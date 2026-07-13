"""Clean-room ordinary damage implementation for SIM-01.

No source text was copied from the legacy ``champions`` project.  The root of
that repository had no LICENSE file at the audited revision; only observable
compatibility examples and the documented arithmetic contract were retained.
See ``PROVENANCE.md`` beside this module.
"""

from __future__ import annotations

from fractions import Fraction

from .models import (
    DamageCategory,
    DamageInput,
    DamageResult,
    DamageStats,
    KnockOutInfo,
    UnsupportedDamageMechanic,
)
from .rounding import apply_fixed_point_modifier, apply_floor_modifier, ceil_ratio, floor_ratio


RANDOM_PERCENT_ROLLS = tuple(range(85, 101))
STAB_MODIFIER = 6144
CRITICAL_MODIFIER = 6144
BURN_PHYSICAL_MODIFIER = 2048
_SUPPORTED_TYPE_EFFECTIVENESS = frozenset(
    {
        Fraction(0, 1),
        Fraction(1, 4),
        Fraction(1, 2),
        Fraction(1, 1),
        Fraction(2, 1),
        Fraction(4, 1),
    }
)


def calculate_damage(request: DamageInput) -> DamageResult:
    """Calculate the sixteen ordinary damage rolls for one resolved hit.

    Modifier order intentionally stays explicit: ranks, base formula, random
    percentage, STAB, type effectiveness, then the resolved critical modifier.
    Critical hits also ignore a negative attacking rank and a positive
    defending rank.
    """

    category = _validated_category(request.category)
    _validate_request(request)

    attack_rank = _critical_attack_rank(request.attack_rank, request.critical)
    defense_rank = _critical_defense_rank(request.defense_rank, request.critical)
    attack = apply_battle_rank(request.attacker.offensive(category), attack_rank)
    defense = apply_battle_rank(request.defender.defensive(category), defense_rank)
    base = calculate_base_damage(
        level=request.level,
        power=_fixed_power(request.power),
        attack=attack,
        defense=defense,
    )

    rolls = tuple(
        _calculate_roll(
            base,
            random_percent=random_percent,
            stab=request.stab,
            type_effectiveness=request.type_effectiveness,
            critical=request.critical,
            burn_physical_modifier=request.burn_physical_modifier,
        )
        for random_percent in RANDOM_PERCENT_ROLLS
    )
    ko = None if request.defender_hp is None else summarize_ko(request.defender_hp, rolls)
    return DamageResult(
        rolls=rolls,
        min_damage=min(rolls),
        max_damage=max(rolls),
        effective_attack=attack,
        effective_defense=defense,
        ko=ko,
    )


def apply_battle_rank(stat: int, rank: int) -> int:
    """Apply a -6..+6 battle rank to one positive combat stat, rounding down."""

    _require_positive_int("stat", stat)
    if not isinstance(rank, int) or isinstance(rank, bool) or not -6 <= rank <= 6:
        raise ValueError("rank must be an integer between -6 and 6")
    if rank >= 0:
        return apply_floor_modifier(stat, rank + 2, 2)
    return apply_floor_modifier(stat, 2, 2 - rank)


def calculate_base_damage(*, level: int, power: int, attack: int, defense: int) -> int:
    """Apply every floor in the ordinary level/power/attack/defense formula."""

    _require_positive_int("level", level)
    _require_positive_int("power", power)
    _require_positive_int("attack", attack)
    _require_positive_int("defense", defense)

    level_term = floor_ratio(2 * level, 5) + 2
    scaled_by_defense = floor_ratio(level_term * power * attack, defense)
    return floor_ratio(scaled_by_defense, 50) + 2


