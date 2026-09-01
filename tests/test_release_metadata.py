from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from mini_mesa import __version__


_ROOT = Path(__file__).resolve().parent.parent


class ReleaseMetadataTests(unittest.TestCase):
    def test_version_is_consistent_across_package_project_and_installer(self) -> None:
        project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        installer = (_ROOT / "installer" / "MiniMesaDeSom.iss").read_text(
            encoding="utf-8"
        )

        self.assertEqual(project["project"]["version"], __version__)
        self.assertIn(f'#define AppVersion "{__version__}"', installer)
        self.assertIn(f"VersionInfoVersion={__version__}.0", installer)

    def test_release_uses_the_final_product_name(self) -> None:
        project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        ui_source = (_ROOT / "mini_mesa" / "ui.py").read_text(encoding="utf-8")
        package_source = (_ROOT / "mini_mesa" / "__init__.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual(project["project"]["name"], "mini-mesa-de-som")
        self.assertIsNone(re.search(r"Mini Mesa de Som Teste", ui_source))
        self.assertIsNone(re.search(r"Mini Mesa de Som Teste", package_source))


if __name__ == "__main__":
    unittest.main()
