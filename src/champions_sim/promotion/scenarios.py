"""Evidence-bound SIM-02B scenario partitions and engine probe results.

This module deliberately owns only executable scenario, partition, and probe
contracts.  Source/license resolution and readiness scope remain the
responsibility of the promotion compiler and readiness resolver.

Replay bodies are never embedded in these small manifests.  Callers retain the
exact :class:`~champions_sim.core.ReplayRecord` artifact and pass it back to
``verify_engine_probe_v2`` or ``build_engine_probe_report_v2``.  A positive
probe is issued only after the existing production ``verify_replay`` path has
re-executed every recorded transition against the supplied ``BattleEngine``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping

from champions_sim.capabilities.models import (
    TargetCapability,
    TargetCapabilitySet,
)
from champions_sim.core import (
    BattleEventKind,
    RNG_ALGORITHM_ID,
    ReplayRecord,
    canonical_hash,
    canonical_json,
)
from champions_sim.engine import BattleEngine
from champions_sim.runner import verify_replay


SCENARIO_SCHEMA_VERSION = "2.0.0"
PARTITION_SCHEMA_VERSION = "2.0.0"
ENGINE_PROBE_SCHEMA_VERSION = "2.0.0"

_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UINT64_MAX = (1 << 64) - 1
_PARTITION_ROLES = frozenset({"development", "external_holdout"})
_PROBE_ROLES = frozenset({"primary", "supplemental"})
_VERIFIED_PROBE_TOKEN = object()


class PromotionScenarioError(ValueError):
    """A scenario, partition, Replay, or probe violates its sealed contract."""


def _stable(value: str, label: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise PromotionScenarioError(f"{label} must be a stable ID")


def _sha256(value: str, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PromotionScenarioError(f"{label} must be a lowercase SHA-256")


def _sorted_unique_nonempty(values: tuple[str, ...], label: str) -> None:
    if type(values) is not tuple or not values:
        raise PromotionScenarioError(f"{label} must be a non-empty tuple")
    for value in values:
        _stable(value, label)
    if len(values) != len(set(values)):
        raise PromotionScenarioError(f"{label} must be unique")
    if values != tuple(sorted(values)):
        raise PromotionScenarioError(f"{label} must be sorted")


def _sorted_unique_hashes(values: tuple[str, ...], label: str) -> None:
    if type(values) is not tuple or not values:
        raise PromotionScenarioError(f"{label} must be a non-empty tuple")
    for value in values:
        _sha256(value, label)
    if len(values) != len(set(values)):
        raise PromotionScenarioError(f"{label} must be unique")
    if values != tuple(sorted(values)):
        raise PromotionScenarioError(f"{label} must be sorted")


def _exact_uint(value: int, label: str, *, maximum: int | None = None) -> None:
    if type(value) is not int or value < 0:
        raise PromotionScenarioError(f"{label} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise PromotionScenarioError(f"{label} is above its maximum")


@dataclass(frozen=True, slots=True)
class EngineScenarioV2:
    """One content-addressed engine execution and its capability witness.

    ``scenario_hash`` intentionally excludes the scenario ID, partition role,
    and lineage labels.  Relabelling identical executable content as a holdout
    therefore cannot hide development/holdout overlap.
    """

    scenario_id: str
    partition_role: str
    capability_id: str
    target_capability_set_hash: str
    initial_state_hash: str
    choice_sequence_hash: str
    seed: int
    rng_algorithm_id: str
    catalog_hash: str
    ruleset_hash: str
    replay_hash: str
    witness_step_index: int
    witness_event_index: int
    witness_event_kind: str
    witness_event_hash: str
    source_lineage_ids: tuple[str, ...]
    collection_lineage_ids: tuple[str, ...]
    authoring_lineage_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.scenario_id, "scenario_id")
        if self.partition_role not in _PARTITION_ROLES:
            raise PromotionScenarioError("unsupported scenario partition_role")
        _stable(self.capability_id, "capability_id")
        for value, label in (
            (self.target_capability_set_hash, "target_capability_set_hash"),
            (self.initial_state_hash, "initial_state_hash"),
            (self.choice_sequence_hash, "choice_sequence_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
            (self.replay_hash, "replay_hash"),
            (self.witness_event_hash, "witness_event_hash"),
        ):
            _sha256(value, label)
        _exact_uint(self.seed, "seed", maximum=_UINT64_MAX)
        if self.rng_algorithm_id != RNG_ALGORITHM_ID:
            raise PromotionScenarioError("unsupported scenario RNG algorithm")
        _exact_uint(self.witness_step_index, "witness_step_index")
        _exact_uint(self.witness_event_index, "witness_event_index")
        _stable(self.witness_event_kind, "witness_event_kind")
        _sorted_unique_nonempty(self.source_lineage_ids, "source_lineage_ids")
        _sorted_unique_nonempty(
            self.collection_lineage_ids, "collection_lineage_ids"
        )
        _sorted_unique_nonempty(self.authoring_lineage_ids, "authoring_lineage_ids")

    def _content_data(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "target_capability_set_hash": self.target_capability_set_hash,
            "initial_state_hash": self.initial_state_hash,
            "choice_sequence_hash": self.choice_sequence_hash,
            "seed": self.seed,
            "rng_algorithm_id": self.rng_algorithm_id,
            "catalog_hash": self.catalog_hash,
            "ruleset_hash": self.ruleset_hash,
            "replay_hash": self.replay_hash,
            "witness_step_index": self.witness_step_index,
            "witness_event_index": self.witness_event_index,
            "witness_event_kind": self.witness_event_kind,
            "witness_event_hash": self.witness_event_hash,
        }

    @property
    def scenario_hash(self) -> str:
        return canonical_hash(self._content_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "partition_role": self.partition_role,
            **self._content_data(),
            "source_lineage_ids": list(self.source_lineage_ids),
            "collection_lineage_ids": list(self.collection_lineage_ids),
            "authoring_lineage_ids": list(self.authoring_lineage_ids),
            "scenario_hash": self.scenario_hash,
        }


@dataclass(frozen=True, slots=True)
class EngineScenarioCorpusV2:
    """A non-empty, exact-role collection of executable scenarios."""

    schema_version: str
    corpus_id: str
    corpus_role: str
    target_capability_set_hash: str
    catalog_hash: str
    ruleset_hash: str
    scenarios: tuple[EngineScenarioV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCENARIO_SCHEMA_VERSION:
            raise PromotionScenarioError("unsupported scenario corpus schema_version")
        _stable(self.corpus_id, "corpus_id")
        if self.corpus_role not in _PARTITION_ROLES:
            raise PromotionScenarioError("unsupported corpus_role")
        for value, label in (
            (self.target_capability_set_hash, "target_capability_set_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
        ):
            _sha256(value, label)
        if type(self.scenarios) is not tuple or not self.scenarios:
            raise PromotionScenarioError("scenario corpus cannot be empty")
        if any(type(value) is not EngineScenarioV2 for value in self.scenarios):
            raise PromotionScenarioError("scenario corpus requires exact EngineScenarioV2")
        for scenario in self.scenarios:
            scenario.__post_init__()
            if scenario.partition_role != self.corpus_role:
                raise PromotionScenarioError("scenario role differs from corpus role")
            if scenario.target_capability_set_hash != self.target_capability_set_hash:
                raise PromotionScenarioError("scenario capability-set hash mismatch")
            if scenario.catalog_hash != self.catalog_hash:
                raise PromotionScenarioError("scenario Catalog hash mismatch")
            if scenario.ruleset_hash != self.ruleset_hash:
                raise PromotionScenarioError("scenario RuleSet hash mismatch")
        if self.scenarios != tuple(sorted(self.scenarios, key=lambda item: item.scenario_id)):
            raise PromotionScenarioError("scenario corpus must be sorted by scenario_id")
        ids = tuple(value.scenario_id for value in self.scenarios)
        hashes = tuple(value.scenario_hash for value in self.scenarios)
        if len(ids) != len(set(ids)):
            raise PromotionScenarioError("scenario IDs must be unique")
        if len(hashes) != len(set(hashes)):
            raise PromotionScenarioError("scenario content hashes must be unique")

    @property
    def corpus_hash(self) -> str:
        return canonical_hash(self._unsigned_data())

    def _unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "corpus_role": self.corpus_role,
            "target_capability_set_hash": self.target_capability_set_hash,
            "catalog_hash": self.catalog_hash,
            "ruleset_hash": self.ruleset_hash,
            "scenarios": [value.to_data() for value in self.scenarios],
        }

    def to_data(self) -> dict[str, Any]:
        return {**self._unsigned_data(), "corpus_hash": self.corpus_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


def build_engine_scenario_corpus_v2(
    *,
    corpus_id: str,
    corpus_role: str,
    target_capability_set_hash: str,
    catalog_hash: str,
    ruleset_hash: str,
    scenarios: Iterable[EngineScenarioV2],
) -> EngineScenarioCorpusV2:
    """Canonicalize caller ordering while preserving exact scenario substance."""

    values = tuple(scenarios)
    if any(type(value) is not EngineScenarioV2 for value in values):
        raise PromotionScenarioError("scenario corpus requires exact EngineScenarioV2")
    return EngineScenarioCorpusV2(
        schema_version=SCENARIO_SCHEMA_VERSION,
        corpus_id=corpus_id,
        corpus_role=corpus_role,
        target_capability_set_hash=target_capability_set_hash,
        catalog_hash=catalog_hash,
        ruleset_hash=ruleset_hash,
        scenarios=tuple(sorted(values, key=lambda item: item.scenario_id)),
    )


@dataclass(frozen=True, slots=True)
class ScenarioPartitionManifestV2:
    """Derived proof that development and external holdout lineages are disjoint."""

    schema_version: str
    manifest_id: str
    target_capability_set_hash: str
    catalog_hash: str
    ruleset_hash: str
    development_corpus_id: str
    development_corpus_hash: str
    external_holdout_corpus_id: str
    external_holdout_corpus_hash: str
    development_scenario_hashes: tuple[str, ...]
    external_holdout_scenario_hashes: tuple[str, ...]
    development_replay_hashes: tuple[str, ...]
    external_holdout_replay_hashes: tuple[str, ...]
    development_source_lineage_ids: tuple[str, ...]
    external_holdout_source_lineage_ids: tuple[str, ...]
    development_collection_lineage_ids: tuple[str, ...]
    external_holdout_collection_lineage_ids: tuple[str, ...]
    development_authoring_lineage_ids: tuple[str, ...]
    external_holdout_authoring_lineage_ids: tuple[str, ...]
    scenario_hash_overlap: tuple[str, ...]
    replay_hash_overlap: tuple[str, ...]
    source_lineage_overlap: tuple[str, ...]
    collection_lineage_overlap: tuple[str, ...]
    authoring_lineage_overlap: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PARTITION_SCHEMA_VERSION:
            raise PromotionScenarioError("unsupported partition schema_version")
        _stable(self.manifest_id, "partition manifest_id")
        _stable(self.development_corpus_id, "development_corpus_id")
        _stable(self.external_holdout_corpus_id, "external_holdout_corpus_id")
        for value, label in (
            (self.target_capability_set_hash, "target_capability_set_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
            (self.development_corpus_hash, "development_corpus_hash"),
            (self.external_holdout_corpus_hash, "external_holdout_corpus_hash"),
        ):
            _sha256(value, label)
        for values, label in (
            (self.development_scenario_hashes, "development_scenario_hashes"),
            (self.external_holdout_scenario_hashes, "external_holdout_scenario_hashes"),
            (self.development_replay_hashes, "development_replay_hashes"),
            (self.external_holdout_replay_hashes, "external_holdout_replay_hashes"),
        ):
            _sorted_unique_hashes(values, label)
        for values, label in (
            (self.development_source_lineage_ids, "development_source_lineage_ids"),
            (self.external_holdout_source_lineage_ids, "external_holdout_source_lineage_ids"),
            (self.development_collection_lineage_ids, "development_collection_lineage_ids"),
            (self.external_holdout_collection_lineage_ids, "external_holdout_collection_lineage_ids"),
            (self.development_authoring_lineage_ids, "development_authoring_lineage_ids"),
            (self.external_holdout_authoring_lineage_ids, "external_holdout_authoring_lineage_ids"),
        ):
            _sorted_unique_nonempty(values, label)
        overlaps = (
            self.scenario_hash_overlap,
            self.replay_hash_overlap,
            self.source_lineage_overlap,
            self.collection_lineage_overlap,
            self.authoring_lineage_overlap,
        )
        if any(type(value) is not tuple for value in overlaps):
            raise PromotionScenarioError("partition overlap fields must be tuples")
        if any(overlaps):
            raise PromotionScenarioError("development and holdout partitions overlap")
        expected_id = _partition_manifest_id(
            self.target_capability_set_hash,
            self.development_corpus_hash,
            self.external_holdout_corpus_hash,
        )
        if self.manifest_id != expected_id:
            raise PromotionScenarioError("partition manifest ID is not canonical")

    @property
    def partition_hash(self) -> str:
        return canonical_hash(self._unsigned_data())

    def _unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "target_capability_set_hash": self.target_capability_set_hash,
            "catalog_hash": self.catalog_hash,
            "ruleset_hash": self.ruleset_hash,
            "development_corpus_id": self.development_corpus_id,
            "development_corpus_hash": self.development_corpus_hash,
            "external_holdout_corpus_id": self.external_holdout_corpus_id,
            "external_holdout_corpus_hash": self.external_holdout_corpus_hash,
            "development_scenario_hashes": list(self.development_scenario_hashes),
            "external_holdout_scenario_hashes": list(self.external_holdout_scenario_hashes),
            "development_replay_hashes": list(self.development_replay_hashes),
            "external_holdout_replay_hashes": list(self.external_holdout_replay_hashes),
            "development_source_lineage_ids": list(self.development_source_lineage_ids),
            "external_holdout_source_lineage_ids": list(self.external_holdout_source_lineage_ids),
            "development_collection_lineage_ids": list(self.development_collection_lineage_ids),
            "external_holdout_collection_lineage_ids": list(self.external_holdout_collection_lineage_ids),
            "development_authoring_lineage_ids": list(self.development_authoring_lineage_ids),
            "external_holdout_authoring_lineage_ids": list(self.external_holdout_authoring_lineage_ids),
            "scenario_hash_overlap": list(self.scenario_hash_overlap),
            "replay_hash_overlap": list(self.replay_hash_overlap),
            "source_lineage_overlap": list(self.source_lineage_overlap),
            "collection_lineage_overlap": list(self.collection_lineage_overlap),
            "authoring_lineage_overlap": list(self.authoring_lineage_overlap),
        }

    def to_data(self) -> dict[str, Any]:
        return {**self._unsigned_data(), "partition_hash": self.partition_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())

    def validate_against(
        self,
        development: EngineScenarioCorpusV2,
        external_holdout: EngineScenarioCorpusV2,
    ) -> None:
        resolved = build_scenario_partition_manifest_v2(
            development=development,
            external_holdout=external_holdout,
        )
        if self.to_data() != resolved.to_data():
            raise PromotionScenarioError(
                "partition manifest differs from recomputed corpus substance"
            )


def _partition_manifest_id(
    target_capability_set_hash: str,
    development_corpus_hash: str,
    external_holdout_corpus_hash: str,
) -> str:
    return "scenario-partition-" + canonical_hash(
        (
            target_capability_set_hash,
            development_corpus_hash,
            external_holdout_corpus_hash,
        )
    )


def _lineage_ids(
    corpus: EngineScenarioCorpusV2,
    attribute: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for scenario in corpus.scenarios
                for value in getattr(scenario, attribute)
            }
        )
    )


def build_scenario_partition_manifest_v2(
    *,
    development: EngineScenarioCorpusV2,
    external_holdout: EngineScenarioCorpusV2,
) -> ScenarioPartitionManifestV2:
    """Derive a clean partition manifest or fail closed on any lineage leak."""

    if type(development) is not EngineScenarioCorpusV2 or type(
        external_holdout
    ) is not EngineScenarioCorpusV2:
        raise PromotionScenarioError("partition builder requires exact scenario corpora")
    development.__post_init__()
    external_holdout.__post_init__()
    if development.corpus_role != "development":
        raise PromotionScenarioError("development corpus has the wrong role")
    if external_holdout.corpus_role != "external_holdout":
        raise PromotionScenarioError("external holdout corpus has the wrong role")
    for label, first, second in (
        (
            "target capability set",
            development.target_capability_set_hash,
            external_holdout.target_capability_set_hash,
        ),
        ("Catalog", development.catalog_hash, external_holdout.catalog_hash),
        ("RuleSet", development.ruleset_hash, external_holdout.ruleset_hash),
    ):
        if first != second:
            raise PromotionScenarioError(f"partition {label} hash mismatch")

    development_scenario_hashes = tuple(
        sorted(value.scenario_hash for value in development.scenarios)
    )
    holdout_scenario_hashes = tuple(
        sorted(value.scenario_hash for value in external_holdout.scenarios)
    )
    development_replay_hashes = tuple(
        sorted({value.replay_hash for value in development.scenarios})
    )
    holdout_replay_hashes = tuple(
        sorted({value.replay_hash for value in external_holdout.scenarios})
    )
    development_source = _lineage_ids(development, "source_lineage_ids")
    holdout_source = _lineage_ids(external_holdout, "source_lineage_ids")
    development_collection = _lineage_ids(
        development, "collection_lineage_ids"
    )
    holdout_collection = _lineage_ids(
        external_holdout, "collection_lineage_ids"
    )
    development_authoring = _lineage_ids(development, "authoring_lineage_ids")
    holdout_authoring = _lineage_ids(
        external_holdout, "authoring_lineage_ids"
    )

    scenario_overlap = tuple(
        sorted(set(development_scenario_hashes) & set(holdout_scenario_hashes))
    )
    replay_overlap = tuple(
        sorted(set(development_replay_hashes) & set(holdout_replay_hashes))
    )
    source_overlap = tuple(sorted(set(development_source) & set(holdout_source)))
    collection_overlap = tuple(
        sorted(set(development_collection) & set(holdout_collection))
    )
    authoring_overlap = tuple(
        sorted(set(development_authoring) & set(holdout_authoring))
    )
    overlap_labels = tuple(
        label
        for values, label in (
            (scenario_overlap, "scenario_hash_overlap"),
            (replay_overlap, "replay_hash_overlap"),
            (source_overlap, "source_lineage_overlap"),
            (collection_overlap, "collection_lineage_overlap"),
            (authoring_overlap, "authoring_lineage_overlap"),
        )
        if values
    )
    if overlap_labels:
        raise PromotionScenarioError(
            "development and holdout partitions overlap: "
            + ",".join(overlap_labels)
        )

    return ScenarioPartitionManifestV2(
        schema_version=PARTITION_SCHEMA_VERSION,
        manifest_id=_partition_manifest_id(
            development.target_capability_set_hash,
            development.corpus_hash,
            external_holdout.corpus_hash,
        ),
        target_capability_set_hash=development.target_capability_set_hash,
        catalog_hash=development.catalog_hash,
        ruleset_hash=development.ruleset_hash,
        development_corpus_id=development.corpus_id,
        development_corpus_hash=development.corpus_hash,
        external_holdout_corpus_id=external_holdout.corpus_id,
        external_holdout_corpus_hash=external_holdout.corpus_hash,
        development_scenario_hashes=development_scenario_hashes,
        external_holdout_scenario_hashes=holdout_scenario_hashes,
        development_replay_hashes=development_replay_hashes,
        external_holdout_replay_hashes=holdout_replay_hashes,
        development_source_lineage_ids=development_source,
        external_holdout_source_lineage_ids=holdout_source,
        development_collection_lineage_ids=development_collection,
        external_holdout_collection_lineage_ids=holdout_collection,
        development_authoring_lineage_ids=development_authoring,
        external_holdout_authoring_lineage_ids=holdout_authoring,
        scenario_hash_overlap=(),
        replay_hash_overlap=(),
        source_lineage_overlap=(),
        collection_lineage_overlap=(),
        authoring_lineage_overlap=(),
    )


def replay_choice_sequence_hash(replay: ReplayRecord) -> str:
    """Hash the exact ordered selections at every Replay decision boundary."""

    if type(replay) is not ReplayRecord:
        raise PromotionScenarioError("choice hashing requires exact ReplayRecord")
    return canonical_hash(tuple(step.selections for step in replay.steps))


@dataclass(frozen=True, slots=True)
class _CapabilityEventContract:
    """Production-owned event proof for one supported semantic effect."""

    entity_kind: str
    witness_kind: BattleEventKind
    required_sequence: tuple[BattleEventKind, ...]


_CAPABILITY_EVENT_CONTRACTS = {
    "move.damage": _CapabilityEventContract(
        "move", BattleEventKind.DAMAGE,
        (BattleEventKind.MOVE_USED, BattleEventKind.DAMAGE),
    ),
    "move.damage_drain": _CapabilityEventContract(
        "move", BattleEventKind.HEALED,
        (
            BattleEventKind.MOVE_USED,
            BattleEventKind.DAMAGE,
            BattleEventKind.HEALED,
        ),
    ),
    "move.damage_secondary_flinch": _CapabilityEventContract(
        "move", BattleEventKind.VOLATILE_CHANGED,
        (
            BattleEventKind.MOVE_USED,
            BattleEventKind.DAMAGE,
            BattleEventKind.VOLATILE_CHANGED,
        ),
    ),
    "move.damage_secondary_stage": _CapabilityEventContract(
        "move", BattleEventKind.STAT_STAGE_CHANGED,
        (
            BattleEventKind.MOVE_USED,
            BattleEventKind.DAMAGE,
            BattleEventKind.STAT_STAGE_CHANGED,
        ),
    ),
    "move.damage_secondary_status": _CapabilityEventContract(
        "move", BattleEventKind.STATUS_CHANGED,
        (
            BattleEventKind.MOVE_USED,
            BattleEventKind.DAMAGE,
            BattleEventKind.STATUS_CHANGED,
        ),
    ),
    "move.heal_self": _CapabilityEventContract(
        "move", BattleEventKind.HEALED,
        (BattleEventKind.MOVE_USED, BattleEventKind.HEALED),
    ),
    "move.inflict_status": _CapabilityEventContract(
        "move", BattleEventKind.STATUS_CHANGED,
        (BattleEventKind.MOVE_USED, BattleEventKind.STATUS_CHANGED),
    ),
    "move.raise_self": _CapabilityEventContract(
        "move", BattleEventKind.STAT_STAGE_CHANGED,
        (BattleEventKind.MOVE_USED, BattleEventKind.STAT_STAGE_CHANGED),
    ),
    "ability.rough_skin": _CapabilityEventContract(
        "ability", BattleEventKind.ABILITY_TRIGGERED,
        (BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.DAMAGE),
    ),
    "ability.natural_cure": _CapabilityEventContract(
        "ability", BattleEventKind.ABILITY_TRIGGERED,
        (BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.STATUS_CHANGED),
    ),
    "ability.technician": _CapabilityEventContract(
        "ability", BattleEventKind.ABILITY_TRIGGERED,
        (BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.DAMAGE),
    ),
    "ability.intimidate": _CapabilityEventContract(
        "ability", BattleEventKind.ABILITY_TRIGGERED,
        (BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.STAT_STAGE_CHANGED),
    ),
    "ability.overgrow": _CapabilityEventContract(
        "ability", BattleEventKind.ABILITY_TRIGGERED,
        (BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.DAMAGE),
    ),
    "ability.blaze": _CapabilityEventContract(
        "ability", BattleEventKind.ABILITY_TRIGGERED,
        (BattleEventKind.ABILITY_TRIGGERED, BattleEventKind.DAMAGE),
    ),
    "item.leftovers": _CapabilityEventContract(
        "item", BattleEventKind.ITEM_TRIGGERED,
        (BattleEventKind.ITEM_TRIGGERED, BattleEventKind.HEALED),
    ),
    "item.sitrus_berry": _CapabilityEventContract(
        "item", BattleEventKind.ITEM_TRIGGERED,
        (
            BattleEventKind.ITEM_TRIGGERED,
            BattleEventKind.ITEM_CONSUMED,
            BattleEventKind.HEALED,
        ),
    ),
    "item.focus_sash": _CapabilityEventContract(
        "item", BattleEventKind.ITEM_TRIGGERED,
        (
            BattleEventKind.ITEM_TRIGGERED,
            BattleEventKind.ITEM_CONSUMED,
            BattleEventKind.DAMAGE,
        ),
    ),
    "item.mega_stone": _CapabilityEventContract(
        "item", BattleEventKind.MEGA_EVOLVED,
        (BattleEventKind.MEGA_EVOLVED,),
    ),
    "mechanic.mega_evolution": _CapabilityEventContract(
        "mechanic", BattleEventKind.MEGA_EVOLVED,
        (BattleEventKind.MEGA_EVOLVED,),
    ),
}


def _capability_for_scenario(
    capability_set: TargetCapabilitySet,
    scenario: EngineScenarioV2,
) -> tuple[TargetCapability, _CapabilityEventContract, frozenset[str]]:
    matches = tuple(
        capability
        for capability in capability_set.capabilities
        if capability.capability_id == scenario.capability_id
    )
    if len(matches) != 1:
        raise PromotionScenarioError(
            "scenario capability is not unique in TargetCapabilitySet"
        )
    capability = matches[0]
    contract = _CAPABILITY_EVENT_CONTRACTS.get(capability.signature.effect_id)
    if contract is None:
        raise PromotionScenarioError(
            "scenario capability has no production event-proof contract"
        )
    referenced = set(capability.entity_ref_ids)
    entity_ids = frozenset(
        reference.entity_id
        for reference in capability_set.entity_capability_refs
        if reference.ref_id in referenced
        and reference.capability_id == capability.capability_id
        and reference.entity_kind == contract.entity_kind
    )
    if not entity_ids:
        raise PromotionScenarioError(
            "scenario capability lacks an event-bindable entity reference"
        )
    return capability, contract, entity_ids


def _event_details(event: Any) -> dict[str, Any]:
    return {key: value for key, value in event.details}


def _find_event_index(
    events: tuple[Any, ...],
    *,
    start: int,
    kind: BattleEventKind,
    predicate: Any,
) -> int:
    for index in range(start, len(events)):
        event = events[index]
        if event.kind is kind and predicate(event):
            return index
    raise PromotionScenarioError(
        f"capability event proof lacks required event: {kind.value}"
    )


def _validate_move_event_proof(
    *,
    events: tuple[Any, ...],
    witness_index: int,
    contract: _CapabilityEventContract,
    entity_ids: frozenset[str],
) -> None:
    witness = events[witness_index]
    anchor_index = _find_event_index(
        events,
        start=0,
        kind=BattleEventKind.MOVE_USED,
        predicate=lambda event: (
            _event_details(event).get("move_id") in entity_ids
            and event.actor == witness.actor
        ),
    )
    if anchor_index >= witness_index:
        raise PromotionScenarioError(
            "move capability witness is not after its bound move-used event"
        )
    current = anchor_index
    resolved_indexes = [anchor_index]
    for kind in contract.required_sequence[1:]:
        def matches(event: Any, required_kind: BattleEventKind = kind) -> bool:
            details = _event_details(event)
            if event.actor != witness.actor:
                return False
            if required_kind in {
                BattleEventKind.DAMAGE,
                BattleEventKind.HEALED,
                BattleEventKind.STATUS_CHANGED,
                BattleEventKind.STAT_STAGE_CHANGED,
            }:
                return details.get("source") in entity_ids
            if required_kind is BattleEventKind.VOLATILE_CHANGED:
                return details.get("added") == "flinch"
            return True

        current = _find_event_index(
            events,
            start=current + 1,
            kind=kind,
            predicate=matches,
        )
        resolved_indexes.append(current)
    if resolved_indexes[-1] != witness_index:
        raise PromotionScenarioError(
            "move capability witness is not the distinctive terminal proof event"
        )


def _validate_ability_event_proof(
    *,
    effect_id: str,
    events: tuple[Any, ...],
    witness_index: int,
    contract: _CapabilityEventContract,
    entity_ids: frozenset[str],
) -> None:
    witness = events[witness_index]
    details = _event_details(witness)
    if details.get("ability_id") not in entity_ids:
        raise PromotionScenarioError(
            "ability witness does not name a bound TargetCapability entity"
        )
    selector = effect_id.removeprefix("ability.")
    if details.get("effect_id") not in {None, selector}:
        raise PromotionScenarioError("ability witness effect_id differs")
    current = witness_index
    for kind in contract.required_sequence[1:]:
        def matches(event: Any, required_kind: BattleEventKind = kind) -> bool:
            if event.actor != witness.actor:
                return False
            source = _event_details(event).get("source")
            if effect_id in {
                "ability.rough_skin",
                "ability.natural_cure",
                "ability.intimidate",
            }:
                return source == selector
            return required_kind is BattleEventKind.DAMAGE

        current = _find_event_index(
            events,
            start=current + 1,
            kind=kind,
            predicate=matches,
        )


def _validate_item_event_proof(
    *,
    effect_id: str,
    events: tuple[Any, ...],
    witness_index: int,
    contract: _CapabilityEventContract,
    entity_ids: frozenset[str],
) -> None:
    witness = events[witness_index]
    if _event_details(witness).get("item_id") not in entity_ids:
        raise PromotionScenarioError(
            "item witness does not name a bound TargetCapability entity"
        )
    selector = effect_id.removeprefix("item.")
    current = witness_index
    for kind in contract.required_sequence[1:]:
        def matches(event: Any, required_kind: BattleEventKind = kind) -> bool:
            if event.subject != witness.subject:
                return False
            details = _event_details(event)
            if required_kind is BattleEventKind.ITEM_CONSUMED:
                return details.get("item_id") in entity_ids
            if required_kind is BattleEventKind.HEALED:
                return details.get("source") == selector
            return required_kind is BattleEventKind.DAMAGE

        current = _find_event_index(
            events,
            start=current + 1,
            kind=kind,
            predicate=matches,
        )


def _validate_capability_event_proof(
    *,
    capability_set: TargetCapabilitySet,
    scenario: EngineScenarioV2,
    replay: ReplayRecord,
) -> None:
    capability, contract, entity_ids = _capability_for_scenario(
        capability_set, scenario
    )
    if scenario.witness_event_kind != contract.witness_kind.value:
        raise PromotionScenarioError(
            "scenario witness kind does not prove its capability effect"
        )
    events = replay.steps[scenario.witness_step_index].events
    witness_index = scenario.witness_event_index
    if contract.entity_kind == "move":
        _validate_move_event_proof(
            events=events,
            witness_index=witness_index,
            contract=contract,
            entity_ids=entity_ids,
        )
    elif contract.entity_kind == "ability":
        _validate_ability_event_proof(
            effect_id=capability.signature.effect_id,
            events=events,
            witness_index=witness_index,
            contract=contract,
            entity_ids=entity_ids,
        )
    elif contract.entity_kind == "item":
        _validate_item_event_proof(
            effect_id=capability.signature.effect_id,
            events=events,
            witness_index=witness_index,
            contract=contract,
            entity_ids=entity_ids,
        )
    elif contract.entity_kind == "mechanic":
        # The production engine has one supported mechanic event today.  Its
        # capability identity is fixed by the exact TargetCapabilitySet and
        # the closed effect-id table above, rather than by caller metadata.
        if events[witness_index].kind is not BattleEventKind.MEGA_EVOLVED:
            raise PromotionScenarioError("mechanic witness is not mega_evolved")
    else:  # pragma: no cover - closed production table makes this unreachable.
        raise PromotionScenarioError("unsupported capability event-proof kind")


def _probe_id(role: str, capability_id: str, scenario_hash: str) -> str:
    return f"probe-{role}-" + canonical_hash((capability_id, scenario_hash))


@dataclass(frozen=True, slots=True)
class VerifiedEngineProbeV2:
    """Resolver-issued positive result for one exact Replay-backed scenario."""

    probe_id: str
    probe_role: str
    capability_id: str
    scenario_id: str
    scenario_hash: str
    target_capability_set_hash: str
    initial_state_hash: str
    choice_sequence_hash: str
    seed: int
    rng_algorithm_id: str
    catalog_hash: str
    ruleset_hash: str
    replay_hash: str
    final_state_hash: str
    witness_step_index: int
    witness_event_index: int
    witness_event_kind: str
    witness_event_hash: str
    observed_outcome: str
    contract_observed: bool
    replay_verified: bool
    silent_fallback_detected: bool
    _resolver_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._resolver_token is not _VERIFIED_PROBE_TOKEN:
            raise PromotionScenarioError(
                "VerifiedEngineProbeV2 must be created by the Replay resolver"
            )
        if self.probe_role not in _PROBE_ROLES:
            raise PromotionScenarioError("unsupported engine probe role")
        _stable(self.probe_id, "probe_id")
        _stable(self.capability_id, "capability_id")
        _stable(self.scenario_id, "scenario_id")
        for value, label in (
            (self.scenario_hash, "scenario_hash"),
            (self.target_capability_set_hash, "target_capability_set_hash"),
            (self.initial_state_hash, "initial_state_hash"),
            (self.choice_sequence_hash, "choice_sequence_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
            (self.replay_hash, "replay_hash"),
            (self.final_state_hash, "final_state_hash"),
            (self.witness_event_hash, "witness_event_hash"),
        ):
            _sha256(value, label)
        _exact_uint(self.seed, "seed", maximum=_UINT64_MAX)
        if self.rng_algorithm_id != RNG_ALGORITHM_ID:
            raise PromotionScenarioError("unsupported probe RNG algorithm")
        _exact_uint(self.witness_step_index, "witness_step_index")
        _exact_uint(self.witness_event_index, "witness_event_index")
        _stable(self.witness_event_kind, "witness_event_kind")
        if self.probe_id != _probe_id(
            self.probe_role, self.capability_id, self.scenario_hash
        ):
            raise PromotionScenarioError("engine probe ID is not canonical")
        if (
            self.observed_outcome != "success"
            or self.contract_observed is not True
            or self.replay_verified is not True
            or self.silent_fallback_detected is not False
        ):
            raise PromotionScenarioError(
                "verified engine probe requires positive Replay-backed execution"
            )

    @property
    def probe_hash(self) -> str:
        return canonical_hash(self._unsigned_data())

    def _unsigned_data(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "probe_role": self.probe_role,
            "capability_id": self.capability_id,
            "scenario_id": self.scenario_id,
            "scenario_hash": self.scenario_hash,
            "target_capability_set_hash": self.target_capability_set_hash,
            "initial_state_hash": self.initial_state_hash,
            "choice_sequence_hash": self.choice_sequence_hash,
            "seed": self.seed,
            "rng_algorithm_id": self.rng_algorithm_id,
            "catalog_hash": self.catalog_hash,
            "ruleset_hash": self.ruleset_hash,
            "replay_hash": self.replay_hash,
            "final_state_hash": self.final_state_hash,
            "witness_step_index": self.witness_step_index,
            "witness_event_index": self.witness_event_index,
            "witness_event_kind": self.witness_event_kind,
            "witness_event_hash": self.witness_event_hash,
            "observed_outcome": self.observed_outcome,
            "contract_observed": self.contract_observed,
            "replay_verified": self.replay_verified,
            "silent_fallback_detected": self.silent_fallback_detected,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self._unsigned_data(), "probe_hash": self.probe_hash}


def verify_engine_probe_v2(
    *,
    engine: BattleEngine,
    capability_set: TargetCapabilitySet,
    scenario: EngineScenarioV2,
    replay: ReplayRecord,
    probe_role: str = "primary",
) -> VerifiedEngineProbeV2:
    """Re-execute ``replay`` and prove one exact production capability effect."""

    if type(engine) is not BattleEngine:
        raise PromotionScenarioError("probe verification requires exact BattleEngine")
    if type(capability_set) is not TargetCapabilitySet:
        raise PromotionScenarioError(
            "probe verification requires exact TargetCapabilitySet"
        )
    if type(scenario) is not EngineScenarioV2:
        raise PromotionScenarioError("probe verification requires exact EngineScenarioV2")
    if type(replay) is not ReplayRecord:
        raise PromotionScenarioError("probe verification requires exact ReplayRecord")
    if probe_role not in _PROBE_ROLES:
        raise PromotionScenarioError("unsupported engine probe role")
    capability_set.__post_init__()
    scenario.__post_init__()
    if not capability_set.denominator_final:
        raise PromotionScenarioError(
            "probe verification requires a final capability denominator"
        )
    if scenario.target_capability_set_hash != capability_set.capability_set_hash:
        raise PromotionScenarioError("scenario TargetCapabilitySet hash differs")
    if capability_set.catalog_hash != engine.catalog.snapshot_hash:
        raise PromotionScenarioError("TargetCapabilitySet Catalog differs from engine")
    if capability_set.ruleset_hash != engine.ruleset.snapshot_hash:
        raise PromotionScenarioError("TargetCapabilitySet RuleSet differs from engine")
    if scenario.catalog_hash != engine.catalog.snapshot_hash:
        raise PromotionScenarioError("scenario Catalog hash differs from engine")
    if scenario.ruleset_hash != engine.ruleset.snapshot_hash:
        raise PromotionScenarioError("scenario RuleSet hash differs from engine")

    try:
        final_state = verify_replay(engine, replay)
    except Exception as error:
        raise PromotionScenarioError("Replay re-execution verification failed") from error

    bindings = (
        ("initial_state_hash", scenario.initial_state_hash, replay.initial_state.state_hash),
        (
            "choice_sequence_hash",
            scenario.choice_sequence_hash,
            replay_choice_sequence_hash(replay),
        ),
        ("seed", scenario.seed, replay.initial_rng.seed),
        ("rng_algorithm_id", scenario.rng_algorithm_id, replay.rng_algorithm_id),
        ("catalog_hash", scenario.catalog_hash, replay.bundle.catalog_content_hash),
        ("ruleset_hash", scenario.ruleset_hash, replay.bundle.ruleset_content_hash),
        ("replay_hash", scenario.replay_hash, replay.replay_hash),
    )
    mismatches = [label for label, actual, expected in bindings if actual != expected]
    if mismatches:
        raise PromotionScenarioError(
            f"scenario/Replay binding mismatch: {','.join(mismatches)}"
        )

    if scenario.witness_step_index >= len(replay.steps):
        raise PromotionScenarioError("witness step index is outside Replay")
    events = replay.steps[scenario.witness_step_index].events
    if scenario.witness_event_index >= len(events):
        raise PromotionScenarioError("witness event index is outside Replay step")
    event = events[scenario.witness_event_index]
    event_kind = event.kind.value
    event_hash = canonical_hash(event)
    witness_mismatches = []
    if scenario.witness_event_kind != event_kind:
        witness_mismatches.append("event_kind")
    if scenario.witness_event_hash != event_hash:
        witness_mismatches.append("event_hash")
    if witness_mismatches:
        raise PromotionScenarioError(
            "scenario witness differs from Replay: " + ",".join(witness_mismatches)
        )
    _validate_capability_event_proof(
        capability_set=capability_set,
        scenario=scenario,
        replay=replay,
    )

    return VerifiedEngineProbeV2(
        probe_id=_probe_id(probe_role, scenario.capability_id, scenario.scenario_hash),
        probe_role=probe_role,
        capability_id=scenario.capability_id,
        scenario_id=scenario.scenario_id,
        scenario_hash=scenario.scenario_hash,
        target_capability_set_hash=scenario.target_capability_set_hash,
        initial_state_hash=scenario.initial_state_hash,
        choice_sequence_hash=scenario.choice_sequence_hash,
        seed=scenario.seed,
        rng_algorithm_id=scenario.rng_algorithm_id,
        catalog_hash=scenario.catalog_hash,
        ruleset_hash=scenario.ruleset_hash,
        replay_hash=scenario.replay_hash,
        final_state_hash=canonical_hash(final_state),
        witness_step_index=scenario.witness_step_index,
        witness_event_index=scenario.witness_event_index,
        witness_event_kind=event_kind,
        witness_event_hash=event_hash,
        observed_outcome="success",
        contract_observed=True,
        replay_verified=True,
        silent_fallback_detected=False,
        _resolver_token=_VERIFIED_PROBE_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class EngineProbeReportV2:
    """All-scenario verification plus exactly one canonical primary per capability."""

    schema_version: str
    report_id: str
    target_capability_set_hash: str
    development_corpus_id: str
    development_corpus_hash: str
    engine_semantics_version: str
    catalog_hash: str
    ruleset_hash: str
    declared_capability_ids: tuple[str, ...]
    required_probe_count: int
    verified_pass_probe_count: int
    engine_probe_pass_rate_ppm: int
    scenario_probe_count: int
    verified_scenario_probe_count: int
    silent_fallback_count: int
    probes: tuple[VerifiedEngineProbeV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ENGINE_PROBE_SCHEMA_VERSION:
            raise PromotionScenarioError("unsupported engine probe report schema_version")
        _stable(self.report_id, "engine probe report_id")
        _stable(self.development_corpus_id, "development_corpus_id")
        _stable(self.engine_semantics_version, "engine_semantics_version")
        for value, label in (
            (self.target_capability_set_hash, "target_capability_set_hash"),
            (self.development_corpus_hash, "development_corpus_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
        ):
            _sha256(value, label)
        _sorted_unique_nonempty(
            self.declared_capability_ids, "declared_capability_ids"
        )
        if type(self.probes) is not tuple or not self.probes:
            raise PromotionScenarioError("engine probe report cannot be empty")
        if any(type(value) is not VerifiedEngineProbeV2 for value in self.probes):
            raise PromotionScenarioError(
                "engine probe report requires exact VerifiedEngineProbeV2"
            )
        for probe in self.probes:
            probe.__post_init__()
            if probe.target_capability_set_hash != self.target_capability_set_hash:
                raise PromotionScenarioError(
                    "probe TargetCapabilitySet hash differs from report"
                )
            if probe.catalog_hash != self.catalog_hash:
                raise PromotionScenarioError("probe Catalog hash differs from report")
            if probe.ruleset_hash != self.ruleset_hash:
                raise PromotionScenarioError("probe RuleSet hash differs from report")
        if self.probes != tuple(sorted(self.probes, key=lambda item: item.probe_id)):
            raise PromotionScenarioError("engine probes must be sorted by probe_id")
        probe_ids = tuple(value.probe_id for value in self.probes)
        scenario_ids = tuple(value.scenario_id for value in self.probes)
        if len(probe_ids) != len(set(probe_ids)):
            raise PromotionScenarioError("engine probe IDs must be unique")
        if len(scenario_ids) != len(set(scenario_ids)):
            raise PromotionScenarioError("each scenario must have exactly one probe")
        declared = set(self.declared_capability_ids)
        if any(value.capability_id not in declared for value in self.probes):
            raise PromotionScenarioError("probe capability is outside declared denominator")
        primary_by_capability = {
            capability_id: tuple(
                value
                for value in self.probes
                if value.capability_id == capability_id
                and value.probe_role == "primary"
            )
            for capability_id in self.declared_capability_ids
        }
        if any(len(values) != 1 for values in primary_by_capability.values()):
            raise PromotionScenarioError(
                "each declared capability requires exactly one primary probe"
            )
        required = len(self.declared_capability_ids)
        verified_primary = sum(len(values) == 1 for values in primary_by_capability.values())
        scenario_count = len(self.probes)
        if self.required_probe_count != required:
            raise PromotionScenarioError("required probe count differs from denominator")
        if self.verified_pass_probe_count != verified_primary:
            raise PromotionScenarioError("verified primary probe count differs")
        if self.engine_probe_pass_rate_ppm != verified_primary * 1_000_000 // required:
            raise PromotionScenarioError("engine probe pass rate differs")
        if self.scenario_probe_count != scenario_count:
            raise PromotionScenarioError("scenario probe count differs")
        if self.verified_scenario_probe_count != scenario_count:
            raise PromotionScenarioError("not every development scenario is verified")
        if self.silent_fallback_count != 0:
            raise PromotionScenarioError("verified report cannot contain silent fallback")
        expected_id = _engine_probe_report_id(
            self.target_capability_set_hash,
            self.development_corpus_hash,
            tuple(value.probe_hash for value in self.probes),
        )
        if self.report_id != expected_id:
            raise PromotionScenarioError("engine probe report ID is not canonical")

    @property
    def report_hash(self) -> str:
        return canonical_hash(self._unsigned_data())

    def _unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "target_capability_set_hash": self.target_capability_set_hash,
            "development_corpus_id": self.development_corpus_id,
            "development_corpus_hash": self.development_corpus_hash,
            "engine_semantics_version": self.engine_semantics_version,
            "catalog_hash": self.catalog_hash,
            "ruleset_hash": self.ruleset_hash,
            "declared_capability_ids": list(self.declared_capability_ids),
            "required_probe_count": self.required_probe_count,
            "verified_pass_probe_count": self.verified_pass_probe_count,
            "engine_probe_pass_rate_ppm": self.engine_probe_pass_rate_ppm,
            "scenario_probe_count": self.scenario_probe_count,
            "verified_scenario_probe_count": self.verified_scenario_probe_count,
            "silent_fallback_count": self.silent_fallback_count,
            "probes": [value.to_data() for value in self.probes],
        }

    def to_data(self) -> dict[str, Any]:
        return {**self._unsigned_data(), "report_hash": self.report_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())

    def validate_against(
        self,
        *,
        engine: BattleEngine,
        capability_set: TargetCapabilitySet,
        development_corpus: EngineScenarioCorpusV2,
        replays: Mapping[str, ReplayRecord],
    ) -> None:
        resolved = build_engine_probe_report_v2(
            engine=engine,
            capability_set=capability_set,
            development_corpus=development_corpus,
            replays=replays,
        )
        if self.to_data() != resolved.to_data():
            raise PromotionScenarioError(
                "engine probe report differs from recomputed Replay substance"
            )


def _engine_probe_report_id(
    target_capability_set_hash: str,
    development_corpus_hash: str,
    probe_hashes: tuple[str, ...],
) -> str:
    return "engine-probe-report-" + canonical_hash(
        (target_capability_set_hash, development_corpus_hash, probe_hashes)
    )


def build_engine_probe_report_v2(
    *,
    engine: BattleEngine,
    capability_set: TargetCapabilitySet,
    development_corpus: EngineScenarioCorpusV2,
    replays: Mapping[str, ReplayRecord],
) -> EngineProbeReportV2:
    """Verify every development scenario and derive canonical primary probes."""

    if type(engine) is not BattleEngine:
        raise PromotionScenarioError("probe report requires exact BattleEngine")
    if type(capability_set) is not TargetCapabilitySet:
        raise PromotionScenarioError("probe report requires exact TargetCapabilitySet")
    if type(development_corpus) is not EngineScenarioCorpusV2:
        raise PromotionScenarioError("probe report requires exact scenario corpus")
    capability_set.__post_init__()
    development_corpus.__post_init__()
    if not capability_set.denominator_final:
        raise PromotionScenarioError(
            "probe report requires a final capability denominator"
        )
    if development_corpus.corpus_role != "development":
        raise PromotionScenarioError("probe report requires a development corpus")
    if (
        development_corpus.target_capability_set_hash
        != capability_set.capability_set_hash
    ):
        raise PromotionScenarioError(
            "development corpus TargetCapabilitySet hash differs"
        )
    if capability_set.catalog_hash != engine.catalog.snapshot_hash:
        raise PromotionScenarioError("TargetCapabilitySet Catalog differs from engine")
    if capability_set.ruleset_hash != engine.ruleset.snapshot_hash:
        raise PromotionScenarioError("TargetCapabilitySet RuleSet differs from engine")
    if development_corpus.catalog_hash != engine.catalog.snapshot_hash:
        raise PromotionScenarioError("development corpus Catalog differs from engine")
    if development_corpus.ruleset_hash != engine.ruleset.snapshot_hash:
        raise PromotionScenarioError("development corpus RuleSet differs from engine")

    declared = tuple(
        sorted(capability.capability_id for capability in capability_set.capabilities)
    )
    _sorted_unique_nonempty(declared, "declared_capability_ids")
    declared_set = set(declared)
    if any(
        scenario.capability_id not in declared_set
        for scenario in development_corpus.scenarios
    ):
        raise PromotionScenarioError(
            "development scenario capability is outside declared denominator"
        )
    by_capability: dict[str, list[EngineScenarioV2]] = {
        value: [] for value in declared
    }
    for scenario in development_corpus.scenarios:
        by_capability[scenario.capability_id].append(scenario)
    missing = tuple(
        capability_id
        for capability_id, scenarios in by_capability.items()
        if not scenarios
    )
    if missing:
        raise PromotionScenarioError(
            "declared capabilities lack development scenarios: " + ",".join(missing)
        )

    replay_keys = set(replays)
    scenario_ids = {value.scenario_id for value in development_corpus.scenarios}
    if replay_keys != scenario_ids:
        missing_replays = sorted(scenario_ids - replay_keys)
        extra_replays = sorted(replay_keys - scenario_ids)
        raise PromotionScenarioError(
            "Replay artifact set differs from development scenarios: "
            f"missing={missing_replays}, extra={extra_replays}"
        )
    if any(type(value) is not ReplayRecord for value in replays.values()):
        raise PromotionScenarioError("Replay artifact map requires exact ReplayRecord")

    primary_scenario_ids = {
        min(
            scenarios,
            key=lambda value: (value.scenario_hash, value.scenario_id),
        ).scenario_id
        for scenarios in by_capability.values()
    }
    probes = tuple(
        sorted(
            (
                verify_engine_probe_v2(
                    engine=engine,
                    capability_set=capability_set,
                    scenario=scenario,
                    replay=replays[scenario.scenario_id],
                    probe_role=(
                        "primary"
                        if scenario.scenario_id in primary_scenario_ids
                        else "supplemental"
                    ),
                )
                for scenario in development_corpus.scenarios
            ),
            key=lambda value: value.probe_id,
        )
    )
    probe_hashes = tuple(value.probe_hash for value in probes)
    return EngineProbeReportV2(
        schema_version=ENGINE_PROBE_SCHEMA_VERSION,
        report_id=_engine_probe_report_id(
            development_corpus.target_capability_set_hash,
            development_corpus.corpus_hash,
            probe_hashes,
        ),
        target_capability_set_hash=development_corpus.target_capability_set_hash,
        development_corpus_id=development_corpus.corpus_id,
        development_corpus_hash=development_corpus.corpus_hash,
        engine_semantics_version=engine.ruleset.engine_semantics_version,
        catalog_hash=development_corpus.catalog_hash,
        ruleset_hash=development_corpus.ruleset_hash,
        declared_capability_ids=declared,
        required_probe_count=len(declared),
        verified_pass_probe_count=len(declared),
        engine_probe_pass_rate_ppm=1_000_000,
        scenario_probe_count=len(probes),
        verified_scenario_probe_count=len(probes),
        silent_fallback_count=0,
        probes=probes,
    )


__all__ = [
    "ENGINE_PROBE_SCHEMA_VERSION",
    "PARTITION_SCHEMA_VERSION",
    "SCENARIO_SCHEMA_VERSION",
    "EngineProbeReportV2",
    "EngineScenarioCorpusV2",
    "EngineScenarioV2",
    "PromotionScenarioError",
    "ScenarioPartitionManifestV2",
    "VerifiedEngineProbeV2",
    "build_engine_probe_report_v2",
    "build_engine_scenario_corpus_v2",
    "build_scenario_partition_manifest_v2",
    "replay_choice_sequence_hash",
    "verify_engine_probe_v2",
]
