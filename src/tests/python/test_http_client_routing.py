"""Exercise HTTPClient with a local forward proxy, bypass rules and a stalled resolver."""

import http.server
import os
import subprocess
import sys
import threading

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_build import NativeCorpusBuild
from tools.qualification.dependencies import DependencyAudit

PROBE = """import Library.HTTP.HTTPClient;
import Library.Platform;
import Library.Vector;

int main() {
    Vector<string> fields = [];
    HTTPClientResponse result = HTTPClient().timeout(1).get(Environment.get("TEST_URL", ""), fields);
    print(f"{result.status}|{result.body}|{result.error}");
    return 0;
}
"""

# Linked into a second copy of the same public client. If the calling thread
# ever waits for this resolver, the outer test times out.
SLOW_RESOLVER = """#define _POSIX_C_SOURCE 200809L
#include <netdb.h>
#include <unistd.h>

int getaddrinfo(const char *name, const char *service, const struct addrinfo *hints, struct addrinfo **found) {
    (void)name;
    (void)service;
    (void)hints;
    *found = NULL;
    sleep(30);
    return EAI_AGAIN;
}
"""


class RoutingPeer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        fields = (self.path, self.headers["Host"], self.headers.get("Proxy-Authorization", ""))
        body = "|".join(fields).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def test_public_http_proxy_bypass_and_resolver_deadline(compiler, request, tmp_path):
    if sys.platform not in {"linux", "darwin"}:
        pytest.skip("requires the desktop BSD socket HTTP provider")
    source = tmp_path / "RouteProbe.btrc"
    source.write_text(PROBE)
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    artifact = NativeCorpusBuild(tmp_path / "route.c", tmp_path / "route.json", tuple(frontend))
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
    program = tmp_path / "route"
    artifact.build(program)
    assert DependencyAudit().binary_problems(program, PackageTarget.parse(None).label) == []
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment = {
        k: v for k, v in os.environ.items() if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    environment["PATH"] = str(empty_path)

    def run(executable, **settings):
        result = subprocess.run(
            [str(executable)], env={**environment, **settings}, capture_output=True, text=True, timeout=6, check=True
        )
        return result.stdout.strip()

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), RoutingPeer) as peer:
        serving = threading.Thread(target=peer.serve_forever)
        serving.start()
        try:
            endpoint = f"127.0.0.1:{peer.server_port}"
            proxy = f"http://user:pass@{endpoint}"
            target = "http://unresolvable.invalid/test?q=1"
            assert run(program, TEST_URL=target, http_proxy=proxy) == (
                f"200|{target}|unresolvable.invalid|Basic dXNlcjpwYXNz|"
            )
            for host, rule in (("127.0.0.1", "127.0.0.0/8"), ("localhost", ".localhost"), ("localhost", "*")):
                authority = f"{host}:{peer.server_port}"
                assert run(program, TEST_URL=f"http://{authority}/direct", all_proxy=proxy, NO_PROXY=rule) == (
                    f"200|/direct|{authority}||"
                )
            assert run(program, TEST_URL=f"http://{endpoint}/direct", HTTP_PROXY=proxy) == f"200|/direct|{endpoint}||"
        finally:
            peer.shutdown()
            serving.join()

    slow_source = tmp_path / "slow.c"
    slow_object = tmp_path / "slow.o"
    slow_source.write_text(SLOW_RESOLVER)
    subprocess.run(["cc", "-std=c11", "-c", str(slow_source), "-o", str(slow_object)], check=True, timeout=60)
    slow_client = tmp_path / "slow"
    artifact.build(slow_client, link_flags=[str(slow_object)])
    assert run(slow_client, TEST_URL="http://slow.invalid/") == "0||request timed out"
