"""Real AppKit UI2 provider regressions; no native probe substitutes an implementation."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
PROBES = ROOT / "src/tests/native/gui/ui2/probes/macos"
CONTAINER_PROBE_SYMBOLS = [
    "+[UI2ContainerProbe childCount:]",
    "+[UI2ContainerProbe arrangedCount:]",
    "+[UI2ContainerProbe observeMutations:]",
    "+[UI2ContainerProbe indexOf:inParent:]",
    "+[UI2ContainerProbe arrangedIndexOf:inStack:]",
    "+[UI2ContainerProbe armOrderFaults:first:second:firstAfter:secondAfter:hideMembership:]",
    "+[UI2ContainerProbe armAttachmentFaults:child:first:second:firstAfter:secondAfter:]",
    "+[UI2ContainerProbe orderCalls]",
    "+[UI2ContainerProbe resetFaults]",
    "+[UI2ContainerProbe openHost]",
    "+[UI2ContainerProbe newField]",
    "+[UI2ContainerProbe newInputView]",
    "+[UI2ContainerProbe newPlainView]",
    "+[UI2ContainerProbe addUnarrangedChild:]",
    "+[UI2ContainerProbe removeForeignChild:]",
    "+[UI2ContainerProbe primaryDown:]",
    "+[UI2ContainerProbe beginEditing:]",
    "+[UI2ContainerProbe editorUnchanged]",
    "+[UI2ContainerProbe editingNotifications]",
    "+[UI2ContainerProbe closeHost]",
]


WINDOW_PROBE_SYMBOLS = [
    "+[UI2WindowProbe initializeAppKit]",
    "+[UI2WindowProbe beginEditing:]",
    "+[UI2WindowProbe editorUnchanged:]",
    "+[UI2WindowProbe requestNativeClose:]",
    "+[UI2WindowProbe closeCount:]",
    "+[UI2WindowProbe setMinimized:value:]",
    "+[UI2WindowProbe awaitMinimized:value:]",
    "+[UI2WindowProbe faultView]",
    "+[UI2WindowProbe setRemovalFault:]",
    "+[UI2WindowProbe restoreFaultViewTo:]",
    "+[UI2WindowProbe resizeNative:]",
    "+[UI2WindowProbe finish]",
]


APPLICATION_QUIT_PROBE_BINDINGS = (
    '[[native.bindings]]\nmodule = "ApplicationQuitProbe"\nheader = "ApplicationQuitProbe.h"\n'
    'language = "c"\nstandard = "c11"\n'
    'symbols = ["ui2RequestNativeApplicationQuit", "ui2NativeApplicationQuitRequests"]\n'
    '[[native.sources]]\npath = "ApplicationQuitProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
)


APPLICATION_QUIT_FIXTURES = {
    "NativeApplicationQuit",
    "NativeApplicationQuitEarlyCancel",
    "NativeApplicationQuitTransactions",
    "NativeApplicationQuitCleanup",
    "NativeApplicationQuitModal",
}

APPLICATION_QUIT_FAULT_BINDINGS = (
    '[[native.bindings]]\nmodule = "ApplicationQuitFaults"\nheader = "ApplicationQuitFaults.h"\n'
    'language = "c"\nstandard = "c11"\n'
    'symbols = ["ui2ArmQuitPublisherFault", "ui2DisarmQuitPublisherFault", "ui2QuitPublisherFaultCount"]\n'
    '[[native.sources]]\npath = "ApplicationQuitFaults.c"\nlanguage = "c"\nstandard = "c11"\n'
)

APPLICATION_QUIT_MODAL_BINDINGS = (
    '[[native.bindings]]\nmodule = "ApplicationQuitModal"\nheader = "ApplicationQuitModal.h"\n'
    'language = "c"\nstandard = "c11"\nsymbols = ["ui2RunNativeQuitModal"]\n'
    '[[native.sources]]\npath = "ApplicationQuitModal.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
)


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("NativeWindowClose", "UI2 native windows preserve cancellable close identity and revision authority"),
        ("NativeWindowState", "UI2 native window snapshots preserve revisions and independent platform state"),
        (
            "NativeApplicationHost",
            "UI2 public application host shares bounded work, worker ingress and native view delivery",
        ),
        (
            "NativeApplicationQuit",
            "UI2 native application quit preserves all dirty windows when one decision cancels",
        ),
        (
            "NativeApplicationQuitEarlyCancel",
            "UI2 native quit cancellation suppresses queued decisions without cancelling handlers",
        ),
        (
            "NativeApplicationQuitTransactions",
            "UI2 native application quit revalidates saves membership and sealed ingress",
        ),
        (
            "NativeApplicationQuitCleanup",
            "UI2 application quit retries native publisher cleanup without reopening ingress",
        ),
        (
            "NativeApplicationQuitModal",
            "UI2 native quit unwinds modal receivers before deferred cancellable decisions",
        ),
        ("RunLoopWake", "UI2 worker wakes idle default and tracking run-loop modes without polling"),
        (
            "RunLoopAttachment",
            "UI2 staged native attachment preserves preattach readiness and rolls back failed admission",
        ),
        ("RunLoopDeadline", "UI2 monotonic deadlines wake default and tracking modes once"),
        ("NativeViewState", "UI2 native view visibility updates revisioned state without inline delivery"),
        ("NativeTreeState", "UI2 native subtree state preserves disabled preference across hide and reattachment"),
        (
            "NativeContainerOrder",
            "UI2 native container transactions preserve editor state and report verified rollback ownership",
        ),
        ("NativeContainerBarrier", "UI2 container barriers defer terminal input and seal reentrant receiver admission"),
        (
            "NativeCaptureFailure",
            "UI2 native capture failures surface after barriers without escaping native callbacks",
        ),
        ("InteractionState", "UI2 view state preserves snapshots and separates observation from input eligibility"),
        ("WorkQueue", "UI2 scheduled work shares capacity, preserves rounds and applies suspension policy"),
        ("Publisher", "UI2 worker publication preserves capacity, receipt identity and cancellation ownership"),
        ("RunLoopLifetime", "UI2 wake cancellation, worker close, native allocation failure and slot reuse drain"),
    ],
)
def test_ui2_native_run_loop_modes(native_project, native_compile, gui_provider_root, sanitize, fixture, expected):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((PROBES / f"{fixture}.btrc").read_text())
    shutil.copyfile(PROBES / "RunLoopProbe.btrc", source.parent / "RunLoopProbe.btrc")
    shutil.copyfile(PROBES / "RunLoopProbe.h", root / "RunLoopProbe.h")
    shutil.copyfile(PROBES / "RunLoopProbe.m", root / "RunLoopProbe.m")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "ui2MacOSRunLoop"\n'
        '[[native.bindings]]\nmodule = "RunLoopProbe"\nheader = "RunLoopProbe.h"\n'
        'language = "c"\nstandard = "c11"\n'
        'symbols = ["ui2RunLoopTurn", "ui2RunLoopIsMainThread", "ui2InitializeAppKit"]\n'
        + ("" if fixture in APPLICATION_QUIT_FIXTURES else '[[native.frameworks]]\nname = "AppKit"\n')
        + '[[native.sources]]\npath = "RunLoopProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    if fixture in {"NativeWindowClose", "NativeWindowState"}:
        shutil.copyfile(PROBES / "WindowProbe.btrc", source.parent / "WindowProbe.btrc")
        for name in ("WindowProbe.h", "WindowProbe.m"):
            shutil.copyfile(PROBES / name, root / name)
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write(
                '[[native.bindings]]\nmodule = "WindowProbe"\nheader = "WindowProbe.h"\n'
                'language = "objective-c"\nstandard = "c11"\n'
                f"symbols = {json.dumps(WINDOW_PROBE_SYMBOLS)}\n"
                '[[native.sources]]\npath = "WindowProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
            )
    if fixture == "NativeApplicationHost":
        shutil.copyfile(PROBES / "ApplicationHostProbe.btrc", source.parent / "ApplicationHostProbe.btrc")
        for name in ("ApplicationHostProbe.h", "ApplicationHostProbe.m"):
            shutil.copyfile(PROBES / name, root / name)
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write(
                '[[native.bindings]]\nmodule = "ApplicationHostProbe"\nheader = "ApplicationHostProbe.h"\n'
                'language = "c"\nstandard = "c11"\n'
                'symbols = ["ui2InstallHostDelegate", "ui2HostDelegateUnchanged", "ui2RestoreHostDelegate", "ui2DispatchHostInput"]\n'
                '[[native.sources]]\npath = "ApplicationHostProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
            )
    if fixture in APPLICATION_QUIT_FIXTURES - {"NativeApplicationQuitCleanup"}:
        shutil.copyfile(PROBES / "ApplicationQuitProbe.btrc", source.parent / "ApplicationQuitProbe.btrc")
        for name in ("ApplicationQuitProbe.h", "ApplicationQuitProbe.m"):
            shutil.copyfile(PROBES / name, root / name)
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write(APPLICATION_QUIT_PROBE_BINDINGS)
    if fixture == "NativeApplicationQuitCleanup":
        shutil.copyfile(PROBES / "ApplicationQuitFaults.btrc", source.parent / "ApplicationQuitFaults.btrc")
        for name in ("ApplicationQuitFaults.h", "ApplicationQuitFaults.c"):
            shutil.copyfile(PROBES / name, root / name)
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write(APPLICATION_QUIT_FAULT_BINDINGS)
    if fixture == "NativeApplicationQuitModal":
        shutil.copyfile(PROBES / "ApplicationQuitModal.btrc", source.parent / "ApplicationQuitModal.btrc")
        for name in ("ApplicationQuitModal.h", "ApplicationQuitModal.m"):
            shutil.copyfile(PROBES / name, root / name)
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write(APPLICATION_QUIT_MODAL_BINDINGS)
    if fixture in {"NativeContainerOrder", "NativeContainerBarrier"}:
        shutil.copyfile(PROBES / "ContainerProbe.btrc", source.parent / "ContainerProbe.btrc")
        for name in ("ContainerProbe.h", "ContainerProbe.m"):
            shutil.copyfile(PROBES / name, root / name)
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write(
                '[[native.bindings]]\nmodule = "ContainerProbe"\nheader = "ContainerProbe.h"\n'
                'language = "objective-c"\nstandard = "c11"\n'
                f"symbols = {json.dumps(CONTAINER_PROBE_SYMBOLS)}\n"
                '[[native.sources]]\npath = "ContainerProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
            )
    plan = root / "RunLoop.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "RunLoop.c"
    generated.write_text(compiled.c_source)
    executable = root / "RunLoop"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    environment = apple_environment()
    if fixture in {"RunLoopLifetime", "RunLoopAttachment"}:
        faults = root / "RunLoopFaults.dylib"
        built = runner(
            [
                "/usr/bin/clang",
                "-std=c11",
                "-dynamiclib",
                "-framework",
                "CoreFoundation",
                str(PROBES / "RunLoopFaults.c"),
                "-o",
                str(faults),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        (root / "fault-build.stdout").write_text(built.stdout)
        (root / "fault-build.stderr").write_text(built.stderr)
        assert built.returncode == 0, (built.returncode, built.stdout, built.stderr)
        previous = environment.get("DYLD_INSERT_LIBRARIES")
        environment["DYLD_INSERT_LIBRARIES"] = f"{previous}:{faults}" if previous else str(faults)
    try:
        completed = subprocess.run(
            [str(executable)], cwd=root, env=environment, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired as error:
        for suffix, output in (("stdout", error.stdout), ("stderr", error.stderr)):
            (root / f"run.{suffix}").write_bytes(output if isinstance(output, bytes) else (output or "").encode())
        raise
    (root / "run.stdout").write_text(completed.stdout)
    (root / "run.stderr").write_text(completed.stderr)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert expected in completed.stdout
