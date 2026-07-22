"""End-to-end tests for the --debug, --freestanding, and --no-dce CLI flags.

These exercise the real frontend (stdlib composition, position mapping) via
main(), then inspect the generated C — the same path a user hits — so the
source-map (#line), freestanding seam, and dead-code elimination are protected
from regression.
"""

import os
import shutil
import subprocess
import sys

import pytest

import src.compiler.python.main as m
from src.compiler.python.ir.emitter_debug import _c_line_filename


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["btrc"] + argv)
    m.main()


def test_emit_modes_are_mutually_exclusive(monkeypatch, capsys):
    with pytest.raises(SystemExit) as error:
        run_main(monkeypatch, ["input.btrc", "--emit-tokens", "--emit-ast"])

    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def compile_btrc(tmp_path, monkeypatch, source, *flags, name="prog"):
    """Compile *source* with *flags*, return (c_text, out_path)."""
    src = tmp_path / f"{name}.btrc"
    src.write_text(source)
    out = tmp_path / f"{name}.c"
    run_main(monkeypatch, ["--no-cache", *flags, str(src), "-o", str(out)])
    return out.read_text(), out


PURE = "int sq(int n) { return n * n; }\nint main() { return sq(7); }\n"
PRINTS = 'int main() { print("hi"); return 0; }\n'
USES_VECTOR = (
    "import std.vector;\n"
    "int main() { Vector<int> v = [1, 2, 3]; v.push(4);\n  int t = 0; for x in v { t = t + x; } print(t); return 0; }\n"
)
USES_THREAD = "int main() { Thread<int> t = spawn(() => 42); return t.join() == 42 ? 0 : 1; }\n"
USES_CONVERSIONS = (
    'int main() { int i = "  -2147483649tail".toInt(); '
    'long n = "999999999999999999999999".toLong(); '
    'float f = "12.5tail".toFloat(); bool b = "false".toBool(); '
    "return i == INT_MIN && n == LONG_MAX && f == 12.5f && !b ? 0 : 1; }\n"
)
ZERO_LIBC_SETJMP_SHIM = r"""
typedef struct { int opaque; } jmp_buf[1];
static _Noreturn void btrc_test_longjmp(jmp_buf environment, int status) {
    (void)environment;
    (void)status;
    for (;;) {}
}
#define setjmp(environment) ((void)(environment), 0)
#define longjmp(environment, status) \
    btrc_test_longjmp((environment), (status))
"""
TLS_RUNTIME_SYMBOLS = {
    "__emutls_get_address",
    "___emutls_get_address",
    "__tlv_bootstrap",
    "___tlv_bootstrap",
}


# --- --debug / #line source map ---


def test_debug_emits_line_directives_to_btrc(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PURE, "--debug")
    assert '#line 1 "' in c and "prog.btrc" in c
    assert '#line 2 "' in c  # both statements mapped


def test_no_debug_has_no_line_directives(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PURE)
    assert "#line" not in c


def test_debug_filename_escaping_is_c11_safe():
    assert _c_line_filename('a\\b"c??/d\ne') == 'a\\\\b\\"c\\?\\?/d\\012e'


def test_debug_maps_synthesized_code_to_generated_c(tmp_path, monkeypatch):
    # Synthesized functions (e.g. a class's allocating `_new` wrapper) have no
    # btrc statements; they must map to the generated .c, not auto-increment into
    # bogus btrc lines that would mis-bind breakpoints to glue code.
    src = "class P { public int x; public P(int x) { self.x = x; } }\nint main() { P p = P(5); return p.x; }\n"
    c, out = compile_btrc(tmp_path, monkeypatch, src, "--debug", name="cls")
    assert f'"{os.path.abspath(str(out))}"' in c


# --- --freestanding / btrc_rt.h seam ---


def test_freestanding_pure_is_self_contained(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PURE, "--freestanding", "--no-stdlib")
    assert "#include <" not in c
    assert "btrc_rt.h" not in c  # references no runtime symbol


def test_freestanding_routes_runtime_through_seam(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PRINTS, "--freestanding", "--no-stdlib")
    assert "#include <" not in c  # no hosted libc leaks
    assert '#include "btrc_rt.h"' in c  # printf routed through the seam


def test_freestanding_writes_runtime_header(tmp_path, monkeypatch):
    compile_btrc(tmp_path, monkeypatch, PRINTS, "--freestanding")
    rt = tmp_path / "btrc_rt.h"
    assert rt.exists()
    text = rt.read_text()
    assert "BTRC_FREESTANDING" in text and "btrc_rt.h" in text
    assert "#include <limits.h>" in text


def test_freestanding_stdlib_program_has_no_system_includes(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, USES_VECTOR, "--freestanding")
    assert "#include <" not in c
    assert '#include "btrc_rt.h"' in c


