"""Committed acceptance-host manifests and their embedding in budget_bench's report.json."""

from __future__ import annotations

import copy
import json
import os
import sys
import tomllib
from pathlib import Path

import pytest

from tools import budget_bench as bench

REPO = Path(__file__).resolve().parents[3]
HOSTS = REPO / "tools/qualification/hosts"
MAC = "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0"


def manifests() -> dict[str, bench.HostManifest]:
    return {manifest.id: manifest for manifest in bench.HostManifest.committed()}


def table(name: str) -> dict[str, object]:
    return tomllib.loads((HOSTS / f"{name}.toml").read_text(encoding="utf-8"))


def write(directory: Path, data: dict[str, object]) -> Path:
    """A manifest file from a table of strings, integers, lists and one level of subtables."""

    def value(item: object) -> str:
        return json.dumps(item)

    lines = [f"{key} = {value(item)}" for key, item in data.items() if not isinstance(item, dict)]
    for key, item in data.items():
        if isinstance(item, dict):
            lines += ["", f"[{key}]", *(f"{name} = {value(entry)}" for name, entry in item.items())]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{data['id']}.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_three_hosts_are_committed_and_valid():
    assert sorted(manifests()) == ["fractal-north", "gh-ubuntu-24.04-x86_64", "mac-m1-max"]
    for path in sorted(HOSTS.glob("*.toml")):
        assert bench.HostManifest.problems(tomllib.loads(path.read_text(encoding="utf-8")), path.stem) == []


def test_the_mac_manifest_is_agents_md_exact_provenance_string():
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert f"{MAC}. Record exactly that host provenance string" in " ".join(agents.split())
    mac = manifests()["mac-m1-max"]
    assert mac.table["summary"] == MAC and mac.table["role"] == "acceptance"
    assert mac.table["cpu"] == {"model": "Apple M1 Max", "topology": "8P+2E", "logical_cores": 10, "physical_cores": 10}
    assert mac.table["memory_gib"] == 64 and mac.table["instruction_counter"] == "/usr/bin/time -l"
    assert mac.matches(MAC)
    assert not mac.matches(MAC.replace("27.0", "27.1"))


def test_the_acceptance_mac_selects_its_manifest(monkeypatch):
    """The sysctl and sw_vers facts of the M1 Max select mac-m1-max through HostProvenance.summary."""
    from tools.qualification import adapters

    facts = {
        ("sw_vers", "-productVersion"): "27.0",
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M1 Max",
        ("sysctl", "-n", "hw.perflevel0.physicalcpu"): "8",
        ("sysctl", "-n", "hw.perflevel1.physicalcpu"): "2",
        ("sysctl", "-n", "hw.physicalcpu"): "10",
        ("sysctl", "-n", "hw.memsize"): str(64 * 2**30),
    }
    monkeypatch.setattr(adapters.host_platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        adapters.HostProvenance, "_run", staticmethod(lambda command, cwd=None: facts.get(tuple(command)))
    )
    selected = bench.HostManifest.select(bench.HostSummary.describe())
    assert selected is not None and selected.id == "mac-m1-max"
    embedded = selected.embed(logical_cores=10, instruction_counter="/usr/bin/time -l")
    assert embedded["file"] == "tools/qualification/hosts/mac-m1-max.toml"
    assert embedded["discrepancies"] == [] and embedded["manifest"] == table("mac-m1-max")


@pytest.mark.parametrize(
    ("summary", "selected"),
    [
        ("AMD EPYC 7763 64-Core Processor, 4 logical CPUs, 15.6 GiB, Linux 6.8.0-1021-azure", True),
        ("AMD EPYC 7763 64-Core Processor, 4 logical CPUs, 16 GiB, Linux 6.11.0-1015-azure", True),
        ("AMD EPYC 9V74 80-Core Processor, 4 logical CPUs, 15.6 GiB, Linux 6.8.0-1021-azure", False),
        ("AMD EPYC 7763 64-Core Processor, 2 logical CPUs, 7.8 GiB, Linux 6.8.0-1021-azure", False),
        ("AMD EPYC 7763 64-Core Processor, 4 logical CPUs, 15.6 GiB, Linux 6.8.0-1021-generic", False),
    ],
)
def test_the_github_runner_manifest_matches_only_its_cpu_and_shape(summary, selected):
    chosen = bench.HostManifest.select(summary)
    assert (chosen.id if chosen else None) == ("gh-ubuntu-24.04-x86_64" if selected else None)


def test_fractal_north_awaits_d7s_probe_and_matches_nothing():
    fractal = manifests()["fractal-north"]
    assert not fractal.recorded
    assert fractal.table["probe"] == ["nproc", "free -g", "lscpu", "nix --version"]
    assert fractal.table["requirements"] == {"min_logical_cores": 16, "min_memory_gib": 16}
    assert {"cpu", "memory_gib", "summary", "summary_pattern"}.isdisjoint(fractal.table)
    assert not fractal.matches("")


