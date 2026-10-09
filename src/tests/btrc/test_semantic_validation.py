"""Focused fail-closed contracts for the self-hosted semantic stage."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import (
    REPO,
    compile_reference_source,
    compile_source,
    strict_build_and_run,
)
from src.tests.c_toolchains import host_c_compiler

SELFHOST = REPO / "src/compiler/btrc"

pytestmark = pytest.mark.skipif(
    host_c_compiler() is None,
    reason="needs a C compiler",
)


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ('int main() { return "oops"; }', "Return type mismatch"),
        ('int main() { int x = "oops"; return 0; }', "Cannot assign"),
        ("int main() { bool x = 3; return 0; }", "Cannot assign"),
        ('int main() { return 1 + "x"; }', "Operator '+'"),
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
    result, _ = compile_source(semantic_btrcc, tmp_path, source)
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
    result, _ = compile_source(semantic_btrcc, tmp_path, source)
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
    result, generated = compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "nested-break")


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
    selfhost, selfhost_source = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    assert "__btrc_finally_pending" not in selfhost_source.read_text()
    assert "__btrc_finally_pending" not in reference_source.read_text()
    strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-try-finally-return",
        optimization="-O0",
    )
    strict_build_and_run(
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
    result, generated = compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    main_c = generated.read_text().split("int main(void)", 1)[1]
    assert main_c.count(": fallback()") == 4
    # Each boundary releases its handed-off receiver, then yields its result.
    released_then_result = re.findall(
        r"__btrc_arc_release(?:_acyclic)?\(__btrc_released_operand_\d+, [^;]*?\), __btrc_call_result_\d+\);", main_c
    )
    assert len(released_then_result) == 4
    strict_build_and_run(generated, tmp_path / "optional-once")


def test_optional_generic_method_coalesce_keeps_result_and_cleanup_paths_separate(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int receiverCalls = 0;
        int argumentCalls = 0;
        int methodCalls = 0;
        int scalarFallbackCalls = 0;
        int managedArgumentCalls = 0;
        int managedFallbackCalls = 0;

        class Item {
            public int value;
            public Item(int value) { self.value = value; }
        }

        class Box<T> {
            public T stored;
            public Box(T stored) { self.stored = stored; }
            public int read(int delta) {
                methodCalls += 1;
                return 40 + delta;
            }
            public Item makeItem(int value) {
                return new Item(value);
            }
        }

        Box<int>? select(bool present) {
            receiverCalls += 1;
            if (present) { return new Box<int>(7); }
            return null;
        }

        int argument() { argumentCalls += 1; return 2; }
        int scalarFallback() { scalarFallbackCalls += 1; return 17; }
        int managedArgument() { managedArgumentCalls += 1; return 31; }
        Item managedFallback() {
            managedFallbackCalls += 1;
            return new Item(99);
        }

        int main() {
            int present = select(true)?.read(argument()) ?? scalarFallback();
            int absent = select(false)?.read(argument()) ?? scalarFallback();
            try {
                Item presentItem = select(true)?.makeItem(managedArgument())
                    ?? managedFallback();
                Item absentItem = select(false)?.makeItem(managedArgument())
                    ?? managedFallback();
                if (presentItem.value != 31 || absentItem.value != 99) {
                    return 2;
                }
            } catch (string error) {
                return 3;
            }
            return receiverCalls == 4 && argumentCalls == 1
                && methodCalls == 1 && scalarFallbackCalls == 1
                && managedArgumentCalls == 1 && managedFallbackCalls == 1
                && present == 42 && absent == 17 ? 0 : 1;
        }
    """
    result, generated = compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    main_c = generated.read_text().split("int main(void)", 1)[1]
    scalar_fallback_results = re.findall(
        r": \((__btrc_optional_result_\d+) = scalarFallback\(\)\)",
        main_c,
    )
    assert main_c.count("scalarFallback()") == 2
    assert len(scalar_fallback_results) == 2
    assert len(set(scalar_fallback_results)) == 2

    managed_handoffs = re.findall(
        r"\((__btrc_optional_result_handoff_\d+) = (__btrc_optional_result_\d+)\), "
        r"\(\2 = NULL\), \1",
        main_c,
    )
    managed_coalesces = re.findall(
        r"\(\((__nc_\d+) != NULL\) \? \1 : managedFallback\(\)\)",
        main_c,
    )
    assert len(managed_handoffs) == 2
    assert len(set(managed_handoffs)) == 2
    assert {result for _, result in managed_handoffs}.isdisjoint(scalar_fallback_results)
    assert main_c.count("managedFallback()") == 2
    assert len(managed_coalesces) == 2
    assert len(set(managed_coalesces)) == 2
    strict_build_and_run(generated, tmp_path / "optional-generic-method")


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
    result, generated = compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    strict_build_and_run(generated, tmp_path / "typedef-domain")


