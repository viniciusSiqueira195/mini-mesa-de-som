from __future__ import annotations

import sys
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "mini_mesa"


def main() -> int:
    try:
        from .ui import run
    except ImportError as exc:
        print(
            "Não foi possível carregar a interface. "
            "Instale as dependências com: python -m pip install -e ."
        )
        print(f"Detalhes: {exc}")
        return 1

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
