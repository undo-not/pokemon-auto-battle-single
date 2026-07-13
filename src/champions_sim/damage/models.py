"""Value objects for the deliberately small SIM-01 damage contract.

The contract accepts resolved battle facts.  It does not look up a species,
move, item, ability, weather, or field state.  A caller that knows such a fact
can affect damage must either resolve it into the supported fields or name it
in ``unsupported_effects`` so calculation fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction


class UnsupportedDamageMechanic(ValueError):
    """Raised instead of silently approximating an unsupported mechanic."""

    def __init__(self, mechanics: str | tuple[str, ...]) -> None:
        if isinstance(mechanics, str):
            mechanics = (mechanics,)
        normalized = tuple(str(mechanic).strip() for mechanic in mechanics if str(mechanic).strip())
        if not normalized:
            normalized = ("unspecified_damage_mechanic",)
        self.mechanics = normalized
        super().__init__("unsupported damage mechanic(s): " + ", ".join(normalized))


class DamageCategory(str, Enum):
    PHYSICAL = "physical"
    SPECIAL = "special"


@dataclass(frozen=True)
class DamageStats:
    """Resolved combat stats before battle rank modifiers."""

    attack: int
    defense: int
    special_attack: int
    special_defense: int

    def offensive(self, category: DamageCategory) -> int:
        return self.attack if category is DamageCategory.PHYSICAL else self.special_attack

    def defensive(self, category: DamageCategory) -> int:
        return self.defense if category is DamageCategory.PHYSICAL else self.special_defense


@dataclass(frozen=True)
class DamageInput:
    """All inputs that SIM-01 is allowed to use for one ordinary damage hit.

    ``critical`` describes the resolved outcome of this hit; critical-hit odds
    are outside the damage calculator.  ``type_effectiveness`` is already the
    product against all defender types and must use :class:`fractions.Fraction`
    to keep the calculation exact and reproducible.
    """

    level: int
    power: int | None
    category: DamageCategory | str
    attacker: DamageStats
    defender: DamageStats
    attack_rank: int = 0
    defense_rank: int = 0
    stab: bool = False
    type_effectiveness: Fraction = Fraction(1, 1)
    critical: bool = False
    burn_physical_modifier: bool = False
    defender_hp: int | None = None
    unsupported_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnockOutInfo:
    """KO bounds when every hit uses this damage distribution.

    The bounds deliberately ignore healing, residual damage, multi-hit move
    rules, and state changes between attacks.
    """

    defender_hp: int
    best_case_hits: int | None
    worst_case_hits: int | None
    one_hit_ko_rolls: int
    one_hit_ko_probability: Fraction

    @property
    def possible_one_hit_ko(self) -> bool:
        return self.one_hit_ko_rolls > 0

    @property
    def guaranteed_one_hit_ko(self) -> bool:
        return self.one_hit_ko_rolls == 16


@dataclass(frozen=True)
class DamageResult:
    rolls: tuple[int, ...]
    min_damage: int
    max_damage: int
    effective_attack: int
    effective_defense: int
    ko: KnockOutInfo | None
