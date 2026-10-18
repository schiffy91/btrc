"""A BTRC program inside a Java VM it did not create: the adopted-VM JNI fixture.

Interop step 4's exit (docs/design/native-interop-ownership.md section 2.3 and
the step table): a library a running VM loads adopts that VM at JNI_OnLoad
(btrcJavaAdopt), and a native method runs the BTRC program, compiled with
-Dmain=btrc_program_main (WORKSTREAMS.md Q18), on the calling Java thread. The
program makes checked JNI calls back into Java through a generated binding:
a string round trip, a static field, a Java exception, a BTRC thread that
attaches and detaches, and 10,000 object-returning calls with no frame leak,
ending with no live claim. It never creates or destroys the VM.

Interop step 7, slice A: the program also registers BTRC receivers for Java
`native` methods (`natives`, RegisterNatives), and Java calls them: every
primitive, strings both ways through UTF-16, objects as owners both ways, an
instance native, Java -> BTRC -> Java -> BTRC nesting, a BTRC exception
surfacing in Java as a RuntimeException, a receiver that cancels its own
registration inside a call, a call after cancellation that never enters BTRC,
and a BTRC thread that registers natives of its own and is called back on
itself. Modes 4 and 5 are what terminates: a native called on a thread other
than its registration's, and a BTRC exception escaping an abort-failure
native.

The application classes load through their own class loader on a host JVM
(JniEntry's third argument), so a BTRC thread the runtime attaches resolves
them only through the application ClassLoader cached at JNI_OnLoad, never
FindClass (section 2.3, "VM lifetime").

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

# The natives a BTRC registration binds (RegisterNatives), and the Java
# callers through which BTRC reaches them.
CALLBACKS = """package dev.btrc.fixture;

public class JniCallbacks {
    private final int factor;

    public JniCallbacks(int factor) {
        this.factor = factor;
    }

    public int factor() {
        return factor;
    }

    public static native int compute(int value);

    public static native long widen(byte b, short s, char c, boolean z, float f, double d, long j);

    public static native String greet(String name);

    public static native int depth(int level);

    public static native JniHost wrap(JniHost host);

    public static native void fail(String message);

    public static native boolean stop();

    public native int scale(int value);

    /** Not native: only the ACC_NATIVE rejection names it. */
    public static int plain(int value) {
        return value;
    }

    /** Natives only the rejection cases name: an array, and an overload of compute. */
    public static native int sum(int[] values);

    public static native long compute(long value);

    public static int callCompute(int value) {
        return compute(value);
    }

    public static long callWiden() {
        return widen((byte) 1, (short) 2, (char) 3, true, 4.5f, 5.5, 6000000000L);
    }

    public static String callGreet(String name) {
        return greet(name);
    }

    public static String callGreetNul() {
        return greet("a\\u0000b");
    }

    public static int nest(int level) {
        return depth(level);
    }

    public static int callWrap(int value) {
        JniHost made = wrap(new JniHost(value));
        return made == null ? -1 : made.value();
    }

    public static boolean callWrapNull() {
        return wrap(null) == null;
    }

    public static void relay(String message) {
        fail(message);
    }

    public static boolean callStop() {
        return stop();
    }

    public static int callScale(int factor, int value) {
        return new JniCallbacks(factor).scale(value);
    }
}
"""

# A natives class a BTRC thread registers on itself, with failure = "abort".
WORKER = """package dev.btrc.fixture;

public class JniWorker {
    public static native int twice(int value);

    public static int callTwice(int value) {
        return twice(value);
    }
}
"""

# The library's Java side: start() loads it (JNI_OnLoad adopts the VM), then
# runs the BTRC program on this thread. A negative mode runs the CheckJNI probe.
APP = """package dev.btrc.fixture;

public final class JniApp {
    private JniApp() {
    }

    private static native int run(int mode);

    private static native int probe();

    public static int start(String library, int mode) {
        System.load(library);
        return mode < 0 ? probe() : run(mode);
    }
}
"""

# The process's entry, on the system class path. Given a third argument, it
# loads the application classes through their own class loader, the one an
# application's own classes have, and makes it the thread's context class
# loader, as an Android application's main thread has; else its own loader
# holds them (app_process).
ENTRY = """package dev.btrc.fixture;

import java.io.File;
import java.net.URL;
import java.net.URLClassLoader;

public final class JniEntry {
    private JniEntry() {
    }

