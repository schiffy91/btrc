"""COM sinks and copied COM strings through both compilers (interop step 5, slice B).

A `com-sinks` entry implements a selected `ownership = "com"` resource's table
with a BTRC handler: the generated holder answers QueryInterface for
IID_IUnknown, the sink's IID and its bases', holds one external claim on its
CallbackContext while its COM count is positive, and is registered with the
source's Advise and cancelled with its Unadvise (native-interop-ownership.md
section 2.4, M2). `copied-outputs` copies a BSTR or CoTaskMemAlloc string an
[out] slot returns into a BTRC string and frees it inside the adapter.

SinkShape.h is a Linux/macOS proxy: a counter whose one connection point
fires its sink's Changed and Reset slots, records the counts its AddRef and
Release on the sink return, can keep or drop a sink against the protocol, and
returns UTF-16 strings from SysAllocString and CoTaskMemAlloc stand-ins that
count their frees. The program runs through both compilers, plain and under
ASan/UBSan, at -O0 and -O2.
"""

import os
import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#ifndef SINK_SHAPE_H
#define SINK_SHAPE_H
#include <stdint.h>

typedef int32_t HRESULT;
typedef uint32_t ULONG;
typedef uint32_t DWORD;
typedef uint16_t OLECHAR;
typedef OLECHAR* BSTR;
typedef OLECHAR* LPOLESTR;
typedef struct _GUID { uint32_t Data1; uint16_t Data2; uint16_t Data3; uint8_t Data4[8]; } GUID;
typedef GUID IID;
#define REFIID const IID *

extern const IID IID_IUnknown;
extern const IID IID_IBaseEvents;
extern const IID IID_ICounterEvents;
extern const IID IID_ICounter;
extern const IID IID_IMissing;

