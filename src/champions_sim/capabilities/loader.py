"""Strict JSON intake for construction and explicit mapping evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from champions_sim.core import canonical_hash

from .models import (
    ArtifactRecordRef,
    CapabilitySignature,
    ConstructionRecord,
    ConstructionSelectionCorpus,
    ContextAtom,
    MappingEntry,
    MappingEvidenceSet,
    MappingResolutionStatus,
    ObservationStatus,
    ObservedEntity,
    SCHEMA_VERSION,
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
    evidence = tuple(_artifact_ref(value, index) for index, value in enumerate(_list(raw["evidence_refs"], "evidence_refs")))
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
                candidate_pokemon_ids=tuple(str(value) for value in _list(item["candidate_pokemon_ids"], "candidate_pokemon_ids")),
                evidence_ref_ids=tuple(str(value) for value in _list(item["evidence_ref_ids"], "evidence_ref_ids")),
            )
        )
    return MappingEvidenceSet(
        mapping_set_id=str(raw["mapping_set_id"]),
        target_pool_hash=str(raw["target_pool_hash"]),
        catalog_hash=str(raw["catalog_hash"]),
        entries=tuple(entries),
        evidence_refs=evidence,
        source_manifest_ids=tuple(str(value) for value in _list(raw["source_manifest_ids"], "source_manifest_ids")),
    )


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
        raw = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapabilityDataError(f"invalid UTF-8 JSON for {label}") from error
    return _object(raw, label)


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CapabilityDataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


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
