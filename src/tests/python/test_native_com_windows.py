"""Real COM on Windows through both compilers: interop step 5's Windows exit.

Two programs run against the real COM runtime (native-interop-ownership.md
section 6, step 5). The first reaches a registry-free counter server DLL
through LoadLibrary, GetProcAddress and DllGetClassObject: it creates the
counter, takes an alias, checks QueryInterface identity with sameObject,
calls Clone, copies a BSTR name, Advises a BTRC sink, fires an event,
Unadvises, releases everything, and checks that the server has no live
object, that its releases equal its claims, that the sink's count peaked at 2
and ended at 0, and that the receiver was destroyed once. The second creates
an ole32 stream with CreateStreamOnHGlobal, asks it for ISequentialStream,
widens it to its base, and checks that the last Release returns 0.

Both programs link through their native plans, whose libraries come from
Library.COM's link records (ole32, uuid, oleaut32). zig builds the
executables, and the server, for windows-x64 and windows-arm64 here; with
BTRC_WIN32_EVIDENCE_DIR set they are copied there, and windows.yml's
win32-native job runs them on Windows x64 and ARM64 and checks their output.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import REPO, zig_libc
from tools.native_plan import NativePlanBuilder

TARGETS = {
    "windows-x64": ("x86_64-w64-windows-gnu", "x86_64", "x64"),
    "windows-arm64": ("aarch64-w64-windows-gnu", "aarch64", "arm64"),
}

# The server's and the client's interface declarations, in MinGW-w64's C style.
COUNTER_HEADER = """#ifndef BTRC_COM_COUNTERS_H
#define BTRC_COM_COUNTERS_H
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <unknwn.h>
#include <oleauto.h>

extern const IID IID_ICounter;
extern const IID IID_ICounterEvents;
extern const CLSID CLSID_Counter;

typedef struct ICounterEvents ICounterEvents;
typedef struct ICounterEventsVtbl {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(ICounterEvents *This, REFIID riid, void **ppvObject);
    ULONG (STDMETHODCALLTYPE *AddRef)(ICounterEvents *This);
    ULONG (STDMETHODCALLTYPE *Release)(ICounterEvents *This);
    HRESULT (STDMETHODCALLTYPE *Changed)(ICounterEvents *This, LONG value);
} ICounterEventsVtbl;
struct ICounterEvents { const ICounterEventsVtbl *lpVtbl; };

typedef struct ICounter ICounter;
typedef struct ICounterVtbl {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(ICounter *This, REFIID riid, void **ppvObject);
    ULONG (STDMETHODCALLTYPE *AddRef)(ICounter *This);
    ULONG (STDMETHODCALLTYPE *Release)(ICounter *This);
    LONG (STDMETHODCALLTYPE *Value)(ICounter *This);
    HRESULT (STDMETHODCALLTYPE *Add)(ICounter *This, LONG amount);
    HRESULT (STDMETHODCALLTYPE *Clone)(ICounter *This, ICounter **copy);
    HRESULT (STDMETHODCALLTYPE *Name)(ICounter *This, BSTR *name);
    HRESULT (STDMETHODCALLTYPE *Advise)(ICounter *This, ICounterEvents *sink, DWORD *cookie);
    HRESULT (STDMETHODCALLTYPE *Unadvise)(ICounter *This, DWORD cookie);
} ICounterVtbl;
struct ICounter { const ICounterVtbl *lpVtbl; };

/* The client's loader: LoadLibrary, then DllGetClassObject; no registry. */
HRESULT CounterServerCreate(ICounter **counter);
/* The server's accounting, read through GetProcAddress. */
int CounterServerLive(void);
int CounterServerCreated(void);
int CounterServerAddRefs(void);
int CounterServerReleases(void);
int CounterServerSinkPeak(void);
int CounterServerSinkLast(void);
#endif
"""

GUIDS = """const IID IID_ICounter = {0x6b0c9a51u, 0x3c1eu, 0x4c1fu, {0x9d, 0x2b, 0x41, 0x7a, 0x02, 0x11, 0x5c, 0x01}};
const IID IID_ICounterEvents = {0x6b0c9a52u, 0x3c1eu, 0x4c1fu, {0x9d, 0x2b, 0x41, 0x7a, 0x02, 0x11, 0x5c, 0x02}};
const CLSID CLSID_Counter = {0x6b0c9a53u, 0x3c1eu, 0x4c1fu, {0x9d, 0x2b, 0x41, 0x7a, 0x02, 0x11, 0x5c, 0x03}};
"""

# The registry-free server: one counter class behind DllGetClassObject, with
# one connection point, and the counts the test checks.
COUNTER_SERVER = (
    """/* combaseapi.h declares DllGetClassObject without dllexport; this server
 * defines and exports it, so the header's declaration takes another name. */
