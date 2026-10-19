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


_UNANSWERED_SIMCTL: list[str] = []


def _simulator() -> str:
    """A booted iOS simulator, booting the newest available iPhone when none runs.

    The device stays booted afterwards: another worker may be using it. A
    CoreSimulator service that never answers (a host whose Xcode still needs
    its first-launch setup) skips the launch after the app is built; the
    hosted runners' expected-skip manifest has no such skip, so there it
    still fails the run.
    """
    if _UNANSWERED_SIMCTL:
        pytest.skip(_UNANSWERED_SIMCTL[0])
    # The first simctl call of a run starts CoreSimulator's service, which on
    # a cold hosted runner has outlasted 60 s; booting has its own budget below.
    try:
        listed = _xcrun("simctl", "list", "devices", "available", "--json", timeout=180)
    except subprocess.TimeoutExpired:
        _UNANSWERED_SIMCTL.append("CoreSimulator did not answer simctl list within 180 s on this host")
        pytest.skip(_UNANSWERED_SIMCTL[0])
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


def _project(
    root: Path, manifest: str = MANIFEST, program: str = PROGRAM, header: str = "#import <UIKit/UIKit.h>\n"
) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    (root / "UIKitBinding.h").write_text(header, encoding="utf-8")
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
    frontend: str,
    root: Path,
    source: Path,
    identifier: str,
    btrcc: Path | None,
    sdk: str,
    plist: dict | None = None,
    expected: tuple[str, ...] = ("btrc-",),
) -> str:
    generated = root / "Main.c"
    plan = root / "Main.link.json"
    _transpile(frontend, source, generated, plan, sdk, btrcc)
    bundle = _build_app(root, generated, plan, sdk, identifier, plist)
    device = _simulator()
    installed = _xcrun("simctl", "install", device, str(bundle), timeout=300)
    assert installed.returncode == 0, installed.stderr
    try:
        # simctl's console relay can lose lines of an app that exits moments
        # after printing: a hosted run has shown only the launch line, and one
        # showed the first line without the next. Relaunching until every
        # expected line arrives tells that apart from an app that never
        # printed them, which still fails the caller's assertions.
        for _ in range(3):
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
            if all(line in output for line in expected):
                break
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
    expected = ("btrc-uikit launched", "btrc-uikit active after 1 launch")
    output = _launch(frontend, root, _project(root), f"{BUNDLE_IDENTIFIER}.{frontend}", btrcc, sdk, expected=expected)
    for line in expected:
        assert line in output, output


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
    # Two taps, one edit that cancels itself, nothing after cancellation; the
    # button's receiver is released at cancellation, the field's receiver is
    # still held by this frame's `edit`.
    expected = "btrc-uikit controls taps=2 edits=1 released=1 done=1"
    output = _launch(
        frontend, root, source, f"{BUNDLE_IDENTIFIER}.controls.{frontend}", btrcc, sdk, expected=(expected,)
    )
    assert expected in output, output


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
        assert second, outputs
        written = second.group(1)
        if first is None:
            # simctl's console relay can drop every line of a launch (seen on a
            # hosted runner); the second launch read what the first wrote, so
            # the first launch's file must exist where the second found it.
            assert Path(written).is_file(), outputs
        else:
            assert first.group(1) == written, outputs
        assert written.startswith(os.path.realpath(container) + "/Library/Application Support/") or written.startswith(
            container + "/Library/Application Support/"
        ), (container, written)
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
    expected = (
        "btrc-scene launched",
        "btrc-scene configured",
        "btrc-scene window scene connected key=1",
        "btrc-scene active scenes=1 window=1",
    )
    output = _launch(
        frontend, root, source, f"{BUNDLE_IDENTIFIER}.scenes.{frontend}", btrcc, sdk, manifest, expected=expected
    )
    for line in expected:
        assert line in output, output


