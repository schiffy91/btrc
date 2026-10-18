"""Java natives registrations: what both compilers refuse (interop step 7, slice A).

A `natives` table of a Java binding binds a selected class's `native` methods,
by name and JNI descriptor, to a generated BTRC receiver interface through
RegisterNatives (docs/design/native-interop-ownership.md section 2.3, "Java ->
btrc"; src/language/package-manifest.md, "Java natives"). The round trip
itself runs inside a Java VM (test_native_jni_adopted.py on a host JDK,
test_native_jni_android.py on the emulators); this module proves that both
compilers reject every malformed registration with the same diagnostic, and
that what they accept is bound through RegisterNatives.
"""

import pytest

from src.tests.python.jni_adoption_fixtures import (
    CALLBACK_NATIVES,
    SYMBOLS,
    compile_java,
    manifest,
    missing_java_tools,
    natives_table,
)
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project

CALLBACKS = "dev.btrc.fixture.JniCallbacks"
HOST = "dev.btrc.fixture.JniHost"
PROGRAM = """import Library.Callback;
import Library.Java.JavaVirtualMachine;
import ./Fixture.btrc;
int main() { return 0; }
"""


@pytest.fixture
def natives_project(native_project, monkeypatch):
    missing = missing_java_tools()
    if missing:
        pytest.skip(missing)
    source, _, _ = native_project
    root = source.parent.parent
    classes = compile_java(root)
    monkeypatch.setenv("BTRC_JAVA_CLASSPATH", str(classes / "app"))
    (source.parent / "Foundation.btrc").unlink()
    (source.parent / "Fixture.btrc").write_text("// The Java binding's module.\n", encoding="utf-8")
    source.write_text(PROGRAM, encoding="utf-8")
    return source


def registration(methods=("compute(I)I",), **fields):
    """A JniCallbacks registration whose `fields` override (or, given None, drop) its keys."""
    values = {
        "name": '"registerJniCallbacks"',
        "interface": '"IJniCallbacks"',
        "methods": "[" + ", ".join(f'"{method}"' for method in methods) + "]",
        "executor": '"caller"',
        "failure": '"throw"',
        "cancellation": '"entry-barrier"',
    }
    for key, value in fields.items():
        values[key.replace("_", "-")] = value
    owner = values.pop("owner", "JniCallbacks")
    lines = "".join(f"{key} = {value}\n" for key, value in values.items() if value is not None)
    return f"[native.bindings.natives.{owner}]\n{lines}"


def rejected(source, native_compile, natives, symbols=None):
    (source.parent.parent / "btrc.toml").write_text(manifest(symbols, natives, sources=False), encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    return str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    ("natives", "message"),
    [
        (registration(owner="JniOther"), "natives.JniOther: natives requires a Java class the binding selects"),
        (registration(extra="1"), "natives.JniCallbacks contains unexpected field 'extra'"),
        (registration(cancellation=None), "natives.JniCallbacks requires cancellation"),
        (registration(["compute(int)int"]), "natives.JniCallbacks.methods must name methods by JNI descriptor"),
        (registration(["<init>(I)V"]), "natives.JniCallbacks.methods must name methods by JNI descriptor"),
        (registration([]), "natives.JniCallbacks.methods must name methods by JNI descriptor"),
        (
            registration(["compute(I)I", "depth(I)I", "compute(I)I"]),
            "natives.JniCallbacks.methods registers compute(I)I twice",
        ),
        (registration(executor='"main"'), "natives.JniCallbacks.executor currently requires caller"),
        (registration(failure='"ignore"'), "natives.JniCallbacks.failure requires throw or abort"),
        (registration(cancellation='"drain"'), "natives.JniCallbacks.cancellation requires entry-barrier"),
        (
            registration(name='"JniHost"'),
            "natives.JniCallbacks: the factory and interface names must be distinct from selected classes and other natives",
        ),
        (
            registration(interface='"registerJniCallbacks"'),
            "natives.JniCallbacks: the factory and interface names must be distinct from selected classes and other natives",
        ),
        (
            registration() + natives_table("JniWorker", "registerJniCallbacks", "IJniWorker", ["twice(I)I"], "abort"),
            "natives.JniWorker: the factory and interface names must be distinct from selected classes and other natives",
        ),
    ],
    ids=[
        "unselected-class",
        "unknown-key",
        "missing-key",
        "no-descriptor",
        "constructor",
        "no-methods",
        "duplicate-registration",
        "executor",
        "failure",
        "cancellation",
        "factory-names-a-class",
        "interface-is-the-factory",
        "factory-of-another-registration",
    ],
)
def test_natives_manifest_rejections(natives_project, native_compile, natives, message):
    assert message in rejected(natives_project, native_compile, natives)


