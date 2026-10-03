"""The CI tier manifest, ``ci/tiers.toml``, and the plan each workflow runs.

Schema identifier: ``btrc.ci-tiers/1``.

``[tiers]``      tier name -> one line on when it runs. ``hardware`` names
                 the self-hosted runners and devices nothing here schedules.
``[[jobs]]``     one per job of a tiered workflow: ``workflow`` (``ci.yml``),
                 ``job``, and either ``tiers`` (a plain job) or ``key`` (a
                 matrix job whose rows are the ``[[shards]]`` naming it, and
                 whose rows the key tells apart). Optional ``reports``: the
                 evidence it uploads (``skip-report``, ``junit``, ``bench``).
``[[shards]]``   one matrix row: ``job`` (``ci.yml/tests``), the key's value,
                 every other field the row carries (``target``), ``tiers``,
                 and optional ``reports`` (``boundary-report``).
``[[corpus]]``   ``paths`` -> ``directories`` for ``corpus_tiers`` below.
``[[hardware]]`` ``id``, ``runner`` (as covered_by spells it), ``description``.

A job or shard runs in a tier its ``tiers`` names. In a tier its
``changed_tiers`` names it runs only when a changed file matches one of its
``changed_paths`` (GitHub's ``paths`` glob rules). In a tier its
``corpus_tiers`` names, a corpus shard runs only the corpus directories the
change selects, through ``pytest_addopts``, and not at all when it selects
none. A matrix job runs when any of its rows does.

`TierManifest.plan` is what the workflows' ``scope`` job emits, and
`TierManifest.expected_reports` is what the release bundle checks it holds.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "ci" / "tiers.toml"
SCHEMA = "btrc.ci-tiers/1"
HARDWARE_TIER = "hardware"
REPORT_KINDS = ("skip-report", "junit", "bench", "boundary-report")
WHOLE_CORPUS = "*"
_NAME = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_ROW_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 =._-]*$")
_CORPUS_DIRECTORY = re.compile(r"^[a-z_]+$")
_RESERVED_ROW_FIELDS = frozenset({"job", "tiers", "changed_tiers", "changed_paths", "corpus_tiers", "reports"})


class TierManifestError(ValueError):
    """``ci/tiers.toml`` is malformed or contradicts itself."""


class GitHubPaths:
    """GitHub's ``paths`` filter: ``*`` within a directory, ``**`` across them, ``!`` excludes."""

    @staticmethod
    def pattern(glob: str) -> re.Pattern[str]:
        text = re.escape(glob)
        text = text.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        return re.compile(text)

    @classmethod
    def selects(cls, patterns: Iterable[str], path: str) -> bool:
        selected = False
        for glob in patterns:
            negated = glob.startswith("!")
            if cls.pattern(glob.removeprefix("!")).fullmatch(path):
                selected = not negated
        return selected

    @classmethod
    def any_selected(cls, patterns: Iterable[str], paths: Iterable[str]) -> bool:
        patterns = tuple(patterns)
        return any(cls.selects(patterns, path) for path in paths)


@dataclass(frozen=True)
class TierCondition:
    """When an entry runs: always in ``tiers``; in ``changed_tiers`` when its paths change."""

    tiers: tuple[str, ...] = ()
    changed_tiers: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()

    def runs(self, tier: str, changed: tuple[str, ...] | None) -> bool:
        if tier in self.tiers:
            return True
        # A plan without a change list (a push, a dispatch) has no paths to match.
        return tier in self.changed_tiers and changed is not None and GitHubPaths.any_selected(self.changed_paths, changed)

    def names(self) -> set[str]:
        return {*self.tiers, *self.changed_tiers}


@dataclass(frozen=True)
class TierJob:
    workflow: str
    job: str
    condition: TierCondition
    key: str | None = None
    reports: tuple[str, ...] = ()

    @property
    def stem(self) -> str:
        return self.workflow.rsplit(".", 1)[0]

    @property
    def reference(self) -> str:
        return f"{self.workflow}/{self.job}"


@dataclass(frozen=True)
class TierShard:
    job: str
    row: Mapping[str, str]
    condition: TierCondition
    corpus_tiers: tuple[str, ...] = ()
    reports: tuple[str, ...] = ()

    def names(self) -> set[str]:
        return {*self.condition.names(), *self.corpus_tiers}


