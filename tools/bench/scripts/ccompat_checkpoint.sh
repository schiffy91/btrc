#!/usr/bin/env bash
# Bucket-2 Mac checkpoints. --dry-run prints the same argv plan on any host.
# Measurements compose the existing helpers; no measurements run on Linux.
set -euo pipefail
exec python3 - "$0" "$@" <<'PY'
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import platform
import re
import shlex
import statistics
import subprocess
import sys


HOST = "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0"
QUIET = """import subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools.runbook.quiet import QuietCheck, QuietSettings
settings = QuietSettings().load(Path.home() / '.cache/btrc/runbook/quiet.toml')
print("Waiting for an automated quiet window", flush=True)
QuietCheck(Path(sys.argv[2]), settings, say=lambda message: print(message, flush=True)).wait()
print("Quiet window ready; starting measurement", flush=True)
raise SystemExit(subprocess.call(sys.argv[3:], timeout=12 * 60 * 60))
"""


def options(arguments):
    parser = argparse.ArgumentParser(description=__doc__ or "Mac bucket-2 checkpoint; Linux supports --dry-run")
    parser.add_argument("--parent")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--budget", metavar="SCENARIOS")
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--btrsmith", type=Path, help="gate and pin checkout; never the measurement workspace")
    parser.add_argument("--workspace", type=Path, help="measurement workspace (default: D9-pinned BSM_WORKSPACE)")
    parser.add_argument("--bump-btrsmith-pin", action="store_true")
    parser.add_argument("--logdir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(arguments)
    if not (args.memory or args.budget or args.gate):
        parser.error("choose --memory, --budget or --gate")
    if args.memory and not args.parent:
        parser.error("--memory requires --parent")
    if args.memory and args.parent == args.commit:
        parser.error("--memory needs two different revisions")
    if args.bump_btrsmith_pin and not (args.gate and args.btrsmith):
        parser.error("--bump-btrsmith-pin requires --gate and --btrsmith")
    for revision in (args.parent, args.commit):
        if revision is not None and not re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
            parser.error("--parent and --commit must be hexadecimal commit SHAs (7–40 characters)")
    if args.budget and not re.fullmatch(r"[a-z][a-z0-9-]*(,[a-z][a-z0-9-]*)*", args.budget):
        parser.error("--budget requires comma-separated scenario names")
    return args


class Checkpoint:
    def __init__(self, args, script):
        self.args = args
        self.helpers = Path(script).resolve().parent
        self.repo = self.helpers.parents[2]
        self.root = Path.home() / ".cache/btrc/bench.noindex/ccompat"
        self.logs = args.logdir.expanduser().absolute()
        self.bsm = args.btrsmith.expanduser().absolute() if args.btrsmith else None
        cache = Path(os.environ.get("BTRC_BENCH_HOME", str(Path.home() / ".cache/btrc")))
        self.workspace = (args.workspace or Path(os.environ.get("BSM_WORKSPACE", str(cache / "bsm-measure")))).expanduser().absolute()
        self.bsm_shell = Path(os.environ.get("BTRSMITH_DEV_SHELL", str(cache / "gcroots/btrsmith-dev"))).expanduser().absolute()
        self.pkg_config = Path(os.environ.get("BSM_PKG_CONFIG_PATH", str(cache / "measure/bsm-pkg-config-path.txt"))).expanduser().absolute()
        self.compiler = os.environ.get("BTRCC_CC", "/usr/bin/clang")
        self.results = {"host_provenance": HOST, "binaries": {}, "deltas_percent": {}, "gate": "not-run"}
        self.failed = False
        self.completed = False
        self.results.update(measurement="not-run", budget_reports=[], worktrees={}, errors=[])

    def command(self, *argv, log=None):
        argv = [str(arg) for arg in argv]
        print(shlex.join(argv), flush=True)
        if self.args.dry_run:
            return ""
        chunks = []
        with (Path(log).open("w") if log else nullcontext()) as stream:
            with subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                try:
                    for line in process.stdout:
                        chunks.append(line)
                        print(line, end="", flush=True)
                        if stream:
                            stream.write(line)
                            stream.flush()
                    status = process.wait(timeout=60)
                except BaseException:
                    process.kill()
                    process.wait(timeout=60)
                    raise
        if status:
            raise RuntimeError(f"command exited {status}: {shlex.join(argv)}")
        return "".join(chunks)

    def helper(self, name):
        return self.helpers / name

    def environment(self, tree):
        env = ["env", f"BTRC_REPO={tree}", f"BTRC_DEV_SHELL={tree}", f"BTRCC_CC={self.compiler}"]
        env += [f"BSM_WORKSPACE={self.workspace}", f"BTRSMITH_DEV_SHELL={self.bsm_shell}",
                f"BSM_PKG_CONFIG_PATH={self.pkg_config}"]
        return env

    def reader_shell(self, tree):
        # bsm_env.sh's historical READER default predates these compiler revisions.
        # Resolve the reader in the measured tree's shell, then preserve it when
        # the helper enters BTRSmith's shell.
        reader = self.results.get("readers", {}).get(tree.name)
        if reader:
            return ["nix", "develop", tree, "--command", "env", f"READER={reader}"]
        return ["nix", "develop", tree, "--command", "bash", "-c",
                'export READER="${BTRC_NATIVE_HEADER_READER:?missing native header reader}"; exec "$@"', "checkpoint"]

    def prepare(self, revision, *, build=True):
        if not self.args.dry_run:
            revision = self.command("git", "-C", self.repo, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()
        tree = self.root / revision
        if self.logs == tree or tree in self.logs.parents:
            raise RuntimeError("--logdir must not be inside a measurement worktree")
        binary = tree / "build/ccompat/btrcc"
        if self.args.dry_run and not build and revision in self.results["worktrees"]:
            return revision, tree, binary
        self.command("mkdir", "-p", self.root)
        if not self.args.dry_run and tree.exists():
            head = self.command("git", "-C", tree, "rev-parse", "HEAD").strip()
            dirty = self.command("git", "-C", tree, "status", "--porcelain").strip()
            if head != revision or dirty:
                raise RuntimeError(f"existing checkpoint worktree is not clean at {revision}: {tree}")
        else:
            self.command("git", "-C", self.repo, "worktree", "add", "--detach", tree, revision)
        self.results["worktrees"][revision] = {
            "path": str(tree),
            "cleanup": shlex.join(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(tree)]),
        }
        if not build:
            return revision, tree, binary
        self.command("mkdir", "-p", binary.parent)
        self.command(*self.environment(tree), self.helper("withlock.sh"), "btrcc-build",
                     self.helper("build_btrcc.sh"), binary, log=self.logs / f"build-{revision}.log")
        version = self.command(self.compiler, "--version")
        self.results["binaries"][revision] = {
            "path": str(binary), "c_compiler": self.compiler, "c_compiler_version": version.splitlines()[0] if version else "",
            "size_bytes": None if self.args.dry_run else binary.stat().st_size, "samples": [],
        }
        return revision, tree, binary

    def quiet_measurement(self, workspace, *argv, log):
        if not (self.repo / "tools/runbook/quiet.py").is_file():
            raise RuntimeError("measurement deferred until the automated quiet check is available")
        # Hold one lock across the quiet window and the measurement it qualifies.
        return self.command(self.helper("withlock.sh"), "bench", "nix", "develop", self.repo,
                     "--command", "python3", "-u", "-c", QUIET,
                     self.repo, workspace, *argv, log=log)

    def memory(self, builds):
        for sample in range(1, 4):
            for role, (revision, tree, binary) in builds.items():
                tag = f"{role}-{sample}"
                output = self.quiet_measurement(
                    self.workspace, *self.environment(tree), f"BTRC_BENCH_HOME={self.logs}",
                    *self.reader_shell(tree), self.helper("instr.sh"), binary, tag,
                    log=self.logs / f"{tag}.log")
                if self.args.dry_run:
                    continue
                # instr.sh reports the compiler's status in stdout but does not propagate it.
                match = re.search(r"rc=0\s+\S+\s+instructions=(\d+) peak-footprint=(\d+)", output)
                if not match or min(map(int, match.groups())) <= 0:
                    raise RuntimeError(f"{tag}: failed compile or missing instruction/footprint counters")
                self.results["binaries"][revision]["samples"].append({
                    "instructions_retired": int(match[1]), "peak_footprint_bytes": int(match[2]),
                })
        if self.args.dry_run:
            print("# Compare medians of three alternating samples; flag either metric >0.3%, fail either metric >1%.")
            return
        for row in self.results["binaries"].values():
            for metric in ("instructions_retired", "peak_footprint_bytes"):
                row[metric] = statistics.median(sample[metric] for sample in row["samples"])
        before, after = (self.results["binaries"][builds[role][0]] for role in ("parent", "commit"))
        for metric in ("instructions_retired", "peak_footprint_bytes"):
            self.results["deltas_percent"][metric] = (after[metric] - before[metric]) * 100 / before[metric]
        self.results["flags"] = [key for key, value in self.results["deltas_percent"].items() if value > 0.3]
        self.failed |= any(value > 1 for value in self.results["deltas_percent"].values())

    def budget(self, builds):
        for role, (_, tree, binary) in builds.items():
            for frontend in ("reference", "selfhost"):
                bench = [*self.environment(tree), *self.reader_shell(tree), self.helper("bench.sh"), tree,
                         binary if frontend == "selfhost" else "", self.logs / f"budget-{role}-{frontend}",
                         "--frontend", frontend, "--scenarios", self.args.budget]
                self.results["budget_reports"].append(str(self.logs / f"budget-{role}-{frontend}" / "report.json"))
                # BudgetHarness measures its copy at <out>/ws, not the compiler tree.
                self.quiet_measurement(self.logs / f"budget-{role}-{frontend}" / "ws", *bench,
                                       log=self.logs / f"budget-{role}-{frontend}.log")

    def gate(self, tree, base):
        args = [self.helper("withlock.sh"), "gate", self.helper("batch_gate.sh"), tree, self.logs / "gate", base]
        if self.bsm:
            args.append(self.bsm)
        self.results["gate"] = "running"
        self.command(*args, log=self.logs / "gate.log")
        if not self.args.dry_run:
            summary = (self.logs / "gate/summary.txt").read_text()
            self.results["gate_summary"] = summary
            if not re.search(r"^total .* result=GREEN(?: |$)", summary, re.MULTILINE):
                raise RuntimeError("gate did not record GREEN")
            self.results["gate"] = "GREEN"

    def pin_preflight(self):
        branch = self.command("git", "-C", self.bsm, "branch", "--show-current").strip()
        status = self.command("git", "-C", self.bsm, "status", "--porcelain").strip()
        if not self.args.dry_run and (branch != "main" or status):
            raise RuntimeError("BTRSmith pin update requires a clean main checkout")
        self.command("git", "-C", self.bsm, "fetch", "origin", "main")
        ahead = self.command("git", "-C", self.bsm, "rev-list", "--left-right", "--count", "HEAD...origin/main")
        if not self.args.dry_run and ahead.split() != ["0", "0"]:
            raise RuntimeError("BTRSmith main must equal origin/main before the pin update")

    def pin(self, revision):
        if self.failed:
            raise RuntimeError("checkpoint failure prevents the BTRSmith pin update")
        if not self.args.dry_run and self.results["gate"] != "GREEN":
            raise RuntimeError("BTRSmith pin update requires a GREEN gate")
        print("# Only after GREEN: update and verify the actual pinned flake, then commit and push.")
        self.pin_preflight()
        self.command("nix", "flake", "lock", str(self.bsm), "--update-input", "btrc")
        print(f"# Verify flake.lock btrc revision equals gated commit {revision}.")
        if not self.args.dry_run:
            lock = json.loads((self.bsm / "flake.lock").read_text())
            node = lock["nodes"][lock["root"]]["inputs"]["btrc"]
            if lock["nodes"][node]["locked"].get("rev") != revision:
                raise RuntimeError("updated BTRSmith pin differs from the gated btrc commit; refusing publication")
        # -C is a make argument: nix's shell stays pinned, with no override-input.
        self.command("nix", "develop", self.bsm, "--command", "make", "-C", self.bsm, "application-frontend-check")
        for frontend in ("reference", "selfhost"):
            self.command("nix", "develop", self.bsm, "--command", "make", "-C", self.bsm,
                         "btrsmith-library-smoke", f"BTRC_FRONTEND={frontend}")
        self.command("git", "-C", self.bsm, "-c", "commit.gpgsign=false", "commit", "--no-gpg-sign",
                     "--only", "flake.lock", "-m", f"chore: pin btrc checkpoint {revision}")
        self.command("git", "-C", self.bsm, "push", "origin", "HEAD:main")
        self.results["btrsmith_commit"] = self.command("git", "-C", self.bsm, "rev-parse", "HEAD").strip()

    def summary(self):
        if self.args.dry_run:
            print(f"# Write {self.logs / 'summary.json'} and {self.logs / 'summary.txt'}; planned host: {HOST}.")
            return
        self.results["result"] = "GREEN" if self.completed and not self.failed else "RED"
        report = json.dumps(self.results, indent=2) + "\n"
        (self.logs / "summary.json").write_text(report)
        lines = [f"{self.results['result']}: {HOST}", f"gate: {self.results['gate']}"]
        for revision, row in self.results["binaries"].items():
            lines.append(f"{revision}: {row['c_compiler_version']}; binary {row['size_bytes']} bytes")
            for metric in ("instructions_retired", "peak_footprint_bytes"):
                if metric in row:
                    lines.append(f"  {metric}: {row[metric]}")
        for metric, value in self.results["deltas_percent"].items():
            lines.append(f"{metric}: {value:+.3f}%" + (" FLAG (>0.3%)" if value > 0.3 else ""))
        lines.append(f"measurement: {self.results['measurement']}")
        if "workspace" in self.results:
            lines.append(f"workspace: {self.results['workspace']}")
        for revision, reader in self.results.get("readers", {}).items():
            lines.append(f"reader {revision}: {reader}")
        if "gate_summary" in self.results:
            lines += ["gate steps:", self.results["gate_summary"].rstrip()]
        lines += [f"budget report: {path}" for path in self.results["budget_reports"]]
        lines += [f"retained worktree: {row['path']}\ncleanup: {row['cleanup']}"
                  for row in self.results["worktrees"].values()]
        if "error" in self.results:
            lines.append(self.results["error"])
        if "btrsmith_commit" in self.results:
            lines.append(f"BTRSmith: {self.results['btrsmith_commit']}")
        (self.logs / "summary.txt").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))

    def record_failure(self, error):
        self.failed = True
        detail = str(error) or "checkpoint interrupted"
        self.results["errors"].append(detail)
        self.results["error"] = "; ".join(self.results["errors"])

    def provenance(self, builds):
        if not self.args.dry_run and not self.pkg_config.is_file():
            raise RuntimeError(f"missing measurement package configuration: {self.pkg_config}")
        head = self.command("git", "-C", self.workspace, "rev-parse", "HEAD").strip()
        self.results["workspace"] = {
            "path": str(self.workspace), "head": head,
            "dev_shell": str(self.bsm_shell), "pkg_config_path": str(self.pkg_config),
        }
        self.results["readers"] = {}
        for revision, tree, _ in builds.values():
            output = self.command(*self.reader_shell(tree), "bash", "-c", 'printf "CHECKPOINT_READER=%s\\n" "$READER"')
            readers = re.findall(r"^CHECKPOINT_READER=(/[^\n]+)$", output, re.MULTILINE)
            if not self.args.dry_run and len(readers) != 1:
                raise RuntimeError(f"missing or ambiguous native reader provenance for {revision}")
            self.results["readers"][revision] = readers[0] if readers else ""

    def run(self):
        if not self.args.dry_run and platform.system() != "Darwin":
            raise RuntimeError("real checkpoints require macOS; use --dry-run on this host")
        # Output and measurement trees must never alias: repeated instruction samples remove their own outputs.
        if self.logs == self.root or self.logs in self.root.parents:
            raise RuntimeError("--logdir must be a checkpoint subdirectory, not an ancestor of the worktree root")
        if (self.args.memory or self.args.budget) and self.root.parent not in self.logs.parents:
            raise RuntimeError("measurement --logdir must be under ~/.cache/btrc/bench.noindex/")
        self.command("mkdir", "-p", self.logs)
        try:
            # Fail pin preconditions before any multi-hour work and recheck at publication.
            if self.args.bump_btrsmith_pin:
                self.pin_preflight()
            measuring = bool(self.args.memory or self.args.budget)
            if measuring:
                self.results["measurement"] = "running"
                try:
                    builds = {}
                    if self.args.parent:
                        builds["parent"] = self.prepare(self.args.parent)
                    builds["commit"] = self.prepare(self.args.commit)
                    self.provenance(builds)
                    if self.args.memory:
                        if builds["parent"][0] == builds["commit"][0]:
                            raise RuntimeError("--memory revisions resolve to the same commit")
                        self.memory(builds)
                    if self.args.budget:
                        self.budget(builds)
                    self.results["measurement"] = "RED" if self.failed else "GREEN"
                except Exception as error:
                    self.record_failure(error)
                    self.results["measurement"] = "RED"
            # Reopen the commit independently: even a parent build/provenance failure
            # must not suppress the correctness gate.
            if self.args.gate:
                self.results["gate"] = "running"
                try:
                    revision, tree, _ = self.prepare(self.args.commit, build=False)
                    base = self.args.parent or f"{revision}^"
                    self.gate(tree, base)
                except Exception as error:
                    self.record_failure(error)
                    self.results["gate"] = "RED"
            if self.args.bump_btrsmith_pin and not self.failed:
                self.pin(revision)
            self.completed = True
        except BaseException as error:
            self.record_failure(error)
            if self.results["gate"] == "running":
                self.results["gate"] = "RED"
            if self.results["measurement"] == "running":
                self.results["measurement"] = "RED"
        finally:
            self.summary()
        return int(self.failed)


if __name__ == "__main__":
    try:
        raise SystemExit(Checkpoint(options(sys.argv[2:]), sys.argv[1]).run())
    except RuntimeError as error:
        print(f"checkpoint: {error}", file=sys.stderr)
        raise SystemExit(2)
PY
