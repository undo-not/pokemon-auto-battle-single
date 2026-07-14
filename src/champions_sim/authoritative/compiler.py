"""Deterministic SIM-02C-A acquisition, mapping, and Catalog V2 workbench.

The compiler never performs network I/O.  It inventories caller-supplied local
roots, reports permission and provenance gaps, and emits review candidates only.
Existing SIM-02B/V3 promotion APIs intentionally do not accept these documents.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from champions_sim.intake import (
    CatalogIntakeBundle,
    CatalogIntakeError,
    CatalogIntakePaths,
    CatalogIntakeProfile,
    build_catalog_intake,
    load_source_lock,
)

from .models import (
    AUTHORITATIVE_INTAKE_COMPILER_VERSION,
    AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
    ArtifactIdentity,
    AuthoritativeIntakeCompilation,
    AuthoritativeIntakeError,
    IntakeBlocker,
    canonical_json,
    canonical_sha256,
    require_sha256,
    require_stable_id,
)


ACQUISITION_PLAN_SCHEMA_VERSION = "2.0.0"
SOURCE_POLICY_SCHEMA_VERSION = "1.0.0"
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_LOCATOR_PATTERN = re.compile(r"[^\x00-\x1f\x7f]+")
_RECORD_POINTER_PATTERN = re.compile(r"(?:|(?:/(?:[^~/]|~[01])*)+)")

_PLAN_KEYS = {
    "schema_version",
    "plan_id",
    "regulation_id",
    "target_pool_path",
    "target_source_manifests",
    "expected_target_count",
    "policy_registry_id",
    "routes",
    "plan_hash",
}
_TARGET_SOURCE_MANIFEST_KEYS = {
    "manifest_id",
    "relative_path",
    "sha256",
    "required_authority",
}
_POLICY_KEYS = {
    "schema_version",
    "registry_id",
    "reviewed_on",
    "authorization_status",
    "policies",
    "registry_hash",
}
_ROUTE_KEYS = {
    "route_id",
    "root_kind",
    "source_kind",
    "semantic_authority",
    "source_ids",
    "locators",
    "policy_id",
    "candidate_roles",
    "evidence_files",
    "raw_inventories",
    "derived_artifacts",
}
_EVIDENCE_FILE_KEYS = {
    "artifact_id",
    "role",
    "relative_path",
    "required",
    "expected_source_id",
}
_EVIDENCE_FILE_OPTIONAL_KEYS = {"inventory_id"}
_EVIDENCE_ROLES = frozenset(
    {
        "builder",
        "fetcher",
        "implementation",
        "normalizer",
        "parser",
        "raw_manifest",
        "review_record",
        "source_config",
        "validator",
    }
)
_EXTERNAL_AUTHORITIES = frozenset(
    {"champions_official", "general_official", "third_party_reference"}
)
_RAW_INVENTORY_KEYS = {
    "inventory_id",
    "relative_path",
    "suffixes",
    "expected_min_files",
}
_DERIVED_KEYS = {
    "artifact_id",
    "relative_path",
    "record_pointer",
    "expected_min_records",
    "expected_source",
}
_DERIVED_OPTIONAL_KEYS = {"lineage_requirements", "lineage_gap_hint"}
_LINEAGE_REQUIREMENT_KEYS = {
    "expected_lineage_hash",
    "source_artifact_ids",
    "transform_artifact_ids",
}
_LINEAGE_GAP_HINT_KEYS = {
    "reason_codes",
    "parent_refs",
    "unregistered_paths",
    "runtime_dependencies",
}
_LINEAGE_GAP_REASON_CODES = frozenset(
    {
        "cross_route_parent_unsupported",
        "derived_parent_unsupported",
        "direct_source_config_unsupported",
        "multi_stage_in_place_output",
        "unregistered_input",
        "unregistered_transform",
        "unmanifested_intermediate",
        "runtime_dependency_unpinned",
    }
)
_DERIVED_TRANSFORM_ROLES = frozenset({"builder", "normalizer", "parser"})
_POLICY_ENTRY_KEYS = {
    "policy_id",
    "source_group",
    "source_ids",
    "review_status",
    "evidence_urls",
    "decision_basis",
    "collection_status",
    "candidate_use",
    "private_match_use",
    "training_use",
    "redistribution",
    "production_promotion",
    "notes",
}


@dataclass(frozen=True, slots=True)
class AuthoritativeIntakeConfig:
    repository_root: Path | str
    legacy_root: Path | str
    plan_path: Path | str
    policy_registry_path: Path | str
    source_lock_path: Path | str
    intake_paths: CatalogIntakePaths | None = None
    intake_profile: CatalogIntakeProfile | None = None


def load_source_acquisition_plan(path: Path | str) -> dict[str, Any]:
    raw = _read_json_object(Path(path), "source acquisition plan")
    _exact_keys(raw, _PLAN_KEYS, "source acquisition plan")
    if raw["schema_version"] != ACQUISITION_PLAN_SCHEMA_VERSION:
        raise AuthoritativeIntakeError("unsupported acquisition plan schema_version")
    require_stable_id(_string(raw["plan_id"], "plan_id"), "plan_id")
    require_stable_id(_string(raw["regulation_id"], "regulation_id"), "regulation_id")
    _safe_relative_path(_string(raw["target_pool_path"], "target_pool_path"))
    if type(raw["expected_target_count"]) is not int or raw["expected_target_count"] <= 0:
        raise AuthoritativeIntakeError("expected_target_count must be a positive integer")
    require_stable_id(
        _string(raw["policy_registry_id"], "policy_registry_id"),
        "policy_registry_id",
    )
    manifest_ids: list[str] = []
    for index, value in enumerate(
        _array(raw["target_source_manifests"], "target_source_manifests")
    ):
        binding = _object(value, f"target_source_manifests[{index}]")
        _exact_keys(
            binding,
            _TARGET_SOURCE_MANIFEST_KEYS,
            f"target_source_manifests[{index}]",
        )
        manifest_id = _string(binding["manifest_id"], "manifest_id")
        require_stable_id(manifest_id, "manifest_id")
        manifest_ids.append(manifest_id)
        _safe_relative_path(_string(binding["relative_path"], "relative_path"))
        require_sha256(_string(binding["sha256"], "manifest sha256"), "manifest sha256")
        if binding["required_authority"] not in {"official", "synthetic"}:
            raise AuthoritativeIntakeError("unsupported target manifest authority")
    if not manifest_ids:
        raise AuthoritativeIntakeError("target_source_manifests must not be empty")
    if manifest_ids != sorted(manifest_ids) or len(manifest_ids) != len(set(manifest_ids)):
        raise AuthoritativeIntakeError(
            "target_source_manifests must be unique and sorted by manifest_id"
        )
    routes = _array(raw["routes"], "routes")
    if not routes:
        raise AuthoritativeIntakeError("acquisition plan requires routes")
    route_ids: list[str] = []
    artifact_path_owners: dict[tuple[str, str], str] = {}
    inventory_path_owners: dict[tuple[str, str], str] = {}
    for index, value in enumerate(routes):
        route = _object(value, f"routes[{index}]")
        _validate_route(route, index)
        route_ids.append(route["route_id"])
        root_kind = route["root_kind"]
        declarations = [
            *( (item, "evidence") for item in route["evidence_files"] ),
            *( (item, "derived") for item in route["derived_artifacts"] ),
        ]
        for declaration, declaration_kind in declarations:
            key = (root_kind, declaration["relative_path"])
            owner = f"{route['route_id']}:{declaration_kind}:{declaration['artifact_id']}"
            prior_owner = artifact_path_owners.get(key)
            if prior_owner is not None:
                raise AuthoritativeIntakeError(
                    "evidence and derived relative paths must be globally "
                    f"role-independent: {prior_owner} and {owner}"
                )
            artifact_path_owners[key] = owner
        for declaration in route["raw_inventories"]:
            key = (root_kind, declaration["relative_path"])
            owner = f"{route['route_id']}:inventory:{declaration['inventory_id']}"
            prior_owner = inventory_path_owners.get(key)
            if prior_owner is not None:
                raise AuthoritativeIntakeError(
                    "raw inventory relative paths must be globally unique: "
                    f"{prior_owner} and {owner}"
                )
            inventory_path_owners[key] = owner
    if route_ids != sorted(route_ids) or len(route_ids) != len(set(route_ids)):
        raise AuthoritativeIntakeError("routes must be unique and sorted by route_id")
    declared_artifact_refs = {
        (route["route_id"], declaration["artifact_id"])
        for route in routes
        for declaration in [
            *route["evidence_files"],
            *route["derived_artifacts"],
        ]
    }
    for route in routes:
        for declaration in route["derived_artifacts"]:
            hint = declaration.get("lineage_gap_hint")
            if hint is None:
                continue
            child_ref = (route["route_id"], declaration["artifact_id"])
            parent_refs = {
                (value["route_id"], value["artifact_id"])
                for value in hint["parent_refs"]
            }
            if child_ref in parent_refs:
                raise AuthoritativeIntakeError(
                    "lineage gap hint cannot name the child as its own parent"
                )
            unknown_refs = sorted(parent_refs - declared_artifact_refs)
            if unknown_refs:
                raise AuthoritativeIntakeError(
                    f"lineage gap hint references unknown parent artifacts: {unknown_refs}"
                )
    claimed = _string(raw["plan_hash"], "plan_hash")
    require_sha256(claimed, "plan_hash")
    derived = canonical_sha256({key: value for key, value in raw.items() if key != "plan_hash"})
    if claimed != derived:
        raise AuthoritativeIntakeError("acquisition plan_hash mismatch")
    return raw


def load_source_policy_registry(path: Path | str) -> dict[str, Any]:
    raw = _read_json_object(Path(path), "source policy registry")
    _exact_keys(raw, _POLICY_KEYS, "source policy registry")
    if raw["schema_version"] != SOURCE_POLICY_SCHEMA_VERSION:
        raise AuthoritativeIntakeError("unsupported source policy schema_version")
    require_stable_id(_string(raw["registry_id"], "registry_id"), "registry_id")
    _timestamp_or_date(_string(raw["reviewed_on"], "reviewed_on"), "reviewed_on")
    if raw["authorization_status"] != "not_authorization":
        raise AuthoritativeIntakeError("policy registry is never production authorization")
    policies = _array(raw["policies"], "policies")
    if not policies:
        raise AuthoritativeIntakeError("policy registry requires policies")
    policy_ids: list[str] = []
    for index, value in enumerate(policies):
        policy = _object(value, f"policies[{index}]")
        _validate_policy(policy, index)
        policy_ids.append(policy["policy_id"])
    if policy_ids != sorted(policy_ids) or len(policy_ids) != len(set(policy_ids)):
        raise AuthoritativeIntakeError("policies must be unique and sorted by policy_id")
    claimed = _string(raw["registry_hash"], "registry_hash")
    require_sha256(claimed, "registry_hash")
    derived = canonical_sha256(
        {key: value for key, value in raw.items() if key != "registry_hash"}
    )
    if claimed != derived:
        raise AuthoritativeIntakeError("source policy registry_hash mismatch")
    return raw


def compile_authoritative_intake(
    config: AuthoritativeIntakeConfig,
) -> AuthoritativeIntakeCompilation:
    repo_input = Path(config.repository_root).expanduser()
    legacy_input = Path(config.legacy_root).expanduser()
    if repo_input.is_symlink():
        raise AuthoritativeIntakeError("repository root must not be a symlink")
    if legacy_input.is_symlink():
        raise AuthoritativeIntakeError("legacy root must not be a symlink")
    repo = repo_input.resolve()
    legacy = legacy_input.resolve()
    if not repo.is_dir():
        raise AuthoritativeIntakeError(f"repository root does not exist: {repo}")
    if not legacy.is_dir():
        raise AuthoritativeIntakeError(f"legacy root does not exist: {legacy}")

    plan = load_source_acquisition_plan(config.plan_path)
    policies = load_source_policy_registry(config.policy_registry_path)
    if plan["policy_registry_id"] != policies["registry_id"]:
        raise AuthoritativeIntakeError("plan references another policy registry")
    roots = {"repository": repo, "legacy": legacy}
    target_path = _resolve_path(repo, plan["target_pool_path"], "target pool")
    target_bytes = _read_confined_bytes(repo, target_path, "target pool")
    target_pool = _parse_json_object(target_bytes, "target pool")
    target_members = _validate_target_pool(target_pool, plan)
    target_pool_hash = hashlib.sha256(target_bytes).hexdigest()
    (
        target_source_manifest_ids,
        target_source_manifest_hash,
        denominator_final,
    ) = _validate_target_source_manifests(
        repo=repo,
        plan=plan,
        target_pool=target_pool,
        target_pool_bytes=target_bytes,
    )
    regulation_revision = target_pool["regulation_revision"]

    policy_by_id = {value["policy_id"]: value for value in policies["policies"]}
    source_review = _build_source_review(plan, policies, policy_by_id, roots)

    source_lock_path = Path(config.source_lock_path).expanduser()
    if source_lock_path.is_symlink():
        raise AuthoritativeIntakeError("Catalog intake source lock must not be a symlink")
    try:
        expected_inventory = load_source_lock(config.source_lock_path)
    except CatalogIntakeError as error:
        raise AuthoritativeIntakeError(
            f"frozen Catalog intake rejected the source lock: {error}"
        ) from error
    if not source_lock_path.is_file():
        raise AuthoritativeIntakeError("Catalog intake source lock does not exist")
    source_lock_bytes = _read_stable_bytes(
        source_lock_path.resolve(), "Catalog intake source lock"
    )
    source_lock_document = _parse_json_object(
        source_lock_bytes, "Catalog intake source lock"
    )
    _validate_source_lock_document(expected_inventory, source_lock_document)
    source_lock_hash = hashlib.sha256(source_lock_bytes).hexdigest()
    usage_expectation = expected_inventory.get("pokemon_usage")
    if usage_expectation is None or usage_expectation.record_count <= 0:
        raise AuthoritativeIntakeError(
            "source lock must declare a positive pokemon_usage record count"
        )
    locked_path_fields = {
        "target_pool": "official_target_pool",
        "pokemon_usage": "pokemon_usage",
        "pokemon_catalog": "pokemon_catalog",
        "pokemon": "pokemon",
        "moves": "moves",
        "abilities": "abilities",
        "items": "items",
        "types": "types",
        "usage_details": "pokemon_usage_details",
    }
    missing_path_artifacts = sorted(
        artifact_id
        for artifact_id in locked_path_fields.values()
        if artifact_id not in expected_inventory
    )
    if missing_path_artifacts:
        raise AuthoritativeIntakeError(
            f"source lock is missing intake paths: {missing_path_artifacts}"
        )
    locked_paths = CatalogIntakePaths(
        **{
            field: expected_inventory[artifact_id].relative_path
            for field, artifact_id in locked_path_fields.items()
        }
    )
    paths = config.intake_paths or locked_paths
    if paths != locked_paths:
        raise AuthoritativeIntakeError(
            "intake paths must exactly match the frozen source lock"
        )
    if paths.target_pool != plan["target_pool_path"]:
        raise AuthoritativeIntakeError(
            "source-lock target_pool path must equal the acquisition plan target_pool_path"
        )
    profile = config.intake_profile or CatalogIntakeProfile(
        profile_id="sim02c_authoritative_workbench_v1",
        regulation_id=plan["regulation_id"],
        regulation_revision=target_pool["regulation_revision"],
        expected_target_count=plan["expected_target_count"],
        expected_usage_count=usage_expectation.record_count,
    )
    if (
        profile.regulation_id != plan["regulation_id"]
        or profile.regulation_revision != target_pool["regulation_revision"]
        or profile.expected_target_count != plan["expected_target_count"]
    ):
        raise AuthoritativeIntakeError(
            "intake profile must match the acquisition plan and target pool"
        )
    try:
        intake = build_catalog_intake(
            repository_root=repo,
            legacy_root=legacy,
            paths=paths,
            profile=profile,
            expected_inventory=expected_inventory,
        )
    except CatalogIntakeError as error:
        raise AuthoritativeIntakeError(
            f"frozen Catalog intake rejected the source corpus: {error}"
        ) from error
    if intake.target_pool_sha256 != target_pool_hash:
        raise AuthoritativeIntakeError(
            "target pool changed while the frozen intake was being resolved"
        )
    if tuple(_target_key(value) for value in target_members) != tuple(
        value.target_key for value in intake.members
    ):
        raise AuthoritativeIntakeError(
            "target member identity changed while the frozen intake was being resolved"
        )
    _validate_source_review_intake_snapshot(source_review, intake)
    intake_documents = _load_strict_intake_snapshot(roots, intake)
    mapping = _build_mapping_workbench(
        plan,
        target_members,
        intake,
        target_pool_hash,
        source_lock_hash,
        regulation_revision,
        target_source_manifest_ids,
        target_source_manifest_hash,
        denominator_final,
    )
    catalog = _build_catalog_workbench(
        plan=plan,
        intake=intake,
        intake_documents=intake_documents,
        mapping=mapping,
        source_review=source_review,
        target_pool_hash=target_pool_hash,
        regulation_revision=regulation_revision,
        target_source_manifest_hash=target_source_manifest_hash,
    )
    assessment = _build_assessment(
        plan=plan,
        source_review=source_review,
        mapping=mapping,
        catalog=catalog,
        target_pool_hash=target_pool_hash,
        regulation_revision=regulation_revision,
        target_source_manifest_hash=target_source_manifest_hash,
        denominator_final=denominator_final,
    )
    return AuthoritativeIntakeCompilation(
        plan_id=plan["plan_id"],
        plan_hash=plan["plan_hash"],
        policy_registry_id=policies["registry_id"],
        policy_registry_hash=policies["registry_hash"],
        source_lock_hash=source_lock_hash,
        regulation_id=plan["regulation_id"],
        regulation_revision=regulation_revision,
        target_pool_hash=target_pool_hash,
        target_source_manifest_ids=target_source_manifest_ids,
        target_source_manifest_hash=target_source_manifest_hash,
        source_review=source_review,
        mapping_workbench=mapping,
        catalog_workbench=catalog,
        assessment=assessment,
    )


def _build_source_review(
    plan: Mapping[str, Any],
    policy_registry: Mapping[str, Any],
    policy_by_id: Mapping[str, Mapping[str, Any]],
    roots: Mapping[str, Path],
) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    all_blockers: list[IntakeBlocker] = []
    total_raw_files = 0
    total_raw_bytes = 0
    total_derived = 0
    artifact_file_owners: dict[tuple[int, int], str] = {}
    artifact_hashes: set[str] = set()
    artifact_role_by_hash: dict[str, str] = {}
    for route in plan["routes"]:
        route_id = route["route_id"]
        root_kind = route["root_kind"]
        root = roots[root_kind]
        source_covering_roles = _source_covering_evidence_roles(
            route["semantic_authority"]
        )
        policy = policy_by_id.get(route["policy_id"])
        if policy is None:
            raise AuthoritativeIntakeError(
                f"route references unknown policy: {route['policy_id']}"
            )
        route_blockers: list[IntakeBlocker] = []
        observed_source_ids: set[str] = set()
        artifacts: list[ArtifactIdentity] = []
        artifact_by_id: dict[str, ArtifactIdentity] = {}
        manifest_audits: list[dict[str, Any]] = []
        manifest_audit_by_id: dict[str, dict[str, Any]] = {}
        manifest_expected_source_by_id: dict[str, str | None] = {}
        inventory_declaration_by_id = {
            value["inventory_id"]: value for value in route["raw_inventories"]
        }
        manifest_paths_by_inventory_id: dict[str, set[str]] = {}
        for evidence in route["evidence_files"]:
            if evidence["role"] != "raw_manifest":
                continue
            manifest_expected_source_by_id[evidence["artifact_id"]] = evidence[
                "expected_source_id"
            ]
            inventory_id = evidence.get("inventory_id")
            if inventory_id is not None:
                manifest_paths_by_inventory_id.setdefault(inventory_id, set()).add(
                    evidence["relative_path"]
                )
        for evidence in route["evidence_files"]:
            path = _try_resolve_path(root, evidence["relative_path"])
            if path is None or not path.is_file():
                if evidence["required"]:
                    route_blockers.append(
                        _blocker(
                            "acquisition",
                            "required_evidence_file_missing",
                            f"{route_id}:{evidence['artifact_id']}",
                            "the declared source config/fetcher/parser/raw manifest file",
                            "restore the exact file and rerun the content-addressed review",
                        )
                    )
                continue
            _reject_symlink_path(root, path)
            identity, payload, file_key = _snapshot_file_identity(
                evidence["artifact_id"], root_kind, root, path, evidence["role"]
            )
            owner = f"{route_id}:evidence:{evidence['artifact_id']}"
            prior_owner = artifact_file_owners.get(file_key)
            if prior_owner is not None:
                raise AuthoritativeIntakeError(
                    "one opened file cannot satisfy multiple evidence or derived "
                    f"artifacts: {prior_owner} and {owner}"
                )
            prior_role = artifact_role_by_hash.get(identity.sha256)
            if identity.sha256 in artifact_hashes:
                raise AuthoritativeIntakeError(
                    "identical bytes cannot satisfy multiple evidence or derived "
                    f"artifacts: {prior_role or 'raw_payload'} and {identity.role}"
                )
            artifact_file_owners[file_key] = owner
            artifact_hashes.add(identity.sha256)
            artifact_role_by_hash[identity.sha256] = identity.role
            artifacts.append(identity)
            artifact_by_id[identity.artifact_id] = identity
            source_identity_matches = True
            raw_manifest_integrity_verified = False
            if evidence["role"] in {"source_config", "raw_manifest"}:
                parsed = _parse_json_object(payload, evidence["role"])
                expected_source = evidence["expected_source_id"]
                actual_source = parsed.get("source_id")
                if expected_source is not None and actual_source != expected_source:
                    source_identity_matches = False
                    route_blockers.append(
                        _blocker(
                            "acquisition",
                            "source_id_mismatch",
                            f"{route_id}:{evidence['artifact_id']}",
                            f"source_id {expected_source} in the exact evidence document",
                            "correct the route or reacquire the matching source evidence",
                        )
                    )
                if evidence["role"] == "raw_manifest":
                    inventory_id = evidence.get("inventory_id")
                    audit, blockers = _audit_raw_manifest(
                        artifact_id=evidence["artifact_id"],
                        route_id=route_id,
                        root=root,
                        root_kind=root_kind,
                        manifest=parsed,
                        manifest_relative_path=evidence["relative_path"],
                        expected_source_id=expected_source,
                        inventory_id=inventory_id,
                        inventory_declaration=(
                            inventory_declaration_by_id.get(inventory_id)
                            if inventory_id is not None
                            else None
                        ),
                    )
                    manifest_audits.append(audit)
                    manifest_audit_by_id[evidence["artifact_id"]] = audit
                    route_blockers.extend(blockers)
                    raw_manifest_integrity_verified = (
                        audit["integrity_status"] == "verified"
                    )
            expected_source = evidence["expected_source_id"]
            evidence_integrity_verified = (
                raw_manifest_integrity_verified
                if evidence["role"] == "raw_manifest"
                else True
            )
            if (
                evidence["role"] != "raw_manifest"
                and
                expected_source is not None
                and source_identity_matches
                and evidence_integrity_verified
                and evidence["role"] in source_covering_roles
            ):
                observed_source_ids.add(expected_source)

        inventories: list[dict[str, Any]] = []
        for declaration in route["raw_inventories"]:
            bound_manifest_ids = sorted(
                evidence["artifact_id"]
                for evidence in route["evidence_files"]
                if evidence["role"] == "raw_manifest"
                and evidence.get("inventory_id") == declaration["inventory_id"]
            )
            if not bound_manifest_ids:
                route_blockers.append(
                    _blocker(
                        "acquisition",
                        "raw_inventory_manifest_binding_missing",
                        _stable_subject(route_id, declaration["inventory_id"]),
                        "exactly one source-specific raw manifest bound to this inventory",
                        "bind one reviewed raw manifest to the inventory and rerun",
                    )
                )
            elif len(bound_manifest_ids) > 1:
                route_blockers.append(
                    _blocker(
                        "acquisition",
                        "raw_inventory_manifest_binding_ambiguous",
                        _stable_subject(route_id, declaration["inventory_id"]),
                        "exactly one source-specific raw manifest bound to this inventory",
                        "partition the inventory or issue one union manifest; bound manifests: "
                        + ", ".join(bound_manifest_ids),
                    )
                )
            excluded_manifest_paths = {
                evidence["relative_path"]
                for evidence in route["evidence_files"]
                if evidence["role"] == "raw_manifest"
                and _payload_is_declared_by_inventory(
                    evidence["relative_path"], (declaration,)
                )
            }
            inventory, blockers = _inventory_raw_root(
                route_id=route_id,
                root=root,
                root_kind=root_kind,
                declaration=declaration,
                excluded_relative_paths=(
                    excluded_manifest_paths
                    | manifest_paths_by_inventory_id.get(
                        declaration["inventory_id"], set()
                    )
                ),
                occupied_file_owners=artifact_file_owners,
                occupied_hashes=artifact_hashes,
                occupied_role_by_hash=artifact_role_by_hash,
            )
            inventories.append(inventory)
            route_blockers.extend(blockers)
            total_raw_files += inventory["file_count"]
            total_raw_bytes += inventory["byte_count"]

        inventory_by_id = {
            value["inventory_id"]: value for value in inventories
        }
        for audit in manifest_audits:
            inventory_id = audit["inventory_id"]
            if inventory_id is None or audit["inventory_binding_status"] != "verified":
                continue
            inventory = inventory_by_id.get(inventory_id)
            if (
                inventory is None
                or audit["payload_inventory_hash"] != inventory["inventory_hash"]
            ):
                raise AuthoritativeIntakeError(
                    "raw payload changed across source snapshot: "
                    f"{route_id}:{audit['artifact_id']}:{inventory_id}"
                )
            expected_source = manifest_expected_source_by_id.get(audit["artifact_id"])
            if expected_source is not None and audit["source_id"] == expected_source:
                observed_source_ids.add(expected_source)

        derived: list[dict[str, Any]] = []
        for declaration in route["derived_artifacts"]:
            item, blockers = _audit_derived_artifact(
                route_id=route_id,
                root=root,
                root_kind=root_kind,
                declaration=declaration,
                semantic_authority=route["semantic_authority"],
                evidence_by_id=artifact_by_id,
                occupied_file_owners=artifact_file_owners,
                occupied_hashes=artifact_hashes,
                manifest_audit_by_id=manifest_audit_by_id,
            )
            if item is not None:
                artifact_role_by_hash[item["sha256"]] = "derived_artifact"
                derived.append(item)
                total_derived += 1
                expected_source = declaration["expected_source"]
                if (
                    expected_source is not None
                    and item["actual_source"] == expected_source
                    and item["lineage_status"] == "snapshot_bound"
                ):
                    observed_source_ids.add(expected_source)
            route_blockers.extend(blockers)

        missing_source_evidence = sorted(
            set(route["source_ids"]) - observed_source_ids
        )
        if missing_source_evidence:
            route_blockers.append(
                _blocker(
                    "acquisition",
                    "source_evidence_coverage_incomplete",
                    _stable_subject(route_id, "source_coverage"),
                    "present, identity-matching evidence for every route source_id",
                    "restore or add required evidence for: "
                    + ", ".join(missing_source_evidence),
                )
            )

        route_blockers.extend(_policy_blockers(route, policy))
        route_blockers = _sorted_unique_blockers(route_blockers)
        all_blockers.extend(route_blockers)
        evidence_status = (
            "snapshot_bound"
            if not any(value.stage == "acquisition" for value in route_blockers)
            else "partial"
        )
        routes.append(
            {
                "route_id": route_id,
                "root_kind": root_kind,
                "source_kind": route["source_kind"],
                "semantic_authority": route["semantic_authority"],
                "source_ids": list(route["source_ids"]),
                "locators": list(route["locators"]),
                "candidate_roles": list(route["candidate_roles"]),
                "policy_id": policy["policy_id"],
                "usage_permission": {
                    "source_ids": list(policy["source_ids"]),
                    **{
                        key: policy[key]
                        for key in (
                            "review_status",
                            "collection_status",
                            "candidate_use",
                            "private_match_use",
                            "training_use",
                            "redistribution",
                            "production_promotion",
                        )
                    },
                },
                "acquisition_integrity_status": evidence_status,
                "evidence_artifacts": [
                    value.to_data()
                    for value in sorted(artifacts, key=lambda item: item.artifact_id)
                ],
                "raw_manifest_audits": sorted(
                    manifest_audits, key=lambda item: item["source_id"]
                ),
                "raw_inventories": sorted(
                    inventories, key=lambda item: item["inventory_id"]
                ),
                "derived_artifacts": sorted(
                    derived, key=lambda item: item["artifact_id"]
                ),
                "blockers": [value.to_data() for value in route_blockers],
                "production_promotable": False,
            }
        )

    all_blockers = _sorted_unique_blockers(all_blockers)
    route_status_counts = Counter(value["acquisition_integrity_status"] for value in routes)
    permission_counts = Counter(
        value["usage_permission"]["review_status"] for value in routes
    )
    resolved_route_count = sum(
        _route_permission_is_resolved(value) for value in routes
    )
    summary = {
        "route_count": len(routes),
        "acquisition_integrity_counts": dict(sorted(route_status_counts.items())),
        "policy_review_status_counts": dict(sorted(permission_counts.items())),
        "policy_resolved_for_production_route_count": resolved_route_count,
        # V2 can prove only snapshot binding.  Causal acquisition replay needs
        # an execution-evidence contract and is reserved for a later version.
        "acquisition_route_integrity_rate_ppm": 0,
        "snapshot_bound_route_rate_ppm": (
            route_status_counts["snapshot_bound"] * 1_000_000 // len(routes)
        ),
        "source_policy_resolution_rate_ppm": (
            resolved_route_count
            * 1_000_000
            // len(routes)
        ),
        "production_promotable_route_count": 0,
        "raw_file_count": total_raw_files,
        "raw_byte_count": total_raw_bytes,
        "derived_artifact_count": total_derived,
        "blocker_count": len(all_blockers),
    }
    unsigned = {
        "schema_version": AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
        "compiler_version": AUTHORITATIVE_INTAKE_COMPILER_VERSION,
        "review_id": f"source-review:{plan['plan_id']}",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "policy_registry_id": policy_registry["registry_id"],
        "policy_registry_hash": policy_registry["registry_hash"],
        "authorization_status": "not_authorization",
        "network_io_performed": False,
        "routes": routes,
        "blockers": [value.to_data() for value in all_blockers],
        "summary": summary,
    }
    return {**unsigned, "review_hash": canonical_sha256(unsigned)}


def _build_mapping_workbench(
    plan: Mapping[str, Any],
    target_members: Sequence[Mapping[str, Any]],
    intake: CatalogIntakeBundle,
    target_pool_hash: str,
    source_lock_hash: str,
    regulation_revision: str,
    target_source_manifest_ids: tuple[str, ...],
    target_source_manifest_hash: str,
    denominator_final: bool,
) -> dict[str, Any]:
    intake_by_key = {value.target_key: value for value in intake.members}
    conflict_keys = {value.target_key for value in intake.usage_detail_conflicts}
    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for target in target_members:
        target_key = _target_key(target)
        member = intake_by_key.get(target_key)
        if member is None:
            status = "unresolved"
            candidate_ids: tuple[str, ...] = ()
            selected_id = None
            mapping_basis = "no_intake_row"
            detail_hash = None
            source_record_key = target_key
        else:
            candidate_ids = member.evidence.candidate_pokemon_ids
            selected_id = member.selected_pokemon_id
            mapping_basis = (
                f"{member.mapping_status}:{member.evidence.matched_by}"
            )
            detail_hash = member.detail_record_sha256
            source_record_key = member.evidence.source_record_key
            if target_key in conflict_keys:
                status = "conflict"
            elif candidate_ids:
                status = "candidate"
            else:
                status = "unresolved"
        status_counts[status] += 1
        source_entities = []
        for candidate_id in sorted(candidate_ids):
            source_entities.append(
                {
                    "namespace": "yakkun_champions",
                    "entity_id": candidate_id,
                    "form_id": None,
                    "variant_id": None,
                    "record_sha256": (
                        detail_hash if candidate_id == selected_id else None
                    ),
                    "evidence_status": "candidate_unreviewed",
                }
            )
        target_record = {
            "national_dex_no": target["national_dex_no"],
            "form_code": target["form_code"],
            "variant_code": target["variant_code"],
            "label": target["label"],
        }
        rows.append(
            {
                "target_key": target_key,
                "target_namespace": "champions_target",
                "target_record_sha256": canonical_sha256(target_record),
                "national_dex_no": target["national_dex_no"],
                "form_code": target["form_code"],
                "variant_code": target["variant_code"],
                "label": target["label"],
                "resolution_status": status,
                "verification_status": "unverified",
                "mapping_basis": mapping_basis,
                "source_record_key": source_record_key,
                "selected_catalog_candidate_id": selected_id,
                "candidate_catalog_ids": list(sorted(candidate_ids)),
                "source_entities": source_entities,
                "review_decision_id": None,
                "promotion_eligible": False,
            }
        )
    rows.sort(key=lambda value: value["target_key"])
    if len(rows) != plan["expected_target_count"]:
        raise AuthoritativeIntakeError("mapping workbench changed the target denominator")
    summary = {
        "target_member_count": len(rows),
        "candidate_count": status_counts["candidate"],
        "conflict_count": status_counts["conflict"],
        "unresolved_count": status_counts["unresolved"],
        "verified_count": 0,
        "promotion_unresolved_count": (
            status_counts["candidate"]
            + status_counts["conflict"]
            + status_counts["unresolved"]
        ),
        "reviewed_mapping_count": 0,
        "namespace_form_complete_count": 0,
        "authoritative_mapping_rate_ppm": 0,
    }
    unsigned = {
        "schema_version": AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
        "compiler_version": AUTHORITATIVE_INTAKE_COMPILER_VERSION,
        "workbench_id": f"mapping:{plan['plan_id']}",
        "plan_id": plan["plan_id"],
        "regulation_id": plan["regulation_id"],
        "regulation_revision": regulation_revision,
        "target_pool_hash": target_pool_hash,
        "target_source_manifest_ids": list(target_source_manifest_ids),
        "target_source_manifest_hash": target_source_manifest_hash,
        "source_lock_hash": source_lock_hash,
        "intake_bundle_hash": intake.bundle_hash,
        "authorization_status": "not_authorization",
        "denominator_final": denominator_final,
        "members": rows,
        "summary": summary,
    }
    return {**unsigned, "mapping_workbench_hash": canonical_sha256(unsigned)}


def _build_catalog_workbench(
    *,
    plan: Mapping[str, Any],
    intake: CatalogIntakeBundle,
    intake_documents: Mapping[str, Mapping[str, Any]],
    mapping: Mapping[str, Any],
    source_review: Mapping[str, Any],
    target_pool_hash: str,
    regulation_revision: str,
    target_source_manifest_hash: str,
) -> dict[str, Any]:
    datasets = {
        "pokemon": _dataset_items(intake_documents, "pokemon"),
        "moves": _dataset_items(intake_documents, "moves"),
        "abilities": _dataset_items(intake_documents, "abilities"),
        "items": _dataset_items(intake_documents, "items"),
        "types": dict(intake_documents["types"]),
    }
    pokemon_by_id = _index_records(datasets["pokemon"], "pokemon_id", "pokemon")
    move_by_id = _index_records(datasets["moves"], "move_id", "moves")
    ability_by_id = _index_records(datasets["abilities"], "ability_id", "abilities")
    item_by_id = _index_records(datasets["items"], "item_id", "items")

    unions = {value.entity_kind: value for value in intake.entity_unions}
    species: list[dict[str, Any]] = []
    for row in mapping["members"]:
        candidate_id = row["selected_catalog_candidate_id"]
        record = pokemon_by_id.get(str(candidate_id)) if candidate_id is not None else None
        record_hash = canonical_sha256(record) if record is not None else None
        source_ref = (
            [f"legacy-pokemon:{candidate_id}:{record_hash}"]
            if record_hash is not None
            else []
        )
        fields = {
            "name": _candidate_field(record, "name", source_ref),
            "types": _candidate_field(record, "type_ids", source_ref),
            "base_stats": _missing_field(
                "legacy data contains level-dependent actual-stat ranges, not base stats"
            ),
            "abilities": _candidate_field(record, "abilities", source_ref),
            "legal_moves": _candidate_field(record, "move_ids", source_ref),
            "form_relation": _form_relation_field(record, source_ref),
        }
        species.append(
            {
                "target_key": row["target_key"],
                "catalog_candidate_id": candidate_id,
                "mapping_status": row["resolution_status"],
                "source_record_sha256": record_hash,
                "fields": fields,
                "runtime_lowering_status": "blocked",
            }
        )

    move_ids = unions.get("move").ids if unions.get("move") is not None else ()
    moves: list[dict[str, Any]] = []
    for entity_id in move_ids:
        record = move_by_id.get(str(entity_id))
        record_hash = canonical_sha256(record) if record is not None else None
        refs = [f"legacy-move:{entity_id}:{record_hash}"] if record_hash else []
        moves.append(
            {
                "entity_id": str(entity_id),
                "source_record_sha256": record_hash,
                "fields": {
                    "name": _candidate_field(record, "name", refs),
                    "type": _candidate_field(record, "type_id", refs),
                    "category": _candidate_field(record, "category", refs),
                    "power": _candidate_field(record, "power", refs, nullable=True),
                    "accuracy": _candidate_field(
                        record, "accuracy", refs, nullable=True
                    ),
                    "pp": _candidate_field(record, "pp", refs),
                    "priority": _missing_field("legacy move records do not declare priority"),
                    "target": _candidate_field(record, "target_id", refs),
                    "contact": _nested_candidate_field(
                        record, ("flags", "direct_attack"), refs
                    ),
                    "structured_effect": _unknown_field(
                        "free-text effect exists but has not been lowered to a reviewed effect contract",
                        refs,
                    ),
                },
                "runtime_lowering_status": "blocked",
            }
        )

    ability_ids = (
        unions.get("ability").ids if unions.get("ability") is not None else ()
    )
    abilities: list[dict[str, Any]] = []
    for entity_id in ability_ids:
        record = ability_by_id.get(str(entity_id))
        record_hash = canonical_sha256(record) if record is not None else None
        refs = [f"legacy-ability:{entity_id}:{record_hash}"] if record_hash else []
        abilities.append(
            {
                "entity_id": str(entity_id),
                "source_record_sha256": record_hash,
                "fields": {
                    "name": _candidate_field(record, "name", refs),
                    "trigger": _unknown_field(
                        "ability trigger has not been structured and reviewed", refs
                    ),
                    "target": _unknown_field(
                        "ability target has not been structured and reviewed", refs
                    ),
                    "structured_effect": _unknown_field(
                        "free-text ability effect is not an executable contract", refs
                    ),
                },
                "runtime_lowering_status": "blocked",
            }
        )

    item_ids = unions.get("item").ids if unions.get("item") is not None else ()
    items: list[dict[str, Any]] = []
    for entity_id in item_ids:
        record = item_by_id.get(str(entity_id))
        record_hash = canonical_sha256(record) if record is not None else None
        refs = [f"legacy-item:{entity_id}:{record_hash}"] if record_hash else []
        items.append(
            {
                "entity_id": str(entity_id),
                "source_record_sha256": record_hash,
                "fields": {
                    "name": _candidate_field(record, "name", refs),
                    "trigger": _unknown_field(
                        "item trigger has not been structured and reviewed", refs
                    ),
                    "target": _unknown_field(
                        "item target has not been structured and reviewed", refs
                    ),
                    "structured_effect": _unknown_field(
                        "free-text item effect is not an executable contract", refs
                    ),
                },
                "runtime_lowering_status": "blocked",
            }
        )

    type_records = datasets["types"].get("types", [])
    effectiveness_records = datasets["types"].get("effectiveness", [])
    if type(type_records) is not list or type(effectiveness_records) is not list:
        raise AuthoritativeIntakeError("legacy types dataset has invalid arrays")
    types_hash = canonical_sha256(datasets["types"])
    type_refs = [f"legacy-types:{types_hash}"]
    types: list[dict[str, Any]] = []
    for raw_type in type_records:
        if type(raw_type) is not dict or "type_id" not in raw_type:
            raise AuthoritativeIntakeError("legacy type record has no type_id")
        entity_id = str(raw_type["type_id"])
        matchups = [
            value
            for value in effectiveness_records
            if type(value) is dict and str(value.get("attack_type_id")) == entity_id
        ]
        matchups.sort(key=lambda value: str(value.get("defense_type_id")))
        types.append(
            {
                "entity_id": entity_id,
                "source_record_sha256": canonical_sha256(
                    {"type": raw_type, "effectiveness": matchups}
                ),
                "fields": {
                    "name": _candidate_field(raw_type, "name", type_refs),
                    "effectiveness": {
                        "status": "candidate_unreviewed",
                        "value": matchups,
                        "source_refs": type_refs,
                        "note": "candidate matrix; unknown pairs must never default to neutral",
                    },
                },
                "runtime_lowering_status": "blocked",
            }
        )
    types.sort(key=lambda value: value["entity_id"])

    mega_relations = _build_mega_relation_candidates(species, pokemon_by_id)
    all_entities = [*species, *moves, *abilities, *items, *types, *mega_relations]
    field_statuses = Counter(
        field["status"]
        for entity in all_entities
        for field in entity["fields"].values()
    )
    required_field_count = sum(field_statuses.values())
    summary = {
        "species_count": len(species),
        "move_count": len(moves),
        "ability_count": len(abilities),
        "item_count": len(items),
        "type_count": len(type_records),
        "mega_relation_candidate_count": len(mega_relations),
        "required_field_count": required_field_count,
        "field_status_counts": dict(sorted(field_statuses.items())),
        "verified_field_count": 0,
        "catalog_required_field_evidence_rate_ppm": 0,
        "runtime_lowerable_entity_count": 0,
        "production_catalog_ready": False,
    }
    unsigned = {
        "schema_version": "2.0.0-workbench",
        "compiler_version": AUTHORITATIVE_INTAKE_COMPILER_VERSION,
        "catalog_workbench_id": f"catalog-v2:{plan['plan_id']}",
        "plan_id": plan["plan_id"],
        "regulation_id": plan["regulation_id"],
        "regulation_revision": regulation_revision,
        "target_pool_hash": target_pool_hash,
        "target_source_manifest_hash": target_source_manifest_hash,
        "source_review_hash": source_review["review_hash"],
        "mapping_workbench_hash": mapping["mapping_workbench_hash"],
        "authorization_status": "not_authorization",
        "payload_policy": "restricted_local_git_external",
        "types_inventory_hash": canonical_sha256(datasets["types"]),
        "species": species,
        "moves": moves,
        "abilities": abilities,
        "items": items,
        "types": types,
        "mega_relations": mega_relations,
        "summary": summary,
    }
    return {**unsigned, "catalog_workbench_hash": canonical_sha256(unsigned)}


def _build_assessment(
    *,
    plan: Mapping[str, Any],
    source_review: Mapping[str, Any],
    mapping: Mapping[str, Any],
    catalog: Mapping[str, Any],
    target_pool_hash: str,
    regulation_revision: str,
    target_source_manifest_hash: str,
    denominator_final: bool,
) -> dict[str, Any]:
    blockers: list[IntakeBlocker] = []
    for value in source_review["blockers"]:
        blockers.append(
            IntakeBlocker(
                stage=value["stage"],
                code=value["code"],
                subject=value["subject"],
                evidence_required=value["evidence_required"],
                restart_condition=value["restart_condition"],
            )
        )

    if not denominator_final:
        blockers.append(
            _blocker(
                "acquisition",
                "target_denominator_authority_unresolved",
                _stable_subject("target", plan["regulation_id"], regulation_revision),
                "an exact official source manifest binding the target path, bytes, count, regulation, and revision",
                "bind the reviewed official manifest before treating the target population as final",
            )
        )

    for member in mapping["members"]:
        subject = _stable_subject("mapping", member["target_key"])
        status = member["resolution_status"]
        if status == "unresolved":
            blockers.append(
                _blocker(
                    "mapping",
                    "authoritative_mapping_missing",
                    subject,
                    "an authoritative namespace/entity/form/variant record bound to this exact target",
                    "add reviewed source evidence without shrinking the fixed target denominator",
                )
            )
        elif status == "conflict":
            blockers.append(
                _blocker(
                    "mapping",
                    "candidate_mapping_conflict",
                    subject,
                    "a reviewed decision resolving every conflicting namespace-safe candidate",
                    "record the decision and immutable evidence hashes for the selected form",
                )
            )
        else:
            blockers.append(
                _blocker(
                    "mapping",
                    "candidate_mapping_unreviewed",
                    subject,
                    "a human-reviewed mapping decision with source record hash",
                    "bind the exact namespace, entity, form, and variant in a review record",
                )
            )
        if not member["source_entities"] or any(
            value["form_id"] is None or value["variant_id"] is None
            for value in member["source_entities"]
        ):
            blockers.append(
                _blocker(
                    "mapping",
                    "namespace_form_identity_incomplete",
                    subject,
                    "explicit source namespace, entity ID, form ID, and variant ID",
                    "supply an exact form-aware identity rather than a name or dex-number guess",
                )
            )
        blockers.append(
            _blocker(
                "mapping",
                "mapping_permission_unresolved",
                subject,
                "source-specific permission allowing the mapped facts in the intended production scope",
                "approve the source policy and attach the decision before promotion",
            )
        )

    for group in (
        "species",
        "moves",
        "abilities",
        "items",
        "types",
        "mega_relations",
    ):
        for entity in catalog[group]:
            raw_id = (
                entity.get("target_key")
                or entity.get("entity_id")
                or entity.get("relation_id")
                or canonical_sha256(entity)[:24]
            )
            for field_name, field in sorted(entity["fields"].items()):
                subject = _stable_subject("catalog", group, raw_id, field_name)
                status = field["status"]
                if status == "missing":
                    code = "catalog_field_missing"
                    evidence = "a value from a reviewed source record with field-level provenance"
                    restart = "supply and review the missing field without substituting a default"
                elif status == "unknown_semantics":
                    code = "catalog_field_unknown_semantics"
                    evidence = "a structured semantic contract plus an executable handler and tests"
                    restart = "lower the source meaning explicitly and validate it against evidence"
                elif status == "conflict":
                    code = "catalog_field_conflict"
                    evidence = "a reviewed resolution of all conflicting field values"
                    restart = "record the selected value and the decision evidence"
                else:
                    code = "catalog_field_unverified"
                    evidence = "field-level reviewed evidence whose usage permission is approved"
                    restart = "review the candidate value and bind its exact source record hash"
                blockers.append(
                    _blocker("catalog", code, subject, evidence, restart)
                )

    global_gaps = (
        (
            "mechanics",
            "runtime_handler_coverage_incomplete",
            "global:runtime_handlers",
            "reviewed handlers for every reachable structured effect",
            "implement fail-closed handlers and generated boundary scenarios",
        ),
        (
            "scenario",
            "scenario_coverage_incomplete",
            "global:scenario_corpus",
            "coverage-linked deterministic scenarios for every reachable mechanic",
            "generate, review, and seal the scenario corpus",
        ),
        (
            "grounding",
            "private_match_grounding_missing",
            "global:private_match_grounding",
            "anonymized private-match observations with Git-external payload hashes",
            "collect read-only observations and pass differential conformance",
        ),
        (
            "holdout",
            "external_holdout_missing",
            "global:external_holdout",
            "an independently authored and lineage-separated holdout corpus",
            "seal and evaluate the holdout without development leakage",
        ),
        (
            "trust",
            "production_attestation_missing",
            "global:production_trust",
            "a valid production trust attestation over approved promotion inputs",
            "complete all evidence gates before issuing a trust attestation",
        ),
        (
            "rehearsal",
            "regulation_rehearsal_missing",
            "global:regulation_rehearsal",
            "a successful archived or synthetic regulation-change rehearsal within 48 hours",
            "run the sealed update workflow and retain only metadata-sized Git artifacts",
        ),
    )
    blockers.extend(_blocker(*value) for value in global_gaps)
    blockers = _sorted_unique_blockers(blockers)
    stage_counts = Counter(value.stage for value in blockers)
    code_counts = Counter(value.code for value in blockers)
    summary = {
        "decision": "NO-GO",
        "candidate_for_production_promotion": False,
        "fixed_target_denominator": mapping["summary"]["target_member_count"],
        "verified_mapping_count": mapping["summary"]["verified_count"],
        "verified_catalog_field_count": catalog["summary"]["verified_field_count"],
        "blocker_enumeration_scope": (
            "declared_workbench_surfaces_and_known_gap_hints"
        ),
        "blocker_enumeration_complete": True,
        "assessment_blocker_enumeration_rate_ppm": 1_000_000,
        "undeclared_dependency_enumeration_complete": False,
        "blocker_count": len(blockers),
        "stage_blocker_counts": dict(sorted(stage_counts.items())),
        "code_blocker_counts": dict(sorted(code_counts.items())),
    }
    unsigned = {
        "schema_version": AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
        "compiler_version": AUTHORITATIVE_INTAKE_COMPILER_VERSION,
        "assessment_id": f"authoritative-intake-assessment:{plan['plan_id']}",
        "plan_id": plan["plan_id"],
        "regulation_id": plan["regulation_id"],
        "regulation_revision": regulation_revision,
        "target_pool_hash": target_pool_hash,
        "target_source_manifest_hash": target_source_manifest_hash,
        "source_review_hash": source_review["review_hash"],
        "mapping_workbench_hash": mapping["mapping_workbench_hash"],
        "catalog_workbench_hash": catalog["catalog_workbench_hash"],
        "authorization_status": "not_authorization",
        "blockers": [value.to_data() for value in blockers],
        "summary": summary,
    }
    return {**unsigned, "assessment_hash": canonical_sha256(unsigned)}


def write_authoritative_intake_documents(
    compilation: AuthoritativeIntakeCompilation,
    output_root: Path | str,
) -> Path:
    """Write immutable, content-addressed workbench documents.

    The function never emits a promotion request or production Catalog.  An
    existing object is accepted only when every byte is identical.
    """

    snapshot = compilation.validated_snapshot()

    root = Path(output_root).expanduser()
    if root.exists() and root.is_symlink():
        raise AuthoritativeIntakeError("output root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    destination = root / snapshot.compilation_hash
    if destination.exists() and destination.is_symlink():
        raise AuthoritativeIntakeError("content-addressed output must not be a symlink")
    documents: dict[str, Mapping[str, Any]] = {
        **snapshot.document_map,
        "authoritative-intake-compilation.json": snapshot.summary_data(),
    }
    payloads = {
        name: (canonical_json(value) + "\n").encode("utf-8")
        for name, value in sorted(documents.items())
    }
    if destination.exists():
        _verify_content_addressed_output(destination, payloads)
        return destination

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{snapshot.compilation_hash}.tmp-",
            dir=root,
        )
    )
    try:
        for name, payload in payloads.items():
            path = staging / name
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        try:
            staging.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            _verify_content_addressed_output(destination, payloads)
        else:
            staging = destination
        _verify_content_addressed_output(destination, payloads)
    finally:
        if staging != destination and staging.exists():
            shutil.rmtree(staging)
    return destination


def _verify_content_addressed_output(
    destination: Path,
    payloads: Mapping[str, bytes],
) -> None:
    if destination.is_symlink() or not destination.is_dir():
        raise AuthoritativeIntakeError(
            "content-addressed output must be a non-symlink directory"
        )
    unexpected = sorted(
        value.name for value in destination.iterdir() if value.name not in payloads
    )
    if unexpected:
        raise AuthoritativeIntakeError(
            f"content-addressed output contains unexpected entries: {unexpected}"
        )
    for name, payload in payloads.items():
        path = destination / name
        if (
            not path.is_file()
            or path.is_symlink()
            or path.read_bytes() != payload
        ):
            raise AuthoritativeIntakeError(
                f"content-addressed output collision: {name}"
            )


def _audit_raw_manifest(
    *,
    artifact_id: str,
    route_id: str,
    root: Path,
    root_kind: str,
    manifest: Mapping[str, Any],
    manifest_relative_path: str,
    expected_source_id: str | None,
    inventory_id: str | None,
    inventory_declaration: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[IntakeBlocker]]:
    blockers: list[IntakeBlocker] = []
    inventory_path_mismatch_count = 0
    if inventory_id is None:
        blockers.append(
            _blocker(
                "acquisition",
                "raw_manifest_inventory_binding_missing",
                _stable_subject(route_id, artifact_id),
                "a source-specific raw inventory ID bound to the manifest",
                "bind this manifest to exactly one declared raw inventory",
            )
        )
    elif inventory_declaration is None:
        blockers.append(
            _blocker(
                "acquisition",
                "raw_manifest_inventory_binding_invalid",
                _stable_subject(route_id, artifact_id),
                "an inventory_id declared by the same source route",
                "correct the manifest-to-inventory binding in the reviewed plan",
            )
        )
    source_id = manifest.get("source_id")
    source_id_is_stable = (
        type(source_id) is str
        and _STABLE_ID_PATTERN.fullmatch(source_id) is not None
    )
    source_identity_status = (
        "verified"
        if source_id_is_stable
        and source_id == expected_source_id
        else "mismatch"
    )
    if type(source_id) is not str or not source_id:
        source_id = expected_source_id or "unknown_source"
        blockers.append(
            _blocker(
                "acquisition",
                "raw_manifest_source_missing",
                _stable_subject(route_id, "raw_manifest"),
                "a stable source_id in the raw manifest",
                "regenerate the manifest with explicit source identity",
            )
        )
    elif not source_id_is_stable:
        # The exact hostile value remains sealed by the manifest artifact hash;
        # never copy an unbounded/control-bearing identifier into review output.
        source_id = "invalid_source_id"
    values = manifest.get("results")
    if type(values) is not list:
        values = []
        blockers.append(
            _blocker(
                "acquisition",
                "raw_manifest_results_missing",
                _stable_subject(route_id, source_id),
                "a results array binding every payload to its saved path",
                "regenerate the raw manifest before reviewing acquisition integrity",
            )
        )
    elif not values:
        blockers.append(
            _blocker(
                "acquisition",
                "raw_manifest_results_empty",
                _stable_subject(route_id, source_id),
                "at least one acquired payload bound to the raw manifest",
                "reacquire or restore the payload before claiming route completeness",
            )
        )
    result_count = len(values)
    saved_count = 0
    sealed_count = 0
    missing_count = 0
    byte_mismatch_count = 0
    hash_mismatch_count = 0
    unmanifested_file_count = 0
    duplicate_saved_path_count = 0
    identities: list[dict[str, Any]] = []
    manifested_path_set: set[str] = set()
    for index, raw in enumerate(values):
        if type(raw) is not dict:
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_result_invalid",
                    _stable_subject(route_id, source_id, index),
                    "an object describing the raw acquisition result",
                    "regenerate the malformed manifest result",
                )
            )
            continue
        relative = raw.get("saved_to")
        subject = _stable_subject(route_id, source_id, index)
        if type(relative) is not str or not relative:
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_saved_path_missing",
                    subject,
                    "a safe repository-relative saved_to path",
                    "bind the result to its exact local payload",
                )
            )
            continue
        path = _try_resolve_path(root, relative)
        if path is None or not path.is_file():
            missing_count += 1
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_saved_file_missing",
                    subject,
                    "the raw payload declared by saved_to",
                    "restore or reacquire the exact payload and reseal the manifest",
                )
            )
            continue
        _reject_symlink_path(root, path)
        saved_count += 1
        canonical_relative = path.relative_to(root).as_posix()
        duplicate_saved_path = canonical_relative in manifested_path_set
        if duplicate_saved_path:
            duplicate_saved_path_count += 1
            inventory_path_mismatch_count += 1
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_duplicate_saved_path",
                    subject,
                    "each canonical saved_to path appearing exactly once",
                    "deduplicate the manifest results without changing payload bytes",
                )
            )
        else:
            manifested_path_set.add(canonical_relative)
        if (
            inventory_declaration is not None
            and not _payload_is_declared_by_inventory(
                canonical_relative, (inventory_declaration,)
            )
        ):
            inventory_path_mismatch_count += 1
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_payload_outside_inventory",
                    subject,
                    "every manifested payload inside a declared raw inventory",
                    "bind the route to the matching raw inventory or correct saved_to",
                )
            )
        payload = _read_confined_bytes(root, path, f"raw payload {relative}")
        actual_bytes = len(payload)
        actual_hash = hashlib.sha256(payload).hexdigest()
        if not duplicate_saved_path:
            identities.append(
                {
                    "relative_path": canonical_relative,
                    "byte_count": actual_bytes,
                    "sha256": actual_hash,
                }
            )
        declared_bytes = raw.get("bytes")
        if type(declared_bytes) is int and not isinstance(declared_bytes, bool):
            if declared_bytes != actual_bytes:
                byte_mismatch_count += 1
                blockers.append(
                    _blocker(
                        "acquisition",
                        "raw_manifest_byte_count_mismatch",
                        subject,
                        "the declared byte count matching the saved payload",
                        "correct the manifest only from the immutable source payload",
                    )
                )
        else:
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_result_unsealed",
                    subject,
                    "a non-negative payload byte count and lowercase SHA-256",
                    "compute and review payload identity without changing the source bytes",
                )
            )
        declared_hash = raw.get("sha256")
        if type(declared_hash) is str and re.fullmatch(r"[0-9a-f]{64}", declared_hash):
            if declared_hash != actual_hash:
                hash_mismatch_count += 1
                blockers.append(
                    _blocker(
                        "acquisition",
                        "raw_manifest_hash_mismatch",
                        subject,
                        "the declared SHA-256 matching the saved payload",
                        "restore the exact payload or issue a separately reviewed manifest",
                    )
                )
            elif type(declared_bytes) is int and declared_bytes == actual_bytes:
                sealed_count += 1
        elif type(declared_bytes) is int:
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_result_unsealed",
                    subject,
                    "a lowercase SHA-256 for the exact payload",
                    "hash and review the payload before any downstream use",
                )
            )
    if inventory_declaration is not None:
        inventory_path = _try_resolve_path(
            root, inventory_declaration["relative_path"]
        )
        inventory_files: set[str] = set()
        if inventory_path is None or not inventory_path.is_dir():
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_manifest_inventory_directory_missing",
                    _stable_subject(route_id, artifact_id),
                    "the bound raw inventory directory",
                    "restore the bound inventory before reviewing the manifest",
                )
            )
        else:
            _reject_symlink_path(root, inventory_path)
            suffixes = set(inventory_declaration["suffixes"])
            for item in sorted(
                inventory_path.rglob("*"), key=lambda value: value.as_posix()
            ):
                if item.is_symlink():
                    raise AuthoritativeIntakeError(
                        f"raw inventory contains a symlink: {item}"
                    )
                if not item.is_file() or (suffixes and item.suffix not in suffixes):
                    continue
                relative_item = item.relative_to(root).as_posix()
                if relative_item != manifest_relative_path:
                    inventory_files.add(relative_item)
        manifested_files = {
            value["relative_path"] for value in identities
        }
        unmanifested_files = sorted(inventory_files - manifested_files)
        unmanifested_file_count = len(unmanifested_files)
        if unmanifested_files:
            inventory_path_mismatch_count += len(unmanifested_files)
            blockers.append(
                _blocker(
                    "acquisition",
                    "raw_inventory_contains_unmanifested_payload",
                    _stable_subject(route_id, artifact_id, "inventory_union"),
                    "the bound inventory equal to the manifest payload set",
                    "manifest or remove unbound payloads: "
                    + ", ".join(unmanifested_files[:5]),
                )
            )
    blockers = _sorted_unique_blockers(blockers)
    inventory_binding_status = (
        "missing"
        if inventory_id is None or inventory_declaration is None
        else "mismatch"
        if inventory_path_mismatch_count
        else "verified"
    )
    audit = {
        "artifact_id": artifact_id,
        "source_id": str(source_id),
        "expected_source_id": expected_source_id,
        "source_identity_status": source_identity_status,
        "root_kind": root_kind,
        "inventory_id": inventory_id,
        "inventory_binding_status": inventory_binding_status,
        "integrity_status": (
            "verified"
            if not blockers and source_identity_status == "verified"
            else "incomplete"
        ),
        "result_count": result_count,
        "saved_file_count": saved_count,
        "sealed_result_count": sealed_count,
        "missing_file_count": missing_count,
        "byte_mismatch_count": byte_mismatch_count,
        "hash_mismatch_count": hash_mismatch_count,
        "duplicate_saved_path_count": duplicate_saved_path_count,
        "unmanifested_file_count": unmanifested_file_count,
        "payload_inventory_hash": canonical_sha256(
            sorted(identities, key=lambda value: value["relative_path"])
        ),
    }
    return audit, blockers


def _payload_is_declared_by_inventory(
    relative_path: str,
    declarations: Sequence[Mapping[str, Any]],
) -> bool:
    payload = PurePosixPath(relative_path)
    for declaration in declarations:
        inventory = PurePosixPath(declaration["relative_path"])
        if payload != inventory and inventory not in payload.parents:
            continue
        suffixes = declaration["suffixes"]
        if not suffixes or payload.suffix in suffixes:
            return True
    return False


def _source_covering_evidence_roles(semantic_authority: str) -> frozenset[str]:
    if semantic_authority in _EXTERNAL_AUTHORITIES or semantic_authority == "private_observation":
        return frozenset({"raw_manifest"})
    if semantic_authority == "local_implementation":
        return frozenset({"implementation"})
    raise AuthoritativeIntakeError(
        f"unsupported semantic authority profile: {semantic_authority}"
    )


def _inventory_raw_root(
    *,
    route_id: str,
    root: Path,
    root_kind: str,
    declaration: Mapping[str, Any],
    excluded_relative_paths: set[str] | frozenset[str] = frozenset(),
    occupied_file_owners: dict[tuple[int, int], str] | None = None,
    occupied_hashes: set[str] | None = None,
    occupied_role_by_hash: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[IntakeBlocker]]:
    blockers: list[IntakeBlocker] = []
    relative = declaration["relative_path"]
    path = _try_resolve_path(root, relative)
    identities: list[dict[str, Any]] = []
    suffixes = set(declaration["suffixes"])
    if path is None or not path.is_dir():
        blockers.append(
            _blocker(
                "acquisition",
                "raw_inventory_missing",
                _stable_subject(route_id, declaration["inventory_id"]),
                "the declared Git-external raw inventory directory",
                "restore the directory and rerun the deterministic inventory",
            )
        )
    else:
        _reject_symlink_path(root, path)
        for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
            if item.is_symlink():
                raise AuthoritativeIntakeError(
                    f"raw inventory contains a symlink: {item}"
                )
            if not item.is_file() or (suffixes and item.suffix not in suffixes):
                continue
            relative_item = item.relative_to(root).as_posix()
            if relative_item in excluded_relative_paths:
                continue
            payload, file_key = _read_confined_snapshot(
                root,
                item,
                f"raw inventory payload {relative_item}",
            )
            payload_hash = hashlib.sha256(payload).hexdigest()
            if occupied_file_owners is not None:
                prior_owner = occupied_file_owners.get(file_key)
                owner = (
                    f"{route_id}:raw_inventory:{declaration['inventory_id']}:"
                    f"{relative_item}"
                )
                if prior_owner is not None:
                    raise AuthoritativeIntakeError(
                        "one opened file cannot satisfy multiple evidence, raw, or "
                        f"derived artifacts: {prior_owner} and {owner}"
                    )
                occupied_file_owners[file_key] = owner
            if occupied_role_by_hash is not None:
                prior_role = occupied_role_by_hash.get(payload_hash)
                if prior_role is not None and prior_role != "raw_payload":
                    raise AuthoritativeIntakeError(
                        "identical bytes cannot satisfy different evidence, raw, or "
                        f"derived roles: {prior_role} and raw_payload"
                    )
                occupied_role_by_hash[payload_hash] = "raw_payload"
            if occupied_hashes is not None:
                occupied_hashes.add(payload_hash)
            identities.append(
                {
                    "relative_path": relative_item,
                    "byte_count": len(payload),
                    "sha256": payload_hash,
                }
            )
    if len(identities) < declaration["expected_min_files"]:
        blockers.append(
            _blocker(
                "acquisition",
                "raw_inventory_too_small",
                _stable_subject(route_id, declaration["inventory_id"]),
                f"at least {declaration['expected_min_files']} matching raw files",
                "restore the declared corpus or revise the plan through review",
            )
        )
    result = {
        "inventory_id": declaration["inventory_id"],
        "root_kind": root_kind,
        "relative_path": relative,
        "suffixes": list(declaration["suffixes"]),
        "expected_min_files": declaration["expected_min_files"],
        "file_count": len(identities),
        "byte_count": sum(value["byte_count"] for value in identities),
        "inventory_hash": canonical_sha256(identities),
    }
    return result, _sorted_unique_blockers(blockers)


def _audit_derived_artifact(
    *,
    route_id: str,
    root: Path,
    root_kind: str,
    declaration: Mapping[str, Any],
    semantic_authority: str,
    evidence_by_id: Mapping[str, ArtifactIdentity],
    occupied_file_owners: dict[tuple[int, int], str],
    occupied_hashes: set[str],
    manifest_audit_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[IntakeBlocker]]:
    blockers: list[IntakeBlocker] = []
    subject = _stable_subject(route_id, declaration["artifact_id"])
    path = _try_resolve_path(root, declaration["relative_path"])
    if path is None or not path.is_file():
        return None, [
            _blocker(
                "acquisition",
                "derived_artifact_missing",
                subject,
                "the declared processed artifact",
                "regenerate it from reviewed raw inputs and parser code",
            )
        ]
    _reject_symlink_path(root, path)
    identity, payload, file_key = _snapshot_file_identity(
        declaration["artifact_id"],
        root_kind,
        root,
        path,
        "derived_artifact",
    )
    prior_owner = occupied_file_owners.get(file_key)
    if prior_owner is not None or identity.sha256 in occupied_hashes:
        raise AuthoritativeIntakeError(
            "derived artifact must be independent from every evidence or derived "
            f"artifact; prior owner={prior_owner or 'identical-bytes'}"
        )
    occupied_file_owners[file_key] = f"{route_id}:derived:{declaration['artifact_id']}"
    occupied_hashes.add(identity.sha256)
    raw = _parse_json_object(
        payload, f"derived artifact {declaration['artifact_id']}"
    )
    expected_source = declaration["expected_source"]
    observed_source = raw.get("source")
    source_metadata_valid = observed_source is None or (
        type(observed_source) is str
        and _STABLE_ID_PATTERN.fullmatch(observed_source) is not None
    )
    actual_source = observed_source if source_metadata_valid else None
    source_identity_matches = source_metadata_valid and (
        expected_source is None or actual_source == expected_source
    )
    if not source_identity_matches:
        blockers.append(
            _blocker(
                "acquisition",
                "derived_source_mismatch",
                subject,
                f"source metadata exactly equal to {expected_source}",
                "select the matching artifact or regenerate it from the declared route",
            )
        )
    try:
        pointed = _resolve_json_pointer(raw, declaration["record_pointer"])
        if type(pointed) not in {list, dict}:
            raise AuthoritativeIntakeError("record pointer must resolve to an array or object")
        record_count = 1 if declaration["record_pointer"] == "" else len(pointed)
    except AuthoritativeIntakeError:
        record_count = 0
        blockers.append(
            _blocker(
                "acquisition",
                "derived_record_pointer_invalid",
                subject,
                "a JSON pointer resolving to the declared record collection",
                "correct the reviewed plan or regenerate the processed artifact",
            )
        )
    if record_count < declaration["expected_min_records"]:
        blockers.append(
            _blocker(
                "acquisition",
                "derived_record_count_too_small",
                subject,
                f"at least {declaration['expected_min_records']} derived records",
                "restore the full derived dataset without reducing the declared minimum",
            )
        )
    lineage, lineage_blockers = _audit_derived_lineage(
        route_id=route_id,
        declaration=declaration,
        output_identity=identity,
        record_count=record_count,
        declared_source=expected_source,
        actual_source=actual_source,
        source_identity_matches=source_identity_matches,
        semantic_authority=semantic_authority,
        evidence_by_id=evidence_by_id,
        manifest_audit_by_id=manifest_audit_by_id,
    )
    blockers.extend(lineage_blockers)
    result = {
        **identity.to_data(),
        "record_pointer": declaration["record_pointer"],
        "record_count": record_count,
        "declared_source": expected_source,
        "actual_source": actual_source,
        **lineage,
    }
    return result, _sorted_unique_blockers(blockers)


def _audit_derived_lineage(
    *,
    route_id: str,
    declaration: Mapping[str, Any],
    output_identity: ArtifactIdentity,
    record_count: int,
    declared_source: str | None,
    actual_source: str | None,
    source_identity_matches: bool,
    semantic_authority: str,
    evidence_by_id: Mapping[str, ArtifactIdentity],
    manifest_audit_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[IntakeBlocker]]:
    artifact_id = declaration["artifact_id"]
    subject = _stable_subject(route_id, artifact_id)
    gap_hint = declaration.get("lineage_gap_hint")
    gap_snapshot = (
        {
            "reason_codes": list(gap_hint["reason_codes"]),
            "parent_refs": [dict(value) for value in gap_hint["parent_refs"]],
            "unregistered_paths": list(gap_hint["unregistered_paths"]),
            "runtime_dependencies": list(gap_hint["runtime_dependencies"]),
        }
        if gap_hint is not None
        else None
    )
    empty_result = {
        "lineage_status": "missing",
        "lineage_binding_hash": None,
        "lineage_source_artifact_ids": [],
        "lineage_transform_artifact_ids": [],
        "lineage_gap_hint": gap_snapshot,
    }
    requirements = declaration.get("lineage_requirements")
    if requirements is None:
        if gap_snapshot is not None:
            parent_refs = [
                f"{value['route_id']}:{value['artifact_id']}"
                for value in gap_snapshot["parent_refs"]
            ]
            evidence_parts = [
                "reason_codes=" + ",".join(gap_snapshot["reason_codes"])
            ]
            if parent_refs:
                evidence_parts.append("parent_refs=" + ",".join(parent_refs))
            if gap_snapshot["unregistered_paths"]:
                evidence_parts.append(
                    "unregistered_paths="
                    + ",".join(gap_snapshot["unregistered_paths"])
                )
            if gap_snapshot["runtime_dependencies"]:
                evidence_parts.append(
                    "runtime_dependencies="
                    + ",".join(gap_snapshot["runtime_dependencies"])
                )
            return {
                **empty_result,
                "lineage_status": "unrepresentable",
            }, [
                _blocker(
                    "acquisition",
                    "derived_lineage_graph_unrepresentable",
                    subject,
                    "route-qualified lineage DAG closure; " + "; ".join(evidence_parts),
                    "implement the SIM-02C-B route-qualified DAG, register and hash "
                    "every listed parent, transform, intermediate, and runtime dependency, "
                    "then regenerate and replace this gap hint with sealed requirements",
                )
            ]
        return empty_result, [
            _blocker(
                "acquisition",
                "derived_lineage_requirements_missing",
                subject,
                "reviewed source and transform artifact IDs for the derived output",
                "add a reviewed lineage requirement and regenerate the artifact",
            )
        ]
    source_ids = list(requirements["source_artifact_ids"])
    transform_ids = list(requirements["transform_artifact_ids"])
    computed_lineage_hash: str | None = None
    try:
        if not source_identity_matches:
            raise AuthoritativeIntakeError("derived source identity does not match")
        source_entries: list[dict[str, Any]] = []
        source_roles: set[str] = set()
        for entry_id in source_ids:
            identity = evidence_by_id.get(entry_id)
            if identity is None:
                raise AuthoritativeIntakeError("lineage source identity missing")
            source_roles.add(identity.role)
            entry = {
                "artifact_id": identity.artifact_id,
                "relative_path": identity.relative_path,
                "role": identity.role,
                "byte_count": identity.byte_count,
                "sha256": identity.sha256,
                "source_id": None,
                "expected_source_id": None,
                "inventory_id": None,
                "payload_inventory_hash": None,
            }
            if identity.role == "raw_manifest":
                audit = manifest_audit_by_id.get(entry_id)
                if audit is None or audit["integrity_status"] != "verified":
                    raise AuthoritativeIntakeError(
                        "lineage raw manifest is not integrity-verified"
                    )
                entry["inventory_id"] = audit["inventory_id"]
                entry["source_id"] = audit["source_id"]
                entry["expected_source_id"] = audit["expected_source_id"]
                entry["payload_inventory_hash"] = audit[
                    "payload_inventory_hash"
                ]
            elif identity.role == "review_record":
                pass
            else:
                raise AuthoritativeIntakeError(
                    "unsupported derived lineage source role"
                )
            source_entries.append(entry)

        transform_entries: list[dict[str, Any]] = []
        transform_roles: set[str] = set()
        for entry_id in transform_ids:
            identity = evidence_by_id.get(entry_id)
            if identity is None:
                raise AuthoritativeIntakeError("lineage transform identity missing")
            transform_roles.add(identity.role)
            transform_entries.append(
                {
                    "artifact_id": identity.artifact_id,
                    "relative_path": identity.relative_path,
                    "role": identity.role,
                    "byte_count": identity.byte_count,
                    "sha256": identity.sha256,
                }
            )

        if semantic_authority in _EXTERNAL_AUTHORITIES or semantic_authority == "private_observation":
            if source_roles != {"raw_manifest"}:
                raise AuthoritativeIntakeError(
                    "corpus lineage sources must be raw manifests"
                )
            if (
                not transform_roles <= _DERIVED_TRANSFORM_ROLES
                or not transform_roles.intersection({"builder", "parser"})
            ):
                raise AuthoritativeIntakeError(
                    "corpus lineage requires a parser or builder"
                )
        elif semantic_authority == "local_implementation":
            if source_roles != {"review_record"} or not {
                "implementation",
                "validator",
            } <= transform_roles:
                raise AuthoritativeIntakeError(
                    "local lineage requires review, implementation, and validator"
                )
        else:
            raise AuthoritativeIntakeError("unsupported lineage authority profile")
        binding = {
            "binding_domain": "sim02c-derived-lineage-v2",
            "schema_version": "2.0.0",
            "route_id": route_id,
            "output": {
                "artifact_id": output_identity.artifact_id,
                "relative_path": output_identity.relative_path,
                "byte_count": output_identity.byte_count,
                "sha256": output_identity.sha256,
                "record_count": record_count,
                "declared_source": declared_source,
                "actual_source": actual_source,
            },
            "source_artifacts": source_entries,
            "transform_artifacts": transform_entries,
        }
        computed_lineage_hash = canonical_sha256(binding)
        if computed_lineage_hash != requirements["expected_lineage_hash"]:
            raise AuthoritativeIntakeError("derived lineage binding hash mismatch")
    except (AuthoritativeIntakeError, KeyError, TypeError):
        return {
            **empty_result,
            "lineage_status": "invalid",
            "lineage_binding_hash": computed_lineage_hash,
            "lineage_source_artifact_ids": source_ids,
            "lineage_transform_artifact_ids": transform_ids,
        }, [
            _blocker(
                "acquisition",
                "derived_lineage_invalid",
                subject,
                "exact source payload, manifest, inventory, and transform hashes",
                "regenerate the artifact from the reviewed chain and reseal lineage",
            )
        ]

    return {
        "lineage_status": "snapshot_bound",
        "lineage_binding_hash": computed_lineage_hash,
        "lineage_source_artifact_ids": source_ids,
        "lineage_transform_artifact_ids": transform_ids,
        "lineage_gap_hint": None,
    }, []


def _policy_blockers(
    route: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[IntakeBlocker]:
    route_id = route["route_id"]
    blockers: list[IntakeBlocker] = []
    if list(route["source_ids"]) != list(policy["source_ids"]):
        blockers.append(
            _blocker(
                "policy",
                "source_policy_binding_mismatch",
                _stable_subject(route_id, policy["policy_id"]),
                "an exact source-ID binding between the acquisition route and policy review",
                "review the intended source set and issue a policy entry bound to those exact IDs",
            )
        )
    if policy["review_status"] != "approved":
        blockers.append(
            _blocker(
                "policy",
                "source_policy_review_unresolved",
                _stable_subject(route_id, policy["policy_id"]),
                "an approved, source-specific usage review",
                "record the review decision and immutable evidence URLs",
            )
        )
    if policy["collection_status"] != "allowed":
        blockers.append(
            _blocker(
                "policy",
                "source_collection_not_approved",
                _stable_subject(route_id, policy["policy_id"]),
                "explicit approval for the declared collection method",
                "keep acquisition disabled until the source-specific review allows it",
            )
        )
    if policy["candidate_use"] != "allowed":
        blockers.append(
            _blocker(
                "policy",
                "source_candidate_use_restricted",
                _stable_subject(route_id, policy["policy_id"]),
                "permission for candidate use in the intended scope",
                "retain the corpus locally and resolve the policy before materialization",
            )
        )
    if policy["private_match_use"] != "allowed":
        blockers.append(
            _blocker(
                "policy",
                "source_private_match_use_not_allowed",
                _stable_subject(route_id, policy["policy_id"]),
                "explicit permission for use in the private-match execution scope",
                "keep the source out of private-match runtime inputs until reviewed as allowed",
            )
        )
    if policy["training_use"] != "allowed":
        blockers.append(
            _blocker(
                "policy",
                "source_training_use_not_allowed",
                _stable_subject(route_id, policy["policy_id"]),
                "explicit permission for model training and optimization use",
                "exclude the source from training until a source-specific review allows it",
            )
        )
    if policy["redistribution"] != "allowed":
        blockers.append(
            _blocker(
                "policy",
                "source_redistribution_prohibited",
                _stable_subject(route_id, policy["policy_id"]),
                "explicit permission to redistribute source payload or derived protected content",
                "keep payloads Git-external and publish only permitted metadata",
            )
        )
    if policy["production_promotion"] != "allowed":
        blockers.append(
            _blocker(
                "policy",
                "source_production_promotion_blocked",
                _stable_subject(route_id, policy["policy_id"]),
                "an approved production-promotion decision for the exact source role",
                "complete source review before constructing any V2/V3 production input",
            )
        )
    return blockers


def _route_permission_is_resolved(route_review: Mapping[str, Any]) -> bool:
    permission = route_review["usage_permission"]
    return (
        list(route_review["source_ids"]) == list(permission["source_ids"])
        and permission["review_status"] == "approved"
        and permission["collection_status"] == "allowed"
        and permission["candidate_use"] == "allowed"
        and permission["private_match_use"] == "allowed"
        and permission["training_use"] == "allowed"
        and permission["redistribution"] == "allowed"
        and permission["production_promotion"] == "allowed"
    )


def _dataset_items(
    documents: Mapping[str, Mapping[str, Any]], artifact_id: str
) -> list[dict[str, Any]]:
    raw = documents[artifact_id]
    items = raw.get("items")
    if type(items) is not list or any(type(value) is not dict for value in items):
        raise AuthoritativeIntakeError(
            f"intake artifact {artifact_id} must contain an items array of objects"
        )
    return items


def _load_strict_intake_snapshot(
    roots: Mapping[str, Path],
    intake: CatalogIntakeBundle,
) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for artifact in intake.artifacts:
        root = roots.get(artifact.root_kind)
        if root is None:
            raise AuthoritativeIntakeError(
                f"intake artifact has unsupported root_kind: {artifact.artifact_id}"
            )
        path = _resolve_path(
            root,
            artifact.relative_path,
            f"intake artifact {artifact.artifact_id}",
        )
        payload = _read_confined_bytes(
            root,
            path,
            f"intake artifact {artifact.artifact_id}",
        )
        if len(payload) != artifact.byte_count:
            raise AuthoritativeIntakeError(
                f"intake artifact changed after frozen intake: {artifact.artifact_id}"
            )
        if hashlib.sha256(payload).hexdigest() != artifact.sha256:
            raise AuthoritativeIntakeError(
                f"intake artifact hash changed after frozen intake: {artifact.artifact_id}"
            )
        documents[artifact.artifact_id] = _parse_json_object(
            payload,
            f"intake artifact {artifact.artifact_id}",
        )
    return documents


def _validate_source_lock_document(
    expected_inventory: Mapping[str, Any],
    raw: Mapping[str, Any],
) -> None:
    artifacts = raw.get("artifacts")
    if type(artifacts) is not list:
        raise AuthoritativeIntakeError("source lock artifacts must be an array")
    document_by_id: dict[str, Mapping[str, Any]] = {}
    for index, value in enumerate(artifacts):
        if type(value) is not dict or type(value.get("artifact_id")) is not str:
            raise AuthoritativeIntakeError(
                f"source lock artifacts[{index}] has no artifact_id"
            )
        identity = value["artifact_id"]
        if identity in document_by_id:
            raise AuthoritativeIntakeError(
                f"duplicate source-lock artifact_id: {identity}"
            )
        document_by_id[identity] = value
    if set(document_by_id) != set(expected_inventory):
        raise AuthoritativeIntakeError(
            "source lock changed while its inventory was being resolved"
        )
    for artifact_id, expected in expected_inventory.items():
        value = document_by_id[artifact_id]
        projection = {
            "artifact_id": expected.artifact_id,
            "root_kind": expected.root_kind,
            "relative_path": expected.relative_path,
            "sha256": expected.sha256,
            "byte_count": expected.byte_count,
            "record_count": expected.record_count,
        }
        if dict(value) != projection:
            raise AuthoritativeIntakeError(
                f"source lock changed while resolving {artifact_id}"
            )


def _validate_source_review_intake_snapshot(
    source_review: Mapping[str, Any],
    intake: CatalogIntakeBundle,
) -> None:
    reviewed: dict[tuple[str, str], tuple[int, str]] = {}
    for route in source_review["routes"]:
        for value in route["derived_artifacts"]:
            key = (value["root_kind"], value["relative_path"])
            identity = (value["byte_count"], value["sha256"])
            previous = reviewed.get(key)
            if previous is not None and previous != identity:
                raise AuthoritativeIntakeError(
                    f"source review contains conflicting artifact snapshots: {key}"
                )
            reviewed[key] = identity
    for artifact in intake.artifacts:
        key = (artifact.root_kind, artifact.relative_path)
        identity = reviewed.get(key)
        if identity is not None and identity != (
            artifact.byte_count,
            artifact.sha256,
        ):
            raise AuthoritativeIntakeError(
                f"source artifact changed between review and intake: {artifact.artifact_id}"
            )


def _index_records(
    values: Iterable[Mapping[str, Any]], key: str, label: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, value in enumerate(values):
        if key not in value or isinstance(value[key], bool) or not isinstance(
            value[key], (str, int)
        ):
            raise AuthoritativeIntakeError(f"{label}[{index}] has no valid {key}")
        identity = str(value[key])
        if not identity or identity in result:
            raise AuthoritativeIntakeError(f"duplicate or empty {label} {key}")
        result[identity] = value
    return result


def _candidate_field(
    record: Mapping[str, Any] | None,
    key: str,
    source_refs: Sequence[str],
    *,
    nullable: bool = False,
) -> dict[str, Any]:
    if record is None or key not in record or (record[key] is None and not nullable):
        return _missing_field(f"source record does not provide {key}")
    return {
        "status": "candidate_unreviewed",
        "value": record[key],
        "source_refs": list(source_refs),
        "note": "candidate value; source role, permission, and field meaning are unreviewed",
    }


def _nested_candidate_field(
    record: Mapping[str, Any] | None,
    keys: Sequence[str],
    source_refs: Sequence[str],
) -> dict[str, Any]:
    current: Any = record
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return _missing_field(f"source record does not provide {'.'.join(keys)}")
        current = current[key]
    return {
        "status": "candidate_unreviewed",
        "value": current,
        "source_refs": list(source_refs),
        "note": "nested candidate value; not reviewed for runtime semantics",
    }


def _missing_field(note: str) -> dict[str, Any]:
    return {"status": "missing", "value": None, "source_refs": [], "note": note}


def _unknown_field(note: str, source_refs: Sequence[str]) -> dict[str, Any]:
    return {
        "status": "unknown_semantics",
        "value": None,
        "source_refs": list(source_refs),
        "note": note,
    }


def _form_relation_field(
    record: Mapping[str, Any] | None, source_refs: Sequence[str]
) -> dict[str, Any]:
    if record is None:
        return _missing_field("no mapped species record exists")
    if "mega_evolution_ids" not in record:
        return _missing_field("source record has no explicit form-relation field")
    return {
        "status": "candidate_unreviewed",
        "value": {"mega_evolution_ids": record["mega_evolution_ids"]},
        "source_refs": list(source_refs),
        "note": "candidate relation uses legacy site IDs and has not been form-reviewed",
    }


def _build_mega_relation_candidates(
    species: Sequence[Mapping[str, Any]],
    pokemon_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    relations: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in species:
        base_id = entity["catalog_candidate_id"]
        if base_id is None:
            continue
        base_key = str(base_id)
        base = pokemon_by_id.get(base_key)
        if base is None:
            continue
        values = base.get("mega_evolution_ids", [])
        if type(values) is not list:
            raise AuthoritativeIntakeError("mega_evolution_ids must be an array")
        base_hash = canonical_sha256(base)
        base_refs = [f"legacy-pokemon:{base_key}:{base_hash}"]
        for raw_mega_id in values:
            if isinstance(raw_mega_id, bool) or not isinstance(raw_mega_id, (str, int)):
                raise AuthoritativeIntakeError("mega_evolution_ids must contain IDs")
            mega_id = str(raw_mega_id)
            key = (base_key, mega_id)
            mega = pokemon_by_id.get(mega_id)
            mega_hash = canonical_sha256(mega) if mega is not None else None
            mega_refs = (
                [f"legacy-pokemon:{mega_id}:{mega_hash}"] if mega_hash is not None else []
            )
            relations[key] = {
                "relation_id": _stable_subject("mega", base_key, mega_id),
                "base_catalog_candidate_id": base_key,
                "mega_catalog_candidate_id": mega_id,
                "fields": {
                    "base_form": {
                        "status": "candidate_unreviewed",
                        "value": base_key,
                        "source_refs": base_refs,
                        "note": "legacy namespace candidate; not a reviewed Champions form ID",
                    },
                    "mega_form": (
                        {
                            "status": "candidate_unreviewed",
                            "value": mega_id,
                            "source_refs": mega_refs,
                            "note": "legacy namespace candidate; not a reviewed Champions form ID",
                        }
                        if mega is not None
                        else _missing_field("referenced Mega record is missing")
                    ),
                    "required_item": _missing_field(
                        "legacy relation contains no reviewed Mega Stone identity"
                    ),
                    "base_stats": _missing_field(
                        "legacy record does not provide reviewed species base stats"
                    ),
                    "mega_stats": _missing_field(
                        "legacy record does not provide reviewed Mega base stats"
                    ),
                    "types": _candidate_field(mega, "type_ids", mega_refs),
                    "ability": _candidate_field(mega, "abilities", mega_refs),
                },
                "runtime_lowering_status": "blocked",
            }
    return [relations[key] for key in sorted(relations)]


def _validate_route(route: Mapping[str, Any], index: int) -> None:
    label = f"routes[{index}]"
    _exact_keys(route, _ROUTE_KEYS, label)
    route_id = _string(route["route_id"], f"{label}.route_id")
    require_stable_id(route_id, f"{label}.route_id")
    if route["root_kind"] not in {"repository", "legacy"}:
        raise AuthoritativeIntakeError(f"{label}.root_kind is unsupported")
    if route["semantic_authority"] not in {
        "champions_official",
        "general_official",
        "third_party_reference",
        "local_implementation",
        "private_observation",
    }:
        raise AuthoritativeIntakeError(f"{label}.semantic_authority is unsupported")
    require_stable_id(_string(route["source_kind"], f"{label}.source_kind"), "source_kind")
    require_stable_id(_string(route["policy_id"], f"{label}.policy_id"), "policy_id")
    route_source_ids = set(
        _sorted_string_ids(
            route["source_ids"], f"{label}.source_ids", allow_empty=False
        )
    )
    locators = _sorted_strings(
        route["locators"], f"{label}.locators", allow_empty=False
    )
    if any(_LOCATOR_PATTERN.fullmatch(value) is None for value in locators):
        raise AuthoritativeIntakeError(
            f"{label}.locators must not contain control characters"
        )
    _sorted_string_ids(
        route["candidate_roles"], f"{label}.candidate_roles", allow_empty=False
    )

    authority = route["semantic_authority"]
    source_covering_roles = _source_covering_evidence_roles(authority)
    evidence_values = _array(route["evidence_files"], f"{label}.evidence_files")
    if not evidence_values:
        raise AuthoritativeIntakeError(f"{label}.evidence_files must not be empty")
    evidence_ids: list[str] = []
    evidence_paths: list[str] = []
    evidence_role_by_id: dict[str, str] = {}
    manifest_inventory_bindings: list[str] = []
    covered_source_ids: set[str] = set()
    required_evidence_count = 0
    required_roles: set[str] = set()
    for item_index, raw in enumerate(evidence_values):
        value = _object(raw, f"{label}.evidence_files[{item_index}]")
        _keys_with_optional(
            value,
            _EVIDENCE_FILE_KEYS,
            _EVIDENCE_FILE_OPTIONAL_KEYS,
            f"{label}.evidence_files[{item_index}]",
        )
        identity = _string(value["artifact_id"], "artifact_id")
        require_stable_id(identity, "artifact_id")
        evidence_ids.append(identity)
        role = _string(value["role"], "evidence role")
        if role not in _EVIDENCE_ROLES:
            raise AuthoritativeIntakeError(
                f"{label}.evidence_files[{item_index}].role is unsupported"
            )
        relative_path = _string(value["relative_path"], "relative_path")
        _safe_relative_path(relative_path)
        evidence_paths.append(relative_path)
        evidence_role_by_id[identity] = role
        inventory_id = value.get("inventory_id")
        if inventory_id is not None:
            require_stable_id(
                _string(inventory_id, "inventory_id"), "inventory_id"
            )
            if role != "raw_manifest":
                raise AuthoritativeIntakeError(
                    "only raw_manifest evidence may bind an inventory_id"
                )
            manifest_inventory_bindings.append(inventory_id)
        if type(value["required"]) is not bool:
            raise AuthoritativeIntakeError("evidence required must be boolean")
        required_evidence_count += int(value["required"])
        if value["required"]:
            required_roles.add(role)
        expected_source = value["expected_source_id"]
        if role == "raw_manifest" and expected_source is None:
            raise AuthoritativeIntakeError(
                "raw_manifest evidence requires expected_source_id"
            )
        if expected_source is not None:
            require_stable_id(_string(expected_source, "expected_source_id"), "expected_source_id")
            if expected_source not in route_source_ids:
                raise AuthoritativeIntakeError(
                    "expected_source_id must belong to the route source_ids"
                )
            if value["required"] and role in source_covering_roles:
                covered_source_ids.add(expected_source)
    if evidence_ids != sorted(evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        raise AuthoritativeIntakeError(f"{label}.evidence_files must be sorted and unique")
    if len(evidence_paths) != len(set(evidence_paths)):
        raise AuthoritativeIntakeError(
            f"{label}.evidence_files relative paths must be unique across roles"
        )
    if required_evidence_count == 0:
        raise AuthoritativeIntakeError(
            f"{label}.evidence_files requires at least one required artifact"
        )

    inventory_ids: list[str] = []
    inventory_paths: list[str] = []
    for item_index, raw in enumerate(_array(route["raw_inventories"], f"{label}.raw_inventories")):
        value = _object(raw, f"{label}.raw_inventories[{item_index}]")
        _exact_keys(value, _RAW_INVENTORY_KEYS, f"{label}.raw_inventories[{item_index}]")
        identity = _string(value["inventory_id"], "inventory_id")
        require_stable_id(identity, "inventory_id")
        inventory_ids.append(identity)
        inventory_path = _string(value["relative_path"], "relative_path")
        _safe_relative_path(inventory_path)
        inventory_paths.append(inventory_path)
        suffixes = _sorted_strings(value["suffixes"], "suffixes", allow_empty=True)
        if any(not suffix.startswith(".") for suffix in suffixes):
            raise AuthoritativeIntakeError("inventory suffixes must begin with a dot")
        if type(value["expected_min_files"]) is not int or value["expected_min_files"] <= 0:
            raise AuthoritativeIntakeError("expected_min_files must be positive")
    if inventory_ids != sorted(inventory_ids) or len(inventory_ids) != len(set(inventory_ids)):
        raise AuthoritativeIntakeError(f"{label}.raw_inventories must be sorted and unique")
    if len(inventory_paths) != len(set(inventory_paths)):
        raise AuthoritativeIntakeError(
            f"{label}.raw inventory relative paths must be unique"
        )
    unknown_inventory_bindings = sorted(
        set(manifest_inventory_bindings) - set(inventory_ids)
    )
    if unknown_inventory_bindings:
        raise AuthoritativeIntakeError(
            f"{label} raw manifests bind unknown inventory IDs: "
            f"{unknown_inventory_bindings}"
        )

    derived_ids: list[str] = []
    derived_paths: list[str] = []
    for item_index, raw in enumerate(_array(route["derived_artifacts"], f"{label}.derived_artifacts")):
        value = _object(raw, f"{label}.derived_artifacts[{item_index}]")
        _keys_with_optional(
            value,
            _DERIVED_KEYS,
            _DERIVED_OPTIONAL_KEYS,
            f"{label}.derived_artifacts[{item_index}]",
        )
        identity = _string(value["artifact_id"], "artifact_id")
        require_stable_id(identity, "artifact_id")
        derived_ids.append(identity)
        relative_path = _string(value["relative_path"], "relative_path")
        _safe_relative_path(relative_path)
        derived_paths.append(relative_path)
        pointer = value["record_pointer"]
        if (
            type(pointer) is not str
            or _RECORD_POINTER_PATTERN.fullmatch(pointer) is None
        ):
            raise AuthoritativeIntakeError(
                "record_pointer must be an RFC 6901 pointer with valid ~0/~1 escapes"
            )
        if type(value["expected_min_records"]) is not int or value["expected_min_records"] <= 0:
            raise AuthoritativeIntakeError("expected_min_records must be positive")
        expected_source = value["expected_source"]
        if expected_source is not None and (
            type(expected_source) is not str or not expected_source
        ):
            raise AuthoritativeIntakeError("expected_source must be a string or null")
        if expected_source is not None and expected_source not in route_source_ids:
            raise AuthoritativeIntakeError(
                "derived expected_source must belong to the route source_ids"
            )
        if expected_source is not None:
            covered_source_ids.add(expected_source)
        requirements = value.get("lineage_requirements")
        gap_hint = value.get("lineage_gap_hint")
        if requirements is not None and gap_hint is not None:
            raise AuthoritativeIntakeError(
                "lineage requirements and lineage_gap_hint are mutually exclusive"
            )
        if gap_hint is not None:
            gap_hint = _object(gap_hint, "lineage_gap_hint")
            _exact_keys(gap_hint, _LINEAGE_GAP_HINT_KEYS, "lineage_gap_hint")
            reason_codes = _sorted_string_ids(
                gap_hint["reason_codes"],
                "lineage gap reason_codes",
                allow_empty=False,
            )
            unknown_reasons = sorted(
                set(reason_codes) - _LINEAGE_GAP_REASON_CODES
            )
            if unknown_reasons:
                raise AuthoritativeIntakeError(
                    f"unsupported lineage gap reason codes: {unknown_reasons}"
                )
            parent_ref_keys: list[tuple[str, str]] = []
            for parent_index, parent_raw in enumerate(
                _array(gap_hint["parent_refs"], "lineage gap parent_refs")
            ):
                parent = _object(
                    parent_raw, f"lineage gap parent_refs[{parent_index}]"
                )
                _exact_keys(
                    parent,
                    {"route_id", "artifact_id"},
                    f"lineage gap parent_refs[{parent_index}]",
                )
                parent_route_id = _string(parent["route_id"], "parent route_id")
                parent_artifact_id = _string(
                    parent["artifact_id"], "parent artifact_id"
                )
                require_stable_id(parent_route_id, "parent route_id")
                require_stable_id(parent_artifact_id, "parent artifact_id")
                parent_ref_keys.append((parent_route_id, parent_artifact_id))
            if parent_ref_keys != sorted(parent_ref_keys) or len(
                parent_ref_keys
            ) != len(set(parent_ref_keys)):
                raise AuthoritativeIntakeError(
                    "lineage gap parent_refs must be sorted and unique"
                )
            unregistered_paths = _sorted_strings(
                gap_hint["unregistered_paths"],
                "lineage gap unregistered_paths",
                allow_empty=True,
            )
            for gap_path in unregistered_paths:
                _safe_relative_path(gap_path)
            runtime_dependencies = _sorted_string_ids(
                gap_hint["runtime_dependencies"],
                "lineage gap runtime_dependencies",
                allow_empty=True,
            )
            if not parent_ref_keys and not unregistered_paths and not runtime_dependencies:
                raise AuthoritativeIntakeError(
                    "lineage gap hint requires a concrete missing dependency"
                )
            if "cross_route_parent_unsupported" in reason_codes and not any(
                parent_route_id != route_id
                for parent_route_id, _parent_artifact_id in parent_ref_keys
            ):
                raise AuthoritativeIntakeError(
                    "cross-route lineage gap requires a parent in another route"
                )
        if requirements is not None:
            requirements = _object(requirements, "lineage_requirements")
            _exact_keys(
                requirements,
                _LINEAGE_REQUIREMENT_KEYS,
                "lineage_requirements",
            )
            require_sha256(
                _string(
                    requirements["expected_lineage_hash"],
                    "expected_lineage_hash",
                ),
                "expected_lineage_hash",
            )
            source_artifact_ids = _sorted_string_ids(
                requirements["source_artifact_ids"],
                "lineage source_artifact_ids",
                allow_empty=False,
            )
            transform_artifact_ids = _sorted_string_ids(
                requirements["transform_artifact_ids"],
                "lineage transform_artifact_ids",
                allow_empty=False,
            )
            lineage_ids = set(source_artifact_ids) | set(transform_artifact_ids)
            if len(lineage_ids) != len(source_artifact_ids) + len(
                transform_artifact_ids
            ):
                raise AuthoritativeIntakeError(
                    "lineage source and transform artifact IDs must be disjoint"
                )
            unknown_lineage_ids = sorted(lineage_ids - set(evidence_ids))
            if unknown_lineage_ids:
                raise AuthoritativeIntakeError(
                    f"lineage requirements reference unknown evidence: "
                    f"{unknown_lineage_ids}"
                )
            source_roles = {
                evidence_role_by_id[value] for value in source_artifact_ids
            }
            transform_roles = {
                evidence_role_by_id[value] for value in transform_artifact_ids
            }
            if authority in _EXTERNAL_AUTHORITIES or authority == "private_observation":
                if source_roles != {"raw_manifest"} or (
                    not transform_roles <= _DERIVED_TRANSFORM_ROLES
                    or not transform_roles.intersection({"builder", "parser"})
                ):
                    raise AuthoritativeIntakeError(
                        "corpus lineage requirements need raw manifests and a parser or builder"
                    )
            elif authority == "local_implementation" and (
                source_roles != {"review_record"}
                or not {"implementation", "validator"} <= transform_roles
            ):
                raise AuthoritativeIntakeError(
                    "local lineage requirements need review, implementation, and validator"
                )
    if derived_ids != sorted(derived_ids) or len(derived_ids) != len(set(derived_ids)):
        raise AuthoritativeIntakeError(f"{label}.derived_artifacts must be sorted and unique")
    overlapping_artifact_ids = sorted(set(derived_ids).intersection(evidence_ids))
    if overlapping_artifact_ids:
        raise AuthoritativeIntakeError(
            f"{label} evidence and derived artifact IDs must be disjoint: "
            f"{overlapping_artifact_ids}"
        )
    if len(derived_paths) != len(set(derived_paths)) or set(derived_paths).intersection(
        evidence_paths
    ):
        raise AuthoritativeIntakeError(
            f"{label} evidence and derived relative paths must be role-independent"
        )

    if authority in _EXTERNAL_AUTHORITIES:
        missing_roles = {"raw_manifest", "source_config"} - required_roles
        if missing_roles:
            raise AuthoritativeIntakeError(
                f"{label} external acquisition profile lacks required roles: "
                f"{sorted(missing_roles)}"
            )
        if not inventory_ids or not derived_ids:
            raise AuthoritativeIntakeError(
                f"{label} external acquisition profile requires raw inventory "
                "and derived artifact declarations"
            )
    elif authority == "private_observation":
        if "raw_manifest" not in required_roles or not inventory_ids or not derived_ids:
            raise AuthoritativeIntakeError(
                f"{label} private observation profile requires a raw manifest, "
                "raw inventory, and derived artifact"
            )
    elif authority == "local_implementation":
        missing_roles = {
            "implementation",
            "review_record",
            "validator",
        } - required_roles
        if missing_roles or not derived_ids:
            raise AuthoritativeIntakeError(
                f"{label} local implementation profile lacks required roles "
                f"{sorted(missing_roles)} or a derived review artifact"
            )
    if covered_source_ids != route_source_ids:
        missing = sorted(route_source_ids - covered_source_ids)
        raise AuthoritativeIntakeError(
            f"{label} source_ids lack declared evidence coverage: {missing}"
        )


def _validate_policy(policy: Mapping[str, Any], index: int) -> None:
    label = f"policies[{index}]"
    _exact_keys(policy, _POLICY_ENTRY_KEYS, label)
    for key in ("policy_id", "source_group"):
        require_stable_id(_string(policy[key], f"{label}.{key}"), f"{label}.{key}")
    _sorted_string_ids(policy["source_ids"], f"{label}.source_ids", allow_empty=False)
    choices = {
        "review_status": {"approved", "review_required", "rejected"},
        "collection_status": {"allowed", "manual_reference_only", "disabled_pending_review"},
        "candidate_use": {"allowed", "restricted_local", "prohibited"},
        "private_match_use": {"allowed", "review_required", "prohibited"},
        "training_use": {"allowed", "review_required", "prohibited"},
        "redistribution": {"allowed", "prohibited"},
        "production_promotion": {"allowed", "blocked"},
    }
    for key, allowed in choices.items():
        if policy[key] not in allowed:
            raise AuthoritativeIntakeError(f"{label}.{key} is unsupported")
    urls = _sorted_strings(policy["evidence_urls"], f"{label}.evidence_urls", allow_empty=False)
    for value in urls:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AuthoritativeIntakeError(f"{label}.evidence_urls contains an invalid URL")
    for key in ("decision_basis", "notes"):
        if type(policy[key]) is not str or not policy[key].strip():
            raise AuthoritativeIntakeError(f"{label}.{key} must not be empty")


def _validate_target_pool(
    raw: Mapping[str, Any], plan: Mapping[str, Any]
) -> list[dict[str, Any]]:
    keys = {
        "schema_version",
        "regulation_id",
        "regulation_revision",
        "expected_member_count",
        "source_manifest_ids",
        "members",
    }
    member_keys = {
        "national_dex_no",
        "form_code",
        "variant_code",
        "label",
        "pokemon_id",
    }
    _exact_keys(raw, keys, "target pool")
    if raw["schema_version"] != "1.0.0" or raw["regulation_id"] != plan["regulation_id"]:
        raise AuthoritativeIntakeError("target pool version or regulation mismatch")
    if type(raw["regulation_revision"]) is not str or not raw["regulation_revision"]:
        raise AuthoritativeIntakeError("target pool regulation_revision is missing")
    members = _array(raw["members"], "target pool members")
    expected = raw["expected_member_count"]
    if type(expected) is not int or isinstance(expected, bool):
        raise AuthoritativeIntakeError("expected_member_count must be an integer")
    if expected != len(members) or expected != plan["expected_target_count"]:
        raise AuthoritativeIntakeError("target pool changed the fixed target denominator")
    _sorted_string_ids(raw["source_manifest_ids"], "source_manifest_ids", allow_empty=False)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_member in enumerate(members):
        member = _object(raw_member, f"target pool members[{index}]")
        _exact_keys(member, member_keys, f"target pool members[{index}]")
        dex = member["national_dex_no"]
        if type(dex) is not int or dex <= 0:
            raise AuthoritativeIntakeError("target national_dex_no must be positive")
        form = _string(member["form_code"], "form_code")
        variant = _string(member["variant_code"], "variant_code")
        label = _string(member["label"], "label")
        if member["pokemon_id"] is not None and type(member["pokemon_id"]) is not str:
            raise AuthoritativeIntakeError("target pokemon_id must be a string or null")
        if not label.startswith(f"No.{dex:04d} "):
            raise AuthoritativeIntakeError("target label dex does not match")
        value = {
            "national_dex_no": dex,
            "form_code": form,
            "variant_code": variant,
            "label": label,
            "pokemon_id": member["pokemon_id"],
        }
        key = _target_key(value)
        if key in seen:
            raise AuthoritativeIntakeError(f"duplicate target key: {key}")
        seen.add(key)
        result.append(value)
    if [_target_key(value) for value in result] != sorted(seen):
        raise AuthoritativeIntakeError("target members must be sorted by exact target key")
    return result


def _validate_target_source_manifests(
    *,
    repo: Path,
    plan: Mapping[str, Any],
    target_pool: Mapping[str, Any],
    target_pool_bytes: bytes,
) -> tuple[tuple[str, ...], str, bool]:
    target_ids = tuple(target_pool["source_manifest_ids"])
    bindings = tuple(plan["target_source_manifests"])
    binding_ids = tuple(value["manifest_id"] for value in bindings)
    if binding_ids != target_ids:
        raise AuthoritativeIntakeError(
            "target pool source_manifest_ids must exactly match the reviewed plan bindings"
        )

    identities: list[dict[str, Any]] = []
    denominator_final = True
    expected_target_hash = hashlib.sha256(target_pool_bytes).hexdigest()
    for binding in bindings:
        manifest_id = binding["manifest_id"]
        path = _resolve_path(
            repo,
            binding["relative_path"],
            f"target source manifest {manifest_id}",
        )
        payload = _read_confined_bytes(
            repo,
            path,
            f"target source manifest {manifest_id}",
        )
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != binding["sha256"]:
            raise AuthoritativeIntakeError(
                f"target source manifest hash mismatch: {manifest_id}"
            )
        raw = _parse_json_object(payload, f"target source manifest {manifest_id}")
        if raw.get("manifest_id") != manifest_id:
            raise AuthoritativeIntakeError(
                f"target source manifest identity mismatch: {manifest_id}"
            )
        trust = raw.get("trust")
        if type(trust) is not dict or trust.get("authority") != binding["required_authority"]:
            raise AuthoritativeIntakeError(
                f"target source manifest authority mismatch: {manifest_id}"
            )
        if (
            binding["required_authority"] == "official"
            and trust.get("verification_status")
            not in {"partially_verified", "fully_verified"}
        ):
            raise AuthoritativeIntakeError(
                f"official target source manifest is not reviewed: {manifest_id}"
            )
        denominator_final = denominator_final and (
            binding["required_authority"] == "official"
        )
        scope = raw.get("scope")
        regulation_ids = scope.get("regulation_ids") if type(scope) is dict else None
        if (
            type(regulation_ids) is not list
            or regulation_ids != sorted(regulation_ids)
            or len(regulation_ids) != len(set(regulation_ids))
            or plan["regulation_id"] not in regulation_ids
        ):
            raise AuthoritativeIntakeError(
                f"target source manifest regulation scope mismatch: {manifest_id}"
            )
        artifacts = raw.get("artifacts")
        if type(artifacts) is not list:
            raise AuthoritativeIntakeError(
                f"target source manifest artifacts missing: {manifest_id}"
            )
        matches = [
            value
            for value in artifacts
            if type(value) is dict
            and value.get("logical_path") == plan["target_pool_path"]
        ]
        if len(matches) != 1:
            raise AuthoritativeIntakeError(
                f"target source manifest must bind the exact target path once: {manifest_id}"
            )
        artifact = matches[0]
        if (
            artifact.get("sha256") != f"sha256:{expected_target_hash}"
            or artifact.get("byte_size") != len(target_pool_bytes)
            or artifact.get("record_count") != plan["expected_target_count"]
            or artifact.get("media_type") != "application/json"
        ):
            raise AuthoritativeIntakeError(
                f"target source manifest artifact identity mismatch: {manifest_id}"
            )
        identities.append(
            {
                "manifest_id": manifest_id,
                "relative_path": binding["relative_path"],
                "sha256": actual_hash,
                "required_authority": binding["required_authority"],
                "target_pool_sha256": expected_target_hash,
                "target_record_count": plan["expected_target_count"],
                "regulation_id": plan["regulation_id"],
                "regulation_revision": target_pool["regulation_revision"],
            }
        )
    return target_ids, canonical_sha256(identities), denominator_final


def _target_key(value: Mapping[str, Any]) -> str:
    return (
        f"dex:{value['national_dex_no']:04d}:form:{value['form_code']}:"
        f"variant:{value['variant_code']}"
    )


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser()
    if path.is_symlink():
        raise AuthoritativeIntakeError(f"{label} must not be a symlink")
    if not path.is_file():
        raise AuthoritativeIntakeError(f"{label} does not exist: {path}")
    path = path.resolve()
    return _parse_json_object(_read_stable_bytes(path, label), label)


def _parse_json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuthoritativeIntakeError(f"{label} must be UTF-8 JSON") from error

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthoritativeIntakeError(f"{label} contains duplicate key {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise AuthoritativeIntakeError(f"{label} contains non-finite number {value}")

    try:
        raw = json.loads(
            text,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except AuthoritativeIntakeError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise AuthoritativeIntakeError(f"{label} is invalid JSON") from error
    if type(raw) is not dict:
        raise AuthoritativeIntakeError(f"{label} must be a JSON object")
    canonical_json(raw)
    return raw


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unexpected = sorted(set(value) - expected)
        raise AuthoritativeIntakeError(
            f"{label} key mismatch; missing={missing}; unexpected={unexpected}"
        )


def _keys_with_optional(
    value: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - required - optional)
    if missing or unexpected:
        raise AuthoritativeIntakeError(
            f"{label} key mismatch; missing={missing}; unexpected={unexpected}"
        )


def _string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise AuthoritativeIntakeError(f"{label} must be a non-empty string")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise AuthoritativeIntakeError(f"{label} must be an array")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise AuthoritativeIntakeError(f"{label} must be an object")
    return value


def _sorted_strings(value: Any, label: str, *, allow_empty: bool) -> list[str]:
    values = _array(value, label)
    if not allow_empty and not values:
        raise AuthoritativeIntakeError(f"{label} must not be empty")
    if any(type(item) is not str or not item for item in values):
        raise AuthoritativeIntakeError(f"{label} must contain non-empty strings")
    if values != sorted(values) or len(values) != len(set(values)):
        raise AuthoritativeIntakeError(f"{label} must be sorted and unique")
    return values


def _sorted_string_ids(value: Any, label: str, *, allow_empty: bool) -> list[str]:
    values = _sorted_strings(value, label, allow_empty=allow_empty)
    for item in values:
        require_stable_id(item, label)
    return values


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise AuthoritativeIntakeError("relative paths must use forward slashes")
    path = PurePosixPath(value)
    raw_parts = value.split("/")
    windows_reserved = re.compile(
        r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
        re.IGNORECASE,
    )
    if (
        not value
        or path.is_absolute()
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(":" in part for part in raw_parts)
        or any(any(ord(character) < 32 or ord(character) == 127 for character in part) for part in raw_parts)
        or any(part[0].isspace() or part[-1].isspace() or part.endswith(".") for part in raw_parts)
        or any(windows_reserved.fullmatch(part) for part in raw_parts)
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise AuthoritativeIntakeError(f"unsafe relative path: {value}")
    return path


def _resolve_path(root: Path, relative: str, label: str) -> Path:
    path = _try_resolve_path(root, relative)
    if path is None or not path.exists():
        raise AuthoritativeIntakeError(f"{label} does not exist: {relative}")
    _reject_symlink_path(root, path)
    return path


def _try_resolve_path(root: Path, relative: str) -> Path | None:
    safe = _safe_relative_path(relative)
    root = root.resolve()
    candidate = root.joinpath(*safe.parts)
    current = root
    for part in safe.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise AuthoritativeIntakeError(f"source path contains a symlink: {relative}")
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise AuthoritativeIntakeError(f"cannot resolve source path: {relative}") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AuthoritativeIntakeError(f"source path escapes root: {relative}") from error
    return resolved


def _reject_symlink_path(root: Path, path: Path) -> None:
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise AuthoritativeIntakeError("path is outside its declared root") from error
    current = root
    if current.is_symlink():
        raise AuthoritativeIntakeError("declared root must not be a symlink")
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise AuthoritativeIntakeError(f"source path contains a symlink: {current}")


def _snapshot_file_identity(
    artifact_id: str,
    root_kind: str,
    root: Path,
    path: Path,
    role: str,
) -> tuple[ArtifactIdentity, bytes, tuple[int, int]]:
    payload, file_key = _read_confined_snapshot(
        root, path, f"artifact {artifact_id}"
    )
    identity = ArtifactIdentity(
        artifact_id=artifact_id,
        root_kind=root_kind,
        relative_path=path.relative_to(root).as_posix(),
        role=role,
        byte_count=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    return identity, payload, file_key


def _read_confined_bytes(root: Path, path: Path, label: str) -> bytes:
    root = root.resolve()
    _reject_symlink_path(root, path)
    return _read_stable_bytes(path, label, confinement_root=root)


def _read_confined_snapshot(
    root: Path, path: Path, label: str
) -> tuple[bytes, tuple[int, int]]:
    root = root.resolve()
    _reject_symlink_path(root, path)
    return _read_stable_snapshot(path, label, confinement_root=root)


def _read_stable_bytes(
    path: Path,
    label: str,
    *,
    confinement_root: Path | None = None,
) -> bytes:
    payload, _file_key = _read_stable_snapshot(
        path,
        label,
        confinement_root=confinement_root,
    )
    return payload


def _read_stable_snapshot(
    path: Path,
    label: str,
    *,
    confinement_root: Path | None = None,
) -> tuple[bytes, tuple[int, int]]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AuthoritativeIntakeError(f"cannot open {label}") from error
    try:
        opened_path = _opened_file_path(descriptor, path)
        if confinement_root is not None:
            try:
                opened_path.relative_to(confinement_root.resolve())
            except ValueError as error:
                raise AuthoritativeIntakeError(
                    f"opened {label} escapes its declared root"
                ) from error
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuthoritativeIntakeError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in stable_fields):
            raise AuthoritativeIntakeError(f"{label} changed while it was read")
        payload = b"".join(chunks)
        if len(payload) != after.st_size:
            raise AuthoritativeIntakeError(f"{label} byte count changed while it was read")
        return payload, (int(after.st_dev), int(after.st_ino))
    finally:
        os.close(descriptor)


def _opened_file_path(descriptor: int, requested_path: Path) -> Path:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
        function.argtypes = (
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        function.restype = wintypes.DWORD
        handle = msvcrt.get_osfhandle(descriptor)
        required = function(handle, None, 0, 0)
        if required == 0:
            raise AuthoritativeIntakeError("cannot resolve opened file handle")
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = function(handle, buffer, len(buffer), 0)
        if written == 0 or written >= len(buffer):
            raise AuthoritativeIntakeError("cannot resolve opened file handle")
        raw = buffer.value
        if raw.startswith("\\\\?\\UNC\\"):
            raw = "\\\\" + raw[8:]
        elif raw.startswith("\\\\?\\"):
            raw = raw[4:]
        return Path(raw).resolve()
    descriptor_path = Path(f"/proc/self/fd/{descriptor}")
    if descriptor_path.exists():
        return descriptor_path.resolve(strict=True)
    return requested_path.resolve(strict=True)


def _timestamp_or_date(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuthoritativeIntakeError(f"{label} must be ISO-8601") from error
    if "T" in value and parsed.tzinfo is None:
        raise AuthoritativeIntakeError(f"{label} timestamp must include a timezone")


def _resolve_json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise AuthoritativeIntakeError("invalid JSON pointer")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                raise AuthoritativeIntakeError("JSON pointer key is missing")
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise AuthoritativeIntakeError("JSON pointer index is out of range")
            current = current[index]
        else:
            raise AuthoritativeIntakeError("JSON pointer cannot be resolved")
    return current


def _blocker(
    stage: str,
    code: str,
    subject: str,
    evidence_required: str,
    restart_condition: str,
) -> IntakeBlocker:
    return IntakeBlocker(
        stage=stage,
        code=code,
        subject=subject,
        evidence_required=evidence_required,
        restart_condition=restart_condition,
    )


def _sorted_unique_blockers(values: Iterable[IntakeBlocker]) -> list[IntakeBlocker]:
    unique = {
        (
            value.stage,
            value.code,
            value.subject,
            value.evidence_required,
            value.restart_condition,
        ): value
        for value in values
    }
    return [unique[key] for key in sorted(unique)]


def _stable_subject(*parts: Any) -> str:
    raw = ":".join(str(value) for value in parts)
    normalized = re.sub(r"[^A-Za-z0-9._:-]", "_", raw)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized or len(normalized) > 240:
        normalized = f"subject:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    require_stable_id(normalized, "blocker subject")
    return normalized
