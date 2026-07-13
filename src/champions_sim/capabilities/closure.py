"""Public legal fixed-point closure boundary.

The implementation shares manifest-bound validation helpers with ``pipeline``;
this module keeps the closure API independently importable for downstream tools.
"""

from .pipeline import build_target_capability_set

__all__ = ["build_target_capability_set"]
