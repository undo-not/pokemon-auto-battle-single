---
name: validate-simulator-change
description: Select and run risk-based validation for champions_sim changes, including governance, repository size, pinned Showdown identity, bridge contracts, deterministic Replay, grounding, and agent Skills. Use before committing, handing off, or opening a pull request, and when diagnosing a regression.
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

### Showdown dependency, bridge, Replay, fixture, or observation

```powershell
python scripts/bootstrap_showdown.py --verify-only
$env:SHOWDOWN_INTEGRATION = "1"
python -m pytest -q tests/test_showdown_manifest.py tests/test_showdown_integration.py tests/test_showdown_cli.py
```

Verify the pinned origin, commit, Git tree, selected source hashes, license hash, compiled/runtime-file count, build fingerprint, Node minimum, format name/mod/purpose, bridge protocol, and bridge source hash before battle tests. When random-team generation changes, verify its source and runtime JSON, the generation-format binding, ten-battle audit Schema, target-format validation, cross-process determinism, decision-to-Replay correspondence, and external-only no-overwrite report. Test terminal equal-input Replay identity and input-log re-execution, concurrent session isolation, policy-view privacy, team validation, legal choices, invalid choices, process termination, timeout transport disposal, strict JSON, and clone-only damage sampling. A mismatch must fail closed; do not add the removed Python engine as a fallback.

### Regulation or upstream pin

Validate the dependency manifest and battle-script/Replay schemas. Build the candidate external checkout twice when build or pin inputs change and compare fingerprints. Inspect the exact upstream diff affecting the bound format and Champions mods. Keep downloaded source and build output outside the workspace.

Run network acquisition only when the Issue authorizes bootstrapping or updating the upstream pin. A pre-existing verified external checkout is sufficient for ordinary validation. Report an unavailable external check; never fabricate a pass.

### Documentation, policy, ADR, or Skill

Run the governance checker and `python scripts/validate_project_skills.py`. During Skill authoring, also run the environment-provided standard Skill validator when available. Confirm Claude wrappers still point to canonical Skill paths and contain no independent workflow copy.

### BlueStacks or grounding

Keep diagnostics read-only unless the Issue explicitly authorizes capture. Confirm no ADB daemon, player, capture, or input side effect occurs during ordinary tests. Store captures outside Git.

## Interpret results

- Distinguish engineering regression success from Pokémon Champions fidelity, permission, deployment readiness, and competitive strength.
- Treat skipped, unavailable, or unrepresentable evidence as explicit uncertainty or a blocker.
- Put exact commands, concise results, skipped checks, and residual risk in the pull request, not a tracked validation report.
