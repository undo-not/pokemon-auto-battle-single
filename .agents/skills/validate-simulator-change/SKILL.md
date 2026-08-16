---
name: validate-simulator-change
description: Select and run risk-based validation for champions_sim changes, including governance, size, schemas, deterministic battle behavior, Replay, regulation pipelines, evidence readiness, trust, and agent Skills. Use before committing, handing off, or opening a pull request, and when diagnosing a regression.
---

# Validate a simulator change

## Classify the diff

Inspect the complete diff and map every changed surface to the checks below. Run all applicable groups; do not choose checks solely by filename when behavior crosses boundaries.

## Always run

```powershell
python scripts/check_repository_governance.py
python scripts/validate_project_skills.py
python scripts/check_repo_size.py
git diff --check
python -m pytest -q
```

## Add risk-specific checks

### Engine, RuleSet, Catalog, Replay, fixture, or observation

```powershell
python scripts/validate_sim01_bundle.py --usage-scope local_research
python scripts/validate_sim01_frozen.py
python -m champions_sim smoke --battles 10000 --seed-start 0
```

Run focused engine, Replay, observation, prebattle, and integration tests while iterating. Treat a frozen-baseline change as a semantic change requiring specification and ADR review, not as an expected snapshot update.

### Schema, compiler, regulation, evidence, or readiness

Run focused loader/compiler mutation tests and validate at least one positive and one fail-closed path. Rebuild deterministic dry-run output twice when a builder changed and compare canonical hashes. Resolve every input artifact from bytes.

Run an actual external-root dry run only when the Issue authorizes the data and the root is available. Report an unrun external check; never fabricate a pass.

### Trust

Run V2 fail-closed and V3 enrollment, signature, revocation, clock, ledger, TOCTOU, and current-context tests. Do not create actual trust state or keys in the workspace.

### Documentation, policy, ADR, or Skill

Run the governance checker and `python scripts/validate_project_skills.py`. During Skill authoring, also run the environment-provided standard Skill validator when available. Confirm Claude wrappers still point to canonical Skill paths and contain no independent workflow copy.

### BlueStacks or grounding

Keep diagnostics read-only unless the Issue explicitly authorizes capture. Confirm no ADB daemon, player, capture, or input side effect occurs during ordinary tests. Store captures outside Git.

## Interpret results

- Distinguish engineering regression success from Pokémon Champions fidelity, permission, deployment readiness, and competitive strength.
- Treat skipped, unavailable, or unrepresentable evidence as explicit uncertainty or a blocker.
- Put exact commands, concise results, skipped checks, and residual risk in the pull request, not a tracked validation report.
