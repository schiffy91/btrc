"""Measure both frontends through the strict production native-plan compile/link path."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import default_c_compiler, default_cxx_compiler, default_toolchain
from src.tests.process_limits import RUN_TIMEOUT, TRANSPILE_TIMEOUT
from tools import budget_bench, perf

ROOT = Path(__file__).resolve().parents[3]


def test_default_drivers_are_the_budget_bench_toolchain():
    arguments = perf.Perf.parse_arguments(["Program.btrc"])
    assert (arguments.cc, arguments.cxx) == (budget_bench.CC, budget_bench.CXX) == ("clang", "clang++")


def test_phase_times_reads_both_compilers_marks():
    stderr = "noise\nbtrcpy timing: lex=1500us parse=500us analyze=2000000us\nbtrcc timing: lex=1000us emit=250us\n"
    assert perf.phase_times(stderr) == {"lex": 0.0025, "parse": 0.0005, "analyze": 2.0, "emit": 0.00025}


def test_phase_times_reads_annotated_marks_and_skips_counters():
    stderr = (
        "btrcc timing: lex=10us a-records-stored(replayed=3,journaled=1)=20us "
        "a-instances(replayed=4)=5us module-unit-workers=2 module-units=lowered:3,reused:2 "
        "setjmp-analyses=2/3,rounds=1,levels=2 relowered-stale=4 "
        "instance-closure=class:3+2r,method:4+1r a-records-stored(replayed=0,journaled=7)=30us\n"
    )
    assert perf.phase_times(stderr) == pytest.approx(
        {"lex": 0.00001, "a-records-stored": 0.00005, "a-instances": 0.000005}
    )


TIMER_CALL = re.compile(r'BtrccPhaseTimer\.(mark|note)\((f?)"([^"]*)"')
INTERPOLATION = re.compile(r"\{[^{}]*\}")


def test_phase_times_parses_every_mark_the_compilers_print():
    """Each mark either compiler can print is one phase; each note is none."""

    marks: set[str] = set()
    notes: set[str] = set()
    for source in sorted((ROOT / "src/compiler/btrc").rglob("*.btrc")):
        for kind, _, text in TIMER_CALL.findall(source.read_text()):
            (marks if kind == "mark" else notes).add(INTERPOLATION.sub("7", text))
    python_labels = set()
    for source in sorted((ROOT / "src/compiler/python").rglob("*.py")):
        python_labels.update(re.findall(r'_timed\([^,]+, "([^"]+)"', source.read_text()))
    assert any("(" in mark for mark in marks) and notes and python_labels
    for mark in sorted(marks):
        name = mark.split("(", 1)[0]
        assert perf.phase_times(f"btrcc timing: {mark}=3us") == {name: 0.000003}, mark
    for label in sorted(python_labels):
        assert perf.phase_times(f"btrcpy timing: {label}=3us") == {label: 0.000003}, label
    for note in sorted(notes):
        assert perf.phase_times(f"btrcc timing: {note}") == {}, note


def test_worker_phase_times_reads_worker_lines_and_owner_sums_skip_them():
    owner = "btrcc timing: lex=1000us u-lowered=4000us module-unit-workers=2"
    stderr = "\n".join(
        (
            owner,
            "btrcc worker timing: worker=0 pid=11 requests=lower:2,setjmp:0,realtime:0,finish:2 "
            "busy=lower:3000us,setjmp:0us,realtime:0us,finish:500us w-wait=10us l-setup=100us l-setup=50us",
            "btrcpy worker timing: worker=1 pid=12 requests=lower:1,setjmp:1,realtime:0,finish:1 "
            "busy=lower:2000us,setjmp:5us,realtime:0us,finish:7us w-wait=20us",
        )
    )
    assert perf.phase_times(stderr) == perf.phase_times(owner) == {"lex": 0.001, "u-lowered": 0.004}
    workers = perf.worker_phase_times(stderr)
    assert sorted(workers) == [0, 1]
    assert workers[0]["l-setup"] == pytest.approx(0.00015)
    assert workers[0]["w-wait"] == pytest.approx(0.00001)
    assert workers[0]["busy:lower"] == pytest.approx(0.003)
    assert workers[1]["busy:finish"] == pytest.approx(0.000007)
    assert "pid" not in workers[0] and "requests" not in workers[0]
    assert perf.worker_phase_times(owner) == {}


def test_worker_usage_reads_reaped_usage_and_phase_sums_skip_it():
    owner = "btrcc timing: lex=1000us module-unit-workers=2"
    stderr = "\n".join(
        (
            owner,
            "btrcc worker timing: worker=0 pid=11 requests=lower:1,setjmp:0,realtime:0,finish:1 "
            "busy=lower:3000us,setjmp:0us,realtime:0us,finish:500us w-wait=10us "
            "usage=user:2500000us,sys:125000us,maxrss:204800KiB",
            "btrcpy worker timing: worker=1 pid=12 requests=lower:1,setjmp:0,realtime:0,finish:1 "
            "busy=lower:2000us,setjmp:0us,realtime:0us,finish:7us w-wait=20us",
        )
    )
    assert perf.worker_usage(stderr) == {0: {"user": 2.5, "sys": 0.125, "maxrss_kib": 204800.0}}
    workers = perf.worker_phase_times(stderr)
    assert not any(name.startswith("usage") or name in {"user", "sys", "maxrss"} for name in workers[0])
    assert (
        workers[0]
        == perf.worker_phase_times(stderr.replace(" usage=user:2500000us,sys:125000us,maxrss:204800KiB", ""))[0]
    )
    assert perf.phase_times(stderr) == perf.phase_times(owner)
    assert perf.worker_usage(owner) == {}


@pytest.mark.parametrize("platform,raw", [("darwin", 32 * 1024 * 1024), ("linux", 32 * 1024)])
def test_measurement_normalizes_peak_rss(platform, raw):
    measured = perf.Measurement.from_usage({"wall_s": 1.0, "cpu_s": 0.8, "max_rss": raw, "returncode": 0}, platform)
    assert measured.max_rss_kb == 32 * 1024


def test_selfhost_sequential_marks_belong_to_their_stage():
    run = perf.CompilerRun(
        "btrcc",
        30.0,
        29.0,
        1024,
        {
            "lex": 1.0,
            "r-graph": 2.0,
            "a-register": 3.0,
            "analyze": 0.1,
            "l-setup": 4.0,
            "lower": 0.2,
            "setjmp-analysis": 0.3,
            "o-setjmp": 5.0,
            "optimize": 0.4,
            "emit": 6.0,
            "new-phase": 0.5,
        },
        "program.c",
        "program.link.json",
    )
    assert run.phase_totals() == pytest.approx(
        {
            "frontend": 3.0,
            "analyze": 3.1,
            "lower": 4.2,
            "optimize": 5.7,
            "emit": 6.0,
            "other": 0.5,
            "unattributed": 7.5,
        }
    )


def test_reference_phase_totals_do_not_invent_frontend_work():
    run = perf.CompilerRun("btrcpy", 10.0, 9.0, 1024, {"lex": 1.0, "analyze": 2.0, "lower": 3.0}, "p.c", "p.json")
    totals = run.phase_totals()
    assert totals["frontend"] == 1.0
    assert totals["unattributed"] == 4.0
    assert sum(totals.values()) == run.wall_s


def test_c_stats_counts_definitions(tmp_path):
    source = tmp_path / "unit.c"
    source.write_text(
        '#line 3 "x.btrc"\ntypedef struct btrc_Vector_int btrc_Vector_int;\nstruct A {\n};\nint f(void) {\n}\nstatic int g(int a) {\n}\n'
    )
    stats = perf.CStats.read(source)
    assert (stats.lines, stats.functions, stats.structs, stats.vector_instances, stats.line_directives) == (
        8,
        2,
        1,
        1,
        1,
    )


@pytest.mark.skipif(default_toolchain() is None, reason="needs a C and C++ toolchain")
def test_reference_compiler_measurement(tmp_path):
    report = tmp_path / "report.json"
    code = perf.main(
        [
            str(ROOT / "src/tests/basics/Hello.btrc")
            if (ROOT / "src/tests/basics/Hello.btrc").exists()
            else str(next((ROOT / "src/tests/basics").glob("*.btrc"))),
            "--frontends",
            "btrcpy",
            "--opt",
            "O0",
            "--cc",
            default_c_compiler(),
            "--cxx",
            default_cxx_compiler(),
            "--out",
            str(tmp_path / "work"),
            "--json",
            str(report),
        ]
    )
    assert code == 0
    data = json.loads(report.read_text())
    assert data["compilers"][0]["frontend"] == "btrcpy"
    assert data["compilers"][0]["phases_s"]["lower"] >= 0.0
    assert data["schema"] == 2
    target = perf.PackageTarget.parse(None)
    assert data["target"] == f"{target.operating_system}-{target.architecture}"
    assert data["provenance"]["input_stability"] == {"changed": [], "unchanged": True}
    cold, warm = data["native_builds"]
    assert cold["operations"]["optimization"] == 0
    assert cold["operations"]["executable_bytes"] > 0
    assert cold["operations"]["compiled_units"] >= 1
    assert warm["operations"]["compiled_units"] == 0
    assert warm["operations"]["reused_units"] == cold["operations"]["compiled_units"]
    assert warm["end_to_end_s"] is None
    assert data["provenance"]["compiler_sources"]["files"] > 0
    assert data["provenance"]["compiler_repository"]["revision"]
    assert data["provenance"]["rss_unit"] == "KiB"
    assert sys.executable


@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
def test_complete_build_measurement_includes_every_unit_and_mode(tmp_path, request, frontend, capsys):
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples/native-package", project, ignore=shutil.ignore_patterns("build", ".btrc-cache"))
    path = tmp_path / "report.json"
    options = [
        str(project / "src/Main.btrc"),
        "--frontends",
        frontend,
        "--unit-lines",
        "1",
        "--jobs",
        "2",
        "--out",
        str(tmp_path / "results"),
        "--json",
        str(path),
    ]
    if frontend == "btrcc":
        options.extend(["--btrcc", str(request.getfixturevalue("immutable_btrcc"))])
    assert perf.main(options) == 0
    rendered = capsys.readouterr().out
    report = json.loads(path.read_text())
    assert {run["mode"] for run in report["compilers"]} == {"dev", "release"}
    assert report["provenance"]["entry_package_sources"]["files"] >= 6
    assert len(report["native_builds"]) == 4
    native_count = 4 if report["target"].startswith("macos-") else 2
    for run in report["native_builds"]:
        operations = run["operations"]
        assert operations["emitted_units"] >= 2
        assert operations["native_units"] == native_count
        assert len(operations["units"]) == operations["emitted_units"] + native_count
        if operations["link_cache_status"] in {"hit", "stored"}:
            assert operations["links"] == (2 if run["scenario"] == "cold" else 0)
        else:
            assert operations["links"] == 1
        scenario = "cold build" if run["scenario"] == "cold" else "warm native only"
        prefix = f"| {run['frontend']} / {run['mode']} | {scenario} |"
        row = next(line for line in rendered.splitlines() if line.startswith(prefix))
        assert row.split("|")[-2].strip() == str(operations["links"])
        assert operations["debug_info"] == (run["mode"] == "dev")
        assert operations["optimization"] == (0 if run["mode"] == "dev" else 2)
        for unit in operations["units"]:
            assert "-Werror" in unit["command"] and "-w" not in unit["command"]
            assert unit["dependency_scan_s"] >= 0.0 and unit["cache_validation_s"] >= 0.0
        if run["scenario"] == "cold":
            assert operations["compiled_units"] == len(operations["units"])
            assert operations["cache_misses"] == {"missing-entry": len(operations["units"])}
            assert run["end_to_end_s"] >= run["measurement"]["wall_s"]
        else:
            assert operations["compiled_units"] == 0
            assert operations["reused_units"] == len(operations["units"])
        result = subprocess.run([run["executable"]], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT)
        assert result.stdout == "PASS: native package graph\n"


def test_failed_frontend_retains_measurement_and_logs(tmp_path):
    source = tmp_path / "Broken.btrc"
    source.write_text("int main( {\n")
    path = tmp_path / "report.json"
    assert (
        perf.main(
            [
                str(source),
                "--frontends",
                "btrcpy",
                "--modes",
                "dev",
                "--out",
                str(tmp_path / "runs"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert report["failure"]
    assert report["compilers"][0]["returncode"] != 0
    assert report["native_builds"] == []
    directory = Path(report["provenance"]["work_directory"])
    assert (directory / "btrcpy-dev-1/frontend.stderr").stat().st_size > 0


@pytest.mark.parametrize(
    "option,value",
    [
        ("--frontends", "typo"),
        ("--frontends", ""),
        ("--modes", "dev,dev"),
        ("--modes", ""),
        ("--samples", "0"),
        ("--jobs", "0"),
        ("--opt", "O5"),
        ("--opt", ""),
        ("--target", "unknown-x64"),
    ],
)
def test_measurement_rejects_invalid_matrix_before_build(tmp_path, option, value):
    with pytest.raises(SystemExit) as error:
        perf.main([str(tmp_path / "Absent.btrc"), option, value])
    assert error.value.code == 2


def test_failed_link_retains_native_measurement_and_logs(tmp_path):
    source = tmp_path / "Unresolved.btrc"
    source.write_text("extern int missing_native_symbol();\nint main() { return missing_native_symbol(); }\n")
    path = tmp_path / "report.json"
    assert (
        perf.main(
            [
                str(source),
                "--frontends",
                "btrcpy",
                "--modes",
                "dev",
                "--out",
                str(tmp_path / "runs"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert report["compilers"][0]["returncode"] == 0
    assert report["native_builds"][0]["measurement"]["returncode"] != 0
    assert report["native_builds"][0]["operations"] == {}
    directory = Path(report["provenance"]["work_directory"])
    assert "missing_native_symbol" in (directory / "btrcpy-dev-1/cold.stderr").read_text()


def test_measurement_rejects_inputs_changed_during_build(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples/native-package", project, ignore=shutil.ignore_patterns("build", ".btrc-cache"))
    original = perf.Perf.run_native

    def build_then_edit(self, run, directory, scenario, started):
        original(self, run, directory, scenario, started)
        with (project / "packages/leaf/src/Api.btrc").open("a") as stream:
            stream.write("\n// concurrent source edit\n")

    monkeypatch.setattr(perf.Perf, "run_native", build_then_edit)
    path = tmp_path / "report.json"
    assert (
        perf.main(
            [
                str(project / "src/Main.btrc"),
                "--frontends",
                "btrcpy",
                "--modes",
                "dev",
                "--warm-native-runs",
                "0",
                "--out",
                str(project / "results"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert "inputs changed" in report["failure"]
    assert report["provenance"]["input_stability"] == {"changed": ["entry_package_sources"], "unchanged": False}
    assert report["native_builds"][0]["measurement"]["returncode"] == 0


@pytest.mark.parametrize("alias", [False, True])
def test_report_cannot_replace_program(tmp_path, alias):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    report = tmp_path / "report.json" if alias else source
    if alias:
        report.hardlink_to(source)
    with pytest.raises(SystemExit) as error:
        perf.main([str(source), "--json", str(report)])
    assert error.value.code == 2
    assert source.read_text() == "int main() { return 0; }\n"


# -- --cprofile: reference-compiler attribution ---------------------------------------------


def test_owner_rules_cover_every_reference_compiler_file():
    """No reference-compiler source falls through to the driver by accident."""

    files = sorted(path for path in perf.COMPILER_ROOT.rglob("*.py") if "__pycache__" not in path.parts)
    assert files
    for path in files:
        relative = path.relative_to(perf.COMPILER_ROOT).as_posix()
        assert perf.ProfileAttribution.owner_rule(relative, None) is not None, relative
    assert {rule[0] for rule in perf.OWNER_RULES} | {"startup"} == set(perf.OWNERS)
    assert set(perf.OWNER_PHASE_GROUPS) == {*perf.OWNERS, perf.UNATTRIBUTED}
    assert set(perf.OWNER_PHASE_GROUPS.values()) <= set(perf.PHASE_GROUPS)
    assert perf.ProfileAttribution.owner_rule("frontend/packages.py", "NativeLinkPlan")[0] == "native-plan"
    assert perf.ProfileAttribution.owner_rule("frontend/packages.py", "PackageUniverse")[0] == "frontend"
    assert perf.ProfileAttribution.owner_rule("ir/optimizer.py", "IROptimizer")[0] == "optimizer"
    assert perf.ProfileAttribution.owner_rule("ir/lowering/calls.py", None)[0] == "lowering"
    assert perf.ProfileAttribution.owner_rule("application/modules.py", None)[0] == "module-units"
    assert perf.ProfileAttribution.owner_rule("mainly.py", None) is None


def test_class_spans_name_the_innermost_owner_class(tmp_path):
    source = tmp_path / "owners.py"
    source.write_text(
        "def loose():\n"  # 1
        "    return 1\n"  # 2
        "\n"  # 3
        "@decorated\n"  # 4
        "class Outer:\n"  # 5
        "    def method(self):\n"  # 6
        "        return [x for x in ()]\n"  # 7
        "\n"  # 8
        "    class Inner:\n"  # 9
        "        def method(self):\n"  # 10
        "            return 2\n"  # 11
        "\n"  # 12
        "    def after(self):\n"  # 13
        "        return 3\n"  # 14
    )
    spans = perf.ClassSpans()
    assert spans.owner(source, 1) is None
    assert spans.owner(source, 4) == "Outer"
    assert spans.owner(source, 7) == "Outer"
    assert spans.owner(source, 10) == "Outer.Inner"
    assert spans.owner(source, 13) == "Outer"
    assert spans.owner(tmp_path / "absent.py", 1) is None


def test_profile_attribution_partitions_time_among_owners(tmp_path):
    """Own time splits by each caller's own time in it; inherited time by cumulative time."""

    compiler = tmp_path / "src/compiler/python"
    (compiler / "analyzer").mkdir(parents=True)
    (compiler / "ir/lowering").mkdir(parents=True)
    (compiler / "analyzer/types.py").write_text("class TypeSystem:\n    def resolve(self):\n        pass\n")
    (compiler / "ir/lowering/calls.py").write_text("class CallLowerer:\n    def lower(self):\n        pass\n")
    analyzer = (str(compiler / "analyzer/types.py"), 2, "resolve")
    lowering = (str(compiler / "ir/lowering/calls.py"), 2, "lower")
    helper = ("/usr/lib/python3/re.py", 10, "match")
    builtin = ("~", 0, "<built-in method builtins.isinstance>")
    module = (str(compiler / "analyzer/types.py"), 1, "<module>")
    importer = ("<frozen importlib._bootstrap>", 1, "_find_and_load")
    harness = ("<string>", 1, "<module>")
    stats = {
        # (primitive calls, calls, own time, cumulative time, callers)
        harness: (1, 1, 0.5, 10.0, {}),
        analyzer: (1, 1, 2.0, 5.0, {harness: (1, 1, 2.0, 5.0)}),
        lowering: (1, 1, 1.0, 3.5, {harness: (1, 1, 1.0, 3.5)}),
        # re.match: 3 s of its own; the analyzer's calls spent 1 s in it, the lowerer's 2 s.
        helper: (5, 5, 3.0, 4.0, {analyzer: (2, 2, 1.0, 1.5), lowering: (3, 3, 2.0, 2.5)}),
        # isinstance's own second goes to its only caller, re.match, then on by cumulative time.
        builtin: (9, 9, 1.0, 1.0, {helper: (9, 9, 1.0, 1.0)}),
        importer: (1, 1, 0.25, 1.0, {harness: (1, 1, 0.25, 1.0)}),
        module: (1, 1, 0.25, 0.25, {importer: (1, 1, 0.25, 0.25)}),
    }
    attribution = perf.ProfileAttribution(stats, root=tmp_path, compiler=compiler)
    rollup = attribution.rollup(top=10)
    owners = rollup["owners_s"]
    assert rollup["profile_total_s"] == pytest.approx(8.0)
    assert sum(owners.values()) == pytest.approx(8.0)
    assert owners["analyzer"] == pytest.approx(2.0 + 1.0 + 1.0 * 1.5 / 4.0)
    assert owners["lowering"] == pytest.approx(1.0 + 2.0 + 1.0 * 2.5 / 4.0)
    assert owners["startup"] == pytest.approx(0.5)
    assert owners["unattributed"] == pytest.approx(0.5)
    assert {row["class"] for row in rollup["classes"]} == {
        "src/compiler/python/analyzer/types.py:TypeSystem",
        "src/compiler/python/ir/lowering/calls.py:CallLowerer",
    }
    # A module's import time is startup's; the time its functions run is its owner's.
    modules = {(row["owner"], row["module"]): row["seconds"] for row in rollup["modules"]}
    assert modules[("startup", "src/compiler/python/analyzer/types.py")] == pytest.approx(0.25)
    assert modules[("startup", "<frozen importlib._bootstrap>")] == pytest.approx(0.25)
    assert modules[("analyzer", "src/compiler/python/analyzer/types.py")] == pytest.approx(owners["analyzer"])
    heaviest = rollup["functions"][0]
    assert heaviest["owner"] == "lowering" and heaviest["owner_class"] == "CallLowerer"
    assert heaviest["self_s"] == 1.0 and heaviest["calls"] == 1


