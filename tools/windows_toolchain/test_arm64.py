"""Portable negative checks; none execute a Windows image on Linux."""

import base64
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.windows_toolchain.arm64 import PINS, ROOT, Evidence, main, pe_arm64
from tools.windows_toolchain.process_runner import Result, _remove_capture, run, run_windows


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
        with self.assertRaisesRegex(ValueError, "PE optional header"):
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

    def test_empty_c_frontend_version_stops_before_compilation(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch("tools.windows_toolchain.arm64.run_process", return_value=Result(0, b"", b"", False)) as execute,
            self.assertRaisesRegex(RuntimeError, "C frontend version probe returned no output"),
        ):
            evidence.probe_native_toolchain()
        self.assertEqual(execute.call_count, 1)
        self.assertFalse((self.root / "toolchain-probe.c").exists())
        self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_native_toolchain_probe_requires_both_actual_streams(self):
        for stdout, stderr in ((b"", b"BTRC_TOOLCHAIN_STDERR\n"), (b"BTRC_TOOLCHAIN_STDOUT\n", b"")):
            with self.subTest(stdout=stdout, stderr=stderr):
                evidence = Evidence(self.root, "zig")
                (self.root / "toolchain-probe.exe").write_bytes(self.data)
                with (
                    patch(
                        "tools.windows_toolchain.arm64.run_process",
                        side_effect=[
                            Result(0, b"C frontend version\n", b"", False),
                            Result(0, b"", b"", False),
                            Result(0, stdout, stderr, False),
                        ],
                    ),
                    self.assertRaisesRegex(RuntimeError, "preserve both output streams"),
                ):
                    evidence.probe_native_toolchain()
                self.assertNotIn("native_toolchain_probe", evidence.report)
                self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_native_toolchain_failure_prevents_expensive_compiler_build(self):
        evidence = Evidence(self.root / "output", "zig")
        with (
            patch("platform.system", return_value="Windows"),
            patch("sysconfig.get_platform", return_value="win-arm64"),
            patch.object(evidence, "verify_cross"),
            patch.object(evidence, "probe_native_toolchain", side_effect=RuntimeError("C frontend crashed")),
            patch.object(evidence, "build") as build,
            self.assertRaisesRegex(RuntimeError, "C frontend crashed"),
        ):
            evidence.native(self.image, self.root / "cross.json")
        build.assert_not_called()
        self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_tiny_build_crash_collects_bounded_diagnostics_and_still_fails(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch(
                "tools.windows_toolchain.arm64.run_process",
                side_effect=[
                    Result(0, b"C frontend version\n", b"", False),
                    Result(0xC0000005, b"", b"original crash", False),
                    Result(0, b"", b"driver plan", False),
                    Result(0xC0000005, b"", b"syntax crash", False),
                    *[Result(0, b"diagnostic output", b"", False) for _ in range(4)],
                ],
            ) as execute,
            self.assertRaisesRegex(RuntimeError, "toolchain-probe-build exited 3221225477"),
        ):
            evidence.probe_native_toolchain()
        self.assertEqual(execute.call_count, 8)
        self.assertEqual([call.kwargs["timeout"] for call in execute.call_args_list[2:]], [60] * 6)
        self.assertEqual((self.root / "toolchain-probe-build.stderr").read_bytes(), b"original crash")
        self.assertEqual((self.root / "diagnostic-native-syntax.stderr").read_bytes(), b"syntax crash")
        self.assertEqual(list(evidence.report["c_frontend_diagnostics"]["failures"]), ["native-syntax"])
        self.assertEqual(evidence.report["status"], "failed")
        self.assertEqual(evidence.report["native_execution"], "not-run")

    def test_tiny_build_diagnostic_error_preserves_the_original_failure(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch(
                "tools.windows_toolchain.arm64.run_process",
                side_effect=[Result(0, b"version", b"", False), Result(3, b"", b"build failed", False)],
            ),
            patch.object(evidence, "diagnose_c_frontend", side_effect=OSError("diagnostic write failed")),
            self.assertRaisesRegex(RuntimeError, "toolchain-probe-build exited 3"),
        ):
            evidence.probe_native_toolchain()
        self.assertEqual(evidence.report["c_frontend_diagnostics_error"], "diagnostic write failed")
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

    def test_crash_diagnostics_keep_partial_output_under_a_separate_bound(self):
        evidence = Evidence(self.root, "zig")
        evidence.deadline = 0  # Failure diagnostics still have their own bounded budget.
        with patch(
            "tools.windows_toolchain.arm64.run_process",
            return_value=Result(None, b"partial crash event", b"probe stalled", True),
        ) as execute:
            evidence.diagnose_windows_failure()
        self.assertEqual(execute.call_args.kwargs["timeout"], 20)
        self.assertEqual((self.root / "host-diagnostics.stdout").read_bytes(), b"partial crash event")
        self.assertEqual((self.root / "host-diagnostics.stderr").read_bytes(), b"probe stalled")
        self.assertTrue(evidence.report["host_diagnostics"]["timed_out"])
        self.assertEqual(evidence.report["status"], "failed")

    def test_diagnostic_failure_cannot_replace_the_original_compiler_error(self):
        with (
            patch("sys.argv", ["arm64.py", "cross", "--out", str(self.root)]),
            patch("tools.windows_toolchain.arm64.sys.platform", "win32"),
            patch.object(Evidence, "identify", side_effect=RuntimeError("original build crash")),
            patch.object(Evidence, "diagnose_windows_failure", side_effect=OSError("diagnostic failure")),
        ):
            self.assertEqual(main(), 1)
        report = json.loads((self.root / "summary.json").read_text())
        self.assertEqual(report["error"], "original build crash")
        self.assertEqual(report["host_diagnostics_error"], "diagnostic failure")
        self.assertEqual(report["status"], "failed")

    def test_empty_successful_diagnostic_is_not_accepted_as_host_evidence(self):
        evidence = Evidence(self.root, "zig")
        with (
            patch("tools.windows_toolchain.arm64.run_process", return_value=Result(0, b"", b"", False)),
            self.assertRaisesRegex(RuntimeError, "host diagnostic.*report"),
        ):
            evidence.diagnose_windows_failure()
        self.assertEqual((self.root / "host-diagnostics.stdout").read_bytes(), b"")
        self.assertEqual(evidence.report["host_diagnostics"]["exit_code"], 0)

    def test_native_diagnostic_emits_a_host_report_through_the_actual_job(self):
        if sys.platform != "win32":
            self.skipTest("Windows host diagnostics require the native Job owner")
        evidence = Evidence(self.root, "zig")
        try:
            evidence.diagnose_windows_failure()
        except RuntimeError as error:
            self.fail(
                f"{error}; metadata={evidence.report.get('host_diagnostics')}; "
                f"stdout={(self.root / 'host-diagnostics.stdout').read_bytes()!r}; "
                f"stderr={(self.root / 'host-diagnostics.stderr').read_bytes()!r}"
            )
        report = json.loads((self.root / "host-diagnostics.stdout").read_bytes())
        self.assertEqual(report["schema"], "btrc.windows-host-diagnostics/1")
        self.assertGreater(report["capacity"]["TotalVisibleMemorySize"], 0)

    def test_parent_exit_with_inherited_pipes_has_bounded_cleanup(self):
        child = "import time; time.sleep(60)"
        program = (
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('partial',flush=True)"
        )
        started = time.monotonic()
        result = run([sys.executable, "-c", program, child], cwd=self.root, env=None, timeout=3)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), [b"partial"])
        self.assertLess(time.monotonic() - started, 6)

    def test_timeout_keeps_child_output(self):
        result = run(
            [sys.executable, "-c", "import time; print('partial',flush=True); time.sleep(60)"],
            cwd=self.root,
            env=None,
            timeout=3,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout.splitlines(), [b"partial"])

    def test_download_pins_are_complete(self):
        pins = json.loads(Path(__file__).with_name("pins.json").read_text())
        self.assertEqual(pins["zig_version"], "0.16.0")
        for key in ("zig_windows_arm64",):
            self.assertEqual(len(pins[key]["shasum"]), 64)
            self.assertGreater(int(pins[key]["size"]), 0)
        self.assertEqual(len(pins["wgpu"]["sha256"]), 64)

    def test_windows_job_cannot_be_claimed_on_another_host(self):
        if sys.platform != "win32":
            with self.assertRaisesRegex(RuntimeError, "require native Windows"):
                run_windows([sys.executable], cwd=self.root, env={}, timeout=1)
        else:
            result = run_windows([sys.executable, "-c", "pass"], cwd=self.root, env=None, timeout=10)
            self.assertEqual(result.returncode, 0)

    def test_file_capture_keeps_failure_and_launch_error(self):
        result = run(
            [sys.executable, "-c", "import sys; print('OBSERVED'); sys.exit(2)"],
            cwd=self.root,
            env=os.environ.copy(),
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout.strip(), b"OBSERVED")
        result = run([str(self.root / "missing-clang.exe")], cwd=self.root, env=None, timeout=10)
        self.assertEqual(result.returncode, 127)
        self.assertIn(b"missing-clang.exe", result.stderr)

    def test_windows_cleanup_failure_is_not_a_successful_result(self):
        process, job = Mock(), Mock()
        job.name = "fixture-event"
        process.poll.return_value = 0
        job.wait_empty.side_effect = RuntimeError("job still has live processes")
        with (
            patch("tools.windows_toolchain.process_runner.WindowsJob", return_value=job),
            patch("tools.windows_toolchain.process_runner.subprocess.Popen", return_value=process),
        ):
            result = run_windows(["fixture"], cwd=self.root, env=None, timeout=1)
        self.assertIsNone(result.returncode)
        self.assertIn("job still has live processes", result.error)
        job.assign.assert_called_once_with(process)
        job.release.assert_called_once()
        job.terminate.assert_called_once()
        job.close.assert_called_once()

    def test_capture_cleanup_waits_for_a_transient_windows_sharing_violation(self):
        directory = self.root / "capture"
        directory.mkdir()
        (directory / "stderr").write_bytes(b"child diagnostic")
        blocked = PermissionError("capture still open")
        blocked.winerror = 32
        remove = shutil.rmtree
        attempts = []

        def release_then_remove(path):
            attempts.append(path)
            if len(attempts) == 1:
                raise blocked
            remove(path)

        with patch("tools.windows_toolchain.process_runner.shutil.rmtree", side_effect=release_then_remove):
            _remove_capture(directory)
        self.assertEqual(len(attempts), 2)
        self.assertFalse(directory.exists())

    def test_persistent_capture_lock_retains_the_command_result_and_fails(self):
        directory = self.root / "capture"
        directory.mkdir()
        (directory / "stderr").write_bytes(b"child diagnostic")
        blocked = PermissionError("capture still open")
        blocked.winerror = 32
        with (
            patch("tools.windows_toolchain.process_runner.tempfile.mkdtemp", return_value=str(directory)),
            patch(
                "tools.windows_toolchain.process_runner._run_windows_captured",
                return_value=Result(None, b"child output", b"child diagnostic", True),
            ),
            patch("tools.windows_toolchain.process_runner.shutil.rmtree", side_effect=blocked),
            patch("tools.windows_toolchain.process_runner.time.monotonic", side_effect=[0, 6]),
        ):
            result = run_windows(["fixture"], cwd=self.root, env=None, timeout=1)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout, b"child output")
        self.assertTrue(result.stderr.startswith(b"child diagnostic"))
        self.assertIn("Capture cleanup failed", result.error)
        self.assertIn(str(directory), result.error)
        self.assertEqual((directory / "stderr").read_bytes(), b"child diagnostic")

    def test_capture_cleanup_does_not_retry_other_permission_errors(self):
        with (
            patch(
                "tools.windows_toolchain.process_runner.shutil.rmtree", side_effect=PermissionError("denied")
            ) as remove,
            patch("tools.windows_toolchain.process_runner.time.sleep") as sleep,
            self.assertRaisesRegex(PermissionError, "denied"),
        ):
            _remove_capture(self.root / "capture")
        remove.assert_called_once()
        sleep.assert_not_called()

    def test_windows_launch_diagnostic_keeps_executable_when_os_message_omits_it(self):
        process, job = Mock(), Mock()
        job.name = "fixture-event"
        process.poll.return_value = 1

        def gate(command, **_options):
            request = json.loads(Path(command[-1]).read_text())
            Path(request["launch_error"]).write_text(
                json.dumps(
                    {
                        "stage": "CreateProcessW",
                        "message": "The system cannot find the file specified",
                        "winerror": 2,
                    }
                )
            )
            return process

        with (
            patch("tools.windows_toolchain.process_runner.WindowsJob", return_value=job),
            patch("tools.windows_toolchain.process_runner.subprocess.Popen", side_effect=gate),
        ):
            result = run_windows(["missing-clang.exe"], cwd=self.root, env=None, timeout=10)
        self.assertEqual(result.returncode, 127)
        self.assertIn(b"missing-clang.exe", result.stderr)
        self.assertIn(b"CreateProcessW", result.stderr)
        self.assertIn(b"The system cannot find the file specified", result.stderr)
        job.terminate.assert_called_once()
        job.close.assert_called_once()

    def test_overall_deadline_caps_each_command_and_refuses_new_work(self):
        evidence = Evidence(self.root, "zig")
        evidence.deadline = 105
        with (
            patch("tools.windows_toolchain.arm64.time.monotonic", return_value=100),
            patch("tools.windows_toolchain.arm64.run_process", return_value=Result(0, b"ok", b"", False)) as execute,
        ):
            evidence.run(["fixture"], "bounded", timeout=3600)
            self.assertEqual(execute.call_args.kwargs["timeout"], 5)
        with (
            patch("tools.windows_toolchain.arm64.time.monotonic", return_value=106),
            patch("tools.windows_toolchain.arm64.run_process") as execute,
            self.assertRaisesRegex(TimeoutError, "overall native evidence deadline"),
        ):
            evidence.run(["fixture"], "expired")
        execute.assert_not_called()

    def test_assignment_failure_still_reaps_gate_when_job_termination_fails(self):
        process, job = Mock(), Mock()
        job.name = "fixture-event"
        process.poll.return_value = None
        job.assign.side_effect = RuntimeError("assignment failed")
        job.terminate.side_effect = RuntimeError("termination failed")
        with (
            patch("tools.windows_toolchain.process_runner.WindowsJob", return_value=job),
            patch("tools.windows_toolchain.process_runner.subprocess.Popen", return_value=process),
        ):
            result = run_windows(["fixture"], cwd=self.root, env=None, timeout=1)
        self.assertIsNone(result.returncode)
        self.assertIn("assignment failed", result.error)
        self.assertIn("termination failed", result.error)
        job.release.assert_not_called()
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)
        job.wait_empty.assert_called_once()
        job.close.assert_called_once()

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
