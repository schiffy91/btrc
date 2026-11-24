"""Linux's public HTTPS candidate over the same SOCKS wire client as Android."""

import ipaddress
import os
import socketserver
import subprocess
import threading
import time

from src.tests.native.http.socks_peer import SocksPeer
from src.tests.python import test_linux_tls_http as https

client = https.client
compiled_clients = https.compiled_clients
local_server = https.local_server
pytestmark = https.pytestmark


def test_https_over_socks(client, local_server, tmp_path):
    directory, port, seen = local_server
    environment = {key: value for key, value in os.environ.items() if not key.lower().endswith("_proxy")}
    environment.update(CURL_CA_BUNDLE=str(directory / "root.pem"), SSL_CERT_FILE="", SSL_CERT_DIR="", PATH="/no-curl")

    class Proxy(SocksPeer):
        def handle(self):
            if self.server.stall:
                time.sleep(3)
                return
            super().handle()

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Proxy) as proxy:
        proxy.daemon_threads = True
        proxy.observed = []
        proxy.origin = ("127.0.0.1", port)
        proxy.stall = False
        serving = threading.Thread(target=proxy.serve_forever, daemon=True)
        serving.start()

        def probe(scheme, host, mode, *, creds="", error="", **settings):
            proxy_url = f"{scheme}://{creds}127.0.0.1:{proxy.server_address[1]}"
            result = subprocess.run(
                [client, f"https://user:ori@{host}:{port}/credentials", mode],
                env=environment | {"https_proxy": proxy_url} | settings,
                capture_output=True,
                timeout=6,
                text=True,
            )
            assert (result.returncode, result.stdout.strip(), result.stderr) == (0, error, "")

        try:
            for scheme, host, auth, expected_address in (
                ("socks4", "localhost", False, "127.0.0.1"),
                ("socks4a", "proxy-only.invalid", True, "proxy-only.invalid"),
                ("socks5", "localhost", False, None),
                ("socks5h", "proxy-only.invalid", True, "proxy-only.invalid"),
            ):
                proxy.require_auth = auth
                count = len(proxy.observed)
                before = len(seen)
                probe(scheme, host, "explicit", creds="u%3As:p%2Bw@" if auth else "")
                assert proxy.observed[count:] and len(proxy.observed) == count + 1
                version, kind, address, target_port, credentials = proxy.observed[-1]
                assert target_port == port and seen[before:] == ["/credentials"]
                assert version == (4 if scheme.startswith("socks4") else 5)
                assert credentials == (
                    (b"u:s" if auth else b"") if version == 4 else ((b"u:s", b"p+w") if auth else None)
                )
                if expected_address is None:
                    assert kind in (1, 4) and ipaddress.ip_address(address).is_loopback
                else:
                    assert address == expected_address and kind == (3 if host.endswith(".invalid") else 1)
            # SOCKS4 has no GSSAPI mode to defer to an installed curl.
            tripwire = tmp_path / "curl"
            tripwire.write_text("#!/bin/sh\nexit 42\n")
            tripwire.chmod(0o755)
            proxy.require_auth = False
            probe("socks4a", "proxy-only.invalid", "ok", PATH=str(tmp_path))
            assert proxy.observed[-1][:4] == (4, 3, "proxy-only.invalid", port)
            before = len(seen)
            probe("socks4a", "proxy-only.invalid", "legacy", PATH=str(tmp_path), error="curl failed (exit 42)")
            probe("socks5h", "[::1]", "name", error="TLS handshake failed")
            assert proxy.observed[-1][:4] == (5, 4, "::1", port)
            probe("socks4a", "wrong.invalid", "name", error="TLS handshake failed")
            assert proxy.observed[-1][:4] == (4, 3, "wrong.invalid", port)
            assert len(seen) == before
            count = len(proxy.observed)
            proxy.require_auth = True
            probe("socks5h", "proxy-only.invalid", "denied", creds="u:wrong@", error="SOCKS negotiation failed")
            probe("socks5h", "proxy-only.invalid", "denied", error="SOCKS negotiation failed")
            probe("socks4", "[::1]", "unsupported", error="SOCKS negotiation failed")
            assert len(proxy.observed) == count and len(seen) == before
            probe("socks5h", "localhost", "direct", NO_PROXY="localhost")
            assert len(proxy.observed) == count and len(seen) == before + 1
            proxy.stall = True
            start = time.monotonic()
            probe("socks5", "localhost", "stalled", error="request timed out")
            assert 1.5 <= time.monotonic() - start < 3.5
            assert len(proxy.observed) == count and len(seen) == before + 1
        finally:
            proxy.shutdown()
            serving.join()
