from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib import error, request

from . import __version__


GITHUB_OWNER = "viniciusSiqueira195"
GITHUB_REPOSITORY = "mini-mesa-de-som"
HTTP_TIMEOUT_SECONDS = 20
DOWNLOAD_CHUNK_SIZE = 256 * 1024


class UpdateError(RuntimeError):
    """Raised when an update cannot be checked, downloaded, or launched."""


class UpdateCancelled(UpdateError):
    """Raised when the user cancels an update download."""


def can_self_update() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_notes: str
    release_page_url: str
    installer_name: str
    installer_url: str
    installer_size: int
    checksum_url: str


def normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if text.casefold().startswith("v"):
        text = text[1:]
    match = re.search(r"\d+(?:\.\d+)*", text)
    return match.group(0) if match else text


def is_newer_version(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def check_for_update(current_version: str = __version__) -> UpdateInfo | None:
    latest = fetch_latest_release(current_version)
    if is_newer_version(latest.latest_version, current_version):
        return latest
    return None


def fetch_latest_release(current_version: str = __version__) -> UpdateInfo:
    api_url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
        "/releases/latest"
    )
    try:
        payload = json.loads(_download_text(api_url, "application/vnd.github+json"))
    except (error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
        raise UpdateError("Não foi possível verificar as atualizações.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("A resposta de atualização do GitHub é inválida.")

    latest_version = normalize_version(
        str(payload.get("tag_name") or payload.get("name") or "")
    )
    assets = payload.get("assets")
    if not latest_version or not isinstance(assets, list):
        raise UpdateError("A release mais recente não contém dados válidos.")

    installer = _select_installer(assets, latest_version)
    checksum = _select_checksum(assets, latest_version)
    if installer is None or checksum is None:
        raise UpdateError(
            "A release mais recente não contém o instalador e sua assinatura SHA-256."
        )

    installer_url = str(installer.get("browser_download_url") or "").strip()
    checksum_url = str(checksum.get("browser_download_url") or "").strip()
    if not installer_url or not checksum_url:
        raise UpdateError("Os links da atualização são inválidos.")

    return UpdateInfo(
        current_version=normalize_version(current_version),
        latest_version=latest_version,
        release_notes=str(payload.get("body") or "").strip(),
        release_page_url=str(payload.get("html_url") or "").strip(),
        installer_name=str(installer.get("name") or "").strip(),
        installer_url=installer_url,
        installer_size=_safe_int(installer.get("size")),
        checksum_url=checksum_url,
    )


def download_installer(
    update: UpdateInfo,
    *,
    progress_callback=None,
    cancel_event: Event | None = None,
) -> Path:
    expected_checksum = _read_checksum(update.checksum_url)
    destination = Path(tempfile.mkdtemp(prefix="mini-mesa-update-"))
    target = destination / update.installer_name
    partial = target.with_suffix(f"{target.suffix}.part")
    digest = hashlib.sha256()
    downloaded = 0
    completed = False

    try:
        download_request = request.Request(
            update.installer_url,
            headers=_headers("application/octet-stream"),
        )
        with request.urlopen(download_request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            total = _safe_int(response.headers.get("Content-Length"))
            if total <= 0:
                total = update.installer_size
            with partial.open("wb") as destination_file:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateCancelled("Download cancelado.")
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    destination_file.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total)

        if update.installer_size > 0 and downloaded != update.installer_size:
            raise UpdateError("O instalador baixado está incompleto.")
        if digest.hexdigest().casefold() != expected_checksum.casefold():
            raise UpdateError("A validação SHA-256 do instalador falhou.")
        with partial.open("rb") as downloaded_file:
            signature = downloaded_file.read(2)
        if signature != b"MZ":
            raise UpdateError("O arquivo baixado não é um instalador do Windows.")
        os.replace(partial, target)
        completed = True
        return target
    except UpdateError:
        raise
    except (OSError, error.URLError, error.HTTPError) as exc:
        raise UpdateError("Não foi possível baixar a atualização.") from exc
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
        if not completed:
            try:
                destination.rmdir()
            except OSError:
                pass


def launch_installer(installer_path: Path) -> None:
    installer = installer_path.resolve()
    if not installer.is_file():
        raise UpdateError("O instalador baixado não foi encontrado.")
    try:
        subprocess.Popen(
            [
                str(installer),
                "/VERYSILENT",
                "/SP-",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/NOCANCEL",
                "/MERGETASKS=!vbcable",
            ],
            cwd=str(installer.parent),
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError("Não foi possível abrir o instalador da atualização.") from exc


def _select_installer(assets: list[dict], version: str) -> dict | None:
    expected = f"MiniMesaDeSom-Setup-{version}.exe".casefold()
    return next(
        (
            asset
            for asset in assets
            if str(asset.get("name") or "").casefold() == expected
        ),
        next(
            (
                asset
                for asset in assets
                if str(asset.get("name") or "").casefold().startswith(
                    "minimesadesom-setup-"
                )
                and str(asset.get("name") or "").casefold().endswith(".exe")
            ),
            None,
        ),
    )


def _select_checksum(assets: list[dict], version: str) -> dict | None:
    expected = f"MiniMesaDeSom-Setup-{version}.exe.sha256".casefold()
    return next(
        (
            asset
            for asset in assets
            if str(asset.get("name") or "").casefold() == expected
        ),
        next(
            (
                asset
                for asset in assets
                if str(asset.get("name") or "").casefold().endswith(".sha256")
            ),
            None,
        ),
    )


def _read_checksum(url: str) -> str:
    try:
        content = _download_text(url, "text/plain")
    except (error.URLError, error.HTTPError) as exc:
        raise UpdateError("Não foi possível baixar a assinatura da atualização.") from exc
    match = re.search(r"\b[a-fA-F0-9]{64}\b", content)
    if match is None:
        raise UpdateError("A assinatura SHA-256 da atualização é inválida.")
    return match.group(0)


def _download_text(url: str, accept: str) -> str:
    download_request = request.Request(url, headers=_headers(accept))
    with request.urlopen(download_request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _headers(accept: str) -> dict[str, str]:
    return {"Accept": accept, "User-Agent": f"MiniMesaDeSom/{__version__}"}


def _version_key(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", normalize_version(version))]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
