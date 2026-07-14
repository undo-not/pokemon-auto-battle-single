from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset  # noqa: E402
from champions_sim.arena import (  # noqa: E402
    ArenaPlan,
    EvaluationPartition,
    competitive_baseline_binding,
    random_reference_binding,
    run_paired_arena,
)
from champions_sim.core import PlayerId, PokemonInstanceId, canonical_hash, canonical_json  # noqa: E402
from champions_sim.prebattle import (  # noqa: E402
    FirstThreeTeamSelectionPolicy,
    TeamPreviewRoster,
    TeamPreviewSession,
    TypeCoverageTeamSelectionPolicy,
    run_team_preview,
)


EVIDENCE_MANIFEST_SCHEMA_VERSION = "ai01-arena-evidence-manifest-v1"
MAX_SEED = (1 << 64) - 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic AI-01 six-to-three paired benchmark."
    )
    parser.add_argument("--pairs", type=int, default=64)
    parser.add_argument("--engine-seed-start", type=int, default=10_000)
    parser.add_argument("--agent-seed-start", type=int, default=90_000)
    parser.add_argument("--preview-seed", type=int, default=20260714)
    parser.add_argument("--output-root", default="runs/ai01")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="print a lightweight, non-verifiable summary without persisting evidence",
    )
    parser.add_argument(
        "--write-replays",
        action="store_true",
        help="deprecated compatibility flag; Replay evidence is now written by default",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="deprecated compatibility alias for --summary-only",
    )
    args = parser.parse_args()
    if args.pairs <= 0:
        parser.error("--pairs must be positive")
    if min(args.engine_seed_start, args.agent_seed_start, args.preview_seed) < 0:
        parser.error("seeds must be non-negative")
    if max(args.engine_seed_start, args.agent_seed_start, args.preview_seed) > MAX_SEED:
        parser.error("seeds must fit unsigned 64-bit")
    if args.engine_seed_start + args.pairs - 1 > MAX_SEED:
        parser.error("engine seed range must fit unsigned 64-bit")
    if args.agent_seed_start + args.pairs - 1 > MAX_SEED:
        parser.error("agent seed range must fit unsigned 64-bit")

    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    session = _synthetic_six_member_session(fixture.initial_state, catalog, ruleset)
    preview_policies = {
        PlayerId.P1: TypeCoverageTeamSelectionPolicy(catalog),
        PlayerId.P2: FirstThreeTeamSelectionPolicy(),
    }
    preview = run_team_preview(
        session, policies=preview_policies, seed=args.preview_seed
    )
    selected_state = preview.session.materialize()
    engine = BattleEngine(catalog, ruleset)
    candidate = competitive_baseline_binding(catalog)
    opponent = random_reference_binding()
    plan = ArenaPlan(
        plan_id="ai01-competitive-baseline-v1",
        scenario_id="sim01-frozen-six-to-three-synthetic-v1",
        partition=EvaluationPartition.DEVELOPMENT,
        pair_count=args.pairs,
        engine_seed_start=args.engine_seed_start,
        agent_seed_start=args.agent_seed_start,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        initial_state_hash=canonical_hash(selected_state),
        candidate=candidate.identity,
        opponent=opponent.identity,
        prebattle_session_hash=preview.session.session_hash,
        prebattle_proof_hash=preview.proof.proof_hash,
        provisional_decision_ids=("PD-009",),
    )
    run = run_paired_arena(
        engine,
        selected_state,
        plan=plan,
        candidate=candidate,
        opponent=opponent,
        prebattle_run=preview,
        prebattle_policies=preview_policies,
        external_blockers=(
            "sim02_m_b_candidate_no_go",
            "sim02_grounding_corpus_missing",
            "sim02_external_holdout_missing",
            "prebattle_evidence_bundle_not_self_contained",
        ),
    )

    summary_only = args.summary_only or args.dry_run
    output_directory = None
    if not summary_only:
        output_root = _validated_output_root(args.output_root)
        output_directory = _persist_evidence_bundle(
            output_root,
            run,
            prebattle_session_hash=preview.session.session_hash,
            prebattle_proof_hash=preview.proof.proof_hash,
        )

    print(
        canonical_json(
            {
                "schema_version": run.report.schema_version,
                "decision": run.report.decision,
                "champions_readiness_decision": (
                    run.report.champions_readiness_decision
                ),
                "scope": run.report.plan.scope,
                "report_hash": run.report.report_hash,
                "plan_hash": run.report.plan.plan_hash,
                "prebattle_session_hash": preview.session.session_hash,
                "prebattle_proof_hash": preview.proof.proof_hash,
                "arena_evidence_hash": run.evidence_hash,
                "provisional_decision_ids": plan.provisional_decision_ids,
                "pairs": run.report.summary.pairs,
                "matches": run.report.summary.matches,
                "wins": run.report.summary.wins,
                "draws": run.report.summary.draws,
                "losses": run.report.summary.losses,
                "paired_net_utility_ppm": run.report.summary.paired_net_utility_ppm,
                "replay_verification_rate_ppm": (
                    run.report.summary.replay_verification_rate_ppm
                ),
                "rank1_equivalence_status": run.report.rank1_equivalence_status,
                "champions_candidate": run.report.champions_candidate,
                "evidence_persisted": output_directory is not None,
                "evidence_mode": (
                    "battle_replay_bundle"
                    if output_directory is not None
                    else "summary_only"
                ),
                "output_directory": str(output_directory) if output_directory else None,
            }
        )
    )
    return 0