# A UIView subclass that hosts a CAMetalLayer (subclass adapters, interop step
# 6): +layerClass names CAMetalLayer through the BTRC factory, -layoutSubviews
# reaches the BTRC receiver, and the NS_REQUIRES_SUPER -updateConstraints sends
# super after it. The scene's window shows the view.
VIEW_MANIFEST = SCENE_MANIFEST.replace(
    'symbols = ["UIApplicationMain", ',
    'symbols = ["-[UIView initWithFrame:]", "+[UIView layerClass]", "-[UIView layoutSubviews]", '
    '"-[UIView updateConstraints]", "-[UIView layer]", "-[UIView setNeedsLayout]", "-[UIView layoutIfNeeded]", '
    '"-[UIView setNeedsUpdateConstraints]", "-[UIView updateConstraintsIfNeeded]", "-[UIWindow addSubview:]", '
    '"-[UIWindow bounds]", "-[CAMetalLayer pixelFormat]", "UIApplicationMain", ',
).replace(
    "[[native.frameworks]]",
    """[native.bindings.callbacks."-[UIView initWithFrame:].self"]
interface = "IMetalView"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
superclass = "UIView"
overrides = ["+[UIView layerClass]", "-[UIView layoutSubviews]", "-[UIView updateConstraints]"]
[[native.frameworks]]
name = "QuartzCore"
os = ["ios"]
[[native.frameworks]]""",
    1,
)

VIEW_PROGRAM = """import Library.Callback;
import ./UIKit.btrc;
#include <stdio.h>
#include <stdlib.h>
int layouts = 0;
int constraints = 0;
class MetalView implements IMetalView {
	public void layoutSubviews() { layouts++; }
	public void updateConstraints() { constraints++; }
}
class MetalViews implements IMetalViewFactory {
	public IMetalView create() { return MetalView(); }
	public string layerClass() { return "CAMetalLayer"; }
}
class Scene implements ISceneDelegate {
	private UIWindow? window = null;
	private UIView? view = null;
	public void scene(UIScene scene, UISceneSession session, UISceneConnectionOptions options) {
		UIWindowScene? windowScene = (UIWindowScene?)scene;
		if (windowScene == null) { exit(4); }
		UIWindow window = UIWindow.initWithWindowScene(windowScene);
		UIView view = UIView.initWithFrame(MetalViews(), window.bounds());
		window.addSubview(view);
		window.makeKeyAndVisible();
		CAMetalLayer? layer = (CAMetalLayer?)view.layer();
		view.setNeedsUpdateConstraints();
		view.updateConstraintsIfNeeded();
		view.setNeedsLayout();
		view.layoutIfNeeded();
		int format = -1;
		if (layer != null) { format = (int)layer.pixelFormat(); }
		printf("btrc-view metal=%d layouts=%d\\n", (int)(layer != null), (int)(layouts > 0));
		printf("btrc-view constraints=%d format=%d\\n", constraints, format);
		fflush(stdout);
		self.window = window;
		self.view = view;
	}
	public void sceneDidBecomeActive(UIScene scene) {
		printf("btrc-view active\\n");
		fflush(stdout);
		exit(0);
	}
	public void sceneDidDisconnect(UIScene scene) {
		self.view = null;
		self.window = null;
	}
}
class Scenes implements ISceneDelegateFactory {
	public ISceneDelegate create() { return Scene(); }
}
class Application implements IApplicationDelegate {
	public void applicationDidFinishLaunching(UIApplication application) {}
	public UISceneConfiguration application(UIApplication application, UISceneSession session, UISceneConnectionOptions options) {
		UISceneConfiguration configuration = UISceneConfiguration.configurationWithName(null, session.role());
		configuration.setDelegateClass(Scenes());
		return configuration;
	}
}
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
"""


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_uikit_metal_view_subclass_runs_through_btrc(frontend, tmp_path: Path, request) -> None:
    """A generated UIView subclass whose +layerClass is CAMetalLayer, shown in the scene's window."""
    sdk = _sdk()
    if sdk is None:
        pytest.skip("the iphonesimulator SDK is Mac-bound (xcrun)")
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    root = tmp_path / "project"
    header = "#import <UIKit/UIKit.h>\n#import <QuartzCore/CAMetalLayer.h>\n"
    source = _project(root, VIEW_MANIFEST, VIEW_PROGRAM, header)
    manifest = {"UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": False}}
    expected = ("btrc-view metal=1 layouts=1", "btrc-view active")
    output = _launch(
        frontend, root, source, f"{BUNDLE_IDENTIFIER}.metal.{frontend}", btrcc, sdk, manifest, expected=expected
    )
    for line in expected:
        assert line in output, output


