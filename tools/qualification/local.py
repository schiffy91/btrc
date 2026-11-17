"""Local passes: the CI jobs a machine of the owner's reproduces, and a plan without the ones it passed.

A ``[[jobs]]`` entry of ``ci/tiers.toml`` that names ``local = "<platform>"``
can be reproduced on a machine of that platform, spelled as ``ci-local``
spells it (``linux-x86_64``, ``macos-arm64``). `LocalJobs` derives
``ci/local.json`` from those entries and the workflows themselves: one job
per matrix row a push to main runs, named as GitHub shows it (``CI / tests
(unit)``), whose command hands the workflow job's own unconditional ``run``
steps to ``tools/ci-local-job.sh``, which runs them in a fresh clone of the
commit. ``ci-local run`` records a pass for that exact commit and ``ci-local
push`` posts it as the commit status ``local/<platform>/<name>``.

In CI, a workflow's ``local`` job (the shared workflow of schiffy91/ci-local)
reports the owner's standing passes among the commit's statuses, and
`LocalJobs.without_passed` takes each passed job and row out of that
workflow's plan. `LocalPasses.accepted` is the same filter here, for the
``local-passes`` command and the tests. A row leaves only when the
plan would run exactly the row the local command ran: a pull request's unit
shard that keeps the GUI files, or a corpus row narrowed to some directories,
is a different command and still runs.
"""

from __future__ import annotations

import copy
import json
import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.qualification.tiers import TierJob, TierManifest, TierManifestError

TABLE = Path("ci") / "local.json"
CONTEXT_PREFIX = "local/"
RUNNER = "tools/ci-local-job.sh"
# A push to main is the one run whose commit a machine can have passed (a pull request's is
# its merge commit; a dispatch and a release read no pass), so its rows are the local jobs.
REFERENCE_TIER = "main"
# The owner's Mac is the acceptance runner `macos`; only GitHub's image is `macos-hosted`.
PLATFORM_ENVIRONMENT = {"macos-arm64": {"BTRC_TEST_RUNNER": "macos"}}


class MatrixExpression:
    """The GitHub expressions a reproducible step may use: its matrix row, text, ==, !=, &&, || and format()."""

    TOKEN = re.compile(
        r"\s*(?:(?P<text>'(?:[^']|'')*')|(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)|(?P<symbol>==|!=|&&|\|\||[(),]))"
    )
    USE = re.compile(r"\$\{\{(.*?)\}\}")

    def __init__(self, row: Mapping[str, str] | None, where: str) -> None:
        self.row = row or {}
        self.where = where

    def expand(self, text: str) -> str:
        """`text` with each ``${{ … }}`` replaced by its value, as the runner would."""

        return self.USE.sub(lambda use: self.text(self.evaluate(use.group(1))), text)

    @staticmethod
    def text(value: object) -> str:
        return "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)

    def evaluate(self, expression: str) -> object:
        tokens, position = [], 0
        while expression[position:].strip():
            token = self.TOKEN.match(expression, position)
            if token is None:
                raise TierManifestError(f"{self.where}: a local job cannot evaluate ${{{{{expression}}}}}")
            tokens.append((token.lastgroup, token.group(token.lastgroup)))
            position = token.end()
        value, rest = self._either(tokens)
        if rest:
            raise TierManifestError(f"{self.where}: a local job cannot evaluate ${{{{{expression}}}}}")
        return value

    def _either(self, tokens: list) -> tuple[object, list]:
        value, tokens = self._both(tokens)
        while tokens[:1] == [("symbol", "||")]:
            other, tokens = self._both(tokens[1:])
            value = value or other
        return value, tokens

    def _both(self, tokens: list) -> tuple[object, list]:
        value, tokens = self._compared(tokens)
        while tokens[:1] == [("symbol", "&&")]:
            other, tokens = self._compared(tokens[1:])
            value = value and other
        return value, tokens

    def _compared(self, tokens: list) -> tuple[object, list]:
        value, tokens = self._value(tokens)
        if tokens[:1] in ([("symbol", "==")], [("symbol", "!=")]):
            other, rest = self._value(tokens[1:])
            same = self.text(value).casefold() == self.text(other).casefold()  # GitHub compares text without case
            return same == (tokens[0][1] == "=="), rest
        return value, tokens

    def _value(self, tokens: list) -> tuple[object, list]:
        if not tokens:
            raise TierManifestError(f"{self.where}: an expression ends early")
        (kind, text), rest = tokens[0], tokens[1:]
        if kind == "text":
            return text[1:-1].replace("''", "'"), rest
        if (kind, text) == ("symbol", "("):
            value, rest = self._either(rest)
            return value, self._expect(rest, ")")
        if kind == "name" and text == "format":
            arguments, rest = [], self._expect(rest, "(")
            while True:
                argument, rest = self._either(rest)
                arguments.append(self.text(argument))
                if rest[:1] != [("symbol", ",")]:
                    break
                rest = rest[1:]
            return re.sub(r"\{(\d+)\}", lambda use: arguments[int(use.group(1)) + 1], arguments[0]), self._expect(
                rest, ")"
            )
        if kind == "name" and text.startswith("matrix."):
            return self.row.get(text.removeprefix("matrix.")), rest  # a field the row lacks is null, as on GitHub
        raise TierManifestError(f"{self.where}: a local machine has no value for {text!r}")

    def _expect(self, tokens: list, symbol: str) -> list:
        if tokens[:1] != [("symbol", symbol)]:
            raise TierManifestError(f"{self.where}: expected {symbol!r} in an expression")
        return tokens[1:]


