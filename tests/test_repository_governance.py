from __future__ import annotations

from scripts.check_repository_governance import (
    ROOT,
    evaluate_repository,
    forbidden_headings,
    forbidden_path_reason,
)


def test_repository_governance_is_clean() -> None:
    assert evaluate_repository(ROOT) == ()


def test_project_state_document_names_are_rejected() -> None:
    assert forbidden_path_reason("docs/validation-report-example.md") is not None
    assert forbidden_path_reason("docs/spec-audit-log.md") is not None
    assert forbidden_path_reason("specs/sim-phase-contract.md") is not None
    assert forbidden_path_reason("docs/specs/battle-engine.md") is None
    assert forbidden_path_reason("docs/adr/0001-example.md") is None


def test_project_state_headings_are_rejected_without_blocking_normative_language() -> None:
    assert forbidden_headings("# Product\n\n## Next steps\n") == ("Next steps",)
    assert forbidden_headings("# Product\n\n## 次の大きな目的\n") == (
        "次の大きな目的",
    )
    assert forbidden_headings("# Readiness\n\n## Readiness decision\n") == ()
