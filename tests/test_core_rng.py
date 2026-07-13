import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from champions_sim.core import ExplicitRNG  # noqa: E402


def _draws(seed: int, count: int) -> tuple[list[int], ExplicitRNG]:
    rng = ExplicitRNG.seeded(seed)
    values: list[int] = []
    for _ in range(count):
        value, rng = rng.next_u64()
        values.append(value)
    return values, rng


def test_same_seed_reproduces_values_state_and_cursor() -> None:
    values_a, final_a = _draws(123456789, 20)
    values_b, final_b = _draws(123456789, 20)

    assert values_a == values_b
    assert final_a == final_b
    assert final_a.cursor == 20


def test_rng_calls_do_not_mutate_or_cross_contaminate_branches() -> None:
    root = ExplicitRNG.seeded(42)
    first_a, branch_a = root.randbelow(1000)
    first_b, branch_b = root.randbelow(1000)

    assert first_a == first_b
    assert branch_a == branch_b
    assert root.cursor == 0

    child_a = root.branch("damage-roll")
    child_b = root.branch("damage-roll")
    child_c = root.branch("speed-tie")
    assert child_a == child_b
    assert child_a != child_c
    assert root.cursor == 0


def test_chance_records_the_consumed_rng_state() -> None:
    root = ExplicitRNG.seeded(7)
    outcome, next_rng = root.chance(1, 3)

    assert isinstance(outcome, bool)
    assert next_rng.cursor >= 1
    assert root.cursor == 0
