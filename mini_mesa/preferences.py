from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .settings import (
    VALID_AMBIENCES,
    VALID_CREATIVE_PRESETS,
    VALID_MODULATIONS,
    VALID_VOICE_PRESETS,
)


_APP_DIRECTORY = "Mini Mesa de Som"
_LEGACY_APP_DIRECTORIES = ("Mini Mesa de Som Teste",)
_PREFERENCES_FILENAME = "preferences.json"


def default_preferences_path() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / _APP_DIRECTORY / _PREFERENCES_FILENAME
    return Path.home() / ".config" / _APP_DIRECTORY / _PREFERENCES_FILENAME


def legacy_preferences_paths() -> tuple[Path, ...]:
    app_data = os.environ.get("APPDATA")
    root = Path(app_data) if app_data else Path.home() / ".config"
    return tuple(
        root / directory / _PREFERENCES_FILENAME
        for directory in _LEGACY_APP_DIRECTORIES
    )


@dataclass(frozen=True, slots=True)
class PersonalSound:
    name: str
    path: str
    page: int = 0


def _personal_sounds(value: object) -> tuple[PersonalSound, ...]:
    if not isinstance(value, list):
        return ()
    sounds = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        name, path = item.get("name"), item.get("path")
        if isinstance(name, str) and isinstance(path, str) and name.strip() and path.strip():
            page = item.get("page", min(index // 10, 9))
            if isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < 10:
                page = 0
            sounds.append(PersonalSound(name.strip(), path.strip(), page))
    return tuple(sounds)


@dataclass(frozen=True, slots=True)
class AppPreferences:
    welcome_shown: bool = False
    last_seen_news_version: str = ""
    input_device: str = ""
    output_device: str = ""
    monitor_enabled: bool = False
    monitor_device: str = ""
    reverb_enabled: bool = True
    reverb_level: int = 25
    noise_reduction_enabled: bool = False
    spatial_enabled: bool = False
    spatial_x: int = 0
    spatial_y: int = 0
    spatial_z: int = 100
    spatial_automatic: bool = False
    spatial_speed: int = 35
    voice_enabled: bool = False
    voice_preset: str = "female"
    voice_pitch_semitones: float = 4.0
    creative_effect_preset: str = "none"
    modulation_effect: str = "none"
    ambience_preset: str = "none"
    delay_enabled: bool = False
    delay_level_percent: int = 30
    style_intensity_percent: int = 70
    modulation_intensity_percent: int = 60
    ambience_intensity_percent: int = 50
    roger_beep_enabled: bool = False
    compressor_enabled: bool = False
    eq_enabled: bool = False
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0
    noise_gate_enabled: bool = False
    deesser_enabled: bool = False
    expander_enabled: bool = False
    auto_gain_enabled: bool = False
    plosive_filter_enabled: bool = False
    soundboard_volume_percent: int = 80
    soundboard_ducking_enabled: bool = False
    soundboard_ducking_percent: int = 60
    personal_sounds: tuple[PersonalSound, ...] = ()
    selected_sound_page: int = 0

    @property
    def spatial_angle(self) -> int:
        """Legacy horizontal angle retained for older integrations."""

        if self.spatial_x == 0 and self.spatial_z == 0:
            return 0
        return round(math.degrees(math.atan2(self.spatial_x, self.spatial_z)))

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

        def float_db_value(name: str, default: float) -> float:
            val = data.get(name, default)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not -12.0 <= float(val) <= 12.0:
                return default
            return float(val)

        level = data.get("reverb_level", defaults.reverb_level)
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 100:
            level = defaults.reverb_level

        def coordinate_value(name: str, default: int) -> int:
            value = data.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int):
                return default
            return value if -100 <= value <= 100 else default

        if not any(name in data for name in ("spatial_x", "spatial_y", "spatial_z")):
            old_angle = data.get("spatial_angle", 0)
            if (
                isinstance(old_angle, bool)
                or not isinstance(old_angle, int)
                or not -180 <= old_angle <= 180
            ):
                old_angle = 0
            radians = math.radians(old_angle)
            spatial_x = round(math.sin(radians) * 100)
            spatial_y = 0
            spatial_z = round(math.cos(radians) * 100)
        else:
            spatial_x = coordinate_value("spatial_x", defaults.spatial_x)
            spatial_y = coordinate_value("spatial_y", defaults.spatial_y)
            spatial_z = coordinate_value("spatial_z", defaults.spatial_z)

        spatial_speed = data.get("spatial_speed", defaults.spatial_speed)
        if (
            isinstance(spatial_speed, bool)
            or not isinstance(spatial_speed, int)
            or not 1 <= spatial_speed <= 100
        ):
            spatial_speed = defaults.spatial_speed

        voice_pitch = data.get("voice_pitch_semitones", defaults.voice_pitch_semitones)
        if (
            isinstance(voice_pitch, bool)
            or not isinstance(voice_pitch, (int, float))
            or not -12.0 <= float(voice_pitch) <= 12.0
        ):
            voice_pitch = defaults.voice_pitch_semitones
        else:
            voice_pitch = float(voice_pitch)

        preset = text_value("creative_effect_preset", defaults.creative_effect_preset)
        if preset not in VALID_CREATIVE_PRESETS:
            preset = defaults.creative_effect_preset
        legacy_voice_presets = {
            4.0: "female",
            3.0: "female_soft",
            6.0: "female_thin",
            -4.0: "male",
        }
        voice_preset = text_value(
            "voice_preset",
            legacy_voice_presets.get(voice_pitch, "custom"),
        )
        removed_voice_preset = voice_preset in ("autotune", "vocoder")
        if removed_voice_preset:
            voice_preset = "custom"
            voice_pitch = 0.0
        if voice_preset not in VALID_VOICE_PRESETS:
            voice_preset = defaults.voice_preset
        modulation = text_value("modulation_effect", defaults.modulation_effect)
        if modulation not in VALID_MODULATIONS:
            modulation = defaults.modulation_effect
        ambience = text_value("ambience_preset", defaults.ambience_preset)
        if ambience not in VALID_AMBIENCES:
            ambience = defaults.ambience_preset

        delay_level = data.get("delay_level_percent", defaults.delay_level_percent)
        if (
            isinstance(delay_level, bool)
            or not isinstance(delay_level, int)
            or not 0 <= delay_level <= 100
        ):
            delay_level = defaults.delay_level_percent

        def percent_value(name: str, default: int) -> int:
            value = data.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                return default
            return value

        style_intensity = percent_value(
            "style_intensity_percent", defaults.style_intensity_percent
        )
        modulation_intensity = percent_value(
            "modulation_intensity_percent", defaults.modulation_intensity_percent
        )
        ambience_intensity = percent_value(
            "ambience_intensity_percent", defaults.ambience_intensity_percent
        )

        sb_volume = data.get("soundboard_volume_percent", defaults.soundboard_volume_percent)
        if (
            isinstance(sb_volume, bool)
            or not isinstance(sb_volume, int)
            or not 0 <= sb_volume <= 100
        ):
            sb_volume = defaults.soundboard_volume_percent

        selected_page = data.get("selected_sound_page", 0)
        if isinstance(selected_page, bool) or not isinstance(selected_page, int) or not 0 <= selected_page < 10:
            selected_page = 0
        return cls(
            selected_sound_page=selected_page,
            personal_sounds=_personal_sounds(data.get("personal_sounds")),
            last_seen_news_version=text_value("last_seen_news_version", ""),
            welcome_shown=bool_value("welcome_shown", defaults.welcome_shown),
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
            spatial_x=spatial_x,
            spatial_y=spatial_y,
            spatial_z=spatial_z,
            spatial_automatic=bool_value(
                "spatial_automatic", defaults.spatial_automatic
            ),
            spatial_speed=spatial_speed,
            voice_enabled=bool_value("voice_enabled", defaults.voice_enabled) and not removed_voice_preset,
            voice_preset=voice_preset,
            voice_pitch_semitones=voice_pitch,
            creative_effect_preset=preset,
            modulation_effect=modulation,
            ambience_preset=ambience,
            delay_enabled=bool_value("delay_enabled", defaults.delay_enabled),
            delay_level_percent=delay_level,
            style_intensity_percent=style_intensity,
            modulation_intensity_percent=modulation_intensity,
            ambience_intensity_percent=ambience_intensity,
            roger_beep_enabled=bool_value(
                "roger_beep_enabled", defaults.roger_beep_enabled
            ),
            compressor_enabled=bool_value("compressor_enabled", defaults.compressor_enabled),
            eq_enabled=bool_value("eq_enabled", defaults.eq_enabled),
            eq_low_db=float_db_value("eq_low_db", defaults.eq_low_db),
            eq_mid_db=float_db_value("eq_mid_db", defaults.eq_mid_db),
            eq_high_db=float_db_value("eq_high_db", defaults.eq_high_db),
            noise_gate_enabled=bool_value(
                "noise_gate_enabled", defaults.noise_gate_enabled
            ),
            deesser_enabled=bool_value("deesser_enabled", defaults.deesser_enabled),
            expander_enabled=bool_value("expander_enabled", defaults.expander_enabled),
            auto_gain_enabled=bool_value("auto_gain_enabled", defaults.auto_gain_enabled),
            plosive_filter_enabled=bool_value(
                "plosive_filter_enabled", defaults.plosive_filter_enabled
            ),
            soundboard_volume_percent=sb_volume,
            soundboard_ducking_enabled=bool_value(
                "soundboard_ducking_enabled", defaults.soundboard_ducking_enabled
            ),
            soundboard_ducking_percent=percent_value(
                "soundboard_ducking_percent", defaults.soundboard_ducking_percent
            ),
        )


class PreferencesStore:
    def __init__(
        self,
        path: Path | None = None,
        *,
        legacy_paths: Sequence[Path] | None = None,
    ) -> None:
        uses_default_path = path is None
        self.path = path or default_preferences_path()
        self.legacy_paths = tuple(
            legacy_preferences_paths() if uses_default_path and legacy_paths is None
            else legacy_paths or ()
        )

    def load(self) -> AppPreferences:
        for candidate in (self.path, *self.legacy_paths):
            try:
                with candidate.open("r", encoding="utf-8") as preferences_file:
                    preferences = AppPreferences.from_dict(json.load(preferences_file))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if candidate != self.path:
                try:
                    self.save(preferences)
                except OSError:
                    pass
            return preferences
        return AppPreferences()

    def save(self, preferences: AppPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
                json.dump(
                    {"schema_version": 11, **asdict(preferences)},
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
