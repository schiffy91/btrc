"""The CI tier manifest, the plans it gives each workflow, and the release ledger bundle."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tools.qualification.bundle import BUNDLE_SCHEMA, LedgerBundle, ToolsBenchAdapter
from tools.qualification.cli import QualificationCommand
from tools.qualification.schema import EvidenceStatus, LedgerDocument, Platform, SubjectKind
from tools.qualification.tiers import MANIFEST, GitHubPaths, TierManifest, TierManifestError

REPO = Path(__file__).resolve().parents[3]


def _manifest() -> TierManifest:
    return TierManifest.load(MANIFEST)


def _rows(plan: dict, job: str) -> dict[str, dict[str, str]]:
    matrix = plan["matrix"].get(job, {"include": []})
    key = {"native-bundle": "target", "linux-gui": "session"}.get(job, "shard")
    return {row[key]: row for row in matrix["include"]}


# ----------------------------------------------------------------- manifest


def test_the_tracked_manifest_loads_and_describes_every_tier() -> None:
    manifest = _manifest()
    assert list(manifest.tiers) == ["docs", "pr", "lane", "main", "extended", "release", "native-gui", "hardware"]
    assert manifest.workflows() == ["ci.yml", "macos.yml", "windows.yml"]
    assert {runner.runner for runner in manifest.hardware} == {"macos", "linux", "ios", "android"}


def _minimal(**overrides: object) -> dict:
    data = {
        "schema": "btrc.ci-tiers/1",
        "tiers": {"pr": "a pull request", "main": "main", "hardware": "devices"},
        "jobs": [{"workflow": "ci.yml", "job": "tests", "key": "shard", "reports": ["skip-report"]}],
        "shards": [{"job": "ci.yml/tests", "shard": "unit", "target": "test-shard-unit", "tiers": ["pr", "main"]}],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "btrc.ci-tiers/0"}, "schema"),
        ({"tiers": {"pr": "x", "main": "y"}}, "hardware"),
        ({"jobs": [{"workflow": "ci.yml", "job": "tests", "key": "shard", "tiers": ["pr"]}]}, "come from its shards"),
        ({"jobs": [{"workflow": "ci.yml", "job": "static"}]}, "needs tiers"),
        ({"jobs": [{"workflow": "ci.yml", "job": "static", "tiers": ["nightly"]}]}, "unknown nightly"),
        ({"jobs": [{"workflow": "ci.yml", "job": "static", "tiers": ["hardware"]}]}, "unknown hardware"),
        ({"jobs": [{"workflow": "ci.yml", "job": "s", "tiers": ["pr"], "reports": ["coverage"]}]}, "unknown coverage"),
        ({"jobs": [{"workflow": "ci.yml", "job": "s", "tiers": ["pr"], "changed_tiers": ["main"]}]}, "go together"),
        (
            {
                "jobs": [
                    {"workflow": "ci.yml", "job": "s", "tiers": ["pr"], "changed_tiers": ["pr"], "changed_paths": ["a"]}
                ]
            },
            "both unconditional and changed",
        ),
        ({"jobs": [{"workflow": "ci.yml", "job": "s", "tiers": ["pr"], "typo": 1}]}, "unknown field"),
        ({"shards": [{"job": "ci.yml/other", "shard": "unit", "tiers": ["pr"]}]}, "not a matrix job"),
        ({"shards": [{"job": "ci.yml/tests", "target": "x", "tiers": ["pr"]}]}, "has no 'shard'"),
        ({"shards": [{"job": "ci.yml/tests", "shard": "unit"}]}, "runs in no tier"),
        ({"shards": [{"job": "ci.yml/tests", "shard": "a; rm -rf /", "tiers": ["pr"]}]}, "plain text value"),
        ({"shards": [{"job": "ci.yml/tests", "shard": "u", "tiers": ["pr"], "pytest_addopts": "fast"}]}, "computed"),
        ({"shards": []}, "has no shards"),
        (
            {
                "shards": [
                    {"job": "ci.yml/tests", "shard": "unit", "tiers": ["pr"]},
                    {"job": "ci.yml/tests", "shard": "unit", "tiers": ["main"]},
                ]
            },
            "two shard 'unit' rows",
        ),
        ({"corpus": [{"paths": ["src/**"], "directories": ["Strings"]}]}, "corpus directory names"),
        ({"corpus": [{"paths": ["src/?.py"], "directories": ["stdlib"]}]}, "only \\*, \\*\\* and a leading !"),
        ({"paths": {"lane-linux": ["src/**"]}}, "no entry selects with \\[paths\\] lane-linux"),
        ({"paths": {"Lane": ["src/**"]}}, "lowercase name"),
        ({"paths": {"lane-linux": ["!src/**"]}}, "starts with a pattern that selects"),
        ({"paths": {"lane-linux": []}}, "starts with a pattern that selects"),
        ({"paths": {"lane-linux": ["src/[a].py"]}}, "only \\*, \\*\\* and a leading !"),
        ({"paths": ["src/**"]}, "maps a path-set name"),
        (
            {"shards": [{"job": "ci.yml/tests", "shard": "unit", "tiers": ["main"], "selected_tiers": {"pr": "x"}}]},
            "no \\[paths\\] set x",
        ),
        (
            {
                "paths": {"x": ["src/**"]},
                "shards": [{"job": "ci.yml/tests", "shard": "unit", "selected_tiers": {"nightly": "x"}}],
            },
            "unknown nightly",
        ),
        (
            {
                "paths": {"x": ["src/**"]},
                "shards": [{"job": "ci.yml/tests", "shard": "unit", "tiers": ["pr"], "selected_tiers": {"pr": "x"}}],
            },
            "both selected and listed",
        ),
        (
            {
                "paths": {"x": ["src/**"]},
                "shards": [
                    {"job": "ci.yml/tests", "shard": "unit", "corpus_tiers": ["pr"], "selected_tiers": {"pr": "x"}}
                ],
            },
            "both selected and listed",
        ),
        (
            {"shards": [{"job": "ci.yml/tests", "shard": "unit", "tiers": ["pr"], "selected_tiers": ["pr"]}]},
            "maps a tier to a \\[paths\\] set name",
        ),
    ],
)
def test_a_malformed_manifest_is_refused_with_its_reason(change: dict, message: str) -> None:
    with pytest.raises(TierManifestError, match=message):
        TierManifest.from_mapping(_minimal(**change), REPO)


def test_github_paths_follow_the_filter_pattern_rules() -> None:
    assert GitHubPaths.selects(["**/MacOS/**"], "src/stdlib/GUI/MacOS/Window.btrc")
    assert GitHubPaths.selects(["**/MacOS/**"], "MacOS/x")
    assert not GitHubPaths.selects(["src/*.btrc"], "src/stdlib/Vector.btrc")
    assert GitHubPaths.selects(["src/**", "!src/stdlib/**"], "src/compiler/x.py")
    assert not GitHubPaths.selects(["src/**", "!src/stdlib/**"], "src/stdlib/Vector.btrc")
    assert GitHubPaths.selects(["src/tests/native/win_compat*"], "src/tests/native/win_compat_main.c")


# -------------------------------------------------------------------- plans


def test_the_main_tier_is_the_full_matrix_and_extended_and_release_contain_it() -> None:
    manifest = _manifest()
    for workflow in manifest.workflows():
        main = manifest.plan(workflow, "main")
        for wider in ("extended", "release"):
            plan = manifest.plan(workflow, wider)
            assert set(main["jobs"]) <= set(plan["jobs"]), (workflow, wider)
            for job, matrix in main["matrix"].items():
                assert all(row in plan["matrix"][job]["include"] for row in matrix["include"]), (workflow, wider, job)
    ci = manifest.plan("ci.yml", "main")
    assert ci["jobs"] == ["release", "tests", "bench", "linux-arm64-bundle", "linux-gui"]
    assert len(ci["matrix"]["tests"]["include"]) == 13
    assert list(_rows(ci, "linux-gui")) == ["x11", "wayland"]
    macos = manifest.plan("macos.yml", "main")
    assert list(_rows(macos, "tests")) == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        "c11-clang-O0",
        "c11-clang-O2",
    ]
    assert list(_rows(macos, "native-bundle")) == ["macos-arm64", "macos-x64"]
    assert manifest.plan("windows.yml", "main")["jobs"] == ["windows", "bootstrap"]
    extended = manifest.plan("macos.yml", "extended")
    assert [name for name in _rows(extended, "tests") if name.startswith("c11-")] == [
        f"c11-clang-O{level}" for level in range(4)
    ]


def test_the_release_tier_runs_every_job_any_scheduled_tier_runs() -> None:
    manifest = _manifest()
    for workflow in manifest.workflows():
        release = manifest.plan(workflow, "release")
        for tier in manifest.scheduled_tiers():
            plan = manifest.plan(workflow, tier)
            assert set(plan["jobs"]) <= set(release["jobs"]), (workflow, tier)
            for job in plan["matrix"]:
                assert set(_rows(plan, job)) <= set(_rows(release, job)), (workflow, tier, job)
    # Changed-path rows join the release tier unconditionally.
    for shard in manifest.shards:
        assert "release" in shard.condition.tiers, shard.row
    for job in manifest.jobs:
        if job.key is None:
            assert "release" in job.condition.tiers, job.reference


def test_a_docs_change_runs_only_the_static_gates() -> None:
    manifest = _manifest()
    assert manifest.plan("ci.yml", "docs", ["docs/x.md"]) == {
        "tier": "docs",
        "jobs": ["static"],
        "matrix": {},
        "reports": {"static": ["skip-report-ci-static"]},
    }
    assert manifest.plan("macos.yml", "docs", ["docs/x.md"])["jobs"] == []
    assert manifest.plan("windows.yml", "docs", ["docs/x.md"])["jobs"] == []


def test_a_pull_request_runs_the_unit_shard_and_the_corpus_its_paths_select() -> None:
    manifest = _manifest()
    tools_only = manifest.plan("ci.yml", "pr", ["tools/qualification/report.py"])
    assert tools_only["jobs"] == ["static", "tests"]
    assert list(_rows(tools_only, "tests")) == ["unit"]

    corpus = manifest.plan("ci.yml", "pr", ["src/tests/strings/expected/Foo.stdout", "src/tests/memory/Arc.btrc"])
    rows = _rows(corpus, "tests")
    assert list(rows) == ["unit", "corpus-python", "corpus-btrc"]
    expected = '-k "python-memory/ or btrc-memory/ or python-strings/ or btrc-strings/"'
    assert rows["corpus-python"] == {
        "shard": "corpus-python",
        "target": "test-shard-corpus-python",
        "pytest_addopts": expected,
    }
    assert rows["corpus-btrc"]["pytest_addopts"] == expected
    assert corpus["reports"]["tests"] == [
        "skip-report-ci-tests-unit",
        "skip-report-ci-tests-corpus-python",
        "skip-report-ci-tests-corpus-btrc",
    ]

    stdlib = _rows(manifest.plan("ci.yml", "pr", ["src/stdlib/GUI/Linux/Window.btrc"]), "tests")
    assert list(stdlib) == ["unit", "btrc", "corpus-python", "corpus-btrc"]
    assert (
        stdlib["corpus-python"]["pytest_addopts"]
        == '-k "python-imports/ or btrc-imports/ or python-stdlib/ or btrc-stdlib/"'
    )

    # A change to the corpus runner selects the whole corpus, with no -k.
    whole = _rows(manifest.plan("ci.yml", "pr", ["src/tests/runner.py"]), "tests")
    assert "pytest_addopts" not in whole["corpus-python"]
    # A non-corpus test directory selects nothing.
    assert list(_rows(manifest.plan("ci.yml", "pr", ["src/tests/python/test_x.py"]), "tests")) == ["unit"]
    # Packaging and benchmark changes bring the jobs that exercise them.
    assert manifest.plan("ci.yml", "pr", ["src/devex/lsp/server.py"])["jobs"] == ["static", "release", "tests"]
    assert manifest.plan("ci.yml", "pr", ["tools/bench/suite.py"])["jobs"] == ["static", "tests", "bench"]


def test_macos_and_windows_run_on_a_pull_request_only_when_their_paths_change() -> None:
    manifest = _manifest()
    plain = ["tools/qualification/report.py"]
    assert manifest.plan("macos.yml", "pr", plain)["jobs"] == []
    assert manifest.plan("windows.yml", "pr", plain)["jobs"] == []

    macos = manifest.plan("macos.yml", "pr", ["src/stdlib/GUI/MacOS/Window.btrc"])
    assert macos["jobs"] == ["native-bundle", "tests"]
    assert list(_rows(macos, "native-bundle")) == ["macos-arm64"]
    assert list(_rows(macos, "tests")) == ["unit"]

    windows = manifest.plan("windows.yml", "pr", ["src/stdlib/FileSystem/Windows/FileSystemProvider.btrc"])
    assert windows["jobs"] == ["windows"], "the two-hour bootstrap waits for the main tier"
    assert manifest.plan("windows.yml", "lane", ["src/devex/vscode/package.json"])["jobs"] == ["windows"]
    # A platform's expected-skip manifest is read only by that platform's skip gate.
    skips = ["src/tests/fixtures/expected-skips/macos-hosted.json"]
    assert list(_rows(manifest.plan("macos.yml", "pr", skips), "tests")) == ["unit"]
    skips = ["src/tests/fixtures/expected-skips/windows.json"]
    assert manifest.plan("windows.yml", "pr", skips)["jobs"] == ["windows"]
    # A push or dispatch has no change list: changed-path entries stay out.
    assert manifest.plan("windows.yml", "lane")["jobs"] == []


def test_a_lane_keeps_the_linux_matrix_and_the_macos_lane_jobs() -> None:
    manifest = _manifest()
    ci = manifest.plan("ci.yml", "lane", ["src/stdlib/GUI/Linux/Window.btrc"])
    # The static job runs the naming contract, which reads every tracked file.
    assert ci["jobs"] == ["static", "release", "tests", "bench", "linux-arm64-bundle", "linux-gui"]
    assert ci["matrix"] == manifest.plan("ci.yml", "main")["matrix"]
    macos = manifest.plan("macos.yml", "lane", ["src/stdlib/GUI/Linux/Window.btrc"])
    assert macos["jobs"] == ["native-bundle", "native-gui"]
    assert list(_rows(macos, "native-bundle")) == ["macos-arm64"]


LANE_LINUX = ["static", "release", "tests", "bench", "linux-arm64-bundle"]
LANE_LIGHT = ["static", "release", "tests"]
# The Linux GUI and audio shard joins when a Linux GUI, audio or native path changes.
LANE_LINUX_GUI = [*LANE_LINUX, "linux-gui"]
LANE_LIGHT_GUI = [*LANE_LIGHT, "linux-gui"]
LANE_MACOS = ["native-bundle", "native-gui"]


@pytest.mark.parametrize(
    ("changed", "linux", "macos"),
    [
        # UI catalog data, its loader and its tests: the static gates and the unit shard only.
        (
            [
                "docs/design/native-ui-catalog/families.toml",
                "docs/design/native-ui-catalog/operations/IWindow.toml",
                "tools/qualification/ui_catalog.py",
                "src/tests/python/test_ui0_catalog.py",
                "src/tests/python/test_ui0_surface.py",
            ],
            LANE_LIGHT,
            [],
        ),
        (["src/tests/python/test_ccompat_checkpoint_script.py"], LANE_LIGHT, []),
        (["tools/target_hosts/android/emulator.sh"], LANE_LIGHT, []),
        (["docs/design/native-ui-catalog.toml", "docs/design/ui0-source-amendments.toml"], LANE_LIGHT, []),
        # tools/ui is the macOS GUI harness: macOS, not the Linux heavy shards.
        (["tools/ui/codex-setup.sh"], LANE_LIGHT, LANE_MACOS),
        # ... except the headless session every Linux test shard runs inside.
        (["tools/ui/headless-session.sh"], LANE_LINUX_GUI, LANE_MACOS),
        # A btrc-shard contract imports this unit test module.
        (["src/tests/python/test_exception_codegen_contracts.py"], LANE_LINUX, []),
        (["src/tests/python/test_native_gui_target.py"], LANE_LIGHT_GUI, LANE_MACOS),
        (["src/stdlib/GUI/MacOS/Window.btrc"], LANE_LINUX, LANE_MACOS),
        (["src/tests/native/gui/shell/probes/macos/ShellProbe.m"], LANE_LINUX, LANE_MACOS),
        (["src/stdlib/Tray/Tray.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/stdlib/HTTP/Client.btrc"], LANE_LINUX, []),
        (["src/tests/python/native_ui_shell_fixtures.py"], LANE_LINUX_GUI, []),
        (["src/tests/strings/Escapes.btrc"], LANE_LINUX, []),
        (["examples/todo/Todo.btrc"], LANE_LINUX, []),
        (["tools/bench/scripts/ccompat_checkpoint.sh"], LANE_LINUX, []),
        (["tools/qualification/report.py"], LANE_LINUX, []),
        (["tools/NativeHeaderReader.cpp"], LANE_LINUX_GUI, LANE_MACOS),
        # One heavy path among light ones selects the heavy jobs.
        (["tools/ui/codex-setup.sh", "src/tests/stdlib/Json.btrc"], LANE_LINUX, LANE_MACOS),
        # No change list, or an empty one, fails safe to the whole lane selection.
        (None, LANE_LINUX_GUI, LANE_MACOS),
        ([], LANE_LINUX_GUI, LANE_MACOS),
        ([""], LANE_LINUX_GUI, LANE_MACOS),
        # A macOS provider or probe does not select the Linux GUI shard.
        (["src/stdlib/Audio/MacOS/CoreAudio.btrc"], LANE_LINUX, LANE_MACOS),
        (["src/tests/python/linux_provider_fixtures.py"], LANE_LINUX_GUI, []),
        (["nix/asound.conf"], LANE_LIGHT_GUI, []),
        (["src/tests/fixtures/expected-skips/linux-devcontainer.json"], LANE_LINUX_GUI, []),
        # Root files that configure pytest, the container or line endings reach every shard.
        (["pyproject.toml"], LANE_LINUX, []),
        (["uv.lock"], LANE_LINUX, []),
        ([".gitattributes"], LANE_LINUX, []),
        ([".dockerignore"], LANE_LINUX, []),
        # Each macOS pattern on its own, with a path no other pattern matches.
        (["MacOS/Notes.txt"], LANE_LIGHT, LANE_MACOS),
        (["docs/design/probe.m"], LANE_LIGHT, LANE_MACOS),
        (["src/stdlib/GUI/Linux/Window.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/stdlib/UI/View.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/stdlib/App/App.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/stdlib/Audio/Mixer.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/stdlib/GPU/Device.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/tests/native/gui/Shell.c"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/tests/fixtures/expected-skips/macos-hosted.json"], LANE_LINUX, LANE_MACOS),
        (["src/stdlib/Image/EncodedImage.btrc"], LANE_LINUX, []),
    ],
)
def test_a_lane_runs_the_heavy_jobs_only_when_its_paths_select_them(
    changed: list[str] | None, linux: list[str], macos: list[str]
) -> None:
    manifest = _manifest()
    ci = manifest.plan("ci.yml", "lane", changed)
    assert ci["jobs"] == linux
    rows = list(_rows(ci, "tests"))
    heavy = "bench" in linux
    assert rows == (list(_rows(manifest.plan("ci.yml", "main"), "tests")) if heavy else ["unit"])
    assert list(_rows(ci, "linux-gui")) == (["x11", "wayland"] if "linux-gui" in linux else [])
    plan = manifest.plan("macos.yml", "lane", changed)
    assert plan["jobs"] == macos
    assert list(_rows(plan, "native-bundle")) == (["macos-arm64"] if macos else [])
    # Windows keeps its own rule: only its paths, as in the pr tier, and nothing without a list.
    windows = manifest.plan("windows.yml", "lane", changed)["jobs"]
    assert windows == (["windows"] if changed == ["pyproject.toml"] else [])
    assert windows == (manifest.plan("windows.yml", "pr", changed)["jobs"] if changed is not None else [])


def test_lane_path_selection_leaves_every_other_tier_alone() -> None:
    """Only the lane tier is path-selected; the tiers that run without a change list ignore paths."""

    manifest = _manifest()
    selected = {tier for entry in (*manifest.jobs, *manifest.shards) for tier in entry.condition.selected_tiers()}
    assert selected == {"lane"}
    samples = [
        ["docs/design/native-ui-catalog/families.toml"],
        ["tools/ui/codex-setup.sh"],
        ["src/stdlib/GUI/MacOS/Window.btrc"],
        ["src/tests/python/test_native_gui_target.py"],
    ]
    for workflow in manifest.workflows():
        for tier in ("main", "extended", "release", "native-gui"):
            for changed in samples:
                assert manifest.plan(workflow, tier, changed) == manifest.plan(workflow, tier), (workflow, tier)


def test_expected_reports_name_every_artifact_a_tier_leaves() -> None:
    expected = _manifest().expected_reports("release")
    assert expected["ci.yml/static"] == ["skip-report-ci-static"]
    assert expected["ci.yml/bench"] == ["bench-results"]
    assert expected["ci.yml/native-gui"] == ["skip-report-ci-native-gui", "junit-ci-native-gui"]
    assert expected["ci.yml/linux-gui"] == [
        "skip-report-ci-linux-gui-x11",
        "junit-ci-linux-gui-x11",
        "skip-report-ci-linux-gui-wayland",
        "junit-ci-linux-gui-wayland",
    ]
    assert "boundary-report-ci-tests-bootstrap" in expected["ci.yml/tests"]
    assert "boundary-report-macos-tests-bootstrap" in expected["macos.yml/tests"]
    assert len([name for name in expected["ci.yml/tests"] if name.startswith("skip-report-")]) == 13
    assert len([name for name in expected["macos.yml/tests"] if name.startswith("skip-report-")]) == 9
    assert expected["windows.yml/windows"] == ["skip-report-windows-windows"]
    assert expected["windows.yml/bootstrap"] == ["skip-report-windows-bootstrap"]
    with pytest.raises(TierManifestError, match="no scheduled tier"):
        _manifest().plan("ci.yml", "hardware")


def test_the_tiers_command_prints_one_line_of_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    changed = tmp_path / "changed.txt"
    changed.write_text("src/tests/strings/Foo.btrc\n\n", encoding="utf-8")
    code = QualificationCommand().run(["tiers", "--workflow", "ci.yml", "--tier", "pr", "--changed", str(changed)])
    out = capsys.readouterr().out
    assert code == 0 and out.count("\n") == 1
    assert json.loads(out) == _manifest().plan("ci.yml", "pr", ["src/tests/strings/Foo.btrc"])
    assert QualificationCommand().run(["tiers"]) == 0
    assert "ci.yml main: 5 job(s), 15 matrix row(s)" in capsys.readouterr().out
    assert QualificationCommand().run(["tiers", "--workflow", "ci.yml"]) == 2
    assert QualificationCommand().run(["tiers", "--workflow", "ci.yml", "--tier", "nightly"]) == 2


# ------------------------------------------------------------------- bundle

SKIP_REPORT = {
    "schema": "btrc.skip-report/1",
    "runner": "linux-devcontainer",
    "revision": "abc1234",
    "finished_at": "2026-10-03T08:00:00+00:00",
    "tests": {"src/tests/a.py::t1": "passed", "src/tests/a.py::t2": "skipped"},
    "skips": [{"nodeid": "src/tests/a.py::t2", "reason": "needs CoreAudio", "expected": True, "covered_by": ["macos"]}],
    "counts": {"passed": 1, "skipped": 1},
}
JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
<testcase classname="src.tests.python.test_qualification_bundle" name="test_a" />
<testcase classname="src.tests.python.test_qualification_bundle" name="test_b"><failure message="no" /></testcase>
</testsuite></testsuites>
"""
BOUNDARY = {
    "schema": "btrc.boundary-check/1",
    "created_at": "2026-10-03T08:00:00+00:00",
    "total_records": 2,
    "checked_records": 1,
    "records": [
        {"id": "arith.python.c.bytes", "fixture": "arith", "capability": "python.c", "checked": True},
        {"id": "arith.observed.gcc.bytes", "fixture": "arith", "capability": "observed.gcc", "checked": False},
    ],
}
BENCH = {
    "meta": {
        "platform": "linux-x86_64",
        "revision": "abc1234",
        "cc": "gcc",
        "recorded_at": "2026-10-03T08:00:00+00:00",
    },
    "metrics": {
        "btrcc.compile.BenchHello_ms": 41.5,
        "emit.BenchHello.c_bytes": 120345,
        "btrcc.compile.BenchArc_peak": 9e6,
    },
}


