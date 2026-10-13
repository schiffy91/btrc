"""A BTRC iOS application whose UIKit delegate the compiler generates (interop step 6).

UIApplicationMain instantiates the application delegate from a class name. Both
compilers project that parameter to an ordinary interface receiver and generate
the named class (lifetime = "instantiated"). The app is built with Xcode's own
clang for the iOS simulator; when a simulator is booted, it is installed and
launched, and must report launch and activation through the BTRC receiver.
Simulator evidence is not physical-device evidence (D8).
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget

REPO = Path(__file__).resolve().parents[3]
XCRUN = Path("/usr/bin/xcrun")
XCODE = Path("/Applications/Xcode.app/Contents/Developer")
APPLE_ENVIRONMENT = {"DEVELOPER_DIR": str(XCODE), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())}
TARGET = "ios-aarch64-simulator"
BUNDLE_IDENTIFIER = "dev.btrc.tests.uikit-application"

MANIFEST = """manifest-version = 1
[package]
name = "uikitApplication"
[[native.bindings]]
module = "UIKit"
header = "UIKitBinding.h"
language = "objective-c"
standard = "c11"
os = ["ios"]
symbols = ["UIApplicationMain", "-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]"]
[native.bindings.callbacks."UIApplicationMain.delegateClassName"]
interface = "IApplicationDelegate"
lifetime = "instantiated"
scope = "process"
failure = "abort"
executor = "caller"
methods = ["-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]"]
[[native.frameworks]]
name = "UIKit"
os = ["ios"]
[[native.frameworks]]
name = "Foundation"
os = ["ios"]
"""

PROGRAM = """import Library.Callback;
import ./UIKit.btrc;
#include <stdio.h>
#include <stdlib.h>
class Application implements IApplicationDelegate {
	private int launches = 0;
	public void applicationDidFinishLaunching(UIApplication application) {
		self.launches++;
		printf("btrc-uikit launched\\n");
		fflush(stdout);
	}
	public void applicationDidBecomeActive(UIApplication application) {
		printf("btrc-uikit active after %d launch\\n", self.launches);
		fflush(stdout);
		exit(self.launches == 1 ? 0 : 3);
	}
}
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
"""


def _xcrun(*arguments: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(XCRUN), *arguments], capture_output=True, text=True, timeout=timeout, check=False, env=APPLE_ENVIRONMENT
    )


def _sdk() -> str | None:
    if not XCRUN.is_file() or not XCODE.is_dir():
        return None
    result = _xcrun("--sdk", "iphonesimulator", "--show-sdk-path", timeout=60)
    path = result.stdout.strip()
    return path if result.returncode == 0 and Path(path).is_dir() else None


def _simulator() -> str:
    """A booted iOS simulator, booting the newest available iPhone when none runs.

    The device stays booted afterwards: another worker may be using it.
    """
    listed = _xcrun("simctl", "list", "devices", "available", "--json", timeout=60)
    assert listed.returncode == 0, listed.stderr
    runtimes = json.loads(listed.stdout).get("devices", {})
    candidates = []
    for runtime, devices in runtimes.items():
        if ".iOS-" not in runtime:
            continue
        version = tuple(int(part) for part in runtime.rsplit(".iOS-", 1)[1].split("-") if part.isdigit())
        for device in devices:
            if device.get("state") == "Booted":
                return device["udid"]
            if device.get("name", "").startswith("iPhone"):
                candidates.append((version, device["udid"]))
    assert candidates, "no iPhone simulator is installed for the iphonesimulator SDK"
    udid = max(candidates)[1]
    _xcrun("simctl", "boot", udid, timeout=300)
    status = _xcrun("simctl", "bootstatus", udid, "-b", timeout=600)
    assert status.returncode == 0, status.stderr
    return udid


def _project(root: Path, manifest: str = MANIFEST, program: str = PROGRAM) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    (root / "UIKitBinding.h").write_text("#import <UIKit/UIKit.h>\n", encoding="utf-8")
    (root / "src/UIKit.btrc").write_text("// Native wrapper module.\n", encoding="utf-8")
    source = root / "src/Main.btrc"
    source.write_text(program, encoding="utf-8")
    return source


def _transpile(frontend: str, source: Path, output: Path, plan: Path, sdk: str, btrcc: Path | None):
    row = PackageTarget.parse(TARGET).row
    environment = {
        **APPLE_ENVIRONMENT,
        **{key: value for key, value in os.environ.items() if key.startswith("BTRC_")},
        "BTRC_NATIVE_TARGET": row.triple,
        "BTRC_NATIVE_SYSROOT": sdk,
        "BTRC_HOME": str(REPO / "src"),
    }
    environment["PATH"] = os.environ["PATH"]
    if frontend == "reference":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--target",
            TARGET,
            "--emit-link-plan",
            str(plan),
            str(source),
            "-o",
            str(output),
        ]
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=600, env=environment)
    else:
        command = [str(btrcc), "--target", TARGET, "--emit-link-plan", str(plan), str(source)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600, env=environment)
        if result.returncode == 0:
            output.write_text(result.stdout, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def _build_app(
    root: Path, generated: Path, plan_path: Path, sdk: str, identifier: str, plist: dict | None = None
) -> Path:
    """Compile the program and the plan's generated Objective-C units with Xcode's clang.

    `plist` adds Info.plist entries, such as a scene manifest.
    """
    row = PackageTarget.parse(TARGET).row
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    common = [*row.target_arguments, "-isysroot", sdk, "-O2", "-Wall", "-Wextra", "-Werror"]
    objects = []
    compiled = _xcrun(
        "--sdk",
        "iphonesimulator",
        "clang",
        *common,
        "-std=c11",
        "-pedantic-errors",
        "-I",
        str(root),
        "-c",
        str(generated),
        "-o",
        str(root / "Main.o"),
    )
    assert compiled.returncode == 0, compiled.stderr
    objects.append(root / "Main.o")
    for unit in plan.get("generated-units", []):
        assert unit["language"] == "objective-c", unit["language"]
        unit_source = root / f"{unit['name']}.m"
        unit_source.write_text(unit["source"], encoding="utf-8")
        arc = ["-fobjc-arc"] if unit.get("memory-management") == "arc" else []
        compiled = _xcrun(
            "--sdk",
            "iphonesimulator",
            "clang",
            *common,
            "-x",
            "objective-c",
            "-std=c11",
            *arc,
            "-fobjc-exceptions",
            "-fobjc-arc-exceptions",
            "-I",
            str(root),
            "-c",
            str(unit_source),
            "-o",
            str(root / f"{unit['name']}.o"),
        )
        assert compiled.returncode == 0, compiled.stderr
        objects.append(root / f"{unit['name']}.o")
    bundle = root / "BTRCApplication.app"
    bundle.mkdir()
    frameworks = [
        argument
        for framework in plan.get("frameworks", [])
        for argument in ("-framework", framework["name"] if isinstance(framework, dict) else framework)
    ]
    linked = _xcrun(
        "--sdk",
        "iphonesimulator",
        "clang",
        *row.target_arguments,
        "-isysroot",
        sdk,
        *[str(path) for path in objects],
        *frameworks,
        "-o",
        str(bundle / "BTRCApplication"),
    )
    assert linked.returncode == 0, linked.stderr
    (bundle / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": identifier,
                "CFBundleExecutable": "BTRCApplication",
                "CFBundleName": "BTRCApplication",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": "1.0",
                "MinimumOSVersion": "17.0",
                "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
                "UIDeviceFamily": [1, 2],
                "LSRequiresIPhoneOS": True,
                **(plist or {}),
            }
        )
    )
    signed = _xcrun("codesign", "--force", "--sign", "-", str(bundle), timeout=120)
    assert signed.returncode == 0, signed.stderr
    return bundle


def _launch(
    frontend: str, root: Path, source: Path, identifier: str, btrcc: Path | None, sdk: str, plist: dict | None = None
) -> str:
    generated = root / "Main.c"
    plan = root / "Main.link.json"
    _transpile(frontend, source, generated, plan, sdk, btrcc)
    bundle = _build_app(root, generated, plan, sdk, identifier, plist)
    device = _simulator()
    installed = _xcrun("simctl", "install", device, str(bundle), timeout=300)
    assert installed.returncode == 0, installed.stderr
    try:
        launched = _xcrun(
            "simctl",
            "launch",
            "--console-pty",
            "--terminate-running-process",
            device,
            identifier,
            timeout=180,
        )
        output = launched.stdout + launched.stderr
        print(f"{frontend} on {device}: {output!r}")
        return output
    finally:
        _xcrun("simctl", "uninstall", device, identifier, timeout=120)


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_uikit_application_delegate_runs_through_btrc(frontend, tmp_path: Path, request) -> None:
    sdk = _sdk()
    if sdk is None:
        pytest.skip("the iphonesimulator SDK is Mac-bound (xcrun)")
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    root = tmp_path / "project"
    # One identifier per frontend: parallel workers share the booted simulator.
    output = _launch(frontend, root, _project(root), f"{BUNDLE_IDENTIFIER}.{frontend}", btrcc, sdk)
    assert "btrc-uikit launched" in output, output
    assert "btrc-uikit active after 1 launch" in output, output


CONTROLS_MANIFEST = MANIFEST.replace(
    'symbols = ["UIApplicationMain", ',
    'symbols = ["+[UIButton buttonWithType:]", "UIButtonTypeSystem", "+[UITextField new]", '
    '"-[UIControl addTarget:action:forControlEvents:]", "-[UIControl removeTarget:action:forControlEvents:]", '
    '"-[UIControl sendActionsForControlEvents:]", "UIControlEventTouchUpInside", "UIControlEventEditingChanged", '
    '"UIApplicationMain", ',
).replace(
    "[[native.frameworks]]",
    """[native.bindings.callbacks."-[UIControl addTarget:action:forControlEvents:].target"]
