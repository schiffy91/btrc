"""The GUI conformance suite's Android rows: built on a Linux host, run on an emulator.

The suite (src/tests/native/gui/conformance) is compiled for the device's
ABI through both compilers and linked, through its native plan, into the
shared library of an app: the shim provider's activity
(src/stdlib/GUI/Android/java), the probe's Java
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
import sys
import tomllib
import zipfile
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
HAS = {"web"}
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


def build_suite_app(frontend, device, request, tmp_path_factory):
    NativeBindingPackage.require_reader()
    abi = device.property("ro.product.cpu.abi")
    tools = AndroidBuildTools(device.sdk, abi)
    work = tmp_path_factory.mktemp(f"android-conformance-{frontend}")
    include, libraries = wgpu_native(abi, tmp_path_factory.getbasetemp())
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("ANDROID_NDK_HOME", str(tools.ndk))
        environment.setenv("BTRC_NATIVE_TARGET", tools.triple)
        environment.setenv("BTRC_NATIVE_SYSROOT", str(tools.sysroot))
        # An app has no pkg-config search path: the header reader and the
        # compiler find wgpu-native's headers here, the linker its library below.
        environment.setenv("C_INCLUDE_PATH", str(include))
        environment.delenv("BASH_ENV", raising=False)
        generated, plan = work / "Suite.c", work / "Suite.json"
        result = transpile(SUITE / "Main.btrc", generated, plan, frontend, request, tools.label)
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
    report = f"{name} on Android API {android_device.property('ro.build.version.sdk')} ({frontend})\n{stdout}{stderr}"
    evidence = os.environ.get("BTRC_ANDROID_UI_EVIDENCE")
    if evidence:
        (Path(evidence) / f"{shell.FRONTENDS[frontend]}-{name}.txt").write_text(report, encoding="utf-8")
    assert status == 0 and f"CASE {name} PASS" in stdout, report
