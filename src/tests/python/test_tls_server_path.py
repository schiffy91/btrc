"""Check TLS server identity and path building with independently issued certificate chains."""

import base64
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls_x509 import change, children, tlv
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def chains(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("requires OpenSSL to issue and verify independent certificate chains")
    directory = tmp_path_factory.mktemp("server-paths")

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=directory, capture_output=True, check=True, timeout=30)

    for name, kind in (("rsa", "RSA"), ("other", "RSA"), ("ed", "ED25519")):
        key_options = ["-pkeyopt", "rsa_keygen_bits:2048"] if kind == "RSA" else []
        openssl("genpkey", "-algorithm", kind, *key_options, "-out", name + ".key")

    for name, curve in (("p256", "P-256"), ("p384", "P-384")):
        openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:" + curve, "-out", name + ".key")

    for name, options in (
        ("pss-any", []),
        (
            "pss-sha384",
            [
                "-pkeyopt",
                "rsa_pss_keygen_md:sha384",
                "-pkeyopt",
                "rsa_pss_keygen_mgf1_md:sha384",
                "-pkeyopt",
                "rsa_pss_keygen_saltlen:32",
            ],
        ),
    ):
        openssl("genpkey", "-algorithm", "RSA-PSS", "-pkeyopt", "rsa_keygen_bits:2048", *options, "-out", name + ".key")

    def issue(name, subject, key, issuer, extensions, *options, serial=None):
        openssl("req", "-new", "-key", key + ".key", "-subj", "/CN=" + subject, "-out", name + ".csr")
        config = "\n".join(["subjectKeyIdentifier=hash", "authorityKeyIdentifier=keyid", *extensions])
        (directory / "extensions.cnf").write_text(config + "\n")
        signing = (
            ["-key", key + ".key"] if issuer is None else ["-CA", issuer + ".pem", "-CAkey", keys[issuer] + ".key"]
        )
        openssl(
            "x509",
            "-req",
            "-in",
            name + ".csr",
            "-days",
            "3",
            "-set_serial",
            str(len(keys) + 2 if serial is None else serial),
            *signing,
            *options,
            "-extfile",
            "extensions.cnf",
            "-out",
            name + ".pem",
        )
        openssl("x509", "-in", name + ".pem", "-outform", "DER", "-out", name + ".der")
        keys[name] = key

    keys = {}
    ca = ["basicConstraints=critical,CA:TRUE", "keyUsage=critical,keyCertSign,cRLSign"]
    leaf = ["basicConstraints=critical,CA:FALSE", "keyUsage=critical,digitalSignature", "extendedKeyUsage=serverAuth"]
    san = "subjectAltName=DNS:service.example.test,DNS:*.edge.example.test,IP:192.0.2.3,IP:2001:db8::3"
    issue("root", "Trusted", "rsa", None, ca)
    issue("wrong-ski-root", "Trusted", "rsa", None, [*ca, "subjectKeyIdentifier=01:02:03:04"])
    issue("case-root", "  TRustED  ", "rsa", None, ca)
    issue("root-other", "Untrusted", "other", None, ca)
    issue("root-short", "Short", "rsa", None, [*ca[1:], "basicConstraints=critical,CA:TRUE,pathlen:0"])
    issuer = [
        *ca,
        "extendedKeyUsage=serverAuth",
        "nameConstraints=critical,permitted;DNS:.example.test,excluded;DNS:blocked.example.test,"
        "permitted;IP:192.0.2.0/255.255.255.0,permitted;IP:2001:db8::/ffff:ffff:ffff:ffff::",
    ]
    issue("ca", "Issuer", "ed", "root", issuer, "-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:digest")
    issue("wrong-key", "Issuer", "other", "root", issuer)
    original_serial = (
        subprocess.check_output(["openssl", "x509", "-in", directory / "ca.pem", "-serial", "-noout"])
        .decode()
        .strip()
        .split("=")[1]
    )
    issue("second-ca", "Issuer", "ed", "root", issuer)
    issue("other-authority-ca", "Issuer", "ed", "root-other", issuer, serial=int(original_serial, 16))
    issue("wrong-issuer", "Issuer", "ed", "root-other", issuer)
    issue("short-chain", "Issuer", "ed", "root-short", issuer)
    issue("bad-ca-ku", "Issuer", "ed", "root", [ca[0], "keyUsage=critical,digitalSignature"])
    issue("not-ca", "Issuer", "ed", "root", leaf)
    issue("ca-client", "Issuer", "ed", "root", [*ca, "extendedKeyUsage=clientAuth"])
    issue("leaf", "ignored.example.test", "rsa", "ca", [*leaf, san])
    issue("authority-leaf", "HTTPS", "rsa", "ca", [*leaf, san, "authorityKeyIdentifier=keyid:always,issuer:always"])
    issue("rsa-leaf", "ignored", "other", "wrong-key", [*leaf, san], "-sha384")
    for key in ("p256", "p384"):
        issue(key + "-ca", key + " issuer", key, "root", issuer)
        for digest in ("sha256", "sha384", "sha512"):
            issue(key + "-" + digest, "HTTPS", "ed", key + "-ca", [*leaf, san], "-" + digest)
    for key, digests in (("pss-any", ("sha256", "sha384", "sha512")), ("pss-sha384", ("sha384",))):
        issue(key + "-ca", key + " issuer", key, "root", issuer)
        for digest in digests:
            issue(
                key + "-" + digest,
                "HTTPS",
                "ed",
                key + "-ca",
                [*leaf, san],
                "-" + digest,
                "-sigopt",
                "rsa_pss_saltlen:digest",
            )
    # Preserve n/e while changing local SPKI restrictions. A directly selected
    # trust anchor is external input and its self-signature is not relied upon.
    base = (directory / "pss-sha384-ca.der").read_bytes()
    tbs = children(base)[0]
    spki = children(tbs)[6]
    alg = children(spki)[0]
    params = children(alg)[1]
    digest, mgf, salt = children(params)
    assert salt == tlv(162, tlv(2, bytes([32])))
    mismatches = {
        "salt-large": change(params, 2, tlv(162, tlv(2, bytes([49])))),
        "digest-sha256": change(
            params, 0, digest.replace(bytes.fromhex("608648016503040202"), bytes.fromhex("608648016503040201"))
        ),
        "mask-sha256": change(
            params, 1, mgf.replace(bytes.fromhex("608648016503040202"), bytes.fromhex("608648016503040201"))
        ),
        "mask-default": tlv(48, digest + salt),
        "sha1-defaults": tlv(48, b""),
        "bad-trailer": tlv(48, digest + mgf + salt + tlv(163, tlv(2, b"\x02"))),
        "negative-salt": change(params, 2, tlv(162, tlv(2, b"\xff"))),
    }
    for label, modified in mismatches.items():
        cert = change(base, 0, change(tbs, 6, change(spki, 0, change(alg, 1, modified))))
        (directory / (label + ".der")).write_bytes(cert)
        (directory / (label + ".pem")).write_bytes(
            b"-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(cert) + b"-----END CERTIFICATE-----\n"
        )
    issue("weak-signature", "ignored", "other", "wrong-key", [*leaf, san], "-sha1")
    issue("client", "ignored", "rsa", "ca", [*leaf[:2], "extendedKeyUsage=clientAuth", san])
    issue("wrong-ku", "ignored", "rsa", "ca", [leaf[0], "keyUsage=critical,keyEncipherment", leaf[2], san])
    issue("dns-out", "ignored", "rsa", "ca", [*leaf, san + ",DNS:never.example"])
    issue("dns-block", "ignored", "rsa", "ca", [*leaf, san + ",DNS:blocked.example.test"])
    issue("wildcard-block", "ignored", "rsa", "ca", [*leaf, san + ",DNS:*.example.test"])
    issue("ip-out", "ignored", "rsa", "ca", [*leaf, san + ",IP:192.0.3.3"])
    issue("too-broad", "ignored", "rsa", "root", [*leaf, "subjectAltName=DNS:*.test"])
    issue("numeric", "ignored", "rsa", "root", [*leaf, "subjectAltName=DNS:192.0.2.3,DNS:127.1,DNS:0x7f000001"])
    issue("no-san", "service.example.test", "rsa", "root", leaf)
    corrupted = bytearray((directory / "leaf.der").read_bytes())
    corrupted[-1] ^= 1
    (directory / "corrupt.der").write_bytes(corrupted)
    openssl("x509", "-inform", "DER", "-in", "corrupt.der", "-out", "corrupt.pem")
    return directory


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("gcc", True), ("clang", True)])
def test_tls_server_path(tmp_path, compiler, request, c_compiler, sanitized, chains):
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    for path in (ROOT / "src/stdlib/TLS").glob("*.btrc"):
        if path.name.startswith("X509") or path.name in ("DER.btrc", "ECDSASignature.btrc"):
            shutil.copy(path, tmp_path / path.name)
    source = tmp_path / "X509Path.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated = tmp_path / "Program.c"
    plan = _transpile(compiler, source, generated, request)
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    client = tmp_path / "Program"
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=client,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", *flags],
        link_flags=flags,
    )
    assert DependencyAudit().binary_problems(client, PackageTarget.parse(None).label) == []
    now = int(time.time())
    env = os.environ | {"ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"}

    def check(
        expected,
        cert="leaf",
        intermediates=("ca",),
        anchors=("root",),
        host="service.example.test",
        *,
        at=now,
        oracle=True,
    ):
        args = [
            host,
            str(at),
            cert + ".der",
            *(i + ".der" for i in intermediates),
            "--anchors",
            *(a + ".der" for a in anchors),
        ]
        result = subprocess.run([str(client), *args], cwd=chains, env=env, capture_output=True, timeout=15)
        assert result.returncode == (0 if expected else 1), (args, result.stderr)
        assert not result.stderr, result.stderr
        if oracle and anchors:
            import ipaddress

            target = (
                ["-verify_ip", str(ipaddress.ip_address(bytes.fromhex(host[3:])))]
                if host.startswith("ip:")
                else ["-verify_hostname", host]
            )
            trusted = tmp_path / "trusted.pem"
            trusted.write_bytes(b"".join((chains / (a + ".pem")).read_bytes() for a in anchors))
            options = []
            if intermediates:
                peers = tmp_path / "peers.pem"
                peers.write_bytes(b"".join((chains / (i + ".pem")).read_bytes() for i in intermediates))
                options = ["-untrusted", str(peers)]
            verified = subprocess.run(
                [
                    "openssl",
                    "verify",
                    "-no-CApath",
                    "-no-CAstore",
                    "-trusted",
                    str(trusted),
                    "-partial_chain",
                    "-purpose",
                    "sslserver",
                    "-attime",
                    str(at),
                    *target,
                    *options,
                    cert + ".pem",
                ],
                cwd=chains,
                capture_output=True,
                timeout=15,
            )
            assert (verified.returncode == 0) == expected, (args, verified.stdout, verified.stderr)

    check(True)
    check(True, anchors=("case-root",))
    check(False, anchors=("wrong-ski-root",))
    check(True, "authority-leaf")
    check(False, "authority-leaf", ("second-ca",))
    check(False, "authority-leaf", ("other-authority-ca",), anchors=("root-other",))
    check(True, "authority-leaf", ("second-ca", "ca"))
    check(True, host="SERVICE.EXAMPLE.TEST")
    check(True, host="SERVICE.EXAMPLE.TEST.", oracle=False)
    check(True, host="a.edge.example.test")
    check(False, host="x.a.edge.example.test")
    check(False, host="edge.example.test")
    check(False, host="service.example.test.com")
    check(True, host="ip:c0000203")
    check(False, host="ip:c0000204")
    check(True, host="ip:20010db8000000000000000000000003")
    check(False, host="ignored.example.test")
    check(False, "corrupt")
    check(False, intermediates=())
    check(False, anchors=())
    check(False, intermediates=("ca", "root"), anchors=("root-other",))
    check(False, intermediates=("wrong-key",))
    check(True, intermediates=("wrong-key", "ca"))
    check(True, intermediates=("wrong-issuer", "ca"), oracle=False)
    check(True, anchors=("ca",), intermediates=())
    check(True, anchors=("leaf",), intermediates=())
    check(False, intermediates=("short-chain",), anchors=("root-short",))
    for ca in ("not-ca", "bad-ca-ku", "ca-client"):
        check(False, intermediates=(ca,))
    check(True, "rsa-leaf", ("wrong-key",))
    for key in ("p256", "p384"):
        for digest in ("sha256", "sha384", "sha512"):
            check(True, key + "-" + digest, (key + "-ca",))
    for key, digests in (("pss-any", ("sha256", "sha384", "sha512")), ("pss-sha384", ("sha384",))):
        for digest in digests:
            signer = key + "-ca"
            cert = key + "-" + digest
            check(True, cert, (signer,))
            code = {"sha256": 0x0809, "sha384": 0x080A, "sha512": 0x080B}[digest]
            for scheme, accepted in ((code, True), (code - 5, False), (0x0401, False)):
                signed = subprocess.run(
                    [client, "--signature", hex(scheme), signer + ".der", cert + ".der"],
                    cwd=chains,
                    env=env,
                    capture_output=True,
                    timeout=10,
                )
                assert signed.returncode == (0 if accepted else 1), (signer, digest, scheme, signed.stderr)
                assert not signed.stderr
    for signer in (
        "salt-large",
        "digest-sha256",
        "mask-sha256",
        "mask-default",
        "sha1-defaults",
        "bad-trailer",
        "negative-salt",
    ):
        # OpenSSL 3.5 accepts an unsupported trailerField in the SPKI. RFC
        # 4055 only defines trailer field 1, and DER omits that default.
        check(False, "pss-sha384-sha384", intermediates=(), anchors=(signer,), oracle=signer != "bad-trailer")
    check(False, "weak-signature", ("wrong-key",), oracle=False)
    for cert in ("client", "dns-out", "dns-block", "ip-out"):
        check(False, cert)
    check(False, "wrong-ku", oracle=False)  # TLS 1.3 always signs CertificateVerify.
    check(False, "wildcard-block", oracle=False)
    check(False, "too-broad", (), host="foo.test", oracle=False)
    for host in ("192.0.2.3", "127.1", "0x7f000001"):
        check(False, "numeric", (), host=host, oracle=False)
    check(False, "no-san", (), oracle=False)  # RFC 9525 does not match the legacy Subject CN.
    check(False, at=now - 3600)
    check(False, at=now + 86400 * 7)