interface = "IControlAction"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[UIControl removeTarget:action:forControlEvents:]"
action-parameter = "action"
captured-handles = ["controlEvents"]
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.frameworks]]""",
    1,
)

CONTROLS_PROGRAM = """import Library.Callback;
import ./UIKit.btrc;
#include <stdio.h>
#include <stdlib.h>
int taps = 0;
int edits = 0;
int released = 0;
class Tap implements IControlAction {
	public void invoke() { taps++; }
	public void __del__() { released++; }
}
class Edit implements IControlAction {
	private CallbackScope scope;
	public int pending = 0;
	public Edit(CallbackScope scope) { self.scope = scope; }
	public void invoke() {
		edits++;
		if (self.scope.cancel() == CALLBACK_CANCELLATION_PENDING) { self.pending++; }
	}
	public void __del__() { released++; }
}
class Application implements IApplicationDelegate {
	public void applicationDidFinishLaunching(UIApplication application) {
		var buttonScope = CallbackScope();
		var fieldScope = CallbackScope();
		UIControl button = UIButton.buttonWithType(UIButtonTypeSystem);
		UIControl field = UITextField.new();
		ICallbackRegistration tap = button.addTarget(Tap(), UIControlEventTouchUpInside, buttonScope);
		var edit = Edit(fieldScope);
		ICallbackRegistration typing = field.addTarget(edit, UIControlEventEditingChanged, fieldScope);
		button.sendActionsForControlEvents(UIControlEventTouchUpInside);
		button.sendActionsForControlEvents(UIControlEventEditingChanged | UIControlEventTouchUpInside);
		field.sendActionsForControlEvents(UIControlEventEditingChanged);
		field.sendActionsForControlEvents(UIControlEventEditingChanged);
		bool fieldDone = typing.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE && edit.pending == 1;
		bool buttonDone = buttonScope.cancel() == CALLBACK_CANCELLATION_COMPLETE && !tap.isOpen();
		button.sendActionsForControlEvents(UIControlEventTouchUpInside);
		printf("btrc-uikit controls taps=%d edits=%d released=%d done=%d\\n", taps, edits, released, (int)(fieldDone && buttonDone));
		fflush(stdout);
	}
	public void applicationDidBecomeActive(UIApplication application) { exit(0); }
}
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
"""


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_uikit_controls_deliver_actions_through_btrc(frontend, tmp_path: Path, request) -> None:
    """A real UIButton and UITextField send their actions to BTRC receivers (control actions)."""
    sdk = _sdk()
    if sdk is None:
        pytest.skip("the iphonesimulator SDK is Mac-bound (xcrun)")
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    root = tmp_path / "project"
    source = _project(root, CONTROLS_MANIFEST, CONTROLS_PROGRAM)
    output = _launch(frontend, root, source, f"{BUNDLE_IDENTIFIER}.controls.{frontend}", btrcc, sdk)
    # Two taps, one edit that cancels itself, nothing after cancellation; the
    # button's receiver is released at cancellation, the field's receiver is
    # still held by this frame's `edit`.
    assert "btrc-uikit controls taps=2 edits=1 released=1 done=1" in output, output


PERSISTENCE_PROGRAM = """import Library.Callback;
import Library.FileSystem;
import Library.FileSystem.ApplicationDirectories;
import ./UIKit.btrc;
#include <stdio.h>
#include <stdlib.h>
class Application implements IApplicationDelegate {
	public void applicationDidFinishLaunching(UIApplication application) {
		var roots = ApplicationDirectories.resolveStandard();
		if (!roots.ok()) {
			printf("btrc-persist unresolved %s\\n", roots.error().message());
			exit(3);
		}
		string state = roots.value().stateRoot();
		if (FileSystem.mkdirp(state) != 0) {
			printf("btrc-persist cannot create %s\\n", state);
			exit(4);
		}
		string path = state + "/btrc-persist.txt";
		if (FileSystem.exists(path)) {
			printf("btrc-persist read %s at %s\\n", FileSystem.readText(path), path);
		} else {
			bool written = FileSystem.writeText(path, "first launch");
			printf("btrc-persist wrote %d at %s\\n", (int)written, path);
		}
		fflush(stdout);
		exit(0);
	}
	public void applicationDidBecomeActive(UIApplication application) {}
}
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
"""


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_uikit_application_state_persists_across_launches(frontend, tmp_path: Path, request) -> None:
    """ApplicationDirectories resolves inside the app's own container, and a file written there survives a relaunch."""
    sdk = _sdk()
    if sdk is None:
        pytest.skip("the iphonesimulator SDK is Mac-bound (xcrun)")
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    root = tmp_path / "project"
    source = _project(root, program=PERSISTENCE_PROGRAM)
    generated = root / "Main.c"
    plan = root / "Main.link.json"
    _transpile(frontend, source, generated, plan, sdk, btrcc)
    identifier = f"{BUNDLE_IDENTIFIER}.persist.{frontend}"
    bundle = _build_app(root, generated, plan, sdk, identifier)
    device = _simulator()
    installed = _xcrun("simctl", "install", device, str(bundle), timeout=300)
    assert installed.returncode == 0, installed.stderr
    try:
        outputs = []
        for _ in range(2):
            launched = _xcrun(
                "simctl", "launch", "--console-pty", "--terminate-running-process", device, identifier, timeout=180
            )
            outputs.append(launched.stdout + launched.stderr)
        print(f"{frontend} on {device}: {outputs!r}")
        container = _xcrun("simctl", "get_app_container", device, identifier, "data", timeout=60).stdout.strip()
        assert container, "the simulator reports no data container"
        first = re.search(r"btrc-persist wrote 1 at ([^\r\n]+)", outputs[0])
        second = re.search(r"btrc-persist read first launch at ([^\r\n]+)", outputs[1])
        assert first and second, outputs
        assert first.group(1) == second.group(1), outputs
        assert first.group(1).startswith(os.path.realpath(container) + "/Library/Application Support/") or first.group(
            1
        ).startswith(container + "/Library/Application Support/"), (container, first.group(1))
    finally:
        _xcrun("simctl", "uninstall", device, identifier, timeout=120)


