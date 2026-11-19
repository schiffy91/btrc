"""A qualification cell cannot pass with a partial denominator or evidence set."""

import io
import json
import shutil
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from tools.ui.e40 import E40Run, LinuxE40Cases, MacOSE40Cases, MenuDismissal, MetalPresentation

NODES = LinuxE40Cases.nodes("python", "plain")
METADATA = {"frontend": "python", "variant": "plain", "session": "x11", "revision": "a" * 40, "source_changes": []}


def junit(path, nodes, status=None, skips=None):
    suite = ET.Element("testsuite")
    for node in nodes:
        source, name = node.split("::")
        case = ET.SubElement(suite, "testcase", classname=source.removesuffix(".py").replace("/", "."), name=name)
        if status:
            ET.SubElement(case, status)
        if skips and node in skips:
            ET.SubElement(case, "skipped", type="pytest.skip", message=skips[node])
    ET.ElementTree(suite).write(path)


def evidence(root):
    common = {
        "frontend": "python",
        "sanitized": False,
        "backend": "x11",
        "returncode": 0,
        "revision": METADATA["revision"],
        "source_changes": [],
    }
    for terminal in range(4):
        for count in (4095, 4096, 4097, 8193):
            directory = root / "pytest" / f"burst-{count}-{terminal}"
            directory.mkdir(parents=True)
            (directory / "e40-bursts.json").write_text(
                json.dumps(
                    {
                        **common,
                        "count": count,
                        "terminal": terminal,
                        "repetitions": 100,
                        "trials": [{}] * 100,
                        "admission": [{}] * 100,
                    }
                )
            )
            (directory / "stdout.txt").write_text("native output")
            (directory / "stderr.txt").write_text("")
    directory = root / "pytest" / "load"
    directory.mkdir()
    (directory / "e40-load.json").write_text(
        json.dumps(
            {
                **common,
                "requested_seconds": 600,
                "qualifying": True,
                "native": [{"duration_ns": 600_000_000_000, "qualifying": True}],
            }
        )
    )
    (directory / "stdout.txt").write_text("native output")
    (directory / "stderr.txt").write_text("")
    (directory / "presentations.csv").write_text("window,ns\n0,1\n1,2\n")


def test_complete_cell_evidence(tmp_path):
    assert len(NODES) == len(set(NODES)) == 17
    E40Run.validate_collection("\n".join(NODES), NODES)
    path = tmp_path / "junit.xml"
    junit(path, NODES)
    E40Run.validate_junit(path, NODES)
    evidence(tmp_path)
    LinuxE40Cases.validate_evidence(tmp_path, METADATA)


