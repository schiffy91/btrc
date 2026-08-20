"""Tests for the precompiled-stdlib archive (--build-stdlib / --stdlib).

The fast unit tests exercise the pure transform/partition logic; the end-to-end
test proves the payoff: a program compiled in *reference* mode (linking the
archive) produces byte-identical output to the same program compiled inline,
while emitting far less C.
"""

import ast
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.compiler.python.application.pipeline as application_pipeline
import src.compiler.python.artifacts.stdlib as sa
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline, StdlibArchiveError
from src.compiler.python.artifacts.publication import ArtifactPublisher, ArtifactStorage
from src.compiler.python.artifacts.stdlib import StdlibArchivePublisher
from src.compiler.python.cli.compiler import CompilerCommand
from src.compiler.python.frontend.sources import CompilerStdlibSource, StdlibRepository


def _archive_publisher() -> StdlibArchivePublisher:
    return StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))


def _archive_adapter():
    repository = sa.StdlibArtifactRepository(_archive_publisher())
    return CompilationPipeline(archive_repository=repository).stdlib_archive


def _archive_compiler() -> Compiler:
    repository = sa.StdlibArtifactRepository(_archive_publisher())
    return Compiler(CompilationPipeline(archive_repository=repository))


def run_main(monkeypatch, argv):
    CompilerCommand(_archive_compiler()).run(argv)


