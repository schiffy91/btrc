"""Register a new stdlib package everywhere a package is named.

    python3 -m tools.register_package Name --summary "..." --reason "..."

A package is a directory ``src/stdlib/Name`` with a ``btrc.toml`` whose
exports are its modules. Until now adding one meant hand edits to eight files
that each name every package or count every export, and a missed one failed a
test far from the change. This writes them from the package's manifest:

- ``src/stdlib/btrc.toml``: the dependency ``Name = { path = "Name" }``;
- ``src/stdlib/btrc.lock``: rewritten by the compiler's own resolver;
- ``docs/design/platform-inventory.toml``: one operation row for each export,
  classified the same on all six target slices;
- ``tools/qualification/denominators.toml``: the operation denominator of
  that ledger, frozen again under a release named for the day and the package;
- ``docs/design/platform-parity.md``: the counts and per-slice totals it
  publishes;
- ``src/tests/python/test_qualification_ledger.py``: the counts it pins;
- ``src/stdlib/README.md``: the package among its groups;
- ``README.md``, with ``--summary``: a row in its table of library groups and
  the package's place in its tree. Both present chosen packages, so without a
  summary README.md is left alone.

It only classifies what it can know: a package of plain BTRC, with no native
binding and no C include, behaves the same on every slice, and ``--reason``
says so in the row. A package with a native boundary differs by slice, and
its rows are a judgement this refuses to make: it stops and names the file.

Every step looks before it writes, so running it again changes nothing, and
``--check`` writes nothing and fails if anything would change.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.compiler.python.frontend.packages import PackageUniverse
from tools.qualification.denominators import Denominator
from tools.qualification.report import QualificationReport
from tools.qualification.schema import TARGET_SLICES, LedgerDocument, Parity, SubjectKind

REPO = Path(__file__).resolve().parents[1]
INVENTORY = "docs/design/platform-inventory.toml"
SUPPLEMENTS = ("windows-supervisor.toml", "windows-supervisor-image.toml", "windows-daemon-files.toml")
# UI0 inventories these groups itself; P0's ledger does not repeat them.
UI0_GROUPS = frozenset({"App", "GUI", "Tray", "UI"})
REGRESSION = "src/tests/runner.py::test_btrc_file"
TIMES = "\N{MULTIPLICATION SIGN}"


class RegistrationError(Exception):
    """The package cannot be registered as it stands; the message says what to do."""


@dataclass
class PackageRegistration:
    repo: Path
    name: str
    summary: str | None
    reason: str
    titles: dict[str, str] = field(default_factory=dict)
    today: datetime.date = field(default_factory=datetime.date.today)
    changed: list[str] = field(default_factory=list)
    write: bool = True

    # -- reading ---------------------------------------------------------

    def text(self, relative: str) -> str:
        return (self.repo / relative).read_text(encoding="utf-8")

    def put(self, relative: str, content: str) -> None:
        if content == self.text(relative):
            return
        self.changed.append(relative)
        if self.write:
            (self.repo / relative).write_text(content, encoding="utf-8")

    def directory(self) -> Path:
        return self.repo / "src/stdlib" / self.name

    def exports(self) -> list[str]:
        manifest = self.directory() / "btrc.toml"
        if not manifest.is_file():
            raise RegistrationError(f"src/stdlib/{self.name}/btrc.toml is not there: make the package first")
        package = tomllib.loads(manifest.read_text(encoding="utf-8"))
        exports = package.get("package", {}).get("exports", [])
        if not exports:
            raise RegistrationError(f"src/stdlib/{self.name}/btrc.toml exports nothing")
        if package.get("native"):
            raise RegistrationError(
                f"src/stdlib/{self.name}/btrc.toml has a native section: its rows differ by slice, "
                f"so classify them by hand in {INVENTORY}"
            )
        for source in sorted(self.directory().rglob("*.btrc")):
            if re.search(r"^\s*#include\b", source.read_text(encoding="utf-8"), re.MULTILINE):
                raise RegistrationError(
                    f"{source.relative_to(self.repo)} includes C: its rows differ by slice, "
                    f"so classify them by hand in {INVENTORY}"
                )
        declaration = re.compile(
            r"^\s*(?:abstract\s+)?(?:class|interface|enum|struct)\s+\w+|^\w[\w<>*, ]*\s+\w+\s*\(", re.MULTILINE
        )
        for export in exports:
            source = self.directory() / f"{export.replace('.', '/')}.btrc"
            if not source.is_file():
                raise RegistrationError(f"src/stdlib/{self.name} exports {export}, which has no source file")
            # What the inventory's own test asks of every export: it declares something, or it is the
            # package's aggregate module and imports the modules it selects by their library names.
            text = source.read_text(encoding="utf-8")
            aggregate = re.search(rf"^import {re.escape(self.identifier(export))}\.\w+;", text, re.MULTILINE)
            if not declaration.search(text) and not aggregate:
                raise RegistrationError(
                    f"{source.relative_to(self.repo)} declares nothing and imports no "
                    f"{self.identifier(export)}.<module>: an export is a module with declarations, or the "
                    f"package's aggregate that imports its modules by their library names"
                )
        return exports

    def identifier(self, export: str) -> str:
        return f"Library.{self.name}" if export == self.name else f"Library.{self.name}.{export}"

    def records(self):
        ledger = self.repo / INVENTORY
        return [
            *LedgerDocument.load(ledger),
            *(record for name in SUPPLEMENTS for record in LedgerDocument.load(ledger.with_suffix("") / name)),
        ]

    def stdlib_exports(self) -> int:
        """Every exported stdlib module outside UI0's groups, as the inventory's own test counts them."""

        root = tomllib.loads(self.text("src/stdlib/btrc.toml"))
        count = len(root["package"]["exports"])
        for group, dependency in root["dependencies"].items():
            if group in UI0_GROUPS:
                continue
            manifest = tomllib.loads(
                (self.repo / "src/stdlib" / dependency["path"] / "btrc.toml").read_text(encoding="utf-8")
            )
            count += len(manifest["package"]["exports"])
        return count

    # -- the files -------------------------------------------------------

    def root_manifest(self) -> None:
        relative = "src/stdlib/btrc.toml"
        lines = self.text(relative).split("\n")
        wanted = f'{self.name} = {{ path = "{self.name}" }}'
        if wanted in lines:
            return
        start = lines.index("[dependencies]") + 1
        end = next((index for index in range(start, len(lines)) if not lines[index].strip()), len(lines))
        place = next((index for index in range(start, end) if lines[index].split(" ", 1)[0] > self.name), end)
        lines.insert(place, wanted)
        self.put(relative, "\n".join(lines))

    def lock(self) -> None:
        """The compiler's resolver rewrites the lock; nothing here knows its format. A check cannot tell
        whether it is current without writing it, and leaves it to the run that writes."""

        if not self.write:
            return
        relative = "src/stdlib/btrc.lock"
        before = self.text(relative)
        try:
            PackageUniverse().resolve_manifest(str(self.repo / "src/stdlib/btrc.toml"), refresh=True)
        except ValueError as error:
            raise RegistrationError(f"the resolver could not rewrite {relative}: {error}") from error
        if self.text(relative) != before:
            self.changed.append(relative)

    def inventory(self) -> None:
        known = {record.subject.id for record in self.records()}
        blocks = []
        for export in self.exports():
            identifier = self.identifier(export)
            if identifier in known:
                continue
            title = self.titles.get(export) or (
                f"{self.name} library facade" if export == self.name else f"{self.name} {export}"
            )
            row = (
                '{ parity = "equivalent", implementation = "implemented", owner = "P2", '
                f'status = "implemented-unverified", reason = {self.quoted(self.reason)} }}'
            )
            blocks.append(
                "\n".join(
                    [
                        "[[rows]]",
                        'kind = "operation"',
                        f'id = "{identifier}"',
                        f'group = "stdlib/{self.name}"',
                        f"title = {self.quoted(title)}",
                        f'regression = ["{REGRESSION}"]',
                        *(f"{name} = {row}" for name in TARGET_SLICES),
                    ]
                )
            )
        if blocks:
            self.put(INVENTORY, self.text(INVENTORY).rstrip("\n") + "\n\n" + "\n\n".join(blocks) + "\n")

    @staticmethod
    def quoted(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def release(self) -> tuple[str, int, int] | None:
        """Freeze the main ledger's operation denominator again; (old release, old ids, old slots) when it moved."""

        relative = "tools/qualification/denominators.toml"
        content = self.text(relative)
        ledger = LedgerDocument.load(self.repo / INVENTORY) if self.write or not self.changed else None
        if ledger is None:
            return None  # a check that would add rows cannot read them back; the rows are the finding
        ids = sorted({record.subject.id for record in ledger if record.subject.kind is SubjectKind.OPERATION})
        entries = content.split("[[denominators]]")
        for index, entry in enumerate(entries):
            if f'source = {{ ledger = "{INVENTORY}" }}' not in entry or 'kind = "operation"' not in entry:
                continue
            old_release = re.search(r'^release = "([^"]+)"$', entry, re.MULTILINE)[1]
            old_ids = int(re.search(r"^ids = (\d+)$", entry, re.MULTILINE)[1])
            old_slots = int(re.search(r"^slots = (\d+)$", entry, re.MULTILINE)[1])
            digest = Denominator.digest(ids)
            if re.search(r'^sha256 = "([0-9a-f]+)"$', entry, re.MULTILINE)[1] == digest and old_ids == len(ids):
                return None
            release = f"p0-inventory-{self.today.isoformat()}-{self.name.lower()}"
            slots = len(ids) * len(TARGET_SLICES)
            entry = re.sub(r'^release = "[^"]+"$', f'release = "{release}"', entry, flags=re.MULTILINE)
            entry = re.sub(r"^ids = \d+$", f"ids = {len(ids)}", entry, flags=re.MULTILINE)
            entry = re.sub(r"^slots = \d+$", f"slots = {slots}", entry, flags=re.MULTILINE)
            entry = re.sub(r'^sha256 = "[0-9a-f]+"$', f'sha256 = "{digest}"', entry, flags=re.MULTILINE)
            entries[index] = entry
            self.put(relative, "[[denominators]]".join(entries))
            return old_release, old_ids, old_slots
        raise RegistrationError(f"{relative} has no operation denominator whose source is {INVENTORY}")

    def frozen(self) -> tuple[str, int, int]:
        entry = next(
            entry
            for entry in self.text("tools/qualification/denominators.toml").split("[[denominators]]")
            if f'source = {{ ledger = "{INVENTORY}" }}' in entry and 'kind = "operation"' in entry
        )
        return (
            re.search(r'^release = "([^"]+)"$', entry, re.MULTILINE)[1],
            int(re.search(r"^ids = (\d+)$", entry, re.MULTILINE)[1]),
            int(re.search(r"^slots = (\d+)$", entry, re.MULTILINE)[1]),
        )

    def parity(self, before: tuple[str, int, int] | None) -> None:
        """The counts platform-parity.md publishes: every operation, the stdlib's exports, the release, each slice's classes."""

        relative = "docs/design/platform-parity.md"
        content = self.text(relative)
        records = self.records()
        operations = len({record.subject.id for record in records})
        content = self.replace_once(
            content,
            r"hold \d+ operations: the\n\d+ exports",
            f"hold {operations} operations: the\n{self.stdlib_exports()} exports",
            relative,
        )
        release, ids, slots = self.frozen()
        if before is not None:
            old_release, old_ids, old_slots = before
            old = f"`{old_release}`, {old_ids} ids {TIMES} {len(TARGET_SLICES)} slices = {old_slots} slots"
            if old not in content:
                raise RegistrationError(f"{relative} does not name the release {old_release} as its denominator does")
            content = content.replace(
                old, f"`{release}`, {ids} ids {TIMES} {len(TARGET_SLICES)} slices = {slots} slots"
            )
        slice_of = {target: name for name, target in TARGET_SLICES.items()}
        for row in QualificationReport(records).parity_rows():
            name = slice_of[(row["platform"], row["variant"])]
            totals = " | ".join(str(row[key]) for key in ("slots", *(parity.value for parity in Parity)))
            content = self.replace_once(
                content,
                rf"^\| `{re.escape(name)}` \| \d+ \| \d+ \| \d+ \| \d+ \| \d+ \|$",
                f"| `{name}` | {totals} |",
                relative,
            )
        self.put(relative, content)

    @staticmethod
    def replace_once(content: str, pattern: str, replacement: str, where: str) -> str:
        found = re.findall(pattern, content, flags=re.MULTILINE)
        if len(found) != 1:
            raise RegistrationError(f"{where}: expected one place matching {pattern!r}, found {len(found)}")
        return re.sub(pattern, lambda _: replacement, content, flags=re.MULTILINE)

    def pinned_counts(self, before: tuple[str, int, int] | None) -> None:
        """test_qualification_ledger.py pins the release and its counts; they move with the denominator."""

        if before is None:
            return
        relative = "src/tests/python/test_qualification_ledger.py"
        content = self.text(relative)
        old_release, old_ids, old_slots = before
        release, ids, slots = self.frozen()
        added = slots - old_slots
        total = re.search(r'if row\["kind"\] == "operation"\) == (\d+)$', content, re.MULTILINE)
        if total is None:
            raise RegistrationError(f"{relative}: the pinned sum of operation slots is not where it was")
        for old, new in (
            (f"SubjectKind.OPERATION: {old_slots},", f"SubjectKind.OPERATION: {slots},"),
            (f'"operation": ({old_ids}, {old_slots}),', f'"operation": ({ids}, {slots}),'),
            (f'("{old_release}", {old_ids}, {old_slots}),', f'("{release}", {ids}, {slots}),'),
            (f'== "operation") == {total[1]}', f'== "operation") == {int(total[1]) + added}'),
        ):
            if content.count(old) != 1:
                raise RegistrationError(f"{relative}: expected one {old!r}, found {content.count(old)}")
            content = content.replace(old, new)
        self.put(relative, content)

    def readmes(self) -> None:
        # README.md's table and tree present chosen packages, not all of them (the tree has no Testing/):
        # a package is put in both when it is given a summary, and README.md is left alone when it is not.
        if self.summary:
            relative = "README.md"
            content = self.text(relative)
            if not re.search(rf"^\|[^\n]*`{re.escape(self.name)}`[^\n|]*\|", content, re.MULTILINE):
                rows = list(re.finditer(r"^\| `[A-Z][^|]*\| [^\n]*\|$", content, re.MULTILINE))
                table_end = self.last_row_before(content, rows, "The everyday surfaces are intentionally practical")
                content = content[:table_end] + f"\n| `{self.name}` | {self.summary} |" + content[table_end:]
            content = self.listed(
                content, r"^    (?:[A-Z][A-Za-z]*/ )*[A-Z][A-Za-z]*/$", f"{self.name}/", " ", relative
            )
            self.put(relative, content)

        relative = "src/stdlib/README.md"
        content = self.text(relative)
        start = content.index("Current groups:")
        end = content.index("\nEach group with behavior worth explaining", start)
        groups = content[start:end]
        if f"`{self.name}`" not in groups:
            names = re.findall(r"`([A-Z][A-Za-z]*)`(?! ?\()|`([A-Z][A-Za-z]*)` \(", groups)
            after = next((first or second for first, second in names if (first or second) > self.name), None)
            if after is None:
                groups = groups.rstrip(".") + f", `{self.name}`."
            else:
                groups = groups.replace(f"`{after}`", f"`{self.name}`, `{after}`", 1)
            content = content[:start] + groups + content[end:]
        self.put(relative, content)

    @staticmethod
    def last_row_before(content: str, rows: list[re.Match[str]], marker: str) -> int:
        limit = content.index(marker)
        ends = [match.end() for match in rows if match.end() < limit]
        if not ends:
            raise RegistrationError("README.md: the table of library groups is not where it was")
        return ends[-1]

    def listed(self, content: str, line_pattern: str, token: str, separator: str, where: str) -> str:
        """Put `token` in its alphabetical place in the last tree line of package directories."""

        if re.search(rf"(?<![A-Za-z]){re.escape(token)}", content):
            return content
        lines = [match for match in re.finditer(line_pattern, content, re.MULTILINE)]
        if not lines:
            raise RegistrationError(f"{where}: the tree of package directories is not where it was")
        last = lines[-1]
        tokens = last[0].split()
        place = next((index for index, existing in enumerate(tokens) if existing > token), len(tokens))
        tokens.insert(place, token)
        return content[: last.start()] + "    " + separator.join(tokens) + content[last.end() :]

    # -- all of it -------------------------------------------------------

    def run(self) -> list[str]:
        self.exports()
        self.root_manifest()
        self.lock()
        self.inventory()
        before = self.release()
        if self.write or not self.changed:
            self.parity(before)
            self.pinned_counts(before)
        self.readmes()
        return self.changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tools.register_package", description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="the package: the name of its directory under src/stdlib")
    parser.add_argument(
        "--summary", help="one line for README.md's table of library groups; without it README.md is left alone"
    )
    parser.add_argument("--reason", required=True, help="why it behaves the same on every target slice")
    parser.add_argument("--title", action="append", default=[], metavar="EXPORT=TITLE", help="an export's row title")
    parser.add_argument("--check", action="store_true", help="write nothing; fail if anything would change")
    arguments = parser.parse_args(argv)
    titles = dict(title.split("=", 1) for title in arguments.title)
    registration = PackageRegistration(
        REPO, arguments.name, arguments.summary, arguments.reason, titles, write=not arguments.check
    )
    try:
        changed = registration.run()
    except RegistrationError as error:
        print(f"register_package: {error}", file=sys.stderr)
        return 2
    for relative in changed:
        print(("would change " if arguments.check else "changed ") + relative)
    if not changed:
        print(f"{arguments.name} is registered everywhere; nothing to change")
    return 1 if arguments.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
