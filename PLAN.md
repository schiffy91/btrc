# PLAN: compile performance, platform parity and native UI

**Priority: optimization → C compatibility → platform foundations → native UI → release qualification.**
Current work is **bucket 1 / edit and cold-build acceleration**. The unchanged-build
latency objective is closed at the user-approved **≤5 s** target. Native UI
implementation stays queued until bucket 4.

Goal: make a BTRSmith body edit build to an executable in **10 seconds or
less**, an unchanged build in **5 seconds or less**, and a cold self-hosted
development build at the new working target of **13 seconds**, including native
compilation and linking. Edit and cold builds must improve by at least 10×
against the repeated baseline. Keep both compilers, strict C11, ownership safety,
and bootstrap qualification. Section 1 defines intermediate targets and
exactly what is timed. These are proposed acceptance budgets, not forecasts.

Latest September 22 actual-Make comparison on macOS: **97.427 s cold** and
**92.095 s navigation body edit**, medians of two alternating baseline/current
pairs. The lexical type-map copy cut saves **3.35% cold / 2.26% edit** versus
its matched previous compiler (100.803/94.224 s). The earlier filename-reuse
and setjmp cuts saved 13.7%/13.3% and 4.6%/5.4% in their own comparisons.
These are diagnostic pairs, not qualifying 5-cold/20-edit distributions.
M0–M6 landed; unchanged latency is closed at 5 s, and M7 is partially complete.
The working design budgets remain **13 s cold / 10 s edit**, with final ≥10×
acceptance against a frozen repeated baseline on each required host. Continue
M7's remaining analysis/lowering costs before M8a and M11.
Historical measurements live in
[`docs/design/compile-performance.md`](docs/design/compile-performance.md).

Implementation is paused at the user's September 22 quota checkpoint. The full
unit rerun records **7,638 passed / 49 skipped / 1 intermittent warm-link cache
assertion failure**. The affected modules subsequently pass 42 tests, and ten
diagnostic repetitions pass; this does not close the failed full-suite gate.
On resume, reproduce that cache miss under suite load, then continue bucket 1
at M7 before M8a and M11. Conditional
experiments still require their stated evidence; proposed budgets are not
measured results. Section 1 records evidence and budgets; section 2 defines
verification; section 3 preserves the implementation history; section 4
specifies the remaining performance work; section 5 contains the separate
C-compatibility proposals; section 6 adds iOS, Android and Windows parity;
section 7 inventories native UI across all five platforms; section 8 defines
the required execution order and milestone gates.

## Execution order: five buckets

User-directed sequence, 2026-09-21; performance priorities revised 2026-09-22.
**Work one bucket at a time, in this order.** The active bucket is **1 — compiler
performance**, now focused on **10× faster edit-to-executable and cold self-host
BTRSmith builds**. The unchanged-build latency campaign is closed: the user
raised its target to **≤5 s**, and all ten current qualified macOS samples are
below it (medians 4.180/4.732 s; maxima 4.213/4.794 s). This replaces the earlier
2 s target and associated 3 s p95 gate. Keep ≤5 s as a regression guard; do not
spend further optimization work closing the retired 2 s gap. Required-host and
full-tree correctness evidence remain open and must not be described as passed.
The user explicitly authorizes moving on from this latency gate; residual M6a
qualification is not a reason to keep optimizing no-op paths. The platform
and UI inventories are planning artifacts; they do not authorize starting those
implementations ahead of this sequence. This overrides earlier recommendations
to develop platform/UI work alongside optimization.

**The five big chunks, in order:**

1. **Optimize the compiler and builds.** Finish reliable incremental builds,
   measured compiler optimizations and separate compilation; prove BTRSmith's
   numeric build-time and memory goals.
2. **Complete C compatibility.** Close the planned language and interop gaps
   through both compilers, with explicit supported and rejected cases.
3. **Establish cross-platform foundations.** Bring Windows, iOS and Android
   build, runtime, library and packaging support to the required parity.
4. **Complete native UI.** Implement the inventoried toolkit and BTRSmith UI
   across macOS, Linux, Windows, iOS and Android.
5. **Qualify the product and releases.** Prove installed workflows, physical
   device/audio behavior, performance budgets and release gates on every target.

**Current assignment:** the initial cold/body-edit diagnostic checkpoint is
complete. Execute M7's dominant compiler cuts, M8a's measured allocation experiment
and M11a/full M11's separate compilation. Seek **at least 10×** improvement
against the frozen baseline in both self-host scenarios. Budgets are
**≤min(10 s, edit baseline / 10)** for body edits and
**≤min(20 s, cold baseline / 10)** for cold dev executables; the existing
long-term ≤5 s body-edit objective remains. Do not turn this into another
no-op micro-optimization campaign. Buckets 2–5 stay queued.

**Before choosing the next task:** identify the first unfinished milestone in
the active bucket and its next unmet exit criterion. Work on that criterion or
a demonstrated prerequisite. Native UI is bucket 4; its inventory is retained
for later execution, not a reason to switch away from optimization. Status
updates must lead with the active milestone, measured KPI gap and next action.

| Order | Bucket | Milestones / scope | State and exit requirement |
| --- | --- | --- | --- |
| 1 | Compiler performance and reliable incremental builds | M6a → M7 → M8a → M11a/full M11; then evidence-gated M8b/M9/M10 as required by the remaining budgets | **Active: M7 → M8a → M11; initial edit/cold diagnostics complete.** M6a unchanged latency is closed at ≤5 s by user direction. Prove section 1's remaining build/compile/memory KPIs on the actual BTRSmith workload and required hosts, with applicable compiler gates. Headline goals: ≤5 s no-op regression guard, ≥10× self-host edit/cold acceleration, ≤10 s edit build at M11, ultimately ≤20 s cold self-host dev build and ≤5 s self-host body edit. |
| 2 | C compatibility | C1 → C2 → C3 → C4 → C5, with a reproducible baseline before changing behavior | **Queued.** Both frontends pass the specified compatibility/negative corpus; deliberate refusals are documented and applicable compiler gates pass. |
| 3 | Cross-platform build and runtime foundations | P0 → P1 → P2/P3/P4; W1 and the non-UI target, runtime, storage, audio/GPU and packaging foundations of W2/I1/I2/A1/A2 | **Queued.** Required Windows/iOS/Android targets, ABI/runtime/library/package contracts and test hosts work through both frontends. UI-dependent product exits remain assigned to buckets 4/5. |
| 4 | Native UI across all five platforms | UI0 → UI1 → UI2/UI3 → UI4–UI9 → UI10/UI11, including the UI portions of W2/I1/I2/A1/A2 | **Queued; inventory only so far.** Implement and qualify the full native UI contracts, platform providers, BTRSmith screens and UI budgets; retain all extended toolkit scope. Accessibility and ownership are acceptance criteria for each control. |
| 5 | Complete product and release qualification | P5 → P6 → P7; final W2/I2/A2 installed-product exits and cross-track regression matrix | **Queued.** Installed BTRSmith journeys, physical audio/device checks, numeric budgets, packaging/signing, upgrades and CI/release gates pass on the final revision. |

