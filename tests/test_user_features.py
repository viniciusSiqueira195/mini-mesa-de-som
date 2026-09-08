from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from mini_mesa.global_hotkeys import GlobalHotkeyManager
from mini_mesa.preferences import AppPreferences, PersonalSound
from mini_mesa.user_features import ProfileStore, diagnostic_text, export_backup, import_backup


class ProfileStoreTests(unittest.TestCase):
    def test_profile_round_trip_preserves_current_onboarding_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.json")
            saved = AppPreferences(
                input_device="Mic", reverb_level=73,
                personal_sounds=(PersonalSound("Som", "sound.wav", 2),),
            )
            store.save("Podcast", saved)
            loaded = store.load(
                "Podcast", AppPreferences(welcome_shown=True, last_seen_news_version="1.1.0")
            )
            self.assertEqual(loaded.input_device, "Mic")
            self.assertEqual(loaded.reverb_level, 73)
            self.assertTrue(loaded.welcome_shown)
            self.assertEqual(loaded.last_seen_news_version, "1.1.0")
            self.assertEqual(store.names(), ("Podcast",))
            store.delete("Podcast")
            self.assertEqual(store.names(), ())

    def test_invalid_profile_file_is_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text("broken", encoding="utf-8")
            self.assertEqual(ProfileStore(path).names(), ())


class BackupTests(unittest.TestCase):
    def test_portable_backup_restores_audio_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "efeito.wav"
            audio.write_bytes(b"RIFF-test-audio")
            preferences = AppPreferences(
                reverb_level=64,
                sound_page_names=("Memes",) + tuple(f"Página {n}" for n in range(2, 11)),
                personal_sounds=(PersonalSound("Efeito", str(audio), 0),),
            )
            backup = root / "mesa.mmb"
            export_backup(preferences, backup, include_audio=True)
            loaded = import_backup(backup, root / "imported")
            self.assertEqual(loaded.reverb_level, 64)
            self.assertEqual(loaded.sound_page_names[0], "Memes")
            restored = Path(loaded.personal_sounds[0].path)
            self.assertEqual(restored.read_bytes(), audio.read_bytes())
            self.assertNotEqual(restored, audio)

    def test_configuration_only_backup_keeps_original_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferences = AppPreferences(
                personal_sounds=(PersonalSound("Efeito", r"D:\sons\efeito.mp3"),)
            )
            backup = root / "config.mmb"
            export_backup(preferences, backup, include_audio=False)
            loaded = import_backup(backup, root / "unused")
            self.assertEqual(loaded.personal_sounds, preferences.personal_sounds)
            self.assertFalse((root / "unused").exists())

    def test_unsafe_archive_path_is_rejected_without_extracting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "unsafe.mmb"
            manifest = {
                "format": "mini-mesa-backup", "audio_included": True,
                "preferences": {"personal_sounds": [
                    {"name": "Ruim", "path": "../outside.wav", "page": 0}
                ]},
            }
            with zipfile.ZipFile(backup, "w") as archive:
                archive.writestr("mini-mesa-backup.json", json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "inseguro"):
                import_backup(backup, root / "imported")
            self.assertFalse((root / "imported").exists())

    def test_failed_export_does_not_replace_existing_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "existing.mmb"
            backup.write_bytes(b"previous")
            preferences = AppPreferences(
                personal_sounds=(PersonalSound("Ausente", str(root / "missing.wav")),)
            )
            with self.assertRaises(FileNotFoundError):
                export_backup(preferences, backup, include_audio=True)
            self.assertEqual(backup.read_bytes(), b"previous")


class GlobalHotkeyTests(unittest.TestCase):
    def test_registers_twenty_one_shortcuts_and_dispatches_action(self):
        window = Mock()
        window.RegisterHotKey.return_value = True
        manager = GlobalHotkeyManager(window)
        play, page, stop = Mock(), Mock(), Mock()
        with patch("mini_mesa.global_hotkeys.wx.NewIdRef", side_effect=range(100, 121)):
            manager.apply(
                enabled=True, effect_modifier="control", page_modifier="alt",
                play=play, select_page=page, stop=stop,
            )
        self.assertEqual(window.RegisterHotKey.call_count, 21)
        first_handler = window.Bind.call_args_list[0].args[1]
        first_handler(None)
        play.assert_called_once_with(0)
        manager.close()
        self.assertEqual(window.UnregisterHotKey.call_count, 21)

    def test_conflict_rolls_back_every_registered_shortcut(self):
        window = Mock()
        window.RegisterHotKey.side_effect = [True, True, False]
        manager = GlobalHotkeyManager(window)
        with patch("mini_mesa.global_hotkeys.wx.NewIdRef", side_effect=range(3)):
            with self.assertRaisesRegex(RuntimeError, "já está em uso"):
                manager.apply(
                    enabled=True, effect_modifier="control", page_modifier="alt",
                    play=Mock(), select_page=Mock(), stop=Mock(),
                )
        self.assertEqual(window.UnregisterHotKey.call_count, 2)


class DiagnosticTests(unittest.TestCase):
    def test_report_is_readable_and_contains_devices(self):
        engine = Mock(is_running=False)
        engine.input_devices.return_value = ("Microfone USB",)
        engine.output_devices.return_value = ("CABLE Input", "Fones")
        engine.monitor_devices.return_value = ("Fones",)
        engine.diagnostic_details.return_value = {"api": "Windows WASAPI"}
        report = diagnostic_text(
            engine, AppPreferences(input_device="Microfone USB", output_device="CABLE Input")
        )
        self.assertIn("Entradas encontradas (1)", report)
        self.assertIn("Microfone USB", report)
        self.assertIn("Windows WASAPI", report)
