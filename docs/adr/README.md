# Architecture decision records

ADRs preserve durable decisions, their context, and their consequences. Project progress and implementation status belong in GitHub Issues and pull requests.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-issue-driven-project-state.md) | Keep project state in GitHub Issues and pull requests | Accepted |
| [ADR-0002](0002-artifact-storage-and-size-limits.md) | Keep large artifacts outside Git and enforce size limits | Accepted |
| [ADR-0003](0003-deterministic-unverified-battle-semantics.md) | Isolate deterministic but unverified battle semantics in RuleSet data | Superseded by ADR-0007 |
| [ADR-0004](0004-validation-budgets-and-regulation-sla.md) | Use bounded engineering regressions and a fail-closed adaptation SLA | Superseded by ADR-0007 |
| [ADR-0005](0005-external-production-trust-boundary.md) | Require externally enrolled asymmetric trust and anti-rollback state | Accepted |
| [ADR-0006](0006-conservative-evidence-intake.md) | Separate semantic authority from permission and promote conservatively | Accepted |
| [ADR-0007](0007-pinned-showdown-champions-engine.md) | Use a pinned external Showdown Champions engine | Accepted |

Serialized `PD-*` identifiers belong only to historical custom-engine artifacts retained in Git history. They are not part of the current Showdown bridge or Replay contract.
