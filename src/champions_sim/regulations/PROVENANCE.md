# Regulation pipeline provenance

This package is an independent implementation and does not copy parser or fetcher code from the legacy `champions` repository.

The regulation pipeline accepts versioned local inputs, requires complete schema fields, binds snapshots to SHA-256 and source manifests, preserves source-use policy, and fails closed before downstream adaptation. Official notice URLs, effective periods, target membership, and special rules are data rather than constants in Python code.

Network acquisition is not implicit. It requires a source-specific reviewed Issue and the permission boundary in `docs/policies/evidence-and-claims.md`. Downloaded and generated payloads remain outside Git under `docs/policies/artifacts-and-data.md`.
