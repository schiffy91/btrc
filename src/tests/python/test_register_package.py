"""tools/register_package.py: a new stdlib package is named and counted everywhere by one command.

The first test holds the generator to what was done by hand: every package
already registered must come out of it unchanged. The others register a
package that does not exist, in a copy of the files the generator writes, and
check the result the way the inventory's own tests check the repository.
"""

from __future__ import annotations

import datetime
import re
import shutil
import tomllib
from pathlib import Path

import pytest

from tools.qualification.denominators import Denominator
from tools.qualification.report import QualificationReport
from tools.qualification.schema import TARGET_SLICES, LedgerDocument, Parity, SubjectKind
from tools.register_package import (
    INVENTORY,
    SUPPLEMENTS,
    TIMES,
    UI0_GROUPS,
    PackageRegistration,
    RegistrationError,
)

REPO = Path(__file__).resolve().parents[3]
WRITTEN = (
    "README.md",
    "src/stdlib/README.md",
    "docs/design/platform-parity.md",
    "tools/qualification/denominators.toml",
    "src/tests/python/test_qualification_ledger.py",
)


def plain_packages() -> list[str]:
    """The registered packages the generator can classify: plain BTRC, outside UI0's groups."""

    root = tomllib.loads((REPO / "src/stdlib/btrc.toml").read_text(encoding="utf-8"))
    names = []
    for group, dependency in root["dependencies"].items():
        directory = REPO / "src/stdlib" / dependency["path"]
        manifest = tomllib.loads((directory / "btrc.toml").read_text(encoding="utf-8"))
        includes = any(
            re.search(r"^\s*#include\b", source.read_text(encoding="utf-8"), re.MULTILINE)
            for source in directory.rglob("*.btrc")
        )
        if group not in UI0_GROUPS and not manifest.get("native") and not includes:
            names.append(group)
    return names


@pytest.mark.parametrize("name", plain_packages())
def test_a_registered_package_comes_out_unchanged(name):
    registration = PackageRegistration(REPO, name, None, "unused: its rows are there", write=False)
    assert registration.run() == []


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """The files a registration reads and writes, and a package nobody registered."""

    shutil.copytree(REPO / "src/stdlib", tmp_path / "src/stdlib")
    for relative in (*WRITTEN, INVENTORY, *(f"{INVENTORY.removesuffix('.toml')}/{name}" for name in SUPPLEMENTS)):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, tmp_path / relative)
    package = tmp_path / "src/stdlib/Probe"
    package.mkdir()
    (package / "btrc.toml").write_text(
        'manifest-version = 1\n\n[package]\nname = "btrc_stdlib_probe"\nexports = ["Probe", "ProbeCount"]\n'
    )
    (package / "Probe.btrc").write_text("import Library.Probe.ProbeCount;\n")
    (package / "ProbeCount.btrc").write_text("class ProbeCount {\n\tclass int of(int value) { return value + 1; }\n}\n")
    return tmp_path


def register(repo: Path, **changes) -> PackageRegistration:
    settings = {
        "summary": "A package nobody registered",
        "reason": "plain btrc; no OS includes",
        "today": datetime.date(2031, 2, 3),
        **changes,
    }
    return PackageRegistration(repo, "Probe", **settings)


def records(repo: Path):
    ledger = repo / INVENTORY
    return [
        *LedgerDocument.load(ledger),
        *(record for name in SUPPLEMENTS for record in LedgerDocument.load(ledger.with_suffix("") / name)),
    ]


