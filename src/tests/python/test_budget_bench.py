"""Contracts of the bucket-1 budget harness: its statistics, parsers, manifest and command wiring."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from tools import budget_bench as bench

REPO = Path(__file__).resolve().parents[3]

BSD_TIME = """\
btrcc timing: lex=1000us
       43.21 real        40.12 user         2.01 sys
          3184183936  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
         1084717529574  instructions retired
          140000000000  cycles elapsed
          3100000000  peak memory footprint
"""

GNU_TIME = """\
\tCommand being timed: "btrcc src/BTRSmith.btrc"
\tUser time (seconds): 40.12
\tSystem time (seconds): 2.01
\tPercent of CPU this job got: 98%
\tElapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}
\tMaximum resident set size (kbytes): 3109554
\tExit status: 0
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "bsm"
    (root / "src").mkdir(parents=True)
    (root / bench.ENTRY).write_text("int main() { return 0; }\n")
    return root


@pytest.fixture
def btrcc(tmp_path: Path) -> Path:
    """A stand-in compiler: it copies its input to the -o path."""
    path = tmp_path / "fake-btrcc"
    path.write_text(
        '#!/bin/sh\nprevious=""\nwhile [ $# -gt 0 ]; do\n'
        '  if [ "$1" = -o ]; then exec cp "$previous" "$2"; fi\n'
        '  previous="$1"; shift\ndone\nexit 2\n'
    )
    path.chmod(0o755)
    return path


def settings(workspace: Path, out: Path, *options: str, btrcc: Path | None = None) -> bench.BenchSettings:
    arguments = ["--workspace", str(workspace), "--out", str(out), *options]
    if btrcc is not None:
        arguments = ["--btrcc", str(btrcc), *arguments]
    return bench.BenchSettings.parse(arguments)


# -- statistics ---------------------------------------------------------------


@pytest.mark.parametrize(
    "samples,median,p95",
    [
        ([4.0], 4.0, 4.0),
        ([5.0, 1.0, 3.0, 2.0, 4.0], 3.0, 5.0),  # five cold samples: p95 is the maximum
        ([float(value) for value in range(20, 0, -1)], 10.5, 19.0),  # twenty: the nineteenth smallest
        ([float(value) for value in range(1, 101)], 50.5, 95.0),
        ([1.0, 2.0], 1.5, 2.0),
    ],
)
def test_median_and_nearest_rank_p95(samples, median, p95):
    assert bench.Distribution.median(samples) == median
    assert bench.Distribution.nearest_rank(samples, 95) == p95


def test_empty_distribution_has_no_statistics():
    assert bench.Distribution.median([]) is None
    assert bench.Distribution.nearest_rank([], 95) is None


def test_scenario_summary_reports_every_sample_and_numeric_metric_medians(capsys):
    scenario = bench.Scenario("edit-navigation")
    for index, total in enumerate((9.5, 9.7, 9.6)):
        scenario.add(
            total,
            compile_s=total - 2.0,
            native_s=2.0,
            metrics={"native_compiled_units": index, "native_link_cache": "hit", "flag": True, "absent": None},
        )
    scenario.add(12.0)
    summary = scenario.summary()
    assert summary["samples"] == [9.5, 9.7, 9.6, 12.0]
    assert summary["compile_native"] == [[7.5, 2.0], [7.7, 2.0], [7.6, 2.0], None]
    assert (summary["median"], summary["p95"], summary["max"]) == (9.65, 12.0, 12.0)
    assert summary["metric_medians"] == {"native_compiled_units": 1.0}
    assert summary["metrics"][0] == {"native_compiled_units": 0, "native_link_cache": "hit", "flag": True}
    assert scenario.compile_samples() == pytest.approx([7.5, 7.7, 7.6])
    assert "edit-navigation #4:   12.00 s" in capsys.readouterr().out


# -- parsers ------------------------------------------------------------------


def test_bsd_time_report_reads_bytes_and_apple_counters():
    report = bench.TimeReport.parse(BSD_TIME, "darwin")
    assert report == bench.TimeReport(43.21, 40.12, 2.01, 3184183936, 3100000000, 1084717529574)
    assert bench.TimeReport.command("darwin") == ["/usr/bin/time", "-l"]
    assert report.metrics("compiler_")["compiler_peak_footprint_bytes"] == 3100000000


