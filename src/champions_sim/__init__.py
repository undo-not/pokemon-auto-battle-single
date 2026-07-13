"""Deterministic Pokémon Champions singles simulation foundation."""

from .catalog import (
    BaseStatBlock,
    CatalogSnapshot,
    MegaEvolutionDefinition,
    RuleSetSnapshot,
    SnapshotValidationError,
    load_catalog,
    load_ruleset,
    validate_snapshot_pair,
)
from .engine import BattleEngine, IllegalAction
from .fixtures import LoadedBattleFixture, load_battle_fixture
from .runner import (
    BatchSummary,
    BattleRun,
    ReplayVerificationError,
    run_battle,
    run_random_batch,
    verify_replay,
)

__all__ = [
    "BatchSummary",
    "BaseStatBlock",
    "BattleEngine",
    "BattleRun",
    "CatalogSnapshot",
    "IllegalAction",
    "LoadedBattleFixture",
    "MegaEvolutionDefinition",
    "RuleSetSnapshot",
    "ReplayVerificationError",
    "SnapshotValidationError",
    "load_battle_fixture",
    "load_catalog",
    "load_ruleset",
    "run_battle",
    "run_random_batch",
    "verify_replay",
    "validate_snapshot_pair",
]
