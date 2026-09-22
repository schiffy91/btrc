"""Actual optional FreeType setup, distinct from owned glyph-domain tests."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import REPO, apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("snapshot", [False, True])
def test_freetype_unique_setup(native_project, native_compile, sanitize, snapshot):
    if not shutil.which("pkg-config") or subprocess.run(["pkg-config", "--exists", "freetype2"]).returncode:
        pytest.skip("requires the optional FreeType SDK through pkg-config")
    font = Path(os.environ.get("BTRC_TEST_FONT", "/System/Library/Fonts/Supplemental/Arial.ttf"))
    if not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT or the system Arial font")
    source, _, _ = native_project
    root = source.parent.parent
    provider = REPO / "src/stdlib/GUI/FreeType"
    (source.parent / "FreeTypeFace.btrc").write_text((provider / "FreeTypeFace.btrc").read_text())
    (root / "FreeType.h").write_text((provider / "FreeType.h").read_text())
    manifest = (REPO / "src/stdlib/GUI/btrc.toml").read_text()
    binding = re.search(
        r'\[\[native\.bindings\]\]\nmodule = "FreeType\.FreeTypeFace"\n.*?(?=\n\[\[native\.)',
        manifest,
        re.DOTALL,
    )
    assert binding is not None
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "freeTypeSetup"\n'
        + binding.group()
        .replace('"FreeType.FreeTypeFace"', '"FreeTypeFace"')
        .replace('"FreeType/FreeType.h"', '"FreeType.h"')
        + '\n[[native.pkg-config]]\nname = "freetype2"\nmodules = ["FreeTypeFace"]\n'
    )
    source.write_text("""import ./FreeTypeFace.btrc;
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 2);
    for (int index = 0; index < 100; index++) {
        { var face = new FreeTypeFace(argv[1], 18); }
        bool failed = false;
        try { var missing = new FreeTypeFace("/no/such/font.ttf", 18); }
        catch (string error) { failed = true; }
        assert(failed);
        failed = false;
        try { var invalid = new FreeTypeFace(argv[1], 0); }
        catch (string error) { failed = true; }
        assert(failed);
    }
    print("PASS: actual FreeType unique setup");
    return 0;
}
""")
    if snapshot:
        source.write_text("""import ./FreeTypeFace.btrc;
import Library.Bytes;
import Library.GUI.FontFace;
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 2);
    var initialized = FT_Init_FreeType();
    assert(initialized.status == 0);
    var library = initialized.value;
    if (library == null) { throw "Cannot initialize FreeType"; }
    var loaded = FT_New_Face(library, argv[1], 0L);
    assert(loaded.status == 0);
    var face = loaded.value;
    if (face == null) { throw "Cannot load FreeType face"; }
    assert(FT_Set_Pixel_Sizes(face, 0U, 18U) == 0);
    var metrics = copyFreeTypeMetrics(face);
    if (metrics == null) { throw "Cannot snapshot FreeType metrics"; }
    assert(metrics.ascender > 0L && metrics.height > 0L);
    assert(FT_Load_Char(face, 65UL, BTRC_FT_LOAD_RENDER) == 0);
    var glyph = copyFreeTypeGlyph(face, 65536);
    if (glyph == null) { throw "Cannot snapshot actual glyph"; }
    assert(glyph.width > 0U && glyph.rows > 0U && glyph.pitch > 0);
    assert(glyph.bitmap.length() == glyph.pitch * (int)glyph.rows);
    int coverage = 0;
    for (int index = 0; index < glyph.bitmap.length(); index++) { coverage += glyph.bitmap.get(index); }
    assert(coverage > 0);
    assert(FT_Load_Char(face, 32UL, BTRC_FT_LOAD_RENDER) == 0);
    var empty = copyFreeTypeGlyph(face, 0);
    if (empty == null) { throw "Space glyph must have an owned empty bitmap"; }
    assert(empty.bitmap.length() == 0);
    face.close();
    assert(metrics.ascender > 0L && metrics.height > 0L);
    int retained = 0;
    for (int index = 0; index < glyph.bitmap.length(); index++) { retained += glyph.bitmap.get(index); }
    assert(retained == coverage);
    library.close();
    var provider = new FreeTypeFace(argv[1], 18);
    assert(provider.metrics().heightFixed() > 0LL);
    var rendered = provider.glyph(0xe9, true);
    if (rendered == null) { throw "Cannot render accented glyph"; }
    assert(rendered.width() > 0 && rendered.rows() > 0);
    var measured = provider.glyph(0xe9, false);
    if (measured == null) { throw "Cannot measure accented glyph"; }
    assert(measured.advanceX26_6() == rendered.advanceX26_6());
    print("PASS: actual FreeType unique setup");
    return 0;
}
""")
    completed = _compile_and_run(source, native_compile, sanitize, [str(font)])
    assert "PASS: actual FreeType unique setup" in completed.stdout


def _compile_and_run(source, native_compile, sanitize, arguments):
    plan = source.with_suffix(".link.json")
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)
    executable = source.parent / "FreeTypeSetup"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
    )
    completed = subprocess.run(
        [str(executable), *arguments],
        env=apple_environment(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("consumer", ["GuiFontConformance", "FontSmoke"])
def test_optional_freetype_factory(native_project, native_compile, sanitize, consumer):
    if not shutil.which("pkg-config") or subprocess.run(["pkg-config", "--exists", "freetype2"]).returncode:
        pytest.skip("requires the optional FreeType SDK through pkg-config")
    font = Path(os.environ.get("BTRC_TEST_FONT", "/System/Library/Fonts/Supplemental/Arial.ttf"))
    if consumer == "GuiFontConformance" and not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT or the system Arial font")
    source, _, _ = native_project
    directory = REPO / ("src/tests/native/gui" if consumer == "GuiFontConformance" else "examples/gui")
    source.write_text((directory / f"{consumer}.btrc").read_text())
    arguments = [str(font)] if consumer == "GuiFontConformance" else []
    result = _compile_and_run(source, native_compile, sanitize, arguments)
    assert ("PASS: FreeType draws into BTRC-owned pixels" if arguments else "FONT SMOKE TEST PASSED") in result.stdout
