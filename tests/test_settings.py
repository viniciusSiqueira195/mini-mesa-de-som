from __future__ import annotations

import unittest

from mini_mesa.settings import ReverbSettings


class ReverbSettingsTests(unittest.TestCase):
    def test_defaults_are_safe_and_convert_to_backend_values(self) -> None:
        settings = ReverbSettings()

        self.assertEqual(settings.wet_level, 0.25)
        self.assertEqual(settings.room_size, 0.4)
        self.assertEqual(settings.damping, 0.5)

    def test_percentages_accept_both_limits(self) -> None:
        disabled = ReverbSettings(0)
        maximum = ReverbSettings(100)

        self.assertEqual(disabled.wet_level, 0.0)
        self.assertEqual(maximum.wet_level, 1.0)
        self.assertAlmostEqual(maximum.room_size, 0.85)
        self.assertAlmostEqual(maximum.damping, 0.35)

    def test_out_of_range_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReverbSettings(level_percent=101)

    def test_non_integer_value_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            ReverbSettings(level_percent=40.5)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
