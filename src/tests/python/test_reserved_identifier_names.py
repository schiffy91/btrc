"""C-reserved declaration and source-macro namespace boundaries."""

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<reserved-name>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


@pytest.mark.parametrize(
    ("source", "name"),
    (
        ("int __hidden() { return 0; } int main() { return 0; }", "__hidden"),
        ("int run(int _Value) { return _Value; } int main() { return 0; }", "_Value"),
        ("int main() { int __temporary = 0; return 0; }", "__temporary"),
        ("class Box<_T> {} int main() { return 0; }", "_T"),
        ("class Box { public int __field; } int main() { return 0; }", "__field"),
        (
            "class Box<T> { public T copy(T value) { T __tmp_1 = value; return __tmp_1; } } int main() { return 0; }",
            "__tmp_1",
        ),
        (
            "@gpu void kernel(int[] values, int __gid) { "
            "int i = gpu_id(); values[i] += __gid; } int main() { return 0; }",
            "__gid",
        ),
    ),
)
def test_c_reserved_source_bindings_are_rejected(source: str, name: str) -> None:
    errors = _errors(source)
    assert any(name in error and "reserved by C11" in error for error in errors)


@pytest.mark.parametrize(
    ("name", "prefix"),
    (
        ("__btrc_arc_release", "__btrc_"),
        ("__gpu_dispatch_1", "__gpu_"),
        ("btrc_runtime", "btrc_"),
    ),
)
def test_compiler_prefix_macros_are_rejected(name: str, prefix: str) -> None:
    errors = _errors(f"#define {name} 1\nint main() {{ return 0; }}")
    assert any(name in error and prefix in error for error in errors)


@pytest.mark.parametrize(
    "directive",
    (
        "#define/*gap*/free(value) 0",
        "#/*gap*/define free(value) 0",
        "#\vdefine free(value) 0",
    ),
)
def test_preprocessing_whitespace_cannot_hide_hosted_macro_name(directive: str) -> None:
    errors = _errors(f"{directive}\nint main() {{ return 0; }}")
    assert any("free" in error and "hosted C symbol" in error for error in errors)


def test_c_reserved_macro_is_rejected() -> None:
    errors = _errors("#define _Hidden 1\nint main() { return 0; }")
    assert any("Macro name '_Hidden' is reserved by C11" in error for error in errors)


def test_hosted_macro_parameter_names_remain_source_api() -> None:
    source = (
        "int ordered(int stdin, int stdout, int stderr) { "
        "return stdin * 100 + stdout * 10 + stderr; } "
        "int main() { return ordered(stderr=3, stdin=1, stdout=2) == 123 ? 0 : 1; }"
    )
    assert _errors(source) == []


def test_file_scope_underscore_is_rejected_but_local_is_valid() -> None:
    errors = _errors("int _private() { return 0; } int main() { return 0; }")
    assert any("'_private' is reserved by C11 at file scope" in error for error in errors)
    assert _errors("int main() { int _local = 42; return _local == 42 ? 0 : 1; }") == []


def test_file_scope_underscore_macro_is_rejected() -> None:
    errors = _errors("#define _private 1\nint main() { return 0; }")
    assert any("'_private' is reserved by C11 at file scope" in error for error in errors)


def test_uppercase_compiler_internal_reference_is_rejected() -> None:
    errors = _errors("int main() { return __BTRC_ARC_LIVE; }")
    assert any("compiler-owned C symbol '__BTRC_ARC_LIVE'" in error for error in errors)


def test_function_like_macro_collides_with_generated_class_symbol() -> None:
    errors = _errors("#define Box_new(value) (value)\nclass Box {} int main() { return 0; }")
    assert any("Box_new" in error and "collides with source macro" in error for error in errors)


@pytest.mark.parametrize(
    ("source", "symbol", "kind"),
    (
        (
            "#define CALL(value) Vault_secret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { return 0; }",
            "Vault_secret",
            "compiler-generated",
        ),
        (
            "#define STATE __BTRC_ARC_LIVE\nint main() { return 0; }",
            "__BTRC_ARC_LIVE",
            "compiler-owned",
        ),
        (
            "#undef Box_new\nclass Box {} int main() { return 0; }",
            "Box_new",
            "compiler-generated",
        ),
        (
            "#undef __btrc_safe_calloc\nint main() { return 0; }",
            "__btrc_safe_calloc",
            "compiler-owned",
        ),
        (
            "#define DROP(value) free(value)\nint main() { char* owner = null; DROP(owner); return 0; }",
            "free",
            "Raw lifetime consumer",
        ),
        (
            "#define WIPE(value) memset(value, 0, 8)\nint main() { return 0; }",
            "memset",
            "semantic call analysis",
        ),
        (
            "#define READ(fd, value) read(fd, value, 8)\nint main() { return 0; }",
            "read",
            "semantic call analysis",
        ),
        (
            "#define CLOSE(value) fclose(value)\nint main() { return 0; }",
            "fclose",
            "Raw lifetime consumer",
        ),
        (
            "#define FIND(value, needle) strstr(value, needle)\nint main() { return 0; }",
            "strstr",
            "semantic call analysis",
        ),
    ),
)
def test_preprocessor_replacements_and_undef_cannot_bypass_boundaries(
    source: str,
    symbol: str,
    kind: str,
) -> None:
    errors = _errors(source)
    assert any(symbol in error and kind in error for error in errors)


