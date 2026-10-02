"""P0's compact parity inventory: every operation on every target slice, against a denominator it recomputes.

``docs/design/platform-inventory.toml`` is a ``btrc.qualification.ledger/1``
ledger with one ``operation`` record per operation and target slice
(``TARGET_SLICES``: windows-x64, windows-arm64, ios-device, ios-simulator,
android-arm64, android-x86_64). Its operations are derived, never chosen:

- every export of the root stdlib manifest and of each group manifest, as its
  import path (``Library.Vector``, ``Library.HTTP.HTTPClient``, and
  ``Library.Graph`` for a group's eponymous module), except the groups UI0
  owns (``UI0_GROUPS``), whose operations the UI0 denominators already freeze;
- every helper of the runtime manifest, as ``runtime.<name>``;
- every corpus topic directory, as ``corpus.<topic>``.

A runtime helper's row pins the corpus programs whose emitted C carries that
helper, each cited for every compiler whose runtime catalog carries the helper
(both, except the gpu and collection rows the manifest gives no btrc order),
and the last tests below compile every cited program with those compilers and
look for the helper's definition. A helper no
corpus program can reach says why in its note, and that reason is checked:
``corpus-unreached (archive-api)`` is an arc_runtime API root that only a
stdlib archive selects, and ``corpus-unreached (unselected)`` is a catalog row
no lowering in either compiler selects, no source can name and no helper
depends on.

The frozen ``operation`` denominator in ``tools/qualification/denominators.toml``
holds the same ids, so a row deleted from the ledger is a missing slot and a
new export, helper or topic is drift until the inventory classifies it and the
denominator is re-frozen. The per-class totals for each slice are published in
platform-parity.md and must match the ledger.
"""

from __future__ import annotations

import ast
import re
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from src.compiler.python.application.pipeline import StdlibArchiveAdapter
from src.compiler.python.runtime.generated import RUNTIME_HELPER_ROWS
from src.tests import runner
from src.tests.corpus_files import language_test_files
from tools.qualification.denominators import DenominatorManifest
from tools.qualification.report import QualificationReport
from tools.qualification.schema import TARGET_SLICES, LedgerDocument, Parity, SubjectKind

REPO = Path(__file__).resolve().parents[3]
INVENTORY = REPO / "docs/design/platform-inventory.toml"
PARITY_DOCUMENT = REPO / "docs/design/platform-parity.md"
STDLIB = REPO / "src/stdlib"
RUNTIME_MANIFEST = REPO / "src/runtime/c/manifest.toml"
# Their exports are inventoried by UI0 (docs/design/native-ui-parity.md and
# native-ui-api-inventory.md), whose family-cell, ui-operation and ui-case
# denominators are frozen beside P0's; P0 references them and does not repeat them.
UI0_GROUPS = frozenset({"App", "GUI", "Tray", "UI"})
UI0_KINDS = (SubjectKind.FAMILY_CELL, SubjectKind.UI_OPERATION, SubjectKind.UI_CASE)
SLICE_OF = {target: name for name, target in TARGET_SLICES.items()}
_DEFINITION = re.compile(r"^(?:async )?def (\w+)\(", re.MULTILINE)
_CORPUS_NODE = re.compile(r"^src/tests/runner\.py::test_btrc_file\[(python|btrc)-([^\]]+\.btrc)\]$")
COMPILERS = ("python", "btrc")
VERIFIER = (
    "src/tests/python/test_platform_inventory.py"
    "::test_every_runtime_helper_is_reached_by_a_cited_corpus_program_or_proven_unreached"
)
ARCHIVE_API = "corpus-unreached (archive-api): "
ARCHIVE_API_TEST = (
    "src/tests/python/test_stdlib_archive_shared_state.py"
    "::test_shared_api_completion_reaches_fixed_point_and_externalizes"
)
UNSELECTED = "corpus-unreached (unselected): "
PYTHON_CATALOG = "python-catalog only: "
# Handwritten compiler and stdlib sources: a helper none of them names is selected by no lowering.
HANDWRITTEN = (
    *(
        path
        for path in (REPO / "src/compiler/python").rglob("*.py")
        if path.name not in {"generated.py", "native_generated.py"}
    ),
    *(path for path in (REPO / "src/compiler/btrc").rglob("*.btrc") if "generated" not in path.parts),
    *(REPO / "src/stdlib").rglob("*.btrc"),
)


