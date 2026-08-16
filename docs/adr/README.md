# Architecture decision records

ADRs preserve durable decisions, their context, and their consequences. Project progress and implementation status belong in GitHub Issues and pull requests.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-issue-driven-project-state.md) | Keep project state in GitHub Issues and pull requests | Accepted |
| [ADR-0002](0002-artifact-storage-and-size-limits.md) | Keep large artifacts outside Git and enforce size limits | Accepted |
| [ADR-0003](0003-deterministic-unverified-battle-semantics.md) | Isolate deterministic but unverified battle semantics in RuleSet data | Accepted |
| [ADR-0004](0004-validation-budgets-and-regulation-sla.md) | Use bounded engineering regressions and a fail-closed adaptation SLA | Accepted |
| [ADR-0005](0005-external-production-trust-boundary.md) | Require externally enrolled asymmetric trust and anti-rollback state | Accepted |
| [ADR-0006](0006-conservative-evidence-intake.md) | Separate semantic authority from permission and promote conservatively | Accepted |

Serialized `PD-*` identifiers predate this ADR structure. They remain stable compatibility labels in frozen RuleSet, Replay, rehearsal, and benchmark artifacts and resolve to the ADRs listed below; they are not a project-status ledger.