@pytest.mark.parametrize("elapsed,wall", [("0:43.21", 43.21), ("1:02:03", 3723.0), ("12:00.50", 720.5)])
def test_gnu_time_report_reads_kibibytes_and_both_clock_forms(elapsed, wall):
    report = bench.TimeReport.parse(GNU_TIME.format(elapsed=elapsed), "linux")
    assert report.wall_s == pytest.approx(wall)
    assert (report.user_s, report.system_s) == (40.12, 2.01)
    assert report.max_rss_bytes == 3109554 * 1024
    assert report.peak_footprint_bytes is None and report.instructions_retired is None
    assert bench.TimeReport.command("linux") == ["/usr/bin/time", "-v"]


def test_time_report_of_unrelated_output_is_empty():
    assert bench.TimeReport.parse("nothing here", "darwin") == bench.TimeReport()
    assert bench.TimeReport.parse("nothing here", "linux") == bench.TimeReport()


def test_phase_timing_names_the_owner_by_its_worker_count():
    stderr = (
        "warning: noise\n"
        "btrcc timing: grammar=295us lex=1000us g-members=10us g-members=5us instance-closure=class:0+277r,method:0+0r\n"
        "btrcc timing: l-setup=2000000us u-merge=3us module-unit-workers=4 a-records-stored(replayed=9,journaled=3)=807us\n"
        "btrcc timing: l-setup=1000000us\n"
    )
    worker, owner, other = bench.PhaseTiming.parse(stderr)
    assert (worker.role, owner.role, other.role) == ("worker", "owner", "worker")
    assert worker.phases_s == pytest.approx({"grammar": 0.000295, "lex": 0.001, "g-members": 0.000015})
    assert worker.facts == ("instance-closure=class:0+277r,method:0+0r",)
    assert owner.phases_s["a-records-stored(replayed=9,journaled=3)"] == 0.000807
    assert owner.facts == ("module-unit-workers=4",)
    assert owner.as_dict()["total_s"] == pytest.approx(2.00081)


def test_phase_timing_without_a_pool_makes_the_last_line_the_owner():
    lines = bench.PhaseTiming.parse("btrcpy timing: lex=1500us\nbtrcpy timing: emit=250us\n")
    assert [(line.compiler, line.role) for line in lines] == [("btrcpy", "worker"), ("btrcpy", "owner")]
    assert bench.PhaseTiming.parse("no timing\n") == []


def test_process_tree_rss_sums_only_descendants():
    listing = "  1     0  100\n 10     1  200\n 11    10  300\n 12    11  400\n 20     1  999\n bad line\n"
    assert bench.ProcessTreeSampler.tree_rss(10, listing) == (300 + 400) * 1024
    assert bench.ProcessTreeSampler.tree_rss(1, listing) == (200 + 300 + 400 + 999) * 1024


def test_process_tree_sampler_returns_the_action_result():
    result, peak = bench.ProcessTreeSampler(interval=0.01).run(lambda: 42)
    assert result == 42 and peak >= 0


# -- batch manifest -----------------------------------------------------------


def manifest_data(**changes):
    data = {
        "schema": 1,
        "status": "final",
        "entries": [{"name": f"Test{index}", "source": f"tests/integration/Test{index}.btrc"} for index in range(10)],
    }
    data.update(changes)
    return data


def test_shipped_batch_manifest_is_a_valid_placeholder_of_ten():
    manifest = bench.BatchManifest.load(bench.DEFAULT_BATCH_MANIFEST)
    assert manifest.placeholder
    assert len(manifest.entries) == bench.BatchManifest.SIZE == 10
    assert all(entry.source.startswith("tests/integration/") for entry in manifest.entries)


