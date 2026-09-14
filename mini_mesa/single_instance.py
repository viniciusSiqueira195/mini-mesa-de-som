"""Keep the Windows mixer process unique and wake it from a new launch."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from ctypes import wintypes


_MUTEX_NAME = "Local\\MiniMesaDeSom.SingleInstance.v1"
_ACTIVATION_EVENT = "Local\\MiniMesaDeSom.ToggleWindow.v1"
_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0
_ERROR_ALREADY_EXISTS = 183


def _kernel32() -> Any:
    """Return typed kernel functions so Windows handles are never truncated."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = (
        wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR
    )
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class SingleInstanceController:
    """Own one app instance and ask it to toggle when launched again.

    A named Windows mutex owns the process-wide lock.  A named Windows event is
    used separately because a second launch must do something useful:
    it asks the first process to show or minimize its existing window.
    """

    def __init__(self) -> None:
        self._mutex: int | None = None
        self._activation_event: int | None = None
        self._stop = threading.Event()
        self._listener: threading.Thread | None = None

    def claim(self) -> bool:
        """Return whether this process is the only active application instance."""

        if os.name != "nt":
            return True
        mutex = _kernel32().CreateMutexW(None, False, _MUTEX_NAME)
        if not mutex:
            raise OSError(ctypes.get_last_error(), "Não foi possível iniciar a Mini Mesa.")
        if ctypes.get_last_error() != _ERROR_ALREADY_EXISTS:
            self._mutex = mutex
            return True
        _kernel32().CloseHandle(mutex)
        self._signal_existing_instance()
        return False

    def listen(self, on_activate: Callable[[], None]) -> None:
        """Deliver launches of the shortcut to the current application's UI."""

        if os.name != "nt":
            return
        kernel32 = _kernel32()
        event = kernel32.CreateEventW(None, False, False, _ACTIVATION_EVENT)
        if not event:
            raise OSError(ctypes.get_last_error(), "Não foi possível criar o sinal da Mini Mesa.")
        self._activation_event = event

        def wait_for_activation() -> None:
            while not self._stop.is_set():
                result = kernel32.WaitForSingleObject(event, 100)
                if result == _WAIT_OBJECT_0 and not self._stop.is_set():
                    on_activate()

        self._listener = threading.Thread(
            target=wait_for_activation, name="mini-mesa-window-toggle", daemon=True
        )
        self._listener.start()

    def close(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.join(timeout=0.3)
            self._listener = None
        if self._activation_event is not None:
            _kernel32().CloseHandle(self._activation_event)
            self._activation_event = None
        if self._mutex is not None:
            _kernel32().CloseHandle(self._mutex)
            self._mutex = None

    @staticmethod
    def _signal_existing_instance() -> None:
        kernel32 = _kernel32()
        # The first process creates the event during startup.  A short retry
        # handles a user double-clicking the shortcut while it is still opening.
        for _ in range(10):
            event = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, _ACTIVATION_EVENT)
            if event:
                try:
                    kernel32.SetEvent(event)
                finally:
                    kernel32.CloseHandle(event)
                return
            time.sleep(0.05)