@pytest.mark.parametrize("outcome", ["passed", "test-failure", "evidence-failure"])
def test_run_finalizes_real_evidence_files_and_preserves_outcome(tmp_path, monkeypatch, outcome):
    calls = []
    monkeypatch.delenv("BTRC_NATIVE_HEADER_READER", raising=False)
    monkeypatch.delenv("BTRC_TEST_BTRCC", raising=False)
    monkeypatch.setattr("tools.ui.e40.platform.platform", lambda: "fixture-platform")
    monkeypatch.setattr("tools.ui.e40.platform.machine", lambda: "fixture-machine")

    def command_output(command, **kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return METADATA["revision"] + "\n"
        if command[-2:] == ["status", "--porcelain"]:
            return ""
        assert command == ["cc", "--version"]
        return "fixture compiler\n"

    def process(command, **kwargs):
        calls.append(command)
        if "--collect-only" in command:
            return SimpleNamespace(stdout=io.StringIO("\n".join(NODES) + "\n"), wait=lambda: 0)
        evidence(tmp_path)
        junit(tmp_path / "junit.xml", NODES, "failure" if outcome == "test-failure" else None)
        if outcome == "evidence-failure":
            (tmp_path / "pytest/load/e40-load.json").unlink()
        return SimpleNamespace(
            stdout=io.StringIO("qualification output\n"), wait=lambda: 1 if outcome == "test-failure" else 0
        )

    monkeypatch.setattr("tools.ui.e40.subprocess.check_output", command_output)
    monkeypatch.setattr("tools.ui.e40.subprocess.Popen", process)
    run = E40Run(NODES, tmp_path, {**METADATA, "cell": "fixture-cell"}, LinuxE40Cases.validate_evidence)
    if outcome == "passed":
        run.run()
    else:
        expected = "qualification exited 1" if outcome == "test-failure" else "16 burst reports and one load"
        with pytest.raises(RuntimeError, match=expected) as error:
            run.run()
    saved = json.loads((tmp_path / "provenance.json").read_text())
    assert saved["status"] == ("passed" if outcome == "passed" else "failed")
    if outcome != "passed":
        assert saved["error"] == str(error.value)
    assert len(calls) == 2
    assert [phase["returncode"] for phase in saved["phases"]] == [0, 1 if outcome == "test-failure" else 0]
    expected_files = {
        str(path.relative_to(tmp_path)): path.stat().st_size
        for path in tmp_path.rglob("*")
        if path.is_file() and path != tmp_path / "provenance.json"
    }
    assert expected_files
    assert {item["path"]: item["bytes"] for item in saved["evidence"]} == expected_files
    assert saved["expected_nodes"] == NODES


@pytest.mark.parametrize("nodes", [NODES[:-1], [*NODES, NODES[0]], [*NODES[:-1], NODES[0]]])
def test_collection_rejects_missing_extra_and_duplicate_cases(nodes):
    with pytest.raises(RuntimeError, match="collection differs"):
        E40Run.validate_collection("\n".join(nodes), NODES)


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
def test_junit_rejects_nonpassing_cases(tmp_path, status):
    path = tmp_path / "junit.xml"
    junit(path, NODES, status)
    with pytest.raises(RuntimeError, match="without skips"):
        E40Run.validate_junit(path, NODES)


@pytest.mark.parametrize("nodes", [NODES[:-1], [*NODES, NODES[0]], [*NODES[:-1], NODES[0]]])
def test_junit_requires_each_identity_exactly_once(tmp_path, nodes):
    path = tmp_path / "junit.xml"
    junit(path, nodes)
    with pytest.raises(RuntimeError, match="exactly once"):
        E40Run.validate_junit(path, NODES)


@pytest.mark.parametrize(
    "missing", ["burst-4095-0/e40-bursts.json", "load/e40-load.json", "load/presentations.csv", "load/stderr.txt"]
)
def test_evidence_requires_all_reports_and_native_outputs(tmp_path, missing):
    evidence(tmp_path)
    (tmp_path / "pytest" / missing).unlink()
    with pytest.raises(RuntimeError):
        LinuxE40Cases.validate_evidence(tmp_path, METADATA)


@pytest.mark.parametrize(
    "field,value", [("requested_seconds", 10), ("qualifying", False), ("frontend", "selfhost"), ("backend", "wayland")]
)
def test_short_or_wrong_cell_evidence_cannot_qualify(tmp_path, field, value):
    evidence(tmp_path)
    path = tmp_path / "pytest/load/e40-load.json"
    report = json.loads(path.read_text())
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError):
        LinuxE40Cases.validate_evidence(tmp_path, METADATA)


@pytest.mark.parametrize("field,value", [("revision", "b" * 40), ("source_changes", [" M changed.btrc"])])
def test_report_identity_must_match_the_qualification_run(tmp_path, field, value):
    evidence(tmp_path)
    path = tmp_path / "pytest/burst-4095-0/e40-bursts.json"
    report = json.loads(path.read_text())
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError, match="provenance/outcome differs"):
        LinuxE40Cases.validate_evidence(tmp_path, METADATA)


MAC_METADATA = {**METADATA, "frontend": "reference", "provider": "macos"}


@pytest.fixture
def mac_evidence(tmp_path, monkeypatch):
    class Calls(list):
        """The delegated checks, with the dismissal floor each tracking check was given."""

        floors: list

    calls = Calls()
    calls.floors = floors = []

    class Evidence:
        def __init__(self, report, sanitized, menu_dismissal_floor_ns=None):
            self.report = report
            self.floor = menu_dismissal_floor_ns
            assert sanitized is False

        def bursts(self):
            calls.append((self.report["entry"], "bursts"))

        def load(self):
            calls.append((self.report["entry"], "load"))

        def tracking(self, trial):
            floors.append((trial, self.floor))
            calls.append((self.report["entry"], trial))

        def presentations(self, path):
            assert path.is_file()
            calls.append((self.report["entry"], "presentations"))

    monkeypatch.setattr("src.tests.python.native_ui2_e40_evidence.E40Evidence", Evidence)
    for entry in MacOSE40Cases.entries:
        for trial in MacOSE40Cases.trials:
            directory = tmp_path / "native/reference/plain" / entry / trial
            directory.mkdir(parents=True)
            identity = {
                **MAC_METADATA,
                "sanitized": False,
                "native_optimization": 2,
                "native_build_commands": [
                    ["/usr/bin/clang", "-c", "source.c", "-o", "source.o"],
                    ["/usr/bin/clang", "source.o", "-o", "program"],
                ],
                "executable_sha256": "0" * 64,
            }
            (directory / "provenance.json").write_text(json.dumps(identity))
            (directory / "observations.json").write_text(json.dumps({"entry": entry, "trial": trial}))
            (directory / "stdout.txt").write_text("native output")
            (directory / "stderr.txt").write_text("")
            if trial != "bursts":
                (directory / "observations.json.presentations.csv").write_text("native presentation records")
    return calls


