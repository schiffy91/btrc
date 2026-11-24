"""The GUI conformance suite's Android rows: built on a Linux host, run on an emulator.

The suite (src/tests/native/gui/conformance) is compiled for the device's
ABI through both compilers and linked, through its native plan, into the
shared library of an app: the shim provider's activity
(src/stdlib/GUI/Android/Java), the probe's Java
(conformance/probes/android/java) and wgpu-native's pinned prebuilt library
beside it (tools/target_hosts/android/gui.py; no Gradle, nothing fetched but
that pinned archive). Each case then runs as its own process of the
installed app, started under instrumentation, which is how the system lets
the probe send the app real input.

It needs what the JNI round trip needs (test_native_jni_android.py): an
Android SDK and a device, named the same way. host-android.yml runs it on
its API 29 and 36 x86_64 emulators. BTRC_ANDROID_UI_EVIDENCE names a
directory that receives each compiler's APK and every case's output.
"""

import os
import shlex
import struct
import subprocess
import sys
import time
import tomllib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.python import test_native_ui_shell_windows as shell
from src.tests.python.native_ui_shell_fixtures import transpile
from src.tests.python.test_native_jni_android import AndroidBuildTools, android_device  # noqa: F401
from tools.native_plan import NativePlanBuilder
from tools.target_hosts.android.gui import GUIAppBuilder, GUIAppRunner

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "src/tests/native/gui/conformance"
CASES = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))["case"]
NAMES = [case["name"] for case in CASES]
NEEDS = {case["name"]: case["needs"] for case in CASES if "needs" in case}
# What the Android provider has of what a case may need: a web view, and no
# FreeType (a font face from a file is FreeType's, which the NDK does not carry).
HAS = {"web", "modal", "wheel"}
PROBE_JAVA = SUITE / "probes/android/java"
RUNNER = "dev.btrc.probe.Runner"
# The pinned wgpu-native archive of each ABI (nix/wgpu-native-prebuilt.nix).
ARCHIVES = {"x86_64": "android-x64", "arm64-v8a": "android-arm64"}
FRONTENDS = sorted(shell.FRONTENDS)
BUILT = {}


def wgpu_native(abi, directory):
    """The ABI's pinned wgpu-native archive, extracted: its include and library directories."""
    root = directory / "wgpu-native"
    if not root.is_dir():
        with zipfile.ZipFile(shell.pinned_archive(ARCHIVES[abi])) as bundle:
            bundle.extractall(root)
    return root / "include/webgpu", root / "lib"


def suite_app(frontend, device, request, tmp_path_factory):
    """Build, package and install the suite through one compiler, once a session; its runner."""
    if frontend in BUILT:
        if isinstance(BUILT[frontend], BaseException):
            # One failure to build or install is every case's: say it once each, without building again.
            raise BUILT[frontend]
        return BUILT[frontend]
    try:
        BUILT[frontend] = build_suite_app(frontend, device, request, tmp_path_factory)
    except BaseException as error:
        BUILT[frontend] = error
        raise
    return BUILT[frontend]


def build_gui_library(source, frontend, request, tools, include, libraries, work):
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("ANDROID_NDK_HOME", str(tools.ndk))
        environment.setenv("BTRC_NATIVE_TARGET", tools.triple)
        environment.setenv("BTRC_NATIVE_SYSROOT", str(tools.sysroot))
        # An app has no pkg-config search path: the header reader and the
        # compiler find wgpu-native's headers here, the linker its library below.
        environment.setenv("C_INCLUDE_PATH", str(include))
        environment.delenv("BASH_ENV", raising=False)
        generated, plan = work / "Suite.c", work / "Suite.json"
        result = transpile(source, generated, plan, frontend, request, tools.label)
        assert result.returncode == 0, result.stderr
        assert "warning:" not in result.stderr.lower(), result.stderr
        library = work / "libbtrcprogram.so"
        NativePlanBuilder().build(
            plan_path=plan,
            generated_c=generated,
            output=library,
            optimization=2,
            compile_flags=["-fPIC", f"-I{include}"],
            link_flags=["-shared", f"-L{libraries}", "-Wl,-z,max-page-size=16384", "-Wl,--no-undefined"],
        )
    tools.check_alignment(library)
    return library


def build_suite_app(frontend, device, request, tmp_path_factory):
    NativeBindingPackage.require_reader()
    abi = device.property("ro.product.cpu.abi")
    tools = AndroidBuildTools(device.sdk, abi)
    work = tmp_path_factory.mktemp(f"android-conformance-{frontend}")
    include, libraries = wgpu_native(abi, tmp_path_factory.getbasetemp())
    library = build_gui_library(SUITE / "Main.btrc", frontend, request, tools, include, libraries, work)
    package = f"dev.btrc.testhost.conformance.{shell.FRONTENDS[frontend]}"
    apk = GUIAppBuilder(device.sdk, abi=abi).package(
        program=library,
        libraries=[libraries / "libwgpu_native.so"],
        package=package,
        label=f"BTRC conformance ({shell.FRONTENDS[frontend]})",
        output=work / f"gui-conformance-{shell.FRONTENDS[frontend]}-{tools.label}.apk",
        work=work / "apk",
        java=[PROBE_JAVA],
        instrumentation=RUNNER,
    )
    evidence = os.environ.get("BTRC_ANDROID_UI_EVIDENCE")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        (Path(evidence) / apk.name).write_bytes(apk.read_bytes())
    runner = GUIAppRunner(device.sdk, device.serial, package, instrumentation=RUNNER)
    runner.install(apk)
    web = runner.put(SUITE / "web", "web")
    request.session.addfinalizer(runner.uninstall)
    return runner, web


