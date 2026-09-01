from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from .settings import SpatialSettings


_ANGLES = (0, 45, 90, 135, 180)
_TRANSITION_MILLISECONDS = 20
_AUTOMATIC_PATH = (
    (0, 0, 100),    # front
    (100, 0, 0),    # right
    (0, 0, -100),   # behind
    (-100, 0, 0),   # left
    (0, 100, 0),    # above
    (0, -100, 0),   # below
)


class HRTFSpatializer:
    """Streaming binaural convolution using the compact MIT KEMAR HRIRs."""

    def __init__(self, sample_rate: float, asset_directory: Path | None = None) -> None:
        if sample_rate <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")
        self._sample_rate = float(sample_rate)
        self._asset_directory = asset_directory or (
            Path(__file__).parent / "assets" / "hrtf" / "mit_kemar"
        )
        self._filters = {
            angle: self._load_filter(angle) for angle in _ANGLES
        }
        filter_length = next(iter(self._filters.values())).shape[1]
        self._history = np.zeros(max(0, filter_length - 1), dtype=np.float32)
        self._settings = SpatialSettings()
        self._current_filter = self._filters[0]
        self._previous_filter = self._current_filter
        self._current_mix = 0.0
        self._previous_mix = 0.0
        self._transition_frames = max(
            1, round(self._sample_rate * _TRANSITION_MILLISECONDS / 1000)
        )
        self._transition_remaining = 0
        self._automatic_progress = 0.0

    @property
    def settings(self) -> SpatialSettings:
        return self._settings

    def update(self, settings: SpatialSettings) -> None:
        if settings == self._settings:
            return
        self._previous_filter, self._previous_mix = self._effective_target()
        self._current_filter = self._filter_for_position(
            settings.x,
            settings.y,
            settings.z,
        )
        self._current_mix = 1.0 if settings.enabled else 0.0
        if settings.automatic and not self._settings.automatic:
            self._automatic_progress = 0.0
        self._settings = settings
        self._transition_remaining = self._transition_frames

    def _effective_target(self) -> tuple[np.ndarray, float]:
        if not self._transition_remaining:
            return self._current_filter, self._current_mix
        amount = 1.0 - self._transition_remaining / self._transition_frames
        effective_filter = (
            self._previous_filter * (1.0 - amount)
            + self._current_filter * amount
        ).astype(np.float32)
        effective_mix = self._previous_mix * (1.0 - amount) + self._current_mix * amount
        return effective_filter, effective_mix

    def process(self, mono_samples: np.ndarray) -> np.ndarray:
        mono = np.asarray(mono_samples, dtype=np.float32).reshape(-1)
        if mono.size == 0:
            return np.empty((0, 2), dtype=np.float32)

        if self._settings.enabled and self._settings.automatic:
            x, y, z = self._next_automatic_position(mono.size)
            self._retarget_position(x, y, z)

        dry = np.column_stack((mono, mono))
        current = self._convolve(mono, self._current_filter)
        target = dry * (1.0 - self._current_mix) + current * self._current_mix

        if self._transition_remaining:
            previous = self._convolve(mono, self._previous_filter)
            previous = dry * (1.0 - self._previous_mix) + previous * self._previous_mix
            transition_count = min(mono.size, self._transition_remaining)
            start = self._transition_frames - self._transition_remaining
            amounts = (
                np.arange(start + 1, start + transition_count + 1, dtype=np.float32)
                / self._transition_frames
            )
            target[:transition_count] = (
                previous[:transition_count] * (1.0 - amounts[:, None])
                + target[:transition_count] * amounts[:, None]
            )
            self._transition_remaining -= transition_count

        history_length = self._history.size
        if history_length:
            extended = np.concatenate((self._history, mono))
            self._history = extended[-history_length:].copy()
        return target.astype(np.float32, copy=False)

    def _next_automatic_position(self, frame_count: int) -> tuple[int, int, int]:
        """Advance a smooth 3D orbit using audio frames as the clock."""

        segments_per_second = 0.25 + 1.75 * self._settings.speed_percent / 100.0
        progress_increment = (
            segments_per_second * frame_count / self._sample_rate
        )
        midpoint = self._automatic_progress + progress_increment / 2.0
        self._automatic_progress = (
            self._automatic_progress + progress_increment
        ) % len(_AUTOMATIC_PATH)
        start_index = int(midpoint) % len(_AUTOMATIC_PATH)
        end_index = (start_index + 1) % len(_AUTOMATIC_PATH)
        amount = midpoint % 1.0
        start = _AUTOMATIC_PATH[start_index]
        end = _AUTOMATIC_PATH[end_index]
        return tuple(
            round(start[axis] * (1.0 - amount) + end[axis] * amount)
            for axis in range(3)
        )

    def _retarget_position(self, x: int, y: int, z: int) -> None:
        new_filter = self._filter_for_position(x, y, z)
        self._previous_filter, self._previous_mix = self._effective_target()
        self._current_filter = new_filter
        self._transition_remaining = self._transition_frames

    def _filter_for_position(self, x: int, y: int, z: int) -> np.ndarray:
        azimuth = 0 if x == 0 and z == 0 else round(
            math.degrees(math.atan2(x, z))
        )
        horizontal_distance = math.hypot(x, z)
        elevation = 0.0 if y == 0 and horizontal_distance == 0 else math.degrees(
            math.atan2(y, horizontal_distance)
        )
        filters = self._filter_for_angle(azimuth)
        elevation_amount = max(-1.0, min(1.0, elevation / 90.0))
        if elevation_amount == 0.0:
            return filters

        delayed = np.pad(filters, ((0, 0), (1, 0)), mode="constant")[:, :-1]
        if elevation_amount > 0.0:
            # A subtle high-frequency emphasis approximates the pinna cue above.
            filters = filters + (filters - delayed) * (0.22 * elevation_amount)
        else:
            # A subtle low-pass cue distinguishes positions below the listener.
            amount = 0.20 * abs(elevation_amount)
            filters = filters * (1.0 - amount) + delayed * amount
        return self._normalize(filters)

    def _convolve(self, mono: np.ndarray, filters: np.ndarray) -> np.ndarray:
        extended = np.concatenate((self._history, mono))
        start = filters.shape[1] - 1
        channels = [
            np.convolve(extended, channel, mode="full")[start : start + mono.size]
            for channel in filters
        ]
        return np.column_stack(channels).astype(np.float32, copy=False)

    def _filter_for_angle(self, angle_degrees: int) -> np.ndarray:
        absolute_angle = abs(angle_degrees)
        upper_index = int(np.searchsorted(_ANGLES, absolute_angle, side="left"))
        if upper_index == 0:
            result = self._filters[_ANGLES[0]].copy()
        elif upper_index >= len(_ANGLES):
            result = self._filters[_ANGLES[-1]].copy()
        else:
            lower = _ANGLES[upper_index - 1]
            upper = _ANGLES[upper_index]
            amount = (absolute_angle - lower) / (upper - lower)
            result = (
                self._filters[lower] * (1.0 - amount)
                + self._filters[upper] * amount
            ).astype(np.float32)
        if angle_degrees < 0:
            result = result[::-1].copy()
        return self._normalize(result)

    def _load_filter(self, angle: int) -> np.ndarray:
        path = self._asset_directory / f"H0e{angle:03d}a.wav"
        try:
            with wave.open(str(path), "rb") as hrir_file:
                if hrir_file.getnchannels() != 2 or hrir_file.getsampwidth() != 2:
                    raise ValueError(f"HRIR incompatível: {path.name}")
                source_rate = hrir_file.getframerate()
                frames = hrir_file.readframes(hrir_file.getnframes())
        except OSError as exc:
            raise RuntimeError(f"Não foi possível carregar o HRTF {path.name}.") from exc

        stereo = (
            np.frombuffer(frames, dtype="<i2")
            .reshape(-1, 2)
            .astype(np.float32)
            / 32768.0
        ).T
        if source_rate != round(self._sample_rate):
            stereo = self._resample(stereo, source_rate, self._sample_rate)
        return self._normalize(stereo)

    @staticmethod
    def _resample(filters: np.ndarray, source_rate: float, target_rate: float) -> np.ndarray:
        target_length = max(2, round(filters.shape[1] * target_rate / source_rate))
        old_positions = np.linspace(0.0, 1.0, filters.shape[1])
        new_positions = np.linspace(0.0, 1.0, target_length)
        return np.vstack(
            [np.interp(new_positions, old_positions, channel) for channel in filters]
        ).astype(np.float32)

    @staticmethod
    def _normalize(filters: np.ndarray) -> np.ndarray:
        fft_size = max(512, 1 << (filters.shape[1] - 1).bit_length())
        peak_response = float(np.max(np.abs(np.fft.rfft(filters, n=fft_size))))
        if peak_response > 1.0:
            filters = filters / peak_response
        return filters.astype(np.float32, copy=False)
