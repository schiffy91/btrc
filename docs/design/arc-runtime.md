# ARC Runtime Invariants

This document defines the ownership counters and the concurrency seam used by
the cycle collector. The Python and self-hosted compilers must emit the same
ABI and the same ownership atoms.

## Object header

Every managed object starts with one real header member:

```c
/* src/runtime/c/cycles.c, helper __btrc_arc_callback_types */
typedef _Atomic int __btrc_arc_count;
typedef struct __btrc_arc_type __btrc_arc_type;
typedef struct __btrc_arc_incoming __btrc_arc_incoming;
typedef enum {
    __BTRC_ARC_LIVE = 1,
    __BTRC_ARC_QUEUED = 2,
    __BTRC_ARC_DESTROYING = 3
} __btrc_arc_state;
typedef struct __btrc_arc_header {
    __btrc_arc_count rc;
    __btrc_arc_count edge_rc;
    /* One current incoming-edge owner, or self as a full-snapshot sentinel. */
    _Atomic(void*) live_witness;
    const __btrc_arc_type* type;
    __btrc_arc_incoming* incoming;
    void* deferred_next;
    unsigned char suppress_hook;
    _Atomic unsigned char in_suspects;
    /* Bit 15: per-object edge spinlock; bits 0..14: active witness-walk pins. */
    _Atomic unsigned short pin_lock;
    _Atomic int state;
} __btrc_arc_header;
struct __btrc_arc_incoming {
    void* owner;
    __btrc_arc_incoming* next;
};
```

`incoming` is the singly linked list of managed owners currently holding an
edge to a visitable object (acyclic leaf objects with `type->visit == NULL`
skip `incoming` allocation), with `live_witness` caching one of them (or the
object itself as a full-snapshot sentinel); `deferred_next` links the object
into the thread's deferred-destruction queue, `state` records whether it is
live, queued or being destroyed, `in_suspects` tracks suspect-table membership
for fast lock-free terminal release, `pin_lock` packs a per-object edge lock in
bit 15 and a witness-walk pin count in bits 0..14 while keeping the header at
48 bytes, and `suppress_hook` makes that queue skip the type's destruction
hook, which the collector sets on unreachable roots of a partial construction.

`type` points to one immutable, process-lifetime descriptor for the object's
concrete type. It is never inferred from a base-typed release site. This keeps
terminal destruction and cycle visitation polymorphically correct without
changing source-language method dispatch.

`__btrc_arc_count` is `_Atomic int`. Generated code must access counters by
header member, not by casting an object to `int*` or assuming byte offsets.

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

The runtime uses C11 `stdatomic.h` directly so `--freestanding` builds require
no platform lock headers. The concurrency model separates fast mutator paths
from exclusive cycle snapshots with a strict lock hierarchy:

1. **Level 0 (Striped snapshot gate):** Each thread claims a 128-byte-aligned
   stripe in `__btrc_arc_shared.stripes[64]` (`active`, `topology`, `drains`,
   `unwinds`). Normal retains, acyclic releases, and edge updates increment
   their own stripe with `seq_cst` and read `__btrc_arc_snapshotting` (skipping
   `active` updates when already inside a thread-local topology scope). An
   exclusive cycle snapshot publishes `__btrc_arc_snapshotting = 1` with
   `seq_cst` first, then checks every `topology` stripe and drains every
   `active` stripe with `seq_cst` (Dekker ordering), guaranteeing that visitors
   observe a stable object graph without serializing mutators against one
   global lock.
2. **Level 1 (Striped slot locks):** Slot transactions (`__btrc_arc_replace_edge`,
   `__btrc_arc_destroy_slot`, `__btrc_arc_destroy_edge`) lock at most one
   128-byte-aligned stripe in `__btrc_arc_shared.slot_locks[512]` hashed by the
   slot address.
3. **Level 2 (Inline per-object header locks):** Cyclic edge mutations acquire
   bit 15 of `header->pin_lock` in strictly ascending pointer-address order,
   eliminating cross-object lock collisions. Acyclic leaf objects
   (`type->visit == NULL`) take lock-free atomic `rc`/`edge_rc` paths and skip
   `incoming` node allocation.
4. **Level 3 (Suspect table lock):** Candidates live in one process-wide
   suspect table guarded by `__btrc_arc_shared.suspect_lock`, deduplicated with
   `header->in_suspects`. Witness walks pin the candidate in bits 0..14 of
   `header->pin_lock` and traverse `live_witness` hand-over-hand with Brent's
   cycle check before falling back to suspect insertion.
5. **Lock-free terminal drains:** User destructors and hooks never run while
   any lock or snapshot gate is held. Objects reaching `rc == 0` enqueue onto
   the releasing thread's intrusive deferred FIFO, wait for any active witness
   pins to drop to zero, then run hooks and `destroy` unlocked.
6. **Thread and process cleanup:** Worker exit drains its thread-local deferred
   FIFO and abandon queue without tearing down shared process storage. Process
   exit sets `__btrc_arc_shutdown`, drains all mutator stripes, verifies zero
   active drains/unwinds/topology scopes, and frees process-wide collector
   tables.
7. **Sharded string registry:** Managed string ownership (`src/runtime/c/strings.c`)
   uses 256 128-byte-aligned shards with per-shard atomic live counts, letting
   string literals bypass locks completely and letting worker threads retain
   and release distinct strings in parallel.
