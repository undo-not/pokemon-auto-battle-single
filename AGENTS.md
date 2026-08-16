# Repository agent contract

These instructions apply to the entire repository and are shared by Codex and Claude Code.

## Sources of truth

- Use GitHub Issues for objectives, acceptance criteria, progress, blockers, and future work.
- Use the linked branch and pull request only for implementing and reviewing one Issue.
- Treat `docs/specs/` as normative behavior, `docs/policies/` as current operating rules, and `docs/adr/` as durable decision rationale.
- Do not add status reports, roadmaps, milestone reports, audit logs, handwritten traceability tables, or next-work sections to the repository.
- Convert a durable decision into an ADR. Put an unresolved question or task in an Issue.
- Treat chat history, agent memory, local plans, and generated summaries as non-authoritative.

## Issue delivery

- Read the entire linked Issue before changing files. Confirm outcome, scope, non-goals, acceptance criteria, and evidence requirements.
- Use one cohesive branch per Issue. Use `codex/<issue>-<slug>` for Codex and `claude/<issue>-<slug>` for Claude Code.
- Keep one writer per branch/worktree. Use another agent only through a separate worktree or as a read-only reviewer.
- Update current specs, policies, ADRs, schemas, and tests in the same pull request as the behavior they describe.
- Put work summaries and test results in the pull request or Issue, not a tracked report.
- Reference the Issue in commits and use `Closes #<issue>` in the pull request when all acceptance criteria are met.

## Product and evidence boundaries

- Limit game-facing operation to private friend matches.
- Do not implement ranked-match automation or unattended BlueStacks input automation.
- Keep battle rules deterministic and versioned. Do not ask an LLM to invent rule values or expected mechanics.
- Fail closed for unsupported mechanics, missing evidence, unresolved mappings, unverified permission, or invalid lineage.
- Keep semantic authority, usage permission, artifact identity, mapping status, execution evidence, grounding, and competitive strength as separate claims.
- Do not promote candidate data to verified because of names, IDs, hashes, popularity, model confidence, or source prestige alone.
- Do not publish source code, raw data, captures, credentials, private keys, trust registries, or model artifacts unless the Issue explicitly authorizes that exact external action.

## Implementation

- Support Python 3.10 or newer and keep runtime dependencies in the standard library unless an ADR changes the rule.
- Preserve deterministic output for equal versioned inputs, decisions, and seed.
- Keep schemas strict, reject duplicate JSON keys and non-finite numbers, and preserve content-addressed identity.
- Preserve user changes and avoid destructive Git operations.
- Use `rg` for repository search and `apply_patch` for hand edits.
- Keep generated and large artifacts in ignored directories described by `docs/policies/artifacts-and-data.md`.

## Validation

- Select checks by risk using `.agents/skills/validate-simulator-change/SKILL.md`.
- Always run `python scripts/check_repository_governance.py` and `python scripts/check_repo_size.py` for a pull request.
- Run focused tests while iterating and the full `python -m pytest -q` suite before handoff.
- Run `python scripts/validate_sim01_frozen.py` when simulator, Replay, Catalog, RuleSet, or fixture behavior can change.
- Report commands, results, skipped external checks, and residual risk in the pull request.

## Agent collaboration

- Follow `docs/policies/agent-collaboration.md` when consulting or delegating to another coding agent.
- Never let the authoring agent be the only reviewer for a high-risk change.
- Do not use permission-bypass modes outside an explicitly authorized disposable sandbox.
