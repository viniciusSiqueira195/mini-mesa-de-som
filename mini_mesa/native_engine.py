"""Python control surface for the single native C++ audio engine."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, NamedTuple

from .process_audio import _helper_path


class _Route(NamedTuple):
    input_device: str
    output_device: str
    monitor_output: str | None
    process_pids: tuple[int, ...]


class NativeAudioEngine:
    native_only = True

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._on_error: Callable[[str], None] | None = None
        self._mic_volume = self._process_volume = 1.0
        self._input_level = 0.0
        self._route: _Route | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def input_level(self) -> float:
        return self._input_level

    def set_error_handler(self, handler: Callable[[str], None] | None) -> None:
        self._on_error = handler

    def _helper(self) -> Path:
        helper = _helper_path()
        if helper is None:
            raise RuntimeError("Placasom.exe não foi encontrado. Reinstale a Mini Mesa.")
        return helper

    def _list_devices(self) -> tuple[tuple[str, str, str], ...]:
        try:
            result = subprocess.run([str(self._helper()), "--list"], capture_output=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Não foi possível listar os dispositivos de áudio.") from exc
        items = []
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split("\t", 3)
            if len(parts) == 4 and parts[0] == "DEVICE":
                items.append((parts[1], parts[2], parts[3]))
        return tuple(items)

    def input_devices(self) -> tuple[str, ...]:
        return tuple(name for flow, _id, name in self._list_devices() if flow == "capture")

    def output_devices(self) -> tuple[str, ...]:
        return tuple(name for flow, _id, name in self._list_devices() if flow == "render")

    def monitor_devices(self) -> tuple[str, ...]:
        return self.output_devices()

    def set_volumes(self, microphone: float, processes: float) -> None:
        if not all(0.0 <= value <= 2.0 for value in (microphone, processes)):
            raise ValueError("O volume deve estar entre 0 e 200 por cento.")
        self._mic_volume, self._process_volume = microphone, processes
        if self.is_running:
            self._send(f"mic:{microphone * 100:.0f}\nproc:{processes * 100:.0f}\n")

    def start(self, input_device: str, output_device: str, monitor_output: str | None = None, *, process_pids=(), **_ignored) -> None:
        route = _Route(input_device, output_device, monitor_output, tuple(sorted({int(pid) for pid in process_pids if int(pid) > 0})))
        with self._lock:
            if self.is_running:
                raise RuntimeError("A mesa já está ativa.")
        self._start_route(route)

    def _start_route(self, route: _Route) -> None:
        devices = self._list_devices()
        input_id = next((device_id for flow, device_id, name in devices if flow == "capture" and name == route.input_device), None)
        output_id = next((device_id for flow, device_id, name in devices if flow == "render" and name == route.output_device), None)
        monitor_id = next((device_id for flow, device_id, name in devices if flow == "render" and name == route.monitor_output), "-1")
        if input_id is None or output_id is None:
            raise ValueError("Atualize os dispositivos e escolha microfone e saída virtual válidos.")
        command = [str(self._helper()), "--run", input_id, output_id, monitor_id, f"{self._mic_volume:.2f}", f"{self._process_volume:.2f}", *(str(pid) for pid in route.process_pids)]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        status: dict[str, object] = {"ready": False, "message": "O motor nativo não confirmou a inicialização."}
        ready = threading.Event()
        with self._lock:
            self._process = process
        threading.Thread(target=self._watch, args=(process, ready, status), daemon=True, name="mini-mesa-native-engine").start()
        if not ready.wait(timeout=12.0) or not status["ready"]:
            self.stop()
            raise RuntimeError(str(status["message"]))
        with self._lock:
            if self._process is not process:
                raise RuntimeError(str(status["message"]))
            self._route = route

    def _watch(self, process: subprocess.Popen[bytes], ready: threading.Event, status: dict[str, object]) -> None:
        assert process.stdout is not None
        message = "Motor nativo encerrado."
        for line in iter(process.stdout.readline, b""):
            text = line.decode("utf-8", "replace").strip()
            if text == "READY":
                status["ready"] = True
                ready.set()
            elif text.startswith("ERROR\t"):
                message = text.split("\t", 1)[1]
                status["message"] = message
        process.wait()
        ready.set()
        with self._lock:
            expected = self._process is not process
            if self._process is process:
                self._process = None
                self._route = None
        if not expected and self._on_error is not None:
            self._on_error(message)

    def _send(self, text: str) -> None:
        with self._lock:
            if self._process is not None and self._process.stdin is not None:
                self._process.stdin.write(text.encode("ascii"))
                self._process.stdin.flush()

    def stop(self, *, timeout: float = 3.0) -> None:
        with self._lock:
            process, self._process = self._process, None
            self._route = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.write(b"stop\n")
                process.stdin.flush()
            except OSError:
                pass
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=timeout)

    def update_monitor(self, monitor_output: str | None, **_kwargs) -> None:
        with self._lock:
            previous = self._route
        if previous is None:
            raise RuntimeError("A mesa não está ativa.")
        requested = previous._replace(monitor_output=monitor_output)
        if requested == previous:
            return
        self.stop()
        try:
            self._start_route(requested)
        except Exception as update_error:
            try:
                self._start_route(previous)
            except Exception as restore_error:
                raise RuntimeError(f"Não foi possível alterar o retorno nem restaurar a rota anterior. Alteração: {update_error}. Restauração: {restore_error}.") from restore_error
            raise RuntimeError(f"Não foi possível alterar o retorno; a rota anterior foi restaurada. Detalhes: {update_error}") from update_error

    # Compatibility with the current interface; these effects are outside the
    # first C++ engine migration.
    def update_noise_reduction(self, *_args): pass
    def update_settings(self, *_args): pass
    def update_voice_settings(self, *_args): pass
    def update_creative_settings(self, *_args): pass
    def update_pro_audio_settings(self, *_args): pass
    def update_soundboard_settings(self, *_args): pass
    def update_spatial(self, *_args): pass
    def stop_sound_effects(self): pass
    def play_sound(self, *_args): return False
    def preview_sound(self, *_args): raise RuntimeError("O painel de efeitos não faz parte do motor nativo.")
    def stop_preview(self): pass
    def sound_effects(self): return ()
    def play_sound_effect(self, *_args): raise RuntimeError("O painel de efeitos não faz parte do motor nativo.")
    def diagnostic_details(self): return {"backend": "WASAPI Process Loopback (C++)"}
