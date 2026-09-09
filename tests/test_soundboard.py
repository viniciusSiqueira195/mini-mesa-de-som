from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from mini_mesa.settings import SoundboardSettings
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
            _write_test_wave(assets / "dj_horn.wav", np.array([0.1, 0.2, 0.3]))
            mixer = SoundboardMixer(assets)
            mixer.set_volume_percent(100)

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
                assets / "pistol.wav", np.linspace(0.0, 0.5, 4), sample_rate=24_000
            )
            mixer = SoundboardMixer(assets)
            mixer.trigger("pistol", 48_000)
            self.assertEqual(mixer.mix(8).shape, (8, 2))
            np.testing.assert_array_equal(mixer.mix(1), np.zeros((1, 2)))

    def test_multiple_effects_are_mixed_simultaneously(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            _write_test_wave(assets / "pistol.wav", np.full(4, 0.1))
            _write_test_wave(assets / "applause.wav", np.full(4, 0.2))
            mixer = SoundboardMixer(assets)
            mixer.set_volume_percent(100)
            mixer.trigger("pistol")
            mixer.trigger("applause")
            np.testing.assert_allclose(mixer.mix(4), np.full((4, 2), 0.3), atol=0.0001)

    def test_retriggering_the_same_effect_restarts_instead_of_layering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            _write_test_wave(assets / "pistol.wav", np.array([0.1, 0.2, 0.3]))
            mixer = SoundboardMixer(assets)
            mixer.set_volume_percent(100)

            mixer.trigger("pistol")
            np.testing.assert_allclose(mixer.mix(1)[:, 0], [0.1], atol=0.0001)
            mixer.trigger("pistol")

            np.testing.assert_allclose(
                mixer.mix(3)[:, 0], [0.1, 0.2, 0.3], atol=0.0001
            )

    def test_custom_audio_file_is_loaded_and_resampled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.flac"
            sf.write(path, np.full(120, 0.25, dtype=np.float32), 24_000)
            mixer = SoundboardMixer(sample_rate=48_000)
            mixer.set_volume_percent(100)

            self.assertTrue(mixer.play(str(path)))
            rendered = mixer.mix(240)

            self.assertEqual(rendered.shape, (240, 2))
            self.assertTrue(np.any(rendered))

    def test_volume_and_stop_apply_to_all_active_sounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            _write_test_wave(assets / "applause.wav", np.ones(10))
            mixer = SoundboardMixer(assets)
            mixer.set_volume_percent(25)
            mixer.trigger("applause")
            np.testing.assert_allclose(mixer.mix(2), np.full((2, 2), 0.25), atol=0.0001)
            mixer.stop_all()
            np.testing.assert_array_equal(mixer.mix(4), np.zeros((4, 2)))

    def test_all_personal_effects_are_exposed_with_direct_shortcuts(self) -> None:
        mixer = SoundboardMixer(Path("missing-test-assets"))
        effects = mixer.effects()
        self.assertEqual(len(effects), 5)
        self.assertEqual(
            [effect.shortcut for effect in effects],
            ["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5"],
        )

    def test_missing_personal_effect_has_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mixer = SoundboardMixer(Path(directory))
            with self.assertRaisesRegex(SoundEffectError, "sensational_brown.*não foi instalado"):
                mixer.trigger("sensational_brown")

    def test_personal_effects_from_the_legacy_test_directory_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_preferences = root / "Mini Mesa de Som" / "preferences.json"
            legacy_preferences = (
                root / "Mini Mesa de Som Teste" / "preferences.json"
            )
            _write_test_wave(
                legacy_preferences.parent / "sounds" / "pistol.wav",
                np.full(4, 0.2),
            )
            with (
                patch(
                    "mini_mesa.soundboard.default_preferences_path",
                    return_value=current_preferences,
                ),
                patch(
                    "mini_mesa.soundboard.legacy_preferences_paths",
                    return_value=(legacy_preferences,),
                ),
            ):
                mixer = SoundboardMixer()
                mixer.set_volume_percent(100)

            mixer.trigger("pistol")

            np.testing.assert_allclose(mixer.mix(4), np.full((4, 2), 0.2), atol=0.0001)

    def test_soundboard_settings_validation(self) -> None:
        settings = SoundboardSettings(
            volume_percent=80, ducking_enabled=True, ducking_percent=55
        )
        self.assertTrue(settings.ducking_enabled)
        with self.assertRaises(ValueError):
            SoundboardSettings(volume_percent=120)
        with self.assertRaises(ValueError):
            SoundboardSettings(ducking_percent=120)


if __name__ == "__main__":
    unittest.main()
