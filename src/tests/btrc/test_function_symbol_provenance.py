"""Function-value provenance across reachability pruning."""

from __future__ import annotations

import re
from pathlib import Path

from src.tests.btrc.production_readiness_harness import run_strict_pair
from src.tests.btrc.string_coercion_harness import compile_pair

SOURCE = """
    int shadowed(int value) { return value + 100; }
    int addressed(int value) { return value + 1; }

    int invoke(__fn_ptr<int, int> shadowed) {
        return shadowed(41);
    }

    int main() {
        var callback = &addressed;
        return invoke(callback) == 42 ? 0 : 1;
    }
"""

GENERIC_STATIC_METHOD_SOURCE = """
    class Util {
        static int make() { return 42; }
    }

    class Box<T> {
        public int invoke() {
            __fn_ptr<int> callback = Util.make;
            return callback();
        }
    }

    int main() {
        Box<int> box = new Box<int>();
        int result = box.invoke();
        delete box;
        return result == 42 ? 0 : 1;
    }
"""


def _definition(name: str) -> re.Pattern[str]:
    return re.compile(rf"^int {name}\(int value\) \{{$", re.MULTILINE)


def test_function_values_have_explicit_reachability_provenance(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        SOURCE,
        "function_symbol_provenance",
        include_stdlib=False,
    )

    for _frontend, generated in compiled:
        source = generated.read_text()
        assert _definition("addressed").search(source)
        assert not _definition("shadowed").search(source)
        assert "return shadowed(41);" in source

    run_strict_pair(compiled, tmp_path)


def test_generic_body_lowers_static_method_value_as_function_symbol(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        GENERIC_STATIC_METHOD_SOURCE,
        "generic_static_method_value_provenance",
        include_stdlib=False,
    )

    for _frontend, generated in compiled:
        source = generated.read_text()
        assert "Util.make" not in source
        assert "Util_make" in source
        assert "callback = Util_make;" in source

    run_strict_pair(compiled, tmp_path)
