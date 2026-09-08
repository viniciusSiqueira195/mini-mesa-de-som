from __future__ import annotations

import re
import threading
from dataclasses import replace
from collections import deque
from collections.abc import Callable, Sequence
from itertools import product
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Protocol

from .noise_reduction import RNNOISE_SAMPLE_RATE, RNNoiseReducer
from .settings import (
    CreativeEffectSettings,
    ProAudioSettings,
    ReverbSettings,
    SoundboardSettings,
    SpatialSettings,
    VoiceSettings,
)
from .soundboard import (
    SoundboardManager,
    SoundEffectInfo,
    _read_custom_audio,
    _resample,
)
from .spatial_audio import HRTFSpatializer


_HOST_API_RANKS = {
    "Windows WASAPI": 0,
    "Windows WDM-KS": 1,
    "Windows DirectSound": 2,
    "MME": 3,
}
_MONITOR_API_RANKS = {
    "Windows WASAPI": 0,
    "Windows DirectSound": 1,
    "MME": 2,
}
_DEVICE_INSTANCE_PREFIX = re.compile(r"\((?:\d+\s*-\s*)")
_VAC_LINE_OUT = re.compile(r"^Line Out \(Virtual Cable (\d+)\)$", re.IGNORECASE)
_VAC_LINE_INPUT = re.compile(
    r"^Line \d+ \(Virtual Cable (\d+)\)$",
    re.IGNORECASE,
)
_WINDOWS_DEFAULT_ALIASES = (
    "driver de captura de som primário",
    "driver de som primário",
    "mapeador de som da microsoft",
    "microsoft sound mapper",
    "primary sound capture driver",
    "primary sound driver",
)


def _stream_block_sizes(monitor_enabled: bool) -> tuple[int, ...]:
    """Return callback sizes with enough DSP time when monitoring is active."""

    # A 256-frame callback at 48 kHz gives the whole effects chain only 5.3 ms.
    # Opening a second, independently clocked output makes that deadline too
    # fragile on Windows.  Start at 512 frames and retain a 1024-frame fallback
    # for machines or effects that need a wider real-time processing margin.
    return (512, 1024) if monitor_enabled else (512, 256)


def _normalize_device_label(label: str) -> str:
    """Collapse Windows instance prefixes such as ``(5- USB Audio Device)``."""

    compact = " ".join(label.split())
    normalized = _DEVICE_INSTANCE_PREFIX.sub("(", compact)
    virtual_line = _VAC_LINE_INPUT.fullmatch(normalized)
    if virtual_line is not None:
        return f"Line {virtual_line.group(1)} (Virtual Audio Cable)"
    return normalized


def _normalize_output_device_label(label: str) -> str:
    """Group the WDM-KS and WASAPI names of Virtual Audio Cable outputs."""

    normalized = _normalize_device_label(label)
    match = _VAC_LINE_OUT.fullmatch(normalized)
    if match is not None:
        return f"Line {match.group(1)} (Virtual Audio Cable)"
    return normalized


def _resolve_device_label(
    requested: str,
    available: Sequence[str],
    *,
    output: bool = False,
) -> str:
    """Resolve a saved label after Windows renames or renumbers an endpoint."""

    normalize = _normalize_output_device_label if output else _normalize_device_label
    requested_key = normalize(requested).casefold()
    for label in available:
        if normalize(label).casefold() == requested_key:
            return label
    raise KeyError(requested)


def match_device_label(
    requested: str,
    available: Sequence[str],
    *,
    output: bool = False,
) -> str | None:
    """Return the current label matching a possibly old saved preference."""

    if not requested:
        return None
    try:
        return _resolve_device_label(requested, available, output=output)
    except KeyError:
        return None


def _is_windows_default_alias(label: str) -> bool:
    """Identify generic Windows aliases that duplicate the default endpoint."""

    return label.casefold().startswith(_WINDOWS_DEFAULT_ALIASES)


def _merge_mme_truncated_labels(
    devices: dict[str, list[tuple[int, str]]],
) -> None:
    """Merge 31-character MME labels into their complete API counterpart."""

    for truncated in tuple(devices):
        candidates = devices.get(truncated)
        if candidates is None or not any(api == "MME" for _id, api in candidates):
            continue
        matches = [
            label
            for label in devices
            if label != truncated
            and len(label) > len(truncated)
            and label.casefold().startswith(truncated.casefold())
        ]
        if len(matches) != 1:
            continue
        complete = matches[0]
        devices[complete].extend(devices.pop(truncated))


class AudioDependencyError(RuntimeError):
    """Raised when the native audio backend cannot be imported."""


class _StreamingPitchShifter:
    """Adapt a window-based pitch plugin to fixed real-time audio blocks."""

    def __init__(
        self,
        numpy_module,
        processor,
        sample_rate: float,
        window_size: int = 4096,
        overlap: int = 1024,
        synchronous: bool = False,
    ) -> None:
        if overlap <= 0 or overlap >= window_size:
            raise ValueError("A sobreposição deve ser menor que a janela de pitch.")
        self._np = numpy_module
        self._processor = processor
        self._sample_rate = sample_rate
        self._window_size = window_size
        self._overlap = overlap
        self._hop_size = window_size - overlap
        self._synchronous = synchronous
        self._input = numpy_module.empty(0, dtype=numpy_module.float32)
        self._output = numpy_module.empty(0, dtype=numpy_module.float32)
        if synchronous:
            # A fixed analysis delay guarantees enough samples for every
            # callback, including block sizes that do not divide the hop.
            self._output = numpy_module.zeros(window_size, dtype=numpy_module.float32)
        self._pending_tail = None
        self._output_lock = threading.Lock()
        self._error: Exception | None = None
        self._jobs: Queue = Queue(maxsize=3)
        self._stopped = threading.Event()
        phase = numpy_module.linspace(
            0.0, numpy_module.pi / 2.0, overlap, endpoint=True
        )
        self._fade_in = numpy_module.sin(phase).astype(numpy_module.float32) ** 2
        self._fade_out = 1.0 - self._fade_in
        self._worker = threading.Thread(target=self._run, daemon=True)
        if not synchronous:
            self._worker.start()

    def process(self, samples):
        with self._output_lock:
            error = self._error
        if error is not None:
            raise RuntimeError("O modificador de voz foi interrompido.") from error
        samples = self._np.asarray(samples, dtype=self._np.float32).reshape(-1)
        self._input = self._np.concatenate((self._input, samples))

        while self._input.size >= self._window_size:
            window = self._input[: self._window_size].copy()
            if self._synchronous:
                self._output = self._np.concatenate((self._output, self._render_window(window)))
            else:
                try:
                    self._jobs.put_nowait(window)
                except Full:
                    pass
            self._input = self._input[self._hop_size :]

        output = self._np.zeros(samples.size, dtype=self._np.float32)
        with self._output_lock:
            available = min(samples.size, self._output.size)
            if available:
                output[:available] = self._output[:available]
                self._output = self._output[available:]
        return output

    def close(self, *, timeout: float = 0.0) -> None:
        self._stopped.set()
        while True:
            try:
                self._jobs.get_nowait()
            except Empty:
                break
        try:
            self._jobs.put_nowait(None)
        except Full:
            pass
        if not self._synchronous and timeout > 0.0 and self._worker is not threading.current_thread():
            self._worker.join(timeout=timeout)

    def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                window = self._jobs.get()
                if window is None or self._stopped.is_set():
                    return
                produced = self._render_window(window)
                if not self._stopped.is_set():
                    with self._output_lock:
                        self._output = self._np.concatenate((self._output, produced))
        except Exception as exc:
            with self._output_lock:
                self._error = exc

    def _render_window(self, window):
        shifted = self._processor.process(
            window[self._np.newaxis, :], self._sample_rate,
            buffer_size=self._window_size, reset=True,
        )
        shifted = self._np.asarray(shifted, dtype=self._np.float32).reshape(-1)
        if self._pending_tail is None:
            produced = shifted[:self._hop_size]
        else:
            crossfade = (self._pending_tail * self._fade_out
                         + shifted[:self._overlap] * self._fade_in)
            produced = self._np.concatenate((crossfade, shifted[self._overlap:self._hop_size]))
        self._pending_tail = shifted[self._hop_size:].copy()
        return produced


class _MixedPitchProcessor:
    def __init__(self, numpy_module, processor, dry: float, wet: float) -> None:
        self._np = numpy_module
        self._processor = processor
        self._dry = dry
        self._wet = wet

    def process(self, samples, sample_rate, **kwargs):
        shifted = self._processor.process(samples, sample_rate, **kwargs)
        return self._dry * self._np.asarray(samples) + self._wet * shifted


