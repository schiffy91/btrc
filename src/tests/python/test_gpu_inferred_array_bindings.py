"""Semantic contracts for inferred array-returning GPU bindings."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import FunctionDecl, VarDeclStmt


def _analyze(source: str):
    program = Parser(Lexer(source, "<gpu-inferred-array>").tokenize()).parse()
    return program, SemanticAnalyzer().analyze(program)


def _local(program, name: str) -> VarDeclStmt:
    main = next(
        declaration
        for declaration in program.declarations
        if isinstance(declaration, FunctionDecl) and declaration.name == "main"
    )
    return next(
        statement for statement in main.body.statements if isinstance(statement, VarDeclStmt) and statement.name == name
    )


def test_inferred_gpu_result_retains_owned_array_storage() -> None:
    program, analyzed = _analyze(
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "int main() { int[] values = {3, 5}; var output = copy(values); "
        "output = copy(output); return output[1] == 5 ? 0 : 1; }"
    )

    assert analyzed.errors == []
    assert _local(program, "output").type.is_array


def test_inferred_scalar_only_gpu_result_is_one_element_array_storage() -> None:
    program, analyzed = _analyze(
        "@gpu int[] fill(int value) { return value; } "
        "int main() { var output = fill(7); return output[0] == 7 ? 0 : 1; }"
    )

    assert analyzed.errors == []
    assert _local(program, "output").type.is_array


def test_gpu_result_cannot_initialize_pointer_valued_array_alias() -> None:
    _, analyzed = _analyze(
        "typedef int[] Values; "
        "@gpu int[] copy(int[] values) { int i = gpu_id(); return values[i]; } "
        "int main() { int[] values = {3, 5}; Values output = copy(values); return 0; }"
    )

    assert any("pointer-valued array alias" in error for error in analyzed.errors)


def test_brace_initialized_var_is_rejected_before_invalid_c_lowering() -> None:
    _, analyzed = _analyze("int main() { var values = {1, 2}; return 0; }")

    assert any("Cannot infer array storage for 'var'" in error for error in analyzed.errors)
