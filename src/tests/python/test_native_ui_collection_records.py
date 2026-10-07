"""Frozen 100k collection data: two compilers, stable keys and replayable edits.

The emitted ledger samples describe this fixture run, not UI throughput or a
quiet-machine performance qualification. No toolkit or display is required.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TOOL_TIMEOUT, TRANSPILE_TIMEOUT
from tools.qualification.schema import LedgerRecord

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src/tests/native/gui/collections/CollectionRecords.btrc"
DIGEST = FIXTURE.with_name("records.sha256")


def _check_records(output: bytes) -> None:
    assert output.endswith(b"\n") and b"\r" not in output
    rows = [line.split("\t") for line in output.decode("utf-8").splitlines()]
    assert rows[0] == ["btrc.collection-records", "1"]
    assert len(rows) == 102001
    records = rows[1:100001]
    assert all(len(row) == 5 and row[0] == "R" for row in records)
    keys = {row[1] for row in records}
    assert len(keys) == 100000
    assert keys == {f"k{index:06d}" for index in range(100000)}
    assert {int(row[2]) for row in records} == set(range(100000))
    assert {int(row[3]) for row in records} == set(range(17))
    titles = {row[4] for row in records}
    assert "" in titles and max(map(len, titles)) > 60
    assert any("مرحبا" in title for title in titles)
    assert any("שלום" in title for title in titles)
    assert any("🎸" in title for title in titles)
    assert any("\u0301" in title for title in titles)
    all_keys = keys.copy()
    deleted = set()
    for step in range(1000):
        remove, insert = rows[100001 + step * 2 : 100003 + step * 2]
        assert len(remove) == 3 and remove[:2] == ["D", str(step)]
        assert len(insert) == 6 and insert[:2] == ["I", str(step)]
        assert remove[2] in keys and remove[2] not in deleted
        assert insert[2] not in all_keys
        assert 0 <= int(insert[3]) < 100000 and 0 <= int(insert[4]) < 17
        assert insert[5] in titles
        keys.remove(remove[2])
        deleted.add(remove[2])
        keys.add(insert[2])
        all_keys.add(insert[2])
    assert len(keys) == 100000 and len(deleted) == 1000 and len(all_keys) == 101000


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_collection_records(tmp_path, request, record_property, frontend):
    generated = tmp_path / "CollectionRecords.c"
    environment = {**os.environ, "LC_ALL": "C", "BTRC_HOME": str(ROOT / "src")}
    flags = ["--no-stdlib", str(FIXTURE)]
    command = (
        [sys.executable, "-B", "-m", "src.compiler.python.main", "--no-cache", *flags, "-o", str(generated)]
        if frontend == "reference"
        else [str(request.getfixturevalue("immutable_btrcc")), *flags]
    )
    result = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT
    )
    assert result.returncode == 0, result.stderr
    if frontend == "selfhost":
        generated.write_text(result.stdout, encoding="utf-8")
    compiler = "/usr/bin/clang" if sys.platform == "darwin" else "cc"
    if sys.platform == "darwin":
        environment.pop("DEVELOPER_DIR", None)
        environment.pop("SDKROOT", None)
    executable = tmp_path / "collection-records"
    built = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            str(generated),
            "-lm",
            "-o",
            str(executable),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr
    samples = []
    outputs = []
    for _ in range(2):
        started = time.perf_counter()
        result = subprocess.run([str(executable)], env=environment, capture_output=True, timeout=RUN_TIMEOUT)
        samples.append(time.perf_counter() - started)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1], "fresh processes must emit identical bytes"
    output = outputs[0]
    digest = hashlib.sha256(output).hexdigest()
    assert digest == DIGEST.read_text(encoding="ascii").strip()
    _check_records(output)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=TOOL_TIMEOUT
    ).stdout.strip()
    native_version = subprocess.run(
        [compiler, "--version"], env=environment, capture_output=True, text=True, check=True, timeout=TOOL_TIMEOUT
    ).stdout.splitlines()[0]
    destination = ROOT / "build/ui-collection-records" / f"{frontend}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for metric, unit, values in (
        ("generator-wall-time", "s", samples),
        ("serialized-size", "bytes", [len(data) for data in outputs]),
    ):
        record = LedgerRecord.from_mapping(
            {
                "schema": "btrc.qualification.ledger/1",
                "subject": {
                    "kind": "test",
                    "id": f"{request.node.nodeid}::{metric}",
                    "platform": {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()],
                    "frontend": frontend,
                    "group": "collection-records",
                },
                "evidence": {
                    "status": "passed",
                    "observed": "measured",
                    "reason": f"100000 records and 1000 edit pairs; sha256:{digest}; no UI performance claim",
                    "artifact": str(destination.relative_to(ROOT)),
                },
                "measurement": {"metric": metric, "unit": unit, "samples": values, "minimum_samples": 2},
                "provenance": {
                    "source": "collection-records",
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "runner": os.environ.get("BTRC_TEST_RUNNER", platform.system().lower()),
                    "btrc_revision": revision,
                    "frontend": frontend,
                    "os_build": platform.platform(),
                    "c_compiler": native_version,
                    "build_mode": "strict-c11-O2",
                    "jobs": "1",
                },
            }
        )
        records.append(json.dumps(record.to_mapping(), sort_keys=True))
    destination.write_text("\n".join(records) + "\n", encoding="utf-8")
    record_property("records_sha256", digest)
    record_property("serialized_bytes", len(output))
    record_property("measurement_ledger", str(destination.relative_to(ROOT)))
