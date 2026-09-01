from __future__ import annotations

import argparse
import hashlib
import http.server
import shutil
import threading
from functools import partial
from pathlib import Path

from mini_mesa import __version__
from mini_mesa.updater import UpdateInfo, download_installer


def verify_update_artifacts(output_directory: Path) -> None:
    output_directory = output_directory.resolve()
    installer_name = f"MiniMesaDeSom-Setup-{__version__}.exe"
    installer = output_directory / installer_name
    checksum_file = output_directory / f"{installer_name}.sha256"
    if not installer.is_file() or not checksum_file.is_file():
        raise RuntimeError("O instalador ou sua assinatura SHA-256 não foi encontrado.")

    payload_hash = hashlib.sha256(installer.read_bytes()).hexdigest()
    published_hash = checksum_file.read_text(encoding="ascii").split()[0].casefold()
    if payload_hash != published_hash:
        raise RuntimeError("A assinatura publicada não corresponde ao instalador.")
    if installer.read_bytes()[:2] != b"MZ":
        raise RuntimeError("O artefato não possui assinatura executável MZ.")

    handler = partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(output_directory),
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    downloaded: Path | None = None
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        update = UpdateInfo(
            current_version="0.1.0",
            latest_version=__version__,
            release_notes="Teste local do atualizador.",
            release_page_url=base_url,
            installer_name=installer_name,
            installer_url=f"{base_url}/{installer_name}",
            installer_size=installer.stat().st_size,
            checksum_url=f"{base_url}/{installer_name}.sha256",
        )
        downloaded = download_installer(update)
        downloaded_hash = hashlib.sha256(downloaded.read_bytes()).hexdigest()
        if downloaded_hash != payload_hash:
            raise RuntimeError("O atualizador alterou o instalador durante o download.")
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        if downloaded is not None:
            shutil.rmtree(downloaded.parent, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida os artefatos da release pelo fluxo real de download."
    )
    parser.add_argument(
        "output_directory",
        nargs="?",
        type=Path,
        default=Path("installer-output"),
    )
    arguments = parser.parse_args()
    verify_update_artifacts(arguments.output_directory)
    print(f"Atualizador validado com os artefatos da versão {__version__}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
