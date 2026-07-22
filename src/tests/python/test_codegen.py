"""Unit tests for C code generation invariants.

These compile a btrc snippet all the way through the pipeline (lex -> parse ->
analyze -> IR gen -> optimize -> emit) and assert properties of the emitted C
text. They guard cross-cutting guarantees that no single stage owns -- most
importantly that the output is strict C11 with no compiler-specific extensions
(a hard project rule).
"""

import re

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
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
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors, f"analyzer errors: {analyzed.errors}"
    ir_module = IRGenerator(analyzed).generate()
    ir_module = optimize(ir_module)
    return CEmitter().emit(ir_module)


def test_switch_fallthrough_metadata_survives_normal_and_generic_lowering():
    emitted = emit_c(
        """
        int ordinary(int value) {
            int result = 0;
            switch (value) {
                case 1: result += 1;
                case 2: result += 2; break;
            }
            return result;
        }
        class Flow<T> {
            public Flow() {}
            public int run(int value) {
                int result = 0;
                switch (value) {
                    case 1: result += 1;
                    case 2: result += 2; break;
                }
                return result;
            }
        }
        int main() {
            Flow<int> flow = new Flow<int>();
            return ordinary(1) + flow.run(1);
        }
        """
    )

    ordinary = emitted.split("int ordinary(int value) {", 1)[1].split("\n}", 1)[0]
    generic = emitted.split(
        "static int btrc_Flow_int_run(btrc_Flow_int* self, int value) {",
        1,
    )[1].split("\n}", 1)[0]
    assert ordinary.count("/* fall through */") == 1
    assert generic.count("/* fall through */") == 1


# --- Strict-C11: no GNU/Clang extensions in emitted code ---

# Extensions that have previously leaked into output, or would if a future
# change reached for them. Each must never appear in emitted C.
_GNU_EXTENSIONS = [
    r"\b__auto_type\b",  # type inference (use the concrete type instead)
    r"\b__typeof__\b",  # typeof (same)
    r"\btypeof\b",  # GNU typeof spelling
    r"\(\{",  # statement expressions ({ ...; })
    r"\b__extension__\b",  # explicit GNU extension marker
]


def test_no_gnu_extensions_in_simple_program():
    c = emit_c('int main() { print("hi"); return 0; }')
    for pat in _GNU_EXTENSIONS:
        assert not re.search(pat, c), f"emitted C contains GNU extension {pat!r}:\n{c}"


def test_return_without_managed_locals_needs_no_temp():
    """A non-trivial return in a function with no ARC-managed locals lowers to a
    plain `return expr;` — no temp is needed, so none is emitted."""
    src = """
    int doubler(int x) { return x * 2; }
    int main() { return doubler(21); }
    """
    c = emit_c(src)
    assert "__auto_type" not in c
    assert "__btrc_ret" not in c, "no temp should be emitted when nothing to release"
    assert "return (x * 2);" in c


def test_return_temp_with_managed_local_uses_concrete_type():
    """When a function HAS an ARC-managed local, the return value is stashed in a
    temp (so the local can be released after the value is computed). That temp
    must use the function's concrete C return type — never `__auto_type` (a GNU
    extension) and never the expression's analyzer type (which drops pointer
    depth: a class type `Box` is C type `Box*`).
    """
    src = """
    class Box { public int v; public Box(int v) { self.v = v; } public int get() { return self.v; } }
    int compute() {
        Box b = new Box(21);   // managed local -> released at scope exit
        return b.get() * 2;    // non-trivial return -> needs a temp
    }
    int main() { return compute(); }
    """
    c = emit_c(src)
    assert "__auto_type" not in c
    # A temp IS emitted here, and it is typed `int` (compute's return type).
    assert re.search(r"\bint __btrc_ret_\d+ = ", c), c


def test_return_pointer_temp_uses_pointer_type():
    """A method returning a class type returns a C pointer; when a temp is needed
    (managed local present) it must be the pointer type, not the bare struct."""
    src = """
    class Box { public int v; public Box(int v) { self.v = v; } }
    class Factory {
        public Box make() {
            Box scratch = new Box(1);   // managed local forces a return temp
            return new Box(scratch.v + 1);
        }
    }
    int main() { Factory f = new Factory(); Box b = f.make(); return 0; }
    """
    c = emit_c(src)
    assert "__auto_type" not in c
    # If a return temp is emitted for make(), it is `Box*` (pointer), never `Box`.
    assert not re.search(r"\bBox __btrc_ret_\d+ = ", c), c


def test_void_return_emits_bare_return():
    c = emit_c("void f() { return; } int main() { f(); return 0; }")
    assert "return;" in c
    assert "__auto_type" not in c


def test_main_promoted_to_int():
    """A `void main` is emitted returning int (C requires it)."""
    c = emit_c('void main() { print("x"); }')
    assert re.search(r"\bint main\s*\(", c), c