def stdlib_operations() -> dict[str, tuple[Path, bool]]:
    """Every exported stdlib module outside UI0's groups, by import path: its source and whether a native binding declares it."""

    root = tomllib.loads((STDLIB / "btrc.toml").read_text(encoding="utf-8"))
    operations = {f"Library.{export}": (STDLIB / f"{export}.btrc", False) for export in root["package"]["exports"]}
    for group, dependency in root["dependencies"].items():
        if group in UI0_GROUPS:
            continue
        directory = STDLIB / dependency["path"]
        manifest = tomllib.loads((directory / "btrc.toml").read_text(encoding="utf-8"))
        bound = {binding["module"] for binding in manifest.get("native", {}).get("bindings", ())}
        for export in manifest["package"]["exports"]:
            identifier = f"Library.{group}" if export == group else f"Library.{group}.{export}"
            operations[identifier] = (directory / f"{export.replace('.', '/')}.btrc", export in bound)
    return operations


def runtime_operations() -> list[str]:
    manifest = tomllib.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    return [f"runtime.{helper['name']}" for helper in manifest["helpers"]]


def corpus_operations() -> list[str]:
    topics = {Path(program).parts[0] for program in language_test_files(REPO / "src/tests")}
    return [f"corpus.{topic}" for topic in sorted(topics)]


def expected_operations() -> set[str]:
    return {*stdlib_operations(), *runtime_operations(), *corpus_operations()}


def records():
    return LedgerDocument.load(INVENTORY)


def test_every_stdlib_operation_names_a_module_with_declarations():
    declaration = re.compile(
        r"^\s*(?:abstract\s+)?(?:class|interface|enum|struct)\s+\w+|^\w[\w<>*, ]*\s+\w+\s*\(", re.MULTILINE
    )
    for identifier, (source, bound) in stdlib_operations().items():
        assert source.is_file(), f"{identifier}: {source.relative_to(REPO)} does not exist"
        text = source.read_text(encoding="utf-8")
        # A group's aggregate module (Library.BackgroundJobs) only imports the modules it selects.
        aggregate = re.findall(rf"^import ({re.escape(identifier)}\.\w+);", text, re.MULTILINE)
        # A native binding module (Library.GPU.WebGPU) is declared by its checked SDK header.
        assert declaration.search(text) or aggregate or bound, (
            f"{identifier}: {source.relative_to(REPO)} declares nothing"
        )


def test_the_inventory_covers_the_recomputed_denominator_on_every_slice():
    ledger = records()
    expected = expected_operations()
    ids = {record.subject.id for record in ledger}
    assert sorted(expected - ids) == [], "operations the inventory has not classified"
    assert sorted(ids - expected) == [], "rows whose operation no manifest, export or corpus topic declares"
    slots = Counter(
        (record.subject.id, SLICE_OF.get((record.subject.platform, record.subject.variant))) for record in ledger
    )
    assert all(record.subject.kind is SubjectKind.OPERATION for record in ledger)
    assert None not in {name for _, name in slots}, "every row names one of the six target slices"
    assert [slot for slot, count in slots.items() if count != 1] == [], "one row per operation and slice"
    assert len(slots) == len(expected) * len(TARGET_SLICES)


def test_every_row_is_classified_owned_pinned_and_has_a_current_status():
    for record in records():
        where = f"{record.subject.id} {SLICE_OF[(record.subject.platform, record.subject.variant)]}"
        classification = record.classification
        assert classification is not None and classification.parity is not None, f"{where}: no class"
        assert classification.implementation is not None, f"{where}: no implementation state"
        assert classification.owner, f"{where}: no owner"
        assert classification.regression, f"{where}: no regression"
        assert record.evidence is not None, f"{where}: no evidence status"
        if classification.parity in {Parity.OS_RESTRICTED, Parity.MISSING}:
            assert record.evidence.reason, f"{where}: a {classification.parity.value} row names its reason"


