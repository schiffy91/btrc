"""End-to-end native macOS HTTPS, trust store, GET/HEAD-body, and proxy verification without curl."""

from __future__ import annotations

import http.server
import os
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import DependencyAudit
from src.tests.native.http.socks_peer import SocksPeer
from src.tests.native_build import NativeCorpusBuild

ROOT = Path(__file__).resolve().parents[3]

PROBE = """import Library.HTTP.HTTPClient;
import Library.Platform;
import Library.Strings;
import Library.Vector;

int main() {
    string method = Environment.get("TEST_METHOD", "GET");
    string url = Environment.get("TEST_URL", "");
    string body = Environment.get("TEST_BODY", "");
    int timeout = Strings.toInt(Environment.get("TEST_TIMEOUT", "3"));
    int limit = Strings.toInt(Environment.get("TEST_LIMIT", "65536"));
    Vector<string> headers = [];
    if (Environment.has("TEST_HEADER")) { headers.push(Environment.get("TEST_HEADER", "")); }
    if (Environment.has("TEST_HEADER2")) { headers.push(Environment.get("TEST_HEADER2", "")); }
    HTTPClient client = HTTPClient().timeout(timeout);
    client.maxResponseBytes = limit;
    HTTPClientResponse result = client.request(method, url, headers, body);
    print(f"{result.status}|{result.body}|{result.error}");
    return 0;
}
"""

CA_CONFIG = """[req]
distinguished_name = subject
prompt = no

[subject]
CN = btrc macOS HTTP fixture CA

[ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always

[leaf_origin]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = IP:127.0.0.1, IP:::1, DNS:localhost, DNS:btrc-origin.invalid
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid

[leaf_wrong]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:wrong-host.invalid
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
"""


