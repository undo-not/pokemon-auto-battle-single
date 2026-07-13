"""Deterministic, fail-closed damage calculation for the simulator core."""

from .calculator import calculate_damage
from .models import (
    DamageCategory,
    DamageInput,
    DamageResult,
    DamageStats,
    KnockOutInfo,
    UnsupportedDamageMechanic,
)

__all__ = [
    "DamageCategory",
    "DamageInput",
    "DamageResult",
    "DamageStats",
    "KnockOutInfo",
    "UnsupportedDamageMechanic",
    "calculate_damage",
]