@dataclass(frozen=True)
class CorpusRule:
    paths: tuple[str, ...]
    directories: tuple[str, ...]


@dataclass(frozen=True)
class HardwareRunner:
    id: str
    runner: str
    description: str


@dataclass(frozen=True)
class TierManifest:
    tiers: Mapping[str, str]
    jobs: tuple[TierJob, ...]
    shards: tuple[TierShard, ...]
    corpus: tuple[CorpusRule, ...] = ()
    hardware: tuple[HardwareRunner, ...] = ()
    root: Path = field(default=REPO, compare=False)

    @classmethod
    def load(cls, path: Path = MANIFEST, root: Path | None = None) -> TierManifest:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise TierManifestError(f"{path}: {error}") from None
        return cls.from_mapping(data, root or path.resolve().parents[1])

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], root: Path = REPO) -> TierManifest:
        reader = _Reader(data, "tiers.toml", {"schema", "tiers", "jobs", "shards", "corpus", "hardware"})
        if data.get("schema") != SCHEMA:
            raise TierManifestError(f"tiers.toml: schema must be {SCHEMA!r}")
        tiers = data.get("tiers")
        if not isinstance(tiers, Mapping) or not tiers:
            raise TierManifestError("tiers.toml: [tiers] must name at least one tier")
        for name, description in tiers.items():
            if not _NAME.match(name) or not isinstance(description, str) or not description.strip():
                raise TierManifestError(f"tiers.toml: tier {name!r} needs a lowercase name and a description")
        if HARDWARE_TIER not in tiers:
            raise TierManifestError(f"tiers.toml: [tiers] must describe {HARDWARE_TIER!r}")
        scheduled = set(tiers) - {HARDWARE_TIER}
        jobs = tuple(cls._job(entry, f"jobs[{index}]", scheduled) for index, entry in enumerate(reader.tables("jobs")))
        shards = tuple(
            cls._shard(entry, f"shards[{index}]", scheduled) for index, entry in enumerate(reader.tables("shards"))
        )
        corpus = tuple(cls._corpus(entry, f"corpus[{index}]") for index, entry in enumerate(reader.tables("corpus")))
        hardware = tuple(
            HardwareRunner(**_Reader(entry, f"hardware[{index}]", {"id", "runner", "description"}).texts())
            for index, entry in enumerate(reader.tables("hardware"))
        )
        manifest = cls(dict(tiers), jobs, shards, corpus, hardware, root)
        manifest._validate()
        return manifest

    @staticmethod
    def _condition(reader: _Reader, scheduled: set[str]) -> TierCondition:
        condition = TierCondition(
            tiers=reader.names("tiers", scheduled),
            changed_tiers=reader.names("changed_tiers", scheduled),
            changed_paths=reader.strings("changed_paths"),
        )
        if bool(condition.changed_tiers) != bool(condition.changed_paths):
            raise TierManifestError(f"{reader.where}: changed_tiers and changed_paths go together")
        if overlap := set(condition.tiers) & set(condition.changed_tiers):
            raise TierManifestError(f"{reader.where}: {sorted(overlap)} cannot be both unconditional and changed")
        return condition

    @classmethod
    def _job(cls, entry: object, where: str, scheduled: set[str]) -> TierJob:
        reader = _Reader(entry, where, {"workflow", "job", "key", "reports", "tiers", "changed_tiers", "changed_paths"})
        key = reader.optional_text("key")
        condition = cls._condition(reader, scheduled)
        if key is not None and condition.names():
            raise TierManifestError(f"{where}: a matrix job's tiers come from its shards")
        if key is None and not condition.names():
            raise TierManifestError(f"{where}: a job needs tiers, or a key for its matrix rows")
        workflow, job = reader.text("workflow"), reader.text("job")
        if not re.fullmatch(r"[a-z0-9-]+\.yml", workflow) or not _NAME.match(job):
            raise TierManifestError(f"{where}: {workflow}/{job} is not a workflow file and job name")
        reports = reader.names("reports", set(REPORT_KINDS))
        return TierJob(workflow, job, condition, key, reports)

    @classmethod
    def _shard(cls, entry: object, where: str, scheduled: set[str]) -> TierShard:
        if not isinstance(entry, Mapping):
            raise TierManifestError(f"{where}: expected a table")
        reader = _Reader(entry, where, set(entry))
        row = {name: value for name, value in entry.items() if name not in _RESERVED_ROW_FIELDS | {"corpus_tiers"}}
        for name, value in row.items():
            if not re.fullmatch(r"[a-z_]+", name) or not isinstance(value, str) or not _ROW_VALUE.match(value):
                raise TierManifestError(f"{where}.{name}: a row field is a snake_case name with a plain text value")
        return TierShard(
            job=reader.text("job"),
            row=row,
            condition=cls._condition(reader, scheduled),
            corpus_tiers=reader.names("corpus_tiers", scheduled),
            reports=reader.names("reports", set(REPORT_KINDS)),
        )

    @staticmethod
    def _corpus(entry: object, where: str) -> CorpusRule:
        reader = _Reader(entry, where, {"paths", "directories"})
        directories = reader.strings("directories")
        if not directories or not all(name == WHOLE_CORPUS or _CORPUS_DIRECTORY.match(name) for name in directories):
            raise TierManifestError(f"{where}.directories: corpus directory names, or {WHOLE_CORPUS!r}")
        paths = reader.strings("paths")
        if not paths:
            raise TierManifestError(f"{where}.paths: at least one pattern")
        return CorpusRule(paths, directories)

    def _validate(self) -> None:
        seen: set[str] = set()
        for job in self.jobs:
            if job.reference in seen:
                raise TierManifestError(f"tiers.toml: {job.reference} is listed twice")
            seen.add(job.reference)
        matrix_jobs = {job.reference: job for job in self.jobs if job.key is not None}
        rows: dict[str, set[str]] = {reference: set() for reference in matrix_jobs}
        for shard in self.shards:
            job = matrix_jobs.get(shard.job)
            if job is None:
                raise TierManifestError(f"tiers.toml: shard of {shard.job}, which is not a matrix job here")
            value = shard.row.get(job.key or "")
            if value is None:
                raise TierManifestError(f"tiers.toml: a {shard.job} shard has no {job.key!r}")
            if value in rows[shard.job]:
                raise TierManifestError(f"tiers.toml: {shard.job} has two {job.key} {value!r} rows")
            rows[shard.job].add(value)
            if not shard.names():
                raise TierManifestError(f"tiers.toml: {shard.job} {value} runs in no tier")
            if "pytest_addopts" in shard.row:
                raise TierManifestError(f"tiers.toml: {shard.job} {value}: pytest_addopts is computed, not written")
        for reference, values in rows.items():
            if not values:
                raise TierManifestError(f"tiers.toml: matrix job {reference} has no shards")
        if len({runner.id for runner in self.hardware}) != len(self.hardware):
            raise TierManifestError("tiers.toml: hardware ids repeat")

    # ------------------------------------------------------------------ plans

    def workflows(self) -> list[str]:
        return sorted({job.workflow for job in self.jobs})

    def scheduled_tiers(self) -> list[str]:
        return [tier for tier in self.tiers if tier != HARDWARE_TIER]

    def shards_of(self, job: TierJob) -> list[TierShard]:
        return [shard for shard in self.shards if shard.job == job.reference]

    def corpus_directories(self) -> set[str]:
        tests = self.root / "src" / "tests"
        return {path.parent.name for path in tests.glob("*/expected") if path.is_dir()}

    def corpus_selection(self, changed: Iterable[str]) -> set[str]:
        """The corpus directories a change selects; ``{"*"}`` for the whole corpus."""

        known = self.corpus_directories()
        selected: set[str] = set()
        for path in changed:
            for rule in self.corpus:
                if GitHubPaths.selects(rule.paths, path):
                    selected.update(rule.directories)
            parts = path.split("/")
            if len(parts) > 3 and parts[:2] == ["src", "tests"] and parts[2] in known:
                selected.add(parts[2])
        return {WHOLE_CORPUS} if WHOLE_CORPUS in selected else selected

    def row(self, shard: TierShard, tier: str, changed: tuple[str, ...] | None) -> dict[str, str] | None:
        """The matrix row `shard` contributes in `tier`, or None when it does not run."""

        if shard.condition.runs(tier, changed):
            return dict(shard.row)
        if tier not in shard.corpus_tiers or changed is None:
            return None
        selected = self.corpus_selection(changed)
        if not selected:
            return None
        if WHOLE_CORPUS in selected:
            return dict(shard.row)
        # Corpus test ids are `<frontend>-<directory>/<Program>.btrc`.
        expression = " or ".join(
            f"{frontend}-{directory}/" for directory in sorted(selected) for frontend in ("python", "btrc")
        )
        return {**shard.row, "pytest_addopts": f'-k "{expression}"'}

    def plan(self, workflow: str, tier: str, changed: Iterable[str] | None = None) -> dict[str, Any]:
        """Which jobs and matrix rows of `workflow` run in `tier`, and what each must upload."""

        if tier not in self.scheduled_tiers():
            raise TierManifestError(f"no scheduled tier {tier!r}; choose from {', '.join(self.scheduled_tiers())}")
        jobs = [job for job in self.jobs if job.workflow == workflow]
        if not jobs:
            raise TierManifestError(f"tiers.toml lists no job of {workflow}")
        files = tuple(changed) if changed is not None else None
        plan: dict[str, Any] = {"tier": tier, "jobs": [], "matrix": {}, "reports": {}}
        for job in jobs:
            if job.key is None:
                if not job.condition.runs(tier, files):
                    continue
                reports = self.report_names(job, None, ())
            else:
                rows = [(shard, row) for shard in self.shards_of(job) if (row := self.row(shard, tier, files))]
                if not rows:
                    continue
                plan["matrix"][job.job] = {"include": [row for _, row in rows]}
                reports = [name for shard, row in rows for name in self.report_names(job, row, shard.reports)]
            plan["jobs"].append(job.job)
            plan["reports"][job.job] = reports
        return plan

    @staticmethod
    def report_names(job: TierJob, row: Mapping[str, str] | None, shard_reports: tuple[str, ...]) -> list[str]:
        """The artifact names a job (one matrix row of it) uploads its evidence under."""

        suffix = f"-{row[job.key]}" if row is not None and job.key else ""
        names = []
        for kind in (*job.reports, *shard_reports):
            if kind == "bench":
                names.append("bench-results")
            else:
                names.append(f"{kind}-{job.stem}-{job.job}{suffix}")
        return names

    def expected_reports(self, tier: str) -> dict[str, list[str]]:
        """Every artifact a run of `tier` across all workflows must leave, keyed ``workflow/job``."""

        expected: dict[str, list[str]] = {}
        for workflow in self.workflows():
            plan = self.plan(workflow, tier)
            for job, names in plan["reports"].items():
                if names:
                    expected[f"{workflow}/{job}"] = names
        return expected


