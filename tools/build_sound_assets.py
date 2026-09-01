"""Convert the locally downloaded personal sound pack to normalized WAV files."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile


SAMPLE_RATE = 48_000

SOURCES = {
    "pistol": "01-pistola.mp3",
    "machine_gun": "02-metralhadora.mp3",
    "applause": "02-palmas-show.mp3",
    "dj_horn": "03-buzina-dj.mp3",
    "sensational_brown": "05-sensacional-manobrown.mp3",
}

TARGET_PEAKS = {
    "pistol": 0.96,
    "machine_gun": 0.92,
    "applause": 0.72,
    "dj_horn": 0.88,
    "sensational_brown": 0.82,
}

MAXIMUM_DURATIONS = {
    "dj_horn": 4.0,
}


def _fade_and_normalize(audio: np.ndarray, *, peak: float = 0.72) -> np.ndarray:
    stereo = np.asarray(audio, dtype=np.float32)
    if stereo.ndim == 1:
        stereo = np.column_stack((stereo, stereo))
    elif stereo.shape[0] <= 2 and stereo.shape[0] < stereo.shape[1]:
        stereo = stereo.T
    if stereo.shape[1] == 1:
        stereo = np.repeat(stereo, 2, axis=1)
    stereo = stereo[:, :2]

    fade_frames = min(round(SAMPLE_RATE * 0.015), stereo.shape[0] // 2)
    if fade_frames:
        fade = np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
        stereo[:fade_frames] *= fade[:, None]
        stereo[-fade_frames:] *= fade[::-1, None]
    current_peak = float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if current_peak:
        stereo *= peak / current_peak
    return np.clip(stereo, -1.0, 1.0)


def _write_wave(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.asarray(np.clip(audio, -1.0, 1.0) * 32767.0, dtype="<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.tobytes())


def _read_source(
    source: Path,
    *,
    peak: float,
    maximum_duration: float | None = None,
) -> np.ndarray:
    with AudioFile(str(source)).resampled_to(SAMPLE_RATE) as audio_file:
        audio = audio_file.read(audio_file.frames)
    stereo = np.asarray(audio, dtype=np.float32).T
    magnitude = np.max(np.abs(stereo), axis=1)
    threshold = max(0.002, float(magnitude.max()) * 0.02)
    audible = np.flatnonzero(magnitude >= threshold)
    if audible.size:
        pre_roll = round(SAMPLE_RATE * 0.005)
        stereo = stereo[max(0, int(audible[0]) - pre_roll) :]
    if maximum_duration is not None:
        stereo = stereo[: round(SAMPLE_RATE * maximum_duration)]
    return _fade_and_normalize(stereo, peak=peak)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args()

    missing = [
        filename
        for filename in SOURCES.values()
        if not (arguments.source_directory / filename).is_file()
    ]
    if missing:
        parser.error("arquivos ausentes: " + ", ".join(missing))

    for effect_id, filename in SOURCES.items():
        source = arguments.source_directory / filename
        _write_wave(
            arguments.output_directory / f"{effect_id}.wav",
            _read_source(
                source,
                peak=TARGET_PEAKS[effect_id],
                maximum_duration=MAXIMUM_DURATIONS.get(effect_id),
            ),
        )


if __name__ == "__main__":
    main()
