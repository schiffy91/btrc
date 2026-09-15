"""Unique SDK resources share an ordinary ARC owner, never an SDK retain."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import (
    apple_environment,
    run_native_executable,
)
from src.tests.python.test_native_import_consumer import (
    native_compile as native_compile,
)
from src.tests.python.test_native_import_consumer import (
    native_project as native_project,
)
from src.tests.python.test_native_import_consumer import (
    resource_project as resource_project,
)
from tools.native_plan import NativePlanBuilder


@pytest.fixture
def copied_project(unique_project):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static char copyData[] = {'a', 0, 'b', 0};
static inline const char* WidgetText(WidgetRef widget) { assert(widget); return copyData; }
static inline const void* WidgetBytes(WidgetRef widget, int mode) { assert(widget); return mode == 1 || mode == 2 ? NULL : copyData; }
static inline int WidgetLength(WidgetRef widget, int mode) { assert(widget); return mode == 1 ? 0 : mode == 3 ? -1 : mode == 4 ? 2147483647 : 3; }
static inline const char* StaticText(void) { return "static"; }
static inline void ChangeText(void) { copyData[0] = 'z'; }
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetText", "WidgetBytes", "WidgetLength", "StaticText", "ChangeText", ')
        .replace(
            "borrowed-parameters = [",
            'borrowed-parameters = ["WidgetText.widget", "WidgetBytes.widget", "WidgetLength.widget", ',
        )
        + """
[native.bindings.copied-results.WidgetText]
kind = "string"
owner = "widget"
[native.bindings.copied-results.StaticText]
kind = "string"
lifetime = "static"
[native.bindings.copied-results.WidgetBytes]
kind = "bytes"
owner = "widget"
length-function = "WidgetLength"
length-arguments = ["widget", "mode"]
length-preserves-result = true
"""
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_unique_copied_results_preserve_owned_data(copied_project, native_compile, sanitize):
    source, sdk, triple = copied_project
    root = source.parent.parent
    source.write_text("""import ./Foundation.btrc;
import Library.Bytes;
int main() {
    var owner = WidgetCreate(7);
    var text = WidgetText(owner);
    var bytes = WidgetBytes(owner, 0);
    var empty = WidgetBytes(owner, 1);
    assert(WidgetBytes(owner, 2) == null);
    assert(WidgetBytes(owner, 3) == null);
    assert(WidgetBytes(owner, 4) == null);
    var read = WidgetText;
    assert(read(owner) == "a");
    assert(StaticText() == "static");
    ChangeText(); owner.close();
    assert(text == "a");
    assert(bytes != null && bytes.length() == 3 && bytes.get(0) == 97 && bytes.get(1) == 0 && bytes.get(2) == 98);
    assert(empty != null && empty.length() == 0);
    assert(WidgetLive() == 0);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "invalid",
    [
        "owner",
        "owner-borrow",
        "length-type",
        "length-arity",
        "length-argument",
        "length-owner",
        "length-promise",
        "mutable",
        "volatile",
        "spoof-bytes",
        "empty",
        "duplicate",
    ],
)
def test_unique_copied_results_reject_invalid_contract(copied_project, native_compile, invalid):
    source, _, _ = copied_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    header = root / "Foundation.h"
    if invalid == "owner":
        manifest.write_text(manifest.read_text().replace('owner = "widget"', 'owner = "missing"'))
    elif invalid == "owner-borrow":
        manifest.write_text(manifest.read_text().replace('"WidgetBytes.widget", ', ""))
    elif invalid == "length-type":
        header.write_text(header.read_text().replace("int WidgetLength", "long WidgetLength"))
    elif invalid == "length-arity":
        manifest.write_text(manifest.read_text().replace('["widget", "mode"]', '["widget"]'))
    elif invalid == "length-argument":
        manifest.write_text(manifest.read_text().replace('["widget", "mode"]', '["mode", "widget"]'))
    elif invalid == "length-owner":
        header.write_text(
            header.read_text().replace(
                "int WidgetLength(WidgetRef widget, int mode) { assert(widget);", "int WidgetLength(int mode) {"
            )
        )
        manifest.write_text(
            manifest.read_text().replace('"WidgetLength.widget", ', "").replace('["widget", "mode"]', '["mode"]')
        )
    elif invalid == "length-promise":
        manifest.write_text(
            manifest.read_text().replace("length-preserves-result = true", "length-preserves-result = false")
        )
    elif invalid == "mutable":
        header.write_text(header.read_text().replace("const void* WidgetBytes", "void* WidgetBytes"))
    elif invalid == "volatile":
        header.write_text(header.read_text().replace("const void* WidgetBytes", "const volatile void* WidgetBytes"))
    elif invalid == "empty":
        manifest.write_text(manifest.read_text() + "\n[native.bindings.copied-results.ChangeText]\n")
    elif invalid == "duplicate":
        manifest.write_text(
            manifest.read_text()
            + '\n[native.bindings.copied-results.StaticText]\nkind = "string"\nlifetime = "static"\n'
        )
    source.write_text(
        "import ./Foundation.btrc;\n"
        + (
            "class Bytes { public Bytes() {} class Bytes fromRaw(char* value, int length) { return Bytes(); } }\n"
            if invalid == "spoof-bytes"
            else "import Library.Bytes;\n"
        )
        + "int main() { var owner = WidgetCreate(7); var bytes = WidgetBytes(owner, 0); return 0; }\n"
    )
    compiled = native_compile(source)
    assert not compiled.successful
    diagnostic = str(compiled.failure) + str(compiled.diagnostics)
    assert (
        "copied" in diagnostic.lower() or "native ownership" in diagnostic.lower() or "duplicate" in diagnostic.lower()
    ), diagnostic


