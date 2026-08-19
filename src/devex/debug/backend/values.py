"""Configurable btrc-aware presentation of LLDB values.

The generated C represents btrc values as tagged C structs. A
``BtrcValuePresenter`` turns an ``lldb.SBValue`` into a btrc-level display: a
``string`` shows its text, a ``Vector<int>`` shows ``[10, 20, 30]``, a ``Map``
shows ``{a: 1}``, and a class instance shows its fields by btrc name while
hiding its ARC header.

Layouts are discovered from debug types and fields rather than a separate
registry, so presentation follows the generated stdlib collection layouts.
"""

from __future__ import annotations


class BtrcValuePresenter:
    """Own recursive LLDB value classification, summaries, and children."""

    DEFAULT_MAX_ELEMENTS = 100
    DEFAULT_MAX_OBJECT_FIELDS = 12

    def __init__(
        self,
        *,
        max_elements: int = DEFAULT_MAX_ELEMENTS,
        max_object_fields: int = DEFAULT_MAX_OBJECT_FIELDS,
    ) -> None:
        if max_elements < 0:
            raise ValueError("max_elements must be non-negative")
        if max_object_fields < 0:
            raise ValueError("max_object_fields must be non-negative")
        self.max_elements = max_elements
        self.max_object_fields = max_object_fields

    def classify(self, value) -> str:
        """Return ``string``, ``vector``, ``map``, ``set``, ``object``, or ``plain``."""
        type_name = self._type_name(value)
        c_type_name = value.GetType().GetName() or ""
        if self._is_string_type_name(c_type_name):
            return "string"
        if type_name.startswith(("btrc_Vector_", "btrc_List_")):
            return "vector"
        if type_name.startswith("btrc_Map_"):
            return "map"
        if type_name.startswith("btrc_Set_"):
            return "set"
        if self._value_type(value).IsPointerType():
            struct_type = self._struct_type(value)
            if struct_type.IsValid() and any(
                self._is_arc_header(struct_type.GetFieldAtIndex(index).GetName())
                for index in range(struct_type.GetNumberOfFields())
            ):
                return "object"
        return "plain"

    def summarize(self, value) -> str:
        """Return a btrc-level one-line summary for an ``SBValue``."""
        try:
            kind = self.classify(value)
            if kind == "string":
                return self._string_summary(value)
            if kind == "vector":
                return self._vector_summary(value)
            if kind == "map":
                return self._map_summary(value)
            if kind == "set":
                return self._set_summary(value)
            if kind == "object":
                return self._object_summary(value)
            raw_value = value.GetValue()
            return raw_value if raw_value is not None else (value.GetSummary() or "")
        except Exception as error:  # never let formatting crash a debug session
            return f"<error: {error}>"

    def children(self, value):
        """Return expandable ``(name, SBValue)`` pairs for a structured value."""
        try:
            kind = self.classify(value)
            if kind in ("string", "plain") or self._is_null(value):
                return []
            struct_value = self._deref(value)
            if kind == "vector":
                length = struct_value.GetChildMemberWithName("len").GetValueAsSigned()
                data = struct_value.GetChildMemberWithName("data")
                return [
                    (f"[{index}]", data.GetChildAtIndex(index, 0, True))
                    for index in range(min(length, self.max_elements))
                ]
            if kind in ("map", "set"):
                return self._collection_children(struct_value, kind)
            if kind == "object":
                return [
                    (name, struct_value.GetChildMemberWithName(name))
                    for name in self._field_names(struct_value)
                    if not self._is_arc_header(name)
                ]
            return []
        except Exception:
            return []

    def _value_type(self, value):
        """Return a value's type without top-level C qualifiers."""
        value_type = value.GetType()
        get_unqualified = getattr(value_type, "GetUnqualifiedType", None)
        if get_unqualified is None:
            return value_type
        unqualified = get_unqualified()
        return unqualified if unqualified.IsValid() else value_type

    def _struct_type(self, value):
        """Return the pointee struct type for ``T*``, otherwise the value type."""
        value_type = self._value_type(value)
        if value_type.IsPointerType():
            return value_type.GetPointeeType()
        return value_type

    def _type_name(self, value) -> str:
        return self._struct_type(value).GetName() or ""

    def _deref(self, value):
        if self._value_type(value).IsPointerType():
            return value.Dereference()
        return value

    def _is_null(self, value) -> bool:
        return self._value_type(value).IsPointerType() and value.GetValueAsUnsigned() == 0

    def _field_names(self, struct_value):
        return [struct_value.GetChildAtIndex(index).GetName() for index in range(struct_value.GetNumChildren())]

    def _is_arc_header(self, name: str | None) -> bool:
        """Accept both the current aggregate header and legacy scalar slot."""
        return name in {"__arc", "__rc"}

    def _is_string_type_name(self, c_type_name: str) -> bool:
        """Recognize btrc strings despite C debug-info qualifiers and spacing."""
        words = c_type_name.replace("*", " * ").split()
        unqualified = [word for word in words if word not in {"const", "volatile", "restrict", "_Atomic"}]
        return unqualified == ["char", "*"]

    def _element_summary(self, element) -> str:
        """Render a collection element through this presenter's policy."""
        kind = self.classify(element)
        if kind == "string":
            return self._string_summary(element)
        if kind in ("vector", "map", "set", "object"):
            return self.summarize(element)
        raw_value = element.GetValue()
        return raw_value if raw_value is not None else "?"

    def _string_summary(self, value) -> str:
        if self._is_null(value):
            return "null"
        summary = value.GetSummary()
        if summary:
            return summary
        data = value.GetPointeeData(0, 1)
        return '""' if data.GetByteSize() == 0 else value.GetValue() or '""'

    def _vector_summary(self, value) -> str:
        if self._is_null(value):
            return "null"
        struct_value = self._deref(value)
        length = struct_value.GetChildMemberWithName("len").GetValueAsSigned()
        data = struct_value.GetChildMemberWithName("data")
        shown = min(length, self.max_elements)
        parts = [self._element_summary(data.GetChildAtIndex(index, 0, True)) for index in range(shown)]
        if length > shown:
            parts.append(f"... +{length - shown}")
        return f"[{', '.join(parts)}]  (len={length})"

    def _map_summary(self, value) -> str:
        if self._is_null(value):
            return "null"
        struct_value = self._deref(value)
        capacity = struct_value.GetChildMemberWithName("cap").GetValueAsSigned()
        length = struct_value.GetChildMemberWithName("len").GetValueAsSigned()
        keys = struct_value.GetChildMemberWithName("keys")
        values = struct_value.GetChildMemberWithName("values")
        occupied = struct_value.GetChildMemberWithName("occupied")
        parts = []
        for index in range(capacity):
            if len(parts) >= self.max_elements:
                break
            if occupied.GetChildAtIndex(index, 0, True).GetValueAsUnsigned():
                key = self._element_summary(keys.GetChildAtIndex(index, 0, True))
                item = self._element_summary(values.GetChildAtIndex(index, 0, True))
                parts.append(f"{key}: {item}")
        return f"{{{', '.join(parts)}}}  (len={length})"

    def _set_summary(self, value) -> str:
        if self._is_null(value):
            return "null"
        struct_value = self._deref(value)
        capacity = struct_value.GetChildMemberWithName("cap").GetValueAsSigned()
        length = struct_value.GetChildMemberWithName("len").GetValueAsSigned()
        items = struct_value.GetChildMemberWithName("keys") or struct_value.GetChildMemberWithName("items")
        occupied = struct_value.GetChildMemberWithName("occupied")
        parts = []
        for index in range(capacity):
            if len(parts) >= self.max_elements:
                break
            if occupied.GetChildAtIndex(index, 0, True).GetValueAsUnsigned():
                parts.append(self._element_summary(items.GetChildAtIndex(index, 0, True)))
        return f"{{{', '.join(parts)}}}  (len={length})"

    def _object_summary(self, value) -> str:
        if self._is_null(value):
            return "null"
        struct_value = self._deref(value)
        fields = []
        for name in self._field_names(struct_value):
            if self._is_arc_header(name):
                continue
            if len(fields) >= self.max_object_fields:
                break
            fields.append(f"{name}={self._element_summary(struct_value.GetChildMemberWithName(name))}")
        return f"{self._type_name(value)} {{{', '.join(fields)}}}"

    def _collection_children(self, struct_value, kind: str):
        capacity = struct_value.GetChildMemberWithName("cap").GetValueAsSigned()
        occupied = struct_value.GetChildMemberWithName("occupied")
        keys = struct_value.GetChildMemberWithName("keys") or struct_value.GetChildMemberWithName("items")
        values = struct_value.GetChildMemberWithName("values")
        children = []
        for index in range(capacity):
            if len(children) >= self.max_elements:
                break
            if not occupied.GetChildAtIndex(index, 0, True).GetValueAsUnsigned():
                continue
            key = keys.GetChildAtIndex(index, 0, True)
            if kind == "map" and values.IsValid():
                children.append((str(self._element_summary(key)), values.GetChildAtIndex(index, 0, True)))
            else:
                children.append((f"[{len(children)}]", key))
        return children
