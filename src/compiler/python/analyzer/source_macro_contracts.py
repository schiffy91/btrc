"""Semantic boundaries for function-like source macro invocations."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass

from ..ast_nodes import FieldAccessExpr, Identifier, LambdaExpr
from ..hosted_abi import (
    hosted_function,
    hosted_macro_reference_requires_semantic_call,
    hosted_parameter_is_read_only_borrow,
)
from ..source_macros import (
    source_macro_replacement_identifiers,
    source_macro_replacement_member_identifiers,
    source_macro_single_call,
    source_macro_unwrapped_identifier,
)
from ..type_identity import type_shape_key

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MANAGED_MACRO_BASES = frozenset({"string", "Mutex", "Thread", "Vector", "List", "Map", "Set", "Array"})


class SourceMacroContractsMixin:
    def _validate_source_macro_call(self, call) -> bool:
        if not isinstance(call.callee, Identifier):
            return False
        directive = getattr(self, "_source_macro_definitions", {}).get(
            call.callee.name,
        )
        if directive is None or not directive.function_like:
            return False
        macro_name = directive.name
        if any(call.arg_names or ()):
            self._error(
                f"Source macro '{macro_name}' does not accept named arguments",
                call.line,
                call.col,
            )
        read_only = _read_only_macro_parameters(directive)
        for index, argument in enumerate(call.args):
            if self._macro_argument_is_callable(argument):
                self._error(
                    f"Source macro '{macro_name}' cannot accept callable argument "
                    f"{index + 1} because macro expansion bypasses semantic call analysis",
                    getattr(argument, "line", call.line),
                    getattr(argument, "col", call.col),
                )
                continue
            if not self._macro_argument_requires_boundary(argument):
                continue
            parameter = directive.parameter_order[index] if index < len(directive.parameter_order) else None
            expected = read_only.get(parameter)
            if expected is not None and self._macro_read_only_argument_is_safe(expected, argument):
                continue
            self._error(
                f"Source macro '{macro_name}' cannot accept managed or opaque-borrow "
                f"argument {index + 1} because its expansion is not a proven read-only hosted call",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
        self._validate_source_macro_captures(directive, call)
        return True

    def _macro_argument_requires_boundary(self, argument) -> bool:
        return self._expression_is_opaque_borrow(argument) or _macro_type_requires_boundary(
            self,
            self._infer_type(argument),
            self._source_macro_type_parameters(),
        )

    def _source_macro_type_parameters(self):
        return frozenset(getattr(self.current_class, "generic_params", ()) or ()) | frozenset(
            getattr(self.current_callable, "generic_params", ()) or ()
        )

    def _macro_read_only_argument_is_safe(self, expected, argument) -> bool:
        if self._expression_produces_owned_result(argument):
            return False
        actual = self._infer_type(argument)
        return bool(
            actual is not None
            and (self._hosted_argument_type_is_deferred(expected, actual) or self._types_compatible(expected, actual))
        )

    def _macro_argument_is_callable(self, argument) -> bool:
        if self._function_pointer_signature(self._infer_type(argument)) is not None:
            return True
        for node in _walk_nodes(argument):
            if isinstance(node, LambdaExpr):
                return True
            if isinstance(node, Identifier):
                symbol = self.scope.lookup(node.name)
                if symbol is not None and self._function_pointer_signature(symbol.type) is not None:
                    return True
                if symbol is None and node.name in self.function_table:
                    return True
            if isinstance(node, FieldAccessExpr) and _field_is_language_method(self, node):
                return True
        return False

    def _validate_source_macro_captures(self, directive, call) -> None:
        definitions = getattr(self, "_source_macro_definitions", {})
        for name in _macro_free_identifiers(directive, definitions):
            symbol = self.scope.lookup(name)
            type_expr = symbol.type if symbol is not None else None
            if type_expr is None:
                declaration = getattr(self, "_global_declarations", {}).get(name)
                type_expr = getattr(declaration, "type", None)
            callable_value = self._function_pointer_signature(type_expr) is not None
            if not callable_value and not _macro_type_requires_boundary(
                self,
                type_expr,
                self._source_macro_type_parameters(),
            ):
                continue
            self._error(
                f"Source macro '{directive.name}' cannot capture managed or callable "
                f"value '{name}' because macro expansion bypasses semantic analysis",
                call.line,
                call.col,
            )


def validate_macro_replacement_language_symbol(
    analyzer,
    directive,
    symbol: str,
    declaration,
) -> None:
    """Reject source-language symbols whose C expansion is not transparent."""
    if symbol in analyzer.class_table or symbol in analyzer.interface_table:
        analyzer._error(
            f"Language type '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
            declaration.line,
            declaration.col,
        )
        return
    function = analyzer.function_table.get(symbol)
    if function is not None and function.body is not None:
        bare_alias = source_macro_unwrapped_identifier(directive.replacement) == symbol
        sensitive = any(
            _macro_type_requires_boundary(
                analyzer,
                type_expr,
                frozenset(getattr(function, "generic_params", ()) or ()),
            )
            for type_expr in (function.return_type, *(parameter.type for parameter in function.params))
        )
        if directive.function_like or bare_alias or sensitive:
            analyzer._error(
                f"Language callable '{symbol}' requires semantic call analysis and "
                f"cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )
        return
    if (
        directive.function_like
        and symbol in source_macro_replacement_member_identifiers(directive)
        and _language_method_named(analyzer, symbol)
    ):
        analyzer._error(
            f"Language method '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
            declaration.line,
            declaration.col,
        )
        return
    global_decl = getattr(analyzer, "_global_declarations", {}).get(symbol)
    if global_decl is not None and _macro_type_requires_boundary(analyzer, global_decl.type):
        analyzer._error(
            f"Managed source value '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
            declaration.line,
            declaration.col,
        )


def _read_only_macro_parameters(directive) -> dict[str, object]:
    direct_call = source_macro_single_call(directive)
    if direct_call is None:
        return {}
    callee, arguments = direct_call
    spec = hosted_function(callee)
    if (
        spec is None
        or spec.parameters is None
        or spec.variadic
        or hosted_macro_reference_requires_semantic_call(callee)
        or len(arguments) != len(spec.parameters)
    ):
        return {}
    result = {}
    for parameter in directive.parameter_order:
        occurrences = [index for index, argument in enumerate(arguments) if parameter in _IDENTIFIER.findall(argument)]
        if len(occurrences) != 1:
            continue
        index = occurrences[0]
        if source_macro_unwrapped_identifier(arguments[index]) == parameter and hosted_parameter_is_read_only_borrow(
            callee, index
        ):
            result[parameter] = spec.parameters[index].as_type_expr()
    return result


def _macro_type_requires_boundary(analyzer, type_expr, type_params=frozenset(), seen=frozenset()) -> bool:
    canonical = analyzer._canonical_type(type_expr)
    if canonical is None:
        return False
    key = type_shape_key(canonical)
    if key in seen:
        return False
    seen = seen | {key}
    if canonical.base in type_params or canonical.base in _MANAGED_MACRO_BASES:
        return True
    if canonical.base in analyzer.class_table or canonical.base in analyzer.interface_table:
        return True
    if analyzer._function_pointer_signature(canonical) is not None:
        return True
    if any(_macro_type_requires_boundary(analyzer, item, type_params, seen) for item in canonical.generic_args):
        return True
    name = canonical.base.removeprefix("struct ")
    structure = analyzer.struct_table.get(name)
    if structure is not None and not structure.is_forward:
        return any(_macro_type_requires_boundary(analyzer, field.type, type_params, seen) for field in structure.fields)
    rich_enum = analyzer.rich_enum_table.get(name)
    return bool(
        rich_enum
        and any(
            _macro_type_requires_boundary(analyzer, parameter.type, type_params, seen)
            for variant in rich_enum.variants
            for parameter in variant.params
        )
    )


def _language_method_named(analyzer, name: str) -> bool:
    return any(name in info.methods for info in analyzer.class_table.values()) or any(
        name in info.methods for info in analyzer.interface_table.values()
    )


def _field_is_language_method(analyzer, expression) -> bool:
    if isinstance(expression.obj, Identifier) and analyzer.scope.lookup(expression.obj.name) is None:
        info = analyzer.class_table.get(expression.obj.name)
        if info is not None and expression.field in info.methods:
            return True
    receiver = analyzer._canonical_type(analyzer._infer_type(expression.obj))
    info = analyzer.class_table.get(receiver.base) if receiver is not None else None
    return bool(info is not None and expression.field in info.methods)


def _macro_free_identifiers(directive, definitions, visiting=frozenset()) -> set[str]:
    if directive.name in visiting:
        return set()
    visiting = visiting | {directive.name}
    result = set()
    for name in source_macro_replacement_identifiers(directive):
        nested = definitions.get(name)
        if nested is not None:
            result.update(_macro_free_identifiers(nested, definitions, visiting))
        else:
            result.add(name)
    return result


def _walk_nodes(root):
    pending = [root]
    seen = set()
    while pending:
        node = pending.pop()
        if node is None or isinstance(node, (str, bytes, int, float, bool)):
            continue
        if isinstance(node, (list, tuple)):
            pending.extend(node)
            continue
        if not is_dataclass(node) or id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        pending.extend(getattr(node, field.name) for field in fields(node))


__all__ = ["SourceMacroContractsMixin", "validate_macro_replacement_language_symbol"]
