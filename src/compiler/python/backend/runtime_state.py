"""Runtime helper C text split at top level, and its file-scope state shaped
for one translation unit of a split program.

The stdlib archive and ``--emit-units`` both need one definition of every
mutable runtime variable across several C files. The helpers are written as
plain ``static`` definitions; the unit that owns the state drops ``static``
and the others declare the same names ``extern`` without an initializer.

A module-unit program goes further: its runtime unit alone defines every
helper function and object with external linkage, and each group's unit
declares them, so the runtime is compiled once per build rather than once per
unit.
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


_LINKAGE_WORDS = ("static", "inline")


def _external(text: str) -> str:
    """``text`` without the leading ``static``/``inline`` specifiers that give a
    helper internal linkage; the remaining specifiers keep their order."""

    head = text.lstrip()
    words = head.split(" ")
    kept = 0
    while kept < len(words) and words[kept] in _LINKAGE_WORDS:
        kept += 1
    return " ".join(words[kept:])


def runtime_linkage(source: str, define: bool) -> str:
    """Helper text for a module-unit program. The runtime unit (``define``)
    gives every helper function and file-scope object external linkage; every
    other unit keeps the types and macros and declares the functions and
    objects instead of defining them."""

    output: list[str] = []
    for unit in split_toplevel_units(source):
        head = unit.lstrip()
        if head.startswith("#") or not head.startswith(("static ", "inline ")):
            output.append(unit)
            continue
        prototype = function_definition_prototype(unit)
        if prototype is not None:
            output.append(_external(unit if define else prototype))
            continue
        definition = _external(unit)
        if define:
            output.append(definition)
            continue
        declaration = definition.rstrip().rstrip(";")
        initializer = declaration.find("=")
        if initializer != -1:
            declaration = declaration[:initializer].rstrip()
        output.append(f"extern {declaration};")
    return "\n".join(output)
