# Callback representations

BTRC distinguishes a raw callable ABI from managed receivers and contexts.

`RealtimeFunction<Result, Parameters...>` is the proof-carrying form of the
same one-word C function pointer. Only a direct named `@realtime` function or
an exact `RealtimeFunction` copy can initialize it. Its signature and proof are
preserved through typed locals, returns, fields, parameters, and generic
storage such as `Vector<RealtimeFunction<...>>`; casts, lambdas, ordinary
`CFunction` values, and native declarations cannot create or expose one.
Calling it from `@realtime` code is therefore a statically admitted indirect
edge. Assignment to the corresponding `CFunction` is an intentional one-way
downgrade and cannot be reversed.

The proof type is direct, nonnullable, unqualified, and not an array. A
zero-initialized aggregate may use a null proof slot only as inert unpublished
storage paired with separate occupancy state; it must never invoke that slot.
This is the representation used while fixed-capacity realtime tables are
prepared off-thread. Native APIs receive only the downgraded `CFunction`; an
FFI declaration cannot mint or return compiler proof.

`CFunction<Result, Parameters...>` is one exact C function-pointer word.  Its
result, parameter count, pointer depth, and `const` qualifiers are part of the
type.  It carries no context and therefore accepts only named functions and
noncapturing lambdas.  The hosted-ABI manifest records whether each C callback
parameter is borrowed for the call or stored until unregister.

