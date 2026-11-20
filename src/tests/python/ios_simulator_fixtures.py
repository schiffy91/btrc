"""iOS simulators for GUI programs: apps built for the simulator, and the one device they run on.

A program is compiled for the simulator through either compiler, plain or
sanitized, and linked, through its native plan, into an app: the shim
provider's UIKit entry (src/stdlib/GUI/IOS) and wgpu-native's pinned static
library (tools/target_hosts/ios/gui.py; nothing fetched but that pinned
archive). The driver boots one simulator of a class at a time and starts the
host's input injector for it (tools/target_hosts/ios/simhid.m).

The rows that use this boot simulators and send them input, so they run
where they are asked for: BTRC_IOS_UI_DEVICES names the device classes
("iphone,ipad"). Simulator results are never physical-device evidence, and
the installed runtime is not the iOS 17 floor, which the build targets.
"""

import os
import re
import shutil
import socket
import subprocess
import sys
import time
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
TARGET = "ios-aarch64-simulator"
SIMULATOR_BOUND = "requires a Mac with Xcode and iOS simulators: set BTRC_IOS_UI_DEVICES (iphone,ipad)"
# One device of each class, made for these rows: a phone wide enough for the
# conformance suite's windows, and a tablet whose system gives an app more than one scene.
DEVICES = {"iphone": ("btrc-ui-iphone", "iPhone 17 Pro Max"), "ipad": ("btrc-ui-ipad", "iPad Air 11-inch (M4)")}
FRONTENDS = sorted(shell.FRONTENDS)
MODES = {False: "plain", True: "sanitized"}
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
    """Apps of BTRC programs and the one simulator they run on at a time.

    A program is named by a short lower-case word, which is also its app's
    name: `build` keeps one build of it per compiler and mode for the run.
    """

    def __init__(self, directories):
        self.base = directories.mktemp("ios-simulators")
        self.programs = {}
        self.runners = {}
        self.host = None
        self.injector = None
        self.port = 0
        self.sdk_path = None
        # The app whose scene may be a window on the tablet's stage, by its runner's key.
        self.windowed = None

    def asked(self, device_class):
        """Skip unless this host can run simulators and the run asked for this device class."""
        wanted = {name.strip() for name in os.environ.get("BTRC_IOS_UI_DEVICES", "").split(",")}
        if sys.platform != "darwin" or device_class not in wanted or not self.sdk():
            pytest.skip(SIMULATOR_BOUND)

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

    def program(self, name, source, frontend, sanitized, request, app=True, probe=None, quiet=True):
        """The program built once per compiler and mode: for an app's bundle, or as an executable to spawn."""
        key = (name, frontend, sanitized, app)
        if key in self.programs:
            if isinstance(self.programs[key], BaseException):
                # One failure to build is every row's: say it once each, without building again.
                raise self.programs[key]
            return self.programs[key]
        try:
            self.programs[key] = self.build(name, source, frontend, sanitized, request, app, probe, quiet)
        except BaseException as error:
            self.programs[key] = error
            raise
        return self.programs[key]

    def build(self, name, source, frontend, sanitized, request, app=True, probe=None, quiet=True):
        """`probe` is a fixture's (header, symbols, C source): the program binds the header and links the source.

        A program compiles without a warning unless it is another driver's,
        whose source that driver accepts with the warnings it raises (`quiet`).
        """
        NativeBindingPackage.require_reader()
        work = self.base / f"{name}-{frontend}-{MODES[sanitized]}"
        work.mkdir()
        if probe is not None:
            source = NativeBindingPackage.write(source, work / "package", probe[0], probe[1])
        include, libraries = self.wgpu_native()
        row = PackageTarget.parse(TARGET).row
        if frontend == "selfhost":
            # The self-hosted compiler is a host program, keyed by the stdlib it
            # resolves for the host: it is found before the simulator's
            # environment below would make the host's native imports refuse.
            request.getfixturevalue("immutable_btrcc")
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv("BTRC_NATIVE_TARGET", row.triple)
            environment.setenv("BTRC_NATIVE_SYSROOT", self.sdk())
            # An app has no pkg-config search path: the header reader and the
            # compiler find wgpu-native's headers here, the linker its library below.
            environment.setenv("C_INCLUDE_PATH", str(include))
            generated, plan = work / "Program.c", work / "Program.json"
            result = transpile(source, generated, plan, frontend, request, TARGET)
            assert result.returncode == 0, result.stderr
            assert not quiet or "warning:" not in result.stderr.lower(), result.stderr
            flags = list(SANITIZERS) if sanitized else []
            program = work / "Program"
            objects = []
            if probe is not None:
                objects.append(str(work / "Probe.o"))
                target = ["-target", row.triple, "-isysroot", self.sdk(), "-std=c11", "-O2", f"-I{probe[0].parent}"]
                built = xcrun("clang", *target, *flags, "-c", str(probe[2]), "-o", objects[0])
                assert built.returncode == 0, built.stderr
            if app:
                link_flags = [*GUIAppBuilder.link_flags(libraries), *flags, "-Wl,-rpath,@executable_path/Frameworks"]
            else:
                # A spawned program has no bundle to carry the sanitizer's runtime: it loads Xcode's own.
                link_flags = [*objects, *flags, *([f"-Wl,-rpath,{self.runtime('asan').parent}"] if sanitized else [])]
            NativePlanBuilder().build(
                plan_path=plan,
                generated_c=generated,
                output=program,
                optimization=2,
                compile_flags=[f"-I{include}", *flags],
                link_flags=link_flags,
            )
        return program

    def spawned(
        self,
        device_class,
        name,
        source,
        frontend,
        sanitized,
        request,
        arguments=(),
        probe=None,
        quiet=True,
        environment=None,
        timeout=120,
    ):
        """One run of a program without a window, as a process of the booted simulator: (status, stdout, stderr).

        Such a program is no app. `simctl spawn` starts it inside the simulator,
        where the system it sees is the simulator's: its sockets, its
        frameworks, its file system under the device's own root.
        """
        self.asked(device_class)
        host = self.device(device_class)
        program = self.program(name, source, frontend, sanitized, request, app=False, probe=probe, quiet=quiet)
        variables = {"ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1", **(environment or {})}
        process = host.spawn([str(program), *arguments], variables)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            host.kill_group(process.pid)
            stdout, stderr = process.communicate()
            return (
                -1,
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace") + f"\nno end within {timeout} seconds\n",
            )
        return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    @staticmethod
    def identifier(name, frontend, sanitized, variant=""):
        """One app a program, compiler, mode and variant: the system keeps a scene's size by the app it belongs to."""
        suffix = f"-{variant}" if variant else ""
        return f"dev.btrc.testhost.{name}.{shell.FRONTENDS[frontend]}-{MODES[sanitized]}{suffix}"

    def bundle(self, name, source, frontend, sanitized, variant, request):
        program = self.program(name, source, frontend, sanitized, request)
        identifier = self.identifier(name, frontend, sanitized, variant)
        # The address sanitizer's runtime is a library the app carries; the other's is linked in.
        resources = {f"Frameworks/{self.runtime('asan').name}": self.runtime("asan")} if sanitized else {}
        return GUIAppBuilder.package(
            program=program,
            identifier=identifier,
            label=f"BTRC {name} ({shell.FRONTENDS[frontend]}, {MODES[sanitized]})",
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
        # An app a stopped run left behind may still have a window on the stage (runner).
        listed = host.command("listapps", host.device(), check=False).stdout.decode(errors="replace")
        for identifier in sorted(set(re.findall(r"dev\.btrc\.testhost\.[A-Za-z0-9.-]+", listed))):
            host.command("terminate", host.device(), identifier, check=False)
            host.command("uninstall", host.device(), identifier, check=False)
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

    def runner(self, device_class, name, source, frontend, sanitized, request, variant="", windowed=False):
        """The program's app, installed on the booted simulator of this class.

        One app at a time may have its scene made a window (`windowed`): when
        an app is launched, iPadOS starts every other app whose window shows
        on the stage beside it, with no arguments, and a program started so
        would run beside the one a row is watching. The last such app is
        uninstalled before another app's runner is handed out."""
        self.asked(device_class)
        host = self.device(device_class)
        key = (device_class, name, frontend, sanitized, variant)
        if self.windowed not in (None, key):
            self.runners.pop(self.windowed).uninstall()
            self.windowed = None
        if windowed:
            self.windowed = key
        if key not in self.runners:
            runner = GUIAppRunner(host, self.identifier(name, frontend, sanitized, variant))
            runner.install(self.bundle(name, source, frontend, sanitized, variant, request))
            self.runners[key] = runner
        return self.runners[key]

    def screenshot(self, path):
        """What the booted simulator's screen shows, as an uncompressed bitmap."""
        self.host.command("io", self.host.device(), "screenshot", "--type=bmp", str(path), timeout=60)
        return path

    def close(self):
        if self.injector is not None:
            self.injector.terminate()
            self.injector.wait(timeout=30)
            self.injector = None
        if self.host is not None:
            for key in [key for key in self.runners if key[0] == self.host.device_class]:
                self.runners.pop(key).uninstall()
            self.host.close()
            self.host = None
            self.windowed = None


@pytest.fixture(scope="session")
def simulators(tmp_path_factory):
    simulators = Simulators(tmp_path_factory)
    yield simulators
    simulators.close()
