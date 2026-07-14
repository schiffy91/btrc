"""Compatibility imports for persistent-edge ARC atoms."""

from __future__ import annotations

from .arc_ops import adopt_edge_if_present, release_edge_if_present

__all__ = ["adopt_edge_if_present", "release_edge_if_present"]
