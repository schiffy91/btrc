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


def mark_borrowed_cycle_seeds(scopes: list[list[ManagedLocal]]) -> None:
    """Conservatively dirty live aliases after a managed ownership mutation."""
    for scope in scopes:
        for local in scope:
            if local.cleanup_kind == "arc":
                local.cycle_seed = True
