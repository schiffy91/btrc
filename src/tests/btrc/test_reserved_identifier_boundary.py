"""Dual-frontend C-reserved declaration and macro boundaries."""

import re
from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    ("source", "name", "diagnostic"),
    (
        ("int __hidden() { return 0; } int main() { return 0; }", "__hidden", "reserved by C11"),
        ("int run(int _Value) { return _Value; } int main() { return 0; }", "_Value", "reserved by C11"),
        ("int main() { int __temporary = 0; return 0; }", "__temporary", "reserved by C11"),
        ("class Box<_T> {} int main() { return 0; }", "_T", "reserved by C11"),
        ("class Box { public int __field; } int main() { return 0; }", "__field", "reserved by C11"),
        (
            "int _private() { return 0; } int main() { return 0; }",
            "_private",
            "reserved by C11 at file scope",
        ),
        (
            "class Box<T> { public T copy(T value) { T __tmp_1 = value; return __tmp_1; } } int main() { return 0; }",
            "__tmp_1",
            "reserved by C11",
        ),
        (
            "@gpu void kernel(int[] values, int __gid) { "
            "int i = gpu_id(); values[i] += __gid; } int main() { return 0; }",
            "__gid",
            "reserved by C11",
        ),
        (
            "#define __btrc_arc_release 1\nint main() { return 0; }",
            "__btrc_arc_release",
            "compiler-reserved '__btrc_' prefix",
        ),
        (
            "#define __gpu_dispatch_1 1\nint main() { return 0; }",
            "__gpu_dispatch_1",
            "compiler-reserved '__gpu_' prefix",
        ),
        (
            "#define btrc_runtime 1\nint main() { return 0; }",
            "btrc_runtime",
            "compiler-reserved 'btrc_' prefix",
        ),
        (
            "#define _Hidden 1\nint main() { return 0; }",
            "_Hidden",
            "reserved by C11",
        ),
        (
            "#define _private 1\nint main() { return 0; }",
            "_private",
            "reserved by C11 at file scope",
        ),
        (
            "int main() { return __BTRC_ARC_LIVE; }",
            "__BTRC_ARC_LIVE",
            "compiler-owned C symbol",
        ),
        (
            "#define Box_new(value) (value)\nclass Box {} int main() { return 0; }",
            "Box_new",
            "collid",
        ),
        (
            "#define CALL(value) Vault_secret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { return 0; }",
            "Vault_secret",
            "compiler-generated C symbol",
        ),
        (
            "#define STATE __BTRC_ARC_LIVE\nint main() { return 0; }",
            "__BTRC_ARC_LIVE",
            "compiler-owned C symbol",
        ),
        (
            "#define CALL(value) Vault_##secret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { return 0; }",
            "CALL",
            "token pasting",
        ),
        (
            "#define CALL(value) \\\n Vault_secret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { return 0; }",
            "Vault_secret",
            "compiler-generated C symbol",
        ),
        (
            "#undef Box_new\nclass Box {} int main() { return 0; }",
            "Box_new",
            "compiler-generated C symbol",
        ),
        (
            "#undef __btrc_safe_calloc\nint main() { return 0; }",
            "__btrc_safe_calloc",
            "compiler-owned C symbol",
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
        (
            "#define DROP(value) fr" + "\\" + "\n" + "ee(value)\n"
            "int main() { char* owner = null; DROP(owner); return 0; }",
            "free",
            "Raw lifetime consumer",
        ),
        (
            "#define DROP(value) fr??/\nee(value)\nint main() { char* owner = null; DROP(owner); return 0; }",
            "free",
            "Raw lifetime consumer",
        ),
        (
            "#define CALL(value) Vault_??/\nsecret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { char* value = null; CALL(value); return 0; }",
            "Vault_secret",
            "compiler-generated C symbol",
        ),
        (
            "#/*gap*/define free(value) 0\nint main() { return 0; }",
            "free",
            "hosted C symbol",
        ),
        (
            "#define CALL(value) Vault_" + "\\" + "\n" + "secret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { char* value = null; CALL(value); return 0; }",
            "Vault_secret",
            "compiler-generated C symbol",
        ),
        (
            "#define CALL(value) Vault_#" + "\\" + "\n" + "#secret(value)\n"
            "class Vault { private int secret() { return 42; } } "
            "int main() { char* value = null; CALL(value); return 0; }",
            "CALL",
            "token pasting",
        ),
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "void kernel__gpuitem() {} int main() { return 0; }",
            "kernel__gpuitem",
            "collid",
        ),
        (
            "class Box { public U identity<U>(U value) { return value; } } "
            "int Box_identity_int(Box receiver, int value) { return value; } "
            "int main() { Box box = new Box(); return box.identity(42); }",
            "Box_identity_int",
            "collid",
        ),
        (
            "class O { public int CLOEXEC() { return 1; } } int main() { return 0; }",
            "O_CLOEXEC",
            "hosted C symbol",
        ),
        (
            "enum { EINVAL = 1 }; int main() { return EINVAL; }",
            "EINVAL",
            "automatically included C macro",
        ),
    ),
)
def test_reserved_and_generated_names_fail_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    name: str,
    diagnostic: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert name in result.stderr
        assert diagnostic in result.stderr


