from __future__ import annotations

import unittest

from mini_mesa.preferences import AppPreferences
from mini_mesa.settings import (
    CreativeEffectSettings,
    ProAudioSettings,
    VALID_AMBIENCES,
    VALID_CREATIVE_PRESETS,
    VALID_MODULATIONS,
    VALID_VOICE_PRESETS,
    VoiceSettings,
)


class VoiceSettingsTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        settings = VoiceSettings()
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.pitch_semitones, 4.0)
        self.assertEqual(settings.highpass_cutoff, 120.0)

    def test_custom_values_accepted(self) -> None:
        settings = VoiceSettings(enabled=True, pitch_semitones=6.0, highpass_cutoff=150.0)
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.pitch_semitones, 6.0)
        self.assertEqual(settings.highpass_cutoff, 150.0)

    def test_pitch_semitones_range_validation(self) -> None:
        with self.assertRaises(ValueError):
            VoiceSettings(pitch_semitones=13.0)

        with self.assertRaises(ValueError):
            VoiceSettings(pitch_semitones=-13.0)

    def test_invalid_types_rejected(self) -> None:
        with self.assertRaises(TypeError):
            VoiceSettings(enabled="yes")  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            VoiceSettings(pitch_semitones="high")  # type: ignore[arg-type]

    def test_removed_voice_presets_are_rejected(self) -> None:
        for preset in ("autotune", "vocoder"):
            with self.assertRaises(ValueError):
                VoiceSettings(enabled=True, preset=preset)


class CreativeEffectSettingsTests(unittest.TestCase):
    def test_defaults_and_presets(self) -> None:
        settings = CreativeEffectSettings()
        self.assertEqual(settings.preset, "none")
        self.assertFalse(settings.delay_enabled)
        self.assertEqual(settings.delay_mix, 0.0)

    def test_telephone_preset_and_delay(self) -> None:
        settings = CreativeEffectSettings(
            preset="telephone", delay_enabled=True, delay_level_percent=50
        )
        self.assertEqual(settings.preset, "telephone")
        self.assertTrue(settings.delay_enabled)
        self.assertAlmostEqual(settings.delay_seconds, 0.325)
        self.assertAlmostEqual(settings.delay_feedback, 0.40)
        self.assertAlmostEqual(settings.delay_mix, 0.30)

    def test_effect_intensities_and_radio_beeps(self) -> None:
        settings = CreativeEffectSettings(
            style_intensity_percent=80,
            modulation_intensity_percent=40,
            ambience_intensity_percent=65,
            roger_beep_enabled=True,
        )
        self.assertEqual(settings.style_intensity_percent, 80)
        self.assertTrue(settings.roger_beep_enabled)
        with self.assertRaises(ValueError):
            CreativeEffectSettings(style_intensity_percent=101)

    def test_invalid_preset_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CreativeEffectSettings(preset="invalid_preset")

    def test_all_style_modulation_and_ambience_values_are_valid(self) -> None:
        for preset in VALID_CREATIVE_PRESETS:
            self.assertEqual(CreativeEffectSettings(preset=preset).preset, preset)
        for modulation in VALID_MODULATIONS:
            self.assertEqual(
                CreativeEffectSettings(modulation=modulation).modulation,
                modulation,
            )
        for ambience in VALID_AMBIENCES:
            self.assertEqual(
                CreativeEffectSettings(ambience=ambience).ambience,
                ambience,
            )

    def test_all_voice_presets_are_valid(self) -> None:
        for preset in VALID_VOICE_PRESETS:
            self.assertEqual(VoiceSettings(preset=preset).preset, preset)


class ProAudioSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        settings = ProAudioSettings()
        self.assertFalse(settings.compressor_enabled)
        self.assertFalse(settings.eq_enabled)
        self.assertEqual(settings.eq_low_db, 0.0)
        self.assertEqual(settings.eq_mid_db, 0.0)
        self.assertEqual(settings.eq_high_db, 0.0)

    def test_custom_eq_values(self) -> None:
        settings = ProAudioSettings(
            compressor_enabled=True,
            eq_enabled=True,
            eq_low_db=3.0,
            eq_mid_db=-2.0,
            eq_high_db=4.5,
        )
        self.assertTrue(settings.compressor_enabled)
        self.assertTrue(settings.eq_enabled)
        self.assertEqual(settings.eq_low_db, 3.0)
        self.assertEqual(settings.eq_mid_db, -2.0)
        self.assertEqual(settings.eq_high_db, 4.5)

    def test_eq_range_validation(self) -> None:
        with self.assertRaises(ValueError):
            ProAudioSettings(eq_low_db=15.0)

    def test_microphone_processors_accept_boolean_toggles(self) -> None:
        settings = ProAudioSettings(
            noise_gate_enabled=True,
            deesser_enabled=True,
            expander_enabled=True,
            auto_gain_enabled=True,
            plosive_filter_enabled=True,
        )
        self.assertTrue(settings.noise_gate_enabled)
        self.assertTrue(settings.deesser_enabled)
        self.assertTrue(settings.expander_enabled)
        self.assertTrue(settings.auto_gain_enabled)
        self.assertTrue(settings.plosive_filter_enabled)


class PreferencesVoiceTests(unittest.TestCase):
    def test_voice_preferences_deserialization(self) -> None:
        raw = {
            "voice_enabled": True,
            "voice_preset": "monster",
            "voice_pitch_semitones": 5.0,
            "creative_effect_preset": "megaphone",
            "modulation_effect": "phaser",
            "ambience_preset": "cave",
            "delay_enabled": True,
            "delay_level_percent": 60,
            "compressor_enabled": True,
            "eq_enabled": True,
            "eq_low_db": 4.0,
            "eq_mid_db": -1.0,
            "eq_high_db": 5.0,
        }
        prefs = AppPreferences.from_dict(raw)
        self.assertTrue(prefs.voice_enabled)
        self.assertEqual(prefs.voice_preset, "monster")
        self.assertEqual(prefs.voice_pitch_semitones, 5.0)
        self.assertEqual(prefs.creative_effect_preset, "megaphone")
        self.assertEqual(prefs.modulation_effect, "phaser")
        self.assertEqual(prefs.ambience_preset, "cave")
        self.assertTrue(prefs.delay_enabled)
        self.assertEqual(prefs.delay_level_percent, 60)
        self.assertTrue(prefs.compressor_enabled)
        self.assertTrue(prefs.eq_enabled)
        self.assertEqual(prefs.eq_low_db, 4.0)
        self.assertEqual(prefs.eq_mid_db, -1.0)
        self.assertEqual(prefs.eq_high_db, 5.0)

    def test_voice_preferences_fallback_on_invalid(self) -> None:
        raw = {
            "voice_enabled": "invalid",
            "voice_preset": "invalid",
            "voice_pitch_semitones": 999.0,
            "creative_effect_preset": "invalid",
            "delay_level_percent": -10,
            "compressor_enabled": "not_bool",
            "eq_low_db": 99.0,
        }
        prefs = AppPreferences.from_dict(raw)
        self.assertFalse(prefs.voice_enabled)
        self.assertEqual(prefs.voice_preset, "female")
        self.assertEqual(prefs.voice_pitch_semitones, 4.0)
        self.assertEqual(prefs.creative_effect_preset, "none")
        self.assertEqual(prefs.delay_level_percent, 30)
        self.assertFalse(prefs.compressor_enabled)
        self.assertEqual(prefs.eq_low_db, 0.0)


if __name__ == "__main__":
    unittest.main()
