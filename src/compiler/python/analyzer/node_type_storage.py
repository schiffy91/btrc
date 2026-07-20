"""Canonical storage for inferred expression types."""

from __future__ import annotations


class NodeTypeStorageMixin:
    def _record_node_type(self, node, type_expr):
        """Store and return the canonical semantic type for ``node``."""
        canonical = self._canonical_type(type_expr)
        if canonical is not None:
            self.node_types[id(node)] = canonical
        return canonical


__all__ = ["NodeTypeStorageMixin"]
