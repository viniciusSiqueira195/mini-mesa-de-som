from __future__ import annotations

from dataclasses import dataclass


_MIX_HEADROOM = 0.90
_MAX_WET_SHARE = 0.80


def _validate_percent(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} deve ser um número inteiro")
    if not 0 <= value <= 100:
        raise ValueError(f"{name} deve estar entre 0 e 100")


@dataclass(frozen=True, slots=True)
class ReverbSettings:
    """A single user-facing level mapped to the internal reverb parameters."""

    level_percent: int = 25
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_percent("Nível de reverb", self.level_percent)
        if not isinstance(self.enabled, bool):
            raise TypeError("Estado do reverb deve ser verdadeiro ou falso")

    @property
    def normalized_level(self) -> float:
        return self.level_percent / 100.0

    @property
    def wet_level(self) -> float:
        if not self.enabled:
            return 0.0
        return _MIX_HEADROOM * _MAX_WET_SHARE * self.normalized_level

    @property
    def dry_level(self) -> float:
        if not self.enabled:
            return _MIX_HEADROOM
        return _MIX_HEADROOM - self.wet_level

    @property
    def room_size(self) -> float:
        return 0.25 + (0.60 * self.normalized_level)

    @property
    def damping(self) -> float:
        return 0.55 - (0.20 * self.normalized_level)


@dataclass(frozen=True, slots=True)
class SpatialSettings:
    """User-facing horizontal position for binaural HRTF processing."""

    enabled: bool = False
    angle_degrees: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("Estado do áudio espacial deve ser verdadeiro ou falso")
        if isinstance(self.angle_degrees, bool) or not isinstance(
            self.angle_degrees, int
        ):
            raise TypeError("Posição espacial deve ser um número inteiro")
        if not -180 <= self.angle_degrees <= 180:
            raise ValueError("Posição espacial deve estar entre -180 e 180 graus")
