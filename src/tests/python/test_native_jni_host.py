"""Library.Java on a host JVM: the VM owner, its environment key and its limits.

Interop step 4 (docs/design/native-interop-ownership.md section 2.3). A BTRC
program starts JDK 17's HotSpot under -Xcheck:jni through
Library.Java.JavaVirtualMachine, and shuts it down from the creating thread
once no reference is alive. The flake's btrc-jni pkg-config package supplies
the JDK's headers and libjvm.
"""

import os
import subprocess
import sys

import pytest

from src.tests.dependencies import BinaryImports, DependencyAudit
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.jni_host_fixtures import desktop_compiler, desktop_dependency, require_desktop_jdk
from src.tests.python.jni_host_fixtures import desktop_jni_source as desktop_jni_source
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from tools.native_plan import NativePlanBuilder

LIFECYCLE = """import JavaHost.JavaVirtualMachine;
import Library.Vector;
#include <assert.h>
#include <stdlib.h>
int main(int argc, char** argv) {
	assert(argc == 2);
	int mode = atoi(argv[1]);
	assert(!JavaVirtualMachine.running());
	Vector<string> options = ["-Xcheck:jni"];
	JavaVirtualMachine.createHost(options);
	assert(JavaVirtualMachine.running());
	assert(JavaVirtualMachine.liveClaims() == 0 && JavaVirtualMachine.attachedThreads() == 0);
	if (mode == 1) {
		Vector<string> none = [];
		JavaVirtualMachine.createHost(none);
	}
	if (mode == 2) {
		bool rejected = false;
		try { JavaVirtualMachine.shutdown(); JavaVirtualMachine.shutdown(); }
		catch (string error) { rejected = true; }
		return rejected ? 0 : 1;
	}
	JavaVirtualMachine.shutdown();
	assert(!JavaVirtualMachine.running());
	printf("jvm-ok\\n");
	return 0;
}
"""


@pytest.fixture
def jvm_project(desktop_jni_source):
    require_desktop_jdk()
    environment = apple_environment()
    source = desktop_jni_source
    root = source.parent.parent
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "jvmHost"\n' + desktop_dependency(root), encoding="utf-8"
    )
    return source, environment


def build(source, native_compile, environment):
    root = source.parent.parent
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = root / "Program"

    def run(command, **kwargs):
        if os.path.basename(command[0]).startswith("clang"):
            command = [command[0], "-O2", *command[1:]]
        return subprocess.run(command, env=environment, **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc=desktop_compiler(), cxx=desktop_compiler(cxx=True)
    )
    return executable


def test_host_jvm_lifecycle(jvm_project, native_compile):
    source, environment = jvm_project
    source.write_text(LIFECYCLE, encoding="utf-8")
    executable = build(source, native_compile, environment)
    assert any(name.rsplit("/", 1)[-1] in {"libjvm.so", "libjvm.dylib"} for name in BinaryImports.read(executable))
    for mode, returncode, stdout, message in (
        (0, 0, "jvm-ok\n", ""),
        (1, -6, "", "a process runs at most one Java VM"),
        (2, -6, "", "no Java VM is running"),
    ):
        completed = subprocess.run(
            [str(executable), str(mode)],
            env={key: value for key, value in environment.items() if key != "JAVA_TOOL_OPTIONS"},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == returncode, (mode, completed.stdout, completed.stderr)
        assert completed.stdout == stdout, (mode, completed.stdout)
        assert message in completed.stderr, (mode, completed.stderr)
        # -Xcheck:jni reports every JNI misuse as a warning on stdout or stderr.
        assert "WARNING" not in completed.stdout + completed.stderr, (mode, completed.stderr)
        assert "FATAL ERROR" not in completed.stdout + completed.stderr, (mode, completed.stderr)
    assert os.environ.get("BTRC_JAVA_CLASS_READER"), "the dev shell exports the Java class reader"


def test_desktop_stdlib_without_jdk(desktop_jni_source, native_compile, monkeypatch):
    source = desktop_jni_source
    root = source.parent.parent
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "standalone"\n', encoding="utf-8")
    for key in ("JAVA_HOME", "BTRC_JAVA_CLASS_READER", "BTRC_JAVA_CLASSPATH", "JAVA_TOOL_OPTIONS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PKG_CONFIG_PATH", "")
    monkeypatch.setenv("PKG_CONFIG_LIBDIR", str(root / "no-packages"))
    source.write_text(
        "import Library.Vector;\nint main() { Vector<int> values = [41, 1]; return values.get(0) + values.get(1) - 42; }\n"
    )
    executable = build(source, native_compile, dict(os.environ))
    subprocess.run([str(executable)], check=True, timeout=TOOL_TIMEOUT)
    assert "btrc-jni" not in (root / "Program.link.json").read_text()
    target = "macos" if sys.platform == "darwin" else "linux"
    assert not DependencyAudit().binary_problems(executable, target)
    source.write_text("import Library.Java.JavaVirtualMachine;\nint main() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert "has no provider for target" in str(result.failure) + str(result.diagnostics)