def test_unique_copied_results_preserve_repeated_arguments(copied_project, native_compile):
    source, _, _ = copied_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text().replace(
            "int WidgetLength(WidgetRef widget, int mode) { assert(widget);",
            "int WidgetLength(WidgetRef widget, int mode, int repeated) { assert(widget && repeated == mode);",
        )
    )
    manifest = root / "btrc.toml"
    manifest.write_text(manifest.read_text().replace('["widget", "mode"]', '["widget", "mode", "mode"]'))
    test_unique_copied_results_preserve_owned_data(copied_project, native_compile, True)


def test_unique_copied_length_cannot_destroy_its_owner(copied_project, native_compile):
    source, _, _ = copied_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("static inline void WidgetRelease", "static inline int WidgetRelease")
        .replace("free(widget); }\n}", "free(widget); } return 0;\n}")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace(
            'release = "WidgetRelease"',
            'release = "WidgetRelease"\nrelease-consumption = "always"\ncleanup-status = "discard"',
        )
        .replace('length-function = "WidgetLength"', 'length-function = "WidgetRelease"')
        .replace('["widget", "mode"]', '["widget"]')
    )
    source.write_text("import ./Foundation.btrc;\nimport Library.Bytes;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "copied-results length-function requires a selected non-consuming C function" in str(compiled.failure) + str(
        compiled.diagnostics
    )


