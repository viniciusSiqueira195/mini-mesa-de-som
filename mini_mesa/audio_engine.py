from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Sequence
from typing import Protocol

from .settings import ReverbSettings


class AudioDependencyError(RuntimeError):
    """Raised when the native audio backend cannot be imported."""


class AudioStream(Protocol):
    def run(self) -> None: ...

    def close(self) -> None: ...


class AudioBackend(Protocol):
    def input_devices(self) -> Sequence[str]: ...

    def output_devices(self) -> Sequence[str]: ...

    def create_stream(
        self,
        input_device: str,
        output_device: str,
        settings: ReverbSettings,
    ) -> AudioStream: ...

    def update_reverb(self, settings: ReverbSettings) -> None: ...


class PedalboardBackend:
    """PortAudio routing with native DSP powered by Spotify's Pedalboard."""

    def __init__(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from pedalboard import Limiter, Pedalboard, Reverb
        except ImportError as exc:
            raise AudioDependencyError(
                "O motor de áudio não está instalado. "
                "Execute: python -m pip install -e ."
            ) from exc

        self._np = np
        self._sd = sd
        self._Limiter = Limiter
        self._Pedalboard = Pedalboard
        self._Reverb = Reverb
        self._reverb = None
        self._effects = None
        self._sample_rate = 48_000.0
        self._input_ids: dict[str, tuple[int, str]] = {}
        self._output_ids: dict[str, tuple[int, str]] = {}

    def input_devices(self) -> Sequence[str]:
        self._refresh_devices()
        return tuple(self._input_ids)

    def output_devices(self) -> Sequence[str]:
        self._refresh_devices()
        return tuple(self._output_ids)

    def _refresh_devices(self) -> None:
        devices = self._sd.query_devices()
        host_apis = self._sd.query_hostapis()
        input_ids: dict[str, tuple[int, str]] = {}
        output_ids: dict[str, tuple[int, str]] = {}
        ranks = {
            "Windows WDM-KS": 0,
            "Windows WASAPI": 1,
            "Windows DirectSound": 2,
            "MME": 3,
        }

        for device_id, device in enumerate(devices):
            host_name = host_apis[device["hostapi"]]["name"]
            label = device["name"]
            if device["max_input_channels"] > 0:
                current = input_ids.get(label)
                if current is None or ranks.get(host_name, 99) < ranks.get(current[1], 99):
                    input_ids[label] = (device_id, host_name)
            if device["max_output_channels"] > 0:
                current = output_ids.get(label)
                if current is None or ranks.get(host_name, 99) < ranks.get(current[1], 99):
                    output_ids[label] = (device_id, host_name)

        self._input_ids = dict(
            sorted(
                input_ids.items(),
                key=lambda item: (ranks.get(item[1][1], 99), item[0].casefold()),
            )
        )
        self._output_ids = dict(
            sorted(
                output_ids.items(),
                key=lambda item: (ranks.get(item[1][1], 99), item[0].casefold()),
            )
        )

    def create_stream(
        self,
        input_device: str,
        output_device: str,
        settings: ReverbSettings,
    ) -> AudioStream:
        if input_device not in self._input_ids or output_device not in self._output_ids:
            self._refresh_devices()
        try:
            input_id, _input_api = self._input_ids[input_device]
            output_id, _output_api = self._output_ids[output_device]
        except KeyError as exc:
            raise ValueError(
                "O dispositivo selecionado não está mais disponível. "
                "Atualize a lista de dispositivos."
            ) from exc
        input_info = self._sd.query_devices(input_id)
        output_info = self._sd.query_devices(output_id)
        input_channels = min(2, int(input_info["max_input_channels"]))
        output_channels = min(2, int(output_info["max_output_channels"]))
        self._sample_rate = self._find_common_sample_rate(
            input_id,
            output_id,
            input_channels,
            output_channels,
            float(input_info["default_samplerate"]),
            float(output_info["default_samplerate"]),
        )

        reverb = self._Reverb(
            room_size=settings.room_size,
            damping=settings.damping,
            wet_level=settings.wet_level,
            dry_level=1.0,
            width=1.0,
        )
        self._effects = self._Pedalboard(
            [
                reverb,
                self._Limiter(threshold_db=-1.0, release_ms=100.0),
            ]
        )
        stream = _SplitSoundDeviceStream(
            sounddevice=self._sd,
            numpy=self._np,
            input_id=input_id,
            output_id=output_id,
            sample_rate=self._sample_rate,
            input_channels=input_channels,
            output_channels=output_channels,
            processor=self._process_audio,
        )
        self._reverb = reverb
        return stream

    def _find_common_sample_rate(
        self,
        input_id: int,
        output_id: int,
        input_channels: int,
        output_channels: int,
        input_default: float,
        output_default: float,
    ) -> float:
        candidates = [input_default, output_default, 48_000.0, 44_100.0]
        tried: set[float] = set()
        for sample_rate in candidates:
            if sample_rate in tried:
                continue
            tried.add(sample_rate)
            try:
                self._sd.check_input_settings(
                    device=input_id,
                    channels=input_channels,
                    dtype="float32",
                    samplerate=sample_rate,
                )
                self._sd.check_output_settings(
                    device=output_id,
                    channels=output_channels,
                    dtype="float32",
                    samplerate=sample_rate,
                )
            except self._sd.PortAudioError:
                continue
            return sample_rate
        raise ValueError(
            "Não foi encontrada uma taxa de amostragem comum entre a entrada e a saída."
        )

    def _process_audio(self, indata, frames: int, output_channels: int):
        output = self._np.zeros((frames, output_channels), dtype=self._np.float32)
        if self._effects is None:
            return output

        mono_input = self._np.mean(indata, axis=1, dtype=self._np.float32)
        processed = self._effects.process(
            mono_input[self._np.newaxis, :],
            self._sample_rate,
            buffer_size=frames,
            reset=False,
        )
        if processed.ndim == 1:
            mono = processed
        else:
            mono = processed[0]
        available = min(frames, mono.shape[0])
        output[:available, :] = mono[:available, self._np.newaxis]
        return output

    def update_reverb(self, settings: ReverbSettings) -> None:
        if self._reverb is None:
            return
        self._reverb.room_size = settings.room_size
        self._reverb.damping = settings.damping
        self._reverb.wet_level = settings.wet_level


class _SplitSoundDeviceStream:
    """Bridge two independent audio devices through a small bounded buffer."""

    def __init__(
        self,
        *,
        sounddevice,
        numpy,
        input_id: int,
        output_id: int,
        sample_rate: float,
        input_channels: int,
        output_channels: int,
        processor: Callable,
    ) -> None:
        self._sd = sounddevice
        self._np = numpy
        self._processor = processor
        self._output_channels = output_channels
        self._block_size = 512
        self._chunks = deque()
        self._head_offset = 0
        self._queued_frames = 0
        self._max_queued_frames = self._block_size * 12
        self._queue_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._error: Exception | None = None
        self._input = sounddevice.InputStream(
            device=input_id,
            samplerate=sample_rate,
            blocksize=self._block_size,
            channels=input_channels,
            dtype="float32",
            latency="low",
            callback=self._on_input,
        )
        try:
            self._output = sounddevice.OutputStream(
                device=output_id,
                samplerate=sample_rate,
                blocksize=self._block_size,
                channels=output_channels,
                dtype="float32",
                latency="low",
                callback=self._on_output,
            )
        except Exception:
            self._input.close()
            raise

    def run(self) -> None:
        try:
            self._input.start()
            self._output.start()
            while (
                self._input.active
                and self._output.active
                and not self._stop_event.wait(0.1)
            ):
                pass
        finally:
            self._close_streams()
        if self._error is not None:
            raise RuntimeError(str(self._error)) from self._error

    def close(self) -> None:
        self._stop_event.set()
        self._close_streams()

    def _on_input(self, indata, frames, _time_info, _status) -> None:
        try:
            processed = self._processor(indata, frames, self._output_channels)
        except Exception as exc:
            self._error = exc
            self._stop_event.set()
            raise self._sd.CallbackAbort

        with self._queue_lock:
            self._chunks.append(processed)
            self._queued_frames += processed.shape[0]
            while self._queued_frames > self._max_queued_frames and self._chunks:
                removed = self._chunks.popleft()
                self._queued_frames -= removed.shape[0] - self._head_offset
                self._head_offset = 0

    def _on_output(self, outdata, frames, _time_info, _status) -> None:
        outdata.fill(0)
        written = 0
        with self._queue_lock:
            while written < frames and self._chunks:
                chunk = self._chunks[0]
                available = chunk.shape[0] - self._head_offset
                count = min(frames - written, available)
                outdata[written : written + count] = chunk[
                    self._head_offset : self._head_offset + count
                ]
                written += count
                self._head_offset += count
                self._queued_frames -= count
                if self._head_offset == chunk.shape[0]:
                    self._chunks.popleft()
                    self._head_offset = 0

    def _close_streams(self) -> None:
        for stream in (self._input, self._output):
            try:
                if not stream.closed:
                    stream.abort()
                    stream.close()
            except Exception:
                pass


class AudioEngine:
    """Coordinates one live audio stream without depending on the UI toolkit."""

    def __init__(
        self,
        backend: AudioBackend | None = None,
        *,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._backend = backend or PedalboardBackend()
        self._on_error = on_error
        self._settings = ReverbSettings()
        self._stream: AudioStream | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._lock = threading.RLock()

    @property
    def settings(self) -> ReverbSettings:
        with self._lock:
            return self._settings

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._stream is not None

    def input_devices(self) -> tuple[str, ...]:
        return tuple(self._backend.input_devices())

    def output_devices(self) -> tuple[str, ...]:
        return tuple(self._backend.output_devices())

    def update_settings(self, settings: ReverbSettings) -> None:
        with self._lock:
            self._settings = settings
            if self._stream is not None:
                self._backend.update_reverb(settings)

    def set_error_handler(self, handler: Callable[[str], None] | None) -> None:
        with self._lock:
            self._on_error = handler

    def start(self, input_device: str, output_device: str) -> None:
        input_device = input_device.strip()
        output_device = output_device.strip()
        if not input_device:
            raise ValueError("Selecione um microfone de entrada.")
        if not output_device:
            raise ValueError("Selecione uma saída virtual.")
        if input_device == output_device:
            raise ValueError(
                "A entrada e a saída não podem ser o mesmo dispositivo; "
                "isso causaria microfonia."
            )

        with self._lock:
            if self._stream is not None:
                raise RuntimeError("O processamento de áudio já está ativo.")
            stream = self._backend.create_stream(
                input_device,
                output_device,
                self._settings,
            )
            self._stream = stream
            self._stopping = False
            thread = threading.Thread(
                target=self._run_stream,
                args=(stream,),
                name="mini-mesa-audio",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            stream = self._stream
            thread = self._thread
            if stream is None:
                return
            self._stopping = True

        try:
            stream.close()
        finally:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=timeout)
            with self._lock:
                if self._stream is stream:
                    self._stream = None
                    self._thread = None
                self._stopping = False

    def _run_stream(self, stream: AudioStream) -> None:
        error: Exception | None = None
        try:
            stream.run()
        except Exception as exc:  # Native audio errors must reach the UI safely.
            error = exc
        finally:
            with self._lock:
                expected_stop = self._stopping
                if self._stream is stream:
                    self._stream = None
                    self._thread = None

        if error is not None and not expected_stop and self._on_error is not None:
            self._on_error(str(error))
