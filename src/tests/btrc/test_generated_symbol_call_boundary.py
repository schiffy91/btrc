"""Dual-frontend generated-symbol reference and lifecycle boundaries."""

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    compile_no_dce_pair,
)
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        ("class Box {} int main() { Box_init(null); return 0; }", "Box_init"),
        ("class Box {} int main() { Box_new(); return 0; }", "Box_new"),
        ("class Box {} int main() { Box_destroy(null); return 0; }", "Box_destroy"),
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "int main() { kernel__gpuitem(); return 0; }",
            "kernel__gpuitem",
        ),
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "int main() { kernel__gpucpu(); return 0; }",
            "kernel__gpucpu",
        ),
        (
            "class Vault { private int secret() { return 42; } } "
            "int main() { Vault value = new Vault(); return Vault_secret(value); }",
            "Vault_secret",
        ),
        (
            "class Vault { private int secret { get { return 42; } } } "
            "int main() { Vault value = new Vault(); return Vault_get_secret(value); }",
            "Vault_get_secret",
        ),
        (
            "class Box { class int total = 0; } int main() { return Box_total(); }",
            "Box_total",
        ),
        (
            "class Box { public void __del__() {} } int main() { __btrc_Box_destructor_hook(null); return 0; }",
            "__btrc_Box_destructor_hook",
        ),
        (
            "class Box<T> {} int main() { Box<int> stored = new Box<int>(); btrc_Box_int_destroy(stored); return 0; }",
            "btrc_Box_int_destroy",
        ),
        (
            "class Box { public U identity<U>(U value) { return value; } } "
            "int main() { Box box = new Box(); int value = box.identity(42); "
            "return Box_identity_int(box, value); }",
            "Box_identity_int",
        ),
    ),
)
def test_generated_c_calls_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    symbol: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    "symbol",
    (
        "__btrc_lambda_1",
        "__btrc_spawn_wrapper_1",
        "__btrc_spawn_env_dispose_1",
        "__btrc_cleanup_take_1",
        "__gpu_dispatch_1_run",
    ),
)
def test_dynamic_compiler_owned_names_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    symbol: str,
) -> None:
    source = f"int main() {{ {symbol}(); return 0; }}"
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-owned C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    ("statement", "symbol"),
    (
        ("__fn_ptr<void, void*> hook = __btrc_Box_destructor_hook; hook(null);", "__btrc_Box_destructor_hook"),
        ("void* hook = (void*)&__btrc_Box_destructor_hook;", "__btrc_Box_destructor_hook"),
        ("((__fn_ptr<void, void*>)__btrc_Box_destructor_hook)(null);", "__btrc_Box_destructor_hook"),
        ("void* hook = (void*)&Vault_secret;", "Vault_secret"),
    ),
)
def test_generated_symbol_value_reference_fails_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    statement: str,
    symbol: str,
) -> None:
    source = (
        "class Box { public void __del__() {} } class Vault { private int secret() { return 42; } } int main() { "
        + statement
        + " return 0; }"
    )
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


def test_generic_intrinsic_values_are_not_runtime_symbols(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            __fn_ptr<bool, int, int> equal = __btrc_eq;
            return equal(1, 1) ? 0 : 1;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-owned C symbol '__btrc_eq'" in result.stderr


def test_nonclaimed_c_interop_name_is_not_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {}
        extern int Box_destroy_external();
        int main() { return Box_destroy_external(); }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode == 0, result.stderr


def test_lexical_callables_may_shadow_generated_global_symbols(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {}
        int invoke(__fn_ptr<int> Box_new) { return Box_new(); }
        int main() {
            __fn_ptr<int> Box_new = () => 20;
            return Box_new() + invoke(() => 22) == 42 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generated-symbol-lexical-shadow",
    ):
        _strict_matrix(artifact, tmp_path)


def test_hosted_runtime_helper_values_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            __fn_ptr<void*, size_t, size_t> allocate = &__btrc_safe_calloc;
            return 0;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "Hosted function '__btrc_safe_calloc' cannot be stored or forwarded as a value" in result.stderr


def test_supported_runtime_helper_direct_calls_are_strict_c(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            void* storage = __btrc_safe_calloc(1, 4);
            char* copy = __btrc_strdup("ok");
            int length = __btrc_string_length(copy);
            bool equal = __btrc_eq(length, 2);
            free(copy);
            free(storage);
            return equal ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generated-symbol-runtime-helper-direct-call",
    ):
        _strict_matrix(artifact, tmp_path)


def test_unused_generic_method_is_not_emitted_unspecialized_with_no_dce(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {
            public U identity<U>(U value) { return value; }
        }
        int main() {
            Box box = new Box();
            delete box;
            return 0;
        }
    """
    for artifact in compile_no_dce_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generic-method-no-dce",
    ):
        assert "Box_identity(" not in artifact[1].read_text()
        _strict_matrix(artifact, tmp_path)


LIFECYCLE_SOURCE = """
    int destroyed = 0;
    class Box {
        public int value;
        public Box(int value) { self.value = value; }
        private int secret() { return self.value; }
        public int read() { return self.secret(); }
        public void __del__() { destroyed += 1; }
    }
    int main() {
        Box box = new Box(42);
        if (box.read() != 42) { return 1; }
        delete box;
        return box == null && destroyed == 1 ? 0 : 2;
    }
"""


def test_source_lifecycle_api_is_strict_and_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        LIFECYCLE_SOURCE,
        "generated-symbol-source-lifecycle",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-generated-symbol-lifecycle-san",
            toolchain,
        )
