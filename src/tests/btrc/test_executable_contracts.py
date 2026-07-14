"""Adversarial executable contracts for the self-hosted compiler."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    CC,
    _compile_source,
    _run,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "int main() { var pair = (1, 2); if (pair) {} return 0; }",
            "requires a scalar condition",
        ),
        (
            "int main() { var pair = (1, 2); return pair[0]; }",
            "Tuple values are not dynamically indexable",
        ),
        (
            "class Box {} int main() { Box box = new Box(); return box[0]; }",
            "indexing requires an instance get(index) method",
        ),
        (
            "class Set<T> {} int main() { Set<int> values = new Set<int>(); return values[0]; }",
            "indexing requires an instance get(index) method",
        ),
        (
            "class Box { public int get(int index) { return index; } } "
            'int main() { Box box = new Box(); return box["bad"]; }',
            "Index expression expects 'int'",
        ),
        (
            "class Box { public int get(int index) { return index; } "
            "public int set(int index, int value) { return value; } } "
            "int main() { Box box = new Box(); box[0] = 1; return 0; }",
            "has no void instance set(index, value) method",
        ),
        (
            "int main() { int values[2]; return values[1.5]; }",
            "Index expression must have an integral type",
        ),
        (
            "class Box {} int main() { Box box = new Box(); for value in box {} return 0; }",
            "does not satisfy the for-in protocol",
        ),
        (
            "int main() { for value in range() {} return 0; }",
            "range expects 1 to 3 arguments",
        ),
        (
            "int main() { for value in range(true) {} return 0; }",
            "integral non-bool type",
        ),
        (
            "int main() { for value in range(0, 3, 0) {} return 0; }",
            "range step cannot be zero",
        ),
        (
            "class Box {} int main() { for (var box = new Box(); true;) {} return 0; }",
            "C-style for initializer cannot own an ARC-managed value",
        ),
        (
            "int main() { int value = 1; delete value; return 0; }",
            "delete is not valid for type 'int'",
        ),
        (
            "class Box { public Box item { get; set; } } "
            "int main() { Box box = new Box(); release box.item; return 0; }",
            "release cannot target a property",
        ),
        (
            "int main() { int value = new int(); return value; }",
            "new requires a class type",
        ),
        (
            "class Box {} int main() { Box* value = new Box*(); return 0; }",
            "new requires an unqualified class type",
        ),
        (
            "class Box {} int main() { Box** value = null; release value; return 0; }",
            "release is not valid",
        ),
        (
            "int main() { var f = (int value = 1) => value; return 0; }",
            "Lambda parameters cannot have default arguments",
        ),
        (
            "int main() { while (true) { var f = () => { break; }; break; } return 0; }",
            "outside of loop or switch",
        ),
    ],
)
def test_invalid_executable_shapes_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "fixture_name",
    [
        "executable_contracts_runtime.btrc",
        "optional_call_contracts_runtime.btrc",
    ],
)
def test_executable_contracts_compile_strictly_and_run(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    source = (FIXTURES / fixture_name).read_text()
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / Path(fixture_name).stem)


def test_dynamic_zero_range_step_exits_before_iteration(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = (FIXTURES / "range_zero_runtime.btrc").read_text()
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    binary = tmp_path / "range-zero"
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
            str(binary),
            "-lm",
            "-lpthread",
        ],
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = _run([str(binary)], timeout=30)
    assert run.returncode == 1
    assert "range step cannot be zero" in run.stderr