def test_macos_catalog_has_four_disjoint_twelve_case_cells():
    all_nodes = MacOSE40Cases.all_nodes()
    assert len(all_nodes) == len(set(all_nodes)) == 48
    for frontend in ("reference", "selfhost"):
        for variant in ("plain", "sanitized"):
            nodes = MacOSE40Cases.nodes(frontend, variant)
            assert len(nodes) == 12
            assert nodes[0].endswith(f"[{variant}-{frontend}-desktop-bursts]")
            assert nodes[-1].endswith(f"[{variant}-{frontend}-host-sheet]")


@pytest.mark.parametrize(
    "host,environment",
    [
        ("linux", {"CI": "true", "BTRC_UI2_HOSTED_E40": "1"}),
        ("darwin", {}),
        ("darwin", {"CI": "true"}),
        ("darwin", {"BTRC_UI2_HOSTED_E40": "1"}),
    ],
)
def test_macos_runtime_requires_both_hosted_opt_ins(host, environment):
    with pytest.raises(RuntimeError, match="hosted CI opt-in"):
        MacOSE40Cases.require_hosted(host, environment)


def test_macos_explicit_hosted_admission():
    MacOSE40Cases.require_hosted("darwin", {"CI": "true", "BTRC_UI2_HOSTED_E40": "1"})


def test_fresh_output_refuses_existing_directory_without_deleting_it(tmp_path):
    marker = tmp_path / "user-file.txt"
    marker.write_text("preserve me")
    run = E40Run([], tmp_path, {}, MacOSE40Cases.validate_evidence, fresh_output=True)
    with pytest.raises(FileExistsError):
        run.run()
    assert marker.read_text() == "preserve me"
    assert not (tmp_path / "provenance.json").exists()


def test_mac_artifact_owner_delegates_every_trial_and_presentation(tmp_path, mac_evidence):
    MacOSE40Cases.validate_evidence(tmp_path, MAC_METADATA)
    assert len(mac_evidence) == 22
    for entry in MacOSE40Cases.entries:
        assert [trial for observed, trial in mac_evidence if observed == entry].count("presentations") == 5
        assert {trial for observed, trial in mac_evidence if observed == entry} == {
            *MacOSE40Cases.trials,
            "presentations",
        }


@pytest.mark.parametrize(
    "missing",
    ["observations.json", "provenance.json", "stdout.txt", "stderr.txt", "observations.json.presentations.csv"],
)
def test_mac_artifacts_cannot_omit_case_evidence(tmp_path, mac_evidence, missing):
    (tmp_path / "native/reference/plain/host/sheet" / missing).unlink()
    with pytest.raises((RuntimeError, AssertionError)):
        MacOSE40Cases.validate_evidence(tmp_path, MAC_METADATA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "b" * 40),
        ("source_changes", [" M wrong.btrc"]),
        ("frontend", "selfhost"),
        ("sanitized", True),
        ("native_build_commands", []),
        ("native_optimization", 0),
        ("executable_sha256", "missing"),
    ],
)
def test_mac_report_provenance_is_bound_to_the_run(tmp_path, mac_evidence, field, value):
    path = tmp_path / "native/reference/plain/desktop/bursts/provenance.json"
    identity = json.loads(path.read_text())
    identity[field] = value
    path.write_text(json.dumps(identity))
    with pytest.raises(RuntimeError):
        MacOSE40Cases.validate_evidence(tmp_path, MAC_METADATA)


