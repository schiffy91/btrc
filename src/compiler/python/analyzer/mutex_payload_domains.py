"""Ownership-shape contracts for values copied through ``Mutex<T>``."""

from __future__ import annotations

from dataclasses import replace

from ..type_identity import is_semantic_scalar_string

_RUNTIME_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})


class MutexPayloadDomainContractsMixin:
    def _validate_mutex_payloads_in_type(
        self,
        type_expr,
        *,
        active_type_params=(),
        line=0,
        col=0,
    ) -> bool:
        """Validate every concrete Mutex payload nested in ``type_expr``."""
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return True
        valid = True
        if canonical.base == "Mutex" and len(canonical.generic_args or []) == 1:
            problem = self._mutex_payload_problem(
                canonical.generic_args[0],
                frozenset(active_type_params),
            )
            if problem is not None:
                self._report_type_shape_error(
                    f"Mutex<T> payload type {problem}",
                    canonical,
                    line,
                    col,
                )
                valid = False
        for argument in canonical.generic_args or []:
            if not self._validate_mutex_payloads_in_type(
                argument,
                active_type_params=active_type_params,
                line=line,
                col=col,
            ):
                valid = False
        return valid

    def _mutex_payload_problem(self, payload, active_type_params):
        visiting = frozenset()
        if self._mutex_payload_contains_handle(
            payload,
            "Thread",
            active_type_params,
            visiting,
        ):
            return "cannot contain a Thread handle"
        if self._mutex_payload_contains_handle(
            payload,
            "Mutex",
            active_type_params,
            visiting,
        ):
            return "cannot contain a Mutex handle"
        if self._mutex_payload_contains_array(
            payload,
            active_type_params,
            visiting,
        ):
            return "cannot contain array storage"
        collection = self._unregistered_mutex_collection(
            payload,
            active_type_params,
            visiting,
        )
        if collection is not None:
            return (
                "cannot contain runtime-owned collection storage without a "
                f"registered managed class declaration ('{collection}')"
            )
        canonical = self._canonical_type(payload)
        if not self._is_direct_mutex_managed_value(canonical) and self._mutex_payload_has_managed_reference(
            canonical,
            active_type_params,
            visiting,
        ):
            return "aggregate cannot contain string or class references"
        return None

    def _mutex_payload_contains_handle(
        self,
        type_expr,
        handle,
        active_type_params,
        visiting,
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return False
        if canonical.base == handle:
            return True
        if canonical.base == "__fn_ptr":
            return False
        if any(
            self._mutex_payload_contains_handle(
                argument,
                handle,
                active_type_params,
                visiting,
            )
            for argument in canonical.generic_args or []
        ):
            return True
        return self._mutex_aggregate_fields_match(
            canonical,
            active_type_params,
            visiting,
            lambda field, nested: self._mutex_payload_contains_handle(
                field,
                handle,
                active_type_params,
                nested,
            ),
        )

    def _mutex_payload_contains_array(
        self,
        type_expr,
        active_type_params,
        visiting,
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return False
        if canonical.is_array:
            return True
        if canonical.base == "__fn_ptr":
            return False
        if any(
            self._mutex_payload_contains_array(argument, active_type_params, visiting)
            for argument in canonical.generic_args or []
        ):
            return True
        return self._mutex_aggregate_fields_match(
            canonical,
            active_type_params,
            visiting,
            lambda field, nested: self._mutex_payload_contains_array(
                field,
                active_type_params,
                nested,
            ),
        )

    def _unregistered_mutex_collection(
        self,
        type_expr,
        active_type_params,
        visiting,
    ):
        canonical = self._canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return None
        if canonical.base in _RUNTIME_COLLECTION_BASES and canonical.base not in self.class_table:
            return canonical.base
        if canonical.base == "__fn_ptr":
            return None
        for argument in canonical.generic_args or []:
            collection = self._unregistered_mutex_collection(
                argument,
                active_type_params,
                visiting,
            )
            if collection is not None:
                return collection
        return self._mutex_aggregate_fields_find(
            canonical,
            active_type_params,
            visiting,
            lambda field, nested: self._unregistered_mutex_collection(
                field,
                active_type_params,
                nested,
            ),
        )

    def _mutex_payload_has_managed_reference(
        self,
        type_expr,
        active_type_params,
        visiting,
    ) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None or self._is_unresolved_mutex_parameter(canonical, active_type_params):
            return False
        if self._is_direct_mutex_managed_value(canonical):
            return True
        if canonical.pointer_depth > 0 or canonical.base == "__fn_ptr":
            return False
        if canonical.is_array:
            canonical = replace(canonical, is_array=False, array_size=None)
        if canonical.base == "Tuple":
            return any(
                self._mutex_payload_has_managed_reference(
                    argument,
                    active_type_params,
                    visiting,
                )
                for argument in canonical.generic_args or []
            )
        return self._mutex_aggregate_fields_match(
            canonical,
            active_type_params,
            visiting,
            lambda field, nested: self._mutex_payload_has_managed_reference(
                field,
                active_type_params,
                nested,
            ),
        )

    def _is_direct_mutex_managed_value(self, canonical) -> bool:
        return bool(
            canonical
            and not canonical.is_array
            and (
                is_semantic_scalar_string(canonical)
                or (canonical.base in self.class_table and canonical.pointer_depth <= 1)
            )
        )

    @staticmethod
    def _is_unresolved_mutex_parameter(canonical, active_type_params) -> bool:
        return bool(
            canonical.base in active_type_params
            and not canonical.generic_args
            and canonical.pointer_depth == 0
            and not canonical.is_array
        )

    def _mutex_aggregate_fields_match(
        self,
        canonical,
        active_type_params,
        visiting,
        predicate,
    ) -> bool:
        return bool(
            self._mutex_aggregate_fields_find(
                canonical,
                active_type_params,
                visiting,
                lambda field, nested: True if predicate(field, nested) else None,
            )
        )

    def _mutex_aggregate_fields_find(
        self,
        canonical,
        active_type_params,
        visiting,
        find,
    ):
        if canonical.pointer_depth > 0:
            return None
        if canonical.base == "Tuple":
            for argument in canonical.generic_args or []:
                result = find(argument, visiting)
                if result is not None:
                    return result
            return None
        name = canonical.base.removeprefix("struct ")
        kind = "struct" if name in self.struct_table else "rich-enum"
        visit_key = f"{kind}:{name}"
        if visit_key in visiting:
            return None
        nested = visiting | {visit_key}
        declaration = self.struct_table.get(name)
        if declaration and not declaration.is_forward:
            for field in declaration.fields:
                result = find(field.type, nested)
                if result is not None:
                    return result
        rich_enum = self.rich_enum_table.get(name)
        if rich_enum:
            for variant in rich_enum.variants:
                for parameter in variant.params:
                    result = find(parameter.type, nested)
                    if result is not None:
                        return result
        return None


__all__ = ["MutexPayloadDomainContractsMixin"]
