from pathlib import Path

from . import __version__


def load_release_notes() -> str:
    path = Path(__file__).parent / "assets" / "novidades" / f"{__version__}.txt"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OSError("O arquivo de novidades está vazio.")
    return text