def test_scalar_string_join_is_rejected(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = 'int main() { string value = "a".join(","); return 0; }'
    result, _ = compile_source(semantic_btrcc, tmp_path, source)
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
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = compile_reference_source(tmp_path, source)

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
    selfhost, selfhost_source = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    strict_build_and_run(selfhost_source, tmp_path / "selfhost-class-method")
    strict_build_and_run(reference_source, tmp_path / "reference-class-method")


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
    selfhost, selfhost_source = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    strict_build_and_run(selfhost_source, tmp_path / "selfhost-shadowing")
    strict_build_and_run(reference_source, tmp_path / "reference-shadowing")


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
            "Duplicate definition of function 'value'",
        ),
        (
            "class A { public int value; public int value; } int main() { return 0; }",
            "Duplicate field 'value' in class 'A'",
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
            "Class method 'value' must be accessed on 'A', not on an instance",
        ),
        (
            "class A { public int value() { return 1; } } int main() { return A.value(); }",
            "is not a class method",
        ),
        # The callee resolves before its arguments, keyed by the member's
        # owner as the reference does: a parent's private method through
        # `self` in a subclass, and a private function-pointer field.
        (
            "class A { public A() {} private int helper() { return 1; } }\n"
            "class B extends A { public B() {} public int viaB() { return self.helper(); } }\n"
            "int main() { B b = new B(); return b.viaB(); }",
            "Cannot access private method 'helper' of class 'A'",
        ),
        (
            "class A { public A() { self.cb = null; } private CFunction<int, int>? cb; }\n"
            "int main() { A a = new A(); return a.cb(1); }",
            "Cannot access private field 'cb' of class 'A'",
        ),
        (
            "int f(int x) { return x; }\n"
            "class R { public R() {} private int m(int v) { return v; } }\n"
            "int main() { R r = new R(); return r.m(f(1, 2)); }",
            "Cannot access private method 'm' of class 'R'",
        ),
    ],
)
def test_declaration_and_context_contracts(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert diagnostic in result.stderr


def test_semantic_stage_precedes_structured_ir_lowering() -> None:
    pipeline = (SELFHOST / "pipeline/Pipeline.btrc").read_text()
    analyzer_stage = (SELFHOST / "analyzer/Stage.btrc").read_text()
    semantic_analyzer = (SELFHOST / "analyzer/Analyzer.btrc").read_text()
    ir_stage = (SELFHOST / "ir/Stage.btrc").read_text()

    assert pipeline.index("Analyzed analyzed = analyzer.analyze(program, self.hostedAbi);") < pipeline.index(
        "IRLowerer lowerer = IRLowerer("
    )
    assert semantic_analyzer.index("validator.validate();") < semantic_analyzer.index("return self.analysis;")
    assert "import ./validation/Validator.btrc;" in analyzer_stage
    assert "import ./Analyzer.btrc;" in analyzer_stage
    assert "#include" not in analyzer_stage
    assert "import ../analyzer/Stage.btrc;" in ir_stage