def test_every_recorded_manifest_meets_its_requirements_and_names_a_bench_counter():
    for manifest in manifests().values():
        assert manifest.table["instruction_counter"] in {f"{bench.TimeReport.TOOL} -l", "perf stat -e instructions:u"}
        assert manifest.table["toolchain"]["cc"] == bench.CC
    broken = table("gh-ubuntu-24.04-x86_64")
    broken["cpu"]["logical_cores"] = 2
    broken["cpu"]["physical_cores"] = 1
    assert bench.HostManifest.problems(broken, "gh-ubuntu-24.04-x86_64") == [
        "cpu.logical_cores is below requirements.min_logical_cores"
    ]


def drop(name: str):
    return lambda data: data.pop(name)


def put(name: str, value: object):
    return lambda data: data.__setitem__(name, value)


@pytest.mark.parametrize(
    ("base", "change", "problem"),
    [
        ("mac-m1-max", put("schema", 2), "schema must be 1"),
        ("mac-m1-max", put("schema", True), "schema must be 1"),
        ("mac-m1-max", put("schema", 1.0), "schema must be 1"),
        ("mac-m1-max", put("role", ["acceptance"]), "role must be one of"),
        ("mac-m1-max", put("architecture", {"arm64": 1}), "architecture must be one of"),
        ("mac-m1-max", put("instruction_counter", ["/usr/bin/time -l"]), "instruction_counter must be one of"),
        ("mac-m1-max", put("id", "mac"), "id must be the file name"),
        ("mac-m1-max", put("role", "dev"), "role must be one of"),
        ("mac-m1-max", put("architecture", "riscv64"), "architecture must be one of"),
        ("mac-m1-max", put("instruction_counter", "estimated"), "instruction_counter must be one of"),
        ("mac-m1-max", drop("source"), "source must say"),
        ("mac-m1-max", put("status", "maybe"), "status must be recorded or awaiting-probe"),
        ("mac-m1-max", drop("summary"), "exactly one of summary, summary_pattern"),
        ("mac-m1-max", put("summary_pattern", "Apple.*"), "exactly one of summary, summary_pattern"),
        ("gh-ubuntu-24.04-x86_64", put("summary_pattern", "AMD (EPYC"), "summary_pattern:"),
        ("mac-m1-max", drop("cpu"), "missing cpu"),
        ("mac-m1-max", lambda data: data["cpu"].pop("topology"), "cpu must hold exactly"),
        ("mac-m1-max", lambda data: data["cpu"].__setitem__("logical_cores", "10"), "cpu.logical_cores must be"),
        ("mac-m1-max", lambda data: data["cpu"].__setitem__("physical_cores", 12), "physical_cores exceeds"),
        ("mac-m1-max", put("memory_gib", 0), "memory_gib must be a positive integer"),
        ("mac-m1-max", put("probe", ["nproc"]), "unknown or misplaced field(s) probe"),
        ("mac-m1-max", put("notes", "x"), "unknown or misplaced field(s) notes"),
        ("mac-m1-max", put("requirements", {"min_cores": 4}), "requirements may hold only"),
        ("mac-m1-max", put("requirements", {"min_memory_gib": 128}), "memory_gib is below"),
        ("mac-m1-max", lambda data: data["toolchain"].pop("cc"), "toolchain must name at least cc, environment"),
        ("mac-m1-max", lambda data: data["toolchain"].__setitem__("nix", 2), "toolchain values must be text"),
        ("fractal-north", drop("probe"), "probe must list"),
        ("fractal-north", put("probe", ["nproc", ""]), "probe must list"),
        ("fractal-north", drop("requirements"), "needs the requirements"),
        ("fractal-north", put("cpu", {}), "unknown or misplaced field(s) cpu"),
        ("fractal-north", put("summary", "x"), "unknown or misplaced field(s) summary"),
    ],
)
def test_the_schema_rejects(base, change, problem):
    data = copy.deepcopy(table(base))
    change(data)
    problems = bench.HostManifest.problems(data, base)
    assert any(problem in line for line in problems), problems


def test_a_malformed_or_ambiguous_manifest_directory_is_an_error(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "x.toml").write_text("schema = [\n")
    with pytest.raises(ValueError, match=r"host manifest .*x\.toml"):
        bench.HostManifest.committed(broken)
    invalid = copy.deepcopy(table("mac-m1-max"))
    invalid["id"] = "other"
    write(tmp_path / "invalid", invalid)
    (tmp_path / "invalid" / "other.toml").rename(tmp_path / "invalid" / "mac.toml")
    with pytest.raises(ValueError, match="id must be the file name"):
        bench.HostManifest.select(MAC, tmp_path / "invalid")
    twins = tmp_path / "twins"
    write(twins, table("mac-m1-max"))
    second = copy.deepcopy(table("mac-m1-max"))
    del second["summary"]
    second |= {"id": "mac-twin", "summary_pattern": "Apple M1 Max, .*"}
    write(twins, second)
    with pytest.raises(ValueError, match="several manifests: mac-m1-max, mac-twin"):
        bench.HostManifest.select(MAC, twins)


