"""The CI tier manifest and the plans it gives each workflow."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / ".github" / "ci") not in sys.path:
    sys.path.insert(0, str(REPO / ".github" / "ci"))

from tiers import MANIFEST, GitHubPaths, TierManifest, TierManifestError
from tiers import main as tiers_main


def _manifest() -> TierManifest:
    return TierManifest.load(MANIFEST)


def _rows(plan: dict, job: str) -> dict[str, dict[str, str]]:
    matrix = plan["matrix"].get(job, {"include": []})
    key = {
        "native-bundle": "target",
        "linux-gui": "cell",
        "native-gui": "cell",
        "linux-gui-coverage": "session",
        "linux-e40": "cell",
        "macos-e40": "cell",
        "win32-native": "target",
        "target-corpus": "target",
    }.get(job, "shard")
    return {row[key]: row for row in matrix["include"]}


# ----------------------------------------------------------------- manifest


def test_the_tracked_manifest_loads_and_describes_every_tier() -> None:
    manifest = _manifest()
    assert list(manifest.tiers) == ["docs", "pr", "lane", "main", "extended", "release", "native-gui", "hardware"]
    assert manifest.workflows() == ["ci.yml", "host-android.yml", "macos.yml", "windows.yml"]
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
    assert ci["jobs"] == [
        "release",
        "vm-test",
        "tests",
        "bench",
        "linux-arm64-bundle",
        "linux-gui",
        "linux-gui-coverage",
        "linux-e40",
    ]
    assert list(_rows(ci, "tests")) == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        "c11-gcc",
        "c11-clang",
    ]
    # Native Wayland gates Linux GUI and E40 on every push and nightly tier.
    assert list(_rows(ci, "linux-gui")) == [f"wayland-{index}" for index in range(4)]
    assert list(_rows(ci, "linux-gui-coverage")) == ["wayland"]
    assert list(_rows(ci, "linux-e40")) == [
        f"wayland-{frontend}-{variant}" for frontend in ("python", "selfhost") for variant in ("plain", "sanitized")
    ]
    nightly = manifest.plan("ci.yml", "extended")
    assert [name for name in _rows(nightly, "tests") if name not in _rows(ci, "tests")] == [
        "c11-gcc-nightly",
        "c11-clang-nightly",
    ]
    assert list(_rows(nightly, "linux-gui")) == [f"wayland-{index}" for index in range(4)]
    assert list(_rows(nightly, "linux-gui-coverage")) == ["wayland"]
    assert list(_rows(nightly, "linux-e40")) == [
        f"wayland-{frontend}-{variant}" for frontend in ("python", "selfhost") for variant in ("plain", "sanitized")
    ]
    macos = manifest.plan("macos.yml", "main")
    assert macos["jobs"] == ["native-bundle", "tests", "native-gui", "native-gui-coverage", "macos-e40"]
    assert list(_rows(macos, "macos-e40")) == [
        f"macos-{frontend}-{variant}" for frontend in ("reference", "selfhost") for variant in ("plain", "sanitized")
    ]
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
    assert manifest.plan("windows.yml", "main")["jobs"] == [
        "windows",
        "win32-native-build",
        "win32-native",
        "target-corpus-build",
        "target-corpus",
        "bootstrap",
    ]
    assert list(_rows(manifest.plan("windows.yml", "main"), "target-corpus")) == ["windows-x64", "windows-arm64"]
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
    tools_only = manifest.plan("ci.yml", "pr", ["tools/host_provenance.py"])
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
    plain = ["tools/host_provenance.py"]
    assert manifest.plan("macos.yml", "pr", plain)["jobs"] == []
    assert manifest.plan("windows.yml", "pr", plain)["jobs"] == []

    macos = manifest.plan("macos.yml", "pr", ["src/stdlib/GUI/MacOS/Window.btrc"])
    assert macos["jobs"] == ["native-bundle", "tests", "macos-e40"]
    assert list(_rows(macos, "native-bundle")) == ["macos-arm64"]
    assert list(_rows(macos, "tests")) == ["unit"]

    windows = manifest.plan("windows.yml", "pr", ["src/stdlib/FileSystem/Windows/FileSystemProvider.btrc"])
    # A Windows provider also runs its native cases and corpus bundle
    # (win32-native) and the whole corpus on both Windows rows (CX-P1-07).
    assert windows["jobs"] == [
        "windows",
        "win32-native-build",
        "win32-native",
        "target-corpus-build",
        "target-corpus",
    ], "the two-hour bootstrap waits for the main tier"
    assert list(_rows(windows, "win32-native")) == ["windows-x64", "windows-arm64"]
    assert list(_rows(windows, "target-corpus")) == ["windows-x64", "windows-arm64"]
    # The Winsock provider runs its cases and the HTTP corpus bundle there too
    # (CX-P2-10); a change to the portable HTTP sources or the HTTP corpus runs
    # them without the whole Windows corpus.
    assert manifest.plan("windows.yml", "pr", ["src/stdlib/HTTP/Windows/Win32Sockets.c"])["jobs"] == windows["jobs"]
    for http in ("src/stdlib/HTTP/HTTPServer.btrc", "src/tests/stdlib/HttpListenerPort.btrc"):
        assert manifest.plan("windows.yml", "pr", [http])["jobs"] == ["win32-native-build", "win32-native"]
    # The executor and the applicability manifest feed win32-native's Process,
    # FileSystem and HTTP bundles (CX-P2-06, CX-P2-04, CX-P2-10) as well as the corpus.
    for runner in ("tools/target_hosts/windows/executor.py", ".github/ci/target-applicability.toml"):
        assert manifest.plan("windows.yml", "pr", [runner])["jobs"] == [
            "win32-native-build",
            "win32-native",
            "target-corpus-build",
            "target-corpus",
        ]
    # The Win32 GUI provider runs its shell rows on both Windows architectures (CX-UIA-15).
    shell = manifest.plan("windows.yml", "pr", ["src/stdlib/GUI/Windows/WindowsWindow.btrc"])
    assert shell["jobs"] == ["windows", "win32-native-build", "win32-native", "target-corpus-build", "target-corpus"]
    assert list(_rows(shell, "win32-native")) == ["windows-x64", "windows-arm64"]
    assert shell["reports"]["win32-native"] == [
        "skip-report-windows-win32-native-windows-x64",
        "skip-report-windows-win32-native-windows-arm64",
    ]
    assert manifest.plan("windows.yml", "pr", ["src/tests/native/gui/shell/probes/macos/ShellProbe.m"])["jobs"] == []
    assert manifest.plan("windows.yml", "lane", ["src/devex/vscode/package.json"])["jobs"] == ["windows"]
    # A platform's expected-skip manifest is read only by that platform's skip gate.
    skips = [".github/ci/expected-skips/macos-hosted.json"]
    assert list(_rows(manifest.plan("macos.yml", "pr", skips), "tests")) == ["unit"]
    skips = [".github/ci/expected-skips/windows.json"]
    assert manifest.plan("windows.yml", "pr", skips)["jobs"] == ["windows"]
    # A push or dispatch has no change list: changed-path entries stay out.
    assert manifest.plan("windows.yml", "lane")["jobs"] == []


def test_the_android_corpus_runs_in_every_full_tier_and_on_its_own_paths() -> None:
    manifest = _manifest()
    corpus = ["target-corpus-build", "target-corpus-compile", "target-corpus"]
    for tier in ("main", "extended", "release"):
        plan = manifest.plan("host-android.yml", tier)
        assert plan["jobs"] == corpus, tier
        assert list(_rows(plan, "target-corpus")) == ["android-x64-api29", "android-x64-api36"], tier
    for changed in (
        ["tools/target_hosts/android/executor.py"],
        ["src/tests/target_runner.py"],
        [".github/ci/target-applicability.toml"],
        ["src/stdlib/FileSystem/Android/Provider.btrc"],
    ):
        assert manifest.plan("host-android.yml", "pr", changed)["jobs"] == corpus, changed
        assert manifest.plan("host-android.yml", "lane", changed)["jobs"] == corpus, changed
    # A JNI change runs the workflow's untiered fixture and JNI jobs, never the corpus.
    assert manifest.plan("host-android.yml", "pr", ["src/stdlib/Java/JNI.btrc"])["jobs"] == []
    assert manifest.plan("host-android.yml", "docs", ["tools/target_hosts/android/README.md"])["jobs"] == []
    assert manifest.expected_reports("release").get("host-android.yml/target-corpus") is None


def test_a_lane_keeps_the_linux_matrix_and_the_macos_lane_jobs() -> None:
    manifest = _manifest()
    ci = manifest.plan("ci.yml", "lane", ["src/stdlib/GUI/Linux/Window.btrc"])
    # The static job runs the naming contract, which reads every tracked file.
    assert ci["jobs"] == [
        "static",
        "release",
        "tests",
        "bench",
        "linux-arm64-bundle",
        "linux-gui",
        "linux-gui-coverage",
        "linux-e40",
    ]
    assert ci["matrix"] == manifest.plan("ci.yml", "main")["matrix"]
    macos = manifest.plan("macos.yml", "lane", ["src/stdlib/GUI/Linux/Window.btrc"])
    assert macos["jobs"] == ["native-bundle", "native-gui", "native-gui-coverage", "macos-e40"]
    assert list(_rows(macos, "native-bundle")) == ["macos-arm64"]


LANE_LINUX = ["static", "release", "tests", "bench", "linux-arm64-bundle"]
LANE_LIGHT = ["static", "release", "tests"]
# The Linux GUI and audio shard joins when a Linux GUI, audio or native path changes.
LANE_LINUX_GUI = [*LANE_LINUX, "linux-gui", "linux-gui-coverage", "linux-e40"]
LANE_LIGHT_GUI = [*LANE_LIGHT, "linux-gui", "linux-gui-coverage", "linux-e40"]
LANE_MACOS = ["native-bundle", "native-gui", "native-gui-coverage", "macos-e40"]
# Windows runs only its own paths. The Win32 GUI shell rows build from the
# shared shell fixtures and link Library.GPU (CX-UIA-15).
LANE_WINDOWS = {
    ("pyproject.toml",): ["windows"],
    ("src/stdlib/HTTP/Client.btrc",): ["win32-native-build", "win32-native"],
    ("src/tests/python/native_ui_shell_fixtures.py",): ["win32-native-build", "win32-native"],
    ("src/stdlib/GPU/Device.btrc",): ["win32-native-build", "win32-native"],
}


@pytest.mark.parametrize(
    ("changed", "linux", "macos"),
    [
        (["tools/target_hosts/android/emulator.sh"], LANE_LIGHT, []),
        # ... except the headless session every Linux test shard runs inside.
        ([".github/ci/headless-session.sh"], LANE_LINUX_GUI, LANE_MACOS),
        # A btrc-shard contract imports this unit test module.
        (["src/tests/python/test_exception_codegen_contracts.py"], LANE_LINUX, []),
        (["src/tests/python/test_native_gui_target.py"], LANE_LIGHT_GUI, LANE_MACOS),
        (["src/stdlib/GUI/MacOS/Window.btrc"], LANE_LINUX, LANE_MACOS),
        (["src/tests/native/gui/shell/probes/macos/ShellProbe.m"], LANE_LINUX, LANE_MACOS),
        (["src/stdlib/Tray/Tray.btrc"], LANE_LINUX_GUI, LANE_MACOS),
        (["src/stdlib/HTTP/Client.btrc"], LANE_LINUX, []),
        (["src/tests/python/native_ui_shell_fixtures.py"], LANE_LINUX_GUI, []),
        (["src/tests/strings/Escapes.btrc"], LANE_LINUX, []),
        (["tools/NativeHeaderReader.cpp"], LANE_LINUX_GUI, LANE_MACOS),
        # One heavy path among light ones selects the heavy jobs.
        (["docs/design/probe.m", "src/tests/stdlib/Json.btrc"], LANE_LINUX, LANE_MACOS),
        # No change list, or an empty one, fails safe to the whole lane selection.
        (None, LANE_LINUX_GUI, LANE_MACOS),
        ([], LANE_LINUX_GUI, LANE_MACOS),
        ([""], LANE_LINUX_GUI, LANE_MACOS),
        # A macOS provider or probe does not select the Linux GUI shard.
        (["src/stdlib/Audio/MacOS/CoreAudio.btrc"], LANE_LINUX, LANE_MACOS),
        (["src/tests/python/linux_provider_fixtures.py"], LANE_LINUX_GUI, []),
        (["src/tests/python/pulse_audio_peer.py"], LANE_LINUX_GUI, []),
        ([".github/ci/expected-skips/linux-devcontainer.json"], LANE_LINUX_GUI, []),
        # Root files that configure pytest, the container or line endings reach every shard.
        (["pyproject.toml"], LANE_LINUX, []),
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
        ([".github/ci/expected-skips/macos-hosted.json"], LANE_LINUX, LANE_MACOS),
        (["src/stdlib/Image/EncodedImage.btrc"], LANE_LINUX_GUI, []),
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
    assert list(_rows(ci, "linux-gui")) == ([f"wayland-{index}" for index in range(4)] if "linux-gui" in linux else [])
    plan = manifest.plan("macos.yml", "lane", changed)
    assert plan["jobs"] == macos
    assert list(_rows(plan, "native-bundle")) == (["macos-arm64"] if macos else [])
    # Windows keeps its own rule: only its paths, as in the pr tier, and nothing without a list.
    windows = manifest.plan("windows.yml", "lane", changed)["jobs"]
    assert windows == (LANE_WINDOWS.get(tuple(changed), []) if changed is not None else [])
    assert windows == (manifest.plan("windows.yml", "pr", changed)["jobs"] if changed is not None else [])


def test_path_selection_leaves_unconditional_full_tiers_alone() -> None:
    """Lane/PR path selection cannot narrow the unconditional full-tier matrix."""

    manifest = _manifest()
    selected = {tier for entry in (*manifest.jobs, *manifest.shards) for tier in entry.condition.selected_tiers()}
    assert selected == {"lane", "pr"}
    samples = [
        ["tools/target_hosts/android/emulator.sh"],
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
    assert expected["macos.yml/native-gui"] == [
        f"{kind}-macos-native-gui-macos-{index}" for index in range(4) for kind in ("skip-report", "junit")
    ]
    assert expected["ci.yml/linux-gui"] == [
        f"{kind}-ci-linux-gui-wayland-{index}" for index in range(4) for kind in ("skip-report", "junit")
    ]
    assert expected["ci.yml/linux-e40"] == [
        f"{kind}-ci-linux-e40-wayland-{frontend}-{variant}"
        for frontend in ("python", "selfhost")
        for variant in ("plain", "sanitized")
        for kind in ("skip-report", "junit")
    ]
    assert expected["macos.yml/macos-e40"] == [
        f"{kind}-macos-macos-e40-macos-{frontend}-{variant}"
        for frontend in ("reference", "selfhost")
        for variant in ("plain", "sanitized")
        for kind in ("skip-report", "junit")
    ]
    assert "boundary-report-ci-tests-bootstrap" in expected["ci.yml/tests"]
    assert "boundary-report-macos-tests-bootstrap" in expected["macos.yml/tests"]
    # Five shards and four C11 rows, each row's artifact holding its two cells' reports.
    assert len([name for name in expected["ci.yml/tests"] if name.startswith("skip-report-")]) == 9
    assert len([name for name in expected["macos.yml/tests"] if name.startswith("skip-report-")]) == 9
    assert expected["windows.yml/windows"] == ["skip-report-windows-windows"]
    assert expected["windows.yml/bootstrap"] == ["skip-report-windows-bootstrap"]
    with pytest.raises(TierManifestError, match="no scheduled tier"):
        _manifest().plan("ci.yml", "hardware")


def test_the_tiers_command_prints_one_line_of_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    changed = tmp_path / "changed.txt"
    changed.write_text("src/tests/strings/Foo.btrc\n\n", encoding="utf-8")
    code = tiers_main(["--workflow", "ci.yml", "--tier", "pr", "--changed", str(changed)])
    out = capsys.readouterr().out
    assert code == 0 and out.count("\n") == 1
    assert json.loads(out) == _manifest().plan("ci.yml", "pr", ["src/tests/strings/Foo.btrc"])
    assert tiers_main([]) == 0
    assert "ci.yml main: 8 job(s), 16 matrix row(s)" in capsys.readouterr().out
    assert tiers_main(["--workflow", "ci.yml"]) == 2
    assert tiers_main(["--workflow", "ci.yml", "--tier", "nightly"]) == 2


@pytest.mark.parametrize(
    ("workflow", "tier", "changed", "delegated"),
    [
        ("ci.yml", "main", None, "1"),
        ("ci.yml", "release", None, "1"),
        ("ci.yml", "lane", None, "1"),
        ("ci.yml", "pr", ["src/stdlib/GUI/Linux/Window.btrc"], "1"),
        ("ci.yml", "pr", ["src/tests/python/test_build_safety.py"], "1"),
        ("ci.yml", "pr", ["src/compiler/python/main.py"], "0"),
        ("ci.yml", "pr", ["src/stdlib/GUI/MacOS/Window.btrc"], "0"),
        ("ci.yml", "pr", None, "0"),
        ("ci.yml", "lane", [".github/ci/tiers.py"], "0"),
        ("macos.yml", "main", None, "1"),
        ("macos.yml", "release", None, "1"),
    ],
)
def test_unit_gui_delegation_follows_required_platform_coverage(workflow, tier, changed, delegated):
    manifest = _manifest()
    plan = manifest.plan(workflow, tier, changed)
    assert _rows(plan, "tests")["unit"].get("unit_gui_delegated") == delegated
    # Planning must not modify manifest rows or leak a decision into the next plan.
    assert all("unit_gui_delegated" not in shard.row for shard in manifest.shards)
    assert _rows(manifest.plan("ci.yml", "pr", ["README.md"]), "tests")["unit"].get("unit_gui_delegated", "0") == "0"


@pytest.mark.parametrize(
    "damage",
    [
        "missing-partition",
        "optional-partition",
        "wrong-count",
        "duplicate-index",
        "wrong-cell",
        "missing-coverage",
        "optional-coverage",
        "wrong-session",
    ],
)
def test_unit_keeps_gui_when_the_required_wayland_plan_is_incomplete(damage):
    manifest = _manifest()
    shards = []
    for shard in manifest.shards:
        row = dict(shard.row)
        if shard.job == "ci.yml/linux-gui" and row["session"] == "wayland":
            if damage == "missing-partition" and row["index"] == "0":
                continue
            if damage == "wrong-session":
                row["session"] = "x11"
                row["cell"] = f"x11-{row['index']}"
            elif row["index"] == "0":
                if damage == "optional-partition":
                    row["report_only"] = "true"
                elif damage == "wrong-count":
                    row["count"] = "3"
                elif damage == "duplicate-index":
                    row["index"] = "1"
                elif damage == "wrong-cell":
                    row["cell"] = "other-0"
        if shard.job == "ci.yml/linux-gui-coverage" and row["session"] == "wayland":
            if damage == "missing-coverage":
                continue
            if damage == "optional-coverage":
                row["report_only"] = "true"
        shards.append(replace(shard, row=row))
    plan = replace(manifest, shards=tuple(shards)).plan("ci.yml", "main")
    assert _rows(plan, "tests")["unit"]["unit_gui_delegated"] == "0"


def test_manifest_cannot_force_unit_gui_delegation():
    data = _minimal()
    data["shards"][0]["unit_gui_delegated"] = "1"
    with pytest.raises(TierManifestError, match="unit_gui_delegated is computed"):
        TierManifest.from_mapping(data)


@pytest.mark.parametrize(
    "damage",
    ["missing-partition", "optional-partition", "wrong-count", "duplicate-index", "wrong-cell", "missing-coverage"],
)
def test_unit_keeps_gui_when_the_required_macos_plan_is_incomplete(damage):
    manifest = _manifest()
    shards = []
    for shard in manifest.shards:
        row = dict(shard.row)
        if shard.job == "macos.yml/native-gui" and row["index"] == "0":
            if damage == "missing-partition":
                continue
            if damage == "optional-partition":
                row["report_only"] = "true"
            elif damage == "wrong-count":
                row["count"] = "3"
            elif damage == "duplicate-index":
                row["index"] = "1"
            elif damage == "wrong-cell":
                row["cell"] = "other-0"
        shards.append(replace(shard, row=row))
    jobs = tuple(
        job
        for job in manifest.jobs
        if not (damage == "missing-coverage" and job.reference == "macos.yml/native-gui-coverage")
    )
    plan = replace(manifest, shards=tuple(shards), jobs=jobs).plan("macos.yml", "main")
    assert _rows(plan, "tests")["unit"]["unit_gui_delegated"] == "0"


def test_macos_pr_unit_keeps_gui_without_required_partitions():
    plan = _manifest().plan("macos.yml", "pr", ["src/stdlib/GUI/MacOS/Window.btrc"])
    assert "native-gui" not in plan["jobs"]
    assert _rows(plan, "tests")["unit"]["unit_gui_delegated"] == "0"