def test_profile_attribution_survives_recursion_and_untimed_edges(tmp_path):
    compiler = tmp_path / "src/compiler/python"
    (compiler / "backend").mkdir(parents=True)
    (compiler / "backend/c_emitter.py").write_text("class CEmitter:\n    def emit(self):\n        pass\n")
    emitter = (str(compiler / "backend/c_emitter.py"), 2, "emit")
    walk = ("/usr/lib/python3/ast.py", 5, "walk")
    fast = ("~", 0, "<built-in method builtins.len>")
    stats = {
        emitter: (1, 1, 1.0, 3.0, {}),
        # walk recurses into itself; only the emitter is a real caller.
        walk: (1, 50, 2.0, 2.0, {emitter: (1, 1, 0.5, 2.0), walk: (0, 49, 1.5, 1.5)}),
        # Too fast for the clock on every edge: split by call count.
        fast: (4, 4, 0.0004, 0.0004, {walk: (3, 3, 0.0, 0.0), emitter: (1, 1, 0.0, 0.0)}),
    }
    owners = perf.ProfileAttribution(stats, root=tmp_path, compiler=compiler).rollup()["owners_s"]
    assert owners["emitter"] == pytest.approx(3.0004)
    assert owners["unattributed"] == pytest.approx(0.0)


