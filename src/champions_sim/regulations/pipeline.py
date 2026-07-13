"""Coverage and delta tooling for a one-week regulation adaptation loop."""

from __future__ import annotations

from datetime import datetime

from champions_sim.catalog import CatalogSnapshot, RuleSetSnapshot

from .loader import RegulationDataBundle
from .models import (
    COVERAGE_GAP_SCHEMA_VERSION,
    REGULATION_DIFF_SCHEMA_VERSION,
    REHEARSAL_REPORT_SCHEMA_VERSION,
    CoverageGapReport,
    FieldChange,
    RegulationDiffBundle,
    RegulationRehearsalReport,
    RehearsalResources,
    SealedInputHash,
    SnapshotReference,
)


_REHEARSAL_SLA_SECONDS = 48 * 60 * 60


def build_coverage_gap_report(
    bundle: RegulationDataBundle,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
) -> CoverageGapReport:
    regulation = bundle.regulation
    pool = bundle.target_pool
    catalog_by_id = {str(item.pokemon_id): item for item in catalog.species}
    mapped_ids: list[str] = []
    unmapped_keys: list[str] = []
    for member in pool.members:
        mapped = member.pokemon_id
        if mapped is None:
            unmapped_keys.append(member.target_key)
        else:
            mapped_ids.append(mapped)
    mapped_set = set(mapped_ids)
    covered = tuple(sorted(mapped_set & set(catalog_by_id)))
    missing = tuple(sorted(mapped_set - set(catalog_by_id)))
    required = tuple(sorted(regulation.required_mechanics))
    unsupported = tuple(sorted(set(required) - set(ruleset.supported_mechanics)))
    blockers = [f"missing_catalog_pokemon:{value}" for value in missing]
    blockers.extend(f"unsupported_mechanic:{value}" for value in unsupported)
    blockers.extend(f"unmapped_target:{value}" for value in unmapped_keys)
    source_ids = tuple(
        sorted({*regulation.source_manifest_ids, *pool.source_manifest_ids})
    )
    return CoverageGapReport(
        schema_version=COVERAGE_GAP_SCHEMA_VERSION,
        report_id=f"coverage:{regulation.regulation_id}:{regulation.revision}:{pool.target_pool_id}",
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        regulation_hash=regulation.snapshot_hash,
        target_pool_id=pool.target_pool_id,
        target_pool_hash=pool.snapshot_hash,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        eligible_member_count=pool.expected_member_count,
        mapped_member_count=len(mapped_ids),
        covered_member_count=len(covered),
        covered_pokemon_ids=covered,
        missing_pokemon_ids=missing,
        unmapped_target_keys=tuple(unmapped_keys),
        required_mechanics=required,
        unsupported_mechanics=unsupported,
        coverage_complete=not blockers,
        blocking_reasons=tuple(blockers),
        source_manifest_ids=source_ids,
        restricted_source_manifest_ids=bundle.restricted_source_manifest_ids,
    )