#define DllGetClassObject btrcHeaderDllGetClassObject
#include "Counters.h"
#undef DllGetClassObject
#include <stdlib.h>
#include <string.h>

"""
    + GUIDS
    + """
#define CONNECT_E_NOCONNECTION ((HRESULT)0x80040200L)
#define CONNECT_E_ADVISELIMIT ((HRESULT)0x80040201L)

typedef struct CounterObject { ICounter counter; LONG references; LONG value; ICounterEvents *sink; DWORD cookie; } CounterObject;

static LONG live, created, addRefs, releases, sinkPeak = -1, sinkLast = -1;
static DWORD cookies;

static int sameGuid(REFIID left, REFIID right) { return memcmp(left, right, sizeof(GUID)) == 0; }
static CounterObject *object(ICounter *This) { return (CounterObject *)(void *)This; }
static ICounter *newCounter(LONG value);

static HRESULT STDMETHODCALLTYPE counterQuery(ICounter *This, REFIID riid, void **out) {
    if (out == NULL) { return E_POINTER; }
    *out = NULL;
    if (!sameGuid(riid, &IID_IUnknown) && !sameGuid(riid, &IID_ICounter)) { return E_NOINTERFACE; }
    addRefs++;
    object(This)->references++;
    *out = This;
    return S_OK;
}
static ULONG STDMETHODCALLTYPE counterAddRef(ICounter *This) {
    addRefs++;
    return (ULONG)++object(This)->references;
}
static ULONG STDMETHODCALLTYPE counterRelease(ICounter *This) {
    CounterObject *counter = object(This);
    releases++;
    LONG remaining = --counter->references;
    if (remaining == 0) {
        if (counter->sink != NULL) { counter->sink->lpVtbl->Release(counter->sink); }
        live--;
        free(counter);
    }
    return (ULONG)remaining;
}
static LONG STDMETHODCALLTYPE counterValue(ICounter *This) { return object(This)->value; }
static HRESULT STDMETHODCALLTYPE counterAdd(ICounter *This, LONG amount) {
    object(This)->value += amount;
    ICounterEvents *sink = object(This)->sink;
    /* The sink may Unadvise inside the event; the source never touches it afterwards. */
    return sink != NULL ? sink->lpVtbl->Changed(sink, object(This)->value) : S_OK;
}
static HRESULT STDMETHODCALLTYPE counterClone(ICounter *This, ICounter **copy) {
    if (copy == NULL) { return E_POINTER; }
    *copy = newCounter(object(This)->value);
    return *copy != NULL ? S_OK : E_OUTOFMEMORY;
}
static HRESULT STDMETHODCALLTYPE counterName(ICounter *This, BSTR *name) {
    /* "counter " then e-acute and G clef, a surrogate pair. */
    static const OLECHAR text[] = {0x63, 0x6F, 0x75, 0x6E, 0x74, 0x65, 0x72, 0x20, 0xE9, 0xD834, 0xDD1E, 0};
    (void)This;
    if (name == NULL) { return E_POINTER; }
    *name = SysAllocString(text);
    return *name != NULL ? S_OK : E_OUTOFMEMORY;
}
static HRESULT STDMETHODCALLTYPE counterAdvise(ICounter *This, ICounterEvents *sink, DWORD *cookie) {
    if (sink == NULL || cookie == NULL) { return E_POINTER; }
    *cookie = 0;
    if (object(This)->sink != NULL) { return CONNECT_E_ADVISELIMIT; }
    /* AddRef returns the sink's new count: the BTRC factory's reference and this one. */
    LONG count = (LONG)sink->lpVtbl->AddRef(sink);
    if (count > sinkPeak) { sinkPeak = count; }
    object(This)->sink = sink;
    *cookie = object(This)->cookie = ++cookies;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE counterUnadvise(ICounter *This, DWORD cookie) {
    ICounterEvents *sink = object(This)->sink;
    if (sink == NULL || cookie != object(This)->cookie) { return CONNECT_E_NOCONNECTION; }
    object(This)->sink = NULL;
    object(This)->cookie = 0;
    sinkLast = (LONG)sink->lpVtbl->Release(sink);
    return S_OK;
}

static const ICounterVtbl counterTable = {
    counterQuery, counterAddRef, counterRelease, counterValue, counterAdd, counterClone, counterName, counterAdvise, counterUnadvise,
};

static ICounter *newCounter(LONG value) {
    CounterObject *counter = calloc(1, sizeof *counter);
    if (counter == NULL) { return NULL; }
    counter->counter.lpVtbl = &counterTable;
    counter->references = 1;
    counter->value = value;
    live++;
    created++;
    return &counter->counter;
}

/* The class factory: one static object, outside the counts. */
static HRESULT STDMETHODCALLTYPE factoryQuery(IClassFactory *This, REFIID riid, void **out) {
    if (out == NULL) { return E_POINTER; }
    *out = NULL;
    if (!sameGuid(riid, &IID_IUnknown) && !sameGuid(riid, &IID_IClassFactory)) { return E_NOINTERFACE; }
    *out = This;
    return S_OK;
}
static ULONG STDMETHODCALLTYPE factoryAddRef(IClassFactory *This) { (void)This; return 2; }
static ULONG STDMETHODCALLTYPE factoryRelease(IClassFactory *This) { (void)This; return 1; }
static HRESULT STDMETHODCALLTYPE factoryCreate(IClassFactory *This, IUnknown *outer, REFIID riid, void **out) {
    (void)This;
    if (out == NULL) { return E_POINTER; }
    *out = NULL;
    if (outer != NULL) { return CLASS_E_NOAGGREGATION; }
    ICounter *counter = newCounter(0);
    if (counter == NULL) { return E_OUTOFMEMORY; }
    HRESULT status = counter->lpVtbl->QueryInterface(counter, riid, out);
    counter->lpVtbl->Release(counter);
    return status;
}
static HRESULT STDMETHODCALLTYPE factoryLock(IClassFactory *This, BOOL lock) { (void)This; (void)lock; return S_OK; }

static const IClassFactoryVtbl factoryTable = {factoryQuery, factoryAddRef, factoryRelease, factoryCreate, factoryLock};
static IClassFactory factory = {(IClassFactoryVtbl *)&factoryTable};

__declspec(dllexport) HRESULT WINAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID *ppv) {
    if (ppv == NULL) { return E_POINTER; }
    *ppv = NULL;
    if (!sameGuid(rclsid, &CLSID_Counter)) { return CLASS_E_CLASSNOTAVAILABLE; }
    return factoryQuery(&factory, riid, ppv);
}

