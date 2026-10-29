"""A replayed validation record must mark the replacement callable body."""

import subprocess
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler, requires_host_c_compiler

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def jump_validation_driver(selfhost_driver):
    return selfhost_driver(
        ROOT / "src/tests/btrc/fixtures/JumpValidationDriver.btrc",
        compile_flags=("-pedantic-errors", "-Wall", "-Wextra", "-Werror"),
    )


def test_jump_body_fact_replays_and_rejects_nonbody_nodes(jump_validation_driver):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_jump_record_fixture_analyzes_without_building():
    from src.compiler.python.application.pipeline import CompilationPipeline
    from src.compiler.python.application.results import CompilerOptions

    source = ROOT / "src/tests/btrc/fixtures/JumpValidationDriver.btrc"
    pipeline = CompilationPipeline()
    options = CompilerOptions(use_cache=False, use_ast_cache=False)
    resolved = pipeline.resolve(source.read_text(), str(source), options)
    parsed = pipeline.parse(resolved, str(source), options)
    analyzed = pipeline.analyze(parsed.program, prune_stdlib=True)
    assert analyzed.errors == []


@requires_host_c_compiler
@pytest.mark.parametrize(
    "source",
    [
        'int main() { int n = 0; label("again"); n++; if (n < 3) { jump("again"); } return n - 3; }',
        'int main() { var run = () => { jump("done"); label("done"); return 0; }; jump("done"); label("done"); return run(); }',
        """
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
        """,
        """
        int destroyed = 0;
        class Box { public Box() {} public void __del__() { destroyed++; } }
        void possibleException() { throw "failure"; }
        int main() {
            Box prefix = new Box(); int n = 0;
            label("again"); Box iteration = new Box(); n++;
            if (n < 3) { Box nested = new Box(); jump("again"); }
            { Box outward = new Box(); jump("done"); }
            label("done");
            if (destroyed != 5) { return 10; }
            try { possibleException(); } catch (string error) {}
            delete iteration; delete prefix; return destroyed - 7;
        }
    """,
    ],
)
def test_native_jump_lowering_runs(jump_validation_driver, tmp_path, source):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf"), source, "lower"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    generated = tmp_path / "goto.c"
    generated.write_text(result.stdout)
    executable = tmp_path / "goto"
    subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    execution = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert execution.returncode == 0, execution.stdout + execution.stderr


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ('void f(bool flag) { if (flag) { jump("done"); } bool value = true; label("done"); }', None),
        ('void f(bool flag) { if (flag) { jump("done"); } int values[2]; label("done"); }', None),
        ('void f(bool flag) { if (flag) { jump("done"); } static int value = 3; label("done"); value++; }', None),
        (
            'void f(bool flag) { if (flag) { jump("done"); } char* value = "owned"; label("done"); }',
            "not a plain C value",
        ),
        (
            'void f(bool flag) { if (flag) { jump("done"); } int value = 3; label("done"); value++; }',
            "used after the label",
        ),
        (
            'void f(bool flag, int count) { if (flag) { jump("done"); } try {} finally { int values[count]; } label("done"); }',
            "jumps into the scope of variable-length array",
        ),
        (
            'string original() { return "owned"; } void f(bool flag) { if (flag) { jump("done"); } char* value = original(); int original = 3; label("done"); }',
            "not a plain C value",
        ),
    ],
)
def test_native_jump_declaration_safety(jump_validation_driver, source, diagnostic):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf"), source],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if diagnostic is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ('int f() { jump("done"); label("done"); return 1; }', None),
        ('int f() { label("again"); jump("again"); }', None),
        ('int f(int n) { return 0; label("again"); n++; jump("again"); }', None),
        ('int f(bool flag) { label("again"); while (true) { if (flag) { jump("again"); } return 1; } }', None),
        ('int f(bool flag) { if (flag) { jump("done"); } return 1; label("done"); }', "does not return on every path"),
        ('int f() { while (true) { jump("done"); } label("done"); }', "does not return on every path"),
        (
            'void f() { jump("done"); int value = 1; label("done"); }',
            "Unreachable code after return/throw/break/continue/goto",
        ),
        ('void f() { return; label("unused"); }', "Unreachable code after return/throw/break/continue/goto"),
    ],
)
def test_native_jump_completion(jump_validation_driver, source, diagnostic):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf"), source],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if diagnostic is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "body, warnings",
    [
        ('if (box == null) { jump("done"); } box.value; label("done"); box.value;', 1),
        ('if (box != null) { jump("done"); } return; label("done"); box.value;', 0),
        ('if (flag) { jump("done"); } if (box == null) { return; } label("done"); box.value;', 1),
        ('if (box == null) { return; } label("again"); box.value; if (flag) { box = null; jump("again"); }', 1),
        ('{ Box? box = new Box(); jump("done"); } label("done"); box.value;', 1),
        ('if (box == null) { return; } { jump("inner"); label("inner"); } box.value;', 0),
        ('while (true) { if (box != null) { jump("done"); } return; } label("done"); box.value;', 0),
    ],
)
def test_native_jump_nullable_flow(jump_validation_driver, body, warnings):
    source = "class Box { public int value; } void f(Box? box, bool flag) { " + body + " }"
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf"), source],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Non-optional access") == warnings


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ('@realtime int f(int n) { label("again"); if (n > 0) { jump("again"); } return n; }', "backward goto 'again'"),
        ("@realtime int f(int n) { again: if (n > 0) goto again; return n; }", "backward goto 'again'"),
        ("@realtime int f(int n) { if (n > 0) goto done; return 0; done: return n; }", None),
        ('@realtime int f(int n) { if (n > 0) { jump("done"); } return 0; label("done"); return n; }', None),
        (
            '@gpu void f(int n) { jump("done"); label("done"); return; }',
            "goto statement is not allowed in GPU functions",
        ),
        ('@gpu void f(int n) { label("unused"); return; }', "labeled statement is not allowed in GPU functions"),
    ],
)
def test_native_jump_execution_domains(jump_validation_driver, source, diagnostic):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf"), source],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if diagnostic is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert diagnostic in result.stdout + result.stderr
