"""Shared linear-time managed-graph scratch primitives."""

from .core import HelperDef
from .cycle_collector_prefix import (
    CYCLE_COLLECTOR_PRIMITIVES,
    CYCLE_COLLECTOR_STATE,
)

ARC_GRAPH_HELPERS = {
    "__btrc_cycle_collector_state": HelperDef(
        c_source=CYCLE_COLLECTOR_STATE,
    ),
    "__btrc_arc_graph_primitives": HelperDef(
        c_source=CYCLE_COLLECTOR_PRIMITIVES,
        depends_on=[
            "__btrc_cycle_collector_state",
            "__btrc_ptr_hash",
            "__btrc_safe_realloc",
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
        ],
    ),
}

__all__ = ["ARC_GRAPH_HELPERS"]
