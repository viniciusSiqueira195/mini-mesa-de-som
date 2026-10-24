"""Windows process-loopback integration used by the real-time audio backend.

The native helper is deliberately a separate process: COM's process-loopback
activation is not exposed by PortAudio/sounddevice.  Its stdout is a binary
float32 stereo stream, while this module keeps all blocking I/O out of the
PortAudio callback.
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .drift import LevelTracker, drift_ratio, frames_needed, resample_block


_EXCLUDED = frozenset({
    "audiodg.exe", "csrss.exe", "dwm.exe", "explorer.exe", "lsass.exe",
    "mini_mesa.exe", "minimesadesom.exe", "placasom.exe", "services.exe",
    "smss.exe", "svchost.exe", "system.exe", "wininit.exe", "winlogon.exe",
})


def _hidden_subprocess_options() -> dict[str, object]:
    """Prevent console helpers from flashing a Command Prompt window."""

    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


class ProcessCaptureError(RuntimeError):
    """The selected programs' audio could not be captured (not a device error)."""


@dataclass(frozen=True, slots=True)
class ProcessItem:
    pids: tuple[int, ...]
    name: str

    @property
    def label(self) -> str:
        return self.name


def list_candidate_processes() -> tuple[ProcessItem, ...]:
    """Return current user-visible processes without evaluating shell input."""
    if os.name != "nt":
        return ()
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=4, check=True,
            **_hidden_subprocess_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    groups: dict[str, set[int]] = {}
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) < 2 or row[0].casefold() in _EXCLUDED:
            continue
        try:
            pid = int(row[1])
        except ValueError:
            continue
        if pid > 0:
            groups.setdefault(row[0].casefold(), set()).add(pid)
    return tuple(
        ProcessItem(tuple(sorted(pids)), name)
        for name, pids in sorted(groups.items())
    )


def _helper_path() -> Path | None:
    name = "Placasom.exe"
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent,
             Path(__file__).resolve().parent.parent]
    for root in roots:
        if root and (candidate := root / name).is_file():
            return candidate
    return None


# Frames used to fade a gap in the programs' audio out and back in, so a hole is never a click.
_GAP_FADE_FRAMES = 32


