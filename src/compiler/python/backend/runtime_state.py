"""Runtime helper C text split at top level, and its file-scope state shaped
for one translation unit of a split program.

The stdlib archive and ``--emit-units`` both need one definition of every
mutable runtime variable across several C files. The helpers are written as
plain ``static`` definitions; the unit that owns the state drops ``static``
and the others declare the same names ``extern`` without an initializer.
"""

from __future__ import annotations


def split_toplevel_units(source: str) -> list[str]:
    """Top-level C units: one declaration, definition or directive each.
    Blank lines and comments between units are dropped."""

    units: list[str] = []
    current: list[str] = []
    depth = 0
    directive = False
    for line in source.split("\n"):
        stripped = line.strip()
        if directive or (not current and stripped.startswith("#")):
            current.append(line)
            directive = stripped.endswith("\\")
            if not directive:
                units.append("\n".join(current))
                current = []
            continue
        if not current and (
            not stripped or stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("//")
        ):
            continue
        current.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0 and (stripped.endswith(";") or stripped.endswith("}")):
            units.append("\n".join(current))
            current = []
    if current:
        units.append("\n".join(current))
    return units


def function_definition_prototype(unit: str) -> str | None:
    """The prototype of a function definition unit, or None for anything else."""

    if unit.lstrip().startswith("#"):
        return None
    brace = unit.find("{")
    if brace < 0:
        return None
    signature = unit[:brace].rstrip()
    return None if "(" not in signature or signature.endswith("=") else signature + ";"


def is_mutable_state(unit: str) -> bool:
    """A ``static`` file-scope variable that is neither const nor a function."""

    head = unit.lstrip()
    if not head.startswith("static ") or head.startswith(("static const ", "static inline ")):
        return False
    return function_definition_prototype(unit) is None


def unit_state(source: str, primary: bool) -> str:
    """Helper text for one unit of a split program: the primary defines the
    mutable state once, every other unit declares it ``extern``."""

    output: list[str] = []
    for unit in split_toplevel_units(source):
        if not is_mutable_state(unit):
            output.append(unit)
            continue
        definition = unit.lstrip()[len("static ") :]
        if primary:
            output.append(definition)
            continue
        declaration = definition.rstrip().rstrip(";")
        initializer = declaration.find("=")
        if initializer != -1:
            declaration = declaration[:initializer].rstrip()
        output.append(f"extern {declaration};")
    return "\n".join(output)
