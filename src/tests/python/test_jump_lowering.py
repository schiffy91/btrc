"""Source jump lowering, lexical ownership and callable joins."""

import subprocess

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.ir.nodes import IRCall, IRGoto, IRLabel, IRVarDecl
from src.tests.c_toolchains import configured_c_compiler, requires_host_c_compiler
from src.tests.python.test_jump_validation import _program


def _lower(source):
    analyzed = SemanticAnalyzer().analyze(_program(source))
    assert analyzed.errors == []
    return IRLowerer(analyzed).lower()


def _emit(source):
    pipeline = CompilationPipeline()
    module = pipeline.optimize(_lower(source), CompilerOptions())
    return pipeline.emit(module)


@pytest.mark.parametrize(
    "body",
    [
        'jump("done"); label("done"); return 0;',
        'int n = 0; label("again"); n++; if (n < 3) { jump("again"); } return n - 3;',
        '{ jump("done"); } label("done"); return 0;',
        'label("unused"); return 0;',
        'int n = 0; label("EOF"); if (n++ < 1) { jump("EOF"); } return n - 2;',
        'int n = 0; if (n == 0) { jump("done"); } int unused = 5; n = unused; label("done"); return n;',
        'int n = 1; label("again"); int values[n]; values[0] = n; n++; if (n < 3) { jump("again"); } return values[0] - 2;',
        'switch (1) { case 1: jump("done"); label("done"); case 2: break; } return 0;',
        'try { jump("done"); label("done"); } finally {} return 0;',
        'var run = () => { jump("done"); label("done"); return 0; }; jump("done"); label("done"); return run();',
    ],
)
def test_jump_statements_reach_c(body):
    emitted = _emit(f"int main() {{ {body} }}")
    if 'label("unused")' in body:
        assert "unused: ;" not in emitted
    else:
        assert "goto " in emitted and ": ;" in emitted


def test_backward_cleanup_reuses_the_declarations_slot_identity():
    module = _lower("""
        void mayThrow() { throw "failure"; }
        int main() {
            string keepAlive = "keep";
            int n = 0;
            label("again");
            string iteration = "iteration";
            n++;
            if (n < 2) { jump("again"); }
            try { mayThrow(); } catch (string error) { print(keepAlive, iteration, error); }
            return 0;
        }
    """)
    nodes = list(next(function for function in module.function_defs if function.name == "main").walk())
    declaration = next(node for node in nodes if isinstance(node, IRVarDecl) and node.name == "keepAlive")
    registrations = [
        node for node in nodes if isinstance(node, IRCall) and node.cleanup_slot is declaration.cleanup_slot
    ]
    assert declaration.cleanup_slot is not None
    assert len(registrations) == 2
    assert registrations[0] is not registrations[1]
    assert registrations[0].args[0] is not registrations[1].args[0]
    assert sum(isinstance(node, IRGoto) for node in nodes) == 1


def test_backward_jump_rejects_changed_callback_ownership_abi():
    with pytest.raises(CodegenError, match="back-edge from goto 'again'; changed binding\\(s\\): callback"):
        _lower("""
            extern string foreign();
            string owned() { return "owned"; }
            int main() {
                __fn_ptr<string> callback = owned;
                label("again");
                callback = foreign;
                jump("again");
            }
        """)


def test_forward_callback_flow_survives_shadowed_nested_scope():
    emitted = _emit("""
        string owned() { return "owned"; }
        int main() {
            __fn_ptr<string> callback = owned;
            { int callback = 1; if (callback == 1) { jump("done"); } }
            label("done");
            print(callback());
            return 0;
        }
    """)
    assert "goto done;" in emitted


@pytest.mark.parametrize(
    "body",
    [
        'label("again"); int callback = n++; if (n < 2) { jump("again"); }',
        'if (n == 0) { jump("done"); } int callback = 1; n = callback; label("done");',
    ],
)
def test_jump_projection_restores_or_removes_shadowed_callable(body):
    _emit(
        'string owned() { return "owned"; } int main() { __fn_ptr<string> callback = owned; int n = 0; {'
        + body
        + "} print(callback()); return 0; }"
    )