def test_batch_manifest_reads_arguments_and_environment():
    data = manifest_data()
    data["entries"][0].update(arguments=["--quick"], environment={"B": "2", "A": "1"})
    manifest = bench.BatchManifest.parse(data)
    assert not manifest.placeholder
    assert manifest.entries[0].arguments == ("--quick",)
    assert manifest.entries[0].environment == (("A", "1"), ("B", "2"))


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda data: data.update(schema=2), "schema must be 1"),
        (lambda data: data.update(status="draft"), "status must be one of"),
        (lambda data: data.update(extra=1), "unknown keys"),
        (lambda data: data["entries"].pop(), "exactly 10"),
        (lambda data: data["entries"][1].update(name="Test0"), "duplicate entry names"),
        (lambda data: data["entries"][1].update(source="tests/integration/Test0.btrc"), "duplicate entry sources"),
        (lambda data: data["entries"][2].update(source="/abs/Test.btrc"), "normalized relative"),
        (lambda data: data["entries"][2].update(source="../outside/Test.btrc"), "normalized relative"),
        (lambda data: data["entries"][2].update(source="tests/./Test.btrc"), "normalized relative"),
        (lambda data: data["entries"][2].update(source="tests/Test.c"), "normalized relative"),
        (lambda data: data["entries"][2].update(source="tests\\Test.btrc"), "POSIX path"),
        (lambda data: data["entries"][3].update(name="1bad"), "name must match"),
        (lambda data: data["entries"][3].update(arguments="--flag"), "arguments must be a list"),
        (lambda data: data["entries"][3].update(environment={"A": 1}), "environment must map"),
        (lambda data: data["entries"][3].update(timeout=5), "unknown keys"),
    ],
)
def test_batch_manifest_rejects_malformed_input(mutate, message):
    data = manifest_data()
    mutate(data)
    with pytest.raises(ValueError, match=message):
        bench.BatchManifest.parse(data)


def test_batch_manifest_names_missing_sources(tmp_path):
    manifest = bench.BatchManifest.parse(manifest_data())
    (tmp_path / "tests/integration").mkdir(parents=True)
    for entry in manifest.entries[:-1]:
        (tmp_path / entry.source).write_text("")
    with pytest.raises(ValueError, match=r"Test9\.btrc"):
        manifest.check_sources(tmp_path)


# -- fixtures -----------------------------------------------------------------


@pytest.mark.parametrize("fixture", [*bench.EDIT_FIXTURES, bench.INSTANCE_FIXTURE, bench.INTERFACE_FIXTURE])
def test_every_fixture_revision_is_novel_and_reversible(fixture):
    revisions = [fixture.render(revision) for revision in range(25)]
    assert revisions[0] == fixture.original
    assert len(set(revisions)) == len(revisions)
    # Reverting finds the original text exactly once, so no revision may contain it.
    assert all(fixture.original not in text for text in revisions[1:])


def test_instance_fixture_adds_a_generic_instance_and_its_marked_stdlib_call():
    text = bench.INSTANCE_FIXTURE.render(7)
    assert "Vector<Vector<double>> budgetBenchRows0007" in text
    assert f"Math.{bench.INSTANCE_FIXTURE.new_call}(7, 6)" in text
    assert text.endswith("(double)(budgetBenchRows0007.len - 1);")


def test_interface_fixture_changes_the_layout_every_revision():
    assert "public long long budgetBenchLayout0001 = 0;" in bench.INTERFACE_FIXTURE.render(1)
    assert "public int budgetBenchLayout0002 = 0;" in bench.INTERFACE_FIXTURE.render(2)
    assert bench.INTERFACE_FIXTURE.render(2).startswith("class AuthoredTimeline {\n")


def test_fixture_and_scenario_names_are_unique():
    names = [fixture.name for fixture in (*bench.EDIT_FIXTURES, bench.INSTANCE_FIXTURE, bench.INTERFACE_FIXTURE)]
    assert len(set(names)) == len(names)
    assert len(set(bench.SCENARIOS)) == len(bench.SCENARIOS)


# -- settings and wiring --------------------------------------------------------


@pytest.mark.parametrize(
    "system,machine,expected", [("Darwin", "arm64", "macos-arm64"), ("Linux", "x86_64", "linux-x86_64")]
)
def test_host_target_uses_btrsmiths_spelling(system, machine, expected):
    assert bench.HostTarget.resolve(None, system, machine) == expected


