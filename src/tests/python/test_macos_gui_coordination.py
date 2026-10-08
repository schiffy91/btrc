"""Real process exclusion for the AppKit pytest lease; no GUI/compiler is launched."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# Execution inventory: these bodies launch actual AppKit applications/windows.
# Compile-only imports, headless GPU devices and text rasters are intentionally absent.
APPKIT_TESTS = {
    "test_native_gui_appkit.py": {
        "test_macos_gpu_surface_owner_resize_and_close",
        "test_native_window_keyboard_monitor",
        "test_macos_panel_and_progress_controls",
        "test_portable_native_example_edit_apply_and_quit",
        "test_macos_view_capture_owns_native_pixels",
        "test_native_capture_composes_with_image_io",
    },
    "test_native_app_runtime.py": {
        "test_btrc_directory_picker_appkit",
        "test_btrc_text_field_and_scroll_view_appkit",
    },
    "test_native_pointer_runtime.py": {"test_native_pointer_routing"},
    "test_native_control_sizing_runtime.py": {"test_native_control_sizing"},
    "test_native_tray_runtime.py": {"test_native_tray_lifecycle"},
    "test_native_webgpu_imports.py": {"test_native_gpu_child_renders_and_reads_pixels"},
    "test_native_objective_c_delegates.py": {
        "test_stored_objective_c_window_delegate",
        "test_stored_objective_c_button_action",
    },
    "test_native_ui_shell_macos.py": {"test_macos_native_shell"},
}


class GuiProcesses:
    def __init__(self, root):
        self.root = root
        self.processes = {}
        (root / "conftest.py").write_text(
            "import hashlib, json, os, sys\nfrom pathlib import Path\nfrom types import SimpleNamespace\nimport pytest\n"
            "from src.tests import conftest as owner\n"
            "gui_lock_path = None\n"
            "owner_path = Path(owner.__file__).resolve()\n"
            "assert owner_path == Path(os.environ['LEASE_OWNER_PATH']), 'Wrong GUI fixture owner'\n"
            "owner_sha = hashlib.sha256(owner_path.read_bytes()).hexdigest()\n"
            "assert owner_sha == os.environ['LEASE_OWNER_SHA256'], 'Changed GUI fixture owner'\n"
            "Path(os.environ['LEASE_ROLE'] + '.owner.json').write_text(json.dumps({'path': str(owner_path), 'sha256': owner_sha}))\n"
            "pytest_plugins = ['src.tests.conftest']\n"
            # Replace only the fixture owner's view of the platform. The real
            # kernel lock is exercised on POSIX, including Linux CI; no AppKit claim.
            "owner.sys = SimpleNamespace(**(vars(sys) | {'platform': os.environ['LEASE_PLATFORM']}))\n"
            # Observe actual kernel contention. Setup readiness alone cannot
            # prove that a contender has reached the lease on a busy runner.
            "if os.name == 'posix':\n"
            "    import fcntl\n"
            "    original_flock = fcntl.flock\n"
            "    def observed_flock(*args, **kwargs):\n"
            "        try:\n"
            "            return original_flock(*args, **kwargs)\n"
            "        except BlockingIOError:\n"
            "            expected = gui_lock_path\n"
            "            if expected is not None and expected.exists() and os.path.samestat(os.fstat(args[0]), expected.stat()):\n"
            "                Path(os.environ['LEASE_ROLE'] + '.blocked').write_text(str(expected.resolve()))\n"
            "            raise\n"
            "    fcntl.flock = observed_flock\n"
            "if os.environ.get('LEASE_TIMEOUT'):\n"
            "    original = owner._exclusive\n"
            "    def bounded(path, **kwargs):\n"
            "        return original(path, **(kwargs | {'timeout': float(os.environ['LEASE_TIMEOUT'])}))\n"
            "    owner._exclusive = bounded\n"
            "def pytest_configure(config):\n"
            "    global gui_lock_path\n"
            "    gui_lock_path = config.cache.mkdir('macos-gui') / 'execution.lock'\n"
            "    assert config.inipath.resolve() == Path(os.environ['LEASE_CONFIG']), 'Wrong GUI pytest configuration'\n"
            "    assert Path(config.getini('cache_dir')).resolve() == Path(os.environ['LEASE_CACHE']), 'Wrong GUI pytest cache'\n"
            "    config.addinivalue_line('markers', 'macos_gui: shared AppKit session')\n"
            "@pytest.hookimpl(tryfirst=True)\n"
            "def pytest_runtest_setup(item):\n"
            "    Path(os.environ['LEASE_ROLE'] + '.ready').touch()\n"
        )
        (root / "test_process.py").write_text(
            "import os, time\nfrom pathlib import Path\nimport pytest\n"
            "def journey():\n"
            "    role = os.environ['LEASE_ROLE']\n"
            "    Path(role + '.entered').touch()\n"
            "    if role == 'holder':\n"
            "        deadline = time.monotonic() + 20\n"
            "        while not Path('release').exists():\n"
            "            assert time.monotonic() < deadline, 'parent did not release holder'\n"
            "            time.sleep(0.01)\n"
            "        assert os.environ.get('LEASE_FAIL') != '1', 'deliberate holder failure'\n"
            "@pytest.fixture\ndef journey_fixture():\n"
            "    role = os.environ['LEASE_ROLE']\n"
            "    Path(role + '.setup').touch()\n"
            "    yield\n"
            "    Path(role + '.teardown').touch()\n"
            "    if os.environ.get('LEASE_TEARDOWN') == '1':\n"
            "        deadline = time.monotonic() + 20\n"
            "        while not Path('teardown.release').exists():\n"
            "            assert time.monotonic() < deadline, 'parent did not release teardown'\n"
            "            time.sleep(0.01)\n"
            "@pytest.mark.macos_gui\ndef test_gui(journey_fixture):\n    journey()\n"
            "def test_ordinary(journey_fixture):\n    journey()\n"
        )

    def start(self, role, *, marked=True, fail=False, platform=None, timeout=None, teardown=False):
        environment = os.environ | {
            "PYTHONPATH": str(REPO),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_ADDOPTS": "",
            "LEASE_PLATFORM": platform or ("darwin" if os.name != "nt" else sys.platform),
            "LEASE_CONFIG": str((REPO / "pyproject.toml").resolve()),
            "LEASE_CACHE": str((self.root / ".pytest_cache").resolve()),
            "LEASE_OWNER_PATH": str((REPO / "src/tests/conftest.py").resolve()),
            "LEASE_OWNER_SHA256": hashlib.sha256((REPO / "src/tests/conftest.py").read_bytes()).hexdigest(),
            "LEASE_ROLE": role,
            "LEASE_FAIL": "1" if fail else "0",
            "LEASE_TIMEOUT": "" if timeout is None else str(timeout),
            "LEASE_TEARDOWN": "1" if teardown else "0",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-c",
                environment["LEASE_CONFIG"],
                "--rootdir=" + str(self.root),
                "--confcutdir=" + str(self.root),
                "-o",
                "cache_dir=" + environment["LEASE_CACHE"],
                "test_process.py::" + ("test_gui" if marked else "test_ordinary"),
            ],
            cwd=self.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.processes[role] = process
        return process

    def wait(self, role, event):
        deadline = time.monotonic() + 15
        while not (self.root / f"{role}.{event}").exists():
            process = self.processes[role]
            assert process.poll() is None, process.communicate()[0]
            assert time.monotonic() < deadline, f"{role} did not reach {event}"
            time.sleep(0.01)

    def wait_for_contention_or_entry(self, role):
        """Wait for real lock contention or the body, never just process setup."""
        deadline = time.monotonic() + 15
        while not any((self.root / f"{role}.{event}").exists() for event in ("blocked", "entered")):
            process = self.processes[role]
            assert process.poll() is None, process.communicate()[0]
            assert time.monotonic() < deadline, f"{role} reached neither kernel contention nor its body"
            time.sleep(0.01)

    def finish(self, role, expected=0):
        process = self.processes[role]
        output = process.communicate(timeout=15)[0]
        assert process.returncode == expected, output
        return output

    def release(self):
        (self.root / "release").touch()

    def close(self):
        self.release()
        (self.root / "teardown.release").touch()
        for process in self.processes.values():
            if os.name == "posix":
                # Retire the owned pytest group, including any remaining children.
                # Kill its process group even if the outer leader has exited.
                # Reap an exited leader before signalling its remaining group.
                # Darwin may report EPERM for an unreaped zombie-only group.
                process.poll()
                with suppress(ProcessLookupError):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except PermissionError:
                        # A leader can exit between poll and killpg. Retry only
                        # after proving its exit; never ignore a live denial or
                        # assume that its descendants have also exited.
                        if process.poll() is None:
                            raise
                        os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
            process.communicate(timeout=15)


@pytest.fixture
def gui_processes(tmp_path):
    processes = GuiProcesses(tmp_path)
    try:
        yield processes
    finally:
        processes.close()


def test_macos_gui_lease_excludes_other_gui_workers_but_not_ordinary_work(gui_processes):
    processes = gui_processes
    processes.start("holder")
    processes.wait("holder", "entered")
    processes.start("contender")
    processes.wait("contender", "ready")
    processes.wait_for_contention_or_entry("contender")
    processes.start("ordinary", marked=False)
    processes.wait("ordinary", "entered")
    processes.finish("ordinary")
    if os.name == "nt":
        # The macOS-only fixture must leave Windows execution untouched.
        processes.wait("contender", "entered")
    else:
        assert not (processes.root / "contender.entered").exists(), "AppKit workers overlapped"
        assert not (processes.root / "contender.setup").exists(), "AppKit fixture setup overlapped"
    processes.release()
    processes.finish("holder")
    processes.wait("contender", "entered")
    processes.finish("contender")


@pytest.mark.parametrize("release", ["exception", "process-death"])
def test_macos_gui_lease_releases_after_failed_or_dead_owner(gui_processes, release):
    processes = gui_processes
    holder = processes.start("holder", fail=True)
    processes.wait("holder", "entered")
    processes.start("contender")
    processes.wait("contender", "ready")
    processes.wait_for_contention_or_entry("contender")
    if release == "process-death":
        holder.kill()
        holder.communicate(timeout=15)
        assert holder.returncode != 0
    else:
        processes.release()
        assert "deliberate holder failure" in processes.finish("holder", expected=1)
    processes.wait("contender", "entered")
    processes.finish("contender")


def test_macos_gui_marker_does_not_serialize_non_macos_workers(gui_processes):
    processes = gui_processes
    processes.start("holder", platform="linux")
    processes.wait("holder", "entered")
    processes.start("contender", platform="linux")
    processes.wait("contender", "entered")
    processes.finish("contender")
    processes.release()
    processes.finish("holder")


def test_all_known_appkit_execution_tests_claim_the_gui_session(tmp_path):
    records = tmp_path / "collection.json"
    (tmp_path / "gui_collection.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "def pytest_collection_modifyitems(items):\n"
        "    records = [(item.path.name, item.originalname, "
        "item.get_closest_marker('macos_gui') is not None) for item in items]\n"
        f"    Path({str(records)!r}).write_text(json.dumps(records))\n"
    )
    environment = os.environ | {
        "PYTHONPATH": os.pathsep.join([str(tmp_path), str(REPO)]),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "",
    }
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(REPO / "pyproject.toml"),
            "--collect-only",
            "-q",
            "-p",
            "gui_collection",
            *(str(REPO / "src/tests/python" / filename) for filename in APPKIT_TESTS),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    observed = json.loads(records.read_text())
    for filename, expected in APPKIT_TESTS.items():
        for name in expected:
            cases = [marked for file, function, marked in observed if file == filename and function == name]
            assert cases, f"review removed/renamed AppKit execution: {filename}::{name}"
            assert all(cases), f"uncoordinated AppKit execution: {filename}::{name}"


def test_macos_gui_lease_covers_fixture_teardown(gui_processes):
    processes = gui_processes
    processes.start("holder", teardown=True)
    processes.wait("holder", "entered")
    processes.release()
    processes.wait("holder", "teardown")
    processes.start("contender")
    processes.wait("contender", "ready")
    processes.wait_for_contention_or_entry("contender")
    processes.start("ordinary", marked=False)
    processes.wait("ordinary", "entered")
    processes.finish("ordinary")
    if os.name != "nt":
        assert not (processes.root / "contender.setup").exists(), "AppKit teardown overlaps next setup"
    (processes.root / "teardown.release").touch()
    processes.finish("holder")
    processes.wait("contender", "entered")
    processes.finish("contender")


def test_macos_gui_lease_timeout_reports_holder_and_keeps_it_exclusive(gui_processes):
    processes = gui_processes
    holder = processes.start("holder")
    processes.wait("holder", "entered")
    processes.start("contender", timeout=0.2)
    if os.name == "nt":
        processes.wait("contender", "entered")
        processes.finish("contender")
    else:
        output = processes.finish("contender", expected=1)
        assert "Timed out after 0.2s waiting for" in output
        assert "execution.lock" in output
        assert '"pid": ' + str(holder.pid) in output
        assert "test_process.py::test_gui" in output
        assert not (processes.root / "contender.setup").exists()
    assert holder.poll() is None
    processes.release()
    processes.finish("holder")
    processes.start("successor")
    processes.wait("successor", "entered")
    processes.finish("successor")
