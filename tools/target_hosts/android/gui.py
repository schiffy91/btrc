"""A BTRC GUI program as an Android app: built without Gradle, run on one emulator.

The app is the shim provider's activity (src/stdlib/GUI/Android/Java) around
the program, linked as libbtrcprogram.so, with wgpu-native's library beside
it. The SDK's own tools make it: javac and d8 compile the Java, aapt2 links
the manifest, zipalign and apksigner finish the archive. Nothing is fetched.

A run starts the activity with the program's arguments and environment,
waits for the result the program's thread leaves in the app's files
directory, and returns it with what the program printed.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHIM_JAVA = ROOT / "src/stdlib/GUI/Android/Java"
ACTIVITY = "dev.btrc.shim.ShimActivity"
ABIS = {"x86_64": "x86_64-linux-android29", "arm64-v8a": "aarch64-linux-android29"}
MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{package}" android:versionCode="1" android:versionName="1">
    <uses-sdk android:minSdkVersion="29" android:targetSdkVersion="{target}"/>
    <uses-permission android:name="android.permission.INTERNET"/>
    <application android:label="{label}" android:hasCode="true" android:extractNativeLibs="true" android:theme="@android:style/Theme.DeviceDefault.NoActionBar">
        <activity android:name="{activity}" android:exported="true" android:launchMode="singleTask" android:windowSoftInputMode="adjustNothing|stateAlwaysHidden" android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize|keyboard|keyboardHidden|navigation|uiMode|density|fontScale|layoutDirection|locale">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>{instrumentation}
</manifest>
"""
INSTRUMENTATION = """
    <instrumentation android:name="{name}" android:targetPackage="{package}"/>"""


