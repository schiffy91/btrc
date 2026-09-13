"""Caller-owned SDK records remain private, nonmoving ordinary ARC resources."""

import pytest

from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from src.tests.python.test_native_import_consumer import run_native_executable


@pytest.fixture
def inline_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""
#include <stdlib.h>
#include <assert.h>
#include <string.h>
typedef struct InlineRecord {
    struct InlineRecord* self;
    const unsigned char* input;
    size_t size;
    unsigned char padding[67];
} InlineRecord;
static int inlineCalls = 0, inlineEnds = 0;
static const int InlineSuccess = 7;
static inline int InlineInit(InlineRecord* record, const void* input, size_t size, int status) {
    InlineRecord zero = {0};
    assert(record && memcmp(record, &zero, sizeof(zero)) == 0);
    ++inlineCalls;
    if (status != InlineSuccess) return status;
    record->self = record; record->input = input; record->size = size;
    return status;
}
static inline int InlineEnd(InlineRecord* record) {
    assert(record && record->self == record && record->size == 3);
    assert(record->input[0] == 11 && record->input[1] == 0 && record->input[2] == 29);
    ++inlineEnds; return 91;
}
static inline int InlineRead(InlineRecord* record) {
    assert(record && record->self == record); return record->input[0];
}
static inline int InlineCalls(void) { return inlineCalls; }
static inline int InlineEnds(void) { return inlineEnds; }
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "inlineResources"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["InlineRecord", "InlineInit", "InlineEnd", "InlineRead", "InlineCalls", "InlineEnds", "InlineSuccess"]
read-only-borrows = ["InlineInit.input"]
borrowed-parameters = ["InlineRead.record"]
[native.bindings.resources.InlineRecord]
ownership = "unique"
storage = "inline"
release = "InlineEnd"
release-consumption = "always"
cleanup-status = "discard"
[native.bindings.initializers.InlineInit]
resource = "InlineRecord"
parameter = "record"
result = "InlineOpenResult"
success = "InlineSuccess"
failure = "rolled-back"
[native.bindings.initializers.InlineInit.copied-inputs.input]
length = "size"
""")
    (source.parent / "Foundation.btrc").write_text("// Imported checked SDK owner.\n")
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_inline_resource_nonmoving_copied_input_lifecycle(inline_project, native_compile, sanitize):
    source, sdk, triple = inline_project
    source.write_text("""import ./Foundation.btrc;
void abandon(const void* input) {
    try { var abandoned = InlineInit(input, (size_t)3, InlineSuccess); throw "expected"; }
    catch (string error) { assert(error == "expected"); }
}
int main() {
    unsigned char input[3] = {11, 0, 29};
    var failed = InlineInit(input, (size_t)3, -3);
    assert(failed.called && failed.status == -3 && failed.value == null);
    assert(InlineCalls() == 1 && InlineEnds() == 0);
    var opened = InlineInit(input, (size_t)3, InlineSuccess);
    assert(opened.called && opened.status == InlineSuccess && opened.value != null);
    var owner = opened.value;
    release opened;
    input[0] = 99;
    assert(InlineRead(owner) == 11);
    var alias = owner;
    release owner;
    assert(alias.close() == 91 && !alias.isOpen());
    assert(alias.close() == 91 && InlineEnds() == 1);
    release alias;
    input[0] = 11;
    var create = InlineInit;
    create(input, (size_t)3, InlineSuccess);
    assert(InlineEnds() == 2);
    abandon(input);
    assert(InlineEnds() == 3);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "change, diagnostic",
    [
        ('storage = "inline"', "inline unique ownership"),
        ('failure = "rolled-back"', "fully rolled-back"),
        ('success = "InlineSuccess"', "selected success constant"),
    ],
)
def test_inline_initializer_invalid_contract(inline_project, native_compile, change, diagnostic):
    source, _, _ = inline_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(change, change.split("=", 1)[0] + '= "invalid"'))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("expression", ["new InlineRecord()", "owner.value.self", "InlineEnd(owner.value)"])
