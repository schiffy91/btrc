"""COM interfaces through both compilers (interop step 5, slice A).

A COM interface is an `ownership = "com"` resource: a record typedef whose
first field `lpVtbl` points to its function table. AddRef and Release are
slots 1 and 2, so every BTRC value of the interface holds one claim, ended by
exactly one Release. Factories, [out] parameters and QueryInterface each hand
over one claim; [in] interfaces are borrowed for the call; a declared `base`
is checked slot by slot, so widening to it is static. Methods dispatch through
`lpVtbl`, `(T?)value` asks QueryInterface, and `sameObject` compares IUnknown
identities. Library.COM's COMApartment counts every claim and checks that each
adapter runs on its apartment's thread (native-interop-ownership.md section
2.4).

ComShape.h is a Linux/macOS proxy of COM's C shape: a 32-bit HRESULT and ULONG,
GUID, extern IIDs, a flattened IUnknown prefix in every table, and a counter
server whose objects count their creation, AddRef and Release calls. The
program runs through both compilers, plain and under ASan/UBSan, at -O0 and
-O2, and ends with no live object and exactly one Release per claim.
"""

import os
import shutil
import subprocess

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import REPO, apple_environment, zig_libc
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#ifndef COM_SHAPE_H
#define COM_SHAPE_H
#include <stdint.h>

typedef int32_t HRESULT;
typedef uint32_t ULONG;
typedef uint32_t DWORD;
typedef struct _GUID { uint32_t Data1; uint16_t Data2; uint16_t Data3; uint8_t Data4[8]; } GUID;
typedef GUID IID;
#define REFIID const IID *
#define S_OK ((HRESULT)0)
#define S_FALSE ((HRESULT)1)
#define E_NOINTERFACE ((HRESULT)-2147467262)
#define E_FAIL ((HRESULT)-2147467259)
#define E_INVALIDARG ((HRESULT)-2147024809)

extern const IID IID_IUnknown;
extern const IID IID_IBaseCounter;
extern const IID IID_ICounter;
extern const IID IID_IReader;
extern const IID IID_IMissing;

