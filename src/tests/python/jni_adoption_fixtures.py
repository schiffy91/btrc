"""A BTRC program inside a Java VM it did not create: the adopted-VM JNI fixture.

Interop step 4's exit (docs/design/native-interop-ownership.md section 2.3 and
the step table): a library a running VM loads adopts that VM at JNI_OnLoad
(btrcJavaAdopt), and a native method runs the BTRC program, compiled with
-Dmain=btrc_program_main (WORKSTREAMS.md Q18), on the calling Java thread. The
program makes checked JNI calls back into Java through a generated binding:
a string round trip, a static field, a Java exception, a BTRC thread that
attaches and detaches, and 10,000 object-returning calls with no frame leak,
ending with no live claim. It never creates or destroys the VM.

A host `java` process (test_native_jni_adopted.py) and Android's app_process
(test_native_jni_android.py) load the same sources; each test supplies its own
toolchain and runner.
"""

import os
import shutil
import subprocess
from pathlib import Path

from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]
JNI_HEADER = REPO / "src" / "stdlib" / "Java" / "JNI.h"
ENTRY_CLASS = "dev.btrc.fixture.JniEntry"
LIBRARY_NAME = "BtrcAdopted"

# The bound class. collected() asks Runtime.gc() for a collection: ART's
# System.gc() only requests one after finalization has run.
HOST = """package dev.btrc.fixture;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.List;

public class JniHost {
    public static final int LIMIT = 41;
    public static String label = "start";
    private static final List<WeakReference<JniHost>> made = new ArrayList<>();
    private final int amount;

    public JniHost(int amount) {
        this.amount = amount;
    }

    public static int twice(int value) {
        return value * 2;
    }

    public int value() {
        return amount;
    }

    public JniHost add(JniHost other) {
        return new JniHost(amount + other.amount);
    }

    public static boolean isExpected(String text) {
        return "a\\u00e9\\uD834\\uDD1E".equals(text);
    }

    public static int units(String text) {
        return text == null ? -1 : text.length();
    }

    public static String echo(String text) {
        return text;
    }

    public static String withNul() {
        return "a\\u0000b";
    }

    public static void fail(String message) {
        throw new IllegalStateException(message);
    }

    public static JniHost make(int value) {
        JniHost made = new JniHost(value);
        JniHost.made.add(new WeakReference<>(made));
        return made;
    }

    /** How many made objects the collector has reclaimed: none survives a leaked reference. */
    public static int collected() throws InterruptedException {
        int cleared = 0;
        for (int attempt = 0; attempt < 40; attempt++) {
            Runtime.getRuntime().gc();
            cleared = 0;
            for (WeakReference<JniHost> reference : made) {
                if (reference.get() == null) {
                    cleared++;
                }
            }
            if (cleared == made.size()) {
                break;
            }
            Thread.sleep(50);
        }
        return cleared;
    }

    public static boolean daemonThread() {
        return Thread.currentThread().isDaemon();
    }
}
"""

# The process's Java entry: load the library (JNI_OnLoad adopts the VM), then
# run the BTRC program on this thread. A negative mode runs the CheckJNI probe.
ENTRY = """package dev.btrc.fixture;

public final class JniEntry {
    private JniEntry() {
    }

    private static native int run(int mode);

    private static native int probe();

    public static void main(String[] arguments) {
        System.load(arguments[0]);
        int mode = Integer.parseInt(arguments[1]);
        int status = mode < 0 ? probe() : run(mode);
        System.out.print("java-entry-status=");
        System.out.println(status);
        System.exit(status);
    }
}
"""

JAVA_SOURCES = {"dev/btrc/fixture/JniHost.java": HOST, "dev/btrc/fixture/JniEntry.java": ENTRY}

SYMBOLS = [
    "dev.btrc.fixture.JniHost",
    "dev.btrc.fixture.JniHost.<init>(I)V",
    "dev.btrc.fixture.JniHost.twice(I)I",
    "dev.btrc.fixture.JniHost.value()I",
    "dev.btrc.fixture.JniHost.add(Ldev/btrc/fixture/JniHost;)Ldev/btrc/fixture/JniHost;",
    "dev.btrc.fixture.JniHost.isExpected(Ljava/lang/String;)Z",
    "dev.btrc.fixture.JniHost.units(Ljava/lang/String;)I",
    "dev.btrc.fixture.JniHost.echo(Ljava/lang/String;)Ljava/lang/String;",
    "dev.btrc.fixture.JniHost.withNul()Ljava/lang/String;",
    "dev.btrc.fixture.JniHost.fail(Ljava/lang/String;)V",
    "dev.btrc.fixture.JniHost.make(I)Ldev/btrc/fixture/JniHost;",
    "dev.btrc.fixture.JniHost.collected()I",
    "dev.btrc.fixture.JniHost.daemonThread()Z",
    "dev.btrc.fixture.JniHost.LIMIT:I",
    "dev.btrc.fixture.JniHost.label:Ljava/lang/String;",
]

