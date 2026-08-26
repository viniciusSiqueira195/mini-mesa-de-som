from __future__ import annotations


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
