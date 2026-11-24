"""First-party font loading, hinting, rasterization, and shaping runtime tests."""

import gzip
import os
import platform
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
from tools.qualification.dependencies import DependencyAudit


def _host_target_label() -> str:
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    system = "macos" if sys.platform == "darwin" else "linux"
    return f"{system}-{arch}"


@pytest.fixture
def font_project(request, tmp_path):
    """macOS's native project, or on Linux an empty package with the same layout."""
    if sys.platform == "darwin":
        return request.getfixturevalue("native_project")
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires macOS or Linux and the explicitly built native header reader")
    (tmp_path / "src").mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "nativeConsumer"\n', encoding="utf-8")
    return tmp_path / "src/Main.btrc", None, None


def _test_font() -> Path:
    """BTRC_TEST_FONT, else macOS's Arial, else fontconfig's sans-serif match."""
    if configured := os.environ.get("BTRC_TEST_FONT"):
        return Path(configured)
    arial = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    if arial.is_file() or not shutil.which("fc-match"):
        return arial
    matched = subprocess.run(
        ["fc-match", "--format=%{file}", "sans-serif"], capture_output=True, text=True, timeout=TOOL_TIMEOUT
    )
    return Path(matched.stdout.strip()) if matched.returncode == 0 and matched.stdout.strip() else arial


