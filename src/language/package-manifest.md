# Package manifests and native link plans

This document defines package manifest version 1, lockfile schema 3, and native
link-plan schema 5 (readers keep schemas 1, 2 and 4 for host-native plans). The
reference and self-hosted compilers implement the same
strict local graph, lock, and plan contracts. The reference compiler also
materializes Git dependencies; the self-hosted compiler currently rejects that
acquisition surface precisely. A build tool consumes the emitted plan; compilers never execute
compiler flags or shell fragments from a manifest.

## Manifest version 1

`btrc.toml` opts into this contract with the integer root field
`manifest-version = 1`.  Versioned manifests are strict: unknown fields,
unknown tables, duplicate package identities, ambiguous dependency sources,
and values of the wrong TOML type are errors.

Every version-1 manifest has exactly one package identity:

```toml
manifest-version = 1

[package]
name = "example"
```

Names and dependency aliases use ASCII identifiers (`[A-Za-z_][A-Za-z0-9_]*`).
A resolved graph may contain only one source for a package name.  Depending on
two different sources with the same package identity is an error.

### Public modules

An optional `package.exports` array defines a package's public source modules:

```toml
[package]
name = "widgets"
exports = ["GUI", "IView", "IButton"]
```

Names resolve to `src/<module>.btrc`, falling back to `<module>.btrc` at the
package root; dotted names select subdirectories. Entries must exist, remain
inside the package after symlink resolution, and be distinct valid module names.
An empty array makes every module private. Omitting `exports` preserves the
existing unrestricted import behavior; it does **not** establish encapsulation.

Code inside the same package can import its private implementations. Imports
from outside can reach only exported files, regardless of dependency alias,
relative/absolute spelling, directory glob, symlink, or BTRC `#include`. Checks
run on every edge before import de-duplication: importing a public factory does
not grant access to a private file that factory already loaded. Canonical paths
and the nearest manifest define ownership, including nested packages and loose
consumers without a manifest. Export-policy caches live for one resolution only.

Exports control source-module access and named references through transitive
imports. Importing a public module does not authorize calling a private helper,
constructing a private class, or reading/writing its static fields. Code inside
the owning package can still use those names. Exported dependencies reached
through private modules retain normal transitive visibility.

Public factories must return portable public types; listing a module does not
inspect its API for leaked platform types. Handwritten C and deliberate unsafe
access are not sandboxed.

### Target-selected source providers

An ordinary BTRC module can declare one implementation dependency per target:

```toml
[[package.providers]]
module = "GUI"
implementation = "MacOS.Provider"
os = ["macos"]
arch = ["aarch64", "x86_64"]
```

Both names resolve to existing package modules using the same path and symlink
checks as exports. The resolver adds the selected implementation as a normal
import of `GUI` before composing its source. `GUI` contains ordinary BTRC code
using that implementation; no runtime provider registry, virtual source file,
generated import text or caller-side OS branch is introduced. This also applies
when `GUI` is the compilation entrypoint. The compiler's normalized target—not
the build host—selects the dependency.

`os`, `arch` and `env` use the closed target sets below; omitted or empty
selectors match all values. Declarations for the same canonical module must be
disjoint: no row of `targets.toml` may satisfy two of them, even when that row
is not the current target. Self-selection, missing modules, escaping
paths and unknown fields are errors. Importing a configured module without a
matching provider is an error, not a fallback to another OS. Only selected
implementation source is parsed; inactive files must exist but may be unfinished.

Provider imports obey ordinary strict visibility and package privacy. Export the
public module, not its implementation; loading it does not authorize consumers
to import a private implementation directly. Provider selection is scoped to
one resolution and indexed by canonical module identity. The existing manifest
hash locks these declarations; selected implementations enter the ordinary
source dependency graph. They do not create native link-plan records.

Dependencies are local to their declaring package.  An import beginning with
an alias is resolved against the manifest owning the importing source, not the
root application's aliases.  Dependencies use one of these forms:

```toml
[dependencies]
local = { path = "../local" }
remote = { git = "https://example.invalid/remote.git", rev = "<ref>" }
```

`path` and `git` are mutually exclusive.  A Git dependency may specify at most
one of `rev`, `tag`, and `branch`; an omitted ref means `HEAD`.  Paths are
relative to the declaring manifest.  Every dependency directory must contain
a version-1 `btrc.toml` whose package name matches the resolved graph identity.

The native tables contain data, never arbitrary `cflags`, `ldflags`, commands,
or shell text.  Each entry may have `os`, `arch` and `env` string arrays.  An
omitted or empty array matches every value.  The accepted values are the
operating systems, architectures and environments of the rows in
`src/language/targets.toml`: today `android`, `ios`, `linux`, `macos` and
`windows`; `aarch64` and `x86_64`; and `""`, `gnu`, `msvc` and `simulator`.
`env = [""]` selects the empty environment, so `os = ["ios"], env = [""]`
selects the iOS device row alone and `env = ["simulator"]` the simulator row.

A module that lives under a platform directory (`MacOS`, `IOS`, `Linux`,
`Android` or `Windows`, matched case-insensitively against the operating
systems above) selects exactly that platform. Provider implementations, the
`modules` of native tables and the `module` of a native binding are checked:
`implementation = "Android.Provider"` requires `os = ["android"]`, and an
omitted `os` is an error, as is any other value.

```toml
[[native.sources]]
path = "native/example.cpp"
language = "c++"
standard = "c++17"
modules = ["AudioDevice"]
os = ["linux", "macos", "windows"]
arch = ["x86_64", "aarch64"]

[[native.headers]]
path = "native/example.h"

[[native.include-directories]]
path = "native"

[[native.defines]]
name = "EXAMPLE_ABI"
value = "1"

[[native.frameworks]]
name = "Cocoa"
os = ["macos"]

[[native.pkg-config]]
name = "dbus-1"
os = ["linux"]

[[native.libraries]]
name = "ole32"
os = ["windows"]
```

Every native declaration may have a non-empty `modules` array of dotted module
names relative to its declaring package. `AudioDevice` resolves as
`src/AudioDevice.btrc` and `GUI.IWindow` as `src/GUI/IWindow.btrc`, with the
package root as the fallback module directory. Missing, malformed, duplicate,
or escaping module names are errors. A scoped declaration is emitted when any
named module is loaded. An entry without `modules` is package-wide and is
emitted when any module from that package is loaded; `modules = []` is invalid.

Source languages and standards are closed sets:

- `c`: `c11`
- `c++`: `c++17`, `c++20`
- `objective-c`: `c11`
- `objective-c++`: `c++17`, `c++20`

Declared sources and headers must be regular files inside their package root.
Declared include directories must be directories inside that root.  Symlinks
that escape the root are rejected.  Define names are C identifiers.  Framework,
pkg-config and library names use only letters, digits, `_`, `.`, `+`, and `-`.

`native.libraries` names a system library the executable links, as
`-l<name>` after the objects: `Library.COM` declares `ole32`, `uuid` and
`oleaut32` for Windows. A plan carries its selected libraries in a
`libraries` array of `{name, package}` records, present exactly when one is
selected, so plans without libraries are unchanged; each name links once.

Selected `native.pkg-config` dependencies supply `--cflags` to typed header
imports as well as the native build plan. The shared header reader invokes
`pkg-config` without a shell, preserving quoted include paths and definitions;
missing dependencies fail before emitting C. Link flags remain build-plan-owned.
The environment must resolve metadata for the explicitly selected target, not an
unrelated host installation. Nix pins the dependency; do not copy store paths into
headers. Target and module selection apply before dependency resolution.

## Experimental native header imports

`native.bindings` describes a typed header request owned by one existing BTRC
module. Both frontends validate, select and experimentally consume C requests.
Unloaded modules and inactive targets do not
activate their bindings. Existing `native.headers` and `#include` retain their
untyped behavior.

### Call-scoped native callbacks

An explicit callback mapping projects a native function-pointer/context pair
into an ordinary BTRC interface parameter. The header remains the signature
authority; the manifest supplies only the context relationship, lifetime,
failure policy and imported interface name:

```toml
[[native.bindings]]
module = "Visits"
header = "Visits.h"
language = "c"
standard = "c11"
symbols = ["VisitNow"]

[native.bindings.callbacks."VisitNow.callback"]
context = "context"
context-index = 1
interface = "IVisitor"
lifetime = "call"
failure = "abort"
executor = "caller"
```

For `int VisitNow(int value, int (*callback)(int, void*), void* context)`, this
imports `IVisitor` with `int invoke(int argument0)` and exposes
`VisitNow(int value, IVisitor callback)`. `context` names the enclosing native
function's parameter; `context-index` is the zero-based context slot in the
callback prototype, whose parameter names are not part of a C function type.

```btrc
class Visitor implements IVisitor {
	public int invoke(int value) { return value * 2; }
}
var result = VisitNow(21, Visitor());
```

Generated strict-C11 adapters retain the ordinary managed receiver across the
whole native call, pass a stack-scoped typed context, dispatch synchronously,
and release the receiver afterward. Nested/reentrant calls use independent call frames.
The stack context records caller-thread identity using the existing thread-local
runtime state; a wrong-thread delivery terminates before entering the receiver.
Receiver leases and owned native results use BTRC's normal exception-cleanup
slots, including when a receiver destructor throws after the native call.
No userdata, manual retain, trampoline, or second owner is exposed to provider
code. An indirect function value uses the same checked adapter.

`call` asserts that native code neither retains the context nor delivers a
callback after the enclosing call returns. This is a trusted foreign lifetime
fact, not a claim that arbitrary C behavior can be statically verified. Context
slots must be distinct, unshared `void*` parameters. C callback arguments/results
currently support scalar values (and void results); pointer/managed payloads
require borrow/ownership mappings and are rejected. The same interface
name may be reused by mappings with identical native result/payload types,
including across binding modules and different context positions. Context slots
are omitted from interface identity; public arguments are numbered consecutively.
Conflicting signatures or names colliding with other imported declarations fail
compilation. SDK signature changes are checked when compiling.

`abort` is currently the only supported failure policy: a BTRC exception runs
its local cleanup and terminates at the callback boundary, without unwinding
through native frames. `caller` is the only supported executor. This adapter is
not realtime-safe. Stored C registrations use the mapping in "Stored C
registrations" below; broader executor ownership/destruction and direct
capturing-lambda conversion remain unfinished. One-shot requests and
Objective-C delegates use the mappings below. Use table form as above for
both compilers; self-hosted inline-table parsing remains limited.

`Library.Callback` provides the shared cancellation owner for stored
bindings: `CallbackScope.create(context)` creates and owns a `CallbackState`
before native publication. There is no operation to adopt another scope's state.
Scope cancellation closes new registration admission, visits all registrations
even when an unregister operation throws, retains unfinished states, and prunes
completed states. `cancel()` and `pollCompletion()` use the existing nonblocking
state transitions; they do not wait for active callbacks or implicitly retry a
failed unregister. Scope operations and destruction belong to its creating
thread. The application must retain an independent cancellation owner and drive
pending completion before shutdown; premature destruction is diagnosed, not
treated as a successful drain. The generated stored-block path below uses this
owner; a captured receiver must not be its only lifecycle authority.

Objective-C method block parameters use the same callback declaration and
ordinary interface. Omit `context` and `context-index`: the compiler generates
the internal C thunk/context pair and a typed block in the separate native
adapter. Never supply native context plumbing in BTRC provider code.

```toml
[[native.bindings]]
module = "Process"
header = "Foundation/NSProcessInfo.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NSProcessInfo processInfo]", "-[NSProcessInfo performActivityWithOptions:reason:usingBlock:]"]

[native.bindings.callbacks."-[NSProcessInfo performActivityWithOptions:reason:usingBlock:].block"]
interface = "IActivity"
lifetime = "call"
failure = "abort"
executor = "caller"

[[native.frameworks]]
name = "Foundation"
os = ["macos"]
```

This imports `IActivity` with `void invoke()`. An ordinary class implements it
and is passed to `process.performActivityWithOptions(options, reason, activity)`.
The key uses the full SDK selector and the SDK parameter name, not the generated
BTRC method name. SDK scalar aliases and enums keep their native spelling inside
the block while the shared C ABI and interface use their underlying scalar types.
Block receivers are required even when the SDK permits a null block. Object
arguments use the same managed native type and nullability projection as outbound
Objective-C methods. The generated callback holds each object through synchronous
dispatch using ordinary ARC cleanup, including when the receiver releases the
object's original owner reentrantly. Identity and aliasing are preserved; assigning
an argument to a managed field retains it normally beyond the callback. Required
object arguments are checked before dispatch; nullable arguments admit nil.

For example, Foundation's `sortUsingComparator:` block becomes an interface with
`long invoke(id left, id right)`: the SDK supplies its nonnull object parameters
and scalar comparison result. No additional payload-lifetime manifest or provider
retain/release code is needed. This does not authorize retaining raw call-scoped
buffers or mutating invalidatable interior storage.

Both compilers reject raw-pointer payloads, object-valued results without an
ownership mapping, protocol/generic/class-object payloads, unsupported qualifiers,
conflicting interfaces and unsupported lifetimes. The same
receiver lease, caller-thread guard and terminal failure boundary apply to C and
Objective-C callbacks; this does not support storing or copying a block beyond
the call. The binding author must establish synchronous lifetime from the API's
documented contract; absence of `noescape` is not proof of either lifetime.

### Stored C registrations

A C SDK may keep a callback and its context until a matching unregister call
returns: a Win32 window subclass (`SetWindowSubclass`/`RemoveWindowSubclass`),
an Android looper file descriptor. Declare the context words, the unregister
function and the integer statuses that mean success:

```toml
[native.bindings.callbacks."SetWindowSubclass.pfnSubclass"]
interface = "IWindowSubclass"
context = ["uIdSubclass", "dwRefData"]
context-index = [4, 5]
lifetime = "stored"
executor = "caller"
failure = "abort"
registration-status = "nonzero"
activation-failure = "unpublished"
unregister = "RemoveWindowSubclass"
unregister-status = "nonzero"
captured-handles = ["hWnd"]
cancellation = "entry-barrier"
```

Import `Library.Callback`. The call becomes
`ICallbackRegistration SetWindowSubclass(HWND hWnd, IWindowSubclass pfnSubclass,
CallbackScope scope)`: the context words disappear, the receiver implements
`LRESULT invoke(HWND argument0, UINT argument1, WPARAM argument2, LPARAM
argument3)`, and the registration is the same managed `CallbackContext` that
stored Objective-C blocks return.

- **Context words.** Every named registration parameter and callback position
  carries the registration's context: an unqualified `void*` or an unqualified,
  non-enum integer exactly as wide as a pointer on the selected target
  (`uintptr_t`, `DWORD_PTR`, `LONG_PTR`). Different typedefs of the same integer
  are allowed. Because the compiler chooses the context, each live
  registration is distinct to the SDK, so a Win32 subclass id can never collide
  and silently replace another registration's data.
- **Unregister.** Each unregister parameter repeats the registration parameter
  of the same name and type: the callback parameter receives the same
  generated function, a context word the same context, and every other
  parameter the value the registration captured. Captured parameters must be
  listed in `captured-handles` and be scalars or opaque handles.
- **Statuses.** `registration-status` and `unregister-status` take `nonzero`
  (Win32 `BOOL`), `positive`, `nonnegative` or `zero` (`OSStatus`) and are
  required exactly when the function returns an integer. A failed registration
  follows `activation-failure`: `unpublished` releases everything and throws,
  `abort` terminates. A failed unregister reports a retryable cancellation
  failure and keeps the registration.
- **Payloads.** Callback arguments are scalars, enums or opaque handles: a
  pointer to an SDK record reached only through pointers, such as `HWND`,
  borrowed for the call. Data pointers and unique resources are still rejected.

Deliveries are admitted only on the creating thread, run under the shared
callback gate and abort at the boundary on an exception. `scope.cancel()`
closes admission, calls the unregister function, drains admitted calls and
then releases the receiver; a cancel from inside a delivery stays pending
until that delivery returns. The SDK's claim on the context is released only
after the drain. `cancellation = "self-removal"` (Android's looper, where a
callback unregisters itself by its result) is not implemented yet.

### Stored Objective-C blocks (foundation in progress)

The supported shape is a class factory with one escaping block returning
void, a scalar, an enum or a managed Objective-C object. It returns a native object with a selected, non-consuming, zero-argument
instance method that unregisters the callback. For example, Foundation timers:

```toml
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = ["+[NSTimer scheduledTimerWithTimeInterval:repeats:block:]", "-[NSTimer invalidate]"]

[native.bindings.callbacks."+[NSTimer scheduledTimerWithTimeInterval:repeats:block:].block"]
interface = "ITimerCallback"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSTimer invalidate]"
activation-failure = "abort"
cancellation = "entry-barrier"

[[native.frameworks]]
name = "Foundation"
os = ["macos"]
```

`Foundation.h` includes the public Foundation header. The block projects to
`ITimerCallback.invoke(NSTimer argument0)`. Import `Library.Callback`; the factory
appends a `CallbackScope` argument and returns a managed registration, not the raw
native token:

```btrc
ICallbackRegistration subscription = NSTimer.scheduledTimerWithTimeInterval(0.1, true, receiver, scope);
```

An instance registration may instead return a token removed through its original
source: `source.register(receiver, scope)` paired with `source.remove(token)`.
Select the one-argument, non-consuming, void unregister method on the same native
receiver. Its argument must accept the returned token type or unqualified `id`.
The compiler retains source and token in ordinary
`CallbackToken<TSource, TValue>` fields inside the same `CallbackContext`; it
allocates that pair before native publication. Consumers still receive only an
`ICallbackRegistration`, and may release their source reference immediately.
A protocol-qualified opaque result such as Foundation's `id<NSObject>` may be
stored as managed `id` only when unregister accepts unqualified `id`. This does
not expose protocol methods or erase qualifications on general native calls.
A class registration may instead pair with a class unregister method accepting
its token, as with `NSEvent.addLocalMonitorForEventsMatchingMask` and
`NSEvent.removeMonitor`. The context owns only the token; there is no instance
source or fabricated receiver pair.