# The rest of step 6 on UIKit: the application delegate extends UIResponder
# (superclass on an SDK-created form), so UIApplication's next responder is the
# generated delegate and UIResponder's -targetForAction:withSender: asks the
# BTRC override -canPerformAction:withSender:; conformsToProtocol: casts a
# UIView, but not the application, to UITraitEnvironment; and an
# AVAudioSession interruption that a BTRC thread posts reaches a main-executor
# observer on the main queue, which cancels itself. A run-loop timer drives the
# checks, because a launch callout runs inside the main queue, which a nested
# run loop does not drain.
RESPONDER_MANIFEST = """manifest-version = 1
[package]
name = "uikitResponder"
[[native.bindings]]
module = "UIKit"
header = "UIKitBinding.h"
language = "objective-c"
standard = "c11"
os = ["ios"]
symbols = ["UIApplicationMain", "-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]", "-[UIResponder canPerformAction:withSender:]", "-[UIResponder targetForAction:withSender:]", "-[UIApplication nextResponder]", "+[UIView new]", "-[UITraitEnvironment traitCollection]", "-[UITraitCollection displayScale]", "+[AVAudioSession sharedInstance]", "AVAudioSessionInterruptionNotification", "AVAudioSessionInterruptionTypeKey", "+[NSNotificationCenter defaultCenter]", "-[NSNotificationCenter addObserverForName:object:queue:usingBlock:]", "-[NSNotificationCenter removeObserver:]", "-[NSNotificationCenter postNotificationName:object:userInfo:]", "+[NSOperationQueue mainQueue]", "-[NSNotification object]", "-[NSNotification userInfo]", "-[NSDictionary objectForKey:]", "+[NSMutableDictionary dictionary]", "-[NSMutableDictionary setValue:forKey:]", "+[NSNumber numberWithInt:]", "-[NSNumber intValue]", "+[NSThread isMainThread]", "+[NSRunLoop currentRunLoop]", "-[NSRunLoop runUntilDate:]", "+[NSDate dateWithTimeIntervalSinceNow:]", "+[NSTimer scheduledTimerWithTimeInterval:repeats:block:]", "-[NSTimer invalidate]"]
[native.bindings.callbacks."UIApplicationMain.delegateClassName"]
interface = "IApplicationDelegate"
lifetime = "instantiated"
scope = "process"
failure = "abort"
executor = "caller"
superclass = "UIResponder"
methods = ["-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]"]
overrides = ["-[UIResponder canPerformAction:withSender:]"]
[native.bindings.callbacks."-[NSNotificationCenter addObserverForName:object:queue:usingBlock:].block"]
interface = "IInterruptionObserver"
lifetime = "stored"
failure = "abort"
executor = "main"
unregister = "-[NSNotificationCenter removeObserver:]"
activation-failure = "abort"
cancellation = "entry-barrier"
[native.bindings.callbacks."+[NSTimer scheduledTimerWithTimeInterval:repeats:block:].block"]
interface = "IStartTimer"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSTimer invalidate]"
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.bindings]]
module = "Selectors"
header = "Selectors.h"
language = "c"
standard = "c11"
os = ["ios"]
symbols = ["SEL", "sel_registerName"]
read-only-borrows = ["sel_registerName.str"]
[[native.frameworks]]
name = "UIKit"
os = ["ios"]
[[native.frameworks]]
name = "AVFAudio"
os = ["ios"]
[[native.frameworks]]
name = "Foundation"
os = ["ios"]
"""

