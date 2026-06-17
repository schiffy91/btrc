#!/usr/bin/env python3
"""Generate the self-hosted btrc AST as a FAT TAGGED NODE.

btrc has no dynamic dispatch / downcast / interface-typed variables, so the
Python compiler's polymorphic class-hierarchy AST cannot be walked in btrc.
Instead we emit ONE `Node` struct with a `kind` (NodeKind) tag and the union of
all constructors' fields, plus a `canon(depth)` method that reproduces the
reference canonical AST dump (src/compiler/btrc/verify_ast.py) byte-for-byte.

All node-typed fields collapse to `Node`; node lists to `Vector<Node>`; string
lists to `Vector<string>`; scalars stay int/bool/string/float. The only field
name whose type differs across constructors is `value` (Node vs int/float/bool/
string), which gets per-type backing fields (value_node/value_int/...).

Output: src/compiler/btrc/node.btrc  (via `make ast-generate-btrc`).
Reuses helpers from asdl_btrc.py; does not modify the Python compiler.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asdl_btrc as B  # noqa: E402
from asdl_parser import parse_file  # noqa: E402

SCALARS = {"int", "bool", "string", "float"}


def fat(btrc_type: str):
    """(category, declared_btrc_type) for a field's fat-node representation."""
    if btrc_type in SCALARS:
        return ("scalar", btrc_type)
    if btrc_type.startswith("List<"):
        inner = btrc_type[len("List<"):-1]
        return ("strlist", "Vector<string>") if inner == "string" else ("nodelist", "Vector<Node>")
    return ("node", "Node")


def variant_suffix(cat: str, decl: str) -> str:
    if cat == "scalar":
        return decl  # int/bool/string/float
    return {"node": "node", "nodelist": "nlist", "strlist": "slist"}[cat]


def build_plan(module):
    """Return (constructors, field_decls, per_kind) where:
      constructors = [(ctor, fields_incl_attrs)]
      field_decls  = ordered [(backing_name, declared_type, init)]
      per_kind     = {kind_name: [(asdl_name, backing_name, cat, decl)]}
    """
    name_map = B._build_type_name_map(module)
    ctors = []
    for t in module.types:
        if B._is_simple_enum(t):
            continue
        for c in t.constructors:
            ctors.append((c, list(c.fields) + list(t.attributes)))

    # Collect every field name -> set of (cat, decl) across constructors.
    seen = {}
    for _c, fields in ctors:
        for f in fields:
            cat, decl = fat(B._btrc_type(f, name_map))
            seen.setdefault(B._safe_name(f.name), set()).add((cat, decl))

    conflicted = {n for n, s in seen.items() if len(s) > 1}

    # A string field that is optional in EVERY use becomes a nullable `string?`
    # so canon can emit `nil` when absent (matching the Python AST's None).
    str_opt = {}      # name -> [bools]  (opt flag per use, string fields only)
    for _c, fields in ctors:
        for f in fields:
            cat, decl = fat(B._btrc_type(f, name_map))
            if cat == "scalar" and decl == "string":
                str_opt.setdefault(B._safe_name(f.name), []).append(bool(f.opt))
    nullable_str = {n for n, flags in str_opt.items() if all(flags) and n not in conflicted}

    def backing(name, cat, decl):
        return f"{name}_{variant_suffix(cat, decl)}" if name in conflicted else name

    # Ordered, de-duplicated backing field declarations.
    decls = {}  # backing_name -> (declared_type, init)
    order = []
    per_kind = {}
    for c, fields in ctors:
        kind = f"NK_{B._to_screaming_snake(c.name)}"
        entries = []
        for f in fields:
            name = B._safe_name(f.name)
            cat, decl = fat(B._btrc_type(f, name_map))
            bn = backing(name, cat, decl)
            optstr = bn in nullable_str
            if bn not in decls:
                if optstr:
                    decls[bn] = ("string?", "null")
                else:
                    init = {"int": "0", "bool": "false", "string": '""', "float": "0.0",
                            "Vector<Node>": "[]", "Vector<string>": "[]", "Node": "null"}[decl]
                    decls[bn] = (decl, init)
                order.append(bn)
            entries.append((f.name, bn, cat, decl, optstr))
        per_kind[kind] = entries
    return ctors, [(n, *decls[n]) for n in order], per_kind