def test_every_regression_names_a_test_that_exists():
    definitions: dict[Path, set[str]] = {}
    for nodeid in sorted({nodeid for record in records() for nodeid in record.classification.regression}):
        path, _, name = nodeid.partition("::")
        source = REPO / path
        assert source.is_file(), f"{nodeid}: no such test file"
        if source not in definitions:
            definitions[source] = set(_DEFINITION.findall(source.read_text(encoding="utf-8")))
        function = name.split("::")[-1].split("[")[0]
        assert function.startswith("test_") and function in definitions[source], f"{nodeid}: no such test"


def test_the_frozen_operation_denominator_is_the_inventory():
    manifest = DenominatorManifest.load()
    denominator = manifest.by_kind()[SubjectKind.OPERATION]
    assert denominator.drift() == []
    assert denominator.slices == tuple(TARGET_SLICES)
    assert set(denominator.ids) == expected_operations()
    assert {kind for kind in manifest.by_kind()} >= set(UI0_KINDS), "UI0's rows stay referenced, not repeated"
    report = QualificationReport(records(), manifest)
    rows = [row for row in report.denominator_rows() if row["kind"] == SubjectKind.OPERATION.value]
    assert [(row["missing_slots"], row["undeclared"], row["drift"]) for row in rows] == [(0, 0, [])]


def published_totals() -> dict[str, dict[str, int]]:
    """The per-slice class totals platform-parity.md publishes."""

    text = PARITY_DOCUMENT.read_text(encoding="utf-8")
    pattern = re.compile(r"^\| `([a-z0-9_-]+)` \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", re.MULTILINE)
    return {
        match[1]: dict(zip(("slots", *(parity.value for parity in Parity)), map(int, match.groups()[1:])))
        for match in pattern.finditer(text)
        if match[1] in TARGET_SLICES
    }


def test_the_per_class_totals_are_published_for_every_slice():
    report = QualificationReport(records())
    computed = {}
    for row in report.parity_rows():
        name = SLICE_OF[(row["platform"], row["variant"])]
        assert row["unclassified"] == 0, f"{name}: unclassified rows"
        computed[name] = {"slots": row["slots"], **{parity.value: row[parity.value] for parity in Parity}}
    assert set(computed) == set(TARGET_SLICES)
    assert published_totals() == computed


def runtime_rows() -> dict[str, tuple[tuple[str, ...], str]]:
    """Each runtime helper's regression and note, which a row shares across its slices."""

    rows = {}
    for record in records():
        if record.subject.id.startswith("runtime."):
            classification = record.classification
            rows[record.subject.id.removeprefix("runtime.")] = (classification.regression, classification.note or "")
    return rows


def corpus_pins(regression) -> dict[str, set[str]]:
    """The corpus programs a regression cites, each with the compilers it is cited for."""

    pins: dict[str, set[str]] = {}
    for nodeid in regression:
        if match := _CORPUS_NODE.match(nodeid):
            pins.setdefault(match[2], set()).add(match[1])
    return pins


def function_source(nodeid: str) -> str:
    path, _, name = nodeid.partition("::")
    text = (REPO / path).read_text(encoding="utf-8")
    function = name.split("::")[-1].split("[")[0]
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function:
            return ast.get_source_segment(text, node) or ""
    return ""


def catalogs() -> dict[str, set[str]]:
    """The compilers whose runtime catalog carries each helper: those the manifest gives an order."""

    manifest = tomllib.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))["helpers"]
    return {helper["name"]: set(helper["order"]) & set(COMPILERS) for helper in manifest}


