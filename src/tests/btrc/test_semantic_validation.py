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


def _compile_reference_source(
    tmp_path: Path,
    source: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / "reference.btrc"
    generated = tmp_path / "reference.c"
    program.write_text(source)
    result = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "reference-cache")},
        timeout=120,
    )
    return result, generated


def _strict_build_and_run(
    generated: Path,
    output: Path,
    *,
    optimization: str | None = None,
) -> None:
    optimization_flags = [optimization] if optimization is not None else []
    build = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *optimization_flags,
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


def test_try_finally_without_catch_preserves_try_return_proof(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int finallyRuns = 0;
        int run() {
            try {
                return 7;
            } finally {
                finallyRuns += 1;
            }
        }
        int main() {
            return run() == 7 && finallyRuns == 0 ? 0 : 1;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    assert "__btrc_finally_pending" not in selfhost_source.read_text()
    assert "__btrc_finally_pending" not in reference_source.read_text()
    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-try-finally-return",
        optimization="-O0",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-try-finally-return",
        optimization="-O0",
    )


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
        (
            "enum class Color { Red, Blue } int main() { return Color.Missing; }",
            "Rich enum 'Color' has no variant 'Missing'",
        ),
        (
            "enum class Color { Red, Blue } int main() { return Color.Missing(); }",
            "Rich enum 'Color' has no variant 'Missing'",
        ),
        (
            "enum class Color { Red, Blue } int main() { Color value = Color.Red; return value.missing; }",
            "Rich enum 'Color' has no field 'missing'",
        ),
        (
            "class Box { class int value; } int main() { return Box.missing; }",
            "Class 'Box' has no static field or method 'missing'",
        ),
        (
            "class Box { public int value; } int main() { return Box.value; }",
            "Instance member 'value' cannot be accessed on class 'Box'",
        ),
        (
            "class Base { class int value; } class Child extends Base {} int main() { return Child.value; }",
            "Class 'Child' has no static field or method 'value'",
        ),
        (
            "class Box { class int value; } int main() { Box box = Box(); return box.value; }",
            "Class 'Box' has no field or method 'value'",
        ),
        (
            "class Box { private int value; } int read(Box box) { return box.value; } int main() { return 0; }",
            "Cannot access private field 'value' of class 'Box'",
        ),
        (
            "class Box { private int value; } void write(Box box) { box.value = 1; } int main() { return 0; }",
            "Cannot access private field 'value' of class 'Box'",
        ),
        (
            "class Box { private int value { get; set; } } "
            "int read(Box box) { return box.value; } int main() { return 0; }",
            "Cannot access private property 'value' of class 'Box'",
        ),
        (
            "class Box { private int value { get; set; } } "
            "void write(Box box) { box.value = 1; } int main() { return 0; }",
            "Cannot access private property 'value' of class 'Box'",
        ),
        (
            "class Box { public int values[2] { get; set; } } int main() { return 0; }",
            "Property 'Box.values' cannot use fixed-size array storage; use an instance field plus accessors",
        ),
        (
            "class Item { public Item() {} } class Box { public Item values[2]; } int main() { return 0; }",
            "Field 'Box.values' cannot contain managed elements without elementwise ownership support",
        ),
        (
            "class Base { private int value; } class Child extends Base { "
            "public int read() { return self.value; } } int main() { return 0; }",
            "Cannot access private field 'value' of class 'Base'",
        ),
    ],
)
def test_member_projection_diagnostics_match_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_inherited_class_method_wrappers_match_reference_abi(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int saved = 0;
        class Base {
            class int sum(int left, int right) { return left + right; }
            class void remember(int value) { saved = value; }
        }
        class Child extends Base {}
        int main() {
            Child.remember(40);
            return Child.sum(saved, 2) == 42 ? 0 : 1;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-class-method")
    _strict_build_and_run(reference_source, tmp_path / "reference-class-method")


def test_type_name_shadowing_uses_instance_member_lookup(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {
            public int value;
            public Box(int value) { self.value = value; }
        }
        int read() {
            Box Box = Box(42);
            Box other = new Box(1);
            {
                int Box = 7;
                if (Box != 7) { return 0; }
            }
            return Box.value + other.value;
        }
        int main() { return read() == 43 ? 0 : 1; }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-shadowing")
    _strict_build_and_run(reference_source, tmp_path / "reference-shadowing")


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
    assert driver.index("semanticValidateProgram(prog, a)") < driver.index("IRGen gen = IRGen(")
    for module in SELFHOST.glob("semantic_validation*.btrc"):
        assert len(module.read_text().splitlines()) <= 300, module
