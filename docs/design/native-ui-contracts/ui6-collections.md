# UI6 keyed collections, recycling and scrolling

**Pre-draft — CX-UIB-03, `ui-6-contract-collections`.** This is input to the
Stage 34 collection contract and CL-UIB-02 approval, not an API or provider
implementation. UI2/UI3, the five shells and CL-UIA-22 review precede landing.
It changes no source interfaces, catalog records or frozen denominator. All
budgets below are acceptance targets; no native run or measurement is claimed.

## Source audit: preserve existing gains

btrc baseline: `f4317455de1e567d4d6290139e5ba28fbada7d0c`.

- [UIVirtualGrid and UIVirtualGridViewport](../../../src/stdlib/UI/Element.btrc)
  are descriptor values, not a native reusable-cell implementation.
  UIVirtualGrid validates nonnegative count, positive columns/row height and a
  first index within the count. UIVirtualGridViewport separates grid id, total,
  column count, row height/pitch, content origin, local scroll and visible index/
  count. Preserve that distinction; data index, content coordinate and pool slot
  are not interchangeable identities.
- [IScrollView](../../../src/stdlib/GUI/IScrollView.btrc) owns a clipped document,
  content size, a vertical-only scrollOffset and scrollTo. Its resize clamps the
  existing offset. Two-axis geometry and observation must reuse the approved
  UI2 scroll shape rather than introducing a competing event API.
