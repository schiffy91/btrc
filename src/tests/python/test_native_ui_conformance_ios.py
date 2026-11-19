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
of the app, and in a scene made as narrow as a phone's (a compact width,
which is what a split view gives an app): the probe drags the corner of the
scene's window, as a person would. Simulator results are never
physical-device evidence, and the installed runtime is not the iOS 17 floor,
which the build targets.

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
# that answers a modal, and no FreeType (the iOS SDK does not carry it). A
# tablet has a pointer and its wheel; a phone has neither.
HAS = {"iphone": {"web", "modal"}, "ipad": {"web", "modal", "wheel"}}
TARGET = "ios-aarch64-simulator"
SIMULATOR_BOUND = "requires a Mac with Xcode and iOS simulators: set BTRC_IOS_UI_DEVICES (iphone,ipad)"
# One worker owns the simulator: a device is booted, installed on and sent input by one process.
pytestmark = pytest.mark.xdist_group(name="ios_ui")
# One device of each class, made for this suite: a phone wide enough for the
# suite's windows, and a tablet whose system gives an app more than one scene.
DEVICES = {"iphone": ("btrc-ui-iphone", "iPhone 17 Pro Max"), "ipad": ("btrc-ui-ipad", "iPad Air 11-inch (M4)")}
FRONTENDS = sorted(shell.FRONTENDS)
MODES = {False: "plain", True: "sanitized"}
SANITIZERS = ("-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer")
SIMHID = REPO / "tools/target_hosts/ios/simhid.m"
# Cases whose windows a person is shown and sends input to: the probe arranges the scene for each of them.
SHOWN_IN_A_SCENE = {"window.state", "view.arrange", "button.click", "view.pointer", "slider.dragging", "mix.order"}


def applicable(device_class):
    return [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS[device_class]]


