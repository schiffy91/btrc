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


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["btrc"] + argv)
    m.main()


def compile_btrc(tmp_path, monkeypatch, source, *flags, name="prog"):
    """Compile *source* with *flags*, return (c_text, out_path)."""
    src = tmp_path / f"{name}.btrc"
    src.write_text(source)
    out = tmp_path / f"{name}.c"
    run_main(monkeypatch, ["--no-cache", *flags, str(src), "-o", str(out)])
    return out.read_text(), out


PURE = "int sq(int n) { return n * n; }\nint main() { return sq(7); }\n"
PRINTS = 'int main() { print("hi"); return 0; }\n'
USES_VECTOR = ("int main() { Vector<int> v = [1, 2, 3]; v.push(4);\n"
               "  int t = 0; for x in v { t = t + x; } print(t); return 0; }\n")


# --- --debug / #line source map ---

def test_debug_emits_line_directives_to_btrc(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PURE, "--debug")
    assert '#line 1 "' in c and "prog.btrc" in c
    assert '#line 2 "' in c  # both statements mapped

def test_no_debug_has_no_line_directives(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PURE)
    assert "#line" not in c

def test_debug_maps_synthesized_code_to_generated_c(tmp_path, monkeypatch):
    # Synthesized functions (e.g. a class's allocating `_new` wrapper) have no
    # btrc statements; they must map to the generated .c, not auto-increment into
    # bogus btrc lines that would mis-bind breakpoints to glue code.
    src = ("class P { public int x; public P(int x) { self.x = x; } }\n"
           "int main() { P p = P(5); return p.x; }\n")
    c, out = compile_btrc(tmp_path, monkeypatch, src, "--debug", name="cls")
    assert f'"{os.path.abspath(str(out))}"' in c


# --- --freestanding / btrc_rt.h seam ---

def test_freestanding_pure_is_self_contained(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PURE, "--freestanding", "--no-stdlib")
    assert "#include <" not in c
    assert "btrc_rt.h" not in c  # references no runtime symbol

def test_freestanding_routes_runtime_through_seam(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PRINTS, "--freestanding", "--no-stdlib")
    assert "#include <" not in c          # no hosted libc leaks
    assert '#include "btrc_rt.h"' in c    # printf routed through the seam

def test_freestanding_writes_runtime_header(tmp_path, monkeypatch):
    compile_btrc(tmp_path, monkeypatch, PRINTS, "--freestanding")
    rt = tmp_path / "btrc_rt.h"
    assert rt.exists()
    text = rt.read_text()
    assert "BTRC_FREESTANDING" in text and "btrc_rt.h" in text

def test_freestanding_stdlib_program_has_no_system_includes(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, USES_VECTOR, "--freestanding")
    assert "#include <" not in c
    assert '#include "btrc_rt.h"' in c


# --- dead-code elimination + --no-dce ---

def test_dce_keeps_one_liner_small(tmp_path, monkeypatch):
    c, _ = compile_btrc(tmp_path, monkeypatch, PRINTS)
    # Before the proto/struct DCE fix this dragged in the whole stdlib (~6k lines).
    assert len(c.splitlines()) < 1500

def test_no_dce_emits_full_stdlib(tmp_path, monkeypatch):
    lean, _ = compile_btrc(tmp_path, monkeypatch, PRINTS, name="lean")
    full, _ = compile_btrc(tmp_path, monkeypatch, PRINTS, "--no-dce", name="full")
    assert len(full.splitlines()) > 3 * len(lean.splitlines())

def test_dce_prunes_unused_stdlib_structs(tmp_path, monkeypatch):
    # A program that never touches Regex must not emit its struct (whose field
    # type would force <regex.h> in freestanding builds).
    c, _ = compile_btrc(tmp_path, monkeypatch, USES_VECTOR)
    assert "regex_t" not in c


# --- the debug build is real: it compiles and runs ---

@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("nm") is None,
                    reason="needs gcc + nm")
def test_freestanding_stdlib_links_with_zero_libc(tmp_path, monkeypatch):
    # A Vector+string program built --freestanding, compiled against the
    # reference runtime with no hosted libc, must have ZERO undefined symbols
    # (the kernel/embedded readiness guarantee for the core stdlib subset).
    c, out = compile_btrc(tmp_path, monkeypatch, USES_VECTOR, "--freestanding", name="fk")
    obj = tmp_path / "fk.o"
    r = subprocess.run(
        ["gcc", "-std=c11", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
         "-nostdlib", "-DBTRC_FREESTANDING", "-DBTRC_FREESTANDING_IMPL",
         f"-I{tmp_path}", "-c", str(out), "-o", str(obj)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    nm = subprocess.run(["nm", str(obj)], capture_output=True, text=True)
    undefined = [ln for ln in nm.stdout.splitlines() if " U " in ln]
    assert not undefined, "freestanding object has external deps:\n" + "\n".join(undefined)


@pytest.mark.skipif(shutil.which("gcc") is None and shutil.which("cc") is None,
                    reason="no C compiler")
def test_freestanding_runtime_formatter(tmp_path):
    # The reference runtime's printf/snprintf must format ints, strings, hex,
    # width/zero-pad, and floats correctly (it has no libc to fall back on).
    from src.compiler.python.freestanding import RUNTIME_HEADER
    (tmp_path / "btrc_rt.h").write_text(RUNTIME_HEADER)
    harness = r'''
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
'''
    (tmp_path / "h.c").write_text(harness)
    cc = shutil.which("gcc") or shutil.which("cc")
    binp = tmp_path / "h"
    r = subprocess.run([cc, "-std=c11", "-w", f"-I{tmp_path}", str(tmp_path / "h.c"),
                        "-o", str(binp)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    run = subprocess.run([str(binp)], capture_output=True, text=True)
    assert run.returncode == 0, f"{run.returncode} formatter mismatch(es)"


@pytest.mark.skipif(shutil.which("cc") is None and shutil.which("gcc") is None,
                    reason="no C compiler")
def test_debug_build_compiles_and_runs(tmp_path, monkeypatch):
    cc = shutil.which("cc") or shutil.which("gcc")
    c, out = compile_btrc(tmp_path, monkeypatch, USES_VECTOR, "--debug")
    binary = tmp_path / "prog_bin"
    r = subprocess.run([cc, "-std=c11", "-g", str(out), "-o", str(binary),
                        "-lm", "-lpthread"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0
    assert run.stdout.strip() == "10"
