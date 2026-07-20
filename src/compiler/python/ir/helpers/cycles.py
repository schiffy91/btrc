"""Cycle-runtime helper registry assembled from focused modules."""

from .cycle_abandon import ARC_ABANDON_HELPERS
from .cycle_abandon_queue import ARC_ABANDON_QUEUE_HELPERS
from .cycle_boundaries import CYCLE_BOUNDARY_HELPERS
from .cycle_collector import COLLECTOR_HELPERS
from .cycle_drain import ARC_DRAIN_HELPERS
from .cycle_graph import ARC_GRAPH_HELPERS
from .cycle_incoming import ARC_INCOMING_HELPERS
from .cycle_lifecycle import ARC_LIFECYCLE_HELPERS
from .cycle_lock import ARC_LOCK_HELPERS
from .cycle_release import ARC_RELEASE_HELPERS
from .cycle_retain import ARC_RETAIN_HELPERS
from .cycle_snapshot import ARC_SNAPSHOT_HELPERS
from .cycle_state import ARC_STATE_HELPERS

CYCLES = {
    **ARC_STATE_HELPERS,
    **ARC_LOCK_HELPERS,
    **ARC_SNAPSHOT_HELPERS,
    **ARC_INCOMING_HELPERS,
    **ARC_RETAIN_HELPERS,
    **ARC_RELEASE_HELPERS,
    **ARC_LIFECYCLE_HELPERS,
    **ARC_GRAPH_HELPERS,
    **ARC_ABANDON_HELPERS,
    **ARC_ABANDON_QUEUE_HELPERS,
    **COLLECTOR_HELPERS,
    **ARC_DRAIN_HELPERS,
    **CYCLE_BOUNDARY_HELPERS,
}

__all__ = ["CYCLES"]
