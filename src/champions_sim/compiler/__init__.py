"""Production Catalog-to-capability compiler boundary."""

from .bridge import CatalogBridgeProfile, compile_catalog_bridge
from .bridge_models import (
    CatalogBridgeResult,
    CatalogCompilerError,
    ProductionCatalogInput,
)
from .bundle import (
    SourceToCapabilityCompilation,
    SourceToCapabilityConfig,
    compile_source_to_capability_bundle,
    write_compilation_documents,
)
from .execution import compile_execution_registry
from .models import (
    CompiledProbePlan,
    ExecutionCompilation,
    ExecutionGap,
    SelectorDiagnostic,
    SemanticCompilation,
)
from .probes import compile_probe_plan, run_compiled_probe_plan
from .semantic import compile_effect_semantic_registry

__all__ = [
    "CatalogBridgeProfile",
    "CatalogBridgeResult",
    "CatalogCompilerError",
    "CompiledProbePlan",
    "ExecutionCompilation",
    "ExecutionGap",
    "ProductionCatalogInput",
    "SelectorDiagnostic",
    "SemanticCompilation",
    "SourceToCapabilityCompilation",
    "SourceToCapabilityConfig",
    "compile_catalog_bridge",
    "compile_effect_semantic_registry",
    "compile_execution_registry",
    "compile_probe_plan",
    "compile_source_to_capability_bundle",
    "run_compiled_probe_plan",
    "write_compilation_documents",
]