def test_profile_attribution_reads_a_real_reference_profile(tmp_path):
    """A cProfile of the reference lexer lands on the frontend, its imports on startup."""

    script = tmp_path / "lex.py"
    script.write_text(
        "from src.compiler.python.lexer.lexer import Lexer\n"
        "for _ in range(20):\n"
        "    Lexer('int main() { return 1 + 2; }\\n', 'Main.btrc').tokenize()\n"
    )
    profile = tmp_path / "lex.prof"
    subprocess.run(
        [sys.executable, "-P", "-m", "cProfile", "-o", str(profile), str(script)],
        cwd=tmp_path,
        env={**perf.os.environ, "PYTHONPATH": str(ROOT)},
        check=True,
        capture_output=True,
        timeout=RUN_TIMEOUT,
    )
    rollup = perf.ProfileAttribution.load([profile]).rollup()
    owners = rollup["owners_s"]
    assert owners["frontend"] > 0.0 and owners["startup"] > 0.0
    assert sum(owners.values()) == pytest.approx(rollup["profile_total_s"])
    assert any(row["class"] == "src/compiler/python/lexer/lexer.py:Lexer" for row in rollup["classes"])


def test_reference_attribution_groups_phases_and_their_remainder():
    phases = {
        "resolve_includes": 0.5,
        "lex": 0.25,
        "analyze": 1.0,
        "lower": 2.0,
        "setjmp-analysis": 0.5,
        "optimize": 0.25,
        "emit": 0.125,
        "artifact-hit": 0.0625,
    }
    groups = perf.ReferenceAttribution.grouped_phases(phases, 6.0)
    assert groups == pytest.approx(
        {"frontend": 0.75, "analyze": 1.0, "lower": 2.0, "optimize": 0.75, "emit": 0.125, "outside": 1.375}
    )
    assert sum(groups.values()) == pytest.approx(6.0)


