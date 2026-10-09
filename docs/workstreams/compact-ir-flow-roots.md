# Compact tagged IR with safety-rooted flow retention

The combined compiler at `c8221ae4ff9f7e157917943509304ca02f84698f` composes
compact `61d60799` and flow `266cadd7` on exact `6f1b81d9`. It preserves
fat tagged IR, domain-guarded projections, copied fixed flow-root policies,
and unconditional function-summary/dependency export. The merged selector
also traverses declaration array bounds. The standalone packets and their
successful and failed evidence remain unchanged.

## Correctness evidence

The combined source passed its fresh selfhost build, 37 compact cases,
seven flow reference cases, and the actual selfhost flow driver, including
array-bound-only setjmp reachability. The additional original selfhost
incremental effect-changing edit passed separately. Its direct current
BTRSmith `dbe8df0e` compile preserved all 423 macOS C/header outputs and the
complete ordered link plan against the retained baseline at common roots.
The corresponding result/audit pairs are `59144619`/`457ae6be` and
`51f67e69`/`f36ce4f9`. These focused proofs do not replace final-tree gates.

## Measured Linux current-product result

Private hosted run `37901757750`, workflow head
`5f3103a21dca1e2bd1e079db292c81176fa4f15f`, completed successfully on
2026-10-09. It compared baseline `6f1b81d9` with combined `c8221ae4` on
product `dbe8df0e806bb0a3e7fb65b0b4f8e233f674b472`. Both compilers used the
same authenticated Linux GCC 15.2 toolchain, original strict C11/O2 flags,
canonical Linux entry and shared product environment. The binaries and
generated C were reused from authenticated artifact `11600342131`, not
rebuilt or substituted. Fresh admission checked source, flags, tools, ELF
interpreter and runtime closure. The original run did not record library
byte hashes; the reuse proof explicitly retains that retrospective limit.

All 45 focused cases (37 compact, seven flow, one selfhost incremental edit)
and the actual native flow driver passed again. The original sequence was
`warm-B, warm-C, 1-B, 1-C, 2-C, 2-B, 3-B, 3-C`; both warmups were discarded.
Every compile retained the original 240-second bound, cold cache, strict
imports, debug module units and one inline worker. All eight outputs had
exactly equal complete C/header rosters, normalized contents and ordered
plans. Linux emitted 422 C/header files; its plan is the 423rd semantic
comparison entry. This is distinct from macOS's 423 C/header files.

| Measured sample | Baseline peak RSS, bytes | Combined peak RSS, bytes |
| --- | ---: | ---: |
| 1 | 3,469,336,576 | 2,329,120,768 |
| 2 | 3,470,024,704 | 2,325,925,888 |
| 3 | 3,471,245,312 | 2,326,315,008 |
| Median | 3,470,024,704 | 2,326,315,008 |

Median Linux peak RSS fell by **1,143,709,696 bytes (32.9597%)**. The worst
combined sample was **2,329,120,768 bytes**, still **718,508,032 bytes above
the 1.5 GiB target**. Linux wait4 RSS is not Apple peak footprint or final
target acceptance. Median observed wall time was 124.184 seconds versus
115.342 seconds (7.12% lower); host variation and unavailable instruction
counters prevent an instruction-based speed claim. Instructions retired
and Apple footprint remained null, with the actual perf-policy refusal
recorded. No system setting or threshold was changed.

The independent audit rehashed the complete 215,216,793-byte ZIP and all
33,295 members in place, independently parsed raw per-sample wait4 telemetry,
recomputed all eight C/header/ordered-plan comparisons and summary arithmetic,
and verified source, binary, tool, environment and reuse closure. All 22
stage receipts recorded successful reaping; the hosted owner recorded the
21 prior process groups absent. This was not a separate remote PID probe.
The uploader omits two hidden empty publication leases per output; their
identities and empty hashes are receipt evidence, not rehashed payload bytes.

Evidence: `/private/tmp/btrc-audit-repair/compact-ir-flow-linux-memory-success-37901757750/`.
Artifact `11603088704` ZIP SHA256:
`1e2f7d42905bacdcbb95a9c3d537c3cf2d7b9e27b9138ba36b9a5ef8428d1c4f`.
Independent audit SHA256:
`4bb27c36f906fd406a76410f536aa234a3ec9a9b5ab682e45390a5861de42576`.
Prior environment, tool-probe and receipt-label failures remain preserved;
discarded warmups from those attempts earn no measured-sample credit.

## Remaining work

The 1.5 GiB target remains open, as do final combined-tree full qualification
and instruction-based performance acceptance. A proposed Linux-only phase
RSS diagnostic will locate whether the remaining peak occurs before final
solve, during finish/emission, or during final publication. It must preserve
the current generated C and product-output parity; instrumented observations
will not become performance acceptance. No retention or ownership change is
justified solely by the historical census or by this aggregate RSS result.