__declspec(dllexport) int ServerLive(void) { return (int)live; }
__declspec(dllexport) int ServerCreated(void) { return (int)created; }
__declspec(dllexport) int ServerAddRefs(void) { return (int)addRefs; }
__declspec(dllexport) int ServerReleases(void) { return (int)releases; }
__declspec(dllexport) int ServerSinkPeak(void) { return (int)sinkPeak; }
__declspec(dllexport) int ServerSinkLast(void) { return (int)sinkLast; }
"""
)

# The client half the program links: the IIDs and the registry-free loader.
COUNTER_LOADER = (
    """#include "Counters.h"

"""
    + GUIDS
    + """
#if defined(__aarch64__) || defined(_M_ARM64)
#define COUNTER_SERVER "ComCounterServer-arm64.dll"
#else
#define COUNTER_SERVER "ComCounterServer-x64.dll"
#endif

typedef HRESULT(WINAPI *CounterGetClassObject)(REFCLSID, REFIID, LPVOID *);
typedef int (*CounterCount)(void);

static HMODULE server;

/* The server is the DLL beside the executable; nothing reads the registry. */
static FARPROC serverSymbol(const char *name) {
    if (server == NULL) { server = LoadLibraryA(COUNTER_SERVER); }
    return server != NULL ? GetProcAddress(server, name) : NULL;
}

