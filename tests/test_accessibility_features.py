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

    def test_native_controls_expose_their_own_accessible_labels(self):
        soundboard = self.frame.soundboard_panel

        def assert_msaa_name(control, expected):
            accessible = control.GetAccessible()
            self.assertIsNotNone(accessible)
            self.assertEqual(accessible.GetName(0), (ui.wx.ACC_OK, expected))

        self.assertEqual(soundboard.search.GetLabel(), "Buscar efeito na página atual")
        self.assertEqual(soundboard.search.GetName(), "Buscar efeito na página atual")
        assert_msaa_name(soundboard.search, "Buscar efeito na página atual")
        search_children = soundboard.search.GetChildren()
        search_text = next(
            child for child in search_children if isinstance(child, ui.wx.TextCtrl)
        )
        self.assertEqual(search_text.GetName(), "Buscar efeito na página atual")
        assert_msaa_name(search_text, "Buscar efeito na página atual")
        auxiliary_names = {
            child.GetName()
            for child in search_children
            if not isinstance(child, ui.wx.TextCtrl)
        }
        self.assertIn("Buscar efeito", auxiliary_names)
        self.assertIn("Limpar busca", auxiliary_names)
        for child in search_children:
            if not isinstance(child, ui.wx.TextCtrl):
                assert_msaa_name(child, child.GetName())

        choice_labels = (
            (self.frame.input_choice, "Microfone de entrada"),
            (self.frame.output_choice, "Saída virtual para Discord ou TeamTalk"),
            (
                self.frame.monitor_choice,
                "Dispositivo para ouvir os efeitos e o retorno da voz",
            ),
            (self.frame.voice_preset_choice, "Preset de modulação de voz"),
            (self.frame.creative_choice, "Estilo de voz especial"),
            (self.frame.modulation_choice, "Modulação"),
            (self.frame.ambience_choice, "Ambiente"),
            (self.frame.recording_panel.format_choice, "Formato do arquivo de áudio"),
            (self.frame.recording_panel.bitrate_choice, "Qualidade e taxa de bits"),
            (self.frame.recording_panel.mode_choice, "Modo de captura de áudio"),
        )
        for control, expected in choice_labels:
            with self.subTest(control=expected):
                self.assertEqual(control.GetLabel(), expected)
                self.assertEqual(control.GetName(), expected)
        self.assertEqual(self.frame.notebook.GetLabel(), "Guias da mesa de som")
        self.assertEqual(
            soundboard.effect_list.GetLabel(), "Lista de efeitos sonoros"
        )
        assert_msaa_name(soundboard.effect_list, soundboard.effect_list.GetName())

        dialog = ui.HotkeySettingsDialog(self.frame, self.store.load())
        try:
            self.assertEqual(
                dialog.effect_modifier.GetName(), "Modificador para tocar efeitos"
            )
            self.assertEqual(
                dialog.page_modifier.GetName(), "Modificador para trocar páginas"
            )
        finally:
            dialog.Destroy()

        labeled_ranges = (
            (self.frame.reverb_level, "Nível de reverb"),
            (self.frame.voice_pitch, "Ajuste de tom da voz em semitons"),
            (self.frame.delay_level, "Nível de eco"),
            (soundboard.volume, "Volume dos efeitos sonoros"),
            (soundboard.ducking_amount, "Intensidade do ducking dos efeitos"),
            (self.frame.spatial_x, "X, esquerda menos 100 e direita mais 100"),
            (self.frame.spatial_y, "Y, baixo menos 100 e cima mais 100"),
            (self.frame.spatial_z, "Z, trás menos 100 e frente mais 100"),
            (self.frame.spatial_speed, "Velocidade do movimento espacial automático"),
        )
        for control, expected in labeled_ranges:
            with self.subTest(control=expected):
                self.assertEqual(control.GetLabel(), expected)
                self.assertEqual(control.GetName(), expected)
