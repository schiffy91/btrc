"""Run the public HTTPS fixture against a local TLS endpoint on an Apple test host.

The runner supplies a server key and a localhost-only certificate chain whose
root it trusts in the test keychain. For the iOS simulator, install the root
into the named disposable simulator before starting the fixture.
"""

from __future__ import annotations

import argparse
import http.server
import os
import select
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_build import NativeCorpusBuild
from tools.qualification.dependencies import DependencyAudit
from tools.target_hosts.ios.simhost import AppleEnvironment, IOSSimulatorHost


class ConnectProxy(http.server.BaseHTTPRequestHandler):
    def do_CONNECT(self):
        expected = f"btrc-origin.invalid:{self.server.origin_port}"
        if self.path != expected:
            self.send_error(403)
            return
        with socket.create_connection(("127.0.0.1", self.server.origin_port), timeout=10) as origin:
            self.send_response_only(200)
            self.end_headers()
            self.server.tunneled.set()
            peers = (self.connection, origin)
            while ready := select.select(peers, (), (), 10)[0]:
                for src in ready:
                    chunk = src.recv(65536)
                    if not chunk:
                        return
                    (origin if src is self.connection else self.connection).sendall(chunk)


class Peer(http.server.BaseHTTPRequestHandler):
    def reply(self, status, body, location=None):
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/redirect":
            self.reply(302, b"", "/missing")
        elif self.path == "/large":
            self.reply(200, b"12345")
        elif self.path == "/slow":
            time.sleep(3)
            self.reply(200, b"")
        else:
            self.reply(404, b"missing")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.reply(201, self.headers["X-Check"].encode() + b"/" + body)


def main():
    parser = argparse.ArgumentParser()
    for name in ("target", "compiler", "cert", "key", "root-cert", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--trust-file", help="exercise explicit PEM bundle selection on both native Apple providers")
    args = parser.parse_args()
    ios = args.target == "ios-aarch64-simulator"
    host = IOSSimulatorHost("iphone", name="btrc-https-test") if ios else None
    sdk = "iphonesimulator" if ios else "macosx"
    os.environ["BTRC_NATIVE_TARGET"] = PackageTarget.parse(args.target).row.triple
    os.environ["BTRC_NATIVE_SYSROOT"] = subprocess.check_output(
        ["/usr/bin/xcrun", "--sdk", sdk, "--show-sdk-path"],
        env=AppleEnvironment.variables(),
        text=True,
    ).strip()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Peer) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            if host:
                host.prepare()
                if not args.trust_file:
                    host.command(
                        "keychain",
                        host.device(),
                        "add-root-cert",
                        str(Path(args.root_cert).resolve()),
                        timeout=host.BOOTSTATUS_TIMEOUT_S,
                    )
            for name, frontend in (
                ("reference", [sys.executable, "-m", "src.compiler.python.main"]),
                ("selfhost", [args.compiler]),
            ):
                out = Path(args.output).resolve() / name
                out.mkdir(parents=True, exist_ok=True)
                artifact = NativeCorpusBuild(out / "http.c", out / "http.json", tuple(frontend))
                source = Path(__file__).resolve().with_name("AppleHTTPS.btrc")
                subprocess.run(
                    [
                        *frontend,
                        str(source),
                        "--target",
                        args.target,
                        "--strict-imports",
                        "--emit-link-plan",
                        str(artifact.plan),
                        "-o",
                        str(artifact.primary),
                    ],
                    check=True,
                )
                exe = out / "https"
                if ios:
                    artifact.build(exe)
                else:
                    # The Nix host compiler can be GCC, which cannot build the Foundation provider.
                    artifact.build(
                        exe,
                        cc="/usr/bin/clang",
                        compile_flags=("-isysroot", os.environ["BTRC_NATIVE_SYSROOT"]),
                        link_flags=("-isysroot", os.environ["BTRC_NATIVE_SYSROOT"]),
                    )
                problems = DependencyAudit().binary_problems(exe, args.target)
                assert not problems, problems
                cmd = [str(exe), f"https://localhost:{server.server_port}", f"https://127.0.0.1:{server.server_port}"]
                env = {
                    "PATH": "/no-curl",
                    "no_proxy": "*",
                    "CURL_CA_BUNDLE": "",
                    "SSL_CERT_FILE": "",
                    "SSL_CERT_DIR": "",
                }
                if args.trust_file:
                    # Exercise both environment names. The reference client gets an
                    # invalid SSL_CERT_FILE alongside CURL_CA_BUNDLE to test precedence.
                    trust_file = str(Path(args.trust_file).resolve())
                    if name == "reference":
                        env.update(CURL_CA_BUNDLE=trust_file, SSL_CERT_FILE="/no-such-ca")
                    else:
                        env["SSL_CERT_FILE"] = trust_file
                if host:
                    proc = host.spawn(cmd, env)
                    stdout, stderr = proc.communicate(timeout=90)
                    assert proc.returncode == 0, (stdout, stderr)
                else:
                    # A failed proxy would make these calls fail unless NO_PROXY is respected.
                    env.update(https_proxy="http://127.0.0.1:1", no_proxy="localhost,127.0.0.1")
                    stdout = subprocess.check_output(cmd, env={**os.environ, **env}, timeout=90)
                    if args.trust_file:
                        # A curl executable on PATH must never be invoked even when
                        # CURL_CA_BUNDLE or SSL_CERT_FILE is set: Apple targets use
                        # Security.framework trust anchors directly.
                        curl = out / "curl"
                        marker = out / "curl-invoked"
                        curl.write_text(f"#!/bin/sh\necho invoked > '{marker}'\nexit 99\n")
                        curl.chmod(0o700)
                        direct = subprocess.check_output(
                            cmd,
                            env={**os.environ, **env, "PATH": str(out)},
                            timeout=90,
                        )
                        assert direct.splitlines() == [b"PASS Apple HTTPS"], direct
                        assert not marker.exists(), "macOS HTTPS unexpectedly invoked curl on PATH"
                    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), ConnectProxy) as proxy:
                        proxy.origin_port = server.server_port
                        proxy.tunneled = threading.Event()
                        threading.Thread(target=proxy.serve_forever, daemon=True).start()
                        try:
                            env.update(https_proxy=f"http://127.0.0.1:{proxy.server_port}", no_proxy="")
                            cmd = [str(exe), f"https://btrc-origin.invalid:{server.server_port}", "--proxy-only"]
                            result = subprocess.check_output(cmd, env={**os.environ, **env}, timeout=90)
                            assert result.splitlines() == [b"PASS Apple HTTPS proxy"], result
                            assert proxy.tunneled.is_set()
                        finally:
                            proxy.shutdown()
                assert stdout.splitlines() == [b"PASS Apple HTTPS"], stdout
                print(f"{name} {args.target}: public HTTPS and binary imports passed", flush=True)
        finally:
            if host:
                host.close()
            server.shutdown()


if __name__ == "__main__":
    main()