def _synthetic_six_member_session(initial_state, catalog, ruleset) -> TeamPreviewSession:
    rosters = {}
    for player in (PlayerId.P1, PlayerId.P2):
        originals = initial_state.side(player).team
        reserves = tuple(
            replace(
                member,
                instance_id=PokemonInstanceId(f"{member.instance_id}-reserve"),
                item_id=None,
            )
            for member in originals
        )
        rosters[player] = TeamPreviewRoster(
            player=player,
            members=(*originals, *reserves),
        )
    return TeamPreviewSession.create(
        session_id="ai01-synthetic-preview-v1",
        battle_id="ai01-synthetic-six-to-three-v1",
        catalog=catalog,
        ruleset=ruleset,
        p1_roster=rosters[PlayerId.P1],
        p2_roster=rosters[PlayerId.P2],
    )


def _validated_output_root(raw: str) -> Path:
    allowed = (ROOT / "runs").resolve()
    requested = Path(raw)
    resolved = (ROOT / requested).resolve() if not requested.is_absolute() else requested.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError("AI-01 benchmark output must stay under Gitignored runs/")
    return resolved


def _persist_evidence_bundle(
    output_root: Path,
    run,
    *,
    prebattle_session_hash: str,
    prebattle_proof_hash: str,
) -> Path:
    """Persist the private battle-Replay archive, publishing its manifest last."""

    replay_hashes = tuple(replay.replay_hash for replay in run.replays)
    expected_evidence_hash = canonical_hash(
        {
            "report_hash": run.report.report_hash,
            "replay_hashes": replay_hashes,
        }
    )
    if run.evidence_hash != expected_evidence_hash:
        raise ValueError("arena evidence hash does not bind the report and Replays")
    if run.report.plan.prebattle_proof_hash != prebattle_proof_hash:
        raise ValueError("prebattle proof hash does not match the arena plan")
    if run.report.plan.prebattle_session_hash != prebattle_session_hash:
        raise ValueError("prebattle session hash does not match the arena plan")

    output_directory = output_root / run.report.report_hash
    replay_root = output_directory / "replays"
    replay_root.mkdir(parents=True, exist_ok=True)

    report_document = run.report.to_json() + "\n"
    _write_text_atomically(output_directory / "arena-report.json", report_document)

    replay_files = []
    for index, replay in enumerate(run.replays):
        filename = f"{index:06d}-{replay.replay_hash}.json"
        relative_path = f"replays/{filename}"
        document = replay.to_json() + "\n"
        _write_text_atomically(replay_root / filename, document)
        replay_files.append(
            {
                "path": relative_path,
                "replay_hash": replay.replay_hash,
                "file_sha256": _sha256_text(document),
            }
        )

    manifest = {
        "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "report_path": "arena-report.json",
        "report_hash": run.report.report_hash,
        "report_file_sha256": _sha256_text(report_document),
        "replay_hashes": replay_hashes,
        "replay_files": replay_files,
        "arena_evidence_hash": run.evidence_hash,
        "prebattle_evidence_mode": "regeneration_required",
        "prebattle_session_hash": prebattle_session_hash,
        "prebattle_proof_hash": prebattle_proof_hash,
    }
    _write_text_atomically(
        output_directory / "arena-evidence-manifest.json",
        canonical_json(manifest) + "\n",
    )
    return output_directory


def _write_text_atomically(path: Path, document: str) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(document)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _sha256_text(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