def _openssl(args: list[str], cwd: Path) -> str:
    tool = shutil.which("openssl")
    if not tool:
        pytest.skip("requires openssl CLI")
    result = subprocess.run([tool, *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout


def _mint_fixtures(directory: Path) -> dict[str, Path]:
    config = directory / "ca.cnf"
    config.write_text(CA_CONFIG, encoding="utf-8")
    common = ["-config", str(config)]

    # Primary CA (ca1) and untrusted CA (ca2)
    for name, cn in (("ca1", "btrc CA 1"), ("ca2", "btrc CA 2")):
        _openssl(
            ["req", "-x509", *common, "-extensions", "ca", "-newkey", "rsa:2048", "-sha256", "-days", "1"]
            + ["-nodes", "-subj", f"/CN={cn}", "-keyout", f"{name}.key", "-out", f"{name}.pem"],
            cwd=directory,
        )

    # Origin leaf signed by ca1 (SAN: 127.0.0.1, localhost, btrc-origin.invalid)
    for stem, ca_name, ext in (
        ("origin", "ca1", "leaf_origin"),
        ("rogue", "ca2", "leaf_origin"),
        ("wrong", "ca1", "leaf_wrong"),
    ):
        _openssl(
            ["req", "-new", *common, "-newkey", "rsa:2048", "-nodes", "-keyout", f"{stem}.key"]
            + ["-subj", "/CN=btrc-origin.invalid", "-out", f"{stem}.csr"],
            cwd=directory,
        )
        _openssl(
            ["x509", "-req", "-in", f"{stem}.csr", "-CA", f"{ca_name}.pem", "-CAkey", f"{ca_name}.key"]
            + ["-CAcreateserial", "-sha256", "-days", "1", "-extfile", str(config), "-extensions", ext]
            + ["-out", f"{stem}.pem"],
            cwd=directory,
        )

    # Real-world bundle variants: UTF-8 explanatory header + OpenSSL TRUSTED CERTIFICATE
    ca1_text = (directory / "ca1.pem").read_text(encoding="utf-8")
    ca1_labeled = directory / "ca1-labeled.pem"
    ca1_labeled.write_text(
        "Autoridad de Certificación — Fixture CA\n=== Header Comment ===\n" + ca1_text,
        encoding="utf-8",
    )
    _openssl(["x509", "-in", "ca1.pem", "-addtrust", "serverAuth", "-out", "ca1-trusted.pem"], cwd=directory)
    _openssl(["x509", "-in", "ca1.pem", "-addreject", "serverAuth", "-out", "ca1-rejected.pem"], cwd=directory)

    # SSL_CERT_DIR fixtures: direct .pem (with non-cert .key beside it), hashed symlink dir, empty dir
    dir_pem = directory / "certdir-pem"
    dir_pem.mkdir()
    shutil.copyfile(directory / "ca1.pem", dir_pem / "root.pem")
    shutil.copyfile(directory / "ca1.key", dir_pem / "ignored.key")

    dir_hash = directory / "certdir-hash"
    dir_hash.mkdir()
    subject_hash = _openssl(["x509", "-in", "ca1.pem", "-noout", "-subject_hash"], cwd=directory).strip()
    os.symlink(directory / "ca1.pem", dir_hash / f"{subject_hash}.0")

    dir_empty = directory / "certdir-empty"
    dir_empty.mkdir()

    return {
        "ca1": directory / "ca1.pem",
        "ca2": directory / "ca2.pem",
        "ca1_labeled": ca1_labeled,
        "ca1_trusted": directory / "ca1-trusted.pem",
        "ca1_rejected": directory / "ca1-rejected.pem",
        "dir_pem": dir_pem,
        "dir_hash": dir_hash,
        "dir_empty": dir_empty,
        "origin_cert": directory / "origin.pem",
        "origin_key": directory / "origin.key",
        "rogue_cert": directory / "rogue.pem",
        "rogue_key": directory / "rogue.key",
        "wrong_cert": directory / "wrong.pem",
        "wrong_key": directory / "wrong.key",
    }


class OriginHandler(http.server.BaseHTTPRequestHandler):
    def _reply(self, status: int, body: bytes, *, location: str | None = None, close_unframed: bool = False) -> None:
        if close_unframed:
            self.protocol_version = "HTTP/1.0"
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length).decode("utf-8", "replace") if length > 0 else ""

    def _record_and_echo(self) -> None:
        payload = self._read_body()
        self.server.seen.append(
            (
                self.command,
                self.path,
                self.headers.get("Host", ""),
                self.headers.get("Authorization", ""),
                self.headers.get("Proxy-Authorization", ""),
                self.headers.get("X-Check", ""),
                payload,
            )
        )
        if self.path == "/redirect":
            self._reply(302, b"", location="/missing")
        elif self.path == "/large":
            self._reply(200, b"1234567890")
        elif self.path == "/slow":
            time.sleep(3)
            self._reply(200, b"late")
        elif self.path == "/close":
            self._reply(200, b"until-eof", close_unframed=True)
        elif self.path == "/chunked":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"5\r\nhello\r\n7\r\n, world\r\n0\r\n\r\n")
        else:
            body = "|".join(
                (
                    self.command,
                    self.path,
                    self.headers.get("Authorization", ""),
                    self.headers.get("Proxy-Authorization", ""),
                    self.headers.get("X-Check", ""),
                    payload,
                )
            ).encode()
            self._reply(200, body)

    def do_GET(self) -> None:
        self._record_and_echo()

    def do_HEAD(self) -> None:
        self._record_and_echo()

    def do_POST(self) -> None:
        self._record_and_echo()

    def do_DELETE(self) -> None:
        self._record_and_echo()

    def log_message(self, format: str, *args: object) -> None:
        pass


class RecordingTLSServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, cert: Path, key: Path) -> None:
        super().__init__(("127.0.0.1", 0), OriginHandler)
        self.daemon_threads = True
        self.seen: list[tuple[str, ...]] = []
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert), str(key))
        self.socket = ctx.wrap_socket(self.socket, server_side=True)


class ConnectAndForwardProxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.forward_seen.append(
            (
                self.path,
                self.headers.get("Host", ""),
                self.headers.get("Proxy-Authorization", ""),
            )
        )
        body = f"fwd|{self.path}|{self.headers.get('Host', '')}|{self.headers.get('Proxy-Authorization', '')}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self) -> None:
        auth = self.headers.get("Proxy-Authorization", "")
        self.server.connect_seen.append((self.path, auth))
        if self.server.expected_auth is not None and auth != self.server.expected_auth:
            self.send_response(407, "Proxy Authentication Required")
            self.send_header("Proxy-Authenticate", 'Basic realm="btrc"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with socket.create_connection(("127.0.0.1", self.server.origin_port), timeout=5) as upstream:
            self.send_response_only(200, "Connection Established")
            self.end_headers()
            peers = (self.connection, upstream)
            while True:
                ready, _, _ = select.select(peers, (), (), 10)
                if not ready:
                    return
                for src in ready:
                    try:
                        chunk = src.recv(65536)
                    except OSError:
                        return
                    if not chunk:
                        return
                    (upstream if src is self.connection else self.connection).sendall(chunk)

    def log_message(self, format: str, *args: object) -> None:
        pass


class ProxyServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, origin_port: int, *, tls_pair: tuple[Path, Path] | None = None) -> None:
        super().__init__(("127.0.0.1", 0), ConnectAndForwardProxy)
        self.daemon_threads = True
        self.origin_port = origin_port
        self.expected_auth: str | None = None
        self.connect_seen: list[tuple[str, str]] = []
        self.forward_seen: list[tuple[str, str, str]] = []
        if tls_pair is not None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(tls_pair[0]), str(tls_pair[1]))
            self.socket = ctx.wrap_socket(self.socket, server_side=True)


def _start_server(server) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


