"""Named integer-rounding operations used by the damage pipeline."""

from __future__ import annotations


FIXED_POINT_DENOMINATOR = 4096


def floor_ratio(numerator: int, denominator: int) -> int:
    """Return floor(numerator / denominator) for non-negative damage values."""

    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return numerator // denominator


def ceil_ratio(numerator: int, denominator: int) -> int:
    """Return ceil(numerator / denominator) without converting to float."""

    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (numerator + denominator - 1) // denominator


def round_half_down_ratio(numerator: int, denominator: int) -> int:
    """Round a non-negative ratio to nearest, resolving exact halves downward."""

    quotient = floor_ratio(numerator, denominator)
    remainder = numerator % denominator
    return quotient + int(remainder * 2 > denominator)


def apply_fixed_point_modifier(
    value: int,
    modifier: int,
    denominator: int = FIXED_POINT_DENOMINATOR,
) -> int:
    """Apply a 4096-based modifier using the game's half-down rounding rule."""

    if value < 0:
        raise ValueError("value must be non-negative")
    if modifier < 0:
        raise ValueError("modifier must be non-negative")
    return round_half_down_ratio(value * modifier, denominator)


def apply_floor_modifier(value: int, numerator: int, denominator: int) -> int:
    """Apply a rational modifier and round down."""

    if value < 0 or numerator < 0:
        raise ValueError("value and numerator must be non-negative")
    return floor_ratio(value * numerator, denominator)
