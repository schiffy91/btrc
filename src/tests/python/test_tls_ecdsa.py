"""Compare the TLS DER ECDSA verifier to OpenSSL for both named curves and all certificate hashes."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import DependencyAudit
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls_x509 import body, children, tlv
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
CURVES = [
    (23, "prime256v1", "ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551"),
    (
        24,
        "secp384r1",
        "ffffffffffffffffffffffffffffffffffffffffffffffffc7634d81f4372ddf581a0db248b0a77aecec196accc52973",
    ),
]


def integer(value):
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return tlv(2, b"\x00" + raw if raw[0] & 128 else raw)


@pytest.fixture(scope="module")
def signature_cases(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL is required as the independent ECDSA signer")
    directory = tmp_path_factory.mktemp("ecdsa-oracle")
    private, public, der = (directory / name for name in ("key.pem", "pub.pem", "sig.der"))
    cases = []
    for group, curve, order_hex in CURVES:
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", f"ec_paramgen_curve:{curve}", "-out", private],
            check=True,
        )
        subprocess.run(["openssl", "pkey", "-in", private, "-pubout", "-out", public], check=True)
        key_info = subprocess.check_output(["openssl", "pkey", "-in", private, "-pubout", "-outform", "DER"])
        bits = body(children(key_info)[1])
        assert bits[:2] == b"\x00\x04"
        point = bits[1:]
        order = int(order_hex, 16)
        for scheme, digest in [(0x0403, "-sha256"), (0x0503, "-sha384"), (0x0603, "-sha512")]:
            msg = b"TLS and X.509\x00" + bytes(range(64))
            sig = subprocess.check_output(["openssl", "dgst", digest, "-sign", private], input=msg)
            first, second = children(sig)
            r, s = (int.from_bytes(body(value), "big") for value in (first, second))
            reverse = tlv(48, first + integer(order - s))
            for signature in [sig, reverse]:
                der.write_bytes(signature)
                verified = subprocess.run(
                    ["openssl", "dgst", digest, "-verify", public, "-signature", der],
                    input=msg,
                    capture_output=True,
                    check=True,
                )
                assert b"Verified OK" in verified.stdout
                cases.append((group, scheme, point, msg, signature, True))
            cases.append((group, scheme, point, msg + b"!", sig, False))
            for bad_key in [
                b"\0",
                point[:-1],
                b"\x02" + point[1:],
                point[:-1] + bytes([point[-1] ^ 1]),
                b"\x04" + b"\xff" * (len(point) - 1),
            ]:
                cases.append((group, scheme, bad_key, msg, sig, False))
            for invalid in [
                b"",
                sig + b"\0",
                sig[:-1],
                tlv(48, first),
                tlv(48, first + second + first),
                tlv(48, integer(0) + second),
                tlv(48, first + integer(order)),
                tlv(48, integer(order) + second),
                tlv(48, tlv(2, b"\xff") + second),
                tlv(48, tlv(2, b"\x00" + body(first)) + second),
                b"\x30\x81" + sig[1:],
                tlv(48, integer(r + 1) + second),
            ]:
                cases.append((group, scheme, point, msg, invalid, False))
            cases.append((25, scheme, point, msg, sig, False))
            cases.append((group, 0x0807, point, msg, sig, False))
    return cases


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "asan-ubsan"])
def test_ecdsa_signature(tmp_path, request, compiler, sanitized, signature_cases):
    cc = ("/usr/bin/clang" if sys.platform == "darwin" else "clang") if sanitized else "cc"
    if not shutil.which(cc):
        pytest.skip(f"{cc} is required to build the ECDSA verifier")
    for name in ["ECDSASignature", "DER"]:
        shutil.copy(ROOT / f"src/stdlib/TLS/{name}.btrc", tmp_path)
    source = tmp_path / "ECDSACheck.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated, exe = tmp_path / "Program.c", tmp_path / "Program"
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
        output=exe,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
        **toolchain,
    )
    assert not DependencyAudit().binary_problems(exe, PackageTarget.parse(None).label)
    for group, scheme, key, message, signature, valid in signature_cases:
        result = subprocess.run(
            [exe, str(group), str(scheme), key.hex(), message.hex(), signature.hex()],
            env={**run_env, "UBSAN_OPTIONS": "halt_on_error=1"},
            check=True,
            timeout=15,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ("valid" if valid else "invalid")
        assert not result.stderr
