# champions_sim

`champions_sim` is a deterministic Pokémon Champions singles battle simulator and AI research platform. It separates battle rules, regulation data, evidence, evaluation, and UI integration so that unsupported mechanics fail closed instead of being approximated.

The intended game-facing environment is private friend matches. Ranked-match automation and unattended input automation are not part of this repository. Competitive strength, Pokémon Champions fidelity, and data-use permission are separate claims and require their own evidence.

## Requirements

- Python 3.10 or newer
- Runtime dependencies: Python standard library
- Development dependency: `pytest`
- Optional local integrations: GitHub CLI, Claude Code, BlueStacks diagnostics

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Common commands

```powershell
python -m champions_sim battle --seed 20260713
python -m champions_sim verify-replay --replay replays/example.json
python -m champions_sim smoke --battles 10000 --seed-start 0
python scripts/validate_sim01_bundle.py --usage-scope local_research
python scripts/validate_sim01_frozen.py
python scripts/check_repo_size.py
python scripts/check_repository_governance.py
python -m pytest -q
```

Commands that build source, regulation, benchmark, or grounding artifacts write to Gitignored content-addressed directories unless explicitly documented otherwise. They do not grant permission to redistribute source data and do not authorize a production candidate.

## Repository structure

- `src/champions_sim/`: simulator, Replay, regulation, evidence, readiness, and evaluation code
- `data/schemas/`: versioned machine-readable contracts
- `data/fixtures/`: minimal deterministic fixtures
- `data/manifests/`: source identities, hashes, and use-policy metadata
- `data/golden/` and `data/baselines/`: small executable regression references
- `scripts/`: deterministic build and validation entry points
- `tests/`: unit, contract, mutation, and integration tests
- `docs/specs/`: normative behavior and system boundaries
- `docs/adr/`: durable architecture decisions and their consequences
- `docs/policies/`: repository, evidence, data, and agent operating rules

## Documentation

- [Product boundaries](docs/specs/product-boundaries.md)
- [Battle engine](docs/specs/battle-engine.md)
- [Regulation and Catalog](docs/specs/regulation-and-catalog.md)
- [Evidence and readiness](docs/specs/evidence-and-readiness.md)
- [AI evaluation](docs/specs/ai-evaluation.md)
- [Project workflow](docs/policies/project-workflow.md)
- [Artifacts and data](docs/policies/artifacts-and-data.md)
- [Evidence and claims](docs/policies/evidence-and-claims.md)
- [Agent collaboration](docs/policies/agent-collaboration.md)
- [Architecture decisions](docs/adr/README.md)

Objectives, progress, blockers, and future work live in [GitHub Issues](https://github.com/undo-not/pokemon-auto-battle-single/issues). Branches and pull requests are disposable implementation and review surfaces; they are not specification or project-state stores.

## Data boundary

Raw acquisition data, generated Catalogs, Replays, runs, model files, embeddings, emulator captures, and trust state remain outside Git. Git tracks only code, schemas, minimal fixtures, manifests, and small deterministic references. See [Artifacts and data](docs/policies/artifacts-and-data.md).
