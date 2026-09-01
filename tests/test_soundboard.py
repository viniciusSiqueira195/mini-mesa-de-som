from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from mini_mesa.soundboard import SoundboardMixer, SoundEffectError


def _write_test_wave(path: Path, samples: np.ndarray, sample_rate: int = 48_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mono = np.asarray(samples, dtype=np.float32)
    stereo = np.column_stack((mono, mono))
    pcm = np.asarray(np.clip(stereo, -1.0, 1.0) * 32767, dtype="<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


class SoundboardMixerTests(unittest.TestCase):
    def test_effect_is_mixed_across_successive_audio_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            _write_test_wave(
                assets / "dj_horn.wav",
                np.array([0.1, 0.2, 0.3], dtype=np.float32),
            )
            mixer = SoundboardMixer(assets)

            effect = mixer.trigger("dj_horn", 48_000)
            first = mixer.mix(2)
            second = mixer.mix(2)

            self.assertEqual(effect.name, "Buzina de DJ")
            np.testing.assert_allclose(first[:, 0], [0.1, 0.2], atol=0.0001)
            np.testing.assert_allclose(second[:, 0], [0.3, 0.0], atol=0.0001)

    def test_effect_is_resampled_to_the_active_audio_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            _write_test_wave(
                assets / "pistol.wav",
                np.linspace(0.0, 0.5, 4, dtype=np.float32),
                sample_rate=24_000,
            )
            mixer = SoundboardMixer(assets)

            mixer.trigger("pistol", 48_000)

            self.assertEqual(mixer.mix(8).shape, (8, 2))
            np.testing.assert_array_equal(mixer.mix(1), np.zeros((1, 2)))

    def test_stop_all_discards_every_active_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            _write_test_wave(assets / "applause.wav", np.ones(10, dtype=np.float32))
            mixer = SoundboardMixer(assets)
            mixer.trigger("applause", 48_000)

            mixer.stop_all()

            np.testing.assert_array_equal(mixer.mix(4), np.zeros((4, 2)))

    def test_all_personal_effects_are_exposed_with_direct_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mixer = SoundboardMixer(Path(directory))

            effects = mixer.effects()

            self.assertEqual(len(effects), 5)
            self.assertEqual([effect.shortcut for effect in effects], [
                "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5",
            ])

    def test_missing_personal_effect_has_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mixer = SoundboardMixer(Path(directory))

            with self.assertRaisesRegex(
                SoundEffectError,
                "sensational_brown.*não foi instalado",
            ):
                mixer.trigger("sensational_brown", 48_000)


if __name__ == "__main__":
    unittest.main()