    public static void main(String[] arguments) throws Exception {
        ClassLoader loader = JniEntry.class.getClassLoader();
        if (arguments.length > 2) {
            loader = new URLClassLoader(new URL[] {new File(arguments[2]).toURI().toURL()}, loader);
            Thread.currentThread().setContextClassLoader(loader);
        }
        Class<?> application = Class.forName("dev.btrc.fixture.JniApp", true, loader);
        Object result = application.getMethod("start", String.class, int.class)
                .invoke(null, arguments[0], Integer.parseInt(arguments[1]));
        int status = (Integer) result;
        System.out.print("java-entry-status=");
        System.out.println(status);
        System.exit(status);
    }
}
"""

# The application's classes, which the Java binding reads, and the entry.
APP_SOURCES = {
    "dev/btrc/fixture/JniHost.java": HOST,
    "dev/btrc/fixture/JniCallbacks.java": CALLBACKS,
    "dev/btrc/fixture/JniWorker.java": WORKER,
    "dev/btrc/fixture/JniApp.java": APP,
}
ENTRY_SOURCES = {"dev/btrc/fixture/JniEntry.java": ENTRY}

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
    "dev.btrc.fixture.JniCallbacks",
    "dev.btrc.fixture.JniCallbacks.factor()I",
    "dev.btrc.fixture.JniCallbacks.callCompute(I)I",
    "dev.btrc.fixture.JniCallbacks.callWiden()J",
    "dev.btrc.fixture.JniCallbacks.callGreet(Ljava/lang/String;)Ljava/lang/String;",
    "dev.btrc.fixture.JniCallbacks.callGreetNul()Ljava/lang/String;",
    "dev.btrc.fixture.JniCallbacks.nest(I)I",
    "dev.btrc.fixture.JniCallbacks.callWrap(I)I",
    "dev.btrc.fixture.JniCallbacks.callWrapNull()Z",
    "dev.btrc.fixture.JniCallbacks.relay(Ljava/lang/String;)V",
    "dev.btrc.fixture.JniCallbacks.callStop()Z",
    "dev.btrc.fixture.JniCallbacks.callScale(II)I",
    "dev.btrc.fixture.JniWorker",
    "dev.btrc.fixture.JniWorker.callTwice(I)I",
]

# The natives each registration binds, by name and JNI descriptor.
CALLBACK_NATIVES = [
    "compute(I)I",
    "widen(BSCZFDJ)J",
    "greet(Ljava/lang/String;)Ljava/lang/String;",
    "depth(I)I",
    "wrap(Ldev/btrc/fixture/JniHost;)Ldev/btrc/fixture/JniHost;",
    "fail(Ljava/lang/String;)V",
    "stop()Z",
    "scale(I)I",
]
WORKER_NATIVES = ["twice(I)I"]

# Mode 0 is the round trip. Modes 1-3 are what an adopted VM refuses, each
# before any Java call: shutting it down, a second VM, and VM options. Modes 4
# and 5 are what a natives registration terminates on.
PROGRAM = """import Library.Callback;
import Library.Java.JavaVirtualMachine;
import Library.Vector;
import ./Fixture.btrc;
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

int receiversReleased = 0;

/* The receiver of dev.btrc.fixture.JniCallbacks's natives. */
class Callbacks implements IJniCallbacks {
	public int calls = 0;
	public int deepest = 0;
	public JniHost? kept = null;
	public ICallbackRegistration? registration = null;

	public int compute(int argument0) {
		self.calls++;
		return argument0 * 2 + 1;
	}

	public long long widen(signed char argument0, short argument1, unsigned short argument2, bool argument3, float argument4, double argument5, long long argument6) {
		self.calls++;
		long long total = (long long)argument0 + (long long)argument1 + (long long)argument2 + (long long)argument4 + (long long)argument5 + argument6;
		if (argument3) { total = total + 1000LL; }
		return total;
	}

	public string? greet(string? argument0) {
		self.calls++;
		if (argument0 == null) { return null; }
		string name = argument0;
		return f"hello {name}";
	}

	/* Java -> BTRC -> Java -> BTRC: each level calls Java, which calls back. */
	public int depth(int argument0) {
		self.calls++;
		if (argument0 > self.deepest) { self.deepest = argument0; }
		if (argument0 == 0) { return 0; }
		return argument0 + JniCallbacks.nest(argument0 - 1);
	}

