"""Structured lowering for the supported ``#pragma pack`` contract."""

from __future__ import annotations

import re

from ...ast_nodes import ClassDecl, PreprocessorDirective, StructDecl
from .errors import CodegenError

_PUSH = re.compile(r"^#pragma\s+pack\s*\(\s*push\s*(?:,\s*(\d+)\s*)?\)\s*$")
_POP = re.compile(r"^#pragma\s+pack\s*\(\s*pop\s*\)\s*$")


def declaration_pack_alignments(program) -> dict[int, int]:
    """Map packed class/struct declarations to their active alignment."""
    stack: list[int | None] = []
    current: int | None = None
    result: dict[int, int] = {}
    for declaration in program.declarations:
        if isinstance(declaration, PreprocessorDirective):
            text = declaration.text.strip()
            push = _PUSH.fullmatch(text)
            if push:
                stack.append(current)
                if push.group(1) is not None:
                    alignment = int(push.group(1))
                    if alignment not in {1, 2, 4, 8, 16}:
                        raise CodegenError(f"unsupported #pragma pack alignment {alignment}")
                    current = alignment
                continue
            if _POP.fullmatch(text):
                if not stack:
                    raise CodegenError("#pragma pack(pop) has no matching push")
                current = stack.pop()
                continue
        if current is not None and isinstance(declaration, (ClassDecl, StructDecl)):
            result[id(declaration)] = current
    if stack:
        raise CodegenError("#pragma pack(push) has no matching pop")
    return result


def is_pack_pragma(text: str) -> bool:
    """Whether a source directive is represented by struct IR metadata."""
    stripped = text.strip()
    return bool(_PUSH.fullmatch(stripped) or _POP.fullmatch(stripped))