def value_dump(cat: str, decl: str, backing: str, optstr: bool) -> str:
    """btrc expression dumping `self.<backing>` at depth `d` (a local var)."""
    if cat == "scalar":
        if optstr:
            return f"canonOptStr(self.{backing})"
        fn = {"int": "canonInt", "bool": "canonBool", "string": "canonStr", "float": "canonFloat"}[decl]
        return f"{fn}(self.{backing})"
    if cat == "node":
        return f"canonNode(self.{backing}, d + 1)"
    if cat == "nodelist":
        return f"canonNodeList(self.{backing}, d + 1)"
    return f"canonStrList(self.{backing}, d + 1)"


def generate(module) -> str:
    L: list[str] = [
        "/* Self-hosted btrc AST — fat tagged node.",
        " *",
        " * Auto-generated from src/language/ast/ast.asdl by gen_btrc_ast.py.",
        " * DO NOT EDIT BY HAND. btrc lacks dynamic dispatch/downcast, so the AST",
        " * is one Node with a `kind` tag + the union of all fields.",
        " */",
        "",
    ]
    B._emit_node_kind_enum(module, L)
    B._emit_simple_enums(module, L)

    ctors, decls, per_kind = build_plan(module)

    # --- fat Node class ---
    L.append("class Node {")
    L.append("    public int kind;")
    for name, decl, _init in decls:
        L.append(f"    public {decl} {name};")
    L.append("")
    L.append("    public Node() {")
    L.append("        self.kind = NK_NONE;")
    for name, _decl, init in decls:
        L.append(f"        self.{name} = {init};")
    L.append("    }")
    L.append("")
    # canon(depth): per-kind field emission in ASDL order.
    L.append("    public string canon(int d) {")
    first = True
    for c, _fields in ctors:
        kind = f"NK_{B._to_screaming_snake(c.name)}"
        kw = "if" if first else "} else if"
        first = False
        L.append(f"        {kw} (self.kind == {kind}) {{")
        L.append(f'            string out = "({c.name}";')
        for asdl_name, backing, cat, decl, optstr in per_kind[kind]:
            vd = value_dump(cat, decl, backing, optstr)
            L.append(f'            out = out + "\\n" + spaces(2 * (d + 1)) + "{asdl_name}=" + {vd};')
        L.append('            return out + ")";')
    L.append("        }")
    L.append('        return "(Unknown)";')
    L.append("    }")
    L.append("}")
    L.append("")

    # --- canon formatting helpers ---
    L.append(_HELPERS)
    return "\n".join(L)


_HELPERS = r'''string spaces(int n) {
    string s = "";
    int i = 0;
    while (i < n) { s = s + " "; i = i + 1; }
    return s;
}

string canonInt(int v) { return Strings.fromInt(v); }
string canonBool(bool b) { if (b) { return "true"; } return "false"; }
string canonFloat(float f) { return f"{f}"; }

string canonStr(string s) {
    string out = "\"";
    int i = 0;
    int n = s.length();
    while (i < n) {
        char c = s[i];
        if (c == '\\') { out = out + "\\\\"; }
        else if (c == '"') { out = out + "\\\""; }
        else if (c == '\n') { out = out + "\\n"; }
        else if (c == '\r') { out = out + "\\r"; }
        else if (c == '\t') { out = out + "\\t"; }
        else { out = out + f"{c}"; }
        i = i + 1;
    }
    return out + "\"";
}

string canonOptStr(string? s) {
    if (s == null) { return "nil"; }
    return canonStr(s);
}

string canonNode(Node node, int d) {
    if (node == null) { return "nil"; }
    return node.canon(d);
}

string canonNodeList(Vector<Node> xs, int d) {
    if (xs.len == 0) { return "[]"; }
    string out = "[\n";
    int i = 0;
    while (i < xs.len) {
        out = out + spaces(2 * (d + 1)) + xs.get(i).canon(d + 1);
        if (i < xs.len - 1) { out = out + "\n"; }
        i = i + 1;
    }
    return out + "\n" + spaces(2 * d) + "]";
}

string canonStrList(Vector<string> xs, int d) {
    if (xs.len == 0) { return "[]"; }
    string out = "[\n";
    int i = 0;
    while (i < xs.len) {
        out = out + spaces(2 * (d + 1)) + canonStr(xs.get(i));
        if (i < xs.len - 1) { out = out + "\n"; }
        i = i + 1;
    }
    return out + "\n" + spaces(2 * d) + "]";
}
'''


def main():
    if len(sys.argv) < 2:
        print("usage: gen_btrc_ast.py <ast.asdl>", file=sys.stderr)
        sys.exit(1)
    print(generate(parse_file(sys.argv[1])))


if __name__ == "__main__":
    main()
