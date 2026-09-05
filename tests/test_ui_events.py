from __future__ import annotations

import types
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from mini_mesa import ui


class _FakeEvent:
    def __init__(self, key_code: int = 0) -> None:
        self.key_code = key_code
        self.skipped = False

    def Skip(self) -> None:
        self.skipped = True

    def GetKeyCode(self) -> int:
        return self.key_code


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
            )
            ui.MainFrame._update_voice_controls(frame)
            self.assertEqual(frame.voice_preset_choice.enabled, enabled)
            self.assertEqual(frame.voice_pitch.enabled, enabled)


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
