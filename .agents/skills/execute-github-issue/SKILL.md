---
name: execute-github-issue
description: Deliver a cohesive GitHub Issue from intake through an isolated branch, implementation, validation, independent review, and pull request. Use when starting, resuming, handing off, or completing repository work that has an Issue number or URL.
---

# Execute a GitHub Issue

## Establish the contract

1. Read the complete Issue and linked specifications or ADRs.
2. Restate the outcome, scope, non-goals, acceptance criteria, evidence, and authorized external effects.
3. Inspect `main`, the worktree, related pull requests, and dependencies. Do not infer progress from branch existence.
4. Put missing or materially ambiguous scope in the Issue before implementation.

## Isolate the work

1. Update from `main` without discarding user changes.
2. Use one writer and one branch: `codex/<issue>-<slug>`, `claude/<issue>-<slug>`, or `human/<issue>-<slug>`.
3. Use a separate worktree when another writer is active or when delegating.
4. Never edit or commit unrelated user changes.

## Implement the outcome

1. Make the smallest cohesive design that satisfies the entire Issue outcome.
2. Update implementation, schemas, tests, current specifications, policies, and ADRs together when their contracts change.
3. Keep progress, blockers, plans, test transcripts, and handoff notes in the Issue or pull request.
4. Fail closed at evidence, permission, mapping, mechanics, trust, and external-action boundaries.

## Validate and review

1. Follow the `validate-simulator-change` project Skill to select focused and repository-wide checks.
2. Inspect the final diff and run `git diff --check`.
3. Request independent review for high-risk simulator, data, provenance, trust, or integration changes. Give the reviewer the diff and Issue, not the desired findings.
4. Resolve actionable findings or explain their rejection in the pull request.

## Deliver

1. Commit cohesive changes with an Issue reference.
2. Push only the Issue branch.
3. Open a pull request containing `Closes #<issue>`, outcome, scope, spec/ADR changes, exact validation results, external checks not run, independent-review disposition, and residual risk.
4. Update the Issue rather than adding a repository status file.
5. Do not merge or close the Issue until all acceptance criteria and required checks pass.
