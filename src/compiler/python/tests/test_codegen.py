"""Unit tests for C code generation invariants.

These compile a btrc snippet all the way through the pipeline (lex -> parse ->
analyze -> IR gen -> optimize -> emit) and assert properties of the emitted C
text. They guard cross-cutting guarantees that no single stage owns -- most
importantly that the output is strict C11 with no compiler-specific extensions
(a hard project rule).
"""

import re

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def emit_c(source: str) -> str:
    """Run the full pipeline on a self-contained snippet, return emitted C.

    No stdlib is auto-included, so the output is exactly what the snippet
    lowers to -- which keeps these assertions precise and fast.
    """
    tokens = Lexer(source, "<test>").tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors, f"analyzer errors: {analyzed.errors}"
    ir_module = IRGenerator(analyzed).generate()
    ir_module = optimize(ir_module)
    return CEmitter().emit(ir_module)


# --- Strict-C11: no GNU/Clang extensions in emitted code ---

# Extensions that have previously leaked into output, or would if a future
# change reached for them. Each must never appear in emitted C.
_GNU_EXTENSIONS = [
    r"\b__auto_type\b",     # type inference (use the concrete type instead)
    r"\b__typeof__\b",      # typeof (same)
    r"\btypeof\b",          # GNU typeof spelling
    r"\(\{",                # statement expressions ({ ...; })
    r"\b__extension__\b",   # explicit GNU extension marker
]


def test_no_gnu_extensions_in_simple_program():
    c = emit_c("int main() { print(\"hi\"); return 0; }")
    for pat in _GNU_EXTENSIONS:
        assert not re.search(pat, c), f"emitted C contains GNU extension {pat!r}:\n{c}"


def test_return_temp_uses_concrete_int_type():
    """A non-trivial int return lowers to an `int` temp, never `__auto_type`.

    The temp exists to evaluate the return value before ARC scope-release runs
    (avoiding use-after-free); it must be declared with the function's real
    return type to stay strict C11.
    """
    src = """
    int doubler(int x) { return x * 2; }
    int main() { return doubler(21); }
    """
    c = emit_c(src)
    assert "__auto_type" not in c
    # The return temp for `x * 2` is declared `int`.
    assert re.search(r"\bint __btrc_ret_\d+ = ", c), c


def test_return_temp_uses_concrete_string_type():
    """A non-trivial string return lowers to a `char*` temp, not `__auto_type`."""
    src = """
    string greet(string n) { return n; }
    int main() { string g = greet("x"); return 0; }
    """
    c = emit_c(src)
    assert "__auto_type" not in c


def test_void_return_emits_bare_return():
    c = emit_c("void f() { return; } int main() { f(); return 0; }")
    assert "return;" in c
    assert "__auto_type" not in c


def test_main_promoted_to_int():
    """A `void main` is emitted returning int (C requires it)."""
    c = emit_c("void main() { print(\"x\"); }")
    assert re.search(r"\bint main\s*\(", c), c
