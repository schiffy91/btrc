"""Guarded SDK unions copy bounded strings/spans while their owner is admitted."""

import pytest

from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from src.tests.python.test_native_import_consumer import run_native_executable


@pytest.fixture
def guarded_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>
enum EventKind { TextEvent = 1, OtherEvent = 2 };
enum WrongKind { WrongTextEvent = 1 };
typedef struct EventOwner {
    enum EventKind type;
    union { struct { const char* label; const unsigned char* bytes; long long length; int value; } text; void* other; } data;
    char storage[8];
} *EventOwner;
static int living;
static EventOwner CreateEvent(void) { EventOwner value = calloc(1, sizeof(*value)); if (!value) abort(); ++living; return value; }
static void DestroyEvent(EventOwner value) { if (value) { --living; free(value); } }
static int EventLiving(void) { return living; }
static void ConfigureEvent(EventOwner value, int mode) {
    memcpy(value->storage, "abc\\0x\\0y", 8); value->type = TextEvent;
    value->data.text.label = value->storage; value->data.text.bytes = (const unsigned char*)value->storage + 4;
    value->data.text.length = 3; value->data.text.value = 42;
    if (mode == 1) { value->type = OtherEvent; value->data.other = (void*)(uintptr_t)1; }
    if (mode == 2) value->data.text.length = -1;
    if (mode == 3) value->data.text.length = LLONG_MAX;
    if (mode == 4) value->data.text.bytes = NULL;
    if (mode == 5) value->data.text.bytes = (const unsigned char*)(uintptr_t)(UINTPTR_MAX - 1);
    if (mode == 6) { value->data.text.length = 0; value->data.text.bytes = NULL; value->data.text.label = NULL; }
    if (mode == 7) { value->data.text.length = 0; value->data.text.label = ""; }
    if (mode == 8) memset(value->storage, 'z', 8);
}
""")
    (source.parent / "Foundation.btrc").write_text("import Library.Bytes;\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "guardedSnapshots"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["EventOwner", "CreateEvent", "DestroyEvent", "ConfigureEvent", "EventLiving", "TextEvent", "WrongTextEvent"]
owned-results = ["CreateEvent"]
borrowed-parameters = ["ConfigureEvent.value"]
[native.bindings.resources.EventOwner]
ownership = "unique"
release = "DestroyEvent"
[native.bindings.record-snapshots.EventSnapshot]
owner = "EventOwner"
name = "eventSnapshot"
fields = { value = "data.text.value" }
guard = { field = "type", equals = "TextEvent" }
strings = { label = "data.text.label" }
byte-span = { field = "bytes", pointer = "data.text.bytes", length = "data.text.length" }
""")
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_guarded_snapshot_owns_bounded_values(guarded_project, native_compile, sanitize):
    source, sdk, triple = guarded_project
    source.write_text("""import ./Foundation.btrc;
int main() {
    var owner = CreateEvent(); ConfigureEvent(owner, 0);
    assert(eventSnapshot(owner, -1) == null && eventSnapshot(owner, 2) == null);
    var copied = eventSnapshot(owner, 3);
    assert(copied != null && copied.value == 42 && copied.label == "abc");
    assert(copied.bytes.length() == 3 && copied.bytes.get(0) == 120 && copied.bytes.get(1) == 0 && copied.bytes.get(2) == 121);
    for (int mode = 1; mode <= 5; mode++) { ConfigureEvent(owner, mode); assert(eventSnapshot(owner, 3) == null); }
    ConfigureEvent(owner, 6); var empty = eventSnapshot(owner, 0);
    assert(empty != null && empty.label == null && empty.bytes.length() == 0);
    ConfigureEvent(owner, 7); var blank = eventSnapshot(owner, 0);
    assert(blank != null && blank.label != null && blank.label == "");
    ConfigureEvent(owner, 8); assert(eventSnapshot(owner, 3) == null);
    owner.close(); assert(EventLiving() == 0);
    assert(copied.label == "abc" && copied.bytes.get(2) == 121);
    return 0;
}
""")
    compiled = native_compile(source)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    run_native_executable(compiled.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    "before,after,diagnostic",
    [
        ('equals = "TextEvent"', 'equals = "WrongTextEvent"', "exactly the field's SDK enum"),
        ('guard = { field = "type", equals = "TextEvent" }', "", "unavailable SDK field"),
        ('field = "type", equals', 'field = "data.text.value", equals', "unavailable SDK field"),
        ('length = "data.text.length"', 'length = "data.text.label"', "scalar SDK fields"),
        ('strings = { label = "data.text.label" }', 'strings = { value = "data.text.label" }', "distinct aliases"),
    ],
)
def test_guarded_snapshot_rejects_unproved_contract(guarded_project, native_compile, before, after, diagnostic):
    source, _, _ = guarded_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(before, after))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)
