"""Stdlib packages on iOS and iPadOS: their native conformance programs, run in the simulators.

A stdlib package that reaches the system (sockets, threads, a framework) has
a conformance program, which its own driver builds and runs on the host. The
rows here build the same programs for the simulator through both compilers,
plain and sanitized, and run each as a process of a booted iPhone and iPad
simulator (`simctl spawn`): the program has no window and is no app, and the
system it calls is the simulator's own. Simulator results are never
physical-device evidence.

The rows boot simulators, so they run where they are asked for:
BTRC_IOS_UI_DEVICES names the device classes ("iphone,ipad").
"""

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.python import test_apple_encoded_image_decoder_runtime as image_decoder
from src.tests.python import test_background_jobs_runtime as background_jobs
from src.tests.python.ios_simulator_fixtures import FRONTENDS, MODES, simulators  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
NATIVE = REPO / "src/tests/native"
DIGESTED = REPO / "src/language/grammar.ebnf"


@dataclass(frozen=True)
class Program:
    """A package's program: what it is run with, and the line it ends on when every check held."""

    source: Path
    passed: str
    arguments: tuple[str, ...] = ()
    # A fixture's header, the names the program binds from it, and the C source that defines them.
    probe: tuple | None = None
    # Its own driver on the host accepts the nullability warnings its source raises; so do these rows.
    warns: bool = False
    environment: tuple[tuple[str, str], ...] = ()
    # Files the program reads, made on the host into a directory it is given: their paths are its arguments.
    prepared: Callable[[Path], tuple[str, ...]] | None = None


def two_frame_tiff(directory: Path) -> tuple[str, ...]:
    """The decoder's TIFF, written by the host's own ImageIO: a file is the same file on either system."""

    encoder, tiff = directory / "tiff-encoder", directory / "two-frames.tiff"
    frameworks = [{"name": name} for name in ("CoreFoundation", "CoreGraphics", "ImageIO")]
    image_decoder._build(image_decoder.FIXTURES / "ImageIoTiffFixture.c", encoder, frameworks)
    made = subprocess.run([str(encoder), str(tiff)], capture_output=True, text=True, timeout=60, check=False)
    assert made.returncode == 0 and tiff.is_file(), made.stderr
    return (str(tiff),)


PROGRAMS = {
    "background-jobs": Program(
        background_jobs.CONFORMANCE,
        "PASS: bounded background job ownership",
        probe=(
            *background_jobs.BINDINGS[background_jobs.CONFORMANCE],
            background_jobs.FIXTURE / "background_job_probe.c",
        ),
        warns=True,
    ),
    # The system's SHA-256 of a file, which the program holds to the portable one's.
    "digest": Program(
        REPO / "src/tests/btrc/fixtures/NativeDigestDriver.btrc",
        hashlib.sha256(DIGESTED.read_bytes()).hexdigest(),
        arguments=(str(DIGESTED),),
        warns=True,
    ),
    # ImageIO's PNG, JPEG, GIF and TIFF, with the portable DDS decoder, the limits and the refusals.
    "image": Program(
        image_decoder.FIXTURES / "AppleEncodedImageDecoderConformance.btrc",
        "PASS AppleEncodedImageDecoderConformance",
        prepared=two_frame_tiff,
        warns=True,
    ),
    # The program forks its client, which a simulator's process may do and an
    # app on a device may not: the row is the channel's, not an app's. A Unix
    # socket's path is at most 103 bytes, and a simulator's own temporary
    # directory is longer than that already, so the endpoint is made under /tmp.
    "local-channel": Program(
        NATIVE / "local_application_channel/LocalApplicationChannelConformance.btrc",
        "PASS: local application channel conformance",
        warns=True,
        environment=(("TMPDIR", "/tmp"),),
    ),
    "network": Program(
        NATIVE / "network/NetworkConformance.btrc",
        "PASS: network listener, streams, deadlines, resolver and bulk transfer",
    ),
    "process-threads": Program(NATIVE / "background_jobs/ProcessThreadsLive.btrc", "PASS: process thread count"),
    # An emulated HID device exported over USB/IP to a user-space host, the
    # device in a forked child at the other end of a socket pair.
    "usb": Program(NATIVE / "usb/USBEmulatedDevice.btrc", "PASS: emulated USB device over USB/IP"),
    # Neither the host nor the gadget is open to an iOS or iPadOS program.
    "usb-refusals": Program(
        NATIVE / "usb/USBAppleRefusals.btrc",
        "PASS: no USB host or device controller for a program on this system",
    ),
}
# One worker owns the simulator: a device is booted and run on by one process.
pytestmark = pytest.mark.xdist_group(name="ios_ui")


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("name", sorted(PROGRAMS))
@pytest.mark.parametrize("device_class", ["iphone", "ipad"])
def test_ios_stdlib_program(simulators, request, tmp_path, device_class, name, frontend, sanitized):  # noqa: F811
    program = PROGRAMS[name]
    arguments = program.arguments + (program.prepared(tmp_path) if program.prepared else ())
    status, stdout, stderr = simulators.spawned(
        device_class,
        name,
        program.source,
        frontend,
        sanitized,
        request,
        arguments,
        program.probe,
        quiet=not program.warns,
        environment=dict(program.environment),
    )
    where = simulators.host.provenance()
    report = f"{name} on {where['device']}, {where['os_build']} ({frontend}, {MODES[sanitized]})\n{stdout}{stderr}"
    assert status == 0, report
    assert "ERROR: AddressSanitizer" not in stderr and "runtime error:" not in stderr, report
    assert stdout.splitlines()[-1:] == [program.passed], report
