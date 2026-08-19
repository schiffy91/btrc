/* btrc-runtime-helper:begin List_forEach */
static inline void {name}_forEach({name}* l, void (*fn)({c_type}, void*), void* __ctx) {{
    if (!l || !fn) return;
    for (int i = 0; i < l->len; i++) fn(l->data[i], __ctx);
}}
/* btrc-runtime-helper:end List_forEach */
/* btrc-runtime-helper:begin List_filter */
static inline {name}* {name}_filter({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{
    {name}* result = {name}_new();
    if (!l || !fn) return result;
    for (int i = 0; i < l->len; i++) {{
        if (fn(l->data[i], __ctx)) {name}_push(result, l->data[i]);
    }}
    return result;
}}
/* btrc-runtime-helper:end List_filter */
/* btrc-runtime-helper:begin List_any */
static inline bool {name}_any({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{
    if (!l || !fn) return false;
    for (int i = 0; i < l->len; i++) {{ if (fn(l->data[i], __ctx)) return true; }}
    return false;
}}
/* btrc-runtime-helper:end List_any */
/* btrc-runtime-helper:begin List_all */
static inline bool {name}_all({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{
    if (!l || !fn) return false;
    for (int i = 0; i < l->len; i++) {{ if (!fn(l->data[i], __ctx)) return false; }}
    return true;
}}
/* btrc-runtime-helper:end List_all */
/* btrc-runtime-helper:begin List_findIndex */
static inline int {name}_findIndex({name}* l, bool (*fn)({c_type}, void*), void* __ctx) {{
    if (!l || !fn) return -1;
    for (int i = 0; i < l->len; i++) {{ if (fn(l->data[i], __ctx)) return i; }}
    return -1;
}}
/* btrc-runtime-helper:end List_findIndex */
/* btrc-runtime-helper:begin List_map */
static inline {name}* {name}_map({name}* l, {c_type} (*fn)({c_type}, void*), void* __ctx) {{
    {name}* result = {name}_new();
    if (!l || !fn) return result;
    for (int i = 0; i < l->len; i++) {name}_push(result, fn(l->data[i], __ctx));
    return result;
}}
/* btrc-runtime-helper:end List_map */
/* btrc-runtime-helper:begin List_reduce */
static inline {c_type} {name}_reduce({name}* l, {c_type} init, {c_type} (*fn)({c_type}, {c_type})) {{
    if (!l || !fn) return init;
    {c_type} acc = init;
    for (int i = 0; i < l->len; i++) acc = fn(acc, l->data[i]);
    return acc;
}}
/* btrc-runtime-helper:end List_reduce */
/* btrc-runtime-helper:begin Map_forEach */
static inline void {name}_forEach({name}* m, void (*fn)({k_type}, {v_type}, void*), void* __ctx) {{
    if (!m || !fn) return;
    for (int i = 0; i < m->cap; i++) {{
        if (m->occupied[i]) fn(m->keys[i], m->values[i], __ctx);
    }}
}}
/* btrc-runtime-helper:end Map_forEach */
/* btrc-runtime-helper:begin Map_containsValue */
static inline bool {name}_containsValue({name}* m, {v_type} value) {{
    if (!m) return false;
    for (int i = 0; i < m->cap; i++) {{
        if (m->occupied[i] && {val_eq}) return true;
    }}
    return false;
}}
/* btrc-runtime-helper:end Map_containsValue */
/* btrc-runtime-helper:begin Set_forEach */
static inline void {name}_forEach({name}* s, void (*fn)({c_type}, void*), void* __ctx) {{
    if (!s || !fn) return;
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i]) fn(s->keys[i], __ctx);
    }}
}}
/* btrc-runtime-helper:end Set_forEach */
/* btrc-runtime-helper:begin Set_filter */
static inline {name}* {name}_filter({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{
    {name}* result = {name}_new();
    if (!s || !fn) return result;
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && fn(s->keys[i], __ctx)) {{
            {name}_add(result, s->keys[i]);
        }}
    }}
    return result;
}}
/* btrc-runtime-helper:end Set_filter */
/* btrc-runtime-helper:begin Set_any */
static inline bool {name}_any({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{
    if (!s || !fn) return false;
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && fn(s->keys[i], __ctx)) return true;
    }}
    return false;
}}
/* btrc-runtime-helper:end Set_any */
/* btrc-runtime-helper:begin Set_all */
static inline bool {name}_all({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{
    if (!s || !fn) return false;
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && !fn(s->keys[i], __ctx)) return false;
    }}
    return true;
}}
/* btrc-runtime-helper:end Set_all */
/* btrc-runtime-helper:begin Set_findIndex */
static inline int {name}_findIndex({name}* s, bool (*fn)({c_type}, void*), void* __ctx) {{
    if (!s || !fn) return -1;
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && fn(s->keys[i], __ctx)) return i;
    }}
    return -1;
}}
/* btrc-runtime-helper:end Set_findIndex */
