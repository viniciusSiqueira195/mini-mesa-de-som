import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mini_mesa.audio_engine import PedalboardBackend
from tools.verify_frozen_app import verify


class PackagingTests(unittest.TestCase):
    def test_wasapi_does_not_hide_other_monitor_devices(self):
        backend = PedalboardBackend()
        backend._output_ids = {
            "Fone WASAPI": [(1, "Windows WASAPI")],
            "Caixas MME": [(2, "MME")],
            "Fone DirectSound": [(3, "Windows DirectSound")],
            "Cabo Virtual": [(4, "Windows WASAPI")],
        }
        with patch.object(backend, "_refresh_devices"):
            devices = backend.monitor_devices()
        self.assertEqual(devices[0], "Fone WASAPI")
        self.assertEqual(set(devices), {"Fone WASAPI", "Caixas MME", "Fone DirectSound"})
        backend.deactivate()

    def test_frozen_verifier_requires_complete_success_in_isolated_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "app.exe"
            executable.touch()
            result_path = root / "result.json"
            result = dict(ok=True, pedalboard=True, rnnoise=True, hrtf=True,
                          interface=True, help=True, release_notes=True,
                          user_features=True, codecs=["wav", "mp3", "flac", "ogg"])

            def run(command, **kwargs):
                self.assertEqual(command, [str(executable), "--self-test", str(result_path)])
                self.assertNotEqual(Path(kwargs["cwd"]), executable.parent)
                self.assertNotIn("PYTHONPATH", kwargs["env"])
                self.assertNotIn("VIRTUAL_ENV", kwargs["env"])
                self.assertNotIn("venv", kwargs["env"]["PATH"])
                result_path.write_text(json.dumps(result), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with patch("tools.verify_frozen_app.subprocess.run", side_effect=run):
                self.assertEqual(verify(executable, result_path), result)
                result["rnnoise"] = False
                with self.assertRaisesRegex(RuntimeError, "rnnoise"):
                    verify(executable, result_path)

    def test_old_success_report_cannot_mask_a_crashed_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "app.exe"
            executable.touch()
            result = root / "result.json"
            result.write_text('{"ok":true}', encoding="utf-8")
            with patch("tools.verify_frozen_app.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaisesRegex(RuntimeError, "não produziu diagnóstico"):
                    verify(executable, result)