def rows():
    """Every case of every device class it applies to, the phone's first: one simulator is booted at a time."""
    return [
        pytest.param(name, device_class, id=f"{name}-{device_class}")
        for device_class in ("iphone", "ipad")
        for name in applicable(device_class)
    ]


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
        self.base = directories.mktemp("ios-conformance")
        self.programs = {}
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

    def program(self, frontend, sanitized, request):
        key = (frontend, sanitized)
        if key in self.programs:
            if isinstance(self.programs[key], BaseException):
                # One failure to build is every case's: say it once each, without building again.
                raise self.programs[key]
            return self.programs[key]
        try:
            self.programs[key] = self.build(frontend, sanitized, request)
        except BaseException as error:
            self.programs[key] = error
            raise
        return self.programs[key]

    def build(self, frontend, sanitized, request):
        NativeBindingPackage.require_reader()
        work = self.base / f"{frontend}-{MODES[sanitized]}"
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
        return program

    @staticmethod
    def identifier(frontend, sanitized, scene):
        """One app a compiler, mode and kind of scene: the system keeps a scene's size by the app it belongs to."""
        suffix = "-compact" if scene == "compact" else ""
        return f"dev.btrc.testhost.conformance.{shell.FRONTENDS[frontend]}-{MODES[sanitized]}{suffix}"

    def bundle(self, frontend, sanitized, scene, request):
        program = self.program(frontend, sanitized, request)
        identifier = self.identifier(frontend, sanitized, scene)
        # The address sanitizer's runtime is a library the app carries; the other's is linked in.
        resources = {f"Frameworks/{self.runtime('asan').name}": self.runtime("asan")} if sanitized else {}
        return GUIAppBuilder.package(
            program=program,
            identifier=identifier,
            label=f"BTRC conformance ({shell.FRONTENDS[frontend]}, {MODES[sanitized]})",
            output=program.parent / f"{identifier.rsplit('.', 1)[1]}.app",
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
            frameworks = ["-framework", "Foundation", "-framework", "CoreGraphics"]
            built = xcrun("clang", "-fobjc-arc", "-O2", *frameworks, str(SIMHID), "-o", str(tool))
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
        self.inject("HOVER 100 100")
        time.sleep(1.0)

    def inject(self, command):
        """One request of the injector; its answer."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=30) as injector:
            injector.sendall(command.encode() + b"\n")
            return injector.recv(256).decode()

    def runner(self, device_class, frontend, sanitized, scene, request):
        host = self.device(device_class)
        key = (device_class, frontend, sanitized, scene == "compact")
        if key not in self.runners:
            runner = GUIAppRunner(host, self.identifier(frontend, sanitized, scene))
            runner.install(self.bundle(frontend, sanitized, scene, request))
            self.runners[key] = (runner, runner.put(SUITE / "web", "web"))
        return self.runners[key]

    def run(self, device_class, frontend, sanitized, request, argument, scene="first"):
        asked = {name.strip() for name in os.environ.get("BTRC_IOS_UI_DEVICES", "").split(",")}
        if sys.platform != "darwin" or device_class not in asked or not self.sdk():
            pytest.skip(SIMULATOR_BOUND)
        runner, web = self.runner(device_class, frontend, sanitized, scene, request)
        environment = {
            "BTRC_UI_PRIVATE_SESSION": "1",
            "BTRC_CONFORMANCE_HID": str(self.port),
            "BTRC_CONFORMANCE_WEB": web,
            "ASAN_OPTIONS": "detect_leaks=0",
            "UBSAN_OPTIONS": "halt_on_error=1",
        }
        if scene == "second":
            environment["BTRC_SHIM_SCENE"] = "second"
        if device_class == "ipad":
            # A tablet keeps the size a scene was left at: every row says which it runs in.
            environment["BTRC_CONFORMANCE_SCENE"] = "compact" if scene == "compact" else "whole"
        # A finger a failed case left down would be down for this one too.
        assert self.inject("RELEASE").startswith("OK"), "simhid could not lift the finger"
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
    where = simulators.host.provenance()
    report = f"{name} on {where['device']}, {where['os_build']}, {scene} scene ({frontend}, {MODES[sanitized]})\n"
    report += stdout + stderr
    evidence = os.environ.get("BTRC_IOS_UI_EVIDENCE")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        label = f"{device_class}-{scene}-{shell.FRONTENDS[frontend]}-{MODES[sanitized]}-{name}.txt"
        (Path(evidence) / label).write_text(report, encoding="utf-8")
    assert status == 0, report
    assert "ERROR: AddressSanitizer" not in stderr and "runtime error:" not in stderr, report
    assert stdout.splitlines()[-2:] == [f"CASE {name} PASS", "CONFORMANCE ran=1 failed=0"], report
    if scene == "second":
        # The provider says so when the system gave the program a second scene to live in.
        assert "the program's windows live in a second scene (2 connected)" in stderr, report
    # The probe ends a program whose scene is not the one asked for; a case that shows no window has none.
    assert "probe: the scene would not become" not in stderr, report
    if scene == "compact" and name in SHOWN_IN_A_SCENE:
        assert "probe: the scene is compact" in stderr, report


def test_the_ios_program_lists_exactly_the_recorded_cases(simulators, request):
    status, stdout, stderr = simulators.run("iphone", "python", False, request, "--list")
    assert status == 0, stderr
    assert sorted(stdout.split()) == sorted(NAMES)


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize(("name", "device_class"), rows())
def test_ios_conformance_case(simulators, request, name, device_class, frontend, sanitized):
    check(simulators, request, name, device_class, frontend, sanitized, "first")


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("name", applicable("ipad"))
def test_ipad_conformance_case_in_a_second_scene(simulators, request, name, frontend, sanitized):
    check(simulators, request, name, "ipad", frontend, sanitized, "second")


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("name", applicable("ipad"))
def test_ipad_conformance_case_in_a_compact_scene(simulators, request, name, frontend, sanitized):
    check(simulators, request, name, "ipad", frontend, sanitized, "compact")
