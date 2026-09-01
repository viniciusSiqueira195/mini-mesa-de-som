from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from mini_mesa import ui


class _FakeEvent:
    def __init__(self, key_code: int = 0) -> None:
        self.key_code = key_code
        self.skipped = False

    def Skip(self) -> None:
        self.skipped = True

    def GetKeyCode(self) -> int:
        return self.key_code


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


if __name__ == "__main__":
    unittest.main()
