"""A clocked Pulse native v13 peer for Linux provider tests without an audio service."""

from __future__ import annotations

import os
import select
import socket
import socketserver
import struct
import threading
import time
from pathlib import Path

CONTROL = 0xFFFFFFFF
CHANNEL = 3
RATE = 48000


def u32(value: int) -> bytes:
    return b"L" + struct.pack(">I", value)


def string(value: str) -> bytes:
    return b"t" + value.encode() + b"\0"


def spec(channels: int, rate: int) -> bytes:
    return b"a" + bytes([5, channels]) + struct.pack(">I", rate)


def channel_map(channels: int) -> bytes:
    return b"m" + bytes([channels]) + bytes(range(1, channels + 1))


def volume(channels: int) -> bytes:
    return b"v" + bytes([channels]) + struct.pack(">I", 65536) * channels


def device(name: str, jack: bool = False) -> bytes:
    properties = b"P" + (string("device.api") + u32(5) + b"x\0\0\0\5jack\0" if jack else b"") + b"N"
    return (
        u32(1)
        + string(name)
        + string("Test audio")
        + spec(2, RATE)
        + channel_map(2)
        + u32(1)
        + volume(2)
        + b"0"
        + u32(1)
        + string("monitor")
        + b"U"
        + bytes(8)
        + string("clock")
        + u32(0)
        + properties
        + b"U"
        + bytes(8)
    )


class TagReader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def take(self, length):
        assert 0 <= length <= len(self.data) - self.at
        value = self.data[self.at : self.at + length]
        self.at += length
        return value

    def number(self):
        assert self.take(1) == b"L"
        return struct.unpack(">I", self.take(4))[0]

    def done(self):
        return self.at == len(self.data)


