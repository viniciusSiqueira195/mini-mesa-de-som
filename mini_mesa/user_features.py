from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import tempfile
import zipfile

from . import __version__
from .preferences import AppPreferences, PersonalSound, default_preferences_path


_PACK_MANIFEST = "mini-mesa-backup.json"
_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


def _atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_preferences_path().with_name("profiles.json")

    def _load_all(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        profiles = data.get("profiles", {}) if isinstance(data, dict) else {}
        return profiles if isinstance(profiles, dict) else {}

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._load_all(), key=str.casefold))

    def save(self, name: str, preferences: AppPreferences) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Digite um nome para o perfil.")
        profiles = self._load_all()
        snapshot = asdict(preferences)
        snapshot.pop("welcome_shown", None)
        snapshot.pop("last_seen_news_version", None)
        profiles[name] = snapshot
        _atomic_json(self.path, {"schema_version": 1, "profiles": profiles})

    def load(self, name: str, current: AppPreferences) -> AppPreferences:
        snapshot = self._load_all().get(name)
        if not isinstance(snapshot, dict):
            raise KeyError(name)
        snapshot["welcome_shown"] = current.welcome_shown
        snapshot["last_seen_news_version"] = current.last_seen_news_version
        return AppPreferences.from_dict(snapshot)

    def delete(self, name: str) -> None:
        profiles = self._load_all()
        if name not in profiles:
            raise KeyError(name)
        del profiles[name]
        _atomic_json(self.path, {"schema_version": 1, "profiles": profiles})


def export_backup(
    preferences: AppPreferences, destination: Path, *, include_audio: bool
) -> None:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    snapshot = asdict(preferences)
    sounds = snapshot["personal_sounds"]
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if include_audio:
                for index, (sound_data, sound) in enumerate(
                    zip(sounds, preferences.personal_sounds, strict=True), start=1
                ):
                    source = Path(sound.path).resolve(strict=True)
                    if source.stat().st_size > 256 * 1024 * 1024:
                        raise ValueError(f"O arquivo '{source.name}' ultrapassa 256 MB.")
                    suffix = source.suffix.lower() or ".audio"
                    member = f"sounds/{index:03d}{suffix}"
                    archive.write(source, member)
                    sound_data["path"] = member
            manifest = {
                "format": "mini-mesa-backup",
                "format_version": 1,
                "app_version": __version__,
                "audio_included": include_audio,
                "preferences": snapshot,
            }
            archive.writestr(_PACK_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def import_backup(source: Path, audio_directory: Path) -> AppPreferences:
    source = source.resolve(strict=True)
    if source.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise ValueError("O backup ultrapassa 2 GB.")
    with zipfile.ZipFile(source) as archive:
        try:
            manifest = json.loads(archive.read(_PACK_MANIFEST))
        except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Este arquivo não é um backup válido da Mini Mesa.") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != "mini-mesa-backup":
            raise ValueError("Este arquivo não é um backup válido da Mini Mesa.")
        raw = manifest.get("preferences")
        if not isinstance(raw, dict):
            raise ValueError("O backup não contém preferências válidas.")
        if manifest.get("audio_included"):
            sounds = raw.get("personal_sounds", [])
            if not isinstance(sounds, list):
                raise ValueError("A lista de efeitos do backup é inválida.")
            infos = []
            total_size = 0
            for sound in sounds:
                if not isinstance(sound, dict) or not isinstance(sound.get("path"), str):
                    continue
                member = PurePosixPath(sound["path"])
                if member.is_absolute() or ".." in member.parts or member.parts[:1] != ("sounds",):
                    raise ValueError("O backup contém um caminho de áudio inseguro.")
                info = archive.getinfo(member.as_posix())
                total_size += info.file_size
                if info.file_size > 256 * 1024 * 1024 or total_size > _MAX_ARCHIVE_BYTES:
                    raise ValueError("Os áudios descompactados do backup ultrapassam o limite.")
                infos.append((sound, info))
            audio_directory.parent.mkdir(parents=True, exist_ok=True)
            target_directory = audio_directory
            counter = 2
            while target_directory.exists():
                target_directory = audio_directory.with_name(f"{audio_directory.name}-{counter}")
                counter += 1
            with tempfile.TemporaryDirectory(
                prefix=f".{audio_directory.name}-", dir=audio_directory.parent
            ) as staging_name:
                staging = Path(staging_name)
                targets = []
                for index, (sound, info) in enumerate(infos, start=1):
                    filename = f"{index:03d}_{Path(info.filename).name}"
                    target = staging / filename
                    with archive.open(info) as incoming, target.open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    targets.append((sound, filename))
                os.replace(staging, target_directory)
                for sound, filename in targets:
                    sound["path"] = str((target_directory / filename).resolve())
        return AppPreferences.from_dict(raw)


def diagnostic_text(engine, preferences: AppPreferences) -> str:
    details = getattr(engine, "diagnostic_details", lambda: {})()
    inputs = engine.input_devices()
    outputs = engine.output_devices()
    monitors = engine.monitor_devices()
    lines = [
        f"Mini Mesa de Som {__version__}",
        f"Windows: {platform.platform()}",
        f"Mesa ativa: {'sim' if engine.is_running else 'não'}",
        f"Microfone selecionado: {preferences.input_device or 'nenhum'}",
        f"Saída virtual selecionada: {preferences.output_device or 'nenhuma'}",
        f"Retorno selecionado: {preferences.monitor_device or 'nenhum'}",
        f"Retorno da voz: {'ligado' if preferences.monitor_enabled else 'desligado'}",
        "",
        f"Entradas encontradas ({len(inputs)}):",
        *(f"- {name}" for name in inputs),
        "",
        f"Saídas encontradas ({len(outputs)}):",
        *(f"- {name}" for name in outputs),
        "",
        f"Retornos encontrados ({len(monitors)}):",
        *(f"- {name}" for name in monitors),
    ]
    if details:
        lines.extend(("", "Detalhes das APIs de áudio:", json.dumps(details, ensure_ascii=False, indent=2)))
    return "\r\n".join(lines)