The existing generic `CallbackContext<ITimerCallback, NSTimer>` holds receiver and
token in normal managed fields. A generated ARC-captured Objective-C holder owns
an ordinary external BTRC ARC claim. No provider context pointer, retain/release
code, handwritten trampoline or separate root registry is needed. Native object
payloads use the same managed leases as call-scoped blocks.
Scalar/enum queries return their answer synchronously after admitted-call cleanup,
including when the receiver cancels its own scope. A query delivered after
cancellation terminates through `failure = "abort"`: the compiler cannot invent
a valid default answer for the native caller. Void notifications may be ignored
after cancellation. Managed Objective-C results use the existing return-ownership
lowering: the BTRC callback transfers an owned result claim to the generated ARC
block, which returns according to the SDK block signature. Nullability is
preserved. This permits returning the same event or nullable consumption from a
native event monitor without raw pointers or manual retain/release code. Other
callback forms still reject object results without their own checked mapping.
These return rules also apply to source/token registrations.
The analyzers authenticate these runtime declarations through compiler-owned
stdlib provenance; application classes with matching names cannot replace them.

The activation-failure policy and cancellation guarantee are mandatory, not inferred:

- `activation-failure = "abort"`: nil or a native exception terminates with a
  diagnostic before BTRC context cleanup. Publication is indeterminate; neither
  unregister nor a speculative release of the callback receiver is attempted.
  This also applies when inline delivery requested cancellation before failure.
- `activation-failure = "unpublished"`: a nil result or native exception leaves no retained callback or
  future delivery. Inline callbacks before such a failure are allowed, but must
  have returned before the factory does. This stronger native guarantee permits
  cleanup and a recoverable BTRC exception; it must be established by the binding
  author, not guessed from a successful SDK test.
- `cancellation = "entry-barrier"`: unregister is nonblocking and, on return, prevents new callback
  entry. Already admitted calls must return before completion. Unregister returns
  void; an Objective-C exception terminates at the native boundary, without a
  speculative retry or a claim that cancellation succeeded.

The compiler roots and activates context before calling the factory, publishes
the cancellation token before resolving inline cancellation, and reserves the
unregister method for generated lifecycle code across bindings. A `noescape`
parameter, incompatible token/cancellation signature, missing facts or
unsupported executor fails compilation. Callback exceptions and
wrong-thread native delivery terminate before unwinding a foreign frame.

The independent application/component owner must cancel its scope and observe
completion before shutdown, including when receivers retain their scope. Polling
does not block; self-cancellation remains pending until dispatch returns. This
path passes real copied-block and Foundation run-loop tests in both compilers,
including sanitizers. It does **not** yet qualify automatic application shutdown,
abandoned foreign ownership cycles or GUI migration. One-shot bindings follow below.

#### Main-thread blocks

A stored block that the SDK calls on the main thread, such as an observer
registered with `NSOperationQueue.mainQueue` for the interruption notifications
`AVAudioSession` posts from a thread of its own, binds `executor = "main"`
(rules 3 and 4 in
[native-interop-ownership.md](../../docs/design/native-interop-ownership.md)):

```toml
[native.bindings.callbacks."-[NSNotificationCenter addObserverForName:object:queue:usingBlock:].block"]
interface = "IInterruptionObserver"
lifetime = "stored"
failure = "abort"
executor = "main"
unregister = "-[NSNotificationCenter removeObserver:]"
activation-failure = "abort"
cancellation = "entry-barrier"
```

```btrc
ICallbackRegistration observation = NSNotificationCenter.defaultCenter().addObserverForName(AVAudioSessionInterruptionNotification, AVAudioSession.sharedInstance(), NSOperationQueue.mainQueue(), Interruption(scope), scope);
```

- The registration must run on the main thread: elsewhere it throws
  `"Stored callback <method> requires the main thread"` before it creates or
  publishes anything. The callback context is therefore created there, and its
  own thread check admits every entry, and the final release of the context, on
  the main thread only; a delivery on another thread terminates.
- The generated holder's last release may happen wherever the SDK drops the
  block (a poster thread that still held its observer, an SDK queue). On the
  main thread it releases the context's claim at once; elsewhere it posts that
  release to the main queue (`dispatch_async_f`) and never touches ARC on the
  calling thread. The context itself releases its receiver at cancellation, as
  for every stored block. With `executor = "caller"` such a release terminates.
