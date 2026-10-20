"""Weak census of actual Select/Slider owners, without presenting native UI."""

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_ui2_control_lifetime(native_project, native_compile, gui_provider_root, sanitized):
    fixture = "UI2MacOSControlLifetime"
    source, _, _ = native_project
    package = source.parent.parent
    root = Path(__file__).resolve().parents[3]
    fixtures = root / "src/tests/native/gui/ui2/probes/macos"
    for suffix in ("h", "m"):
        name = f"{fixture}.{suffix}"
        (package / name).write_text((fixtures / name).read_text())
    symbols = [
        "+[BTRCUI2ControlLifetimeProbe runCycle:callback:]",
        "+[BTRCUI2ControlLifetimeProbe host:slider:]",
        "+[BTRCUI2ControlLifetimeProbe observe:slider:generation:]",
        "+[BTRCUI2ControlLifetimeProbe choose:]",
        "+[BTRCUI2ControlLifetimeProbe increment:]",
        "+[BTRCUI2ControlLifetimeProbe finish]",
    ]
    manifest = package / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + f'\n[[native.bindings]]\nmodule = "Main"\nheader = "{fixture}.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[native.bindings.callbacks."+[BTRCUI2ControlLifetimeProbe runCycle:callback:].callback"]\n'
        'interface = "IControlLifetimeCycle"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        f'[[native.sources]]\npath = "{fixture}.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    source.write_text((fixtures / f"{fixture}.btrc").read_text())
    plan = package / "Lifetime.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "Lifetime.c"
    generated.write_text(result.c_source)
    executable = package / "Lifetime"

    def runner(command, **kwargs):
        flags = []
        if sanitized and Path(command[0]).name in {"clang", "clang++"}:
            flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    ran = subprocess.run(
        [str(executable)],
        env=apple_environment() | {"BTRC_GUI_BACKGROUND": "1"},
        capture_output=True,
        text=True,
        timeout=300,
    )
    (package / "control-lifetime.stdout.txt").write_text(ran.stdout)
    (package / "control-lifetime.stderr.txt").write_text(ran.stderr)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    rows = [
        json.loads(line.removeprefix("CONTROL_LIFETIME "))
        for line in ran.stdout.splitlines()
        if line.startswith("CONTROL_LIFETIME ")
    ]
    assert [row["cycle"] for row in rows] == list(range(1, 101))
    expected = {
        "host": 1,
        "select": 1,
        "select-cell": 1,
        "menu": 2,
        "item": 4,
        "presentation": 2,
        "slider": 1,
        "slider-cell": 1,
    }
    for row in rows:
        assert row["counts"] == expected and row["survivors"] == 0
        assert row["drain_turns"] >= 10 and row["drain_seconds"] >= 0 and row["drain_deadline_seconds"] == 2
        assert set(row["classes"]) == set(expected)
        for role, count in expected.items():
            classes = row["classes"][role]
            assert classes and all(
                isinstance(name, str) and name and type(value) is int and value > 0 for name, value in classes.items()
            )
            assert sum(classes.values()) == count
    assert "PASS: macOS Select and Slider native lifetime cycles=100" in ran.stdout
