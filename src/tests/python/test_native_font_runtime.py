"""Actual optional FreeType setup, distinct from owned glyph-domain tests."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.fixture
def font_project(request, tmp_path):
    """macOS's native project, or on Linux an empty package with the same
    layout: these cases write their own sources and FreeType manifest."""
    if sys.platform == "darwin":
        return request.getfixturevalue("native_project")
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires macOS or Linux and the explicitly built native header reader")
    (tmp_path / "src").mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "nativeConsumer"\n', encoding="utf-8")
    return tmp_path / "src/Main.btrc", None, None


def _test_font() -> Path:
    """BTRC_TEST_FONT, else macOS's Arial, else fontconfig's sans-serif match,
    so Linux CI exercises FreeType without configuration."""
    if configured := os.environ.get("BTRC_TEST_FONT"):
        return Path(configured)
    arial = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    if arial.is_file() or not shutil.which("fc-match"):
        return arial
    matched = subprocess.run(
        ["fc-match", "--format=%{file}", "sans-serif"], capture_output=True, text=True, timeout=TOOL_TIMEOUT
    )
    return Path(matched.stdout.strip()) if matched.returncode == 0 and matched.stdout.strip() else arial


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("snapshot", [False, True])
def test_freetype_unique_setup(font_project, native_compile, sanitize, snapshot):
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK through pkg-config")
    font = _test_font()
    if not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT, the system Arial font or fontconfig")
    source, _, _ = font_project
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
import Library.GUI.IFontFace;
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
    assert(FT_Load_Char(face, 65UL, FT_LOAD_RENDER) == 0);
    var glyph = copyFreeTypeGlyph(face, 65536);
    if (glyph == null) { throw "Cannot snapshot actual glyph"; }
    assert(glyph.width > 0U && glyph.rows > 0U && glyph.pitch > 0);
    assert(glyph.bitmap.length() == glyph.pitch * (int)glyph.rows);
    int coverage = 0;
    for (int index = 0; index < glyph.bitmap.length(); index++) { coverage += glyph.bitmap.get(index); }
    assert(coverage > 0);
    assert(FT_Load_Char(face, 32UL, FT_LOAD_RENDER) == 0);
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
    assert(measured.advanceFixed() == rendered.advanceFixed());
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

    apple = sys.platform == "darwin"
    # The builder invokes each driver by its resolved path, so the runner must
    # recognize that path: a bare "cc" never matches and drops the sanitizers.
    drivers = ("/usr/bin/clang", "/usr/bin/clang++") if apple else ("cc", "c++")
    cc, cxx = (shutil.which(driver) for driver in drivers)
    if cc is None or cxx is None:
        pytest.skip(f"requires the {drivers[0]} and {drivers[1]} drivers")
    environment = apple_environment() if apple else {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    sanitizers = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    driven = []

    def runner(command, **kwargs):
        flags = ["-O2"] if command[0] in {cc, cxx} else []
        if flags and sanitize:
            flags += sanitizers
        if flags:
            driven.append([command[0], *flags, *command[1:]])
        return subprocess.run([command[0], *flags, *command[1:]], env=environment, **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=cc,
        cxx=cxx,
    )
    # Every compile and the link went through a recognized driver, and a
    # sanitized build carried the sanitizers into each of them.
    assert any("-c" in command for command in driven), driven
    assert any("-c" not in command and "-o" in command for command in driven), driven
    for command in driven:
        assert all(flag in command for flag in sanitizers) == sanitize, command
    completed = subprocess.run(
        [str(executable), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("consumer", ["GUIFontConformance", "FontSmoke"])
def test_optional_freetype_factory(font_project, native_compile, sanitize, consumer):
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK through pkg-config")
    font = _test_font()
    if consumer == "GUIFontConformance" and not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT, the system Arial font or fontconfig")
    source, _, _ = font_project
    source.write_text((REPO / "src/tests/native/gui" / f"{consumer}.btrc").read_text())
    arguments = [str(font)] if consumer == "GUIFontConformance" else []
    result = _compile_and_run(source, native_compile, sanitize, arguments)
    assert ("PASS: FreeType draws into BTRC-owned pixels" if arguments else "FONT SMOKE TEST PASSED") in result.stdout


def _linux_test_font() -> Path | None:
    """BTRC_TEST_FONT, else fontconfig's sans-serif match."""
    configured = os.environ.get("BTRC_TEST_FONT")
    if configured:
        return Path(configured)
    if not shutil.which("fc-match"):
        return None
    matched = subprocess.run(["fc-match", "-f", "%{file}", "sans-serif"], capture_output=True, text=True, timeout=30)
    return Path(matched.stdout.strip()) if matched.returncode == 0 and matched.stdout.strip() else None


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_freetype_draws_into_owned_pixels(tmp_path, request, frontend, sanitized):
    """Linux runs the same FreeType conformance as macOS, on a fontconfig font."""
    from src.tests.python.test_native_linux_providers import _build, _environment, _require_linux_reader

    _require_linux_reader()
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK through pkg-config")
    font = _linux_test_font()
    if font is None or not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT or a fontconfig sans-serif font")
    source = tmp_path / "GUIFontConformance.btrc"
    source.write_text((REPO / "src/tests/native/gui/GUIFontConformance.btrc").read_text())
    executable = _build(source, tmp_path, frontend, sanitized, request)
    result = subprocess.run(
        [str(executable), str(font)], capture_output=True, text=True, timeout=60, env=_environment(sanitized)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: FreeType draws into BTRC-owned pixels" in result.stdout
