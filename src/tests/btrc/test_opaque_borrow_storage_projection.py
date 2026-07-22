"""Stored raw fields stay distinct from managed-backed projections."""

from pathlib import Path

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    run_strict_pair,
)
from src.tests.btrc.string_coercion_harness import compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


STORED_POINTER_SOURCE = r"""
#include <stdlib.h>

class Buffer<T> {
    public T* data;

    public Buffer() { self.data = null; }

    public void clear() {
        T* previous = self.data;
        free(previous);
        self.data = null;
    }
}

int main() {
    Buffer<int> buffer = new Buffer<int>();
    buffer.clear();
    delete buffer;
    return 0;
}
"""


EMBEDDED_ARRAY_SOURCE = r"""
class Holder {
    public int values[1];
}

int main() {
    Holder owner = new Holder();
    int* escaped = owner.values;
    delete owner;
    return escaped[0];
}
"""


MUTABLE_ADDRESS_SOURCE = r"""
#include <regex.h>

class CompiledPattern {
    public regex_t pattern;

    public bool probe() {
        if (regcomp(&self.pattern, "x", REG_EXTENDED) != 0) {
            return false;
        }
        regfree(&self.pattern);
        return true;
    }
}

int main() {
    CompiledPattern pattern = new CompiledPattern();
    bool ok = pattern.probe();
    delete pattern;
    return ok ? 0 : 1;
}
"""


def test_stored_pointer_field_remains_a_raw_value(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        STORED_POINTER_SOURCE,
        "opaque-stored-pointer-field",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


def test_embedded_array_field_remains_managed_backed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        EMBEDDED_ARRAY_SOURCE,
    ):
        assert result.returncode != 0
        assert "cannot persist a managed value as a raw representation" in result.stderr


def test_explicit_field_address_allows_nonescaping_mutation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        MUTABLE_ADDRESS_SOURCE,
        "opaque-mutable-field-address",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)
