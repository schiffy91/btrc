"""Map<K, V> monomorphization: struct + methods."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type

if TYPE_CHECKING:
    from ..generator import IRGenerator


def _emit_map_instance(gen: IRGenerator, args: list[TypeExpr]):
    """Emit a monomorphized Map<K, V> struct and methods."""
    if len(args) < 2:
        return
    k_c = type_to_c(args[0])
    v_c = type_to_c(args[1])
    mangled = mangle_generic_type("Map", args)

    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=[
        IRStructField(c_type=CType(text=f"{k_c}*"), name="keys"),
        IRStructField(c_type=CType(text=f"{v_c}*"), name="values"),
        IRStructField(c_type=CType(text="bool*"), name="occupied"),
        IRStructField(c_type=CType(text="int"), name="len"),
        IRStructField(c_type=CType(text="int"), name="cap"),
    ]))

    _emit_map_methods_raw(gen, mangled, k_c, v_c, args[0], args[1] if len(args) > 1 else args[0])


def _emit_map_methods_raw(gen: IRGenerator, name: str, k_c: str, v_c: str,
                          k_type: TypeExpr, v_type: TypeExpr = None):
    """Emit new, put, get, has, etc. for a Map."""
    is_str_key = k_type.base == "string"
    hash_fn = "__btrc_hash_str(key)" if is_str_key else "(unsigned int)(key)"
    eq_fn = "strcmp(m->keys[idx], key) == 0" if is_str_key else "m->keys[idx] == key"

    if is_str_key:
        gen.use_helper("__btrc_hash_str")

    methods = f"""
static void {name}_put({name}* m, {k_c} key, {v_c} value);
static void {name}_resize({name}* m);
static {name}* {name}_new(void) {{
    {name}* m = ({name}*)malloc(sizeof({name}));
    m->cap = 16; m->len = 0;
    m->keys = ({k_c}*)calloc(m->cap, sizeof({k_c}));
    m->values = ({v_c}*)calloc(m->cap, sizeof({v_c}));
    m->occupied = (bool*)calloc(m->cap, sizeof(bool));
    return m;
}}
static void {name}_resize({name}* m) {{
    int old_cap = m->cap;
    {k_c}* old_k = m->keys; {v_c}* old_v = m->values; bool* old_o = m->occupied;
    m->cap *= 2; m->len = 0;
    m->keys = ({k_c}*)calloc(m->cap, sizeof({k_c}));
    m->values = ({v_c}*)calloc(m->cap, sizeof({v_c}));
    m->occupied = (bool*)calloc(m->cap, sizeof(bool));
    for (int i = 0; i < old_cap; i++) {{
        if (old_o[i]) {{ {name}_put(m, old_k[i], old_v[i]); }}
    }}
    free(old_k); free(old_v); free(old_o);
}}
static void {name}_put({name}* m, {k_c} key, {v_c} value) {{
    if (m->len * 4 >= m->cap * 3) {name}_resize(m);
    unsigned int h = {hash_fn} % (unsigned int)m->cap;
    int idx = (int)h;
    while (m->occupied[idx]) {{
        if ({eq_fn}) {{ m->values[idx] = value; return; }}
        idx = (idx + 1) % m->cap;
    }}
    m->keys[idx] = key; m->values[idx] = value; m->occupied[idx] = true; m->len++;
}}
static {v_c} {name}_get({name}* m, {k_c} key) {{
    unsigned int h = {hash_fn} % (unsigned int)m->cap;
    int idx = (int)h;
    for (int i = 0; i < m->cap; i++) {{
        if (!m->occupied[idx]) {{ fprintf(stderr, "Key not found\\n"); exit(1); }}
        if ({eq_fn}) return m->values[idx];
        idx = (idx + 1) % m->cap;
    }}
    fprintf(stderr, "Key not found\\n"); exit(1);
    return ({v_c}){{0}};
}}
static bool {name}_has({name}* m, {k_c} key) {{
    unsigned int h = {hash_fn} % (unsigned int)m->cap;
    int idx = (int)h;
    for (int i = 0; i < m->cap; i++) {{
        if (!m->occupied[idx]) return false;
        if ({eq_fn}) return true;
        idx = (idx + 1) % m->cap;
    }}
    return false;
}}
static bool {name}_contains({name}* m, {k_c} key) {{ return {name}_has(m, key); }}
static void {name}_free({name}* m) {{ free(m->keys); free(m->values); free(m->occupied); free(m); }}
static int {name}_size({name}* m) {{ return m->len; }}
static bool {name}_isEmpty({name}* m) {{ return m->len == 0; }}
static {v_c} {name}_getOrDefault({name}* m, {k_c} key, {v_c} fallback) {{
    unsigned int h = {hash_fn} % (unsigned int)m->cap;
    int idx = (int)h;
    for (int i = 0; i < m->cap; i++) {{
        if (!m->occupied[idx]) return fallback;
        if ({eq_fn}) return m->values[idx];
        idx = (idx + 1) % m->cap;
    }}
    return fallback;
}}
static void {name}_remove({name}* m, {k_c} key) {{
    unsigned int h = {hash_fn} % (unsigned int)m->cap;
    int idx = (int)h;
    for (int i = 0; i < m->cap; i++) {{
        if (!m->occupied[idx]) return;
        if ({eq_fn}) {{ m->occupied[idx] = false; m->len--; return; }}
        idx = (idx + 1) % m->cap;
    }}
}}
static void {name}_clear({name}* m) {{
    memset(m->occupied, 0, sizeof(bool) * m->cap);
    m->len = 0;
}}
static void {name}_putIfAbsent({name}* m, {k_c} key, {v_c} value) {{
    if (!{name}_has(m, key)) {name}_put(m, key, value);
}}
static bool {name}_containsValue({name}* m, {v_c} value) {{
    for (int i = 0; i < m->cap; i++) {{
        if (m->occupied[i] && m->values[i] == value) return true;
    }}
    return false;
}}
static void {name}_set({name}* m, {k_c} key, {v_c} value) {{ {name}_put(m, key, value); }}
static void {name}_merge({name}* m, {name}* other) {{
    for (int i = 0; i < other->cap; i++) {{
        if (other->occupied[i]) {name}_put(m, other->keys[i], other->values[i]);
    }}
}}
"""
    # Add keys/values/toList methods that return List types
    k_list_name = mangle_generic_type("List", [k_type])
    v_list_name = mangle_generic_type("List", [v_type]) if v_type else "btrc_List_int"
    methods += f"""
static {k_list_name}* {name}_keys({name}* m) {{
    {k_list_name}* r = {k_list_name}_new();
    for (int i = 0; i < m->cap; i++) {{
        if (m->occupied[i]) {k_list_name}_push(r, m->keys[i]);
    }}
    return r;
}}
static {v_list_name}* {name}_values({name}* m) {{
    {v_list_name}* r = {v_list_name}_new();
    for (int i = 0; i < m->cap; i++) {{
        if (m->occupied[i]) {v_list_name}_push(r, m->values[i]);
    }}
    return r;
}}
"""
    gen.module.raw_sections.append(methods.strip())
