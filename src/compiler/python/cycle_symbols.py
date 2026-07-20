"""Canonical compiler-reserved ARC cycle metadata symbols."""


def cycle_visitor_symbol(emitted_name: str) -> str:
    return f"__btrc_arc_visit_{emitted_name}"


__all__ = ["cycle_visitor_symbol"]
