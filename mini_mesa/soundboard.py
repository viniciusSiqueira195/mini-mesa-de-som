from __future__ import annotations

import threading
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .preferences import default_preferences_path


@dataclass(frozen=True, slots=True)
class SoundEffectInfo:
    effect_id: str
    name: str
    shortcut: str
    description: str


@dataclass(slots=True)
class _Playback:
    audio: np.ndarray
    position: int = 0


_EFFECTS = (
    SoundEffectInfo("pistol", "Pistola", "Ctrl+1", "Disparo único e forte de pistola"),
    SoundEffectInfo(
        "machine_gun",
        "Metralhadora",
        "Ctrl+2",
        "Rajada curta de metralhadora",
    ),
    SoundEffectInfo("applause", "Palmas", "Ctrl+3", "Palmas de encerramento de show"),
    SoundEffectInfo(
        "dj_horn",
        "Buzina de DJ",
        "Ctrl+4",
        "Air horn de DJ com quatro segundos",
    ),
    SoundEffectInfo(
        "sensational_brown",
        "Sensacional! — Mano Brown",
        "Ctrl+5",
        "Trecho com a voz de Mano Brown",
    ),
)


class SoundEffectError(RuntimeError):
    """Raised when a sound effect cannot be prepared for playback."""


class SoundboardMixer:
    """Load effects outside the audio callback and mix active playbacks safely."""

    def __init__(
        self,
        asset_directory: Path | None = None,
    ) -> None:
        self._personal_directory = asset_directory or (
            default_preferences_path().parent / "sounds"
        )
        self._bundled_directory = Path(__file__).parent / "assets" / "sounds"
        self._active: list[_Playback] = []
        self._lock = threading.Lock()

    def effects(self) -> Sequence[SoundEffectInfo]:
        return _EFFECTS

    def trigger(self, effect_id: str, sample_rate: float) -> SoundEffectInfo:
        effect = next((item for item in _EFFECTS if item.effect_id == effect_id), None)
        if effect is None:
            raise ValueError(f"Efeito desconhecido: {effect_id}")
        if sample_rate <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")

        path = self._effect_path(effect_id)
        audio, source_rate = _read_wave(path)
        prepared = _resample(audio, source_rate, float(sample_rate))
        with self._lock:
            self._active.append(_Playback(prepared))
            if len(self._active) > 8:
                del self._active[:-8]
        return effect

    def stop_all(self) -> None:
        with self._lock:
            self._active.clear()

    def mix(self, frame_count: int) -> np.ndarray:
        if frame_count < 0:
            raise ValueError("A quantidade de quadros não pode ser negativa.")
        output = np.zeros((frame_count, 2), dtype=np.float32)
        with self._lock:
            remaining: list[_Playback] = []
            for playback in self._active:
                available = min(frame_count, playback.audio.shape[0] - playback.position)
                if available > 0:
                    output[:available] += playback.audio[
                        playback.position : playback.position + available
                    ]
                    playback.position += available
                if playback.position < playback.audio.shape[0]:
                    remaining.append(playback)
            self._active = remaining
        return np.clip(output, -1.0, 1.0)

    def _effect_path(self, effect_id: str) -> Path:
        personal_path = self._personal_directory / f"{effect_id}.wav"
        if personal_path.is_file():
            return personal_path
        bundled_path = self._bundled_directory / f"{effect_id}.wav"
        if bundled_path.is_file():
            return bundled_path
        raise SoundEffectError(
            f"O arquivo do efeito '{effect_id}' não foi instalado em "
            f"'{self._personal_directory}'."
        )


def _read_wave(path: Path) -> tuple[np.ndarray, float]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = float(source.getframerate())
            frames = source.readframes(source.getnframes())
    except (OSError, wave.Error) as exc:
        raise SoundEffectError(f"Não foi possível carregar o efeito '{path.name}'.") from exc
    if channels not in (1, 2) or sample_width != 2:
        raise SoundEffectError(
            f"O efeito '{path.name}' precisa ser WAV de 16 bits, mono ou estéreo."
        )
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    audio = audio.reshape(-1, channels)
    if channels == 1:
        audio = np.repeat(audio, 2, axis=1)
    return audio, sample_rate


def _resample(audio: np.ndarray, source_rate: float, target_rate: float) -> np.ndarray:
    if source_rate == target_rate or audio.shape[0] < 2:
        return audio.astype(np.float32, copy=True)
    target_length = max(1, round(audio.shape[0] * target_rate / source_rate))
    source_positions = np.linspace(0.0, 1.0, audio.shape[0])
    target_positions = np.linspace(0.0, 1.0, target_length)
    return np.column_stack(
        [
            np.interp(target_positions, source_positions, audio[:, channel])
            for channel in range(2)
        ]
    ).astype(np.float32)
