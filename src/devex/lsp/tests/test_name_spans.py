"""Name-span migration: features read each decl/member's own name_line/
name_col (populated by the parser) instead of the retired token-rescan
side-table.

Go-to-definition must land on the NAME token (not the leading keyword/type),
document-symbol selection ranges must cover the name, an interface method's
definition must land on the method name (the old MethodSig bug), and enum
values now carry real positions.
"""

from lsprotocol import types as lsp

from src.devex.lsp.definition import DefinitionMap, get_definition
from src.devex.lsp.symbols import get_document_symbols
from src.devex.lsp.tests.lsphelp import analyze, pos_of

SRC = """\
interface Shape {
    int area();
}

class Circle {
    public int radius;
    public int area() { return self.radius; }
}

enum Color { RED, GREEN, BLUE };

int compute(int n) { return n; }

int main() {
    Circle c = Circle();
    int a = c.area();
    Color k = RED;
    int z = compute(3);
    return z;
}
"""


def _def_at(src, needle, occurrence=1, offset=0):
    res = analyze(src)
    return get_definition(res, pos_of(src, needle, occurrence, offset))


def _char_at(src, needle, occurrence=1):
    """0-based column where *needle* starts (its name token)."""
    return pos_of(src, needle, occurrence).character


# --- go-to-definition lands on the NAME, not the keyword/type ----------------


def test_class_definition_lands_on_name_not_keyword():
    loc = _def_at(SRC, "Circle()", offset=2)
    assert loc is not None
    # `class Circle` -> Circle starts after the `class ` keyword.
    assert loc.range.start.line == 4  # 0-based: source line 5
    assert loc.range.start.character == _char_at(SRC, "Circle", 1)
    # Not the `class` keyword column (col 0).
    assert loc.range.start.character > 0


def test_function_definition_lands_on_name_not_return_type():
    loc = _def_at(SRC, "compute(3)", offset=2)
    assert loc is not None
    # `int compute(...)` -> name, not the `int` return type at col 0.
    assert loc.range.start.character == _char_at(SRC, "compute", 1)
    assert loc.range.start.character > 0


def test_method_definition_lands_on_name():
    loc = _def_at(SRC, "c.area", offset=2)
    assert loc is not None
    # `public int area()` -> the `area` name token.
    assert loc.range.start.line == 6  # 0-based: source line 7
    assert loc.range.start.character == _char_at(SRC, "area", 2)  # 2nd `area` = the def


def test_field_definition_lands_on_name():
    src = SRC.replace("int a = c.area();", "int a = c.area();\n    int rr = c.radius;")
    loc = _def_at(src, "c.radius", offset=2)
    assert loc is not None
    # `public int radius;` -> the `radius` name token, not the `int` type.
    assert loc.range.start.character == _char_at(src, "radius", 1)
    assert loc.range.start.character > 0


def test_interface_method_definition_lands_on_method_name():
    # The MethodSig name span used to be wrong; it now lands on the method name.
    dmap = DefinitionMap.from_result(analyze(SRC))
    pos = dmap.method_defs.get(("Shape", "area"))
    assert pos is not None
    _file, line, col = pos
    assert line == 2  # 1-based source line of `int area();`
    # `    int area();` -> `area` at col 9, NOT the `int` at col 5.
    assert col == SRC.split("\n")[1].index("area") + 1


def test_enum_value_has_real_distinct_position():
    dmap = DefinitionMap.from_result(analyze(SRC))
    red = dmap.enum_defs.get("RED")
    green = dmap.enum_defs.get("GREEN")
    assert red is not None and green is not None
    # Each value maps to its OWN variant position, not the enum declaration.
    assert red[1:] != green[1:]
    enum_line = SRC.split("\n")[9]  # `enum Color { RED, GREEN, BLUE };`
    assert red[2] == enum_line.index("RED") + 1
    assert green[2] == enum_line.index("GREEN") + 1


def test_enum_value_go_to_definition():
    loc = _def_at(SRC, "= RED", offset=2)
    assert loc is not None
    # Jumps to the RED variant on the enum line (0-based line 9).
    assert loc.range.start.line == 9
    assert loc.range.start.character == _char_at(SRC, "RED", 1)


# --- document-symbol selection ranges cover the NAME -------------------------


def _symbol(syms, name):
    for s in syms:
        if s.name == name:
            return s
    return None


def test_document_symbol_selection_ranges_cover_names():
    syms = get_document_symbols(analyze(SRC))

    cls = _symbol(syms, "Circle")
    assert cls is not None
    # Selection is the name `Circle`, not the `class` keyword at col 0.
    assert cls.selection_range.start.character == _char_at(SRC, "Circle", 1)
    assert cls.selection_range.end.character == cls.selection_range.start.character + len("Circle")

    fn = _symbol(syms, "compute")
    assert fn is not None
    assert fn.selection_range.start.character == _char_at(SRC, "compute", 1)
    assert fn.selection_range.start.character > 0

    # Method child selects the method name.
    method = _symbol(cls.children, "area")
    assert method is not None
    assert method.selection_range.start.line == 6
    assert method.selection_range.start.character == _char_at(SRC, "area", 2)

    # Field child selects the field name.
    field = _symbol(cls.children, "radius")
    assert field is not None
    assert field.selection_range.start.character == _char_at(SRC, "radius", 1)


def test_document_symbol_enum_members_have_distinct_ranges():
    syms = get_document_symbols(analyze(SRC))
    enum = _symbol(syms, "Color")
    assert enum is not None
    red = _symbol(enum.children, "RED")
    green = _symbol(enum.children, "GREEN")
    assert red is not None and green is not None
    # Each member selects its own name, so the ranges differ.
    assert red.selection_range.start.character != green.selection_range.start.character
    assert red.selection_range.start.character == _char_at(SRC, "RED", 1)


def test_document_symbol_struct_fields_have_ranges():
    src = "struct Pt { int x; int y; };\nint main() { return 0; }\n"
    syms = get_document_symbols(analyze(src))
    pt = _symbol(syms, "Pt")
    assert pt is not None
    assert pt.selection_range.start.character == src.index("Pt")
    fx = _symbol(pt.children, "x")
    fy = _symbol(pt.children, "y")
    assert fx is not None and fy is not None
    assert fx.selection_range.start.character == src.index(" x;") + 1
    assert fy.selection_range.start.character == src.index(" y;") + 1


def test_document_symbol_constructor_kind_uses_ast_marker():
    src = (
        "class NamedMethod { public int NamedMethod() { return 1; } }\nclass Constructed { public Constructed() {} }\n"
    )
    symbols = get_document_symbols(analyze(src))
    named_method = _symbol(_symbol(symbols, "NamedMethod").children, "NamedMethod")
    constructor = _symbol(_symbol(symbols, "Constructed").children, "Constructed")

    assert named_method.kind == lsp.SymbolKind.Method
    assert constructor.kind == lsp.SymbolKind.Constructor


def test_struct_definition_wins_over_later_forward_declaration():
    src = "struct Tail { int value; };\nstruct Tail;\nint main() { Tail value = {1}; return value.value; }\n"
    location = get_definition(analyze(src), pos_of(src, "Tail value", offset=1))

    assert location is not None
    assert location.range.start.line == 0
