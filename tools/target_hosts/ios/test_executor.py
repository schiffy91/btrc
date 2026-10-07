"""Local process tests for executor mechanics; never simulator evidence."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tools.target_hosts.ios.executor import ExecutionRequest, IOSSimulatorExecutor
from tools.target_hosts.ios.simhost import IOSSimulatorHost, SimulatorError
from tools.target_hosts.ios.spike import SimulatorSpike


class LocalProcessHost:
    """Run the actual C host locally while simulating only simctl's transport."""

    def __init__(self, root: Path):
        self.root = root
        self.processes = {}
        self.apps = {}
        self.containers = []
        self.signals = []

    def prepare(self):
        pass

    def provenance(self):
        return {"executor": "local-process-test", "evidence": "not-ios", "device_class": "test"}

    def device(self):
        return "local-test-device"

    @staticmethod
    def child_environment(values):
        return dict(os.environ, **values)

    def spawn(self, executable, argv, env):
        process = subprocess.Popen(
            [str(executable), *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.child_environment(env),
            start_new_session=True,
        )
        self.processes[process.pid] = process
        return process

    def alive(self, pid):
        return self.processes[pid].poll() is None

    def send_signal(self, pid, number, *, group=False):
        self.signals.append(number)
        if self.alive(pid):
            if group:
                os.killpg(pid, number)
            else:
                os.kill(pid, number)

    @staticmethod
    def stop_launcher(process):
        return process.communicate(timeout=3)

    def terminate_app(self, bundle_id):
        app = self.apps.get(bundle_id)
        if app and app.get("process"):
            process = app["process"]
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)

    def command(self, *args, **kwargs):
        output = b""
        status = 0
        match args:
            case ("get_app_container", _, bundle_id, kind):
                if bundle_id not in self.apps:
                    status = 1
                else:
                    output = str(self.apps[bundle_id][kind]).encode() + b"\n"
            case ("install", _, artifact):
                bundle_id = f"dev.btrc.testhost.{Path(artifact).stem}"
                directory = Path(tempfile.mkdtemp(dir=self.root, prefix="container-"))
                self.containers.append(directory)
                self.apps[bundle_id] = {"app": Path(artifact), "data": directory}
            case ("launch", "--terminate-running-process", _, bundle_id, *argv):
                app = self.apps[bundle_id]
                app["process"] = self.spawn(app["app"] / "TestHost", tuple(argv), kwargs["env"])
                output = f"{bundle_id}: {app['process'].pid}\n".encode()
            case ("uninstall", _, bundle_id):
                app = self.apps.pop(bundle_id)
                shutil.rmtree(app["data"])
            case _:
                raise AssertionError(args)
        return subprocess.CompletedProcess(args, status, stdout=output, stderr=b"")

    def close(self):
        for process in self.processes.values():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)


