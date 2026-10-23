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
    main = tmp_path / "Main.btrc"
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


def test_target_changes_reanalyze_open_buffers_over_stdio(tmp_path):
    """Exercise real protocol registration and worker-to-client publication."""
    path = tmp_path / "Target.btrc"
    source = "#if _WIN32\nint main() { return missingOnWindows; }\n#else\nint main() { return 0; }\n#endif\n"
    path.write_text(source)
    uri = path.as_uri()
    client = LspClient(env={"BTRC_LSP_DEBOUNCE": "0"})
    try:
        init_id = client.send(
            "initialize",
            {
                "processId": None,
                "rootUri": tmp_path.as_uri(),
                "capabilities": {},
                "initializationOptions": {"target": "linux-x86_64"},
            },
        )
        response = client.wait_response(init_id)
        assert "error" not in response, response
        client.send("initialized", {}, request=False)
        client.send(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "btrc", "version": 1, "text": source}},
            request=False,
        )
        initial = client.wait_notification("textDocument/publishDiagnostics")
        assert initial["params"]["uri"] == uri
        assert initial["params"]["diagnostics"] == []

        for target, missing in (("windows-x86_64", True), ("linux-x86_64", False)):
            client.send(
                "workspace/didChangeConfiguration",
                {"settings": {"btrc": {"target": target}}},
                request=False,
            )
            publish = client.wait_notification("textDocument/publishDiagnostics")
            assert publish["params"]["uri"] == uri
            diagnostics = publish["params"]["diagnostics"]
            if missing:
                assert len(diagnostics) == 1, diagnostics
                assert "missingOnWindows" in diagnostics[0]["message"]
            else:
                assert diagnostics == []
        shutdown_id = client.send("shutdown", {})
        client.wait_response(shutdown_id)
        client.send("exit", {}, request=False)
    finally:
        client.close()


@pytest.mark.parametrize(
    ("keyword", "body", "kind"), [("struct", "int x;", 23), ("union", "int x;", 23), ("enum", "READY", 10)]
)
def test_identity_typedef_symbols_and_definition_over_stdio(tmp_path, keyword, body, kind):
    path = tmp_path / "Record.btrc"
    source = (
        f"typedef {keyword} Record Record;\n"
        f"{keyword} Record {{ {body} }};\n"
        "typedef Record Alias;\n"
        "int main() { Record* value = null; return value == null ? 0 : 1; }\n"
    )
    path.write_text(source)
    uri = path.as_uri()
    client = LspClient(env={"BTRC_LSP_DEBOUNCE": "0"})
    try:
        initialize = client.send("initialize", {"processId": None, "rootUri": tmp_path.as_uri(), "capabilities": {}})
        assert "error" not in client.wait_response(initialize)
        client.send("initialized", {}, request=False)
        client.send(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "btrc", "version": 1, "text": source}},
            request=False,
        )
        published = client.wait_notification("textDocument/publishDiagnostics")
        assert published["params"]["uri"] == uri
        assert published["params"]["diagnostics"] == []
        document = client.wait_response(client.send("textDocument/documentSymbol", {"textDocument": {"uri": uri}}))
        records = [symbol for symbol in document["result"] if symbol["name"] == "Record"]
        assert len(records) == 1
        assert records[0]["kind"] == kind
        assert records[0]["selectionRange"]["start"] == {"line": 1, "character": len(keyword) + 1}
        assert any(symbol["name"] == "Alias" for symbol in document["result"])
        workspace = client.wait_response(client.send("workspace/symbol", {"query": "Record"}))
        records = [
            symbol for symbol in workspace["result"] if symbol["name"] == "Record" and symbol["location"]["uri"] == uri
        ]
        assert len(records) == 1
        assert records[0]["kind"] == kind
        assert records[0]["location"]["range"]["start"]["line"] == 1
        definition = client.wait_response(
            client.send(
                "textDocument/definition",
                {"textDocument": {"uri": uri}, "position": {"line": 3, "character": 14}},
            )
        )
        assert definition["result"]["uri"] == uri
        assert definition["result"]["range"]["start"] == {"line": 1, "character": len(keyword) + 1}
        shutdown = client.send("shutdown", {})
        client.wait_response(shutdown)
        client.send("exit", {}, request=False)
    finally:
        client.close()


@pytest.mark.parametrize(
    ("declaration", "access"),
    [
        ("Record value;", "value.count"),
        ("Record value; Record* pointer = &value;", "pointer->count"),
        ("Alias value;", "value.count"),
        ("Holder value;", "value.record.count"),
        ("Callable value;", "value.callback()->count"),
        ("AliasedCallable value;", "value.callback()->count"),
    ],
)
@pytest.mark.parametrize("imported", [False, True])
def test_anonymous_member_symbols_and_definition_over_stdio(tmp_path, declaration, access, imported):
    path = tmp_path / "Record.btrc"
    source = (
        "struct Record {\n"
        "    int kind;\n"
        "    union {\n"
        "        int count;\n"
        "        float real;\n"
        "    };\n"
        "};\n"
        "typedef Record Alias;\n"
        "struct Holder { Record record; };\n"
        "struct Callable { union { CFunction<Record*> callback; void* pointer; }; };\n"
        "typedef CFunction<Record*> RecordCallback;\n"
        "struct AliasedCallable { union { RecordCallback callback; void* pointer; }; };\n"
        f"int main() {{ {declaration} {access} = 7; return {access}; }}\n"
    )
    definition_path = path
    access_line = 12
    if imported:
        definition_path = tmp_path / "Records.btrc"
        definition_path.write_text("\n".join(source.splitlines()[:12]) + "\n")
        source = "import ./Records.btrc;\n" + source.splitlines()[12] + "\n"
        access_line = 1
    path.write_text(source)
    uri = path.as_uri()
    client = LspClient(env={"BTRC_LSP_DEBOUNCE": "0"})
    try:
        initialize = client.send("initialize", {"processId": None, "rootUri": tmp_path.as_uri(), "capabilities": {}})
        assert "error" not in client.wait_response(initialize)
        client.send("initialized", {}, request=False)
        client.send(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": "btrc", "version": 1, "text": source}},
            request=False,
        )
        published = client.wait_notification("textDocument/publishDiagnostics")
        assert published["params"]["uri"] == uri
        assert published["params"]["diagnostics"] == []
        document = client.wait_response(client.send("textDocument/documentSymbol", {"textDocument": {"uri": uri}}))
        if not imported:
            record = next(symbol for symbol in document["result"] if symbol["name"] == "Record")
            assert [symbol["name"] for symbol in record["children"]] == ["kind", "count", "real"]
            field = next(symbol for symbol in record["children"] if symbol["name"] == "count")
            assert field["selectionRange"]["start"] == {"line": 3, "character": 12}
        definition = client.wait_response(
            client.send(
                "textDocument/definition",
                {
                    "textDocument": {"uri": uri},
                    "position": {
                        "line": access_line,
                        "character": source.splitlines()[access_line].rindex("count") + 1,
                    },
                },
            )
        )
        assert definition["result"]["uri"] == definition_path.as_uri()
        assert definition["result"]["range"]["start"] == {"line": 3, "character": 12}
        shutdown = client.send("shutdown", {})
        client.wait_response(shutdown)
        client.send("exit", {}, request=False)
    finally:
        client.close()
