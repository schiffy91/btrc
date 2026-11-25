"""Tests for precompiled user-package archives (--build-package / --package-archive)
and NativePlanBuilder.build_library (static .a and shared .dylib/.so)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.application import pipeline as application_pipeline
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts import package_archive as pa
from src.compiler.python.artifacts.package_archive import PackageArchiveError, PackageArtifactRepository
from src.compiler.python.artifacts.stdlib import StdlibArtifactRepository
from src.compiler.python.cli.compiler import CompilerCommand
from tools.native_plan import NativePlanBuilder


def _archive_compiler() -> Compiler:
    return Compiler(
        CompilationPipeline(
            archive_repository=StdlibArtifactRepository(),
            package_archive_repository=PackageArtifactRepository(),
        )
    )


def _write_sample_workspace(root: Path) -> tuple[Path, Path, Path]:
    """Create a multi-module library package and a consumer app package."""
    lib_dir = root / "metric_lib"
    (lib_dir / "src" / "Core").mkdir(parents=True)
    (lib_dir / "btrc.toml").write_text(
        'manifest-version = 1\n\n'
        '[package]\n'
        'name = "metric_lib"\n'
        'exports = ["Core.Point", "Core.Stats"]\n',
        encoding="utf-8",
    )
    (lib_dir / "src" / "Core" / "Point.btrc").write_text(
        "int g_pointCreatedCount = 0;\n\n"
        "interface Scorable {\n"
        "    int score();\n"
        "}\n\n"
        "class Point implements Scorable {\n"
        "    public int x;\n"
        "    public int y;\n"
        "    public string label;\n\n"
        "    public Point(int x, int y, string label) {\n"
        "        self.x = x;\n"
        "        self.y = y;\n"
        "        self.label = label;\n"
        "        g_pointCreatedCount = g_pointCreatedCount + 1;\n"
        "    }\n\n"
        "    public int score() {\n"
        "        return self.x * 10 + self.y;\n"
        "    }\n\n"
        "    public string describe() {\n"
        '        return f"{self.label}({self.x},{self.y})";\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (lib_dir / "src" / "Core" / "Stats.btrc").write_text(
        "import Library.BackgroundJobs;\n"
        "import Library.JSON;\n"
        "import Library.Map;\n"
        "import Library.Vector;\n"
        'import "./Point.btrc";\n\n'
        "class Stats {\n"
        "    public Vector<Point> points;\n\n"
        "    public Stats() {\n"
        "        self.points = [];\n"
        "    }\n\n"
        "    public void add(Point p) {\n"
        "        self.points.push(p);\n"
        "    }\n\n"
        "    public int totalScore() {\n"
        "        int sum = 0;\n"
        "        for p in self.points {\n"
        "            sum = sum + p.score();\n"
        "        }\n"
        "        return sum;\n"
        "    }\n\n"
        "    public int requireNonEmpty() {\n"
        "        if (self.points.len == 0) {\n"
        '            throw "empty-stats";\n'
        "        }\n"
        "        return self.points.len;\n"
        "    }\n\n"
        "    public string summaryJson() {\n"
        "        var obj = JSONValue.makeObject();\n"
        '        obj.set("count", JSONValue.makeInt(self.points.len));\n'
        '        obj.set("total", JSONValue.makeInt(self.totalScore()));\n'
        "        return obj.stringify();\n"
        "    }\n"
        "}\n\n"
        "int sumScorables(Vector<Scorable> items) {\n"
        "    int total = 0;\n"
        "    for item in items {\n"
        "        total = total + item.score();\n"
        "    }\n"
        "    return total;\n"
        "}\n",
        encoding="utf-8",
    )

    app_dir = root / "metric_app"
    (app_dir / "src").mkdir(parents=True)
    (app_dir / "btrc.toml").write_text(
        'manifest-version = 1\n\n'
        '[package]\n'
        'name = "metric_app"\n\n'
        '[dependencies]\n'
        'metric_lib = { path = "../metric_lib" }\n',
        encoding="utf-8",
    )
    app_main = app_dir / "src" / "Main.btrc"
    app_main.write_text(
        "import Library.BackgroundJobs;\n"
        "import Library.Vector;\n"
        "import metric_lib.Core.Point;\n"
        "import metric_lib.Core.Stats;\n\n"
        "class AppMetric implements Scorable {\n"
        "    public int weight;\n"
        "    public AppMetric(int weight) { self.weight = weight; }\n"
        "    public int score() { return self.weight * 3; }\n"
        "}\n\n"
        "int main() {\n"
        "    var empty = Stats();\n"
        "    bool caught = false;\n"
        "    try {\n"
        "        empty.requireNonEmpty();\n"
        "    } catch (string err) {\n"
        '        caught = err.equals("empty-stats");\n'
        "    }\n"
        "    var stats = Stats();\n"
        '    var p1 = Point(2, 5, "alpha");\n'
        '    var p2 = Point(4, 1, "beta");\n'
        "    stats.add(p1);\n"
        "    stats.add(p2);\n"
        "    Vector<AppMetric> localMetrics = [];\n"
        "    localMetrics.push(AppMetric(7));\n"
        "    localMetrics.push(AppMetric(3));\n"
        "    int localSum = 0;\n"
        "    for m in localMetrics { localSum = localSum + m.score(); }\n"
        "    Vector<Scorable> mixed = [];\n"
        "    mixed.push(p1);\n"
        "    mixed.push(AppMetric(5));\n"
        "    int ifaceSum = sumScorables(mixed);\n"
        '    print(f"caught={caught} created={g_pointCreatedCount} desc={p1.describe()} '
        'total={stats.totalScore()} local={localSum} iface={ifaceSum} json={stats.summaryJson()}");\n'
        "    return caught ? 0 : 1;\n"
        "}\n",
        encoding="utf-8",
    )
    return lib_dir, app_dir, app_main


def test_package_archive_workflow_is_instance_owned():
    for owner_module in (application_pipeline, pa):
        module = ast.parse(Path(owner_module.__file__).read_text(encoding="utf-8"))
        loose_behavior = [
            node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert loose_behavior == []

    assert not Compiler().package_archive_available
    assert _archive_compiler().package_archive_available
    assert callable(_archive_compiler().build_package_archive)


def test_build_package_writes_verified_archive_artifacts(tmp_path):
    lib_dir, _, _ = _write_sample_workspace(tmp_path)
    archive_dir = tmp_path / "pkg-archive"
    command = CompilerCommand(_archive_compiler())
    assert command.run(["--build-package", str(lib_dir), "-o", str(archive_dir)]) == 0

    for name in ("metric_lib.h", "metric_lib.c", "metric_lib.link.json", "metric_lib.manifest"):
        assert (archive_dir / name).is_file()

    target = Compiler.select_target(None)
    assert isinstance(target, str)
    manifest = PackageArtifactRepository().load(str(archive_dir), target)
    assert manifest["package"] == "metric_lib"
    assert manifest["exports"] == ["Core.Point", "Core.Stats"]
    assert "Point" in manifest["types"]
    assert "Stats" in manifest["types"]
    assert "Point_new" in manifest["functions"]
    assert "Stats_totalScore" in manifest["functions"]
    assert "g_pointCreatedCount" in manifest["global_decl_names"]
    assert "BTRC_PKG_METRIC_LIB_H" in (archive_dir / "metric_lib.h").read_text(encoding="utf-8")


def test_package_archive_links_static_and_shared_matching_inline(tmp_path):
    lib_dir, _, app_main = _write_sample_workspace(tmp_path)
    archive_dir = tmp_path / "pkg-archive"
    command = CompilerCommand(_archive_compiler())
    assert command.run(["--build-package", str(lib_dir), "-o", str(archive_dir)]) == 0

    builder = NativePlanBuilder()
    static_lib = tmp_path / "lib" / "libmetric_lib.a"
    shared_ext = ".dylib" if sys.platform == "darwin" else ".so"
    shared_lib = tmp_path / "lib" / f"libmetric_lib{shared_ext}"
    static_lib.parent.mkdir(parents=True)

    builder.build_library(
        plan_path=archive_dir / "metric_lib.link.json",
        generated_c=archive_dir / "metric_lib.c",
        output=static_lib,
        shared=False,
        optimization=0,
    )
    assert static_lib.is_file() and static_lib.stat().st_size > 0

    builder.build_library(
        plan_path=archive_dir / "metric_lib.link.json",
        generated_c=archive_dir / "metric_lib.c",
        output=shared_lib,
        shared=True,
        install_name=f"@rpath/{shared_lib.name}" if sys.platform == "darwin" else shared_lib.name,
        optimization=0,
    )
    assert shared_lib.is_file() and shared_lib.stat().st_size > 0

    # Baseline inline compile & run
    inline_c = tmp_path / "inline.c"
    inline_plan = tmp_path / "inline.link.json"
    inline_bin = tmp_path / "app-inline"
    assert (
        command.run(
            [str(app_main), "-o", str(inline_c), "--emit-link-plan", str(inline_plan)]
        )
        == 0
    )
    builder.build(plan_path=inline_plan, generated_c=inline_c, output=inline_bin, optimization=0)
    inline_run = subprocess.run([str(inline_bin)], capture_output=True, text=True, check=True)

    # Consumer compile with --package-archive
    ref_c = tmp_path / "app-ref.c"
    ref_plan = tmp_path / "app-ref.link.json"
    assert (
        command.run(
            [
                str(app_main),
                "--package-archive",
                str(archive_dir),
                "-o",
                str(ref_c),
                "--emit-link-plan",
                str(ref_plan),
            ]
        )
        == 0
    )
    ref_text = ref_c.read_text(encoding="utf-8")
    inline_text = inline_c.read_text(encoding="utf-8")
    assert '#include "metric_lib.h"' in ref_text
    assert len(ref_text) < len(inline_text)
    assert "Stats_totalScore(" not in ref_text or "int32_t Stats_totalScore(" not in ref_text

    # Link & run against static archive (.a)
    static_bin = tmp_path / "app-static"
    builder.build(
        plan_path=ref_plan,
        generated_c=ref_c,
        output=static_bin,
        optimization=0,
        package_archives=[(archive_dir, static_lib)],
    )
    static_run = subprocess.run([str(static_bin)], capture_output=True, text=True, check=True)
    assert static_run.stdout == inline_run.stdout

    # Link & run against shared library (.dylib / .so)
    shared_bin = tmp_path / "app-shared"
    builder.build(
        plan_path=ref_plan,
        generated_c=ref_c,
        output=shared_bin,
        optimization=0,
        package_archives=[(archive_dir, shared_lib)],
        link_flags=(f"-Wl,-rpath,{shared_lib.parent}",),
    )
    shared_run = subprocess.run([str(shared_bin)], capture_output=True, text=True, check=True)
    assert shared_run.stdout == inline_run.stdout
    assert "caught=true" in shared_run.stdout
    assert "created=2" in shared_run.stdout
    assert "desc=alpha(2,5)" in shared_run.stdout
    assert "total=66" in shared_run.stdout
    assert "local=30" in shared_run.stdout
    assert "iface=40" in shared_run.stdout

    if sys.platform == "darwin":
        otool = subprocess.run(["otool", "-L", str(shared_bin)], capture_output=True, text=True, check=True)
        assert f"@rpath/{shared_lib.name}" in otool.stdout


def test_package_archive_rejects_main_function_in_library(tmp_path):
    pkg = tmp_path / "bad_lib"
    (pkg / "src").mkdir(parents=True)
    (pkg / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "bad_lib"\nexports = ["Entry"]\n',
        encoding="utf-8",
    )
    (pkg / "src" / "Entry.btrc").write_text("int main() { return 0; }\n", encoding="utf-8")
    result = _archive_compiler().build_package_archive(str(pkg), str(tmp_path / "out"))
    assert result.failure is not None
    assert "main" in result.failure.message


def test_package_archive_deduplicates_native_units_across_shared_lib_and_consumer(tmp_path):
    lib_dir = tmp_path / "img_lib"
    (lib_dir / "src").mkdir(parents=True)
    (lib_dir / "native").mkdir(parents=True)
    (lib_dir / "native" / "gain.h").write_text(
        "#ifndef TEST_GAIN_H\n#define TEST_GAIN_H\nint imglib_apply_gain(int value, int gain);\n#endif\n",
        encoding="utf-8",
    )
    (lib_dir / "native" / "gain.c").write_text(
        '#include "gain.h"\nint imglib_apply_gain(int value, int gain) { return value * gain; }\n',
        encoding="utf-8",
    )
    (lib_dir / "btrc.toml").write_text(
        'manifest-version = 1\n'
        '[package]\n'
        'name = "img_lib"\n'
        'exports = ["Canvas"]\n\n'
        '[[native.bindings]]\n'
        'module = "Canvas"\n'
        'header = "native/gain.h"\n'
        'language = "c"\n'
        'standard = "c11"\n'
        'symbols = ["imglib_apply_gain"]\n\n'
        '[[native.sources]]\n'
        'path = "native/gain.c"\n'
        'language = "c"\n'
        'standard = "c11"\n'
        'modules = ["Canvas"]\n',
        encoding="utf-8",
    )
    (lib_dir / "src" / "Canvas.btrc").write_text(
        "import Library.Image.Pixels;\n"
        "import Library.Image.ImageCodec;\n\n"
        "Image makeSolidCanvas(int w, int h, int r, int g, int b) {\n"
        "    var img = Image(w, h);\n"
        "    var scaledR = imglib_apply_gain(r, 2);\n"
        "    var color = RGBA(scaledR, g, b, 255);\n"
        "    for (int y = 0; y < h; y++) {\n"
        "        for (int x = 0; x < w; x++) {\n"
        "            img.setPixel(x, y, color);\n"
        "        }\n"
        "    }\n"
        "    return img;\n"
        "}\n",
        encoding="utf-8",
    )

    app_dir = tmp_path / "img_app"
    (app_dir / "src").mkdir(parents=True)
    (app_dir / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "img_app"\n'
        '[dependencies]\nimg_lib = { path = "../img_lib" }\n',
        encoding="utf-8",
    )
    app_main = app_dir / "src" / "Main.btrc"
    app_main.write_text(
        "import Library.Image.Pixels;\n"
        "import img_lib.Canvas;\n\n"
        "int main() {\n"
        "    var img = makeSolidCanvas(4, 3, 10, 20, 30);\n"
        "    var px = img.pixel(2, 1);\n"
        '    print(f"{img.width}x{img.height}:{px.red},{px.green},{px.blue}");\n'
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    archive_dir = tmp_path / "img-archive"
    command = CompilerCommand(_archive_compiler())
    assert command.run(["--build-package", str(lib_dir), "-o", str(archive_dir)]) == 0

    builder = NativePlanBuilder()
    cc = "clang" if sys.platform == "darwin" else "cc"
    cxx = "clang++" if sys.platform == "darwin" else "c++"
    shared_ext = ".dylib" if sys.platform == "darwin" else ".so"
    shared_lib = tmp_path / "lib" / f"libimg_lib{shared_ext}"
    shared_lib.parent.mkdir(parents=True)
    lib_report = builder.build_library(
        plan_path=archive_dir / "img_lib.link.json",
        generated_c=archive_dir / "img_lib.c",
        output=shared_lib,
        shared=True,
        install_name=f"@rpath/{shared_lib.name}" if sys.platform == "darwin" else shared_lib.name,
        cc=cc,
        cxx=cxx,
        optimization=0,
    )
    assert lib_report.native_units > 0

    app_c = tmp_path / "img_app.c"
    app_plan = tmp_path / "img_app.link.json"
    app_bin = tmp_path / "img-app-bin"
    assert (
        command.run(
            [
                str(app_main),
                "--package-archive",
                str(archive_dir),
                "-o",
                str(app_c),
                "--emit-link-plan",
                str(app_plan),
            ]
        )
        == 0
    )
    app_report = builder.build(
        plan_path=app_plan,
        generated_c=app_c,
        output=app_bin,
        cc=cc,
        cxx=cxx,
        optimization=0,
        package_archives=[(archive_dir, shared_lib)],
        link_flags=(f"-Wl,-rpath,{shared_lib.parent}",),
    )
    assert app_report.native_units == 0
    ran = subprocess.run([str(app_bin)], capture_output=True, text=True, check=True)
    assert ran.stdout.strip() == "4x3:20,20,30"


def test_package_archive_rejects_tampered_stale_wrong_target_and_override(tmp_path):
    lib_dir, _, _ = _write_sample_workspace(tmp_path)
    archive_dir = tmp_path / "pkg-archive"
    compiler = _archive_compiler()
    built = compiler.build_package_archive(str(lib_dir), str(archive_dir))
    assert built.failure is None

    target = Compiler.select_target(None)
    assert isinstance(target, str)
    other_target = next(label for label in Compiler.target_labels() if label != target)
    with pytest.raises(PackageArchiveError, match="was built for"):
        PackageArtifactRepository().load(str(archive_dir), other_target)

    # User override conflict check
    conflict_app = tmp_path / "conflict_app"
    (conflict_app / "src").mkdir(parents=True)
    (conflict_app / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "conflict_app"\n'
        '[dependencies]\nmetric_lib = { path = "../metric_lib" }\n',
        encoding="utf-8",
    )
    conflict_main = conflict_app / "src" / "Main.btrc"
    conflict_main.write_text(
        "class Point { public int v; public Point(int v) { self.v = v; } }\n"
        "int main() { var p = Point(1); return p.v - 1; }\n",
        encoding="utf-8",
    )
    conflict_result = compiler.compile(
        conflict_main.read_text(encoding="utf-8"),
        str(conflict_main),
        CompilerOptions(package_archives=(str(archive_dir),)),
    )
    assert conflict_result.failure is not None
    assert "overrides archive-provided" in conflict_result.failure.message

    # Tampered header check
    header_path = archive_dir / "metric_lib.h"
    original_header = header_path.read_text(encoding="utf-8")
    header_path.write_text(original_header + "\n/* tampered */\n", encoding="utf-8")
    with pytest.raises(PackageArchiveError, match=r"modified metric_lib\.h"):
        PackageArtifactRepository().load(str(archive_dir), target)
    header_path.write_text(original_header, encoding="utf-8")

    # Stale source check (modifying library source without rebuilding archive)
    point_path = lib_dir / "src" / "Core" / "Point.btrc"
    point_path.write_text(point_path.read_text(encoding="utf-8") + "\n// edited\n", encoding="utf-8")
    with pytest.raises(PackageArchiveError, match="is stale"):
        PackageArtifactRepository().load(str(archive_dir), target)

    # Tampered manifest schema check
    manifest_path = archive_dir / "metric_lib.manifest"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema"] = 999
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PackageArchiveError, match="invalid or unsupported manifest"):
        PackageArtifactRepository().load(str(archive_dir), target)
