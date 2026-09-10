from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mini_mesa import startup


class StartupTests(unittest.TestCase):
    def test_enabling_creates_a_per_user_windows_run_entry(self) -> None:
        key = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = key
        with (
            patch("mini_mesa.startup.sys.platform", "win32"),
            patch("winreg.CreateKeyEx", return_value=context) as create_key,
            patch("winreg.SetValueEx") as set_value,
        ):
            startup.configure_startup(True)

        self.assertEqual(create_key.call_args.args[0], __import__("winreg").HKEY_CURRENT_USER)
        self.assertEqual(set_value.call_args.args[1], "Mini Mesa de Som")
        self.assertIn("mini_mesa", set_value.call_args.args[4])

    def test_disabling_removes_the_per_user_run_entry(self) -> None:
        key = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = key
        with (
            patch("mini_mesa.startup.sys.platform", "win32"),
            patch("winreg.CreateKeyEx", return_value=context),
            patch("winreg.DeleteValue") as delete_value,
        ):
            startup.configure_startup(False)

        self.assertEqual(delete_value.call_args.args[1], "Mini Mesa de Som")