HRESULT CounterServerCreate(ICounter **counter) {
    *counter = NULL;
    CounterGetClassObject get = (CounterGetClassObject)(void (*)(void))serverSymbol("DllGetClassObject");
    if (get == NULL) { return HRESULT_FROM_WIN32(GetLastError()); }
    IClassFactory *factory = NULL;
    HRESULT status = get(&CLSID_Counter, &IID_IClassFactory, (void **)&factory);
    if (FAILED(status)) { return status; }
    status = factory->lpVtbl->CreateInstance(factory, NULL, &IID_ICounter, (void **)counter);
    factory->lpVtbl->Release(factory);
    return status;
}

static int serverCount(const char *name) {
    CounterCount count = (CounterCount)(void (*)(void))serverSymbol(name);
    return count != NULL ? count() : -1000;
}

int CounterServerLive(void) { return serverCount("ServerLive"); }
int CounterServerCreated(void) { return serverCount("ServerCreated"); }
int CounterServerAddRefs(void) { return serverCount("ServerAddRefs"); }
int CounterServerReleases(void) { return serverCount("ServerReleases"); }
int CounterServerSinkPeak(void) { return serverCount("ServerSinkPeak"); }
int CounterServerSinkLast(void) { return serverCount("ServerSinkLast"); }
"""
)

COUNTER_MANIFEST = """manifest-version = 1
[package]
name = "comCounterClient"

[[native.sources]]
path = "CounterLoader.c"
language = "c"
standard = "c11"
modules = ["Counters"]
os = ["windows"]

[[native.bindings]]
module = "Counters"
header = "Counters.h"
language = "c"
standard = "c11"
os = ["windows"]
symbols = ["IUnknown", "ICounter", "ICounterEvents", "IID_IUnknown", "IID_ICounter", "IID_ICounterEvents", "SysFreeString", "CounterServerCreate", "CounterServerLive", "CounterServerCreated", "CounterServerAddRefs", "CounterServerReleases", "CounterServerSinkPeak", "CounterServerSinkLast"]

[native.bindings.resources.IUnknown]
ownership = "com"
iid = "IID_IUnknown"
release-executor = "apartment"

[native.bindings.resources.ICounterEvents]
ownership = "com"
iid = "IID_ICounterEvents"
base = "IUnknown"
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
value = "Value"
add = "Add"
clone = "Clone"
name = "Name"
advise = "Advise"
unadvise = "Unadvise"

[native.bindings.status-results]
"ICounter.clone" = "hresult"
"ICounter.name" = "hresult"

[native.bindings.copied-outputs."ICounter.name.name"]
encoding = "utf-16"
free = "SysFreeString"

[native.bindings.owned-outputs."CounterServerCreate.counter"]
result = "CounterCreation"
status = "hresult"

[native.bindings.com-sinks.ICounterEvents]
name = "makeCounterEvents"
interface = "ICounterEventsHandler"
register = "ICounter.advise"
unregister = "ICounter.unadvise"
executor = "apartment"
failure = "abort"
activation-failure = "unpublished"
cancellation = "entry-barrier"
"""

COUNTER_PROGRAM = """import Library.COM.COMApartment;
import Library.Callback;
import ./Counters.btrc;
#include <stdio.h>

int destroyed = 0;
int changes = 0;
long lastValue = 0;

class Events implements ICounterEventsHandler {
	public long changed(long value) {
		changes++;
		lastValue = value;
		return 0;
	}
	public void __del__() { destroyed++; }
}

int roundTrip() {
	var created = CounterServerCreate();
	ICounter? counter = created.value;
	if (created.status < 0 || counter == null) { return 1; }
	// An alias takes its own claim; QueryInterface answers the same object.
	var alias = counter;
	IUnknown? unknown = counter;
	ICounter? queried = (ICounter?)unknown;
	bool same = queried != null && queried == counter && IUnknown.sameObject(alias, unknown);
	ICounter? copy = counter.clone();
	bool cloned = copy != null && copy.value() == counter.value() && !IUnknown.sameObject(copy, counter);
	string? name = counter.name();
	bool named = name != null && name.equals("counter é𝄞");
	var scope = CallbackScope();
	ICallbackRegistration registration = makeCounterEvents(counter, Events(), scope);
	bool fired = counter.add(5) == 0 && changes == 1 && lastValue == 5;
	bool cancelled = scope.cancel() == CALLBACK_CANCELLATION_COMPLETE && !registration.isOpen();
	bool quiet = counter.add(1) == 0 && changes == 1;
	printf("com-sinks same=%d cloned=%d named=%d fired=%d cancelled=%d quiet=%d\\n", (int)same, (int)cloned, (int)named, (int)fired, (int)cancelled, (int)quiet);
	return same && cloned && named && fired && cancelled && quiet ? 0 : 2;
}