@pytest.fixture
def unique_project(resource_project):
    source, sdk, triple = resource_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('ownership = "reference-counted"', 'ownership = "unique"')
        .replace('retain = "WidgetRetain"\n', "")
        .replace('"WidgetRetain", ', "")
    )
    header = root / "Foundation.h"
    header.write_text(
        header.read_text().replace(
            "assert(widget && widget->references > 0);\n if (--widget->references == 0)",
            "assert(widget && widget->references == 1);\n if (--widget->references == 0)",
        )
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_unique_resource_owner_lifecycle(unique_project, native_compile, sanitize):
    source, sdk, triple = unique_project
    source.write_text("""import ./Foundation.btrc;
class Holder { public WidgetRef? value; public Holder(WidgetRef? value) { self.value = value; } }
int main() {
    for (int index = 0; index < 40; index++) {
        var value = WidgetCreate(42);
        assert(value != null && value.isOpen());
        var alias = value;
        var holder = new Holder(value);
        release value;
        assert(WidgetRead(alias) == 42 && WidgetLive() == 1);
        release alias;
        assert(WidgetRead(holder.value) == 42);
        release holder;
        assert(WidgetLive() == 0);
    }
    assert(WidgetDestroyed() == 40);
    var original = WidgetCreate(7);
    var alias = original;
    original.close();
    assert(!alias.isOpen() && WidgetLive() == 0 && WidgetDestroyed() == 41);
    alias.close();
    release original; release alias;
    assert(WidgetDestroyed() == 41);
    assert(WidgetCreate(-1) == null);
    WidgetCreate(1);
    assert(WidgetLive() == 0 && WidgetDestroyed() == 42);
    bool caught = false;
    try { var value = WidgetCreate(8); assert(value.isOpen()); throw "expected"; }
    catch (string error) { caught = error == "expected"; }
    assert(caught && WidgetLive() == 0 && WidgetDestroyed() == 43);
    var create = WidgetCreate;
    var read = WidgetRead;
    var finalValue = create(9);
    assert(read(finalValue) == 9);
    release finalValue;
    assert(WidgetLive() == 0 && WidgetDestroyed() == 44);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize("close_during_borrow", [False, True])
def test_unique_resource_rejects_closed_and_borrowed_use(unique_project, native_compile, close_during_borrow):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
#include <stdio.h>
static inline int WidgetVisit(WidgetRef widget, int (*callback)(void*), void* context) {
    int result = callback(context); assert(widget->value == 9); return result;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetVisit", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetVisit.widget", ')
        + '\n[native.bindings.callbacks."WidgetVisit.callback"]\ncontext = "context"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    source.write_text(
        """import ./Foundation.btrc;
class Visitor implements IVisitor {
    public WidgetRef? value;
    public Visitor(WidgetRef? value) { self.value = value; }
    public int invoke() { self.value.close(); return 0; }
}
int main() {
    var value = WidgetCreate(9);
    var alias = value;
"""
        + (
            "    WidgetVisit(value, Visitor(alias));\n"
            if close_during_borrow
            else "    value.close(); WidgetRead(alias);\n"
        )
        + "    return 0;\n}\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        root,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="close during borrow" if close_during_borrow else "use after close",
    )


@pytest.mark.parametrize(
    "body, diagnostic",
    [
        ("class Ordinary { public void close(); } int main() { return 0; }", "expected lbrace"),
        ("class FILE {} int main() { return 0; }", "compiler-owned"),
        ("int main() { var value = new WidgetRef(); return 0; }", "abstract"),
        ("int main() { var value = WidgetCreate(1); WidgetRelease(value); return 0; }", "lifetime"),
        ("int main() { var releaseNative = WidgetRelease; return 0; }", "lifetime"),
        ("int main() { var value = WidgetCreate(1); void* raw = (void*)value; return 0; }", "native"),
        ("int main() { var value = WidgetCreate(1); WidgetRef* raw = (WidgetRef*)value; return 0; }", "native"),
        ("class Spoof extends WidgetRef {} int main() { return 0; }", "native"),
        ("int main() { var value = WidgetCreate(1); var raw = value.value; return 0; }", "value"),
    ],
)
def test_unique_resource_cannot_escape_owner(unique_project, native_compile, body, diagnostic):
    source, _, _ = unique_project
    source.write_text("import ./Foundation.btrc;\n" + body)
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in (str(compiled.failure) + str(compiled.diagnostics)).lower()


@pytest.mark.parametrize(
    "mutation, diagnostic",
    [
        ("retain", "retain"),
        ("status", "unsupported lifetime result"),
        ("missing-owned", "owned-results"),
        ("missing-borrow", "borrowed-parameters"),
    ],
)
def test_unique_resource_contract_validation(unique_project, native_compile, mutation, diagnostic):
    source, _, _ = unique_project
    manifest = source.parent.parent / "btrc.toml"
    if mutation == "retain":
        manifest.write_text(manifest.read_text() + 'retain = "WidgetRetain"\n')
    elif mutation == "status":
        header = source.parent.parent / "Foundation.h"
        header.write_text(
            header.read_text()
            .replace("void WidgetRelease", "int WidgetRelease")
            .replace("++widgetDestroyed; free(widget); }", "++widgetDestroyed; free(widget); } return 0;")
        )
    else:
        remove = (
            'owned-results = ["WidgetCreate"]\n'
            if mutation == "missing-owned"
            else 'borrowed-parameters = ["WidgetRead.widget"]\n'
        )
        manifest.write_text(manifest.read_text().replace(remove, ""))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in (str(compiled.failure) + str(compiled.diagnostics)).lower()


def test_unique_resource_inside_collected_cycle(unique_project, native_compile):
    source, sdk, triple = unique_project
    source.write_text("""import ./Foundation.btrc;
class Owner {
    public Owner? next;
    public WidgetRef? value;
    public Owner(int number) { self.value = WidgetCreate(number); }
}
int main() {
    {
        var first = Owner(1); var second = Owner(2);
        first.next = second; second.next = first;
        assert(WidgetLive() == 2);
    }
    assert(WidgetLive() == 0 && WidgetDestroyed() == 2);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, True, frameworks=())


def test_unique_native_borrow_survives_last_application_release(unique_project, native_compile):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static inline int WidgetVisit(WidgetRef widget, int (*callback)(void*), void* context) {
    callback(context); assert(widgetLive == 1); return widget->value;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetVisit", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetVisit.widget", ')
        + '\n[native.bindings.callbacks."WidgetVisit.callback"]\ncontext = "context"\ncontext-index = 0\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    source.write_text("""import ./Foundation.btrc;
class Holder { public WidgetRef? value; }
class Visitor implements IVisitor {
    public Holder holder;
    public Visitor(Holder holder) { self.holder = holder; }
    public int invoke() { self.holder.value = null; assert(WidgetLive() == 1); return 0; }
}
int main() {
    var holder = Holder(); holder.value = WidgetCreate(17);
    assert(WidgetVisit(holder.value, Visitor(holder)) == 17);
    assert(holder.value == null && WidgetLive() == 0 && WidgetDestroyed() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("reentrant", [False, True])
@pytest.mark.parametrize("status_release", [False, True])
def test_unique_destructor_callback_keeps_owner_alive(unique_project, native_compile, reentrant, status_release):
    source, sdk, triple = unique_project
    if status_release:
        configure_status_release(source)
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        "static int (*widgetObserver)(int, void*);\nstatic void* widgetContext;\n"
        + header.read_text().replace(
            "if (--widget->references == 0)",
            "if (widgetObserver) widgetObserver(1, widgetContext);\n if (--widget->references == 0)",
        )
        + "static inline void WidgetObserveClose(int (*callback)(int, void*), void* context) {\n"
        " widgetObserver = callback; widgetContext = context; callback(0, context); widgetObserver = 0; widgetContext = 0;\n}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["WidgetObserveClose", ')
        + '\n[native.bindings.callbacks."WidgetObserveClose.callback"]\ncontext = "context"\ncontext-index = 1\n'
        'interface = "IVisitor"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
    )
    source.write_text(
        """import ./Foundation.btrc;
class Holder { public WidgetRef? value; }
class Visitor implements IVisitor {
    public Holder holder;
    public Visitor(Holder holder) { self.holder = holder; }
    public int invoke(int stage) {
        if (stage == 0) { self.holder.value.close(); }
        else {
            assert(!self.holder.value.isOpen());
"""
        + ("            self.holder.value.close();\n" if reentrant else "            self.holder.value = null;\n")
        + """
        }
        return 0;
    }
}
int main() {
    var holder = Holder(); holder.value = WidgetCreate(1);
    WidgetObserveClose(Visitor(holder));
    assert(holder.value == null && WidgetLive() == 0 && WidgetDestroyed() == 1);
    return 0;
}
"""
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        root,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="reentrant close" if reentrant else None,
    )


@pytest.mark.parametrize("status_release", [False, True])
def test_unique_concurrent_close_joins_destructor(unique_project, native_compile, status_release):
    source, sdk, triple = unique_project
    if status_release:
        configure_status_release(source)
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        "#include <stdatomic.h>\n#include <sched.h>\n"
        "static atomic_int widgetDestroyEntered, widgetDestroyFinish;\n"
        + header.read_text().replace(
            "if (--widget->references == 0)",
            "atomic_store(&widgetDestroyEntered, 1);\n"
            " while (!atomic_load(&widgetDestroyFinish)) sched_yield();\n"
            " if (--widget->references == 0)",
        )
    )
    source.write_text("""import ./Foundation.btrc;
int main() {
    var value = WidgetCreate(1); value.close(); assert(!value.isOpen()); return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    # Observe the actual condition wait, not a timing-dependent assumption that
    # the second closer has reached its synchronization boundary.
    harness = (
        """#include <pthread.h>
#include <stdatomic.h>
static pthread_cond_t* observedCondition;
static atomic_int closeWaitEntered;
static int observeConditionWait(pthread_cond_t* condition, pthread_mutex_t* mutex) {
    if (condition == observedCondition) atomic_store(&closeWaitEntered, 1);
    return pthread_cond_wait(condition, mutex);
}
#define pthread_cond_wait observeConditionWait
#define main generatedUniqueMain
"""
        + compiled.c_source
        + """
#undef main
#undef pthread_cond_wait
static void* closeResource(void* value) {
    __btrc_unique_WidgetRef_close_public(value);
    assert(atomic_load(&widgetDestroyFinish));
    assert(widgetDestroyed == 1);
    return NULL;
}
int main(void) {
    struct __btrc_native_WidgetRef* value = __btrc_native_WidgetCreate(1);
    observedCondition = &value->completed;
    pthread_t first, second;
    assert(pthread_create(&first, NULL, closeResource, value) == 0);
    while (!atomic_load(&widgetDestroyEntered)) sched_yield();
    assert(!__btrc_unique_WidgetRef_isOpen_public(value));
    assert(pthread_create(&second, NULL, closeResource, value) == 0);
    while (!atomic_load(&closeWaitEntered)) sched_yield();
    assert(widgetDestroyed == 0);
    atomic_store(&widgetDestroyFinish, 1);
    assert(pthread_join(first, NULL) == 0);
    assert(pthread_join(second, NULL) == 0);
    assert(widgetDestroyed == 1 && !__btrc_unique_WidgetRef_isOpen_public(value));
    __btrc_native_WidgetRef_release(value);
    assert(widgetDestroyed == 1 && widgetLive == 0);
    return 0;
}
"""
    )
    if status_release:
        harness = harness.replace(
            "__btrc_unique_WidgetRef_close_public(value);", "assert(__btrc_unique_WidgetRef_close_public(value) == 37);"
        )
        harness = harness.replace(
            "__btrc_native_WidgetRef_release(value);",
            "assert(__btrc_unique_WidgetRef_close_public(value) == 37);\n    __btrc_native_WidgetRef_release(value);",
        )
    run_native_executable(harness, root, sdk, triple, True, frameworks=())


def test_unique_method_value_rejected(unique_project, native_compile):
    source, _, _ = unique_project
    source.write_text("""import ./Foundation.btrc;
int main() {
    var value = WidgetCreate(1);
    var close = value.close;
    close();
    assert(!value.isOpen() && WidgetLive() == 0 && WidgetDestroyed() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert not compiled.successful
    assert not compiled.c_source


def test_unique_methods_do_not_collide_with_sdk_functions(unique_project, native_compile):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static inline int WidgetRef_close(WidgetRef widget) { return widget->value + 100; }
static inline int WidgetRef_isOpen(WidgetRef widget) { return widget->value + 200; }
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["WidgetRef_close", "WidgetRef_isOpen", ')
        .replace(
            "borrowed-parameters = [", 'borrowed-parameters = ["WidgetRef_close.widget", "WidgetRef_isOpen.widget", '
        )
    )
    source.write_text("""import ./Foundation.btrc;
void check(WidgetRef? value, bool opened = value.isOpen()) { assert(opened); }
int main() {
    var value = WidgetCreate(1);
    assert(WidgetRef_close(value) == 101 && WidgetRef_isOpen(value) == 201);
    assert(value.isOpen() && WidgetDestroyed() == 0);
    check(value);
    var close = () => { value.close(); };
    close();
    assert(!value.isOpen() && WidgetDestroyed() == 1);
    var second = WidgetCreate(2);
    second.close();
    assert(!second.isOpen() && WidgetDestroyed() == 2);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def select_record_resource(source, record_kind):
    root = source.parent.parent
    header = root / "Foundation.h"
    contents = header.read_text()
    if record_kind == "typedef":
        contents = contents.replace("} *WidgetRef;", "} WidgetRef;")
        pointer = "WidgetRef*"
    else:
        contents = contents.replace(
            "typedef struct WidgetStorage { int references; int value; } *WidgetRef;",
            "struct WidgetRef { int references; int value; };",
        )
        pointer = "struct WidgetRef*"
    header.write_text(
        contents.replace("WidgetRef Widget", pointer + " Widget").replace("WidgetRef widget", pointer + " widget")
    )
    return header, pointer


@pytest.mark.parametrize("record_kind", ["typedef", "tag"])
def test_unique_selected_record_resource(unique_project, native_compile, record_kind):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header, pointer = select_record_resource(source, record_kind)
    header.write_text(header.read_text().replace("WidgetRead(" + pointer, "WidgetRead(const " + pointer))
    source.write_text("""import ./Foundation.btrc;
int main() {
    var value = WidgetCreate(42); var alias = value;
    assert(value.isOpen() && WidgetRead(alias) == 42);
    release value; assert(WidgetRead(alias) == 42);
    alias.close(); assert(!alias.isOpen() && WidgetLive() == 0 && WidgetDestroyed() == 1);
    release alias; assert(WidgetDestroyed() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize("record_kind", ["typedef", "tag"])
def test_unique_record_by_value_rejected(unique_project, native_compile, record_kind):
    source, _, _ = unique_project
    header, pointer = select_record_resource(source, record_kind)
    header.write_text(
        header.read_text() + "\nstatic inline int WidgetByValue(" + pointer[:-1] + " widget) { return widget.value; }\n"
    )
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace("symbols = [", 'symbols = ["WidgetByValue", '))
    compiled = native_compile(source)
    assert not compiled.successful
    assert "requires pointer use" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("record_kind", ["typedef", "tag"])
def test_unique_record_const_owned_result_rejected(unique_project, native_compile, record_kind):
    source, _, _ = unique_project
    header, pointer = select_record_resource(source, record_kind)
    header.write_text(header.read_text().replace(pointer + " WidgetCreate", "const " + pointer + " WidgetCreate"))
    compiled = native_compile(source)
    assert not compiled.successful
    assert "incompatible pointer qualifiers" in str(compiled.failure) + str(compiled.diagnostics)


def test_unique_const_owner_rejects_mutable_borrow(unique_project, native_compile):
    source, _, _ = unique_project
    (source.parent.parent / "Foundation.h").write_text("""typedef const struct WidgetStorage { int value; } WidgetRef;
WidgetRef* WidgetCreate(int value);
void WidgetRelease(WidgetRef* widget);
int WidgetRead(struct WidgetStorage* widget);
int WidgetLive(void);
int WidgetDestroyed(void);
""")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "parameter has incompatible pointer qualifiers" in str(compiled.failure) + str(compiled.diagnostics)


def configure_status_release(source, status_type="int", expression="37"):
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("void WidgetRelease", status_type + " WidgetRelease")
        .replace("free(widget); }", "free(widget); } return " + expression + ";")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(manifest.read_text() + 'release-consumption = "always"\ncleanup-status = "discard"\n')


@pytest.mark.parametrize(
    "status_type, expression", [("int", "-37"), ("unsigned long long", "5000000000"), ("WidgetStatus", "37")]
)
def test_unique_status_release_preserves_completed_outcome(unique_project, native_compile, status_type, expression):
    source, sdk, triple = unique_project
    root = source.parent.parent
    select_record_resource(source, "typedef")
    configure_status_release(source, status_type, expression)
    if status_type == "WidgetStatus":
        header = root / "Foundation.h"
        header.write_text("typedef enum { WidgetPriorFailure = 37 } WidgetStatus;\n" + header.read_text())
    source.write_text(
        """import ./Foundation.btrc;
int main() {
    var value = WidgetCreate(1); var alias = value;
    var result = value.close();
    assert(result == EXPECTED && alias.close() == result);
    assert(!alias.isOpen() && WidgetDestroyed() == 1);
    release value; release alias; assert(WidgetDestroyed() == 1);
    WidgetCreate(2); assert(WidgetDestroyed() == 2);
    try { var local = WidgetCreate(3); throw "expected"; } catch (string error) { assert(error == "expected"); }
    assert(WidgetDestroyed() == 3 && WidgetLive() == 0);
    assert(WidgetCreate(-1) == null && WidgetDestroyed() == 3);
    return 0;
}
""".replace("EXPECTED", expression)
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize(
    "policy",
    [
        'release-consumption = "always"',
        'cleanup-status = "discard"',
        'release-consumption = "on-success"\ncleanup-status = "discard"',
        'release-consumption = "always"\ncleanup-status = "abort"',
        'release-consumption = "always"\ncleanup-status = "discard"',
    ],
)
def test_unique_status_policy_rejects_partial_conflicting_and_void(unique_project, native_compile, policy):
    source, _, _ = unique_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text() + policy + "\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "status" in str(compiled.failure) + str(compiled.diagnostics)


def test_unique_status_close_on_null_rejected(unique_project, native_compile):
    source, sdk, triple = unique_project
    configure_status_release(source)
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var value = WidgetCreate(-1); value.close(); return 0; }\n"
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="close on null owner",
    )


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("mode", [0, 1, 2])
@pytest.mark.parametrize("reuse", [False, True])
def test_unique_indeterminate_release_never_retries(unique_project, native_compile, sanitize, mode, reuse):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("static int widgetLive", "static int releaseCalls = 0;\nstatic int widgetLive")
        .replace("void WidgetRelease", "int WidgetRelease")
        .replace(
            "assert(widget && widget->references == 1);",
            "assert(widget && widget->references == 1); assert(++releaseCalls == 1);\n"
            " int mode = widget->value; if (mode == 1) return -37;",
        )
        .replace("free(widget); }", "free(widget); } return mode == 2 ? -37 : 0;")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + 'release-consumption = "success-or-indeterminate"\ncleanup-status = "abort"\n'
    )
    source.write_text(
        """import ./Foundation.btrc;
int main() {
    var owner = WidgetCreate(MODE); var alias = owner;
    assert(owner.isOpen());
    var status = owner.close();
    assert(status == STATUS && alias.close() == status && !alias.isOpen());
    assert(WidgetLive() == LIVE && WidgetDestroyed() == DESTROYED);
    ACTION
    return 0;
}
""".replace("MODE", str(mode))
        .replace("STATUS", "0" if mode == 0 else "-37")
        .replace("LIVE", "1" if mode == 1 else "0")
        .replace("DESTROYED", "0" if mode == 1 else "1")
        .replace("ACTION", "WidgetRead(alias);" if reuse else "release owner; release alias;")
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    failure = "use after close" if reuse else "destruction outcome is indeterminate" if mode else None
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=(), expected_failure=failure)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("mode", [0, 10, 12])
def test_unique_audio_unit_sdk_disposal_contract(native_project, native_compile, sanitize, mode):
    source, sdk, triple = native_project
    root = source.parent.parent
    faults = Path(__file__).resolve().parents[1] / "native" / "audio" / "UnitFaults.c"
    (root / "Foundation.h").write_text(f'#include "{faults}"\n')
    (source.parent / "Foundation.btrc").write_text("// Real AudioToolbox types with the existing SDK fault driver.\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "audioUnitOwnership"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["AudioComponent", "AudioComponentInstance", "AudioComponentDescription", "unitFind", "unitNew", "unitDispose", "unitReset", "unitDisposals", "pendingSessions", "kAudioUnitType_Output", "kAudioUnitSubType_HALOutput", "kAudioUnitManufacturer_Apple"]
[native.bindings.resources.AudioComponentInstance]
ownership = "unique"
release = "unitDispose"
release-consumption = "success-or-indeterminate"
cleanup-status = "abort"
[native.bindings.owned-outputs."unitNew.result"]
result = "AudioUnitOpenResult"
""")
    source.write_text(
        """import ./Foundation.btrc;
int main() {
    unitReset(MODE);
    AudioComponentDescription description = {kAudioUnitType_Output, kAudioUnitSubType_HALOutput, kAudioUnitManufacturer_Apple, 0u, 0u};
    var opened = unitNew(unitFind(null, &description));
    assert(opened.status == 0 && opened.value != null);
    var unit = opened.value; release opened;
    var status = unit.close();
    assert((status == 0) == SUCCESS && unit.close() == status);
    assert(!unit.isOpen() && unitDisposals() == 1 && pendingSessions() == LIVE);
    release unit;
    assert(unitDisposals() == 1);
    return 0;
}
""".replace("MODE", str(mode))
        .replace("SUCCESS", "true" if mode == 0 else "false")
        .replace("LIVE", "1" if mode == 10 else "0")
    )
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        root,
        sdk,
        triple,
        sanitize,
        frameworks=("AudioToolbox", "CoreAudio"),
        expected_failure="destruction outcome is indeterminate" if mode else None,
    )


@pytest.mark.parametrize("sanitize", [False, True])
def test_audio_unit_callback_installation_after_initialize(native_project, sanitize):
    source, sdk, triple = native_project
    fixture = Path(__file__).resolve().parents[1] / "native" / "audio" / "CallbackInstallation.c"
    ran = run_native_executable(
        fixture.read_text(),
        source.parent.parent,
        sdk,
        triple,
        sanitize,
        frameworks=("AudioToolbox", "CoreAudio"),
    )
    assert ran.stdout == "PASS: HAL callback installation after initialization\n"


def test_unique_actual_stdio_record_and_status(native_project, native_compile):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#include <stdio.h>\n")
    (source.parent / "Foundation.btrc").write_text("// Actual SDK declarations.\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "uniqueStdio"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["FILE", "tmpfile", "fclose", "fputc"]
owned-results = ["tmpfile"]
borrowed-parameters = ["fputc.argument1"]
[native.bindings.resources.FILE]
ownership = "unique"
release = "fclose"
release-consumption = "always"
cleanup-status = "discard"
""")
    source.write_text("""import ./Foundation.btrc;
int main() {
    var stream = tmpfile(); assert(stream != null && stream.isOpen());
    var alias = stream;
    assert(fputc(65, stream) == 65);
    release stream;
    assert(alias.close() == 0 && !alias.isOpen());
    assert(alias.close() == 0);
    release alias;
    var automatic = tmpfile(); assert(automatic != null);
    assert(fputc(66, automatic) == 66);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_unique_import_does_not_authenticate_provider_class(unique_project, native_compile):
    source, _, _ = unique_project
    (source.parent / "Foundation.btrc").write_text("class FILE {}\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "compiler-owned" in str(compiled.failure) + str(compiled.diagnostics)


def configure_owned_output(source, output_first=False):
    root = source.parent.parent
    header, _ = select_record_resource(source, "typedef")
    configure_status_release(source)
    parameters = "WidgetRef** output, int mode" if output_first else "int mode, WidgetRef** output"
    header.write_text(
        header.read_text() + "\nstatic inline int WidgetAcquire(" + parameters + ") {\n"
        " assert(output && !*output); *output = WidgetCreate(mode == 2 ? -1 : mode);\n"
        " return mode == 0 ? 0 : -37;\n}\n"
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["WidgetAcquire", ')
        + '\n[native.bindings.owned-outputs."WidgetAcquire.output"]\nresult = "WidgetAcquireResult"\n'
    )
    return header, manifest


@pytest.mark.parametrize("output_first", [False, True])
def test_unique_owned_output_adopts_error_claim(unique_project, native_compile, output_first):
    source, sdk, triple = unique_project
    root = source.parent.parent
    configure_owned_output(source, output_first)
    source.write_text("""import ./Foundation.btrc;
WidgetAcquireResult acquire(int mode) { var operation = WidgetAcquire; return operation(mode); }
int main() {
    for (int mode = 0; mode < 3; mode++) {
        var result = acquire(mode);
        assert(result.status == (mode == 0 ? 0 : -37));
        var value = result.value;
        release result;
        if (mode == 2) { assert(value == null); }
        else { assert(value != null && WidgetRead(value) == mode); assert(value.close() == 37); }
        release value; assert(WidgetLive() == 0);
    }
    assert(WidgetDestroyed() == 2);
    WidgetAcquire(1); assert(WidgetDestroyed() == 3);
    try { var result = WidgetAcquire(1); assert(result.value != null); throw "expected"; }
    catch (string error) { assert(error == "expected"); }
    assert(WidgetDestroyed() == 4 && WidgetLive() == 0);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


@pytest.mark.parametrize(
    "mutation, diagnostic",
    [
        ("unknown-parameter", "unknown parameter"),
        ("conditional", "unconditional"),
        ("missing-result", "result"),
        ("invalid-name", "identifier"),
        ("symbol-collision", "distinct result"),
        ("provider-collision", "WidgetAcquireResult"),
        ("slot-const", "mutable resource pointer"),
        ("claim-const", "incompatible resource pointer"),
        ("not-slot", "mutable resource pointer"),
        ("float-status", "integral or enum status"),
        ("borrow-overlap", "unknown or non-resource"),
    ],
)
def test_unique_owned_output_requires_complete_contract(unique_project, native_compile, mutation, diagnostic):
    source, _, _ = unique_project
    header, manifest = configure_owned_output(source)
    if mutation == "unknown-parameter":
        manifest.write_text(
            manifest.read_text().replace(
                'owned-outputs."WidgetAcquire.output"', 'owned-outputs."WidgetAcquire.unknown"'
            )
        )
    elif mutation == "conditional":
        manifest.write_text(manifest.read_text() + 'adoption = "on-success"\n')
    elif mutation == "missing-result":
        manifest.write_text(manifest.read_text().replace('result = "WidgetAcquireResult"', ""))
    elif mutation == "invalid-name":
        manifest.write_text(manifest.read_text().replace('result = "WidgetAcquireResult"', 'result = "invalid-name"'))
    elif mutation == "symbol-collision":
        manifest.write_text(manifest.read_text().replace('result = "WidgetAcquireResult"', 'result = "WidgetAcquire"'))
    elif mutation == "provider-collision":
        (source.parent / "Foundation.btrc").write_text("class WidgetAcquireResult {}\n")
    elif mutation == "borrow-overlap":
        manifest.write_text(
            manifest.read_text().replace("borrowed-parameters = [", 'borrowed-parameters = ["WidgetAcquire.output", ')
        )
    else:
        signature = {
            "slot-const": "WidgetRef* const*",
            "claim-const": "const WidgetRef**",
            "not-slot": "WidgetRef*",
        }.get(mutation, "WidgetRef**")
        status = "double" if mutation == "float-status" else "int"
        header.write_text(
            header.read_text().split("static inline int WidgetAcquire(")[0]
            + status
            + " WidgetAcquire(int mode, "
            + signature
            + " output);\n"
        )
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


def configure_output_offset(source, reordered=False):
    header, manifest = configure_owned_output(source)
    header.write_text(
        header.read_text().split("static inline int WidgetAcquire(")[0]
        + """
static inline int WidgetAcquire(int mode, const char* input, int length, WidgetRef** output, const char** tail) {
    assert(length >= 0 && output && !*output && tail && !*tail);
    *output = WidgetCreate(mode == 6 ? -1 : mode);
    *tail = mode == 0 || mode == 6 ? input + 1 : mode == 1 ? input + length :
        mode == 2 ? NULL : mode == 3 ? (const char*)((uintptr_t)input - 1U) :
        mode == 4 ? (const char*)((uintptr_t)input + (uintptr_t)length + 1U) : (const char*)UINTPTR_MAX;
    return mode == 0 ? 0 : -37;
}
"""
    )
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'read-only-borrows = ["WidgetAcquire.input"]\nsymbols = [')
        + """
[native.bindings.output-offsets."WidgetAcquire.tail"]
input = "input"
length = "length"
field = "tailOffset"
"""
    )
    if reordered:
        header.write_text(
            header.read_text().replace(
                "int mode, const char* input, int length, WidgetRef** output, const char** tail",
                "const char** tail, int mode, WidgetRef** output, const char* input, int length",
            )
        )
    return header, manifest


@pytest.mark.parametrize("reordered", [False, True])
def test_unique_owned_output_offset_bounds(unique_project, native_compile, reordered):
    source, sdk, triple = unique_project
    root = source.parent.parent
    configure_output_offset(source, reordered)
    source.write_text("""import ./Foundation.btrc;
int main() {
    var acquire = WidgetAcquire;
    for (int mode = 0; mode < 7; mode++) {
        var result = acquire(mode, "abc", 3);
        assert(result.status == (mode == 0 ? 0 : -37));
        assert(result.tailOffset == (mode == 0 || mode == 6 ? 1 : mode == 1 ? 3 : -1));
        assert((result.value != null) == (mode != 6));
        release result;
        assert(WidgetLive() == 0);
    }
    assert(WidgetDestroyed() == 6);
    var empty = acquire(1, "", 0);
    assert(empty.tailOffset == 0);
    release empty;
    var absent = acquire(2, null, 0);
    assert(absent.tailOffset == -1 && absent.value != null);
    release absent;
    assert(WidgetDestroyed() == 8 && WidgetLive() == 0);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, True, frameworks=())


def test_unique_owned_output_offset_negative_length_fails_before_sdk(unique_project, native_compile):
    source, sdk, triple = unique_project
    header, _ = configure_output_offset(source)
    header.write_text(
        "#include <stdio.h>\n"
        + header.read_text().replace(
            "assert(length >= 0", 'fputs("native body reached\\n", stderr); assert(length >= 0'
        )
    )
    source.write_text('import ./Foundation.btrc;\nint main() { WidgetAcquire(1, "abc", -1); return 0; }\n')
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        True,
        frameworks=(),
        expected_failure="negative bounded input length",
    )


@pytest.mark.parametrize(
    "mutation, diagnostic",
    [
        ("unknown-input", "unknown parameter"),
        ("owned-collision", "owned resource output"),
        ("missing-bound", "input, length, and field"),
        ("field-collision", "fresh result field"),
        ("wide-length", "signed int byte count"),
        ("mutable-tail", "const-char-pointer"),
        ("const-slot", "const-char-pointer"),
        ("missing-borrow", "read-only-borrows"),
    ],
)
def test_unique_owned_output_offset_rejects_invalid_contract(unique_project, native_compile, mutation, diagnostic):
    source, _, _ = unique_project
    header, manifest = configure_output_offset(source)
    if mutation == "unknown-input":
        manifest.write_text(manifest.read_text().replace('input = "input"', 'input = "unknown"'))
    elif mutation == "owned-collision":
        manifest.write_text(manifest.read_text().replace('input = "input"', 'input = "output"'))
    elif mutation == "missing-bound":
        manifest.write_text(manifest.read_text().replace('length = "length"', ""))
    elif mutation == "field-collision":
        manifest.write_text(manifest.read_text().replace('field = "tailOffset"', 'field = "status"'))
    elif mutation == "missing-borrow":
        manifest.write_text(manifest.read_text().replace('read-only-borrows = ["WidgetAcquire.input"]', ""))
    else:
        parameters = {
            "wide-length": "const char* input, long long length, WidgetRef** output, const char** tail",
            "mutable-tail": "const char* input, int length, WidgetRef** output, char** tail",
            "const-slot": "const char* input, int length, WidgetRef** output, const char* const* tail",
        }[mutation]
        header.write_text(
            header.read_text().split("static inline int WidgetAcquire(")[0]
            + "int WidgetAcquire(int mode, "
            + parameters
            + ");\n"
        )
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("prepare_offset", [False, True])
def test_unique_owned_output_actual_sqlite_open(native_project, native_compile, prepare_offset):
    try:
        configured = subprocess.run(["pkg-config", "--exists", "sqlite3"], capture_output=True, timeout=10)
    except FileNotFoundError:
        pytest.skip("actual SQLite SDK proof requires pkg-config")
    if configured.returncode:
        pytest.skip("actual SQLite SDK proof requires sqlite3.pc in PKG_CONFIG_PATH")
    source, _, _ = native_project
    root = source.parent.parent
    (source.parent / "Foundation.btrc").write_text("// Actual SQLite API.\n")
    (root / "Foundation.h").write_text(
        "#include <sqlite3.h>\nenum { SQLiteReadWrite = SQLITE_OPEN_READWRITE, SQLiteCreate = SQLITE_OPEN_CREATE };\n"
    )
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "ownedSQLite"
[[native.pkg-config]]
name = "sqlite3"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["sqlite3", "sqlite3_open_v2", "sqlite3_close_v2", "sqlite3_errcode", "SQLiteReadWrite", "SQLiteCreate"]
borrowed-parameters = ["sqlite3_errcode.db"]
read-only-borrows = ["sqlite3_open_v2.filename", "sqlite3_open_v2.zVfs"]
[native.bindings.resources.sqlite3]
ownership = "unique"
release = "sqlite3_close_v2"
release-consumption = "always"
cleanup-status = "discard"
[native.bindings.owned-outputs."sqlite3_open_v2.ppDb"]
result = "SQLiteOpenResult"
""")
    source.write_text("""import ./Foundation.btrc;
int main() {
    int flags = SQLiteReadWrite | SQLiteCreate;
    var opened = sqlite3_open_v2(":memory:", flags, null);
    assert(opened.status == 0 && opened.value != null && opened.value.isOpen());
    var database = opened.value; release opened;
    assert(sqlite3_errcode(database) == 0);
    assert(database.close() == 0 && database.close() == 0 && !database.isOpen());
    release database;
    var failed = sqlite3_open_v2(":memory:", flags, "BTRC_missing_vfs");
    assert(failed.status != 0 && failed.value != null && failed.value.isOpen());
    assert(sqlite3_errcode(failed.value) != 0);
    assert(failed.value.close() == 0);
    release failed;
    sqlite3_open_v2(":memory:", flags, null);
    sqlite3_open_v2(":memory:", flags, "BTRC_missing_vfs");
    return 0;
}
""")
    if prepare_offset:
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text()
            .replace("symbols = [", 'symbols = ["sqlite3_stmt", "sqlite3_finalize", "sqlite3_prepare_v3", ')
            .replace("borrowed-parameters = [", 'borrowed-parameters = ["sqlite3_prepare_v3.db", ')
            .replace("read-only-borrows = [", 'read-only-borrows = ["sqlite3_prepare_v3.zSql", ')
            + """
[native.bindings.resources.sqlite3_stmt]
ownership = "unique"
release = "sqlite3_finalize"
release-consumption = "always"
cleanup-status = "discard"
[native.bindings.owned-outputs."sqlite3_prepare_v3.ppStmt"]
result = "SQLitePrepareResult"
[native.bindings.output-offsets."sqlite3_prepare_v3.pzTail"]
input = "zSql"
length = "nByte"
field = "tailOffset"
"""
        )
        source.write_text(
            source.read_text().replace(
                "    assert(database.close() == 0",
                """
    var prepared = sqlite3_prepare_v3(database, "SELECT 1; SELECT 2", 18, 0U);
    assert(prepared.status == 0 && prepared.value != null && prepared.tailOffset == 9);
    assert(prepared.value.close() == 0);
    var failedPrepare = sqlite3_prepare_v3(database, "SELECT FROM", 11, 0U);
    assert(failedPrepare.status != 0 && failedPrepare.value == null);
    var comment = sqlite3_prepare_v3(database, " --comment", 10, 0U);
    assert(comment.status == 0 && comment.value == null && comment.tailOffset == 10);
    assert(database.close() == 0""",
            )
        )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def sanitized_run(command, **kwargs):
        if command[0] in {"/usr/bin/clang", "/usr/bin/clang++"}:
            command = [command[0], "-fsanitize=address,undefined", "-fno-omit-frame-pointer", *command[1:]]
        return subprocess.run(command, env=apple_environment(), **kwargs)

    binary = root / "Program"
    NativePlanBuilder(runner=sanitized_run).build(
        plan_path=plan, generated_c=generated, output=binary, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    ran = subprocess.run([str(binary)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
    assert not ran.stderr
