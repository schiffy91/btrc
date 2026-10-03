"""Frozen inventory denominators: the slots a complete report counts against.

platform-parity.md requires "immutable inventory denominators for each
release". A denominator that is whatever rows a ledger happens to hold
shrinks the moment a row is deleted, so each entry of ``denominators.toml``
freezes one release of one inventory kind: the release's name, where its ids are
declared, the platform families and frontends every id is qualified on, and
the id count, slot count and digest it was frozen with. Loading a manifest
re-reads every source, and a source that now yields other ids -- a deleted
row, a renamed one -- is drift until the entry is deliberately re-frozen
under a new release. `QualificationReport` counts every declared slot that
has no record as missing, and every inventory record outside the declared
slots as undeclared, and the report fails on either. A slot the ledger
classifies as ``retired`` (`Implementation.RETIRED`) is present and stays in
its release, but is reported apart from both classified and unclassified slots.

Manifest::

    schema = "btrc.qualification.denominators/1"

    [[denominators]]
    kind = "ui-case"
    release = "ui0-source-inventory-2026-09-21"
    platforms = ["macos", "linux", "windows", "ios", "android"]
    frontends = ["reference", "selfhost"]   # [] when not frontend-specific
    ids = 47                                # the frozen id count
    slots = 470                             # ids x platforms x frontends
    sha256 = "..."                          # of the sorted ids, one per line
    source = { ledger = "docs/design/native-ui-catalog.toml" }

A P0 entry may name ``slices`` (from ``TARGET_SLICES``) instead of whole
families: its ``platforms`` are then exactly the slices' families, in order,
and every id is declared once per slice, as that family plus the slice's
artifact variant (``slots = ids x slices x frontends``)::

    platforms = ["windows", "ios", "android"]
    slices = ["windows-x64", "windows-arm64", "ios-device", "ios-simulator", "android-arm64", "android-x86_64"]

A source is ``{document, pattern}`` (the first group of every matching line of
a tracked document), ``{ledger}`` (the ids of this kind in a checked inventory
ledger, such as UI0's seed catalog or P0's compact inventory) or ``{list}``
(the ids themselves).

A kind may hold several releases, one entry each, keyed by ``(kind,
release)``: a re-freeze that adds ids is a new reviewed release beside the
old one, never an edit of it. Every entry in the manifest is in force; a
release leaves force only when a reviewed change removes its entry. The
report counts missing slots per release, counts a slot as undeclared only
when it is outside the union of every release of its kind, and its coverage
of a kind is that union.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.qualification.schema import (
    INVENTORY_KINDS,
    TARGET_SLICES,
    FieldReader,
    Frontend,
    LedgerDocument,
    LedgerRecord,
    LedgerSchemaError,
    Platform,
    Subject,
    SubjectKind,
)

SCHEMA = "btrc.qualification.denominators/1"
REPO = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).resolve().with_name("denominators.toml")


@dataclass(frozen=True, slots=True)
class Denominator:
    """One frozen inventory kind, with the ids its source yields today."""

    kind: SubjectKind
    release: str
    platforms: tuple[Platform, ...]
    frontends: tuple[Frontend, ...]
    frozen_ids: int
    frozen_slots: int
    frozen_digest: str
    source: str
    ids: tuple[str, ...]
    slices: tuple[str, ...] = ()

    FIELDS = ("kind", "release", "platforms", "slices", "frontends", "ids", "slots", "sha256", "source")

    @staticmethod
    def digest(ids: Iterable[str]) -> str:
        return hashlib.sha256("".join(f"{identifier}\n" for identifier in sorted(ids)).encode()).hexdigest()

    def targets(self) -> tuple[tuple[Platform, str | None], ...]:
        """The (family, variant) pairs every id is declared on: the slices, or the bare families."""

        if self.slices:
            return tuple(TARGET_SLICES[name] for name in self.slices)
        return tuple((platform, None) for platform in self.platforms)

    def slot_keys(self) -> set[tuple[str, str, str, str, str]]:
        """Every slot the frozen release declares, keyed as `Subject.key` keys a record."""

        return {
            Subject(kind=self.kind, id=identifier, platform=platform, frontend=frontend, variant=variant).key
            for identifier in self.ids
            for platform, variant in self.targets()
            for frontend in self.frontends or (None,)
        }

    def drift(self) -> list[str]:
        """How the source has moved away from the frozen release; empty when it has not."""

        where = f"{self.kind.value} denominator (release {self.release})"
        problems = []
        if len(self.ids) != self.frozen_ids:
            problems.append(f"{where}: its source yields {len(self.ids)} ids, frozen at {self.frozen_ids}")
        elif self.digest(self.ids) != self.frozen_digest:
            problems.append(f"{where}: its source yields different ids than the frozen sha256")
        expected_slots = self.frozen_ids * len(self.targets()) * max(1, len(self.frontends))
        if self.frozen_slots != expected_slots:
            axis = "slices" if self.slices else "platforms"
            problems.append(f"{where}: slots = {self.frozen_slots}, but ids x {axis} x frontends = {expected_slots}")
        return problems


class DenominatorManifest:
    """Read ``denominators.toml`` and resolve every source against a checkout."""

    def __init__(self, denominators: Sequence[Denominator]) -> None:
        self.denominators = tuple(denominators)

    @classmethod
    def load(cls, path: Path = MANIFEST, repo: Path = REPO) -> DenominatorManifest:
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise LedgerSchemaError(f"{path}: {error}") from None
        fields = FieldReader(document, str(path), ("schema", "denominators"))
        if fields.text("schema", required=True) != SCHEMA:
            raise LedgerSchemaError(f"{path}.schema: expected {SCHEMA!r}")
        entries = fields.data.get("denominators") or []
        if not isinstance(entries, Sequence) or isinstance(entries, str):
            raise LedgerSchemaError(f"{path}.denominators: expected a list of tables")
        ledgers: dict[Path, list[LedgerRecord]] = {}
        denominators = [
            cls.entry(entry, f"{path}.denominators[{index}]", repo, ledgers) for index, entry in enumerate(entries)
        ]
        releases = Counter((denominator.kind.value, denominator.release) for denominator in denominators)
        if repeated := [f"{kind} {release}" for (kind, release), count in releases.items() if count > 1]:
            raise LedgerSchemaError(f"{path}: one entry per kind and release, but {', '.join(repeated)} repeats")
        return cls(denominators)

    @classmethod
    def entry(
        cls, data: object, where: str, repo: Path, ledgers: dict[Path, list[LedgerRecord]] | None = None
    ) -> Denominator:
        fields = FieldReader(data, where, Denominator.FIELDS)
        kind = fields.choice("kind", SubjectKind, required=True)
        if kind not in INVENTORY_KINDS:
            raise LedgerSchemaError(f"{where}.kind: only inventory kinds have frozen denominators")
        platforms = tuple(cls.members(fields, "platforms", Platform))
        if not platforms:
            raise LedgerSchemaError(f"{where}.platforms: name at least one platform family")
        if Platform.IPADOS in platforms:
            raise LedgerSchemaError(f"{where}.platforms: iOS/iPadOS is one family, ios")
        slices = fields.texts("slices") or ()
        for name in slices:
            if name not in TARGET_SLICES:
                raise LedgerSchemaError(f"{where}.slices: {name!r} is not one of {', '.join(TARGET_SLICES)}")
        if slices and tuple(dict.fromkeys(TARGET_SLICES[name][0] for name in slices)) != platforms:
            raise LedgerSchemaError(f"{where}.platforms: must be the slices' families in slice order")
        sha256 = fields.text("sha256", required=True)
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise LedgerSchemaError(f"{where}.sha256: expected 64 lowercase hex digits")
        source, ids = cls.resolve(fields.data.get("source"), f"{where}.source", kind, repo, ledgers)
        return Denominator(
            kind=kind,
            release=fields.text("release", required=True),
            platforms=platforms,
            frontends=tuple(cls.members(fields, "frontends", Frontend)),
            frozen_ids=cls.count(fields, "ids"),
            frozen_slots=cls.count(fields, "slots"),
            frozen_digest=sha256,
            source=source,
            ids=ids,
            slices=tuple(slices),
        )

    @staticmethod
    def members[E: (Platform, Frontend)](fields: FieldReader, name: str, enum: type[E]) -> list[E]:
        values = fields.texts(name) or ()
        try:
            return [enum(value) for value in values]
        except ValueError as error:
            raise LedgerSchemaError(f"{fields.where}.{name}: {error}") from None

    @staticmethod
    def count(fields: FieldReader, name: str) -> int:
        value = fields.integer(name, minimum=1)
        if value is None:
            raise LedgerSchemaError(f"{fields.where}.{name}: required")
        return value

    @staticmethod
    def resolve(
        data: object, where: str, kind: SubjectKind, repo: Path, ledgers: dict[Path, list[LedgerRecord]] | None = None
    ) -> tuple[str, tuple[str, ...]]:
        """A description of the source and the ids it declares today, in declaration order.

        `ledgers` caches each ledger source by path, so entries that share one are read once.
        """

        fields = FieldReader(data, where, ("document", "pattern", "ledger", "list"))
        if fields.present("list"):
            return "inline list", fields.texts("list") or ()
        if fields.present("ledger"):
            path = repo / fields.text("ledger")
            records = ledgers.get(path) if ledgers is not None else None
            if records is None:
                records = LedgerDocument.load(path)
                if ledgers is not None:
                    ledgers[path] = records
            ids = dict.fromkeys(record.subject.id for record in records if record.subject.kind is kind)
            return fields.text("ledger"), tuple(ids)
        document = fields.text("document", required=True)
        try:
            pattern = re.compile(fields.text("pattern", required=True))
        except re.error as error:
            raise LedgerSchemaError(f"{where}.pattern: {error}") from None
        if pattern.groups < 1:
            raise LedgerSchemaError(f"{where}.pattern: capture the id in a group")
        ids = [
            match.group(1)
            for line in (repo / document).read_text(encoding="utf-8").splitlines()
            if (match := pattern.search(line))
        ]
        if len(set(ids)) != len(ids):
            raise LedgerSchemaError(f"{where}: {document} declares an id twice")
        return document, tuple(ids)

    def drift(self) -> list[str]:
        return [problem for denominator in self.denominators for problem in denominator.drift()]

    def by_kind(self) -> Mapping[SubjectKind, Denominator]:
        """Each kind's base release: the first entry the manifest declares for it."""

        base: dict[SubjectKind, Denominator] = {}
        for denominator in self.denominators:
            base.setdefault(denominator.kind, denominator)
        return base

    def releases(self, kind: SubjectKind) -> tuple[Denominator, ...]:
        """Every release in force for `kind`, in manifest order."""

        return tuple(denominator for denominator in self.denominators if denominator.kind is kind)

    def kinds(self) -> tuple[SubjectKind, ...]:
        """The kinds with at least one release, in manifest order."""

        return tuple(dict.fromkeys(denominator.kind for denominator in self.denominators))

    def slot_keys(self, kind: SubjectKind) -> set[tuple[str, str, str, str, str]]:
        """The union of the slots every release in force declares for `kind`."""

        return set().union(*(denominator.slot_keys() for denominator in self.releases(kind)))
