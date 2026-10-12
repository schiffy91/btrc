"""Raw handles released directly beside managed resources that share their release.

Core Foundation's CFRelease is the managed release of CF objects in one binding
and, in another, the release of a run-loop timer held in plain data. The
operation stays reserved: only a call passing exactly a declared unmanaged
handle is admitted (CL-REQ-UI2-CF-BORROW; package-manifest.md, "Unmanaged
handles"). This header mimics that shape with one erased release.
"""

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import run_native_executable

HEADER = """#include <stdlib.h>
#include <assert.h>
typedef const void *ObjectRef;
typedef struct ObjectHeader { int references; int kind; } ObjectHeader;
typedef struct WidgetStorage { ObjectHeader header; int value; } *WidgetRef;
typedef struct TimerStorage { ObjectHeader header; int fires; } *TimerRef;
static int objectsLive = 0;
static inline ObjectRef ObjectRetain(ObjectRef object) {
    ObjectHeader *header = (ObjectHeader *)object;
    assert(header && header->references > 0);
    ++header->references;
    return object;
}
static inline void ObjectRelease(ObjectRef object) {
    ObjectHeader *header = (ObjectHeader *)object;
    assert(header && header->references > 0);
    if (--header->references == 0) { --objectsLive; free(header); }
}
static inline WidgetRef WidgetCreate(int value) {
    WidgetRef widget = malloc(sizeof(*widget)); assert(widget);
    widget->header.references = 1; widget->header.kind = 1; widget->value = value; ++objectsLive;
    return widget;
}
static inline int WidgetRead(WidgetRef widget) { assert(widget); return widget->value; }
static inline TimerRef TimerCreate(void) {
    TimerRef timer = malloc(sizeof(*timer)); assert(timer);
    timer->header.references = 1; timer->header.kind = 2; timer->fires = 0; ++objectsLive;
    return timer;
}
static inline void TimerFire(TimerRef timer) { assert(timer); ++timer->fires; }
static inline int TimerFires(TimerRef timer) { assert(timer); return timer->fires; }
static inline int ObjectsLive(void) { return objectsLive; }
"""

WIDGETS = """[[native.bindings]]
module = "Widgets"
header = "Objects.h"
language = "c"
standard = "c11"
symbols = ["WidgetRef", "WidgetCreate", "WidgetRead", "ObjectRetain", "ObjectRelease", "ObjectsLive"]
owned-results = ["WidgetCreate"]
borrowed-parameters = ["WidgetRead.widget"]
[native.bindings.resources.WidgetRef]
ownership = "reference-counted"
retain = "ObjectRetain"
release = "ObjectRelease"
"""

TIMERS = """[[native.bindings]]
module = "Timers"
header = "Objects.h"
language = "c"
standard = "c11"
symbols = ["TimerRef", "TimerCreate", "TimerFire", "TimerFires", "ObjectRelease"]
[native.bindings.unmanaged-handles.TimerRef]
release = "ObjectRelease"
"""

PROGRAM = """import ./Widgets.btrc;
import ./Timers.btrc;
#include <assert.h>
struct TimerState { TimerRef timer; int armed; };
int main() {
	var widget = WidgetCreate(7);
	assert(WidgetRead(widget) == 7);
	struct TimerState state;
	state.timer = TimerCreate();
	state.armed = 1;
	TimerFire(state.timer);
	assert(TimerFires(state.timer) == 1 && ObjectsLive() == 2);
	BODY
	return 0;
}
"""

RELEASE = "ObjectRelease(state.timer);\n\tstate.timer = null;\n\tassert(ObjectsLive() == 1);"


def _project(native_project, bindings, body=RELEASE):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "Objects.h").write_text(HEADER, encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "unmanagedHandles"\n' + "".join(bindings), encoding="utf-8"
    )
    for module in ("Widgets", "Timers", "Plain"):
        (source.parent / f"{module}.btrc").write_text("// Native wrapper module.\n", encoding="utf-8")
    source.write_text(PROGRAM.replace("BODY", body), encoding="utf-8")
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("order", ["managed-first", "unmanaged-first"])
def test_unmanaged_handle_release_beside_a_managed_family(native_project, native_compile, order, sanitize):
    bindings = [WIDGETS, TIMERS] if order == "managed-first" else [TIMERS, WIDGETS]
    source, sdk, triple = _project(native_project, bindings)
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(result.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("ObjectRelease(widget);", "may release only a declared unmanaged handle passed directly"),
        ("ObjectRelease((TimerRef)state.timer);", "may release only a declared unmanaged handle passed directly"),
        ("ObjectRelease(state.timer, state.timer);", "may release only a declared unmanaged handle passed directly"),
        ("var releaser = ObjectRelease;", "reserved for managed cleanup"),
    ],
)
def test_unmanaged_release_admits_only_a_declared_handle(native_project, native_compile, body, message):
    source, _, _ = _project(native_project, [WIDGETS, TIMERS], body)
    result = native_compile(source)
    assert not result.successful
    assert message in str(result.failure) + str(result.diagnostics)


PLAIN = """[[native.bindings]]
module = "Plain"
header = "Objects.h"
language = "c"
standard = "c11"
symbols = ["ObjectRelease"]
"""


@pytest.mark.parametrize("order", ["managed-first", "plain-first"])
def test_an_ordinary_lifetime_selection_is_reserved_in_either_order(native_project, native_compile, order):
    bindings = [WIDGETS, PLAIN] if order == "managed-first" else [PLAIN, WIDGETS]
    source, _, _ = _project(native_project, bindings)
    source.write_text("import ./Widgets.btrc;\nimport ./Plain.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert "resource lifetime operations are reserved across native bindings" in str(result.failure) + str(
        result.diagnostics
    )


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        (
            [
                WIDGETS.replace('"WidgetRef", ', '"WidgetRef", "TimerRef", ')
                + '[native.bindings.resources.TimerRef]\nownership = "reference-counted"\nretain = "ObjectRetain"\nrelease = "ObjectRelease"\n',
                TIMERS,
            ],
            "unmanaged handle 'TimerRef' is a managed resource",
        ),
        (
            [WIDGETS, TIMERS.replace('release = "ObjectRelease"', 'release = "TimerFires"')],
            "must take one pointer and return void",
        ),
        (
            [WIDGETS, TIMERS.replace('"TimerFires", "ObjectRelease"]', '"TimerFires"]')],
            "requires a selected record-pointer typedef",
        ),
        (
            [WIDGETS, TIMERS.replace("unmanaged-handles.TimerRef", "unmanaged-handles.TimerCreate")],
            "requires a selected record-pointer typedef",
        ),
    ],
)
def test_unmanaged_handles_reject_unchecked_mappings(native_project, native_compile, bindings, message):
    source, _, _ = _project(native_project, bindings)
    result = native_compile(source)
    assert not result.successful
    assert message in str(result.failure) + str(result.diagnostics)
