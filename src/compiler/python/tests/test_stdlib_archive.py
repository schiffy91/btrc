"""Tests for the precompiled-stdlib archive (--build-stdlib / --stdlib).

The fast unit tests exercise the pure transform/partition logic; the end-to-end
test proves the payoff: a program compiled in *reference* mode (linking the
archive) produces byte-identical output to the same program compiled inline,
while emitting far less C.
"""

import os
import shutil
import subprocess
import sys

import pytest

from src.compiler.python import main as m
from src.compiler.python import stdlib_archive as sa


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["btrc"] + argv)
    m.main()


# A program that crosses the archive boundary in the ways that matter: temp
# strings (the string pool), a stdlib generic (Vector<string> from the archive),
# a user-type generic (Vector<Item> — NOT in the archive, emitted locally), and
# objects with destructors (the shared destroyed-pointer guard).
CROSS_BOUNDARY_PROG = """
class Item {
    public string name;
    public Item(string name) { self.name = name; }
    public string label() { return f"<{self.name}>"; }
}

int main() {
    Vector<string> tags = [];
    tags.push("a");
    tags.push("b");
    Map<string, int> seen = {};
    for t in tags { seen.put(t, seen.contains(t) ? seen.get(t) + 1 : 1); }

    Vector<Item> items = [];
    for i in range(3) { items.push(Item(f"i{i}")); }
    string out = "";
    for it in items { out = out + it.label(); }

    string x = "p" + "q";
    print(f"tags={tags.len} seen_a={seen.get(\\"a\\")} out={out} eq={x == \\"pq\\"}");
    return 0;
}
"""


# --------------------------------------------------------------------------
# unit tests — pure logic, no compiler/cc needed
# --------------------------------------------------------------------------

def test_forward_decl_name():
    assert sa._forward_decl_name("typedef struct Foo Foo;") == "Foo"
    assert sa._forward_decl_name("static int Bar_baz(Bar* self);") == "Bar_baz"
    assert sa._forward_decl_name("void btrc_Vector_int_push(btrc_Vector_int* v, int x);") \
        == "btrc_Vector_int_push"
    assert sa._forward_decl_name("/* just a comment */") is None


def test_externize_toplevel_strips_only_leading_static():
    src = "static int g = 0;\nstatic inline int f(void) {\n    static int local = 1;\n    return local;\n}"
    out = sa._externize_toplevel(src)
    assert out.startswith("int g = 0;")
    assert "\nint f(void) {" in out
    # An indented `static` inside the body must be preserved.
    assert "    static int local = 1;" in out


def test_brace_section_prototype():
    from src.compiler.python.ir.emitter import _brace_section_prototype
    assert _brace_section_prototype("void V_visit(V* s, void (*fn)(void**)) {\n  ;\n}") \
        == "void V_visit(V* s, void (*fn)(void**));"
    # Not a function definition → no prototype.
    assert _brace_section_prototype("int table[] = {1, 2, 3};") is None
    assert _brace_section_prototype("no braces here;") is None


def test_partition_drops_archive_symbols():
    """partition_for_archive removes exactly what the manifest provides and
    prepends the header include."""
    from src.compiler.python.ir.nodes import (
        IRFunctionDef, IRStructDef, IRModule, CType,
    )

    class _H:  # minimal helper stand-in
        def __init__(self, name):
            self.name = name

    mod = IRModule(
        includes=["stdio.h"],
        forward_decls=["typedef struct Std Std;", "typedef struct Usr Usr;"],
        struct_defs=[IRStructDef(name="Std", fields=[]),
                     IRStructDef(name="Usr", fields=[])],
        function_defs=[IRFunctionDef(name="Std_m", return_type=CType(text="void")),
                       IRFunctionDef(name="Usr_m", return_type=CType(text="void"))],
        helper_decls=[_H("__btrc_strcat"), _H("__btrc_user_only")],
    )
    manifest = {
        "types": ["Std"], "functions": ["Std_m"], "helpers": ["__btrc_strcat"],
        "forward_decls": ["typedef struct Std Std;"], "vtables": [],
        "globals": [], "raw_sections": [], "shared_helpers": [],
    }
    sa.partition_for_archive(mod, manifest, "btrc_stdlib.h")

    assert [s.name for s in mod.struct_defs] == ["Usr"]
    assert [f.name for f in mod.function_defs] == ["Usr_m"]
    assert [h.name for h in mod.helper_decls] == ["__btrc_user_only"]
    assert mod.forward_decls == ["typedef struct Usr Usr;"]
    assert mod.includes[0] == '#include "btrc_stdlib.h"'


