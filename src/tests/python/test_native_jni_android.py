"""A checked JNI call round trip on an Android device: interop step 4's exit (CL-P2-09).

docs/design/native-interop-ownership.md, step 4: "a checked JNI call makes one
round trip on the emulator test host: app_process with a pushed .dex and .so,
debug.checkjni 1, and no CheckJNI abort in logcat". The NDK's clang builds the
adopted-VM fixture (jni_adoption_fixtures.py) for the device's ABI into a JNI
library, d8 dexes its Java classes, and both are pushed to /data/local/tmp.
app_process starts ART with -Xcheck:jni: the entry class System.loads the
library, JNI_OnLoad adopts ART's VM, and the BTRC program calls Java through
its generated binding on the Java main thread and on a BTRC thread.

A deliberate JNI misuse runs first in exactly that configuration and must
abort with CheckJNI's report, so a clean round trip cannot mean CheckJNI was
off. The round trip must then exit 0 with its expected output, and logcat must
hold no CheckJNI report and no fatal line from its process.

It needs an Android SDK (ANDROID_SDK_ROOT or ANDROID_HOME, holding the NDK and
build-tools nix/platforms.nix pins; ANDROID_NDK_HOME may name the NDK) and a
device: BTRC_ANDROID_SERIAL names a running one, or BTRC_ANDROID_AVD_STATE
(with BTRC_ANDROID_API) names tools/target_hosts/android AVD state that this
module boots and stops. host-android.yml runs it on its API 29 and 36 x86_64
emulators. BTRC_ANDROID_JNI_REQUIRED=1 makes a missing prerequisite fail
instead of skip, and BTRC_ANDROID_JNI_EVIDENCE names a directory for each
run's logcat and report.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.python.jni_adoption_fixtures import (
    ENTRY_CLASS,
    LIBRARY_NAME,
    REPO,
    build_library,
    missing_java_tools,
    write_project,
)
from tools.native_plan import TargetToolchain
from tools.target_hosts.android.avd import AvdManager
from tools.target_hosts.android.build import AndroidHostBuilder
from tools.target_hosts.android.sdk import SDKVersions

# Each device ABI's target row, and the triple BTRC_NATIVE_TARGET spells it with.
ABI_TARGETS = {
    "x86_64": ("android-x86_64", "x86_64-linux-android29"),
    "arm64-v8a": ("android-aarch64", "aarch64-linux-android29"),
}
REMOTE = "/data/local/tmp/btrc-jni"
DEX = "btrc-jni.dex"
LIBRARY = f"lib{LIBRARY_NAME}.so"
# What CheckJNI, or the runtime it aborts, writes to logcat.
CHECKJNI_REPORTS = ("JNI DETECTED ERROR IN APPLICATION", "JNI WARNING", "Runtime aborting")
# A threadtime line: date, time, pid, tid, priority.
THREADTIME = re.compile(r"^\d\d-\d\d \d\d:\d\d:\d\d\.\d+\s+(\d+)\s+\d+ ([VDIWEFA]) ")


def unavailable(reason):
    if os.environ.get("BTRC_ANDROID_JNI_REQUIRED") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


class AndroidDevice:
    """One adb-reachable device: shell commands with their remote status, pushes and logcat."""

    def __init__(self, sdk, serial):
        self.sdk = Path(sdk)
        self.adb_path = self.sdk / "platform-tools" / "adb"
        self.serial = serial

    def adb(self, *arguments, timeout=120, check=True):
        completed = subprocess.run(
            [str(self.adb_path), "-s", self.serial, *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if check and completed.returncode:
            raise AssertionError(f"adb {shlex.join(arguments)} failed ({completed.returncode}): {completed.stderr}")
        return completed

    def shell(self, command, *, timeout=120, check=True):
        # -T: shell protocol v2, so the result carries the remote exit status
        # and keeps stdout and stderr apart.
        return self.adb("shell", "-T", command, timeout=timeout, check=check)

    def property(self, name):
        return self.shell(shlex.join(["getprop", name])).stdout.strip()

    BUFFERS = ("-b", "main", "-b", "system", "-b", "crash")

    def clear_logcat(self):
        self.adb("logcat", "-c", *self.BUFFERS)

    def logcat(self):
        return self.adb("logcat", "-d", "-v", "threadtime", *self.BUFFERS).stdout

    def facts(self):
        return {
            "serial": self.serial,
            "sdk": self.property("ro.build.version.sdk"),
            "release": self.property("ro.build.version.release"),
            "abi": self.property("ro.product.cpu.abi"),
            "page_size": self.shell("getconf PAGESIZE").stdout.strip(),
            "fingerprint": self.property("ro.build.fingerprint"),
        }


class AndroidBuildTools:
    """The pinned NDK, its sysroot, d8 and an android.jar, for one device ABI."""

    def __init__(self, sdk, abi):
        versions = SDKVersions()
        if abi not in ABI_TARGETS:
            pytest.fail(f"no target row builds for the device ABI {abi!r}")
        self.label, self.triple = ABI_TARGETS[abi]
        self.ndk = Path(os.environ.get("ANDROID_NDK_HOME") or Path(sdk) / "ndk" / versions.ndk)
        prebuilt = self.ndk / "toolchains" / "llvm" / "prebuilt" / TargetToolchain.NDK_HOSTS.get(sys.platform, "")
        self.sysroot = prebuilt / "sysroot"
        self.readelf = prebuilt / "bin" / "llvm-readelf"
        self.d8 = Path(sdk) / "build-tools" / versions.build_tools[-1] / "d8"
        jars = [Path(sdk) / "platforms" / f"android-{api}" / "android.jar" for api in reversed(versions.apis)]
        self.android_jar = next((jar for jar in jars if jar.is_file()), jars[0])
        for path in (self.sysroot, self.readelf, self.d8, self.android_jar):
            assert path.exists(), f"the Android SDK lacks {path}"

    def dex(self, classes, output):
        output.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(self.d8),
                "--min-api",
                "29",
                "--lib",
                str(self.android_jar),
                "--output",
                str(output),
                *sorted(str(path) for path in classes.rglob("*.class")),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        return output / "classes.dex"

    def check_alignment(self, library):
        """Every LOAD segment is 16 KiB-aligned, so the library also loads on a 16 KiB-page image."""
        segments = subprocess.run(
            [str(self.readelf), "-lW", str(library)], capture_output=True, text=True, check=True, timeout=60
        ).stdout
        AndroidHostBuilder.load_alignment(segments)
        return segments


@pytest.fixture(scope="module")
def android_device(request):
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    serial = os.environ.get("BTRC_ANDROID_SERIAL")
    state = os.environ.get("BTRC_ANDROID_AVD_STATE")
    if not sdk or not (serial or state):
        unavailable(
            "requires an Android SDK and device: set ANDROID_SDK_ROOT and BTRC_ANDROID_SERIAL or BTRC_ANDROID_AVD_STATE"
        )
    manager = None
    if not serial:
        # The AVD tools/target_hosts/android created; this module owns only the emulator it boots.
        manager = AvdManager(sdk, state, api=os.environ.get("BTRC_ANDROID_API", "29"))
        manager.create()
        manager.boot()
        serial = manager.serial
    try:
        yield AndroidDevice(sdk, serial)
    finally:
        if manager is not None:
            manager.close()
            evidence = os.environ.get("BTRC_ANDROID_JNI_EVIDENCE")
            log = manager.state / f"{manager.name}.log"
            if evidence and log.is_file():
                # The next boot of this AVD rewrites its log.
                Path(evidence).mkdir(parents=True, exist_ok=True)
                selection = request.config.getoption("--compilers").replace(",", "-")
                (Path(evidence) / f"emulator-{selection}.log").write_bytes(log.read_bytes())


def compile_for(compiler, source, plan, label, request):
    """Compile `source` for the target row `label` through the reference or the self-hosted compiler."""
    if compiler == "python":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"), str(source), CompilerOptions(include_stdlib=False, target=label)
        )
        if result.successful:
            plan.write_text(result.native_plan.canonical_json(), encoding="utf-8")
        return result
    binary = request.getfixturevalue("immutable_btrcc")
    completed = subprocess.run(
        [str(binary), "--no-stdlib", "--target", label, "--emit-link-plan", str(plan), str(source)],
        env={**os.environ, "BTRC_HOME": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    return SimpleNamespace(
        successful=completed.returncode == 0,
        c_source=completed.stdout if completed.returncode == 0 else None,
        failure=completed.stderr,
        diagnostics=[],
    )


def app_process(device, remote, mode, *, timeout=300):
    """Run the entry class under app_process with CheckJNI; returns (result, pid, seconds)."""
    command = (
        f"cd {shlex.quote(remote)} && CLASSPATH={shlex.quote(f'{remote}/{DEX}')} "
        f"app_process -Xcheck:jni {shlex.quote(remote)} {ENTRY_CLASS} {shlex.quote(f'{remote}/{LIBRARY}')} {mode}"
    )
    started = time.monotonic()
    completed = device.shell(command, timeout=timeout, check=False)
    seconds = time.monotonic() - started
    pid = next(
        (line.removeprefix("btrc-pid=") for line in completed.stdout.splitlines() if line.startswith("btrc-pid=")), None
    )
    return completed, pid, seconds


def process_lines(logcat, pid):
    """The (priority, line) pairs of the logcat lines process `pid` wrote."""
    lines = []
    for line in logcat.splitlines():
        match = THREADTIME.match(line)
        if match and match[1] == pid:
            lines.append((match[2], line))
    return lines


def reports(logcat, pid):
    """CheckJNI's reports, and the runtime aborting, in process `pid`'s lines."""
    return [line for _, line in process_lines(logcat, pid) if any(report in line for report in CHECKJNI_REPORTS)]


def test_checked_jni_round_trip_on_android(android_device, compiler, tmp_path, monkeypatch, request):
    missing = missing_java_tools()
    if missing or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.fail(missing or "requires BTRC_NATIVE_HEADER_READER, which reads Library.Java's JNI.h for Android")
    device = android_device
    facts = device.facts()
    tools = AndroidBuildTools(device.sdk, facts["abi"])
    monkeypatch.setenv("ANDROID_NDK_HOME", str(tools.ndk))
    monkeypatch.setenv("BTRC_NATIVE_TARGET", tools.triple)
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(tools.sysroot))
    source, classes = write_project(tmp_path)
    monkeypatch.setenv("BTRC_JAVA_CLASSPATH", str(classes))

    evidence = os.environ.get("BTRC_ANDROID_JNI_EVIDENCE")
    evidence = Path(evidence) / compiler if evidence else None
    report = {"schema": "btrc.android-jni-round-trip/1", "compiler": compiler, "target": tools.label, "device": facts}
    try:
        compiled = compile_for(compiler, source, tmp_path / "Program.link.json", tools.label, request)
        library = build_library(
            compiled,
            tmp_path,
            tmp_path / LIBRARY,
            dict(os.environ),
            link_flags=["-Wl,-z,max-page-size=16384"],
        )
        report["load_segments"] = tools.check_alignment(library)
        dex = tools.dex(classes, tmp_path / "dex")

        remote = f"{REMOTE}/{compiler}"
        device.shell(f"rm -rf {shlex.quote(remote)} && mkdir -p {shlex.quote(remote)}")
        device.adb("push", str(dex), f"{remote}/{DEX}")
        device.adb("push", str(library), f"{remote}/{LIBRARY}")
        # A read-only dex: newer ART refuses to load a writable one.
        device.shell(f"chmod 0444 {shlex.quote(f'{remote}/{DEX}')} && chmod 0755 {shlex.quote(f'{remote}/{LIBRARY}')}")
        device.shell("setprop debug.checkjni 1")
        report["debug.checkjni"] = device.property("debug.checkjni")
        assert report["debug.checkjni"] == "1"

        # CheckJNI must be on: a misuse it alone reports aborts this exact command line.
        device.clear_logcat()
        probe, probe_pid, _ = app_process(device, remote, -1, timeout=120)
        deadline = time.monotonic() + 30
        probe_log = device.logcat()
        while "JNI DETECTED ERROR IN APPLICATION" not in probe_log and time.monotonic() < deadline:
            time.sleep(1)
            probe_log = device.logcat()
        # logd can still be taking the aborted process's dump; let it land
        # before the round trip's logcat starts.
        time.sleep(3)
        probe_log = device.logcat()
        report["probe"] = {
            "exit_status": probe.returncode,
            "pid": probe_pid,
            "stdout": probe.stdout,
            "stderr": probe.stderr,
            "reports": reports(probe_log, probe_pid),
        }
        if evidence is not None:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / "probe-logcat.txt").write_text(probe_log, encoding="utf-8")
        print(json.dumps(report["probe"], indent=2))
        assert probe_pid is not None, (probe.stdout, probe.stderr)
        assert probe.returncode != 0, ("the CheckJNI probe was not refused", probe.stdout, probe.stderr)
        refused = [line for line in report["probe"]["reports"] if "illegal class name 'java.lang.String'" in line]
        assert refused, probe_log[-4000:]

        device.clear_logcat()
        completed, pid, seconds = app_process(device, remote, 0)
        # logd may take the process's last lines after it exits.
        time.sleep(2)
        logcat = device.logcat()
        if evidence is not None:
            (evidence / "round-trip-logcat.txt").write_text(logcat, encoding="utf-8")
        own = process_lines(logcat, pid) if pid else []
        fatal = [line for priority, line in own if priority in "FA"]
        found = reports(logcat, pid) if pid else []
        everywhere = [line for line in logcat.splitlines() if any(report in line for report in CHECKJNI_REPORTS)]
        report["round_trip"] = {
            "exit_status": completed.returncode,
            "pid": pid,
            "seconds": round(seconds, 3),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "reports": found,
            "fatal": fatal,
            "process_lines": len(own),
            "checkjni_lines": [line for _, line in own if "CheckJNI" in line],
            # Another process's reports (a late line of the probe's dump) are recorded, not judged.
            "other_process_reports": len(everywhere) - len(found),
        }
        print(json.dumps(report["round_trip"], indent=2))
        assert completed.returncode == 0, (completed.stdout, completed.stderr, logcat[-4000:])
        assert pid is not None and completed.stdout.splitlines() == [
            f"btrc-pid={pid}",
            "java-adopted-ok",
            "java-entry-status=0",
        ], completed.stdout
        # The process wrote to logcat (ART's start-up lines), so an empty scan is not a missed filter.
        assert own, logcat[-4000:]
        assert found == [] and fatal == [], logcat[-4000:]
        report["status"] = "passed"
    finally:
        report.setdefault("status", "failed")
        if evidence is not None:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
