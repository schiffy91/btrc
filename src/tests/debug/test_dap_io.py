"""Unit tests for bounded, exact DAP wire framing."""

import io
import json

import pytest

from src.devex.debug.protocol.transport import DapProtocolError, DapReader, DapWriter


def _frame(message):
    body = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class ShortReadStream(io.BytesIO):
    """A pipe-like stream that returns at most three body bytes per read."""

    def read(self, size=-1):
        if size < 0:
            size = 3
        return super().read(min(size, 3))


class ShortWriteStream(io.BytesIO):
    def write(self, data):
        return super().write(data[:3])


def test_reader_collects_short_reads_until_the_body_is_complete():
    message = {"seq": 1, "type": "request", "command": "threads"}
    assert DapReader(ShortReadStream(_frame(message))).read() == message


def test_reader_distinguishes_clean_eof_from_a_truncated_body():
    assert DapReader(io.BytesIO()).read() is None
    with pytest.raises(DapProtocolError, match="unexpected EOF in DAP body"):
        DapReader(io.BytesIO(b"Content-Length: 10\r\n\r\n{}")).read()


@pytest.mark.parametrize(
    "wire",
    [
        b"X-Test: value\r\n\r\n{}",
        b"Content-Length: -1\r\n\r\n",
        b"Content-Length: nope\r\n\r\n",
        b"Content-Length: 0\r\n\r\n",
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"Content-Length: 2\n\n{}",
    ],
)
def test_reader_rejects_malformed_or_ambiguous_headers(wire):
    with pytest.raises(DapProtocolError):
        DapReader(io.BytesIO(wire)).read()


def test_reader_enforces_a_configurable_body_limit_before_reading():
    wire = b"Content-Length: 5\r\n\r\n{}"
    with pytest.raises(DapProtocolError, match="exceeds 4 bytes"):
        DapReader(io.BytesIO(wire), max_content_length=4).read()


@pytest.mark.parametrize("body", [b"{", b"[]", b"\xff"])
def test_reader_rejects_invalid_or_non_object_json(body):
    wire = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    with pytest.raises(DapProtocolError):
        DapReader(io.BytesIO(wire)).read()


def test_reader_rejects_nonstandard_nonfinite_json_numbers():
    body = b'{"value": NaN}'
    wire = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    with pytest.raises(DapProtocolError, match="invalid DAP JSON body"):
        DapReader(io.BytesIO(wire)).read()


def test_reader_rejects_excessively_nested_json_as_protocol_error():
    # Python 3.14's iterative decoder accepts substantially deeper arrays
    # than older releases; this remains well below DAP's 16 MiB body limit.
    depth = 500_000
    body = b'{"value":' + (b"[" * depth) + b"0" + (b"]" * depth) + b"}"
    wire = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body

    with pytest.raises(DapProtocolError, match="invalid DAP JSON body"):
        DapReader(io.BytesIO(wire)).read()


def test_writer_uses_utf8_byte_length_without_mutating_the_message():
    stream = io.BytesIO()
    message = {"type": "event", "event": "output", "body": {"output": "λ"}}
    DapWriter(stream).send(message)

    assert "seq" not in message
    stream.seek(0)
    decoded = DapReader(stream).read()
    assert decoded["seq"] == 1
    assert decoded["body"]["output"] == "λ"


def test_writer_retries_short_writes_until_the_frame_is_complete():
    stream = ShortWriteStream()
    DapWriter(stream).event("ready", {"text": "ok"})
    stream.seek(0)
    assert DapReader(stream).read()["event"] == "ready"
