"""Real-time asynchronous audio recorder supporting WAV, MP3, and OGG formats."""
from __future__ import annotations

import datetime
import os
import threading
from pathlib import Path
from queue import Empty, Full, Queue

import numpy as np
import soundfile as sf

from .settings import RecordingSettings, VALID_RECORDING_BITRATES, VALID_RECORDING_FORMATS


def default_recordings_directory() -> Path:
    """Return default directory for user recordings."""

    documents = Path.home() / "Documents"
    if not documents.exists():
        documents = Path.home()
    recording_dir = documents / "Mini Mesa de Som" / "Gravações"
    try:
        recording_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        recording_dir = Path.home()
    return recording_dir


def generate_default_filename(fmt: str, now: datetime.datetime | None = None) -> str:
    """Generate automatic filename based on date and time."""

    now = now or datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    ext = fmt.lower().lstrip(".")
    return f"Gravação {timestamp}.{ext}"


class _PyAVAudioWriter:
    """Audio file writer using PyAV for MP3 encoding."""

    def __init__(
        self,
        filepath: str | Path,
        sample_rate: int,
        channels: int,
        codec_name: str,
        bitrate_kbps: int,
    ) -> None:
        import av

        self._av = av
        self.container = av.open(str(filepath), mode="w")
        self.stream = self.container.add_stream(codec_name, rate=sample_rate)
        if bitrate_kbps > 0:
            self.stream.bit_rate = bitrate_kbps * 1000
        self.stream.format = "fltp"
        self.stream.layout = "stereo" if channels == 2 else "mono"
        self.sample_rate = sample_rate
        self.channels = channels

    def write(self, data: np.ndarray) -> None:
        if data.size == 0:
            return
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        data_t = np.ascontiguousarray(data.T, dtype=np.float32)
        layout = "stereo" if self.channels == 2 else "mono"
        frame = self._av.AudioFrame.from_ndarray(data_t, format="fltp", layout=layout)
        frame.rate = self.sample_rate
        for packet in self.stream.encode(frame):
            self.container.mux(packet)


    def close(self) -> None:
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()


def _create_audio_writer(
    filepath: Path,
    sample_rate: int,
    channels: int,
    fmt: str,
    bitrate_kbps: int,
):
    fmt = fmt.lower().strip(".")
    if fmt == "wav":
        return sf.SoundFile(
            filepath,
            mode="w",
            samplerate=sample_rate,
            channels=channels,
            format="WAV",
            subtype="PCM_16",
        )
    elif fmt == "ogg":
        return sf.SoundFile(
            filepath,
            mode="w",
            samplerate=sample_rate,
            channels=channels,
            format="OGG",
            subtype="VORBIS",
        )
    elif fmt == "mp3":
        try:
            return _PyAVAudioWriter(
                filepath,
                sample_rate=sample_rate,
                channels=channels,
                codec_name="mp3",
                bitrate_kbps=bitrate_kbps,
            )
        except Exception:
            return sf.SoundFile(
                filepath,
                mode="w",
                samplerate=sample_rate,
                channels=channels,
                format="MP3",
            )
    else:
        raise ValueError(f"Formato de áudio não suportado: {fmt}")


class AudioRecorder:
    """Asynchronous thread-safe recorder for audio streams."""

    def __init__(
        self,
        settings: RecordingSettings,
        sample_rate: int = 48000,
        channels: int = 2,
    ) -> None:
        fmt = settings.format.lower().strip(".")
        if fmt not in VALID_RECORDING_FORMATS:
            fmt = "mp3"
        bitrate = (
            settings.bitrate_kbps
            if settings.bitrate_kbps in VALID_RECORDING_BITRATES
            else 192
        )

        folder = Path(settings.folder) if settings.folder.strip() else default_recordings_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = default_recordings_directory()

        custom_name = settings.custom_filename.strip()
        if custom_name:
            if not custom_name.lower().endswith(f".{fmt}"):
                custom_name = f"{custom_name}.{fmt}"
            filename = custom_name
        else:
            filename = generate_default_filename(fmt)

        self.file_path = folder / filename
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = fmt
        self.bitrate_kbps = bitrate
        self.mode = settings.mode

        # The writer can temporarily be slower than real time (especially when
        # encoding MP3/OGG).  Keep a bounded reserve so it never grows without
        # limit and competes with the capture callback for memory and CPU.
        self._queue: Queue[np.ndarray | None] = Queue(maxsize=192)
        self._recording = False
        self._total_frames = 0
        self._dropped_blocks = 0
        self._error: Exception | None = None

        self._writer = _create_audio_writer(
            self.file_path,
            sample_rate=self.sample_rate,
            channels=self.channels,
            fmt=self.format,
            bitrate_kbps=self.bitrate_kbps,
        )

        self._recording = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="mini-mesa-recorder",
            daemon=True,
        )
        self._thread.start()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed_seconds(self) -> float:
        return float(self._total_frames) / float(self.sample_rate)

    @property
    def dropped_blocks(self) -> int:
        return self._dropped_blocks

    def push(self, data: np.ndarray) -> None:
        if not self._recording or data is None or data.size == 0:
            return
        try:
            # InputStream reuses its input memory after the callback returns,
            # so the copy must happen here.  Crucially, do it only if there is
            # room; allocating when the writer is already behind risks making
            # the live process capture underflow too.
            if self._queue.full():
                self._dropped_blocks += 1
                return
            self._queue.put_nowait(np.copy(data))
        except Full:
            self._dropped_blocks += 1

    def _worker_loop(self) -> None:
        pending_chunks: list[np.ndarray] = []
        pending_frames = 0
        min_batch_frames = 4096  # ~85ms batching to prevent GIL lock contention with real-time audio threads

        def _flush_pending() -> None:
            nonlocal pending_chunks, pending_frames
            if not pending_chunks:
                return
            if len(pending_chunks) == 1:
                batch = pending_chunks[0]
            else:
                batch = np.vstack(pending_chunks)
            pending_chunks.clear()
            pending_frames = 0
            try:
                self._writer.write(batch)
                frames = batch.shape[0] if batch.ndim > 0 else 0
                self._total_frames += frames
            except Exception as exc:
                self._error = exc

        while True:
            try:
                chunk = self._queue.get(timeout=0.05)
            except Empty:
                _flush_pending()
                if not self._recording:
                    break
                continue

            if chunk is None:
                _flush_pending()
                break

            pending_chunks.append(chunk)
            pending_frames += chunk.shape[0] if chunk.ndim > 0 else 0
            if pending_frames >= min_batch_frames:
                _flush_pending()

        _flush_pending()


    def stop(self, timeout: float = 3.0) -> tuple[Path, float]:
        if not self._recording:
            return self.file_path, self.elapsed_seconds
        self._recording = False
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        try:
            self._writer.close()
        except Exception:
            pass
        return self.file_path, self.elapsed_seconds
