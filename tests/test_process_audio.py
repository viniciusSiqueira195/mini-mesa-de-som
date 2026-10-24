import os
import subprocess
import threading
from collections import deque
from unittest.mock import Mock, patch

import numpy as np
import pytest

from mini_mesa.process_audio import _EXCLUDED, ProcessAudioSource, list_candidate_processes


def test_teamtalk_is_offered_as_a_transmitted_process() -> None:
    assert not {
        "teamtalk.exe", "teamtalk5.exe", "teamtalkclassic.exe", "teamtalk5classic.exe",
    } & _EXCLUDED
    assert {"explorer.exe", "svchost.exe", "placasom.exe"} <= _EXCLUDED


@pytest.mark.skipif(os.name != "nt", reason="Comportamento específico do Windows")
def test_process_inventory_runs_without_a_visible_console() -> None:
    completed = Mock(stdout='"player.exe","123","Console","1,000 K"\n')
    with patch("mini_mesa.process_audio.subprocess.run", return_value=completed) as run:
        processes = list_candidate_processes()

    assert processes[0].pids == (123,)
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

    # The audio that was there fades out so the hole is not a click.
    assert rendered[0, 0] == np.float32(0.25)
    np.testing.assert_array_equal(rendered[1:], np.zeros((3, 2), dtype=np.float32))
    assert source.underflow_count == 1
    assert source.statistics()["faltas_de_audio"] == 1


def test_process_source_fades_a_gap_out_and_back_in_and_refills_before_resuming() -> None:
    source = _source_with_samples(np.full((64, 2), 0.5, dtype=np.float32))
    source.set_prebuffer_frames(0)
    source._primed = True

    rendered = source.take(128)

    tail = rendered[32:64, 0]
    assert tail[0] == np.float32(0.5) and tail[-1] == 0.0
    assert np.all(np.diff(tail) <= 0)
    assert source.underflow_count == 1
    assert not source._primed

    # One small packet is not enough to resume: it waits for a reserve to avoid stuttering.
    with source._lock:
        source._samples.append(np.full((64, 2), 0.5, dtype=np.float32))
        source._available += 64
    np.testing.assert_array_equal(source.take(64), np.zeros((64, 2), dtype=np.float32))
    assert source.underflow_count == 1

    with source._lock:
        source._samples.append(np.full((256, 2), 0.5, dtype=np.float32))
        source._available += 256
    resumed = source.take(64)
    assert resumed[0, 0] == 0.0 and resumed[31, 0] > resumed[1, 0]
    np.testing.assert_allclose(resumed[32:], 0.5)


def test_process_source_idle_program_does_not_count_underflows() -> None:
    source = _source_with_samples()
    source.set_prebuffer_frames(0)
    for _ in range(5):
        np.testing.assert_array_equal(source.take(64), np.zeros((64, 2), dtype=np.float32))
    assert source.underflow_count == 0
