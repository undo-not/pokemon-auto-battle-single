"""Strict local loaders and provenance checks for regulation intake."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .models import (
    REGULATION_SCHEMA_VERSION,
    TARGET_POOL_SCHEMA_VERSION,
    BattleTimer,
    ItemClause,
    RegulationPeriod,
    RegulationSnapshot,
    TargetPoolMember,
    TargetPoolSnapshot,
)


_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_REGULATION_KEYS = frozenset(
    {
        "schema_version",
        "regulation_id",
        "revision",
        "title",
        "status",
        "verification_status",
        "published_at",
        "period",
        "battle_format",
        "team_size",
        "level",
        "item_clause",
        "battle_timer",
        "required_mechanics",
        "source_manifest_ids",
    }
)
_TARGET_POOL_KEYS = frozenset(
    {
        "schema_version",
        "regulation_id",
        "regulation_revision",
        "expected_member_count",
        "members",
        "source_manifest_ids",
    }
)


class RegulationDataError(ValueError):
    """Raised when SIM-02 data is incomplete, inconsistent, or untraceable."""


@dataclass(frozen=True, slots=True)
class SourceManifestEvidence:
    manifest_id: str
    license_status: str
    local_research_only: bool
    redistribution: str
    verification_status: str
    declared_artifact_paths: tuple[str, ...]

    @property
    def restricted(self) -> bool:
        return self.license_status != "verified" or self.redistribution != "allowed"


@dataclass(frozen=True, slots=True)
class RegulationDataBundle:
    regulation: RegulationSnapshot
    target_pool: TargetPoolSnapshot
    manifests: tuple[SourceManifestEvidence, ...]

    @property
    def restricted_source_manifest_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.manifest_id for item in self.manifests if item.restricted))


def load_source_manifest_evidence(
    manifest_id: str,
    *,
    manifest_dir: Path | str,
    repository_root: Path | str,
) -> SourceManifestEvidence:
    """Validate one manifest and every repository-local artifact it declares."""

    stable_id = _stable_id(manifest_id, "manifest_id")
    return _load_manifest(
        Path(manifest_dir) / f"{stable_id}.json",
        Path(repository_root).resolve(),
    )


def load_regulation_snapshot(path: Path | str) -> RegulationSnapshot:
    source = Path(path)
    raw, snapshot_hash = _read_object(source, "regulation snapshot")
    _exact_keys(raw, _REGULATION_KEYS, "regulation snapshot")
    if raw["schema_version"] != REGULATION_SCHEMA_VERSION:
        raise RegulationDataError("unsupported regulation schema_version")
    regulation_id = _stable_id(raw["regulation_id"], "regulation_id")
    revision = _stable_id(raw["revision"], "revision")
    status = _enum(raw["status"], {"current", "archived", "synthetic"}, "status")
    verification = _enum(
        raw["verification_status"],
        {"verified", "partially_verified", "synthetic_rehearsal"},
        "verification_status",
    )
    if status == "synthetic" and verification != "synthetic_rehearsal":
        raise RegulationDataError("synthetic regulation must use synthetic_rehearsal verification")
    if status != "synthetic" and verification == "synthetic_rehearsal":
        raise RegulationDataError("non-synthetic regulation cannot use synthetic verification")
    published_at = raw["published_at"]
    if published_at is not None:
        _datetime(str(published_at), "published_at")
    period_raw = _mapping(raw["period"], "period")
    _exact_keys(period_raw, {"start_date", "end_at", "timezone"}, "period")
    start_date = str(period_raw["start_date"])
    end_at = str(period_raw["end_at"])
    _date(start_date, "period.start_date")
    _datetime(end_at, "period.end_at")
    if str(period_raw["timezone"]) != "Asia/Tokyo":
        raise RegulationDataError("SIM-02 fixture timezone must be Asia/Tokyo")
    if datetime.fromisoformat(end_at).date() < date.fromisoformat(start_date):
        raise RegulationDataError("regulation period ends before it starts")
    item_raw = _mapping(raw["item_clause"], "item_clause")
    _exact_keys(
        item_raw,
        {"held_items_enabled", "duplicate_held_items_allowed"},
        "item_clause",
    )
    timer_raw = _mapping(raw["battle_timer"], "battle_timer")
    _exact_keys(
        timer_raw,
        {"total_minutes", "player_minutes", "turn_seconds", "selection_seconds"},
        "battle_timer",
    )
    timer_values = {
        key: _positive_int(timer_raw[key], f"battle_timer.{key}")
        for key in timer_raw
    }
    if timer_values["player_minutes"] > timer_values["total_minutes"]:
        raise RegulationDataError("player timer cannot exceed total timer")
    team_size = _positive_int(raw["team_size"], "team_size")
    level = _positive_int(raw["level"], "level")
    if raw["battle_format"] != "singles_3v3" or team_size != 3:
        raise RegulationDataError("SIM-02 vertical slice requires singles_3v3")
    if not 1 <= level <= 100:
        raise RegulationDataError("level must be between 1 and 100")
    mechanics = _stable_id_array(raw["required_mechanics"], "required_mechanics", allow_empty=True)
    manifests = _stable_id_array(raw["source_manifest_ids"], "source_manifest_ids")
    return RegulationSnapshot(
        schema_version=REGULATION_SCHEMA_VERSION,
        regulation_id=regulation_id,
        revision=revision,
        title=_nonempty_string(raw["title"], "title"),
        status=status,
        verification_status=verification,
        published_at=str(published_at) if published_at is not None else None,
        period=RegulationPeriod(start_date, end_at, "Asia/Tokyo"),
        battle_format="singles_3v3",
        team_size=team_size,
        level=level,
        item_clause=ItemClause(
            _bool(item_raw["held_items_enabled"], "item_clause.held_items_enabled"),
            _bool(
                item_raw["duplicate_held_items_allowed"],
                "item_clause.duplicate_held_items_allowed",
            ),
        ),
        battle_timer=BattleTimer(**timer_values),
        required_mechanics=mechanics,
        source_manifest_ids=manifests,
        snapshot_hash=snapshot_hash,
    )


def load_target_pool(path: Path | str) -> TargetPoolSnapshot:
    source = Path(path)
    raw, snapshot_hash = _read_object(source, "target pool")
    _exact_keys(raw, _TARGET_POOL_KEYS, "target pool")
    if raw["schema_version"] != TARGET_POOL_SCHEMA_VERSION:
        raise RegulationDataError("unsupported target-pool schema_version")
    expected_member_count = _positive_int(
        raw["expected_member_count"], "expected_member_count"
    )
    items = raw["members"]
    if not isinstance(items, list) or not items:
        raise RegulationDataError("target pool members must be a non-empty array")
    members: list[TargetPoolMember] = []
    for index, value in enumerate(items):
        item = _mapping(value, f"members[{index}]")
        _exact_keys(
            item,
            {"national_dex_no", "form_code", "variant_code", "label", "pokemon_id"},
            f"members[{index}]",
        )
        pokemon_id = item["pokemon_id"]
        if pokemon_id is not None:
            pokemon_id = _stable_id(pokemon_id, f"members[{index}].pokemon_id")
        members.append(
            TargetPoolMember(
                national_dex_no=_positive_int(
                    item["national_dex_no"], f"members[{index}].national_dex_no"
                ),
                form_code=_code(item["form_code"], f"members[{index}].form_code", 2),
                variant_code=_code(
                    item["variant_code"], f"members[{index}].variant_code", 1
                ),
                label=_nonempty_string(item["label"], f"members[{index}].label"),
                pokemon_id=pokemon_id,
            )
        )
    if len(members) != expected_member_count:
        raise RegulationDataError(
            "target pool member count does not match expected_member_count"
        )
    target_keys = [item.target_key for item in members]
    if len(target_keys) != len(set(target_keys)):
        raise RegulationDataError("target pool dex/form/variant keys must be unique")
    explicit_ids = [item.pokemon_id for item in members if item.pokemon_id is not None]
    if len(explicit_ids) != len(set(explicit_ids)):
        raise RegulationDataError("explicit target pool pokemon IDs must be unique")
    return TargetPoolSnapshot(
        schema_version=TARGET_POOL_SCHEMA_VERSION,
        target_pool_id=(
            f"eligible-pokemon:{_stable_id(raw['regulation_id'], 'regulation_id')}:"
            f"{_stable_id(raw['regulation_revision'], 'regulation_revision')}"
        ),
        regulation_id=_stable_id(raw["regulation_id"], "regulation_id"),
        regulation_revision=_stable_id(raw["regulation_revision"], "regulation_revision"),
        expected_member_count=expected_member_count,
        members=tuple(members),
        source_manifest_ids=_stable_id_array(raw["source_manifest_ids"], "source_manifest_ids"),
        snapshot_hash=snapshot_hash,
    )


def load_regulation_bundle(
    regulation_path: Path | str,
    target_pool_path: Path | str,
    *,
    manifest_dir: Path | str,
    repository_root: Path | str,
) -> RegulationDataBundle:
    regulation_file = Path(regulation_path)
    target_pool_file = Path(target_pool_path)
    regulation = load_regulation_snapshot(regulation_file)
    target_pool = load_target_pool(target_pool_file)
    if target_pool.regulation_id != regulation.regulation_id:
        raise RegulationDataError("target pool regulation_id does not match regulation")
    if target_pool.regulation_revision != regulation.revision:
        raise RegulationDataError("target pool regulation_revision does not match regulation")
    ids = tuple(sorted({*regulation.source_manifest_ids, *target_pool.source_manifest_ids}))
    manifest_root = Path(manifest_dir)
    repo_root = Path(repository_root).resolve()
    evidence = tuple(
        load_source_manifest_evidence(
            value,
            manifest_dir=manifest_root,
            repository_root=repo_root,
        )
        for value in ids
    )
    declared = {
        artifact
        for manifest in evidence
        for artifact in manifest.declared_artifact_paths
    }
    for input_path, label in (
        (regulation_file, "regulation snapshot"),
        (target_pool_file, "target pool"),
    ):
        try:
            logical = input_path.resolve().relative_to(repo_root).as_posix()
        except ValueError as error:
            raise RegulationDataError(f"{label} must be inside repository_root") from error
        if logical not in declared:
            raise RegulationDataError(f"{label} is not declared by its source manifests: {logical}")
    return RegulationDataBundle(regulation, target_pool, evidence)


def _load_manifest(path: Path, repository_root: Path) -> SourceManifestEvidence:
    raw, _ = _read_object(path, "source manifest")
    required = {
        "schema_version",
        "manifest_id",
        "license_status",
        "license",
        "usage_policy",
        "artifacts",
        "trust",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise RegulationDataError(f"source manifest missing fields: {missing}")
    manifest_id = _stable_id(raw["manifest_id"], "manifest_id")
    if manifest_id != path.stem:
        raise RegulationDataError(
            f"source manifest_id does not match its filename: {path.name}"
        )
    license_status = _enum(
        raw["license_status"], {"verified", "unverified", "not_applicable"}, "license_status"
    )
    license_record = _mapping(raw["license"], "license")
    usage = _mapping(raw["usage_policy"], "usage_policy")
    trust = _mapping(raw["trust"], "trust")
    local_only = _bool(usage.get("local_research_only"), "usage_policy.local_research_only")
    redistribution = _enum(
        usage.get("redistribution"), {"allowed", "prohibited"}, "usage_policy.redistribution"
    )
    if license_status == "unverified":
        if not local_only or redistribution != "prohibited":
            raise RegulationDataError("unverified manifest must be local-only and non-redistributable")
        if license_record.get("redistribution_allowed") is not False:
            raise RegulationDataError("unverified manifest must prohibit redistribution")
        if license_record.get("commercial_use_allowed") is not False:
            raise RegulationDataError("unverified manifest must prohibit commercial use")
    artifacts = raw["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise RegulationDataError("source manifest must declare at least one artifact")
    paths: list[str] = []
    for index, value in enumerate(artifacts):
        artifact = _mapping(value, f"artifacts[{index}]")
        for key in ("logical_path", "byte_size", "sha256"):
            if key not in artifact:
                raise RegulationDataError(f"artifact is missing {key}")
        logical = _nonempty_string(artifact["logical_path"], "artifact.logical_path")
        file_path = (repository_root / logical).resolve()
        try:
            file_path.relative_to(repository_root)
        except ValueError as error:
            raise RegulationDataError("manifest artifact escapes repository root") from error
        if not file_path.is_file():
            raise RegulationDataError(f"declared regulation artifact is missing: {logical}")
        payload = file_path.read_bytes()
        expected_size = _positive_or_zero_int(artifact["byte_size"], "artifact.byte_size")
        actual_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        if len(payload) != expected_size:
            raise RegulationDataError(f"artifact byte_size mismatch: {logical}")
        if artifact["sha256"] != actual_hash:
            raise RegulationDataError(f"artifact sha256 mismatch: {logical}")
        paths.append(logical)
    return SourceManifestEvidence(
        manifest_id=manifest_id,
        license_status=license_status,
        local_research_only=local_only,
        redistribution=redistribution,
        verification_status=_enum(
            trust.get("verification_status"),
            {"verified", "partially_verified", "unverified", "example_only"},
            "trust.verification_status",
        ),
        declared_artifact_paths=tuple(sorted(paths)),
    )


def _read_object(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        raw = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegulationDataError(f"{label} is not valid UTF-8 JSON: {path}") from error
    if not isinstance(raw, dict):
        raise RegulationDataError(f"{label} root must be an object")
    return raw, hashlib.sha256(payload).hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str] | frozenset[str], label: str) -> None:
    missing = sorted(set(expected) - set(value))
    extra = sorted(set(value) - set(expected))
    if missing or extra:
        raise RegulationDataError(f"{label} field mismatch: missing={missing}, extra={extra}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RegulationDataError(f"{label} must be an object")
    return value


def _stable_id(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    if _STABLE_ID.fullmatch(text) is None:
        raise RegulationDataError(f"{label} must be a stable ID")
    return text


def _stable_id_array(value: Any, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise RegulationDataError(f"{label} must be a {'possibly empty' if allow_empty else 'non-empty'} array")
    result = tuple(_stable_id(item, label) for item in value)
    if len(result) != len(set(result)):
        raise RegulationDataError(f"{label} values must be unique")
    return result


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegulationDataError(f"{label} must be a non-empty string")
    return value


def _code(value: Any, label: str, minimum_length: int) -> str:
    text = _nonempty_string(value, label)
    if len(text) < minimum_length or re.fullmatch(r"[0-9A-Za-z_-]+", text) is None:
        raise RegulationDataError(f"{label} must be a stable form code")
    return text


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RegulationDataError(f"{label} must be a positive integer")
    return value


def _positive_or_zero_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RegulationDataError(f"{label} must be a non-negative integer")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise RegulationDataError(f"{label} must be boolean")
    return value


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RegulationDataError(f"{label} must be one of {sorted(allowed)}")
    return value


def _date(value: str, label: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise RegulationDataError(f"{label} must be an ISO date") from error


def _datetime(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise RegulationDataError(f"{label} must be an ISO datetime") from error
    if parsed.tzinfo is None:
        raise RegulationDataError(f"{label} must include a timezone offset")
