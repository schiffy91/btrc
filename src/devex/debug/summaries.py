"""btrc-aware rendering of lldb values.

The generated C represents btrc values as tagged C structs. This module turns an
``lldb.SBValue`` into a btrc-level display: a ``string`` shows its text, a
``Vector<int>`` shows ``[10, 20, 30]``, a ``Map`` shows ``{a: 1}``, and a class
instance shows its fields by btrc name (hiding the ARC ``__rc`` slot).

Everything is introspected from the value's type (field names ``data``/``len``,
``keys``/``values``/``occupied``, the leading ``__rc``) rather than hard-coded,
so it tracks the stdlib collection layouts without a separate registry.
"""

from __future__ import annotations

MAX_ELEMS = 100  # cap children/summary length so huge collections stay responsive


def _struct_type(value):
    """Return the pointee struct type for a ``T*`` value, else its own type."""
    t = value.GetType()
    if t.IsPointerType():
        return t.GetPointeeType()
    return t


def _type_name(value) -> str:
    return _struct_type(value).GetName() or ""


def _deref(value):
    """Follow one pointer level if needed, returning the struct SBValue."""
    if value.GetType().IsPointerType():
        return value.Dereference()
    return value


def _is_null(value) -> bool:
    return value.GetType().IsPointerType() and value.GetValueAsUnsigned() == 0


def _field_names(struct_val):
    return [struct_val.GetChildAtIndex(i).GetName()
            for i in range(struct_val.GetNumChildren())]


def classify(value) -> str:
    """One of: string, vector, map, set, object, plain."""
    tn = _type_name(value)
    ctype = value.GetType().GetName() or ""
    if ctype in ("char *", "const char *", "char*", "const char*"):
        return "string"
    if tn.startswith("btrc_Vector_") or tn.startswith("btrc_List_"):
        return "vector"
    if tn.startswith("btrc_Map_"):
        return "map"
    if tn.startswith("btrc_Set_"):
        return "set"
    if value.GetType().IsPointerType():
        st = _struct_type(value)
        if st.IsValid() and "__rc" in [st.GetFieldAtIndex(i).GetName()
                                       for i in range(st.GetNumberOfFields())]:
            return "object"
    return "plain"


def _elem_summary(elem) -> str:
    """Short inline rendering of a collection element."""
    kind = classify(elem)
    if kind == "string":
        return _string_summary(elem)
    if kind in ("vector", "map", "set", "object"):
        return summarize(elem)
    v = elem.GetValue()
    return v if v is not None else "?"


def _string_summary(value) -> str:
    if _is_null(value):
        return "null"
    s = value.GetSummary()
    if s:
        return s
    data = value.GetPointeeData(0, 1)
    return '""' if data.GetByteSize() == 0 else value.GetValue() or '""'


def _vector_summary(value) -> str:
    if _is_null(value):
        return "null"
    st = _deref(value)
    n = st.GetChildMemberWithName("len").GetValueAsSigned()
    data = st.GetChildMemberWithName("data")
    shown = min(n, MAX_ELEMS)
    parts = [_elem_summary(data.GetChildAtIndex(i, 0, True)) for i in range(shown)]
    if n > shown:
        parts.append(f"... +{n - shown}")
    return f"[{', '.join(parts)}]  (len={n})"


def _map_summary(value) -> str:
    if _is_null(value):
        return "null"
    st = _deref(value)
    cap = st.GetChildMemberWithName("cap").GetValueAsSigned()
    n = st.GetChildMemberWithName("len").GetValueAsSigned()
    keys = st.GetChildMemberWithName("keys")
    values = st.GetChildMemberWithName("values")
    occ = st.GetChildMemberWithName("occupied")
    parts = []
    for i in range(cap):
        if len(parts) >= MAX_ELEMS:
            break
        if occ.GetChildAtIndex(i, 0, True).GetValueAsUnsigned():
            k = _elem_summary(keys.GetChildAtIndex(i, 0, True))
            v = _elem_summary(values.GetChildAtIndex(i, 0, True))
            parts.append(f"{k}: {v}")
    return f"{{{', '.join(parts)}}}  (len={n})"


def _set_summary(value) -> str:
    if _is_null(value):
        return "null"
    st = _deref(value)
    cap = st.GetChildMemberWithName("cap").GetValueAsSigned()
    n = st.GetChildMemberWithName("len").GetValueAsSigned()
    items = st.GetChildMemberWithName("keys") or st.GetChildMemberWithName("items")
    occ = st.GetChildMemberWithName("occupied")
    parts = []
    for i in range(cap):
        if len(parts) >= MAX_ELEMS:
            break
        if occ.GetChildAtIndex(i, 0, True).GetValueAsUnsigned():
            parts.append(_elem_summary(items.GetChildAtIndex(i, 0, True)))
    return f"{{{', '.join(parts)}}}  (len={n})"


def _object_summary(value) -> str:
    if _is_null(value):
        return "null"
    st = _deref(value)
    tn = _type_name(value)
    fields = []
    for name in _field_names(st):
        if name == "__rc":
            continue
        fields.append(f"{name}={_elem_summary(st.GetChildMemberWithName(name))}")
        if len(fields) >= 12:
            break
    return f"{tn} {{{', '.join(fields)}}}"


def summarize(value) -> str:
    """Return a btrc-level one-line summary for an SBValue."""
    try:
        kind = classify(value)
        if kind == "string":
            return _string_summary(value)
        if kind == "vector":
            return _vector_summary(value)
        if kind == "map":
            return _map_summary(value)
        if kind == "set":
            return _set_summary(value)
        if kind == "object":
            return _object_summary(value)
        v = value.GetValue()
        return v if v is not None else (value.GetSummary() or "")
    except Exception as e:  # never let formatting crash a debug session
        return f"<error: {e}>"


def children(value):
    """Return [(name, SBValue), ...] for expanding a structured btrc value.

    Empty for scalars/strings (leaf nodes)."""
    try:
        kind = classify(value)
        if kind in ("string", "plain") or _is_null(value):
            return []
        st = _deref(value)
        if kind == "vector":
            n = st.GetChildMemberWithName("len").GetValueAsSigned()
            data = st.GetChildMemberWithName("data")
            return [(f"[{i}]", data.GetChildAtIndex(i, 0, True))
                    for i in range(min(n, MAX_ELEMS))]
        if kind in ("map", "set"):
            cap = st.GetChildMemberWithName("cap").GetValueAsSigned()
            occ = st.GetChildMemberWithName("occupied")
            keys = (st.GetChildMemberWithName("keys")
                    or st.GetChildMemberWithName("items"))
            values = st.GetChildMemberWithName("values")  # invalid for sets
            out = []
            for i in range(cap):
                if len(out) >= MAX_ELEMS:
                    break
                if not occ.GetChildAtIndex(i, 0, True).GetValueAsUnsigned():
                    continue
                key_repr = _elem_summary(keys.GetChildAtIndex(i, 0, True))
                if kind == "map" and values.IsValid():
                    out.append((str(key_repr), values.GetChildAtIndex(i, 0, True)))
                else:
                    out.append((f"[{len(out)}]", keys.GetChildAtIndex(i, 0, True)))
            return out
        if kind == "object":
            return [(name, st.GetChildMemberWithName(name))
                    for name in _field_names(st) if name != "__rc"]
        return []
    except Exception:
        return []
