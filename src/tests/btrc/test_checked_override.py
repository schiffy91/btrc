"""Checked override declarations preserve inherited signatures and static dispatch."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import compile_both
from src.tests.btrc.selfhost_snippet_harness import REPO, strict_build_and_run


@pytest.mark.parametrize(
    "source",
    [
        "class Child { public override int value() { return 1; } }",
        "class Parent {} class Child extends Parent { public override int value() { return 1; } }",
        "class Parent { public int value; } class Child extends Parent { public override int value() { return 1; } }",
        "class Parent { public Parent() {} } class Child extends Parent { public override int Parent() { return 1; } }",
        "interface Value { int value(); } class Child implements Value { public override int value() { return 1; } }",
        "class Child<T> { public override T value(T item) { return item; } }",
    ],
)
def test_override_requires_inherited_method(semantic_btrcc: Path, tmp_path: Path, source: str) -> None:
    for result, _ in compile_both(semantic_btrcc, tmp_path, source + " int main() { return 0; }"):
        assert result.returncode != 0
        assert "is marked override but no inherited method exists" in result.stderr


@pytest.mark.parametrize(
    "member",
    [
        "int value;",
        "int value { get; }",
        "int (*callback)(int);",
        "Child() {}",
        "@realtime int value;",
        "@realtime int (*callback)(int);",
    ],
)
def test_override_refuses_non_method(semantic_btrcc: Path, tmp_path: Path, member: str) -> None:
    for result, _ in compile_both(
        semantic_btrcc, tmp_path, f"class Child {{ public override {member} }} int main() {{ return 0; }}"
    ):
        assert result.returncode != 0
        assert "override can only be applied to non-constructor methods" in result.stderr


@pytest.mark.parametrize(
    "parent, child",
    [
        ("public int value(int item) { return item; }", "public override float value(int item) { return 1.0; }"),
        ("public int value(int item) { return item; }", "public override int value() { return 1; }"),
        ("public int value(int item) { return item; }", "static override int value(int item) { return item; }"),
        ("public int value(int item) { return item; }", "public override int value(float item) { return (int)item; }"),
        ("public int value<T>(T item) { return 1; }", "public override int value(int item) { return item; }"),
        ("public int value<T>() { return 1; }", "public override int value() { return 2; }"),
        ("public @realtime int value() { return 1; }", "public override int value() { return 2; }"),
        ('public keep string value() { return "a"; }', 'public override string value() { return "b"; }'),
        (
            "public int value(keep string item) { return 1; }",
            "public override int value(string item) { return 2; }",
        ),
    ],
)
def test_override_checks_signature(semantic_btrcc: Path, tmp_path: Path, parent: str, child: str) -> None:
    source = f"class Parent {{ {parent} }} class Child extends Parent {{ {child} }} int main() {{ return 0; }}"
    for result, _ in compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "Override '" in result.stderr


def test_override_uses_method_namespace_and_static_dispatch(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        #include <assert.h>
        class Parent {
            public int value;
            public int value() { return 3; }
            static int tag() { return 5; }
            public T identity<T>(T item) { return item; }
            public int add(int amount = 1) { return amount; }
        }
        class Middle extends Parent {}
        class Child extends Middle {
            public override int value() { return 11; }
            static override int tag() { return 13; }
            public override U identity<U>(U item) { return item; }
            public override int add(int count = 2) { return count; }
        }
        int main() {
            Child child = Child();
            Parent parent = child;
            assert(child.value() == 11);
            assert(parent.value() == 3);
            assert(Child.tag() == 13);
            assert(Parent.tag() == 5);
            assert(child.identity(17) == 17);
            assert(child.add() == 2);
            assert(parent.add() == 1);
            return 0;
        }
    """
    for index, (result, generated) in enumerate(compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        strict_build_and_run(generated, tmp_path / f"override-{index}")


def test_abstract_override_can_be_implemented(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        #include <assert.h>
        class Parent { public int value() { return 3; } }
        abstract class Middle extends Parent { public abstract override int value(); }
        class Child extends Middle { public override int value() { return 7; } }
        int main() { Child child = Child(); assert(child.value() == 7); return 0; }
    """
    for index, (result, generated) in enumerate(compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        strict_build_and_run(generated, tmp_path / f"abstract-override-{index}")


def test_override_cannot_hide_signature_mismatch_behind_field(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        class Parent { public int value; public int value() { return 1; } }
        class Child extends Parent { public override float value() { return 2.0; } }
        int main() { return 0; }
    """
    for result, _ in compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "Override '" in result.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_cached_override_rechecks_changed_parent(tmp_path: Path, request, frontend: str) -> None:
    parent = tmp_path / "Parent.btrc"
    parent.write_text("class Parent { public int value() { return 1; } }")
    program = tmp_path / "Main.btrc"
    program.write_text(
        "import ./Parent.btrc;\n"
        "class Child extends Parent { public override int value() { return 2; } }\n"
        "int main() { Child child = Child(); return child.value() == 2 ? 0 : 1; }\n"
    )
    command = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if frontend == "python"
        else [str(request.getfixturevalue("semantic_btrcc"))]
    )
    for changed in (False, False, True):
        if changed:
            parent.write_text("class Parent {}")
        result = subprocess.run(
            [*command, "--no-stdlib", str(program)],
            cwd=REPO,
            env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
            capture_output=True,
            text=True,
            timeout=60,
        )
        if changed:
            assert result.returncode != 0
            assert "is marked override but no inherited method exists" in result.stderr
        else:
            assert result.returncode == 0, result.stderr
