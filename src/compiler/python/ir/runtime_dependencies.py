"""Materialize freestanding runtime dependencies from structured IR."""

from __future__ import annotations

import re

from .expr_nodes import CType, IRCall, IRLiteral, IRVar
from .module import IRModule
from .optimizer_walk import IRTree
from .top_nodes import IRInclude, IRMacroDef

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


class RuntimeDependencyMaterializer:
    """Own runtime-feature derivation for one mutable IR module."""

    def __init__(self, module: IRModule):
        self._module = module

    def refresh(self) -> None:
        """Recompute and materialize the live freestanding runtime seam."""

        self._remove_generated_preprocessor()
        self._lower_freestanding_system_includes()
        self._module.needs_runtime = bool(
            self._module.runtime_roots or self._module.helper_decls or self._has_structured_runtime_use()
        )
        if not self._module.freestanding:
            return

        generated_features: list[IRMacroDef] = []
        required_headers = {header for helper in self._module.helper_decls for header in helper.required_headers}
        required_features = self._structured_runtime_features()
        for header, feature in _HEADER_FEATURES.items():
            if header in required_headers:
                required_features.add(feature)
        for feature in sorted(required_features):
            if not any(
                isinstance(declaration, IRMacroDef) and declaration.name == feature
                for declaration in self._module.preprocessor_decls
            ):
                generated_features.append(IRMacroDef(name=feature, replacement="1"))

        has_runtime_seam = any(
            isinstance(declaration, IRInclude) and not declaration.is_system and declaration.header == "btrc_rt.h"
            for declaration in self._module.preprocessor_decls
        )
        generated: list[IRInclude | IRMacroDef] = list(generated_features)
        if has_runtime_seam:
            seam_index = next(
                index
                for index, declaration in enumerate(self._module.preprocessor_decls)
                if (
                    isinstance(declaration, IRInclude)
                    and not declaration.is_system
                    and declaration.header == "btrc_rt.h"
                )
            )
            self._module.preprocessor_decls[seam_index:seam_index] = generated_features
        elif self._module.needs_runtime:
            seam = IRInclude(header="btrc_rt.h", is_system=False)
            generated.append(seam)
            self._module.preprocessor_decls.extend(generated)

        self._module._generated_runtime_preprocessor.extend(generated)

    def _remove_generated_preprocessor(self) -> None:
        generated = self._module._generated_runtime_preprocessor
        if not generated:
            return
        generated_ids = {id(declaration) for declaration in generated}
        self._module.preprocessor_decls = [
            declaration for declaration in self._module.preprocessor_decls if id(declaration) not in generated_ids
        ]
        generated.clear()

    def _lower_freestanding_system_includes(self) -> None:
        """Replace source system headers once with one local runtime seam."""

        if not self._module.freestanding or self._module._freestanding_system_includes_lowered:
            return
        lowered = []
        emitted_seam = False
        for declaration in self._module.preprocessor_decls:
            if not isinstance(declaration, IRInclude) or not declaration.is_system:
                lowered.append(declaration)
            elif not emitted_seam:
                lowered.append(IRInclude(header="btrc_rt.h", is_system=False))
                emitted_seam = True
        self._module.preprocessor_decls = lowered
        self._module._freestanding_system_includes_lowered = True

    def _has_structured_runtime_use(self) -> bool:
        defined_functions = {function.name for function in self._module.function_defs}
        defined_globals = {declaration.name for declaration in self._module.global_decls}
        for node in IRTree(self._module):
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

    def _structured_runtime_features(self) -> set[str]:
        """Return feature macros reached by typed native-runtime calls."""

        defined_functions = {function.name for function in self._module.function_defs}
        features: set[str] = set()
        for node in IRTree(self._module):
            if not isinstance(node, IRCall) or not isinstance(node.callee, str) or node.callee in defined_functions:
                continue
            for prefix, feature in _RUNTIME_CALL_FEATURES.items():
                if node.callee.startswith(prefix):
                    features.add(feature)
                    break
        return features


__all__ = ["RuntimeDependencyMaterializer"]
