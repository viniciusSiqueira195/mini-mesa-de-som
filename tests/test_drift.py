"""Clock-drift compensation: the controller, the resampler and the two queues that use them."""
from __future__ import annotations

import threading
from collections import deque
from unittest.mock import Mock

import numpy as np

from mini_mesa.drift import (
    MAX_ADJUST,
    LevelTracker,
    drift_ratio,
    frames_needed,
    resample_block,
)
from mini_mesa.audio_engine import _BufferedAudioOutput
from mini_mesa.process_audio import ProcessAudioSource

RATE = 48_000
BLOCK = 512
FREQUENCY = 440.0
AMPLITUDE = 0.5


def test_ratio_is_exactly_one_inside_the_band_and_grows_with_the_distance() -> None:
    assert drift_ratio(100, 50, 150, 100) == 1.0
    assert drift_ratio(50, 50, 150, 100) == 1.0
    assert drift_ratio(150, 50, 150, 100) == 1.0
    assert 1.0 < drift_ratio(175, 50, 150, 100) < drift_ratio(225, 50, 150, 100) <= 1.0 + MAX_ADJUST
    assert 1.0 - MAX_ADJUST <= drift_ratio(0, 50, 150, 100) < drift_ratio(25, 50, 150, 100) < 1.0
    assert drift_ratio(10_000, 50, 150, 100) == 1.0 + MAX_ADJUST
    assert drift_ratio(-10_000, 50, 150, 100) == 1.0 - MAX_ADJUST


def test_level_tracker_waits_for_the_warm_up_and_then_smooths() -> None:
    tracker = LevelTracker(warmup=3, smoothing=0.5)
    assert [tracker.update(100.0) for _ in range(3)] == [None, None, None]
    assert tracker.update(100.0) == 100.0
    assert tracker.update(200.0) == 150.0
    tracker.reset()
    assert tracker.update(10.0) is None


def test_resampling_a_sine_stays_continuous_across_blocks() -> None:
    index = np.arange(20 * BLOCK)
    wave = (AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * index / RATE)).astype(np.float32)
    source = np.repeat(wave[:, None], 2, axis=1)
    phase, position, rendered = 0.0, 0, []
    for _ in range(10):
        needed = frames_needed(BLOCK, 1.004, phase)
        block, consumed, phase = resample_block(np, source[position:position + needed], BLOCK, 1.004, phase)
        rendered.append(block[:, 0])
        position += consumed
    signal = np.concatenate(rendered)
    steepest = AMPLITUDE * 2 * np.pi * FREQUENCY / RATE
    assert np.abs(np.diff(signal)).max() <= steepest * 1.02
    assert position == int(10 * BLOCK * 1.004)


def _smoothness(signal: np.ndarray) -> float:
    """Largest sample-to-sample step relative to a pure sine's steepest one."""
    return float(np.abs(np.diff(signal)).max() / (AMPLITUDE * 2 * np.pi * FREQUENCY / RATE))


def _simulate_output(drift: float, seconds: float = 120.0):
    """The microphone pushes blocks on a clock ``drift`` faster than the output drains them."""
    sounddevice = Mock()
    output = _BufferedAudioOutput(
        sounddevice=sounddevice, output_id=7, sample_rate=RATE, output_channels=2, block_size=BLOCK,
    )
    produced = 0

    def push_block() -> None:
        nonlocal produced
        index = np.arange(BLOCK) + produced
        output.push((AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * index / RATE)).astype(np.float32))
        produced += BLOCK

    push_block()
    push_block()
    credit = 0.0
    rendered = []
    for number in range(int(seconds * RATE / BLOCK)):
        credit += BLOCK * (1.0 + drift)
        while credit >= BLOCK:
            credit -= BLOCK
            push_block()
        destination = np.zeros((BLOCK, 2), dtype=np.float32)
        output._on_output(destination, BLOCK, None, None)
        if number >= 2:
            rendered.append(destination[:, 0].copy())
    return output, np.concatenate(rendered)


def test_output_absorbs_a_faster_microphone_without_dropping_blocks() -> None:
    for drift in (0.001, 0.003, 0.008):
        output, signal = _simulate_output(drift)
        assert output._dropped_block_count == 0, drift
        assert output._underrun_count == 0, drift
        assert output._drift_corrections > 0, drift
        assert _smoothness(signal) <= 1.05, drift


def test_output_absorbs_a_slower_microphone_without_going_silent() -> None:
    for drift in (-0.001, -0.003, -0.005):
        output, signal = _simulate_output(drift)
        assert output._dropped_block_count == 0, drift
        assert output._underrun_count == 0, drift
        assert output._drift_corrections > 0, drift
        assert _smoothness(signal) <= 1.05, drift


def test_output_without_drift_is_never_resampled() -> None:
    output, signal = _simulate_output(0.0, seconds=30.0)
    assert output._drift_corrections == 0
    assert output._dropped_block_count == 0 and output._underrun_count == 0
    assert _smoothness(signal) <= 1.001


def _source_with_stream(prebuffer: int = 4_800) -> ProcessAudioSource:
    source = ProcessAudioSource.__new__(ProcessAudioSource)
    source._np = np
    source._lock = threading.Lock()
    source._samples = deque()
    source._available = 0
    source._prebuffer_frames = prebuffer
    source._primed = False
    source._underflow_count = 0
    return source


def _simulate_process_source(drift: float, seconds: float = 120.0):
    """The helper process delivers packets on a clock ``drift`` faster than the mixer reads them."""
    source = _source_with_stream()
    produced = 0
    credit = 0.0
    rendered = []

    def deliver() -> None:
        nonlocal produced
        index = np.arange(BLOCK) + produced
        wave = (AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * index / RATE)).astype(np.float32)
        packet = np.repeat(wave[:, None], 2, axis=1)
        with source._lock:
            source._samples.append(packet)
            source._available += len(packet)
        produced += BLOCK

    for _ in range(12):
        deliver()
    for number in range(int(seconds * RATE / BLOCK)):
        credit += BLOCK * (1.0 + drift)
        while credit >= BLOCK:
            credit -= BLOCK
            deliver()
        block = source.take(BLOCK)
        if number >= 1:
            rendered.append(block[:, 0].copy())
    return source, np.concatenate(rendered)


def test_process_source_absorbs_drift_in_both_directions_without_gaps() -> None:
    for drift in (0.001, 0.004, -0.001, -0.004):
        source, signal = _simulate_process_source(drift)
        assert source.underflow_count == 0, drift
        assert source._drift_corrections > 0, drift
        assert _smoothness(signal) <= 1.05, drift
        assert 0 < source._available < 96_000, drift


def test_process_source_without_drift_is_copied_untouched() -> None:
    source, signal = _simulate_process_source(0.0, seconds=30.0)
    assert source._drift_corrections == 0 and source.underflow_count == 0
    assert _smoothness(signal) <= 1.001
