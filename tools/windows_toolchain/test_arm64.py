"""Portable negative checks; none execute a Windows image on Linux."""

import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.windows_toolchain.arm64 import Evidence, main, pe_arm64
from tools.windows_toolchain.process_runner import Result, run


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
                evidence.native(self.image, self.root / "summary.json")
            build.assert_not_called()
        self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_native_refuses_overwriting_the_cross_artifact(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch("platform.system", return_value="Windows"),
            patch("sysconfig.get_platform", return_value="win-arm64"),
            self.assertRaisesRegex(RuntimeError, "separate"),
        ):
            evidence.native(self.image, self.root / "summary.json")
        self.assertEqual(self.image.read_bytes(), self.data)

    def test_emulated_x64_python_is_not_native_arm64_evidence(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch("platform.system", return_value="Windows"),
            patch("sysconfig.get_platform", return_value="win-amd64"),
            self.assertRaisesRegex(RuntimeError, "ARM64 Python"),
        ):
            evidence.native(self.image, self.root / "summary.json")

    def test_actual_report_writer_supplies_accepted_cross_provenance(self):
        def identify(evidence):
            evidence.report.update(revision="a" * 40, zig_version="0.16.0")

        def build(evidence):
            evidence.report["compiler"] = pe_arm64(self.image)
            return self.image

        with (
            patch("sys.argv", ["arm64.py", "cross", "--out", str(self.root)]),
            patch("platform.system", return_value="Linux"),
            patch.object(Evidence, "identify", identify),
            patch.object(Evidence, "build", build),
        ):
            self.assertEqual(main(), 0)
        report = json.loads((self.root / "summary.json").read_text())
        self.assertEqual(report["host_system"], "Linux")
        self.assertTrue(report["python_platform"])
        consumer = Evidence(self.root / "native", "zig")
        consumer.report.update(revision="a" * 40, cross_compiler=pe_arm64(self.image))
        consumer.verify_cross(self.root / "summary.json")

    def test_cross_provenance_checks_host_revision_and_bytes(self):
        evidence = Evidence(self.root, "zig")
        evidence.report.update(revision="a" * 40, cross_compiler=pe_arm64(self.image))
        summary = {
            "status": "passed",
            "mode": "cross",
            "host_system": "Linux",
            "native_execution": "not-run",
            "revision": "a" * 40,
            "zig_version": "0.16.0",
            "compiler": pe_arm64(self.image),
        }
        path = self.root / "cross.json"
        path.write_text(json.dumps(summary))
        evidence.verify_cross(path)
        for key, value in (
            ("host_system", "Windows"),
            ("mode", "native"),
            ("revision", "b" * 40),
            ("compiler", {**summary["compiler"], "sha256": "0" * 64}),
        ):
            with self.subTest(key=key):
                path.write_text(json.dumps({**summary, key: value}))
                with self.assertRaises(RuntimeError):
                    evidence.verify_cross(path)

    def test_subprocess_failure_keeps_stderr_and_failed_status(self):
        evidence = Evidence(self.root, "zig")
        result = Result(3, b"output", b"exact diagnostic", False)
        with patch("tools.windows_toolchain.arm64.run_process", return_value=result) as command_run:
            with self.assertRaisesRegex(RuntimeError, "exited 3"):
                evidence.run(["zig"], "probe", timeout=7)
            self.assertEqual(command_run.call_args.kwargs["timeout"], 7)
        self.assertEqual((self.root / "probe.stderr").read_bytes(), b"exact diagnostic")
        self.assertEqual(evidence.report["status"], "failed")

    def test_timeout_retains_partial_output_and_step_metadata(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch(
                "tools.windows_toolchain.arm64.run_process", return_value=Result(None, b"partial", b"diagnostic", True)
            ),
            self.assertRaisesRegex(RuntimeError, "partial stdout/stderr retained"),
        ):
            evidence.run(["zig"], "timeout", timeout=1)
        self.assertEqual((self.root / "timeout.stdout").read_bytes(), b"partial")
        self.assertTrue(evidence.report["steps"][0]["timed_out"])

    def test_parent_exit_with_inherited_pipes_has_bounded_cleanup(self):
        child = "import time; time.sleep(60)"
        program = (
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('partial',flush=True)"
        )
        started = time.monotonic()
        timeout = 3 if sys.platform == "win32" else 0.2
        result = run([sys.executable, "-c", program, child], cwd=self.root, env=None, timeout=timeout)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout.splitlines(), [b"partial"])
        self.assertLess(time.monotonic() - started, timeout + 3)

    def test_download_pins_are_complete(self):
        pins = json.loads(Path(__file__).with_name("pins.json").read_text())
        self.assertEqual(pins["zig_version"], "0.16.0")
        for key in ("zig_windows_arm64", "zig_linux_x64"):
            self.assertEqual(len(pins[key]["shasum"]), 64)
            self.assertGreater(int(pins[key]["size"]), 0)
        self.assertEqual(len(pins["wgpu"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
