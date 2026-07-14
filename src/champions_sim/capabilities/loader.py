"""Strict JSON intake for construction and explicit mapping evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from champions_sim.core import canonical_hash

from .models import (
    ArtifactRecordRef,
    CapabilitySignature,
    ConformanceCheckRef,
    ConstructionRecord,
    ConstructionSelectionCorpus,
    ContextAtom,
    GroundingAssertion,
    GroundingAssertionSet,
    MappingEntry,
    MappingEvidenceSet,
    MappingResolutionStatus,
    ObservationStatus,
    ObservedEntity,
    SCHEMA_VERSION,
    StateCheck,
    VerificationStatus,
)


class CapabilityDataError(ValueError):
    pass


def load_construction_selection_corpus(
    path: Path | str,
) -> ConstructionSelectionCorpus:
    raw = _read_object(path, "construction-selection corpus")
    _exact(
        raw,
        {
            "schema_version",
            "corpus_id",
            "corpus_role",
            "regulation_id",
            "regulation_revision",
            "regulation_hash",
            "capture_window_start",
            "capture_window_end",
            "records",
            "evidence_refs",
            "source_manifest_ids",
        },
        "construction-selection corpus",
    )
    if raw["schema_version"] != SCHEMA_VERSION:
        raise CapabilityDataError("unsupported construction corpus schema_version")
    evidence = tuple(_artifact_ref(value, index) for index, value in enumerate(_list(raw["evidence_refs"], "evidence_refs")))
    records = tuple(
        _construction_record(value, index)
        for index, value in enumerate(_list(raw["records"], "records"))
    )
    return ConstructionSelectionCorpus(
        schema_version=SCHEMA_VERSION,
        corpus_id=str(raw["corpus_id"]),
        corpus_role=str(raw["corpus_role"]),
        regulation_id=str(raw["regulation_id"]),
        regulation_revision=str(raw["regulation_revision"]),
        regulation_hash=str(raw["regulation_hash"]),
        capture_window_start=str(raw["capture_window_start"]),
        capture_window_end=str(raw["capture_window_end"]),
        records=records,
        evidence_refs=evidence,
        source_manifest_ids=tuple(str(value) for value in _list(raw["source_manifest_ids"], "source_manifest_ids")),
    )


def load_mapping_evidence_set(path: Path | str) -> MappingEvidenceSet:
    raw = _read_object(path, "mapping evidence")
    _exact(
        raw,
        {
            "schema_version",
            "mapping_set_id",
            "target_pool_hash",
            "catalog_hash",
            "entries",
            "evidence_refs",
            "source_manifest_ids",
        },
        "mapping evidence",
    )
    if raw["schema_version"] != SCHEMA_VERSION:
        raise CapabilityDataError("unsupported mapping evidence schema_version")
    evidence = tuple(
        _artifact_ref(value, index)
        for index, value in enumerate(_list(raw["evidence_refs"], "evidence_refs"))
    )
    entries = []
    for index, value in enumerate(_list(raw["entries"], "entries")):
        item = _object(value, f"entries[{index}]")
        _exact(
            item,
            {
                "target_key",
                "catalog_pokemon_id",
                "resolution_status",
                "verification_status",
                "mapping_method",
                "candidate_pokemon_ids",
                "evidence_ref_ids",
            },
            f"entries[{index}]",
        )
        entries.append(
            MappingEntry(
                target_key=str(item["target_key"]),
                catalog_pokemon_id=(
                    str(item["catalog_pokemon_id"])
                    if item["catalog_pokemon_id"] is not None
                    else None
                ),
                resolution_status=MappingResolutionStatus(str(item["resolution_status"])),
                verification_status=VerificationStatus(str(item["verification_status"])),
                mapping_method=str(item["mapping_method"]),
                candidate_pokemon_ids=tuple(
                    str(value)
                    for value in _list(item["candidate_pokemon_ids"], "candidate_pokemon_ids")
                ),
                evidence_ref_ids=tuple(
                    str(value)
                    for value in _list(item["evidence_ref_ids"], "evidence_ref_ids")
                ),
            )
        )
    return MappingEvidenceSet(
        mapping_set_id=str(raw["mapping_set_id"]),
        target_pool_hash=str(raw["target_pool_hash"]),
        catalog_hash=str(raw["catalog_hash"]),
        entries=tuple(entries),
        evidence_refs=evidence,
        source_manifest_ids=tuple(
            str(value)
            for value in _list(raw["source_manifest_ids"], "source_manifest_ids")
        ),
    )


def load_grounding_assertion_set(path: Path | str) -> GroundingAssertionSet:
    """Load the exact grounding-assertion contract from UTF-8 JSON.

    This loader intentionally preserves the distinction between a raw claimed
    verdict and a resolver-validated assertion set.  Callers must still pass the
    result through ``resolve_grounding_assertions``.
    """

    raw = _read_object(path, "grounding assertion set")
    _exact(
        raw,
        {
            "schema_version",
            "assertion_set_id",
            "target_capability_set_id",
            "target_capability_set_hash",
            "assertions",
            "source_manifest_ids",
        },
        "grounding assertion set",
    )
    if raw["schema_version"] != SCHEMA_VERSION:
        raise CapabilityDataError("unsupported grounding assertion schema_version")
    assertions: list[GroundingAssertion] = []
    for index, value in enumerate(_list(raw["assertions"], "assertions")):
        label = f"assertions[{index}]"
        item = _object(value, label)
        _exact(
            item,
            {
                "assertion_id",
                "requirement_ids",
                "capability_ids",
                "evidence_kind",
                "ruleset_id",
                "ruleset_hash",
                "catalog_hash",
                "trace_id",
                "trace_hash",
                "reference_replay_hash",
                "initial_state_hash",
                "choice_sequence_hash",
                "rng_condition_id",
                "expected_event_slice_hash",
                "expected_state_checks",
                "conformance_check_refs",
                "evidence_ref_ids",
                "claimed_verdict",
            },
            label,
        )
        state_checks: list[StateCheck] = []
        for check_index, raw_check in enumerate(
            _list(item["expected_state_checks"], f"{label}.expected_state_checks")
        ):
            check_label = f"{label}.expected_state_checks[{check_index}]"
            check = _object(raw_check, check_label)
            _exact(check, {"path", "expected"}, check_label)
            try:
                state_checks.append(
                    StateCheck(
                        path=_string(check["path"], f"{check_label}.path"),
                        expected=_json_value(check["expected"], f"{check_label}.expected"),
                    )
                )
            except ValueError as error:
                raise CapabilityDataError(f"invalid {check_label}") from error
        conformance_refs: list[ConformanceCheckRef] = []
        for check_index, raw_check in enumerate(
            _list(item["conformance_check_refs"], f"{label}.conformance_check_refs")
        ):
            check_label = f"{label}.conformance_check_refs[{check_index}]"
            check = _object(raw_check, check_label)
            _exact(check, {"frame_id", "path"}, check_label)
            try:
                conformance_refs.append(
                    ConformanceCheckRef(
                        frame_id=_string(check["frame_id"], f"{check_label}.frame_id"),
                        path=_string(check["path"], f"{check_label}.path"),
                    )
                )
            except ValueError as error:
                raise CapabilityDataError(f"invalid {check_label}") from error
        try:
            assertions.append(
                GroundingAssertion(
                    assertion_id=_string(item["assertion_id"], f"{label}.assertion_id"),
                    requirement_ids=_string_tuple(item["requirement_ids"], f"{label}.requirement_ids"),
                    capability_ids=_string_tuple(item["capability_ids"], f"{label}.capability_ids"),
                    evidence_kind=_string(item["evidence_kind"], f"{label}.evidence_kind"),
                    ruleset_id=_string(item["ruleset_id"], f"{label}.ruleset_id"),
                    ruleset_hash=_string(item["ruleset_hash"], f"{label}.ruleset_hash"),
                    catalog_hash=_string(item["catalog_hash"], f"{label}.catalog_hash"),
                    trace_id=_nullable_string(item["trace_id"], f"{label}.trace_id"),
                    trace_hash=_nullable_string(item["trace_hash"], f"{label}.trace_hash"),
                    reference_replay_hash=_nullable_string(
                        item["reference_replay_hash"], f"{label}.reference_replay_hash"
                    ),
                    initial_state_hash=_nullable_string(
                        item["initial_state_hash"], f"{label}.initial_state_hash"
                    ),
                    choice_sequence_hash=_nullable_string(
                        item["choice_sequence_hash"], f"{label}.choice_sequence_hash"
                    ),
                    rng_condition_id=_string(
                        item["rng_condition_id"], f"{label}.rng_condition_id"
                    ),
                    expected_event_slice_hash=_nullable_string(
                        item["expected_event_slice_hash"],
                        f"{label}.expected_event_slice_hash",
                    ),
                    expected_state_checks=tuple(state_checks),
                    conformance_check_refs=tuple(conformance_refs),
                    evidence_ref_ids=_string_tuple(
                        item["evidence_ref_ids"], f"{label}.evidence_ref_ids"
                    ),
                    claimed_verdict=_string(
                        item["claimed_verdict"], f"{label}.claimed_verdict"
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise CapabilityDataError(f"invalid {label}") from error
    try:
        return GroundingAssertionSet(
            schema_version=SCHEMA_VERSION,
            assertion_set_id=_string(raw["assertion_set_id"], "assertion_set_id"),
            target_capability_set_id=_string(
                raw["target_capability_set_id"], "target_capability_set_id"
            ),
            target_capability_set_hash=_string(
                raw["target_capability_set_hash"], "target_capability_set_hash"
            ),
            assertions=tuple(assertions),
            source_manifest_ids=_string_tuple(
                raw["source_manifest_ids"], "source_manifest_ids"
            ),
        )
    except (TypeError, ValueError) as error:
        raise CapabilityDataError("invalid grounding assertion set") from error
def _construction_record(value: Any, index: int) -> ConstructionRecord:
    item = _object(value, f"records[{index}]")
    _exact(
        item,
        {
            "record_id",
            "record_kind",
            "observed_at",
            "regulation_id",
            "joint_group_id",
            "target_key",
            "entities",
            "observed_capabilities",
            "source_complete",
            "evidence_ref_ids",
            "blockers",
            "record_hash",
        },
        f"records[{index}]",
    )
    entities = []
    for entity_index, raw_entity in enumerate(_list(item["entities"], "entities")):
        entity = _object(raw_entity, f"records[{index}].entities[{entity_index}]")
        _exact(
            entity,
            {"field", "entity_id", "status", "rate_ppm", "rank", "evidence_ref_ids"},
            f"records[{index}].entities[{entity_index}]",
        )
        entities.append(
            ObservedEntity(
                field=str(entity["field"]),
                entity_id=str(entity["entity_id"]) if entity["entity_id"] is not None else None,
                status=ObservationStatus(str(entity["status"])),
                rate_ppm=int(entity["rate_ppm"]) if entity["rate_ppm"] is not None else None,
                rank=int(entity["rank"]) if entity["rank"] is not None else None,
                evidence_ref_ids=tuple(str(value) for value in _list(entity["evidence_ref_ids"], "evidence_ref_ids")),
            )
        )
    capabilities = tuple(
        _capability_signature(value, f"records[{index}].observed_capabilities")
        for value in _list(item["observed_capabilities"], "observed_capabilities")
    )
    canonical_payload = {key: value for key, value in item.items() if key != "record_hash"}
    expected_hash = canonical_hash(canonical_payload)
    if item["record_hash"] != expected_hash:
        raise CapabilityDataError(f"records[{index}] record_hash mismatch")
    return ConstructionRecord(
        record_id=str(item["record_id"]),
        record_kind=str(item["record_kind"]),
        observed_at=str(item["observed_at"]) if item["observed_at"] is not None else None,
        regulation_id=str(item["regulation_id"]),
        joint_group_id=str(item["joint_group_id"]) if item["joint_group_id"] is not None else None,
        target_key=str(item["target_key"]) if item["target_key"] is not None else None,
        entities=tuple(entities),
        observed_capabilities=capabilities,
        source_complete=bool(item["source_complete"]),
        evidence_ref_ids=tuple(str(value) for value in _list(item["evidence_ref_ids"], "evidence_ref_ids")),
        blockers=tuple(str(value) for value in _list(item["blockers"], "blockers")),
        record_hash=str(item["record_hash"]),
    )


def _capability_signature(value: Any, label: str) -> CapabilitySignature:
    item = _object(value, label)
    _exact(item, {"effect_id", "trigger", "target", "resolution_context", "ruleset_branch"}, label)
    context = []
    for index, raw_atom in enumerate(_list(item["resolution_context"], "resolution_context")):
        atom = _object(raw_atom, f"{label}.resolution_context[{index}]")
        _exact(atom, {"key", "value"}, f"{label}.resolution_context[{index}]")
        if isinstance(atom["value"], (list, dict, float)):
            raise CapabilityDataError("context atom values must be scalar")
        context.append(ContextAtom(str(atom["key"]), atom["value"]))
    return CapabilitySignature(
        effect_id=str(item["effect_id"]),
        trigger=str(item["trigger"]),
        target=str(item["target"]),
        resolution_context=tuple(context),
        ruleset_branch=str(item["ruleset_branch"]),
    )


def _artifact_ref(value: Any, index: int) -> ArtifactRecordRef:
    item = _object(value, f"evidence_refs[{index}]")
    _exact(item, {"evidence_ref_id", "source_manifest_id", "artifact_id", "json_pointer", "record_sha256"}, f"evidence_refs[{index}]")
    return ArtifactRecordRef(
        evidence_ref_id=str(item["evidence_ref_id"]),
        source_manifest_id=str(item["source_manifest_id"]),
        artifact_id=str(item["artifact_id"]),
        json_pointer=str(item["json_pointer"]),
        record_sha256=str(item["record_sha256"]),
    )


def _read_object(path: Path | str, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_non_finite,
            parse_float=_finite_float,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, OverflowError) as error:
        raise CapabilityDataError(f"invalid UTF-8 JSON for {label}") from error
    return _object(raw, label)


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CapabilityDataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str):
    raise CapabilityDataError(f"non-finite JSON number is forbidden: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise CapabilityDataError(f"non-finite JSON number is forbidden: {value}")
    return parsed


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityDataError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CapabilityDataError(f"{label} must be an array")
    return value


def _exact(raw: dict[str, Any], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise CapabilityDataError(
            f"{label} fields differ; missing={sorted(expected - set(raw))}, extra={sorted(set(raw) - expected)}"
        )


def _json_value(value: Any, label: str):
    if value is None or type(value) in {str, bool, int}:
        return value
    if isinstance(value, list):
        return tuple(_json_value(item, f"{label}[]") for item in value)
    if isinstance(value, dict):
        return {str(key): _json_value(item, f"{label}.{key}") for key, item in value.items()}
    raise CapabilityDataError(f"{label} must be canonical JSON without floats")


def _string(value: Any, label: str) -> str:
    if type(value) is not str:
        raise CapabilityDataError(f"{label} must be a string")
    return value


def _nullable_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{label}[{index}]")
        for index, item in enumerate(_list(value, label))
    )