Do not move to the next bucket until the current exit requirements are proven
or the user explicitly changes the order/scope. Conditional performance
experiments retain their existing evidence requirements; unnecessary machinery
is not a deliverable. Detailed operating rules and the immediate next checkpoint
are in [section 8](#8-execution-order-and-milestone-gates).

### Bucket 1 KPI checkpoint

The **unchanged-build latency objective is closed** under the September 22
user-approved ≤5 s target on the measured macOS workload. Edit/cold and broader
qualification targets remain open. The chronology below retains earlier
measurements and superseded 2 s goals; it does not override the current scope. The September 21
actual `make btrsmith-native` runs use BTRSmith `5549c261` plus the product Make
repairs and working-tree compiler on macOS. Both frontends now pass the real
dev-to-release and native-option invalidation probes. The earlier Make shortcut
failed preserved-timestamp edits, removed sources and byte-identical touches.
The entry point now delegates validation to both tools on every invocation;
real compiler/native fixtures pass those cases under system and GNU Make.
The earlier fast unchanged-build timings therefore do not qualify the no-op KPI. See the
[actual-make evidence](docs/design/compile-performance.md#actual-product-make-baseline-september-21).

Before SDK dispatch, Darwin link reuse measured **10.293 s self-host /
9.810 s reference warm medians** at the actual Make entry point, five repeats
each after a seed.
Every warm invocation hits the compiler artifact cache, reuses all native
objects (17 self-host / 39 reference) and performs **zero links**. Executable
bytes/inodes/mtimes and emitted-generation/ownership metadata remain unchanged;
both executables retain complete debug maps.

Bounded SDK dispatch is now qualified on the actual Make entry point:
**9.222 s self-host / 9.043 s reference warm medians**, five repeats each.
All ten warm builds retain the complete emitted generation and executable,
hit compiler/object caches, and perform zero compiles and zero links. Both
debug maps remain valid, and production/product/test inputs stay unchanged.
At that checkpoint, the two-second KPI was unmet by **7.222 s / 7.043 s**. These sequential
measurements do not isolate the SDK component's contribution. Separate 50 ms
full-process-tree diagnostics sample peaks of **714.2 / 686.1 MiB**; they are
lower bounds on true peak, not required-host memory acceptance. See the
[SDK dispatch product evidence](docs/design/compile-performance.md#bounded-sdk-dispatch-product-measurement-2026-09-21).
Five alternating native-only pairs measure 2.617 → 2.631 s self-host and
4.663 → 4.732 s reference: validation replaces approximately the same amount
of work as linking, so no elapsed-time improvement is established. Native
process peak RSS falls from about 175/183 MiB to 92/94 MiB respectively; this
is not aggregate full-build memory. Supported receipt admission requires two
links, so cold/miss cost must also be included in future acceptance runs.

Owned digest reuse now improves the actual self-host Make command from
**9.035 s → 8.341 s median** in five alternating baseline/current pairs:
**0.694 s (7.7%)** saved. The reference control measures **9.169 s median**
over five warm runs; its compiler implementation is unchanged by this step.
All 15 warm runs retain outputs, hit compiler/object caches and perform zero
compiles/links. Both debug maps pass; source, test, tool and product inputs are
unchanged. At that checkpoint, the no-op gaps were **6.341 s self-host / 7.169 s reference**.
Separate sampled process-tree peaks are **708.7 / 689.2 MiB**, lower bounds on
true peaks. Six system/GNU Make check invocations pass on the new compiler.
CLI/structure/frontend-I/O coverage passes 156 tests with two platform skips;
GCC digest/corruption/publication coverage passes 11 tests without skips.
Generated-source, lint and Python formatting checks pass. The full final-tree
and required-host matrix remains open. See the
[alternating actual-Make comparison](docs/design/compile-performance.md#owned-digest-reuse-actual-make-comparison-2026-09-21).

SDK-cache integration in both frontends now measures **8.285 → 7.021 s
self-host medians** in five alternating baseline/current pairs, saving
**1.264 s (15.3%)**. The reference measures **7.748 s** across five current warm
runs. All 15 warm builds hit compiler/object caches, retain outputs and perform
zero native compiles/links. The current SDK receipts remain unchanged throughout
each warm series; both debug maps pass and all 1,314 recorded inputs remain
unchanged. At that checkpoint, the no-op gaps were **5.021 s self-host / 5.748 s reference**.
Separate sampled process-tree peaks are **713.6 / 683.7 MiB**. Empty-SDK-cache
runs with warm compiler/native artifacts retain outputs and sample
**713.2 / 688.5 MiB**; their instrumented 10.096 / 11.119 s wall observations
are diagnostics, not headline KPI samples. All are lower bounds on true peak.
The combined reader/cache, lifecycle, frontend-I/O and structure run passes
268 tests with one `/dev/full` skip; frontend integration passes another 47.
Six system/GNU Make check runs pass. See the
[SDK-cache actual-Make comparison](docs/design/compile-performance.md#sdk-cache-actual-make-comparison-2026-09-21).

Worker-failure and cleanup qualification now passes through the actual Make
entry point at **7.053 s self-host / 7.697 s reference**, five warm samples each.
All ten retain outputs and SDK receipts, reuse all objects and perform zero
compiles/links; debug maps pass and all 1,317 recorded inputs stay unchanged.
These are current measurements, not a paired speedup claim for cleanup. Current
no-op gaps are **5.053 / 5.697 s**. Separate sampled process-tree peaks are
**711.4 / 684.4 MiB**, lower bounds rather than memory acceptance. The final
reader/cache suite passes **215 tests** and frontend integration **47**, with
no skips. Launch failure falls back, crashes remain failures, live child/writer
leases prevent premature collection, and abandoned captures/partial publications
are collected without changing prior entries. See the
[cleanup checkpoint](docs/design/compile-performance.md#sdk-worker-failure-and-interruption-cleanup-2026-09-21).

Native physical-header identity is now repaired on the POSIX Clang path, and
its decoder/reconciliation work is optimized. The actual Make recheck measures
**6.720 s self-host / 7.407 s reference**, five warm samples each, leaving
**4.720 / 5.407 s** to the two-second goal. All ten retain outputs and SDK
receipts, reuse all 17/39 objects, perform zero compiles/links and pass debug-map
checks; all 1,319 recorded inputs remain unchanged. This is a current checkpoint,
not a paired estimate of the repair's speedup. The 185 existing native build,
link, debug and performance tests and 15 new final identity regressions pass;
12 GCC cache checks also pass. See the
[physical-header repair](docs/design/compile-performance.md#native-physical-header-identity-repair-2026-09-21).

The preceding native process-worker checkpoint measured **7.079 → 7.027 s self-host /
7.766 → 6.814 s reference** in five alternating actual-Make pairs per frontend.
Self-host is effectively flat; reference saves **0.952 s (12.3%)**. All 20 warm
runs retain outputs and SDK receipts, reuse all objects and perform zero
compiles/links. Debug maps pass and all **1,324 recorded inputs** remain
unchanged. Separate process-tree samples rise from **709.8 → 1,066.0 MiB
self-host / 677.1 → 1,000.4 MiB reference**. This is an explicit memory-for-time
tradeoff, not a memory optimization or required-host acceptance. The existing
200 native cases, six final process-boundary cases and four packaged CLI cases
pass; the latter use Python 3.14, separately from Python 3.13 product timing.
See the [process-worker comparison](docs/design/compile-performance.md#bounded-native-process-workers-2026-09-21).

Earlier single cold samples were **127.646 s self-host / 349.113 s reference**,
from before debug retention and link reuse; a qualifying cold distribution is
still outstanding.
These are local macOS diagnostics with working-tree overrides, not installed,
pinned or required-host qualification. Inputs stayed unchanged during all
24 native and 12 actual Make runs. The native-builder/debugger/performance
selection passes 185 tests without skips; both Make versions pass product
checks. See the [earlier evidence](docs/design/compile-performance.md#darwin-executable-reuse-2026-09-21).

**Latest: integrated native preprocessing receipts.** Five alternating
actual-Make pairs per frontend measure **6.596 → 6.245 s self-host** and
**6.314 → 5.794 s reference**, savings of **0.352 s (5.3%) / 0.520 s (8.2%)**.
Both variants use the same final reader, so this comparison isolates the
consumer integration; it does not separately measure the shared platform-hash
change against the earlier checkpoint. All 20 warm runs retain outputs and SDK
receipts, hit every object, and perform zero compiles/links. The current path
hits all 17/39 preprocessing receipts. All **1,330 recorded inputs** remain
unchanged and debug maps pass. Separate sampled process-tree RSS falls from
**1,065.0 → 304.3 MiB self-host / 1,030.0 → 551.9 MiB reference**; these are
sampling lower bounds, not peak-memory guarantees. See the
[consumer evidence](docs/design/compile-performance.md#native-preprocessing-consumer-integration-2026-09-21).

Structured trace sharing now measures **6.408 → 6.139 s self-host /
6.044 → 5.612 s reference** in five alternating actual-Make pairs
per frontend. All 20 warm builds hit compiler/native caches, retain outputs and
SDK receipts, and perform zero compiles/links; debug maps pass and all
**1,330 recorded inputs** remain unchanged. The helper passes **293 tests**
without skips and all **56 product parity units**. Native-only warm medians
improve 2.000 → 1.884 / 2.996 → 2.630 s; cold medians are effectively unchanged.
Separate process-tree RSS samples are **302.2 → 303.6 MiB self-host /
551.8 → 552.6 MiB reference**, lower bounds on true peaks. The initial
Make attempt lost unrooted Nix helpers; it is preserved and excluded from this
complete rerun. Both helpers now have GC roots. See the
[structured-trace evidence](docs/design/compile-performance.md#structured-filesystem-trace-sharing-2026-09-21).

Grammar-derived operator lookup now measures **5.902 → 5.467 s self-host**
in five alternating actual-Make pairs: **0.435 s (7.4%)** saved.
The unchanged reference control measures **5.306 s** over five warm runs.
Baseline and candidate binaries used the same Apple Clang build recipe; the candidate reaches a
byte-stable self-host fixed point. All 15 timed builds hit compiler/native caches,
retain outputs and SDK receipts, and perform zero compiles/links. The final
compiler passes **74 focused tests**. The source-graph phase falls from
**1.230 → 0.832 s**; this is a diagnostic
phase comparison, not an additional wall-time saving. Separate 50 ms process-tree
RSS initially sampled **307.4 → 353.3 MiB self-host**. Three subsequent
alternating pairs measured median **304.1 → 308.5 MiB** (+4.3 MiB / 1.4%);
the 353 MiB observation did not recur. All are sampling lower bounds, with
true peak-memory qualification still open. See the
[operator-lookup evidence](docs/design/compile-performance.md#grammar-derived-operator-lookup-2026-09-21).

Native macOS artifact hashing now measures **5.763 → 4.910 s self-host**
in five alternating actual-Make pairs: **0.854 s (14.8%)** saved.
The unchanged reference control measures **5.977 s** over five warm runs.
Both variants use matching Apple Clang builds and current source inputs. All
15 timed builds retain outputs/SDK receipts and perform zero compiles/links.
The native compiler reaches a byte-stable self-host fixed point and passes
**410 focused tests**, with one Windows-only skip. Its artifact-hit phase falls
**1.277 → 0.420 s**.
This optional managed provider uses the checked SDK binding; ordinary SHA256
and portable compiler entries retain their SDK-independent implementation.
See the [native digest evidence](docs/design/compile-performance.md#native-artifact-digest-2026-09-21).

The Make checkpoint precedes a subsequent Python startup repair: host integer
widths now use native-size `struct` instead of loading `ctypes`, whose Nix
libffi dependency aborts on this host. The numeric suite passes 27 checks;
the native Nix package now builds, and a compiler rebuilt from it reaches a
byte-stable fixed point and passes 152 focused checks (one Windows-only skip).
Keep final-tree performance/host qualification open.

The subsequent directive-cache comparison measures **4.673 → 4.526 s self-host**
in five alternating actual-Make pairs: **0.147 s (3.1%)** saved. The unchanged
reference control measures **5.586 s** over five warm runs. All 15 timed builds
retain outputs/SDK receipts and perform zero compiles/links; all 444 self-host
directive entries retain their bytes and metadata. The source graph falls from
**0.840 → 0.707 s**. The formatted compiler reaches a byte-stable fixed point and
passes **375 focused checks**, with one `/dev/full` skip on macOS. Separate
50 ms tree-RSS observations are **307.2 → 302.4 MiB self-host / 551.2 MiB reference**,
all sampling lower bounds. Compare against this run's paired baseline; differences
from earlier checkpoints do not isolate an optimization. See the
[directive-cache evidence](docs/design/compile-performance.md#directive-cache-candidate-and-interface-prerequisite).

Vocabulary identity reuse now measures **4.703 → 4.611 s self-host** in five
alternating actual-Make pairs, saving **0.091 s (1.9%)**. The unchanged reference
control is **5.567 s**. All 15 timed runs retain outputs and SDK receipts with
zero compiles/links; all 1,350 input fingerprints stay unchanged. The source
graph falls **0.743 → 0.643 s**. The candidate reaches a byte-stable self-host
fixed point and passes **213 focused checks without skips**. See the
[vocabulary identity evidence](docs/design/compile-performance.md#vocabulary-identity-reuse).

Absolute-path trace keys subsequently measure **4.388 → 4.248 s self-host /
5.283 → 5.062 s reference** in five alternating pairs per frontend, saving
**0.140 s (3.2%) / 0.221 s (4.2%)**. Both use the same freshly qualified compiler;
only the native helper differs. All 20 timed runs retain outputs and receipts,
hit all 17/39 preprocessing entries and perform zero compiles/links. All 1,357
input fingerprints stay unchanged. The two-second gaps are **2.248 / 3.062 s**.
The candidate passes 445 focused checks without skips; its interface-generic
prerequisite reaches a raw byte-stable fixed point. These local warm results
do not close full final-tree, cold/edit, package or required-host qualification.

Production shared trace fragments now measure **4.249 → 4.180 s self-host /
4.995 → 4.732 s reference** in five alternating pairs per frontend, saving
**0.070 s (1.6%) / 0.263 s (5.3%)**. All ten pairs favor the candidate; all
20 timed builds retain outputs, SDK/native receipts and fragment files, hit
all 17/39 preprocessing entries, and perform zero compiles/links. All 1,362
input fingerprints remain unchanged. The new format passes **463 focused
checks without skips**. Five paired cold-helper samples per frontend add
0.113/0.156 s to capture/publication; full product cold qualification stays open.

| KPI | Delivery goal | Latest recorded evidence | Remaining proof |
| --- | --- | --- | --- |
| No-op build, either frontend | **≤5 s; latency objective closed by user** | Actual Make: self-host 4.180 s / reference 4.732 s medians; all 10 current samples <5 s, full hits and zero compiles/links | Retain regression guard; required-host evidence remains separate. No further no-op optimization campaign. |
| Self-host body edit | ≤10 s at M11; final ≤5 s median / ≤8 s p95 | 92.095 s navigation edit median in two matched pairs; other two fixtures retain their earlier single-sample diagnostics | Separate compilation and real edit workloads on the required hosts |
| Cold self-host dev executable | ≥10×; working 13 s budget, ≤min(20 s, frozen baseline / 10) | 97.427 s actual-Make median in two matched pairs; 3.35% faster than their 100.803 s baseline | Actual entry point, pinned product/toolchain, 5 cold samples and final gates |
| Cold self-host compiler command | M7 ≤55 s; final ≤10 s | 88.750 s cold compiler median in the matched pairs, including artifact storage/output publication | Repeated phase/wall/RSS evidence; separate pipeline and publication costs |
| Cold reference dev executable | Final ≤75 s median | 349.113 s in one actual-Make diagnostic before debug-input retention | Pinned product/toolchain, 5 cold samples and final gates |

The historical 101 s cold build, September 20 direct CLI diagnostics and these
actual-make runs use different conditions; do not label their differences a
speedup or regression. Publication repairs have correctness evidence, not a
demonstrated improvement in these KPIs. The settings repair has correctness
evidence; preserve the remaining invalidation/qualification gaps.

---

## M6a: historical path from nine seconds toward the retired two-second target

**Superseded September 22:** the user closed unchanged-build latency at ≤5 s.
The analysis and allocations below are historical evidence, not active gates or
assignments. The unfinished SDK preparation/projection change is shelved as a
verified patch; production sources retain the previously qualified behavior.
The active assignment is the cold/edit campaign in section 8.

**Nine seconds is not close to the two-second goal.** The latest paired
actual-Make checkpoint measures **4.180 s self-host / 4.732 s reference**.
Self-host still needs **2.180 s removed (52.2%, or 2.09× faster)**;
reference needs **2.732 s removed (57.7%, or 2.37× faster)**.
Shared trace fragments save 0.070/0.263 s against their paired baselines.
Earlier vocabulary reuse, directive reuse and native artifact hashing were
qualified in separate comparisons; do not attribute differences between those
runs to this change. Both warm builds already perform zero native compiles and
zero links. The remaining problem is the cost of proving cached results valid.

Use these proposed component budgets to direct M6a experiments. They total
**2.0 s** and are engineering allocations, not achieved results or forecasts.
Phase medians and instrumented profiles are diagnostic; they do not add up to
an exact wall-time decomposition. End-to-end Make measurements decide success.

| Component | Current evidence | Proposed warm budget | Required change / proof |
| --- | --- | --- | --- |
| Source and configuration resolution | Self-host source graph: 0.611 s at fragment qualification | 0.3 s | Remaining reads/path work stays open; prioritize the larger native receipt cost before further cache-lifetime changes. Retain every alias binding and original-read validation. Preserve import removal, search order, package changes and edits with preserved timestamps. |
| Native SDK validation | Self-host SDK phase: 1.020 → 0.986 s with shared trace fragments | 0.4 s | Reduce remaining preparation/validation/consumption cost while retaining complete tool, SDK, options, dependency and search-path identity. Old dependency lists alone cannot detect newly shadowing headers; do not admit an unsound cache. |
| Emitted artifacts and publication | Self-host identity/load: 0.403 s, plus publication outside that timer; optional native hashing qualified locally | 0.4 s | Measure remaining file reads, parsing and publication work. Retain current-file corruption checks, locking, atomic recovery and output metadata. |
| Native object and executable validation | Native command medians: 1.346 s self-host / 1.802 s reference; initial receipt batch alone 0.955/1.374 s | 0.7 s | Profile duplicated receipt metadata, per-unit runtime/context preparation, fresh driver expansion and blob consumption. Share verified inputs only within proven ownership/lifetime boundaries. Preserve header shadowing, native options, tool replacement, library identities and debug inputs. Another hash-only memo is unjustified without new evidence. |
| Make/process startup and remaining overhead | Not separately isolated yet | 0.2 s | Measure the residual after the above changes and remove redundant orchestration; include startup and teardown in the real Make timing. |

**Implementation order within M6a:** warm receipt sharing, indexed operator
lookup, native macOS artifact hashing, directive-range reuse, vocabulary
identity reuse, absolute-path trace keys and shared trace fragments are
qualified locally for warm builds. Fragment publication adds a measured
0.113/0.156 s to cold helper work. Current v2 actual-Make owner profiling now
separates runtime/provider setup, driver expansion and fresh filesystem checks.
Follow-up self-host caller attribution now justifies testing deferred SDK
semantic projection on artifact hits, with bounded retention and diagnostic
ordering preserved.
See the immediate checkpoint in section 8 for the measured breakdown and next
proof. Reduce the dominant work before returning to source/path costs. Preserve negative observations, directory contexts, header shadowing,
aliases, tool/options identity and content changes with preserved timestamps.
Reprofile after each accepted change; these component budgets remain
allocations, not guaranteed savings.

The following checkpoints preserve the experiment history; the current Make
results and component evidence above supersede their earlier KPI snapshots.

The digest experiment processes the actual 197,096,694-byte emitted C payload.
Through both frontends, two Clang-built SHA passes take about **1.83 s** and
owned digest reuse about **0.92 s**; GCC takes about **2.68–2.74 s → 1.35–1.37 s**.
That established roughly **0.9 s of component savings under Clang**. The subsequent
alternating actual Make comparison now proves **0.694 s** saved on this local
workload, bringing self-host to **8.341 s**, with **6.341 s** left to remove. The production
composition has been implemented and rebuilt through two strict-C11 self-host
stages. Cache/publication coverage passes 182 cases across the main run and an
explicitly configured rerun of its one SDK skip. Broader final-tree qualification
remains open; the subsequent focused CLI/structure/frontend-I/O selection passes
156 tests with two platform skips, and GCC digest coverage passes 11 tests.
This local measurement does not prove required-host or p95 acceptance.

SDK validation now has an isolated feasibility result: replaying the actual
16 reader groups under production capture limits takes **1.937 s**; a compact
filesystem-witness verifier with cwd and opened-file checks takes **0.346 s**
to recheck the recorded operations and hash **24,768,454 bytes**. These are
separate component experiments, not an
integrated cache or a new Make KPI. The product remains **8.341 / 9.169 s**.
Fresh preprocessing alone takes **1.331 s** and is insufficient: equal hashes
can conceal changed ABI layout or declaration columns. Do not use that shortcut.

The next SDK implementation must bind semantic documents to the complete
request/tool/environment identity and validate consumed bytes, negative lookups
and path resolution. The revised diagnostic fixes cwd-sensitive deduplication,
records each handle's opening cwd/mode, checks metadata around its buffer read,
and preserves remapping behavior while disabling reuse for that unsupported
case. Ten contract probes, four real-filesystem fixtures and an ASan/UBSan run
over all 16 SDK groups pass. Byte-identical touches still conservatively miss.

**Share validation across requests in one compiler invocation.** The revised
verifier takes **0.870 s** as 16 processes under the current waves, rechecking
**70,575,443 bytes / 33,333 operations**, versus **24,768,454 bytes / 9,901
operations** in the shared validator. Compacting each group's JSON does not
close the gap (**0.880 s** in a follow-up series). Keep selection authority
and existing response limits per group; share filesystem validation only.
Resolve tool/runtime identity, volatile macros, unsupported VFS/module/PCH
behavior, private cache publication and concurrency before enabling reuse.
Then qualify both frontends and actual Make timing before counting any saving. See
[SDK validation feasibility](docs/design/compile-performance.md#sdk-validation-feasibility-2026-09-21).

Input-contract follow-up: an isolated reader now captures Clang's effective
invocation and its actual working directory before parsing, ordered selections,
and a canonical digest of the complete environment. Used date/time macros,
PCH, modules, plugins and virtual inputs reject reuse in the tested cases.
The macOS runtime prototype also identifies loaded libraries: immutable Nix
store and identified system shared-cache images qualify; mutable images do not.
The input/runtime probes preserve all 16 actual SDK responses, with stable
identities across repeats, and pass Apple ASan/UBSan qualification. Five groups
emit `#pragma once in main file` warnings and are excluded by the conservative
input predicate; implement faithful diagnostic retention/replay for them.
This is still **not cache admission**: finish the external-input/side-effect audit
(including serialized AST/module inputs and requested diagnostic/dependency
outputs), implement other required runtime providers, then compose private
storage and the shared validation session. The Make KPI is unchanged.

The diagnostic tee experiment preserves semantics and emitted stderr for all
five warning-producing groups, but its capture omits Clang's final warning
summary in every case. It is not sufficient for faithful replay. Capture the
complete bounded worker response in the session design; do not reconstruct the
missing summary or suppress warnings to make these groups eligible.

The next composition uses the expanded input guards and owned-buffer recorder:
23 real-reader cases cover additional serialized/module inputs, API notes,
external instrumentation/layout files and requested diagnostic/dependency/stats
outputs. Six requested files are recreated by fresh extraction. Shared
validation publishes successful observations only after a group passes and
restores cwd on both success and failure; ten isolation cases and all 16 fresh
SDK traces pass, including under ASan/UBSan. Recorded source buffers now own
the bytes later parsed, independent of mutable VFS storage. These are isolated
prerequisite implementations, not an enabled cache or a new build-time result.
They are now composed in an experimental native-reader session and private
cache. Its immutable Nix package gets **16/16 warm hits**, including all five
warning-producing groups, with exact stdout/stderr retention and one shared
package-resolution query. One warm lookup measures **0.766 s**; this is a
component diagnostic, not a new Make result or the proposed 0.4 s SDK budget.
Twenty-five cache contracts and five dependency/driver identity cases pass.
Concurrent publishers/readers and an interruption after temporary-file creation
retain valid prior entries. Receipt checksums, content-addressed response blobs,
ownership/no-follow checks and filesystem validation reject corrupted or stale
entries. See the [session/cache evidence](docs/design/compile-performance.md#native-sdk-session-and-persistent-cache-prototype-2026-09-21).

The provider and session protocol now live in `tools/NativeHeaderReader.cpp`.
Normal extraction creates no filesystem recorder, input/runtime digest owner or
macro observers; cache publication opts into those costs. The installed Nix
package preserves fresh stdout/stderr on all 16 recorded product groups and gets
16/16 warm hits. Tracked cache regressions cover stale content, negative header
lookups, corruption, warnings, unsupported inputs and concurrent publication.
The initial full reader/cache suite passes **200 tests**, including semantic
decoding through both compilers.

Both frontends now prepare one shared SDK session per compilation, consume
responses in binding order and recheck response sizes and SHA digests. Cache
misses use private worker stages with complete stdout/stderr capture and normal
cleanup; unsupported or unsafe storage uses fresh extraction. `--no-cache`
disables this path. Compact control replies preserve per-group capture limits,
and an immutable configured launcher must match the session's launcher identity.
The focused frontend run passes **47 tests**, including both compilers' actual
SDK cold/warm, preserved-timestamp invalidation and cache-disabled paths. The
updated self-host compiler reaches a two-stage byte-identical C fixed point and
builds under strict C11/O2. Six new cache/worker cases bring that suite to **30**. The broader
reader/cache, process lifecycle, frontend I/O and compiler structure run passes
**268 tests**, with one `/dev/full` case unavailable on macOS.

The integrated path now also passes real launch-failure, parent/child-death and
mid-payload publication tests. Bounded collection uses live leases and private
worker namespaces; it preserves active children, writers and caller-owned stages.
The final tool passes 215 reader/cache and 47 frontend tests plus the actual-Make
recheck above. Other runtime hosts, broader storage/eviction qualification and
full cold/miss distributions stay open. The proposed 0.4 s SDK allocation is not
met by the 1.365 s SDK phase.

Native dependency identity is now repaired for POSIX Clang. Physical-header
reports recover paths lost by Make escaping, while the Make rule retains
existence-only and other additional dependencies. Real DWARF-5 and native-builder
regressions prove correct hits and invalidation for colliding paths, tabs,
forced/system headers and preserved timestamps. The final decoder and physical
name reconciliation take **0.306 s versus 1.104 s** before parser optimization
across the 39 actual reference units, in five alternating isolated passes.
That baseline already includes the correctness repair; it is not the former
0.384 s Make-only parser and does not establish a product speedup. Other compiler
providers retain their existing dependency mechanism and remain subject to
required-host qualification.

Native validation now uses bounded spawned workers at the guarded CLI entry
point; embedded/custom-capability callers keep their existing execution model.
Actual native command medians are **2.249 / 3.380 s**, still far above the
**0.7 s** allocation. The profile finds **17/39 compiler-version subprocesses**
and **9,411/20,257 file hashes** per self-host/reference build. The process pool
reduces contention but does not remove that repeated work. Its higher sampled
memory is recorded above; adding workers is not the next optimization.

The repeated-version experiment is now deferred: five alternating native-only
pairs measure **2.117 → 2.107 s self-host / 3.148 → 2.967 s reference**. Even
this fixed-tool best case saves only 0.010/0.181 s, before adding general
identity admission. The prototype was not promoted.

An isolated native preprocessing-receipt prototype reuses the SDK filesystem
trace and verification owners. All **56 actual product units** reproduce the
real compiler's preprocessed bytes, dependency files, physical-header reports
and diagnostics. Fourteen final fixtures cover content/comment edits with
preserved timestamps, shadowing, negative lookups, removal, symlink retargeting,
physical-name collisions, diagnostic behavior and volatile-macro refusals.
No production source changed in this experiment.

Under a proven fixed working directory, identical observations can be stored
once: **52,817/115,143 observations become 9,763/9,851**, preserving every
distinct check. Validation still hashes **222/347 MB of current input bytes**.
Five alternating pairs using the platform SHA-256 provider instead of LLVM's
implementation measure **0.976 → 0.419 s self-host / 1.359 → 0.477 s reference**
for compact-witness validation. Including fresh driver expansion for every unit
at eight jobs measures **0.624 / 0.867 s** over five passes. These exclude
complete tool/runtime admission, object/executable checks and cache publication;
they are not actual native-build or Make timings. Existing link-receipt
validation alone is about 0.33/0.34 s, so the **0.7 s native allocation remains
unproven**. See the [receipt prototype evidence](docs/design/compile-performance.md#native-preprocessing-witness-prototype-2026-09-21).

**Production prerequisite completed:** the packaged reader now exposes a bounded
compiler-context protocol for its configured Nix Clang provider on macOS. It
binds the selected immutable drivers, environment and actual loaded Clang/LLVM
images to the helper runtime, using the existing private worker capture owner.
Unsupported drivers, mutable helpers, dynamic shell/loader settings and unsafe
storage refuse admission. **235 targeted tests pass** (20 context, 39 cache,
176 reader). At that prerequisite checkpoint, receipt consumption was not yet integrated
and there was no new actual-Make speedup claim. See the
[compiler-binding evidence](docs/design/compile-performance.md#native-compiler-runtime-binding-2026-09-21).

**Receipt-owner checkpoint, before consumer integration:** capture and reuse
were implemented in the existing reader/cache owners. Fresh capture and cache hits match ordinary preprocessing, dependency
files, physical-header reports and diagnostics for all **56 product units**.
The endpoint binds C and C++ compiler executables independently: the actual Nix
`clang++` binary differs from `clang`. Tests cover content/search invalidation,
corruption, diagnostics and cleanup after killing Clang during temporary-output
creation. The final package passes 28 new and 235 existing cases in separate
runs, with no skips. Native-plan did not yet consume these receipts. Single warm endpoint
observations are **1.892 / 3.166 s**, excluding fresh driver expansion, native
object/link work and Make; they are neither KPI results nor a speedup claim.
That endpoint still used LLVM SHA-256. See the
[receipt integration evidence](docs/design/compile-performance.md#native-preprocessing-receipt-owner-2026-09-21).

**Consumer integration is implemented and locally qualified; M6a remains open.**
NativePlanBuilder batches receipt lookups after fresh driver expansion, checks
the bound compiler, launcher and returned blobs, and includes invocation/context
and current source/header content in object keys. Missing receipts are captured
in bounded workers. Real compiles retain a fresh post-compile validation before
object publication; unsupported tools and invalid responses use ordinary
preprocessing. The reader now uses the measured platform SHA-256 provider on
macOS. Directory identity retains inode, ownership and permissions while child
lookups capture relevant changes; unrelated build outputs no longer invalidate
every receipt solely by changing directory size or modification time.

All **56 product units** match ordinary preprocessing and diagnostics on the
new helper, with **17/17 self-host and 39/39 reference** receipt hits on reuse.
Targeted coverage totals **487 distinct passing cases across split toolchain
runs**, with no skips counted as passes. The actual-Make comparison above shows
modest warm savings and lower sampled memory. Native-only empty-cache samples
expose a cost: **7.533 → 9.619 s self-host / 11.364 → 14.255 s reference**.
These are single observations; repeat and profile them before accepting the
tradeoff. Missing-object checks rebuild exactly one unit and preserve executable
bytes, keys and receipt hits.

**Cold-capture follow-up:** owned structured records now go directly to the
existing cache publisher. Profiling showed avoidable serialization/rereading;
runtime preparation was comparatively small. A reproduced publication race is
also repaired: identical blobs preserve their inode, so active readers are not
invalidated by another publisher. Corrupt blobs still receive checked repairs.
The final helper passes **288 targeted tests** and all **56 product parity
units**. Three alternating native-only pairs per frontend, against a baseline
with the same race repair, improve cold medians **9.779 → 9.134 s self-host /
14.087 → 13.681 s reference**; warm timings are essentially unchanged. All 24
cold/warm builds meet their expected operation counts, every receipt is usable,
and outputs/keys remain stable on reuse. No full-Make or memory gain is claimed
for this follow-up. See the
[owned-capture evidence](docs/design/compile-performance.md#owned-preprocessing-capture-and-stable-blobs-2026-09-21).

**Warm-trace follow-up:** the measured serialization cost is reduced by grouping
observations by CWD/operation/path and checking complete structured values.
All content, metadata, negative-lookup and runtime proofs remain in place; CWD
transitions are ordered and failed groups share nothing. The latest full-Make
and memory results appear in the KPI checkpoint above.

**Directive reuse implemented and measured; source resolution remains over budget.**
The preceding five warm diagnostic compiler runs measured a **0.829 s** graph: **444 directive
scans / 0.388 s**, including **0.290 s** in the lexer, and **1,307 source reads /
0.219 s**. Nested times overlap; these are not new Make KPIs. The reference
compiler already stores content/toolchain-keyed directive ranges and reparses
their source fragments. The self-host candidate adds a frontend-owned optional
cache capability with bounded atomic storage owned by the CLI. It binds source
bytes, compiler identity and grammar; it keeps resolved paths,
wildcard membership, target providers and package access fresh. Invalid ranges,
comment-context dependence and cache failures must fall back to a full scan;
malformed source must not become a cached empty success, and speculative
fragment parsing must not terminate compilation. The no-cache path is retained.

The typed cache exposed a self-host prerequisite: interface declarations did
not normalize nested class arguments as implementing methods do. The existing
generic normalization pass now covers interface return and parameter types;
a valid owned `Vector<Part>` interface regression failed before the repair.
The formatted compiler reaches a byte-stable self-host fixed point and passes
**375 focused checks**, with one macOS `/dev/full` skip. The structural audit now
resolves declared interface implementations rather than relying on globally
unique method names. Five paired actual Make runs measure **4.673 → 4.526 s**;
the unchanged reference control is **5.586 s**. Full cold/edit, release and host
gates are still separate from this focused warm-build qualification.

The old **0.388 s scanning cost** was an upper bound before lookup overhead.
The cached-path profile subsequently found **0.102 s** repeatedly serializing
the unchanged vocabulary. TokenVocabulary now owns a memo invalidated by every
keyword/operator/annotation mutation. Source identity, cache admission and
fresh file validation are unchanged. The actual-Make comparison above saves
**0.091 s**, with source-graph time now **0.643 s**. Private-cache opening cost
about **0.085 s** in the profile; defer more lifetime machinery while native
receipt preparation still costs **1.204 / 1.939 s**.

Do not move the duplicate-import guard before source validation: distinct
aliases must retain their own path bindings, and later reads must not bless a
changed original input. Required cold/edit workloads, host distributions and
full final-tree gates remain open. The next experiment profiles the existing
native receipt path before changing JSON, driver expansion, validation or blob
consumption. Runtime preparation alone has not justified a snapshot memo.
See the [source-resolution evidence](docs/design/compile-performance.md#source-resolution-costs-2026-09-21).

The preceding no-op experiment history is retained for provenance. Its old
2 s/3 s gates and next-action proposals are superseded by the September 22
user decision. Preserve correctness and the ≤5 s regression guard while
prioritizing cold and edit work. Required-host and full-tree gates still apply
to final qualification.

## 1. Handoff state (2026-09-20)

- Reviewed btrc tree: **4e5c98239868e805586524b4ee06424bf4556130**.
  The previous handoff reported gates green at **0823f8c1**:
  `make test` 8608 passed, `make bootstrap`,
  `make test-c11` on gcc and clang -O0..-O3, `make lint`, `make format-check`.
  BTRSmith's inspected remote `main` is **5549c261**, with units,
  object cache and `BUILD=dev` in
  `make/Config.mk`, `make/Toolchain.mk`, `tools/LinkPlanParity.btrc`, and
  its btrc flake input repinned to 0823f8c1 (`nix build .` of btrsmith
  passed against that pin, 502 s including the store btrcc build).
- The clean local BTRSmith checkout was fast-forwarded from **292deaff** to
  **5549c261** on September 21. Earlier diagnostic numbers still describe
  292deaff. M6a product integration now removes the make macros' destructive
  pre-compile deletion; failed-command regressions preserve both frontends'
  prior output generations. Actual-make timings are recorded above. Do not
  confuse the pinned compiler with the working-tree compiler under test.
- The initial review updated documents only. Implementation now includes native
  object-cache validation, adapter retention, timing-accounting repairs and
  verified reference-compiler artifact generations for non-SDK builds.
  M6a remains open: SDK dependency identity, self-host generation parity,
  transactional user outputs, link identity, product integration and no-op
  acceptance still need implementation/qualification. Preserve normal
  signing configuration; the full plan is not complete.
- Historical numbers (BTRSmith, x86_64 NixOS, quiet machine; exact host and
  repeated-run distribution still need recapture):

  | | wall | phases |
  | --- | --- | --- |
  | btrcc | **76 s** (was 542 s) | lex+parse 2.7, analyze 12 (generics 3.1, validate 4.8, close-generics 1.9, realtime 2.1), lower 28 (l-generic-classes 12.3, l-declarations 14.8), optimize 16.5 (o-setjmp 12.0, o-dce 2.8), emit 2.8 |
  | btrcpy | **259 s** (was 742 s) | analyze 16, lower 140, optimize 57, emit 7 |
  | clang + link, 15 units | **~8 s** (was 85 s) | |
  | `make btrsmith-native` cold / edit one module | 101 s / 98 s | edit recompiles 1 of 15 units |

### Code-review findings that determine the order

| Observed code | Consequence / recommendation |
| --- | --- |
| `tools/native_plan.py::_ObjectCache.key` hashes compiler path/version, flags and source bytes, but not included header contents. A temporary native-C probe changed only a header: the cache key stayed identical while freshly compiled objects differed. | Fix dependency validation before extending caching. This is a reproduced correctness gap, not a performance hypothesis. Existing `test_native_plan_builder.py` covers warm hits, flags and source edits, but needs header-edit coverage. |
| `application/compiler.py::Compiler.compile` still bypasses the reference output cache for native bindings. Verified generations now support non-SDK split/debug builds; profiling still runs the pipeline. | Removing `--no-cache` will not fix BTRSmith no-op builds. Finish native semantic dependency identity and self-host parity before enabling product artifact reuse. |
| `CEmitter._unit_starts` and `CEmitter.unitStarts` in the two backends pack source runs by generated line count; prologues still contain program-wide declarations. | The measured one-unit edit is one example, not a stability guarantee. Crossing a packing boundary or changing a shared declaration can invalidate many units. Use stable module identity and measured dependency closures. |
| `CompilationPipeline.compile_resolved` analyzes, lowers and optimizes before `StdlibArchiveAdapter.consume`. | The stdlib archive demonstrates publication and shared-runtime linkage, not front-end separate compilation. Reuse those mechanisms without assuming analysis is already modular. |
| `SourceDependencyGraph` stores import/include edges and visibility, not a ready-made topological module schedule. | Define compilation groups, include semantics and import-cycle behavior before summary scheduling. |
| `ast.asdl` already names fields per constructor; Python AST/IR are per-kind classes. Python IR `_TRAVERSAL_FIELDS` is derived from dataclass metadata. | M8 changes self-host representation and generator output. Do not create a second field schema or migrate Python to solve a self-host-only layout problem. |
| The ASDL generator also generates native ABI nodes through the shared node generator. | An AST representation change needs explicit scope for `NativeNode`, renderer completeness checks and bootstrap compatibility. |
| `SetjmpPointerFlowResult` copies/deduplicates vectors; existing alias snapshots share until mutation. | M7 should preserve snapshot isolation and first-record ordering while measuring whether interning beats copying. |
| ARC `retain_edge`, `replace_edge`, adoption and release maintain both target and owner state. | M9 needs a mixed arena/ARC edge contract; checking only the allocated object's header is insufficient design. |
| The original `tools/perf.py` timed one emitted C unit without linking, misattributed self-host stage slices to frontend time, and mislabeled Darwin RSS. `BtrccPhaseTimer.mark` resets its stopwatch after each mark. | The harness now groups sequential stage slices, normalizes RSS and runs complete strict native-plan builds for both frontends and dev/release. Per-unit scans/cache/compile, linking, raw logs and provenance are recorded. Actual product no-op/edit scenarios, aggregate RSS and final product qualification remain open. |
| BTRSmith remote `make/Config.mk` defaults to the reference frontend and release mode; its toolchain stamp records executable paths. | Always name frontend/mode. Include flags and compiler content identity in build state; changing `BUILD`, an override, or a binary in place must invalidate the right artifacts. |
| BTRSmith `make/Application.mk::application-frontend-check` generates C/link plans and runs plan parity; it does not build the application executables. | Run explicit native builds and product checks for each frontend/mode as well; plan parity alone cannot qualify the emitted units. |

### Numeric acceptance budgets

Primary workload: the pinned BTRSmith application, including its resolved
stdlib/native packages. Count and record files, bytes, classes, generic
instances and native bindings; the historical fixture was 361 product
files / 72k product lines plus 21 packages. Do not silently shrink it.

The main acceptance host is a recorded, quiet x86_64 NixOS machine with at
least 16 logical CPUs and 16 GiB RAM; fix native compilation at **8 jobs**
for comparisons. Record CPU model, physical/logical cores, RAM and toolchain.
Rebaseline there: the old notes alternately describe 16 and 32 cores.
Also run on Apple Silicon macOS with a fixed job count and publish a
separate table; do not present Linux measurements as Mac results.

All absolute times below are **median wall seconds**, from build-command
entry until the requested artifact exists. Incremental/no-op p95 budgets
are shown explicitly. Repeat cold scenarios 5 times, incremental/no-op
scenarios 20 times; report every sample, median, p95, maximum and failures.
Use nearest-rank p95; with five cold samples it is the maximum. A correctness
failure fails acceptance regardless of the timing distribution.

| BTRSmith scenario | Historical evidence | Next delivery: M6a + M7 | Separate compilation delivery: M11 | Final objective after measured M8–M10 work |
| --- | --- | --- | --- | --- |
| Self-host transpile, empty btrc artifact caches | 76 s | ≤55 s | ≤55 s | ≤10 s |
| Self-host cold dev build, executable included | 134.608 s fresh diagnostic; repeat for acceptance | ≤80 s | ≤80 s intermediate | ≥10×; ≤min(20 s, baseline / 10); working budget 13 s |
| Self-host cold release build | 101 s; recapture exact flags | ≤90 s | ≤90 s | ≤30 s |
| Self-host private body edit, dev executable | 98 s; original mode must be recaptured | ≤80 s | ≤10 s; p95 ≤15 s | ≤5 s; p95 ≤8 s |
| No-op dev build, either frontend | Current 4.180/4.732 s macOS medians | **≤5 s; closed by user** | Regression guard | Regression guard |
| Touch an input without changing bytes, either frontend | Correct invalidation/retention proven locally; fresh timing distribution pending | ≤5 s regression guard | Same | Same |
| Reference cold transpile | 259 s | ≤180 s | ≤180 s | ≤60 s |
| Reference cold dev build | Unmeasured | ≤210 s | ≤210 s | ≤75 s |
| Reference private body edit, dev executable | Unmeasured | ≤210 s | ≤15 s; p95 ≤20 s | ≤10 s; p95 ≤15 s |
| 10 distinct product test executables, self-host, common app cache primed | Unmeasured | Establish baseline | ≤60 s total | ≤30 s total |
| Same 10 executables, reference | Unmeasured | Establish baseline | ≤120 s total | ≤60 s total |
| Compiler process peak RSS, self-host / reference | 5.4 / 1.7 GB at M1–M3, not a new M7 measurement | No increase >5% from recaptured baseline | ≤3 / ≤2 GiB | ≤1.5 / ≤1.5 GiB |

These are delivery goals, not promises that a particular optimization yields
a fixed speedup. Report misses; revise budgets explicitly with evidence.
For the second host, the near-term regression limit is **5%** versus its own
baseline; the final developer-experience objectives are the same, with any
miss stated separately. Do not claim cross-platform acceptance before both
hosts have results.

Definitions and scope:

- **Cold project build:** delete only the benchmark's generated artifacts,
  summaries, object cache and output executable. Compiler binaries, Nix
  dependencies and fetched packages are already installed; OS page cache is
  uncontrolled and recorded. Time Nix provisioning/compiler bootstrap
  separately; the historical 502 s `nix build` is not a project-build target.
- **Body edit:** a real implementation change in a named product module
  (including the body of a public method), with unchanged exported facts,
  ABI, generic requests, ownership/effect
  summaries and source locations of unrelated modules. Use at least three
  fixtures: navigation/model, UI controller, and an audio-adjacent non-RT
  implementation. An invalid edit does not count as a fast rebuild.
- **Interface edit:** deliberately changes a public signature or layout.
  Require correct dependent rebuilding and wall time no worse than **110%**
  of a clean build of the changed tree. The 10-second budget does not apply
  when the change genuinely affects the whole application.
- **No-op:** no transpile, C compile or link invocation. A byte-identical
  touch likewise must not trigger those operations after dependency checking.
- **Warm test batch:** store the exact 10 entry points in the benchmark
  manifest; prime only their shared application dependencies, not the ten
  final binaries or entry-point objects. Record build and test execution
  separately. Additionally report the entire current product frontend suite;
  do not assume the historical 37 × 2 count is still current.
- **Memory:** report compiler peak RSS and sampled concurrent build-process
  RSS separately. Final aggregate build objective: **≤6 GiB** at 8 native
  jobs. `RUSAGE_CHILDREN` alone does not measure concurrent aggregate RSS.
- **Runtime guardrail:** existing native, ownership, realtime and product
  acceptance stays mandatory. Compare the same release runtime benchmarks;
  investigate any median slowdown >5% or executable-size increase >10%.
  Build-speed gains do not qualify physical audio or visual fidelity.

The self-compile and full corpus remain additional scaling workloads. Record
their baseline now; no median wall/RSS regression >5% is acceptable without
an explained tradeoff. Do not optimize only the BTRSmith fixture.

---

## 2. Ground rules and the commands

### Rules

- Both compilers change together: the reference compiler
  (`src/compiler/python`, "btrcpy") and the self-hosted one
  (`src/compiler/btrc`, "btrcc") land in the same commit, and BTRSmith's
  `application-frontend-check` (reference and self-hosted link plans
  equivalent) is part of the gate. That target does not build the binaries;
  native builds and execution through both frontends are separate required
  steps. Representation/performance changes need equivalent semantics, not
  artificial source symmetry where one compiler already has the right shape.
- "Byte-identical" means each compiler against **its own** output before the
  change. The two compilers do not emit identical C (957 of 960 corpus
  programs differ between them, by design); the bootstrap fixed point is
  btrcc against btrcc.
- Gates that never regress: `make test`, `make bootstrap`, `make test-c11`,
  `make lint`, `make format-check`, `make generated-check`, `make extension`,
  repository structure/hygiene checks and `git diff --check`; in `../btrsmith`,
  `application-frontend-check` and the library smoke on both frontends.
- Every milestone records its numbers in
  `docs/design/compile-performance.md` (the `BTRC_TIMING=1` phase line and
  wall time on BTRSmith) so the next milestone starts from measured, not
  remembered.
- No effort estimates. Order is by dependency and payoff only.
- The initial document review ran document checks and bounded reproductions.
  Every implementation milestone must run the
  full matrix on its final frozen source tree. Record skips, unavailable
  platforms/tools and observed-boundary coverage separately from passes.
- Never bypass signing to complete a checkpoint. Inspect `git status` and
  HEAD before editing or committing; this checkout is synchronized.

### Building the compilers

```sh
cd /path/to/btrc                 # use this checkout, not a remembered machine path
nix develop                     # dev shell: python, ruff, clang, gcc, pkg-config
make btrcc                      # bin/btrcc from dist/btrcc.c (btrcpy transpiles BtrccMain.btrc, cc -O2 compiles it; ~5 min)
export BTRC_HOME=$PWD/src       # both compilers find the stdlib here
python3 -m src.compiler.python.main --no-cache --strict-imports --target linux-x86_64 P.btrc -o P.c   # btrcpy
bin/btrcc --strict-imports --target linux-x86_64 P.btrc -o P.c                                          # btrcc
```

`make btrcc` runs `compiler-codegen-check` first (regenerate with
`make compiler-codegen-generate` after touching `src/runtime/c/*` or
`src/runtime/c/manifest.toml`; it rewrites
`src/compiler/python/runtime/generated.py` and
`src/compiler/btrc/generated/runtime/Catalog.btrc`, which are committed).

**Never run `make btrcc` while `make test` is running**: it replaces
`bin/btrcc` under the suite. **Never edit Python sources while `make test`
runs**: a mid-run import error produced 332 bogus failures once.
`make test` with `BTRC_TEST_BTRCC=$PWD/bin/btrcc` exported skips the
suite's own content-addressed btrcc build.

### Measuring

```sh
BTRC_TIMING=1 bin/btrcc ... 2>&1 >/dev/null | grep 'btrcc timing:'      # phase and sub-phase marks (a-*, l-*, o-*)
BTRC_TIMING=1 python3 -m src.compiler.python.main ... 2>&1 | grep 'btrcpy timing:'
python3 -m tools.perf ../btrsmith/src/BTRSmith.btrc --samples 5 --warm-native-runs 4 --json build/perf/btrsmith.json   # both frontends, dev/release, all units and link
nix develop ../btrsmith -c make NIX= perf-btrsmith                                    # same, from BTRSmith's dev shell (its packages)
```

BTRSmith needs its packages' headers: run btrcc/btrcpy on it inside
`nix develop /path/to/btrsmith` (which puts pkg-config paths and the
native header reader in the environment), or export that shell's
`PKG_CONFIG_PATH`. Phase marks are added with `BtrccPhaseTimer.mark("name")`
(`src/compiler/btrc/frontend/Timing.btrc`) and `self._timed(profile, "name", start)`
in `src/compiler/python/application/pipeline.py`.

gprof works on btrcc: `cc -std=c11 -O2 -pg -w dist/btrcc.c -o btrcc-pg -lm -lpthread`,
run it on BTRSmith, `gprof -b -p btrcc-pg gmon.out` (flat) and `-q` (graph).
Self time under `-pg` is dominated by the ARC runtime; read the **call
counts** and the call graph's inclusive column, not the self column. For
btrcpy use `python3 -m cProfile -o out.prof -m src.compiler.python.main ...`.

These `gprof` instructions describe the measured Linux toolchain; use an
available native profiler on macOS. Do not transfer instrumented absolute
times into acceptance tables. Capture uninstrumented wall time separately.

`tools/perf.py` now runs the production native-plan builder, including every
generated/native/adapter unit and the linker with strict warnings. It defaults
to the current host target and both frontends in dev (`--debug`, `-O0 -g`) and
release (`-O2`) modes. Each sample has fresh generated files and an empty object
cache. Native-header, package and OS caches are uncontrolled and reported as
such; this is not yet proof of every cold-project condition above.

Warm-native repeats reuse the emitted plan, validate the object cache and link
again. They **exclude retranspilation and are not product no-op measurements**.
Each report retains exact commands, per-unit scan/cache/compile/publication
durations, cache outcomes, unit counts, link time and source/tool provenance.
Per-unit sums overlap when jobs run concurrently. Before/after snapshots reject
observed source/tool changes; they do not prove absence of transient edits or
capture the complete external SDK dependency closure. Keep the tree frozen.

Darwin RSS is normalized to KiB; `RUSAGE_CHILDREN.ru_maxrss` is not simultaneous
aggregate build memory. Self-host sequential `a-*`, `l-*`, `o-*` marks join their
respective stage remainder exactly once, while raw marks and unattributed wall
time remain available. Still add analyzed/lowered-module counts, summary-merge
timing when that stage exists, aggregate memory measurement, and BTRSmith's real
make no-op/touch/edit scenarios before accepting the corresponding budgets.

Each report must contain both repository SHAs, compiler binary/source
fingerprints, lockfile hash, target/SDK, exact argv/environment inputs,
worker counts, hardware, cache state and input sizes. Count analyzed/lowered
modules, emitted/compiled/reused units, cache misses by reason and links.
Keep raw samples in `build/perf/`; commit a compact result table and workload
manifest, with durable CI/artifact references when available. A deleted
`/tmp` profile is not sufficient evidence for a completed milestone.

### Byte-identity gate

Emit the whole corpus with each compiler into a fresh directory, once
before and once after, and compare the complete inventories and bytes.
The gate must exit nonzero on any failed compile, missing/extra output or
changed output. Retain stderr; do not turn compiler failures into an `echo`
and then continue to a successful exit. Example for one compiler/capture:

```sh
python3 - <<'PY'
from pathlib import Path
import subprocess
from src.tests.corpus_files import language_test_files

output = Path('build/verification/perf-after-btrcc')
output.mkdir(parents=True, exist_ok=False)  # stale captures must not pass
for relative in language_test_files('src/tests'):
    source = Path('src/tests') / relative
    target = (output / relative).with_suffix('.c')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_suffix('.stderr').open('w') as errors:
        subprocess.run(['bin/btrcc', '--strict-imports', '--target',
                        'linux-x86_64', str(source), '-o', str(target)],
                       stderr=errors, check=True)
PY
```

Capture with a source-frozen before compiler and after compiler, separately
for btrcpy and btrcc; use the selected host target, not Linux on a Mac.
The comparison runner must check both file sets before comparing bytes.
Implement it in the existing verification tooling rather than relying on a
shell loop that silently ignores newly added outputs.

Three programs embed absolute include paths
(`basics/InteropCEnumBaseType`, `basics/InteropUnionBaseType`,
`imports/ImportCSourceFile`): compare them modulo the checkout path. For
BTRSmith, `cmp` the single-unit output (no `--emit-units`). Milestones
that intentionally change emitted shape (M4–M6, M11, any M8 change to the
compiler's own representation) require behavioral, ownership, strict-C11
and bootstrap gates. Keep byte identity for programs whose output should
be unchanged. A stable new bootstrap fixed point does not require the new
compiler to emit its own old implementation byte-for-byte.

### Frozen compiler boundaries

`src/tests/fixtures/compiler_boundaries/manifest.toml` freezes IR dumps,
generated C and the runtime catalog. After an intentional change:

1. `python3 -m tools.compiler_codegen.main boundary-capture` writes
   candidates to `build/verification/compiler-boundaries/candidate/records/<id>.bin`.
2. Inspect every differing record against the intended contract. For an
   intentional, explained portable change only, copy its candidate under
   `src/tests/fixtures/compiler_boundaries/artifacts/accepted/<id>.bin` and set
   `accepted_path`, `accepted_sha256`, `reason`, `regressions` on the
   record by editing the TOML (no tool does this). Do not accept every
   difference automatically. Observed capabilities (`*.behavior-gcc`,
   `*.behavior-clang`) require their compatible host/toolchain; skipped
   Linux observations do not authorize changing the macOS baselines.
3. `python3 -m tools.compiler_codegen.main boundary-check`.
4. A new runtime helper needs a new `helper.<name>` channel on
   `shared.runtime-metadata` and a record whose baseline file contains
   `null`; `src/tests/python/test_boundary_manifest.py` hardcodes the
   record count (309).

### BTRSmith

```sh
cd /path/to/btrsmith && nix develop              # initially uses the pinned compiler
make BTRC_FRONTEND=selfhost BUILD=dev btrsmith-native
make BTRC_FRONTEND=reference BUILD=dev btrsmith-native
make BTRC_FRONTEND=selfhost BUILD=release btrsmith-native
make BTRC_FRONTEND=reference BUILD=release btrsmith-native
make BTRC_FRONTEND=selfhost macos-btrsmith-library-smoke
make BTRC_FRONTEND=reference macos-btrsmith-library-smoke
make -f make/Product.mk application-frontend-check
```

Until M6a fixes mode identity, these commands must use separate disposable
build directories or force regeneration between modes; invoking them in
sequence alone does not prove that make rebuilt with new flags. The smoke
target also runs on Linux despite its name; satisfy its native dependencies.

To use a locally built compiler, pass absolute `BTRCC`/`BTRC` paths for the
self-host run. For the reference run use the checkout's wrapper or a wrapper
that sets its absolute `PYTHONPATH` and runs `src.compiler.python.main`.
Use the same checkout's native-plan tool and export `BTRC_HOME` to its `src`;
keep the product dev shell's SDK/pkg-config inputs. Verify the effective
commands and tool fingerprints in the report before timing. Knobs:
`BTRC_UNITS=` (one unit),
`BTRC_UNIT_LINES` (unit size, default 40000), `BTRC_OBJECT_CACHE=`
(disable), `BUILD=dev|release`.

---

## 3. What landed (M0–M6 and part of M7)

### M0 — Measurement harness (b27a1acb)

`tools/perf.py` (`make perf-btrsmith`, `make perf-self`), `BTRC_TIMING=1`
phase timing in both compilers with the same phase names, baseline tables
in the design doc. Test: `src/tests/python/test_perf_tool.py`.

### M1–M3 — Algorithmic cuts (154093de, b1c9816a, 4ae64cda)

- Subclass/ancestor index in `Analyzed`
  (`src/compiler/btrc/analyzer/Models.btrc`: `ancestorsOf`, `subclassesOf`,
  `refreshInheritanceIndex`); `CycleSemantics` iterates `subclassesOf`.
  Python mirror in `ir/lowering/ownership.py` (`_ancestors`, `_subclasses_of`).
- Environments shared instead of copied per expression
  (`ir/lowering/ownership/Operands.btrc` `variables()`/`typeArguments()`;
  `generics.py` `TypeSubstitution` caches decoded tables and hands out
  copies on read — a9b4d215).
- Native-declaration indexes, DCE membership sets, setjmp fixed point
  driven by "consulted" summaries (`ir/optimization/setjmp/Analysis.btrc`,
  `exceptions.py`), iterative IR walker in `ir/nodes.py`.
- The compiler `keep`s its analysis and IR graphs at exit
  (`pipeline/Pipeline.btrc`, `analyzer/Analyzer.btrc`): releasing them
  cost 200 s of ARC reverse-edge proofs.

### M4 — Translation units (62d69404, reworked in 598bc161)

`--emit-units PREFIX` in both compilers writes `PREFIX.unit-<k>.c`; the
link plan now uses schema 4 with ordered absolute `emitted-units` paths
(the builder also reads legacy schema-3 counts); `btrc-native-plan --jobs`
compiles units in parallel. Every unit carries the prologue, types,
helpers and prototypes; functions and globals lose `static`; the primary
unit defines globals and kernels, secondaries declare them. Runtime
file-scope state stays written as plain `static` in `src/runtime/c/*.c`
(the stdlib archive parses that text to derive its `extern` header); the
unit emitters reshape it per unit through
`src/compiler/python/backend/runtime_state.py` and
`src/compiler/btrc/ir/RuntimeState.btrc` (primary drops `static`, others
declare `extern`). Emitters: `c_emitter.py` `emit_units`/`_emit_unit`,
`ir/Emitter.btrc` `emitUnits`/`emitUnit`. Tests:
`src/tests/python/test_emitted_units.py`, `test_native_plan_builder.py`.

### M5 — Source mapping and dev builds (d7f24d73, f7000dcd)

btrcc `--debug` lowers `IRK_LINE_MARKER` statements
(`ir/lowering/Statements.btrc` `lowerStmtInto`) and the emitter stamps
`#line` before every content line of a function body
(`ir/Emitter.btrc` `emitLineDirective`, `fixGeneratedLineResets`);
`-o PATH` (options may follow the input); `btrc-native-plan --debug-info`;
BTRSmith `BUILD=dev`. Tests: `src/tests/btrc/test_cli_arguments.py`,
`test_emitted_units.py::test_debug_split_units_map_lines_and_run`.

### M6 — Incremental rebuilds (1d285e55)

Every lowered function records its `.btrc` module (`IRFunction.sourceFile`,
`IRFunctionDef.source_file`, stamped by
`LoweringContext.stampFunctionSources` per top-level declaration and per
generic instantiation, and by `TranslationUnit._stamping_sources`);
`--emit-units` packs consecutive same-module runs to the line target
(`Emitter.unitStarts`, `CEmitter._unit_starts`); the recorded edit changed
one unit. `btrc-native-plan --object-cache DIR` (`tools/native_plan.py`
`_ObjectCache`) keys objects on compiler identity, flags and source bytes.
Per-module parse caching was dropped for cause: the front end is 3 s of 76.

The one-unit result was observed for one NavigationHistory edit. Packing
thresholds, generated naming, shared declarations and debug source locations
can change other units. M6a below makes cache correctness/no-op behavior an
explicit milestone. Prologue trimming requires transitive typed dependencies
(types, initializers, helpers, callbacks and native declarations), not only
names found in function bodies; measure the gain instead of assuming clang
time halves.

### M7 — Profile-driven cuts (9f7d7328, 5d9562be; in progress)

Parallel lowering is off the table as the plan first stated it: every ARC
retain and release takes the global spinlock `__btrc_arc_lock_mutation`
(`src/runtime/c/cycles.c`), so threads inside btrcc would serialise on it,
and `Analyzed`'s lazily filled caches are not thread-safe. This is evidence
against immediate parallel lowering; it does not establish that arenas are
the only possible solution. Re-profile after allocation and incremental work.

Landed, all byte-identical: cleanup-adapter name index
(`ir/optimization/Cleanup.btrc`), `TypeIdentity.utf8Hex` through a
`StringBuilder` (`syntax/Identity.btrc`), memoised setjmp body scans
(`setjmp/Safety.btrc` `bodyContainsSetjmp`), copy-on-write alias states
and one shared empty origin set (`setjmp/Analysis.btrc` `shareSlot`,
`ownOrigins`, `noOrigins`), `CallableBoundaryContext.variables()` returns
the live table (`ir/lowering/Callables.btrc`). Sub-phase marks `l-*` and
`o-*` in `Lowerer.btrc`, `Optimizer.btrc`, `Pipeline.btrc`.

---

## 4. Open milestones

### M6a — Correct dependency caching and make no-op builds cheap

**September 22 scope decision:** unchanged latency is closed at ≤5 s. Remaining
correctness/host qualification stays recorded, but no longer blocks starting
the user-directed edit/cold acceleration campaign. Below is implementation history.

Self-host artifact checkpoint (2026-09-21): named-output invocations now resolve
source/package/native inputs afresh, then reuse a checksummed complete emitted
generation before lexing and analysis. Both cache hits and misses use the
existing output publication owner. The package resolver records the published
lock after validating/replacing derived lock state, so the first build is
immediately reusable. All **12 focused cache regressions** pass on a fresh
self-compiled strict C11/-O2 compiler, including actual native-header changes,
include shadowing, reader replacement and malformed generations; **23 structure
checks** and generated-source checks pass. Broader integration passes **361
checks / 5 platform skips**; the final formatted compiler passes **114 cache/CLI
checks**. A complete BTRSmith direct compiler/native diagnostic now proves
artifact and 17/17 native-object reuse at **13.687 s warm median** over five
repeats, still above the 2 s no-op budget. Product Make now invokes both owners
for input validation on every build, with reference artifact caching enabled;
22 process-boundary, four publication-preservation and six actual compiler/native
cases pass with each of system Make 3.81 and GNU Make 4.4.1. Complete product
Make warm medians are 12.855 s self-host / 10.892 s reference (five repeats each),
with complete compiler/object reuse and one link per build. This does not
close M6a: output write/link elision, cheaper lookups, concurrent configuration
binding, eviction, Windows storage and required-host KPI evidence remain open.

Measured native scheduling follow-up: emitted C, package sources and generated
adapters now share the existing bounded worker pool. Five alternating warm
native-only pairs retain identical object keys and complete reuse; median native
wall falls 3.090 → 2.567 s for self-host output and 5.102 → 4.613 s for reference
output. The 147 native-builder/performance-tool checks pass, as do the product Make
checks under both Make versions. Complete Make follow-up medians are 12.855 s
self-host / 10.892 s reference (five warm runs each); neither meets the 2 s goal.
Required-host acceptance remains open.

Output-retention follow-up: both generation owners now verify the complete
owned output set under the publication locks before skipping payload staging.
Source/path guards, recovery, ownership/layout, actual bytes and modes still
apply; missing, changed or unowned files take the existing publication path.
Warm and unchanged-touch tests preserve output and ownership-manifest inodes
and timestamps through both real compilers and both Make versions, including
`--no-cache` compiler invocations. The final tree passes 504 focused checks,
23 architecture checks, and 23 optimized publication scenarios per frontend
under each of GCC/Clang. Fresh actual Make timing passes the full-generation
byte and inode/mtime/mode checks: five warm samples per frontend have medians
12.915 s self-host / 10.608 s reference. Neither meets the 2 s goal; no retention
speedup is established. Link elision remains open.

SDK reader follow-up: one shared declaration index per translation unit replaces
repeated indexing for each selection. Five alternating component pairs reduce
the reader median 3.227 → 2.759 s (14.5%), with all 41 product selections retaining
identical decoded semantics. The final native reader/consumer suite passes
2,512 tests with zero skips on the packaged reader and fresh self-host compiler.
Actual Make cold/warm measurement now passes all 12 runs and input-stability
checks: warm medians are 11.887 s self-host / 9.695 s reference, with retained
outputs, complete cache hits, zero native recompiles and one link each. Single
cold samples are 131.744 / 346.838 s. The no-op KPI remains open; these sequential
whole-build results do not isolate the component's contribution. See the
[qualification evidence](docs/design/compile-performance.md#shared-native-declaration-index-2026-09-21).

Hashing follow-up: both call-boundary owners now avoid forcing volatile result
storage when no cleanup suffix follows, retaining typed values, managed cleanup
protection and setjmp planning. Isolated SHA-256 elapsed time falls 46.2% with
Clang / 36.5% with GCC across five alternating pairs. The fresh self-host passes
six smoke checks, 276 call/ownership/setjmp checks, 46 additional Clang checks
and both-frontends SHA vectors under GCC/Clang, with no skips. Its next
self-compilation emits byte-identical C. Actual Make timing passes all 12 builds
and source/tool-stability checks: warm medians are 10.377 / 9.649 s, with complete
cache hits, retained outputs, no native recompiles and one link each. Single
cold builds are 127.646 / 349.113 s. The 2 s no-op target remains unmet.
See the [bounded experiment and qualification](docs/design/compile-performance.md#boundary-result-volatility-experiment-2026-09-21).

Link-reuse prerequisite: the Darwin development executable's debug map referred
to deleted temporary objects (17 in self-host BTRSmith, 39 in reference output).
The native builder now retains immutable debug-object generations beside the
executable, independently of the optional object cache. Debug adapter sources
also survive uncached and fallback builds. All 165 focused native-builder,
performance-tool and debugger checks pass, including both frontends' split
source maps, corruption, cache deletion and concurrent builds. Both Make
versions pass the product checks. All 12 actual Make runs pass with stable
inputs, complete cache hits and retained generated/debug artifacts; five warm
samples per frontend measure 10.141 / 9.796 s medians. Real BTRSmith source
lookup succeeds in LLDB through both frontends. This repair is not link elision
or evidence that the no-op budget has been met. See the
[debug lifetime evidence](docs/design/compile-performance.md#native-debug-input-lifetime-2026-09-21).

Darwin executable-reuse follow-up: the native builder now validates the real
expanded link command, toolchain and loaded libraries, ordered objects,
selected libraries, missing search candidates, path bindings and executable
contents before retaining the output. A discovery link plus a verification
link qualifies a receipt; unchanged builds perform zero links. Unknown argument
languages/wrappers take ordinary linking. Output publication uses the existing
parent lock. All 185 focused tests and both product Make check sets pass.
All 12 actual Make builds retain expected compiler/native cache behavior, with
zero links on five warm repeats per frontend: 10.293 / 9.810 s medians.
Alternating native-only measurements show no elapsed-time gain; validation
costs about as much as the avoided link. The no-op KPI and other-host coverage
remain open. See the [receipt qualification](docs/design/compile-performance.md#darwin-executable-reuse-2026-09-21).

Implementation checkpoint (2026-09-20): compiler preprocessing/dependency
rescans, transitive/system-header content fingerprints, source-path and driver
identity, versioned object manifests/checksums, atomic cache publication and
post-compile validation are implemented in `tools/native_plan.py`. Executable
regressions reproduce the original stale-header/source-path behavior and cover
include shadowing, corruption and concurrent callers. This is a correctness
slice, not completed M6a: follow the remaining steps and full qualification
below. Measurement evidence belongs in `docs/design/compile-performance.md`.

The full native-plan measurement path now exposes real product work: a single
macOS diagnostic on local BTRSmith `292deaff` took **173.619 s** for self-host dev
and **5.204 s** for a native-only warm repeat. The repeat reused 15 emitted
objects but rebuilt 2 generated adapters from changing temporary source paths
and linked again. This does not satisfy the no-op goal or qualify current
remote product `5549c261`; it establishes adapter identity, scan cost and link
elision as concrete remaining work. See the evidence document for toolchain,
environment workaround, sample limits and complete stage/operation counts.

Follow-up implementation: `NativePlanBuilder` now atomically retains verified
adapter source generations beside the native output when object caching is
enabled. Real source paths and parent-relative includes remain observable and
validated. Both-frontends pugixml ownership and AppKit text/scroll fixtures pass
after warm object reuse. Missing, corrupt or inaccessible generations fall back
to private compilation; shared generations remain intact until build-directory
cleanup. This closes the observed adapter-path miss, while whole-compiler
artifact generations, cheaper validated lookups and link caching remain open.
On the same emitted BTRSmith plan, five warm native repeats now reuse **17/17
objects**, with **0 compiles**; median native-only time improved from **5.001 s
to 3.297 s**. Linking and validation still run, and retranspilation is excluded.
The product no-op budget therefore remains unachieved.

Reference artifact checkpoint: `CompilerCache` now publishes checksum-verified
generations containing the primary C, every secondary and the canonical link
plan, using the existing `ArtifactPublisher` transaction and recovery owner.
Debug source maps remain in the emitted C. Cache keys distinguish debug paths,
unit prefixes/packing, DCE, parse/source-map modes and source provenance; the
toolchain fingerprint also covers runtime source inputs. Resolver validation
still runs on every lookup. Partial, corrupt, linked or interrupted generations
are misses, and output files can be recreated from a valid generation.

Reference split/debug reuse now includes native SDK bindings when resolution
supplies a verified semantic identity. Each lookup reruns the actual native
reader and package resolution, hashing the validated response, complete binding
contracts, reader executable/arguments and environment. Missing or changing
reader identity bypasses reuse. Generated adapters are restored only after
canonical plan validation. Successful warnings and their source mapping are
stored in the checksummed generation and reproduced on a hit. Profiling,
freestanding and prebuilt-stdlib cases remain uncached.

The old C-text cache port is replaced, and old `.c` entries are ignored. A real
BTRSmith split/debug build exposed a 326,726,292-byte emitted generation above
the initial 256 MiB cache limit. The default aggregate bound is now 512 MiB,
with a real-file regression across the old boundary and smaller explicit
budgets still enforced. This fixes admission of that workload; it is not a
claim that cache capacity or compiler memory scaling is solved generally.
Self-host artifact reuse, cheaper validated resolution, atomic publication to
the requested output paths, cache eviction and product no-op qualification
remain open. The cache directory transaction does not make the CLI's individual
output writes transactional.

Actual SDK product reuse is now measured on local BTRSmith `292deaff`: the
unprofiled reference dev build took **394.519 s cold** (376.048 s compiler,
18.471 s native). Five complete warm repeats had a **23.912 s median**,
including **18.803 s compiler** and **5.040 s native** stage medians. Every warm
run hit the generation cache, reproduced artifacts and warnings, reused **39/39
objects**, performed **0 compiles** and still linked once. Inputs/tool identities
were stable. This is direct CLI/native-plan evidence, not real `make`, installed
product or remote-main qualification; the **≤2 s no-op** and cold reference
budgets remain unmet. The discarded profiled probes cannot establish reuse.

A separate instrumented resolution diagnostic points to native-reader process
work and import scanning, not key hashing, as the next lookup costs: **42
subprocess calls** and **444 source scans**; semantic-key construction was
0.750 s under cProfile. Preserve live resolution correctness while caching
validated per-file scans and reducing repeated SDK process work. See the
evidence document for the instrumented timings and their limits.

Reference directive-scan reuse is now implemented through the existing cache
owner and an explicit frontend port. Entries key complete normalized source
content and compiler/grammar identity, store checksummed line spans, and reparse
the actual directive fragments with the ordinary lexer/parser. Paths, package
visibility, glob membership, imported source contents and SDK bindings are
still resolved on each invocation. Corrupt/unavailable entries and fragments
requiring surrounding comment context fall back to full scanning; malformed
lexical input is never persisted as a successful empty scan. `--no-cache` and
`--profile` bypass this storage.

On BTRSmith's same 444-file graph, three alternating baseline/warm resolution
pairs preserve source/provenance/native identities. Median import discovery
fell **2.863 s → 0.587 s**, with **4,688,012 → 56,615 characters lexed**. Complete
resolution still includes fresh native-reader work; this measurement is not a
full build or a ≤2 s no-op result. Native SDK process/semantic resolution,
self-host reuse, link elision and transactional output remain open.

Full-build follow-up on that directive-cache tree: one cold build took
**394.575 s**; five warm compiler/native pairs had a **24.299 s median**
(18.650 s compiler and 5.568 s native stage medians). All five hit the compiler
cache, reproduced emitted artifacts and warnings, reused **39/39 objects**,
performed **0 compiles** and linked once. Inputs/tools remained unchanged.
The separate-run result does not establish a full-build speedup over 23.912 s;
only the avoided import-scan work is established. The ≤2 s goal remains open.

SDK batch-reader foundation: the current selected product plan has **41
bindings across 16 header/language/standard groups**, including **24 bindings
to the same AppKit wrapper**. The shared reader now supports `--batch=FILE`
or stdin with a versioned request/response envelope. One fresh Clang parse
serves independent selections; each result retains its own declarations,
layouts, receiver interfaces and errors. C++ owner selection in one request
cannot authorize another. Standalone extraction remains available, and both
compiler semantic decoders accept the inner documents.

An isolated diagnostic grouped the actual 41 product requests by **all identical
non-selection arguments**, not only their headers. Three alternating pairs
reduced median extraction **15.182 s → 3.442 s** with **41 → 16 processes**;
all 41 semantic documents matched standalone extraction on every run. Inputs
and tools were stable. This is a shared-reader result, not a full-build timing.

Both frontend native-import owners now use strict grouping and envelope
validation while retaining original binding order, ownership and diagnostics.
Reference cache identities use validated typed semantics so batch formatting
does not invalidate equivalent generations. Self-host batches preserve each
member's 8 MiB/60 s allowance and partition groups above 255 for the process
API's capture limit. The 9 MiB response regression exposed repeated whole-string
length scans in self-host validation; that scan now caches the length and checks
escape bytes without substring allocation. The final rebuild passes **38 batch
consumer/codec checks**, including the 9 MiB and 256-binding cases. Broader SDK,
C++ owner and AppKit checks pass after correcting an Apple test-helper toolchain
mismatch; detailed counts and scope are in the performance evidence document.

An integrated reference-resolution diagnostic on the same 444-file product
graph preserves source/native-plan/cache identities over three alternating
pairs: median resolution **16.548 s → 4.405 s**, with **41 → 16 reader processes**.
This includes real frontend import and semantic work, but excludes later
compiler/native-build stages; a self-host rebuild overlapped the measurement.
The complete direct compiler/native diagnostic now measures **353.565 s cold
reference** (334.533 s compiler + 19.032 s native) and a **10.404 s median** over
five warm pairs (5.331 s compiler and 5.080 s native stage medians), compared
with the earlier 24.299 s warm median. Every warm run hit the artifact cache,
reproduced emitted files/warnings, reused **39/39 objects**, performed **0
compiles** and linked once. The cold self-host build also succeeds: **137.455 s**
(123.826 s compiler + 13.629 s native), with 17 compiled units. Inputs and tools
remained stable. These are local-product diagnostic builds, not make/installed
product or remote-main qualification; cold timing differences across separate
runs cannot all be attributed to batching. The ≤2 s goal remains unmet.

Next, profile the remaining validated lookup costs before choosing another
optimization: an inspected warm native build spends 0.286 s linking out of
5.012 s internal build wall time. Dependency scanning and cache validation
dominate that stage; their per-unit times overlap and must not be added as
wall time. Preserve the header-shadowing and compiler-replacement invalidation
contracts while improving reuse. Never union binding permissions or reuse
headers by timestamp.

The native-only follow-up measured **20,296 digest reads**, **39 fresh
preprocessors** and **39 compiler-version probes** per warm build. An experiment
sharing read-only Nix store hashes cut reads to 2,924 but moved median native
wall only **5.140 s → 5.124 s**. It was removed; reducing an isolated operation
count did not produce a useful build improvement. Preserve this rejected
experiment in the performance record before choosing further lookup work.

The native transport audit also reproduced acceptance of a valid JSON prefix
followed by a raw NUL and trailing bytes in the self-host compiler, in both
standalone and batch mode. `ExecResult` now retains captured byte counts through
`ChildProcess` and `UnixShell`; the native process provider rejects a successful
selected stream whose string length omits captured bytes. This is separate from
the codec's escaped-NUL check. The rebuilt compiler passes **40 consumer cases**,
including standalone/batch rejection through both frontends. Seven self-host
process corpus cases, six real C++/AppKit cases and 62 structure/ABI/naming checks
also pass; the reference process/descriptor suite passes 31 cases. This is
targeted qualification, not the final repository or product matrix.

Recommendation: establish this before M11; it fixes an existing correctness
gap and preserves the current **≤5 s unchanged / byte-identical-touch**
regression budgets without requiring modular semantic analysis. The earlier
2 s / 3 s latency goals were retired by the user on September 22.

1. **Native cache correctness.** Extend `tools/native_plan.py` and
   `src/tests/python/test_native_plan_builder.py`. The object identity must
   cover the actual toolchain/target, compile flags, source identity where
   observable, and transitive inputs including generated/system headers.
   Use a compiler-supported dependency/preprocessing scan as the initial
   correctness oracle, with versioned manifests. Missing, changed or
   unreadable dependencies are misses. Test a header-only constant/layout
   edit with an executable that changes behavior, not only a hash assertion.
2. **Resolution changes.** Rehashing last build's depfile alone misses a new
   header earlier on an include search path. Model search roots, negative
   lookups and relevant environment, or rescan preprocessing. Immutable Nix
   store paths can support a cheaper identity; mutable SDK/include trees
   need validation. Measure scan cost against the no-op budget. Do not trade
   correctness for an incomplete cheap key.
3. **Whole-build artifact cache.** Persist the primary C, all secondaries,
   native adapter units, link plan, source maps and dependency identities
   as one verified generation. Reference split/debug generations and fresh SDK
   semantic identity are implemented, including warning/source-map preservation.
   Measure actual product reuse and resolution cost; retain fresh native/header
   validation while improving lookup. The self-host path needs equivalent
   inputs and behavior through the existing artifact owners.
4. **Separate compile and link identity.** Hash link inputs, actual native
   libraries/toolchain and ordered flags. A changed library may require
   relinking without transpiling; unchanged build inputs require neither.
   Include `BUILD`, frontend, target, optimization/debug flags, selected
   compiler fingerprint and unit layout in build state. Replacing a compiler
   in place must invalidate, and dev/release outputs must not be confused.
5. **Publication/failure semantics.** Stage a generation in a private
   directory and publish the manifest only after every file is complete.
   Cache publication must tolerate parallel callers and process interruption;
   do not delete the last good generation before compiling its replacement.
   Reference CLI output preflight now rejects aliases among primary/secondary
   C, the link plan and freestanding seam, and protects resolved sources,
   declared native inputs and package metadata (including hard-link aliases).
   Reference CLI publication now stages the primary C, every secondary and the
   link plan before replacing any of those outputs; the plan is published last.
   Injected primary/secondary staging failures previously left mixed output,
   and now preserve all prior files. Cross-directory staging, encoding and
   missing-parent failures are covered; the focused CLI/artifact suite passes
   122 cases with four Linux-only cases unavailable on the macOS runner.
   Stage-all alone did not make replacements transactional or close the
   filesystem race between validation and publication. The regular-file CLI
   transaction integration below now supplies recovery and rollback; the
   separately created freestanding seam remains open. Whole-generation publication also
   includes the product macros that currently remove secondary C first.
   The shared `ArtifactPublisher` recovery audit reproduced loss of the last
   good backup when a post-restore flush failed. Recovery now retains that
   restored artifact and its pending journal for retry. Regressions cover
   directories, payloads and validators, plus actual process exit during
   backup, replacement, validator publication, commit and cleanup. CLI
   transaction integration must reuse this owner. It now supports outputs in
   multiple directories with ordered directory locks, destination-local staging
   and backups, and participant recovery markers. Concurrent publishers with
   different coordinators serialize, and a writer touching only a participant
   directory rejects interrupted work until recovery finishes. Recovery now
   accepts an independently authorized prior inventory alongside the requested
   layout and holds the union of their directory locks throughout. Before any
   recovery mutation, all surviving journals must match one of those supplied
   layouts, including when an earlier retry had already started the new one.
   Variable-count tests cover 0/1/4 replacement units and changed directories.
   A 260-artifact regression also proves that
   journal validation grows with the caller's known inventory instead of imposing
   the former fixed 64 KiB read ceiling. CLI integration uses this shared
   foundation rather than inventing another journal.
   Explicit obsolete-file retirement is now part of the shared transaction:
   `PublishedArtifact(None, path, expected_digest=prior_sha256)` removes only an
   unchanged regular file. The digest must come from an owned prior generation,
   not a fresh hash of whatever happens to occupy the path. A modified file
   rejects publication; a file recreated after retirement is preserved as a
   recovery conflict. Omitted prior paths are never implicitly deleted. Removal
   uses the existing backup/commit/rollback path, with the anchor and final
   validator retained as replacements. Recovery schema 3 records explicit
   absence; existing write-only recovery schemas 1/2 remain supported.
   The reference artifact layer now has `CompilerGenerationPublisher`: a
   persistent prepared inventory plus a committed ownership record containing
   primary/secondary/link-plan/freestanding roles, SHA-256 hashes and modes.
   The committed record is the existing transaction's final validator, so
   rollback and commit also choose the matching ownership set. A retry recovers
   the recorded attempt before preparing another layout; it does not infer
   authority from arbitrary output journals. Retirement uses committed hashes.
   The state root must be private and durable, separate from evictable caches;
   missing or malformed recovery authority fails closed. A strict directory
   flush precedes publication. The reference CLI now composes this owner through
   an application port for regular primary/secondary/link-plan outputs, even
   with `--no-cache`. It freezes path resolution and captures source identities;
   guards run before recovery, before preparing the next intent and within the
   publication policy, covering old outputs selected for retirement as well as
   current outputs and separately reserved outputs such as an existing
   freestanding header. An ownership-role change cannot retire that header and
   silently convert create-if-absent to replacement. Symlink retargets and changed
   output-directory identities reject publication. A default private per-user state root is provisioned
   lazily, independently of the compile cache, with `BTRC_STATE_DIR` as an
   absolute override. Existing output symlinks and permissions remain supported.
   Freestanding headers still use separate create-if-absent publication, and
   requests containing devices retain their direct I/O path. Fully coordinated
   seam/device handling, final path-race closure, existing Windows ACL validation
   and native qualification, self-host parity and product
   integration remain open.
   The native-plan builder now participates in the directory-lock protocol:
   hold primary/plan locks to discover the inventory, release and reacquire the
   complete sorted directory set, and reread if a replacement moved secondary
   units. Generated primary/secondary/plan symlinks now participate through
   both requested and resolved parent directories. Re-resolve bindings after
   each lock-set expansion, with eight bounded attempts; preserve requested C
   filenames for relative includes. Package sources and SDK headers retain
   their no-follow validation. Keep locks through compilation, cache probes
   and linking. Pending journals reject the build before tools; recovery stays
   with the independently authorized generation owner. Read-side locking does not make
   self-host/direct writes transactional or freeze arbitrary native headers.
   The initial reader checkpoint records **97 native-builder**, **233 boundary** and
   **98 architecture/API passes**, with one native-Windows skip. The installed
   Nix adapter also builds/runs split C and rejects an interrupted generation;
   its isolated import path prevents checkout modules from shadowing the
   packaged reader. The subsequent generated-alias checkpoint passes **116
   native-builder cases**, within **337 passes / 4 Linux-only skips** across the
   native builder, emitted units, native packages, performance harness and
   self-host CLI. Both frontends emit aliased outputs that build/run and reuse
   cached objects; the rebuilt installed adapter passes the same alias/include
   smoke and interrupted-target rejection. See the performance roadmap for
   exact artifacts. These are consistency checks, not performance completion.
   Directory-sharing builds serialize while their inputs are in use; read-only
   generated-output distributions still need an explicit coordination policy.
   Shared-publication qualification passes 225 tests (including 58 durability
   cases) with one native-Windows stat-mode skip, plus 92 architecture checks;
   exact records are in the performance roadmap.
   The subsequent ownership implementation passes 245 integration tests
   (including 78 durability cases), the same visible Windows skip, and 92
   architecture checks. Subsequent reference CLI tests now cover actual compiler
   process crashes, a third unit-prefix layout, replacement rollback, shrinking
   to one output, current-input retirement/recovery conflicts and custom seams.
   Full cross-frontend publication parity and adoption by remaining direct
   consumers remain required.
   Final CLI integration qualification records 282 source/CLI/cache passes,
   235 emitted/native/build passes on a fresh self-host compiler, and 175
   architecture/artifact passes, with six visible platform-specific skips.
   Exact records and remaining release gates are in the performance roadmap;
   these checks do not establish a build-speed improvement.
   The next output-inventory repair makes both compilers emit schema-4 plans
   containing ordered absolute secondary paths. The reproduced separate-prefix
   build failure came from schema 3 deriving them from the primary C filename.
   The builder now consumes explicit paths and still reads legacy schema-3
   counts. Cache restoration validates the requested paths and order; debug
   resets name the actual secondary files. Resolve the destination directory
   without following the final output, preserving filename-prefix semantics
   and stable plans before/after files exist, including symlinked directories.
   Consumers must update their plan reader with the compiler. This inventory
   alone does not authenticate a complete generation or retire obsolete units;
   the reference CLI now adds ownership and retirement through the transaction
   owner described above. The following self-host checkpoints record that
   integration and its remaining qualification.
   Self-host preflight inventories successful source/metadata reads and declared
   native/package inputs before writing any primary, secondary or plan output.
   It preserves output symlinks and modes while rejecting input/output aliases,
   nonregular targets and publication-control names. Earlier staging and owner
   coordination checkpoints qualified **217 focused integration/corpus tests**
   plus **29 architecture/naming checks**; those checks alone did not provide
   recovery or committed ownership.

   The regular-file generation transaction is now implemented in the self-host
   CLI on POSIX. It uses the reference schema-1 ownership/intent records and
   schema-1/2/3 publication journals, with owner-first locking and the sorted
   union of interrupted/current output directories. Recovery reads only the
   independently authorized inventory, restores the old validator last, and
   removes the coordinator marker before participant markers. Ownership is
   reloaded after recovery before choosing retirements. Durable intent precedes
   public replacements; the new committed manifest is published last. All
   prepared bytes/modes and retirement digests are rechecked before journaling.
   A bounded read comparison avoids another whole-output buffer for payload
   validation. The private filesystem lease now supports durable, no-follow
   removal of retired authority, including retry after an uncertain flush.

   Qualification includes actual process death in either implementation,
   cross-frontend recovery, participant/coordinator crash boundaries, a changed
   layout, malformed journals, modified retirements, current-input conflicts,
   large inventories and failed flushing after restoration. Tests also cover
   corruption of staged bytes/modes and editing a retirement during preparation.
   Final evidence is recorded in the performance roadmap. Keep the full M6a
   gate open: source identity at read time and remaining path races need
   qualification, native Windows private state/locking is missing, and the
   installed product/full release matrix has not been established by these
   focused fixtures. Retirement hashing now uses incremental SHA-256 over one
   immutable snapshot in 64 KiB reads. Native writers built through both frontends have
   retired a **2 GiB + 65-byte** file with a Python-matched digest and about
   **3 MiB peak RSS** each. The old whole-file byte-buffer ceiling no longer applies
   to that path. The owner also revalidates newly resolved output destinations
   after lock contention, before persisting intent, preventing a rejected
   private-state redirection from poisoning the next build. The follow-up
   qualification and measurements are recorded in the performance roadmap.
   Earlier focused qualification on a fresh self-host compiler passes **192
   transaction/CLI/filesystem cases**, **116 native-builder cases**, **78
   reference publication regressions**, and **29 architecture/naming checks**,
   with no skips in those selections. Lint, formatting, generated sources and
   whitespace checks pass. The performance roadmap records exact XML artifacts
   and input/compiler hashes. These results qualify the tested transaction
   paths; they do not establish full M6a completion or a build-speed improvement.
   The subsequent lock-rebinding/streaming-digest checkpoint passes **222
   transaction/CLI/digest/filesystem cases**, **116 native-builder cases**, and
   **107 reference publication/architecture/naming checks** on fresh compiler
   `d6c34f6344fa2a7b2ca2d1921a980601`, with no skips. Both frontends' digest
   corpus also passes GCC/Clang at **-O0 through -O3** and address/undefined
   sanitizers. The performance roadmap distinguishes digest microbenchmarks
   from the still-required end-to-end BTRSmith integration proof: the 128 MiB
   text digest trial improves from **2.6454 s to 1.4203 s median** (five samples),
   with peak RSS reduced from **385.84 MiB to 129.67 MiB**. This qualifies the
   digest improvement, not the product's build-time acceptance budgets.
   The cleanup-error follow-up now propagates snapshot-close and lock-release
   failures, preserves the original failure alongside cleanup diagnostics, and
   stops recovery on journal I/O failure. Both authorized inventories determine
   journal read bounds. Fresh compiler `20e450e924c5a1169a4118d25f5a1554` passes
   **477 focused checks with no skips**; all 16 new scenarios also pass as
   strict C11/-O2 executables generated by both frontends and built by GCC/Clang.
   See the performance roadmap for artifacts and fault coverage. A cleanup
   error after commit may leave the complete new generation installed; it must
   still produce an unsuccessful command result.

   Read-time identity now travels with CLI root/import/relaxed-stdlib source
   text in the reference compiler and with reads made by the POSIX self-host
   `FeSourceFileReader`. Capture comes from the actual open stream, with checks
   after reading and inside publication guards after lock contention. Inputs
   renamed into an output cannot be replaced merely because a different file
   now occupies the original input name. Source reads still run to EOF, and
   copied metadata does not retain open descriptors throughout compilation.
   `Library.IO` owns the shared immutable `FileSnapshot`/`FileKind` values and
   the stream-inspection outcome; exact filesystem handles reuse those values.
   Explicit consumers import IO, preserving the closed root prelude and the
   existing filesystem snapshot constructor/cache-token format. Fresh compiler
   `a26a8832357525806c6d3a26fe0a341d` passes **742 focused checks / 6 platform
   skips**, plus **26 corpus** and **149 reference CLI/source/archive checks**.
   Reusable readers keep the original publication identity while allowing later
   repository snapshots; the reuse and optimized GCC/Clang fixture evidence is
   recorded in the performance roadmap. Reference package/SDK/binary-reader identity, remaining external
   path races, native Windows publication and product build budgets remain open.
6. **Integration proof.** Invoke BTRSmith's real make entry point twice,
   touch an input without changing bytes, edit a transitive native header,
   replace a compiler at the same path, and switch dev/release/frontend.
   Assert operation counts and behavior against clean builds. Keep the
   source resolver/dependency validation active even on a cache hit.

Use the existing native-plan tests, emitted-unit tests, artifact tests and
product make tests as homes for these regressions. Do not introduce a second
build engine just to bypass broad mtime dependencies. Scope invalidation to
the actual entry point's closure, including glob membership and packages.

### M7 (remainder) — finish the profile-driven cuts

Target: btrcc **≤55 s**, btrcpy **≤180 s** cold transpile on BTRSmith,
byte-identical for unchanged output contracts. Measure each step with
`BTRC_TIMING=1`, uninstrumented wall/RSS, and the complete corpus comparison.

The September 22 phase evidence changes the order *within M7*: attribute and
remove repeated emission work first (item 4), then setjmp origin-set churn,
generic substitution and the remaining declaration/analysis costs. This stays
inside the existing milestone. Use one bounded owner-attribution experiment
before the first emission change, not another open-ended profiling campaign. The
filename-reuse cut is now implemented and measured: emission falls from about
26.4 s to 10.0 s; cold/edit walls improve 13.7%/13.3% in two matched pairs.
The first item 1 cut now saves a further 4.6% cold / 5.4% edit in its matched
comparison, with compiler peak RSS about 8% lower. Continue with item 2 and the
remaining lowering costs; revisit origin representation only if residual
profiles justify it.

1. **Remove setjmp origin-set churn before choosing interning.** The bounded
   September 22 full-product counter run finds **31,734,770 origin vectors**,
   **20,591,611 expression visits**, and **16,354,702 null visits**. Its 711,530
   literal and 344,042 function-reference visits unnecessarily traverse fifteen
   absent children each: **15,833,580 avoidable null visits**. Copies are
   overwhelmingly empty or singleton (3,653,551 / 909,036 versus 157 larger).
   First short-circuit childless leaves and omit empty per-node origin facts in
   both compilers. Missing facts already mean empty; preserve independent
   mutable return values, accumulated nonempty facts and write-record ordering.
   This cut passes 137 focused tests and a byte-identical self-host bootstrap;
   two actual-Make pairs now save 4.6% cold / 5.4% edit. The post-change diagnostic reduces origin
   vectors **59.8%** (31.7 M → 12.8 M) and null visits **96.8%**, preserving
   nonempty-operation counts. The counter run proves output identity for all
   fifteen C units, but its instrumented wall time is not a build KPI.

   Re-measure residual allocation/time before selecting a new representation.
   If copying remains dominant, compare empty/singleton value representations
   with full per-function interning keyed by exact
   `storage.identity/depth/sourceExposed` triples. Prefer compact IDs or
   structural keys over joined strings. Interning and alias-slot ownership
   changes must earn their place with measured end-to-end improvement.
   Audit `src/compiler/python/ir/lowering/exceptions.py` separately: function
   effects use `frozenset`, while pointer origins and alias states are mutable
   sets. Do not infer immutability from the function-effect model. Preserve
   first-record order where output depends on it; canonical membership must
   not reorder emitted summaries. Test branch snapshot isolation, loops/fixed
   points, captures, unknown pointers and setjmp cleanup. Report allocation
   counts and bytes, peak lifetime, and unique sets/hits/misses if interning is
   tried. Gate: full matrix plus output identity and actual-build measurement.
2. **Generic instantiation allocation** (`l-generic-classes` 12 s).
   `SemanticTypeSystem.resolveGenericType` and
   `TypeShape.copyWithArguments` (`src/compiler/btrc/analyzer/Types.btrc`,
   `syntax/Types.btrc`) create ~1.6 M type nodes per compile;
   `SemanticTypeSystem.namedClass` another 1.15 M. Memoise substitution
   per (type identity, type-map identity) within one instantiation
   (`DeclarationLowerer.emitGenericInstance`, `ir/lowering/Declarations.btrc`),
   return the input when no parameter is reached (the M1 shape in
   `resolveTypedefType`), and audit `namedClass` callers for mutation
   before sharing its result. A mutable map's object identity alone is not a
   valid substitution-cache key: use an immutable substitution context or
   generation and include every semantic option. Bound cache lifetime to the
   instantiation/analysis session, not a global address-keyed cache.
3. **Declaration lowering** (`l-declarations` 15 s). Re-profile after 1–2.
   The September 21 interrupted reference cold profile additionally records
   944,478,612 iterations in `_binding_conflicts_with_type`'s generic-parameter
   scan (`src/compiler/python/ir/lowering/calls.py`). Audit declaration-table
   mutation and name-collision semantics before replacing repeated full scans
   with a compilation-scoped membership index. Preserve generic and hosted-type
   collisions and qualify emitted-name identity. This is an M7 lead from an
   incomplete instrumented run, not a new priority or a measured speedup.
   Inclusive-time candidates from the last graph:
   `CallTargetResolver.resolve` (300k calls, 4.7 s), `resolveField`
   (219k), `CallableValueSemantics.expressionAbi` (620k, 4.8 s),
   `CallableFlowState.applyEvaluation` (240k, 4.8 s),
   `CycleSemantics.reaches` (2.2k calls at 1.8 ms each — memoise per
   (type, target) or precompute reachability once per class graph).
4. **Repeated C emission and debug formatting**, added after the September 22
   actual-Make cold diagnostic: `emit` now costs **27.750 s** and the 15 C
   units total **182.535 MB**. These differ in host/mode/workload from the old
   2.8 s profile; do not attribute the difference to one regression without
   a controlled comparison. `CEmitter.emitUnits` renders each function to
   count its lines, discards that text, then renders it again. Each unit also
   renders all helpers, types, aliases and function prototypes. In debug mode,
   `emitLineDirective` repeatedly escapes the same filename character by
   character; `spliceLines` copies the entire line vector before joining it.
   Attribute these costs with bounded owner timers/counters, then remove the
   dominant repetition within the emitter's formatting responsibility.
   Compare a count-only traversal with reuse of bounded rendered fragments;
   retained text must earn its memory cost. Reuse escaped filenames by exact
   string value within an emission, never by an unsafe raw pointer key.
   Preserve exact split boundaries, linkage, directive filenames/line numbers,
   deterministic output and repeated calls on the same emitter. Do not omit
   debug information to meet a dev-build KPI. The cold sample also has **9.844 s**
   between total phase marks and complete compiler wall time. Attribute artifact
   serialization/publication and graph teardown separately before assigning that
   residual; do not label it all filesystem time. Dependency-selective headers
   and helper ownership belong to M11's typed unit planning, not C text scans.
5. Port each cut to btrcpy where the same shape exists; record the numbers.
   Do not assume matching source edits produce matching benefits: keep each
   frontend's algorithm idiomatic and profile its actual dominant costs.
   Persist rejected experiments and their evidence, as AGENTS.md already
   does for substring/TLS optimizations. Phase targets are diagnostic;
   end-to-end budgets decide whether the milestone is complete.

### M8a — Reduce node allocation before changing representation

Recommendation: do this bounded experiment before a full AST migration.
Target: **at least 50% fewer empty child-container allocations**, self-host
peak RSS **≤3 GiB**, and cold transpile **≤40 s** on the reference BTRSmith
workload. Count node objects, child containers, backing buffers and bytes
separately. Smaller nodes do not imply fewer logical AST nodes.

1. Instrument construction by node kind in a profiling build. Distinguish
   parse nodes from temporary type nodes and IR nodes; confirm what survives
   until process exit. Keep instrumentation out of acceptance timings.
2. Prototype lazy child containers for a frequently constructed kind, with
   explicit read versus mutation paths. A read may observe an immutable empty
   view; a write must allocate private storage. Never return a globally shared
   mutable `Vector` that callers can push into. Audit cloning and aliasing.
3. Keep `src/language/ast.asdl` authoritative. The generator already knows
   constructor fields. Generated output remains data/schema; behavior stays
   with an intentional handwritten owner. Python is already per-kind and
   should not acquire a redundant wrapper API.
4. Measure on BTRSmith, self-compile and small/large corpus programs. Keep the
   experiment only if memory or wall time improves without semantic drift.
   If nullable-container checks erase the gain, record it and stop; do not
   force the representation migration to justify the experiment.

### M8b — Per-kind self-hosted AST and IR, conditional

Target: self-host cold transpile **≤30 s**, compiler peak RSS **≤1.5 GiB**.
This is a larger architectural option if M8a leaves node layout dominant;
it is **not a prerequisite for the M11 prototype**.

- First prove a small heterogeneous node tree with kind-specific payloads,
  identity, traversal, mutation and safe access using current language
  facilities. The generator still says fat nodes avoid dispatch/downcast;
  verify today's support instead of assuming either the comment or a proposed
  base-class design is correct. Do not introduce unchecked casts.
- Generate storage/field metadata from ASDL. Preserve line/column, source
  provenance and identity used by analysis memoization. Decide how existing
  mutable analyzer annotations are represented without a universal property
  bag that recreates the fat node.
- Prove parser → analyzer → IR → emitter for a small vertical slice before
  migrating all kinds. Transitional accessors must have a removal endpoint;
  wrong-kind writes should fail, not disappear into an empty container.
- Cover the generator's native ABI consumer explicitly: preserve its old
  representation until deliberately migrated, or migrate and qualify it in
  the same change. Keep renderer/schema completeness checks and normative
  repository inventories current.
- AST first, IR second. The IR has its own typed model and runtime references;
  do not pretend AST ASDL describes IR. Reuse Python's dataclass traversal
  metadata and define a reviewed self-host IR traversal source of truth.
- Corpus output should remain identical where behavior/shape is unchanged.
  Rebuild every bootstrap stage after compiler representation changes; prove
  the new fixed point. Intentional fixture changes need individual reasons
  and regressions, not a blanket recapture.

### M11 — Separate compilation, with explicit dependency contracts

This is the main developer-loop delivery: **≤10 s self-host / ≤15 s
reference** for the body-edit scenario in section 1. Preserve release
whole-program compilation until separate mode is fully qualified. A cold
separate dev build must meet the table and be **≤110%** of the same tree's
whole-program dev build; adding caching must not make a cold build much worse.

#### M11a: prove the smallest complete module build

Build a repeatable fixture with a library module, two consumers, and two
entry points. It must contain a generic, an inherited managed type, a native
header dependency and a cross-module call with effects. Start with functions
and add those mechanisms before declaring the prototype representative.

Exercise the real compiler CLI, native compiler, cache and linker. Build
clean, edit, rebuild incrementally, then rebuild clean in a second output
directory. Compare diagnostics, runtime behavior and canonical semantic/link
artifacts; same-mode deterministic C should also match. Whole-program and
separate mode need behavioral/ABI equivalence, not identical C text.

#### Module artifacts and owners

A compilation group is a source module plus package context and any
inseparable textual includes. Preserve current import visibility. If accepted
imports form cycles, compute strongly connected groups and analyze the group
together; if a cycle is invalid today, preserve the diagnostic. Do not invent
an import order or silently turn textual inclusion into module import.

Store artifacts under `build/` or the configured cache, never next to source:

| Artifact | Contract | Existing owner to extend |
| --- | --- | --- |
| Module interface summary | Versioned deterministic declarations, resolved types/layouts, hierarchy, ABI, native/call/ownership/realtime contracts; no process addresses | Frontend and analyzer models, persisted through artifact owners |
| Generic implementation payload | Typed, canonical template AST or portable IR plus defining scope and provenance; versioned separately from public interface | Generic analyzer/specializer and AST codec |
| Local analysis result | Body facts and consulted external fact identities; diagnostic/source-map provenance | Analyzer result model |
| Program facts | Reachability, runtime type/cycle facts, dispatch sets, generic demand and helper/native requirements | Optimizer/ownership/realtime owners |
| Lowered module | Structured IR, definition ownership and transitive declaration/helper dependencies | IR lowering and optimizer |
| Native artifact set | C units, required headers/adapters, link plan, dependency manifest and content hashes published together | Artifact publication and native-plan builder |

Use one versioned schema understood by both frontends, with round-trip and
parity tests; internal representations may differ. Follow the existing
archive/publication owners instead of adding a second cache framework.
The current stdlib archive is a linkage/publication precedent only: its
consumer runs after whole-program lowering and optimization.

#### Distinguish rebuild keys from exported semantic hashes

The artifact key includes compiler/schema/runtime identity, source and include
content, target/ABI/SDK, package/lock context, native bindings, options and
consulted dependency facts. The **public semantic hash excludes irrelevant
private body bytes**. Changing a private implementation must not automatically
change every importer's public hash. Diagnostics and debug locations still
need correct independent provenance.

A cached lowering records the specific program facts it read. A new subclass
may alter cycle handling or dispatch in an unchanged module; rerun the global
summary fixed point and invalidate those consumers. A conservative whole-
program invalidation is acceptable during the prototype, but must be visible
in counters and cannot pass the localized-edit acceptance budget.

| Change | Required invalidation / proof |
| --- | --- |
| Private body, unchanged exported effects/ABI/generic demand | Its group, its unit and final link; unrelated analyzed/lowered groups stay cached |
| Body changes release/capture/realtime effects | Recompute summaries to a fixed point; revisit affected callers even when signatures match |
| Public layout, signature, default argument or exported constant | All consumers of the changed fact, transitively where their own summaries change |
| Add/remove subclass or interface implementation | Recompute dispatch/cycle facts; invalidate lowering and validation that consulted them |
| Generic body or demanded type arguments change | Rebuild affected instantiations and their definition units; update transitive demand |
| Native header, binding contract, SDK, compiler flags or package lock changes | Invalidate dependent semantic and/or native artifacts, including transitive headers |
| Add/delete/rename source, change glob membership or include search resolution | Re-resolve the graph; remove stale definitions/units from the link manifest |
| Change frontend, target, mode, compiler binary or runtime | Select a different validated artifact identity; never reuse by path alone |

Do not hash the entire changing program summary into every unit as the final
solution: that is correct but destroys incremental behavior. Conservative
facts may over-approximate safely in dev mode; explain the resulting runtime
cost and preserve all ownership and realtime rejection rules.

#### Generics and program facts

Recommend **definition-owned specialization units**, deterministically keyed
by package/module/symbol identity, normalized type arguments, compiler target
and generic payload hash. Consumers request instances from the defining
owner; that owner reads its implementation payload and emits each definition
once. Fixed-point demand discovery handles generics that request other
instances. Start with one stable specialization unit per defining module;
split further only if rebuilding it prevents the acceptance target.

Interface summaries alone cannot instantiate an arbitrary generic body.
Never reopen and reanalyze all imported sources under the name of summary
loading. Persist a checked implementation payload or explicitly schedule the
defining module. Include private dependencies, recursive instances, imported
methods, visibility and source diagnostics in the fixture.

Do not use weak-linkage extensions for duplicate definitions: generated C
must remain strict C11. Keep temporary names, generated symbols and ownership
stable across entry points and rebuild order. A specialization shared by two
executables has one object implementation per cache identity and one linked
definition in each executable.

Whole-program merging consumes sufficient per-symbol dependency/effect facts,
not signatures alone. Preserve address-taken callbacks, indirect dispatch,
global initialization, native adapters, GPU kernels and runtime helper roots.
Unsafe/unknown effects must remain conservative, never become empty summaries.
Realtime and call-effect recursion requires a fixed point over the call graph.

#### Stable emission and build integration

- Emit stable module/group units plus deterministic specialization, runtime
  and necessary registration units. Separate unrelated declarations into
  headers by actual dependency closure; one all-program header causes every
  object to miss when any layout changes. Keep one definition of shared
  runtime state across C/Objective-C/C++ adapters.
- Lowering/optimizer plan typed unit dependencies. Emitters render them;
  do not move semantic dependency discovery into C text scans or the emitter.
  Handle complete-type ordering, forward declarations, initializer edges,
  helper dependencies, native declarations and callback tables.
- A driver orchestrates existing frontend/analyzer/lowering/artifact owners;
  it does not implement a second semantic pipeline. Proposed CLI:
  `btrcc --module PATH --summary-dir DIR` with equivalent reference support,
  and a build entry point beside `tools/native_plan.py`. Final API follows
  the vertical-slice proof, not the provisional flag spelling.
- BTRSmith mode/frontend/target outputs must be distinguishable. Build
  identity includes the actual selected compiler and all flags, not just
  `command -v` output. Preserve generated files' mtimes when bytes are equal;
  validate content regardless of source mtimes. Publish a complete generation
  atomically and retain the previous usable generation on failure.
- Record cache-hit reasons and counts. For the fixed body-edit fixtures,
  require exactly one changed source group analyzed/lowered, no unchanged
  group re-lowered, and only dependency-justified native compiles plus one
  link. Shared specialization/registration changes count and must be explained.

#### Cold-build scheduling and work reduction

M11 must address cold work as well as edit reuse. The September 22 cold
diagnostic spends 124.340 of 134.608 s in btrcc. Even eliminating the entire
9.304 s native stage would improve that build only about 1.07×; object-cache
work alone cannot establish the requested 10×. Even deleting all measured emission
and setjmp time would leave about **90.9 s** end to end. The remaining compiler
work, allocation and module-level critical path must also change; no single
local cut is being presented as the 10× solution.

- First measure source-group SCC sizes, work per group and the longest
  dependency chain. An effectively whole-program SCC limits parallelism;
  report it instead of assuming eight independent compiler jobs exist.
- After summaries and specialization ownership are proven, schedule ready
  groups with bounded workers. Share immutable facts or load bounded artifacts;
  do not clone the full mutable program per worker. Global effect/generic
  fixed points and deterministic definition ownership remain explicit barriers.
- Budget compiler and native workers together against the **≤6 GiB aggregate**
  ceiling. Measure one versus bounded workers on the same empty-cache tree;
  count repeated parsing, analysis, generic work and bytes read/written.
  Summed CPU time is not critical-path wall time. Avoid oversubscription and
  retain the existing sequential memory-intensive bootstrap gate.
- Reduce emitted dependency closure and shared runtime duplication through
  structured IR planning. Measure native preprocessing/compile/link wall after
  smaller units; moving all declarations into one shared header alone does not
  reduce each compiler's parsing work or prevent broad invalidation.
- Keep compiler/SDK/object/output caches empty for the cold comparison, with
  installed toolchains/packages reported explicitly. Prebuilt application or
  stdlib artifacts are a different scenario, never a hidden cold-build win.

Initial end-to-end design envelopes are **≤7 s compiler + ≤5 s native + ≤1 s
outer driver** for cold dev builds, and **≤4.5 s compiler + ≤4.5 s native +
≤1 s outer driver** for edits. These are proposed budgets, not a demonstrated
speedup or predicted allocation. Replace them with measured allocations as
M7/M8a/M11 land; keep the end-to-end 10× requirement. If remaining serial work
exceeds the envelope, identify its owner and require new evidence before the
conditional M8b/M9/M10 experiments. Caching cannot close a cold serial floor.

#### Acceptance before enabling BTRSmith dev mode

Run the invalidation table through both compilers. Include clean/warm cache,
corrupt/missing artifacts, interrupted publication, concurrent builds to the
same cache, changed include search order, new shadowing headers, and rebuilds
in different directories. Cache misses can rebuild; cache corruption must
never silently produce a successful stale binary.

Verify cross-module ARC destruction/cycles, exceptions and cleanup, generic
identity, function pointers/interfaces, native callbacks, globals and debug
source locations through the real native executable. Run sanitizer ownership
cases as well as stdout goldens. Exercise dev → release → dev without manual
cleaning. Preserve release bootstrap and add a separate-mode self-compile
check before declaring the new compiler build mode broadly supported.

Only then run the complete BTRSmith frontend/native suite in both modes and
measure every scenario in section 1. A fast library fixture alone does not
complete M11.

### M9 — Arena allocation, only after ownership and allocation evidence

A possible route toward the **≤10 s final self-host transpile** objective;
not a commitment to add a general language feature for a compiler benchmark.
Re-profile after M7/M8/M11. If allocation/ARC remains dominant, first compare
bounded graph-lifetime storage with an arena prototype and record total
allocated/retained bytes, ARC operations and lock time.

Before implementing, specify:

1. **Scope/lifetime:** process-lifetime arenas initially never free storage.
   Do not call them reclaimable regions. A public region-lifetime feature
   requires a separate escape/lifetime design. The CLI can tolerate retained
   graphs; repeated use of the `Compiler` API must have an explicit policy and
   a many-compilations RSS test, not accidental unbounded growth.
2. **Mixed edges:** define ordinary→ordinary, ordinary→arena, arena→ordinary
   and arena→arena behavior for construction, assignment, replacement,
   adoption and destruction. Arena→ordinary values need real ownership;
   process lifetime alone does not retain their targets. State how reverse
   reachability, witnesses and cycle collection treat mixed graphs.
3. **Storage propagation:** decide separately how node payloads, vector/map
   containers, backing buffers, strings and temporary analysis data allocate.
   An arena node containing ordinary containers still pays ordinary ARC.
   Measure which allocations become arena-owned; emitter strings can stay ARC.
4. **Observable behavior:** constructors, destructors, native resource
   owners, weak/non-owning views, exceptions and allocation failure retain
   defined behavior. Restrict unsupported arena payloads explicitly; don't
   silently suppress a destructor that closes a native resource.
5. **Concurrency:** lifetime does not imply immutability or thread safety.
   Define arena allocation ownership and publication before M10. Cover
   `replace_edge`, adoption, cleanup and collector paths, not only retain/
   release fast paths.

Use existing analyzer/ownership/runtime owners and shared grammar/ASDL if
syntax is needed. No generated-C patching or alternate compiler ownership
system. Run mixed-edge stress, ASan/UBSan, failure-path and repeated-compilation
tests, then the full matrix. Track lock time directly: disappearing from the
top twenty profile entries alone is not an acceptance criterion.

### M10 — Parallel analysis and lowering, conditional on measured scaling

Final objectives remain those in section 1. **3–5 s cold transpile is a
stretch target**, not a result implied by having 16 cores. Record serial
fraction after prior milestones before predicting parallel speedup.

1. Inventory writes reachable from each proposed work item: analyzer caches,
   generic registries, runtime/helper selection, native adapters, diagnostic
   storage, generated symbol counters and ownership state. Freeze shared
   tables after their fixed point; make remaining writes local or merge them
   deterministically. A shallow `freeze()` on `Analyzed` is insufficient.
2. Begin with already-independent per-function setjmp work. Move body lowering
   and validation only after demonstrating their dependencies. Per-worker
   contexts own temporary names and allocation; stable declaration identities
   determine ordering, names and diagnostics. Cross-function fixed points stay
   explicit. `BTRC_JOBS=1` is the same scheduler with one worker.
3. Measure **1, 2, 4 and 8 workers** at fixed native jobs, including peak RSS.
   Require **≥1.5×** wall speedup at four workers on the qualifying cold
   BTRSmith compile to justify enabling the pool by default, with aggregate
   memory inside budget. Record actual hot-lock wait/hold counts and time.
4. Compare output/diagnostics at every worker count and across at least ten
   repeated shuffled schedules. Use TSan where the runtime/toolchain supports
   it, plus stress fixtures; report unavailable coverage. ASan/UBSan and the
   full normal matrix remain required.
5. For Python, benchmark process workers on coarse independent modules only
   after M11. Include serialization, process startup and duplicated RSS in
   wall/memory results; do not mirror a thread implementation mechanically.

Stop adding parallel machinery if separate compilation already meets the
interactive goals and a measured cold-build benefit does not justify it.

---

## 5. C compatibility proposals (separate scope)

### Why, and how much

btrc does not need C source inside `.btrc` files to use C: `#include "x.h"`
pulls native declarations through the header reader, a `.c` file compiles
and links through the package link plan (`src/tests/imports/ImportCSourceFile.btrc`),
and every Linux provider (SDL, ALSA, FreeType, WebGPU) is imported that way.
So the gaps below never block building software. They matter for two
reasons: the README's "C, but better" reads as "C is a subset", and the
first C habits a newcomer types (`int main(void)`, a braceless `if`,
`int a, b;`) fail today; and C programmers write btrc with the same habits.
The goal of this track is therefore **ordinary C11 parses as btrc, and the
things btrc refuses are refused on purpose and documented**, not "rename
`.c` to `.btrc` and it compiles".

### Compatibility inventory: reported probe, not yet a reproducible gate

The earlier handoff reported 100 one-construct programs on 2026-09-20,
but did not commit the battery. Treat the table as hypotheses except where
existing regressions verify the behavior. Start C5 by preserving the actual
programs, compiler revision, diagnostics and native results.

Reported method: one tiny C11 program per construct, compiled with
`python3 -m src.compiler.python.main --no-cache --strict-imports --target linux-x86_64 P.btrc -o P.c`,
then `cc -std=c11 P.c && ./a.out`; a construct "passes" when the binary
exits 0. Replace that weak oracle with explicit semantic assertions, strict
C11 builds and both frontends. Include negative cases and interactions, not
only one syntax example per row. Do not recreate supposed historical evidence
from a table and label it as the original measurement.

Reported successes to reproduce: pointers, pointer-to-pointer, pointer arithmetic (`p = p + 2`),
arrays and decay, casts including `void*`, `static` functions and locals,
`extern`, globals with initialisers, enums with values, function-like
macros, `_Generic`, `do`/`while`, `switch` with fallthrough, nested struct
initialisers, literal suffixes (`LL`, `UL`, `f`), hex, octal, escapes,
`volatile`, `printf`, prototypes with named parameters,
`int main(int argc, char** argv)`, assignment in a condition, `if (i)` on an int.

| # | Construct | Symptom today | Class |
| --- | --- | --- | --- |
| 1 | `int f(void)`; unnamed prototype parameters `int f(int);` | "Expected parameter name" | parser gap |
| 2 | braceless bodies after `if`/`else`/`for`/`while` | "Expected LBRACE" | parser gap |
| 3 | multiple declarators `int a = 1, b = 2;`, `int x, y;` in structs | "Expected SEMICOLON, got COMMA" | parser gap |
| 4 | `char s[] = "abc"`, `char s[4] = "abc"` | "requires an array initializer" | parser gap |
| 5 | adjacent string literals `"a" "b"` | parse error | lexer gap |
| 6 | empty statement `;` (`for (...);`) | "Expected LBRACE" | parser gap |
| 7 | function-pointer declarators `int (*f)(int)`, `typedef int (*Op)(int,int)`, arrays of them, as parameters | parse error; btrc spells these `CFunction<...>` | parser gap (sugar) |
| 8 | `typedef struct { } T;`, `typedef struct P { } P;`, anonymous struct/union members | "Expected struct name" / "Expected typedef alias" | parser gap |
| 9 | `union U { };` as a declaration | only `union IDENT` as an interop base type (grammar line 30) | parser gap with an ownership rule |
| 10 | designated initialisers `{.b = 2}`, `{[2] = 7}`; compound literals `(struct S){5}` | "Unexpected token" | parser + IR gap |
| 11 | `goto` / labels | no syntax by design (grammar line 27) | parser + lowering rule |
| 12 | bitfields `unsigned a:3` | "Expected SEMICOLON, got COLON" | struct model gap |
| 13 | flexible array member `int d[];` | rejected | struct model gap |
| 14 | variadic definitions `int f(int n, ...)`, `va_list` | "Expected parameter name, got DOT" | parser + intrinsics |
| 15 | `inline`, `restrict`, `register`, `auto`, `_Noreturn`, `_Thread_local`, `_Alignas`, `_Static_assert` | "Expected name" | keyword pass-through |
| 16 | `long double` literal `1.5L`, `wchar_t`, `L'x'` | "Invalid numeric literal" / parse error | lexer + type gap |
| 17 | multi-dimensional arrays `int m[2][3]` | explicit diagnostic: needs an AST/IR representation per dimension | known gap |
| 18 | `#if`/`#else`/`#ifndef`/`#if 0` | directives pass through; the analyzer sees every branch ("Duplicate definition", "unsupported directive") | preprocessor gap |
| 19 | comma operator `(1, 2)` | parsed as a tuple literal | **conflict**: tuples |
| 20 | identifiers named `in`, `string`, `keep`, `self`, `class`, `interface`, `spawn`, `new`, `var`, `null`, `true`, `false` | keywords | **conflict**: reserved words |
| 21 | `strlen(s) == 2` (`size_t` vs `int`) | "mixes ABI-dependent integer type" | **on purpose**: strict integer mixing |
| 22 | `_Bool b = 1`; `return a();` in a void function | type errors | **on purpose** |
| 23 | VLAs `int v[n]` | already supported in checked contexts; initializers and some views have restrictions | **preserve existing behavior**; audit exact supported forms |
| 24 | `_Atomic`, `_Complex` | rejected | **deferred**: need type-system entries |

### C1 — The ergonomic set (rows 1–7)

Recommended ergonomic additions after the inventory is reproducible. Each
needs grammar, analyzer/lowering and diagnostic coverage as appropriate;
parser convenience does not make its semantic cost zero.

1. `(void)` as an empty parameter list; unnamed parameters in prototypes
   and in function-pointer types.
2. A single statement as the body of `if`, `else`, `for`, `while`; lower
   with braces. `;` as an empty statement.
3. Multiple declarators per declaration, locals and struct fields,
   preserving each declarator's pointer/array shape and initializer. Test
   `int *p, value;`, declaration order, scope and side effects. Choose a
   faithful AST form; semantic lowering stays in IR generation.
4. String literal as the initialiser of a `char` array, sized or not;
   enforce inferred/fixed extent and terminator rules in the appropriate
   semantic owner. Adjacent literal concatenation must agree with macro
   expansion, prefixes and source diagnostics, not merely join token text.
5. C function-pointer declarator syntax parsed into the existing
   `CFunction` type (the parser maps this public spelling to `__fn_ptr`),
   including `typedef` and arrays of pointers. Add the declarator grammar
   explicitly; there is no existing `function_pointer` grammar rule to reuse.

Files: `src/language/grammar.ebnf` (the spec; change it first),
`src/compiler/python/parser/parser.py`, `src/compiler/btrc/parser/Parser.btrc`,
`src/compiler/python/lexer/`, `src/compiler/btrc/lexer/`. Any new AST node
goes through `src/language/ast.asdl` and `make compiler-codegen-generate`.

### C2 — Declarations (rows 8–10, 12–13, 17)

1. Anonymous struct and union members; `typedef struct { } T` and
   `typedef struct P { } P` (synthesize the tag; both analyzers key structs
   by name).
2. `union` declarations for plain C members. Rule: a union member may not
   be ARC-managed (class, `string`, collection) — the runtime cannot know
   which member is live; the analyzer rejects it with a diagnostic, in
   both compilers.
3. Designated initialisers and compound literals: represent field/index
   designators with checked types, storage lifetime and managed
   ownership. IR already has initializer-list/compound-literal forms; extend
   those owners instead of assuming a new raw-C escape is needed.
4. Bitfields: represent field width in ASDL and the analyzer's storage/type
   model, then structured IR. Specify legal access, layout and address-taking
   restrictions. Keep existing native-binding restrictions until separately
   qualified; source syntax support does not establish native ABI support.
5. Flexible array members: specify layout, allocation extent, indexing and
   which copy forms btrc permits before implementation. Test actual target
   layout against the native compiler; do not hide a semantic rule in emission.
6. Multi-dimensional arrays (row 17): define each dimension in AST/type/IR,
   array-to-pointer conversions, indexing, `sizeof` and parameter forms.
   Preserve supported one-dimensional VLAs; this row was previously omitted
   from the implementation sequence.

### C3 — Control flow and calls (rows 11, 14–16)

1. `goto` and labels. btrc scopes carry ARC releases and cleanup slots, so
   the lowering must reject a jump that enters a scope past an owned
   variable's initialiser or leaves an unsupported `try` frame. Same-scope
   jumps can also skip initialization or repeat it: analyze forward and
   backward edges, definite assignment, VLA lifetime and cleanup state.
   Use an explicit control-flow contract in both analyzers/lowerers; emit
   releases only after that proof. First add negative fixtures for the
   unsafe paths, then positive cases for the supported subset.
2. Variadic definitions: `...` as the last parameter, `va_list`,
   `va_start`, `va_arg`, `va_end` as opaque intrinsics in
   `src/language/intrinsic_effects.toml`; realtime analysis treats them
   as non-allocating only after their ABI, promotions, argument ownership,
   `va_copy`/cleanup and escape behavior have explicit checked contracts.
3. Declaration semantics for `inline`, `restrict`, `register`, `auto`,
   `_Noreturn`, `_Thread_local`, `_Alignas`, `_Static_assert`: give each a
   grammar/type/flow/storage rule as applicable. These are not interchangeable
   keyword pass-through attributes. Specify static assertions, alignment,
   aliasing, TLS initialization/cleanup and nonreturning control flow; prove
   linkage across split units. Do not delegate semantic checks to emitted C.
4. `long double` literals with `L`, `wchar_t` and `L'x'`/`L"x"` literals.

### C4 — Preprocessor conditionals (row 18)

Directives are passed through to C today, so the analyzer sees every
branch. Evaluate `#if`/`#ifdef`/`#ifndef`/`#elif`/`#else`/`#endif` in the
front end over a source-ordered macro environment plus the target's
predefined macros (`__linux__`, `__APPLE__`, `__x86_64__`, from
`src/language/hosted_abi.toml`'s target table), drop the dead branches
before parsing, and keep emitting the live branch's directives so the C
compiler agrees. `#if` on a macro the front end cannot evaluate (a system
header's) stays an error with a diagnostic naming the macro. This is a
documented restricted subset, not a complete C preprocessor. Define
`#undef`, nesting, undefined identifiers, include order, macro expansion and
source maps. Discarded branches must not introduce imports/native bindings
into the dependency graph. Front-end and C-compiler configurations must
agree; do not leave directives that can select a different live branch.
Fingerprint all preprocessing inputs in M6a/M11 artifacts.

### C5 — Spec, corpus and the documented refusals (rows 19–24)

1. Preserve the probe as tests in existing topic suites, or add a cohesive
   C-compatibility corpus if it improves discovery. Cover every row,
   each printing `PASS: <construct>` with a golden
   (`src/tests/generate_expected.py`), run through both compilers by the
   existing runner. Use diagnostics tests only for actual refusals; row 23
   needs positive VLA regressions and negative unsupported contexts. Existing
   `test_gpu_boundary.py::test_gpu_vla_capacity_does_not_replay_the_declared_bound`
   already verifies single evaluation through both frontends, and
   `test_aggregate_evaluation_order_parity.py` verifies VLA initializer rejection.
2. A section in `src/language/grammar.ebnf`'s preamble and in
   `docs/known-language-gaps.md`: "C that btrc rejects on purpose" —
   the comma operator outside `for` headers (tuple literals win; support
   it only in `for` init/update), the reserved-word list, strict integer
   mixing, int-to-bool assignment and returning a void expression, after
   confirming each policy. Document supported VLA forms and their restrictions
   separately. Distinguish deferred C `_Atomic`/`_Complex` syntax from existing
   btrc atomic primitives; do not add tests rejecting working language features.
3. README wording: "C's syntax and semantics where they are safe, the rest
   reachable through `#include`", linking to that section.

### Order and gates

C5 inventory/regressions → C1 → C4 → C2 → C3, with C5 docs/tests
updated at each step. Select additions by demonstrated consumer need; a
README slogan is not by itself a reason to add `goto` or variadic definitions.
The track shares AST/schema owners with M8: land overlapping C-track parser
work either before M8b starts or after it lands, never interleaved. Every
step: both compilers in one commit, `make test`, `make bootstrap`,
`make test-c11`, and the boundary fixtures for `surface.python.tokens`/
`surface.python.ast` reviewed for intentional changes (section 2).

---

## 6. Existing-feature parity: iOS, Android and Windows

Goal: build and ship existing BTRC functionality and BTRSmith workflows on
all three platform families, preserving both compilers, strict C11, native
ownership and the existing macOS/Linux contracts. Treat the gaps as explicit
implementation milestones; a hello-world app or a successfully linked binary
does not complete a platform.

The code audit, API inventory scope, native-provider recommendations, dependency
contracts, physical-device gates and primary platform references are in
[the detailed platform-parity roadmap](docs/design/platform-parity.md). That
file is part of this plan; it holds the implementation detail so the performance
milestones remain readable. All platform milestones below are **proposed/open**.

### Scope and current gaps

- **Target support:** both target parsers admit only Linux/macOS/Windows;
  native extraction is limited to macOS/Linux GNU triples, and native plans
  lack full mobile SDK/environment/deployment/artifact identity. Add iOS
  device/simulator and Android explicitly, not as aliases for desktop targets.
- **Windows:** keep the existing x64 compiler bundle, native CI, portable
  runtime subset and GPU Windows branches. Finish native SDK scanning,
  Unicode/process/terminal/network/Regex/filesystem gaps, native providers,
  ARM64 qualification and the installed product.
- **iOS/iPadOS:** add UIKit application/scene lifecycle, checked Objective-C
  providers, scoped document storage, a real iOS audio session/I/O backend,
  mobile GPU surfaces, signed apps and physical iPhone/iPad verification.
- **Android:** add NDK target/build support, a checked JNI and Activity boundary,
  platform GUI/storage/permission behavior, audio/GPU providers and validated
  APK/AAB packaging, including every native library's 16 KiB compatibility.
- **Full parity:** inventory every public stdlib operation and existing product
  journey. Report equivalent, adapted, OS-restricted and missing counts
  separately. Mobile document access or background execution can require a
  different interaction; feasible missing features remain open work.

Proposed initial matrix: Windows 11 x64 then native ARM64; iOS/iPadOS 17+
arm64 devices plus supported simulator slices; Android API 29+ arm64 devices
and x86_64 emulator. P0 validates the floors and pins exact SDK/OS/toolchain
versions. Desktop compilers generate mobile apps; running a compiler on a phone
is not a prerequisite. Windows compiler-host parity includes native bootstrap.

### Milestones and exit evidence

| Milestone | Deliverable | Required exit evidence |
| --- | --- | --- |
| P0 — Inventory and support matrix | Every existing public API and product journey mapped per platform; exact host/target/SDK/device matrix | 100% classified, stable denominator, tests/owners identified; no silent exclusions |
| P1 — Target/ABI/build artifacts | Shared target contracts; native SDK extraction; executable/static/shared outputs; correct target-specific cache identities | Both frontends run ABI/callback fixtures in minimal apps on Windows, iOS device/simulator and Android device/emulator |
| P2 — Hosted runtime/language | ARC/cycles, exceptions, TLS, threads/atomics, pure stdlib and target test hosts | 100% applicable portable corpus through both frontends; ownership/cleanup stress and available sanitizers |
| P3 — OS library contracts | Real filesystem, Unicode, process/terminal, HTTP/sockets, Regex, jobs/IPC providers and mobile capability adaptations | Negative/failure tests and actual operations; no curl-shell assumption or unsafe path fallback |
| P4 — Native package closure | Cross-built database/archive/media/font/image/GPU dependencies and generated bindings | Existing package contracts pass on each required ABI; formats/codecs remain in the inventory |
| W1 — Windows development host | Real SDK-reader process provider, Win32/COM contracts, Unicode tooling, relocatable compiler | Native self-host fixed point, SDK imports/callbacks and corpus; installed compiler works outside the checkout |
| W2 — Windows product | Native GUI/input/tray, WASAPI audio, GPU/image/font providers and installer | Complete BTRSmith journeys on native x64 and ARM64; install/update and physical audio/GPU qualification |
| I1 — iOS shell and providers | UIKit lifecycle/GUI, scoped document import and durable state | Both-frontends signed app runs Library/Settings/import/restoration on a physical device |
| I2 — iOS complete product | Audio session/I/O, Metal-backed GPU path, assets, signing/distribution archive | BTRSmith on iPhone and iPad; interruptions, route changes, suspension, physical audio and package validation |
| A1 — Android shell and providers | Checked JNI, Activity/GUI/input, content-URI storage and permission lifecycle | Both-frontends APK on emulator and physical device; Activity recreation/process-death recovery |
| A2 — Android complete product | AAudio/qualified audio backend, GPU, native libraries and APK/AAB distribution | Two physical vendors, 4/16 KiB qualification, actual audio/GPU, lifecycle and package validation |
| P5 — Product journey parity | Library/import/search/settings/playback/practice/rendering/input/persistence and supported automation | 100% inventoried journeys passed or explicit OS restriction with reviewed replacement; zero missing core journeys |
| P6 — Numeric acceptance | End-to-end builds, responsiveness, audio latency, memory and lifecycle budgets | Repeated measurements on named hosts/devices, with raw results and failures |
| P7 — Release qualification | CI matrix, source-level diagnostics/debugging, signed artifacts, upgrade tests and coverage report | Same revision and package set passes every required gate; unavailable device evidence stays unfinished |

Detailed substeps and dependency boundaries live in the roadmap. Carry its
implementation owners through both compilers and the existing provider system;
do not introduce per-product native wrappers or a second ownership model.

### Numeric goals for BTRSmith on the new targets

These are final self-host build goals after M6a/M11, not measured current
support. Cold means dependencies/toolchains already installed and project
artifacts cold. Times include native compile/link and development packaging/
signing, with local credentials ready. Record provisioning separately.

| Build scenario | Windows | iOS/iPadOS | Android |
| --- | --- | --- | --- |
| Cold dev package, one architecture | ≤30 s | ≤45 s | ≤60 s |
| Private body edit to installable artifact, median / p95 | ≤10 / 15 s | ≤15 / 20 s | ≤20 / 30 s |
| No-op through the real build driver | ≤5 s | ≤5 s | ≤5 s |
| Incremental install/relaunch on ready local target | ≤5 s | ≤15 s | ≤15 s |
| Cold reference-frontend dev package | ≤90 s | ≤120 s | ≤150 s |

Use the same 10,000-song/1,000-album fixture (or a larger existing acceptance
fixture) across platforms. Proposed runtime goals: interactive cold Library
p95 ≤3 s desktop / ≤4 s mobile, search/filter p95 ≤100 ms, 60 Hz frame-time
p95 ≤16.7 ms, zero app-induced audio xruns in a controlled 30-minute soak,
100 lifecycle/route-change cycles without leaked native owners, and settled
memory growth ≤5% after warmup. The roadmap defines device classes, memory
budgets, p99 callback deadlines and physical wired audio-latency gates.
Existing stricter product budgets take precedence.

Cross-builds, emulators and simulators prove different properties from native
hardware. Windows x64/ARM64, iPhone/iPad, and two Android vendors need actual
execution before final parity. OS limitations must remain explicit, and missing
implementations must not be renamed limitations to make the table green.

---

## 7. Native UI across macOS, Linux, Windows, iOS and Android

Goal: a complete native application UI with platform controls, native editing,
focus, accessibility and OS integration, composed with custom GPU musical
views. The [native UI inventory and roadmap](docs/design/native-ui-parity.md)
is part of this plan. It records **60 capability families**, concrete source
evidence, provider recommendations, behavioral contracts and qualification
criteria. All UI milestones are **proposed/open**.

Start review with the roadmap's [decision checkpoint](docs/design/native-ui-parity.md#review-checkpoint):
it separates the first editor/focus slice, provider feasibility, collection
reuse, product migration and completion criteria. Review the native-shell
proof before expanding a new provider, then the shared event/focus contract
before migrating every screen.

The source inventory also maps **19 public interface files, 24 interfaces and
135 directly declared methods**, plus **27 GUI factory/service methods**, to
specific missing contracts. These are source counts, not coverage percentages.
The [individual API checklist](docs/design/native-ui-api-inventory.md) lists
all **162 current interface/facade declarations** with stable operation IDs,
source links, inheritance and starting milestone/case mappings. UI0 must record
**1,620 operation mapping slots** (162 × 5 platforms × 2 frontends), checking
inherited behavior at concrete controls and linking actual assertions. These
overlap the behavioral cases below; they are not an extra test-pass count.
Other exported types/modules and product callers remain to be inventoried.
Nine explicit contract increments cover events, focus, dispatch, scenes,
layout, collections, async services, accessibility and GPU presentation.
The detailed roadmap adds five ordered BTRSmith migration slices and native
binding/OS-update gates so the capability list leads to reviewable changes.
It also separates platform readiness from shared API gaps and defines **47
initial operation-level acceptance cases**, with concrete owners and expected
results for editor events, selection, dispatch, focus, commands, restoration,
resource pickers, accessibility and GPU composition. Design-resource work
includes semantic appearance roles, localized/pluralized text and packaged
assets alongside native theme and text-size changes.

The follow-up source audit adds keyboard-only controls, native undo, large-text
adaptation, independent windows/scenes, external open requests, mobile keyboard
and Back behavior, secure input, live theme/locale changes, accessible virtual
collections, drag/drop cancellation, nested presentation and queue pressure.
Track **470 case-result slots** (47 cases × 5 providers × 2 frontends), then
expand by OS/device configuration; this is planned coverage, not a pass count.
The detailed document maps these cases to existing owners and UI milestones.

The family matrix now also has a numerical source baseline: macOS has **33
partial / 27 missing** families; Linux has **15 partial / 15 custom / 30 missing**;
Windows, iOS/iPadOS and Android each have **60 missing GUI integration families**.
**27 families are missing everywhere.** These counts describe available source
foundations, not implementation effort or passed behavior.

E46/E47 expand lifecycle coverage: dirty-window/Back dismissal during asynchronous
save, and versioned scene restoration after actual process death. The macOS
close delegate currently always permits close; Linux closes on the recorded
request, and the shared interfaces have no portable decision hook. UI1/UI3/UI5/UI7
must add an owned Save/Discard/Cancel transaction, with **100 cycles per applicable
entry path and zero lost drafts or duplicate saves**. UI1/UI5/UI10 must qualify
**100 fresh-process restores**, schema upgrades, corrupt checkpoints, missing
resources and concurrent activation, with **zero replayed side effects or
cross-scene swaps**. Use a proposed **64 KiB scene-metadata fixture budget** and
keep durable document data separate; **20 launch samples** must meet the existing
**p95 ≤3 s desktop / ≤4 s mobile** Library goal. Details and native platform
references are in the roadmap's [dismissal and restoration contracts](docs/design/native-ui-parity.md#dismissal-transactions-and-durable-scene-restoration).

The source inventory also adds E25–E32: full shortcut/key identity, constrained
measurement and RTL alignment, coordinate/anchor conversion, accessible
operations and text limits, failed tree updates, suspension/deadline semantics,
final-release ownership and comparable input-to-presentation timing. These
extend the 60 families rather than inflating the toolkit count. In particular,
the present keyboard enum has only 24 named non-unknown values, view fitting
methods accept no size constraint, and semantic text values have a 512-byte
limit. UI3/UI5/UI8 must resolve those contracts before wider provider rollout.

E33–E34 add large/dynamic selectors and changing numeric ranges. The Linux
selector has no keyboard opening path and consumes wheel events without popup
scrolling; its popup paints all options. Both slider providers fix the range at
construction and cap discrete intervals at 1,000. Qualify **0/1/100/10,000-option**
selectors, disabled/loading/unselected states, and **999/1,000/1,001-step** range
updates without replacing focused owners. Keep exact 64-bit product timeline
values separate from native floating-point presentation, including tests around
**2^53**, and retain the 100-cycle cancellation/refresh gate. These are core
UI2–UI4/UI7/UI8 work within the existing families.

E35–E37 add image lifetime, bounded artwork resources and text shaping. The
image providers differ in whether a view still paints after a published handle
is explicitly closed; establish a shared retained-presentation contract and
test **100 shared-handle/replace/close cycles**. Linux artwork eviction currently
depends on rendered frames and has no aggregate byte budget. Qualify catalog
artwork at **≤128 MiB desktop / ≤64 MiB mobile**, including decoded/native/GPU
and in-flight allocations, with **≤2 concurrent decode/conversion jobs** and
eligible cache release **within 1 s of explicit trim without repainting**.
These limits sit inside the existing product memory budgets. Linux measurement,
paint and system-text raster paths also operate on individual scalars rather
than shaped runs; UI5/UI9 need native layout, fallback fonts, cluster mapping
and matching ink bounds, including Arabic/Indic/bidi/emoji fixtures. Widget
migration alone does not repair the custom GPU text path. These findings are
source observations and proposed gates, not reproduced live failures.

E38 adds a capture contract needed for trustworthy visual regression evidence.
macOS captures the requested subtree and validates supplied GPU layers; Linux
captures the owning window, ignores the layers and can wait up to **5 s** for
GPU readiness on the UI thread. UI9/UI10 must align subtree scope, backing scale,
frame identity, layer validation and explicit readiness/cancellation outcomes.
Qualify **100 capture/resize/cancel/close cycles** at **100/150/200% scale**, with
no UI-thread GPU wait and bounded temporary allocations. Offscreen composition
does not establish that a frame was presented or that native input works.

E39 adds effective visibility and interaction state. Linux hiding currently
changes a paint flag while focus/capture lookup still traverses hidden
ancestors. UI2/UI3/UI5/UI8 must define hiding or disabling a subtree during
composition, dragging, popup presentation and queued command delivery. Preserve
local enabled preferences and distinguish hidden, disabled and merely clipped
content in input and accessibility. Qualify **100 hide/show/disable/restore
cycles**, with **0 stale commits, duplicate completions or trapped focus paths**.
This is a source-observed contract gap; native runtime behavior remains to be
tested through both frontends.

E40 adds lossless event batching and fair executor progress. Linux dispatches
at most 4,096 native events per turn but polls one more before checking the
limit, potentially discarding event 4,097. Reproduce this in a native fixture
before repair; test **4,095/4,096/4,097/8,193 events** for **100 bursts**, with
release, commit and close events at the edge and **0 unexplained event losses**.
UI2/UI3/UI9 must also bound queued/delayed dispatch so continuous work cannot
starve input, other windows or rendering. Under a declared **10-minute** load
with short nonblocking handlers, target command delivery p95 **≤100 ms**,
runnable work-class service gaps **≤250 ms**, and shutdown initiation **≤250 ms**.
Record queue rejection, coalescing and cancellation separately from delivery;
these scheduling goals supplement the existing frame and audio budgets.

E41–E43 add nested scrolling, window exposure and presentation recovery. Linux
currently consumes wheel events at an overflowing viewport's boundary, reports
no precise/phase metadata, ignores hidden/minimized notifications for its stored
frame-eligibility flag, and escalates repeated unavailable frames to an exception
that can close the application. These source findings need native reproductions.
UI1/UI3/UI5/UI6/UI9 must define scroll units and remaining-motion handoff, observed
exposure versus requested visibility, and bounded GPU recovery that preserves
native editors and healthy windows. Qualify **100 gestures per input class** and
**100 exposure/recovery cycles**, with **0 duplicated motion**, **0 presentation
attempts while settled and known non-presentable**, and **0 unintended closes of
healthy windows**. Proposed recovery limits are **≤10 retries/s**, an explicit
failure outcome within **5 s** of continuous retryable failure, and a current
frame within **1 s** after replacement resources are ready. Hidden/zero-size
surfaces wait for exposure; they do not consume a failure retry budget.

E44–E45 add clipboard failure safety and bounded editing. Linux cut currently
ignores clipboard-write failure before deleting the selection; paste does not
distinguish a failed empty clipboard read from valid replacement text. UI3/UI7
must prove **100 success/failure/retry cycles per operation**, with **0 lost
selections, failed-operation mutations or late deliveries**. UI3/UI4/UI7 must
also define consistent text validation and admission across setters, typing,
composition and transfer. Qualify **64 KiB single-line / 1 MiB multiline fixture
limits**, **L−1/L/L+1-byte boundaries**, and **100 interaction samples** at the
admitted size with **p95 ≤100 ms**. These are configurable test limits, not global
product restrictions. Preserve native editor/undo ownership, Unicode range
semantics and secure-input policy. The roadmap records the exact source
findings and SDK error semantics; runtime reproductions remain open.

### Complete platform inventory for review

The roadmap now includes a [60-family × five-platform source matrix](docs/design/native-ui-parity.md#complete-family-by-platform-source-inventory):
**300 explicitly classified cells**, distinguishing partial providers, custom
controls and missing native integrations. This completes the family-level
source inventory; UI0's operation-level catalog and all runtime qualification
remain open. The existing **47 cases / 470 frontend-provider result slots** are
planned evidence, not successful tests.

The inventory also preserves existing **macOS and Linux native tray providers**
under N56. Their shell-string actions and synchronous command execution need
integration with UI2/UI3's typed application commands and owned background work.
UI11 must prove **100 tray lifecycle cycles**, exactly one command per accepted
activation, zero late actions after close and zero leaked registrations or
connections. Notifications, badges and missing platform providers remain
separate work within that family; existing tray menus do not complete the
application/context-menu contract.

### Findings that change the implementation scope

- **macOS is the strongest starting point:** existing AppKit controls and
  native/GPU composition should be extended. Their presence does not qualify
  every focus, IME, accessibility or multi-window journey.
- **Linux still has a native-widget gap:** the current provider draws controls
  through SDL/WebGPU. Evaluate GTK4 controls, input and accessibility, with a
  real WebGPU embedding proof on Wayland and X11 before choosing migration.
- **Portable events are incomplete:** text fields, selects and sliders have
  getters/setters but no corresponding portable edit/change/commit callbacks.
  Add scoped events and stable selection identities, then migrate product
  polling while preserving native editor state.
- **Worker delivery needs an explicit boundary:** `GUI.post`/`postAfter` are
  UI-thread-only. Connect background completions to a bounded native-loop
  wakeup with cancellation, generation checks and teardown ownership; permanent
  polling is not the completion target.
- **Accessibility needs OS bridges:** custom `UI` semantics and activation
  exist, but the audited GUI/UI sources contain no bridge to the five native
  accessibility systems. Include native controls and virtual GPU children,
  with screen-reader journeys and focus continuity.
- **Collections and layout need shared contracts:** BTRSmith already owns a
  recycled album pool; preserve that work while adding native list/table/tree
  abstractions. Its application view currently rejects widths below 480;
  mobile requires adaptive layout, safe areas, keyboard insets and navigation.
- **The missing surface is broader than widgets:** focus/commands, IME and
  grapheme-safe editing, typed control events, async dialogs/pickers, clipboard,
  drag/drop, themes, text scaling, RTL, touch, lifecycle and GPU scheduling all
  have explicit inventory rows and acceptance requirements.
- **Native bindings and OS updates are core work:** qualify GObject ownership,
  Windows COM/message callbacks, Apple delegates and Android JNI lifetimes.
  Track build SDK, minimum OS and runtime capabilities separately, and verify
  installed artifacts on minimum/current OS versions. Keep adaptations in the
  provider so ordinary OS changes do not force product-screen rewrites.
- **Existing controls have concrete behavioral limits:** Linux button, slider
  and scroll handlers lack keyboard behavior; window key subscribers run before
  the focused editor, and the Linux editor key handler has no undo/redo branch.
  MacOS bordered buttons/selects reject fonts above 20 pt. Add behavioral
  regressions for these gaps in UI3–UI5, including native large-text adaptation.
- **Scene and presentation ownership need explicit rules:** current pickers
  block or pump nested events. UI1/UI7 must cover asynchronous parent-owned
  presentation, independent windows, external activation and non-path resource
  selections. Run the named lifecycle/transfer/queue cases for 100 cycles with
  zero wrong-owner deliveries, duplicate completions or stale mutations.

Retain the existing GUI factory, provider owners, checked native adapters,
`CallbackScope` and close/drain model. Reuse useful custom-renderer semantics
without treating a painted control as a native widget. Platform adaptations
should preserve the task and interaction semantics rather than desktop chrome.
The detailed roadmap cites the native accessibility/input contracts behind
these recommendations and leaves toolkit feasibility decisions reviewable.

### Native UI milestones

Recommended first reviewable increment: a native shell on each platform with
one editor, one button, a scrolling list and a GPU child. It must demonstrate
real focus traversal, one text commit, an inspectable accessibility tree and
clean teardown through both frontends. This exposes binding and composition
risks before a large widget rollout. Then migrate BTRSmith in order: search and
filters; Settings; Library browse/import; Player controls; mobile restoration.
Develop accessibility and ownership with each slice. Keep extended toolkit
families in UI11, promoting any used by an existing product journey into UI10.

| Milestone | Deliverable | Required exit evidence |
| --- | --- | --- |
| UI0 — Inventory and acceptance catalog | 60 families × 5 platforms; operation/test/owner mapping and documentation reconciliation | 300 classified planning cells, 100% public GUI operations and product journeys inventoried; missing/unverified distinct |
| UI1 — Native shell proofs | AppKit, proposed GTK4, Win32, UIKit and Android Views fixtures with text, scroll, GPU and accessibility | Both frontends on each platform, genuine native controls, interop proof and 100 lifecycle cycles |
| UI2 — Events and ownership | Scoped control/lifecycle/scroll events, stable identities, bounded dispatch and polling migration | Exactly one product command per commit; no setter-generated user action, late callback or editor replacement |
| UI3 — Input, focus and commands | Focus scopes, native command routing, keyboard/IME/undo, pointer/touch/pen contracts | Complete input matrix; zero lost commits, focus traps or playback shortcuts consuming text editing |
| UI4 — Controls and forms | Buttons/toggles, labels, text/search/password/multiline, numeric/range/select, images, progress and validation | 12 core control families qualified per platform with real input and accessibility |
| UI5 — Layout and adaptation | Intrinsic layout, navigation/splits, mobile insets, typography/RTL/themes/text scaling | Small phone through desktop layout matrix; zero clipped essential actions; state survives 100 layout/lifecycle changes |
| UI6 — Virtual collections | Native lists, tables, trees, selection, stable recycling and scroll anchors | 100,000-row stress fixture plus BTRSmith catalog; bounded cells/binds and preserved focus/selection |
| UI7 — Native services | Menus, popovers, async dialogs/pickers, clipboard, drag/drop, share/open and undo integration | All eight families qualified or genuinely OS-adapted; cancellation and parent-close behavior proven |
| UI8 — Accessibility | Native OS bridges, virtual GPU children, accessible collections and input alternatives | All core actions named/operable; core journeys pass keyboard and platform screen reader |
| UI9 — GPU and scheduling | Native/GPU clipping/overlays, display pacing, invalidation, assets and resource recovery | Frame/idle/memory budgets with playback; no unnecessary static redraw or per-frame accessibility flood |
| UI10 — Product qualification | Installed BTRSmith using the common native contracts, native automation and diagnostics | 50 core families passed/adapted, zero missing core journeys, all five platforms and both frontends qualified |
| UI11 — Extended toolkit | Date/color/font pickers, rich text, WebView, printing, notifications/tray, media integration, advanced data/document/help surfaces | Ten extended families retained and qualified where supported; product-used capabilities promoted before UI10 |

UI1 uses the host/binding prerequisites from P1/W1/I1/A1. Early platform shell
slices do not wait for complete UI10; final P5–P7 product qualification includes
it. Develop accessibility with each control and GPU surface. UI11 is explicit
remaining toolkit scope, not a reason to postpone the first usable product.

### Numeric UI acceptance goals

Use P6's named devices and 10,000-song / 1,000-album catalog. These are proposed
goals, with stricter existing product requirements retained:

- User action and catalog search/filter p95 **≤100 ms**, with I/O and debounce
  reported separately; 60 Hz frame p95 **≤16.7 ms**, p99 **≤33.3 ms** over
  10 minutes. Report 120 Hz results separately.
- Native cell pool **≤3× viewport capacity + 2 pinned editor/focus cells**,
  using maximum viewport capacity during the run; unchanged presentation has
  **0 cell rebinds**. Qualify with **100,000 rows** and actual product data.
- Settled static UI, with no animation/caret/work pending: **0 application
  layout/paint passes**, mean CPU **≤1% of one core over 60 s**.
- **100 lifecycle cycles**, **0 leaked owned handles/registrations**, settled
  memory growth **≤5%**; retain P6's **512 MiB desktop / 384 MiB mobile** budgets.
- Within those totals, catalog artwork uses **≤128 MiB desktop / ≤64 MiB
  mobile**, including in-flight resources, with **≤2 decode/conversion jobs**;
  explicit idle trim releases eligible cache entries within **1 s** without
  generating redraw work.
- **100% core actions and journeys** accessible via keyboard and the platform
  screen reader; **0** lost/duplicate text commits or inaccessible modal exits.
- Cover desktop scale **100/150/200%**, text scaling through **200%** and mobile
  accessibility text categories, RTL, IME, phone widths starting at **320 logical
  units**, tablet/split-screen and multi-monitor desktop layouts.

The detailed roadmap defines measurement conditions, exact input and device
matrices, resource ownership tests, and core versus extended completion. Live
native input, assistive technology and installed-product evidence are required;
screenshots and programmatic activation alone cannot complete native UI parity.

---

## 8. Execution order and milestone gates

The five-bucket table at the start of this plan is the execution schedule.
Preserve all detailed requirements above; the grouping changes order, not scope.
Work sequentially within the active bucket. A named platform milestone can
span foundation, UI and final product evidence; record those portions explicitly
and keep the overall milestone open until its last required gate passes.

1. **Compiler performance and reliable incremental builds.** The user closed
   unchanged latency at ≤5 s. Initial actual-Make cold/edit diagnostics are
   recorded. Continue M7's measured compiler cuts, M8a's allocation experiment and M11a/full
   M11 separate compilation. Deliver at least 10× improvement in self-host
   edit-to-executable and cold dev builds, with the stricter absolute budgets
   stated in the current assignment. Profile again before conditional M8b/M9/M10
   work. Preserve the ≤5 s unchanged regression guard and all correctness,
   reference, memory and required-host qualification. Do not revive the retired
   2 s no-op target or the shelved SDK projection work without new scope/evidence.
2. **C compatibility.** Freeze the reproducible audit/negative cases, then
   complete C1–C5 in order. Preserve the six-stage architecture and strict C11;
   update grammar, generated schemas, both frontends and incremental identities
   together where required. Qualify interactions and document intended refusals
   before starting new platform implementations.
3. **Cross-platform foundations.** Run P0/P1 first, then P2/P3/P4 and W1.
   Implement the target, ABI, runtime, OS service, native package, audio/GPU
   and packaging prerequisites in the Windows/iOS/Android tracks. Platform
   launch/ABI fixtures belong here; full native controls and product screens
   belong to bucket 4. Do not claim W2/I1/I2/A1/A2 complete while their UI or
   installed-product requirements are pending.
4. **Native UI.** Use the existing inventory, prove UI1's native shells and
   finish UI2/UI3's ownership/event/input contracts before widening controls.
   Complete UI4–UI9 with accessibility and GPU qualification in each slice,
   then UI10/UI11, preserving all 60 families and extended scope. Migrate
   BTRSmith screens using the existing native owners and shared provider model.
   This work starts after bucket 3, not alongside compiler optimization.
5. **Product and release qualification.** Finish P5–P7 and every outstanding
   W2/I2/A2 installed-product exit. Run the same final revision through complete
   journeys, physical-device/audio checks, performance/memory/lifecycle budgets,
   signed packaging, install/update and the full regression/CI matrix. Missing
   evidence remains open; focused checks cannot stand in for a full release.

### Focus rules

- Every implementation change names the **active bucket and milestone**, the
  requirement it advances, and the evidence that will close it. Keep one
  current checkpoint rather than switching tracks after an individual fix.
- Every handoff starts with the active bucket/milestone, its outstanding exit
  criteria and the next action toward those criteria. A detailed inventory in
  a later bucket is backlog, not a reason to change the current priority.
- Correctness repairs needed by that milestone are part of its work. Reproduce
  the failure, repair the owning contract, run the relevant gates, then return
  to the milestone's product/KPI acceptance. Do not expand a repair into a new
  subsystem or an unbounded hardening campaign without a demonstrated need.
- Record non-blocking discoveries and later-bucket ideas in the backlog; do
  not implement them ahead of sequence. Updating an inventory is not progress
  on its implementation milestone.
- Each performance checkpoint reports **goal, latest actual measurement,
  workload/revision, sample count and remaining gap**. Separate component
  benchmarks from real build-command timings. A higher test count or faster
  microbenchmark does not establish movement in BTRSmith's build KPIs.
- Do not claim a milestone complete because an experiment finished or tests
  passed. Its specified behavior and numeric goals need matching evidence.
  Reordering or reducing a bucket's exit requirements needs an explicit user
  decision; elapsed time and a difficult gate are not that decision.

**Immediate checkpoint, revised by the user September 22:** unchanged-build
latency is **closed at ≤5 s** on the measured macOS workload. Current qualified
medians are **4.180 s self-host / 4.732 s reference**, with all ten samples below
5 s. This is not a claim that the full host/correctness matrix is complete.
The unfinished SDK prepare/project implementation is backed up outside the
working tree and removed from production sources. Do not resume it as the
active assignment.

**Fresh diagnostic checkpoint:** actual `make btrsmith-native`, self-host dev
`-O0` with debug information and eight native jobs, in an isolated complete
copy of the 830 tracked current BTRSmith files. Compiler/SDK/object/output
caches start empty for the cold sample; installed toolchains/packages remain
available and OS page cache is uncontrolled. Compiler bootstrap is separate.

| Scenario | Actual Make wall | btrcc wall | Native wall | Compiled / reused units |
| --- | ---: | ---: | ---: | ---: |
| cold | 134.608 s | 124.340 s | 9.304 s | 17 / 0 |
| edit-navigation | 126.747 s | 119.000 s | 7.308 s | 1 / 16 |
| edit-ui-live | 112.325 s | 107.080 s | 4.935 s | 1 / 16 |
| edit-audio-adjacent | 113.142 s | 106.980 s | 5.843 s | 1 / 16 |

Each accepted body edit changes exactly one emitted C unit and the executable;
the other 16 native objects are reused. Each cold/changed build performs two
links for the existing receipt-admission protocol. The navigation/UI/audio
fixtures change only implementation literals, preserving signatures, layouts,
generic requests, call/effect shape and unrelated line counts. The original
UI fixture edited a dead toolbar method: compilation succeeded but output was
identical. It is retained as a rejected diagnostic, not counted as a body-edit
KPI. Its replacement edits the live library-screen title. All source/tool
hashes match afterward, and both the original product and isolated sources
are restored. These four timings are diagnostics, not medians/p95 or runtime
qualification; collect the required 5 cold / 20 edit distributions for acceptance.

**What must change:** the cold compiler accounts for 124.340 of 134.608 s.
Measured sequential phase marks attribute 37.213 s to lowering, 27.750 s to
emission, 21.570 s to analysis and 19.125 s to optimization (15.916 s setjmp).
Other phase marks total 8.838 s; 9.844 s of compiler wall remains outside those
marks and requires attribution. The 15 emitted C units total 182.535 MB.
Object reuse alone is already proven and leaves nearly the entire compiler
running after an edit. Whole-program artifact caching cannot reuse a changed
program's typed analysis or lowered bodies.

**M7 emission implementation checkpoint:** an isolated owner profile attributes
14.677 s to 507,509 filename escapes, for only 420 distinct encoded paths
(51,845 value bytes, excluding keys/map overhead). Both emitters now reuse
escaped filenames by exact value within one emission. Debug text, source maps
and unit partitioning are preserved. A fresh compiler reaches a raw byte-stable
self-host fixed point; expanded coverage passes **245 tests / four Linux-only
skips**. This is correctness evidence, not an end-to-end speedup claim.

**M7 measured emission result:** both alternating pairs improve. Cold Make
medians are **121.676 → 105.035 s**, saving **16.641 s / 13.7%**; navigation edit
medians are **115.059 → 99.706 s**, saving **15.353 s / 13.3%**. Emission falls
from **26.372 → 9.994 s cold** and **26.505 → 10.003 s after the edit**. Native
wall is effectively unchanged. All four unchanged controls pass the 5 s guard
(current median 4.094 s versus baseline 4.029 s); no no-op gain is claimed.
Both edits per variant rebuild one native unit and reuse 16; all four cold
runs compile all 17. All 30 final C units match after mapping only their exact
generated-output filenames in line directives. Source/tool/product hashes pass,
and the isolated product sources are restored. This completes qualification of
this performance cut at the stated scope, not M7 or the final acceptance matrix.
Reference performance and peak memory remain unmeasured for this cut.

**M7 measured setjmp result:** leaf short-circuits and sparse empty node facts
reduce origin-vector allocations **31.7 M → 12.8 M (59.8%)** and null visits
**16.35 M → 0.52 M (96.8%)**. Both compilers retain independent mutable results,
nonempty fact accumulation and write-record ordering. Baseline coverage passes
136 tests; the expanded suite passes **137 without skips**, using a fresh
strict-C11/O2 compiler with a raw byte-stable self-host fixed point.

Two alternating actual-Make pairs measure **104.836 → 99.975 s cold** and
**99.341 → 93.962 s navigation edit**, saving **4.861 s / 4.6%** and
**5.379 s / 5.4%**. Cold compiler wall is **91.390 s**; its setjmp phase falls
13.847 → 10.252 s. Compiler peak RSS falls about 8%, **4.57 → 4.20 GiB**;
this is not aggregate full-build memory. All 30 C units match under only exact
generated-output line-filename mapping, all input/restoration checks pass,
and all four unchanged controls stay below 5 s (current median **4.004 s**).
Cold builds compile 17 units; edits compile one, reuse 16 and change the
executable. These are diagnostic pairs, not full acceptance distributions.
Evidence: `~/.cache/btrc/perf/setjmp-builds-2026-09-22/{results,summary}.json`;
allocation, bootstrap and output proofs are in `setjmp-origin-2026-09-22/`.

**Type-owner checkpoint:** 221 generic/type baseline tests pass without skips.
The bounded product profile puts generic substitution at 2.535 s, generic C-type
rendering at 0.191 s, and all AST construction at 6.858 s (3.63 M nodes).
Nested owner times overlap; the instrumented wall is not a KPI. All fifteen
product C units match and input hashes pass. Substitution results can be mutated
by callers, so caching shared results requires an ownership redesign. Defer
that cache. The follow-up owner profile puts body lowering at **28.363 s**,
expression lowering at **17.705 s**, specialization inference at **4.477 s**,
and call-target resolution at **3.415 s** (nested times overlap). AST
construction/destruction is 6.421/2.349 s; IR construction/destruction is
1.557/0.431 s. Constructor cost alone cannot explain the remaining gap. Both
profiles preserve all fifteen C units. Evidence is in the performance document.

**M7 lexical type-map copying: implemented and measured.** A full-product
owner probe measures **6.561 s across 91,506 `TypeValidator.cloneTypes` calls**.
Callable snapshots/restores cost only 0.396/0.162 s, and source/borrowed-binding
and GPU-capacity snapshots/restores each cost less than 0.05 s. Keep their
isolation contracts; do not introduce shared flow snapshots to save that time.
The implementation uses the existing `Map.merge` operation to copy lexical
type bindings in bucket order, removing the temporary key vector and repeated
source lookups while retaining independently mutable maps. The candidate passes a strict-C11/O2
byte-identical bootstrap and 1,001 focused tests with no skips. Two alternating
actual-Make pairs measure **100.803 → 97.427 s cold** and
**94.224 → 92.095 s edit**, saving **3.35% / 2.26%**. All thirty output-unit
comparisons and source checks pass; compiler peak RSS is effectively flat.
All unchanged controls remain below 5 s with no compiles or links.
Evidence: `~/.cache/btrc/perf/scope-copy-builds-2026-09-22/{results,summary}.json`.
This qualifies the cut at that scope; M7 and final acceptance remain open.
The baseline passed 945 call, closure, ownership, default-argument and scope
tests. The profile preserves all
fifteen product C units and input hashes.

**Next: M7 remaining analysis/body lowering.** Cold analysis/lowering now
measure 18.343/31.281 s. The preceding owner profile measured
call-target resolution at 3.475 s / 298,932 calls; closure-escape checking
is 2.901 s / 118,656 calls, with nested time overlapping. Some apparent repeats
have different flow state. Calls with no explicit arguments can still have
default callback arguments requiring validation; do not skip those checks.
Preserve statement evaluation, defaults, ownership, generic and flow identity
when revisiting call resolution. Measure
repeated substitution and type-node allocation inside the remaining dominant
lowering phases. The code already reuses unbound leaf types; inspect compound
no-change resolution and repeated resolving/rendering of the same signature.
Use resolved types once where possible before introducing an interning table.
Any cache must have immutable substitution context or revision-aware identity,
with a caller-mutation audit; a mutable map address is not sufficient. Preserve
qualifiers, nullable/array shape, source coordinates, callback registration and
deterministic specialization ownership. Reference behavior, generic/ownership
regressions, fresh bootstrap and actual-product output/timing remain the gates.
Do not pursue more setjmp micro-optimizations without evidence that the residual
cost warrants them. Full final-tree and required-host gates remain open.

The completed comparison lives in
`~/.cache/btrc/perf/emission-builds-2026-09-22/{results,summary}.json`;
`build/plan-emission-builds.py` and its summary driver reproduce it. The prior
owner profile puts artifact storage/publication at only 0.181/0.281 s. The
remaining unmarked compiler lifetime is not all filesystem work, and the
pipeline explicitly retains major graphs, so teardown needs actual attribution.

**Remaining sequence:** finish M7's setjmp/generic/declaration cuts, run M8a's
allocation experiment, then prove M11a's module-contract slice before full M11.
For edits, reuse validated analyzed/lowered groups and stable C units, rebuild
only the changed group and consumers of genuinely changed semantic facts.
For cold builds, reduce repeated work/bytes and use bounded ready-group
parallelism only after dependency ownership is proven. Preserve the 6 GiB
aggregate memory ceiling and empty-cache definition. M7's 55 s and M8a's 40 s
compiler goals are intermediate; neither meets 10×. Conditional representation
or allocation changes require a new profile of the remaining serial floor.
The detailed contracts and 13 s cold / 10 s edit design envelopes are in M7
and M11; these are targets, not measured gains.

Evidence: `~/.cache/btrc/perf/edit-cold-2026-09-22/summary.json`,
`continued-results.json`, original failed-fixture `results.json`, raw logs and
native reports. The reproduction drivers are `build/plan-edit-cold-*`.
Full final-tree, reference, required-host, memory and runtime gates remain open.
Buckets 2–5 stay queued.