int main() {
	COMApartment.initialize();
	int result = roundTrip();
	long long claims = COMApartment.liveClaims();
	long long sinks = COMApartment.liveSinks();
	COMApartment.uninitialize();
	bool balanced = CounterServerReleases() == CounterServerCreated() + CounterServerAddRefs();
	printf("com-server live=%d balanced=%d peak=%d last=%d destroyed=%d claims=%lld sinks=%lld\\n", CounterServerLive(), (int)balanced, CounterServerSinkPeak(), CounterServerSinkLast(), destroyed, claims, sinks);
	return result == 0 && CounterServerLive() == 0 && balanced && CounterServerSinkPeak() == 2 && CounterServerSinkLast() == 0 && destroyed == 1 && claims == 0 && sinks == 0 ? 0 : 3;
}
"""

STREAM_HEADER = """#ifndef BTRC_COM_STREAMS_H
#define BTRC_COM_STREAMS_H
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objidl.h>

/* An outside reference to a stream: its Release is then the last one. */
void StreamWatch(IStream *stream);
ULONG StreamReleaseWatched(void);
#endif
"""

STREAM_WATCH = """#include "Streams.h"

static IStream *watched;

void StreamWatch(IStream *stream) {
    stream->lpVtbl->AddRef(stream);
    watched = stream;
}

ULONG StreamReleaseWatched(void) {
    IStream *stream = watched;
    watched = NULL;
    return stream != NULL ? stream->lpVtbl->Release(stream) : 0xFFFFFFFFu;
}
"""

STREAM_MANIFEST = """manifest-version = 1
[package]
name = "comStreams"

[[native.sources]]
path = "StreamWatch.c"
language = "c"
standard = "c11"
modules = ["Streams"]
os = ["windows"]

[[native.bindings]]
module = "Streams"
header = "Streams.h"
language = "c"
standard = "c11"
os = ["windows"]
symbols = ["IUnknown", "ISequentialStream", "IStream", "IID_IUnknown", "IID_ISequentialStream", "IID_IStream", "CreateStreamOnHGlobal", "StreamWatch", "StreamReleaseWatched"]
borrowed-parameters = ["StreamWatch.stream"]

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
	StreamWatch(stream);
	unsigned char bytes[4] = {1, 2, 3, 4};
	ULONG written = 0;
	// QueryInterface for ISequentialStream through IUnknown, then the static base widening.
	IUnknown? unknown = stream;
	ISequentialStream? asked = (ISequentialStream?)unknown;
	ISequentialStream? sequential = stream;
	HRESULT status = sequential.write(bytes, 4, &written);
	IStream? copy = stream.clone();
	IStream? queried = (IStream?)asked;
	bool same = asked != null && queried != null && IUnknown.sameObject(asked, stream) && IUnknown.sameObject(queried, stream) && !IUnknown.sameObject(copy, stream);
	printf("com-stream status=%d written=%u same=%d\\n", (int)status, (unsigned int)written, (int)same);
	return status == 0 && written == 4 && same ? 0 : 2;
}

