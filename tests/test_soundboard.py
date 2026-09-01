from __future__ import annotations

import unittest
import numpy as np

from mini_mesa.settings import SoundboardSettings
from mini_mesa.soundboard import (
    SoundboardManager,
    generate_applause_sound,
    generate_drums_sound,
    generate_horn_sound,
    generate_siren_sound,
)


class SoundboardTests(unittest.TestCase):
    def test_synth_generators_return_valid_float32(self) -> None:
        sr = 48000
        horn = generate_horn_sound(sr)
        drums = generate_drums_sound(sr)
        claps = generate_applause_sound(sr)
        siren = generate_siren_sound(sr)

        for name, arr in [("horn", horn), ("drums", drums), ("claps", claps), ("siren", siren)]:
            self.assertEqual(arr.dtype, np.float32)
            self.assertGreater(len(arr), 0)
            self.assertLessEqual(np.max(np.abs(arr)), 1.5, f"{name} volume peak out of bounds")

    def test_soundboard_manager_play_and_mix(self) -> None:
        mgr = SoundboardManager(48000)
        self.assertTrue(mgr.play("horn"))

        target = np.zeros(256, dtype=np.float32)
        mgr.mix_into(target)
        self.assertTrue(np.any(target != 0.0))

    def test_soundboard_regenerates_builtins_for_the_active_sample_rate(self) -> None:
        mgr = SoundboardManager(48000)

        mgr.set_sample_rate(44100)

        self.assertEqual(mgr.sample_rate, 44100)
        self.assertEqual(len(mgr._builtins["horn"]), 22050)

    def test_soundboard_manager_unknown_sound(self) -> None:
        mgr = SoundboardManager(48000)
        self.assertFalse(mgr.play("non_existent_sound_12345"))

    def test_stopping_discards_the_active_sound(self) -> None:
        mgr = SoundboardManager(48000)
        self.assertTrue(mgr.play("horn"))

        mgr.stop()

        self.assertIsNone(mgr.render(256))

    def test_applause_generation_does_not_reset_numpy_global_random_state(self) -> None:
        np.random.seed(1234)
        expected = np.random.random(4)
        np.random.seed(1234)

        generate_applause_sound(48000)
        actual = np.random.random(4)

        np.testing.assert_allclose(actual, expected)

    def test_soundboard_settings_validation(self) -> None:
        settings = SoundboardSettings(
            volume_percent=80, ducking_enabled=True, ducking_percent=55
        )
        self.assertEqual(settings.volume_percent, 80)
        self.assertTrue(settings.ducking_enabled)
        self.assertEqual(settings.ducking_percent, 55)

        with self.assertRaises(ValueError):
            SoundboardSettings(volume_percent=120)

        with self.assertRaises(TypeError):
            SoundboardSettings(volume_percent="high")  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            SoundboardSettings(ducking_percent=120)


if __name__ == "__main__":
    unittest.main()