def test_explicit_target_is_validated_and_kept():
    assert bench.HostTarget.resolve("linux-aarch64") == "linux-aarch64"
    with pytest.raises(ValueError):
        bench.HostTarget.resolve("plan9-mips")


def test_self_compile_entry_follows_the_host():
    assert bench.HostTarget.self_compile_entry("Darwin") == "src/compiler/btrc/cli/MacOSMain.btrc"
    assert bench.HostTarget.self_compile_entry("Linux") == "src/compiler/btrc/BtrccMain.btrc"
    for system in ("Darwin", "Linux"):
        assert (REPO / bench.HostTarget.self_compile_entry(system)).is_file()


def test_defaults_measure_selfhost_dev_module_units_on_the_host(workspace, tmp_path, btrcc):
    configured = settings(workspace, tmp_path / "out", btrcc=btrcc)
    assert (configured.frontend, configured.mode, configured.units, configured.entry) == (
        "selfhost",
        "dev",
        "module",
        "direct",
    )
    assert configured.target == bench.HostTarget.resolve(None)
    assert configured.scenarios == (
        "cold",
        "edit-navigation",
        "edit-ui-controller",
        "edit-audio-preparation",
        "noop",
        "touch",
        "memory",
    )
    assert (configured.cold_samples, configured.incremental_samples) == (5, 20)
    assert configured.workers == (1, 2, 4, 8)
    assert configured.describe()["btrcc"] == str(btrcc)


def test_release_defaults_to_the_whole_program_split(workspace, tmp_path, btrcc):
    configured = settings(workspace, tmp_path / "out", "--mode", "release", btrcc=btrcc)
    assert configured.flavor == bench.Flavor("release", "whole")
    variant = settings(workspace, tmp_path / "out", "--mode", "release", "--units", "module", btrcc=btrcc)
    assert variant.flavor == bench.Flavor("release", "module")


def test_dry_run_takes_one_sample_of_every_scenario(workspace, tmp_path):
    (workspace / "tests/integration").mkdir(parents=True)
    for entry in bench.BatchManifest.load(bench.DEFAULT_BATCH_MANIFEST).entries:
        (workspace / entry.source).write_text("")
    configured = settings(workspace, tmp_path / "out", "--frontend", "reference", "--scenarios", "all", "--dry-run")
    assert configured.scenarios == bench.SCENARIOS
    assert (configured.cold_samples, configured.incremental_samples) == (1, 1)
    assert configured.btrcc is None


@pytest.mark.parametrize(
    "options,message",
    [
        ((), "needs --btrcc"),
        (("--frontend", "reference", "--scenarios", "cold,bogus"), "unknown scenario 'bogus'"),
        (("--frontend", "reference", "--scenarios", ","), "names no scenario"),
        (("--frontend", "reference", "--entry", "make", "--scenarios", "cold,memory,corpus"), "memory, corpus"),
        (("--frontend", "reference", "--workers", "1,x"), "comma-separated integers"),
        (("--frontend", "reference", "--workers", "2,2"), "distinct counts"),
        (("--frontend", "reference", "--workers", "0"), "distinct counts"),
        (("--frontend", "reference", "--cold-samples", "0"), "must be positive"),
        (("--frontend", "reference", "--target", "plan9-mips"), "--target"),
        (("--frontend", "reference", "--scenarios", "batch"), "is a placeholder"),
    ],
)
def test_invalid_runs_are_rejected_before_any_build(workspace, tmp_path, capsys, options, message):
    with pytest.raises(SystemExit):
        settings(workspace, tmp_path / "out", *options)
    assert message in capsys.readouterr().err


def test_out_may_not_overlap_the_workspace(workspace, tmp_path, capsys):
    with pytest.raises(SystemExit):
        settings(workspace, workspace / "run", "--frontend", "reference")
    with pytest.raises(SystemExit):
        settings(workspace, tmp_path, "--frontend", "reference")
    assert "outside the workspace" in capsys.readouterr().err


def test_workspace_must_hold_the_product_entry(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit):
        settings(tmp_path / "empty", tmp_path / "out", "--frontend", "reference")
    assert "has no src/BTRSmith.btrc" in capsys.readouterr().err