def _tiny_manifest() -> TierManifest:
    return TierManifest.from_mapping(
        {
            "schema": "btrc.ci-tiers/1",
            "tiers": {"release": "everything", "hardware": "devices"},
            "jobs": [
                {"workflow": "ci.yml", "job": "tests", "key": "shard", "reports": ["skip-report"]},
                {"workflow": "ci.yml", "job": "bench", "tiers": ["release"], "reports": ["bench"]},
                {"workflow": "macos.yml", "job": "native-gui", "tiers": ["release"], "reports": ["junit"]},
            ],
            "shards": [
                {"job": "ci.yml/tests", "shard": "unit", "tiers": ["release"]},
                {"job": "ci.yml/tests", "shard": "bootstrap", "tiers": ["release"], "reports": ["boundary-report"]},
            ],
            "hardware": [{"id": "macos-acceptance", "runner": "macos", "description": "the owner's Mac"}],
        },
        REPO,
    )


def _artifacts(tmp_path: Path, *, drop: str | None = None) -> Path:
    root = tmp_path / "artifacts"
    files = {
        "skip-report-ci-tests-unit/skip-report-unit.json": json.dumps(SKIP_REPORT),
        "skip-report-ci-tests-bootstrap/skip-report-bootstrap.json": json.dumps(
            {**SKIP_REPORT, "tests": {"src/tests/b.py::t": "passed"}, "skips": []}
        ),
        "boundary-report-ci-tests-bootstrap/boundary-report.json": json.dumps(BOUNDARY),
        "bench-results/results.json": json.dumps(BENCH),
        "junit-macos-native-gui/native-gui.xml": JUNIT,
        "btrcc-linux-x64/btrcc-linux-x64.tar.gz": "not evidence",
    }
    for name, text in files.items():
        if drop is not None and name.startswith(drop):
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_a_bundle_holds_every_jobs_records_and_its_raw_inputs(tmp_path: Path) -> None:
    output = tmp_path / "ledger-bundle-abc1234"
    outcome = LedgerBundle(_artifacts(tmp_path), _tiny_manifest(), "release", "abc1234", "42").build(output)
    assert outcome.passed, outcome.problems

    records = LedgerDocument.load(output / "ledger.jsonl")
    assert outcome.records == len(records) == 2 + 1 + 2 + 3 + 2
    by_kind: dict[SubjectKind, list] = {}
    for record in records:
        by_kind.setdefault(record.subject.kind, []).append(record)
    assert len(by_kind[SubjectKind.TEST]) == 5
    assert len(by_kind[SubjectKind.BOUNDARY_RECORD]) == 2
    assert len(by_kind[SubjectKind.SCENARIO]) == 3
    junit = [record for record in records if record.provenance.source == "junit"]
    assert {record.subject.platform for record in junit} == {Platform.MACOS}
    assert {record.provenance.runner for record in junit} == {"macos-hosted"}
    assert all(record.provenance.btrc_revision == "abc1234" for record in records)
    for record in records:
        assert (output / record.evidence.artifact).is_file(), record.evidence.artifact

    document = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    assert document["schema"] == BUNDLE_SCHEMA
    assert (document["revision"], document["tier"], document["run"]) == ("abc1234", "release", "42")
    assert document["missing"] == [] and document["problems"] == [] and document["extra"] == []
    assert document["ignored"] == ["btrcc-linux-x64"]
    assert document["counts"] == {
        "records": len(records),
        "inputs": 5,
        "inputs_by_kind": {"bench": 1, "boundary-report": 1, "junit": 1, "skip-report": 2},
    }
    assert {item["artifact"]: item["job"] for item in document["inputs"]} == {
        "bench-results": "ci.yml/bench",
        "boundary-report-ci-tests-bootstrap": "ci.yml/tests",
        "junit-macos-native-gui": "macos.yml/native-gui",
        "skip-report-ci-tests-bootstrap": "ci.yml/tests",
        "skip-report-ci-tests-unit": "ci.yml/tests",
    }
    assert document["awaiting"] == [
        {
            "id": "macos-acceptance",
            "runner": "macos",
            "description": "the owner's Mac",
            "status": "awaiting",
            "owed_skips": 1,
        }
    ]
    with pytest.raises(Exception, match="not empty"):
        LedgerBundle(_artifacts(tmp_path), _tiny_manifest(), "release", "abc1234").build(output)


