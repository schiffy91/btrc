"""Source macro declarations, namespaces, and call contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, is_dataclass
from typing import TYPE_CHECKING

from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.program import DeclarationIndex
from src.compiler.python.syntax.ast.generated import FieldAccessExpr, Identifier, LambdaExpr
from src.compiler.python.syntax.tokens import SourceSymbolDirective

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.types import TypeSystem


_IDENTIFIER = re.compile("[A-Za-z_][A-Za-z0-9_]*")
_MANAGED_MACRO_BASES = frozenset({"string", "Mutex", "Thread", "Vector", "List", "Map", "Set", "Array"})


@dataclass(frozen=True)
class SourceMacroArgumentPlan:
    index: int
    argument: object
    callable_value: bool
    type_requires_boundary: bool
    read_only_type: object | None


@dataclass(frozen=True)
class SourceMacroCallPlan:
    name: str
    arguments: tuple[SourceMacroArgumentPlan, ...]


class SourceMacroAnalyzer:
    """Source macro declarations, namespaces, and call contracts."""

    def __init__(self, session: AnalysisSession, index: DeclarationIndex, types: TypeSystem) -> None:
        self.session = session
        self.index = index
        self.types = types

    def plan_call(self, call) -> SourceMacroCallPlan | None:
        if not isinstance(call.callee, Identifier):
            return None
        directive = self.index.source_macros.active(call.callee.name)
        if directive is None or not directive.function_like:
            return None
        if any(call.arg_names or ()):
            self.session.error(f"Source macro '{directive.name}' does not accept named arguments", call.line, call.col)
        if not directive.invalid_parameters and (not directive.accepts_arity(len(call.args))):
            expectation = f"at least {directive.minimum_arity}" if directive.variadic else str(directive.expected_arity)
            self.session.error(
                f"Source macro '{directive.name}' expects {expectation} argument(s) but got {len(call.args)}",
                call.line,
                call.col,
            )
        read_only = self._read_only_macro_parameters(directive)
        type_parameters = self._source_macro_type_parameters()
        arguments = tuple(
            SourceMacroArgumentPlan(
                index=index,
                argument=argument,
                callable_value=self._macro_argument_is_callable(argument),
                type_requires_boundary=self._macro_type_requires_boundary(self.type_of(argument), type_parameters),
                read_only_type=read_only.get(
                    directive.parameter_order[index] if index < len(directive.parameter_order) else None
                ),
            )
            for index, argument in enumerate(call.args)
        )
        self._validate_source_macro_captures(directive, call)
        return SourceMacroCallPlan(directive.name, arguments)

    def type_of(self, expression):
        """Read a type fact produced by ExpressionAnalyzer."""
        return self.session.node_types.get(id(expression))

    def _source_macro_type_parameters(self):
        return frozenset(getattr(self.session.current_class, "generic_params", ()) or ()) | frozenset(
            getattr(self.session.current_callable, "generic_params", ()) or ()
        )

    def _macro_argument_is_callable(self, argument) -> bool:
        if self.types.function_pointer_signature(self.type_of(argument)) is not None:
            return True
        for node in self._walk_macro_nodes(argument):
            if isinstance(node, LambdaExpr):
                return True
            if isinstance(node, Identifier):
                symbol = self.session.scope.lookup(node.name)
                if symbol is not None and self.types.function_pointer_signature(symbol.type) is not None:
                    return True
                if symbol is None and node.name in self.index.function_table:
                    return True
            if isinstance(node, FieldAccessExpr) and self._field_is_language_method(node):
                return True
        return False

    def _validate_source_macro_captures(self, directive, call) -> None:
        namespace = self.index.source_macros
        for name in self._macro_free_identifiers(directive, namespace):
            symbol = self.session.scope.lookup(name)
            type_expr = symbol.type if symbol is not None else None
            if type_expr is None:
                declaration = self.index.global_declarations.get(name)
                type_expr = getattr(declaration, "type", None)
            callable_value = self.types.function_pointer_signature(type_expr) is not None
            if not callable_value and (
                not self._macro_type_requires_boundary(type_expr, self._source_macro_type_parameters())
            ):
                continue
            self.session.error(
                f"Source macro '{directive.name}' cannot capture managed or callable value '{name}' because macro expansion bypasses semantic analysis",
                call.line,
                call.col,
            )

    def validate_replacement_language_symbol(self, directive, symbol: str, declaration) -> None:
        """Reject language symbols whose C replacement is not transparent."""
        if symbol in self.index.class_table or symbol in self.index.interface_table:
            self.session.error(
                f"Language type '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )
            return
        function = self.index.function_table.get(symbol)
        if function is not None and function.body is not None:
            bare_alias = SourceSymbolDirective.unwrapped_identifier(directive.replacement) == symbol
            type_params = frozenset(getattr(function, "generic_params", ()) or ())
            sensitive = any(
                self._macro_type_requires_boundary(type_expr, type_params)
                for type_expr in (function.return_type, *(parameter.type for parameter in function.params))
            )
            if directive.function_like or bare_alias or sensitive:
                self.session.error(
                    f"Language callable '{symbol}' requires semantic call analysis and cannot be referenced from macro replacement '{directive.name}'",
                    declaration.line,
                    declaration.col,
                )
            return
        if (
            directive.function_like
            and symbol in directive.replacement_member_identifiers()
            and self._language_method_named(symbol)
        ):
            self.session.error(
                f"Language method '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )
            return
        global_decl = self.index.global_declarations.get(symbol)
        if global_decl is not None and self._macro_type_requires_boundary(global_decl.type):
            self.session.error(
                f"Managed source value '{symbol}' cannot be referenced from macro replacement '{directive.name}'",
                declaration.line,
                declaration.col,
            )

    def _read_only_macro_parameters(self, directive) -> dict[str, object]:
        direct_call = directive.single_call()
        if direct_call is None:
            return {}
        callee, arguments = direct_call
        spec = HOSTED_ABI.function(callee)
        if (
            spec is None
            or spec.parameters is None
            or spec.variadic
            or HOSTED_ABI.macro_reference_requires_semantic_call(callee)
            or (len(arguments) != len(spec.parameters))
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
            ) == parameter and HOSTED_ABI.parameter_is_read_only_borrow(callee, index):
                result[parameter] = spec.parameters[index].as_type_expr()
        return result

    def _macro_type_requires_boundary(self, type_expr, type_params=frozenset(), seen=frozenset()) -> bool:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None:
            return False
        key = self.types.type_shape_key(canonical)
        if key in seen:
            return False
        seen = seen | {key}
        if canonical.base in type_params or canonical.base in _MANAGED_MACRO_BASES:
            return True
        if canonical.base in self.index.class_table or canonical.base in self.index.interface_table:
            return True
        if self.types.function_pointer_signature(canonical) is not None:
            return True
        if any(self._macro_type_requires_boundary(item, type_params, seen) for item in canonical.generic_args):
            return True
        name = canonical.base.removeprefix("struct ")
        structure = self.index.struct_table.get(name)
        if structure is not None and (not structure.is_forward):
            return any(self._macro_type_requires_boundary(field.type, type_params, seen) for field in structure.fields)
        rich_enum = self.index.rich_enum_table.get(name)
        return bool(
            rich_enum
            and any(
                self._macro_type_requires_boundary(parameter.type, type_params, seen)
                for variant in rich_enum.variants
                for parameter in variant.params
            )
        )

    def _language_method_named(self, name: str) -> bool:
        return any(name in info.methods for info in self.index.class_table.values()) or any(
            name in info.methods for info in self.index.interface_table.values()
        )

    def _field_is_language_method(self, expression) -> bool:
        if isinstance(expression.obj, Identifier) and self.session.scope.lookup(expression.obj.name) is None:
            info = self.index.class_table.get(expression.obj.name)
            if info is not None and expression.field in info.methods:
                return True
        receiver = self.types.canonical_type(self.type_of(expression.obj))
        info = self.index.class_table.get(receiver.base) if receiver is not None else None
        return bool(info is not None and expression.field in info.methods)

    def _macro_free_identifiers(self, directive, namespace, visiting=frozenset()) -> set[str]:
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


__all__ = ["SourceMacroAnalyzer"]
