"""Set<T> monomorphization: struct + methods."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type

if TYPE_CHECKING:
    from ..generator import IRGenerator


def _emit_set_instance(gen: IRGenerator, args: list[TypeExpr]):
    """Emit a monomorphized Set<T> struct and methods."""
    if not args:
        return
    elem_c = type_to_c(args[0])
    mangled = mangle_generic_type("Set", args)

    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=[
        IRStructField(c_type=CType(text=f"{elem_c}*"), name="keys"),
        IRStructField(c_type=CType(text="bool*"), name="occupied"),
        IRStructField(c_type=CType(text="int"), name="len"),
        IRStructField(c_type=CType(text="int"), name="cap"),
    ]))

    _emit_set_methods_raw(gen, mangled, elem_c, args[0])


def _emit_set_methods_raw(gen: IRGenerator, name: str, elem_c: str,
                          elem_type: TypeExpr):
    """Emit new, add, contains, remove, etc. for a Set."""
    is_str = elem_type.base == "string"
    hash_fn = "__btrc_hash_str(key)" if is_str else "(unsigned int)(key)"
    eq_fn = "strcmp(s->keys[idx], key) == 0" if is_str else "s->keys[idx] == key"

    if is_str:
        gen.use_helper("__btrc_hash_str")

    methods = f"""
static void {name}_add({name}* s, {elem_c} key);
static void {name}_resize({name}* s);
static {name}* {name}_new(void) {{
    {name}* s = ({name}*)malloc(sizeof({name}));
    s->cap = 16; s->len = 0;
    s->keys = ({elem_c}*)calloc(s->cap, sizeof({elem_c}));
    s->occupied = (bool*)calloc(s->cap, sizeof(bool));
    return s;
}}
static void {name}_resize({name}* s) {{
    int old_cap = s->cap;
    {elem_c}* old_k = s->keys; bool* old_o = s->occupied;
    s->cap *= 2; s->len = 0;
    s->keys = ({elem_c}*)calloc(s->cap, sizeof({elem_c}));
    s->occupied = (bool*)calloc(s->cap, sizeof(bool));
    for (int i = 0; i < old_cap; i++) {{
        if (old_o[i]) {{ {name}_add(s, old_k[i]); }}
    }}
    free(old_k); free(old_o);
}}
static void {name}_add({name}* s, {elem_c} key) {{
    if (s->len * 4 >= s->cap * 3) {name}_resize(s);
    unsigned int h = {hash_fn} % (unsigned int)s->cap;
    int idx = (int)h;
    while (s->occupied[idx]) {{
        if ({eq_fn}) return;
        idx = (idx + 1) % s->cap;
    }}
    s->keys[idx] = key; s->occupied[idx] = true; s->len++;
}}
static bool {name}_contains({name}* s, {elem_c} key) {{
    unsigned int h = {hash_fn} % (unsigned int)s->cap;
    int idx = (int)h;
    for (int i = 0; i < s->cap; i++) {{
        if (!s->occupied[idx]) return false;
        if ({eq_fn}) return true;
        idx = (idx + 1) % s->cap;
    }}
    return false;
}}
static bool {name}_has({name}* s, {elem_c} key) {{ return {name}_contains(s, key); }}
static void {name}_free({name}* s) {{ free(s->keys); free(s->occupied); free(s); }}
static int {name}_size({name}* s) {{ return s->len; }}
static bool {name}_isEmpty({name}* s) {{ return s->len == 0; }}
static void {name}_remove({name}* s, {elem_c} key) {{
    unsigned int h = {hash_fn} % (unsigned int)s->cap;
    int idx = (int)h;
    for (int i = 0; i < s->cap; i++) {{
        if (!s->occupied[idx]) return;
        if ({eq_fn}) {{ s->occupied[idx] = false; s->len--; return; }}
        idx = (idx + 1) % s->cap;
    }}
}}
static void {name}_clear({name}* s) {{
    memset(s->occupied, 0, sizeof(bool) * s->cap);
    s->len = 0;
}}
static void {name}_forEach({name}* s, void (*fn)({elem_c})) {{
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i]) fn(s->keys[i]);
    }}
}}
static {name}* {name}_filter({name}* s, bool (*pred)({elem_c})) {{
    {name}* r = {name}_new();
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && pred(s->keys[i])) {name}_add(r, s->keys[i]);
    }}
    return r;
}}
"""
    # toList, any, all, intersect, unite, subtract methods
    list_name = mangle_generic_type("List", [elem_type])
    methods += f"""
static {list_name}* {name}_toList({name}* s) {{
    {list_name}* r = {list_name}_new();
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i]) {list_name}_push(r, s->keys[i]);
    }}
    return r;
}}
static bool {name}_any({name}* s, bool (*pred)({elem_c})) {{
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && pred(s->keys[i])) return true;
    }}
    return false;
}}
static bool {name}_all({name}* s, bool (*pred)({elem_c})) {{
    for (int i = 0; i < s->cap; i++) {{
        if (s->occupied[i] && !pred(s->keys[i])) return false;
    }}
    return true;
}}
static {name}* {name}_intersect({name}* a, {name}* b) {{
    {name}* r = {name}_new();
    for (int i = 0; i < a->cap; i++) {{
        if (a->occupied[i] && {name}_contains(b, a->keys[i])) {name}_add(r, a->keys[i]);
    }}
    return r;
}}
static {name}* {name}_unite({name}* a, {name}* b) {{
    {name}* r = {name}_new();
    for (int i = 0; i < a->cap; i++) {{
        if (a->occupied[i]) {name}_add(r, a->keys[i]);
    }}
    for (int i = 0; i < b->cap; i++) {{
        if (b->occupied[i]) {name}_add(r, b->keys[i]);
    }}
    return r;
}}
static {name}* {name}_subtract({name}* a, {name}* b) {{
    {name}* r = {name}_new();
    for (int i = 0; i < a->cap; i++) {{
        if (a->occupied[i] && !{name}_contains(b, a->keys[i])) {name}_add(r, a->keys[i]);
    }}
    return r;
}}
"""
    gen.module.raw_sections.append(methods.strip())