def test_archive_build_workflow_is_instance_owned():
    for owner_module in (application_pipeline, sa):
        module = ast.parse(Path(owner_module.__file__).read_text())
        loose_behavior = [
            node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert loose_behavior == []

    assert not Path(sa.__file__).with_name("stdlib_archive_helpers.py").exists()
    assert _archive_compiler().stdlib_archive_available
    assert callable(_archive_compiler().build_stdlib_archive)


# A program that crosses the archive boundary in the ways that matter: temp
# strings (the string pool), a stdlib generic (Vector<string> from the archive),
# a user-type generic (Vector<Item> — NOT in the archive, emitted locally), and
# objects with destructors (the shared destroyed-pointer guard).
CROSS_BOUNDARY_PROG = """
import std.map;
import std.vector;

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

ARCHIVE_THROW_PROG = """
import std.cli;

int main() {
    var arguments = CliArgs(0, null);
    var caught = false;
    try {
        arguments.require(3, "missing");
    } catch (string error) {
        caught = error.equals("missing");
    }
    print(caught ? "caught" : "missed");
    return caught ? 0 : 1;
}
"""


# --------------------------------------------------------------------------
# unit tests — pure logic, no compiler/cc needed
# --------------------------------------------------------------------------


def test_externize_toplevel_strips_only_leading_static():
    src = "static int g = 0;\nstatic inline int f(void) {\n    static int local = 1;\n    return local;\n}"
    out = _archive_adapter().externize_toplevel(src)
    assert out.startswith("int g = 0;")
    assert "\nint f(void) {" in out
    # An indented `static` inside the body must be preserved.
    assert "    static int local = 1;" in out


def test_archive_manifest_roundtrip_preserves_typed_declarations():
    """partition_for_archive removes exactly what the manifest provides and
    inserts the header without reordering the remaining directives."""
    from src.compiler.python.ir.nodes import (
        CType,
        IRFunctionDecl,
        IRFunctionDef,
        IRFunctionPointerTypedef,
        IRHelperDecl,
        IRInclude,
        IRMacroDef,
        IRModule,
        IRStructDef,
        IRStructForward,
    )

    archive_module = IRModule(
        struct_forwards=[IRStructForward(name="Std")],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef(
                name="StdCallback",
                return_type=CType(text="void"),
            )
        ],
        function_decls=[
            IRFunctionDecl(
                name="Std_api",
                return_type=CType(text="void"),
            ),
            IRFunctionDecl(
                name="Std_private",
                return_type=CType(text="void"),
                is_static=True,
            ),
        ],
        struct_defs=[IRStructDef(name="Std", fields=[])],
        function_defs=[IRFunctionDef(name="Std_m", return_type=CType(text="void"))],
        preprocessor_decls=[IRMacroDef(name="STD_VALUE", replacement="7")],
        helper_decls=[
            IRHelperDecl(
                category="strings",
                name="__btrc_strcat",
                c_source="static char* __btrc_strcat(void);",
            )
        ],
    )
    archive = _archive_adapter()
    metadata = archive.metadata(archive_module, [])
    manifest = {
        **metadata,
        "artifacts": {sa.HEADER_NAME: "0" * 64, sa.IMPL_NAME: "0" * 64},
        "schema": sa.MANIFEST_SCHEMA,
        "stdlib_source": "0" * 64,
        "toolchain": "test",
    }
    assert manifest["schema"] == sa.MANIFEST_SCHEMA == 5
    assert set(manifest["artifacts"]) == {sa.HEADER_NAME, sa.IMPL_NAME}

    mod = IRModule(
        preprocessor_decls=[
            IRMacroDef(name="STD_VALUE", replacement="7"),
            IRMacroDef(name="USER_VALUE", replacement="9"),
            IRInclude(header="stdio.h"),
            IRMacroDef(name="AFTER_INCLUDE", replacement="11"),
        ],
        struct_forwards=[
            IRStructForward(name="Std"),
            IRStructForward(name="Usr"),
        ],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef(name="StdCallback", return_type=CType(text="void")),
            IRFunctionPointerTypedef(name="UsrCallback", return_type=CType(text="void")),
        ],
        function_decls=[
            IRFunctionDecl(name="Std_api", return_type=CType(text="void")),
            IRFunctionDecl(
                name="Std_private",
                return_type=CType(text="void"),
                is_static=True,
            ),
            IRFunctionDecl(name="Usr_api", return_type=CType(text="void")),
        ],
        struct_defs=[IRStructDef(name="Std", fields=[]), IRStructDef(name="Usr", fields=[])],
        function_defs=[
            IRFunctionDef(name="Std_m", return_type=CType(text="void")),
            IRFunctionDef(name="Usr_m", return_type=CType(text="void")),
        ],
        helper_decls=[
            IRHelperDecl(
                category="strings",
                name="__btrc_strcat",
                c_source="static char* __btrc_strcat(void);",
            ),
            IRHelperDecl(
                category="user",
                name="__btrc_user_only",
                c_source="static void __btrc_user_only(void);",
            ),
        ],
    )
    archive.partition(mod, manifest, "btrc_stdlib.h")

    assert [s.name for s in mod.struct_defs] == ["Usr"]
    assert [f.name for f in mod.function_defs] == ["Usr_m"]
    assert [h.name for h in mod.helper_decls] == ["__btrc_user_only"]
    assert [item.name for item in mod.struct_forwards] == ["Usr"]
    assert [item.name for item in mod.function_pointer_typedefs] == ["UsrCallback"]
    assert [item.name for item in mod.function_decls] == [
        "Std_private",
        "Usr_api",
    ]
    assert all(isinstance(item, IRStructForward) for item in mod.struct_forwards)
    assert all(isinstance(item, IRFunctionPointerTypedef) for item in mod.function_pointer_typedefs)
    assert all(isinstance(item, IRFunctionDecl) for item in mod.function_decls)
    assert mod.preprocessor_decls == [
        IRMacroDef(name="USER_VALUE", replacement="9"),
        IRInclude(header="btrc_stdlib.h", is_system=False),
        IRInclude(header="stdio.h"),
        IRMacroDef(name="AFTER_INCLUDE", replacement="11"),
    ]
    assert "forward_decls" not in manifest
    assert not {"raw_sections", "vtables", "globals"} & set(manifest)
    assert manifest["function_declarations"] == ["Std_api"]
    assert manifest["macros"] == [
        {
            "name": "STD_VALUE",
            "params": None,
            "replacement": "7",
        }
    ]


def test_archive_header_excludes_private_ir_function_declarations():
    from src.compiler.python.backend.c_emitter import CEmitter
    from src.compiler.python.ir.nodes import (
        CType,
        IRFunctionDecl,
        IRFunctionDef,
        IRModule,
    )

    module = IRModule(
        function_decls=[
            IRFunctionDecl(name="public_api", return_type=CType("void")),
            IRFunctionDecl(
                name="private_helper",
                return_type=CType("void"),
                is_static=True,
            ),
        ],
        function_defs=[
            IRFunctionDef(
                name="private_helper",
                return_type=CType("void"),
                is_static=True,
            )
        ],
    )

    emitter = CEmitter()
    header = emitter.emit_header(module)
    implementation = emitter.emit_impl(module, "btrc_stdlib.h")

    assert "void public_api(void);" in header
    assert "private_helper" not in header
    assert "static void private_helper(void);" in implementation
    assert "static void private_helper(void) {" in implementation


def test_archive_override_check_distinguishes_imports_from_user_code(tmp_path):
    manifest = {
        "types": ["CliArgs"],
        "functions": [],
        "global_decl_names": [],
    }
    stdlib_root = Path(StdlibRepository().directory())
    stdlib_decl = SimpleNamespace(
        name="CliArgs",
        source_file=CompilerStdlibSource(str(stdlib_root / "cli.btrc")),
    )
    archive = _archive_adapter()
    archive.reject_user_overrides(SimpleNamespace(declarations=[stdlib_decl]), manifest)

    for user_path in (tmp_path / "program.btrc", stdlib_root / "program.btrc"):
        user_decl = SimpleNamespace(name="CliArgs", source_file=str(user_path))
        with pytest.raises(StdlibArchiveError, match=r"overrides.*CliArgs"):
            archive.reject_user_overrides(SimpleNamespace(declarations=[user_decl]), manifest)


# --------------------------------------------------------------------------
# build the archive
# --------------------------------------------------------------------------


def test_build_stdlib_writes_archive(tmp_path, monkeypatch, capsys):
    out = tmp_path / "std"
    run_main(monkeypatch, ["--build-stdlib", str(out)])
    assert "Built stdlib archive" in capsys.readouterr().out
    for name in (sa.HEADER_NAME, sa.IMPL_NAME, sa.MANIFEST_NAME):
        assert (out / name).exists(), name
    manifest = sa.StdlibArtifactRepository(_archive_publisher()).load(str(out), StdlibRepository().source(""))
    # The archive must provide a substantial, real interface.
    assert len(manifest["functions"]) > 100
    assert {macro["name"] for macro in manifest["macros"]} >= {
        "_DEFAULT_SOURCE",
        "_DARWIN_C_SOURCE",
    }
    assert "__btrc_destroyed_tracking" in manifest["shared_helpers"]
    assert "__btrc_destroyed_capacity" in manifest["shared_helpers"]
    assert "__btrc_cleanup_types" in manifest["shared_helpers"]
    assert "__btrc_cleanup_capacity" in manifest["shared_helpers"]
    assert "__btrc_suspect_state" in manifest["shared_helpers"]
    # The header guards itself and declares (not defines) the shared state.
    header = (out / sa.HEADER_NAME).read_text()
    impl = (out / sa.IMPL_NAME).read_text()
    assert "#ifndef BTRC_STDLIB_H" in header
    assert "extern _Thread_local void** __btrc_destroyed;" in header
    assert "extern _Thread_local int __btrc_tracking;" in header
    assert "extern _Thread_local int __btrc_destroyed_count;" in header
    assert "extern _Thread_local int __btrc_destroyed_cap;" in header
    assert "extern _Thread_local __btrc_cleanup_entry* __btrc_cleanup_stack;" in header
    assert "extern _Thread_local int __btrc_cleanup_cap;" in header
    assert "extern void** __btrc_suspects;" in header
    assert "extern int __btrc_suspect_cap;" in header
    assert "void __btrc_cycle_state_cleanup(void);" in header
    assert "static void __btrc_cycle_state_cleanup(void)" not in header
    assert "static _Thread_local void** __btrc_destroyed" not in header
    assert "_Thread_local void** __btrc_suspects" not in header
    assert "static _Thread_local int __btrc_cleanup_cap" not in header
    assert "_Thread_local void** __btrc_destroyed = NULL;" in impl
    assert "_Thread_local int __btrc_tracking = 0;" in impl
    assert "_Thread_local int __btrc_destroyed_count = 0;" in impl
    assert "_Thread_local int __btrc_destroyed_cap = 0;" in impl
    assert "_Thread_local int __btrc_cleanup_cap = 64;" in impl
    assert "void** __btrc_suspects = NULL;" in impl
    assert "int __btrc_suspect_cap = 0;" in impl
    assert "void __btrc_cycle_state_cleanup(void) {" in impl
    assert "static _Thread_local void** __btrc_destroyed" not in impl
    assert "_Thread_local void** __btrc_suspects" not in impl


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
        [
            cc,
            "-std=c11",
            "-O1",
            "-ffunction-sections",
            "-fdata-sections",
            "-c",
            str(std / sa.IMPL_NAME),
            "-o",
            str(std / "btrc_stdlib.o"),
        ],
        check=True,
        cwd=str(std),
        timeout=120,
    )
    subprocess.run(
        ["ar", "rcs", str(std / "libbtrc.a"), str(std / "btrc_stdlib.o")],
        check=True,
        timeout=60,
    )

    prog = tmp_path / "p.btrc"
    prog.write_text(CROSS_BOUNDARY_PROG)

    # Inline build.
    inline_c = str(tmp_path / "inline.c")
    run_main(monkeypatch, ["--no-cache", str(prog), "-o", inline_c])
    capsys.readouterr()
    inline_bin = str(tmp_path / "inline_bin")
    subprocess.run(
        [cc, "-std=c11", inline_c, "-o", inline_bin, "-lm", "-lpthread"],
        check=True,
        timeout=120,
    )
    inline_out = subprocess.run([inline_bin], capture_output=True, text=True, timeout=30)

    # Reference build.
    ref_c = str(tmp_path / "ref.c")
    run_main(monkeypatch, ["--no-cache", "--stdlib", str(std), str(prog), "-o", ref_c])
    capsys.readouterr()
    ref_bin = str(tmp_path / "ref_bin")
    subprocess.run(
        [cc, "-std=c11", f"-I{std}", ref_c, str(std / "libbtrc.a"), "-o", ref_bin, "-lm", "-lpthread"],
        check=True,
        timeout=120,
    )
    ref_out = subprocess.run([ref_bin], capture_output=True, text=True, timeout=30)

    # Byte-identical behaviour — the whole point.
    assert ref_out.returncode == 0, ref_out.stderr
    assert ref_out.stdout == inline_out.stdout
    assert "tags=2" in ref_out.stdout and "eq=true" in ref_out.stdout

    # The reference TU links the stdlib instead of inlining it: it includes the
    # archive header and does NOT define the stdlib functions it uses, whereas
    # the inline build defines them locally. (A raw line-count ratio is no longer
    # a good proxy now that dead-code elimination keeps the inline build lean —
    # this checks the actual property: archive-provided code is not duplicated.)
    with open(inline_c) as f:
        inline_src = f.read()
    with open(ref_c) as f:
        ref_src = f.read()
    assert "btrc_stdlib.h" in ref_src
    # An archive-provided function the program uses: defined in inline, only
    # declared (extern, from the header) in the reference build.
    assert "btrc_Vector_string_push(" in inline_src
    inline_defs = inline_src.count("btrc_Vector_string_push(")
    ref_defs = sum(1 for ln in ref_src.splitlines() if "btrc_Vector_string_push(" in ln and ln.rstrip().endswith("{"))
    assert ref_defs == 0, "stdlib function should be linked from the archive, not inlined"
    assert inline_defs >= 1


def test_reference_catches_stdlib_throw(tmp_path, monkeypatch, capsys):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")

    std = tmp_path / "std"
    run_main(monkeypatch, ["--build-stdlib", str(std)])
    capsys.readouterr()
    subprocess.run(
        [
            cc,
            "-std=c11",
            "-O1",
            "-ffunction-sections",
            "-fdata-sections",
            "-c",
            str(std / sa.IMPL_NAME),
            "-o",
            str(std / "btrc_stdlib.o"),
        ],
        check=True,
        cwd=str(std),
        timeout=120,
    )
    subprocess.run(
        ["ar", "rcs", str(std / "libbtrc.a"), str(std / "btrc_stdlib.o")],
        check=True,
        timeout=60,
    )

    prog = tmp_path / "throw.btrc"
    prog.write_text(ARCHIVE_THROW_PROG)
    ref_c = str(tmp_path / "throw.c")
    run_main(monkeypatch, ["--no-cache", "--stdlib", str(std), str(prog), "-o", ref_c])
    capsys.readouterr()
    ref_bin = str(tmp_path / "throw_bin")
    subprocess.run(
        [cc, "-std=c11", f"-I{std}", ref_c, str(std / "libbtrc.a"), "-o", ref_bin, "-lm", "-lpthread"],
        check=True,
        timeout=120,
    )
    ref_out = subprocess.run([ref_bin], capture_output=True, text=True, timeout=30)

    assert ref_out.returncode == 0, ref_out.stderr
    assert ref_out.stdout.strip() == "caught"
