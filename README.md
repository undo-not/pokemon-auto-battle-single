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
python -m champions_sim battle --input data/fixtures/showdown-battle-script.json
python -m champions_sim damage --input data/fixtures/showdown-battle-script.json --attacker p1 --move Thunderbolt
python -m champions_sim replay --input C:\external-artifacts\replay.json
python scripts/diagnose_bluestacks.py
```

The Python API keeps one Node process alive for multiple isolated battles:

```python
from champions_sim import ShowdownClient

with ShowdownClient() as client:
    problems = client.validate_team(team)
    session = client.create_session(
        session_id="experiment-1",
        seed=(1, 2, 3, 4),
        p1_name="policy-a",
        p1_team=team,
        p2_name="policy-b",
        p2_team=opponent,
    )
    observation = session.observe("p1")
```

`ShowdownObservation` contains only that player's request and visible log. `damage_sample` clones the battle and proves that the live PRNG state is unchanged. Replay export includes private packed teams and therefore belongs in the external artifact store, not Git. The `replay` command validates its self-hash and engine/bridge identity, re-executes the Showdown input log, and requires the full canonical result to match.

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
- `src/champions_sim/grounding/`: read-only BlueStacks diagnostics and content-addressed capture evidence
- `data/manifests/`: pinned external dependency identity
- `data/schemas/`: current dependency, script, Replay, and grounding contracts
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
