# ADR-0004: Use bounded engineering regressions and a fail-closed adaptation SLA

- Status: Accepted
- Date: 2026-08-17
- Legacy aliases: `PD-005`, `PD-008`, `PD-009`

## Context

The project needs repeatable engineering budgets that catch nondeterminism and integration drift without being mistaken for exhaustive correctness or competitive evidence. Regulation changes also require a decision early enough to leave time for operational preparation, while source publication and permission may be outside engineering control.

## Decision

Use these bounded contracts:

- run 10,000 seeded smoke battles before promoting a simulator bundle that changes transition behavior;
- run the frozen synthetic arena over 64 seed pairs and both seats, for 128 matches, as an engineering regression;
- from a sealed regulation input at `t0`, emit a verified candidate or reasoned `NO-GO` within 48 hours;
- complete the private-match deployment decision within seven days.

Record compute, manual work, and external wait separately. A reasoned `NO-GO` within 48 hours counts as operational rehearsal success but not deployable-candidate success. Never reduce denominators, skip permission or holdout gates, or use unverified defaults to meet the SLA.

## Consequences

- Test budgets are stable and automatable.
- Smoke count and synthetic match count do not claim state-space coverage or real-game strength.
- The adaptation process remains useful when external evidence is missing because it produces explicit restart conditions.
- A real or sealed-historical rehearsal is required before claiming the wall-clock objective was measured.
