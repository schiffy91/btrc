"""Throwaway CX-UIB-07 macOS evidence; this branch is never merged."""

import json
import subprocess

from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def test_macos_virtual_gpu_accessibility(native_project, native_compile, gui_provider_root, record_property):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Bridge.h").write_text((REPO / "spikes/accessibility-bridges/macos/Bridge.h").read_text())
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "Bridge.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["spikeAccessibilityProbe"]\n'
        '[[native.frameworks]]\nname = "ApplicationServices"\nmodules = ["Main"]\nos = ["macos"]\n'
    )
    source.write_text(
        """import Library.GUI.MacOS.MacOSApplication;
import Library.GUI.MacOS.MacOSGPUSurface;
int main() {
    var app = MacOSApplication();
    var surface = MacOSGPUSurface();
    int result = spikeAccessibilityProbe((void*)surface.nativeView());
    surface.close();
    return result;
}
"""
    )
    plan = root / "Program.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Program.c"
    generated.write_text(result.c_source)
    executable = root / "Program"

    bridge = root / "Bridge.m"
    bridge.write_text((REPO / "spikes/accessibility-bridges/macos/Bridge.m").read_text())
    bridge_object = root / "Bridge.o"
    compiled = subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-isysroot",
            str(sdk),
            "-target",
            triple,
            "-c",
            str(bridge),
            "-o",
            str(bridge_object),
        ],
        env=apple_environment(),
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert compiled.returncode == 0, compiled.stderr

    def runner(command, **kwargs):
        command = list(command)
        if "-o" in command and "-c" not in command:
            command.append(str(bridge_object))
        return subprocess.run(command, env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["virtual_child_attached"] is True
    assert isinstance(evidence["ax_trusted"], bool)
    # JUnit is already uploaded by the unchanged macOS focused workflow.
    # Trust is an observed yes/no, not an assertion that a hosted runner grants it.
    for key, value in evidence.items():
        record_property(key, str(value).lower())