RESPONDER_PROGRAM = """import Library.Callback;
import ./UIKit.btrc;
import ./Selectors.btrc;
#include <stdio.h>
#include <stdlib.h>
int asked = 0;
int deliveries = 0;
int offMain = 0;
int sessions = 0;
int lastType = -1;
int released = 0;
class Interruption implements IInterruptionObserver {
	private CallbackScope scope;
	public Interruption(CallbackScope scope) { self.scope = scope; }
	public void invoke(NSNotification notification) {
		deliveries++;
		if (!NSThread.isMainThread()) { offMain++; }
		if ((AVAudioSession?)notification.object() != null) { sessions++; }
		NSDictionary? info = notification.userInfo();
		if (info != null) {
			NSNumber? type = (NSNumber?)info.objectForKey(AVAudioSessionInterruptionTypeKey);
			if (type != null) { lastType = type.intValue(); }
		}
		self.scope.cancel();
	}
	public void __del__() { released++; }
}
class Start implements IStartTimer {
	private UIApplication application;
	public Start(UIApplication application) { self.application = application; }
	public void invoke(NSTimer timer) {
		// UIApplication's next responder is the delegate only when it is a UIResponder.
		UIResponder? next = self.application.nextResponder();
		bool target = false;
		if (next != null) { target = next.targetForAction(sel_registerName("btrcProbe:"), null) != null; }
		printf("btrc-responder delegate=%d asked=%d target=%d\\n", (int)(next != null), asked, (int)target);
		UIView view = UIView.new();
		UITraitEnvironment? environment = (UITraitEnvironment?)view;
		UITraitEnvironment? application = (UITraitEnvironment?)self.application;
		bool traits = false;
		if (environment != null) {
			UITraitCollection collection = environment.traitCollection();
			traits = collection.displayScale() >= 0.0;
		}
		printf("btrc-protocol view=%d traits=%d application=%d\\n", (int)(environment != null), (int)traits, (int)(application != null));
		fflush(stdout);
		var scope = CallbackScope();
		ICallbackRegistration observation = NSNotificationCenter.defaultCenter().addObserverForName(AVAudioSessionInterruptionNotification, AVAudioSession.sharedInstance(), NSOperationQueue.mainQueue(), Interruption(scope), scope);
		// AVAudioSession posts from a thread of its own; so does this one, which waits for the main queue.
		var poster = spawn(() => {
				NSMutableDictionary info = NSMutableDictionary.dictionary();
				info.setValue(NSNumber.numberWithInt(1), AVAudioSessionInterruptionTypeKey);
				NSNotificationCenter.defaultCenter().postNotificationName(AVAudioSessionInterruptionNotification, AVAudioSession.sharedInstance(), info);
			});
		for (int index = 0; index < 1000 && deliveries == 0; index++) {
			NSRunLoop.currentRunLoop().runUntilDate(NSDate.dateWithTimeIntervalSinceNow(0.01));
		}
		if (deliveries == 0) {
			printf("btrc-audio no delivery\\n");
			fflush(stdout);
			exit(4);
		}
		poster.join();
		bool done = !observation.isOpen() && scope.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE;
		printf("btrc-audio deliveries=%d main=%d session=%d type=%d released=%d done=%d\\n", deliveries, (int)(offMain == 0), sessions, lastType, released, (int)done);
		fflush(stdout);
		exit(0);
	}
}
class Application implements IApplicationDelegate {
	private CallbackScope timers;
	private ICallbackRegistration? start = null;
	public Application() { self.timers = CallbackScope(); }
	// UIKit may ask about its own actions too; only the probe's counts.
	public bool canPerformAction(SEL action, id? sender) {
		if (action != sel_registerName("btrcProbe:")) { return false; }
		asked++;
		return sender == null;
	}
	public void applicationDidFinishLaunching(UIApplication application) {
		self.start = NSTimer.scheduledTimerWithTimeInterval(0.1, false, Start(application), self.timers);
	}
	public void applicationDidBecomeActive(UIApplication application) {}
}
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
"""


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_uikit_responder_delegate_protocols_and_audio_interruptions(frontend, tmp_path: Path, request) -> None:
    """A UIResponder app delegate, a conformsToProtocol: cast and an AVAudioSession interruption on the main queue."""
    sdk = _sdk()
    if sdk is None:
        pytest.skip("the iphonesimulator SDK is Mac-bound (xcrun)")
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    root = tmp_path / "project"
    header = "#import <UIKit/UIKit.h>\n#import <AVFAudio/AVFAudio.h>\n"
    source = _project(root, RESPONDER_MANIFEST, RESPONDER_PROGRAM, header)
    (root / "Selectors.h").write_text("#include <objc/objc.h>\n", encoding="utf-8")
    (root / "src/Selectors.btrc").write_text("// The Objective-C runtime's selectors.\n", encoding="utf-8")
    expected = (
        "btrc-responder delegate=1 asked=1 target=1",
        "btrc-protocol view=1 traits=1 application=0",
        "btrc-audio deliveries=1 main=1 session=1 type=1 released=1 done=1",
    )
    output = _launch(frontend, root, source, f"{BUNDLE_IDENTIFIER}.responder.{frontend}", btrcc, sdk, expected=expected)
    for line in expected:
        assert line in output, output
