from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mini_mesa import ui
from mini_mesa.preferences import AppPreferences, PersonalSound, PreferencesStore


class AccessibilityFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ui.wx.App.Get() or ui.wx.App(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = PreferencesStore(Path(self.directory.name) / "preferences.json")
        self.store.save(AppPreferences(welcome_shown=True, last_seen_news_version=ui.__version__))
        self.engine = Mock(is_running=False, input_level=0.0)
        self.engine.input_devices.return_value = ("Mic",)
        self.engine.output_devices.return_value = ("CABLE Input", "Fones")
        self.engine.monitor_devices.return_value = ("Fones",)
        with (
            patch.object(ui, "SystemTrayIcon", return_value=None),
            patch.object(ui, "can_self_update", return_value=False),
        ):
            self.frame = ui.MainFrame(self.engine, self.store)

    def tearDown(self):
        self.frame.Destroy()
        self.app.ProcessPendingEvents()
        self.directory.cleanup()

    def test_level_announces_only_after_stable_category_change(self):
        self.engine.is_running = True
        self.engine.input_level = 0.1
        with patch.object(ui.wx.Accessible, "NotifyEvent") as notify:
            self.frame._on_level_timer(None)
            self.frame._on_level_timer(None)
            notify.assert_not_called()
            self.frame._on_level_timer(None)
            notify.assert_called_once()
            self.assertIn("adequado", self.frame.input_level_status.GetValue())
            for _ in range(4):
                self.frame._on_level_timer(None)
            notify.assert_called_once()
            self.engine.input_level = 0.9
            for _ in range(3):
                self.frame._on_level_timer(None)
            self.assertEqual(notify.call_count, 2)
            self.assertIn("Saturando", self.frame.input_level_status.GetValue())

    def test_loaded_profile_updates_controls_pages_and_stays_stopped(self):
        names = ("Programa",) + tuple(f"Página {number}" for number in range(2, 11))
        preferences = replace(
            self.store.load(),
            input_device="Mic",
            output_device="CABLE Input",
            monitor_device="Fones",
            reverb_enabled=False,
            reverb_level=71,
            sound_page_names=names,
            personal_sounds=(PersonalSound("Abertura", "a.wav", 0),),
            feedback_sounds_enabled=True,
        )
        with patch.object(self.frame, "_apply_global_hotkeys", return_value=True):
            self.frame._apply_loaded_preferences(preferences)
        self.assertFalse(self.frame.reverb_checkbox.GetValue())
        self.assertEqual(self.frame.reverb_level.GetValue(), 71)
        self.assertEqual(self.frame.soundboard_panel.page_choice.GetString(0), "Programa")
        self.assertIn("Abertura", self.frame.soundboard_panel.effect_list.GetString(0))
        self.assertTrue(self.frame._feedback_item.IsChecked())
        self.assertFalse(self.engine.stop.called)
        self.assertEqual(self.store.load().sound_page_names[0], "Programa")

    def test_global_hotkey_failure_is_disabled_and_persisted(self):
        self.frame.preferences = replace(self.frame.preferences, global_shortcuts_enabled=True)
        with (
            patch.object(self.frame._global_hotkeys, "apply", side_effect=RuntimeError("Ctrl+1 ocupado")),
            patch.object(self.frame, "_show_error") as error,
        ):
            self.assertFalse(self.frame._apply_global_hotkeys())
        self.assertFalse(self.store.load().global_shortcuts_enabled)
        self.assertIn("Ctrl+1 ocupado", error.call_args.args[0])

    def test_preview_dialog_works_while_mixer_is_stopped(self):
        self.frame.monitor_choice.SetStringSelection("Fones")
        dialog = ui.SoundPreviewDialog(self.frame, "efeito.wav", 0)
        try:
            preview = next(
                control for control in dialog.GetChildren()
                if isinstance(control, ui.wx.Button) and "prévia" in control.GetLabel()
            )
            self.assertTrue(preview.IsEnabled())
            preview.ProcessEvent(ui.wx.CommandEvent(ui.wx.EVT_BUTTON.typeId, preview.GetId()))
            self.app.ProcessPendingEvents()
        finally:
            dialog.Destroy()

    def test_diagnostic_dialog_exposes_copy_action_and_read_only_report(self):
        dialog = ui.DiagnosticDialog(self.frame, "Entradas encontradas: Mic")
        try:
            self.assertFalse(dialog.report.IsEditable())
            self.assertIn("Mic", dialog.report.GetValue())
            self.assertEqual(dialog.report.GetName(), "Relatório de diagnóstico")
        finally:
            dialog.Destroy()