SCENE_MANIFEST = """manifest-version = 1
[package]
name = "uikitScenes"
[[native.bindings]]
module = "UIKit"
header = "UIKitBinding.h"
language = "objective-c"
standard = "c11"
os = ["ios"]
symbols = ["UIApplicationMain", "-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate application:configurationForConnectingSceneSession:options:]", "+[UISceneConfiguration configurationWithName:sessionRole:]", "-[UISceneConfiguration setDelegateClass:]", "-[UISceneSession role]", "-[UIWindow initWithWindowScene:]", "-[UIWindow makeKeyAndVisible]", "-[UIWindow isKeyWindow]", "-[UISceneDelegate scene:willConnectToSession:options:]", "-[UISceneDelegate sceneDidBecomeActive:]", "-[UISceneDelegate sceneDidDisconnect:]"]
[native.bindings.callbacks."UIApplicationMain.delegateClassName"]
interface = "IApplicationDelegate"
lifetime = "instantiated"
scope = "process"
failure = "abort"
executor = "caller"
methods = ["-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate application:configurationForConnectingSceneSession:options:]"]
[native.bindings.callbacks."-[UISceneConfiguration setDelegateClass:].delegateClass"]
interface = "ISceneDelegate"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
methods = ["-[UISceneDelegate scene:willConnectToSession:options:]", "-[UISceneDelegate sceneDidBecomeActive:]", "-[UISceneDelegate sceneDidDisconnect:]"]
terminal = "-[UISceneDelegate sceneDidDisconnect:]"
[[native.frameworks]]
name = "UIKit"
os = ["ios"]
[[native.frameworks]]
name = "Foundation"
os = ["ios"]
"""

