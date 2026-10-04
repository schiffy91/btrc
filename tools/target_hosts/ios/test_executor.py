"""Linux process tests for executor mechanics; never simulator evidence."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
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
        process.communicate(timeout=3)

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


class ExecutorProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="btrc-ios-local-test-")
        cls.root = Path(cls.temporary.name)
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


class SimulatorInventoryTests(unittest.TestCase):
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

    def test_child_environment_does_not_replay_previous_request(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {"SIMCTL_CHILD_OLD": "stale", "HOST_ONLY": "retained"}):
            values = IOSSimulatorHost.child_environment({"CURRENT": "new"})
        self.assertNotIn("SIMCTL_CHILD_OLD", values)
        self.assertEqual(values["SIMCTL_CHILD_CURRENT"], "new")
        self.assertEqual(values["HOST_ONLY"], "retained")


if __name__ == "__main__":
    unittest.main()
