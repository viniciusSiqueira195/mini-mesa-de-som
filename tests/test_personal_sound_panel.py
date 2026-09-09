from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from mini_mesa import ui
from mini_mesa.preferences import AppPreferences, PersonalSound, PreferencesStore
from mini_mesa.soundboard import SoundboardMixer, SoundEffectError, validate_custom_audio


class PersonalSoundPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ui.wx.App.Get() or ui.wx.App(False)

    def setUp(self):
        self.confirmation = patch.object(ui.wx, "MessageBox", return_value=ui.wx.YES)
        self.confirmation.start()
        self.addCleanup(self.confirmation.stop)
        self.preview = patch.object(ui, "SoundPreviewDialog")
        preview_factory = self.preview.start()
        preview_factory.return_value.ShowModal.return_value = ui.wx.ID_OK
        self.addCleanup(self.preview.stop)
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "Minha vinheta.wav"
        sf.write(self.path, np.full(240, 0.25), 24_000)
        self.store = PreferencesStore(self.root / "preferences.json")
        self.store.save(AppPreferences(welcome_shown=True, last_seen_news_version=ui.__version__))
        self.engine = Mock(is_running=True)
        self.frame = self.open_frame()
        self.panel = self.frame.soundboard_panel

    def open_frame(self):
        with (
            patch.object(ui.MainFrame, "_refresh_devices"),
            patch.object(ui, "SystemTrayIcon", return_value=None),
            patch.object(ui, "can_self_update", return_value=False),
        ):
            return ui.MainFrame(self.engine, self.store)

    def tearDown(self):
        self.frame.Destroy()
        self.app.ProcessPendingEvents()
        self.directory.cleanup()

    def file_dialog(self, path=None, result=None):
        dialog = Mock()
        dialog.__enter__ = Mock(return_value=dialog)
        dialog.__exit__ = Mock(return_value=False)
        dialog.ShowModal.return_value = ui.wx.ID_OK if result is None else result
        dialog.GetPath.return_value = str(path or self.path)
        dialog.GetPaths.return_value = [str(path or self.path)]
        return patch.object(ui.wx, "FileDialog", return_value=dialog)

    def multiple_file_dialog(self, paths, result=None):
        dialog = Mock()
        dialog.__enter__ = Mock(return_value=dialog)
        dialog.__exit__ = Mock(return_value=False)
        dialog.ShowModal.return_value = ui.wx.ID_OK if result is None else result
        dialog.GetPaths.return_value = [str(path) for path in paths]
        return patch.object(ui.wx, "FileDialog", return_value=dialog)

    def add_sound(self):
        with self.file_dialog():
            self.panel._on_add(None)

    def test_new_panel_is_empty_and_can_be_configured_with_audio_stopped(self):
        self.assertEqual(self.panel.effect_list.GetCount(), 0)
        self.assertIn("vazia", self.panel.effect_list.GetName())
        self.assertFalse(self.panel.play_button.IsEnabled())
        self.engine.is_running = False
        self.add_sound()
        self.assertEqual(self.store.load().personal_sounds, (
            PersonalSound("Minha vinheta", str(self.path)),
        ))
        self.assertTrue(self.panel.play_button.IsEnabled())
        self.engine.play_sound.assert_not_called()

    def test_add_can_import_multiple_files_and_previews_each_one(self):
        second = self.root / "Segunda vinheta.wav"
        sf.write(second, np.full(240, 0.5), 24_000)
        with self.multiple_file_dialog([self.path, second]):
            self.panel._on_add(None)
        self.assertEqual(self.store.load().personal_sounds, (
            PersonalSound("Minha vinheta", str(self.path)),
            PersonalSound("Segunda vinheta", str(second)),
        ))
        self.assertEqual(ui.SoundPreviewDialog.call_count, 2)

    def test_add_rejects_a_selection_larger_than_remaining_page_capacity(self):
        effects = [PersonalSound(f"Som {i}", str(self.path)) for i in range(9)]
        self.panel._commit_effects(effects, 8)
        extra = self.root / "Extra.wav"
        sf.write(extra, np.full(240, 0.5), 24_000)
        with self.multiple_file_dialog([self.path, extra]), patch.object(self.frame, "_show_error") as error:
            self.panel._on_add(None)
        error.assert_called_once_with(
            "Esta página tem espaço para apenas 1 vaga, mas você selecionou 2 arquivos."
        )
        self.assertEqual(self.store.load().personal_sounds, tuple(effects))
        ui.SoundPreviewDialog.assert_not_called()

    def test_canceling_one_preview_does_not_save_a_partial_batch(self):
        second = self.root / "Segunda vinheta.wav"
        sf.write(second, np.full(240, 0.5), 24_000)
        ui.SoundPreviewDialog.return_value.ShowModal.side_effect = [ui.wx.ID_OK, ui.wx.ID_CANCEL]
        with self.multiple_file_dialog([self.path, second]):
            self.panel._on_add(None)
        self.assertEqual(self.store.load().personal_sounds, ())

    def test_effects_survive_other_preferences_and_reopening(self):
        self.add_sound()
        self.frame.reverb_level.SetValue(42)
        self.frame._save_preferences()
        self.frame.Destroy()
        self.app.ProcessPendingEvents()
        self.frame = self.open_frame()
        self.assertEqual(self.frame.soundboard_panel.effect_list.GetCount(), 1)
        self.assertIn("Minha vinheta; Ctrl+1", self.frame.soundboard_panel.effect_list.GetString(0))
        self.assertEqual(self.frame.reverb_level.GetValue(), 42)

    def test_rename_replace_and_remove_preserve_original_files(self):
        self.add_sound()
        with patch.object(ui.wx, "TextEntryDialog") as factory:
            dialog = factory.return_value.__enter__.return_value
            dialog.ShowModal.return_value = ui.wx.ID_OK
            dialog.GetValue.return_value = "Abertura"
            self.panel._on_rename(None)
        replacement = self.root / "Novo som.flac"
        sf.write(replacement, np.full(120, 0.5), 48_000)
        with self.file_dialog(replacement):
            self.panel._on_replace(None)
        self.assertEqual(self.store.load().personal_sounds, (PersonalSound("Abertura", str(replacement)),))
        self.panel._on_remove(None)
        self.assertEqual(self.store.load().personal_sounds, ())
        self.assertTrue(self.path.is_file())
        self.assertTrue(replacement.is_file())
        self.assertFalse(self.panel.play_button.IsEnabled())

    def test_cancel_and_invalid_file_leave_catalog_unchanged(self):
        with self.file_dialog(result=ui.wx.ID_CANCEL):
            self.panel._on_add(None)
        invalid = self.root / "invalid.wav"
        invalid.write_text("not audio")
        with self.file_dialog(invalid), patch.object(self.frame, "_show_error") as error:
            self.panel._on_add(None)
        error.assert_called_once()
        self.assertEqual(self.store.load().personal_sounds, ())

    def test_save_failure_preserves_previous_catalog(self):
        self.add_sound()
        with patch.object(self.store, "save", side_effect=OSError("disk full")), patch.object(self.frame, "_show_error") as error:
            self.panel._on_remove(None)
        error.assert_called_once()
        self.assertEqual(len(self.panel._effects), 1)
        self.assertEqual(len(self.store.load().personal_sounds), 1)

    def test_shortcuts_follow_current_list_after_removal(self):
        self.add_sound()
        other = PersonalSound("Segundo", str(self.path))
        self.panel._commit_effects([*self.panel._effects, other], 0)
        self.panel._on_remove(None)
        with patch.object(self.frame, "play_personal_sound") as play:
            menu_id = next(iter(self.frame._effect_menu_ids))
            event = ui.wx.CommandEvent(ui.wx.EVT_MENU.typeId, menu_id)
            self.frame.GetEventHandler().ProcessEvent(event)
            play.assert_called_once_with(other)
            self.panel.play_index(8)
            self.assertEqual(play.call_count, 1)

    def test_saved_file_reaches_real_mixer_and_resamples(self):
        self.add_sound()
        mixer = SoundboardMixer(sample_rate=48_000)
        self.engine.play_sound.side_effect = mixer.play
        sound = self.store.load().personal_sounds[0]
        with patch.object(ui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)):
            self.frame._custom_sound_worker(sound)
        np.testing.assert_allclose(mixer.mix(480), 0.2, atol=0.0001)
        self.assertFalse(np.any(mixer.mix(1)))
        self.path.unlink()
        with patch.object(ui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)), patch.object(self.frame, "_show_error") as error:
            self.frame._custom_sound_worker(sound)
        self.assertIn("Substituir arquivo", error.call_args.args[0])
        self.assertEqual(len(self.store.load().personal_sounds), 1)

    def test_pages_keep_independent_sounds_and_survive_reopening(self):
        self.add_sound()
        self.panel.select_page(9)
        self.assertEqual(self.panel.effect_list.GetCount(), 0)
        self.add_sound()
        self.assertEqual(self.store.load().selected_sound_page, 9)
        self.assertEqual({sound.page for sound in self.store.load().personal_sounds}, {0, 9})
        self.panel._on_remove(None)
        self.assertEqual(len(self.store.load().personal_sounds), 1)
        self.frame.Destroy()
        self.app.ProcessPendingEvents()
        self.frame = self.open_frame()
        self.assertEqual(self.frame.soundboard_panel.page_choice.GetSelection(), 9)
        self.frame.soundboard_panel.select_page(0)
        self.assertEqual(self.frame.soundboard_panel.effect_list.GetCount(), 1)

    def test_ten_slots_limit_and_tenth_shortcut(self):
        effects = [PersonalSound(f"Som {i}", str(self.path)) for i in range(10)]
        self.panel._commit_effects(effects, 9)
        self.assertIn("Ctrl+0", self.panel.effect_list.GetString(9))
        self.assertFalse(self.panel.add_button.IsEnabled())
        with patch.object(self.panel, "_choose_file") as choose, patch.object(self.frame, "_show_error") as error:
            self.panel._on_add(None)
        choose.assert_not_called()
        error.assert_called_once()
        with patch.object(self.frame, "play_personal_sound") as play:
            menu_id = list(self.frame._effect_menu_ids)[9]
            self.frame.ProcessEvent(ui.wx.CommandEvent(ui.wx.EVT_MENU.typeId, menu_id))
            play.assert_called_once_with(effects[9])
        self.panel.select_page(1)
        self.assertTrue(self.panel.add_button.IsEnabled())

    def test_page_shortcut_changes_page_without_stopping_audio(self):
        self.add_sound()
        menu_id = list(self.frame._page_menu_ids)[9]
        self.frame.ProcessEvent(ui.wx.CommandEvent(ui.wx.EVT_MENU.typeId, menu_id))
        self.assertEqual(self.panel.page_choice.GetSelection(), 9)
        self.assertEqual(self.frame.notebook.GetSelection(), 4)
        self.engine.stop_sound_effects.assert_not_called()
        self.engine.stop.assert_not_called()

    def test_failed_page_save_keeps_current_page(self):
        with patch.object(self.store, "save", side_effect=OSError("disk full")), patch.object(self.frame, "_show_error"):
            self.panel.select_page(9)
        self.assertEqual(self.panel.page_choice.GetSelection(), 0)
        self.assertEqual(self.panel._page, 0)

    def test_page_picker_keeps_focus_and_add_button_names_destination(self):
        self.frame.Show()
        self.frame._on_open_soundboard(None)
        self.app.Yield()
        self.assertEqual(ui.wx.Window.FindFocus(), self.panel.page_choice)
        self.panel.page_choice.SetSelection(2)
        event = ui.wx.CommandEvent(ui.wx.EVT_CHOICE.typeId, self.panel.page_choice.GetId())
        self.panel.page_choice.ProcessEvent(event)
        self.assertEqual(ui.wx.Window.FindFocus(), self.panel.page_choice)
        self.assertEqual(self.panel.add_button.GetName(), "Adicionar efeitos, Página 3")
        self.add_sound()
        self.assertEqual(self.store.load().personal_sounds[0].page, 2)
        self.assertNotIn(str(self.path), self.panel.effect_list.GetString(0))

    def test_context_menu_plays_and_deletes_selected_sound_only(self):
        self.add_sound()
        second = PersonalSound("Segundo", str(self.path))
        self.panel._commit_effects([*self.panel._effects, second], 1)
        menu = self.panel._create_effect_menu()
        try:
            items = menu.GetMenuItems()
            self.assertEqual([item.GetItemLabelText() for item in items], [
                "Tocar", "Renomear...", "Substituir arquivo...", "Mover para cima",
                "Mover para baixo", "Mover para outra página...", "Excluir do painel",
                "Parar todos os efeitos"
            ])
            with patch.object(self.frame, "play_personal_sound") as play:
                menu.ProcessEvent(ui.wx.CommandEvent(ui.wx.EVT_MENU.typeId, items[0].GetId()))
                play.assert_called_once_with(second)
            menu.ProcessEvent(ui.wx.CommandEvent(ui.wx.EVT_MENU.typeId, items[6].GetId()))
            self.assertEqual(len(self.store.load().personal_sounds), 1)
            self.assertEqual(self.store.load().personal_sounds[0].name, "Minha vinheta")
            self.assertTrue(self.path.is_file())
        finally:
            menu.Destroy()

    def test_keyboard_context_menu_keeps_selected_effect(self):
        self.add_sound()
        with patch.object(self.panel.effect_list, "PopupMenu") as popup:
            for key, shift in ((ui.wx.WXK_WINDOWS_MENU, False), (ui.wx.WXK_F10, True)):
                event = ui.wx.KeyEvent(ui.wx.EVT_KEY_DOWN.typeId)
                event.SetKeyCode(key)
                event.SetShiftDown(shift)
                self.panel.effect_list.ProcessEvent(event)
            event = ui.wx.ContextMenuEvent(ui.wx.EVT_CONTEXT_MENU.typeId, self.panel.effect_list.GetId())
            event.SetPosition(ui.wx.DefaultPosition)
            self.panel.effect_list.ProcessEvent(event)
            self.assertEqual(popup.call_count, 3)
        self.assertEqual(self.panel.effect_list.GetSelection(), 0)

    def test_right_click_targets_the_effect_under_pointer(self):
        self.add_sound()
        self.panel._commit_effects([*self.panel._effects, PersonalSound("Segundo", str(self.path))], 0)
        self.frame.Show()
        self.frame._on_open_soundboard(None)
        self.app.Yield()
        target = next((ui.wx.Point(5, y) for y in range(self.panel.effect_list.GetClientSize().height)
                       if self.panel.effect_list.HitTest(ui.wx.Point(5, y)) == 1), None)
        self.assertIsNotNone(target)
        event = ui.wx.ContextMenuEvent(ui.wx.EVT_CONTEXT_MENU.typeId, self.panel.effect_list.GetId())
        event.SetPosition(self.panel.effect_list.ClientToScreen(target))
        with patch.object(self.panel.effect_list, "PopupMenu") as popup:
            self.panel.effect_list.ProcessEvent(event)
            popup.assert_called_once()
        self.assertEqual(self.panel.effect_list.GetSelection(), 1)

    def test_empty_page_does_not_open_effect_menu(self):
        with patch.object(self.panel.effect_list, "PopupMenu") as popup:
            self.panel._show_effect_menu()
            popup.assert_not_called()
        self.assertFalse(self.panel.actions_button.IsEnabled())

    def test_page_can_be_named_and_name_survives_reopening(self):
        with patch.object(ui.wx, "TextEntryDialog") as factory:
            dialog = factory.return_value.__enter__.return_value
            dialog.ShowModal.return_value = ui.wx.ID_OK
            dialog.GetValue.return_value = " Memes "
            self.panel._on_rename_page(None)
        self.assertEqual(self.panel.page_choice.GetString(0), "Memes")
        self.assertEqual(self.panel.add_button.GetName(), "Adicionar efeitos, Memes")
        self.frame.Destroy()
        self.app.ProcessPendingEvents()
        self.frame = self.open_frame()
        self.assertEqual(self.frame.soundboard_panel.page_choice.GetString(0), "Memes")

    def test_search_keeps_original_shortcuts_and_selected_action(self):
        effects = [
            PersonalSound("Abertura", str(self.path)),
            PersonalSound("Risada", str(self.path)),
            PersonalSound("Encerramento", str(self.path)),
        ]
        self.panel._commit_effects(effects, 0)
        self.panel.search.ChangeValue("risa")
        self.panel._on_search(None)
        self.assertEqual(self.panel.effect_list.GetCount(), 1)
        self.assertEqual(self.panel.effect_list.GetString(0), "Risada; Ctrl+2")
        with patch.object(self.frame, "play_personal_sound") as play:
            self.panel._on_play(None)
            play.assert_called_once_with(effects[1])

    def test_effect_can_move_within_and_between_pages(self):
        effects = [
            PersonalSound("Primeiro", str(self.path)),
            PersonalSound("Segundo", str(self.path)),
        ]
        self.panel._commit_effects(effects, 1)
        self.panel._move_selected(-1)
        self.assertEqual([sound.name for sound in self.panel._effects], ["Segundo", "Primeiro"])
        chooser = Mock()
        chooser.__enter__ = Mock(return_value=chooser)
        chooser.__exit__ = Mock(return_value=False)
        chooser.ShowModal.return_value = ui.wx.ID_OK
        chooser.GetSelection.return_value = 0
        with patch.object(ui.wx, "SingleChoiceDialog", return_value=chooser):
            self.panel._on_move_to_page(None)
        saved = self.store.load().personal_sounds
        self.assertEqual(
            {(sound.name, sound.page) for sound in saved},
            {("Primeiro", 0), ("Segundo", 1)},
        )

    def test_delete_requires_confirmation(self):
        self.add_sound()
        with patch.object(ui.wx, "MessageBox", return_value=ui.wx.NO):
            self.panel._on_remove(None)
        self.assertEqual(len(self.panel._effects), 1)
        self.assertTrue(self.path.exists())

    def test_enter_plays_and_space_stops(self):
        self.add_sound()
        with patch.object(self.frame, "play_personal_sound") as play:
            event = ui.wx.KeyEvent(ui.wx.EVT_KEY_DOWN.typeId)
            event.SetKeyCode(ui.wx.WXK_RETURN)
            self.panel.effect_list.GetEventHandler().ProcessEvent(event)
            play.assert_called_once_with(self.store.load().personal_sounds[0])
        event.SetKeyCode(ui.wx.WXK_SPACE)
        self.panel.effect_list.GetEventHandler().ProcessEvent(event)
        self.engine.stop_sound_effects.assert_called_once()