def test_every_runtime_helper_is_reached_by_a_cited_corpus_program_or_proven_unreached():
    manifest = tomllib.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))["helpers"]
    carried = catalogs()
    visible = {helper["name"] for helper in manifest if helper["source_visible"]}
    depended = {dependency for helper in manifest for dependency in helper["dependencies"]}
    api_roots = set().union(*StdlibArchiveAdapter.API_ROOTS.values())
    corpus = set(language_test_files(REPO / "src/tests"))
    handwritten = {path: path.read_text(encoding="utf-8") for path in HANDWRITTEN}
    rows = runtime_rows()
    assert set(rows) == {helper["name"] for helper in manifest}
    for name, (regression, note) in rows.items():
        named = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])")
        pins = corpus_pins(regression)
        for program, compilers in pins.items():
            assert program in corpus, f"{name}: {program} is not a corpus program"
            assert compilers == carried[name], (
                f"{name}: {program} is cited for {sorted(compilers)}, not {sorted(carried[name])}"
            )
        others = [nodeid for nodeid in regression if not _CORPUS_NODE.match(nodeid)]
        if pins:
            assert not note.startswith("corpus-unreached"), f"{name}: a corpus program reaches it"
            if carried[name] != set(COMPILERS):
                assert note.startswith(PYTHON_CATALOG) and carried[name] == {"python"}, (
                    f"{name}: carried by {sorted(carried[name])} without a python-catalog note"
                )
        elif note.startswith(PYTHON_CATALOG):
            pytest.fail(f"{name}: a python-catalog helper still needs a corpus program that reaches it")
        elif note.startswith(ARCHIVE_API):
            assert name in api_roots and name not in visible, f"{name}: not an archive-only API root"
            assert ARCHIVE_API_TEST in others, f"{name}: cites no archive API completion test"
            others.remove(ARCHIVE_API_TEST)
        elif note.startswith(UNSELECTED):
            assert name not in visible, f"{name}: source-visible, so a program can call it"
            assert name not in depended, f"{name}: another helper depends on it"
            naming = sorted(str(path.relative_to(REPO)) for path, text in handwritten.items() if named.search(text))
            assert naming == [], f"{name}: selected or named by {naming}"
            assert VERIFIER in others, f"{name}: cites no proof that it is unselected"
            others.remove(VERIFIER)
        else:
            pytest.fail(f"{name}: no corpus program reaches it and its note gives no checked reason")
        for nodeid in others:
            assert named.search(function_source(nodeid)), f"{name}: {nodeid} does not name the helper"


def pinned_programs() -> dict[str, dict[str, set[str]]]:
    """Each corpus program a runtime-helper row cites, with the helpers it pins per compiler."""

    pinned: dict[str, dict[str, set[str]]] = {}
    for name, (regression, _) in runtime_rows().items():
        for program, compilers in corpus_pins(regression).items():
            for compiler in compilers:
                pinned.setdefault(program, {}).setdefault(compiler, set()).add(name)
    return pinned


HELPER_SOURCES = {row.name: row.c_source.strip() for row in RUNTIME_HELPER_ROWS}


@pytest.mark.parametrize("program", sorted(pinned_programs()))
def test_a_cited_corpus_program_emits_every_helper_it_pins(program, compiler, request):
    """The emitted C of a pinned program carries each helper pinned for that compiler verbatim.

    ``compiler`` is the shared --compilers parametrization, so both compilers check every
    program. A helper only the Python catalog carries must stay absent from btrcc's C, so a
    change that brings it into the btrc catalog also updates its row.
    """

    path = str(REPO / "src/tests" / program)
    if compiler == "python":
        c_source = runner._transpile_python(path, program)
    else:
        c_source = runner._transpile_btrc(request.getfixturevalue("btrcc_bin"), path)
    pinned = pinned_programs()[program]
    carried = catalogs()
    missing = sorted(name for name in pinned.get(compiler, set()) if HELPER_SOURCES[name] not in c_source)
    assert missing == [], f"{program} through {compiler} no longer emits {missing}"
    foreign = {name for names in pinned.values() for name in names if compiler not in carried[name]}
    unexpected = sorted(name for name in foreign if HELPER_SOURCES[name] in c_source)
    assert unexpected == [], f"{program} through {compiler} emits {unexpected}, which its catalog does not carry"