@pytest.mark.skipif(sys.platform != "darwin", reason="tests macOS native Apple HTTP/TLS provider")
def test_macos_native_https_trust_get_body_and_proxies_without_curl(compiler, request, tmp_path, monkeypatch):
    modules = tmp_path / "pkgconfig"
    modules.mkdir()
    monkeypatch.setenv("PKG_CONFIG_LIBDIR", str(modules))
    monkeypatch.delenv("PKG_CONFIG_PATH", raising=False)

    source = tmp_path / "MacOSHttpProbe.btrc"
    source.write_text(PROBE, encoding="utf-8")
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    artifact = NativeCorpusBuild(tmp_path / "probe.c", tmp_path / "probe.json", tuple(frontend))
    subprocess.run(
        [
            *frontend,
            str(source),
            "--strict-imports",
            "-o",
            str(artifact.primary),
            "--emit-link-plan",
            str(artifact.plan),
        ],
        check=True,
        timeout=120,
    )
    cc = os.environ.get("BTRC_NATIVE_PROVIDER_CC") or "clang"
    program = tmp_path / "probe"
    artifact.build(program, cc=cc)
    assert DependencyAudit().binary_problems(program, PackageTarget.parse(None).label) == []

    # Poison curl on PATH plus an empty PATH dir; curl must never be invoked.
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    poison_path = tmp_path / "poison-path"
    poison_path.mkdir()
    curl_marker = tmp_path / "curl-was-called"
    poison_curl = poison_path / "curl"
    poison_curl.write_text(f"#!/bin/sh\necho invoked > '{curl_marker}'\nexit 99\n", encoding="utf-8")
    poison_curl.chmod(0o755)

    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k.lower()
        not in {
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
            "curl_ca_bundle",
            "ssl_cert_file",
            "ssl_cert_dir",
        }
    }
    clean_env["PATH"] = str(empty_path)

    def run(*, use_poison_path: bool = False, **settings: str) -> str:
        env = {**clean_env, **settings}
        if use_poison_path:
            env["PATH"] = str(poison_path)
        completed = subprocess.run([str(program)], env=env, capture_output=True, text=True, timeout=15, check=True)
        assert not curl_marker.exists(), f"curl was unexpectedly invoked for {settings}"
        return completed.stdout.strip()

    fixtures = _mint_fixtures(tmp_path)

    origin = RecordingTLSServer(fixtures["origin_cert"], fixtures["origin_key"])
    rogue = RecordingTLSServer(fixtures["rogue_cert"], fixtures["rogue_key"])
    wrong = RecordingTLSServer(fixtures["wrong_cert"], fixtures["wrong_key"])
    http_proxy = ProxyServer(origin.server_port)
    https_proxy = ProxyServer(origin.server_port, tls_pair=(fixtures["origin_cert"], fixtures["origin_key"]))
    rogue_https_proxy = ProxyServer(origin.server_port, tls_pair=(fixtures["rogue_cert"], fixtures["rogue_key"]))
    wrong_origin_https_proxy = ProxyServer(
        wrong.server_port, tls_pair=(fixtures["origin_cert"], fixtures["origin_key"])
    )
    socks_proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SocksPeer)
    socks_proxy.daemon_threads = True
    socks_proxy.origin = ("127.0.0.1", origin.server_port)
    socks_proxy.observed = []
    socks_proxy.require_auth = False

    servers = [
        origin,
        rogue,
        wrong,
        http_proxy,
        https_proxy,
        rogue_https_proxy,
        wrong_origin_https_proxy,
        socks_proxy,
    ]
    threads = [_start_server(srv) for srv in servers]
    try:
        origin_ip = f"https://127.0.0.1:{origin.server_port}"
        origin_local = f"https://localhost:{origin.server_port}"
        origin_named = f"https://btrc-origin.invalid:{origin.server_port}"
        ca1 = str(fixtures["ca1"])

        # 1. Direct HTTPS with CURL_CA_BUNDLE, SSL_CERT_FILE, SSL_CERT_DIR, and poison curl on PATH
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/ca-bundle",
                CURL_CA_BUNDLE=ca1,
                SSL_CERT_FILE="/no-such-ca",
                SSL_CERT_DIR="/no-such-dir",
            )
            == "200|GET|/ca-bundle|||||"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/labeled",
                SSL_CERT_FILE=str(fixtures["ca1_labeled"]),
            )
            == "200|GET|/labeled|||||"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/trusted-pem",
                SSL_CERT_FILE=str(fixtures["ca1_trusted"]),
            )
            == "200|GET|/trusted-pem|||||"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/rejected-pem",
                SSL_CERT_FILE=str(fixtures["ca1_rejected"]),
            )
            == "0||could not load CA bundle"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/certdir-pem",
                SSL_CERT_DIR=str(fixtures["dir_pem"]),
            )
            == "200|GET|/certdir-pem|||||"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/certdir-hash",
                SSL_CERT_DIR=str(fixtures["dir_hash"]),
            )
            == "200|GET|/certdir-hash|||||"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/certdir-colon",
                SSL_CERT_DIR=f"/no-such-dir:{fixtures['dir_hash']}",
            )
            == "200|GET|/certdir-colon|||||"
        )
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_ip}/certdir-empty",
                SSL_CERT_DIR=str(fixtures["dir_empty"]),
            )
            == "0||could not load CA bundle"
        )
        # Combined SSL_CERT_FILE (ca2) + SSL_CERT_DIR (ca1) succeeds
        assert (
            run(
                TEST_URL=f"{origin_ip}/combined-store",
                SSL_CERT_FILE=str(fixtures["ca2"]),
                SSL_CERT_DIR=str(fixtures["dir_pem"]),
            )
            == "200|GET|/combined-store|||||"
        )
        # Real system bundle (UTF-8 + TRUSTED CERTIFICATE entries) combined with fixture CA
        for system_bundle in (Path("/etc/ssl/certs/ca-certificates.crt"), Path("/etc/ssl/cert.pem")):
            if system_bundle.is_file():
                combined_bundle = tmp_path / f"combined-{system_bundle.name}"
                combined_bundle.write_bytes(system_bundle.read_bytes() + b"\n" + fixtures["ca1"].read_bytes())
                assert (
                    run(
                        use_poison_path=True,
                        TEST_URL=f"{origin_ip}/system-bundle",
                        SSL_CERT_FILE=str(combined_bundle),
                    )
                    == "200|GET|/system-bundle|||||"
                )
        # POST, DELETE with body, headers, URL credentials, 302 no-redirect, size limit, timeout
        assert (
            run(
                TEST_METHOD="POST",
                TEST_URL=f"https://user:p%40ss@localhost:{origin.server_port}/post",
                TEST_HEADER="X-Check: apple",
                TEST_BODY="hello body",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|POST|/post|Basic dXNlcjpwQHNz||apple|hello body|"
        )
        assert (
            run(
                TEST_METHOD="DELETE",
                TEST_URL=f"{origin_ip}/delete",
                TEST_BODY="del-body",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|DELETE|/delete||||del-body|"
        )
        assert run(TEST_URL=f"{origin_local}/redirect", CURL_CA_BUNDLE=ca1) == "302||"
        assert run(TEST_URL=f"{origin_ip}/large", TEST_LIMIT="4", CURL_CA_BUNDLE=ca1) == "0||response body is too large"
        assert run(TEST_URL=f"{origin_ip}/slow", TEST_TIMEOUT="1", CURL_CA_BUNDLE=ca1) == "0||request timed out"

        # 2. GET and HEAD with non-empty request body over HTTPS (Network.framework path)
        assert (
            run(
                use_poison_path=True,
                TEST_METHOD="GET",
                TEST_URL=f"{origin_local}/get-body",
                TEST_HEADER="X-Check: body-get",
                TEST_BODY="query-payload",
                SSL_CERT_DIR=str(fixtures["dir_hash"]),
            )
            == "200|GET|/get-body|||body-get|query-payload|"
        )
        origin.seen.clear()
        assert (
            run(
                use_poison_path=True,
                TEST_METHOD="HEAD",
                TEST_URL=f"{origin_ip}/head-body",
                TEST_HEADER="X-Check: body-head",
                TEST_BODY="head-payload",
                CURL_CA_BUNDLE=ca1,
            )
            == "200||"
        )
        assert origin.seen[-1][0] == "HEAD"
        assert origin.seen[-1][1] == "/head-body"
        assert origin.seen[-1][5] == "body-head"
        assert origin.seen[-1][6] == "head-payload"
        # GET-with-body response framing (close, chunked), size limit, redirect, timeout, fast-fail
        assert (
            run(TEST_METHOD="GET", TEST_URL=f"{origin_ip}/close", TEST_BODY="x", CURL_CA_BUNDLE=ca1) == "200|until-eof|"
        )
        assert (
            run(TEST_METHOD="GET", TEST_URL=f"{origin_ip}/chunked", TEST_BODY="x", CURL_CA_BUNDLE=ca1)
            == "200|hello, world|"
        )
        assert run(TEST_METHOD="GET", TEST_URL=f"{origin_ip}/redirect", TEST_BODY="x", CURL_CA_BUNDLE=ca1) == "302||"
        assert (
            run(TEST_METHOD="GET", TEST_URL=f"{origin_ip}/large", TEST_BODY="x", TEST_LIMIT="4", CURL_CA_BUNDLE=ca1)
            == "0||response body is too large"
        )
        assert (
            run(TEST_METHOD="GET", TEST_URL=f"{origin_ip}/slow", TEST_BODY="x", TEST_TIMEOUT="1", CURL_CA_BUNDLE=ca1)
            == "0||request timed out"
        )
        # Closed port must fail fast (not hang until the 10-second timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unused:
            unused.bind(("127.0.0.1", 0))
            closed_port = unused.getsockname()[1]
        t0 = time.monotonic()
        assert (
            run(
                TEST_METHOD="GET",
                TEST_URL=f"https://127.0.0.1:{closed_port}/closed",
                TEST_BODY="x",
                TEST_TIMEOUT="10",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||HTTPS request failed"
        )
        assert time.monotonic() - t0 < 5.0
        # Stalled TLS handshake (TCP accepts, never replies) must honor deadline
        stall_sock = socket.create_server(("127.0.0.1", 0))
        stall_port = stall_sock.getsockname()[1]
        stall_accepted: list[socket.socket] = []

        def accept_and_stall() -> None:
            try:
                conn, _ = stall_sock.accept()
                stall_accepted.append(conn)
                time.sleep(3)
            except OSError:
                pass

        stall_thread = threading.Thread(target=accept_and_stall, daemon=True)
        stall_thread.start()
        try:
            assert (
                run(
                    TEST_METHOD="GET",
                    TEST_URL=f"https://127.0.0.1:{stall_port}/stall",
                    TEST_BODY="x",
                    TEST_TIMEOUT="1",
                    CURL_CA_BUNDLE=ca1,
                )
                == "0||request timed out"
            )
        finally:
            stall_sock.close()
            for conn in stall_accepted:
                conn.close()
            stall_thread.join(timeout=5)

        # 3. Untrusted CA and hostname mismatch reject BEFORE sending any HTTP bytes
        rogue.seen.clear()
        wrong.seen.clear()
        for method, body in (("GET", ""), ("GET", "secret-body")):
            assert (
                run(
                    TEST_METHOD=method,
                    TEST_URL=f"https://127.0.0.1:{rogue.server_port}/secret",
                    TEST_BODY=body,
                    CURL_CA_BUNDLE=ca1,
                )
                == "0||HTTPS request failed"
            )
            assert (
                run(
                    TEST_METHOD=method,
                    TEST_URL=f"https://127.0.0.1:{wrong.server_port}/secret",
                    TEST_BODY=body,
                    CURL_CA_BUNDLE=ca1,
                )
                == "0||HTTPS request failed"
            )
        assert rogue.seen == [], f"untrusted CA server received HTTP bytes: {rogue.seen}"
        assert wrong.seen == [], f"wrong-host server received HTTP bytes: {wrong.seen}"

        # 4. HTTPS over HTTP CONNECT proxy (plain, Basic auth, caller Proxy-Authorization, path, GET-body, 407)
        http_proxy_addr = f"127.0.0.1:{http_proxy.server_port}"
        http_proxy.expected_auth = None
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_named}/connect-plain",
                https_proxy=f"http://{http_proxy_addr}",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|GET|/connect-plain|||||"
        )
        assert http_proxy.connect_seen[-1] == (f"btrc-origin.invalid:{origin.server_port}", "")

        http_proxy.expected_auth = "Basic dTpzOnArdw=="
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_named}/connect-auth",
                https_proxy=f"http://u%3As:p%2Bw@{http_proxy_addr}",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|GET|/connect-auth|||||"
        )
        assert http_proxy.connect_seen[-1] == (f"btrc-origin.invalid:{origin.server_port}", "Basic dTpzOnArdw==")

        http_proxy.expected_auth = "Bearer caller-proxy-token"
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_named}/connect-header-auth",
                TEST_HEADER="Proxy-Authorization: Bearer caller-proxy-token",
                TEST_HEADER2="X-Check: stripped",
                https_proxy=f"http://{http_proxy_addr}/ignored-path",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|GET|/connect-header-auth|||stripped||"
        )
        assert http_proxy.connect_seen[-1] == (
            f"btrc-origin.invalid:{origin.server_port}",
            "Bearer caller-proxy-token",
        )
        # IPv6 literal CONNECT authority uses RFC 9110 bracketed host:port
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"https://[::1]:{origin.server_port}/connect-ipv6",
                TEST_HEADER="Proxy-Authorization: Bearer caller-proxy-token",
                https_proxy=f"http://{http_proxy_addr}",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|GET|/connect-ipv6|||||"
        )
        assert http_proxy.connect_seen[-1] == (
            f"[::1]:{origin.server_port}",
            "Bearer caller-proxy-token",
        )
        # Failed proxy auth (407)
        origin.seen.clear()
        assert (
            run(
                TEST_URL=f"{origin_named}/connect-407",
                https_proxy=f"http://wrong:creds@{http_proxy_addr}",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||proxy connection failed"
        )
        assert origin.seen == []
        # Unsupported proxy scheme fails closed
        assert (
            run(TEST_URL=f"{origin_named}/bad-proxy", https_proxy="ftp://127.0.0.1:21", CURL_CA_BUNDLE=ca1)
            == "0||invalid proxy URL"
        )

        # 5. HTTPS over HTTPS CONNECT proxy (TLS-in-TLS)
        https_proxy.expected_auth = "Basic dTpzOnArdw=="
        assert (
            run(
                use_poison_path=True,
                TEST_METHOD="GET",
                TEST_URL=f"{origin_named}/tls-in-tls",
                TEST_BODY="nested-body",
                https_proxy=f"https://u%3As:p%2Bw@127.0.0.1:{https_proxy.server_port}",
                SSL_CERT_DIR=str(fixtures["dir_pem"]),
            )
            == "200|GET|/tls-in-tls||||nested-body|"
        )
        assert https_proxy.connect_seen[-1] == (f"btrc-origin.invalid:{origin.server_port}", "Basic dTpzOnArdw==")

        # Untrusted outer HTTPS proxy cert rejected BEFORE sending CONNECT
        rogue_https_proxy.connect_seen.clear()
        assert (
            run(
                TEST_URL=f"{origin_named}/rogue-outer",
                https_proxy=f"https://u:p@127.0.0.1:{rogue_https_proxy.server_port}",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||HTTPS request failed"
        )
        assert rogue_https_proxy.connect_seen == []

        # Valid outer HTTPS proxy + wrong-host inner origin cert rejected BEFORE sending HTTP
        wrong.seen.clear()
        assert (
            run(
                TEST_URL=f"https://btrc-origin.invalid:{wrong.server_port}/bad-inner",
                https_proxy=f"https://127.0.0.1:{wrong_origin_https_proxy.server_port}",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||HTTPS request failed"
        )
        assert wrong.seen == []

        # 6. Plain http:// over https:// forward proxy
        https_proxy.forward_seen.clear()
        assert (
            run(
                use_poison_path=True,
                TEST_URL="http://unresolvable.invalid/plain-over-tls?a=1",
                http_proxy=f"https://user:pass@127.0.0.1:{https_proxy.server_port}",
                CURL_CA_BUNDLE=ca1,
            )
            == "200|fwd|http://unresolvable.invalid/plain-over-tls?a=1|unresolvable.invalid|Basic dXNlcjpwYXNz|"
        )
        rogue_https_proxy.forward_seen.clear()
        assert (
            run(
                TEST_URL="http://unresolvable.invalid/plain-over-rogue",
                http_proxy=f"https://user:pass@127.0.0.1:{rogue_https_proxy.server_port}",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||HTTPS request failed"
        )
        assert rogue_https_proxy.forward_seen == []

        # 7. HTTPS over SOCKS4 / SOCKS4a / SOCKS5 (IPv4 & IPv6) / SOCKS5h
        socks_endpoint = f"127.0.0.1:{socks_proxy.server_address[1]}"
        for scheme, host, auth, version, kind, addr, creds in (
            ("socks4", "127.0.0.1", False, 4, 1, "127.0.0.1", b""),
            ("socks4a", "btrc-origin.invalid", True, 4, 3, "btrc-origin.invalid", b"u:s"),
            ("socks5", "127.0.0.1", True, 5, 1, "127.0.0.1", (b"u:s", b"p+w")),
            ("socks5", "[::1]", True, 5, 4, "::1", (b"u:s", b"p+w")),
            ("socks5h", "btrc-origin.invalid", True, 5, 3, "btrc-origin.invalid", (b"u:s", b"p+w")),
        ):
            socks_proxy.require_auth = auth
            user_part = "u%3As:p%2Bw@" if auth else ""
            assert (
                run(
                    use_poison_path=True,
                    TEST_URL=f"https://user:ori@{host}:{origin.server_port}/socks-https",
                    TEST_HEADER="Proxy-Authorization: Bearer stripped-on-socks",
                    https_proxy=f"{scheme}://{user_part}{socks_endpoint}",
                    CURL_CA_BUNDLE=ca1,
                )
                == "200|GET|/socks-https|Basic dXNlcjpvcmk=||||"
            )
            assert socks_proxy.observed[-1] == (version, kind, addr, origin.server_port, creds)

        socks_proxy.require_auth = True
        assert (
            run(
                use_poison_path=True,
                TEST_URL=f"{origin_named}/socks-no-auth",
                https_proxy=f"socks5h://{socks_endpoint}",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||SOCKS connection failed"
        )

        # Untrusted origin cert over SOCKS5h rejected before any HTTP bytes
        socks_proxy.require_auth = False
        socks_proxy.origin = ("127.0.0.1", rogue.server_port)
        rogue.seen.clear()
        assert (
            run(
                TEST_URL=f"https://btrc-origin.invalid:{rogue.server_port}/socks-rogue",
                https_proxy=f"socks5h://{socks_endpoint}",
                CURL_CA_BUNDLE=ca1,
            )
            == "0||HTTPS request failed"
        )
        assert rogue.seen == []
    finally:
        for srv in servers:
            srv.shutdown()
            srv.server_close()
        for thread in threads:
            thread.join(timeout=5)


@pytest.mark.skipif(sys.platform != "darwin", reason="tests macOS SlowTrust URLSession compatibility")
def test_macos_slow_trust_fixture_builds_and_passes(tmp_path):
    cc = os.environ.get("BTRC_NATIVE_PROVIDER_CC") or "clang"
    exe = tmp_path / "slow-trust"
    subprocess.run(
        [
            cc,
            "-x",
            "objective-c",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{ROOT / 'src/stdlib/HTTP/Apple'}",
            str(ROOT / "src/stdlib/HTTP/Apple/URLSessionTransport.m"),
            str(ROOT / "src/tests/native/http/SlowTrust.m"),
            "-framework",
            "Foundation",
            "-framework",
            "CFNetwork",
            "-framework",
            "Security",
            "-o",
            str(exe),
        ],
        check=True,
        timeout=60,
    )
    completed = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15, check=True)
    assert completed.stdout.strip() == "PASS Apple custom trust deadline"
