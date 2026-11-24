"""Reject invalid peer credentials through public HTTPClient before sending HTTP."""

import datetime
import os
import socket
import ssl
import subprocess
import sys
import threading

import pytest

from src.tests.python.test_linux_tls_http import client as client
from src.tests.python.test_linux_tls_http import compiled_clients as compiled_clients
from src.tests.python.test_tls_server_path import chains as chains

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux TLS provider")


@pytest.fixture(scope="module")
def credentials(chains):
    # The path suite already issues these trees. Add certificates whose
    # signed times lie on either side of the actual HTTP client's clock.
    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=chains, capture_output=True, check=True, timeout=30)

    (chains / "date-ca.db").touch()
    (chains / "date-ca.serial").write_text("40\n")
    (chains / "date-ca.cnf").write_text(
        "[ca]\ndefault_ca=test\n[test]\ndatabase=date-ca.db\nserial=date-ca.serial\nnew_certs_dir=.\n"
        "default_md=sha256\npolicy=subject\nunique_subject=no\n[subject]\ncommonName=supplied\n"
        "[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:service.example.test\n"
    )
    now = datetime.datetime.now(datetime.UTC)

    def date(offset):
        return (now + datetime.timedelta(days=offset)).strftime("%y%m%d%H%M%SZ")

    openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:1024", "-out", "small.key")
    openssl("req", "-new", "-key", "small.key", "-subj", "/CN=small", "-out", "small.csr")
    for name, csr, start, end in [("before", "leaf", -5, -1), ("after", "leaf", 1, 5), ("small", "small", -1, 5)]:
        openssl(
            "ca",
            "-batch",
            "-notext",
            "-config",
            "date-ca.cnf",
            "-extensions",
            "leaf",
            "-cert",
            "root.pem",
            "-keyfile",
            "rsa.key",
            "-startdate",
            date(start),
            "-enddate",
            date(end),
            "-in",
            csr + ".csr",
            "-out",
            name + ".pem",
        )
    return chains


# cert, intermediate, trust anchor, URL hostname, private key, expected peer alert
CASES = [
    ("leaf", "ca", "root", "service.example.test", "rsa", None),
    ("leaf", "ca", "root", "valid.edge.example.test", "rsa", None),
    ("leaf", "ca", "root-other", "service.example.test", "rsa", 48),
    ("leaf", "ca", "root", "nested.valid.edge.example.test", "rsa", 42),
    ("leaf", "ca", "root", "wrong.example.test", "rsa", 42),
    ("no-san", None, "root", "service.example.test", "rsa", 42),
    ("client", "ca", "root", "service.example.test", "rsa", 46),
    ("leaf", "not-ca", "root", "service.example.test", "rsa", 46),
    ("leaf", "bad-ca-ku", "root", "service.example.test", "rsa", 46),
    ("leaf", "short-chain", "root-short", "service.example.test", "rsa", 46),
    ("dns-block", "ca", "root", "service.example.test", "rsa", 46),
    ("before", None, "root", "service.example.test", "rsa", 45),
    ("after", None, "root", "service.example.test", "rsa", 45),
    ("small", None, "root", "service.example.test", "small", 42),
]


def public_case(binary, root, tmp, version, profile):
    cert, intermediate, anchor, host, key, alert = profile
    chain = tmp / "chain.pem"
    chain.write_bytes(
        (root / (cert + ".pem")).read_bytes() + ((root / (intermediate + ".pem")).read_bytes() if intermediate else b"")
    )
    hosts = tmp / "hosts"
    hosts.write_text("127.0.0.1 localhost " + host + "\n")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = version
    # Permit the independent peer to present intentionally weak credentials.
    context.set_ciphers("ECDHE-RSA-AES128-GCM-SHA256:@SECLEVEL=0")
    context.load_cert_chain(chain, root / (key + ".key"))
    events = []

    def observe(conn, direction, tls_version, kind, msg, data):
        if direction == "write" and int(kind) == 22 and int(msg) == 11:
            events.append("certificate")
        if direction == "read" and int(kind) == 21:
            events.append(bytes(data))

    context._msg_callback = observe
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            try:
                with listener.accept()[0] as conn:
                    conn.settimeout(4)
                    try:
                        tls = context.wrap_socket(conn, server_side=True)
                    except ssl.SSLError:
                        assert alert is not None
                        return
                    with tls:
                        request = bytearray()
                        while not request.endswith(b"\r\n\r\npayload"):
                            data = tls.recv(4096)
                            assert data
                            request.extend(data)
                        events.append("HTTP")
                        tls.sendall(b"HTTP/1.1 201 Created\r\nContent-Length: 13\r\n\r\ntrust:payload")
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        public_mode = "ok" if alert is None else "reject"
        run = subprocess.run(
            [
                "bwrap",
                "--ro-bind",
                "/",
                "/",
                "--ro-bind",
                hosts,
                "/etc/hosts",
                "--setenv",
                "PATH",
                "/no-curl",
                "--",
                binary,
                f"https://{host}:{listener.getsockname()[1]}/test",
                public_mode,
            ],
            env=os.environ
            | {
                "CURL_CA_BUNDLE": str(root / (anchor + ".pem")),
                "SSL_CERT_FILE": "",
                "SSL_CERT_DIR": "",
                "NO_PROXY": "*",
                "no_proxy": "*",
            },
            capture_output=True,
            text=True,
            timeout=9,
        )
        thread.join(5)
    assert not thread.is_alive() and not errors, (profile, errors, events, run)
    assert (run.returncode, run.stdout.strip(), run.stderr) == (
        0,
        "" if alert is None else "TLS handshake failed",
        "",
    ), (profile, run, events)
    if alert is None:
        assert events[:2] == ["certificate", "HTTP"], (profile, events)
    else:
        assert events == ["certificate", bytes([2, alert])], (profile, events)


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3], ids=["TLS1.2", "TLS1.3"])
def test_http_certificate_policy(client, credentials, tmp_path, version):
    for profile in CASES:
        public_case(client, credentials, tmp_path, version, profile)
