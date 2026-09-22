"""Real reader sessions: cache hits must preserve extraction and invalidation."""

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def reader():
    path = os.environ.get("BTRC_NATIVE_HEADER_READER")
    if not path:
        pytest.skip("build .#btrc-native-header and set BTRC_NATIVE_HEADER_READER")
    assert Path(path).is_file(), path
    return path


class NativeSession:
    """Exercise the actual process and filesystem protocol, with a fixed environment."""

    def __init__(self, reader, root):
        self.reader = reader
        self.root = root
        self.cache = root / "cache"
        self.cache.mkdir(mode=0o700)
        self.environment = dict(os.environ)
        self.source = root / "Native.c"
        self.source.write_text("enum { Selected = 1 };\n")
        self.arguments = ["--symbol=Selected", str(self.source), "--", "-x", "c", "-std=c11"]
        self.limit = 8 * 1024 * 1024

    def run(self, arguments, *, input=None):
        return subprocess.run(
            [self.reader, *arguments],
            input=input,
            capture_output=True,
            env=self.environment,
            timeout=30,
        )

    def cached(self):
        return self.run(
            ["--cached-native-read=-"],
            input=json.dumps(
                {
                    "schema": "btrc.native-read.v1",
                    "cache_directory": str(self.cache),
                    "arguments": self.arguments,
                    "input": None,
                    "output_limit": self.limit,
                }
            ).encode(),
        )

    def control(self, groups=None, *, store=False, cache=None):
        groups = (
            groups
            if groups is not None
            else [{"id": "fixture", "arguments": self.arguments, "input": None, "output_limit": self.limit}]
        )
        result = self.run(
            ["--store-native-session=-" if store else "--prepare-native-session=-"],
            input=json.dumps(
                {
                    "schema": "btrc.native-session-requests.v1",
                    "cache_directory": str(self.cache if cache is None else cache),
                    "groups": groups,
                }
            ).encode(),
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        document = json.loads(result.stdout)
        assert document["schema"] == "btrc.native-session-prepared.v1"
        assert document["runtime_stable"]
        return document["groups"]

    def stage(self):
        stage = self.cache / ("stage-" + secrets.token_hex(32))
        stage.mkdir(mode=0o700)
        for name in ("inputs.json", "filesystem.json", "stdout", "stderr"):
            descriptor = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        result = self.run(
            [f"--input-report={stage / 'inputs.json'}", f"--trace-files={stage / 'filesystem.json'}", *self.arguments]
        )
        (stage / "stdout").write_bytes(result.stdout)
        (stage / "stderr").write_bytes(result.stderr)
        return stage, result

    def publish(self, stage):
        return self.control([{"id": "fixture", "stage": stage.name, "output_limit": self.limit}], store=True)[0][
            "stored"
        ]

    def seed(self):
        stage, result = self.stage()
        assert result.returncode == 0, result.stderr
        assert self.publish(stage)
        return stage, result

    def response(self):
        group = self.control()[0]
        assert group["cache_hit"], group
        streams = []
        for stream in ("stdout", "stderr"):
            descriptor = group["response"][stream]
            data = Path(descriptor["path"]).read_bytes()
            assert len(data) == descriptor["bytes"]
            assert hashlib.sha256(data).hexdigest() == descriptor["sha256"]
            streams.append(data)
        return tuple(streams)

    def receipt(self):
        identity = self.control()[0]["inputs"]["identity_sha256"]
        path = self.cache / (identity + ".receipt")
        data = path.read_bytes()
        assert hashlib.sha256(data[65:]).hexdigest().encode() == data[:64]
        return path, json.loads(data[65:])

    def write_receipt(self, path, document):
        data = json.dumps(document, separators=(",", ":")).encode()
        path.write_bytes(hashlib.sha256(data).hexdigest().encode() + b"\n" + data)

    def fragment(self, rows):
        data = json.dumps(rows, separators=(",", ":")).encode()
        digest = hashlib.sha256(data).hexdigest()
        path = self.cache / ("trace-" + digest)
        path.write_bytes(data)
        path.chmod(0o600)
        return digest


@pytest.fixture
def session(reader):
    # A shared /tmp ancestor is intentionally not admitted by the storage owner.
    # Use a private directory below the actual user's home, also on macOS.
    with tempfile.TemporaryDirectory(prefix=".btrc-native-cache-", dir=Path.home()) as directory:
        yield NativeSession(reader, Path(directory))


@pytest.fixture
def cache_session(session):
    group = session.control()[0]
    assert group["prepared"], group
    if not group["inputs"]["eligible_runtime"]:
        if os.environ.get("BTRC_NATIVE_CACHE_REQUIRED") == "1":
            pytest.fail("cache qualification requires an admitted immutable reader/runtime")
        pytest.skip("this reader/runtime has no qualified persistent-cache provider")
    assert group["inputs"]["eligible_inputs"]
    assert not group["cache_hit"]
    return session


@pytest.mark.parametrize(
    "source",
    [
        "enum { Selected = 1 };\n",
        "#warning retained diagnostic\nenum { Selected = 1 };\n",
        "enum { Selected = missing };\n",
    ],
)
def test_receipt_capture_preserves_ordinary_extraction(session, source):
    session.source.write_text(source)
    ordinary = session.run(session.arguments)
    stage, captured = session.stage()
    assert (captured.returncode, captured.stdout, captured.stderr) == (
        ordinary.returncode,
        ordinary.stdout,
        ordinary.stderr,
    )
    assert json.loads((stage / "inputs.json").read_text())["reader_exit"] == captured.returncode
    assert json.loads((stage / "filesystem.json").read_text())["operations"]


def test_cache_retains_complete_warnings(cache_session):
    session = cache_session
    session.source.write_text("#warning retained diagnostic\nenum { Selected = 1 };\n")
    _, result = session.seed()
    assert b"1 warning generated." in result.stderr
    assert session.response() == (result.stdout, result.stderr)


def test_source_change_with_preserved_metadata_requires_fresh_extraction(cache_session):
    session = cache_session
    _, original = session.seed()
    assert session.response() == (original.stdout, original.stderr)
    metadata = session.source.stat()
    session.source.write_text("enum { Selected = 2 };\n")
    os.utime(session.source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert not session.control()[0]["cache_hit"]
    _, changed = session.seed()
    assert changed.stdout != original.stdout
    assert session.response() == (changed.stdout, changed.stderr)


@pytest.mark.parametrize("kind", ["shadow", "has_include"])
def test_new_header_invalidates_negative_lookups(cache_session, kind):
    session = cache_session
    first, second = session.root / "first", session.root / "second"
    first.mkdir()
    second.mkdir()
    session.arguments += ["-I" + str(first), "-I" + str(second)]
    if kind == "shadow":
        (second / "Choice.h").write_text("enum { Selected = 1 };\n")
        session.source.write_text('#include "Choice.h"\n')
    else:
        session.source.write_text(
            '#if __has_include("Choice.h")\n#include "Choice.h"\n#else\nenum { Selected = 1 };\n#endif\n'
        )
    _, original = session.seed()
    assert session.response() == (original.stdout, original.stderr)
    (first / "Choice.h").write_text("enum { Selected = 2 };\n")
    assert not session.control()[0]["cache_hit"]
    _, changed = session.seed()
    assert changed.stdout != original.stdout
    assert session.response() == (changed.stdout, changed.stderr)


@pytest.mark.parametrize("mutation", ["receipt", "stdout", "stderr", "mode", "symlink", "hardlink"])
def test_damaged_cache_is_a_miss(cache_session, mutation):
    session = cache_session
    session.source.write_text("#warning retained diagnostic\nenum { Selected = 1 };\n")
    session.seed()
    group = session.control()[0]
    assert group["cache_hit"]
    receipt = session.cache / (group["inputs"]["identity_sha256"] + ".receipt")
    target = Path(group["response"][mutation]["path"]) if mutation in {"stdout", "stderr"} else receipt
    original = target.read_bytes()
    metadata = target.stat()
    if mutation in {"receipt", "stdout", "stderr"}:
        target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    elif mutation == "mode":
        target.chmod(0o644)
    elif mutation == "symlink":
        copy = target.with_suffix(".copy")
        target.rename(copy)
        target.symlink_to(copy)
    else:
        os.link(target, target.with_suffix(".copy"))
    assert not session.control()[0]["cache_hit"]
    assert session.run(session.arguments).returncode == 0


@pytest.mark.parametrize("change", ["environment", "driver", "abi", "output_limit", "unsafe_root"])
def test_changed_contract_does_not_reuse(cache_session, change):
    session = cache_session
    session.seed()
    assert session.control()[0]["cache_hit"]
    if change == "environment":
        session.environment["BTRC_CACHE_TEST_INPUT"] = "changed"
    elif change == "driver":
        session.arguments += ["-Qunused-arguments"]
    elif change == "abi":
        session.arguments += ["-fpack-struct=1"]
    elif change == "output_limit":
        session.limit = 1
    else:
        session.cache.chmod(0o755)
    assert not session.control()[0]["cache_hit"]


@pytest.mark.parametrize("kind", ["volatile", "failed", "diagnostic_output"])
def test_unreusable_workers_are_not_published(cache_session, kind):
    session = cache_session
    if kind == "volatile":
        session.source.write_text("const char* Selected = __TIME__;\n")
    elif kind == "failed":
        session.arguments[0] = "--symbol=Missing"
    else:
        output = session.root / "diagnostics.plist"
        session.arguments += ["-Xclang=-diagnostic-log-file", "-Xclang=" + str(output)]
    stage, result = session.stage()
    assert result.returncode == (1 if kind == "failed" else 0), result.stderr
    assert not session.publish(stage)
    if kind == "diagnostic_output":
        assert output.is_file()
        output.unlink()
    assert not session.control()[0]["cache_hit"]
    if kind == "diagnostic_output":
        assert not output.exists()
        assert session.run(session.arguments).returncode == 0
        assert output.is_file()


def test_failed_group_does_not_poison_other_groups(cache_session):
    session = cache_session
    session.seed()
    valid = {"id": "good", "arguments": session.arguments, "input": None, "output_limit": session.limit}
    invalid = {**valid, "id": "bad", "arguments": ["--unknown-option"]}
    rows = session.control([invalid, valid, {**invalid, "id": "bad-again"}, {**valid, "id": "good-again"}])
    assert [row["cache_hit"] for row in rows] == [False, True, False, True]


@pytest.mark.parametrize("scope", ["within_group", "across_groups"])
@pytest.mark.parametrize("change", ["exists", "buffer_digest"])
def test_shared_trace_compares_complete_observation(cache_session, scope, change):
    session = cache_session
    good, captured = session.stage()
    assert captured.returncode == 0, captured.stderr
    bad, captured = session.stage()
    assert captured.returncode == 0, captured.stderr
    trace = json.loads((good / "filesystem.json").read_text())
    if change == "exists":
        observation = {"operation": "exists", "path": str(session.source), "exists": True}
        changed = {**observation, "exists": False}
    else:
        observation = next(row for row in trace["operations"] if row["operation"] == "buffer")
        changed = {**observation, "sha256": "0" * 64}
    trace["operations"].append(observation)
    (good / "filesystem.json").write_text(json.dumps(trace))
    invalid = {"complete": True, "operations": [observation, changed] if scope == "within_group" else [changed]}
    (bad / "filesystem.json").write_text(json.dumps(invalid))
    groups = [{"id": "bad", "stage": bad.name, "output_limit": session.limit}]
    if scope == "across_groups":
        groups.insert(0, {"id": "good", "stage": good.name, "output_limit": session.limit})
    results = session.control(groups, store=True)
    assert [row["stored"] for row in results] == ([True, False] if scope == "across_groups" else [False])


@pytest.mark.parametrize("absolute", [False, True])
def test_trace_sharing_respects_working_directory_transitions(cache_session, absolute):
    session = cache_session
    present, absent = session.root / "present", session.root / "absent"
    present.mkdir()
    absent.mkdir()
    (present / "Probe.h").write_text("/* present only here */\n")
    stage, captured = session.stage()
    assert captured.returncode == 0, captured.stderr
    trace = json.loads((stage / "filesystem.json").read_text())
    for directory, exists in [(present, True), (absent, False), (present, True)]:
        trace["operations"].extend(
            [
                {"operation": "setcwd", "path": str(directory), "error": {"code": 0, "category": "system"}},
                {"operation": "getcwd", "directory": str(directory)},
                {
                    "operation": "exists",
                    "path": str(present / "Probe.h") if absolute else "Probe.h",
                    "exists": True if absolute else exists,
                },
            ]
        )
    (stage / "filesystem.json").write_text(json.dumps(trace))
    assert session.publish(stage)
    assert session.response() == (captured.stdout, captured.stderr)


def test_absolute_open_with_relative_directory_remains_context_bound(cache_session):
    session = cache_session
    present, absent = session.root / "present", session.root / "absent"
    (present / "subdir").mkdir(parents=True)
    absent.mkdir()
    stage, captured = session.stage()
    assert captured.returncode == 0, captured.stderr
    trace = json.loads((stage / "filesystem.json").read_text())
    for directory in [present, absent]:
        trace["operations"].extend(
            [
                {"operation": "setcwd", "path": str(directory), "error": {"code": 0, "category": "system"}},
                {"operation": "open", "path": str(session.source), "open_cwd": "subdir"},
            ]
        )
    (stage / "filesystem.json").write_text(json.dumps(trace))
    # The absolute file exists in both contexts, but the recorded relative
    # opening directory exists only in the first. A shared row cannot hide it.
    assert not session.publish(stage)


def test_concurrent_publishers_and_readers_preserve_complete_responses(cache_session):
    session = cache_session
    stage, result = session.seed()
    expected = result.stdout, result.stderr
    with ThreadPoolExecutor(max_workers=4) as pool:
        publications = [pool.submit(session.publish, stage) for _ in range(2)]
        reads = [pool.submit(session.response) for _ in range(4)]
        assert all(job.result() for job in publications)
        assert all(job.result() == expected for job in reads)
    assert session.response() == expected


def test_fragment_publication_preserves_complete_ordered_trace(cache_session):
    session = cache_session
    stage, captured = session.stage()
    trace = json.loads((stage / "filesystem.json").read_text())
    trace["operations"].extend(
        {"operation": "exists", "path": str(session.root / f"missing-{index}"), "exists": False} for index in range(600)
    )
    (stage / "filesystem.json").write_text(json.dumps(trace))
    assert session.publish(stage)
    _, receipt = session.receipt()
    assert receipt["schema"] == "btrc.native-header-cache.v2"
    references = receipt["filesystem"]["fragments"]
    assert len(references) > 2 and "operations" not in receipt["filesystem"]
    restored = []
    for digest in references:
        path = session.cache / ("trace-" + digest)
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert path.stat().st_mode & 0o777 == 0o600
        restored.extend(json.loads(data))
    assert restored == trace["operations"]
    assert session.response() == (captured.stdout, captured.stderr)


def test_inline_receipt_remains_readable(cache_session):
    session = cache_session
    stage, captured = session.seed()
    path, receipt = session.receipt()
    receipt.update(schema="btrc.native-header-cache.v1", filesystem=json.loads((stage / "filesystem.json").read_text()))
    session.write_receipt(path, receipt)
    assert session.response() == (captured.stdout, captured.stderr)


@pytest.mark.parametrize("damage", ["missing", "contents", "mode", "symlink", "hardlink"])
def test_damaged_trace_fragment_is_a_miss_and_can_be_repaired(cache_session, damage):
    session = cache_session
    stage, captured = session.seed()
    _, receipt = session.receipt()
    path = session.cache / ("trace-" + receipt["filesystem"]["fragments"][0])
    original = path.read_bytes()
    alias = session.cache / "unowned-fragment"
    if damage == "missing":
        path.unlink()
    elif damage == "contents":
        metadata = path.stat()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    elif damage == "mode":
        path.chmod(0o644)
    elif damage == "symlink":
        path.rename(alias)
        path.symlink_to(alias)
    else:
        os.link(path, alias)
    assert not session.control()[0]["cache_hit"]
    assert session.publish(stage)
    assert not path.is_symlink() and path.stat().st_nlink == 1
    assert path.stat().st_mode & 0o777 == 0o600 and path.read_bytes() == original
    if alias.exists():
        assert alias.read_bytes() == original
    assert session.response() == (captured.stdout, captured.stderr)


@pytest.mark.parametrize("damage", ["reference", "shape", "row", "expanded", "mixed"])
def test_invalid_fragment_document_never_returns_response(cache_session, damage):
    session = cache_session
    session.seed()
    path, receipt = session.receipt()
    if damage == "reference":
        references = ["../outside"]
    elif damage == "shape":
        references = [session.fragment({"not": "an array"})]
    elif damage == "row":
        references = [session.fragment([{"operation": "exists", "path": str(session.source), "exists": False}])]
    elif damage == "expanded":
        # One small parsed fragment must not admit arbitrarily large expansion.
        digest = session.fragment([{"operation": "exists", "path": "x" * 65536, "exists": False}])
        references = [digest] * 1024
    else:
        references = receipt["filesystem"]["fragments"]
    receipt["filesystem"] = {"complete": True, "fragments": references}
    if damage == "mixed":
        receipt["filesystem"]["operations"] = []
    session.write_receipt(path, receipt)
    group = session.control()[0]
    assert not group["cache_hit"] and "response" not in group


@pytest.mark.parametrize("relative", [False, True])
def test_directory_context_survives_fragment_boundaries(cache_session, relative):
    session = cache_session
    present, absent = session.root / "present", session.root / "absent"
    present.mkdir()
    absent.mkdir()
    (present / "Probe.h").write_text("present")
    _, captured = session.seed()
    path, receipt = session.receipt()
    fragments = []
    for directory, exists in [(present, True), (absent, False), (present, True)]:
        fragments.append(
            session.fragment(
                [{"operation": "setcwd", "path": str(directory), "error": {"code": 0, "category": "system"}}]
            )
        )
        fragments.append(
            session.fragment(
                [
                    {"operation": "getcwd", "directory": str(directory)},
                    {
                        "operation": "exists",
                        "path": "Probe.h" if relative else str(present / "Probe.h"),
                        "exists": exists if relative else True,
                    },
                ]
            )
        )
    receipt["filesystem"] = {"complete": True, "fragments": fragments}
    session.write_receipt(path, receipt)
    assert session.response() == (captured.stdout, captured.stderr)


def test_failed_fragment_group_does_not_publish_earlier_observations(cache_session):
    session = cache_session
    probe = session.root / "Probe.h"
    probe.write_text("present")
    barriers = [session.root / name for name in ["first-barrier", "second-barrier"]]
    for barrier in barriers:
        os.mkfifo(barrier, 0o600)
    observation = {"operation": "exists", "path": str(probe), "exists": True}
    groups = []
    for bad in [True, False]:
        session.arguments += ["-DFIRST=1" if bad else "-DSECOND=1"]
        session.seed()
        path, receipt = session.receipt()
        fragments = [session.fragment([observation])]
        if bad:
            fragments.append(
                session.fragment(
                    [
                        *({"operation": "open", "path": str(barrier)} for barrier in barriers),
                        {"operation": "exists", "path": str(session.root / "missing"), "exists": True},
                    ]
                )
            )
        receipt["filesystem"] = {"complete": True, "fragments": fragments}
        session.write_receipt(path, receipt)
        groups.append(
            {
                "id": "bad" if bad else "good",
                "arguments": list(session.arguments),
                "input": None,
                "output_limit": session.limit,
            }
        )
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(session.control, groups)
        for index, barrier in enumerate(barriers):
            deadline = time.monotonic() + 15
            while True:
                try:
                    descriptor = os.open(barrier, os.O_WRONLY | os.O_NONBLOCK)
                    os.close(descriptor)
                    break
                except OSError:
                    assert not result.done() and time.monotonic() < deadline
                    time.sleep(0.01)
            if index == 0:
                # The first fragment was checked. The second barrier prevents
                # either group from finishing until this mutation has happened.
                probe.unlink()
        assert [group["cache_hit"] for group in result.result()] == [False, False]


def test_relative_opening_context_is_not_shared_across_fragment_directories(cache_session):
    session = cache_session
    present, absent = session.root / "present", session.root / "absent"
    (present / "subdir").mkdir(parents=True)
    absent.mkdir()
    session.seed()
    path, receipt = session.receipt()
    opening = session.fragment([{"operation": "open", "path": str(session.source), "open_cwd": "subdir"}])
    fragments = []
    for directory in [present, absent]:
        fragments.extend(
            [
                session.fragment(
                    [{"operation": "setcwd", "path": str(directory), "error": {"code": 0, "category": "system"}}]
                ),
                opening,
            ]
        )
    receipt["filesystem"] = {"complete": True, "fragments": fragments}
    session.write_receipt(path, receipt)
    # Identical absolute-file observations still depend on relative open_cwd.
    assert not session.control()[0]["cache_hit"]


def test_fragment_parsing_budget_overflow_remains_a_valid_cache_hit(cache_session):
    session = cache_session
    groups = []
    for group in range(2):
        session.arguments += [f"-DGROUP{group}=1"]
        session.seed()
        path, receipt = session.receipt()
        # Each receipt fits the expansion limit, while their distinct parsed
        # data exceeds the invocation's 64 MiB retention budget. The extra
        # arrays must remain alive through validation without being retained.
        fragments = [
            session.fragment(
                [{"operation": "exists", "path": f"{group}-{index}-" + "x" * (1024 * 1024), "exists": False}]
            )
            for index in range(34)
        ]
        receipt["filesystem"] = {"complete": True, "fragments": fragments}
        session.write_receipt(path, receipt)
        groups.append(
            {"id": str(group), "arguments": list(session.arguments), "input": None, "output_limit": session.limit}
        )
    assert [group["cache_hit"] for group in session.control(groups)] == [True, True]


def test_concurrent_fragment_publication_preserves_open_descriptors(cache_session):
    session = cache_session
    stage, captured = session.seed()
    _, receipt = session.receipt()
    paths = [session.cache / ("trace-" + digest) for digest in receipt["filesystem"]["fragments"]]
    with contextlib.ExitStack() as stack:
        readers = [stack.enter_context(path.open("rb")) for path in paths]
        before = [os.fstat(reader.fileno()) for reader in readers]
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert all(pool.map(session.publish, [stage] * 4))
        for path, reader, original in zip(paths, readers, before, strict=True):
            assert os.fstat(reader.fileno()).st_nlink == 1
            assert path.stat().st_ino == original.st_ino
            assert reader.read() == path.read_bytes()
    assert session.response() == (captured.stdout, captured.stderr)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_republishing_identical_blob_preserves_active_reader(cache_session, stream):
    session = cache_session
    stage, result = session.seed()
    descriptor = session.control()[0]["response"][stream]
    path = Path(descriptor["path"])
    with path.open("rb") as reader:
        before = os.fstat(reader.fileno())
        assert session.publish(stage)
        after = os.fstat(reader.fileno())
        # The cache's before/after checks reject an unlinked descriptor even
        # when a replacement at the same digest happens to contain equal bytes.
        assert after.st_nlink == before.st_nlink == 1
        assert path.stat().st_ino == before.st_ino
        assert hashlib.sha256(reader.read()).hexdigest() == descriptor["sha256"]
    assert session.response() == (result.stdout, result.stderr)


@pytest.mark.parametrize("damage", ["contents", "mode", "hardlink"])
def test_republishing_repairs_invalid_blob_without_changing_aliases(cache_session, damage):
    session = cache_session
    stage, result = session.seed()
    descriptor = session.control()[0]["response"]["stdout"]
    path = Path(descriptor["path"])
    alias = session.cache / "unowned-alias"
    if damage == "contents":
        path.write_bytes(b"corrupt")
    elif damage == "mode":
        path.chmod(0o644)
    else:
        os.link(path, alias)
    previous = path.stat().st_ino
    assert session.publish(stage)
    assert path.stat().st_ino != previous and path.stat().st_nlink == 1
    assert path.stat().st_mode & 0o777 == 0o600
    if damage == "hardlink":
        assert alias.stat().st_ino == previous and alias.read_bytes() == result.stdout
    assert session.response() == (result.stdout, result.stderr)


def test_mutable_reader_cannot_admit_cache(cache_session):
    session = cache_session
    # The Mach-O runtime provider must identify the executable actually loaded.
    reader = Path(session.reader)
    unwrapped = reader.with_name("." + reader.name + "-wrapped")
    executable = session.root / "mutable-reader"
    shutil.copy2(unwrapped if unwrapped.is_file() else reader, executable)
    session.reader = str(executable)
    group = session.control()[0]
    assert not group["inputs"]["eligible_runtime"]
    assert not group["cache_hit"]


def test_reference_session_stores_consumes_and_revalidates(cache_session):
    from src.compiler.python.frontend.native_imports import NativeHeaderRead, NativeHeaderSession

    session = cache_session
    session.environment["BTRC_CACHE_DIR"] = str(session.root / "compiler-cache")
    request = NativeHeaderRead((session.reader, *session.arguments), (0,))
    prepared = NativeHeaderSession.prepare([request], session.environment)
    assert prepared and not prepared[0].cached_response
    original = prepared[0].read(session.environment)
    prepared = NativeHeaderSession.prepare([request], session.environment)
    assert prepared[0].cached_response
    cache = Path(prepared[0].cache_directory)
    before = {path.name: path.stat().st_ino for path in cache.glob("*.receipt")}
    assert before and prepared[0].read(session.environment) == original
    assert {path.name: path.stat().st_ino for path in cache.glob("*.receipt")} == before
    # Change a response after the helper validated it, before frontend consumption.
    path = Path(prepared[0].cached_response["stdout"]["path"])
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    assert prepared[0].read(session.environment) == original
    assert {path.name: path.stat().st_ino for path in cache.glob("*.receipt")} != before
    assert not list(cache.glob("stage-*"))
    assert not list((cache / "workers").glob("*"))


def test_reference_session_rejects_a_forwarding_launcher(cache_session):
    from src.compiler.python.frontend.native_imports import NativeHeaderRead, NativeHeaderSession

    session = cache_session
    wrapper = session.root / "reader-wrapper"
    # This may transform ordinary output, so its child cannot authorize bypassing it.
    wrapper.write_text('#!/bin/sh\nexec "' + session.reader + '" "$@"\n')
    wrapper.chmod(0o700)
    session.environment["BTRC_CACHE_DIR"] = str(session.root / "compiler-cache")
    request = NativeHeaderRead((str(wrapper), *session.arguments), (0,))
    assert NativeHeaderSession.prepare([request], session.environment) == {}
    assert request.read(session.environment) == session.run(session.arguments).stdout.decode()


def test_cached_worker_storage_failure_falls_back_to_ordinary(session):
    session.cache.chmod(0o755)
    ordinary = session.run(session.arguments)
    cached = session.run(
        ["--cached-native-read=-"],
        input=json.dumps(
            {
                "schema": "btrc.native-read.v1",
                "cache_directory": str(session.cache),
                "arguments": session.arguments,
                "input": None,
                "output_limit": session.limit,
            }
        ).encode(),
    )
    assert (cached.returncode, cached.stdout, cached.stderr) == (ordinary.returncode, ordinary.stdout, ordinary.stderr)


@pytest.mark.parametrize("mode", ["success", "warning", "error"])
def test_cached_worker_preserves_streams_and_cleans_stages(cache_session, mode):
    session = cache_session
    if mode == "warning":
        session.source.write_text("#warning retained diagnostic\nenum { Selected = 1 };\n")
    elif mode == "error":
        session.source.write_text("enum { Selected = missing };\n")
    ordinary = session.run(session.arguments)
    cached = session.run(
        ["--cached-native-read=-"],
        input=json.dumps(
            {
                "schema": "btrc.native-read.v1",
                "cache_directory": str(session.cache),
                "arguments": session.arguments,
                "input": None,
                "output_limit": session.limit,
            }
        ).encode(),
    )
    assert (cached.returncode, cached.stdout, cached.stderr) == (ordinary.returncode, ordinary.stdout, ordinary.stderr)
    assert not list(session.cache.glob("stage-*"))
    assert not list((session.cache / "workers").glob("*"))
    assert session.control()[0]["cache_hit"] == (mode != "error")


@pytest.fixture(scope="module")
def spawn_faults(tmp_path_factory):
    if sys.platform != "darwin":
        pytest.skip("Mach-O spawn interposition")
    compiler = shutil.which("clang", path="/usr/bin")
    if compiler is None:
        pytest.skip("Apple Clang is required for Mach-O fault injection")
    output = tmp_path_factory.mktemp("native-spawn-faults") / "faults.dylib"
    source = Path(__file__).resolve().parents[1] / "native" / "NativeReaderSpawnFaults.c"
    environment = {key: value for key, value in os.environ.items() if key not in ("SDKROOT", "DEVELOPER_DIR")}
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-dynamiclib", str(source), "-o", str(output)],
        env=environment,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return output


@pytest.mark.parametrize("mode", ["refuse", "move", "kill"])
def test_cached_worker_launch_failure_falls_back_but_crash_does_not(session, spawn_faults, mode):
    ordinary = session.run(session.arguments)
    assert ordinary.returncode == 0
    marker = session.root / "spawned"
    moved = session.root / "moved-cache"
    session.environment.update(
        DYLD_INSERT_LIBRARIES=str(spawn_faults),
        BTRC_TEST_SPAWN_FAULT=mode,
        BTRC_TEST_SPAWN_MARKER=str(marker),
        BTRC_TEST_CACHE=str(session.cache),
        BTRC_TEST_MOVED_CACHE=str(moved),
    )
    result = session.cached()
    assert marker.read_text() == "worker\n", "fault must run at the actual worker spawn boundary"
    cache = moved if mode == "move" else session.cache
    assert not list(cache.glob("stage-*"))
    assert not list((cache / "workers").glob("*"))
    assert not list(cache.glob("*.receipt"))
    if mode == "kill":
        assert result.returncode == 1
        assert not result.stdout
        assert b"native header reader child failed" in result.stderr
    else:
        assert (result.returncode, result.stdout, result.stderr) == (
            ordinary.returncode,
            ordinary.stdout,
            ordinary.stderr,
        )


def test_worker_collection_preserves_live_leases_and_caller_stages(cache_session):
    import fcntl

    session = cache_session
    caller, _ = session.seed()
    workers = session.cache / "workers"
    workers.mkdir(mode=0o700)
    stale, live, incomplete = (workers / (character * 64) for character in "abc")
    for directory in (stale, live, incomplete):
        directory.mkdir(mode=0o700)
        (directory / "stdout").write_bytes(b"partial capture")
    for directory in (stale, live):
        (directory / "owner").touch(mode=0o600)
    with (live / "owner").open("r+") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        # A collector must not enter a creation/cleanup gap held by another owner.
        descriptor = os.open(workers, os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            assert session.control()[0]["cache_hit"]
            assert all(directory.exists() for directory in (stale, live, incomplete))
        finally:
            os.close(descriptor)
        assert session.control()[0]["cache_hit"]
        assert not stale.exists() and not incomplete.exists()
        assert live.is_dir() and caller.is_dir()
    assert session.control()[0]["cache_hit"]
    assert not live.exists() and caller.is_dir()


def test_worker_lease_survives_parent_death_until_child_exits(cache_session, spawn_faults):
    import signal
    import time

    session = cache_session
    marker = session.root / "child"
    marker.touch()
    (session.root / "spawned").touch()
    session.seed()
    receipts = {path.name: (path.stat().st_ino, path.read_bytes()) for path in session.cache.glob("*.receipt")}
    environment = {
        **session.environment,
        "DYLD_INSERT_LIBRARIES": str(spawn_faults),
        "BTRC_TEST_SPAWN_FAULT": "hold",
        "BTRC_TEST_SPAWN_MARKER": str(session.root / "spawned"),
        "BTRC_TEST_CHILD_MARKER": str(marker),
    }
    request = {
        "schema": "btrc.native-read.v1",
        "cache_directory": str(session.cache),
        "arguments": session.arguments,
        "input": None,
        "output_limit": session.limit,
    }
    parent = subprocess.Popen(
        [session.reader, "--cached-native-read=-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        start_new_session=True,
    )
    try:
        parent.stdin.write(json.dumps(request).encode())
        parent.stdin.close()
        parent.stdin = None
        deadline = time.monotonic() + 10
        while not marker.exists() or not marker.read_text().endswith("\n"):
            assert parent.poll() is None, parent.communicate()
            assert time.monotonic() < deadline, "observed child did not reach its hold boundary"
            time.sleep(0.01)
        child = int(marker.read_text())
        stages = list((session.cache / "workers").iterdir())
        assert len(stages) == 1
        parent.kill()
        parent.communicate(timeout=5)
        assert parent.returncode == -signal.SIGKILL
        # This is a different process's collection attempt while only the
        # stopped child still owns the inherited lease.
        assert session.control()[0]["cache_hit"]
        assert stages[0].is_dir()
        os.kill(child, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while stages[0].exists():
            assert time.monotonic() < deadline, "abandoned worker stage was not collected"
            assert session.control()[0]["cache_hit"]
            time.sleep(0.01)
        assert {
            path.name: (path.stat().st_ino, path.read_bytes()) for path in session.cache.glob("*.receipt")
        } == receipts
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(parent.pid, signal.SIGKILL)
        parent.communicate(timeout=5)


@pytest.mark.parametrize("unsafe", ["mode", "symlink"])
def test_unsafe_worker_directory_is_never_used(session, unsafe):
    ordinary = session.run(session.arguments)
    workers = session.cache / "workers"
    target = session.root / "other-directory"
    target.mkdir(mode=0o700)
    sentinel = target / "keep"
    sentinel.write_bytes(b"not cache storage")
    if unsafe == "mode":
        workers.mkdir(mode=0o777)
        workers.chmod(0o777)
    else:
        workers.symlink_to(target, target_is_directory=True)
    result = session.cached()
    assert (result.returncode, result.stdout, result.stderr) == (
        ordinary.returncode,
        ordinary.stdout,
        ordinary.stderr,
    )
    assert sorted(path.name for path in target.iterdir()) == ["keep"]
    assert sentinel.read_bytes() == b"not cache storage"
    assert not list(session.cache.glob("*.receipt"))


def test_publication_collection_preserves_live_writers_and_published_data(cache_session):
    import fcntl

    session = cache_session
    session.seed()
    published = {path.name: path.read_bytes() for path in session.cache.iterdir() if path.is_file()}
    stale, live = (session.cache / (".tmp-" + character * 64) for character in "de")
    for path in (stale, live):
        path.touch(mode=0o600)
        path.write_bytes(b"incomplete publication")
    with live.open("r+") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        directory = os.open(session.cache, os.O_RDONLY)
        try:
            fcntl.flock(directory, fcntl.LOCK_SH)
            assert session.control()[0]["cache_hit"]
            assert stale.is_file() and live.is_file()
        finally:
            os.close(directory)
        assert session.control()[0]["cache_hit"]
        assert not stale.exists() and live.is_file()
    assert session.control()[0]["cache_hit"]
    assert not live.exists()
    assert {name: (session.cache / name).read_bytes() for name in published} == published


def test_interrupted_publication_keeps_prior_entry_and_collects_partial_bytes(cache_session, spawn_faults):
    import signal
    import time

    session = cache_session
    marker = session.root / "partial-write"
    marker.touch()
    session.source.write_text("struct Selected {\n" + "".join(f"int field{i};\n" for i in range(3000)) + "};\n")
    stage, result = session.seed()
    assert len(result.stdout) > 65536
    published = {
        path.name: (path.stat().st_ino, path.read_bytes()) for path in session.cache.iterdir() if path.is_file()
    }
    request = {
        "schema": "btrc.native-session-requests.v1",
        "cache_directory": str(session.cache),
        "groups": [{"id": "fixture", "stage": stage.name, "output_limit": session.limit}],
    }
    publisher = subprocess.Popen(
        [session.reader, "--store-native-session=-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **session.environment,
            "DYLD_INSERT_LIBRARIES": str(spawn_faults),
            "BTRC_TEST_SPAWN_FAULT": "publish",
            "BTRC_TEST_SPAWN_MARKER": str(marker),
            "BTRC_TEST_CACHE": str(session.cache),
        },
        start_new_session=True,
    )
    try:
        publisher.stdin.write(json.dumps(request).encode())
        publisher.stdin.close()
        publisher.stdin = None
        deadline = time.monotonic() + 10
        while not marker.read_text().endswith("\n"):
            assert publisher.poll() is None, publisher.communicate()
            assert time.monotonic() < deadline, "publisher never reached a partial payload write"
            time.sleep(0.01)
        assert 0 < int(marker.read_text()) < len(result.stdout)
        temporary = list(session.cache.glob(".tmp-*"))
        assert len(temporary) == 1 and temporary[0].stat().st_size > 0
        assert session.control()[0]["cache_hit"]
        assert temporary[0].exists(), "collector removed a live writer's payload"
        publisher.kill()
        publisher.communicate(timeout=5)
        assert publisher.returncode == -signal.SIGKILL
        assert session.control()[0]["cache_hit"]
        assert not list(session.cache.glob(".tmp-*"))
        assert {
            name: ((session.cache / name).stat().st_ino, (session.cache / name).read_bytes()) for name in published
        } == published
    finally:
        if publisher.poll() is None:
            publisher.kill()
        publisher.communicate(timeout=5)