def test_a_missing_report_or_an_unreadable_input_fails_after_the_bundle_is_written(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path, drop="skip-report-ci-tests-bootstrap")
    (artifacts / "junit-macos-native-gui" / "broken.xml").write_text("<testsuite", encoding="utf-8")
    output = tmp_path / "bundle"
    outcome = LedgerBundle(artifacts, _tiny_manifest(), "release", "abc1234").build(output)
    assert not outcome.passed
    assert outcome.problems[-1] == "missing skip-report-ci-tests-bootstrap (from ci.yml/tests)"
    assert any("broken.xml" in problem for problem in outcome.problems)
    document = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    assert document["missing"] == ["skip-report-ci-tests-bootstrap"]
    assert LedgerDocument.load(output / "ledger.jsonl"), "the records it could read are kept"


def test_bench_metrics_are_kept_as_samples_but_never_pass_as_budget_evidence() -> None:
    from tools.qualification.schema import Provenance

    records = ToolsBenchAdapter(Provenance(btrc_revision="abc1234"), "linux-devcontainer").records(BENCH, "raw/r.json")
    by_id = {record.subject.id: record for record in records}
    assert by_id["btrcc.compile.BenchHello_ms"].measurement.unit == "ms"
    assert by_id["btrcc.compile.BenchArc_peak"].measurement.unit == "bytes"
    assert by_id["emit.BenchHello.c_bytes"].measurement.samples == (120345.0,)
    for record in records:
        assert record.subject.platform is Platform.LINUX
        assert record.evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
        assert record.evidence.reason.startswith("a hosted bench-check regression guard")
        assert (record.provenance.source, record.provenance.c_compiler) == ("tools.bench", "gcc")


