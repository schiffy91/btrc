"""The UI catalog's section of the qualification report, pinned on a small fixture checkout.

The fixture is a whole checkout in miniature: a denominator manifest with one
release per UI kind, a seed holding exactly its operation and case slots, an
amendment that adds one pending operation and retires another, a shard tree
with families, an operation shard carrying evidence, a case shard and a
surface shard, and the four surface packages' manifests. The live catalog is
never read, so its data can move without moving these tables.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qualification.cli import QualificationCommand
from tools.qualification.denominators import Denominator
from tools.qualification.report import QualificationReport
from tools.qualification.ui_catalog import UICatalog

RELEASE = "fixture-2026-10-04"
PLATFORMS = ("macos", "linux", "windows", "ios", "android")
FRONTENDS = ("reference", "selfhost")
OPERATIONS = ("IWindow.close", "IWindow.isOpen")
CASES = ("E01",)
FAMILIES = ("N01",)
LEDGER = 'schema = "btrc.qualification.ledger/1"\n'
# A compact shard's evidence needs provenance: its own run's, or the document's.
PROVENANCE = '\n[provenance]\nbtrc_revision = "fixture"\nrecorded_at = "2026-10-04T00:00:00Z"\n'


def _quoted(values) -> str:
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"


def _release(kind: str, ids: tuple[str, ...], frontends: tuple[str, ...]) -> str:
    slots = len(ids) * len(PLATFORMS) * max(1, len(frontends))
    return (
        "[[denominators]]\n"
        f'kind = "{kind}"\nrelease = "{RELEASE}"\n'
        f"platforms = {_quoted(PLATFORMS)}\nfrontends = {_quoted(frontends)}\n"
        f"ids = {len(ids)}\nslots = {slots}\nsha256 = {json.dumps(Denominator.digest(ids))}\n"
        f"source = {{ list = {_quoted(ids)} }}\n"
    )


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    _write(
        root,
        "tools/qualification/denominators.toml",
        'schema = "btrc.qualification.denominators/1"\n\n'
        + "\n".join(
            (
                _release("family-cell", FAMILIES, ()),
                _release("ui-operation", OPERATIONS, FRONTENDS),
                _release("ui-case", CASES, FRONTENDS),
            )
        ),
    )
    seed = [
        f'[[records]]\nsubject = {{ kind = "{kind}", id = "{identifier}", platform = "{platform}", '
        f'frontend = "{frontend}" }}\n'
        for kind, ids in (("ui-operation", OPERATIONS), ("ui-case", CASES))
        for identifier in ids
        for platform in PLATFORMS
        for frontend in FRONTENDS
    ]
    _write(root, "docs/design/native-ui-catalog.toml", LEDGER + "\n" + "\n".join(seed))
    _write(
        root,
        "docs/design/ui0-source-amendments.toml",
        f'release = "{RELEASE}"\n\n'
        '[[additions]]\nsource = "IWindow.btrc"\nowner = "IWindow"\ndecision = "fixture-D1"\n'
        'declarations = ["bool isVisible();"]\n\n'
        '[[removals]]\nid = "IWindow.close"\ndecision = "fixture-D2"\nreason = "Removed by the fixture."\n',
    )
    catalog = "docs/design/native-ui-catalog"
    families = [
        f'[[records]]\nsubject = {{ kind = "family-cell", id = "N01", platform = "{platform}" }}\n'
        f'classification = {{ implementation = "{"partial" if platform in ("macos", "linux") else "missing"}" }}\n'
        for platform in PLATFORMS
    ]
    _write(root, f"{catalog}/families.toml", LEDGER + "\n" + "\n".join(families))
    _write(
        root,
        f"{catalog}/operations/IWindow.toml",
        LEDGER + PROVENANCE + '\n[runs.fixture-run]\nsource = "junit"\nrecorded_at = "2026-10-04T00:00:00Z"\n'
        'btrc_revision = "fixture"\nrunner = "github-linux"\n\n'
        '[[operations]]\nid = "IWindow.isOpen"\nowner = "IWindow"\nimplementation = "implemented"\n'
        "[operations.linux.reference]\n"
        'run = "fixture-run"\nevidence = { status = "passed" }\n'
        "[operations.linux.selfhost]\n"
        'run = "fixture-run"\nevidence = { status = "implemented-unverified" }\n\n'
        '[[operations]]\nid = "IWindow.isVisible"\nowner = "IWindow"\nimplementation = "partial"\n'
        "[operations.macos]\n"
        'evidence = { status = "unavailable", reason = "no macOS runner in the fixture" }\n',
    )
    _write(
        root,
        f"{catalog}/cases/E01-E01.toml",
        LEDGER + PROVENANCE + '\n[[cases]]\nid = "E01"\nimplementation = "partial"\n'
        '[cases.linux]\nevidence = { status = "source-only" }\n',
    )
    _write(
        root,
        f"{catalog}/surface/GUIModules.toml",
        'schema = "btrc.ui-catalog.surface/1"\n\n'
        '[[symbols]]\nmodule = "GUI.Button"\nsymbol = "Button"\nkind = "class"\ndisposition = "family"\n'
        'links = ["N01"]\noperations = ["Button.press"]\n',
    )
    for package, exports in (("GUI", ["Button", "IWindow"]), ("App", []), ("UI", []), ("Tray", [])):
        _write(root, f"src/stdlib/{package}/btrc.toml", f'[package]\nname = "fixture"\nexports = {_quoted(exports)}\n')
    _write(
        root, "src/stdlib/GUI/Button.btrc", "class Button {\n}\n\nenum Alignment {\n    LEADING,\n    TRAILING\n};\n"
    )
    _write(root, "src/stdlib/GUI/IWindow.btrc", "interface IWindow {\n    bool isOpen();\n}\n")
    return root


EXPECTED = """\
## UI catalog