def test_magic_methods_and_nonprefix_btrc_names_run_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #define btrcTestMacro 20
        #define GENERATED_LABEL "## Number___add__"
        #define IDENTITY(Number___add__) Number___add__
        #define FREE_IDENTITY(free) free
        #define LENGTH(value) strlen(value)
        extern bool btrc_gpu_available();
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
            int _local = 0;
            string text = "abc";
            Number left = new Number(20);
            Number right = new Number(22);
            Number total = left + right;
            Number negative = -left;
            return total.value == 42 && negative.value == -20
                && left == left
                && _local == 0
                && LENGTH(text) == 3
                && btrcTestMacro == 20
                && btrcTestValue() == 22 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "reserved-name-magic-methods",
    ):
        _strict_matrix(artifact, tmp_path)


def test_named_enum_value_in_hosted_macro_namespace_runs_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <errno.h>
        enum Error { EINVAL = 7 };
        int main() { return EINVAL == 7 ? 0 : 1; }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "named-enum-hosted-macro",
    ):
        _strict_matrix(artifact, tmp_path)


def test_hosted_macro_parameter_names_preserve_named_argument_api(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int ordered(int stdin, int stdout, int stderr) {
            return stdin * 100 + stdout * 10 + stderr;
        }
        int main() {
            return ordered(stderr=3, stdin=1, stdout=2) == 123 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "hosted-macro-parameter-api",
    ):
        _strict_matrix(artifact, tmp_path)


def test_hosted_macro_parameter_names_cover_generated_c_boundaries(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int ordinary(int stdin, int stdout = stdin + 1) {
            return stdout;
        }

        class Parent {
            public int pass(int stderr) { return stderr; }
        }
        class Child extends Parent {}

        class Counter {
            public int value;
            public Counter(int stdin) { self.value = stdin; }
            public int add(int stdout, int stderr = stdout + 1) {
                return self.value + stderr;
            }
        }

        class Box<T> {
            public T value;
            public Box(T stdin) { self.value = stdin; }
            public T choose(T stdout, T stderr = stdout) { return stderr; }
            public U echo<U>(U stdin) { return stdin; }
            public Packet pack(int stdin) {
                return Packet.Triple(stdout=2, stdin=stdin);
            }
        }

        enum class Packet {
            Triple(int stdin, int stdout, int stderr = stdout + 1)
        }

        int lambdaPaths(int stdout) {
            var block = (int stdin) => { return stdin + stdout; };
            int immediate = ((int stderr) => stderr + stdout)(3);
            return block(2) + immediate;
        }

        int threadPath(int stderr) {
            Thread<int> worker = spawn(() => stderr + 1);
            return worker.join();
        }

        int main() {
            Counter counter = new Counter(stdin=10);
            Child child = new Child();
            Box<int> box = new Box<int>(stdin=20);
            Packet packet = Packet.Triple(stdout=2, stdin=1);
            Packet genericPacket = box.pack(stdin=4);
            return ordinary(stdin=4) == 5
                && counter.add(stdout=6) == 17
                && child.pass(stderr=8) == 8
                && box.choose(stdout=21) == 21
                && box.echo(stdin=22) == 22
                && packet.data.Triple.stdin == 1
                && packet.data.Triple.stdout == 2
                && packet.data.Triple.stderr == 3
                && genericPacket.data.Triple.stdin == 4
                && genericPacket.data.Triple.stdout == 2
                && genericPacket.data.Triple.stderr == 3
                && lambdaPaths(stdout=5) == 15
                && threadPath(stderr=40) == 41 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "hosted-macro-generated-c-boundaries",
    ):
        generated = artifact[1].read_text()
        assert "__btrc_source_stdin" in generated
        assert "__btrc_source_stdout" in generated
        assert "__btrc_source_stderr" in generated
        assert re.search(r"\bint (?:stdin|stdout|stderr)\b", generated) is None
        wrapper = re.search(
            r"static void\* __btrc_spawn_wrapper_\d+\(void\* __arg\) \{(.*?)^\}",
            generated,
            re.MULTILINE | re.DOTALL,
        )
        assert wrapper is not None
        assert len(re.findall(r"^\s*return\b", wrapper.group(1), re.MULTILINE)) == 1
        _strict_matrix(artifact, tmp_path)
