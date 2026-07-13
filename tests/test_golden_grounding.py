from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from champions_sim.damage import DamageInput, DamageStats, calculate_damage


ROOT = Path(__file__).resolve().parents[1]


def test_published_champions_damage_reference_is_reproduced() -> None:
    payload = json.loads(
        (ROOT / "data/golden/sim01_damage_reference.json").read_text(encoding="utf-8")
    )
    request = payload["input"]

    result = calculate_damage(
        DamageInput(
            level=request["level"],
            power=request["power"],
            category=request["category"],
            attacker=DamageStats(
                attack=request["attack"],
                defense=1,
                special_attack=1,
                special_defense=1,
            ),
            defender=DamageStats(
                attack=1,
                defense=request["defense"],
                special_attack=1,
                special_defense=1,
            ),
            stab=request["stab"],
            type_effectiveness=Fraction(
                request["type_effectiveness_numerator"],
                request["type_effectiveness_denominator"],
            ),
            critical=request["critical"],
        )
    )

    assert result.rolls == tuple(payload["expected_rolls"])
    assert payload["evidence_status"] == "published_champions_reference_not_device_capture"
