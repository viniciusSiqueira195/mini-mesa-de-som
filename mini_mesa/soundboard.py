from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import soundfile as sf


_MAX_CUSTOM_FILE_BYTES = 256 * 1024 * 1024
_MAX_CUSTOM_SOUND_SECONDS = 10 * 60


def generate_horn_sound(sample_rate: int = 48000, duration: float = 0.5) -> np.ndarray:
    """Dual-tone car/air horn sound (440 Hz + 554 Hz)."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False, dtype=np.float32)
    tone1 = np.sin(2 * np.pi * 440 * t)
    tone2 = np.sin(2 * np.pi * 554.37 * t)
    envelope = np.exp(-3.0 * t)
    signal = 0.4 * (tone1 + tone2) * envelope
    return signal.astype(np.float32)


def generate_drums_sound(sample_rate: int = 48000) -> np.ndarray:
    """Synthesizes a classic 'Ba-dum-tss' drum hit."""
    total_len = int(sample_rate * 0.75)
    signal = np.zeros(total_len, dtype=np.float32)

    # Ba
    t_ba = np.linspace(0, 0.12, int(sample_rate * 0.12), endpoint=False, dtype=np.float32)
    freq_ba = 120.0 * np.exp(-15.0 * t_ba) + 50.0
    ba = np.sin(2 * np.pi * freq_ba * t_ba) * np.exp(-8.0 * t_ba) * 0.7

    # Dum
    t_dum = np.linspace(0, 0.15, int(sample_rate * 0.15), endpoint=False, dtype=np.float32)
    freq_dum = 200.0 * np.exp(-12.0 * t_dum) + 90.0
    noise_dum = np.random.uniform(-0.3, 0.3, len(t_dum)).astype(np.float32)
    dum = (np.sin(2 * np.pi * freq_dum * t_dum) * 0.5 + noise_dum) * np.exp(-10.0 * t_dum) * 0.7

    # Tss
    t_tss = np.linspace(0, 0.35, int(sample_rate * 0.35), endpoint=False, dtype=np.float32)
    noise_tss = np.random.uniform(-0.5, 0.5, len(t_tss)).astype(np.float32)
    tss = noise_tss * np.exp(-12.0 * t_tss) * 0.6

    idx_ba = 0
    idx_dum = int(sample_rate * 0.15)
    idx_tss = int(sample_rate * 0.35)

    signal[idx_ba : idx_ba + len(ba)] += ba
    signal[idx_dum : idx_dum + len(dum)] += dum
    signal[idx_tss : idx_tss + len(tss)] += tss

    return signal.astype(np.float32)


def generate_applause_sound(sample_rate: int = 48000, duration: float = 1.5) -> np.ndarray:
    """Synthesizes applause / clapping noise bursts."""
    num_samples = int(sample_rate * duration)
    signal = np.zeros(num_samples, dtype=np.float32)

    t = np.linspace(0, duration, num_samples, endpoint=False, dtype=np.float32)

    rng = np.random.default_rng(42)
    num_claps = 35
    for _ in range(num_claps):
        start_t = rng.uniform(0.0, duration - 0.1)
        start_idx = int(start_t * sample_rate)
        clap_len = int(sample_rate * 0.08)
        t_c = np.linspace(0, 0.08, clap_len, endpoint=False, dtype=np.float32)
        clap_noise = rng.uniform(-1.0, 1.0, clap_len).astype(np.float32)
        clap_env = np.exp(-40.0 * t_c) * rng.uniform(0.3, 0.8)
        end_idx = min(start_idx + clap_len, num_samples)
        actual_len = end_idx - start_idx
        signal[start_idx:end_idx] += clap_noise[:actual_len] * clap_env[:actual_len]

    fade_in = np.minimum(1.0, t / 0.1)
    fade_out = np.minimum(1.0, (duration - t) / 0.3)
    signal *= fade_in * fade_out * 0.6
    return signal.astype(np.float32)


def generate_siren_sound(sample_rate: int = 48000, duration: float = 1.2) -> np.ndarray:
    """Synthesizes a dual-tone police siren sweep."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False, dtype=np.float32)
    freq = 600.0 + 400.0 * np.sin(2 * np.pi * 2.0 * t)
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate
    signal = 0.5 * np.sin(phase) * (0.8 + 0.2 * np.sin(2 * np.pi * 10.0 * t))
    return signal.astype(np.float32)


