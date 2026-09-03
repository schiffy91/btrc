# Callback representations

BTRC has two deliberately different callback representations.

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
nothing was published. Either path closes the owned context and frees the gate;
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
context before unregistration began. `close()` then performs, in order:

1. close gate admission;
2. obtain the external unregister entry barrier;
3. drain every admitted callback;
4. destroy the owned context;
5. publish terminal completion.

A `false` or throwing unregister operation publishes a completed retry state,
keeps the context and gate alive, and never starts destruction. `close()`
returns `false` for the boolean case, and a later call retries unregister. A
destructor that still cannot obtain the barrier aborts rather than leaking
silently. Concurrent close callers never return while an attempt is in the
closing state. They wait for its publication; after a retryable unregister
failure, one waiting caller may atomically own the next retry, while closed and
destroy-failed results are terminal. Reentrant close from either unregister or
destroy is rejected before it can self-deadlock.
