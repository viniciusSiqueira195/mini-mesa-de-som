from __future__ import annotations

from unittest.mock import Mock, patch

from mini_mesa.single_instance import SingleInstanceController


def test_non_windows_run_does_not_require_windows_instance_api() -> None:
    controller = SingleInstanceController()
    with patch("mini_mesa.single_instance.os.name", "posix"):
        assert controller.claim() is True
        controller.listen(Mock())
    controller.close()


def test_existing_instance_is_signalled_and_not_claimed() -> None:
    controller = SingleInstanceController()
    kernel32 = Mock()
    kernel32.CreateMutexW.return_value = 123

    with (
        patch("mini_mesa.single_instance.os.name", "nt"),
        patch("mini_mesa.single_instance._kernel32", return_value=kernel32),
        patch("mini_mesa.single_instance.ctypes.get_last_error", return_value=183),
        patch.object(controller, "_signal_existing_instance") as signal,
    ):
        assert controller.claim() is False

    signal.assert_called_once_with()
    kernel32.CloseHandle.assert_called_once_with(123)