def _compile_and_run(source, native_compile, sanitize, arguments, *, exe_name="FontRuntimeProbe"):
    plan = source.with_suffix(".link.json")
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)
    executable = source.parent / exe_name

    apple = sys.platform == "darwin"
    # The builder invokes each driver by its resolved path, so the runner must
    # recognize that path: a bare "cc" never matches and drops the sanitizers.
    drivers = ("/usr/bin/clang", "/usr/bin/clang++") if apple else ("cc", "c++")
    cc, cxx = (shutil.which(driver) for driver in drivers)
    if cc is None or cxx is None:
        pytest.skip(f"requires the {drivers[0]} and {drivers[1]} drivers")
    base_env = apple_environment() if apple else {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    # Build without any pkg-config search path to prove freetype2 is not required.
    environment = {**base_env, "PKG_CONFIG_PATH": ""}
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
    assert any("-c" in command for command in driven), driven
    assert any("-c" not in command and "-o" in command for command in driven), driven
    for command in driven:
        assert all(flag in command for flag in sanitizers) == sanitize, command
    assert DependencyAudit().binary_problems(executable, _host_target_label()) == []
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
@pytest.mark.parametrize("snapshot", [False, True])
def test_freetype_unique_setup(font_project, native_compile, sanitize, snapshot):
    font = _test_font()
    if not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT, the system Arial font or fontconfig")
    source, _, _ = font_project
    corrupt = source.parent / "corrupt.ttf"
    corrupt.write_bytes(b"not a valid font file")
    source.write_text("""import Library.GUI.Font;
import Library.GUI.FreeType;
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 3);
    for (int index = 0; index < 100; index++) {
        { var face = FreeType.load(argv[1], 18); }
        bool failed = false;
        try { var missing = FreeType.load("/no/such/font.ttf", 18); }
        catch (string error) { failed = true; }
        assert(failed);
        failed = false;
        try { var invalid = FreeType.load(argv[1], 0); }
        catch (string error) { failed = true; }
        assert(failed);
        failed = false;
        try { var bad = FreeType.load(argv[2], 18); }
        catch (string error) { failed = true; }
        assert(failed);
    }
    print("PASS: actual FreeType unique setup");
    return 0;
}
""")
    if snapshot:
        source.write_text("""import Library.Bytes;
import Library.GUI.Font;
import Library.GUI.FreeType;
import Library.GUI.IFontFace;
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 3);
    FontMetrics? retainedMetrics = null;
    FontGlyph? retainedGlyph = null;
    int coverage = 0;
    {
        var face = FreeType.load(argv[1], 18);
        var metrics = face.metrics();
        assert(metrics.ascenderFixed() > 0LL && metrics.heightFixed() > 0LL);
        retainedMetrics = metrics;
        var glyph = face.glyph(65, true);
        if (glyph == null) { throw "Cannot render capital A"; }
        assert(glyph.width() > 0 && glyph.rows() > 0 && glyph.pitch() > 0);
        for (int y = 0; y < glyph.rows(); y++) {
            for (int x = 0; x < glyph.width(); x++) { coverage += glyph.coverage(y, x); }
        }
        assert(coverage > 0);
        retainedGlyph = glyph;
        var empty = face.glyph(32, true);
        if (empty == null) { throw "Space glyph must return an owned empty snapshot"; }
        assert(empty.width() == 0 && empty.rows() == 0);
    }
    if (retainedMetrics == null || retainedGlyph == null) { throw "Missing retained snapshots"; }
    assert(retainedMetrics.ascenderFixed() > 0LL && retainedMetrics.heightFixed() > 0LL);
    int retained = 0;
    for (int y = 0; y < retainedGlyph.rows(); y++) {
        for (int x = 0; x < retainedGlyph.width(); x++) { retained += retainedGlyph.coverage(y, x); }
    }
    assert(retained == coverage);
    var provider = FreeType.load(argv[1], 18);
    assert(provider.metrics().heightFixed() > 0LL);
    var rendered = provider.glyph(0xe9, true);
    if (rendered == null) { throw "Cannot render accented glyph"; }
    assert(rendered.width() > 0 && rendered.rows() > 0);
    var measured = provider.glyph(0xe9, false);
    if (measured == null) { throw "Cannot measure accented glyph"; }
    assert(measured.advanceFixed() == rendered.advanceFixed());
    bool rejected = false;
    try { provider.glyph(0xd800, true); } catch (string error) { rejected = true; }
    assert(rejected);
    print("PASS: actual FreeType unique setup");
    return 0;
}
""")
    completed = _compile_and_run(source, native_compile, sanitize, [str(font), str(corrupt)])
    assert "PASS: actual FreeType unique setup" in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("consumer", ["GUIFontConformance", "FontSmoke"])
def test_optional_freetype_factory(font_project, native_compile, sanitize, consumer):
    font = _test_font()
    if consumer == "GUIFontConformance" and not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT, the system Arial font or fontconfig")
    source, _, _ = font_project
    source.write_text((REPO / "src/tests/native/gui" / f"{consumer}.btrc").read_text())
    arguments = [str(font)] if consumer == "GUIFontConformance" else []
    result = _compile_and_run(source, native_compile, sanitize, arguments)
    assert ("PASS: FreeType draws into BTRC-owned pixels" if arguments else "FONT SMOKE TEST PASSED") in result.stdout


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
    for tag, fmt_word, data in tables:
        directory.extend(pack("<4I", tag, fmt_word, len(data), 8 + len(tables) * 16 + len(payload)))
        payload.extend(data)
        payload.extend(bytes(-len(payload) % 4))
    return bytes(directory + payload)


def _run_hinted_suite(executable: Path, work_dir: Path, env: dict[str, str]) -> None:
    fixtures = REPO / "src/tests/native/gui/fixtures"

    def run(suffix: str, count: object, fixture: bytes) -> subprocess.CompletedProcess[str]:
        path = work_dir / f"input.{suffix}"
        path.write_bytes(fixture)
        return subprocess.run(
            [str(executable), str(path), str(count)], capture_output=True, text=True, env=env, timeout=60
        )

    result = run("ttf", "unicode", (fixtures / "hinted-full-cmap.ttf").read_bytes())
    assert result.returncode == 0, result.stdout + result.stderr

    for extension in ("ttf", "woff", "woff2"):
        mixed = (fixtures / f"hinted-mixed.{extension}").read_bytes()
        for suffix in (extension, "raw"):
            for count in (5, 6):
                result = run(suffix, count, mixed)
                assert result.returncode == 0, result.stdout + result.stderr
                assert "PASS: hinted outline snapshots after unlink" in result.stdout

    legacy = (fixtures / "hinted-legacy-bmp.ttf").read_bytes()
    for suffix in ("ttf", "raw"):
        for mode in ("measure", "render"):
            result = run(suffix, mode, legacy)
            assert result.returncode == 0, result.stdout + result.stderr

    composite = (fixtures / "hinted-composite-offset.ttf").read_bytes()
    for size in (8, 13):
        for suffix in ("ttf", "raw"):
            result = run(suffix, f"composite{size}", composite)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "PASS: size-specific composite component placement" in result.stdout

    inhibited = (fixtures / "hinted-inhibited-vectors.ttf").read_bytes()
    for size in (9, 10):
        for suffix in ("ttf", "raw"):
            result = run(suffix, f"vector{size}", inhibited)
            assert result.returncode == 0, result.stdout + result.stderr

    active = (fixtures / "hinted-active-instructionless.ttf").read_bytes()
    for code in "BCDE":
        for suffix in ("ttf", "raw"):
            result = run(suffix, f"active{code}", active)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "PASS: active vector outline after unlink" in result.stdout

    delta = (fixtures / "hinted-delta-points.ttf").read_bytes()
    for size in (13, 14):
        for suffix in ("ttf", "raw"):
            result = run(suffix, f"delta{size}", delta)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "PASS: size-specific point deltas" in result.stdout

    env_fixture = (fixtures / "hinted-environment.ttf").read_bytes()
    for suffix in ("ttf", "raw"):
        result = run(suffix, "environment", env_fixture)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS: TrueType interpreter environment" in result.stdout

    general = (fixtures / "hinted-general.woff2").read_bytes()
    for suffix in ("woff2", "raw"):
        result = run(suffix, 6, general)
        assert result.returncode == 0, result.stdout + result.stderr


def _run_cff_suite(executable: Path, work_dir: Path, env: dict[str, str]) -> None:
    fixtures = REPO / "src/tests/native/gui/fixtures"
    data = (fixtures / "measured-cff.otf").read_bytes()

    def run(suffix: str, mode: str, input_bytes: bytes = data) -> subprocess.CompletedProcess[str]:
        path = work_dir / f"input.{suffix}"
        path.write_bytes(input_bytes)
        return subprocess.run([str(executable), str(path), mode], capture_output=True, text=True, env=env, timeout=60)

    curve = bytes.fromhex("f9508b16f75cf8eceff75cf72a27f72afd50190e")
    assert data.count(curve) == 2
    at = data.rindex(curve)
    unusual = data[:at] + b"\x00\x0e" + data[at + 2 :]
    square = bytes.fromhex("f9508bef95bd018b16efef27060e").ljust(len(curve), b"\x0e")
    hinted = data[:at] + square + data[at + len(curve) :]
    triangle = bytes.fromhex("f9508b16e5f7efd8f7a7050e").ljust(len(curve), b"\x0e")
    long_edge = data[:at] + triangle + data[at + len(curve) :]
    separated = (fixtures / "cff-separated-stems.otf").read_bytes()
    blue = (fixtures / "cff-blue-stem.otf").read_bytes()
    zones = bytes.fromhex("878ff82490fbe59206")
    assert blue.count(zones) == 1
    family = blue.replace(zones, zones[:-1] + b"\x08")
    flat_top = blue.replace(zones, bytes.fromhex("878ff82490fbe19206"))
    flat_bottom = blue.replace(zones, bytes.fromhex("918ff81a90fbd99206"))
    single = bytes.fromhex("f95095c9019516c88b8be54e8b050e").ljust(len(curve), b"\x0e")
    single_stem = data[:at] + single + data[at + len(curve) :]
    odd = bytes.fromhex("f95095c8019516c88b8be54e8b050e").ljust(len(curve), b"\x0e")
    odd_stem = data[:at] + odd + data[at + len(curve) :]

    for mode, face in (
        ("measure", data),
        ("render", data),
        ("measure", unusual),
        ("render", unusual),
        ("edge", long_edge),
        ("polygon", separated),
        ("blue", flat_top),
        ("y", flat_bottom),
        ("zero", blue),
        ("zero", family),
        ("uncaptured", blue),
        ("blue", blue),
        ("y", single_stem),
        ("y", odd_stem),
        ("hint", hinted),
    ):
        for suffix in ("otf", "raw"):
            result = run(suffix, mode, face)
            assert result.returncode == 0, f"{suffix}/{mode}: {result.stdout + result.stderr}"

    for operator in (3, 23):
        stem = bytes.fromhex("f95095c8") + bytes([operator]) + bytes.fromhex("9516c88b8be54e8b050e")
        vertical_face = data[:at] + stem.ljust(len(curve), b"\x0e") + data[at + len(curve) :]
        for suffix in ("otf", "raw"):
            result = run(suffix, "vertical", vertical_face)
            assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("sanitize", [False, True])
def test_first_party_font_conformance_without_freetype(font_project, native_compile, sanitize):
    """Run all first-party font format conformance suites on macOS and Linux with zero FreeType."""
    source, _, _ = font_project
    work_dir = source.parent
    fixtures = REPO / "src/tests/native/gui"
    apple = sys.platform == "darwin"
    env = {
        **(apple_environment() if apple else {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}),
        "PKG_CONFIG_PATH": "",
    }

    def compile_only(program_name: str) -> Path:
        source.write_text((fixtures / f"{program_name}.btrc").read_text())
        plan = source.with_suffix(".link.json")
        compiled = native_compile(source, plan_path=plan)
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        assert not compiled.diagnostics
        generated = source.with_suffix(".c")
        generated.write_text(compiled.c_source)
        exe = work_dir / program_name
        drivers = ("/usr/bin/clang", "/usr/bin/clang++") if apple else ("cc", "c++")
        cc, cxx = (shutil.which(d) for d in drivers)
        if cc is None or cxx is None:
            pytest.skip(f"requires the {drivers[0]} and {drivers[1]} drivers")
        sanitizers = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]

        def runner(command, **kwargs):
            flags = ["-O2"] if command[0] in {cc, cxx} else []
            if flags and sanitize:
                flags += sanitizers
            return subprocess.run([command[0], *flags, *command[1:]], env=env, **kwargs)

        NativePlanBuilder(runner=runner).build(plan_path=plan, generated_c=generated, output=exe, cc=cc, cxx=cxx)
        assert DependencyAudit().binary_problems(exe, _host_target_label()) == []
        return exe

    mono_exe = compile_only("MonochromeFontConformance")
    pcf_bytes = _pcf_strike()
    bdf_bytes = (fixtures / "fixtures/mono-strike.bdf").read_bytes()
    for fname, payload, kind in (
        ("strike.pcf", pcf_bytes, "pcf"),
        ("strike.pcf.gz", gzip.compress(pcf_bytes, mtime=0), "pcf"),
        ("strike.raw", pcf_bytes, "pcf"),
        ("strike.bdf", bdf_bytes, "bdf"),
        ("strike_bdf.raw", bdf_bytes, "bdf"),
    ):
        p = work_dir / fname
        p.write_bytes(payload)
        run = subprocess.run([str(mono_exe), str(p), kind], capture_output=True, text=True, env=env, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "PASS: monochrome strike metrics, default glyph and packed pixels" in run.stdout

    legacy_exe = compile_only("LegacyBDFFontConformance")
    for fname in ("legacy.bdf", "legacy.raw"):
        p = work_dir / fname
        p.write_bytes((fixtures / "fixtures/legacy-strike.bdf").read_bytes())
        run = subprocess.run([str(legacy_exe), str(p)], capture_output=True, text=True, env=env, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "PASS: BDF glyph indices and short rows" in run.stdout

    color_exe = compile_only("ColorBitmapFontConformance")
    for fname in ("color.ttf", "color.raw"):
        p = work_dir / fname
        p.write_bytes((fixtures / "fixtures/color-bitmap.ttf").read_bytes())
        run = subprocess.run([str(color_exe), str(p)], capture_output=True, text=True, env=env, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "PASS: color bitmap native metrics and coverage" in run.stdout

    hinted_exe = compile_only("HintedFontConformance")
    _run_hinted_suite(hinted_exe, work_dir, env)

    cff_exe = compile_only("CFFMeasurementConformance")
    _run_cff_suite(cff_exe, work_dir, env)

    # Also verify TTC collections, unhinted TrueType, and CFF > 128 px via GUIFontConformance.
    gui_exe = compile_only("GUIFontConformance")
    ttc_path = fixtures / "fixtures/installed-families.ttc"
    # Verify TTC face 0 opens cleanly and produces metrics; also check real system TTC/OTF if present.
    source.write_text("""import Library.GUI.FreeType;
import Library.GUI.IFontFace;
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 3);
    var ttc = FreeType.load(argv[1], 18);
    assert(ttc.metrics().heightFixed() > 0LL);
    var bigCff = FreeType.load(argv[2], 160);
    assert(bigCff.metrics().heightFixed() > 0LL);
    var glyph = bigCff.glyph(65, true);
    if (glyph == null) { throw "Cannot render CFF glyph above 128 px"; }
    assert(glyph.width() > 0 && glyph.rows() > 0 && glyph.advanceFixed() > 0LL);
    print("PASS: TTC and large CFF first-party");
    return 0;
}
""")
    extra = _compile_and_run(
        source,
        native_compile,
        sanitize,
        [str(ttc_path), str(fixtures / "fixtures/measured-cff.otf")],
        exe_name="TTCAndLargeCFF",
    )
    assert "PASS: TTC and large CFF first-party" in extra.stdout
    for system_font in (
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/System/Library/Fonts/Supplemental/Al Nile.ttc"),
        Path("/System/Library/Fonts/Supplemental/STIXGeneral.otf"),
        Path("/System/Library/Fonts/LastResort.otf"),
    ):
        if system_font.is_file():
            run = subprocess.run([str(gui_exe), str(system_font)], capture_output=True, text=True, env=env, timeout=30)
            assert run.returncode == 0, f"{system_font}: {run.stdout + run.stderr}"
            assert "PASS: FreeType draws into BTRC-owned pixels" in run.stdout


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
    """Linux runs the same first-party font conformance as macOS, on a fontconfig font."""
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    font = _linux_test_font()
    if font is None or not font.is_file():
        pytest.skip("requires BTRC_TEST_FONT or a fontconfig sans-serif font")
    source = tmp_path / "GUIFontConformance.btrc"
    source.write_text((REPO / "src/tests/native/gui/GUIFontConformance.btrc").read_text())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    assert DependencyAudit().binary_problems(executable, _host_target_label()) == []
    result = subprocess.run(
        [str(executable), str(font)], capture_output=True, text=True, timeout=60, env=provider_environment(sanitized)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: FreeType draws into BTRC-owned pixels" in result.stdout


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
    fixtures = REPO / "src/tests/native/gui"
    source = tmp_path / f"{consumer}.btrc"
    source.write_text((fixtures / source.name).read_text())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    assert DependencyAudit().binary_problems(executable, _host_target_label()) == []
    portable = tmp_path / fixture
    suffix = portable.suffix[1:]
    if suffix == "pcf":
        portable.write_bytes(_pcf_strike())
    else:
        portable.write_bytes((fixtures / "fixtures" / fixture).read_bytes())
    arguments = [suffix] if consumer == "MonochromeFontConformance" else []
    raw_copy = tmp_path / "fixture.raw"
    raw_copy.write_bytes(portable.read_bytes())
    env = provider_environment(sanitized)
    inputs = [portable, raw_copy]
    if suffix == "pcf":
        compressed = tmp_path / "fixture.pcf.gz"
        compressed.write_bytes(gzip.compress(portable.read_bytes(), mtime=0))
        inputs.append(compressed)
    for path in inputs:
        run = subprocess.run([executable, path, *arguments], capture_output=True, text=True, timeout=60, env=env)
        assert run.returncode == 0, run.stdout + run.stderr
        assert expected in run.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_hinted_outlines_after_unlink(tmp_path, request, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    tests = REPO / "src/tests/native/gui"
    source = tmp_path / "HintedFontConformance.btrc"
    source.write_text((tests / source.name).read_text())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    assert DependencyAudit().binary_problems(executable, _host_target_label()) == []
    _run_hinted_suite(executable, tmp_path, provider_environment(sanitized))


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_cff_measurement_and_retained_fallback(tmp_path, request, frontend, sanitized):
    from src.tests.python.linux_provider_fixtures import (
        build_provider_program,
        provider_environment,
        require_linux_reader,
    )

    require_linux_reader()
    fixtures = REPO / "src/tests/native/gui"
    source = tmp_path / "CFFMeasurementConformance.btrc"
    source.write_bytes((fixtures / source.name).read_bytes())
    executable = build_provider_program(source, tmp_path, frontend, sanitized, request)
    assert DependencyAudit().binary_problems(executable, _host_target_label()) == []
    _run_cff_suite(executable, tmp_path, provider_environment(sanitized))


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