- BTRSmith access was available for a **read-only source audit**.
  [AlbumGrid at adb3276f](https://github.com/schiffy91/btrsmith/blob/adb3276f93cbeb7b0c2ab79ab34e366c9eef5f5c/src/frontend/library/AlbumGrid.btrc)
  owns a reusable AlbumCell pool and native IScrollView, while catalog, artwork
  jobs, playback and search stay outside it. AlbumCell separates album id,
  artwork revision, dataIndex and stable poolSlot. Its bind suppresses unchanged
  text/frame/image setters; a move changes the root frame without rearranging
  unchanged children. AlbumGrid.present tracks lastBinds, reuses projected cells
  and avoids reapplying unchanged content size/offset because that interrupts
  native momentum. viewportChange returns no message when its descriptor is
  unchanged. Preserve those properties through extraction.
- That caller uses data-index lookup/reservation and derives resize anchors from
  prior row/index geometry; it is not evidence of a general key-preserving diff
  contract. Its width bound of 320–4096, projection/pool capacity checks and
  product-specific section layout are current caller constraints, not universal
  limits for all collections. This packet neither changes them nor claims their
  runtime behavior passed. Broader caller mapping remains `btrsmith-ui0-callers`.

[native-ui-parity](../native-ui-parity.md) defines N26–N30 and E09/E21/E24/E29/
E36/E41. The proposed [layout](ui5-layout.md) and
[accessibility](ui8-accessibility.md) documents share geometry/realization
semantics with this pre-draft; their independent review is still pending.

## Family coverage and candidate operations

| Family | Owner and required behavior | Acceptance |
|---|---|---|
| N26 | Two-axis scrolling/visible rect, scroll-to-item and stable anchors; native momentum and nested handoff. | E09/E41 |
| N27 | Keyed list/grid source, reusable cell pool, loading/empty/error states, cancellation and bounded owners. | E21/E24/E36 |
| N28 | Virtual table rows and typed keyed columns, headers, sort/filter, sizing, row actions and editing; mobile detail adaptation. | E09/E21/E29 |
| N29 | Lazy tree/outline expansion, hierarchy, loading/error/retry, keyboard movement and stable selection. | E21/E24/E29 |
| N30 | Single/multi/range selection, anchor and active item in the model rather than recycled cells. | E09/E21/E29 |

These are candidate operation ids for the later amendment, not signatures:

| Candidate operation ids | Proposed input/result |
|---|---|
| ICollectionSource.snapshot, ICollectionSource.keyAt, ICollectionSource.indexOf | Revisioned count/key lookup and explicit loading/missing outcomes; no implicit materialization of every record. |
| ICollectionSource.applyBatch | Base revision plus keyed insert/remove/move/update and next revision → applied/stale/invalid/resource-failed. |
| ICollectionView.setSource, ICollectionView.setCellFactory | Scoped source and typed cell-kind factory registration; atomic failure before publishing ownership. |
| ICollectionCell.bind, ICollectionCell.unbind | Key, source/content revision and binding generation; no model side effects; unbind cancels the previous cell scope. |
| ICollectionSelection.setKeys, ICollectionSelection.extendTo, ICollectionSelection.activate | Stable selected keys plus anchor/active key, independent of cell existence; user action distinguished from model refresh. |
| ICollectionView.scrollToItem, ICollectionView.anchor | Stable key, alignment and optional intra-item offset → positioned/pending/missing/stale; return a stable anchor snapshot. |
| ITableView.setColumns, ITableView.requestSort | Stable typed column keys and a sort request routed to the data owner; provider does not mutate product records. |
| ITreeSource.children, ITreeSource.requestExpansion | Parent key/revision with lazy state and cancellable request; loading and empty are distinct. |
| ICollectionView.requestRealization | Stable key/source revision → realized/pending/stale/missing; shared UI8 realization path. |

Use the approved UI2 two-axis IScrollView operations and scoped subscriptions.
The existing vertical scrollOffset/scrollTo caller can be adapted with x=0 until
the reviewed compatibility policy and BTRSmith pin bump. New collection APIs
must not silently reinterpret a legacy vertical offset as a vector.

## Keyed data, diffs and failure

A key is immutable within its logical item lifetime, nonempty and unique in its
source scope. A revision identifies a complete ordered snapshot. Indices are
positions only; keys survive sort/filter/reparent. Reusing a deleted key for a
new logical item requires a new generation so stale jobs or native proxies cannot
address it. Selection, editing and commands refer to keys, never pool slots.

A diff batch declares base and next revisions and references keys/anchors rather
than shifting integer positions. Define its order explicitly: operations apply
sequentially to a private candidate snapshot; every referenced key/parent exists
at that operation or the batch rejects. Validate duplicate keys, missing anchors,
cycle-producing tree moves, incompatible cell kinds and bounds before publishing.
A stale base returns stale and requests a new snapshot; never guess at rebasing.
An identical snapshot/revision produces no bind or native-layout churn.

The provider stages bindings and native mutations against that candidate. Commit
publishes one source/tree/selection revision; if a native step fails, rollback to
the prior valid snapshot before notifying observers. If rollback itself fails,
report failed/pending cleanup, retain affected owners and disable only the broken
view until a deliberate rebuild; never report success with a half-applied tree.
A retry has a fresh transaction identity and cannot attach one cell twice or
repeat a product mutation. User callbacks see only committed snapshots.

Loading, empty, partial and failed data have distinct states and stable retry
commands. Async results carry source revision, item key, content revision and
request generation. Validate these on the UI executor at delivery. An old image
or children response may finish and be reclaimed without changing the current
cell. Cancellation suppresses stale presentation while its job owner still
records terminal completion and frees all retained payloads.

Table columns have stable keys, value types and presentation/editing policies.
Sort/filter requests go to the source owner; an arrow/header state is not an
independent sorting implementation. Multi-column sorting, null values and stable
tie-breaking use the declared source policy. Edited drafts live with the model
and survive recycling; departure uses E46 rather than an implicit save in unbind.
A compact mobile row can expose details instead of squeezing every desktop
column into an unreadable native grid, with that adaptation recorded.

Tree children are lazy revisioned snapshots. Expand/collapse preserves keys;
failed loads expose retry, not an empty success. Reject ancestor cycles and
bounded-depth overflow before creating native nodes. Collapsing cancels obsolete
child requests; a subsequent expansion has a fresh request generation. Depth,
position-in-set and expansion remain available to assistive clients even when
no cell is allocated.

## Pool, binding and selection ownership

The view owns a pool of typed native cell owners. A cell owns presentation and
its binding scope only; it does not own catalog rows, search policy, playback or
artwork executors. Rebinding first seals/cancels the old binding scope, increments
its generation, clears stale presentation and then publishes the new snapshot.
An in-flight callback may finish against pinned old state but cannot mutate the
new binding. Final cleanup follows UI2; a reused address is not proof of identity.

A cell key/content/style/geometry revision tuple controls work: unchanged
presentation performs **0 cell rebinds** and **0 redundant native setters**.
Entering or changed visible/overscan rows account for bind work. Pure root motion
does not reset child editor/image state. Updating one item does not traverse all
100,000 items on every frame. Source indexes may do declared one-time work for a
sort/diff; record that cost separately from per-frame presentation.

Let Vmax be the maximum geometrically visible capacity of the viewport during
this run (including partially visible edge cells). The upper bound is
**native cell owners ≤3 × Vmax + 2**. The extra two are explicitly named pinned
editor/focus cells, not spare overscan slots. Count hidden, unbound, animating and
retired-but-not-released cells too; do not hide ownership in toolkit caches.
All cell roots, not their child labels/buttons, are the counted unit; report
child/native-handle counts separately. Publish pool counts after viewport shrink
and during teardown; Vmax cannot increase simply because the provider allocated
more cells. A separate current-visible count explains retained high-water capacity.
If more than two cells need pinning, settle an interaction or reject the new
request explicitly; do not expand the exception silently. Variable-size layouts
must declare minimum extents and a bounded viewport-capacity estimator so zero-
height rows cannot turn the budget into an unlimited pool.

The selection model owns selected keys, anchor and active key. Single/multi/range
modes are explicit. Range extension traverses the current ordered source from a
stable anchor; a sort changes positions without changing selected identities.
Filtering may retain selected hidden keys as model state, with a truthful hidden-
selection count, but active focus moves to a visible eligible key. On deletion,
remove the deleted key and choose the nearest surviving successor in prior view
order, then predecessor, then container/empty fallback; record the fallback in
the same committed revision. Tree collapse moves active focus to its ancestor
while optional retained descendant selection remains distinguishable.

A recycled cell reads this model; it cannot retain selection just because its
native selected flag remained set. Model setters emit no user selection/commit
command. Keyboard/pointer/accessibility activation uses one command identity and
revalidates state immediately before delivery.

## Scrolling, anchors and accessible realization

Use logical top-left content coordinates on both axes. Keep content origin,
viewport offset, screen transform and data order distinct. A stable anchor is
item key plus intra-item offset/alignment and source revision, not row number
alone. After sort/insert/resize, resolve the key in the new snapshot and preserve
its relative viewport placement; clamp only to legal bounds. If deleted, apply
the declared successor/predecessor fallback. If filter/query policy deliberately
resets the viewport, report that transition rather than calling it preservation.
Avoid reapplying equal native offsets/content sizes, preserving AlbumGrid's
momentum behavior. Fractional offsets remain fractional until native conversion.

scrollToItem validates the key/revision, asks the layout index for geometry and
returns pending when data is unavailable. Completion checks owner and request
generation before moving the viewport; a newer user scroll cancels or supersedes
an older programmatic request by explicit policy. Variable-height measurement
updates preserve the anchor while their index converges within a declared budget.
No full offscreen child realization is needed to locate one item.

Nested scrolling receives typed units, axes, direction and available gesture/
momentum phase. The child reports consumed and remaining motion in the same
units; each axis passes remaining motion to its eligible ancestor once. At a
zero-range or clamped boundary it consumes zero on that axis. A popup/capture may
own a gesture by an explicit UI3 policy, never by indiscriminately swallowing
wheel input. Begin/end/cancel survives detach or direction reversal. Unknown
native phase remains unknown; SDL floating deltas do not imply pixel units.
Native overscroll and fling trajectories remain platform behavior.

Accessible realization uses the same source keys, revision and pool budget,
not a hidden second collection of native views. A screen reader can request an
offscreen item; return pending/busy, schedule bounded realization, scroll if
needed and transfer accessibility focus only after revalidating the request.
Deletion/sort during realization resolves by key or explicit missing/stale
outcome. Virtual proxies can remain after cells recycle and therefore carry
stable generation checks; report their own cache/holder budget separately.

## E36 artwork ownership hooks

A bounded cell pool does not bound images. Charge decoded, staging, native and
GPU allocations, including in-flight/retired uploads, to one accounting owner;
report physical allocations without double-counting shared aliases. Proposed
catalog artwork limits are **128 MiB desktop / 64 MiB mobile**, a subset of the
product working-set limit (**512 MiB / 384 MiB**), with stricter existing BTRSmith
limits prevailing. Allow **at most two simultaneous thumbnail decode/conversion
jobs** and reserve peak bytes before allocation. Downsample to the displayed
256/512-pixel fixture variant; oversized sources cannot allocate first and claim
failure after the limit is exceeded.

The data owner schedules artwork; cells request/release presentation claims and
supply the binding generation, never start an uncontrolled worker per cell.
Cancellation/recycle/close retires obsolete results and releases their bytes
once. Displayed handles stay retained under the approved IImageHandle contract.
Explicit trim or real memory pressure releases all eligible unreferenced cache
entries within **1 s** in a quiescent fixture with **0 repaint requests solely
for eviction**. Frame-count-based eviction cannot satisfy idle trim. Count pending
GPU retirements explicitly and report a failed drain rather than pretending
those allocations vanished.

## Five-platform mapping and dependencies

| Family | Native adapter candidate and qualification boundary |
|---|---|
| macOS | NSCollectionView, NSTableView and NSOutlineView data-source/delegate owners; keyed batches and reused cells share the portable selection/source model. CL-UIB-09 qualifies required Objective-C protocols/subclasses under interop steps 3/6. |
| Linux | GtkListView/ColumnView/TreeListModel if D23 chooses GTK4, with factory bind/unbind and GtkAccessible realization; otherwise a bounded SDL recycler plus AT-SPI bridge. CL-UIB-12 and GObject step 8 or verified D-Bus export remain prerequisites. Qualify X11 and Wayland independently. |
| Windows | Owner-data ListView and appropriate virtualized/custom TreeView adapter; a plain TreeView is not assumed to virtualize 100,000 native nodes. Prove bounded owners or record the adaptation. Typed UIA providers require CL-UIB-10 and COM step 5; cross-architecture host lanes remain required. |
| iOS/iPadOS | UICollectionView diffable data-source snapshots with stable item/section keys, reused cells and selection model. CL-UIB-09 after UIKit step 6 qualifies delegates/generic erasure. iPad is device_class in ios, with split/Stage Manager resize and hardware-keyboard selection. |
| Android | RecyclerView with stable IDs, DiffUtil and scoped bind/recycle work; detect/avoid lossy collisions when adapting portable keys to numeric IDs. CL-UIB-11 after JNI steps 4/7 qualifies androidx reader/shims and accessibility realization. |

Use [native-interop-ownership](../native-interop-ownership.md) for checked entry,
native claims, release executor and cycle cancellation. Header import, a C/Java
prototype or an accessibility JSON projection alone cannot qualify a provider.
BTRSmith migration waits for btrc contract/provider landing and the pin bump;
this read-only caller audit grants no change to its composition or domain model.

## CX-UIB-28 stress fixture plan

Use CX-UIB-08's **100,000 stable records**, not 100,000 media files. The fixture
`CollectionStress.btrc` and driver `test_native_ui_collections.py` are owned by
CX-UIB-28 after contract approval; this packet adds neither. Deterministic seeds,
key order and operation journal make both frontends comparable.

1. Start with empty/loading/error and 1/viewport/100,000-item snapshots. Exercise
   list/grid/table/tree layouts at narrow/wide widths and changing row sizes.
   Capture visible capacity, Vmax, allocated/live/retired/pinned cells, native
   handles, bind/setter counts, model revision and memory category counters.
2. **E09/E29:** scroll while inserting, sorting, filtering, deleting and expanding;
   preserve stable anchors/active keys, apply the documented deletion fallback,
   and inject failure at every native batch mutation. Assert no duplicate owner,
   wrong-item edit or partially acknowledged batch; retry produces one commit.
3. **E21:** request item 99,999 through each native assistive transport before it
   has a cell. Race sort/delete/recycle with completion. Assert stable announced
   position, bounded realization and explicit pending/missing/stale outcomes.
4. **E24:** saturate the executor while recycling cells and closing one of two
   scenes. Complete old image/child requests out of order. Assert generation
   rejection, terminal completion accounting and zero stale cell mutation.
5. **E36:** separately traverse the 1,000-album workload with 256/512-pixel
   thumbnails and oversized sources; enforce byte/concurrency reservations and
   perform 100 cancel/recycle/close-during-upload cycles. Stop both rendering and
   scrolling, trim, and verify the 1 s/zero-repaint target without evicting live
   presentation claims.
6. **E41:** 100 gestures per supported detented-wheel/precision-trackpad/touch/
   keyboard-accessibility class, including nested axes, zero range, fractional
   deltas, content shrink, RTL and 100/150/200% scale. With overscroll disabled,
   final-position error ≤1 logical unit; zero duplicated deltas or stranded
   end/cancel. Report unavailable phase information and native adaptations.
7. Run 10 minutes of continuous scrolling/diff/resize with frame counters:
   at 60 Hz, p95 ≤16.7 ms and p99 ≤33.3 ms; report missed presents/longest stall.
   Unchanged settled presentation has zero rebinds and no application-requested
   layout/paint churn. Measure idle 60 s separately with/without assistive tech.
8. Shrink the viewport, force trim, then close/reopen 100 times. Check the
   3×Vmax+2 rule throughout, report retained high-water counts and require zero
   leaked owned handles/registrations after successful drain. Deliberately use
   an unbounded mock owner once to prove the budget assertion fails; do not make
   the real regression xfail or count the mock failure as native evidence.

Emit ledger measurement rows for native cells, binds, memory and frame timing
with btrc/BTRSmith revision where applicable, provider/frontend/backend, runner,
OS/toolkit, load, warmup and device class. Run reference/selfhost and plain/
sanitized where supported. Software rendering and hosted/simulator frame numbers
are stand-ins; **MAC-UIB-03** supplies physical timing evidence. Report missing
provider or unavailable transport separately, never as a passing empty run.