@pytest.mark.parametrize(
    ("methods", "message"),
    [
        (["plain(I)I"], f"Java RegisterNatives target {CALLBACKS}.plain(I)I is not ACC_NATIVE"),
        # The class declares depth(I)I: a descriptor it does not declare is not a native of it.
        (["depth(J)J"], f"JavaClassReader: unknown member {CALLBACKS}.depth(J)J"),
        (["sum([I)I"], f"Java arrays are not projected yet: {CALLBACKS}.sum([I)I"),
        (
            ["compute(I)I", "compute(J)J"],
            f"Java natives {CALLBACKS}.compute(I)I and {CALLBACKS}.compute(J)J project to the same BTRC name compute",
        ),
    ],
    ids=["not-native", "signature-mismatch", "array", "overload"],
)
def test_natives_projection_rejections(natives_project, native_compile, methods, message):
    assert message in rejected(natives_project, native_compile, registration(methods))


def test_natives_reject_an_unselected_class_type(natives_project, native_compile):
    # wrap takes and returns a JniHost, which this binding does not select.
    symbols = [symbol for symbol in SYMBOLS if not symbol.startswith(HOST)]
    method = f"wrap(L{HOST.replace('.', '/')};)L{HOST.replace('.', '/')};"
    message = f"Java member {CALLBACKS}.{method} uses unselected class {HOST}"
    assert message in rejected(natives_project, native_compile, registration([method]), symbols)


def test_natives_require_library_callback(natives_project, native_compile):
    # The factory returns the registration's Library.Callback context.
    natives_project.write_text(PROGRAM.replace("import Library.Callback;\n", ""), encoding="utf-8")
    message = (
        "Return type of function 'registerJniCallbacks' uses unknown by-value type "
        "'CallbackContext<IJniCallbacks*, OwnedClosure<CFunction<void, void*>>>'"
    )
    assert message in rejected(natives_project, native_compile, registration(CALLBACK_NATIVES))


REGISTERING = """import Library.Callback;
import Library.Java.JavaVirtualMachine;
import ./Fixture.btrc;

class Receiver implements IJniCallbacks {
	public int compute(int argument0) { return argument0; }
	public string? greet(string? argument0) { return argument0; }
	public int scale(JniCallbacks instance, int argument0) { return argument0; }
}

int main() {
	CallbackScope scope = CallbackScope();
	var registration = registerJniCallbacks(Receiver(), scope);
	return registration.isOpen() ? 0 : 1;
}
"""


def test_natives_bind_through_register_natives(natives_project, native_compile):
    methods = ["compute(I)I", "greet(Ljava/lang/String;)Ljava/lang/String;", "scale(I)I"]
    (natives_project.parent.parent / "btrc.toml").write_text(
        manifest(None, registration(methods), sources=False), encoding="utf-8"
    )
    natives_project.write_text(REGISTERING, encoding="utf-8")
    compiled = native_compile(natives_project)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    c_source = compiled.c_source.replace("JNIEnv* volatile", "JNIEnv*")
    # One thunk per native, registered by name and descriptor; an instance
    # native receives its object; no thread-invoke seam.
    for method in methods:
        name, _, descriptor = method.partition("(")
        assert f"__btrc_java_natives_JniCallbacks_{name}(JNIEnv* env, " in c_source, name
        assert f'"{name}", "({descriptor}"' in c_source, method
    assert "__btrc_java_natives_JniCallbacks_scale(JNIEnv* env, jobject __btrc_java_target" in c_source
    assert "btrcJavaRegisterNatives" in c_source and "btrcJavaEnter" in c_source
    assert "__btrc_native_thread_invoke" not in c_source
