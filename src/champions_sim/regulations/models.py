"""Immutable SIM-02 regulation pipeline contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from champions_sim.core import canonical_hash, canonical_json


REGULATION_SCHEMA_VERSION = "1.0.0"
TARGET_POOL_SCHEMA_VERSION = "1.0.0"
COVERAGE_GAP_SCHEMA_VERSION = "1.0.0"
REGULATION_DIFF_SCHEMA_VERSION = "1.0.0"
REHEARSAL_REPORT_SCHEMA_VERSION = "1.0.0"

Scalar: TypeAlias = str | int | bool | None


@dataclass(frozen=True, slots=True)
class RegulationPeriod:
    start_date: str
    end_at: str
    timezone: str


@dataclass(frozen=True, slots=True)
class ItemClause:
    held_items_enabled: bool
    duplicate_held_items_allowed: bool


@dataclass(frozen=True, slots=True)
class BattleTimer:
    total_minutes: int
    player_minutes: int
    turn_seconds: int
    selection_seconds: int


@dataclass(frozen=True, slots=True)
class RegulationSnapshot:
    schema_version: str
    regulation_id: str
    revision: str
    title: str
    status: str
    verification_status: str
    published_at: str | None
    period: RegulationPeriod
    battle_format: str
    team_size: int
    level: int
    item_clause: ItemClause
    battle_timer: BattleTimer
    required_mechanics: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]
    snapshot_hash: str

    @property
    def identity(self) -> str:
        return f"{self.regulation_id}:{self.revision}"


@dataclass(frozen=True, slots=True)
class TargetPoolMember:
    national_dex_no: int
    form_code: str
    variant_code: str
    label: str
    pokemon_id: str | None

    @property
    def target_key(self) -> str:
        return (
            f"dex:{self.national_dex_no:04d}:"
            f"form:{self.form_code}:variant:{self.variant_code}"
        )


@dataclass(frozen=True, slots=True)
class TargetPoolSnapshot:
    schema_version: str
    target_pool_id: str
    regulation_id: str
    regulation_revision: str
    expected_member_count: int
    members: tuple[TargetPoolMember, ...]
    source_manifest_ids: tuple[str, ...]
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class CoverageGapReport:
    schema_version: str
    report_id: str
    regulation_id: str
    regulation_revision: str
    regulation_hash: str
    target_pool_id: str
    target_pool_hash: str
    catalog_id: str
    catalog_hash: str
    ruleset_id: str
    ruleset_hash: str
    eligible_member_count: int
    mapped_member_count: int
    covered_member_count: int
    covered_pokemon_ids: tuple[str, ...]
    missing_pokemon_ids: tuple[str, ...]
    unmapped_target_keys: tuple[str, ...]
    required_mechanics: tuple[str, ...]
    unsupported_mechanics: tuple[str, ...]
    coverage_complete: bool
    blocking_reasons: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]
    restricted_source_manifest_ids: tuple[str, ...]

    def to_json(self) -> str:
        return canonical_json(self)

    @property
    def report_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class SnapshotReference:
    regulation_id: str
    regulation_revision: str
    regulation_hash: str
    target_pool_id: str
    target_pool_hash: str
    coverage_report_hash: str


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    before: Scalar
    after: Scalar


@dataclass(frozen=True, slots=True)
class RegulationDiffBundle:
    schema_version: str
    diff_id: str
    before: SnapshotReference
    after: SnapshotReference
    changed_fields: tuple[FieldChange, ...]
    added_mechanics: tuple[str, ...]
    removed_mechanics: tuple[str, ...]
    added_target_keys: tuple[str, ...]
    removed_target_keys: tuple[str, ...]
    added_blocking_reasons: tuple[str, ...]
    resolved_blocking_reasons: tuple[str, ...]
    requires_simulator_update: bool
    source_manifest_ids: tuple[str, ...]

    def to_json(self) -> str:
        return canonical_json(self)

    @property
    def diff_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class SealedInputHash:
    artifact_id: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RehearsalResources:
    measurement_status: str
    compute_environment: str
    process_count: int
    max_parallel_workers: int
    network_fetch_count: int
    execution_minutes: int
    manual_work_minutes: int
    external_wait_minutes: int

    def __post_init__(self) -> None:
        if self.measurement_status not in {"measured", "synthetic_fixture"}:
            raise ValueError("unsupported rehearsal resource measurement_status")
        if not self.compute_environment:
            raise ValueError("compute_environment must be non-empty")
        if self.process_count <= 0 or self.max_parallel_workers <= 0:
            raise ValueError("rehearsal process and worker counts must be positive")
        for value in (
            self.network_fetch_count,
            self.execution_minutes,
            self.manual_work_minutes,
            self.external_wait_minutes,
        ):
            if value < 0:
                raise ValueError("rehearsal resource durations/counts cannot be negative")


@dataclass(frozen=True, slots=True)
class RegulationRehearsalReport:
    schema_version: str
    report_id: str
    rehearsal_kind: str
    outcome: str
    t0: str
    t_decision: str
    decision_lead_time_seconds: int
    within_48_hours: bool
    provisional_decision_ids: tuple[str, ...]
    sealed_input_hashes: tuple[SealedInputHash, ...]
    source_manifest_ids: tuple[str, ...]
    resources: RehearsalResources
    coverage_report_hash: str
    regulation_diff_hash: str
    target_pool_execution_coverage_rate_ppm: int | None
    verified_grounding_conformance_rate_ppm: int | None
    silent_fallback_count: int
    candidate_bundle_hash: str | None
    no_go_reason_codes: tuple[str, ...]
    operational_rehearsal_success: bool
    deployable_candidate_success: bool
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.rehearsal_kind != "synthetic_internal":
            raise ValueError("rehearsal report v1 only supports synthetic_internal")
        if self.outcome != "no_go":
            raise ValueError("rehearsal report v1 is fail-closed NO-GO only")
        if self.decision_lead_time_seconds < 0:
            raise ValueError("decision lead time cannot be negative")
        if self.silent_fallback_count < 0:
            raise ValueError("silent fallback count cannot be negative")
        for rate in (
            self.target_pool_execution_coverage_rate_ppm,
            self.verified_grounding_conformance_rate_ppm,
        ):
            if rate is not None and not 0 <= rate <= 1_000_000:
                raise ValueError("rehearsal rates must be within 0..1,000,000 ppm")
        if not self.no_go_reason_codes or self.candidate_bundle_hash is not None:
            raise ValueError("NO-GO requires reasons and cannot carry a candidate hash")
        if self.deployable_candidate_success:
            raise ValueError("NO-GO cannot count as deployable candidate success")

    def to_json(self) -> str:
        return canonical_json(self)

    @property
    def report_hash(self) -> str:
        return canonical_hash(self)
