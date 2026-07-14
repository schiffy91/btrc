"""Type contracts shared by fields, parameters, and local initializers."""

from ..ast_nodes import BraceInitializer, ListLiteral, MapLiteral
from ..type_identity import is_semantic_scalar_void


class InitializerValidationMixin:
    def _validate_typed_initializer(self, expected, initializer, subject, line, col):
        """Validate an already-analyzed initializer against its declared type."""
        self._validate_fixed_array_initializer(
            expected,
            initializer,
            subject,
            line,
            col,
        )
        self._contextualize_generic_constructor(expected, initializer)
        contextual = self._contextualize_aggregate_initializer(expected, initializer, subject, line, col)
        contextual = contextual or self._contextualize_collection_initializer(expected, initializer, subject, line, col)

        actual = self._infer_type(initializer)
        if actual is None:
            return
        if is_semantic_scalar_void(actual):
            self._error(f"{subject} cannot be initialized from a void expression", line, col)
        elif not contextual and not self._types_compatible(expected, actual):
            self._error(
                f"{subject} expects '{self._format_type(expected)}' but got '{self._format_type(actual)}'",
                line,
                col,
            )
        return contextual

    def _contextualize_aggregate_initializer(self, expected, initializer, subject, line, col) -> bool:
        """Give a positional brace initializer its struct or tuple type."""

        if not isinstance(initializer, BraceInitializer):
            return False
        canonical = self._canonical_type(expected)
        if canonical is None or canonical.pointer_depth > 0 or canonical.is_array:
            return False

        struct_name = canonical.base.removeprefix("struct ")
        declaration = self.struct_table.get(struct_name)
        if declaration is not None and not declaration.is_forward:
            fields = [(field.name, field.type) for field in declaration.fields]
            aggregate_name = f"struct '{struct_name}'"
        elif canonical.base == "Tuple":
            fields = [(f"_{index}", argument) for index, argument in enumerate(canonical.generic_args)]
            aggregate_name = f"tuple '{self._format_type(canonical)}'"
        else:
            return False

        if len(initializer.elements) > len(fields):
            self._error(
                f"{subject} has {len(initializer.elements)} initializer elements "
                f"but {aggregate_name} has {len(fields)} fields",
                line,
                col,
            )
        for element, (field_name, field_type) in zip(initializer.elements, fields):
            element_line = getattr(element, "line", line)
            element_col = getattr(element, "col", col)
            self._validate_typed_initializer(
                field_type,
                element,
                f"Field '{field_name}'",
                element_line,
                element_col,
            )
        self.node_types[id(initializer)] = expected
        self._collect_generic_instances(expected)
        return True

    def _contextualize_collection_initializer(self, expected, initializer, subject, line, col) -> bool:
        element_types = None
        if isinstance(initializer, BraceInitializer):
            if expected.generic_args:
                element_types = expected.generic_args[:1]
            elif expected.is_array:
                element_types = [self._array_element_type(expected)]
        elif isinstance(initializer, ListLiteral):
            if expected.is_array:
                element_types = [self._array_element_type(expected)]
            elif expected.base in ("Vector", "List", "Array") and len(expected.generic_args) == 1:
                element_types = expected.generic_args
        elif isinstance(initializer, MapLiteral) and expected.base == "Map" and len(expected.generic_args) == 2:
            self._validate_map_initializer(expected, initializer, subject, line, col)
            self.node_types[id(initializer)] = expected
            self._collect_generic_instances(expected)
            return True

        if element_types is None:
            return False
        expected_element = element_types[0]
        for element in initializer.elements:
            self._validate_collection_element(expected_element, element, subject, line, col)
        self.node_types[id(initializer)] = expected
        self._collect_generic_instances(expected)
        return True

    def _array_element_type(self, array_type):
        from dataclasses import replace

        return replace(array_type, is_array=False, array_size=None)

    def _validate_collection_element(self, expected, element, subject, line, col):
        if isinstance(element, (BraceInitializer, ListLiteral, MapLiteral)):
            self._validate_typed_initializer(
                expected,
                element,
                subject,
                getattr(element, "line", line),
                getattr(element, "col", col),
            )
            return
        actual = self._infer_type(element)
        if actual and not self._types_compatible(expected, actual):
            self._error(
                f"{subject} expects '{self._format_type(expected)}' elements but got '{self._format_type(actual)}'",
                getattr(element, "line", line),
                getattr(element, "col", col),
            )

    def _validate_map_initializer(self, expected, initializer, subject, line, col):
        key_type, value_type = expected.generic_args
        for entry in initializer.entries:
            self._validate_collection_element(key_type, entry.key, f"{subject} key", line, col)
            self._validate_collection_element(value_type, entry.value, f"{subject} value", line, col)
