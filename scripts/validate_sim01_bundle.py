"""Validate the local SIM-01 fixture bundle without third-party dependencies.

JSON Schema files define the serialized contract.  This validator checks their
top-level required/allowed fields, then delegates semantic cross-reference
validation to the production snapshot loaders.  It also enforces source
manifest hash and license-use restrictions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.catalog import (  # noqa: E402
    SnapshotValidationError,
    load_catalog,
    load_ruleset,
    validate_snapshot_pair,
)
from champions_sim.engine import BattleEngine  # noqa: E402
from champions_sim.fixtures import load_battle_fixture  # noqa: E402
from champions_sim.runner import run_battle  # noqa: E402


class BundleValidationError(ValueError):
    """Raised when a bundle cannot be used under the requested scope."""


@dataclass(frozen=True, slots=True)
class BundleValidationReport:
    catalog_id: str
    catalog_hash: str
    ruleset_id: str
    ruleset_hash: str
    engine_semantics_version: str
    manifest_id: str
    source_manifest_ids: tuple[str, ...]
    license_status: str
    usage_scope: str
    local_research_allowed: bool
    redistribution_allowed: bool
    fixture_battle_id: str
    replay_schema_version: str
    replay_hash: str
    decision_windows: int


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
            parse_float=_parse_finite_float,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleValidationError(f"{label} is not valid UTF-8 JSON: {path}") from error
    if not isinstance(raw, dict):
        raise BundleValidationError(f"{label} root must be an object: {path}")
    return raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    raise BundleValidationError(f"non-finite JSON number is forbidden: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise BundleValidationError(f"non-finite JSON number is forbidden: {value}")
    return parsed


def load_json_object_strict(path: Path | str, label: str) -> dict[str, Any]:
    """Public strict parser used by promotion/schema gates."""

    return _read_object(Path(path), label)


def validate_top_level_contract(
    document: Mapping[str, Any],
    schema: Mapping[str, Any],
    label: str,
) -> None:
    """Check the top-level shape before semantic loading.

    Nested constraints remain in the JSON Schema and are additionally bounded
    by the production loader.  This focused check prevents the P0 failure mode
    where a fixture and schema shared a version while having unrelated roots.
    """

    required = set(schema.get("required", ()))
    properties = set(schema.get("properties", {}))
    missing = sorted(required - set(document))
    if missing:
        raise BundleValidationError(f"{label} missing schema fields: {missing}")
    if schema.get("additionalProperties") is False:
        extra = sorted(set(document) - properties)
        if extra:
            raise BundleValidationError(f"{label} has fields outside schema: {extra}")
    version_contract = schema.get("properties", {}).get("schema_version", {})
    expected_version = version_contract.get("const")
    if expected_version is not None and document.get("schema_version") != expected_version:
        raise BundleValidationError(
            f"{label} schema_version must be {expected_version!r}, "
            f"got {document.get('schema_version')!r}"
        )


def _resolve_ref(root_schema: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise BundleValidationError(f"only local schema references are supported: {ref}")
    current: Any = root_schema
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or token not in current:
            raise BundleValidationError(f"unresolved schema reference: {ref}")
        current = current[token]
    if not isinstance(current, Mapping):
        raise BundleValidationError(f"schema reference is not an object: {ref}")
    return current


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def validate_document_contract(
    document: Any,
    schema: Mapping[str, Any],
    label: str,
    *,
    fail_on_unknown_keywords: bool = False,
) -> None:
    """Validate the JSON Schema subset used by this repository.

    The implementation intentionally covers only locally used structural and
    scalar keywords. Production dataclass/loaders remain the semantic validator.
    """

    if fail_on_unknown_keywords:
        validate_schema_contract(schema)
    _validate_schema_value(
        document,
        schema,
        schema,
        f"{label}.$",
        fail_on_unknown_keywords=fail_on_unknown_keywords,
        active_refs=frozenset(),
    )


_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema", "$id", "$defs", "$ref", "title", "description",
        "default", "examples", "deprecated", "readOnly", "writeOnly",
        "allOf", "oneOf", "if", "then", "else", "const", "enum",
        "type", "minLength", "maxLength", "pattern", "minimum",
        "maximum", "exclusiveMinimum", "minItems", "maxItems",
        "uniqueItems", "contains", "prefixItems", "items", "required",
        "dependentRequired", "minProperties", "propertyNames", "properties",
        "additionalProperties",
    }
)


def validate_schema_contract(schema: Mapping[str, Any]) -> None:
    """Fail closed on unsupported keywords and malformed schema meta-shapes."""

    if not isinstance(schema, Mapping):
        raise BundleValidationError("schema root must be an object")
    seen: set[int] = set()

    def visit(node: Mapping[str, Any], path: str) -> None:
        identity = id(node)
        if identity in seen:
            return
        seen.add(identity)
        unknown = sorted(set(node) - _SUPPORTED_SCHEMA_KEYWORDS)
        if unknown:
            raise BundleValidationError(
                f"{path} uses unsupported schema keywords: {unknown}"
            )

        for key in ("allOf", "oneOf", "prefixItems"):
            if key not in node:
                continue
            values = node[key]
            if not isinstance(values, list) or not values:
                raise BundleValidationError(f"{path}.{key} must be a non-empty array")
            if any(not isinstance(value, Mapping) for value in values):
                raise BundleValidationError(f"{path}.{key} entries must be schemas")
            for index, value in enumerate(values):
                visit(value, f"{path}.{key}[{index}]")
        for key in ("if", "then", "else", "contains", "propertyNames"):
            if key in node:
                value = node[key]
                if not isinstance(value, Mapping):
                    raise BundleValidationError(f"{path}.{key} must be a schema")
                visit(value, f"{path}.{key}")
        if "items" in node:
            value = node["items"]
            if value is not False and not isinstance(value, Mapping):
                raise BundleValidationError(f"{path}.items must be false or a schema")
            if isinstance(value, Mapping):
                visit(value, f"{path}.items")
        if "additionalProperties" in node:
            value = node["additionalProperties"]
            if type(value) is not bool and not isinstance(value, Mapping):
                raise BundleValidationError(
                    f"{path}.additionalProperties must be boolean or a schema"
                )
            if isinstance(value, Mapping):
                visit(value, f"{path}.additionalProperties")
        for key in ("properties", "$defs"):
            if key not in node:
                continue
            values = node[key]
            if not isinstance(values, Mapping):
                raise BundleValidationError(f"{path}.{key} must be an object")
            if any(not isinstance(value, Mapping) for value in values.values()):
                raise BundleValidationError(f"{path}.{key} values must be schemas")
            for name, value in values.items():
                visit(value, f"{path}.{key}.{name}")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str):
                raise BundleValidationError(f"{path}.$ref must be a string")
            visit(_resolve_ref(schema, ref), f"{path}.$ref({ref})")
        if "required" in node:
            required = node["required"]
            if (
                not isinstance(required, list)
                or any(type(value) is not str for value in required)
                or len(required) != len(set(required))
            ):
                raise BundleValidationError(f"{path}.required must be unique strings")
        if "dependentRequired" in node:
            dependent = node["dependentRequired"]
            if not isinstance(dependent, Mapping):
                raise BundleValidationError(f"{path}.dependentRequired must be an object")
            for name, values in dependent.items():
                if (
                    type(name) is not str
                    or not isinstance(values, list)
                    or any(type(value) is not str for value in values)
                ):
                    raise BundleValidationError(
                        f"{path}.dependentRequired entries must be string arrays"
                    )
        if "type" in node:
            value = node["type"]
            valid_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, list) and value and all(type(item) is str for item in value):
                values = value
            else:
                raise BundleValidationError(f"{path}.type has an invalid meta-shape")
            if not set(values) <= valid_types or len(values) != len(set(values)):
                raise BundleValidationError(f"{path}.type contains invalid values")

    visit(schema, "schema.$")


def _validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str,
    *,
    fail_on_unknown_keywords: bool = False,
    active_refs: frozenset[tuple[str, int]] = frozenset(),
) -> None:
    if "$ref" in schema:
        ref = str(schema["$ref"])
        ref_key = (ref, id(value))
        if ref_key in active_refs:
            raise BundleValidationError(f"{path} contains a non-progressing cyclic $ref: {ref}")
        _validate_schema_value(
            value,
            _resolve_ref(root_schema, ref),
            root_schema,
            path,
            fail_on_unknown_keywords=fail_on_unknown_keywords,
            active_refs=active_refs | {ref_key},
        )

    for subschema in schema.get("allOf", ()):
        _validate_schema_value(
            value,
            subschema,
            root_schema,
            path,
            fail_on_unknown_keywords=fail_on_unknown_keywords,
            active_refs=active_refs,
        )
    condition = schema.get("if")
    if isinstance(condition, Mapping):
        try:
            _validate_schema_value(
                value,
                condition,
                root_schema,
                path,
                fail_on_unknown_keywords=fail_on_unknown_keywords,
                active_refs=active_refs,
            )
        except BundleValidationError:
            else_schema = schema.get("else")
            if isinstance(else_schema, Mapping):
                _validate_schema_value(
                    value,
                    else_schema,
                    root_schema,
                    path,
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )
        else:
            then_schema = schema.get("then")
            if isinstance(then_schema, Mapping):
                _validate_schema_value(
                    value,
                    then_schema,
                    root_schema,
                    path,
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )

    alternatives = schema.get("oneOf")
    if isinstance(alternatives, list):
        matched = 0
        for alternative in alternatives:
            try:
                _validate_schema_value(
                    value,
                    alternative,
                    root_schema,
                    path,
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )
            except BundleValidationError:
                continue
            matched += 1
        if matched != 1:
            raise BundleValidationError(f"{path} must match exactly one schema, matched {matched}")

    if "const" in schema and not _json_schema_equal(value, schema["const"]):
        raise BundleValidationError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and not any(
        _json_schema_equal(value, candidate) for candidate in schema["enum"]
    ):
        raise BundleValidationError(f"{path} is not in the allowed enum")

    expected_types = schema.get("type")
    if isinstance(expected_types, str):
        expected_types = [expected_types]
    if isinstance(expected_types, list) and not any(
        _matches_type(value, expected) for expected in expected_types
    ):
        raise BundleValidationError(f"{path} has an invalid JSON type")

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise BundleValidationError(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise BundleValidationError(f"{path} is longer than maxLength")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            raise BundleValidationError(f"{path} does not match {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise BundleValidationError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise BundleValidationError(f"{path} is above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise BundleValidationError(f"{path} is not above exclusiveMinimum")

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise BundleValidationError(f"{path} has too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise BundleValidationError(f"{path} has too many items")
        if schema.get("uniqueItems"):
            for index, item in enumerate(value):
                if any(_json_schema_equal(item, prior) for prior in value[:index]):
                    raise BundleValidationError(f"{path} items must be unique")
        contains_schema = schema.get("contains")
        if isinstance(contains_schema, Mapping):
            contains_match = False
            for index, item in enumerate(value):
                try:
                    _validate_schema_value(
                        item,
                        contains_schema,
                        root_schema,
                        f"{path}[{index}]",
                        fail_on_unknown_keywords=fail_on_unknown_keywords,
                        active_refs=active_refs,
                    )
                except BundleValidationError:
                    continue
                contains_match = True
                break
            if not contains_match:
                raise BundleValidationError(
                    f"{path} must contain at least one item matching the contains schema"
                )
        prefix_items = schema.get("prefixItems", ())
        for index, item_schema in enumerate(prefix_items):
            if index < len(value):
                _validate_schema_value(
                    value[index], item_schema, root_schema, f"{path}[{index}]",
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )
        item_schema = schema.get("items")
        start = len(prefix_items)
        if item_schema is False and len(value) > start:
            raise BundleValidationError(f"{path} contains undeclared tuple items")
        if isinstance(item_schema, Mapping):
            for index in range(start, len(value)):
                _validate_schema_value(
                    value[index], item_schema, root_schema, f"{path}[{index}]",
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )

    if isinstance(value, Mapping):
        required = set(schema.get("required", ()))
        missing = sorted(required - set(value))
        if missing:
            raise BundleValidationError(f"{path} missing required fields: {missing}")
        dependent_required = schema.get("dependentRequired", {})
        if isinstance(dependent_required, Mapping):
            for trigger, dependencies in dependent_required.items():
                if trigger not in value:
                    continue
                missing_dependencies = sorted(set(dependencies) - set(value))
                if missing_dependencies:
                    raise BundleValidationError(
                        f"{path} field {trigger!r} requires fields: "
                        f"{missing_dependencies}"
                    )
        if len(value) < int(schema.get("minProperties", 0)):
            raise BundleValidationError(f"{path} has too few properties")
        property_name_schema = schema.get("propertyNames")
        if isinstance(property_name_schema, Mapping):
            for key in value:
                _validate_schema_value(
                    key, property_name_schema, root_schema, f"{path}.<key>",
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            if key in properties:
                _validate_schema_value(
                    child, properties[key], root_schema, f"{path}.{key}",
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )
            elif additional is False:
                raise BundleValidationError(f"{path}.{key} is not declared by the schema")
            elif isinstance(additional, Mapping):
                _validate_schema_value(
                    child, additional, root_schema, f"{path}.{key}",
                    fail_on_unknown_keywords=fail_on_unknown_keywords,
                    active_refs=active_refs,
                )


def _json_schema_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Enum):
        left = left.value
    if isinstance(right, Enum):
        right = right.value
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is bool and type(right) is bool and left == right
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_schema_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, Mapping):
        return set(left) == set(right) and all(
            _json_schema_equal(left[key], right[key]) for key in left
        )
    return left == right


def _artifact_for_path(
    manifest: Mapping[str, Any],
    artifact_path: Path,
    root: Path,
) -> Mapping[str, Any]:
    try:
        logical_path = artifact_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise BundleValidationError("catalog artifact must be inside the repository") from error
    matches = [
        artifact
        for artifact in manifest.get("artifacts", ())
        if isinstance(artifact, Mapping) and artifact.get("logical_path") == logical_path
    ]
    if len(matches) != 1:
        raise BundleValidationError(
            f"manifest must contain exactly one artifact for {logical_path}, got {len(matches)}"
        )
    return matches[0]


def _verify_artifact(
    manifest: Mapping[str, Any],
    artifact_path: Path,
    root: Path,
) -> None:
    artifact = _artifact_for_path(manifest, artifact_path, root)
    payload = artifact_path.read_bytes()
    expected_size = artifact.get("byte_size")
    expected_hash = artifact.get("sha256")
    actual_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_size != len(payload):
        raise BundleValidationError(
            f"manifest byte_size mismatch: expected {expected_size}, got {len(payload)}"
        )
    if expected_hash != actual_hash:
        raise BundleValidationError(
            f"manifest sha256 mismatch: expected {expected_hash}, got {actual_hash}"
        )


def _verify_declared_local_artifacts(
    manifest: Mapping[str, Any],
    root: Path,
) -> None:
    for artifact in manifest.get("artifacts", ()):
        if not isinstance(artifact, Mapping):
            raise BundleValidationError("manifest artifact entries must be objects")
        logical_path = str(artifact.get("logical_path", ""))
        candidate = root / logical_path
        if candidate.is_file():
            _verify_artifact(manifest, candidate, root)
        elif logical_path.startswith("data/"):
            raise BundleValidationError(f"declared local artifact is missing: {logical_path}")


def _license_permissions(
    manifest: Mapping[str, Any],
    usage_scope: str,
) -> tuple[bool, bool]:
    license_status = str(manifest.get("license_status", ""))
    license_record = manifest.get("license")
    usage_policy = manifest.get("usage_policy")
    if not isinstance(license_record, Mapping) or not isinstance(usage_policy, Mapping):
        raise BundleValidationError("manifest license and usage_policy must be objects")

    local_allowed = bool(usage_policy.get("local_research_only"))
    redistribution_allowed = bool(license_record.get("redistribution_allowed")) and (
        usage_policy.get("redistribution") == "allowed"
    )
    if license_status == "unverified":
        if not local_allowed:
            raise BundleValidationError("unverified source must be marked local-research-only")
        if license_record.get("redistribution_allowed") is not False:
            raise BundleValidationError("unverified source must explicitly prohibit redistribution")
        if license_record.get("commercial_use_allowed") is not False:
            raise BundleValidationError("unverified source must explicitly prohibit commercial use")
        if usage_policy.get("redistribution") != "prohibited":
            raise BundleValidationError("unverified source usage policy must prohibit redistribution")
        redistribution_allowed = False

    if usage_scope == "distribution" and not redistribution_allowed:
        raise BundleValidationError(
            "bundle is not eligible for distribution: source license is unverified or restricted"
        )
    if usage_scope == "local_research" and not local_allowed and not redistribution_allowed:
        raise BundleValidationError("bundle manifest does not permit local research")
    return local_allowed, redistribution_allowed


def validate_bundle(
    *,
    root: Path = ROOT,
    catalog_path: Path | None = None,
    ruleset_path: Path | None = None,
    battle_path: Path | None = None,
    manifest_dir: Path | None = None,
    schema_dir: Path | None = None,
    usage_scope: str = "local_research",
) -> BundleValidationReport:
    if usage_scope not in {"local_research", "distribution"}:
        raise BundleValidationError(f"unsupported usage_scope: {usage_scope}")

    catalog_path = catalog_path or root / "data/fixtures/sim01_catalog.json"
    ruleset_path = ruleset_path or root / "data/fixtures/sim01_ruleset.json"
    battle_path = battle_path or root / "data/fixtures/sim01_battle.json"
    manifest_dir = manifest_dir or root / "data/manifests"
    schema_dir = schema_dir or root / "data/schemas"

    catalog_raw = _read_object(catalog_path, "catalog")
    ruleset_raw = _read_object(ruleset_path, "ruleset")
    battle_raw = _read_object(battle_path, "battle fixture")
    catalog_schema = _read_object(schema_dir / "catalog.schema.json", "catalog schema")
    ruleset_schema = _read_object(schema_dir / "ruleset.schema.json", "ruleset schema")
    battle_schema = _read_object(schema_dir / "battle-fixture.schema.json", "battle schema")
    validate_document_contract(catalog_raw, catalog_schema, "catalog")
    validate_document_contract(ruleset_raw, ruleset_schema, "ruleset")
    validate_document_contract(battle_raw, battle_schema, "battle fixture")

    source_manifest_id = str(catalog_raw["source_manifest_id"])
    source_manifest_ids = tuple(
        sorted(
            {
                source_manifest_id,
                *(str(value) for value in ruleset_raw["source_manifest_ids"]),
            }
        )
    )
    manifest_schema = _read_object(
        schema_dir / "source-manifest.schema.json", "source manifest schema"
    )
    manifests: dict[str, dict[str, Any]] = {}
    local_permissions: list[bool] = []
    redistribution_permissions: list[bool] = []
    for manifest_id in source_manifest_ids:
        manifest_path = manifest_dir / f"{manifest_id}.json"
        manifest = _read_object(manifest_path, f"source manifest {manifest_id}")
        validate_document_contract(manifest, manifest_schema, f"source manifest {manifest_id}")
        if manifest.get("manifest_id") != manifest_id:
            raise BundleValidationError(
                f"source manifest filename/reference does not match manifest_id: {manifest_id}"
            )
        _verify_declared_local_artifacts(manifest, root)
        local_allowed, redistribution_allowed = _license_permissions(manifest, usage_scope)
        manifests[manifest_id] = manifest
        local_permissions.append(local_allowed)
        redistribution_permissions.append(redistribution_allowed)

    _verify_artifact(manifests[source_manifest_id], catalog_path, root)
    local_allowed = all(local_permissions)
    redistribution_allowed = all(redistribution_permissions)

    try:
        catalog = load_catalog(catalog_path)
        ruleset = load_ruleset(ruleset_path)
        validate_snapshot_pair(catalog, ruleset)
        fixture = load_battle_fixture(battle_path, catalog=catalog, ruleset=ruleset)
        engine = BattleEngine(catalog, ruleset)
    except (KeyError, TypeError, ValueError, SnapshotValidationError) as error:
        raise BundleValidationError(f"bundle semantic validation failed: {error}") from error

    provisional_ids = tuple(str(value) for value in ruleset_raw["provisional_decision_ids"])
    if not provisional_ids:
        raise BundleValidationError("provisional RuleSet must name its provisional decision IDs")

    run = run_battle(engine, fixture.initial_state, seed=fixture.rng.seed)
    replay_raw = json.loads(run.replay.to_json())
    replay_schema = _read_object(schema_dir / "replay.schema.json", "replay schema")
    validate_document_contract(replay_raw, replay_schema, "generated replay")
    if set(run.replay.provisional_decision_ids) != set(provisional_ids):
        raise BundleValidationError("Replay did not preserve RuleSet provisional decision IDs")
    if set(run.replay.source_manifest_ids) != set(source_manifest_ids):
        raise BundleValidationError("Replay did not preserve all RuleSet/Catalog source manifest IDs")

    return BundleValidationReport(
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        engine_semantics_version=ruleset.engine_semantics_version,
        manifest_id=source_manifest_id,
        source_manifest_ids=source_manifest_ids,
        license_status=(
            "verified"
            if all(manifest["license_status"] == "verified" for manifest in manifests.values())
            else "unverified"
        ),
        usage_scope=usage_scope,
        local_research_allowed=local_allowed,
        redistribution_allowed=redistribution_allowed,
        fixture_battle_id=fixture.initial_state.battle_id,
        replay_schema_version=run.replay.schema_version,
        replay_hash=run.replay.replay_hash,
        decision_windows=run.decision_windows,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the local SIM-01 bundle")
    parser.add_argument(
        "--usage-scope",
        choices=("local_research", "distribution"),
        default="local_research",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate_bundle(usage_scope=args.usage_scope)
    except BundleValidationError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **asdict(report)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
