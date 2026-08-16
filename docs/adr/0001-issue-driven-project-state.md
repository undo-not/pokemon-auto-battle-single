# ADR-0001: Keep project state in GitHub Issues and pull requests

- Status: Accepted
- Date: 2026-08-17

## Context

Phase contracts, validation reports, audit logs, traceability tables, provisional-decision ledgers, README status sections, and agent conversations each described overlapping project state. Their values drifted whenever a later change updated only some documents. A repository checkout therefore required reconstructing progress from several historical narratives before implementation could begin.

Implementation knowledge and project-management state have different lifecycles. Current behavior must travel with the code, while objectives, blockers, work assignment, and test-run summaries change frequently and already have durable collaboration surfaces in GitHub.

## Decision

Use GitHub Issues as the sole source of truth for objectives, scope, acceptance criteria, progress, blockers, and future work. Use one short-lived Issue branch and pull request as the implementation and review surface.

Keep only these durable knowledge types in the repository working tree:

- implementation and executable data contracts;
- present-tense normative specifications;
- current operating policies and agent rules;
- ADRs explaining durable decisions;
- tests, schemas, fixtures, manifests, and executable baselines.

Do not track status reports, roadmaps, milestone reports, next-work sections, phase contracts, audit logs, or manual traceability ledgers. Preserve old files through normal Git history rather than rewriting history.

Use `AGENTS.md` as the shared cross-agent contract. Let Claude Code import it from `CLAUDE.md`. Treat agent memory and chats as non-authoritative.

## Consequences

- A clean checkout describes the product rather than the work diary.
- Issue and pull-request access is required to understand active work.
- Closing or deleting a branch cannot erase project rationale because the Issue, pull request, commit, and ADR remain.
- Behavioral changes must update current specs and tests in the same pull request.
- Test transcripts stay in CI and pull requests; executable regressions stay in Git only when code consumes them.
- Git history retains old progress documents, but they are not authoritative in the default branch tree.