class GUIAppBuilder:
    def __init__(self, sdk, *, abi="x86_64", api="36", build_tools=None):
        if abi not in ABIS:
            raise ValueError(f"supported Android ABIs are {', '.join(ABIS)}")
        self.sdk, self.abi, self.api = Path(sdk), abi, api
        tools = (
            sorted((self.sdk / "build-tools").iterdir())
            if build_tools is None
            else [self.sdk / "build-tools" / build_tools]
        )
        if not tools or not (tools[-1] / "aapt2").is_file():
            raise ValueError(f"{self.sdk} has no build-tools with aapt2")
        self.tools = tools[-1]
        self.platform = self.sdk / "platforms" / f"android-{api}" / "android.jar"
        if not self.platform.is_file():
            raise ValueError(f"{self.sdk} has no android-{api} platform")

    @staticmethod
    def run(command, **options):
        result = subprocess.run([str(part) for part in command], capture_output=True, text=True, timeout=600, **options)
        if result.returncode:
            raise RuntimeError(
                f"{Path(str(command[0])).name} failed ({result.returncode}):\n{result.stdout}{result.stderr}"
            )
        return result

    def dex(self, sources, work):
        """classes.dex of every .java file under the source roots."""
        classes = work / "classes"
        shutil.rmtree(classes, ignore_errors=True)
        classes.mkdir(parents=True)
        files = sorted(path for root in sources for path in Path(root).rglob("*.java"))
        self.run(
            [
                "javac",
                "-Xlint:all,-options",
                "-Werror",
                "-source",
                "11",
                "-target",
                "11",
                "-cp",
                self.platform,
                "-d",
                classes,
                *files,
            ]
        )
        self.run(
            [
                self.tools / "d8",
                "--min-api",
                "29",
                "--lib",
                self.platform,
                "--output",
                work,
                *sorted(classes.rglob("*.class")),
            ]
        )
        return work / "classes.dex"

    def keystore(self, work):
        store = work / "debug.keystore"
        if not store.is_file():
            self.run(
                [
                    "keytool",
                    "-genkeypair",
                    "-keystore",
                    store,
                    "-storepass",
                    "android",
                    "-keypass",
                    "android",
                    "-alias",
                    "debug",
                    "-keyalg",
                    "RSA",
                    "-keysize",
                    "2048",
                    "-validity",
                    "10000",
                    "-dname",
                    "CN=btrc test host",
                ]
            )
        return store

    def package(self, *, program, libraries, package, label, output, work, java=(), instrumentation=None):
        """The signed, debuggable APK of one program.

        `program` is its shared library, installed as libbtrcprogram.so;
        `libraries` are the shared libraries it needs beside it; `java` names
        more Java source roots than the shim's own (a test's probe), and
        `instrumentation` the class among them that starts the activity
        when a test host runs the app with `am instrument`."""
        if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", package):
            raise ValueError("the package must be a dotted lower-case Java name")
        work = Path(work)
        work.mkdir(parents=True, exist_ok=True)
        manifest = work / "AndroidManifest.xml"
        declared = INSTRUMENTATION.format(name=instrumentation, package=package) if instrumentation else ""
        manifest.write_text(
            MANIFEST.format(package=package, label=label, activity=ACTIVITY, target=self.api, instrumentation=declared),
            encoding="utf-8",
        )
        dex = self.dex([SHIM_JAVA, *java], work)
        linked = work / "linked.apk"
        self.run(
            [
                self.tools / "aapt2",
                "link",
                "--manifest",
                manifest,
                "-I",
                self.platform,
                "--min-sdk-version",
                "29",
                "--target-sdk-version",
                self.api,
                "--debug-mode",
                "-o",
                linked,
            ]
        )
        with zipfile.ZipFile(linked, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.write(dex, "classes.dex")
            archive.write(program, f"lib/{self.abi}/libbtrcprogram.so")
            for library in libraries:
                archive.write(library, f"lib/{self.abi}/{Path(library).name}")
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.run([self.tools / "zipalign", "-f", "-P", "16", "4", linked, output])
        self.run(
            [
                self.tools / "apksigner",
                "sign",
                "--ks",
                self.keystore(work),
                "--ks-pass",
                "pass:android",
                "--key-pass",
                "pass:android",
                output,
            ]
        )
        return output


class GUIAppRunner:
    """Runs one installed app's program, one process at a time, on one emulator."""

    def __init__(self, sdk, serial, package, *, instrumentation=None):
        if not re.fullmatch(r"emulator-[0-9]+", serial):
            raise ValueError("select one emulator serial explicitly")
        self.adb_path, self.serial, self.package = Path(sdk) / "platform-tools/adb", serial, package
        # The class that starts the activity under instrumentation, for a program that sends itself input.
        self.instrumentation = instrumentation

    def adb(self, *arguments, timeout=60, check=True, input=None):
        result = subprocess.run(
            [str(self.adb_path), "-s", self.serial, *arguments], input=input, capture_output=True, timeout=timeout
        )
        if check and result.returncode:
            raise RuntimeError(
                f"adb {' '.join(arguments[:3])} failed ({result.returncode}): {result.stderr.decode(errors='replace')}"
            )
        return result

    def within(self, script, **options):
        """A shell script run as the app, in its data directory."""
        return self.adb("shell", "-T", shlex.join(["run-as", self.package, "sh", "-c", script]), **options)

    def install(self, apk):
        # A device made for tests shows no "isn't responding" dialog over the
        # program: on a slow host a freshly booted system raises them for its
        # own apps, and the system refuses input aimed at a window under one.
        self.adb("shell", "settings", "put", "global", "hide_error_dialogs", "1", check=False)
        self.settle(180, 3.0)
        self.adb("uninstall", self.package, check=False)
        self.adb("install", "-r", str(apk), timeout=180)
        self.within("mkdir -p files")

    def uninstall(self):
        self.adb("shell", "am", "force-stop", self.package, check=False)
        self.adb("uninstall", self.package, check=False)

    def put(self, directory, name):
        """Copy a directory's files into the app's files directory; its path there."""
        directory = Path(directory)
        self.within(f"rm -rf files/{shlex.quote(name)}")
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            target = f"files/{name}/{path.relative_to(directory).as_posix()}"
            self.within(
                f"mkdir -p {shlex.quote(str(Path(target).parent))} && cat > {shlex.quote(target)}",
                input=path.read_bytes(),
            )
        return f"/data/user/0/{self.package}/files/{name}"

    def file(self, name):
        result = self.within(f"if [ -e files/{name} ]; then cat files/{name}; else exit 42; fi", check=False)
        if result.returncode == 42:
            return None
        if result.returncode:
            raise RuntimeError(f"cannot read the app's {name}: {result.stderr.decode(errors='replace')}")
        return result.stdout

    def front(self):
        """What the system says is in front: the focused window and the focused app."""
        state = self.adb("shell", "dumpsys", "window", check=False).stdout.decode(errors="replace")
        return " ".join(
            line.strip() for line in state.splitlines() if re.match(r"\s*m(CurrentFocus|FocusedApp)=", line)
        )

    def clear_foreground(self):
        """Stop whatever another program left in front of the launcher.

        A program may hand a link to the system, which starts the browser:
        left alone, it comes to the front in its own time, over the next run."""
        found = re.search(r"mFocusedApp=ActivityRecord\{\S+ \S+ ([\w.]+)/", self.front())
        if found and found[1] != self.package and "launcher" not in found[1]:
            self.adb("shell", "am", "force-stop", found[1], check=False)

    def settle(self, timeout, held):
        """Wait until the launcher's own window has held the focus for `held` seconds.

        A device that has just booted is still putting its own windows up,
        and a system dialog may be over the launcher: Home is what a person
        presses to get past them. Whether it settled; a run goes on either
        way, and a failure says what was in front."""
        deadline, since = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            focus = re.search(r"mCurrentFocus=Window\{[^}]*\}", self.front())
            if focus and "launcher" in focus[0].lower():
                since = since or time.monotonic()
                if time.monotonic() - since >= held:
                    return True
            else:
                since = None
                self.adb("shell", "input", "keyevent", "KEYCODE_HOME", check=False)
            time.sleep(0.5)
        return False

    def running(self):
        return bool(self.adb("shell", "pidof", self.package, check=False).stdout.strip())

    def run(self, arguments=(), environment=None, timeout=180):
        """(exit status or None, stdout, stderr): None when the program crashed or ran out of time."""
        values = [f"{key}={value}" for key, value in (environment or {}).items()] + ["--", *arguments]
        if any("," in value for value in values):
            raise ValueError("an argument or environment value contains a comma")
        self.adb("shell", "am", "force-stop", self.package)
        self.clear_foreground()
        settled = self.settle(30, 0.0)
        self.adb("logcat", "-c", check=False)
        self.within("rm -f files/exit.txt files/stdout.txt files/stderr.txt")
        joined = shlex.quote(",".join(values))
        if self.instrumentation:
            self.adb("shell", "am", "instrument", "-e", "arguments", joined, f"{self.package}/{self.instrumentation}")
        else:
            self.adb("shell", "am", "start", "-n", f"{self.package}/{ACTIVITY}", "--esa", "arguments", joined)
        deadline = time.monotonic() + timeout
        status, started = None, False
        while time.monotonic() < deadline:
            payload = self.file("exit.txt")
            if payload is not None and payload.strip():
                status = int(payload)
                break
            alive = self.running()
            started = started or alive
            if started and not alive and self.file("exit.txt") is None:
                break
            time.sleep(0.1)
        front = self.front()
        self.adb("shell", "am", "force-stop", self.package)
        self.clear_foreground()
        stdout = (self.file("stdout.txt") or b"").decode(errors="replace")
        stderr = (self.file("stderr.txt") or b"").decode(errors="replace")
        if status != 0:
            # A host that cannot be watched: what was in front when it ended,
            # what the system refused of the probe's input, and a crash's trace.
            tags = ["AndroidRuntime:E", "DEBUG:F", "libc:F", "btrc-probe:E"]
            crash = self.adb("logcat", "-d", "-t", "200", "-s", *tags, check=False)
            stderr += f"\nin front when it ended: {front}\n" + (
                "" if settled else "the launcher never had the focus before it started\n"
            )
            stderr += crash.stdout.decode(errors="replace")
        return status, stdout, stderr
