"""Immutable contracts for the SIM-02 TargetCapability pipeline.

The contracts deliberately separate the official eligible population, explicit
Catalog mappings, observed construction evidence, the legal capability closure,
and execution/grounding coverage.  None of the models contains a popularity or
top-N selection knob.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, TypeAlias

from champions_sim.core import canonical_hash, canonical_json


JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | dict[str, "JsonValue"]

SCHEMA_VERSION = "1.0.0"
EXECUTION_DIMENSIONS = (
    "legality",
    "transition",
    "rng",
    "event",
    "observation",
    "replay",
)

_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _stable(value: str, label: str) -> None:
    if _STABLE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a stable ID")


def _sha256(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class ObservationStatus(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class MappingResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"


class CapabilityReachability(str, Enum):
    LEGAL = "legal"
    OBSERVED = "observed"
    MANDATORY = "mandatory"


class DimensionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"


class ResolvedAssertionVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class ArtifactRecordRef:
    evidence_ref_id: str
    source_manifest_id: str
    artifact_id: str
    json_pointer: str
    record_sha256: str

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence_ref_id", self.evidence_ref_id),
            ("source_manifest_id", self.source_manifest_id),
            ("artifact_id", self.artifact_id),
        ):
            _stable(value, label)
        if not self.json_pointer.startswith("/"):
            raise ValueError("json_pointer must be absolute")
        _sha256(self.record_sha256, "record_sha256")


@dataclass(frozen=True, slots=True)
class ContextAtom:
    key: str
    value: JsonScalar

    def __post_init__(self) -> None:
        _stable(self.key, "context key")


@dataclass(frozen=True, slots=True)
class CapabilitySignature:
    effect_id: str
    trigger: str
    target: str
    resolution_context: tuple[ContextAtom, ...]
    ruleset_branch: str

    def __post_init__(self) -> None:
        for label, value in (
            ("effect_id", self.effect_id),
            ("trigger", self.trigger),
            ("target", self.target),
            ("ruleset_branch", self.ruleset_branch),
        ):
            _stable(value, label)
        keys = tuple(value.key for value in self.resolution_context)
        _unique(keys, "resolution context keys")
        if keys != tuple(sorted(keys)):
            raise ValueError("resolution context must be sorted by key")

    @property
    def capability_id(self) -> str:
        return "cap-" + canonical_hash(self)


@dataclass(frozen=True, slots=True)
class ObservedEntity:
    field: str
    entity_id: str | None
    status: ObservationStatus
    rate_ppm: int | None
    rank: int | None
    evidence_ref_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.field not in {"pokemon", "move", "ability", "item", "mega_target"}:
            raise ValueError("unsupported observed entity field")
        if self.entity_id is not None:
            _stable(self.entity_id, "observed entity_id")
        if self.status in {ObservationStatus.UNKNOWN, ObservationStatus.CONFLICT}:
            if self.entity_id is not None:
                raise ValueError("unknown/conflict observations cannot carry one entity_id")
        elif self.entity_id is None:
            raise ValueError("confirmed/inferred observations require entity_id")
        if self.rate_ppm is not None and not 0 <= self.rate_ppm <= 1_000_000:
            raise ValueError("rate_ppm must be between 0 and 1,000,000")
        if self.rank is not None and self.rank <= 0:
            raise ValueError("rank must be positive")
        _unique(self.evidence_ref_ids, "observation evidence refs")


@dataclass(frozen=True, slots=True)
class ConstructionRecord:
    record_id: str
    record_kind: str
    observed_at: str | None
    regulation_id: str
    joint_group_id: str | None
    target_key: str | None
    entities: tuple[ObservedEntity, ...]
    observed_capabilities: tuple[CapabilitySignature, ...]
    source_complete: bool
    evidence_ref_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    record_hash: str

    def __post_init__(self) -> None:
        _stable(self.record_id, "record_id")
        if self.record_kind not in {
            "roster",
            "selection",
            "usage_marginal",
            "battle_reveal",
        }:
            raise ValueError("unsupported construction record_kind")
        _stable(self.regulation_id, "record regulation_id")
        if self.joint_group_id is not None:
            _stable(self.joint_group_id, "joint_group_id")
        if self.target_key is not None:
            _stable(self.target_key, "target_key")
        _unique(self.evidence_ref_ids, "construction evidence refs")
        _unique(self.blockers, "construction blockers")
        _sha256(self.record_hash, "record_hash")


@dataclass(frozen=True, slots=True)
class ConstructionSelectionCorpus:
    schema_version: str
    corpus_id: str
    corpus_role: str
    regulation_id: str
    regulation_revision: str
    regulation_hash: str
    capture_window_start: str
    capture_window_end: str
    records: tuple[ConstructionRecord, ...]
    evidence_refs: tuple[ArtifactRecordRef, ...]
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported construction corpus schema_version")
        _stable(self.corpus_id, "corpus_id")
        if self.corpus_role not in {"development", "external_holdout"}:
            raise ValueError("corpus_role must be development or external_holdout")
        _stable(self.regulation_id, "corpus regulation_id")
        _stable(self.regulation_revision, "corpus regulation_revision")
        _sha256(self.regulation_hash, "corpus regulation_hash")
        if not self.capture_window_start or not self.capture_window_end:
            raise ValueError("capture window is required")
        record_ids = tuple(value.record_id for value in self.records)
        evidence_ids = tuple(value.evidence_ref_id for value in self.evidence_refs)
        _unique(record_ids, "construction record IDs")
        _unique(evidence_ids, "corpus evidence IDs")
        _unique(self.source_manifest_ids, "corpus source manifest IDs")
        available = set(evidence_ids)
        for record in self.records:
            if not set(record.evidence_ref_ids) <= available:
                raise ValueError("construction record references unknown evidence")
            for entity in record.entities:
                if not set(entity.evidence_ref_ids) <= available:
                    raise ValueError("observed entity references unknown evidence")

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class MappingEntry:
    target_key: str
    catalog_pokemon_id: str | None
    resolution_status: MappingResolutionStatus
    verification_status: VerificationStatus
    mapping_method: str
    candidate_pokemon_ids: tuple[str, ...]
    evidence_ref_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.target_key, "mapping target_key")
        _stable(self.mapping_method, "mapping_method")
        if self.catalog_pokemon_id is not None:
            _stable(self.catalog_pokemon_id, "catalog_pokemon_id")
        _unique(self.candidate_pokemon_ids, "mapping candidates")
        _unique(self.evidence_ref_ids, "mapping evidence refs")
        if self.resolution_status is MappingResolutionStatus.RESOLVED:
            if self.catalog_pokemon_id is None or not self.evidence_ref_ids:
                raise ValueError("resolved mapping requires an ID and source evidence")
        elif self.catalog_pokemon_id is not None:
            raise ValueError("unresolved/conflict mapping cannot select a Catalog ID")
        if self.resolution_status is MappingResolutionStatus.CONFLICT:
            if len(self.candidate_pokemon_ids) < 2:
                raise ValueError("conflict mapping requires at least two candidates")


@dataclass(frozen=True, slots=True)
class MappingEvidenceSet:
    mapping_set_id: str
    target_pool_hash: str
    catalog_hash: str
    entries: tuple[MappingEntry, ...]
    evidence_refs: tuple[ArtifactRecordRef, ...]
    source_manifest_ids: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported MappingEvidenceSet schema_version")
        _stable(self.mapping_set_id, "mapping_set_id")
        _sha256(self.target_pool_hash, "mapping target_pool_hash")
        _sha256(self.catalog_hash, "mapping catalog_hash")
        _unique(tuple(value.target_key for value in self.entries), "mapping target keys")
        evidence_ids = tuple(value.evidence_ref_id for value in self.evidence_refs)
        _unique(evidence_ids, "mapping evidence IDs")
        available = set(evidence_ids)
        if any(not set(value.evidence_ref_ids) <= available for value in self.entries):
            raise ValueError("mapping entry references unknown evidence")
        _unique(self.source_manifest_ids, "mapping source manifest IDs")

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    eligible_member_policy: str = "all_official_records"
    construction_record_policy: str = "all_sealed_records"
    popularity_filter: str = "none"
    rank_filter: str = "none"
    minimum_usage_filter: str = "none"
    dedupe_policy: str = "exact_record_hash_only"

    def __post_init__(self) -> None:
        if (
            self.eligible_member_policy != "all_official_records"
            or self.construction_record_policy != "all_sealed_records"
            or self.popularity_filter != "none"
            or self.rank_filter != "none"
            or self.minimum_usage_filter != "none"
            or self.dedupe_policy != "exact_record_hash_only"
        ):
            raise ValueError("TargetPool policy cannot narrow the official/corpus inputs")


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    record_id: str
    record_hash: str

    def __post_init__(self) -> None:
        _stable(self.record_id, "record identity")
        _sha256(self.record_hash, "record identity hash")


@dataclass(frozen=True, slots=True)
class DuplicateRecordAlias:
    canonical_record_id: str
    duplicate_record_id: str
    identical_record_hash: str

    def __post_init__(self) -> None:
        _stable(self.canonical_record_id, "canonical record ID")
        _stable(self.duplicate_record_id, "duplicate record ID")
        _sha256(self.identical_record_hash, "duplicate record hash")
        if self.canonical_record_id == self.duplicate_record_id:
            raise ValueError("duplicate alias must name different records")


@dataclass(frozen=True, slots=True)
class TargetPoolManifest:
    schema_version: str
    manifest_id: str
    regulation_id: str
    regulation_revision: str
    regulation_hash: str
    eligible_pool_id: str
    eligible_pool_hash: str
    catalog_id: str
    catalog_hash: str
    ruleset_id: str
    ruleset_hash: str
    construction_corpus_id: str
    construction_corpus_hash: str
    mapping_set_id: str
    mapping_set_hash: str
    selection_policy: SelectionPolicy
    eligible_member_count: int
    required_mechanics: tuple[str, ...]
    member_mappings: tuple[MappingEntry, ...]
    included_records: tuple[RecordIdentity, ...]
    duplicate_aliases: tuple[DuplicateRecordAlias, ...]
    source_manifest_ids: tuple[str, ...]
    restricted_source_manifest_ids: tuple[str, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported target pool manifest schema_version")
        for label, value in (
            ("manifest_id", self.manifest_id),
            ("regulation_id", self.regulation_id),
            ("regulation_revision", self.regulation_revision),
            ("eligible_pool_id", self.eligible_pool_id),
            ("catalog_id", self.catalog_id),
            ("ruleset_id", self.ruleset_id),
            ("construction_corpus_id", self.construction_corpus_id),
            ("mapping_set_id", self.mapping_set_id),
        ):
            _stable(value, label)
        for label, value in (
            ("regulation_hash", self.regulation_hash),
            ("eligible_pool_hash", self.eligible_pool_hash),
            ("catalog_hash", self.catalog_hash),
            ("ruleset_hash", self.ruleset_hash),
            ("construction_corpus_hash", self.construction_corpus_hash),
            ("mapping_set_hash", self.mapping_set_hash),
        ):
            _sha256(value, label)
        if self.eligible_member_count <= 0:
            raise ValueError("eligible_member_count must be positive")
        if len(self.member_mappings) != self.eligible_member_count:
            raise ValueError("member mapping count differs from eligible denominator")
        _unique(self.required_mechanics, "required mechanics")
        _unique(tuple(value.target_key for value in self.member_mappings), "manifest target keys")
        _unique(tuple(value.record_id for value in self.included_records), "included records")
        _unique(self.source_manifest_ids, "manifest source IDs")
        _unique(self.restricted_source_manifest_ids, "restricted source IDs")
        _unique(self.blockers, "target-pool blockers")

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class SemanticDefinition:
    semantic_id: str
    entity_kind: str
    selector_id: str
    signature: CapabilitySignature
    requires_tokens: tuple[str, ...]
    produces_tokens: tuple[str, ...]
    grounding_boundaries: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.semantic_id, "semantic_id")
        if self.entity_kind not in {"move", "ability", "item", "mechanic", "interaction"}:
            raise ValueError("unsupported semantic entity_kind")
        _stable(self.selector_id, "semantic selector_id")
        for values, label in (
            (self.requires_tokens, "required tokens"),
            (self.produces_tokens, "produced tokens"),
            (self.grounding_boundaries, "grounding boundaries"),
        ):
            _unique(values, label)
            for value in values:
                _stable(value, label)


@dataclass(frozen=True, slots=True)
class EffectSemanticRegistry:
    registry_id: str
    semantics_version: str
    definitions: tuple[SemanticDefinition, ...]
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.registry_id, "registry_id")
        _stable(self.semantics_version, "semantics_version")
        _unique(tuple(value.semantic_id for value in self.definitions), "semantic IDs")
        selectors = tuple(
            f"{value.entity_kind}:{value.selector_id}:{value.signature.capability_id}"
            for value in self.definitions
        )
        _unique(selectors, "semantic selector/signature definitions")
        _unique(self.source_manifest_ids, "semantic source IDs")

    @property
    def registry_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class EntityCapabilityRef:
    ref_id: str
    entity_kind: str
    entity_id: str
    owner_entity_id: str | None
    capability_id: str
    legal_status: str
    observed_in_corpus: bool
    source_record_ids: tuple[str, ...]
    evidence_ref_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("ref_id", self.ref_id),
            ("entity_id", self.entity_id),
            ("capability_id", self.capability_id),
        ):
            _stable(value, label)
        if self.entity_kind not in {"move", "ability", "item", "mechanic", "interaction"}:
            raise ValueError("unsupported entity capability kind")
        if self.owner_entity_id is not None:
            _stable(self.owner_entity_id, "owner_entity_id")
        if self.legal_status != "legal":
            raise ValueError("TargetCapability refs must be legally reachable")
        _unique(self.source_record_ids, "entity source record IDs")
        _unique(self.evidence_ref_ids, "entity evidence refs")


@dataclass(frozen=True, slots=True)
class GroundingRequirement:
    requirement_id: str
    capability_id: str
    boundary_id: str
    scope: str
    entity_ref_id: str | None
    allowed_evidence_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("requirement_id", self.requirement_id),
            ("capability_id", self.capability_id),
            ("boundary_id", self.boundary_id),
        ):
            _stable(value, label)
        if self.scope not in {"shared_semantics", "entity_reference"}:
            raise ValueError("unsupported grounding requirement scope")
        if (self.scope == "entity_reference") != (self.entity_ref_id is not None):
            raise ValueError("entity grounding scope requires exactly one entity ref")
        _unique(self.allowed_evidence_kinds, "allowed grounding evidence kinds")


@dataclass(frozen=True, slots=True)
class TargetCapability:
    capability_id: str
    signature: CapabilitySignature
    reachability: CapabilityReachability
    entity_ref_ids: tuple[str, ...]
    grounding_requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.capability_id, "capability_id")
        _unique(self.entity_ref_ids, "capability entity refs")
        _unique(self.grounding_requirement_ids, "capability grounding requirements")
        if not self.entity_ref_ids or not self.grounding_requirement_ids:
            raise ValueError("capability requires entity and grounding references")


@dataclass(frozen=True, slots=True)
class UnresolvedRequirement:
    requirement_id: str
    kind: str
    subject_ref: str
    evidence_ref_ids: tuple[str, ...]
    blocker_code: str

    def __post_init__(self) -> None:
        _stable(self.requirement_id, "unresolved requirement_id")
        _stable(self.kind, "unresolved kind")
        if not self.subject_ref or not self.blocker_code:
            raise ValueError("unresolved requirement requires subject and blocker")
        _unique(self.evidence_ref_ids, "unresolved evidence refs")


@dataclass(frozen=True, slots=True)
class TargetCapabilitySet:
    schema_version: str
    capability_set_id: str
    target_pool_manifest_id: str
    target_pool_manifest_hash: str
    catalog_hash: str
    ruleset_hash: str
    semantic_registry_id: str
    semantic_registry_hash: str
    closure_algorithm_version: str
    denominator_final: bool
    entity_capability_refs: tuple[EntityCapabilityRef, ...]
    capabilities: tuple[TargetCapability, ...]
    grounding_requirements: tuple[GroundingRequirement, ...]
    unresolved_requirements: tuple[UnresolvedRequirement, ...]
    development_records: tuple[RecordIdentity, ...]
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported TargetCapabilitySet schema_version")
        _stable(self.capability_set_id, "capability_set_id")
        for value, label in (
            (self.target_pool_manifest_hash, "target_pool_manifest_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
            (self.semantic_registry_hash, "semantic_registry_hash"),
        ):
            _sha256(value, label)
        cap_ids = tuple(value.capability_id for value in self.capabilities)
        ref_ids = tuple(value.ref_id for value in self.entity_capability_refs)
        req_ids = tuple(value.requirement_id for value in self.grounding_requirements)
        _unique(cap_ids, "capability IDs")
        _unique(ref_ids, "entity capability ref IDs")
        _unique(req_ids, "grounding requirement IDs")
        _unique(
            tuple(value.requirement_id for value in self.unresolved_requirements),
            "unresolved requirement IDs",
        )
        if self.denominator_final != (not self.unresolved_requirements):
            raise ValueError("denominator_final must reflect unresolved requirements")
        if self.denominator_final and not self.capabilities:
            raise ValueError("a final denominator cannot be empty")
        cap_set = set(cap_ids)
        ref_set = set(ref_ids)
        req_set = set(req_ids)
        for capability in self.capabilities:
            if capability.capability_id != capability.signature.capability_id:
                raise ValueError("capability ID differs from canonical signature")
            if not set(capability.entity_ref_ids) <= ref_set:
                raise ValueError("capability references unknown entity refs")
            if not set(capability.grounding_requirement_ids) <= req_set:
                raise ValueError("capability references unknown grounding requirements")
        if any(value.capability_id not in cap_set for value in self.entity_capability_refs):
            raise ValueError("entity ref references unknown capability")
        if any(value.capability_id not in cap_set for value in self.grounding_requirements):
            raise ValueError("grounding requirement references unknown capability")

    @property
    def capability_set_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class CoverageDimensionResult:
    dimension: str
    status: DimensionStatus
    contract_id: str
    test_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.dimension not in EXECUTION_DIMENSIONS:
            raise ValueError("unsupported execution dimension")
        _stable(self.contract_id, "execution contract_id")
        _unique(self.test_ids, "execution test IDs")
        if self.status is DimensionStatus.PASS and not self.test_ids:
            raise ValueError("passing execution dimension requires test evidence")
        if self.dimension == "rng" and self.status is DimensionStatus.PASS:
            if not (self.contract_id.startswith("rng:") or self.contract_id.startswith("rng.")):
                raise ValueError("RNG dimension must explicitly name its consumption contract")


@dataclass(frozen=True, slots=True)
class ExecutionSupport:
    capability_id: str
    handler_id: str
    dimensions: tuple[CoverageDimensionResult, ...]

    def __post_init__(self) -> None:
        _stable(self.capability_id, "execution capability_id")
        _stable(self.handler_id, "handler_id")
        dimension_ids = tuple(value.dimension for value in self.dimensions)
        _unique(dimension_ids, "execution dimensions")


@dataclass(frozen=True, slots=True)
class ExecutionRegistry:
    registry_id: str
    engine_semantics_version: str
    supports: tuple[ExecutionSupport, ...]
    source_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.registry_id, "execution registry_id")
        _stable(self.engine_semantics_version, "engine semantics version")
        _unique(tuple(value.capability_id for value in self.supports), "execution capability IDs")
        for value in self.source_hashes:
            _sha256(value, "execution source hash")

    @property
    def registry_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    probe_id: str
    capability_id: str
    expected_outcome: str

    def __post_init__(self) -> None:
        if self.expected_outcome not in {"supported", "explicit_unsupported"}:
            raise ValueError("unsupported expected probe outcome")


@dataclass(frozen=True, slots=True)
class ProbeExecution:
    observed_outcome: str
    contract_observed: bool
    replay_hash: str | None

    def __post_init__(self) -> None:
        if self.observed_outcome not in {
            "success",
            "unsupported_exception",
            "unexpected_error",
        }:
            raise ValueError("unsupported observed probe outcome")
        if self.replay_hash is not None:
            _sha256(self.replay_hash, "probe replay_hash")


@dataclass(frozen=True, slots=True)
class SilentFallbackProbeResult:
    probe_id: str
    capability_id: str
    expected_outcome: str
    observed_outcome: str
    explicit_unsupported: bool
    silent_fallback_detected: bool
    replay_hash: str | None


@dataclass(frozen=True, slots=True)
class StateCheck:
    path: str
    expected: JsonValue

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("state check path must be absolute")


@dataclass(frozen=True, slots=True)
class ConformanceCheckRef:
    frame_id: str
    path: str

    def __post_init__(self) -> None:
        _stable(self.frame_id, "conformance frame_id")
        if not self.path.startswith("/"):
            raise ValueError("conformance path must be absolute")


@dataclass(frozen=True, slots=True)
class GroundingAssertion:
    assertion_id: str
    requirement_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    evidence_kind: str
    ruleset_id: str
    ruleset_hash: str
    catalog_hash: str
    trace_id: str | None
    trace_hash: str | None
    reference_replay_hash: str | None
    initial_state_hash: str | None
    choice_sequence_hash: str | None
    rng_condition_id: str
    expected_event_slice_hash: str | None
    expected_state_checks: tuple[StateCheck, ...]
    conformance_check_refs: tuple[ConformanceCheckRef, ...]
    evidence_ref_ids: tuple[str, ...]
    claimed_verdict: str

    def __post_init__(self) -> None:
        _stable(self.assertion_id, "assertion_id")
        _stable(self.rng_condition_id, "rng_condition_id")
        _unique(self.requirement_ids, "assertion requirement IDs")
        _unique(self.capability_ids, "assertion capability IDs")
        _unique(self.evidence_ref_ids, "assertion evidence refs")
        if self.claimed_verdict not in {"pass", "fail", "unknown"}:
            raise ValueError("unsupported claimed assertion verdict")
        for value, label in (
            (self.ruleset_hash, "assertion ruleset_hash"),
            (self.catalog_hash, "assertion catalog_hash"),
        ):
            _sha256(value, label)
        for value, label in (
            (self.trace_hash, "trace_hash"),
            (self.reference_replay_hash, "reference_replay_hash"),
            (self.initial_state_hash, "initial_state_hash"),
            (self.choice_sequence_hash, "choice_sequence_hash"),
            (self.expected_event_slice_hash, "expected_event_slice_hash"),
        ):
            if value is not None:
                _sha256(value, label)
        if self.initial_state_hash is None or self.choice_sequence_hash is None:
            raise ValueError(
                "grounding assertion requires initial-state and choice-sequence hashes"
            )
        if self.expected_event_slice_hash is None and not self.expected_state_checks:
            raise ValueError(
                "grounding assertion requires an expected event slice or state check"
            )


@dataclass(frozen=True, slots=True)
class GroundingAssertionSet:
    schema_version: str
    assertion_set_id: str
    target_capability_set_id: str
    target_capability_set_hash: str
    assertions: tuple[GroundingAssertion, ...]
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported GroundingAssertionSet schema_version")
        _stable(self.assertion_set_id, "assertion_set_id")
        _stable(self.target_capability_set_id, "assertion target set ID")
        _sha256(self.target_capability_set_hash, "assertion target set hash")
        _unique(tuple(value.assertion_id for value in self.assertions), "assertion IDs")
        _unique(self.source_manifest_ids, "assertion source manifest IDs")

    @property
    def assertion_set_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class ResolvedGroundingAssertion:
    assertion_id: str
    requirement_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    verdict: ResolvedAssertionVerdict
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MechanicCoverageRow:
    capability_id: str
    entity_ref_ids: tuple[str, ...]
    execution_dimensions: tuple[CoverageDimensionResult, ...]
    grounding_requirement_ids: tuple[str, ...]
    passed_grounding_requirement_ids: tuple[str, ...]
    probe_ids: tuple[str, ...]
    fully_supported: bool
    grounding_complete: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MechanicCoverageMatrix:
    schema_version: str
    matrix_id: str
    target_capability_set_id: str
    target_capability_set_hash: str
    execution_registry_hash: str
    grounding_assertion_set_hash: str
    probe_report_hash: str
    holdout_report_hash: str | None
    denominator_final: bool
    declared_target_capability_count: int | None
    fully_supported_target_capability_count: int | None
    target_pool_execution_coverage_rate_ppm: int | None
    required_grounding_requirement_count: int | None
    passed_grounding_requirement_count: int | None
    verified_grounding_conformance_rate_ppm: int | None
    silent_fallback_count: int
    rows: tuple[MechanicCoverageRow, ...]
    unresolved_requirements: tuple[UnresolvedRequirement, ...]
    coverage_complete: bool
    candidate_ready: bool
    blocking_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported MechanicCoverageMatrix schema_version")
        _unique(tuple(value.capability_id for value in self.rows), "coverage row capabilities")
        _unique(self.blocking_reasons, "coverage blocking reasons")
        if not self.denominator_final:
            if any(
                value is not None
                for value in (
                    self.declared_target_capability_count,
                    self.fully_supported_target_capability_count,
                    self.target_pool_execution_coverage_rate_ppm,
                    self.required_grounding_requirement_count,
                    self.passed_grounding_requirement_count,
                    self.verified_grounding_conformance_rate_ppm,
                )
            ):
                raise ValueError("non-final denominator cannot publish coverage counts/rates")
            if self.coverage_complete or self.candidate_ready:
                raise ValueError("non-final denominator cannot be complete or ready")
        else:
            declared = len(self.rows)
            fully_supported = sum(value.fully_supported for value in self.rows)
            required_ids = {
                requirement_id
                for row in self.rows
                for requirement_id in row.grounding_requirement_ids
            }
            passed_ids = {
                requirement_id
                for row in self.rows
                for requirement_id in row.passed_grounding_requirement_ids
            }
            if self.declared_target_capability_count != declared:
                raise ValueError("declared capability count differs from rows")
            if self.fully_supported_target_capability_count != fully_supported:
                raise ValueError("fully-supported count differs from rows")
            if self.target_pool_execution_coverage_rate_ppm != _ppm(
                fully_supported, declared
            ):
                raise ValueError("execution coverage rate differs from rows")
            if self.required_grounding_requirement_count != len(required_ids):
                raise ValueError("required grounding count differs from rows")
            if self.passed_grounding_requirement_count != len(passed_ids):
                raise ValueError("passed grounding count differs from rows")
            if self.verified_grounding_conformance_rate_ppm != _ppm(
                len(passed_ids), len(required_ids)
            ):
                raise ValueError("grounding coverage rate differs from rows")
        if self.candidate_ready and (
            not self.coverage_complete
            or self.holdout_report_hash is None
            or any(not value.grounding_complete for value in self.rows)
            or self.silent_fallback_count != 0
        ):
            raise ValueError("candidate_ready requires every promotion gate")

    @property
    def matrix_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


def _ppm(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return numerator * 1_000_000 // denominator


@dataclass(frozen=True, slots=True)
class HoldoutGapReport:
    schema_version: str
    report_id: str
    target_capability_set_id: str
    target_capability_set_hash: str
    holdout_corpus_id: str
    holdout_corpus_hash: str
    overlapping_record_hashes: tuple[str, ...]
    new_entity_refs: tuple[str, ...]
    new_capability_ids: tuple[str, ...]
    unknown_observation_refs: tuple[str, ...]
    quality_blockers: tuple[str, ...]
    holdout_clean: bool
    blocking_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported HoldoutGapReport schema_version")
        if self.holdout_clean != (not self.blocking_reasons):
            raise ValueError("holdout_clean must reflect blocking reasons")
        for values, label in (
            (self.overlapping_record_hashes, "overlapping holdout hashes"),
            (self.new_entity_refs, "new holdout entities"),
            (self.new_capability_ids, "new holdout capabilities"),
            (self.unknown_observation_refs, "unknown holdout observations"),
            (self.quality_blockers, "holdout quality blockers"),
            (self.blocking_reasons, "holdout blocking reasons"),
        ):
            _unique(values, label)

    @property
    def report_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)