def test_batch_dry_run_accepts_the_placeholder_when_its_sources_exist(workspace, tmp_path, capsys):
    manifest = bench.BatchManifest.load(bench.DEFAULT_BATCH_MANIFEST)
    with pytest.raises(SystemExit):
        settings(workspace, tmp_path / "out", "--frontend", "reference", "--scenarios", "batch", "--dry-run")
    assert "missing from" in capsys.readouterr().err
    (workspace / "tests/integration").mkdir(parents=True)
    for entry in manifest.entries:
        (workspace / entry.source).write_text("")
    configured = settings(workspace, tmp_path / "out", "--frontend", "reference", "--scenarios", "batch", "--dry-run")
    assert configured.scenarios == ("batch",)


def test_direct_commands_follow_mode_and_units(workspace, tmp_path, btrcc):
    configured = settings(workspace, tmp_path / "out", "--target", "macos-arm64", btrcc=btrcc)
    commands = bench.BuildCommands(configured, tmp_path / "bin")
    paths = bench.ProductPaths.direct(tmp_path / "build")
    dev = commands.compile(paths, bench.Flavor("dev", "module"), jobs=4)
    assert dev == [
        str(btrcc),
        "--strict-imports",
        "--target",
        "macos-arm64",
        "--debug",
        "--module-units",
        "--jobs",
        "4",
        "--emit-link-plan",
        str(tmp_path / "build/p.json"),
        "--emit-units",
        str(tmp_path / "build/p"),
        bench.ENTRY,
        "-o",
        str(tmp_path / "build/p.c"),
    ]
    release = commands.compile(paths, bench.Flavor("release", "whole"))
    assert "--debug" not in release and "--module-units" not in release and "--jobs" not in release
    assert release[release.index("--emit-units") + 1] == str(tmp_path / "build/p")
    native_dev = commands.native(paths, bench.Flavor("dev", "module"), tmp_path / "objects")
    assert native_dev[:4] == [sys.executable, "-P", "-m", "tools.native_plan"]
    assert native_dev[native_dev.index("--jobs") + 1] == "8"
    assert {"--debug-info", "--optimization", "--object-cache", "--report-json"} <= set(native_dev)
    native_release = commands.native(paths, bench.Flavor("release", "whole"), tmp_path / "objects")
    assert "--debug-info" not in native_release and "--optimization" not in native_release


def test_reference_frontend_runs_this_checkouts_compiler(workspace, tmp_path):
    configured = settings(workspace, tmp_path / "out", "--frontend", "reference")
    commands = bench.BuildCommands(configured, tmp_path / "bin")
    assert commands.frontend() == [sys.executable, "-P", "-m", "src.compiler.python.main"]
    command = commands.compile(bench.ProductPaths.direct(tmp_path / "build"), configured.flavor)
    assert command[:4] == commands.frontend()


@pytest.mark.parametrize("frontend", ["selfhost", "reference"])
def test_make_entry_drives_btrsmiths_product_make(workspace, tmp_path, btrcc, frontend):
    configured = settings(
        workspace,
        tmp_path / "out",
        "--frontend",
        frontend,
        "--entry",
        "make",
        "--scenarios",
        "cold,release,edit,instance-edit,interface-edit,noop,touch",
        "--mode",
        "release",
        "--units",
        "module",
        "--native-jobs",
        "6",
        btrcc=btrcc if frontend == "selfhost" else None,
    )
    commands = bench.BuildCommands(configured, tmp_path / "bin")
    state = bench.State(tmp_path / "out/warm")
    command = commands.make(state, configured.flavor, "btrsmith-native")
    assert command[:4] == ["make", "-f", "make/Product.mk", "btrsmith-native"]
    assignments = dict(item.split("=", 1) for item in command[4:])
    assert assignments["BUILD"] == "release"
    assert assignments["BTRC_FRONTEND"] == frontend
    assert assignments["BTRC_BUILD_FLAGS"] == "--module-units"
    assert assignments["BUILD_DIR"] == str(state.build)
    assert assignments["BTRC_OBJECT_CACHE"] == str(state.objects)
    assert assignments["CODESIGN_IDENTITY"] == "-"
    assert shlex.split(assignments["NATIVE_PLAN_FLAGS"]) == [
        "--jobs",
        "6",
        "--report-json",
        str(state.build / "native.json"),
    ]
    assert shlex.split(assignments["NATIVE_PLAN"]) == [str(tmp_path / "bin/btrc-native-plan")]
    if frontend == "selfhost":
        assert shlex.split(assignments["BTRCC"]) == [str(btrcc)] and "BTRCPY" not in assignments
    else:
        assert shlex.split(assignments["BTRCPY"]) == [str(tmp_path / "bin/btrcpy")] and "BTRCC" not in assignments
    dev = commands.make(state, bench.Flavor("dev", "whole"), "btrsmith-source")
    dev_assignments = dict(item.split("=", 1) for item in dev[4:])
    assert dev_assignments["BTRC_BUILD_FLAGS"] == "--debug"
    assert shlex.split(dev_assignments["NATIVE_PLAN_FLAGS"])[:3] == ["--optimization", "0", "--debug-info"]
    paths = bench.ProductPaths.make(state.build, frontend)
    assert paths.executable == state.build / "bin" / f"btrsmith.{frontend}"
    assert paths.units_prefix == paths.generated_c == state.build / "generated" / f"btrsmith.{frontend}.c"