class _SmoothEqualizer:
    """Keep filter history alive and ramp gain changes over 20 milliseconds."""

    def __init__(self, numpy_module, pedalboard_factory, filters):
        self._np = numpy_module
        self._filters = tuple(filters)
        self._board = pedalboard_factory(filters)
        self._gains = (0.0, 0.0, 0.0)
        self._target = self._gains
        self._remaining_seconds = 0.0

    def update(self, settings):
        target = (
            (settings.eq_low_db, settings.eq_mid_db, settings.eq_high_db)
            if settings.eq_enabled else (0.0, 0.0, 0.0)
        )
        if target != self._target:
            self._target = target
            self._remaining_seconds = 0.020

    def process(self, samples, sample_rate, **kwargs):
        # Keep the plugin's preparation size constant during and after ramps.
        kwargs = dict(kwargs, buffer_size=64)
        if not self._remaining_seconds:
            return self._board.process(samples, sample_rate, **kwargs)
        output = self._np.empty_like(samples)
        for start in range(0, samples.shape[-1], 64):
            end = min(start + 64, samples.shape[-1])
            duration = (end - start) / sample_rate
            fraction = min(1.0, duration / self._remaining_seconds) if self._remaining_seconds else 1.0
            self._gains = tuple(
                gain + (target - gain) * fraction
                for gain, target in zip(self._gains, self._target)
            )
            for effect, gain in zip(self._filters, self._gains):
                effect.gain_db = gain
            self._remaining_seconds = max(0.0, self._remaining_seconds - duration)
            block_options = dict(kwargs)
            block_options["reset"] = bool(kwargs.get("reset", False)) and start == 0
            output[..., start:end] = self._board.process(
                samples[..., start:end], sample_rate, **block_options
            )
        return output


class _EffectChain:
    """Keep plugin order while allowing the complete style chain to be mixed."""

    def __init__(
        self,
        numpy_module,
        pedalboard_factory,
        pre_effects,
        style_effects,
        post_effects,
        style_mix: float,
        equalizer=None,
        before_eq_effects=(),
    ) -> None:
        self._np = numpy_module
        self._plugins = tuple((*pre_effects, *style_effects, *before_eq_effects,
                               *(equalizer._filters if equalizer else ()), *post_effects))
        self._before_eq = pedalboard_factory(before_eq_effects) if before_eq_effects else None
        self._equalizer = equalizer
        self._pre = pedalboard_factory(pre_effects) if pre_effects else None
        self._style = pedalboard_factory(style_effects) if style_effects else None
        self._post = pedalboard_factory(post_effects) if post_effects else None
        self._style_mix = style_mix

    def __iter__(self):
        return iter(self._plugins)

    def process(self, samples, sample_rate, **kwargs):
        current = self._np.asarray(samples, dtype=self._np.float32)
        if self._pre is not None:
            current = self._pre.process(current, sample_rate, **kwargs)
        if self._style is not None:
            styled = self._style.process(current, sample_rate, **kwargs)
            if styled.shape[-1] == 0:
                styled = current
            elif styled.shape[-1] != current.shape[-1]:
                old_positions = self._np.linspace(0.0, 1.0, styled.shape[-1])
                new_positions = self._np.linspace(0.0, 1.0, current.shape[-1])
                styled = self._np.vstack(
                    [
                        self._np.interp(new_positions, old_positions, channel)
                        for channel in self._np.atleast_2d(styled)
                    ]
                ).astype(self._np.float32)
            current = current * (1.0 - self._style_mix) + styled * self._style_mix
        if self._before_eq is not None:
            current = self._before_eq.process(current, sample_rate, **kwargs)
        if self._equalizer is not None:
            current = self._equalizer.process(current, sample_rate, **kwargs)
        if self._post is not None:
            current = self._post.process(current, sample_rate, **kwargs)
        return current


