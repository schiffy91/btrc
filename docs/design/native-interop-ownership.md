# Foreign interop ownership

Status: **design step 0 of PLAN.md Stage 27**, written 2026-10-02 on lane
`stage27/interop-design`. This is the one ownership plan that Stages 27, 29
and 31 implement for C function tables, Objective-C protocols and blocks, JNI,
COM and GObject. It changes no compiler code. Three reviewers checked it, and
every blocking finding is resolved below; see [Review](#review).

It extends the contracts already recorded in
[native-interop.md](native-interop.md), the native-binding sections of
[`src/language/package-manifest.md`](../../src/language/package-manifest.md),
[arc-runtime.md](arc-runtime.md) and [string-lifetime.md](string-lifetime.md),
and does not replace them. Where this document says "the existing X", X is
implemented in both compilers today and documented there.

## 1. One model: three relations, three mechanisms, two rules

### Relations

Every value that crosses a foreign boundary stands in exactly one of three
relations to btrc ARC. All five foreign models are expressed in these three
relations and nothing else. No model gets its own wrapper, holder runtime or
cancellation system.

| Relation | What it is | Existing owner | ARC effect |
|---|---|---|---|
| **R1. btrc owns a foreign claim** | One native claim held by a btrc value: a retain, a unique handle, a COM reference, a JNI global ref or a GObject reference. | Resources declared with `ownership = "unique"` or `"reference-counted"` (package-manifest.md, "Unique C resources" and "Managed reference-counted C resources"), and managed Objective-C instances (native-interop.md:326-332). | A unique resource has one ordinary btrc owner, and aliases retain that owner. A reference-counted resource keeps native identity, and each alias holds its own native claim. Native objects never get a btrc ARC header, and the cycle collector never traverses them. |
| **R2. A call borrows** | Arguments, results borrowed from an owner, Objective-C autoreleased values, JNI local refs, and temporaries inside one generated adapter. | Native call leases and cleanup slots; read-only call borrows; `borrowed-results`. | A borrowed resource argument holds one claim (or one owner retain) for the duration of the call, released in reverse order by normal cleanup. Nothing borrowed outlives the adapter frame. |
| **R3. Foreign code holds btrc** | A native object, table, COM sink, Objective-C holder, GObject signal closure or Java peer refers to a btrc receiver. | Callback-table holders (`resources.<R>.table`); `CallbackContext`, `CallbackScope`, `CallbackToken` and `CallbackRequest` in `src/stdlib/Callback.btrc`; generated Objective-C holders. | The foreign holder owns exactly **one external ARC claim** on a btrc `CallbackContext` (or, for tables, on the receiver). That claim changes `rc` only, never `edge_rc` (arc-runtime.md, "Exact-counter invariant"). The holder releases it on the foreign side's own final event: table release, `dealloc`, COM `Release` to zero, `GClosureNotify`, or an explicit Java peer `close()`. |

### Rules every model inherits

1. **Foreign-held cycles are never collected.** Consider a cycle that passes
   through an R3 claim: receiver → R1 owner → native object → holder →
   receiver. The collector cannot see it, because the holder's claim is an
   external root. Only **explicit cancellation** breaks such a cycle:
   - cancelling the `CallbackScope`;
   - calling `close()` on the R1 owner;
   - a declared terminal callback.

   This is the existing rule "do not rely on receiver/scope destructors alone
   to break a foreign-held cycle", now applied to every model. Where a cycle
   is directly visible in source, the analyzer rejects it for every R3 form:
   a class that implements the receiver interface of a registration may not
   declare a field, or a collection element, whose type is that
   registration's source resource (section 5).
2. **R3 entries pin what they call.** Every R3 entry does three things in
   order:
   - before calling btrc, it retains the receiver (`rc` +1) and pins the
     holder: it increments the holder's foreign-claim counter, or AddRefs the
     holder for COM;
   - it runs the call;
   - it releases both after the boundary.

   Final holder teardown is deferred to the outermost unpin. So a handler
   that cancels its own registration, closes its own stream, calls
   `Unadvise`, or reaches its terminal callback finishes against live memory.
   Every model's fixture includes a case that drops the last claim from
   inside the callback.
3. **Thread affinity is checked, never assumed.** ARC counters are not atomic
   yet (arc-runtime.md, "Cross-thread design"). Two manifest keys carry
   affinity in every model, and both take values from one closed set:

   | Key | Governs | Values |
   |---|---|---|
   | `executor` | R3 entry and M1 dispatch | `caller`, `main`, `main-context`, `apartment`, `realtime` |
   | `release-executor` | the final R1 release, and an R3 holder's final event | `caller`, `main`, `main-context`, `apartment`, `any` |

   The values mean the following:
   - `caller` is the creating thread, the existing meaning.
   - `main` is always the platform main/UI thread: the Apple main thread, or
     Android's `Looper.getMainLooper()` thread.
   - `main-context` is the thread captured by the stdlib GLib owner as the
     default main context's thread (section 2.5).
   - `apartment` is the COM apartment's creating thread.
   - `realtime` is the existing realtime-callback executor
     (package-manifest.md, "Registration-owned realtime C callbacks").
   - `any` permits a release on any thread, for free-threaded native
     reference counts.

   Thread identity is the `pthread_t` plus a per-thread generation counter,
   so a holder that outlives its thread cannot pass the check on a new thread
   that reuses the old TLS address. Today's holders compare
   `&__btrc_tls.try_top`; step 2 replaces that. Any R1 resource whose
   `release-executor` is not `any` cannot be captured by `spawn`; that is a
   compile-time error.
4. **An R3 final event on the wrong thread never touches ARC.** SDKs choose
   the thread for a holder `dealloc`, a COM `Release` to zero, or a
   `GClosureNotify` triggered by a worker's finalize. When that thread is not
   the holder's `release-executor`:
   - for `main`, the holder posts its claim release to the main thread:
     `dispatch_async` to the main queue on Apple, or the Android main
     `Looper` through the Java stdlib owner;
   - for `main-context`, it posts the release with `g_main_context_invoke`;
   - for `caller` and `apartment`, it aborts with "foreign holder released on
     the wrong thread".

   Java peers release their claim only through an explicit `close()` on
   their executor. A `Cleaner` that finds an unclosed peer reports a leak and
   never releases it.

### Mechanisms

The model has three shared mechanisms. Each is implemented once in each
compiler and reused by every model that needs it.

- **M1. Dispatch through a foreign table.** A generated adapter loads a
  function pointer from a foreign table and calls through it, null-checking
  both the table and the slot. Two receiver forms exist:
  - **Resource dispatch.** Used for C vtables and COM `lpVtbl`. The adapter
    holds an R2 lease on the R1 owner of the receiver. In `context` mode, the
    leased owner is the resource that owns the table record, and the context
    pointer is only an argument.
  - **Environment dispatch.** Used for JNI's `JNIEnv`. There is no lease,
    because the env is not a btrc value. The env is loaded from its
    per-thread key and null-checked.

  In both forms, unmapped slots are uncallable, and variadic slots are
  rejected only if a binding maps them.
- **M2. One holder shape for R3.** A generated holder contains:
  - the external claim (on a `CallbackContext`, or, for tables, on the
    receiver);
  - a foreign-claim counter;
  - the creating thread identity (rule 3);
  - a state word: `live`, `cancelled` or `dead`.

  The existing callback-table holder is the template. COM sinks and Java
  peers are instances of it. Objective-C holders keep their generated
  `NSObject` class, built around the same fields. At the zero transition the
  holder sets `dead` before releasing anything. An AddRef, QueryInterface or
  retain arriving in the `dead` state aborts. After cancellation, entries
  return the binding's declared no-op default without entering btrc.
- **M3. One checked conversion.** `(T?)value` on a foreign object behaves the
  same in every model:
  - null input yields null without calling the SDK;
  - a mismatch yields null;
  - a match yields a new R1 claim, taken before the source lease ends;
  - any other failure aborts.

  The existing CF cast is the template. Each model supplies only its test,
  through the existing key `type-query` (plus `type-tag` where needed). The
  new key `type-relation = "equal" | "subtype"` chooses how the result is
  compared; CF's relation is `equal`. The tests are:
  - CF: `CFGetTypeID`;
  - GObject: `g_type_check_instance_is_a`, with `subtype`;
  - COM: `QueryInterface`, generated without a `type-query` key;
  - Objective-C: `isKindOfClass:` or `conformsToProtocol:`;
  - JNI: `IsInstanceOf`.

  COM's `QueryInterface` already returns a claim, so it adds no retain. On a
  unique resource (a JNI global ref), M3 creates a **separate** owner, and
  `close()` on one owner does not close the other. Models whose `==` is not
  identity generate `sameObject(a, b)`: COM compares `IUnknown` identities,
  and JNI calls `IsSameObject`.

### Failure rule

- **F1. Foreign failure is translated inside the adapter.** The generated
  adapter first inspects the foreign failure:
  - HRESULT status;
  - `NSError` out-parameters;
  - Objective-C exceptions;
  - pending JNI exceptions;
  - GLib validation results.

  It then unwinds its own R2 state (autorelease pool, JNI local frame,
  leases). Only after that does a btrc exception start. No foreign unwind
  crosses generated C, and no btrc `longjmp` crosses a foreign frame.

  Each model spells the translation with one of a single family of keys:
  - `status-results` maps a function or dispatched method to a status kind.
    The first kind is `hresult`, where a negative value is a failure that
    throws after any adopted output is released.
  - `owned-outputs.status` uses the same vocabulary.
  - `error-outputs` is Objective-C `NSError**`.
  - JNI exceptions need no key, because every JNI call is checked.

  A btrc exception that escapes an R3 entry runs its local cleanup, then
  follows the binding's `failure`. The values are `abort` (existing) and
  `throw`, which is valid only for Java-entry thunks (section 2.3).

## 2. Per-model mapping

### 2.1 C function tables (Stage 27, step 2)

**Already implemented.** btrc *implementing* a table, through
`resources.<R>.table` (package-manifest.md, "Unique C callback tables"):
- Python: `native_imports.py:1565-1686` and `ir/lowering/functions.py:1239-1420`;
- btrc: `frontend/NativeImports.btrc:473-554` and `ir/lowering/Declarations.btrc`.

This is R3 through the M2 holder, with one claim per live table, SDK reopen
clones included.

**Missing.** btrc *calling* a table that the SDK hands it. Today a
function-pointer field imports as an unchecked `__fn_ptr<R, P...>` field,
with no null check and no lease on the receiver (`_callback_field`,
`native_imports.py:3436-3460`).

**Rules.**

- The native object owns its table. btrc never copies, frees, caches or
  retains a table pointer or a slot. Both are reloaded on every call, because
  SDKs swap tables when their state changes.
- A dispatched call is M1 resource dispatch:
  1. borrow the unique owner (`_begin_borrow`);
  2. load the table and check it for null;
  3. load the slot and check it for null;
  4. call;
  5. end the borrow.

  Closing through any alias during the call aborts. Calling on a closed owner
  aborts before the SDK runs. A callback may make reentrant calls on the same
  object; a reentrant close aborts (the existing unique rule).
- Every field of a dispatch-table record becomes private. That removes the
  unchecked `__fn_ptr` read path for these records.
- Arguments are R2 borrows: scalars, POD data pointers, and declared
  `borrowed-parameters` resources.
- Results are scalars or, through `owned-results`, resources. A raw pointer
  result is rejected unless it is declared as borrowed from the receiver.
- When a table `release` slot is named, final owner cleanup runs it exactly
  once. It cannot be combined with the resource's top-level `release`.
- In Stage 27, `dispatch` is accepted only on `unique` and `com` resources.

**Loopback.** Dispatching through a table that btrc itself implemented needs
no new mechanism. The R2 lease of the call composes with the R3 holder claim,
and rule 2's entry pin keeps the receiver alive if the callback closes its own
owner.

**Manifest.** `dispatch` is a new subtable beside `table`, and it reuses the
existing `context`/`context-index` spelling.

```toml
[native.bindings.resources.Codec]
ownership = "unique"

[native.bindings.resources.Codec.dispatch]
table = "vtbl"            # record field holding the table pointer
context = "user_data"     # optional; absent means the object itself is the receiver argument
context-index = 0         # parameter receiving the object (or the context)
executor = "caller"       # required
failure = "abort"         # required
release = "destroy"       # optional slot; excludes the resource's top-level release

[native.bindings.resources.Codec.dispatch.methods]
decode = "decode"
reset = "reset"
```

`borrowed-parameters`, `owned-results`, `owned-outputs` and `status-results`
can name a dispatched method with a three-part key,
`"Codec.decode.<parameter>"`. Both parsers accept the three-part form only
when the first part is a resource with `dispatch` and the second part is one
of its methods. The btrc parser counts parts from the right. Slot parameter
names come from the new `NativeField.callback_parameters` (section 3).

### 2.2 Objective-C protocols and blocks (Stage 27 step 3; Stage 29 step 6)

**Already implemented.**
- R1: managed instances, with generated ARC retain/release adapters.
- R3: stored and one-shot blocks, target/action, and stored delegates. These
  go through `CallbackContext`, `CallbackToken<Source, id>`, and a generated
  `NSObject` holder that owns one external claim on the context
  (package-manifest.md:314-716; `functions.py:2919-2960, 3432-3466`).
- Adapter units compile with ARC, Objective-C exceptions and `-Werror`, with
  the exception boundary nested inside the autorelease pool (F1).

The R3 chain is:

```
CallbackScope -> CallbackState -> CallbackContext<Receiver, CallbackToken<Source, id>>
CallbackContext -> receiver (strong), token (strong)
token -> source (strong), holder (strong, managed id)
holder -> context: one external ARC claim
native source -> holder: weak, assign or strong, per the SDK property
```

The token keeps the holder alive, so a `weak` or `assign` native delegate
property cannot let the adapter die early. The loop context → token → holder
→ context is deliberate, and only cancellation breaks it:
1. clear the slot through the setter, and verify through the getter;
2. drain;
3. drop the receiver and the token;
4. `dealloc` then releases the context.

The getter returns a retained, autoreleased value, so the verification runs
**inside the adapter's autorelease pool**. The holder's last release then
happens before scope teardown finishes, not in an outer pool.

The order "clear the slot, then release the holder" is **required** for
`assign` (`unsafe_unretained`) properties. Property ownership therefore
becomes a checked reader fact. For a `main_actor` setter or protocol, the
binding gets `executor = "main"` and `release-executor = "main"` by
derivation. A conflicting declared value is an error.

**Blocks.**
- `no_escape` is a hard fact, but its absence proves nothing. The binding
  therefore still declares `lifetime = "call" | "stored" | "one-shot"`.
- The generated adapter copies stored blocks (ARC) and releases them when the
  holder dies.
- A block property is `ownership = "copy"` with a `NativeObjectiveCBlock`
  type, and needs no new node.

**Stage 27 slice.** The exit is one checked delegate round trip on macOS and
on the iOS simulator test host. The slice adds analysis, not new runtime:
- The reader extracts protocol requirement closures, property ownership,
  protocol conformance and main-actor annotations (section 3).
- These binding errors become btrc diagnostics: `methods` omits a required
  method; `methods` selects a selector outside the requirement closure; the
  binding contradicts property ownership. Today they fail only at native
  `-Werror` compile time.
- A main-actor setter or protocol gets a main-thread check at publication and
  on entry, reusing the existing thread guard.

**Stage 29 I1 additions.** These are the same model with new modes:

- `lifetime = "instantiated"`, for adapters that UIKit creates by class name
  (`UIApplicationMain`, Info.plist scene delegates). The generated class's
  `-init` claims a receiver from a registered btrc factory.
  - `scope = "process"` makes the adapter a declared permanent root, outside
    leak accounting. A second instantiation aborts.
  - `scope = "instance"` releases the claim after the declared `terminal`
    method (`sceneDidDisconnect:`) or at `dealloc`. After `terminal`, later
    entries return no-op defaults.
- `superclass = "UIView"` with `overrides = [...]`, for CAMetalLayer hosting
  (`+layerClass`, `-layoutSubviews`).
  - The reader's `requires_super` fact forces the super send.
  - The reader's designated-initializer facts choose the init.
- `error-outputs` for `NSError**` parameters (F1). A `nil` error is success.
  A non-nil error becomes a btrc exception carrying `localizedDescription`.
- M3 checked downcasts through `isKindOfClass:` and `conformsToProtocol:`.
  Lightweight generics are erased to their bound for payloads.
- `id<P>` protocol handles stay deferred. WebGPU takes the `CAMetalLayer`
  pointer, so I1 does not need them.

### 2.3 JNI (Stage 27 step 4; Stage 29 step 7)

JNI uses all three relations and M1 environment dispatch. It adds no new
ownership idea.

**`JNIEnv`.** The env is per thread and is never stored in btrc data.

- `jni.h` is read by Clang through an ordinary C binding owned by the new
  stdlib package `src/stdlib/Java/`. Generated adapters dispatch through that
  binding's `JNINativeInterface_` record by M1 environment dispatch.
- Only the `...A` (`jvalue*`) call variants are mapped. The roughly 90
  variadic `Call*Method` slots and the reserved slots stay unmapped, and
  therefore uncallable.
- The thread's env lives in a `pthread_key_t` owned by `src/stdlib/Java/`.
  Lazy attach first calls `GetEnv`, and attaches only on `JNI_EDETACHED`,
  using `AttachCurrentThreadAsDaemon` so `DestroyJavaVM` cannot block on a
  btrc thread.
- The key stores a btrc-attached marker, and its destructor detaches only
  marked threads. Threads Java owns are never detached: Java-entry threads,
  the main thread, and SDK threads Java attached.
- POSIX runs key destructors after the thread's start routine returns.
  `__btrc_thread_wrapper` runs ARC thread cleanup before returning
  (`src/runtime/c/threads.c:43-57`), so the detach ordering is correct
  without a runtime hook. That cleanup may delete global refs and may attach
  lazily to do so; the destructor then detaches, as intended. The destructor
  touches no btrc TLS, which also keeps it correct under emutls on NDK API
  levels below 29.

**Local refs (R2).**
- Each generated adapter brackets its body with `PushLocalFrame(n)`, where n
  is computed from the signature and temporaries, and checks the result.
- If the push fails, `OutOfMemoryError` is pending. The adapter translates it
  through F1 **without** popping.
- Every path dominated by a successful push passes `PopLocalFrame(NULL)`,
  including F1's exception path.
- A loop inside one adapter deletes each element's local ref.
- No local ref reaches a btrc value.

**Global refs (R1), as unique resources.**
- Each selected Java class becomes a generated unique resource whose release
  is `DeleteGlobalRef`. There is one btrc owner per global ref, and aliases
  retain the owner.
- `close()` and final cleanup each delete the global ref at most once.
- An object result becomes `NewGlobalRef(local)` and a new owner before the
  frame pops. That owner is registered in a cleanup slot before the next env
  call that can throw.
- A borrowed argument passes the global ref directly, which is legal as a JNI
  argument, under the owner's borrow.
- Weak global refs (Stage 29) are a generated `JavaWeak<T>` unique resource
  that owns the `jweak`. Its `get()` returns `T?`: `NewLocalRef`, then a null
  check, then promotion to a new global owner.

**VM lifetime.** `src/stdlib/Java/` owns a `JavaVirtualMachine` owner.
- It counts live global and weak claims.
- It owns the `jclass` cache. Classes are cached as global refs, which keeps
  their method and field IDs valid; IDs are never released. The cache is
  outside the user claim count and is released before destroy.
- Destroying the VM with live user claims aborts.
- On Android the VM is never destroyed. On a host JVM, the test destroys it
  after every owner is closed.
- Class and ID initialization runs once per binding symbol, under the
  existing btrc mutex. (C11 `call_once` is missing on macOS.)
- Application classes resolve at `JNI_OnLoad` or through a cached application
  `ClassLoader` global ref, never through `FindClass` on an attached thread.

**F1.** Every env call outside a closed non-throwing set
(`ExceptionCheck`, `ExceptionClear`, `ExceptionOccurred`, `DeleteLocalRef`,
`DeleteGlobalRef`, `DeleteWeakGlobalRef`, `PopLocalFrame`, `Release*`) is
followed immediately by `ExceptionCheck`, with no other env call in between.
On a pending exception, the adapter:
1. calls `ExceptionOccurred`, then `ExceptionClear`;
2. promotes the throwable to a global ref;
3. pops the frame;
4. throws btrc `JavaException`.

The verifier enforces this placement (section 4).

**Strings.** Strings copy through UTF-16 (`GetStringRegion`, `NewString`),
transcoded to and from real UTF-8 in `src/stdlib/Java/`. `GetStringUTFChars`
and `NewStringUTF` are not used, because modified UTF-8 corrupts embedded NUL
characters and supplementary characters.

**Arrays.** Primitive arrays copy through `Get/Set<X>ArrayRegion`. Borrowed
spans (Stage 29) are released with `JNI_ABORT` when read-only.
`GetPrimitiveArrayCritical` is rejected.

**Java → btrc (Stage 29) is R3.**
- `RegisterNatives` thunks run over the M2 holder and the existing
  `caller`-executor callback boundary. They do not use
  `__btrc_native_thread_invoke`, which rejects nested entry and drains the
  thread's ARC state on every call (`threads.c:215-223`), so it cannot carry
  synchronous Java → btrc → Java → btrc nesting.
- The env is installed in the key for the duration of the call and restored
  afterwards.
- Consider a Java peer that holds a btrc receiver while btrc holds a global
  ref back to it. That is a foreign-held cycle. Break it by cancellation tied
  to `onDestroy`, or hold the back edge as `JavaWeak`.
- `failure = "throw"` turns a btrc exception into `ThrowNew` of
  `java.lang.RuntimeException`, carrying the message.

**Executors.** `executor = "main"` marks UI classes. `main` is the thread of
`Looper.getMainLooper()`, captured once by `src/stdlib/Java/` through its own
binding. If that thread cannot be established, `JNI_OnLoad` aborts.

**Metadata.** D22 fixes the source: a class-file reader over `android.jar`,
not C headers.
- **Output.** The reader's output is the same `native_abi.asdl` document
  (section 3), served through the same batch protocol as
  `tools/NativeHeaderReader.cpp`: `btrc.native-requests.v1` in,
  `btrc.native-responses.v1` out, with the same ordering, NUL handling and
  size and time limits. Both compilers decode it with their existing codecs.
- **The tool.** It is a separate build-time tool, `tools/JavaClassReader.c`,
  written in strict C11 plus zlib for jar inflate. It is built in `flake.nix`
  beside the header reader and needs no JVM and no LLVM.
- **Wiring in each importer.** Each importer gets a Java branch, inside the
  existing files:
  - the launch variable `BTRC_JAVA_CLASS_READER`, separate from
    `BTRC_NATIVE_HEADER_READER`;
  - the classpath from `BTRC_JAVA_CLASSPATH`, which the flake or Stage 23
    provisioning sets; manifests never expand `$VAR` paths;
  - Java groups never go through the native session or the cache-prepare
    protocol (`--prepare-native-session`, `--cached-native-read`);
  - `expected_target` and the document's `target_triple` come from the build
    target: the Android triple for device builds, the host triple for the
    host-JVM test;
  - the reader's identity and the classpath digest enter the resolution
    fingerprint.
- **Windows.** `cli/WindowsMain.btrc` has no reader today. Reading Java
  metadata on a Windows host waits for the W1 SDK-reader provider, through
  the same `FeNativeHeaderReader` seam.
- **Scope by stage.** Stage 27 ships reader v1: public classes, methods and
  fields of selected symbols, from a jar or a class directory. The reader
  omits non-public, synthetic and bridge members, so selecting one reports
  "unknown member". Stage 29's separate reader agent completes it:
  nullability annotations, inner classes, inherited lookup, `android.jar`
  scale, and caching.

**Manifest.** A Java binding has no `header` and no `standard`. Its validator
is separate from `_SOURCE_STANDARDS`, so Java never becomes a source-unit
language. The API level comes from the D21 target spec (floor API 29).
Members are selected by JNI descriptor, so overloads are never guessed, and a
dedicated symbol pattern accepts them.

```toml
[[native.bindings]]
module = "AndroidApp"
language = "java"
symbols = ["android.app.Activity",
           "android.app.Activity.getFilesDir()Ljava/io/File;"]
```

### 2.4 COM (Stage 27 step 5)

COM is a reference-counted R1 resource whose hooks are vtable slots, together
with M1 resource dispatch, M2 sinks and M3 `QueryInterface`.

**Claims.**
- Every interface pointer that arrives from a factory, from an `[out]` or
  `[out, retval]` `T**`, or from `QueryInterface` is one claim. Exactly one
  `Release` through the same pointer ends it.
- The `ULONG` returned by `AddRef` and `Release` is diagnostic only, and is
  discarded.
- `[in]` interface parameters are R2 borrows.
- The existing `owned-outputs` contract zero-initializes the slot before the
  call, so "adopt every nonnull output on every status" is sound, beyond what
  `_COM_Outptr_` guarantees.

**Status.** There are two forms, and a method uses at most one:
- **Existing:** `owned-outputs` keeps its result-class form (`result = ...`),
  with `status = "hresult"`, so the caller inspects the status.
- **New:** `status-results."IStream.clone" = "hresult"` makes failure throw,
  after any adopted output has been released (F1).

**Shape.**
- `ownership = "com"` joins the closed ownership set, alongside `unique` and
  `reference-counted`. It applies to a record typedef: `typedef interface
  IStream IStream;` represents `IStream*`.
- The importer checks slots 0–2 of the `lpVtbl` table against the real
  layout. They must be `QueryInterface(This, REFIID, void**)`,
  `AddRef(This)->ULONG` and `Release(This)->ULONG`.
- A manifest `base` is checked slot by slot, with signatures equal except for
  `This`, so widening is static.
- Methods use M1 `dispatch` with `table = "lpVtbl"`.

**Identity and casts.**
- `==` stays pointer equality. `sameObject(a, b)` compares `IUnknown`
  identities: it QIs both pointers, compares them, and releases both claims.
- `(IBar?)foo` lowers to `QueryInterface(&IID_IBar, &out)` (M3):
  - success is an owned claim;
  - `E_NOINTERFACE` gives null;
  - any other failure aborts;
  - a nonnull `*ppv` together with a failed HRESULT is adopted, then aborts.
- **GUIDs.** IIDs are referenced as the SDK's `extern const IID` objects and
  linked from `uuid`. Their values are not in Windows SDK C headers, so the
  reader does not carry them.

**Sinks (R3, M2).** A sink uses the same stored-registration shape as the
other models:
- Its factory key is `name`, as for `resources.<R>.table`. The factory takes
  a `CallbackScope` and returns `ICallbackRegistration`.
- `Advise` and `Unadvise` are declared as `register` and `unregister`, with
  `cancellation = "entry-barrier"` and `activation-failure`.
- The generated holder is `{ const Vtbl* lpVtbl; uint32_t comCount; context
  claim; thread; state }`, with one static const vtable.
- While `comCount > 0`, the holder holds **one** external claim on the
  `CallbackContext`. At zero, it sets `dead`, releases the claim and frees
  itself.
- `QueryInterface` answers `IID_IUnknown`, the declared IID and its bases,
  compared by `memcmp`. Anything else returns `E_NOINTERFACE` with
  `*ppv = NULL`.
- After cancellation, methods return `S_OK` without entering btrc. A source
  that keeps sink references after `Unadvise` then pins only the holder and
  the context, not the receiver.
- `AddRef` or `Release` from another thread follows rules 3 and 4. Both
  executors are `apartment`. Free-threaded (MTA) sinks are deferred.

**Apartments.** Apartments use `executor = "apartment"` and
`release-executor = "apartment"`. `CoInitializeEx` and `CoUninitialize`
belong to a stdlib `COMApartment` owner in `src/stdlib/COM/`. It counts live
claims, and an uninitialize with claims still live aborts.

**Allocators.** `BSTR` (freed with `SysFreeString`) and `CoTaskMemAlloc`
strings are not record pointers, so they are never R1 resources. They are
copied out with `copied-outputs` (`encoding = "utf-16"`, and `free =
"CoTaskMemFree"` or `"SysFreeString"`) and freed inside the adapter.

**Calling convention.**
- On x64 and ARM64 MinGW, Clang reports the convention of `STDMETHODCALLTYPE`
  as `CC_C`, which the reader emits as `c`.
- `x86_stdcall` (32-bit `__stdcall`) cannot be spelled in strict C11, and
  stays rejected.

**Rejected.**
- Aggregation: `pUnkOuter` must be hidden or null.
- Duplicate sink IIDs.
- Sink method names that collide with `IUnknown`.

```toml
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
read = "Read"
clone = "Clone"

[native.bindings.status-results]
"IStream.read" = "hresult"

[native.bindings.owned-outputs."IStream.clone.ppstm"]
result = "StreamClone"
status = "hresult"

[native.bindings.com-sinks.ICounterEvents]
name = "makeCounterEvents"
interface = "ICounterEventsHandler"
register = "ICounter.advise"
unregister = "ICounter.unadvise"
executor = "apartment"
failure = "abort"
activation-failure = "abort"
cancellation = "entry-barrier"
```

### 2.5 GObject (Stage 31 step 8, `ui-1-linux-gobject-binding`)

GObject is the existing `reference-counted` resource (`retain =
"g_object_ref"`, `release = "g_object_unref"`). On top of it come
floating-reference sinking, M3 subtype casts, and signals as existing stored
callbacks.

**Sinking.**
- A new resource key `sink = "g_object_ref_sink"`, and a new binding map
  `sunk-results` (function → mode), each mode producing exactly one btrc
  claim:
  - `floating-or-none` covers floating constructors and transfer-none results
    held by the library, such as `gtk_window_new`. The adapter sinks every
    non-null result: a floating reference is adopted, and a held one gains a
    reference.
  - `floating-or-full` covers `g_object_new`, which returns a floating
    reference only for `GInitiallyUnowned` subtypes. The adapter sinks only
    when `g_object_is_floating`, and otherwise adopts the full reference.
- `owned-results` stays transfer-full, and is never sunk.
- btrc never holds a floating reference. Every resource parameter therefore
  stays an ordinary R2 borrow, and a container's own sink adds its own
  reference.

**Transfer facts come from the manifest only.**
- In GTK they exist only in `.gir` files and gtk-doc, which Clang never sees,
  and function names are not a reliable guide.
- Reading `.gir` would add a second semantic input to two compilers, and
  would put binding policy into the header schema, which `native_abi.asdl`
  forbids.
- An offline tool that turns `.gir` into a manifest fragment may come later.
  It is never a compiler input.
- A wrong transfer declaration is a trusted promise that only the fixture's
  exact counts catch.

**Toggle refs are rejected.** btrc has no proxy object, so the problem toggle
refs solve does not arise. They would also add a third counter state to the
exact-counter invariant, and conflict with any other binding in the process.

**Signals (R3).** A signal is an existing stored C callback on
`g_signal_connect_data`'s handler parameter, using the existing keys
`context`, `unregister`, `lifetime`, `executor`, `failure`,
`activation-failure` and `cancellation`.
- GObject adds only four facts that the existing set lacks:
  - `signal`, the signal name;
  - `destroy-notify`, the `GClosureNotify` parameter;
  - `slot-check`, the still-connected query;
  - `signature` or `signature-typedef`.
- The rule "a stored C callback fails compilation" (package-manifest.md:404)
  is lifted for exactly this form.
- `data` is the context's external claim, and the generated `GClosureNotify`
  releases it, so disconnect or finalize frees it exactly once.
- The claim is taken only after validation:
  - `g_signal_parse_name` failing raises a recoverable exception, with no
    publication;
  - `g_signal_query` reporting an arity or return mismatch is terminal.

  If the connect call returns handler id 0, the adapter releases the claim
  explicitly and then aborts.
- The context holds the source as a `GWeakRef`, not strongly, so the instance
  and its context do not form a native cycle that only cancellation could
  break.
- Cancellation reads the weak ref. If the source is non-null and still
  connected, it disconnects (entry barrier). Then it releases.
- The handler signature always comes from a header type, never from manifest
  text: either `signature = "class-field:GtkAdjustmentClass.value_changed"`,
  or `signature-typedef` naming a typedef in the package's own header.
- `GCallback` erasure is the single typed cast inside the adapter.
- A `GClosureNotify` that a worker's finalize triggers off the executor
  follows rule 4. For `main-context` it is posted to the context; for
  `caller` it aborts.

**Cycles.** A widget's closure that holds a receiver, which in turn holds the
widget, is a foreign-held cycle. The independent `CallbackScope` breaks it.
A window's documented shutdown is `close-request` → `scope.cancel()` →
`gtk_window_destroy`.

**M3.**
- Downcasts use `type-query = "g_type_check_instance_is_a"` with `type-tag =
  "gtk_button_get_type"` and `type-relation = "subtype"`.
- Upcasts use `parent` and `implements`. The importer checks that the hooks
  are identical. Where the header exposes `<T>Class`, it also checks that the
  first field is `<Parent>Class`.

**Affinity.**
- A stdlib GLib owner captures the default main context's thread once, at
  application start or at the first `main-context` use.
- Checks compare that thread by `pthread_equal`.
  `g_main_context_is_owner` is not used, because it is false outside a
  running loop.
- Release, sink and borrow adapters of a `release-executor = "main-context"`
  resource check this thread. Capturing such a resource in `spawn` is a
  compile-time error (rule 3).

```toml
[native.bindings.resources.GObject]
ownership = "reference-counted"
retain = "g_object_ref"
release = "g_object_unref"
sink = "g_object_ref_sink"
release-executor = "any"
type-query = "g_type_check_instance_is_a"
type-tag = "g_object_get_type"
type-relation = "subtype"

[native.bindings.sunk-results]
g_object_new_with_properties = "floating-or-full"

[native.bindings.callbacks."g_signal_connect_data.c_handler"]
interface = "IActionActivate"
signal = "activate"
signature-typedef = "BtrcActivateHandler"
context = "data"
destroy-notify = "destroy_data"
unregister = "g_signal_handler_disconnect"
slot-check = "g_signal_handler_is_connected"
lifetime = "stored"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "entry-barrier"
```

## 3. The `native_abi.asdl` extension

`native_abi.asdl` stays semantic data with no policy. Ownership modes,
executors, transfers, sinks, signals and dispatch maps are binding policy.
They live in the package manifest, parsed by `frontend/packages.py` and
`frontend/Packages.btrc`. The schema grows only by facts a reader can
observe. All names are snake_case; the generator respells them camelCase for
`generated/native_abi/Models.btrc`.

The delta is **purely additive**:
- no constructor changes shape;
- `native_interface` stays a single-constructor type;
- no new field reuses an existing field name with a different shape.

The btrc renderer renames any field name used with two shapes
(`tools/compiler_codegen/ast.py:498-531`), which is why the Java class's
interface list is called `super_interfaces` and the protocol list is called
`protocol_declarations`. Every step runs `make compiler-codegen-generate` and
confirms that no existing btrc field was renamed.

```asdl
-- Step 1 (schema btrc.native-declarations.v2): function tables, later COM slots
native_field = NativeField(identifier name, native_type field_type, string offset_bits,
                           bool is_anonymous, bool is_bitfield, string width_bits,
                           native_parameter* callback_parameters)

-- Step 3 (schema v3): Objective-C slice
native_header = NativeHeader(string target_triple, string compiler_version,
                             bool big_endian, int character_bits,
                             native_declaration* exports, native_record* records,
                             native_interface* interfaces,
                             native_protocol* protocol_declarations)

native_interface = NativeObjectiveCInterface(identifier name, string identity, bool complete,
                                             string superclass,
                                             identifier* protocols,
                                             native_property* properties,
                                             bool main_actor)

native_protocol = NativeObjectiveCProtocol(identifier name, string identity, bool complete,
                                           identifier* protocols,
                                           native_requirement* requirements,
                                           native_property* properties,
                                           bool main_actor)

native_requirement = NativeProtocolRequirement(string selector, bool class_method,
                                               bool optional, identifier declaring_protocol)

native_property = NativeObjectiveCProperty(identifier name, string getter, string? setter,
                                           native_type value_type, string ownership,
                                           bool read_only, bool class_property)

-- NativeObjectiveCMethod gains three trailing fields:
--   bool designated_initializer, bool requires_super, bool main_actor

-- Step 4 (schema v4): JNI slice
native_declaration = ...
    | NativeJavaClass(identifier name, string identity, string binary_name,
                      string? super_name, identifier* super_interfaces,
                      bool interface_class, bool abstract_class, bool complete)
    | NativeJavaMethod(identifier name, string identity, identifier owner,
                       string method_name, string descriptor, native_type signature,
                       bool static_member, bool constructor, bool native_method)
    | NativeJavaField(identifier name, string identity, identifier owner,
                      string field_name, string descriptor, native_type value_type,
                      bool static_member, bool read_only)

native_type = ...
    | NativeJavaObject(identifier name, string binary_name)
    | NativeJavaArray(native_type element)
```

Each field, its source, and the step that consumes it:

| Field | Source | Consumer |
|---|---|---|
| `NativeField.callback_parameters` | Names come from the field's `FunctionProtoTypeLoc`. `no_escape`, `ns_consumed` and `cf_consumed` come from `ExtParameterInfo`. The list is empty unless the field's type, after aliases and qualifiers, is a pointer to `NativeFunctionType`. Otherwise there is exactly one entry per parameter, and a length mismatch is a codec error. | Step 2: three-part keys and consumed-argument checks. Step 5: COM slot names. |
| `NativeHeader.protocol_declarations` | `ObjCProtocolDecl`, in its own namespace. `NSObject` is both a class and a protocol. | Step 3: requirement and property checks. |
| `NativeObjectiveCInterface.protocols` | `all_referenced_protocols`. | Step 3: conformance of the slot's source class. |
| `properties` | `ObjCPropertyDecl`. `ownership` is one of `strong`, `weak`, `copy`, `assign` or `unsafe_unretained`, from `getSetterKind()`; `assign` on an object type is reported as `unsafe_unretained`. A class property is never a delegate slot. | Step 3: slot ownership. |
| `main_actor` (interface, protocol, method) | `SwiftAttrAttr` text `@MainActor` or `@UIActor`. `NS_SWIFT_UI_ACTOR` expands to the latter. | Step 3: derived `main` executors. |
| `requirements` | The full inherited closure from `ObjCProtocolDecl::protocols()` and `isOptional()`, sorted by selector and then `class_method`. `declaring_protocol` names the protocol in the "missing required method" diagnostic. | Step 3. |
| `designated_initializer`, `requires_super` | `isDesignatedInitializerForTheInterface`, `ObjCRequiresSuperAttr`. | Step 6. |
| `NativeJavaClass` | The class file's `this_class`, `super_class`, `interfaces` and access flags. `identity` is the descriptor `Landroid/app/Activity;`. | Step 4: resources. `interface_class` and `abstract_class` select interface dispatch and suppress constructors. |
| `NativeJavaMethod`, `NativeJavaField` | Method and field tables. `identity` is the smali form `Landroid/app/Activity;->getFilesDir()Ljava/io/File;`. `read_only` is `ACC_FINAL`. | Step 4: `static_member`, `constructor` and `read_only`. Step 7: `native_method` for `RegisterNatives`. |
| `NativeJavaObject`, `NativeJavaArray` | Descriptors. | Step 4. |

Java conventions:
- Primitives reuse `NativeBuiltin`: `jint` is 32-bit signed, `jchar` is
  16-bit unsigned and `jboolean` is 8-bit unsigned.
- Nullability reuses `native_qualifiers.nullability` and is nullable until
  the Stage 29 reader reads annotations.
- `static final` constants reuse `NativeConstant` and
  `NativeStringConstant`.
- For a class-file document, `compiler_version` is `btrc-class-reader/1
  sha256:<classpath digest>`, and declarations carry `source_file =
  "<jar>!<path>.class"` with `line = 0` and `column = 0`.

**Calling conventions.** `NativeFunctionType.calling_convention` keeps its
shape but widens its vocabulary. The reader reports `c`, `x86_stdcall`,
`win64` (Clang's `CC_Win64`, `ms_abi` on a non-Windows target), `aapcs`, and
so on, instead of rejecting them (`NativeHeaderReader.cpp:569-577`). Both
importers reject everything except `c` until a convention is qualified.
`_type_identity` already includes the convention, so C-convention identities
do not change.

**Versioning.** Both codecs match keys exactly
(`native_imports.py:4737`). Each step therefore bumps the document schema:
- `btrc.native-declarations.experimental` becomes `v2` in step 1;
- `v3` in step 3;
- `v4` in step 4.

Each bump comes with both codecs in the same commit, so a reader and a
compiler from different steps fail with the schema error, not with a field
error. The header cache is keyed by the reader's digest, so a rebuilt reader
never serves a stale document.

**Considered and left out.**
- GUID initializer values: absent from SDK headers; IIDs are linked instead.
- SAL annotations: empty macros in MinGW; the manifest is authoritative.
- GObject transfer annotations: they live in `.gir` (section 2.5).
- A deprecation attribute: P1's availability record owns that.
- Several Java facts with no consumer: generic signatures, `throws` lists,
  `final` methods and classes, outer-class names.
- A shared "resolved binding semantics" schema: binding policy already has
  one parser per compiler and does not belong in the reader schema.

## 4. Compiler work in both compilers

Every construct lands **Python first, then its btrc twin, one commit per
construct**. The generator is regenerated in the Python commit. Every file
below already exists, so the 88-file Python and 97-file btrc inventories do
not change.

| Construct | Python owner | btrc twin |
|---|---|---|
| ASDL | `src/language/native_abi.asdl` → `abi/native_generated.py` | → `generated/native_abi/Models.btrc` |
| Readers | `tools/NativeHeaderReader.cpp` (C family); new `tools/JavaClassReader.c` | shared tools |
| Codec and reader launch | `NativeHeaderCodec` and the reader launch code in `frontend/native_imports.py` | `frontend/NativeImports.btrc` |
| Manifest keys | `frontend/packages.py` | `frontend/Packages.btrc` |
| Projection and checks | `NativeDeclarationImporter` (`native_imports.py`), for example `_project_dispatch_tables` beside `_project_callback_tables` | `FeNativeDeclarationImporter` (`NativeImports.btrc`) |
| Analyzer rules (private dispatch slots, direct R3 cycles, `spawn` capture) | `analyzer/expressions.py`, `analyzer/ownership.py` | the `analyzer/` and `analyzer/ownership/` owners |
| Adapter lowering | `ir/lowering/functions.py` | `ir/lowering/Declarations.btrc` |
| Verification | `ir/verifier.py` (`IRVerifier`) | a new validator class in `ir/optimization/Cleanup.btrc`, called from `ir/optimization/Optimizer.btrc` where `RealtimeIRVerifier` runs |

**New manifest keys and values.** No key outside this list is accepted, and
every other key keeps its existing closed set.

| Key or value | Where | Step |
|---|---|---|
| `dispatch` subtable: `table`, `context`, `context-index`, `executor`, `failure`, `release`, `methods` | resources | 2 |
| Three-part `"<R>.<method>.<parameter>"` names | `borrowed-parameters`, `owned-results`, `owned-outputs`, `status-results` | 2 |
| `release-executor` with `caller`/`any` | resources | 2 |
| `executor = "main"`; `release-executor = "main"`, derived from `main_actor` | Objective-C callbacks and resources | 3 |
| `language = "java"` (no `header` or `standard`); descriptor symbols | `[[native.bindings]]` | 4 |
| `ownership = "com"`, `iid`, `base` | resources | 5 |
| `executor` and `release-executor` = `apartment` | COM resources, dispatch, sinks | 5 |
| `status-results` | binding map | 5 |
| `status = "hresult"` | `owned-outputs` | 5 |
| `copied-outputs` (`encoding`, `free`) | binding map | 5 |
| `com-sinks` (`name`, `interface`, `register`, `unregister`, `executor`, `failure`, `activation-failure`, `cancellation`) | binding map | 5 |
| `lifetime = "instantiated"`, `scope`, `terminal`, `superclass`, `overrides` | Objective-C callbacks | 6 |
| `error-outputs` | binding map | 6 |
| `failure = "throw"`; `executor = "main"` for Java | Java entry thunks, Java classes | 7 |
| `sink` | resources | 8 |
| `sunk-results` (`floating-or-none`, `floating-or-full`) | binding map | 8 |
| `type-relation`, `parent`, `implements` | resources | 8 |
| `executor`/`release-executor` = `main-context` | GObject | 8 |
| `signal`, `destroy-notify`, `slot-check`, `signature`, `signature-typedef` | stored C callbacks | 8 |

**Lowering stays structured.**
- **M1** needs no new IR node. `IRCall.callee` already takes an `IRExpr`
  (`ir/nodes.py:202-206`; btrc `IRNode.indirectCall`, `ir/Model.btrc:331`).
  The adapter declares the table and the slot as `IRVarDecl`s, guards each
  with `_native_null_guard` (btrc `nativeNullGuard`,
  `Declarations.btrc:143`), and calls through the slot. If a slot local
  cannot be spelled, `IRFunctionPointerTypedef` (`nodes.py:400`) supplies the
  type.
- **M2** holders are `IRStructDef`s, plus static `IRFunctionDef`s and a static
  const table global.
- **Objective-C** uses the existing `IRObjectiveCClass`, `IRObjectiveCMethod`,
  message, block, autorelease-pool and exception-boundary nodes. Stage 29's
  instantiated adapters add one expression node for a class reference, beside
  `IRObjectiveCSelector`.
- The emitter only renders.

**Verifier rules.** These are new, in both compilers:

1. A call whose callee is a value loaded from a private field of a native
   dispatch-table record appears only inside a generated native adapter, after
   the table and slot null checks. Other expression callees are unaffected:
   interface dispatch, lambdas, collection callbacks and blocks.
2. In a JNI adapter:
   - every env call outside the non-throwing set is followed immediately by
     its `ExceptionCheck` branch;
   - every path dominated by a successful `PushLocalFrame` passes
     `PopLocalFrame`;
   - an R1 owner created inside the frame is registered in a cleanup slot
     before the next throwing env call.
3. A generated R3 entry checks its executor, retains its receiver and pins its
   holder before any btrc call (rules 2 and 3).

**Runtime.** This plan adds no `src/runtime/c` asset and no `manifest.toml`
rows. The holders reuse the existing thread check, which step 2 upgrades to
`pthread_t` plus generation, and `__btrc_safe_calloc`. Callback state stays in
`src/stdlib/Callback.btrc`. New stdlib packages hold the rest:
- `src/stdlib/Java/`: `JavaVirtualMachine`, the env key, attach and detach,
  exception translation, UTF-16, and the `jni.h` binding;
- `src/stdlib/COM/`: `COMApartment`;
- a GLib main-context owner in the Linux GUI provider.

Each new package needs a row in `src/stdlib/btrc.toml`, a package
`btrc.toml` with providers, a README, and regenerated `btrc.symbols` and
`btrc.lock`. If an implementation step finds a runtime row unavoidable, it
goes through the `runtime/c` single owner and D14, as usual.

**Toolchain and link plans.**

| Model | Toolchain inputs | Link plan |
|---|---|---|
| Java | zlib (reader); a JDK for `javac` and `libjvm` (host test); `android.jar` from the Stage 23 Android SDK provisioning | a host test links `libjvm`; Android links nothing extra |
| COM | — | `ole32`, `uuid` |
| GObject | `glib.dev` and `pkg-config` (`gtk4.dev` for tier B) | `gobject-2.0` (`gtk4` for tier B) |

Every new input is a `flake.nix` change. A missing input is a classified
skip in PLAN.md Stage 2's skip ledger, never a silent one.

## 5. Diagnostics

Every compile-time diagnostic is a source-mapped `NativeImportError` or
analyzer error, with identical text in both compilers. The parity tests
compare the texts.

**All models.**
- A receiver class that holds a field or collection element of its own
  registration's source resource type (a direct R3 cycle).
- A `spawn` capture of a resource whose `release-executor` is not `any`.
- An executor value outside the closed set.
- An `executor` that conflicts with a derived `main`.

**Function tables.**
- A non-function slot, or a mapped variadic slot.
- A convention other than `c`.
- A wrong receiver type at `context-index`.
- An unmapped-but-selected, duplicate or unknown slot.
- `table` is not a pointer to a complete record.
- A slot `release` together with a top-level `release`.
- A method name that shadows `close`/`isOpen` or a selected symbol.
- A managed btrc value in a slot signature.
- A raw pointer result with no declared borrow.
- A `callback_parameters` length mismatch.
- An unsupported `executor` or `failure`.
- Reading, writing or taking the address of a dispatch-record field: "native
  dispatch slot is private; call it through `<R>.<m>()`".

**Objective-C.**
- A required method is missing from `methods`. The error names the
  `declaring_protocol`.
- A selector outside the requirement closure.
- Property ownership that contradicts the mode: a strong delegate mapped as a
  vacant slot, or a read-only or class property used as a slot.
- `no_escape` with a stored or one-shot mapping.
- An override that does not send the `requires_super` call.
- No usable designated initializer.
- A duplicate adapter class name.
- An unmapped object result or generic `id<P>` payload.

**JNI.**
- An unknown class or member, including non-public, synthetic and bridge
  members, which the reader omits.
- An overloaded name without a descriptor.
- An unsupported class-file major version.
- A missing `BTRC_JAVA_CLASSPATH`.
- A `RegisterNatives` target that is not `ACC_NATIVE`.
- A nullable result used as non-null.
- Generic arguments, which are erased.
- User code that names reserved env hooks.
- A reader error that is not attributed to its own binding, or that is filled
  from a sibling.

**COM.**
- Slots 0–2 are not IUnknown-shaped.
- A `base` prefix mismatch.
- `iid` is not a read-only `GUID` global.
- An `owned-outputs` parameter that is not a mutable `Interface**`.
- `status = "hresult"` or `status-results` on a result that is not 32-bit
  signed.
- Both status forms on one method.
- A visible `pUnkOuter`.
- `x86_stdcall`.
- A `copied-outputs` allocator that is not selected, or has the wrong
  signature.
- Duplicate sink IIDs.
- Sink names that collide with `IUnknown`.

**GObject.**
- A function in both `owned-results` and `sunk-results`.
- `sink` on a resource that is not reference-counted.
- A transfer-container result.
- `parent` contradicted by the class struct or by different hooks.
- `signature` naming a non-function field, or one whose first parameter is
  not the owner.
- An unannotated resource result.

**Runtime terminal errors.** Each has its own message and fires before
control enters the SDK.
- A closed owner; a close during an admitted call, or a reentrant close.
- A null table or slot.
- The wrong executor, apartment or main context.
- A holder released on the wrong thread (rule 4).
- An AddRef or QI on a `dead` holder.
- A btrc exception crossing an R3 boundary with `failure = "abort"`.
- A scope destroyed before cancellation (existing).
- JNI: `GetMethodID` returning null ("metadata/runtime API mismatch", plus
  the identity); an exception already pending on adapter entry; an exception
  while translating an exception; no `JavaVM`; destroying the VM with live
  claims.
- COM: QI failing with anything other than `E_NOINTERFACE`; a nonnull `*ppv`
  together with failure; `CoUninitialize` with live claims.
- GObject: a signal arity mismatch; connect returning handler id 0.
- Objective-C: a second instantiation of a process-scoped adapter; a factory
  returning null.

**Recoverable btrc exceptions.**
- Translated foreign failures (F1).
- `JavaException`.
- An invalid GLib signal name.

Realtime paths keep `__builtin_trap`, without logging, as today.

**Trusted, documented, not provable.**
- An SDK does not free an object inside its own slot call.
- Slots are thread-safe.
- Manifest transfer facts (`sunk-results`, `owned-outputs`, COM `[out]`).
- A JNI metadata jar matches the device runtime.

## 6. Ordered implementation plan

The order follows PLAN.md Stage 27: function tables, then the Objective-C
slice, then the JNI slice, then COM. Each step has one owner, covering the
ASDL, both importers and lowering. A mirror agent ports each construct to
btrc, and the fixture author supplies the fixture.

Each step ends with:
- its focused suite through both compilers;
- `make test`;
- **a bootstrap for the feature**, as Stage 27's exit requires.

In the "Where" column, "Linux" means runnable in the cloud and in the
`linux-ci` container, "Mac" means the M1 host, and the device rows follow the
Stage 25 test hosts and D8.

| # | Step | Commits (each Python, then btrc) | Tests and exit evidence | Where |
|---|---|---|---|---|
| 1 | Schema v2 | <ul><li>`NativeField.callback_parameters`</li><li>reader emits slot semantics and real conventions</li><li>both codecs</li><li>importers reject conventions other than `c`</li></ul> | <ul><li>Reader goldens for slot names and `no_escape`</li><li>Codec round trip and length-mismatch rejection</li><li>Generated-source check, with no renamed btrc field</li></ul> | Linux |
| 2 | **Function-table calls** (`platforms-interop-function-table-calls`) | <ul><li>`dispatch` keys and three-part names</li><li>`_project_dispatch_tables`</li><li>private dispatch records</li><li>M1 adapters</li><li>verifier rules 1 and 3</li><li>direct-cycle rule</li><li>R3 entry pinning and the `pthread_t` + generation check for the existing table holder</li></ul> | <ul><li>`Codec` vtable fixture:<ul><li>decode and reset</li><li>a table swap (proves no caching)</li><li>alias plus `close()` runs `destroy` once</li><li>live count 0 after 1,000 iterations</li></ul></li><li>Loopback through the existing `Reader` table in `context = "user_data"` mode, including a method that closes its own stream mid-call</li><li>Negatives: a null slot aborts; a close inside a callback aborts; a slot read is rejected; a self-cycle is rejected</li><li>**Exit: passes at `-O2` and under ASan/UBSan** in both compilers</li><li>The fixture gains a Linux sysroot variant of `native_project`, which today skips off macOS (`native_import_fixtures.py:49`)</li></ul> | Linux, Mac |
| 3 | **Objective-C slice** (first slice of `platforms-i1-objc-protocol-adapters`) | <ul><li>Schema v3: protocols, properties, requirements, `main_actor`, method flags</li><li>reader extraction and codecs</li><li>required-method, property-ownership and main-actor checks</li><li>derived `main` executors</li><li>slot verification inside the pool</li></ul> | <ul><li>Linux: reader goldens only, invoked directly with `objc_root_class` fixtures. Both importers reject Objective-C bindings off macOS targets (`native_imports.py:1067-1069`), so diagnostics run on the Mac.</li><li>Extend `test_native_objective_c_delegates.py` with:<ul><li>`weak` and `strong` property variants</li><li>an optional method</li><li>a missing-required-method rejection</li><li>a main-actor guard</li><li>an off-thread holder release (rule 4)</li></ul></li><li>**Exit: a checked delegate round trip on macOS and on the iOS simulator.** The same Foundation-only fixture is cross-compiled for `arm64-apple-ios17.0-simulator` and run with `simctl spawn`. It needs Stage 24's iOS target and Stage 25's simulator host. If the iOS 17 runtime cannot be installed, it uses D8's oldest installable runtime, with the iOS 17 deployment target compile-checked.</li></ul> | Linux (reader); Mac; iOS simulator |
| 4 | **JNI slice** (first slice of `platforms-a1-checked-jni`) | <ul><li>Schema v4: Java constructors</li><li>`tools/JavaClassReader.c` v1 and its flake build</li><li>the importers' Java branch and `language = "java"` validator</li><li>`src/stdlib/Java/` (VM owner, env key, attach/detach, exceptions, UTF-16, `jni.h` binding)</li><li>class resources (global refs), static and instance calls, fields, local frames</li><li>verifier rule 2</li></ul> | <ul><li>Reader goldens over javac-built fixture classes.</li><li>Host-JVM test: `JNI_CreateJavaVM` with `-Xcheck:jni`, where any CheckJNI warning fails. It covers:<ul><li>a string round trip of `"a\0é𝄞"`</li><li>a static field read</li><li>a Java exception becoming `JavaException`</li><li>a btrc-spawned thread attaching and detaching</li><li>10,000 object-returning calls with no frame leak</li><li>user global-ref count 0, then `DestroyJavaVM`</li></ul></li><li>**Exit: a checked JNI call makes one round trip on the emulator test host**: `app_process` with a pushed `.dex` and `.so`, `debug.checkjni 1`, and no CheckJNI abort in logcat, on API 29, the current API and the 16 KiB-page image (D8).</li></ul> | Linux (host JVM); Android emulator |
| 5 | **COM** (`platforms-w1-win32-com-imports`) | <ul><li>`ownership = "com"`, slot-hook validation, `base`</li><li>`dispatch` over `lpVtbl`</li><li>M3 `QueryInterface`, `sameObject`</li><li>`status-results`, `owned-outputs` status, `copied-outputs`</li><li>`com-sinks` over `CallbackContext`</li><li>`src/stdlib/COM/` `COMApartment`</li></ul> | <ul><li>**Linux proxy** (`ComShape.h`: `int32_t HRESULT`, `uint32_t ULONG`, `GUID`, extern IIDs, a flattened IUnknown prefix, and a counter server with live/AddRef/Release hooks). It proves slot validation, dispatch, claim adoption, QI, the sink holder (including `Unadvise` inside an event), cycle teardown, and exact counts under sanitizers.</li><li>The reader runs with `--target=x86_64-w64-mingw32` over real mingw-w64 headers, to check the actual vtable layouts.</li><li>**Exit: a real COM round trip with exact release counts** on Windows x64 and ARM64 CI (MinGW), after the D4 push. A registry-free fixture server is reached via `DllGetClassObject`. The test creates the object, takes an alias, checks QI identity, calls `Clone`, `Advise`s a btrc sink, fires an event, calls `Unadvise`, and releases everything. It asserts:<ul><li>the server's live count is 0</li><li>releases equal claims</li><li>the sink count peaks at 2 and ends at 0</li><li>the receiver is destroyed once</li></ul>A second test runs `CreateStreamOnHGlobal`, QIs to `ISequentialStream`, and checks that the last `Release` returns 0.</li></ul> | Linux (proxy, layout read); Windows CI |
| 6 | Stage 29: Objective-C (I1) | <ul><li>`lifetime = "instantiated"` with `scope` and `terminal`</li><li>class-reference IR node</li><li>`superclass` and `overrides`</li><li>`error-outputs`</li><li>M3 downcasts</li><li>generic erasure</li></ul> | <ul><li>A UIKit test-host app with:<ul><li>a process-scoped app delegate</li><li>an instance-scoped scene delegate</li><li>a `UIView` subclass with `layerClass`</li><li>`AVAudioSession` interruption notifications on the main queue</li></ul></li><li>100 scene connect/disconnect cycles without leaks.</li><li>Physical device: awaiting hardware (D8).</li></ul> | iOS simulator; Mac |
| 7 | Stage 29: JNI (A1) | <ul><li>Reader v2, by the separate agent</li><li>`RegisterNatives` Java→btrc through M2 and the `caller` boundary</li><li>`failure = "throw"`</li><li>`JavaWeak<T>`</li><li>array spans</li><li>`executor = "main"` from the main `Looper`</li><li>the application `ClassLoader`</li></ul> | <ul><li>On the emulator:<ul><li>Java calls btrc, and btrc calls back</li><li>nested Java→btrc→Java→btrc</li><li>weak refs clear under `System.gc()`</li><li>100 activity lifecycle cycles with no leaked global refs</li></ul></li><li>The host JVM covers everything except ART-specific checks.</li><li>Physical arm64 device: awaiting hardware (D8).</li></ul> | Linux (host JVM); Android emulator |
| 8 | Stage 31: GObject (`ui-1-linux-gobject-binding`) | <ul><li>`sink` and `sunk-results` modes</li><li>`release-executor`</li><li>`type-relation = "subtype"`, `parent`, `implements`</li><li>signal stored callbacks with a weak source and `GClosureNotify`</li><li>the GLib main-context owner</li></ul> | <ul><li>**Tier A** (GLib only, no display):<ul><li>a floating sink: not floating afterwards, count 1, one finalize</li><li>`g_object_new` on a non-floating type adopted at count 1</li><li>transfer-full `g_simple_action_new` with up- and down-casts at exact counts</li><li>an `activate` signal whose receiver cycle is broken by `scope.cancel()`: notify 1, finalize 1</li><li>a weak source finalized while the scope lives</li><li>a bad signal name throws, with no leak</li><li>a handler that cancels itself</li><li>`-O2` and ASan/UBSan through both compilers; the bootstrap is byte-stable</li></ul></li><li>**Tier B** (`gtk_adjustment_new`, a class-field signature, `gtk_window_new` sinking) is required before `ui-1-linux-gtk-spike` starts.</li></ul> | Linux |

Stage 27's other exits belong to the W1 lanes, not to this plan:
- a native Windows btrcc importing Win32 headers;
- serial and parallel builds producing identical output;
- PowerShell builds from non-ASCII paths;
- 10 green Windows runs.

Step 5's Windows evidence rides on those runners. W1 stays open until Stage
28's ABI-route decision.

## 7. Open questions for the owner

None of these blocks Stage 27. Each records a choice that this plan made, so
the owner can overturn it.

1. **Which language the Java class reader is written in.** This plan picks
   strict C11 plus zlib, which gives parity by construction and no coupling to
   the compiler. A btrc implementation would also work, but the reader would
   then depend on a working btrcc of the same revision.
2. **`failure = "throw"` for Java entry.** Every other R3 boundary aborts. JNI
   is the one foreign runtime with an exception channel that the adapter can
   use safely, so the plan allows `throw` for Java-entry thunks only.
3. **Free-threaded COM sinks.** Both MTA sinks and `release-executor = "any"`
   holders wait for the atomic ARC runtime (arc-runtime.md, "Cross-thread
   design").
4. **Timing of the iOS slice.** Step 3's simulator evidence needs Stage 24's
   iOS target and Stage 25's simulator host. If either slips, step 3 lands
   with macOS evidence, and the simulator row stays open on the Stage 27 exit.

## Review

Three read-only reviewers checked the first complete draft (commit `c9b8545`)
against the tree:
- an ARC-soundness reviewer, covering leaks, double release and cycles across
  all five models;
- an implementability reviewer, covering Python/btrc parity, the ASDL
  generator and the file inventories;
- a parity reviewer, covering consistency across models and the PLAN.md and
  platform-parity requirements.

They raised 44 findings, 13 of them blocking. Every finding is resolved in
the text above. **No blocking finding remains unresolved.** The five drafting
reports (one per foreign model) and these three reviews were session
transcripts on lane `stage27/interop-design`; their substance is recorded
here.

### ARC soundness (4 blocking, 11 non-blocking)

| # | Finding | Resolution |
|---|---|---|
| A1 | **Blocking.** An R3 final event on an SDK-chosen thread (block `dealloc` on GCD, a worker finalize, COM `Release`, a Java `Cleaner`) runs `requireExecutor` and aborts correct programs. | Rule 4: post the release to `main` or `main-context`, or abort for `caller` and `apartment`. Java peers release only by explicit `close()`. Fixtures add off-thread final releases. |
| A2 | **Blocking.** No lease across an R3 entry: the existing table holder frees itself and the receiver when the last claim drops mid-call (`functions.py:1292-1312, 1370-1388`). | Rule 2: retain the receiver and pin the holder for every entry, and defer teardown to the outermost unpin. Verifier rule 3. A per-model fixture drops the last claim inside the callback. |
| A3 | **Blocking.** `g_main_context_is_owner` is false outside a running loop. | §2.5: capture the context's thread once and compare with `pthread_equal`. |
| A4 | **Blocking.** Nothing owns the JVM's lifetime; deletes could run after `DestroyJavaVM`; cached classes contradicted "count 0". | §2.3 `JavaVirtualMachine` owner: claim count, abort on destroy with live claims, class cache outside the user count, `AttachCurrentThreadAsDaemon`. |
| A5 | Attach provenance; emutls ordering. | `GetEnv` first, a btrc-attached marker, and no btrc TLS in the destructor. |
| A6 | A failed `PushLocalFrame`; owners created inside the frame. | Translate without popping; pop on paths dominated by a successful push; register owners before the next throwing call. |
| A7 | Java entry must not use `__btrc_native_thread_invoke`; `main` captured at `JNI_OnLoad` is wrong. | Use the `caller` boundary; `main` comes from `Looper.getMainLooper()`. |
| A8 | COM sinks had no cancellation owner, and no resurrection guard. | Sinks hold a `CallbackContext` claim; `Unadvise` is `unregister`; `S_OK` after cancellation; the `dead` state aborts AddRef/QI. |
| A9 | `sunk-results` could not describe `g_object_new`. | Modes `floating-or-none` and `floating-or-full`. |
| A10 | Connect returning 0 leaks the claim. | Claim only after validation; release explicitly, then abort. |
| A11 | Affinity covered only GObject. | Derived `main` for `main_actor`; the `spawn` capture rule for every non-`any` resource. |
| A12 | Holder thread identity can be reused by a new thread at the same TLS address. | `pthread_t` plus generation (rule 3, step 2). |
| A13 | `table = "*"` and `context` mode had no lease owner. | M1 resource dispatch versus environment dispatch; context mode leases the table record's owner. |
| A14 | Getter verification autoreleases outside the pool; post-`terminal` entries were unspecified. | Verify inside the adapter pool; `terminal` bars entries. |
| A15 | A wrong section reference; the COM `owned-outputs` example lacked `result`; it conflicted with F1. | Fixed; the two status forms are now explicit and mutually exclusive. |

### Implementability and Python/btrc parity (3 blocking, 11 non-blocking)

| # | Finding | Resolution |
|---|---|---|
| B1 | **Blocking.** Verifier rule 1 as written rejects the current tree: interface dispatch, lambdas, collection callbacks and blocks all use expression callees. | Rule 1 now covers only callees loaded from private dispatch-table fields. |
| B2 | **Blocking.** The Java reader did not fit the launch path: there is a single reader variable, clang argv, target and sysroot checks, session prepare, `header`/`symbols`/`_SOURCE_STANDARDS`, `$VAR` paths, and Windows has no reader. | §2.3 "Metadata": a separate `BTRC_JAVA_CLASS_READER` and `BTRC_JAVA_CLASSPATH`, no session or cache prepare, target-derived `expected_target`, a fingerprint entry, a separate validator with no `header` or `standard`, a descriptor symbol pattern, and the Windows dependency on W1's provider. |
| B3 | **Blocking.** `NativeJavaClass.interfaces` (an identifier list) collides with `NativeHeader.interfaces` (a node list) in the btrc renderer, renaming every consumer. | Renamed to `super_interfaces`; each step confirms that no field was renamed. |
| B4 | Making `native_interface` a three-way sum breaks the `.identity`-keyed merge and the separate Objective-C namespaces (`NSObject`). | `native_interface` stays single; `protocol_declarations` is added; `NativeJavaClass` is a declaration. The delta is purely additive. |
| B5 | Exact-key codecs make a new field a field error, not a version error. | Bump the schema per step (v2, v3, v4) with both codecs in the same commit. |
| B6 | btrc has no general IR verifier. | The twin is a new validator in `ir/optimization/Cleanup.btrc`, called from `Optimizer.btrc`. The Python projection citation is corrected to 1565-1686. |
| B7 | `owned-outputs` requires `result`; `com` is not in the ownership set; `type-check` was missing from the key list. | `ownership = "com"` joins the set; `result` is kept; there is a single `type-query` spelling; the §4 key table is complete. |
| B8 | Three-part names do not parse. | Accepted only for dispatch resources; btrc counts parts from the right. |
| B9 | JNIEnv is not a resource and has about 230 slots, including variadic ones. | Environment dispatch; unmapped slots are uncallable; only `...A` variants are mapped; `jni.h` comes through the `src/stdlib/Java/` binding. |
| B10 | Objective-C bindings are rejected off macOS targets, so step 3's Linux claim was too broad. | Linux evidence is reader goldens only; diagnostics run on the Mac. |
| B11 | Detach ordering. | Confirmed against `threads.c:43-57`; lazy attach during cleanup is documented. |
| B12 | Stdlib package obligations; `ComApartment` spelling. | Rows, README, symbols and lock are listed; the type is `COMApartment`. |
| B13 | No zlib, JDK or `android.jar` in the flake. | Toolchain table; skips are classified in Stage 2's ledger. |
| B14 | `win64` spelling; identity is unaffected. | Clarified as `CC_Win64`; `_type_identity` noted. |

### Parity (6 blocking, 9 non-blocking)

| # | Finding | Resolution |
|---|---|---|
| C1 | **Blocking.** The §4 key list omitted most new keys. | A complete table with step numbers; no other key is accepted. |
| C2 | **Blocking.** Executor was spelled four ways (`apartment` key, `release-executor = any`, missing `realtime`, COM dispatch with no executor). | One closed value set for `executor` and `release-executor` (rule 3); `dispatch` requires `executor` and `failure`. |
| C3 | **Blocking.** GObject signals introduced a second stored-registration syntax with no `activation-failure`. | Signals are `callbacks."g_signal_connect_data.c_handler"` with existing keys plus four GObject facts; the stored-C rule is lifted for that form only. |
| C4 | **Blocking.** COM sinks had no cancellation, but W1 requires asynchronous cancellation. | `CallbackScope`/`ICallbackRegistration`, `register`/`unregister`, `cancellation`, `activation-failure`; the factory key is `name`. |
| C5 | **Blocking.** HRESULT on ordinary methods was undefined; `error-out` was spelled inconsistently. | `status-results`; `error-outputs`; F1 lists the key family. |
| C6 | **Blocking.** JNI `main` meant the `JNI_OnLoad` thread. | `main` always means the platform UI thread (rule 3, §2.3). |
| C7 | Cast keys were inconsistent; the "recoverable cast" clause; unique-resource casts. | `type-query` plus `type-relation`; the clause is removed; separate owners. |
| C8 | `receiver-index` reinvented `context-index`. | `context` and `context-index` are reused. |
| C9 | ASDL naming (`readonly`, `is_varargs`, `is_*`); no identity on the Java class. | `read_only`, unprefixed booleans, `identity` and `complete` added. |
| C10 | Fields without consumers; access flags missing. | The consumer table; unused fields dropped; the reader omits non-public members. |
| C11 | `standard = "android-34"`. | No `standard`; the API level comes from the D21 target spec. |
| C12 | Device rows; D8 fallback; "blocked on push"; W1 open. | Physical-device rows, the D8 fallback, "after the D4 push", and the W1 note added. |
| C13 | GTK tier B was marked optional. | Required before the GTK spike. |
| C14 | No `sameObject` for JNI; `ComApartment`; `requires_super` wording. | `IsSameObject`; `COMApartment`; reworded. |
| C15 | Direct-cycle rejection covered only tables. | Applied to every R3 form (rule 1, §5). |

**Approval.** Under PLAN.md's standing approvals ("Design and interface
approvals ... Stage 27's ownership plan ... approved when its two adversarial
reviewers and the parity reviewer leave no unresolved blocking finding"), this
plan is approved as of the commit that records this section.
