# champions_sim

`champions_sim` is a Pokémon Champions singles AI research environment. Battle transitions, legality, and damage come from an exact external build of the Pokémon Showdown Champions mod; Python provides the policy-facing session, observation, Replay, and validation interfaces.

The game-facing scope is explicitly authorized private friend matches. Ranked-match automation and unattended BlueStacks input automation are not part of this repository. A pinned Showdown build is an engineering dependency, not proof of exact Pokémon Champions fidelity or rank-1 strength.

## Requirements

- Python 3.10 or newer
- Git
- Node.js 22 or newer
- Network access only while explicitly bootstrapping a pinned upstream checkout

The Showdown checkout, `node_modules`, and compiled output are stored outside the repository. Runtime battle execution performs no network access.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python scripts/bootstrap_showdown.py
```

If Node or npm is not on `PATH`, pass `--node` and `--npm`. A pinned `npm@11.6.2` fallback is available through `--pnpm`.

## Use

```powershell
python -m champions_sim verify-showdown
python -m champions_sim battle --input data/fixtures/showdown-battle-script.json --allow-incomplete
python -m champions_sim damage --input data/fixtures/showdown-battle-script.json --attacker p1 --move Thunderbolt
python -m champions_sim replay --input C:\external-artifacts\replay.json
python -m champions_sim audit-random-battles --output C:\external-artifacts\m-b-random-10.json
python scripts/diagnose_bluestacks.py
python scripts/inspect_bluestacks_client_build.py --instance INSTANCE --target-package PACKAGE --confirm-read-only-inspection
python scripts/initialize_capture_store.py --store C:\external-artifacts\captures\development
python scripts/initialize_capture_store.py --partition holdout --store C:\external-holdout\captures
python scripts/validate_grounding_plan.py --plan C:\external-artifacts\grounding-plan.json --lineage C:\external-artifacts\grounding-lineage.json --replay REPLAY_SHA256=C:\external-artifacts\replay.json
python scripts/capture_bluestacks_observation.py --instance INSTANCE --store C:\external-artifacts\captures\development --plan C:\external-artifacts\grounding-plan.json --lineage C:\external-artifacts\grounding-lineage.json --plan-seal-comment COMMENT_URL --authorization C:\external-artifacts\authorization.json
```

BlueStacks diagnosis reads installation metadata, configuration, and process
state only. It never invokes ADB or starts the player. Real observation requires
an initialized external store, an external plan sealed by an unedited live
GitHub Issue comment, a content-addressed external lineage receipt, and a
short-lived authorization document outside the repository. It connects directly
to an existing loopback ADB server and verifies the exact accepted TCP
connection before sending bytes; the capture path cannot start an ADB daemon
and never performs input. It binds the sealed `versionCode`, `versionName`, and
installed base/split APK-set digest before and after observation, so an old,
updated, or replaced client fails closed even when the package name is unchanged.
A screenshot is admitted only when its complete PNG
chunk and image stream validate and target-package UI hierarchies captured
immediately before and after it have the same projected state.

Run the explicit client-build inspection before sealing a grounding plan. It
prints only the package, version metadata, APK count, and canonical APK-set
digest; it does not persist device APK paths or capture match UI.

The Python API keeps one Node process alive for multiple isolated battles:

```python
from champions_sim import ShowdownClient

with ShowdownClient() as client:
    problems = client.validate_team(team)
    session = client.create_session(
        session_id="experiment-1",
        seed="sodium," + "00" * 32,
        p1_name="policy-a",
        p1_team=team,
        p2_name="policy-b",
        p2_team=opponent,
    )
    observation = session.observe("p1")
```

`ShowdownObservation` contains only that player's request and visible log. `damage_sample` clones the battle and proves that the live PRNG state is unchanged. Replay export includes private packed teams and therefore belongs in the external artifact store, not Git. The `replay` command validates its self-hash and engine/bridge identity, re-executes the Showdown input log, and requires the full canonical result to match.

`audit-random-battles` is the completion gate for the pinned M-B singles engine. It generates two unique, Showdown-validated teams of six per battle, chooses an ordered team of three and every later legal move or switch through a reproducible uniform pseudo-random selector, requires ten terminal battles, re-executes every Replay, and repeats the complete run in a fresh bridge process with the same seed. The full Schema-validated report contains private teams and Replays, so `--output` must point outside the repository and refuses to overwrite an existing artifact.

## Validation

```powershell
python scripts/check_repository_governance.py
python scripts/validate_project_skills.py
python scripts/check_repo_size.py
python scripts/bootstrap_showdown.py --verify-only
$env:SHOWDOWN_INTEGRATION = "1"
python -m pytest -q
```

CI bootstraps and verifies the exact upstream commit and runs the integration suite on Python 3.10 and 3.12.

## Repository contents

- `bridge/`: strict persistent Node bridge
- `src/champions_sim/showdown/`: manifest resolver, process transport, sessions, observations, damage samples, and Replay
- `src/champions_sim/grounding/`: scoped observation authorization, read-only BlueStacks diagnostics, existing-server ADB transport, external development/holdout plans, and content-addressed capture evidence
- `data/manifests/`: pinned external dependency identity
- `data/schemas/`: current dependency, script, Replay, completion-audit, and grounding contracts
- `data/fixtures/`: one small deterministic battle script
- `docs/specs/`: current normative behavior
- `docs/adr/`: durable decision history
- `docs/policies/`: current repository and evidence rules

Bulk experiments, Replays, models, external source trees, builds, downloaded data, and captures stay outside Git. The workspace may contain only the ignored active model bundle allowed by the [artifact policy](docs/policies/artifacts-and-data.md).

Project objectives, progress, blockers, and handoffs live in [GitHub Issues](https://github.com/undo-not/pokemon-auto-battle-single/issues), branches, and pull requests—not tracked status documents.

## Documentation

- [Product boundaries](docs/specs/product-boundaries.md)
- [Battle engine](docs/specs/battle-engine.md)
- [Regulation and engine binding](docs/specs/regulation-and-engine.md)
- [Evidence and readiness](docs/specs/evidence-and-readiness.md)
- [AI evaluation](docs/specs/ai-evaluation.md)
- [Project workflow](docs/policies/project-workflow.md)
- [Artifacts and data](docs/policies/artifacts-and-data.md)
- [Evidence and claims](docs/policies/evidence-and-claims.md)
- [Agent collaboration](docs/policies/agent-collaboration.md)
- [Architecture decisions](docs/adr/README.md)
