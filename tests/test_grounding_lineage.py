from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.core import canonical_json
from champions_sim.grounding import (
    GroundingLineageError,
    GroundingLineageReceipt,
    load_grounding_lineage_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
ISSUE_URL = "https://github.com/undo-not/pokemon-auto-battle-single/issues/3"


def _receipt() -> GroundingLineageReceipt:
    return GroundingLineageReceipt(
        schema_version="1.0.0",
        lineage_id="development-lineage",
        issue_url=ISSUE_URL,
        regulation_id="champions-m-b",
        format_id="gen9championsbssregmb",
        partition="development",
        capture_store_id="development-captures",
        capture_store_identity_sha256="sha256:" + "1" * 64,
        source_artifact_sha256=("sha256:" + "2" * 64,),
        source_store_identity_sha256="sha256:" + "3" * 64,
        collected_at="2026-08-21T07:50:00Z",
        collection_method="private-friend-match-manual-observation",
        collector_id="collector-development",
        author_id="author-development",
        executor_id="executor-development",
        independence_attested=True,
        local_research_only=True,
        distribution_allowed=False,
    )


def test_external_lineage_receipt_is_canonical_content_addressed_and_schema_valid(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    path = tmp_path / "lineage.json"
    path.write_text(canonical_json(receipt), encoding="utf-8")

    resolved = load_grounding_lineage_receipt(path)

    assert resolved.receipt == receipt
    assert resolved.receipt_sha256.startswith("sha256:")
    schema = json.loads(
        (ROOT / "data/schemas/grounding-lineage-receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(receipt.to_dict())


def test_lineage_receipt_rejects_noncanonical_or_repository_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lineage.json"
    path.write_text(json.dumps(_receipt().to_dict(), indent=2), encoding="utf-8")
    with pytest.raises(GroundingLineageError, match="canonical JSON"):
        load_grounding_lineage_receipt(path)

    with pytest.raises(GroundingLineageError, match="outside the repository"):
        load_grounding_lineage_receipt(
            ROOT / "data/schemas/grounding-lineage-receipt.schema.json"
        )


def test_lineage_receipt_requires_sorted_unique_source_identities() -> None:
    value = _receipt().to_dict()
    value["source_artifact_sha256"] = [
        "sha256:" + "2" * 64,
        "sha256:" + "2" * 64,
    ]
    with pytest.raises(GroundingLineageError, match="sorted unique"):
        GroundingLineageReceipt(**value)