@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("name", [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS])
def test_android_conformance_case(name, frontend, android_device, request, tmp_path_factory):  # noqa: F811
    if sys.platform != "linux":
        pytest.skip("requires an Android SDK and device: the app is built with the Linux NDK")
    runner, web = suite_app(frontend, android_device, request, tmp_path_factory)
    # The probe sends real input: the emulator is a session made for tests.
    status, stdout, stderr = runner.run([name], {"BTRC_UI_PRIVATE_SESSION": "1", "BTRC_CONFORMANCE_WEB": web}, 180)
    passed = status == 0 and f"CASE {name} PASS" in stdout
    report = f"{name} on Android API {android_device.property('ro.build.version.sdk')} ({frontend})\n{stdout}{stderr}"
    if not passed:
        report += f"\nexit status: {status}\n"
    evidence = os.environ.get("BTRC_ANDROID_UI_EVIDENCE")
    if evidence:
        stem = f"{shell.FRONTENDS[frontend]}-{name}"
        (Path(evidence) / f"{stem}.txt").write_text(report, encoding="utf-8")
        if not passed:
            # The next case clears logcat. Keep the driver and linker messages
            # preceding a framework abort, even if the program printed nothing.
            logs = android_device.adb("logcat", "-d", "-v", "threadtime", *android_device.BUFFERS, check=False)
            (Path(evidence) / f"{stem}-logcat.txt").write_text(logs.stdout + logs.stderr, encoding="utf-8")
    assert passed, report


def frame_on_screen(raw):
    # screencap emits a native-endian header and tightly packed RGBA pixels.
    if len(raw) < 16:
        return False
    width, height, format_code = struct.unpack_from("<3I", raw)
    start = len(raw) - width * height * 4
    if format_code not in (1, 2) or start not in (12, 16):
        return False
    pixels = memoryview(raw)[start:]
    # A column of red above blue must be wide enough to be the frame.
    # Status-bar icons and single-color window backgrounds cannot satisfy this.
    matching = []
    for x in range(0, width, 8):
        red, blue = [], []
        for y in range(0, height, 8):
            i = (y * width + x) * 4
            r, g, b = pixels[i : i + 3]
            if r > 235 and g < 20 and b < 20:
                red.append(y)
            if b > 235 and g < 20 and r < 20:
                blue.append(y)
        if len(red) >= 4 and len(blue) >= 4 and red[-1] < blue[0] <= red[-1] + 16:
            matching.append(x)
    return any(matching[i + 7] - x == 56 for i, x in enumerate(matching[:-7]))


@pytest.mark.parametrize("frontend", FRONTENDS)
def test_android_shared_frame_case(frontend, android_device, request, tmp_path, tmp_path_factory):  # noqa: F811
    NativeBindingPackage.require_reader()
    device = android_device
    abi = device.property("ro.product.cpu.abi")
    tools = AndroidBuildTools(device.sdk, abi)
    include, libraries = wgpu_native(abi, tmp_path_factory.getbasetemp())
    source = SUITE.parent / "android/shared_frame"
    library = build_gui_library(source / "Main.btrc", frontend, request, tools, include, libraries, tmp_path)
    sender = tmp_path / "libframeproducer.so"
    subprocess.run(
        [
            str(tools.readelf.parent / "clang"),
            f"--target={tools.triple}",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source / "Producer.c"),
            "-landroid",
            "-Wl,-z,max-page-size=16384",
            "-o",
            str(sender),
        ],
        check=True,
        timeout=120,
    )
    package = f"dev.btrc.testhost.frame.{shell.FRONTENDS[frontend]}"
    apk = GUIAppBuilder(device.sdk, abi=abi).package(
        program=library,
        libraries=[libraries / "libwgpu_native.so", sender],
        package=package,
        label="Shared frame",
        output=tmp_path / "shared-frame.apk",
        work=tmp_path / "apk",
    )
    runner = GUIAppRunner(device.sdk, device.serial, package)
    runner.install(apk)
    request.addfinalizer(runner.uninstall)
    base = runner.adb("shell", "pm", "path", package).stdout.decode().strip().removeprefix("package:")
    install = base.rsplit("/", 1)[0]
    (peer,) = runner.within(f"find {shlex.quote(install)}/lib -name libframeproducer.so").stdout.decode().splitlines()
    with ThreadPoolExecutor(max_workers=2) as worker:
        result = worker.submit(runner.run, timeout=90)
        producer = None
        deadline = time.monotonic() + 90
        shown = False
        while time.monotonic() < deadline and not result.done():
            if producer is None:
                if runner.within("test -S files/frame-peer", check=False).returncode == 0:
                    producer = worker.submit(runner.within, f"cd files && exec {shlex.quote(peer)}", timeout=60)
            elif producer.done():
                producer.result()
                if runner.file("frame-ready") and frame_on_screen(runner.adb("exec-out", "screencap").stdout):
                    shown = True
                    evidence = os.environ.get("BTRC_ANDROID_UI_EVIDENCE")
                    if evidence:
                        directory = Path(evidence)
                        directory.mkdir(parents=True, exist_ok=True)
                        picture = runner.adb("exec-out", "screencap", "-p").stdout
                        (directory / f"shared-frame-{frontend}.png").write_bytes(picture)
                    runner.within("touch files/frame-captured")
                    break
            time.sleep(0.2)
        status, stdout, stderr = result.result(timeout=100)
    assert status == 0 and shown and "Shared frame captured after producer exit" in stdout, stdout + stderr