def test_discrepancies_name_what_the_run_observed():
    mac = manifests()["mac-m1-max"]
    assert mac.discrepancies(logical_cores=10, instruction_counter="/usr/bin/time -l") == []
    assert mac.discrepancies(logical_cores=8, instruction_counter="unavailable on this host: perf is not on PATH") == [
        "8 logical CPUs, not the manifest's 10",
        "instruction counter is 'unavailable on this host: perf is not on PATH', not the manifest's '/usr/bin/time -l'",
    ]


# -- report.json and ingestion -------------------------------------------------


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


def this_host(tmp_path: Path) -> Path:
    """A manifest describing the machine running the test, as the probe would record it."""

    directory = tmp_path / "hosts"
    write(
        directory,
        {
            "schema": 1,
            "id": "this-host",
            "role": "x86_64-acceptance",
            "status": "recorded",
            "architecture": "arm64" if bench.platform.machine() in {"arm64", "aarch64"} else "x86_64",
            "summary": bench.HostSummary.describe(),
            "memory_gib": 16,
            "os": "the test host",
            "instruction_counter": "perf stat -e instructions:u",
            "source": "test_acceptance_hosts.py",
            "cpu": {"model": "test", "topology": "test", "logical_cores": os.cpu_count(), "physical_cores": 1},
            "toolchain": {"environment": "the test's", "cc": "clang"},
        },
    )
    return directory


def dry_run(workspace: Path, out: Path, btrcc: Path) -> dict[str, object]:
    arguments = ["--btrcc", str(btrcc), "--workspace", str(workspace), "--out", str(out)]
    configured = bench.BenchSettings.parse([*arguments, "--scenarios", "self-compile", "--dry-run"])
    bench.BudgetBench(configured).run()
    return json.loads((out / "report.json").read_text())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX stand-in compiler")
def test_a_dry_run_embeds_the_selected_manifest_and_ingests(workspace, tmp_path, btrcc, monkeypatch, capsys):
    from tools.qualification.cli import QualificationCommand
    from tools.qualification.store import QualificationStore

    monkeypatch.setattr(bench.HostManifest, "DIRECTORY", this_host(tmp_path))
    report = dry_run(workspace, tmp_path / "run", btrcc)
    embedded = report["provenance"]["host_manifest"]
    manifest = tmp_path / "hosts/this-host.toml"
    assert embedded["id"] == "this-host" and embedded["file"] == str(manifest)
    assert embedded["manifest"] == tomllib.loads(manifest.read_text())
    assert len(embedded["sha256"]) == 64
    counter = bench.TimeReport.instruction_counter()
    assert embedded["discrepancies"] == (
        []
        if counter == "perf stat -e instructions:u"
        else [f"instruction counter is {counter!r}, not the manifest's 'perf stat -e instructions:u'"]
    )

    store = QualificationStore(tmp_path / "qualification")
    path = tmp_path / "run/report.json"
    status = QualificationCommand(store).run(["ingest", "--run", "r1", "--budget-bench", str(path)])
    assert status == 0, capsys.readouterr().err
    kept = next((store.root / "raw" / "r1").iterdir())
    assert json.loads(kept.read_text())["provenance"]["host_manifest"] == embedded


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX stand-in compiler")
def test_an_undescribed_host_records_no_manifest_and_still_ingests(workspace, tmp_path, btrcc, monkeypatch, capsys):
    """A host no manifest describes (the cloud container) records null, and the CLI ingests its report."""
    from tools.qualification.cli import QualificationCommand
    from tools.qualification.store import QualificationStore

    others = tmp_path / "others"
    others.mkdir()
    summary = bench.HostSummary.describe()
    for manifest in bench.HostManifest.committed(HOSTS):
        if not manifest.matches(summary):
            (others / manifest.path.name).write_bytes(manifest.path.read_bytes())
    monkeypatch.setattr(bench.HostManifest, "DIRECTORY", others)
    report = dry_run(workspace, tmp_path / "run", btrcc)
    assert report["provenance"]["host_manifest"] is None
    capsys.readouterr()
    store = QualificationStore(tmp_path / "qualification")
    status = QualificationCommand(store).run(
        ["ingest", "--run", "r1", "--budget-bench", str(tmp_path / "run/report.json")]
    )
    assert status == 0, capsys.readouterr().err
    assert capsys.readouterr().out.startswith("wrote ")