typedef struct IUnknown IUnknown;
typedef struct IUnknownVtbl {
    HRESULT (*QueryInterface)(IUnknown* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(IUnknown* This);
    ULONG (*Release)(IUnknown* This);
} IUnknownVtbl;
struct IUnknown { const IUnknownVtbl* lpVtbl; };

typedef struct IBaseCounter IBaseCounter;
typedef struct IBaseCounterVtbl {
    HRESULT (*QueryInterface)(IBaseCounter* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(IBaseCounter* This);
    ULONG (*Release)(IBaseCounter* This);
    int32_t (*Value)(IBaseCounter* This);
} IBaseCounterVtbl;
struct IBaseCounter { const IBaseCounterVtbl* lpVtbl; };

typedef struct ICounter ICounter;
typedef struct ICounterVtbl {
    HRESULT (*QueryInterface)(ICounter* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(ICounter* This);
    ULONG (*Release)(ICounter* This);
    int32_t (*Value)(ICounter* This);
    HRESULT (*Add)(ICounter* This, int32_t amount);
    HRESULT (*Clone)(ICounter* This, ICounter** copy);
    HRESULT (*Fail)(ICounter* This, ICounter** copy);
    HRESULT (*Split)(ICounter* This, ICounter** part);
    HRESULT (*Fork)(ICounter* This, ICounter** left, ICounter** right);
    HRESULT (*Absorb)(ICounter* This, ICounter* other);
    ULONG (*Count)(ICounter* This);
} ICounterVtbl;
struct ICounter { const ICounterVtbl* lpVtbl; };

typedef struct IReader IReader;
typedef struct IReaderVtbl {
    HRESULT (*QueryInterface)(IReader* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(IReader* This);
    ULONG (*Release)(IReader* This);
    int32_t (*Read)(IReader* This);
} IReaderVtbl;
struct IReader { const IReaderVtbl* lpVtbl; };

typedef struct IMissing IMissing;
typedef struct IMissingVtbl {
    HRESULT (*QueryInterface)(IMissing* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(IMissing* This);
    ULONG (*Release)(IMissing* This);
} IMissingVtbl;
struct IMissing { const IMissingVtbl* lpVtbl; };

/* Factories: one claim each. CounterOpen refuses a negative value. */
ICounter* CounterCreate(int32_t value);
HRESULT CounterOpen(int32_t value, ICounter** counter);

/* The server's accounting and its fault switches. */
int ServerLive(void);
int ServerCreated(void);
int ServerAddRefs(void);
int ServerReleases(void);
int ServerApartmentCalls(void);
int ServerAbsorbedReferences(void);
/* 1: the next QueryInterface fails with E_FAIL; 2: it fails but still writes an interface. */
void ServerFailNextQuery(int mode);
void CounterDetach(ICounter* counter);
#endif
"""

SERVER = """#include "ComShape.h"
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

const IID IID_IUnknown = {0x00000000u, 0x0000u, 0x0000u, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
const IID IID_IBaseCounter = {0x0B7C0001u, 0x0001u, 0x0001u, {1, 2, 3, 4, 5, 6, 7, 1}};
const IID IID_ICounter = {0x0B7C0002u, 0x0002u, 0x0002u, {1, 2, 3, 4, 5, 6, 7, 2}};
const IID IID_IReader = {0x0B7C0003u, 0x0003u, 0x0003u, {1, 2, 3, 4, 5, 6, 7, 3}};
const IID IID_IMissing = {0x0B7C0004u, 0x0004u, 0x0004u, {1, 2, 3, 4, 5, 6, 7, 4}};

/* One server object answers ICounter (and its bases) and IReader. */
typedef struct CounterObject { ICounter counter; IReader reader; ULONG references; int32_t value; } CounterObject;

static int live, created, addRefs, releases, apartmentCalls, absorbedReferences, failNextQuery;

static CounterObject* fromCounter(ICounter* This) { return (CounterObject*)(void*)This; }
static CounterObject* fromReader(IReader* This) { return (CounterObject*)(void*)((char*)This - offsetof(CounterObject, reader)); }

static ULONG objectAddRef(CounterObject* object) {
    assert(object->references > 0);
    addRefs++;
    return ++object->references;
}

static ULONG objectRelease(CounterObject* object) {
    assert(object->references > 0);
    releases++;
    ULONG remaining = --object->references;
    if (remaining == 0) { live--; free(object); }
    return remaining;
}

static int sameGuid(REFIID left, REFIID right) { return memcmp(left, right, sizeof(GUID)) == 0; }

static HRESULT objectQuery(CounterObject* object, REFIID riid, void** out) {
    *out = NULL;
    int mode = failNextQuery;
    failNextQuery = 0;
    if (mode == 1) { return E_FAIL; }
    if (mode == 2) { objectAddRef(object); *out = &object->counter; return E_FAIL; }
    if (sameGuid(riid, &IID_IUnknown) || sameGuid(riid, &IID_IBaseCounter) || sameGuid(riid, &IID_ICounter)) {
        *out = &object->counter;
    } else if (sameGuid(riid, &IID_IReader)) {
        *out = &object->reader;
    } else {
        return E_NOINTERFACE;
    }
    objectAddRef(object);
    return S_OK;
}

static ICounter* newCounter(int32_t value);

static HRESULT counterQuery(ICounter* This, REFIID riid, void** out) { return objectQuery(fromCounter(This), riid, out); }
static ULONG counterAddRef(ICounter* This) { return objectAddRef(fromCounter(This)); }
static ULONG counterRelease(ICounter* This) { return objectRelease(fromCounter(This)); }
static int32_t counterValue(ICounter* This) { return fromCounter(This)->value; }
static HRESULT counterAdd(ICounter* This, int32_t amount) {
    if (amount < 0) { return E_INVALIDARG; }
    fromCounter(This)->value += amount;
    return S_OK;
}
static HRESULT counterClone(ICounter* This, ICounter** copy) {
    *copy = NULL;
    if (fromCounter(This)->value == 13) { return E_FAIL; }
    *copy = newCounter(fromCounter(This)->value);
    return S_OK;
}
/* A failing call that still writes its output: the caller adopts and releases it. */
static HRESULT counterFail(ICounter* This, ICounter** copy) {
    *copy = newCounter(fromCounter(This)->value);
    return E_FAIL;
}
/* An odd value fails, yet still hands over a part: every nonnull output is a claim. */
static HRESULT counterSplit(ICounter* This, ICounter** part) {
    *part = newCounter(fromCounter(This)->value / 2);
    return fromCounter(This)->value % 2 ? E_FAIL : S_FALSE;
}
static HRESULT counterFork(ICounter* This, ICounter** left, ICounter** right) {
    *left = newCounter(fromCounter(This)->value);
    *right = newCounter(fromCounter(This)->value);
    return S_OK;
}
static HRESULT counterAbsorb(ICounter* This, ICounter* other) {
    if (other == NULL) { return E_INVALIDARG; }
    absorbedReferences = (int)fromCounter(other)->references;
    fromCounter(This)->value += other->lpVtbl->Value(other);
    return S_OK;
}
static ULONG counterCount(ICounter* This) { return fromCounter(This)->references; }

static HRESULT readerQuery(IReader* This, REFIID riid, void** out) { return objectQuery(fromReader(This), riid, out); }
static ULONG readerAddRef(IReader* This) { return objectAddRef(fromReader(This)); }
static ULONG readerRelease(IReader* This) { return objectRelease(fromReader(This)); }
static int32_t readerRead(IReader* This) { return fromReader(This)->value; }

static const ICounterVtbl counterTable = {
    counterQuery, counterAddRef, counterRelease, counterValue, counterAdd, counterClone,
    counterFail, counterSplit, counterFork, counterAbsorb, counterCount,
};
static const IReaderVtbl readerTable = {readerQuery, readerAddRef, readerRelease, readerRead};

static ICounter* newCounter(int32_t value) {
    CounterObject* object = calloc(1, sizeof *object);
    assert(object != NULL);
    object->counter.lpVtbl = &counterTable;
    object->reader.lpVtbl = &readerTable;
    object->references = 1;
    object->value = value;
    live++;
    created++;
    return &object->counter;
}

ICounter* CounterCreate(int32_t value) { return newCounter(value); }

HRESULT CounterOpen(int32_t value, ICounter** counter) {
    *counter = NULL;
    if (value < 0) { return E_INVALIDARG; }
    *counter = newCounter(value);
    return S_OK;
}

int ServerLive(void) { return live; }
int ServerCreated(void) { return created; }
int ServerAddRefs(void) { return addRefs; }
int ServerReleases(void) { return releases; }
int ServerApartmentCalls(void) { return apartmentCalls; }
int ServerAbsorbedReferences(void) { return absorbedReferences; }
void ServerFailNextQuery(int mode) { failNextQuery = mode; }
void CounterDetach(ICounter* counter) { counter->lpVtbl = NULL; }

/* The proxy's stand-ins for ole32, which Library.COM's runtime calls. */
HRESULT CoInitializeEx(void* reserved, DWORD model) {
    (void)reserved;
    assert(model == 0x2);
    apartmentCalls++;
    return S_OK;
}
void CoUninitialize(void) { apartmentCalls++; }
"""

SYMBOLS = [
    "IUnknown",
    "IBaseCounter",
    "ICounter",
    "IReader",
    "IMissing",
    "IID_IUnknown",
    "IID_IBaseCounter",
    "IID_ICounter",
    "IID_IReader",
    "IID_IMissing",
    "CounterCreate",
    "CounterOpen",
    "ServerLive",
    "ServerCreated",
    "ServerAddRefs",
    "ServerReleases",
    "ServerApartmentCalls",
    "ServerAbsorbedReferences",
    "ServerFailNextQuery",
    "CounterDetach",
]

MANIFEST = """manifest-version = 1
[package]
name = "comConsumer"

[[native.sources]]
path = "ComServer.c"
language = "c"
standard = "c11"
modules = ["Counters"]

[[native.bindings]]
module = "Counters"
header = "ComShape.h"
language = "c"
standard = "c11"
symbols = [SYMBOLS]
owned-results = ["CounterCreate"]
borrowed-parameters = ["CounterDetach.counter"]

[native.bindings.resources.IUnknown]
ownership = "com"
iid = "IID_IUnknown"
release-executor = "apartment"

[native.bindings.resources.IBaseCounter]
ownership = "com"
iid = "IID_IBaseCounter"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.IBaseCounter.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IBaseCounter.dispatch.methods]
value = "Value"

[native.bindings.resources.ICounter]
ownership = "com"
iid = "IID_ICounter"
base = "IBaseCounter"
release-executor = "apartment"

[native.bindings.resources.ICounter.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.ICounter.dispatch.methods]
value = "Value"
add = "Add"
clone = "Clone"
fail = "Fail"
split = "Split"
absorb = "Absorb"
count = "Count"

[native.bindings.resources.IReader]
ownership = "com"
iid = "IID_IReader"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.IReader.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IReader.dispatch.methods]
read = "Read"

[native.bindings.resources.IMissing]
ownership = "com"
iid = "IID_IMissing"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.status-results]
"ICounter.add" = "hresult"
"ICounter.clone" = "hresult"
"ICounter.fail" = "hresult"

[native.bindings.owned-outputs."ICounter.split.part"]
result = "CounterSplit"
status = "hresult"

[native.bindings.owned-outputs."CounterOpen.counter"]
result = "CounterOpening"
status = "hresult"
""".replace("SYMBOLS", ", ".join(f'"{symbol}"' for symbol in SYMBOLS))

PROGRAM = """import Library.COM.COMApartment;
import ./Counters.btrc;
#include <assert.h>
#include <stdio.h>

void exercise() {
	var counter = CounterCreate(5);
	assert(counter != null);
	assert(COMApartment.liveClaims() == 1);
	assert(counter.value() == 5);
	// A status-results method without an output returns its nonnegative HRESULT.
	assert(counter.add(2) == 0);
	assert(counter.value() == 7);
	string refused = "";
	try { counter.add(-1); }
	catch (string error) { refused = error; }
	assert(refused.equals("COM ICounter.add failed with HRESULT 0x80070057"));

	// A declared base widens statically, slot for slot.
	IBaseCounter? base = counter;
	assert(base != null && base.value() == 7);
	var alias = counter;
	assert(alias == counter);
	assert(COMApartment.liveClaims() == 3);

	// An [out] interface is one adopted claim.
	var copy = counter.clone();
	assert(copy != null && copy.value() == 7);
	assert(!IUnknown.sameObject(copy, counter));
	// An [in] interface is borrowed for the call.
	assert(counter.absorb(copy) == 0);
	assert(counter.value() == 14 && ServerAbsorbedReferences() >= 2);
	// A failing HRESULT releases the adopted output before it throws.
	int liveBefore = ServerLive();
	string failure = "";
	try { counter.fail(); }
	catch (string error) { failure = error; }
	assert(failure.equals("COM ICounter.fail failed with HRESULT 0x80004005"));
	assert(ServerLive() == liveBefore);

	// The owned-outputs result class carries the HRESULT and adopts on every status.
	var even = counter.split();
	ICounter? half = even.value;
	assert(even.status == 1 && half != null && half.value() == 7);
	var odd = half.split();
	ICounter? third = odd.value;
	assert(odd.status < 0 && third != null && third.value() == 3);
	var opened = CounterOpen(4);
	ICounter? fresh = opened.value;
	assert(opened.status == 0 && fresh != null && fresh.value() == 4);
	var closed = CounterOpen(-1);
	assert(closed.status < 0 && closed.value == null);

	// QueryInterface (M3): a new claim, or null for E_NOINTERFACE.
	IReader? reader = (IReader?)counter;
	assert(reader != null && reader.read() == 14);
	assert(IUnknown.sameObject(reader, counter));
	assert(IUnknown.sameObject(null, null) && !IUnknown.sameObject(reader, null));
	ICounter? back = (ICounter?)reader;
	assert(back != null && back == counter);
	IMissing? missing = (IMissing?)counter;
	assert(missing == null);
	ICounter? nothing = null;
	assert((IReader?)nothing == null);

	for (int index = 0; index < 1000; index++) {
		var transient = CounterCreate(index);
		IReader? view = (IReader?)transient;
		assert(view != null && view.read() == index);
	}
}

int main() {
	COMApartment.initialize();
	assert(COMApartment.initialized());
	exercise();
	assert(COMApartment.liveClaims() == 0);
	COMApartment.uninitialize();
	assert(!COMApartment.initialized());
	assert(ServerLive() == 0);
	assert(ServerReleases() == ServerCreated() + ServerAddRefs());
	assert(ServerApartmentCalls() == 2);
	printf("com-ok %d %d %d\\n", ServerCreated(), ServerAddRefs(), ServerReleases());
	return 0;
}
"""


@pytest.fixture
def com_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").unlink()
    (root / "ComShape.h").write_text(HEADER, encoding="utf-8")
    (root / "ComServer.c").write_text(SERVER, encoding="utf-8")
    (root / "btrc.toml").write_text(MANIFEST, encoding="utf-8")
    (source.parent / "Foundation.btrc").unlink()
    (source.parent / "Counters.btrc").write_text("// The COM binding's module.\n", encoding="utf-8")
    source.write_text(PROGRAM, encoding="utf-8")
    return source


def build(source, native_compile, optimization=2, sanitize=False):
    root = source.parent.parent
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = root / "Program"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=all"] if sanitize else []

    def run(command, **kwargs):
        if os.path.basename(command[0]).startswith("clang"):
            command = [command[0], *flags, *command[1:]]
        return subprocess.run(command, env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        optimization=optimization,
    )
    return compiled.c_source, executable


def run(executable):
    return subprocess.run([str(executable)], capture_output=True, text=True, timeout=60, check=False)


@pytest.mark.parametrize("optimization", [0, 2])
@pytest.mark.parametrize("sanitize", [False, True])
def test_com_interfaces_count_every_claim(com_project, native_compile, optimization, sanitize):
    c_source, executable = build(com_project, native_compile, optimization, sanitize)
    # Every slot call reloads lpVtbl; AddRef and Release go through it too.
    assert "->lpVtbl" in c_source and "QueryInterface" in c_source
    completed = run(executable)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert completed.stdout.startswith("com-ok "), completed.stdout


OPENED = "COMApartment.initialize(); var counter = CounterCreate(1);"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # Any QueryInterface failure other than E_NOINTERFACE terminates.
        (
            OPENED + " ServerFailNextQuery(1); IReader? reader = (IReader?)counter;",
            "Native COM ICounter.QueryInterface failed with HRESULT 0x80004005",
        ),
        # A failure that still wrote an interface adopts it, then terminates.
        (
            OPENED + " ServerFailNextQuery(2); IReader? reader = (IReader?)counter;",
            "Native COM ICounter.QueryInterface: a failed query returned an interface",
        ),
        # The apartment cannot end while BTRC holds an interface.
        (OPENED + " COMApartment.uninitialize();", "Library.COM: uninitialize with 1 live COM claims"),
        # The SDK owns the table, and every call reloads it: ending the
        # argument's borrow after the table is gone terminates.
        (OPENED + " CounterDetach(counter);", "Native COM ICounter.Release: null function table"),
        # Every adapter checks that it runs in the apartment.
        ("var counter = CounterCreate(1);", "Library.COM: COM call outside its apartment"),
    ],
)
@pytest.mark.parametrize("optimization", [0, 2])
@pytest.mark.parametrize("sanitize", [False, True])
def test_com_failures_terminate(com_project, native_compile, body, expected, optimization, sanitize):
    com_project.write_text(
        f"import Library.COM.COMApartment;\nimport ./Counters.btrc;\nint main() {{ {body} return 0; }}\n",
        encoding="utf-8",
    )
    _, executable = build(com_project, native_compile, optimization, sanitize)
    completed = run(executable)
    assert completed.returncode < 0, (completed.returncode, completed.stderr)
    assert expected in completed.stderr, completed.stderr


def rejected(source, native_compile):
    result = native_compile(source)
    assert not result.successful
    return str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    ("path", "before", "after", "message"),
    [
        # Slots 0-2 must be IUnknown's, in order, with their real signatures.
        (
            "ComShape.h",
            "    ULONG (*Release)(IReader* This);",
            "    int32_t (*Release)(IReader* This);",
            "lpVtbl slots 0-2 are not IUnknown-shaped",
        ),
        (
            "ComShape.h",
            "    HRESULT (*QueryInterface)(IMissing* This, REFIID riid, void** ppvObject);\n"
            "    ULONG (*AddRef)(IMissing* This);",
            "    ULONG (*AddRef)(IMissing* This);\n"
            "    HRESULT (*QueryInterface)(IMissing* This, REFIID riid, void** ppvObject);",
            "lpVtbl slots 0-2 are not IUnknown-shaped",
        ),
        (
            "ComShape.h",
            "HRESULT (*QueryInterface)(IReader* This, REFIID riid, void** ppvObject);",
            "HRESULT (*QueryInterface)(IReader* This, const GUID* riid, IReader** ppvObject);",
            "lpVtbl slots 0-2 are not IUnknown-shaped",
        ),
        # The reader resolves each slot through lpVtbl before the importer runs.
        (
            "ComShape.h",
            "struct IMissing { const IMissingVtbl* lpVtbl; };",
            "struct IMissing { const IMissingVtbl* table; };",
            "Record path names an unavailable SDK field: IMissing.lpVtbl",
        ),
        (
            "ComShape.h",
            "struct IMissing { const IMissingVtbl* lpVtbl; };",
            "struct IMissing { int tag; const IMissingVtbl* lpVtbl; };",
            "first field lpVtbl points to a complete SDK table",
        ),
        # A base is a slot-by-slot prefix, signatures equal except This.
        (
            "ComShape.h",
            "    int32_t (*Value)(ICounter* This);",
            "    int64_t (*Value)(ICounter* This);",
            "base IBaseCounter is not a slot-by-slot prefix of its lpVtbl table",
        ),
        ("btrc.toml", 'iid = "IID_IReader"', 'iid = "ServerLive"', "iid ServerLive is not a read-only GUID global"),
        ("btrc.toml", 'iid = "IID_IReader"', 'iid = "IID_Absent"', "com resources require a selected iid"),
        ("btrc.toml", 'base = "IBaseCounter"', 'base = "ICounter"', "com base requires another com resource"),
        ("btrc.toml", 'base = "IBaseCounter"', 'base = "IAbsent"', "com base requires another com resource"),
        (
            "btrc.toml",
            'iid = "IID_IMissing"\nbase = "IUnknown"\nrelease-executor = "apartment"',
            'iid = "IID_IMissing"\nbase = "IUnknown"',
            "release-executor currently requires apartment on a com resource",
        ),
        (
            "btrc.toml",
            'iid = "IID_IMissing"\nbase = "IUnknown"\nrelease-executor = "apartment"',
            'iid = "IID_IMissing"\nbase = "IUnknown"\nrelease-executor = "worker"',
            "release-executor must be caller, main, main-context, apartment or any",
        ),
        (
            "btrc.toml",
            'iid = "IID_IMissing"\nbase = "IUnknown"',
            'iid = "IID_IMissing"\nbase = "IUnknown"\nretain = "CounterCreate"',
            "com resources take AddRef, Release and QueryInterface from lpVtbl",
        ),
        (
            "btrc.toml",
            'ownership = "com"\niid = "IID_IMissing"',
            'ownership = "unique"\nrelease = "CounterDetach"\niid = "IID_IMissing"',
            "iid and base require a com resource",
        ),
        ("btrc.toml", 'read = "Read"', 'read = "AddRef"', "com dispatch cannot map the IUnknown slots"),
        ("btrc.toml", 'read = "Read"', 'sameObject = "Read"', "cannot shadow resource operations"),
        (
            "btrc.toml",
            '[native.bindings.resources.IReader.dispatch]\ntable = "lpVtbl"\nexecutor = "apartment"',
            '[native.bindings.resources.IReader.dispatch]\ntable = "lpVtbl"\nexecutor = "caller"',
            "executor currently requires apartment",
        ),
        (
            "btrc.toml",
            '[native.bindings.resources.IReader.dispatch]\ntable = "lpVtbl"',
            '[native.bindings.resources.IReader.dispatch]\ntable = "vtbl"',
            "com dispatch requires table = lpVtbl",
        ),
        # Status forms: one per method, on a 32-bit signed HRESULT.
        (
            "btrc.toml",
            '"ICounter.add" = "hresult"',
            '"ICounter.missing" = "hresult"',
            "requires a dispatched com method",
        ),
        (
            "btrc.toml",
            '"ICounter.add" = "hresult"',
            '"ICounter.add" = "boolean"',
            "status-results kind must be hresult",
        ),
        (
            "btrc.toml",
            '"ICounter.add" = "hresult"',
            '"ICounter.add" = "hresult"\n"ICounter.count" = "hresult"',
            "require a 32-bit signed result",
        ),
        (
            "btrc.toml",
            '"ICounter.add" = "hresult"',
            '"ICounter.add" = "hresult"\n"ICounter.split" = "hresult"',
            "a method declares one status form",
        ),
        ("btrc.toml", 'count = "Count"', 'count = "Count"\nfork = "Fork"', "adopts at most one [out] interface"),
        (
            "btrc.toml",
            '"ICounter.clone" = "hresult"\n',
            "",
            "an [out] interface requires status-results or owned-outputs",
        ),
        (
            "btrc.toml",
            'result = "CounterSplit"\nstatus = "hresult"',
            'result = "CounterSplit"',
            "owned-outputs status = hresult pairs with a com interface output",
        ),
        (
            "btrc.toml",
            'result = "CounterOpening"\nstatus = "hresult"',
            'result = "CounterOpening"',
            "owned-outputs status = hresult pairs with a com interface output",
        ),
        (
            "btrc.toml",
            'result = "CounterSplit"\nstatus = "hresult"',
            'result = "CounterSplit"\nstatus = "errno"',
            "owned-outputs status must be hresult",
        ),
        # A COM interface is a record typedef, and needs Library.COM's runtime.
        (
            "Main.btrc",
            "import Library.COM.COMApartment;\n",
            "",
            "COM resources require import Library.COM.COMApartment",
        ),
    ],
)
def test_com_rejects_unchecked_facts(com_project, native_compile, path, before, after, message):
    target = com_project if path == "Main.btrc" else com_project.parent.parent / path
    text = target.read_text(encoding="utf-8")
    assert before in text, before
    target.write_text(text.replace(before, after, 1), encoding="utf-8")
    if path == "Main.btrc":
        target.write_text(
            "import ./Counters.btrc;\nint main() { var counter = CounterCreate(1); return counter == null ? 1 : 0; }\n",
            encoding="utf-8",
        )
    assert message in rejected(com_project, native_compile)


# The real MinGW-w64 declarations of IStream and its bases (objidl.h,
# unknwn.h): both compilers check lpVtbl slots 0-2 and the base prefixes
# against the layouts the reader reads for each Windows target, and the
# generated C compiles and links against ole32 with zig.
WINDOWS_TARGETS = {
    "windows-x64": ("x86_64-w64-windows-gnu", "x86_64"),
    "windows-arm64": ("aarch64-w64-windows-gnu", "aarch64"),
}

STREAM_MANIFEST = """manifest-version = 1
[package]
name = "comStreams"

[[native.bindings]]
module = "Streams"
header = "Streams.h"
language = "c"
standard = "c11"
os = ["windows"]
symbols = ["IUnknown", "ISequentialStream", "IStream", "IID_IUnknown", "IID_ISequentialStream", "IID_IStream", "CreateStreamOnHGlobal"]

[native.bindings.resources.IUnknown]
ownership = "com"
iid = "IID_IUnknown"
release-executor = "apartment"

[native.bindings.resources.ISequentialStream]
ownership = "com"
iid = "IID_ISequentialStream"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.ISequentialStream.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.ISequentialStream.dispatch.methods]
read = "Read"
write = "Write"

[native.bindings.resources.IStream]
ownership = "com"
iid = "IID_IStream"
base = "ISequentialStream"
release-executor = "apartment"

[native.bindings.resources.IStream.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IStream.dispatch.methods]
clone = "Clone"

[native.bindings.status-results]
"IStream.clone" = "hresult"

[native.bindings.owned-outputs."CreateStreamOnHGlobal.ppstm"]
result = "StreamCreation"
status = "hresult"
"""

STREAM_PROGRAM = """import Library.COM.COMApartment;
import ./Streams.btrc;
#include <stdio.h>

int roundTrip() {
	var created = CreateStreamOnHGlobal(null, 1);
	IStream? stream = created.value;
	if (created.status < 0 || stream == null) { return 1; }
	unsigned char bytes[4] = {1, 2, 3, 4};
	ULONG written = 0;
	ISequentialStream? sequential = stream;
	HRESULT status = sequential.write(bytes, 4, &written);
	IStream? copy = stream.clone();
	IStream? queried = (IStream?)sequential;
	bool same = queried != null && IUnknown.sameObject(queried, stream) && !IUnknown.sameObject(copy, stream);
	printf("com-stream status=%d written=%u same=%d claims=%lld\\n", (int)status, (unsigned int)written, (int)same, COMApartment.liveClaims());
	return status == 0 && written == 4 && same ? 0 : 2;
}

int main() {
	COMApartment.initialize();
	int result = roundTrip();
	COMApartment.uninitialize();
	return result;
}
"""


@pytest.fixture
def stream_project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(STREAM_MANIFEST, encoding="utf-8")
    (root / "Streams.h").write_text(
        "#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <objidl.h>\n", encoding="utf-8"
    )
    (root / "src/Streams.btrc").write_text("// The COM binding's module.\n", encoding="utf-8")
    source = root / "src/Main.btrc"
    source.write_text(STREAM_PROGRAM, encoding="utf-8")
    return source


def windows_transpile(frontend, source, target, request, monkeypatch, manifest=None):
    sysroot = zig_libc()
    monkeypatch.setenv("BTRC_NATIVE_TARGET", WINDOWS_TARGETS[target][0])
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(sysroot))
    if manifest is not None:
        (source.parent.parent / "btrc.toml").write_text(manifest, encoding="utf-8")
    if frontend == "reference":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"),
            str(source),
            CompilerOptions(include_stdlib=False, use_cache=False, target=target),
        )
        return result.successful, result.c_source, str(result.failure) + str(result.diagnostics)
    btrcc = request.getfixturevalue("immutable_btrcc")
    completed = subprocess.run(
        [str(btrcc), "--no-stdlib", "--no-cache", "--target", target, str(source)],
        env={**os.environ, "BTRC_HOME": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=False,
    )
    return completed.returncode == 0, completed.stdout, completed.stderr


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_com_layouts_read_from_real_mingw_headers(stream_project, frontend, target, request, monkeypatch, tmp_path):
    successful, c_source, failure = windows_transpile(frontend, stream_project, target, request, monkeypatch)
    assert successful, failure
    generated = tmp_path / "Main.c"
    generated.write_text(c_source, encoding="utf-8")
    executable = tmp_path / f"com-stream-{frontend}-{target}.exe"
    built = subprocess.run(
        [
            shutil.which("zig"),
            "cc",
            "-target",
            f"{WINDOWS_TARGETS[target][1]}-windows-gnu",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(REPO / "src/runtime/windows"),
            "-include",
            str(REPO / "src/runtime/windows/btrc_win_compat.h"),
            "-I",
            str(stream_project.parent.parent),
            "-I",
            str(REPO / "src/stdlib/COM"),
            str(generated),
            str(REPO / "src/stdlib/COM/COMRuntime.c"),
            "-o",
            str(executable),
            "-lole32",
            "-luuid",
            "-lm",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    assert executable.read_bytes()[:2] == b"MZ"


PERSIST_RESOURCE = """
[native.bindings.resources.IPersist]
ownership = "com"
iid = "IID_IPersist"
base = "IUnknown"
release-executor = "apartment"
"""


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        # IPersist's table (GetClassID after IUnknown) is not a prefix of IStream's.
        (
            'iid = "IID_IStream"\nbase = "ISequentialStream"',
            'iid = "IID_IStream"\nbase = "IPersist"',
            "base IPersist is not a slot-by-slot prefix of its lpVtbl table",
        ),
        (
            'iid = "IID_IStream"',
            'iid = "CreateStreamOnHGlobal"',
            "iid CreateStreamOnHGlobal is not a read-only GUID global",
        ),
    ],
)
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_com_real_layouts_reject_unchecked_facts(
    stream_project, frontend, before, after, message, request, monkeypatch
):
    manifest = STREAM_MANIFEST.replace(
        '"CreateStreamOnHGlobal"]', '"CreateStreamOnHGlobal", "IPersist", "IID_IPersist"]'
    )
    manifest = manifest.replace(
        "\n[native.bindings.status-results]", PERSIST_RESOURCE + "\n[native.bindings.status-results]"
    )
    assert before in manifest
    successful, _, failure = windows_transpile(
        frontend, stream_project, "windows-x64", request, monkeypatch, manifest.replace(before, after, 1)
    )
    assert not successful
    assert message in failure, failure