def test_a_new_package_is_named_and_counted_everywhere(copy):
    before = {record.subject.id for record in records(copy)}
    changed = register(copy).run()
    assert set(changed) == {*WRITTEN, INVENTORY, "src/stdlib/btrc.toml", "src/stdlib/btrc.lock"}

    root = tomllib.loads((copy / "src/stdlib/btrc.toml").read_text(encoding="utf-8"))
    assert root["dependencies"]["Probe"] == {"path": "Probe"}
    assert list(root["dependencies"]) == sorted(root["dependencies"]), "the dependency is in its alphabetical place"
    assert "btrc_stdlib_probe" in (copy / "src/stdlib/btrc.lock").read_text(encoding="utf-8")

    ledger = records(copy)
    added = {record.subject.id for record in ledger} - before
    assert added == {"Library.Probe", "Library.Probe.ProbeCount"}
    rows = [record for record in ledger if record.subject.id in added]
    assert len(rows) == len(added) * len(TARGET_SLICES), "one row for each export on each slice"
    assert all(
        record.classification.parity is Parity.EQUIVALENT and record.evidence.reason == "plain btrc; no OS includes"
        for record in rows
    )

    # What test_platform_inventory asks of the repository: the frozen denominator is the ledger, with no drift.
    ids = sorted(
        {
            record.subject.id
            for record in LedgerDocument.load(copy / INVENTORY)
            if record.subject.kind is SubjectKind.OPERATION
        }
    )
    frozen = tomllib.loads((copy / "tools/qualification/denominators.toml").read_text(encoding="utf-8"))
    main = next(entry for entry in frozen["denominators"] if entry["source"] == {"ledger": INVENTORY})
    assert main["release"] == "p0-inventory-2031-02-03-probe"
    assert (main["ids"], main["slots"]) == (len(ids), len(ids) * len(TARGET_SLICES))
    assert main["sha256"] == Denominator.digest(ids)
    assert {"Library.Probe", "Library.Probe.ProbeCount"} <= set(ids)

    # And the totals platform-parity.md publishes are the ledger's.
    text = (copy / "docs/design/platform-parity.md").read_text(encoding="utf-8")
    slice_of = {target: name for name, target in TARGET_SLICES.items()}
    for row in QualificationReport(ledger).parity_rows():
        totals = " | ".join(str(row[key]) for key in ("slots", *(parity.value for parity in Parity)))
        assert f"| `{slice_of[(row['platform'], row['variant'])]}` | {totals} |" in text
    assert f"`p0-inventory-2031-02-03-probe`, {len(ids)} ids {TIMES} 6 slices = {len(ids) * 6} slots" in text

    pinned = (copy / "src/tests/python/test_qualification_ledger.py").read_text(encoding="utf-8")
    assert f'("p0-inventory-2031-02-03-probe", {len(ids)}, {len(ids) * 6}),' in pinned
    assert "| `Probe` | A package nobody registered |" in (copy / "README.md").read_text(encoding="utf-8")
    assert " Network/ Probe/ Realtime/ " in (copy / "README.md").read_text(encoding="utf-8")
    assert "`Probe`, `Realtime`" in (copy / "src/stdlib/README.md").read_text(encoding="utf-8")


def test_a_second_run_changes_nothing_and_a_check_says_so(copy):
    register(copy).run()
    assert register(copy).run() == []
    assert register(copy, write=False).run() == []


def test_a_check_names_what_it_would_change_and_writes_nothing(copy):
    untouched = {
        relative: (copy / relative).read_bytes()
        for relative in (*WRITTEN, INVENTORY, "src/stdlib/btrc.toml", "src/stdlib/btrc.lock")
    }
    changed = register(copy, write=False).run()
    assert {"src/stdlib/btrc.toml", INVENTORY, "README.md", "src/stdlib/README.md"} <= set(changed)
    assert untouched == {relative: (copy / relative).read_bytes() for relative in untouched}


@pytest.mark.parametrize(
    ("spoil", "words"),
    [
        (
            lambda package: (package / "ProbeCount.btrc").write_text("#include <stdio.h>\nclass ProbeCount {}\n"),
            "includes C",
        ),
        (
            lambda package: (package / "btrc.toml").write_text(
                (package / "btrc.toml").read_text() + '\n[[native.bindings]]\nmodule = "ProbeCount"\n'
            ),
            "native section",
        ),
        (lambda package: (package / "Probe.btrc").write_text("import ./ProbeCount.btrc;\n"), "declares nothing"),
        (lambda package: (package / "ProbeCount.btrc").unlink(), "has no source file"),
        (lambda package: shutil.rmtree(package), "is not there"),
    ],
)
def test_a_package_it_cannot_classify_is_refused_before_anything_is_written(copy, spoil, words):
    untouched = {
        relative: (copy / relative).read_bytes()
        for relative in (*WRITTEN, INVENTORY, "src/stdlib/btrc.toml", "src/stdlib/btrc.lock")
    }
    spoil(copy / "src/stdlib/Probe")
    with pytest.raises(RegistrationError, match=words):
        register(copy).run()
    assert untouched == {relative: (copy / relative).read_bytes() for relative in untouched}
