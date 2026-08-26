from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


_APP_DIRECTORY = "Mini Mesa de Som Teste"
_PREFERENCES_FILENAME = "preferences.json"


def default_preferences_path() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / _APP_DIRECTORY / _PREFERENCES_FILENAME
    return Path.home() / ".config" / _APP_DIRECTORY / _PREFERENCES_FILENAME


@dataclass(frozen=True, slots=True)
class AppPreferences:
    input_device: str = ""
    output_device: str = ""
    monitor_enabled: bool = False
    monitor_device: str = ""
    reverb_enabled: bool = True
    reverb_level: int = 25
    noise_reduction_enabled: bool = False
    spatial_enabled: bool = False
    spatial_angle: int = 0

    @classmethod
    def from_dict(cls, data: object) -> AppPreferences:
        if not isinstance(data, dict):
            return cls()

        defaults = cls()

        def text_value(name: str, default: str) -> str:
            value = data.get(name, default)
            return value if isinstance(value, str) else default

        def bool_value(name: str, default: bool) -> bool:
            value = data.get(name, default)
            return value if isinstance(value, bool) else default

        level = data.get("reverb_level", defaults.reverb_level)
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 100:
            level = defaults.reverb_level

        spatial_angle = data.get("spatial_angle", defaults.spatial_angle)
        if (
            isinstance(spatial_angle, bool)
            or not isinstance(spatial_angle, int)
            or not -180 <= spatial_angle <= 180
        ):
            spatial_angle = defaults.spatial_angle

        return cls(
            input_device=text_value("input_device", defaults.input_device),
            output_device=text_value("output_device", defaults.output_device),
            monitor_enabled=bool_value(
                "monitor_enabled", defaults.monitor_enabled
            ),
            monitor_device=text_value("monitor_device", defaults.monitor_device),
            reverb_enabled=bool_value("reverb_enabled", defaults.reverb_enabled),
            reverb_level=level,
            noise_reduction_enabled=bool_value(
                "noise_reduction_enabled", defaults.noise_reduction_enabled
            ),
            spatial_enabled=bool_value("spatial_enabled", defaults.spatial_enabled),
            spatial_angle=spatial_angle,
        )


class PreferencesStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_preferences_path()

    def load(self) -> AppPreferences:
        try:
            with self.path.open("r", encoding="utf-8") as preferences_file:
                return AppPreferences.from_dict(json.load(preferences_file))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return AppPreferences()

    def save(self, preferences: AppPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
                json.dump(
                    {"schema_version": 3, **asdict(preferences)},
                    output,
                    ensure_ascii=False,
                    indent=2,
                )
                output.write("\n")
            os.replace(temporary_path, self.path)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