The UI0 seed ledger and its shards: 35 frozen and 20 pending slots, 10 of them retired. Frozen slots are the releases in force; pending slots are admitted operations no release declares yet; a retired slot keeps its partition and resolves by its decision.

### Partitions

| kind | frozen ids | frozen slots | pending ids | pending slots | retired ids | retired slots |
|---|---:|---:|---:|---:|---:|---:|
| ui-operation | 2 | 20 | 2 | 20 | 1 | 10 |
| ui-case | 1 | 10 | 0 | 0 | 0 | 0 |
| family-cell | 1 | 5 | 0 | 0 | 0 | 0 |

### Classification

| partition | kind | platform | frontend | slots | classified | unclassified | retired |
|---|---|---|---|---:|---:|---:|---:|
| frozen | family-cell | android | - | 1 | 1 | 0 | 0 |
| frozen | family-cell | ios | - | 1 | 1 | 0 | 0 |
| frozen | family-cell | linux | - | 1 | 1 | 0 | 0 |
| frozen | family-cell | macos | - | 1 | 1 | 0 | 0 |
| frozen | family-cell | windows | - | 1 | 1 | 0 | 0 |
| frozen | ui-case | android | reference | 1 | 0 | 1 | 0 |
| frozen | ui-case | android | selfhost | 1 | 0 | 1 | 0 |
| frozen | ui-case | ios | reference | 1 | 0 | 1 | 0 |
| frozen | ui-case | ios | selfhost | 1 | 0 | 1 | 0 |
| frozen | ui-case | linux | reference | 1 | 1 | 0 | 0 |
| frozen | ui-case | linux | selfhost | 1 | 1 | 0 | 0 |
| frozen | ui-case | macos | reference | 1 | 0 | 1 | 0 |
| frozen | ui-case | macos | selfhost | 1 | 0 | 1 | 0 |
| frozen | ui-case | windows | reference | 1 | 0 | 1 | 0 |
| frozen | ui-case | windows | selfhost | 1 | 0 | 1 | 0 |
| frozen | ui-operation | android | reference | 2 | 0 | 1 | 1 |
| frozen | ui-operation | android | selfhost | 2 | 0 | 1 | 1 |
| frozen | ui-operation | ios | reference | 2 | 0 | 1 | 1 |
| frozen | ui-operation | ios | selfhost | 2 | 0 | 1 | 1 |
| frozen | ui-operation | linux | reference | 2 | 1 | 0 | 1 |
| frozen | ui-operation | linux | selfhost | 2 | 1 | 0 | 1 |
| frozen | ui-operation | macos | reference | 2 | 0 | 1 | 1 |
| frozen | ui-operation | macos | selfhost | 2 | 0 | 1 | 1 |
| frozen | ui-operation | windows | reference | 2 | 0 | 1 | 1 |
| frozen | ui-operation | windows | selfhost | 2 | 0 | 1 | 1 |
| pending | ui-operation | android | reference | 2 | 0 | 2 | 0 |
| pending | ui-operation | android | selfhost | 2 | 0 | 2 | 0 |
| pending | ui-operation | ios | reference | 2 | 0 | 2 | 0 |
| pending | ui-operation | ios | selfhost | 2 | 0 | 2 | 0 |
| pending | ui-operation | linux | reference | 2 | 0 | 2 | 0 |
| pending | ui-operation | linux | selfhost | 2 | 0 | 2 | 0 |
| pending | ui-operation | macos | reference | 2 | 1 | 1 | 0 |
| pending | ui-operation | macos | selfhost | 2 | 1 | 1 | 0 |
| pending | ui-operation | windows | reference | 2 | 0 | 2 | 0 |
| pending | ui-operation | windows | selfhost | 2 | 0 | 2 | 0 |

