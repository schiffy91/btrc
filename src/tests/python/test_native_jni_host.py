"""Library.Java on a host JVM: the VM owner, its environment key and its limits.

Interop step 4 (docs/design/native-interop-ownership.md section 2.3). A BTRC
program starts JDK 17's HotSpot under -Xcheck:jni through
Library.Java.JavaVirtualMachine, and shuts it down from the creating thread
once no reference is alive. The flake's btrc-jni pkg-config package supplies
the JDK's headers and libjvm.
"""

import os
import shutil
import subprocess

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

LIFECYCLE = """import Library.Java.JavaVirtualMachine;
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


def jni_environment():
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "btrc-jni"], check=False, timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the btrc-jni pkg-config package (the flake's dev shell provides JDK 17)")
    return apple_environment()


@pytest.fixture
def jvm_project(native_project):
    environment = jni_environment()
    source, _, _ = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "jvmHost"\n', encoding="utf-8")
    (source.parent / "Foundation.btrc").unlink()
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
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    return executable


def test_host_jvm_lifecycle(jvm_project, native_compile):
    source, environment = jvm_project
    source.write_text(LIFECYCLE, encoding="utf-8")
    executable = build(source, native_compile, environment)
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
