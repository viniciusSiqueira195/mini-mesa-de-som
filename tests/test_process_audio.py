import os
import subprocess
import threading
from collections import deque
from unittest.mock import Mock, patch

import numpy as np
import pytest

from mini_mesa.process_audio import ProcessAudioSource, list_candidate_processes


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


def _source_with_samples(*blocks: np.ndarray) -> ProcessAudioSource:
    """Create the buffer portion of a source without starting its helper."""

    source = ProcessAudioSource.__new__(ProcessAudioSource)
    source._np = np
    source._lock = threading.Lock()
    source._samples = deque(blocks)
    source._available = sum(len(block) for block in blocks)
    source._prebuffer_frames = 0
    source._primed = True
    source._underflow_count = 0
    return source


def test_process_source_waits_for_its_jitter_buffer_before_mixing() -> None:
    first = np.full((4, 2), 0.25, dtype=np.float32)
    source = _source_with_samples(first)
    source.set_prebuffer_frames(8)

    np.testing.assert_array_equal(source.take(4), np.zeros((4, 2), dtype=np.float32))
    assert source._available == 4

    second = np.full((4, 2), 0.5, dtype=np.float32)
    with source._lock:
        source._samples.append(second)
        source._available += len(second)

    np.testing.assert_array_equal(source.take(4), first)


def test_process_source_records_an_underflow_after_it_is_primed() -> None:
    source = _source_with_samples(np.full((2, 2), 0.25, dtype=np.float32))

    rendered = source.take(4)

    np.testing.assert_allclose(rendered[:2], 0.25)
    np.testing.assert_array_equal(rendered[2:], np.zeros((2, 2), dtype=np.float32))
    assert source.underflow_count == 1