class ProcessAudioSource:
    """Non-blocking reader for PCM emitted by ``Placasom.exe --capture``."""

    # Defaults so a source built without ``__init__`` (tests) behaves like a fresh one.
    _resume_frames = 0
    _phase = 0.0
    _fade_in = False
    _drift_corrections = 0
    _dropped_frames = 0
    _sample_rate = 48_000.0
    _level: LevelTracker | None = None

    def __init__(self, numpy_module, pids: tuple[int, ...], sample_rate: float) -> None:
        helper = _helper_path()
        if helper is None:
            raise ProcessCaptureError(
                "A captura de programas não está instalada. Reinstale a Mini Mesa "
                "com o componente nativo de transmissão."
            )
        self._np = numpy_module
        self._sample_rate = float(sample_rate)
        self._lock = threading.Lock()
        self._samples = deque()
        self._available = 0
        # Process loopback and PortAudio run on separate clocks.  Do not start
        # consuming a partial first packet: wait for this small jitter buffer
        # instead, so the first scheduling wobble is not heard as a cut.
        self._prebuffer_frames = 0
        self._primed = True
        self._underflow_count = 0
        self._stopped = threading.Event()
        args = [str(helper), "--capture", str(round(sample_rate)), *(str(pid) for pid in pids)]
        try:
            self._process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, **_hidden_subprocess_options(),
            )
        except OSError as exc:
            raise ProcessCaptureError("Não foi possível iniciar a captura dos programas.") from exc
        self._reader = threading.Thread(target=self._read, name="mini-mesa-process-audio", daemon=True)
        self._reader.start()
        try:
            self._process.wait(timeout=0.12)
        except subprocess.TimeoutExpired:
            pass
        else:
            message = b""
            if self._process.stderr is not None:
                message = self._process.stderr.read()
            self.close()
            detail = message.decode("utf-8", "replace").strip()
            raise ProcessCaptureError(
                "A captura dos programas não foi iniciada"
                + (f": {detail}" if detail else ".")
            )

    def _read(self) -> None:
        assert self._process.stdout is not None
        frame_bytes = 8
        pending = b""
        while not self._stopped.is_set():
            # BufferedReader.read(8192) is allowed to wait for the whole
            # request.  The native helper normally emits 4096-byte packets,
            # which made this reader add a whole audio packet of latency and
            # periodically starve the real-time callback.  read1() returns as
            # soon as the pipe has a packet ready.
            read_available = getattr(self._process.stdout, "read1", None)
            chunk = (read_available(8192) if read_available is not None
                     else self._process.stdout.read(8192))
            if not chunk:
                return
            pending += chunk
            usable = len(pending) - len(pending) % frame_bytes
            if not usable:
                continue
            audio = self._np.frombuffer(pending[:usable], dtype="<f4").reshape(-1, 2).copy()
            pending = pending[usable:]
            with self._lock:
                self._samples.append(audio)
                self._available += len(audio)
                # Never let a stalled callback turn into unbounded memory/latency.
                while self._available > 96_000 and self._samples:
                    dropped = self._samples.popleft()
                    self._available -= len(dropped)
                    self._dropped_frames += len(dropped)

    def set_prebuffer_frames(self, frames: int) -> None:
        """Gate playback until a small, non-blocking jitter buffer is ready."""

        if frames < 0:
            raise ValueError("O pré-buffer de processos não pode ser negativo.")
        with self._lock:
            self._prebuffer_frames = frames
            self._primed = frames == 0

    @property
    def underflow_count(self) -> int:
        """Number of times the real-time mixer received too little process audio."""

        with self._lock:
            return self._underflow_count

    def take(self, frames: int):
        """Return ``frames`` of program audio, absorbing clock drift and gaps without clicks.

        The helper process captures on the programs' clock while the mixer pulls on the
        microphone's.  While the buffered amount stays in its band the audio is copied
        as is; when it wanders out, playback runs up to 1 % faster or slower
        (``mini_mesa.drift``).  If the buffer does run dry the audio fades out, stays
        silent until a small reserve is back and fades in again.
        """

        np = self._np
        output = np.zeros((frames, 2), dtype=np.float32)
        with self._lock:
            if not self._primed:
                if self._available < (self._resume_frames or self._prebuffer_frames):
                    return output
                self._primed = True
                self._resume_frames = 0
            ratio = self._drift_ratio()
            if ratio != 1.0 and self._take_resampled(output, frames, ratio):
                self._drift_corrections += 1
                return output
            self._phase = 0.0
            written = 0
            while written < frames and self._samples:
                block = self._samples[0]
                count = min(frames - written, len(block))
                output[written:written + count] = block[:count]
                written += count
                self._available -= count
                if count == len(block):
                    self._samples.popleft()
                else:
                    self._samples[0] = block[count:]
            if written and self._fade_in:
                fade = min(_GAP_FADE_FRAMES, written)
                output[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
                self._fade_in = False
            if written < frames:
                if written:
                    fade = min(_GAP_FADE_FRAMES, written)
                    output[written - fade:written] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)[:, None]
                    self._underflow_count += 1
                    self._fade_in = True
                    self._primed = False
                    self._resume_frames = max(frames * 2, self._prebuffer_frames // 2)
                    self._level = None
        return output

    def _drift_ratio(self) -> float:
        if self._prebuffer_frames <= 0:
            return 1.0
        if self._level is None:
            self._level = LevelTracker()
        average = self._level.update(self._available)
        if average is None:
            return 1.0
        reserve = self._prebuffer_frames
        return drift_ratio(average, 0.75 * reserve, 1.5 * reserve, 0.25 * reserve)

    def _take_resampled(self, output, frames: int, ratio: float) -> bool:
        np = self._np
        needed = frames_needed(frames, ratio, self._phase)
        if self._available < needed:
            return False
        parts = []
        gathered = 0
        for block in self._samples:
            parts.append(block)
            gathered += len(block)
            if gathered >= needed:
                break
        source = np.concatenate(parts, axis=0)[:needed]
        block, consumed, self._phase = resample_block(np, source, frames, ratio, self._phase)
        output[:] = block
        self._available -= consumed
        while consumed > 0 and self._samples:
            head = self._samples[0]
            if consumed >= len(head):
                consumed -= len(head)
                self._samples.popleft()
            else:
                self._samples[0] = head[consumed:]
                consumed = 0
        return True

    def statistics(self) -> dict[str, object]:
        with self._lock:
            return {
                "faltas_de_audio": self._underflow_count,
                "blocos_com_correcao_de_relogio": self._drift_corrections,
                "audio_descartado_ms": round(self._dropped_frames / max(1.0, float(self._sample_rate)) * 1000.0),
            }

    def close(self) -> None:
        self._stopped.set()
        if self._process.poll() is None:
            self._process.terminate()
        self._reader.join(timeout=0.5)
