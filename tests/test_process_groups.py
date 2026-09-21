import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from mini_mesa import ui
from mini_mesa.process_audio import ProcessItem, list_candidate_processes


@pytest.mark.skipif(os.name != "nt", reason="Inventário do Windows")
def test_inventory_groups_executables_without_losing_pids():
    inventory = Mock(stdout='\n'.join([
        '"chrome.exe","30"', '"Chrome.EXE","10"', '"chrome.exe","30"',
        '"nvda.exe","20"', '"teamtalk.exe","40"',
        '"invalid.exe","bad"', '"zero.exe","0"',
    ]))
    with patch("mini_mesa.process_audio.subprocess.run", return_value=inventory):
        groups = list_candidate_processes()
    assert groups == (ProcessItem((10, 30), "chrome.exe"), ProcessItem((20,), "nvda.exe"))
    assert [group.label for group in groups] == ["chrome.exe", "nvda.exe"]


def make_frame(items=(), checked=(), saved=(), running=False):
    checks = set(checked)
    control = Mock()
    control.GetCheckedItems.side_effect = lambda: tuple(sorted(checks))
    control.Set.side_effect = lambda labels: checks.clear()
    control.Check.side_effect = lambda index, value: checks.add(index) if value else checks.discard(index)
    frame = SimpleNamespace(
        _process_items=items, process_list=control,
        preferences=SimpleNamespace(transmitted_processes=saved),
        engine=Mock(is_running=running), SetStatusText=Mock(),
        _format_process_item_label=ui.MainFrame._format_process_item_label,
    )
    frame._selected_process_pids = lambda: ui.MainFrame._selected_process_pids(frame)
    return frame


def test_selected_application_includes_every_pid_and_unchecking_removes_them():
    frame = make_frame((ProcessItem((10, 30), "chrome.exe"), ProcessItem((20,), "nvda.exe")), (0, 1))
    assert frame._selected_process_pids() == (10, 20, 30)
    frame.process_list.Check(0, False)
    assert frame._selected_process_pids() == (20,)


def test_refresh_keeps_application_checked_when_all_pids_change_and_updates_live_capture():
    frame = make_frame((ProcessItem((10, 30), "chrome.exe"),), (0,), running=True)
    with patch.object(ui, "list_candidate_processes", return_value=(ProcessItem((40, 50), "chrome.exe"),)):
        ui.MainFrame._refresh_processes(frame)
    assert frame._selected_process_pids() == (40, 50)
    frame.process_list.Set.assert_called_once_with(["chrome.exe, marcado"])
    frame.engine.update_transmitted_processes.assert_called_once_with((40, 50))


def test_old_saved_pid_selects_its_whole_group_on_initial_load():
    frame = make_frame(saved=(30,))
    with patch.object(ui, "list_candidate_processes", return_value=(ProcessItem((10, 30), "chrome.exe"),)):
        ui.MainFrame._refresh_processes(frame)
    assert frame._selected_process_pids() == (10, 30)
    frame.engine.update_transmitted_processes.assert_not_called()


def test_refresh_does_not_restore_a_group_the_user_unchecked():
    group = ProcessItem((10, 30), "chrome.exe")
    frame = make_frame((group,), saved=(30,))
    with patch.object(ui, "list_candidate_processes", return_value=(group,)):
        ui.MainFrame._refresh_processes(frame)
    assert frame._selected_process_pids() == ()


def test_refresh_does_not_capture_another_app_that_reuses_a_pid():
    frame = make_frame((ProcessItem((10,), "chrome.exe"),), (0,), running=True)
    with patch.object(ui, "list_candidate_processes", return_value=(ProcessItem((10,), "other.exe"),)):
        ui.MainFrame._refresh_processes(frame)
    assert frame._selected_process_pids() == ()
    frame.engine.update_transmitted_processes.assert_called_once_with(())
