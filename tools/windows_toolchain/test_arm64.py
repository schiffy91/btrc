"""Portable negative checks; none execute a Windows image on Linux."""

import base64
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.windows_toolchain.arm64 import PINS, ROOT, Evidence, main, pe_arm64
from tools.windows_toolchain.process_runner import Result, run, run_windows


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
        if sys.platform == "win32":
            # The runner owns orphan cleanup; only assert this direct child deadline here.
            program = "import time; print('partial',flush=True); time.sleep(60)"
        started = time.monotonic()
        timeout = 3
        result = run([sys.executable, "-c", program, child], cwd=self.root, env=None, timeout=timeout)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout.splitlines(), [b"partial"])
        self.assertLess(time.monotonic() - started, timeout + 3)

    def test_download_pins_are_complete(self):
        pins = json.loads(Path(__file__).with_name("pins.json").read_text())
        self.assertEqual(pins["zig_version"], "0.16.0")
        for key in ("zig_windows_arm64",):
            self.assertEqual(len(pins[key]["shasum"]), 64)
            self.assertGreater(int(pins[key]["size"]), 0)
        self.assertEqual(len(pins["wgpu"]["sha256"]), 64)

    def test_windows_requires_external_containment_contract(self):
        with self.assertRaisesRegex(RuntimeError, "enclosing runner deadline"):
            run_windows([sys.executable], cwd=self.root, env={}, timeout=1)

    def test_windows_file_capture_keeps_failure_and_launch_error(self):
        environment = {**os.environ, "BTRC_WINDOWS_EXTERNAL_CONTAINMENT": "ephemeral-runner"}
        result = run_windows(
            [sys.executable, "-c", "import sys; print('OBSERVED'); sys.exit(2)"],
            cwd=self.root,
            env=environment,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout.strip(), b"OBSERVED")
        result = run_windows([str(self.root / "missing-clang.exe")], cwd=self.root, env=environment, timeout=1)
        self.assertEqual(result.returncode, 127)
        self.assertIn(b"missing-clang.exe", result.stderr)

    def test_windows_cleanup_failure_retains_output(self):
        environment = {**os.environ, "BTRC_WINDOWS_EXTERNAL_CONTAINMENT": "ephemeral-runner"}
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired("fixture", 1)
        process.poll.return_value = None

        def launch(command, **kwargs):
            kwargs["stdout"].write(b"CHILD-EVIDENCE-31ab")
            kwargs["stdout"].flush()
            return process

        with (
            patch("tools.windows_toolchain.process_runner.subprocess.Popen", side_effect=launch),
            patch("tools.windows_toolchain.process_runner.subprocess.run", side_effect=OSError("taskkill unavailable")),
        ):
            result = run_windows(["fixture"], cwd=self.root, env=environment, timeout=1)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout, b"CHILD-EVIDENCE-31ab")
        self.assertIn(b"taskkill unavailable", result.stderr)
        self.assertIn(b"direct child cleanup failed", result.stderr)
        process.kill.assert_called_once()

    def test_report_writer_refuses_cross_summary_collision_before_any_output(self):
        output = self.root / "output"
        output.mkdir()
        summary = output / "summary.json"
        summary.write_bytes(b"cross provenance must survive")
        with (
            patch(
                "sys.argv",
                [
                    "arm64.py",
                    "native",
                    "--out",
                    str(output),
                    "--cross",
                    str(self.image),
                    "--cross-summary",
                    str(summary),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            main()
        self.assertEqual(summary.read_bytes(), b"cross provenance must survive")

    def test_bad_provenance_does_not_claim_native_execution(self):
        evidence = Evidence(self.root / "output", "zig")
        evidence.report["revision"] = "a" * 40
        summary = self.root / "cross.json"
        summary.write_text("{}")
        with (
            patch("platform.system", return_value="Windows"),
            patch("sysconfig.get_platform", return_value="win-arm64"),
            self.assertRaisesRegex(RuntimeError, "passing Linux cross-build"),
        ):
            evidence.native(self.image, summary)
        self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_zig_version_comes_from_pins(self):
        evidence = Evidence(self.root, "zig")
        with patch.dict(PINS, zig_version="99.1.2"), patch.object(evidence, "run", side_effect=[b"a" * 40, b"99.1.2"]):
            evidence.identify()
        self.assertEqual(evidence.report["zig_version"], "99.1.2")

    def test_wgpu_pin_matches_integrated_archive_hash(self):
        source = (ROOT / "nix/wgpu-native-prebuilt.nix").read_text()
        row = re.search(r'windows-arm64\s*=\s*archive\s+"[^"]+"\s+"sha256-([^"]+)"', source)
        self.assertIsNotNone(row)
        self.assertEqual(base64.b64decode(row[1]).hex(), PINS["wgpu"]["sha256"])


if __name__ == "__main__":
    unittest.main()
