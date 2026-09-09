"""Exercise the shipped executable without the development Python on PATH."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def verify(executable: Path, result_path: Path) -> dict:
    executable = executable.resolve(strict=True)
    result_path = result_path.resolve()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        environment.pop(name, None)
    windows = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    with tempfile.TemporaryDirectory(prefix="mini-mesa-package-") as directory:
        process = subprocess.run(
            [str(executable), "--self-test", str(result_path)],
            cwd=directory,
            env=environment,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    if not result_path.is_file():
        raise RuntimeError(f"O executável não produziu diagnóstico. Código: {process.returncode}.")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if process.returncode != 0 or result.get("ok") is not True:
        raise RuntimeError(f"Autoteste do pacote falhou: {result.get('error', result)}")
    for feature in (
        "pedalboard",
        "rnnoise",
        "hrtf",
        "interface",
        "help",
        "release_notes",
        "recording",
        "recording_beep",
        "user_features",
    ):
        if result.get(feature) is not True:
            raise RuntimeError(f"Autoteste incompleto: {feature}.")
    if set(result.get("codecs", [])) != {"wav", "mp3", "flac", "ogg"}:
        raise RuntimeError("Autoteste incompleto: codecs de áudio.")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    verify(args.executable, args.result)
    print(f"Executável verificado. Diagnóstico: {args.result}")
