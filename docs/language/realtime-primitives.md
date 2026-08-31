# Realtime primitive contracts

This document specifies the minimum BTRC value primitives used to build
bounded realtime code.  They are deliberately small: fixed arrays remain the
owning, fixed-size storage primitive; `Span<T>` is a borrowed view;
`Atomic<T>` exposes typed C11 atomics; and `SpscQueue<T>` is the one canonical
preallocated single-producer/single-consumer queue composition.

## Fixed arrays

`T values[N]` owns exactly `N` inline elements.  Its extent is part of the
declaration and is preserved by fixed-array `for-in` lowering.  A fixed array
does not resize, allocate, or carry a hidden length field.  Parameters continue
to use C array/pointer semantics; use `Span<T>` when a callee needs an explicit
borrowed extent.

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

`std.spsc` defines `SpscQueue<T>`, the sole fixed-capacity SPSC queue/ring
implementation.  `T` must be realtime POD.  Construction allocates the payload
buffer off the realtime path; `tryPush` and `tryPop` are bounded O(1) operations
with no allocation, destruction, locks, logging, retry loops, or blocking.
The implementation reserves one sentinel slot and advances each cursor with a
single branch at the end of the buffer, so neither operation uses division or
modulo.

Exactly one producer may call `tryPush`, and exactly one consumer may call
`tryPop`.  The queue is FIFO.  A full push returns `false` without overwriting
unread data.  An empty pop returns `false` without changing its output.  Payload
publication is release/acquire ordered; producer- and consumer-owned cursors use
relaxed accesses.  Destruction is only valid after both participating threads
have stopped.

The queue intentionally composes `Atomic<uint>` and raw preallocated storage in
BTRC source.  It is not a second compiler primitive, and product repositories
must not carry private substitutes for it.
