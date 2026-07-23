"""Fail-closed domains for types that become concrete C declarations."""

from ..numeric_semantics import is_known_integer_typedef_name
from ..qualifier_provenance import (
    effective_outer_const,
    effective_outer_volatile,
)
from .mutex_payload_domains import MutexPayloadDomainContractsMixin
from .thread_type_domains import ThreadTypeDomainContractsMixin

_RUNTIME_TYPE_BASES = frozenset(
    {
        "Array",
        "List",
        "Map",
        "Mutex",
        "Set",
        "Thread",
        "Tuple",
        "Vector",
        "__fn_ptr",
    }
)
_EXPLICIT_C_TAG_PREFIXES = ("struct ", "enum ", "union ")


class TypeDomainContractsMixin(
    MutexPayloadDomainContractsMixin,
    ThreadTypeDomainContractsMixin,
):
    def _validate_declared_type(
        self,
        type_expr,
        subject,
        line=0,
        col=0,
        *,
        role="object",
        active_type_params=(),
    ) -> None:
        if type_expr is None:
            return
        type_line = type_expr.line or line
        type_col = type_expr.col or col
        self._validate_storage_qualifiers(type_expr, subject, role, type_line, type_col)
        if role == "return" and (
            effective_outer_const(type_expr, self.declarations.typedef_table)
            or effective_outer_volatile(type_expr, self.declarations.typedef_table)
        ):
            self.context.error(
                f"{subject} cannot carry an outer const/volatile qualifier; C discards qualifiers on returned values",
                type_line,
                type_col,
            )
        self._validate_generic_arity(
            type_expr,
            type_expr.base in set(active_type_params),
        )
        if type_expr.is_array and type_expr.base in self.declarations.typedef_table:
            alias_target = self._canonical_type(
                self.declarations.typedef_table[type_expr.base],
            )
            if alias_target is not None and alias_target.is_array:
                self._report_type_shape_error(
                    "Nested array composition through typedef is not supported",
                    type_expr,
                    type_line,
                    type_col,
                )
        if type_expr.base in self.declarations.interface_table and type_expr.base not in set(active_type_params):
            self._report_type_shape_error(
                f"Interface type '{type_expr.base}' cannot be used as a runtime "
                "value; use an implementing concrete class",
                type_expr,
                type_line,
                type_col,
            )
        canonical = self._canonical_type(type_expr)
        if (
            canonical
            and canonical.base == "Mutex"
            and (canonical.pointer_depth > 0 or canonical.is_array or canonical.is_const)
        ):
            self.context.error(
                "Mutex<T> owner type must be one direct mutable handle; pointer, array, and const Mutex shapes are not supported",
                type_line,
                type_col,
            )
        if (
            canonical
            and canonical.base not in {"Mutex", "Thread", "__fn_ptr"}
            and canonical.base not in self.declarations.class_table
            and self._contains_mutex_storage(canonical)
        ):
            self.context.error(
                f"{subject} cannot embed a Mutex handle in shallow by-value storage; keep Mutex<T> as a direct managed value",
                type_line,
                type_col,
            )
        self._validate_mutex_payloads_in_type(
            type_expr,
            active_type_params=active_type_params,
            line=type_line,
            col=type_col,
        )
        if (
            canonical
            and canonical.base == "Thread"
            and (canonical.pointer_depth > 0 or canonical.is_array or canonical.is_const or canonical.is_nullable)
        ):
            self.context.error(
                "Thread<T> owner type must be one direct mutable handle; "
                "pointer, array, const, and nullable Thread shapes are not supported",
                type_line,
                type_col,
            )
        if role in {"field", "parameter"} and self._contains_thread_storage(type_expr):
            self.context.error(
                f"{subject} cannot own a Thread handle; keep each Thread<T> "
                "in one initialized local variable or return it",
                type_line,
                type_col,
            )
        if canonical and canonical.base == "Thread" and canonical.generic_args:
            result_type = canonical.generic_args[0]
            if self._thread_result_contains_unsized_array(result_type):
                self.context.error(
                    "Thread<T> result type cannot contain an unsized array; "
                    "return a managed collection or another explicitly owned value",
                    type_line,
                    type_col,
                )
            if self._contains_thread_storage(result_type):
                self.context.error(
                    "Thread<T> result type cannot contain another Thread handle",
                    type_line,
                    type_col,
                )
            if self._contains_mutex_storage(result_type):
                self.context.error(
                    "Thread<T> result type cannot contain a Mutex handle",
                    type_line,
                    type_col,
                )
            if not self._is_direct_managed_thread_result(
                result_type
            ) and self._thread_result_aggregate_contains_managed_reference(
                result_type,
            ):
                self.context.error(
                    "Thread<T> aggregate result type cannot contain string or "
                    "class references; return the managed value directly or use "
                    "a scalar-only aggregate",
                    type_line,
                    type_col,
                )
        if role not in {"alias", "return"} and self._is_nonpointer_void_object(canonical):
            self.context.error(
                f"{subject} cannot have scalar/non-pointer void type",
                type_line,
                type_col,
            )
        if not self._is_known_declaration_type(type_expr, active_type_params):
            self.context.error(
                f"{subject} uses unknown by-value type '{self._format_type(type_expr)}'",
                type_line,
                type_col,
            )

        arguments = type_expr.generic_args or []
        for index, argument in enumerate(arguments):
            result_slot = type_expr.base in {"__fn_ptr", "Thread"} and index == 0
            argument_role = "return" if result_slot else "object"
            self._validate_declared_type(
                argument,
                f"Generic argument {index + 1} of {subject}",
                type_line,
                type_col,
                role=argument_role,
                active_type_params=active_type_params,
            )

    def _is_known_declaration_type(self, type_expr, active_type_params=()) -> bool:
        base = type_expr.base
        if type_expr.pointer_depth > 0 and not type_expr.generic_args:
            return True
        if base in active_type_params:
            return True
        if base in self._NUMERIC_TYPES or base in {"bool", "string", "void"}:
            return True
        if base in _RUNTIME_TYPE_BASES:
            return True
        if base in self.declarations.class_table or base in self.declarations.interface_table:
            return True
        if base in self.declarations.enum_table or base in self.declarations.rich_enum_table:
            return True
        if base in self.declarations.struct_table or base in self.declarations.typedef_table:
            return True
        if base in self.declarations.declared_type_names:
            return True
        if base.endswith("_t") or is_known_integer_typedef_name(base):
            return True
        return base.startswith(_EXPLICIT_C_TAG_PREFIXES)

    def _is_nonpointer_void_object(self, type_expr) -> bool:
        return self.type_identity.is_scalar_void(type_expr)

    def _contains_thread_storage(self, type_expr) -> bool:
        """Whether a concrete value shape contains a uniquely owned handle."""
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.base == "Thread":
            return True
        arguments = canonical.generic_args or []
        # A function pointer's result is produced on invocation rather than
        # stored in the pointer value.  Its parameter domains remain relevant.
        if canonical.base == "__fn_ptr":
            arguments = arguments[1:]
        return any(self._contains_thread_storage(argument) for argument in arguments)

    def _validate_storage_qualifiers(self, type_expr, subject, role, line, col) -> None:
        if type_expr.is_static and type_expr.is_extern:
            self.context.error(f"{subject} cannot be both static and extern", line, col)
        if role in {"parameter", "field"} and (type_expr.is_static or type_expr.is_extern):
            self.context.error(
                f"{subject} cannot carry static/extern storage qualifiers",
                line,
                col,
            )


__all__ = ["TypeDomainContractsMixin"]
