"""UI0's focused source gate and unclassified operation/case ledger.

Parse the portable declarations with the compiler's parser, not line counts.
The frozen checklist plus explicit source amendments must describe the exact
current surface, including signatures/defaults and interface inheritance.
The original release still declares 162 operations and 47 acceptance cases;
later source changes must never silently shrink or expand its denominator.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
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
from tools.qualification.schema import Frontend, LedgerDocument, LedgerSchemaError, Platform, Subject, SubjectKind
from tools.qualification.ui_catalog import CatalogAmendments, UICatalog

REPO = Path(__file__).resolve().parents[3]
GUI = REPO / "src/stdlib/GUI"
CHECKLIST = REPO / "docs/design/native-ui-api-inventory.md"
ROADMAP = REPO / "docs/design/native-ui-parity.md"
AMENDMENTS = REPO / "docs/design/ui0-source-amendments.toml"
CATALOG = REPO / "docs/design/native-ui-catalog.toml"
SHARDS = REPO / "docs/design/native-ui-catalog"
KINDS = (SubjectKind.UI_OPERATION, SubjectKind.UI_CASE, SubjectKind.FAMILY_CELL)
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
    return CatalogAmendments(REPO, SHARDS).data


def expected_surface():
    files, owners, methods = surface(frozen_sources())
    changes = amendments()
    for addition in changes["additions"]:
        assert addition["decision"]
        declaration = CatalogAmendments.declaration(addition)
        added_files, added_owners, added = surface({addition["source"]: declaration})
        for name, definition in added_owners.items():
            if name in owners:
                assert owners[name] == definition, "an addition must preserve the declaring owner"
            else:
                owners[name] = definition
        files.update(added_files)
        assert not methods.keys() & added.keys(), "an addition already exists in the frozen catalog"
        methods.update(added)
    for change in changes.get("changes", []):
        identifier = change["id"]
        owner = identifier.split(".")[0]
        filename, parent, _ = owners[owner]
        definitions = []
        for signature in (change["frozen"], change["current"]):
            addition = {"owner": owner, "declarations": [signature], "parent": parent}
            definitions.append(surface({filename: CatalogAmendments.declaration(addition)})[2])
        assert definitions[0].keys() == definitions[1].keys() == {identifier}
        assert methods[identifier] == definitions[0][identifier], "changed frozen signature does not match"
        assert change["decision"]
        methods[identifier] = definitions[1][identifier]
    for removal in changes["removals"]:
        assert removal["decision"] and removal["reason"]
        if removal.get("replacement"):
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
    families = DenominatorManifest.load().by_kind()[SubjectKind.FAMILY_CELL].ids
    return {
        SubjectKind.UI_OPERATION: (current - additions) | removals,
        SubjectKind.UI_CASE: set(cases),
        SubjectKind.FAMILY_CELL: set(families),
    }


def verify_catalog(records):
    denominators = DenominatorManifest.load().by_kind()
    counts = Counter(record.subject.key for record in records)
    expected = set()
    for kind, identifiers in source_ids().items():
        denominator = denominators[kind]
        assert denominator.drift() == []
        assert denominator.release == amendments()["release"]
        frontends = (None,) if kind is SubjectKind.FAMILY_CELL else FRONTENDS
        assert denominator.platforms == PLATFORMS
        assert denominator.frontends == (() if kind is SubjectKind.FAMILY_CELL else FRONTENDS)
        assert len(identifiers) == denominator.frozen_ids
        assert Denominator.digest(identifiers) == denominator.frozen_digest
        slots = {
            Subject(kind=kind, id=identifier, platform=platform, frontend=frontend).key
            for identifier in identifiers
            for platform in PLATFORMS
            for frontend in frontends
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
    denominator = DenominatorManifest.load().by_kind()[SubjectKind.UI_OPERATION]
    assert len(frozen_methods) == denominator.frozen_ids
    counts = amendments()["current"]
    assert (len(files) - 1, len(owners) - 1) == (counts["interface_files"], counts["interfaces"])
    assert sum(not name.startswith("GUI.") for name in methods) == counts["interface_declarations"]
    assert sum(name.startswith("GUI.") for name in methods) == counts["facade_declarations"]
    added = {
        identifier
        for addition in amendments()["additions"]
        for identifier in surface({addition["source"]: CatalogAmendments.declaration(addition)})[2]
    }
    assert methods.keys() - frozen_methods.keys() == added
    assert frozen_methods.keys() - methods.keys() == {row["id"] for row in amendments()["removals"]}
    assert len(files) == len(frozen_files | {row["source"] for row in amendments()["additions"]})
    assert len(owners) == len(frozen_owners.keys() | {row["owner"] for row in amendments()["additions"]})


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
    records = UICatalog().frozen_records
    verify_catalog(records)
    assert Counter(record.subject.kind for record in records) == {
        SubjectKind.UI_OPERATION: 1620,
        SubjectKind.UI_CASE: 470,
        SubjectKind.FAMILY_CELL: 300,
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
        verify_catalog(UICatalog().frozen_records)


def test_unclassified_slots_remain_unrecorded_in_the_report():
    # Later fan-out may classify real slots. Removing evidence must still retain
    # every declared slot; absence must never be promoted to a passing outcome.
    records = [
        replace(record, classification=None, evidence=None, measurement=None) for record in UICatalog().frozen_records
    ]
    manifest = DenominatorManifest(
        [denominator for denominator in DenominatorManifest.load().denominators if denominator.kind in KINDS]
    )
    report = QualificationReport(records, manifest)
    assert report.problems() == []
    assert all(row["missing_slots"] == 0 and row["undeclared"] == 0 for row in report.denominator_rows())
    assert sum(row["unrecorded"] for row in report.evidence_rows()) == sum(
        denominator.frozen_slots for denominator in manifest.denominators
    )
    assert all(row["passed"] == 0 and row["unavailable"] == 0 for row in report.evidence_rows())


@pytest.mark.parametrize("mutation", ["deleted", "duplicated", "wrong-frontend", "renamed"])
def test_catalog_rejects_missing_extra_and_duplicate_slots(mutation):
    records = UICatalog().frozen_records
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


def exported_gui_sources(root=GUI):
    """Resolve exported modules, including exported subpackages, from manifests."""
    exports = tomllib.loads((root / "btrc.toml").read_text(encoding="utf-8"))["package"]["exports"]
    result = {}
    for module in exports:
        path = root.joinpath(*module.split("."))
        if path.with_suffix(".btrc").is_file() and not path.name.startswith("I"):
            result[module] = path.with_suffix(".btrc").read_text(encoding="utf-8")
        elif path.is_dir():
            result.update({f"{module}.{name}": value for name, value in exported_gui_sources(path).items()})
    return result


def verify_outside_interfaces(exported_sources, exceptions):
    discovered = {
        f"{module}.{declaration.name}"
        for module, source in exported_sources.items()
        for declaration in parse(source)
        if isinstance(declaration, InterfaceDecl)
    }
    recorded = {row["id"] for row in exceptions}
    assert len(recorded) == len(exceptions), "duplicate outside interface exception"
    assert all(row["decision"] and row["reason"] for row in exceptions)
    assert discovered == recorded, (
        f"outside interface drift: added={discovered - recorded}, removed={recorded - discovered}"
    )


def test_exported_gui_interfaces_outside_the_filename_scope_are_explicit():
    verify_outside_interfaces(exported_gui_sources(), amendments()["outside_interfaces"])


@pytest.mark.parametrize("mutation", ["new-interface", "removed-exception", "stale-exception"])
def test_outside_interface_guard_rejects_unreviewed_exports(mutation):
    exported = exported_gui_sources()
    exceptions = [dict(row) for row in amendments()["outside_interfaces"]]
    if mutation == "new-interface":
        exported["Font"] += "\ninterface IUnreviewedFont {}\n"
    elif mutation == "removed-exception":
        exceptions.pop()
    else:
        exceptions.append({"id": "Font.INotExported", "decision": "fixture", "reason": "fixture"})
    with pytest.raises(AssertionError, match="outside interface drift"):
        verify_outside_interfaces(exported, exceptions)


def inline_toml(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(key)} = {inline_toml(item)}" for key, item in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(inline_toml(item) for item in value) + "]"
    return json.dumps(value)


def write_shard(directory, relative, **document):
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = document.pop("schema", "btrc.qualification.ledger/1")
    if schema == "btrc.qualification.ledger/1" and not relative.startswith("amendments/"):
        document.setdefault(
            "provenance", {"btrc_revision": "fixture-revision", "recorded_at": "2026-10-02T12:00:00+00:00"}
        )
        for record in document.get("records", []):
            record["provenance"] = {**document["provenance"], **record.get("provenance", {})}
    path.write_text(
        f"schema = {json.dumps(schema)}\n"
        + "\n".join(f"{key} = {inline_toml(value)}" for key, value in document.items()),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def catalog_directory(tmp_path):
    directory = tmp_path / "catalog"
    directory.mkdir()
    shutil.copy(SHARDS / "families.toml", directory / "families.toml")
    return directory


def operation(identifier="IWindow.isOpen", *, classification=None, evidence=None, **subject):
    record = {
        "subject": {"kind": "ui-operation", "id": identifier, "platform": "linux", "frontend": "reference", **subject}
    }
    if classification is not None:
        record["classification"] = classification
    if evidence is not None:
        record["evidence"] = evidence
    return record


def classified_operation(identifier="IWindow.isOpen"):
    return operation(
        identifier,
        classification={
            "implementation": "partial",
            "regression": ["src/tests/python/test_ui0_catalog.py::test_fixture"],
        },
        evidence={"status": "implemented-unverified"},
    )


@pytest.mark.parametrize(
    "relative",
    [
        "typo.toml",
        "operations/README.txt",
        "other/nested.toml",
        "surface/Unknown.toml",
        "evidence/Uppercase.toml",
        "amendments/UPPER.toml",
    ],
)
def test_shard_layout_rejects_unknown_paths(catalog_directory, relative):
    write_shard(catalog_directory, relative, records=[])
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


@pytest.mark.parametrize(
    "mutation", ["foreign-owner", "unknown-id", "variant", "retired", "wrong-kind", "duplicate-record"]
)
def test_operation_admission_rejects_invalid_slots(catalog_directory, mutation):
    record = classified_operation()
    if mutation == "foreign-owner":
        record["subject"]["id"] = "IButton.setTitle"
    elif mutation == "unknown-id":
        record["subject"]["id"] = "IWindow.notDeclared"
    elif mutation == "variant":
        record["subject"].update(platform="ios", variant="simulator")
    elif mutation == "retired":
        record["subject"]["id"] = "GUI.rasterText"
    elif mutation == "wrong-kind":
        record["subject"].update(kind="ui-case", id="E01")
    filename = "GUI" if mutation == "retired" else "IWindow"
    write_shard(
        catalog_directory,
        f"operations/{filename}.toml",
        records=[record] * (2 if mutation == "duplicate-record" else 1),
    )
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


@pytest.mark.parametrize("mutation", ["out-of-range", "overlap", "reversed"])
def test_case_shards_reject_bad_ranges(catalog_directory, mutation):
    record = operation("E25", kind="ui-case")
    if mutation == "out-of-range":
        write_shard(catalog_directory, "cases/E01-E24.toml", records=[record])
    elif mutation == "overlap":
        write_shard(catalog_directory, "cases/E01-E25.toml", records=[])
        write_shard(catalog_directory, "cases/E25-E47.toml", records=[record])
    else:
        write_shard(catalog_directory, "cases/E47-E25.toml", records=[record])
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


@pytest.mark.parametrize("mutation", ["evidence-classification", "classification-twice"])
def test_evidence_cannot_reclassify_an_owner_slot(catalog_directory, mutation):
    record = classified_operation()
    if mutation == "classification-twice":
        write_shard(catalog_directory, "operations/IWindow.toml", records=[record])
    write_shard(catalog_directory, "evidence/ui1-linux.toml", records=[record])
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


@pytest.mark.parametrize("mutation", ["deleted", "duplicate", "pending-in-seed"])
def test_seed_slot_set_is_immutable(catalog_directory, tmp_path, mutation):
    document = tomllib.loads(CATALOG.read_text(encoding="utf-8"))
    if mutation == "deleted":
        document["records"].pop()
    elif mutation == "duplicate":
        document["records"].append(document["records"][0])
    else:
        document["records"].append(operation("IApplication.createButton"))
    seed = write_shard(tmp_path, "seed.toml", **document)
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory, seed=seed)


def test_pending_and_retired_partitions_do_not_change_frozen_coverage():
    catalog = UICatalog()
    verify_catalog(catalog.frozen_records)
    pending = {record.subject.id for record in catalog.pending_records}
    assert pending == CatalogAmendments(REPO, SHARDS).added_ids()
    assert len(catalog.pending_records) == len(pending) * len(PLATFORMS) * len(FRONTENDS)
    assert {record.subject.id for record in catalog.retired_records} == {row["id"] for row in amendments()["removals"]}
    frozen = {record.subject.key for record in catalog.frozen_records}
    assert not frozen.intersection(record.subject.key for record in catalog.pending_records)
    assert {record.subject.key for record in catalog.retired_records} <= frozen
    assert not {record.subject.key for record in catalog.retired_records}.intersection(
        record.subject.key for record in catalog.unclassified()
    )
    assert catalog.problems() == []


@pytest.mark.parametrize("stale", [False, True])
def test_last_evidence_wins_without_erasing_classification(catalog_directory, stale):
    original = classified_operation()
    original["provenance"] = {"recorded_at": "2026-10-02T12:00:00+00:00", "runner": "linux-devcontainer"}
    write_shard(catalog_directory, "operations/IWindow.toml", records=[original])
    replacement = operation(
        evidence={"status": "passed", "observed": "passed"}, classification={"note": "UI1 fixture proof"}
    )
    replacement["provenance"] = {
        "recorded_at": "2026-10-01T12:00:00+00:00" if stale else "2026-10-03T12:00:00+00:00",
        "runner": "linux-devcontainer",
    }
    write_shard(catalog_directory, "evidence/ui1-linux.toml", records=[replacement])
    catalog = UICatalog(directory=catalog_directory)
    merged = next(
        record
        for record in catalog.records
        if record.subject.key == ("ui-operation", "IWindow.isOpen", "linux", "reference", "")
    )
    assert merged.evidence.status == "passed"
    assert merged.classification.implementation == "partial"
    assert merged.classification.note == "UI1 fixture proof"
    assert merged.provenance.recorded_at == replacement["provenance"]["recorded_at"]
    assert bool(catalog.problems()) == stale
    if stale:
        assert any("stale" in problem.lower() for problem in catalog.problems())


def surface_font(**overrides):
    return {
        "module": "GUI.Font",
        "symbol": "Font",
        "kind": "class",
        "disposition": "family",
        "links": ["N44", "UI5"],
        "operations": ["Font.pendingMeasure"],
        **overrides,
    }


def test_exported_surface_can_admit_a_new_owner_and_optional_shards(catalog_directory):
    write_shard(
        catalog_directory, "surface/GUIModules.toml", schema="btrc.ui-catalog.surface/1", symbols=[surface_font()]
    )
    write_shard(catalog_directory, "operations/Font.toml", records=[classified_operation("Font.pendingMeasure")])
    write_shard(
        catalog_directory,
        "evidence/ui1-macos.toml",
        records=[
            {
                "subject": {
                    "kind": "test",
                    "id": "src/tests/python/test_ui0_catalog.py::test_fixture",
                    "platform": "macos",
                    "frontend": "reference",
                },
                "evidence": {"status": "passed"},
                "provenance": {"runner": "macos-hosted", "recorded_at": "2026-10-03T12:00:00+00:00"},
            }
        ],
    )
    (catalog_directory / "hosts.toml").write_text("# Validated by the host packet\n", encoding="utf-8")
    catalog = UICatalog(directory=catalog_directory)
    assert len([row for row in catalog.pending_records if row.subject.id == "Font.pendingMeasure"]) == 10
    assert any(row.subject.kind is SubjectKind.TEST for row in catalog.records)
    assert catalog.problems() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"module": "GUI.NotExported"},
        {"symbol": "NotExported"},
        {"kind": "interface"},
        {"disposition": "legacy", "reason": "Retained only for compatibility"},
        {"disposition": "out-of-scope", "operations": []},
        {"unexpected": "field"},
    ],
)
def test_surface_rejects_unexported_or_invalid_proposals(catalog_directory, overrides):
    write_shard(
        catalog_directory,
        "surface/GUIModules.toml",
        schema="btrc.ui-catalog.surface/1",
        symbols=[surface_font(**overrides)],
    )
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


def test_two_packets_compact_shards_merge_and_expand_both_frontends(catalog_directory):
    write_shard(
        catalog_directory,
        "operations/IWindow.toml",
        operations=[
            {
                "id": "IWindow.isOpen",
                "implementation": "partial",
                "links": ["N02", "UI1"],
                "linux": {"evidence": {"status": "implemented-unverified"}},
                "macos": {
                    "reference": {"evidence": {"status": "passed"}},
                    "selfhost": {"evidence": {"status": "implemented-unverified"}},
                },
            }
        ],
    )
    write_shard(
        catalog_directory,
        "cases/E01-E24.toml",
        cases=[
            {
                "id": "E01",
                "implementation": "missing",
                "parity": "missing",
                "android": {
                    "evidence": {"status": "unavailable", "covered_by": [], "reason": "No Android shell runner"}
                },
            }
        ],
    )
    catalog = UICatalog(directory=catalog_directory)
    classified = [
        row
        for row in catalog.records
        if row.subject.kind is not SubjectKind.FAMILY_CELL
        and row.classification is not None
        and not catalog.retired(row)
    ]
    assert len(classified) == 6
    assert Counter(row.evidence.status for row in classified) == {
        "implemented-unverified": 3,
        "passed": 1,
        "unavailable": 2,
    }
    assert all(row.subject.frontend in FRONTENDS for row in classified)
    assert catalog.problems() == []
    # Verbose round-trip exercises the actual ledger representation, not a second expander.
    (catalog_directory / "operations/IWindow.toml").unlink()
    (catalog_directory / "cases/E01-E24.toml").unlink()
    for kind, filename in (
        (SubjectKind.UI_OPERATION, "operations/IWindow.toml"),
        (SubjectKind.UI_CASE, "cases/E01-E24.toml"),
    ):
        write_shard(
            catalog_directory, filename, records=[row.to_mapping() for row in classified if row.subject.kind is kind]
        )
    assert UICatalog(directory=catalog_directory).records == catalog.records


@pytest.mark.parametrize(
    "cell",
    [
        {"evidence": {"status": "passed", "observed": "failed"}},
        {"evidence": {"status": "passed", "covered_by": ["macos"]}},
        {"implementation": "missing", "evidence": {"status": "passed"}},
        {"evidence": {"status": "unrecognized"}},
    ],
)
def test_compact_cells_enforce_ledger_cross_field_invariants(catalog_directory, cell):
    write_shard(catalog_directory, "operations/IWindow.toml", operations=[{"id": "IWindow.isOpen", "linux": cell}])
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


def test_compact_id_cannot_be_split_across_repeated_tables(catalog_directory):
    write_shard(
        catalog_directory,
        "operations/IWindow.toml",
        operations=[
            {"id": "IWindow.isOpen", "linux": {"implementation": "partial"}},
            {"id": "IWindow.isOpen", "macos": {"implementation": "partial"}},
        ],
    )
    with pytest.raises(LedgerSchemaError, match="one table per id"):
        UICatalog(directory=catalog_directory)


# N01..N60 in macOS/Linux/Windows/iOS/Android order. This is the frozen
# 2026-09-21 source matrix, independent of the evolving roadmap prose.
FAMILY_SEED = [
    "PPMMM",
    "PPMMM",
    "PPMMM",
    "PPMMM",
    "PPMMM",
    "PCMMM",
    "PPMMM",
    "PPMMM",
    "MMMMM",
    "PCMMM",
    "PCMMM",
    "MMMMM",
    "MMMMM",
    "PCMMM",
    "PCMMM",
    "MMMMM",
    "MMMMM",
    "PCMMM",
    "PCMMM",
    "PPMMM",
    "PCMMM",
    "MMMMM",
    "PCMMM",
    "PCMMM",
    "MMMMM",
    "PCMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "PCMMM",
    "PPMMM",
    "PPMMM",
    "PCMMM",
    "MMMMM",
    "MMMMM",
    "PMMMM",
    "MMMMM",
    "PMMMM",
    "PMMMM",
    "PCMMM",
    "PCMMM",
    "MMMMM",
    "PPMMM",
    "PPMMM",
    "PPMMM",
    "PPMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "PPMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
    "MMMMM",
]
FAMILY_SEED_SHA256 = "e8c9c9abac253b9efcfa61d236b957a12fc6e9fc28c0d96fec7cd01484a91157"


def verify_family_seed(records):
    assert hashlib.sha256(("\n".join(FAMILY_SEED) + "\n").encode()).hexdigest() == FAMILY_SEED_SHA256
    expected = {
        (f"N{index:02}", platform): {"P": "partial", "C": "custom", "M": "missing"}[value]
        for index, row in enumerate(FAMILY_SEED, start=1)
        for platform, value in zip(PLATFORMS, row, strict=True)
    }
    assert len(records) == len(expected) == 300
    assert {(row.subject.id, row.subject.platform) for row in records} == expected.keys()
    for row in records:
        assert row.subject.kind is SubjectKind.FAMILY_CELL
        assert row.subject.frontend is None
        implementation = row.classification.implementation
        if implementation != expected[row.subject.id, row.subject.platform]:
            assert row.classification.decision, "changed family seed cell requires a decision"
        if implementation == "missing":
            assert row.classification.parity == "missing"
        assert row.subject.id in row.classification.links
        assert any(link.startswith("UI") for link in row.classification.links)


def test_family_seed_is_pinned_and_changes_need_a_decision():
    records = LedgerDocument.load(SHARDS / "families.toml")
    verify_family_seed(records)
    seeded = Counter({"P": "partial", "C": "custom", "M": "missing"}[value] for row in FAMILY_SEED for value in row)
    assert seeded == {"partial": 48, "custom": 15, "missing": 237}
    assert Counter(row[0] for row in FAMILY_SEED) == {"P": 33, "M": 27}
    assert Counter(row[1] for row in FAMILY_SEED) == {"P": 15, "C": 15, "M": 30}
    for index in (2, 3, 4):
        assert Counter(row[index] for row in FAMILY_SEED) == {"M": 60}


def test_family_seed_mutation_requires_an_explicit_decision():
    records = LedgerDocument.load(SHARDS / "families.toml")
    row = records[0]
    from tools.qualification.schema import Implementation

    changed = replace(row.classification, implementation=Implementation.IMPLEMENTED, parity=None, decision=None)
    records[0] = replace(row, classification=changed)
    with pytest.raises(AssertionError, match="requires a decision"):
        verify_family_seed(records)
    records[0] = replace(records[0], classification=replace(changed, decision="fixture reviewed implementation"))
    verify_family_seed(records)


def test_family_foundation_notes_do_not_claim_shared_contract_proof():
    records = LedgerDocument.load(SHARDS / "families.toml")
    for row in records:
        if row.subject.id in {"N10", "N37", "N40", "N42", "N43"} and row.subject.platform is Platform.MACOS:
            assert "not a verified shared" in row.classification.note
        if row.subject.id == "N41":
            assert "no custom-content bridge" in row.classification.note
        if row.classification.decision is None:
            assert row.evidence is None


def test_packet_amendments_parse_inheritance_nullable_types_and_changes(catalog_directory, monkeypatch):
    path = catalog_directory / "amendments/cx-uia-99.toml"
    path.parent.mkdir()
    path.write_text(
        """
