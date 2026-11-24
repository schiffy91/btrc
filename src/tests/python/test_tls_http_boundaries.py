"""Exercise large and fragmented HTTPS transfers and negotiate against real obsolete profiles."""

import os
import socket
import ssl
import subprocess
import sys
import threading
import warnings

import pytest

from src.tests.python.test_linux_tls_http import client as client
from src.tests.python.test_linux_tls_http import compiled_clients as compiled_clients
from src.tests.python.test_linux_tls_http import local_server as local_server

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux TLS provider")


def context(version, server):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    # Python warns when configuring a TLS 1.1 endpoint, which is the point
    # of this obsolete-peer conformance test.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx.minimum_version = ctx.maximum_version = version
    return ctx


def run_client(binary, port, root, mode):
    result = subprocess.run(
        [binary, f"https://localhost:{port}/{mode}", mode],
        env=os.environ
        | {
            "CURL_CA_BUNDLE": str(root / "root.pem"),
            "SSL_CERT_FILE": "",
            "SSL_CERT_DIR": "",
            "PATH": "/no-curl",
            "NO_PROXY": "*",
        },
        capture_output=True,
        text=True,
        timeout=40,
    )
    expected = {"bulk": "", "bulk-limit": "response body is too large", "obsolete": "TLS handshake failed"}[mode]
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, expected, "")


def exchange(server, client):
    failures = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(10)

        def serve():
            try:
                with listener.accept()[0] as sock:
                    sock.settimeout(35)
                    server(sock)
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            client(listener.getsockname()[1])
        finally:
            thread.join(36)
        assert not thread.is_alive() and not failures, failures


def bulk_transfer(binary, root, version, mode):
    ctx = context(version, True)
    ctx.load_cert_chain(root / "server.pem", root / "server.key")
    ctx.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256")
    request_body = b"0123456789abcdef" * 16384 + b"REQ"
    response_body = b"fedcba9876543210" * 32768 + b"REPLY"
    headers = []

    def observe(conn, direction, tls_version, kind, msg, data):
        if int(kind) == 256 and data[0] == 23:
            headers.append((direction, int.from_bytes(data[3:5], "big")))

    ctx._msg_callback = observe

    def serve(sock):
        with ctx.wrap_socket(sock, server_side=True) as tls:
            raw = bytearray()
            while b"\r\n\r\n" not in raw:
                part = tls.recv(16384)
                assert part
                raw.extend(part)
            head, body = bytes(raw).split(b"\r\n\r\n", 1)
            assert head.startswith(f"POST /{mode} HTTP/1.1\r\n".encode())
            assert b"X-Test: bulk" in head and f"Content-Length: {len(request_body)}".encode() in head
            body = bytearray(body)
            while len(body) < len(request_body):
                part = tls.recv(16384)
                assert part
                body.extend(part)
            assert body == request_body
            # Use close-delimited HTTP so the limit case must actually
            # consume records and detect the boundary in the response body.
            tls.sendall(b"HTTP/1.1 201 Created\r\nConnection: close\r\n\r\n")
            for value in response_body[:257]:
                tls.sendall(bytes([value]))
            if mode == "bulk-limit":
                tls.sendall(response_body[257:65537])
                return
            tls.sendall(response_body[257:])
            tls.unwrap().close()

    exchange(serve, lambda port: run_client(binary, port, root, mode))
    # Each SSL_write above generated a one-byte application record. The
    # TLS 1.2 suite additionally carries an explicit eight-byte nonce.
    tiny_size = 25 if version == ssl.TLSVersion.TLSv1_2 else 18
    assert headers.count(("write", tiny_size)) >= 257
    assert sum(d == "read" for d, _ in headers) >= 17


def refuse_obsolete(binary, root, version):
    cipher = "ECDHE-ECDSA-AES128-SHA" if version == ssl.TLSVersion.TLSv1_1 else "ECDHE-ECDSA-AES128-SHA256"
    server = context(version, True)
    server.set_ciphers(cipher + ":@SECLEVEL=0")
    server.load_cert_chain(root / "server.pem", root / "server.key")
    reference = context(version, False)
    reference.set_ciphers(cipher + ":@SECLEVEL=0")
    reference.load_verify_locations(cafile=root / "root.pem")

    # Prove the endpoint genuinely negotiates this obsolete profile.
    def accept_control(sock):
        with server.wrap_socket(sock, server_side=True) as tls:
            assert tls.cipher()[0] == cipher
            assert tls.recv(1) == b"x"
            tls.sendall(b"y")

    def send_control(port):
        with (
            socket.create_connection(("127.0.0.1", port), timeout=6) as sock,
            reference.wrap_socket(sock, server_hostname="localhost") as tls,
        ):
            tls.sendall(b"x")
            assert tls.recv(1) == b"y"

    exchange(accept_control, send_control)

    alerts = []
    client_records = []

    def observe(conn, direction, tls_version, kind, msg, data):
        if direction == "write" and int(kind) == 21:
            alerts.append(bytes(data))
        if direction == "read" and int(kind) == 256:
            client_records.append(data[0])

    server._msg_callback = observe

    def refuse(sock):
        with pytest.raises(ssl.SSLError):
            server.wrap_socket(sock, server_side=True)

    exchange(refuse, lambda port: run_client(binary, port, root, "obsolete"))
    expected = 70 if version == ssl.TLSVersion.TLSv1_1 else 40
    assert alerts == [bytes([2, expected])]
    assert client_records and all(kind == 22 for kind in client_records)


def test_http_tls_boundaries(client, request, local_server):
    root, _, _ = local_server
    version = request.node.callspec.params["local_server"]
    for mode in ("bulk", "bulk-limit"):
        bulk_transfer(client, root, version, mode)
    obsolete = ssl.TLSVersion.TLSv1_1 if version == ssl.TLSVersion.TLSv1_2 else ssl.TLSVersion.TLSv1_2
    refuse_obsolete(client, root, obsolete)