def test_make_wrappers_run_this_checkouts_tools(workspace, tmp_path):
    configured = settings(workspace, tmp_path / "out", "--frontend", "reference")
    scripts = bench.BuildCommands(configured, tmp_path / "bin").wrapper_scripts()
    assert set(scripts) == {"btrcpy", "btrc-native-plan"}
    assert f"PYTHONPATH={shlex.quote(str(REPO))}" in scripts["btrcpy"]
    assert scripts["btrcpy"].rstrip().endswith('-m src.compiler.python.main "$@"')
    assert scripts["btrc-native-plan"].rstrip().endswith('-m tools.native_plan "$@"')


# -- outputs -------------------------------------------------------------------


def test_run_directory_replaces_only_its_own_runs(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("mine")
    with pytest.raises(ValueError, match="refusing to replace"):
        bench.RunDirectory.prepare(foreign)
    run = tmp_path / "run"
    bench.RunDirectory.prepare(run)
    (run / "ws").mkdir()
    (run / "report.json").write_text("{}")
    (run / "timing").mkdir()
    bench.RunDirectory.prune(run)
    assert sorted(child.name for child in run.iterdir()) == [bench.RunDirectory.MARKER, "report.json", "timing"]
    bench.RunDirectory.prepare(run)
    assert [child.name for child in run.iterdir()] == [bench.RunDirectory.MARKER]


def test_symbols_and_bodies_ignore_unit_split_and_session_numbers(tmp_path):
    first = tmp_path / "p.c"
    first.write_text(
        "typedef struct btrc_Vector_double btrc_Vector_double;\n"
        "static void Math_gcd(int a, int b) {\n"
        '#line 4 "x.btrc"\n'
        "\treturn __lambda_12(a);\n"
        "}\n"
    )
    second = tmp_path / "p.unit-A.c"
    second.write_text("int helper_3(void) {\n\treturn 1;\n}\n")
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps({"emitted-units": [str(second)]}))
    paths = bench.ProductPaths.direct(tmp_path)
    files = paths.c_files(tmp_path)
    assert files == [first, second]
    symbols = bench.SymbolSet.scan(files)
    assert symbols.structs == {"btrc_Vector_double"}
    assert symbols.functions == {"Math_gcd", "helper_3"}
    assert symbols.added_since(bench.SymbolSet(frozenset(), frozenset({"helper_3"}))).functions == {"Math_gcd"}
    bodies = bench.BudgetBench.function_bodies(files)
    assert bodies == {"Math_gcd": {"return_(a);"}, "_": {"return1;"}}


def test_relative_emitted_units_resolve_in_the_workspace(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps({"emitted-units": ["build/p.unit-1.c"]}))
    assert bench.ProductPaths.direct(tmp_path).c_files(tmp_path / "ws")[1] == tmp_path / "ws/build/p.unit-1.c"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX stand-in compiler")
