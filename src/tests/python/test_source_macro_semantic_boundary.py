"""Function-like source macros cannot erase typed call boundaries."""

from __future__ import annotations

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.source_macro_queries import source_macro_expands_to_any
from src.compiler.python.source_macros import source_symbol_directive


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<source-macro-boundary>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "#define CALL(fn,value) fn(value)\n"
            "class Item {} void consume(Item value) {} "
            "int main(){ Item owner=new Item(); CALL(consume,owner); return 0; }",
            "cannot accept callable argument 1",
        ),
        (
            "#define CALL(fn,value) (fn)(value)\n"
            "void consumeInt(int value) {} "
            "int main(){ __fn_ptr<void, int> fn=consumeInt; "
            "CALL((__fn_ptr<void, int>)fn,1); return 0; }",
            "cannot accept callable argument 1",
        ),
        (
            "#define CALL(fn,value) ((void (*)(int))(fn))(value)\n"
            "void consumeInt(int value) {} "
            "int main(){ __fn_ptr<void, int> fn=consumeInt; "
            "CALL((void*)fn,1); return 0; }",
            "cannot accept callable argument 1",
        ),
        (
            "#define PASS(value) inspect(value)\nextern void inspect(void* value); "
            "class Item {} int main(){ Item owner=new Item(); "
            "PASS((void*)owner); return 0; }",
            "managed or opaque-borrow argument 1",
        ),
        (
            "#define INNER() owner\n#define OUTER() INNER()\n"
            "class Item {} int main(){ Item owner=new Item(); OUTER(); return 0; }",
            "cannot capture managed or callable value 'owner'",
        ),
        (
            "#define TAKE(value) consume(value)\nclass Item {} void consume(Item value) {} int main(){ return 0; }",
            "Language callable 'consume' requires semantic call analysis",
        ),
        (
            "#define APPLY(value) value.take()\nclass Item { public void take() {} } int main(){ return 0; }",
            "Language method 'take'",
        ),
        (
            "#define CREATE() Item()\nclass Item {} int main(){ return 0; }",
            "Language type 'Item'",
        ),
        (
            "#define PASS(value) (value)\n"
            "class Box { public void forward<T>(T value) { PASS(value); } } "
            "int main(){ return 0; }",
            "managed or opaque-borrow argument 1",
        ),
    ),
)
def test_unsafe_macro_semantic_boundaries_are_rejected(
    source: str,
    diagnostic: str,
) -> None:
    assert any(diagnostic in error for error in _errors(source))


def test_scalar_and_exact_read_only_hosted_wrappers_remain_valid() -> None:
    source = """
        #define SQUARE(value) ((value) * (value))
        #define LENGTH(value) strlen(value)
        #define FREE_IDENTITY(free) free
        int main() {
            string text = "abc";
            return SQUARE(3) == 9 && LENGTH(text) == 3 ? 0 : 1;
        }
    """
    assert _errors(source) == []


def test_latest_redefinition_controls_the_hoisted_macro_namespace() -> None:
    latest_safe = """
        #define WRAP(value) (value)
        #define WRAP(value) strlen(value)
        int main() { string text = "abc"; return WRAP(text) == 3 ? 0 : 1; }
    """
    assert _errors(latest_safe) == []

    latest_unmodeled = """
        #define WRAP(value) strlen(value)
        int before(string text) { return WRAP(text); }
        #define WRAP(value) (value)
        int after(string text) { return WRAP(text).length(); }
        int main() { return 0; }
    """
    errors = _errors(latest_unmodeled)
    assert sum("managed or opaque-borrow argument 1" in error for error in errors) == 2


def test_undef_removes_the_final_active_definition() -> None:
    source = """
        #define WRAP(value) strlen(value)
        #undef WRAP
        int main() { string text = "abc"; return WRAP(text); }
    """
    assert not any("Source macro 'WRAP'" in error for error in _errors(source))


def test_context_identifier_query_is_transitive_and_cycle_safe() -> None:
    outer = source_symbol_directive("#define OUTER() INNER()")
    inner = source_symbol_directive("#define INNER() __LINE__")
    left = source_symbol_directive("#define LEFT() RIGHT()")
    right = source_symbol_directive("#define RIGHT() LEFT()")
    assert outer is not None and inner is not None
    assert left is not None and right is not None
    definitions = {item.name: item for item in (outer, inner, left, right)}

    assert source_macro_expands_to_any("OUTER", definitions, frozenset({"__LINE__"}))
    assert not source_macro_expands_to_any("LEFT", definitions, frozenset({"__LINE__"}))
