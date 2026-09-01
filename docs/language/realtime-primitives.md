# Realtime primitive contracts

This document specifies the minimum BTRC value primitives used to build
bounded realtime code.  They are deliberately small: fixed arrays remain the
inline fixed-size primitive; `OwnedBuffer<T>` owns fallible fixed heap storage;
`Span<T>` is a lexical borrowed view; `Atomic<T>` exposes typed C11 atomics;
and `SpscQueue<T>` is the one canonical preallocated
single-producer/single-consumer queue composition.

## Fixed arrays

`T values[N]` owns exactly `N` inline elements.  Its extent is part of the
declaration and is preserved by fixed-array `for-in` lowering.  A fixed array
does not resize, allocate, or carry a hidden length field.  Parameters continue
to use C array/pointer semantics; use `Span<T>` when a callee needs an explicit
borrowed extent.

## Fixed owned buffers

`std.OwnedBuffer` provides fixed, zero-initialized heap storage whose capacity
never changes. `OwnedBuffer<T>` accepts realtime-POD values. It exposes
`status()`, `opened()`, `count()`, checked value-level `get`/`set`, a stable
`T* borrow()`, pointer-form `tryPointerAt`/`tryGet`/`trySet`, checked raw and
buffer-to-buffer copy, and idempotent `close()`. The raw borrow remains valid
only while the owner is open; destruction must run off native/realtime callback
paths after all borrowers stop.

The managed wrapper reports backing failures as `OWNED_BUFFER_OUT_OF_MEMORY`,
but allocation of the wrapper object itself follows BTRC's normal fail-fast
managed-allocation rule. Boundaries requiring completely fallible setup use
`OwnedBuffers.tryOpen(count, sizeof(T), &owner)`. It returns
`OWNED_BUFFER_OPENED`, `OWNED_BUFFER_INVALID_ARGUMENT`,
`OWNED_BUFFER_COUNT_OUT_OF_RANGE`, `OWNED_BUFFER_SIZE_OVERFLOW`, or
`OWNED_BUFFER_OUT_OF_MEMORY`, leaving the owner null on failure. The caller
borrows storage with `OwnedBuffers.borrow(owner, sizeof(T))` and consumes the
owner with `OwnedBuffers.close(&owner)` after borrowers stop. The byte-erased
raw boundary exists for stored native callback contexts; product code must use
one concrete type and matching `sizeof(T)` for the owner's whole lifetime.

`AtomicBuffer<T>` is the distinct fixed owner for atomic payloads. It exposes
only `status()`, `opened()`, `count()`, stable `Atomic<T>* borrow()`, and
`close()`: get, set, and copy operations are deliberately unrepresentable.
Initialize each borrowed element once off-callback and use only atomic
operations afterward. `OwnedBuffer<Atomic<T>>`, `Array<Atomic<T>>`, aggregate
atomic fields, managed buffer payloads, and unsupported atomic payloads remain
rejected.

## Borrowed spans

`Span<T>` has the value representation `{ T* data; size_t length; }`.  It does
not allocate, retain, release, or own its backing storage.  Construction is
contextual:

```btrc
int samples[64];
Span<int> whole = Span(samples);       // extent derived before array decay
Span<int> part = Span(samples, 32);    // explicit pointer and extent
```

A span may be a lexical local or a function parameter.  It may not be stored in
global/static storage, fields, heap aggregates, closure captures, thread
captures, generic managed storage, or return values.  Aggregate and generic
containment is checked transitively, so wrapping a span does not make it
escapable.  These restrictions make the borrow nonescaping; the caller remains
responsible for keeping the backing storage alive for the whole call.

The intrinsic surface is bounded and checked:

- `length() -> size_t`
- `isEmpty() -> bool`
- `isValid() -> bool` (`null, 0` is valid; `null, nonzero` is invalid)
- `tryGet(size_t index, remove_cv(T)* output) -> bool`
- `trySet(size_t index, T value) -> bool`

Failed `tryGet`/`trySet` calls do not touch the output or backing storage.
Span construction and these operations introduce no allocation, lock, logging,
retry loop, or hidden ownership work.

## Typed atomics

