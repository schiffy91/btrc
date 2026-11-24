"""Rejected frame packets must release every fd installed by recvmsg."""

import ctypes
import os
import socket
import struct
import subprocess
import sys
from array import array
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux DMA-BUF socket")
def test_discard_malformed_dma_bufs_without_leaking_fds(tmp_path):
    source = Path(__file__).resolve().parents[2] / "stdlib/GUI/Linux/DmaBufReceiver.c"
    so = tmp_path / "receiver.so"
    subprocess.run(
        ["cc", "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", source, "-o", so],
        check=True,
    )
    receiver = ctypes.CDLL(str(so))
    receiver.btrcDmaBufListen.argtypes = [ctypes.c_int]
    receiver.btrcDmaBufListen.restype = ctypes.c_void_p
    receiver.btrcDmaBufAddress.argtypes = [ctypes.c_void_p]
    receiver.btrcDmaBufAddress.restype = ctypes.c_char_p
    receiver.btrcDmaBufReceive.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    receiver.btrcDmaBufReceive.restype = ctypes.c_bool
    receiver.btrcDmaBufDisconnect.argtypes = [ctypes.c_void_p]
    receiver.btrcDmaBufDisconnect.restype = None

    endpoint = receiver.btrcDmaBufListen(os.getpid())
    assert endpoint
    try:
        address = receiver.btrcDmaBufAddress(endpoint)
        header = struct.pack("<4sIIIQII8I", b"BTF1", 16, 16, 0x34325258, 0, 1, 0, 64, *([0] * 7))
        frame = ctypes.create_string_buffer(80)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender, (tmp_path / "regular").open("w+b") as file:
            file.truncate(4096)
            initial = len(os.listdir("/proc/self/fd"))
            for payload, count in [
                (header, 1),
                (header, 0),
                (header, 2),
                (header, 30),
                (header[:-1], 1),
                (header + b"!", 1),
            ]:
                rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array("i", [file.fileno()] * count))] if count else []
                sender.sendmsg([payload], rights, 0, address)
                assert not receiver.btrcDmaBufReceive(endpoint, frame)
                assert len(os.listdir("/proc/self/fd")) == initial
    finally:
        receiver.btrcDmaBufDisconnect(endpoint)
    assert not Path(os.fsdecode(address)).parent.exists()
