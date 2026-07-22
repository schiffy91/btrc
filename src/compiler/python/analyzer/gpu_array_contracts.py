"""GPU buffer capacity and ABI-exact element contracts."""

from dataclasses import replace

from ..type_identity import type_shape_key


class GpuArrayContractsMixin:
    def _gpu_buffer_element_type(self, type_expr):
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return None
        if canonical.base in {"Array", "Vector"} and len(canonical.generic_args) == 1:
            element = self._canonical_type(canonical.generic_args[0])
        elif canonical.is_array:
            element = self._canonical_type(self._array_element_type(canonical))
        else:
            return None
        return replace(element, is_static=False, is_extern=False)

    def _gpu_buffer_elements_exact(self, expected, actual) -> bool:
        expected_element = self._gpu_buffer_element_type(expected)
        actual_element = self._gpu_buffer_element_type(actual)
        return bool(
            expected_element is not None
            and actual_element is not None
            and type_shape_key(expected_element) == type_shape_key(actual_element)
        )

    def _gpu_input_has_compatible_storage(self, argument, expected, actual) -> bool:
        canonical = self._canonical_type(actual)
        return bool(
            canonical is not None
            and not canonical.is_volatile
            and self._array_target_has_capacity(argument, actual)
            and self._gpu_buffer_elements_exact(expected, actual)
            and not self._gpu_buffer_element_type(actual).is_volatile
        )

    def _gpu_output_element_compatible(self, target, source) -> bool:
        canonical = self._canonical_type(target)
        element = self._gpu_buffer_element_type(target)
        return bool(
            canonical is not None
            and element is not None
            and not canonical.is_const
            and not canonical.is_volatile
            and not element.is_const
            and not element.is_volatile
            and self._gpu_buffer_elements_exact(target, source)
        )


__all__ = ["GpuArrayContractsMixin"]
