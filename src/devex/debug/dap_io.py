"""Debug Adapter Protocol wire framing over a byte stream.

DAP messages are JSON objects prefixed with a ``Content-Length: N\\r\\n\\r\\n``
header (the same framing as LSP). This module is the transport only — it knows
nothing about lldb or message semantics.
"""

from __future__ import annotations

import json
import threading

MAX_HEADER_BYTES = 8 * 1024
MAX_CONTENT_LENGTH = 16 * 1024 * 1024


class DapProtocolError(ValueError):
    """The byte stream cannot be decoded as a valid DAP frame."""


class DapReader:
    """Reads framed DAP messages from a binary stream."""

    def __init__(self, stream, *, max_content_length=MAX_CONTENT_LENGTH):
        self._stream = stream
        self._max_content_length = max_content_length

    def read(self) -> dict | None:
        """Block until one full message is read; return it, or None at EOF."""
        content_length = None
        header_bytes = 0
        # Header block: `Key: Value` lines terminated by a blank line.
        while True:
            remaining = MAX_HEADER_BYTES - header_bytes
            line = self._stream.readline(remaining + 1)
            if not line:
                if header_bytes == 0:
                    return None
                raise DapProtocolError("unexpected EOF in DAP headers")
            header_bytes += len(line)
            if header_bytes > MAX_HEADER_BYTES:
                raise DapProtocolError("DAP headers exceed 8192 bytes")
            if not line.endswith(b"\r\n"):
                raise DapProtocolError("DAP headers must use CRLF line endings")
            line = line[:-2]
            if not line:
                break
            name, separator, value = line.partition(b":")
            if not separator:
                raise DapProtocolError("malformed DAP header")
            if name.strip().lower() != b"content-length":
                continue
            if content_length is not None:
                raise DapProtocolError("duplicate Content-Length header")
            value = value.strip()
            if not value.isdigit():
                raise DapProtocolError("Content-Length must be a decimal integer")
            content_length = int(value)
        if content_length is None:
            raise DapProtocolError("missing Content-Length header")
        if content_length <= 0:
            raise DapProtocolError("Content-Length must be positive")
        if content_length > self._max_content_length:
            raise DapProtocolError(f"Content-Length exceeds {self._max_content_length} bytes")

        body = self._read_exact(content_length)
        try:
            message = json.loads(
                body.decode("utf-8"),
                parse_constant=lambda value: _reject_json_constant(value),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise DapProtocolError(f"invalid DAP JSON body: {error}") from error
        if not isinstance(message, dict):
            raise DapProtocolError("DAP message body must be a JSON object")
        return message

    def _read_exact(self, length: int) -> bytes:
        chunks = []
        remaining = length
        while remaining:
            chunk = self._stream.read(remaining)
            if not chunk:
                received = length - remaining
                raise DapProtocolError(f"unexpected EOF in DAP body ({received}/{length} bytes)")
            if len(chunk) > remaining:
                raise DapProtocolError("DAP stream returned more bytes than requested")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


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
            payload = {**msg, "seq": self._next_seq()}
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
            header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
            self._write_all(header)
            self._write_all(data)
            self._stream.flush()

    def _write_all(self, data: bytes) -> None:
        written = 0
        while written < len(data):
            count = self._stream.write(data[written:])
            if not isinstance(count, int) or count <= 0:
                raise OSError("DAP stream did not accept output bytes")
            written += count

    def respond(
        self, request: dict, body: dict | None = None, success: bool = True, message: str | None = None
    ) -> None:
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


def _reject_json_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")
