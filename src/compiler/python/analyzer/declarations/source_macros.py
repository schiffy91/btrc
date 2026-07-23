"""Owned collection and validation of source-defined C macros."""

from ...ast_nodes import PreprocessorDirective
from ...hosted_abi import hosted_owned_name
from ...source_macros import SourceMacroNamespace, SourceSymbolDirective
from .c_names import c_file_scope_reserved_identifier, compiler_reserved_prefix


class SourceMacroDeclarations:
    """Build the analyzer's immutable macro namespace from source order."""

    def __init__(self, context) -> None:
        self.context = context

    def collect(self, declarations) -> SourceMacroNamespace:
        names: set[str] = set()
        definitions: dict[str, SourceSymbolDirective] = {}
        for declaration in declarations:
            if not isinstance(declaration, PreprocessorDirective):
                continue
            directive = SourceSymbolDirective.parse(declaration.text)
            if directive is None:
                continue
            name = directive.name
            if directive.operation == "define":
                names.add(name)
                definitions[name] = directive
                self._validate_mutation(declaration, name, define=True)
            else:
                definitions.pop(name, None)
                self._validate_mutation(declaration, name, define=False)
        return SourceMacroNamespace(names, definitions)

    def _validate_mutation(self, declaration, name: str, *, define: bool) -> None:
        prefix = compiler_reserved_prefix(name)
        if prefix is not None:
            message = (
                f"Macro name '{name}' uses the compiler-reserved '{prefix}' prefix"
                if define
                else f"Source #undef of compiler-owned C symbol '{name}' is not allowed"
            )
        elif c_file_scope_reserved_identifier(name):
            subject = "Macro name" if define else "Source #undef name"
            message = f"{subject} '{name}' is reserved by C11 at file scope"
        elif hosted_owned_name(name):
            action = "Macro name" if define else "Source #undef of"
            message = f"{action} compiler-owned hosted C symbol '{name}' is not allowed"
        else:
            return
        self.context.error(message, declaration.line, declaration.col)


__all__ = ["SourceMacroDeclarations"]