class SoundboardManager:
    """Manages real-time soundboard audio buffer playing and mixing into the audio engine."""

    def __init__(self, sample_rate: int = 48000) -> None:
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._active_buffer: np.ndarray | None = None
        self._active_offset = 0
        self._volume = 0.8
        self._builtins: dict[str, np.ndarray] = {}
        self._preload_builtins()

    def _preload_builtins(self) -> None:
        self._builtins["horn"] = generate_horn_sound(self.sample_rate)
        self._builtins["drums"] = generate_drums_sound(self.sample_rate)
        self._builtins["claps"] = generate_applause_sound(self.sample_rate)
        self._builtins["siren"] = generate_siren_sound(self.sample_rate)

    def set_sample_rate(self, sample_rate: int) -> None:
        sample_rate = int(sample_rate)
        if sample_rate <= 0:
            raise ValueError("A taxa de amostragem deve ser positiva.")
        if sample_rate == self.sample_rate:
            return

        builtins = {
            "horn": generate_horn_sound(sample_rate),
            "drums": generate_drums_sound(sample_rate),
            "claps": generate_applause_sound(sample_rate),
            "siren": generate_siren_sound(sample_rate),
        }
        with self._lock:
            self.sample_rate = sample_rate
            self._builtins = builtins
            self._active_buffer = None
            self._active_offset = 0

    def set_volume_percent(self, percent: int) -> None:
        val = max(0, min(100, int(percent)))
        with self._lock:
            self._volume = val / 100.0

    def play(self, sound_id_or_path: str) -> bool:
        sound_key = sound_id_or_path.lower().strip()
        data: np.ndarray | None = None

        if sound_key in self._builtins:
            data = self._builtins[sound_key]
        else:
            path = Path(sound_id_or_path)
            if path.exists() and path.is_file():
                try:
                    if path.stat().st_size > _MAX_CUSTOM_FILE_BYTES:
                        return False
                    file_info = sf.info(str(path))
                    if (
                        file_info.samplerate <= 0
                        or file_info.frames / file_info.samplerate
                        > _MAX_CUSTOM_SOUND_SECONDS
                    ):
                        return False
                    audio_data, file_sr = sf.read(str(path), dtype="float32")
                    if audio_data.ndim == 2:
                        audio_data = np.mean(audio_data, axis=1)
                    if file_sr != self.sample_rate:
                        num_samples = int(len(audio_data) * self.sample_rate / file_sr)
                        audio_data = np.interp(
                            np.linspace(0, len(audio_data), num_samples, endpoint=False),
                            np.arange(len(audio_data)),
                            audio_data,
                        ).astype(np.float32)
                    data = audio_data
                except Exception:
                    return False

        if data is None or len(data) == 0:
            return False

        with self._lock:
            self._active_buffer = data
            self._active_offset = 0
        return True

    def mix_into(self, target_mono: np.ndarray) -> None:
        """Mix active soundboard buffer into target mono float32 array in place."""
        rendered = self.render(len(target_mono))
        if rendered is not None:
            target_mono += rendered

    def stop(self) -> None:
        """Discard any active sound so it cannot resume on a later route."""
        with self._lock:
            self._active_buffer = None
            self._active_offset = 0

    def render(self, frames: int) -> np.ndarray | None:
        """Return the next soundboard block without mixing it into microphone audio."""
        with self._lock:
            if self._active_buffer is None:
                return None
            remaining = len(self._active_buffer) - self._active_offset
            if remaining <= 0:
                self._active_buffer = None
                self._active_offset = 0
                return None

            chunk_len = min(frames, remaining)
            chunk = self._active_buffer[self._active_offset : self._active_offset + chunk_len]
            output = np.zeros(frames, dtype=np.float32)
            output[:chunk_len] = chunk * self._volume

            self._active_offset += chunk_len
            if self._active_offset >= len(self._active_buffer):
                self._active_buffer = None
                self._active_offset = 0
            return output
