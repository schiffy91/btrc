"""Actual optional FreeType setup, distinct from owned glyph-domain tests."""

import gzip
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from struct import pack

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
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
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
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    result = subprocess.run(
        [str(executable), str(font)], capture_output=True, text=True, timeout=60, env=provider_environment(sanitized)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: FreeType draws into BTRC-owned pixels" in result.stdout


def _pcf_strike():
    # Table layouts are intentionally mixed: little-endian metrics and
    # a four-byte-padded bitmap whose two-byte scan units are byte-swapped.
    fmt = 0x1A
    strings = b"PIXEL_SIZE\0CHARSET_REGISTRY\0CHARSET_ENCODING\0ISO10646\x001\0"
    props = pack("<II", 0, 3)
    for key, is_string, value in (
        (b"PIXEL_SIZE", 0, 8),
        (b"CHARSET_REGISTRY", 1, strings.index(b"ISO10646")),
        (b"CHARSET_ENCODING", 1, len(strings) - 2),
    ):
        props += pack("<IBI", strings.index(key), is_string, value)
    props += bytes(-len(props) % 4) + pack("<I", len(strings)) + strings
    accelerators = pack("<I", 0) + bytes(8) + pack("<iii", 6, 2, 0) + bytes(24)
    metrics = pack("<IH", 0x100, 2) + bytes((128, 128, 134, 128, 128, 127, 136, 134, 130, 129))
    bitmaps = pack("<IIII4I", fmt, 2, 0, 0, 6, 6, 12, 24) + bytes.fromhex("80ff00008080000080ff0000")
    ids = [0] + [0xFFFF] * 47 + [1]
    encodings = pack("<I5H", 0, 32, 80, 0, 0, 80) + pack("<" + "H" * len(ids), *ids)
    tables = [(1, 0, props), (2, 0, accelerators), (4, 0x100, metrics), (8, fmt, bitmaps), (32, 0, encodings)]
    directory = bytearray(pack("<II", 0x70636601, len(tables)))
    payload = bytearray()
    for tag, format, data in tables:
        directory.extend(pack("<4I", tag, format, len(data), 8 + len(tables) * 16 + len(payload)))
        payload.extend(data)
        payload.extend(bytes(-len(payload) % 4))
    return bytes(directory + payload)


def unavailable_freetype(tmp_path, env):
    blocker = tmp_path / "unavailable.c"
    blocker.write_text("int FT_Init_FreeType(void **library) { *library = 0; return 1; }\n")
    shared = tmp_path / "unavailable.so"
    subprocess.run(["cc", "-shared", "-fPIC", str(blocker), "-o", str(shared)], check=True, timeout=TOOL_TIMEOUT)
    return {**env, "LD_PRELOAD": str(shared)}


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize(
    ("consumer", "fixture", "expected"),
    [
        (
            "MonochromeFontConformance",
            "fixture.pcf",
            "PASS: monochrome strike metrics, default glyph and packed pixels",
        ),
        (
            "MonochromeFontConformance",
            "mono-strike.bdf",
            "PASS: monochrome strike metrics, default glyph and packed pixels",
        ),
        ("LegacyBDFFontConformance", "legacy-strike.bdf", "PASS: BDF glyph indices and short rows"),
        ("ColorBitmapFontConformance", "color-bitmap.ttf", "PASS: color bitmap native metrics and coverage"),
    ],
)
def test_linux_bitmap_factory_matches_freetype(tmp_path, request, frontend, sanitized, consumer, fixture, expected):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK for the reference provider")

    fixtures = REPO / "src/tests/native/gui"
    source = tmp_path / f"{consumer}.btrc"
    source.write_text((fixtures / source.name).read_text())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    portable = tmp_path / fixture
    suffix = portable.suffix[1:]
    if suffix == "pcf":
        portable.write_bytes(_pcf_strike())
    else:
        portable.write_bytes((fixtures / "fixtures" / fixture).read_bytes())
    arguments = [suffix] if consumer == "MonochromeFontConformance" else []
    reference = tmp_path / "fixture.raw"
    reference.write_bytes(portable.read_bytes())
    env = provider_environment(sanitized)
    first_party = [portable]
    if suffix == "pcf":
        compressed = tmp_path / "fixture.pcf.gz"
        compressed.write_bytes(gzip.compress(portable.read_bytes(), mtime=0))
        first_party.append(compressed)
    for path in [reference, *first_party]:
        run = subprocess.run([executable, path, *arguments], capture_output=True, text=True, timeout=60, env=env)
        assert run.returncode == 0, run.stdout + run.stderr
        assert expected in run.stdout

    if not sanitized:
        # The native fallback shares this binary. Make its initialization fail
        # to prove which provider the existing public factory actually used.
        blocked = unavailable_freetype(tmp_path, env)
        for path in first_party:
            good = subprocess.run(
                [executable, path, *arguments], capture_output=True, text=True, timeout=60, env=blocked
            )
            assert good.returncode == 0, good.stdout + good.stderr
        fallback = subprocess.run(
            [executable, reference, *arguments], capture_output=True, text=True, timeout=60, env=blocked
        )
        assert fallback.returncode != 0 and "Cannot initialize FreeType library" in fallback.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_hinted_outlines_after_unlink(tmp_path, request, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK for the native fallback")
    tests = REPO / "src/tests/native/gui"
    source = tmp_path / "HintedFontConformance.btrc"
    source.write_text((tests / source.name).read_text())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    env = provider_environment(sanitized)

    def run(suffix, count, environment, fixture):
        path = tmp_path / f"input.{suffix}"
        path.write_bytes(fixture)
        return subprocess.run(
            [executable, path, str(count)], capture_output=True, text=True, env=environment, timeout=60
        )

    blocked = None if sanitized else unavailable_freetype(tmp_path, env)
    unicode_maps = (tests / "fixtures/hinted-full-cmap.ttf").read_bytes()
    for environment in [env] if blocked is None else [env, blocked]:
        result = run("ttf", "unicode", environment, unicode_maps)
        assert result.returncode == 0, result.stdout + result.stderr

    for extension in ("ttf", "woff", "woff2"):
        mixed = (tests / f"fixtures/hinted-mixed.{extension}").read_bytes()
        for suffix in (extension, "raw"):
            result = run(suffix, 6, env, mixed)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "PASS: hinted outline snapshots after unlink" in result.stdout
        if blocked is not None:
            supported = run(extension, 5, blocked, mixed)
            assert supported.returncode == 0, supported.stdout + supported.stderr
            fallback = run(extension, 6, blocked, mixed)
            assert fallback.returncode != 0 and "Cannot initialize FreeType library" in fallback.stderr
    legacy = (tests / "fixtures/hinted-legacy-bmp.ttf").read_bytes()
    for suffix in ("ttf", "raw"):
        rendered = run(suffix, "render", env, legacy)
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    if blocked is not None:
        measured = run("ttf", "measure", blocked, legacy)
        assert measured.returncode == 0, measured.stdout + measured.stderr
        native_ink = run("ttf", "render", blocked, legacy)
        assert native_ink.returncode != 0 and "Cannot initialize FreeType library" in native_ink.stderr
    composite = (tests / "fixtures/hinted-composite-offset.ttf").read_bytes()
    for size in (8, 13):
        for extension, environment in (("raw", env), ("ttf", blocked or env)):
            result = run(extension, f"composite{size}", environment, composite)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "PASS: size-specific composite component placement" in result.stdout
    general = (tests / "fixtures/hinted-general.woff2").read_bytes()
    result = run("woff2", 6, env, general)
    assert result.returncode == 0, result.stdout + result.stderr
    if blocked is not None:
        early = run("woff2", 5, blocked, general)
        assert early.returncode != 0 and "Cannot initialize FreeType library" in early.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_cff_measurement_and_retained_fallback(tmp_path, request, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK for the native fallback")
    fixtures = REPO / "src/tests/native/gui"
    source = tmp_path / "CFFMeasurementConformance.btrc"
    source.write_bytes((fixtures / source.name).read_bytes())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    data = (fixtures / "fixtures/measured-cff.otf").read_bytes()
    env = provider_environment(sanitized)

    def run(suffix, mode, environment, input_bytes=data):
        path = tmp_path / f"input.{suffix}"
        path.write_bytes(input_bytes)
        return subprocess.run([executable, path, mode], capture_output=True, text=True, env=environment, timeout=60)

    for suffix in ("otf", "raw"):
        visible = run(suffix, "render", env)
        assert visible.returncode == 0, visible.stdout + visible.stderr
        assert "PASS: CFF font measurement and retained fallback" in visible.stdout
    # The final glyph's Type 2 program begins with a reserved operator.
    # FreeType tolerates it, so the public probe must switch to the saved
    # bytes after unlink before returning its advance.
    curve = bytes.fromhex("f9508b16f75cf8eceff75cf72a27f72afd50190e")
    assert data.count(curve) == 2
    at = data.rindex(curve)
    unusual = data[:at] + b"\x00\x0e" + data[at + 2 :]
    # Give B a 0..100 horizontal stem and a 100-unit square. Its device
    # coverage at 10 px is 248, as independently rendered by FreeType.
    square = bytes.fromhex("f9508bef018b16efef27060e").ljust(len(curve), b"\x0e")
    hinted = data[:at] + square + data[at + len(curve) :]
    # Straight edges in the triangle (0,0), (90,347), (167,622) cross a
    # subpixel rounding boundary at 65 px. Compare both providers.
    triangle = bytes.fromhex("f9508b16e5f7efd8f7a7050e").ljust(len(curve), b"\x0e")
    long_edge = data[:at] + triangle + data[at + len(curve) :]
    for suffix in ("otf", "raw"):
        visible_edge = run(suffix, "edge", env, long_edge)
        assert visible_edge.returncode == 0, visible_edge.stdout + visible_edge.stderr
    visible_hint = run("otf", "hint", env, hinted)
    assert visible_hint.returncode == 0, visible_hint.stdout + visible_hint.stderr
    fallback = run("otf", "render", env, unusual)
    assert fallback.returncode == 0, fallback.stdout + fallback.stderr
    if not sanitized:
        blocked = unavailable_freetype(tmp_path, env)
        rejected = run("otf", "measure", blocked, unusual)
        assert rejected.returncode != 0 and "Cannot initialize FreeType library" in rejected.stderr
        measured = run("otf", "measure", blocked)
        assert measured.returncode == 0, measured.stdout + measured.stderr
        portable_curve = run("otf", "render", blocked)
        assert portable_curve.returncode == 0, portable_curve.stdout + portable_curve.stderr
        portable_edge = run("otf", "edge", blocked, long_edge)
        assert portable_edge.returncode == 0, portable_edge.stdout + portable_edge.stderr
        for suffix, mode, font_data in (("raw", "measure", data), ("otf", "hint", hinted)):
            native = run(suffix, mode, blocked, font_data)
            assert native.returncode != 0 and "Cannot initialize FreeType library" in native.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_installed_font_catalog(tmp_path, request, gui_provider_root, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    tests = REPO / "src/tests/native/gui"
    executable = build_provider_program(
        tests / "InstalledFontConformance.btrc", tmp_path, frontend, sanitized, request, data_root=gui_provider_root
    )
    root = tmp_path / "font root"
    root.mkdir()
    (root / "subdir").mkdir()
    (root / "subdir" / "collection file.ttc").write_bytes((tests / "fixtures/installed-families.ttc").read_bytes())
    (root / "cycle").symlink_to(root, target_is_directory=True)
    (root / "duplicate.ttc").symlink_to(root / "subdir" / "collection file.ttc")
    (root / "invalid.otf").write_bytes(b"OTTO")
    result = subprocess.run(
        [executable, root], capture_output=True, text=True, env=provider_environment(sanitized), timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: installed font collections, Unicode family fallback and XDG precedence" in result.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_system_text_runs(tmp_path, request, gui_provider_root, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    tests = REPO / "src/tests/native/gui"
    program = build_provider_program(
        tests / "SystemTextConformance.btrc", tmp_path, frontend, sanitized, request, data_root=gui_provider_root
    )
    configs = tmp_path / "font settings"
    configs.mkdir()
    (configs / "35-primary.conf").write_text(
        '<fontconfig><alias binding="strong"><family>sans-serif</family><prefer><family>Test</family></prefer></alias></fontconfig>'
    )
    config = tmp_path / "fonts.conf"
    config.write_text(
        f'<fontconfig><dir>{tmp_path}</dir><include prefix="relative">font settings</include></fontconfig>'
    )
    # The program unlinks each font after opening it. The second lookup
    # therefore exercises a desktop configured with only a web-format face.
    for extension in ("ttf", "woff2"):
        path = tmp_path / f"widgets.{extension}"
        path.write_bytes((tests / f"fixtures/shaping-fixture.{extension}").read_bytes())
        result = subprocess.run(
            [program, path],
            capture_output=True,
            text=True,
            env=provider_environment(sanitized, FONTCONFIG_FILE=str(config)),
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS: native text ligatures, kerning, ellipsis and owned pixels" in result.stdout
    contextual = subprocess.run(
        [program, "--context", tests / "fixtures/shaping-classes.ttf"],
        capture_output=True,
        text=True,
        env=provider_environment(sanitized),
        timeout=60,
    )
    assert contextual.returncode == 0, contextual.stdout + contextual.stderr
    vectors = subprocess.run(
        [program, "--vectors", tests / "fixtures/shaping-vectors.ttf"],
        capture_output=True,
        text=True,
        env=provider_environment(sanitized),
        timeout=60,
    )
    assert vectors.returncode == 0, vectors.stdout + vectors.stderr
    for fixture, caret in (("shaping-fixture.ttf", "5"), ("shaping-carets.ttf", "3")):
        result = subprocess.run(
            [program, "--carets", tests / "fixtures" / fixture, caret],
            capture_output=True,
            text=True,
            env=provider_environment(sanitized),
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.linux_gui
def test_gtk_shaped_text(tmp_path_factory, tmp_path, request, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import build_observed_provider_program, provider_environment

    program = build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        "src/tests/native/gui/linux/GtkShapedText.btrc",
        "src/tests/native/gui/linux/GtkTextRoute",
        ("gtkTextGlyphCalls", "gtkTextLayoutCalls", "gtkTextUseNativeLayout"),
        ("pango_cairo_show_glyph_string", "pango_cairo_show_layout"),
        # The optimized cases cover the production binary. An unoptimized
        # sanitizer translation unit keeps full GUI instrumentation bounded.
        optimization=0 if sanitized else 2,
    )
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    shutil.copyfile(REPO / "src/tests/native/gui/fixtures/shaping-fixture.ttf", fonts / "widgets.ttf")
    config = tmp_path / "fonts.conf"
    config.write_text(f"<fontconfig><dir>{fonts}</dir><cachedir>{tmp_path / 'cache'}</cachedir></fontconfig>")
    result = subprocess.run(
        [program],
        capture_output=True,
        text=True,
        env=provider_environment(sanitized, FONTCONFIG_FILE=str(config), LC_ALL="C.UTF-8"),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: public Latin shaping and native fallback produce the same RGBA pixels" in result.stdout
