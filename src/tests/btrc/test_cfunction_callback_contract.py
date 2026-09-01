"""Exact noncapturing CFunction ABI parity across both compilers."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

_RECURSIVE_CONST_ALIAS_SOURCE = Path(__file__).parents[1] / "basics" / "test_cfunction_recursive_const_alias.btrc"


def _compile_pair(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    return (selfhost, selfhost_c), (reference, reference_c)


def test_recursive_const_callback_aliases_preserve_declaration_layers_through_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = _RECURSIVE_CONST_ALIAS_SOURCE.read_text()
    (selfhost, selfhost_c), (reference, reference_c) = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    callback = (
        "typedef void (*__btrc_fn_void_InputChannels_int_OutputChannels_int)(InputChannels, int, OutputChannels, int);"
    )
    aliases = (
        "typedef const float* InputChannel;",
        "typedef const InputChannel* InputChannels;",
        "typedef float* OutputChannel;",
        "typedef const OutputChannel* OutputChannels;",
    )
    callback_alias = "typedef __btrc_fn_void_InputChannels_int_OutputChannels_int Process;"
    for generated in (selfhost_c.read_text(), reference_c.read_text()):
        alias_positions = [generated.index(alias) for alias in aliases]
        callback_position = generated.index(callback)
        assert alias_positions == sorted(alias_positions)
        assert alias_positions[-1] < callback_position
        assert callback_position < generated.index(callback_alias)
        assert generated.count("(*__btrc_fn_void_InputChannels_int_OutputChannels_int)") == 1
        assert "const float**" not in generated

    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-recursive-const-alias")
    _strict_build_and_run(reference_c, tmp_path / "reference-recursive-const-alias")


def test_cfunction_qsort_bsearch_compiles_and_runs_through_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        #include <stdlib.h>

        int compare(const void* left, const void* right) {
            int a = *(const int*)left;
            int b = *(const int*)right;
            return a < b ? -1 : (a > b ? 1 : 0);
        }

        int main() {
            int values[4] = {4, 2, 1, 3};
            CFunction<int, const void*, const void*> callback = compare;
            qsort(values, 4, sizeof(int), callback);
            int key = 3;
            int* found = (int*)bsearch(
                &key, values, 4, sizeof(int), callback);
            assert(found != null);
            assert(*found == 3);
            return 0;
        }
    """
    (selfhost, selfhost_c), (reference, reference_c) = _compile_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-cfunction")
    _strict_build_and_run(reference_c, tmp_path / "reference-cfunction")


@pytest.mark.parametrize(
    "declaration",
    (
        "int compare(const void* value) { return 0; }",
        "void compare(const void* left, const void* right) {}",
        "int compare(void* left, void* right) { return 0; }",
    ),
)
def test_qsort_rejects_wrong_callback_shape_through_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    declaration: str,
) -> None:
    source = f"""
        #include <stdlib.h>
        {declaration}
        int main() {{
            int values[2] = {{2, 1}};
            qsort(values, 2, sizeof(int), compare);
            return 0;
        }}
    """
    (selfhost, _), (reference, _) = _compile_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Argument 4" in selfhost.stderr
    assert "Argument 4" in reference.stderr
    assert "CFunction<int, const void*, const void*>" in selfhost.stderr
    assert "CFunction<int, const void*, const void*>" in reference.stderr


def test_qsort_rejects_capturing_lambda_through_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <stdlib.h>
        int main() {
            int values[2] = {2, 1};
            int direction = 1;
            qsort(values, 2, sizeof(int),
                (const void* left, const void* right) => direction);
            return 0;
        }
    """
    (selfhost, _), (reference, _) = _compile_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "environment" in (selfhost.stdout + selfhost.stderr).lower()
    assert "capturing lambda" in reference.stderr.lower()


def test_exact_qsort_declaration_accepts_only_cfunction_shape(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    good = """
        extern void qsort(void* base, size_t count, size_t size,
            CFunction<int, const void*, const void*> compare);
        int main() { return 0; }
    """
    bad = good.replace("const void*, const void*", "void*, void*")
    (selfhost_good, _), (reference_good, _) = _compile_pair(semantic_btrcc, tmp_path, good)
    assert selfhost_good.returncode == 0, selfhost_good.stderr
    assert reference_good.returncode == 0, reference_good.stderr

    (selfhost_bad, _), (reference_bad, _) = _compile_pair(semantic_btrcc, tmp_path, bad)
    assert selfhost_bad.returncode != 0
    assert reference_bad.returncode != 0
    assert "does not match compiler-owned C ABI" in selfhost_bad.stderr
    assert "does not match compiler-owned C ABI" in reference_bad.stderr
