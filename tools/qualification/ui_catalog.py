"""UI catalog admission, compact shards and frozen/pending/retired views.

The immutable seed declares identities. Each shard has one classification
writer; evidence can be refreshed independently without erasing that writer.
All expanded and merged records pass through the existing ledger schema.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.parser.parser import ParseError, Parser
from src.compiler.python.syntax.ast.generated import ClassDecl, InterfaceDecl
from tools.qualification.adapters import JUnitAdapter
from tools.qualification.denominators import DenominatorManifest
from tools.qualification.report import QualificationReport
from tools.qualification.schema import (
    SCHEMA,
    Classification,
    EvidenceStatus,
    FieldReader,
    Frontend,
    Implementation,
    LedgerDocument,
    LedgerRecord,
    LedgerSchemaError,
    Platform,
    Provenance,
    Subject,
    SubjectKind,
)

REPO = Path(__file__).resolve().parents[2]
PLATFORMS = (Platform.MACOS, Platform.LINUX, Platform.WINDOWS, Platform.IOS, Platform.ANDROID)
FRONTENDS = (Frontend.REFERENCE, Frontend.SELFHOST)
UI_KINDS = (SubjectKind.UI_OPERATION, SubjectKind.UI_CASE, SubjectKind.FAMILY_CELL)
SURFACE_SCHEMA = "btrc.ui-catalog.surface/1"
SURFACE_STEMS = {"GUIModules": "GUI", "App": "App", "UI": "UI", "Tray": "Tray"}
# Data, rather than permissive recursive ledger discovery: unknown paths fail.
LAYOUT = {
    "families.toml": r"families\.toml",
    "operations": r"operations/[A-Z][A-Za-z0-9]*\.toml",
    "cases": r"cases/E[0-9]{2}-E[0-9]{2}\.toml",
    "surface": r"surface/(?:GUIModules|App|UI|Tray)\.toml",
    "evidence": r"evidence/[a-z][a-z0-9]*(?:-[a-z0-9]+)*\.(?:toml|jsonl)",
    "amendments": r"amendments/cx-[a-z0-9]+-[0-9]+\.toml",
    "hosts.toml": r"hosts\.toml",
    "README.md": r"README\.md",
}


class CatalogAmendments:
    """Reviewed source deltas; method identities are parsed, never regexed."""

    SECTIONS = ("additions", "changes", "removals", "outside_interfaces")
    FIELDS: ClassVar = {
        "additions": ("source", "owner", "decision", "declarations", "parent", "scope", "links", "reason"),
        "changes": ("id", "decision", "frozen", "current"),
        "removals": ("id", "decision", "reason", "replacement"),
        "outside_interfaces": ("id", "decision", "reason"),
    }

    def __init__(self, repo: Path = REPO, directory: Path | None = None):
        directory = directory or repo / "docs/design/native-ui-catalog"
        paths = [repo / "docs/design/ui0-source-amendments.toml", *sorted((directory / "amendments").glob("*.toml"))]
        self.data = {key: [] for key in self.SECTIONS}
        for path in paths:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
            fields = FieldReader(document, str(path), ("release", "current", *self.SECTIONS))
            release = fields.text("release", required=True)
            if "release" in self.data and release != self.data["release"]:
                raise LedgerSchemaError(f"{path}: amendment release differs from the base release")
            self.data["release"] = release
            if "current" in document:
                counts = FieldReader(
                    document["current"],
                    str(path),
                    ("interface_files", "interfaces", "interface_declarations", "facade_declarations"),
                )
                self.data["current"] = {key: counts.integer(key) for key in counts.data}
            for section in self.SECTIONS:
                rows = document.get(section, [])
                if not isinstance(rows, list):
                    raise LedgerSchemaError(f"{path}.{section}: expected an array of tables")
                for row in rows:
                    item = FieldReader(row, f"{path}.{section}", self.FIELDS[section])
                    item.text("decision", required=True)
                    if section == "additions":
                        for key in ("source", "owner"):
                            item.text(key, required=True)
                        declarations = item.texts("declarations")
                        if not declarations:
                            raise LedgerSchemaError(f"{path}: addition needs declarations")
                        if row.get("scope", "in-scope") not in ("in-scope", "out-of-scope"):
                            raise LedgerSchemaError(f"{path}: invalid addition scope")
                        if row.get("scope") == "out-of-scope":
                            item.text("reason", required=True)
                        self.methods(row)
                    else:
                        item.text("id", required=True)
                        if section in ("removals", "outside_interfaces"):
                            item.text("reason", required=True)
                        if section == "changes":
                            for key in ("frozen", "current"):
                                signature = item.text(key, required=True)
                                owner = row["id"].split(".")[0]
                                parsed = self.methods({"owner": owner, "declarations": [signature]})
                                if set(parsed) != {row["id"]}:
                                    raise LedgerSchemaError(f"{path}: changed signature must retain its id")
                    self.data[section].append(row)
        for section in ("changes", "removals", "outside_interfaces"):
            ids = [row["id"] for row in self.data[section]]
            if len(ids) != len(set(ids)):
                raise LedgerSchemaError(f"duplicate {section} amendment")
        self.added_ids()

    @staticmethod
    def declaration(addition):
        owner = addition["owner"]
        declarations = addition["declarations"]
        if owner == "GUI":
            return "class GUI {" + "\n".join(text.rstrip(";") + " {}" for text in declarations) + "}"
        parent = f" extends {addition['parent']}" if addition.get("parent") else ""
        return f"interface {owner}{parent} {{" + "\n".join(declarations) + "}"

    @classmethod
    def methods(cls, addition):
        try:
            declarations = Parser(Lexer(cls.declaration(addition)).tokenize()).parse().declarations
        except (LexerError, ParseError, SyntaxError, ValueError) as error:
            raise LedgerSchemaError(f"invalid amendment declaration: {error}") from error
        if len(declarations) != 1 or not isinstance(declarations[0], (ClassDecl, InterfaceDecl)):
            raise LedgerSchemaError("an addition declares exactly one owner")
        owner = declarations[0]
        methods = owner.methods if isinstance(owner, InterfaceDecl) else owner.members
        result = {f"{owner.name}.{method.name}": method for method in methods}
        if len(result) != len(methods):
            raise LedgerSchemaError("duplicate operation in amendment")
        return result

    def added_ids(self):
        result = set()
        seen = set()
        for addition in self.data["additions"]:
            ids = set(self.methods(addition))
            if seen & ids:
                raise LedgerSchemaError("duplicate addition across amendments")
            seen.update(ids)
            if addition.get("scope", "in-scope") == "in-scope":
                result.update(ids)
        return result


class UICatalog:
    """Validate a shard tree and expose one current record per slot."""

    def __init__(self, repo=REPO, directory=None, seed=None, manifest=None):
        self.repo = Path(repo)
        self.directory = Path(directory) if directory is not None else self.repo / "docs/design/native-ui-catalog"
        self.seed = Path(seed) if seed is not None else self.repo / "docs/design/native-ui-catalog.toml"
        manifest = manifest or DenominatorManifest.load(self.repo / "tools/qualification/denominators.toml", self.repo)
        self.manifest = DenominatorManifest([entry for entry in manifest.denominators if entry.kind in UI_KINDS])
        self.paths = self.layout()
        self.amendment_model = CatalogAmendments(self.repo, self.directory)
        self.amendments = self.amendment_model.data
        self.runs = {}
        self.record_runs = {}
        self._problems = []
        self.surface = []
        self._frozen_keys = set().union(*(entry.slot_keys() for entry in self.manifest.denominators))
        self.admissible = {kind: {key[1] for key in self._frozen_keys if key[0] == kind} for kind in UI_KINDS}
        seed_records = LedgerDocument.load(self.seed)
        self.check_seed(seed_records)
        additions = self.amendment_model.added_ids()
        seed_ids = {record.subject.id for record in seed_records if record.subject.kind == SubjectKind.UI_OPERATION}
        if additions & seed_ids:
            raise LedgerSchemaError("an addition already exists in the frozen seed")
        self.admissible[SubjectKind.UI_OPERATION].update(additions)
        for change in self.amendments["changes"]:
            if change["id"] not in self.admissible[SubjectKind.UI_OPERATION]:
                raise LedgerSchemaError(f"changed id is undeclared: {change['id']}")
        self.retirements = {row["id"]: row for row in self.amendments["removals"]}
        for identifier in self.retirements:
            if identifier not in self.admissible[SubjectKind.UI_OPERATION]:
                raise LedgerSchemaError(f"retired id is undeclared: {identifier}")
        for path in self.paths.get("surface", []):
            self.load_surface(path)
        self._pending_keys = {
            Subject(kind=kind, id=identifier, platform=platform, frontend=frontend).key
            for kind in (SubjectKind.UI_OPERATION, SubjectKind.UI_CASE)
            for identifier in self.admissible[kind]
            for platform in PLATFORMS
            for frontend in FRONTENDS
        } - self._frozen_keys
        merged = {record.subject.key: record for record in seed_records}
        for key in sorted(self._pending_keys):
            merged[key] = LedgerRecord(Subject(SubjectKind(key[0]), key[1], Platform(key[2]), Frontend(key[3])))
        for key, record in list(merged.items()):
            if record.subject.kind == SubjectKind.UI_OPERATION and record.subject.id in self.retirements:
                merged[key] = replace(
                    record,
                    classification=Classification(
                        implementation=Implementation.RETIRED, decision=self.retirements[record.subject.id]["decision"]
                    ),
                )
        writers = {}
        for category in ("families.toml", "operations", "cases", "evidence"):
            for path in self.paths.get(category, []):
                records, run_names = self.load_records(path, category)
                seen = set()
                for record, run in zip(records, run_names, strict=True):
                    updates_evidence = record.evidence is not None
                    key = record.subject.key
                    if key in seen:
                        raise LedgerSchemaError(f"{path}: duplicate slot {key}")
                    seen.add(key)
                    self.admit(record, path, category)
                    classification = record.classification
                    if classification is not None and category != "evidence":
                        if key in writers:
                            raise LedgerSchemaError(f"classification duplicated in {writers[key]} and {path}: {key}")
                        writers[key] = path
                    old = merged.get(key)
                    if old is not None:
                        record = self.merge(old, record, category, path)
                    merged[key] = record
                    if updates_evidence and run:
                        self.record_runs[key] = run
                    elif updates_evidence:
                        self.record_runs.pop(key, None)
        self.records = list(merged.values())
        self.frozen_records = [record for record in self.records if record.subject.key in self._frozen_keys]
        self.pending_records = [record for record in self.records if record.subject.key in self._pending_keys]
        self.retired_records = [record for record in self.records if self.retired(record)]

    def layout(self):
        if not self.directory.is_dir():
            raise LedgerSchemaError(f"missing catalog shard directory: {self.directory}")
        paths = defaultdict(list)
        ranges = []
        directories = {name for name in LAYOUT if "." not in name}
        for path in sorted(self.directory.rglob("*")):
            relative = path.relative_to(self.directory).as_posix()
            if path.is_symlink():
                raise LedgerSchemaError(f"catalog shard symlink is not admitted: {relative}")
            if path.is_dir():
                if relative not in directories:
                    raise LedgerSchemaError(f"unknown catalog directory: {relative}")
                continue
            category = next((name for name, pattern in LAYOUT.items() if re.fullmatch(pattern, relative)), None)
            if category is None:
                raise LedgerSchemaError(f"unknown catalog file: {relative}")
            if category == "cases":
                start, stop = (int(part[1:]) for part in path.stem.split("-"))
                if start > stop or start < 1 or any(start <= end and stop >= begin for begin, end in ranges):
                    raise LedgerSchemaError(f"invalid or overlapping case range: {relative}")
                ranges.append((start, stop))
            paths[category].append(path)
        if not paths["families.toml"]:
            raise LedgerSchemaError("families.toml is required")
        return paths

    def check_seed(self, records):
        expected = set().union(
            *(
                entry.slot_keys()
                for entry in self.manifest.denominators
                if entry.release == self.amendments["release"] and entry.kind != SubjectKind.FAMILY_CELL
            )
        )
        actual = [record.subject.key for record in records]
        if set(actual) != expected or len(actual) != len(set(actual)):
            raise LedgerSchemaError("tampered seed slot set: frozen operation/case slots must remain exact")
        if any(record.classification or record.evidence or record.measurement for record in records):
            raise LedgerSchemaError("the seed contains identities only; write dispositions in shards")

    def load_surface(self, path):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        fields = FieldReader(document, str(path), ("schema", "symbols"))
        if fields.text("schema", required=True) != SURFACE_SCHEMA:
            raise LedgerSchemaError(f"{path}: invalid surface schema")
        rows = document.get("symbols", [])
        if not isinstance(rows, list):
            raise LedgerSchemaError(f"{path}: symbols must be an array of tables")
        package = SURFACE_STEMS[path.stem]
        root = self.repo / "src/stdlib" / package
        exports = tomllib.loads((root / "btrc.toml").read_text(encoding="utf-8"))["package"]["exports"]
        seen = {(row["module"], row["symbol"]) for row in self.surface}
        for row in rows:
            item = FieldReader(
                row, str(path), ("module", "symbol", "kind", "disposition", "links", "reason", "operations")
            )
            module, symbol = item.text("module", required=True), item.text("symbol", required=True)
            kind, disposition = item.text("kind", required=True), item.text("disposition", required=True)
            if disposition not in ("family", "legacy", "provider-internal", "out-of-scope"):
                raise LedgerSchemaError(f"{path}: unknown surface disposition {disposition}")
            if disposition != "family":
                item.text("reason", required=True)
                if "operations" in row:
                    raise LedgerSchemaError(f"{path}: only a family proposes operations")
            Classification.from_mapping({"links": row.get("links", [])}, str(path))
            if not module.startswith(f"{package}.") or module[len(package) + 1 :] not in exports:
                raise LedgerSchemaError(f"{path}: surface module is not exported: {module}")
            if path.stem == "GUIModules" and module.split(".")[-1].startswith("I"):
                raise LedgerSchemaError(f"{path}: GUIModules excludes I*.btrc")
            source = self.repo / "src/stdlib" / Path(*module.split("."))
            source = source.with_suffix(".btrc")
            try:
                declarations = Parser(Lexer(source.read_text(encoding="utf-8")).tokenize()).parse().declarations
            except (LexerError, ParseError) as error:
                raise LedgerSchemaError(f"{path}: invalid exported module: {error}") from error
            matched = [decl for decl in declarations if getattr(decl, "name", None) == symbol]
            if len(matched) != 1 or type(matched[0]).__name__.removesuffix("Decl").lower() != kind:
                raise LedgerSchemaError(f"{path}: surface symbol/kind does not match {module}.{symbol}")
            if (module, symbol) in seen:
                raise LedgerSchemaError(f"{path}: duplicate surface symbol {module}.{symbol}")
            seen.add((module, symbol))
            operations = item.texts("operations") or ()
            for identifier in operations:
                if not re.fullmatch(r"[A-Z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*", identifier):
                    raise LedgerSchemaError(f"{path}: invalid proposed operation id {identifier}")
                if identifier.split(".")[0] != symbol:
                    raise LedgerSchemaError(f"{path}: proposed operation has a foreign owner: {identifier}")
            self.admissible[SubjectKind.UI_OPERATION].update(operations)
            self.surface.append(row)

    def load_records(self, path, category):
        if category not in ("operations", "cases"):
            records = LedgerDocument.load(path)
            return records, [None] * len(records)
        if category == "operations" and not any(
            identifier.startswith(f"{path.stem}.") for identifier in self.admissible[SubjectKind.UI_OPERATION]
        ):
            raise LedgerSchemaError(f"{path}: foreign owner has no admissible operations")
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        fields = FieldReader(document, str(path), ("schema", "records", category, "runs", "provenance"))
        if fields.text("schema", required=True) != SCHEMA:
            raise LedgerSchemaError(f"{path}: invalid ledger schema")
        runs = document.get("runs", {})
        if not isinstance(runs, Mapping):
            raise LedgerSchemaError(f"{path}: runs must be a mapping")
        for name, run in runs.items():
            provenance = Provenance.from_mapping(run, f"{path}.runs.{name}")
            if name in self.runs and self.runs[name] != provenance:
                raise LedgerSchemaError(f"{path}: conflicting provenance for run {name}")
            self.runs[name] = provenance
        records = LedgerDocument.from_document(
            {key: value for key, value in document.items() if key not in (category, "runs")}, str(path)
        )
        names = [None] * len(records)
        rows = document.get(category, [])
        if not isinstance(rows, list):
            raise LedgerSchemaError(f"{path}: {category} must be an array of tables")
        kind = SubjectKind.UI_OPERATION if category == "operations" else SubjectKind.UI_CASE
        compact_ids = set()
        for row in rows:
            item = FieldReader(row, str(path), ("id", *Classification.FIELDS, *PLATFORMS))
            identifier = item.text("id", required=True)
            if identifier in compact_ids:
                raise LedgerSchemaError(f"{path}: duplicate compact id {identifier}; use one table per id")
            compact_ids.add(identifier)
            shared = {key: value for key, value in row.items() if key in Classification.FIELDS}
            Classification.from_mapping(shared, str(path))
            if not any(platform in row for platform in PLATFORMS):
                raise LedgerSchemaError(f"{path}: compact row {identifier} has no platform cells")
            for platform in PLATFORMS:
                if platform not in row:
                    continue
                cell = row[platform]
                if not isinstance(cell, Mapping):
                    raise LedgerSchemaError(f"{path}: a platform cell is a mapping")
                split = any(frontend in cell for frontend in FRONTENDS)
                if split:
                    FieldReader(cell, str(path), FRONTENDS)
                for frontend in FRONTENDS:
                    if split and frontend not in cell:
                        continue
                    value = cell[frontend] if split else cell
                    values = FieldReader(value, str(path), (*Classification.FIELDS, "evidence", "run"))
                    classification = {
                        **shared,
                        **{key: val for key, val in values.data.items() if key in Classification.FIELDS},
                    }
                    run = values.text("run")
                    if run is not None and run not in runs:
                        raise LedgerSchemaError(f"{path}: unknown run {run}")
                    mapping = {
                        "schema": SCHEMA,
                        "subject": {"kind": kind, "id": identifier, "platform": platform, "frontend": frontend},
                    }
                    if classification:
                        mapping["classification"] = classification
                    if "evidence" in value:
                        mapping["evidence"] = value["evidence"]
                    if run is not None:
                        mapping["provenance"] = self.runs[run].to_mapping()
                    elif document.get("provenance"):
                        mapping["provenance"] = document["provenance"]
                    records.append(LedgerRecord.from_mapping(mapping, str(path)))
                    names.append(run)
        return records, names

    def admit(self, record, path, category):
        subject = record.subject
        allowed = {
            "families.toml": (SubjectKind.FAMILY_CELL,),
            "operations": (SubjectKind.UI_OPERATION,),
            "cases": (SubjectKind.UI_CASE,),
            "evidence": (*UI_KINDS, SubjectKind.TEST),
        }
        if subject.kind not in allowed[category]:
            raise LedgerSchemaError(f"{path}: foreign subject kind {subject.kind}")
        if subject.kind in UI_KINDS:
            if subject.variant is not None:
                raise LedgerSchemaError(f"{path}: UI slots cannot carry a variant")
            if subject.platform not in PLATFORMS:
                raise LedgerSchemaError(f"{path}: UI slots need one of the five platform families")
            frontends = (None,) if subject.kind == SubjectKind.FAMILY_CELL else FRONTENDS
            if subject.frontend not in frontends:
                raise LedgerSchemaError(f"{path}: invalid UI frontend")
            if subject.id not in self.admissible[subject.kind]:
                raise LedgerSchemaError(f"{path}: unknown id {subject.id}")
            if subject.kind == SubjectKind.UI_OPERATION and subject.id in self.retirements:
                if record.classification or record.evidence or record.measurement:
                    raise LedgerSchemaError(f"{path}: retired id cannot be classified or evidenced: {subject.id}")
        if category == "operations" and not subject.id.startswith(f"{path.stem}."):
            raise LedgerSchemaError(f"{path}: foreign owner {subject.id}")
        if category == "cases":
            first, last = path.stem.split("-")
            if not first <= subject.id <= last:
                raise LedgerSchemaError(f"{path}: case id outside filename range: {subject.id}")
        if category == "evidence" and record.classification:
            if set(record.classification.to_mapping()) - {"note"}:
                raise LedgerSchemaError(f"{path}: evidence shard classification may contain only note")

    def merge(self, old, new, category, path):
        classification = new.classification or old.classification
        if category == "evidence" and new.classification is not None:
            prior = old.classification or Classification()
            notes = [text for text in (prior.note, new.classification.note) if text]
            classification = replace(prior, note="\n".join(notes) or None)
        if old.evidence is not None and new.evidence is not None:
            before = old.provenance.recorded_at if old.provenance else None
            after = new.provenance.recorded_at if new.provenance else None
            if before and after and datetime.datetime.fromisoformat(after) < datetime.datetime.fromisoformat(before):
                self._problems.append(f"{path}: stale evidence overwrite for {new.subject.key}: {after} < {before}")
        return LedgerRecord(
            subject=new.subject if new.subject.group or new.subject.title else old.subject,
            classification=classification,
            evidence=new.evidence or old.evidence,
            measurement=new.measurement if new.evidence is not None else new.measurement or old.measurement,
            provenance=new.provenance if new.evidence is not None else old.provenance or new.provenance,
        )

    @staticmethod
    def retired(record):
        return record.classification is not None and record.classification.implementation == Implementation.RETIRED

    @classmethod
    def classified(cls, record):
        if cls.retired(record) or record.classification is None or record.classification.implementation is None:
            return False
        return record.subject.kind == SubjectKind.FAMILY_CELL or record.evidence is not None

    @staticmethod
    def selected(record, owner=(), kind=()):
        if isinstance(owner, str):
            owner = (owner,)
        if isinstance(kind, str):
            kind = (kind,)
        return (not kind or record.subject.kind in kind) and (
            not owner
            or record.subject.id.split(".")[0] in owner
            or (record.classification is not None and record.classification.owner in owner)
        )

    def unclassified(self, owner=(), kind=()):
        return [
            record
            for record in self.records
            if record.subject.kind in UI_KINDS
            and self.selected(record, owner, kind)
            and not self.retired(record)
            and not self.classified(record)
        ]

    def problems(self, strict=False, owner=(), kind=(), junit=None):
        tests = [record for record in self.records if record.subject.kind == SubjectKind.TEST]
        problems = [*self._problems, *QualificationReport([*self.frozen_records, *tests], self.manifest).problems()]
        if strict:
            problems.extend(f"unclassified: {record.subject.key}" for record in self.unclassified(owner, kind))
        for run, path in (junit or {}).items():
            if run not in self.runs:
                problems.append(f"unknown JUnit run: {run}")
                continue
            outcomes = JUnitAdapter(self.runs[run], platform=None, repo=self.repo).records(Path(path))
            passed = {record.subject.id for record in outcomes if record.evidence.status == EvidenceStatus.PASSED}
            for record in self.records:
                if (
                    not self.selected(record, owner, kind)
                    or not record.evidence
                    or record.evidence.status != EvidenceStatus.PASSED
                ):
                    continue
                record_run = self.record_runs.get(record.subject.key)
                if record_run is None and record.provenance == self.runs[run]:
                    record_run = run
                if record_run != run:
                    continue
                regression = record.classification.regression if record.classification else None
                if not regression or not set(regression) <= passed:
                    problems.append(f"{record.subject.key}: regression node ids did not pass JUnit run {run}")
        return problems

    def report(self, owner=(), kind=()):
        counts = defaultdict(Counter)
        partitions = {"frozen": self.frozen_records, "pending": self.pending_records, "retired": self.retired_records}
        partition_rows = {}
        for partition, records in partitions.items():
            chosen = [record for record in records if self.selected(record, owner, kind)]
            partition_rows[partition] = {
                "ids": len({(record.subject.kind, record.subject.id) for record in chosen}),
                "slots": len(chosen),
            }
            if partition == "retired":
                continue
            for record in chosen:
                subject = record.subject
                row = counts[
                    (
                        partition,
                        subject.kind.value,
                        subject.platform.value,
                        subject.frontend.value if subject.frontend else "",
                    )
                ]
                row["slots"] += 1
                row[
                    "retired" if self.retired(record) else "classified" if self.classified(record) else "unclassified"
                ] += 1
                if record.classification and record.classification.implementation and not self.retired(record):
                    row[record.classification.implementation.value] += 1
                if record.evidence:
                    row[f"evidence:{record.evidence.status.value}"] += 1
        rows = [
            {"partition": key[0], "kind": key[1], "platform": key[2], "frontend": key[3], **dict(value)}
            for key, value in sorted(counts.items())
        ]
        unclassified = defaultdict(list)
        for record in self.unclassified(owner, kind):
            unclassified[record.subject.id.split(".")[0]].append(list(record.subject.key))
        return {
            "partitions": partition_rows,
            "counts": rows,
            "unclassified": dict(sorted(unclassified.items())),
            "retired": [
                {"id": identifier, "decision": row["decision"]}
                for identifier, row in sorted(self.retirements.items())
                if any(
                    record.subject.id == identifier and self.selected(record, owner, kind)
                    for record in self.retired_records
                )
            ],
            "surface": [
                row for row in self.surface if (not kind or "surface" in kind) and (not owner or row["symbol"] in owner)
            ],
            "problems": self.problems(),
        }

    def render_markdown(self, owner=(), kind=()):
        report = self.report(owner, kind)
        lines = [
            "| Partition | Kind | Platform | Frontend | Slots | Classified | Unclassified | Retired |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for row in report["counts"]:
            values = [
                row.get(key, 0)
                for key in (
                    "partition",
                    "kind",
                    "platform",
                    "frontend",
                    "slots",
                    "classified",
                    "unclassified",
                    "retired",
                )
            ]
            lines.append("| " + " | ".join(map(str, values)) + " |")
        for name, summary in report["partitions"].items():
            lines.append(f"\n{name}: {summary['ids']} ids / {summary['slots']} slots")
        for retired in report["retired"]:
            lines.append(f"Retired: {retired['id']} ({retired['decision']})")
        lines.append("\nUnclassified slots per owner:")
        lines.extend(f"- {owner}: {len(slots)}" for owner, slots in report["unclassified"].items())
        return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "report"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--owner", action="append", default=[])
    parser.add_argument("--kind", choices=(*UI_KINDS, "surface"), action="append", default=[])
    parser.add_argument("--junit", action="append", default=[], metavar="RUN=PATH")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    try:
        catalog = UICatalog()
        junit = {}
        for value in args.junit:
            run, separator, path = value.partition("=")
            if not separator or not run or not path or run in junit:
                raise LedgerSchemaError("--junit requires a unique RUN=PATH")
            junit[run] = Path(path)
        problems = catalog.problems(args.strict, args.owner, args.kind, junit)
        if args.command == "report":
            report = catalog.report(args.owner, args.kind)
            report["problems"] = problems
            print(
                json.dumps(report, indent=2)
                if args.format == "json"
                else catalog.render_markdown(args.owner, args.kind)
            )
        else:
            for kind in UI_KINDS:
                actual = sum(record.subject.kind == kind for record in catalog.frozen_records)
                expected = len(catalog.manifest.slot_keys(kind))
                print(f"{kind}: {actual:,}/{expected:,} frozen slots")
            for name in ("pending", "retired"):
                summary = catalog.report(args.owner, args.kind)["partitions"][name]
                print(f"{name}: {summary['ids']} ids / {summary['slots']} slots")
            print("0 duplicate (admission enforced)")
            undeclared = sum(
                row["undeclared"]
                for row in QualificationReport(catalog.frozen_records, catalog.manifest).denominator_rows()
            )
            print(f"{undeclared} undeclared")
        for problem in problems:
            print(problem, file=sys.stderr)
        return int(bool(problems))
    except (OSError, ValueError) as error:
        print(f"ui-catalog: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
