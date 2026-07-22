"""Collection and validation of source-defined preprocessor symbols."""

from ...ast_nodes import PreprocessorDirective
from ...hosted_abi import hosted_owned_name
from ...source_macros import source_macro_name, source_symbol_directive, source_undef_name
from .c_names import c_file_scope_reserved_identifier, compiler_reserved_prefix


def collect_source_macros(declarations, context) -> tuple[set[str], dict[str, object]]:
    names: set[str] = set()
    definitions: dict[str, object] = {}
    for declaration in declarations:
        if not isinstance(declaration, PreprocessorDirective):
            continue
        name = source_macro_name(declaration.text)
        if name is not None:
            names.add(name)
            definitions[name] = source_symbol_directive(declaration.text)
            _validate_mutation(declaration, name, define=True, context=context)
            continue
        name = source_undef_name(declaration.text)
        if name is not None:
            definitions.pop(name, None)
            _validate_mutation(declaration, name, define=False, context=context)
    return names, definitions


def _validate_mutation(declaration, name, *, define, context) -> None:
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
    context.error(message, declaration.line, declaration.col)


__all__ = ["collect_source_macros"]