@pytest.mark.parametrize("operator", ("##", "%:%:", "??=??="))
def test_macro_token_pasting_cannot_synthesize_generated_symbols(operator: str) -> None:
    source = (
        f"#define CALL(value) Vault_{operator}secret(value)\n"
        "class Vault { private int secret() { return 42; } } "
        "int main() { return 0; }"
    )
    errors = _errors(source)
    assert any("CALL" in error and "token pasting" in error for error in errors)


def test_multiline_macro_replacement_is_validated() -> None:
    source = (
        "#define CALL(value) \\\n Vault_secret(value)\n"
        "class Vault { private int secret() { return 42; } } "
        "int main() { return 0; }"
    )
    errors = _errors(source)
    assert any("Vault_secret" in error and "compiler-generated" in error for error in errors)


@pytest.mark.parametrize(
    ("replacement", "symbol", "diagnostic"),
    (
        ("Vault_" + "\\" + "\n" + "secret(value)", "Vault_secret", "compiler-generated"),
        ("fr" + "\\" + "\n" + "ee(value)", "free", "Raw lifetime consumer"),
        ("Vault_#" + "\\" + "\n" + "#secret(value)", "CALL", "token pasting"),
        ("Vault_??/\nsecret(value)", "Vault_secret", "compiler-generated"),
        ("fr??/\nee(value)", "free", "Raw lifetime consumer"),
    ),
)
def test_line_splicing_cannot_hide_macro_replacement_symbols(
    replacement: str,
    symbol: str,
    diagnostic: str,
) -> None:
    source = (
        f"#define CALL(value) {replacement}\n"
        "class Vault { private int secret() { return 42; } } "
        "int main() { char* value = null; CALL(value); return 0; }"
    )
    errors = _errors(source)
    assert any(symbol in error and diagnostic in error for error in errors)


def test_macro_literals_and_parameters_are_not_symbol_references() -> None:
    source = """
        #define LABEL "## Vault_secret"
        #define IDENTITY(Vault_secret) Vault_secret
        #define FREE_IDENTITY(free) free
        class Vault { private int secret() { return 42; } }
        int main() { return 0; }
    """
    assert _errors(source) == []


def test_read_only_scalar_hosted_macro_reference_is_allowed() -> None:
    source = (
        '#define LENGTH(value) strlen(value)\nint main() { string text = "abc"; return LENGTH(text) == 3 ? 0 : 1; }'
    )
    assert _errors(source) == []


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "void kernel__gpuitem() {} int main() { return 0; }",
            "kernel__gpuitem",
        ),
        (
            "class Box { public U identity<U>(U value) { return value; } } "
            "int Box_identity_int(Box receiver, int value) { return value; } "
            "int main() { Box box = new Box(); return box.identity(42); }",
            "Box_identity_int",
        ),
    ),
)
def test_gpu_and_generic_generated_collisions_are_rejected(
    source: str,
    symbol: str,
) -> None:
    errors = _errors(source)
    assert any(symbol in error and "collides" in error for error in errors)


def test_generated_symbol_cannot_enter_hosted_abi_namespace() -> None:
    source = "class O { public int CLOEXEC() { return 1; } } int main() { return 0; }"
    errors = _errors(source)
    assert any("O_CLOEXEC" in error and "hosted C symbol" in error for error in errors)


def test_magic_methods_and_nonprefix_btrc_names_remain_valid() -> None:
    source = """
        #define btrcTestMacro 20
        int btrcTestValue() { return 22; }
        class Number {
            public int value;
            public Number(int value) { self.value = value; }
            public Number __add__(Number other) {
                return new Number(self.value + other.value);
            }
            public bool __eq__(Number other) {
                return self.value == other.value;
            }
            public Number __neg__() { return new Number(-self.value); }
            public void __del__() {}
        }
        int main() {
            Number left = new Number(20);
            Number right = new Number(22);
            Number total = left + right;
            Number negative = -left;
            return total.value == 42 && negative.value == -20
                && left == left
                && btrcTestMacro == 20
                && btrcTestValue() == 22 ? 0 : 1;
        }
    """
    assert _errors(source) == []


def test_trusted_native_prototype_but_not_definition_is_allowed() -> None:
    assert _errors("extern bool btrc_gpu_available(); int main() { return 0; }") == []
    errors = _errors("bool btrc_gpu_available() { return true; } int main() { return 0; }")
    assert any("compiler-reserved 'btrc_' prefix" in error for error in errors)
