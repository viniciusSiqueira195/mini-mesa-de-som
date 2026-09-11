from __future__ import annotations

import types
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from mini_mesa import ui


class _FakeEvent:
    def __init__(self, key_code: int = 0, selection: int = -1) -> None:
        self.key_code = key_code
        self.selection = selection
        self.skipped = False

    def Skip(self) -> None:
        self.skipped = True

    def GetKeyCode(self) -> int:
        return self.key_code

    def GetSelection(self) -> int:
        return self.selection


class _FakeControl:
    def __init__(self, *, value: bool = False, selection: int = 0) -> None:
        self.value = value
        self.selection = selection
        self.enabled = True

    def GetValue(self) -> bool:
        return self.value

    def GetSelection(self) -> int:
        return self.selection

    def Enable(self, enabled: bool) -> None:
        self.enabled = enabled


class RecordingControlTests(unittest.TestCase):
    def test_recording_requires_running_mixer(self) -> None:
        engine = Mock(is_recording=False, is_running=False)
        frame = Mock(engine=engine)
        panel = Mock(_frame=frame)

        ui.RecordingPanel._on_toggle_record(panel)

        frame._show_error.assert_called_once_with(
            "Inicie a mesa de som antes de iniciar a gravação."
        )
        engine.start_recording.assert_not_called()
        panel.timer.Start.assert_not_called()

    def test_running_mixer_can_start_recording(self) -> None:
        engine = Mock(is_recording=False, is_running=True)
        engine.start_recording.return_value = Path("recording.wav")
        frame = Mock(engine=engine)
        panel = Mock(_frame=frame)

        with patch.object(ui, "_set_button_accessible_name"):
            ui.RecordingPanel._on_toggle_record(panel)

        engine.start_recording.assert_called_once_with(panel._current_settings.return_value)
        panel.timer.Start.assert_called_once_with(1000)
        frame._show_error.assert_not_called()

    def test_active_recording_can_still_be_stopped(self) -> None:
        engine = Mock(is_recording=True, is_running=False)
        engine.stop_recording.return_value = (Path("recording.wav"), 2.0)
        frame = Mock(engine=engine)
        panel = Mock(_frame=frame)

        with patch.object(ui, "_set_button_accessible_name"):
            ui.RecordingPanel._on_toggle_record(panel)

        engine.stop_recording.assert_called_once_with()
        panel.timer.Stop.assert_called_once_with()
        frame._show_error.assert_not_called()


class VoiceControlTests(unittest.TestCase):
    def test_removed_voice_presets_are_not_offered(self) -> None:
        presets = [value for value, _label, _pitch in ui._VOICE_PRESETS]
        self.assertNotIn("autotune", presets)
        self.assertNotIn("vocoder", presets)

    def test_voice_controls_follow_enabled_state(self) -> None:
        for enabled in (True, False):
            frame = types.SimpleNamespace(
                voice_checkbox=_FakeControl(value=enabled),
                voice_preset_choice=_FakeControl(),
                voice_pitch=_FakeControl(),
                voice_compatibility=_FakeControl(),
            )
            ui.MainFrame._update_voice_controls(frame)
            self.assertEqual(frame.voice_preset_choice.enabled, enabled)
            self.assertEqual(frame.voice_pitch.enabled, enabled)
            self.assertEqual(frame.voice_compatibility.enabled, enabled)


class ProcessSelectionAnnouncementTests(unittest.TestCase):
    @staticmethod
    def _frame(*, checked: bool, running: bool):
        messages: list[str] = []
        labels: dict[int, str] = {}
        checked_states: dict[int, bool] = {0: checked}
        return types.SimpleNamespace(
            _process_items=(types.SimpleNamespace(pid=42, label="player.exe (PID 42)"),),
            process_list=types.SimpleNamespace(
                IsChecked=lambda index: checked,
                SetString=labels.__setitem__,
                Check=checked_states.__setitem__,
            ),
            engine=types.SimpleNamespace(is_running=running),
            _save_preferences=lambda: None,
            _format_process_item_label=ui.MainFrame._format_process_item_label,
            SetStatusText=messages.append,
            messages=messages,
            labels=labels,
            checked_states=checked_states,
        )

    def test_checked_program_announcement_identifies_the_process(self) -> None:
        frame = self._frame(checked=True, running=False)
        event = _FakeEvent(selection=0)

        ui.MainFrame._on_process_selection_changed(frame, event)

        self.assertEqual(frame.messages, ["player.exe (PID 42): marcado para transmissão."])
        self.assertEqual(frame.labels.get(0), "player.exe (PID 42), marcado")
        self.assertTrue(event.skipped)

    def test_unchecked_program_says_it_applies_on_next_activation(self) -> None:
        frame = self._frame(checked=False, running=True)

        ui.MainFrame._on_process_selection_changed(frame, _FakeEvent(selection=0))

        self.assertEqual(
            frame.messages,
            ["player.exe (PID 42): desmarcado para transmissão. "
             "A alteração será aplicada ao reativar a mesa."],
        )
        self.assertEqual(frame.labels.get(0), "player.exe (PID 42), desmarcado")

    def test_running_program_selection_is_applied_immediately(self) -> None:
        frame = self._frame(checked=True, running=True)
        applied: list[tuple[int, ...]] = []
        frame._selected_process_pids = lambda: (42,)
        frame.engine.update_transmitted_processes = lambda pids: applied.append(pids)

        ui.MainFrame._on_process_selection_changed(frame, _FakeEvent(selection=0))

        self.assertEqual(applied, [(42,)])
        self.assertEqual(
            frame.messages,
            ["player.exe (PID 42): marcado para transmissão. Alteração aplicada agora."],
        )

    def test_process_item_label_includes_marcado_state_for_nvda(self) -> None:
        item = types.SimpleNamespace(label="discord.exe (PID 1234)")
        self.assertEqual(
            ui.MainFrame._format_process_item_label(item, is_checked=True),
            "discord.exe (PID 1234), marcado",
        )
        self.assertEqual(
            ui.MainFrame._format_process_item_label(item, is_checked=False),
            "discord.exe (PID 1234), desmarcado",
        )

    def test_process_controls_remain_enabled_while_route_controls_are_locked(self) -> None:
        class Control:
            def __init__(self):
                self.calls = []

            def Enable(self, *args):
                self.calls.append(args)

        frame = types.SimpleNamespace(
            input_choice=Control(), output_choice=Control(), monitor_checkbox=Control(),
            monitor_choice=Control(), playback_output_choice=Control(),
            refresh_button=Control(), process_list=Control(),
            refresh_processes_button=Control(), playback_process_list=Control(),
            refresh_playback_processes_button=Control(), noise_reduction_checkbox=Control(),
        )

        ui.MainFrame._set_routing_controls_enabled(frame, False)

        self.assertEqual(frame.input_choice.calls, [(False,)])
        self.assertEqual(frame.process_list.calls, [()])
        self.assertEqual(frame.refresh_processes_button.calls, [()])