def test_self_compile_dry_run_writes_a_report(workspace, tmp_path, btrcc):
    out = tmp_path / "run"
    configured = settings(workspace, out, "--scenarios", "self-compile", "--dry-run", btrcc=btrcc)
    report = bench.BudgetBench(configured).run()
    written = json.loads((out / "report.json").read_text())
    assert written == report
    assert written["schema"] == 2 and written["dry_run"] is True and written["failure"] is None
    scenario = written["scenarios"]["self-compile"]
    assert len(scenario["samples"]) == 1
    assert scenario["facts"]["entry"] == configured.self_compile_entry
    assert scenario["metrics"][0]["c_bytes"] == (REPO / configured.self_compile_entry).stat().st_size
    if bench.TimeReport.available():
        assert scenario["metrics"][0]["max_rss_bytes"] > 0
    assert written["configuration"]["frontend"] == "selfhost"
    assert written["provenance"]["btrcc"]["path"] == str(btrcc)
    assert sorted(child.name for child in out.iterdir()) == [bench.RunDirectory.MARKER, "report.json"]


def test_a_failed_build_still_writes_its_report(workspace, tmp_path):
    failing = tmp_path / "failing-btrcc"
    failing.write_text("#!/bin/sh\necho broken >&2\nexit 3\n")
    failing.chmod(0o755)
    out = tmp_path / "run"
    code = bench.main(
        ["--btrcc", str(failing), "--workspace", str(workspace), "--out", str(out), "--scenarios", "self-compile"]
    )
    assert code == 1
    written = json.loads((out / "report.json").read_text())
    assert "self-compile failed (3)" in written["failure"] and "broken" in written["failure"]
    assert written["scenarios"]["self-compile"]["samples"] == []
    assert (out / "ws").is_dir()  # a failed run keeps its evidence


def comparison(
    tmp_path: Path, workspace: Path, outputs: dict[str, list[str]]
) -> tuple[bench.BudgetBench, bench.Scenario]:
    """A bench whose two builds have equal C and whose smoke prints `outputs` in turn."""
    runner = object.__new__(bench.BudgetBench)
    runner.settings = settings(workspace, tmp_path / "out", "--frontend", "reference")
    runner.workspace = workspace
    for name in ("warm", "clean"):
        build = tmp_path / name / "build"
        build.mkdir(parents=True)
        (build / "p.c").write_text("int f(void) {\n\treturn 1;\n}\n")
        (build / "p.json").write_text(json.dumps({"emitted-units": []}))
    printed = {
        tmp_path / name / "build/BTRSmith": iter(outputs[label])
        for name, label in (("warm", "incremental"), ("clean", "clean"))
    }
    runner.smoke = lambda executable: (next(printed[executable]), "Native agent channel unavailable: busy\n")
    return runner, bench.Scenario("edit-navigation")


def test_clean_build_check_reruns_a_timing_dependent_smoke(tmp_path, workspace, capsys):
    runner, scenario = comparison(
        tmp_path,
        workspace,
        {
            "incremental": ["exit 0\nPASS teardown=3\n", "exit 0\nPASS teardown=4\n"],
            "clean": ["exit 0\nPASS teardown=4\n"] * 2,
        },
    )
    runner.compare(scenario, bench.State(tmp_path / "warm"), bench.State(tmp_path / "clean"))
    assert "bodies equal; smoke equal after 1 rerun(s): 'exit 0\\nPASS teardown=4'" in scenario.notes[0]
    assert scenario.notes[1] == "smoke stderr: Native agent channel unavailable: busy"


def test_clean_build_check_fails_a_reproducible_difference(tmp_path, workspace, capsys):
    runner, scenario = comparison(
        tmp_path,
        workspace,
        {"incremental": ["exit 0\nPASS teardown=3\n"] * 3, "clean": ["exit 0\nPASS teardown=4\n"] * 3},
    )
    with pytest.raises(RuntimeError, match="differs from a clean build"):
        runner.compare(scenario, bench.State(tmp_path / "warm"), bench.State(tmp_path / "clean"))
    assert "smoke DIFFERS after 2 rerun(s)" in scenario.notes[0]
