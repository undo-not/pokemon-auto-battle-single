"""Fail-closed bridge from local CatalogIntake to capability/Catalog inputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
import unicodedata

from champions_sim.capabilities import (
    ArtifactRecordRef,
    MappingEntry,
    MappingEvidenceSet,
    MappingResolutionStatus,
    VerificationStatus,
)
from champions_sim.intake import CatalogIntakeBundle
from champions_sim.intake.models import canonical_sha256

from .bridge_models import (
    CatalogBridgeResult,
    CatalogCompilerError,
    ProductionCatalogInput,
    ProductionCatalogRecord,
    ProductionMemberBinding,
)


@dataclass(frozen=True, slots=True)
class CatalogBridgeProfile:
    profile_id: str = "official_m_b_source_bound_v1"
    regulation_id: str = "M-B"
    regulation_revision: str = "official-2026-06-17"
    expected_target_count: int = 235
    source_manifest_id: str = "catalog-intake-local-unverified"
    engine_semantics_version: str = "sim-core-0.1"

    def __post_init__(self) -> None:
        if self.expected_target_count <= 0:
            raise CatalogCompilerError("bridge target count must be positive")


@dataclass(frozen=True, slots=True)
class _Source:
    artifact_id: str
    data: dict[str, Any]
    sha256: str
    byte_count: int
    record_count: int


def compile_catalog_bridge(
    intake: CatalogIntakeBundle,
    *,
    repository_root: Path | str,
    legacy_root: Path | str,
    profile: CatalogBridgeProfile = CatalogBridgeProfile(),
) -> CatalogBridgeResult:
    """Compile only explicit source bindings; no member becomes verified/resolved.

    The produced runtime Catalog is structurally loadable, but every legacy
    effect is explicit ``unsupported`` and every source move keeps unknown
    priority as ``null``.  It therefore cannot reach move ordering.
    """

    _validate_intake_identity(intake, profile)
    sources = _resolve_sources(
        intake,
        repository_root=Path(repository_root).resolve(),
        legacy_root=Path(legacy_root).resolve(),
    )
    official_keys = _official_target_keys(sources["official_target_pool"].data)
    intake_keys = tuple(value.target_key for value in intake.members)
    if len(official_keys) != profile.expected_target_count:
        raise CatalogCompilerError("official target count differs from bridge profile")
    if tuple(sorted(official_keys)) != tuple(sorted(intake_keys)):
        missing = sorted(set(official_keys) - set(intake_keys))
        extra = sorted(set(intake_keys) - set(official_keys))
        raise CatalogCompilerError(
            f"intake must cover exact official target keys; missing={missing}; extra={extra}"
        )
    if canonical_sha256(tuple(sorted(official_keys))) != intake.target_key_sha256:
        raise CatalogCompilerError("intake target-key hash does not match official target keys")

    indexes = _source_indexes(sources)
    evidence: dict[str, ArtifactRecordRef] = {}

    def reference(artifact_id: str, source_key: str) -> ArtifactRecordRef:
        try:
            record, pointer = indexes[artifact_id][source_key]
        except KeyError as error:
            raise CatalogCompilerError(
                f"source record is missing: {artifact_id}:{source_key}"
            ) from error
        record_hash = canonical_sha256(record)
        ref_id = "ev-" + canonical_sha256(
            (artifact_id, pointer, record_hash, profile.source_manifest_id)
        )[:40]
        value = ArtifactRecordRef(
            ref_id,
            profile.source_manifest_id,
            artifact_id,
            pointer,
            record_hash,
        )
        previous = evidence.get(ref_id)
        if previous is not None and previous != value:
            raise CatalogCompilerError("evidence reference hash collision")
        evidence[ref_id] = value
        return value

    conflicts = {value.target_key: value for value in intake.usage_detail_conflicts}
    mapping_entries: list[MappingEntry] = []
    member_bindings: list[ProductionMemberBinding] = []
    blockers: set[str] = {
        f"intake:{value.code}:{value.subject}" for value in intake.blockers
    }
    for member in sorted(intake.members, key=lambda value: value.target_key):
        mapping_refs: list[str] = []
        candidates = tuple(member.evidence.candidate_pokemon_ids)
        mapping_method = _mapping_method(member.mapping_status, member.evidence.matched_by)
        resolution = MappingResolutionStatus.UNRESOLVED

        if member.mapping_status == "usage_crosswalk":
            source = reference("pokemon_usage", member.evidence.source_record_key)
            mapping_refs.append(source.evidence_ref_id)
            raw = indexes["pokemon_usage"][member.evidence.source_record_key][0]
            selected = _required_string(raw, "pokemon_id", "pokemon_usage")
            if selected != member.selected_pokemon_id or candidates != (selected,):
                raise CatalogCompilerError("usage crosswalk changed after intake sealing")
            if _required_string(raw, "matched_by", "pokemon_usage") != member.evidence.matched_by:
                raise CatalogCompilerError("usage matched_by changed after intake sealing")
            diagnostic = conflicts.get(member.target_key)
            if diagnostic is not None:
                if "pokemon_usage_details" not in indexes:
                    raise CatalogCompilerError("sealed usage-detail conflict has no source")
                diagnostic_ref = reference(
                    "pokemon_usage_details", diagnostic.pokedb_pokemon_id
                )
                mapping_refs.append(diagnostic_ref.evidence_ref_id)
                candidates = tuple(
                    sorted(
                        {
                            diagnostic.selected_pokemon_id,
                            diagnostic.diagnostic_pokemon_id,
                        }
                    )
                )
                resolution = MappingResolutionStatus.CONFLICT
                blockers.add(f"mapping_conflict:{member.target_key}")
            else:
                blockers.add(f"mapping_unresolved:{member.target_key}:usage_crosswalk")
        elif member.mapping_status in {"exact_name_candidate", "ambiguous_name"}:
            matching = indexes["pokemon_catalog_name"].get(
                member.evidence.source_record_key, ()
            )
            actual_candidates = tuple(
                sorted(_required_string(value[0], "pokemon_id", "pokemon_catalog") for value in matching)
            )
            if actual_candidates != tuple(sorted(candidates)):
                raise CatalogCompilerError("catalog name candidates changed after intake sealing")
            for record, _ in matching:
                candidate_id = _required_string(record, "pokemon_id", "pokemon_catalog")
                mapping_refs.append(
                    reference("pokemon_catalog", candidate_id).evidence_ref_id
                )
            if member.mapping_status == "ambiguous_name":
                resolution = MappingResolutionStatus.CONFLICT
                blockers.add(f"mapping_conflict:{member.target_key}")
            else:
                blockers.add(f"mapping_unresolved:{member.target_key}:exact_name_candidate")
        elif member.mapping_status == "unmapped":
            if candidates:
                raise CatalogCompilerError("unmapped intake member cannot carry candidates")
            blockers.add(f"mapping_unresolved:{member.target_key}:no_candidate")
        else:
            raise CatalogCompilerError(
                f"unsupported intake mapping_status: {member.mapping_status}"
            )

        detail_ref_id: str | None = None
        if member.detail_status == "available":
            if member.selected_pokemon_id is None:
                raise CatalogCompilerError("available detail has no selected source candidate")
            detail_ref = reference("pokemon", member.selected_pokemon_id)
            if detail_ref.record_sha256 != member.detail_record_sha256:
                raise CatalogCompilerError("pokemon detail record hash differs from intake")
            detail_ref_id = detail_ref.evidence_ref_id
        elif member.detail_status != "missing":
            raise CatalogCompilerError("unsupported intake detail_status")

        entry = MappingEntry(
            target_key=member.target_key,
            catalog_pokemon_id=None,
            resolution_status=resolution,
            verification_status=VerificationStatus.UNVERIFIED,
            mapping_method=mapping_method,
            candidate_pokemon_ids=candidates,
            evidence_ref_ids=tuple(sorted(set(mapping_refs))),
        )
        mapping_entries.append(entry)
        member_bindings.append(
            ProductionMemberBinding(
                target_key=member.target_key,
                catalog_pokemon_id=None,
                candidate_pokemon_ids=candidates,
                resolution_status=resolution.value,
                verification_status=VerificationStatus.UNVERIFIED,
                mapping_method=mapping_method,
                mapping_evidence_ref_ids=entry.evidence_ref_ids,
                detail_evidence_ref_id=detail_ref_id,
            )
        )
        blockers.add(f"mapping_not_verified:{member.target_key}:unverified")

    records: list[ProductionCatalogRecord] = []
    for union in intake.entity_unions:
        hashes = {value.entity_id: value.canonical_sha256 for value in union.record_hashes}
        artifact_id = _entity_artifact_id(union.entity_kind)
        for entity_id in union.ids:
            if entity_id in hashes:
                source_ref = reference(artifact_id, entity_id)
                if source_ref.record_sha256 != hashes[entity_id]:
                    raise CatalogCompilerError(
                        f"entity record hash differs from intake: {union.entity_kind}:{entity_id}"
                    )
                status = "source_bound"
            else:
                if entity_id not in union.missing_record_ids:
                    raise CatalogCompilerError("entity union omits record hash without missing marker")
                source_ref = None
                status = "missing"
                blockers.add(f"catalog_record_missing:{union.entity_kind}:{entity_id}")
            records.append(
                ProductionCatalogRecord(
                    union.entity_kind,
                    entity_id,
                    status,
                    VerificationStatus.UNVERIFIED,
                    source_ref,
                )
            )

    _add_semantic_blockers(sources, intake, blockers)
    runtime_catalog = _build_runtime_catalog(
        intake=intake,
        indexes=indexes,
        references=reference,
        type_effectiveness=sources["types"].data["effectiveness"],
        profile=profile,
    )
    runtime_catalog_hash = canonical_sha256(runtime_catalog)
    sorted_evidence = tuple(sorted(evidence.values(), key=lambda value: value.evidence_ref_id))
    sorted_records = tuple(
        sorted(records, key=lambda value: (value.entity_kind, value.entity_id))
    )
    catalog_input = ProductionCatalogInput(
        input_id=(
            f"production-catalog-input:{profile.regulation_id}:"
            f"{profile.regulation_revision}:{profile.profile_id}"
        ),
        intake_bundle_hash=intake.bundle_hash,
        regulation_id=profile.regulation_id,
        regulation_revision=profile.regulation_revision,
        target_pool_hash=intake.target_pool_sha256,
        target_key_hash=intake.target_key_sha256,
        runtime_catalog_hash=runtime_catalog_hash,
        target_member_count=len(member_bindings),
        members=tuple(member_bindings),
        records=sorted_records,
        evidence_refs=sorted_evidence,
        source_manifest_ids=(profile.source_manifest_id,),
        blockers=tuple(sorted(blockers)),
        denominator_final=False,
        catalog_emit_eligible=False,
    )
    mapping = MappingEvidenceSet(
        mapping_set_id=(
            f"mapping-intake:{profile.regulation_id}:"
            f"{profile.regulation_revision}:{profile.profile_id}"
        ),
        target_pool_hash=intake.target_pool_sha256,
        catalog_hash=runtime_catalog_hash,
        entries=tuple(mapping_entries),
        evidence_refs=sorted_evidence,
        source_manifest_ids=(profile.source_manifest_id,),
    )
    return CatalogBridgeResult(mapping, catalog_input, runtime_catalog)


def _validate_intake_identity(
    intake: CatalogIntakeBundle, profile: CatalogBridgeProfile
) -> None:
    if (
        intake.regulation_id != profile.regulation_id
        or intake.regulation_revision != profile.regulation_revision
    ):
        raise CatalogCompilerError("intake regulation identity differs from bridge profile")
    if intake.target_member_count != profile.expected_target_count:
        raise CatalogCompilerError("intake target count differs from bridge profile")
    if len(intake.members) != intake.target_member_count:
        raise CatalogCompilerError("intake target member count is internally inconsistent")
    for artifact in intake.artifacts:
        if (
            artifact.license_status != "unverified"
            or artifact.access_scope != "local_only"
            or artifact.redistribution != "prohibited"
        ):
            raise CatalogCompilerError(
                "compiler refuses to change intake license/local-only restrictions"
            )


def _resolve_sources(
    intake: CatalogIntakeBundle, *, repository_root: Path, legacy_root: Path
) -> dict[str, _Source]:
    roots = {"repository": repository_root, "legacy": legacy_root}
    result: dict[str, _Source] = {}
    for artifact in intake.artifacts:
        root = roots.get(artifact.root_kind)
        if root is None:
            raise CatalogCompilerError(f"unsupported artifact root kind: {artifact.root_kind}")
        relative = Path(artifact.relative_path)
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise CatalogCompilerError("unsafe source artifact path")
        source = (root / relative).resolve()
        try:
            source.relative_to(root)
        except ValueError as error:
            raise CatalogCompilerError("source artifact escapes declared root") from error
        if not source.is_file():
            raise CatalogCompilerError(f"source artifact is missing: {artifact.artifact_id}")
        payload = source.read_bytes()
        if len(payload) != artifact.byte_count:
            raise CatalogCompilerError(f"source byte-count drift: {artifact.artifact_id}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact.sha256:
            raise CatalogCompilerError(f"source hash drift: {artifact.artifact_id}")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CatalogCompilerError(f"invalid source JSON: {artifact.artifact_id}") from error
        if not isinstance(raw, dict):
            raise CatalogCompilerError("source artifact root must be an object")
        count = _source_count(artifact.artifact_id, raw)
        if count != artifact.record_count:
            raise CatalogCompilerError(f"source record-count drift: {artifact.artifact_id}")
        result[artifact.artifact_id] = _Source(
            artifact.artifact_id, raw, digest, len(payload), count
        )
    required = {
        "official_target_pool",
        "pokemon_usage",
        "pokemon_catalog",
        "pokemon",
        "moves",
        "abilities",
        "items",
        "types",
    }
    if not required <= set(result):
        raise CatalogCompilerError(
            f"intake source inventory is incomplete: {sorted(required - set(result))}"
        )
    return result


def _source_indexes(
    sources: Mapping[str, _Source],
) -> dict[str, dict[str, tuple[dict[str, Any], str]] | dict[str, tuple[tuple[dict[str, Any], str], ...]]]:
    result: dict[str, Any] = {}
    specs = {
        "pokemon_usage": ("items", "pokedb_pokemon_id"),
        "pokemon_catalog": ("items", "pokemon_id"),
        "pokemon": ("items", "pokemon_id"),
        "moves": ("items", "move_id"),
        "abilities": ("items", "ability_id"),
        "items": ("items", "item_id"),
        "types": ("types", "type_id"),
        "pokemon_usage_details": ("items", "pokedb_pokemon_id"),
    }
    for artifact_id, (array_name, key) in specs.items():
        if artifact_id not in sources:
            continue
        values = sources[artifact_id].data.get(array_name)
        if not isinstance(values, list):
            raise CatalogCompilerError(f"{artifact_id}.{array_name} must be an array")
        indexed: dict[str, tuple[dict[str, Any], str]] = {}
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                raise CatalogCompilerError(f"{artifact_id} record must be an object")
            source_key = str(value.get(key, ""))
            if not source_key or source_key in indexed:
                raise CatalogCompilerError(f"duplicate/missing source key: {artifact_id}:{source_key}")
            indexed[source_key] = (value, f"/{array_name}/{index}")
        result[artifact_id] = indexed

    by_name: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for record, pointer in result["pokemon_catalog"].values():
        name = _normalize_name(_required_string(record, "name", "pokemon_catalog"))
        by_name.setdefault(name, []).append((record, pointer))
    result["pokemon_catalog_name"] = {
        key: tuple(sorted(value, key=lambda item: str(item[0]["pokemon_id"])))
        for key, value in by_name.items()
    }
    return result


def _official_target_keys(raw: Mapping[str, Any]) -> tuple[str, ...]:
    members = raw.get("members")
    if not isinstance(members, list):
        raise CatalogCompilerError("official target members must be an array")
    keys: list[str] = []
    for value in members:
        if not isinstance(value, dict):
            raise CatalogCompilerError("official target member must be an object")
        try:
            key = (
                f"dex:{int(value['national_dex_no']):04d}:"
                f"form:{value['form_code']}:variant:{value['variant_code']}"
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CatalogCompilerError("invalid official target member") from error
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise CatalogCompilerError("official target keys are not unique")
    return tuple(keys)


def _build_runtime_catalog(
    *,
    intake: CatalogIntakeBundle,
    indexes: Mapping[str, Any],
    references: Callable[[str, str], ArtifactRecordRef],
    type_effectiveness: Any,
    profile: CatalogBridgeProfile,
) -> dict[str, Any]:
    union = {value.entity_kind: value for value in intake.entity_unions}
    type_ids = tuple(union["type"].ids)
    types = []
    for entity_id in type_ids:
        record = indexes["types"][entity_id][0]
        types.append(
            {
                "type_id": entity_id,
                "legacy_type_id": int(entity_id),
                "name": _required_string(record, "name", "types"),
            }
        )
    type_chart: dict[str, dict[str, int | float]] = {value: {} for value in type_ids}
    if not isinstance(type_effectiveness, list) or any(
        not isinstance(value, dict) for value in type_effectiveness
    ):
        raise CatalogCompilerError("type effectiveness source must be an object array")
    for row in type_effectiveness:
        attack = str(row["attack_type_id"])
        defense = str(row["defense_type_id"])
        if attack in type_chart and defense in set(type_ids):
            multiplier = row["multiplier"]
            if not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool):
                raise CatalogCompilerError("type multiplier must be numeric")
            type_chart[attack][defense] = multiplier

    moves = []
    categories = {"物理": "physical", "特殊": "special", "変化": "status"}
    for entity_id in union["move"].ids:
        record = indexes["moves"][entity_id][0]
        source_ref = references("moves", entity_id)
        category_name = _required_string(record, "category", "moves")
        if category_name not in categories:
            raise CatalogCompilerError(f"unknown move category: {category_name}")
        flags = record.get("flags")
        if not isinstance(flags, dict) or flags.get("direct_attack") not in {"接触", "×"}:
            raise CatalogCompilerError("move contact flag is not explicit")
        moves.append(
            {
                "move_id": entity_id,
                "legacy_move_id": int(entity_id),
                "name": _required_string(record, "name", "moves"),
                "type_id": str(record["type_id"]),
                "category": categories[category_name],
                "power": record.get("power"),
                "accuracy": record.get("accuracy"),
                "pp": int(record["pp"]),
                "priority": None,
                "contact": flags["direct_attack"] == "接触",
                "effect": {
                    "kind": "unsupported",
                    "source_record_sha256": source_ref.record_sha256,
                    "reason": "legacy_text_effect_not_semantically_compiled",
                },
            }
        )
    abilities = []
    for entity_id in union["ability"].ids:
        record = indexes["abilities"][entity_id][0]
        source_ref = references("abilities", entity_id)
        abilities.append(
            {
                "ability_id": entity_id,
                "legacy_ability_id": int(entity_id),
                "name": _required_string(record, "name", "abilities"),
                "effect_id": f"unsupported:ability:{entity_id}",
                "source_record_sha256": source_ref.record_sha256,
                "unsupported_reason": "legacy_text_effect_not_semantically_compiled",
            }
        )
    items = []
    for entity_id in union["item"].ids:
        record = indexes["items"][entity_id][0]
        source_ref = references("items", entity_id)
        items.append(
            {
                "item_id": entity_id,
                "legacy_item_id": int(entity_id),
                "name": _required_string(record, "name", "items"),
                "effect_id": f"unsupported:item:{entity_id}",
                "consumable": None,
                "source_record_sha256": source_ref.record_sha256,
                "unsupported_reason": "legacy_text_effect_not_semantically_compiled",
            }
        )
    species = []
    available_hashes = {
        value.entity_id: value.canonical_sha256
        for value in union["pokemon"].record_hashes
    }
    for entity_id in sorted(available_hashes):
        record = indexes["pokemon"][entity_id][0]
        source_ref = references("pokemon", entity_id)
        if source_ref.record_sha256 != available_hashes[entity_id]:
            raise CatalogCompilerError("runtime species record differs from intake")
        abilities_for_species = record.get("abilities")
        if not isinstance(abilities_for_species, list):
            raise CatalogCompilerError("pokemon abilities must be an array")
        species.append(
            {
                "pokemon_id": entity_id,
                "legacy_pokemon_id": entity_id,
                "name": _required_string(record, "name", "pokemon"),
                "types": [str(value) for value in record["type_ids"]],
                "ability_ids": [str(value["ability_id"]) for value in abilities_for_species],
                "legal_move_ids": [str(value) for value in record["move_ids"]],
            }
        )
    return {
        "schema_version": "1.0.0",
        "catalog_id": (
            f"champions-source-bound:{profile.regulation_id}:"
            f"{profile.regulation_revision}"
        ),
        "engine_semantics_version": profile.engine_semantics_version,
        "source_manifest_id": profile.source_manifest_id,
        "type_chart_default_multiplier": 1,
        "types": sorted(types, key=lambda value: value["type_id"]),
        "type_chart": {
            key: dict(sorted(value.items())) for key, value in sorted(type_chart.items())
        },
        "abilities": sorted(abilities, key=lambda value: value["ability_id"]),
        "items": sorted(items, key=lambda value: value["item_id"]),
        "moves": sorted(moves, key=lambda value: value["move_id"]),
        "species": sorted(species, key=lambda value: value["pokemon_id"]),
        "mega_evolutions": [],
    }


def _add_semantic_blockers(
    sources: Mapping[str, _Source],
    intake: CatalogIntakeBundle,
    blockers: set[str],
) -> None:
    moves = sources["moves"].data["items"]
    pokemon = sources["pokemon"].data["items"]
    priority_missing = sum("priority" not in value for value in moves)
    structured_missing = sum(not isinstance(value.get("effect"), dict) for value in moves)
    base_stats_missing = sum("base_stats" not in value for value in pokemon)
    mega_union = next(value for value in intake.entity_unions if value.entity_kind == "mega_pokemon")
    blockers.update(
        {
            f"source_priority_missing:{priority_missing}/{len(moves)}",
            f"source_structured_effect_missing:{structured_missing}/{len(moves)}",
            f"source_base_stats_missing:{base_stats_missing}/{len(pokemon)}",
            f"source_mega_stone_relations_missing:0/{len(mega_union.ids)}",
            "runtime_catalog_contains_explicit_unsupported_semantics",
        }
    )
    effectiveness = sources["types"].data.get("effectiveness")
    if not isinstance(effectiveness, list):
        raise CatalogCompilerError("types effectiveness must be an array")
    if any(not isinstance(value, dict) for value in effectiveness):
        raise CatalogCompilerError("types effectiveness records must be objects")


def _source_count(artifact_id: str, raw: Mapping[str, Any]) -> int:
    key = "members" if artifact_id == "official_target_pool" else (
        "types" if artifact_id == "types" else "items"
    )
    values = raw.get(key)
    if not isinstance(values, list):
        raise CatalogCompilerError(f"{artifact_id}.{key} must be an array")
    return len(values)


def _entity_artifact_id(entity_kind: str) -> str:
    return {
        "pokemon": "pokemon",
        "mega_pokemon": "pokemon",
        "move": "moves",
        "ability": "abilities",
        "item": "items",
        "type": "types",
    }[entity_kind]


def _mapping_method(mapping_status: str, matched_by: str) -> str:
    allowed = {
        ("usage_crosswalk", "name"): "intake.usage_crosswalk.name",
        ("usage_crosswalk", "pokedb_id_map"): "intake.usage_crosswalk.pokedb_id_map",
        (
            "exact_name_candidate",
            "normalized_official_name_exact",
        ): "intake.exact_name_candidate.normalized_official_name_exact",
        (
            "ambiguous_name",
            "ambiguous_normalized_official_name",
        ): "intake.ambiguous_name.normalized_official_name",
        ("unmapped", "no_match"): "intake.unmapped.no_match",
    }
    try:
        return allowed[(mapping_status, matched_by)]
    except KeyError as error:
        raise CatalogCompilerError(
            f"unsupported mapping evidence kind: {mapping_status}/{matched_by}"
        ) from error


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise CatalogCompilerError(f"{label}.{key} must be a non-empty string")
    return result