def test_mac_native_identity_cannot_be_reused_for_another_trial(tmp_path, mac_evidence):
    path = tmp_path / "native/reference/plain/host/sheet/observations.json"
    path.write_text(json.dumps({"entry": "desktop", "trial": "sheet"}))
    with pytest.raises(RuntimeError, match="native trial identity differs"):
        MacOSE40Cases.validate_evidence(tmp_path, MAC_METADATA)


def menu_dismissal(root, **changes):
    """Retain a bare menu-dismissal control's files; `changes` replace report or sample fields."""
    directory = root / "native" / f"{MenuDismissal.CONTROL}-control"
    directory.mkdir(parents=True, exist_ok=True)
    samples = [
        {
            "entered_ns": 1_000,
            "return_submitted_ns": 2_000_001_000,
            "tracking_ended_ns": 2_000_001_000 + dismissal,
            "dismissal_ns": dismissal,
            "maximum_arrow_ns": 8_000_000,
            "keys": 21,
            "highlight_changes": 20,
            "selected_index": 20,
            "application_active": True,
            "window_key": True,
            "forced_cleanup": False,
        }
        for dismissal in (362_000_000, 355_000_000, 371_000_000, 358_000_000, 366_000_000)
    ]
    report = {
        "schema": "btrc.ui2.macos-menu-dismissal-control/1",
        "native_backend": "AppKit",
        "btrc_code": False,
        "clock": "mach_continuous_time nanoseconds",
        "input_route": "menu-arrow-highlight-return",
        "items": 21,
        "samples": samples,
        "unavailable": None,
    }
    execution = {"status": "completed", "returncode": 0}
    for name, value in changes.items():
        if name in execution:
            execution[name] = value
        elif name in report:
            report[name] = value
        else:
            samples[2][name] = value
    (directory / "execution.json").write_text(json.dumps(execution))
    (directory / "observations.json").write_text(json.dumps(report))
    return root / "native"


def test_menu_dismissal_floor_is_the_smallest_complete_sample(tmp_path):
    assert MenuDismissal.floor(menu_dismissal(tmp_path)) == 355_000_000


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "failed"},
        {"returncode": 1},
        {"schema": "btrc.ui2.macos-menu-dismissal-control/0"},
        {"btrc_code": True},
        {"clock": "wall"},
        {"items": 3},
        {"unavailable": "CGPreflightPostEventAccess is false"},
        {"samples": []},
        {"forced_cleanup": True},
        {"selected_index": 19},
        {"highlight_changes": 19},
        {"keys": 20},
        {"application_active": False},
        {"window_key": False},
        {"dismissal_ns": 1},
        {"tracking_ended_ns": 0},
    ],
)
def test_incomplete_menu_dismissal_control_gives_no_floor(tmp_path, changes):
    assert MenuDismissal.floor(menu_dismissal(tmp_path, **changes)) is None


def test_missing_menu_dismissal_control_gives_no_floor(tmp_path):
    assert MenuDismissal.floor(tmp_path / "native") is None
    menu_dismissal(tmp_path)
    (tmp_path / "native" / f"{MenuDismissal.CONTROL}-control" / "execution.json").unlink()
    assert MenuDismissal.floor(tmp_path / "native") is None


def test_mac_artifact_owner_gives_the_dismissal_floor_to_the_popup_trials_alone(tmp_path, mac_evidence):
    menu_dismissal(tmp_path)
    MacOSE40Cases.validate_evidence(tmp_path, MAC_METADATA)
    assert sorted(mac_evidence.floors) == sorted(
        (trial, 355_000_000 if trial == "popup" else None)
        for trial in ("popup", "slider", "resize", "sheet")
        for _ in MacOSE40Cases.entries
    )


def test_mac_artifact_owner_invents_no_dismissal_floor(tmp_path, mac_evidence):
    MacOSE40Cases.validate_evidence(tmp_path, MAC_METADATA)
    assert {floor for _, floor in mac_evidence.floors} == {None}


MAC_NODES = MacOSE40Cases.nodes("reference", "plain")
HOSTED_METADATA = {**MAC_METADATA, "runner": "macos-hosted"}
WITHHELD = "this hosted runner's GPU presents no frames (direct Metal control: 20 acquired, 20 completed, 0 presented)"
WITHHELD_NODES = dict.fromkeys([node for node in MAC_NODES if not node.endswith("-bursts]")], WITHHELD)


