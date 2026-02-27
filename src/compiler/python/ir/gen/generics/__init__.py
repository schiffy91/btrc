"""Generic monomorphization package: emit struct + methods for each generic instance."""

from .core import emit_generic_instances

__all__ = ["emit_generic_instances"]
