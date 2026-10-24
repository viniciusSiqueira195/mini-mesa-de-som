"""Clock-drift compensation for queues fed and drained by different audio clocks.

The microphone, the virtual cable and the captured programs each run on their
own clock.  Even at the same nominal sample rate they differ by a few parts per
thousand, so a queue between two of them slowly fills up or runs dry.  Dropping
a block when it overflows, or inserting silence when it empties, is audible as
a click.  Instead, the reader of the queue plays slightly faster or slower than
real time (never more than ``MAX_ADJUST``) while the smoothed queue level is
outside a comfortable band, which absorbs the drift without any discontinuity.
"""
from __future__ import annotations

import math

# Largest speed change, as a fraction (1 % is about 17 cents, inaudible on speech).
MAX_ADJUST = 0.01
# Callbacks to wait before correcting anything: the start-up level is not drift.
WARMUP_CALLBACKS = 100
# Weight of each new level in the running average (about 50 callbacks of memory).
SMOOTHING = 0.02


def drift_ratio(level: float, low: float, high: float, span: float, max_adjust: float = MAX_ADJUST) -> float:
    """Playback speed for a queue holding ``level`` frames: 1.0 inside [low, high].

    Above ``high`` the reader speeds up and below ``low`` it slows down, in
    proportion to how far the level is outside the band, reaching ``max_adjust``
    after ``span`` frames.
    """

    if span <= 0:
        return 1.0
    if level > high:
        return 1.0 + min(max_adjust, max_adjust * (level - high) / span)
    if level < low:
        return 1.0 - min(max_adjust, max_adjust * (low - level) / span)
    return 1.0


class LevelTracker:
    """Smoothed queue level, available only after a warm-up."""

    def __init__(self, warmup: int = WARMUP_CALLBACKS, smoothing: float = SMOOTHING) -> None:
        self._warmup = warmup
        self._smoothing = smoothing
        self._average: float | None = None
        self._callbacks = 0

    def update(self, level: float) -> float | None:
        self._callbacks += 1
        if self._average is None:
            self._average = float(level)
        else:
            self._average += (level - self._average) * self._smoothing
        return self._average if self._callbacks > self._warmup else None

    def reset(self) -> None:
        self._average = None
        self._callbacks = 0


def frames_needed(frames: int, ratio: float, phase: float) -> int:
    """Source frames a resampled block of ``frames`` reads, counting the interpolation neighbour."""

    return int(math.ceil(phase + frames * ratio)) + 1


def resample_block(np, source, frames: int, ratio: float, phase: float):
    """Linearly resample ``frames`` output frames from ``source`` at speed ``ratio``.

    ``source`` needs at least ``frames_needed`` rows.  Returns the block, how many
    source frames were consumed and the fractional position to carry to the next block.
    """

    position = phase + np.arange(frames, dtype=np.float64) * ratio
    base = position.astype(np.int64)
    fraction = (position - base).astype(np.float32)[:, None]
    block = source[base] * (1.0 - fraction) + source[base + 1] * fraction
    advance = phase + frames * ratio
    consumed = int(advance)
    return block.astype(np.float32), consumed, advance - consumed
