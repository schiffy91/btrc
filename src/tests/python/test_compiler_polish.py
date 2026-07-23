"""Compiler correctness/soundness polish fixes.

Each test pins one of five fixes:

* CMP-19  generic mangling now encodes pointer depth, so ``Vector<int*>`` and
          ``Vector<int>`` no longer collide on one C struct/function set.
* CMP-27  ``_has_return`` descends into loop bodies, so a function whose only
          ``return`` lives inside a ``for``/``for-in``/``do-while`` is no longer
          falsely flagged "missing return".
* CMP-29  ``_compute_cyclable_flags`` marks exactly the classes that can reach
          themselves (participate in a cycle); a class that merely points into
          someone else's cycle stays non-cyclable.
* CMP-21  ``extern``/``static``/``volatile`` type qualifiers on globals survive
          to the emitter instead of being collapsed to ``static``.
* CMP-26  ``catch (T e)`` stores the annotation on the AST and the analyzer
          validates it (string payload) instead of silently discarding it.
"""

import subprocess
import sys
from pathlib import Path

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

REPO = Path(__file__).resolve().parents[3]


def _analyze(source: str):
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    return SemanticAnalyzer().analyze(program)


def _errors(source: str) -> list[str]:
    return _analyze(source).errors


def _compile(tmp_path, source, run=False):
    """Run the full CLI pipeline, optionally gcc-compile and execute."""
    src = tmp_path / "t.btrc"
    src.write_text(source)
    out_c = tmp_path / "t.c"
    r = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(src), "-o", str(out_c)],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={"BTRC_CACHE_DIR": str(tmp_path / "cache"), "PATH": "/usr/bin:/bin"},
    )
    if not run:
        return r, out_c
    assert r.returncode == 0, r.stderr
    exe = tmp_path / "t"
    g = subprocess.run(
        ["cc", "-std=c11", "-pedantic-errors", str(out_c), "-o", str(exe), "-lm", "-lpthread"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert g.returncode == 0, g.stderr
    run_res = subprocess.run([str(exe)], capture_output=True, text=True)
    return run_res, out_c


# ---------------------------------------------------------------------------
# CMP-19: pointer depth in generic mangling
# ---------------------------------------------------------------------------


class TestPointerDepthMangling:
    SRC = """
        import std.vector;

        int main() {
            Vector<int> a = new Vector<int>();
            a.push(10);
            a.push(20);
            Vector<int*> b = new Vector<int*>();
            int x = 99;
            int y = 88;
            b.push(&x);
            b.push(&y);
            print(a.get(0) + a.get(1));
            print(*b.get(0) + *b.get(1));
            return 0;
        }
    """

    def test_distinct_structs_and_runtime(self, tmp_path):
        run_res, out_c = _compile(tmp_path, self.SRC, run=True)
        text = out_c.read_text()
        # Two distinct monomorphized structs, not one collided definition.
        assert "struct btrc_Vector_int {" in text
        assert "struct btrc_Vector_int_p1 {" in text
        assert run_res.returncode == 0, run_res.stderr
        assert run_res.stdout.split() == ["30", "187"]

    def test_unit_mangling_includes_pointer_suffix(self):
        from src.compiler.python.ast_nodes import TypeExpr
        from src.compiler.python.ir.gen.types import mangle_type_name

        plain = mangle_type_name(TypeExpr(base="int"))
        ptr = mangle_type_name(TypeExpr(base="int", pointer_depth=1))
        ptr2 = mangle_type_name(TypeExpr(base="int", pointer_depth=2))
        assert plain == "int"  # depth 0 unchanged (zero churn)
        assert ptr == "int_p1"
        assert ptr2 == "int_p2"
        assert plain != ptr != ptr2


# ---------------------------------------------------------------------------
# CMP-27: _has_return descends into loop bodies
# ---------------------------------------------------------------------------


class TestHasReturnLoops:
    def test_c_for_that_may_not_execute_does_not_satisfy_return(self):
        src = """
            int f() {
                for (int i = 0; i < 1; i = i + 1) { return i; }
            }
        """
        assert any("no return statement" in e for e in _errors(src))

    def test_for_in_that_may_not_execute_does_not_satisfy_return(self):
        src = """
            int g() {
                for x in [1, 2, 3] { return x; }
            }
        """
        assert any("no return statement" in e for e in _errors(src))

    def test_do_while_return_no_false_positive(self):
        src = """
            int h() {
                int i = 0;
                do { return i; } while (i < 1);
            }
        """
        assert not any("no return statement" in e for e in _errors(src))

    def test_method_c_for_does_not_satisfy_return(self):
        src = """
            class C {
                public int m() {
                    for (int i = 0; i < 2; i = i + 1) { return i; }
                }
            }
        """
        assert any("no return statement" in e for e in _errors(src))

    def test_truly_missing_return_still_errors(self):
        # No return anywhere -> the missing-return diagnostic must remain.
        src = """
            int noret() {
                int i = 0;
                for (int j = 0; j < 1; j = j + 1) { i = i + 1; }
            }
        """
        assert any("no return statement" in e for e in _errors(src))


# ---------------------------------------------------------------------------
# CMP-29: cyclable-flag classification
# ---------------------------------------------------------------------------


class TestCyclableFlags:
    def _cyclable(self, src: str) -> dict[str, bool]:
        a = _analyze(src)
        return {n: ci.is_cyclable for n, ci in a.class_table.items()}

    def test_self_loop_is_cyclable(self):
        src = """
            class N { public N next; public N() {} }
        """
        assert self._cyclable(src)["N"] is True

    def test_mutual_cycle_both_cyclable(self):
        src = """
            class A { public B b; public A() {} }
            class B { public A a; public B() {} }
        """
        flags = self._cyclable(src)
        assert flags["A"] is True
        assert flags["B"] is True

    def test_pointer_into_cycle_is_not_cyclable(self):
        # D references cyclable C, but nothing points back to D, so D is not in
        # any cycle and must stay non-cyclable (the docstring's "references a
        # cyclable class" reading would wrongly mark it).
        src = """
            class C { public C me; public C() {} }
            class D { public C c; public D() {} }
        """
        flags = self._cyclable(src)
        assert flags["C"] is True
        assert flags["D"] is False

    def test_base_typed_edge_can_close_cycle_through_subclass(self):
        src = """
            class Base {}
            class Derived extends Base { public Base peer; }
        """
        flags = self._cyclable(src)
        assert flags["Base"] is False
        assert flags["Derived"] is True

    def test_acyclic_class_not_cyclable(self):
        src = """
            class Leaf { public int v; public Leaf() {} }
        """
        assert self._cyclable(src)["Leaf"] is False


# ---------------------------------------------------------------------------
# CMP-21: extern/static/volatile global qualifiers
# ---------------------------------------------------------------------------


class TestGlobalQualifiers:
    def test_qualifiers_emit_distinctly(self, tmp_path):
        src = """
            extern int g_external;
            volatile int g_flag = 0;
            static int g_counter = 5;
            int main() { print(g_counter + g_flag); return 0; }
        """
        r, out_c = _compile(tmp_path, src)
        assert r.returncode == 0, r.stderr
        text = out_c.read_text()
        assert "extern int g_external;" in text
        # extern is a declaration -> never carries an initializer
        assert "extern int g_external = " not in text
        assert "volatile int g_flag = 0;" in text  # volatile preserved
        assert "static int g_counter = 5;" in text  # static preserved

    def test_unqualified_global_stays_static(self, tmp_path):
        # Zero-churn guard: a plain global still emits file-scope `static`.
        src = """
            int g_plain = 7;
            int main() { print(g_plain); return 0; }
        """
        r, out_c = _compile(tmp_path, src)
        assert r.returncode == 0, r.stderr
        assert "static int g_plain = 7;" in out_c.read_text()


# ---------------------------------------------------------------------------
# CMP-26: typed catch annotation stored + validated
# ---------------------------------------------------------------------------


class TestTypedCatch:
    def _try_stmt(self, src: str):
        tokens = Lexer(src).tokenize()
        program = Parser(tokens).parse()
        # Walk to the TryCatchStmt.
        found = []

        def walk(node):
            import dataclasses

            if type(node).__name__ == "TryCatchStmt":
                found.append(node)
            if dataclasses.is_dataclass(node):
                for fld in dataclasses.fields(node):
                    v = getattr(node, fld.name)
                    for x in v if isinstance(v, list) else [v]:
                        if dataclasses.is_dataclass(x):
                            walk(x)

        walk(program)
        return found[0]

    def test_catch_type_stored_on_ast(self):
        src = """
            int main() {
                try { throw "x"; } catch (string e) { print(e); }
                return 0;
            }
        """
        tc = self._try_stmt(src)
        assert tc.catch_type is not None
        assert tc.catch_type.base == "string"

    def test_untyped_catch_has_no_type(self):
        src = """
            int main() {
                try { throw "x"; } catch (e) { print(e); }
                return 0;
            }
        """
        tc = self._try_stmt(src)
        assert tc.catch_type is None

    def test_string_catch_accepted(self):
        src = """
            int main() {
                try { throw "x"; } catch (string e) { print(e); }
                return 0;
            }
        """
        assert not any("Catch type" in e for e in _errors(src))

    def test_non_string_catch_rejected(self):
        src = """
            class MyError { public int code; public MyError() {} }
            int main() {
                try { throw "x"; } catch (MyError e) { print("c"); }
                return 0;
            }
        """
        assert any("Catch type 'MyError' is not supported" in e for e in _errors(src))
