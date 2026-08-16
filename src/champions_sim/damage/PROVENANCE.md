# Damage implementation provenance

This package is an independent compatibility implementation. No source code from the legacy `undo-not/champions` checkout is copied because that checkout did not provide a repository-root license granting reuse.

The implementation retains only source-manifested, externally observable compatibility examples and is written with Python standard-library facilities. Rule values are versioned in the bound RuleSet and carry any applicable legacy decision identifiers described by ADR-0003.

The calculator implements only effects explicitly represented by `DamageInput` and the selected RuleSet. Unsupported items, abilities, weather, terrain, burn modifiers, screens, variable-power moves, spread modifiers, and other effects must appear in `unsupported_effects`; calculation raises `UnsupportedDamageMechanic` instead of ignoring or approximating them.
