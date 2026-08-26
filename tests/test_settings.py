from __future__ import annotations

import unittest

from mini_mesa.settings import ReverbSettings, SpatialSettings


class ReverbSettingsTests(unittest.TestCase):
    def test_defaults_are_safe_and_convert_to_backend_values(self) -> None:
        settings = ReverbSettings()

        self.assertAlmostEqual(settings.wet_level, 0.18)
        self.assertAlmostEqual(settings.dry_level, 0.72)
        self.assertEqual(settings.room_size, 0.4)
        self.assertEqual(settings.damping, 0.5)

    def test_percentages_accept_both_limits(self) -> None:
        disabled = ReverbSettings(0)
        maximum = ReverbSettings(100)

        self.assertEqual(disabled.wet_level, 0.0)
        self.assertEqual(disabled.dry_level, 0.9)
        self.assertAlmostEqual(maximum.wet_level, 0.72)
        self.assertAlmostEqual(maximum.dry_level, 0.18)
        self.assertAlmostEqual(maximum.room_size, 0.85)
        self.assertAlmostEqual(maximum.damping, 0.35)

    def test_dry_and_wet_mix_always_preserves_headroom(self) -> None:
        for level in range(101):
            settings = ReverbSettings(level)
            self.assertAlmostEqual(settings.dry_level + settings.wet_level, 0.9)

    def test_disabled_reverb_keeps_the_dry_audio_flowing(self) -> None:
        settings = ReverbSettings(level_percent=100, enabled=False)

        self.assertEqual(settings.wet_level, 0.0)
        self.assertEqual(settings.dry_level, 0.9)

    def test_out_of_range_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReverbSettings(level_percent=101)

    def test_non_integer_value_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            ReverbSettings(level_percent=40.5)  # type: ignore[arg-type]

    def test_non_boolean_enabled_value_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            ReverbSettings(enabled=1)  # type: ignore[arg-type]


class SpatialSettingsTests(unittest.TestCase):
    def test_horizontal_position_accepts_the_full_circle(self) -> None:
        self.assertEqual(SpatialSettings(True, -180).angle_degrees, -180)
        self.assertEqual(SpatialSettings(True, 180).angle_degrees, 180)

    def test_invalid_horizontal_position_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SpatialSettings(True, 181)

        with self.assertRaises(TypeError):
            SpatialSettings(True, 45.5)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
