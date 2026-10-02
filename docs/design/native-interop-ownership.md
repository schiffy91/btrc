# Foreign interop ownership

Status: **design step 0 of PLAN.md Stage 27**, written 2026-10-02 on lane
`stage27/interop-design`. It is the one ownership plan that Stages 27, 29 and
31 implement for C function tables, Objective-C protocols and blocks, JNI,
COM and GObject. It changes no compiler code. The review and its resolutions
are in [Review](#review).

It extends, and does not replace, the contracts already recorded in
[native-interop.md](native-interop.md), the native-binding sections of
[`src/language/package-manifest.md`](../../src/language/package-manifest.md),
[arc-runtime.md](arc-runtime.md) and [string-lifetime.md](string-lifetime.md).
Where this document says "the existing X", X is implemented in both compilers
today and documented there.

## 1. One model, three relations

Every value that crosses a foreign boundary is in exactly one of three
relations to btrc ARC. All five foreign models are spelled in these three
relations and nothing else. No model gets its own wrapper, holder runtime or
cancellation system.

| Relation | What it is | Existing owner | ARC effect |
|---|---|---|---|
| **R1. btrc owns a foreign claim** | One native claim (a retain, a unique handle, a COM reference, a JNI global ref, a GObject reference) held by a btrc value. | Resources: `ownership = "unique"` and `"reference-counted"` (package-manifest.md, "Unique C resources", "Managed reference-counted C resources"); managed Objective-C instances (native-interop.md:326-332). | A unique resource is one ordinary btrc owner; aliases retain the owner. A reference-counted resource keeps native identity; each alias holds its own native claim. Native objects never get a btrc ARC header and are never traversed by the cycle collector. |
| **R2. A call borrows** | Arguments, results borrowed from an owner, Objective-C autoreleased values, JNI local refs, temporaries inside one generated adapter. | Call leases and cleanup slots of native calls; read-only call borrows; `borrowed-results`. | A borrowed resource argument holds one claim (or owner retain) for the call; it unwinds in reverse order through normal cleanup. Nothing borrowed survives the adapter frame. |
| **R3. Foreign code holds btrc** | A native object, table, COM sink, Objective-C holder, GObject signal closure or Java peer refers to a btrc receiver. | Callback-table holders (`resources.<R>.table`), `CallbackContext`/`CallbackScope`/`CallbackToken`/`CallbackRequest` in `src/stdlib/Callback.btrc`, generated Objective-C holders. | The foreign holder owns exactly **one external ARC claim** (`rc` only, never `edge_rc`; arc-runtime.md "Exact-counter invariant") on a btrc context or receiver, and releases it on the foreign side's own final event: table release, `dealloc`, COM `Release` to zero, `GClosureNotify`, Java peer close. |

Two consequences follow, and every model repeats them:

1. **Foreign-held cycles are never collected.** A cycle that passes through
   an R3 claim (receiver → R1 owner → native object → holder → receiver) is
   invisible to the collector, because the holder's claim is an external root.
   Cycles are broken only by **explicit cancellation**: `CallbackScope`
   cancellation, `close()` on the R1 owner, or a declared terminal callback.
   This is the existing rule ("do not rely on receiver/scope destructors alone
   to break a foreign-held cycle") applied to every model. Where a cycle is
   directly visible in source the analyzer rejects it (section 6).
2. **Thread affinity is checked, not assumed.** ARC counters are not atomic
   yet (arc-runtime.md, "Cross-thread design"). Every R3 entry and every final
   R1 release whose foreign side has affinity checks its executor and aborts on
   the wrong thread before any btrc code runs. Executors are declared per
   binding: `caller` (the creating thread; existing), `main` (process main
   thread, for Objective-C `@MainActor`/UI-actor APIs and Android UI classes),
   `main-context` (GLib default main context owner) and `apartment` (the COM
   apartment's creating thread).

The model also has three shared mechanisms, each implemented once in each
compiler and reused by every model that needs it:

- **M1. Dispatch through a foreign table.** A call through a function pointer
  loaded from a foreign table, inside a generated adapter, under an R2 lease on
  the receiver. Used by C vtables, COM `lpVtbl`, and `JNIEnv`.
- **M2. One holder shape for R3.** A generated holder carrying the receiver
  claim, a foreign-claim counter, the creating thread and a state word. The
  existing callback-table holder is the template; COM sinks and Java peers are
  instances of it, and Objective-C holders keep their generated `NSObject`
  class around the same fields.
- **M3. One checked conversion.** `(T?)value` on a foreign object: null input
  yields null without calling the SDK; a mismatch yields null; a match yields a
  new R1 claim taken before the source lease ends. The existing CF
  `type-query`/`type-tag` cast is the template. Each model supplies only the
  test: `CFGetTypeID` equality, GObject `g_type_check_instance_is_a`, COM
  `QueryInterface`, Objective-C `isKindOfClass:`/`conformsToProtocol:`, JNI
  `IsInstanceOf`. COM's `QueryInterface` already returns a claim, so it adds
  no retain.

And one shared failure rule:

- **F1. Foreign failure is translated inside the adapter.** HRESULT status,
  `NSError` out-parameters, Objective-C exceptions, pending JNI exceptions and
  GLib invalid-signal results are inspected inside the generated adapter, the
  adapter's own R2 state is unwound (autorelease pool, JNI local frame, leases),
  and only then does a btrc exception start. No foreign unwind crosses
  generated C and no btrc `longjmp` crosses a foreign frame. A btrc exception
  escaping an R3 entry runs its local cleanup and then follows the binding's
  `failure` (today only `abort`; JNI may add `throw`, below).

## 2. Per-model mapping

### 2.1 C function tables (Stage 27, first)

**Implemented today:** btrc *implementing* a table, `resources.<R>.table`
(package-manifest.md "Unique C callback tables"; Python
`native_imports.py:1532-1686`, `ir/lowering/functions.py:1239-1420`; btrc
`frontend/NativeImports.btrc:473-554`, `ir/lowering/Declarations.btrc`). This
is R3 through the M2 holder, with one claim per live table including SDK
reopen clones.

**Missing:** btrc *calling* a table the SDK hands it. Today a function-pointer
field imports as an unchecked `__fn_ptr<R, P...>` field with no null check and
no lease on the receiver (`_callback_field`, `native_imports.py:3436-3460`).

**Rules.**

- The native object owns its table. btrc never copies, frees, caches or
  retains a table pointer or a slot; both are reloaded on every call, because
  SDKs swap tables when their state changes.
- A dispatched call is M1: borrow the unique owner (`_begin_borrow`), load the
  table, null-check it, load the slot, null-check it, call, end the borrow.
  Closing through any alias during the call aborts; calling on a closed owner
  aborts before the SDK runs. Reentrant calls on the same object from inside
  a callback are legal; reentrant close aborts (the existing unique rule).
- Every field of a dispatch-table record becomes private. That removes the
  unchecked `__fn_ptr` read path for these records.
- Arguments are R2 borrows (scalars, POD data pointers, declared
  `borrowed-parameters` resources). Results are scalars or, through
  `owned-results`, resources. A raw pointer result is rejected unless declared
  borrowed from the receiver.
- A table `release` slot, when named, runs exactly once from final owner
  cleanup. It is mutually exclusive with the resource's top-level `release`.
- Reference-counted dispatch receivers are COM's (section 2.4); a plain C
  `reference-counted` resource does not take `dispatch` in Stage 27.

**Loopback.** Dispatching through a table btrc itself implemented composes the
R2 lease of the call with the R3 holder claim of the receiver; no new
mechanism.

**Manifest** (new subtable beside `table`):

```toml
[native.bindings.resources.Codec]
ownership = "unique"

[native.bindings.resources.Codec.dispatch]
table = "vtbl"            # field holding the table pointer; "*" = receiver points at the table pointer (JNIEnv)
receiver-index = 0        # parameter receiving the object (or the context, below)
receiver = "self"         # "self" | "context:<field>" (libstreamfile-style user_data tables)
executor = "caller"
failure = "abort"
release = "destroy"       # optional slot; excludes the resource's top-level release
ignored = ["reserved0"]   # slots deliberately left uncallable

[native.bindings.resources.Codec.dispatch.methods]
decode = "decode"
reset = "reset"
```

`borrowed-parameters`, `owned-results` and `owned-outputs` may name a dispatched
method as `"Codec.decode.<parameter>"`; slot parameter names come from the new
`NativeField.callback_parameters` (section 3).

### 2.2 Objective-C protocols and blocks (Stage 27 slice, Stage 29 I1)

**Implemented today:** managed instances (R1, generated ARC retain/release
adapters); stored and one-shot blocks, target/action and stored delegates
(R3) through `CallbackContext`, `CallbackToken<Source, id>` and a generated
`NSObject` holder that owns one external claim on the context
(package-manifest.md:314-716; `functions.py:2919-2960, 3432-3466`). Adapter
units compile with ARC, Objective-C exceptions and `-Werror`, with the
exception boundary nested inside the autorelease pool (F1).

The R3 chain is:

```
CallbackScope -> CallbackState -> CallbackContext<Receiver, CallbackToken<Source, id>>
CallbackContext -> receiver (strong), token (strong)
token -> source (strong), holder (strong, managed id)
holder -> context: one external ARC claim
native source -> holder: weak, assign or strong, per the SDK property
```

The token keeps the holder alive, so a `weak` or `assign` native delegate
property cannot let the adapter die early. The context→token→holder→context
loop is deliberate and broken only by cancellation: clear the slot through the
setter and verify it, drain, then drop the receiver and token; `dealloc` then
releases the context. The order "clear slot, then release holder" is
**required** for `assign` (`unsafe_unretained`) properties, so property
ownership becomes a checked reader fact.

**Blocks.** `no_escape` is a hard fact; its absence proves nothing, so the
binding still declares `lifetime = "call" | "stored" | "one-shot"`. Stored
blocks are copied by the generated adapter (ARC) and released when the holder
dies; a block property is `ownership = "copy"` with a `NativeObjectiveCBlock`
type and needs no new node.

**Stage 27 slice** (exit: one checked delegate round trip on macOS and the iOS
simulator test host) adds analysis, not new runtime:

- the reader extracts protocol requirement closures, property ownership,
  protocol conformance and main-actor annotations (section 3);
- a binding whose `methods` omits a required method, selects a selector outside
  the requirement closure, or contradicts property ownership is a btrc
  diagnostic (today it fails only at native `-Werror` compile time);
- a main-actor setter or protocol gets a main-thread check at publication and
  on entry (`executor = "main"`), reusing the existing thread guard.

**Stage 29 I1 additions** (same model, new modes):

- `lifetime = "instantiated"`: adapters UIKit creates by class name
  (`UIApplicationMain`, Info.plist scene delegates). The generated class's
  `-init` claims a receiver from a registered btrc factory. `scope = "process"`
  makes it a declared permanent root, outside leak accounting, and a second
  instantiation aborts; `scope = "instance"` releases the claim after the
  declared `terminal` method (`sceneDidDisconnect:`) or at `dealloc`.
- `superclass = "UIView"` with `overrides = [...]` for CAMetalLayer hosting
  (`+layerClass`, `-layoutSubviews`); `requires_super` forces the super send;
  designated initializers choose the init.
- `error-out` for `NSError**` parameters (F1): `nil` is success, non-nil
  becomes a btrc exception carrying `localizedDescription`.
- M3 checked downcasts through `isKindOfClass:`/`conformsToProtocol:`;
  lightweight generics erased to their bound for payloads.
- `id<P>` protocol handles stay deferred: WebGPU takes the `CAMetalLayer`
  pointer, so I1 does not need them.

### 2.3 JNI (Stage 27 slice, Stage 29 A1)

JNI uses all three relations and M1 for `JNIEnv`; it adds no new ownership
idea.

- **`JNIEnv`** is per thread and never stored in btrc data. It is a C function
  table (`const struct JNINativeInterface_*`), read by Clang from the NDK's or
  JDK's `jni.h`, and every call through it is M1 dispatch with `table = "*"`.
  The thread's env lives in a `pthread_key_t` owned by a new stdlib module.
  Threads btrc spawns attach lazily on first use, and the key's destructor
  detaches them. POSIX runs key destructors after the thread start routine
  returns, which is after `__btrc_thread_wrapper` has run ARC thread cleanup
  (that cleanup may delete global refs), so the order is correct without a
  runtime hook. Threads Java gave us (native-method entry, the main thread) are
  never detached.
- **Local refs are R2.** Each generated adapter brackets its body with
  `PushLocalFrame(n)` (n computed from the signature and temporaries) and
  `PopLocalFrame(NULL)` on every path, including F1's exception path. A loop
  inside one adapter deletes each element's local ref. No local ref reaches a
  btrc value. This stays within the 16-slot guarantee.
- **Global refs are R1, as unique resources.** Each selected Java class
  becomes a generated unique resource whose release is `DeleteGlobalRef`: one
  btrc owner per global ref, aliases retain the owner, `close()` and final
  cleanup delete once. An object result becomes `NewGlobalRef(local)` and a new
  owner before the frame pops. A borrowed argument passes the global ref
  directly (legal as a JNI argument) under the owner's borrow.
- **Weak global refs** (Stage 29) are a generated `JavaWeak<T>` unique resource
  owning the `jweak`; `get()` returns `T?` via `NewLocalRef`, a null check and
  promotion to a new global owner.
- **IDs and classes.** A `jclass` is cached as a global ref, which keeps its
  method and field IDs valid; IDs are never released. Initialization is once
  per binding symbol, under the existing btrc mutex (C11 `call_once` is missing
  on macOS). Application classes resolve at `JNI_OnLoad` or through a cached
  application `ClassLoader` global ref, never `FindClass` on an attached thread.
- **F1.** Every env call outside a closed non-throwing set (`ExceptionCheck`,
  `ExceptionClear`, `ExceptionOccurred`, `DeleteLocalRef`, `DeleteGlobalRef`,
  `DeleteWeakGlobalRef`, `PopLocalFrame`, `Release*`) is followed immediately
  by `ExceptionCheck`, with no other env call between. On a pending exception:
  `ExceptionOccurred`, `ExceptionClear`, promote the throwable to a global
  ref, pop the frame, throw btrc `JavaException`. The IR verifier enforces the
  placement.
- **Strings** copy through UTF-16 (`GetStringRegion`, `NewString`), transcoded
  to and from real UTF-8 in the stdlib module. `GetStringUTFChars` and
  `NewStringUTF` are not used: modified UTF-8 corrupts embedded NUL and
  supplementary characters. Primitive arrays copy through
  `Get/Set<X>ArrayRegion`; borrowed spans (Stage 29) release with `JNI_ABORT`
  when read-only; `GetPrimitiveArrayCritical` is rejected.
- **Java → btrc (Stage 29)** is R3: `RegisterNatives` thunks over the M2
  holder and the existing callback registration, with the env installed in the
  key for the call and restored after. A Java peer that holds a btrc receiver
  while btrc holds a global ref back is a foreign-held cycle: break it by
  cancellation tied to `onDestroy`, or hold the back edge as `JavaWeak`.
  `failure = "throw"` (Java-entry only) turns a btrc exception into `ThrowNew`
  of `java.lang.RuntimeException` with the message.
- **Executors.** `executor = "main"` marks UI classes; it is checked against
  the thread captured at `JNI_OnLoad`.

**Metadata.** D22 fixes the source: a class-file reader over `android.jar`,
not C headers. Its output is the same `native_abi.asdl` document (section 3),
served through the same batch protocol (`btrc.native-requests.v1` in,
`btrc.native-responses.v1` out, same ordering, NUL and size/time limits) as
`tools/NativeHeaderReader.cpp`, so both compilers consume it through their
existing codecs and `FeNativeHeaderReader` seam. It is a separate build-time
tool, `tools/JavaClassReader.c`: strict C11 plus zlib for jar inflate, built
in `flake.nix` beside the header reader, with no JVM and no LLVM, so it also
runs on the Windows host. A binding selects it with `language = "java"`; the
classpath is part of the reader's cache key. Stage 27 ships reader v1 (public
classes, methods and fields of selected symbols from a jar or class
directory). Stage 29's separate reader agent completes it (nullability
annotations, inner classes, inherited lookup, `android.jar` scale, caching).

**Manifest.**

```toml
[[native.bindings]]
module = "AndroidApp"
language = "java"
standard = "android-34"
classpath = ["$ANDROID_SDK_ROOT/platforms/android-34/android.jar"]
symbols = ["android.app.Activity",
           "android.app.Activity.getFilesDir()Ljava/io/File;"]
```

Member selections use the JNI descriptor, so overloads are never guessed.

### 2.4 COM (Stage 27, last)

COM is a reference-counted R1 resource whose hooks are vtable slots, plus M1
dispatch, M2 sinks and M3 `QueryInterface`.

- **Claims.** Every interface pointer from a factory, an `[out]`/`[out,
  retval]` `T**` or `QueryInterface` is one claim, ended by exactly one
  `Release` through the same pointer. The `ULONG` that `AddRef`/`Release`
  return is diagnostic only and discarded. `[in]` interface parameters are R2
  borrows. Under `_COM_Outptr_` the callee stores null on failure, so "adopt
  every nonnull output on every status" is sound: that is the existing
  `owned-outputs` contract with `status = "hresult"` (negative is failure).
- **Shape.** `ownership = "com"` on a record typedef (`typedef interface
  IStream IStream;` representing `IStream*`). The importer proves slots 0-2
  of the `lpVtbl` table are `QueryInterface(This, REFIID, void**)`,
  `AddRef(This)->ULONG` and `Release(This)->ULONG` against the real layout. A
  manifest `base` is checked slot by slot (signatures equal except `This`), so
  widening is static. Methods are M1 `dispatch` with `table = "lpVtbl"`.
- **Identity.** `==` stays pointer equality. A generated `sameObject(a, b)`
  compares the two `IUnknown` identities (QI both, compare, release both).
- **M3.** `(IBar?)foo` lowers to `QueryInterface(&IID_IBar, &out)`: success is
  an owned claim, `E_NOINTERFACE` is null, any other failure aborts in Stage 27.
  A nonnull `*ppv` with a failed HRESULT is adopted and then aborts.
- **GUIDs.** IIDs are referenced as the SDK's `extern const IID` objects and
  linked from `uuid`; their values are not in Windows SDK C headers, so the
  reader does not carry them.
- **Sinks (R3, M2).** `[native.bindings.com-sinks.<Interface>]` generates the
  holder `{ const Vtbl* lpVtbl; uint32_t comCount; receiver; thread; state }`
  with one static const vtable. While `comCount > 0` the holder holds **one**
  external claim on the receiver; at zero it releases the receiver and frees
  itself. `QueryInterface` answers `IID_IUnknown`, the declared IID and its
  bases by `memcmp`, else `E_NOINTERFACE` with `*ppv = NULL`. `AddRef`/
  `Release` from another thread abort (ARC is not atomic); free-threaded
  (MTA) sinks are deferred.
- **Apartments.** `apartment = "creating-thread"` checks every call and the
  final release against the creating thread. `CoInitializeEx`/`CoUninitialize`
  belong to a stdlib `ComApartment` owner that counts live claims and aborts
  an uninitialize with claims live.
- **Allocators.** `BSTR` (`SysFreeString`) and `CoTaskMemAlloc` strings are not
  record pointers, so they are never R1 resources. They are copied out with
  `copied-outputs` (`encoding = "utf-16"`, `free = "CoTaskMemFree"` or
  `"SysFreeString"`) and freed inside the adapter.
- **Calling convention.** On x64 and ARM64 Clang reports `STDMETHODCALLTYPE`
  as the C convention. 32-bit x86 `__stdcall` cannot be spelled in strict C11
  and stays rejected.
- **Rejected.** Aggregation (`pUnkOuter` must be hidden or null), duplicate
  sink IIDs, sink method names colliding with `IUnknown`.

```toml
[native.bindings.resources.IStream]
ownership = "com"
iid = "IID_IStream"
base = "ISequentialStream"
apartment = "creating-thread"

[native.bindings.resources.IStream.dispatch]
table = "lpVtbl"
receiver = "self"
[native.bindings.resources.IStream.dispatch.methods]
read = "Read"
clone = "Clone"

[native.bindings.owned-outputs."IStream.clone.ppstm"]
status = "hresult"

[native.bindings.com-sinks.ICounterEvents]
interface = "ICounterEventsHandler"
factory = "makeCounterEvents"
executor = "caller"
failure = "abort"
```

### 2.5 GObject (Stage 31, `ui-1-linux-gobject-binding`)

GObject is the existing `reference-counted` resource (`retain =
"g_object_ref"`, `release = "g_object_unref"`), plus floating-reference
sinking, M3 subtype casts and signals as existing stored registrations.

- **Sinking.** A new resource key `sink = "g_object_ref_sink"` and binding list
  `sunk-results`. The adapter sinks every non-null sunk result, which always
  yields exactly one btrc claim: a floating constructor's reference is
  adopted, and a transfer-none result held by the library (`gtk_window_new`)
  gains one reference. `owned-results` stays transfer-full and is never sunk,
  because sinking a non-floating full reference leaks a count. btrc never
  holds a floating reference, so every resource parameter remains an ordinary
  R2 borrow and a container's own sink adds its own reference.
- **Transfer facts come from the manifest only.** They exist in `.gir` files
  and gtk-doc, not in anything Clang sees, and naming is unreliable. Reading
  `.gir` would add a second semantic input in two compilers and put binding
  policy into the header schema, which `native_abi.asdl` forbids. An offline
  `.gir`-to-manifest-fragment tool may come later; it is never a compiler
  input. A wrong `sunk-results`/`owned-results` declaration is a trusted
  promise caught only by fixture counts.
- **Toggle refs are rejected.** btrc has no proxy object, so the problem they
  solve does not arise, and they would add a third counter state to the
  exact-counter invariant and conflict with any other binding in the process.
- **Signals (R3).** `g_signal_connect_data(instance, name, GCallback, data,
  GClosureNotify, flags)` maps onto the stored registration: `data` is the
  context's external claim and the generated `GClosureNotify` releases it, so
  disconnect or finalize frees it exactly once. The context holds the source
  as a `GWeakRef`, not strongly, so instance and context do not form a native
  cycle that only cancellation could break. Cancellation: get the weak ref; if
  non-null and still connected, disconnect (entry barrier); release. The
  handler signature always comes from a header type, never manifest text:
  `signature = "class-field:GtkAdjustmentClass.value_changed"` or
  `signature-typedef = "<typedef in the package's own header>"`. `GCallback`
  erasure is the single typed cast inside the adapter. Registration validates
  the name (`g_signal_parse_name`, recoverable exception with no publication)
  and arity/return (`g_signal_query`, terminal on mismatch).
- **Cycles.** A widget's closure holding a receiver that holds the widget is a
  foreign-held cycle; the independent `CallbackScope` is the breaker. A
  window's documented shutdown is `close-request` → `scope.cancel()` →
  `gtk_window_destroy`.
- **M3.** `type-check = "g_type_check_instance_is_a"`, `type-tag =
  "gtk_button_get_type"`, `type-relation = "subtype"` (CF's is `"equal"`).
  Upcasts use `parent` and `implements`; the importer checks identical hooks
  and, where the header exposes `<T>Class`, that its first field is
  `<Parent>Class`.
- **Affinity.** `release-executor = "main-context" | "any"`. For
  `main-context`, release, sink and borrow adapters check
  `g_main_context_is_owner(g_main_context_default())`; capturing such a
  resource in `spawn` is a compile-time error.

```toml
[native.bindings.resources.GObject]
ownership = "reference-counted"
retain = "g_object_ref"
release = "g_object_unref"
sink = "g_object_ref_sink"
release-executor = "any"
type-check = "g_type_check_instance_is_a"
type-tag = "g_object_get_type"
type-relation = "subtype"

[native.bindings.signals."GSimpleAction::activate"]
interface = "IActionActivate"
signature-typedef = "BtrcActivateHandler"
connect = "g_signal_connect_data"
disconnect = "g_signal_handler_disconnect"
check-connected = "g_signal_handler_is_connected"
lifetime = "stored"
executor = "caller"
failure = "abort"
cancellation = "entry-barrier"
```

## 3. The `native_abi.asdl` extension

`native_abi.asdl` stays semantic data with no policy. Ownership modes,
executors, transfers, sinks, signals and dispatch maps are binding policy and
live in the package manifest, parsed by `frontend/packages.py` and
`frontend/Packages.btrc`. The schema grows only by facts a reader can observe.
All names are snake_case; the generator respells them camelCase for
`generated/native_abi/Models.btrc`.

The complete delta, applied in the order the implementation steps need it:

```asdl
-- Step 1 (function tables; reused by COM slots):
native_field = NativeField(identifier name, native_type field_type, string offset_bits,
                           bool is_anonymous, bool is_bitfield, string width_bits,
                           native_parameter* callback_parameters)

-- Step 3 (Objective-C slice): native_interface becomes a three-way sum
-- (NativeJavaClass is added by step 4).
native_interface = NativeObjectiveCInterface(identifier name, string identity, bool complete,
                                             string superclass, identifier* protocols,
                                             native_property* properties, bool main_actor)
                 | NativeObjectiveCProtocol(identifier name, string identity, bool complete,
                                            identifier* protocols,
                                            native_requirement* requirements,
                                            native_property* properties, bool main_actor)
                 | NativeJavaClass(identifier name, string binary_name, string? super_name,
                                   identifier* interfaces, bool is_interface, bool is_abstract,
                                   bool is_final, string? outer_name)

native_requirement = NativeProtocolRequirement(string selector, bool class_method,
                                               bool optional, identifier declaring_protocol)

native_property = NativeObjectiveCProperty(identifier name, string getter, string? setter,
                                           native_type value_type, string ownership,
                                           bool readonly, bool atomic, bool class_property,
                                           identifier declaring_owner)

-- NativeObjectiveCMethod gains three trailing fields:
--   bool designated_initializer, bool requires_super, bool main_actor

-- Step 4 (JNI slice):
native_declaration = ...
                   | NativeJavaMethod(identifier name, string identity, identifier owner,
                                      string method_name, string descriptor,
                                      string? generic_signature, native_type signature,
                                      bool is_static, bool is_constructor, bool is_final,
                                      bool is_abstract, bool is_native, bool is_varargs,
                                      string* exceptions)
                   | NativeJavaField(identifier name, string identity, identifier owner,
                                     string field_name, string descriptor,
                                     native_type value_type, bool is_static, bool is_final)

native_type = ...
            | NativeJavaObject(identifier name, string binary_name)
            | NativeJavaArray(native_type element)
```

Field rules both codecs enforce:

- `callback_parameters` is empty unless the field's type, after aliases and
  qualifiers, is a pointer to `NativeFunctionType`; then it has exactly one
  entry per parameter (names from the field's `FunctionProtoTypeLoc`, plus
  `no_escape`, `ns_consumed`, `cf_consumed` from `ExtParameterInfo`). A
  length mismatch is a codec error. `NativeFunctionType` itself is unchanged,
  so type identity (`_type_identity`, `native_imports.py:3369-3375`) is
  unchanged.
- `NativeObjectiveCProperty.ownership` is one of `strong`, `weak`, `copy`,
  `assign`, `unsafe_unretained` (`assign` on an object type is reported as
  `unsafe_unretained`), from `ObjCPropertyDecl::getSetterKind()`.
- `requirements` is the full inherited closure, sorted by selector then
  `class_method`, from `ObjCProtocolDecl::protocols()` and `isOptional()`.
- `main_actor` is true when a `SwiftAttrAttr` reads `@MainActor` or `@UIActor`
  (what `NS_SWIFT_UI_ACTOR` expands to). `designated_initializer` is
  `isDesignatedInitializerForTheInterface`; `requires_super` is
  `ObjCRequiresSuperAttr`. Interface `protocols` is
  `all_referenced_protocols`.
- Java `identity` is the smali form, `Landroid/app/Activity;->getFilesDir()Ljava/io/File;`.
  Primitives reuse `NativeBuiltin` (`jint` 32-bit signed, `jchar` 16-bit
  unsigned, `jboolean` 8-bit unsigned). Nullability reuses
  `native_qualifiers.nullability` (absent annotation means nullable).
  `static final` constants reuse `NativeConstant`/`NativeStringConstant`.
  `Signature` is recorded in `generic_signature` and erased. For a class-file
  document, `target_triple` is the Android triple, `compiler_version` is
  `btrc-class-reader/1 sha256:<classpath digest>`, and declaration attributes
  carry `source_file = "<jar>!<path>.class"`, `line = 0`, `column = 0`.
- The `calling_convention` string of `NativeFunctionType` keeps its shape but
  widens its vocabulary: the reader reports `c`, `x86_stdcall`, `win64`,
  `aapcs`, ... instead of rejecting (`NativeHeaderReader.cpp:569-577`), and
  both importers reject everything except `c` until a convention is qualified.

**Generator impact.** `native_interface` is a single-constructor type today,
which the generator renders as an alias of its class
(`native_generated.py:271`) and `NativeHeader.interfaces` as
`list[NativeObjectiveCInterface]`. Adding constructors makes it a tagged sum
like `native_declaration`, so `NativeHeader.interfaces` becomes
`list[native_interface]` and both codecs (`NativeHeaderCodec` in Python, its
btrc twin) dispatch on the constructor tag. Every existing consumer of
`interfaces` is updated in the same commit; that is the only non-additive
change. The reader's document schema string moves from
`btrc.native-declarations.experimental` to `btrc.native-declarations.v2` in
step 1, and each later step is additive under v2 (new fields default
empty/false in both codecs, so a reader and compiler built from the same
commit always agree; a mismatch is the existing version error).

**Considered and left out.** GUID initializer values (absent from SDK
headers; IIDs are linked), SAL annotations (empty macros in MinGW; the
manifest is authoritative), GObject transfer annotations (`.gir`, see 2.5), a
deprecation attribute (P1's availability record owns that). A shared
"resolved binding semantics" schema was considered and rejected: binding
policy already has one parser per compiler and does not belong in the reader
schema.

## 4. Compiler work in both compilers

Every construct lands **Python first, then its btrc twin, one commit per
construct**, with the generator regenerated in the Python commit. All files
below already exist; the 88-file Python and 97-file btrc inventories do not
change.

| Construct | Python owner | btrc twin |
|---|---|---|
| ASDL fields and constructors | `src/language/native_abi.asdl` → `abi/native_generated.py` | → `generated/native_abi/Models.btrc` |
| Reader extraction | `tools/NativeHeaderReader.cpp` (C-family); new `tools/JavaClassReader.c` (Java) | shared tools |
| Codec | `NativeHeaderCodec` in `frontend/native_imports.py` | codec in `frontend/NativeImports.btrc` |
| Manifest keys (`dispatch`, `com-sinks`, `signals`, `sink`, `sunk-results`, `release-executor`, `type-relation`, `parent`, `implements`, `iid`, `base`, `apartment`, `copied-outputs`, `error-out`, `language = "java"`, `classpath`) | `frontend/packages.py` | `frontend/Packages.btrc` |
| Projection and checks | `NativeDeclarationImporter` (`native_imports.py`), e.g. `_project_dispatch_tables` beside `_project_callback_tables` | `FeNativeDeclarationImporter` (`NativeImports.btrc`) |
| Analyzer rules (private slots, direct-cycle rejection, spawn capture of `main-context` resources) | `analyzer/expressions.py`, `analyzer/ownership.py` | `analyzer/` and `analyzer/ownership/` owners |
| Adapter lowering | `ir/lowering/functions.py` (native adapters) | `ir/lowering/Declarations.btrc` |
| IR verification | `ir/verifier.py` | `ir/` verifier owner |

**Lowering stays structured.** M1 needs no new IR node: `IRCall.callee`
already takes an `IRExpr` (`ir/nodes.py:202-206`), so a dispatched call is
`IRCall(callee=IRVar(slot), ...)` after `IRVarDecl`s for the table and slot
with `_native_null_guard` checks; if a slot local cannot be spelled,
`IRFunctionPointerTypedef` (`nodes.py:400`) supplies the type. M2 holders are
`IRStructDef`s plus static `IRFunctionDef`s and a static const table global.
Objective-C uses the existing `IRObjectiveCClass`, `IRObjectiveCMethod`,
message, block, autorelease-pool and exception-boundary nodes; Stage 29's
instantiated adapters add one expression node for a class reference beside
`IRObjectiveCSelector`. The emitter only renders.

**Verifier rules** (new, both compilers):

1. An `IRCall` whose callee is an expression appears only inside a generated
   native adapter.
2. In a JNI adapter, every env call outside the non-throwing set is followed
   immediately by its `ExceptionCheck` branch, and every path out of the body
   passes `PopLocalFrame`.
3. A generated R3 entry checks its executor before any btrc call.

**Runtime.** No new `src/runtime/c` asset and no `manifest.toml` rows. The
holders reuse the existing thread-identity check and `__btrc_safe_calloc`;
callback state stays in `src/stdlib/Callback.btrc`. JNI's VM pointer,
per-thread env key, attach/detach, exception translation and UTF-16
transcoding live in a new stdlib package `src/stdlib/Java/` (Android and host
providers selected by `[[package.providers]]`), and `ComApartment` lives in a
new `src/stdlib/COM/` package. If an implementation step finds a runtime row
unavoidable, it goes through the `runtime/c` single owner and D14 as usual.

**Link plans.** `java` bindings add the JVM or `libnativehelper`-free NDK link
(Android links nothing extra; a host JVM test links `libjvm`); COM adds
`ole32` and `uuid`; GObject adds `gobject-2.0` (`gtk4` for tier B).

## 5. Diagnostics

All compile-time diagnostics are source-mapped `NativeImportError`s (or
analyzer errors) with identical text in both compilers; the parity tests
compare them.

| Model | Compile-time rejections |
|---|---|
| Tables | non-function or variadic slot; non-`c` convention; wrong receiver type at `receiver-index`; unmapped, duplicate or unknown slot; `table` not a pointer to a complete record; slot `release` together with a top-level `release`; method name shadowing `close`/`isOpen` or a selected symbol; managed btrc value in a slot signature; raw pointer result without a declared borrow; `callback_parameters` length mismatch; executor other than `caller`, failure other than `abort`; reading, writing or taking the address of a dispatch-record field ("native dispatch slot is private; call it through `<R>.<m>()`"); a class implementing a table interface with a field of its own resource type (direct cycle). |
| Objective-C | required method missing from `methods`; selector outside the requirement closure; property ownership contradicting the mode (strong delegate mapped as a vacant slot, read-only property as a slot); `no_escape` with a stored or one-shot mapping; main-actor API bound with a non-`main` executor; override missing a `requires_super` send; no usable designated initializer; duplicate adapter class name; unmapped object result or generic `id<P>` payload. |
| JNI | unknown class or member; overloaded name without a descriptor; non-public, synthetic or bridge member; unsupported class-file major version; missing classpath; `RegisterNatives` target not `ACC_NATIVE`; nullable result used as non-null; generic arguments (erased); user code naming reserved env hooks; reader errors attributed to their binding, never filled from a sibling. |
| COM | slots 0-2 not IUnknown-shaped; `base` prefix mismatch; `iid` not a read-only `GUID` global; `owned-outputs` parameter not a mutable `Interface**`; `status = "hresult"` on a non-32-bit-signed result; visible `pUnkOuter`; `x86_stdcall`; `copied-outputs` with an unselected or wrong-signature allocator; duplicate sink IIDs; sink names colliding with `IUnknown`. |
| GObject | function in both `owned-results` and `sunk-results`; `sink` on a non-reference-counted resource; transfer-container result; `parent` contradicted by the class struct or by different hooks; `signature` naming a non-function field or one whose first parameter is not the owner; unannotated resource result; spawn capture of a `main-context` resource. |

Runtime terminal errors, each with its own message before control enters the
SDK: closed owner; close during an admitted call or reentrant close; null
table or slot; wrong executor, apartment or main context; btrc exception
crossing an R3 boundary with `failure = "abort"`; scope destroyed before
cancellation (existing); JNI `GetMethodID` null ("metadata/runtime API
mismatch" plus identity), exception pending on adapter entry, exception while
translating an exception, no `JavaVM`; COM failed QI other than
`E_NOINTERFACE`, nonnull `*ppv` with failure, `CoUninitialize` with live
claims; GObject signal arity mismatch; second instantiation of a process-scoped
Objective-C adapter, factory returning null. Recoverable btrc exceptions:
translated foreign failures (F1), `JavaException`, invalid GLib signal name,
failed checked downcast where the binding declares it recoverable. Realtime
paths keep `__builtin_trap` without logging, as today.

**Trusted, documented, not provable:** that an SDK does not free an object
inside its own slot call; slot thread safety; manifest transfer facts
(`sunk-results`, `owned-outputs`, COM `[out]`); that a JNI metadata jar
matches the device runtime.

## 6. Ordered implementation plan

Order follows PLAN.md Stage 27: function tables, then the Objective-C slice,
then the JNI slice, then COM. Each step is one owner (ASDL, both importers,
lowering), with the mirror agent porting each construct to btrc and the
fixture author supplying the fixture. Each step ends with its focused suite
through both compilers, `make test`, and **a bootstrap for the feature**
(Stage 27 exit). "Linux" below means runnable in the cloud and the
`linux-ci` container; "Mac" means the M1 host; device rows follow the
Stage 25 test hosts.

| # | Step | Commits (each Python, then btrc) | Tests and exit evidence | Where |
|---|---|---|---|---|
| 1 | Schema v2 base | `NativeField.callback_parameters`; reader emits slot parameter semantics and real calling conventions; codecs; importers reject non-`c` | Reader goldens for slot names/no_escape; codec round trip and malformed-length rejection in both codecs; generated-source check | Linux |
| 2 | **Function-table calls** (`platforms-interop-function-table-calls`) | `dispatch` manifest keys; `_project_dispatch_tables`; private dispatch records; M1 adapters; verifier rule 1; direct-cycle analyzer rule | `Codec` vtable fixture: decode, reset, swap tables (no caching), alias + `close()` runs `destroy` once, live count 0, 1,000 iterations; loopback through the existing `Reader` table in `receiver = "context:user_data"` mode; negatives (null slot aborts, close inside callback aborts, slot read rejected, self-cycle rejected). **Exit: passes at `-O2` and under ASan/UBSan** in both compilers. The fixture gains a Linux sysroot variant of `native_project` (today it skips off macOS, `native_import_fixtures.py:49`) | Linux and Mac |
| 3 | **Objective-C slice** (first slice of `platforms-i1-objc-protocol-adapters`) | `native_interface` sum with `NativeObjectiveCProtocol`, properties, requirements, `main_actor`, method flags; reader extraction; codec; required-method, property-ownership and main-actor checks; `executor = "main"` guard | Reader/codec/diagnostic goldens with `objc_root_class` fixtures on Linux; extend `test_native_objective_c_delegates.py` with `weak` and `strong` property variants, an optional method, a missing-required-method rejection and a main-actor guard. **Exit: a checked delegate round trip on macOS and on the iOS simulator** (the same Foundation-only fixture cross-compiled for `arm64-apple-ios17.0-simulator` and run with `simctl spawn`; needs Stage 24's iOS target and Stage 25's simulator host) | Linux (reader, analysis, goldens); Mac; iOS simulator |
| 4 | **JNI slice** (first slice of `platforms-a1-checked-jni`) | Java ASDL constructors; `tools/JavaClassReader.c` v1 and its flake build; `language = "java"` bindings; `src/stdlib/Java/` (VM, env key, attach/detach, exceptions, UTF-16); generated class resources (global refs), static/instance calls and fields, local frames; verifier rule 2 | Reader goldens over javac-built fixture classes; host-JVM test (`JNI_CreateJavaVM`, `-Xcheck:jni`, any CheckJNI warning fails): string round trip of `"a\0é𝄞"`, static field read, Java exception → `JavaException`, a btrc-spawned thread attaching and detaching, 10,000 object-returning calls with no frame leak, global-ref count 0 after teardown. **Exit: a checked JNI call makes one round trip on the emulator test host** (`app_process` with a pushed `.dex` and `.so`, `debug.checkjni 1`, no CheckJNI abort in logcat) | Linux (host JVM); Android emulator |
| 5 | **COM** (`platforms-w1-win32-com-imports`) | `ownership = "com"`; slot-hook validation and `base`; `dispatch` over `lpVtbl`; M3 `QueryInterface`; `owned-outputs` with `status = "hresult"`; `copied-outputs`; `com-sinks` holders; `src/stdlib/COM/` `ComApartment` | Linux proxy (`ComShape.h`: `int32_t HRESULT`, `uint32_t ULONG`, `GUID`, extern IIDs, flattened IUnknown prefix, counter server with live/AddRef/Release hooks) proving slot validation, dispatch, claim adoption, QI, sink holder, cycle teardown and exact counts under sanitizers; reader run with `--target=x86_64-w64-mingw32` over real mingw-w64 headers to check actual vtable layouts. **Exit: a real COM round trip with exact release counts** on Windows x64 and ARM64 CI (MinGW): registry-free fixture server via `DllGetClassObject`, create, alias, QI identity, `Clone`, `Advise` a btrc sink, fire, `Unadvise`, release all; server live 0, releases equal claims, sink count peaks at 2 and ends at 0, receiver destroyed once; plus `CreateStreamOnHGlobal` → QI `ISequentialStream`, last `Release` returns 0 | Linux (proxy, layout read); Windows CI (blocked on push) |
| 6 | Stage 29, Objective-C (I1) | `lifetime = "instantiated"` with `scope` and `terminal`; class-reference IR node; `superclass`/`overrides`; `error-out`; M3 downcasts; generic erasure | UIKit test-host app: process-scoped app delegate, instance-scoped scene delegate, `UIView` subclass with `layerClass`, `AVAudioSession` interruption notifications on the main queue; 100 scene connect/disconnect cycles without leaks | iOS simulator; Mac |
| 7 | Stage 29, JNI (A1) | Reader v2 (separate agent): annotations, inner classes, inherited lookup, `android.jar` scale, cache; `RegisterNatives` Java→btrc through M2 and the callback registration; `failure = "throw"`; `JavaWeak<T>`; array spans; `executor = "main"`; application `ClassLoader` | Emulator: Java calls btrc and back, weak clearing under `System.gc()`, activity lifecycle 100 cycles without leaked global refs; host JVM for everything but ART-specific checks | Linux (host JVM); Android emulator |
| 8 | Stage 31, GObject (`ui-1-linux-gobject-binding`) | `sink`, `sunk-results`, `release-executor`, `type-relation = "subtype"`, `parent`/`implements`, `signals` with weak source and `GClosureNotify` | Tier A, GLib only, no display: floating sink (not floating, count 1, one finalize), transfer-full `g_simple_action_new` with up/down casts at exact counts, `activate` signal with a receiver cycle broken by `scope.cancel()` (notify 1, finalize 1), weak source finalized while the scope lives, bad signal name throws with no leak; `-O2` and ASan/UBSan through both compilers; bootstrap byte-stable. Tier B (optional): `gtk_adjustment_new` with a class-field signature | Linux (nix `glib.dev`, `pkg-config`; `gtk4.dev` for tier B) |

Stage 27's other exits (native Windows btrcc importing Win32 headers, serial
and parallel build identity, PowerShell non-ASCII paths, 10 green Windows runs)
belong to the W1 lanes, not this plan; step 5's Windows evidence rides those
runners.

## 7. Open questions for the owner

1. **Java class reader language.** This plan picks strict C11 plus zlib
   (`tools/JavaClassReader.c`) for parity by construction and no compiler
   coupling. A btrc implementation would also work but would make the reader
   depend on a working btrcc of the same revision. Revisit only if the owner
   prefers btrc tools.
2. **`failure = "throw"` for Java entry.** Every other R3 boundary aborts. JNI
   is the one foreign runtime with a native exception channel the adapter can
   use safely, so the plan allows it for Java-entry thunks only (Stage 29).
3. **Free-threaded COM sinks and atomic ARC.** MTA sinks wait for the atomic
   ARC runtime (arc-runtime.md, "Cross-thread design").
4. **iOS slice timing.** Step 3's simulator evidence needs Stage 24's iOS
   target and Stage 25's simulator host. If either slips, step 3 lands with
   macOS evidence and the simulator row stays open on the Stage 27 exit.

## Review

Three read-only reviewers checked a complete draft of this document against
the tree: an ARC-soundness reviewer (leaks, double release and cycles across
the five models), an implementability reviewer (Python/btrc parity, the ASDL
generator and the file inventories), and a parity reviewer.

<!-- REVIEW-PLACEHOLDER -->
