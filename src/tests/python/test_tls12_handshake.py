"""Drive the first-party TLS 1.2 client, including certificate trust and Finished, against OpenSSL."""

import os
import select
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import BinaryImports, DependencyAudit
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls12_records import SUITES, records
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True, timeout=30)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL is required as the independent TLS 1.2 server")
    root = tmp_path_factory.mktemp("tls12-pki")
    for ca in ("root", "stranger"):
        openssl(
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-nodes",
            "-subj",
            f"/CN={ca}",
            "-days",
            "2",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign",
            "-keyout",
            root / f"{ca}.key",
            "-out",
            root / f"{ca}.pem",
        )
        openssl("x509", "-in", root / f"{ca}.pem", "-outform", "der", "-out", root / f"{ca}.der")
    (root / "extensions").write_text(
        "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:loopback.test\n"
    )
    for kind, args in [
        ("RSA", ["-newkey", "rsa:2048"]),
        ("ECDSA", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256"]),
        ("P384", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-384"]),
        ("Ed25519", ["-newkey", "ed25519"]),
        (
            "PSS",
            [
                "-newkey",
                "rsa-pss",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-pkeyopt",
                "rsa_pss_keygen_md:sha256",
                "-pkeyopt",
                "rsa_pss_keygen_mgf1_md:sha256",
                "-pkeyopt",
                "rsa_pss_keygen_saltlen:32",
            ],
        ),
    ]:
        openssl(
            "req",
            "-new",
            *args,
            "-nodes",
            "-subj",
            "/CN=unused",
            "-keyout",
            root / f"{kind}.key",
            "-out",
            root / f"{kind}.csr",
        )
        openssl(
            "x509",
            "-req",
            "-in",
            root / f"{kind}.csr",
            "-CA",
            root / "root.pem",
            "-CAkey",
            root / "root.key",
            "-set_serial",
            "33",
            "-days",
            "1",
            "-extfile",
            root / "extensions",
            "-out",
            root / f"{kind}.pem",
        )
    return root


def exact(pipe, size):
    data = bytearray()
    while len(data) < size:
        assert select.select([pipe], [], [], 15)[0], "timed out waiting for a BTRC TLS record"
        part = os.read(pipe.fileno(), size - len(data))
        assert part, "unexpected end of BTRC TLS flight"
        data.extend(part)
    return bytes(data)


def next_record(process):
    header = exact(process.stdout, 5)
    return header + exact(process.stdout, int.from_bytes(header[3:], "big"))


def record(kind, data):
    return bytes([kind, 3, 3]) + len(data).to_bytes(2, "big") + data


def handshake_messages(data):
    result = []
    while data:
        length = 4 + int.from_bytes(data[1:4], "big")
        assert len(data) >= length and length >= 4
        result.append(data[:length])
        data = data[length:]
    return result


def live(exe, suite, name, root, fault=None, credential=None, *, env=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(name)
    context.set_ecdh_curve("X25519")
    context.set_alpn_protocols(["http/1.1"])
    context.options |= ssl.OP_NO_TICKET
    key = name.split("-")[1]
    context.load_cert_chain(root / f"{credential or key}.pem", root / f"{credential or key}.key")
    if key == "RSA":
        context.verify_mode = ssl.CERT_OPTIONAL
        context.load_verify_locations(cafile=root / "root.pem")
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    server = context.wrap_bio(incoming, outgoing, server_side=True)
    authority = (root / "root.der").read_bytes().hex()
    now = str(int(time.time()))
    cmd = [exe, "new", authority, "loopback.test", now]
    with subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env
    ) as client:
        try:
            hello = next_record(client)
            incoming.write(hello)
            with pytest.raises(ssl.SSLWantReadError):
                server.do_handshake()
            server_hello = records(outgoing.read())
            assert all(item[0] == 22 for item in server_hello)
            messages = handshake_messages(b"".join(item[5:] for item in server_hello))
            assert [item[0] for item in messages] == ([2, 11, 12, 13, 14] if key == "RSA" else [2, 11, 12, 14])
            # Exercise arbitrary handshake fragmentation and coalescing, including
            # a two-byte handshake header split across adjacent records.
            joined = b"".join(messages)
            for start, end in [(0, 2), (2, 40), (40, len(joined))]:
                client.stdin.write(record(22, joined[start:end]))
            from_client = [next_record(client) for _ in range(3)]
            assert [r[0] for r in from_client] == [22, 20, 22]
            assert [x[0] for x in handshake_messages(from_client[0][5:])] == ([11, 16] if key == "RSA" else [16])
            incoming.write(b"".join(from_client))
            server.do_handshake()
            assert server.cipher()[0] == name and server.selected_alpn_protocol() == "http/1.1"
            server_finished = records(outgoing.read())
            assert [r[0] for r in server_finished] == [20, 22]
            if fault:
                ccs, finished_record = server_finished
                if fault == "finished-tag":
                    client.stdin.write(ccs + finished_record[:-1] + bytes([finished_record[-1] ^ 1]))
                elif fault == "missing-ccs":
                    client.stdin.write(finished_record)
                elif fault == "early-application":
                    client.stdin.write(ccs + bytes([23]) + finished_record[1:])
                else:
                    raise AssertionError(fault)
                assert client.wait(timeout=15) == 9 and not client.stdout.read() and not client.stderr.read()
                return None
            client.stdin.write(b"".join(server_finished))
            payload = b"authenticated BTRC TLS 1.2 echo\0" + bytes(range(255))
            assert server.write(payload) == len(payload)
            app_record = outgoing.read()
            client.stdin.write(app_record)
            incoming.write(next_record(client))
            assert server.read(16384) == payload
            with pytest.raises(ssl.SSLWantReadError):
                server.unwrap()
            client.stdin.write(outgoing.read())
            incoming.write(next_record(client))
            server.unwrap()
            assert client.wait(timeout=15) == 0 and not client.stderr.read()
            return cmd, hello[5:], messages, server_finished
        finally:
            if client.poll() is None:
                client.kill()


def negatives(exe, root, cmd, hello, messages, *, env=None):
    now = cmd[-1]
    good_anchor = cmd[2]
    server_hello, certificate, key_exchange = messages[:3]

    # Tampering is tested before any secret or application flight is sent.
    # Reuse precisely the captured ClientHello for the ServerKeyExchange signature.
    def reject(parts, *, anchor=good_anchor, name="loopback.test", at=now, code=5):
        run = subprocess.run(
            [exe, hello.hex(), anchor, name, at],
            input=b"".join(record(22, m) for m in parts),
            capture_output=True,
            timeout=15,
            env=env,
        )
        assert run.returncode == code and run.stdout == record(22, hello), (run.returncode, run.stderr)

    reject(messages, anchor=(root / "stranger.der").read_bytes().hex(), code=8)
    reject(messages, name="wrong.test", code=8)
    reject(messages, at="1", code=8)
    reject([certificate, server_hello, *messages[2:]])
    reject([server_hello, certificate, key_exchange[:-1] + bytes([key_exchange[-1] ^ 1]), *messages[3:]])
    reject([server_hello, certificate, key_exchange[:5] + b"\0\x17" + key_exchange[7:], *messages[3:]])
    reject([*messages[:-1], messages[-1] + messages[-1]])
    for sentinel in (b"DOWNGRD\x01", b"DOWNGRD\x00"):
        changed = bytearray(server_hello)
        changed[30:38] = sentinel
        reject([bytes(changed), *messages[1:]])
    # Flood of warning alerts during handshake must be bounded and rejected (> 4 warnings).
    warning_flood = subprocess.run(
        [exe, hello.hex(), good_anchor, "loopback.test", now],
        input=record(22, server_hello) + record(21, b"\x01\x64") * 5,
        capture_output=True,
        timeout=15,
        env=env,
    )
    assert warning_flood.returncode == 5 and warning_flood.stdout == record(22, hello)
    # Excessive 1-byte handshake record flood (> 256 records) must be rejected.
    joined = b"".join(messages)
    fragment_flood = subprocess.run(
        [exe, hello.hex(), good_anchor, "loopback.test", now],
        input=b"".join(record(22, joined[i : i + 1]) for i in range(min(len(joined), 260))),
        capture_output=True,
        timeout=15,
        env=env,
    )
    assert fragment_flood.returncode == 5 and fragment_flood.stdout == record(22, hello)
    # Oversized plaintext alert record (> 16384 bytes) must be rejected with record_overflow.
    oversized_alert = subprocess.run(
        [exe, hello.hex(), good_anchor, "loopback.test", now],
        input=record(21, b"\x01\x64" * 8193),
        capture_output=True,
        timeout=15,
        env=env,
    )
    assert oversized_alert.returncode == 5 and oversized_alert.stdout == record(22, hello)
    # Strip required extensions (EMS 0x0017 and renegotiation_info 0xff01) individually.
    for required_ext in (b"\x00\x17", b"\xff\x01"):
        changed = bytearray(server_hello)
        pos = 4 + 35 + changed[4 + 34] + 5
        while pos < len(changed):
            n = int.from_bytes(changed[pos + 2 : pos + 4], "big")
            if changed[pos : pos + 2] == required_ext:
                del changed[pos : pos + 4 + n]
                changed[1:4] = (len(changed) - 4).to_bytes(3, "big")
                extlen = 4 + 35 + changed[4 + 34] + 3
                changed[extlen : extlen + 2] = (len(changed) - extlen - 2).to_bytes(2, "big")
                break
            pos += 4 + n
        else:
            raise AssertionError(f"OpenSSL omitted extension {required_ext.hex()}")
        reject([bytes(changed), *messages[1:]])


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "asan-ubsan"])
def test_tls12_client(tmp_path, request, compiler, sanitized, pki):
    cc = ("/usr/bin/clang" if sys.platform == "darwin" else "clang") if sanitized else "cc"
    if not shutil.which(cc):
        pytest.skip(f"{cc} is required to build the TLS 1.2 client")
    for module in (ROOT / "src/stdlib/TLS").glob("*.btrc"):
        shutil.copy(module, tmp_path)
    source = tmp_path / "TLS12Client.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated, exe = tmp_path / "Program.c", tmp_path / "Program"
    plan = _transpile(compiler, source, generated, request)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    builder, toolchain = NativePlanBuilder(), {"cc": cc}
    run_env = None
    if sanitized and sys.platform == "darwin":

        def run(command, **options):
            return subprocess.run(command, **{**options, "env": apple_environment(options.get("env"))})

        builder = NativePlanBuilder(runner=run)
        toolchain = {"cc": "/usr/bin/clang", "cxx": "/usr/bin/clang++"}
        run_env = apple_environment()
    builder.build(
        plan_path=plan,
        generated_c=generated,
        output=exe,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
        **toolchain,
    )
    assert not DependencyAudit().binary_problems(exe, PackageTarget.parse(None).label)
    assert all("ssl" not in lib.lower() and "crypto" not in lib.lower() for lib in BinaryImports.read(exe))
    for suite, name in SUITES.items():
        cmd, hello, messages, _ = live(exe, suite, name, pki, env=run_env)
        if suite == 0xC02B:
            negatives(exe, pki, cmd, hello, messages, env=run_env)
            for fault in ["finished-tag", "missing-ccs", "early-application"]:
                live(exe, suite, name, pki, fault, env=run_env)
    for credential, suite in [("P384", 0xC02C), ("Ed25519", 0xCCA9), ("PSS", 0xC02F)]:
        live(exe, suite, SUITES[suite], pki, credential=credential, env=run_env)
