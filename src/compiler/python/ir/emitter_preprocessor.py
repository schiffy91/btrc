"""Formatting for structured preprocessor declarations."""

from .nodes import IRInclude, IRMacroDef, IRModule


class _PreprocessorEmitterMixin:
    @staticmethod
    def _include_text(include: IRInclude) -> str:
        if include.is_system:
            return f"#include <{include.header}>"
        return f'#include "{include.header}"'

    @staticmethod
    def _macro_text(macro: IRMacroDef) -> str:
        params = "" if macro.params is None else f"({', '.join(macro.params)})"
        replacement = f" {macro.replacement}" if macro.replacement else ""
        return f"#define {macro.name}{params}{replacement}"

    def _preprocessor_text(self, declaration: IRInclude | IRMacroDef) -> str:
        if isinstance(declaration, IRInclude):
            return self._include_text(declaration)
        return self._macro_text(declaration)

    def _emit_preprocessor_declarations(self, module: IRModule) -> None:
        for declaration in module.preprocessor_decls:
            self._line(self._preprocessor_text(declaration))
        if module.preprocessor_decls:
            self._line("")
