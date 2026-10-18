"""Checked JNI calls: `language = "java"` bindings through both compilers (interop step 4b).

A Java binding selects classes, constructors, methods and fields by JNI
descriptor. Each selected class becomes a unique BTRC owner of one global
reference, and each member a generated adapter that checks every throwing JNI
call, frames its local references and translates a Java exception into a BTRC
exception (docs/design/native-interop-ownership.md section 2.3). A JDK 17
HotSpot runs the program under -Xcheck:jni, where any CheckJNI warning fails.
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

HOST = """package dev.btrc.fixture;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.List;

public class JniHost {
    public static final int LIMIT = 41;
    public static String label = "start";
    private static final List<WeakReference<JniHost>> made = new ArrayList<>();
    private final int amount;
    public int count;

    public JniHost(int amount) {
        this.amount = amount;
    }

    public static int twice(int value) {
        return value * 2;
    }

    public static long widen(byte b, short s, char c, boolean z, float f, double d, long j) {
        return b + s + c + (z ? 1000 : 0) + (long) f + (long) d + j;
    }

    public int value() {
        return amount;
    }

    public JniHost add(JniHost other) {
        return new JniHost(amount + (other == null ? 100 : other.amount));
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

    public static JniHost none() {
        return null;
    }

    /** How many made objects the collector has reclaimed: none survives a leaked reference. */
    public static int collected() throws InterruptedException {
        int cleared = 0;
        for (int attempt = 0; attempt < 20; attempt++) {
            System.gc();
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

    // Members only the rejection cases select.
    public static long twice(long value) {
        return value * 2;
    }

    public void close() {
    }

    public static int hash(Object value) {
        return value.hashCode();
    }

    public static String[] names() {
        return new String[] {"one"};
    }

    public static int[][] grid() {
        return new int[][] {{1}};
    }

    public static class Inner {
        public Inner() {
        }
    }
}
"""

# Classes only the rejection cases select.
OTHERS = {
    "dev/btrc/fixture/JniBase.java": "package dev.btrc.fixture;\npublic abstract class JniBase {\n    public JniBase() {\n    }\n}\n",
    "dev/btrc/other/JniHost.java": "package dev.btrc.other;\npublic class JniHost {\n}\n",
}

SYMBOLS = [
    "dev.btrc.fixture.JniHost",
    "dev.btrc.fixture.JniHost.<init>(I)V",
    "dev.btrc.fixture.JniHost.twice(I)I",
    "dev.btrc.fixture.JniHost.widen(BSCZFDJ)J",
    "dev.btrc.fixture.JniHost.value()I",
    "dev.btrc.fixture.JniHost.add(Ldev/btrc/fixture/JniHost;)Ldev/btrc/fixture/JniHost;",
    "dev.btrc.fixture.JniHost.isExpected(Ljava/lang/String;)Z",
    "dev.btrc.fixture.JniHost.units(Ljava/lang/String;)I",
    "dev.btrc.fixture.JniHost.echo(Ljava/lang/String;)Ljava/lang/String;",
    "dev.btrc.fixture.JniHost.withNul()Ljava/lang/String;",
    "dev.btrc.fixture.JniHost.fail(Ljava/lang/String;)V",
    "dev.btrc.fixture.JniHost.make(I)Ldev/btrc/fixture/JniHost;",
    "dev.btrc.fixture.JniHost.none()Ldev/btrc/fixture/JniHost;",
    "dev.btrc.fixture.JniHost.collected()I",
    "dev.btrc.fixture.JniHost.daemonThread()Z",
    "dev.btrc.fixture.JniHost.LIMIT:I",
    "dev.btrc.fixture.JniHost.label:Ljava/lang/String;",
    "dev.btrc.fixture.JniHost.count:I",
]

PROGRAM = """import Library.Java.JavaVirtualMachine;
import Library.Vector;
import ./Fixture.btrc;
#include <assert.h>
#include <stdio.h>

int callFromThread() {
	assert(JniHost.daemonThread());
	return JniHost.twice(4);
}

void exercise() {
	assert(JniHost.twice(21) == 42);
	assert(JniHost.widen((signed char)1, (short)2, (unsigned short)3, true, 4.5f, 5.5, 6000000000LL) == 6000001015LL);
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
	JniHost? fallback = two.add(null);
	assert(fallback != null && fallback.value() == 102);
	two.setCount(7);
	assert(two.count() == 7 && two.isOpen());
	assert(JniHost.none() == null);
	assert(JavaVirtualMachine.liveClaims() == 3);

	assert(JniHost.isExpected("aé𝄞"));
	assert(JniHost.units("aé𝄞") == 4);
	assert(JniHost.units(null) == -1);
	string? back = JniHost.echo("aé𝄞");
	assert(back != null && back.equals("aé𝄞"));
	assert(JniHost.echo(null) == null);

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
	assert(!sum.isOpen());
	assert(JavaVirtualMachine.liveClaims() == 2);

	Thread<int> worker = spawn(() => callFromThread());
	assert(worker.join() == 8);
}

int main() {
	Vector<string> options = ["-Xcheck:jni", "-Djava.class.path=CLASSPATH"];
	JavaVirtualMachine.createHost(options);
	exercise();
	assert(JniHost.collected() == 10000);
	assert(JavaVirtualMachine.liveClaims() == 0);
	assert(JavaVirtualMachine.attachedThreads() == 0);
	JavaVirtualMachine.shutdown();
	printf("java-calls-ok\\n");
	return 0;
}
"""


def java_environment():
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "btrc-jni"], check=False, timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the btrc-jni pkg-config package (the flake's dev shell provides JDK 17)")
    if not shutil.which("javac") or not os.environ.get("BTRC_JAVA_CLASS_READER"):
        pytest.skip("requires javac and BTRC_JAVA_CLASS_READER (the flake's dev shell provides both)")
    return apple_environment()


def manifest(symbols, extra=""):
    listed = ", ".join(f'"{symbol}"' for symbol in symbols)
    return (
        'manifest-version = 1\n[package]\nname = "javaConsumer"\n'
        f'[[native.bindings]]\nmodule = "Fixture"\nlanguage = "java"\nsymbols = [{listed}]\n{extra}'
    )


@pytest.fixture
def java_project(native_project, monkeypatch):
    environment = java_environment()
    source, _, _ = native_project
    root = source.parent.parent
    classes = root / "classes"
    sources = []
    for name, text in {"dev/btrc/fixture/JniHost.java": HOST, **OTHERS}.items():
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
    monkeypatch.setenv("BTRC_JAVA_CLASSPATH", str(classes))
    (root / "btrc.toml").write_text(manifest(SYMBOLS), encoding="utf-8")
    (source.parent / "Foundation.btrc").unlink()
    (source.parent / "Fixture.btrc").write_text("// The Java binding's module.\n", encoding="utf-8")
    source.write_text(PROGRAM.replace("CLASSPATH", str(classes)), encoding="utf-8")
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
    return compiled.c_source, executable


def test_java_calls_round_trip_under_checkjni(java_project, native_compile):
    source, environment = java_project
    c_source, executable = build(source, native_compile, environment)
    # Adapters call JNI slots by name through the env, never a variadic slot.
    assert "CallStaticIntMethodA" in c_source and "PushLocalFrame" in c_source
    assert "CallStaticIntMethod(" not in c_source
    completed = subprocess.run(
        [str(executable)],
        env={key: value for key, value in environment.items() if key != "JAVA_TOOL_OPTIONS"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert completed.stdout == "java-calls-ok\n", completed.stdout
    # -Xcheck:jni reports every JNI misuse as a warning on stdout or stderr.
    assert "WARNING" not in completed.stdout + completed.stderr, completed.stderr
    assert "FATAL ERROR" not in completed.stdout + completed.stderr, completed.stderr


def rejected(source, native_compile):
    result = native_compile(source)
    assert not result.successful
    return str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    ("extra", "symbols", "message"),
    [
        ('header = "Fixture.h"\n', SYMBOLS[:1], "Java bindings take no header or standard"),
        ('standard = "c11"\n', SYMBOLS[:1], "Java bindings take no header or standard"),
        ('realtime-safe = ["dev.btrc.fixture.JniHost"]\n', SYMBOLS[:1], "contains unexpected field 'realtime-safe'"),
        (
            "",
            ["dev.btrc.fixture.JniHost.twice(int)int"],
            "symbols must name Java classes, or members by JNI descriptor",
        ),
        ("", ["dev.btrc.fixture.JniHost.<init>(I)I"], "symbols must name Java classes, or members by JNI descriptor"),
        ("", ["dev.btrc.fixture.JniHost.count:Q"], "symbols must name Java classes, or members by JNI descriptor"),
        ("", ["dev.btrc.fixture.JniHost.twice(I)"], "symbols must name Java classes, or members by JNI descriptor"),
        ("", ["dev.btrc.fixture.JniHost", "dev.btrc.fixture.JniHost"], "symbols contains a duplicate value"),
    ],
    ids=[
        "header",
        "standard",
        "unknown-key",
        "no-descriptor",
        "constructor-result",
        "field-type",
        "no-result",
        "duplicate",
    ],
)
def test_java_manifest_rejections(java_project, native_compile, extra, symbols, message):
    source, _ = java_project
    root = source.parent.parent
    (root / "Fixture.h").write_text("", encoding="utf-8")
    (root / "btrc.toml").write_text(manifest(symbols, extra), encoding="utf-8")
    assert message in rejected(source, native_compile)


MINIMAL = "import Library.Java.JavaVirtualMachine;\nimport ./Fixture.btrc;\nint main() { return 0; }\n"
HOST_CLASS = "dev.btrc.fixture.JniHost"


@pytest.mark.parametrize(
    ("symbols", "message"),
    [
        (
            [f"{HOST_CLASS}.hash(Ljava/lang/Object;)I"],
            f"Java member {HOST_CLASS}.hash(Ljava/lang/Object;)I uses unselected class java.lang.Object",
        ),
        (
            [HOST_CLASS, f"{HOST_CLASS}.names()[Ljava/lang/String;"],
            f"Java arrays of objects or arrays are not projected yet: {HOST_CLASS}.names()[Ljava/lang/String;",
        ),
        (
            [HOST_CLASS, f"{HOST_CLASS}.grid()[[I"],
            f"Java arrays of objects or arrays are not projected yet: {HOST_CLASS}.grid()[[I",
        ),
        ([f"{HOST_CLASS}$Inner"], f"Java nested classes are not projected yet: {HOST_CLASS}$Inner"),
        (
            [HOST_CLASS, f"{HOST_CLASS}.twice(I)I", f"{HOST_CLASS}.twice(J)J"],
            f"Java members {HOST_CLASS}.twice(I)I and {HOST_CLASS}.twice(J)J project to the same BTRC name twice",
        ),
        (
            [HOST_CLASS, f"{HOST_CLASS}.close()V"],
            f"Java members {HOST_CLASS}.close and {HOST_CLASS}.close()V project to the same BTRC name close",
        ),
        (
            [HOST_CLASS, "dev.btrc.other.JniHost"],
            f"Java classes {HOST_CLASS} and dev.btrc.other.JniHost project to the same BTRC name JniHost",
        ),
        (
            ["dev.btrc.fixture.JniBase.<init>()V"],
            "Java constructor dev.btrc.fixture.JniBase.<init>()V cannot create an abstract class or interface",
        ),
        (
            [HOST_CLASS, f"{HOST_CLASS}.toString()Ljava/lang/String;"],
            f"JavaClassReader: unknown member {HOST_CLASS}.toString()Ljava/lang/String;",
        ),
    ],
    ids=[
        "unselected",
        "object-array",
        "nested-array",
        "nested",
        "overload",
        "close",
        "simple-name",
        "abstract",
        "unknown-member",
    ],
)
def test_java_projection_rejections(java_project, native_compile, symbols, message):
    source, _ = java_project
    (source.parent.parent / "btrc.toml").write_text(manifest(symbols), encoding="utf-8")
    source.write_text(MINIMAL, encoding="utf-8")
    assert message in rejected(source, native_compile)


def test_java_class_selected_by_two_bindings(java_project, native_compile):
    source, _ = java_project
    root = source.parent.parent
    second = '[[native.bindings]]\nmodule = "Second"\nlanguage = "java"\nsymbols = ["dev.btrc.fixture.JniHost"]\n'
    (root / "btrc.toml").write_text(manifest([HOST_CLASS], second), encoding="utf-8")
    (source.parent / "Second.btrc").write_text("// A second Java binding's module.\n", encoding="utf-8")
    source.write_text(MINIMAL.replace("import ./Fixture.btrc;", "import ./Fixture.btrc;\nimport ./Second.btrc;"))
    assert f"Java class {HOST_CLASS} is selected by two bindings" in rejected(source, native_compile)


@pytest.mark.parametrize(
    ("variable", "program", "message"),
    [
        ("BTRC_JAVA_CLASS_READER", MINIMAL, "Java bindings require BTRC_JAVA_CLASS_READER"),
        ("BTRC_JAVA_CLASSPATH", MINIMAL, "Java bindings require BTRC_JAVA_CLASSPATH"),
        (
            None,
            "import ./Fixture.btrc;\nint main() { return 0; }\n",
            "Java bindings require import Library.Java.JavaVirtualMachine",
        ),
    ],
    ids=["reader", "classpath", "runtime"],
)
def test_java_binding_requirements(java_project, native_compile, monkeypatch, variable, program, message):
    source, _ = java_project
    (source.parent.parent / "btrc.toml").write_text(manifest([HOST_CLASS]), encoding="utf-8")
    source.write_text(program, encoding="utf-8")
    if variable is not None:
        monkeypatch.delenv(variable)
    assert message in rejected(source, native_compile)
