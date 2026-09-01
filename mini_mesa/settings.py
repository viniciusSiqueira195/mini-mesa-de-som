from __future__ import annotations

import math
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
    """Three-dimensional voice position and optional automatic movement."""

    enabled: bool = False
    x: int = 0
    y: int = 0
    z: int = 100
    automatic: bool = False
    speed_percent: int = 35

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("Estado do áudio espacial deve ser verdadeiro ou falso")
        for axis, value in (("X", self.x), ("Y", self.y), ("Z", self.z)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Coordenada {axis} deve ser um número inteiro")
            if not -100 <= value <= 100:
                raise ValueError(f"Coordenada {axis} deve estar entre -100 e 100")
        if not isinstance(self.automatic, bool):
            raise TypeError("Movimento automático deve ser verdadeiro ou falso")
        if (
            isinstance(self.speed_percent, bool)
            or not isinstance(self.speed_percent, int)
        ):
            raise TypeError("Velocidade espacial deve ser um número inteiro")
        if not 1 <= self.speed_percent <= 100:
            raise ValueError("Velocidade espacial deve estar entre 1 e 100")

    @property
    def azimuth_degrees(self) -> int:
        """Horizontal angle: negative left, zero front, positive right."""

        if self.x == 0 and self.z == 0:
            return 0
        return round(math.degrees(math.atan2(self.x, self.z)))

    @property
    def elevation_degrees(self) -> int:
        """Vertical angle: negative below and positive above."""

        horizontal_distance = math.hypot(self.x, self.z)
        if self.y == 0 and horizontal_distance == 0:
            return 0
        return round(math.degrees(math.atan2(self.y, horizontal_distance)))