`Atomic<T>` is direct, stable `_Atomic(T)` storage.  Phase 1 accepts `bool`,
`int`, `uint`, and raw pointer payloads.  Managed references, aggregates,
arrays, nested atomics, and qualified atomic owners are rejected.  Atomic
owners may be lexical variables, globals, or class fields, but may not be
copied, returned by value, passed by value, or embedded in a shallow-copyable
aggregate.  This stable-storage rule is checked transitively through aggregate
and generic shapes.  Pass `Atomic<T>*` when a helper needs access to an existing
owner.

Every operation requires a literal member of `MemoryOrder`; BTRC does not add a
hidden default order:

```btrc
Atomic<uint> cursor = Atomic(0u);
cursor.store(1u, MemoryOrder.RELEASE);
uint observed = cursor.load(MemoryOrder.ACQUIRE);
```

`MemoryOrder` contains `RELAXED`, `ACQUIRE`, `RELEASE`, `ACQ_REL`, and
`SEQ_CST`.  The legal C11 order domains are enforced exactly:

| operation | accepted orders |
| --- | --- |
| `load` | relaxed, acquire, seq_cst |
| `store` | relaxed, release, seq_cst |
| `exchange`, `fetchAdd`, `fetchSub`, `fetchAnd`, `fetchOr`, `fetchXor` | all five |
| compare-exchange success | all five |
| compare-exchange failure | relaxed, acquire, seq_cst, and not stronger than success |

`init`, `load`, `store`, `exchange`, the integral fetch operations, and
`compareExchangeStrong` lower directly to their C11 counterparts.  Each
translation unit also emits a compile-time proof that every instantiated atomic
payload is always lock-free (`ATOMIC_*_LOCK_FREE == 2`); a target that cannot
prove this fails to compile rather than silently introducing a lock.

## Canonical SPSC queue

`std.spsc` owns the sole fixed-capacity SPSC queue/ring implementation. Ordinary
managed code uses `SpscQueue<T>`; `T` must be realtime POD. A stored raw callback
instead opens the same implementation explicitly and stores only its borrowed
storage pointer in the callback context:

```btrc
struct Command { int kind; unsigned long long token; };
struct AudioContext { struct SpscQueueStorage* commands; };

struct SpscQueueStorage* commands = null;
SpscQueueOpenKind opened = SpscQueues.tryOpen(
    64u, sizeof(struct Command), &commands);

@realtime bool nextCommand(
    struct AudioContext* context,
    struct Command* output
) {
    return SpscQueues.tryPopBorrowed(context->commands, output);
}
```

`tryOpen` returns `SPSC_QUEUE_OPENED`, `SPSC_QUEUE_INVALID_ARGUMENT`,
`SPSC_QUEUE_CAPACITY_OUT_OF_RANGE`, `SPSC_QUEUE_SIZE_OVERFLOW`, or
`SPSC_QUEUE_OUT_OF_MEMORY`. On every failure it leaves the output null. On
success the caller owns the returned pointer and must call `SpscQueues.close`
off the realtime path after both participating threads stop. A callback only
borrows the pointer; it may call `tryPushBorrowed` or `tryPopBorrowed` but may
not close it.

The raw boundary copies exactly the `valueSize` fixed at open. Callers must use
one concrete realtime-POD type and pass `sizeof(T)` plus `T*` values throughout
that storage's lifetime. The byte-erased representation is intentional at the
stored-C-callback boundary; the managed `SpscQueue<T>` wrapper enforces the same
payload rule statically for ordinary code.

Construction allocates the payload buffer and cursors off the realtime path.
Borrowed push and pop are bounded operations with no allocation, destruction,
locks, logging, retry loops, or blocking. The implementation reserves one
sentinel slot and advances each cursor with a single branch at the end of the
buffer, so neither operation uses division or modulo. Copy cost is bounded by
the fixed element size supplied at open.

Exactly one producer may call `tryPush`, and exactly one consumer may call
`tryPop`.  The queue is FIFO.  A full push returns `false` without overwriting
unread data.  An empty pop returns `false` without changing its output.  Payload
publication is release/acquire ordered; producer- and consumer-owned cursors use
relaxed accesses.  Destruction is only valid after both participating threads
have stopped.

The queue intentionally composes `Atomic<uint>` and raw preallocated storage in
BTRC source. It is not a second compiler primitive, and product repositories
must not carry private substitutes for it.