class _RealtimeTransform:
    """Low-cost effects that must preserve phase or block history."""

    def __init__(
        self,
        numpy_module,
        sample_rate: float,
        voice_preset: str,
        style_preset: str,
        modulation: str,
        ambience: str = "none",
        style_intensity: float = 0.70,
        modulation_intensity: float = 0.60,
        ambience_intensity: float = 0.50,
        roger_beep: bool = False,
    ) -> None:
        self._np = numpy_module
        self._sample_rate = sample_rate
        self._voice_preset = voice_preset
        self._style_preset = style_preset
        self._modulation = modulation
        self._ambience = ambience
        self._style_mix = style_intensity
        self._modulation_mix = modulation_intensity
        self._ambience_mix = ambience_intensity
        self._roger_beep = roger_beep
        self._phase = 0.0
        self._glitch_counter = 0
        self._glitch_block = None
        self._radio_rng = numpy_module.random.default_rng(0x52414449)
        self._radio_open = False
        self._radio_silence_samples = 0
        self._radio_squelch_samples = 0
        self._radio_start_beep_samples = 0
        self._roger_samples = 0
        self._effect_counter = 0
        self._freeze_block = None
        self._style_last_sample: float | None = None
        self._interference_gain = 1.0
        self._ping_index = 0
        delay_samples = max(1, round(sample_rate * 0.18))
        self._ping_left = numpy_module.zeros(delay_samples, dtype=numpy_module.float32)
        self._ping_right = numpy_module.zeros(delay_samples, dtype=numpy_module.float32)
        self._haas_delay = numpy_module.zeros(
            max(1, round(sample_rate * 0.018)), dtype=numpy_module.float32
        )
        self._haas_index = 0
        self._convolution_history = numpy_module.zeros(1023, dtype=numpy_module.float32)
        self._impulse = self._make_impulse_response(ambience)

    def process_mono(self, samples):
        output = self._np.asarray(samples, dtype=self._np.float32).copy()
        count = output.size
        positions = self._phase + self._np.arange(count, dtype=self._np.float32)

        radio_presets = {
            "telephone": (1.8, 0.006),
            "walkie_police": (2.0, 0.007),
            "walkie_military": (2.3, 0.009),
            "walkie_toy": (2.8, 0.012),
        }
        style_input = output.copy()
        if self._style_preset in radio_presets:
            drive, maximum_hiss = radio_presets[self._style_preset]
            level = float(self._np.sqrt(self._np.mean(output * output)))
            if level >= 0.008:
                if not self._radio_open:
                    self._radio_squelch_samples = round(self._sample_rate * 0.045)
                    if self._roger_beep:
                        self._radio_start_beep_samples = round(
                            self._sample_rate * 0.065
                        )
                self._radio_open = True
                self._radio_silence_samples = 0
            elif self._radio_open:
                self._radio_silence_samples += count
                if self._radio_silence_samples >= self._sample_rate * 0.25:
                    self._radio_open = False
                    if self._roger_beep:
                        self._roger_samples = round(self._sample_rate * 0.10)

            output = self._np.tanh(output * drive) / self._np.tanh(drive)
            if self._radio_open:
                hiss_level = min(maximum_hiss, 0.0015 + level * 0.07)
                output += self._radio_rng.normal(0.0, hiss_level, count).astype(
                    self._np.float32
                )
            if self._radio_squelch_samples > 0:
                burst_count = min(count, self._radio_squelch_samples)
                decay = self._np.linspace(1.0, 0.0, burst_count, dtype=self._np.float32)
                output[:burst_count] += (
                    self._radio_rng.normal(0.0, 0.025, burst_count).astype(
                        self._np.float32
                    )
                    * decay
                )
                self._radio_squelch_samples -= burst_count

        if self._radio_start_beep_samples > 0:
            beep_count = min(count, self._radio_start_beep_samples)
            output[:beep_count] += 0.055 * self._np.sin(
                2.0 * self._np.pi * 880.0 * positions[:beep_count] / self._sample_rate
            )
            self._radio_start_beep_samples -= beep_count

        if self._roger_samples > 0:
            beep_count = min(count, self._roger_samples)
            output[:beep_count] += 0.07 * self._np.sin(
                2.0 * self._np.pi * 1050.0 * positions[:beep_count] / self._sample_rate
            )
            self._roger_samples -= beep_count

        if self._style_preset == "reverse":
            output = 0.35 * output + 0.65 * output[::-1]
        elif self._style_preset in ("glitch", "stutter"):
            if self._glitch_block is None or self._glitch_counter % 6 == 0:
                self._glitch_block = output.copy()
            elif self._glitch_counter % 6 in ((2, 3, 4) if self._style_preset == "stutter" else (3, 4)):
                output = self._glitch_block.copy()
            self._glitch_counter += 1
        elif self._style_preset == "spectral_freeze":
            if (
                self._freeze_block is None
                or self._freeze_block.size != count
                or self._effect_counter % 32 == 0
            ):
                spectrum = self._np.fft.rfft(output)
                self._freeze_block = self._np.fft.irfft(
                    self._np.abs(spectrum) * self._np.exp(1j * self._np.angle(spectrum)),
                    n=count,
                ).astype(self._np.float32)
            output = 0.25 * output + 0.75 * self._freeze_block
        elif self._style_preset == "granular":
            grain = 64
            grains = [output[i : i + grain] for i in range(0, count, grain)]
            output = self._np.concatenate(grains[::2] + grains[1::2])[:count]
            output = self._smooth_internal_boundaries(output, grain, fade_frames=16)
        elif self._style_preset == "tape":
            wow = 0.97 + 0.03 * self._np.sin(
                2.0 * self._np.pi * 0.7 * positions / self._sample_rate
            )
            output = self._np.tanh(output * 1.25) * wow
            output += self._radio_rng.normal(0.0, 0.0012, count)
        elif self._style_preset == "vinyl":
            output += self._radio_rng.normal(0.0, 0.002, count)
            clicks = self._radio_rng.random(count) < 0.0012
            output[clicks] += self._radio_rng.uniform(-0.12, 0.12, int(clicks.sum()))
        elif self._style_preset == "vhs":
            hum = 0.003 * self._np.sin(
                2.0 * self._np.pi * 60.0 * positions / self._sample_rate
            )
            output = self._np.tanh(output * 1.15) + hum
        elif self._style_preset == "radio_interference":
            interference = self._radio_rng.normal(0.0, 0.008, count)
            target_gain = 0.35 if self._effect_counter % 19 in (11, 12) else 1.0
            gain = self._smooth_gain_change(self._interference_gain, target_gain, count)
            self._interference_gain = target_gain
            output = output * gain + interference
        elif self._style_preset == "octave_fuzz":
            output = self._np.tanh((2.0 * self._np.abs(output) - 0.12) * 4.0) * 0.35

        sample_hold_steps = {
            "telephone": 5,
            "walkie_police": 5,
            "walkie_military": 6,
            "walkie_toy": 7,
            "old_radio": 6,
            "arcade": 8,
        }
        hold_step = sample_hold_steps.get(self._style_preset)
        if hold_step is not None and output.size:
            output = self._np.repeat(output[::hold_step], hold_step)[:count]

        if self._style_preset != "none":
            output = style_input * (1.0 - self._style_mix) + output * self._style_mix
            if self._style_preset in {
                "reverse",
                "glitch",
                "stutter",
                "spectral_freeze",
                "granular",
            }:
                output = self._smooth_style_boundary(output)

        if self._modulation == "tremolo":
            lfo = 0.60 + 0.40 * self._np.sin(
                2.0 * self._np.pi * 5.5 * positions / self._sample_rate
            )
            output *= (1.0 - self._modulation_mix) + self._modulation_mix * lfo
        elif self._modulation == "ring":
            carrier = self._np.sin(
                2.0 * self._np.pi * 72.0 * positions / self._sample_rate
            )
            modulated = 0.25 * output + 0.75 * output * carrier
            output = (
                output * (1.0 - self._modulation_mix)
                + modulated * self._modulation_mix
            )
        elif self._modulation == "doppler":
            depth = 6.0 * self._modulation_mix
            offsets = depth * self._np.sin(
                2.0 * self._np.pi * 0.45 * positions / self._sample_rate
            )
            source_positions = self._np.clip(
                self._np.arange(count) + offsets, 0, count - 1
            )
            shifted = self._np.interp(self._np.arange(count), source_positions, output)
            output = (1.0 - self._modulation_mix) * output + self._modulation_mix * shifted
        elif self._modulation == "leslie":
            rotor = 0.72 + 0.28 * self._np.sin(
                2.0 * self._np.pi * 4.2 * positions / self._sample_rate
            )
            output *= (1.0 - self._modulation_mix) + self._modulation_mix * rotor

        if self._impulse is not None:
            extended = self._np.concatenate((self._convolution_history, output))
            convolved = self._np.convolve(extended, self._impulse, mode="full")
            wet = convolved[1023 : 1023 + count].astype(self._np.float32)
            self._convolution_history = extended[-1023:].copy()
            output = output * (1.0 - self._ambience_mix) + wet * self._ambience_mix

        self._phase = float((self._phase + count) % self._sample_rate)
        self._effect_counter += 1
        return output.astype(self._np.float32, copy=False)

    def _smooth_style_boundary(self, samples, fade_frames: int = 48):
        """Remove callback-edge clicks without hiding the selected effect."""

        output = self._np.asarray(samples, dtype=self._np.float32).copy()
        count = min(fade_frames, output.size)
        if self._style_last_sample is not None and count:
            phase = self._np.linspace(
                0.0, self._np.pi / 2.0, count, endpoint=True,
                dtype=self._np.float32,
            )
            fade_in = self._np.sin(phase) ** 2
            output[:count] = (
                self._style_last_sample * (1.0 - fade_in)
                + output[:count] * fade_in
            )
        if output.size:
            self._style_last_sample = float(output[-1])
        return output

    def _smooth_internal_boundaries(self, samples, interval: int, fade_frames: int):
        """Bridge reordered grain edges while retaining their granular rhythm."""

        output = self._np.asarray(samples, dtype=self._np.float32).copy()
        for boundary in range(interval, output.size, interval):
            start = max(0, boundary - fade_frames)
            stop = min(output.size, boundary + fade_frames)
            if start == 0 or stop >= output.size or stop <= start:
                continue
            phase = self._np.linspace(
                0.0, 1.0, stop - start, endpoint=True, dtype=self._np.float32
            )
            curve = phase * phase * (3.0 - 2.0 * phase)
            output[start:stop] = (
                output[start - 1] * (1.0 - curve) + output[stop] * curve
            )
        return output

    def _smooth_gain_change(self, previous: float, target: float, count: int):
        """Ramp intentional dropouts so they sound degraded rather than cut."""

        if count <= 0 or previous == target:
            return self._np.full(count, target, dtype=self._np.float32)
        transition = min(96, count)
        phase = self._np.linspace(
            0.0, 1.0, transition, endpoint=True, dtype=self._np.float32
        )
        curve = phase * phase * (3.0 - 2.0 * phase)
        gain = self._np.full(count, target, dtype=self._np.float32)
        gain[:transition] = previous + (target - previous) * curve
        return gain

    def process_stereo(self, stereo):
        if self._modulation == "stereo_widener":
            output = self._np.asarray(stereo, dtype=self._np.float32).copy()
            for frame in range(output.shape[0]):
                delayed = self._haas_delay[self._haas_index]
                self._haas_delay[self._haas_index] = output[frame, 1]
                output[frame, 1] = (
                    output[frame, 1] * (1.0 - 0.45 * self._modulation_mix)
                    + delayed * 0.45 * self._modulation_mix
                )
                self._haas_index = (self._haas_index + 1) % self._haas_delay.size
            return output
        if self._modulation == "haas":
            output = self._np.asarray(stereo, dtype=self._np.float32).copy()
            for frame in range(output.shape[0]):
                delayed = self._haas_delay[self._haas_index]
                self._haas_delay[self._haas_index] = output[frame, 1]
                output[frame, 1] = (
                    output[frame, 1] * (1.0 - self._modulation_mix)
                    + delayed * self._modulation_mix
                )
                self._haas_index = (self._haas_index + 1) % self._haas_delay.size
            return output
        if self._modulation == "leslie":
            output = self._np.asarray(stereo, dtype=self._np.float32).copy()
            pan = 0.5 + 0.5 * self._np.sin(
                2.0 * self._np.pi * 4.2 * (
                    self._phase + self._np.arange(output.shape[0])
                ) / self._sample_rate
            )
            output[:, 0] *= 1.0 - 0.55 * self._modulation_mix * pan
            output[:, 1] *= 1.0 - 0.55 * self._modulation_mix * (1.0 - pan)
            return output
        if self._modulation != "ping_pong":
            return stereo
        output = self._np.asarray(stereo, dtype=self._np.float32).copy()
        buffer_size = self._ping_left.size
        for frame in range(output.shape[0]):
            delayed_left = self._ping_left[self._ping_index]
            delayed_right = self._ping_right[self._ping_index]
            source = 0.5 * (output[frame, 0] + output[frame, 1])
            output[frame, 0] += delayed_left * 0.40 * self._modulation_mix
            output[frame, 1] += delayed_right * 0.40 * self._modulation_mix
            feedback = 0.35 * self._modulation_mix
            self._ping_left[self._ping_index] = delayed_right * feedback
            self._ping_right[self._ping_index] = (
                source * self._modulation_mix + delayed_left * feedback
            )
            self._ping_index = (self._ping_index + 1) % buffer_size
        return output

    def _make_impulse_response(self, ambience: str):
        if ambience not in ("convolution_room", "convolution_hall"):
            return None
        impulse = self._np.zeros(1024, dtype=self._np.float32)
        impulse[0] = 1.0
        taps = (
            ((83, 0.32), (191, 0.22), (337, 0.15), (601, 0.09), (911, 0.05))
            if ambience == "convolution_room"
            else ((127, 0.38), (293, 0.29), (487, 0.21), (733, 0.15), (997, 0.10))
        )
        for index, gain in taps:
            impulse[index] = gain
        return impulse


class AudioStream(Protocol):
    def set_monitor_voice(self, enabled: bool) -> None: ...

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
        *,
        monitor_voice: bool = True,
    ) -> AudioStream: ...

    def update_reverb(self, settings: ReverbSettings) -> None: ...

    def update_voice_effect(self, settings: VoiceSettings) -> None: ...

    def update_creative_effects(self, settings: CreativeEffectSettings) -> None: ...

    def update_pro_audio(self, settings: ProAudioSettings) -> None: ...

    def update_soundboard(self, settings: SoundboardSettings) -> None: ...

    def play_sound(self, sound_id_or_path: str) -> bool: ...

    def preview_sound(self, path: str, output_device: str) -> None: ...

    def stop_preview(self) -> None: ...

    def update_monitor(self, monitor_output: str | None) -> None: ...

    def update_noise_reduction(self, enabled: bool) -> None: ...

    def update_spatial(self, settings: SpatialSettings) -> None: ...

    def sound_effects(self) -> Sequence[SoundEffectInfo]: ...

    def play_sound_effect(self, effect_id: str) -> SoundEffectInfo: ...

    def stop_sound_effects(self) -> None: ...

    def deactivate(self) -> None: ...


