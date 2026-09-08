import re
from pathlib import Path

from . import __version__


def _version_section(markdown: str, version: str) -> str:
    heading = re.compile(rf"^##\s+{re.escape(version)}(?:\s|$)", re.MULTILINE)
    match = heading.search(markdown)
    if match is None:
        raise OSError(f"A versão {version} não foi encontrada no histórico.")
    following = re.search(r"^##\s+", markdown[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(markdown)
    return markdown[match.start() : end].strip()


def _accessible_text(markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)]\(([^)]+)\)", r"\1 — \2", markdown)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*-\s+", "• ", line)
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def load_release_notes(changelog_path: Path | None = None) -> str:
    """Load this version's complete entry from the canonical changelog."""

    path = changelog_path or Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    try:
        markdown = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OSError("O histórico de versões não foi encontrado.") from exc
    text = _accessible_text(_version_section(markdown, __version__))
    if not text:
        raise OSError("As novidades desta versão estão vazias.")
    return text