	public JniHost? wrap(JniHost? argument0) {
		self.calls++;
		JniHost? host = argument0;
		if (host == null) { return null; }
		self.kept = host;
		return JniHost.create(host.value() + 1);
	}

	public void fail(string? argument0) {
		self.calls++;
		string text = "nothing";
		if (argument0 != null) { text = argument0; }
		throw f"btrc says {text}";
	}

	/* Cancels its own registration inside the call: it completes once the call has left. */
	public bool stop() {
		self.calls++;
		ICallbackRegistration? registration = self.registration;
		if (registration == null) { return false; }
		return registration.cancel() == CALLBACK_CANCELLATION_PENDING;
	}

	public int scale(JniCallbacks instance, int argument0) {
		self.calls++;
		return instance.factor() * argument0;
	}

	public void __del__() { receiversReleased++; }
}

/* The receiver of dev.btrc.fixture.JniWorker's natives, which abort on failure. */
class Worker implements IJniWorker {
	public int twice(int argument0) {
		if (argument0 < 0) { throw "a worker refuses negative values"; }
		return argument0 * 2;
	}
}

int callFromThread() {
	assert(JniHost.daemonThread());
	return JniHost.twice(4);
}

/* A BTRC thread registers natives of its own and Java calls them back on it. */
int workOnThread(int value) {
	assert(JniHost.daemonThread());
	CallbackScope scope = CallbackScope();
	var registration = registerJniWorker(Worker(), scope);
	assert(registration.isOpen() && JavaVirtualMachine.liveNatives() == 1);
	int result = JniWorker.callTwice(value);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(JavaVirtualMachine.liveNatives() == 0);
	return result;
}

int callNativeFromThread() { return JniCallbacks.callCompute(1); }

/* Mode 4: a native called on a thread other than its registration's terminates. */
void callOffThread() {
	CallbackScope scope = CallbackScope();
	var registration = registerJniCallbacks(Callbacks(), scope);
	assert(registration.isOpen());
	Thread<int> worker = spawn(() => callNativeFromThread());
	worker.join();
}

