#!/usr/bin/env bash
# Bucket-2 Mac checkpoints. --dry-run prints the same argv plan on any host.
# Measurements compose the existing helpers; no measurements run on Linux.
set -euo pipefail
exec python3 - "$0" "$@" <<'PY'
import argparse
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
QuietCheck(Path(sys.argv[2]), settings).wait()
raise SystemExit(subprocess.call(sys.argv[3:]))
"""


def options(arguments):
    parser = argparse.ArgumentParser(description=__doc__ or "Mac bucket-2 checkpoint; Linux supports --dry-run")
    parser.add_argument("--parent")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--budget", metavar="SCENARIOS")
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--btrsmith", type=Path)
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
        self.workspace = self.bsm or Path(os.environ.get("BSM_WORKSPACE", str(cache / "bsm-measure")))
        self.bsm_shell = self.bsm or Path(os.environ.get("BTRSMITH_DEV_SHELL", str(cache / "gcroots/btrsmith-dev")))
        self.compiler = os.environ.get("BTRCC_CC", "/usr/bin/clang")
        self.results = {"host_provenance": HOST, "binaries": {}, "deltas_percent": {}, "gate": "not-run"}
        self.failed = False

    def command(self, *argv, log=None):
        argv = [str(arg) for arg in argv]
        print(shlex.join(argv), flush=True)
        if self.args.dry_run:
            return ""
        result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if log:
            Path(log).write_text(result.stdout)
        print(result.stdout, end="", flush=True)
        if result.returncode:
            raise RuntimeError(f"command exited {result.returncode}: {shlex.join(argv)}")
        return result.stdout

    def helper(self, name):
        return self.helpers / name

    def environment(self, tree):
        env = ["env", f"BTRC_REPO={tree}", f"BTRC_DEV_SHELL={tree}", f"BTRCC_CC={self.compiler}"]
        env += [f"BSM_WORKSPACE={self.workspace}", f"BTRSMITH_DEV_SHELL={self.bsm_shell}"]
        return env

    def reader_shell(self, tree):
        # bsm_env.sh's historical READER default predates these compiler revisions.
        # Resolve the reader in the measured tree's shell, then preserve it when
        # the helper enters BTRSmith's shell.
        return ["nix", "develop", tree, "--command", "bash", "-c",
                'export READER="${BTRC_NATIVE_HEADER_READER:?missing native header reader}"; exec "$@"', "checkpoint"]

    def prepare(self, revision):
        if not self.args.dry_run:
            revision = self.command("git", "-C", self.repo, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()
        tree = self.root / revision
        if self.logs == tree or tree in self.logs.parents:
            raise RuntimeError("--logdir must not be inside a measurement worktree")
        binary = tree / "build/ccompat/btrcc"
        self.command("mkdir", "-p", self.root)
        if not self.args.dry_run and tree.exists():
            head = self.command("git", "-C", tree, "rev-parse", "HEAD").strip()
            dirty = self.command("git", "-C", tree, "status", "--porcelain").strip()
            if head != revision or dirty:
                raise RuntimeError(f"existing checkpoint worktree is not clean at {revision}: {tree}")
        else:
            self.command("git", "-C", self.repo, "worktree", "add", "--detach", tree, revision)
        self.command("mkdir", "-p", binary.parent)
        self.command(*self.environment(tree), self.helper("withlock.sh"), "btrcc-build",
                     self.helper("build_btrcc.sh"), binary, log=self.logs / f"build-{revision}.log")
        version = self.command(self.compiler, "--version")
        self.results["binaries"][revision] = {
            "path": str(binary), "c_compiler": self.compiler, "c_compiler_version": version.strip(),
            "size_bytes": None if self.args.dry_run else binary.stat().st_size, "samples": [],
        }
        return revision, tree, binary

    def memory(self, builds):
        for sample in range(1, 4):
            for role, (revision, tree, binary) in builds.items():
                tag = f"{role}-{sample}"
                output = self.command(
                    *self.environment(tree), f"BTRC_BENCH_HOME={self.logs}", self.helper("withlock.sh"),
                    "bench", *self.reader_shell(tree), self.helper("instr.sh"), binary, tag,
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
            print("# Compare medians of three alternating samples; flag >0.3%, fail footprint >1%.")
            return
        for row in self.results["binaries"].values():
            for metric in ("instructions_retired", "peak_footprint_bytes"):
                row[metric] = statistics.median(sample[metric] for sample in row["samples"])
        before, after = (self.results["binaries"][builds[role][0]] for role in ("parent", "commit"))
        for metric in ("instructions_retired", "peak_footprint_bytes", "size_bytes"):
            self.results["deltas_percent"][metric] = (after[metric] - before[metric]) * 100 / before[metric]
        self.results["flags"] = [key for key, value in self.results["deltas_percent"].items() if value > 0.3]
        self.failed = self.results["deltas_percent"]["peak_footprint_bytes"] > 1

    def budget(self, builds):
        for role, (_, tree, binary) in builds.items():
            for frontend in ("reference", "selfhost"):
                bench = [*self.environment(tree), *self.reader_shell(tree), self.helper("bench.sh"), tree,
                         binary if frontend == "selfhost" else "", self.logs / f"budget-{role}-{frontend}",
                         "--frontend", frontend, "--scenarios", self.args.budget]
                if (self.repo / "tools/runbook/quiet.py").is_file():
                    # Keep the quiet check and its measurement inside the same bench lock.
                    self.command(self.helper("withlock.sh"), "bench", "python3", "-c", QUIET,
                                 self.repo, tree, *bench, log=self.logs / f"budget-{role}-{frontend}.log")
                else:
                    print("# No automated quiet check: the wall-clock half needs a quiet window.")
                    if not self.args.dry_run:
                        raise RuntimeError("budget measurement deferred until the automated quiet check is available")
                    self.command(self.helper("withlock.sh"), "bench", *bench)

    def gate(self, tree, base):
        args = [self.helper("withlock.sh"), "gate", self.helper("batch_gate.sh"), tree, self.logs / "gate", base]
        if self.bsm:
            args.append(self.bsm)
        self.results["gate"] = "running"
        self.command(*args, log=self.logs / "gate.log")
        if not self.args.dry_run:
            summary = (self.logs / "gate/summary.txt").read_text()
            if not re.search(r"^total .* result=GREEN(?: |$)", summary, re.MULTILINE):
                raise RuntimeError("gate did not record GREEN")
            self.results["gate"] = "GREEN"

    def pin(self, revision):
        if self.failed:
            raise RuntimeError("memory regression prevents the BTRSmith pin update")
        if not self.args.dry_run and self.results["gate"] != "GREEN":
            raise RuntimeError("BTRSmith pin update requires a GREEN gate")
        print("# Only after GREEN: update and verify the actual pinned flake, then commit and push.")
        branch = self.command("git", "-C", self.bsm, "branch", "--show-current").strip()
        status = self.command("git", "-C", self.bsm, "status", "--porcelain").strip()
        if not self.args.dry_run and (branch != "main" or status):
            raise RuntimeError("BTRSmith pin update requires a clean main checkout")
        self.command("git", "-C", self.bsm, "fetch", "origin", "main")
        ahead = self.command("git", "-C", self.bsm, "rev-list", "--left-right", "--count", "HEAD...origin/main")
        if not self.args.dry_run and ahead.split() != ["0", "0"]:
            raise RuntimeError("BTRSmith main must equal origin/main before the pin update")
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
        self.results["result"] = "RED" if self.failed else "GREEN"
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
        if "error" in self.results:
            lines.append(self.results["error"])
        if "btrsmith_commit" in self.results:
            lines.append(f"BTRSmith: {self.results['btrsmith_commit']}")
        (self.logs / "summary.txt").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))

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
            builds = {}
            if self.args.parent:
                builds["parent"] = self.prepare(self.args.parent)
            builds["commit"] = self.prepare(self.args.commit)
            if self.args.memory:
                if builds["parent"][0] == builds["commit"][0]:
                    raise RuntimeError("--memory revisions resolve to the same commit")
                self.memory(builds)
            if self.args.budget:
                self.budget(builds)
            if self.args.gate:
                base = builds["parent"][0] if "parent" in builds else f"{builds['commit'][0]}^"
                self.gate(builds["commit"][1], base)
            if self.args.bump_btrsmith_pin:
                self.pin(builds["commit"][0])
        except (RuntimeError, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
            self.failed = True
            self.results["error"] = str(error) or "checkpoint interrupted"
            if self.results["gate"] == "running":
                self.results["gate"] = "RED"
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
