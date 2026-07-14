"""Fail-closed ownership domains for values stored behind ``Mutex<T>``."""

from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import _compile_reference
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    "source,diagnostic",
    [
        (
            "int main() { Mutex<Thread<int>> value; return 0; }",
            "cannot contain a Thread handle",
        ),
        (
            "int main() { Mutex<(int, Thread<int>)> value; return 0; }",
            "cannot contain a Thread handle",
        ),
        (
            "int main() { Mutex<Mutex<int>> value; return 0; }",
            "cannot contain a Mutex handle",
        ),
        (
            "int main() { Mutex<(int, Mutex<int>)> value; return 0; }",
            "cannot contain a Mutex handle",
        ),
        (
            "int main() { Mutex<int[]> value; return 0; }",
            "cannot contain array storage",
        ),
        (
            "int main() { Mutex<(string, int)> value; return 0; }",
            "cannot contain string or class references",
        ),
        (
            "class Box { public Box() {} } struct Payload { Box box; }; int main() { Mutex<Payload> value; return 0; }",
            "cannot contain string or class references",
        ),
        (
            "enum class Payload { Text(string text), Empty } int main() { Mutex<Payload> value; return 0; }",
            "cannot contain string or class references",
        ),
        (
            "struct Payload { string text; }; "
            "typedef Payload Alias; typedef Alias Result; "
            "int main() { Mutex<Result> value; return 0; }",
            "cannot contain string or class references",
        ),
        (
            "int main() { Mutex<Vector<int>> value; return 0; }",
            "cannot contain runtime-owned collection storage",
        ),
        (
            "int main() { Mutex<List<int>> value; return 0; }",
            "cannot contain runtime-owned collection storage",
        ),
        (
            "int main() { Mutex<Map<int, int>> value; return 0; }",
            "cannot contain runtime-owned collection storage",
        ),
        (
            "int main() { Mutex<Set<int>> value; return 0; }",
            "cannot contain runtime-owned collection storage",
        ),
        (
            "int main() { Mutex<Array<int>> value; return 0; }",
            "cannot contain runtime-owned collection storage",
        ),
        (
            "struct Payload { string text; }; "
            "class Holder<T> { "
            "public Mutex<T> value; "
            "public Holder(T initial) { self.value = Mutex(initial); } "
            "} "
            "int main() { Holder<Payload> owner; return 0; }",
            "cannot contain string or class references",
        ),
    ],
)
def test_mutex_payload_shapes_are_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(
        tmp_path,
        source,
        "mutex-payload-diagnostic",
    )
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "Mutex<T> payload type" in result.stderr
        assert diagnostic in result.stderr


def test_registered_class_backed_collection_payload_is_a_managed_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "class Vector<T> { public int marker; } int main() { Mutex<Vector<int>> value; return 0; }"
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(
        tmp_path,
        source,
        "mutex-managed-vector",
    )
    for result in (selfhost, reference):
        assert result.returncode == 0, result.stderr