void exerciseNatives() {
	CallbackScope scope = CallbackScope();
	Callbacks receiver = Callbacks();
	var registration = registerJniCallbacks(receiver, scope);
	receiver.registration = registration;
	assert(JavaVirtualMachine.liveNatives() == 1);
	string again = "";
	try { registerJniCallbacks(Callbacks(), scope); }
	catch (string error) { again = error; }
	assert(again.equals("Java natives dev.btrc.fixture.JniCallbacks are already registered"));

	assert(JniCallbacks.callCompute(20) == 41);
	assert(JniCallbacks.callWiden() == 6000001015LL);
	string? greeting = JniCallbacks.callGreet("aé𝄞");
	assert(greeting != null && greeting.equals("hello aé𝄞"));
	assert(JniCallbacks.callGreet(null) == null);
	string refused = "";
	try { JniCallbacks.callGreetNul(); }
	catch (string error) { refused = error; }
	assert(refused.equals("JavaException: java.lang.IllegalArgumentException: Java string contains U+0000, which a BTRC string cannot hold"));
	assert(JniCallbacks.nest(3) == 6 && receiver.deepest == 3);
	assert(JniCallbacks.callWrap(41) == 42);
	assert(JniCallbacks.callWrapNull());
	JniHost? kept = receiver.kept;
	assert(kept != null && kept.value() == 41);
	string thrown = "";
	try { JniCallbacks.relay("aé𝄞"); }
	catch (string error) { thrown = error; }
	assert(thrown.equals("JavaException: java.lang.RuntimeException: btrc says aé𝄞"));
	assert(JniCallbacks.callScale(6, 7) == 42);

	int calls = receiver.calls;
	assert(JniCallbacks.callStop());
	assert(JavaVirtualMachine.liveNatives() == 1);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
	assert(JavaVirtualMachine.liveNatives() == 0);
	assert(scope.pollCompletion() == CALLBACK_CANCELLATION_NOT_REQUESTED && scope.pendingCount() == 0);
	string cancelled = "";
	try { JniCallbacks.callCompute(1); }
	catch (string error) { cancelled = error; }
	assert(cancelled.equals("JavaException: java.lang.IllegalStateException: Java natives dev.btrc.fixture.JniCallbacks are not registered"));
	assert(receiver.calls == calls + 1);
	assert(!registration.isOpen());
	receiver.kept = null;
	receiver.registration = null;
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
	if (mode == 4) { callOffThread(); }
	if (mode == 5) {
		Thread<int> failing = spawn(() => workOnThread(-1));
		failing.join();
	}
	exercise();
	exerciseNatives();
	assert(receiversReleased == 2);
	Thread<int> worker = spawn(() => workOnThread(21));
	assert(worker.join() == 42);
	assert(JniHost.collected() == 10000);
	assert(JavaVirtualMachine.liveClaims() == 0);
	assert(JavaVirtualMachine.liveNatives() == 0);
	assert(JavaVirtualMachine.attachedThreads() == 0);
	assert(JavaVirtualMachine.running() && JavaVirtualMachine.adopted());
	printf("java-natives-ok\\n");
	printf("java-adopted-ok\\n");
	return 0;
}
"""

# What each refusing mode writes to stderr as it terminates.
REFUSALS = {
    1: "Library.Java: an adopted Java VM belongs to its host and is never destroyed",
    2: "Library.Java: a process runs at most one Java VM",
    3: "Library.Java: an adopted Java VM takes no options; its host started it",
    4: "Java natives dev.btrc.fixture.JniCallbacks.compute(I)I: called off its executor thread",
    5: "BTRC native callback failed: a worker refuses negative values",
}
# The round trip's output after the program's pid line.
ROUND_TRIP_LINES = ["java-natives-ok", "java-adopted-ok", "java-entry-status=0"]

HARNESS = """/* The JNI entry of a library a running VM loads. JNI_OnLoad adopts the VM;
 * JniApp.run executes the BTRC program, whose main is compiled as
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

JNIEXPORT jint JNICALL Java_dev_btrc_fixture_JniApp_run(JNIEnv* env, jclass entry, jint mode) {
	(void)env;
	(void)entry;
	char name[] = "JniApp";
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
JNIEXPORT jint JNICALL Java_dev_btrc_fixture_JniApp_probe(JNIEnv* env, jclass entry) {
	(void)entry;
	printf("btrc-pid=%ld\\n", (long)getpid());
	fflush(stdout);
	jclass found = (*env)->FindClass(env, "java.lang.String");
	if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionClear(env); }
	if (found != NULL) { (*env)->DeleteLocalRef(env, found); }
	return 0;
}
"""


def natives_table(owner, factory, interface, methods, failure):
    """One `natives` registration of the Java binding."""
    listed = ", ".join(f'"{method}"' for method in methods)
    return (
        f"[native.bindings.natives.{owner}]\n"
        f'name = "{factory}"\ninterface = "{interface}"\nmethods = [{listed}]\n'
        f'executor = "caller"\nfailure = "{failure}"\ncancellation = "entry-barrier"\n'
    )


NATIVES = natives_table(
    "JniCallbacks", "registerJniCallbacks", "IJniCallbacks", CALLBACK_NATIVES, "throw"
) + natives_table("JniWorker", "registerJniWorker", "IJniWorker", WORKER_NATIVES, "abort")


def manifest(symbols=None, natives=NATIVES, *, sources=True):
    listed = ", ".join(f'"{symbol}"' for symbol in (SYMBOLS if symbols is None else symbols))
    return (
        'manifest-version = 1\n[package]\nname = "javaAdopted"\n'
        f'[[native.bindings]]\nmodule = "Fixture"\nlanguage = "java"\nsymbols = [{listed}]\n{natives}'
        + ('[[native.sources]]\npath = "Harness.c"\nlanguage = "c"\nstandard = "c11"\n' if sources else "")
    )


def compile_java(root):
    """Compile the application classes into classes/app and the entry into classes/entry; returns classes."""
    classes = root / "classes"
    for directory, files in (("app", APP_SOURCES), ("entry", ENTRY_SOURCES)):
        sources = []
        for name, text in files.items():
            path = root / "java" / directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            sources.append(str(path))
        subprocess.run(
            ["javac", "--release", "17", "-encoding", "UTF-8", "-d", str(classes / directory), *sources],
            check=True,
            capture_output=True,
            timeout=600,
        )
    return classes


def write_project(root):
    """Write the project under `root` and compile its Java classes; returns (Main.btrc, classes).

    The Java binding reads classes/app; classes/entry holds only JniEntry.
    """
    classes = compile_java(root)
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
