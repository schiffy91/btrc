# Keyed collection data model feasibility

CX-UIB-06. Never merge this prototype branch; its findings PR contains only
`docs/design/native-ui-contracts/spikes/collections-data-model.md`.

Run in the pinned shell from the repository root:

```bash
nix develop --command bash spikes/collections-data-model/run.sh reference
nix develop --command bash spikes/collections-data-model/run.sh selfhost PATH_TO_CURRENT_BTRCC
```

The source is pure btrc, with standard assert.h assertions. The script compiles
to strict C11 and uses ASan/UBSan with leak detection enabled and no suppression.
Both frontend executables returned 0 and identical counters in `evidence/`.
Use a self-host compiler built from the same main base and pinned shell.

The primary source contains 100,000 generic Row<int> objects in a Map plus an
ordered key Vector. An interface exposes the order/revision lookup. Batches
validate base/next revision and duplicate/missing/deleted keys before mutation;
then a snapshot rebuild applies deletes/filtering and a real descending sort.
Source mutation is synchronous; this is not a concurrent publication model.

Sixty model Cell objects serve a maximum viewport of 20, with one viewport of
overscan on either side. Reconciliation marks retained keys before recycling,
preserves unchanged content revisions, unbinds inactive cells, and rejects old
key/generation tokens. It simulates 100 scroll positions, a reverse sort with
an identical retained key window, filtering, selected/visible deletion, empty
and repopulated selection, invalid batches, content updates and viewport shrink.
Selection is represented by anchor/active keys; this does not implement all
multi-selection/range policies.

The 3×Vmax+2 comparison counts all 60 model cells, even unbound retained cells.
No native view exists, the two extra pinned owners are not exercised, and a
viewport larger than 20 is outside this prototype. A zero-size viewport and a
shrink to 5 retain the 60-object high-water pool, which is reported rather than
hidden. Bind counts are model calls, not native-setter counts.

Every batch rebuilds the entire order; descending batches sort it. Deleted rows
remain tombstones in the source map until teardown. These are explicit costs,
not proposed per-frame production behavior. Per-frame work scans only the
bounded pool/window, but zero rebinds does not imply zero CPU work. The
repopulation test temporarily constructs a second 100,000-row source; it is
not a claim that peak row ownership is limited to 100,000.

Two cells deliberately form an ARC cycle. Both frontend runs end with zero live
rows/cells and no sanitizer diagnostic. This proves that specific graph only,
not arbitrary callback/cross-runtime cycles. No compiler defect was observed.
