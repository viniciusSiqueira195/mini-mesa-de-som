import os
import subprocess
from unittest.mock import Mock, patch

import pytest

from mini_mesa.process_audio import list_candidate_processes


@pytest.mark.skipif(os.name != "nt", reason="Comportamento específico do Windows")
def test_process_inventory_runs_without_a_visible_console() -> None:
    completed = Mock(stdout='"player.exe","123","Console","1,000 K"\n')
    with patch("mini_mesa.process_audio.subprocess.run", return_value=completed) as run:
        processes = list_candidate_processes()

    assert processes[0].pid == 123
    assert processes[0].name == "player.exe"
    assert run.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    startupinfo = run.call_args.kwargs["startupinfo"]
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
