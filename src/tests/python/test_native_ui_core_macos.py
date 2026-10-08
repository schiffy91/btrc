"""Real AppKit UI2 provider regressions; no native probe substitutes an implementation."""

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


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("RunLoopWake", "UI2 worker wakes idle default and tracking run-loop modes without polling"),
        ("RunLoopDeadline", "UI2 monotonic deadlines wake default and tracking modes once"),
        ("WorkQueue", "UI2 scheduled work shares capacity, preserves rounds and applies suspension policy"),
        ("RunLoopLifetime", "UI2 wake cancellation, worker close, native allocation failure and slot reuse drain"),
    ],
)
def test_ui2_native_run_loop_modes(native_project, native_compile, gui_provider_root, sanitize, fixture, expected):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((PROBES / f"{fixture}.btrc").read_text())
    shutil.copyfile(PROBES / "RunLoopProbe.btrc", source.parent / "RunLoopProbe.btrc")
    shutil.copyfile(PROBES / "RunLoopProbe.h", root / "RunLoopProbe.h")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "ui2MacOSRunLoop"\n'
        '[[native.bindings]]\nmodule = "RunLoopProbe"\nheader = "RunLoopProbe.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        'symbols = ["ui2RunLoopTurn", "ui2RunLoopIsMainThread"]\n'
        '[[native.frameworks]]\nname = "AppKit"\n'
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
    if fixture == "RunLoopLifetime":
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
