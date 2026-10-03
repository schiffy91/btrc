"""Publish a runbook run: summary.json, the qualification ledger, the evidence branch.

``EvidencePublisher`` turns a run's checkpoints into:

- ``summary.json`` and ``summary.txt`` in the run's workspace: every cell's
  status, and per scenario the median, p95, maximum and sample count; the
  failures; the budgets a report misses; and the provenance (the exact host
  string, the clang that built btrcc, every SHA, the btrcc digest and the
  stdlib tree digest, because Codex's stdlib changes can move the measured
  workload under a fixed BTRSmith pin);
- ledger records, through ``python3 -m tools.qualification ingest
  --budget-bench <report> --this-host`` for every acceptance budget_bench report;
- a redacted, secret-scanned copy of the summaries (never raw logs) committed
  without touching any working tree and pushed, fast-forward only, to the
  never-merged ``evidence/<preset>-<date>`` branch (WORKSTREAMS.md §7 Q24).

Rehearsals, stand-ins and dry runs write the summary and stage the copy, but
never ingest or push.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.runbook.engine import ACCEPTANCE_HOST, CellOutcome, Evidence, Git, Host, RunbookError, RunState

if TYPE_CHECKING:
    from tools.runbook.engine import Budget, RunbookEngine

INGEST_TIMEOUT_S = 900
SCAN_TIMEOUT_S = 600

# Built-in secret patterns; gitleaks, when installed, scans as well.
SECRET_PATTERNS = (
    ("private key", r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"),
    ("OpenAI/Anthropic key", r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    (
        "credential assignment",
        r"(?i)\b(?:password|passwd|secret|api_key|apikey|access_token)\s*[=:]\s*['\"][^'\"\s]{8,}",
    ),
    ("home path", r"/(?:Users|home)/(?!<redacted>)[A-Za-z0-9._-]+"),
)


class Redactor:
    """Replace the owner's home, any other user's home path and the host name with placeholders."""

    PRIVATE_KEYS = frozenset({"node", "hostname", "user", "username"})

    def __init__(self, home: Path | None = None) -> None:
        self.home = str(home or Path.home())

    def text(self, text: str) -> str:
        if self.home and self.home != "/":
            text = text.replace(self.home, "~")
        return re.sub(r"/(Users|home)/[A-Za-z0-9._-]+", r"/\1/<redacted>", text)

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            # platform.uname()'s node is the Mac's network name; it never leaves the machine.
            return {
                self.text(str(key)): "<redacted>" if key in self.PRIVATE_KEYS else self.value(item)
                for key, item in value.items()
            }
        return value


class SecretScan:
    """The built-in patterns over every staged file, plus gitleaks when it is on PATH."""

    @staticmethod
    def builtin(root: Path) -> list[str]:
        findings: list[tuple[str, int, str]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(errors="replace")
            for label, pattern in SECRET_PATTERNS:
                for match in re.finditer(pattern, text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append((path.relative_to(root).as_posix(), line, label))
        return [f"{name}:{line}: {label}" for name, line, label in sorted(findings)]

    @staticmethod
    def gitleaks(root: Path) -> tuple[str, list[str]]:
        """(status, findings): status is clean, findings, not installed or an error."""

        if shutil.which("gitleaks") is None:
            return "not installed", []
        report = root.parent / f"{root.name}.gitleaks.json"
        attempts = (
            ["gitleaks", "dir", str(root), "--no-banner", "--redact", "--report-format", "json"],
            [
                "gitleaks",
                "detect",
                "--no-git",
                "--source",
                str(root),
                "--no-banner",
                "--redact",
                "--report-format",
                "json",
            ],
        )
        for command in attempts:
            try:
                completed = subprocess.run(
                    [*command, "--report-path", str(report), "--exit-code", "3"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=SCAN_TIMEOUT_S,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                return f"error: {error}", []
            if completed.returncode in (0, 3):
                found = json.loads(report.read_text() or "[]") if report.is_file() else []
                report.unlink(missing_ok=True)
                names = [
                    f"{item.get('File', '?')}:{item.get('StartLine', '?')}: {item.get('RuleID', '?')}" for item in found
                ]
                return ("findings" if names else "clean"), names
        return f"error: {completed.stderr.strip()[-300:]}", []


class EvidencePublisher:
    """Summarize, ingest, redact, scan and push one run's evidence."""

    def __init__(self, engine: RunbookEngine, state: RunState, outcomes: Sequence[CellOutcome]) -> None:
        self.engine = engine
        self.state = state
        self.outcomes = list(outcomes)
        self.options = engine.options
        self.redactor = Redactor()

    @property
    def branch(self) -> str:
        return f"evidence/{self.state.run_id}"

    # -- the summary

    def provenance(self) -> dict[str, object]:
        from tools.qualification.adapters import HostProvenance

        frozen = self.engine.frozen
        clone = self.engine.btrc_clone()
        shas = frozen.get("shas", {})
        host = HostProvenance(clone).summary()
        btrcc = self.options.btrcc or self.state.work / "btrcc" / "btrcc"
        clang = Host.first_line("/usr/bin/clang", "--version") if Path("/usr/bin/clang").exists() else None
        stdlib = None
        if shas.get("btrc") and Git.ok("rev-parse", "--verify", "--quiet", f"{shas['btrc']}:src/stdlib", cwd=clone):
            stdlib = Git.run("rev-parse", f"{shas['btrc']}:src/stdlib", cwd=clone)
        builders = [outcome for outcome in self.outcomes if self.provides_btrcc(outcome.id)]
        build_log = (
            Path(builders[0].log) if builders and builders[0].log else btrcc.with_name(btrcc.name + ".build.log")
        )
        return {
            "host": host,
            "host_matches_acceptance": host == ACCEPTANCE_HOST,
            "acceptance_host": ACCEPTANCE_HOST,
            "system": f"{platform.system()} {platform.release()} {platform.machine()}",
            "clang": clang or Host.first_line("clang", "--version"),
            "python": sys.version.split()[0],
            "nix": Host.first_line("nix", "--version"),
            "btrc": {"ref": frozen["refs"]["btrc"], "sha": shas.get("btrc")},
            "btrsmith": {
                label: {"ref": ref, "sha": shas.get("btrsmith", {}).get(label)}
                for label, ref in frozen["refs"]["btrsmith"].items()
            },
            "trees": shas.get("trees", {}),
            "stdlib_tree": stdlib,
            "btrcc": {
                "path": str(btrcc),
                "sha256": Evidence.digest(btrcc),
                "entry": self.engine.host.entry(),
                "build": self.build_line(build_log),
                "given": self.options.btrcc is not None,
            },
        }

    def provides_btrcc(self, cell_id: str) -> bool:
        return any(cell.id == cell_id and cell.provides == "btrcc" for cell in self.engine.cells)

    @staticmethod
    def build_line(log: Path) -> str | None:
        """build_btrcc.sh's verdict, which names the C compiler that built btrcc."""

        if not log.is_file():
            return None
        lines = [line for line in log.read_text(errors="replace").splitlines() if line.strip()]
        verdicts = [line for line in lines if line.startswith(("BUILD OK", "BUILD FAIL"))]
        return (verdicts or lines or [""])[-1][:300] or None

    def misses(self, outcome: CellOutcome) -> list[dict[str, object]]:
        """The preset's budgets this budget-bench cell's report misses (findings, not failures)."""

        missed: list[dict[str, object]] = []
        scenarios = outcome.results.get("scenarios", {})
        frontend = outcome.variables.get("frontend") or outcome.results.get("frontend")
        if not isinstance(scenarios, dict):
            return missed
        budget: Budget
        for budget in self.engine.preset.budgets:
            if budget.frontend and budget.frontend != frontend:
                continue
            summary = scenarios.get(budget.scenario)
            if not isinstance(summary, dict):
                continue
            value = summary.get("facts", {}).get(budget.fact) if budget.fact else summary.get(budget.statistic or "")
            if isinstance(value, int | float) and value > budget.limit:
                missed.append(
                    {
                        "cell": outcome.id,
                        "pin": outcome.variables.get("pin"),
                        "frontend": frontend,
                        "budget": budget.describe(),
                        "value": value,
                        "limit": budget.limit,
                    }
                )
        return missed

    def regressions(self) -> list[dict[str, object]]:
        """Compare scenarios with the same cell in an earlier run's summary.json (Stage 13 vs Stage 5)."""

        preset = self.engine.preset
        if not preset.regressions or not preset.baseline:
            return []
        path = Path(self.engine.describe(preset.baseline)).expanduser()
        if not path.is_file():
            return [{"ok": False, "message": f"baseline {path} is missing; copy the Stage 5 summary.json there"}]
        baseline = {cell["id"]: cell for cell in json.loads(path.read_text()).get("cells", [])}
        compared: list[dict[str, object]] = []
        for outcome in self.outcomes:
            scenarios = outcome.results.get("scenarios")
            earlier = baseline.get(outcome.id, {}).get("results", {}).get("scenarios", {})
            if not isinstance(scenarios, dict) or not earlier:
                continue
            for rule in preset.regressions:
                name, measure = rule["scenario"], rule.get("measure", "median")
                tolerance = float(rule.get("tolerance", 1.05))
                now, then = (self.measure(source.get(name), measure) for source in (scenarios, earlier))
                if now is None or then is None or then <= 0:
                    continue
                ratio = now / then
                compared.append(
                    {
                        "cell": outcome.id,
                        "scenario": name,
                        "measure": measure,
                        "baseline": then,
                        "value": now,
                        "ratio": round(ratio, 4),
                        "tolerance": tolerance,
                        "ok": ratio <= tolerance,
                    }
                )
        return compared

    @staticmethod
    def measure(summary: object, measure: str) -> float | None:
        if not isinstance(summary, dict):
            return None
        value = summary.get(measure)
        if value is None:
            value = summary.get("metric_medians", {}).get(measure)
        return float(value) if isinstance(value, int | float) else None

    def summarize(self) -> dict[str, object]:
        cells = []
        failures = []
        misses: list[dict[str, object]] = []
        for outcome in self.outcomes:
            entry = outcome.as_dict()
            cells.append(entry)
            if outcome.status not in CellOutcome.FINISHED:
                failures.append({"cell": outcome.id, "status": outcome.status, "message": outcome.message})
            if outcome.status == "passed" and "scenarios" in outcome.results:
                misses += self.misses(outcome)
        expected = [cell.id for cell in self.engine.cells]
        finished = {outcome.id for outcome in self.outcomes}
        missing = [cell_id for cell_id in expected if cell_id not in finished]
        result = "green" if not failures and not missing else "red" if failures else "incomplete"
        frozen = self.engine.frozen
        return {
            "schema": 1,
            "tool": "tools/runbook",
            "preset": self.engine.preset.name,
            "packet": self.engine.preset.packet,
            "title": self.engine.preset.title,
            "run": self.state.run_id,
            "started": frozen.get("started"),
            "written": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "mode": self.options.mode(),
            "acceptance": self.options.acceptance(),
            "result": result,
            "provenance": self.provenance(),
            "variables": frozen.get("variables", {}),
            "optional_not_requested": self.engine.optional_skipped,
            "cells": cells,
            "not_reached": missing,
            "failures": failures,
            "budget_misses": misses,
            "regressions": self.regressions(),
            "workspace": str(self.state.work),
            "raw_logs": str(self.state.logs),
        }

    # -- ingest

    def ingest(self, summary: dict[str, object]) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        reports = [outcome for outcome in self.outcomes if outcome.status == "passed" and "report" in outcome.results]
        if not reports:
            return records
        if not self.options.acceptance():
            reason = "rehearsal, stand-in or dry run: qualification takes acceptance runs only"
            return [{"cell": outcome.id, "status": "skipped", "message": reason} for outcome in reports]
        done = set(self.engine.frozen.get("ingested", []))
        for outcome in reports:
            if outcome.id in done:
                records.append({"cell": outcome.id, "status": "ingested earlier", "message": ""})
                continue
            report = str(outcome.results["report"])
            command = [
                sys.executable, "-m", "tools.qualification", "ingest", "--budget-bench", report, "--this-host",
                "--run", f"{self.state.run_id}-{outcome.id}",
            ]  # fmt: skip
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.engine.btrc_clone(),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=INGEST_TIMEOUT_S,
                )
                status = "ingested" if completed.returncode == 0 else f"exit {completed.returncode}"
                tail = (completed.stdout + completed.stderr).strip().splitlines()[-3:]
            except (OSError, subprocess.TimeoutExpired) as error:
                status, tail = "error", [str(error)]
            records.append({"cell": outcome.id, "status": status, "message": " | ".join(tail)})
            if status == "ingested":
                # The ledger appends; a rerun must not record the same samples twice.
                self.engine.frozen.setdefault("ingested", []).append(outcome.id)
                self.state.save(self.engine.frozen)
        return records

    # -- the redacted copy

    def stage(self, summary: Mapping[str, object]) -> Path:
        stage = self.state.work / "evidence" / self.state.run_id
        if stage.exists():
            shutil.rmtree(stage)
        (stage / "cells").mkdir(parents=True)
        redacted = self.redactor.value(dict(summary))
        (stage / "summary.json").write_text(json.dumps(redacted, indent=2) + "\n")
        (stage / "summary.txt").write_text(self.redactor.text(self.render_text(summary)) + "\n")
        for outcome in self.outcomes:
            for key, name in (("report", "report.json"), ("summary", "summary.txt")):
                source = Path(str(outcome.results.get(key, "")))
                if key in outcome.results and source.is_file():
                    target = stage / "cells" / outcome.id / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    text = source.read_text(errors="replace")
                    if name.endswith(".json"):
                        text = json.dumps(self.redactor.value(json.loads(text)), indent=2) + "\n"
                    target.write_text(self.redactor.text(text))
        return stage

    def scan(self, stage: Path) -> dict[str, object]:
        builtin = SecretScan.builtin(stage)
        gitleaks, leaks = SecretScan.gitleaks(stage)
        clean = not builtin and not leaks and not gitleaks.startswith("error")
        return {"clean": clean, "builtin": builtin, "gitleaks": gitleaks, "gitleaks_findings": leaks}

    # -- the branch

    def clone(self) -> Path:
        """The clone whose object store builds the evidence commit: btrc's, or BTRSmith's for private content."""

        if self.engine.preset.evidence_repo == "btrsmith" and self.engine.preset.branch_pin:
            return self.engine.btrsmith_clone(self.engine.preset.branch_pin)
        return self.engine.btrc_clone()

    def commit(self, stage: Path, remote: str, message: str) -> str:
        """A commit of ``stage`` on top of the remote branch (or none), built without a working tree."""

        clone = self.clone()
        parent = None
        listed = Git.run("ls-remote", "--heads", remote, self.branch, cwd=clone, timeout=300)
        if listed:
            Git.run("fetch", "--quiet", remote, f"refs/heads/{self.branch}", cwd=clone, timeout=900)
            parent = Git.run("rev-parse", "FETCH_HEAD", cwd=clone)
        with tempfile.TemporaryDirectory() as scratch:
            environment = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch) / "index"))
            for path in sorted(stage.rglob("*")):
                if not path.is_file():
                    continue
                blob = Git.run("hash-object", "-w", str(path), cwd=clone)
                relative = f"{self.state.run_id}/{path.relative_to(stage).as_posix()}"
                self.git_with(environment, clone, "update-index", "--add", "--cacheinfo", f"100644,{blob},{relative}")
            tree = self.git_with(environment, clone, "write-tree")
        identity = {
            "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "btrc runbook"),
            "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "runbook@btrc.invalid"),
        }
        identity |= {
            "GIT_COMMITTER_NAME": identity["GIT_AUTHOR_NAME"],
            "GIT_COMMITTER_EMAIL": identity["GIT_AUTHOR_EMAIL"],
        }
        arguments = ["-c", "commit.gpgsign=false", "commit-tree", tree, "-m", message]
        if parent:
            arguments += ["-p", parent]
        return self.git_with(dict(os.environ) | identity, clone, *arguments)

    @staticmethod
    def git_with(environment: Mapping[str, str], cwd: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            env=dict(environment) | {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            raise RunbookError(f"git {' '.join(arguments[:2])} failed: {completed.stderr.strip()[-400:]}")
        return completed.stdout.strip()

    def remote(self) -> str:
        if self.options.evidence_remote:
            return self.options.evidence_remote
        if self.engine.preset.evidence_repo == "btrsmith":
            # BTRSmith content (its test names, its logs) stays in the private repository (§7 Q24).
            return Evidence.upstream(self.engine.btrsmith_hub(), fallback="git@github.com:schiffy91/btrsmith.git")
        return Evidence.upstream(self.engine.btrc_hub(), fallback="git@github.com:schiffy91/btrc.git")

    def push(self, stage: Path, summary: Mapping[str, object]) -> dict[str, object]:
        remote = self.remote()
        message = (
            f"evidence: {self.engine.preset.name} {self.state.run_id} ({summary['result']})\n\n"
            f"Redacted runbook summaries; never merged (WORKSTREAMS.md §7 Q24).\n"
            f"btrc {summary['provenance']['btrc']['sha']}"  # type: ignore[index]
        )
        if remote.startswith(("git@", "ssh://")) and not self.engine.wait_for_ssh_agent():
            return {
                "pushed": False,
                "remote": remote,
                "branch": self.branch,
                "message": "the SSH agent has no identity: unlock 1Password, then rerun the same command to publish",
            }
        sha = self.commit(stage, remote, message)
        Git.run("push", remote, f"{sha}:refs/heads/{self.branch}", cwd=self.clone(), timeout=900)
        return {"pushed": True, "remote": remote, "branch": self.branch, "commit": sha}

    # -- everything

    def publish(self) -> dict[str, object]:
        summary = self.summarize()
        summary["ingest"] = self.ingest(summary)
        self.write(summary)
        stage = self.stage(summary)
        scan = self.scan(stage)
        summary["secret_scan"] = scan
        if not scan["clean"]:
            publication: dict[str, object] = {"pushed": False, "message": "the secret scan found something; not pushed"}
        elif not self.options.publish:
            publication = {"pushed": False, "message": "--no-publish"}
        elif not self.options.acceptance():
            publication = {
                "pushed": False,
                "message": f"rehearsal, stand-in or dry run: staged at {stage}, not pushed",
                "branch": self.branch,
            }
        else:
            try:
                publication = self.push(stage, summary)
            except RunbookError as error:
                publication = {"pushed": False, "message": f"push failed: {error}; rerun the same command to retry"}
            if publication.get("pushed") and summary["result"] == "green":
                self.engine.frozen["published"] = {"branch": self.branch, "commit": publication.get("commit")}
                self.state.save(self.engine.frozen)
        summary["publication"] = publication
        self.write(summary)
        return summary

    def write(self, summary: Mapping[str, object]) -> None:
        (self.state.work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (self.state.work / "summary.txt").write_text(self.render_text(summary) + "\n")

    def render_text(self, summary: Mapping[str, object]) -> str:
        provenance = summary["provenance"]
        assert isinstance(provenance, dict)
        lines = [
            f"{summary['preset']} {summary['run']}: {str(summary['result']).upper()}"
            + ("" if summary["acceptance"] else "  (rehearsal: not acceptance evidence)"),
            f"host {provenance['host']}"
            + ("" if provenance["host_matches_acceptance"] else f"  (acceptance host is {ACCEPTANCE_HOST})"),
            f"btrc {provenance['btrc']['sha']}  stdlib tree {provenance['stdlib_tree']}  clang {provenance['clang']}",
        ]
        for label, pin in provenance["btrsmith"].items():
            lines.append(f"BTRSmith {label}: {pin['ref']} = {pin['sha']}")
        lines.append("")
        for cell in summary["cells"]:  # type: ignore[union-attr]
            assert isinstance(cell, dict)
            duration = f"{cell['duration_s'] / 60:6.1f} min" if cell.get("duration_s") else " " * 10
            lines.append(f"  {cell['status']:8} {duration}  {cell['id']}  {cell.get('message') or ''}".rstrip())
            scenarios = cell.get("results", {}).get("scenarios", {})
            for name, values in scenarios.items():
                if values.get("median") is None:
                    continue
                lines.append(
                    f"      {name:22} median {values['median']:9.2f}  p95 {values['p95']:9.2f}  "
                    f"max {values['max']:9.2f}  n={values['samples']}"
                )
        for cell_id in summary.get("not_reached", []):  # type: ignore[union-attr]
            lines.append(f"  not run           {cell_id}")
        misses = summary.get("budget_misses") or []
        if misses:
            lines.append("")
            lines.append("Budgets missed (findings):")
            for miss in misses:  # type: ignore[union-attr]
                lines.append(f"  - {miss['cell']}: {miss['budget']}: measured {miss['value']}")
        regressed = [item for item in summary.get("regressions") or [] if not item.get("ok")]  # type: ignore[union-attr]
        if regressed:
            lines.append("")
            lines.append("Regressions against the baseline (findings):")
            for item in regressed:
                if "cell" not in item:
                    lines.append(f"  - {item['message']}")
                    continue
                lines.append(
                    f"  - {item['cell']} {item['scenario']} {item['measure']}: {item['value']} vs {item['baseline']} "
                    f"(x{item['ratio']}, allowed x{item['tolerance']})"
                )
        publication = summary.get("publication")
        lines.append("")
        lines.append(f"summary: {summary['workspace']}/summary.json   raw logs: {summary['raw_logs']}")
        if isinstance(publication, dict):
            if publication.get("pushed"):
                lines.append(f"evidence: pushed {publication['branch']} to {publication['remote']}")
            else:
                lines.append(f"evidence: {publication.get('message')}")
        lines.append(f"next: {self.next_action(summary)}")
        return "\n".join(lines)

    def next_action(self, summary: Mapping[str, object]) -> str:
        publication = summary.get("publication") or {}
        assert isinstance(publication, dict)
        if summary["result"] == "incomplete" or summary["failures"]:
            failed = ", ".join(str(item["cell"]) for item in summary["failures"])  # type: ignore[union-attr]
            return (
                f"red or unfinished ({failed or 'cells not reached'}). Read the logs above; rerun the same command "
                "to retry what failed (finished cells are not repeated), or paste summary.txt into the Claude session."
            )
        if not publication.get("pushed") and summary["acceptance"]:
            return f"{publication.get('message')}"
        return self.engine.preset.next_action or "nothing; the cloud agents read the evidence branch."
