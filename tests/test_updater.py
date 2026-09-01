from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mini_mesa import updater


class UpdaterTests(unittest.TestCase):
    def test_versions_are_compared_numerically(self) -> None:
        self.assertTrue(updater.is_newer_version("v0.10.0", "0.9.9"))
        self.assertFalse(updater.is_newer_version("v0.1.0", "0.1.0"))
        self.assertFalse(updater.is_newer_version("1.0.0", "1.0"))
        self.assertFalse(updater.is_newer_version("1.0", "1.0.0"))

    def test_latest_release_requires_matching_installer_and_checksum(self) -> None:
        payload = {
            "tag_name": "v0.2.0",
            "body": "Correções importantes.",
            "html_url": "https://example.invalid/release",
            "assets": [
                {
                    "name": "MiniMesaDeSom-Setup-0.2.0.exe",
                    "browser_download_url": "https://example.invalid/setup.exe",
                    "size": 123,
                },
                {
                    "name": "MiniMesaDeSom-Setup-0.2.0.exe.sha256",
                    "browser_download_url": "https://example.invalid/setup.sha256",
                },
            ],
        }
        with patch.object(updater, "_download_text", return_value=json.dumps(payload)):
            info = updater.fetch_latest_release("0.1.0")

        self.assertEqual(info.latest_version, "0.2.0")
        self.assertEqual(info.installer_size, 123)
        self.assertTrue(info.checksum_url.endswith("setup.sha256"))

    def test_same_release_does_not_offer_an_update(self) -> None:
        info = updater.UpdateInfo(
            current_version="0.1.0",
            latest_version="0.1.0",
            release_notes="",
            release_page_url="",
            installer_name="MiniMesaDeSom-Setup-0.1.0.exe",
            installer_url="https://example.invalid/setup.exe",
            installer_size=1,
            checksum_url="https://example.invalid/setup.sha256",
        )
        with patch.object(updater, "fetch_latest_release", return_value=info):
            self.assertIsNone(updater.check_for_update("0.1.0"))

    def test_downloaded_installer_must_match_published_checksum(self) -> None:
        payload = b"MZmini-mesa-installer"
        info = updater.UpdateInfo(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_notes="",
            release_page_url="",
            installer_name="MiniMesaDeSom-Setup-0.2.0.exe",
            installer_url="https://example.invalid/setup.exe",
            installer_size=len(payload),
            checksum_url="https://example.invalid/setup.sha256",
        )

        class FakeResponse:
            headers = {"Content-Length": str(len(payload))}

            def __init__(self) -> None:
                self._content = io.BytesIO(payload)

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self, size: int = -1) -> bytes:
                return self._content.read(size)

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(
                    updater,
                    "_read_checksum",
                    return_value=hashlib.sha256(payload).hexdigest(),
                ),
                patch.object(updater.request, "urlopen", return_value=FakeResponse()),
                patch.object(
                    updater.tempfile,
                    "mkdtemp",
                    return_value=temporary_directory,
                ),
            ):
                installer = updater.download_installer(info)

            self.assertEqual(installer, Path(temporary_directory) / info.installer_name)
            self.assertEqual(installer.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
