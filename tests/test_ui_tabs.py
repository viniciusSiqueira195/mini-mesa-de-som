from __future__ import annotations

import unittest
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
        self.store.load.return_value = AppPreferences(welcome_shown=True)
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
            ["Dispositivos", "Voz e efeitos", "Limpeza da voz", "Áudio 3D", "Sons e vinhetas"],
        )
        for expected in (1, 2, 3, 4, 0):
            self.key(ui.wx.WXK_TAB, ctrl=True)
            self.assertEqual(book.GetSelection(), expected)
            for index in range(book.GetPageCount()):
                self.assertEqual(book.GetPage(index).IsShown(), index == expected)
        self.key(ui.wx.WXK_TAB, ctrl=True, shift=True)
        self.assertEqual(book.GetSelection(), 4)
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

    def test_programmatic_restore_updates_button_action_and_accessible_name(self) -> None:
        button = self.frame.monitor_checkbox
        button.SetValue(True)
        self.assertIn("Desativar", button.GetLabel())
        button.SetValue(False)
        self.assertIn("Ativar", button.GetLabel())
        self.assertIn("Desligado", button.GetName())
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

    def test_soundboard_menu_reveals_embedded_controls(self) -> None:
        self.frame._on_open_soundboard(None)
        self.assertEqual(self.frame.notebook.GetSelection(), 4)
        self.assertTrue(self.frame.soundboard_panel.IsShown())
        self.assertEqual(self.engine.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
