# Keyed collection data-model feasibility

CX-UIB-06, 2026-10-04, based on main
`f4317455de1e567d4d6290139e5ba28fbada7d0c`.

The tested pure-btrc model supports a 100,000-record keyed source, validated
revisioned delete/reorder/filter batches, anchor/active selection, and bounded
cell reuse with generation checks. Both compilers produced identical counters
under ASan/UBSan, with zero live rows/cells after teardown and no sanitizer
report. This is evidence for the **model shapes**, not native UI performance or
qualification of a collection widget.

## Source and reproduction

Prototype branch `codex/cx-uib-06-spike`, immutable commit
[`156353a5`](https://github.com/schiffy91/btrc/tree/156353a5/spikes/collections-data-model),
is pushed with no PR and must never merge. This findings PR contains only this
note. The prototype includes source, runner, raw counters and source hashes.

From the prototype checkout root:

```bash
nix develop --command bash spikes/collections-data-model/run.sh reference
nix develop --command bash spikes/collections-data-model/run.sh selfhost PATH_TO_CURRENT_BTRCC
```

Use a self-host compiler built from that main base in the pinned shell. Both
commands were executed on Linux x86_64 cloud with GCC 15.2.0. The runner compiles
strict C11 at `-O1 -g`, with `-fsanitize=address,undefined`,
`-fno-sanitize-recover=all`, `-fno-omit-frame-pointer` and
`ASAN_OPTIONS=detect_leaks=1`. No sanitizer suppressions or disabled assertions
are used. Both executions returned **0**; **2 passed, 0 skipped, 0 failed**.

## Observed counts

The viewport's maximum visible capacity is fixed at 20. Sixty model cell owners
are allocated, including all unbound/retained objects, compared with the
`3 × Vmax + 2 = 62` limit. The two extra pinned editor/focus owners are unused.

| Counter | Reference | Self-host |
|---|---:|---:|
| Primary source records | 100,000 | 100,000 |
| Maximum visible capacity | 20 | 20 |
| Peak model cell owners | 60 | 60 |
| Total binds over the complete scenario | 3,293 | 3,293 |
| Unchanged presentation rebinds | 0 | 0 |
| Offscreen content update rebinds | 0 | 0 |
| One retained item's content update rebinds | 1 | 1 |
| Reverse sort, same 60 retained keys | 0 | 0 |
| Filter at the tested viewport | 27 | 27 |
| Delete batch at the tested viewport | 1 | 1 |
| Stale callback tokens rejected | 2 | 2 |
| Live rows after scope teardown | 0 | 0 |
| Live cells after scope teardown | 0 | 0 |

Raw output: [reference](https://github.com/schiffy91/btrc/blob/156353a5/spikes/collections-data-model/evidence/reference.log)
and [self-host](https://github.com/schiffy91/btrc/blob/156353a5/spikes/collections-data-model/evidence/selfhost.log).
The total includes 100 scrolling positions, a jump after the retained-window
sort check, and repopulation of the smaller viewport. Individual operation
counts above are measured deltas, not a partition of the total.

After shrinking the viewport to zero and then five, all 60 high-water cell
owners remain allocated and counted. The model does not silently redefine
Vmax or hide unused cells. It does not test increasing viewport capacity beyond
20, adaptive allocation, native handles, native-setter suppression, or the two
pinned-owner exception. Zero model binds must not be called zero native work.

## Executed behavior

The source stores generic `Row<int>` objects in `Map<int, Row<int>>` and an ordered
`Vector<int>` of keys. A non-generic `KeyedSource` interface exposes count, key
and content-revision lookup. The pool calls through that interface.

Each batch validates base/next revision and rejects duplicate, unknown or
already-deleted keys before mutating the source. The executable asserts that a
duplicate-key batch and a stale-base batch leave committed revision/count and
row state unchanged. Sorting uses the existing comparator-driven stable sort,
and every one of the 100,000 positions is checked against the reversed order.
Filtering removes multiples of three from the view (66,666 remain); deleting
two eligible keys leaves 66,664 visible records.

Cell reconciliation first marks every key retained by the desired window,
then invalidates inactive bindings, then recycles available cells. This prevents
an early new key from evicting an unchanged retained key that occurs later in
the new order. A reverse sort uses a mirrored viewport containing exactly the
same 60 keys, which directly proves zero rebinds for that reorder. A content
revision change of one retained key binds once; an offscreen revision change
binds none. Each desired key must appear in exactly one active cell.

Binding generations invalidate asynchronous tokens on both reuse and unbind.
The executable accepts a current token, rejects it after reuse, and rejects a
second token after the viewport becomes empty. Merely setting a visibility flag
without invalidating the binding would have left the latter callback valid;
that review finding is covered by the final assertion.

Selection stores anchor and active keys outside cells. Sort preserves those
identities. Filtering a selected key moves active focus to the next eligible
key in prior order while preserving the hidden anchor. Deleting key 43 in the
descending filtered order chooses successor 41 (42 is filtered), and the deleted
anchor follows it. Deleting all remaining records yields `-1` for both keys;
repeated empty reconciliation remains valid. Replacing the source with a populated
source selects key 0. The prototype does not implement multi-selection ranges,
tree selection, accessibility commands or production user-event semantics.

## Ownership and costs

Both compilers handle the generic row nested in a map, vectors of managed cell
objects, interface dispatch and the exercised nullable cell references. Two
cells deliberately form a reference cycle before scope exit. Their destructors
run, counters reach zero, and unsuppressed LeakSanitizer reports no leak in either
execution. This proves that specific owned graph, not arbitrary callback cycles,
foreign-object cycles or executor cancellation.

The snapshot implementation has deliberately visible costs:

- Every batch scans all 100,000 keys and rebuilds the ordered vector; descending
  batches sort it. This is whole-source batch work, not an incremental index.
- Deleted row objects remain tombstoned in the map until source teardown.
- Per-presentation reconciliation scans only the bounded pool and desired
  window, with quadratic work in their bounded capacities. It does not scan
  100,000 records per scroll frame; zero rebinds still involves model work.
- The empty/repopulation assertion temporarily creates a second 100,000-row
  source. Peak row ownership therefore exceeds 100,000 in that subtest; no
  100,000-object memory-budget claim is made.

No frame-time, memory-footprint or hardware performance target is qualified by
these counters. Native widget allocation, layout, image caches and assistive
proxies still need their own measurements and lifetime accounting.

## Recommendations for CX-UIB-14

Keep stable keys, committed source revision and per-item content revision as
separate inputs. Validate a complete diff before publishing it. Preserve cells
by key across reordering, and invalidate their generation on unbind as well as
reuse. Keep anchor/active selection independent from cell lifetime, including
explicit hidden, deleted, empty and repopulated states.

Replace this full snapshot rebuild with a measured index/update strategy before
claiming incremental production behavior. Count every retained native owner,
exercise pinned editor/focus exceptions and viewport growth, and add realistic
native callbacks/cancellation. Keep the same retained-window metamorphic sort
check and no-op/offscreen update checks when moving to real providers.

An independent review found and resolved the successor-assignment error,
inactive-token acceptance, empty-selection lookup and missing retained-sort
proof before the recorded runs. No compiler/parity defect was observed in the
final prototype, so no speculative CL-UIB-13 repair is requested.
