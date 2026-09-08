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
                welcome_shown=True,
                input_device="Microfone Áudio",
                output_device="CABLE Input",
                monitor_enabled=True,
                monitor_device="Fones",
                reverb_enabled=False,
                reverb_level=72,
                noise_reduction_enabled=True,
                spatial_enabled=True,
                spatial_x=-80,
                spatial_y=25,
                spatial_z=-40,
                spatial_automatic=True,
                spatial_speed=60,
                sound_page_names=("Memes",) + tuple(
                    f"Página {number}" for number in range(2, 11)
                ),
                global_shortcuts_enabled=True,
                global_effect_modifier="control_alt",
                global_page_modifier="alt_shift",
                feedback_sounds_enabled=True,
            )

            store.save(expected)

            self.assertEqual(store.load(), expected)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 12)
            self.assertEqual(saved["input_device"], "Microfone Áudio")
            self.assertEqual(saved["sound_page_names"][0], "Memes")

    def test_invalid_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text("{isto não é json", encoding="utf-8")

            self.assertEqual(PreferencesStore(path).load(), AppPreferences())

    def test_legacy_test_directory_is_migrated_without_losing_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "Mini Mesa de Som" / "preferences.json"
            legacy = root / "Mini Mesa de Som Teste" / "preferences.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(
                json.dumps({"input_device": "Microfone antigo", "reverb_level": 61}),
                encoding="utf-8",
            )
            store = PreferencesStore(current, legacy_paths=(legacy,))

            preferences = store.load()

            self.assertEqual(preferences.input_device, "Microfone antigo")
            self.assertEqual(preferences.reverb_level, 61)
            self.assertTrue(current.is_file())
            self.assertEqual(PreferencesStore(current).load(), preferences)

    def test_invalid_fields_do_not_poison_valid_preferences(self) -> None:
        preferences = AppPreferences.from_dict(
            {
                "input_device": "Zeus X",
                "welcome_shown": "talvez",
                "monitor_enabled": "sim",
                "reverb_enabled": False,
                "reverb_level": 500,
                "noise_reduction_enabled": True,
                "spatial_enabled": True,
                "spatial_x": 900,
                "spatial_y": -40,
                "spatial_z": "frente",
                "spatial_automatic": True,
                "spatial_speed": 900,
            }
        )

        self.assertEqual(preferences.input_device, "Zeus X")
        self.assertFalse(preferences.welcome_shown)
        self.assertFalse(preferences.monitor_enabled)
        self.assertFalse(preferences.reverb_enabled)
        self.assertEqual(preferences.reverb_level, 25)
        self.assertTrue(preferences.noise_reduction_enabled)
        self.assertTrue(preferences.spatial_enabled)
        self.assertEqual(preferences.spatial_x, 0)
        self.assertEqual(preferences.spatial_y, -40)
        self.assertEqual(preferences.spatial_z, 100)
        self.assertTrue(preferences.spatial_automatic)
        self.assertEqual(preferences.spatial_speed, 35)

    def test_horizontal_angle_from_schema_four_migrates_to_xyz(self) -> None:
        preferences = AppPreferences.from_dict(
            {"spatial_enabled": True, "spatial_angle": -90}
        )

        self.assertEqual(preferences.spatial_x, -100)
        self.assertEqual(preferences.spatial_y, 0)
        self.assertEqual(preferences.spatial_z, 0)

    def test_invalid_accessibility_preferences_fall_back_safely(self) -> None:
        preferences = AppPreferences.from_dict({
            "sound_page_names": ["somente uma"],
            "global_shortcuts_enabled": "sim",
            "global_effect_modifier": "windows",
            "global_page_modifier": "control",
            "feedback_sounds_enabled": 1,
        })
        self.assertEqual(preferences.sound_page_names[0], "Página 1")
        self.assertFalse(preferences.global_shortcuts_enabled)
        self.assertEqual(preferences.global_effect_modifier, "control")
        self.assertEqual(preferences.global_page_modifier, "alt")
        self.assertFalse(preferences.feedback_sounds_enabled)

    def test_legacy_voice_pitch_migrates_to_the_matching_preset(self) -> None:
        preferences = AppPreferences.from_dict(
            {"voice_enabled": True, "voice_pitch_semitones": -4.0}
        )

        self.assertEqual(preferences.voice_preset, "male")

    def test_removed_voice_presets_migrate_to_disabled_neutral_voice(self) -> None:
        for preset in ("autotune", "vocoder"):
            preferences = AppPreferences.from_dict({
                "voice_enabled": True, "voice_preset": preset,
                "voice_pitch_semitones": 4.0, "autotune_mode": "trap",
                "autotune_scale": "minor", "autotune_key": 9,
                "eq_enabled": True, "eq_low_db": 3.0,
            })
            self.assertFalse(preferences.voice_enabled)
            self.assertEqual(preferences.voice_preset, "custom")
            self.assertEqual(preferences.voice_pitch_semitones, 0.0)
            self.assertTrue(preferences.eq_enabled)
            self.assertEqual(preferences.eq_low_db, 3.0)
            self.assertFalse(hasattr(preferences, "autotune_mode"))


if __name__ == "__main__":
    unittest.main()
