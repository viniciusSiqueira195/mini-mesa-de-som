from __future__ import annotations

import threading
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .preferences import default_preferences_path, legacy_preferences_paths


_MAX_CUSTOM_FILE_BYTES = 256 * 1024 * 1024
_MAX_CUSTOM_SOUND_SECONDS = 10 * 60
_MAX_SIMULTANEOUS_PLAYBACKS = 8


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
        "machine_gun", "Metralhadora", "Ctrl+2", "Rajada curta de metralhadora"
    ),
    SoundEffectInfo("applause", "Palmas", "Ctrl+3", "Palmas de encerramento de show"),
    SoundEffectInfo(
        "dj_horn", "Buzina de DJ", "Ctrl+4", "Air horn de DJ com quatro segundos"
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
    """Prepare sounds off-callback and mix several active playbacks safely."""

    def __init__(
        self,
        asset_directory: Path | None = None,
        *,
        sample_rate: int = 48_000,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")
        self.sample_rate = int(sample_rate)
        if asset_directory is not None:
            self._personal_directories = (asset_directory,)
        else:
            self._personal_directories = (
                default_preferences_path().parent / "sounds",
                *(path.parent / "sounds" for path in legacy_preferences_paths()),
            )
        self._bundled_directory = Path(__file__).parent / "assets" / "sounds"
        self._active: list[_Playback] = []
        self._builtins: dict[str, np.ndarray] = {}
        self._volume = 0.8
        self._lock = threading.Lock()

    def effects(self) -> Sequence[SoundEffectInfo]:
        return _EFFECTS

    def set_sample_rate(self, sample_rate: int) -> None:
        value = int(sample_rate)
        if value <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")
        with self._lock:
            if value != self.sample_rate:
                self.sample_rate = value
                self._active.clear()

    def set_volume_percent(self, percent: int) -> None:
        value = max(0, min(100, int(percent)))
        with self._lock:
            self._volume = value / 100.0

    def trigger(
        self, effect_id: str, sample_rate: float | None = None
    ) -> SoundEffectInfo:
        effect = next((item for item in _EFFECTS if item.effect_id == effect_id), None)
        if effect is None:
            raise ValueError(f"Efeito desconhecido: {effect_id}")
        target_rate = float(self.sample_rate if sample_rate is None else sample_rate)
        if target_rate <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")
        audio, source_rate = _read_wave(self._effect_path(effect_id))
        self._append(_resample(audio, source_rate, target_rate))
        return effect

    def play(self, sound_id_or_path: str) -> bool:
        """Play a bundled/personal effect id or a safe custom audio file."""

        key = sound_id_or_path.strip()
        builtin = self._builtins.get(key.lower())
        if builtin is not None:
            prepared = np.asarray(builtin, dtype=np.float32)
            if prepared.ndim == 1:
                prepared = np.column_stack((prepared, prepared))
            if prepared.ndim != 2 or prepared.shape[1] != 2 or prepared.size == 0:
                return False
            self._append(prepared.copy())
            return True
        if any(effect.effect_id == key.lower() for effect in _EFFECTS):
            try:
                self.trigger(key.lower())
            except (OSError, ValueError, SoundEffectError):
                return False
            return True
        try:
            audio, source_rate = _read_custom_audio(Path(key))
            prepared = _resample(audio, source_rate, float(self.sample_rate))
        except (OSError, ValueError, SoundEffectError):
            return False
        if prepared.size == 0:
            return False
        self._append(prepared)
        return True

    def stop_all(self) -> None:
        with self._lock:
            self._active.clear()

    def stop(self) -> None:
        self.stop_all()

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
                    ] * self._volume
                    playback.position += available
                if playback.position < playback.audio.shape[0]:
                    remaining.append(playback)
            self._active = remaining
        return np.clip(output, -1.0, 1.0)

    def render(self, frames: int) -> np.ndarray | None:
        mixed = self.mix(frames)
        if not np.any(mixed):
            return None
        return mixed.mean(axis=1, dtype=np.float32)

    def mix_into(self, target_mono: np.ndarray) -> None:
        rendered = self.render(len(target_mono))
        if rendered is not None:
            target_mono += rendered

    def _append(self, audio: np.ndarray) -> None:
        with self._lock:
            self._active.append(_Playback(audio.astype(np.float32, copy=False)))
            if len(self._active) > _MAX_SIMULTANEOUS_PLAYBACKS:
                del self._active[:-_MAX_SIMULTANEOUS_PLAYBACKS]

    def _effect_path(self, effect_id: str) -> Path:
        for personal_directory in self._personal_directories:
            personal_path = personal_directory / f"{effect_id}.wav"
            if personal_path.is_file():
                return personal_path
        bundled_path = self._bundled_directory / f"{effect_id}.wav"
        if bundled_path.is_file():
            return bundled_path
        raise SoundEffectError(
            f"O arquivo do efeito '{effect_id}' não foi instalado em "
            f"'{self._personal_directories[0]}'."
        )


class SoundboardManager(SoundboardMixer):
    """Compatibility name retained for Paulo's audio-engine integration."""

    def __init__(self, sample_rate: int = 48_000) -> None:
        super().__init__(sample_rate=sample_rate)


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


def _read_custom_audio(path: Path) -> tuple[np.ndarray, float]:
    if not path.is_file() or path.stat().st_size > _MAX_CUSTOM_FILE_BYTES:
        raise SoundEffectError("Arquivo de som personalizado inválido ou muito grande.")
    try:
        info = sf.info(str(path))
        if info.samplerate <= 0 or info.frames / info.samplerate > _MAX_CUSTOM_SOUND_SECONDS:
            raise SoundEffectError("O som personalizado ultrapassa dez minutos.")
        audio, source_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SoundEffectError("Não foi possível carregar o som personalizado.") from exc
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]
    return audio.astype(np.float32, copy=False), float(source_rate)


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