class PedalboardBackend:
    """PortAudio routing with native DSP powered by Spotify's Pedalboard."""

    def __init__(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from pedalboard import (
                Bitcrush,
                Chorus,
                Compressor,
                Delay,
                Distortion,
                Gain,
                HighpassFilter,
                HighShelfFilter,
                Limiter,
                LowpassFilter,
                LowShelfFilter,
                NoiseGate,
                PeakFilter,
                Pedalboard,
                Phaser,
                PitchShift,
                Reverb,
            )
        except ImportError as exc:
            raise AudioDependencyError(
                "O motor de áudio não está instalado. "
                "Execute: python -m pip install -e ."
            ) from exc

        self._np = np
        self._sd = sd
        self._Bitcrush = Bitcrush
        self._Chorus = Chorus
        self._Compressor = Compressor
        self._Delay = Delay
        self._Distortion = Distortion
        self._Gain = Gain
        self._HighpassFilter = HighpassFilter
        self._HighShelfFilter = HighShelfFilter
        self._Limiter = Limiter
        self._LowpassFilter = LowpassFilter
        self._LowShelfFilter = LowShelfFilter
        self._NoiseGate = NoiseGate
        self._PeakFilter = PeakFilter
        self._Pedalboard = Pedalboard
        self._Phaser = Phaser
        self._PitchShift = PitchShift
        self._Reverb = Reverb
        self._reverb = None
        self._effects = None
        self._equalizer = _SmoothEqualizer(np, Pedalboard, [
            LowShelfFilter(cutoff_frequency_hz=150.0, gain_db=0.0),
            PeakFilter(cutoff_frequency_hz=2500.0, gain_db=0.0, q=1.0),
            HighShelfFilter(cutoff_frequency_hz=6000.0, gain_db=0.0),
        ])
        self._pitch_shifter: _StreamingPitchShifter | None = None
        self._sample_rate = 48_000.0
        self._realtime_transform = _RealtimeTransform(
            np, self._sample_rate, "none", "none", "none"
        )
        self._voice_settings = VoiceSettings()
        self._creative_settings = CreativeEffectSettings()
        self._pro_audio_settings = ProAudioSettings()
        self._soundboard_settings = SoundboardSettings()
        self._soundboard = SoundboardManager(int(self._sample_rate))
        self._limiter = None
        self._spatializer: HRTFSpatializer | None = None
        self._spatial_settings = SpatialSettings()
        self._active_stream: _MultiOutputSoundDeviceStream | None = None
        self._noise_reduction_enabled = False
        self._noise_reducer: RNNoiseReducer | None = None
        self._processing_lock = threading.Lock()
        self._input_ids: dict[str, list[tuple[int, str]]] = {}
        self._output_ids: dict[str, list[tuple[int, str]]] = {}
        self._input_level = 0.0

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
        # Prefer WASAPI without hiding devices exposed only by other APIs.
        physical_outputs.sort(key=lambda item: (
            min(_MONITOR_API_RANKS[api] for _, api in item[1] if api in _MONITOR_API_RANKS),
            item[0].casefold(),
        ))
        return tuple(label for label, _candidates in physical_outputs)

    @property
    def input_level(self) -> float:
        return self._input_level

    def diagnostic_details(self) -> dict[str, object]:
        self._refresh_devices()
        return {
            "host_apis": [dict(api) for api in self._sd.query_hostapis()],
            "devices": [dict(device) for device in self._sd.query_devices()],
            "grouped_inputs": self._input_ids,
            "grouped_outputs": self._output_ids,
        }

    def _refresh_devices(self) -> None:
        devices = self._sd.query_devices()
        host_apis = self._sd.query_hostapis()
        input_ids: dict[str, list[tuple[int, str]]] = {}
        output_ids: dict[str, list[tuple[int, str]]] = {}

        for device_id, device in enumerate(devices):
            host_name = host_apis[device["hostapi"]]["name"]
            label = _normalize_device_label(device["name"])
            if _is_windows_default_alias(label):
                continue
            if device["max_input_channels"] > 0:
                input_ids.setdefault(label, []).append((device_id, host_name))
            if device["max_output_channels"] > 0:
                output_label = _normalize_output_device_label(device["name"])
                output_ids.setdefault(output_label, []).append((device_id, host_name))

        _merge_mme_truncated_labels(input_ids)
        _merge_mme_truncated_labels(output_ids)

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
        *,
        monitor_voice: bool = True,
    ) -> AudioStream:
        try:
            (
                input_candidates,
                output_candidates,
                monitor_candidates,
            ) = self._resolve_current_routes(
                input_device,
                output_device,
                monitor_output,
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
        self._reverb = reverb
        self._rebuild_effects_chain()
        self._limiter = self._Pedalboard(
            [self._Limiter(threshold_db=-1.0, release_ms=100.0)]
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
                block_sizes = _stream_block_sizes(monitor_output is not None)
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
                            effects_processor=lambda: self._effects_monitor_audio,
                            monitor_voice=monitor_voice,
                        )
                        # Construction alone does not prove that a Windows host
                        # API can start the endpoint. Validate every route so an
                        # unusable WASAPI/WDM candidate falls through to the next
                        # compatible API before the UI reports success.
                        stream.validate_start()
                    except Exception as exc:
                        if stream is not None:
                            stream.close()
                        last_error = exc
                        continue

                    self._sample_rate = sample_rate
                    self._soundboard.set_sample_rate(round(sample_rate))
                    self._reverb = reverb
                    with self._processing_lock:
                        self._replace_noise_reducer()
                        self._replace_pitch_shifter()
                        self._rebuild_effects_chain()
                        self._spatializer = HRTFSpatializer(sample_rate)
                        self._spatializer.update(self._spatial_settings)
                    self._active_stream = stream
                    return stream
            except Exception as exc:
                last_error = exc
                continue

        self._effects = None
        self._limiter = None
        details = f" Detalhes técnicos: {last_error}" if last_error else ""
        raise RuntimeError(
            f"Não foi possível abrir o microfone '{input_device}' com a saída "
            f"'{output_device}'. Atualize os dispositivos ou escolha outra entrada. "
            "Feche programas que estejam usando o microfone físico e configure "
            "o TeamTalk ou Discord para usar a ponta de gravação do cabo virtual, "
            "não o microfone físico. Se o retorno estiver marcado, tente também "
            "outra saída de retorno."
            f"{details}"
        )

    def _resolve_current_routes(
        self,
        input_device: str,
        output_device: str,
        monitor_output: str | None,
    ) -> tuple[
        list[tuple[int, str]],
        list[tuple[int, str]],
        list[tuple[int | None, str]],
    ]:
        """Return candidates using a fresh PortAudio device snapshot."""

        # PortAudio IDs are positions in the current device list, not persistent
        # Windows endpoint identifiers. Driver and Windows updates can renumber
        # every endpoint while their user-facing names remain unchanged.
        self._refresh_devices()
        resolved_input = _resolve_device_label(input_device, self._input_ids)
        resolved_output = _resolve_device_label(
            output_device,
            self._output_ids,
            output=True,
        )
        input_candidates = self._input_ids[resolved_input]
        output_candidates = self._output_ids[resolved_output]
        if monitor_output is None:
            return input_candidates, output_candidates, [(None, "")]

        resolved_monitor = _resolve_device_label(
            monitor_output,
            self._output_ids,
            output=True,
        )
        monitor_candidates: list[tuple[int | None, str]] = sorted(
            (
                candidate
                for candidate in self._output_ids[resolved_monitor]
                if candidate[1] in _MONITOR_API_RANKS
            ),
            key=lambda candidate: _MONITOR_API_RANKS[candidate[1]],
        )
        return input_candidates, output_candidates, monitor_candidates

    def _find_common_sample_rate(
        self,
        input_id: int,
        input_channels: int,
        input_default: float,
        output_specs: Sequence[tuple[int, int, float]],
    ) -> float:
        candidates = (
            [float(RNNOISE_SAMPLE_RATE)]
            if self._noise_reduction_enabled
            else [
                input_default,
                *(item[2] for item in output_specs),
                48_000.0,
                44_100.0,
            ]
        )
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
        output = self._np.zeros((frames, 2), dtype=self._np.float32)
        self._effects_monitor_audio = output
        with self._processing_lock:
            if self._effects is None:
                return output

            mono_input = self._np.mean(indata, axis=1, dtype=self._np.float32)
            self._input_level = min(
                1.0, float(self._np.sqrt(self._np.mean(mono_input * mono_input)))
            )
            soundboard_audio = None
            soundboard_duck = 1.0
            soundboard = getattr(self, "_soundboard", None)
            if soundboard is not None:
                soundboard_audio = soundboard.mix(frames)
                if soundboard_audio is not None:
                    soundboard_settings = getattr(
                        self, "_soundboard_settings", SoundboardSettings()
                    )
                    if soundboard_settings.ducking_enabled:
                        voice_level = float(
                            self._np.sqrt(self._np.mean(mono_input * mono_input))
                        )
                        activity = min(1.0, voice_level / 0.06)
                        soundboard_duck -= (
                            soundboard_settings.ducking_percent / 100.0
                        ) * activity
            if soundboard_audio is not None:
                self._effects_monitor_audio = soundboard_audio * soundboard_duck
            if self._noise_reducer is not None:
                mono_input = self._noise_reducer.process(mono_input)
            pitch_shifter = getattr(self, "_pitch_shifter", None)
            if pitch_shifter is not None:
                mono_input = pitch_shifter.process(mono_input)
            realtime_transform = getattr(self, "_realtime_transform", None)
            if realtime_transform is not None:
                mono_input = realtime_transform.process_mono(mono_input)
            combined_input = mono_input
            if soundboard_audio is not None:
                soundboard_mono = self._np.mean(
                    soundboard_audio,
                    axis=1,
                    dtype=self._np.float32,
                )
                combined_input = mono_input + (soundboard_mono * soundboard_duck)
            reverberated = self._effects.process(
                combined_input[self._np.newaxis, :],
                self._sample_rate,
                buffer_size=frames,
                reset=False,
            )
            mono = reverberated if reverberated.ndim == 1 else reverberated[0]
            spatializer = self._spatializer
            if spatializer is None:
                stereo = self._np.column_stack((mono, mono))
            else:
                stereo = spatializer.process(mono)
            if realtime_transform is not None:
                stereo = realtime_transform.process_stereo(stereo)
            if self._limiter is not None:
                limited = self._limiter.process(
                    stereo.T,
                    self._sample_rate,
                    buffer_size=frames,
                    reset=False,
                )
                stereo = limited.T if limited.ndim == 2 else self._np.column_stack(
                    (limited, limited)
                )
        available = min(frames, stereo.shape[0])
        output[:available, :] = stereo[:available, :2]
        return output

    def update_reverb(self, settings: ReverbSettings) -> None:
        with self._processing_lock:
            if self._reverb is None:
                return
            self._reverb.room_size = settings.room_size
            self._reverb.damping = settings.damping
            self._reverb.wet_level = settings.wet_level
            self._reverb.dry_level = settings.dry_level

    def update_voice_effect(self, settings: VoiceSettings) -> None:
        with self._processing_lock:
            self._voice_settings = settings
            self._replace_pitch_shifter()
            self._rebuild_effects_chain()

    def update_creative_effects(self, settings: CreativeEffectSettings) -> None:
        with self._processing_lock:
            self._creative_settings = settings
            self._rebuild_effects_chain()

    def update_pro_audio(self, settings: ProAudioSettings) -> None:
        with self._processing_lock:
            previous = self._pro_audio_settings
            self._pro_audio_settings = settings
            self._equalizer.update(settings)
            other_settings = replace(
                settings, eq_enabled=previous.eq_enabled,
                eq_low_db=previous.eq_low_db, eq_mid_db=previous.eq_mid_db,
                eq_high_db=previous.eq_high_db,
            )
            if self._effects is None or other_settings != previous:
                self._rebuild_effects_chain()

    def update_soundboard(self, settings: SoundboardSettings) -> None:
        with self._processing_lock:
            self._soundboard_settings = settings
            if self._soundboard is not None:
                self._soundboard.set_volume_percent(settings.volume_percent)

    def play_sound(self, sound_id_or_path: str) -> bool:
        if self._soundboard is None:
            return False
        return self._soundboard.play(sound_id_or_path)

    def preview_sound(self, path: str, output_device: str) -> None:
        self._refresh_devices()
        resolved = _resolve_device_label(output_device, self._output_ids, output=True)
        candidates = sorted(
            self._output_ids[resolved],
            key=lambda candidate: _MONITOR_API_RANKS.get(candidate[1], 99),
        )
        if not candidates:
            raise ValueError(f"O dispositivo de retorno '{output_device}' não está disponível.")
        device_id = candidates[0][0]
        device = self._sd.query_devices(device_id)
        target_rate = float(device["default_samplerate"])
        audio, source_rate = _read_custom_audio(Path(path))
        prepared = _resample(audio, source_rate, target_rate)
        self._sd.play(prepared, samplerate=target_rate, device=device_id, blocking=False)

    def stop_preview(self) -> None:
        self._sd.stop()

    def _rebuild_effects_chain(self) -> None:
        if self._reverb is None:
            return
        effects = []
        if self._voice_settings.enabled:
            effects.append(
                self._HighpassFilter(
                    cutoff_frequency_hz=self._voice_settings.highpass_cutoff
                )
            )
            voice_preset = self._voice_settings.preset
            if voice_preset in ("female", "female_soft", "female_thin", "helium"):
                effects.append(
                    self._LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=-3.0)
                )
                effects.append(
                    self._PeakFilter(
                        cutoff_frequency_hz=2800.0, gain_db=3.0, q=0.8
                    )
                )
            elif voice_preset in ("male", "monster"):
                effects.append(
                    self._LowShelfFilter(cutoff_frequency_hz=220.0, gain_db=3.5)
                )
                effects.append(
                    self._HighShelfFilter(cutoff_frequency_hz=4500.0, gain_db=-2.5)
                )
            if voice_preset == "monster":
                effects.append(self._Distortion(drive_db=7.0))

        pre_effects = effects
        effects = []

        style_mix = self._creative_settings.style_intensity_percent / 100.0
        preset = self._creative_settings.preset if style_mix > 0.0 else "none"
        if preset in (
            "telephone",
            "walkie_police",
            "walkie_military",
            "walkie_toy",
        ):
            radio_profiles = {
                "telephone": (300.0, 3200.0, 1450.0, 7.0),
                "walkie_police": (350.0, 3000.0, 1550.0, 8.0),
                "walkie_military": (400.0, 2800.0, 1650.0, 10.0),
                "walkie_toy": (500.0, 2500.0, 1750.0, 13.0),
            }
            highpass, lowpass, mid_peak, drive = radio_profiles[preset]
            effects.append(self._HighpassFilter(cutoff_frequency_hz=highpass))
            effects.append(self._HighpassFilter(cutoff_frequency_hz=highpass))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=lowpass))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=lowpass))
            effects.append(
                self._PeakFilter(
                    cutoff_frequency_hz=mid_peak,
                    gain_db=5.0,
                    q=1.1,
                )
            )
            effects.append(
                self._Compressor(
                    threshold_db=-26.0,
                    ratio=8.0,
                    attack_ms=2.0,
                    release_ms=55.0,
                )
            )
            effects.append(self._Distortion(drive_db=drive))
            effects.append(self._Bitcrush(bit_depth=11.0))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=lowpass))
            effects.append(self._Gain(gain_db=2.0))
        elif preset == "megaphone":
            effects.append(self._HighpassFilter(cutoff_frequency_hz=350.0))
            effects.append(self._HighpassFilter(cutoff_frequency_hz=350.0))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=3000.0))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=3000.0))
            effects.append(
                self._Compressor(
                    threshold_db=-22.0,
                    ratio=5.0,
                    attack_ms=3.0,
                    release_ms=80.0,
                )
            )
            effects.append(self._Distortion(drive_db=8.0))
            effects.append(self._Gain(gain_db=1.5))
        elif preset == "robot":
            effects.append(
                self._Chorus(rate_hz=8.0, depth=0.7, feedback=0.35, mix=0.75)
            )
            effects.append(self._Bitcrush(bit_depth=10.0))
            effects.append(self._Gain(gain_db=0.5))
        elif preset == "old_radio":
            effects.extend(
                [
                    self._HighpassFilter(cutoff_frequency_hz=350.0),
                    self._LowpassFilter(cutoff_frequency_hz=2800.0),
                    self._Bitcrush(bit_depth=9.0),
                    self._Distortion(drive_db=3.0),
                    self._Gain(gain_db=3.0),
                ]
            )
        elif preset == "intercom":
            effects.extend(
                [
                    self._HighpassFilter(cutoff_frequency_hz=450.0),
                    self._LowpassFilter(cutoff_frequency_hz=4200.0),
                    self._Compressor(threshold_db=-25.0, ratio=7.0),
                    self._Distortion(drive_db=6.0),
                    self._Gain(gain_db=2.0),
                ]
            )
        elif preset == "space_helmet":
            effects.extend(
                [
                    self._Chorus(rate_hz=0.6, depth=0.35, feedback=0.2, mix=0.35),
                    self._Delay(delay_seconds=0.08, feedback=0.25, mix=0.18),
                ]
            )
        elif preset == "ghost":
            effects.extend(
                [
                    self._Chorus(rate_hz=0.25, depth=0.8, feedback=0.45, mix=0.65),
                    self._Delay(delay_seconds=0.22, feedback=0.50, mix=0.30),
                ]
            )
        elif preset == "underwater":
            effects.extend(
                [
                    self._LowpassFilter(cutoff_frequency_hz=950.0),
                    self._Chorus(rate_hz=0.8, depth=0.65, feedback=0.2, mix=0.50),
                    self._Gain(gain_db=3.0),
                ]
            )
        elif preset == "arcade":
            effects.extend(
                [
                    self._Bitcrush(bit_depth=7.0),
                    self._Gain(gain_db=1.5),
                ]
            )
        elif preset == "tape":
            effects.extend(
                [
                    self._LowpassFilter(cutoff_frequency_hz=12500.0),
                    self._Distortion(drive_db=1.5),
                ]
            )
        elif preset == "vinyl":
            effects.append(self._HighpassFilter(cutoff_frequency_hz=45.0))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=10500.0))
        elif preset == "vhs":
            effects.append(self._HighpassFilter(cutoff_frequency_hz=80.0))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=7500.0))
        elif preset == "broken_speaker":
            effects.extend(
                [
                    self._HighpassFilter(cutoff_frequency_hz=240.0),
                    self._LowpassFilter(cutoff_frequency_hz=4800.0),
                    self._Distortion(drive_db=18.0),
                    self._Bitcrush(bit_depth=8.0),
                    self._Gain(gain_db=-3.0),
                ]
            )
        elif preset == "radio_interference":
            effects.append(self._HighpassFilter(cutoff_frequency_hz=250.0))
            effects.append(self._LowpassFilter(cutoff_frequency_hz=4200.0))
        elif preset == "octave_fuzz":
            effects.append(self._HighpassFilter(cutoff_frequency_hz=100.0))
            effects.append(self._Distortion(drive_db=14.0))
            effects.append(self._Gain(gain_db=-2.0))

        style_effects = effects
        effects = []

        modulation_mix = self._creative_settings.modulation_intensity_percent / 100.0
        modulation = (
            self._creative_settings.modulation if modulation_mix > 0.0 else "none"
        )
        if modulation == "flanger":
            effects.append(
                self._Chorus(
                    rate_hz=0.35,
                    depth=0.7,
                    centre_delay_ms=2.0,
                    feedback=0.60,
                    mix=modulation_mix,
                )
            )
        elif modulation == "phaser":
            effects.append(
                self._Phaser(
                    rate_hz=0.7,
                    depth=0.75,
                    centre_frequency_hz=1200.0,
                    feedback=0.35,
                    mix=modulation_mix,
                )
            )
        elif modulation == "chorus":
            effects.append(
                self._Chorus(
                    rate_hz=1.2,
                    depth=0.45,
                    feedback=0.15,
                    mix=modulation_mix,
                )
            )

        ambience_mix = self._creative_settings.ambience_intensity_percent / 100.0
        ambience = self._creative_settings.ambience if ambience_mix > 0.0 else "none"
        ambience_reverbs = {
            "small_room": (0.30, 0.60, 0.12),
            "auditorium": (0.70, 0.48, 0.18),
            "cathedral": (0.95, 0.22, 0.28),
            "cave": (0.88, 0.12, 0.25),
            "bathroom": (0.42, 0.25, 0.20),
        }
        if ambience in ambience_reverbs:
            room_size, damping, wet = ambience_reverbs[ambience]
            wet *= self._creative_settings.ambience_intensity_percent / 50.0
            wet = min(0.45, wet)
            effects.append(
                self._Reverb(
                    room_size=room_size,
                    damping=damping,
                    wet_level=wet,
                    dry_level=(0.90 - wet) / 2.0,
                    width=1.0,
                )
            )
        elif ambience == "mountain":
            effects.append(
                self._Delay(
                    delay_seconds=0.42,
                    feedback=0.48 * ambience_mix,
                    mix=0.34 * ambience_mix,
                )
            )

        before_eq_effects = effects
        effects = []

        if self._pro_audio_settings.compressor_enabled:
            effects.append(
                self._Compressor(
                    threshold_db=-16.0,
                    ratio=3.5,
                    attack_ms=15.0,
                    release_ms=100.0,
                )
            )

        if self._pro_audio_settings.noise_gate_enabled:
            effects.append(
                self._NoiseGate(
                    threshold_db=-42.0,
                    ratio=10.0,
                    attack_ms=2.0,
                    release_ms=120.0,
                )
            )
        if self._pro_audio_settings.expander_enabled:
            effects.append(
                self._NoiseGate(
                    threshold_db=-48.0,
                    ratio=2.0,
                    attack_ms=8.0,
                    release_ms=180.0,
                )
            )
        if self._pro_audio_settings.deesser_enabled:
            effects.append(
                self._HighShelfFilter(
                    cutoff_frequency_hz=5800.0,
                    gain_db=-5.0,
                )
            )
        if self._pro_audio_settings.plosive_filter_enabled:
            effects.extend(
                (
                    self._HighpassFilter(cutoff_frequency_hz=95.0),
                    self._HighpassFilter(cutoff_frequency_hz=95.0),
                )
            )
        if self._pro_audio_settings.auto_gain_enabled:
            effects.extend(
                (
                    self._Compressor(
                        threshold_db=-24.0,
                        ratio=4.0,
                        attack_ms=12.0,
                        release_ms=160.0,
                    ),
                    self._Gain(gain_db=5.0),
                )
            )

        if self._creative_settings.delay_enabled:
            effects.append(
                self._Delay(
                    delay_seconds=self._creative_settings.delay_seconds,
                    feedback=self._creative_settings.delay_feedback,
                    mix=self._creative_settings.delay_mix,
                )
            )

        effects.append(self._reverb)
        self._effects = _EffectChain(
            self._np,
            self._Pedalboard,
            pre_effects,
            style_effects,
            effects,
            style_mix,
            equalizer=self._equalizer,
            before_eq_effects=before_eq_effects,
        )
        self._realtime_transform = _RealtimeTransform(
            self._np,
            self._sample_rate,
            self._voice_settings.preset if self._voice_settings.enabled else "none",
            self._creative_settings.preset,
            self._creative_settings.modulation,
            self._creative_settings.ambience,
            self._creative_settings.style_intensity_percent / 100.0,
            self._creative_settings.modulation_intensity_percent / 100.0,
            self._creative_settings.ambience_intensity_percent / 100.0,
            self._creative_settings.roger_beep_enabled,
        )

    def _replace_pitch_shifter(self) -> None:
        if self._pitch_shifter is not None:
            self._pitch_shifter.close()
            self._pitch_shifter = None
        if not self._voice_settings.enabled:
            self._pitch_shifter = None
            return
        preset = self._voice_settings.preset
        pitch_map = {
            "female": 4.0,
            "female_soft": 3.0,
            "female_thin": 6.0,
            "male": -4.0,
            "monster": -7.0,
            "helium": 9.0,
            "double": 0.35,
            "harmony_third": 4.0,
            "harmony_fifth": 7.0,
            "harmony_octave": 12.0,
            "custom": self._voice_settings.pitch_semitones,
        }
        semitones = pitch_map.get(preset, self._voice_settings.pitch_semitones)
        if semitones == 0.0:
            return
        pitched = self._Pedalboard([self._PitchShift(semitones=semitones)])
        if preset == "double":
            processor = _MixedPitchProcessor(self._np, pitched, 0.58, 0.42)
        elif preset.startswith("harmony_"):
            processor = _MixedPitchProcessor(self._np, pitched, 0.55, 0.45)
        elif preset == "monster":
            processor = _MixedPitchProcessor(self._np, pitched, 0.20, 0.80)
        else:
            processor = pitched
        self._pitch_shifter = _StreamingPitchShifter(
            self._np, processor, self._sample_rate
        )

    def update_noise_reduction(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Estado da redução de ruído deve ser verdadeiro ou falso.")
        self._noise_reduction_enabled = enabled

    def update_spatial(self, settings: SpatialSettings) -> None:
        with self._processing_lock:
            self._spatial_settings = settings
            if self._spatializer is not None:
                self._spatializer.update(settings)

    def sound_effects(self) -> Sequence[SoundEffectInfo]:
        return self._soundboard.effects()

    def play_sound_effect(self, effect_id: str) -> SoundEffectInfo:
        return self._soundboard.trigger(effect_id, self._sample_rate)

    def stop_sound_effects(self) -> None:
        self._soundboard.stop_all()

    def _replace_noise_reducer(self) -> None:
        previous = self._noise_reducer
        self._noise_reducer = (
            RNNoiseReducer() if self._noise_reduction_enabled else None
        )
        if previous is not None:
            previous.close()

    def update_monitor(self, monitor_output: str | None) -> None:
        stream = self._active_stream
        if stream is None:
            raise RuntimeError("A mesa não está ativa.")
        if monitor_output is None:
            stream.replace_monitor(None, 0)
            return

        self._refresh_devices()
        try:
            resolved_monitor = _resolve_device_label(
                monitor_output,
                self._output_ids,
                output=True,
            )
            candidates = sorted(
                (
                    candidate
                    for candidate in self._output_ids[resolved_monitor]
                    if candidate[1] in _MONITOR_API_RANKS
                ),
                key=lambda candidate: _MONITOR_API_RANKS[candidate[1]],
            )
        except KeyError as exc:
            raise ValueError(
                "O dispositivo de retorno não está mais disponível. "
                "Atualize a lista de dispositivos."
            ) from exc

        last_error: Exception | None = None
        for output_id, _api_name in candidates:
            try:
                device_info = self._sd.query_devices(output_id)
                channels = min(2, int(device_info["max_output_channels"]))
                self._sd.check_output_settings(
                    device=output_id,
                    channels=channels,
                    dtype="float32",
                    samplerate=self._sample_rate,
                )
                stream.replace_monitor(output_id, channels)
                return
            except Exception as exc:
                last_error = exc

        details = f" Detalhes técnicos: {last_error}" if last_error else ""
        raise RuntimeError(
            f"Não foi possível abrir o retorno '{monitor_output}'.{details}"
        )

    def deactivate(self) -> None:
        with self._processing_lock:
            if self._pitch_shifter is not None:
                self._pitch_shifter.close(timeout=0.25)
                self._pitch_shifter = None
            if self._noise_reducer is not None:
                self._noise_reducer.close()
                self._noise_reducer = None
            self._active_stream = None
            self._soundboard.stop()


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
        gain: float = 1.0,
        peak_limit: float | None = None,
        drop_when_busy: bool = False,
        host_managed_blocksize: bool = False,
        latency: str | float = "low",
    ) -> None:
        self._sd = sounddevice
        self._block_size = block_size
        self._output_channels = output_channels
        self._gain = gain
        self._peak_limit = peak_limit
        self._drop_when_busy = drop_when_busy
        self._chunks = deque()
        self._head_offset = 0
        self._queued_frames = 0
        self._max_queued_frames = self._block_size * 4
        self._queue_lock = threading.Lock()
        self._prefilled = threading.Event()
        self._last_sample = self._np_zeros(output_channels)
        self._underrun = True
        self._needs_crossfade = False
        self._underrun_count = 0
        self._dropped_block_count = 0
        self.stream = sounddevice.OutputStream(
            device=output_id,
            samplerate=sample_rate,
            blocksize=0 if host_managed_blocksize else self._block_size,
            channels=output_channels,
            dtype="float32",
            latency=latency,
            callback=self._on_output,
        )

    def push(self, processed) -> bool:
        acquired = self._queue_lock.acquire(blocking=not self._drop_when_busy)
        if not acquired:
            self._dropped_block_count += 1
            return False
        try:
            self._chunks.append(processed)
            self._queued_frames += processed.shape[0]
            while self._queued_frames > self._max_queued_frames and self._chunks:
                removed = self._chunks.popleft()
                self._queued_frames -= removed.shape[0] - self._head_offset
                self._head_offset = 0
                self._needs_crossfade = True
                self._dropped_block_count += 1
            if self._queued_frames >= self._block_size * 2:
                self._prefilled.set()
        finally:
            self._queue_lock.release()
        return True

    def clear(self) -> None:
        with self._queue_lock:
            self._chunks.clear()
            self._head_offset = 0
            self._queued_frames = 0
            self._last_sample = self._np_zeros(self._output_channels)
            self._underrun = True
            self._needs_crossfade = False
            self._prefilled.clear()

    def wait_until_prefilled(self, timeout: float) -> bool:
        return self._prefilled.wait(timeout)

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
                samples = chunk[self._head_offset : self._head_offset + count]
                adapted = self._adapt_channels(samples)
                outdata[written : written + count, :] = adapted
                if self._underrun or self._needs_crossfade:
                    fade_from = (
                        self._np_zeros(self._output_channels)
                        if self._underrun
                        else self._last_sample
                    )
                    fade_frames = min(32, count)
                    for index in range(fade_frames):
                        amount = (index + 1) / fade_frames
                        outdata[written + index, :] = (
                            fade_from * (1.0 - amount) + adapted[index] * amount
                        )
                    self._underrun = False
                    self._needs_crossfade = False
                written += count
                self._head_offset += count
                self._queued_frames -= count
                self._last_sample = adapted[-1].copy()
                if self._head_offset == chunk.shape[0]:
                    self._chunks.popleft()
                    self._head_offset = 0

            if written < frames:
                missing_frames = frames - written
                fade_frames = min(32, missing_frames)
                for index in range(fade_frames):
                    amount = (index + 1) / fade_frames
                    outdata[written + index, :] = self._last_sample * (1.0 - amount)
                self._last_sample = self._np_zeros(self._output_channels)
                if not self._underrun:
                    self._underrun_count += 1
                self._underrun = True

    @staticmethod
    def _np_zeros(channels: int):
        import numpy as np

        return np.zeros(channels, dtype=np.float32)

    def _adapt_channels(self, samples):
        import numpy as np

        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim == 1:
            adapted = np.repeat(samples[:, None], self._output_channels, axis=1)
        elif samples.shape[1] == self._output_channels:
            adapted = samples
        elif self._output_channels == 1:
            adapted = np.mean(samples, axis=1, keepdims=True, dtype=np.float32)
        elif samples.shape[1] == 1:
            adapted = np.repeat(samples, self._output_channels, axis=1)
        else:
            adapted = samples[:, : self._output_channels]
        if self._gain != 1.0:
            adapted = adapted * self._gain
        if self._peak_limit is not None:
            adapted = np.clip(adapted, -self._peak_limit, self._peak_limit)
        return adapted


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
        effects_processor: Callable | None = None,
        monitor_voice: bool = True,
    ) -> None:
        self._sd = sounddevice
        self._processor = processor
        self._effects_processor = effects_processor
        self._monitor_voice = monitor_voice
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._stop_event = threading.Event()
        self._first_audio = threading.Event()
        self._captured_blocks = 0
        self._prefill_blocks = 3 if len(outputs) > 1 else 2
        self._error: Exception | None = None
        self._validating = False
        self._lifecycle_lock = threading.Lock()
        self._run_entered = False
        self._disposed = False
        self._outputs: list[_BufferedAudioOutput] = []
        self._outputs_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._pending_monitor: _BufferedAudioOutput | None = None
        self._monitor_output: _BufferedAudioOutput | None = None
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
            for index, (output_id, output_channels) in enumerate(outputs):
                self._outputs.append(
                    _BufferedAudioOutput(
                        sounddevice=sounddevice,
                        output_id=output_id,
                        sample_rate=sample_rate,
                        output_channels=output_channels,
                        block_size=block_size,
                        gain=1.0 if index == 0 else 0.72,
                        peak_limit=None if index == 0 else 0.95,
                        drop_when_busy=index > 0,
                        host_managed_blocksize=index > 0,
                        latency="low" if index == 0 else 0.02,
                    )
                )
            self._primary_output = self._outputs[0]
            if len(self._outputs) > 1:
                self._monitor_output = self._outputs[1]
        except Exception:
            self._close_streams()
            raise

    def validate_start(self) -> None:
        """Start every device once so failing Windows APIs can be skipped."""

        self._validating = True
        try:
            self._input.start()
            for output in self._outputs:
                output.stream.start()
        except Exception:
            self._abort_streams()
            raise
        finally:
            self._validating = False

    def run(self) -> None:
        with self._lifecycle_lock:
            if self._disposed:
                return
            self._run_entered = True
        try:
            if not self._input.active:
                self._input.start()
            self._first_audio.wait(timeout=0.15)
            if self._stop_event.is_set():
                return
            for output in self._outputs:
                if not output.stream.active:
                    output.stream.start()
            while (
                self._input.active
                and self._primary_output.stream.active
                and not self._stop_event.wait(0.1)
            ):
                pass
        finally:
            self._close_streams()
            with self._lifecycle_lock:
                self._disposed = True
        if self._error is not None:
            raise RuntimeError(str(self._error)) from self._error

    def close(self) -> None:
        self._stop_event.set()
        # PortAudio stream teardown must have a single owner. Once run() has
        # entered, its audio thread closes every native stream in the finally
        # block. Closing them here as well can race inside PortAudio and end
        # the process instead of raising a Python exception.
        with self._lifecycle_lock:
            dispose_here = not self._run_entered and not self._disposed
            if dispose_here:
                self._disposed = True
        if dispose_here:
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

        # The virtual cable is the recording path and always receives the block
        # first. A congested experimental monitor is allowed to drop its copy,
        # but can never hold up the input callback or the primary output.
        self._primary_output.push(processed)
        with self._outputs_lock:
            monitor_audio = processed
            if not self._monitor_voice and self._effects_processor is not None:
                monitor_audio = self._effects_processor()
            for monitor in (self._monitor_output, self._pending_monitor):
                if monitor is not None:
                    monitor.push(monitor_audio)
        self._captured_blocks += 1
        if self._captured_blocks >= self._prefill_blocks:
            self._first_audio.set()

    def set_monitor_voice(self, enabled: bool) -> None:
        with self._outputs_lock:
            if self._monitor_voice == enabled:
                return
            self._monitor_voice = enabled
            for monitor in (self._monitor_output, self._pending_monitor):
                if monitor is not None:
                    monitor.clear()

    def replace_monitor(self, output_id: int | None, output_channels: int) -> None:
        if output_id is None:
            with self._outputs_lock:
                previous = self._monitor_output
                self._monitor_output = None
                if previous in self._outputs:
                    self._outputs.remove(previous)
            if previous is not None:
                self._close_output(previous)
            return

        replacement = _BufferedAudioOutput(
            sounddevice=self._sd,
            output_id=output_id,
            sample_rate=self._sample_rate,
            output_channels=output_channels,
            block_size=self._block_size,
            gain=0.72,
            peak_limit=0.95,
            drop_when_busy=True,
            host_managed_blocksize=True,
            latency=0.02,
        )
        with self._outputs_lock:
            if self._pending_monitor is not None:
                self._close_output(replacement)
                raise RuntimeError("Outra alteração de retorno já está em andamento.")
            self._pending_monitor = replacement

        try:
            if not replacement.wait_until_prefilled(0.2):
                raise RuntimeError("O retorno não recebeu áudio a tempo de iniciar.")
            replacement.stream.start()
        except Exception:
            with self._outputs_lock:
                if self._pending_monitor is replacement:
                    self._pending_monitor = None
            self._close_output(replacement)
            raise

        with self._outputs_lock:
            previous = self._monitor_output
            self._monitor_output = replacement
            self._outputs.append(replacement)
            self._pending_monitor = None
            if previous in self._outputs:
                self._outputs.remove(previous)
        if previous is not None:
            self._close_output(previous)

    @staticmethod
    def _close_output(output: _BufferedAudioOutput) -> None:
        try:
            if not output.stream.closed:
                output.stream.abort()
                output.stream.close()
        except Exception:
            pass

    def _close_streams(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            with self._outputs_lock:
                outputs = tuple(self._outputs)
                pending_monitor = self._pending_monitor
            if pending_monitor is not None:
                outputs = (*outputs, pending_monitor)
            streams = [self._input, *(output.stream for output in outputs)]
            for stream in streams:
                try:
                    if not stream.closed:
                        stream.abort()
                        stream.close()
                except Exception:
                    pass

    def _abort_streams(self) -> None:
        with self._outputs_lock:
            outputs = tuple(self._outputs)
        streams = [self._input, *(output.stream for output in outputs)]
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
        self._voice_settings = VoiceSettings()
        self._creative_settings = CreativeEffectSettings()
        self._pro_audio_settings = ProAudioSettings()
        self._soundboard_settings = SoundboardSettings()
        self._stream: AudioStream | None = None
        self._thread: threading.Thread | None = None
        self._input_device: str | None = None
        self._output_device: str | None = None
        self._monitor_output: str | None = None
        self._effects_output: str | None = None
        self._noise_reduction_enabled = False
        self._spatial_settings = SpatialSettings()
        self._stopping = False
        self._lock = threading.RLock()

    @property
    def settings(self) -> ReverbSettings:
        with self._lock:
            return self._settings

    @property
    def voice_settings(self) -> VoiceSettings:
        with self._lock:
            return self._voice_settings

    @property
    def creative_settings(self) -> CreativeEffectSettings:
        with self._lock:
            return self._creative_settings

    @property
    def pro_audio_settings(self) -> ProAudioSettings:
        with self._lock:
            return self._pro_audio_settings

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

    @property
    def input_level(self) -> float:
        return float(getattr(self._backend, "input_level", 0.0))

    def diagnostic_details(self) -> dict[str, object]:
        method = getattr(self._backend, "diagnostic_details", None)
        return method() if method is not None else {}

    def update_settings(self, settings: ReverbSettings) -> None:
        with self._lock:
            if self._stream is not None:
                self._backend.update_reverb(settings)
            self._settings = settings

    def update_voice_settings(self, settings: VoiceSettings) -> None:
        with self._lock:
            if self._stream is not None:
                self._backend.update_voice_effect(settings)
            self._voice_settings = settings

    def update_creative_settings(self, settings: CreativeEffectSettings) -> None:
        with self._lock:
            if self._stream is not None:
                self._backend.update_creative_effects(settings)
            self._creative_settings = settings

    def update_pro_audio_settings(self, settings: ProAudioSettings) -> None:
        with self._lock:
            if self._stream is not None:
                self._backend.update_pro_audio(settings)
            self._pro_audio_settings = settings

    def update_soundboard_settings(self, settings: SoundboardSettings) -> None:
        with self._lock:
            self._soundboard_settings = settings
            self._backend.update_soundboard(settings)

    def play_sound(self, sound_id_or_path: str) -> bool:
        with self._lock:
            if self._stream is None:
                return False
            return self._backend.play_sound(sound_id_or_path)

    def preview_sound(self, path: str, output_device: str) -> None:
        with self._lock:
            if self._stream is not None:
                if not self._backend.play_sound(path):
                    raise ValueError("Não foi possível carregar o efeito.")
                return
            self._backend.preview_sound(path, output_device)

    def stop_preview(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._backend.stop_sound_effects()
            else:
                self._backend.stop_preview()

    def set_error_handler(self, handler: Callable[[str], None] | None) -> None:
        with self._lock:
            self._on_error = handler

    def start(
        self,
        input_device: str,
        output_device: str,
        monitor_output: str | None = None,
        *,
        effects_output: str | None = None,
    ) -> None:
        input_device = input_device.strip()
        output_device = output_device.strip()
        monitor_output = monitor_output.strip() if monitor_output else None
        effects_output = effects_output.strip() if effects_output else None
        local_output = monitor_output or effects_output
        if not input_device:
            raise ValueError("Selecione um microfone de entrada.")
        if not output_device:
            raise ValueError("Selecione uma saída virtual.")
        if input_device == output_device:
            raise ValueError(
                "A entrada e a saída não podem ser o mesmo dispositivo; "
                "isso causaria microfonia."
            )
        if local_output == output_device:
            raise ValueError(
                "A saída de retorno deve ser diferente da saída virtual."
            )
        if local_output == input_device:
            raise ValueError(
                "O retorno não pode usar o mesmo dispositivo de entrada."
            )

        with self._lock:
            if self._stream is not None:
                raise RuntimeError("O processamento de áudio já está ativo.")
            self._backend.update_voice_effect(self._voice_settings)
            self._backend.update_creative_effects(self._creative_settings)
            self._backend.update_pro_audio(self._pro_audio_settings)
            self._backend.update_soundboard(self._soundboard_settings)
            try:
                stream = self._backend.create_stream(
                    input_device,
                    output_device,
                    self._settings,
                    local_output,
                    **({"monitor_voice": monitor_output is not None} if effects_output else {}),
                )
            except Exception:
                deactivate = getattr(self._backend, "deactivate", None)
                if deactivate is not None:
                    deactivate()
                raise
            if effects_output is not None:
                stream.set_monitor_voice(monitor_output is not None)
            self._effects_output = effects_output
            self._stream = stream
            self._input_device = input_device
            self._output_device = output_device
            self._monitor_output = monitor_output
            self._stopping = False
            thread = threading.Thread(
                target=self._run_stream,
                args=(stream,),
                name="mini-mesa-audio",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def update_monitor(self, monitor_output: str | None, *, effects_output: str | None = None) -> None:
        monitor_output = monitor_output.strip() if monitor_output else None
        with self._lock:
            if self._stream is None:
                raise RuntimeError("A mesa não está ativa.")
            effects_output = effects_output or self._effects_output
            local_output = monitor_output or effects_output
            if local_output == self._output_device:
                raise ValueError(
                    "A saída de retorno deve ser diferente da saída virtual."
                )
            if local_output == self._input_device:
                raise ValueError(
                    "O retorno não pode usar o mesmo dispositivo de entrada."
                )
            if monitor_output == self._monitor_output and effects_output == self._effects_output:
                return
            previous_output = self._monitor_output or self._effects_output
            if local_output != previous_output:
                self._backend.update_monitor(local_output)
            if effects_output is not None:
                self._stream.set_monitor_voice(monitor_output is not None)
            self._monitor_output = monitor_output
            self._effects_output = effects_output

    def update_noise_reduction(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Estado da redução de ruído deve ser verdadeiro ou falso.")
        with self._lock:
            if self._stream is not None:
                raise RuntimeError(
                    "Desative a mesa antes de alterar a redução de ruído."
                )
            self._backend.update_noise_reduction(enabled)
            self._noise_reduction_enabled = enabled

    def update_spatial(self, settings: SpatialSettings) -> None:
        with self._lock:
            self._spatial_settings = settings
            self._backend.update_spatial(settings)

    def sound_effects(self) -> tuple[SoundEffectInfo, ...]:
        return tuple(self._backend.sound_effects())

    def play_sound_effect(self, effect_id: str) -> SoundEffectInfo:
        with self._lock:
            if self._stream is None:
                raise RuntimeError("Ative a mesa antes de reproduzir um efeito.")
            return self._backend.play_sound_effect(effect_id)

    def stop_sound_effects(self) -> None:
        with self._lock:
            self._backend.stop_sound_effects()

    def stop(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            stream = self._stream
            thread = self._thread
            if stream is None:
                return
            self._stopping = True

        try:
            self._backend.stop_sound_effects()
            stream.close()
        finally:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=timeout)
            if thread is not None and thread.is_alive():
                raise RuntimeError(
                    "A rota de áudio anterior não encerrou a tempo; "
                    "a nova configuração não foi iniciada por segurança."
                )
            with self._lock:
                if self._stream is stream:
                    self._stream = None
                    self._thread = None
                    self._input_device = None
                    self._output_device = None
                    self._monitor_output = None
                    self._effects_output = None
                self._stopping = False

    def _run_stream(self, stream: AudioStream) -> None:
        error: Exception | None = None
        try:
            stream.run()
        except Exception as exc:  # Native audio errors must reach the UI safely.
            error = exc
        finally:
            self._backend.stop_sound_effects()
            deactivate = getattr(self._backend, "deactivate", None)
            if deactivate is not None:
                try:
                    deactivate()
                except Exception as exc:
                    if error is None:
                        error = exc
            with self._lock:
                expected_stop = self._stopping
                if self._stream is stream:
                    self._stream = None
                    self._thread = None
                    self._input_device = None
                    self._output_device = None
                    self._monitor_output = None
                self._stopping = False

        if error is not None and not expected_stop and self._on_error is not None:
            self._on_error(str(error))