@pytest.mark.skipif(shutil.which("cc") is None, reason="requires a hosted C11 compiler")
def test_freestanding_thread_feature_selects_pthread_seam(tmp_path, monkeypatch):
    c, out = compile_btrc(
        tmp_path,
        monkeypatch,
        USES_THREAD,
        "--freestanding",
        "--no-stdlib",
        name="freestanding_thread",
    )
    feature = "#define BTRC_RT_NEEDS_PTHREAD 1"
    seam = '#include "btrc_rt.h"'
    assert feature in c
    assert c.index(feature) < c.index(seam)

    executable = tmp_path / "freestanding_thread"
    subprocess.run(
        [
            shutil.which("cc"),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{tmp_path}",
            str(out),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run([str(executable)], check=True, timeout=30)


# --- dead-code elimination + --no-dce ---


def test_dce_keeps_one_liner_small(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PRINTS)
    # Before the proto/struct DCE fix this dragged in the whole stdlib (~6k lines).
    assert len(c.splitlines()) < 1500


def test_no_dce_emits_full_stdlib(tmp_path, monkeypatch):
    lean, _ = compile_btrc(tmp_path, monkeypatch, PRINTS, "--relaxed-imports", name="lean")
    full, _ = compile_btrc(
        tmp_path,
        monkeypatch,
        PRINTS,
        "--relaxed-imports",
        "--no-dce",
        name="full",
    )
    assert len(full.splitlines()) > 3 * len(lean.splitlines())


def test_dce_prunes_unused_stdlib_structs(tmp_path, monkeypatch):
    # A program that never touches Regex must not emit its struct (whose field
    # type would force <regex.h> in freestanding builds).
    c, _ = compile_btrc(tmp_path, monkeypatch, USES_VECTOR)
    assert "regex_t" not in c


# --- the debug build is real: it compiles and runs ---


@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("nm") is None, reason="needs gcc + nm")
@pytest.mark.parametrize(
    "program",
    (USES_VECTOR, USES_CONVERSIONS),
    ids=("collections", "numeric-conversions"),
)
def test_freestanding_stdlib_links_with_zero_libc(tmp_path, monkeypatch, program):
    # Reached cleanup guards use a target-owned non-local-control-flow seam.
    # Core programs then need no libc symbols; C11 TLS may use compiler support.
    generated, out = compile_btrc(tmp_path, monkeypatch, program, "--freestanding", name="fk")
    setjmp_shim = tmp_path / "btrc_test_setjmp.h"
    # This link-only test needs a target-owned seam, but never executes an
    # exception.  A tiny conforming stub keeps the object independent of libc
    # and works on targets where compiler setjmp builtins are unavailable.
    setjmp_shim.write_text(ZERO_LIBC_SETJMP_SHIM)
    obj = tmp_path / "fk.o"
    setjmp_flags = ["-DBTRC_RT_SETJMP_HEADER=<btrc_test_setjmp.h>"] if "BTRC_RT_NEEDS_SETJMP" in generated else []
    r = subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-nostdlib",
            "-DBTRC_FREESTANDING",
            "-DBTRC_FREESTANDING_IMPL",
            *setjmp_flags,
            f"-I{tmp_path}",
            "-c",
            str(out),
            "-o",
            str(obj),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    nm = subprocess.run(["nm", str(obj)], capture_output=True, text=True, timeout=30)
    undefined = [line for line in nm.stdout.splitlines() if " U " in line]
    allowed = TLS_RUNTIME_SYMBOLS if "_Thread_local" in generated else set()
    unexpected = [line for line in undefined if line.split()[-1] not in allowed]
    assert not unexpected, "freestanding object has external deps:\n" + "\n".join(unexpected)


@pytest.mark.skipif(shutil.which("gcc") is None and shutil.which("cc") is None, reason="no C compiler")
def test_freestanding_runtime_formatter(tmp_path):
    # The reference runtime's printf/snprintf must format ints, strings, hex,
    # width/zero-pad, and floats correctly (it has no libc to fall back on).
    from src.compiler.python.freestanding import RUNTIME_HEADER

    (tmp_path / "btrc_rt.h").write_text(RUNTIME_HEADER)
    harness = r"""
#define BTRC_FREESTANDING
#define BTRC_FREESTANDING_IMPL
#include "btrc_rt.h"
static int ck(const char *g, const char *w) { return strcmp(g, w) == 0 ? 0 : 1; }
int main(void) {
  char b[64]; int f = 0;
  snprintf(b, sizeof b, "%d", 42);          f += ck(b, "42");
  snprintf(b, sizeof b, "%d", -7);          f += ck(b, "-7");
  snprintf(b, sizeof b, "%s", "hi");        f += ck(b, "hi");
  snprintf(b, sizeof b, "%x", 255);         f += ck(b, "ff");
  snprintf(b, sizeof b, "%05d", 42);        f += ck(b, "00042");
  snprintf(b, sizeof b, "%f", 3.14159);     f += ck(b, "3.141590");
  snprintf(b, sizeof b, "%f", -2.5);        f += ck(b, "-2.500000");
  snprintf(b, sizeof b, "%.2f", 3.14159);   f += ck(b, "3.14");
  snprintf(b, sizeof b, "%.0f", 2.7);       f += ck(b, "3");
  snprintf(b, sizeof b, "v=%d s=%s", 5, "y"); f += ck(b, "v=5 s=y");
  return f;
}
"""
    (tmp_path / "h.c").write_text(harness)
    cc = shutil.which("gcc") or shutil.which("cc")
    binp = tmp_path / "h"
    r = subprocess.run(
        [cc, "-std=c11", "-w", f"-I{tmp_path}", str(tmp_path / "h.c"), "-o", str(binp)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    run = subprocess.run([str(binp)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, f"{run.returncode} formatter mismatch(es)"


@pytest.mark.skipif(shutil.which("cc") is None and shutil.which("gcc") is None, reason="no C compiler")
def test_debug_build_compiles_and_runs(tmp_path, monkeypatch):
    cc = shutil.which("cc") or shutil.which("gcc")
    _c, out = compile_btrc(tmp_path, monkeypatch, USES_VECTOR, "--debug")
    binary = tmp_path / "prog_bin"
    r = subprocess.run(
        [cc, "-std=c11", "-g", str(out), "-o", str(binary), "-lm", "-lpthread"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0
    assert run.stdout.strip() == "10"