# --------------------------------------------------------------------------
# build the archive
# --------------------------------------------------------------------------

def test_build_stdlib_writes_archive(tmp_path, monkeypatch, capsys):
    out = tmp_path / "std"
    run_main(monkeypatch, ["--build-stdlib", str(out)])
    assert "Built stdlib archive" in capsys.readouterr().out
    for name in (sa.HEADER_NAME, sa.IMPL_NAME, sa.MANIFEST_NAME):
        assert (out / name).exists(), name
    manifest = sa.load_manifest(str(out))
    # The archive must provide a substantial, real interface.
    assert len(manifest["functions"]) > 100
    assert "__btrc_destroyed_tracking" in manifest["shared_helpers"]
    # The header guards itself and declares (not defines) the shared state.
    header = (out / sa.HEADER_NAME).read_text()
    assert "#ifndef BTRC_STDLIB_H" in header
    assert "extern void** __btrc_destroyed;" in header


# --------------------------------------------------------------------------
# end-to-end: reference build == inline build, but smaller
# --------------------------------------------------------------------------

def test_reference_matches_inline_and_is_smaller(tmp_path, monkeypatch, capsys):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")

    std = tmp_path / "std"
    run_main(monkeypatch, ["--build-stdlib", str(std)])
    capsys.readouterr()
    subprocess.run(
        [cc, "-std=c11", "-O1", "-ffunction-sections", "-fdata-sections",
         "-c", str(std / sa.IMPL_NAME), "-o", str(std / "btrc_stdlib.o")],
        check=True, cwd=str(std))
    subprocess.run(["ar", "rcs", str(std / "libbtrc.a"), str(std / "btrc_stdlib.o")],
                   check=True)

    prog = tmp_path / "p.btrc"
    prog.write_text(CROSS_BOUNDARY_PROG)

    # Inline build.
    inline_c = str(tmp_path / "inline.c")
    run_main(monkeypatch, ["--no-cache", str(prog), "-o", inline_c])
    capsys.readouterr()
    inline_bin = str(tmp_path / "inline_bin")
    subprocess.run([cc, "-std=c11", inline_c, "-o", inline_bin, "-lm", "-lpthread"],
                   check=True)
    inline_out = subprocess.run([inline_bin], capture_output=True, text=True)

    # Reference build.
    ref_c = str(tmp_path / "ref.c")
    run_main(monkeypatch, ["--no-cache", "--stdlib", str(std), str(prog), "-o", ref_c])
    capsys.readouterr()
    ref_bin = str(tmp_path / "ref_bin")
    subprocess.run([cc, "-std=c11", f"-I{std}", ref_c, str(std / "libbtrc.a"),
                    "-o", ref_bin, "-lm", "-lpthread"], check=True)
    ref_out = subprocess.run([ref_bin], capture_output=True, text=True)

    # Byte-identical behaviour — the whole point.
    assert ref_out.returncode == 0, ref_out.stderr
    assert ref_out.stdout == inline_out.stdout
    assert "tags=2" in ref_out.stdout and "eq=true" in ref_out.stdout

    # And the reference TU is dramatically smaller (stdlib not inlined).
    inline_lines = len(open(inline_c).read().splitlines())
    ref_lines = len(open(ref_c).read().splitlines())
    assert ref_lines < inline_lines / 2
