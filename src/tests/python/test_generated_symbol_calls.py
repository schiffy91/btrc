"""Source boundaries for compiler-owned generated C symbols."""

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<generated-symbol-call>").tokenize()).parse()
    return Analyzer().analyze(program).errors


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
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
def test_direct_generated_symbol_calls_are_rejected(source: str, symbol: str) -> None:
    errors = _errors(source)
    assert any(f"compiler-generated C symbol '{symbol}'" in error for error in errors)


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
def test_unresolved_compiler_owned_names_are_rejected(symbol: str) -> None:
    errors = _errors(f"int main() {{ {symbol}(); return 0; }}")
    assert any(f"compiler-owned C symbol '{symbol}'" in error for error in errors)


@pytest.mark.parametrize(
    ("statement", "symbol"),
    (
        ("__fn_ptr<void, void*> hook = __btrc_Box_destructor_hook; hook(null);", "__btrc_Box_destructor_hook"),
        ("void* hook = (void*)&__btrc_Box_destructor_hook;", "__btrc_Box_destructor_hook"),
        ("((__fn_ptr<void, void*>)__btrc_Box_destructor_hook)(null);", "__btrc_Box_destructor_hook"),
        ("void* hook = (void*)&Vault_secret;", "Vault_secret"),
    ),
)
def test_generated_symbol_value_reference_is_rejected(statement: str, symbol: str) -> None:
    source = (
        "class Box { public void __del__() {} } class Vault { private int secret() { return 42; } } int main() { "
        + statement
        + " return 0; }"
    )
    errors = _errors(source)
    assert any(f"compiler-generated C symbol '{symbol}'" in error for error in errors)


def test_runtime_helper_values_are_rejected_while_direct_calls_remain_supported() -> None:
    value_source = """
        int main() {
            __fn_ptr<void*, size_t, size_t> allocate = &__btrc_safe_calloc;
            return 0;
        }
    """
    errors = _errors(value_source)
    assert len(errors) == 1
    assert "Hosted function '__btrc_safe_calloc' cannot be stored or forwarded as a value" in errors[0]

    direct_source = """
        int main() {
            void* storage = __btrc_safe_calloc(1, 4);
            bool equal = __btrc_eq(20 + 22, 42);
            free(storage);
            return equal ? 0 : 1;
        }
    """
    assert _errors(direct_source) == []


def test_generic_intrinsics_are_not_first_class_runtime_symbols() -> None:
    errors = _errors("int main() { __fn_ptr<bool, int, int> equal = __btrc_eq; return equal(1, 1) ? 0 : 1; }")
    assert any("compiler-owned C symbol '__btrc_eq'" in error for error in errors)


def test_source_calls_and_nonclaimed_c_names_remain_valid() -> None:
    source = """
        class Box {
            public int value;
            public Box(int value) { self.value = value; }
            public int read() { return self.value; }
        }
        extern int Box_destroy_external();
        int main() {
            Box box = new Box(42);
            int value = box.read();
            delete box;
            return value == 42 ? 0 : Box_destroy_external();
        }
    """
    assert _errors(source) == []


def test_local_callables_may_shadow_generated_global_symbols() -> None:
    source = """
        class Box {}
        int invoke(__fn_ptr<int> Box_new) { return Box_new(); }
        int main() {
            __fn_ptr<int> Box_new = () => 20;
            return Box_new() + invoke(() => 22) == 42 ? 0 : 1;
        }
    """
    assert _errors(source) == []