@pytest.mark.parametrize(
    "options",
    [
        ["--cprofile"],
        ["--cprofile", "--stand-in", "--workspace", "."],
        ["--cprofile", "--stand-in", "--edits", "typo"],
        ["--cprofile", "--stand-in", "--edits", "navigation,navigation"],
        ["--cprofile", "--stand-in", "--cold-samples", "0", "--edits", "none"],
        ["--cprofile", "--stand-in", "--cold-samples", "-1"],
        ["--cprofile", "--stand-in", "--edit-samples", "0"],
        ["--cprofile", "--stand-in", "--min-attributed", "1.5"],
        ["--cprofile", "--stand-in", "--frontend", "selfhost"],
        ["--cprofile", "--stand-in", "--target", "unknown-x64"],
        ["--cprofile", "--workspace", "/nonexistent/btrsmith"],
        ["--cprofile", "--workspace", "."],
        ["--cprofile", "--stand-in", "--jobs", "0"],
    ],
)
def test_cprofile_rejects_invalid_options_before_building(options):
    with pytest.raises(SystemExit) as error:
        perf.main(options)
    assert error.value.code == 2


def test_cprofile_dry_run_takes_one_sample_and_resolves_defaults():
    arguments = perf.ReferenceAttribution.parse_arguments(
        ["--cprofile", "--stand-in", "--mode", "release", "--cold-samples", "4", "--edit-samples", "6", "--dry-run"]
    )
    assert (arguments.cold_samples, arguments.edit_samples, arguments.units) == (1, 1, "whole")
    assert [fixture.name for fixture in arguments.fixtures] == [fixture.name for fixture in budget_bench.EDIT_FIXTURES]
    assert perf.ReferenceAttribution.parse_arguments(["--cprofile", "--stand-in"]).units == "module"