@dataclass(frozen=True)
class WorkflowStep:
    """One ``run`` step: its script, its ``env`` and whether an ``if`` decides it."""

    script: str
    environment: tuple[tuple[str, str], ...]
    conditional: bool


@dataclass(frozen=True)
class WorkflowJob:
    """A workflow job's display name and ``run`` steps, read from the workflow's text.

    The workflows keep one layout, which this reads rather than YAML at large:
    a job two spaces in, its keys four, a step's ``- `` six, the step's keys
    eight and a block scalar's or mapping's lines ten.
    """

    workflow_name: str
    job: str
    name: str | None
    steps: tuple[WorkflowStep, ...]

    @classmethod
    def read(cls, path: Path, job: str) -> WorkflowJob:
        lines = path.read_text(encoding="utf-8").splitlines()
        title = next((line.removeprefix("name:").strip() for line in lines if line.startswith("name:")), None)
        start = next((index for index, line in enumerate(lines) if line.rstrip() == f"  {job}:"), None)
        if title is None or start is None:
            raise TierManifestError(f"{path.name}: no workflow name or no {job!r} job to reproduce locally")
        end = next(
            (index for index in range(start + 1, len(lines)) if re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", lines[index])),
            len(lines),
        )
        block = lines[start + 1 : end]
        if any(line.rstrip() == "    env:" for line in block):
            raise TierManifestError(f"{path.name}/{job}: a local job cannot carry job-level env")
        name = next((line.removeprefix("    name:").strip() for line in block if line.startswith("    name:")), None)
        starts = [index for index, line in enumerate(block) if line.startswith("      - ")]
        steps = []
        for first, last in zip(starts, [*starts[1:], len(block)], strict=True):
            step = cls._step(["        " + block[first][8:], *block[first + 1 : last]])
            if step is not None:
                steps.append(step)
        return cls(title, job, name, tuple(steps))

    @staticmethod
    def _step(lines: list[str]) -> WorkflowStep | None:
        """The step these lines spell, with its keys all eight spaces in; None when it runs no script."""

        fields: dict[str, list[str]] = {}
        key = None
        for line in lines:
            entry = re.fullmatch(r" {8}([A-Za-z-]+):(?: (.*))?", line)
            if entry:
                key = entry.group(1)
                fields[key] = [] if entry.group(2) in (None, "|") else [entry.group(2)]
            elif key is not None and (line.startswith(" " * 10) or not line.strip()):
                fields[key].append(line[10:])
        if "run" not in fields:
            return None
        if unread := sorted({"shell", "working-directory"} & set(fields)):
            raise TierManifestError(f"a local job's step cannot set {', '.join(unread)}")
        script = [line for line in fields["run"] if not line.lstrip().startswith("#")]  # a comment runs nothing
        while script and not script[-1].strip():
            script.pop()
        environment = []
        for line in fields.get("env", []):
            if line.strip() and not line.lstrip().startswith("#"):
                name, _, value = line.partition(":")
                value = value.strip()
                if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                environment.append((name.strip(), value))
        return WorkflowStep("\n".join(script), tuple(environment), "if" in fields)


@dataclass(frozen=True)
class LocalJob:
    """One CI job, or one matrix row of one, as a machine of `platform` reproduces it."""

    workflow: str
    job: str
    name: str
    platform: str
    row: Mapping[str, str] | None
    environment: tuple[tuple[str, str], ...]
    steps: tuple[str, ...]

    @property
    def context(self) -> str:
        return f"{CONTEXT_PREFIX}{self.platform}/{self.name}"

    @property
    def run(self) -> str:
        return shlex.join([RUNNER, *(f"{name}={value}" for name, value in self.environment), "--", *self.steps])


class LocalJobs:
    """Every job ``ci/tiers.toml`` marks ``local``, and the plans their passes shorten."""

    def __init__(self, manifest: TierManifest) -> None:
        self.manifest = manifest

    def entries(self) -> list[LocalJob]:
        entries = []
        for job in self.manifest.jobs:
            if job.local is None:
                continue
            plan = self.manifest.plan(job.workflow, REFERENCE_TIER)
            if job.job not in plan["jobs"]:
                raise TierManifestError(f"{job.reference}: a local job runs in the {REFERENCE_TIER} tier")
            source = WorkflowJob.read(self.manifest.root / ".github" / "workflows" / job.workflow, job.job)
            rows = plan["matrix"][job.job]["include"] if job.key else [None]
            entries.extend(self._entry(job, source, row) for row in rows)
        names = [entry.name for entry in entries]
        if len(set(names)) != len(names):
            raise TierManifestError("local jobs: two jobs share a name")
        return entries

    @staticmethod
    def _entry(job: TierJob, source: WorkflowJob, row: Mapping[str, str] | None) -> LocalJob:
        expression = MatrixExpression(row, job.reference)
        if job.key and source.name is None:
            raise TierManifestError(f"{job.reference}: a local matrix job needs a name that tells its rows apart")
        environment = dict(PLATFORM_ENVIRONMENT.get(job.local or "", {}))
        steps = []
        # A step an `if` decides is the runner's provisioning or its evidence, not the job's command.
        for step in (step for step in source.steps if not step.conditional):
            for name, value in step.environment:
                value = expression.expand(value)
                if environment.setdefault(name, value) != value:
                    raise TierManifestError(f"{job.reference}: {name} has two values across the job's steps")
            steps.append(expression.expand(step.script))
        if not steps:
            raise TierManifestError(f"{job.reference}: no unconditional run step to reproduce")
        name = expression.expand(source.name) if source.name else job.job
        return LocalJob(
            workflow=job.workflow,
            job=job.job,
            name=f"{source.workflow_name} / {name}",
            platform=job.local or "",
            row=dict(row) if row is not None else None,
            environment=tuple(environment.items()),
            steps=tuple(steps),
        )

    def table(self) -> str:
        """The text of ``ci/local.json``: what ``ci-local`` reads."""

        jobs = {entry.name: {"platform": entry.platform, "run": entry.run} for entry in self.entries()}
        return json.dumps({"jobs": jobs}, indent=2) + "\n"

    def without_passed(self, workflow: str, plan: Mapping[str, Any], contexts: Iterable[str]) -> dict[str, Any]:
        """`plan` minus each job and row a context in `contexts` passed; ``local`` lists what left."""

        passed, shortened, left = set(contexts), copy.deepcopy(dict(plan)), []
        tiered = {job.job: job for job in self.manifest.jobs if job.workflow == workflow}
        for entry in self.entries():
            if entry.workflow != workflow or entry.context not in passed or entry.job not in shortened["jobs"]:
                continue
            job = tiered[entry.job]
            if entry.row is not None:
                rows = shortened["matrix"][entry.job]["include"]
                if entry.row not in rows:
                    continue  # this plan runs another command under the name
                rows.remove(entry.row)
                shard = next(
                    shard for shard in self.manifest.shards_of(job) if shard.row[job.key] == entry.row[job.key]
                )
                for name in TierManifest.report_names(job, entry.row, shard.reports):
                    shortened["reports"][entry.job].remove(name)
            if entry.row is None or not shortened["matrix"][entry.job]["include"]:
                shortened["jobs"].remove(entry.job)
                shortened["matrix"].pop(entry.job, None)
                del shortened["reports"][entry.job]
            left.append(entry.context)
        if left:
            shortened["local"] = left
        return shortened


class LocalPasses:
    """Which of a commit's statuses are the owner's standing local passes."""

    @staticmethod
    def accepted(statuses: Iterable[object], owner: str) -> list[str]:
        """The ``local/`` contexts whose newest status by `owner` is a success.

        `statuses` is the commit-statuses listing, or its pages. Anyone with
        write access can post a status, so only the repository owner's count,
        and a later failure by the owner withdraws an earlier pass.
        """

        newest: dict[str, tuple[tuple[str, int], str]] = {}
        for status in statuses:
            for item in status if isinstance(status, list) else [status]:
                if not isinstance(item, Mapping):
                    continue
                context, creator = item.get("context"), item.get("creator")
                login = creator.get("login") if isinstance(creator, Mapping) else None
                if (
                    not isinstance(context, str)
                    or not context.startswith(CONTEXT_PREFIX)
                    or not owner
                    or login != owner
                ):
                    continue
                identity = item.get("id")
                age = (str(item.get("created_at") or ""), identity if isinstance(identity, int) else 0)
                if context not in newest or age > newest[context][0]:
                    newest[context] = (age, str(item.get("state")))
        return sorted(context for context, (_, state) in newest.items() if state == "success")