def diff_regulation_bundles(
    before_bundle: RegulationDataBundle,
    after_bundle: RegulationDataBundle,
    before_coverage: CoverageGapReport,
    after_coverage: CoverageGapReport,
) -> RegulationDiffBundle:
    before = before_bundle.regulation
    after = after_bundle.regulation
    before_pool = before_bundle.target_pool
    after_pool = after_bundle.target_pool
    _validate_report_boundary(before_bundle, before_coverage, "before")
    _validate_report_boundary(after_bundle, after_coverage, "after")
    changes: list[FieldChange] = []
    scalar_fields = (
        ("period.start_date", before.period.start_date, after.period.start_date),
        ("period.end_at", before.period.end_at, after.period.end_at),
        ("battle_format", before.battle_format, after.battle_format),
        ("team_size", before.team_size, after.team_size),
        ("level", before.level, after.level),
        (
            "item_clause.held_items_enabled",
            before.item_clause.held_items_enabled,
            after.item_clause.held_items_enabled,
        ),
        (
            "item_clause.duplicate_held_items_allowed",
            before.item_clause.duplicate_held_items_allowed,
            after.item_clause.duplicate_held_items_allowed,
        ),
        ("battle_timer.total_minutes", before.battle_timer.total_minutes, after.battle_timer.total_minutes),
        ("battle_timer.player_minutes", before.battle_timer.player_minutes, after.battle_timer.player_minutes),
        ("battle_timer.turn_seconds", before.battle_timer.turn_seconds, after.battle_timer.turn_seconds),
        (
            "battle_timer.selection_seconds",
            before.battle_timer.selection_seconds,
            after.battle_timer.selection_seconds,
        ),
        (
            "target_pool.expected_member_count",
            before_pool.expected_member_count,
            after_pool.expected_member_count,
        ),
    )
    for field, old, new in scalar_fields:
        if old != new:
            changes.append(FieldChange(field, old, new))
    before_mechanics = set(before_coverage.required_mechanics)
    after_mechanics = set(after_coverage.required_mechanics)
    before_pokemon = {item.target_key for item in before_pool.members}
    after_pokemon = {item.target_key for item in after_pool.members}
    before_blockers = set(before_coverage.blocking_reasons)
    after_blockers = set(after_coverage.blocking_reasons)
    added_blockers = tuple(sorted(after_blockers - before_blockers))
    resolved_blockers = tuple(sorted(before_blockers - after_blockers))
    source_ids = tuple(
        sorted(
            {
                *before_coverage.source_manifest_ids,
                *after_coverage.source_manifest_ids,
            }
        )
    )
    return RegulationDiffBundle(
        schema_version=REGULATION_DIFF_SCHEMA_VERSION,
        diff_id=f"diff:{before.regulation_id}:{before.revision}..{after.regulation_id}:{after.revision}",
        before=_snapshot_reference(before_bundle, before_coverage),
        after=_snapshot_reference(after_bundle, after_coverage),
        changed_fields=tuple(changes),
        added_mechanics=tuple(sorted(after_mechanics - before_mechanics)),
        removed_mechanics=tuple(sorted(before_mechanics - after_mechanics)),
        added_target_keys=tuple(sorted(after_pokemon - before_pokemon)),
        removed_target_keys=tuple(sorted(before_pokemon - after_pokemon)),
        added_blocking_reasons=added_blockers,
        resolved_blocking_reasons=resolved_blockers,
        requires_simulator_update=bool(
            changes
            or after_mechanics - before_mechanics
            or after_pokemon - before_pokemon
            or added_blockers
        ),
        source_manifest_ids=source_ids,
    )