class CreativeChoiceEventTests(unittest.TestCase):
    @staticmethod
    def _frame(applied: list[str]):
        frame = types.SimpleNamespace(
            _creative_update_queued=False,
            _apply_creative_settings=lambda: applied.append("applied"),
        )
        frame._queue_creative_update = types.MethodType(
            ui.MainFrame._queue_creative_update, frame
        )
        frame._apply_queued_creative_settings = types.MethodType(
            ui.MainFrame._apply_queued_creative_settings, frame
        )
        return frame

    def test_choice_update_runs_after_the_native_selection_is_committed(self) -> None:
        applied: list[str] = []
        queued = []
        frame = self._frame(applied)
        event = _FakeEvent()

        with patch.object(ui.wx, "CallAfter", side_effect=queued.append):
            ui.MainFrame._on_creative_choice_changed(frame, event)

        self.assertTrue(event.skipped)
        self.assertEqual(applied, [])
        self.assertEqual(len(queued), 1)
        queued[0]()
        self.assertEqual(applied, ["applied"])


    def test_keyboard_and_choice_events_coalesce_into_one_live_update(self) -> None:
        applied: list[str] = []
        queued = []
        frame = self._frame(applied)
        key_event = _FakeEvent(ui.wx.WXK_DOWN)
        choice_event = _FakeEvent()

        with patch.object(ui.wx, "CallAfter", side_effect=queued.append):
            ui.MainFrame._on_creative_choice_key_up(frame, key_event)
            ui.MainFrame._on_creative_choice_changed(frame, choice_event)

        self.assertTrue(key_event.skipped)
        self.assertTrue(choice_event.skipped)
        self.assertEqual(len(queued), 1)
        queued[0]()
        self.assertEqual(applied, ["applied"])


class ApplicationEngineTests(unittest.TestCase):
    def test_application_starts_with_the_effect_capable_audio_engine(self) -> None:
        app = unittest.mock.Mock()
        frame = unittest.mock.Mock()
        engine = object()
        with (
            patch.object(ui.wx, "App", return_value=app),
            patch.object(ui, "AudioEngine", return_value=engine) as constructor,
            patch.object(ui, "MainFrame", return_value=frame) as main_frame,
        ):
            result = ui.run()

        self.assertEqual(result, 0)
        constructor.assert_called_once_with()
        main_frame.assert_called_once_with(engine)
        frame.Show.assert_called_once_with()
        app.MainLoop.assert_called_once_with()


class HelpContentTests(unittest.TestCase):
    def test_f1_help_inherits_project_shortcuts_and_credits_from_readme(self) -> None:
        help_text = ui._load_project_help()

        for expected in (
            "Mini Mesa de Som",
            "F1",
            "Ctrl+Shift+E",
            "Paulo Santesso",
            "paulosantesso1",
            "viniciusSiqueira195",
        ):
            self.assertIn(expected, help_text)

    def test_markdown_is_simplified_for_screen_readers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(
                "# Ajuda\n\n- Use `F1`.\n[Projeto](https://example.com)",
                encoding="utf-8",
            )

            help_text = ui._load_project_help(readme)

        self.assertEqual(
            help_text,
            "Ajuda\n\n• Use F1.\nProjeto — https://example.com",
        )

    def test_markdown_headings_remain_semantic_in_web_mode(self) -> None:
        html = ui._markdown_to_help_html(
            "# Mini Mesa\n\n## Atalhos\n\n### Créditos"
        )

        self.assertIn("<html lang='pt-BR'>", html)
        self.assertIn('<h1 id="mini-mesa">Mini Mesa</h1>', html)
        self.assertIn('<h2 id="atalhos">Atalhos</h2>', html)
        self.assertIn('<h3 id="creditos">Créditos</h3>', html)

    def test_missing_readme_has_an_actionable_fallback(self) -> None:
        help_text = ui._load_project_help(Path("missing-readme-for-test.md"))

        self.assertIn("documentação completa não foi encontrada", help_text)
        self.assertIn("github.com", help_text)

if __name__ == "__main__":
    unittest.main()
