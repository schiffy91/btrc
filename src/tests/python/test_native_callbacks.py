"""C function-pointer callbacks: receivers, leases, context slots and the resources they borrow."""

import json

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import resource_project as resource_project
from src.tests.python.native_import_fixtures import run_native_executable


@pytest.fixture
def callback_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <assert.h>\n"
        "static int VisitNow(int value, int (*callback)(int, void*), void* context) {\n"
        "  int first = callback(value, context);\n"
        "  return first + callback(value + 1, context);\n}\n",
        encoding="utf-8",
    )
    (root / "src/Foundation.btrc").write_text("", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["VisitNow"]\n'
        '[native.bindings.callbacks."VisitNow.callback"]\ncontext = "context"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_callback_receiver_lifetime(callback_project, native_compile, sanitized):
    source, sdk, triple = callback_project
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
int destroyed = 0;
class Holder { public IVisitor? visitor; }
class Visitor implements IVisitor {
	private Holder owner;
	public Visitor(Holder owner) { self.owner = owner; }
	public int invoke(int value) {
		self.owner.visitor = null;
		assert(destroyed == 0);
		return value * 2;
	}
	public void __del__() { destroyed++; }
}
int main() {
	var holder = Holder();
	holder.visitor = Visitor(holder);
	assert(VisitNow(10, holder.visitor) == 42);
	assert(destroyed == 1);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_callback_reentrancy_and_indirect_call(callback_project, native_compile, sanitized):
    source, sdk, triple = callback_project
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Visitor implements IVisitor {
	public int calls = 0;
	private int depth = 0;
	public int invoke(int value) {
		self.calls++;
		if (self.depth > 0) { return value * 2; }
		self.depth++;
		int result = VisitNow(value, self);
		self.depth--;
		return result;
	}
}
int main() {
	var visitor = Visitor();
	var visit = VisitNow;
	for (int index = 0; index < 100; index++) { assert(visit(10, visitor) == 88); }
	assert(visitor.calls == 600);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize("split_bindings", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("conflict", ["", "argument", "result"])
def test_native_callback_shared_interface(callback_project, native_compile, split_bindings, reverse, conflict):
    source, sdk, triple = callback_project
    root = source.parent.parent
    argument = "double" if conflict == "argument" else "int"
    result = "double" if conflict == "result" else "int"
    (root / "Foundation.h").write_text(
        "static int VisitFirst(int (*callback)(void*, int), void* context) { return callback(context, 7); }\n"
        f"static {result} VisitLast(void* context, {result} (*callback)({argument}, void*)) {{ return callback(9, context); }}\n",
        encoding="utf-8",
    )
    mappings = [
        ("VisitFirst", 0, "Foundation"),
        ("VisitLast", 1, "Other" if split_bindings else "Foundation"),
    ]
    if reverse:
        mappings.reverse()
    manifest = 'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
    for index, (function, context_index, module) in enumerate(mappings):
        if split_bindings or index == 0:
            symbols = [function] if split_bindings else [entry[0] for entry in mappings]
            manifest += (
                f'[[native.bindings]]\nmodule = "{module}"\nheader = "Foundation.h"\n'
                f'language = "c"\nstandard = "c11"\nsymbols = {json.dumps(symbols)}\n'
            )
        manifest += (
            f'[native.bindings.callbacks."{function}.callback"]\ncontext = "context"\ncontext-index = {context_index}\n'
            'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        )
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    (source.parent / "Other.btrc").write_text("", encoding="utf-8")
    modules = list(dict.fromkeys(entry[2] for entry in mappings))
    source.write_text(
        "".join(f"import ./{module}.btrc;\n" for module in modules)
        + """#include <assert.h>
int destroyed = 0;
class Visitor implements IVisitor {
	public int calls = 0;
	public int invoke(int value) { self.calls++; return value * 2; }
	public void __del__() { destroyed++; }
}
void check() {
	var receiver = Visitor();
	IVisitor shared = receiver;
	var first = VisitFirst;
	var last = VisitLast;
	assert(first(shared) == 14);
	assert(last(shared) == 18);
	assert(receiver.calls == 2);
	assert(destroyed == 0);
}
int main() { check(); assert(destroyed == 1); return 0; }
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    if conflict:
        assert not compiled.successful
        assert "conflicting native declaration 'IVisitor'" in str(compiled.failure) + str(compiled.diagnostics)
    else:
        assert compiled.successful, (compiled.failure, compiled.diagnostics)
        run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_native_callback_shared_receiver_with_two_leases(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "static int VisitBoth(int (*first)(void*, int), void* a, int (*second)(int, void*), void* b) {\n"
        "  return first(a, 3) + second(5, b);\n}\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["VisitBoth"]\n'
        '[native.bindings.callbacks."VisitBoth.first"]\ncontext = "a"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[native.bindings.callbacks."VisitBoth.second"]\ncontext = "b"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
int destroyed = 0;
class Holder { public IVisitor? visitor; }
class Visitor implements IVisitor {
	private Holder owner;
	public Visitor(Holder owner) { self.owner = owner; }
	public int invoke(int value) { self.owner.visitor = null; assert(destroyed == 0); return value * 2; }
	public void __del__() { destroyed++; }
}
int main() {
	var holder = Holder();
	holder.visitor = Visitor(holder);
	assert(VisitBoth(holder.visitor, holder.visitor) == 16);
	assert(destroyed == 1);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_native_callback_multiple_context_positions(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#include <assert.h>\n"
        "static double CallBoth(void* a, int (*left)(void*, int), int value, double (*right)(double, void*), void* b) {\n"
        "  return left(a, value) + right(value + 0.5, b);\n}\n",
        encoding="utf-8",
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativeConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["CallBoth"]\n'
        '[native.bindings.callbacks."CallBoth.left"]\ncontext = "a"\ncontext-index = 0\n'
        'interface = "ILeft"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[native.bindings.callbacks."CallBoth.right"]\ncontext = "b"\ncontext-index = 1\n'
        'interface = "IRight"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Left implements ILeft { public int invoke(int value) { return value * 2; } }
class Right implements IRight { public double invoke(double value) { return value * 3.0; } }
int main() {
	assert(CallBoth(Left(), 4, Right()) == 21.5);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_native_callback_rejects_wrong_thread(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        """#include <pthread.h>
#include <assert.h>
struct Delivery { int (*callback)(int, void*); void* context; };
static void* deliver(void* raw) {
    struct Delivery* value = raw;
    value->callback(1, value->context);
    return NULL;
}
static int VisitNow(int value, int (*callback)(int, void*), void* context) {
    struct Delivery delivery = {callback, context};
    pthread_t worker;
    assert(pthread_create(&worker, NULL, deliver, &delivery) == 0);
    assert(pthread_join(worker, NULL) == 0);
    return value;
}
""",
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <stdio.h>
class Visitor implements IVisitor {
	public int invoke(int value) { fputs("native body reached", stderr); return value; }
}
int main() { return VisitNow(1, Visitor()); }
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        root,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="BTRC native callback delivered on the wrong thread",
    )


def test_native_callback_void_delivery(callback_project, native_compile):
    source, sdk, triple = callback_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "static void VisitNow(void (*callback)(void*), void* context) { callback(context); callback(context); }\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(manifest.read_text().replace("context-index = 1", "context-index = 0"), encoding="utf-8")
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Visitor implements IVisitor {
	public int count = 0;
	public void invoke() { self.count++; }
}
int main() {
	var visitor = Visitor();
	VisitNow(visitor);
	assert(visitor.count == 2);
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize(
    "signature,message",
    [
        ("char* (*callback)(int, void*)", "non-scalar results require an ownership mapping"),
        ("int (*callback)(char*, void*)", "non-scalar arguments require a borrow mapping"),
    ],
)
def test_native_callback_rejects_unmapped_payload(callback_project, native_compile, signature, message):
    source, _sdk, _triple = callback_project
    (source.parent.parent / "Foundation.h").write_text(
        f"int VisitNow(int value, {signature}, void* context);\n", encoding="utf-8"
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


def test_native_callback_contains_failure(callback_project, native_compile):
    source, sdk, triple = callback_project
    source.write_text(
        """import ./Foundation.btrc;
#include <stdio.h>
class Probe { public void __del__() { fputs("callback cleaned\\n", stderr); } }
class Visitor implements IVisitor {
	public int invoke(int value) {
		var probe = Probe();
		throw "expected callback error";
	}
}
int main() {
	try { VisitNow(1, Visitor()); }
	catch (string error) { fputs("native body reached", stderr); }
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    ran = run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="BTRC native callback failed: expected callback error",
    )
    assert "callback cleaned\n" in ran.stderr


@pytest.mark.parametrize(
    "old,new,message",
    [
        ('context = "context"', 'context = "missing"', "context must identify one"),
        ("context-index = 1", "context-index = 9", "context-index is outside"),
        ("context-index = 1", "context-index = 0", "context must be an unqualified void pointer"),
        ('lifetime = "call"', 'lifetime = "stored"', "stored callbacks currently require Objective-C blocks"),
        ('failure = "abort"', 'failure = "ignore"', "failure currently requires abort"),
        ('executor = "caller"', 'executor = "worker"', "executor currently requires caller"),
        ('interface = "IVisitor"', 'interface = "VisitNow"', "interface conflicts"),
        ("VisitNow.callback", "VisitNow.missing", "unknown function parameter"),
    ],
)
def test_native_callback_invalid_mapping(callback_project, native_compile, old, new, message):
    source, _sdk, _triple = callback_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(old, new), encoding="utf-8")
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("temporary_receiver", [False, True])
def test_native_callback_preserves_borrowed_resource(resource_project, native_compile, indirect, temporary_receiver):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "static int VisitBorrowed(WidgetRef widget, int (*callback)(void*), void* context) {\n"
        " callback(context); return WidgetRead(widget);\n}\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["VisitBorrowed", "WidgetRef"')
        .replace(
            'borrowed-parameters = ["WidgetRead.widget"]',
            'borrowed-parameters = ["WidgetRead.widget", "VisitBorrowed.widget"]',
        )
        + '[native.bindings.callbacks."VisitBorrowed.callback"]\ncontext = "context"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? widget; }
class Visitor implements IVisitor {
	private Holder holder;
	public Visitor(Holder holder) { self.holder = holder; }
	public int invoke() {
		self.holder.widget = null;
		assert(WidgetLive() == 1 && WidgetDestroyed() == 0);
		return 0;
	}
}
int main() {
	var holder = Holder();
	holder.widget = WidgetCreate(29);
	DECLARE_VISIT
	DECLARE_RECEIVER
	assert(CALL(holder.widget, RECEIVER) == 29);
	assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
	return 0;
}
""".replace("DECLARE_VISIT", "var visit = VisitBorrowed;" if indirect else "")
        .replace("DECLARE_RECEIVER", "" if temporary_receiver else "var receiver = Visitor(holder);")
        .replace("RECEIVER", "Visitor(holder)" if temporary_receiver else "receiver")
        .replace("CALL", "visit" if indirect else "VisitBorrowed"),
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_managed_c_resource_borrow_survives_registered_callback(resource_project, native_compile):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text() + "static void (*installedHook)(void);\n"
        "static void InstallHook(void (*hook)(void)) { installedHook = hook; }\n"
        "static int VisitBorrowed(WidgetRef widget) { installedHook(); return WidgetRead(widget); }\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["InstallHook", "VisitBorrowed", "WidgetRef"')
        .replace(
            'borrowed-parameters = ["WidgetRead.widget"]',
            'borrowed-parameters = ["WidgetRead.widget", "VisitBorrowed.widget"]',
        ),
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder { public WidgetRef? widget; }
class Roots { class Holder holder = null; }
void clearOwner() {
	Roots.holder.widget = null;
	assert(WidgetLive() == 1 && WidgetDestroyed() == 0);
}
int main() {
	Roots.holder = Holder();
	Roots.holder.widget = WidgetCreate(17);
	InstallHook(clearOwner);
	assert(VisitBorrowed(Roots.holder.widget) == 17);
	assert(WidgetLive() == 0 && WidgetDestroyed() == 1);
	Roots.holder = null;
	return 0;
}
""",
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("borrowed_source", [False, True])
def test_native_callback_result_cleanup_when_receiver_destructor_throws(
    resource_project, native_compile, borrowed_source
):
    source, sdk, triple = resource_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + "static WidgetRef VisitMake("
        + ("WidgetRef source, " if borrowed_source else "")
        + "int (*callback)(int, void*), void* context) {\n callback(1, context); "
        + ("assert(WidgetRead(source) == 17); " if borrowed_source else "")
        + "return WidgetCreate(9);\n}\n",
        encoding="utf-8",
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["WidgetRef"', 'symbols = ["VisitMake", "WidgetRef"')
        .replace('owned-results = ["WidgetCreate"]', 'owned-results = ["WidgetCreate", "VisitMake"]')
        .replace(
            "borrowed-parameters = [",
            'borrowed-parameters = ["VisitMake.source", ' if borrowed_source else "borrowed-parameters = [",
        )
        + '[native.bindings.callbacks."VisitMake.callback"]\ncontext = "context"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n',
        encoding="utf-8",
    )
    source.write_text(
        """import ./Foundation.btrc;
#include <assert.h>
class Holder { public IVisitor? visitor; public WidgetRef? widget; }
class Visitor implements IVisitor {
	private Holder holder;
	public Visitor(Holder holder) { self.holder = holder; }
	public int invoke(int value) { self.holder.visitor = null; self.holder.widget = null; return value; }
	public void __del__() { throw "receiver destruction"; }
}
int main() {
	var holder = Holder();
SOURCE_INITIALIZATION
	holder.visitor = Visitor(holder);
	bool caught = false;
	try { var result = VisitMake(SOURCE_ARGUMENTholder.visitor); }
	catch (string error) { caught = true; }
	assert(caught);
	assert(WidgetLive() == 0);
	assert(WidgetDestroyed() == EXPECTED_DESTRUCTIONS);
	return 0;
}
""".replace("SOURCE_INITIALIZATION", "\tholder.widget = WidgetCreate(17);" if borrowed_source else "")
        .replace("SOURCE_ARGUMENT", "holder.widget, " if borrowed_source else "")
        .replace("EXPECTED_DESTRUCTIONS", "2" if borrowed_source else "1"),
        encoding="utf-8",
    )
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_callback_slot_accepts_weaker_incoming_preconditions(
    native_project, native_compile, tmp_path, sanitized
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["CallbackSlot", "invokeSlot"]',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        "typedef int (*Callback)(const int * _Nonnull value);\n"
        "typedef struct CallbackSlot { Callback _Nullable process; } CallbackSlot;\n"
        "static inline int invokeSlot(const CallbackSlot * _Nonnull slot) { int value = 42; return slot->process(&value); }\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        "int readValue(const int* value) { return value == null ? 0 : *value; }\n"
        "int verifyFoundation() { CallbackSlot slot; slot.process = readValue; int result = invokeSlot(&slot); slot.process = (CFunction<int, const int*>)null; return result == 42 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=())


@pytest.mark.parametrize(
    "observation",
    [
        "var escaped = slot.process;",
        "slot.process(null);",
        "var address = &slot.process;",
        "var copied = slot; var escaped = copied.process;",
        "CallbackSlot* pointer = &slot; var escaped = pointer->process;",
    ],
)
def test_native_callback_slot_does_not_erase_call_preconditions(native_project, native_compile, tmp_path, observation):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["CallbackSlot"]',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        "typedef struct CallbackSlot { int (*process)(const int * _Nonnull value); } CallbackSlot;\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        f"int verifyFoundation() {{ CallbackSlot slot; slot.process = (CFunction<int, const int*>)null; {observation} return 0; }}\n"
    )
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert "requires a checked callback adapter" in str(result.failure) + str(result.diagnostics)