class PulseTestPeer(socketserver.StreamRequestHandler):
    def send(self, channel, payload):
        self.request.sendall(struct.pack(">5I", len(payload), channel, 0, 0, 0) + payload)

    def reply(self, tag, payload=b""):
        self.send(CONTROL, u32(2) + u32(tag) + payload)

    def event(self, opcode, extra=b""):
        self.send(CONTROL, u32(opcode) + u32(CONTROL) + u32(CHANNEL) + extra)

    def create(self, tag, args, capture):
        assert args.take(2) == b"a\x05"
        self.channels = args.take(1)[0]
        self.rate = struct.unpack(">I", args.take(4))[0]
        assert args.take(2) == b"m" + bytes([self.channels])
        args.take(self.channels)
        assert args.number() == CONTROL
        expected = string("hosted-in" if capture else "hosted-out") if self.server.hosted_jack else b"N"
        assert args.take(len(expected)) == expected
        maximum = args.number()
        assert args.take(1) == b"1"
        if capture:
            self.period = args.number()
            metrics = u32(maximum) + u32(self.period)
        else:
            target, initial, self.period = args.number(), args.number(), args.number()
            assert args.number() == 0
            assert args.take(2) == b"v" + bytes([self.channels])
            args.take(4 * self.channels)
            metrics = u32(2 * self.period) + u32(maximum) + u32(target) + u32(initial) + u32(self.period)
        assert maximum == self.period * 4
        assert args.take(9) == b"000000001"
        assert args.take(1) == b"P"
        assert args.take(len(string("media.name"))) == string("media.name")
        size = args.number()
        assert args.take(5) == b"x" + struct.pack(">I", size)
        assert args.take(size) == b"btrc audio\0" and args.take(1) == b"N"
        if capture:
            assert args.number() == CONTROL
        assert args.done()
        self.capture = capture
        self.reply(
            tag,
            u32(CHANNEL)
            + u32(1)
            + metrics
            + spec(self.channels, self.rate)
            + channel_map(self.channels)
            + u32(1)
            + string("test")
            + b"0U"
            + bytes(8),
        )

    def command(self, data):
        args = TagReader(data)
        op, tag = args.number(), args.number()
        if op == 8:
            assert args.number() == 13 and args.take(5) == b"x\0\0\1\0"
            assert args.take(256) == self.server.cookie and args.done()
            self.reply(tag, u32(35))
        elif op == 9:
            assert args.take(1) == b"P" and b"application.name\0" in data
            self.reply(tag, u32(0))
        elif op == 20:
            self.reply(
                tag,
                string("PulseAudio")
                + string("17")
                + string("test")
                + string("local")
                + spec(2, RATE)
                + string("sink")
                + string("source")
                + u32(1),
            )
        elif op in (22, 24):
            listing = device("sink" if op == 22 else "source")
            if self.server.hosted_jack:
                listing += device("hosted-out" if op == 22 else "hosted-in", jack=True)
            self.reply(tag, listing)
        elif op in (3, 5):
            self.create(tag, args, op == 5)
        elif op in (41, 58):
            assert args.number() == CHANNEL
            self.running = args.take(1) == b"0"
            self.next_tick = time.monotonic()
            assert args.done()
            self.reply(tag)
        elif op in (4, 6, 42, 59):
            assert args.number() == CHANNEL and args.done()
            self.reply(tag)
        else:
            raise AssertionError(f"unexpected Pulse command {op}")

    def handle(self):
        self.period = 0
        self.capture = self.running = False
        self.sent_blocks = 0
        self.next_tick = time.monotonic()
        try:
            while True:
                if self.capture and self.running and time.monotonic() >= self.next_tick:
                    samples = struct.pack("<ff", -0.5, 0.25)
                    self.sent_blocks += 1
                    if self.sent_blocks == 8:
                        if self.server.fault == "disconnect":
                            self.request.shutdown(socket.SHUT_RDWR)
                            return
                        if self.server.fault == "malformed":
                            self.request.sendall(struct.pack(">5I", 0x7FFFFFFF, CHANNEL, 0, 0, 0))
                            return
                        if self.server.fault == "overflow":
                            self.event(62)
                    self.send(CHANNEL, (samples * ((self.period + 7) // 8))[: self.period])
                    self.next_tick += self.period / (4 * self.channels * self.rate)
                delay = max(0.0, self.next_tick - time.monotonic()) if self.capture and self.running else 1.0
                ready, _, _ = select.select([self.request], [], [], delay)
                if not ready:
                    continue
                # StreamRequestHandler normally buffers input; use an unbuffered reader with select().
                header = self.rfile.read(20)
                if not header:
                    return
                while len(header) < 20:
                    more = self.rfile.read(20 - len(header))
                    if not more:
                        return
                    header += more
                size, channel, high, low, flags = struct.unpack(">5I", header)
                assert 0 < size <= 1 << 24 and (high, low, flags) == (0, 0, 0)
                data = bytearray()
                while len(data) < size:
                    more = self.rfile.read(size - len(data))
                    if not more:
                        return
                    data.extend(more)
                if channel == CONTROL:
                    self.command(bytes(data))
                else:
                    assert not self.capture and channel == CHANNEL and size == self.period
                    self.server.playback.append(bytes(data))
                    if self.server.fault == "underflow" and len(self.server.playback) == 8:
                        self.event(63)
                    self.event(61, u32(size))
        except (ConnectionResetError, BrokenPipeError):
            return

    rbufsize = 0


class PulseTestServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, directory: Path, fault: str = "", hosted_jack: bool = False):
        self.hosted_jack = hosted_jack
        self.fault = fault
        self.cookie = os.urandom(256)
        self.playback = []
        self.errors = []
        self.cookie_path = directory / "cookie"
        self.cookie_path.write_bytes(self.cookie)
        super().__init__(str(directory / "native"), PulseTestPeer)

    def handle_error(self, request, client_address):
        import traceback

        self.errors.append(traceback.format_exc())

    def __enter__(self):
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()
        self.thread.join()
        if not exc[0]:
            assert not self.errors, "\n".join(self.errors)

    @property
    def environment(self):
        return {"PULSE_SERVER": "unix:" + self.server_address, "PULSE_COOKIE": str(self.cookie_path)}
