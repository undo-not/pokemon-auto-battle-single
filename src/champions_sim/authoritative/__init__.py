"""Fail-closed authoritative evidence workbench for SIM-02C-A."""

from .compiler import (
    AuthoritativeIntakeConfig,
    compile_authoritative_intake,
    load_source_acquisition_plan,
    load_source_policy_registry,
    write_authoritative_intake_documents,
)
from .models import (
    AUTHORITATIVE_INTAKE_COMPILER_VERSION,
    AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
    ArtifactIdentity,
    AuthoritativeIntakeCompilation,
    AuthoritativeIntakeError,
    IntakeBlocker,
    canonical_json,
    canonical_sha256,
)

__all__ = [
    "AUTHORITATIVE_INTAKE_COMPILER_VERSION",
    "AUTHORITATIVE_INTAKE_SCHEMA_VERSION",
    "ArtifactIdentity",
    "AuthoritativeIntakeCompilation",
    "AuthoritativeIntakeConfig",
    "AuthoritativeIntakeError",
    "IntakeBlocker",
    "canonical_json",
    "canonical_sha256",
    "compile_authoritative_intake",
    "load_source_acquisition_plan",
    "load_source_policy_registry",
    "write_authoritative_intake_documents",
]