class _Reader:
    """Field access for one TOML table that rejects unknown keys."""

    def __init__(self, data: object, where: str, allowed: set[str]) -> None:
        if not isinstance(data, Mapping):
            raise TierManifestError(f"{where}: expected a table")
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise TierManifestError(f"{where}: unknown field(s) {', '.join(unknown)}")
        self.data = data
        self.where = where

    def tables(self, name: str) -> list[object]:
        value = self.data.get(name, [])
        if not isinstance(value, list):
            raise TierManifestError(f"{self.where}.{name}: expected an array of tables")
        return value

    def text(self, name: str) -> str:
        value = self.data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise TierManifestError(f"{self.where}.{name}: required text")
        return value

    def optional_text(self, name: str) -> str | None:
        return self.text(name) if name in self.data else None

    def texts(self) -> dict[str, str]:
        return {name: self.text(name) for name in self.data}

    def strings(self, name: str) -> tuple[str, ...]:
        value = self.data.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise TierManifestError(f"{self.where}.{name}: expected a list of text")
        if len(set(value)) != len(value):
            raise TierManifestError(f"{self.where}.{name}: repeats an entry")
        return tuple(value)

    def names(self, name: str, allowed: set[str]) -> tuple[str, ...]:
        values = self.strings(name)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise TierManifestError(f"{self.where}.{name}: unknown {', '.join(unknown)}")
        return values