### Evidence status

| partition | kind | platform | frontend | slots | passed | implemented-unverified | source-only | unavailable | unrecorded |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| frozen | family-cell | android | - | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | family-cell | ios | - | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | family-cell | linux | - | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | family-cell | macos | - | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | family-cell | windows | - | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | android | reference | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | android | selfhost | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | ios | reference | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | ios | selfhost | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | linux | reference | 1 | 0 | 0 | 1 | 0 | 0 |
| frozen | ui-case | linux | selfhost | 1 | 0 | 0 | 1 | 0 | 0 |
| frozen | ui-case | macos | reference | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | macos | selfhost | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | windows | reference | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-case | windows | selfhost | 1 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | android | reference | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | android | selfhost | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | ios | reference | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | ios | selfhost | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | linux | reference | 2 | 1 | 0 | 0 | 0 | 0 |
| frozen | ui-operation | linux | selfhost | 2 | 0 | 1 | 0 | 0 | 0 |
| frozen | ui-operation | macos | reference | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | macos | selfhost | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | windows | reference | 2 | 0 | 0 | 0 | 0 | 1 |
| frozen | ui-operation | windows | selfhost | 2 | 0 | 0 | 0 | 0 | 1 |
| pending | ui-operation | android | reference | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | android | selfhost | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | ios | reference | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | ios | selfhost | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | linux | reference | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | linux | selfhost | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | macos | reference | 2 | 0 | 0 | 0 | 1 | 1 |
| pending | ui-operation | macos | selfhost | 2 | 0 | 0 | 0 | 1 | 1 |
| pending | ui-operation | windows | reference | 2 | 0 | 0 | 0 | 0 | 2 |
| pending | ui-operation | windows | selfhost | 2 | 0 | 0 | 0 | 0 | 2 |

### Retired operations

| id | decision |
|---|---|
| IWindow.close | fixture-D2 |

### Surface

1 surface rows; 1 of 2 exported symbols have no row.

| module | symbol | kind | disposition | operations | links | reason |
|---|---|---|---|---|---|---|
| GUI.Button | Button | class | family | Button.press | N01 | - |

Exported symbols without a surface row, per package:

