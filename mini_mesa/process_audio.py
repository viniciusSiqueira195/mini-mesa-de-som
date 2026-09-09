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


@dataclass(frozen=True, slots=True)
class ProcessItem:
    pid: int
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} (PID {self.pid})"


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
    items: list[ProcessItem] = []
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) < 2 or row[0].casefold() in _EXCLUDED:
            continue
        try:
            pid = int(row[1])
        except ValueError:
            continue
        if pid > 0:
            items.append(ProcessItem(pid, row[0]))
    return tuple(sorted(items, key=lambda item: (item.name.casefold(), item.pid)))


def _helper_path() -> Path | None:
    name = "Placasom.exe"
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent,
             Path(__file__).resolve().parent.parent]
    for root in roots:
        if root and (candidate := root / name).is_file():
            return candidate
    return None


class ProcessAudioSource:
    """Non-blocking reader for PCM emitted by ``Placasom.exe --capture``."""

    def __init__(self, numpy_module, pids: tuple[int, ...], sample_rate: float) -> None:
        helper = _helper_path()
        if helper is None:
            raise RuntimeError(
                "A captura de programas não está instalada. Reinstale a Mini Mesa "
                "com o componente nativo de transmissão."
            )
        self._np = numpy_module
        self._lock = threading.Lock()
        self._samples = deque()
        self._available = 0
        self._stopped = threading.Event()
        args = [str(helper), "--capture", str(round(sample_rate)), *(str(pid) for pid in pids)]
        try:
            self._process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, **_hidden_subprocess_options(),
            )
        except OSError as exc:
            raise RuntimeError("Não foi possível iniciar a captura dos programas.") from exc
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
            raise RuntimeError(
                "A captura dos programas não foi iniciada"
                + (f": {detail}" if detail else ".")
            )

    def _read(self) -> None:
        assert self._process.stdout is not None
        frame_bytes = 8
        pending = b""
        while not self._stopped.is_set():
            chunk = self._process.stdout.read(8192)
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

    def take(self, frames: int):
        output = self._np.zeros((frames, 2), dtype=self._np.float32)
        written = 0
        with self._lock:
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
        return output

    def close(self) -> None:
        self._stopped.set()
        if self._process.poll() is None:
            self._process.terminate()
        self._reader.join(timeout=0.5)
