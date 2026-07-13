from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from champions_sim.damage.calculator import apply_battle_rank, calculate_base_damage  # noqa: E402
from champions_sim.damage.rounding import (  # noqa: E402
    apply_fixed_point_modifier,
    apply_floor_modifier,
    ceil_ratio,
    floor_ratio,
    round_half_down_ratio,
)


class DamageRoundingTest(unittest.TestCase):
    def test_floor_ratio_names_each_integer_floor(self) -> None:
        self.assertEqual(floor_ratio(9, 2), 4)
        self.assertEqual(apply_floor_modifier(37, 85, 100), 31)

    def test_ceil_ratio_avoids_float_rounding(self) -> None:
        self.assertEqual(ceil_ratio(227, 44), 6)
        self.assertEqual(ceil_ratio(44, 44), 1)

    def test_round_half_down_breaks_exact_ties_downward(self) -> None:
        self.assertEqual(round_half_down_ratio(5, 10), 0)
        self.assertEqual(round_half_down_ratio(6, 10), 1)
        self.assertEqual(round_half_down_ratio(15, 10), 1)
        self.assertEqual(round_half_down_ratio(16, 10), 2)

    def test_fixed_point_modifier_uses_4096_denominator(self) -> None:
        self.assertEqual(apply_fixed_point_modifier(100, 6144), 150)
        self.assertEqual(apply_fixed_point_modifier(100, 2048), 50)

    def test_rank_rounding_uses_integer_floor(self) -> None:
        self.assertEqual(apply_battle_rank(101, 1), 151)
        self.assertEqual(apply_battle_rank(101, -1), 67)
        self.assertEqual(apply_battle_rank(101, 6), 404)
        self.assertEqual(apply_battle_rank(101, -6), 25)

    def test_base_damage_exposes_formula_rounding(self) -> None:
        self.assertEqual(calculate_base_damage(level=50, power=100, attack=182, defense=189), 44)


if __name__ == "__main__":
    unittest.main()
