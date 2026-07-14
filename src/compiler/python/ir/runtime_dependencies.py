"""Materialize freestanding runtime dependencies from structured IR."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .expr_nodes import CType, IRCall, IRLiteral, IRVar
from .optimizer_walk import iter_ir_nodes
from .top_nodes import IRInclude, IRMacroDef

if TYPE_CHECKING:
    from .module import IRModule


_C_RUNTIME_CALLS = frozenset(
    {
        "abort",
        "calloc",
        "ceil",
        "clock_gettime",
        "exit",
        "fabs",
        "floor",
        "fmod",
        "fprintf",
        "free",
        "isalpha",
        "isdigit",
        "isspace",
        "longjmp",
        "malloc",
        "memcmp",
        "memcpy",
        "memmove",
        "memset",
        "nanosleep",
        "pow",
        "printf",
        "qsort",
        "realloc",
        "round",
        "setjmp",
        "sin",
        "snprintf",
        "sqrt",
        "strchr",
        "strcmp",
        "strcpy",
        "strlen",
        "strncmp",
        "strncpy",
        "strstr",
        "strtod",
        "strtof",
        "tolower",
        "toupper",
    }
)
_RUNTIME_CALL_FEATURES = {
    "btrc_gpu_": "BTRC_RT_NEEDS_GPU",
    "btrc_gui_": "BTRC_RT_NEEDS_GUI",
    "btrc_tray_": "BTRC_RT_NEEDS_TRAY",
    "pthread_": "BTRC_RT_NEEDS_PTHREAD",
}
_C_RUNTIME_CALL_PREFIXES = tuple(_RUNTIME_CALL_FEATURES)
_C_RUNTIME_OBJECTS = frozenset({"errno", "stderr", "stdin", "stdout"})
_C_RUNTIME_TYPES = frozenset(
    {
        "bool",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "intptr_t",
        "max_align_t",
        "ptrdiff_t",
        "size_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "uintptr_t",
    }
)
_C_RUNTIME_LITERALS = frozenset(
    {
        "CHAR_BIT",
        "CHAR_MAX",
        "CHAR_MIN",
        "INT_MAX",
        "INT_MIN",
        "LLONG_MAX",
        "LLONG_MIN",
        "LONG_MAX",
        "LONG_MIN",
        "NULL",
        "SCHAR_MAX",
        "SCHAR_MIN",
        "SHRT_MAX",
        "SHRT_MIN",
        "SIZE_MAX",
        "UCHAR_MAX",
        "UINT_MAX",
        "ULLONG_MAX",
        "ULONG_MAX",
        "USHRT_MAX",
        "false",
        "true",
    }
)
_C_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEADER_FEATURES = {
    "pthread.h": "BTRC_RT_NEEDS_PTHREAD",
    "setjmp.h": "BTRC_RT_NEEDS_SETJMP",
}


def refresh_runtime_dependencies(module: IRModule) -> None:
    """Recompute whether a live freestanding module needs ``btrc_rt.h``.

    Dependencies are derived from surviving helpers, typed calls, C types,
    literal macros, and runtime objects. Re-running this after DCE removes
    features owned only by dead code. Freestanding preprocessor lowering also
    happens here, so the C emitter only formats typed declarations.
    """

    _remove_generated_preprocessor(module)
    _lower_freestanding_system_includes(module)
    module.needs_runtime = bool(module.runtime_roots or module.helper_decls or _structured_runtime_use(module))
    if not module.freestanding:
        return

    generated_features: list[IRMacroDef] = []
    required_headers = {header for helper in module.helper_decls for header in helper.required_headers}
    required_features = _structured_runtime_features(module)
    for header, feature in _HEADER_FEATURES.items():
        if header in required_headers:
            required_features.add(feature)
    for feature in sorted(required_features):
        if not any(
            isinstance(declaration, IRMacroDef) and declaration.name == feature
            for declaration in module.preprocessor_decls
        ):
            generated_features.append(IRMacroDef(name=feature, replacement="1"))

    has_runtime_seam = any(
        isinstance(declaration, IRInclude) and not declaration.is_system and declaration.header == "btrc_rt.h"
        for declaration in module.preprocessor_decls
    )
    generated: list[IRInclude | IRMacroDef] = list(generated_features)
    if has_runtime_seam:
        seam_index = next(
            index
            for index, declaration in enumerate(module.preprocessor_decls)
            if isinstance(declaration, IRInclude) and not declaration.is_system and declaration.header == "btrc_rt.h"
        )
        module.preprocessor_decls[seam_index:seam_index] = generated_features
    elif module.needs_runtime:
        seam = IRInclude(header="btrc_rt.h", is_system=False)
        generated.append(seam)
        module.preprocessor_decls.extend(generated)

    module._generated_runtime_preprocessor.extend(generated)


def _remove_generated_preprocessor(module: IRModule) -> None:
    if not module._generated_runtime_preprocessor:
        return
    generated_ids = {id(declaration) for declaration in module._generated_runtime_preprocessor}
    module.preprocessor_decls = [
        declaration for declaration in module.preprocessor_decls if id(declaration) not in generated_ids
    ]
    module._generated_runtime_preprocessor.clear()


def _lower_freestanding_system_includes(module: IRModule) -> None:
    """Replace source system headers once with one typed local runtime seam."""

    if not module.freestanding or module._freestanding_system_includes_lowered:
        return
    lowered = []
    emitted_seam = False
    for declaration in module.preprocessor_decls:
        if not isinstance(declaration, IRInclude) or not declaration.is_system:
            lowered.append(declaration)
        elif not emitted_seam:
            lowered.append(IRInclude(header="btrc_rt.h", is_system=False))
            emitted_seam = True
    module.preprocessor_decls = lowered
    module._freestanding_system_includes_lowered = True


def _structured_runtime_use(module: IRModule) -> bool:
    defined_functions = {function.name for function in module.function_defs}
    defined_globals = {declaration.name for declaration in module.global_decls}

    for node in iter_ir_nodes(module):
        if isinstance(node, IRCall) and isinstance(node.callee, str):
            if node.callee not in defined_functions and (
                node.callee in _C_RUNTIME_CALLS or node.callee.startswith(_C_RUNTIME_CALL_PREFIXES)
            ):
                return True
        elif isinstance(node, CType):
            if _C_RUNTIME_TYPES.intersection(_C_IDENTIFIER.findall(node.text)):
                return True
        elif isinstance(node, IRLiteral):
            if node.text in _C_RUNTIME_LITERALS:
                return True
        elif isinstance(node, IRVar):
            if node.name not in defined_globals and node.name in _C_RUNTIME_OBJECTS:
                return True
    return False


def _structured_runtime_features(module: IRModule) -> set[str]:
    """Return native-runtime feature macros reached by typed external calls."""

    defined_functions = {function.name for function in module.function_defs}
    features: set[str] = set()
    for node in iter_ir_nodes(module):
        if not isinstance(node, IRCall) or not isinstance(node.callee, str):
            continue
        if node.callee in defined_functions:
            continue
        for prefix, feature in _RUNTIME_CALL_FEATURES.items():
            if node.callee.startswith(prefix):
                features.add(feature)
                break
    return features


__all__ = ["refresh_runtime_dependencies"]
