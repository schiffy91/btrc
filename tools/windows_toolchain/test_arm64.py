"""Portable negative checks; none execute a Windows image on Linux."""

import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.windows_toolchain.arm64 import Evidence, pe_arm64


class Arm64EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "btrcc.exe"
        self.data = bytearray(256)
        self.data[:2] = b"MZ"
        struct.pack_into("<I", self.data, 60, 128)
        self.data[128:132] = b"PE\0\0"
        struct.pack_into("<H", self.data, 132, 0xAA64)
        struct.pack_into("<H", self.data, 152, 0x20B)
        self.image.write_bytes(self.data)

    def test_arm64_pe_metadata_does_not_claim_execution(self):
        result = pe_arm64(self.image)
        self.assertEqual(result["machine"], 0xAA64)
        self.assertEqual(result["bytes"], 256)
        self.assertEqual(len(result["sha256"]), 64)
        self.assertNotIn("executed", result)

    def test_x64_machine_is_rejected(self):
        struct.pack_into("<H", self.data, 132, 0x8664)
        self.image.write_bytes(self.data)
        with self.assertRaisesRegex(ValueError, "expected ARM64"):
            pe_arm64(self.image)

    def test_truncated_and_wrong_pe_headers_are_rejected(self):
        for data in (b"", b"MZ", b"MZ" + bytes(100), self.data[:150]):
            with self.subTest(length=len(data)):
                self.image.write_bytes(data)
                with self.assertRaises(ValueError):
                    pe_arm64(self.image)

    def test_pe32_arm64_is_rejected(self):
        struct.pack_into("<H", self.data, 152, 0x10B)
        self.image.write_bytes(self.data)
        with self.assertRaisesRegex(ValueError, "PE32"):
            pe_arm64(self.image)

    def test_native_refuses_linux_before_compilation(self):
        evidence = Evidence(self.root, "zig")
        with patch("platform.system", return_value="Linux"), patch.object(evidence, "build") as build:
            with self.assertRaisesRegex(RuntimeError, "actual ARM64 Windows"):
                evidence.native(self.image)
            build.assert_not_called()
        self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_native_refuses_overwriting_the_cross_artifact(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch("platform.system", return_value="Windows"),
            patch("platform.machine", return_value="ARM64"),
            self.assertRaisesRegex(RuntimeError, "separate"),
        ):
            evidence.native(self.image)
        self.assertEqual(self.image.read_bytes(), self.data)

    def test_subprocess_failure_keeps_stderr_and_failed_status(self):
        evidence = Evidence(self.root, "zig")
        result = subprocess.CompletedProcess(["zig"], 3, b"output", b"exact diagnostic")
        with patch("subprocess.run", return_value=result) as run:
            with self.assertRaisesRegex(RuntimeError, "exited 3"):
                evidence.run(["zig"], "probe", timeout=7)
            self.assertEqual(run.call_args.kwargs["timeout"], 7)
        self.assertEqual((self.root / "probe.stderr").read_bytes(), b"exact diagnostic")
        self.assertEqual(evidence.report["status"], "failed")

    def test_download_pins_are_complete(self):
        pins = json.loads(Path(__file__).with_name("pins.json").read_text())
        self.assertEqual(pins["zig_version"], "0.16.0")
        for key in ("zig_windows_arm64", "zig_linux_x64"):
            self.assertEqual(len(pins[key]["shasum"]), 64)
            self.assertGreater(int(pins[key]["size"]), 0)
        self.assertEqual(len(pins["wgpu"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
