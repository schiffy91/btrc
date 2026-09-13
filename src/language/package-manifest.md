# Package manifests and native link plans

This document defines package manifest version 1, lockfile schema 3, and native
link-plan schemas 1 and 2.  The reference and self-hosted compilers implement the same
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

`os` and `arch` use the existing closed target sets below; omitted or empty
selectors match all values. Declarations for the same canonical module must be
disjoint, even on inactive targets. Self-selection, missing modules, escaping
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
or shell text.  Each entry may have `os` and `arch` string arrays.  An omitted
or empty array matches every value.  Supported operating systems are `linux`,
`macos`, and `windows`; supported architectures are `x86_64` and `aarch64`.

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
that escape the root are rejected.  Define names are C identifiers.  Framework
and pkg-config names use only letters, digits, `_`, `.`, `+`, and `-`.

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
not realtime-safe. C stored registrations, broader executor ownership/destruction
and direct capturing-lambda conversion remain unfinished. One-shot requests and
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
parameter, incompatible token/cancellation signature, missing facts, stored C
callback or unsupported executor fails compilation. Callback exceptions and
wrong-thread native delivery terminate before unwinding a foreign frame.

The independent application/component owner must cancel its scope and observe
completion before shutdown, including when receivers retain their scope. Polling
does not block; self-cancellation remains pending until dispatch returns. This
path passes real copied-block and Foundation run-loop tests in both compilers,
including sanitizers. It does **not** yet qualify automatic application shutdown,
abandoned foreign ownership cycles or GUI migration. One-shot bindings follow below.

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
signatures. Colliding names fail; signatures are never supplied in the manifest.
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
not schema-1 linker records or native source units.

Both compiler consumers require explicit `BTRC_NATIVE_HEADER_READER` (built with
`nix build .#btrc-native-header`), `BTRC_NATIVE_SYSROOT` (an available macOS SDK
or Linux GNU sysroot with `usr/include`), and `BTRC_NATIVE_TARGET` (a matching
triple, e.g. `arm64-apple-macosx14.0.0` or `aarch64-unknown-linux-gnu`).
The Nix development shell and packaged compilers supply these from
their pinned reader, SDK and host platform; explicit caller values override
the package defaults. A raw standalone compiler still requires configuration.
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
`--target OS-ARCH` selects platform predicates; accepted aliases are `x64` for
`x86_64` and `arm64` for `aarch64`. The self-hosted `btrcc` requires this
option explicitly for every version-1 manifest and fails closed if it is
missing. The reference `btrcpy` may infer a supported host target.

Plans without compiler-emitted adapters retain the byte-compatible schema 1.
Schema 2 adds a nonempty `generated-units` array, sorted by unique identifier
`name`. Each record contains exactly `name`, `language`, `standard`,
`memory-management` and `source` (the emitted translation-unit text). It has no
package path: generated output must not masquerade as a source-package file.
The plan is the single published artifact, so it cannot refer to a half-published
adapter file. This is compiler output, not a new manifest input table.

Generated C uses `c11`/`manual`, C++ uses `c++17` or `c++20`/`raii`, and
Objective-C or Objective-C++ uses the matching standard with `arc`. The builder
enables C++ exceptions for RAII units, and Objective-C exceptions, ARC and ARC
exception cleanup for ARC units. These policies apply only to generated units;
handwritten Objective-C sources keep their existing memory-management behavior.
No unit accepts arbitrary compiler flags. Both ordinary and generated C++ units
participate in linker-language selection.

The builder validates the whole plan before invoking tools, writes generated
units only inside its private temporary build directory, and removes them after
success or failure. It replaces the requested executable only after a successful
link. Existing package-root/path validation remains unchanged for source units.

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

Compiler-owned standard-library metadata lives in `src/stdlib/btrc.toml`, using
this same schema and validator. Loaded modules select their native sources,
headers, frameworks and typed bindings before semantic imports run. The reserved
`btrc_stdlib_runtime` package owns all selected stdlib units; the compiler no
longer contains separate provider lists. Importing an unrelated pure module adds
no native package. The manifest travels with installed compiler data, is hashed
as a compiler input, and cannot declare package dependencies. Importing it never
writes a lock into compiler data. Custom pure-source stdlibs may omit it.

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