# Mode 0 is the round trip. Modes 1-3 are what an adopted VM refuses, each
# before any Java call: shutting it down, a second VM, and VM options.
PROGRAM = """import Library.Java.JavaVirtualMachine;
import Library.Vector;
import ./Fixture.btrc;
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

int callFromThread() {
	assert(JniHost.daemonThread());
	return JniHost.twice(4);
}

void exercise() {
	assert(JniHost.twice(21) == 42);
	assert(JniHost.LIMIT() == 41);
	string? label = JniHost.label();
	assert(label != null && label.equals("start"));
	JniHost.setLabel("aé𝄞");
	string? changed = JniHost.label();
	assert(changed != null && changed.equals("aé𝄞"));
	JniHost.setLabel(null);
	assert(JniHost.label() == null);

	JniHost two = JniHost.create(2);
	JniHost? sum = two.add(JniHost.create(3));
	assert(sum != null && sum.value() == 5);
	assert(JavaVirtualMachine.liveClaims() == 2);

	assert(JniHost.isExpected("aé𝄞"));
	assert(JniHost.units("aé𝄞") == 4);
	assert(JniHost.units(null) == -1);
	string? back = JniHost.echo("aé𝄞");
	assert(back != null && back.equals("aé𝄞"));
	bool nul = false;
	try { JniHost.withNul(); }
	catch (string error) { nul = error.equals("Java string contains U+0000, which a BTRC string cannot hold"); }
	assert(nul);
	string failure = "";
	try { JniHost.fail("boom"); }
	catch (string error) { failure = error; }
	assert(failure.equals("JavaException: java.lang.IllegalStateException: boom"));

	for (int index = 0; index < 10000; index++) {
		JniHost? made = JniHost.make(index);
		assert(made != null && made.value() == index);
	}
	sum.close();
	assert(JavaVirtualMachine.liveClaims() == 1);

	Thread<int> worker = spawn(() => callFromThread());
	assert(worker.join() == 8);
}

int main(int argc, char** argv) {
	assert(argc == 2);
	int mode = atoi(argv[1]);
	assert(JavaVirtualMachine.running() && JavaVirtualMachine.adopted());
	if (mode == 1) { JavaVirtualMachine.shutdown(); }
	if (mode == 2) {
		Vector<string> none = [];
		JavaVirtualMachine.createHost(none);
	}
	if (mode == 3) {
		Vector<string> options = ["-Xcheck:jni"];
		JavaVirtualMachine.createHost(options);
	}
	exercise();
	assert(JniHost.collected() == 10000);
	assert(JavaVirtualMachine.liveClaims() == 0);
	assert(JavaVirtualMachine.attachedThreads() == 0);
	assert(JavaVirtualMachine.running() && JavaVirtualMachine.adopted());
	printf("java-adopted-ok\\n");
	return 0;
}
"""

REFUSALS = {
    1: "an adopted Java VM belongs to its host and is never destroyed",
    2: "a process runs at most one Java VM",
    3: "an adopted Java VM takes no options; its host started it",
}

