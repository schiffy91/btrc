"""Runtime parity contracts for self-hosted helper mirrors."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BTRCC_SOURCE = REPO / "src/compiler/btrc/btrcc_main.btrc"
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
CLANG = shutil.which("clang")

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture(scope="module")
def btrcc_driver(tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("selfhost-helper-mirrors")
    generated = output / "btrcc.c"
    binary = output / "btrcc"
    transpile = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(BTRCC_SOURCE),
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(output / "cache")},
        timeout=300,
    )
    assert transpile.returncode == 0 and generated.exists(), transpile.stderr
    compile_result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            str(generated),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        timeout=300,
    )
    assert compile_result.returncode == 0 and binary.exists(), compile_result.stderr
    return binary


def _emit(btrcc_driver: Path, tmp_path: Path, source: str) -> str:
    program = tmp_path / "helper_mirror.btrc"
    program.write_text(source)
    emitted = _run(
        [str(btrcc_driver), "--no-stdlib", str(program)],
        timeout=30,
    )
    assert emitted.returncode == 0 and emitted.stderr == ""
    return emitted.stdout


def _compile(tmp_path: Path, source_text: str) -> Path:
    source = tmp_path / "helper_mirror.c"
    binary = tmp_path / "helper_mirror"
    source.write_text(source_text)
    compiled = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        timeout=30,
    )
    assert compiled.returncode == 0 and binary.exists(), compiled.stderr
    return binary


def test_mirrored_helpers_execute_without_libm(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _emit(
        btrcc_driver,
        tmp_path,
        "#include <assert.h>\n"
        "int main() {\n"
        '    assert("  +12tail".toLong() == 12);\n'
        '    assert("999999999999999999999999".toInt() == 2147483647);\n'
        '    assert("yes".toBool() && !"false".toBool() && !"0".toBool());\n'
        "    assert(7.9 % 2.0 == 1);\n"
        "    uint zeroHash = (uint)__btrc_hash_real(0.0);\n"
        "    uint negativeZeroHash = (uint)__btrc_hash_real(-0.0);\n"
        "    assert(zeroHash == negativeZeroHash);\n"
        "    uint infinityHash = (uint)__btrc_hash_real(INFINITY);\n"
        "    uint sameInfinityHash = (uint)__btrc_hash_real(INFINITY);\n"
        "    assert(infinityHash == sameInfinityHash);\n"
        "    return 0;\n"
        "}\n",
    )

    for obsolete in (
        "strtol(",
        "truncl(",
        "isfinite(",
        "isnan(",
        "isinf(",
        "signbit(",
        "frexpl(",
        "fabsl(",
    ):
        assert obsolete not in generated
    assert "__btrc_parseBool" in generated
    assert "memcpy(bytes, &canonical, sizeof canonical);" in generated

    binary = _compile(tmp_path, generated)
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0
    assert executed.stdout == ""
    assert executed.stderr == ""


def test_real_modulo_rejects_open_cast_boundary_before_conversion(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _emit(
        btrcc_driver,
        tmp_path,
        "int main() {\n    double outside = 2147483648.0;\n    return outside % 2.0;\n}\n",
    )
    binary = _compile(tmp_path, generated)

    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 1
    assert executed.stdout == ""
    assert executed.stderr == "Floating modulo conversion out of range\n"


def test_nested_function_pointer_typedefs_are_dependency_ordered(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _emit(
        btrcc_driver,
        tmp_path,
        "#include <assert.h>\n"
        "int main() {\n"
        "    __fn_ptr<int, __fn_ptr<int, int> > callback = null;\n"
        "    assert(callback == null);\n"
        "    return 0;\n"
        "}\n",
    )

    binary = _compile(tmp_path, generated)
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0


@pytest.mark.skipif(not CLANG, reason="requires Clang's default depth limit")
def test_selfhost_long_string_concat_has_bounded_c_expression_depth(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    expression = " + ".join('"x"' for _ in range(500))
    generated = _emit(
        btrcc_driver,
        tmp_path,
        "string joined() { return "
        + expression
        + "; }\n"
        + "int main() { string value = joined(); "
        + "return value.length() == 500 ? 0 : 1; }\n",
    )
    source = tmp_path / "long_string_concat.c"
    binary = tmp_path / "long_string_concat"
    source.write_text(generated)
    compiled = _run(
        [
            CLANG,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        timeout=120,
    )
    assert compiled.returncode == 0 and binary.exists(), compiled.stderr
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0


def test_structured_arc_header_type_roots_callback_abi_helper(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _emit(
        btrcc_driver,
        tmp_path,
        "class Box {\n"
        "    public int value;\n"
        "    public Box(int value) { self.value = value; }\n"
        "}\n"
        "int main() {\n"
        "    Box box = new Box(42);\n"
        "    return box.value == 42 ? 0 : 1;\n"
        "}\n",
    )

    callback_types = generated.index("typedef struct __btrc_arc_header {")
    embedded_header = generated.index("__btrc_arc_header __arc;")
    assert callback_types < embedded_header

    binary = _compile(tmp_path, generated)
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0
    assert executed.stdout == ""
    assert executed.stderr == ""


def test_helper_name_in_string_literal_does_not_root_helper(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    generated = _emit(
        btrcc_driver,
        tmp_path,
        'int main() { string marker = "__btrc_replace"; return marker.length() == 14 ? 0 : 1; }\n',
    )

    assert "static inline char* __btrc_replace(" not in generated
    binary = _compile(tmp_path, generated)
    executed = _run([str(binary)], timeout=15)
    assert executed.returncode == 0


def test_thread_only_runtime_omits_optional_cycle_and_launder_callables(
    btrcc_driver: Path,
    tmp_path: Path,
) -> None:
    emitted = _run(
        [
            str(btrcc_driver),
            str(REPO / "src/tests/threads/test_thread_void.btrc"),
        ],
        timeout=120,
    )
    assert emitted.returncode == 0 and emitted.stderr == ""
    assert "static _Thread_local void** __btrc_suspects" not in emitted.stdout
    assert "static _Thread_local void* volatile __btrc_launder_slot" in emitted.stdout
    assert "static inline void __btrc_suspect(" not in emitted.stdout
    assert "static inline void* __btrc_launder(" not in emitted.stdout

    source = tmp_path / "thread_only.c"
    binary = tmp_path / "thread_only"
    source.write_text(emitted.stdout)
    compiled = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-pthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = _run([str(binary)], timeout=30)
    assert executed.returncode == 0
    assert executed.stdout == "PASS thread_void\n"
