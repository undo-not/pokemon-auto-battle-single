# SIM-02 regulation pipeline provenance

This package is a clean-room implementation. It does not copy parser or fetcher
code from the legacy `champions` repository.

The legacy revision `59bf57cc3cdcb2eaa93cbab19eb9851a6fb15c1b` was audited for
interfaces and failure modes. Its fetcher usefully separated source configuration,
raw download, normalization, and reporting. Its regulation normalizer, however,
used a page-specific regular expression, returned `None` for missing fields, wrote
no content hash or license record, skipped its test when raw HTML was absent, and
had no versioned target-pool, coverage-gap, or regulation-diff contract.

SIM-02 therefore accepts only local normalized fixtures, requires every field,
binds snapshots to SHA-256 and source manifests, enforces unverified-license
restrictions, and fails closed before downstream adaptation. Network acquisition
is deliberately outside this vertical slice. Official notice URLs and effective
periods are versioned fixture inputs, never timeless constants in Python code.
