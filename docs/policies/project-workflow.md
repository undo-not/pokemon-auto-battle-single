# Project workflow policy

## Information ownership

| Information | Authoritative location |
|---|---|
| Objective, scope, acceptance criteria | GitHub Issue |
| Progress, blocker, handoff, test summary | Issue or pull request |
| In-flight implementation | Issue-linked branch |
| Review and merge decision | Pull request |
| Normative system behavior | `docs/specs/` |
| Durable technical decision | `docs/adr/` |
| Operating constraint | `docs/policies/` and `AGENTS.md` |
| Executable evidence | tests, schemas, fixtures, manifests, CI |

Chat, local plans, agent memory, branch names, and generated reports are never authoritative project state.

Write GitHub Issue and pull-request titles, descriptions, progress comments, and
review summaries in Japanese. Keep code identifiers, paths, commands, and quoted
external text in their original language when translation would reduce precision.

## Issue contract

Every implementation Issue must state:

- one outcome that is meaningful when delivered as a whole;
- included scope and explicit non-goals;
- observable acceptance criteria;
- evidence and test expectations;
- external dependencies and safety boundaries;
- whether the work may change external systems or publish data.

Use objective Issues for large outcomes. Add child Issues only when a portion can be delivered, reviewed, or delegated independently; do not split work into bookkeeping-sized tickets.

Open questions remain Issues. Once a question produces a durable architecture decision, add an ADR in the implementing pull request and close or resolve the Issue.

## Branch and pull-request lifecycle

1. Start from updated `main` after reading the complete Issue.
2. Create one branch named `codex/<issue>-<slug>`, `claude/<issue>-<slug>`, or `human/<issue>-<slug>` according to its writer.
3. Keep a single writer for that branch and worktree.
4. Make cohesive commits that reference the Issue.
5. Open a pull request with `Closes #<issue>`, a behavioral summary, validation evidence, residual risk, and external checks that were not run.
6. Obtain an independent review for high-risk simulator, evidence, trust, data-use, or external-integration changes.
7. Merge only after acceptance criteria and required checks pass. Delete the implementation branch after merge.

Branch existence does not indicate progress. Record pauses, blockers, scope changes, and handoffs in the Issue.

## Repository documentation

Repository documentation uses present-tense normative language. It explains what the system is, what it must do, and why durable decisions were made.

Keep tracked documentation files directly inside their respective `docs/specs/`, `docs/policies/`, and `docs/adr/` directories. Do not create nested report, archive, phase, or milestone trees.

Do not add:

- status, progress, roadmap, milestone, or completion reports;
- “next step”, backlog, or remaining-work sections;
- dated test-run transcripts or hand-maintained test counts;
- phase contracts or gate snapshots tied to a completed work package;
- audit logs or handwritten traceability ledgers;
- temporary plans or agent handoff notes.

Store those records in Issues, pull requests, commits, and CI. Keep a small golden or baseline only when executable regression validation consumes it.

When behavior changes, update the affected specification and tests in the same pull request. When only project state changes, update the Issue and do not modify the repository.

## ADR rules

An ADR records context, the chosen decision, alternatives considered when material, and consequences. Use status `Accepted`, `Superseded by ADR-NNNN`, or `Rejected`. Never rewrite an accepted ADR to make history look current; add a superseding ADR instead.

ADR status describes the decision record, not project progress. Experimental results and task completion do not belong in ADRs unless they are necessary evidence for the decision itself.

## Validation evidence

Pull-request evidence must list exact commands and outcomes. CI logs are the durable run record. Do not copy those logs into tracked Markdown.

Required repository-level checks are:

```powershell
python scripts/check_repository_governance.py
python scripts/validate_project_skills.py
python scripts/check_repo_size.py
python -m pytest -q
```

Run additional checks selected by `.agents/skills/validate-simulator-change/SKILL.md`.
