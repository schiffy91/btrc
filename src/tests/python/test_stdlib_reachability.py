"""The stdlib reachability pass keeps every callable a program can name and prunes the rest."""

from __future__ import annotations

from src.compiler.python.frontend.sources import CompilerStdlibSource
from src.compiler.python.ir.lowering.reachability import IMPLIED_METHOD_NAMES, StdlibReachability
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import ClassDecl, FunctionDecl, MethodDecl

STDLIB = """
interface Shape { int area(); }
class Square implements Shape {
    public int side;
    public Square(int side) { self.side = side; }
    public int area() { return self.side * self.side; }
    public int perimeter() { return 4 * self.side; }
}
class Tools {
    class int twice(int x) { return Tools.helper(x) * 2; }
    class int helper(int x) { return x; }
    class int unused(int x) { return x + 1; }
    public string toString() { return "tools"; }
}
class Orphan { public int nothing() { return 0; } }
int lonely() { return 1; }
"""
USER = """
int main() { Shape s = Square(2); return s.area() + Tools.twice(1); }
"""


def _program():
    stdlib = Parser(Lexer(STDLIB, "<stdlib>").tokenize()).parse()
    for declaration in stdlib.declarations:
        declaration.source_file = CompilerStdlibSource("<stdlib>")
    user = Parser(Lexer(USER, "<user>").tokenize()).parse()
    return stdlib.declarations + user.declarations


def _by_name(declarations):
    return {getattr(d, "name", None): d for d in declarations}


def test_names_close_over_identifiers_members_types_parents_and_signatures() -> None:
    declarations = _program()
    reach = StdlibReachability(declarations)
    named = _by_name(declarations)
    assert not StdlibReachability.is_stdlib_declaration(named["main"]) and StdlibReachability.is_stdlib_declaration(
        named["Square"]
    )
    assert reach.reaches(named["main"])
    assert reach.reaches(named["Shape"]) and reach.reaches(named["Square"])  # named, and implements a named interface
    assert reach.reaches(named["Tools"])
    assert not reach.reaches(named["Orphan"]) and not reach.reaches(named["lonely"])


def test_methods_prune_by_name_but_keep_constructors_operators_and_implied_names() -> None:
    declarations = _program()
    reach = StdlibReachability(declarations)
    named = _by_name(declarations)
    square: ClassDecl = named["Square"]
    tools: ClassDecl = named["Tools"]
    methods = {m.name: m for m in square.members if isinstance(m, MethodDecl)}
    assert reach.lowers_method(square, methods["area"])  # interface signature names it
    assert reach.lowers_method(square, methods["Square"])  # constructor
    assert not reach.lowers_method(square, methods["perimeter"])
    tool_methods = {m.name: m for m in tools.members if isinstance(m, MethodDecl)}
    assert reach.lowers_method(tools, tool_methods["twice"])
    assert reach.lowers_method(tools, tool_methods["helper"])  # reached through twice's body
    assert not reach.lowers_method(tools, tool_methods["unused"])
    assert reach.lowers_method(tools, tool_methods["toString"])  # lowering-implied
    selected = reach.selected_callables(tools, None)
    assert ("method", "twice") in selected and ("method", "unused") not in selected
    assert reach.selected_callables(tools, frozenset({("method", "unused")})) == frozenset()
    user_main: FunctionDecl = named["main"]
    assert reach.reaches(user_main)


def test_always_lowered_covers_operators_generics_and_the_implied_set() -> None:
    def method(name: str, **fields) -> MethodDecl:
        return MethodDecl(name=name, return_type=None, **fields)

    assert StdlibReachability.always_lowered(method("__eq__"))
    assert StdlibReachability.always_lowered(method("size"))
    assert StdlibReachability.always_lowered(method("pick", generic_params=["T"]))
    assert not StdlibReachability.always_lowered(method("perimeter"))
    assert "iterLen" in IMPLIED_METHOD_NAMES and "toString" in IMPLIED_METHOD_NAMES


def test_mentioned_names_reads_the_class_parent_and_interfaces() -> None:
    declarations = _program()
    names: set[str] = set()
    StdlibReachability.mentioned_names(_by_name(declarations)["Square"], names)
    assert {"Shape", "side", "int"} <= names


def test_both_compilers_carry_the_same_implied_method_names() -> None:
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "src/compiler/btrc/ir/lowering/Reachability.btrc"
    text = source.read_text(encoding="utf-8")
    body = text[text.index("class bool impliedMethodName(") :]
    body = body[: body.index("return implied.has(name);")]
    assert set(re.findall(r'built\.put\("([A-Za-z0-9_]+)", true\);', body)) == set(IMPLIED_METHOD_NAMES)


TAGGED_STDLIB = """
struct Storage { int slots; };
class Buffers {
    class bool tryOpen(struct Storage** output) { return true; }
}
class Element { public int value; public Element(int value) { self.value = value; } }
class Box<T> {
    public T item;
    public Box(T item) { self.item = item; }
}
class Hidden { public int nothing() { return 0; } }
"""
TAGGED_USER = """
int main() { struct Storage* storage = null; Buffers.tryOpen(&storage); return 0; }
"""


def _tagged_program():
    stdlib = Parser(Lexer(TAGGED_STDLIB, "<stdlib>").tokenize()).parse()
    for declaration in stdlib.declarations:
        declaration.source_file = CompilerStdlibSource("<stdlib>")
    user = Parser(Lexer(TAGGED_USER, "<user>").tokenize()).parse()
    return stdlib.declarations + user.declarations


def test_struct_tagged_types_reach_the_bare_declaration() -> None:
    """`struct Storage**` spells Storage; its forward and definition must survive."""

    declarations = _tagged_program()
    named = _by_name(declarations)
    reach = StdlibReachability(declarations)
    assert reach.reaches(named["Buffers"]) and reach.reaches(named["Storage"])
    assert not reach.reaches(named["Hidden"])


def test_generic_instance_type_arguments_are_roots() -> None:
    """A Box<Element> the analyzer inferred reaches Box and Element without either being spelled."""

    declarations = _tagged_program()
    named = _by_name(declarations)
    box = named["Box"]
    element_type = next(
        member.params[0].type for member in box.members if isinstance(member, MethodDecl) and member.is_constructor
    )
    element_type = type(element_type)(base="Element", line=0, col=0)
    reach = StdlibReachability(declarations, [box], (), [element_type])
    assert reach.reaches(box) and reach.reaches(named["Element"])
    assert reach.lowers_method(named["Element"], next(m for m in named["Element"].members if isinstance(m, MethodDecl)))
    assert not reach.reaches(named["Hidden"])