def metal_control(root, **counts):
    directory = root / "native/metal-control"
    directory.mkdir(parents=True, exist_ok=True)
    report = {"acquired": 20, "command_completed": 20, "command_errors": 0, "presented": 0, "skipped": 20} | counts
    (directory / "observations.json").write_text(json.dumps(report))


def withhold_presentation(root):
    metal_control(root)
    for entry in MacOSE40Cases.entries:
        for trial in MacOSE40Cases.presented_trials:
            shutil.rmtree(root / "native/reference/plain" / entry / trial)


def test_presentation_trials_are_every_trial_whose_evidence_requires_presented_frames():
    assert MacOSE40Cases.presented_trials == ("load", "popup", "slider", "resize", "sheet")
    assert MacOSE40Cases.trials == ("bursts", *MacOSE40Cases.presented_trials)
    assert len(WITHHELD_NODES) == 10 and set(WITHHELD_NODES) < set(MAC_NODES)


@pytest.mark.parametrize(
    "runner,counts,withheld",
    [
        ("macos-hosted", {}, True),
        ("macos-hosted", {"acquired": 3, "command_completed": 3}, True),
        ("macos", {}, False),  # the acceptance Mac fails without presentation; it never skips
        ("unconfigured", {}, False),
        (None, {}, False),
        ("macos-hosted", {"presented": 19}, False),
        ("macos-hosted", {"acquired": 0, "command_completed": 0}, False),  # the control never drew
        ("macos-hosted", {"command_completed": 19}, False),
        ("macos-hosted", {"command_errors": 1}, False),
        ("macos-hosted", {"presented": None}, False),
        ("macos-hosted", {"presented": False}, False),
    ],
)
def test_only_a_hosted_gpu_that_completes_commands_and_presents_nothing_withholds(tmp_path, runner, counts, withheld):
    metal_control(tmp_path, **counts)
    metadata = {**HOSTED_METADATA, "runner": runner}
    reason = MacOSE40Cases.presentation_withheld(tmp_path, metadata)
    if not withheld:
        assert reason is None and MacOSE40Cases.expected_skips(tmp_path, metadata) == {}
        return
    assert reason == WITHHELD.replace("20", str(counts.get("acquired", 20)))
    assert MacOSE40Cases.expected_skips(tmp_path, metadata) == dict.fromkeys(WITHHELD_NODES, reason)


@pytest.mark.parametrize("report", [None, "", "[]", "{}", '{"acquired": 20}'])
def test_a_missing_or_unusable_control_report_withholds_nothing(tmp_path, report):
    if report is not None:
        (tmp_path / "native/metal-control").mkdir(parents=True)
        (tmp_path / "native/metal-control/observations.json").write_text(report)
    assert MetalPresentation.read(tmp_path / "native") is None
    assert MacOSE40Cases.expected_skips(tmp_path, HOSTED_METADATA) == {}


def test_junit_accepts_exactly_the_declared_skips(tmp_path):
    path = tmp_path / "junit.xml"
    junit(path, MAC_NODES, skips=WITHHELD_NODES)
    E40Run.validate_junit(path, MAC_NODES, WITHHELD_NODES)
    with pytest.raises(RuntimeError, match="without skips"):
        E40Run.validate_junit(path, MAC_NODES)


@pytest.mark.parametrize("change", ["ran", "other-reason", "bursts-skipped", "failed"])
def test_junit_rejects_any_departure_from_the_declared_skips(tmp_path, change):
    path = tmp_path / "junit.xml"
    recorded = dict(WITHHELD_NODES)
    if change == "ran":
        del recorded[MAC_NODES[1]]
    elif change == "other-reason":
        recorded[MAC_NODES[1]] = "E40 visible native execution requires explicit hosted CI opt-in"
    elif change == "bursts-skipped":
        recorded[MAC_NODES[0]] = WITHHELD
    junit(path, MAC_NODES, skips=recorded)
    if change == "failed":
        document = ET.parse(path)
        ET.SubElement(next(document.getroot().iter("testcase")), "failure")
        document.write(path)
    with pytest.raises(RuntimeError, match="without skips" if change in ("bursts-skipped", "failed") else "declared"):
        E40Run.validate_junit(path, MAC_NODES, WITHHELD_NODES)


def test_withheld_mac_evidence_is_the_bursts_and_the_control(tmp_path, mac_evidence):
    withhold_presentation(tmp_path)
    MacOSE40Cases.validate_evidence(tmp_path, HOSTED_METADATA)
    assert mac_evidence == [("desktop", "bursts"), ("host", "bursts")]


