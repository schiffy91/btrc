# WORKSTREAMS packets: Claude

Part of [WORKSTREAMS.md](../../WORKSTREAMS.md), the shared plan for Claude, Codex and the owner. That file holds the purpose, decision D27, the coordination protocol, the assignment matrix, the timeline and the open questions; this file holds the Claude packets in full. `packets.json` beside it is the same packet set in machine-readable form.


Grouped by owner, then by stage (the first stage a packet's `plan_stage` names), then by group and number. Owned paths, steps, acceptance and risks are the analysts' text, escaped for Markdown only. Changes are marked **Writer note** (listed in §9) or **Review change** (listed in §10); where the two differ, the review change wins.

### 6.1 Claude packets

Claude: the compilers, specs, runtime, interop, the C track, Stage 24, bucket 1, CI hotspots and every integration. Each packet lands Python first and btrc second, in one commit per construct where it changes behavior (parity), and ends with the gates its acceptance lists.

#### Stage 4: Structure-first drift review, native-migration audit, BTRSmith pin bump

<a id="cl-r-00"></a>

##### CL-R-00 · Stage 4 close-out: integrate the three open Stage 4 lanes and write the drift-findings ledger

- **Owner:** Claude · **Group:** R · **Stage:** 4 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-structure-stdlib`; `btrsmith-structure-repo`
- **Depends on:** none
- **Parallel-safe with:** CL-R-02, CL-UIA-01

> **Review change:** New (§10 P2). PLAN Stage 4's `btrsmith-structure-stdlib` and `btrsmith-structure-repo` were in no packet, and three Stage 4 lanes were unmerged against `430a892` while the C4 lane reserves the same hotspots.

**Owned paths**

- lanes `stage4/btrsmith-defects-compiler` (12 commits on `origin/main` 430a892), `stage4/residual-final` (6) and `stage4/c-output-parity` (37), integrated through `integ/*` branches off main-kn9jxh
- the hotspots those lanes change: src/compiler/btrc/pipeline/ModuleUnits.btrc, pipeline/Pipeline.btrc, ir/gpu/Pipeline.btrc, cli/Driver.btrc, frontend/Packages.btrc, src/compiler/python/frontend/packages.py, src/runtime/c/manifest.toml, Makefile, examples/native-package/Makefile
- src/tests/fixtures/compiler_boundaries/ (c-output-parity's D14 re-captures, one per commit)
- src/stdlib/README.md (new 'Drift findings' ledger section)
- BTRSmith docs/NativePlatformPlan.md ('Drift findings' section; shared append-only with CX-P1-01 and CL-UIA-03)
- PLAN.md (Stage 4 progress entry)

**Must not touch**

- docs/design/plan-reference.md
- BTRSmith `src/**`, `make/**` and flake files (CL-R-01 owns the pin bump and native-source-check)

**Steps**

1. Before the C4 lane takes its hotspot reservation (`CL-C-03` and `CL-C-04` depend on this packet), integrate the three open lanes in D5 batches: `stage4/btrsmith-defects-compiler` once its two failing contracts pass in both compilers; `stage4/residual-final`; then `stage4/c-output-parity` with its D14 boundary re-captures (one per commit, each reason recorded in the manifest and in PLAN.md).
2. Regenerate derived files, run the cloud batch gate (§3.8 step 4), push `main` and read ci.yml, macos.yml and windows.yml.
3. Write the findings ledger: every ranked btrc finding (btrc-D001…) in a 'Drift findings' section of src/stdlib/README.md, each closed (with its commit) or excepted (documented exception such as btrc-D024 and btrc-D039); every BTRSmith finding (bsm-D001…D045) in BTRSmith docs/NativePlatformPlan.md's 'Drift findings' section.
4. Check the 17 manifests: each of the 16 stdlib groups plus the root manifest has a facade and a manifest, or a documented exception (GPU, Realtime); the naming and LSP-catalog tests pass.
5. Post the issue #20 evidence (the 17-file native inventory with keep/migrate/delete reasons) on BTRSmith #20. native-source-check's `*.swift` coverage is `CL-R-01`'s, which owns BTRSmith `make/**`.

**Acceptance**

- [ ] The three lanes are on main; ci.yml, macos.yml and windows.yml are green on the pushed SHA (run ids); boundary-check passes and each re-capture is recorded.
- [ ] src/stdlib/README.md and BTRSmith NativePlatformPlan.md list every ranked finding as closed or excepted (0 open).
- [ ] 17 manifests checked; naming and LSP-catalog tests pass.
- [ ] PLAN.md's Stage 4 entry records the btrc side of the Stage 4 exit. The BTRSmith side (native-source-check covers `*.swift`, #20 evidence, the pin) closes with `CL-R-01` and `MAC-R-01`.

**Risks**

- The ranked list (`~/.cache/btrc/roadmap/stage4-consolidated.json`) lives on the Mac. If the cloud session cannot read it, rebuild the ledger from PLAN.md's Stage 4 entries and the lane reports, or have the owner export it in Session 1.
- `stage4/btrsmith-defects-compiler`'s first integration failed two contracts; it may need another fix round.

<a id="cl-r-01"></a>

##### CL-R-01 · BTRSmith pin bump to the Stage-4 btrc close-out: merge stage4/w2-btrsmith, re-pin, finish the rename ripple, run the Linux checks

- **Owner:** Claude · **Group:** R · **Stage:** 4 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `btrsmith-pin-bump`
- **Depends on:** [CL-R-00](#cl-r-00) (to finish: this packet starts now and re-pins to the close-out commit when CL-R-00 lands)
- **Parallel-safe with:** CL-R-02, CL-R-04, CL-R-05, CL-R-06, CL-R-23, CL-R-36, CL-R-37, CX-R-01, CX-R-03

> **Review change:** Its Stage 4 dependency now names `CL-R-00`. It also takes the `*.swift` native-source-check item, because it owns BTRSmith make/** (§10 P2).

**Owned paths**

- btrsmith:flake.nix
- btrsmith:flake.lock
- btrsmith:btrc.lock (regenerated by the compilers, never hand-edited)
- `btrsmith:src/**`
- `btrsmith:tests/**`
- `btrsmith:tools/**`
- `btrsmith:make/**`
- btrsmith:docs/Handoff.md

**Must not touch**

- btrsmith:main (no push; MAC-R-01 fast-forwards it after requalification)
- `btrsmith:.github/**` (CL-R-37)
- every btrc path (read-only; a missing rename-table row is reported to the integrator)
- docs/design/plan-reference.md

**Steps**

1. Attach schiffy91/btrsmith with push access; create branch stage4/pin-bump from btrsmith main adb3276f and merge stage4/w2-btrsmith (e8a53e27, pins btrc c7f785e), resolving against main.
2. Bump the btrc flake input from c7f785e to btrc main 8b73c79 and run `nix flake lock`. Re-point it to the Stage-4 close-out commit when that lands (docs-only delta expected).
3. Apply every docs/design/btrsmith-rename-table-w2.md row added after c7f785e: btrc-D050/D051 primitives, D033/D055/D056 macOS provider surface, nullable flow (List.head/tail, ListNode.next), D028/D052/D053 (DaemonSpec.renderStartCommand, Strings delegates, NativeWorker), D061 FileSystemOutcome\<T>, plus section-2 substitutions. Then grep every old spelling.
4. Guard every new possibly-null store warning in BTRSmith sources with checks, no casts. Let the compilers rewrite btrc.lock.
5. In BTRSmith's dev shell on Linux run `make check source-check application-frontend-check flake-check linux-product-check`, and `btrsmith-library-smoke` under btrc's tools/virtual-display.sh. Diff failures against Stage 2's qualifying column (pin 05ec9cb: 5 pre-existing plus 7 drifted).
6. Update docs/Handoff.md with the pin. Push the branch and open a BTRSmith draft PR (never merged by this packet). Report SHAs, a per-target table and the macOS-only targets left to MAC-R-01.
7. Extend BTRSmith's native-source-check to cover `*.swift` (PLAN Stage 4 exit), and run it.

**Acceptance**

- [ ] `nix develop -c make check source-check` exits 0 on Linux through both frontends with clang and gcc
- [ ] `make application-frontend-check` exits 0: reference and selfhost link plans byte-identical
- [ ] No failure outside the Stage 2 qualifying-column list; every remaining failure is named
- [ ] `git grep` for every old spelling in rename-table sections 1-2 finds nothing in src/, tests/ or tools/
- [ ] PR body lists commits, per-target pass/fail counts, the btrc pin SHA and the deferred macOS-only targets
- [ ] native-source-check covers `*.swift` and passes

**Risks**

- Cloud access to the private BTRSmith repo: if add_repo is refused, this moves to the Mac.
- macOS-only sources (tests/macos, the CoreAudio and AppKit paths) are not compiled on Linux, so renames there are verified only in MAC-R-01.
- The Stage-4 close-out may add renames; re-pin and re-grep.

#### Stage 5: Quiet baseline measurement round

<a id="cl-r-02"></a>

##### CL-R-02 · Mac runbook kit: tools/runbook engine, automated quiet check, resumable rounds, stage4-requal/stage5/stage13-final presets, evidence publication

- **Owner:** Claude · **Group:** R · **Stage:** 5 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-baseline-round`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-04, CL-R-05, CL-R-06, CL-R-23, CL-R-36, CL-R-37, CX-R-01, CX-R-03

> **Writer note:** `tools/bench/scripts/README.md` is shared append-only with `CX-C-01` (§9 item 11).

**Owned paths**

- tools/runbook/__init__.py
- tools/runbook/__main__.py
- tools/runbook/engine.py
- tools/runbook/quiet.py
- tools/runbook/evidence.py
- tools/runbook/run.sh
- tools/runbook/README.md
- tools/runbook/presets/stage4-requal.toml
- tools/runbook/presets/stage5.toml
- tools/runbook/presets/stage13-final.toml
- src/tests/python/test_runbook_engine.py
- src/tests/python/test_quiet_check.py
- tools/bench/scripts/README.md

**Must not touch**

- tools/budget_bench.py (hotspot; request changes instead)
- tools/native_plan.py
- Makefile
- src/tests/conftest.py
- `src/compiler/**`
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. RunbookEngine (engine.py) runs presets:
   - clones from ~/.cache/btrc/hub.git and ~/.cache/btrsmith/hub.git into ~/.cache/btrc/clones/\<preset>, outside Drive;
   - checks for at least 80 GB free and prunes build/test-btrcc to the newest 20;
   - builds the clang -O2 btrcc via tools/bench/scripts/build_btrcc.sh under `withlock.sh btrcc-build`;
   - runs each cell under its named lock (gate, bench, gui-capture, guest);
   - writes a checkpoint per cell, so rerunning the same command resumes.
2. QuietCheck (quiet.py) is the standing-approvals check, 60 s of samples every 5 s:
   - no other agents, builds or guests (process scan for btrcc, cc1, clang, pytest, nix builders, qemu, emulator, Simulator);
   - `podman machine list --format json` shows the machine stopped;
   - `tmutil currentphase` reports BackupNotRunning;
   - Google Drive, mds and mdworker each under 5% CPU;
   - the workspace is under ~/.cache/btrc/bench.noindex/.

   It waits and retries, never changes settings, takes injectable probes, and refuses non-Darwin hosts unless --rehearsal.
3. stage5.toml:
   - BTRSmith pins aeeca0fd and the post-Stage-4 pin, on the selfhost and reference frontends;
   - budget_bench `--scenarios all`, plus noop through `--entry make`, self-compile and corpus;
   - workers 1/2/4/8 at --native-jobs 8, with --timing-cold;
   - 5 cold and 20 incremental samples;
   - the quiet check before every cell.
4. stage4-requal.toml runs, in order:
   - tools/bench/scripts/batch_gate.sh with the BTRSmith clone;
   - `make release-check` for each frontend, serially, under gui-capture;
   - a diff against the stored Stage 2 qualifying-column failure list;
   - on green, a fast-forward push of BTRSmith main (needs the owner's SSH agent).

   Optional cell: the Stage 15 BTRSmith peak/instructions A/B via tools/bench/scripts/instr.sh. stage13-final.toml composes the full D5 gate, the determinism tier and the final quiet scenarios.
5. EvidencePublisher (evidence.py):
   - writes summary.json: per-cell median/p95/max, failures, and provenance (exact host string 'Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0', clang version, SHAs);
   - ingests through `python3 -m tools.qualification ingest --budget-bench ... --this-host`;
   - redacts $HOME paths and runs gitleaks;
   - pushes only the summaries to the evidence/\<preset>-\<date> branch.
6. run.sh enters `nix develop --profile ~/.cache/btrc/gcroots/runbook` and runs `python3 -m tools.runbook <preset...>`. It prints the next owner action, for example unlocking 1Password.
7. Write the tests with fake probes. Rehearse stage5 in the container with --rehearsal --stand-in --dry-run.

**Acceptance**

- [ ] `python3 -m pytest src/tests/python/test_runbook_engine.py src/tests/python/test_quiet_check.py src/tests/python/test_budget_bench.py -q` passes on Linux
- [ ] `tools/runbook/run.sh stage5 --rehearsal --stand-in --dry-run` completes in the container and writes summary.json; a second run resumes without repeating finished cells
- [ ] Draft-PR macos.yml `tests (unit)` shard is green, with test_quiet_check.py running the real Darwin probes in report-only mode
- [ ] `make lint format-check` and `git diff --check` are clean

**Risks**

- Quiet heuristics may misfire on the owner's Mac (process names); probes must be tunable without code changes.
- Evidence push needs the owner's credentials, and the public-repo destination is open question 2.
- If budget_bench needs a change, file it for the budget_bench window holder (CL-R-23).

<a id="cl-r-03"></a>

##### CL-R-03 · Stage 5 attribution and gap table from the evidence branch

- **Owner:** Claude · **Group:** R · **Stage:** 5 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `perf-baseline-round`
- **Depends on:** [MAC-R-02](owner.md#mac-r-02)
- **Why not now:** Needs the Stage 5 evidence (MAC-R-02).
- **Parallel-safe with:** CL-R-04, CL-R-05, CL-R-06, CL-R-07

**Owned paths**

- PLAN.md (Status gap table, Stage 5 progress entry)
- docs/design/compile-performance.md (new 'Stage 5 baseline' section)

**Must not touch**

- docs/design/plan-reference.md
- `tools/**`
- `src/**`

**Steps**

1. Fetch evidence/stage5-\<date>.
2. Run 4 read-only analysts (self-host cold; release; reference; edits plus workers). They use tools/bench/scripts/phases.py, tools/perf.py worker_phase_times and worker_usage, and the BTRC_TIMING owner and worker lines.
3. The integrator writes the tables from JSON: compile-performance.md section, PLAN.md Status gap table, and a progress entry naming the btrcc build (clang -O2).
4. Record every budget the new pin misses as a finding before Stage 6.

**Acceptance**

- [ ] Every open bucket-1 row in PLAN.md Status shows median/p95/max, sample count and pin
- [ ] Phase attribution covers ≥90% of cold and edit wall time for both frontends
- [ ] New-pin misses are listed as findings
- [ ] `git diff --check` is clean

**Risks**

- Missing samples (an interrupted round) mean rerunning MAC-R-02 cells, not estimating them.

#### Stage 6: Edit-floor spikes, Stage B key and journal spec, reference attribution, native track I

<a id="cl-r-04"></a>

##### CL-R-04 · Stage B consulted-fact reuse-key spec and skip-unchanged journal spec, with pass-family auditors and adversarial review (design only)

- **Owner:** Claude · **Group:** R · **Stage:** 6 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-stageb-slice4`; `perf-stageb-skip-unchanged`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-02, CL-R-05, CL-R-06, CL-R-23, CL-R-36, CL-R-37

**Owned paths**

- docs/design/stage-b-reuse-keys.md (new)
- docs/design/separate-compilation.md (one link paragraph under Stage B only)

**Must not touch**

- `src/compiler/**` (read-only)
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Four read-only pass-family auditors list every lookup each pass consults:
   - btrcc analysis: `analyzer/*.btrc`, `analyzer/validation/*`, `analyzer/ownership/*`;
   - btrcc lowering: `ir/lowering/*` (Calls, CallableFlow, Callables, Generics, Context);
   - the Python `analyzer/*.py`;
   - the Python `ir/lowering/*.py` plus application/modules.py and pipeline/ModuleUnits.btrc records (ValidationJournal, demand journal, realtime scan records).
2. The key designer specifies the per-source-group key: exported facts, ABI, generic requests, ownership and effect summaries, and source locations of unrelated modules.
3. The key designer specifies the journal: what is recorded, how replay reproduces the side tables, and the fall-back on a missing or incomplete journal.
4. The key designer specifies the observable counters in both compilers: groups analyzed and lowered, native compiles, links.
5. Two adversarial reviewers construct edits the spec would reuse unsoundly. Each becomes a numbered Stage 7 invalidation row with a fixture sketch and the expected rebuild set.
6. A parity reviewer confirms both compilers can expose identical counters. Record the review table in the doc.

**Acceptance**

- [ ] Approved under the standing design-approval rule: two adversarial reviewers and one parity reviewer, zero unresolved blocking findings, review table in the doc
- [ ] Every pass from the audit is listed with the facts it consults
- [ ] Each reviewer-found edit has an invalidation row with a fixture sketch; CL-R-09 cites these ids
- [ ] `git diff --check` is clean

**Risks**

- Stage 5/6 numbers may reprioritize levers; the spec freezes only at Stage 9 (CL-R-19).
- Drafting ahead of Stage 5 relies on the D27(a) planning clause.

<a id="cl-r-05"></a>

##### CL-R-05 · Stage 6 per-file-cache floor spikes (decl, parse, instances, records, visibility, composed) as never-merged spike branches, with the stage6-spikes preset

- **Owner:** Claude · **Group:** R · **Stage:** 6 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-floor-spikes`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-02, CL-R-04, CL-R-06, CL-R-23, CL-R-36, CL-R-37

**Owned paths**

- branches spike/stage6-decl, spike/stage6-parse, spike/stage6-instances, spike/stage6-records, spike/stage6-visibility, spike/stage6-composed (never merged)
- tools/runbook/presets/stage6-spikes.toml

**Must not touch**

- main and main-kn9jxh (spikes are never merged)
- `src/language/**`
- src/compiler/btrc/parser/Parser.btrc on main (C lanes)

**Steps**

1. From main 8b73c79, each spike prototypes one lever in btrcc only:
   - decl: reuse DeclarationRegistry facts of unchanged groups;
   - parse: reuse cached tokens and AST of unchanged files;
   - instances: reuse generic-instance closure records;
   - records: load packed per-group records without re-validation;
   - visibility: reuse the import visibility of unchanged import sets.
2. Compose the five on spike/stage6-composed.
3. Each spike keeps btrcc output byte-identical on budget_bench's edit fixtures (stand-in in the cloud).
4. Verify each branch in the container:
   - btrcc builds with zero analyzer warnings;
   - the corpus passes through btrcc;
   - `tools/bench/scripts/cmp_units.py` finds identical units against the base on the stand-in edit fixtures and on self-compile.
5. Write stage6-spikes.toml:
   - per branch, a clang -O2 build under btrcc-build;
   - `tools/bench/scripts/edit_instr.py` instructions retired per fixture at --jobs 1 against the base;
   - one quiet wall-clock cell for the composed branch.

**Acceptance**

- [ ] Six spike branches pushed; none merged
- [ ] Each branch: btrcc builds warning-free and the btrcc corpus run passes
- [ ] cmp_units.py reports identical units against the base on the stand-in fixtures and on self-compile
- [ ] `python3 -m tools.runbook stage6-spikes --dry-run --rehearsal` validates the preset

**Risks**

- Spikes are deliberately unsound shortcuts; their only output is the measurement.
- C-lane parser changes may force a rebase before MAC-R-03.
- Instructions are not measurable in the container, so there is no cloud signal on value.

<a id="cl-r-06"></a>

##### CL-R-06 · Reference-compiler attribution capture: tools/perf.py --cprofile rollup by owner and phase, plus the stage6-reference preset

- **Owner:** Claude · **Group:** R · **Stage:** 6 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `perf-ref-attribution`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-02, CL-R-04, CL-R-05, CL-R-23, CL-R-36

**Owned paths**

- tools/perf.py
- src/tests/python/test_perf_tool.py
- tools/runbook/presets/stage6-reference.toml

**Must not touch**

- tools/budget_bench.py
- `src/compiler/python/**` (profiling only, no code change)

**Steps**

1. Add a --cprofile mode for --frontend reference. It profiles cold builds and budget_bench EDIT_FIXTURES edits, rolls cumulative time up by owner class and module (frontend, analyzer, lowering, optimizer, emitter, artifacts, native plan), reconciles with the `btrcpy timing:` phases, and reports the attributed fraction.
2. Test on the stand-in workspace; optionally cross-check on a Linux BTRSmith clone (cProfile proportions are host-independent enough for triage).
3. Write stage6-reference.toml for the Mac capture on the measured pin.

**Acceptance**

- [ ] test_perf_tool.py passes
- [ ] A stand-in run writes attribution JSON reconciling to ≥90% of wall time
- [ ] The preset validates in a dry run

**Risks**

- cProfile overhead skews small functions; report it beside the uninstrumented BTRC_TIMING totals.

<a id="cl-r-07"></a>

##### CL-R-07 · Native track I: attestation after SIGN_CODE and native receipts, so a product no-op does 0 links and 0 signings (sole native_plan.py owner)

- **Owner:** Claude · **Group:** R · **Stage:** 6 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `perf-signing-attest`; `perf-native-receipts`
- **Depends on:** [MAC-R-02](owner.md#mac-r-02)
- **Why not now:** Stage 6 opens after the Stage 5 baseline (MAC-R-02); native_plan.py changes alter the measured native builder.
- **Parallel-safe with:** CL-R-03, CL-R-04, CL-R-05, CL-R-06

**Owned paths**

- tools/native_plan.py
- src/tests/python/test_native_plan_attestation.py (new)
- btrsmith:make/Packaging.mk (attestation after SIGN_CODE, D9)
- btrsmith:make/Product.mk
- tools/runbook/presets/stage6-native.toml

**Must not touch**

- tools/budget_bench.py
- `src/compiler/**`
- `btrsmith:src/**`

**Steps**

1. Record a link and signing attestation after SIGN_CODE (D9). An unchanged product build then proves the signed executable is current and skips the link and codesign.
2. Extend the receipts already keyed on the environment (ab1f68f) with the signing identity. Fold in the natives spike.
3. Write tests with an injected fake codesign on Linux; macOS draft-PR CI exercises real ad-hoc codesign.
4. Write stage6-native.toml: product no-op link and sign counts, and the native edit-step distribution on BTRSmith.

**Acceptance**

- [ ] test_native_plan_attestation.py passes on Linux and in the macos.yml unit shard (real `codesign -s -`)
- [ ] A second unchanged build of the macOS test fixture reports 0 links and 0 codesign invocations in the native report
- [ ] Product evidence comes from MAC-R-03: no-op 0 links / 0 signings, native edit step ≤1.4 s

**Risks**

- BTRSmith's post-link codesign rewrote binaries after the receipt in Stage 2; the attestation must cover that ordering.
- native_plan.py hotspot: Lane N (CL-R-21, CL-R-28) waits for it.

<a id="cl-r-08"></a>

##### CL-R-08 · Stage 6 close: spike table, D12 resident-compiler go/no-go, D11 stopping-rule baselines, reference ≥90% attribution report, native-track merge gate

- **Owner:** Claude · **Group:** R · **Stage:** 6 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `perf-floor-spikes`; `perf-ref-attribution`; `perf-signing-attest`; `perf-native-receipts`
- **Depends on:** [MAC-R-03](owner.md#mac-r-03); [CL-R-04](#cl-r-04)
- **Why not now:** Needs the Stage 6 Mac evidence (MAC-R-03).

**Owned paths**

- docs/design/separate-compilation.md (spike table)
- docs/design/compile-performance.md (Stage 6 section)
- PLAN.md (Stage 6 progress, D11/D12 records)

**Must not touch**

- docs/design/plan-reference.md
- `src/compiler/**`

**Steps**

1. Write the per-lever delta table from evidence/stage6-\<date>: either the composed floor from the quiet run or the per-lever deltas as a non-additive estimate.
2. Record D12: does a per-file-cache floor reach ≤3 s private-body edit compile time? State go or no-go with numbers.
3. Write the reference attribution (≥90%) naming the Stage 8 hotspot modules.
4. Integrate CL-R-07 through a batch gate: lint, format-check, generated-check, extension, the full CI matrix on the draft PR, local bootstrap, zero-warning self-host transpiles. Push main fast-forward.

**Acceptance**

- [ ] Spike table and D12 decision recorded with instruction numbers
- [ ] Reference attribution ≥90%
- [ ] Batch gate green and CI green on the pushed main (ci.yml, macos.yml, windows.yml run ids reported)

**Risks**

- An ambiguous floor (non-additive levers) needs an explicit D12 rationale.

#### Stage 7: Correctness nets, M10 pool qualification, first cold-path cuts

<a id="cl-r-09"></a>

##### CL-R-09 · M11 acceptance test modules (invalidation; corruption and interruption; concurrency and directories; native and sanitizer; dev/release switching) and the edit-sequence harness

- **Owner:** Claude · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-m11-acceptance`
- **Depends on:** [CL-R-04](#cl-r-04); [CL-R-08](#cl-r-08)
- **Why not now:** Stage 7 opens after Stage 6 (CL-R-08); invalidation rows come from the key spec (CL-R-04).
- **Parallel-safe with:** CL-R-10, CL-R-12, CL-R-13, CL-R-15, CL-R-17

**Owned paths**

- src/tests/python/test_m11_invalidation.py
- src/tests/python/test_m11_corruption_interruption.py
- src/tests/python/test_m11_concurrency_directories.py
- src/tests/python/test_m11_native_sanitizer.py
- src/tests/python/test_m11_dev_release_switching.py
- src/tests/python/m11_edit_sequence.py
- `src/tests/fixtures/m11/**`

**Must not touch**

- `src/compiler/**` (defects go to a fixer commit reviewed as a paired change)
- src/tests/conftest.py
- src/tests/corpus_files.py (integrator updates counts)

**Steps**

1. Five authors share one worktree with a pinned BTRC_TEST_BTRCC; each owns one module.
2. Every CL-R-04 invalidation row becomes a test run through both compilers; tests cite the row ids.
3. Build the edit-sequence harness: a scripted series of edits, each checked against a clean build.
4. A fixer in its own worktree lands paired compiler fixes for real defects found.
5. The integrator updates source_count and fixture lists.

**Acceptance**

- [ ] All five modules pass through both compilers on Linux
- [ ] The native/sanitizer module is green in the macos.yml unit shard of the draft PR
- [ ] Every CL-R-04 row is referenced by at least one test id
- [ ] `python3 -m tools.qualification skip-gate` reports no unexpected skip

**Risks**

- Real reuse defects found here block Stage 9; budget fixer time.

<a id="cl-r-10"></a>

##### CL-R-10 · Opt-in determinism tier: module-unit self-compile byte-stable at 1/2/4/8 workers × 10 shuffled schedules (make test-determinism)

- **Owner:** Claude · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `perf-m11-acceptance`
- **Depends on:** [CL-R-08](#cl-r-08)
- **Why not now:** Stage 7 opens after Stage 6 (CL-R-08).
- **Parallel-safe with:** CL-R-09, CL-R-12, CL-R-15

**Owned paths**

- src/tests/btrc/test_m11_determinism.py
- Makefile (test-determinism target only)
- tools/runbook/presets/stage7-determinism.toml

**Must not touch**

- src/compiler/btrc/pipeline/ModuleUnits.btrc and src/compiler/python/application/modules.py (a schedule-shuffle hook goes through CL-R-11's queue)
- src/tests/conftest.py

**Steps**

1. Add an opt-in pytest marker excluded from `make test`.
2. Self-compile with --module-units at --jobs 1/2/4/8, 10 schedules each, seeded through the worker pool's existing ordering knob. If none exists, request the hook from CL-R-11.
3. Compare all unit outputs byte for byte; add `make test-determinism`.
4. Write the Mac preset.

**Acceptance**

- [ ] `make test-determinism` is green in the container
- [ ] `pytest --collect-only` under `make test` does not collect it
- [ ] Runtime recorded; the Mac run comes from MAC-R-04

**Risks**

- 40 self-compiles take hours on 4 CPUs.
- The shuffle hook may need a compiler change; route it through CL-R-11.

<a id="cl-r-11"></a>

##### CL-R-11 · setjmp barriers off the serialized u-solve path (paired, one commit; first in the ModuleUnits.btrc/modules.py queue)

- **Owner:** Claude · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-setjmp-barriers`
- **Depends on:** [CL-R-08](#cl-r-08)
- **Why not now:** Stage 7 opens after Stage 6 (CL-R-08).
- **Parallel-safe with:** CL-R-09, CL-R-10, CL-R-12, CL-R-13, CL-R-15

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc
- src/compiler/python/application/modules.py
- src/compiler/btrc/ir/optimization/setjmp/Analysis.btrc
- src/compiler/btrc/ir/optimization/setjmp/Safety.btrc
- src/compiler/python/ir/lowering/exceptions.py
- src/tests/python/test_module_units.py (setjmp cases)
- tools/runbook/presets/stage7-setjmp.toml

**Must not touch**

- `src/language/**`
- src/compiler/btrc/parser/Parser.btrc
- src/compiler/python/parser/parser.py

**Steps**

1. Write one spec covering both halves; implement btrc and Python in a single commit.
2. Keep units byte-identical to each compiler's own previous output.
3. Add setjmp cases to test_module_units.py.
4. Bootstrap, then run the zero-warning self-host transpiles of BtrccMain, cli/WindowsMain and cli/MacOSMain.
5. Write the u-solve-at-4-workers preset.

**Acceptance**

- [ ] test_module_units.py passes through both compilers
- [ ] cmp_units.py finds identical units per compiler on the corpus and self-compile
- [ ] Bootstrap fixed point holds; zero analyzer warnings
- [ ] MAC-R-04 shows u-solve ≥40% faster at 4 workers

**Risks**

- Holds the ModuleUnits/modules.py hotspot; CL-R-14 and CL-R-16 queue behind it.

<a id="cl-r-12"></a>

##### CL-R-12 · Generic temporaries in btrcc (btrc-internal, byte-identical) plus an empty child-container allocation counter for M8a

- **Owner:** Claude · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-generic-temporaries`
- **Depends on:** [CL-R-08](#cl-r-08)
- **Why not now:** Stage 7 opens after Stage 6 (CL-R-08).
- **Parallel-safe with:** CL-R-09, CL-R-10, CL-R-11, CL-R-13

**Owned paths**

- src/compiler/btrc/ir/lowering/Generics.btrc
- src/compiler/btrc/ir/lowering/Context.btrc
- src/compiler/btrc/frontend/Timing.btrc (allocation counter)
- tools/runbook/presets/stage7-m8a.toml

**Must not touch**

- `src/compiler/btrc/generated/**` (no hand edits)
- tools/compiler_codegen/ast.py (hotspot)
- `src/compiler/python/**`

**Steps**

1. Three read-only caller-mutation auditors list every mutation of generic temporaries.
2. One implementer removes the redundant temporaries and child-container allocations (precedent fcdbd6d).
3. Add a BTRC_TIMING counter for empty child-container allocations.
4. Check byte identity against btrcc's own previous output; bootstrap.
5. Write the M8a preset: cold transpile and peak at --jobs 1.

**Acceptance**

- [ ] btrcc units byte-identical to its previous output on the corpus, self-compile and the stand-in
- [ ] Bootstrap fixed point holds
- [ ] The counter shows ≥50% fewer empty child-container allocations on self-compile
- [ ] MAC-R-04: peak ≤3 GiB and cold transpile ≤40 s on BTRSmith, or a budget revision with evidence

**Risks**

- The 40 s target may stay unmet; D11's stopping rule then moves the levers to Stage 12.

<a id="cl-r-13"></a>

##### CL-R-13 · mimalloc for btrcc (btrc-internal build option) with instruction and quiet-run presets feeding D15

- **Owner:** Claude · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `perf-mimalloc`
- **Depends on:** [CL-R-08](#cl-r-08)
- **Why not now:** Stage 7 opens after Stage 6 (CL-R-08).
- **Parallel-safe with:** CL-R-09, CL-R-11, CL-R-12

**Owned paths**

- flake.nix
- flake.lock
- `nix/*`
- Makefile (btrcc link flags only)
- tools/bench/scripts/build_btrcc.sh
- tools/runbook/presets/stage7-mimalloc.toml

**Must not touch**

- `src/runtime/c/**` (runtime allocator untouched)
- `src/compiler/**`

**Steps**

1. Add the pinned nixpkgs mimalloc to the dev shell and an opt-in BTRCC_ALLOCATOR=mimalloc link.
2. Prove btrcc output byte-identical to the system-malloc build.
3. Write instruction and quiet wall/RSS cells for the Mac.
4. After MAC-R-04, record D15: adopt only if ≥5% faster cold in a quiet run.

**Acceptance**

- [ ] A mimalloc btrcc passes the bootstrap fixed point and the corpus
- [ ] Its output is byte-identical to system malloc
- [ ] The draft PR is green on ci.yml, macos.yml and windows.yml (flake change)
- [ ] D15 recorded with MAC-R-04 numbers

**Risks**

- A flake.lock change invalidates every worktree's btrcc key; coordinate with the nix owner and the other lanes.

<a id="cl-r-14"></a>

##### CL-R-14 · M10 pool qualification: hot-lock wait/hold counters, TSan run, and real-thread stress of the stdlib concurrency contracts

- **Owner:** Claude · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-m10-pool-qualification`
- **Depends on:** [CL-R-08](#cl-r-08); [CL-R-11](#cl-r-11)
- **Why not now:** Stage 7 opens after Stage 6; the counters land in ModuleUnits.btrc after CL-R-11.
- **Parallel-safe with:** CL-R-09, CL-R-12, CL-R-13

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc (counters, after CL-R-11)
- src/compiler/python/application/modules.py (counters)
- `src/tests/stdlib/ConcurrencyStress*.btrc` (new)
- src/tests/python/test_m10_pool.py (new)
- tools/runbook/presets/stage7-m10.toml

**Must not touch**

- `src/stdlib/GUI/**`
- `src/stdlib/UI/**`
- `src/runtime/c/**` (unless a defect needs a D14 re-capture as its own commit)

**Steps**

1. Add wait/hold counts and times for the pool's hot locks to the BTRC_TIMING worker lines in both compilers.
2. Run TSan: clang -fsanitize=thread btrcc on Linux, or record unavailability.
3. Write stress fixtures composed in the M11a compiler fixture: contention, producer/consumer races, full and empty queues, shutdown while blocked, worker failure, exactly-once completion with managed payload destruction.
4. BackgroundJobs is a compiler import, so build this lane's own btrcc and run bootstrap.
5. Write the worker-sweep preset.

**Acceptance**

- [ ] Stress fixtures pass 1,000 iterations under TSan with zero reports, or TSan unavailability is recorded
- [ ] Counters appear in both compilers' worker lines; tools/perf.py worker_phase_times parses them
- [ ] Bootstrap fixed point holds
- [ ] MAC-R-04: worker table with peak RSS and ≥1.5× at 4 workers on cold BTRSmith, or a revised default

**Risks**

- TSan on a self-hosted compiler may flag benign ARC races; triage before suppressing anything.

#### Stage 8: Reference compiler M11 budgets (Python track)

<a id="cl-r-15"></a>

##### CL-R-15 · Reference compiler frontend cache (F) and shared positions/codec (S0)

- **Owner:** Claude · **Group:** R · **Stage:** 8 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-ref-frontend-cache`
- **Depends on:** [CL-R-08](#cl-r-08)
- **Why not now:** Stage 8 depends on Stage 6 (CL-R-08).
- **Parallel-safe with:** CL-R-09, CL-R-10, CL-R-11, CL-R-12, CL-R-17

**Owned paths**

- src/compiler/python/frontend/sources.py
- src/compiler/python/frontend/imports.py
- src/compiler/python/artifacts/cache.py
- src/compiler/python/syntax/ast/codec.py
- src/tests/python/test_reference_frontend_cache.py (new)

**Must not touch**

- src/compiler/python/parser/parser.py (C lanes)
- src/compiler/python/application/modules.py (CL-R-11 and CL-R-16 queue)
- `src/compiler/btrc/**`

**Steps**

1. F: a reference lex+parse cache keyed on source identity, stored under the compiler cache.
2. S0: shared positions and an AstJsonCodec extension for records, serially.
3. Check that cached and uncached `--emit-ast` renders are identical on every corpus program.
4. Run verify mode and check byte identity of reference units against their own previous output.

**Acceptance**

- [ ] Canonical renders identical cached vs uncached on all corpus programs
- [ ] Verify mode passes on every corpus program; reference units byte-identical to the pre-change output
- [ ] MAC-R-05: reference lex+parse ≤3 s per edit

**Risks**

- Cache invalidation must cover source macros and native imports; CL-R-09 rows apply.

<a id="cl-r-16"></a>

##### CL-R-16 · Reference Stage B slices (validation, generics, realtime) as codecs plus replay, and the modules.py wiring

- **Owner:** Claude · **Group:** R · **Stage:** 8 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-ref-stageb`
- **Depends on:** [CL-R-15](#cl-r-15); [CL-R-11](#cl-r-11)
- **Why not now:** Needs S0 (CL-R-15), and the setjmp Python half must land in modules.py first (CL-R-11).
- **Parallel-safe with:** CL-R-12, CL-R-13, CL-R-17

**Owned paths**

- src/compiler/python/analyzer/generics.py
- src/compiler/python/analyzer/realtime.py
- src/compiler/python/analyzer/statements.py (validation owner)
- src/compiler/python/application/modules.py
- src/tests/python/test_reference_stageb.py (new)

**Must not touch**

- `src/compiler/btrc/**` (read btrcc's ValidationRecordCodec only)
- src/compiler/python/parser/parser.py

**Steps**

1. Three slice agents write only the codecs and replay in their analyzer modules.
2. One modules.py owner wires the slices in order.
3. Two adversarial reviewers per slice: one diffs verify mode against clean builds; one cross-reads btrcc's ValidationRecordCodec.

**Acceptance**

- [ ] Verify mode passes on all corpus programs and on a Linux BTRSmith clone
- [ ] Reference units byte-identical to their own pre-change output
- [ ] Counters show each slice reused on the edit fixtures

**Risks**

- Replay order bugs show up only in verify mode on large programs; run it on BTRSmith, not just the corpus.

<a id="cl-r-17"></a>

##### CL-R-17 · Reference cold path: one serial cProfile, then hotspot cuts including the reference generic-allocation work, plus the stage8-reference preset

- **Owner:** Claude · **Group:** R · **Stage:** 8 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-ref-cold`
- **Depends on:** [CL-R-08](#cl-r-08)
- **Why not now:** Stage 8 depends on Stage 6 (CL-R-08).
- **Parallel-safe with:** CL-R-09, CL-R-15, CL-R-16

**Owned paths**

- src/compiler/python/ir/lowering/calls.py
- src/compiler/python/ir/lowering/generics.py
- src/compiler/python/ir/lowering/storage.py (if the profile names it)
- tools/runbook/presets/stage8-reference.toml

**Must not touch**

- src/compiler/python/application/modules.py
- src/compiler/python/parser/parser.py
- `src/compiler/btrc/**`

**Steps**

1. Run one serial cProfile of the reference cold transpile on a Linux BTRSmith clone, using tools/perf.py --cprofile from CL-R-06.
2. Assign 2-3 agents, one per hotspot module named by the profile. Profile `_binding_conflicts_with_type` before treating it as hot (PLAN Corrections).
3. Keep units byte-identical.
4. Write stage8-reference.toml: edit, cold, peak and the 1/2/4-worker table.

**Acceptance**

- [ ] Reference units byte-identical on the corpus and BTRSmith
- [ ] Before/after cProfile table per cut
- [ ] MAC-R-05: cold transpile ≤180 s, cold dev ≤210 s, peak ≤2 GiB

**Risks**

- Python-level cuts may not reach the 180 s target; D11 stopping rule.

#### Stage 9: Stage B completion and M11 closure on the Mac

<a id="cl-r-18"></a>

##### CL-R-18 · Stage B slice 4: consulted-fact reuse keys from the CL-R-04 spec (paired, one commit)

- **Owner:** Claude · **Group:** R · **Stage:** 9 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-stageb-slice4`
- **Depends on:** [CL-R-09](#cl-r-09); [CL-R-16](#cl-r-16); [MAC-R-04](owner.md#mac-r-04); [MAC-R-05](owner.md#mac-r-05)
- **Why not now:** Stage 9 depends on Stages 7-8 and D15.
- **Parallel-safe with:** CL-R-23

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc
- src/compiler/python/application/modules.py
- src/compiler/btrc/analyzer/Models.btrc
- src/compiler/python/analyzer/program.py

**Must not touch**

- `src/language/**`
- both parsers
- tools/native_plan.py

**Steps**

1. A btrc agent and a Python agent implement the consulted-fact keys from the CL-R-04 spec in one commit.
2. Two adversarial reviewers re-run the invalidation table against the implementation.
3. Bootstrap; run zero-warning self-host transpiles.

**Acceptance**

- [ ] Every CL-R-09 invalidation test passes in both compilers
- [ ] Units byte-identical when consulted facts are unchanged
- [ ] Bootstrap fixed point holds; CI green on the draft PR

**Risks**

- Key misses cost speed and key over-reuse costs correctness; the invalidation table is the guard.

<a id="cl-r-19"></a>

##### CL-R-19 · Skip-unchanged journal: analysis and lowering of unchanged groups skipped, plus fall-back, counters and edit-sequence harness (paired); freeze the journal spec

- **Owner:** Claude · **Group:** R · **Stage:** 9 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-stageb-skip-unchanged`
- **Depends on:** [CL-R-18](#cl-r-18)
- **Why not now:** After slice 4 (CL-R-18).
- **Parallel-safe with:** CL-R-23

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc
- src/compiler/python/application/modules.py
- src/compiler/btrc/analyzer/Analyzer.btrc
- src/compiler/python/analyzer/analyzer.py
- docs/design/stage-b-reuse-keys.md (freeze marker)

**Must not touch**

- both parsers
- `src/language/**`

**Steps**

1. The same pair implements the journal from the spec.
2. A missing or incomplete journal falls back to full analysis, visibly in the counters.
3. Two adversarial reviewers try to break it with the edit-sequence harness.
4. Mark the journal spec frozen: later memo caches must extend it.

**Acceptance**

- [ ] For each of the three body-edit fixtures, in both compilers: exactly one source group analyzed and lowered, none re-lowered, only dependency-justified native compiles plus one link (on the stand-in and a Linux BTRSmith clone)
- [ ] Fall-back green in the edit-sequence harness
- [ ] Bootstrap fixed point holds; CI green

**Risks**

- Shared specialization and registration changes must be counted and explained, not hidden.

<a id="cl-r-20"></a>

##### CL-R-20 · 10-executable warm batch in both compilers, plus BTRSmith's test-batch Make target

- **Owner:** Claude · **Group:** R · **Stage:** 9 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-batch-10`; `btrsmith-test-batch`
- **Depends on:** [CL-R-18](#cl-r-18); [CL-R-19](#cl-r-19)
- **Why not now:** After slice 4; it shares the ModuleUnits/modules.py hotspot with CL-R-19.
- **Parallel-safe with:** CL-R-21, CL-R-23

**Owned paths**

- src/compiler/btrc/cli/Driver.btrc
- src/compiler/btrc/pipeline/Pipeline.btrc
- src/compiler/python/cli/compiler.py
- src/compiler/python/application/compiler.py
- tools/bench/btrsmith-batch.json
- btrsmith:make/Suites.mk
- btrsmith:make/Targets.mk

**Must not touch**

- tools/native_plan.py
- `btrsmith:src/**`

**Steps**

1. Three agents: btrc emitter and keys; Python emitter and keys; the batch manifest.
2. The BTRSmith Make-graph owner adds a test-batch target that builds and runs the D10 manifest's ten entries in parallel.
3. Prove shared reuse with counters.

**Acceptance**

- [ ] Both compilers build the ten entries with shared reuse visible in counters (Linux)
- [ ] BTRSmith `make test-batch` builds and runs all ten
- [ ] MAC-R-06: ≤60 s self-host and ≤120 s reference

**Risks**

- CatalogSongPagingParity links sqlite through pkg-config; the Linux CI needs it.

<a id="cl-r-21"></a>

##### CL-R-21 · Cold release: module units plus LTO (emitter pair, LTO in native_plan) within the runtime guardrail

- **Owner:** Claude · **Group:** R · **Stage:** 9 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `perf-cold-release`
- **Depends on:** [CL-R-18](#cl-r-18); [CL-R-13](#cl-r-13)
- **Why not now:** After slice 4 and D15 (CL-R-13).
- **Parallel-safe with:** CL-R-20, CL-R-23

**Owned paths**

- tools/native_plan.py
- src/compiler/btrc/ir/Emitter.btrc
- src/compiler/python/backend/c_emitter.py

**Must not touch**

- ModuleUnits.btrc and modules.py (CL-R-19)

**Steps**

1. The emitter pair adds release-mode module units; the native owner adds LTO.
2. Run the release runtime benchmarks: `make bench-check` for sizes and parity, plus BTRSmith release runtime numbers.

**Acceptance**

- [ ] BTRSmith release suite green through module units plus LTO on Linux
- [ ] Runtime guardrail: median slowdown ≤5% and executable size ≤+10%
- [ ] MAC-R-06: cold release ≤90 s

**Risks**

- LTO differs between ld64 and lld; macOS proof comes from the draft-PR macos.yml and the Mac.

<a id="cl-r-22"></a>

##### CL-R-22 · Product integration, then BTRSmith dev mode: module units in dev builds (D9), selfhost as default dev frontend (D16), issue #1 evidence, plus the stage9-acceptance preset

- **Owner:** Claude · **Group:** R · **Stage:** 9 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `perf-product-integration`; `btrsmith-dev-mode`
- **Depends on:** [CL-R-19](#cl-r-19); [CL-R-20](#cl-r-20); [CL-R-21](#cl-r-21); [CL-R-23](#cl-r-23)
- **Why not now:** After the Stage B, batch and cold-release lanes; budget_bench is free after CL-R-23.

**Owned paths**

- btrsmith:make/Config.mk
- btrsmith:make/Product.mk
- btrsmith:make/Toolchain.mk
- btrsmith:flake.nix
- btrsmith:flake.lock
- tools/budget_bench.py (--entry make parity)
- tools/runbook/presets/stage9-acceptance.toml

**Must not touch**

- `src/compiler/**`
- `btrsmith:src/**`

**Steps**

1. Dev builds pass --module-units (D9). Switch the default dev frontend to selfhost at the Stage 9 exit (D16).
2. Run the dev and release suites back to back without a clean on Linux.
3. Write the stage9-acceptance preset: Stage B counter fixtures, batch, cold release, product-Make medians against budget_bench, dev/release, and BTRSmith requalification.
4. After MAC-R-06, post evidence on btrsmith#1 and close it (standing approvals). Push the dev-mode pin.

**Acceptance**

- [ ] BTRSmith `make check` in dev mode then release mode, without a clean between, green on Linux
- [ ] MAC-R-06: product-Make medians within 5% of budget_bench
- [ ] Evidence comment on btrsmith#1; issue closed

**Risks**

- D16's selfhost switch exposes any remaining frontend gap in BTRSmith's full suite.

#### Stage 10: x86_64 NixOS acceptance host (remote lane, starts whenever the host exists)

<a id="cl-r-23"></a>

##### CL-R-23 · Committed host manifests embedded in budget_bench JSON (the x86_64 acceptance workflow is CL-R-49)

- **Owner:** Claude · **Group:** R · **Stage:** 10 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 4 agent-hours
- **PLAN items:** `qualification-acceptance-hosts`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-02, CL-R-04, CL-R-05, CL-R-06, CL-R-36, CL-R-37

> **Review change:** Split (§10 P15): the dispatch workflow moved to `CL-R-49`, which waits for D7's FRACTAL-NORTH probe (`MAC-R-07`) and the Stage 5 baseline (`MAC-R-02`). This half measures nothing and stays start-now.

**Owned paths**

- tools/qualification/hosts/mac-m1-max.toml
- tools/qualification/hosts/gh-ubuntu-24.04-x86_64.toml
- tools/qualification/hosts/fractal-north.toml
- tools/budget_bench.py (host-manifest embedding)
- src/tests/python/test_acceptance_hosts.py (new)

**Must not touch**

- .github/workflows/ci.yml, macos.yml, windows.yml (CL-R-36, CL-R-38)
- `src/compiler/**`

**Steps**

1. Define a host-manifest schema with CPU model, logical/physical cores, RAM, toolchain and the instruction counter. budget_bench embeds the matching manifest, selected by HostProvenance.summary, in report.json.
2. Ingest a budget_bench report with its manifest through tools.qualification (dry run on the cloud host).

**Acceptance**

- [ ] test_acceptance_hosts.py passes; `python3 -m tools.qualification ingest --budget-bench report.json` succeeds

<a id="cl-r-49"></a>

##### CL-R-49 · x86_64 acceptance workflow on the host D7's probe selects (acceptance-x86.yml)

- **Owner:** Claude · **Group:** R · **Stage:** 10 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `tooling-x86-acceptance-host`; `perf-nixos-acceptance`
- **Depends on:** [CL-R-23](#cl-r-23); [MAC-R-07](owner.md#mac-r-07); [MAC-R-02](owner.md#mac-r-02); [CL-UIA-02](#cl-uia-02)
- **Why not now:** D7: the FRACTAL-NORTH probe (MAC-R-07) decides the host; the ≥10× ratio needs the Stage 5 baseline SHA (MAC-R-02).

> **Review change:** New (§10 P15): the workflow half of the old `CL-R-23`.

**Owned paths**

- .github/workflows/acceptance-x86.yml (new; the dispatch-only class in test_ci_workflow_contracts.py)
- src/tests/python/test_ci_workflow_contracts.py (this workflow's row; shared append-only)

**Must not touch**

- docs/design/plan-reference.md
- .github/workflows/ci.yml, macos.yml, windows.yml
- `src/compiler/**`

**Steps**

1. The dispatch-only workflow runs on ubuntu-24.04 when MAC-R-07's probe fails D7's bar, or on the self-hosted nixos-x86-acceptance label when it passes. It builds the frozen baseline compiler (SHA input, the Stage 5 record) and the current btrcc with clang -O2.
2. It probes `perf stat -e instructions:u`; if unavailable, it counts with cachegrind Ir at --jobs 1, recorded as a distinct counter (§7 Q27).
3. It runs self-compile, corpus and stand-in scenarios with repeats. No BTRSmith workload runs in btrc's public workflows (§7 Q28); that row runs in BTRSmith's CI (CL-R-37).
4. Ingest through tools.qualification; publish a separate Linux table; compute the ≥10× ratio against the baseline built on the same image. Later, rerun CL-R-14's stress on real threads (M10 host qualification).

**Acceptance**

- [ ] `gh workflow run acceptance-x86.yml --ref main -f baseline=<sha>` uploads report.json with the host manifest and counter name, ≥3 repeats (run id)
- [ ] The ≥10× ratio row is computed for self-compile and corpus; ≥16-CPU wall rows are recorded as awaiting hardware with the exact command (D7)

**Risks**

- Hosted runners usually expose no PMU, so the cachegrind fallback is about 50× slower.
- Shared-runner wall clock is noise, so only counters and peaks gate.

#### Stage 11: Bounded final push A, the edit path (D11)

<a id="cl-r-24"></a>

##### CL-R-24 · Stage 11 Lane Q step 1: records pack (paired), plus the stage11-remeasure and stage12-profile presets

- **Owner:** Claude · **Group:** R · **Stage:** 11 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-records-pack`
- **Depends on:** [CL-R-19](#cl-r-19); [MAC-R-06](owner.md#mac-r-06)
- **Why not now:** Stage 11 follows the Stage 9 freeze of the journal (CL-R-19) and the M11 acceptance (MAC-R-06).
- **Parallel-safe with:** CL-R-26, CL-R-28

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc
- src/compiler/python/application/modules.py
- src/compiler/btrc/analyzer/Models.btrc
- tools/runbook/presets/stage11-remeasure.toml
- tools/runbook/presets/stage12-profile.toml

**Must not touch**

- both parsers
- `src/language/**`
- tools/native_plan.py

**Steps**

1. Two adversarial reviewers add invalidation rows before implementation.
2. Pack the records in both compilers, recorded in the frozen journal.
3. Keep units byte-identical; run verify gates and bootstrap.
4. Write the remeasure preset (all Stage 11 rows) and the profile preset (macOS `sample` call graphs plus instructions for the Stage 12 hotspots).

**Acceptance**

- [ ] Each compiler's units byte-identical to its own output; bootstrap fixed point; new invalidation rows pass
- [ ] MAC-R-08: records plus g-transitive ≤0.4 s (from 1.42 s)

**Risks**

- Serial hotspot queue; CL-R-25 and CL-R-31 wait.

<a id="cl-r-25"></a>

##### CL-R-25 · Stage 11 Lane Q step 2: declaration-session cache (two codec agents from one schema note, then wiring; paired)

- **Owner:** Claude · **Group:** R · **Stage:** 11 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-decl-session-cache`
- **Depends on:** [CL-R-24](#cl-r-24)
- **Why not now:** Serial after the records pack (CL-R-24).
- **Parallel-safe with:** CL-R-26, CL-R-28

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc
- src/compiler/python/application/modules.py
- src/compiler/btrc/analyzer/Declarations.btrc
- src/compiler/python/analyzer/declarations.py

**Must not touch**

- both parsers
- `src/language/**`

**Steps**

1. Write one schema note; two codec agents implement it, one per compiler; one wiring agent connects it.
2. Adversarial reviewers add invalidation rows.
3. Verify against live lowering.

**Acceptance**

- [ ] Declaration session reuse verified against live lowering on the corpus and BTRSmith; bootstrap fixed point
- [ ] MAC-R-08: declarations session ≤0.2 s

**Risks**

- Session staleness across stdlib changes; key on the stdlib lock.

<a id="cl-r-26"></a>

##### CL-R-26 · Stage 11 Lane F: durable cache-store API (BTRC_CACHE_DIR), then Visibility/imports and NativeImports/native_imports reuse (paired)

- **Owner:** Claude · **Group:** R · **Stage:** 11 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-frontend-durable`
- **Depends on:** [CL-R-19](#cl-r-19); [MAC-R-06](owner.md#mac-r-06)
- **Why not now:** Stage 11 follows Stage 9.
- **Parallel-safe with:** CL-R-24, CL-R-25, CL-R-28

**Owned paths**

- src/compiler/btrc/frontend/Models.btrc
- src/compiler/btrc/cli/Driver.btrc
- src/compiler/python/artifacts/cache.py
- src/compiler/btrc/frontend/Visibility.btrc
- src/compiler/python/frontend/imports.py
- src/compiler/btrc/frontend/NativeImports.btrc
- src/compiler/python/frontend/native_imports.py

**Must not touch**

- ModuleUnits.btrc and modules.py (Lane Q)
- tools/NativeHeaderReader.cpp

**Steps**

1. Land the durable store API serially, both compilers.
2. Then two agents: Visibility with imports.py; NativeImports with native_imports.py.
3. Add corruption and interruption tests to the store (extend CL-R-09 modules).

**Acceptance**

- [ ] Store survives kill and corruption tests; both compilers produce identical outputs cached vs uncached
- [ ] macos.yml unit shard green (native imports run on macOS)
- [ ] MAC-R-08: visibility plus n-import ≤0.15 s; no-op ≤1.0 s

**Risks**

- The SDK-reader session identity must stay in the key (macOS only).

<a id="cl-r-27"></a>

##### CL-R-27 · Stage 11 Lane F: parse-cache decoder prototype (go/no-go), then implementation (btrc-internal)

- **Owner:** Claude · **Group:** R · **Stage:** 11 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-parse-cache`
- **Depends on:** [CL-R-26](#cl-r-26)
- **Why not now:** After the durable store (CL-R-26).
- **Parallel-safe with:** CL-R-24, CL-R-25, CL-R-28

**Owned paths**

- src/compiler/btrc/frontend/SourceIo.btrc
- `src/compiler/btrc/syntax/**` (decoder only)
- src/tests/btrc/test_parse_cache.py (new)

**Must not touch**

- src/compiler/btrc/parser/Parser.btrc (C lanes)
- `src/compiler/python/**`

**Steps**

1. Prototype the decoder and record go/no-go with instruction evidence from MAC-R-08.
2. If go, implement with btrcc output byte-identical to its own previous output.

**Acceptance**

- [ ] Go/no-go recorded
- [ ] If go: identical canonical renders and units; MAC-R-08 lex+parse ≤0.3 s
- [ ] If no-go: numbers recorded in PLAN.md

**Risks**

- Decoding may cost as much as parsing.

<a id="cl-r-28"></a>

##### CL-R-28 · Stage 11 Lane N: edit-path native link and cold native, one commit in tools/native_plan.py

- **Owner:** Claude · **Group:** R · **Stage:** 11 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `perf-native-link`; `perf-cold-native`
- **Depends on:** [CL-R-21](#cl-r-21); [MAC-R-06](owner.md#mac-r-06)
- **Why not now:** Stage 11 follows Stage 9; native_plan.py is held by CL-R-21 until it lands.
- **Parallel-safe with:** CL-R-24, CL-R-25, CL-R-26

**Owned paths**

- tools/native_plan.py
- `src/tests/python/test_native_plan*.py`

**Must not touch**

- `src/compiler/**`

**Steps**

1. Make the edit link incremental where the platform allows; cold-native scheduling cuts.
2. Keep `make test-debug` passing: debug maps and source maps intact.

**Acceptance**

- [ ] `make test-debug` passes on macOS (draft PR) and Linux
- [ ] MAC-R-08: edit link ≤0.2 s and cold native ≤8 s

**Risks**

- ld64-specific link reuse leaves the Linux relink as a recorded host-unsupported path.

<a id="cl-r-29"></a>

##### CL-R-29 · Resident compiler, only if D12 = go (both compilers, protocol and tests)

- **Owner:** Claude · **Group:** R · **Stage:** 11 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-resident-compiler`
- **Depends on:** [CL-R-08](#cl-r-08); [CL-R-26](#cl-r-26)
- **Why not now:** Built only if CL-R-08 records D12 = go; after the durable store (CL-R-26).
- **Parallel-safe with:** CL-R-24, CL-R-28

**Owned paths**

- `src/compiler/btrc/cli/**` (resident entry, if approved)
- src/compiler/python/cli/compiler.py
- docs/design/resident-compiler.md (new)
- src/tests/python/test_resident_compiler.py (new)

**Must not touch**

- the 88/97 file inventories without integrator approval (a new compiler file changes test_compiler_structure_contract.py)

**Steps**

1. One design agent; then a serial core plus one protocol-and-tests agent; both compilers (no parity exception).
2. Wall clock is measured on the quiet queue (MAC-R-08).

**Acceptance**

- [ ] Design approved by two adversarial reviewers and one parity reviewer
- [ ] Resident builds byte-identical to cold builds; crash and stale-state tests pass
- [ ] Quiet edit wall-clock reported

**Risks**

- A compiler file inventory change; the structure contract must be updated by the integrator.

#### Stage 12: Bounded final push B, cold path and memory (conditional tiers)

<a id="cl-r-30"></a>

##### CL-R-30 · Stage 12 declaration and lowering hotspot cuts (4 btrc owners plus the Python calls.py check)

- **Owner:** Claude · **Group:** R · **Stage:** 12 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-decl-lowering-hotspots`
- **Depends on:** [MAC-R-08](owner.md#mac-r-08); [CL-R-25](#cl-r-25)
- **Why not now:** Needs the Stage 12 profile (MAC-R-08); lands after the journal freeze, never interleaved with journal work.
- **Parallel-safe with:** CL-R-32

**Owned paths**

- src/compiler/btrc/ir/lowering/Calls.btrc
- src/compiler/btrc/ir/lowering/CallableFlow.btrc
- src/compiler/btrc/ir/lowering/Callables.btrc
- src/compiler/btrc/analyzer/ownership/Cycles.btrc
- src/compiler/python/ir/lowering/calls.py

**Must not touch**

- ModuleUnits.btrc and modules.py
- both parsers

**Steps**

1. Four agents with exact paths: CallTargetResolver.resolve, CallableFlowState.applyEvaluation, CallableValueSemantics.expressionAbi, CycleSemantics.reaches.
2. Profile the Python `_binding_conflicts_with_type` first.
3. Every memo gets an adversarial reviewer's sign-off that its lookups are journaled.

**Acceptance**

- [ ] Each kept cut saves ≥1% instructions at --jobs 1 (MAC-R-08 rerun) and is recorded in the journal; rejected cuts recorded with numbers
- [ ] Byte-identical units; bootstrap fixed point

**Risks**

- Leaf-sample share is not speedup (rejected-experiments list); require instruction deltas.

<a id="cl-r-31"></a>

##### CL-R-31 · Stage 12 parallel analysis (paired, one commit): protocol core, journal-completeness auditors, test authors

- **Owner:** Claude · **Group:** R · **Stage:** 12 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-parallel-analysis`
- **Depends on:** [CL-R-24](#cl-r-24); [CL-R-25](#cl-r-25); [CL-R-10](#cl-r-10)
- **Why not now:** Runs after Lane Q drains (CL-R-24, CL-R-25).
- **Parallel-safe with:** CL-R-30, CL-R-32

**Owned paths**

- src/compiler/btrc/pipeline/ModuleUnits.btrc
- src/compiler/python/application/modules.py
- src/compiler/btrc/analyzer/Analyzer.btrc
- src/compiler/python/analyzer/analyzer.py
- src/tests/python/test_parallel_analysis.py (new)

**Must not touch**

- both parsers
- `src/runtime/c/**`

**Steps**

1. Serial protocol core first.
2. 3-4 read-only journal-completeness auditors.
3. Two test authors share one worktree.
4. Land the btrc and Python halves in one commit.

**Acceptance**

- [ ] Determinism tier (`make test-determinism`) green: identical output across workers and shuffles
- [ ] MAC-R-08 quiet run: cold transpile ≤25 s at 4 workers; aggregate memory ≤6 GiB

**Risks**

- The Python half may not speed up under the GIL; record that as a distance.

<a id="cl-r-32"></a>

##### CL-R-32 · Stage 12 conditional-tier gate: attribute the profile and decline or design each of borrowed returns, M9 arena, thread-confined ARC and M8b

- **Owner:** Claude · **Group:** R · **Stage:** 12 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `perf-borrowed-returns`; `perf-m9-arena`; `perf-arc-thread-confined`; `perf-m8b`
- **Depends on:** [MAC-R-08](owner.md#mac-r-08)
- **Why not now:** Needs the Stage 12 profile (MAC-R-08).
- **Parallel-safe with:** CL-R-30, CL-R-31

**Owned paths**

- PLAN.md (tier decisions)
- docs/design/arc-runtime.md (design notes for triggered ARC tiers)
- docs/design/stage12-tiers.md (new)

**Must not touch**

- `src/**`

**Steps**

1. For each tier, compute its share of a still-open row's cost: ≥5% triggers it (standing approvals); M8b needs D17's 20%.
2. Decline untriggered tiers with numbers.
3. For triggered tiers: one design agent, then 4 read-only auditors.
4. M8b ordering: D17 required it before Stage 15, which already landed. Propose it after Stage 21 or decline (open question 6).

**Acceptance**

- [ ] Each tier recorded as declined with numbers or as triggered with an approved design
- [ ] PLAN.md updated

**Risks**

- Profile attribution across fat-node construction is diffuse.

<a id="cl-r-33"></a>

##### CL-R-33 · Stage 12 conditional implementation: borrowed returns and thread-confined ARC (only if triggered; runtime/c single owner; D14 re-capture)

- **Owner:** Claude · **Group:** R · **Stage:** 12 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-borrowed-returns`; `perf-arc-thread-confined`
- **Depends on:** [CL-R-32](#cl-r-32)
- **Why not now:** Only if CL-R-32 triggers a tier.
- **Parallel-safe with:** CL-R-30

**Owned paths**

- `src/runtime/c/**` (single owner)
- src/runtime/c/manifest.toml
- `src/compiler/btrc/ir/lowering/ownership/**`
- src/compiler/python/ir/lowering/ownership.py
- src/tests/fixtures/compiler_boundaries/manifest.toml (D14 re-capture)

**Must not touch**

- `src/stdlib/**`
- both parsers

**Steps**

1. Serial btrc/Python pair implementation.
2. One D14 re-capture per commit, with the reason recorded.
3. Measure only in quiet windows.

**Acceptance**

- [ ] ARC witness and sanitizer suites green; bootstrap fixed point; boundary-check re-captured with reasons
- [ ] Quiet MAC-R-08 rerun shows the tier's exit met, or it is reverted and declined

**Risks**

- Runtime ARC changes are the highest-risk compiler change; full matrix plus the macOS and Windows runners.

<a id="cl-r-34"></a>

##### CL-R-34 · Stage 12 conditional implementation: M9 arena and M8b per-kind nodes (only if triggered)

- **Owner:** Claude · **Group:** R · **Stage:** 12 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `perf-m9-arena`; `perf-m8b`
- **Depends on:** [CL-R-32](#cl-r-32); ext:ccompat-c5-docs-final (Stage 21) for M8b → [CL-C-40](#cl-c-40)
- **Why not now:** Only if CL-R-32 triggers a tier. M8b must not collide with the C2/C3 schema commits.

**Owned paths**

- tools/compiler_codegen/ast.py (M8b, hotspot)
- src/compiler/btrc/generated/ast/Node.btrc (regenerated only)
- src/compiler/btrc/syntax/Identity.btrc (M8b)
- src/runtime/c/core.c (arena, if M9)

**Must not touch**

- src/language/ast.asdl during C-track schema commits

**Steps**

1. M8b: one serial vertical slice, then 4 agents by package directory, using renamed readers as the compile-error oracle, merging serially.
2. M9: one design agent, auditors, then a btrc/Python pair.
3. Measure only in quiet windows.

**Acceptance**

- [ ] Byte-identical units per compiler; bootstrap fixed point; generated-source check clean
- [ ] The quiet run meets the tier's exit, or the tier is declined with sign-off

**Risks**

- M8b conflicts with any in-flight ASDL work; schedule it after Stage 21.

#### Stage 13: Bucket-1 exit qualification

<a id="cl-r-35"></a>

##### CL-R-35 · Stage 13 tables and D11 row dispositions (Mac and x86_64), marking bucket 1 done

- **Owner:** Claude · **Group:** R · **Stage:** 13 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `perf-final-qualification`
- **Depends on:** [MAC-R-09](owner.md#mac-r-09); [CL-R-23](#cl-r-23); [CL-R-49](#cl-r-49)
- **Why not now:** Needs the final Mac evidence (MAC-R-09) and the x86_64 tables (CL-R-23).

> **Review change:** Cites the x86_64 ≥10× rows, so it also waits for `CL-R-49` (§10 P15).

**Owned paths**

- PLAN.md (bucket-1 row, Stage 13 progress)
- docs/design/compile-performance.md (final tables)
- docs/design/separate-compilation.md

**Must not touch**

- `src/**`
- docs/design/plan-reference.md

**Steps**

1. A docs agent drafts the tables from JSON while the gates run.
2. Cite each D11 row as met or formally revised, with measured value, profile evidence and the next lever.
3. Cite the ≥10× ratio per required host (Mac; x86_64 per D7).

**Acceptance**

- [ ] PLAN.md bucket-1 row marked done, with each row cited
- [ ] `git diff --check` clean

**Risks**

- The x86_64 instruction counter differs (cachegrind); state it beside each ratio.

#### Stage 16: C1 constructs, then C4 (approved, D19)

<a id="cl-c-01"></a>

##### CL-C-01 · ccompat-c1-integrate: C1 exit proofs on the merged tree, per-construct parity review of r03/r19/r07, deferral hand-off (IN FLIGHT)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 16 · **Environment:** Linux cloud · **Start now:** in flight · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-c1-integrate`
- **Depends on:** none
- **Parallel-safe with:** CL-C-00, CX-C-01

**Owned paths**

- src/tests/btrc/fixtures/c_compat_probe/c1.toml
- src/tests/btrc/test_c_compatibility_inventory.py
- src/tests/btrc/test_c_compatibility_refusals.py
- src/tests/btrc/test_c_compatibility_bodies.py
- src/tests/btrc/test_c_compatibility_function_pointers.py
- src/tests/btrc/test_c_compatibility_integration.py
- src/tests/c_compat/ (C1 programs and expected/)
- docs/design/c-compatibility.md (Stage 16 sections)
- docs/known-language-gaps.md (C rows 1, 3, 5, 7, 19)
- src/compiler/python/parser/parser.py and src/compiler/btrc/parser/Parser.btrc (shared parser rule, only for confirmed findings)
- fix sites a parity reviewer confirms in src/compiler/python/{analyzer,ir} and src/compiler/btrc/{analyzer,ir}

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**` (Codex-owned under D27)
- src/stdlib/btrc.symbols, src/stdlib/btrc.lock, src/devex/lsp/catalog/generated.py, btrc.toml exports (integrator-derived)
- generated files (src/compiler/python/syntax/ast/generated.py, src/compiler/python/abi/generated.py, `src/compiler/btrc/generated/**`) except by regeneration
- `src/runtime/c/**`
- `src/tests/fixtures/compiler_boundaries/**`
- `src/language/**` (no schema change in this packet)

**Steps**

1. Lane stage16/c1-integrate (already running) from 8b73c79, with its own btrcc built under the btrcc-build semaphore.
2. Re-run c1.toml through both compilers. Every row 1-7 positive must be accepted with identical output, and every negative must give an identical diagnostic and position. KNOWN_DIVERGENCES must hold no C1 entry.
3. One parity reviewer each for r03 (multi-declarators), r19 (for-header comma) and r07 (function-pointer declarators), as merged in batch 9 (semantics, diagnostics, ARC witnesses), reusing the lane btrcc; fix each confirmed finding in both compilers, one commit per construct.
4. Re-prove the Stage 16 exit on the merged tree: Python raw IR and btrcc C identical for braced vs braceless bodies, including multi-declarator and function-pointer bodies (test_c_compatibility_bodies.py); per-declarator ARC counts (c_compat/MultipleDeclarators.btrc); comma operands (c_compat/CommaForHeaders.btrc).
5. Update c-compatibility.md 'Stage 16 integration notes' and hand the remaining deferrals to CL-C-39 by name: catch (`string*` e) parses to different errors; a global read only through sizeof is dropped by the optimizer; const int N = 3; char t[N] = "abc" emitted as a VLA with an initializer; btrcc's discarded tuple-literal statement.
6. Lane report to the integrator (commits, test counts, deferrals).

**Acceptance**

- [ ] pytest -n 4 src/tests/btrc/test_c_compatibility_inventory.py src/tests/btrc/test_c_compatibility_refusals.py src/tests/btrc/test_c_compatibility_bodies.py src/tests/btrc/test_c_compatibility_function_pointers.py src/tests/btrc/test_c_compatibility_integration.py green through Python and cached btrcc (pass/skip counts reported)
- [ ] c1.toml: every positive accepted in both compilers; no C1 KNOWN_DIVERGENCES entry
- [ ] make test-btrc and make test-btrc-selfhost green; make generated-check, make lint, make format-check, git diff --check clean
- [ ] Zero 'warning:' lines from the reference transpiles of src/compiler/btrc/BtrccMain.btrc, cli/WindowsMain.btrc and cli/MacOSMain.btrc
- [ ] make bootstrap reaches its fixed point
- [ ] After integration and push: ci.yml, macos.yml and windows.yml green on main (run ids in the report); the Mac half is MAC-C-01

**Risks**

- CL-C-02 edits src/compiler/btrc/analyzer/validation/Expressions.btrc too; merge CL-C-01 first and rebase CL-C-02.
- A reviewer finding in r07's syntactic disambiguation would reopen parser code that C4 (B1 body sites) also edits; finish CL-C-01 before CL-C-05 starts.

<a id="cl-c-03"></a>

##### CL-C-03 · C4 spec commit ccompat-r18-spec: src/language/targets.toml, TargetManifest generator, generated target tables (no behavior change)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 16 (C4 step 1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-r18-preprocessor-conditionals` (step 1: ccompat-r18-spec)
- **Depends on:** [CL-C-01](#cl-c-01); [CL-R-00](#cl-r-00)
- **Why not now:** D18: C4 runs after ccompat-c1-integrate, never alongside it (CL-C-01 is in flight). See the open question on pulling this no-behavior commit forward to unblock Stage 24.
- **Parallel-safe with:** CL-C-04, CL-C-02, CX-C-01

> **Review change:** Waits for `CL-R-00`, which integrates the three open Stage 4 lanes before the C4 lane reserves their hotspots (§10 P2).

**Owned paths**

- src/language/targets.toml (new)
- tools/compiler_codegen/hosted_abi.py (TargetManifest)
- tools/compiler_codegen/main.py
- tools/compiler_codegen/stdlib_symbols.py
- tools/compiler_codegen/builtins.py
- src/compiler/python/abi/generated.py and src/compiler/btrc/generated/hosted_abi/Tables.btrc (regenerated only)
- src/tests/python/test_target_macro_table.py (new)
- src/tests/python/test_hosted_abi_contract.py
- AGENTS.md shared-spec list (CLAUDE.md is a symlink)
- PLAN.md shared-spec list line
- docs/design/c-preprocessor-conditionals.md (status)

**Must not touch**

- `src/compiler/python/frontend/**`, `src/compiler/btrc/frontend/**` (behavior is CL-C-05/06)
- src/language/ast.asdl, grammar.ebnf
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- src/stdlib/btrc.symbols, src/stdlib/btrc.lock (integrator regenerates)
- `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Branch stage16/c4-spec. Spec owner: the only writer of hosted_abi.py for the stage.
2. Write targets.toml exactly as c-preprocessor-conditionals.md 'Spec commit' gives it: schema_version 1; six [[targets]] rows (linux, macos, windows × x86_64, aarch64); the [[predefined_macros]] rows (OS, arch, __arm64__ macos+aarch64, __CHAR_UNSIGNED__ linux+aarch64, size, byte-order, __STDC__/__STDC_VERSION__); [conditionals] undefined_macro_names and foreign_macro_names; environments empty.
3. TargetManifest in hosted_abi.py: load, validate the eight generator rules in the HostedAbiManifestError style, and render the Python rows/tables (GeneratedTargetRow, GeneratedPredefinedMacroRow, TARGET_ROWS, TARGET_PREDEFINED_MACRO_ROWS, TARGET_UNDEFINED_MACRO_NAMES, TARGET_FOREIGN_MACRO_NAMES, TARGET_SPEC_FINGERPRINT). In btrc, GeneratedHostedAbiData gains the memoized targetRows()/predefinedMacroRows()/undefinedMacroNames()/foreignMacroNames() and targetSpecFingerprint, emitted as small methods.
4. stdlib_symbols.py and builtins.py: an owner is the union over every spec target; a per-target disagreement fails naming the file and the two targets (vacuous today).
5. test_target_macro_table.py: clang -std=c11 --target=\<triple> -dM -E for x86_64/aarch64 linux-gnu, apple-macos and w64-windows-gnu. clang must define exactly the names the table selects, with its values, and the left-out names must be absent from the table. Host gcc must agree. A missing clang is a classified skip in the skip ledger.
6. test_hosted_abi_contract.py: generator rules; generated rows equal the spec; the target rows equal PackageTarget's sets in both compilers (frontend/packages.py:55-56, frontend/Packages.btrc:34-36); __CHAR_BIT__/__SIZEOF_SHORT__/__SIZEOF_INT__/__SIZEOF_LONG_LONG__ equal both analyzers' widths for every target.
7. Add targets.toml to the shared-spec lists; one parity reviewer; lane report.

**Acceptance**

- [ ] make compiler-codegen-generate, then make generated-check clean
- [ ] pytest src/tests/python/test_hosted_abi_contract.py src/tests/python/test_target_macro_table.py green (6 triples checked, no unexplained skip in build/skip-report.json)
- [ ] make test-btrc and make test-btrc-selfhost unchanged (no behavior change)
- [ ] boundary-check: 311 records, none changed
- [ ] make bootstrap fixed point after the btrcc fixture rebuild; zero-warning transpiles of the three entries

**Risks**

- Stage 24 (bucket 3) extends targets.toml (ios/android rows, environments, triples, sysroots, data-model columns), and CL-C-23 adds C3 layout columns: one writer at a time, and the later one rebases.
- On the critical path for every iOS/Android/Windows UI lane via Stage 24.

<a id="cl-c-04"></a>

##### CL-C-04 · C4 step 2: module units carry the whole directive list in source order (fixes the existing #define/#include ordering bug)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 16 (C4 step 2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ccompat-r18-preprocessor-conditionals` (step 2: module-unit directive order)
- **Depends on:** [CL-C-01](#cl-c-01); [CL-R-00](#cl-r-00)
- **Why not now:** D18 (C4 after ccompat-c1-integrate, CL-C-01 in flight); the pipeline/ModuleUnits.btrc + application/modules.py hotspot is held by the C4 lane agent from here through CL-C-06.
- **Parallel-safe with:** CL-C-03, CL-C-02, CX-C-01

> **Review change:** Waits for `CL-R-00`, which integrates the three open Stage 4 lanes before the C4 lane reserves their hotspots (§10 P2).

**Owned paths**

- src/compiler/python/application/modules.py (hotspot)
- src/compiler/btrc/pipeline/ModuleUnits.btrc (hotspot)
- src/tests/python/test_module_units.py

**Must not touch**

- `src/compiler/*/frontend/**` (CL-C-05/06)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Branch stage16/c4-module-order (same lane agent as CL-C-05/06).
2. Python SharedDeclarations.merge_into (modules.py:726-730), trim_native_includes and runtime_module: every unit carries the program's whole directive list in source order; only identical IRIncludes are deduplicated; macros are never deduplicated.
3. btrc mirror at ModuleUnits.btrc:632-657, :698-699, :739-746.
4. Tests (both compilers): a #define CFG / #include "lib.h" pair split across groups keeps its order; each unit's directive list equals the whole-program list; every unit compiles under gcc and clang -std=c11 -pedantic-errors.
5. Lane report.

**Acceptance**

- [ ] pytest src/tests/python/test_module_units.py green (new cases through both compilers)
- [ ] Module-unit corpus sweep no worse than the Stage 18 baseline (61 passed / 8 skipped)
- [ ] make bootstrap fixed point; zero-warning transpiles; lint, format-check, generated-check clean

**Risks**

- Changes module-unit outputs for programs with directives in several groups; cache keys already cover the directive text, so stale reuse is not expected but must be checked by the warm-cache cases.

<a id="cl-c-05"></a>

##### CL-C-05 · C4 Python half: per-file #if conditioning, evaluator, macro rules, IRMacroUndef, caches, LSP, formatter, tools

- **Owner:** Claude · **Group:** C · **Stage:** Stage 16 (C4 step 3, Python half) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-r18-preprocessor-conditionals` (step 3: Python evaluator, LSP/formatter/tools)
- **Depends on:** [CL-C-03](#cl-c-03); [CL-C-04](#cl-c-04)
- **Why not now:** Needs targets.toml and generated target tables (CL-C-03) and the whole-list module-unit rule (CL-C-04).
- **Parallel-safe with:** CX-C-01, CL-C-00

**Owned paths**

- src/compiler/python/frontend/sources.py, imports.py, stage.py
- src/compiler/python/application/compiler.py, pipeline.py, modules.py (hotspot, held since CL-C-04)
- src/compiler/python/parser/parser.py (B1 body sites; shared parser rule)
- src/compiler/python/analyzer/program.py, declarations.py, expressions.py, macros.py, calls.py
- src/compiler/python/ir/nodes.py, ir/verifier.py, ir/optimizer.py, ir/lowering/translation_unit.py
- src/compiler/python/backend/c_emitter.py (hotspot)
- src/devex/lsp/workspace/units.py, cache.py, workspace.py; src/devex/lsp/features/symbols.py, completion.py; src/devex/lsp/analysis/resolution.py
- src/devex/formatter/engine.py
- tools/compiler_codegen/verification.py (selection regex)
- src/tests/python/test_corpus_strict_imports.py, test_ir_declarations.py, test_source_macro_semantic_boundary.py, test_main.py
- src/tests/btrc/test_preprocessor_conditionals.py (new; reference half)
- src/tests/c_compat/PreprocessorConditionals.btrc and expected/PreprocessorConditionals.stdout (new)
- src/tests/btrc/fixtures/c_compat_probe/c3_c4.toml (r18 rows), test_c_compatibility_inventory.py (REFUSAL_ROWS), test_c_compatibility_refusals.py
- `src/tests/lsp/**`, `src/tests/formatter/**` (C4 cases)
- docs/known-language-gaps.md (row 18), src/language/grammar.ebnf (@syntax comment block only), docs/design/compiler-structure.md (sources.py owner description)

**Must not touch**

- src/language/ast.asdl (C4 changes no ASDL)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- src/stdlib/btrc.symbols, btrc.lock, src/devex/lsp/catalog/generated.py (integrator)
- generated files except by regeneration; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**` (C4 changes no record)

**Steps**

1. Branch stage16/c4-conditionals (one lane agent for CL-C-05 and CL-C-06; nothing merges until CL-C-06 squashes both halves into one construct commit).
2. frontend/sources.py: SourceConditionals, ConditionalEnvironment, ConditionalExpression, ConditionedSource, ConditionalTest and PreprocessorConditionalError. Also: SourceFileReader's LF normalization as a class method; the fast-path candidate regex; the raw lex on the slow path; the directive walk (D/E/I/A rules, in-file M1, M3/M4, keyword and reserved-name rules); the environment built in SourceResolver.resolve from packages.native_plan.target; ResolvedSource.conditional_tests; cache_identity() gaining the program-check records.
3. Call sites: ImportResolver._open_frame conditions before scan; StdlibRepository.source_mapped, _source_without_imports, defined_names and parsed_symbol_owners; CompilationPipeline.build_stdlib_archive; frontend/stage.py verify_tests (P1-P4) after parse and before visibility; compiler.py/pipeline.py map the error to a positioned SYNTAX failure.
4. Parser B1 body sites; analyzer: SourceMacroNamespace.undefined (program.py), collect with cross-file M1, M2 and #undef records (declarations.py), _validate_mutation with M3/M4 and the BTRC_ prefix, and U1/U2 at expressions.py (:855, :1590), macros.py plan_call (:49) and calls.py defaults (:1289).
5. IR: IRMacroUndef in ir/nodes.py and preprocessor_decls; the IRVerifier check (C identifier); the optimizer skips undefs (:720-746); translation_unit.py handles #undef, U3 and D15/D17; c_emitter.py's freestanding include check tests isinstance(IRInclude).
6. LSP: FileUnit.parse LF-normalizes and conditions with the host target; conditioned_source; the unit-cache key gains the target and environment identity; dead lines get no tokens, symbols, hovers or diagnostics. Formatter regions per engine.py:974-1000 (balanced groups formatted, unbalanced kept verbatim, idempotent). Tools: verification.py skips candidate files; test_corpus_strict_imports.py conditions with the host target.
7. Tests: corpus PreprocessorConditionals.btrc (target-independent output); the ~60-row expression battery as a shared table for the btrc driver; the C oracle (~40 #if expressions selected identically to gcc and clang -std=c11 -pedantic-errors -E -P, and shape cases refused); M1-M4 and U1-U3; module units with #undef; inventory r18 rows and new probes; flipped tests test_ir_declarations.py:289 (U3), python test_source_macro_semantic_boundary.py:112-118 (U1), test_main.py:680-690 (#line 1); the LSP and formatter cases from the design's test plan item 7.
8. Docs: known-language-gaps row 18 and deviations; the grammar @syntax block; the compiler-structure.md description; then a handoff note listing every message and position for the btrc port.

**Acceptance**

- [ ] pytest src/tests/python src/tests/lsp src/tests/formatter green, plus the reference half of src/tests/btrc/test_preprocessor_conditionals.py (counts in the handoff note)
- [ ] make test-btrc green including c_compat/PreprocessorConditionals.btrc
- [ ] C-oracle selections equal gcc's and clang's for every case; shape cases refused
- [ ] Handoff note with the diagnostic table (message, line:col) the btrc port must match

**Risks**

- Holds the backend/c_emitter.py and modules.py hotspots: no other C lane runs during CL-C-05/06.
- The LSP unit-cache key change invalidates persistent editor caches (intended).
- Python counts columns in code points and btrc in bytes: keep every parity battery ASCII-only.

<a id="cl-c-06"></a>

##### CL-C-06 · C4 btrc port, cache/driver tests, single construct commit, parity review and Linux memory evidence

- **Owner:** Claude · **Group:** C · **Stage:** Stage 16 (C4 step 3, btrc half + exit) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-r18-preprocessor-conditionals` (step 3: btrc port, cache fingerprints, exit evidence except the Mac re-measure)
- **Depends on:** [CL-C-05](#cl-c-05)
- **Why not now:** Ports CL-C-05's Python half on the same branch.
- **Parallel-safe with:** CX-C-01, CL-C-00

**Owned paths**

- src/compiler/btrc/frontend/Models.btrc, Resolver.btrc, Visibility.btrc
- src/compiler/btrc/pipeline/Pipeline.btrc (hotspot), pipeline/ModuleUnits.btrc (hotspot)
- src/compiler/btrc/cli/Driver.btrc (hotspot), src/compiler/btrc/tools/FrontendMain.btrc
- src/compiler/btrc/parser/Parser.btrc (B1; shared parser rule), parser/SourceMacros.btrc
- src/compiler/btrc/analyzer/SourceMacros.btrc, analyzer/validation/Expressions.btrc, analyzer/validation/Calls.btrc
- src/compiler/btrc/ir/Model.btrc, ir/lowering/Declarations.btrc, ir/Emitter.btrc (hotspot), ir/optimization/Optimizer.btrc, ir/runtime/References.btrc, ir/runtime/Catalog.btrc
- src/tests/btrc/fixtures/ConditionalExpressionDriver.btrc (new), src/tests/btrc/fixtures/DirectiveCacheDriver.btrc
- src/tests/btrc/test_preprocessor_conditionals.py, test_parser_diagnostics.py, test_source_macro_semantic_boundary.py
- src/tests/fixtures/expected-skips/{macos,linux-devcontainer,windows}.json
- PLAN.md D20 row (evaluated-operand reading; integrator applies)

**Must not touch**

- src/language/ast.asdl
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- src/stdlib/btrc.symbols, btrc.lock, src/devex/lsp/catalog/generated.py
- generated files except by regeneration; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Port to btrc. Frontend: FeSourceConditionals, FeConditionalEnvironment and FeConditionalExpression in Resolver.btrc; the values in Models.btrc; openFrame, sourceWithoutImports, sourceAtSnapshot and definedTypeNames; FeFrontendResolver takes the environment.
2. Pipeline: CompilerPipeline.resolve builds the environment from options.target, the package graph and HostedAbiRepository's owned names with GeneratedHostedAbiData, and runs verifyTests after parse. Visibility.ensureStdlibIndex takes the union over targets. FrontendMain gets --target, and Driver renders through FeVisibilityDiagnostic.render.
3. Rest of the port: Parser B1; SourceMacros replacement() and M1 identity; analyzer SourceMacros (undefined, M1-M4, BTRC_); validation Expressions.btrc:915-934 and Calls.btrc:1039-1043, :1124; IR_PREPROCESSOR_UNDEF in Model.btrc; Declarations.btrc:4447-4452 and :4565-4605; Emitter.btrc:412-427; Optimizer.btrc:257, :459, :705; References.btrc:183; Catalog.btrc:215.
4. Drivers: ConditionalExpressionDriver.btrc runs the shared battery and is built once per btrcc fingerprint by selfhost_driver. DirectiveCacheDriver gets a conditioned mode: one raw text under two targets gives two entries, and a restore never brings back a dead import.
5. Per-target selection: FrontendMain --target T equals the reference's resolved source byte for byte for all six targets, and both emitted C files hold exactly the selected functions and #includes. Dead imports: a dead import of a missing file compiles, adds no edge, and leaves --emit-link-plan sources identical in both compilers.
6. Cache cases in both compilers (Python module_units_lowered/reused, btrcc lowered/reused): warm across a target switch equals cold; a live in-group edit re-lowers one group; a live directive edit re-lowers all groups; a dead-group edit; combined edits; ValidationRecords replay; the P3 warm variant.
7. Flip test_parser_diagnostics.py:216-221 (D4) and btrc test_source_macro_semantic_boundary.py:195-207 (U1). Add the reader-dependent skips (P2, P3 binding evidence) to expected-skips.
8. Squash both halves into one construct commit. Run one parity reviewer (semantics, positions, caches, C oracle) on the lane btrcc. Linux memory by Stage 15's method: gcc-built btrcc for parent and commit, three alternating --target linux-x86_64 --no-cache compiles of BtrccMain.btrc each, wait4 peak RSS and user CPU.
9. gh workflow run ci.yml/macos.yml/windows.yml --ref stage16/c4-conditionals, because the default host target differs per OS (__APPLE__ on macos-15, _WIN32 in the Windows native bootstrap); record the run ids; lane report.

**Acceptance**

- [ ] pytest src/tests/btrc/test_preprocessor_conditionals.py green through both compilers: per-target selection 6/6, dead imports, diagnostics with identical message and line:col, fast path, caches, directive cache, lowering invariant
- [ ] Inventory: r18-if-zero and r18-ifdef-else accepted as c_compat corpus references; r18-undefined-identifier-in-if refused-on-purpose with I1 at 1:5; new r18 probes recorded with revision = parent
- [ ] make generated-check (every stdlib module conditions without error for every target, no #undef, no test of an absent name), make lint, make format-check including format-btrc-check
- [ ] make test-btrc, make test-btrc-selfhost, make test-lsp and pytest src/tests/formatter green
- [ ] make bootstrap fixed point; zero warnings on BtrccMain, cli/WindowsMain and cli/MacOSMain; boundary-check 311 records unchanged
- [ ] Linux memory delta ≤0.3% (≤1% accepted and recorded)
- [ ] ci.yml, macos.yml and windows.yml green on the lane branch (run ids in the report)

**Risks**

- The btrcc file-position renderer for imported files is new behavior; keep positions file-local or the parity battery diverges.
- The quiet M11 re-measure is Mac-only (MAC-C-02); the stage exit is not complete until it lands.

#### Stage 17: C2 aggregates

<a id="cl-c-07"></a>

##### CL-C-07 · ccompat-c2-schema: one serial schema commit for C2 and Stage 18 dimensions (ASDL, Node, IR, grammar, shape invariant, 2 AST boundary re-captures)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ccompat-c2-schema`
- **Depends on:** [CL-C-06](#cl-c-06)
- **Why not now:** D18 order (C4 before C2). The schema commit also shares the ir/nodes.py, ir/Model.btrc, ir/verifier.py, c_emitter.py, ir/Emitter.btrc, grammar.ebnf and ModuleUnits hotspots with the C4 lane.
- **Parallel-safe with:** CX-C-01

**Owned paths**

- src/language/ast.asdl, src/language/grammar.ebnf
- tools/compiler_codegen/ast.py with generated src/compiler/btrc/generated/ast/Node.btrc and src/compiler/python/syntax/ast/generated.py (hotspot; regenerated)
- src/compiler/btrc/syntax/Identity.btrc (AstCanonicalRenderer, AstStructure.children, TypeIdentity.encodable; hotspot)
- src/compiler/btrc/syntax/Types.btrc (TypeShape copies)
- src/compiler/python/ir/nodes.py, ir/verifier.py, ir/lowering/exceptions.py (setjmp walkers)
- src/compiler/btrc/ir/Model.btrc, ir/Emitter.btrc (shape invariant; hotspot), ir/optimization/Optimizer.btrc, pipeline/ModuleUnits.btrc (recurse into record; hotspot)
- src/compiler/python/backend/c_emitter.py (hotspot)
- src/tests/fixtures/compiler_boundaries/ (surface.python.ast.artifact, surface.btrc.ast.artifact only)
- src/tests/btrc/test_ast_structure_contract.py, a new TypeExpr copy contract test

**Must not touch**

- parser acceptance of any new syntax (each lane flips its own)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- src/stdlib/btrc.symbols, btrc.lock, src/devex/lsp/catalog/generated.py
- `src/runtime/c/**`

**Steps**

1. Main session, serial. Two read-only adversarial reviewers check the diff against c-compatibility.md 'Schema commit (ccompat-c2-schema)' before commit.
2. ASDL changes:
   - StructDecl.is_union;
   - TypeExpr.elements and array_pointer_depth;
   - FieldDef.value;
   - the AnonymousMember field_def;
   - BraceInitializer.entries;
   - CompoundLiteral;
   - designation and designator (Designation, FieldDesignator, IndexDesignator).

   The five new NK kinds go in the documented positions. Regenerate.
3. Check Node storage: isUnion and arrayPointerDepth sit in padding, elementsStorage moves next to arraySize, and sizeof(Node) is unchanged.
4. Render order: is_union after is_forward, value after name, elements after array_size, array_pointer_depth after is_volatile, entries after elements. AstStructure.children moves the elementsStorage line. TypeExpr copies carry elements only when written (guarded). TypeIdentity.encodable is false for non-empty elements or a non-zero arrayPointerDepth.
5. grammar.ebnf: record_keyword, struct_member, struct_declarator, array_declarator, typedef_decl, type_name, compound_literal, initializer_item/designation/designator, plus the comment changes. Both parsers still refuse every new form.
6. IR in both compilers: IRStructDef.is_union, IRStructForward.is_union, IRStructField.record/is_unsized_array/bit_width, IRFieldAccess.bit_field, IRDesignation (btrc IRK_DESIGNATION after IRK_COMPOUND_LITERAL), and positional '' entries. The shape invariant goes in IRVerifier and in btrc CEmitter.structFieldDeclaration/emitStruct. The walkers (btrc optimizer struct ordering, ModuleUnitDeclarations.collectField, Python setjmp walkers) recurse.
7. Re-capture surface.python.ast.artifact and surface.btrc.ast.artifact with the reason 'TypeExpr carries inner array extents and outer pointers for C2/r17'. Then the Linux memory run by Stage 15's method, and the lane report.

**Acceptance**

- [ ] make generated-check clean, including the AstCanonicalRenderer coverage check
- [ ] boundary-check: exactly the two AST records changed, still equal to each other, reason recorded; test_boundary_renderers.py and test_ast_structure_contract.py green
- [ ] AST and parser parity suites green; corpus through both compilers unchanged (make test-btrc, make test-btrc-selfhost)
- [ ] sizeof(Node) in the generated C unchanged; Linux peak RSS delta ≤0.3% (≤1% recorded)
- [ ] make bootstrap fixed point; zero-warning transpiles
- [ ] Both reviewers leave no unresolved blocking finding

**Risks**

- A new Node pointer costs about the whole 0.3% gate (Stage 15 measured -0.35% for removing one); any deviation from the reuse plan must be caught before commit.
- Mac BTRSmith row is MAC-C-03; lanes should not fork until it is ≤1%.

<a id="cl-c-08"></a>

##### CL-C-08 · C2 shared-owner commit: record-member owner, initializer-slot owner, three-way integer-constant query

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-c2-schema` (shared-owner commit that follows it)
- **Depends on:** [CL-C-07](#cl-c-07)
- **Why not now:** Builds on the C2 schema (CL-C-07) and on C4's SourceMacroNamespace.undefined (CL-C-06).
- **Parallel-safe with:** MAC-C-03

**Owned paths**

- src/compiler/python/analyzer/types.py (TypeSystem record-member class methods), aggregates.py (InitializerAnalyzer.plan_aggregate), program.py (plan side table), expressions.py (integer_constant_expression)
- src/compiler/btrc/analyzer/Types.btrc (SemanticTypeSystem record members), analyzer/Models.btrc (plans keyed by AstIdentity.key), analyzer/validation/Expressions.btrc (validateStructInitializer), analyzer/validation/Constants.btrc (ConstantValidator.integerConstant), analyzer/validation/Ownership.btrc (shallowElementType)
- every struct-field walk site in both compilers (~58 in btrc): aggregate dependencies and ordering, ownership, thread/mutex payloads, realtime, closure environments, module-unit collection, src/devex/lsp/features/symbols.py
- src/compiler/python/ir/lowering/collections.py (plan_brace), src/compiler/btrc/ir/lowering/{Expressions,Aggregates,Callables,CallableFlow}.btrc
- src/tests/btrc/test_record_member_owner_contract.py, test_initializer_slot_owner_contract.py, test_integer_constant_query_parity.py (new)

**Must not touch**

- parser acceptance of new syntax
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Main session (serial) or one dedicated agent; Python first, then the btrc port, in one commit.
2. Record-member owner: direct members (FieldDef, AnonymousMember) and flattened named members with member paths; unnamed bit-fields are not members. Route every struct-field walk through it. A contract test fails on any raw StructDecl.fields iteration elsewhere.
3. Initializer-slot owner: map each brace element to a member path or array index (flattening anonymous members, skipping unnamed bit-fields, following designators). Record the plan in AnalyzedProgram and in Analyzed by AstIdentity.key. Convert every element-to-field pairing site to read it. A contract test fails on element/field index pairing outside the owner.
4. Integer constants: one query per compiler with three answers (not constant / constant btrc cannot evaluate / value). Python adopts btrc's long long overflow rule (the one behavior change). It may fold an object-like source macro that is never #undef'd by parsing its replacement and emitting the digits.
5. Prove no accepted program changes except the evaluator parity fix; lane report.

**Acceptance**

- [ ] The three new contract tests pass in both compilers
- [ ] test_integer_constant_query_parity.py: identical answers on the shared battery (value / not constant / cannot evaluate)
- [ ] Corpus through both compilers unchanged (make test-btrc, make test-btrc-selfhost); make test-lsp green
- [ ] make bootstrap fixed point; zero-warning transpiles; lint, format-check, generated-check

**Risks**

- About 58 btrc walk sites: a missed site silently skips members once anonymous members exist; the contract test is the safety net, so it must land in this commit.

<a id="cl-c-09"></a>

##### CL-C-09 · C2 L1 r09: unions, C tag aliases for btrc records, wrong-keyword validator, tag references for strict imports, struct message parity

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L1, construct 1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r09-union-declarations`
- **Depends on:** [CL-C-08](#cl-c-08)
- **Why not now:** Lanes fork from the shared-owner commit (CL-C-08).
- **Parallel-safe with:** CL-C-13

**Owned paths**

- src/compiler/python/parser/parser.py and src/compiler/btrc/parser/Parser.btrc (shared parser rule; rebase in merge order r09, r08, r13, enum, r10a, r10b, r12)
- the r09 consumers in c-compatibility.md 'Consumers to update' (Python analyzer declarations/types/aggregates/expressions/storage/macros/ownership; frontend imports.py, native_imports.py; lowering translation_unit/classes/collections/functions/calls/storage/ownership; verifier; btrc DeclarationRegistry, SemanticTypeSystem, Names/Declarations/Types/Storage/Ownership/Expressions validators, frontend Visibility/NativeImports, ir/lowering/Declarations, Expressions, Aggregates)
- src/compiler/python/backend/c_emitter.py and src/compiler/btrc/ir/Emitter.btrc (hotspot shared with L2; merge order)
- src/devex/lsp/features/symbols.py
- src/tests/btrc/fixtures/c_compat_probe/c2.toml (r09, x-typedef-union rows), src/tests/c_compat/UnionDeclaration.btrc, UnionLayout.btrc, c_compat/layout/ (C mirror), src/tests/btrc/test_c_compatibility_refusals.py
- docs/known-language-gaps.md (unions), docs/design/btrsmith-rename-table-w2.md (if BTRSmith needs imports)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**` (report hits to the integrator for Codex)
- src/stdlib/btrc.symbols, btrc.lock, src/devex/lsp/catalog/generated.py
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Lane stage17/c2-l1 with its own btrcc (btrcc-build semaphore). One commit: Python first, then the btrc port.
2. Struct message parity first: btrc adopts Python's wording for a duplicate field, a duplicate definition and an empty body; union wording derives from it.
3. Unions: StructDecl(is_union) parse at file scope with the forward form; R8 and P1 in union bodies from the first commit (a FAM, and the T[] name spelling); the plain-member rule extending is_realtime_pod; positional init lowers to a first-member designator; == / print / new / delete / keep / release refused as for structs; @gpu refusal pinned.
4. C tags: alias rows 'struct X'/'union X' for btrc records on the existing typedef index (extend _alias_native_tag / aliasNativeTag); canonicalize before every removeprefix('struct ') reader; the wrong-keyword validator; ImportReferenceCollector and FeImportReferenceCollector count struct/union/enum X as references to X; a contract test that no consumer iterates the alias index.
5. Native: both importers set is_union from record_kind; Objective-C rebuild sites (objectiveCUnit/objectiveCValue and the Python twins in ir/lowering/functions.py) assert not-union and fail closed.
6. Tests: c2.toml r09 and x-typedef-union rows flipped (revision = parent); UnionDeclaration.btrc and UnionLayout.btrc with a C mirror returning size_t sizeof/offsetof; the native opaque union probe (union `T*` and `T*` are one type); the refusal table; a strict-import tag test; LSP union symbols.
7. Grep the stdlib, examples and BTRSmith (read-only; gh api search or the hub clone) for btrc types spelled with a tag and no import. Fix btrc-owned files, list BTRSmith hits in the rename table, and report Codex-owned hits to the integrator.
8. One parity reviewer (semantics, diagnostics, ARC witnesses); gh workflow run macos.yml --ref stage17/c2-l1; lane report.

**Acceptance**

- [ ] test_c_compatibility_inventory.py (r09 and x-typedef-union rows PASS) and test_c_compatibility_refusals.py (union and struct-parity rows) green through both compilers
- [ ] UnionDeclaration.btrc and UnionLayout.btrc pass make test-btrc and make test-btrc-selfhost; sizeof and offsetof equal the C mirror under gcc and clang
- [ ] make test-lsp, lint, format-check, generated-check; zero warnings; make bootstrap fixed point
- [ ] macos.yml green on the lane branch (run id)

**Risks**

- The strict-import tag rule can break sources that spell struct X without importing X (stdlib RealtimeAudioRouter's OwnedBuffer\<struct X> must keep working).
- Emitter hotspot shared with L2: L2 rebases on r09's emitter changes.

<a id="cl-c-10"></a>

##### CL-C-10 · C2 L1 r08: typedef records, identity typedefs, object declarators, anonymous members

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L1, construct 2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r08-typedef-struct-anonymous-members`
- **Depends on:** [CL-C-09](#cl-c-09)
- **Why not now:** L1 is sequential: r08 follows r09 on stage17/c2-l1.
- **Parallel-safe with:** CL-C-13, CL-C-14

**Owned paths**

- parser.py / Parser.btrc (_parse_typedef_decl, _parse_top_level_item splice, struct member loop; shared parser rule)
- Python DeclarationRegistry (records/enums first, identity typedefs), AggregateAnalyzer._validate_typedef_cycles, record-member owner users, TranslationUnitLowerer._emit_declarations/_declaration_types, ClassLowerer.emit_struct_decl (record)
- btrc DeclarationRegistry, NameValidator, TypeValidator typedef checks, DeclarationValidator.orderedStructDefinitions, SemanticTypeSystem.structFieldFor, CTypeLowerer.appendTypedefs, DeclarationLowerer.emitStructDecl
- c_emitter.py _emit_struct / Emitter.btrc structFieldDeclaration (inline anonymous body; hotspot, merge order)
- src/devex/lsp/features/symbols.py, navigation.py
- src/tests/c_compat/TypedefRecords.btrc, AnonymousMembers.btrc, AnonymousMemberLayout.btrc; c2.toml r08 and x-typedef(-enum) rows; src/tests/python/test_structured_ir_contract.py
- docs/known-language-gaps.md (untagged named-member refusal)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Same lane; one commit, Python then btrc.
2. Typedef records: typedef struct/union [Tag] { … } D1, `*D2`; splices one StructDecl plus one TypedefDecl per declarator (deep-copied specifier, own `*` and []). An untagged record takes its first plain declarator's name as the tag. A plain declarator equal to the tag is dropped. typedef enum splices EnumDecl plus TypedefDecls. A tagged definition may declare file-scope objects.
3. Identity typedefs: register records and enums before classifying typedefs; typedef struct X X; is a redeclaration when X is a btrc record of that keyword; native typedefs keep the importer's rules.
4. Anonymous members: lookup is flattened with collisions refused at the later member; one positional slot that needs its own braces; designators name flattened members; lowering writes such initializers as flattened designators; IRStructField.record is emitted inline. Every r08 refusal row is identical in both compilers.
5. LSP: symbols recurse into anonymous members, with no duplicate symbol for an identity typedef; navigation resolves flattened members.
6. Tests: the corpus programs above, the c2.toml r08 and x-typedef rows, test_structured_ir_contract.py; one parity reviewer; lane report.

**Acceptance**

- [ ] Inventory r08, x-typedef-enum rows PASS and the r08 refusals identical (r08-anonymous-member-collision at 3:14) through both compilers
- [ ] TypedefRecords.btrc, AnonymousMembers.btrc, AnonymousMemberLayout.btrc pass both compilers; layout equals the C mirror
- [ ] Record-member owner contract test still green (AnonymousMember reached only through the owner)
- [ ] make test-lsp, lint, format-check, generated-check; zero warnings; make bootstrap fixed point

**Risks**

- Splicing changes Program/StructDecl lists in ways the LSP and module-unit collectors walk; the identity-typedef rule must not register a typedefTable entry or both registrations collide.

<a id="cl-c-11"></a>

##### CL-C-11 · C2 L1 r10a: designated initializers (designators, current object, override refusal, extents, source-order evaluation)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L1, construct 3a) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r10-designated-init-compound-literals` (part 1: designated initializers)
- **Depends on:** [CL-C-10](#cl-c-10)
- **Why not now:** L1 is sequential: r10a follows r08 (designators name flattened anonymous members).
- **Parallel-safe with:** CL-C-14, CL-C-15

**Owned paths**

- parser.py _parse_map_or_brace_initializer plus new _parse_designation; Parser.btrc parseMapOrBraceInitializer plus parseDesignation (shared parser rule)
- Python InitializerAnalyzer (designators, overrides, extents), AggregateAnalyzer.validate_fixed_array_initializer, StatementAnalyzer static-initializer and inferred-array helpers, AnalyzedProgram side tables, CollectionLowerer.plan_brace and static plans, global extents in TranslationUnitLowerer/ClassLowerer, IRDesignation in IRVerifier and c_emitter.py
- btrc ExpressionValidator.validateInitializerValue/validateStructInitializer/validateInitializerElements, StorageValidator (bounds, static initializers), ConstantValidator, Analyzed side tables, ExpressionLowerer.lowerBraceInit/lowerBraceInitPlain/lowerFixedArrayInitializer, AggregateValueLowerer, DeclarationLowerer.emitGlobalVar, CEmitter IRK_DESIGNATION, setjmp Analysis.btrc
- src/tests/c_compat/DesignatedInitializers.btrc; c2.toml r10 designator rows; test_c_compatibility_inventory.py KNOWN_DIVERGENCES; src/tests/btrc/test_aggregate_evaluation_order_parity.py

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. Parse the designations: .IDENT, and [..] chains continuing to '='. [2] followed by ',' or '}' stays a list literal; map literals still need ':'. Refuse a GNU range in both token forms ('. . .' today; '...' after Stage 19), pinned by a probe.
3. Semantics (C11 6.7.9p17-21): the innermost brace is the current object; .f names a flattened member; [k] goes through the three-way integer query and must lie in [0, bound); an unsized outer extent is the largest index plus one, recorded for sizeof, for-in and globals; positional elements continue after a designator; no brace elision; unnamed subobjects are zero.
4. Overrides are refused when one path is a prefix of the other or the paths diverge at a union. A positional element after a designator into an anonymous member is refused. Static initializers need constants. A string designated into a char[] follows r04.
5. Lowering normalizes chains into one-step IRDesignation, with nested IRCompoundLiteral or IRInitializerList as appropriate. Operands evaluate in source order and are hoisted to temporaries when any has an effect.
6. Tests: DesignatedInitializers.btrc; the c2.toml r10 rows; drop r10-designated-index-initializer from KNOWN_DIVERGENCES; out-of-order designators in test_aggregate_evaluation_order_parity.py; negative probes (a capturing lambda through a designator, overrides, ranges, wrong targets, a missing contextual type); one parity reviewer.

**Acceptance**

- [ ] Inventory r10 designator rows PASS and the {[2] = 7} divergence gone; r10-unknown-field-designator at 3:24 and r10-duplicate-designator at 3:32 identical in both compilers
- [ ] DesignatedInitializers.btrc passes both compilers; strict C11 (-Woverride-init clean)
- [ ] test_aggregate_evaluation_order_parity.py green with out-of-order designators
- [ ] Initializer-slot contract test green; zero warnings; make bootstrap fixed point

**Risks**

- Elements of the form [..] = v now parse as designations; any existing program that relied on the old list-literal-of-assignment parse changes meaning (the inventory says none in the corpus).

<a id="cl-c-12"></a>

##### CL-C-12 · C2 L1 r10b: compound literals, the type_name rule and the for-in head exception

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L1, construct 3b) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r10-designated-init-compound-literals` (part 2: compound literals)
- **Depends on:** [CL-C-11](#cl-c-11)
- **Why not now:** Builds on r10a's initializer planning.
- **Parallel-safe with:** CL-C-15

**Owned paths**

- parser.py _parse_primary plus _is_compound_literal, for-in/parallel-for iterable rule; Parser.btrc parsePrimary plus isCompoundLiteral, parseForStmt (shared parser rule)
- Python ExpressionAnalyzer (literal type, addressability, return escape, try rule), compound-literal arms in analyzer/ownership.py, _EXPRESSION_LABELS in analyzer/gpu.py, ExpressionLowerer (compound literal, & inside the evaluation boundary), OwnershipLowerer.owns_result, ExceptionLowerer children
- btrc ExpressionTypeResolver, GpuKernelValidator label, RealtimeAnalyzer, compound-literal arms in validation {Ownership, Borrows, Calls, ControlFlow, Declarations, Types}, ExpressionLowerer.lowerCompoundLiteral (new), the kind-coverage walkers in ir/lowering/{Statements, Callables, CallableFlow, Concurrency, ownership/Operands, ownership/Semantics}, ir/gpu/{Pipeline, Wgsl}
- src/tests/c_compat/CompoundLiterals.btrc; c2.toml r10 compound rows; a CompoundLiteral kind-coverage contract test (src/tests/btrc/test_compound_literal_kind_coverage.py)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. Parse: '(' type_name ')' '{' is a compound literal, and the type_name rule (C11 6.7.7) is the one abstract form, with [] meaning an array of unknown size. In for-in and parallel-for iterables, an expression-shaped head (IDENT) or (IDENT[expr]) stays the iterable when '{' follows.
3. Semantics: a complete object type or an unsized array sized from the initializer; managed, VLA, void and incomplete types are refused. It is an lvalue. A whole-initializer compound literal of the same struct/union/tuple/scalar type is that object's initializer, and the array form is refused. At file scope only address constants are accepted. Escapes (a returned address, a static initialized from an automatic literal) are refused. The try rule applies. Defaults and field initializers are value-only. Refused in @gpu, allowed in @realtime.
4. Kind coverage: audit the 51 NK_BRACE_INITIALIZER sites in 21 btrc files, the NK_TERNARY_EXPR sites and the 16 Python files naming BraceInitializer. Each names CompoundLiteral or sits on a reasoned allow-list (contract test).
5. Tests: CompoundLiterals.btrc; the c2.toml rows; negative probes (a capturing lambda through a compound literal, for x in (items) { parse parity, default/field addresses, try, escapes, VLA, managed and non-constant file-scope literals); one parity reviewer; lane report.

**Acceptance**

- [ ] Inventory r10 compound-literal rows PASS in both compilers; every compound-literal refusal row identical
- [ ] CompoundLiterals.btrc passes both compilers under strict C11 (no -Wreturn-local-addr / -Wreturn-stack-address)
- [ ] Kind-coverage contract test green; for-in head parse parity test green
- [ ] Zero warnings; make bootstrap fixed point

**Risks**

- Ownership predicates return false for unknown kinds, so a missed arm leaks or double-releases silently; the contract test plus ARC witnesses in the corpus are mandatory.

<a id="cl-c-13"></a>

##### CL-C-13 · C2 L2 r13: flexible array members (C11 layout, behind-a-pointer only) and the layout harness

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L2, construct 1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ccompat-r13-flexible-array-members`
- **Depends on:** [CL-C-08](#cl-c-08)
- **Why not now:** Lanes fork from the shared-owner commit (CL-C-08).
- **Parallel-safe with:** CL-C-09, CL-C-10

**Owned paths**

- parser.py _parse_struct_decl / Parser.btrc parseStructField (P1; shared parser rule; L2 rebases on L1 in merge order)
- Python AggregateAnalyzer (array_field_value_type, is_pointer_backed_array_target, array_target_has_capacity, validate_complete_aggregate_use, validate_sizeof_operand, _collect_aggregate_dependencies), InitializerTypeLayout.array_field_value, TypeSystem.validate_declared_type, ExpressionAnalyzer (assignment, &, NewExpr), StatementAnalyzer declaration checks, StorageModel.projection_embeds_storage, ClassLowerer.emit_struct_decl, IRObjectiveCClass.validate
- btrc StorageValidator (FAM predicate as a class method), DeclarationValidator.visitStructDefinition/validateStructLayouts, TypeValidator, ExpressionValidator, DeclarationLowerer.emitStructDecl
- c_emitter.py _emit_struct / Emitter.btrc structFieldDeclaration (hotspot shared with L1)
- src/tests/c_compat/FlexibleArrayMembers.btrc, FlexibleArrayLayout.btrc, c_compat/layout/flexible_array_layout.c; src/tests/btrc/test_flexible_array_member_contract.py, test_c_aggregate_layout.py (new); updated test_generic_array_assignment_contract.py, test_thread_ownership_contract.py, test_parser_decls.py::test_struct_with_array_fields, test_structured_ir_contract.py
- docs/known-language-gaps.md (FAM refusals, allocation pattern)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Lane stage17/c2-l2 with its own btrcc; one commit, Python then btrc.
2. A FAM is the last member, follows a named member and sits directly in a named struct body. The T[] name spelling in struct bodies is refused (P1). Elements are complete non-managed types. Layout follows C11.
3. Behind-a-pointer only: refuse objects, by-value parameters and returns, casts, brace and compound initialization, copy and assignment, new, and storage in arrays, records, tuples, payloads and generic arguments, each with the subject wording table. sizeof(struct S) and `sizeof(*p`) are allowed. Member access decays; sizeof(p->data) and &p->data are refused.
4. Layout harness: test_c_aggregate_layout.py requires identical emitted declarations from both compilers, raw IR carrying is_unsized_array, and sizeof/offsetof equal to a C mirror returning size_t.
5. Grep the stdlib, examples (none today) and BTRSmith (read-only) for struct fields spelled T[] name. Add BTRSmith hits to docs/design/btrsmith-rename-table-w2.md and report Codex-owned stdlib hits.
6. Drop both r13 KNOWN_DIVERGENCES entries and flip the c2.toml r13 rows (not-last rejected at 1:21). Update the four existing tests. One parity reviewer. gh workflow run macos.yml --ref stage17/c2-l2 (layout under Apple clang). Lane report.

**Acceptance**

- [ ] Inventory r13 rows PASS (r13-flexible-array-not-last rejected at 1:21 in both); KNOWN_DIVERGENCES has no r13 entry
- [ ] FlexibleArrayMembers.btrc and FlexibleArrayLayout.btrc pass both compilers; test_flexible_array_member_contract.py and test_c_aggregate_layout.py green
- [ ] The C11-valid forms btrc refuses are listed in known-language-gaps 'C that btrc rejects on purpose' with tests in test_c_compatibility_refusals.py
- [ ] macos.yml green on the lane branch; zero warnings; make bootstrap fixed point

**Risks**

- P1 turns a previously accepted spelling (T[] name in a struct) into an error; BTRSmith or Codex stdlib code written meanwhile could break (covered by D27's forward-compat rule and the grep).

<a id="cl-c-14"></a>

##### CL-C-14 · C2 L2 enum tags: tag aliases on r09's owner, evidence rule for unknown enum X, typedef enum emission, native-tag collision refusal

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L2, construct 2) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-x-enum-tag-spelling`
- **Depends on:** [CL-C-13](#cl-c-13); [CL-C-09](#cl-c-09)
- **Why not now:** Rebases on r09's tag owner (CL-C-09) and follows r13 on stage17/c2-l2.
- **Parallel-safe with:** CL-C-10, CL-C-11

**Owned paths**

- Python EnumRegistrar.register_simple, per-file evidence from the source dependency graph and quoted #includes, TypeSystem.validate_declared_type/validate_cast_target_name/_is_known_declaration_type, AggregateAnalyzer.validate_sizeof_operand, NativeDeclarationImporter._enum, c_emitter.py _emit_enum_def
- btrc DeclarationRegistry (alias, evidence), TypeValidator.validateDeclaredType/knownDeclarationType/explicitCTag, ExpressionValidator cast and sizeof operands, isEnum(base) callers in Operators.btrc, Realtime.btrc, validation/Constants.btrc, ir/lowering/Strings.btrc, frontend/NativeImports.btrc, CEmitter.emitEnum
- src/tests/c_compat/EnumTagSpelling.btrc; src/tests/btrc/test_enum_tag_contract.py (new); c2.toml x-enum-tag rows

**Must not touch**

- src/tests/basics/InteropCEnumBaseType.btrc (must stay as is)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. Resolve enum X in order: btrc plain enum, native enum tag (the importer registers enum \<tag>), another kind (refused with the tag template), unknown. An unknown tag is accepted only with evidence from the spelling file (a .c import edge or a quoted non-.btrc #include); system includes do not count.
3. Emit typedef enum Color { … } Color; for named plain enums. Generic identity keeps the written spelling.
4. A btrc enum named like a native-import record or enum tag is refused at the enum (macOS-shaped probe).
5. btrcc's own C changes (tagged enum emission): re-prove the bootstrap fixed point.
6. Tests: EnumTagSpelling.btrc covering parameters, returns, pointers, arrays, casts, sizeof, switch, print, toString, typedef enum Color Shade, a struct field and a generic argument; test_enum_tag_contract.py; drop both x-enum-tag KNOWN_DIVERGENCES; one parity reviewer; macos.yml dispatch; lane report.

**Acceptance**

- [ ] Inventory x-enum-tag rows PASS (x-enum-tag-unknown rejected at 2:2 in both); KNOWN_DIVERGENCES has no x-enum-tag entry
- [ ] EnumTagSpelling.btrc and basics/InteropCEnumBaseType.btrc pass both compilers; test_enum_tag_contract.py green
- [ ] make bootstrap fixed point with the new enum emission; zero warnings
- [ ] macos.yml green on the lane branch (native tag collision against real SDK headers)

**Risks**

- Apple SDK tags are PascalCase, so a btrc enum named like an SDK record becomes an error once a native import registers that tag; stdlib/BTRSmith grep needed.

<a id="cl-c-15"></a>

##### CL-C-15 · C2 L2 r12: bit-fields (types, widths, promoted reads, stores through the containing object, never addressable)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (lane L2, construct 3) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r12-bitfields`
- **Depends on:** [CL-C-14](#cl-c-14); [CL-C-10](#cl-c-10); [CL-C-11](#cl-c-11)
- **Why not now:** Rebases on r08 (unnamed bit-field vs AnonymousMember) and r10a (designators skip unnamed bit-fields); follows the enum lane on L2.
- **Parallel-safe with:** CL-C-12

**Owned paths**

- parser.py _parse_struct_decl (named and unnamed widths), _parse_class_member refusal; Parser.btrc parseStructField and the class-member refusal (shared parser rule)
- Python TopLevelRegistrar.register_struct, AggregateAnalyzer.validate_bit_field (new), validate_struct_field_access, validate_sizeof_operand, InitializerAnalyzer.plan_aggregate (fit), ExpressionAnalyzer (read type, address checks, store fit), ClassLowerer.emit_struct_decl, ExpressionLowerer field access (bit_field), StorageLowerer.materialize_target/prepare_update, OwnershipLowerer.assignment_target_operands/_receiver_operands, out-parameter adapters in functions.py and calls.py, exceptions.py, IRVerifier
- btrc TypeValidator.validateAggregateDeclarationTypes, ConstantValidator.integerConstant, NameValidator, ExpressionValidator.validateUnary and sizeof, StorageValidator.isAddressableStorage, ExpressionTypeResolver.inferTypeRaw, SemanticTypeSystem.structFieldFor, DeclarationLowerer.emitStructDecl, ExpressionLowerer.lowerDirectStore/lowerDirectCompound/directLvaluePointerType/lowerIndirectIncDec/staticInitializerFieldCount, setjmp Analysis.btrc and Safety.btrc, CEmitter no-address assertion
- src/devex/lsp/features/symbols.py, src/devex/lsp/analysis/resolution.py (hover)
- src/tests/c_compat/BitFields.btrc, BitfieldLayout.btrc; src/tests/btrc/test_bitfield_lvalue_contract.py (new); c2.toml r12 rows

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. Struct and union bodies only. Types: bool, int, signed int, unsigned int (uint), optionally const or volatile. The width is a known integer constant: 0..32 for the int family, ≤1 for bool, 0 only when unnamed. Unnamed bit-fields are not members, and a record keeps at least one named member.
3. Reads have the promoted type (int / unsigned int for :32 / bool). Stores convert as C does, and constants that do not fit are refused.
4. Compound assignment and ++/-- read into a temporary, compute, and store back through the member lvalue, stabilizing the containing object (&recv or the pointer) and never the member. Fix btrc lowerDirectStore/lowerDirectCompound, which take &target today.
5. Never addressable: &s.f, sizeof(s.f) and offsetof are refused. Every access is marked IRFieldAccess.bit_field. A post-optimization rule (IRVerifier; btrc CEmitter) refuses IRAddressOf, array decay or out-parameter adapters rooted at one.
6. Tests: BitFields.btrc, BitfieldLayout.btrc (sizeof only), and test_bitfield_lvalue_contract.py (=, op=, prefix and postfix through . and ->, arr[i++].f, call()->f, try/catch, lambdas, generic bodies) under gcc and clang -pedantic-errors. LSP symbols skip unnamed members and show 'unsigned int : 3'. One parity reviewer; macos.yml dispatch; lane report.

**Acceptance**

- [ ] Inventory r12 rows PASS (r12-bitfield-address refused identically in both); every r12 refusal row identical
- [ ] BitFields.btrc and BitfieldLayout.btrc pass both compilers under strict C11; test_bitfield_lvalue_contract.py green under gcc and clang
- [ ] The no-address verifier rule has a negative test that injects an IRAddressOf of a bit-field access
- [ ] make test-lsp; macos.yml green on the lane branch; zero warnings; make bootstrap fixed point

**Risks**

- Setjmp stabilization or any later address-taking rewrite could reintroduce &bitfield; the post-optimization rule is the guard and must run in both compilers.

<a id="cl-c-16"></a>

##### CL-C-16 · ccompat-c2-integrate: every C2 row PASS, layout agreement, divergences gone, memory delta, docs

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (exit) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-c2-integrate`
- **Depends on:** [CL-C-09](#cl-c-09); [CL-C-10](#cl-c-10); [CL-C-11](#cl-c-11); [CL-C-12](#cl-c-12); [CL-C-13](#cl-c-13); [CL-C-14](#cl-c-14); [CL-C-15](#cl-c-15)
- **Why not now:** Needs every C2 construct merged (merge order r09, r08, r13, enum, r10a, r10b, r12).
- **Parallel-safe with:** CX-C-01

**Owned paths**

- src/tests/btrc/fixtures/c_compat_probe/c2.toml
- src/tests/btrc/test_c_compatibility_inventory.py (KNOWN_DIVERGENCES)
- docs/design/c-compatibility.md (C2 status)
- docs/known-language-gaps.md (C2 sections)
- fix sites for integration findings in both compilers

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. Integration branch on the merged batch(es): re-run c2.toml through both compilers; every approved row PASS or deliberately refused with a test in both.
2. KNOWN_DIVERGENCES must hold only the two Stage 19 entries (x-hex-float-without-exponent, x-alignof-expression).
3. Layout harness over unions, anonymous members, FAMs, bit-field sizeof and enums: sizeof/offsetof agree with gcc and clang. Bit-field no-address rule holds.
4. Linux memory delta by Stage 15's method (parent of CL-C-07 vs the integrated tree); the Mac row is MAC-C-04.
5. Docs: c-compatibility.md C2 status; known-language-gaps sections for unions, typedef records, anonymous members, designators, compound literals, FAMs and bit-fields; record the deferrals.
6. Push after the green D5 gate; record ci.yml/macos.yml/windows.yml run ids on main.

**Acceptance**

- [ ] pytest src/tests/btrc/test_c_compatibility_inventory.py src/tests/btrc/test_c_compatibility_refusals.py green; every c2.toml positive accepted in both compilers
- [ ] test_c_aggregate_layout.py and the layout corpus green under gcc and clang (Linux CI 8 cells; macos.yml clang O0/O2)
- [ ] D5 batch gate green (make test, make bootstrap, make test-c11, lint, format-check, generated-check, extension, git diff --check)
- [ ] Linux memory delta recorded (≤0.3% passes, ≤1% accepted)
- [ ] ci.yml, macos.yml and windows.yml green on main after push (run ids)

**Risks**

- Mac BTRSmith rerun and memory row (MAC-C-04) close the stage; until then Stage 17 is not exited.

<a id="cl-c-17"></a>

##### CL-C-17 · C2 follow-up: lift native flexible array members (last incomplete-array field of a native struct) with a Clang-layout cross-check

- **Owner:** Claude · **Group:** C · **Stage:** Stage 17 (post-exit L2 commit) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ccompat-r13-flexible-array-members` (native FAM lift, own commit after the C2 exit)
- **Depends on:** [CL-C-16](#cl-c-16)
- **Why not now:** The design schedules it after ccompat-c2-integrate as its own commit.
- **Parallel-safe with:** MAC-C-04

**Owned paths**

- src/compiler/python/frontend/native_imports.py
- src/compiler/btrc/frontend/NativeImports.btrc
- src/tests/python/test_native_flexible_array_layout.py (new) and its header fixture under src/tests/native/
- docs/design/native-interop.md (native FAM row)

**Must not touch**

- tools/NativeHeaderReader.cpp unless the reader lacks the field (then a separate reader commit, still Claude)
- src/language/native_abi.asdl (no schema change expected)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. Both importers accept a native struct whose last field is an incomplete array as a FAM record (IRStructField.is_unsized_array), and keep native union values, anonymous fields and bit-fields refused (ref:3191-3192).
2. Test: the reader's Clang offset_bits for every field equals offsets measured from the emitted C (C mirror returning size_t), on Linux headers and, via macos.yml, an Apple SDK record with a FAM.
3. Docs and lane report.

**Acceptance**

- [ ] test_native_flexible_array_layout.py green through both compilers on Linux (reader built from the tree) and on macos.yml (run id)
- [ ] Existing native suites unchanged; zero warnings; make bootstrap fixed point

**Risks**

- Must finish before CL-C-18 so Stage 18 runs alone (PLAN: 'alone').

#### Stage 18: Multi-dimensional arrays, alone (approved, D19)

<a id="cl-c-18"></a>

##### CL-C-18 · Stage 18 r17 step 2: multi-dimensional array representation and analyzer (extents, rank helpers, decay/argument/sizeof/initializer rules, refusals)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 18 (serial step 2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-r17-multidimensional-arrays` (representation and analyzer)
- **Depends on:** [CL-C-17](#cl-c-17)
- **Why not now:** Stage 18 runs alone after C2 (c2-integrate plus the native FAM commit) and uses C2's TypeExpr.elements.

**Owned paths**

- parser.py _parse_declarator_array_suffix/_parse_type_expr; Parser.btrc parseDeclaratorArraySuffix/parseType
- Python TypeIdentity (shape_key, _encode_type, substitute, is_c_string_pointer) and TypeSystem (rank helper, compose_type_expr, strip_outer_storage, add_outer_pointer, types_compatible, qualifier depths, validate_declared_type, format_type, thread/realtime strips) in analyzer/types.py
- Python StatementAnalyzer._validate_array_bound/_analyze_for_in, AggregateAnalyzer.array_parameter_value_type/validate_fixed_array_initializer, ExpressionAnalyzer, CallAnalyzer argument extents, GenericAnalyzer, AnalyzedProgram extent values, frontend/imports.py ImportReferenceCollector.visit (elements)
- btrc syntax/Identity.btrc (TypeIdentity; hotspot), syntax/Types.btrc (TypeShape.withoutOuterArray, copies, TypeComposition.compose), SemanticTypeSystem (resolveGenericType, composeTypedefType, indexResultType), StorageValidator, TypeValidator, ExpressionValidator, validation Calls.btrc/Constants.btrc, ExpressionTypeResolver, OperatorSemantics, Generics.btrc closure walk, frontend/Visibility.btrc (elements)
- src/tests/python/test_parser_decls.py, src/tests/btrc/test_parser_diagnostics.py (inverted rejections), test_ast_structure_contract.py, c2.toml r17 rows

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`
- GPU and iteration files (CL-C-20/21)

**Steps**

1. Branch stage18/r17-arrays (CL-C-18 and CL-C-19 merge together; parsers must not accept extents on main before lowering exists).
2. Parsers fill array_size then elements, and nullable_outer_depth grows by one per extent. T[][] and T[] x[3] get the one-dimension refusal.
3. One rank helper per compiler replaces every storage-level int(is_array). Rank 1 must stay byte-identical in shape keys, symbols and C, or char names[4][16] would pass for a C string.
4. Inner extents go through the three-way query and are recorded per extent (constant_array_bound_ids and constantArrayBoundKeys become value maps). Only the outermost extent may be a run-time bound.
5. Rules and refusals: initializers brace every row and are counted per level; decay to row pointers is allowed only for indexing, `*`, sizeof, matching array parameters and `void*`; parameters drop the outer extent only; sizeof of a rank≥2 array parameter is refused; the full r17 refusal table, identical in both compilers.
6. Both frontend reference collectors visit elements; add the --module-units rank-2 parameter regression and the copy contract test (every btrc site that sets arraySize on a copy handles both new fields); invert test_multidimensional_array_has_architecture_error and the one-dimension case.

**Acceptance**

- [ ] Inverted parser tests green in both compilers; r17 refusal rows identical (r17-unsized-inner-dimension at 2:12)
- [ ] Rank-1 shape keys and generated C byte-identical over the corpus (both compilers) before CL-C-19 lands
- [ ] test_ast_structure_contract.py and the copy contract test green
- [ ] Branch-local: zero warnings and make bootstrap fixed point (merged with CL-C-19)

**Risks**

- TypeIdentity.encodable must stay false for elements/arrayPointerDepth or module units replay int m[][3] as int[].

<a id="cl-c-19"></a>

##### CL-C-19 · Stage 18 r17 step 3: storage lowering via row typedef chains (IRTypedefDef.array_size, ArrayTypedefRegistry, qualifier casts)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 18 (serial step 3) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r17-multidimensional-arrays` (storage lowering)
- **Depends on:** [CL-C-18](#cl-c-18)
- **Why not now:** Same branch as CL-C-18; needs the representation.

**Owned paths**

- src/compiler/python/ir/lowering/types.py (CTypeLowerer, ArrayTypedefRegistry), storage.py (plan_declaration), classes.py, translation_unit.py, expressions.py (_lower_sizeof), exceptions.py
- src/compiler/python/ir/nodes.py (IRTypedefDef.array_size), ir/optimizer.py (plan_type_declarations), backend/c_emitter.py (_emit_typedef; hotspot), application/modules.py (typedef dependencies; hotspot)
- src/compiler/btrc/ir/lowering/Types.btrc (registry), Declarations.btrc, Statements.btrc, Expressions.btrc, Aggregates.btrc, ir/Model.btrc, ir/Emitter.btrc (emitTypedef; hotspot), ir/optimization/Optimizer.btrc (IRTypeDeclarationPlanner complete-type context), pipeline/ModuleUnits.btrc (hotspot), ir/runtime/References.btrc, setjmp Safety.btrc and Analysis.btrc
- src/tests/c_compat/TwoDimensionalArrays.btrc (+ const-row strict case), c2.toml r17 positive

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`
- `ir/gpu/**`, backend/wgsl_emitter.py, iteration lowering (CL-C-20/21)

**Steps**

1. IRTypedefDef.array_size in both IRs (an IRExpr). CTypeLowerer owns an ArrayTypedefRegistry: one typedef per (element, inner extents) as a chain (typedef int R4[4]; typedef R4 R34[3];), with deterministic names identical in both compilers, drained into typedef_defs.
2. Declarations keep their shape (R3 grid[2]); render stays the decayed type (`T*` or `R*`).
3. Qualifier-adding conversions get explicit casts ((const `R3*)arg`), including for iterator and stabilization temporaries.
4. The Python planner and btrc IRTypeDeclarationPlanner treat an array IRTypedefDef as a complete-type context; module-unit typedef dependencies; the setjmp walkers.
5. Corpus TwoDimensionalArrays.btrc, including the strict C11 case that passes a non-const 2-D array to a const parameter.
6. Rebase-merge CL-C-18 and CL-C-19 as one batch; one parity reviewer; lane report.

**Acceptance**

- [ ] TwoDimensionalArrays.btrc passes through both compilers under strict C11 (Linux CI gcc and clang O0-O3)
- [ ] Rank-1 programs: generated C byte-identical to the parent in both compilers
- [ ] --module-units rank-2 regression green; make bootstrap fixed point; zero warnings; make test-btrc and make test-btrc-selfhost green

**Risks**

- Holds the emitter and ModuleUnits hotspots; nothing else in bucket 2 runs (Stage 18 alone).

<a id="cl-c-20"></a>

##### CL-C-20 · Stage 18 r17 step 4a: GPU lane, rank≥2 refused in @gpu, WGSL fails closed

- **Owner:** Claude · **Group:** C · **Stage:** Stage 18 (parallel step 4) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ccompat-r17-multidimensional-arrays` (GPU lane)
- **Depends on:** [CL-C-19](#cl-c-19)
- **Why not now:** Runs after the representation and storage lowering land.
- **Parallel-safe with:** CL-C-21

**Owned paths**

- src/compiler/python/analyzer/gpu.py, ir/lowering/gpu.py, backend/wgsl_emitter.py
- src/compiler/btrc/analyzer/GPU.btrc (GpuKernelValidator), ir/gpu/Pipeline.btrc, ir/gpu/Wgsl.btrc
- GPU probe tests under src/tests/btrc (GPU parity probes) and src/tests/gpu/

**Must not touch**

- iteration/collections files (CL-C-21)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. Refuse rank≥2 everywhere in @gpu with '@gpu buffers are one-dimensional; flatten …', never flattening.
2. The WGSL emitters raise on any rank≥2 type that reaches them.
3. Add GPU probes with identical WGSL and diagnostics in both compilers; lane report.

**Acceptance**

- [ ] GPU probes agree between compilers (the existing 114/114 parity battery stays green plus the new rows)
- [ ] naga validation of unchanged shaders still green; zero warnings

**Risks**

- Low; disjoint files from CL-C-21.

<a id="cl-c-21"></a>

##### CL-C-21 · Stage 18 r17 step 4b: collections and iteration lane (for-in/parallel-for refusals, row for-in, Span, generics, var, lambda captures, LSP)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 18 (parallel step 4) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-r17-multidimensional-arrays` (collections and iteration lane)
- **Depends on:** [CL-C-19](#cl-c-19)
- **Why not now:** Runs after the representation and storage lowering land.
- **Parallel-safe with:** CL-C-20

**Owned paths**

- src/compiler/python/ir/lowering/iteration.py, analyzer/statements.py (_analyze_for_in), analyzer/generics.py, ExpressionAnalyzer spawn captures
- src/compiler/btrc/ir/lowering/Statements.btrc (iteration parts), analyzer/Generics.btrc, validation/Expressions.btrc (captures)
- src/devex/lsp/analysis/resolution.py ([2][3]), src/devex/lsp/features/navigation.py
- r17 iteration/Span/generic tests and c_compat cases

**Must not touch**

- GPU files (CL-C-20)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. for-in and parallel for over rank≥2 are refused with the table's wording; for x in grid[i] works.
2. Span\<T> requires one dimension; generic arguments, var, return and CFunction signatures refuse rank≥2 (until x-pointer-to-array); lambda captures behave as named arrays.
3. LSP hover and navigation render [2][3].
4. Tests in both compilers; lane report.

**Acceptance**

- [ ] The r17 iteration, Span, generic and capture refusals are identical in both compilers; for x in grid[i] runs
- [ ] make test-lsp green; zero warnings

**Risks**

- Shares Statements.btrc with nothing else in flight (Stage 18 alone).

<a id="cl-c-22"></a>

##### CL-C-22 · Stage 18 step 5 and exit: native fixed multi-dimensional scalar fields, two reviewers, docs

- **Owner:** Claude · **Group:** C · **Stage:** Stage 18 (step 5 and exit) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ccompat-r17-multidimensional-arrays` (native fields, exit)
- **Depends on:** [CL-C-20](#cl-c-20); [CL-C-21](#cl-c-21)
- **Why not now:** Needs both Stage 18 parallel lanes merged.
- **Parallel-safe with:** CX-C-02

**Owned paths**

- src/compiler/python/frontend/native_imports.py, src/compiler/btrc/frontend/NativeImports.btrc (fixed multi-dimensional scalar fields)
- src/tests/python/test_native_multidimensional_fields.py (new) and header fixture
- docs/known-language-gaps.md ('Intentional syntax limits' paragraph replaced; VLA table extended with inner run-time extents)
- docs/design/c-compatibility.md (Stage 18 status)
- src/tests/btrc/fixtures/c_compat_probe/c2.toml (r17 rows)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. Lift native fixed multi-dimensional scalar fields in their own commit; cross-check the reader's Clang layout against offsets from the emitted C.
2. Two read-only reviewers over the whole stage (representation and storage soundness; Python/btrc parity).
3. Docs: replace the known-language-gaps paragraph and extend the VLA table; flip the r17 inventory rows; gh workflow run macos.yml on the branch; lane report.

**Acceptance**

- [ ] Stage 18 exit: c_compat/TwoDimensionalArrays.btrc passes through both compilers under strict C11 and the pinned rejection tests are inverted
- [ ] test_native_multidimensional_fields.py green on Linux and on macos.yml (run id)
- [ ] Reviewers leave no unresolved blocking finding; D5 batch gate green; ci.yml/macos.yml/windows.yml green on main after push

**Risks**

- The Mac's own 8-cell test-c11 for this emission change runs in MAC-C-05.

<a id="cl-req-01"></a>

##### CL-REQ-01 · Fix the pre-existing failure test_cached_split_cli_restores_complete_executable_generation (the Python CLI reports --profile as cached)

- **Owner:** Claude · **Group:** REQ · **Stage:** Stage 18 (recorded there; housekeeping under AGENTS.md rule 6) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 2 agent-hours
- **PLAN items:** (none: AGENTS.md rule 6, no pre-existing failures)
- **Depends on:** none
- **Parallel-safe with:** CL-C-00, CL-UIA-02

> **Writer note:** Added by the writer (§7 Q14, §9 item 10). The failure was recorded in Stage 18's Progress entry and no scope owned it.

**Owned paths**

- src/compiler/python/cli/compiler.py and src/compiler/python/application/compiler.py (only the --profile cache-reporting path)
- src/compiler/btrc/cli/Driver.btrc (only if btrcc reports the same way; paired change)
- the test module holding test_cached_split_cli_restores_complete_executable_generation (regression assertion only)

**Must not touch**

- pipeline/ModuleUnits.btrc and application/modules.py while the C4 lane holds them
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`

**Steps**

1. Reproduce on current main: run the 4 cases of test_cached_split_cli_restores_complete_executable_generation (pytest -k) and confirm Stage 18's diagnosis that the Python CLI reports --profile as cached.
2. Fix the owner that decides and reports cache reuse for --profile, Python first. Mirror it in btrc in the same commit only if btrcc behaves the same way (paired).
3. Add the regression assertion to the same test module and write the lane report.

**Acceptance**

- [ ] The 4 cases pass through both frontends
- [ ] make test-unit and the module-unit suites are green; zero-warning self-host transpiles and the make bootstrap fixed point if a btrc compiler source changed

**Risks**

- cli/Driver.btrc is a hotspot held by the C4 lane from CL-C-05 to CL-C-06; if btrc must change, schedule it outside that hold.

#### Stage 19: C3 vocabulary and specifier lanes

<a id="cl-c-00"></a>

##### CL-C-00 · Reconcile the C3 vocabulary design with the goto design (schema reservation, pending tables, D-13/D-7 owners)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 / Stage 20 (design prep) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 2 agent-hours
- **PLAN items:** `ccompat-c3-schema-vocabulary` (design reconciliation only); `ccompat-r11-goto-labels` (design reconciliation only)
- **Depends on:** none
- **Parallel-safe with:** CL-C-01, CL-C-02, CX-C-01

**Owned paths**

- docs/design/c-vocabulary-specifiers.md
- docs/design/c-goto-labels.md
- PLAN.md (Stage 19 and Stage 20 entries only)

**Must not touch**

- `src/**`
- `tools/**`
- docs/design/plan-reference.md (frozen)
- PLAN.md outside the Stage 19/20 entries (integrator-owned)

**Steps**

1. Branch stage19/design-reconcile from main 8b73c79; doc-only, no build.
2. c-vocabulary-specifiers.md: replace the Stage 20 reservation GotoStmt(identifier name) / LabeledStmt(identifier name, stmt body, int name_line, int name_col) everywhere it appears (Decisions row ~l.91, Conventions ~l.283, kind-coverage note ~l.391, ASDL block ~l.965-966, Node storage table ~l.993) with c-goto-labels.md's GotoStmt(identifier name, int name_line, int name_col) and LabelStmt(identifier name), IR IRGoto / IRLabel(falls_through); keep the 0-byte claim (name, nameLine, nameCol, fallsThrough already exist in Node/IRNode).
3. Remove goto from the C3 pending-refusal tables (Commit A 'Pending refusals' and 'Cleanup', and ccompat-c3-integrate step 1): the goto design keeps today's parser errors with no interim message, so the c3_c4.toml goto probes change exactly once.
4. Record owners: D-13 (btrc ExpressionTypeResolver termination copy) lands first as its own parity commit (CL-C-02); r15b keeps the completion table and D-7's missing-return/lambda wording, which closes goto 'Findings for other owners' item 4; items 5, 7 and 8 go to Stage 21's divergence sweep (CL-C-39).
5. Record this plan's scheduling choices in the 'Lanes' sections, marked pending owner approval: C2 schema after the C4 behavior commit; commit B as B1/B2; r10 as designators then compound literals; goto after r15a and r14 so r11 still merges last.
6. Amend PLAN.md's Stage 19 and Stage 20 entries as c-goto-labels.md line 500 requires (LabelStmt, no interim message, released re-initialization, forward-only realtime).
7. One read-only adversarial reviewer re-reads both documents for remaining contradictions (schema, positions, IR kinds, pending tables, termination owner).

**Acceptance**

- [ ] rg -n LabeledStmt docs/design PLAN.md returns nothing
- [ ] Reviewer reports zero remaining contradictions between c-vocabulary-specifiers.md and c-goto-labels.md
- [ ] git diff --check clean; pytest src/tests/python/test_device_registry.py src/tests/btrc/test_c_compatibility_inventory.py stay green (both read PLAN.md item ids)
- [ ] Lane report: commit hash and the list of changed sections

**Risks**

- If CL-C-23 starts before this lands, ast.asdl gets LabeledStmt and Stage 20 needs a second schema commit (both docs forbid that).
- PLAN.md is an integrator hotspot: keep the edit to the two stage entries.

<a id="cl-c-02"></a>

##### CL-C-02 · btrc lambda-termination parity (D-13): one termination predicate, delete ExpressionTypeResolver's copy

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 / Stage 20 prerequisite (pulled forward) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 3 agent-hours
- **PLAN items:** `ccompat-r15b-inline-noreturn` (D-13 prerequisite parity commit only); `ccompat-r11-goto-labels` (lambda-termination parity prerequisite)
- **Depends on:** none
- **Parallel-safe with:** CL-C-00, CL-C-03, CL-C-04, CX-C-01

**Owned paths**

- src/compiler/btrc/analyzer/Expressions.btrc (delete ExpressionTypeResolver.blockTerminates/elseTerminates/statementTerminates, ~l.86-119)
- src/compiler/btrc/analyzer/validation/ControlFlow.btrc (lambda check ~l.63)
- src/compiler/btrc/analyzer/validation/Expressions.btrc (lambda check ~l.775)
- src/tests/btrc/test_lambda_termination_parity.py (new)

**Must not touch**

- `src/compiler/python/**` (Python already accepts; no change)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`
- diagnostic wording (unification is r15b's, CL-C-27)

**Steps**

1. Branch stage19/lambda-termination from main; rebase onto CL-C-01 if it has merged.
2. Reproduce: a typed lambda ending in while (true) { return n; } and one ending in a terminating switch; the reference compiler accepts both and btrcc refuses both.
3. Delete the ExpressionTypeResolver termination copy and route both lambda paths to ControlFlowValidator.statementTerminates / blockTerminates.
4. Add test_lambda_termination_parity.py (both compilers): the two positives; negatives (a loop with break, a switch without default) with each compiler's current wording pinned per compiler.
5. Prove no accepted program changes: btrcc corpus outputs unchanged and btrcc's own C byte-identical to its parent (bootstrap).
6. Lane report.

**Acceptance**

- [ ] pytest src/tests/btrc/test_lambda_termination_parity.py green through Python and cached btrcc
- [ ] make test-btrc-selfhost green
- [ ] make bootstrap fixed point; btrcc C byte-identical to the parent's
- [ ] Zero-warning transpiles of BtrccMain, cli/WindowsMain, cli/MacOSMain; make lint, format-check, generated-check clean

**Risks**

- Pulls a sub-step of r15b ahead of D18's C order (justified as a pre-existing parity defect); if the owner prefers, fold it into CL-C-27 instead.
- Touches a btrc validation file CL-C-01 may also touch: rebase after CL-C-01.

<a id="cl-c-23"></a>

##### CL-C-23 · ccompat-c3-schema-vocabulary: one serial commit for keywords, '...', C3 AST/IR fields, goto kinds, targets.toml C3 columns, hosted/intrinsic rows, VS Code grammar, pending tables, six boundary records

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (batch 0) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-c3-schema-vocabulary`
- **Depends on:** [CL-C-22](#cl-c-22); [CL-C-03](#cl-c-03); [CL-C-00](#cl-c-00)
- **Why not now:** Needs C2 and Stage 18 (type_name, CompoundLiteral, TypeExpr.elements, record-member owner, three-way query), C4's targets.toml, and the reconciled goto schema (CL-C-00).
- **Parallel-safe with:** CX-C-02

**Owned paths**

- src/language/grammar.ebnf (@keywords inline restrict _Alignas _Alignof _Noreturn _Static_assert _Thread_local va_arg; @operators '...')
- src/language/ast.asdl (TypeExpr is_restrict/is_register/is_auto/is_thread_local/parts and type_part; FunctionDecl is_inline/is_noreturn/is_variadic; StaticAssertDecl/Stmt/Member; AlignofExpr; VaArgExpr; GotoStmt(name, name_line, name_col); LabelStmt(name))
- tools/compiler_codegen/ast.py with regenerated Node.btrc and syntax/ast/generated.py (hotspot)
- src/language/targets.toml (C3 columns, [target_layout], [[layout_typedefs]]), src/language/hosted_abi.toml, src/language/intrinsic_effects.toml (`va_*` rows), tools/compiler_codegen/hosted_abi.py and intrinsic_effects.py
- src/compiler/btrc/syntax/Identity.btrc (renderer; hotspot), src/compiler/python/ir/nodes.py, ir/verifier.py (IRGoto/IRLabel refused until Stage 20), src/compiler/btrc/ir/Model.btrc
- parser.py and Parser.btrc pending-refusal tables (no goto entry, per CL-C-00)
- src/devex/vscode/config/grammar.json, src/devex/lsp/features/completion.py (keyword tables)
- src/tests/fixtures/compiler_boundaries/ (six records), src/tests/btrc/fixtures/c_compat_probe/c3_c4.toml (D-1, D-2, D-3, D-5, D-8, D-9, D-12 known-divergence probes)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- src/stdlib/btrc.symbols, btrc.lock, src/devex/lsp/catalog/generated.py
- `src/runtime/c/**` and manifest (the runtime metadata channel reads manifest.toml, unchanged)

**Steps**

1. Main session, serial. One read-only pre-drafter re-verifies every line reference in c-vocabulary-specifiers.md against the post-Stage-18 tree; two adversarial reviewers check the diff.
2. Vocabulary: the seven C11 keywords plus va_arg, and the '...' operator; TokenKinds derive from the grammar. Confirm no identifier collides (C11_RESERVED_NAMES / c11ReservedName already refuse the seven; grep the stdlib, examples and BTRSmith for va_arg).
3. ASDL and generation: all C3 fields and kinds plus the reconciled goto kinds. Check that sizeof(Node) stays 760 bytes (seven bools in padding). Both renderers and the AstStructure/coverage checks.
4. IR: IRFunctionDef/Decl is_inline/is_noreturn/is_variadic, IRStaticAssert with IRModule.static_asserts, the alignment fields, IRAlignof, IRVaArg, IRGoto/IRLabel. The verifier refuses IRGoto/IRLabel until Stage 20.
5. Specs: the targets.toml C3 columns (data model, char/wchar_t signedness, long double and max_align_t cells, [target_layout], [[layout_typedefs]]) with generator rules; hosted_abi.toml and intrinsic_effects.toml `va_*` rows; VS Code grammar and LSP keyword tables.
6. Pending tables: equal in both parsers, keyed by token kind, covering the nine new tokens plus auto and register, on Stage 14's hooks. Record the known-divergence probes.
7. Re-capture the six boundary records (surface.python.ast, surface.btrc.ast and the four Python IR records) with the reason from the design. Linux memory by Stage 15's method; the Mac row is MAC-C-05. Lane report.

**Acceptance**

- [ ] make compiler-codegen-generate then make generated-check clean (renderer coverage, generator rules)
- [ ] boundary-check: exactly six records changed with the recorded reason; test_boundary_manifest.py, test_boundary_renderers.py green
- [ ] make extension and src/tests/lsp/test_extension_assets.py green (VS Code grammar matches @keywords); make test-lsp
- [ ] No program changes behavior: corpus through both compilers unchanged; pending-refusal probes recorded
- [ ] make bootstrap fixed point; zero warnings; Linux memory ≤0.3% (Python fallback if >1%)
- [ ] Reviewers leave no unresolved blocking finding

**Risks**

- targets.toml layout/data-model columns overlap Stage 24's planned columns (bucket 3): one writer at a time; whichever lands second consumes the other's columns rather than adding a twin.
- Seven new reserved words could break Codex stdlib code that names something inline/restrict (already refused by C11_RESERVED_NAMES) or va_arg (D27 rule).

<a id="cl-c-24"></a>

##### CL-C-24 · C3 commit A: declaration-specifier shared owners (one specifier loop, function-specifier slot, lookahead, position table, value_type)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (batch 0) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-c3-schema-vocabulary` (shared-owner commit A)
- **Depends on:** [CL-C-23](#cl-c-23)
- **Why not now:** Follows the vocabulary commit.
- **Parallel-safe with:** MAC-C-05

**Owned paths**

- parser.py _parse_type_expr, _scan_type_expr, _QUALIFIERS, _DEFERRED_C_SPECIFIERS/_refuse_deferred_c_specifier, _parse_top_level_item, _parse_function_or_var_decl, _lookahead_is_var_decl, _parse_param_list/_parse_param, _is_cast, _is_sizeof_type; src/compiler/python/syntax/tokens.py (TYPE_KEYWORDS restrict)
- Parser.btrc parseType, scanTypeEnd, deferredCSpecifierMessage, parseTopLevelItem, parseFunctionOrVarDecl, lookaheadIsVarDecl, parseParamList, parseParam, isCast, isSizeofType, isTypeKeyword/isTypeQualifier
- Python TypeSystem.validate_declaration_specifiers and value_type (analyzer/types.py) and the storage strip sites (types.py:1118, expressions.py:1291, gpu.py:358, declarations.py:803-804)
- btrc TypeValidator.validateDeclarationSpecifiers, TypeShape.valueType (syntax/Types.btrc) and the strip sites (CallableSignature.component, ir/lowering/Callables.btrc:327-328, analyzer/Expressions.btrc:334-335, validation/Types.btrc:449-450, validation/Expressions.btrc:138-139, validation/Names.btrc:380-381)
- src/tests/btrc/test_c3_pending_refusals.py (new), specifier parse-parity test, position-table/value_type/parts-reader contract tests

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One specifier loop per parser reads storage classes, function specifiers (only on the top-level path, through the _pending_function_specifiers / pendingFunctionSpecifiers slot, asserted empty on entry), qualifiers on either side of the base, `*` qualifier levels and _Alignas(...).
2. One lookahead recognizer skips every specifier and balanced _Alignas group in every mode. auto followed by IDENT '=' gets the targeted inference refusal.
3. The position table is the single source of specifier-position refusals. value_type removes storage classes and AlignmentSpecifiers at the listed strip sites, and qualifier clearing stays as today until r15a.
4. Changes no program's behavior; the contract tests fail on any other site that clears a storage flag or reads parts.
5. Commit; lane report.

**Acceptance**

- [ ] test_c3_pending_refusals.py green (tables equal; each pending token refused at its position in top-level, statement, member, parameter, cast and sizeof contexts)
- [ ] The specifier parse-parity test (cast, sizeof, generic argument, lambda parameter, compound-literal head, struct member, class member and parameter positions) and the three contract tests pass in both compilers
- [ ] No recorded probe diagnostic changes; corpus unchanged; zero warnings; make bootstrap fixed point

**Risks**

- The slot leak (struct S { inline int x; }; int f() {…}) must be impossible; the assertion and a test pin it.

<a id="cl-c-25"></a>

##### CL-C-25 · C3 commit B1: TargetLayout widths, typed integer-constant evaluator, constant lowering to plain C operators (D-2, D-3, D-4, D-9)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (batch 0) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-c3-schema-vocabulary` (shared-owner commit B, part 1: target widths, typed evaluator, constant lowering)
- **Depends on:** [CL-C-24](#cl-c-24)
- **Why not now:** Follows commit A.

> **Review change:** If Stage 24's `CL-P1-05` lands first (§7 Q2, Q7), consume its `CIntegerWidths.for_target` and target rows instead of adding a twin; never run beside `CL-P1-05` (§10 X2).

**Owned paths**

- src/compiler/python/abi/hosted.py (TargetLayout), analyzer/types.py (CIntegerWidths.for_target, NumericLiteralSemantics), application/pipeline.py:470, analyzer/analyzer.py:40
- src/compiler/python/analyzer/expressions.py (IntegerConstantEvaluator; integer_constant_expression and _apply_constant_binary), analyzer/statements.py (_validate_array_bound)
- src/compiler/btrc/analyzer/HostedAbi.btrc (TargetLayout), syntax/Literals.btrc (IntegerLiteral.typeName takes widths), analyzer/validation/Constants.btrc (ConstantValidator, SemanticIntegerConstant type, builtinCastRange/abiCastRange)
- constant-lowering sites: TranslationUnitLowerer/DeclarationLowerer enum values, ControlFlowLowerer and ir/lowering/ControlFlow.btrc case labels, StorageLowerer/TranslationUnitLowerer/DeclarationLowerer.emitGlobalVar extents and static initializers (lower_constant_expression / lowerConstantExpression)
- src/tests/basics/ConstantContextDivision.btrc (new), src/tests/btrc/test_integer_constant_evaluator_parity.py (new), c3_c4.toml D-2/D-3/D-4/D-9 probes

**Must not touch**

- LayoutModel/SizeofOperand/pack (CL-C-26)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Main session or one dedicated agent; one commit, Python then btrc. This splits the design's commit B (pending owner approval; see CL-C-00).
2. TargetLayout: an immutable owner over the generated target rows, selected by PackageTarget. Widths for literal typing and cast ranges come from the row (D-4). A host outside the six targets keeps today's host widths.
3. Typed evaluator: C2's three kinds plus (bits, signedness) and the blocking subexpression. Identifier order: scope-bound names first, then enum constants, source macros, native constants, hosted names, and finally upper-case presumed macros (D-9). Semantics follow C11 6.4.4, 6.3.1.1, 6.3.1.8, 6.5 and 6.6 at target widths: char constants with target signedness (D-3), short-circuit, the not-constant cases, and wrapping and arithmetic right shift as gcc and clang define them. sizeof stays 'cannot evaluate' until B2.
4. Constant lowering emits plain C operators (no __btrc_div/__btrc_mod) for evaluable and cannot-evaluate constants at the listed sites (D-2). VLA bounds keep the checked helpers.
5. Tests: ConstantContextDivision.btrc under gcc and clang -pedantic-errors -Werror; test_integer_constant_evaluator_parity.py (~120 expressions vs gcc and clang); the D-4 front-end case (long value = 2147483648 with --target linux-aarch64 vs windows-x86_64); flip the four probes.
6. Cross-target: a --target windows-x86_64 transpile of cli/WindowsMain.btrc with no new diagnostic, and the stdlib Windows transpile, both from Linux. gh workflow run ci.yml/macos.yml/windows.yml on the branch. Constant-evaluator parity reviewer; lane report.

**Acceptance**

- [ ] test_integer_constant_evaluator_parity.py green: both compilers equal to gcc and clang on every row
- [ ] ConstantContextDivision.btrc passes both compilers under strict C11 (Linux CI 8 cells)
- [ ] D-2, D-3, D-4, D-9 probes flipped; the windows-x86_64 transpiles of WindowsMain and the stdlib show no new diagnostic
- [ ] ci.yml, macos.yml and windows.yml green on the branch (run ids); make bootstrap fixed point; zero warnings

**Risks**

- Changing literal typing to target widths can change btrcc's own C on a cross target; the bootstrap is host-target, so also diff the Windows transpile.
- The split from the design's single commit B needs owner approval (open question).

<a id="cl-c-26"></a>

##### CL-C-26 · C3 commit B2: LayoutModel, SizeofOperand owner, layout cross-check asserts, #pragma pack moved to the analyzer

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (batch 0) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-c3-schema-vocabulary` (shared-owner commit B, part 2: layout model, sizeof operands, cross-check, pack)
- **Depends on:** [CL-C-25](#cl-c-25)
- **Why not now:** Follows B1 (evaluator).

**Owned paths**

- src/compiler/python/analyzer/aggregates.py (LayoutModel), SizeofOperand owner, ir/lowering/expressions.py (_lower_sizeof uses it), ir/optimizer.py (static_asserts roots), backend/c_emitter.py (IRStaticAssert; hotspot)
- src/compiler/btrc/analyzer/validation/Constants.btrc (SemanticLayoutModel), SizeofOperand.emittedType, ir/lowering/Expressions.btrc, ir/Emitter.btrc (hotspot), ir/optimization/Optimizer.btrc
- native layout index: frontend/native_imports.py, frontend/NativeImports.btrc, AnalyzedProgram/Analyzed
- pack owner: Python and btrc DeclarationRegistry; readers translation_unit.py:826-852 and ir/lowering/Declarations.btrc:81-138
- src/tests/python/test_target_layout_table.py (new), layout cross-check tests

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. LayoutModel: known layouts (scalars, enums, pointers, fixed arrays, tuples, btrc structs and unions by C11 placement with FAM, anonymous members, the union rule, pack and member _Alignas, typedef chains, layout_typedefs, native records from Clang bits) versus NoLayout(subject). A record inside its own body is incomplete.
2. SizeofOperand: one owner used by analysis and lowering (D-10's meaning kept: 'a' is char, comparisons are bool, array parameters are pointers, VLAs are not constant). sizeof and _Alignof of a known layout now evaluate in C2's constant consumers.
3. Cross-check: every consumed layout value emits IRStaticAssert(\<query> == N, 'btrc layout') at module level, or in place when it names a local, deduplicated per scope. When headers are imported, assert the target row's cells equal the reader's NativeBuiltin bits.
4. #pragma pack: DeclarationRegistry records each record's pack alignment, lowering reads it, and the three messages become analyzer diagnostics (re-recorded).
5. Tests: test_target_layout_table.py (clang -target \<triple> -ffreestanding -fsyntax-only on generated _Static_asserts for every present cell, six triples; host gcc; skip-ledger entry without clang); layout cross-check cases (char buf[sizeof(struct P)], a FAM struct, a union, an anonymous member, a tuple, size_t).
6. One D5 gate after B2 (plus B1's cross-target gates). gh workflow run macos.yml on the branch. Lane report.

**Acceptance**

- [ ] test_target_layout_table.py green for six triples (no unexplained skip)
- [ ] Every cross-check _Static_assert is accepted by gcc and clang (Linux CI 8 cells, macos.yml clang O0/O2)
- [ ] The pack diagnostics are identical in both compilers at the directive
- [ ] D5 batch gate green; make bootstrap fixed point (btrcc's own C gains cross-check asserts); zero warnings; macos.yml run id

**Risks**

- A wrong table cell now fails the C compile instead of diverging silently (intended); expect a few target-specific cell fixes.
- BTRSmith Windows frontend check is Mac-only (MAC-C-06).

<a id="cl-c-27"></a>

##### CL-C-27 · C3 r15b: inline, static inline, _Noreturn, the completion owner and D-7 missing-return/lambda wording

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (wave 1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r15b-inline-noreturn`
- **Depends on:** [CL-C-26](#cl-c-26); [CL-C-02](#cl-c-02)
- **Why not now:** Lanes fork after commit B (CL-C-26).
- **Parallel-safe with:** CL-C-28, CL-C-29, CL-C-30

**Owned paths**

- parser function prologue (parser.py, Parser.btrc; shared parser rule)
- src/compiler/python/analyzer/flow.py (completion owner), statements.py (:763, :817-819, :1462-1466, :1491, :1593-1596), declarations.py, realtime.py
- src/compiler/python/ir/lowering/translation_unit.py (:210-258, :336-345), functions.py, exceptions.py:1563, application/modules.py (SharedDeclarations, ProgramInterface, setjmp solver; hotspot), backend/c_emitter.py and ir/verifier.py
- btrc validation/ControlFlow.btrc, validation/Expressions.btrc:775, validation/Declarations.btrc:802, analyzer/Realtime.btrc, ir/lowering/Declarations.btrc, Functions.btrc, Statements.btrc:1043, Lowerer.btrc:257-277, pipeline/ModuleUnits.btrc (hotspot), ir/Emitter.btrc (hotspot)
- src/tests/c_compat/FunctionSpecifiers.btrc, src/tests/btrc/test_completion_owner_parity.py (new), the inline-site contract test, a module-unit inline-edit reuse test

**Must not touch**

- flow/ownership/setjmp code beyond the completion owner (goto runs later)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Lane stage19/r15b with its own btrcc; one commit, Python then btrc.
2. inline / static inline / extern inline per D20: the inline definition sits in the shared declarations every unit sees and exactly one owning unit emits the external definition; static inline stays unit-local; the C11 6.7.4p3 consequences are documented refusals.
3. _Noreturn: FunctionDecl.is_noreturn flows into the completion owner and IRCall.never_returns; a _Noreturn body must not return.
4. One completion owner per compiler with the full rule table (D-13's deletion already landed in CL-C-02); unify the missing-return and lambda wording (D-7).
5. Tests: FunctionSpecifiers.btrc (two modules, --module-units --emit-units and whole program, linked with gcc and clang at -O0 and -O2); a module-unit test where editing an inline body invalidates its copies; test_completion_owner_parity.py; negatives; delete this lane's pending-table entries.
6. One parity reviewer; gh workflow run macos.yml on the branch (ld64 link semantics); lane report.

**Acceptance**

- [ ] Inventory r15b rows PASS or refused-on-purpose in both compilers; pending entries for inline/_Noreturn removed
- [ ] FunctionSpecifiers.btrc passes both compilers in both build modes under strict C11; test_completion_owner_parity.py green
- [ ] macos.yml green on the branch; zero warnings; make bootstrap fixed point

**Risks**

- Holds the ModuleUnits/modules.py and emitter hotspots; r15c and r15d also touch emitters, so rebase in merge order r15b, r15c, r15d, r16, stragglers.

<a id="cl-c-28"></a>

##### CL-C-28 · C3 r15c: _Static_assert at file, block and member positions, with the evaluator parity reviewer

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (wave 1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ccompat-r15c-static-assert`
- **Depends on:** [CL-C-26](#cl-c-26)
- **Why not now:** Needs the layout model and IRStaticAssert from commit B.
- **Parallel-safe with:** CL-C-27, CL-C-29, CL-C-30

**Owned paths**

- parser.py and Parser.btrc top-level, statement and record-body dispatch (shared parser rule)
- Python analyzer statements.py, declarations.py, aggregates.py, calls.py (static_assert refusal), frontend/imports.py, translation_unit.py, application/modules.py (closure; hotspot, after r15b), optimizer.py roots, c_emitter.py
- btrc validation/Declarations.btrc, Constants.btrc, Calls.btrc, frontend/Visibility.btrc, ir/lowering/Declarations.btrc and Statements.btrc, pipeline/ModuleUnits.btrc (closure, collectText), ir/optimization/Optimizer.btrc, ir/Emitter.btrc
- src/tests/c_compat/StaticAssert.btrc, src/tests/btrc/test_layout_model_parity.py (new), negatives

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. Parse StaticAssertDecl, Stmt and Member with StringConcat message parts. Conditions go through the typed evaluator; refuse non-constant conditions, unknown layouts (naming the type), macros, a record measured inside its own body, and the hosted static_assert(...) (D-8).
3. Strict imports and module-unit closures follow static_asserts (I-3). Lower to IRStaticAssert, and emit it again in C.
4. Tests: StaticAssert.btrc (file/block/member positions; structs, unions, anonymous members, a FAM, tuples, size_t, a native record from a reader fixture); a struct used only by an assertion under strict imports and --module-units; test_layout_model_parity.py.
5. Constant-evaluator parity reviewer; lane report.

**Acceptance**

- [ ] Inventory r15c rows PASS; D-8 probe flipped; every r15c refusal identical (message and position)
- [ ] StaticAssert.btrc passes both compilers; test_layout_model_parity.py green under gcc and clang
- [ ] Zero warnings; make bootstrap fixed point

**Risks**

- Module-unit closure edits touch the ModuleUnits hotspot after r15b; rebase in merge order.

<a id="cl-c-29"></a>

##### CL-C-29 · C3 r15d: _Alignas and _Alignof

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (wave 1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ccompat-r15d-alignment`
- **Depends on:** [CL-C-26](#cl-c-26)
- **Why not now:** Needs commit A's AlignmentSpecifier parse and commit B's layout model.
- **Parallel-safe with:** CL-C-27, CL-C-28, CL-C-30

**Owned paths**

- parser.py _parse_unary (:1655) and Parser.btrc parseUnary (:1782) (shared parser rule)
- Python aggregates.py (member layout), expressions.py (AlignofExpr), storage.py, declarations.py (agreement), gpu.py, ir/lowering/expressions.py, CTypeLowerer, c_emitter.py
- btrc validation/Storage.btrc, validation/Expressions.btrc, validation/Names.btrc, analyzer/GPU.btrc, ir/lowering/Expressions.btrc, ir/Emitter.btrc
- src/tests/c_compat/Alignment.btrc, c3_c4.toml x-alignof rows, test_c_compatibility_inventory.py KNOWN_DIVERGENCES

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. _Alignas(type or constant) entries in TypeExpr.parts with the strictest one winning (C11 6.7.5p6). Refused on bit-fields, under pack, with register, and in positions the table forbids. _Alignof(T) is AlignofExpr; _Alignof(expression) is refused with a targeted message (x-alignof).
3. The IR carries the folded effective alignment on IRVarDecl, IRGlobalDecl and IRStructField, plus IRAlignof.
4. Tests: Alignment.btrc (address modulo, sizeof/_Alignof of aligned structs, _Alignas(2) _Alignas(8)); negatives; drop x-alignof-expression from KNOWN_DIVERGENCES; gh workflow run macos.yml on the branch; lane report.

**Acceptance**

- [ ] Inventory r15d and x-alignof rows PASS in both compilers; KNOWN_DIVERGENCES has no x-alignof entry
- [ ] Alignment.btrc passes on Linux gcc/clang and macos.yml clang (run id)
- [ ] Zero warnings; make bootstrap fixed point

**Risks**

- max_align_t and long double cells differ across targets (MinGW vs MSVC); keep cells the row omits as NoLayout.

<a id="cl-c-30"></a>

##### CL-C-30 · C3 r16: wide and UTF literals, long double (lexer, decoder, char16/32 emission, formatter literal rules)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (wave 1) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-r16-wide-literals-long-double`
- **Depends on:** [CL-C-26](#cl-c-26)
- **Why not now:** Needs the target layout columns (wchar_t, long double) from commit B.
- **Parallel-safe with:** CL-C-27, CL-C-28, CL-C-29

**Owned paths**

- src/compiler/python/lexer/lexer.py (read_number, _read_identifier, read_string, read_char, LiteralDecoder)
- src/compiler/btrc/lexer/Lexer.btrc, src/compiler/btrc/syntax/Literals.btrc
- parser.py _parse_sizeof/_parse_primary/import-path parser; Parser.btrc parseSizeof/parsePrimary (shared parser rule)
- Python analyzer/expressions.py, types.py (literal types, char16/32 sets), aggregates.py (r04 for wide arrays), statements.py, calls.py (print, f-strings), CTypeLowerer (uint_least16_t/uint_least32_t)
- btrc analyzer/Expressions.btrc, Operators.btrc, validation/Expressions.btrc, ir/lowering/Types.btrc
- src/devex/formatter/lexing.py (:84-123) and engine.py (_needs_space :754-800)
- src/tests/c_compat/WideAndLongDoubleLiterals.btrc, test_lexer_literals_extra.py, btrc/test_lexer_diagnostics.py, formatter tests, c3_c4.toml r16 and x-utf8-string rows

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Lane stage19/r16 (the same agent then does the stragglers, CL-C-31); one commit, Python then btrc.
2. The prefixes L/u/U/u8 stay in the token's raw text. 1.5L is a FLOAT_LIT with its suffix kept. Decoding is per code unit at target widths. char16_t/char32_t are emitted as uint_least16_t/uint_least32_t. r04 extends to wchar_t, char16_t and char32_t arrays.
3. The formatter mirrors the lexer's prefix rules, so L"ab" is never split into L "ab".
4. Tests: WideAndLongDoubleLiterals.btrc (target-neutral output); front-end-only extent cases for the windows and linux targets; negatives; lexer and formatter tests.
5. gh workflow run ci.yml/macos.yml/windows.yml on the branch (wchar_t is 16-bit on Windows); parity reviewer; lane report.

**Acceptance**

- [ ] Inventory r16 and x-utf8-string rows PASS in both compilers
- [ ] WideAndLongDoubleLiterals.btrc passes both compilers under strict C11; the windows-target extent cases give identical results in both compilers
- [ ] make format-check (format-btrc-check) green on the new corpus; formatter tests green
- [ ] All three workflows green on the branch (run ids); zero warnings; make bootstrap fixed point

**Risks**

- Python columns count code points and btrc bytes: keep positional parity tests ASCII-only.

<a id="cl-c-31"></a>

##### CL-C-31 · C3 stragglers: sizeof unary, hex floats, .5/1./1.f/1.e3, pointer +=/-=, sizeof (T){…}

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (wave 1, same agent as r16) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-x-expression-stragglers`
- **Depends on:** [CL-C-30](#cl-c-30)
- **Why not now:** Shares the lexer with r16; the same agent lands it next.
- **Parallel-safe with:** CL-C-27, CL-C-28, CL-C-29

**Owned paths**

- lexer.py / Lexer.btrc number forms; Literals.btrc
- parser.py _parse_sizeof/_parse_primary; Parser.btrc parseSizeof/parsePrimary (shared parser rule)
- Python analyzer/expressions.py (pointer += operator rule); btrc Operators.btrc, validation/Expressions.btrc
- src/devex/formatter/lexing.py (leading/trailing dot, hex float)
- src/tests/c_compat/SizeofAndFloatForms.btrc, lexer diagnostics tests, c3_c4.toml x-sizeof-expression, x-hex-float, x-pointer-compound-assignment rows, KNOWN_DIVERGENCES

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. sizeof unary-expression; hex floats (0x1p3, with 0x1.8 lexing as a hex float instead of a tuple member); .5, 1., 1.f and 1.e3 typed as C does (D-5), while 5.toString() stays a call and c?.5:1 and 0...2 lex correctly; pointer += and -=; sizeof (T){…} parses.
3. Tests: SizeofAndFloatForms.btrc; lexer diagnostics for 0x1p, 0x.p1 and 0x1.8; drop x-hex-float-without-exponent from KNOWN_DIVERGENCES; parity reviewer; lane report.

**Acceptance**

- [ ] Inventory x-sizeof-expression, x-hex-float, x-pointer-compound-assignment rows PASS; D-5 probe flipped; KNOWN_DIVERGENCES has no x-hex-float entry
- [ ] SizeofAndFloatForms.btrc passes both compilers; both lexers agree on c?.5:1 and 0...2
- [ ] Formatter keeps 1.f and .5 intact (format-btrc-check); zero warnings; make bootstrap fixed point

**Risks**

- A new number form could change how an existing member access on a literal lexes; the corpus and lexer parity check (verify-lexer) must stay green.

<a id="cl-c-32"></a>

##### CL-C-32 · C3 r15a: qualifiers on the base type, per-level pointer qualifiers (D-1 flip), register/auto/_Thread_local, D-11, D-12, D-7 const wording

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (declarator lane) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 14 agent-hours
- **PLAN items:** `ccompat-r15a-qualifiers-storage-classes`
- **Depends on:** [CL-C-26](#cl-c-26)
- **Why not now:** Takes the first free writer slot after commit B; merges after the stragglers (batch 3).
- **Parallel-safe with:** CL-C-33

**Owned paths**

- Python analyzer/storage.py (:101-130, :206-228, :330-420), types.py (declaration_const_depths, outer-qualifier check, format_type, TypeIdentity.shape_key/_encode_type, generic_argument_problem, compose_type_expr, strip_outer_storage, add_outer_pointer), declarations.py, expressions.py, statements.py, ownership.py (capture), realtime.py, gpu.py
- Python lowering: CTypeLowerer, ir/lowering/storage.py, functions.py, expressions.py:662-715, exceptions.py:839, CType.qualify_object (ir/nodes.py), IRVerifier, c_emitter.py, application/modules.py (thread-local externs)
- btrc validation/Storage.btrc, Types.btrc, Ownership.btrc, Borrows.btrc, Calls.btrc, Realtime.btrc, GPU.btrc; analyzer/Types.btrc; syntax/Types.btrc; syntax/Identity.btrc (qualifierBits, appendEncoded, decode, encodable, genericArgumentProblemInner; hotspot)
- btrc lowering: ir/lowering/Types.btrc, Expressions.btrc (:1238-1290, :3853-3862), Declarations.btrc, Functions.btrc, Concurrency.btrc, Calls.btrc, ownership/Operands.btrc, ir/optimization/setjmp/Safety.btrc:51, ir/Emitter.btrc, pipeline/ModuleUnits.btrc
- src/devex/lsp/features/symbols.py, hover.py
- src/tests/c_compat/PointerQualifiers.btrc, StorageClasses.btrc; test_type_identity_contract.py; flipped tests test_ir_declarations.py:183-221, test_qualifier_provenance_contracts.py:35-43, test_array_storage_codegen_contract.py:177-197, test_exception_codegen_contracts.py:296,407, test_setjmp_continuation_contract.py:164,198, test_emitter_whitebox.py:94

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**` (report any volatile `T*` hit; D27 forbids writing it)
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Lane stage19/r15a with its own btrcc; one commit, Python then btrc.
2. Qualifiers before or after the base qualify the base type. Qualifiers after the k-th `*` form PointerQualifiers(k). This flips D-1: volatile `int*` p now means a pointer to volatile int; grep the stdlib, examples and BTRSmith and record hits (none today).
3. Storage classes: register (a scalar rule, and a post-optimization rule that forbids taking a register object's address), auto as a block-scope no-op, and _Thread_local with static or extern (module-unit externs).
4. D-11: btrc uses value temporaries for identifier roots in compound assignment, and directLvaluePointerType adds restrict/volatile. D-12: qualified generic arguments through typedefs are refused in both compilers. D-7: unify the const-modification and const-discard wording.
5. Tests: PointerQualifiers.btrc, StorageClasses.btrc (register with +=, ++ and try; auto; a _Thread_local counter across two Threads); --module-units with a _Thread_local global; test_type_identity_contract.py; flip the listed tests to C semantics; LSP renders qualifiers.
6. gh workflow run macos.yml on the branch (Darwin TLV for _Thread_local). Parity reviewer. The batch-3 BTRSmith rerun for the D-1 flip is MAC-C-07. Lane report.

**Acceptance**

- [ ] Inventory r15a and x-const-pointer rows PASS; D-1 and D-12 probes flipped; refusals identical
- [ ] PointerQualifiers.btrc and StorageClasses.btrc pass both compilers under strict C11; the _Thread_local test passes on Linux and macos.yml (run id)
- [ ] Flipped tests green; test_type_identity_contract.py green (unqualified encodings byte-identical)
- [ ] Zero warnings; make bootstrap fixed point; D5 gate for batch 3

**Risks**

- D-1 silently changes the meaning of any volatile `T*` written meanwhile (D27 rule).
- Touches ownership and setjmp code: goto (CL-C-35/36) must not be in flight.

<a id="cl-c-33"></a>

##### CL-C-33 · C3 r14: variadic function definitions (..., va_list flow, va_arg, borrowed managed arguments)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (own batch) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-r14-variadic-definitions`
- **Depends on:** [CL-C-26](#cl-c-26)
- **Why not now:** Takes the next free writer slot after commit B; merges as its own batch after r15a.
- **Parallel-safe with:** CL-C-32

**Owned paths**

- parser.py _parse_param_list (:570) / Parser.btrc parseParamList (:1124) (shared parser rule)
- Python analyzer/calls.py, flow.py (va_list states), realtime.py, gpu.py; ir/lowering/functions.py, calls.py (plan_evaluation :293), exceptions.py (planner assertion); c_emitter.py
- btrc validation/Calls.btrc, ControlFlow.btrc, Realtime.btrc; ir/lowering/Functions.btrc, Calls.btrc, ownership/Calls.btrc:94; ir/optimization/setjmp/Analysis.btrc and Safety.btrc; ir/Emitter.btrc
- src/devex/formatter tests (', ...' fixture only)
- src/tests/c_compat/VariadicDefinitions.btrc; realtime classification tests; c3_c4.toml row 14

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. One commit, Python then btrc.
2. FunctionDecl.is_variadic and VaArgExpr(expr, type) via the va_arg keyword. Managed variadic arguments are borrowed for the call. va_arg reads plain C types only.
3. va_list flow: never hoisted or copied by the evaluation planners; a call that also reads ap is refused; a verifier rule limits where a va_list value may appear; try interactions are refused (a list declared before a try, a va_list parameter in a function with a try, va_start inside a try). Revisit r07's variadic-pointee refusal for function-pointer types.
4. Tests: VariadicDefinitions.btrc (sum(int n, ...), a logger with vfprintf(stderr, prefix(), ap), va_copy, promotions, a borrowed string read as `char*`); a cross-group --module-units call; extended realtime tests; test_native_variadic_calls.py stays green.
5. gh workflow run ci.yml/macos.yml/windows.yml on the branch (va_list ABI differs per platform); parity reviewer; lane report.

**Acceptance**

- [ ] Inventory row 14 PASS in both compilers; every r14 refusal identical
- [ ] VariadicDefinitions.btrc passes both compilers under strict C11 on Linux CI and macos.yml; Windows bootstrap green
- [ ] test_native_variadic_calls.py unchanged; zero warnings; make bootstrap fixed point

**Risks**

- Touches flow, ownership and setjmp: goto must start after this merges; it shares Safety.btrc with r15a (rebase r14 on r15a).

<a id="cl-c-37"></a>

##### CL-C-37 · ccompat-c3-integrate: delete pending tables, complete known-language-gaps, full matrix, memory re-measure (r11 merged last)

- **Owner:** Claude · **Group:** C · **Stage:** Stage 19 (exit, after Stage 20 merges r11) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ccompat-c3-integrate`
- **Depends on:** [CL-C-27](#cl-c-27); [CL-C-28](#cl-c-28); [CL-C-29](#cl-c-29); [CL-C-30](#cl-c-30); [CL-C-31](#cl-c-31); [CL-C-32](#cl-c-32); [CL-C-33](#cl-c-33); [CL-C-36](#cl-c-36)
- **Why not now:** Needs every C3 lane and the goto commit merged (r11 last).
- **Parallel-safe with:** CX-C-03

**Owned paths**

- parser.py and Parser.btrc pending-refusal tables (deleted)
- src/tests/btrc/test_c3_pending_refusals.py (retired or reduced)
- docs/known-language-gaps.md (C3 items listed in c-vocabulary-specifiers.md step 4.2)
- docs/design/c-compatibility.md (C3 and goto status)
- src/tests/btrc/fixtures/c_compat_probe/c3_c4.toml

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. Delete both pending tables (no entries remain).
2. Complete known-language-gaps: every † row; row 20's va_arg note; the new meaning of volatile; the inline subset; _Alignas limits and the platform malloc guarantee; the register scalar rule; D-10's sizeof meaning; ?. before a digit; member access on hex literals; the implementation-defined behavior btrc assumes (char signedness per target, wrapping signed conversion, arithmetic right shift, signed plain-int bit-fields).
3. Re-run the inventory: every C3 row PASS or refused-on-purpose, and no C3 entry in KNOWN_DIVERGENCES.
4. Linux memory re-measure by Stage 15's method from the vocabulary commit's parent; the Mac row is MAC-C-08.
5. D5 batch gate, push, and record the ci.yml/macos.yml/windows.yml run ids on main.

**Acceptance**

- [ ] test_c_compatibility_inventory.py green with every C3 row PASS or refused-on-purpose; KNOWN_DIVERGENCES holds no C3 entry
- [ ] Full matrix green on Linux (make test, make bootstrap, make test-c11, lint, format-check, generated-check, extension, test-lsp)
- [ ] Linux memory delta ≤0.3% (≤1% recorded)
- [ ] ci.yml, macos.yml and windows.yml green on main (run ids)

**Risks**

- Stage 19 and 20 are not exited until MAC-C-08 (Darwin test-c11, BTRSmith, Mac memory) is green.

#### Stage 20: goto and labels, alone (approved, D19)

<a id="cl-c-34"></a>

##### CL-C-34 · Stage 20 read-only prep: goto fixture drafts with verified positions and the Python contract refined against the post-C3 code

- **Owner:** Claude · **Group:** C · **Stage:** Stage 20 (read-only prep) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ccompat-r11-goto-labels` (read-only fixtures and contract drafting)
- **Depends on:** [CL-C-23](#cl-c-23)
- **Why not now:** Needs the GotoStmt/LabelStmt kinds and IRGoto/IRLabel from the vocabulary commit, so positions and signatures are checked against real code.
- **Parallel-safe with:** CL-C-27, CL-C-28, CL-C-29, CL-C-30, CL-C-31, CL-C-32, CL-C-33

**Owned paths**

- scratch branch stage20/goto-prep (never merged): fixture drafts and a JSON position table

**Must not touch**

- any production source, test or doc on main (read-only packet)

**Steps**

1. Two read-only agents in parallel.
2. Agent 1: draft the positive cleanup programs and the unsafe-path negatives R1-R18 and P1, reusing Stage 14's VLA cases. Record each expected message and line:col and re-verify every position against the reference parser's tokens.
3. Agent 2: refine the Python contract signatures (JumpScopeIndex build/target/enclosing/entered_declarations/reach_start, the plain-value owner, is_variably_modified, termination predicates with targeted names, the jump-body marker) against the code after C3's lanes.
4. Hand both to the implementer.

**Acceptance**

- [ ] Fixture drafts cover every row of c-goto-labels.md 'Refusals' plus the throw-after-goto and fall-through cases; position table reviewed
- [ ] Contract signature notes name the current file and line of every owner the implementer will touch

**Risks**

- Signatures may drift while r15a and r14 are in flight; agent 2 re-checks after they merge.

<a id="cl-c-35"></a>

##### CL-C-35 · Stage 20 goto Python half: JumpScopeIndex, plain-value owner, rules R1-R18, lowering with scope release, setjmp regions, LSP/formatter/docs

- **Owner:** Claude · **Group:** C · **Stage:** Stage 20 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-r11-goto-labels` (Python half)
- **Depends on:** [CL-C-27](#cl-c-27); [CL-C-32](#cl-c-32); [CL-C-33](#cl-c-33); [CL-C-34](#cl-c-34); [CL-C-01](#cl-c-01)
- **Why not now:** Needs r15b's completion owner, and runs after r15a and r14, which edit flow, ownership and setjmp code that the goto design forbids sibling lanes to touch.
- **Parallel-safe with:** CX-C-01

**Owned paths**

- src/language/grammar.ebnf (block_item, label, goto_stmt, case_clause, braceless leading labels; RESERVED note)
- parser.py (IDENT ':' as LabelStmt, goto_stmt)
- src/compiler/python/analyzer/flow.py (JumpScopeIndex, termination with targeted names), types.py (is_plain_c_object, declaration_is_plain, is_variably_modified), program.py (jump_body_ids), statements.py, realtime.py (backward goto effect), gpu.py, declarations.py (label spelling)
- src/compiler/python/ir/lowering/statements.py, control_flow.py, exceptions.py, ownership.py, ir/verifier.py (V1-V4), backend/c_emitter.py, backend/wgsl_emitter.py
- src/devex/lsp/features/navigation.py, completion.py; src/devex/formatter/engine.py; src/tests/formatter/fixtures/GotoLabels.btrc
- src/tests/c_compat/ goto programs, c3_c4.toml row 11, GOTO_REFUSALS tests
- docs/known-language-gaps.md (goto section), README.md:2154, docs/design/c-compatibility.md link

**Must not touch**

- src/language/ast.asdl (schema already landed)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**` (none change)

**Steps**

1. Branch stage20/goto (one implementer for CL-C-35 and CL-C-36; nothing merges until CL-C-36 squashes one construct commit).
2. Parser and grammar: a LabelStmt is a statement-list item (C23 placement, emitted as 'name: ;'); goto_stmt; P1 errors.
3. JumpScopeIndex as a pure function of a callable body, cached per pass and rebuilt by lowering. Lookup and label rules R1-R11 and R15-R16; the plain-value owner (declared and initializer types); the variably-modified predicate; termination and unreachable-code rules with targeted names.
4. Lowering: leaving scopes releases owners innermost-first with release_scope(force=True) and discards cleanup registrations; a backward goto releases its frame's post-label owners; fall-through tail labels get IRLabel.falls_through; setjmp regions (V4); R17/R18; realtime marks a backward goto as a blocking effect; @gpu refused (R13).
5. LSP navigation and completion, the formatter label rule with the GotoLabels.btrc fixture, docs; then a handoff note with every message and position.

**Acceptance**

- [ ] Python half green: pytest src/tests/python src/tests/lsp src/tests/formatter plus the reference half of the goto refusal tests
- [ ] Every positive goto cleanup program passes make test-btrc with ARC witness counts
- [ ] Handoff note with the full diagnostic table for the btrc port

**Risks**

- The design's 'Stage 20 may overlap r15c/r15d/r16' is not used here (r15a/r14 conflict); if the owner prefers starting right after r15b, then r15a and r14 must wait for goto instead.

<a id="cl-c-36"></a>

##### CL-C-36 · Stage 20 goto btrc port, single construct commit, ARC and setjmp adversarial reviews

- **Owner:** Claude · **Group:** C · **Stage:** Stage 20 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ccompat-r11-goto-labels` (btrc port, reviews, exit)
- **Depends on:** [CL-C-35](#cl-c-35)
- **Why not now:** Ports CL-C-35 on the same branch.
- **Parallel-safe with:** CX-C-01

**Owned paths**

- src/compiler/btrc/parser/Parser.btrc
- src/compiler/btrc/analyzer/validation/ControlFlow.btrc (JumpScopeIndex), validation/Names.btrc (validateLabelName), analyzer/Types.btrc (plainCObject, plainDeclaration, variablyModified), analyzer/Models.btrc (VALIDATION_JUMP_BODY = 13), validation/Validator.btrc (replay), analyzer/Realtime.btrc, analyzer/GPU.btrc
- src/compiler/btrc/ir/lowering/Statements.btrc, ControlFlow.btrc (IRStatementSequence label scan), `ownership/*`, ir/Model.btrc (IRK_GOTO, IRK_LABEL), ir/Emitter.btrc (hotspot), ir/gpu/Wgsl.btrc, ir/optimization/setjmp/Analysis.btrc and Safety.btrc
- src/compiler/btrc/pipeline/ModuleUnits.btrc (collectNode skips IRK_GOTO/IRK_LABEL; validation-record-v5; hotspot)
- goto tests through both compilers (refusals, warm-cache record replay, record verification)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`; `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Port to btrc. Includes the jump-body marker journaled as VALIDATION_JUMP_BODY, the record context bump to validation-record-v5, and a body-emptiness check so bodies without goto pay one check.
2. CEmitter raises on V1-V4 after the optimizer. ModuleUnitDeclarations.collectNode skips both kinds. Labels use the stateless binding C name (HostedAbi.lexicalBindingCName).
3. Tests: warm-cache record replay and record verification; every refusal identical in both compilers; positives clean under the ARC witness; the fall-through case under gcc -Wimplicit-fallthrough.
4. Squash one construct commit. Two adversarial reviewers, one on the ARC checklist and one on the setjmp checklist (both in c-goto-labels.md 'Lanes'). Resolve every blocking finding.
5. gh workflow run ci.yml/macos.yml/windows.yml on the branch; lane report.

**Acceptance**

- [ ] Stage 20 exit: every unsafe-path negative test gives identical diagnostics in both compilers; positive cleanup programs are clean under the ARC witness
- [ ] Inventory row 11 PASS; boundary-check unchanged (311); generated-check, lint, format-check, extension, LSP and formatter tests green
- [ ] make bootstrap fixed point (btrcc's own C unchanged); zero warnings; make test-c11 cells green in Linux CI
- [ ] Both reviewers leave no unresolved blocking finding; all three workflows green on the branch (run ids)

**Risks**

- Re-issued cleanup registrations after a goto must exactly match the originals; the throw-after-goto fixtures are the proof.

#### Stage 21: C5 close-out

<a id="cl-c-38"></a>

##### CL-C-38 · Stage 21: x-pointer-to-array, decide (two reviewers), then land on Stage 18's row typedefs or record a refusal

- **Owner:** Claude · **Group:** C · **Stage:** Stage 21 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-c5-docs-final` (x-pointer-to-array row: land or documented refusal, as C2 and C3 deferred it to Stage 21)
- **Depends on:** [CL-C-37](#cl-c-37)
- **Why not now:** Stage 21 follows the C3/goto integration.
- **Parallel-safe with:** CL-C-39, MAC-C-08

**Owned paths**

- docs/design/c-compatibility.md (decision note)
- parser.py / Parser.btrc ((`*name)[N`] declarators; shared parser rule)
- Python analyzer/types.py, expressions.py, calls.py; ir/lowering/types.py
- btrc syntax/Types.btrc, analyzer validation Types/Expressions/Calls, ir/lowering/Types.btrc
- src/tests/c_compat/PointerToArray.btrc (if landed), c3_c4.toml x-pointer-to-array rows, test_c_compatibility_refusals.py (if refused)

**Must not touch**

- src/language/ast.asdl (array_pointer_depth already exists since C2)
- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. Decision note plus two read-only reviewers (C11 6.7.6.1/6.3.2.1 soundness; Python/btrc implementability). Recommendation: land it, since int (`*p)[3`] lowers to `R3*` p through the existing row-typedef registry.
2. If landing: both parsers accept (`*name)[N`] for locals, parameters, fields, typedefs, casts and sizeof. Rank≥2 decay becomes legal where C allows (&a, arithmetic, comparison, assignment, var, return), and the matching Stage 18 refusals are removed. Lower through row typedef pointers. Flip the rows and add PointerToArray.btrc.
3. If refusing: a targeted diagnostic identical in both compilers, a known-language-gaps 'rejects on purpose' row, the inventory status refused-on-purpose, and tests.
4. Lane report.

**Acceptance**

- [ ] x-pointer-to-array rows PASS or refused-on-purpose in both compilers; the reviewers leave no blocking finding
- [ ] If landed: PointerToArray.btrc passes both compilers under strict C11 (Linux CI 8 cells)
- [ ] Zero warnings; make bootstrap fixed point

**Risks**

- Lifting Stage 18's decay refusals widens the type system; generic/collection element positions stay refused unless separately justified.

<a id="cl-c-39"></a>

##### CL-C-39 · Stage 21 divergence sweep: close every remaining Python/btrc divergence from the C track

- **Owner:** Claude · **Group:** C · **Stage:** Stage 21 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ccompat-c5-docs-final` (exit: no known divergence remains)
- **Depends on:** [CL-C-37](#cl-c-37)
- **Why not now:** Stage 21 follows the C3/goto integration; the C3 evaluator must have landed for the const-bound case.
- **Parallel-safe with:** CL-C-38, MAC-C-08

**Owned paths**

- fix sites in both compilers for each item: parser.py/Parser.btrc (catch type parse), ir/optimizer.py and ir/optimization/Optimizer.btrc (sizeof-only globals), btrc ir/lowering tuple-instance collection, btrc analyzer/validation/Names.btrc (source-macro check for locals, local-name wording, validation order)
- src/tests/btrc/test_c_compatibility_integration.py and refusal tests
- src/tests/btrc/test_c_compatibility_inventory.py (KNOWN_DIVERGENCES must be empty)
- docs/known-language-gaps.md (open-gap rows closed or reclassified)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`
- generated files; `src/runtime/c/**`

**Steps**

1. catch (`string*` e): identical parse error in both compilers (the c1-integrate F8 deferral).
2. A global read only through sizeof(g) must not be dropped by the optimizer (both compilers).
3. const int N = 3; char t[N] = "abc": confirm commit B's D-9 makes it a VLA-with-initializer refusal in both compilers; pin it.
4. btrcc's discarded tuple-literal statement ((j = 1, i = i + 1);) must compile as the reference does.
5. goto findings: 5 (btrc source-macro collision check for locals, and local-name diagnostic wording and position), 7 (btrc block-entry name validation order vs Python), 8 (infinite loops refused as a missing return: fix or document). Re-check finding 4 is closed by r15b.
6. Decide and record the shared, non-divergent gaps: array sizes that do not wait for enum values, the X_V_Data forward declaration, a discarded managed result in a C-for header, realtime loop-bound gaps (fix if small, else keep documented).
7. Empty KNOWN_DIVERGENCES; lane report.

**Acceptance**

- [ ] KNOWN_DIVERGENCES == {} and test_c_compatibility_inventory.py green
- [ ] Each fixed item has a regression test through both compilers
- [ ] make test-btrc, make test-btrc-selfhost, make bootstrap, zero warnings

**Risks**

- Some items may grow (for example the btrc tuple-instance collector); a residual divergence can become a documented, tested refusal only if the owner agrees, because the exit requires no known divergence.

<a id="cl-c-40"></a>

##### CL-C-40 · ccompat-c5-docs-final: grammar preamble refusal section, known-language-gaps, README wording, final C matrix, PLAN/MEMORY close-out

- **Owner:** Claude · **Group:** C · **Stage:** Stage 21 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ccompat-c5-docs-final`
- **Depends on:** [CL-C-38](#cl-c-38); [CL-C-39](#cl-c-39)
- **Why not now:** Needs every row final (CL-C-38, CL-C-39).
- **Parallel-safe with:** CX-C-03

**Owned paths**

- src/language/grammar.ebnf (preamble comment section 'C that btrc rejects on purpose'; RESERVED note)
- docs/known-language-gaps.md
- README.md (C-compatibility wording per ref:3260; Reserved syntax line)
- docs/design/c-compatibility.md (final row matrix: rows 1-24 and x-rows → status and tests)
- PLAN.md (Stage 21 progress entry and bucket-2 exit record; integrator)

**Must not touch**

- docs/design/plan-reference.md
- `src/compiler/**` (no code change)
- `src/stdlib/GUI/**`, `src/stdlib/UI/**`, `src/stdlib/App/**`, `src/stdlib/Tray/**`

**Steps**

1. One docs agent drafts while the main session runs the exit gate.
2. grammar.ebnf preamble section listing the deliberate refusals (the comma operator outside for headers, reserved words, strict integer mixing, int-to-bool, returning a void expression), VLA forms, and _Atomic/_Complex deferral distinguished from Atomic\<T> (ref:3252).
3. README: 'C's syntax and semantics where they are safe, the rest reachable through #include', linking that section; drop goto/auto/register from Reserved syntax.
4. Final matrix table in c-compatibility.md; PLAN.md Stage 21 entry with the gate evidence; MEMORY.md update by the integrator.

**Acceptance**

- [ ] make generated-check, lint, test_grammar_drift.py and src/tests/lsp/test_extension_assets.py green (grammar comments only)
- [ ] Every inventory row is PASS or refused-on-purpose with a test in both compilers (test_c_compatibility_inventory.py)
- [ ] git diff --check clean; the final matrix agrees with the inventory

**Risks**

- Bucket 2 is not closed until MAC-C-09 (Darwin test-c11, BTRSmith) is green.

#### Stage 22: P0 entry, parity inventory, adaptations, toolchain matrix, device registry

<a id="cl-p1-01"></a>

##### CL-P1-01 · Stage 22 doc close-out: D6(c) and D27 amendments to the platform and UI ordering text

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 22 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 1.5 agent-hours
- **PLAN items:** D6 Stage-22 amendment: platform-parity.md section 8 and native-ui-parity.md 'Review checkpoint' (D6 assigns it to Stage 22; no separate item id)
- **Depends on:** [CL-UIA-01](#cl-uia-01)
- **Why not now:** After Gate 0 (CL-UIA-01), because it amends the D27 text that Gate 0 records.
- **Parallel-safe with:** CL-P1-02, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-01, MAC-P1-02

> **Writer note:** Depends on `CL-UIA-01`, because its own risk says D27 must be in PLAN.md first (§9 item 6). It starts right after Gate 0.

> **Review change:** Start-now flag corrected: it depends on `CL-UIA-01` (§10 P17).

**Owned paths**

- docs/design/platform-parity.md (section 8 'Execution order and completion rule' and 'Stage 22 planning artifacts' only)
- docs/design/native-ui-parity.md ('Review checkpoint' section only)

**Must not touch**

- docs/design/plan-reference.md (frozen)
- PLAN.md Decisions table (the orchestrator records D27 once)
- docs/design/platform-adaptations.md and docs/design/platform-inventory.toml (CX-P1-02)
- platform-parity.md '#### P0 inventory' totals table (CX-P1-02 fragment)
- native-ui-parity.md outside 'Review checkpoint'

**Steps**

1. Read PLAN.md D1, D6(c) and the D27 row as the orchestrator recorded it; read platform-parity.md section 8 (lines 613-638) and native-ui-parity.md 'Review checkpoint' (lines 14-31).
2. platform-parity.md section 8: replace 'Do not start a platform implementation as a parallel track beside the active compiler-performance milestone' and 'These are dependency lanes, not instructions to spawn agents. Work one bounded contract at a time' with D6(c) (parallel platform lanes in buckets 3-4, exactly one contract owner per contract) and D27 (a packet starts early only when its dependencies are met on main or it is planning/spike work; Codex lanes land only through Claude's gated integration). Keep the P0 -> P1 -> P2/P3/P4 -> W1/I1/A1 -> W2/I2/A2 -> P5-P7 order and the completion rule word for word.
3. native-ui-parity.md 'Review checkpoint': replace 'This inventory does not authorize early UI work ... it is not a parallel workstream beside optimization' with a pointer to D27's exact list of UI work allowed now and what stays gated; leave the decision table unchanged.
4. 'Stage 22 planning artifacts': add one status line each for btrsmith-p0-inventory (CX-P1-01, private repository) and the adaptation sign-off (CX-P1-02).
5. Grep src/tests and tools for readers of either document and run them.

**Acceptance**

- [ ] git diff --check clean; git diff --stat names only the two documents
- [ ] python3 -m pytest src/tests/python/test_platform_inventory.py src/tests/python/test_device_registry.py src/tests/python/test_toolchain_matrix.py -q passes, plus every reader found in step 5
- [ ] make lint passes
- [ ] Commit body quotes each replaced sentence before and after

**Risks**

- The bucket-4 planning groups may also amend native-ui-parity's Review checkpoint for D27; the orchestrator must give that section to exactly one packet.
- D27 must be recorded in PLAN.md first, or the docs cite an unrecorded decision.

#### Stage 23: P1 provisioning (toolchains, simulators, SDK, VM, signing, devices)

<a id="cl-p1-02"></a>

##### CL-P1-02 · Nix platforms shell: Android SDK and NDK r29, JDK 17, zig 0.16.0, and the wgpu-native archive digests

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 23 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-toolchains`; `tooling-android-sdk-ndk` (nix half: pinned SDK, NDK and JDK in nix develop)
- **Depends on:** none
- **Parallel-safe with:** CL-P1-01, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-01, MAC-P1-02

**Owned paths**

- flake.nix (a new devShells.\<system>.platforms output; default shell unchanged)
- nix/platforms.nix (new: androidenv composition, JDK 17, exported ANDROID_HOME/ANDROID_SDK_ROOT/ANDROID_NDK_HOME/JAVA_HOME)
- nix/wgpu-native-prebuilt.nix (new: fixed-output fetchers for the eight v27.0.4.0 release archives)
- docs/design/platform-toolchain-matrix.md (wgpu digest table, host-facts rows jdk/android-sdk/adb run through .#platforms, the 'Unavailable evidence' rows this closes)
- src/tests/python/test_toolchain_matrix.py (only if the host-facts expectations need it)

**Must not touch**

- flake.lock unless a new input is unavoidable (prefer none)
- nix/devcontainer.nix, nix/containerfile.nix (the CI image must not grow)
- Makefile, `.github/workflows/*`
- `src/compiler/**`, `src/language/**`, `src/runtime/**`
- docs/qualification/devices.toml

**Steps**

1. Check free disk; read flake.nix devShells (lines 102-200) and the matrix pins: NDK 29.0.14206865, build-tools 37.0.0, platform-tools 37.0.1, cmdline-tools 23.0, emulator 37.2.12, platforms android-36, JDK 17, zig 0.16.0.
2. nix/platforms.nix: androidenv.composeAndroidPackages with exactly those versions (ndkVersions = ["29.0.14206865"], platformVersions = ["36"], buildToolsVersions = ["37.0.0"], includeEmulator). System images: x86_64 API 29 and 36 on x86_64-linux; arm64-v8a API 29, 36 and google_apis_ps16k 36 on aarch64-darwin. Accept the licence in a nixpkgs import scoped to this shell only (config.android_sdk.accept_license = true, approved by D8). If the pinned nixpkgs lacks a revision, override androidenv's repo JSON; never substitute a different revision.
3. flake.nix: add devShells.\<system>.platforms = the default shell's inputs plus nix/platforms.nix; keep zig 0.16.0 (cfg.packages, flake.nix:27). Root the shell with --profile ~/.cache/btrc/gcroots/platforms (Determinate GC hazard). Record the PLAN amendment 'Stage 23 exit: in nix develop .#platforms' for the integrator.
4. wgpu-native: prefetch the v27.0.4.0 release archives named in the matrix (six new slices plus macOS/Linux) with nix store prefetch-file. Write nix/wgpu-native-prebuilt.nix with fixed-output hashes (no consumer until Stage 28 tooling-cross-gpu-deps) and record each SHA-256 in the matrix table.
5. Optional wine, inside .#platforms on x86_64-linux only, and only if it adds under 2 GB (supplementary, never evidence).
6. Update the matrix host-facts rows for jdk, android-sdk and adb to run through nix develop .#platforms.

**Acceptance**

- [ ] nix flake check --no-build passes; nix eval .#devShells.aarch64-darwin.platforms.drvPath evaluates (realized on the Mac in MAC-P1-03)
- [ ] nix develop .#platforms --command sh -c 'java -version; sdkmanager --version; adb version; zig version; grep Pkg.Revision $ANDROID_NDK_HOME/source.properties' prints JDK 17, platform-tools 37.0.1, zig 0.16.0 and 29.0.14206865 on x86_64-linux
- [ ] NDK clang --target=aarch64-linux-android29 and x86_64-linux-android29 -std=c11 hello.c each produce an ELF of the right machine (llvm-readelf -h)
- [ ] Default shell untouched: nix develop --command make NIX= generated-check lint passes, and ci.yml's devcontainer build is green on gh workflow run ci.yml --ref \<branch> (run id reported)
- [ ] Matrix records all eight wgpu archive digests; python3 -m pytest src/tests/python/test_toolchain_matrix.py -q passes; the .#platforms closure size is reported

**Risks**

- The pinned nixpkgs' androidenv may not carry NDK 29.0.14206865 or build-tools 37.0.0 (needs a repo JSON override).
- GitHub release downloads may fail through the cloud proxy (the matrix notes the API was unreachable); fall back to a CI job that computes the digests.
- aarch64-darwin emulator support in androidenv is evaluated here but only realized on the Mac (MAC-P1-03).

#### Stage 24: P1 shared target contract

<a id="cl-p1-03"></a>

##### CL-P1-03 · Stage 24 commit 1a: targets.toml schema 2, generator rules and generated rows (no behaviour change)

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-target-spec` (commit 1a)
- **Depends on:** [CL-C-06](#cl-c-06)
- **Why not now:** Starts once C4 lands (CL-C-06) under D27's Stage 24 clause (§2, §7 Q2; the owner approved it on 2026-10-03). If the owner strikes that clause, it waits for CL-C-40 (D1).
- **Parallel-safe with:** CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-03, MAC-P1-04

> **Review change:** Depends on `CL-C-06` (C4 landed), not only on the spec commit `CL-C-03`, matching its own step 1. Stage 24 starts after C4 only under D27's explicit Stage 24 clause, which the owner approved on 2026-10-03; struck, it waits for `CL-C-40` (§10 P3). Never beside `CL-C-07` or `CL-C-23`.

**Owned paths**

- src/language/targets.toml
- tools/compiler_codegen/hosted_abi.py (TargetManifest and its rules)
- src/compiler/python/abi/generated.py (regenerated only)
- src/compiler/btrc/generated/hosted_abi/Tables.btrc (regenerated only)
- src/tests/python/test_hosted_abi_contract.py
- src/tests/python/test_target_macro_table.py
- docs/design/c-preprocessor-conditionals.md (the pointer amendments listed under 'Hand-offs')
- `src/tests/fixtures/expected-skips/*.json` (classified Mac-bound skips; integrator file, edited in this commit only)

**Must not touch**

- frontends, analyzers and CLIs (commits 1b-1c)
- src/language/hosted_abi.toml (commit 2a)
- hand edits to any generated file
- docs/design/plan-reference.md
- `tools/target_hosts/**` and host workflows (Codex)

**Steps**

1. Rebase on main with C4 merged; read platform-target-contract.md sections 1.1-1.3 and C4's 'Spec commit' and 'What later stages rely on'.
2. targets.toml schema 2: add [aliases] (architectures, default_environments) and the 11 [[targets]] rows of section 1.2 with every column: label, operating_system, architecture, environment, minimum_version, triple, triple_aliases, zig_target, target_arguments, sizeof_pointer, sizeof_long, sizeof_wchar_t, sizeof_long_double, char_signed, wchar_signed, sysroot_kind, sysroot_name, compiler_host, objective_c, frameworks.
3. Predefined macros (section 1.3): widen the linux-family, __APPLE__/__MACH__ and __arm64__ rows; __ANDROID__ becomes a row; __STDC__ excludes msvc; add __APPLE_EMBEDDED_SIMULATOR__, __MINGW32__/__MINGW64__/__SEH__ and _M_ARM64; add the `TARGET_OS_*` rows including value-0 rows (TARGET_OS_EMBEDDED needs two); environments lists name "" explicitly; derived macros come only from columns; update both [conditionals] lists.
4. TargetManifest: every rule of section 1.1 in HostedAbiManifestError style (label derivation, OS/environment fit, the triple and alias rules including the pinned msvc19.40.0, sizes, sysroot_name iff xcrun, compiler_host = the six desktop default rows, objective_c/frameworks = macos/ios, the TARGET_ reservation exemption, char/short/int/long-long pinned across rows).
5. Generated forms: Python TARGET_ROWS, TARGET_ARCHITECTURE_ALIASES, TARGET_DEFAULT_ENVIRONMENTS, TARGET_ENVIRONMENTS and TARGET_PREDEFINED_MACRO_ROWS. btrc GeneratedTargetRow in camelCase, plus memoized architectureAliases()/defaultEnvironments() emitted as small methods. Run make compiler-codegen-generate.
6. Tests: one failing fixture per generator rule; test_target_macro_table.py takes its triples from TARGET_ROWS, runs the unwrapped clang (nix-support/orig-cc), resolves object-like aliases (__ANDROID_API__), and classifies the Apple clang and TargetConditionals.h cases as Mac-bound skips (verified in MAC-P1-05).
7. Add the C4 doc pointers listed in platform-target-contract.md 'Hand-offs'.

**Acceptance**

- [ ] make generated-check, make lint, make format-check clean
- [ ] python3 -m pytest src/tests/python/test_hosted_abi_contract.py src/tests/python/test_target_macro_table.py -q green on Linux for all 11 rows (Mac cases are classified skips)
- [ ] btrcc fixture rebuild and make bootstrap reach the fixed point; zero 'warning:' lines when transpiling BtrccMain.btrc, cli/WindowsMain.btrc and cli/MacOSMain.btrc
- [ ] make test-boundaries unchanged (287 of 311 checked); full corpus through both compilers unchanged (no behaviour change)

**Risks**

- C4's final targets.toml shape may differ from what the design assumed; re-read it before writing deltas.
- clang 21 macro dumps for the msvc row need the unwrapped binary (the wrapper's -fPIC breaks it).

<a id="cl-p1-04"></a>

##### CL-P1-04 · Stage 24 commit 1b: one target owner per compiler, the unified accept/reject set and host inference

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p1-target-spec` (commit 1b)
- **Depends on:** [CL-P1-03](#cl-p1-03)
- **Why not now:** Needs the generated TARGET_ROWS from CL-P1-03.
- **Parallel-safe with:** CL-P1-07, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-03, MAC-P1-04

**Owned paths**

- src/compiler/python/abi/hosted.py (new class TargetRepository: parse, host, labels; TargetSelectionError)
- src/compiler/python/frontend/packages.py (PackageTarget fields/row/label; delete _TARGET_OPERATING_SYSTEMS, _TARGET_ARCHITECTURES and as_dict)
- src/compiler/python/application/compiler.py (Compiler.target_labels, Compiler.select_target)
- src/compiler/python/cli/compiler.py (argument -> target -> input order; help)
- src/compiler/python/artifacts/archive.py (TargetCatalog from compiler_host rows)
- src/compiler/btrc/frontend/Packages.btrc (FePackageTarget parse/host/hostFrom/row/label; delete validOperatingSystem/validArchitecture)
- src/compiler/btrc/cli/Driver.btrc (hotspot: targetGiven, help)
- src/compiler/btrc/pipeline/Models.btrc (BtrccOptions.targetGiven)
- src/compiler/btrc/tools/FrontendMain.btrc (help)
- tools/native_plan.py (the two target messages at :320 and :966 only)
- src/tests/btrc/test_target_contract.py (new)

**Must not touch**

- analyzers (commit 1c)
- native_imports.py/NativeImports.btrc (commit 3a)
- hand edits to generated files
- Codex-owned `tools/target_hosts/**` and host workflows

**Steps**

1. Python: TargetRepository.parse splits on '-' into 2 or 3 non-empty parts, applies the aliases and the default environment, looks up TARGET_ROWS, and raises TargetSelectionError with the section 1.5 message character for character. host(system, machine) maps darwin/linux/windows and x86_64/amd64/aarch64/arm64 to tokens, or to nothing.
2. PackageTarget delegates parse and coerce. Compiler.select_target returns CompilerFailure(INPUT). CompilerCommand checks arguments, then the target, then reads input, and prints 'error: \<message>' with exit 1 and no traceback.
3. btrc: FePackageTarget with the same behaviour over GeneratedHostedAbiData rows; hostFrom(platform, architecture) maps codes 1/2/3 and 1/2 (code 0 maps to nothing). targetGiven makes --target "" and a repeated --target errors. Both compilers print the same unknown-host message at the same point.
4. TargetCatalog renders release names from compiler_host rows through the inverse aliases (adding the Windows ARM64 host) and keeps the constructor test_compiler_api.py:338-343 pins.
5. Every message that spells a target uses the label (packages.py:1012, Packages.btrc:1865, native_plan.py:320/:966).
6. test_target_contract.py: the 11 labels plus 19 alias spellings (30 in all), the section 1.11 rejection battery, a missing input path to prove no source is read, the host seam table (Python strings and btrc integer codes), round-trips of today's spellings, the slice-to-row mapping, and that only compiler_host rows reach TargetCatalog. The end-to-end unknown host uses a btrcc built with -DBTRC_TARGET_PLATFORM_OVERRIDE=0.

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_target_contract.py src/tests/python/test_compiler_api.py src/tests/btrc/test_cli_arguments.py src/tests/btrc/test_driver_frontend_parity.py -q green (both compilers)
- [ ] make bootstrap fixed point; zero-warning transpiles of the three self-host entries
- [ ] gh workflow run windows.yml / macos.yml / ci.yml on the integration branch are green (host inference is exercised natively there); run ids reported

**Risks**

- The cache keys change once (btrcc used the raw spelling); expect a one-time cold rebuild.
- Driver.btrc is a hotspot; no other lane may hold it during this commit.

<a id="cl-p1-05"></a>

##### CL-P1-05 · Stage 24 commit 1c: the target data model in both analyzers, literal typing, and the release C files

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-target-spec` (commit 1c)
- **Depends on:** [CL-P1-04](#cl-p1-04); ccompat-r18-preprocessor-conditionals (Stage 16 C4 evaluator lane: test_preprocessor_conditionals.py and the M3 predicate exist) → [CL-C-06](#cl-c-06)
- **Why not now:** Needs commit 1b and C4's evaluator lane. It must not run beside Stage 19's r16 wide-literal lane, because both edit syntax/Literals.btrc.
- **Parallel-safe with:** CL-P1-07, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

> **Review change:** Never beside `CL-C-25` (C3 commit B1) or `CL-C-30` (r16): all three edit `syntax/Literals.btrc`, and `CL-C-25` also touches `CIntegerWidths` (§2 D27, §10 P3).

**Owned paths**

- src/compiler/python/analyzer/types.py (CIntegerWidths.for_target; delete native())
- src/compiler/python/analyzer/analyzer.py and src/compiler/python/application/pipeline.py (target row into SemanticAnalyzer/NumericLiteralSemantics; host-row default for target-less callers)
- src/compiler/btrc/analyzer/validation/Constants.btrc (ConstantValidator, builtinCastRange)
- src/compiler/btrc/syntax/Literals.btrc (IntegerLiteral.typeName long-width parameter)
- src/compiler/btrc/analyzer/Operators.btrc (integerLiteralType caller)
- src/compiler/btrc/frontend/NativeImports.btrc (the :1530 caller only)
- src/compiler/btrc/analyzer/Models.btrc and src/compiler/btrc/pipeline/Pipeline.btrc (row into the analyzer context)
- C4's source-macro M3 predicate in both compilers (refuse #define/#undef of every predefined and derived name)
- Makefile (hotspot: :128-129 --target windows-x86_64 for dist/btrcc-windows.c; per-row identity check for the portable dist/btrcc.c)
- src/tests/btrc/test_target_data_model.py (new)
- src/tests/btrc/test_preprocessor_conditionals.py (extended)

**Must not touch**

- native-import reader arguments (commit 3a)
- the LSP (commit 1d)
- hand edits to generated files

**Steps**

1. Python: CIntegerWidths.for_target(row) from sizeof_long (char 8, short 16, int 32, long long 64). NumericLiteralSemantics and SemanticAnalyzer take the row; the about 118 target-less callers default to TargetRepository.host()'s row.
2. btrc: Constants.btrc, Literals.btrc (via Operators.btrc:138-142 and NativeImports.btrc:1530) take the row's sizeofLong, threaded through the analyzer context that CompilerPipeline fills. All three sites change in this commit, so the two compilers never split on literal typing.
3. Widths contract in test_hosted_abi_contract.py gains __SIZEOF_LONG__ vs for_target for every row.
4. test_target_data_model.py: for linux-x86_64, windows-x86_64 and windows-aarch64-msvc, the 'long' out-of-range refusal, the cast-range checks and the typing of 3000000000 are identical in both compilers and follow the row, not the host.
5. test_preprocessor_conditionals.py: per-target selection over all 11 rows; TARGET_OS_IPHONE and __ANDROID_API__ >= 29 select; #define TARGET_OS_IPHONE 1 is refused with M3's message.
6. Makefile: generate dist/btrcc-windows.c with --target windows-x86_64. The release gate regenerates dist/btrcc.c for each of the four LP64 desktop rows and requires byte identity; any row that differs gets its own C file.

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_target_data_model.py src/tests/btrc/test_preprocessor_conditionals.py src/tests/python/test_hosted_abi_contract.py -q green
- [ ] Full corpus through both compilers unchanged on linux-x86_64 (make test-btrc and make test-btrc-selfhost)
- [ ] make bootstrap fixed point; zero-warning self-host transpiles
- [ ] gh workflow run windows.yml (native bootstrap from the new btrcc-windows.c) and macos.yml (release archives) green; run ids reported

**Risks**

- Observable change: a Linux-to-windows-x86_64 compile now refuses long x = 3000000000; this is intended and pinned.
- Hotspot overlap with Stage 19 lanes (Literals.btrc, Constants.btrc): the integrator sequences them.

<a id="cl-p1-06"></a>

##### CL-P1-06 · Stage 24 commit 1d: the LSP btrc.target setting, then the sub-batch 1 gate

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p1-target-spec` (commit 1d and the sub-batch 1 gate)
- **Depends on:** [CL-P1-05](#cl-p1-05); ccompat-r18-preprocessor-conditionals (C4's lazy ConditionalEnvironment and UnitCache in the LSP) → [CL-C-06](#cl-c-06)
- **Why not now:** Needs commits 1a-1c and C4's LSP conditioning.
- **Parallel-safe with:** CL-P1-07, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- src/devex/vscode/package.json (contributes.configuration btrc.target, enum suggestions generated from the rows)
- src/devex/vscode/src/ (send initializationOptions.target and didChangeConfiguration)
- src/devex/lsp/workspace/workspace.py (parse via PackageTarget.parse, one workspace diagnostic, LSP_FALLBACK_TARGET = 'linux-x86_64', ConditionalEnvironment rebuild, UnitCache invalidation; FileUnit.parse stops using the host)
- src/tests/lsp/test_target_setting.py (new)
- src/tests/vscode/target_setting.test.js (new)

**Must not touch**

- compiler sources (commits 1a-1c are merged)
- src/devex/lsp/catalog/generated.py (derived)

**Steps**

1. Implement platform-target-contract.md section 1.10 in workspace.py and the extension client.
2. Tests: switching linux-x86_64 to windows-x86_64 flips a '#if _WIN32' region; an invalid label gives exactly one diagnostic with the section 1.5 message and falls back to the host; a reopened workspace keeps the setting; an unknown host with no setting shows the unknown-host message once and analyses with the fallback row.
3. Sub-batch 1 gate on the merged 1a-1d tree: generated-check, lint, format-check, btrcc fixture rebuild, make test, make bootstrap, zero-warning transpiles, make test-boundaries, make extension and the VS Code tests; push main after green (D4), then read CI.

**Acceptance**

- [ ] python3 -m pytest src/tests/lsp/test_target_setting.py -q and the VS Code test (target_setting.test.js) green; make extension builds the .vsix
- [ ] Sub-batch 1 gate log green: make test passed/skipped counts, bootstrap fixed point, boundary 287 of 311 unchanged
- [ ] CI on the pushed main: ci.yml, macos.yml and windows.yml green (windows.yml packages the real VSIX); run ids in the PLAN progress entry

**Risks**

- The VS Code test harness may need Node 22 locally; windows.yml covers packaging.

<a id="cl-p1-07"></a>

##### CL-P1-07 · Stage 24 sub-batch 2 input: tools/hosted_platform.py and the Linux, MinGW and NDK unavailability lists

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p1-hosted-abi-targets` (extractor and the Linux-side extractions)
- **Depends on:** [CL-P1-03](#cl-p1-03); [CL-P1-02](#cl-p1-02)
- **Why not now:** Needs TARGET_ROWS (CL-P1-03) and the NDK r29 sysroot in nix develop .#platforms (CL-P1-02).
- **Parallel-safe with:** CL-P1-04, CL-P1-05, CL-P1-06, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- tools/hosted_platform.py (new; class HostedPlatformExtractor)
- src/tests/python/test_hosted_platform_extractor.py (new)
- build/hosted-platform/\<label>.toml (uncommitted fragments handed to CL-P1-08)

**Must not touch**

- src/language/hosted_abi.toml (only CL-P1-08 writes it)
- `tools/compiler_codegen/**` (the extractor stays outside the normative codegen inventory)
- tools/native_plan.py

**Steps**

1. HostedPlatformExtractor (section 2.3): for one row, build a probe TU that includes the C emitter prologue's automatic headers with exactly the row's real build flags (windows-gnu: -I src/runtime/windows -include btrc_win_compat.h and zig's bundled includes). Pass the row's target_arguments and resolved sysroot, and never -D__ANDROID_API__. Read declared names with NativeHeaderReader in names-only mode, or with clang -Xclang -ast-dump=json. Output [platform] minus declared for each of the five kinds.
2. Sysroot discovery lives in this tool (allowed: tools discover toolchains): glibc from the flake; zig's aarch64-linux-gnu glibc headers on an x86_64 host; zig lib/libc/include/any-windows-any (MinGW-w64 38c8142f); the NDK r29 sysroot at API 29; and an --xcrun mode for the Mac (used by MAC-P1-05).
3. Extract linux-x86_64, linux-aarch64, windows-x86_64, windows-aarch64, android-aarch64 and android-x86_64. Write the conservative windows-aarch64-msvc table (the windows-aarch64 list plus every MinGW/winpthreads/compat-overlay-only POSIX and pthread name) with source 'conservative copy pending runner extraction'.
4. Spot-check the bionic borderline names: getrandom, posix_spawn, aligned_alloc, timespec_get and reallocarray are available at 29; the threads.h names are hidden (API 30).

**Acceptance**

- [ ] python3 -m pytest src/tests/python/test_hosted_platform_extractor.py -q green (fixture headers)
- [ ] Seven fragments produced, each with list sizes reported; spot names: GetFileAttributesA unavailable on every non-windows row, arc4random_uniform unavailable on linux-gnu, explicit_bzero available on linux and android
- [ ] make lint clean

**Risks**

- Names-only reader mode may not exist yet; the ast-dump fallback must give identical sets (cross-check on one row).

<a id="cl-p1-08"></a>

##### CL-P1-08 · Stage 24 commit 2a: hosted_abi.toml schema 3 [[platform_targets]] and the generated availability tables

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `platforms-p1-hosted-abi-targets` (commit 2a)
- **Depends on:** [CL-P1-07](#cl-p1-07); [MAC-P1-05](owner.md#mac-p1-05); [CL-P1-06](#cl-p1-06)
- **Why not now:** Needs every row's fragment: the Linux, MinGW and NDK rows from CL-P1-07 and the Apple rows from MAC-P1-05 (a missing extraction fails the generator). Also needs the sub-batch 1 gate.
- **Parallel-safe with:** CX-P1-04, CX-P1-05, CX-P1-06, CX-P1-01, CX-P1-02

**Owned paths**

- src/language/hosted_abi.toml (the only writer)
- tools/compiler_codegen/hosted_abi.py (platform_targets rules)
- src/compiler/python/abi/generated.py (regenerated: HOSTED_PLATFORM_UNAVAILABLE)
- src/compiler/btrc/generated/hosted_abi/Tables.btrc (regenerated: platformUnavailable(label) as small memoized methods)
- src/tests/python/test_hosted_abi_platform_names.py

**Must not touch**

- optimizers (commit 2b)
- hand edits to generated files

**Steps**

1. Schema 3: one [[platform_targets]] per row, with sorted unique subsets of [platform] for each of the five kinds, a non-empty source, no ISO C or runtime-origin names, and target validated against targets.toml.
2. HOSTED_ABI_FINGERPRINT covers the new tables, so ToolchainFingerprint('full') and btrcc's identity follow them.
3. Extend test_hosted_abi_platform_names.py with the section 2.5 spot names: fork unavailable on both ios rows, GetFileAttributesA, arc4random_uniform and explicit_bzero.
4. make compiler-codegen-generate.

**Acceptance**

- [ ] make generated-check clean; python3 -m pytest src/tests/python/test_hosted_abi_platform_names.py src/tests/python/test_hosted_abi_contract.py -q green
- [ ] make bootstrap fixed point; zero-warning transpiles; make test-boundaries unchanged

**Risks**

- The Tables.btrc size grows; keep it to small methods (CLAUDE.md: one large constructor cost about 90% of compiling the compiler).

<a id="cl-p1-09"></a>

##### CL-P1-09 · Stage 24 commit 2b: the reachable-reference availability check in both optimizers, then the sub-batch 2 gate

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-hosted-abi-targets` (commit 2b and the sub-batch 2 gate)
- **Depends on:** [CL-P1-08](#cl-p1-08)
- **Why not now:** Needs the generated availability tables (CL-P1-08).
- **Parallel-safe with:** CX-P1-04, CX-P1-05, CX-P1-06, CX-P1-01, CX-P1-02

**Owned paths**

- src/compiler/python/ir/optimizer.py (IROptimizer.refuse_unavailable_hosted)
- src/compiler/btrc/ir/optimization/Optimizer.btrc (IROptimizer, same message and order)
- src/compiler/python/application/modules.py and src/compiler/btrc/pipeline/ModuleUnits.btrc (hotspot pair: owner-process call over the merged reachability only)
- src/tests/btrc/test_hosted_availability.py (new)

**Must not touch**

- src/language/hosted_abi.toml
- `src/stdlib/**` (a stdlib refusal found here is fixed by its owner: Stage 25 CL-P1-20 or CX-P1-10)

**Steps**

1. After the final reachability graph, walk the reachable functions' calls and identifier references, the reachable globals' initializers and the kept externs. Report the first hit by (function, name) as a CompilerFailureKind.ANALYSIS failure: '\<name>' is not available on target \<label> (hosted ABI); referenced from \<function>. Under --module-units, the owner process checks; a worker never does.
2. --no-dce keeps every function, so every reference is checked.
3. test_hosted_availability.py for linux-x86_64, windows-x86_64, ios-aarch64 and android-aarch64: a reachable reference gives the identical message and exit 1 in both compilers, an unreachable one compiles, a C4-guarded one compiles, plus the --no-dce behaviour.
4. Sub-batch 2 gate: the sub-batch 1 checks, plus the corpus through both compilers on linux-x86_64, plus the corpus emitted for windows-x86_64 on Linux and compiled with zig (no run), plus zero-diagnostic transpiles of cli/WindowsMain.btrc (windows-x86_64 and windows-aarch64), BtrccMain.btrc (both linux rows) and cli/MacOSMain.btrc (both macOS rows).

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_hosted_availability.py -q green
- [ ] Sub-batch 2 gate log green (counts recorded); push, and CI green on ci.yml, macos.yml and windows.yml with run ids
- [ ] The BTRSmith application-frontend-check on the Mac is collected in MAC-P1-06 (a red result triggers D5's revert-bisect)

**Risks**

- Runtime branches such as FileSystemHandles' O_DIRECTORY|O_NOFOLLOW are reachable on every row; only the compat-overlay extraction rule keeps them available on windows-gnu.
- Merges with Stage 17-19 lanes that touch Optimizer.btrc or ModuleUnits.btrc must be sequenced (hotspots).

<a id="cl-p1-10"></a>

##### CL-P1-10 · Stage 24 commit 3a: the native importers read the row's triple and a validated sysroot, in both compilers

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p1-native-import-targets`
- **Depends on:** [CL-P1-09](#cl-p1-09)
- **Why not now:** Sub-batch 3 starts after the sub-batch 2 gate (CL-P1-09).
- **Parallel-safe with:** CL-P1-11, CL-P1-12, CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06

> **Writer note:** `src/tests/native_targets.py` changed in batch 10a (`430a892`); rebase before replacing its TRIPLES table (§9 item 15).

**Owned paths**

- src/compiler/python/frontend/native_imports.py (new class NativeSysroot; the row triple replaces the hand patterns; _reader_arguments per row kind; Objective-C on objective_c rows; resolution fingerprint btrc-native-resolution-v4 with the label and sysroot identity)
- src/compiler/btrc/frontend/NativeImports.btrc (new class FeNativeSysroot; matchesTarget replacement; reader arguments; fingerprint v4)
- src/compiler/btrc/frontend/NativeHeaderProcess.btrc (argv only, if needed)
- tools/NativeHeaderReader.cpp (only if the echoed triple must be compared through aliases)
- src/tests/native_targets.py (the TRIPLES table is replaced by TARGET_ROWS)
- src/tests/python/native_import_fixtures.py (BTRC_NATIVE_TARGET spellings)
- src/tests/native/target_import/ (new: target_import.h, btrc.toml)
- src/tests/btrc/test_native_import_targets.py (new)

**Must not touch**

- link-plan writers and tools/native_plan.py (CL-P1-11)
- the reader cache request format btrc.native-read.v1 (unchanged by design)

**Steps**

1. Both readers take the triple from the row. BTRC_NATIVE_TARGET must equal the triple or an alias, otherwise: BTRC_NATIVE_TARGET '\<value>' does not match target \<label> (\<triple>). NativeHeaderCodec compares the echoed triple with the triple or its aliases.
2. Reader arguments per section 3.1's table: macos/ios -isysroot with Objective-C -fblocks -fobjc-arc; linux unchanged; android --sysroot; windows-gnu -nostdinc plus zig's resource headers, any-windows-any and each compiler's runtime windows overlay root; windows-msvc is runner-bound (W1). The Objective-C error becomes 'Objective-C adapters require an Apple target'.
3. NativeSysroot/FeNativeSysroot validate from files only (no process) per sysroot kind and compute identity = SHA-256 over kind, name and the identity file's bytes. The error is: native imports require a valid \<kind> sysroot for \<label>: \<reason>.
4. target_import.h declares a record with long, wchar_t, size_t, bool and a nested array; an enum; a callback typedef; a variadic function; and a by-value record return. test_native_import_targets.py checks that the semantic JSON is byte-identical between the two compilers per triple, and that layouts equal the row's data model against a _Static_assert TU compiled with the same arguments.
5. Missing sysroots are classified skips in expected-skips (Mac-bound for ios, NDK-bound for android outside .#platforms, runner-bound for msvc).

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_native_import_targets.py -q: windows-x86_64 and windows-aarch64 pass on Linux (zig MinGW); android-aarch64 and android-x86_64 pass inside nix develop .#platforms; ios rows are classified skips (run in MAC-P1-06)
- [ ] Existing native suites green on Linux; gh workflow run macos.yml green for the Objective-C and native suites (run id)
- [ ] make bootstrap fixed point; zero-warning transpiles

**Risks**

- The windows-gnu argv differs per compiler in the runtime root path; that changes only each compiler's own reader-cache key, never the semantics.
- bsm_env.sh spells 14.0.0; any other macOS version now refuses.

<a id="cl-p1-11"></a>

##### CL-P1-11 · Stage 24 commit 3b: link-plan schema 5 writers and the target-aware builder (TargetToolchain)

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p1-native-plan-toolchain` (writers, builder and documentation)
- **Depends on:** [CL-P1-09](#cl-p1-09)
- **Why not now:** Sub-batch 3 starts after the sub-batch 2 gate. It merges after CL-P1-10, because the builder imports NativeSysroot's identity function.
- **Parallel-safe with:** CL-P1-10, CL-P1-12, CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- src/compiler/python/frontend/packages.py (NativeLinkPlan.as_dict v5; NATIVE_LINK_PLAN_SCHEMA = 5; the 1/2/4 writer selection deleted)
- src/compiler/btrc/frontend/Packages.btrc (the link-plan writer's canonicalJson v5)
- tools/native_plan.py (hotspot: ROOT_FIELDS gains toolchain; schemas (1,2,4,5); TARGET_ROWS; new class TargetToolchain; drivers per row; frameworks/pkg-config row rules; legacy-plan host-only rule; NativeBuildReport.target = label; object cache/_DarwinLinkReceipt/_RetainedGenerations keyed on label plus sysroot identity)
- src/language/package-manifest.md ('Native link-plan schemas' gains schema 5; the predicate section lists the new OS set)
- src/tests/python/test_native_plan_builder.py and the existing link-plan goldens that flip from 'schema': 1

**Must not touch**

- the provider predicate code in packages.py/Packages.btrc (CL-P1-14)
- native_imports.py (CL-P1-10)
- BTRSmith Makefiles

**Steps**

1. Writers: both compilers always write the frozen section 4.1 JSON (sorted keys, compact separators, ensure_ascii False, trailing newline), with target {arch, environment, label, minimum, os, triple} and toolchain {sysroot {identity, kind, name}, target-arguments}. The plan never holds a path.
2. Builder: the field sets are exact per schema. A legacy 1/2/4 plan builds only on the matching compiler_host row, else: legacy native link plan for \<os>-\<arch> cannot be built on host \<label>; regenerate it as schema 5.
3. Drivers: the host row uses cc/c++ as today, with no target arguments (test-c11 unchanged). Otherwise: zig cc -target \<zig_target>; xcrun --sdk \<name> clang with target-arguments and -isysroot; NDK clang with --sysroot; windows-sdk clang (runner-bound). If none is found: no toolchain for \<label>: \<what is missing>; never a host fallback.
4. TargetToolchain discovers sysroots (xcrun --show-sdk-path; $ANDROID_NDK_HOME or $ANDROID_HOME/ndk/29.0.14206865; zig env .lib_dir joined with libc), recomputes the identity with NativeSysroot, and refuses a mismatch: sysroot identity changed since the plan was emitted.
5. The builder records the effective deployment target in NativeBuildReport and warns (does not fail) when it differs from the row minimum (Q1).

**Acceptance**

- [ ] python3 -m pytest src/tests/python/test_native_plan_builder.py -q green, plus every existing link-plan consumer test updated to schema 5
- [ ] make test-c11 green (the builder compiles C)
- [ ] make examples-native-package TARGET=linux-x64 still builds; macOS host-row builds keep today's flags (Mac object comparison in MAC-P1-06)
- [ ] gh workflow run macos.yml and windows.yml green (run ids)

**Risks**

- tools/native_plan.py is a hotspot shared with Stage 28; hold it alone for this commit.
- BTRSmith reads plans only through tools/native_plan.py; any accidental flag change on the host row breaks Stage 28's 'host builds byte-identical'.

<a id="cl-p1-12"></a>

##### CL-P1-12 · Stage 24 commit 3c (tests): link-plan v5 parity goldens and cross builds through the builder

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p1-native-plan-toolchain` (the parity and cross-build tests)
- **Depends on:** [CL-P1-09](#cl-p1-09)
- **Why not now:** Starts with sub-batch 3, written against the frozen section 4.1 schema; it merges after CL-P1-11.
- **Parallel-safe with:** CL-P1-10, CL-P1-11, CL-P1-13, CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- src/tests/btrc/test_link_plan_parity.py (new)
- src/tests/fixtures/link_plan_v5/ (new: one golden per row for each of three fixture packages)
- src/tests/python/test_native_plan_cross.py (new)

**Must not touch**

- writers and the builder (CL-P1-11)
- the expected-skip manifests beyond this test's classified skips

**Steps**

1. Write the 11 x 3 goldens by hand from the frozen schema: plain C units; a C++ unit with generated units; an --emit-units split. Both compilers' --emit-link-plan output must equal them byte-for-byte; no toolchain is needed.
2. test_native_plan_cross.py: build a windows-x86_64 v5 plan with zig on Linux and check the PE machine with ExecutableFormatInspector; build android-aarch64 with the NDK and check the ELF machine and 16 KiB LOAD alignment; ios-aarch64-simulator is Mac-bound (Mach-O platform IOSSIMULATOR), run in MAC-P1-06.

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_link_plan_parity.py -q green for all 11 rows on Linux
- [ ] python3 -m pytest src/tests/python/test_native_plan_cross.py -q: windows passes on Linux; android passes inside nix develop .#platforms; ios is a classified skip

**Risks**

- Writing the goldens independently of the writers is the point; do not regenerate them from the writer's output.

<a id="cl-p1-13"></a>

##### CL-P1-13 · Stage 24 commit 3c (fixture): the target ABI fixture, static half

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p1-abi-fixture`
- **Depends on:** [CL-P1-10](#cl-p1-10)
- **Why not now:** Needs the per-triple record offsets from the row-driven native reader (CL-P1-10).
- **Parallel-safe with:** CL-P1-11, CL-P1-12, CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- src/tests/native/target_abi/ (new: TargetAbi.btrc, target_abi.c, target_abi.h, btrc.toml, target_abi.expected)
- src/tests/btrc/test_target_abi_fixture.py (new: static mode, plus a run mode that skips with 'Stage 25 host lane' unless an executor capability is granted)

**Must not touch**

- src/tests/corpus_files.py (native/ is already non-corpus)
- `tools/target_hosts/**` (Codex executors arrive in Stage 25)

**Steps**

1. TargetAbi.btrc imports target_abi.h through its btrc.toml binding and exercises: long, unsigned long, size_t, ptrdiff_t, wchar_t, bool, char, signed char and long double (via double helpers); a mixed-width record; a #pragma pack(1) record passed and returned by value; a nullable pointer; variadic int sum(int count, ...); a callback int (`*)(void*`, long) invoked from C with a btrc context; atomics through the runtime helpers; an enum. It prints one line per checked fact; target_abi.expected is identical on every row.
2. The static half renders target_abi_static.h from the selected row: _Static_assert on the sizes of long, wchar_t, long double, pointers and size_t; the signedness of char and wchar_t; and offsetof for each record field as the reader reported it.
3. Compile only, no link and no run: `linux-*` and windows-gnu (zig) on Linux; windows-aarch64-msvc as a header-free -ffreestanding static half; `android-*` inside .#platforms; macos/ios on a GitHub macos-15 runner as a stand-in (the ABI facts do not depend on the SDK version), confirmed on the Mac in MAC-P1-06.
4. The run mode documents the Stage 25 hook: the executor named by the granted BTRC_TEST_CAPABILITIES capability (windows-native, ios-simulator, android-emulator) through src/tests/target_runner.py.

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_target_abi_fixture.py -q: every row with a toolchain compiles through both compilers' generated C; rows without one are classified skips naming their bound
- [ ] A temporary or dispatched macos-15 job compiles the macos and ios rows (run id reported; stand-in until MAC-P1-06)

**Risks**

- btrc has no long double value type; the double helpers must not hide an ABI mismatch (compare via C-side checks).

<a id="cl-p1-14"></a>

##### CL-P1-14 · Stage 24 commit 4a: provider filters (the env selector and the platform-directory rule) and the 11-row provider matrix

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-provider-filters`
- **Depends on:** [CL-P1-11](#cl-p1-11); [CL-P1-13](#cl-p1-13)
- **Why not now:** Sub-batch 4 follows the sub-batch 3 gate. CL-P1-11 must release packages.py and Packages.btrc first.
- **Parallel-safe with:** CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-06

**Owned paths**

- src/compiler/python/frontend/packages.py (NativeDeclaration, NativeBinding and the provider record: environments, selected_for, disjointness over the label set, the platform-directory rule, framework/Objective-C/pkg-config row rules)
- src/compiler/btrc/frontend/Packages.btrc (FeNativeDeclaration, FeNativeBinding and the provider record, as twins)
- src/language/package-manifest.md (the predicate section, by reference to TARGET_ENVIRONMENTS)
- src/tests/python/test_target_provider_matrix.py (new)
- src/tests/btrc/test_target_provider_matrix.py (new parity variant via tools/FrontendMain --target)
- stdlib btrc.toml os/env audit, submitted as manifest fragments that the integrator applies (derived-artifact rule)

**Must not touch**

- stdlib provider sources under `src/stdlib/{GUI,Tray,App,UI,Audio,Image}/**` (Codex and bucket-4 lanes)
- `src/stdlib/**/btrc.toml` by direct edit (fragments only)

**Steps**

1. os takes the five operating systems from TARGET_ROWS. The new env array covers "", gnu, msvc and simulator; an empty array matches everything. Unknown values are refused: unsupported env '\<value>' in \<table>; expected "", gnu, msvc or simulator (identical in both compilers).
2. Platform-directory rule: a module path segment MacOS/IOS/Linux/Android/Windows must select exactly that one OS: module '\<module>' lives under \<Segment>/ and must select os = ["\<os>"]. [[native.frameworks]] and Objective-C bindings select only rows with frameworks or objective_c; [[native.pkg-config]] never selects ios or android.
3. Audit every stdlib native declaration with an empty os array (it now also matches ios and android): give each an explicit os, or a written reason to stay portable, as fragments.
4. The provider matrix resolves every stdlib group manifest, every examples/ package with a btrc.toml and the native test packages for all 11 rows, through both frontends. It classifies foreign (must be zero), missing (must equal platform-inventory.toml's missing/os-restricted cells) and portable.

**Acceptance**

- [ ] python3 -m pytest src/tests/python/test_target_provider_matrix.py src/tests/btrc/test_target_provider_matrix.py -q: zero foreign records for every row through both frontends; the missing set equals the inventory
- [ ] make test green on Linux
- [ ] The fragments are listed in the commit body and applied by the integrator in the same merge

**Risks**

- Codex UI lanes (D27) may be editing GUI/Tray providers at the same time; manifest changes go only through integrator fragments to avoid collisions.
- A missing-set disagreement with the inventory needs a joint fix with the inventory owner (CX-P1-02's reconciled cells).

<a id="cl-p1-15"></a>

##### CL-P1-15 · Stage 24 commit 4b: canonical-label cache identity, stdlib archive schema 6, the cache-poisoning matrix and the full-matrix gate

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p1-cache-identity`
- **Depends on:** [CL-P1-14](#cl-p1-14)
- **Why not now:** PLAN orders cache identity last, by a single owner, after the provider filters.
- **Parallel-safe with:** CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- src/compiler/btrc/Compiler.btrc (artifact keys spell the label)
- src/compiler/btrc/pipeline/ModuleUnits.btrc (hotspot: :1817 label; :2705 ValidationRecords target=\<label>, context version validation-record-v5)
- src/compiler/python/application/modules.py (hotspot: :863 label)
- src/compiler/python/artifacts/stdlib.py (StdlibArchiveManifest SCHEMA 6 with target and target_spec; ArchiveVersionError: prebuilt stdlib archive was built for \<label>; regenerate it for \<label>)
- src/tests/btrc/test_target_cache_identity.py (new)

**Must not touch**

- native_imports.py (fingerprint v4 landed in CL-P1-10)
- tools/native_plan.py (builder keys landed in CL-P1-11)

**Steps**

1. Every target-dependent key spells PackageTarget.label / FePackageTarget.label(), never the raw option.
2. test_target_cache_identity.py runs four steps for every reachable cache and axis pair in section 6.3: cold under A; warm under B must miss and equal cold B; warm under A must hit and equal step 1; an alias of A must hit. The axes are architecture, OS and data model, environment (ABI), environment (device vs simulator, emission only on Linux), OS with the same data model, spelling, sysroot identity (stub reader via BTRC_NATIVE_HEADER_READER) and spec fingerprint. Compare the emitted C or the error, not only the counters. The stdlib archive must refuse across rows.
3. Full-matrix gate: make test, make bootstrap, make test-c11, lint, format-check, generated-check, extension, hygiene and git diff --check; push main (D4) and read CI.

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_target_cache_identity.py -q green on Linux for every axis without an SDK
- [ ] Full-matrix gate log green; ci.yml, macos.yml and windows.yml green on the pushed main (run ids in the PLAN progress entry)
- [ ] The iOS native-read row and the quiet re-measure are recorded by MAC-P1-07

**Risks**

- ModuleUnits.btrc and modules.py are the hottest pair; no other lane may hold them.
- A one-time cold rebuild everywhere (keys change).

#### Stage 25: P1 test hosts and P2 runtime parity

<a id="cl-p1-16"></a>

##### CL-P1-16 · Stage 25 P2 target probes: iOS and Android platform codes, working-directory-independent probes, D14 re-capture

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p2-target-probes`
- **Depends on:** [CL-P1-06](#cl-p1-06)
- **Why not now:** Needs the ios and android rows and labels (Stage 24 sub-batch 1) to emit and check per-target C.
- **Parallel-safe with:** CL-P1-10, CL-P1-11, CL-P1-12, CL-P1-13, CL-P1-14, CL-P1-15, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- src/runtime/c/core.c (__btrc_target_platform: 4 = iOS via __ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__, 5 = Android via __ANDROID__, each tested before __APPLE__/__linux__)
- src/runtime/c/manifest.toml (only if metadata changes)
- src/compiler/python/runtime/generated.py and src/compiler/btrc/generated/runtime/Catalog.btrc (regenerated)
- src/stdlib/Platform.btrc (compiler import: isIOS, isAndroid, isApple, isMobile)
- src/stdlib/FileSystem/ApplicationDirectories.btrc (:201 selection)
- src/stdlib/BackgroundJobs/Unix/WorkerPoolProvider.btrc (:181 selection)
- src/tests/fixtures/compiler_boundaries/manifest.toml (D14 re-capture records with reasons)
- src/tests/btrc/test_target_probes.py (new)

**Must not touch**

- frontend/Packages.btrc (hostFrom already maps unknown codes to nothing; non-host rows can never be btrcc hosts)
- the Stage 26 provider files (Process, FileSystem Windows handles, HTTP, Regex, jobs/IPC)

**Steps**

1. Add the two codes to the runtime helper and regenerate both catalogs; desktop codes are unchanged.
2. D14: re-capture shared.runtime-source and the affected order records once, with the reason recorded in the boundary manifest and passed to the integrator for PLAN.
3. Platform.btrc gains the mobile predicates; ApplicationDirectories and WorkerPoolProvider stop treating iOS as macOS and Android as Linux (selection only; real mobile providers stay with Stages 26 and 29).
4. test_target_probes.py: compile a header-free probe TU containing the helper for all 11 triples with clang and check the code per row. Run every probe program (basics/RuntimeQueries, stdlib/PlatformEuid, stdlib/PathWindowsLexical, stdlib/ApplicationDirectories) from an unrelated working directory and from a path with spaces, through both compilers; the macOS/Linux goldens stay byte-identical.

**Acceptance**

- [ ] python3 -m pytest src/tests/btrc/test_target_probes.py -q green; full corpus through both compilers with goldens unchanged
- [ ] make test-boundaries shows only the recorded D14 re-capture; make bootstrap fixed point (Platform.btrc is a compiler import); zero-warning transpiles
- [ ] gh workflow run macos.yml / windows.yml green (desktop codes unchanged); run ids reported

**Risks**

- Only one D14 re-capture per commit, and runtime/c has a single owner: serialize with CL-P1-19.
- Counts against Stage 24's 4-writer limit if run during sub-batch 3.

<a id="cl-p1-17"></a>

##### CL-P1-17 · Stage 25 target runner core: compile for a target, the executor protocol, the applicability manifest, logs and ledger ingestion

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-p2-target-runner` (core; the three executor adapters are in CX-P1-07/08/09)
- **Depends on:** [CL-P1-10](#cl-p1-10); [CL-P1-11](#cl-p1-11); [CL-P1-13](#cl-p1-13)
- **Why not now:** Needs row-driven native imports, the TargetToolchain drivers and the ABI fixture (Stage 24 sub-batch 3).
- **Parallel-safe with:** CL-P1-14, CL-P1-15, CL-P1-16, CX-P1-04, CX-P1-05, CX-P1-06

> **Review change:** Discovery by import, so `CX-P1-07/08/09` can register executors without editing `target_runner.py` (§10 C15).

**Owned paths**

- src/tests/target_runner.py (new: TargetCorpusRunner, TargetExecutor protocol, ExecutionRequest/ExecutionResult, LocalExecutor, an executor registry keyed by the TARGET_CAPABILITIES names, a CLI with --compile-only, --bundle and --execute-bundle)
- src/tests/fixtures/target-applicability.toml (new: per-program restricted/requires entries, each with a reason citing an inventory row or adaptation contract)
- tools/qualification/adapters.py (new TargetRunAdapter: runner logs to ledger records per slice and frontend)
- src/tests/python/test_target_runner.py (new)

**Must not touch**

- src/tests/runner.py and src/tests/conftest.py (hotspots; import their helpers only)
- `tools/target_hosts/**` (Codex)
- the .github/workflows host files (Codex)

**Steps**

1. Freeze the executor protocol in the module docstring: prepare(bundle_dir, label); run(ExecutionRequest(program_id, argv, stdin, env, timeout_s, cwd_policy)) -> ExecutionResult(exit_status or None, signal, stdout bytes, stderr bytes, timed_out, duration_s, provenance {executor, device, os_build, toolchain}); close(). The registry maps names (windows-native, ios-simulator, android-emulator, local) to 'module:Class' strings, so tools/target_hosts/\<platform>/executor.py registers without import cycles.
2. Compile: for each corpus program (corpus_files.language_test_files) and frontend (reference through the Compiler API; selfhost through BTRC_TEST_BTRCC), use --target \<label>, then compile the C through tools/native_plan.TargetToolchain drivers with strict C11 flags (the windows overlay on gnu rows). Until CL-P1-15 lands, use --no-cache and no prebuilt stdlib archive.
3. Applicability: BTRC_TEST_REQUIRES directives plus target-applicability.toml plus platform-inventory.toml corpus-topic cells. Every excluded program is reported as restricted with its reason; nothing is silently excluded.
4. Execute serially per target. Write build/target-runs/\<label>/\<frontend>/\<program>.{stdout,stderr,json} and a JUnit file. Compare against expected/\<Stem>.stdout, .stderr and .warnings exactly as runner.py does.
5. Report per-target and per-frontend pass/fail/restricted/missing counts; TargetRunAdapter ingests them into the ledger (slice mapping per platform-target-contract section 1.2).
6. The registry discovers executors by importing tools.target_hosts.\<platform>.executor, so adding one needs no registry edit.

**Acceptance**

- [ ] python3 -m pytest src/tests/python/test_target_runner.py -q green (fake and local executors)
- [ ] python3 -m src.tests.target_runner --target linux-x86_64 --frontend both --executor local reproduces the host corpus results (same pass counts as make test-btrc and make test-btrc-selfhost)
- [ ] python3 -m src.tests.target_runner --target windows-x86_64 --frontend both --compile-only builds every applicable program with zig on Linux; ledger records validate with tools/qualification

**Risks**

- The protocol is the contract the three Codex lanes build against; a change after CX-P1-07/08/09 start needs their agreement.
- Without CL-P1-15, cross-target cache poisoning is possible, which is why caches are disabled until then.

<a id="cl-p1-18"></a>

##### CL-P1-18 · Stage 25 corpus triage, applicability review, per-target counts and the exit record

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p2-portable-corpus` (triage, applicability review, per-target counts and the exit record)
- **Depends on:** [CX-P1-07](codex.md#cx-p1-07); [CX-P1-08](codex.md#cx-p1-08); [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** Needs the first full-corpus logs from the three CI lanes. The Mac logs (MAC-P1-08) are folded in when they arrive.
- **Parallel-safe with:** CL-P1-19, CL-P1-20, CX-P1-10

**Owned paths**

- src/tests/fixtures/target-applicability.toml (reviewed reasons)
- docs/design/platform-inventory.toml (evidence status of corpus-topic rows from ingested results; no class change without review)
- docs/design/platform-parity.md ('#### P0 inventory' totals and a P2 results paragraph)
- PLAN.md (Stage 25 progress entry)
- `~/.cache/btrc/roadmap/stage25-triage/*.json` (triage ledger)

**Must not touch**

- fix code (routed to CL-P1-19, CL-P1-20, CX-P1-10 or the owning CX host packet)
- tools/qualification/denominators.toml

**Steps**

1. gh run download each lane's logs and collect the Mac logs. Fan out read-only triage by target x topic, in waves of at most 10.
2. Classify each failure: runtime/c (CL-P1-19); compiler, either half (CL-P1-20); stdlib in the compiler's import closure (CL-P1-20); other stdlib (CX-P1-10); executor or host (the owning CX packet); golden or test expectation; OS-restricted (an applicability entry with its adaptation reason and inventory cell).
3. After each fix wave, re-dispatch the lanes (gh workflow run `host-*.yml` --ref main), ingest the ledgers and update the counts.
4. Exit record: 100% of the applicable corpus passes through both frontends on windows-x64, windows-arm64, ios-simulator and android-x86_64 (CI) and on the Mac targets; restricted counts are reported separately; device slices are recorded as unavailable (D8).

**Acceptance**

- [ ] The triage ledger classifies 100% of failures with an owner
- [ ] make qualification-report shows per-target, per-frontend pass/restricted/missing counts; python3 -m pytest src/tests/python/test_platform_inventory.py -q passes
- [ ] PLAN.md Stage 25 progress entry with run ids, counts and the D14 approval record

**Risks**

- Do not reclassify a feasible failure as OS-restricted to finish the milestone (platform-parity section 1).

<a id="cl-p1-19"></a>

##### CL-P1-19 · Stage 25 runtime semantics: target qualification fixtures, sanitizer coverage, atomics and the runtime/c fixes

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-p2-runtime-semantics`
- **Depends on:** [CL-P1-17](#cl-p1-17); [CL-P1-16](#cl-p1-16); [CL-P1-18](#cl-p1-18)
- **Why not now:** Needs the runner core and the first triage wave; runtime/c has a single owner, so this runs after CL-P1-16's re-capture.
- **Parallel-safe with:** CL-P1-20, CX-P1-10, CX-P1-07, CX-P1-08, CX-P1-09

**Owned paths**

- src/runtime/c/ (core.c, threads.c, mutex.c, cycles.c, trycatch.c, strings.c, collections.c) and src/runtime/c/manifest.toml
- src/compiler/python/runtime/generated.py and src/compiler/btrc/generated/runtime/Catalog.btrc (regenerated)
- src/tests/fixtures/compiler_boundaries/manifest.toml (D14 re-captures, one per commit)
- src/tests/memory/ and src/tests/threads/ (new target-qualification programs with goldens)
- src/tests/btrc/test_target_runtime_semantics.py (new)

**Must not touch**

- src/runtime/c/process.c's launch seam (Stage 26 platforms-p3-windows-launch-seam)
- `tools/target_hosts/**`

**Steps**

1. Audit per platform-parity P2: ARC retain/release/adopt, cross-unit runtime state, cycle collection, destructor order, callback captures, weak/raw/native borrows, exceptions and setjmp cleanup, TLS and thread exit; pthread Thread/Mutex/jobs/SPSC and atomics on bionic, iOS and winpthreads; clocks and sleep precision, locale, Unicode conversion, environment, errno/status translation, alignment and 16 KiB pages, dynamic loading.
2. Add target fixtures for each audited contract (objects crossing native callbacks and threads included); they run in every lane through both frontends.
3. Sanitizers via the runner's C-flag option: Android ASan/HWASan plus UBSan (NDK), iOS simulator ASan/TSan/UBSan, Linux as today. Record the coverage left out (for example, no ASan on zig MinGW) instead of claiming equivalence.
4. Lock-free table: atomic_is_lock_free for each runtime atomic used in realtime code, per row; refuse non-lock-free ones in realtime code with a clear diagnostic if any exist.
5. Fix triaged runtime/c defects through this single owner, with one D14 re-capture per commit and its reason.

**Acceptance**

- [ ] The new fixtures pass on every lane and on the Mac targets through both frontends
- [ ] Sanitizer runs are clean where supported, and the omitted coverage is listed in test_target_runtime_semantics.py's report
- [ ] make test-boundaries shows only the recorded re-captures; make bootstrap fixed point; make test-c11 green

**Risks**

- Do not replace blocking waits with busy loops or weaken memory ordering (P2).

<a id="cl-p1-20"></a>

##### CL-P1-20 · Stage 25 fixes in the compilers and in the compiler's stdlib import closure, from triage

- **Owner:** Claude · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p2-portable-corpus` (compiler and compiler-import stdlib fixes)
- **Depends on:** [CL-P1-18](#cl-p1-18)
- **Why not now:** Fixes come from the triage ledger (CL-P1-18).
- **Parallel-safe with:** CL-P1-19, CX-P1-10, CX-P1-07, CX-P1-08, CX-P1-09

> **Writer note:** `Callback.btrc` was added to this packet's closure list (§9 item 5).

> **Review change:** Adds `Process.btrc`, which is in the compiler's import closure but was in neither triage set (§10 C7).

**Owned paths**

- `src/compiler/python/**` and `src/compiler/btrc/**` (only the files the triage ledger names; paired commits)
- the stdlib compiler-import closure, only the files named by triage: src/stdlib/{Vector,Map,Strings,Result,Bytes,Timer,Platform,JSON,TOML,IO,Console,Iterable,Math,OwnedBuffer,Callback,Process}.btrc, src/stdlib/FileSystem/, src/stdlib/Digest/, src/stdlib/BackgroundJobs/

**Must not touch**

- Stage 26 provider work (Windows filesystem handles, process/terminal, HTTP, Regex/glob, jobs/IPC); add only C4 #if guards or adaptation diagnostics that the portable corpus needs
- `src/runtime/c/**` (CL-P1-19)
- Codex stdlib paths (CX-P1-10)

**Steps**

1. For each triaged item: reproduce it on the lane's target, write the paired fix (Python first, then btrc, in one commit), and add a regression test.
2. For unavailable hosted names reached on mobile from compiler-import modules: add C4 guards or the platform-adaptations.md diagnostic, never a silent success.
3. Rebuild btrcc and run the bootstrap for every compiler-import change; re-dispatch the affected lanes.

**Acceptance**

- [ ] Every routed item fixed with a regression test, or re-routed with a reason
- [ ] make bootstrap fixed point; zero-warning transpiles; the affected lanes are green on re-dispatch (run ids)

**Risks**

- Overlap with the Stage 26 group's packets on Process, FileSystem and BackgroundJobs; the integrator gives each file one owner at a time.

#### Stage 26: P3 OS services

<a id="cl-p2-01"></a>

##### CL-P2-01 · Adversarial review and approval of the bucket-3 Codex contracts (Windows OS services, HTTP transport, mobile storage)

- **Owner:** Claude · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `platforms-p3-fs-windows[design-approval]`; `platforms-p3-process-terminal[design-approval]`; `platforms-p3-jobs-ipc[design-approval]`; `platforms-p3-sockets-http[contract-approval]`; `platforms-p3-fs-mobile[contract-approval]`
- **Depends on:** [CX-P2-01](codex.md#cx-p2-01); [CX-P2-02](codex.md#cx-p2-02); [CX-P2-03](codex.md#cx-p2-03)
- **Why not now:** Needs the three Codex drafts (draft PRs from codex/cx-p2-01, -02 and -03).
- **Parallel-safe with:** CL-P2-05

**Owned paths**

- PLAN.md (Stage 26 Progress-log entry)
- merge of docs/design/windows-os-services.md, http-transport.md and mobile-storage.md into main-kn9jxh

**Must not touch**

- docs/design/plan-reference.md
- the draft docs' content (review findings go back to Codex as PR review comments)

**Steps**

1. For each draft, run a read-only workflow with 2 adversarial reviewers and 1 parity reviewer. Reviewer 1 checks Win32/mobile API soundness and ownership; reviewer 2 checks the compiler-import, bootstrap and hosted-availability impact.
2. Post the blocking findings on the Codex PR, then re-review Codex's revisions until none remain unresolved.
3. Merge the docs in the next batch, and record the approvals, review files and resolutions in PLAN.md under the standing design-approval rule.
4. Turn each 'Requests to Claude' row into scope for CL-P2-02, -03, -04 and -14, or into new CL packets.

**Acceptance**

- [ ] PLAN.md lists each doc's blocking findings and their resolutions.
- [ ] The docs are on main.
- [ ] `git diff --check` is clean.

**Risks**

- The owner has not signed off the adaptations; the approval must record which defaults it assumes.

<a id="cl-p2-02"></a>

##### CL-P2-02 · Windows bounded launch seam in the runtime owner (CreateProcessW, job object, pipes, timeouts; D14)

- **Owner:** Claude · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p3-windows-launch-seam`
- **Depends on:** stage25:platforms-p2-target-probes → [CL-P1-16](#cl-p1-16); stage25:platforms-p1-host-windows → [CX-P1-07](codex.md#cx-p1-07); stage24:platforms-p1-hosted-abi-targets → [CL-P1-09](#cl-p1-09); [CL-P2-01](#cl-p2-01)
- **Why not now:** Stage 25's target probes and Windows test host have not started on 8b73c79. Stage 24's implementation waits for C4's targets.toml. runtime/c has a single owner, which works serially after the Stage 25 probes.
- **Parallel-safe with:** CL-P2-05, CL-P2-06, CX-P2-04, CX-P2-07, CX-P2-09

**Owned paths**

- src/runtime/c/process.c
- src/runtime/c/btrc_rt.h
- src/runtime/c/manifest.toml
- src/language/hosted_abi.toml (windows-row availability of the helpers' Win32 names, if needed)
- src/compiler/python/runtime/generated.py and src/compiler/btrc/generated/runtime/Catalog.btrc (regenerated)
- src/runtime/windows/btrc_win_compat.h
- src/tests/fixtures/compiler_boundaries/manifest.toml (one D14 re-capture)
- src/tests/native/windows_launch/ (new)
- src/tests/python/test_windows_launch_seam.py (new)
- `src/tests/fixtures/expected-skips/*.json` (rules for the new test)

**Must not touch**

- src/stdlib/Process.btrc (CX-P2-06)
- `src/stdlib/FileSystem/**` (CX-P2-04/05)
- docs/design/plan-reference.md

**Steps**

1. Implement CX-P2-01's requested helper surface as pre-authored C in process.c between btrc-runtime-helper markers, compiled only on _WIN32, with manifest rows in both compiler orders. It covers: CreateProcessW with CREATE_SUSPENDED and STARTUPINFOEXW, where PROC_THREAD_ATTRIBUTE_HANDLE_LIST lets only the 3 stdio pipe ends inherit; AssignProcessToJobObject with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE before ResumeThread; draining both pipes without deadlock under byte bounds; a bounded wait that calls TerminateJobObject on timeout; canonical CommandLineToArgvW-compatible quoting from a UTF-8 argv; UTF-8↔UTF-16 conversion; and distinct launch-failure codes.
2. Run make compiler-codegen-generate. The reference collectors in both compilers select the helpers only when referenced, and Linux/macOS emitted C stays byte-identical over the corpus.
3. D14: re-capture shared.runtime-source and the helper-order boundary records once, with the reason and both compilers in parity; run make boundary-check.
4. Add a native Windows fixture in src/tests/native/windows_launch/ (a C harness plus a btrc program over a test binding), driven by test_windows_launch_seam.py. It covers argv with spaces, quotes, trailing backslashes and non-ASCII characters; stdout/stderr limits; timeout kill of a 3-level process tree; and launch failure (missing exe, bad cwd).
5. Compile the helpers on Linux with zig cc -target x86_64-windows-gnu and aarch64-windows-gnu, using -std=c11 -Werror -pedantic.
6. Dispatch `gh workflow run windows.yml --ref <lane branch>`. Then integrate in a D5 batch, record D14 in PLAN.md, and push main fast-forward only.

**Acceptance**

- [ ] A windows.yml run on the lane branch is green with test_windows_launch_seam.py passing (counts and run id) and the native bootstrap step green.
- [ ] Linux passes make test, make test-c11, make bootstrap, make lint, make format-check, `python -m tools.compiler_codegen.main check` and boundary-check (only the declared records change), with zero-warning transpiles of BtrccMain, cli/WindowsMain and cli/MacOSMain.
- [ ] PLAN.md records the D14 reason.

**Risks**

- CI processes already run inside a job, so the design relies on nested jobs (supported from Windows 8).
- PROC_THREAD_ATTRIBUTE_JOB_LIST is Win10+ and may be missing from the MinGW headers.
- Draining two pipes needs threads or overlapped I/O.

<a id="cl-p2-03"></a>

##### CL-P2-03 · Hosted-ABI route for Windows regex/glob/fnmatch (vendored engine)

- **Owner:** Claude · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `platforms-p3-regex-glob[hosted-abi]`
- **Depends on:** stage24:platforms-p1-hosted-abi-targets → [CL-P1-09](#cl-p1-09)
- **Why not now:** Stage 24 sub-batch 2 (hosted-ABI [[platform_targets]] availability tables) does not exist yet.
- **Parallel-safe with:** CL-P2-02, CL-P2-04

**Owned paths**

- src/language/hosted_abi.toml
- src/compiler/python/abi/generated.py and src/compiler/btrc/generated/hosted_abi/Tables.btrc (regenerated)
- src/tests/python/test_hosted_abi_platform_names.py

**Must not touch**

- src/stdlib/Regex.btrc and src/stdlib/Pattern.btrc (CX-P2-13)
- src/runtime/windows/regex.h, glob.h, fnmatch.h (CX-P2-13)

**Steps**

1. Choose and record the route with CX-P2-13. Route (a): the overlay shims become real declarations and regcomp/regexec/regerror/regfree, glob/globfree, fnmatch and the REG_/GLOB_/FNM_ names become available on the windows rows. Route (b): a stdlib provider with its own binding, under which the hosted names stay unavailable and this packet is a recorded no-op.
2. For route (a), edit the windows-gnu and msvc [[platform_targets]] unavailable lists and regenerate. Add a test that a windows-x86_64 program reaching Regex passes the optimizer availability check, while Linux/macOS output stays unchanged.
3. Integrate before CX-P2-13 lands.

**Acceptance**

- [ ] The generated-source check is clean, and test_hosted_abi_platform_names.py plus Stage 24's availability test pass.
- [ ] Regex corpus programs transpile for windows-x86_64 with zero diagnostics through both compilers.
- [ ] make test passes, and make bootstrap reaches its fixed point.

**Risks**

- Stage 24's availability model may not express 'available when a vendored source is linked'; route (b) is the fallback.

<a id="cl-p2-04"></a>

##### CL-P2-04 · Dev-shell inputs for native HTTP transports and TLS test endpoints

- **Owner:** Claude · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 2 agent-hours
- **PLAN items:** `platforms-p3-sockets-http[flake-inputs]`
- **Depends on:** [CL-P2-01](#cl-p2-01)
- **Why not now:** Waits for the approved HTTP contract (CX-P2-02 via CL-P2-01) to confirm libcurl on Linux and the test-CA tooling.
- **Parallel-safe with:** CL-P2-02, CL-P2-03

**Owned paths**

- flake.nix
- flake.lock
- src/tests/fixtures/expected-skips/linux-devcontainer.json (only if a skip changes)

**Must not touch**

- `src/stdlib/HTTP/**` (CX-P2-09)

**Steps**

1. Add curl.dev (libcurl with pkg-config) and openssl to the dev shell and the devcontainer inputs, and root the profile under ~/.cache/btrc/gcroots in Mac gates.
2. Check `nix develop --command pkg-config --modversion libcurl` on Linux and on the macOS CI dev shell.
3. Rebuild the devcontainer, run the `make linux-ci` smoke (lint, format-check), and integrate.

**Acceptance**

- [ ] pkg-config resolves libcurl in nix develop.
- [ ] The ci.yml devcontainer build is green (run id), and the make test counts are unchanged.

**Risks**

- Nix substitution flakes in CI (ci-health.md).

<a id="cl-p2-27"></a>

##### CL-P2-27 · Land the Windows FileSystem and Process providers into btrcc (W1 host): integration, WindowsMain C review, native bootstrap

- **Owner:** Claude · **Group:** P2 · **Stage:** Stage 26 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `platforms-p3-fs-windows#btrcc-host`; `platforms-p3-process-terminal#btrcc-host`
- **Depends on:** [CX-P2-04](codex.md#cx-p2-04) (ready); [CX-P2-05](codex.md#cx-p2-05) (ready); [CX-P2-06](codex.md#cx-p2-06) (ready)
- **Why not now:** Needs the three Codex provider branches ready.

> **Review change:** New (§10 C7). FileSystem and Process are in btrcc's import closure, and their Windows providers are selected when `cli/WindowsMain.btrc` is transpiled, so these Codex branches change `btrcc.exe` by design; Claude lands them, as it owns the W1 host.

**Owned paths**

- integration branch integ/w-fs-process
- src/compiler/btrc/cli/WindowsMain.btrc (only if host composition must change; hotspot)
- FileSystem and root btrc.toml (integrator: applies fragments; not held)
- PLAN.md (Progress)

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Rebase CX-P2-04, CX-P2-05 and CX-P2-06 in that order on main-kn9jxh, drop `derived:` commits, apply fragments, regenerate.
2. Show btrcc's own C is byte-identical for BtrccMain (locally) and cli/MacOSMain (macos.yml bootstrap shard), and review the cli/WindowsMain diff for windows-x86_64 and windows-aarch64: only the provider dispatch the three packets intend.
3. Gate: the cloud batch gate (§3.8), then windows.yml's native three-stage bootstrap and the Windows FileSystem and Process suites on host-windows.yml (run ids). Push main and read the three workflows.

**Acceptance**

- [ ] windows.yml's native three-stage bootstrap reaches a byte-identical fixed point with the new providers (run id).
- [ ] BtrccMain and MacOSMain C unchanged; the WindowsMain C diff is recorded in the lane report.
- [ ] All three workflows green on main; CX-P2-04/05/06 recorded done.

#### Stage 27: W1 Windows host and interop lane I (one ownership design, function tables, early Objective-C and JNI slices, then COM)

<a id="cl-p2-05"></a>

##### CL-P2-05 · Interop step 1: native_abi schema v2 (callback_parameters, real calling conventions)

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-interop-function-table-calls[step1-schema-v2]`
- **Depends on:** stage24:platforms-p1-native-import-targets → [CL-P1-10](#cl-p1-10); stage24:platforms-p1-abi-fixture → [CL-P1-13](#cl-p1-13); [CL-C-40](#cl-c-40)
- **Why not now:** items.json makes function-table calls depend on Stage 24 sub-batch 3 (native-import targets, ABI fixture), which has not started (Stage 24 waits for C4). D1 bucket order applies too; see the open question about admitting it early.
- **Parallel-safe with:** CL-P2-02, CL-P2-03, CX-P2-04

> **Review change:** Interop (`CL-P2-05`…`24`) waits for bucket 2's close (`CL-C-40`): D27 lets only Stage 24 and Stage 25's compiler packets start early (§2, §10 P3).

**Owned paths**

- src/language/native_abi.asdl
- src/compiler/python/abi/native_generated.py and src/compiler/btrc/generated/native_abi/Models.btrc (regenerated)
- tools/NativeHeaderReader.cpp
- src/compiler/python/frontend/native_imports.py (NativeHeaderCodec, convention check)
- src/compiler/btrc/frontend/NativeImports.btrc
- src/tests/python/test_native_header_reader.py
- src/tests/python/test_native_import_semantics.py
- src/tests/btrc/ (codec parity test)

**Must not touch**

- `src/stdlib/**` in-flight Codex paths
- docs/design/plan-reference.md

**Steps**

1. Following native-interop-ownership.md §3 and §6 row 1, add NativeField.callback_parameters. The reader fills names, no_escape, ns_consumed and cf_consumed from FunctionProtoTypeLoc and ExtParameterInfo.
2. Make the reader report real calling conventions (c, x86_stdcall, win64, aapcs) instead of rejecting them.
3. Bump both codecs from btrc.native-declarations.experimental to v2 in one commit; both importers reject conventions other than c with identical text.
4. Run make compiler-codegen-generate and confirm no existing btrc field was renamed (tools/compiler_codegen/ast.py rename rule). The Python commit lands first, then its btrc twin.

**Acceptance**

- [ ] Reader goldens cover slot names and no_escape, and both compilers pass the codec round trip and the length-mismatch rejection.
- [ ] `python -m tools.compiler_codegen.main check` is clean, with no renamed field.
- [ ] make test passes, make bootstrap reaches its fixed point, and boundary-check is unchanged; the macos.yml reader shard is green (run id).

**Risks**

- Rebuilding the reader invalidates header caches; the reader-digest key already covers that.

<a id="cl-p2-06"></a>

##### CL-P2-06 · Interop step 2: checked function-table calls (dispatch keys, M1 adapters, verifier rules 1 and 3, R3 pinning, D14)

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-interop-function-table-calls[step2-function-tables]`
- **Depends on:** [CL-P2-05](#cl-p2-05)
- **Why not now:** Follows schema v2 (CL-P2-05).
- **Parallel-safe with:** CL-P2-02, CX-P2-04, CX-P2-09

**Owned paths**

- src/compiler/python/frontend/packages.py and src/compiler/btrc/frontend/Packages.btrc (dispatch subtable, three-part names, release-executor)
- src/compiler/python/frontend/native_imports.py (_project_dispatch_tables) and NativeImports.btrc
- src/compiler/python/analyzer/expressions.py, analyzer/ownership.py and their btrc analyzer/ and analyzer/ownership/ owners
- src/compiler/python/ir/lowering/functions.py and src/compiler/btrc/ir/lowering/Declarations.btrc
- src/compiler/python/ir/verifier.py and src/compiler/btrc/ir/optimization/Cleanup.btrc/Optimizer.btrc
- src/runtime/c/threads.c, manifest.toml and the generated catalogs (holder thread pthread_t+generation, one D14)
- src/language/package-manifest.md
- src/tests/fixtures/compiler_boundaries/manifest.toml
- src/tests/native/interop/function_tables/ (new Codec vtable fixture)
- src/tests/python/native_import_fixtures.py (Linux sysroot variant of native_project)
- src/tests/python/test_native_dispatch_tables.py (new) and its btrc twin

**Must not touch**

- `src/stdlib/**` Codex paths
- docs/design/plan-reference.md

**Steps**

1. Add the dispatch subtable keys and the "\<R>.\<method>" / "\<R>.\<method>.\<parameter>" names in both manifest parsers. Unknown keys are refused.
2. Project private dispatch records and build the M1 adapters, IRVarDecl table and slot with nativeNullGuard, through the indirect IRCall callee and with no new IR node. Add verifier rules 1 and 3, the direct R3 cycle rule and R3 entry pinning.
3. Upgrade the holder thread check to pthread_t plus generation through the runtime/c single owner, as one D14 re-capture with its reason.
4. Emit the §5 function-table diagnostics with identical text in both compilers. Land Python first, then the btrc twin, one commit per construct.
5. Codec vtable fixture: decode and reset, a table swap, alias plus close() destroying once, and live count 0 after 1,000 iterations. Add a Reader-table loopback with a method that closes its own stream mid-call, and the negatives: a null slot aborts, a close inside a callback aborts, a slot read is rejected, a self-cycle is rejected.

**Acceptance**

- [ ] The fixture passes at -O2 and under ASan/UBSan through both compilers.
- [ ] make test and make test-c11 pass, and the feature make bootstrap reaches its fixed point; boundary-check shows only the declared D14 records; macos.yml is green (native_project on macOS, run id).
- [ ] PLAN.md has a Stage 27 step 2 entry.

**Risks**

- The analyzer and lowering hotspots are shared with the C2/C3 lanes, so integrate after C3 or rebase carefully.
- Off-thread release semantics are easy to get wrong.

<a id="cl-p2-07"></a>

##### CL-P2-07 · Interop step 3: Objective-C slice (schema v3 protocols/properties/main_actor, checked delegates)

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-i1-objc-protocol-adapters[step3-objc-slice]`
- **Depends on:** [CL-P2-06](#cl-p2-06); stage24:platforms-p1-target-spec → [CL-P1-06](#cl-p1-06)
- **Why not now:** Follows function tables (CL-P2-06) and needs the ios target rows (Stage 24 sub-batch 1).
- **Parallel-safe with:** CL-P2-02, CX-P2-04, CX-P2-10

**Owned paths**

- src/language/native_abi.asdl (v3) and the generated modules
- tools/NativeHeaderReader.cpp (protocols, properties, requirements, main_actor, method flags)
- native_imports.py / NativeImports.btrc (required-method, property-ownership and main-actor checks)
- packages.py / Packages.btrc (derived main executors)
- ir/verifier.py and its btrc validator (slot check inside the pool)
- src/tests/python/test_native_objective_c_delegates.py
- src/tests/native/objective_c/ (objc_root_class reader fixtures)

**Must not touch**

- `src/stdlib/HTTP/MacOS/**` (CX-P2-09)
- docs/design/plan-reference.md

**Steps**

1. Following §3 step 3, add protocol_declarations, interface protocols, properties and main_actor, plus the three method flags, and bump both codecs to v3 in one commit.
2. Run the reader goldens on Linux with objc_root_class fixtures.
3. Extend test_native_objective_c_delegates.py with weak and strong property variants, an optional method, a missing-required-method rejection naming declaring_protocol, a main-actor guard and an off-thread holder release (rule 4).
4. Cross-compile the Foundation-only delegate fixture for arm64-apple-ios17.0-simulator through the Stage 24 row. Hand the simulator round trip to MAC-P2-02, and run it on a GitHub macOS runner simulator as supplementary evidence if Stage 25's iOS host allows.

**Acceptance**

- [ ] The Linux reader goldens pass.
- [ ] The macos.yml unit shard passes the extended delegate tests through both compilers (run id).
- [ ] make test passes and the feature bootstrap reaches its fixed point; the PLAN.md entry records the macOS evidence and the pending simulator row.

**Risks**

- Both importers reject Objective-C off macOS targets, so the diagnostics run only on macOS CI.

<a id="cl-p2-08"></a>

##### CL-P2-08 · Interop step 4a: tools/JavaClassReader.c v1, flake build and schema v4

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-a1-checked-jni[step4-reader-schema-v4]`
- **Depends on:** [CL-P2-07](#cl-p2-07); stage23:tooling-android-sdk-ndk → [CL-P1-02](#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03)
- **Why not now:** The serial interop order puts this after the Objective-C slice. It also needs a JDK and android.jar in the dev shell (Stage 23).
- **Parallel-safe with:** CL-P2-11, CX-P2-10, CX-P2-13

**Owned paths**

- tools/JavaClassReader.c (new; C11 + zlib)
- flake.nix (reader package, zlib, JDK in the test shell)
- src/language/native_abi.asdl (v4: NativeJavaClass/Method/Field, NativeJavaObject/Array) and the generated modules
- both codecs (native_imports.py, NativeImports.btrc)
- src/tests/native/java/ (javac-built fixture classes)
- src/tests/python/test_java_class_reader.py (new)

**Must not touch**

- `src/stdlib/**` Codex paths
- docs/design/plan-reference.md

**Steps**

1. The reader reads jar entries (zlib inflate), class files, descriptors and access flags, and omits non-public, synthetic and bridge members.
2. It spells identity in smali form, reports compiler_version as btrc-class-reader/1 sha256:\<classpath digest>, gives source_file as \<jar>!\<path>.class, and uses the batch protocol (D22).
3. Add the schema v4 delta to the ASDL with both codecs bumped in one commit, and build the reader in the flake.
4. Add reader goldens over javac-built fixtures and the codec round trip.

**Acceptance**

- [ ] The reader goldens pass, and the codec round-trip passes in both compilers.
- [ ] The generated-source check is clean; make test passes; make bootstrap reaches its fixed point.

**Risks**

- Class-file major versions in android.jar.
- Building the jar reader adds a flake dependency.

<a id="cl-p2-09"></a>

##### CL-P2-09 · Interop step 4b: checked JNI calls (Java importer branch, src/stdlib/Java, verifier rule 2, host-JVM CheckJNI)

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-a1-checked-jni[step4-jni-calls]`
- **Depends on:** [CL-P2-08](#cl-p2-08); stage25:platforms-p1-host-android → [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** Follows CL-P2-08. The emulator round trip needs Stage 25's Android host.
- **Parallel-safe with:** CL-P2-11, CL-P2-12, CX-P2-17

**Owned paths**

- native_imports.py / NativeImports.btrc (Java branch, language="java" validator, BTRC_JAVA_CLASSPATH)
- packages.py / Packages.btrc (dispatch-records)
- ir/lowering and the btrc lowering owners (class resources as global refs, static and instance calls, fields, local frames)
- ir/verifier.py and its btrc validator (rule 2)
- src/stdlib/Java/ (new: JavaVirtualMachine, env key, attach/detach, exception translation, UTF-16, jni.h binding)
- src/stdlib/btrc.toml [dependencies] row (applied by Claude)
- src/tests/python/test_native_jni_host.py (new)

**Must not touch**

- `src/stdlib/HTTP/Android/**` (CX-P2-12)
- docs/design/plan-reference.md

**Steps**

1. Implement step 4 of the §6 table, landing Python first and then the btrc twin, one commit per construct.
2. Build the host-JVM test on JNI_CreateJavaVM with -Xcheck:jni, where any CheckJNI warning fails. It covers a `"a\0é𝄞"` string round trip, a static field read, a Java exception becoming JavaException, a btrc-spawned thread attaching and detaching, 10,000 object-returning calls with no frame leak, and a user global-ref count of 0 before DestroyJavaVM.
3. Run the emulator round trip through app_process with the pushed .dex and .so and debug.checkjni 1, on a GitHub ubuntu KVM runner for API 29 and API 36 x86_64. The arm64 16 KiB image runs in MAC-P2-02.

**Acceptance**

- [ ] The host-JVM test passes through both compilers.
- [ ] The emulator run passes with no CheckJNI abort in logcat (run id).
- [ ] make test passes and the feature bootstrap reaches its fixed point; PLAN.md has a step 4 entry.

**Risks**

- Hosted KVM availability.
- JVM lifetime ownership in tests.

<a id="cl-p2-10"></a>

##### CL-P2-10 · Interop step 5: COM (ownership=com, QI, status/copied outputs, com-sinks, src/stdlib/COM) with exact release counts

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-w1-win32-com-imports[step5-com]`
- **Depends on:** [CL-P2-09](#cl-p2-09); [CX-P2-17](codex.md#cx-p2-17); stage24:platforms-p1-native-import-targets → [CL-P1-10](#cl-p1-10)
- **Why not now:** Serial after the JNI slice. It needs the fixture servers (CX-P2-17) and windows-gnu header reads (Stage 24).
- **Parallel-safe with:** CL-P2-11, CL-P2-12, CX-P2-10, CX-P2-13

**Owned paths**

- packages.py / Packages.btrc (ownership=com, iid, base, apartment executors, status-results, copied-outputs, com-sinks)
- native_imports.py / NativeImports.btrc (slot-hook validation, dispatch over lpVtbl)
- the lowering owners (M3 QueryInterface, sameObject) and the verifier
- src/stdlib/COM/ (new: COMApartment, combaseapi binding, links ole32 and uuid)
- src/stdlib/btrc.toml [dependencies] row
- `src/tests/native/com/*.btrc` (btrc side; owns the directory after CX-P2-17 merges)
- src/tests/python/test_native_com.py (new)

**Must not touch**

- `src/stdlib/Audio/Windows/**` and `src/stdlib/Image/Windows/**` (later Codex packets)
- docs/design/plan-reference.md

**Steps**

1. Implement step 5 of the §6 table, landing Python first and then btrc, one commit per construct, with the §5 COM diagnostics identical in both compilers.
2. Run the Linux proxy suite covering slot validation, dispatch, claim adoption, QI, the sink holder including Unadvise inside an event, cycle teardown and exact counts under sanitizers.
3. Run the reader with --target=x86_64-w64-mingw32 over real mingw-w64 headers to check the vtable layouts.
4. Run the Windows CI round trip through both frontends: live count 0, releases equal to claims, a sink peak of 2 ending at 0, and the receiver destroyed once. Add a second test where CreateStreamOnHGlobal, QI'd to ISequentialStream, has its last Release return 0.

**Acceptance**

- [ ] The Linux proxy suite passes at -O2 and under sanitizers through both compilers.
- [ ] The Windows run (windows.yml dispatch on the lane) passes the exact-count tests (run id).
- [ ] make test passes and the feature bootstrap reaches its fixed point; PLAN.md has a step 5 entry.

**Risks**

- Free-threaded (MTA) sinks wait for atomic ARC (open question 3 in the design).

<a id="cl-p2-11"></a>

##### CL-P2-11 · Windows SDK-reader process provider in WindowsMain.btrc; native Windows btrcc imports Win32 headers

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-w1-sdk-reader-provider`; `platforms-w1-win32-com-imports[native-win32-import]`
- **Depends on:** [CL-P2-02](#cl-p2-02); stage23:tooling-windows-ci-arm64-llvm → [CX-P1-03](codex.md#cx-p1-03); stage24:platforms-p1-native-import-targets → [CL-P1-10](#cl-p1-10)
- **Why not now:** Needs the launch seam (CL-P2-02), an LLVM-backed native-header reader built on Windows (Stage 23's tooling-windows-ci-arm64-llvm) and windows-gnu reader targets (Stage 24).
- **Parallel-safe with:** CL-P2-12, CL-P2-09, CX-P2-05, CX-P2-10

**Owned paths**

- src/compiler/btrc/cli/WindowsMain.btrc
- the Windows reader-process owner: preferably inside cli/WindowsMain.btrc; if a new frontend file is unavoidable, also docs/design/compiler-structure.md, src/tests/btrc/test_compiler_structure_contract.py and AGENTS.md (inventory 97→98)
- src/compiler/python/frontend/native_imports.py (Windows reader launch in the reference CLI)
- tools/NativeHeaderReader.cpp (Windows portability: locking, directory walk, process APIs)
- .github/workflows/windows.yml (SDK import fixture step)
- src/tests/python/test_windows_sdk_reader.py (new)

**Must not touch**

- `src/stdlib/FileSystem/**` and Process.btrc (Codex)
- docs/design/plan-reference.md

**Steps**

1. Implement an FeNativeHeaderReader over the launch seam with bounded input and output, a timeout, cancellation, launch errors and a reader version check.
2. Make the reader portable on Windows, replacing flock, dirent and unistd with Win32 equivalents behind its existing owners.
3. Have native Windows btrcc import a Win32 header selection (GetCurrentProcessId, CreateEventW, WaitForSingleObject) and run the Stage 24 ABI fixture's callback.
4. Test the failure paths: a missing reader, a timeout, a bad version and oversized output.
5. Keep the cli/WindowsMain.btrc transpile at zero warnings for windows-x86_64 and windows-aarch64.

**Acceptance**

- [ ] windows.yml on the lane runs green with the SDK import fixture step and test_windows_sdk_reader.py (run id).
- [ ] The Linux make test passes, make bootstrap reaches its fixed point, and the native Windows bootstrap passes; the exact-inventory test is updated if a file was added.

**Risks**

- The pinned LLVM for Windows hosts (MSYS2 clang64, llvm-mingw or a source build) and its bundle size.
- A new compiler file breaks D21's unchanged inventory.

<a id="cl-p2-12"></a>

##### CL-P2-12 · btrcc worker pool on Windows: spawned workers over the launch seam (parallel == serial)

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-w1-worker-pools[btrcc]`
- **Depends on:** [CL-P2-02](#cl-p2-02); [CL-P2-11](#cl-p2-11)
- **Why not now:** Needs the launch seam, and it coordinates WindowsMain.btrc with CL-P2-11.
- **Parallel-safe with:** CL-P2-09, CL-P2-10, CX-P2-05

> **Review change:** Narrowed to the file it names; `CX-P2-15` adds `BackgroundJobs/Windows/ProcessThreadsProvider.btrc` (§10 C16).

**Owned paths**

- src/stdlib/BackgroundJobs/WorkerPoolProvider.btrc (Windows provider)
- src/stdlib/BackgroundJobs/HostWorkerPools.btrc
- src/stdlib/BackgroundJobs/WorkerPools.btrc (protocol, if needed)
- src/stdlib/BackgroundJobs/Windows/WorkerPoolProvider.btrc (new spawned-worker provider; the directory is shared with CX-P2-15's ProcessThreadsProvider.btrc)
- src/compiler/btrc/cli/WindowsMain.btrc (pass HostWorkerPools)
- src/compiler/btrc/pipeline/ModuleUnits.btrc (worker re-entry; hotspot)
- src/compiler/btrc/cli/Driver.btrc (worker mode)
- src/tests/btrc/test_windows_worker_pools.py (new)

**Must not touch**

- `src/stdlib/BackgroundJobs/ProcessThreads*`, NativeThreads.h and the btrc.toml binding rows (CX-P2-15)
- docs/design/plan-reference.md

**Steps**

1. Spawn worker processes through the seam, with anonymous pipes carrying the existing 16-hex-digit frame protocol and the same lower/setjmp/realtime/finish requests.
2. Workers re-enter btrcc in worker mode and rehydrate the analyzed state. Choose between deterministic recomputation and a serialized snapshot by measuring both.
3. Keep the BTRC_TIMING worker lines, taking usage from GetProcessTimes and PROCESS_MEMORY_COUNTERS in place of wait4.
4. Test on Windows that a module-unit compile of the btrcc sources with --jobs 4 is byte-identical to --jobs 1, and record the cold self-compile time, naming the C compiler.

**Acceptance**

- [ ] The Windows run shows the parallel and serial outputs byte-identical (run id) and records the measured cold self-compile time.
- [ ] The Linux and macOS module-unit suites (test_native_compile_workers.py and the module-unit tests) pass unchanged, and make bootstrap reaches its fixed point.

**Risks**

- Rehydration cost may cancel the parallel speedup on Windows.
- The ModuleUnits.btrc hotspot is shared with bucket-1 work.

<a id="cl-p2-13"></a>

##### CL-P2-13 · Reference compiler worker pool on Windows (spawn-based, parallel == serial)

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-w1-worker-pools[python]`
- **Depends on:** [CL-P2-12](#cl-p2-12)
- **Why not now:** Reuses the worker protocol settled in CL-P2-12.
- **Parallel-safe with:** CL-P2-10, CL-P2-14

**Owned paths**

- src/compiler/python/application/modules.py (hotspot)
- src/compiler/python/cli/compiler.py (worker mode, if needed)
- src/tests/python/test_module_units_windows_pool.py (new)

**Must not touch**

- `src/compiler/btrc/**` (done in CL-P2-12)
- docs/design/plan-reference.md

**Steps**

1. Replace the os.fork path (modules.py:314) on Windows with spawned reference-CLI workers that speak the same request protocol and rehydrate the state.
2. Test on the Windows runner that parallel output is byte-identical to serial, and confirm that Linux keeps fork.

**Acceptance**

- [ ] The Windows run passes the byte-identity test (run id); make test passes on Linux.

**Risks**

- The cost of starting Python workers on Windows.

<a id="cl-p2-14"></a>

##### CL-P2-14 · Unicode compiler host on Windows (wide argv/env/console, paths, bundle discovery) and compat-shim retirement

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-w1-unicode-host`; `platforms-p3-fs-windows[compat-shim-retirement]`
- **Depends on:** [CL-P2-27](#cl-p2-27); [CL-P2-11](#cl-p2-11)
- **Why not now:** PLAN requires the Windows filesystem merge first (CX-P2-04/05), and the SDK-reader invocation comes from CL-P2-11.
- **Parallel-safe with:** CL-P2-13, CL-P2-10, CX-P2-06

> **Review change:** Waits for `CL-P2-27`, which lands the Windows filesystem (PLAN: the Unicode host follows Stage 26's filesystem work) (§10 C7).

**Owned paths**

- src/compiler/btrc/cli/Driver.btrc (hotspot)
- src/compiler/btrc/cli/WindowsMain.btrc
- src/compiler/btrc/frontend/SourceIo.btrc
- src/compiler/python/main.py
- src/compiler/python/cli/compiler.py
- src/compiler/python/artifacts/ (bundle discovery)
- src/runtime/c/core.c and the manifest (Windows argv/env/console helpers; D14 if the runtime source changes)
- src/runtime/windows/btrc_win_compat.h, btrc_win_realpath.h, README.md
- src/tests/python/test_windows_unicode_host.py (new)

**Must not touch**

- `src/stdlib/FileSystem/**` (Codex-owned)
- docs/design/plan-reference.md

**Steps**

1. Build UTF-8 argv from GetCommandLineW and CommandLineToArgvW, read the environment through GetEnvironmentStringsW, and write diagnostics through WriteConsoleW when attached to a console (UTF-8 otherwise).
2. Route source, import and cache paths through the Windows FileSystem provider, pass UTF-16 arguments to the SDK reader, and discover the bundle with GetModuleFileNameW.
3. Give the Python CLI the same behaviour (stdout reconfigure, fsencode).
4. Retire the shims listed by CX-P2-01 whose consumers have migrated.

**Acceptance**

- [ ] A PowerShell job on windows-latest compiles a project under a non-ASCII directory with spaces through the bundle from an unrelated cwd (run id).
- [ ] Diagnostics round-trip, matching a golden that contains the non-ASCII path, and cache paths are stable across two runs.
- [ ] make test, make test-c11 and make bootstrap pass, plus the D14 record if the runtime source changed.

**Risks**

- The Driver.btrc hotspot.
- The console code page differs across runner shells.

<a id="cl-p2-15"></a>

##### CL-P2-15 · Windows relocatable bundle, PowerShell invocation, native-plan realization and debug line mapping

- **Owner:** Claude · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-w1-ci-and-bundle[bundle-plan-debug]`
- **Depends on:** [CL-P2-11](#cl-p2-11); [CL-P2-14](#cl-p2-14); stage25:platforms-p2-ci-lanes → [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** Needs the SDK reader, the Unicode host and Stage 25's Windows corpus lane.
- **Parallel-safe with:** CL-P2-12, CL-P2-13, CX-P2-17

**Owned paths**

- src/compiler/python/artifacts/selfhost.py and archive.py (bundle layout and launcher)
- tools/native_plan.py (Windows realization: zig cc driver, .exe/.dll naming, import libraries; hotspot)
- Makefile (btrcc-windows targets)
- .github/workflows/windows.yml (bundle, plan realization and line-mapping steps)
- `src/tests/python/test_btrcc_bundle*.py`
- src/tests/debug/ (Windows line-mapping subset)

**Must not touch**

- new Codex workflow files (CX-P2-18)
- docs/design/plan-reference.md

**Steps**

1. Make btrcc.exe in the relocatable bundle invocable from PowerShell with no MSYS shell; keep the junction and space-path checks.
2. Realize native plans on Windows for examples/native-package and the ABI fixture.
3. Add the debug line-mapping tests for Windows paths (#line with backslashes).

**Acceptance**

- [ ] A green windows.yml run on one revision covers the corpus shard (from the Stage 25 lane), the bootstrap fixed point, the SDK fixture and the PowerShell step (run id).
- [ ] make test passes.

**Risks**

- The native_plan.py hotspot is shared with Stage 28's library work (CL-P2-20).

#### Stage 28: P4 dependency closure and library artifacts (W1 exit)

<a id="cl-p2-16"></a>

##### CL-P2-16 · BTRSmith target abstraction: Config.mk/Toolchain.mk/flake systems generalized to btrc target labels

- **Owner:** Claude · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-cross-target-build[target-abstraction]`
- **Depends on:** stage24:platforms-p1-native-plan-toolchain → [CL-P1-11](#cl-p1-11), [CL-P1-12](#cl-p1-12); stage24:platforms-p1-cache-identity → [CL-P1-15](#cl-p1-15); [CL-P2-15](#cl-p2-15)
- **Why not now:** Needs Stage 24's link plan v5 and canonical labels plus a working W1 bundle (items.json: btrc:P1, btrc:W1).
- **Parallel-safe with:** CL-P2-19, CX-P2-25

**Owned paths**

- BTRSmith make/Config.mk, make/Toolchain.mk, make/Packaging.mk (target selection only)
- BTRSmith flake.nix (systems)
- BTRSmith make/targets/ (new per-target fragment hook)
- BTRSmith tests/packaging/BuildArtifacts.py

**Must not touch**

- BTRSmith packaging/{windows,ios,android} (CX-P2-19/20/21)
- BTRSmith `packages/**` (CX-P2-22/23/24)

**Steps**

1. Generalize HOST_SYSTEM and HOST_ARCH (Config.mk:23-50) to a TARGET canonical label with a host default, relax require-native-host (Toolchain.mk:13-19) per target, build the .clang test binaries per target and add the make/targets/\<label>.mk hook.
2. Hash the Linux host build artifacts before and after the change and require them byte-identical.
3. Push a BTRSmith branch and let its Linux CI run (D26).

**Acceptance**

- [ ] BTRSmith application-frontend-check passes on Linux through both frontends, and the Linux host artifacts are byte-identical (sha256 list).
- [ ] BTRSmith Linux CI is green (run id); the macOS identity check is in MAC-P2-03.

**Risks**

- The Make graph is a hotspot with a single owner.

<a id="cl-p2-17"></a>

##### CL-P2-17 · Stage 28 nix and lock integration: wgpu-native pins and dependency locks merged serially

- **Owner:** Claude · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `tooling-cross-gpu-deps[flake-merge]`; `platforms-p4-dependency-crossbuild[lock-merges]`; `btrsmith-package-closure[lock-merges]`
- **Depends on:** [CX-P2-22](codex.md#cx-p2-22); [CX-P2-23](codex.md#cx-p2-23); [CX-P2-24](codex.md#cx-p2-24); [CX-P2-25](codex.md#cx-p2-25)
- **Why not now:** Merges the four Codex dependency packets' pins and fragments.
- **Parallel-safe with:** CL-P2-19, CL-P2-20

**Owned paths**

- flake.nix, flake.lock
- BTRSmith flake.nix, flake.lock, btrc.lock (integrator: applies fragments; not held)
- src/stdlib/GPU/btrc.toml, GUI/btrc.toml, Image/btrc.toml (applying fragments) (integrator: applies fragments; not held)
- src/stdlib/btrc.lock, btrc.symbols (regenerated) (integrator: applies fragments; not held)

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Add fetchurl derivations per slice from CX-P2-25's pins and dev-shell variables per slice, and root the profiles.
2. Merge the BTRSmith locks serially in dependency order (psarc and sloppak after zlib, miniz and yaml).
3. Regenerate the derived files, run the gates and push.

**Acceptance**

- [ ] `nix develop` exposes the per-slice wgpu-native paths, the ci.yml devcontainer build is green, and the BTRSmith lock resolves.
- [ ] make test passes, and BTRSmith Linux CI is green.

**Risks**

- Large archives in the nix store on the Mac's disk.

<a id="cl-p2-18"></a>

##### CL-P2-18 · W1 close-out: apply the ABI-route decision, record 10 consecutive green Windows main runs, close W1

- **Owner:** Claude · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `platforms-w1-toolchain-abi-route[decision-spec-close]`; `qualification-ci-windows-matrix[ten-green-main-runs]`
- **Depends on:** [CX-P2-26](codex.md#cx-p2-26); [CX-P2-18](codex.md#cx-p2-18); [CL-P2-10](#cl-p2-10); [CL-P2-11](#cl-p2-11); [CL-P2-12](#cl-p2-12); [CL-P2-13](#cl-p2-13); [CL-P2-14](#cl-p2-14); [CL-P2-15](#cl-p2-15)
- **Why not now:** Needs every W1 lane on main plus the route research.
- **Parallel-safe with:** CL-P2-19, CL-P2-20

**Owned paths**

- src/language/targets.toml (windows-aarch64-msvc row) and the generated modules
- tools/native_plan.py (MSVC realization if adopted)
- PLAN.md

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Apply the decision: keep or remove the provisional row. If it is adopted, pass the ABI fixture and allocator-pairing tests on that route.
2. Collect 10 consecutive green Windows main runs (x64 and ARM64, including the bootstrap) and confirm each interop feature's bootstrap.
3. Write the PLAN.md Progress entry mapping every Stage 27 exit and closing W1.

**Acceptance**

- [ ] PLAN.md lists the run ids and the decision, the generated check is clean, make test passes and make bootstrap reaches its fixed point.

**Risks**

- Flaky Windows runs reset the 10-run count.

<a id="cl-p2-19"></a>

##### CL-P2-19 · Link-plan schema 6: artifact kinds, PIC, exports, visibility, import libs (both writers, parity)

- **Owner:** Claude · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p4-library-artifacts[schema6-writers]`
- **Depends on:** stage24:platforms-p1-native-plan-toolchain → [CL-P1-11](#cl-p1-11), [CL-P1-12](#cl-p1-12); stage24:platforms-p1-cache-identity → [CL-P1-15](#cl-p1-15)
- **Why not now:** Builds on Stage 24's frozen v5 schema and cache identity.
- **Parallel-safe with:** CL-P2-16, CL-P2-17, CX-P2-22

**Owned paths**

- src/compiler/python/frontend/packages.py (plan writer)
- src/compiler/btrc/frontend/Packages.btrc
- src/language/package-manifest.md (schema 6)
- the plan goldens
- src/tests/python/test_link_plan_parity.py (v6 cases)

**Must not touch**

- tools/native_plan.py while CL-P2-15 is in flight
- docs/design/plan-reference.md

**Steps**

1. Add the artifact kinds (executable, static-library, shared-library), PIC, exported entry points, symbol visibility, install name/soname, Windows import libraries, Apple framework embedding hints and Android system libraries.
2. Make the v6 output byte-identical across frontends for 11 rows × 3 kinds. The builder still reads 1, 2, 4 and 5.

**Acceptance**

- [ ] The parity test is byte-identical, make test passes and make bootstrap reaches its fixed point.

**Risks**

- Schema churn for BTRSmith's pinned readers.

<a id="cl-p2-20"></a>

##### CL-P2-20 · Library artifact builder: per-target static/shared libraries, split-unit state identity, incremental rebuild, M11 keys

- **Owner:** Claude · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p4-library-artifacts[builder-incremental]`
- **Depends on:** [CL-P2-19](#cl-p2-19)
- **Why not now:** Follows schema 6 (CL-P2-19).
- **Parallel-safe with:** CL-P2-17, CX-P2-27

**Owned paths**

- tools/native_plan.py (hotspot)
- src/compiler/python/application/modules.py and src/compiler/btrc/pipeline/ModuleUnits.btrc (library state identity, M11 key inputs)
- src/tests/python/test_native_plan_library.py (new)

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Realize static and shared libraries per target, keeping one runtime/ARC state per library across split units.
2. Feed the SDK, availability, headers, package settings and resources into the M6a/M11 keys.
3. Make an incremental edit rebuild only the affected units (counter assertion), and validate every adapter at link.

**Acceptance**

- [ ] A BTRSmith-sized library builds for linux, windows (zig) and android (NDK) in the cloud, and an edit relinks only the changed units (counters).
- [ ] make test, make test-c11 and make bootstrap pass.

**Risks**

- Bucket-1 cache work overlaps ModuleUnits.btrc.

<a id="cl-r-48"></a>

##### CL-R-48 · BTRSmith CI extension: a KVM Android emulator job and a windows-latest dispatch job, with billed minutes per run

- **Owner:** Claude · **Group:** R · **Stage:** 28 (BTRSmith CI for bucket-3 evidence; extends CL-R-37) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `btrsmith-cross-target-build#ci`
- **Depends on:** [CL-R-37](#cl-r-37)
- **Why not now:** Extends BTRSmith's CI, which CL-R-37 creates.

> **Review change:** New (§10 F7). BTRSmith is private with no CI before `CL-R-37`, and `CL-R-37` adds only Linux and tagged macOS, yet several Codex BTRSmith packets needed emulator and Windows run ids. Its Windows job needs the owner's approval of §7 Q30, which amends D26.

**Owned paths**

- btrsmith:.github/workflows/android-emulator.yml (new; KVM, API 29 and 36 x86_64)
- btrsmith:.github/workflows/windows-dispatch.yml (new; workflow_dispatch only)
- btrsmith:docs/CI.md (billed minutes per run)

**Must not touch**

- docs/design/plan-reference.md
- btrc's public workflows (no BTRSmith token goes into btrc, §7 Q28)

**Steps**

1. Add the KVM emulator job, mirroring btrc's host-android.yml (CX-P1-05), with the SDK and AVDs cached.
2. Add the windows-latest dispatch job for the launch artifact, packaging and journey runs.
3. Measure billed minutes per run against D26 (on a private repository Windows bills at 2×, macOS at 10×), and record them in docs/CI.md. No macOS job: macOS stays tagged-release only (D26), and macOS evidence comes from MAC- packets.

**Acceptance**

- [ ] Each job is green once on a smoke run (run ids); billed minutes per run are recorded; the monthly projection fits D26's included minutes or triggers are narrowed.

#### Stage 29: Non-UI platform tracks and interop lane II (Objective-C protocols, then JNI)

<a id="cl-p2-21"></a>

##### CL-P2-21 · Interop step 6: Objective-C instantiated adapters (UIKit app/scene delegates, layerClass, error-outputs, M3 downcasts)

- **Owner:** Claude · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-i1-objc-protocol-adapters[step6-instantiated-adapters]`
- **Depends on:** [CL-P2-10](#cl-p2-10); [CL-P2-07](#cl-p2-07); stage25:platforms-p1-host-ios → [CX-P1-08](codex.md#cx-p1-08)
- **Why not now:** In the serial interop order it comes after COM; it needs Stage 25's iOS host.
- **Parallel-safe with:** CL-P2-23, CX-P2-32, CX-P2-43

**Owned paths**

- packages.py / Packages.btrc (lifetime=instantiated, scope, terminal, superclass, overrides, error-outputs)
- native_imports.py / NativeImports.btrc
- ir/nodes.py and src/compiler/btrc/ir/Model.btrc (class-reference expression node), with both emitters rendering it only
- the lowering owners (M3 downcasts, generic erasure) and the verifier
- src/tests/native/objective_c/uikit_host/ (new fixture app)
- src/tests/python/test_native_objective_c_instantiated.py (new)

**Must not touch**

- `src/stdlib/GUI/IOS/**`, `App/IOS/**` (CX-P2-36)
- docs/design/plan-reference.md

**Steps**

1. Implement step 6 of the §6 table, landing Python first and then btrc.
2. Build the UIKit test-host fixture with a process-scoped app delegate, an instance-scoped scene delegate, a UIView subclass with layerClass and AVAudioSession interruption notifications on the main queue.
3. Add NSApplicationDelegate parity tests on macOS CI, and run 100 scene connect/disconnect cycles on a GitHub macOS runner simulator as supplementary evidence.

**Acceptance**

- [ ] macos.yml is green (run id), and the simulator cycles show no leaks (run id); pinned-Xcode acceptance is in MAC-P2-04.
- [ ] make test passes and the feature bootstrap reaches its fixed point.

**Risks**

- Generated delegate classes vs an allowed startup shell (the items.json blocker) is settled by the design (generated).

<a id="cl-p2-22"></a>

##### CL-P2-22 · Lifecycle shape check: I1/A1 lifecycle owners against the UI2 host-owned loop and executor draft (read-only)

- **Owner:** Claude · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 2 agent-hours
- **PLAN items:** `platforms-i1-app-lifecycle[ui2-shape-check]`; `platforms-a1-activity-lifecycle[ui2-shape-check]`
- **Depends on:** stage32:ui-2-contract-executor (draft) → [CX-UIA-19](codex.md#cx-uia-19); stage32:ui-2-contract-lifecycle (draft) → [CX-UIA-20](codex.md#cx-uia-20)
- **Why not now:** Needs a UI2 executor and lifecycle draft (bucket 4, or early under D27) plus the open draft PRs of CX-P2-36 and CX-P2-41.
- **Parallel-safe with:** any

> **Review change:** Adds the re-check against `ui2-approved.md` and routes mismatches to `CL-UIA-22` (§10 P5).

**Owned paths**

- review comments on the CX-P2-36/41 PRs
- PLAN.md note

**Must not touch**

- `src/**` (read-only)

**Steps**

1. Have one read-only agent compare the open CX-P2-36 and CX-P2-41 drafts against the UI2 draft: the host-owned loop, IApplication.post delivery, no busy polling, the executor shape and the lifecycle event names.
2. Post the blocking findings before either lands.
3. Once ui2-approved.md exists (CL-UIA-13), re-check both lifecycle owners against it and route each mismatch to CL-UIA-22, which owns the re-check of UI2 on the real shells.

**Acceptance**

- [ ] The findings are resolved on both PRs, and PLAN.md records the check.

**Risks**

- The UI2 draft may not exist before Stage 29 unless D27 admits early UI2 drafting.

<a id="cl-p2-23"></a>

##### CL-P2-23 · JavaClassReader v2: nullability annotations, ACC_NATIVE RegisterNatives targets, nested classes

- **Owner:** Claude · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-a1-checked-jni[reader-v2]`
- **Depends on:** [CL-P2-08](#cl-p2-08)
- **Why not now:** Follows reader v1.
- **Parallel-safe with:** CL-P2-21, CX-P2-36

**Owned paths**

- tools/JavaClassReader.c
- src/tests/python/test_java_class_reader.py
- src/tests/native/java/

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Read the androidx and javax NonNull/Nullable annotations (RuntimeInvisible), mark ACC_NATIVE targets, give nested classes their binary names and bump the reader version.
2. Add goldens over android.jar from Stage 23 and the fixture classes.

**Acceptance**

- [ ] The goldens pass, and both codecs round-trip; make test passes.

**Risks**

- Annotation coverage in android.jar.

<a id="cl-p2-24"></a>

##### CL-P2-24 · Interop step 7: JNI entry and callbacks (RegisterNatives, failure=throw, JavaWeak\<T>, array spans, Looper executor)

- **Owner:** Claude · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-a1-checked-jni[step7-entry-callbacks]`
- **Depends on:** [CL-P2-09](#cl-p2-09); [CL-P2-21](#cl-p2-21); [CL-P2-23](#cl-p2-23); stage25:platforms-p1-host-android → [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** In the serial interop order it comes after the Objective-C step 6; it needs reader v2 and the Android host.
- **Parallel-safe with:** CX-P2-37, CX-P2-38

**Owned paths**

- packages.py / Packages.btrc (failure="throw", executor="main" for Java)
- native_imports.py / NativeImports.btrc
- the lowering owners (Java→btrc thunks through M2 and the caller boundary) and the verifier
- src/stdlib/Java/ (JavaWeak\<T>, array spans, the application ClassLoader, the Looper executor)
- src/tests/python/test_native_jni_entry.py (new)

**Must not touch**

- `src/stdlib/App/Android/**`, `GUI/Android/**` (CX-P2-41)
- docs/design/plan-reference.md

**Steps**

1. Implement step 7 of the §6 table.
2. On the emulator: Java calling btrc and btrc calling back, nested Java→btrc→Java→btrc, weak refs clearing under System.gc(), and 100 activity lifecycle cycles with no leaked global refs. Use the Stage 25 NativeActivity host APK on a GitHub ubuntu KVM runner.
3. The host JVM covers the non-ART cases.

**Acceptance**

- [ ] The emulator and host-JVM tests pass through both compilers (run ids).
- [ ] make test passes and the feature bootstrap reaches its fixed point; the physical device is recorded in MAC-P2-05.

**Risks**

- The ClassLoader on non-main threads.

<a id="cl-p2-25"></a>

##### CL-P2-25 · BTRSmith durable resource tokens: library roots, non-seekable scanning, container catalog, atomic durable state

- **Owner:** Claude · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-storage-resources[abstraction]`
- **Depends on:** [CX-P2-37](codex.md#cx-p2-37); [CX-P2-42](codex.md#cx-p2-42); [CX-P2-05](codex.md#cx-p2-05)
- **Why not now:** Needs the I1, A1 and Windows storage owners.
- **Parallel-safe with:** CL-P2-26

**Owned paths**

- BTRSmith `src/backend/catalog/*`, `src/backend/state/*`
- BTRSmith src/application/runtime/SettingsSessionOwner.btrc, `AsyncLibraryScan*.btrc`
- BTRSmith `src/domain/protocol/*Settings*.btrc`

**Must not touch**

- BTRSmith tests/\<platform>/ storage fixtures (CX-P2-46)

**Steps**

1. Replace the POSIX-path roots (SettingsSessionOwner.btrc:172, GUIApplication.btrc:144, FileSystemLibrarySourceEnumerator) with resource tokens: bookmarks, SAF URIs or paths.
2. Scan through a non-seekable enumerator, write DurableUserState atomically and migrate the schema without loss.

**Acceptance**

- [ ] BTRSmith Linux CI is green, and the migration test passes from the current schema; per-platform fixtures follow in CX-P2-46.

**Risks**

- The ApplicationSession hotspot.

<a id="cl-p2-26"></a>

##### CL-P2-26 · BTRSmith audio policy for route-based and mobile sessions and Windows endpoints

- **Owner:** Claude · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-audio-adaptation[policy]`
- **Depends on:** [CX-P2-32](codex.md#cx-p2-32); [CX-P2-38](codex.md#cx-p2-38); [CX-P2-43](codex.md#cx-p2-43)
- **Why not now:** Needs the WASAPI, iOS and AAudio providers.
- **Parallel-safe with:** CL-P2-25

**Owned paths**

- BTRSmith src/application/runtime/NativeAudioDeviceProvider.btrc, AudioSession.btrc, NativeAudioSessionOwner.btrc
- BTRSmith `src/domain/protocol/AudioDevice*.btrc`
- BTRSmith src/frontend/settings/AudioSettingsForm.btrc
- BTRSmith make/CoreAudio.mk

**Must not touch**

- BTRSmith `tests/*/AudioSetupFailure*` (CX-P2-47)

**Steps**

1. Handle record-permission denial, pause on interruption with an explicit resume (no auto-resumed monitoring), negotiated rate and buffer reporting and the background policy, and remove the macOS wording.
2. Keep SettingsInputTest, Tuner and PlayerAudioComposition bounded.

**Acceptance**

- [ ] BTRSmith Linux CI is green, and the scripted interruption regressions pass on the fault fixtures.

**Risks**

- The single product-policy owner is serial.

<a id="cl-p2-28"></a>

##### CL-P2-28 · GPU runtime platform branches: the _WIN32, iOS and Android paths of src/runtime/gpu, on request

- **Owner:** Claude · **Group:** P2 · **Stage:** Stage 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-w2-gpu-image-font#runtime`; `platforms-i2-gpu#runtime`; `platforms-a2-gpu#runtime`
- **Depends on:** [CL-P2-17](#cl-p2-17); [CL-P1-15](#cl-p1-15)
- **Why not now:** Needs the cross-built GPU dependencies (CL-P2-17) and Stage 24's target rows.

> **Review change:** New (§10 C8). `src/runtime/gpu` exports the `btrc_gpu_*` ABI that `hosted_abi.toml` declares and both compilers' GPU lowering calls; three Codex packets also claimed `#ifdef` regions of the same files.

**Owned paths**

- `src/runtime/gpu/**` (btrc_gpu.c, btrc_gpu_async.c and their headers)
- Makefile `gpu` target (hotspot)
- src/language/hosted_abi.toml `btrc_gpu_*` rows, only if a signature must change (paired in both compilers)

**Must not touch**

- docs/design/plan-reference.md
- src/stdlib/GPU/{Windows,IOS,Android}/ (Codex)

**Steps**

1. Take REQUEST(CL-P2-28) blocks from CX-P2-33 (Windows), CX-P2-39 (iOS) and CX-P2-44 (Android); land one platform per commit. This is a rolling packet: each platform's commit satisfies that platform's packet.
2. Keep every exported `btrc_gpu_*` signature. A signature change is paired in both compilers' GPU lowering and hosted_abi.toml, with a D14 record if the runtime source is frozen.
3. Keep the @gpu suites green on Linux and macOS (WGSL byte-identical), and run the platform's GPU suite on its lane.

**Acceptance**

- [ ] Each requested platform branch is merged with its lane's GPU suite green (run ids); Linux and macOS @gpu suites unchanged; `make gpu` builds on every host.

#### Stage 30: UI0 catalog, journeys and evidence hosts

<a id="cl-uia-01"></a>

##### CL-UIA-01 · Record D27 and the Codex lane protocol in PLAN.md and AGENTS.md

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 30 entry (cross-cutting coordination; no PLAN item) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 4.5 agent-hours
- **PLAN items:** —
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-02, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Writer note:** Step 1 records §2's D27 row word for word; that row merges all six analysts' D27 proposals, so it replaces this group's three lists. Step 3's commit naming is superseded by §3.5: `fragment:` commits carry hand-written changes Claude re-applies, and `derived:` commits carry regenerated files Claude drops.

> **Writer note:** Absorbs `CL-UIB-01` (§9 item 2). Estimate raised from 2.5 to 3.5 h. It also lands this doc, which makes it **Gate 0** (§5.4).

> **Review change:** Step 3 rewritten: the old text dropped `btrc.toml` edits and skip rules as derived files, used a `compiler request:` syntax instead of `REQUEST(…)`, and capped Codex branches rather than code branches (§10 C3).

> **Review change:** Gate 0 is this packet alone; `CL-UIA-02` lands in Claude's next batch and the first Codex batch (§10 C11).

> **Review change:** AGENTS.md is 37,433 bytes; Codex's documented default `project_doc_max_bytes` is 32 KiB, which would cut it at line 664 and drop the Makefile targets, the Hard Rules and an appended Codex section. Moving the two measurement sections frees only about 6 KB, so the Python file tree moves too (§10 F4).

> **Writer note:** Step 9 is superseded: Gate 0 recorded D27 as in force on 2026-10-03, because the owner asked for the split and started Codex (§2). The owner approved Stage 24's early start on 2026-10-03 (§7 Q2).

**Owned paths**

- PLAN.md (Decisions table, Standing approvals, Stage 30 exit wording, Codex rules under 'Where sub-agents help', Progress log)
- AGENTS.md (new 'Second agent: Codex' section only)
- .github/PULL_REQUEST_TEMPLATE/codex-packet.md (new)
- WORKSTREAMS.md (new, repository root: this document)
- docs/design/compile-performance.md (the two moved AGENTS.md sections)
- src/tests/python/test_python_compiler_structure.py (INVENTORY_DOCUMENTS only)
- tools/perf.py (one comment)

**Must not touch**

- docs/design/plan-reference.md
- `src/**`
- `docs/design/native-ui-*.md`
- `.github/workflows/**`

**Steps**

1. Add a D27 row to the Decisions table. It holds the three lists from this group's summary: starts now; may start once its in-stage dependencies land; stays gated.
2. Add a Standing-approvals row. Codex contract drafts are approved by Claude's two feasibility reviewers plus one parity reviewer, with no blocking finding left open, and Claude records the approval. Codex never pushes main, merges a PR, edits plan-reference.md, or claims Mac or device evidence.
3. Add a 'Codex lanes' table under 'Where sub-agents help'. Branches start with codex/ and claims are keyed by the `[CX-…]` PR title and the `Packet:` line. A draft PR to main exists only for CI, and each packet owns an explicit list of paths. A branch ends with up to two commits: `fragment: <what>` carries hand-written changes to integrator-owned data (btrc.toml exports and native rows, expected-skip rules, denominators, Makefile lines and ci/tiers.toml), which Claude re-applies; `derived: regenerate` carries btrc.lock, btrc.symbols and the LSP catalog, which Claude drops and regenerates. A compiler, spec, runtime or hotspot change goes in the PR body as a `REQUEST(<target>)` block (§3.6). The batch cap is as in D27.
4. Amend Stage 30's exit. The 19/24/162 figures are the frozen 2026-09-21 release; on 8b73c79 the source has 20 files, 25 interfaces and 152 + 26 = 178 declarations, and the drift test derives its counts against CX-UIA-02's re-frozen release. Note that D23's 'UI4-UI8' keeps the UI2/UI3 Linux work on the SDL provider.
5. Write the AGENTS.md Codex section (≤3 KB) directly after the title, so it is inside Codex's read limit. It says that the host-capacity, lock, hub, disk and MEMORY.md rules do not apply to Codex, and points to WORKSTREAMS.md §3. Move 'Measuring a compile' and 'Performance changes already measured and rejected' (about 6 KB) into docs/design/compile-performance.md, and the Python 'File Structure' tree (about 5 KB, already duplicated in docs/design/compiler-structure.md) out of AGENTS.md, dropping its AGENTS.md entry from test_python_compiler_structure.py's INVENTORY_DOCUMENTS and updating tools/perf.py's comment, so AGENTS.md is at most 30,000 bytes.
6. Add a PR template for the required report: commits, every command run with pass/skip/fail counts, CI run ids, catalog rows changed, deferrals and compiler requests.
7. Also carry `CL-UIB-01`'s steps 3 and 4: annotate PLAN.md's Stage 34–37 parallelization bullets with each lane's owner, the `fragment:`/`derived:` rule (§3.5) and the rule that an in-flight track owns its provider directory; and list in AGENTS.md the paths Codex never edits (§3.3.1).
8. Commit this document as `WORKSTREAMS.md` at the repository root and link it from AGENTS.md's Codex section and from PLAN.md (Decisions intro and 'Where sub-agents help'). This commit is Gate 0.
9. Record D27 as `**proposed**` with the owner's approval pending (§2), and record the §7 Q35/Q36 catalog decision (PR #21's amendment model and layout).

**Acceptance**

- [ ] git diff --check is clean. python -m pytest src/tests/python/test_device_registry.py src/tests/python/test_platform_inventory.py -q passes; both tests parse PLAN.md item ids.
- [ ] make lint and make format-check pass.
- [ ] The change lands on main in the integrator's ordinary batch, and the ci.yml run id is recorded in the Progress log.
- [ ] `WORKSTREAMS.md` is on `main` and linked from AGENTS.md and PLAN.md; D27's row matches §2 of this doc word for word
- [ ] `test "$(wc -c < AGENTS.md)" -le 30000` passes, and test_python_compiler_structure.py passes against docs/design/compiler-structure.md

**Risks**

- The owner may strike D27 clauses. Codex start-now packets should begin only after this row lands.
- PLAN.md and AGENTS.md are single-writer hotspots.
- Confirm that Codex's GitHub app can push branches and open draft PRs on schiffy91/btrc before launching any CX lane.

<a id="cl-uia-02"></a>

##### CL-UIA-02 · CI support for Codex lanes: the workflow-class contract policy, concurrency groups, a PR scope job and a focused native-GUI dispatch

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 30 (UI0 enabler) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-0-focused-gate#ci-dispatch`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-03, CX-UIA-01, CX-UIA-02, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Review change:** Rewritten (§10 C1, F1, F8). `test_ci_workflow_contracts.py` requires every workflow's `on:` block to be exactly push/PR/dispatch and the pytest-job set to be exactly three jobs, so lane workflows with paths filters, dispatch-only workflows and `inputs:` failed every unit shard; this packet now owns that policy. Measured CI capacity (2026-10-03: one macos.yml run is 9 jobs and about 236 runner-minutes; at most 5 concurrent macOS jobs) needs the scope job. Hosted macOS runners do have a paravirtual GPU adapter (run 37084025400).

**Owned paths**

- .github/workflows/ci.yml
- .github/workflows/macos.yml
- .github/workflows/windows.yml
- src/tests/python/test_ci_workflow_contracts.py (trigger and skip-report contracts)

**Must not touch**

- Makefile (CX-UIA-01's fragment adds the test-native-gui target)
- flake.nix
- `src/**` except src/tests/python/test_ci_workflow_contracts.py
- docs/design/plan-reference.md

**Steps**

1. Concurrency: pull_request runs use `group: ${{ github.workflow }}-${{ github.head_ref }}` with cancel-in-progress: true; pushes to main use `group: ${{ github.workflow }}-main` with cancel-in-progress: false, so a newer pending main run replaces an older pending one. Record the covering run id per batch.
2. Add a workflow_dispatch input 'focus' (full or native-gui) to ci.yml and macos.yml. With native-gui, one job runs: 'make test-native-gui' on Linux inside the devcontainer under tools/virtual-display.sh, or on macos-15 after the existing header-reader build step. That job uploads build/skip-report.json and the junit XML.
3. Add a first `scope` job to ci.yml and macos.yml that classifies a pull request's diff: Markdown-only changes outside the test-read set (PLAN.md, AGENTS.md, README.md files and docs/design/{native-ui-parity, platform-parity, native-ui-api-inventory, compiler-structure, btrsmith-rename-table-w2, plan-reference}.md) run only lint, format-check and generated-check; other `codex/*` PRs run macOS native-bundle (arm64) plus the native-GUI job; the full macOS matrix runs only when the diff touches `src/compiler/**`, `src/language/**`, `src/runtime/**`, `tools/compiler_codegen/**` or a compiler-import stdlib module, when the PR carries the label `ci:full`, and on main pushes.
4. Replace the exact-trigger test in test_ci_workflow_contracts.py with a per-class policy: the core three workflows trigger on push/PR to main plus workflow_dispatch, which may take inputs; lane workflows (`host-*.yml`, `windows-*.yml`, ios.yml, android.yml) trigger on push [main], pull_request [main] with a paths filter that includes the workflow file, and workflow_dispatch, and may add workflow_call; a named dispatch-only list (windows-msvc-probe.yml, acceptance-x86.yml); release.yml on tags. Derive the skip-report expectation instead of hard-coding it: every job that runs pytest uploads `skip-report-<workflow-stem>-<job>` as its last step.
5. Land in two commits if that is faster: the contract policy, concurrency and scope job first (Claude's next batch after Gate 0, so the lane-workflow packets can go green), then the focus dispatch with CX-UIA-01, which provides the make target.

**Acceptance**

- [ ] 'gh workflow run ci.yml --ref \<branch> -f focus=native-gui' and the same for macos.yml each run only the focused job and upload a skip report (run ids recorded).
- [ ] A second push to the same PR cancels the first run; a newer main push replaces a pending older one (run ids).
- [ ] A Markdown-only PR push schedules at most 4 jobs; a GUI-only `codex/*` push schedules at most 3 macOS jobs (run ids).
- [ ] test_ci_workflow_contracts.py passes with the class policy; every workflow file parses with yaml.safe_load.

**Risks**

- Pushing workflow edits needs a token with the workflow scope; the HTTPS gh token lacked it in Stage 2.
- Hosted macos-15 exposes a paravirtual Metal adapter: GPU correctness rows run there; real-GPU timing, pacing and idle-CPU rows stay owner-tier.

<a id="cl-uia-03"></a>

##### CL-UIA-03 · ui-0-product-journeys + btrsmith-ui0-callers: inventory BTRSmith's runtime GUI/UI callers (private repo)

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-0-product-journeys`; `btrsmith-ui0-callers`
- **Depends on:** [CX-UIA-02](codex.md#cx-uia-02) (ready: PR #21's catalog ids)
- **Why not now:** Maps call sites to catalog operation ids, so it follows the catalog schema (PLAN Stage 30: serial first).
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CX-UIA-01, CX-UIA-02, CX-UIA-03, CX-UIA-04, CX-UIA-05, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13

> **Writer note:** BTRSmith `docs/NativePlatformPlan.md` is shared append-only with `CX-P1-01` (§9 item 11).

> **Review change:** Waits for the catalog schema (`CX-UIA-02`, PR #21) to be ready (§10 P13).

**Owned paths**

- BTRSmith: docs/ui/caller-inventory.toml (new)
- BTRSmith: tools/ui_caller_counts.py (new)
- BTRSmith: docs/NativePlatformPlan.md (UI0 cross-link section only)

**Must not touch**

- btrc repository (public): no BTRSmith paths, line numbers or excerpts
- BTRSmith `src/**` (read-only here)
- docs/design/plan-reference.md

**Steps**

1. Pin the audited BTRSmith revision in the inventory header.
2. Run 5 read-only mappers: Library adapters; Settings adapters and forms; Player adapters with platform/gpu; runtime and inspection; frontend `Ui*` trees. They map every Library.GUI and Library.UI call site to catalog operation ids, N/E ids and the five product slices.
3. Record each workaround a contract will retire: TextBinding/SelectionBinding nextChange polling; GUIApplication's periodic GUI.postAfter loop and GUI.post; the synchronous GUI.chooseDirectory; ApplicationView's 480-4096 × 240-4096 admission.
4. Also record: the AlbumGrid pool; SF Symbols missing from LinuxSymbols (tuningfork, quote.bubble); setFont above 20 pt; and Library.UI's three roles (musical raster, screen tree/inspection/agent, UIEvent command currency).
5. tools/ui_caller_counts.py reproduces every count from source and cross-checks that each referenced operation id exists in btrc's catalog, or in CX-UIA-02's branch.

**Acceptance**

- [ ] In BTRSmith, 'python3 tools/ui_caller_counts.py --check' reproduces every count with 0 unmapped GUI or UI call sites.
- [ ] Each of the five slices lists its operations, its E-cases and the workaround it retires.
- [ ] The btrc diff is empty. The BTRSmith commit is pushed per D4.

**Risks**

- BTRSmith has drifted since the 2026-09-14 review, and Codex has no confirmed access to it, so this stays with Claude.
- A re-freeze in CX-UIA-02 or CX-UIA-05 means rerunning the cross-check.
- btrsmith-p0-inventory is still pending. Reuse its journey ids if it lands first.

<a id="cl-uia-04"></a>

##### CL-UIA-04 · qualification-p5-journey-catalog: freeze BTRSmith product journeys per platform and frontend

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `qualification-p5-journey-catalog`
- **Depends on:** [CL-UIA-03](#cl-uia-03); btrsmith-p0-inventory → [CX-P1-01](codex.md#cx-p1-01); platforms-p0-adaptations → [CX-P1-02](codex.md#cx-p1-02)
- **Why not now:** Needs CL-UIA-03's caller inventory and the pending btrsmith-p0-inventory journey ids. OS-restricted rows also need the owner's sign-off on platform-adaptations.md and its ten questions.
- **Parallel-safe with:** CX-UIA-07, CX-UIA-09, CX-UIA-10, CX-UIA-11

**Owned paths**

- BTRSmith: docs/qualification/journeys.toml (new)
- BTRSmith: tests/qualification/JourneyCatalogCheck (new verifier)

**Must not touch**

- btrc repository except the Stage 30 Progress log line (release name and digest only)
- docs/design/plan-reference.md

**Steps**

1. Draft the catalog from docs/product/PRD.md, issue #15 milestones 1-6, the make/Help.mk targets, tests/macos/PortableCoverage.md and make/AgentSurfaceAcceptance.mk. Each row is a journey × 5 platforms × 2 frontends with an evidence class, an owning test and an adaptation; D25 keeps btrsmithctl/MCP desktop-only.
2. Map the existing checks: ApplicationJourney, PlayerPan, SettingsSession, LibrarySession, durable-user-state-check, macos-app-bundle-smoke and linux-install-smoke.
3. Have one independent read-only auditor check the draft against the PRD and issue #15, and close every omission it finds.
4. Freeze the journey denominator in BTRSmith, and record only its release name and digest in btrc.

**Acceptance**

- [ ] The BTRSmith verifier passes with every slot classified.
- [ ] The auditor reports 0 open omissions, and every OS-restricted row cites the owner's adaptation approval.

**Risks**

- The owner's adaptation answers may reclassify journeys after the freeze.
- Linux, Windows and accessibility are post-MVP in the PRD (D25); those slots need explicit adapted or deferred states.

<a id="cl-uia-05"></a>

##### CL-UIA-05 · Stage 30 integration batches and exit gate

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** —
- **Depends on:** [CL-UIA-01](#cl-uia-01); [CL-UIA-02](#cl-uia-02); [CL-UIA-03](#cl-uia-03); [CX-UIA-01](codex.md#cx-uia-01); [CX-UIA-02](codex.md#cx-uia-02); [CX-UIA-03](codex.md#cx-uia-03); [CX-UIA-04](codex.md#cx-uia-04); [CX-UIA-05](codex.md#cx-uia-05); [CX-UIA-06](codex.md#cx-uia-06); [CX-UIA-07](codex.md#cx-uia-07); [CL-UIA-21](#cl-uia-21)
- **Why not now:** Integrates the Stage 30 packets as they finish. None has finished on 8b73c79.
- **Parallel-safe with:** CX-UIA-09, CX-UIA-10, CX-UIA-12, CX-UIA-13

> **Review change:** Step 1 corrected (`derived:` is dropped, `fragment:` re-applied; `08` is now `CL-UIA-21`'s lane), and it wires the catalog into the qualification report, which nothing else edits before `CL-R-45` (§10 C3, C14).

**Owned paths**

- integration branches `integ/ui0-*` off main-kn9jxh
- PLAN.md (Stage 30 Progress log)
- src/stdlib/btrc.lock, src/stdlib/btrc.symbols, src/devex/lsp/catalog/generated.py, `src/tests/fixtures/expected-skips/*.json` (regenerated or applied from fragments)

**Must not touch**

- docs/design/plan-reference.md
- never force-push a `codex/*` branch; rebase only on the integration branch

**Steps**

1. Merge the Codex branches in this order, at most two code branches per batch: CX-UIA-01 with CL-UIA-02's focus commit, then CL-UIA-21's lane, CX-UIA-02 (PR #21), CX-UIA-06, 03, 04, 05 and 07. Drop each `derived:` commit and re-apply each `fragment:` commit.
2. Regenerate the derived files, then run generated-check, lint, format-check and git diff --check.
3. Gate stdlib and tests batches on the focused suites plus a sharded make test across cloud sessions. The flake.nix batch also rebuilds the devcontainer and runs the bootstrap. Then push main fast-forward and read all three workflows.
4. Record the Stage 30 progress: derived counts, slot totals, Linux GUI runs under Wayland and X11, and run ids. Stage 30 stays open until CL-UIA-04 and MAC-UIA-01 land.
5. Wire the UI catalog (tools/qualification/ui_catalog.py over docs/design/native-ui-catalog.toml and its shards) into tools/qualification/report.py and cli.py, so make qualification-report renders it.

**Acceptance**

- [ ] Each batch gate is green, and CI on main is green in ci.yml, macos.yml and windows.yml (run ids).
- [ ] Stage 30 exit evidence is recorded: derived drift counts with the dummy-method failure, every operation and case slot classified, BTRSmith callers 100% mapped, and Linux GUI tests run under both Wayland and X11.

**Risks**

- Each batch competes with C-track batches for gate time; D27 caps Codex branches at two per batch.
- expected-skips JSON conflicts between fragments are resolved by hand.

<a id="cl-uia-21"></a>

##### CL-UIA-21 · tooling-linux-headless-gui: weston headless, Xvfb, lavapipe, GTK4 and AT-SPI in the dev shell and container

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 7 agent-hours
- **PLAN items:** `tooling-linux-headless-gui`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-02, CX-UIA-06, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Writer note:** Formerly `CX-UIA-08`, reassigned to Claude (§9 item 1). Its owned paths (`flake.nix`, `nix/*`, `src/tests/runner_capabilities.py`) are Claude-only hotspots (§3.3.1). Claude runs it as a lane branch: read "draft PR" as `gh workflow run ci.yml --ref <lane>`, and "PR-body report" as the lane report. Hold `flake.nix` before `CL-P1-02` (§3.3.2).

**Owned paths**

- flake.nix (Linux-only GUI packages and environment variables; no input or lock change)
- nix/containerfile.nix
- nix/devcontainer.nix
- tools/virtual-display.sh
- tools/ui/headless-session.sh (new)
- src/tests/runner_capabilities.py (display and AT-SPI capability functions only)
- tools/linux-ci.sh (session environment only)

**Must not touch**

- flake.lock
- Makefile
- `src/compiler/**`
- `src/language/**`
- `src/runtime/**`
- `.github/workflows/**`
- docs/design/plan-reference.md
- PLAN.md

**Steps**

1. Add Linux-only packages: weston (headless backend), gtk4 and gtk4.dev, glib.dev, at-spi2-core, a session dbus-daemon, and python3 with pyatspi and PyGObject for tree dumps. Confirm the pinned sdl3 has its Wayland backend; keep lavapipe and xvfb-run.
2. Add tools/ui/headless-session.sh --x11|--wayland -- \<cmd>. It wraps the command in dbus-run-session and starts the AT-SPI bus.
3. It then starts either Xvfb -noreset or weston --backend=headless with its own socket, and exports DISPLAY or WAYLAND_DISPLAY plus SDL_VIDEODRIVER, GDK_BACKEND and the lavapipe ICD.
4. After the command it tears the session down. tools/virtual-display.sh delegates to it in X11 mode, so CI behaviour does not change.
5. Add capability gates 'native-display-wayland' and 'native-atspi' next to linux_display_error.
6. Mirror the packages into the containerfile and the devcontainer, so ci.yml's image gets them.

**Acceptance**

- [ ] In the cloud, 'tools/ui/headless-session.sh --x11 -- python -m pytest src/tests/python/test_native_linux_providers.py -k gui -q' and the --wayland variant both execute (rather than skip) the GUI controls, shutdown and GPU-reparent cases through python and selfhost.
- [ ] A GTK4 hello-window C program renders under both sessions with an AT-SPI JSON dump, and a lavapipe GPU-view capture is produced (artifacts listed).
- [ ] On the draft PR, ci.yml is green including the devcontainer image build (run id), and the image-size delta is reported. The PR-body report follows the protocol.

**Risks**

- flake.nix and `nix/*` are hotspots: no other packet may edit them while this one is open.
- GTK4 and AT-SPI enlarge the nix closure and the CI image.
- wgpu-native's Vulkan WSI may not present on weston headless with lavapipe. If so, record it and keep X11 as the gating session.
- The Determinate nix GC hazard means every run needs a gcroot profile.

#### Stage 31: UI1 shells on all five platforms and the toolkit decision

<a id="cl-uia-06"></a>

##### CL-UIA-06 · ui-1-linux-gobject-binding (Tier A, part 1): sinking, subtype casts and the GLib main-context executor in both compilers

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-1-linux-gobject-binding`
- **Depends on:** [CL-P2-24](#cl-p2-24); [CL-UIA-21](#cl-uia-21)
- **Why not now:** GObject is interop step 8 (native-interop-ownership.md §6). It follows step 7 (CL-P2-24) on the single interop lane, and glib.dev reaches the dev shell with CL-UIA-21.
- **Parallel-safe with:** CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Review change:** Depends on `CL-P2-24` (interop step 7) instead of step 2: the approved plan orders GObject as step 8, and the interop lane has one owner for the ASDL, both importers and lowering (§10 P4).

**Owned paths**

- src/compiler/python/frontend/packages.py (PackageManifestValidator, NativeResourceBinding)
- src/compiler/python/frontend/native_imports.py (NativeDeclarationImporter)
- src/compiler/python/analyzer/ownership.py and analyzer/expressions.py (the spawn-capture rule)
- src/compiler/python/ir/lowering/functions.py
- src/compiler/python/ir/verifier.py (IRVerifier)
- src/compiler/btrc/frontend/Packages.btrc (FePackageManifestParser, FeNativeBinding)
- src/compiler/btrc/frontend/NativeImports.btrc (FeNativeDeclarationImporter)
- src/compiler/btrc/analyzer/ownership/
- src/compiler/btrc/ir/lowering/Declarations.btrc (DeclarationLowerer)
- src/compiler/btrc/ir/optimization/Cleanup.btrc
- src/stdlib/GUI/Linux/GLibMainContext.btrc (new)
- src/tests/native/gobject/ (new)
- src/tests/python/test_native_gobject.py (new)
- docs/design/native-interop.md (GObject section)

**Must not touch**

- src/language/native_abi.asdl (GObject needs no schema change)
- `src/runtime/c/**` (no new asset)
- `src/stdlib/GUI/Linux/*` other than GLibMainContext.btrc (Codex lanes)
- docs/design/plan-reference.md

**Steps**

1. Add the manifest keys, Python first and then btrc, one commit per construct: the resource key 'sink'; the 'sunk-results' modes floating-or-none and floating-or-full; type-relation=subtype; parent; implements; and executor/release-executor main-context.
2. Implement every GObject rejection in design section 5 with identical text in both compilers.
3. Lower the sink adapters so each mode yields exactly one claim; owned-results are never sunk. Downcasts go through g_type_check_instance_is_a with the type-tag; upcasts go through parent/implements, with hook-identity and Class-struct first-field checks.
4. Add GLibMainContext. It captures the loop thread only on an explicit bind() or run() on that thread. main-context adapters compare threads with pthread_equal and abort before the bind. Capturing such a resource in spawn is a compile-time error in both analyzers.
5. Tier A fixtures 1-3: a floating sink ends non-floating at count 1 with one finalize; g_object_new on a non-floating type is adopted at count 1; transfer-full g_simple_action_new up- and down-casts keep exact counts.

**Acceptance**

- [ ] python -m pytest src/tests/python/test_native_gobject.py -q passes both frontends at -O2 and under ASan/UBSan.
- [ ] Every GObject diagnostic has identical text and position in both compilers.
- [ ] The self-host transpiles of BtrccMain, cli/WindowsMain and cli/MacOSMain have zero warnings. generated-check, lint and format-check pass, and the landing batch reaches the test_bootstrap.py fixed point.

**Risks**

- The GLib owner file sits in Codex's GUI/Linux tree. Codex must not edit it until this lands.
- ir/lowering and the verifier are hotspots shared with the C track; land between C batches.

<a id="cl-uia-07"></a>

##### CL-UIA-07 · ui-1-linux-gobject-binding (Tier A, part 2): signals as stored callbacks in both compilers

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-1-linux-gobject-binding#signals`
- **Depends on:** [CL-UIA-06](#cl-uia-06)
- **Why not now:** Needs CL-UIA-06, which itself waits for Stage 27 steps 1-2.
- **Parallel-safe with:** CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

**Owned paths**

- the CL-UIA-06 compiler files (sequential owner)
- src/tests/native/gobject/
- src/tests/python/test_native_gobject.py

**Must not touch**

- src/language/native_abi.asdl
- `src/runtime/c/**`
- `src/stdlib/GUI/Linux/*` other than GLibMainContext.btrc
- docs/design/plan-reference.md

**Steps**

1. Accept the stored C-callback form on g_signal_connect_data's handler, with the existing keys plus signal, destroy-notify, slot-check and signature/signature-typedef. Lift the stored-callback rejection for this form only.
2. The signature always comes from a header type: a class field, or a typedef in the package's own header. GCallback erasure is the single cast inside the adapter.
3. The context's external claim is passed as data and released exactly once by the generated GClosureNotify, and the source is held as a GWeakRef.
4. A g_signal_parse_name failure raises a recoverable exception before publication. A g_signal_query arity or return mismatch is terminal, and so is handler id 0: release the claim, then abort.
5. Cancellation reads the weak ref, disconnects if the handler is still connected, then releases.
6. Apply verifier rule 3 to GObject R3 entries (executor check, receiver retain, holder pin) in IRVerifier and in the btrc Cleanup validator.
7. Tier A fixtures 4-7: a receiver cycle broken by scope.cancel() (notify 1, finalize 1); a weak source finalized while its scope lives; a bad signal name throws without leaking; a handler that cancels itself.

**Acceptance**

- [ ] All 7 Tier A fixtures pass both frontends at -O2 and under ASan/UBSan.
- [ ] test_bootstrap.py stays byte-stable, and the self-host transpiles have zero warnings. generated-check, lint and format-check pass, and make test passes in its own Claude batch.

**Risks**

- A wrong transfer declaration is a trusted promise that only exact counts catch.
- The weak-ref and notify ordering must hold under ASan.

<a id="cl-uia-08"></a>

##### CL-UIA-08 · ui-1-linux-gobject-binding (Tier B): gtk_adjustment_new, class-field signatures and gtk_window_new sinking

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-1-linux-gobject-binding#tier-b`
- **Depends on:** [CL-UIA-07](#cl-uia-07); [CL-UIA-21](#cl-uia-21)
- **Why not now:** Needs Tier A (CL-UIA-07) and gtk4.dev plus headless sessions (CL-UIA-21).
- **Parallel-safe with:** CX-UIA-21, CX-UIA-22, CX-UIA-23

**Owned paths**

- src/tests/native/gobject/tierb/ (new)
- src/tests/python/test_native_gobject.py (Tier B cases)
- CL-UIA-06's compiler files, only to fix defects Tier B exposes

**Must not touch**

- src/language/native_abi.asdl
- `src/stdlib/GUI/Linux/*` other than GLibMainContext.btrc
- docs/design/plan-reference.md

**Steps**

1. Bind gtk_adjustment_new with a value_changed handler typed from 'class-field:GtkAdjustmentClass.value_changed'.
2. Sink gtk_window_new with floating-or-none, and shut it down by close-request -> scope.cancel() -> gtk_window_destroy.
3. Run under tools/ui/headless-session.sh on both Wayland and X11, because gtk_init needs a display.

**Acceptance**

- [ ] Tier B passes both frontends, plain and ASan/UBSan, under both sessions.
- [ ] If a compiler file changed, the bootstrap stays byte-stable and the transpiles have zero warnings.
- [ ] Its landing is recorded as the gate that opens CX-UIA-14.

**Risks**

- gtk_init under weston headless may need extra session setup; X11 is the fallback.

<a id="cl-uia-09"></a>

##### CL-UIA-09 · ui-1-feasibility-review: UI1 checkpoint for macOS and Linux SDL (unlocks UI2)

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `ui-1-feasibility-review`
- **Depends on:** [CX-UIA-10](codex.md#cx-uia-10); [CX-UIA-11](codex.md#cx-uia-11)
- **Why not now:** Needs the macOS proof (CX-UIA-10) and the Linux SDL baseline (CX-UIA-11).
- **Parallel-safe with:** CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-06, CL-UIA-07

**Owned paths**

- docs/design/ui-contracts/ui1-feasibility.md (new)
- PLAN.md (Stage 31 progress and decision record)

**Must not touch**

- `src/**`
- docs/design/native-ui-parity.md (Codex's CX-UIA-07)
- docs/design/plan-reference.md

**Steps**

1. Run a read-only review workflow over the CX-UIA-10 and CX-UIA-11 evidence, plus MAC-UIA-02 when it exists: 2 feasibility reviewers and 1 parity reviewer.
2. Record that macOS AppKit and Linux on the shipping SDL provider proceed to UI2, since D23 scopes GTK4 to UI4-UI8. Record Windows, iOS and Android as blocked, with their PLAN item ids. Confirm D24's host-owned loop for mobile.
3. Leave Win32 versus WinUI and Android Views versus GameActivity open until those shells report; CL-UIA-22 decides them.

**Acceptance**

- [ ] The decision record has its review files and 0 unresolved blocking findings, and PLAN.md's Stage 31 entry is updated.
- [ ] The catalog marks macOS and Linux-SDL as eligible for UI2.

**Risks**

- The owner may read D23 as gating UI2 Linux on the toolkit decision (see the open questions).

<a id="cl-uia-10"></a>

##### CL-UIA-10 · D23 toolkit decision and Stage 31 close

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `ui-1-feasibility-review#d23-toolkit`
- **Depends on:** [CX-UIA-14](codex.md#cx-uia-14)
- **Why not now:** Needs the btrc-hosted GTK4 spike (CX-UIA-14), which needs the GObject binding that waits for Stage 27 steps 1-2.
- **Parallel-safe with:** CX-UIA-24, CX-UIA-25, CX-UIA-26, CX-UIA-27

**Owned paths**

- docs/design/ui-contracts/ui1-feasibility.md (D23 section)
- PLAN.md (D23 outcome, Stage 31 close)

**Must not touch**

- `src/**`
- docs/design/plan-reference.md

**Steps**

1. Run 2 adversarial reviewers, one for GTK4 and one for SDL plus an AT-SPI bridge, over linux-gtk4-feasibility.md and the SDL baseline, plus 1 parity reviewer.
2. Apply D23 literally: GTK4 for Linux UI4-UI8 if the btrc-hosted window passed with native controls, keyboard focus, IME and an AT-SPI tree; otherwise SDL plus an AT-SPI bridge.
3. Close Stage 31 for macOS and Linux in the Progress log, with the Windows, iOS and Android shells listed as open and their blocking items named; CL-UIA-22 closes them.

**Acceptance**

- [ ] The D23 outcome is in PLAN.md with its review files and no unresolved blocking finding.
- [ ] The Stage 31 exit is recorded: shell harness, GObject parity with a byte-stable bootstrap, the GTK record, D23, and the Linux GUI shard green.

**Risks**

- If IME evidence is unavailable, applying D23 literally may block the decision; see the open questions.

<a id="cl-uia-11"></a>

##### CL-UIA-11 · qualification-ci-linux-gui-audio: Linux GUI and audio CI shard under Wayland and X11

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `qualification-ci-linux-gui-audio`
- **Depends on:** [CL-UIA-21](#cl-uia-21); [CX-UIA-09](codex.md#cx-uia-09); [CX-UIA-11](codex.md#cx-uia-11); [CL-UIA-02](#cl-uia-02)
- **Why not now:** Needs the headless sessions (CL-UIA-21), the shell harness and the Linux rows (CX-UIA-09 and CX-UIA-11), and the CI dispatch structure (CL-UIA-02).
- **Parallel-safe with:** CL-UIA-09, CX-UIA-18, CX-UIA-19, CX-UIA-20

**Owned paths**

- .github/workflows/ci.yml (linux-gui jobs)
- Makefile (test-shard-gui target)
- src/tests/fixtures/expected-skips/linux-devcontainer.json (gui shard rules)
- nix/asound.conf (null PCM only)

**Must not touch**

- `src/stdlib/**`
- `src/tests/native/**`
- docs/design/plan-reference.md

**Steps**

1. Add test-shard-gui: test-native-gui plus the Linux audio provider tests and the AlsaFaults fixture, under tools/ui/headless-session.sh, as two ci.yml matrix entries (x11 and wayland) with lavapipe and an ALSA null PCM.
2. Upload the AT-SPI dumps and captures as artifacts, and write the skip report.
3. Add a nightly real-session job only if a D7 self-hosted runner exists (D26). Otherwise add a skip-ledger rule recording 'awaiting hardware' with the exact command.

**Acceptance**

- [ ] ci.yml on main shows linux-gui (x11) and linux-gui (wayland) green with their artifacts (run ids).
- [ ] make skip-gate passes, and only hardware-bound cases skip, each with covered_by.

**Risks**

- The extra shards add CI minutes and runtime.
- The Wayland session with lavapipe may be flaky; keep X11 gating until it is stable.

<a id="cl-uia-12"></a>

##### CL-UIA-12 · Stage 31 integration batch: shell harness, macOS proof, Linux SDL baseline and docs

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** —
- **Depends on:** [CX-UIA-09](codex.md#cx-uia-09); [CX-UIA-10](codex.md#cx-uia-10); [CX-UIA-11](codex.md#cx-uia-11); [CX-UIA-12](codex.md#cx-uia-12); [CX-UIA-13](codex.md#cx-uia-13); [CL-UIA-11](#cl-uia-11)
- **Why not now:** Integrates the Stage 31 Codex packets after they finish.
- **Parallel-safe with:** CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-06

**Owned paths**

- integration branches `integ/ui1-*`
- PLAN.md (Stage 31 progress)
- derived files and expected-skips JSON (applied from fragments)

**Must not touch**

- docs/design/plan-reference.md
- the E40 reproduction branch (never merged before CX-UIA-23)

**Steps**

1. Merge CX-UIA-09, 10, 11 (without the E40 branch), 12 and 13 in order, at most two per batch, applying their fragments.
2. Gate the batch (focused suites plus a sharded make test; no compiler change, so CI carries the bootstrap), push main and read all three workflows. The GObject packets land in their own Claude batches.
3. Ingest the shell rows into the catalog.

**Acceptance**

- [ ] The batch gate is green and CI on main is green (run ids).
- [ ] Shell harness rows for macOS and for Linux under X11 and Wayland are in the catalog.

**Risks**

- Codex batches must not displace C-track batches.

<a id="cl-uia-22"></a>

##### CL-UIA-22 · ui-1-feasibility-review for Windows, iOS and Android: toolkit questions, UI2/UI3 re-check on the real shells, Stage 31 close for those providers

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 31 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ui-1-feasibility-review#windows-ios-android`
- **Depends on:** [CX-UIA-15](codex.md#cx-uia-15); [CX-UIA-16](codex.md#cx-uia-16); [CX-UIA-17](codex.md#cx-uia-17); [MAC-UIA-03](owner.md#mac-uia-03); [CL-UIA-10](#cl-uia-10); [CL-UIA-14](#cl-uia-14); [CL-UIA-20](#cl-uia-20)
- **Why not now:** Needs the three new-platform shells, the owner's simulator/emulator confirmation and the UI2/UI3 landings.

> **Review change:** New (§10 P6): the Windows/iOS/Android half of `ui-1-feasibility-review` had no packet, and neither did Stage 31's exit for those providers.

**Owned paths**

- docs/design/ui-contracts/ui1-feasibility.md (Windows, iOS and Android section)
- docs/design/ui-contracts/reviews/ui1-new-platforms/ (new)
- docs/design/ui-contracts/ui2-approved.md and ui3-approved.md (re-check addenda only)
- PLAN.md (Stage 31 close for the three providers)

**Must not touch**

- docs/design/plan-reference.md
- src/stdlib/GUI/{Windows,IOS,Android}/ (Codex provider code)

**Steps**

1. Run 2 feasibility reviewers and 1 parity reviewer over the Win32 (CX-UIA-15), UIKit (CX-UIA-16) and Android Views (CX-UIA-17) shells, their lane runs and MAC-UIA-03.
2. Decide Win32 versus WinUI and Android Views versus GameActivity, and record both decisions with their review files.
3. Re-check ui2-approved.md and ui3-approved.md against the real shells (D27's provisional clause). A mismatch is a versioned contract change: a CL packet that lands it atomically with macOS and Linux and updates the typed-unsupported stubs.
4. Record Stage 31's exit for the three providers: the shell harness on every provider × frontend × sanitizer, E46/E47 at 100 cycles, 0 leaked handles, accessibility tree artifacts; stand-in versus physical classified.

**Acceptance**

- [ ] 0 unresolved blocking findings; both toolkit decisions and the UI2/UI3 re-check are in PLAN.md with review files.
- [ ] Stage 31's exit is recorded for Windows, iOS and Android, or each missing row names its blocking item.

**Risks**

- A contract change found here touches every provider; it lands as one atomic, versioned change.

#### Stage 32: UI2 contracts (events, executor, lifecycle) and the Library.UI split

<a id="cl-uia-13"></a>

##### CL-UIA-13 · ui-2-contract-review: feasibility and parity review, reconciliation and standing approval

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ui-2-contract-review`
- **Depends on:** [CX-UIA-18](codex.md#cx-uia-18); [CX-UIA-19](codex.md#cx-uia-19); [CX-UIA-20](codex.md#cx-uia-20); [CL-UIA-09](#cl-uia-09); [CX-UIA-13](codex.md#cx-uia-13)
- **Why not now:** Needs the three drafts and the UI1 checkpoint for macOS and Linux (CL-UIA-09).
- **Parallel-safe with:** CL-UIA-06, CL-UIA-07, CX-UIA-14

> **Review change:** Also waits for `CX-UIA-13`, which writes the shell notes step 1 reads. Its approval is provisional for Windows, iOS and Android until `CL-UIA-22` re-checks it on the real shells (D27, §10 P5).

**Owned paths**

- docs/design/ui-contracts/reviews/ui2/ (new)
- docs/design/ui-contracts/ui2-approved.md (new)
- PLAN.md (approval record)

**Must not touch**

- `src/stdlib/**`
- docs/design/plan-reference.md

**Steps**

1. Run the review workflow. 2 feasibility reviewers work from the real UI1 shells (AppKit and SDL; Win32, UIKit and Android through native-ui-shells.md) and hunt for AppKit-shaped API.
2. 1 reconciler aligns the payload and scope vocabulary across the drafts. 1 parity reviewer checks that both compilers can express the result.
3. Turn any compiler gap into a CL packet, and send contract defects back to the drafting lanes.
4. Write ui2-approved.md (the frozen interface diff and its operation ids), and record the standing approval in PLAN.md.

**Acceptance**

- [ ] 0 unresolved blocking findings, and PLAN.md has an approval row with the review files.
- [ ] ui2-approved.md lists every operation id the catalog will gain.

**Risks**

- A late Windows or mobile reviewer objection could reopen the drafts.

<a id="cl-uia-14"></a>

##### CL-UIA-14 · UI2 atomic landing: contract, macOS and Linux in one gated commit

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** —
- **Depends on:** [CX-UIA-21](codex.md#cx-uia-21) (ready); [CX-UIA-22](codex.md#cx-uia-22) (ready); [CX-UIA-23](codex.md#cx-uia-23) (ready)
- **Why not now:** Needs all three UI2 branches.
- **Parallel-safe with:** CX-UIA-24, CX-UIA-14

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- integration branch integ/ui2
- src/stdlib/GUI/btrc.toml (fragments applied) (integrator: applies fragments; not held)
- src/stdlib/btrc.lock (integrator: applies fragments; not held)
- src/stdlib/btrc.symbols (integrator: applies fragments; not held)
- src/devex/lsp/catalog/generated.py (integrator: applies fragments; not held)
- `src/tests/fixtures/expected-skips/*.json` (integrator: applies fragments; not held)
- PLAN.md (Stage 32 progress)
- the BTRSmith rename table (ISelect and IScrollView entries)

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Combine the contract, macOS and Linux branches into one commit on integ/ui2, apply the fragments and regenerate the derived files.
2. Run the full batch gate in the cloud: make test (sharded), make bootstrap (BackgroundJobs is a compiler import), make test-c11, lint, format-check, generated-check, extension, git diff --check and the zero-warning transpiles. Then push main and read all three workflows.
3. Ingest the E-case results, and add the API changes to the BTRSmith rename table with the D24 shim noted.

**Acceptance**

- [ ] One atomic commit on main with a green gate and green CI (run ids).
- [ ] Stage 32 exit evidence: E01-E04, E29, E31, E35, E39, E40 and E46 pass on macOS and Linux with sanitizers, and the E40 repair landed with its reproduction.

**Risks**

- Bootstrap and test-c11 must run alone, which competes with the C track for gate slots.

<a id="cl-uia-15"></a>

##### CL-UIA-15 · ui-2-btrsmith-subscriptions: replace BTRSmith polling with UI2 subscriptions and worker wakeup

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-2-btrsmith-subscriptions`
- **Depends on:** [CL-UIA-14](#cl-uia-14); [CL-UIA-03](#cl-uia-03)
- **Why not now:** Needs the UI2 landing on main and a BTRSmith pin bump to it.
- **Parallel-safe with:** CX-UIA-24, CL-UIA-16

> **Review change:** Listed in D27's Claude-early clause: it may run during bucket 1 because bucket 1 measures the D9 BTRSmith copy pinned by `CL-R-01`/`MAC-R-01`, never BTRSmith `main` (§2, §10 P12).

**Owned paths**

- BTRSmith: src/application/adapters/{TextBinding,SelectionBinding,LibraryFilters,SettingsScreen,PlayerScreen,ApplicationView}.btrc
- BTRSmith: src/application/runtime/GUIApplication.btrc
- BTRSmith: tests for those adapters
- BTRSmith: flake btrc pin
- BTRSmith: tools/ui-idle-wakeups.sh (new)

**Must not touch**

- btrc repository
- BTRSmith files owned by CL-UIA-17 and CL-UIA-18
- docs/design/plan-reference.md

**Steps**

1. Bump BTRSmith's btrc pin to the UI2 landing commit.
2. Replace nextChange sampling in TextBinding and SelectionBinding, and value sampling in LibraryFilters, SettingsScreen and PlayerScreen, with UI2 subscriptions. Keep the persistent editor owners.
3. Replace GUIApplication's periodic GUI.postAfter loop with worker-completion wakeup, and keep timers only for genuinely timed work.
4. Prepare tools/ui-idle-wakeups.sh (idle wakeups per minute from 'top -stats idlew', before and after the pin) for MAC-UIA-04.

**Acceptance**

- [ ] The BTRSmith tests for these adapters pass on Linux through both frontends in the cloud.
- [ ] Adapter tests show one product command per commit and 0 artificial actions on unchanged state. The change is pushed per D4.

**Risks**

- BTRSmith has no CI (bucket 5), so the macOS evidence waits for MAC-UIA-04.

<a id="cl-uia-16"></a>

##### CL-UIA-16 · btrsmith-libraryui-split: typed product view-model design and ui.snapshot versioning

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `btrsmith-libraryui-split`
- **Depends on:** [CL-UIA-03](#cl-uia-03); [CL-UIA-14](#cl-uia-14)
- **Why not now:** Needs the BTRSmith caller inventory and the UI2 events on main.
- **Parallel-safe with:** CL-UIA-15, CX-UIA-24

> **Review change:** Listed in D27's Claude-early clause: it may run during bucket 1 because bucket 1 measures the D9 BTRSmith copy pinned by `CL-R-01`/`MAC-R-01`, never BTRSmith `main` (§2, §10 P12).

**Owned paths**

- BTRSmith: docs/design/ProductViewModel.md (new)
- BTRSmith: docs/design/reviews/libraryui-split/ (new)

**Must not touch**

- BTRSmith `src/**` (design only)
- btrc repository
- docs/design/plan-reference.md

**Steps**

1. Design a typed view-model, derived from session state, that replaces the parallel screen trees (UiApplicationRouter, UiSnapshot, ApplicationPresentationSnapshot, UiAlbumLibrary, UiSettings/UiCoreSettings, UiPlayer) as the source for inspection, ui.snapshot, btrsmithctl and MCP.
2. Keep Library.UI for the musical surfaces only: UiTablature, UiInstrumentSurface, RasterText, and NativeVisualFrame's UIElement root to WebGPU. Move UIEvent/UISelect command currency to typed product commands.
3. Version ui.snapshot, as D24 allows. Run 2 adversarial reviewers and 1 parity reviewer, and record the standing approval with per-surface file ownership for CL-UIA-17 and CL-UIA-18.

**Acceptance**

- [ ] The design is approved with 0 unresolved blocking findings, and the file ownership per surface is listed.

**Risks**

- Agent and MCP consumers depend on ui.snapshot's exact shape.

<a id="cl-uia-17"></a>

##### CL-UIA-17 · btrsmith-libraryui-split migration (A): Library and Settings surfaces

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-libraryui-split#library-settings`
- **Depends on:** [CL-UIA-16](#cl-uia-16); [CL-UIA-15](#cl-uia-15)
- **Why not now:** Needs the approved view-model design and the subscriptions migration.
- **Parallel-safe with:** CL-UIA-18, CX-UIA-24

> **Review change:** Listed in D27's Claude-early clause: it may run during bucket 1 because bucket 1 measures the D9 BTRSmith copy pinned by `CL-R-01`/`MAC-R-01`, never BTRSmith `main` (§2, §10 P12).

**Owned paths**

- BTRSmith: the Library and Settings `Ui*` frontend and adapter files named in ProductViewModel.md (UiAlbumLibrary, UiSettings, UiCoreSettings)
- BTRSmith: tests/integration `Ui*` for those surfaces
- BTRSmith: ApplicationSession merges (this packet merges first)

**Must not touch**

- BTRSmith Player, inspection and agent files (CL-UIA-18)
- btrc repository

**Steps**

1. Move the Library and Settings screens onto the typed view-model, and drop their Library.UI screen trees.
2. Merge into ApplicationSession and ApplicationSessionState first, then run the integration tests once.

**Acceptance**

- [ ] Library.UI imports are gone from the Library and Settings surfaces (count script). Agent outputs are equivalent for these screens, both frontends pass on Linux, and the UI test programs stay under the per-test cap.

**Risks**

- At most two BTRSmith clones at once (capacity rule).

<a id="cl-uia-18"></a>

##### CL-UIA-18 · btrsmith-libraryui-split migration (B): Player, inspection and agent surfaces

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-libraryui-split#player-inspection`
- **Depends on:** [CL-UIA-16](#cl-uia-16); [CL-UIA-15](#cl-uia-15)
- **Why not now:** Needs the approved view-model design and the subscriptions migration. ApplicationSession merges wait until after CL-UIA-17's.
- **Parallel-safe with:** CL-UIA-17, CX-UIA-24

> **Review change:** Listed in D27's Claude-early clause: it may run during bucket 1 because bucket 1 measures the D9 BTRSmith copy pinned by `CL-R-01`/`MAC-R-01`, never BTRSmith `main` (§2, §10 P12).

**Owned paths**

- BTRSmith: `src/frontend/player/Ui*.btrc` except UiTablature and UiInstrumentSurface
- BTRSmith: `src/application/inspection/*`
- BTRSmith: src/application/runtime/ApplicationPresentationSnapshot.btrc
- BTRSmith: src/application/runtime/NativeVisualCoordinator.btrc

**Must not touch**

- BTRSmith Library and Settings files (CL-UIA-17)
- btrc repository

**Steps**

1. Move the Player screen tree, inspection and the agent ui.snapshot onto the view-model, as the versioned protocol.
2. Merge into ApplicationSession after CL-UIA-17, then run AgentSurfaceAcceptance.

**Acceptance**

- [ ] Across the whole tree, Library.UI imports are limited to the musical-surface modules (count script).
- [ ] ui.snapshot vN+1, btrsmithctl and MCP outputs are equivalent, AgentSurfaceAcceptance passes, and both frontends pass.

**Risks**

- NativeVisualCoordinator also feeds the GPU path, so the musical surfaces must keep their frame budget.

#### Stage 33: UI3 input, focus and commands, then the tray

<a id="cl-uia-19"></a>

##### CL-UIA-19 · UI3 contract review: feasibility and parity review and standing approval

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `ui-3-contract-input#review`
- **Depends on:** [CX-UIA-24](codex.md#cx-uia-24); [CL-UIA-14](#cl-uia-14); [CX-UIA-13](codex.md#cx-uia-13)
- **Why not now:** Needs the UI3 draft and UI2 on main.
- **Parallel-safe with:** CL-UIA-15, CL-UIA-16, CL-UIA-17, CL-UIA-18

> **Review change:** Also waits for `CX-UIA-13`. Its approval is provisional for Windows, iOS and Android until `CL-UIA-22` re-checks it on the real shells (D27, §10 P5).

**Owned paths**

- docs/design/ui-contracts/reviews/ui3/ (new)
- docs/design/ui-contracts/ui3-approved.md (new)
- PLAN.md (approval record)

**Must not touch**

- `src/stdlib/**`
- docs/design/plan-reference.md

**Steps**

1. Run 2 feasibility reviewers against the landed UI2 providers and the shell notes, plus 1 parity reviewer.
2. Turn compiler gaps into CL packets. Write ui3-approved.md and record the approval.

**Acceptance**

- [ ] 0 unresolved blocking findings, ui3-approved.md written, and a PLAN approval row.

**Risks**

- Key-identity design varies the most across platforms.

<a id="cl-uia-20"></a>

##### CL-UIA-20 · UI3 atomic landing: contract, macOS and Linux in one gated commit

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** —
- **Depends on:** [CX-UIA-25](codex.md#cx-uia-25) (ready); [CX-UIA-26](codex.md#cx-uia-26) (ready); [CX-UIA-27](codex.md#cx-uia-27) (ready)
- **Why not now:** Needs all three UI3 branches.
- **Parallel-safe with:** CL-UIA-17, CL-UIA-18

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- integration branch integ/ui3
- GUI/App btrc.toml (fragments applied) (integrator: applies fragments; not held)
- src/stdlib/btrc.lock (integrator: applies fragments; not held)
- src/stdlib/btrc.symbols (integrator: applies fragments; not held)
- src/devex/lsp/catalog/generated.py (integrator: applies fragments; not held)
- `src/tests/fixtures/expected-skips/*.json` (integrator: applies fragments; not held)
- PLAN.md (Stage 33 progress)
- the BTRSmith rename table (App and IView entries)

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Combine the three branches into one commit, apply the fragments and regenerate the derived files.
2. Run the batch gate (make test, test-c11, lint, format-check, generated-check, extension, git diff --check; plus bootstrap if a compiler import changed), push main and read CI.
3. Ingest the E-case results and update the rename table.

**Acceptance**

- [ ] One atomic commit with a green gate and green CI (run ids).
- [ ] Stage 33 exit evidence: E05-E07, E13, E14, E25, E27, E44 and E45 pass on macOS and Linux, and E46 holds over 100 cycles per UI3 entry path.

**Risks**

- The App.btrc changes may break BTRSmith until its pin moves.

<a id="cl-uia-23"></a>

##### CL-UIA-23 · GTK4 provider-core atomic landing and the Linux provider switch (only if D23 = GTK4)

- **Owner:** Claude · **Group:** UIA · **Stage:** Stage 33 (D23 follow-up) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `ui-2-linux#gtk4-landing`; `ui-3-linux#gtk4-landing`
- **Depends on:** [CX-UIA-29](codex.md#cx-uia-29) (ready)
- **Why not now:** Needs CX-UIA-29; not applicable if D23 picks SDL.

> **Review change:** New (§10 P7).

**Owned paths**

- integration branch integ/ui-gtk4
- GUI/btrc.toml (integrator: applies fragments; not held)
- PLAN.md (Progress)

**Must not touch**

- docs/design/plan-reference.md

**Steps**

1. Rebase CX-UIA-29 on main-kn9jxh, apply its fragment and switch the Linux provider filter to GTK4; regenerate.
2. Run the cloud batch gate plus test-native-gui under X11 and Wayland, push main, read the three workflows.
3. Record in PLAN.md whether the SDL provider stays as a fallback or retires (D23).

**Acceptance**

- [ ] All three workflows green on main; UI2/UI3 Linux E-cases green on GTK4 (run ids).
- [ ] PLAN.md records the provider switch.

#### Stage 34: UI4–UI9 contract packet and macOS/Linux reference providers

<a id="cl-uib-01"></a>

##### CL-UIB-01 · [Merged into CL-UIA-01] Record D27 and the Claude/Codex ownership protocol for bucket 4

- **Owner:** Claude · **Group:** UIB · **Stage:** Decisions (D27); Stages 34-37 lane ownership · **Environment:** Linux cloud · **Start now:** merged · **Estimate:** 0 agent-hours
- **PLAN items:** `decision:D27`
- **Depends on:** none
- **Why not now:** Merged into CL-UIA-01; no separate work.
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-08, CX-UIB-09

> **Writer note:** **Merged into `CL-UIA-01`** (§9 item 2). No separate work. `CL-UIA-01` carries this packet's steps 3 and 4 (lane-owner annotations, the AGENTS.md paths Codex never edits) and its acceptance. The text below is kept for the record.

**Owned paths**

- PLAN.md (Decisions table D27 row; Standing approvals row for Codex contract packets; Stage 34-37 parallelization owner annotations; Progress log entry)
- AGENTS.md (new 'Second agent (Codex)' section)

**Must not touch**

- docs/design/plan-reference.md
- src/
- tools/
- `docs/design/native-ui-*.md` (Codex-owned)

**Steps**

1. Add D27 to the PLAN.md Decisions table, using the resolution text in this group's summary: ownership, allowed-now (a)-(c), and what stays gated.
2. Under Standing approvals, add: a Codex contract packet is approved when Claude's two adversarial reviewers and the parity reviewer (CL-UIB-02) leave no unresolved blocking finding; a Codex draft never counts as approval.
3. Annotate the Stage 34-37 parallelization bullets with the owner of each lane, the derived-commit fragment rule, and the rule that an in-flight track owns its provider directory, including typed-unsupported stubs.
4. Write the AGENTS.md section, which Codex reads natively. It covers: the branch and draft-PR protocol; the list of paths Codex never edits; the `fragment:`/`derived:` pair (§3.5); the PR report fields; and REQUEST(CL-UIB-NN) blocks with a minimal repro.
5. Land docs-only in the next batch and record the commit in the Progress log.

**Acceptance**

- [ ] git diff --check and make lint format-check are clean.
- [ ] python -m pytest src/tests/python/test_device_registry.py src/tests/python/test_python_compiler_structure.py src/tests/btrc/test_compiler_structure_contract.py -q passes: PLAN item ids and the AGENTS.md inventory tables are unchanged.
- [ ] The Progress log cites the D27 commit.

**Risks**

- Scope groups for buckets 1-3 and Stages 30-33 may also propose D27. Record it once and merge their allowed-now lists.

<a id="cl-uib-02"></a>

##### CL-UIB-02 · Adversarial review and approval of the UI4-UI9 contract packet

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 step 0 (approval under the standing rule) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `exit:stage34-contract-packet-approval`
- **Depends on:** [CX-UIB-17](codex.md#cx-uib-17) (ready)
- **Why not now:** There is no contract packet until Stage 33 lands and CX-UIB-10..17 finish.
- **Parallel-safe with:** CL-UIB-03, CL-UIB-04, CL-UIB-13

> **Writer note:** Claude approves as the D6(c) contract owner (§2.1, §9 item 8). After approval, only Claude may change the frozen contract, either itself or by approving a Codex change.

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- docs/design/native-ui-contracts/review/ (new review files)
- PLAN.md (Stage 34 Progress log: approval record)

**Must not touch**

- src/stdlib/ (findings go back to the Codex packets)

**Steps**

1. Run five platform reviewers (macOS; Linux on the D23 route; Windows; iOS; Android), one adversary hunting AppKit-shaped APIs, and one parity reviewer.
2. The parity reviewer compiles the interface diff and the stubs through both compilers on Linux and on the macos.yml run, with zero warnings. It confirms that nothing needs an unfiled compiler change.
3. Turn findings into new fixture assertions or invalidation rows, and send them back to CX-UIB-10..17 until no blocking finding remains.
4. Triage the interop requests into CL-UIB-09..13. Record the approval and the review files in PLAN.md.

**Acceptance**

- [ ] Review files show 0 unresolved blocking findings.
- [ ] The approval is recorded in the Stage 34 Progress log, with the approved commit ids.

**Risks**

- Review against the real Stage 31 shells requires those shells to have landed.

<a id="cl-uib-03"></a>

##### CL-UIB-03 · Nix/devcontainer additions for the Stage 34-37 Linux UI work

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 (tooling for ui-5/ui-7/ui-8/ui-9-linux), Stage 37 (drivers, UI11) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `exit:stage34-linux-tooling`
- **Depends on:** PLAN:tooling-linux-headless-gui (Stage 30) → [CL-UIA-21](#cl-uia-21); PLAN:ui-1-feasibility-review (D23) → [CL-UIA-10](#cl-uia-10)
- **Why not now:** Stage 30's headless GUI tooling and the D23 decision (Stage 31) have not landed.
- **Parallel-safe with:** CL-UIB-02, CL-UIB-04

**Owned paths**

- flake.nix
- flake.lock (only with a stated reason)
- nix/
- tools/virtual-display.sh

**Must not touch**

- src/stdlib/
- src/compiler/

**Steps**

1. Commit 1 (before L2): shaping libraries. HarfBuzz and fribidi on the SDL route, or Pango on the GTK route, wired into the dev shell and the devcontainer.
2. Commit 2 (before L4): xdg-desktop-portal with a GTK backend, a dbus-run-session launcher option in tools/virtual-display.sh, and at-spi2-core with pyatspi if Stage 30 did not add them.
3. Commit 3 (Stage 37): libei/uinput tooling and XTest/xdotool for the Linux journey driver; WebKitGTK for ui-11-rich-web.
4. Root every dev shell with --profile ~/.cache/btrc/gcroots/\<name> on the Mac, as the Stage 2 hazard requires.

**Acceptance**

- [ ] make devcontainer succeeds.
- [ ] make linux-ci LINUX_CI_TARGETS='lint format-check' passes. The ci.yml run on the branch is green.
- [ ] nix develop --command pkg-config --modversion harfbuzz (or pango) and xdg-desktop-portal --version both answer.

**Risks**

- Nix substitution flakes (ci-health.md).
- Image size grows.

<a id="cl-uib-04"></a>

##### CL-UIB-04 · UI test capabilities, expected-skip policy and CI UI shards for Stage 34

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 (verification infrastructure) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `exit:stage34-ci-ui-shards`
- **Depends on:** PLAN:qualification-ci-linux-gui-audio (Stage 31) → [CL-UIA-11](#cl-uia-11); PLAN:tooling-linux-headless-gui (Stage 30) → [CL-UIA-21](#cl-uia-21)
- **Why not now:** The Stage 31 Linux GUI CI lane and the Stage 30 Wayland tooling have not landed.
- **Parallel-safe with:** CL-UIB-02, CL-UIB-03

> **Writer note:** Step 3's concurrency groups already exist once `CL-UIA-02` lands, so that step is only a check (§9 item 13).

**Owned paths**

- src/tests/runner_capabilities.py
- src/tests/fixtures/expected-skips/{macos,linux-devcontainer,windows}.json (rule schema and categories; Codex rules arrive as `fragment:` commits)
- .github/workflows/ci.yml
- .github/workflows/macos.yml
- src/tests/conftest.py (only if needed)

**Must not touch**

- src/stdlib/
- src/compiler/

**Steps**

1. Add target capabilities: accessibility-api (AX trust or an AT-SPI bus), screen-reader-session (a human present) and real-gpu if the existing GPU-adapter probe does not cover it. Each is granted through BTRC_TEST_CAPABILITIES.
2. Make sure `test_native_ui_*.py` runs under tools/virtual-display.sh in the Linux shards, under X11 and Wayland, and in the macOS unit shard.
3. Add concurrency groups so superseded runs of `codex/*` draft PRs are cancelled.
4. Push workflow edits over SSH: the gh token lacks the workflow scope.

**Acceptance**

- [ ] python -m pytest src/tests/python/test_ci_workflow_contracts.py src/tests/python/test_skip_ledger.py passes.
- [ ] ci.yml and macos.yml dispatched on the branch are green, and the skip gate passes.

**Risks**

- Hosted macOS runners may never grant AX trust, so the accessibility-api cases stay owner-tier (MAC-UIB-03).

<a id="cl-uib-05"></a>

##### CL-UIB-05 · Integrate and gate landing L1: UI4 contract, macOS and Linux controls, UI8 cores

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 landing L1 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `exit:stage34-landing-L1-UI4`
- **Depends on:** [CL-UIB-02](#cl-uib-02); [CL-UIB-04](#cl-uib-04); [CX-UIB-17](codex.md#cx-uib-17) (ready); [CX-UIB-18](codex.md#cx-uib-18) (ready); [CX-UIB-19](codex.md#cx-uib-19) (ready); [CX-UIB-20](codex.md#cx-uib-20) (ready); [CX-UIB-21](codex.md#cx-uib-21) (ready); [CX-UIB-22](codex.md#cx-uib-22) (ready); [CX-UIB-23](codex.md#cx-uib-23) (ready)
- **Why not now:** No landing branches exist yet; Stage 34 has not started.
- **Parallel-safe with:** CX-UIB-25, CX-UIB-26, CX-UIB-27, CL-UIB-13

> **Review change:** Carries its own UI8/UI9 acceptance, including the screen-reader records, before the push (PLAN Bucket 4 intro and Stage 34 exit; §10 P9).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- integration branch integ/ui-l1
- src/stdlib/GUI/btrc.toml (integrator: applies fragments; not held)
- src/stdlib/btrc.lock (integrator: applies fragments; not held)
- src/stdlib/btrc.symbols (integrator: applies fragments; not held)
- src/devex/lsp/catalog/generated.py (integrator: applies fragments; not held)
- PLAN.md (Progress log)

**Must not touch**

- the content of Codex-owned files (fix-forward requests go back to the lane)

**Steps**

1. Fetch the codex branches and rebase them on main-kn9jxh in this order: CX-UIB-17, then 22/23, then 18/19, then 20/21, then any stub-only commits from Stage 35 owners. Drop every 'derived:' commit.
2. Apply the GUI/btrc.toml fragments, re-resolve btrc.lock with btrcpy --fetch, run make compiler-codegen-generate, and check the expected-skip rules.
3. Gate: make lint format-check generated-check; git diff --check; the full make test through the ci.yml shards on the integration branch; macos.yml and windows.yml dispatched.
4. Push main fast-forward on green (D4). Build and publish the base btrcc for pinning. Record the Progress log entry with run ids. On red, run the D5 revert-bisect.

**Acceptance**

- [ ] ci.yml, macos.yml and windows.yml are green on the landing commit, and the skip gate passes.
- [ ] The Stage 34 UI4 functional exit (12 of 12 control families on both frontends) is shown by the catalog report from make qualification-report.
- [ ] UI8 rows for every family this landing adds: tree artifacts, automated keyboard-only journeys on both frontends, and the MAC-UIB-01 (VoiceOver) and MAC-UIB-02 (Orca) records for L1, run on integ/ui-l1 and ingested before the push. UI9 rows for the family's GPU-backed content.

**Risks**

- Five provider directories in one landing. Keep the stub commits separate so a bisect can isolate them.

<a id="cl-uib-06"></a>

##### CL-UIB-06 · Integrate and gate landing L2: UI5 layout

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 landing L2 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `exit:stage34-landing-L2-UI5`
- **Depends on:** [CL-UIB-05](#cl-uib-05); [CX-UIB-25](codex.md#cx-uib-25) (ready); [CX-UIB-26](codex.md#cx-uib-26) (ready); [CX-UIB-27](codex.md#cx-uib-27) (ready); [CL-UIB-03](#cl-uib-03)
- **Why not now:** It follows L1.
- **Parallel-safe with:** CX-UIB-28, CX-UIB-29, CX-UIB-30, CX-UIB-32, CX-UIB-33, CX-UIB-34

> **Review change:** Carries its own UI8/UI9 acceptance, including the screen-reader records, before the push (PLAN Bucket 4 intro and Stage 34 exit; §10 P9).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- integration branch integ/ui-l2
- src/stdlib/GUI/btrc.toml (integrator: applies fragments; not held)
- src/stdlib/btrc.lock (integrator: applies fragments; not held)
- src/devex/lsp/catalog/generated.py (integrator: applies fragments; not held)
- PLAN.md (Progress log)

**Must not touch**

- the content of Codex-owned files

**Steps**

1. Rebase in order: CX-UIB-25, CX-UIB-26, CX-UIB-27, then stub commits. Apply the fragments, including the HarfBuzz/Pango pkg-config entry, and regenerate the derived files.
2. Gate as in CL-UIB-05, with ci.yml, macos.yml and windows.yml green.
3. Push main fast-forward and publish the base btrcc. Record the run ids.

**Acceptance**

- [ ] All three workflows are green and the skip gate passes.
- [ ] The catalog report shows the UI5 matrix, E46 and E47 for macOS and Linux on both frontends.
- [ ] UI8 rows for every family this landing adds: tree artifacts, automated keyboard-only journeys on both frontends, and the MAC-UIB-01 (VoiceOver) and MAC-UIB-02 (Orca) records for L2, run on integ/ui-l2 and ingested before the push. UI9 rows for the family's GPU-backed content.

**Risks**

- A new pkg-config dependency can break the macOS and Windows manifests. Check the OS filters in the fragment.

<a id="cl-uib-07"></a>

##### CL-UIB-07 · Integrate and gate landing L3: UI6 collections, UI9 cores, stress fixture, Linux GPU-children accessibility

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 landing L3 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `exit:stage34-landing-L3-UI6-UI9`
- **Depends on:** [CL-UIB-06](#cl-uib-06); [CX-UIB-24](codex.md#cx-uib-24) (ready); [CX-UIB-28](codex.md#cx-uib-28) (ready); [CX-UIB-29](codex.md#cx-uib-29) (ready); [CX-UIB-30](codex.md#cx-uib-30) (ready); [CX-UIB-31](codex.md#cx-uib-31) (ready); [CX-UIB-32](codex.md#cx-uib-32) (ready); [CX-UIB-33](codex.md#cx-uib-33) (ready); [CX-UIB-34](codex.md#cx-uib-34) (ready)
- **Why not now:** It follows L2.
- **Parallel-safe with:** CX-UIB-35, CX-UIB-36

> **Review change:** Carries its own UI8/UI9 acceptance, including the screen-reader records, before the push (PLAN Bucket 4 intro and Stage 34 exit; §10 P9).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- integration branch integ/ui-l3
- src/stdlib/GUI/btrc.toml (integrator: applies fragments; not held)
- src/stdlib/btrc.lock (integrator: applies fragments; not held)
- src/devex/lsp/catalog/generated.py (integrator: applies fragments; not held)
- PLAN.md (Progress log)

**Must not touch**

- the content of Codex-owned files

**Steps**

1. Rebase in order: CX-UIB-28, then 33 and 34, then 31, then 29, 30 and 24, then stubs. Apply the fragments and regenerate the derived files.
2. Gate as in CL-UIB-05.
3. Push, and record the UI6 and UI9 evidence summary.

**Acceptance**

- [ ] All three workflows are green.
- [ ] The catalog shows the 100,000-row budget met on both frontends for macOS and Linux, and E36/E38/E42/E43 on the Linux CI tier.
- [ ] UI8 rows for every family this landing adds: tree artifacts, automated keyboard-only journeys on both frontends, and the MAC-UIB-01 (VoiceOver) and MAC-UIB-02 (Orca) records for L3, run on integ/ui-l3 and ingested before the push. UI9 rows for the family's GPU-backed content.

**Risks**

- The largest landing. Bisect by provider if the gate is red.

<a id="cl-uib-08"></a>

##### CL-UIB-08 · Integrate and gate landing L4 (UI7), the probes and the Stage 34 close, including the denominator re-freeze

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 landing L4 and stage exit · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `exit:stage34-landing-L4-UI7-and-close`
- **Depends on:** [CL-UIB-07](#cl-uib-07); [CX-UIB-35](codex.md#cx-uib-35) (ready); [CX-UIB-36](codex.md#cx-uib-36) (ready); [CX-UIB-37](codex.md#cx-uib-37) (ready); [CX-UIB-38](codex.md#cx-uib-38) (ready); [CX-UIB-41](codex.md#cx-uib-41) (ready); [MAC-UIB-01](owner.md#mac-uib-01); [MAC-UIB-02](owner.md#mac-uib-02); [MAC-UIB-03](owner.md#mac-uib-03)
- **Why not now:** It follows L3.
- **Parallel-safe with:** CL-UIB-14, CL-UIB-15

> **Writer note:** Freeze the added operations as a **new release**, alongside the releases `CX-UIA-02` and `CX-UIA-05` already froze. The 2026-09-21 release stays frozen, and the Stage 37 exit counts every release in force (§7 Q35, §9 item 9).

> **Review change:** Carries its own UI8/UI9 acceptance, including the screen-reader records, before the push (PLAN Bucket 4 intro and Stage 34 exit; §10 P9).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- integration branch integ/ui-l4
- src/stdlib/GUI/btrc.toml (integrator: applies fragments; not held)
- src/stdlib/btrc.lock (integrator: applies fragments; not held)
- src/devex/lsp/catalog/generated.py (integrator: applies fragments; not held)
- tools/qualification/denominators.toml (a new release for the added UI operations)
- PLAN.md (Stage 34 exit record)

**Must not touch**

- the content of Codex-owned files

**Steps**

1. Rebase in order: CX-UIB-37, 38, 35, 36, 41. Apply the fragments and regenerate.
2. Freeze a new ui-operation release for the added operations. Keep ui0-source-inventory-2026-09-21 at 1,620 slots.
3. Gate as in CL-UIB-05. Write the Stage 34 exit:
   - E36, E38, E42 and E43;
   - idle CPU at or below 1%;
   - stable fixture hashes;
   - 100% UI8 coverage of core actionable controls;
   - the screen-reader records from MAC-UIB-01 and 02.

   Push.

**Acceptance**

- [ ] All three workflows are green, and test_qualification_ledger.py passes with the new release.
- [ ] The Progress log records the Stage 34 exit, each criterion with its evidence.
- [ ] UI8 rows for every family this landing adds: tree artifacts, automated keyboard-only journeys on both frontends, and the MAC-UIB-01 (VoiceOver) and MAC-UIB-02 (Orca) records for L4, run on integ/ui-l4 and ingested before the push. UI9 rows for the family's GPU-backed content.

**Risks**

- The owner's sessions are a gating dependency for the exit record. The landing can proceed and the exit stays open until they are done.

<a id="cl-uib-09"></a>

##### CL-UIB-09 · Objective-C interop for AppKit and UIKit UI providers: accessibility-element subclasses, data-source protocols, generic erasure, completion blocks

- **Owner:** Claude · **Group:** UIB · **Stage:** Stages 34-35 (interop support for ui-8-macos, ui-6-macos, ui-7-macos, ui-9-macos and the iOS track) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-8-macos` (compiler/interop half); `ui-ios-a11y-gpu` (compiler/interop half); `ui-ios-collections-services` (compiler/interop half)
- **Depends on:** PLAN:platforms-i1-objc-protocol-adapters (Stage 29, interop step 6: superclass, overrides, generic erasure) → [CL-P2-21](#cl-p2-21); [CX-UIB-07](codex.md#cx-uib-07) (gap list)
- **Why not now:** Interop step 6 (Stage 29) has not landed.
- **Parallel-safe with:** CL-UIB-10, CL-UIB-11, CL-UIB-12

**Owned paths**

- src/compiler/python/frontend/native_imports.py and the matching btrc frontend owners
- src/language/native_abi.asdl (only if a field is needed; one owner per schema commit)
- tools/NativeHeaderReader.cpp
- src/tests/python/test_native_objective_c_{delegates,blocks,objects}.py and new UI interop fixtures

**Must not touch**

- src/stdlib/GUI/ (Codex)

**Steps**

1. Qualify, through both compilers, each construct the UI providers need:
   - NSAccessibilityElement and UIAccessibilityElement subclasses overriding accessibilityPerformPress, accessibilityFrame and accessibilityChildren;
   - the NSTableView/NSOutlineView/NSCollectionView and UICollectionView data-source and delegate protocols;
   - generic erasure of UICollectionViewDiffableDataSource;
   - completion blocks for beginSheetModalForWindow and the open panels;
   - display-link target-action.
2. Fix gaps Python first, then btrc, one commit per construct. Each gets a regression fixture and a feature bootstrap.
3. Answer each Codex REQUEST with the fixture that proves it.

**Acceptance**

- [ ] The new fixtures pass on the macos.yml unit shard and the iOS simulator job, both compilers, at -O2 and under ASan/UBSan.
- [ ] make test, a zero-warning self-host transpile and the bootstrap fixed point all pass.

**Risks**

- Generic erasure of Swift-shaped UIKit APIs may need a schema field (native_abi.asdl is serial).

<a id="cl-uib-12"></a>

##### CL-UIB-12 · Linux UI interop: GTK custom widget and GtkAccessible implementation (GTK route), or verified D-Bus object export (SDL route)

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 34 (interop support for ui-8-linux and ui-6-linux) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-8-linux` (compiler/interop half)
- **Depends on:** PLAN:ui-1-linux-gobject-binding (Stage 31 interop step 8) → [CL-UIA-08](#cl-uia-08); PLAN:ui-1-feasibility-review (D23) → [CL-UIA-10](#cl-uia-10); [CX-UIB-07](codex.md#cx-uib-07)
- **Why not now:** The GObject binding and D23 (Stage 31) are not done.
- **Parallel-safe with:** CL-UIB-09, CL-UIB-10, CL-UIB-11

**Owned paths**

- src/compiler/python/ and btrc native-import owners (GObject parent, implements and class vfuncs)
- `src/tests/python/test_native_gobject_*.py`

**Must not touch**

- src/stdlib/GUI/Linux/ (Codex)

**Steps**

1. GTK route: a GtkWidget subclass with snapshot, measure and size_allocate vfunc overrides for the GPU host widget, and GtkAccessible/GtkAccessibleRange implementations for virtual children.
2. SDL route: prove that D-Bus method and property vtables for `org.a11y.atspi.*` export from btrc with the existing binding. Fix only what fails.

**Acceptance**

- [ ] Tier-B style fixtures, or the D-Bus export round trip, pass through both compilers at -O2 and under ASan/UBSan.
- [ ] The bootstrap fixed point holds.

**Risks**

- The scope depends entirely on D23.

<a id="cl-uib-13"></a>

##### CL-UIB-13 · Compiler request queue for the second half of bucket 4: parity defects, analyzer and realtime support, header-reader gaps

- **Owner:** Claude · **Group:** UIB · **Stage:** Stages 34-37 (support) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `exit:compiler-requests-from-codex-packets`
- **Depends on:** [CL-UIB-02](#cl-uib-02)
- **Why not now:** The bucket-4 request queue opens with the Stage 34 contract approval (CL-UIB-02); earlier requests become CL-REQ-NN.
- **Parallel-safe with:** CL-UIB-02, CL-UIB-05

> **Review change:** No longer start-now and no longer holds all of `src/compiler/**` and `src/language/**`: it opens with `CL-UIB-02`, and each request holds only its own files (§10 P12).

**Owned paths**

- per request, as CL-REQ-NN: the compiler, spec or reader files each request names, held only while its commit is in flight (§3.3)

**Must not touch**

- src/stdlib/GUI/, src/stdlib/UI/, src/stdlib/App/, src/stdlib/Tray/ (Codex)

**Steps**

1. Watch Codex PRs for REQUEST(CL-UIB-13) blocks. Reproduce each through both compilers with the attached repro.
2. Fix Python first, then btrc, in one commit, with a regression test. Typical requests: realtime-proof support for the probe atomics (CX-UIB-37), HarfBuzz/Pango header-reader gaps (CX-UIB-27), generic data-source limits (CX-UIB-14), nullable-flow warnings in new GUI code.
3. Run a zero-warning self-host transpile of all three entries, and a feature bootstrap when compiler sources change. Reply in the PR with the fix commit.

**Acceptance**

- [ ] Each request is closed by a regression test that passes through both compilers, with make test green on CI, the bootstrap fixed point, and a reply in the requesting PR.

**Risks**

- It competes with bucket-2 schema work for the parser and analyzer hotspots. Batch the fixes with C-track merges.

#### Stage 35: Windows, iOS and Android UI tracks (one milestone behind Stage 34)

<a id="cl-uib-10"></a>

##### CL-UIB-10 · COM provider objects with several interfaces, for UI Automation and OLE drag/drop

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 35 (interop support for ui-win-a11y-gpu and ui-win-collections-services) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-a11y-gpu` (compiler/interop half); `ui-win-collections-services` (COM sink half)
- **Depends on:** PLAN:platforms-w1-win32-com-imports (Stage 27 interop step 5: com-sinks) → [CL-P2-10](#cl-p2-10)
- **Why not now:** COM interop step 5 (Stage 27) has not landed.
- **Parallel-safe with:** CL-UIB-09, CL-UIB-11, CL-UIB-12

**Owned paths**

- src/compiler/python/ (native imports, ownership lowering) and the matching btrc owners
- src/stdlib/COM/ (Claude-owned, from Stage 27)
- `src/tests/python/test_native_com_*.py` (new UIA and OLE fixtures)

**Must not touch**

- src/stdlib/GUI/ (Codex)

**Steps**

1. Extend com-sinks so one btrc object implements several interfaces with QueryInterface identity: IRawElementProviderSimple, IRawElementProviderFragment and IRawElementProviderFragmentRoot, plus pattern providers; also IDropTarget, IDropSource and IDataObject, and IFileDialogEvents.
2. Map their lifetime onto native-interop-ownership.md relation 3 (foreign code holds one external claim).
3. Prove it on the Linux proxy (ComShape.h style) with exact counts under sanitizers, then with a UIA client and an OLE round trip on windows.yml (x64 and ARM64).

**Acceptance**

- [ ] Exact release counts: live count 0, and identity holds across interfaces.
- [ ] Both compilers pass, the bootstrap fixed point holds, and windows.yml is green.

**Risks**

- UIA calls arrive on RPC threads, so the executor rules from relation 3 apply.

<a id="cl-uib-11"></a>

##### CL-UIB-11 · Android UI interop: the class-file reader over androidx AAR classes.jar, Java shim classes registered through RegisterNatives

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 35 (interop support for the Android track) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-android-core` (JNI shim half); `ui-android-collections-services` (androidx half); `ui-android-a11y-gpu` (AccessibilityNodeProvider half)
- **Depends on:** PLAN:platforms-a1-checked-jni (Stage 29 interop step 7: RegisterNatives) → [CL-P2-24](#cl-p2-24); PLAN:platforms-a2-packaging-16k → [CX-P2-45](codex.md#cx-p2-45)
- **Why not now:** The JNI steps 4 and 7 (Stages 27 and 29) have not landed.
- **Parallel-safe with:** CL-UIB-09, CL-UIB-10, CL-UIB-12

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- tools/JavaClassReader.c
- src/compiler/python/frontend/native_imports.py (Java branch) and the btrc frontend's Java branch
- tools/native_plan.py (javac/d8 for stdlib shim sources)
- `src/tests/python/test_native_java_*.py`

**Must not touch**

- `src/stdlib/GUI/Android/java/*.java` (Codex writes the shim sources)

**Steps**

1. Read classes.jar from androidx AAR archives (RecyclerView, core, the Material toggle group), pinned by digest in platform-toolchain-matrix.md.
2. Compile Codex's shim classes into the package, and register their native methods through the A1 RegisterNatives path.
3. Test on a host JVM with -Xcheck:jni, then on the emulator, with no CheckJNI aborts.

**Acceptance**

- [ ] Reader goldens, plus host-JVM and emulator round trips, through both compilers.
- [ ] The bootstrap fixed point holds.

**Risks**

- The Gradle/AGP route versus direct d8 (the toolchain matrix calls direct d8 undocumented).

<a id="cl-uib-14"></a>

##### CL-UIB-14 · Stage 35 CI UI shards for Windows, iOS and Android

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 35 (integration) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `exit:stage35-track-landings`
- **Depends on:** [CX-P2-18](codex.md#cx-p2-18); [CX-P2-49](codex.md#cx-p2-49); [CX-P2-50](codex.md#cx-p2-50); [CX-P1-05](codex.md#cx-p1-05); [CL-UIB-04](#cl-uib-04)
- **Why not now:** Needs the Stage 27/29 platform CI workflows and the Stage 34 UI test capabilities.
- **Parallel-safe with:** CL-UIB-15, CL-UIB-13

> **Review change:** Split (§10 F6): `CX-UIB-42`/`50`/`58` depend on this packet, but its step 2 landed those same packets, a cycle. This half adds the CI UI shards; the rolling landings are `CL-UIB-19`.

**Owned paths**

- .github/workflows/windows.yml (UI shard)
- .github/workflows/macos.yml (iOS UI job)
- .github/workflows/ci.yml (Android emulator UI job)
- src/tests/python/test_ci_workflow_contracts.py (rows for these jobs)

**Must not touch**

- the content of Codex-owned provider files

**Steps**

1. Add the UI shards, granting windows-native, ios-simulator and android-emulator, with retry policy for emulator flakes and concurrency groups.
2. Each job uploads its skip report as its last step; add the expected-skip rules for these runners.

**Acceptance**

- [ ] Each shard runs a smoke selection and uploads its skip report (run ids); test_ci_workflow_contracts.py and the skip gate pass.

**Risks**

- Emulator flakes: retry policy per job, never per test.

<a id="cl-uib-19"></a>

##### CL-UIB-19 · Stage 35 rolling track landings for Windows, iOS and Android

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 35 (integration) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 18 agent-hours
- **PLAN items:** `exit:stage35-track-landings`
- **Depends on:** [CL-UIB-14](#cl-uib-14); [CL-UIB-05](#cl-uib-05); [CX-UIB-42](codex.md#cx-uib-42)…65 (rolling: each milestone lands as it becomes ready)
- **Why not now:** The first track milestone follows landing L1 and the CI UI shards.

> **Review change:** New (§10 F6): the landing half of the old `CL-UIB-14`. A track packet is done when its milestone lands, not when this rolling packet finishes.

**Owned paths**

- integration branches `integ/s35-*`
- src/stdlib/GUI/btrc.toml, src/stdlib/btrc.lock, LSP catalog (integrator: applies fragments; not held)
- PLAN.md (Progress log)

**Must not touch**

- the content of Codex-owned provider files
- docs/design/plan-reference.md

**Steps**

1. Land each track milestone (core, controls, layout, collections, services, accessibility, GPU) as its own small batch: rebase, apply fragments, regenerate derived files, gate (lint, format, generated-check, the three workflows), push.
2. Record each milestone's E-cases in the catalog report.

**Acceptance**

- [ ] Every batch is green on all three workflows and the lane workflows, and the skip gate passes.
- [ ] The Stage 35 exit is recorded with its stand-in versus physical classification.

**Risks**

- About 24 landings at roughly 45 minutes each; combine adjacent milestones when CI is green. Each counts as one Codex code branch toward D27's cap.

#### Stage 36: BTRSmith screen migration slices (one milestone behind Stage 34)

<a id="cl-uib-15"></a>

##### CL-UIB-15 · Stage 36 BTRSmith integration batches and btrc pin bumps

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 36 (integration; one integrator owns the ApplicationSession, ApplicationView and GUIApplication merges) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `exit:stage36-integration`
- **Depends on:** [CL-UIB-05](#cl-uib-05)
- **Why not now:** No btrc UI landing exists to pin against (the first pin follows landing L1).
- **Parallel-safe with:** CL-UIB-14

> **Review change:** Depends only on `CL-UIB-05`. `MAC-UIB-07` stays an acceptance item (green before each BTRSmith push), not a dependency: the old edge closed the cycle `CX-UIB-66` → `CL-UIB-15` → `MAC-UIB-07` → `CX-UIB-66` (§10 P1). This is a rolling packet: a slice that needs a pin depends on the named step, not on the whole packet (§3.10).

**Owned paths**

- btrsmith: flake.nix/flake.lock btrc pin
- btrsmith: src/application/runtime/ApplicationSession.btrc (merge resolution)
- btrsmith: integration branches in ~/.cache/btrsmith/hub.git

**Must not touch**

- btrc compiler sources

**Steps**

1. After each btrc landing (L1-L4), bump BTRSmith's btrc pin and update for API changes with the rename table.
2. Merge the codex BTRSmith branches in slice order, serializing the hotspot edits. Run the Linux-side checks in the cloud.
3. Push BTRSmith main only after MAC-UIB-07's Mac gate (D4). Clean the test outputs.

**Acceptance**

- [ ] BTRSmith Linux checks are green, both frontends. MAC-UIB-07 is green before each push. Pin bumps are recorded in PLAN.md.

**Risks**

- At most 2 BTRSmith clones on the Mac.

#### Stage 37: UI10 automation and mobile restoration; UI11 long tail

<a id="cl-uib-16"></a>

##### CL-UIB-16 · Apple and Android API availability model in native_abi.asdl, the reader and both importers (UI10 OS/SDK prerequisite)

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 37 (compiler half of ui-10-qualification; can move into bucket 3 if preferred) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-10-qualification` (availability model the native ABI lacks)
- **Depends on:** PLAN:platforms-p1-target-spec (Stage 24) → [CL-P1-06](#cl-p1-06); native_abi.asdl v2-v4 sequence (Stage 27 steps 1-4) → [CL-P2-05](#cl-p2-05), [CL-P2-07](#cl-p2-07), [CL-P2-08](#cl-p2-08); PLAN:platforms-i1-objc-protocol-adapters → [CL-P2-21](#cl-p2-21); PLAN:platforms-a1-checked-jni → [CL-P2-24](#cl-p2-24); [CL-UIA-08](#cl-uia-08)
- **Why not now:** Stage 24's target rows and the serial native_abi.asdl schema sequence of Stage 27 must land first (one owner per schema commit).
- **Parallel-safe with:** CL-UIB-17

> **Writer note:** Scheduled right after `CL-P2-24`, at the end of the Stage 27–29 `native_abi.asdl` chain, not in Stage 37 (§7 Q12, §9 item 14).

> **Review change:** Joins the `native_abi.asdl` chain right after the GObject binding (`CL-UIA-08`, interop step 8), not before it, so GObject stays on bucket 4's critical path (§7 Q12, which needs the owner's approval; §10 P4).

**Owned paths**

- src/language/native_abi.asdl
- tools/NativeHeaderReader.cpp
- src/compiler/python/frontend/native_imports.py, the optimizer availability check, and their btrc owners
- docs/design/platform-target-contract.md (section 2.4 gap closed)
- src/tests/python/test_native_availability.py and a btrc parity test (new)

**Must not touch**

- src/stdlib/GUI/ (Codex)

**Steps**

1. Add availability (platform, introduced, deprecated, obsoleted) to the declarations, read from clang's AvailabilityAttr (API_AVAILABLE) and bionic's __INTRODUCED_IN.
2. Refuse an unguarded reachable use above the row's deployment minimum, with the same message in both compilers, and design the guard form.
3. Python first, then btrc. Generated-source check, feature bootstrap, reader goldens on Linux and against the macOS SDK on macos.yml.

**Acceptance**

- [ ] The availability tests pass through both compilers on Linux and macos.yml. Generated check and bootstrap fixed point pass.

**Risks**

- Changing a shared spec collides with other schema commits; schedule it serially.

<a id="cl-uib-17"></a>

##### CL-UIB-17 · Stage 37 landings, the final full gate on the bucket-4 revision, and the coverage report

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 37 (integration and full gate) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-10-qualification` (final gate and integration); `exit:stage37-full-gate`
- **Depends on:** [CX-UIB-77](codex.md#cx-uib-77); [CX-UIB-78](codex.md#cx-uib-78); [CX-UIB-79](codex.md#cx-uib-79); [CX-UIB-80](codex.md#cx-uib-80); [CX-UIB-81](codex.md#cx-uib-81); [CX-UIB-82](codex.md#cx-uib-82); [CX-UIB-86](codex.md#cx-uib-86); [CX-UIB-87](codex.md#cx-uib-87); [CX-UIB-88](codex.md#cx-uib-88); [CX-UIB-89](codex.md#cx-uib-89); [CX-UIB-90](codex.md#cx-uib-90); [CX-UIB-91](codex.md#cx-uib-91); [CX-UIB-92](codex.md#cx-uib-92); [CX-UIB-93](codex.md#cx-uib-93); [CX-UIB-94](codex.md#cx-uib-94); [CL-UIB-16](#cl-uib-16); [CX-UIB-95](codex.md#cx-uib-95) (ready); [CL-UIB-18](#cl-uib-18); [CL-UIB-19](#cl-uib-19)
- **Why not now:** All Stage 37 lanes must finish first.
- **Parallel-safe with:** CL-UIB-16

> **Review change:** The Mac gate is `MAC-UIB-11` (split from `MAC-UIB-10`, §10 P1). It runs on this packet's final revision, so this packet's own acceptance is its CI gate; Stage 37 closes when `MAC-UIB-11` is ingested (§3.10 item 4).

**Owned paths**

- integration branches `integ/ui-s37-*`
- src/stdlib/GUI/btrc.toml, src/stdlib/btrc.lock, LSP catalog (derived) (integrator: applies fragments; not held)
- tools/qualification/denominators.toml (any UI11 release)
- PLAN.md (Stage 37 exit; UI10 row kept open until Stage 42)

**Must not touch**

- the content of Codex-owned files

**Steps**

1. Land the drivers, the mobile lanes, UI11 and the aggregation in small batches. Regenerate derived files and gate each batch on the three workflows.
2. On the final revision: the full CI matrix plus MAC-UIB-11's Mac gate. Then make qualification-report.
3. Record the Stage 37 exit, and the deferrals to Stages 41 and 42.

**Acceptance**

- [ ] The full gate is green on CI and on the Mac (MAC-UIB-11, which runs on this revision after this packet's CI gate). The catalog report matches CX-UIB-86's totals.

**Risks**

- Any fix restarts the gate.

<a id="cl-uib-18"></a>

##### CL-UIB-18 · UI11 contract review and approval (pickers, rich text and web, print and media, data editing, documents and help)

- **Owner:** Claude · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `ui-11-pickers-n51-n52#review`; `ui-11-rich-web-n53-n54#review`; `ui-11-print-media-n55-n57#review`; `ui-11-data-docs-help-n58-n60#review`
- **Depends on:** [CX-UIB-95](codex.md#cx-uib-95) (ready: docs-only drafts)
- **Why not now:** Needs CX-UIB-95's drafts.

> **Review change:** New (§10 C10).

**Owned paths**

- docs/design/ui-contracts/reviews/ui11/ (new)
- docs/design/ui-contracts/ui11-approved.md (new)
- PLAN.md (approval row)

**Must not touch**

- docs/design/plan-reference.md
- `src/stdlib/GUI/**` (Codex)

**Steps**

1. Run 2 feasibility reviewers (desktop; Windows, iOS and Android against the landed Stage 35 providers) and 1 parity reviewer over CX-UIB-95's drafts and factory plan.
2. Write ui11-approved.md (the frozen interface diff and operation ids), record the standing approval in PLAN.md, and send defects back to CX-UIB-95.

**Acceptance**

- [ ] 0 unresolved blocking findings; ui11-approved.md lists every operation id; a PLAN.md approval row.

#### Stage 38: CI tiers, macOS native suite, BTRSmith CI, cross-target benchmarks

<a id="cl-r-36"></a>

##### CL-R-36 · Close qualification-ci-macos-native-suite: hardware skip category and a hosted-runner manifest, so hosted macOS shards skip only hardware-tier cases

- **Owner:** Claude · **Group:** R · **Stage:** 38 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `qualification-ci-macos-native-suite`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-02, CL-R-04, CL-R-05, CL-R-06, CL-R-23, CL-R-37

**Owned paths**

- tools/qualification/skips.py
- src/tests/skip_ledger.py
- src/tests/fixtures/expected-skips/macos.json
- src/tests/fixtures/expected-skips/macos-hosted.json (new)
- src/tests/python/test_skip_ledger.py
- .github/workflows/macos.yml
- docs/design/ci-health.md (macOS section)

**Must not touch**

- src/tests/conftest.py (unless the runner name needs it; then this packet holds it)
- flake.nix
- `src/compiler/**`

**Steps**

1. Add CATEGORY 'hardware' (gating capabilities such as coreaudio-device, gpu-adapter, physical-display) and runner 'macos-hosted' to RUNNERS.
2. Split macos.json: the acceptance Mac keeps 'macos'; macos.yml sets BTRC_TEST_RUNNER=macos-hosted.
3. Classify every hosted skip from the latest macOS run's skip-report artifacts (`gh run download <id> -p 'skip-report-macos-*'`). A non-hardware, non-platform skip is either fixed or filed to its owner (tools to the nix owner).
4. Re-run the skip-coverage check over all three runners.

**Acceptance**

- [ ] `gh workflow run macos.yml --ref <branch>` green; every shard's report has 0 unexpected skips
- [ ] Every macos-hosted rule is category hardware or platform
- [ ] `python3 -m pytest src/tests/python/test_skip_ledger.py -q` passes; `python3 -m tools.qualification skip-coverage` confirms every covered_by claim

**Risks**

- Pulled forward under D27(b).
- macOS runner concurrency is shared with Codex draft PRs.

<a id="cl-r-37"></a>

##### CL-R-37 · BTRSmith CI: Linux hosted runners on every push and PR for both frontends, macOS on tags, btrcc via actions/cache, cost per run recorded

- **Owner:** Claude · **Group:** R · **Stage:** 38 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-ci-btrsmith`; `btrsmith-q-ci`
- **Depends on:** none
- **Parallel-safe with:** CL-R-01, CL-R-02, CL-R-23, CL-R-36

**Owned paths**

- btrsmith:.github/workflows/ci.yml (new)
- btrsmith:.github/workflows/release-macos.yml (new, tags only)
- btrsmith:.github/workflows/self-hosted.yml (new, inactive until MAC-R-07)
- btrsmith:docs/CI.md (new)

**Must not touch**

- `btrsmith:src/**`, `tests/**`, `make/**` (CL-R-01 holds them)
- btrc `.github/**`

**Steps**

1. Linux job matrix {reference, selfhost}: nix dev shell; btrcc cached with actions/cache keyed on flake.lock and the btrc rev (D26: no binary-cache account); run `make check source-check application-frontend-check linux-product-check packaging-check`.
2. Run `btrsmith-library-smoke` under Xvfb and lavapipe, copying btrc's tools/virtual-display.sh approach, if the PSARC fixture is in-repo.
3. macOS workflow runs on tags only: `make release-check` per frontend.
4. Self-hosted job gated on the nixos-x86-acceptance label.
5. Measure minutes per run (`gh run view --json jobs`) into docs/CI.md against D26's included minutes; add paths-ignore for docs.

**Acceptance**

- [ ] Two consecutive green runs on a BTRSmith draft PR for both frontends; the second shows a btrcc cache hit
- [ ] docs/CI.md records cost per run and monthly projection within the included minutes
- [ ] One tag-triggered macOS run on a throwaway `ci-test-*` tag (deleted after) proves the release workflow

**Risks**

- Pulled forward under D27(b).
- Private media fixtures may be absent from CI; those targets are listed as Mac-only.
- Private-repo macOS minutes cost 10×.

<a id="cl-r-38"></a>

##### CL-R-38 · CI tiering core: PR, main, extended, release and hardware tiers for Linux, macOS and Windows; a tier manifest for lane fragments; one release dispatch producing one ledger bundle

- **Owner:** Claude · **Group:** R · **Stage:** 38 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-ci-tiering`
- **Depends on:** [CL-R-36](#cl-r-36)
- **Why not now:** Serial after the macOS suite closure (CL-R-36), which also edits macos.yml.
- **Parallel-safe with:** CL-R-37, CL-R-23

**Owned paths**

- .github/workflows/ci.yml
- .github/workflows/macos.yml
- .github/workflows/windows.yml
- .github/workflows/release.yml (new)
- ci/tiers.toml (new tier manifest)
- tools/qualification/bundle.py (new)
- tools/qualification/cli.py (bundle subcommand)
- src/tests/python/test_qualification_bundle.py (new)

**Must not touch**

- flake.nix
- Makefile (shard targets unchanged)
- `src/compiler/**`

**Steps**

1. PR tier: generated, lint and format; unit; path-filtered corpus subsets; macOS and Windows shards only when their paths change.
2. Main push: today's full matrix. Extended (dispatch and nightly): full both-frontend corpus, Windows bootstrap, 8 C11 cells. Hardware: self-hosted and devices, recorded as awaiting.
3. A setup job reads ci/tiers.toml, so Codex lanes add shards as integrator-applied fragments, like btrc.toml fragments.
4. Release dispatch runs every tier, then one job ingests every skip report, JUnit, bench and boundary report into one ledger bundle (`python3 -m tools.qualification bundle`) and uploads ledger-bundle-\<sha>.

**Acceptance**

- [ ] `gh workflow run release.yml --ref <branch>` yields exactly one ledger-bundle-\<sha> artifact containing every job's records
- [ ] A docs-only draft PR finishes CI in under 10 minutes; a compiler PR still runs the full main matrix
- [ ] `python3 -m tools.qualification skip-coverage` shows no lost coverage against the last full run; test_qualification_bundle.py passes

**Risks**

- Pulled forward under D27(b).
- Path filters can hide a cross-cutting break; main pushes keep the full matrix.

<a id="cl-r-39"></a>

##### CL-R-39 · CI tiering extension: Windows ARM64, iOS simulator, Android emulator and Linux GUI/audio lanes folded into the tiers

- **Owner:** Claude · **Group:** R · **Stage:** 38 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `qualification-ci-tiering`
- **Depends on:** [CL-R-38](#cl-r-38); ext:platforms-p2-ci-lanes (Stage 25) → [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09); ext:tooling-android-ci-emulator (Stage 25) → [CX-P1-05](codex.md#cx-p1-05); ext:qualification-ci-windows-matrix (Stage 27) → [CX-P2-18](codex.md#cx-p2-18); ext:qualification-ci-ios (Stage 29) → [CX-P2-49](codex.md#cx-p2-49); ext:qualification-ci-android (Stage 29) → [CX-P2-50](codex.md#cx-p2-50); ext:qualification-ci-linux-gui-audio (Stage 31) → [CL-UIA-11](#cl-uia-11)
- **Why not now:** The platform CI lanes from buckets 3-4 do not exist yet.
- **Parallel-safe with:** CL-R-40

**Owned paths**

- ci/tiers.toml
- .github/workflows/release.yml
- tools/qualification/bundle.py

**Must not touch**

- the platform lanes' own workflow files (their owners)

**Steps**

1. Assign each new lane to PR, extended or release tiers by cost.
2. Extend the release bundle with mobile and ARM64 records.
3. Record minutes per tier.

**Acceptance**

- [ ] Release dispatch bundle includes Windows x64 and ARM64, iOS simulator, Android emulator (min and current API, 4/16 KiB) and Linux GUI/audio records
- [ ] Exit: one release dispatch produces one ledger bundle

**Risks**

- Emulator flakiness on hosted runners; the tier marks retries explicitly.

<a id="cl-r-40"></a>

##### CL-R-40 · P6 build-bench core: budget_bench target/driver abstraction (cross target, installable artifact, install/relaunch), ledger platform and variant records

- **Owner:** Claude · **Group:** R · **Stage:** 38 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p6-build-bench-targets`
- **Depends on:** [CL-R-23](#cl-r-23); ext:platforms-p1-target-spec and platforms-p1-native-plan-toolchain (Stage 24) → [CL-P1-06](#cl-p1-06), [CL-P1-11](#cl-p1-11), [CL-P1-12](#cl-p1-12); ext:btrsmith-cross-target-build (Stage 28) → [CL-P2-16](#cl-p2-16)
- **Why not now:** Needs the Stage 24 target rows and BTRSmith cross-target builds; budget_bench is held by CL-R-23.
- **Parallel-safe with:** CL-R-39

**Owned paths**

- tools/budget_bench.py
- tools/bench/targets/__init__.py (TargetDriver interface, new)
- tools/bench/targets/host.py (new)
- tools/qualification/adapters.py (BudgetBenchAdapter platform and variant)
- src/tests/python/test_budget_bench.py

**Must not touch**

- tools/bench/targets/windows.py, ios.py, android.py (CX-R-11)
- `src/compiler/**`

**Steps**

1. TargetDriver interface: build-driver command, artifact path, install, relaunch, variant (arm64-simulator, ...).
2. Scenarios matching the P6 table: cold dev package, private-body edit to installable artifact, no-op through the real driver, install/relaunch, cold reference package, reference edit.
3. Add a host adapter; record each variant separately in the ledger.

**Acceptance**

- [ ] test_budget_bench.py, with a fake TargetDriver, passes
- [ ] The host-adapter dry run emits records accepted by `python3 -m tools.qualification ingest --budget-bench`
- [ ] Interface documented for CX-R-11

**Risks**

- budget_bench hotspot; sequence after CL-R-22's edit.

#### Stage 39: P5 journeys on installed products and the macOS MVP closure

<a id="cl-r-47"></a>

##### CL-R-47 · BTRSmith self-host matrix: full suite through selfhost on Linux CI, macOS cells via the Mac preset, paired fixes for compiler-caused failures

- **Owner:** Claude · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-q-selfhost-matrix`
- **Depends on:** [CL-R-22](#cl-r-22); [CL-R-37](#cl-r-37); `ext:btrsmith-ui-slice*` (Stage 36) → CX-UIB-66…76
- **Why not now:** Needs D16's selfhost default (CL-R-22), BTRSmith CI (CL-R-37) and the Stage 36 UI slices.
- **Parallel-safe with:** CX-R-08

**Owned paths**

- btrsmith:.github/workflows/ci.yml (selfhost matrix job)
- tools/runbook/presets/btrsmith-selfhost-matrix.toml
- `src/compiler/**` fixes as paired commits only when a failure is a compiler defect

**Must not touch**

- `btrsmith:src/**` (product failures go to their owner packets)

**Steps**

1. Matrix: selfhost × {dev, release} × {clang, gcc} on Linux; macOS GUI cells through the preset run in MAC-R-10.
2. Triage each failure as compiler or product; land paired compiler fixes.

**Acceptance**

- [ ] Linux matrix green; macOS cells green in MAC-R-10
- [ ] No remaining failure attributed to the frontend

**Risks**

- Selfhost-only defects need bootstrap reruns.

#### Stage 42: P7 release engineering

<a id="cl-r-41"></a>

##### CL-R-41 · P7 sanitizer matrix on desktop targets (Linux, macOS, Windows) and the sanitizer omissions table

- **Owner:** Claude · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p7-sanitizers`
- **Depends on:** [CL-R-38](#cl-r-38); ext:qualification-p5-journey-drivers (Stage 37) → CX-UIB-77…82
- **Why not now:** Stage 42 (P7) follows the platform and product milestones; journeys come from Stage 37.
- **Parallel-safe with:** CL-R-43, CL-R-44

**Owned paths**

- src/tests/python/test_sanitizer_matrix.py (new)
- tools/qualification/sanitizers.toml (new)
- docs/qualification/sanitizers.md (new omissions table)
- ci/tiers.toml (sanitizer fragment)

**Must not touch**

- `src/runtime/c/**` (defects become their own paired commits)
- flake.nix (request tools from the nix owner)

**Steps**

1. Linux gcc and clang: ASan+UBSan, TSan, LSan; clang MSan, with uninstrumented-libc omissions noted.
2. macOS clang: ASan+UBSan and TSan; no LSan on arm64 is an omission.
3. Windows MinGW via zig: UBSan in trap mode; ASan an omission unless the MSVC row exists.
4. Run corpus subsets, the stdlib stress and the journeys under each. Never beside a bootstrap on the Mac.
5. Write the omissions table from sanitizers.toml.

**Acceptance**

- [ ] Every target × toolchain × sanitizer cell is passed or listed as an omission with its reason in docs/qualification/sanitizers.md
- [ ] Sanitizer tier green on CI (run ids reported)

**Risks**

- Sanitizers will surface latent runtime defects; budget paired fix commits.

<a id="cl-r-42"></a>

##### CL-R-42 · P7 sanitizers on mobile: iOS simulator ASan/TSan and Android emulator ASan/HWASan, added to the omissions table

- **Owner:** Claude · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p7-sanitizers`
- **Depends on:** [CL-R-41](#cl-r-41); ext:platforms-p1-host-ios and platforms-p1-host-android (Stage 25) → [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** Needs the iOS and Android test hosts (Stage 25).
- **Parallel-safe with:** CL-R-43

**Owned paths**

- tools/qualification/sanitizers.toml
- docs/qualification/sanitizers.md
- src/tests/python/test_sanitizer_matrix.py

**Must not touch**

- `src/runtime/c/**`

**Steps**

1. iOS simulator runs on macOS runners (stand-in Xcode; the pinned-Xcode runs ride MAC-R-15).
2. Android x86_64 emulator ASan on Linux KVM runners; HWASan on arm64 is noted as needing a device.
3. Add the rows to the omissions table.

**Acceptance**

- [ ] Mobile rows present: passed or omission with reason
- [ ] CI run ids reported

**Risks**

- HWASan needs arm64 hardware; recorded as awaiting hardware.

<a id="cl-r-43"></a>

##### CL-R-43 · P7 devtools interface: target-aware DAP launch/attach contract, crash symbolication to .btrc, LSP target-aware imports (Linux/macOS reference)

- **Owner:** Claude · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p7-devtools-targets`; `tooling-target-debuggers`
- **Depends on:** ext:platforms-p1-target-spec (Stage 24, includes the btrc.target LSP setting) → [CL-P1-06](#cl-p1-06); ext:platforms-p1-host-windows, host-ios, host-android (Stage 25) → [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** Needs the Stage 24 target contract and the Stage 25 test hosts.
- **Parallel-safe with:** CL-R-41, CL-R-44

**Owned paths**

- `src/devex/debug/toolchain/**`
- `src/devex/debug/backend/**`
- src/devex/debug/protocol/adapter.py
- src/devex/debug/targets/__init__.py (interface only)
- docs/design/debugger.md
- src/tests/debug/test_target_launch.py (new)

**Must not touch**

- src/devex/debug/targets/windows.py, ios.py, android.py (CX-R-13)
- src/devex/lsp/catalog/generated.py

**Steps**

1. Define TargetDebugSession: local launch; remote attach through lldb gdb-remote, debugserver or lldb-server.
2. Symbolicate crash stacks to .btrc frames through #line and DWARF.
3. Make LSP imports target-aware through btrc.target.
4. Reference implementations for macOS and Linux.

**Acceptance**

- [ ] A .btrc breakpoint hits on macOS (draft-PR macos.yml unit shard with developer mode) and on Linux
- [ ] A deliberate crash in a corpus program symbolicates to its .btrc line
- [ ] test_dap_session.py and test_target_launch.py pass

**Risks**

- Linux CI has no lldb (expected-skip lldb-missing); Linux proof needs gdb or the Mac.

<a id="cl-r-44"></a>

##### CL-R-44 · P7 release artifacts, compiler half: byte-reproducible unsigned btrcc bundles, symbols, license notices, checksums

- **Owner:** Claude · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p7-release-artifacts`
- **Depends on:** [CL-R-38](#cl-r-38); ext:platforms-w1-ci-and-bundle (Stage 27) → [CL-P2-15](#cl-p2-15), [CX-P2-18](codex.md#cx-p2-18)
- **Why not now:** Stage 42; the Windows bundle lane (Stage 27) must exist.
- **Parallel-safe with:** CL-R-41, CL-R-43

**Owned paths**

- Makefile (btrcc-dist reproducibility flags)
- .github/workflows/release.yml (artifact job)
- tools/qualification/reproducibility.py (new)
- docs/qualification/release-artifacts.md (new)
- LICENSES/third-party notices (new)

**Must not touch**

- `src/compiler/**`
- `btrsmith:**` (CX-R-14)

**Steps**

1. SOURCE_DATE_EPOCH, -ffile-prefix-map, sorted tar and fixed gzip mtime for every btrcc-dist bundle.
2. Build twice on separate runners and compare; split symbols.
3. Third-party notices: wgpu-native, FreeType, zig MinGW, and mimalloc if adopted. Add sha256 files.

**Acceptance**

- [ ] The release dispatch builds each bundle twice; `cmp` is identical for all five
- [ ] Checksums and notices present in each archive

**Risks**

- macOS archives embed UUIDs; deterministic linking flags needed.

#### Stage 43: Final platform exits and the release candidate

<a id="cl-r-45"></a>

##### CL-R-45 · Final W2, I2 and A2 platform exit reports from the ledger (equivalent, adapted, restricted, missing; physical rows awaiting)

- **Owner:** Claude · **Group:** R · **Stage:** 43 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `qualification-final-w2-exit`; `qualification-final-i2-exit`; `qualification-final-a2-exit`
- **Depends on:** [CX-R-09](codex.md#cx-r-09); [CX-R-10](codex.md#cx-r-10); [CX-R-12](codex.md#cx-r-12); [CX-R-16](codex.md#cx-r-16); [CX-R-17](codex.md#cx-r-17); [CX-R-18](codex.md#cx-r-18); [CX-R-19](codex.md#cx-r-19); [CX-R-20](codex.md#cx-r-20); [MAC-R-11](owner.md#mac-r-11); [MAC-R-14](owner.md#mac-r-14); [MAC-R-15](owner.md#mac-r-15)
- **Why not now:** Needs the Stage 39-42 evidence.
- **Parallel-safe with:** CX-R-21

**Owned paths**

- tools/qualification/report.py
- docs/qualification/exits/{windows,ios,android}.md (new)

**Must not touch**

- `src/**`

**Steps**

1. Compose per-platform exit reports from the ledger against the frozen denominators.
2. Physical-device rows unavailable under D8 stay unfinished gates.

**Acceptance**

- [ ] `python3 -m tools.qualification report --denominators` passes with every slot classified
- [ ] Exit docs list missing and restricted counts explicitly

**Risks**

- Missing physical evidence must stay visible, never counted as passed.

<a id="cl-r-46"></a>

##### CL-R-46 · Release-candidate coordinator: freeze SHAs and package set, run every tier, aggregate one ledger bundle and coverage report, restart on any fix (plus the rc-mac preset)

- **Owner:** Claude · **Group:** R · **Stage:** 43 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p7-release-candidate-run`
- **Depends on:** [CL-R-45](#cl-r-45); [CL-R-39](#cl-r-39); [CL-R-41](#cl-r-41); [CL-R-42](#cl-r-42); [CL-R-43](#cl-r-43); [CL-R-44](#cl-r-44); [CX-R-14](codex.md#cx-r-14); [CX-R-21](codex.md#cx-r-21)
- **Why not now:** Needs every Stage 38-42 packet.

**Owned paths**

- tools/runbook/presets/rc-mac.toml
- PLAN.md (bucket-5 row)
- docs/qualification/rc-\<date>.md (new)

**Must not touch**

- anything on the frozen SHAs (any fix restarts the run)

**Steps**

1. Freeze btrc and BTRSmith SHAs and the package set.
2. Dispatch release.yml and BTRSmith release CI.
3. Hand the owner the rc-mac preset (MAC-R-16).
4. Aggregate one ledger bundle plus the coverage report; mark bucket 5 done or list unfinished gates.

**Acceptance**

- [ ] One ledger bundle with every required gate on the same frozen SHAs and package set
- [ ] Coverage report of equivalent, adapted, restricted and missing items
- [ ] PLAN.md bucket 5 marked done, or unfinished gates named

**Risks**

- Any fix restarts the run; budget several attempts.