def test_inline_resource_no_public_storage_or_destroy(inline_project, native_compile, expression):
    source, _, _ = inline_project
    source.write_text(f"""import ./Foundation.btrc;
int main() {{ unsigned char bytes[3] = {{11, 0, 29}};
var owner = InlineInit(bytes, (size_t)3, InlineSuccess);
{expression}; return 0; }}
""")
    compiled = native_compile(source)
    assert not compiled.successful


@pytest.mark.parametrize("sanitize", [False, True])
def test_inline_fallible_backing_allocation_never_calls_sdk(inline_project, native_compile, sanitize):
    source, sdk, triple = inline_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static int inlineFailure = 0;
static void* inlineStorage = NULL;
static void* inlineInput = NULL;
static inline void InlineFail(int value) { inlineFailure = value; }
static inline int InlineBackingLive(void) { return (inlineStorage != NULL) + (inlineInput != NULL); }
static inline void* InlineCalloc(size_t count, size_t size) {
    int kind = count == 1 && size == sizeof(InlineRecord) ? 1 : count == 1 && size == 3 ? 2 : 0;
    if (kind && inlineFailure == kind) { inlineFailure = 0; return NULL; }
    void* result = calloc(count, size);
    if (kind == 1) { assert(!inlineStorage); inlineStorage = result; }
    if (kind == 2) { assert(!inlineInput); inlineInput = result; }
    return result;
}
static inline void InlineFree(void* value) {
    if (value == inlineStorage) inlineStorage = NULL;
    if (value == inlineInput) inlineInput = NULL;
    free(value);
}
#define calloc InlineCalloc
#define free InlineFree
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(manifest.read_text().replace("symbols = [", 'symbols = ["InlineFail", "InlineBackingLive", '))
    source.write_text("""import ./Foundation.btrc;
int main() {
    unsigned char input[3] = {11, 0, 29};
    for (int failure = 1; failure <= 2; failure++) {
        InlineFail(failure);
        var failed = InlineInit(input, (size_t)3, InlineSuccess);
        assert(!failed.called && failed.value == null);
        assert(InlineCalls() == 0 && InlineEnds() == 0 && InlineBackingLive() == 0);
    }
    var rejected = InlineInit(input, (size_t)3, -4);
    assert(rejected.called && rejected.status == -4 && rejected.value == null);
    assert(InlineBackingLive() == 0 && InlineCalls() == 1 && InlineEnds() == 0);
    var opened = InlineInit(input, (size_t)3, InlineSuccess);
    assert(opened.called && InlineBackingLive() == 2);
    opened.value.close();
    assert(InlineBackingLive() == 0 && InlineEnds() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize("sanitize", [False, True])
def test_inline_initializer_without_copied_input_and_void_destroy(inline_project, native_compile, sanitize):
    source, sdk, triple = inline_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("InlineRecord* record, const void* input, size_t size, int status", "InlineRecord* record, int status")
        .replace(
            "record->self = record; record->input = input; record->size = size;",
            "static const unsigned char input[] = {11, 0, 29}; record->self = record; record->input = input; record->size = 3;",
        )
        .replace("static inline int InlineEnd(", "static inline void InlineEnd(")
        .replace("++inlineEnds; return 91;", "++inlineEnds;")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('read-only-borrows = ["InlineInit.input"]\n', "")
        .replace('release-consumption = "always"\ncleanup-status = "discard"\n', "")
        .replace('[native.bindings.initializers.InlineInit.copied-inputs.input]\nlength = "size"\n', "")
    )
    source.write_text("""import ./Foundation.btrc;
int main() {
    var failed = InlineInit(-8);
    assert(failed.called && failed.status == -8 && failed.value == null && InlineEnds() == 0);
    var opened = InlineInit(InlineSuccess);
    assert(opened.called && opened.value != null && InlineRead(opened.value) == 11);
    opened.value.close(); opened.value.close();
    release opened;
    assert(InlineEnds() == 1);
    InlineInit(InlineSuccess);
    assert(InlineEnds() == 2);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "old,new,diagnostic",
    [
        ("const void* input", "void* input", "const byte pointer"),
        ("size_t size, int status", "int size, int status", "unsigned byte length"),
        ("static const int InlineSuccess", "static int InlineSuccess", "read-only SDK constant"),
        ("size_t size, int status", "size_t size, const int* status", "additional parameters require SDK scalars"),
    ],
)
def test_inline_initializer_validates_actual_header(inline_project, native_compile, old, new, diagnostic):
    source, _, _ = inline_project
    root = source.parent.parent
    header = root / "Foundation.h"
    contents = header.read_text().replace(old, new)
    if "const int* status" in new:
        contents = contents.replace(
            "if (status != InlineSuccess) return status;", "if (*status != InlineSuccess) return *status;"
        ).replace("return status;", "return *status;")
    header.write_text(contents)
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


def test_inline_initializer_narrow_unsigned_length(inline_project, native_compile):
    source, sdk, triple = inline_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(header.read_text().replace("size_t size, int status", "unsigned int size, int status"))
    source.write_text("""import ./Foundation.btrc;
int main() {
    unsigned char input[3] = {11, 0, 29};
    var value = InlineInit(input, 3u, InlineSuccess);
    assert(value.called && value.value != null);
    value.value.close();
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, False, frameworks=())


@pytest.mark.parametrize("sanitize", [False, True])
def test_inline_initializer_declared_nonzero_success(inline_project, native_compile, sanitize):
    source, sdk, triple = inline_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text().replace("if (status != InlineSuccess) return status;", "if (status == 0) return 0;")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(manifest.read_text().replace('success = "InlineSuccess"', "success-nonzero = true"))
    source.write_text("""import ./Foundation.btrc;
int main() {
    unsigned char input[3] = {11, 0, 29};
    var failed = InlineInit(input, (size_t)3, 0);
    assert(failed.called && failed.status == 0 && failed.value == null);
    var opened = InlineInit(input, (size_t)3, -9);
    assert(opened.called && opened.status == -9 && opened.value != null);
    opened.value.close(); assert(InlineEnds() == 1);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, root, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "replacement", ["success-nonzero = false", 'success = "InlineSuccess"\nsuccess-nonzero = true', ""]
)
def test_inline_initializer_requires_one_success_fact(inline_project, native_compile, replacement):
    source, _, _ = inline_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace('success = "InlineSuccess"', replacement))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "success" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.fixture
def attachment_project(inline_project):
    source, sdk, triple = inline_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("InlineRecord* record, const void* input, size_t size, int status", "InlineRecord* record, int status")
        .replace("record->self = record; record->input = input; record->size = size;", "record->self = record;")
        .replace(
            "assert(record && record->self == record && record->size == 3);",
            "assert(record && record->self == record);",
        )
        .replace(
            "assert(record->input[0] == 11 && record->input[1] == 0 && record->input[2] == 29);",
            "if (record->size) { assert(record->size == 3 && record->input[0] == 11 && record->input[1] == 0 && record->input[2] == 29); }",
        )
        + """
#include <stdatomic.h>
#include <sched.h>
static atomic_int inlinePaused = 0, inlineEntered = 0;
static int inlineSets = 0, inlineFailInput = 0;
static inline void InlinePause(void) { atomic_store(&inlinePaused, 1); }
static inline void InlineWait(void) { while (!atomic_load(&inlineEntered)) sched_yield(); }
static inline void InlineAllow(void) { atomic_store(&inlinePaused, 0); }
static inline int InlineSets(void) { return inlineSets; }
static inline void InlineSet(InlineRecord* record, const void* input, size_t size) {
    assert(record && record->self == record && !record->input && input);
    atomic_store(&inlineEntered, 1);
    while (atomic_load(&inlinePaused)) sched_yield();
    record->input = input; record->size = size; ++inlineSets;
}
static inline void InlineFailNextInput(void) { inlineFailInput = 1; }
static inline void* InlineInputCalloc(size_t count, size_t size) {
    if (inlineFailInput && count == 1 && size == 3) { inlineFailInput = 0; return NULL; }
    return calloc(count, size);
}
#define calloc InlineInputCalloc
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace(
            "symbols = [",
            'symbols = ["InlineSet", "InlineSets", "InlineFailNextInput", "InlinePause", "InlineWait", "InlineAllow", ',
        )
        .replace('read-only-borrows = ["InlineInit.input"]', 'read-only-borrows = ["InlineSet.input"]')
        .replace(
            'borrowed-parameters = ["InlineRead.record"]',
            'borrowed-parameters = ["InlineRead.record", "InlineSet.record"]',
        )
        .replace('[native.bindings.initializers.InlineInit.copied-inputs.input]\nlength = "size"\n', "")
        + """
[native.bindings.copied-inputs."InlineSet.input"]
owner = "record"
length = "size"
assignment = "once"
"""
    )
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_inline_input_attachment_owns_copy_and_oom_retry(attachment_project, native_compile, sanitize):
    source, sdk, triple = attachment_project
    source.write_text("""import ./Foundation.btrc;
int main() {
    var opened = InlineInit(InlineSuccess);
    InlineRecord owner = opened.value;
    unsigned char input[3] = {11, 0, 29};
    InlineFailNextInput();
    assert(!InlineSet(owner, input, (size_t)3));
    assert(owner.isOpen() && InlineSets() == 0);
    var attach = InlineSet;
    assert(attach(owner, input, (size_t)3));
    input[0] = 99;
    var alias = owner;
    release opened; release owner;
    assert(InlineRead(alias) == 11 && InlineSets() == 1);
    assert(alias.close() == 91 && !alias.isOpen());
    var empty = InlineInit(InlineSuccess);
    assert(InlineSet(empty.value, null, (size_t)0));
    empty.value.close();
    assert(InlineSets() == 2 && InlineEnds() == 2);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "operation,diagnostic",
    [
        ("InlineSet(owner, null, (size_t)0);", "input already attached"),
        ("owner.close(); InlineSet(owner, null, (size_t)0);", "use after close"),
    ],
)
def test_inline_input_attachment_rejects_alias_replacement(attachment_project, native_compile, operation, diagnostic):
    source, sdk, triple = attachment_project
    source.write_text(f"""import ./Foundation.btrc;
int main() {{
    var opened = InlineInit(InlineSuccess); InlineRecord owner = opened.value;
    assert(InlineSet(owner, null, (size_t)0));
    {operation}
    return 0;
}}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source, source.parent.parent, sdk, triple, False, frameworks=(), expected_failure=diagnostic
    )


@pytest.mark.parametrize("sanitize", [False, True])
def test_inline_input_attachment_serializes_concurrent_close(attachment_project, native_compile, sanitize):
    source, sdk, triple = attachment_project
    source.write_text("""import ./Foundation.btrc;
import Library.OwnedBuffer;
int main() {
    var opened = InlineInit(InlineSuccess); InlineRecord owner = opened.value;
    OwnedBuffer<unsigned char> input = OwnedBuffer((size_t)3);
    assert(input.opened()); input.set((size_t)0, 11); input.set((size_t)2, 29);
    InlinePause();
    var attach = spawn(() => { return InlineSet(owner, input.borrow(), (size_t)3); });
    InlineWait(); assert(!owner.isOpen());
    var close = spawn(() => { return owner.close(); });
    InlineAllow();
    assert(attach.join() && close.join() == 91);
    assert(InlineSets() == 1 && InlineEnds() == 1 && !owner.isOpen());
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "operation,diagnostic",
    [
        ("assert(!self.owner.isOpen());", None),
        ("self.owner.close();", "reentrant close"),
        ("InlineSet(self.owner, null, (size_t)0);", "exclusive operation in progress"),
    ],
)
def test_inline_input_attachment_reentrant_callback(attachment_project, native_compile, operation, diagnostic):
    source, sdk, triple = attachment_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace(
            "static inline void InlineSet(",
            "static void (*inlineAction)(void*);\nstatic void* inlineActionContext;\nstatic inline void InlineSet(",
        )
        .replace(
            "record->input = input; record->size = size; ++inlineSets;",
            "if (inlineAction) inlineAction(inlineActionContext);\n    record->input = input; record->size = size; ++inlineSets;",
        )
        + """
static inline void InlineWithAction(void (*callback)(void*), void* context) {
    assert(!inlineAction); inlineAction = callback; inlineActionContext = context;
    callback(context);
    inlineAction = NULL; inlineActionContext = NULL;
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("symbols = [", 'symbols = ["InlineWithAction", ')
        + """
[native.bindings.callbacks."InlineWithAction.callback"]
context = "context"
context-index = 0
interface = "IInlineAction"
lifetime = "call"
failure = "abort"
executor = "caller"
"""
    )
    source.write_text(f"""import ./Foundation.btrc;
class Action implements IInlineAction {{
    public InlineRecord owner;
    public int calls = 0;
    public Action(InlineRecord owner) {{ self.owner = owner; }}
    public void invoke() {{
        self.calls++;
        if (self.calls == 1) {{ assert(InlineSet(self.owner, null, (size_t)0)); }}
        else {{ {operation} }}
    }}
}}
int main() {{
    var opened = InlineInit(InlineSuccess);
    var action = Action(opened.value);
    InlineWithAction(action);
    assert(action.calls == 2 && opened.value.isOpen());
    opened.value.close(); assert(InlineEnds() == 1);
    return 0;
}}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source, root, sdk, triple, not diagnostic, frameworks=(), expected_failure=diagnostic
    )


def test_inline_input_attachment_rejects_existing_borrow(attachment_project, native_compile):
    source, sdk, triple = attachment_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
static inline void InlineVisit(InlineRecord* record, void (*callback)(void*), void* context) {
    assert(record && record->self == record); callback(context);
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", 'symbols = ["InlineVisit", ')
        .replace("borrowed-parameters = [", 'borrowed-parameters = ["InlineVisit.record", ')
        + """
[native.bindings.callbacks."InlineVisit.callback"]
context = "context"
context-index = 0
interface = "IInlineAction"
lifetime = "call"
failure = "abort"
executor = "caller"
"""
    )
    source.write_text("""import ./Foundation.btrc;
class Action implements IInlineAction {
    public InlineRecord owner;
    public Action(InlineRecord owner) { self.owner = owner; }
    public void invoke() { InlineSet(self.owner, null, (size_t)0); }
}
int main() {
    var opened = InlineInit(InlineSuccess);
    InlineVisit(opened.value, Action(opened.value));
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source, root, sdk, triple, False, frameworks=(), expected_failure="attachment during borrow"
    )


def test_inline_input_attachment_rejects_concurrent_borrow(attachment_project, native_compile):
    source, sdk, triple = attachment_project
    source.write_text("""import ./Foundation.btrc;
int main() {
    var opened = InlineInit(InlineSuccess); InlineRecord owner = opened.value;
    InlinePause();
    var attach = spawn(() => { return InlineSet(owner, null, (size_t)0); });
    InlineWait();
    InlineRead(owner);
    InlineAllow(); attach.join();
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    run_native_executable(
        compiled.c_source,
        source.parent.parent,
        sdk,
        triple,
        False,
        frameworks=(),
        expected_failure="exclusive operation in progress",
    )