@pytest.mark.parametrize("change", ["acceptance-mac", "control-presents", "control-missing", "trial-reported"])
def test_withheld_mac_evidence_needs_the_hosted_control_and_no_presentation_report(tmp_path, mac_evidence, change):
    withhold_presentation(tmp_path)
    metadata = dict(HOSTED_METADATA)
    if change == "acceptance-mac":
        metadata["runner"] = "macos"
    elif change == "control-presents":
        metal_control(tmp_path, presented=19)
    elif change == "control-missing":
        shutil.rmtree(tmp_path / "native/metal-control")
    else:
        directory = tmp_path / "native/reference/plain/host/sheet"
        directory.mkdir()
        (directory / "observations.json").write_text(json.dumps({"entry": "host", "trial": "sheet"}))
    with pytest.raises(RuntimeError, match="exactly 2 " if change == "trial-reported" else "exactly 12 "):
        MacOSE40Cases.validate_evidence(tmp_path, metadata)


def test_retained_controls_are_not_trial_reports(tmp_path, mac_evidence):
    for control in MacOSE40Cases.controls:
        directory = tmp_path / "native" / f"{control}-control"
        directory.mkdir()
        (directory / "observations.json").write_text(json.dumps({"acquired": 20, "presented": 19}))
    MacOSE40Cases.validate_evidence(tmp_path, {**HOSTED_METADATA, "runner": "macos"})
    assert len(mac_evidence) == 22
    (tmp_path / "native/other-control").mkdir()
    (tmp_path / "native/other-control/observations.json").write_text("{}")
    with pytest.raises(RuntimeError, match="exactly 12 "):
        MacOSE40Cases.validate_evidence(tmp_path, {**HOSTED_METADATA, "runner": "macos"})


@pytest.mark.parametrize("outcome", ["withheld", "presentation-trial-ran", "acceptance-mac"])
def test_mac_run_passes_with_exactly_the_skips_its_control_declares(tmp_path, monkeypatch, mac_evidence, outcome):
    monkeypatch.delenv("BTRC_NATIVE_HEADER_READER", raising=False)
    monkeypatch.delenv("BTRC_TEST_BTRCC", raising=False)
    monkeypatch.setenv("BTRC_TEST_RUNNER", "macos" if outcome == "acceptance-mac" else "macos-hosted")
    monkeypatch.setattr("tools.ui.e40.platform.platform", lambda: "fixture-platform")
    monkeypatch.setattr("tools.ui.e40.platform.machine", lambda: "fixture-machine")

    def command_output(command, **kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return MAC_METADATA["revision"] + "\n"
        return "" if command[-2:] == ["status", "--porcelain"] else "fixture compiler\n"

    def process(command, **kwargs):
        if "--collect-only" in command:
            return SimpleNamespace(stdout=io.StringIO("\n".join(MAC_NODES) + "\n"), wait=lambda: 0)
        withhold_presentation(tmp_path)
        recorded = dict(WITHHELD_NODES)
        if outcome == "presentation-trial-ran":
            del recorded[MAC_NODES[1]]
        junit(tmp_path / "junit.xml", MAC_NODES, skips=recorded)
        return SimpleNamespace(stdout=io.StringIO("qualification output\n"), wait=lambda: 0)

    monkeypatch.setattr("tools.ui.e40.subprocess.check_output", command_output)
    monkeypatch.setattr("tools.ui.e40.subprocess.Popen", process)
    run = E40Run(
        MAC_NODES,
        tmp_path,
        {"provider": "macos", "cell": "fixture-cell", "frontend": "reference", "variant": "plain"},
        MacOSE40Cases.validate_evidence,
        expected_skips=MacOSE40Cases.expected_skips,
    )
    if outcome == "withheld":
        run.run()
    else:
        with pytest.raises(RuntimeError, match="declared" if outcome == "presentation-trial-ran" else "without skips"):
            run.run()
    saved = json.loads((tmp_path / "provenance.json").read_text())
    assert saved["status"] == ("passed" if outcome == "withheld" else "failed")
    assert saved["expected_skips"] == ({} if outcome == "acceptance-mac" else WITHHELD_NODES)
    assert "native/metal-control/observations.json" in {item["path"] for item in saved["evidence"]}
