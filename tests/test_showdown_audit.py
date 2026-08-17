from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from champions_sim.core.canonical import canonical_hash
from champions_sim.showdown.audit import (
    AUDIT_ID,
    AUDIT_SCHEMA_VERSION,
    RandomBattleAuditError,
    _HashChoiceStream,
    _choice_kind,
    run_random_battle_audit,
    verify_repeated_random_battle_audit,
    write_random_battle_audit,
)


ROOT = Path(__file__).resolve().parents[1]


def _minimal_report() -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "status": "passed",
        "battle_count": 10,
        "determinism": {"repetitions": 2, "process_isolated": True},
    }
    report["report_hash"] = canonical_hash(report)
    return report


def test_runtime_import_does_not_require_dev_schema_packages() -> None:
    script = """
import importlib.abc
import sys

class BlockDevPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0] in {'jsonschema', 'referencing'}:
            raise ImportError(f'blocked dev dependency: {fullname}')
        return None

sys.meta_path.insert(0, BlockDevPackages())
import champions_sim
assert champions_sim.ShowdownClient
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")

    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
        timeout=30,
    )


def test_hash_choice_stream_is_reproducible_and_domain_separated() -> None:
    values = ("move 1", "move 2", "switch 2")
    left = _HashChoiceStream("audit-seed", "battle-1")
    right = _HashChoiceStream("audit-seed", "battle-1")
    other = _HashChoiceStream("audit-seed", "battle-2")

    expected = [left.choose(values) for _ in range(32)]

    assert [right.choose(values) for _ in range(32)] == expected
    assert [other.choose(values) for _ in range(32)] != expected
    assert set(expected) == set(values)
    with pytest.raises(RandomBattleAuditError, match="duplicate"):
        left.choose(("move 1", "move 1"))


def test_unknown_choice_kind_fails_closed() -> None:
    with pytest.raises(RandomBattleAuditError, match="unexpected"):
        _choice_kind("pass")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"audit_seed": ""}, "audit_seed"),
        ({"audit_seed": "bad\nseed"}, "audit_seed"),
        ({"battle_count": 9}, "exactly 10"),
        ({"battle_count": 11}, "exactly 10"),
        ({"max_decisions": 0}, "max_decisions"),
        ({"max_decisions": 4_001}, "max_decisions"),
    ],
)
def test_audit_rejects_invalid_bounds_before_starting_engine(
    arguments: dict[str, object], message: str
) -> None:
    with pytest.raises(RandomBattleAuditError, match=message):
        run_random_battle_audit(object(), **arguments)  # type: ignore[arg-type]


def test_audit_report_writer_is_external_atomic_and_immutable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import champions_sim.showdown.audit as audit_module

    monkeypatch.setattr(
        audit_module, "validate_random_battle_audit_document", lambda _report: None
    )
    target = tmp_path / "audit.json"
    report = _minimal_report()

    write_random_battle_audit(target, report)

    assert json.loads(target.read_text(encoding="utf-8")) == report
    with pytest.raises(RandomBattleAuditError, match="already exists"):
        write_random_battle_audit(target, report)


def test_audit_report_writer_rejects_workspace_and_bad_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import champions_sim.showdown.audit as audit_module

    monkeypatch.setattr(
        audit_module, "validate_random_battle_audit_document", lambda _report: None
    )
    report = _minimal_report()
    with pytest.raises(RandomBattleAuditError, match="outside the repository"):
        write_random_battle_audit(ROOT / "runs" / "audit.json", report)

    report["status"] = "failed"
    with pytest.raises(RandomBattleAuditError, match="identity or self-hash"):
        write_random_battle_audit(tmp_path / "invalid.json", report)


def test_audit_report_writer_rejects_schema_invalid_document(tmp_path: Path) -> None:
    with pytest.raises(RandomBattleAuditError, match="contract"):
        write_random_battle_audit(tmp_path / "invalid-schema.json", _minimal_report())


def test_repeated_audit_detects_cross_process_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import champions_sim.showdown.audit as audit_module

    reports = iter(
        [
            {"report_hash": "1" * 64, "value": "first"},
            {"report_hash": "2" * 64, "value": "second"},
        ]
    )

    class IsolatedClient:
        def __init__(self, **_arguments: object) -> None:
            pass

        def __enter__(self) -> "IsolatedClient":
            return self

        def __exit__(self, *_arguments: object) -> None:
            return None

    client = SimpleNamespace(
        resolved=SimpleNamespace(
            root=tmp_path,
            node_executable=tmp_path / "node",
            manifest=SimpleNamespace(path=tmp_path / "manifest.json"),
        )
    )
    monkeypatch.setattr(audit_module, "ShowdownClient", IsolatedClient)
    monkeypatch.setattr(
        audit_module,
        "run_random_battle_audit",
        lambda *_arguments, **_keywords: next(reports),
    )

    with pytest.raises(RandomBattleAuditError, match="different reports"):
        verify_repeated_random_battle_audit(client)  # type: ignore[arg-type]


@pytest.mark.parametrize("repetitions", [1, 5])
def test_repeated_audit_rejects_invalid_repetition_count(repetitions: int) -> None:
    with pytest.raises(RandomBattleAuditError, match="repetitions"):
        verify_repeated_random_battle_audit(object(), repetitions=repetitions)  # type: ignore[arg-type]
