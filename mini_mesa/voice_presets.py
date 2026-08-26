from __future__ import annotations

from enum import Enum

import numpy as np


class VoicePreset(str, Enum):
    NATURAL = "natural"
    FEMININE = "feminine"
    MASCULINE = "masculine"
    ELDERLY_WOMAN = "elderly_woman"
    ELDERLY_MAN = "elderly_man"

    @property
    def label(self) -> str:
        return {
            self.NATURAL: "Natural, sem alteração",
            self.FEMININE: "Feminina suave",
            self.MASCULINE: "Masculina grave",
            self.ELDERLY_WOMAN: "Idosa trêmula",
            self.ELDERLY_MAN: "Idoso rouco",
        }[self]

    @property
    def semitones(self) -> float:
        return {
            self.NATURAL: 0.0,
            self.FEMININE: 3.5,
            self.MASCULINE: -3.5,
            self.ELDERLY_WOMAN: 1.5,
            self.ELDERLY_MAN: -1.5,
        }[self]

    @property
    def tremolo(self) -> tuple[float, float]:
        if self in (self.ELDERLY_WOMAN, self.ELDERLY_MAN):
            return 5.2, 0.12
        return 0.0, 0.0

    @classmethod
    def from_value(cls, value: object) -> VoicePreset:
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                pass
        return cls.NATURAL


class StreamingVoicePreset:
    """Realtime two-head delay-line pitch shifter for playful voice presets."""

    def __init__(
        self,
        preset: VoicePreset,
        sample_rate: float,
        *,
        window_milliseconds: float = 30.0,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")
        if window_milliseconds < 10:
            raise ValueError("A janela de voz deve ter ao menos 10 milissegundos.")
        self.preset = preset
        self._sample_rate = float(sample_rate)
        self._window_frames = max(
            128, round(self._sample_rate * window_milliseconds / 1000)
        )
        self._minimum_delay = max(16, round(self._sample_rate * 0.002))
        self._ring = np.zeros(self._window_frames * 2 + 8192, dtype=np.float32)
        self._sample_cursor = 0
        self._grain_phase = 0.0
        self._tremolo_phase = 0.0

    @property
    def latency_frames(self) -> int:
        if self.preset is VoicePreset.NATURAL:
            return 0
        return self._minimum_delay + self._window_frames // 2

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        if self.preset is VoicePreset.NATURAL or mono.size == 0:
            return mono.copy()

        positions = self._sample_cursor + np.arange(mono.size, dtype=np.int64)
        self._ring[positions % self._ring.size] = mono

        pitch_factor = 2.0 ** (self.preset.semitones / 12.0)
        phase_step = abs(1.0 - pitch_factor) / self._window_frames
        phases = (self._grain_phase + phase_step * np.arange(mono.size)) % 1.0
        second_phases = (phases + 0.5) % 1.0
        delay_a = self._delays(phases, pitch_factor)
        delay_b = self._delays(second_phases, pitch_factor)
        tap_a = self._read_interpolated(positions - delay_a)
        tap_b = self._read_interpolated(positions - delay_b)

        weight_a = 0.5 - 0.5 * np.cos(2.0 * np.pi * phases)
        shifted = tap_a * weight_a + tap_b * (1.0 - weight_a)
        self._grain_phase = float((phases[-1] + phase_step) % 1.0)
        self._sample_cursor += mono.size
        return self._apply_tremolo(shifted.astype(np.float32))

    def _delays(self, phases: np.ndarray, pitch_factor: float) -> np.ndarray:
        direction = phases if pitch_factor < 1.0 else 1.0 - phases
        return self._minimum_delay + direction * self._window_frames

    def _read_interpolated(self, positions: np.ndarray) -> np.ndarray:
        before = np.floor(positions).astype(np.int64)
        amount = positions - before
        first = self._ring[before % self._ring.size]
        second = self._ring[(before + 1) % self._ring.size]
        return first * (1.0 - amount) + second * amount

    def _apply_tremolo(self, samples: np.ndarray) -> np.ndarray:
        frequency, depth = self.preset.tremolo
        if not depth:
            return samples
        phases = self._tremolo_phase + (
            2.0 * np.pi * frequency * np.arange(samples.size) / self._sample_rate
        )
        gain = 1.0 - depth / 2.0 + (depth / 2.0) * np.sin(phases)
        self._tremolo_phase = float(
            (phases[-1] + 2.0 * np.pi * frequency / self._sample_rate)
            % (2.0 * np.pi)
        )
        return (samples * gain).astype(np.float32)
