"""Exact bootstrap bytes and bounds, independent of Windows transport policy."""

import struct
import subprocess
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src/runtime/c"
PROBE = ROOT / "src/tests/native/daemon_windows/protocol_probe.c"
TOKEN = bytes(range(16))
MAX_PAYLOAD = 1_048_576


def frame(kind, payload):
    return b"BTRCDM1\0" + struct.pack("<HHI", 1, kind, len(payload)) + payload


def text(value):
    return struct.pack("<I", len(value)) + value


def vector(items):
    return struct.pack("<I", len(items)) + b"".join(map(text, items))


def startup(*, budget=3000, lifetime=0, restart=1, name=b"worker", arguments=None, environment=None):
    return (
        TOKEN
        + struct.pack("<QII", budget, lifetime, restart)
        + b"".join(map(text, [name, b"C:\\state\\worker.control", b"C:\\state\\worker.log", b"C:\\work", b"tool.exe"]))
        + vector([b"tool.exe", b"argument"] if arguments is None else arguments)
        + vector([b"=C:=C:\\work", b"KEY=value"] if environment is None else environment)
    )


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    output = tmp_path_factory.mktemp("daemon-protocol") / "probe"
    built = subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(RUNTIME),
            str(PROBE),
            "-o",
            str(output),
        ],
        capture_output=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr
    return output


def run(probe, data=b"", *arguments):
    return subprocess.run([str(probe), *arguments], input=data, capture_output=True, timeout=RUN_TIMEOUT)


@pytest.mark.parametrize(
    "encoded",
    [
        frame(1, startup()),
        frame(1, startup(lifetime=1, restart=0, environment=[])),
        frame(1, startup(name="工作é😀".encode(), arguments=[b"tool.exe", b"", "文字".encode()])),
        frame(2, struct.pack("<II", 2, 0)),
        frame(2, struct.pack("<II", 0x7FFFFFFF, 1)),
        frame(3, TOKEN),
        frame(4, TOKEN + struct.pack("<II", 42, 1)),
        frame(5, struct.pack("<IIII", 12, 2, 0xFFFFFFFF, 2)),
    ],
    ids=["init", "contained", "unicode", "ready", "max-pid", "commit", "ack", "error"],
)
def test_exact_wire_bytes(probe, encoded):
    result = run(probe, encoded)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == encoded


def test_all_small_buffer_and_truncation_boundaries(probe):
    result = run(probe, b"", "bounds")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b"daemon-protocol bounds PASS\n"


@pytest.mark.parametrize(
    "kind,length,accepted",
    [(1, 0, True), (5, MAX_PAYLOAD, True), (1, MAX_PAYLOAD + 1, False), (0, 0, False), (6, 0, False)],
)
def test_header_is_validated_before_payload_allocation(probe, kind, length, accepted):
    encoded = b"BTRCDM1\0" + struct.pack("<HHI", 1, kind, length)
    result = run(probe, encoded, "header")
    assert result.returncode == (0 if accepted else 2), result.stderr
    if accepted:
        assert result.stdout == f"type={kind} size={length}\n".encode()


@pytest.mark.parametrize(
    "encoded",
    [
        b"bTRCDM1\0" + struct.pack("<HHI", 1, 3, 16) + TOKEN,
        b"BTRCDM1x" + struct.pack("<HHI", 1, 3, 16) + TOKEN,
        b"BTRCDM1\0" + struct.pack("<HHI", 2, 3, 16) + TOKEN,
        frame(3, TOKEN) + b"x",
        frame(3, TOKEN + b"x"),
        frame(3, TOKEN[:-1]),
        frame(4, TOKEN + struct.pack("<II", 42, 1) + b"x"),
        frame(2, struct.pack("<II", 1, 0)),
        frame(2, struct.pack("<II", 0x80000000, 0)),
        frame(2, struct.pack("<II", 42, 2)),
        frame(5, struct.pack("<IIII", 12, 2, 5, 3)),
        frame(5, struct.pack("<IIII", 12, 2, 5, 0) + b"x"),
        frame(1, startup(budget=0)),
        frame(1, startup(lifetime=2)),
        frame(1, startup(restart=2)),
        frame(1, startup(arguments=[])),
        frame(1, startup() + b"x"),
        frame(1, startup(name=b"x" * 65537)),
        frame(1, startup(arguments=[b""] * 4097)),
        frame(1, startup(environment=[b""] * 4097)),
        frame(1, startup()[:-1]),
        frame(1, startup()[:-4] + b"\xff" * 4),
    ],
    ids=[
        "magic",
        "magic-nul",
        "version",
        "extra-frame-byte",
        "extra-token-byte",
        "short-token",
        "extra-ack-byte",
        "pid-one",
        "pid-overflow",
        "lifetime",
        "ownership",
        "extra-error-byte",
        "zero-budget",
        "init-lifetime",
        "restart",
        "no-argv",
        "extra-init-byte",
        "long-text",
        "many-arguments",
        "many-environment",
        "truncated-text",
        "bad-tail",
    ],
)
def test_rejects_malformed_frame(probe, encoded):
    result = run(probe, encoded)
    assert result.returncode == 2, result.stderr
    assert result.stdout == b""


@pytest.mark.parametrize(
    "invalid",
    [
        b"\0",
        b"a\0b",
        b"\xc0\xaf",
        b"\xed\xa0\x80",
        b"\xf4\x90\x80\x80",
        b"\xff",
        b"\x80",
        b"\xc2",
        b"\xe2\x82",
        b"\xf0\x9f\x98",
    ],
)
def test_strict_length_bounded_utf8(probe, invalid):
    for payload in (startup(name=invalid), startup(arguments=[invalid]), startup(environment=[invalid])):
        result = run(probe, frame(1, payload))
        assert result.returncode == 2, result.stderr


def test_limits_are_inclusive(probe):
    for payload in (startup(name=b"x" * 65536), startup(arguments=[b""] * 4096), startup(environment=[b""] * 4096)):
        encoded = frame(1, payload)
        result = run(probe, encoded)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert result.stdout == encoded


def test_total_payload_limit(probe):
    prefix = TOKEN + struct.pack("<QII", 3000, 0, 0) + text(b"") * 5
    arguments = [b"x" * 65536] * 15 + [b"x" * 65412]
    payload = prefix + vector(arguments) + vector([])
    assert len(payload) == MAX_PAYLOAD
    result = run(probe, frame(1, payload))
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == frame(1, payload)
    result = run(probe, frame(1, payload + b"x"))
    assert result.returncode == 2


@pytest.mark.parametrize("target", ["x86_64-windows-gnu", "aarch64-windows-gnu"])
def test_protocol_compiles_for_windows(target, tmp_path):
    result = subprocess.run(
        [
            "zig",
            "cc",
            "-target",
            target,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(RUNTIME),
            "-c",
            str(PROBE),
            "-o",
            str(tmp_path / "protocol.o"),
        ],
        capture_output=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
