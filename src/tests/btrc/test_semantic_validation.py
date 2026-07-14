"""Focused fail-closed contracts for the self-hosted semantic stage."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture(scope="module")
def semantic_btrcc(tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("selfhost-semantic-validation")
    generated = output / "btrcc.c"
    binary = output / "btrcc"
    transpile = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            "src/compiler/btrc/btrcc_main.btrc",
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(output / "cache")},
        timeout=300,
    )
    assert transpile.returncode == 0 and generated.exists(), transpile.stderr
    compile_result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        timeout=300,
    )
    assert compile_result.returncode == 0 and binary.exists(), compile_result.stderr
    return binary


def _compile_source(
    compiler: Path,
    tmp_path: Path,
    source: str,
    *,
    no_stdlib: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / "program.btrc"
    generated = tmp_path / "program.c"
    program.write_text(source)
    command = [str(compiler)]
    if no_stdlib:
        command.append("--no-stdlib")
    command.append(str(program))
    result = _run(command, timeout=120 if not no_stdlib else 30)
    if result.returncode == 0:
        generated.write_text(result.stdout)
    return result, generated


def _strict_build_and_run(generated: Path, output: Path) -> None:
    build = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(output),
            "-lm",
            "-lpthread",
        ],
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = _run([str(output)], timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ('int main() { return "oops"; }', "Return type mismatch"),
        ('int main() { int x = "oops"; return 0; }', "Cannot assign"),
        ("int main() { bool x = 3; return 0; }", "Cannot assign"),
        ('int main() { return 1 + "x"; }', "operator '+'"),
        (
            'int f(int x) { return x; } int main() { return f("x"); }',
            "expects 'int'",
        ),
    ],
)
def test_original_fail_open_programs_are_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert diagnostic in result.stderr


def test_break_path_prevents_infinite_loop_return_proof(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        int run(bool stop) {
            while (true) {
                if (stop) { break; }
                return 1;
            }
        }
        int main() { return 0; }
    """
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert "does not return on every path" in result.stderr


def test_nested_loop_break_does_not_escape_outer_loop(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        int run() {
            while (true) {
                while (true) { break; }
                return 1;
            }
        }
        int main() { return run() == 1 ? 0 : 1; }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "nested-break")


def test_optional_receiver_runs_once_and_fallback_stays_lazy(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        int receiverCalls = 0;
        int fallbackCalls = 0;

        class Box {
            public int value;
            public Box(int value) { self.value = value; }
            public int doubled { get { return self.value * 2; } }
        }

        Box? makeBox(bool present) {
            receiverCalls += 1;
            if (present) { return Box(7); }
            return null;
        }

        int fallback() { fallbackCalls += 1; return 3; }

        int main() {
            int first = makeBox(true)?.value ?? fallback();
            int second = makeBox(false)?.value ?? fallback();
            int third = makeBox(true)?.doubled ?? fallback();
            int fourth = makeBox(false)?.doubled ?? fallback();
            return receiverCalls == 4 && fallbackCalls == 2
                && first == 7 && second == 3
                && third == 14 && fourth == 3 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "optional-once")


def test_typedefs_use_underlying_operator_domain(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        typedef int Score;
        interface Value { int read(); }
        class Box<Value> {
            public Value stored;
            public Box(Value stored) { self.stored = stored; }
        }
        Score add(Score left, Score right) { return left + right; }
        int store(int* target) { *target = 42; return *target; }
        int main() {
            Score value = add(20, 22);
            Box<int> box = new Box<int>(value);
            int raw = 0;
            store(&raw);
            return box.stored == 42 && raw == 42 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "typedef-domain")


def test_scalar_string_join_is_rejected(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = 'int main() { string value = "a".join(","); return 0; }'
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert "Type 'string' has no method 'join'" in result.stderr


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ("int main() { return self.value; }", "'self' used outside"),
        ("int main() { super.run(); return 0; }", "'super' used outside"),
        (
            "class A { public int run() { return super.run(); } } int main() { return 0; }",
            "class without a parent",
        ),
        (
            'class A { public A(int value) {} } int main() { A value = A("bad"); return 0; }',
            "expects 'int'",
        ),
        (
            "int value() { return 1; } int value() { return 2; } int main() { return 0; }",
            "Duplicate top-level declaration 'value'",
        ),
        (
            "class A { public int value; public int value; } int main() { return 0; }",
            "Duplicate member 'A.value'",
        ),
        (
            "class Base { public int run(int value) { return value; } } "
            "class Child extends Base { "
            'public string run(int value) { return "bad"; } } '
            "int main() { return 0; }",
            "does not match inherited signature",
        ),
        (
            "class A { class int value() { return 1; } } int main() { A item = A(); return item.value(); }",
            "must be called on the class",
        ),
        (
            "class A { public int value() { return 1; } } int main() { return A.value(); }",
            "is not a class method",
        ),
    ],
)
def test_declaration_and_context_contracts(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert diagnostic in result.stderr


def test_semantic_modules_precede_ir_and_stay_small() -> None:
    driver = (SELFHOST / "btrcc_main.btrc").read_text()
    assert driver.index("semanticValidateProgram(prog, a)") < driver.index("IRGen gen = IRGen(a)")
    for module in SELFHOST.glob("semantic_validation*.btrc"):
        assert len(module.read_text().splitlines()) <= 300, module