- `main` is accepted only on a stored Objective-C block; one-shot blocks,
  delegates, target/actions, control actions, instantiated adapters and C
  callbacks still require `caller` ("executor currently requires caller, or
  main for a stored Objective-C block").

`src/tests/python/test_native_objective_c_main_executor.py` posts Foundation
notifications from a background queue and from a BTRC thread to observers on
the main queue, cancels from inside a delivery and checks the receiver is
released once on the main thread, drops a proxy center's block on another thread
(posted release under `main`, termination under `caller`), delivers from another
thread (termination) and registers from a BTRC thread (the exception), plain and
with ASan/UBSan, in both compilers. `test_native_uikit_application.py` posts a
real `AVAudioSessionInterruptionNotification` from a BTRC thread on the iOS
simulator; that is simulator evidence, not device evidence.

### One-shot completion (foundation in progress)

An escaping block that runs exactly once to signal terminal completion uses the
same callback declaration, ordinary BTRC receiver and independent scope:

```toml
[native.bindings.callbacks."-[NSRunLoop performBlock:].block"]
interface = "IRunLoopWork"
lifetime = "one-shot"
failure = "abort"
executor = "caller"
activation-failure = "abort"
cancellation = "abandon"
```

The surrounding binding selects the actual header and methods as usual. A caller
uses `runLoop.performBlock(receiver, scope)` and observes `cancel()` /
`pollCompletion()` on its returned registration. The generated implementation
uses the authenticated `CallbackRequest<IRunLoopWork>` runtime owner, not a native
token. Its activation/ingress/completion methods are adapter machinery, not
provider customization points.

- The native method and block must return `void`; exactly one block is mapped.
  Scalar/enum and managed object block inputs reuse the existing callback leases.
  Owned result/out-slot completion mappings remain unsupported.
- `one-shot` asserts exactly one terminal callback on the calling executor, even
  after consumer cancellation. SDK `noescape` contradicts this escaping mapping.
  A native API that may silently discard its callback needs another proven
  completion contract; do not use this declaration for it.
- `cancel()` abandons delivery, not native execution. An admission acquired before
  publication protects the outstanding native request. Completion is pending
  until its terminal callback and every admitted receiver call have finished.
  Native holders retain ordinary external ARC claims; no extra root registry.
- Inline completion is valid: context is activated before the native call and
  its final cleanup waits for publication to finish. Duplicate completion and
  wrong-thread delivery terminate at the existing callback exception boundary.
- Activation failure uses the existing `abort` / `unpublished` policies. The
  latter requires a native guarantee of no retained callback or future delivery
  after failure; it is not inferred from `void` or an exception.
- `unregister`, delegate slots and action-selector facts are invalid for this
  mode; Objective-C blocks also reject explicit context pointers. Application shutdown must continue its native executor
  until outstanding work drains. Timeouts and block disposal are not completion.

Both compilers execute inline and real `NSRunLoop` completion with sanitizers.
Expanded failure qualification and native application scheduling remain in progress.

For a C function-pointer/context pair, add the same `context` and `context-index`
facts as a call-scoped binding. For example, a header declaring
`void FinishLater(void (*completion)(WidgetRef, void*), void* context)` maps as:

```toml
[native.bindings.callbacks."FinishLater.completion"]
interface = "ICompletion"
context = "context"
context-index = 1
lifetime = "one-shot"
failure = "abort"
executor = "caller"
activation-failure = "abort"
cancellation = "abandon"
owned-arguments = [0]
```

`FinishLater(receiver, scope)` returns `CallbackRequest<ICompletion>` when the
C function returns `void`. Exactly one callback is mapped, and the callback
itself must return `void`.

A C function returning a scalar, enum or complete pointer-free struct instead
returns `CallbackResult<NativeValue, CallbackRequest<ICompletion>>`:

```btrc
var started = FinishLater(receiver, scope);
var future = started.value;
var request = started.request;
```

The native value's type/layout comes from the header. Struct fields may be
scalars, enums or recursively supported structs; pointer fields, unions and
array-bearing results are not supported by this mapping. `CallbackResult` is an
ordinary owning class in `Library.Callback`, not another lifecycle runtime. The
adapter allocates it before native publication and stores the request through
normal class-field ARC. Ignoring/releasing the result, retaining its request, or
leaving via a BTRC exception uses ordinary managed cleanup. Native completion may
already have happened inline before the value is returned.
A zero value or failure status never implies completion or releases the callback
context: the binding still promises one terminal callback on every returned path.
This value projection is not an owned native-resource result or a cancellation
token mapping. The provider interprets the future/status through its native API.

Do not project this result as a language tuple: tuples are intentionally shallow
borrowed aggregates and cannot own the request. Native value-returning and void
one-shot function adapters both return owned managed values, including through
function variables; call-result classification must not add a second claim.

Native code owns one ordinary ARC context claim until terminal delivery, including
after cancellation. Keep the scope alive and pump the native completion executor
until completion; releasing a pending scope fails closed. Discarding a request
alias does not release native code's outstanding claim. Duplicate-delivery checks
do not make an arbitrary native use-after-free safe after terminal completion.

`owned-arguments` is optional and currently applies only to C one-shot payloads.
Its distinct zero-based indices refer to the **native callback prototype**, not
the projected interface; userdata cannot be selected. Each selected parameter
must be a resource declared in the binding's `resources` table. This is a trusted
foreign assertion that each non-null delivered value carries one independent
owned claim. SDK nullability determines the BTRC parameter type. The adapter
adopts that claim into normal exception cleanup without retaining it again,
including when cancellation suppresses delivery. A receiver can keep a value in
an ordinary managed field; unclaimed values are released on callback return.
No raw handle, separate wrapper or manual release reaches provider code.

Other non-resource pointers and borrowed object payloads still require checked
support. Multiple userdata slots and copied string views use the declarations
below; these mechanisms alone do not migrate WebGPU's device owner.

#### Callback fields in by-value descriptors

Use the same callback declaration with `field` when the native parameter is a
by-value struct carrying its callback and context. Combine it with the existing
owning record input projection; do not expose the native userdata to BTRC:

```toml
# Inside the C binding selecting Info and FinishLater:
owned-records = ["Info"]
record-inputs = ["FinishLater.info"]

[native.bindings.callbacks."FinishLater.info"]
field = "completion"
context = "context"
context-index = 1
interface = "ICompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
```

`field` and `context` name actual mutable fields of the selected SDK struct;
`context-index` still refers to the callback prototype. `InfoInput.completion`
is an ordinary owning `ICompletion` field. The native context field is omitted
from `InfoInput`. Other fields keep their existing record-input conversions.
Mapped callback and context fields are reserved from raw SDK record access; only
the owning input's typed receiver is writable. This also permits callbacks with
`owned-arguments` resource payloads without exposing an unchecked function pointer.
Both callback and receiver are required at invocation. Missing record projections,
pointer/nested callback descriptors, conflicting field mappings, and const/volatile
callback storage are rejected. Every function accepting this input projection
must declare the mapped callback, not silently discard it.

Each invocation snapshots its receiver into a fresh ordinary `CallbackRequest`.
Reusing, changing or releasing the input descriptor does not change an outstanding
request. The generated adapter fills the native callback/context fields and owns
one external ARC claim until terminal delivery; cancellation, inline completion,
late cleanup and native value returns use the same one-shot machinery above.
Descriptor bytes and nested borrowed data still cannot escape the call. Only the
declared callback/context slots have the separate completion lifetime.

For descriptors with multiple opaque userdata slots, use arrays in the same facts:

```toml
context = ["userdata1", "userdata2"]
context-index = [3, 4]
```

The first array identifies native record fields; the second identifies callback
parameter indices. Both sets must be distinct, nonempty and equally sized. Order
is immaterial: every slot carries the same request context, with **one** external
ARC claim, not one claim per slot. Ingress verifies that the returned contexts
agree before accessing the receiver. All slots disappear from the BTRC interface
and owning input. This requires a C one-shot callback field; arbitrary user payload
pointers, flat multi-context calls and silently ignored userdata are not supported.

#### Borrowed callback text

A native byte span can enter a C one-shot callback as an ordinary owned BTRC
`string`. Select its actual record or typedef and declare only its field semantics:

```toml
[native.bindings.string-views.WGPUStringView]
data = "data"
length = "length"
null-length = "zero-or-max"
```

The SDK record must contain exactly these two ordinary fields: a `char*` or
`const char*` and an unsigned integer byte count. Reject other fields, bitfields,
volatile/restrict qualifiers, signed lengths and contradictory mappings of the
same native record. `null-length` is required: `"zero"` permits null data only
with zero length; `"zero-or-max"` additionally permits that length type's maximum
unsigned value as a null sentinel. Both become the ordinary empty string.

At admitted callback entry, generated structured IR validates the length and
copies exactly that many bytes into existing managed string storage. Non-null
data with zero length is not read. Non-null lengths above BTRC's signed 32-bit
string range, invalid null spans and embedded NUL bytes terminate with a native
string-view diagnostic before delivery. No `strlen` or implicit transcoding;
source storage must be readable for its declared byte count during the callback.

Normal ARC/exception cleanup owns the copy. A receiver can save it in an ordinary
field after native storage expires. Canceled delivery does not inspect or copy
the span; owned resource payloads still receive their required cleanup. This is
not a zero-copy borrow or a general record/input/result conversion. Unused
string-view declarations and callback modes other than C one-shot are rejected.

### Stored Objective-C target/action (foundation in progress)

Use the same stored callback binding for native momentary-control actions. Select
the actual target and action accessors; the two extra keys declare Objective-C's
`void action(id sender)` convention, not an invented SDK protocol:

```toml
[native.bindings.callbacks."-[NSButton setTarget:].target"]
interface = "IButtonAction"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSButton setTarget:]"
slot-getter = "-[NSButton target]"
action-setter = "-[NSButton setAction:]"
action-getter = "-[NSButton action]"
activation-failure = "abort"
cancellation = "entry-barrier"
```

This generates `IButtonAction { void invoke(); }`. Call
`button.setTarget(handler, scope)`; the returned registration uses the existing
`CallbackContext`/`CallbackScope` ownership, admission and nonblocking cancellation.
The handler knows its source; native sender and selector values do not enter its
API. The generated native method verifies sender identity before dispatch.

All four accessors must be distinct non-consuming instance methods of the same
receiver. The target setter/getter require explicitly nullable `id`; the action
setter/getter require explicitly nullable `SEL`. Setters return void. `methods`
is not allowed alongside action accessors. Reserved slot getters and the selector
setter cannot be called directly by consumers.

Both slots must be vacant before publication. The adapter roots its context,
sets and verifies the target, then sets and verifies the action and target again.
Indeterminate or partially successful publication terminates under the declared
policy. Cancellation verifies both identities, clears the action before the
target, and verifies both empty; it never overwrites another registration.
Inline self-cancellation is resolved after publication. A retained native target
may outlive cancellation: late notifications are ignored by shared admission,
and its source remains alive until the native holder is released.

Action callbacks must only enqueue bounded typed work; execute application
commands after native dispatch, not within AppKit tracking. This binding supplies
safe native delivery, not a queue, event loop, or completed portable GUI factory.

### Stored Objective-C control actions

UIKit controls keep any number of target/action pairs and remove one pair by
repeating it: `-[UIControl addTarget:action:forControlEvents:]` and
`-[UIControl removeTarget:action:forControlEvents:]`. Name the selector
parameter, which the compiler fills with its own action, and list every other
registration parameter that the remove call repeats:

```toml
[native.bindings.callbacks."-[UIControl addTarget:action:forControlEvents:].target"]
interface = "IControlAction"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[UIControl removeTarget:action:forControlEvents:]"
action-parameter = "action"
captured-handles = ["controlEvents"]
activation-failure = "abort"
cancellation = "entry-barrier"
```

This generates `IControlAction { void invoke(); }` and
`ICallbackRegistration addTarget(IControlAction target, UIControlEvents
controlEvents, CallbackScope scope)` on the control. The selector parameter
disappears; registration and cancellation use the shared `CallbackContext` and
`CallbackScope`, as for every stored callback.

- Both methods are distinct, non-consuming, void instance methods of the same
  receiver, with the same parameter names. The target is nullable `id` in both,
  and the named parameter is a `SEL`.
- Every other parameter must be listed in `captured-handles`, be a scalar or an
  enum, and have the same type in both methods. The generated target keeps the
  registration's values and passes them to the remove call.
- The control does not retain its targets, so the registration keeps the
  generated target alive until cancellation has removed the pair and drained
  admitted calls. The target checks that each action comes from its own control
  before delivery.
- `activation-failure` must be `abort`: an Objective-C exception from the add
  call terminates. There is no slot to verify, because the control keeps every
  other target. The remove call is reserved for generated cancellation.

`src/tests/python/test_native_objective_c_control_actions.py` covers a macOS
proxy control (two registrations on one control, cancellation inside a
delivery, 1,000 cycles, sanitizers, wrong sender, wrong thread, publication and
receiver failures) and the rejections, in both compilers.
`test_native_uikit_application.py` sends real `UIButton` and `UITextField`
actions on the iOS simulator; that is simulator evidence, not device evidence.

### Stored Objective-C delegates (foundation in progress)

A callback binding may project a nullable `id<Protocol>` property to one ordinary
BTRC interface. Select its setter, getter and protocol methods from the real SDK:

```toml
[native.bindings.callbacks."-[NSWindow setDelegate:].delegate"]
interface = "IWindowEvents"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[NSWindow setDelegate:]"
slot-getter = "-[NSWindow delegate]"
methods = ["-[NSWindowDelegate windowShouldClose:]", "-[NSWindowDelegate windowWillClose:]"]
activation-failure = "abort"
cancellation = "entry-barrier"
```

The interface methods use the selected selectors' first segments and their SDK
signatures. An optional `method-names` table maps selected `methods` or `overrides`
to BTRC names when selectors share a first segment:

```toml
method-names = { "-[NSTextFieldDelegate control:textShouldBeginEditing:]" = "shouldBeginEditing", "-[NSTextFieldDelegate control:textView:doCommandBySelector:]" = "performTextCommand" }
```

Keys must name this callback's selected methods or overrides. Values must be
nonreserved BTRC identifiers. Unmapped methods keep their default names; aliases
and defaults must be unique within each projected interface, including the
factory's `create` method. Native selectors, signatures and lifetime contracts
stay unchanged. Signatures are never supplied in the manifest.
Optional protocol methods are valid implementations, not unchecked outbound
calls. Required inherited methods and native signature mismatches must also pass
strict native compilation. Unsupported object results and consuming arguments
remain rejected.

`window.setDelegate(events, scope)` returns the same managed registration used by
stored blocks. Generated protocol methods call contained C thunks into ordinary
BTRC methods. They share `CallbackContext` admission, synchronous return, argument
leases and exception/thread checks; there is no provider selector or userdata code.

The slot must be vacant. An occupied slot is rejected without replacing its
delegate. A `CallbackToken<Source, id>` retains the native source and generated
holder, including for a weak native delegate property. Cancellation verifies slot
identity, clears it with the selected setter and verifies the result. Replacement
outside the registration, a failed setter or indeterminate publication terminates
instead of clearing another owner's delegate or guessing at cleanup. Consumers
cannot call the getter or bypass registration with a raw delegate object.

The setter must be a non-consuming instance method taking one nullable protocol
object and returning void; the getter must return that same nullable protocol
object. An independent scope owns cancellation and observes drain before teardown.
Both compiler paths pass real NSWindow close queries/notifications and injected
delegate lifecycle tests with sanitizers. The macOS application now uses the same
binding for its native quit delegate. Fresh self-hosted verification of the
integrated providers and generated protocol conformance passes; full qualification,
native action scheduling and modal shutdown remain unfinished.
Do not rely on receiver/scope destructors alone to break a foreign-held cycle.
Normal SDK delivery tests do not prove the `unpublished` guarantee for every
native exception. Use terminal `abort` unless the stronger guarantee is known.
Terminal behavior is a safety boundary, not successful recovery or cancellation.

### SDK-instantiated Objective-C adapters

Some SDK entries create their delegate themselves, from a class name:
`UIApplicationMain` takes the application delegate's class name and
instantiates it. Map that `NSString` class-name parameter to an ordinary BTRC
interface; the compiler generates the named class (interop step 6 in
[native-interop-ownership.md](../../docs/design/native-interop-ownership.md)):

```toml
[[native.bindings]]
module = "UIKit"
header = "UIKitBinding.h"
language = "objective-c"
standard = "c11"
os = ["ios"]
symbols = ["UIApplicationMain", "-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]"]

[native.bindings.callbacks."UIApplicationMain.delegateClassName"]
interface = "IApplicationDelegate"
lifetime = "instantiated"
scope = "process"
failure = "abort"
executor = "caller"
methods = ["-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]"]

[[native.frameworks]]
name = "UIKit"
os = ["ios"]

[[native.frameworks]]
name = "Foundation"   # the generated class and its name lookup link against Foundation
os = ["ios"]
```

This imports `IApplicationDelegate` with one method per selected protocol
method, named and typed as for stored delegates, and exposes
`UIApplicationMain(int argc, char** argv, NSString? principalClassName,
IApplicationDelegate delegateClassName)`. Import `Library.Callback`:

```btrc
int main(int argc, char** argv) { return UIApplicationMain(argc, argv, null, Application()); }
```

An Objective-C binding may select such a C entry only through this mapping;
its other arguments are C scalars and pointers or borrowed Objective-C objects,
and its result is a scalar or void. The selected methods must all be
non-consuming instance requirements of one protocol.

The entry roots the receiver in a `CallbackRoot` and passes the generated
class's name. `scope = "process"` declares that the SDK keeps the instance for
the rest of the process: the first `-init` claims the root, which is never
released and stays outside leak accounting, and a second instantiation, or a
second call of the entry, aborts. Deliveries are admitted only on the thread
that called the entry; a wrong-thread delivery or a BTRC exception terminates
at the native boundary. `executor` currently requires `caller` and `failure`
requires `abort`. The generated class extends `NSObject`, or the SDK class
that `superclass` names (below).

A selected method of an instantiated adapter may return a managed Objective-C
object, as `-[UIApplicationDelegate
application:configurationForConnectingSceneSession:options:]` returns a
`UISceneConfiguration`. The receiver's result is one ordinary claim, which the
generated method transfers to ARC on return; a null result for an SDK non-null
type terminates at the native boundary. Stored delegates still reject object
results.

#### Instance-scoped instantiated adapters

Some SDK methods take a class rather than a class name, and create one
instance per use: `-[UISceneConfiguration setDelegateClass:]` names the scene
delegate class, and UIKit instantiates it once for each scene it connects. Map
that `Class` parameter with `scope = "instance"` and name the method after
which the instance is finished:

```toml
[native.bindings.callbacks."-[UISceneConfiguration setDelegateClass:].delegateClass"]
interface = "ISceneDelegate"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
methods = ["-[UISceneDelegate scene:willConnectToSession:options:]", "-[UISceneDelegate sceneDidBecomeActive:]", "-[UISceneDelegate sceneDidDisconnect:]"]
terminal = "-[UISceneDelegate sceneDidDisconnect:]"
```

This imports `ISceneDelegate` from the selected methods, as above, and a
generated factory interface `ISceneDelegateFactory { ISceneDelegate create(); }`
named after it. The method becomes `void setDelegateClass(ISceneDelegateFactory
factory)` on `UISceneConfiguration`:

```btrc
class Scenes implements ISceneDelegateFactory {
	public ISceneDelegate create() { return Scene(); }
}
configuration.setDelegateClass(Scenes());
```

- The call roots the factory in a `CallbackRoot` and passes the generated
  class. A later call replaces the factory and releases the previous one;
  instances that already exist keep their receivers. The current factory stays
  rooted, outside leak accounting, until it is replaced.
- Each `-init` claims a new receiver: it calls `create()` and roots the result
  for that instance alone. It aborts when no factory was registered and when
  `create()` returns null.
- Each selected method enters through the instance's receiver and holds a claim
  on it for the call, so an instance released during its own method finishes
  against live memory. After the `terminal` method returns, the instance
  releases its receiver; later void methods do nothing and methods with a
  result abort. `-dealloc` releases a receiver the instance still holds.
- The factory and every receiver are admitted only on the thread that
  registered the factory, UIKit's main thread for scenes. A wrong-thread
  instantiation, delivery or release, and a BTRC exception, terminate at the
  native boundary.

The parameter must be the only parameter of a void, non-consuming Objective-C
instance method, typed `Class` without protocol qualifiers. `terminal` is
required and names one of `methods`; it is rejected with `scope = "process"`,
and `scope = "process"` is rejected on a `Class` parameter. A class method, any
other parameter type and colliding method names are rejected. The receiver
interface's name plus `Factory` must not collide with another imported name.

`src/tests/python/test_native_instantiated_adapters.py` covers a macOS proxy
configuration that instantiates the generated class twice and delivers through
both instances: independent receivers, a replacement factory registered during
a delivery, an object result, release after the terminal method, nothing after
it, an abort for a value method after it, an instance released inside its own
method, release at dealloc, a wrong-thread instantiation, a null `create()` and
a missing factory, plain and with ASan/UBSan, in both compilers, and the
rejections. `test_native_uikit_application.py` runs the real UIScene
life cycle on the iOS simulator; that is simulator evidence, not device
evidence.

#### Objective-C subclass adapters

A view that hosts a `CAMetalLayer` must subclass the SDK's view class and answer
methods of that class itself: `+[UIView layerClass]` and `-[UIView
layoutSubviews]`. BTRC creates such an instance, so the binding maps the
implicit `self` of the superclass's designated initializer and names the
superclass and the methods the generated class overrides:

```toml
symbols = ["-[UIView initWithFrame:]", "+[UIView layerClass]", "-[UIView layoutSubviews]", "-[UIView updateConstraints]", "-[UIView layer]", "-[UIWindow bounds]"]

[native.bindings.callbacks."-[UIView initWithFrame:].self"]
interface = "IMetalView"
lifetime = "instantiated"
scope = "instance"
failure = "abort"
executor = "caller"
superclass = "UIView"
overrides = ["+[UIView layerClass]", "-[UIView layoutSubviews]", "-[UIView updateConstraints]"]
```

This imports `IMetalView { void layoutSubviews(); void updateConstraints(); }`
from the instance overrides (after any protocol `methods`, which the class then
adopts) and `IMetalViewFactory { IMetalView create(); string layerClass(); }`
from the class overrides. The initializer becomes the class method
`UIView initWithFrame(IMetalViewFactory factory, CGRect argument0)`:

```btrc
class MetalView implements IMetalView {
	public void layoutSubviews() { ... }
	public void updateConstraints() { ... }
}
class MetalViews implements IMetalViewFactory {
	public IMetalView create() { return MetalView(); }
	public string layerClass() { return "CAMetalLayer"; }
}
UIView view = UIView.initWithFrame(MetalViews(), window.bounds());
```

- The call roots the factory as `setDelegateClass` does, replacing and
  releasing a previous one, and sends the initializer to a new instance of the
  generated subclass. Its override sends the initializer to `super` and then
  claims a receiver from `create()`, as an instance-scoped adapter's `-init`
  does. The call returns the new object.
- An instance override enters the instance's receiver and holds a claim on it
  for the call. A class override enters the factory, the class's receiver:
  UIKit asks `+layerClass` inside `[super initWithFrame:]`, before the instance
  has a receiver. A class override must return `Class` and take no
  parameters. BTRC cannot hold a class object, so its method returns the
  runtime name of an Objective-C class, which the generated method resolves
  with `objc_lookUpClass`; a name no class answers terminates ("Objective-C
  override +[UIView layerClass] names no Objective-C class: ...").
- The reader reports `requires_super` for a method whose nearest declaration
  carries `NS_REQUIRES_SUPER`. Its override sends the same message to `super`
  after the receiver returns, also when the instance has no receiver
  (`-updateConstraints` asks for super as its final step). Such an override
  must return void. Every other override replaces the superclass's
  implementation.
- `terminal` is optional and names an instance method; without it the instance
  releases its receiver at `-dealloc`. A receiver that keeps its own view in a
  field is a cycle foreign code holds, which only `terminal` or dropping the
  field breaks.
- An instance the SDK creates through another initializer (nib decoding's
  `-initWithCoder:`), and an override the superclass sends inside its own
  initializer, have no receiver: void overrides do nothing beyond a required
  super send, and value overrides terminate.

The key's method must be an Objective-C instance initializer of the
superclass whose reader fact `designated_initializer` holds: one of the
designated initializers of that class, or of its nearest ancestor when it
introduces none. `superclass` must be the initializer's class and `scope` must
be `instance`. Each override must be a selected, non-protocol method of the
superclass (named on the superclass, inherited methods included) outside the
init, alloc, new, copy and dealloc families, non-variadic and non-consuming.
Names may not collide across `methods`, instance overrides, `create` and class
overrides.

The forms the SDK instantiates itself take `superclass` and `overrides` too: a
UIKit application or scene delegate that must be a `UIResponder`, to join the
responder chain or answer responder methods.

```toml
[native.bindings.callbacks."UIApplicationMain.delegateClassName"]
interface = "IApplicationDelegate"
lifetime = "instantiated"
scope = "process"
failure = "abort"
executor = "caller"
superclass = "UIResponder"
methods = ["-[UIApplicationDelegate applicationDidFinishLaunching:]", "-[UIApplicationDelegate applicationDidBecomeActive:]"]
overrides = ["-[UIResponder canPerformAction:withSender:]"]
```

- The generated class extends `superclass` and adopts the protocol of
  `methods`, which stay required. The SDK creates it with `-init`, which sends
  `[super init]` before it claims its receiver, as the `NSObject` form does.
- Instance overrides join the receiver interface after the protocol methods,
  checked as above, and an `NS_REQUIRES_SUPER` override sends super after the
  receiver returns. The process form's receiver is rooted before the SDK
  creates the instance, so its overrides always find it; the instance form's
  overrides behave as a subclass adapter's, without a receiver before `-init`
  returns and after `terminal`.
- Class overrides join `I<Interface>Factory` and so need the instance form; on
  the process form they are rejected ("class-method overrides require an
  instance-scoped adapter"). `overrides` without `superclass` is rejected
  ("overrides require superclass"), as is a superclass without a complete
  interface.

`src/tests/python/test_native_objective_c_subclasses.py` covers a Foundation
proxy shaped like `UIView` (two designated initializers, `+layerClass` asked in
the initializer, an `NS_REQUIRES_SUPER` method): class and instance overrides,
an object result, the required super send, a replacement factory, an instance
from the other initializer, a value override without a receiver, a wrong
thread, an unknown class name and a null `create()`, plain and with
ASan/UBSan, in both compilers, plus the rejections. A real `NSView` subclass
returns a `CAMetalLayer` from `-makeBackingLayer` and receives `-layout`,
`-updateConstraints` and `-drawRect:` from AppKit. For the SDK-created forms
it runs a process delegate created from a class name that extends `NSResponder`
(or an `NSResponder` subclass with an `NS_REQUIRES_SUPER` method) and answers
`-acceptsFirstResponder` and a `SEL`-taking `-tryToPerform:with:`, and an
instance delegate created from a class whose class override answers before any
instance exists and whose required super send follows the terminal method, plus
the rejections. `test_native_uikit_application.py` shows a `UIView` subclass
whose layer is a `CAMetalLayer` in a scene's window, and a `UIResponder`
application delegate that is UIApplication's next responder and answers
`-targetForAction:withSender:` through its `-canPerformAction:withSender:`
override, on the iOS simulator; that is simulator evidence, not device evidence.

#### Objective-C error outputs

Cocoa reports failure through an `NSError**` parameter. Name it in
`error-outputs`:

```toml
error-outputs = ["-[NSFileManager contentsOfDirectoryAtPath:error:].error"]
```

The parameter disappears from the BTRC method,
`NSArray? contentsOfDirectoryAtPath(NSString argument0)`. The generated adapter
passes its own `NSError*`, initially nil, and after the call a nil error is
success. A non-nil error becomes a BTRC exception, `"NSError: "` followed by the
error's `localizedDescription` in UTF-8, cut at a character boundary to the
runtime's 1,023-byte message (F1 in
[native-interop-ownership.md](../../docs/design/native-interop-ownership.md)).
The adapter's autorelease pool releases the error and ARC the result before the
exception starts, and argument leases unwind as it runs. An `NSError**`
parameter that `error-outputs` does not name is rejected ("NSError**
parameters require error-outputs"), so a failure is never ignored.

Each entry must name a parameter of a selected Objective-C method whose type
is a pointer to a nullable `NSError` object, without other qualifiers; a
method takes at most one, and not together with callback parameters or a
subclass adapter's initializer. `test_native_objective_c_errors.py` lists a
directory with `NSFileManager`, lists and removes a missing one, passes a null
generic attribute dictionary, cuts a long description at a character, and
throws a thousand probe errors with none left alive, plain and with
ASan/UBSan, in both compilers, plus the rejections.

#### Lightweight generics

Lightweight generics are erased to their bound, for calls, results and callback
payloads alike: `NSArray<NSString *> *` is `NSArray`, and a method of the class
that returns its type parameter (`-[NSArray objectAtIndex:]`'s `ObjectType`)
returns the parameter's bound, `id` unless the class declares another, as the
reader reports it. A checked downcast recovers the element class. Generated
implementations keep the SDK's spelling, type arguments included, so a block
or override still matches its declaration. Protocol-qualified objects
(`id<P>`) in parameters and results stay rejected; a checked cast reaches a
protocol handle instead (below).

#### Checked Objective-C downcasts

`(T?)value` on a managed Objective-C object is a checked conversion (M3 in
[native-interop-ownership.md](../../docs/design/native-interop-ownership.md)).
`T` must be an imported Objective-C class whose superclass chain, read from the
SDK interface graph, contains the static class of `value`; `value` may be `id`.

```btrc
UIWindowScene? windowScene = (UIWindowScene?)scene;
if (windowScene != null) { var window = UIWindow.initWithWindowScene(windowScene); }
```

- A null input yields null without sending a message.
- Otherwise the generated Objective-C unit asks `[value isKindOfClass:T]`. A
  mismatch yields null; a match yields the same object with a new native claim,
  taken before the source's call lease ends, so the result outlives its source.
  A temporary source is released after the test.
- The unit names `T` by its runtime name (`objc_lookUpClass`), because an
  imported class can be a forward declaration in the selected headers. A class
  that is absent at run time matches no object. An Objective-C exception from
  the test terminates.

A nonnullable target is rejected ("Objective-C downcasts are checked and require
a nullable target"), and so are casts between unrelated classes ("Objective-C
casts require a proven object upcast or a nullable checked downcast").
Upcasts, including to `id`, stay unchecked conversions.

A protocol whose own instance methods the binding selects is a **protocol
handle**: a managed Objective-C object type named after the protocol, which the
generated unit spells `id<P>`. Its methods are the selected requirements, and
`(P?)value` is the checked conversion that produces one:

```toml
symbols = ["+[NSLock new]", "-[NSLocking lock]", "-[NSLocking unlock]"]
```

```btrc
NSLocking? locking = (NSLocking?)NSLock.new();
if (locking != null) { locking.lock(); locking.unlock(); }
```

- The cast asks `[value conformsToProtocol:P]`, with the same null, mismatch
  and claim rules as `isKindOfClass:`. The unit finds `P` by its runtime name
  (`objc_getProtocol`); a protocol no loaded image registers matches no object
  and sends no message.
- The reader reports no class conformance, so every cast to a handle is
  checked, from any Objective-C object: a class, `id` or another handle. A cast
  from a handle to a class asks `isKindOfClass:`. A handle converts to `id`
  unchecked; assigning a class value to a handle without a cast is a type
  error.
- A protocol method belongs to a handle only when its receiver names no class:
  the reader resolves a class of the same name first, as it does for
  `NSObject`, and a protocol method selected on a class (`-[NSLock unlock]`) is
  that class's method. A handle takes instance methods outside the init family
  ("Objective-C protocol handles take instance methods outside the init
  family"), no callbacks, and, as on a class, no optional method ("Optional
  Objective-C calls require an availability check").
- `id<P>` parameters and results stay rejected ("Objective-C
  protocol/generic/dynamic objects require managed native lowering"); a
  delegate slot keeps its own `id<P>` mapping.

`test_native_objective_c_downcasts.py` covers null input, a match, a mismatch, a
base-class instance, `id` sources, a result that outlives its source, 1,000
casts with no live object left, ASan and UBSan, and the rejections, in both
compilers, for classes and for protocol handles: casts to a protocol from a
class, from `id` and from another handle, from a handle back to a class,
`NSLocking` on an `NSLock`, and the rejected handle methods and `id<P>` result.

### Header selection

```toml
[[native.bindings]]
module = "CoreFoundation"
header = "native/CoreFoundation.h"
language = "c"
standard = "c11"
symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease"]
read-only-borrows = ["CFStringCreateWithCString.cStr"]
os = ["macos"]
```

`module` uses existing package-relative dotted module lookup; `header` must be a
file inside the package, including after symlink resolution. An umbrella header
may include SDK headers; do not copy SDK signatures into the manifest. `symbols`
may select protocol methods such as `-[NSWindowDelegate windowShouldClose:]` for
delegate-contract extraction. The shared semantic model preserves the declaring
protocol, requested receiver, full selector, signature, and required/optional
status, including inherited methods. A class of the same name takes precedence
for an ordinary method selection. Protocol methods are not imported as classes
or callable instance methods: a protocol receiver requires a checked delegate
binding. Required methods adopted by a concrete class remain ordinary native
calls (for example, `NSView.appearance` from `NSAppearanceCustomization`).
Optional calls through a concrete class still require an availability check.
Optional-method metadata alone does not establish runtime method
availability. Delegate binding and lifecycle generation remain in progress.

`symbols` is a non-empty, duplicate-free array of exact names (`name` or `namespace::name`).
Objective-C/Objective-C++ bindings also accept exact `+[Class selector:]` and
`-[Class selector:]` spellings, with one or more named selector components.
`Class` is the requested receiver, not necessarily the declaring class: selecting
`-[NSOpenPanel setTitle:]` uses Clang's inherited/category lookup and retains
`NSSavePanel` as the declaring owner. Overrides keep their actual SDK identity.
The source consumer exposes Objective-C class and instance methods as ordinary
method calls and rejects ambiguous method-name projections. Native object
handles retain SDK identity and use generated ARC lifetime operations;
`instancetype` results use the receiver type. Scalar-pointer parameters preserve
const/nullability qualifiers and require caller-owned storage. Enum constants
are imported as typed values. Scalar globals use generated address accessors that
preserve SDK storage identity and const protection; initialize references to them
at runtime, not in static storage. Required arguments and non-null object results
are checked at the BTRC boundary.

Selected instance initializers in the SDK's `init` family with `instancetype`
results project as class factories: `NSTrackingArea.initWithRect(...)` generates
`[[NSTrackingArea alloc] initWithRect:...]` inside the ARC adapter. No existing
BTRC alias is consumed. Native nil, replacement objects and throwing initializers
follow normal ARC cleanup and the existing BTRC exception boundary. Initializers
with callbacks require a separate checked publication contract and are rejected.

Lightweight generic arguments consisting solely of unqualified `id` (for example
`NSDictionary<id, id>`) preserve the nominal managed class. Concrete type bounds,
protocol qualifications, nested generics and class-object payloads are not erased
to make an unsupported signature callable.

Objective-C object globals expose independent owned snapshots, never their native
pointer slots. Constant slots may be read normally. A mutable SDK declaration
requires `main-thread-globals = ["SelectedObjectGlobal"]` on the same binding:
the binding author guarantees that native writes are confined to the main thread
(or never occur). Each generated read checks the main thread **before** reading
and retaining the object; a wrong-thread read throws. The check does not make
arbitrary concurrent foreign writes safe. The original SDK declaration remains
unchanged. Consumers cannot assign, address or release the slot, but may store,
alias and release the returned snapshot through ordinary ARC. Unknown, duplicate,
non-object or non-Objective-C mappings are rejected. This supports actual AppKit
notification-name declarations without inventing const qualifiers or copying
their string values.

It generates a separate ARC unit in the link plan, translates exceptions back
to BTRC after native cleanup, and never includes Objective-C headers in the
main C11 unit. Blocks require the explicit callback mappings above. Consuming
existing receivers/arguments, unsupported protocol/generic/class-object shapes
and borrowed interior results remain rejected. Checked native subclass conversion
uses SDK inheritance; unrelated casts cannot manufacture ownership or type safety.
Language/standard and `os`/`arch` use the existing closed sets. There is no
package-wide binding. Duplicate exports into the same module are rejected when
their target predicates overlap, including inactive targets; disjoint providers
are allowed. Bindings participate in manifest locking but are compiler inputs,
not link-plan linker records or native source units.

Both compiler consumers require explicit `BTRC_NATIVE_HEADER_READER` (built with
`nix build .#btrc-native-header`), `BTRC_NATIVE_SYSROOT` (an available macOS SDK,
a Linux GNU sysroot with `usr/include`, or a MinGW-w64 sysroot with `include`),
and `BTRC_NATIVE_TARGET` (a triple matching `--target`: `arm64-apple-macosx14.0.0`,
`aarch64-unknown-linux-gnu`, or Clang's normalized MinGW spelling
`x86_64-w64-windows-gnu`; the alias `x86_64-w64-mingw32` and MSVC triples are
rejected). The Nix development shell and packaged compilers supply these from
their pinned reader, SDK and host platform; explicit caller values override
the package defaults. A cross build supplies the target's triple and sysroot
the same way; a binding whose header includes no SDK header reads identically
from an empty sysroot directory, which is how the native-package example's
macOS and Windows plans are proven from any host. A raw standalone compiler still requires configuration.
`btrcc` also requires `--target OS-ARCH` when a reached stdlib module imports
native headers, even without a project manifest. Omitting it is an error, not
permission to drop target-scoped bindings and use approximate hosted declarations.
They import C scalar/typedef/opaque-pointer signatures, supported C structs,
exact function-pointer signatures, constants, native globals and SDK parameter names into
ordinary visibility and type checking. Struct declarations retain the SDK's
tag or anonymous typedef spelling; the compiler does not reproduce SDK layouts.
Link the emitted C with the
same target/SDK and required frameworks. There is no automatic SDK fallback.
Types or explicit ownership annotations that cannot yet be lowered faithfully
fail; unannotated pointers remain raw, not managed resources. Native compilations
bypass artifact caching until its key includes transitive headers and toolchain
identity. This is not a completed cross-platform import or lifetime feature.

#### Shared native-reader batch protocol

The host reader accepts either standalone `--symbol`/`--record-path`/
`--record-value` selections or `--batch=FILE` (`--batch=-` reads stdin).
Exactly one translation unit, target and compile command applies to the whole
batch, including ordered include/define flags and pkg-config dependencies.
Consumers may group requests only when these inputs agree. Sharing a header
basename, language or target alone is insufficient. This shares a fresh parse;
it is not a persistent SDK cache and does not waive header validation.

The request envelope has exactly `schema = "btrc.native-requests.v1"` and a
nonempty `requests` array. Each request has a unique nonempty string `id`, a
nonempty string array `symbols`, and optional string arrays `record_paths` and
`record_values`. Unknown fields and malformed selections fail before Clang
executes. Symbols, layouts, receiver interfaces and extraction errors remain
private to their request; one request's selected C++ owner grants no permission
to another. The command-line standalone selection options cannot be mixed
with a batch.

The response envelope is `schema = "btrc.native-responses.v1"` with `results`
in request order. Each result contains the same `id`, an `errors` string array,
and `document`: the existing native-declarations semantic document on success,
or JSON null when selection fails. A successful batch process means the
envelope was produced, **not that every selection succeeded**. Consumers must
validate the exact expected ID set/order, reject malformed envelopes, attribute
selection errors to the original binding and pass each successful document
through the ordinary semantic decoder. Never import a sibling's declarations
as a substitute for a failed request. An invalid batch, unavailable dependency
or Clang translation-unit error gives a nonzero exit and no partial stdout.

The text transport must also reject embedded raw NUL bytes, including after an
otherwise valid document. A C-string prefix is not the complete response. The
self-host Unix provider compares the selected captured stream's byte count
against its text length before admission; the codec separately rejects escaped
NUL inside JSON strings. This applies to standalone responses as well as batches.

Both compiler consumers group requests by the complete ordered non-selection
arguments and preserve original binding projection order. Singletons keep the
standalone path. The reference consumer captures one environment snapshot per
resolution and fingerprints validated semantic values, so equivalent standalone
and batch JSON formatting does not change artifact identity. Every resolution
still reads the SDK afresh.

The self-host host request carries stdin and explicit capture/time allowances.
Each member retains its existing 8 MiB output and 60-second execution allowance;
groups above 255 members are partitioned to fit the process API's signed 32-bit
capture budget. This is a process partition, not an import-count limit. Envelope
validation precedes per-binding projection, and a later failed selection remains
attributed to that binding. Batching does not establish self-host artifact-cache
parity or satisfy the complete product no-op budget by itself.

Outer `_Nullable` and `_Nonnull` pointer annotations on function parameters and
results are preserved. Nullable values keep their original pointer depth;
non-null contracts use typed IR-generated call adapters, including calls through
stored function values. A null non-null argument or result prints a diagnostic
and aborts at the boundary; this is not recoverable exception translation.
Nested `_Nullable` output slots and callback values use BTRC's null-admitting raw
pointer representation without adding indirection. The SDK declaration remains
authoritative. Nested `_Nonnull` promises still fail: they require directional
output/callback enforcement, not just an outer call guard.
These checks do not establish ownership, callback lifetime or realtime safety.

Function calls retain the SDK's source name and included declaration, so the
native compiler applies SDK linker aliases. BTRC does not redeclare those
functions using the linker spelling. Top-level parameter `restrict` is excluded
from compatible function-type projection; the original C declaration and its
aliasing obligations still apply. Nested `restrict`, volatile pointers and
restricted return types remain unsupported.

A complete SDK record imported indirectly can own storage (`sizeof`, locals,
or allocation) without exposing its private fields. The SDK header supplies its
size and alignment; BTRC does not emit an empty/mirrored definition. A genuinely
incomplete SDK type still cannot own storage. Field access requires imported
field metadata. Verified native declarations use their SDK signatures, not
approximate hosted-ABI prototypes; handwritten declarations retain the existing
hosted-ABI checks.

Native globals refer to SDK-owned storage; the compiler does not emit another
definition. A read-only pointer slot and a pointer to read-only data are distinct:
`int *const` forbids rebinding but permits pointee writes; `const int *` does the
reverse. Local shadowing is allowed, but handwritten global redeclarations may
not replace the imported declaration. Taking a read-only scalar/record's address
preserves const; taking a read-only pointer slot's address is rejected until
per-pointer qualifiers can be represented faithfully. Thread-local, renamed,
and C++-linkage globals remain unsupported and produce no partial output.

The Unix self-host entry point supplies bounded SDK-reader execution. The
Windows host entry point uses the same compiler pipeline without that capability;
selected SDK imports fail explicitly rather than pulling unsupported Unix
process helpers into the Windows executable.

### Read-only call borrows

The optional `read-only-borrows` array names exact `function.parameter` pairs
from the selected header declarations. This is a **trusted package assertion**:
the call neither writes through the argument nor retains, consumes, returns,
or otherwise exposes any address into its storage after the call, on any path.
It is not inferred from `const`, and the compiler cannot prove a foreign
implementation honors it. Review the upstream API before declaring it.

The initial surface accepts only pointers to const scalar storage, such as
`CFStringCreateWithCString.cStr`. It allows a managed string to be borrowed for
that copying call without a handwritten wrapper or an intermediate copy.
It does not establish ownership of the returned CF object.
Unknown functions/parameters, duplicate entries, mutable pointers, nested
pointers, records and conflicting consumed-parameter annotations fail closed.
Declarations are attached to the imported function, not a global name whitelist;
ordinary BTRC forwarding wrappers use the same borrow-effect proof. Erasing a
function into a type without borrowing metadata does not grant permission to
pass a managed value. Unannotated SDK calls remain conservative.

### Realtime native calls

### Owning native record inputs

A C binding can generate ordinary owning BTRC classes for selected SDK input
records. The SDK structs themselves keep their original ABI and remain available.

```toml
# Inside [[native.bindings]], with these records and function in symbols:
owned-records = ["WGPUSurfaceDescriptor", "WGPUSurfaceSourceMetalLayer"]
record-inputs = ["wgpuInstanceCreateSurface.descriptor"]
[native.bindings.object-fields]
"WGPUSurfaceDescriptor.nextInChain" = "WGPUSurfaceSourceMetalLayer?"
"WGPUSurfaceSourceMetalLayer.layer" = "CAMetalLayer"
```

This exposes `WGPUSurfaceDescriptorInput` and `WGPUSurfaceSourceMetalLayerInput`.
Their mapped fields retain ordinary BTRC or selected Objective-C objects. Import
the module owning `CAMetalLayer` in the binding's BTRC module. Other fields retain
their SDK-derived types; no header signatures or byte offsets are duplicated.

`record-inputs` changes only the named record-value or const-record-pointer
parameters. At each call, including indirect calls, a generated adapter materializes
temporary SDK records and converts mapped object fields. The header determines
whether it passes the record by value or its address; this is not another binding
flag. Both forms use the same owning input class. Native changes to a by-value
record do not write back to that class. Nullable pointer parameters/fields accept
null; value parameters and required mapped fields are checked before calling
native code. Unannotated root parameters are required. A nested record pointer
must match the SDK record identity, or its first embedded record at offset zero
(for typed extension chains). Cycles, unknown fields, incompatible pointers,
direct array/const-value fields, and realtime declarations are rejected.

Mapped Objective-C fields are retained in the adapter's existing cleanup scope
until the native call returns, including fields in nested descriptors. An inline
callback may clear or replace the owning input's fields without invalidating the
native snapshot. These call leases do not extend the descriptor bytes past the
call or make invalidatable interior storage safe.

This is a **trusted package lifetime declaration**: native code borrows the
temporary descriptor bytes and chain only during the call; it cannot store or
return those addresses. It may independently retain a mapped Objective-C object
through that object's native ownership API. The owning input and the callee's
retained object have separate lifetimes. This is not `read-only-borrows`, an
output/writeback adapter, or permission for application code to cast managed
objects to raw pointer storage. A record input alone grants no callback lifetime;
the explicit callback-field declaration above supplies that separate contract.
Verify the actual callee's lifetime behavior before selecting this mapping.

Fields whose exact SDK type has a managed C `resources` declaration also project
into owning record inputs. No extra field map is needed: `Config.widget` of type
`WidgetRef` becomes an ordinary managed `ConfigInput.widget`, with SDK nullability.
The input retains assigned resources; generated call adapters snapshot and retain
each resource until the call returns, even if a reentrant callback clears or
replaces that field. Nested pointer descriptors use the existing `object-fields`
composition. Embedded by-value fields whose SDK record type is also in
`owned-records` automatically become non-null owning input fields. For example,
selecting `WGPUVertexState` and `WGPURenderPipelineDescriptor` makes
`WGPURenderPipelineDescriptorInput.vertex` a `WGPUVertexStateInput`; its `module`
owns the declared shader resource. Assign a child input before calling native
code. The adapter copies its SDK value and leases its managed fields through
the call, recursively through mixed pointer/value descriptors.

An explicit `object-fields` entry may name that same embedded record, but cannot
make it nullable or substitute a different layout, including a prefix-compatible
record. Value fields have no null representation. Undeclared resource-bearing
embedded records, uninitialized required children, and array/const-value fields
are rejected rather than exposing raw managed storage. Native casts and release
hooks stay in structured adapter lowering.

Those resource fields are unavailable on the raw SDK record. Const/volatile
resource slots and `object-fields` overrides of their type/nullability are rejected.
Every resource-bearing descriptor parameter requires `record-inputs` or a checked
`record-outputs` mapping. Resource-bearing record returns remain rejected. This support does not
infer transfer, zero-copy interior borrows or permission to retain descriptor bytes.

### Owning C output records

Declare missing ownership facts in the same binding; SDK headers supply the
record layout, resource types, nullability and scalar/status fields:

```toml
# Include these functions/records and their resource retain/release operations
# in symbols, and declare WGPUSurface/WGPUTexture under resources as usual.
owned-records = ["WGPUSurfaceTexture"]
borrowed-parameters = ["wgpuSurfaceGetCurrentTexture.surface"]
record-outputs = ["wgpuSurfaceGetCurrentTexture.surfaceTexture"]
owned-output-fields = ["wgpuSurfaceGetCurrentTexture.surfaceTexture.texture"]
null-output-fields = ["wgpuSurfaceGetCurrentTexture.surfaceTexture.nextInChain"]
```

`wgpuSurfaceGetCurrentTexture(surface)` then returns an ordinary managed
`WGPUSurfaceTextureOutput` with `texture` and `status` fields. The native out
parameter disappears; `nextInChain` is not exposed. Every declared resource field
must be listed in `owned-output-fields`. Each returned non-null field supplies
one owned native claim, including on error statuses. Provider code interprets
status; the compiler never guesses that zero or another value means success.

The adapter allocates the empty BTRC owner before the native call, zero-initializes
the SDK record, leases managed inputs, and adopts all returned resource claims
without an extra retain. Ordinary ARC releases fields on scope exit, explicit
release or BTRC exception cleanup. Saving a field uses ordinary managed retention.
Required resource fields are checked after adoption. `null-output-fields` is an
explicit no-extension-storage contract: the native pointer starts null and must
remain null. A violated native promise aborts; it is not a recoverable status.

Current support is one mutable record-pointer output on a C function returning
`void`. Scalar fields and declared C resources are supported; other pointers need
`null-output-fields`. Nested aggregates, callbacks, realtime functions and
resource-bearing native return values are rejected. Native code must return
normally; this is not an exception adapter or asynchronous output buffer.

Non-void native results remain rejected until this mapping has an owning result
projection. Language tuples are intentionally shallow borrowed aggregates;
`(status, Output)` would leak its output owner. Do not enable that projection by
requiring consumers to manually balance fields or changing tuple semantics. Use
ordinary owning classes, as with `CallbackResult`, when extending this mapping.

### Owner-admitted record snapshots

`record-snapshots` copies selected SDK record paths from an existing unique or
reference-counted C resource into an ordinary owning BTRC class. It is distinct
from `owned-records`: the result is a generated snapshot, not a projected SDK
record supplied to a native function.

```toml
[native.bindings.record-snapshots.FreeTypeGlyphSnapshot]
owner = "FT_Face"
name = "copyFreeTypeGlyph"
fields = { advanceX = "glyph.advance.x", pitch = "glyph.bitmap.pitch" }

[native.bindings.record-snapshots.FreeTypeGlyphSnapshot.byte-plane]
field = "bitmap"
pointer = "glyph.bitmap.buffer"
width = "glyph.bitmap.width"
rows = "glyph.bitmap.rows"
pitch = "glyph.bitmap.pitch"
```

The owner must already be a selected resource. Class/function names and copied
field aliases must be distinct. The header reader and importer validate every
dotted path against complete, noncyclic SDK structs; unavailable, anonymous,
bit-field, volatile and restrict-qualified traversal is rejected. Scalar leaves
copy their native scalar types, never resource pointers. An empty scalar table
is allowed with a byte plane, byte span or copied strings.

Without a byte plane, the generated function takes just the authenticated owner.
With copied bytes or strings, its second argument is `int maximumBytes`.
Copied bytes require `Library.Bytes` from the authenticated standard library. The result is nullable:
invalid bounds, a null intermediate pointer or invalid plane metadata returns
null after unwinding owner leases. Allocation uses ordinary class/Bytes
fail-fast behavior. A live owner lease covers all reads and the complete copy.

Byte-plane width and rows are integral pixel extents; pitch must be signed and
the data field must be a byte pointer. Negative width/rows/bounds are rejected.
Zero width or rows returns owned empty bytes without reading the data pointer.
Otherwise a nonzero pitch and nonnull data pointer are required. The adapter
checks arithmetic, the explicit allocation bound, the Bytes length limit and
address ranges before reading `rows * abs(pitch)` bytes. Width does not imply a
pixel format or byte count; providers validate format-specific row coverage.

Tagged SDK unions use the same snapshot projection with a checked guard:

```toml
[native.bindings.record-snapshots.YAMLScalarSnapshot]
owner = "yaml_event_t"
name = "yamlScalarSnapshot"
fields = { style = "data.scalar.style" }
guard = { field = "type", equals = "YAML_SCALAR_EVENT" }
strings = { anchor = "data.scalar.anchor", tag = "data.scalar.tag" }
byte-span = { field = "value", pointer = "data.scalar.value", length = "data.scalar.length" }
```

The guard path cannot traverse a union. Its leaf must be an SDK enum and the
selected enumerator must have exactly that owning enum identity; equal numeric
values from other enums do not qualify. C enum constants preserve their actual
integer ABI type separately from this identity. The declared tag/arm association
is an SDK semantic promise: the compiler checks equality before reading any
projected union arm, returning null on mismatch. Unguarded union traversal is
rejected. No arbitrary expression or raw union field access is exposed.

`strings` copies nullable, NUL-terminated SDK byte pointers to owning nullable
BTRC strings. Null remains null, and an empty string remains a nonnull empty
string. Scanning and allocation are bounded by `maximumBytes`; a longer string
returns null. `byte-span` is mutually exclusive with `byte-plane` and preserves
an explicit integral length, including embedded NUL bytes. Negative/too-wide
lengths, null pointers with nonzero length and overflowing address ranges return
null. Zero length produces valid empty Bytes. The same owner admission covers
the guard, every read and every copy; result cleanup owns any allocated strings
or bytes if subsequent handling throws. Class/string/Bytes allocation retains
ordinary fail-fast semantics, not an invented SDK status.

For negative pitch, the SDK pointer must name the logical first row. The
adapter normalizes the copy start to the lowest-address row and preserves the
signed pitch copied by an explicit scalar field. The foreign SDK promises that
the entire resulting span is valid storage during the operation. An owner
lease alone does not prevent SDK mutation: the provider must serialize every
invalidation operation, such as FT_Load_Char, through snapshot completion.
This contract adds no raw pointer accessor, foreign allocation registry or
independent owner runtime.

### Managed reference-counted C resources

Ownership facts belong to the existing binding, not copied C signatures. The
canonical resource syntax is a named TOML subtable:

```toml
[[native.bindings]]
module = "Widgets"
header = "Widgets.h"
language = "c"
standard = "c11"
symbols = ["WidgetRef", "WidgetCreate", "WidgetRead", "WidgetRetain", "WidgetRelease"]
owned-results = ["WidgetCreate"]
borrowed-parameters = ["WidgetRead.widget"]

[native.bindings.resources.WidgetRef]
ownership = "reference-counted"
retain = "WidgetRetain"
release = "WidgetRelease"
```

Both manifests validate selected names, distinct retain/release operations,
closed fields and duplicate-free selections. Multiple resource types may share
the same lifetime functions. Resources must be SDK record-pointer typedefs;
hooks take one compatible pointer. Release returns void; retain returns void or
a compatible pointer. The importer checks the actual header, not names alone.
Contradictory SDK ownership is an error. SDK `cf_retained` results supply the
owned-result fact without an additional manifest entry.
SDK `cf_consumed` agrees with declared release but is rejected on retain;
`ns_consumed` remains invalid for C resources.

The declared semantics are: each successful owned result supplies one native
ownership claim; a borrowed parameter is valid only for the call and does not
transfer ownership; aliases retain the same native object through its declared
operation. Both native lifetime functions are reserved for generated cleanup,
including when referenced as function values. Managed values preserve native
identity; they never receive a BTRC ARC header. Generated strict-C11 adapters
convert typed carriers and guard null before calling lifetime hooks. Ordinary
BTRC fields, aliases, returns, `release` and exception cleanup use these hooks.
Each borrowed resource argument holds a native retain claim until its call
finishes, even if a reentrant callback clears the last application owner. This
also applies when a callback was registered earlier rather than passed to the
current function. Arguments unwind in reverse order through normal cleanup
slots; a returned owned resource remains protected during that teardown.
This protects object lifetime, not mutable interior storage or concurrent
unsynchronized mutation of the application's owner slot.
Unannotated resource parameters/results are not inferred safe. Nullability
remains SDK-owned; unannotated results are nullable.

**Limits:** raw casts, output slots, unowned resource globals/results and realtime
resource adapters are rejected. C one-shot callbacks can deliver resource claims
using `owned-arguments` above; other resource callback modes remain unsupported.
Transfers and executor-affine cleanup still need checked
support through this mechanism. Reference counting alone does not
prove a UI object's executor or a registration's cancellation contract; this is
not permission to migrate those providers yet. Inactive bindings remain inactive.
Use named subtables for portable manifests; the self-hosted parser does not yet
support general inline TOML tables outside its existing dependency syntax.

A reference-counted getter can declare its borrowed result's owner:

```toml
# In the binding above, select WidgetGet and borrow WidgetGet.owner as well.
[native.bindings.borrowed-results]
WidgetGet = "owner"
```

The named owner must be an explicitly borrowed reference-counted parameter and
the result must also be a declared reference-counted resource. This is a trusted
foreign lifetime promise: the returned pointer remains valid and retainable
through the native return and immediate retain while the owner's call lease is
held. It is not inferred from `cf_not_retained`, and does not cover interior
storage invalidated by mutation. The adapter retains a non-null result before
ending **any** argument lease, then transfers an ordinary owned native claim to
the caller. Normal aliases, release, and exception cleanup apply thereafter.
Null results remain null and never invoke the retain hook. `cf_not_retained` or
unspecified SDK ownership is compatible; `cf_retained`, an `owned-results`
entry, unique resources, and one-shot callback registration are rejected.
This mapping alone does not enable unmanaged globals, erased pointer casts,
or borrowing a unique resource result.

For immutable native constants, `static-globals = ["kCTFontAttributeName"]` in
the binding declares a trusted process-lifetime promise. Each selected name
must be actual read-only SDK global storage with a declared reference-counted
resource type. A generated accessor reads that storage once and acquires an
ordinary native retain claim; consumers never receive raw storage or a second
owner allocation. Constant identity is unchanged. Fields, aliases, returns,
discarded reads and exception cleanup use the same owned-value rules as native
object global reads. Nullable constants return null without retaining; an SDK
nonnull constant containing null fails the native boundary check. The manifest
does not override SDK nullability. Writable globals, unique resources, raw
pointer globals, writes, `release` of the constant storage, and taking its
address are rejected. Mutation through unrelated native aliases would violate
the declared lifetime promise; this mapping is not synchronized global storage.

Reference-counted resources with identical retain/release operations permit only
SDK-compatible pointer widening, including a mutable record pointer to its const
record pointer and a typed pointer to a selected erased resource typedef. The
reverse conversion is not inferred. Selecting `CFTypeRef` does not classify all
`const void*` positions as managed resources: scalar buffers stay ordinary pointers.
Erased SDK positions require explicit mappings in the existing binding:

```toml
[native.bindings.resource-parameters]
"CFDictionarySetValue.key" = "CFTypeRef"
"CFDictionarySetValue.value" = "CFTypeRef"
"CFDictionaryGetValue.key" = "CFTypeRef"
[native.bindings.resource-results]
CFDictionaryGetValue = "CFTypeRef"
[native.bindings.borrowed-results]
CFDictionaryGetValue = "theDict"
```

The corresponding parameter borrows and result ownership remain required. These
erased positions are trusted foreign object/type promises, checked for SDK pointer
compatibility; the header does not prove an arbitrary void pointer is a CF object.
Already typed positions, unknown positions and unique resources are rejected.

A target RC resource can additionally name `type-query = "CFGetTypeID"` and
`type-tag = "CFNumberGetTypeID"`. Both functions must be selected; the query has
one explicitly borrowed, lifecycle-compatible resource parameter, the tag has
no parameters, and both return the same integral SDK type. The existing nullable
cast `(CFNumberRef?)value` then checks this discriminator. Null input skips the
query; a mismatching kind returns null. A matching result gains an ordinary native
retain claim before the source lease ends. Reentrant release and exceptions use
the same cleanup slots as native calls. A nonnullable downcast or raw-pointer cast
is not enabled. Callers that distinguish missing data from wrong kinds check the
input for null before casting.

SDK record callback fields whose signatures expose managed resources without a
checked callable contract are private. The included SDK still owns their full
layout, alignment and size; no shortened replacement record is emitted. Borrowing
a read-only SDK callback-table constant's address preserves its exact const record
type. Hidden members cannot be read, written or called, and nonempty positional
initialization of records with hidden fields is rejected. Existing checked owned
record callback projections are unchanged.

### Unmanaged handles

A lifetime operation stays reserved across every binding of a program: no
ordinary call or function value can reach a managed resource's retain or
release, whichever binding is resolved first. Some providers still hold raw
SDK handles in plain data and release them with the same function. A Core
Foundation run-loop timer, for example, is created, invalidated and released
with `CFRelease` by the UI owner, while other bindings manage CF objects
through `CFRelease`. Declare such a handle typedef in its own binding:

```toml
[[native.bindings]]
module = "MacOS.MacOSRunLoop"
header = "RunLoop.h"
language = "c"
standard = "c11"
symbols = ["CFRunLoopTimerRef", "CFRunLoopTimerCreate", "CFRunLoopTimerInvalidate", "CFRelease"]

[native.bindings.unmanaged-handles.CFRunLoopTimerRef]
release = "CFRelease"
```

The handle must be a selected typedef of a pointer to an SDK record and must not
be a managed resource in any binding of the program. The release must be a
selected function taking one pointer and returning void. The program may then
call the release with exactly one argument whose type is that handle, with no
cast: `CFRelease(state.timer)`. Any other call, a function value, a managed
value or a cast argument fails with "'CFRelease()' may release only a declared
unmanaged handle passed directly", and the operation remains unavailable as an
ordinary declaration. A handle has one release program-wide. The compiler does
not track the handle: a double release or use after release remains the
provider's responsibility, exactly as for any raw SDK handle.

### Unique C resources

A selected SDK record-pointer typedef, record typedef, or struct tag with a void destructor can instead declare
`ownership = "unique"` and `release = "WidgetDestroy"`. A `retain` declaration is
forbidden. `owned-results` and `borrowed-parameters` remain explicit and checked
against the actual header. The native destructor is reserved, including function
references; callers cannot extract the raw pointer, construct the resource, or
inherit from its imported type.

Unnamed SDK parameters use their zero-based generated name `argumentN` in both
the projected signature and binding mappings. Underscores are appended if that
name collides with another SDK parameter's explicit name.

For a selected record typedef or tag, the managed class represents a pointer to
that actual SDK record, not a by-value copy. By-value uses of that record are
rejected. Const-qualified borrows are allowed when the SDK parameter accepts
the owner's pointer; an owned result cannot discard the record's const qualifier.

Each owned result receives one compiler-generated ordinary BTRC ARC owner,
allocated before calling the factory. Aliases retain that owner, never the SDK
resource. Null factories discard the empty owner. Fields, returns, discarded
results and exception cleanup use the existing ARC and cleanup machinery.
The generated `close()` consumes the native resource once and makes `isOpen()`
false for every alias; repeated close is harmless. Final owner cleanup closes
any still-open resource. A native borrow retains the owner and admits a borrow
under the owner mutex. Closing through any alias during an admitted borrow
aborts before native destruction. Borrowing a closed owner also aborts before
the SDK call. Per-owner synchronization serializes close: a second thread waits
for the destructor to finish, while same-thread reentrant close aborts.
`isOpen()` is a nonblocking usable-state query and returns false during closing,
including from a destructor's synchronous callback. Public close retains its
owner through callbacks and waits. No global ARC lock is held across the SDK
destructor. This protects lifetime, not SDK mutable-state thread safety.

An integral or enum status-returning destructor additionally requires both
`release-consumption = "always"` and `cleanup-status = "discard"`. Its generated
`close()` returns the exact SDK status type without narrowing. The owner caches
the result only after the destructor completes; repeated and concurrent closes
return that same result without retrying native destruction. Calling this
status-returning close on a null owner aborts rather than inventing a success
status. Automatic cleanup explicitly discards the status; this is not evidence
that the preceding operation succeeded. Use this policy only when the SDK
always consumes the resource and nonzero reports a prior operation, as with
SQLite statement finalization. Missing or conflicting policies, policies on
void destructors, and still-live/on-success consumption are rejected.

For an SDK that guarantees consumption on zero but leaves nonzero consumption
indeterminate, use `release-consumption = "success-or-indeterminate"` with
`cleanup-status = "abort"`. Close poisons the native handle before entering the
destructor, caches the exact returned status, and never retries or admits another
native operation, including after failure. Nonzero does **not** prove that the
native resource remains live. The final ordinary owner release aborts on the
cached nonzero status before freeing its storage. This is a conservative terminal
boundary, not recovery or permission to drop dependent callback storage. The
provider must retain those dependencies until a separately proven stop/drain
barrier; neither SDK consumption nor that barrier can be inferred from status
alone. Successful zero-result cleanup follows the ordinary unique-owner path.

For caller-owned SDK records, `storage = "inline"` on a unique resource selects
private, zeroed, nonmoving pointee storage. It does not expose record fields,
copying, raw pointer extraction, or a public constructor. Exactly one checked
initializer must supply its actual SDK record pointer:

```toml
[native.bindings.resources.mz_zip_archive]
ownership = "unique"
storage = "inline"
release = "mz_zip_reader_end"
release-consumption = "always"
cleanup-status = "discard"

[native.bindings.initializers.mz_zip_reader_init_mem]
resource = "mz_zip_archive"
parameter = "pZip"
result = "MinizOpenResult"
success = "minizTrue"
failure = "rolled-back"

[native.bindings.initializers.mz_zip_reader_init_mem.copied-inputs.pMem]
length = "size"
```

`success` selects an actual read-only SDK integral constant of the status type;
the header may project an SDK macro without mirroring its numeric value.
Alternatively, `success-nonzero = true` declares the SDK's nonzero success
predicate (for example, libyaml initialize/parse), without fabricating a named
header constant. Exactly one predicate is required; false, missing or both are
rejected. The status remains its exact integral SDK value.
`failure = "rolled-back"` asserts that every other status leaves no initialized
native claim requiring the destructor. This fact must come from the SDK; partially
initialized failures are not supported. The storage parameter disappears from
the BTRC call, which returns an ordinary class with `called`, exact SDK `status`,
and nullable resource `value`. **Status is meaningful only when `called` is true.**
`called = false` reports fallible backing allocation failure without fabricating
an SDK error. Ordinary result/owner allocation retains the language's existing
fail-fast behavior. Result and owner are allocated before backing/native work.

An optional single `copied-inputs` byte pointer plus unsigned length retains a
private immutable copy through SDK destruction. The parameter must also declare
`read-only-borrows`; caller storage is only borrowed while making that copy.
Null with nonzero size, sizes exceeding `SIZE_MAX`, mutable/volatile/restrict
input pointers, and additional unmodeled non-scalar parameters are rejected or fail before
the SDK call. Null with zero size remains null at the native call. Successful
initialization publishes the resource; rolled-back failure frees private backing
without calling the native destructor. Close destroys the SDK claim before
freeing its input copy and inline storage, then publishes completion to waiting
aliases. Indeterminate destruction is not supported for inline storage.
Other native resource parameters may use existing `borrowed-parameters`; their
admission spans initialization, but the returned inline owner is independent and
does not retain them. SDK initializers that store a dependency require a separate
explicit retained dependency contract and cannot claim this call-scoped borrow.

An inline owner initialized without copied input may attach one retained input
span through a selected void SDK setter:

```toml
[native.bindings.copied-inputs."yaml_parser_set_input_string.input"]
owner = "parser"
length = "size"
assignment = "once"
```

The owner parameter must declare `borrowed-parameters`, and the immutable byte
pointer must declare `read-only-borrows`. The generated BTRC call returns bool:
true means the SDK setter was called, false means private backing allocation
failed. False leaves the owner unattached and retryable. Success is write-once,
including an empty span; empty input receives stable nonnull private storage.
The SDK must retain the bytes without modifying them until its destructor.
One attachment is supported per resource, not multiple independently named
buffers. The existing unique owner's exclusive phase rejects attachment during
borrow and use/attachment during attachment; same-thread reentrant close is
rejected, while another thread's close joins attachment completion. `isOpen()`
is false during this exclusive operation. The SDK destructor runs before the
retained input and inline storage are freed.

An integral/enum-status function that writes one unique resource through a
mutable SDK output slot may declare a named owning result:

```toml
[native.bindings.owned-outputs."sqlite3_open_v2.ppDb"]
result = "SQLiteOpenResult"
```

The selected header must declare that parameter as a mutable pointer to the
selected resource pointer. It is removed from the BTRC parameter list. The
generated ordinary owning class exposes `status` with the exact SDK result type
and `value` with the nullable managed resource type. Both that class and the
empty resource owner are allocated and linked before the SDK call, and the
native output slot is zero-initialized. Every nonnull output claim is adopted,
including when status reports an error. Cleanup protects it through later
argument cleanup, discarded results, aliases, and exception unwinding.

This is an unconditional transfer contract; conditional adoption, multiple owned
outputs in one function, floating-point status, const output slots, conflicting
borrow mappings, and result-name collisions are rejected. The binding author
must establish that every nonnull returned claim is owned on every status; the
compiler does not infer transfer from success codes. No shallow managed tuple
or publicly extractable SDK output pointer is emitted. Other resource-bearing
record/output shapes and stored/completion callback combinations remain rejected.

An owning output may also project a bounded tail pointer into an integer offset:

```toml
[native.bindings.output-offsets."sqlite3_prepare_v3.pzTail"]
input = "zSql"
length = "nByte"
field = "tailOffset"
```

The mutable `const char**` output is hidden. The input must be a declared
read-only `const char*` borrow, with a signed `int` byte length. A negative length
aborts before native entry. The result starts at `-1`; only a nonnull tail whose
address is at or above the nonnull input and whose unsigned address difference
is within the length becomes an offset. Address addition and subtraction of
unrelated C pointers are never used. Invalid tails do not discard any owned
resource claim. One fresh result field is allowed; volatile/restrict storage,
colliding parameters, and wider lengths are rejected by this bounded mapping.

Borrowed SDK pointer results can instead be copied into ordinary owned values:

```toml
[native.bindings.copied-results.sqlite3_errmsg]
kind = "string"
owner = "argument0"

[native.bindings.copied-results.sqlite3_errstr]
kind = "string"
lifetime = "static"

[native.bindings.copied-results.sqlite3_column_blob]
kind = "bytes"
owner = "argument0"
length-function = "sqlite3_column_bytes"
length-arguments = ["argument0", "iCol"]
length-preserves-result = true
```

Strings require a const character pointer to NUL-terminated storage and either
a declared borrowed resource owner or explicit static lifetime. Bytes require a
borrowed resource owner, a selected non-consuming length function returning
signed `int`, and type-identical original arguments including that owner.
`length-preserves-result = true` is a trusted SDK no-invalidation promise for
that particular secondary call, not permission to call arbitrary functions on
the borrowed buffer. Pointer acquisition, length acquisition, and copying occur
under the original owner lease. Providers must also serialize any SDK operations
that could invalidate interior storage; a lifetime lease is not mutation exclusion.

The projections return nullable `string` or authenticated `Library.Bytes`.
Negative or too-wide byte counts and null pointers with nonzero length return
null; zero bytes yield a valid owned empty buffer, including a null SDK pointer.
Embedded NUL bytes are preserved. Bytes use the existing `Bytes.fromRaw` copy
and its fail-fast allocation policy. Copied values survive owner destruction.
Unknown owners, contradictory pointer qualifiers, missing length promises,
spoofed Bytes declarations, and combinations with other owning output mappings,
callbacks, selected variadic calls, or realtime calls are rejected. No raw SDK
result pointer is exposed by a copied projection.

For an SDK property API whose owned resource is written through mutable `void*`
storage and whose byte count uses an unsigned integral in/out pointer, the same
mapping can preserve the raw scalar API and expose a separate managed alias:

```toml
[native.bindings.owned-outputs."AudioObjectGetPropertyData.outData"]
result = "CoreAudioPropertyResult"
resource = "CFTypeRef"
size = "ioDataSize"
name = "copyCoreAudioProperty"
```

The resource must be explicitly selected and reference-counted. The alias omits
both storage parameters and returns an ordinary managed class with `status`,
`size`, `sizeValid`, and nullable `value`. The adapter zeroes the resource slot
and initializes the size to the actual SDK `sizeof(CFTypeRef)`, not the size of
the language's managed representation. `sizeValid` compares the returned size
against that same SDK size. The native slot is protected before entry, including
exceptions after a write, and every nonnull claim is adopted regardless of
status or size. The original SDK function remains available for ordinary scalar
properties; neither API exposes managed storage as a raw pointer.

This is a trusted foreign ownership/type promise: every nonnull output must be
a valid owned claim of the selected resource even on error or size mismatch.
The binding does not prove a selector denotes an object. Providers must restrict
the alias to their known owned-object selectors before native entry; a returned
size never grants permission to release arbitrary bytes from another property.
Aliases, result names and size/output positions must be distinct. Unsupported
size/output types, multiple outputs, callback or record projections, realtime
calls and output-offset mappings cannot be combined with this form.

### Unique C callback tables

A unique record resource whose fields are a context slot plus function
pointers can be implemented by one ordinary BTRC receiver. Declare the table
under the resource; the header remains the signature authority:

```toml
[native.bindings.resources.libstreamfile_t]
ownership = "unique"
release = "libstreamfile_close"

[native.bindings.resources.libstreamfile_t.table]
name = "openVgmstreamMemorySource"
interface = "IVgmstreamMemorySource"
context = "user_data"
context-index = 0
executor = "caller"
failure = "abort"
label = "get_name"
reopen = "open"
release = "close"

[native.bindings.resources.libstreamfile_t.table.methods]
read = "read"
size = "get_size"
```

`methods` maps BTRC method names to callback fields whose parameter at
`context-index` is the unqualified `void*` context; the remaining arguments
must be SDK scalars or POD data pointers and the result a scalar or void. The
imported interface exposes those methods without the context (`int read(uint8_t*
argument0, int64_t argument1, int argument2)`, `int64_t size()`), and the
generated factory `libstreamfile_t name(IVgmstreamMemorySource receiver, string
label)` returns the ordinary unique owner: `close()`, `isOpen()`, aliases,
borrows and final cleanup behave exactly as for any other unique resource, and
the SDK release function still runs the table's own `release` callback.

Every field of the SDK record must be mapped exactly once. `label` names a
`const char* (*)(void*)` field answered with the factory's copied `label`
string; it is borrowed from the table holder, never from the BTRC string.
`reopen` names a `struct T* (*)(void*, const char*)` field: the generated
adapter returns a fresh table sharing the same receiver when the requested name
equals the label and null for any other name, so an SDK may reopen its own
input without provider code. `release` names the `void (*)(struct T*)` field
that frees one table. `reopen` requires `label`.

The receiver is retained by a generated holder with one claim per live table:
the original returned to BTRC and every SDK reopen clone. Closing the BTRC
owner releases only its table; the receiver is released after the last table
closes, so an SDK that keeps its reopened stream alive keeps the BTRC receiver
alive until the SDK itself releases it. Callbacks and releases are checked
against the creating thread and abort otherwise; a BTRC exception inside a
method runs its local cleanup and terminates at the boundary. `executor`
currently requires `caller` and `failure` requires `abort`. Method names cannot
shadow `close`/`isOpen`, the factory and interface names must not collide with
selected symbols, and inline-storage or reference-counted resources are
rejected. No userdata, function pointer or table layout reaches provider code.

### SDK-owned dispatch tables

The opposite direction of a callback table: the SDK object owns a table of
function pointers, and BTRC calls through it. Declare `dispatch` under a unique
pointer resource over a complete SDK struct; the header remains the signature
authority (interop step 2 in
[native-interop-ownership.md](../../docs/design/native-interop-ownership.md)).

```toml
[native.bindings.resources.Codec]
ownership = "unique"

[native.bindings.resources.Codec.dispatch]
table = "vtbl"            # object field holding the table pointer
context-index = 0         # slot parameter that receives the object
executor = "caller"
failure = "abort"
release = "destroy"       # optional slot; replaces the top-level release

[native.bindings.resources.Codec.dispatch.methods]
decode = "decode"
reset = "reset"
```

Each mapped slot becomes a public method of the resource, without the
parameter at `context-index` (`int decode(uint8_t* input, int length)`);
parameter names come from the slot's own declaration. Without `context`, that
parameter must be a pointer to the object itself; `context = "field"` passes
the named object field instead, which must be an unqualified `void*`. The
remaining arguments must be SDK scalars or POD data pointers and the result a
scalar or void.

Every call borrows the unique owner, reloads the table pointer and the slot,
aborts with a diagnostic when either is null, calls, and ends the borrow. The
object owns its table: BTRC never copies, caches, retains or frees the table or
a slot, so a table the SDK swaps between calls is honored on the next call.
Calling on a closed owner aborts before the SDK runs, and closing through any
alias during the call aborts, exactly as for every unique resource.

`release` names a `void (*)(T*)` slot that final owner cleanup runs exactly
once, through the same reload and null check; it cannot be combined with the
resource's top-level `release` or `consume` keys. A resource either implements
a table (`table`) or dispatches through one (`dispatch`). `executor` currently
requires `caller` and `failure` requires `abort`; method names cannot shadow
`close`/`isOpen`, and each slot is mapped at most once. The reader reads each
slot's layout by record path, so the table record need not be exported.

### COM interfaces

A COM interface is a resource with `ownership = "com"` on a selected record
typedef (`typedef struct IStream IStream;` represents `IStream*`). Its
lifetime hooks are slots of its own table: AddRef and Release are slots 1 and
2 of `lpVtbl` (interop step 5 in
[native-interop-ownership.md](../../docs/design/native-interop-ownership.md)).
Programs with COM resources import `Library.COM.COMApartment`.

```toml
[native.bindings.resources.ICounter]
ownership = "com"
iid = "IID_ICounter"          # selected read-only IID global
base = "IBaseCounter"         # optional: another com resource of the binding
release-executor = "apartment"

[native.bindings.resources.ICounter.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.ICounter.dispatch.methods]
add = "Add"
clone = "Clone"
split = "Split"

[native.bindings.status-results]
"ICounter.add" = "hresult"
"ICounter.clone" = "hresult"

[native.bindings.owned-outputs."ICounter.split.part"]
result = "CounterSplit"
status = "hresult"
```

The importer checks the real layout. The record's first field must be
`lpVtbl`, a pointer to a complete table whose slots 0 to 2 are
`QueryInterface(This, REFIID, void**)` returning a 32-bit signed HRESULT, then
`AddRef(This)` and `Release(This)` returning a 32-bit unsigned ULONG, all with
the C convention. `iid` must be a read-only global of the record that
QueryInterface's REFIID points to. A `base` table must be a slot-by-slot
prefix whose signatures equal the interface's own except for `This`; the
interface then widens to its base, and to the base's bases, without a call.
A resource with `ownership = "com"` takes no `retain`, `release`, `type-query`,
`storage` or `table`, and `release-executor` is required and currently
`apartment`, which only COM resources accept.

Every BTRC value of the interface is the SDK's own pointer and holds one
claim, ended by exactly one Release through that pointer. An `owned-results`
factory, an `[out]` interface and a successful QueryInterface each hand over
one claim; an alias takes its own claim with AddRef; the returned counts are
discarded. Each AddRef, Release, QueryInterface and method call reloads the
table and the slot, aborts when either is null, and first checks that it runs
on the apartment's thread. `Library.COM` counts every claim, so
`COMApartment.uninitialize()` with a claim still live terminates.

`dispatch` maps methods as for C tables, with `table = "lpVtbl"`,
`executor = "apartment"` and the object passed first; `context`, a nonzero
`context-index`, `release` and the three IUnknown slots cannot be mapped, and
no method may be named `sameObject`. Each call holds a claim on the receiver
and on every `[in]` interface argument for the call. An `[out]` `IFoo**`
parameter is hidden and adopted on every HRESULT, under one of two status
forms, and a method uses at most one of them and one such output:

- `status-results."<R>.<method>" = "hresult"` makes a negative HRESULT release
  the adopted output and throw `COM <R>.<method> failed with HRESULT
  0x80004005`; otherwise the method returns the output, or the nonnegative
  HRESULT when it has none.
- `owned-outputs."<R>.<method>.<parameter>"` with `status = "hresult"` returns
  the result class (`status`, nullable `value`), as for C functions. A C
  factory such as `HRESULT CounterOpen(int32_t, ICounter**)` uses the same form
  under its two-part name, and a COM output requires `status = "hresult"`.

Both forms require a 32-bit signed result. An `[out]` interface without either
form, a second `[out]` interface, and both forms on one method are rejected.

`(IFoo?)value` between two COM interfaces asks the source's own table for
`IID_IFoo` (M3): success is one new claim, `E_NOINTERFACE` gives null, and any
other failure terminates, adopting first any interface a failed query still
wrote. A cast to a declared base is the static widening. `==` stays pointer
equality; when the binding also selects `IID_IUnknown`, every COM resource
gains the class method `sameObject(first, second)`, which compares the two
objects' IUnknown identities and releases both identity claims. IIDs are
linked from `uuid` on Windows; on other hosts the program defines them.

A dispatched method's `[out]` UTF-16 string is copied into a BTRC string and
freed inside the adapter (`copied-outputs`). The slot's parameter must be a
mutable pointer to a mutable pointer to 16-bit unsigned units (`BSTR*`,
`LPOLESTR*`), and the method takes the `status-results` form:

```toml
[native.bindings.status-results]
"ICounter.name" = "hresult"

[native.bindings.copied-outputs."ICounter.name.name"]
encoding = "utf-16"
free = "SysFreeString"     # a BSTR; "CoTaskMemFree" for a CoTaskMemAlloc string
```

The method returns `string?`: null when the slot left its output null, else
the UTF-8 copy (unpaired surrogates become U+FFFD). A BSTR's length is its
prefix, a task-allocated string ends at U+0000, and a BSTR holding U+0000
frees the string and throws `COM ICounter.name returned a string holding
U+0000, which a BTRC string cannot hold`. A negative HRESULT frees any string
the slot still wrote, then throws as for any status-results method. `free`
must be `SysFreeString` (taking the BSTR) or `CoTaskMemFree` (taking a
mutable `void*`), selected and returning void; encoding is `utf-16`; a method
copies at most one output and adopts no `[out]` interface beside it.

A COM sink lets the source of a connection point call a BTRC handler
(`com-sinks`, native-interop-ownership.md section 2.4). The table key names
a selected `ownership = "com"` resource, whose IID, bases and table the sink
reuses:

```toml
[native.bindings.com-sinks.ICounterEvents]
name = "makeCounterEvents"            # the factory
interface = "ICounterEventsHandler"   # the BTRC handler interface
register = "ICounter.advise"          # the source's Advise(sink, cookie*)
unregister = "ICounter.unadvise"      # the source's Unadvise(cookie)
executor = "apartment"
failure = "abort"
activation-failure = "unpublished"    # or "abort"
cancellation = "entry-barrier"
```

Every slot after IUnknown's becomes a method of the handler interface, named
by the slot with a lowercase first letter (`Changed` is `changed`), with the
slot's arguments after `This`, which must be SDK scalars or POD data pointers,
and a 32-bit signed HRESULT result. Import `Library.Callback`. The factory is
`CallbackContext<ICounterEventsHandler, ...> makeCounterEvents(ICounter
source, ICounterEventsHandler receiver, CallbackScope scope)`: it allocates
the sink, Advises it on the source and returns the registration, an
`ICallbackRegistration`. `register` must take one `[in]` interface that the
sink widens to (its own resource or a base, such as `IUnknown*`) and a
pointer to a mutable integer cookie; `unregister` takes that cookie's type;
both return an HRESULT and name methods of one dispatching resource.

The generated sink is `{ lpVtbl, comCount, state, context, thread,
registered }` with one static const table. QueryInterface answers
IID_IUnknown (which the binding must select), the sink's IID and its bases'
by `memcmp`, and anything else with `E_NOINTERFACE` and a null output. While
its COM count is positive the sink holds one external claim on the
registration's CallbackContext. Each event pins the sink (one AddRef) and
enters the context, so a handler may cancel its scope, and so Unadvise,
inside the event; after cancellation an event returns `S_OK` without entering
BTRC, so a source that keeps the sink pointer pins only the sink and its
context. At zero the sink is dead before anything is released, releases its
claim, and frees itself once its registration has ended; until then an
AddRef, QueryInterface or Release on the dead sink terminates (`Native COM
sink ICounterEvents.AddRef: the holder is dead`). Every entry checks the
apartment's thread (`... called off its apartment thread`; `... Release:
foreign holder released on the wrong thread`). The registration holds one
claim on the source and the cookie: cancellation marks the sink cancelled,
calls Unadvise (a dead sink counts as unregistered), drains, then releases
the receiver; the registration's end releases the source. A failed Advise
follows `activation-failure`: `unpublished` releases everything and throws
`COM sink ICounterEvents: ICounter.advise failed with HRESULT 0x80004005`,
`abort` terminates with that message. `COMApartment.liveSinks()` counts the
sinks not yet freed.

Rejected: a key that is not a com resource of the binding; a factory or
interface name equal to a selected symbol or another sink's; two sinks with
one IID, or a chain naming an IID twice; a sink slot named like an IUnknown
method (`release`); a sink slot that does not return an HRESULT; and, for COM
methods and for C functions of a binding with COM resources, a `pUnkOuter`
parameter: aggregation is not supported, so it must be hidden or null (bind
such a call through a C helper that passes NULL).

`Library.COM` declares `ole32`, `uuid` and `oleaut32` for Windows as link
records, so a program with COM resources links them through its plan.

Not yet supported: `status-results` on C functions, `copied-outputs` on C
functions, and the compile-time ban on capturing a COM resource in `spawn`; a
COM call on another thread terminates at run time instead. Free-threaded (MTA)
sinks are deferred.

### Opaque C++ owners

A `language = "c++"` binding publishes SDK classes as opaque owners and
owner-bound views; no C++ object, exception or standard-library type reaches
generated C. Select the classes, the by-value result record, the constants and
the factory method, then describe each lifetime:

```toml
[[native.bindings]]
module = "PugiLibrary"
header = "native/PugiImports.h"
language = "c++"
standard = "c++17"
symbols = ["pugi::xml_document", "pugi::xml_node", "pugi::xml_parse_result", "pugi::status_ok", "pugi::parse_default", "pugi::encoding_utf8", "pugi::node_element", "pugi::xml_document::load_buffer"]
owned-records = ["pugi::xml_parse_result"]
read-only-borrows = ["pugi::xml_document::load_buffer.contents"]

[native.bindings.resources."pugi::xml_document"]
name = "PugiDocument"
ownership = "unique"
constructor = "default"
release = "delete"
methods = ["document_element"]

[native.bindings.resources."pugi::xml_node"]
name = "PugiNode"
ownership = "owner-bound-value"
owner = "pugi::xml_document"
methods = ["empty", "type", "name", "child_value()", "first_child", "next_sibling()"]

[native.bindings.initializers."pugi::xml_document::load_buffer"]
resource = "pugi::xml_document"
result = "PugiParseOutcome"
success = "pugi::status_ok"
status-field = "status"
failure = "destroy"

[native.bindings.copied-results."pugi::xml_node::name"]
kind = "string"
owner = "self"
```

A `unique` class requires an accessible public default constructor and a
public destructor; `constructor = "default"` and `release = "delete"` are the
only lifetimes. It is published under `name` as the ordinary unique owner
(`close()`, `isOpen()`, aliases, borrows, final cleanup) and every unique class
needs exactly one checked factory. The factory (`initializers`) is a non-const
method whose by-value result is a selected trivially copyable `owned-records`
record with public scalar fields; it becomes a class factory
`PugiParseOutcome PugiDocument.load_buffer(const void* contents, size_t size,
unsigned int options, xml_encoding encoding)`. The outcome carries `called`,
the copied `status` record (`PugiParseOutcomeStatus`, one field per SDK field)
and the nullable `value` owner, which is present only when the record's
`status-field` equals the selected `success` constant of exactly that field's
enum; `failure = "destroy"` deletes the object otherwise. Pointer parameters
must be `const void*`/`const char*`/`const unsigned char*` and listed in
`read-only-borrows`; other parameters are SDK scalars.

An `owner-bound-value` class must be trivially copyable and destructible and
names its unique `owner`. It is published as an ordinary managed class whose
instances copy one SDK value and hold one claim on the root owner; a method
returning the SDK class returns such a view of the same owner. Every selected
method other than the factory must be `const` and non-variadic with
non-consuming parameters. Zero-argument overloads are selected with the
explicit `()` suffix. `const char*` results require a `copied-results` entry
with `kind = "string"` and `owner = "self"`: the string is copied while the
owner is borrowed, so a view never lends SDK memory. Scalar results and
parameters project like Objective-C scalars, and selected scoped constants are
visible with `::` replaced by `_` (`pugi_status_ok`).

Each method crosses one generated `extern "C"` adapter in a C++ unit of the link
plan (`generated-units`, `raii`), compiled with `-fexceptions`; the strict C
wrapper borrows the root owner around the call, so use after `close()` through
any view aborts before the SDK sees the object, and a C++ exception becomes an
ordinary BTRC exception after the borrow ends. The delete adapter aborts on a
throwing destructor. The header reader sees the same C++ standard library as
the adapter toolchain: it probes the Clang driver named by `BTRC_NATIVE_CXX`
(default `clang++`) for its include search list, so that driver must pair with
`BTRC_NATIVE_SYSROOT`. Callbacks, record snapshots, string views, variadic
calls and template instantiations are not available for C++ bindings.

### Java bindings

A `language = "java"` binding selects Java classes and members from class
files and calls them through checked JNI adapters
([native-interop-ownership.md](../../docs/design/native-interop-ownership.md)
section 2.3). It has no `header` and no `standard`; either key fails with "Java
bindings take no header or standard", and Java never becomes a source-unit
language. The binding takes only `module`, `language`, `symbols` and the
`os`/`arch`/`env` predicates. Each symbol is a class by its dotted binary name,
a method or constructor by its JNI descriptor, or a field by its type
descriptor, so an overload is never guessed:

```toml
[[native.bindings]]
module = "Fixture"
language = "java"
symbols = ["dev.btrc.fixture.JniHost",
           "dev.btrc.fixture.JniHost.<init>(I)V",
           "dev.btrc.fixture.JniHost.twice(I)I",
           "dev.btrc.fixture.JniHost.add(Ldev/btrc/fixture/JniHost;)Ldev/btrc/fixture/JniHost;",
           "dev.btrc.fixture.JniHost.echo(Ljava/lang/String;)Ljava/lang/String;",
           "dev.btrc.fixture.JniHost.LIMIT:I",
           "dev.btrc.fixture.JniHost.count:I"]
```

Any other symbol fails with "symbols must name Java classes, or members by JNI
descriptor". The program must import `Library.Java.JavaVirtualMachine`, whose
JNI.h binding every generated adapter calls through ("Java bindings require
import Library.Java.JavaVirtualMachine"). Both compilers run the Java class
reader named by `BTRC_JAVA_CLASS_READER` once per binding, with
`--target=<the build target's triple>` and the classpath in
`BTRC_JAVA_CLASSPATH` (each is required: "Java bindings require
BTRC_JAVA_CLASS_READER", "Java bindings require BTRC_JAVA_CLASSPATH"). The
reader never goes through the header session or its cache; its identity and
document join the resolution fingerprint, so a C-only program's fingerprint is
unchanged. The reader's own failures name the symbol, for example
`JavaClassReader: unknown member dev.btrc.fixture.JniHost.toString()Ljava/lang/String;`.

Projection:

- A class the binding names, or that owns a selected member, becomes an
  abstract BTRC class named by its simple name: a unique owner of one JNI
  global reference with `close()` and `isOpen()`, aliases, borrows and final
  cleanup exactly as for [unique C resources](#unique-c-resources). Releasing
  the owner deletes the global reference on the releasing thread (attaching it
  as a daemon if needed) and lowers `JavaVirtualMachine.liveClaims()`.
- A constructor is the class method `create(...)`, returning the class; an
  abstract class or interface has none. A static method is a class method and
  an instance method a public method, under the Java name. A field is a getter
  named for it plus `set<Field>(value)` unless it is final; a static field's
  accessors are class methods. Parameters are named `argument0`, `argument1`,
  and so on.
- `Z`, `B`, `C`, `S`, `I`, `J`, `F`, `D` and `V` are `bool`, `signed char`,
  `unsigned short`, `short`, `int`, `long long`, `float`, `double` and `void`.
  `java.lang.String` is `string?` both ways: text copies through UTF-16, a
  null Java string is `null`, and a Java string holding U+0000 throws "Java
  string contains U+0000, which a BTRC string cannot hold". A selected class
  `T` is a borrowed `T?` argument and an owned `T?` result, and so is a
  primitive array (`[I` is `JavaIntArray?`, below).

Rejected at compile time, with identical diagnostics in both compilers: a type
of a class no Java binding selects ("Java member M uses unselected class C"),
arrays of objects or of arrays ("Java arrays of objects or arrays are not
projected yet: M"), nested classes ("Java nested classes are not projected
yet: C"), two classes with one simple name, a class selected by two bindings,
two members projecting to one BTRC name, including `close` and `isOpen`
("Java members A and B project to the same BTRC name n"), and a generated
class whose name a selected class already has ("Java class C and [I project
to the same BTRC name JavaIntArray").

Every adapter brackets its JNI calls with a checked `PushLocalFrame`; checks
`ExceptionCheck` immediately after every JNI call that can throw; turns a
pending Java exception into the BTRC exception string `"JavaException:
<Throwable.toString()>"` after popping the frame and ending its borrows; and
registers a new result owner in a cleanup slot before `NewGlobalRef`. Adapters
call JNI function-table slots by their JNI-spec names (`CallIntMethodA`) through
the thread's `JNIEnv`, so the C compiler checks each against `jni.h`; only the
`...A` (`jvalue*`) call variants are used. Class references and member IDs are
cached per adapter in Library.Java. In a VM a library adopted at JNI_OnLoad,
classes resolve through the application ClassLoader cached there (the context
class loader of the JNI_OnLoad thread), never FindClass on an attached thread.
No adapter enters a critical region: verifier rule 2 rejects
`GetPrimitiveArrayCritical`, `GetStringCritical` and their releases. Nested
classes come with the Java class reader's v2.

#### Java primitive arrays

A primitive array is a Java object, so it crosses as an owner of one global
reference: each element kind a selected member, field or native uses gets a
generated abstract class, `JavaBooleanArray`, `JavaByteArray`,
`JavaCharArray`, `JavaShortArray`, `JavaIntArray`, `JavaLongArray`,
`JavaFloatArray` or `JavaDoubleArray`, a unique owner exactly like a selected
class (`close()`, `isOpen()`, `liveClaims()`). A `[I` parameter is a borrowed
`JavaIntArray?` and a `[I` result or field an owned one; Java's changes to the
array are visible through the owner. Its members copy through the region
functions (native-interop-ownership.md section 2.3, "Arrays"):

```btrc
const int values[4] = {1, 2, 3, 4};
JavaIntArray made = JavaIntArray.create(Span(values)); // New<X>Array + Set<X>ArrayRegion
int count = made.length();                              // GetArrayLength
int back[4] = {0, 0, 0, 0};
made.read(0, Span(back));                               // Get<X>ArrayRegion from start 0
made.write(1, Span(values));                            // Set<X>ArrayRegion from start 1
```

An empty span copies nothing, a span longer than 2147483647 elements throws
before any JNI call, and a region outside the array is Java's
`ArrayIndexOutOfBoundsException`, thrown as `JavaException: ...`.

#### Java class options

A binding's `classes` table carries options for a class it selects, keyed by
the class's BTRC name:

```toml
[native.bindings.classes.JniHost]
weak = true          # generates JavaWeakJniHost
[native.bindings.classes.JniMain]
executor = "main"    # every call checks the main Looper's thread
```

- `weak = true` generates `JavaWeak<Class>`, spelled `JavaWeak` and the class's
  BTRC name (`JavaWeakJniHost`): a unique owner of one weak global reference.
  `JavaWeakJniHost.create(JniHost referent)` takes `NewWeakGlobalRef` of a
  live owner; `get()` returns `JniHost?`, a new owner of a new global
  reference (`NewLocalRef`, a null check, then `NewGlobalRef`), or `null` once
  the collector has reclaimed the object. `close()` and final cleanup delete
  the weak reference exactly once; `JavaVirtualMachine.liveWeaks()` counts
  them, and shutting a created VM down with one alive terminates.
- `executor = "main"` makes every adapter of the class (constructors, methods
  and fields) check that it runs on the main thread, the thread of
  `android.os.Looper.getMainLooper()`, which Library.Java reads once through
  its own checked JNI and caches; another thread terminates (`Java call
  JniMain.title: called off the main thread`), and so does the first check in
  a VM with no main Looper (`Library.Java: the main thread is not established:
  this Java VM has no main Looper ...`), such as a host JVM. Releasing an owner
  stays legal on any thread: `DeleteGlobalRef` is thread-safe, so the
  release executor is `any`.

Rejected, with identical diagnostics in both compilers: a key that is not a
selected class (`classes requires a Java class the binding selects`), an
unknown field, a table with neither key (`requires executor or weak`), an
executor other than `main` (`executor requires main`), a `weak` that is not a
boolean (`weak must be true or false`), and a weak class whose name a
selected class or a natives factory or interface already has (`the weak
reference class JavaWeakJniHost must be distinct from selected classes and
natives`).

#### Java natives

A `natives` table lets Java call BTRC: it binds a selected class's `native`
methods, by name and JNI descriptor, to a generated BTRC receiver interface
through RegisterNatives (native-interop-ownership.md section 2.3, "Java ->
btrc"). The table key is the class's BTRC name; the class must be selected in
`symbols`:

```toml
[native.bindings.natives.JniCallbacks]
name = "registerJniCallbacks"      # the factory
interface = "IJniCallbacks"        # the generated receiver interface
methods = ["compute(I)I", "greet(Ljava/lang/String;)Ljava/lang/String;", "scale(I)I"]
executor = "caller"                # or "main"
failure = "throw"                  # or "abort"
cancellation = "entry-barrier"
writable-arrays = ["fill([II)V.argument0"]   # optional
```

Each method becomes the interface method of its Java name. Parameters and
results project as for calls into Java: primitives as above, `string?` copied
through UTF-16, and a selected class `T` or a primitive array result as an
owned `T?` (a new global reference for each argument, released after the call
unless the receiver keeps it; a returned owner becomes a new local reference).
A primitive array parameter is a borrowed span of the Java array's elements
for the call (`Get<X>ArrayElements`): `Span<const int>`, released with
`JNI_ABORT`, or, when `writable-arrays` names it as `<method>.argument<N>`,
`Span<int>`, released with mode 0 so the receiver's stores reach the array
once the receiver ran (`JNI_ABORT` when the call never entered BTRC). A null
array raises `java.lang.NullPointerException` (`...: argument0 is null`)
without entering BTRC. An instance native's object reaches the receiver
first, as the parameter `T instance`.
Import `Library.Callback`. The factory is `CallbackContext<IJniCallbacks, ...>
registerJniCallbacks(IJniCallbacks receiver, CallbackScope scope)`: it binds
every native to its generated thunk and returns the registration, an
`ICallbackRegistration`; a second registration of the class while one lives
throws `Java natives dev.btrc.fixture.JniCallbacks are already registered`.
A selected method that is also listed in `symbols` stays callable from BTRC.

Every thunk runs over one M2 holder per class, which holds the registration's
one external claim on its CallbackContext while it is pinned. A call pins the
holder, makes the JNIEnv Java called with the thread's for the call (and
restores the previous one after, so calls nest: Java -> BTRC -> Java -> BTRC),
frames its local references, converts its arguments (a JNI failure returns to
Java with its exception pending), enters the receiver through the context's
caller-executor gate and converts the result. A call on a thread other than
the registering one terminates (`Java natives
dev.btrc.fixture.JniCallbacks.compute(I)I: called off its executor thread`).
With `executor = "main"` the factory itself checks the main Looper's thread
(`Java natives dev.btrc.fixture.JniMain: called off the main thread`), so the
registering thread, and every call's, is the main one; a native the main
Looper dispatches from a posted message runs there. A
Java string holding U+0000 raises `java.lang.IllegalArgumentException` without
entering BTRC. A BTRC exception escaping the receiver runs its cleanups, then
with `failure = "throw"` is raised in Java as `java.lang.RuntimeException`
carrying its message (copied through UTF-16, as ThrowNew would but without
modified UTF-8), and the native returns zero; with `failure = "abort"` it
terminates (`BTRC native callback failed: ...`).

Cancellation is the entry barrier: it marks the holder cancelled and clears
the class's live slot, so no later call enters BTRC. The natives stay bound to
their thunks, which then raise `java.lang.IllegalStateException: Java natives
dev.btrc.fixture.JniCallbacks are not registered` and return zero; that is the
stub a later registration rebinds, so UnregisterNatives is never called. A
receiver may cancel its own registration inside a call: the call keeps the
holder pinned, cancellation completes once it has left, and the holder
releases its claim at its last unpin, which is the holder's final event: a
last unpin on a thread other than the registering one terminates (`Java
natives C: foreign holder released on the wrong thread`); Library.Callback
already refuses a cancellation off the context's creating thread, so no
program reaches it. `JavaVirtualMachine.liveNatives()` counts the holders not
yet freed.

Rejected, with identical diagnostics in both compilers: a key that is not a
selected class (`natives requires a Java class the binding selects`); unknown
or missing fields; a method that is not `<name>(<descriptors>)<result>`, or a
constructor; a method listed twice (`registers compute(I)I twice`); a factory
or interface name equal to another, to a selected class or to another
registration's; an executor other than `caller` or `main`, a failure other
than `throw` or `abort`, a cancellation other than `entry-barrier`; a
`writable-arrays` entry that is not `<method>.argument<N>` of a listed method
(`writable-arrays must name array parameters of its methods as
<method>.argument<N>`), a duplicate one, or one naming a parameter that is not
a primitive array (`Java natives C.fill([II)V: argument1 is not a primitive
array parameter, so writable-arrays cannot name it`); a method that is not
`ACC_NATIVE` (`Java RegisterNatives target dev.btrc.fixture.JniCallbacks.plain(I)I
is not ACC_NATIVE`); a descriptor the class does not declare (the reader's
`unknown member`), which is how a signature mismatch surfaces; an array of
objects or arrays, or an unselected class type; and two natives of one name
(`Java natives A and B project to the same BTRC name compute`). The reader
reports public members only, so a private `native` method waits for reader
v2.

### Selected C variadic calls

An SDK variadic function may expose one fixed, typed call shape. Bind its actual
integral selector parameter to a selected read-only SDK constant and declare the
otherwise-untyped tail:

```toml
[native.bindings.variadic-calls."sqlite3_db_config.op"]
value = "sqliteNativeDefensiveOption"
arguments = ["int", "int*"]
```

Here BTRC calls `sqlite3_db_config(database, enabled, &current)`. The generated
adapter inserts the SDK constant and holds ordinary resource leases across the
call. Function values expose the same fixed signature. The included header
remains authoritative for the fixed parameters, result, calling convention and
actual symbol; no replacement declaration is generated.

The selector and constant must have the same promoted integral SDK type. Tail
arguments allow promoted scalar values and single-level scalar pointers only;
unpromoted `float`/small integers, managed values, arbitrary pointers and open
varargs forwarding are rejected. A binding explicitly promises that this opcode
uses precisely that tail signature; headers cannot prove a varargs convention.
Only C and one shape per selected function are supported. Callback, realtime,
owned-result/output and record-output combinations are rejected. An unselected
variadic function remains an error, not an unchecked escape hatch.

A table keyed by the bare function name is a whole-function shape. It keeps
every fixed parameter, selector included, visible and fixes one tail for every
call, so it takes only `arguments`:

```toml
[native.bindings.variadic-calls.fcntl]
arguments = ["int"]
```

BTRC then calls `fcntl(descriptor, F_SETFL, flags | O_NONBLOCK)` as a
three-argument function: arity and every argument are checked against the fixed
parameters and the declared tail, the adapter passes them to the SDK prototype,
and a function value has the same signature. The binding promises that every
selector the program passes reads exactly that tail (true of `fcntl`'s integer
commands, not of `F_GETLK`, which reads a pointer); a function with
selector-dependent tails needs a selector shape instead. The tail rules and the
rejected combinations are the selector shape's, and a function takes either a
whole-function shape or one selector shape, never both.

### GNU transparent-union parameters

A C parameter whose type is a GNU transparent union (glibc's
`__CONST_SOCKADDR_ARG` and `__SOCKADDR_ARG` under `_GNU_SOURCE`, for `connect`,
`bind`, `accept` and their neighbours) is passed with its first member's calling
convention, and C converts any member type at the call. The header reader marks
such a record `transparent_union`, and the importer projects the parameter as
that first member: `connect` takes `const sockaddr*` on Linux exactly as on
macOS, where the SDK spells it that way. Calls and function values go through a
generated adapter whose parameter is the member type, so the SDK prototype owns
the conversion. C11 forbids converting an argument to a union, and compilers
waive that only for a union a system header declares, as SDK headers do.
Callback, borrow, resource, owned- or copied-result, record-output and realtime
combinations are rejected; every other by-value union remains refused.

A tagged record imported under its tag also answers to its C spelling:
`struct sockaddr` and `struct pollfd` name the imported `sockaddr` and `pollfd`
(the analyzers enter `struct X` or `union X` in the typedef alias index), so C
spellings in BTRC code and hosted declarations of the same tag cannot become a
second, incompatible type. A tag written with the other keyword stays a distinct
foreign tag.

### Realtime native functions

The optional `realtime-safe` array names exact selected functions, for example
`realtime-safe = ["AudioUnitRender"]`. This is a trusted, target-specific package
assertion that the configured foreign implementation is bounded and performs no
allocation, blocking, locking, logging, managed ownership or other forbidden
realtime effects. Review the API and its required setup before declaring it;
headers alone cannot prove an implementation's behavior. It does not certify
every possible audio-unit/plugin implementation reachable through a handle.

Both analyzers attach the assertion to the actual imported declaration. Unknown
names, non-functions, duplicates and malformed arrays fail. Unannotated calls and
ordinary erased function pointers remain unproven. BTRC wrappers still undergo
transitive effect analysis; known forbidden effects cannot be overridden. The structured-IR verifier checks their generated
adapters too. Nullability guards on a certified call trap without logging or
unwinding; non-realtime adapters retain their diagnostic. No callback, allocation
or resource lifetime promise is implied by this setting.

### Registration-owned realtime C callbacks

The existing callback table can project a selected SDK callback record into a
stored realtime registration. Its owner is a declared unique native resource;
the record layout, callback signature, owner parameter and size parameter are
checked against the selected header. For example:

```toml
[native.bindings.callbacks."AudioUnitSetProperty.inData"]
name = "installCoreAudioRender"
record = "AURenderCallbackStruct"
field = "inputProc"
context = "inputProcRefCon"
context-index = 0
size = "inDataSize"
interface = "ICoreAudioRender"
invocation = "CoreAudioRenderInvocation"
lifetime = "stored"
executor = "realtime"
failure = "abort"
owner = "inUnit"
unregister = "AudioOutputUnitStop"
cancellation = "entry-barrier"
activation-failure = "abort"
[native.bindings.callbacks."AudioUnitSetProperty.inData".operations]
input = "AudioUnitRender.inUnit"
```

The alias keeps the original scalar arguments and owner, replacing the record
and size with a typed receiver, an exact stateless `RealtimeFunction` fallback,
and a `CallbackScope`. It returns `CallbackState`. The original scalar SDK
function remains available for other properties. The selected unregister and
operation functions are reserved to this projection, not exported as raw owner
operations. Callback and context fields are private in the imported record.

The receiver's `@realtime invoke` method receives an invocation-local capability
followed by the real SDK POD arguments, excluding the context argument. This
capability has only the declared operations: no constructor, handle field,
address, cast, owned alias, return, capture or storage. Exact capability
parameters may forward only through statically proven realtime helpers; their
bodies must preserve the same non-escape rule. Operations require explicit
`realtime-safe` declarations and ABI-compatible borrowed owner parameters.

Registration acquires one stable unique-owner lease and retains the receiver
off the realtime thread. It resolves interface dispatch before publication.
Admitted callbacks use the existing atomic gate and a stack capability, with
no allocation, retain/release, locks or interface lookup. Denied entries call
only the stateless POD fallback, without the receiver, context or capability.

`entry-barrier` is a trusted foreign lifetime promise: successful unregister
prevents every new native entry; already admitted calls may still be running.
The registration releases its receiver and owner lease only after those calls
drain. The header cannot prove that promise, nor that the selected operations
are realtime-safe. Failed unregister is terminal and never retried: admission
stays closed, the fallback remains valid for late entry, and dependent storage
is retained. Final owner cleanup fails closed. Nonzero installation status
aborts because possible publication cannot safely be inferred from an error.

### Native callback fields

Imported record fields may receive BTRC C-compatible callbacks whose raw pointer
parameters accept the SDK's incoming arguments. Non-null input promises are
retained on the field rather than projected into an unchecked callable value.
This supports real `AURenderCallbackStruct` registration without mirroring its
layout or writing a C bridge. The registering owner must keep callback context
alive until the SDK's unregister/drain barrier completes.

Reading, invoking, taking the address of, or exporting a field with those
preconditions currently fails: it needs a checked indirect-call adapter. Record
copies retain the restriction. Fields promising non-null callback results also
remain unsupported until assignment can establish that outgoing guarantee.
Nullable callback arguments retain the ordinary raw-pointer value domain and
ABI. No realtime, ownership, or foreign-thread runtime-entry proof is implied.

## Recursive graph and lockfile

Resolution walks dependency manifests recursively with an explicit visiting
stack.  Cycles report their package path.  The graph is deterministic and a
diamond dependency contributes one package and one set of native inputs.

Schema-3 `btrc.lock` records the complete resolved graph, each package's local
alias map, portable path edges, and exact Git commits.  It is canonical UTF-8
JSON with sorted keys and no insignificant whitespace.  Publication is an
atomic same-directory replacement.  A stale graph is rebuilt from manifests;
a malformed or future lockfile fails closed. Package manifest stamps hash the
exact validated UTF-8 manifest bytes, so either compiler detects every source
change without depending on a TOML serializer's formatting choices.

## Native link-plan schemas

The compiler result owns the validated native plan.  `--emit-link-plan PATH`
writes its canonical JSON representation while normal C emission continues.
`--target OS-ARCH[-ENV]` selects one row of `src/language/targets.toml`, which
then selects platform predicates; accepted aliases are `x64` for `x86_64` and
`arm64` for `aarch64`. Without `--target`, both compilers infer the same
desktop host row, or fail with the same message on a host no row names.

New compilers write schema 5, and only schema 5; readers keep 1, 2 and 4 for
host-native plans only. Both compilers write byte-identical canonical JSON
(sorted keys, compact separators, non-ASCII text unescaped, a trailing
newline). Schema 5 records the selected row and its toolchain:

```json
{
  "defines": [],
  "frameworks": [],
  "headers": [],
  "include-directories": [],
  "linker-language": "c",
  "packages": [],
  "pkg-config": [],
  "schema": 5,
  "target": {
    "arch": "aarch64",
    "environment": "simulator",
    "label": "ios-aarch64-simulator",
    "minimum": "17.0",
    "os": "ios",
    "triple": "arm64-apple-ios17.0.0-simulator"
  },
  "toolchain": {
    "sysroot": {"identity": "", "kind": "xcrun", "name": "iphonesimulator"},
    "target-arguments": ["--target=arm64-apple-ios17.0.0-simulator"]
  },
  "units": []
}
```

`target` is the row's identity: its canonical label, operating system,
architecture, environment, deployment minimum and clang triple. `environment`
and `minimum` are always present and may be empty. `toolchain.target-arguments`
copies the row's clang target arguments. `toolchain.sysroot` names the row's
sysroot kind and xcrun SDK name, and its `identity` is the 64-digit SHA-256
that both compilers' sysroot validation computes when the compile read native
headers through a sysroot (`""` otherwise). The plan never holds a sysroot
path: paths are facts of the building host. `generated-units` and
`emitted-units` (with `emitted-unit-digests`) keep the meanings below and are
present exactly when non-empty, as is `libraries`, the selected
`native.libraries` records, which the builder links as `-l<name>` after the
objects.

The builder (`tools/native_plan.py`) accepts only the exact field set of each
schema. A schema-5 `target` must equal the row its `label` names, and its
toolchain must equal that row's. A schema 1, 2 or 4 plan names only
`{arch, os}`; it builds only on the compiler-host row that is this host, and
otherwise fails with `legacy native link plan for <os>-<arch> cannot be built
on host <label>; regenerate it as schema 5`.

The builder takes its compiler from the plan's row. On the host row it uses
the caller's `--cc`/`--cxx` with no target arguments, exactly as before, so a
host build's commands do not change. Every other row uses that row's own
driver, and the builder never falls back to the host compiler: `zig cc -target
<zig_target>` for a row with a zig target (the Windows GNU rows, and Linux
rows built from another host), with the Windows compatibility overlay
(`-I src/runtime/windows -include src/runtime/windows/btrc_win_compat.h`)
force-included into every btrc-generated unit of a Windows GNU row, as the
Makefile's `WIN_COMPAT` does; Xcode's clang (`xcrun --sdk <name> --find
clang`) with the target arguments and `-isysroot` for macOS and iOS rows; the
NDK's clang with the target arguments and `--sysroot` for Android rows; and
clang in a Windows SDK (vcvars) environment for the MSVC row, which is
runner-bound. When no driver is found the build fails with `no toolchain for
<label>: <what is missing>`. The builder finds sysroots itself: the
`BTRC_NATIVE_SYSROOT` of its environment when `BTRC_NATIVE_TARGET` spells the
row's triple, else `xcrun --sdk <name> --show-sdk-path`, the NDK's sysroot
under `$ANDROID_NDK_HOME` (else `$ANDROID_HOME/ndk/29.0.14206865`), or the
`libc` directory beside zig's `.lib_dir`. When the plan carries a sysroot
identity and the builder supplies the sysroot, it validates that sysroot the
way the compilers do and refuses a different one: `sysroot identity changed
since the plan was emitted`. The host row's compiler finds its own SDK, so its
builds are not checked. Frameworks require a macOS or iOS row, and pkg-config
is refused for iOS, Android and the Windows SDK row. The build report names
the row's label as `target` and records `deployment_target`: the row minimum
off the host, and `MACOSX_DEPLOYMENT_TARGET` (or the toolchain default) for a
macOS host build, which is reported as a warning when it differs from the row
minimum rather than refused.

Schema 2 added a nonempty `generated-units` array, sorted by unique identifier
`name`. Each record contains exactly `name`, `language`, `standard`,
`memory-management` and `source` (the emitted translation-unit text). It has no
package path: generated output must not masquerade as a source-package file.
The plan is the single published artifact, so it cannot refer to a half-published
adapter file. This is compiler output, not a new manifest input table.

Schema 4 added `emitted-units`, written when `--emit-units PREFIX` produces
secondary translation units. It is a nonempty ordered array of absolute paths
to `PREFIX.unit-<k>.c`, for `k` from 1. Resolve relative prefixes against the
compiler process's working directory and resolve its destination directory
through existing symlinks, without following the final output file. Append a
unit suffix before separating directory and filename: a prefix ending in `/`,
`.` or `..` is not itself a completed filesystem path. Existing outputs must
not change the emitted plan's spelling. The prefix can differ from the primary
C destination, including its directory; the builder must not infer these paths
from the primary C filename or its own working directory. `generated-units`
stays optional. Paths name compiler outputs, not package-owned sources, and
their order is emission order rather than lexical sorting (unit 10 follows
unit 9). The builder validates nonempty strings, absolute paths and distinct
regular files, rejecting symlinks, missing files, duplicate/hardlink aliases
and aliases of the primary C or native source units before invoking build tools.
The plan's existing total-byte bound applies; there is no fixed unit-count
ceiling. Reference cache restoration validates these exact paths and their order
against the current emission options and cached unit count.

Alongside `emitted-units`, both compilers write `emitted-unit-digests`: the
lowercase hexadecimal SHA-256 of each unit's text, in the same order. The plan's
text therefore changes whenever any unit of the program changes, even when
every path stays the same, and the primary C output is published again (new
inode and mtime, same bytes when its own text did not change) whenever any
other output of the compile was replaced. A build rule that depends only on the
primary C file or only on the plan relinks after a change confined to one
secondary unit; when nothing changed, nothing is rewritten. The builder accepts
plans without the field (compilers older than it), and when it is present
requires exactly one 64-digit digest per emitted unit.

No compiler ever wrote schema 3 (a bare emitted-unit count), and the builder
rejects it. Consumers must upgrade their plan reader with the compiler; an old
reader must reject the newer schema. Unsplit output, including a split request
that produces no secondary units, omits `emitted-units`.

The builder compiles secondary units in parallel before linking or validating
a retained executable. A split program's
functions and globals have external linkage and the runtime's file-scope state
is defined by the primary unit alone, so every unit must come from the same
compiler run. Explicit paths establish an output inventory, not generation
atomicity: interrupted publication, prior-inventory recovery, obsolete-unit
retirement and cooperating-reader validation still require the generation
protocol tracked in M6a. A plan alone does not prove that its files share one
generation. Debug resets for generated code use each unit's actual output path.

Generated C uses `c11`/`manual`, C++ uses `c++17` or `c++20`/`raii`, and
Objective-C or Objective-C++ uses the matching standard with `arc`. The builder
enables C++ exceptions for RAII units, and Objective-C exceptions, ARC and ARC
exception cleanup for ARC units. These policies apply only to generated units;
handwritten Objective-C sources keep their existing memory-management behavior.
No unit accepts arbitrary compiler flags. Both ordinary and generated C++ units
participate in linker-language selection.

The builder validates the whole plan before invoking tools. Without object
caching or debug information it writes generated units inside its private
temporary build directory and removes them after success or failure.
With `--object-cache` or `--debug-info`, it can retain
one content-addressed adapter source generation in
`<output-directory>/.btrc-adapters-v1-<digest>/`. Each generation contains exactly
the declared adapter files and a versioned manifest of their names, language,
standard, ownership policy and source hashes. The complete directory publishes
atomically; subsequent builders verify the manifest, file contents and closed
file inventory before using it. Partial, corrupt, linked or unavailable
generations fall back to private sources without modifying the shared
generation. Debug builds retain those private sources as output dependencies;
other builds use temporary sources. Reports expose `adapter_source_status` as
`none`, `temporary`, `retained`, `retained-private` or `fallback`.

Both retained and temporary source directories are one level below the native
output directory, preserving parent-relative quoted includes. Source paths,
preprocessed output and transitive headers remain inputs to object validation;
retention never strips observable paths to manufacture hits. Retained files
remain available for debugger source lookup and are removed when their build
output directory is cleaned. Builders do not evict source generations another
compiler might be using. The embedded plan remains authoritative; this is not
a new manifest input table or a complete compiler-output generation cache.

For a macOS or iOS row, `--debug-info` also retains a complete immutable object generation in
`.btrc-debug-v1-<digest>/` beside the executable. Darwin's debug map refers to
these object paths and timestamps after linking. The generation identity covers
object names and content hashes; validation checks the closed file inventory,
manifest, object contents and fixed nonzero timestamps. Invalid shared generations
remain untouched; a private retained generation serves the current build.
`debug_object_status` reports `none`, `retained` or `retained-private`. These are
build outputs, independent of the optional object cache: cache deletion does not
remove them. Keep them with development executables; build-directory cleanup
removes them. Reports and executables cannot overwrite retained debug inputs.

On Darwin with `--object-cache`, qualified Clang/native-linker invocations can
reuse the requested executable. The receipt binds the expanded command, ordered
object contents and configuration, driver/compiler/linker and loaded-image
identities, wrapper support files, environment, selected libraries, missing
search candidates and path bindings. Actual executable bytes and mode must also
match. Unknown argument languages, response files and unqualified wrappers bypass
reuse; other hosts still link normally. A discovery link identifies inputs;
a second link bracketed by fresh content and negative-lookup snapshots qualifies
the receipt. A supported miss therefore normally performs two links, and a hit
performs zero. Input changes during qualification prevent receipt publication.

Final validation/link/publication shares the existing output-parent lock,
including configurations using different caches. Receipts are optional records
in `<object-cache>/links/`, atomically published after the executable and subject
to the object cache's age-based pruning. Removing a receipt causes a miss.
Reports expose actual `links`, `link_validation_s` and `link_cache_status`:
`disabled`, `unsupported-input`, `miss`, `hit`, `stored`, `publication-failed`
or `unverified-inputs`. `link_s` times actual links; validation is separate.
A hit retains the executable's bytes, inode and timestamp.

The builder replaces the requested executable only after successful linking;
a failed discovery or verification link preserves the prior executable.
Existing package-root/path validation remains unchanged for source units.

The plan contains the target, package roots and dependency aliases, selected
headers, include directories, defines, source compilation units, frameworks,
pkg-config requirements, and final linker language.  Paths in a generated plan
are absolute so a consumer can run from another working directory.  Package
and unit ordering is deterministic.  If any selected C++ or Objective-C++ unit
is present, `linker-language` is `c++`; otherwise it is `c`.

Plan packages and dependency edges are a closed projection of the modules
loaded from the compilation root. Native declarations are then selected from
that projection by module scope and target predicates. Unrelated packages and
native inputs remain validated and locked, but do not appear in the emitted
plan.

Compiler-owned standard-library metadata lives in `src/stdlib/btrc.toml` and in
one `btrc.toml` per group folder (`src/stdlib/GUI/btrc.toml`, ...), all using
this same schema and validator. The root manifest names the reserved
`btrc_stdlib_runtime` package, exports the prelude modules, and lists every
group as a path dependency inside the stdlib tree; each group manifest names a
reserved `btrc_stdlib_<group>` package and keeps its exports, providers, typed
bindings, headers, frameworks and pkg-config beside the modules they describe.
Loaded modules select their native metadata before semantic imports run, and
ordinary export visibility applies across groups (`Library.GUI.MacOS.MacOSRunLoop`
is importable only because GUI exports it). Importing an unrelated pure module
adds no native package. The manifests travel with installed compiler data, are
hashed as compiler inputs, may depend only on path packages beneath the stdlib
root, and never write a lock into compiler data. Custom pure-source stdlibs may
omit them.

The root also carries `btrc.symbols`, a generated index of which root module
owns each canonical stdlib symbol (`tools.compiler_codegen generate`, verified
by `generated-check`). Strict import visibility needs that map even for modules
the program never imported; deriving it means parsing every root module, which
costs more than compiling a typical program. Both compilers load the index only
when its header digest (CRC-32 over each root module's name and bytes, plus the
byte and file counts) matches the modules on disk, parse the modules otherwise,
and never write the index at compile time.

This preserves module-owned metadata in installed and relocatable compiler data
without placing an ambient checkout archive in a supposedly reproducible plan. Migrating a
provider replaces its manifest source unit with a module-owned header binding;
it does not require another compiler-specific provider branch.

Make, Nix, CMake, or another build adapter may realize this plan.  Generated
CMake is a projection of the plan and is never an independent metadata source.
The shipped `btrc-native-plan` adapter is the canonical Make/Nix consumer. It
accepts only a plan, generated C input, output path, and exact tool executable
names; it has no free-form flags or shell surface and never scans source
directories. `nix flake check` builds and runs `examples/native-package`
through the packaged compiler and adapter on every qualified flake system.
