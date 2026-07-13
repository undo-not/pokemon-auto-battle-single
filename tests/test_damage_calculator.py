from __future__ import annotations

import sys
import unittest
from fractions import Fraction
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from champions_sim.damage import (  # noqa: E402
    DamageCategory,
    DamageInput,
    DamageStats,
    UnsupportedDamageMechanic,
    calculate_damage,
)


def stats(
    *,
    attack: int = 100,
    defense: int = 100,
    special_attack: int = 100,
    special_defense: int = 100,
) -> DamageStats:
    return DamageStats(
        attack=attack,
        defense=defense,
        special_attack=special_attack,
        special_defense=special_defense,
    )


class DamageCalculatorTest(unittest.TestCase):
    def test_reproduces_champions_a182_power100_vs_b189_example(self) -> None:
        result = calculate_damage(
            DamageInput(
                level=50,
                power=100,
                category=DamageCategory.PHYSICAL,
                attacker=stats(attack=182),
                defender=stats(defense=189),
                defender_hp=227,
            )
        )

        self.assertEqual(
            result.rolls,
            (37, 37, 38, 38, 39, 39, 40, 40, 40, 41, 41, 42, 42, 43, 43, 44),
        )
        self.assertEqual(result.min_damage, 37)
        self.assertEqual(result.max_damage, 44)
        self.assertIsNotNone(result.ko)
        assert result.ko is not None
        self.assertEqual(result.ko.best_case_hits, 6)
        self.assertEqual(result.ko.worst_case_hits, 7)
        self.assertEqual(result.ko.one_hit_ko_probability, Fraction(0, 1))

    def test_special_category_selects_special_stats(self) -> None:
        physical = calculate_damage(
            DamageInput(
                level=50,
                power=100,
                category="physical",
                attacker=stats(attack=200, special_attack=50),
                defender=stats(defense=100, special_defense=250),
            )
        )
        special = calculate_damage(
            DamageInput(
                level=50,
                power=100,
                category="special",
                attacker=stats(attack=200, special_attack=50),
                defender=stats(defense=100, special_defense=250),
            )
        )

        self.assertEqual(physical.effective_attack, 200)
        self.assertEqual(physical.effective_defense, 100)
        self.assertEqual(special.effective_attack, 50)
        self.assertEqual(special.effective_defense, 250)
        self.assertGreater(physical.max_damage, special.max_damage)

    def test_applies_ranks_stab_and_type_effectiveness(self) -> None:
        result = calculate_damage(
            DamageInput(
                level=50,
                power=100,
                category="physical",
                attacker=stats(attack=100),
                defender=stats(defense=100),
                attack_rank=1,
                stab=True,
                type_effectiveness=Fraction(2, 1),
            )
        )

        self.assertEqual(result.effective_attack, 150)
        self.assertEqual(
            result.rolls,
            (170, 174, 176, 176, 180, 182, 182, 186, 188, 188, 192, 194, 194, 198, 200, 204),
        )

    def test_critical_is_explicit_and_uses_rank_bypass(self) -> None:
        normal = calculate_damage(
            DamageInput(
                level=50,
                power=70,
                category="physical",
                attacker=stats(attack=120),
                defender=stats(defense=120),
                attack_rank=-2,
                defense_rank=2,
            )
        )
        critical = calculate_damage(
            DamageInput(
                level=50,
                power=70,
                category="physical",
                attacker=stats(attack=120),
                defender=stats(defense=120),
                attack_rank=-2,
                defense_rank=2,
                critical=True,
            )
        )

        self.assertEqual(normal.effective_attack, 60)
        self.assertEqual(normal.effective_defense, 240)
        self.assertEqual(critical.effective_attack, 120)
        self.assertEqual(critical.effective_defense, 120)
        self.assertGreater(critical.min_damage, normal.max_damage)

    def test_critical_modifier_has_an_exact_sixteen_roll_distribution(self) -> None:
        result = calculate_damage(
            DamageInput(
                level=50,
                power=70,
                category="physical",
                attacker=stats(),
                defender=stats(),
                critical=True,
            )
        )

        self.assertEqual(
            result.rolls,
            (40, 40, 40, 42, 42, 42, 43, 43, 43, 45, 45, 45, 46, 46, 46, 48),
        )

    def test_burn_is_a_final_physical_damage_modifier(self) -> None:
        normal = calculate_damage(
            DamageInput(
                level=50,
                power=70,
                category="physical",
                attacker=stats(),
                defender=stats(),
            )
        )
        burned = calculate_damage(
            DamageInput(
                level=50,
                power=70,
                category="physical",
                attacker=stats(),
                defender=stats(),
                burn_physical_modifier=True,
            )
        )

        self.assertEqual(normal.effective_attack, burned.effective_attack)
        self.assertEqual(
            burned.rolls,
            (13, 13, 13, 14, 14, 14, 14, 14, 14, 15, 15, 15, 15, 15, 15, 16),
        )

    def test_immunity_returns_sixteen_zero_rolls_and_no_ko_bound(self) -> None:
        result = calculate_damage(
            DamageInput(
                level=50,
                power=100,
                category="special",
                attacker=stats(special_attack=200),
                defender=stats(special_defense=50),
                type_effectiveness=Fraction(0, 1),
                defender_hp=1,
            )
        )

        self.assertEqual(result.rolls, (0,) * 16)
        assert result.ko is not None
        self.assertIsNone(result.ko.best_case_hits)
        self.assertIsNone(result.ko.worst_case_hits)
        self.assertFalse(result.ko.possible_one_hit_ko)

    def test_ko_information_counts_exact_one_hit_rolls(self) -> None:
        result = calculate_damage(
            DamageInput(
                level=50,
                power=100,
                category="physical",
                attacker=stats(attack=182),
                defender=stats(defense=189),
                defender_hp=40,
            )
        )

        assert result.ko is not None
        self.assertEqual(result.ko.one_hit_ko_rolls, 10)
        self.assertEqual(result.ko.one_hit_ko_probability, Fraction(5, 8))
        self.assertTrue(result.ko.possible_one_hit_ko)
        self.assertFalse(result.ko.guaranteed_one_hit_ko)

    def test_unknown_effects_fail_closed(self) -> None:
        with self.assertRaises(UnsupportedDamageMechanic) as raised:
            calculate_damage(
                DamageInput(
                    level=50,
                    power=100,
                    category="physical",
                    attacker=stats(),
                    defender=stats(),
                    unsupported_effects=("weather:rain", "item:life_orb"),
                )
            )

        self.assertEqual(raised.exception.mechanics, ("weather:rain", "item:life_orb"))

    def test_variable_power_and_status_categories_fail_closed(self) -> None:
        with self.assertRaisesRegex(UnsupportedDamageMechanic, "variable_or_missing_power"):
            calculate_damage(
                DamageInput(
                    level=50,
                    power=None,
                    category="physical",
                    attacker=stats(),
                    defender=stats(),
                )
            )
        with self.assertRaisesRegex(UnsupportedDamageMechanic, "damage_category:status"):
            calculate_damage(
                DamageInput(
                    level=50,
                    power=1,
                    category="status",
                    attacker=stats(),
                    defender=stats(),
                )
            )

    def test_non_fraction_type_effectiveness_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "fractions.Fraction"):
            calculate_damage(
                DamageInput(
                    level=50,
                    power=100,
                    category="physical",
                    attacker=stats(),
                    defender=stats(),
                    type_effectiveness=2.0,  # type: ignore[arg-type]
                )
            )


if __name__ == "__main__":
    unittest.main()
