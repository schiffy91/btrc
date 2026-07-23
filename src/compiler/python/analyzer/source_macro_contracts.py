"""Owned semantic boundaries for function-like source macro invocations."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass

from ..ast_nodes import FieldAccessExpr, Identifier, LambdaExpr
from ..hosted_abi import (
    hosted_function,
    hosted_macro_reference_requires_semantic_call,
    hosted_parameter_is_read_only_borrow,
)
from ..source_macros import SourceSymbolDirective

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MANAGED_MACRO_BASES = frozenset(
    {"string", "Mutex", "Thread", "Vector", "List", "Map", "Set", "Array"},
)


class SourceMacroContractsMixin:
    """Own semantic checks at the source-preprocessor boundary."""

    def _validate_source_macro_call(self, call) -> bool:
        if not isinstance(call.callee, Identifier):
            return False
        directive = self.declarations.source_macros.active(call.callee.name)
        if directive is None or not directive.function_like:
            return False
        macro_name = directive.name
        if any(call.arg_names or ()):
            self.context.error(
                f"Source macro '{macro_name}' does not accept named arguments",
                call.line,
                call.col,
            )
        if not directive.invalid_parameters and not directive.accepts_arity(len(call.args)):
            expectation = f"at least {directive.minimum_arity}" if directive.variadic else str(directive.expected_arity)
            self.context.error(
                f"Source macro '{macro_name}' expects {expectation} argument(s) but got {len(call.args)}",
                call.line,
                call.col,
            )
        read_only = self._read_only_macro_parameters(directive)
        for index, argument in enumerate(call.args):
            if self._macro_argument_is_callable(argument):
                self.context.error(
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
            self.context.error(
                f"Source macro '{macro_name}' cannot accept managed or opaque-borrow "
                f"argument {index + 1} because its expansion is not a proven read-only hosted call",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
        self._validate_source_macro_captures(directive, call)
        return True

    def _macro_argument_requires_boundary(self, argument) -> bool:
        return self._expression_is_opaque_borrow(argument) or self._macro_type_requires_boundary(
            self._infer_type(argument),
            self._source_macro_type_parameters(),
        )

    def _source_macro_type_parameters(self):
        return frozenset(getattr(self.current_class, "generic_params", ()) or ()) | frozenset(
            getattr(self.current_callable, "generic_params", ()) or (),
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
        for node in self._walk_macro_nodes(argument):
            if isinstance(node, LambdaExpr):
                return True
            if isinstance(node, Identifier):
                symbol = self.scope.lookup(node.name)
                if symbol is not None and self._function_pointer_signature(symbol.type) is not None:
                    return True
                if symbol is None and node.name in self.declarations.function_table:
                    return True
            if isinstance(node, FieldAccessExpr) and self._field_is_language_method(node):
                return True
        return False

    def _validate_source_macro_captures(self, directive, call) -> None:
        namespace = self.declarations.source_macros
        for name in self._macro_free_identifiers(directive, namespace):
            symbol = self.scope.lookup(name)
            type_expr = symbol.type if symbol is not None else None
            if type_expr is None:
                declaration = self.declarations.global_declarations.get(name)
                type_expr = getattr(declaration, "type", None)
            callable_value = self._function_pointer_signature(type_expr) is not None
            if not callable_value and not self._macro_type_requires_boundary(
                type_expr,
                self._source_macro_type_parameters(),
            ):
                continue
            self.context.error(
                f"Source macro '{directive.name}' cannot capture managed or callable "
                f"value '{name}' because macro expansion bypasses semantic analysis",
                call.line,
                call.col,
            )

    def _validate_macro_replacement_language_symbol(
        self,
        directive,
        symbol: str,
        declaration,
    ) -> None:
        """Reject language symbols whose C replacement is not transparent."""
        if symbol in self.declarations.class_table or symbol in self.declarations.interface_table:
            self.context.error(
                f"Language type '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )
            return
        function = self.declarations.function_table.get(symbol)
        if function is not None and function.body is not None:
            bare_alias = SourceSymbolDirective.unwrapped_identifier(directive.replacement) == symbol
            type_params = frozenset(getattr(function, "generic_params", ()) or ())
            sensitive = any(
                self._macro_type_requires_boundary(type_expr, type_params)
                for type_expr in (
                    function.return_type,
                    *(parameter.type for parameter in function.params),
                )
            )
            if directive.function_like or bare_alias or sensitive:
                self.context.error(
                    f"Language callable '{symbol}' requires semantic call analysis and "
                    f"cannot be referenced from macro replacement '{directive.name}'",
                    declaration.line,
                    declaration.col,
                )
            return
        if (
            directive.function_like
            and symbol in directive.replacement_member_identifiers()
            and self._language_method_named(symbol)
        ):
            self.context.error(
                f"Language method '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )
            return
        global_decl = self.declarations.global_declarations.get(symbol)
        if global_decl is not None and self._macro_type_requires_boundary(global_decl.type):
            self.context.error(
                f"Managed source value '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )

    def _read_only_macro_parameters(self, directive) -> dict[str, object]:
        direct_call = directive.single_call()
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
            occurrences = [
                index for index, argument in enumerate(arguments) if parameter in _IDENTIFIER.findall(argument)
            ]
            if len(occurrences) != 1:
                continue
            index = occurrences[0]
            if SourceSymbolDirective.unwrapped_identifier(
                arguments[index]
            ) == parameter and hosted_parameter_is_read_only_borrow(callee, index):
                result[parameter] = spec.parameters[index].as_type_expr()
        return result

    def _macro_type_requires_boundary(
        self,
        type_expr,
        type_params=frozenset(),
        seen=frozenset(),
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return False
        key = self.type_identity.shape_key(canonical)
        if key in seen:
            return False
        seen = seen | {key}
        if canonical.base in type_params or canonical.base in _MANAGED_MACRO_BASES:
            return True
        if canonical.base in self.declarations.class_table or canonical.base in self.declarations.interface_table:
            return True
        if self._function_pointer_signature(canonical) is not None:
            return True
        if any(self._macro_type_requires_boundary(item, type_params, seen) for item in canonical.generic_args):
            return True
        name = canonical.base.removeprefix("struct ")
        structure = self.declarations.struct_table.get(name)
        if structure is not None and not structure.is_forward:
            return any(self._macro_type_requires_boundary(field.type, type_params, seen) for field in structure.fields)
        rich_enum = self.declarations.rich_enum_table.get(name)
        return bool(
            rich_enum
            and any(
                self._macro_type_requires_boundary(parameter.type, type_params, seen)
                for variant in rich_enum.variants
                for parameter in variant.params
            )
        )

    def _language_method_named(self, name: str) -> bool:
        return any(name in info.methods for info in self.declarations.class_table.values()) or any(
            name in info.methods for info in self.declarations.interface_table.values()
        )

    def _field_is_language_method(self, expression) -> bool:
        if isinstance(expression.obj, Identifier) and self.scope.lookup(expression.obj.name) is None:
            info = self.declarations.class_table.get(expression.obj.name)
            if info is not None and expression.field in info.methods:
                return True
        receiver = self._canonical_type(self._infer_type(expression.obj))
        info = self.declarations.class_table.get(receiver.base) if receiver is not None else None
        return bool(info is not None and expression.field in info.methods)

    def _macro_free_identifiers(
        self,
        directive,
        namespace,
        visiting=frozenset(),
    ) -> set[str]:
        if directive.name in visiting:
            return set()
        visiting = visiting | {directive.name}
        result = set()
        for name in directive.replacement_identifiers():
            nested = namespace.active(name)
            if nested is not None:
                result.update(self._macro_free_identifiers(nested, namespace, visiting))
            else:
                result.add(name)
        return result

    @staticmethod
    def _walk_macro_nodes(root):
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


__all__ = ["SourceMacroContractsMixin"]