release = "ui0-source-inventory-2026-09-21"

[[additions]]
source = "IFixture.btrc"
owner = "IFixture"
parent = "IView"
decision = "fixture addition"
declarations = ["FontGlyph? lookup(int codepoint, bool render = false);"]

[[changes]]
id = "IWindow.isOpen"
decision = "fixture signature change"
frozen = "bool isOpen();"
current = "bool isOpen(bool cached = false);"

[[removals]]
id = "IWindow.show"
decision = "fixture removal without replacement"
reason = "Fixture exercises optional replacement"
""",
        encoding="utf-8",
    )
    combined = CatalogAmendments(REPO, catalog_directory)
    assert "IFixture.lookup" in combined.added_ids()
    monkeypatch.setitem(globals(), "SHARDS", catalog_directory)
    changed_sources = sources()
    changed_sources["IFixture.btrc"] = (
        "interface IFixture extends IView { FontGlyph? lookup(int codepoint, bool render = false); }"
    )
    changed_sources["IWindow.btrc"] = (
        changed_sources["IWindow.btrc"]
        .replace("bool isOpen();", "bool isOpen(bool cached = false);")
        .replace("void show();", "")
    )
    verify_surface(changed_sources)
    changed_sources["IFixture.btrc"] = changed_sources["IFixture.btrc"].replace("false", "true")
    with pytest.raises(AssertionError, match=r"changed=.*IFixture.lookup"):
        verify_surface(changed_sources)


@pytest.mark.parametrize("mutation", ["unknown-field", "no-decision", "invalid-declaration", "duplicate-id"])
def test_amendment_validation_rejects_unreviewed_or_ambiguous_additions(catalog_directory, mutation):
    row = {"source": "IFixture.btrc", "owner": "IFixture", "decision": "fixture", "declarations": ["void run();"]}
    if mutation == "unknown-field":
        row["typo"] = "ignored"
    elif mutation == "no-decision":
        del row["decision"]
    elif mutation == "invalid-declaration":
        row["declarations"] = ["not valid syntax"]
    else:
        row["declarations"].append("void run(int value);")
    path = write_shard(
        catalog_directory, "amendments/cx-uia-99.toml", release="ui0-source-inventory-2026-09-21", additions=[row]
    )
    path.write_text(path.read_text().split("\n", 1)[1], encoding="utf-8")
    with pytest.raises(LedgerSchemaError):
        UICatalog(directory=catalog_directory)


@pytest.mark.parametrize("outcome", ["passed", "failed", "skipped", "missing", "no-regression"])
def test_passed_evidence_requires_passing_junit_regressions(catalog_directory, tmp_path, outcome):
    entry = {
        "id": "IWindow.isOpen",
        "implementation": "partial",
        "regression": ["src/tests/python/test_ui0_catalog.py::test_fixture"],
        "linux": {"reference": {"evidence": {"status": "passed"}, "run": "ui0-linux-fixture"}},
    }
    if outcome == "no-regression":
        del entry["regression"]
    write_shard(
        catalog_directory,
        "operations/IWindow.toml",
        operations=[entry],
        runs={
            "ui0-linux-fixture": {
                "source": "fixture",
                "recorded_at": "2026-10-03T12:00:00+00:00",
                "runner": "linux-devcontainer",
                "btrc_revision": "fixture-revision",
            }
        },
    )
    name = "test_other" if outcome == "missing" else "test_fixture"
    child = {
        "failed": '<failure message="fixture failure"/>',
        "skipped": '<skipped message="fixture unavailable"/>',
    }.get(outcome, "")
    junit = tmp_path / "fixture.xml"
    junit.write_text(
        f'<testsuite><testcase classname="src.tests.python.test_ui0_catalog" name="{name}">{child}</testcase></testsuite>',
        encoding="utf-8",
    )
    catalog = UICatalog(directory=catalog_directory)
    problems = catalog.problems(junit={"ui0-linux-fixture": junit})
    assert bool(problems) == (outcome != "passed")
    if problems:
        assert any("regression" in problem.lower() or "junit" in problem.lower() for problem in problems)


def test_strict_scope_excludes_retired_slots_and_checks_only_selected_owner(catalog_directory):
    baseline = UICatalog(directory=catalog_directory)
    identifiers = sorted({row.subject.id for row in baseline.unclassified(owner=("GUI",))})
    assert "GUI.rasterText" not in identifiers
    write_shard(
        catalog_directory,
        "operations/GUI.toml",
        operations=[
            {
                "id": identifier,
                "implementation": "partial",
                **{platform.value: {"evidence": {"status": "implemented-unverified"}} for platform in PLATFORMS},
            }
            for identifier in identifiers
        ],
    )
    catalog = UICatalog(directory=catalog_directory)
    assert catalog.unclassified(owner=("GUI",)) == []
    assert catalog.problems(strict=True, owner=("GUI",)) == []
    assert catalog.problems(strict=True, owner=("IWindow",))
    assert catalog.problems(strict=True, kind=("family-cell",)) == []
    assert catalog.problems(strict=True, kind=("ui-case",))


def test_evidence_jsonl_supports_test_records_and_last_evidence(catalog_directory):
    write_shard(catalog_directory, "operations/IWindow.toml", records=[classified_operation()])
    path = catalog_directory / "evidence/ui1-linux.jsonl"
    path.parent.mkdir()
    document = operation(evidence={"status": "passed"})
    document.update(
        schema="btrc.qualification.ledger/1",
        provenance={
            "runner": "linux-devcontainer",
            "recorded_at": "2026-10-03T12:00:00+00:00",
            "btrc_revision": "fixture-revision",
        },
    )
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")
    catalog = UICatalog(directory=catalog_directory)
    assert catalog.problems() == []
    assert any(
        row.subject.id == "IWindow.isOpen" and row.evidence and row.evidence.status == "passed"
        for row in catalog.records
    )


def test_cli_strict_and_json_report_observe_selected_scope(catalog_directory, monkeypatch, capsys):
    from tools.qualification import ui_catalog

    monkeypatch.setattr(ui_catalog, "UICatalog", lambda: UICatalog(directory=catalog_directory))
    assert ui_catalog.main(["check", "--strict", "--kind", "family-cell"]) == 0
    checked = capsys.readouterr()
    assert "300/300" in checked.out
    assert "0 undeclared" in checked.out
    assert ui_catalog.main(["check", "--strict", "--owner", "IWindow"]) == 1
    assert "unclassified" in capsys.readouterr().err
    assert ui_catalog.main(["report", "--format", "json", "--kind", "family-cell"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["partitions"]["frozen"]["slots"] == 300
    assert report["partitions"]["pending"]["slots"] == 0
    assert report["unclassified"] == {}
    assert sum(row.get("partial", 0) for row in report["counts"]) == 48
    assert sum(row.get("custom", 0) for row in report["counts"]) == 15
    assert sum(row.get("missing", 0) for row in report["counts"]) == 237


def test_evidence_shard_requires_provenance(catalog_directory):
    path = write_shard(catalog_directory, "evidence/ui1-linux.toml", records=[operation(evidence={"status": "passed"})])
    document = tomllib.loads(path.read_text())
    document.pop("provenance")
    for record in document["records"]:
        record.pop("provenance")
    path.write_text("\n".join(f"{key} = {inline_toml(value)}" for key, value in document.items()), encoding="utf-8")
    with pytest.raises(LedgerSchemaError, match="provenance"):
        UICatalog(directory=catalog_directory)


def test_new_evidence_cannot_override_missing_implementation(catalog_directory):
    write_shard(
        catalog_directory,
        "operations/IWindow.toml",
        records=[
            operation(
                classification={"implementation": "missing", "parity": "missing"},
                evidence={"status": "unavailable", "covered_by": []},
            )
        ],
    )
    write_shard(catalog_directory, "evidence/ui1-linux.toml", records=[operation(evidence={"status": "passed"})])
    with pytest.raises(LedgerSchemaError, match="missing"):
        UICatalog(directory=catalog_directory)


def test_later_denominator_release_admits_ids_without_mutating_the_seed(catalog_directory):
    manifest = DenominatorManifest.load()
    base = manifest.by_kind()[SubjectKind.UI_OPERATION]
    identifiers = ("FutureOwner.measure",)
    later = replace(
        base,
        release="fixture-reviewed-release",
        ids=identifiers,
        frozen_ids=1,
        frozen_slots=len(PLATFORMS) * len(FRONTENDS),
        frozen_digest=Denominator.digest(identifiers),
        source="fixture",
    )
    manifest = DenominatorManifest([*manifest.denominators, later])
    write_shard(
        catalog_directory,
        "operations/FutureOwner.toml",
        operations=[
            {
                "id": identifiers[0],
                "implementation": "missing",
                **{platform.value: {"evidence": {"status": "unavailable", "covered_by": []}} for platform in PLATFORMS},
            }
        ],
    )
    catalog = UICatalog(directory=catalog_directory, manifest=manifest)
    assert catalog.problems() == []
    assert len([row for row in catalog.frozen_records if row.subject.id == identifiers[0]]) == later.frozen_slots
    assert not any(row.subject.id == identifiers[0] for row in catalog.pending_records)
