"""Real consumer-to-companion transfer; cross-builds do not claim native execution."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import RUN_TIMEOUT
from src.tests.python.test_windows_daemon_image import REPO, RUNTIME, STRICT, TARGETS, metadata, run_build


@pytest.fixture(params=sorted(TARGETS), scope="module")
def transfer_bundle(request, tmp_path_factory):
    label = request.param
    root = tmp_path_factory.mktemp(f"daemon-transfer-{label}")
    driver = [shutil.which("zig"), "cc", "-target", TARGETS[label].zig_target, *STRICT, "-I", str(RUNTIME)]
    process = root / "windows_os.o"
    image = root / "image.o"
    run_build([*driver, "-c", str(RUNTIME / "windows_os.c"), "-o", str(process)])
    run_build([*driver, "-c", str(RUNTIME / "windows_daemon_image.c"), "-o", str(image)])
    leaf = root / "consumer.exe.btrc-supervisor.exe"
    run_build(
        [
            *driver,
            str(REPO / "src/tests/native/windows_launch/launch_harness.c"),
            str(process),
            "-lshell32",
            "-ladvapi32",
            "-o",
            str(leaf),
        ]
    )
    carrier = root / "metadata.c"
    metadata(carrier, leaf, label)
    run_build(
        [
            *driver,
            str(REPO / "src/tests/native/daemon_windows/transfer_harness.c"),
            str(carrier),
            str(image),
            str(process),
            "-lbcrypt",
            "-ladvapi32",
            "-o",
            str(root / "consumer.exe"),
        ]
    )
    fault_points = ("commit-then-exit", "partial-commit", "kill-before-commit", "drop-ack", "drop-ack-kill")
    forbidden = (*fault_points, "BTRC_RUNTIME_DAEMON_FAULT_POINT", "btrc_wdi_fault", "btrc_daemon_fault_terminate")
    for production in (image, root / "consumer.exe"):
        content = production.read_bytes()
        assert all(value.encode() not in content for value in forbidden), production
    fixture = root / "fault-fixture.o"
    run_build(
        [
            *driver,
            "-DBTRC_DAEMON_FAULT_FIXTURE=1",
            "-c",
            str(REPO / "src/tests/native/daemon_windows/transfer_harness.c"),
            "-o",
            str(fixture),
        ]
    )
    for point in fault_points:
        fault_object = root / f"{point}.o"
        run_build(
            [
                *driver,
                f'-DBTRC_RUNTIME_DAEMON_FAULT_POINT="{point}"',
                "-c",
                str(RUNTIME / "windows_daemon_image.c"),
                "-o",
                str(fault_object),
            ]
        )
        run_build(
            [
                *driver,
                str(fixture),
                str(fault_object),
                str(process),
                str(carrier),
                "-lbcrypt",
                "-ladvapi32",
                "-o",
                str(root / f"{point}.exe"),
            ]
        )
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        destination = Path(evidence) / f"daemon-transfer-{label}"
        destination.mkdir(parents=True, exist_ok=True)
        for source in root.glob("*.exe"):
            shutil.copy2(source, destination / source.name)
    return label, root


def test_transfer_links_both_windows_abis(transfer_bundle):
    _, root = transfer_bundle
    assert (root / "consumer.exe").read_bytes().startswith(b"MZ")


def test_native_transfer_confirms_records_and_preserves_commit(transfer_bundle, tmp_path):
    label, source = transfer_bundle
    if sys.platform != "win32":
        pytest.skip("requires native Windows process, file and pipe semantics")
    if label == "windows-aarch64" and os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() != "ARM64":
        pytest.skip("ARM64 image requires an ARM64 Windows host")
    root = tmp_path / "daemon transfer é😀"
    shutil.copytree(source, root)
    result = subprocess.run(
        [str(root / "consumer.exe")], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False
    )
    assert result.returncode == 0, (result.stdout, result.stderr, result.returncode)
    assert result.stdout.strip() == "daemon-transfer PASS"


@pytest.mark.parametrize(
    "point", ["commit-then-exit", "partial-commit", "kill-before-commit", "drop-ack", "drop-ack-kill"]
)
def test_native_transfer_faults_do_not_authorize_retries(transfer_bundle, tmp_path, point):
    label, source = transfer_bundle
    if sys.platform != "win32":
        pytest.skip("requires native Windows process, file and pipe semantics")
    if label == "windows-aarch64" and os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() != "ARM64":
        pytest.skip("ARM64 image requires an ARM64 Windows host")
    root = tmp_path / "daemon fault é😀"
    shutil.copytree(source, root)
    argument = "commit-exit-parent" if point == "commit-then-exit" else point
    result = subprocess.run(
        [str(root / f"{point}.exe"), argument], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False
    )
    assert result.returncode == 0, (result.stdout, result.stderr, result.returncode)
    assert result.stdout.strip() == "daemon-transfer-fault PASS"