int main() {
	COMApartment.initialize();
	int result = roundTrip();
	long long claims = COMApartment.liveClaims();
	// BTRC released every claim, so the watcher's Release is the last one.
	ULONG last = StreamReleaseWatched();
	COMApartment.uninitialize();
	printf("com-stream-release claims=%lld last=%u\\n", claims, (unsigned int)last);
	return result == 0 && claims == 0 && last == 0 ? 0 : 3;
}
"""

# What windows.yml's win32-native job checks each executable prints.
EXPECTED = {
    "com-sinks": "com-sinks same=1 cloned=1 named=1 fired=1 cancelled=1 quiet=1\n"
    "com-server live=0 balanced=1 peak=2 last=0 destroyed=1 claims=0 sinks=0",
    "com-stream": "com-stream status=0 written=4 same=1\ncom-stream-release claims=0 last=0",
}


def write_project(root, header_name, header, sources, manifest, module, program):
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    (root / header_name).write_text(header, encoding="utf-8")
    for name, text in sources.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / f"src/{module}.btrc").write_text("// The COM binding's module.\n", encoding="utf-8")
    source = root / "src/Main.btrc"
    source.write_text(program, encoding="utf-8")
    return source


@pytest.fixture
def counter_project(tmp_path):
    return write_project(
        tmp_path / "counter",
        "Counters.h",
        COUNTER_HEADER,
        {"CounterLoader.c": COUNTER_LOADER},
        COUNTER_MANIFEST,
        "Counters",
        COUNTER_PROGRAM,
    )


@pytest.fixture
def stream_project(tmp_path):
    return write_project(
        tmp_path / "stream",
        "Streams.h",
        STREAM_HEADER,
        {"StreamWatch.c": STREAM_WATCH},
        STREAM_MANIFEST,
        "Streams",
        STREAM_PROGRAM,
    )


def build_program(frontend, source, target, request, monkeypatch, output):
    """Compile with one compiler for one Windows row and link through the emitted plan."""
    monkeypatch.setenv("BTRC_NATIVE_TARGET", TARGETS[target][0])
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(zig_libc()))
    root = source.parent.parent
    plan = root / "Program.link.json"
    generated = root / "Program.c"
    if frontend == "reference":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"),
            str(source),
            CompilerOptions(include_stdlib=False, use_cache=False, target=target),
        )
        assert result.successful, (result.failure, result.diagnostics)
        generated.write_text(result.c_source, encoding="utf-8")
        plan.write_text(result.native_plan.canonical_json(), encoding="utf-8")
    else:
        completed = subprocess.run(
            [
                str(request.getfixturevalue("immutable_btrcc")),
                "--no-stdlib",
                "--no-cache",
                "--target",
                target,
                "--emit-link-plan",
                str(plan),
                str(source),
            ],
            env={**os.environ, "BTRC_HOME": str(REPO / "src")},
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        generated.write_text(completed.stdout, encoding="utf-8")
    # Library.COM's link records name the system libraries, not the test.
    libraries = [record["name"] for record in json.loads(plan.read_text(encoding="utf-8"))["libraries"]]
    assert libraries == ["ole32", "oleaut32", "uuid"]
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=output, optimization=2)
    assert output.read_bytes()[:2] == b"MZ"
    return output


def publish(paths, expected=None):
    """Copy the executables (and the server) to the evidence directory; run them on Windows."""
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        for path in paths:
            shutil.copy2(path, Path(evidence) / path.name)
    if sys.platform == "win32" and expected is not None:
        ran = subprocess.run([str(paths[0])], capture_output=True, text=True, timeout=60, check=False)
        assert ran.returncode == 0 and ran.stdout.replace("\r", "").strip() == expected, (
            ran.returncode,
            ran.stdout,
            ran.stderr,
        )


def build_server(target, directory):
    """The counter server DLL, built with zig for the target's architecture."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("requires zig, which the dev shell provides")
    server = directory / f"ComCounterServer-{TARGETS[target][2]}.dll"
    if server.is_file():
        return server
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Counters.h").write_text(COUNTER_HEADER, encoding="utf-8")
    (directory / "CounterServer.c").write_text(COUNTER_SERVER, encoding="utf-8")
    built = subprocess.run(
        [
            zig,
            "cc",
            "-target",
            f"{TARGETS[target][1]}-windows-gnu",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-shared",
            "-I",
            str(directory),
            str(directory / "CounterServer.c"),
            "-o",
            str(server),
            "-loleaut32",
            "-luuid",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    assert server.read_bytes()[:2] == b"MZ"
    return server


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_com_server_sink_round_trip(counter_project, frontend, target, request, monkeypatch, tmp_path):
    server = build_server(target, tmp_path / "server")
    executable = build_program(
        frontend, counter_project, target, request, monkeypatch, tmp_path / f"com-sinks-{frontend}-{target}.exe"
    )
    shutil.copy2(server, executable.parent / server.name)
    publish([executable, server], EXPECTED["com-sinks"])


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_com_stream_last_release(stream_project, frontend, target, request, monkeypatch, tmp_path):
    executable = build_program(
        frontend, stream_project, target, request, monkeypatch, tmp_path / f"com-stream-{frontend}-{target}.exe"
    )
    publish([executable], EXPECTED["com-stream"])