HARNESS = """/* The JNI entry of a library a running VM loads. JNI_OnLoad adopts the VM;
 * JniEntry.run executes the BTRC program, whose main is compiled as
 * btrc_program_main, on the calling Java thread. */
#define _POSIX_C_SOURCE 200809L
#include "JNI_HEADER"
#include <stdio.h>
#include <unistd.h>

int btrc_program_main(int argc, char** argv);

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* machine, void* reserved) {
	(void)reserved;
	return btrcJavaAdopt(machine) == JNI_OK ? JNI_VERSION_1_6 : JNI_ERR;
}

JNIEXPORT jint JNICALL Java_dev_btrc_fixture_JniEntry_run(JNIEnv* env, jclass entry, jint mode) {
	(void)env;
	(void)entry;
	char name[] = "JniEntry";
	char selected[16];
	snprintf(selected, sizeof selected, "%d", (int)mode);
	char* arguments[] = {name, selected, NULL};
	printf("btrc-pid=%ld\\n", (long)getpid());
	fflush(stdout);
	int status = btrc_program_main(2, arguments);
	fflush(stdout);
	return status;
}

/* A misuse only CheckJNI reports: FindClass takes a slash-separated binary
 * name. Under CheckJNI the dotted name aborts the process; without it the
 * lookup fails with an ordinary NoClassDefFoundError, cleared here. */
JNIEXPORT jint JNICALL Java_dev_btrc_fixture_JniEntry_probe(JNIEnv* env, jclass entry) {
	(void)entry;
	printf("btrc-pid=%ld\\n", (long)getpid());
	fflush(stdout);
	jclass found = (*env)->FindClass(env, "java.lang.String");
	if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionClear(env); }
	if (found != NULL) { (*env)->DeleteLocalRef(env, found); }
	return 0;
}
"""


def manifest():
    listed = ", ".join(f'"{symbol}"' for symbol in SYMBOLS)
    return (
        'manifest-version = 1\n[package]\nname = "javaAdopted"\n'
        f'[[native.bindings]]\nmodule = "Fixture"\nlanguage = "java"\nsymbols = [{listed}]\n'
        '[[native.sources]]\npath = "Harness.c"\nlanguage = "c"\nstandard = "c11"\n'
    )


def write_project(root):
    """Write the project under `root` and compile its Java classes; returns (Main.btrc, classes)."""
    classes = root / "classes"
    sources = []
    for name, text in JAVA_SOURCES.items():
        path = root / "java" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        sources.append(str(path))
    subprocess.run(
        ["javac", "--release", "17", "-encoding", "UTF-8", "-d", str(classes), *sources],
        check=True,
        capture_output=True,
        timeout=600,
    )
    (root / "src").mkdir(exist_ok=True)
    (root / "btrc.toml").write_text(manifest(), encoding="utf-8")
    (root / "Harness.c").write_text(HARNESS.replace("JNI_HEADER", str(JNI_HEADER)), encoding="utf-8")
    (root / "src" / "Fixture.btrc").write_text("// The Java binding's module.\n", encoding="utf-8")
    source = root / "src" / "Main.btrc"
    source.write_text(PROGRAM, encoding="utf-8")
    return source, classes


class SharedLibraryRunner:
    """Runs a NativePlanBuilder's commands so they link a JNI library, not an executable.

    Every compile is position-independent, the program's own unit renames
    main to btrc_program_main, and the link adds -shared plus `link_flags`.
    Every other command runs unchanged.
    """

    def __init__(self, generated, environment, *, compile_flags=(), link_flags=()):
        self.generated = Path(generated).resolve()
        self.environment = environment
        self.compile_flags = list(compile_flags)
        self.link_flags = list(link_flags)

    def __call__(self, command, **kwargs):
        # A compile ends with `-c <source> -o <object>`; the link ends with `-o <output>`.
        if len(command) > 4 and command[-4] == "-c" and command[-2] == "-o":
            flags = ["-fPIC", *self.compile_flags]
            if Path(command[-3]).resolve() == self.generated:
                flags.append("-Dmain=btrc_program_main")
            command = [*command[:-4], *flags, *command[-4:]]
        elif len(command) > 2 and command[-2] == "-o" and "-c" not in command:
            command = [*command[:-2], "-shared", *self.link_flags, *command[-2:]]
        return subprocess.run(command, env=self.environment, **kwargs)


def build_library(compiled, root, output, environment, *, cc="cc", compile_flags=(), link_flags=()):
    """Link a compiled program, its JNI runtime and the harness into the shared library `output`."""
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    plan = root / "Program.link.json"
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    runner = SharedLibraryRunner(generated, environment, compile_flags=compile_flags, link_flags=link_flags)
    NativePlanBuilder(runner=runner).build(plan_path=plan, generated_c=generated, output=output, cc=cc, cxx=cc)
    return output


def missing_java_tools():
    """Why the JDK's javac or the binding's Java class reader is unavailable, or None."""
    if not shutil.which("javac") or not os.environ.get("BTRC_JAVA_CLASS_READER"):
        return "requires javac and BTRC_JAVA_CLASS_READER (the flake's dev shell provides both)"
    return None