def test_the_bundle_command_writes_the_bundle_and_reports_problems(tmp_path: Path) -> None:
    manifest = tmp_path / "tiers.toml"
    manifest.write_text(
        "\n".join(
            [
                'schema = "btrc.ci-tiers/1"',
                "[tiers]",
                'release = "everything"',
                'hardware = "devices"',
                "[[jobs]]",
                'workflow = "ci.yml"',
                'job = "bench"',
                'tiers = ["release"]',
                'reports = ["bench"]',
            ]
        ),
        encoding="utf-8",
    )
    assert tomllib.loads(manifest.read_text(encoding="utf-8"))["schema"] == "btrc.ci-tiers/1"
    artifacts = _artifacts(tmp_path)
    arguments = ["bundle", "--artifacts", str(artifacts), "--tier", "release", "--revision", "abc1234"]
    arguments += ["--manifest", str(manifest)]
    # Every input the tiny manifest does not expect is extra, not missing.
    assert QualificationCommand().run([*arguments, "--output", str(tmp_path / "one")]) == 0
    extra = json.loads((tmp_path / "one" / "bundle.json").read_text(encoding="utf-8"))["extra"]
    assert "bench-results" not in extra and "skip-report-ci-tests-unit" in extra
    (artifacts / "bench-results" / "results.json").unlink()
    assert QualificationCommand().run([*arguments, "--output", str(tmp_path / "two")]) == 1
    assert QualificationCommand().run([*arguments, "--output", str(tmp_path / "two")]) == 2


def test_the_qualification_module_runs_the_bundle_in_a_fresh_interpreter(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.qualification",
            "bundle",
            "--artifacts",
            str(_artifacts(tmp_path, drop="junit-")),
            "--output",
            str(output),
            "--tier",
            "release",
            "--revision",
            "abc1234",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    # The tracked release tier expects far more than these few reports.
    assert completed.returncode == 1, completed.stderr
    assert "missing skip-report-macos-tests-unit (from macos.yml/tests)" in completed.stderr
    assert (output / "bundle.json").is_file() and (output / "ledger.jsonl").is_file()
