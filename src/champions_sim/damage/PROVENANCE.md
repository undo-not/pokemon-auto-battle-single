# Damage implementation provenance

This package is a clean-room compatibility implementation for SIM-01.

The legacy `undo-not/champions` checkout was audited at commit
`59bf57cc3cdcb2eaa93cbab19eb9851a6fb15c1b`. No `LICENSE`, `LICENCE`,
`COPYING`, or `NOTICE` file was present at the repository root, so the old
source code was not copied.

Only externally observable compatibility facts were retained, including the
level-50, power-100, Attack-182 versus Defense-189 example whose sixteen rolls
are 37 through 44. The implementation and tests in this package were written
independently with Python 3.10 standard-library facilities.

SIM-01 supports only ordinary fixed-power physical and special damage, battle
ranks, ordinary STAB, ordinary type effectiveness, the sixteen 85--100 random
rolls, and a resolved critical-hit input. Items, abilities, weather, terrain,
burn, screens, variable-power moves, spread modifiers, and other effects must
be named in `DamageInput.unsupported_effects`; calculation then raises
`UnsupportedDamageMechanic` rather than approximating them.
