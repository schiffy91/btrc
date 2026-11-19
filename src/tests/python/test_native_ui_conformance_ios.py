"""The GUI conformance suite's iOS and iPadOS rows: built on a Mac, run on simulators.

The suite (src/tests/native/gui/conformance) is compiled for the simulator
through both compilers, plain and sanitized, and linked, through its native
plan, into an app: the shim provider's UIKit entry (src/stdlib/GUI/IOS),
the suite's own probe (conformance/probes/ios) and wgpu-native's pinned
static library (tools/target_hosts/ios/gui.py; nothing fetched but that
pinned archive). Each case then runs as its own process of the installed
app on one iPhone and one iPad simulator. The probe's input is real: the
driver starts the host's injector for the device
(tools/target_hosts/ios/simhid.m), and a touch, a key and a wheel reach the
app through the simulated device's own HID service.

On the iPad the cases also run with the program's windows in a second scene
of the app. Simulator results are never physical-device evidence, and the
installed runtime is not the iOS 17 floor, which the build targets.

The rows boot simulators and send them input, so they run where they are
asked for: BTRC_IOS_UI_DEVICES names the device classes ("iphone,ipad").
BTRC_IOS_UI_EVIDENCE names a directory that receives every case's output.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_bindings import NativeBindingPackage
from src.tests.python import test_native_ui_shell_windows as shell
from src.tests.python.native_ui_shell_fixtures import transpile
from tools.native_plan import NativePlanBuilder
from tools.target_hosts.ios.gui import GUIAppBuilder, GUIAppRunner
from tools.target_hosts.ios.simhost import AppleEnvironment, IOSSimulatorHost

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "src/tests/native/gui/conformance"
CASES = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))["case"]
NAMES = [case["name"] for case in CASES]
NEEDS = {case["name"]: case["needs"] for case in CASES if "needs" in case}
# What the UIKit provider has of what a case may need: a web view and a probe
# that answers a modal, and no FreeType (the iOS SDK does not carry it).
HAS = {"web", "modal"}
APPLICABLE = [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS]
TARGET = "ios-aarch64-simulator"
SIMULATOR_BOUND = "requires a Mac with Xcode and iOS simulators: set BTRC_IOS_UI_DEVICES (iphone,ipad)"
# One worker owns the simulator: a device is booted, installed on and sent input by one process.
pytestmark = pytest.mark.xdist_group(name="ios_ui")
# One device of each class, made for this suite: a phone wide enough for the
# suite's windows, and a tablet whose system gives an app more than one scene.
DEVICES = {"iphone": ("btrc-ui-iphone", "iPhone 17 Pro Max"), "ipad": ("btrc-ui-ipad", "iPad Air 11-inch (M4)")}
FRONTENDS = sorted(shell.FRONTENDS)
SANITIZERS = ("-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer")
SIMHID = REPO / "tools/target_hosts/ios/simhid.m"


def xcrun(*arguments, timeout=300):
    return subprocess.run(
        [str(AppleEnvironment.XCRUN), *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=AppleEnvironment.variables(),
    )


class Simulators:
    """The suite's apps and the one simulator they run on at a time."""

    def __init__(self, directories):
        self.directories = directories
        self.base = directories.mktemp("ios-conformance")
        self.bundles = {}
        self.runners = {}
        self.host = None
        self.injector = None
        self.port = 0
        self.sdk_path = None

    def sdk(self):
        if self.sdk_path is None:
            found = xcrun("--sdk", "iphonesimulator", "--show-sdk-path", timeout=60)
            self.sdk_path = found.stdout.strip() if found.returncode == 0 else ""
        return self.sdk_path

    def wgpu_native(self):
        """The simulator's pinned wgpu-native archive: its headers, and its static library alone."""
        root = self.base / "wgpu-native"
        if not root.is_dir():
            with zipfile.ZipFile(shell.pinned_archive("ios-simulator-arm64")) as bundle:
                bundle.extractall(root)
            # Beside its shared library the linker would take that one, which an app would have to carry.
            (root / "static").mkdir()
            shutil.move(root / "lib/libwgpu_native.a", root / "static/libwgpu_native.a")
        return root / "include/webgpu", root / "static"

    def runtime(self, name):
        """A sanitizer's runtime for the simulator, which an app carries beside its program."""
        clang = xcrun("--sdk", "iphonesimulator", "--find", "clang", timeout=60).stdout.strip()
        found = sorted(Path(clang).parents[1].glob(f"lib/clang/*/lib/darwin/libclang_rt.{name}_iossim_dynamic.dylib"))
        assert found, f"Xcode has no {name} runtime for the simulator"
        return found[-1]

    def bundle(self, frontend, sanitized, request):
        key = (frontend, sanitized)
        if key in self.bundles:
            if isinstance(self.bundles[key], BaseException):
                # One failure to build is every case's: say it once each, without building again.
                raise self.bundles[key]
            return self.bundles[key]
        try:
            self.bundles[key] = self.build(frontend, sanitized, request)
        except BaseException as error:
            self.bundles[key] = error
            raise
        return self.bundles[key]

    def build(self, frontend, sanitized, request):
        NativeBindingPackage.require_reader()
        mode = "sanitized" if sanitized else "plain"
        work = self.base / f"{frontend}-{mode}"
        work.mkdir()
        include, libraries = self.wgpu_native()
        row = PackageTarget.parse(TARGET).row
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv("BTRC_NATIVE_TARGET", row.triple)
            environment.setenv("BTRC_NATIVE_SYSROOT", self.sdk())
            # An app has no pkg-config search path: the header reader and the
            # compiler find wgpu-native's headers here, the linker its library below.
            environment.setenv("C_INCLUDE_PATH", str(include))
            generated, plan = work / "Suite.c", work / "Suite.json"
            result = transpile(SUITE / "Main.btrc", generated, plan, frontend, request, TARGET)
            assert result.returncode == 0, result.stderr
            assert "warning:" not in result.stderr.lower(), result.stderr
            flags = list(SANITIZERS) if sanitized else []
            program = work / "Suite"
            NativePlanBuilder().build(
                plan_path=plan,
                generated_c=generated,
                output=program,
                optimization=2,
                compile_flags=[f"-I{include}", *flags],
                link_flags=[*GUIAppBuilder.link_flags(libraries), *flags, "-Wl,-rpath,@executable_path/Frameworks"],
            )
        # The address sanitizer's runtime is a library the app carries; the other's is linked in.
        resources = {f"Frameworks/{self.runtime('asan').name}": self.runtime("asan")} if sanitized else {}
        return GUIAppBuilder.package(
            program=program,
            identifier=f"dev.btrc.testhost.conformance.{shell.FRONTENDS[frontend]}-{mode}",
            label=f"BTRC conformance ({shell.FRONTENDS[frontend]}, {mode})",
            output=work / "Conformance.app",
            resources=resources,
        )

    def device(self, device_class):
        """The booted simulator of this class and its injector; the other class's is let go first."""
        if self.host is not None and self.host.device_class == device_class:
            return self.host
        self.close()
        name, model = DEVICES[device_class]
        host = IOSSimulatorHost(device_class, name=name, model=model)
        host.prepare()
        self.host = host
        self.start_injector()
        return host

    def start_injector(self):
        tool = self.base / "simhid"
        if not tool.is_file():
            built = xcrun(
                "clang",
                "-fobjc-arc",
                "-O2",
                "-framework",
                "Foundation",
                "-framework",
                "CoreGraphics",
                str(SIMHID),
                "-o",
                str(tool),
            )
            assert built.returncode == 0, built.stderr
        self.injector = subprocess.Popen(
            [str(tool), self.host.device(), "0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=AppleEnvironment.variables(),
        )
        line = self.injector.stdout.readline()
        assert line.startswith("PORT "), f"simhid did not start: {line}{self.injector.stderr.read()}"
        self.port = int(line.split()[1])
        # A tablet has a pointer, which the injector makes when first asked. What is sent
        # while the system takes the new device in is dropped, so it is made now.
        with socket.create_connection(("127.0.0.1", self.port), timeout=30) as injector:
            injector.sendall(b"HOVER 100 100\n")
            injector.recv(256)
        time.sleep(1.0)

    def runner(self, device_class, frontend, sanitized, request):
        host = self.device(device_class)
        key = (device_class, frontend, sanitized)
        if key not in self.runners:
            bundle = self.bundle(frontend, sanitized, request)
            identifier = (
                f"dev.btrc.testhost.conformance.{shell.FRONTENDS[frontend]}-{'sanitized' if sanitized else 'plain'}"
            )
            runner = GUIAppRunner(host, identifier)
            runner.install(bundle)
            self.runners[key] = (runner, runner.put(SUITE / "web", "web"))
        return self.runners[key]

    def run(self, device_class, frontend, sanitized, request, argument, scene="first"):
        asked = {name.strip() for name in os.environ.get("BTRC_IOS_UI_DEVICES", "").split(",")}
        if sys.platform != "darwin" or device_class not in asked or not self.sdk():
            pytest.skip(SIMULATOR_BOUND)
        runner, web = self.runner(device_class, frontend, sanitized, request)
        environment = {
            "BTRC_UI_PRIVATE_SESSION": "1",
            "BTRC_CONFORMANCE_HID": str(self.port),
            "BTRC_CONFORMANCE_WEB": web,
            "ASAN_OPTIONS": "detect_leaks=0",
            "UBSAN_OPTIONS": "halt_on_error=1",
        }
        if scene != "first":
            environment["BTRC_SHIM_SCENE"] = scene
        # A finger a failed case left down would be down for this one too.
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as injector:
            injector.sendall(b"RELEASE\n")
            assert injector.recv(64).startswith(b"OK"), "simhid could not lift the finger"
        return runner.run([argument], environment, 180)

    def close(self):
        if self.injector is not None:
            self.injector.terminate()
            self.injector.wait(timeout=30)
            self.injector = None
        if self.host is not None:
            for key in [key for key in self.runners if key[0] == self.host.device_class]:
                self.runners.pop(key)[0].uninstall()
            self.host.close()
            self.host = None


@pytest.fixture(scope="module")
def simulators(tmp_path_factory):
    simulators = Simulators(tmp_path_factory)
    yield simulators
    simulators.close()


def check(simulators, request, name, device_class, frontend, sanitized, scene):
    status, stdout, stderr = simulators.run(device_class, frontend, sanitized, request, name, scene)
    mode = "sanitized" if sanitized else "plain"
    where = simulators.host.provenance()
    report = f"{name} on {where['device']}, {where['os_build']}, {scene} scene ({frontend}, {mode})\n{stdout}{stderr}"
    evidence = os.environ.get("BTRC_IOS_UI_EVIDENCE")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        label = f"{device_class}-{scene}-{shell.FRONTENDS[frontend]}-{mode}-{name}.txt"
        (Path(evidence) / label).write_text(report, encoding="utf-8")
    assert status == 0, report
    if scene == "second":
        # The provider says so when the system gave the program a second scene to live in.
        assert "the program's windows live in a second scene (2 connected)" in stderr, report
    assert "ERROR: AddressSanitizer" not in stderr and "runtime error:" not in stderr, report
    assert stdout.splitlines()[-2:] == [f"CASE {name} PASS", "CONFORMANCE ran=1 failed=0"], report


# The last parameter varies slowest: every iPhone row, then every iPad row,
# so that one simulator is booted at a time.
@pytest.mark.parametrize("name", APPLICABLE)
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("device_class", ["iphone", "ipad"])
def test_ios_conformance_case(simulators, request, name, frontend, sanitized, device_class):
    check(simulators, request, name, device_class, frontend, sanitized, "first")


@pytest.mark.parametrize("name", APPLICABLE)
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
def test_ipad_conformance_case_in_a_second_scene(simulators, request, name, frontend, sanitized):
    check(simulators, request, name, "ipad", frontend, sanitized, "second")


def test_the_ios_program_lists_exactly_the_recorded_cases(simulators, request):
    status, stdout, stderr = simulators.run("iphone", "python", False, request, "--list")
    assert status == 0, stderr
    assert sorted(stdout.split()) == sorted(NAMES)
