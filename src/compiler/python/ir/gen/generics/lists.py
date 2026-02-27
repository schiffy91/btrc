"""List<T> monomorphization: struct + methods."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type
from .core import _eq, _gt, _lt

if TYPE_CHECKING:
    from ..generator import IRGenerator


def _emit_list_instance(gen: IRGenerator, args: list[TypeExpr]):
    """Emit a monomorphized List<T> struct and methods."""
    if not args:
        return
    elem_type = args[0]
    elem_c = type_to_c(elem_type)
    mangled = mangle_generic_type("List", args)

    # Struct: { T* data; int len; int cap; }
    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=[
        IRStructField(c_type=CType(text=f"{elem_c}*"), name="data"),
        IRStructField(c_type=CType(text="int"), name="len"),
        IRStructField(c_type=CType(text="int"), name="cap"),
    ]))

    # Emit List methods as raw C (these are well-defined patterns)
    _emit_list_methods_raw(gen, mangled, elem_c)


def _emit_list_methods_raw(gen: IRGenerator, name: str, elem_c: str):
    """Emit new, push, pop, get, set, free, etc. for a List."""
    gen.use_helper("__btrc_safe_realloc")
    methods = f"""
static {name}* {name}_new(void) {{
    {name}* l = ({name}*)malloc(sizeof({name}));
    l->data = ({elem_c}*)malloc(sizeof({elem_c}) * 8);
    l->len = 0; l->cap = 8;
    return l;
}}
static void {name}_push({name}* l, {elem_c} val) {{
    if (l->len >= l->cap) {{
        l->cap *= 2;
        l->data = ({elem_c}*)__btrc_safe_realloc(l->data, sizeof({elem_c}) * l->cap);
    }}
    l->data[l->len++] = val;
}}
static {elem_c} {name}_pop({name}* l) {{
    if (l->len <= 0) {{ fprintf(stderr, "pop from empty list\\n"); exit(1); }}
    return l->data[--l->len];
}}
static {elem_c} {name}_get({name}* l, int i) {{
    if (i < 0 || i >= l->len) {{ fprintf(stderr, "index %d out of bounds (len %d)\\n", i, l->len); exit(1); }}
    return l->data[i];
}}
static void {name}_set({name}* l, int i, {elem_c} val) {{
    if (i < 0 || i >= l->len) {{ fprintf(stderr, "index %d out of bounds (len %d)\\n", i, l->len); exit(1); }}
    l->data[i] = val;
}}
static void {name}_free({name}* l) {{ free(l->data); free(l); }}
static void {name}_remove({name}* l, int idx) {{
    for (int i = idx; i < l->len - 1; i++) l->data[i] = l->data[i+1];
    l->len--;
}}
static int {name}_size({name}* l) {{ return l->len; }}
static bool {name}_isEmpty({name}* l) {{ return l->len == 0; }}
static bool {name}_contains({name}* l, {elem_c} val) {{
    for (int i = 0; i < l->len; i++) if ({_eq(elem_c, "l->data[i]", "val")}) return true;
    return false;
}}
static int {name}_indexOf({name}* l, {elem_c} val) {{
    for (int i = 0; i < l->len; i++) if ({_eq(elem_c, "l->data[i]", "val")}) return i;
    return -1;
}}
static int {name}_lastIndexOf({name}* l, {elem_c} val) {{
    for (int i = l->len - 1; i >= 0; i--) if ({_eq(elem_c, "l->data[i]", "val")}) return i;
    return -1;
}}
static void {name}_reverse({name}* l) {{
    for (int i = 0, j = l->len - 1; i < j; i++, j--) {{
        {elem_c} tmp = l->data[i]; l->data[i] = l->data[j]; l->data[j] = tmp;
    }}
}}
static {name}* {name}_reversed({name}* l) {{
    {name}* r = {name}_new();
    for (int i = l->len - 1; i >= 0; i--) {name}_push(r, l->data[i]);
    return r;
}}
static void {name}_clear({name}* l) {{ l->len = 0; }}
static {elem_c} {name}_first({name}* l) {{ return l->data[0]; }}
static {elem_c} {name}_last({name}* l) {{ return l->data[l->len - 1]; }}
static {name}* {name}_slice({name}* l, int start, int end) {{
    {name}* r = {name}_new();
    if (start < 0) start = l->len + start;
    if (end < 0) end = l->len + end;
    if (start < 0) start = 0;
    if (end > l->len) end = l->len;
    for (int i = start; i < end; i++) {name}_push(r, l->data[i]);
    return r;
}}
static {name}* {name}_take({name}* l, int n) {{ return {name}_slice(l, 0, n); }}
static {name}* {name}_drop({name}* l, int n) {{ return {name}_slice(l, n, l->len); }}
static void {name}_insert({name}* l, int idx, {elem_c} val) {{
    {name}_push(l, val);
    for (int i = l->len - 1; i > idx; i--) l->data[i] = l->data[i-1];
    l->data[idx] = val;
}}
static void {name}_sort({name}* l) {{
    for (int i = 1; i < l->len; i++) {{
        {elem_c} key = l->data[i]; int j = i - 1;
        while (j >= 0 && {_gt(elem_c, "l->data[j]", "key")}) {{ l->data[j+1] = l->data[j]; j--; }}
        l->data[j+1] = key;
    }}
}}
static void {name}_extend({name}* l, {name}* other) {{
    for (int i = 0; i < other->len; i++) {name}_push(l, other->data[i]);
}}
static int {name}_findIndex({name}* l, bool (*pred)({elem_c})) {{
    for (int i = 0; i < l->len; i++) if (pred(l->data[i])) return i;
    return -1;
}}
static {name}* {name}_filter({name}* l, bool (*pred)({elem_c})) {{
    {name}* r = {name}_new();
    for (int i = 0; i < l->len; i++) if (pred(l->data[i])) {name}_push(r, l->data[i]);
    return r;
}}
static void {name}_forEach({name}* l, void (*fn)({elem_c})) {{
    for (int i = 0; i < l->len; i++) fn(l->data[i]);
}}
static {name}* {name}_copy({name}* l) {{
    {name}* r = {name}_new();
    for (int i = 0; i < l->len; i++) {name}_push(r, l->data[i]);
    return r;
}}
static {elem_c} {name}_min({name}* l) {{
    {elem_c} m = l->data[0];
    for (int i = 1; i < l->len; i++) if ({_lt(elem_c, "l->data[i]", "m")}) m = l->data[i];
    return m;
}}
static {elem_c} {name}_max({name}* l) {{
    {elem_c} m = l->data[0];
    for (int i = 1; i < l->len; i++) if ({_gt(elem_c, "l->data[i]", "m")}) m = l->data[i];
    return m;
}}
static bool {name}_any({name}* l, bool (*pred)({elem_c})) {{
    for (int i = 0; i < l->len; i++) if (pred(l->data[i])) return true;
    return false;
}}
static bool {name}_all({name}* l, bool (*pred)({elem_c})) {{
    for (int i = 0; i < l->len; i++) if (!pred(l->data[i])) return false;
    return true;
}}
static {elem_c} {name}_reduce({name}* l, {elem_c} init, {elem_c} (*fn)({elem_c}, {elem_c})) {{
    {elem_c} acc = init;
    for (int i = 0; i < l->len; i++) acc = fn(acc, l->data[i]);
    return acc;
}}
static int {name}_count({name}* l, {elem_c} val) {{
    int c = 0;
    for (int i = 0; i < l->len; i++) if ({_eq(elem_c, "l->data[i]", "val")}) c++;
    return c;
}}
static {name}* {name}_map({name}* l, {elem_c} (*fn)({elem_c})) {{
    {name}* r = {name}_new();
    for (int i = 0; i < l->len; i++) {name}_push(r, fn(l->data[i]));
    return r;
}}
static void {name}_fill({name}* l, {elem_c} val) {{
    for (int i = 0; i < l->len; i++) l->data[i] = val;
}}
static void {name}_removeAll({name}* l, {elem_c} val) {{
    int w = 0;
    for (int i = 0; i < l->len; i++) {{
        if (!({_eq(elem_c, "l->data[i]", "val")})) l->data[w++] = l->data[i];
    }}
    l->len = w;
}}
static void {name}_swap({name}* l, int i, int j) {{
    {elem_c} tmp = l->data[i]; l->data[i] = l->data[j]; l->data[j] = tmp;
}}
static void {name}_removeAt({name}* l, int idx) {{
    for (int i = idx; i < l->len - 1; i++) l->data[i] = l->data[i+1];
    l->len--;
}}
static {name}* {name}_sorted({name}* l) {{
    {name}* r = {name}_copy(l);
    {name}_sort(r);
    return r;
}}
static {name}* {name}_distinct({name}* l) {{
    {name}* r = {name}_new();
    for (int i = 0; i < l->len; i++) {{
        if (!{name}_contains(r, l->data[i])) {name}_push(r, l->data[i]);
    }}
    return r;
}}
"""
    # Numeric-specific methods
    if elem_c in ("int", "float", "double", "long"):
        methods += f"""
static {elem_c} {name}_sum({name}* l) {{
    {elem_c} s = 0;
    for (int i = 0; i < l->len; i++) s += l->data[i];
    return s;
}}
"""
    # String-specific methods: join
    if elem_c == "char*":
        methods += f"""
static char* {name}_join({name}* l, const char* sep) {{
    if (l->len == 0) return "";
    int total = 0;
    int seplen = (int)strlen(sep);
    for (int i = 0; i < l->len; i++) total += (int)strlen(l->data[i]);
    total += seplen * (l->len - 1);
    char* buf = (char*)malloc(total + 1);
    buf[0] = '\\0';
    for (int i = 0; i < l->len; i++) {{
        if (i > 0) strcat(buf, sep);
        strcat(buf, l->data[i]);
    }}
    return buf;
}}
"""
    gen.module.raw_sections.append(methods.strip())
