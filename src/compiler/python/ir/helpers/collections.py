"""Collections runtime helpers -- template-based helpers for List, Map, Set.

These contain Python format-string placeholders ({name}, {c_type},
{k_type}, {v_type}) that must be filled in for each monomorphised
concrete type.  Use  .c_source.format(name=..., c_type=...)  etc.
"""

from .core import HelperDef

COLLECTIONS = {
    # ---- List functional methods ----
    "List_forEach": HelperDef(
        c_source=(
            "static inline void {name}_forEach({name}* l, void (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < l->len; i++) fn(l->data[i], __ctx);\n"
            "}}"
        ),
    ),
    "List_filter": HelperDef(
        c_source=(
            "static inline {name}* {name}_filter({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    {name}* result = {name}_new();\n"
            "    for (int i = 0; i < l->len; i++) {{\n"
            "        if (fn(l->data[i], __ctx)) {name}_push(result, l->data[i]);\n"
            "    }}\n"
            "    return result;\n"
            "}}"
        ),
    ),
    "List_any": HelperDef(
        c_source=(
            "static inline bool {name}_any({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < l->len; i++) {{ if (fn(l->data[i], __ctx)) return true; }}\n"
            "    return false;\n"
            "}}"
        ),
    ),
    "List_all": HelperDef(
        c_source=(
            "static inline bool {name}_all({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < l->len; i++) {{ if (!fn(l->data[i], __ctx)) return false; }}\n"
            "    return true;\n"
            "}}"
        ),
    ),
    "List_findIndex": HelperDef(
        c_source=(
            "static inline int {name}_findIndex({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < l->len; i++) {{ if (fn(l->data[i], __ctx)) return i; }}\n"
            "    return -1;\n"
            "}}"
        ),
    ),
    "List_map": HelperDef(
        c_source=(
            "static inline {name}* {name}_map({name}* l, {c_type} (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    {name}* result = {name}_new();\n"
            "    for (int i = 0; i < l->len; i++) {name}_push(result, fn(l->data[i], __ctx));\n"
            "    return result;\n"
            "}}"
        ),
    ),
    "List_reduce": HelperDef(
        c_source=(
            "static inline {c_type} {name}_reduce({name}* l, {c_type} init, {c_type} (*fn)({c_type}, {c_type})) {{\n"
            "    {c_type} acc = init;\n"
            "    for (int i = 0; i < l->len; i++) acc = fn(acc, l->data[i]);\n"
            "    return acc;\n"
            "}}"
        ),
    ),
    # ---- Map functional methods ----
    "Map_forEach": HelperDef(
        c_source=(
            "static inline void {name}_forEach({name}* m, void (*fn)({k_type}, {v_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < m->cap; i++) {{\n"
            "        if (m->occupied[i]) fn(m->keys[i], m->values[i], __ctx);\n"
            "    }}\n"
            "}}"
        ),
    ),
    "Map_containsValue": HelperDef(
        c_source=(
            "static inline bool {name}_containsValue({name}* m, {v_type} value) {{\n"
            "    for (int i = 0; i < m->cap; i++) {{\n"
            "        if (m->occupied[i] && {val_eq}) return true;\n"
            "    }}\n"
            "    return false;\n"
            "}}"
        ),
    ),
    # ---- Set functional methods ----
    "Set_forEach": HelperDef(
        c_source=(
            "static inline void {name}_forEach({name}* s, void (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < s->cap; i++) {{\n"
            "        if (s->occupied[i]) fn(s->keys[i], __ctx);\n"
            "    }}\n"
            "}}"
        ),
    ),
    "Set_filter": HelperDef(
        c_source=(
            "static inline {name}* {name}_filter({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    {name}* result = {name}_new();\n"
            "    for (int i = 0; i < s->cap; i++) {{\n"
            "        if (s->occupied[i] && fn(s->keys[i], __ctx)) {{\n"
            "            {name}_add(result, s->keys[i]);\n"
            "        }}\n"
            "    }}\n"
            "    return result;\n"
            "}}"
        ),
    ),
    "Set_any": HelperDef(
        c_source=(
            "static inline bool {name}_any({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < s->cap; i++) {{\n"
            "        if (s->occupied[i] && fn(s->keys[i], __ctx)) return true;\n"
            "    }}\n"
            "    return false;\n"
            "}}"
        ),
    ),
    "Set_all": HelperDef(
        c_source=(
            "static inline bool {name}_all({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < s->cap; i++) {{\n"
            "        if (s->occupied[i] && !fn(s->keys[i], __ctx)) return false;\n"
            "    }}\n"
            "    return true;\n"
            "}}"
        ),
    ),
    "Set_findIndex": HelperDef(
        c_source=(
            "static inline int {name}_findIndex({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{\n"
            "    for (int i = 0; i < s->cap; i++) {{\n"
            "        if (s->occupied[i] && fn(s->keys[i], __ctx)) return i;\n"
            "    }}\n"
            "    return -1;\n"
            "}}"
        ),
    ),
}
