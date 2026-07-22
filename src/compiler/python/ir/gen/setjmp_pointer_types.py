"""Pointer shape and pointee constness for setjmp call summaries."""

from dataclasses import dataclass

_TYPE_QUALIFIERS = frozenset({"const", "volatile"})
OPAQUE_POINTER_DEPTH = -1


def _alias_name(c_type: object, aliases: set[str] | frozenset[str]) -> str | None:
    """Return an unadorned typedef name from one rendered C type."""

    text = str(c_type).strip()
    if "*" in text or any(character in text for character in "[]()"):
        return None
    words = [word for word in text.split() if word not in _TYPE_QUALIFIERS]
    return words[0] if len(words) == 1 and words[0] in aliases else None


def _pointer_base_alias(c_type: object, aliases: set[str] | frozenset[str]) -> str | None:
    text = str(c_type).replace("*", " ")
    words = [word for word in text.split() if word not in _TYPE_QUALIFIERS]
    return words[0] if len(words) == 1 and words[0] in aliases else None


def _pointer_stars(c_type: object) -> int:
    return str(c_type).count("*")


@dataclass(frozen=True)
class PointerTypeFacts:
    aliases: frozenset[str]
    read_only_pointee_aliases: frozenset[str]
    alias_depths: dict[str, int]
    void_aliases: frozenset[str]

    def is_pointer(self, c_type: object) -> bool:
        return self.pointer_depth(c_type) != 0

    def pointer_depth(self, c_type: object) -> int:
        stars = _pointer_stars(c_type)
        alias = _alias_name(c_type, self.aliases)
        if stars == 0 and alias is not None and alias in self.alias_depths:
            return self.alias_depths[alias]
        pointer_base = _pointer_base_alias(c_type, self.aliases)
        if pointer_base is not None and pointer_base in self.alias_depths:
            stars += self.alias_depths[pointer_base]
        if stars == 0 and alias is not None:
            return OPAQUE_POINTER_DEPTH
        return stars

    def has_read_only_pointee(self, c_type: object) -> bool:
        text = str(c_type).strip()
        alias = _alias_name(text, self.aliases)
        if alias is not None:
            return alias in self.read_only_pointee_aliases
        # A single direct pointer makes leading `const` a complete read-only
        # contract. Layered pointers remain conservative because a deeper
        # mutable object can still be reached through the intermediate slot.
        return (
            text.startswith("const ") and _pointer_stars(text) == 1 and _pointer_base_alias(text, self.aliases) is None
        )

    def is_void(self, c_type: object) -> bool:
        text = str(c_type).strip()
        if "*" in text or any(character in text for character in "[]()"):
            return False
        words = [word for word in text.split() if word not in _TYPE_QUALIFIERS]
        return words == ["void"] or (len(words) == 1 and words[0] in self.void_aliases)


def pointer_type_facts(module) -> PointerTypeFacts:
    """Resolve pointer shape and pointee constness through typedef chains."""

    definitions = {declaration.name: declaration for declaration in module.typedef_defs}
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, declaration in definitions.items():
            target = str(declaration.target_type).strip()
            inherited = _alias_name(target, set(definitions))
            is_pointer = "*" in target or inherited in aliases
            if is_pointer and name not in aliases:
                aliases.add(name)
                changed = True

    depths: dict[str, int] = {}
    changed = True
    while changed:
        changed = False
        for name, declaration in definitions.items():
            target = str(declaration.target_type).strip()
            stars = _pointer_stars(target)
            inherited = _alias_name(target, set(definitions))
            pointer_base = _pointer_base_alias(target, set(definitions))
            ready = stars > 0
            depth = stars
            if stars == 0 and inherited is not None and inherited in depths:
                ready = True
                depth = depths[inherited]
            elif stars > 0 and pointer_base in aliases:
                ready = pointer_base in depths
                if ready:
                    depth += depths[pointer_base]
            if ready and name not in depths:
                depths[name] = depth
                changed = True

    # Pointee constness depends on the complete pointer-alias closure. Keeping
    # this as a second fixed point makes the result independent of raw IR list
    # order (the declaration planner may legally reorder dependent typedefs).
    read_only: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, declaration in definitions.items():
            target = str(declaration.target_type).strip()
            inherited = _alias_name(target, set(definitions))
            pointer_base = _pointer_base_alias(target, set(definitions))
            is_read_only = (
                inherited in read_only
                if "*" not in target
                else target.startswith("const ") and target.count("*") == 1 and pointer_base not in aliases
            )
            if is_read_only and name not in read_only:
                read_only.add(name)
                changed = True

    void_aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, declaration in definitions.items():
            target = str(declaration.target_type).strip()
            inherited = _alias_name(target, set(definitions))
            words = [word for word in target.split() if word not in _TYPE_QUALIFIERS]
            if (words == ["void"] or inherited in void_aliases) and name not in void_aliases:
                void_aliases.add(name)
                changed = True
    return PointerTypeFacts(
        aliases=frozenset(aliases),
        read_only_pointee_aliases=frozenset(read_only),
        alias_depths=depths,
        void_aliases=frozenset(void_aliases),
    )


__all__ = ["OPAQUE_POINTER_DEPTH", "PointerTypeFacts", "pointer_type_facts"]
