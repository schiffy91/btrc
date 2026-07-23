"""Ownership provenance for one lexical ARC-managed local."""

from dataclasses import dataclass


@dataclass
class ManagedLocal:
    """A local owner and whether releasing it may expose an unreachable cycle."""

    name: str
    type_name: str
    cycle_seed: bool
    c_name: str | None = None
    cleanup_kind: str = "arc"

    def mark_cycle_seed(self) -> None:
        """Conservatively dirty this live ARC alias after graph mutation."""
        if self.cleanup_kind == "arc":
            self.cycle_seed = True