def build_regulation_rehearsal_report(
    *,
    report_id: str,
    rehearsal_kind: str,
    t0: str,
    t_decision: str,
    before_bundle: RegulationDataBundle,
    after_bundle: RegulationDataBundle,
    before_coverage: CoverageGapReport,
    after_coverage: CoverageGapReport,
    diff: RegulationDiffBundle,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
    resources: RehearsalResources,
    silent_fallback_count: int,
    rehearsal_input_hash: str,
    report_source_manifest_ids: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
) -> RegulationRehearsalReport:
    """Issue a fail-closed NO-GO from sealed synthetic inputs.

    The SIM-02 vertical slice deliberately has no candidate-emission path.
    Candidate promotion requires the later capability/grounding gate rather
    than caller-supplied rates or hashes. Every supplied coverage/diff object
    is recomputed from the immutable bundle, catalog, and ruleset here.
    """

    if rehearsal_kind != "synthetic_internal":
        raise ValueError(
            "SIM-02 vertical slice only supports synthetic_internal NO-GO rehearsal"
        )
    start = _aware_datetime(t0, "t0")
    decision = _aware_datetime(t_decision, "t_decision")
    elapsed = int((decision - start).total_seconds())
    if elapsed < 0:
        raise ValueError("t_decision must not precede t0")
    if silent_fallback_count < 0:
        raise ValueError("silent_fallback_count must be non-negative")
    if len(rehearsal_input_hash) != 64 or any(
        value not in "0123456789abcdef" for value in rehearsal_input_hash
    ):
        raise ValueError("rehearsal_input_hash must be a lowercase SHA-256 digest")
    expected_before_coverage = build_coverage_gap_report(
        before_bundle, catalog, ruleset
    )
    expected_after_coverage = build_coverage_gap_report(
        after_bundle, catalog, ruleset
    )
    if before_coverage != expected_before_coverage:
        raise ValueError("before coverage report does not match recomputed inputs")
    if after_coverage != expected_after_coverage:
        raise ValueError("after coverage report does not match recomputed inputs")
    expected_diff = diff_regulation_bundles(
        before_bundle,
        after_bundle,
        expected_before_coverage,
        expected_after_coverage,
    )
    if diff != expected_diff:
        raise ValueError("regulation diff does not match recomputed inputs")

    reasons: list[str] = list(expected_after_coverage.blocking_reasons)
    if silent_fallback_count:
        reasons.append(f"silent_fallback_count:{silent_fallback_count}")
    reasons.extend(
        (
            "target_pool_execution_coverage_unmeasured",
            "verified_grounding_conformance_unmeasured",
            "synthetic_input_not_deployable",
        )
    )
    within_sla = elapsed <= _REHEARSAL_SLA_SECONDS
    operational_success = within_sla and bool(reasons)
    sealed = (
        SealedInputHash("before_regulation", before_bundle.regulation.snapshot_hash),
        SealedInputHash("before_target_pool", before_bundle.target_pool.snapshot_hash),
        SealedInputHash("after_regulation", after_bundle.regulation.snapshot_hash),
        SealedInputHash("after_target_pool", after_bundle.target_pool.snapshot_hash),
        SealedInputHash("after_coverage_report", after_coverage.report_hash),
        SealedInputHash("catalog", after_coverage.catalog_hash),
        SealedInputHash("ruleset", after_coverage.ruleset_hash),
        SealedInputHash("regulation_diff", diff.diff_hash),
        SealedInputHash("rehearsal_input", rehearsal_input_hash),
    )
    return RegulationRehearsalReport(
        schema_version=REHEARSAL_REPORT_SCHEMA_VERSION,
        report_id=report_id,
        rehearsal_kind=rehearsal_kind,
        outcome="no_go",
        t0=t0,
        t_decision=t_decision,
        decision_lead_time_seconds=elapsed,
        within_48_hours=within_sla,
        provisional_decision_ids=("PD-008",),
        sealed_input_hashes=sealed,
        source_manifest_ids=tuple(
            sorted(
                {
                    *before_bundle.regulation.source_manifest_ids,
                    *diff.source_manifest_ids,
                    *report_source_manifest_ids,
                }
            )
        ),
        resources=resources,
        coverage_report_hash=after_coverage.report_hash,
        regulation_diff_hash=diff.diff_hash,
        target_pool_execution_coverage_rate_ppm=None,
        verified_grounding_conformance_rate_ppm=None,
        silent_fallback_count=silent_fallback_count,
        candidate_bundle_hash=None,
        no_go_reason_codes=tuple(sorted(set(reasons))),
        operational_rehearsal_success=operational_success,
        deployable_candidate_success=False,
        notes=notes,
    )


def _validate_report_boundary(
    bundle: RegulationDataBundle,
    report: CoverageGapReport,
    label: str,
) -> None:
    if report.regulation_id != bundle.regulation.regulation_id:
        raise ValueError(f"{label} coverage regulation_id mismatch")
    if report.regulation_revision != bundle.regulation.revision:
        raise ValueError(f"{label} coverage regulation_revision mismatch")
    if report.regulation_hash != bundle.regulation.snapshot_hash:
        raise ValueError(f"{label} coverage regulation_hash mismatch")
    if report.target_pool_id != bundle.target_pool.target_pool_id:
        raise ValueError(f"{label} coverage target_pool_id mismatch")
    if report.target_pool_hash != bundle.target_pool.snapshot_hash:
        raise ValueError(f"{label} coverage target_pool_hash mismatch")


def _snapshot_reference(
    bundle: RegulationDataBundle,
    report: CoverageGapReport,
) -> SnapshotReference:
    return SnapshotReference(
        regulation_id=bundle.regulation.regulation_id,
        regulation_revision=bundle.regulation.revision,
        regulation_hash=bundle.regulation.snapshot_hash,
        target_pool_id=bundle.target_pool.target_pool_id,
        target_pool_hash=bundle.target_pool.snapshot_hash,
        coverage_report_hash=report.report_hash,
    )


def _aware_datetime(value: str, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO datetime") from error
    if result.tzinfo is None:
        raise ValueError(f"{label} must include a timezone offset")
    return result