def test_cprofile_stand_in_attributes_the_reference_compiler(tmp_path, capsys):
    """Cold and edit builds of budget_bench's stand-in, each plain and profiled, reconcile to wall time."""

    path = tmp_path / "attribution.json"
    code = perf.main(
        [
            "--cprofile",
            "--frontend",
            "reference",
            "--stand-in",
            "--cold-samples",
            "1",
            "--edits",
            "navigation",
            "--edit-samples",
            "1",
            "--min-attributed",
            "0.5",
            "--timeout-s",
            str(TRANSPILE_TIMEOUT),
            "--out",
            str(tmp_path / "runs"),
            "--json",
            str(path),
        ]
    )
    rendered = capsys.readouterr().out
    assert code == 0, rendered
    report = json.loads(path.read_text())
    assert report["schema"] == perf.ReferenceAttribution.SCHEMA and report["failure"] is None
    assert report["configuration"]["stand_in"] is True and report["configuration"]["jobs"] == 1
    assert list(report["scenarios"]) == ["cold", "edit-navigation"]
    work = Path(report["provenance"]["work_directory"])
    for name, scenario in report["scenarios"].items():
        (sample,) = scenario["samples"]
        assert (work / sample["profile"]).is_file()
        assert sample["plain_phases_s"]["analyze"] > 0.0 and sample["profiled_phases_s"]["lower"] > 0.0
        # Phase marks never overlap: what no mark covers is a nonnegative remainder.
        for phases, wall in (
            (sample["plain_phases_s"], sample["plain_wall_s"]),
            (sample["profiled_phases_s"], sample["profiled_wall_s"]),
        ):
            assert perf.ReferenceAttribution.grouped_phases(phases, wall)["outside"] >= 0.0
        owners = scenario["attribution"]["owners_s"]
        assert sum(owners.values()) == pytest.approx(scenario["profile_total_s"])
        assert owners["analyzer"] > 0.0 and owners["frontend"] > 0.0 and owners["startup"] > 0.0
        assert scenario["profile_total_s"] <= scenario["profiled_wall_total_s"]
        assert scenario["attributed_fraction"] == pytest.approx(
            scenario["attributed_s"] / scenario["profiled_wall_total_s"]
        )
        assert scenario["attributed_fraction"] >= 0.5, name
        assert 0.0 < scenario["compiler_fraction"] < scenario["attributed_fraction"]
        reconciliation = scenario["reconciliation"]
        assert list(reconciliation) == list(perf.PHASE_GROUPS)
        assert sum(row["plain_phase_s"] for row in reconciliation.values()) == pytest.approx(
            scenario["plain_wall_total_s"]
        )
        assert sum(row["owner_s"] for row in reconciliation.values()) == pytest.approx(
            scenario["profiled_wall_total_s"]
        )
        assert scenario["attribution"]["classes"] and scenario["attribution"]["functions"]
        assert f"| {name} | 1 |" in rendered
    edited = (work / "ws" / budget_bench.EDIT_FIXTURES[0].module).read_text()
    assert budget_bench.EDIT_FIXTURES[0].render(2) in edited
    assert report["summary"]["meets_minimum"] is True
    assert set(report["summary"]["scenario_fractions"]) == {"cold", "edit-navigation"}