For non-realtime C APIs with call-scoped callbacks, use the package's
[checked callback mapping](../../src/language/package-manifest.md#call-scoped-native-callbacks).
It imports an ordinary interface with an `invoke` method, derives its signature
from the header, and generates the foreign context/trampoline. The receiver is
ARC-rooted until the native call finishes. Delivery must occur on the caller's
thread; an exception cannot unwind across the C frame. Returned resources and
callback leases remain in normal exception-cleanup slots during teardown.
Native call borrows must survive reentrancy too: generated C resource adapters
and Objective-C method wrappers lease their managed resource/object arguments
(including instance receivers) until the call finishes. Clearing an application
owner from a callback cannot invalidate the object still used by native code.
Objective-C exceptions return through the existing foreign boundary before
BTRC unwinds those leases. These are object-lifetime claims, not a guarantee
that interior pointers remain valid across mutation.
This is not a new closure ownership system. Stored and one-shot typed native
callbacks, UI-executor destruction and capturing-lambda conversion remain open.

`OwnedClosure<CFunction<...>>` is an ARC-managed owner for a callback that must
outlive one call. It contains an exact, nonnull invoke pointer, an opaque
context, and one context destroy callback. Aliases and fields retain the same
owner. Its standalone `invokePointer()` and `context()` accessors are only for
assembling a registration before concurrent use; they must not race `close()`.
The invoke signature remains exactly as written, so a caller passes the stored
context in the position required by the external C API.

`OwnedClosure.close()` is a completion barrier. One caller changes the closure
from open to closing and runs the destroy callback. Concurrent callers wait for
that operation to publish closed or destroy-failed; they never observe closed
before destruction returns. The winner and all waiters return `true` only for a
completed destruction. A thrown destroy operation publishes a terminal failure
before propagating, so later callers return `false` instead of waiting forever.
Final ARC destruction aborts on that failure rather than silently leaking the
context. Calling `close()` reentrantly from the destroy callback is rejected.

An external registration has a stricter lifetime boundary than an owned
closure alone. `CallbackRegistration<Invoke>` therefore owns activation as
well as shutdown. Its constructor is:

```btrc
CallbackRegistration(
    Invoke invoke,
    void* context,
    CFunction<void, void*> destroy,
    CFunction<bool, Invoke, void*, Atomic<uint>*, void*> activate,
    void* activationContext,
    CFunction<bool, void*> unregister,
    void* unregisterContext)
```

`invoke` must be a direct named `@realtime` function. Construction initializes
the closure and gate before calling `activate` exactly once. The activation
adapter stores the supplied gate in the raw POD context and publishes the exact
invoke/context pair to the external API. Returning `false` or throwing means
nothing was published. Either path closes the owned context, frees the gate
and destroys the native operation guard;
the throwing path then propagates, while `false` aborts instead of returning an
unregistered owner. An activation adapter must therefore publish only on its
successful `true` path. `CallbackRegistration` deliberately exposes neither the
invoke pointer, raw context, nor gate after activation, eliminating a second
publication path and racy context getters.

The realtime trampoline calls `callbackGateTryEnter` before touching callback
state and pairs every successful entry with `callbackGateLeave`. Gate entry uses
a bounded lock-free compare/exchange loop: a saturated counter or exhausted
contention budget rejects that invocation, and integer wrap can never reopen a
closed gate. Because `Span<T>` is deliberately nonescaping, the stored raw
context keeps only backing pointer and extent POD; after admission, the
trampoline constructs its lexical `Span` from those fields. The constructor,
bounded `Span` methods, and lock-free `Atomic` operations are certified by the
compiler-owned intrinsic-effect specification. The ordinary constructor type
checks still reject a non-pointer backing value or non-integral extent, and the
certificate is attached only by typed lowering rather than by globally trusting
a raw C callee name. Because the trampoline is `@realtime`, a direct or
transitive call to `close()` is rejected during analysis.

`unregister` has an entry-barrier contract: a `true` result guarantees that no
callback can later execute its first gate atomic unless it already published an
in-flight gate count. This includes a callback that snapshotted the invoke and
context before unregistration began. Cancellation performs, in order:

1. close gate admission;
2. obtain the external unregister entry barrier;
3. observe every admitted callback leaving the gate;
4. destroy the owned context;
5. publish terminal completion.

`cancel()` closes admission and attempts unregister. `pollCompletion()` observes
progress and, once the entry barrier and callback drain are complete, claims
exactly-once destruction. Neither waits for admitted callbacks or another
caller's unregister/destruction. They return `CallbackCancellation`:

| Result | Meaning |
|---|---|
| `NotRequested` | Registration is open; polling does not initiate cancellation. |
| `Pending` | Unregister, callback drain or destruction is still outstanding. |
| `Complete` | Destruction has finished successfully. |
| `RetryableFailure` | Unregister failed; context remains alive and admission closed. |
| `Failed` | Destruction failed; no automatic retry is safe. |

Repeated cancellation/polling joins the same operation. Cancellation reentered
from unregister or destruction returns `Pending`, without invoking either
adapter again. A false or throwing unregister must guarantee that its context
remains valid for retry; it publishes `RetryableFailure` without destroying
anything. Only an explicit subsequent `cancel()` or `close()` retries it, never
an observational poll. Exceptions propagate after publishing the failure state.
Mappings with indeterminate failures are not supported by this primitive.

For UI/executor use, **the supplied unregister must itself be a nonblocking
entry barrier and destroy must be bounded**. These methods do not make a
blocking native operation asynchronous. They use a short lifecycle-only mutex
to protect reentrancy bookkeeping, never held across adapters or callback drain;
this is not a lock-free or realtime cancellation API. Keep the registration in
its component scope until completion, and call completion polling on the
required destruction executor. Polling must be scheduled, not a UI busy loop.
Thread-affinity enforcement, asynchronous unregister completion and typed
non-realtime native callbacks are not provided by this primitive yet.

`close()` is the blocking completion barrier for independent workers. It uses
the same cancellation path and waits for `Pending` to become a terminal result;
it returns true only for `Complete`. Reentrant close from unregister or destroy
is rejected. Final ARC destruction still calls `close()` and aborts if cleanup
fails. Do not drop the final registration reference on an executor whose
callbacks still need to drain: finish the scoped cancellation first. Existing
`@realtime` callbacks cannot call lifecycle methods, including the new methods.

The shared implementation now separates `CallbackState` from its raw ABI
constructor. `ICallbackContext` holds typed unregister/close operations and
ordinary managed receiver fields; `ICallbackRegistration` exposes cancellation
and completion. These are low-level building blocks, not yet compiler-checked
stored native bindings. The activation gate uses existing stable atomic-buffer
storage; cancellation during inline activation closes admission immediately and
defers unregister until activation returns.

A separate component scope must cancel before abandoning a cyclic receiver.
ARC cycle collection detaches managed fields before destructor hooks. An active
state discovered after detachment now diagnoses missing scope cancellation
instead of dereferencing a cleared gate. The unscoped abandoned-cycle regression
remains failing; that diagnostic does not implement automatic cycle cleanup or
prove that a native context has stopped being used. Generated scope ownership,
foreign context roots and executor-aware teardown remain required.
