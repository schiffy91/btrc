"""Constructor identity is carried by ASDL, never inferred from spelling."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _run,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_parser_diagnostics",)


def test_selfhost_parser_marks_only_constructor_syntax(selfhost_drivers: dict[str, Path], tmp_path: Path) -> None:
    source = tmp_path / "constructors.btrc"
    source.write_text("class Box { public Box() {} public int read() { return 1; } }\n")

    parsed = _run([str(selfhost_drivers["parser"]), str(source)], timeout=15)

    assert parsed.returncode == 0, parsed.stderr
    assert parsed.stdout.count("is_constructor=true") == 1
    assert parsed.stdout.count("is_constructor=false") == 1


@pytest.mark.parametrize(
    "member, diagnostic",
    [
        (
            "public int Box() { return 1; }",
            "Constructor 'Box' cannot have return type 'int'",
        ),
        (
            "public Box Box() { return null; }",
            "uses explicit-return constructor syntax",
        ),
        (
            "public Other() {}",
            "Constructor 'Box' must be named 'Box'",
        ),
    ],
)
def test_constructor_lookalikes_are_rejected(
    selfhost_drivers: dict[str, Path],
    tmp_path: Path,
    member: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(
        selfhost_drivers["compiler"],
        tmp_path,
        f"class Box {{ {member} }} int main() {{ return 0; }}",
    )

    assert result.returncode == 1
    assert diagnostic in result.stderr


def test_marked_constructor_is_the_only_initializer_source(selfhost_drivers: dict[str, Path], tmp_path: Path) -> None:
    source = """
        class Box {
            public int value;
            public Box(int value) { self.value = value; }
            public int read() { return self.value; }
        }
        int main() {
            Box box = new Box(42);
            return box.read() == 42 ? 0 : 1;
        }
    """
    result, generated = _compile_source(selfhost_drivers["compiler"], tmp_path, source)

    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "void Box_init(Box* self, int value)" in emitted
    assert "Box_Box" not in emitted
    _strict_build_and_run(generated, tmp_path / "constructor-identity")
