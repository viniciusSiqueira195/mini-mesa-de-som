from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mini_mesa.preferences import AppPreferences, PreferencesStore


class PreferencesStoreTests(unittest.TestCase):
    def test_preferences_round_trip_as_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            store = PreferencesStore(path)
            expected = AppPreferences(
                input_device="Microfone Áudio",
                output_device="CABLE Input",
                monitor_enabled=True,
                monitor_device="Fones",
                reverb_enabled=False,
                reverb_level=72,
                noise_reduction_enabled=True,
            )

            store.save(expected)

            self.assertEqual(store.load(), expected)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 2)
            self.assertEqual(saved["input_device"], "Microfone Áudio")

    def test_invalid_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text("{isto não é json", encoding="utf-8")

            self.assertEqual(PreferencesStore(path).load(), AppPreferences())

    def test_invalid_fields_do_not_poison_valid_preferences(self) -> None:
        preferences = AppPreferences.from_dict(
            {
                "input_device": "Zeus X",
                "monitor_enabled": "sim",
                "reverb_enabled": False,
                "reverb_level": 500,
                "noise_reduction_enabled": True,
            }
        )

        self.assertEqual(preferences.input_device, "Zeus X")
        self.assertFalse(preferences.monitor_enabled)
        self.assertFalse(preferences.reverb_enabled)
        self.assertEqual(preferences.reverb_level, 25)
        self.assertTrue(preferences.noise_reduction_enabled)


if __name__ == "__main__":
    unittest.main()