def test_generic_method_has_an_independent_jump_frame():
    _emit("""
        class Runner<T> {
            public Runner() {}
            public int run() { jump("done"); label("done"); return 0; }
        }
        int main() { Runner<int> runner = new Runner<int>(); return runner.run(); }
    """)


@requires_host_c_compiler
def test_lifted_lambda_restores_the_enclosing_backward_jump_frame(tmp_path):
    emitted = _emit("""
        int main() {
            int visits = 0;
            label("again");
            var run = () => {
                int inner = 0;
                label("again");
                inner++;
                if (inner < 3) { jump("again"); }
                return inner;
            };
            visits += run();
            if (visits < 6) { jump("again"); }
            return visits - 6;
        }
    """)
    from src.tests.btrc.selfhost_snippet_harness import strict_build_and_run

    generated = tmp_path / "nested-jumps.c"
    generated.write_text(emitted)
    strict_build_and_run(generated, tmp_path / "nested-jumps")


def test_forward_jump_releases_hidden_owned_iterable():
    _emit("""
        string values() { return "abc"; }
        int main() { for letter in values() { jump("done"); } label("done"); return 0; }
    """)


@requires_host_c_compiler
def test_backward_cleanup_prefix_is_still_registered_when_a_callee_throws(tmp_path):
    emitted = _emit("""
        int destroyed = 0;
        class Box { public Box() {} public void __del__() { destroyed++; } }
        void fail() { throw "failure"; }
        void exercise() {
            Box prefix = new Box(); int n = 0;
            label("again"); Box iteration = new Box(); n++;
            if (n < 3) { jump("again"); }
            fail();
        }
        int main() { try { exercise(); } catch (string error) {} return destroyed - 4; }
    """)
    c_file = tmp_path / "unwind.c"
    c_file.write_text(emitted)
    executable = tmp_path / "unwind"
    subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_file),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_case_tail_labels_are_marked():
    module = _lower("""
        int main() {
            switch (1) {
                case 1: { jump("tail"); label("tail"); }
                case 2: return 0;
            }
            return 1;
        }
    """)
    labels = [node for node in module.walk() if isinstance(node, IRLabel)]
    assert len(labels) == 1 and labels[0].falls_through


@requires_host_c_compiler
@pytest.mark.parametrize("exceptions", [False, True])
def test_outward_and_backward_jumps_destroy_each_owner_once(tmp_path, exceptions):
    source = """
        int destroyed = 0;
        class Box {
            public Box() {}
            public void __del__() { destroyed++; }
        }
        int main() {
            Box prefix = new Box();
            int n = 0;
            label("again");
            Box iteration = new Box();
            n++;
            if (n < 3) { Box nested = new Box(); jump("again"); }
            { Box outward = new Box(); jump("done"); }
            label("done");
            if (destroyed != 5) { return 10; }
            delete iteration;
            delete prefix;
            return destroyed - 7;
        }
    """
    if exceptions:
        source = source.replace("int main() {", 'void possibleException() { throw "failure"; }\nint main() {')
        source = source.replace(
            "delete iteration;", "try { possibleException(); } catch (string error) {}\ndelete iteration;"
        )
    emitted = _emit(source)
    c_file = tmp_path / "goto.c"
    c_file.write_text(emitted)
    executable = tmp_path / "goto"
    subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_file),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_jump_names_do_not_retain_same_named_functions_or_globals():
    module = _lower("""
        int unusedFunction() { return 1; }
        int unusedGlobal = 2;
        int main() {
            goto unusedFunction;
            unusedFunction:
            goto unusedGlobal;
            unusedGlobal:
            return 0;
        }
    """)
    optimized = CompilationPipeline().optimize(module, CompilerOptions())
    assert [function.name for function in optimized.function_defs] == ["main"]
    assert not optimized.global_decls
    assert {node.name for node in optimized.function_defs[0].walk() if isinstance(node, IRLabel)} == {
        "unusedFunction",
        "unusedGlobal",
    }
