# ARC Runtime Invariants

This document defines the ownership counters and the concurrency seam used by
the cycle collector. The Python and self-hosted compilers must emit the same
ABI and the same ownership atoms.

## Object header

Every managed object starts with one real header member:

```c
typedef int __btrc_arc_count;

typedef struct {
    __btrc_arc_count rc;
    __btrc_arc_count edge_rc;
    const __btrc_arc_type* type;
} __btrc_arc_header;
```

`type` points to one immutable, process-lifetime descriptor for the object's
concrete type. It is never inferred from a base-typed release site. This keeps
terminal destruction and cycle visitation polymorphically correct without
changing source-language method dispatch.

`__btrc_arc_count` is the single substitution point for the future C11 atomic
implementation. Generated code must access counters by header member, not by
casting an object to `int*` or assuming byte offsets.

## Exact-counter invariant

For every live managed object `o`:

- `R(o) = o->__arc.rc` is the total number of owned references.
- `E(o) = o->__arc.edge_rc` is the number of persistent, collector-visible
  managed slots whose current value is `o`.
- `X(o) = R(o) - E(o)` is the number of roots outside the managed object graph.
- `0 <= E(o) <= R(o)` always holds.

The only legal counter transitions are:

| Ownership operation | `rc` | `edge_rc` |
|---|---:|---:|
| Construct object | `1` | `0` |
| Retain local/argument/thread root | `+1` | unchanged |
| Release local/argument/thread root | `-1` | unchanged |
| Store into a managed field/collection slot | `+1` | `+1` |
| Erase from a managed field/collection slot | `-1` | `-1` |
| Move one persistent slot to another | unchanged | unchanged |
| Transfer an owned return value | unchanged | unchanged |

Persistent slots include class fields, property backing fields, generic class
fields, and managed elements/keys/values in `Array`, `List`, `Map`, `Set`, and
`Vector`. A lambda or thread capture held by a raw, non-visited C environment
is an external root and changes only `rc`.

Replacement evaluates and retains the new edge before publishing it, saves the
old value, removes the old slot from the visible graph, and then releases the
old edge. Erase saves the old value, clears the slot, then releases the edge.
Collection resize and compaction may move pointer bits without counter changes,
but no duplicate source slot may remain visible at a collector boundary.
Exception cleanup releases registered locals as external roots. Destructors
release managed fields as edges. A direct manual destroy is a separate terminal
operation, not a disguised reference decrement.

Tests may enable runtime assertions that reject negative counters or
`edge_rc > rc` after every atom and before/after every collection.

## Why the fast path is sound

If `rc > edge_rc`, at least one owned reference comes from outside the managed
slot graph. The object cannot be reclaimed as cycle garbage, so a queued
candidate is discarded without a graph snapshot.

`rc == edge_rc` is necessary but not sufficient for reclamation: an incoming
edge may originate in a live object outside the candidate's reachable
subgraph. The collector therefore still snapshots every zero-external
candidate. For snapshot vertex set `S`, it computes `I_S(o)`, the number of
incoming edges from `S`. A vertex is initially live when `R(o) > I_S(o)`, and
liveness propagates along outgoing edges. Only the remaining vertices are
detached and destroyed. Exact global edge counts accelerate candidate
selection; they do not replace trial-deletion verification.

## Cross-thread design

Plain integer counters and thread-local candidate queues are not the final
thread-safe contract. Atomic counts alone are also insufficient: a collector
must not race a slot rewrite, and two thread-local queues can retain duplicate
pointers after one thread frees an object.

The thread-safe runtime will use these rules:

1. `__btrc_arc_count` becomes `_Atomic int`. Retains use checked atomic
   increments. Releases use release decrements and an acquire fence before
   terminal destruction. Owned-reference publication still follows normal C11
   happens-before rules; retaining an unowned borrowed pointer is invalid.
2. Candidates live in one process-wide collector domain, deduplicated under
   that domain's lock. No TLS queue may hold a stale independently reclaimable
   pointer.
3. Every managed topology mutation is enclosed by a reentrant per-thread entry
   into the domain lock. The lock covers retaining the new edge, publishing or
   clearing the slot, releasing the old edge, and candidate insertion. Nested
   collection methods and destructor cleanup reuse the same entry depth.
4. Cycle snapshot, liveness marking, and dead-edge detachment hold the same
   domain lock, so visitors observe one stable graph and a mutually consistent
   pair of counters. External-root atomics may change concurrently, but legal
   retain-before-release transfer never transiently removes the last external
   owner.
5. User destructors do not run while the domain lock is exclusively held. The
   collector first detaches proven-dead edges, marks objects terminal, removes
   their candidate entries, then releases the lock and invokes destructors.
   This prevents user callbacks, joins, or nested runtime operations from
   deadlocking the collector.
6. A thread-exit cleanup drains the shared domain; it does not free process-wide
   collector storage still usable by another thread. Process-exit cleanup owns
   final domain storage teardown.

The lock may be implemented with C11 atomics so non-threaded programs do not
gain a mandatory pthread dependency. Before enabling cross-thread collection,
tests must include high-iteration shared-reference transfer, concurrent edge
replacement, a cycle spanning two worker threads, and a ThreadSanitizer-capable
build contract. Until that implementation lands, the header layout and helper
APIs must remain atomic-ready and must not imply that TLS collection is safe.
