"""Check NIST ECDH encodings and both directions of OpenSSL key agreement."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls_x509 import body, children, tlv
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]


def openssl(*args):
    return subprocess.run(["openssl", *args], capture_output=True, check=True, timeout=30).stdout


@pytest.fixture(scope="module")
def key_exchanges(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL is required as an independent ECDH oracle")
    work = tmp_path_factory.mktemp("ecdh-oracle")
    cases = []
    for group, curve, order in [
        (23, "prime256v1", "ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551"),
        (
            24,
            "secp384r1",
            "ffffffffffffffffffffffffffffffffffffffffffffffffc7634d81f4372ddf581a0db248b0a77aecec196accc52973",
        ),
    ]:
        size = len(order) // 2
        keys = []
        for i in range(3):
            key = work / f"{group}-{i}.pem"
            public = key.with_suffix(".pub")
            openssl("ecparam", "-name", curve, "-genkey", "-noout", "-out", key)
            openssl("pkey", "-in", key, "-pubout", "-out", public)
            # SEC 1 ECPrivateKey and X.509 SubjectPublicKeyInfo.
            scalar = body(children(openssl("ec", "-in", key, "-outform", "DER"))[1])
            point = body(children(openssl("pkey", "-in", key, "-pubout", "-outform", "DER"))[1])[1:]
            assert len(scalar) == size and len(point) == 1 + 2 * size and point[0] == 4
            cases.append(([group, scalar.hex()], point.hex()))
            keys.append((key, public, scalar, point))
        for key, _, scalar, _ in keys:
            for _, public, _, peer in keys:
                shared = openssl("pkeyutl", "-derive", "-inkey", key, "-peerkey", public)
                assert len(shared) == size
                cases.append(([group, scalar.hex(), peer.hex()], shared.hex()))
        # Explicitly hit the identity, doubling and inverse-point cases in the
        # complete addition formula. A minimal SEC 1 private key lets OpenSSL
        # compute the independent public point for a chosen scalar.
        oid = bytes.fromhex("2a8648ce3d030107" if group == 23 else "2b81040022")
        for value in [1, 2, int(order, 16) - 1]:
            chosen = value.to_bytes(size, "big")
            der = work / "chosen.der"
            der.write_bytes(tlv(48, tlv(2, b"\x01") + tlv(4, chosen) + tlv(160, tlv(6, oid))))
            spki = openssl("ec", "-inform", "DER", "-in", der, "-pubout", "-outform", "DER")
            expected = body(children(spki)[1])[1:]
            cases.append(([group, chosen.hex()], expected.hex()))
            # The generator has scalar 1, so its shared x is the chosen point's x.
            if value == 1:
                generator = expected
            cases.append(([group, chosen.hex(), generator.hex()], expected[1 : size + 1].hex()))
        scalar, point = keys[0][2:]
        for bad in [bytes(size), bytes.fromhex(order), bytes([255]) * size, scalar[1:], b"\0" + scalar]:
            cases.append(([group, bad.hex()], "invalid"))
            cases.append(([group, bad.hex(), point.hex()], "invalid"))
        for bad in [
            b"\0",
            point[:-1],
            b"\x02" + point[1 : size + 1],
            b"\x04" + bytes(2 * size),
            b"\x04" + bytes([255]) * size + point[-size:],
            point[:-1] + bytes([point[-1] ^ 1]),
        ]:
            cases.append(([group, scalar.hex(), bad.hex()], "invalid"))
        cases.append(([25, scalar.hex(), point.hex()], "invalid"))
    return cases


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "asan-ubsan"])
def test_ecdh(tmp_path, request, compiler, sanitized, key_exchanges):
    cc = ("/usr/bin/clang" if sys.platform == "darwin" else "clang") if sanitized else "cc"
    if not shutil.which(cc):
        pytest.skip(f"{cc} is required to build ECDH")
    source = ROOT / "src/tests/native/tls/ECDHCheck.btrc"
    generated, binary = tmp_path / "Program.c", tmp_path / "Program"
    plan = _transpile(compiler, source, generated, request)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    builder, toolchain = NativePlanBuilder(), {"cc": cc}
    run_env = os.environ
    if sanitized and sys.platform == "darwin":

        def run(command, **options):
            return subprocess.run(command, **{**options, "env": apple_environment(options.get("env"))})

        builder = NativePlanBuilder(runner=run)
        toolchain = {"cc": "/usr/bin/clang", "cxx": "/usr/bin/clang++"}
        run_env = apple_environment(run_env)
    builder.build(
        plan_path=plan,
        generated_c=generated,
        output=binary,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
        **toolchain,
    )
    assert not DependencyAudit().binary_problems(binary, PackageTarget.parse(None).label)
    for args, expected in key_exchanges:
        result = subprocess.run(
            [binary, *map(str, args)],
            env={**run_env, "UBSAN_OPTIONS": "halt_on_error=1"},
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.stdout.strip() == expected
        assert not result.stderr