class PersonalSoundValidationTests(unittest.TestCase):
    def test_old_preferences_start_empty_and_bad_entries_do_not_hide_valid_ones(self):
        self.assertEqual(AppPreferences.from_dict({"schema_version": 8}).personal_sounds, ())
        preferences = AppPreferences.from_dict({"personal_sounds": [
            None, {"name": "", "path": "a.wav"}, {"name": 3, "path": "a.wav"},
            {"name": " Som ", "path": "missing.wav"},
        ]})
        self.assertEqual(preferences.personal_sounds, (PersonalSound("Som", "missing.wav"),))

    def test_previous_flat_list_migrates_in_groups_of_ten(self):
        preferences = AppPreferences.from_dict({"personal_sounds": [
            {"name": f"Som {i}", "path": f"{i}.wav"} for i in range(23)
        ]})
        self.assertEqual([sound.page for sound in preferences.personal_sounds], [0] * 10 + [1] * 10 + [2] * 3)
        loaded = AppPreferences.from_dict({"selected_sound_page": True, "personal_sounds": [
            {"name": "Som", "path": "sound.wav", "page": 99}
        ]})
        self.assertEqual(loaded.selected_sound_page, 0)
        self.assertEqual(loaded.personal_sounds[0].page, 0)

    def test_empty_and_long_audio_are_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sound.wav"
            sf.write(path, np.zeros(0), 8000)
            with self.assertRaises(SoundEffectError):
                validate_custom_audio(path)
            sf.write(path, np.zeros(8000 * 601), 8000)
            with self.assertRaises(SoundEffectError):
                validate_custom_audio(path)
