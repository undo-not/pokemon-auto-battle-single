"""Trust-attested SIM-02C production compiler.

V2 remains the local engineering compiler and always rejects production
sources through its public API.  This module is the only supported production
entry: it rehydrates a path-independent input manifest, verifies a fresh
artifact-root-external trust context both before and after compilation, and
wraps the fully recomputed V2 substance in a stable V3 evidence projection.

The external trust context is a root capability.  It is never serialized or
retained by the compilation.  Code integrity inside this Python process is an
explicit trust assumption; private helpers are misuse boundaries, not a
cryptographic sandbox against malicious imported code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from champions_sim.core import ReplayRecord, canonical_hash, canonical_json, to_canonical_data
from champions_sim.grounding import ValidatedGroundingTrace
from champions_sim.regulations import load_regulation_snapshot, load_target_pool

from .compiler import (
    ProductionPromotionCompilationV2,
    ProductionPromotionRequestV2,
    ResolvedPromotionSourceSetV2,
    _VerifiedProductionTrustProofV3,
    _compile_verified_production_promotion_v3_substance,
    resolve_promotion_source_set_v2,
)
from .input_manifest import (
    ProductionPromotionInputManifestV3,
    build_production_promotion_input_manifest_v3,
    production_promotion_request_binding_hash_v3,
)
from .scenarios import EngineScenarioCorpusV2
from .sources import PromotionSourceScopeV2, read_resolved_artifact
from .trust import (
    PRODUCTION_TRUST_DOMAIN,
    PRODUCTION_TRUST_ENVIRONMENT,
    PRODUCTION_TRUST_PROJECT_ID,
    PRODUCTION_TRUST_PURPOSE,
    PRODUCTION_TRUST_SCHEMA_VERSION,
    PRODUCTION_TRUST_SCOPE,
    ProductionTrustAttestationV1,
    ProductionTrustContextV1,
    ProductionTrustSubjectV1,
    ResolvedProductionTrustV1,
    verify_production_trust_v1,
)
from .trust_enrollment import (
    ResolvedProductionTrustEnrollmentV1,
    resolve_production_trust_enrollment_v1,
    validate_production_trust_receipt_enrollment_v1,
)


PRODUCTION_PROMOTION_COMPILATION_V3_SCHEMA_VERSION = "3.0.0"
PRODUCTION_PROMOTION_COMPILER_V3_ID = "champions-production-promotion-v3"
PRODUCTION_PROMOTION_COMPILER_V3_CONTRACT = "sim-02c-production-promotion-v3"
PRODUCTION_TRUST_AUTHORIZATION_BINDING_SCHEMA_VERSION = "1.0.0"
PRODUCTION_TRUST_AUTHORIZATION_BINDING_DOMAIN = (
    "champions-sim.production-trust-authorization-binding.v1"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOCUMENT_NAMES = frozenset(
    {
        "production-promotion-input-manifest-v3.json",
        "production-promotion-compilation-v2.json",
        "production-trust-attestation-v1.json",
        "production-trust-authorization-binding-v1.json",
    }
)


class ProductionPromotionV3Error(ValueError):
    """A trust-attested production compilation is absent or inconsistent."""


def _sha256(value: Any, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ProductionPromotionV3Error(f"{label} must be a lowercase SHA-256")


def stable_production_trust_binding_data_v3(
    receipt: ResolvedProductionTrustV1,
    enrollment: ResolvedProductionTrustEnrollmentV1,
) -> dict[str, Any]:
    """Return the authorization identity, excluding the verification event time."""

    if type(receipt) is not ResolvedProductionTrustV1:
        raise ProductionPromotionV3Error(
            "stable trust binding requires an exact resolved trust receipt"
        )
    if type(enrollment) is not ResolvedProductionTrustEnrollmentV1:
        raise ProductionPromotionV3Error(
            "stable trust binding requires an exact external enrollment"
        )
    receipt.__post_init__()
    enrollment.__post_init__()
    try:
        validate_production_trust_receipt_enrollment_v1(enrollment, receipt)
    except Exception as error:
        raise ProductionPromotionV3Error(
            "stable trust binding receipt differs from external enrollment"
        ) from error
    data = receipt.to_data()
    trust_receipt_schema_version = data.pop("schema_version")
    data.pop("verified_at")
    return {
        "schema_version": PRODUCTION_TRUST_AUTHORIZATION_BINDING_SCHEMA_VERSION,
        "binding_domain": PRODUCTION_TRUST_AUTHORIZATION_BINDING_DOMAIN,
        "authorization_status": "not_authorization",
        "current_trust_context_required": True,
        "trust_receipt_schema_version": trust_receipt_schema_version,
        "trust_enrollment_schema_version": enrollment.schema_version,
        "trust_enrollment_domain": enrollment.domain,
        "trust_registry_id": enrollment.registry_id,
        "trust_registry_sha256": enrollment.registry_sha256,
        "trust_enrollment_id": enrollment.enrollment_id,
        "trust_enrollment_binding_hash": enrollment.enrollment_binding_hash,
        "trust_enrollment_policy_id": enrollment.policy_id,
        "trust_enrollment_policy_sha256": enrollment.policy_sha256,
        "trust_enrollment_ssh_keygen_sha256": enrollment.ssh_keygen_sha256,
        "trust_enrollment_ledger_instance_id": enrollment.ledger_instance_id,
        "trust_enrollment_ledger_path_binding_hash": (
            enrollment.ledger_path_binding_hash
        ),
        "trust_enrollment_minimum_policy_epoch": enrollment.minimum_policy_epoch,
        "trust_enrollment_not_before": enrollment.not_before,
        "trust_enrollment_expires_at": enrollment.expires_at,
        **data,
    }


def stable_production_trust_binding_hash_v3(
    receipt: ResolvedProductionTrustV1,
    enrollment: ResolvedProductionTrustEnrollmentV1,
) -> str:
    return canonical_hash(
        stable_production_trust_binding_data_v3(receipt, enrollment)
    )


def _replay_binding_hash(
    manifest: ProductionPromotionInputManifestV3,
) -> str:
    return canonical_hash(
        tuple(
            (value.scenario_id, value.artifact.to_data())
            for value in manifest.replay_artifact_bindings
        )
    )


def _source_authority_subject_hash(source_set: Any) -> str:
    return canonical_hash(
        {
            "schema_version": PRODUCTION_TRUST_SCHEMA_VERSION,
            "source_scope": source_set.scope.value,
            "manifests": [
                {
                    "resolution_hash": value.resolution_hash,
                    "manifest": to_canonical_data(value),
                }
                for value in source_set.manifests
            ],
        }
    )


def _load_regulation_and_target_pool(
    request: ProductionPromotionRequestV2,
    source_set: Any,
) -> tuple[Any, Any]:
    try:
        regulation_payload = read_resolved_artifact(
            request.artifact_root,
            source_set.artifact(request.artifacts.regulation),
        )
        target_pool_payload = read_resolved_artifact(
            request.artifact_root,
            source_set.artifact(request.artifacts.target_pool),
        )
        with TemporaryDirectory(prefix="champions-trust-subject-v3-") as directory:
            root = Path(directory)
            regulation_path = root / "regulation.json"
            target_pool_path = root / "target-pool.json"
            regulation_path.write_bytes(regulation_payload)
            target_pool_path.write_bytes(target_pool_payload)
            regulation = load_regulation_snapshot(regulation_path)
            target_pool = load_target_pool(target_pool_path)
    except Exception as error:
        raise ProductionPromotionV3Error(
            "cannot resolve Regulation/TargetPool for production trust subject"
        ) from error
    if (
        regulation.regulation_id != target_pool.regulation_id
        or regulation.revision != target_pool.regulation_revision
    ):
        raise ProductionPromotionV3Error(
            "Regulation and TargetPool identities differ in trust subject"
        )
    if regulation.status != "current" or regulation.verification_status != "verified":
        raise ProductionPromotionV3Error(
            "production trust subject requires current verified Regulation"
        )
    return regulation, target_pool


def derive_production_trust_subject_v1(
    input_manifest: ProductionPromotionInputManifestV3,
    *,
    artifact_root: Path,
) -> ProductionTrustSubjectV1:
    """Derive the exact subject an external issuer may approve.

    This function grants no authority and performs no signing.  The supplied
    artifact root is external runtime state and is intentionally absent from
    the resulting subject and portable manifest.
    """

    if type(input_manifest) is not ProductionPromotionInputManifestV3:
        raise ProductionPromotionV3Error(
            "subject derivation requires an exact V3 input manifest"
        )
    input_manifest.__post_init__()
    if input_manifest.source_scope is not PromotionSourceScopeV2.PRODUCTION_CHAMPIONS:
        raise ProductionPromotionV3Error(
            "V3 production trust requires production_champions source scope"
        )
    try:
        request = input_manifest.rehydrate(artifact_root=artifact_root)
        rebuilt = build_production_promotion_input_manifest_v3(request)
        source_set = resolve_promotion_source_set_v2(request)
    except Exception as error:
        raise ProductionPromotionV3Error(
            "cannot rehydrate exact production inputs for trust subject"
        ) from error
    if rebuilt.to_data() != input_manifest.to_data():
        raise ProductionPromotionV3Error(
            "portable input manifest differs from current artifact substance"
        )
    if source_set.scope is not PromotionSourceScopeV2.PRODUCTION_CHAMPIONS:
        raise ProductionPromotionV3Error(
            "resolved source scope is not production_champions"
        )
    if production_promotion_request_binding_hash_v3(request) != input_manifest.request_binding_hash:
        raise ProductionPromotionV3Error(
            "production request binding differs from portable input manifest"
        )
    regulation, target_pool = _load_regulation_and_target_pool(request, source_set)
    return ProductionTrustSubjectV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        domain=PRODUCTION_TRUST_DOMAIN,
        project_id=PRODUCTION_TRUST_PROJECT_ID,
        purpose=PRODUCTION_TRUST_PURPOSE,
        environment=PRODUCTION_TRUST_ENVIRONMENT,
        compiler_contract_version=PRODUCTION_PROMOTION_COMPILER_V3_CONTRACT,
        attestation_scope=PRODUCTION_TRUST_SCOPE,
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        regulation_hash=regulation.snapshot_hash,
        target_pool_id=target_pool.target_pool_id,
        target_pool_hash=target_pool.snapshot_hash,
        source_authority_subject_hash=_source_authority_subject_hash(source_set),
        request_binding_hash=input_manifest.request_binding_hash,
        replay_binding_hash=_replay_binding_hash(input_manifest),
    )


def _stable_authorizations_match(
    first_receipt: ResolvedProductionTrustV1,
    first_enrollment: ResolvedProductionTrustEnrollmentV1,
    second_receipt: ResolvedProductionTrustV1,
    second_enrollment: ResolvedProductionTrustEnrollmentV1,
) -> bool:
    return stable_production_trust_binding_data_v3(
        first_receipt,
        first_enrollment,
    ) == stable_production_trust_binding_data_v3(
        second_receipt,
        second_enrollment,
    )


def _assert_context_root(
    input_manifest: ProductionPromotionInputManifestV3,
    context: ProductionTrustContextV1,
) -> Path:
    if type(input_manifest) is not ProductionPromotionInputManifestV3:
        raise ProductionPromotionV3Error(
            "V3 production compilation requires an exact input manifest"
        )
    input_manifest.__post_init__()
    if type(context) is not ProductionTrustContextV1:
        raise ProductionPromotionV3Error(
            "V3 production compilation requires an exact external trust context"
        )
    context.__post_init__()
    try:
        root = context.artifact_root.resolve(strict=True)
    except OSError as error:
        raise ProductionPromotionV3Error("trust context artifact_root does not resolve") from error
    if not root.is_dir():
        raise ProductionPromotionV3Error("trust context artifact_root must be a directory")
    # Rehydration proves that this exact root contains the manifest's bytes.
    try:
        input_manifest.rehydrate(artifact_root=root)
    except Exception as error:
        raise ProductionPromotionV3Error(
            "trust context artifact_root differs from portable input substance"
        ) from error
    return root


def _resolve_current_enrollment(
    context: ProductionTrustContextV1,
    *,
    phase: str,
) -> ResolvedProductionTrustEnrollmentV1:
    try:
        return resolve_production_trust_enrollment_v1(context)
    except Exception as error:
        raise ProductionPromotionV3Error(
            f"{phase} external production trust enrollment is unavailable"
        ) from error


def _assert_base_subject_binding(
    base: ProductionPromotionCompilationV2,
    subject: ProductionTrustSubjectV1,
    input_manifest: ProductionPromotionInputManifestV3,
) -> None:
    if base.source_set.scope is not PromotionSourceScopeV2.PRODUCTION_CHAMPIONS:
        raise ProductionPromotionV3Error("V3 base compilation is not production-scoped")
    report = base.report
    if (
        report.attestation_scope != PRODUCTION_TRUST_SCOPE
        or report.champions_candidate is not True
        or report.champions_fidelity_status != "evidence_attested"
        or report.rank1_equivalence_status != "unmeasured"
    ):
        raise ProductionPromotionV3Error(
            "V3 base report production semantics differ"
        )
    regulation = base.regulation_bundle.regulation
    target_pool = base.regulation_bundle.target_pool
    if (
        regulation.regulation_id != subject.regulation_id
        or regulation.revision != subject.regulation_revision
        or regulation.snapshot_hash != subject.regulation_hash
        or target_pool.target_pool_id != subject.target_pool_id
        or target_pool.snapshot_hash != subject.target_pool_hash
        or report.regulation_hash != subject.regulation_hash
        or report.target_pool_hash != subject.target_pool_hash
    ):
        raise ProductionPromotionV3Error(
            "V3 base Regulation/TargetPool differs from attested subject"
        )
    initial_source_set = _initial_source_set_retained_by_base(base)
    if (
        _source_authority_subject_hash(initial_source_set)
        != subject.source_authority_subject_hash
        or initial_source_set.resolution_set_hash
        != input_manifest.source_resolution_set_hash
    ):
        raise ProductionPromotionV3Error(
            "V3 base source snapshot differs from attested input authority"
        )
    if (
        production_promotion_request_binding_hash_v3(base._request)
        != subject.request_binding_hash
    ):
        raise ProductionPromotionV3Error(
            "V3 base request differs from attested request binding"
        )
    if input_manifest.request_binding_hash != subject.request_binding_hash:
        raise ProductionPromotionV3Error(
            "V3 input request binding differs from attested subject"
        )
    if _replay_binding_hash(input_manifest) != subject.replay_binding_hash:
        raise ProductionPromotionV3Error(
            "V3 Replay binding differs from attested subject"
        )


def _initial_source_set_retained_by_base(
    base: ProductionPromotionCompilationV2,
) -> ResolvedPromotionSourceSetV2:
    """Recover the exact source snapshot consumed at core entry.

    The core attaches mapping/construction record references to the already
    resolved manifests after parsing bound artifacts.  Filtering those later
    references leaves the immutable entry snapshot, including every manifest
    and artifact digest.  This prevents a change-compile-restore race from
    being hidden by a fresh post-compile filesystem resolution.
    """

    expected = {
        value.evidence_ref_id: value
        for value in base._request.grounding_evidence_refs
    }
    seen: set[str] = set()
    manifests = []
    for manifest in base.source_set.manifests:
        records = []
        for record in manifest.records:
            evidence_id = record.reference.evidence_ref_id
            if evidence_id not in expected:
                continue
            if record.reference != expected[evidence_id]:
                raise ProductionPromotionV3Error(
                    "V3 base grounding reference differs from retained request"
                )
            records.append(record)
            seen.add(evidence_id)
        manifests.append(replace(manifest, records=tuple(records)))
    if seen != set(expected):
        raise ProductionPromotionV3Error(
            "V3 base source snapshot omits retained grounding references"
        )
    ordered = tuple(sorted(manifests, key=lambda value: value.manifest_id))
    source_set_id = "promotion-source-set-" + canonical_hash(
        tuple((value.manifest_id, value.resolution_hash) for value in ordered)
    )
    return ResolvedPromotionSourceSetV2(
        schema_version=base.source_set.schema_version,
        source_set_id=source_set_id,
        scope=base.source_set.scope,
        manifests=ordered,
    )


@dataclass(frozen=True, slots=True)
class AttestedProductionPromotionCompilationV3:
    """Stable evidence projection retaining runtime substance for revalidation."""

    schema_version: str
    compiler_id: str
    authorization_status: str
    current_trust_context_required: bool
    input_manifest: ProductionPromotionInputManifestV3
    trust_attestation: ProductionTrustAttestationV1
    base_compilation: ProductionPromotionCompilationV2
    documents: Mapping[str, str]
    _trust_receipt: ResolvedProductionTrustV1 = field(repr=False, compare=False)
    _trust_enrollment: ResolvedProductionTrustEnrollmentV1 = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCTION_PROMOTION_COMPILATION_V3_SCHEMA_VERSION:
            raise ProductionPromotionV3Error("unsupported V3 compilation schema_version")
        if self.compiler_id != PRODUCTION_PROMOTION_COMPILER_V3_ID:
            raise ProductionPromotionV3Error("unsupported V3 compiler identity")
        if self.authorization_status != "not_authorization":
            raise ProductionPromotionV3Error(
                "portable V3 compilation cannot claim standalone authorization"
            )
        if self.current_trust_context_required is not True:
            raise ProductionPromotionV3Error(
                "V3 compilation must require current external trust context"
            )
        if type(self.input_manifest) is not ProductionPromotionInputManifestV3:
            raise ProductionPromotionV3Error("V3 compilation requires exact input manifest")
        if type(self.trust_attestation) is not ProductionTrustAttestationV1:
            raise ProductionPromotionV3Error("V3 compilation requires exact trust attestation")
        if type(self.base_compilation) is not ProductionPromotionCompilationV2:
            raise ProductionPromotionV3Error("V3 compilation requires exact V2 substance")
        if type(self._trust_receipt) is not ResolvedProductionTrustV1:
            raise ProductionPromotionV3Error("V3 compilation requires resolved trust receipt")
        if type(self._trust_enrollment) is not ResolvedProductionTrustEnrollmentV1:
            raise ProductionPromotionV3Error(
                "V3 compilation requires resolved external trust enrollment"
            )
        self.input_manifest.__post_init__()
        self.trust_attestation.__post_init__()
        self._trust_receipt.__post_init__()
        self._trust_enrollment.__post_init__()
        subject = self.trust_attestation.statement.subject
        if (
            self.trust_attestation.attestation_hash
            != self._trust_receipt.attestation_hash
            or subject.subject_hash != self._trust_receipt.subject_hash
        ):
            raise ProductionPromotionV3Error(
                "V3 attestation and resolved trust receipt differ"
            )
        try:
            validate_production_trust_receipt_enrollment_v1(
                self._trust_enrollment,
                self._trust_receipt,
            )
        except Exception as error:
            raise ProductionPromotionV3Error(
                "V3 trust receipt differs from retained external enrollment"
            ) from error
        _assert_base_subject_binding(self.base_compilation, subject, self.input_manifest)
        self._validate_documents()

    @property
    def trust_subject(self) -> ProductionTrustSubjectV1:
        return self.trust_attestation.statement.subject

    @property
    def stable_trust_binding_hash(self) -> str:
        return stable_production_trust_binding_hash_v3(
            self._trust_receipt,
            self._trust_enrollment,
        )

    def _expected_documents(self) -> dict[str, str]:
        return {
            "production-promotion-input-manifest-v3.json": self.input_manifest.to_json(),
            "production-promotion-compilation-v2.json": self.base_compilation.to_json(),
            "production-trust-attestation-v1.json": canonical_json(
                self.trust_attestation.to_data()
            ),
            "production-trust-authorization-binding-v1.json": canonical_json(
                stable_production_trust_binding_data_v3(
                    self._trust_receipt,
                    self._trust_enrollment,
                )
            ),
        }

    def _validate_documents(self) -> None:
        if not isinstance(self.documents, Mapping) or set(self.documents) != _DOCUMENT_NAMES:
            raise ProductionPromotionV3Error("V3 document membership differs")
        if any(type(name) is not str or type(value) is not str for name, value in self.documents.items()):
            raise ProductionPromotionV3Error("V3 documents must be named UTF-8 strings")
        if dict(self.documents) != self._expected_documents():
            raise ProductionPromotionV3Error("V3 document content differs from retained substance")

    def document_digests(self) -> tuple[dict[str, Any], ...]:
        self._validate_documents()
        return tuple(
            {
                "file_name": name,
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "byte_count": len(value.encode("utf-8")),
            }
            for name, value in sorted(self.documents.items())
        )

    @property
    def document_set_hash(self) -> str:
        return canonical_hash(self.document_digests())

    def unsigned_data(self) -> dict[str, Any]:
        subject = self.trust_subject
        receipt = self._trust_receipt
        enrollment = self._trust_enrollment
        return {
            "schema_version": self.schema_version,
            "compilation_id": self.compilation_id,
            "compiler_id": self.compiler_id,
            "authorization_status": self.authorization_status,
            "current_trust_context_required": self.current_trust_context_required,
            "attestation_scope": PRODUCTION_TRUST_SCOPE,
            "champions_candidate": True,
            "champions_fidelity_status": "evidence_attested",
            "rank1_equivalence_status": "unmeasured",
            "input_manifest_id": self.input_manifest.manifest_id,
            "input_manifest_hash": self.input_manifest.manifest_hash,
            "input_content_hash": self.input_manifest.input_content_hash,
            "request_binding_hash": self.input_manifest.request_binding_hash,
            "replay_binding_hash": subject.replay_binding_hash,
            "base_compilation_id": self.base_compilation.compilation_id,
            "base_compilation_hash": self.base_compilation.compilation_hash,
            "base_promotion_report_hash": self.base_compilation.report_hash,
            "trust_attestation_id": receipt.attestation_id,
            "trust_attestation_hash": receipt.attestation_hash,
            "trust_subject_hash": receipt.subject_hash,
            "stable_trust_binding_hash": self.stable_trust_binding_hash,
            "trust_policy_id": receipt.policy_id,
            "trust_policy_epoch": receipt.policy_epoch,
            "trust_policy_sha256": receipt.policy_sha256,
            "trust_issuer_id": receipt.issuer_id,
            "trust_key_id": receipt.key_id,
            "trust_key_fingerprint_sha256": receipt.key_fingerprint_sha256,
            "trust_ledger_binding_hash": receipt.ledger_binding_hash,
            "trust_registry_id": enrollment.registry_id,
            "trust_registry_sha256": enrollment.registry_sha256,
            "trust_enrollment_id": enrollment.enrollment_id,
            "trust_enrollment_binding_hash": enrollment.enrollment_binding_hash,
            "trust_enrollment_minimum_policy_epoch": (
                enrollment.minimum_policy_epoch
            ),
            "trust_enrollment_ssh_keygen_sha256": enrollment.ssh_keygen_sha256,
            "trust_ledger_instance_id": enrollment.ledger_instance_id,
            "trust_ledger_path_binding_hash": enrollment.ledger_path_binding_hash,
            "regulation_id": subject.regulation_id,
            "regulation_revision": subject.regulation_revision,
            "regulation_hash": subject.regulation_hash,
            "target_pool_id": subject.target_pool_id,
            "target_pool_hash": subject.target_pool_hash,
            "source_authority_subject_hash": subject.source_authority_subject_hash,
            "documents": list(self.document_digests()),
            "document_set_hash": self.document_set_hash,
        }

    @property
    def compilation_id(self) -> str:
        return "attested-production-promotion-v3-" + canonical_hash(
            {
                "input_manifest_hash": self.input_manifest.manifest_hash,
                "base_compilation_hash": self.base_compilation.compilation_hash,
                "attestation_hash": self.trust_attestation.attestation_hash,
                "stable_trust_binding_hash": self.stable_trust_binding_hash,
                "document_set_hash": self.document_set_hash,
            }
        )

    @property
    def compilation_hash(self) -> str:
        return canonical_hash(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "compilation_hash": self.compilation_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


def _build_v3_documents(
    *,
    input_manifest: ProductionPromotionInputManifestV3,
    attestation: ProductionTrustAttestationV1,
    base: ProductionPromotionCompilationV2,
    receipt: ResolvedProductionTrustV1,
    enrollment: ResolvedProductionTrustEnrollmentV1,
) -> dict[str, str]:
    return {
        "production-promotion-input-manifest-v3.json": input_manifest.to_json(),
        "production-promotion-compilation-v2.json": base.to_json(),
        "production-trust-attestation-v1.json": canonical_json(attestation.to_data()),
        "production-trust-authorization-binding-v1.json": canonical_json(
            stable_production_trust_binding_data_v3(receipt, enrollment)
        ),
    }


def compile_attested_production_promotion_v3(
    input_manifest: ProductionPromotionInputManifestV3,
    *,
    attestation: ProductionTrustAttestationV1,
    trust_context: ProductionTrustContextV1,
    development_scenario_corpus: EngineScenarioCorpusV2,
    external_holdout_scenario_corpus: EngineScenarioCorpusV2,
    replays: Mapping[str, ReplayRecord],
    validated_traces: Mapping[str, ValidatedGroundingTrace] | None = None,
) -> AttestedProductionPromotionCompilationV3:
    """Verify trust around a full production compile and return stable evidence."""

    root = _assert_context_root(input_manifest, trust_context)
    enrollment_before = _resolve_current_enrollment(
        trust_context,
        phase="pre-compilation",
    )
    subject_before = derive_production_trust_subject_v1(
        input_manifest,
        artifact_root=root,
    )
    try:
        receipt_before = verify_production_trust_v1(
            attestation,
            subject_before,
            trust_context,
        )
        validate_production_trust_receipt_enrollment_v1(
            enrollment_before,
            receipt_before,
        )
        request = input_manifest.rehydrate(artifact_root=root)
        base = _compile_verified_production_promotion_v3_substance(
            request,
            trust_proof=_VerifiedProductionTrustProofV3(
                subject_before,
                receipt_before,
                enrollment_before,
            ),
            development_scenario_corpus=development_scenario_corpus,
            external_holdout_scenario_corpus=external_holdout_scenario_corpus,
            replays=replays,
            validated_traces=validated_traces,
        )
    except Exception as error:
        raise ProductionPromotionV3Error(
            "trust-attested production compilation failed"
        ) from error
    _assert_base_subject_binding(base, subject_before, input_manifest)
    subject_after = derive_production_trust_subject_v1(
        input_manifest,
        artifact_root=root,
    )
    if subject_after.to_data() != subject_before.to_data():
        raise ProductionPromotionV3Error(
            "production trust subject changed during compilation"
        )
    enrollment_after = _resolve_current_enrollment(
        trust_context,
        phase="post-compilation",
    )
    try:
        receipt_after = verify_production_trust_v1(
            attestation,
            subject_after,
            trust_context,
        )
        validate_production_trust_receipt_enrollment_v1(
            enrollment_after,
            receipt_after,
        )
    except Exception as error:
        raise ProductionPromotionV3Error(
            "post-compilation production trust verification failed"
        ) from error
    if not _stable_authorizations_match(
        receipt_before,
        enrollment_before,
        receipt_after,
        enrollment_after,
    ):
        raise ProductionPromotionV3Error(
            "production trust authorization changed during compilation"
        )
    return AttestedProductionPromotionCompilationV3(
        schema_version=PRODUCTION_PROMOTION_COMPILATION_V3_SCHEMA_VERSION,
        compiler_id=PRODUCTION_PROMOTION_COMPILER_V3_ID,
        authorization_status="not_authorization",
        current_trust_context_required=True,
        input_manifest=input_manifest,
        trust_attestation=attestation,
        base_compilation=base,
        documents=_build_v3_documents(
            input_manifest=input_manifest,
            attestation=attestation,
            base=base,
            receipt=receipt_after,
            enrollment=enrollment_after,
        ),
        _trust_receipt=receipt_after,
        _trust_enrollment=enrollment_after,
    )


def _revalidate_attested_production_promotion_v3(
    compilation: AttestedProductionPromotionCompilationV3,
    *,
    trust_context: ProductionTrustContextV1,
) -> tuple[AttestedProductionPromotionCompilationV3, ResolvedProductionTrustV1]:
    if type(compilation) is not AttestedProductionPromotionCompilationV3:
        raise ProductionPromotionV3Error(
            "V3 validation requires exact attested compilation"
        )
    compilation.__post_init__()
    root = _assert_context_root(compilation.input_manifest, trust_context)
    enrollment_before = _resolve_current_enrollment(
        trust_context,
        phase="current-context V3 recompilation failed: pre-revalidation",
    )
    subject_before = derive_production_trust_subject_v1(
        compilation.input_manifest,
        artifact_root=root,
    )
    if subject_before.to_data() != compilation.trust_subject.to_data():
        raise ProductionPromotionV3Error(
            "current compiler subject differs from signed V3 subject"
        )
    try:
        current_receipt = verify_production_trust_v1(
            compilation.trust_attestation,
            subject_before,
            trust_context,
        )
        validate_production_trust_receipt_enrollment_v1(
            enrollment_before,
            current_receipt,
        )
        if not _stable_authorizations_match(
            compilation._trust_receipt,
            compilation._trust_enrollment,
            current_receipt,
            enrollment_before,
        ):
            raise ProductionPromotionV3Error(
                "retained V3 authorization differs from current enrollment"
            )
        request = compilation.input_manifest.rehydrate(artifact_root=root)
        base = _compile_verified_production_promotion_v3_substance(
            request,
            trust_proof=_VerifiedProductionTrustProofV3(
                subject_before,
                current_receipt,
                enrollment_before,
            ),
            development_scenario_corpus=(
                compilation.base_compilation.development_scenario_corpus
            ),
            external_holdout_scenario_corpus=(
                compilation.base_compilation.external_holdout_scenario_corpus
            ),
            replays=dict(compilation.base_compilation._replays),
            validated_traces=dict(
                compilation.base_compilation._validated_traces
            ),
        )
    except Exception as error:
        raise ProductionPromotionV3Error(
            "current-context V3 recompilation failed"
        ) from error
    if base != compilation.base_compilation:
        raise ProductionPromotionV3Error(
            "V3 base compilation differs from current full recomputation"
        )
    _assert_base_subject_binding(base, subject_before, compilation.input_manifest)
    subject_after = derive_production_trust_subject_v1(
        compilation.input_manifest,
        artifact_root=root,
    )
    if subject_after.to_data() != subject_before.to_data():
        raise ProductionPromotionV3Error(
            "production trust subject changed during V3 revalidation"
        )
    enrollment_after = _resolve_current_enrollment(
        trust_context,
        phase="current-context V3 recompilation failed: post-revalidation",
    )
    try:
        receipt_after = verify_production_trust_v1(
            compilation.trust_attestation,
            subject_after,
            trust_context,
        )
        validate_production_trust_receipt_enrollment_v1(
            enrollment_after,
            receipt_after,
        )
    except Exception as error:
        raise ProductionPromotionV3Error(
            "post-recompilation production trust verification failed"
        ) from error
    if (
        not _stable_authorizations_match(
            current_receipt,
            enrollment_before,
            receipt_after,
            enrollment_after,
        )
        or not _stable_authorizations_match(
            compilation._trust_receipt,
            compilation._trust_enrollment,
            receipt_after,
            enrollment_after,
        )
    ):
        raise ProductionPromotionV3Error(
            "V3 stable trust authorization differs from current context"
        )
    return compilation, receipt_after


def validate_attested_production_promotion_compilation_v3(
    compilation: AttestedProductionPromotionCompilationV3,
    *,
    trust_context: ProductionTrustContextV1,
) -> AttestedProductionPromotionCompilationV3:
    """Reverify current external trust and fully recompile retained inputs."""

    resolved, _ = _revalidate_attested_production_promotion_v3(
        compilation,
        trust_context=trust_context,
    )
    return resolved


__all__ = [
    "PRODUCTION_PROMOTION_COMPILATION_V3_SCHEMA_VERSION",
    "PRODUCTION_PROMOTION_COMPILER_V3_CONTRACT",
    "PRODUCTION_PROMOTION_COMPILER_V3_ID",
    "PRODUCTION_TRUST_AUTHORIZATION_BINDING_DOMAIN",
    "PRODUCTION_TRUST_AUTHORIZATION_BINDING_SCHEMA_VERSION",
    "AttestedProductionPromotionCompilationV3",
    "ProductionPromotionV3Error",
    "compile_attested_production_promotion_v3",
    "derive_production_trust_subject_v1",
    "stable_production_trust_binding_data_v3",
    "stable_production_trust_binding_hash_v3",
    "validate_attested_production_promotion_compilation_v3",
]
