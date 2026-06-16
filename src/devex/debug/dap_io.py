"""Debug Adapter Protocol wire framing over a byte stream.

DAP messages are JSON objects prefixed with a ``Content-Length: N\\r\\n\\r\\n``
header (the same framing as LSP). This module is the transport only — it knows
nothing about lldb or message semantics.
"""

from __future__ import annotations

import json
import threading


class DapReader:
    """Reads framed DAP messages from a binary stream."""

    def __init__(self, stream):
        self._stream = stream

    def read(self) -> dict | None:
        """Block until one full message is read; return it, or None at EOF."""
        content_length = None
        # Header block: `Key: Value` lines terminated by a blank line.
        while True:
            line = self._stream.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1].strip())
        if content_length is None:
            return None
        body = self._stream.read(content_length)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))


class DapWriter:
    """Writes framed DAP messages to a binary stream, assigning seq numbers.

    Thread-safe: events emitted from lldb's listener thread and responses from
    the request thread share one writer.
    """

    def __init__(self, stream):
        self._stream = stream
        self._seq = 0
        self._lock = threading.Lock()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def send(self, msg: dict) -> None:
        with self._lock:
            msg["seq"] = self._next_seq()
            data = json.dumps(msg).encode("utf-8")
            header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
            self._stream.write(header)
            self._stream.write(data)
            self._stream.flush()

    def respond(self, request: dict, body: dict | None = None,
                success: bool = True, message: str | None = None) -> None:
        resp = {
            "type": "response",
            "request_seq": request["seq"],
            "success": success,
            "command": request["command"],
        }
        if message is not None:
            resp["message"] = message
        if body is not None:
            resp["body"] = body
        self.send(resp)

    def event(self, event: str, body: dict | None = None) -> None:
        msg = {"type": "event", "event": event}
        if body is not None:
            msg["body"] = body
        self.send(msg)
