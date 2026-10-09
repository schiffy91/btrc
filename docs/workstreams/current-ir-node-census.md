# Current compiler IR allocation census

The October 9 diagnostic compiled exact compiler `6f1b81d9` and product
`dbe8df0e` on Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0. A fresh strict
Clang 21.1.8 `-O2` MacOSMain build supplied the uninstrumented compiler C;
five checked private instrumentation insertions supplied the observed binary.
Removing those insertions reproduces every byte of the original C.
Production compiler, runtime, generated catalogs and product sources were unchanged.

Both cold debug module-unit product compiles use one worker, lower 461 groups
with zero reuse, and return zero. Their actual output rosters contain 423 C/header
files and match after only output-directory spelling normalization. No native
product link or runtime acceptance is claimed by this diagnostic.

| Snapshot | Unique live IR nodes | Allocator bytes for those nodes | Incoming records |
|---|---:|---:|---:|
| After lowering | 3,219,828 | 1,236,413,952 | 3,517,805 |
| After final demand | 3,219,828 | 1,236,413,952 | 4,774,976 |
| After emission | 2,995,587 | 1,150,305,408 | 4,428,087 |

Each node's C structure is 368 bytes and its allocation is 384 bytes. Each live
identity is counted once regardless of sharing. The observer's 67,108,864-byte
registry is reported separately. Incoming-owner counts are per-node distinct
owner identities summed, not globally unique objects or attributed heap bytes.
The unchanged node count and additional ownership after demand do not show
copied nodes. String/vector backing allocations, AST and analysis data remain
outside this census's allocation totals.

The uninstrumented run records a diagnostic peak footprint of 3,081,620,168
bytes. It is a single unpaired run without quiet benchmark admission and does
not replace the accepted performance baseline. Its gap to the 1.5 GiB objective
is larger than all observed IR node blocks; a node-storage change alone cannot
close that observed gap by reducing those blocks.

## Implementation direction

Retain the fat-tagged IRNode and its identity. A source-reviewed design keeps
hot leaf/binary fields and cross-cutting provenance inline and moves other fields
into one optional owning reference to typed domain payloads. The current-kind
upper-bound model charges payload headers and new incoming records and predicts
534,773,712 bytes (about 510 MiB) less node/payload storage after lowering.
61.1% of nodes need no payload. This is a planning estimate, not a measured gain;
1.25 million additional payload allocations are a material runtime risk.

Implementation must preserve all 55 fields, supported kinds, absence/default
semantics, shared-child ownership, canonical and diagnostic traversal order,
setjmp/volatile behavior, native forms and deferred generic diagnostics. Actual
layout sizes, allocator costs, current-product output equality, paired memory
and instruction measurements, and all required final gates remain necessary.
Separate source review identifies retained SetjmpPointerFlowResult maps aliased
through kept analyses/optimizers. Retiring facts requires proof of their last
safety use and invalidation behavior; no historical retention estimate is counted
as current savings.

## Evidence

Retained directory:
`~/.cache/btrc/plan-consolidation-2026-10-07/irnode-census-6f1b81d9-attempt-1`.

- Result: `f64bbc1f2400eb184f37ea14303095a3d07e39bc4e4f85cd431f4ce551716b98`.
- Independent audit: `eadb8d2f8cc5bdf72e4049a273be4fffc704802490f69538f230050903761980`.
- Census: `2cf7063839e6e91d993aeb95dcbfb82ebf7d69b98c250c8165c40caa022c375e`.
- Compact-layout planning data: `0e573d1a3233676c44ef787561ca55628c4b3111316c14e0875b02cdebd11881`.

All 4,502 compiler and 846 product files match immutable Git blobs and modes.
All ten owned process groups are absent and their leaders reaped with status
zero. Source archives, tools, binaries and command logs close unchanged.