def summarize_ko(defender_hp: int, rolls: tuple[int, ...]) -> KnockOutInfo:
    """Return simple repeated-hit KO bounds and the exact one-hit roll count."""

    _require_positive_int("defender_hp", defender_hp)
    if len(rolls) != 16:
        raise ValueError("ordinary damage must contain exactly sixteen rolls")
    if any(not isinstance(damage, int) or isinstance(damage, bool) or damage < 0 for damage in rolls):
        raise ValueError("rolls must contain non-negative integers")

    maximum = max(rolls)
    minimum = min(rolls)
    one_hit_rolls = sum(damage >= defender_hp for damage in rolls)
    return KnockOutInfo(
        defender_hp=defender_hp,
        best_case_hits=None if maximum == 0 else ceil_ratio(defender_hp, maximum),
        worst_case_hits=None if minimum == 0 else ceil_ratio(defender_hp, minimum),
        one_hit_ko_rolls=one_hit_rolls,
        one_hit_ko_probability=Fraction(one_hit_rolls, len(rolls)),
    )


def _calculate_roll(
    base: int,
    *,
    random_percent: int,
    stab: bool,
    type_effectiveness: Fraction,
    critical: bool,
    burn_physical_modifier: bool,
) -> int:
    damage = apply_floor_modifier(base, random_percent, 100)
    if stab:
        damage = apply_fixed_point_modifier(damage, STAB_MODIFIER)

    damage = apply_floor_modifier(
        damage,
        type_effectiveness.numerator,
        type_effectiveness.denominator,
    )
    if type_effectiveness > 0:
        damage = max(1, damage)
    # Champions references place burn at the final-damage stage rather than
    # mutating the attack stat. This preserves the modifier rounding boundary.
    if burn_physical_modifier:
        damage = apply_fixed_point_modifier(damage, BURN_PHYSICAL_MODIFIER)
    if critical:
        damage = apply_fixed_point_modifier(damage, CRITICAL_MODIFIER)
    return damage


def _validate_request(request: DamageInput) -> None:
    if request.unsupported_effects:
        raise UnsupportedDamageMechanic(request.unsupported_effects)
    _require_positive_int("level", request.level)
    _validate_stats("attacker", request.attacker)
    _validate_stats("defender", request.defender)
    _validate_rank("attack_rank", request.attack_rank)
    _validate_rank("defense_rank", request.defense_rank)
    if not isinstance(request.stab, bool):
        raise TypeError("stab must be bool")
    if not isinstance(request.critical, bool):
        raise TypeError("critical must be bool")
    if not isinstance(request.burn_physical_modifier, bool):
        raise TypeError("burn_physical_modifier must be bool")
    if not isinstance(request.type_effectiveness, Fraction):
        raise TypeError("type_effectiveness must be fractions.Fraction")
    if request.type_effectiveness not in _SUPPORTED_TYPE_EFFECTIVENESS:
        raise UnsupportedDamageMechanic(
            f"type_effectiveness:{request.type_effectiveness.numerator}/{request.type_effectiveness.denominator}"
        )
    if request.defender_hp is not None:
        _require_positive_int("defender_hp", request.defender_hp)


def _validate_stats(label: str, stats: DamageStats) -> None:
    if not isinstance(stats, DamageStats):
        raise TypeError(f"{label} must be DamageStats")
    for field_name in ("attack", "defense", "special_attack", "special_defense"):
        _require_positive_int(f"{label}.{field_name}", getattr(stats, field_name))


def _validate_rank(label: str, rank: int) -> None:
    if not isinstance(rank, int) or isinstance(rank, bool) or not -6 <= rank <= 6:
        raise ValueError(f"{label} must be an integer between -6 and 6")


def _validated_category(category: DamageCategory | str) -> DamageCategory:
    try:
        return DamageCategory(category)
    except (TypeError, ValueError) as error:
        raise UnsupportedDamageMechanic(f"damage_category:{category}") from error


def _fixed_power(power: int | None) -> int:
    if power is None:
        raise UnsupportedDamageMechanic("variable_or_missing_power")
    _require_positive_int("power", power)
    return power


def _critical_attack_rank(rank: int, critical: bool) -> int:
    return max(0, rank) if critical else rank


def _critical_defense_rank(rank: int, critical: bool) -> int:
    return min(0, rank) if critical else rank


def _require_positive_int(label: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
