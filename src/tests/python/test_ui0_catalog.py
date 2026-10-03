"""UI0's focused source gate and unclassified operation/case ledger.

Parse the portable declarations with the compiler's parser, not line counts.
The frozen checklist plus explicit source amendments must describe the exact
current surface, including signatures/defaults and interface inheritance.
The original release still declares 162 operations and 47 acceptance cases;
later source changes must never silently shrink or expand its denominator.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import ClassDecl, InterfaceDecl, MethodDecl
from tools.qualification.denominators import Denominator, DenominatorManifest
from tools.qualification.report import QualificationReport
from tools.qualification.schema import Frontend, LedgerDocument, Platform, Subject, SubjectKind

REPO = Path(__file__).resolve().parents[3]
GUI = REPO / "src/stdlib/GUI"
CHECKLIST = REPO / "docs/design/native-ui-api-inventory.md"
ROADMAP = REPO / "docs/design/native-ui-parity.md"
AMENDMENTS = REPO / "docs/design/ui0-source-amendments.toml"
CATALOG = REPO / "docs/design/native-ui-catalog.toml"
KINDS = (SubjectKind.UI_OPERATION, SubjectKind.UI_CASE)
PLATFORMS = (Platform.MACOS, Platform.LINUX, Platform.WINDOWS, Platform.IOS, Platform.ANDROID)
FRONTENDS = (Frontend.REFERENCE, Frontend.SELFHOST)
OPERATION_ROW = re.compile(r"^\| `([A-Za-z]\w*\.[A-Za-z]\w*)` \| `([^`]+)` \|$", re.MULTILINE)
CASE_ROW = re.compile(r"^\| (E\d{2}) — ([^|]+) \|", re.MULTILINE)


def parse(source):
    return Parser(Lexer(source).tokenize()).parse().declarations


def surface(sources):
    """Files, declaring owners (with parents), and directly declared methods.

    Keep overloads visible as duplicate IDs rather than overwriting one in a
    dict. Constructors/fields or other new facade members need explicit review.
    Method bodies and source coordinates are not contract changes; AST equality
    already excludes coordinates, while retaining types, defaults and keep.
    """
    owners, methods = {}, {}
    for filename, source in sorted(sources.items()):
        for owner in parse(source):
            if not isinstance(owner, InterfaceDecl) and not (isinstance(owner, ClassDecl) and owner.name == "GUI"):
                continue
            assert owner.name not in owners, f"duplicate owner: {owner.name}"
            owners[owner.name] = (filename, owner.parent, tuple(owner.generic_params))
            declarations = owner.methods if isinstance(owner, InterfaceDecl) else owner.members
            for method in declarations:
                identifier = f"{owner.name}.{method.name}"
                assert identifier not in methods, f"duplicate operation: {identifier}; split overloaded IDs explicitly"
                if isinstance(owner, ClassDecl):
                    assert isinstance(method, MethodDecl), f"uncataloged facade member: {identifier}"
                    method = replace(method, body=None)
                methods[identifier] = method
    return set(sources), owners, methods


def sources():
    return {path.name: path.read_text(encoding="utf-8") for path in [*sorted(GUI.glob("I*.btrc")), GUI / "GUI.btrc"]}


def frozen_sources():
    """The existing reviewable checklist is the frozen declaration catalog."""
    text = CHECKLIST.read_text(encoding="utf-8")
    by_file = {}
    for section in re.split(r"^## ", text, flags=re.MULTILINE):
        rows = OPERATION_ROW.findall(section)
        if not rows:
            continue
        source = re.search(r"^Source: \[([^]]+\.btrc)\]", section, re.MULTILINE)
        assert source, f"no source for {rows[0][0]}"
        owner = rows[0][0].split(".")[0]
        assert all(identifier.split(".")[0] == owner for identifier, _ in rows)
        parent = re.search(r"Extends `([^`]+)`", section)
        if owner == "GUI":
            declaration = "class GUI {" + "\n".join(f"{signature} {{}}" for _, signature in rows) + "}"
        else:
            inheritance = f" extends {parent[1]}" if parent else ""
            declaration = f"interface {owner}{inheritance} {{" + "\n".join(signature for _, signature in rows) + "}"
        parsed = surface({source[1]: declaration})[2]
        assert set(parsed) == {identifier for identifier, _ in rows}, "catalog ID differs from its declaration"
        by_file.setdefault(source[1], []).append(declaration)
    return {filename: "\n".join(declarations) for filename, declarations in by_file.items()}


def amendments():
    return tomllib.loads(AMENDMENTS.read_text(encoding="utf-8"))


def expected_surface():
    files, owners, methods = surface(frozen_sources())
    changes = amendments()
    for addition in changes["additions"]:
        assert addition["decision"]
        declaration = f"interface {addition['owner']} {{" + "\n".join(addition["declarations"]) + "}"
        added_files, added_owners, added = surface({addition["source"]: declaration})
        for name, definition in added_owners.items():
            if name in owners:
                assert owners[name] == definition, "an addition must preserve the declaring owner"
            else:
                owners[name] = definition
        files.update(added_files)
        assert not methods.keys() & added.keys(), "an addition already exists in the frozen catalog"
        methods.update(added)
    for removal in changes["removals"]:
        assert removal["decision"] and removal["reason"]
        assert removal["replacement"] in methods
        assert removal["id"] in methods, "a removal must name a frozen operation exactly once"
        del methods[removal["id"]]
    return files, owners, methods


def verify_surface(actual_sources):
    actual_files, actual_owners, actual_methods = surface(actual_sources)
    expected_files, expected_owners, expected_methods = expected_surface()
    assert actual_files == expected_files, "portable GUI file drift: update the UI0 catalog"
    assert actual_owners == expected_owners, "portable GUI owner/inheritance drift: update the UI0 catalog"
    added = sorted(actual_methods.keys() - expected_methods.keys())
    removed = sorted(expected_methods.keys() - actual_methods.keys())
    changed = sorted(
        name
        for name in actual_methods.keys() & expected_methods.keys()
        if actual_methods[name] != expected_methods[name]
    )
    assert not (added or removed or changed), (
        f"portable GUI declaration drift: added={added}, removed={removed}, changed={changed}; update the UI0 catalog"
    )


def source_ids():
    """Recompute frozen IDs from current source plus the explicit release delta."""
    verify_surface(sources())
    current = set(surface(sources())[2])
    frozen = set(surface(frozen_sources())[2])
    additions = set(expected_surface()[2]) - frozen
    removals = {item["id"] for item in amendments()["removals"]}
    cases = [identifier for identifier, _ in CASE_ROW.findall(ROADMAP.read_text(encoding="utf-8"))]
    assert len(cases) == len(set(cases)), "duplicate acceptance case in roadmap"
    return {SubjectKind.UI_OPERATION: (current - additions) | removals, SubjectKind.UI_CASE: set(cases)}


def verify_catalog(records):
    denominators = DenominatorManifest.load().by_kind()
    counts = Counter(record.subject.key for record in records)
    expected = set()
    for kind, identifiers in source_ids().items():
        denominator = denominators[kind]
        assert denominator.drift() == []
        assert denominator.release == amendments()["release"]
        assert denominator.platforms == PLATFORMS and denominator.frontends == FRONTENDS
        assert len(identifiers) == denominator.frozen_ids
        assert Denominator.digest(identifiers) == denominator.frozen_digest
        slots = {
            Subject(kind=kind, id=identifier, platform=platform, frontend=frontend).key
            for identifier in identifiers
            for platform in PLATFORMS
            for frontend in FRONTENDS
        }
        assert len(slots) == denominator.frozen_slots
        expected.update(slots)
    assert counts.keys() == expected, (
        f"catalog slot drift: missing={sorted(expected - counts.keys())}, extra={sorted(counts.keys() - expected)}"
    )
    assert all(count == 1 for count in counts.values()), "duplicate catalog slot"


def test_portable_gui_surface_matches_the_catalog():
    verify_surface(sources())


def test_surface_counts_explain_the_frozen_release_delta():
    files, owners, methods = surface(sources())
    frozen_files, frozen_owners, frozen_methods = surface(frozen_sources())
    assert (len(frozen_files) - 1, len(frozen_owners) - 1, len(frozen_methods)) == (19, 24, 162)
    counts = amendments()["current"]
    assert (len(files) - 1, len(owners) - 1) == (counts["interface_files"], counts["interfaces"]) == (20, 25)
    assert sum(not name.startswith("GUI.") for name in methods) == counts["interface_declarations"] == 152
    assert sum(name.startswith("GUI.") for name in methods) == counts["facade_declarations"] == 26
    assert len(methods.keys() - frozen_methods.keys()) == 17
    assert frozen_methods.keys() - methods.keys() == {"GUI.rasterText"}


@pytest.mark.parametrize(
    ("before", "after", "diagnostic"),
    [
        ("bool isOpen();", "bool isOpen(); void ui0Dummy();", r"added=.*IWindow.ui0Dummy"),
        ("bool isOpen();", "", r"removed=.*IWindow.isOpen"),
        ("bool isOpen();", "bool renamed();", r"added=.*IWindow.renamed.*removed=.*IWindow.isOpen"),
        ("bool isOpen();", "int isOpen();", r"changed=.*IWindow.isOpen"),
        ("bool isOpen();", "bool isOpen(); bool isOpen(int flag);", "duplicate operation"),
    ],
)
def test_focused_gate_rejects_declaration_drift(before, after, diagnostic):
    mutated = sources()
    assert before in mutated["IWindow.btrc"]
    mutated["IWindow.btrc"] = mutated["IWindow.btrc"].replace(before, after, 1)
    with pytest.raises(AssertionError, match=diagnostic):
        verify_surface(mutated)


def test_focused_gate_rejects_default_and_inheritance_drift():
    mutated = sources()
    mutated["GUI.btrc"] = mutated["GUI.btrc"].replace("workCapacity = 256", "workCapacity = 257")
    with pytest.raises(AssertionError, match=r"changed=.*GUI.initialize"):
        verify_surface(mutated)
    mutated = sources()
    mutated["IButton.btrc"] = mutated["IButton.btrc"].replace("extends IView", "extends IContainer")
    with pytest.raises(AssertionError, match="inheritance drift"):
        verify_surface(mutated)


def test_focused_gate_ignores_comments_and_method_bodies():
    mutated = sources()
    mutated["IWindow.btrc"] += "\n// interface Fake { void ui0Dummy(); }\n"
    mutated["GUI.btrc"] = mutated["GUI.btrc"].replace('"GUI is already initialized"', '"changed diagnostic"')
    verify_surface(mutated)


@pytest.mark.parametrize("mutation", ["added-file", "removed-file", "added-interface"])
def test_focused_gate_rejects_file_and_owner_drift(mutation):
    mutated = sources()
    if mutation == "added-file":
        mutated["IExtra.btrc"] = "interface IExtra {}"
    elif mutation == "removed-file":
        del mutated["IFontFace.btrc"]
    else:
        mutated["IWindow.btrc"] += "\ninterface IExtra {}\n"
    with pytest.raises(AssertionError, match=r"portable GUI (file|owner/inheritance) drift"):
        verify_surface(mutated)


def test_catalog_covers_the_recomputed_frozen_denominators():
    records = LedgerDocument.load(CATALOG)
    verify_catalog(records)
    assert Counter(record.subject.kind for record in records) == {
        SubjectKind.UI_OPERATION: 1620,
        SubjectKind.UI_CASE: 470,
    }


@pytest.mark.parametrize("mutation", ["added", "removed", "renamed"])
def test_case_source_drift_cannot_change_the_frozen_denominator(tmp_path, monkeypatch, mutation):
    text = ROADMAP.read_text(encoding="utf-8")
    last = next(line for line in text.splitlines() if line.startswith("| E47 —"))
    changed = last.replace("E47", "E48", 1)
    if mutation == "added":
        text += f"\n{changed}\n"
    elif mutation == "removed":
        text = text.replace(last, "", 1)
    else:
        text = text.replace(last, changed, 1)
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text(text, encoding="utf-8")
    monkeypatch.setitem(globals(), "ROADMAP", roadmap)
    with pytest.raises(AssertionError):
        verify_catalog(LedgerDocument.load(CATALOG))


def test_unclassified_slots_remain_unrecorded_in_the_report():
    # Later fan-out may classify real slots. Removing evidence must still retain
    # every declared slot; absence must never be promoted to a passing outcome.
    records = [
        replace(record, classification=None, evidence=None, measurement=None) for record in LedgerDocument.load(CATALOG)
    ]
    manifest = DenominatorManifest(
        [denominator for denominator in DenominatorManifest.load().denominators if denominator.kind in KINDS]
    )
    report = QualificationReport(records, manifest)
    assert report.problems() == []
    assert all(row["missing_slots"] == 0 and row["undeclared"] == 0 for row in report.denominator_rows())
    assert sum(row["unrecorded"] for row in report.evidence_rows()) == 2090
    assert all(row["passed"] == 0 and row["unavailable"] == 0 for row in report.evidence_rows())


@pytest.mark.parametrize("mutation", ["deleted", "duplicated", "wrong-frontend", "renamed"])
def test_catalog_rejects_missing_extra_and_duplicate_slots(mutation):
    records = LedgerDocument.load(CATALOG)
    if mutation == "deleted":
        records.pop()
    elif mutation == "duplicated":
        records.append(records[0])
    else:
        subject = records[0].subject
        changed = (
            replace(subject, frontend=None)
            if mutation == "wrong-frontend"
            else replace(subject, id="Uncataloged.operation")
        )
        records[0] = replace(records[0], subject=changed)
    with pytest.raises(AssertionError, match="catalog slot"):
        verify_catalog(records)
