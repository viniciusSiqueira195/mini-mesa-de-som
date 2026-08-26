from __future__ import annotations

from dataclasses import dataclass


def _validate_percent(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} deve ser um número inteiro")
    if not 0 <= value <= 100:
        raise ValueError(f"{name} deve estar entre 0 e 100")


@dataclass(frozen=True, slots=True)
class ReverbSettings:
    """Valores apresentados ao usuário, sempre expressos em porcentagem."""

    amount_percent: int = 25
    room_size_percent: int = 40
    damping_percent: int = 50

    def __post_init__(self) -> None:
        _validate_percent("Quantidade de reverb", self.amount_percent)
        _validate_percent("Tamanho da sala", self.room_size_percent)
        _validate_percent("Amortecimento", self.damping_percent)

    @property
    def wet_level(self) -> float:
        return self.amount_percent / 100.0

    @property
    def room_size(self) -> float:
        return self.room_size_percent / 100.0

    @property
    def damping(self) -> float:
        return self.damping_percent / 100.0
