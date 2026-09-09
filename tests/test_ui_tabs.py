from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from mini_mesa import ui
from mini_mesa.preferences import AppPreferences


class NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ui.wx.App.Get() or ui.wx.App(False)

    def setUp(self) -> None:
        self.engine = Mock()
        self.engine.is_running = True
        self.engine.sound_effects.return_value = []
        self.store = Mock()
        self.store.load.return_value = AppPreferences(welcome_shown=True, last_seen_news_version=ui.__version__)
        with (
            patch.object(ui.MainFrame, "_refresh_devices"),
            patch.object(ui, "SystemTrayIcon", return_value=None),
            patch.object(ui, "can_self_update", return_value=False),
        ):
            self.frame = ui.MainFrame(self.engine, self.store)
        self.frame.Layout()
        self.engine.reset_mock()

    def tearDown(self) -> None:
        self.frame.Destroy()
        self.app.ProcessPendingEvents()

    def key(self, key: int, *, ctrl=False, shift=False, alt=False) -> None:
        event = ui.wx.KeyEvent(ui.wx.EVT_CHAR_HOOK.typeId)
        event.SetKeyCode(key)
        event.SetControlDown(ctrl)
        event.SetShiftDown(shift)
        event.SetAltDown(alt)
        self.frame.GetEventHandler().ProcessEvent(event)

    def test_ctrl_tab_cycles_pages_without_touching_audio_or_preferences(self) -> None:
        book = self.frame.notebook
        self.assertEqual(
            [book.GetPageText(i) for i in range(book.GetPageCount())],
            ["Dispositivos", "Voz e efeitos", "Limpeza da voz", "Áudio 3D", "Painel de efeitos", "Gravar"],
        )
        for expected in (1, 2, 3, 4, 5, 0):
            self.key(ui.wx.WXK_TAB, ctrl=True)
            self.assertEqual(book.GetSelection(), expected)
            for index in range(book.GetPageCount()):
                self.assertEqual(book.GetPage(index).IsShown(), index == expected)
        self.key(ui.wx.WXK_TAB, ctrl=True, shift=True)
        self.assertEqual(book.GetSelection(), 5)
        self.assertEqual(self.engine.mock_calls, [])
        self.store.save.assert_not_called()

    def test_global_actions_stay_outside_the_pages(self) -> None:
        for control in (self.frame.toggle_button, self.frame.exit_button, self.frame.status):
            self.assertFalse(self.frame.notebook.IsDescendant(control))
            self.assertTrue(control.IsShown())

    def test_global_actions_fit_even_when_page_content_needs_scrolling(self) -> None:
        for size in ((620, 800), (480, 600)):
            self.frame.SetSize(size)
            self.frame.Layout()
            parent = self.frame.toggle_button.GetParent()
            parent.Layout()
            for control in (self.frame.notebook, self.frame.toggle_button, self.frame.status):
                rect = control.GetRect()
                self.assertGreater(rect.height, 0)
                self.assertLessEqual(rect.bottom, parent.GetClientSize().height)
                self.assertLessEqual(rect.right, parent.GetClientSize().width)

    def test_effect_shortcut_reveals_page_and_updates_without_restart(self) -> None:
        self.frame.reverb_checkbox.SetValue(False)
        self.key(ord("E"), alt=True)
        self.assertEqual(self.frame.notebook.GetSelection(), 1)
        self.assertTrue(self.frame.reverb_checkbox.GetValue())
        self.assertTrue(self.frame.reverb_level.IsEnabled())
        self.assertIn("Desativar", self.frame.reverb_checkbox.GetLabel())
        self.engine.update_settings.assert_called_once()
        self.engine.start.assert_not_called()
        self.engine.stop.assert_not_called()
        self.assertTrue(self.store.save.call_args.args[0].reverb_enabled)
        self.key(ord("E"), alt=True)
        self.assertFalse(self.frame.reverb_checkbox.GetValue())
        self.assertFalse(self.frame.reverb_level.IsEnabled())

    def test_monitor_uses_a_stable_native_checkbox_label(self) -> None:
        checkbox = self.frame.monitor_checkbox
        self.assertIsInstance(checkbox, ui.wx.CheckBox)
        self.assertEqual(checkbox.GetLabel(), "&Ouvir retorno")
        self.assertEqual(checkbox.GetName(), "Ouvir retorno")
        checkbox.SetValue(True)
        self.assertEqual(checkbox.GetLabel(), "&Ouvir retorno")
        self.assertEqual(self.engine.mock_calls, [])

    def test_native_toggle_event_updates_state_and_audio(self) -> None:
        button = self.frame.eq_checkbox
        button.SetValue(True)
        event = ui.wx.CommandEvent(ui.wx.EVT_TOGGLEBUTTON.typeId, button.GetId())
        event.SetEventObject(button)
        button.GetEventHandler().ProcessEvent(event)
        self.assertTrue(self.frame.eq_low.IsEnabled())
        self.engine.update_pro_audio_settings.assert_called_once()
        self.engine.start.assert_not_called()
        self.engine.stop.assert_not_called()

    def test_without_tray_minimize_keeps_window_accessible(self) -> None:
        self.frame.Show()
        self.app.Yield()
        with patch.object(self.frame, "Hide") as hide:
            self.frame.Iconize(True)
            self.app.Yield()
            self.app.ProcessPendingEvents()
            self.assertTrue(self.frame.IsShown())
            hide.assert_not_called()
        self.frame.restore_from_tray()
        self.app.Yield()
        self.assertTrue(self.frame.IsShown())
        self.assertFalse(self.frame.IsIconized())
        self.engine.stop.assert_not_called()

    def test_minimize_hides_and_notifies_then_restore_stays_visible(self) -> None:
        tray = Mock(is_available=True)
        self.frame._tray_icon = tray
        try:
            self.frame.Show()
            self.app.Yield()
            self.frame.Iconize(True)
            self.app.Yield()
            self.app.ProcessPendingEvents()
            self.assertFalse(self.frame.IsShown())
            tray.notify_minimized.assert_called_once_with()
            generation = self.frame._minimize_generation
            self.frame.restore_from_tray()
            self.frame._hide_to_tray(generation)
            self.app.Yield()
            self.app.ProcessPendingEvents()
            self.assertTrue(self.frame.IsShown())
            self.assertFalse(self.frame.IsIconized())
            self.frame.Iconize(True)
            self.app.Yield()
            self.app.ProcessPendingEvents()
            self.assertFalse(self.frame.IsShown())
            self.assertEqual(tray.notify_minimized.call_count, 2)
            self.engine.stop.assert_not_called()
        finally:
            self.frame._tray_icon = None

    def test_restore_cancels_pending_hide_before_it_runs(self) -> None:
        self.frame._tray_icon = Mock(is_available=True)
        try:
            self.frame.Show()
            self.app.Yield()
            with patch.object(ui.wx, "CallAfter") as pending:
                self.frame.Iconize(True)
                self.app.Yield()
            hide_calls = [call for call in pending.call_args_list
                          if call.args[0] == self.frame._hide_to_tray]
            self.assertTrue(hide_calls)
            self.frame.restore_from_tray()
            for call in hide_calls:
                call.args[0](*call.args[1:])
            self.app.Yield()
            self.assertTrue(self.frame.IsShown())
            self.assertFalse(self.frame.IsIconized())
            self.frame._tray_icon.notify_minimized.assert_not_called()
        finally:
            self.frame._tray_icon = None

    def test_notification_explains_how_to_restore_without_changing_audio(self) -> None:
        tray = Mock(is_available=True)
        ui.SystemTrayIcon.notify_minimized(tray)
        title, message, *_ = tray.ShowBalloon.call_args.args
        self.assertEqual(title, "Mini Mesa minimizada")
        self.assertEqual(message, "A Mini Mesa está minimizada. Você pode restaurá-la pela bandeja do sistema.")
        tray.ShowBalloon.side_effect = ui.wx.wxAssertionError("notifications unavailable")
        ui.SystemTrayIcon.notify_minimized(tray)
        self.assertEqual(self.engine.mock_calls, [])

    def test_tray_open_menu_restores_hidden_window(self) -> None:
        self.frame.Show()
        self.frame.Iconize(True)
        self.frame.Hide()
        icon = ui.SystemTrayIcon(self.frame)
        try:
            icon.ProcessEvent(ui.wx.CommandEvent(ui.wx.EVT_MENU.typeId, int(icon._restore_id)))
            self.app.Yield()
            self.app.ProcessPendingEvents()
            self.assertTrue(self.frame.IsShown())
            self.assertFalse(self.frame.IsIconized())
        finally:
            icon.RemoveIcon()
            icon.Destroy()

    def test_start_always_routes_effects_to_selected_headphones(self) -> None:
        self.frame.input_choice.Set(["Microfone"])
        self.frame.input_choice.SetSelection(0)
        self.frame.output_choice.Set(["Cabo virtual"])
        self.frame.output_choice.SetSelection(0)
        self.frame.monitor_choice.Set(["Fones"])
        self.frame.monitor_choice.SetSelection(0)
        self.frame.monitor_checkbox.SetValue(False)
        self.frame._start_selected_route()
        self.engine.start.assert_called_once_with(
            "Microfone", "Cabo virtual", None, effects_output="Fones"
        )
        self.assertTrue(self.frame.monitor_choice.IsEnabled())

    def test_failed_effects_device_change_restores_previous_headphones(self) -> None:
        self.frame.monitor_choice.Set(["Fones antigos", "Fones novos"])
        self.frame.monitor_choice.SetSelection(1)
        self.engine.update_monitor.side_effect = RuntimeError("device busy")
        with patch.object(self.frame, "_show_error"):
            self.frame._update_running_monitor(None, "Fones antigos")
        self.assertEqual(self.frame.monitor_choice.GetStringSelection(), "Fones antigos")
        self.assertFalse(self.frame.monitor_checkbox.GetValue())
        self.assertTrue(self.frame.monitor_choice.IsEnabled())

    def test_news_appear_once_per_version_and_remain_saved_with_other_preferences(self) -> None:
        self.frame.preferences = replace(self.frame.preferences, last_seen_news_version="1.0.0")
        with patch.object(ui, "ReleaseNotesDialog") as dialog, patch.object(ui, "can_self_update", return_value=False):
            self.frame._show_startup_information()
            self.frame._show_startup_information()
            dialog.return_value.ShowModal.assert_called_once()
            dialog.return_value.Destroy.assert_called_once()
        self.frame._save_preferences()
        self.assertEqual(self.store.save.call_args.args[0].last_seen_news_version, ui.__version__)

    def test_news_can_be_reopened_manually(self) -> None:
        with patch.object(ui, "ReleaseNotesDialog") as dialog:
            self.frame._on_release_notes(None)
            dialog.return_value.ShowModal.assert_called_once()

    def test_missing_news_do_not_mark_version_as_seen(self) -> None:
        self.frame.preferences = replace(self.frame.preferences, last_seen_news_version="1.0.0")
        with patch.object(ui, "load_release_notes", side_effect=FileNotFoundError()), patch.object(self.frame, "_show_error") as error:
            self.frame._on_release_notes(None)
            error.assert_called_once()
        self.assertEqual(self.frame.preferences.last_seen_news_version, "1.0.0")

    def test_news_save_failure_allows_retry(self) -> None:
        self.frame.preferences = replace(self.frame.preferences, last_seen_news_version="1.0.0")
        self.store.save.side_effect = OSError("disk full")
        with patch.object(ui, "ReleaseNotesDialog"):
            self.frame._on_release_notes(None)
        self.assertEqual(self.frame.preferences.last_seen_news_version, "1.0.0")

    def test_news_dialog_has_native_readable_text_and_escape(self) -> None:
        text = ui.load_release_notes()
        dialog = ui.ReleaseNotesDialog(self.frame, text)
        try:
            self.assertIn(ui.__version__, dialog.news_text.GetName())
            self.assertEqual(dialog.news_text.GetValue(), text)
            self.assertFalse(dialog.news_text.IsEditable())
            self.assertEqual(dialog.GetEscapeId(), ui.wx.ID_OK)
        finally:
            dialog.Destroy()

    def test_soundboard_menu_reveals_embedded_controls(self) -> None:
        self.frame._on_open_soundboard(None)
        self.assertEqual(self.frame.notebook.GetSelection(), 4)
        self.assertTrue(self.frame.soundboard_panel.IsShown())
        self.assertEqual(self.engine.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