| package | symbols |
|---|---:|
| GUI | 1 |
"""


def test_the_report_renders_the_ui_catalog_section(checkout: Path):
    catalog = UICatalog(checkout)
    report = QualificationReport([], ui_catalog=catalog)

    markdown = report.render_markdown()
    assert markdown[markdown.index("## UI catalog") :] == EXPECTED
    assert report.problems() == []

    section = report.to_json()["ui_catalog"]
    assert section["partitions"][0] == {
        "kind": "ui-operation",
        **{"frozen_ids": 2, "frozen_slots": 20, "pending_ids": 2, "pending_slots": 20},
        **{"retired_ids": 1, "retired_slots": 10},
    }
    assert section["retired"] == [{"id": "IWindow.close", "decision": "fixture-D2"}]
    assert (section["exported_symbols"], section["unclassified_surface"]) == (2, ["GUI.Button.Alignment"])
    assert section["surface"] == [
        {
            "module": "GUI.Button",
            "symbol": "Button",
            "kind": "class",
            "disposition": "family",
            "operations": ["Button.press"],
            "links": ["N01"],
            "reason": None,
        }
    ]
    # The evidence columns add up to each row's slots: statuses, unrecorded and retired.
    for row in section["evidence"]:
        retired = next(
            other["retired"]
            for other in section["classification"]
            if all(other[key] == row[key] for key in ("partition", "kind", "platform", "frontend"))
        )
        statuses = ("passed", "implemented-unverified", "source-only", "unavailable", "unrecorded")
        assert sum(row[name] for name in statuses) + retired == row["slots"]


def test_a_report_without_the_catalog_has_no_ui_section(checkout: Path):
    report = QualificationReport([])

    assert "## UI catalog" not in report.render_markdown()
    assert "ui_catalog" not in report.to_json()


def test_catalog_problems_fail_the_report(checkout: Path, capsys):
    families = checkout / "docs/design/native-ui-catalog/families.toml"
    text = families.read_text(encoding="utf-8")
    # Keep only the macOS cell: the other four family cells lose their only writer.
    families.write_text("\n[[records]]".join(text.split("\n[[records]]")[:2]), encoding="utf-8")

    problems = QualificationReport([], ui_catalog=UICatalog(checkout)).problems()

    missing = "family-cell: 4 of 5 declared slots have no record (e.g. N01 android, N01 ios, N01 linux, N01 windows)"
    assert problems == [f"ui catalog: {missing}"]
    assert QualificationCommand().run(["report", "--ui-catalog", str(checkout)]) == 1
    assert f"ui catalog: {missing}" in capsys.readouterr().err


def test_a_catalog_that_cannot_load_is_an_input_error(checkout: Path, capsys):
    amendments = checkout / "docs/design/ui0-source-amendments.toml"
    amendments.write_text(amendments.read_text(encoding="utf-8") + "[[removals]\n", encoding="utf-8")

    assert QualificationCommand().run(["report", "--ui-catalog", str(checkout)]) == 2
    assert f"qualification: ui catalog {checkout}: " in capsys.readouterr().err


def test_the_catalog_owns_the_ui_denominators(checkout: Path, capsys):
    """With the catalog, --denominators counts the UI releases once: against the catalog, not the ledger."""

    manifest = str(checkout / "tools/qualification/denominators.toml")

    assert QualificationCommand().run(["report", "--ui-catalog", str(checkout), "--denominators", manifest]) == 0
    assert "## Frozen denominators" not in capsys.readouterr().out
    ledger = checkout / "ledger.toml"
    ledger.write_text(
        'schema = "btrc.qualification.ledger/1"\n\n'
        '[[records]]\nsubject = { kind = "test", id = "src/tests/x.py::test_a", platform = "linux" }\n'
        'evidence = { status = "passed" }\n'
        'provenance = { btrc_revision = "fixture", recorded_at = "2026-10-04T00:00:00Z" }\n',
        encoding="utf-8",
    )
    command = ["report", "--no-ui-catalog", "--ledger", str(ledger), "--denominators", manifest]
    assert QualificationCommand().run(command) == 1
    assert "family-cell: 5 of 5 declared slots have no record" in capsys.readouterr().err


def test_the_report_command_renders_a_checkouts_catalog(checkout: Path, tmp_path: Path, capsys):
    from tools.qualification.denominators import REPO

    # `make qualification-report` names no catalog: the report renders this checkout's.
    assert QualificationCommand().parser().parse_args(["report"]).ui_catalog == REPO
    output = tmp_path / "report.md"

    assert QualificationCommand().run(["report", "--ui-catalog", str(checkout), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8").endswith(EXPECTED)

    assert QualificationCommand().run(["report", "--ui-catalog", str(checkout), "--format", "json"]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert [row["kind"] for row in rendered["ui_catalog"]["partitions"]] == ["ui-operation", "ui-case", "family-cell"]

    assert QualificationCommand().run(["report", "--no-ui-catalog"]) == 2
    assert "nothing to report" in capsys.readouterr().err
