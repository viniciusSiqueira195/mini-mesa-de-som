from __future__ import annotations

import sys
from pathlib import Path


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Mini Mesa de Som"


def _launch_command() -> str:
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    return f'"{executable}" -m mini_mesa'


def configure_startup(enabled: bool) -> None:
    """Add or remove this user's Windows sign-in launch entry."""

    if not isinstance(enabled, bool):
        raise TypeError("Estado de iniciar com o Windows deve ser verdadeiro ou falso")
    if sys.platform != "win32":
        if enabled:
            raise RuntimeError("Iniciar com o Windows está disponível somente no Windows.")
        return

    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        _RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
            return
        try:
            winreg.DeleteValue(key, _VALUE_NAME)
        except FileNotFoundError:
            pass
