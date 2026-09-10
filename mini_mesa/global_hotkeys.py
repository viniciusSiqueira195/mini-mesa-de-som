from __future__ import annotations

from collections.abc import Callable

import wx


_MODIFIERS = {
    "control": wx.MOD_CONTROL,
    "control_shift": wx.MOD_CONTROL | wx.MOD_SHIFT,
    "control_alt": wx.MOD_CONTROL | wx.MOD_ALT,
    "alt": wx.MOD_ALT,
    "alt_shift": wx.MOD_ALT | wx.MOD_SHIFT,
}


def modifier_label(value: str) -> str:
    return {
        "control": "Ctrl",
        "control_shift": "Ctrl+Shift",
        "control_alt": "Ctrl+Alt",
        "alt": "Alt",
        "alt_shift": "Alt+Shift",
    }[value]


class GlobalHotkeyManager:
    """Own system-wide shortcuts and release them as one transaction."""

    def __init__(self, window: wx.Window) -> None:
        self.window = window
        self._ids: list[int] = []

    def apply(
        self,
        *,
        enabled: bool,
        effect_modifier: str,
        page_modifier: str,
        play: Callable[[int], None],
        select_page: Callable[[int], None],
        stop: Callable[[], None],
        toggle_window: Callable[[], None] = lambda: None,
        window_toggle_enabled: bool = False,
        window_toggle_modifier: str = "control_alt",
        window_toggle_key: str = "M",
    ) -> None:
        self.close()
        if not enabled and not window_toggle_enabled:
            return
        registrations = []
        if enabled:
            for index in range(10):
                key = ord(str((index + 1) % 10))
                registrations.append((effect_modifier, key, lambda index=index: play(index)))
                registrations.append((page_modifier, key, lambda index=index: select_page(index)))
            registrations.append(("control_shift", ord("0"), stop))
        if window_toggle_enabled:
            registrations.append(
                (window_toggle_modifier, ord(window_toggle_key), toggle_window)
            )
        try:
            for modifier, key, action in registrations:
                identifier = int(wx.NewIdRef())
                if not self.window.RegisterHotKey(identifier, _MODIFIERS[modifier], key):
                    raise RuntimeError(
                        f"O atalho {modifier_label(modifier)}+{chr(key)} já está em uso."
                    )
                self._ids.append(identifier)
                self.window.Bind(wx.EVT_HOTKEY, lambda _event, action=action: action(), id=identifier)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for identifier in self._ids:
            self.window.UnregisterHotKey(identifier)
            self.window.Unbind(wx.EVT_HOTKEY, id=identifier)
        self._ids.clear()
