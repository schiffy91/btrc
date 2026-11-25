"""Large TLS 1.3 retry cookies preserve the exact transcript across plaintext records."""

import hashlib
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import DependencyAudit
from src.tests.native_build import NativeCorpusBuild
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls_handshake import RETRY_RANDOM, hello_extensions, read_exact, read_record

ROOT = Path(__file__).resolve().parents[3]


def uint16(value):
    return value.to_bytes(2, "big")


def handshake(kind, body):
    return bytes([kind]) + len(body).to_bytes(3, "big") + body


def check_framing(exe, size, *, oversized_record=False):
    local, peer = socket.socketpair()
    with local, peer, subprocess.Popen([exe], stdin=peer, stdout=peer, stderr=subprocess.PIPE) as proc:
        peer.close()
        local.settimeout(15)
        try:
            first = read_record(local)
            assert first[:3] == b"\x16\x03\x03"
            msg = first[5:]
            size_offset = min(s.start for s in hello_extensions(first).values()) - 11
            cookie_size = size - len(msg) - 6
            cookie = (bytes(range(256)) * (cookie_size // 256 + 1))[:cookie_size]
            cookie_extension = b"\x00\x2c" + uint16(len(cookie) + 2) + uint16(len(cookie)) + cookie
            extensions = bytes.fromhex("002b00020304") + cookie_extension
            # The session id echo occupies bytes 38..70 in the ClientHello handshake message.
            body = (
                b"\x03\x03" + RETRY_RANDOM + msg[38:71] + bytes.fromhex("130200") + uint16(len(extensions)) + extensions
            )
            retry = handshake(2, body)
            if oversized_record:
                chunk = retry[:16385]
                assert len(chunk) == 16385
                local.sendall(b"\x16\x03\x03" + uint16(len(chunk)) + chunk)
                assert proc.wait(timeout=10) != 0 and b"invalid retry" in proc.stderr.read()
                return
            # Split the HRR inside its handshake header as well as on full record boundaries.
            for start in [0, *range(2, len(retry), 16384)]:
                chunk = retry[:2] if start == 0 else retry[start : start + 16384]
                local.sendall(b"\x16\x03\x03" + uint16(len(chunk)) + chunk)
            second = bytearray()
            while len(second) < size:
                record = read_record(local)
                assert record[:3] == b"\x16\x03\x03"
                assert len(record) - 5 == min(size - len(second), 16384)
                second.extend(record[5:])
            expected = bytearray(msg + cookie_extension)
            expected[1:4] = (size - 4).to_bytes(3, "big")
            expected[size_offset : size_offset + 2] = uint16(size - size_offset - 2)
            assert second == expected
            synthetic_first = handshake(254, hashlib.sha384(msg).digest())
            assert read_exact(local, 48) == hashlib.sha384(synthetic_first + retry + second).digest()
            assert proc.wait(timeout=10) == 0 and proc.stderr.read() == b""
            assert local.recv(1) == b""
        finally:
            proc.kill()


def check_ccs_rules(exe):
    ccs = bytes.fromhex("140303000101")

    def build_retry(first):
        msg = first[5:]
        cookie = b"c" * 32
        cookie_ext = b"\x00\x2c" + uint16(len(cookie) + 2) + uint16(len(cookie)) + cookie
        extensions = bytes.fromhex("002b00020304") + cookie_ext
        body = b"\x03\x03" + RETRY_RANDOM + msg[38:71] + bytes.fromhex("130200") + uint16(len(extensions)) + extensions
        return handshake(2, body)

    # 1. Pre-ServerHello CCS must be rejected.
    local, peer = socket.socketpair()
    with local, peer, subprocess.Popen([exe], stdin=peer, stdout=peer, stderr=subprocess.PIPE) as proc:
        peer.close()
        local.settimeout(10)
        try:
            read_record(local)
            local.sendall(ccs)
            assert proc.wait(timeout=10) != 0 and b"invalid retry" in proc.stderr.read()
        finally:
            proc.kill()

    # 2. Mid-fragment CCS interleaved inside a split HRR must be rejected.
    local, peer = socket.socketpair()
    with local, peer, subprocess.Popen([exe], stdin=peer, stdout=peer, stderr=subprocess.PIPE) as proc:
        peer.close()
        local.settimeout(10)
        try:
            retry = build_retry(read_record(local))
            local.sendall(b"\x16\x03\x03" + uint16(2) + retry[:2])
            local.sendall(ccs)
            assert proc.wait(timeout=10) != 0 and b"invalid retry" in proc.stderr.read()
        finally:
            proc.kill()

    # 3. After HRR, one dummy CCS is accepted, but a second dummy CCS is rejected.
    local, peer = socket.socketpair()
    with local, peer, subprocess.Popen([exe, "post-retry"], stdin=peer, stdout=peer, stderr=subprocess.PIPE) as proc:
        peer.close()
        local.settimeout(10)
        try:
            retry = build_retry(read_record(local))
            local.sendall(b"\x16\x03\x03" + uint16(len(retry)) + retry)
            read_record(local)
            local.sendall(ccs)
            assert read_exact(local, 3) == b"ok\n"
            local.sendall(ccs)
            assert proc.wait(timeout=10) != 0 and b"invalid post-retry" in proc.stderr.read()
        finally:
            proc.kill()

    # 4. After HRR, a malformed CCS payload (0x02 instead of 0x01) is rejected.
    local, peer = socket.socketpair()
    with local, peer, subprocess.Popen([exe, "post-retry"], stdin=peer, stdout=peer, stderr=subprocess.PIPE) as proc:
        peer.close()
        local.settimeout(10)
        try:
            retry = build_retry(read_record(local))
            local.sendall(b"\x16\x03\x03" + uint16(len(retry)) + retry)
            read_record(local)
            local.sendall(bytes.fromhex("140303000102"))
            assert proc.wait(timeout=10) != 0 and b"invalid post-retry" in proc.stderr.read()
        finally:
            proc.kill()

    # 5. Excessive 1-byte handshake fragmentation (> 256 records) must be bounded and rejected.
    local, peer = socket.socketpair()
    with local, peer, subprocess.Popen([exe], stdin=peer, stdout=peer, stderr=subprocess.PIPE) as proc:
        peer.close()
        local.settimeout(10)
        try:
            read_record(local)
            # Header claims a 400-byte ServerHello, delivered 1 byte per record.
            header = b"\x02\x00\x01\x90" + b"\x03\x03" + bytes(300)
            for i in range(260):
                try:
                    local.sendall(b"\x16\x03\x03\x00\x01" + header[i : i + 1])
                except OSError:
                    break
            assert proc.wait(timeout=10) != 0 and b"invalid retry" in proc.stderr.read()
        finally:
            proc.kill()


@pytest.mark.skipif(sys.platform == "win32", reason="fixture passes a POSIX socket as child stdin and stdout")
def test_retry_record_boundaries(tmp_path, request, compiler):
    for module in (ROOT / "src/stdlib/TLS").glob("*.btrc"):
        shutil.copy(module, tmp_path / module.name)
    source = tmp_path / "HelloRecords.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated, exe = tmp_path / "hello.c", tmp_path / "hello"
    plan = _transpile(compiler, source, generated, request)
    NativeCorpusBuild(generated, plan).build(exe)
    assert not DependencyAudit().binary_problems(exe, PackageTarget.parse(None).label)
    for size in [16383, 16384, 16385, 32768, 32769, 65000]:
        check_framing(exe, size)
    check_framing(exe, 32768, oversized_record=True)
    check_ccs_rules(exe)