class DelayedProcessHost(LocalProcessHost):
    """Keep the simctl-shaped launcher distinct from the native fixture PID."""

    def __init__(self, root, delay=1):
        super().__init__(root)
        self.delay = delay
        self.child_file = root / "delayed-child-pid"
        self.child_file.unlink(missing_ok=True)
        self.child_file.with_suffix(".stdout").unlink(missing_ok=True)

    def spawn(self, executable, argv, env):
        process = subprocess.Popen(
            [
                sys.executable,
                str(SimulatorSpike.root / "fixtures/delayed_launcher.py"),
                str(self.delay),
                str(self.child_file),
                str(executable),
                *argv,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.child_environment(env),
            start_new_session=True,
        )
        self.processes[process.pid] = process
        return process

    def alive(self, pid):
        return IOSSimulatorHost.alive(self, pid)

    def send_signal(self, pid, number, *, group=False):
        self.signals.append(number)
        IOSSimulatorHost.send_signal(self, pid, number, group=group)

    def stop_launcher(self, process):
        return IOSSimulatorHost.stop_launcher(process)

    def close(self):
        # Own cleanup independently, including when testing a regressed executor.
        if self.child_file.exists():
            pid = int(self.child_file.read_text())
            if self.alive(pid):
                self.send_signal(pid, signal.SIGKILL)
        super().close()


class ExecutorProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="btrc-ios-local-test-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.bundle = cls.root / "bundle"
        SimulatorSpike.build(cls.bundle, local_cc="cc")
        cls.programs = json.loads((cls.bundle / "programs.json").read_text())["programs"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.host = LocalProcessHost(self.root)

    def tearDown(self):
        self.host.close()

    def executor(self, mode):
        executor = IOSSimulatorExecutor(mode=mode, host=self.host)
        # Deliberately bypass prepare: the local build is branded non-iOS and
        # production prepare must reject it. These are transport/lifetime tests.
        executor.bundle_dir = self.bundle
        executor.programs = self.programs
        executor.host_provenance = self.host.provenance()
        return executor

    def test_spawn_c_host_byte_streams_status_signal_timeout_and_arguments(self):
        executor = self.executor("spawn")
        for name in SimulatorSpike.cases:
            with self.subTest(fixture=name):
                result = executor.run(SimulatorSpike.request(name))
                SimulatorSpike.check(name, result)
                self.assertEqual(result.provenance["evidence"], "not-ios")
        self.assertIn(signal.SIGKILL, self.host.signals)
        self.assertTrue(all(process.poll() is not None for process in self.host.processes.values()))

    def test_app_mode_uses_fresh_container_and_cleans_after_each_fixture(self):
        executor = self.executor("app")
        for name in (*SimulatorSpike.cases, "stdout"):
            with self.subTest(fixture=name):
                SimulatorSpike.check(name, executor.run(SimulatorSpike.request(name)))
                self.assertFalse(self.host.apps)
        self.assertEqual(len(self.host.containers), len(set(self.host.containers)))
        self.assertTrue(all(not path.exists() for path in self.host.containers))

    def test_bundle_cwd_uses_installed_app_location(self):
        result = self.executor("app").run(ExecutionRequest("cwd", cwd_policy="bundle"))
        self.assertEqual(result.stdout, f"{self.bundle / 'cwd.app'}\n".encode())

    def test_invalid_request_is_rejected_before_launch(self):
        requests = [
            ExecutionRequest("stdout", timeout_s=0),
            ExecutionRequest("stdout", timeout_s=float("nan")),
            ExecutionRequest("stdout", argv=("bad\0arg",)),
            ExecutionRequest("stdout", cwd_policy="ambient"),
            ExecutionRequest("stdout", env={"BTRC_TESTHOST_DIR": "/tmp"}),
            ExecutionRequest("stdout", env={"BAD=NAME": "value"}),
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.executor("spawn").run(request)
        self.assertFalse(self.host.processes)

    def test_local_artifact_cannot_claim_ios_target(self):
        executor = IOSSimulatorExecutor(host=self.host)
        with self.assertRaisesRegex(ValueError, "manifest"):
            executor.prepare(self.bundle, SimulatorSpike.target)
        with self.assertRaisesRegex(ValueError, "ios-aarch64-simulator"):
            executor.prepare(self.bundle, "ios-aarch64")

    def test_unrelated_app_bundle_identifier_is_rejected_before_host_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {
                "schema": "btrc.ios-testhost/1",
                "target": SimulatorSpike.target,
                "programs": {"fixture": {"bundle_id": "com.other.application", "spawn": "missing", "app": "missing"}},
            }
            (root / "programs.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "dev.btrc.testhost"):
                IOSSimulatorExecutor(host=self.host).prepare(root, SimulatorSpike.target)
        self.assertFalse(self.host.apps)

    def test_artifact_cannot_escape_bundle(self):
        executor = self.executor("spawn")
        with self.assertRaisesRegex(ValueError, "escapes"):
            executor._artifact("..")

    def test_malformed_process_identity_never_signals_host_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for identity in ("0 0", "1 1", "-1 -1", "invalid", "2"):
                (directory / "process").write_text(identity)
                with self.subTest(identity=identity), self.assertRaises(SimulatorError):
                    self.executor("spawn")._identity(directory)
        self.assertFalse(self.host.signals)

    def test_status_published_during_exit_observation_is_collected(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "process").write_text("12345 12345\n")

            def finish_process():
                (directory / "exit_status").write_text("0\n")
                return 0

            executor = IOSSimulatorExecutor(host=SimpleNamespace(alive=lambda _pid: False))
            timed_out, identity, _latency = executor._wait(
                directory, 0.1, SimpleNamespace(poll=finish_process), launched_at=time.monotonic()
            )
            self.assertFalse(timed_out)
            self.assertEqual(identity, (12345, True))

    def test_spawn_execution_budget_starts_after_delayed_child_identity(self):
        self.host = DelayedProcessHost(self.root, delay=1)
        result = self.executor("spawn").run(SimulatorSpike.request("timeout"))
        SimulatorSpike.check("timeout", result)
        pid = int(self.host.child_file.read_text())
        self.assertNotIn(pid, self.host.processes)  # Launcher and child really differ.
        self.assertFalse(self.host.alive(pid))
        self.assertTrue(all(process.poll() is not None for process in self.host.processes.values()))
        self.assertGreaterEqual(result.provenance["cold_launch_s"], 1)
        self.assertIn(signal.SIGKILL, self.host.signals)

    def test_launch_deadline_cleans_identity_published_during_cleanup_grace(self):
        self.host = DelayedProcessHost(self.root, delay=0.2)
        executor = self.executor("spawn")
        executor.launch_timeout_s = 0.05
        with self.assertRaisesRegex(SimulatorError, "launch deadline"):
            executor.run(SimulatorSpike.request("stdout"))
        pid = int(self.host.child_file.read_text())
        self.assertFalse(self.host.alive(pid))
        self.assertTrue(all(process.poll() is not None for process in self.host.processes.values()))
        self.assertEqual(self.host.child_file.with_suffix(".stdout").read_bytes(), b"")

    def test_spawn_launcher_diagnostics_survive_failed_execution(self):
        from unittest.mock import patch

        def fail(executable, argv, env):
            process = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.stderr.write('simctl diagnostic'); sys.exit(7)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self.host.processes[process.pid] = process
            return process

        with (
            patch.object(self.host, "spawn", side_effect=fail),
            self.assertRaisesRegex(SimulatorError, "without a test-host result") as caught,
        ):
            self.executor("spawn").run(ExecutionRequest("stdout"))
        self.assertIn("simctl diagnostic", " ".join(caught.exception.__notes__))

    def test_reused_app_container_is_rejected_by_persistent_marker(self):
        from unittest.mock import patch

        original = self.host.command
        kept = {}

        def retain_container(*args, **kwargs):
            if args[0] == "uninstall":
                kept.update(self.host.apps.pop(args[2]))
                return subprocess.CompletedProcess(args, 0, b"", b"")
            result = original(*args, **kwargs)
            if args[0] == "install" and kept:
                bundle_id = f"dev.btrc.testhost.{Path(args[2]).stem}"
                self.host.apps[bundle_id]["data"] = kept["data"]
            return result

        with patch.object(self.host, "command", side_effect=retain_container):
            executor = self.executor("app")
            executor.run(ExecutionRequest("stdout"))
            with self.assertRaisesRegex(SimulatorError, "data survived reinstall"):
                executor.run(ExecutionRequest("stdout"))

    def test_app_cleanup_preserves_execution_error_and_attempts_uninstall(self):
        from unittest.mock import patch

        executor = self.executor("app")
        with (
            patch.object(executor, "_wait", side_effect=SimulatorError("original execution error")),
            patch.object(self.host, "terminate_app", side_effect=SimulatorError("terminate failed")),
            self.assertRaisesRegex(SimulatorError, "original execution error") as caught,
        ):
            executor.run(ExecutionRequest("stdout"))
        self.assertFalse(self.host.apps)
        self.assertIn("terminate failed", " ".join(caught.exception.__notes__))

    def test_fixture_checks_survive_python_optimization(self):
        code = (
            "from types import SimpleNamespace; "
            "from tools.target_hosts.ios.spike import SimulatorSpike; "
            "SimulatorSpike.check('stdout', SimpleNamespace(stdout=b'wrong'))"
        )
        result = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"stdout mismatch", result.stderr)

    def test_malformed_identity_after_launcher_exit_still_reaps_launcher(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        executor = self.executor("spawn")
        launcher = SimpleNamespace(poll=lambda: 0)
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(executor, "_identity", side_effect=[None, SimulatorError("malformed late identity")]),
            patch.object(self.host, "stop_launcher", return_value=(b"", b"")) as stop,
            self.assertRaises(ExceptionGroup) as caught,
        ):
            executor._cleanup_spawn(Path(temporary), launcher)
        stop.assert_called_once_with(launcher)
        self.assertEqual(str(caught.exception.exceptions[0]), "malformed late identity")

    def test_launcher_cleanup_bounds_both_waits_and_handles_exit_race(self):
        from unittest.mock import Mock, patch

        process = Mock(pid=12345)
        process.communicate.side_effect = [subprocess.TimeoutExpired("simctl", 2), (b"out", b"err")]
        with patch("tools.target_hosts.ios.simhost.os.killpg", side_effect=ProcessLookupError):
            self.assertEqual(IOSSimulatorHost.stop_launcher(process), (b"out", b"err"))
        self.assertEqual([call.kwargs for call in process.communicate.call_args_list], [{"timeout": 2}, {"timeout": 3}])
        process.communicate.side_effect = subprocess.TimeoutExpired("simctl", 3)
        with (
            patch("tools.target_hosts.ios.simhost.os.killpg"),
            self.assertRaisesRegex(SimulatorError, "did not drain/reap"),
        ):
            IOSSimulatorHost.stop_launcher(process)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_real_host_spawn_builds_child_environment_and_separate_client_session(self):
        from unittest.mock import patch

        host = IOSSimulatorHost()
        host.udid = "test-device"
        with patch("tools.target_hosts.ios.simhost.subprocess.Popen") as launch:
            host.spawn(Path("/fixture"), ("one argument",), {"VALUE": "data"})
        args, kwargs = launch.call_args
        self.assertEqual(args[0], ["xcrun", "simctl", "spawn", "test-device", "/fixture", "one argument"])
        self.assertEqual(kwargs["env"]["SIMCTL_CHILD_VALUE"], "data")
        self.assertTrue(kwargs["start_new_session"])


class SimulatorInventoryTests(unittest.TestCase):
    def test_diagnostics_preserve_partial_output_and_continue_after_failure(self):
        calls = []

        def runner(command, **options):
            calls.append(command)
            self.assertEqual(options["timeout"], 10)
            if command[0] == "xcrun":
                raise subprocess.TimeoutExpired(command, 10, output=b"partial inventory", stderr=b"stalled")
            if command[0] == "/usr/bin/vm_stat":
                raise OSError("probe unavailable")
            return subprocess.CompletedProcess(command, 0, stdout=b"observation", stderr=b"")

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            IOSSimulatorHost(runner=runner).diagnose(output)
            rows = json.loads((output / "commands.json").read_text())
            self.assertEqual(len(calls), 5)
            self.assertEqual((output / "devices.stdout").read_bytes(), b"partial inventory")
            self.assertEqual((output / "devices.stderr").read_bytes(), b"stalled")
            self.assertIn("TimeoutExpired", rows["devices"]["error"])
            self.assertIn("probe unavailable", rows["memory"]["error"])
            self.assertEqual(rows["services"]["returncode"], 0)
            self.assertFalse(any(word in command for command in calls for word in ("boot", "shutdown", "erase")))

    def test_failed_spike_retains_stage_cleanup_notes_and_diagnostic_failure(self):
        from unittest.mock import Mock, patch

        executor = Mock()
        failure = SimulatorError("identity deadline")
        failure.add_note("original launcher diagnostic")
        executor.run.side_effect = failure
        executor.close.side_effect = SimulatorError("shutdown failed")
        executor.host.diagnose.side_effect = OSError("diagnostic disk failure")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                patch("tools.target_hosts.ios.spike.IOSSimulatorExecutor", return_value=executor),
                self.assertRaises(SimulatorError) as caught,
            ):
                SimulatorSpike.run(output, output, device_class="iphone", mode="spawn")
            self.assertIs(caught.exception, failure)
            summary = json.loads((output / "iphone-spawn.json").read_text())
            self.assertFalse(summary["complete"])
            self.assertEqual(summary["results"], [])
            self.assertEqual(summary["failed_stage"], "execute")
            self.assertEqual(summary["failed_invocation"], "stdout")
            self.assertIn("original launcher diagnostic", summary["error_notes"])
            self.assertTrue(any("diagnostic disk failure" in note for note in summary["error_notes"]))
            self.assertIn("shutdown failed", summary["cleanup_error"])
            executor.close.assert_called_once()

    @staticmethod
    def inventory():
        return {
            "runtimes": [
                {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-17-0", "version": "17.0", "isAvailable": True},
                {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-0", "version": "27.0", "isAvailable": False},
                {"identifier": "com.apple.CoreSimulator.SimRuntime.tvOS-28-0", "version": "28.0", "isAvailable": True},
            ],
            "devices": {},
            "devicetypes": [
                {"name": "iPhone fixture", "identifier": "phone"},
                {"name": "iPad fixture", "identifier": "pad"},
            ],
        }

    def test_phone_and_pad_select_available_ios_runtime_and_wait_for_boot(self):
        for device_class, device_type in (("iphone", "phone"), ("ipad", "pad")):
            calls = []

            def runner(command, calls=calls, **_kwargs):
                calls.append(command)
                if command[-2:] == ["list", "-j"]:
                    output = json.dumps(self.inventory()).encode()
                elif command[2] == "create":
                    output = b"test-udid\n"
                else:
                    output = b""
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

            host = IOSSimulatorHost(device_class, runner=runner)
            host.prepare()
            self.assertIn(
                [
                    "xcrun",
                    "simctl",
                    "create",
                    f"btrc-host-{device_class}",
                    device_type,
                    "com.apple.CoreSimulator.SimRuntime.iOS-17-0",
                ],
                calls,
            )
            self.assertIn(["xcrun", "simctl", "bootstatus", "test-udid", "-b"], calls)
            host.close()
            self.assertIn(["xcrun", "simctl", "shutdown", "test-udid"], calls)
            self.assertFalse(any("erase" in call for call in calls))

    def test_missing_runtime_reports_unavailable_instead_of_substitution(self):
        inventory = self.inventory()
        inventory["runtimes"] = []

        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(inventory).encode(), stderr=b"")

        with self.assertRaisesRegex(SimulatorError, "No available iOS"):
            IOSSimulatorHost(runner=runner).prepare()

    def test_reuses_matching_booted_device_without_shutting_it_down(self):
        inventory = self.inventory()
        inventory["devices"] = {
            "com.apple.CoreSimulator.SimRuntime.iOS-17-0": [
                {
                    "name": "btrc-host-ipad",
                    "udid": "existing",
                    "isAvailable": True,
                    "state": "Booted",
                    "deviceTypeIdentifier": "pad",
                }
            ]
        }
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            output = json.dumps(inventory).encode() if command[-2:] == ["list", "-j"] else b""
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

        host = IOSSimulatorHost("ipad", runner=runner)
        host.prepare()
        host.close()
        self.assertEqual(len(calls), 2)
        inventory["devices"]["com.apple.CoreSimulator.SimRuntime.iOS-17-0"][0]["deviceTypeIdentifier"] = "phone"
        with self.assertRaisesRegex(SimulatorError, "device class"):
            IOSSimulatorHost("ipad", runner=runner).prepare()

    def test_runtime_supported_device_types_excludes_newer_incompatible_type(self):
        inventory = self.inventory()
        inventory["runtimes"][0]["supportedDeviceTypes"] = [{"identifier": "phone"}]
        inventory["devicetypes"].append({"name": "iPhone incompatible", "identifier": "unsupported"})
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            output = json.dumps(inventory).encode() if command[-2:] == ["list", "-j"] else b"new-device\n"
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

        host = IOSSimulatorHost("iphone", runner=runner)
        host.prepare()
        create = next(command for command in calls if command[2] == "create")
        self.assertEqual(create[4], "phone")
        host.close()

    def test_child_environment_does_not_replay_previous_request(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {"SIMCTL_CHILD_OLD": "stale", "HOST_ONLY": "retained"}):
            values = IOSSimulatorHost.child_environment({"CURRENT": "new"})
        self.assertNotIn("SIMCTL_CHILD_OLD", values)
        self.assertEqual(values["SIMCTL_CHILD_CURRENT"], "new")
        self.assertEqual(values["HOST_ONLY"], "retained")


if __name__ == "__main__":
    unittest.main()