SCENE_PROGRAM = """import Library.Callback;
import ./UIKit.btrc;
#include <stdio.h>
#include <stdlib.h>
int scenes = 0;
class Scene implements ISceneDelegate {
	private UIWindow? window = null;
	public void scene(UIScene scene, UISceneSession session, UISceneConnectionOptions options) {
		UIWindowScene? windowScene = (UIWindowScene?)scene;
		if (windowScene == null) {
			printf("btrc-scene connected to a scene that is not a window scene\\n");
			fflush(stdout);
			exit(4);
		}
		UIWindow window = UIWindow.initWithWindowScene(windowScene);
		window.makeKeyAndVisible();
		self.window = window;
		printf("btrc-scene window scene connected key=%d\\n", (int)window.isKeyWindow());
		fflush(stdout);
	}
	public void sceneDidBecomeActive(UIScene scene) {
		UIWindow? window = self.window;
		printf("btrc-scene active scenes=%d window=%d\\n", scenes, (int)(window != null));
		fflush(stdout);
		exit(scenes == 1 && window != null ? 0 : 3);
	}
	public void sceneDidDisconnect(UIScene scene) { self.window = null; }
}
class Scenes implements ISceneDelegateFactory {
	public ISceneDelegate create() {
		scenes++;
		return Scene();
	}
}
class Application implements IApplicationDelegate {
	public void applicationDidFinishLaunching(UIApplication application) {
		printf("btrc-scene launched\\n");
		fflush(stdout);
	}
	public UISceneConfiguration application(UIApplication application, UISceneSession session, UISceneConnectionOptions options) {
		UISceneConfiguration configuration = UISceneConfiguration.configurationWithName(null, session.role());
		configuration.setDelegateClass(Scenes());
		printf("btrc-scene configured\\n");
		fflush(stdout);
		return configuration;
	}
}
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
"""


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_uikit_scene_lifecycle_runs_through_btrc(frontend, tmp_path: Path, request) -> None:
    """The UIScene life cycle: the app delegate configures each scene with a generated scene delegate class.

    UIKit asks the application delegate for a configuration, instantiates the
    configuration's delegate class (scope = "instance"), and connects the
    scene; the receiver downcasts it to UIWindowScene with a checked cast and
    shows a window. The scene manifest has no static configurations.
    """
    sdk = _sdk()
    if sdk is None:
        pytest.skip("the iphonesimulator SDK is Mac-bound (xcrun)")
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    root = tmp_path / "project"
    source = _project(root, SCENE_MANIFEST, SCENE_PROGRAM)
    manifest = {"UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": False}}
    output = _launch(frontend, root, source, f"{BUNDLE_IDENTIFIER}.scenes.{frontend}", btrcc, sdk, manifest)
    for line in (
        "btrc-scene launched",
        "btrc-scene configured",
        "btrc-scene window scene connected key=1",
        "btrc-scene active scenes=1 window=1",
    ):
        assert line in output, output
