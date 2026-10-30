"""Run and verify deterministic partitions of the complete GUI selection.

Collection and execution run inside the same platform session. A partition is
qualified only with exact JUnit/skip membership; a session requires the disjoint
union of all of its partitions. No test timeout or skip policy is changed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.qualification.skips import SkipGate, SkipReport

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "btrc.gui-partition/2"
LEGACY_SCHEMA = "btrc.gui-partition/1"
NODE_PROPERTY = "btrc.gui-shard-nodeid"


class GUIPartition:
    """An exact collection and the deterministic portion owned by one cell."""

    @staticmethod
    def nodes(values: object) -> list[str]:
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(node, str) or "::" not in node for node in values)
            or len(values) != len(set(values))
        ):
            raise ValueError("GUI nodes must be nonempty, unique canonical node IDs")
        return sorted(values)

    @classmethod
    def collection(cls, path: Path) -> list[str]:
        report = json.loads(path.read_text())
        if (
            report.get("schema") != "btrc.gui-collection/1"
            or report.get("exitstatus") != 0
            or report.get("problems") != []
        ):
            raise ValueError("GUI collection failed or skipped a collector; no partition was admitted")
        return cls.nodes(report["nodes"])

    @staticmethod
    def digest(nodes: list[str]) -> str:
        return hashlib.sha256(json.dumps(nodes, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def runner(session: str) -> str:
        if session == "macos":
            return "macos-hosted"
        if session in ("x11", "wayland"):
            return "linux-devcontainer"
        raise ValueError(f"Unknown GUI session: {session}")

    @classmethod
    def create(
        cls, whole: list[str], session: str, index: int, count: int, revision: str, *, schema: str = SCHEMA
    ) -> dict:
        cls.runner(session)
        whole = cls.nodes(whole)
        if count < 1 or not 0 <= index < count or len(whole) < count:
            raise ValueError("GUI partition index/count must describe nonempty cells")
        if schema not in (SCHEMA, LEGACY_SCHEMA):
            raise ValueError("Unsupported GUI partition schema")
        # Fixed strides align repeated parameter matrices with individual cells.
        # Rotate each block while retaining sorted invocation order and full coverage.
        selected = (
            whole[index::count]
            if schema == LEGACY_SCHEMA
            else [
                node for position, node in enumerate(whole) if (position % count + position // count) % count == index
            ]
        )
        return {
            "schema": schema,
            "session": session,
            "cell": f"{session}-{index}",
            "index": index,
            "count": count,
            "revision": revision,
            "whole": whole,
            "whole_sha256": cls.digest(whole),
            "selected": selected,
            "status": "collected",
        }

    @classmethod
    def validate(cls, record: dict, session: str, count: int, revision: str) -> list[str]:
        expected = cls.create(record["whole"], session, record["index"], count, revision, schema=record.get("schema"))
        if any(record.get(key) != value for key, value in expected.items() if key != "status"):
            raise ValueError("GUI partition source, manifest, hash or membership differs")
        if record.get("status") != "passed":
            raise ValueError("GUI partition did not complete successfully")
        return record["selected"]

    @classmethod
    def outcomes(cls, directory: Path, selected: list[str], revision: str, session: str) -> None:
        selected = cls.nodes(selected)
        cases = list(ET.parse(directory / "junit.xml").getroot().iter("testcase"))
        found: dict[str, str] = {}
        for case in cases:
            identities = [
                prop.get("value") for prop in case.findall("./properties/property") if prop.get("name") == NODE_PROPERTY
            ]
            if len(identities) != 1 or identities[0] in found:
                raise ValueError("GUI JUnit has missing or duplicate canonical identities")
            if case.find("failure") is not None or case.find("error") is not None:
                raise ValueError("GUI JUnit contains a failed/error test")
            found[identities[0]] = "skipped" if case.find("skipped") is not None else "passed"
        if sorted(found) != selected:
            raise ValueError("GUI JUnit membership differs from the selected nodes")
        skip_path = directory / "skip-report.json"
        skip = SkipReport.load(skip_path)
        if (
            skip["runner"] != cls.runner(session)
            or skip["tests"] != found
            or skip.get("invocation", {}).get("exitstatus") != 0
            or skip.get("revision") != revision
        ):
            raise ValueError("GUI skip report identity/outcomes differ from JUnit and selected nodes")
        gate = SkipGate().check([skip_path])
        if not gate.passed:
            raise ValueError("GUI skip policy failed: " + "; ".join(gate.failures))

    @classmethod
    def aggregate(cls, root: Path, session: str, count: int, revision: str) -> dict:
        paths = sorted(root.rglob("partition.json"))
        records = [(path, json.loads(path.read_text())) for path in paths]
        if len(records) != count:
            raise ValueError(f"GUI session needs exactly {count} cell receipts, got {len(records)}")
        if any(record.get("schema") != records[0][1].get("schema") for _, record in records):
            raise ValueError("GUI cells mix partition assignment schemas")
        indexes: set[int] = set()
        union: set[str] = set()
        whole: list[str] | None = None
        for path, record in records:
            selected = cls.validate(record, session, count, revision)
            if cls.collection(path.parent / "collection.json") != record["whole"]:
                raise ValueError("GUI partition differs from its retained collection")
            if record["index"] in indexes or union.intersection(selected):
                raise ValueError("GUI cells or their node memberships overlap")
            indexes.add(record["index"])
            union.update(selected)
            if whole is not None and record["whole"] != whole:
                raise ValueError("GUI cells collected different complete manifests")
            whole = record["whole"]
            cls.outcomes(path.parent, selected, revision, session)
        if indexes != set(range(count)) or sorted(union) != whole:
            raise ValueError("GUI cells do not cover the complete collection")
        return {
            "schema": "btrc.gui-union/1",
            "session": session,
            "revision": revision,
            "count": count,
            "nodes": len(union),
            "whole_sha256": cls.digest(whole),
            "status": "passed",
        }


class GUIShardRun:
    """Own collection, the existing pytest invocation and retained cell evidence."""

    def __init__(
        self,
        session: str,
        index: int,
        count: int,
        output: Path,
        skip_report: Path,
        selectors: list[str],
        arguments: list[str],
    ):
        self.session, self.index, self.count = session, index, count
        self.output, self.skip_report = output.resolve(), skip_report.resolve()
        self.selectors, self.arguments = selectors, arguments
        self.record: dict = {}

    def save(self) -> None:
        (self.output / "partition.json").write_text(json.dumps(self.record, indent=2) + "\n")

    def command(self, phase: str, arguments: list[str]) -> int:
        command = [sys.executable, "-m", "pytest", "-p", "tools.ui.gui_collection", *arguments]
        with (self.output / f"{phase}.txt").open("w") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            code = process.wait()
        self.record.setdefault("commands", []).append({"phase": phase, "argv": command, "returncode": code})
        self.save()
        return code

    def run(self) -> None:
        runner = GUIPartition.runner(self.session)
        if self.session == "macos":
            admitted = sys.platform == "darwin"
        else:
            admitted = sys.platform == "linux" and os.environ.get("SDL_VIDEODRIVER") == self.session
        if not admitted or os.environ.get("BTRC_TEST_RUNNER") != runner:
            raise ValueError(f"GUI partitions require the selected {self.session} session on {runner}")
        self.output.mkdir(parents=True, exist_ok=True)
        if (
            any(
                (self.output / name).exists()
                for name in ("partition.json", "collection.json", "junit.xml", "skip-report.json")
            )
            or self.skip_report.exists()
        ):
            raise ValueError("GUI evidence paths already exist; use a fresh cell output")
        revision = subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        self.record = {
            "schema": SCHEMA,
            "session": self.session,
            "index": self.index,
            "count": self.count,
            "revision": revision,
            "status": "starting",
            "commands": [],
        }
        self.save()
        try:
            collection = self.output / "collection.json"
            code = self.command(
                "collection",
                [
                    *self.selectors,
                    *self.arguments,
                    "--collect-only",
                    "-n",
                    "0",
                    f"--gui-collection={collection}",
                    f"--skip-report={self.skip_report}",
                ],
            )
            whole = GUIPartition.collection(collection)
            if code:
                raise ValueError(f"GUI collection exited {code}")
            self.record.update(GUIPartition.create(whole, self.session, self.index, self.count, revision))
            self.save()
            code = self.command(
                "tests",
                [
                    *self.record["selected"],
                    *self.arguments,
                    # Explicit fixture groups share one build per configuration.
                    # Unmarked cases remain independent scheduling units.
                    "--dist=loadgroup",
                    f"--basetemp={self.output / 'pytest'}",
                    f"--junitxml={self.output / 'junit.xml'}",
                    f"--skip-report={self.skip_report}",
                ],
            )
            if self.skip_report.is_file():
                (self.output / "skip-report.json").write_bytes(self.skip_report.read_bytes())
            if code:
                raise ValueError(f"GUI tests exited {code}")
            GUIPartition.outcomes(self.output, self.record["selected"], revision, self.session)
            self.record["status"] = "passed"
        except Exception as error:
            self.record.update(status="failed", error=str(error))
            raise
        finally:
            self.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--session", choices=("x11", "wayland", "macos"), required=True)
    run.add_argument("--index", type=int, default=0)
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--skip-report", type=Path, required=True)
    run.add_argument("--selectors", nargs="+", required=True)
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--session", choices=("x11", "wayland", "macos"), required=True)
    aggregate.add_argument("--count", type=int, required=True)
    aggregate.add_argument("--revision", required=True)
    aggregate.add_argument("--input", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            GUIShardRun(
                args.session,
                args.index,
                args.count,
                args.output,
                args.skip_report,
                args.selectors,
                args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments,
            ).run()
        else:
            receipt = GUIPartition.aggregate(args.input, args.session, args.count, args.revision)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    except Exception as error:
        if args.command == "aggregate":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    {
                        "schema": "btrc.gui-union/1",
                        "session": args.session,
                        "revision": args.revision,
                        "count": args.count,
                        "status": "failed",
                        "error": str(error),
                    },
                    indent=2,
                )
                + "\n"
            )
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
