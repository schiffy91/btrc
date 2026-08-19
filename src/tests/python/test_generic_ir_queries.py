"""Generic specialization is planning for the ordinary lowering stack."""

from types import SimpleNamespace

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.generics import GenericSpecializer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import Program, TypeExpr


def _analyze(source: str) -> AnalyzedProgram:
    program = Parser(Lexer(source, "<generic-specialization>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    return analyzed


def test_class_specializer_produces_an_immutable_view_for_ordinary_lowerers() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
        }
        int main() {
            Box<int> value = new Box<int>(7);
            return value.value;
        }
        """
    )

    views = list(GenericSpecializer(analyzed, TypeIdentity()).class_views())

    assert len(views) == 1
    view = views[0]
    assert view.base_name == "Box"
    assert view.type_arguments == (TypeExpr(base="int"),)
    assert view.substitution.resolve(TypeExpr(base="T")) == TypeExpr(base="int")
    assert view.symbol == "btrc_Box_int"


def test_method_specializer_combines_class_and_method_bindings() -> None:
    method = SimpleNamespace(generic_params=["U"])
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={
            "Box": SimpleNamespace(
                generic_params=["T"],
                methods={"convert": method},
            )
        },
        generic_method_instances={
            ("Box", "convert"): [
                ((TypeExpr(base="int"),), (TypeExpr(base="string"),)),
            ]
        },
    )

    views = list(GenericSpecializer(analyzed, TypeIdentity()).method_views())

    assert len(views) == 1
    view = views[0]
    assert view.base_name == "Box.convert"
    assert view.type_arguments == (
        TypeExpr(base="int"),
        TypeExpr(base="string"),
    )
    assert view.substitution.resolve(TypeExpr(base="T")) == TypeExpr(base="int")
    assert view.substitution.resolve(TypeExpr(base="U")) == TypeExpr(base="string")


def test_generic_methods_are_lowered_into_the_same_structured_module() -> None:
    analyzed = _analyze(
        """
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T get() { return self.value; }
        }
        int main() {
            Box<int> value = new Box<int>(7);
            return value.get();
        }
        """
    )

    module = IRLowerer(analyzed).lower()
    function_names = {function.name for function in module.function_defs}

    assert any(name.startswith("btrc_Box_int") for name in function_names)
