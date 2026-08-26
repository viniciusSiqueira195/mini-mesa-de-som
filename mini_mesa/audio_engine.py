from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Callable, Sequence
from itertools import product
from typing import Protocol

from .settings import ReverbSettings


_HOST_API_RANKS = {
    "Windows WDM-KS": 0,
    "Windows WASAPI": 1,
    "Windows DirectSound": 2,
    "MME": 3,
}
_MONITOR_API_RANKS = {
    "Windows WASAPI": 0,
    "Windows DirectSound": 1,
    "MME": 2,
}
_DEVICE_INSTANCE_PREFIX = re.compile(r"\((?:\d+\s*-\s*)")


def _normalize_device_label(label: str) -> str:
    """Collapse Windows instance prefixes such as ``(5- USB Audio Device)``."""

    compact = " ".join(label.split())
    return _DEVICE_INSTANCE_PREFIX.sub("(", compact)


class AudioDependencyError(RuntimeError):
    """Raised when the native audio backend cannot be imported."""


class AudioStream(Protocol):
    def run(self) -> None: ...

    def close(self) -> None: ...


class AudioBackend(Protocol):
    def input_devices(self) -> Sequence[str]: ...

    def output_devices(self) -> Sequence[str]: ...

    def monitor_devices(self) -> Sequence[str]: ...

    def create_stream(
        self,
        input_device: str,
        output_device: str,
        settings: ReverbSettings,
        monitor_output: str | None = None,
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
        self._input_ids: dict[str, list[tuple[int, str]]] = {}
        self._output_ids: dict[str, list[tuple[int, str]]] = {}

    def input_devices(self) -> Sequence[str]:
        self._refresh_devices()
        return tuple(self._input_ids)

    def output_devices(self) -> Sequence[str]:
        self._refresh_devices()
        return tuple(self._output_ids)

    def monitor_devices(self) -> Sequence[str]:
        self._refresh_devices()
        physical_outputs = [
            (label, candidates)
            for label, candidates in self._output_ids.items()
            if "virtual" not in label.casefold()
            and any(api in _MONITOR_API_RANKS for _device_id, api in candidates)
        ]
        wasapi_outputs = [
            label
            for label, candidates in physical_outputs
            if any(api == "Windows WASAPI" for _device_id, api in candidates)
        ]
        if wasapi_outputs:
            return tuple(wasapi_outputs)
        return tuple(label for label, _candidates in physical_outputs)

    def _refresh_devices(self) -> None:
        devices = self._sd.query_devices()
        host_apis = self._sd.query_hostapis()
        input_ids: dict[str, list[tuple[int, str]]] = {}
        output_ids: dict[str, list[tuple[int, str]]] = {}

        for device_id, device in enumerate(devices):
            host_name = host_apis[device["hostapi"]]["name"]
            label = _normalize_device_label(device["name"])
            if device["max_input_channels"] > 0:
                input_ids.setdefault(label, []).append((device_id, host_name))
            if device["max_output_channels"] > 0:
                output_ids.setdefault(label, []).append((device_id, host_name))

        for candidates in (*input_ids.values(), *output_ids.values()):
            candidates.sort(key=lambda candidate: _HOST_API_RANKS.get(candidate[1], 99))

        self._input_ids = dict(
            sorted(
                input_ids.items(),
                key=lambda item: (
                    _HOST_API_RANKS.get(item[1][0][1], 99),
                    item[0].casefold(),
                ),
            )
        )
        self._output_ids = dict(
            sorted(
                output_ids.items(),
                key=lambda item: (
                    _HOST_API_RANKS.get(item[1][0][1], 99),
                    item[0].casefold(),
                ),
            )
        )

    def create_stream(
        self,
        input_device: str,
        output_device: str,
        settings: ReverbSettings,
        monitor_output: str | None = None,
    ) -> AudioStream:
        if (
            input_device not in self._input_ids
            or output_device not in self._output_ids
            or (monitor_output is not None and monitor_output not in self._output_ids)
        ):
            self._refresh_devices()
        try:
            input_candidates = self._input_ids[input_device]
            output_candidates = self._output_ids[output_device]
            monitor_candidates = (
                sorted(
                    (
                        candidate
                        for candidate in self._output_ids[monitor_output]
                        if candidate[1] in _MONITOR_API_RANKS
                    ),
                    key=lambda candidate: _MONITOR_API_RANKS[candidate[1]],
                )
                if monitor_output is not None
                else [(None, "")]
            )
        except KeyError as exc:
            raise ValueError(
                "O dispositivo selecionado não está mais disponível. "
                "Atualize a lista de dispositivos."
            ) from exc

        reverb = self._Reverb(
            room_size=settings.room_size,
            damping=settings.damping,
            wet_level=settings.wet_level,
            dry_level=settings.dry_level,
            width=1.0,
        )
        self._effects = self._Pedalboard(
            [
                reverb,
                self._Limiter(threshold_db=-1.0, release_ms=100.0),
            ]
        )
        last_error: Exception | None = None
        combinations = product(input_candidates, output_candidates, monitor_candidates)
        for input_candidate, output_candidate, monitor_candidate in combinations:
            input_id, _input_api = input_candidate
            output_id, _output_api = output_candidate
            monitor_id, _monitor_api = monitor_candidate
            try:
                input_info = self._sd.query_devices(input_id)
                input_channels = min(2, int(input_info["max_input_channels"]))
                output_specs: list[tuple[int, int, float]] = []
                for device_id in (output_id, monitor_id):
                    if device_id is None:
                        continue
                    device_info = self._sd.query_devices(device_id)
                    output_specs.append(
                        (
                            device_id,
                            min(2, int(device_info["max_output_channels"])),
                            float(device_info["default_samplerate"]),
                        )
                    )
                sample_rate = self._find_common_sample_rate(
                    input_id,
                    input_channels,
                    float(input_info["default_samplerate"]),
                    output_specs,
                )
                block_sizes = (
                    (256, 512) if monitor_output is not None else (512, 256)
                )
                for block_size in block_sizes:
                    stream = None
                    try:
                        stream = _MultiOutputSoundDeviceStream(
                            sounddevice=self._sd,
                            input_id=input_id,
                            outputs=[(item[0], item[1]) for item in output_specs],
                            sample_rate=sample_rate,
                            input_channels=input_channels,
                            block_size=block_size,
                            processor=self._process_audio,
                        )
                        if monitor_output is not None:
                            stream.validate_start()
                    except Exception as exc:
                        if stream is not None:
                            stream.close()
                        last_error = exc
                        continue

                    self._sample_rate = sample_rate
                    self._reverb = reverb
                    return stream
            except Exception as exc:
                last_error = exc
                continue

        self._effects = None
        details = f" Detalhes técnicos: {last_error}" if last_error else ""
        raise RuntimeError(
            f"Não foi possível abrir o microfone '{input_device}' com a saída "
            f"'{output_device}'. Atualize os dispositivos ou escolha outra entrada. "
            "Se o retorno estiver marcado, tente também outra saída de retorno."
            f"{details}"
        )

    def _find_common_sample_rate(
        self,
        input_id: int,
        input_channels: int,
        input_default: float,
        output_specs: Sequence[tuple[int, int, float]],
    ) -> float:
        candidates = [
            input_default,
            *(item[2] for item in output_specs),
            48_000.0,
            44_100.0,
        ]
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
                for output_id, output_channels, _default_rate in output_specs:
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

    def _process_audio(self, indata, frames: int):
        output = self._np.zeros(frames, dtype=self._np.float32)
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
        output[:available] = mono[:available]
        return output

    def update_reverb(self, settings: ReverbSettings) -> None:
        if self._reverb is None:
            return
        self._reverb.room_size = settings.room_size
        self._reverb.damping = settings.damping
        self._reverb.wet_level = settings.wet_level
        self._reverb.dry_level = settings.dry_level


class _BufferedAudioOutput:
    """Feed one output device while keeping queued latency strictly bounded."""

    def __init__(
        self,
        *,
        sounddevice,
        output_id: int,
        sample_rate: float,
        output_channels: int,
        block_size: int,
    ) -> None:
        self._sd = sounddevice
        self._block_size = block_size
        self._chunks = deque()
        self._head_offset = 0
        self._queued_frames = 0
        self._max_queued_frames = self._block_size * 4
        self._queue_lock = threading.Lock()
        self._last_sample = 0.0
        self._underrun = True
        self._needs_crossfade = False
        self._underrun_count = 0
        self._dropped_block_count = 0
        self.stream = sounddevice.OutputStream(
            device=output_id,
            samplerate=sample_rate,
            blocksize=self._block_size,
            channels=output_channels,
            dtype="float32",
            latency="low",
            callback=self._on_output,
        )

    def push(self, processed) -> None:
        with self._queue_lock:
            self._chunks.append(processed)
            self._queued_frames += processed.shape[0]
            while self._queued_frames > self._max_queued_frames and self._chunks:
                removed = self._chunks.popleft()
                self._queued_frames -= removed.shape[0] - self._head_offset
                self._head_offset = 0
                self._needs_crossfade = True
                self._dropped_block_count += 1

    def clear(self) -> None:
        with self._queue_lock:
            self._chunks.clear()
            self._head_offset = 0
            self._queued_frames = 0
            self._last_sample = 0.0
            self._underrun = True
            self._needs_crossfade = False

    def _on_output(self, outdata, frames, _time_info, _status) -> None:
        outdata.fill(0)
        written = 0
        with self._queue_lock:
            if _status:
                self._needs_crossfade = True
            while written < frames and self._chunks:
                chunk = self._chunks[0]
                available = chunk.shape[0] - self._head_offset
                count = min(frames - written, available)
                mono = chunk[self._head_offset : self._head_offset + count]
                outdata[written : written + count, :] = mono[:, None]
                if self._underrun or self._needs_crossfade:
                    fade_from = 0.0 if self._underrun else self._last_sample
                    fade_frames = min(32, count)
                    for index in range(fade_frames):
                        amount = (index + 1) / fade_frames
                        sample = fade_from * (1.0 - amount) + float(mono[index]) * amount
                        outdata[written + index, :] = sample
                    self._underrun = False
                    self._needs_crossfade = False
                written += count
                self._head_offset += count
                self._queued_frames -= count
                self._last_sample = float(mono[-1])
                if self._head_offset == chunk.shape[0]:
                    self._chunks.popleft()
                    self._head_offset = 0

            if written < frames:
                missing_frames = frames - written
                fade_frames = min(32, missing_frames)
                for index in range(fade_frames):
                    amount = (index + 1) / fade_frames
                    outdata[written + index, :] = self._last_sample * (1.0 - amount)
                self._last_sample = 0.0
                if not self._underrun:
                    self._underrun_count += 1
                self._underrun = True


class _MultiOutputSoundDeviceStream:
    """Process one microphone once and feed the virtual cable plus monitoring."""

    def __init__(
        self,
        *,
        sounddevice,
        input_id: int,
        outputs: Sequence[tuple[int, int]],
        sample_rate: float,
        input_channels: int,
        block_size: int,
        processor: Callable,
    ) -> None:
        self._sd = sounddevice
        self._processor = processor
        self._stop_event = threading.Event()
        self._first_audio = threading.Event()
        self._captured_blocks = 0
        self._prefill_blocks = 2
        self._error: Exception | None = None
        self._validating = False
        self._outputs: list[_BufferedAudioOutput] = []
        self._input = sounddevice.InputStream(
            device=input_id,
            samplerate=sample_rate,
            blocksize=block_size,
            channels=input_channels,
            dtype="float32",
            latency="low",
            callback=self._on_input,
        )
        try:
            for output_id, output_channels in outputs:
                self._outputs.append(
                    _BufferedAudioOutput(
                        sounddevice=sounddevice,
                        output_id=output_id,
                        sample_rate=sample_rate,
                        output_channels=output_channels,
                        block_size=block_size,
                    )
                )
        except Exception:
            self._close_streams()
            raise

    def validate_start(self) -> None:
        """Start every device with silence so failing APIs can be skipped."""

        self._validating = True
        try:
            self._input.start()
            for output in self._outputs:
                output.stream.start()
        finally:
            self._abort_streams()
            for output in self._outputs:
                output.clear()
            self._first_audio.clear()
            self._captured_blocks = 0
            self._validating = False

    def run(self) -> None:
        try:
            self._input.start()
            self._first_audio.wait(timeout=0.15)
            for output in self._outputs:
                output.stream.start()
            while (
                self._input.active
                and all(output.stream.active for output in self._outputs)
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
        if self._validating:
            return
        try:
            processed = self._processor(indata, frames)
        except Exception as exc:
            self._error = exc
            self._stop_event.set()
            raise self._sd.CallbackAbort

        for output in self._outputs:
            output.push(processed)
        self._captured_blocks += 1
        if self._captured_blocks >= self._prefill_blocks:
            self._first_audio.set()

    def _close_streams(self) -> None:
        streams = [self._input, *(output.stream for output in self._outputs)]
        for stream in streams:
            try:
                if not stream.closed:
                    stream.abort()
                    stream.close()
            except Exception:
                pass

    def _abort_streams(self) -> None:
        streams = [self._input, *(output.stream for output in self._outputs)]
        for stream in streams:
            try:
                if stream.active:
                    stream.abort()
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

    def monitor_devices(self) -> tuple[str, ...]:
        return tuple(self._backend.monitor_devices())

    def update_settings(self, settings: ReverbSettings) -> None:
        with self._lock:
            self._settings = settings
            if self._stream is not None:
                self._backend.update_reverb(settings)

    def set_error_handler(self, handler: Callable[[str], None] | None) -> None:
        with self._lock:
            self._on_error = handler

    def start(
        self,
        input_device: str,
        output_device: str,
        monitor_output: str | None = None,
    ) -> None:
        input_device = input_device.strip()
        output_device = output_device.strip()
        monitor_output = monitor_output.strip() if monitor_output else None
        if not input_device:
            raise ValueError("Selecione um microfone de entrada.")
        if not output_device:
            raise ValueError("Selecione uma saída virtual.")
        if input_device == output_device:
            raise ValueError(
                "A entrada e a saída não podem ser o mesmo dispositivo; "
                "isso causaria microfonia."
            )
        if monitor_output == output_device:
            raise ValueError(
                "A saída de retorno deve ser diferente da saída virtual."
            )
        if monitor_output == input_device:
            raise ValueError(
                "O retorno não pode usar o mesmo dispositivo de entrada."
            )

        with self._lock:
            if self._stream is not None:
                raise RuntimeError("O processamento de áudio já está ativo.")
            stream = self._backend.create_stream(
                input_device,
                output_device,
                self._settings,
                monitor_output,
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
