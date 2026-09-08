from pathlib import Path
import tempfile

import pytest

from mini_mesa import __version__
from mini_mesa.release_notes import load_release_notes


def test_release_notes_are_the_complete_current_changelog_section() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        changelog = Path(directory) / "CHANGELOG.md"
        changelog.write_text(
            "# Histórico\n\n"
            f"## {__version__} — hoje\n\n### Recursos\n\n- Primeiro item com `atalho`.\n"
            "- Segundo item.\n\n## 1.0.0 — ontem\n\n- Antigo.\n",
            encoding="utf-8",
        )

        notes = load_release_notes(changelog)

        assert f"{__version__} — hoje" in notes
        assert "Recursos" in notes
        assert "• Primeiro item com atalho." in notes
        assert "• Segundo item." in notes
        assert "1.0.0" not in notes
        assert "#" not in notes
        assert "`" not in notes


def test_release_notes_fail_when_current_version_is_missing() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        changelog = Path(directory) / "CHANGELOG.md"
        changelog.write_text("## 0.0.1\n\n- Antigo.\n", encoding="utf-8")

        with pytest.raises(OSError, match=__version__):
            load_release_notes(changelog)
