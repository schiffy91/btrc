"""End-to-end protocol test: drive the real server over stdio.

Simulates an editor session — open, typing burst, hover/definition/semantic
tokens — against a real server subprocess. This is the test that catches
event-loop blocking, thread-unsafe sends, and position-space regressions.
"""

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVER = PROJECT_ROOT / "src" / "devex" / "lsp" / "__main__.py"


class LspClient:
    def __init__(self, env=None):
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, **(env or {})},
        )
        self._id = 0
        self._messages: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        stream = self.proc.stdout
        while True:
            headers = {}
            line = stream.readline()
            if not line:
                return
            while line and line.strip():
                key, _, value = line.decode().partition(":")
                headers[key.strip().lower()] = value.strip()
                line = stream.readline()
            length = int(headers.get("content-length", 0))
            if not length:
                continue
            body = stream.read(length)
            try:
                self._messages.put(json.loads(body))
            except json.JSONDecodeError:  # corrupt frame = thread-unsafe writes
                self._messages.put({"__corrupt__": body[:100].decode(errors="replace")})

    def send(self, method, params, request=True):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if request:
            self._id += 1
            msg["id"] = self._id
        data = json.dumps(msg).encode()
        frame = b"Content-Length: %d\r\n\r\n%b" % (len(data), data)
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()
        return msg.get("id")

    def wait_response(self, msg_id, timeout=30.0):
        return self._wait(lambda m: m.get("id") == msg_id, timeout, f"response {msg_id}")

    def wait_notification(self, method, timeout=30.0):
        return self._wait(lambda m: m.get("method") == method, timeout, method)

    def _wait(self, predicate, timeout, what):
        deadline = time.time() + timeout
        stash = []
        while time.time() < deadline:
            try:
                msg = self._messages.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            assert "__corrupt__" not in msg, f"corrupt frame: {msg}"
            if predicate(msg):
                for m in stash:
                    self._messages.put(m)
                return msg
            stash.append(msg)
        raise AssertionError(f"timed out waiting for {what}")

    def close(self):
        with contextlib.suppress(Exception):
            self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)


@pytest.fixture()
def project(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text(
        "class Helper {\n"
        "    public int v;\n"
        "    public Helper(int v) { self.v = v; }\n"
        "    public int get() { return self.v; }\n"
        "}\n"
    )
    main = tmp_path / "main.btrc"
    main.write_text("import ./lib.btrc;\nint main() {\n    Helper h = new Helper(1);\n    return h.get();\n}\n")
    return main


def test_editor_session(project):
    client = LspClient(env={"BTRC_LSP_DEBOUNCE": "0.05"})
    uri = project.as_uri()
    text = project.read_text()
    try:
        init_id = client.send(
            "initialize",
            {"processId": None, "rootUri": None, "capabilities": {}},
        )
        client.wait_response(init_id)
        client.send("initialized", {}, request=False)

        client.send(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "btrc",
                    "version": 1,
                    "text": text,
                }
            },
            request=False,
        )

        # First analysis completes and publishes (cold start: stdlib parse).
        publish = client.wait_notification("textDocument/publishDiagnostics")
        assert publish["params"]["uri"] == uri
        assert publish["params"]["diagnostics"] == []

        # Typing burst: 10 rapid full-document changes.
        for i in range(10):
            client.send(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": 2 + i},
                    "contentChanges": [{"text": text + ("\n" * i)}],
                },
                request=False,
            )

        # Requests issued immediately after the burst must answer quickly
        # from the last snapshot — this used to take many seconds.
        start = time.time()
        hover_id = client.send(
            "textDocument/hover",
            {"textDocument": {"uri": uri}, "position": {"line": 2, "character": 6}},
        )
        hover = client.wait_response(hover_id)
        hover_latency = time.time() - start
        assert hover.get("result"), "hover on 'Helper' returned nothing"
        assert "Helper" in json.dumps(hover["result"])
        assert hover_latency < 5.0, f"hover took {hover_latency:.1f}s during burst"

        def_id = client.send(
            "textDocument/definition",
            {"textDocument": {"uri": uri}, "position": {"line": 2, "character": 6}},
        )
        definition = client.wait_response(def_id)
        assert definition.get("result"), "definition returned nothing"
        assert definition["result"]["uri"].endswith("lib.btrc")
        assert definition["result"]["range"]["start"]["line"] == 0

        tokens_id = client.send(
            "textDocument/semanticTokens/full",
            {"textDocument": {"uri": uri}},
        )
        tokens = client.wait_response(tokens_id)
        assert tokens.get("result") and tokens["result"]["data"]

        shutdown_id = client.send("shutdown", {})
        client.wait_response(shutdown_id)
        client.send("exit", {}, request=False)
    finally:
        client.close()
