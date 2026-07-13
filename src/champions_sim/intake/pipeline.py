"""Deterministic local catalog intake with explicit evidence and blockers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
import unicodedata

from .models import (
    ArtifactExpectation,
    ArtifactInventory,
    CatalogIntakeBundle,
    CatalogIntakeError,
    EntityRecordHash,
    EntityUnion,
    IntakeBlocker,
    MappingEvidence,
    MemberIntake,
    UsageDetailConflict,
    canonical_sha256,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OFFICIAL_LABEL = re.compile(r"^No\.(?P<dex>[0-9]{4})\s+(?P<name>.+)$")
_TARGET_KEYS = frozenset(
    {
        "schema_version",
        "regulation_id",
        "regulation_revision",
        "expected_member_count",
        "source_manifest_ids",
        "members",
    }
)
_TARGET_MEMBER_KEYS = frozenset(
    {"national_dex_no", "form_code", "variant_code", "label", "pokemon_id"}
)


@dataclass(frozen=True, slots=True)
class CatalogIntakePaths:
    target_pool: str = "data/fixtures/regulations/m-b-eligible-pokemon.json"
    pokemon_usage: str = "data/processed/pokemon_usage.json"
    pokemon_catalog: str = "data/processed/pokemon_catalog.json"
    pokemon: str = "data/processed/pokemon.json"
    moves: str = "data/processed/moves.json"
    abilities: str = "data/processed/abilities.json"
    items: str = "data/processed/items.json"
    types: str = "data/processed/types.json"
    usage_details: str = (
        "data/processed/pokemon_usage_details/season_2_rule_0.json"
    )


@dataclass(frozen=True, slots=True)
class CatalogIntakeProfile:
    profile_id: str = "official_m_b_legacy_m_a_v1"
    regulation_id: str = "M-B"
    regulation_revision: str = "official-2026-06-17"
    expected_target_count: int = 235
    expected_usage_count: int = 213

    def __post_init__(self) -> None:
        if self.expected_target_count <= 0 or self.expected_usage_count <= 0:
            raise CatalogIntakeError("profile counts must be positive")


@dataclass(frozen=True, slots=True)
class _LoadedArtifact:
    inventory: ArtifactInventory
    data: dict[str, Any]


def build_catalog_intake(
    *,
    repository_root: Path | str,
    legacy_root: Path | str,
    paths: CatalogIntakePaths = CatalogIntakePaths(),
    profile: CatalogIntakeProfile = CatalogIntakeProfile(),
    include_usage_details: bool = True,
    expected_inventory: Mapping[str, ArtifactExpectation] | None = None,
) -> CatalogIntakeBundle:
    """Build a sealed metadata-only bundle without copying source prose/effects."""

    repo = Path(repository_root).resolve()
    legacy = Path(legacy_root).resolve()
    if not repo.is_dir():
        raise CatalogIntakeError(f"repository root does not exist: {repo}")
    if not legacy.is_dir():
        raise CatalogIntakeError(f"legacy root does not exist: {legacy}")

    specs: list[tuple[str, str, str, Callable[[dict[str, Any]], int], bool]] = [
        ("official_target_pool", "repository", paths.target_pool, _target_count, False),
        ("pokemon_usage", "legacy", paths.pokemon_usage, _item_count, False),
        ("pokemon_catalog", "legacy", paths.pokemon_catalog, _item_count, False),
        ("pokemon", "legacy", paths.pokemon, _item_count, False),
        ("moves", "legacy", paths.moves, _item_count, False),
        ("abilities", "legacy", paths.abilities, _item_count, False),
        ("items", "legacy", paths.items, _item_count, False),
        ("types", "legacy", paths.types, _type_count, False),
    ]
    if include_usage_details:
        specs.append(
            (
                "pokemon_usage_details",
                "legacy",
                paths.usage_details,
                _item_count,
                True,
            )
        )

    loaded: dict[str, _LoadedArtifact] = {}
    for artifact_id, root_kind, relative_path, counter, optional in specs:
        root = repo if root_kind == "repository" else legacy
        value = _load_artifact(
            artifact_id=artifact_id,
            root_kind=root_kind,
            root=root,
            relative_path=relative_path,
            counter=counter,
            optional=optional,
        )
        if value is not None:
            loaded[artifact_id] = value
    _validate_expected_inventory(loaded, expected_inventory)

    target_raw = loaded["official_target_pool"].data
    target_members = _validate_target_pool(target_raw, profile)
    usage_items = _validate_dataset(
        loaded["pokemon_usage"].data,
        artifact_id="pokemon_usage",
        expected_count=profile.expected_usage_count,
    )
    catalog_items = _validate_dataset(
        loaded["pokemon_catalog"].data, artifact_id="pokemon_catalog"
    )
    pokemon_items = _validate_dataset(loaded["pokemon"].data, artifact_id="pokemon")
    move_items = _validate_dataset(loaded["moves"].data, artifact_id="moves")
    ability_items = _validate_dataset(
        loaded["abilities"].data, artifact_id="abilities"
    )
    item_items = _validate_dataset(loaded["items"].data, artifact_id="items")
    type_items = _validate_types(loaded["types"].data)
    _validate_parallel_ids(loaded["moves"].data, "move_ids", move_items, "move_id")
    _validate_parallel_ids(loaded["items"].data, "item_ids", item_items, "item_id")

    usage_by_source_key = _unique_index(
        usage_items, "pokedb_pokemon_id", "pokemon_usage"
    )
    catalog_by_id = _unique_index(catalog_items, "pokemon_id", "pokemon_catalog")
    pokemon_by_id = _unique_index(pokemon_items, "pokemon_id", "pokemon")
    moves_by_id = _unique_index(move_items, "move_id", "moves")
    abilities_by_id = _unique_index(ability_items, "ability_id", "abilities")
    items_by_id = _unique_index(item_items, "item_id", "items")
    types_by_id = _unique_index(type_items, "type_id", "types")
    catalog_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in catalog_items:
        catalog_by_name[_normalize_name(_required_string(item, "name", "pokemon_catalog"))].append(item)

    blockers: list[IntakeBlocker] = []
    members: list[MemberIntake] = []
    target_key_by_source_key: dict[str, str] = {}
    usage_selected_by_source_key: dict[str, tuple[str, str, str]] = {}
    for target in target_members:
        target_key = _target_key(target)
        source_key = f"{target['national_dex_no']:04d}-{target['form_code']}"
        official_name = _official_name(target)
        normalized_name = _normalize_name(official_name)
        usage = usage_by_source_key.get(source_key)
        if usage is not None:
            selected_id = _required_string(usage, "pokemon_id", "pokemon_usage")
            matched_by = _required_string(usage, "matched_by", "pokemon_usage")
            mapping_status = "usage_crosswalk"
            evidence = MappingEvidence(
                source_artifact_id="pokemon_usage",
                source_record_key=source_key,
                matched_by=matched_by,
                normalized_official_name=normalized_name,
                candidate_pokemon_ids=(selected_id,),
            )
            usage_selected_by_source_key[source_key] = (
                selected_id,
                matched_by,
                _required_string(usage, "name", "pokemon_usage"),
            )
            target_key_by_source_key[source_key] = target_key
        else:
            matches = sorted(
                catalog_by_name.get(normalized_name, ()),
                key=lambda value: str(value.get("pokemon_id", "")),
            )
            candidate_ids = tuple(
                _required_string(value, "pokemon_id", "pokemon_catalog")
                for value in matches
            )
            if len(candidate_ids) == 1:
                selected_id = candidate_ids[0]
                mapping_status = "exact_name_candidate"
                matched_by = "normalized_official_name_exact"
                blockers.append(
                    IntakeBlocker(
                        "mapping_candidate_unverified",
                        "target_member",
                        target_key,
                        f"catalog candidate {selected_id} lacks usage-listing crosswalk evidence",
                    )
                )
            elif not candidate_ids:
                selected_id = None
                mapping_status = "unmapped"
                matched_by = "no_match"
                blockers.append(
                    IntakeBlocker(
                        "target_mapping_missing",
                        "target_member",
                        target_key,
                        "no exact normalized catalog-name candidate",
                    )
                )
            else:
                selected_id = None
                mapping_status = "ambiguous_name"
                matched_by = "ambiguous_normalized_official_name"
                blockers.append(
                    IntakeBlocker(
                        "target_mapping_ambiguous",
                        "target_member",
                        target_key,
                        f"candidate IDs: {','.join(candidate_ids)}",
                    )
                )
            evidence = MappingEvidence(
                source_artifact_id="pokemon_catalog",
                source_record_key=normalized_name,
                matched_by=matched_by,
                normalized_official_name=normalized_name,
                candidate_pokemon_ids=candidate_ids,
            )

        detail = pokemon_by_id.get(selected_id) if selected_id is not None else None
        if detail is None:
            detail_status = "missing"
            detail_hash = None
            if selected_id is not None:
                blockers.append(
                    IntakeBlocker(
                        "pokemon_detail_missing",
                        "target_member",
                        target_key,
                        f"selected ID {selected_id} is absent from pokemon.json",
                    )
                )
        else:
            detail_status = "available"
            detail_hash = canonical_sha256(detail)
        members.append(
            MemberIntake(
                target_key=target_key,
                national_dex_no=target["national_dex_no"],
                form_code=target["form_code"],
                variant_code=target["variant_code"],
                label=target["label"],
                mapping_status=mapping_status,
                selected_pokemon_id=selected_id,
                evidence=evidence,
                detail_status=detail_status,
                detail_record_sha256=detail_hash,
            )
        )

    selected_id_to_targets: dict[str, list[str]] = defaultdict(list)
    for member in members:
        if member.selected_pokemon_id is not None:
            selected_id_to_targets[member.selected_pokemon_id].append(member.target_key)
    for selected_id, keys in selected_id_to_targets.items():
        if len(keys) > 1:
            blockers.append(
                IntakeBlocker(
                    "selected_pokemon_id_collision",
                    "mapping",
                    selected_id,
                    f"selected by target keys: {','.join(sorted(keys))}",
                )
            )

    conflicts: list[UsageDetailConflict] = []
    usage_detail_present = "pokemon_usage_details" in loaded
    if usage_detail_present:
        detail_items = _validate_dataset(
            loaded["pokemon_usage_details"].data,
            artifact_id="pokemon_usage_details",
            expected_count=profile.expected_usage_count,
        )
        diagnostic_by_source_key = _unique_index(
            detail_items, "pokedb_pokemon_id", "pokemon_usage_details"
        )
        for source_key, (selected_id, selected_matched_by, name) in sorted(
            usage_selected_by_source_key.items()
        ):
            diagnostic = diagnostic_by_source_key.get(source_key)
            if diagnostic is None:
                continue
            diagnostic_id = _required_string(
                diagnostic, "pokemon_id", "pokemon_usage_details"
            )
            if diagnostic_id != selected_id:
                conflict = UsageDetailConflict(
                    pokedb_pokemon_id=source_key,
                    target_key=target_key_by_source_key[source_key],
                    pokemon_name=name,
                    selected_pokemon_id=selected_id,
                    diagnostic_pokemon_id=diagnostic_id,
                    selected_matched_by=selected_matched_by,
                    diagnostic_matched_by=_required_string(
                        diagnostic, "matched_by", "pokemon_usage_details"
                    ),
                )
                conflicts.append(conflict)
                blockers.append(
                    IntakeBlocker(
                        "usage_detail_pokemon_id_conflict",
                        "diagnostic",
                        source_key,
                        f"selected={selected_id}; diagnostic={diagnostic_id}; diagnostic never overrides",
                    )
                )

    selected_ids = {
        member.selected_pokemon_id
        for member in members
        if member.selected_pokemon_id is not None
    }
    selected_details = [
        pokemon_by_id[value] for value in sorted(selected_ids) if value in pokemon_by_id
    ]
    # The legacy source contains 60 Mega records and two battle-only form
    # records in addition to the 213 M-A entries.  Inventory every declared
    # Mega target here so the known five missing raw records cannot disappear
    # merely because a particular base detail is outside the current join.
    mega_ids = {
        _entity_id(value)
        for detail in pokemon_items
        for value in _required_list(detail, "mega_evolution_ids", "pokemon")
    }
    move_ids = {
        _entity_id(value)
        for detail in selected_details
        for value in _required_list(detail, "move_ids", "pokemon")
    }
    ability_ids = {
        _entity_id(_required_field(value, "ability_id", "pokemon.abilities"))
        for detail in selected_details
        for value in _required_list(detail, "abilities", "pokemon")
        if isinstance(value, dict)
    }
    type_ids = {
        _entity_id(value)
        for detail in selected_details
        for value in _required_list(detail, "type_ids", "pokemon")
    }
    item_ids = {_entity_id(value) for value in items_by_id}

    entity_unions = (
        _entity_union(
            "pokemon",
            "selected_target_mapping_ids",
            selected_ids,
            pokemon_by_id,
            blockers,
        ),
        _entity_union(
            "mega_pokemon",
            "mega_evolution_ids_from_full_pokemon_source_inventory",
            mega_ids,
            pokemon_by_id,
            blockers,
        ),
        _entity_union(
            "move",
            "move_ids_from_available_target_details",
            move_ids,
            moves_by_id,
            blockers,
        ),
        _entity_union(
            "ability",
            "ability_ids_from_available_target_details",
            ability_ids,
            abilities_by_id,
            blockers,
        ),
        _entity_union(
            "item",
            "full_authoritative_item_source_inventory",
            item_ids,
            items_by_id,
            blockers,
        ),
        _entity_union(
            "type",
            "type_ids_from_available_target_details",
            type_ids,
            types_by_id,
            blockers,
        ),
    )

    with_base_stats = sum("base_stats" in value for value in pokemon_items)
    if with_base_stats != len(pokemon_items):
        blockers.append(
            IntakeBlocker(
                "pokemon_base_stats_absent",
                "source_inventory",
                "pokemon.json",
                f"base_stats present={with_base_stats}; total={len(pokemon_items)}",
            )
        )

    members.sort(key=lambda value: value.target_key)
    conflicts.sort(key=lambda value: value.pokedb_pokemon_id)
    blockers.sort(key=lambda value: (value.code, value.scope, value.subject, value.detail))
    artifacts = tuple(
        sorted((value.inventory for value in loaded.values()), key=lambda value: value.artifact_id)
    )
    mapping_counts = Counter(value.mapping_status for value in members)
    matched_by_counts = Counter(
        value.evidence.matched_by
        for value in members
        if value.mapping_status == "usage_crosswalk"
    )
    detail_counts = Counter(value.detail_status for value in members)
    summary: dict[str, Any] = {
        "artifact_count": len(artifacts),
        "mapping_counts": dict(sorted(mapping_counts.items())),
        "usage_matched_by_counts": dict(sorted(matched_by_counts.items())),
        "detail_counts": dict(sorted(detail_counts.items())),
        "usage_detail_conflict_count": len(conflicts),
        "entity_id_counts": {
            value.entity_kind: len(value.ids) for value in entity_unions
        },
        "entity_missing_record_counts": {
            value.entity_kind: len(value.missing_record_ids) for value in entity_unions
        },
        "blocker_count": len(blockers),
    }
    target_keys = tuple(value.target_key for value in members)
    return CatalogIntakeBundle(
        bundle_id=(
            f"catalog-intake:{profile.regulation_id}:{profile.regulation_revision}:"
            f"{profile.profile_id}"
        ),
        profile_id=profile.profile_id,
        regulation_id=profile.regulation_id,
        regulation_revision=profile.regulation_revision,
        target_pool_sha256=loaded["official_target_pool"].inventory.sha256,
        target_key_sha256=canonical_sha256(target_keys),
        target_member_count=len(target_keys),
        artifacts=artifacts,
        members=tuple(members),
        entity_unions=entity_unions,
        usage_detail_present=usage_detail_present,
        usage_detail_conflicts=tuple(conflicts),
        blockers=tuple(blockers),
        summary=summary,
    )


def load_source_lock(path: Path | str) -> dict[str, ArtifactExpectation]:
    """Load a strict local-only source inventory lock."""

    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CatalogIntakeError(f"source lock does not exist: {source}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogIntakeError(f"invalid source lock JSON: {source}") from error
    if not isinstance(raw, dict):
        raise CatalogIntakeError("source lock must be an object")
    expected_keys = {
        "schema_version",
        "manifest_id",
        "license_status",
        "access_scope",
        "redistribution",
        "artifacts",
    }
    _exact_keys(raw, expected_keys, "source lock")
    if raw["schema_version"] != "1.0.0":
        raise CatalogIntakeError("unsupported source-lock schema_version")
    if (
        raw["license_status"] != "unverified"
        or raw["access_scope"] != "local_only"
        or raw["redistribution"] != "prohibited"
    ):
        raise CatalogIntakeError("source lock must remain unverified/local-only/prohibited")
    artifacts = raw["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise CatalogIntakeError("source lock artifacts must be a non-empty array")
    result: dict[str, ArtifactExpectation] = {}
    keys = {
        "artifact_id",
        "root_kind",
        "relative_path",
        "sha256",
        "byte_count",
        "record_count",
    }
    for index, value in enumerate(artifacts):
        if not isinstance(value, dict):
            raise CatalogIntakeError(f"source lock artifacts[{index}] must be an object")
        _exact_keys(value, keys, f"source lock artifacts[{index}]")
        artifact_id = _required_string(value, "artifact_id", "source lock")
        if artifact_id in result:
            raise CatalogIntakeError(f"duplicate source-lock artifact_id: {artifact_id}")
        sha256 = _required_string(value, "sha256", "source lock")
        if not _SHA256.fullmatch(sha256):
            raise CatalogIntakeError("source-lock sha256 must be lowercase hexadecimal")
        byte_count = _positive_or_zero_int(value["byte_count"], "byte_count")
        record_count = _positive_or_zero_int(value["record_count"], "record_count")
        result[artifact_id] = ArtifactExpectation(
            artifact_id=artifact_id,
            root_kind=_required_string(value, "root_kind", "source lock"),
            relative_path=_safe_relative_path(
                _required_string(value, "relative_path", "source lock")
            ),
            sha256=sha256,
            byte_count=byte_count,
            record_count=record_count,
        )
    return result


def _load_artifact(
    *,
    artifact_id: str,
    root_kind: str,
    root: Path,
    relative_path: str,
    counter: Callable[[dict[str, Any]], int],
    optional: bool,
) -> _LoadedArtifact | None:
    safe_path = _safe_relative_path(relative_path)
    candidate = (root / Path(safe_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise CatalogIntakeError(
            f"source path escapes {root_kind} root: {relative_path}"
        ) from error
    if not candidate.is_file():
        if optional:
            return None
        raise CatalogIntakeError(f"required source does not exist: {root_kind}:{safe_path}")
    payload = candidate.read_bytes()
    try:
        decoded = payload.decode("utf-8")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogIntakeError(f"invalid UTF-8 JSON source: {root_kind}:{safe_path}") from error
    if not isinstance(data, dict):
        raise CatalogIntakeError(f"source must be a JSON object: {artifact_id}")
    inventory = ArtifactInventory(
        artifact_id=artifact_id,
        root_kind=root_kind,
        relative_path=safe_path,
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        record_count=counter(data),
    )
    return _LoadedArtifact(inventory, data)


def _validate_expected_inventory(
    loaded: Mapping[str, _LoadedArtifact],
    expected: Mapping[str, ArtifactExpectation] | None,
) -> None:
    if expected is None:
        return
    if set(loaded) != set(expected):
        missing = sorted(set(expected) - set(loaded))
        unexpected = sorted(set(loaded) - set(expected))
        raise CatalogIntakeError(
            f"source-lock artifact set mismatch; missing={missing}; unexpected={unexpected}"
        )
    for artifact_id in sorted(loaded):
        actual = loaded[artifact_id].inventory
        wanted = expected[artifact_id]
        if actual.root_kind != wanted.root_kind or actual.relative_path != wanted.relative_path:
            raise CatalogIntakeError(f"source-lock path mismatch: {artifact_id}")
        if actual.sha256 != wanted.sha256:
            raise CatalogIntakeError(f"source hash drift: {artifact_id}")
        if actual.byte_count != wanted.byte_count:
            raise CatalogIntakeError(f"source byte-count mismatch: {artifact_id}")
        if actual.record_count != wanted.record_count:
            raise CatalogIntakeError(f"source record-count mismatch: {artifact_id}")


def _validate_target_pool(
    raw: dict[str, Any], profile: CatalogIntakeProfile
) -> list[dict[str, Any]]:
    _exact_keys(raw, _TARGET_KEYS, "target pool")
    if raw["schema_version"] != "1.0.0":
        raise CatalogIntakeError("unsupported target-pool schema_version")
    if raw["regulation_id"] != profile.regulation_id:
        raise CatalogIntakeError("target-pool regulation_id does not match profile")
    if raw["regulation_revision"] != profile.regulation_revision:
        raise CatalogIntakeError("target-pool regulation_revision does not match profile")
    expected = _positive_or_zero_int(
        raw["expected_member_count"], "expected_member_count"
    )
    values = raw["members"]
    if not isinstance(values, list):
        raise CatalogIntakeError("target-pool members must be an array")
    if expected != len(values):
        raise CatalogIntakeError("target-pool declared count does not match members")
    if expected != profile.expected_target_count:
        raise CatalogIntakeError("target-pool count does not match intake profile")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise CatalogIntakeError(f"target members[{index}] must be an object")
        _exact_keys(value, _TARGET_MEMBER_KEYS, f"target members[{index}]")
        dex = value["national_dex_no"]
        if not isinstance(dex, int) or isinstance(dex, bool) or dex <= 0:
            raise CatalogIntakeError("target national_dex_no must be a positive integer")
        form = _required_string(value, "form_code", "target member")
        variant = _required_string(value, "variant_code", "target member")
        label = _required_string(value, "label", "target member")
        if value["pokemon_id"] is not None and not isinstance(value["pokemon_id"], str):
            raise CatalogIntakeError("target pokemon_id must be a string or null")
        member = {
            "national_dex_no": dex,
            "form_code": form,
            "variant_code": variant,
            "label": label,
            "pokemon_id": value["pokemon_id"],
        }
        _official_name(member)
        key = _target_key(member)
        if key in keys:
            raise CatalogIntakeError(f"duplicate target key: {key}")
        keys.add(key)
        result.append(member)
    return result


def _validate_dataset(
    raw: dict[str, Any], *, artifact_id: str, expected_count: int | None = None
) -> list[dict[str, Any]]:
    if not isinstance(raw.get("source"), str) or not raw["source"]:
        raise CatalogIntakeError(f"{artifact_id} source metadata is missing")
    if not isinstance(raw.get("dataset"), str) or not raw["dataset"]:
        raise CatalogIntakeError(f"{artifact_id} dataset metadata is missing")
    items = raw.get("items")
    if not isinstance(items, list):
        raise CatalogIntakeError(f"{artifact_id} items must be an array")
    if expected_count is not None and len(items) != expected_count:
        raise CatalogIntakeError(
            f"{artifact_id} count {len(items)} does not match profile {expected_count}"
        )
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise CatalogIntakeError(f"{artifact_id} items[{index}] must be an object")
    return items


def _validate_types(raw: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw.get("source"), str) or not isinstance(raw.get("dataset"), str):
        raise CatalogIntakeError("types source metadata is missing")
    types = raw.get("types")
    effectiveness = raw.get("effectiveness")
    if not isinstance(types, list) or not isinstance(effectiveness, list):
        raise CatalogIntakeError("types and effectiveness must be arrays")
    pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(effectiveness):
        if not isinstance(item, dict):
            raise CatalogIntakeError(f"effectiveness[{index}] must be an object")
        pair = (
            _entity_id(_required_field(item, "attack_type_id", "effectiveness")),
            _entity_id(_required_field(item, "defense_type_id", "effectiveness")),
        )
        if pair in pairs:
            raise CatalogIntakeError(f"duplicate type-effectiveness key: {pair}")
        pairs.add(pair)
    if len(effectiveness) != len(types) * len(types):
        raise CatalogIntakeError("type-effectiveness matrix count mismatch")
    for index, item in enumerate(types):
        if not isinstance(item, dict):
            raise CatalogIntakeError(f"types[{index}] must be an object")
    return types


def _validate_parallel_ids(
    raw: dict[str, Any], list_key: str, items: list[dict[str, Any]], item_key: str
) -> None:
    declared = raw.get(list_key)
    if not isinstance(declared, list):
        raise CatalogIntakeError(f"{list_key} must be an array")
    declared_ids = [_entity_id(value) for value in declared]
    record_ids = [_entity_id(_required_field(value, item_key, list_key)) for value in items]
    if len(declared_ids) != len(record_ids) or set(declared_ids) != set(record_ids):
        raise CatalogIntakeError(f"{list_key} count or membership mismatch")
    if len(declared_ids) != len(set(declared_ids)):
        raise CatalogIntakeError(f"duplicate ID in {list_key}")


def _unique_index(
    items: Iterable[dict[str, Any]], key: str, artifact_id: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in items:
        entity_id = _entity_id(_required_field(value, key, artifact_id))
        if entity_id in result:
            raise CatalogIntakeError(f"duplicate {artifact_id} key {key}={entity_id}")
        result[entity_id] = value
    return result


def _entity_union(
    kind: str,
    basis: str,
    ids: Iterable[str | None],
    records: Mapping[str, dict[str, Any]],
    blockers: list[IntakeBlocker],
) -> EntityUnion:
    selected = tuple(sorted({_entity_id(value) for value in ids if value is not None}))
    hashes = tuple(
        EntityRecordHash(value, canonical_sha256(records[value]))
        for value in selected
        if value in records
    )
    missing = tuple(value for value in selected if value not in records)
    for value in missing:
        blockers.append(
            IntakeBlocker(
                "entity_record_missing",
                "entity_union",
                f"{kind}:{value}",
                f"{kind} record required by {basis} is missing",
            )
        )
    return EntityUnion(kind, basis, selected, hashes, missing)


def _target_count(raw: dict[str, Any]) -> int:
    values = raw.get("members")
    if not isinstance(values, list):
        raise CatalogIntakeError("target-pool members must be an array")
    return len(values)


def _item_count(raw: dict[str, Any]) -> int:
    values = raw.get("items")
    if not isinstance(values, list):
        raise CatalogIntakeError("source items must be an array")
    return len(values)


def _type_count(raw: dict[str, Any]) -> int:
    values = raw.get("types")
    if not isinstance(values, list):
        raise CatalogIntakeError("source types must be an array")
    return len(values)


def _safe_relative_path(value: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or path.drive or any(part == ".." for part in path.parts):
        raise CatalogIntakeError(f"unsafe relative source path: {value}")
    normalized = path.as_posix()
    if normalized.startswith("/") or normalized == ".":
        raise CatalogIntakeError(f"unsafe relative source path: {value}")
    return normalized


def _official_name(value: Mapping[str, Any]) -> str:
    label = str(value["label"])
    match = _OFFICIAL_LABEL.fullmatch(label)
    if match is None:
        raise CatalogIntakeError(f"official target label has unsupported format: {label}")
    if int(match.group("dex")) != value["national_dex_no"]:
        raise CatalogIntakeError("official target label dex does not match national_dex_no")
    return match.group("name")


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _target_key(value: Mapping[str, Any]) -> str:
    return (
        f"dex:{value['national_dex_no']:04d}:form:{value['form_code']}:"
        f"variant:{value['variant_code']}"
    )


def _entity_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise CatalogIntakeError("entity IDs must be strings or integers")
    result = str(value)
    if not result:
        raise CatalogIntakeError("entity IDs must be non-empty")
    return result


def _required_field(value: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in value:
        raise CatalogIntakeError(f"{label} record is missing {key}")
    return value[key]


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    result = _required_field(value, key, label)
    if not isinstance(result, str) or not result:
        raise CatalogIntakeError(f"{label}.{key} must be a non-empty string")
    return result


def _required_list(value: Mapping[str, Any], key: str, label: str) -> list[Any]:
    result = _required_field(value, key, label)
    if not isinstance(result, list):
        raise CatalogIntakeError(f"{label}.{key} must be an array")
    return result


def _positive_or_zero_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CatalogIntakeError(f"{label} must be a non-negative integer")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str] | frozenset[str], label: str) -> None:
    actual = set(value)
    if actual != set(expected):
        raise CatalogIntakeError(
            f"{label} fields mismatch; missing={sorted(set(expected) - actual)}; "
            f"extra={sorted(actual - set(expected))}"
        )
