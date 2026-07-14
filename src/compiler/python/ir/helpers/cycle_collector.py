"""Linear-time non-mutating snapshot cycle collector runtime helper."""

from .core import HelperDef
from .cycle_collector_prefix import CYCLE_COLLECTOR_PREFIX
from .cycle_collector_suffix import CYCLE_COLLECTOR_SUFFIX

COLLECTOR_HELPERS = {
    "__btrc_collect_cycles": HelperDef(
        c_source=CYCLE_COLLECTOR_PREFIX + CYCLE_COLLECTOR_SUFFIX,
        depends_on=[
            "__btrc_suspect_state",
            "__btrc_ptr_hash",
            "__btrc_safe_realloc",
            "__btrc_arc_unregister_incoming",
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
            "__btrc_arc_lock_state",
            "__btrc_arc_snapshot_state",
            "__btrc_arc_topology_state",
            "__btrc_arc_deferred_state",
        ],
    ),
}

__all__ = ["COLLECTOR_HELPERS"]