def test_cprofile_below_min_attributed_fails_with_the_report(tmp_path, monkeypatch):
    def summarize(self):
        self.report["summary"] = {"attributed_fraction": 0.5, "minimum_fraction": 0.4, "meets_minimum": False}

    monkeypatch.setattr(perf.ReferenceAttribution, "cold", lambda self: None)
    monkeypatch.setattr(perf.ReferenceAttribution, "edits", lambda self: None)
    monkeypatch.setattr(perf.ReferenceAttribution, "summarize", summarize)
    path = tmp_path / "attribution.json"
    assert (
        perf.main(["--cprofile", "--stand-in", "--min-attributed", "0.9", "--out", str(tmp_path), "--json", str(path)])
        == 1
    )
    report = json.loads(path.read_text())
    assert "below --min-attributed 90%" in report["failure"]


def test_cprofile_runner_keeps_a_failed_compile_s_exit_status(tmp_path):
    """`python -m cProfile` would exit 0 here; the runner exits as the compiler does, profile written."""

    source = tmp_path / "Broken.btrc"
    source.write_text("int main( {\n")
    profile = tmp_path / "broken.prof"
    completed = subprocess.run(
        [
            sys.executable,
            "-P",
            "-c",
            perf.ReferenceAttribution.PROFILER,
            str(profile),
            str(source),
            "-o",
            str(tmp_path / "broken.c"),
        ],
        cwd=tmp_path,
        env={**perf.os.environ, "PYTHONPATH": str(ROOT), "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert completed.returncode != 0, completed.stderr
    assert profile.is_file()
    good = tmp_path / "Good.btrc"
    good.write_text("int main() { return 0; }\n")
    completed = subprocess.run(
        [
            sys.executable,
            "-P",
            "-c",
            perf.ReferenceAttribution.PROFILER,
            str(profile),
            str(good),
            "-o",
            str(tmp_path / "good.c"),
        ],
        cwd=tmp_path,
        env={**perf.os.environ, "PYTHONPATH": str(ROOT), "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "good.c").is_file()
    assert perf.ProfileAttribution.load([profile]).rollup()["owners_s"]["emitter"] > 0.0


def test_cprofile_rejects_out_inside_the_copied_workspace(tmp_path):
    workspace = tmp_path / "product"
    (workspace / "src").mkdir(parents=True)
    (workspace / budget_bench.ENTRY).write_text("int main() { return 0; }\n")
    for out in (workspace, workspace / "results"):
        with pytest.raises(SystemExit) as error:
            perf.main(["--cprofile", "--workspace", str(workspace), "--out", str(out)])
        assert error.value.code == 2
    arguments = perf.ReferenceAttribution.parse_arguments(
        ["--cprofile", "--workspace", str(workspace), "--out", str(workspace / "build/attribution")]
    )
    assert arguments.jobs == 1


def test_cprofile_failed_compile_keeps_its_log(tmp_path):
    workspace = tmp_path / "product"
    (workspace / "src").mkdir(parents=True)
    (workspace / budget_bench.ENTRY).write_text("int main( {\n")
    path = tmp_path / "attribution.json"
    assert (
        perf.main(
            [
                "--cprofile",
                "--workspace",
                str(workspace),
                "--edits",
                "none",
                "--cold-samples",
                "1",
                "--timeout-s",
                str(TRANSPILE_TIMEOUT),
                "--out",
                str(tmp_path / "runs"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert "reference compile cold-1-plain failed" in report["failure"]
    work = Path(report["provenance"]["work_directory"])
    assert (work / "logs/cold-1-plain.stderr").stat().st_size > 0
    assert (workspace / budget_bench.ENTRY).read_text() == "int main( {\n"


# -- the stage6-reference runbook preset -----------------------------------------------------


def test_stage6_reference_preset_expands_to_valid_perf_commands(tmp_path, monkeypatch):
    from tools.runbook.engine import Host, Preset, RunbookEngine, RunOptions

    monkeypatch.setenv("BTRC_LOCK_DIR", str(tmp_path / "locks"))
    preset = Preset.load("stage6-reference")
    assert preset.packet == "MAC-R-03" and preset.kind == "measurement"
    for stand_in, extra in ((False, []), (True, ["--rehearsal", "--stand-in", "--dry-run"])):
        options = RunOptions.parse(["stage6-reference", "--home", str(tmp_path / "home"), *extra])
        engine = RunbookEngine(preset, options, host=Host("Darwin" if not stand_in else "Linux"))
        engine.frozen = {"shas": {"btrc": "0" * 40, "btrsmith": {"post-stage4": "1" * 40}}}
        state = engine.new_state()
        cells = {cell.id: cell for cell in engine.cells}
        assert set(cells) == {"reference-cold-dev", "reference-cold-release", "reference-edits"}
        for cell in cells.values():
            assert cell.lock == "bench" and cell.quiet and cell.shell == "btrsmith"
            command = engine.expand_command(cell.command, engine.context(cell, state))
            assert command[:5] == ["python3", "-m", "tools.perf", "--cprofile", "--frontend"]
            assert ("--stand-in" in command) == stand_in and ("--workspace" in command) != stand_in
            assert ("--dry-run" in command) == stand_in
            assert command[command.index("--min-attributed") + 1] == "0.90"
            workspace = command.index("--workspace") + 1 if not stand_in else None
            if workspace is not None:
                (tmp_path / "pin/src").mkdir(parents=True, exist_ok=True)
                (tmp_path / "pin" / budget_bench.ENTRY).write_text("int main() { return 0; }\n")
                command[workspace] = str(tmp_path / "pin")
            arguments = perf.ReferenceAttribution.parse_arguments(command[3:])
            assert arguments.min_attributed == 0.9
            assert Path(arguments.json) == state.cell_out(cell.id) / "attribution.json"
            if cell.id == "reference-edits":
                assert arguments.cold_samples == 0 and len(arguments.fixtures) == len(budget_bench.EDIT_FIXTURES)
                assert arguments.edit_samples == (1 if stand_in else 5)
            else:
                assert arguments.fixtures == () and arguments.cold_samples == (1 if stand_in else 3)
                assert arguments.mode == cell.variables["mode"]
