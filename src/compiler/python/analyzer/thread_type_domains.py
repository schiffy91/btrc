"""Recursive result-shape contracts for uniquely owned ``Thread<T>``."""

from __future__ import annotations

from ..type_identity import is_semantic_scalar_string


class ThreadTypeDomainContractsMixin:
    def _contains_mutex_storage(
        self,
        type_expr,
        visiting=frozenset(),
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.base == "Mutex":
            return True
        arguments = canonical.generic_args or []
        if canonical.base == "__fn_ptr":
            arguments = arguments[1:]
        if any(self._contains_mutex_storage(argument, visiting) for argument in arguments):
            return True
        if canonical.pointer_depth > 0:
            return False
        return self._aggregate_fields_match(
            canonical,
            visiting,
            self._contains_mutex_storage,
        )

    def _thread_result_contains_unsized_array(
        self,
        type_expr,
        visiting=frozenset(),
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.is_array:
            if canonical.array_size is None:
                return True
            from ..type_composition import strip_outer_storage

            canonical = strip_outer_storage(canonical, array=True)
        if canonical.pointer_depth > 0:
            return False
        if canonical.base == "Tuple":
            return any(
                self._thread_result_contains_unsized_array(argument, visiting) for argument in canonical.generic_args
            )
        return self._aggregate_fields_match(
            canonical,
            visiting,
            self._thread_result_contains_unsized_array,
        )

    def _is_direct_managed_thread_result(self, type_expr) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None or canonical.is_array:
            return False
        scalar_string = is_semantic_scalar_string(canonical)
        class_reference = canonical.base in self.declarations.class_table and canonical.pointer_depth <= 1
        return scalar_string or class_reference

    def _thread_result_aggregate_contains_managed_reference(
        self,
        type_expr,
        visiting=frozenset(),
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.is_array:
            from ..type_composition import strip_outer_storage

            return self._thread_result_aggregate_contains_managed_reference(
                strip_outer_storage(canonical, array=True),
                visiting,
            )
        if self._is_direct_managed_thread_result(canonical):
            return True
        if canonical.pointer_depth > 0:
            return False
        if canonical.base == "Tuple":
            return any(
                self._thread_result_aggregate_contains_managed_reference(
                    argument,
                    visiting,
                )
                for argument in canonical.generic_args
            )
        return self._aggregate_fields_match(
            canonical,
            visiting,
            self._thread_result_aggregate_contains_managed_reference,
        )

    def _aggregate_fields_match(
        self,
        canonical,
        visiting,
        predicate,
    ) -> bool:
        name = canonical.base.removeprefix("struct ")
        kind = "struct" if name in self.declarations.struct_table else "rich-enum"
        visit_key = f"{kind}:{name}"
        if visit_key in visiting:
            return False
        nested_visiting = visiting | {visit_key}
        declaration = self.declarations.struct_table.get(name)
        if declaration and not declaration.is_forward:
            return any(predicate(field.type, nested_visiting) for field in declaration.fields)
        rich_enum = self.declarations.rich_enum_table.get(name)
        if rich_enum:
            return any(
                predicate(parameter.type, nested_visiting)
                for variant in rich_enum.variants
                for parameter in variant.params
            )
        return False


__all__ = ["ThreadTypeDomainContractsMixin"]
