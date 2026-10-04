"""Throwaway CX-UIB-07 macOS evidence; this branch is never merged."""

import json
import subprocess

from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def test_macos_virtual_gpu_accessibility(native_project, native_compile, gui_provider_root, record_property):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "AccessibilityBridge.h").write_text((REPO / "spikes/accessibility-bridges/macos/Bridge.h").read_text())
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "AccessibilityBridge.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["spikeAccessibilityProbe"]\n'
        '[[native.frameworks]]\nname = "ApplicationServices"\nmodules = ["Main"]\nos = ["macos"]\n'
    )
    source.write_text(
        """import Library.GUI.MacOS.MacOSApplication;
import Library.GUI.MacOS.MacOSGPUSurface;
int main() {
    var app = MacOSApplication();
    var surface = MacOSGPUSurface();
    int result = spikeAccessibilityProbe(surface.nativeView());
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

    def runner(command, **kwargs):
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
