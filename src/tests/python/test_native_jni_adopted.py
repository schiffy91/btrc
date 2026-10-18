"""Library.Java inside a host `java` process: the VM is adopted at JNI_OnLoad, never created.

Interop step 4 (docs/design/native-interop-ownership.md section 2.3). The java
launcher is the desktop analog of Android's app_process: it starts JDK 17's
HotSpot under -Xcheck:jni and System.loads a library holding the BTRC program,
Library.Java's runtime and a JNI harness (jni_adoption_fixtures.py). JNI_OnLoad
adopts the running VM and a native method runs the program on the Java main
thread, through both compilers. Any CheckJNI warning fails. The program also
proves what an adopted VM refuses: shutting it down, a second VM and VM
options each terminate before any Java call.

Interop step 7, slice A: the program registers BTRC receivers for Java
natives through RegisterNatives and Java calls them back (nested, with a BTRC
exception surfacing as a RuntimeException, cancellation as an entry barrier,
and on a BTRC thread), and the application classes load through their own
URLClassLoader, so a thread the runtime attaches resolves them only through
the ClassLoader cached at JNI_OnLoad. A native called off its registering
thread, and a BTRC exception escaping an abort-failure native, terminate.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.jni_adoption_fixtures import (
    ENTRY_CLASS,
    LIBRARY_NAME,
    REFUSALS,
    ROUND_TRIP_LINES,
    build_library,
    missing_java_tools,
    write_project,
)
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project


def host_java():
    """The `java` of the JDK btrc-jni links, so the launcher and the library share one libjvm."""
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "btrc-jni"], check=False, timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the btrc-jni pkg-config package (the flake's dev shell provides JDK 17)")
    flags = subprocess.run(
        ["pkg-config", "--libs-only-L", "btrc-jni"], capture_output=True, text=True, check=True, timeout=TOOL_TIMEOUT
    ).stdout.split()
    (server,) = [Path(flag[2:]) for flag in flags if flag.startswith("-L")]
    java = server.parents[1] / "bin" / "java"
    assert java.is_file(), f"btrc-jni's JDK has no launcher at {java}"
    return java


@pytest.fixture
def adopted_project(native_project, monkeypatch):
    java = host_java()
    missing = missing_java_tools()
    if missing:
        pytest.skip(missing)
    source, _, _ = native_project
    root = source.parent.parent
    (source.parent / "Foundation.btrc").unlink()
    source, classes = write_project(root)
    monkeypatch.setenv("BTRC_JAVA_CLASSPATH", str(classes / "app"))
    return source, classes, java


def test_java_process_adopts_its_vm_under_checkjni(adopted_project, native_compile):
    source, classes, java = adopted_project
    root = source.parent.parent
    environment = apple_environment()
    compiled = native_compile(source, plan_path=root / "Program.link.json")
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    # Java natives bind through RegisterNatives, never the thread-invoke seam.
    assert "btrcJavaRegisterNatives" in compiled.c_source and "__btrc_native_thread_invoke" not in compiled.c_source
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    library = build_library(compiled, root, root / f"lib{LIBRARY_NAME}{suffix}", environment, cc="/usr/bin/clang")

    def run(mode):
        # The application classes load through their own class loader (JniEntry's third argument).
        return subprocess.run(
            [
                str(java),
                "-Xcheck:jni",
                "-cp",
                str(classes / "entry"),
                ENTRY_CLASS,
                str(library),
                str(mode),
                str(classes / "app"),
            ],
            env={key: value for key, value in environment.items() if key != "JAVA_TOOL_OPTIONS"},
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    completed = run(0)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    pid, *lines = completed.stdout.splitlines()
    assert pid.startswith("btrc-pid=") and lines == ROUND_TRIP_LINES, completed.stdout
    # -Xcheck:jni reports every JNI misuse as a warning on stdout or stderr.
    assert "WARNING" not in completed.stdout + completed.stderr, completed.stderr
    assert "FATAL ERROR" not in completed.stdout + completed.stderr, completed.stderr

    for mode, message in REFUSALS.items():
        refused = run(mode)
        assert refused.returncode == -6, (mode, refused.stdout, refused.stderr)
        assert message in refused.stderr, (mode, refused.stderr)
        assert "java-adopted-ok" not in refused.stdout and "java-entry-status" not in refused.stdout, mode
        assert "WARNING" not in refused.stdout + refused.stderr, (mode, refused.stderr)