typedef struct IUnknown IUnknown;
typedef struct IUnknownVtbl {
    HRESULT (*QueryInterface)(IUnknown* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(IUnknown* This);
    ULONG (*Release)(IUnknown* This);
} IUnknownVtbl;
struct IUnknown { const IUnknownVtbl* lpVtbl; };

typedef struct IBaseEvents IBaseEvents;
typedef struct IBaseEventsVtbl {
    HRESULT (*QueryInterface)(IBaseEvents* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(IBaseEvents* This);
    ULONG (*Release)(IBaseEvents* This);
    HRESULT (*Changed)(IBaseEvents* This, int32_t value);
} IBaseEventsVtbl;
struct IBaseEvents { const IBaseEventsVtbl* lpVtbl; };

typedef struct ICounterEvents ICounterEvents;
typedef struct ICounterEventsVtbl {
    HRESULT (*QueryInterface)(ICounterEvents* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(ICounterEvents* This);
    ULONG (*Release)(ICounterEvents* This);
    HRESULT (*Changed)(ICounterEvents* This, int32_t value);
    HRESULT (*Reset)(ICounterEvents* This);
} ICounterEventsVtbl;
struct ICounterEvents { const ICounterEventsVtbl* lpVtbl; };

typedef struct ICounter ICounter;
typedef struct ICounterVtbl {
    HRESULT (*QueryInterface)(ICounter* This, REFIID riid, void** ppvObject);
    ULONG (*AddRef)(ICounter* This);
    ULONG (*Release)(ICounter* This);
    HRESULT (*Add)(ICounter* This, int32_t amount);
    HRESULT (*Reset)(ICounter* This);
    HRESULT (*Advise)(ICounter* This, IBaseEvents* sink, DWORD* cookie);
    HRESULT (*Unadvise)(ICounter* This, DWORD cookie);
    HRESULT (*Name)(ICounter* This, BSTR* name);
    HRESULT (*Path)(ICounter* This, LPOLESTR* path);
} ICounterVtbl;
struct ICounter { const ICounterVtbl* lpVtbl; };

/* One claim. */
ICounter* CounterCreate(int32_t value);

/* The allocators copied strings name. */
void SysFreeString(BSTR text);
void CoTaskMemFree(void* block);

/* The server's accounting and its protocol violations. */
int ServerLive(void);
int ServerCreated(void);
int ServerAddRefs(void);
int ServerReleases(void);
/* The largest count an AddRef on a sink returned, and what the last Release returned. */
int ServerSinkPeak(void);
int ServerSinkLast(void);
int ServerStringsAllocated(void);
int ServerStringsFreed(void);
/* 1: Unadvise forgets the cookie but keeps the sink. */
void ServerKeepSinks(int keep);
/* The next Advise fails with E_FAIL. */
void ServerFailNextAdvise(void);
/* 0 a string; 1 S_OK with no string; 2 E_FAIL that still writes one; 3 a BSTR holding U+0000. */
void ServerStringMode(int mode);
int CounterFireKept(ICounter* counter);
void CounterReleaseKept(ICounter* counter);
/* Releases the sink without Unadvise, keeping its pointer. */
void CounterDropSink(ICounter* counter);
/* Calls a slot of the sink: 1 AddRef, 2 QueryInterface, 3 Release, 4 Changed. */
void CounterPokeSink(ICounter* counter, int slot);
void CounterPokeSinkOnThread(ICounter* counter, int slot);
/* QueryInterface on the sink: bit 0 IID_IUnknown, 1 IID_ICounterEvents, 2 IID_IBaseEvents
 * answer this one object; bit 3 IID_IMissing gives E_NOINTERFACE and NULL. */
int CounterQuerySink(ICounter* counter);
#endif
"""

SERVER = """#include "SinkShape.h"
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

const IID IID_IUnknown = {0x00000000u, 0x0000u, 0x0000u, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
const IID IID_IBaseEvents = {0x0B7C1001u, 0x0001u, 0x0001u, {1, 2, 3, 4, 5, 6, 8, 1}};
const IID IID_ICounterEvents = {0x0B7C1002u, 0x0002u, 0x0002u, {1, 2, 3, 4, 5, 6, 8, 2}};
const IID IID_ICounter = {0x0B7C1003u, 0x0003u, 0x0003u, {1, 2, 3, 4, 5, 6, 8, 3}};
const IID IID_IMissing = {0x0B7C1004u, 0x0004u, 0x0004u, {1, 2, 3, 4, 5, 6, 8, 4}};

#define S_OK ((HRESULT)0)
#define E_FAIL ((HRESULT)-2147467259)
#define E_NOINTERFACE ((HRESULT)-2147467262)
#define CONNECT_E_NOCONNECTION ((HRESULT)-2147220992)

typedef struct CounterObject {
    ICounter counter;
    ULONG references;
    int32_t value;
    ICounterEvents* sink;
    DWORD cookie;
    ICounterEvents* kept;
} CounterObject;

static int live, created, addRefs, releases, sinkPeak, sinkLast, allocated, freed, keepSinks, failAdvise, stringMode;
static DWORD cookies;

static CounterObject* object(ICounter* This) { return (CounterObject*)(void*)This; }

static HRESULT counterQuery(ICounter* This, REFIID riid, void** out) {
    *out = NULL;
    if (memcmp(riid, &IID_IUnknown, sizeof(IID)) != 0 && memcmp(riid, &IID_ICounter, sizeof(IID)) != 0) {
        return E_NOINTERFACE;
    }
    addRefs++;
    object(This)->references++;
    *out = This;
    return S_OK;
}
static ULONG counterAddRef(ICounter* This) { addRefs++; return ++object(This)->references; }
static ULONG counterRelease(ICounter* This) {
    assert(object(This)->references > 0);
    releases++;
    ULONG remaining = --object(This)->references;
    if (remaining == 0) {
        /* A source destroyed while advised releases its sink. */
        assert(object(This)->sink == NULL && object(This)->kept == NULL);
        live--;
        free(object(This));
    }
    return remaining;
}

static HRESULT counterAdd(ICounter* This, int32_t amount) {
    object(This)->value += amount;
    ICounterEvents* sink = object(This)->sink;
    /* The sink may Unadvise inside the event; the source never touches it afterwards. */
    return sink ? sink->lpVtbl->Changed(sink, object(This)->value) : S_OK;
}
static HRESULT counterReset(ICounter* This) {
    object(This)->value = 0;
    ICounterEvents* sink = object(This)->sink;
    return sink ? sink->lpVtbl->Reset(sink) : S_OK;
}
static HRESULT counterAdvise(ICounter* This, IBaseEvents* base, DWORD* cookie) {
    *cookie = 0;
    if (failAdvise) { failAdvise = 0; return E_FAIL; }
    assert(object(This)->sink == NULL);
    ICounterEvents* sink = NULL;
    /* A connection point asks the sink for its outgoing interface. */
    HRESULT status = base->lpVtbl->QueryInterface(base, &IID_ICounterEvents, (void**)&sink);
    if (status < 0) { return status; }
    int count = (int)sink->lpVtbl->AddRef(sink);
    sink->lpVtbl->Release(sink);
    if (count - 1 > sinkPeak) { sinkPeak = count - 1; }
    object(This)->sink = sink;
    object(This)->cookie = *cookie = ++cookies;
    return S_OK;
}
static HRESULT counterUnadvise(ICounter* This, DWORD cookie) {
    ICounterEvents* sink = object(This)->sink;
    if (sink == NULL || cookie != object(This)->cookie) { return CONNECT_E_NOCONNECTION; }
    object(This)->sink = NULL;
    object(This)->cookie = 0;
    if (keepSinks) { object(This)->kept = sink; return S_OK; }
    sinkLast = (int)sink->lpVtbl->Release(sink);
    return S_OK;
}

static OLECHAR* allocateText(const OLECHAR* text, size_t units, int prefixed) {
    size_t prefix = prefixed ? sizeof(uint32_t) : 0;
    unsigned char* block = malloc(prefix + (units + 1) * sizeof(OLECHAR));
    assert(block != NULL);
    if (prefixed) {
        uint32_t bytes = (uint32_t)(units * sizeof(OLECHAR));
        memcpy(block, &bytes, sizeof bytes);
    }
    memcpy(block + prefix, text, units * sizeof(OLECHAR));
    memset(block + prefix + units * sizeof(OLECHAR), 0, sizeof(OLECHAR));
    allocated++;
    return (OLECHAR*)(void*)(block + prefix);
}

/* "aé𝄞": a, e-acute, then G clef as a surrogate pair. */
static const OLECHAR nameText[] = {0x61, 0xE9, 0xD834, 0xDD1E};
static const OLECHAR nulText[] = {0x61, 0x00, 0x62};
static const OLECHAR pathText[] = {0x66, 0x2F, 0x61, 0xE9, 0xD834, 0xDD1E, 0x2E, 0x74};

static HRESULT counterName(ICounter* This, BSTR* name) {
    (void)This;
    *name = NULL;
    if (stringMode == 1) { return S_OK; }
    if (stringMode == 3) { *name = allocateText(nulText, 3, 1); return S_OK; }
    *name = allocateText(nameText, 4, 1);
    return stringMode == 2 ? E_FAIL : S_OK;
}
static HRESULT counterPath(ICounter* This, LPOLESTR* path) {
    (void)This;
    *path = NULL;
    if (stringMode == 1) { return S_OK; }
    *path = allocateText(pathText, 8, 0);
    return stringMode == 2 ? E_FAIL : S_OK;
}

void SysFreeString(BSTR text) {
    if (text == NULL) { return; }
    freed++;
    free((unsigned char*)(void*)text - sizeof(uint32_t));
}
void CoTaskMemFree(void* block) {
    if (block == NULL) { return; }
    freed++;
    free(block);
}

static const ICounterVtbl counterTable = {
    counterQuery, counterAddRef, counterRelease, counterAdd, counterReset,
    counterAdvise, counterUnadvise, counterName, counterPath,
};

ICounter* CounterCreate(int32_t value) {
    CounterObject* created_object = calloc(1, sizeof *created_object);
    assert(created_object != NULL);
    created_object->counter.lpVtbl = &counterTable;
    created_object->references = 1;
    created_object->value = value;
    live++;
    created++;
    return &created_object->counter;
}

int ServerLive(void) { return live; }
int ServerCreated(void) { return created; }
int ServerAddRefs(void) { return addRefs; }
int ServerReleases(void) { return releases; }
int ServerSinkPeak(void) { return sinkPeak; }
int ServerSinkLast(void) { return sinkLast; }
int ServerStringsAllocated(void) { return allocated; }
int ServerStringsFreed(void) { return freed; }
void ServerKeepSinks(int keep) { keepSinks = keep; }
void ServerFailNextAdvise(void) { failAdvise = 1; }
void ServerStringMode(int mode) { stringMode = mode; }

int CounterFireKept(ICounter* counter) {
    ICounterEvents* kept = object(counter)->kept;
    return kept ? (int)kept->lpVtbl->Changed(kept, 99) : -1;
}
void CounterReleaseKept(ICounter* counter) {
    ICounterEvents* kept = object(counter)->kept;
    object(counter)->kept = NULL;
    if (kept) { kept->lpVtbl->Release(kept); }
}
void CounterDropSink(ICounter* counter) {
    ICounterEvents* sink = object(counter)->sink;
    object(counter)->kept = sink;
    object(counter)->sink = NULL;
    sink->lpVtbl->Release(sink);
}

static void poke(ICounterEvents* sink, int slot) {
    void* out = NULL;
    if (slot == 1) { sink->lpVtbl->AddRef(sink); }
    if (slot == 2) { sink->lpVtbl->QueryInterface(sink, &IID_IUnknown, &out); }
    if (slot == 3) { sink->lpVtbl->Release(sink); }
    if (slot == 4) { sink->lpVtbl->Changed(sink, 1); }
}
void CounterPokeSink(ICounter* counter, int slot) { poke(object(counter)->kept, slot); }

typedef struct Poke { ICounterEvents* sink; int slot; } Poke;
static void* pokeThread(void* argument) {
    Poke* request = argument;
    poke(request->sink, request->slot);
    return NULL;
}
void CounterPokeSinkOnThread(ICounter* counter, int slot) {
    Poke request = {object(counter)->sink, slot};
    pthread_t thread;
    assert(pthread_create(&thread, NULL, pokeThread, &request) == 0);
    pthread_join(thread, NULL);
}

int CounterQuerySink(ICounter* counter) {
    ICounterEvents* sink = object(counter)->sink;
    int answers = 0;
    const IID* known[] = {&IID_IUnknown, &IID_ICounterEvents, &IID_IBaseEvents};
    for (int index = 0; index < 3; index++) {
        void* out = NULL;
        if (sink->lpVtbl->QueryInterface(sink, known[index], &out) == S_OK && out == (void*)sink) {
            answers |= 1 << index;
            sink->lpVtbl->Release(sink);
        }
    }
    void* missing = (void*)sink;
    if (sink->lpVtbl->QueryInterface(sink, &IID_IMissing, &missing) == E_NOINTERFACE && missing == NULL) {
        answers |= 8;
    }
    return answers;
}

/* The proxy's stand-ins for ole32, which Library.COM's runtime calls. */
HRESULT CoInitializeEx(void* reserved, DWORD model) {
    (void)reserved;
    assert(model == 0x2);
    return S_OK;
}
void CoUninitialize(void) {}
"""

SYMBOLS = [
    "IUnknown",
    "IBaseEvents",
    "ICounterEvents",
    "ICounter",
    "IID_IUnknown",
    "IID_IBaseEvents",
    "IID_ICounterEvents",
    "IID_ICounter",
    "CounterCreate",
    "SysFreeString",
    "CoTaskMemFree",
    "ServerLive",
    "ServerCreated",
    "ServerAddRefs",
    "ServerReleases",
    "ServerSinkPeak",
    "ServerSinkLast",
    "ServerStringsAllocated",
    "ServerStringsFreed",
    "ServerKeepSinks",
    "ServerFailNextAdvise",
    "ServerStringMode",
    "CounterFireKept",
    "CounterReleaseKept",
    "CounterDropSink",
    "CounterPokeSink",
    "CounterPokeSinkOnThread",
    "CounterQuerySink",
]

MANIFEST = """manifest-version = 1
[package]
name = "comSinks"

[[native.sources]]
path = "SinkServer.c"
language = "c"
standard = "c11"
modules = ["Counters"]

[[native.bindings]]
module = "Counters"
header = "SinkShape.h"
language = "c"
standard = "c11"
symbols = [SYMBOLS]
owned-results = ["CounterCreate"]
borrowed-parameters = ["CounterFireKept.counter", "CounterReleaseKept.counter", "CounterDropSink.counter", "CounterPokeSink.counter", "CounterPokeSinkOnThread.counter", "CounterQuerySink.counter"]

[native.bindings.resources.IUnknown]
ownership = "com"
iid = "IID_IUnknown"
release-executor = "apartment"

[native.bindings.resources.IBaseEvents]
ownership = "com"
iid = "IID_IBaseEvents"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.ICounterEvents]
ownership = "com"
iid = "IID_ICounterEvents"
base = "IBaseEvents"
release-executor = "apartment"

[native.bindings.resources.ICounter]
ownership = "com"
iid = "IID_ICounter"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.ICounter.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.ICounter.dispatch.methods]
add = "Add"
reset = "Reset"
advise = "Advise"
unadvise = "Unadvise"
name = "Name"
path = "Path"

[native.bindings.status-results]
"ICounter.name" = "hresult"
"ICounter.path" = "hresult"

[native.bindings.copied-outputs."ICounter.name.name"]
encoding = "utf-16"
free = "SysFreeString"

[native.bindings.copied-outputs."ICounter.path.path"]
encoding = "utf-16"
free = "CoTaskMemFree"

[native.bindings.com-sinks.ICounterEvents]
name = "makeCounterEvents"
interface = "ICounterEventsHandler"
register = "ICounter.advise"
unregister = "ICounter.unadvise"
executor = "apartment"
failure = "abort"
activation-failure = "unpublished"
cancellation = "entry-barrier"
""".replace("SYMBOLS", ", ".join(f'"{symbol}"' for symbol in SYMBOLS))

HANDLER = """int destroyed = 0;
int changes = 0;
int lastValue = 0;
int resets = 0;

class Events implements ICounterEventsHandler {
	private CallbackScope scope;
	private bool cancelInside;
	public Events(CallbackScope scope, bool cancelInside) { self.scope = scope; self.cancelInside = cancelInside; }
	public int changed(int value) {
		changes++;
		lastValue = value;
		// Unadvise inside the event: the entry pin keeps the sink alive.
		if (self.cancelInside) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
		return 0;
	}
	public int reset() {
		resets++;
		return 1;
	}
	public void __del__() { destroyed++; }
}
"""

PROGRAM = (
    """import Library.COM.COMApartment;
import Library.Callback;
import ./Counters.btrc;
#include <assert.h>
#include <stdio.h>

"""
    + HANDLER
    + """
void adviseAndUnadvise() {
	var scope = CallbackScope();
	var counter = CounterCreate(1);
	int before = destroyed;
	int seen = changes;
	ICallbackRegistration registration = makeCounterEvents(counter, Events(scope, false), scope);
	// The factory's reference and the source's: the sink count peaks at 2.
	assert(registration.isOpen() && COMApartment.liveSinks() == 1 && ServerSinkPeak() == 2);
	assert(counter.add(4) == 0 && changes == seen + 1 && lastValue == 5);
	// A handler's HRESULT reaches the source.
	assert(counter.reset() == 1 && resets > 0);
	// QueryInterface answers IUnknown, the sink's IID and its base, and nothing else.
	assert(CounterQuerySink(counter) == 15);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	// Unadvise ended the source's reference: the sink count ends at 0.
	assert(!registration.isOpen() && destroyed == before + 1);
	assert(ServerSinkLast() == 0 && COMApartment.liveSinks() == 0);
	assert(counter.add(1) == 0 && changes == seen + 1);
}

void unadviseInsideEvent() {
	var scope = CallbackScope();
	var counter = CounterCreate(10);
	int before = destroyed;
	int seen = changes;
	ICallbackRegistration registration = makeCounterEvents(counter, Events(scope, true), scope);
	assert(counter.add(1) == 0 && changes == seen + 1);
	// Unadvise ran inside the event, while the event pinned the sink.
	assert(ServerSinkLast() == 1 && COMApartment.liveSinks() == 1);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
	assert(COMApartment.liveSinks() == 0 && destroyed == before + 1);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(counter.add(1) == 0 && changes == seen + 1);
}

void sourceKeepsTheSink() {
	var scope = CallbackScope();
	var counter = CounterCreate(0);
	int before = destroyed;
	int seen = changes;
	ServerKeepSinks(1);
	ICallbackRegistration registration = makeCounterEvents(counter, Events(scope, false), scope);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	// The receiver is gone; the kept sink pins only its holder and context.
	assert(destroyed == before + 1 && COMApartment.liveSinks() == 1);
	// After cancellation an event answers S_OK without entering BTRC.
	assert(CounterFireKept(counter) == 0 && changes == seen);
	CounterReleaseKept(counter);
	assert(COMApartment.liveSinks() == 0);
	ServerKeepSinks(0);
}

void adviseFails() {
	var scope = CallbackScope();
	var counter = CounterCreate(0);
	int before = destroyed;
	ServerFailNextAdvise();
	string failure = "";
	try { var registration = makeCounterEvents(counter, Events(scope, false), scope); }
	catch (string error) { failure = error; }
	assert(failure.equals("COM sink ICounterEvents: ICounter.advise failed with HRESULT 0x80004005"));
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(destroyed == before + 1 && COMApartment.liveSinks() == 0);
}

void strings() {
	var counter = CounterCreate(0);
	string? name = counter.name();
	assert(name != null && name.equals("aé𝄞"));
	string? path = counter.path();
	assert(path != null && path.equals("f/aé𝄞.t"));
	ServerStringMode(1);
	assert(counter.name() == null && counter.path() == null);
	// A failing HRESULT frees the string it still wrote, then throws.
	ServerStringMode(2);
	string failure = "";
	try { counter.path(); }
	catch (string error) { failure = error; }
	assert(failure.equals("COM ICounter.path failed with HRESULT 0x80004005"));
	ServerStringMode(3);
	failure = "";
	try { counter.name(); }
	catch (string error) { failure = error; }
	assert(failure.equals("COM ICounter.name returned a string holding U+0000, which a BTRC string cannot hold"));
	ServerStringMode(0);
	for (int index = 0; index < 1000; index++) {
		string? again = counter.name();
		assert(again != null && again.length() == 7);
	}
	assert(ServerStringsFreed() == ServerStringsAllocated() && ServerStringsAllocated() == 1004);
}

int main() {
	COMApartment.initialize();
	for (int cycle = 0; cycle < 100; cycle++) {
		adviseAndUnadvise();
		unadviseInsideEvent();
		sourceKeepsTheSink();
		adviseFails();
	}
	strings();
	assert(COMApartment.liveClaims() == 0 && COMApartment.liveSinks() == 0);
	COMApartment.uninitialize();
	assert(destroyed == 400 && ServerLive() == 0);
	assert(ServerReleases() == ServerCreated() + ServerAddRefs());
	printf("com-sinks-ok %d %d %d\\n", ServerCreated(), ServerAddRefs(), ServerReleases());
	return 0;
}
"""
)


@pytest.fixture
def sink_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").unlink()
    (root / "SinkShape.h").write_text(HEADER, encoding="utf-8")
    (root / "SinkServer.c").write_text(SERVER, encoding="utf-8")
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


def execute(executable):
    return subprocess.run([str(executable)], capture_output=True, text=True, timeout=60, check=False)


@pytest.mark.parametrize("optimization", [0, 2])
@pytest.mark.parametrize("sanitize", [False, True])
def test_com_sinks_count_every_reference(sink_project, native_compile, optimization, sanitize):
    c_source, executable = build(sink_project, native_compile, optimization, sanitize)
    # One static const table per sink, answered by memcmp.
    assert "static const struct ICounterEventsVtbl __btrc_com_sink_ICounterEvents_table" in c_source
    assert "memcmp" in c_source
    completed = execute(executable)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert completed.stdout.startswith("com-sinks-ok "), completed.stdout


ADVISED = (
    "COMApartment.initialize(); var scope = CallbackScope(); var counter = CounterCreate(1);"
    " ICallbackRegistration registration = makeCounterEvents(counter, Events(scope, false), scope);"
)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # A source that drops its sink without Unadvise leaves a dead holder,
        # which aborts AddRef and QueryInterface while its registration lives.
        (
            ADVISED + " CounterDropSink(counter); CounterPokeSink(counter, 1);",
            "ICounterEvents.AddRef: the holder is dead",
        ),
        (
            ADVISED + " CounterDropSink(counter); CounterPokeSink(counter, 2);",
            "ICounterEvents.QueryInterface: the holder is dead",
        ),
        (
            ADVISED + " CounterDropSink(counter); CounterPokeSink(counter, 3);",
            "ICounterEvents.Release: the holder is dead",
        ),
        # Every entry runs on the apartment's thread (rules 3 and 4).
        (ADVISED + " CounterPokeSinkOnThread(counter, 1);", "ICounterEvents.AddRef: called off its apartment thread"),
        (
            ADVISED + " CounterPokeSinkOnThread(counter, 2);",
            "ICounterEvents.QueryInterface: called off its apartment thread",
        ),
        (
            ADVISED + " CounterPokeSinkOnThread(counter, 3);",
            "ICounterEvents.Release: foreign holder released on the wrong thread",
        ),
        (ADVISED + " CounterPokeSinkOnThread(counter, 4);", "ICounterEvents.Changed: called off its apartment thread"),
    ],
)
@pytest.mark.parametrize("optimization", [0, 2])
@pytest.mark.parametrize("sanitize", [False, True])
def test_com_sink_misuse_terminates(sink_project, native_compile, body, expected, optimization, sanitize):
    sink_project.write_text(
        "import Library.COM.COMApartment;\nimport Library.Callback;\nimport ./Counters.btrc;\n#include <assert.h>\n"
        + HANDLER
        + f"int main() {{ {body} return 0; }}\n",
        encoding="utf-8",
    )
    _, executable = build(sink_project, native_compile, optimization, sanitize)
    completed = execute(executable)
    assert completed.returncode < 0, (completed.returncode, completed.stdout, completed.stderr)
    assert expected in completed.stderr, completed.stderr


def test_com_sink_activation_failure_aborts(sink_project, native_compile):
    root = sink_project.parent.parent
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'activation-failure = "unpublished"', 'activation-failure = "abort"'
        ),
        encoding="utf-8",
    )
    sink_project.write_text(
        "import Library.COM.COMApartment;\nimport Library.Callback;\nimport ./Counters.btrc;\n#include <assert.h>\n"
        + HANDLER
        + "int main() { COMApartment.initialize(); var scope = CallbackScope(); var counter = CounterCreate(1);"
        " ServerFailNextAdvise(); var registration = makeCounterEvents(counter, Events(scope, false), scope);"
        " return 0; }\n",
        encoding="utf-8",
    )
    _, executable = build(sink_project, native_compile)
    completed = execute(executable)
    assert completed.returncode < 0, (completed.returncode, completed.stderr)
    assert "COM sink ICounterEvents: ICounter.advise failed with HRESULT 0x80004005" in completed.stderr


def rejected(source, native_compile):
    result = native_compile(source)
    assert not result.successful
    return str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    ("path", "before", "after", "message"),
    [
        # The sink's key names a com resource of the binding.
        ("btrc.toml", "com-sinks.ICounterEvents]", "com-sinks.ICounterSink]", "com-sinks requires a com resource"),
        ("btrc.toml", 'cancellation = "entry-barrier"\n', "", "requires cancellation"),
        (
            "btrc.toml",
            'cancellation = "entry-barrier"',
            'cancellation = "abandon"',
            "cancellation requires entry-barrier",
        ),
        (
            "btrc.toml",
            'executor = "apartment"\nfailure = "abort"\nactivation-failure',
            'executor = "caller"\nfailure = "abort"\nactivation-failure',
            "executor currently requires apartment",
        ),
        (
            "btrc.toml",
            'activation-failure = "unpublished"',
            'activation-failure = "ignore"',
            "activation-failure requires unpublished or abort",
        ),
        (
            "btrc.toml",
            'register = "ICounter.advise"',
            'register = "ICounter.missing"',
            "register and unregister require two methods of one dispatching com resource",
        ),
        (
            "btrc.toml",
            'name = "makeCounterEvents"',
            'name = "CounterCreate"',
            "the factory and interface names must be distinct from selected symbols",
        ),
        # QueryInterface answers each IID once, and always IID_IUnknown.
        (
            "btrc.toml",
            'iid = "IID_IBaseEvents"',
            'iid = "IID_ICounterEvents"',
            "duplicate sink IID IID_ICounterEvents",
        ),
        # Sink methods: after IUnknown, never named like it, each an HRESULT.
        (
            "SinkShape.h",
            "    HRESULT (*Reset)(ICounterEvents* This);",
            "    HRESULT (*release)(ICounterEvents* This);",
            "sink method release collides with IUnknown",
        ),
        (
            "SinkShape.h",
            "    HRESULT (*Reset)(ICounterEvents* This);",
            "    void (*Reset)(ICounterEvents* This);",
            "sink method Reset must return a 32-bit signed HRESULT",
        ),
        (
            "SinkShape.h",
            "    HRESULT (*Reset)(ICounterEvents* This);",
            "    HRESULT (*Reset)(ICounterEvents* This, int32_t** value);",
            "sink method Reset arguments require SDK scalar or POD data-pointer types",
        ),
        # Advise(sink, cookie*) and Unadvise(cookie) on one source.
        (
            "SinkShape.h",
            "HRESULT (*Advise)(ICounter* This, IBaseEvents* sink, DWORD* cookie);",
            "HRESULT (*Advise)(ICounter* This, IBaseEvents* sink, DWORD cookie);",
            "register ICounter.advise must take the sink and a cookie pointer and return an HRESULT",
        ),
        (
            "SinkShape.h",
            "HRESULT (*Advise)(ICounter* This, IBaseEvents* sink, DWORD* cookie);",
            "HRESULT (*Advise)(ICounter* This, ICounter* sink, DWORD* cookie);",
            "register ICounter.advise must take the sink and a cookie pointer and return an HRESULT",
        ),
        (
            "SinkShape.h",
            "HRESULT (*Unadvise)(ICounter* This, DWORD cookie);",
            "HRESULT (*Unadvise)(ICounter* This, int64_t cookie);",
            "unregister ICounter.unadvise must take the register's cookie and return an HRESULT",
        ),
        # Copied strings: a utf-16 [out] slot of a dispatched method, freed by its allocator.
        (
            "btrc.toml",
            'free = "CoTaskMemFree"',
            'free = "free"',
            "copied-outputs free must be SysFreeString or CoTaskMemFree",
        ),
        (
            "btrc.toml",
            'encoding = "utf-16"\nfree = "SysFreeString"',
            'encoding = "utf-8"\nfree = "SysFreeString"',
            "copied-outputs encoding must be utf-16",
        ),
        (
            "btrc.toml",
            '"CoTaskMemFree", ',
            "",
            "copied-outputs free CoTaskMemFree must be a selected function",
        ),
        ("btrc.toml", '"ICounter.path" = "hresult"\n', "", "copied-outputs requires status-results on its method"),
        (
            "btrc.toml",
            'copied-outputs."ICounter.path.path"',
            'copied-outputs."CounterCreate.value"',
            "copied-outputs currently requires a dispatched com method R.method.parameter",
        ),
        (
            "SinkShape.h",
            "HRESULT (*Name)(ICounter* This, BSTR* name);",
            "HRESULT (*Name)(ICounter* This, char** name);",
            "copied-outputs ICounter.name.name requires a mutable UTF-16 string pointer output",
        ),
        (
            "SinkShape.h",
            "void SysFreeString(BSTR text);",
            "int SysFreeString(BSTR text);",
            "copied-outputs free SysFreeString must take the string and return void",
        ),
        (
            "SinkShape.h",
            "void CoTaskMemFree(void* block);",
            "void CoTaskMemFree(const void* block);",
            "copied-outputs free CoTaskMemFree must take the string and return void",
        ),
        # Aggregation is never supported: no COM method or C function takes pUnkOuter.
        (
            "SinkShape.h",
            "HRESULT (*Path)(ICounter* This, LPOLESTR* path);",
            "HRESULT (*Path)(ICounter* This, LPOLESTR* path, IUnknown* pUnkOuter);",
            "dispatch method ICounter.path: COM aggregation is not supported; pUnkOuter must be hidden or null",
        ),
        (
            "SinkShape.h",
            "ICounter* CounterCreate(int32_t value);",
            "ICounter* CounterCreate(int32_t value, IUnknown* pUnkOuter);",
            "CounterCreate: COM aggregation is not supported; pUnkOuter must be hidden or null",
        ),
    ],
)
def test_com_sinks_reject_unchecked_facts(sink_project, native_compile, path, before, after, message):
    target = sink_project.parent.parent / path
    text = target.read_text(encoding="utf-8")
    assert before in text, before
    target.write_text(text.replace(before, after, 1), encoding="utf-8")
    assert message in rejected(sink_project, native_compile)


def test_com_sink_requires_iid_iunknown(sink_project, native_compile):
    # Without an IUnknown resource, a sink still answers IID_IUnknown, which the binding must select.
    manifest = sink_project.parent.parent / "btrc.toml"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace('"IUnknown", ', "").replace('"IID_IUnknown", ', "")
    text = text.replace(
        '[native.bindings.resources.IUnknown]\nownership = "com"\niid = "IID_IUnknown"\nrelease-executor = "apartment"\n\n',
        "",
    )
    text = text.replace('base = "IUnknown"\n', "")
    manifest.write_text(text, encoding="utf-8")
    assert "a com sink answers IID_IUnknown, which the binding must select" in rejected(sink_project, native_compile)
