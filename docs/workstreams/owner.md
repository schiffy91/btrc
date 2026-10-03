# WORKSTREAMS packets: owner (Mac, devices, accounts)

Part of [WORKSTREAMS.md](../../WORKSTREAMS.md), the shared plan for Claude, Codex and the owner. That file holds the purpose, decision D27, the coordination protocol, the assignment matrix, the timeline and the open questions; this file holds the owner (Mac, devices, accounts) packets in full. `packets.json` beside it is the same packet set in machine-readable form.


Grouped by owner, then by stage (the first stage a packet's `plan_stage` names), then by group and number. Owned paths, steps, acceptance and risks are the analysts' text, escaped for Markdown only. Changes are marked **Writer note** (listed in §9) or **Review change** (listed in §10); where the two differ, the review change wins.

### 6.3 Owner packets

Owner: each packet is one command, or a short fixed sequence, prepared by the packet that builds its wrapper (§3.12). Paste the summary into the Claude session, or let the runbook push it; Claude does the rest. Rows that need hardware or accounts that do not exist stay **awaiting hardware/account** (D8). Each packet shows two figures: **Estimate** is the owner's attended time; **Mac wall** is how long the Mac (or the owner host the packet names) is occupied, with **Overnights** counted separately. The Mac is the bottleneck, so plan by Mac wall (estimates, §10).

#### Stage 4: Structure-first drift review, native-migration audit, BTRSmith pin bump

<a id="mac-r-01"></a>

##### MAC-R-01 · Stage 4 BTRSmith requalification at the new pin, then fast-forward BTRSmith main (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 4 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 5 h
- **PLAN items:** `btrsmith-pin-bump`
- **Depends on:** [CL-R-01](claude.md#cl-r-01); [CL-R-02](claude.md#cl-r-02)
- **Why not now:** Needs the pin-bump branch (CL-R-01) and the stage4-requal preset (CL-R-02).
- **Parallel-safe with:** CL-R-04, CL-R-05, CL-R-23, CL-R-36

> **Writer note:** **Owner Session 1** (§5.3). Run on a `main` that contains `CL-C-01`; this one gate run also serves as `MAC-C-01`. Add the Stage 15 BTRSmith peak and instructions A/B cell (the preset's optional cell, §7 Q43).

> **Review change:** Serves `MAC-C-01` only; `MAC-P1-01` waits for C4 (§10 P11).

**Owned paths**

- ~/.cache/btrc/clones/stage4-requal (local)
- ~/.cache/btrsmith/clones/stage4-requal (local)
- btrsmith:main (fast-forward push only)
- btrc:evidence/stage4-requal-\<date> (branch)

**Must not touch**

- btrc main (no push from this packet)
- the Google Drive checkouts
- system settings

**Steps**

1. Preconditions:
   - no other agent, gate or guest running;
   - `df -h ~` shows at least 80 GB free;
   - the 1Password SSH agent is unlocked for the final push.
2. Run `tools/runbook/run.sh stage4-requal --btrsmith-branch stage4/pin-bump` from a hub clone. Wall time is about 4-5 h. It runs:
   - the D5 batch gate, including application-frontend-check and the library smoke on both frontends;
   - release-check on each frontend, serially;
   - the qualifying-column diff;
   - optionally the Stage 15 BTRSmith peak/instructions A/B.
3. On green, the runbook fast-forwards and pushes BTRSmith main (D4) and pushes the evidence summary. On red, main stays untouched and the summary names the failures for CL-R-01.

**Acceptance**

- [ ] summary.txt shows exit=0 for diff-check, lint, format-check, generated-check, extension, test, bootstrap and test-c11
- [ ] application-frontend-check exits 0 on both frontends with byte-identical link plans
- [ ] btrsmith-library-smoke passes on both frontends
- [ ] release-check failures are a subset of the Stage 2 qualifying column (05ec9cb), with no new failure
- [ ] BTRSmith main pushed at the new pin; evidence/stage4-requal-\<date> pushed

**Risks**

- GUI release-check tests flake under load; the runbook reruns a failed GUI target once.
- Owner presence is needed for the SSH push.

#### Stage 5: Quiet baseline measurement round

<a id="mac-r-02"></a>

##### MAC-R-02 · Stage 5 quiet baseline measurement round, overnight (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 5 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 10 h · **Overnights:** 1
- **PLAN items:** `perf-baseline-round`
- **Depends on:** [MAC-R-01](#mac-r-01); [CL-R-02](claude.md#cl-r-02)
- **Why not now:** Stage 5 needs the post-Stage-4 BTRSmith pin (MAC-R-01) and the stage5 preset (CL-R-02).

**Owned paths**

- ~/.cache/btrc/bench.noindex/stage5-\<date> (local)
- ~/.cache/btrc/bench/stage5-\<date> (raw logs)
- btrc:evidence/stage5-\<date> (branch)

**Must not touch**

- system settings (Spotlight, Time Machine)
- any other agent, build or guest during the round

**Steps**

1. In the evening, stop the podman machine (`podman machine stop`) and stop agent sessions on the Mac.
2. Run `tools/runbook/run.sh stage5`. It waits for the 60 s quiet check, measures overnight, and resumes if the same command is rerun after an interruption.
3. In the morning, confirm the runbook pushed evidence/stage5-\<date>; no further action is needed.

**Acceptance**

- [ ] 5 cold and 20 incremental samples, with median, p95 and max, for every scenario × frontend × pin (aeeca0fd and the post-Stage-4 pin)
- [ ] Coverage: owner/worker split, cold release on both frontends, all reference scenarios, interface and instance edits, product-Make no-op, module-unit ≤110% of whole-program, self-compile and full-corpus wall/RSS, 1/2/4/8-worker sweep with peak RSS
- [ ] Provenance names the clang -O2 btrcc, the SHAs and the host string; raw logs under ~/.cache/btrc/bench/stage5-\<date>
- [ ] Any M11 budget the new pin misses is listed in summary.json

**Risks**

- The quiet check may never pass with Drive syncing; overnight retry is built in, but the owner may need to pause Drive by hand (agents never change settings).
- Disk: a full round plus two BTRSmith copies is about 20 GB.

#### Stage 6: Edit-floor spikes, Stage B key and journal spec, reference attribution, native track I

<a id="mac-r-03"></a>

##### MAC-R-03 · Stage 6 Mac measurements: spike instruction A/B, reference cProfile, native no-op and edit, composed-spike quiet run (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 6 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 10 h · **Overnights:** 1
- **PLAN items:** `perf-floor-spikes`; `perf-ref-attribution`; `perf-signing-attest`; `perf-native-receipts`
- **Depends on:** [MAC-R-02](#mac-r-02); [CL-R-05](claude.md#cl-r-05); [CL-R-06](claude.md#cl-r-06); [CL-R-07](claude.md#cl-r-07)
- **Why not now:** Needs the Stage 5 baseline and the three Stage 6 presets.

**Owned paths**

- ~/.cache/btrc/bench.noindex/stage6-\<date> (local)
- btrc:evidence/stage6-\<date> (branch)

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh stage6-spikes stage6-reference stage6-native`.
2. Instruction cells (--jobs 1) tolerate light load. The composed-spike wall-clock cell waits for the quiet check, so leave the Mac idle overnight.

**Acceptance**

- [ ] Per-lever instructions-retired JSON for 5 spikes plus the composed branch × 3 edit fixtures
- [ ] Reference cProfile JSON for cold and edit builds
- [ ] Product no-op shows 0 links and 0 signings; native edit-step distribution reported against ≤1.4 s
- [ ] One quiet composed-spike wall-clock run; evidence branch pushed

**Risks**

- Building six btrcc variants under the two-slot semaphore takes hours; it is resumable.

#### Stage 7: Correctness nets, M10 pool qualification, first cold-path cuts

<a id="mac-r-04"></a>

##### MAC-R-04 · Stage 7 Mac measurements: setjmp, M8a, mimalloc, M10 worker table, determinism tier, BTRSmith portable-coverage GUI runs (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 7 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 10 h · **Overnights:** 1
- **PLAN items:** `perf-setjmp-barriers`; `perf-generic-temporaries`; `perf-mimalloc`; `perf-m10-pool-qualification`; `perf-m11-acceptance`; `btrsmith-portable-coverage`
- **Depends on:** [CL-R-10](claude.md#cl-r-10); [CL-R-11](claude.md#cl-r-11); [CL-R-12](claude.md#cl-r-12); [CL-R-13](claude.md#cl-r-13); [CL-R-14](claude.md#cl-r-14); [CX-R-22](codex.md#cx-r-22)
- **Why not now:** Needs the Stage 7 lanes and their presets.

**Owned paths**

- ~/.cache/btrc/bench.noindex/stage7-\<date> (local)
- btrc:evidence/stage7-\<date> (branch)

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh stage7-setjmp stage7-m8a stage7-mimalloc stage7-m10 stage7-determinism stage7-btrsmith-portable`. Instruction cells run first; quiet wall-clock cells wait for the quiet check overnight; GUI cells take the gui-capture lock.
2. Supply BTRSmith's private real-song fixtures for the PortableCoverage runs: the copied catalog, the configuration and the chart with the 5:20 passage. The preset's environment block names them.

**Acceptance**

- [ ] u-solve ≥40% faster at 4 workers
- [ ] M8a: ≥50% fewer empty child-container allocations, self-host peak ≤3 GiB, cold transpile ≤40 s, or a recorded revision
- [ ] mimalloc instruction table plus quiet wall/RSS, enough to decide D15
- [ ] M10: 1/2/4/8 worker table with peak RSS, ≥1.5× at 4 workers or a revised default, lock wait/hold counts
- [ ] Determinism tier green on the Mac; every PortableCoverage.md row run on both frontends

**Risks**

- GUI and GPU runs need an unlocked desktop session and the real media fixtures.

#### Stage 8: Reference compiler M11 budgets (Python track)

<a id="mac-r-05"></a>

##### MAC-R-05 · Stage 8 reference-compiler measurements on the Mac (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 8 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 8 h · **Overnights:** 1
- **PLAN items:** `perf-ref-frontend-cache`; `perf-ref-stageb`; `perf-ref-cold`
- **Depends on:** [CL-R-15](claude.md#cl-r-15); [CL-R-16](claude.md#cl-r-16); [CL-R-17](claude.md#cl-r-17)
- **Why not now:** Needs the Stage 8 lanes merged.

**Owned paths**

- ~/.cache/btrc/bench.noindex/stage8-\<date> (local)
- btrc:evidence/stage8-\<date> (branch)

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh stage8-reference` overnight; it includes BTRSmith verify mode.

**Acceptance**

- [ ] Lex+parse ≤3 s per edit with identical canonical renders
- [ ] Edit ≤15 s median and ≤20 s p95; cold transpile ≤180 s; cold dev ≤210 s; peak ≤2 GiB
- [ ] 1/2/4 worker table; verify mode passes on BTRSmith
- [ ] Distances to the reference finals recorded

**Risks**

- Python startup and GC variance; quiet runs only.

#### Stage 9: Stage B completion and M11 closure on the Mac

<a id="mac-r-06"></a>

##### MAC-R-06 · Stage 9 M11 acceptance on the Mac: Stage B counter, batch, cold release, product-Make, BTRSmith requalification, dev-mode pin (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 9 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 10 h · **Overnights:** 1
- **PLAN items:** `perf-stageb-slice4`; `perf-stageb-skip-unchanged`; `perf-batch-10`; `btrsmith-test-batch`; `perf-cold-release`; `perf-product-integration`; `btrsmith-dev-mode`
- **Depends on:** [CL-R-22](claude.md#cl-r-22)
- **Why not now:** Needs every Stage 9 lane and the stage9-acceptance preset.

**Owned paths**

- ~/.cache/btrc/bench.noindex/stage9-\<date> (local)
- btrc:evidence/stage9-\<date>
- btrsmith:main (dev-mode pin push)

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh stage9-acceptance` overnight. It ends with the BTRSmith requalification and, on green, pushes the dev-mode pin (needs the SSH agent).

**Acceptance**

- [ ] Stage B counter met for every fixture in both compilers; interface edit ≤110% of a clean build; instance edit relowers only the edited and template groups
- [ ] Batch ≤60 s self-host and ≤120 s reference; cold release ≤90 s within the guardrail
- [ ] Product-Make medians within 5% of budget_bench; dev and release suites green without a clean
- [ ] Every M11 KPI row met on the Mac; BTRSmith requalification green

**Risks**

- A missed KPI loops back to its lane under D11's stopping rule.

#### Stage 10: x86_64 NixOS acceptance host (remote lane, starts whenever the host exists)

<a id="mac-r-07"></a>

##### MAC-R-07 · Stage 10 owner actions: probe FRACTAL-NORTH, register the BTRSmith runner if it qualifies, add the read-only BTRSmith token secret

- **Owner:** Owner · **Group:** R · **Stage:** 10 · **Environment:** Device or account (owner) · **Start now:** yes · **Estimate:** 0.5 agent-hours · **Mac wall:** 0.5 h
- **PLAN items:** `tooling-x86-acceptance-host`; `qualification-acceptance-hosts`
- **Depends on:** none
- **Parallel-safe with:** MAC-R-01

> **Review change:** Its optional btrc token step contradicted §7 Q28 and is dropped (§10 X1).

**Owned paths**

- btrsmith repository settings (self-hosted runner)
- btrc repository secrets (BTRSMITH_READ_TOKEN)

**Must not touch**

- agents never handle the token value

**Steps**

1. From the Mac's LAN run `ssh FRACTAL-NORTH.local 'nproc; free -g; lscpu; nix --version'` (the verify line in docs/qualification/devices.toml) and paste the output to the integrator.
2. If it shows ≥16 logical CPUs and ≥16 GiB, register it as a BTRSmith self-hosted runner with label nixos-x86-acceptance (approved by D7).
3. Skip the BTRSmith token for btrc: per §7 Q28 no BTRSmith token goes into the public btrc repository; the x86_64 BTRSmith measurement runs in BTRSmith's own CI (CL-R-37).

**Acceptance**

- [ ] Probe output recorded; the integrator updates the devices.toml linux-fractal-north row and PLAN.md
- [ ] Runner online in BTRSmith settings, if the host qualifies

**Risks**

- The host is gone, so D7's fallback governs.

#### Stage 11: Bounded final push A, the edit path (D11)

<a id="mac-r-08"></a>

##### MAC-R-08 · Stage 11/12 quiet re-measure after each batch, and the Stage 12 serial profile (one command each)

- **Owner:** Owner · **Group:** R · **Stage:** 11 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 50 h · **Overnights:** 5
- **PLAN items:** `perf-records-pack`; `perf-frontend-durable`; `perf-decl-session-cache`; `perf-parse-cache`; `perf-native-link`; `perf-cold-native`; `perf-resident-compiler`; `perf-decl-lowering-hotspots`
- **Depends on:** [CL-R-24](claude.md#cl-r-24)
- **Why not now:** Needs the Stage 11 presets (CL-R-24) and each lane's merge.

> **Review change:** Mac wall assumes about five Stage 11/12 batches, one quiet overnight each (§10 F18).

**Owned paths**

- `~/.cache/btrc/bench.noindex/stage11-*/` (local)
- `btrc:evidence/stage11-*`, `evidence/stage12-profile-*`

**Must not touch**

- system settings

**Steps**

1. After each Stage 11 merge batch run `tools/runbook/run.sh stage11-remeasure` overnight.
2. Once Lane Q drains run `tools/runbook/run.sh stage12-profile` (serial profile).

**Acceptance**

- [ ] Per batch: records plus g-transitive ≤0.4 s; visibility plus n-import ≤0.15 s; no-op ≤1.0 s; declarations session ≤0.2 s; lex+parse ≤0.3 s or no-go; all `a-*/g-*/v-*/c-*/r-*` phases ≤0.5 s; edit link ≤0.2 s; cold native ≤8 s
- [ ] Stage 12 profile captured with instruction attribution for the five named hotspots

**Risks**

- Several overnight rounds; each one is resumable.

#### Stage 13: Bucket-1 exit qualification

<a id="mac-r-09"></a>

##### MAC-R-09 · Stage 13 bucket-1 exit on the Mac: full D5 gate chain on the final SHA, Mac test-c11, determinism tier, final quiet tables, BTRSmith checks (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 13 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 12 h · **Overnights:** 1
- **PLAN items:** `perf-final-qualification`
- **Depends on:** [CL-R-30](claude.md#cl-r-30); [CL-R-31](claude.md#cl-r-31); [CL-R-32](claude.md#cl-r-32); [CL-R-27](claude.md#cl-r-27); [CL-R-28](claude.md#cl-r-28); [CL-R-29](claude.md#cl-r-29)
- **Why not now:** Needs every Stage 11-12 lane closed or declined.

**Owned paths**

- ~/.cache/btrc/gates/stage13 (local)
- btrc:evidence/stage13-\<date>

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh stage13-final`. The gate chain runs strictly in sequence, then the final quiet scenarios overnight.

**Acceptance**

- [ ] Full D5 list green on the final SHA, including Mac test-c11 (8 configurations) and the determinism tier
- [ ] Every D11 row measured: self-host and reference finals, M8a, M10 table
- [ ] Self-compile and corpus median wall/RSS within 5% of Stage 5, or an explained tradeoff
- [ ] BTRSmith application-frontend-check and library smoke pass on both frontends

**Risks**

- Any red step restarts the chain.

#### Stage 16: C1 constructs, then C4 (approved, D19)

<a id="mac-c-01"></a>

##### MAC-C-01 · Owner Mac: Stage 16 C1 checkpoint (Darwin 8-cell test-c11, Mac make test/bootstrap, BTRSmith rerun)

- **Owner:** Owner · **Group:** C · **Stage:** Stage 16 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 0.5 agent-hours · **Mac wall:** 4.5 h
- **PLAN items:** `ccompat-c1-integrate` (Mac exit: batch gate plus BTRSmith rerun); `btrsmith-c-compat-regression` (rerun after Stage 16 C1)
- **Depends on:** [CL-C-01](claude.md#cl-c-01)
- **Why not now:** Runs on main after CL-C-01 is integrated and pushed; needs the owner's Mac (BTRSmith is private and macOS-only; full Darwin test-c11 with nix gcc).
- **Parallel-safe with:** CL-C-03, CL-C-04, CL-C-02

> **Writer note:** Satisfied by owner Session 1 (`MAC-R-01`'s gate) when that gate runs on a `main` containing `CL-C-01` (§9 item 12). Run it separately only if Session 1 happens before `CL-C-01` merges.

**Owned paths**

- ~/.cache/btrc/evidence/stage16-c1/ (outside the repo)

**Must not touch**

- any tracked file (evidence only; the integrator writes PLAN.md)

**Steps**

1. Check free disk ≥80 GB. Clone outside Drive: cd ~/.cache/btrc/clones/gate && git fetch origin && git checkout --detach origin/main. BTRSmith clone at ~/.cache/btrsmith/clones/gate on its main.
2. One command: ~/.cache/btrc/tools/withlock.sh gate tools/bench/scripts/batch_gate.sh ~/.cache/btrc/clones/gate ~/.cache/btrc/evidence/stage16-c1 \<pre-C1 base sha> ~/.cache/btrsmith/clones/gate
3. Paste ~/.cache/btrc/evidence/stage16-c1/summary.txt into the Claude session; the integrator records it in PLAN.md's Stage 16 entry.

**Acceptance**

- [ ] summary.txt result=GREEN: make test, make bootstrap, make test-c11 (8 configurations passed), lint, format-check, generated-check, extension
- [ ] BTRSmith bsm-frontend-check and bsm-library-smoke-{reference,selfhost} pass, or fail only on entries already in the Stage 2 BTRSmith baseline ledger; any new failure goes back to CL-C-01's owner

**Risks**

- About 2.5 h wall with the gate lock; nothing heavy may run beside it (AGENTS.md load rules).
- A BTRSmith clone grows to ~7.8 GB; batch_gate.sh removes build/tests afterwards.

<a id="mac-c-02"></a>

##### MAC-C-02 · Owner Mac: C4 checkpoint (BTRSmith --jobs 1 instructions/peak A/B, quiet M11 re-measure, gate with BTRSmith)

- **Owner:** Owner · **Group:** C · **Stage:** Stage 16 (C4 exit) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 8 h · **Overnights:** 1
- **PLAN items:** `ccompat-r18-preprocessor-conditionals` (step 4: quiet M11 re-measure and Mac memory row); `btrsmith-c-compatibility-regression` placeholder: btrsmith-c-compat-regression (rerun after Stage 16)
- **Depends on:** [CL-C-06](claude.md#cl-c-06); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Needs the C4 commit on main (CL-C-06) and, for the one-command form, the checkpoint script (CX-C-01).

**Owned paths**

- ~/.cache/btrc/bench.noindex/ccompat/stage16-c4/ (outside the repo)

**Must not touch**

- any tracked file

**Steps**

1. Quiet machine per the standing approvals (no agents, guests or builds; podman stopped; Time Machine idle; Drive/mds under 5% CPU).
2. One command: tools/bench/scripts/ccompat_checkpoint.sh --parent \<C4 parent sha> --commit \<C4 sha> --memory --budget noop,edit --gate --btrsmith ~/.cache/btrsmith/clones/gate --logdir ~/.cache/btrc/bench.noindex/ccompat/stage16-c4
3. Fallback without CX-C-01: build both btrccs with withlock.sh btrcc-build tools/bench/scripts/build_btrcc.sh; run tools/bench/scripts/instr.sh three times alternately for each under withlock.sh bench; run tools/bench/scripts/bench.sh with --scenarios noop,edit for --frontend selfhost and reference; then batch_gate.sh as in MAC-C-01.
4. Paste the JSON summary and summary.txt into the session.

**Acceptance**

- [ ] Instructions retired and peak footprint at --jobs 1 within 0.3% of the parent (≤1% accepted and recorded); the summary names Apple clang as the btrcc C compiler
- [ ] budget_bench no-op and edit medians show no regression against the last recorded M11 numbers, on both frontends
- [ ] Gate GREEN including BTRSmith frontend check and library smoke on both frontends

**Risks**

- Quiet windows are scarce; the instructions/peak half is load-insensitive and may run first if the quiet check keeps failing.

#### Stage 17: C2 aggregates

<a id="mac-c-03"></a>

##### MAC-C-03 · Owner Mac: C2 schema memory row (BTRSmith --jobs 1 instructions retired and peak footprint, parent vs schema commit)

- **Owner:** Owner · **Group:** C · **Stage:** Stage 17 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 0.3 agent-hours · **Mac wall:** 1.5 h
- **PLAN items:** `ccompat-c2-schema` (Mac memory evidence)
- **Depends on:** [CL-C-07](claude.md#cl-c-07); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Needs the C2 schema commit on main and the owner's Mac.
- **Parallel-safe with:** CL-C-08

**Owned paths**

- ~/.cache/btrc/bench.noindex/ccompat/c2-schema/

**Must not touch**

- any tracked file

**Steps**

1. One command: tools/bench/scripts/ccompat_checkpoint.sh --parent \<schema parent sha> --commit \<schema sha> --memory --logdir ~/.cache/btrc/bench.noindex/ccompat/c2-schema (fallback: build_btrcc.sh twice plus instr.sh three times alternately under withlock.sh bench).
2. Paste the JSON summary into the session.

**Acceptance**

- [ ] Instructions retired and peak footprint within 0.3% (≤1% accepted and recorded); above 1% the integrator applies D17 or optimizes before the C2 lanes fork

**Risks**

- Load-insensitive counters, so no quiet window is needed; still take the bench lock.

<a id="mac-c-04"></a>

##### MAC-C-04 · Owner Mac: Stage 17 exit (C2 memory row, Darwin test-c11, BTRSmith rerun)

- **Owner:** Owner · **Group:** C · **Stage:** Stage 17 (exit) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `ccompat-c2-integrate` (Mac memory row and BTRSmith rerun); `btrsmith-c-compat-regression` (rerun after Stage 17)
- **Depends on:** [CL-C-16](claude.md#cl-c-16); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Needs c2-integrate pushed and the owner's Mac.
- **Parallel-safe with:** CL-C-17

**Owned paths**

- ~/.cache/btrc/bench.noindex/ccompat/stage17/

**Must not touch**

- any tracked file

**Steps**

1. One command: tools/bench/scripts/ccompat_checkpoint.sh --parent \<CL-C-07 parent sha> --commit \<c2-integrate sha> --memory --gate --btrsmith ~/.cache/btrsmith/clones/gate --logdir ~/.cache/btrc/bench.noindex/ccompat/stage17
2. Paste the JSON summary and summary.txt into the session.

**Acceptance**

- [ ] Instructions retired and peak footprint within 0.3% (≤1% recorded) across all of C2
- [ ] Gate GREEN including 8-cell test-c11 and BTRSmith frontend check plus library smoke on both frontends

**Risks**

- BTRSmith may need tag imports (r09) or rename-table updates (r13); failures go back to the owning C2 packet.

#### Stage 18: Multi-dimensional arrays, alone (approved, D19)

<a id="mac-c-05"></a>

##### MAC-C-05 · Owner Mac: Stage 18 exit gate (Darwin test-c11) plus the C3 vocabulary-commit memory row

- **Owner:** Owner · **Group:** C · **Stage:** Stage 18 exit / Stage 19 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `ccompat-r17-multidimensional-arrays` (Mac test-c11 for an emission batch, D5); `ccompat-c3-schema-vocabulary` (Mac BTRSmith --jobs 1 memory row)
- **Depends on:** [CL-C-23](claude.md#cl-c-23); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Runs once the C3 vocabulary commit is on main (its tree includes all of Stage 18).
- **Parallel-safe with:** CL-C-24

**Owned paths**

- ~/.cache/btrc/bench.noindex/ccompat/c3-vocab/

**Must not touch**

- any tracked file

**Steps**

1. One command: tools/bench/scripts/ccompat_checkpoint.sh --parent \<vocab parent sha> --commit \<vocab sha> --memory --gate --logdir ~/.cache/btrc/bench.noindex/ccompat/c3-vocab (no BTRSmith needed here).
2. Paste the JSON summary and summary.txt.

**Acceptance**

- [ ] Gate GREEN including 8-cell Darwin test-c11
- [ ] Instructions retired and peak footprint within 0.3% (≤1% recorded); otherwise the Python () default fallback in c-vocabulary-specifiers.md 'Memory impact' lands before the lanes fork

**Risks**

- If Stage 18's Darwin cell must be proven before CL-C-23 starts, run the gate-only part right after CL-C-22 instead.

#### Stage 19: C3 vocabulary and specifier lanes

<a id="mac-c-06"></a>

##### MAC-C-06 · Owner Mac: C3 commit B cross-target gate, BTRSmith Windows-target frontend check

- **Owner:** Owner · **Group:** C · **Stage:** Stage 19 (batch 0 exit) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 0.5 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `ccompat-c3-schema-vocabulary` (commit B cross-target gate I-18: BTRSmith's Windows frontend check)
- **Depends on:** [CL-C-26](claude.md#cl-c-26)
- **Why not now:** Needs commit B2 pushed; BTRSmith is private and its frontend check needs the Mac's BTRSmith environment.
- **Parallel-safe with:** CL-C-27, CL-C-28, CL-C-29, CL-C-30

**Owned paths**

- ~/.cache/btrc/evidence/stage19-b/

**Must not touch**

- any tracked file

**Steps**

1. One command (from the BTRSmith clone, btrc overridden to the gate clone): cd ~/.cache/btrsmith/clones/gate && nix develop . --override-input btrc path:$HOME/.cache/btrc/clones/gate --command make application-frontend-check BTRC_TARGET=windows-x86_64 > ~/.cache/btrc/evidence/stage19-b/bsm-windows.log 2>&1; echo rc=$?
2. Paste rc and the log tail into the session.

**Acceptance**

- [ ] rc=0, or failures identical to the same check on the parent of CL-C-25 (no new diagnostic from target widths or layout)

**Risks**

- The exact BTRSmith target variable may differ; CX-C-01's script should wrap it so the command is stable.

<a id="mac-c-07"></a>

##### MAC-C-07 · Owner Mac: r15a batch-3 BTRSmith rerun (D-1 volatile flip) and gate

- **Owner:** Owner · **Group:** C · **Stage:** Stage 19 (batch 3) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 0.5 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `ccompat-r15a-qualifiers-storage-classes` (batch 3 BTRSmith rerun)
- **Depends on:** [CL-C-32](claude.md#cl-c-32); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Needs r15a pushed and the owner's Mac.
- **Parallel-safe with:** CL-C-33

**Owned paths**

- ~/.cache/btrc/evidence/stage19-r15a/

**Must not touch**

- any tracked file

**Steps**

1. One command: tools/bench/scripts/ccompat_checkpoint.sh --commit \<r15a sha> --gate --btrsmith ~/.cache/btrsmith/clones/gate --logdir ~/.cache/btrc/evidence/stage19-r15a (fallback: batch_gate.sh as in MAC-C-01).
2. Paste summary.txt.

**Acceptance**

- [ ] Gate GREEN including BTRSmith frontend check and library smoke on both frontends

**Risks**

- BTRSmith native code passing volatile pointers would now be typed differently; any failure goes back to CL-C-32.

<a id="mac-c-08"></a>

##### MAC-C-08 · Owner Mac: Stage 19+20 exit (C3 memory row, Darwin test-c11, BTRSmith rerun)

- **Owner:** Owner · **Group:** C · **Stage:** Stage 19 / Stage 20 exit · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `ccompat-c3-integrate` (Mac matrix, memory and BTRSmith); `btrsmith-c-compat-regression` (reruns after Stages 19 and 20)
- **Depends on:** [CL-C-37](claude.md#cl-c-37); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Needs c3-integrate pushed and the owner's Mac.
- **Parallel-safe with:** CL-C-38, CL-C-39

**Owned paths**

- ~/.cache/btrc/bench.noindex/ccompat/stage19-20/

**Must not touch**

- any tracked file

**Steps**

1. One command: tools/bench/scripts/ccompat_checkpoint.sh --parent \<CL-C-23 parent sha> --commit \<c3-integrate sha> --memory --gate --btrsmith ~/.cache/btrsmith/clones/gate --logdir ~/.cache/btrc/bench.noindex/ccompat/stage19-20
2. Paste the JSON summary and summary.txt.

**Acceptance**

- [ ] Gate GREEN including 8-cell Darwin test-c11, extension, and BTRSmith frontend check plus library smoke on both frontends
- [ ] Instructions retired and peak footprint within 0.3% (≤1% recorded) across C3 and goto

**Risks**

- BTRSmith may hit new reserved words or the volatile flip; failures go back to the owning C3 packet.

#### Stage 21: C5 close-out

<a id="mac-c-09"></a>

##### MAC-C-09 · Owner Mac: Stage 21 final bucket-2 matrix, BTRSmith final regression, BTRSmith pin bump and push

- **Owner:** Owner · **Group:** C · **Stage:** Stage 21 (exit) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 6 h
- **PLAN items:** `btrsmith-c-compat-regression` (final run and pin); `ccompat-c5-docs-final` (exit: final bucket-2 matrix including the Mac's test-c11)
- **Depends on:** [CL-C-40](claude.md#cl-c-40); [CX-C-01](codex.md#cx-c-01)
- **Why not now:** Needs the final bucket-2 tree pushed and the owner's Mac.

**Owned paths**

- ~/.cache/btrc/evidence/stage21-final/
- BTRSmith flake.lock (btrc input bump) in ~/.cache/btrsmith/clones/gate

**Must not touch**

- btrc tracked files (evidence only)
- BTRSmith files other than flake.lock

**Steps**

1. One command: tools/bench/scripts/ccompat_checkpoint.sh --commit \<final sha> --gate --btrsmith ~/.cache/btrsmith/clones/gate --bump-btrsmith-pin --logdir ~/.cache/btrc/evidence/stage21-final (the script runs the gate, then on GREEN runs nix flake lock --update-input btrc in BTRSmith, re-runs application-frontend-check on the pinned flake, commits unsigned, and pushes BTRSmith main per D4).
2. Paste summary.txt and the BTRSmith commit hash.

**Acceptance**

- [ ] Final bucket-2 matrix GREEN on the Mac: make test, make bootstrap, make test-c11 (8 configurations), lint, format-check, generated-check, extension
- [ ] BTRSmith frontend check and library smoke pass on both frontends with the new pin; BTRSmith main pushed with flake.lock pinning the final btrc commit

**Risks**

- BTRSmith pushes need its own gates green first (D4); if 1Password is locked, commit unsigned per the standing approval.

#### Stage 22: P0 entry, parity inventory, adaptations, toolchain matrix, device registry

<a id="mac-p1-01"></a>

##### MAC-P1-01 · Bucket-3 entry gate on the Mac (full D5 batch gate plus the toolchain probe)

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 22 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 4.5 h
- **PLAN items:** `platforms-p0-entry-baseline`
- **Depends on:** [CL-C-06](claude.md#cl-c-06)
- **Why not now:** The bucket-3 entry baseline runs on the main SHA where Stage 24 starts: after C4 (CL-C-06) under D27's Stage 24 clause, after CL-C-40 if that clause is struck.
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

> **Review change:** No longer folded into owner Session 1: a baseline on a tree with only C1 would be stale when bucket 3 starts. It waits for `CL-C-06` (D27's Stage 24 clause; `CL-C-40` if the owner strikes it) (§10 P11; supersedes §9 item 12 for this packet).

**Owned paths**

- ~/.cache/btrc/gate-clones/stage22-entry (clone of ~/.cache/btrc/hub.git, outside Drive)
- ~/.cache/btrsmith/clones/stage22-entry
- ~/.cache/btrc/roadmap/stage22-entry/\<sha>/ (logs, summary.txt, skip report)

**Must not touch**

- repository files (Claude writes the PLAN progress entry from summary.txt)
- system settings
- any other guest or build while the gate runs

**Steps**

1. At the owner's next Mac session: df -h ~ shows at least 100 GB free (CLAUDE.md, before Stage 23); prune build/test-btrcc to the newest 20 fingerprints.
2. git clone ~/.cache/btrc/hub.git ~/.cache/btrc/gate-clones/stage22-entry at the current main head, and clone BTRSmith from ~/.cache/btrsmith/hub.git.
3. One command: ~/.cache/btrc/tools/withlock.sh gate tools/bench/scripts/batch_gate.sh ~/.cache/btrc/gate-clones/stage22-entry ~/.cache/btrc/roadmap/stage22-entry/\<sha> origin/main ~/.cache/btrsmith/clones/stage22-entry (runs make test, make bootstrap alone, make test-c11, lint, format-check, generated-check, extension, hygiene, git diff --check, then BTRSmith application-frontend-check and the library smoke on both frontends).
4. One command: nix develop --command sh -c 'python3 -m tools.qualification.toolchain; make skip-gate; make qualification-report' > the same log directory.
5. Hand summary.txt, the skip report and the toolchain output to Claude.

**Acceptance**

- [ ] summary.txt: exit=0 for every step, with make test passed/skipped counts, test-c11 8 x N configurations and the bootstrap fixed point
- [ ] Toolchain probe: no mismatch except the expected Stage-23 absences (jdk, android-sdk, adb, the iOS 17 simulator runtime)
- [ ] Skip gate clean
- [ ] PLAN.md Stage 22 progress entry (written by Claude) cites the SHA, the counts and the log path

**Risks**

- Known BTRSmith drifted tests from the Stage 2 baseline: record them, do not fix them here.
- stdlib/Daemon.btrc wall-clock limit under load: batch_gate.sh reruns test-c11 once per D5.
- The gate saturates the Mac: no simulator, emulator or agent build beside it.

#### Stage 23: P1 provisioning (toolchains, simulators, SDK, VM, signing, devices)

<a id="mac-p1-02"></a>

##### MAC-P1-02 · iOS simulator runtimes on the Mac: current and iOS 17, each launching a C11 binary

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 23 · **Environment:** Owner's Mac · **Start now:** yes · **Estimate:** 3 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `tooling-ios-simulator-runtimes`
- **Depends on:** none
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- ~/.cache/btrc/roadmap/stage23-ios-runtimes/ (logs; outside the repo)
- simulator devices btrc-ios-current and btrc-ios-17

**Must not touch**

- repository files (Claude updates the matrix host-facts rows from the report)
- system settings
- running beside a gate or bootstrap

**Steps**

1. Disk: at least 150 GB free or an external SSD (Stage 23 prerequisite); install one runtime at a time (D2).
2. xcodebuild -version must print Build version 27A266a. Run xcodebuild -downloadPlatform iOS for the current runtime, then xcodebuild -downloadPlatform iOS -buildVersion \<newest 17.x>. If Xcode 27 refuses the second, record the exact message as 'uninstallable under Xcode 27' (⚠).
3. xcrun simctl create btrc-ios-current \<iPhone type> \<current runtime>, and btrc-ios-17 on the iOS 17 runtime.
4. One command per runtime: xcrun --sdk iphonesimulator clang -target arm64-apple-ios17.0-simulator -std=c11 -pedantic-errors hello.c -o hello && xcrun simctl spawn btrc-ios-current ./hello; echo $? (and the same for btrc-ios-17). If CX-P1-04 has merged, use python3 -m tools.target_hosts.ios.simhost in both modes instead.
5. Report xcrun simctl list runtimes, the outputs and the exit codes to Claude for the ios-simulator-runtime and ios-17-simulator-runtime host-facts rows.

**Acceptance**

- [ ] The current runtime runs the C11 binary, with stdout and exit status captured
- [ ] iOS 17 runs it too, or is recorded as uninstallable with xcodebuild's message
- [ ] After Claude's matrix update, python3 -m tools.qualification.toolchain shows no mismatch for the iOS rows

**Risks**

- Each runtime download is about 8 GB.
- Xcode 27 may not offer an iOS 17 runtime; simulators older than iOS 18 do not accept keyboard or mouse input under Xcode 27, which limits later UI automation.

<a id="mac-p1-03"></a>

##### MAC-P1-03 · Android SDK and AVDs on the Mac: arm64-v8a API 29, 36 and 16 KiB boot

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 23 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `tooling-android-sdk-ndk` (Mac half: the API 29, current and 16 KiB AVDs boot)
- **Depends on:** [CL-P1-02](claude.md#cl-p1-02)
- **Why not now:** Needs the nix develop .#platforms shell with the pinned SDK, NDK and arm64-v8a system images (CL-P1-02).
- **Parallel-safe with:** CL-P1-03, CL-P1-04, CL-P1-07, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- ~/.cache/btrc/gcroots/platforms (shell GC root)
- AVDs btrc-api29, btrc-api36, btrc-api36-16k
- ~/.cache/btrc/roadmap/stage23-android/ (logs)

**Must not touch**

- repository files (Claude records the host facts)
- more than one emulator at once, or any emulator during bootstrap (RAM rule)

**Steps**

1. Disk check, then nix develop .#platforms --profile ~/.cache/btrc/gcroots/platforms.
2. sdkmanager --list | grep system-images to confirm the three image names in the matrix.
3. avdmanager create avd -n btrc-api29 -k 'system-images;android-29;google_apis;arm64-v8a'; btrc-api36 on 'android-36;google_apis;arm64-v8a'; btrc-api36-16k on 'android-36;google_apis_ps16k;arm64-v8a'.
4. One AVD at a time: emulator -avd \<name> -no-window -no-audio -no-snapshot; adb wait-for-device; poll getprop sys.boot_completed; record adb shell getconf PAGE_SIZE (4096, 4096, 16384) and ro.build.version.sdk.
5. Build hello.c with NDK clang --target=aarch64-linux-android29, adb push it, run it, record stdout and the exit status, kill the emulator.
6. Report to Claude for the matrix host-facts rows.

**Acceptance**

- [ ] All three AVDs boot headless with the expected API levels and page sizes
- [ ] The NDK hello prints and exits 0 on each
- [ ] python3 -m tools.qualification.toolchain run inside .#platforms shows jdk, android-sdk and adb present

**Risks**

- androidenv's arm64-darwin emulator build may not realize; fallback is the SDK cmdline-tools at the pinned versions, recorded as a deviation.
- About 4 GiB RAM per emulator.

<a id="mac-p1-04"></a>

##### MAC-P1-04 · Signing identities, accounts and physical-device records under D8

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 23 · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 1 h
- **PLAN items:** `tooling-apple-signing`; `qualification-signing-accounts`; `tooling-ios-physical-devices`; `tooling-android-physical-devices`
- **Depends on:** [CL-P1-02](claude.md#cl-p1-02)
- **Why not now:** keytool, apksigner and adb come from the nix .#platforms shell (CL-P1-02); the Apple steps also need an owner Mac session.
- **Parallel-safe with:** CL-P1-03, CL-P1-04, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- ~/.android/debug.keystore
- ~/.cache/btrsmith/signing/ (local release keystore; never committed)
- ~/.cache/btrc/roadmap/stage23-signing/ (records)

**Must not touch**

- no account creation and no agreement other than the Android SDK licences (D8)
- no key material in any repository
- system settings; the login keychain only for the release keystore password

**Steps**

1. security find-identity -v -p codesigning: record the count (0 expected).
2. Ad-hoc sign an iOS-simulator .app (CX-P1-04's host bundle, or a wrapped hello) with codesign -s - --force, then codesign --verify --verbose.
3. Device signing needs a development team: record it as unavailable (D8). If the owner chooses to sign in a personal team, that is the owner's action, recorded separately.
4. Inside .#platforms: create the standard debug keystore if absent. Create a local release keystore with keytool -genkeypair -keystore ~/.cache/btrsmith/signing/release.jks -alias btrsmith-release -keyalg RSA -keysize 4096 -validity 10000, storing its password with security add-generic-password -s btrsmith-android-release. Record only the certificate fingerprints.
5. Windows: record 'test-signed with an ephemeral self-signed certificate in CI, or unsigned; no trusted certificate (D8)'.
6. xcrun devicectl list devices and adb devices -l (inside .#platforms): record the result (none expected). The devices.toml rows stay unavailable.
7. Hand the records to Claude for devices.toml/README and the PLAN progress entry.

**Acceptance**

- [ ] The signing record lists Apple identities (or 0), a verified ad-hoc signature, the Android keystore fingerprints (keytool -list) and the Windows policy
- [ ] The device listings are recorded; python3 -m pytest src/tests/python/test_device_registry.py -q passes after Claude's update
- [ ] No key material is committed anywhere

**Risks**

- test_device_registry.py allows only the Mac and ad-hoc signing as available; the local keystore is a record, not a device row.

#### Stage 24: P1 shared target contract

<a id="mac-p1-05"></a>

##### MAC-P1-05 · Stage 24 on the Mac: Apple hosted-availability extractions and the Apple macro oracle

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `platforms-p1-hosted-abi-targets` (macos and ios row extractions); `platforms-p1-target-spec` (Mac-bound checks: Apple clang `TARGET_OS_*` set and TargetConditionals.h)
- **Depends on:** [CL-P1-03](claude.md#cl-p1-03); [CL-P1-07](claude.md#cl-p1-07)
- **Why not now:** Needs the schema-2 rows (CL-P1-03) and tools/hosted_platform.py with its --xcrun mode (CL-P1-07).
- **Parallel-safe with:** CL-P1-04, CL-P1-05, CL-P1-06, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- ~/.cache/btrc/roadmap/hosted-platform/\<sha>/ (fragments for macos-aarch64, macos-x86_64, ios-aarch64, ios-aarch64-simulator)

**Must not touch**

- src/language/hosted_abi.toml (CL-P1-08 commits the fragments)

**Steps**

1. One command: nix develop --command python3 -m tools.hosted_platform --xcrun --target macos-aarch64 --target macos-x86_64 --target ios-aarch64 --target ios-aarch64-simulator --out ~/.cache/btrc/roadmap/hosted-platform/\<sha>/ (each source names the SDK version and Xcode 27A266a).
2. One command: nix develop --command python3 -m pytest src/tests/python/test_target_macro_table.py -q with the Mac-bound cases enabled: Apple clang's `TARGET_OS_*` set equals the rows for the four Apple rows, and the iOS 27.0 SDK's TargetConditionals.h accepts the predefined values.
3. Hand the fragments and the pytest log to Claude.

**Acceptance**

- [ ] Four fragments with non-empty source fields
- [ ] test_target_macro_table.py Apple cases pass on the Mac (log attached)

**Risks**

- Apple SDKs declare newer APIs with API_AVAILABLE rather than hiding them, so the iOS lists are weaker than bionic's (a recorded gap; -Wunguarded-availability covers it).

<a id="mac-p1-06"></a>

##### MAC-P1-06 · Stage 24 sub-batches 2-3 on the Mac: BTRSmith checks, iOS native imports, the iOS cross build and the Apple ABI static compile

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `platforms-p1-native-import-targets` (iOS rows on the Mac); `platforms-p1-native-plan-toolchain` (ios-aarch64-simulator cross build; BTRSmith host-object comparison); `platforms-p1-abi-fixture` (macos and ios static compile under Xcode 27A266a)
- **Depends on:** [CL-P1-09](claude.md#cl-p1-09); [CL-P1-11](claude.md#cl-p1-11); [CL-P1-12](claude.md#cl-p1-12); [CL-P1-13](claude.md#cl-p1-13); [MAC-P1-02](#mac-p1-02)
- **Why not now:** Needs sub-batches 2 and 3 on an integration branch, plus the Mac's simulator runtime (MAC-P1-02).
- **Parallel-safe with:** CL-P1-14, CX-P1-04, CX-P1-05, CX-P1-06

**Owned paths**

- ~/.cache/btrc/roadmap/stage24-mac/\<sha>/ (logs, object comparison)

**Must not touch**

- repository files (Claude records the results)

**Steps**

1. One command: tools/bench/scripts/batch_gate.sh \<clone> \<logdir> origin/main ~/.cache/btrsmith/clones/stage24 --no-c11 restricted to the BTRSmith checks: application-frontend-check and the library smoke on both frontends, at the sub-batch 2 head and at the sub-batch 3 head.
2. Build BTRSmith's macOS objects before and after sub-batch 3 and compare them byte-for-byte, including LC_BUILD_VERSION (otool -l).
3. One command: nix develop --command python3 -m pytest src/tests/btrc/test_native_import_targets.py src/tests/python/test_native_plan_cross.py src/tests/btrc/test_target_abi_fixture.py -q with the Xcode sysroots, so the ios rows run.
4. Run the macOS native suites and make skip-gate with the macos manifest; hand the logs to Claude.

**Acceptance**

- [ ] BTRSmith checks green at both heads; Mac objects identical before and after
- [ ] The ios native-import rows, the ios-aarch64-simulator Mach-O (platform IOSSIMULATOR) and the macos/ios static fixture compile all pass
- [ ] Skip gate clean

**Risks**

- If the Mac is unavailable, sub-batch 3 merges on Linux and CI gates alone; a later red result here triggers D5's revert-bisect.

<a id="mac-p1-07"></a>

##### MAC-P1-07 · Stage 24 exit on the Mac: the iOS native-read cache row and the quiet M11 re-measure

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 24 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 4 agent-hours · **Mac wall:** 8 h · **Overnights:** 1
- **PLAN items:** `platforms-p1-cache-identity` (iOS native-read row and the quiet M11 re-measure)
- **Depends on:** [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the cache-identity commit and a quiet window (the standing-approval automated quiet check).

**Owned paths**

- ~/.cache/btrc/bench.noindex/stage24/ (measurement workspace)
- ~/.cache/btrc/roadmap/stage24-exit/ (results)

**Must not touch**

- system settings
- any agent, build or guest during the measurement

**Steps**

1. One command: nix develop --command python3 -m pytest src/tests/btrc/test_target_cache_identity.py -k ios -q with the Xcode sysroot.
2. Wait for the automated quiet check to pass for 60 s. One command: python3 tools/budget_bench.py with the no-op, edit and cold-transpile scenarios on both frontends at --jobs 1 under /usr/bin/time -l, for btrcc built from the pre-Stage-24 base and from the Stage 24 head, both built by clang through default_c_compiler(). Compare instructions retired and peak footprint.
3. Hand the deltas table to Claude.

**Acceptance**

- [ ] The iOS native-read row passes
- [ ] Deltas within 0.3% (pass) or up to 1% (accepted with the delta recorded), naming the C compiler; PLAN Stage 24 exit entry written by Claude

**Risks**

- Above 1% needs D17 or optimization before Stage 24 closes.

#### Stage 25: P1 test hosts and P2 runtime parity

<a id="mac-p1-08"></a>

##### MAC-P1-08 · Stage 25 Mac device-queue runs: pinned-Xcode iOS simulators and arm64-v8a Android emulators

- **Owner:** Owner · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 6 agent-hours · **Mac wall:** 6 h
- **PLAN items:** `platforms-p2-portable-corpus` (Mac device-queue execution: ios-simulator under Xcode 27A266a, android-arm64 emulators at API 29, 36 and 36 with 16 KiB pages)
- **Depends on:** [CX-P1-08](codex.md#cx-p1-08); [CX-P1-09](codex.md#cx-p1-09); [MAC-P1-02](#mac-p1-02); [MAC-P1-03](#mac-p1-03)
- **Why not now:** Needs the registered iOS and Android executors (CX-P1-08/09) and the Mac's provisioned runtimes and AVDs.

**Owned paths**

- ~/.cache/btrc/target-runs/\<sha>/ (logs, JUnit, ledger records)

**Must not touch**

- repository files
- more than one emulator at once; no guest beside a gate or bootstrap

**Steps**

1. One command per target, inside nix develop .#platforms: python3 -m src.tests.target_runner --target ios-aarch64-simulator --frontend both --executor ios-simulator --device btrc-ios-current --out ~/.cache/btrc/target-runs/\<sha>/ios-sim-current (repeat with btrc-ios-17 if MAC-P1-02 installed it).
2. One command per AVD: python3 -m src.tests.target_runner --target android-aarch64 --frontend both --executor android-emulator --avd btrc-api29 (then btrc-api36, then btrc-api36-16k), serially.
3. Hand the logs to Claude for triage and ingestion.

**Acceptance**

- [ ] The ABI fixture and the applicable corpus run on each Mac target through both frontends, with JSON logs and ledger records
- [ ] Counts per target delivered to CL-P1-18

**Risks**

- iOS 17 runtime absence limits the floor run to the iOS 17 deployment target compile-check (D8).

#### Stage 26: P3 OS services

<a id="mac-p2-01"></a>

##### MAC-P2-01 · Stage 26 iOS acceptance on pinned Xcode 27A266a (regex, process/terminal/daemon refusals, channel/jobs, mobile storage, HTTP)

- **Owner:** Owner · **Group:** P2 · **Stage:** 26 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `platforms-p3-regex-glob[ios-acceptance]`; `platforms-p3-fs-mobile[ios-acceptance]`; `platforms-p3-process-terminal[ios-acceptance]`; `platforms-p3-jobs-ipc[ios-acceptance]`; `platforms-p3-sockets-http[ios-acceptance]`
- **Depends on:** [CX-P2-06](codex.md#cx-p2-06); [CX-P2-07](codex.md#cx-p2-07); [CX-P2-08](codex.md#cx-p2-08); [CX-P2-11](codex.md#cx-p2-11); [CX-P2-13](codex.md#cx-p2-13); [CX-P2-14](codex.md#cx-p2-14); [CX-P2-15](codex.md#cx-p2-15); [CX-P2-16](codex.md#cx-p2-16); stage23:tooling-ios-simulator-runtimes → [MAC-P1-02](#mac-p1-02)
- **Why not now:** The Stage 26 providers must be merged on main, and the iOS 17 (or oldest installable) runtime must be installed (Stage 23).
- **Parallel-safe with:** any cloud packet

**Owned paths**

- ~/.cache/btrc/qualification/ (evidence; not in the repository)

**Must not touch**

- the repository (Claude ingests and commits)

**Steps**

1. Claude prepares a single command (the Stage 25 target-runner form, for example `~/.cache/btrc/tools/withlock.sh guest make test-btrc TARGET=ios-aarch64-simulator BTRC_TEST_SELECT=stage26`) for both frontends on the iOS 17 or oldest runtime and on the current runtime.
2. The owner runs it from a clone of ~/.cache/btrc/hub.git outside Drive, with no gate or other guest running and at least 80 GB free disk.
3. Run `python3 -m tools.qualification ingest --junit <files> --platform ios --variant arm64-simulator --frontend reference|selfhost --this-host`.
4. Claude records the result in PLAN.md and files a packet for each failure.

**Acceptance**

- [ ] JUnit results for both frontends on both runtimes are ingested, and the Stage 26 iOS inventory cells are passed or carry recorded failures with packets.
- [ ] The Xcode build 27A266a is named in the provenance.

**Risks**

- The iOS 17 runtime may not install under Xcode 27; then the oldest runtime is used, per D8.

#### Stage 27: W1 Windows host and interop lane I (one ownership design, function tables, early Objective-C and JNI slices, then COM)

<a id="mac-p2-02"></a>

##### MAC-P2-02 · Stage 27 interop device-host evidence: Objective-C delegate on the iOS simulator, JNI on the arm64/16 KiB emulators

- **Owner:** Owner · **Group:** P2 · **Stage:** 27 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `platforms-i1-objc-protocol-adapters[step3-ios-sim-evidence]`; `platforms-a1-checked-jni[step4-emulator-evidence]`
- **Depends on:** [CL-P2-07](claude.md#cl-p2-07); [CL-P2-09](claude.md#cl-p2-09); stage23:tooling-ios-simulator-runtimes → [MAC-P1-02](#mac-p1-02); stage23:tooling-android-sdk-ndk → [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](#mac-p1-03); stage25:platforms-p1-host-ios → [CX-P1-08](codex.md#cx-p1-08); stage25:platforms-p1-host-android → [CX-P1-09](codex.md#cx-p1-09)
- **Why not now:** Needs the Objective-C and JNI slices on main plus the Stage 23 runtimes, SDK and AVDs, and the Stage 25 hosts.
- **Parallel-safe with:** any cloud packet

**Owned paths**

- ~/.cache/btrc/qualification/ (evidence)

**Must not touch**

- the repository

**Steps**

1. Claude prepares two commands from the Stage 25 host lanes. (1) `withlock.sh guest <ios slice runner>` compiles the Foundation-only delegate fixture for arm64-apple-ios17.0-simulator and runs it with `simctl spawn` on the iOS 17 (or oldest installable) runtime and the current runtime.
2. (2) `withlock.sh guest <android app_process runner>` pushes the .dex and .so, runs `setprop debug.checkjni 1` and runs on API 29, API 36 and the 16 KiB arm64 image, scanning logcat for CheckJNI aborts.
3. Run one emulator at a time, with no gate running.
4. Ingest with `python3 -m tools.qualification ingest`; Claude records the Stage 27 exit rows in PLAN.md.

**Acceptance**

- [ ] Logs and JUnit for both frontends are ingested, and PLAN.md marks the Stage 27 exits 'checked Objective-C delegate round trip on the iOS simulator' and 'checked JNI round trip on the emulator test host' as met, or records the failures.

**Risks**

- Uninstallable iOS 17 runtime (D8 fallback).
- The 16 KiB arm64 image needs Apple-silicon acceleration.

#### Stage 28: P4 dependency closure and library artifacts (W1 exit)

<a id="mac-p2-03"></a>

##### MAC-P2-03 · Stage 28 Mac runs: iOS dependency slices, iOS package suites, BTRSmith iOS launch, macOS host byte identity

- **Owner:** Owner · **Group:** P2 · **Stage:** 28 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `platforms-p4-dependency-crossbuild[ios-slices]`; `btrsmith-package-closure[ios-slices]`; `platforms-p4-package-contracts[ios-acceptance]`; `btrsmith-cross-target-build[macos-identity-ios-launch]`
- **Depends on:** [CL-P2-16](claude.md#cl-p2-16); [CX-P2-21](codex.md#cx-p2-21); [CX-P2-22](codex.md#cx-p2-22); [CX-P2-23](codex.md#cx-p2-23); [CX-P2-24](codex.md#cx-p2-24); [CX-P2-29](codex.md#cx-p2-29); [CX-P2-30](codex.md#cx-p2-30)
- **Why not now:** Needs the Stage 28 Codex packets on main and the BTRSmith target abstraction.
- **Parallel-safe with:** any cloud packet

**Owned paths**

- ~/.cache/btrc/xbuild/ (outputs)
- ~/.cache/btrc/qualification/ (evidence)

**Must not touch**

- the repositories

**Steps**

1. Check for at least 100 GB of free disk.
2. Run one command for the tools/xbuild ios-aarch64 and ios-aarch64-simulator builds of every dependency.
3. Run one command for the package suites on the simulator through both frontends.
4. Run one command to build the BTRSmith iOS launch artifact and launch it with simctl.
5. Run one command to compare the macOS host build's sha256 before and after CL-P2-16, plus application-frontend-check and the library smoke on both frontends. Signing work runs behind locks/signing.

**Acceptance**

- [ ] The manifest gains its iOS rows, the iOS suite reports are ingested, the BTRSmith simulator launch passes, and the macOS host artifacts are byte-identical.

**Risks**

- Mac disk pressure.

#### Stage 29: Non-UI platform tracks and interop lane II (Objective-C protocols, then JNI)

<a id="mac-p2-04"></a>

##### MAC-P2-04 · Stage 29 pinned-Xcode iOS acceptance and Metal: UIKit adapters, xcarchive validation, BTRSmith Metal readback

- **Owner:** Owner · **Group:** P2 · **Stage:** 29 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `platforms-i1-objc-protocol-adapters[step6-ios-sim-acceptance]`; `platforms-i2-app-packaging[mac-archive-validation]`; `btrsmith-gpu-portability[metal]`
- **Depends on:** [CL-P2-21](claude.md#cl-p2-21); [CX-P2-36](codex.md#cx-p2-36); [CX-P2-37](codex.md#cx-p2-37); [CX-P2-38](codex.md#cx-p2-38); [CX-P2-39](codex.md#cx-p2-39); [CX-P2-40](codex.md#cx-p2-40); [CX-P2-46](codex.md#cx-p2-46); [CX-P2-48](codex.md#cx-p2-48)
- **Why not now:** Needs the Stage 29 iOS packets on main.
- **Parallel-safe with:** any cloud packet

**Owned paths**

- ~/.cache/btrc/qualification/ (evidence)

**Must not touch**

- the repositories

**Steps**

1. Run one command for the UIKit test-host 100 scene cycles on the pinned Xcode, re-running the lifecycle, storage, audio and GPU simulator suites on the iOS 17 (or oldest) runtime and the current one.
2. Run one command for xcodebuild archive on both slices, with ad-hoc signing behind locks/signing, validation and symbolication.
3. Run one command for the BTRSmith PlayerGPU and SharedGPUComposition readback on macOS Metal and the iOS simulator, plus the BTRSmith iOS storage fixtures.
4. Ingest everything; Claude records the results in PLAN.md.

**Acceptance**

- [ ] The ingested reports cover both frontends, the archives validate cleanly, and the Metal readback passes.

**Risks**

- There is no Developer ID (D8), so ad-hoc signing only.

<a id="mac-p2-05"></a>

##### MAC-P2-05 · Physical devices, audio endpoints, GPUs and distribution signing: prepared runbooks recorded as awaiting hardware/account (D8)

- **Owner:** Owner · **Group:** P2 · **Stage:** 29 · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 1 h
- **PLAN items:** `platforms-w2-arm64[physical]`; `platforms-w2-wasapi[physical]`; `platforms-w2-gpu-image-font[physical-gpu]`; `platforms-i1-objc-protocol-adapters[physical]`; `platforms-i2-audio[physical]`; `platforms-i2-gpu[physical]`; `platforms-i2-app-packaging[distribution-signing]`; `platforms-a1-checked-jni[physical]`; `platforms-a2-aaudio[physical]`; `platforms-a2-gpu[physical]`; `qualification-ci-ios[physical-device-jobs]`
- **Depends on:** [CX-P2-31](codex.md#cx-p2-31); [CX-P2-32](codex.md#cx-p2-32); [CX-P2-33](codex.md#cx-p2-33); [CX-P2-38](codex.md#cx-p2-38); [CX-P2-39](codex.md#cx-p2-39); [CX-P2-40](codex.md#cx-p2-40); [CL-P2-24](claude.md#cl-p2-24); [CX-P2-43](codex.md#cx-p2-43); [CX-P2-44](codex.md#cx-p2-44); [CX-P2-49](codex.md#cx-p2-49)
- **Why not now:** No physical iPhone/iPad, Android vendor devices, Windows hardware, Apple Developer ID or Windows code-signing certificate exists (D8). The runbooks need the providers first.
- **Parallel-safe with:** any

**Owned paths**

- docs/qualification/devices.toml (status rows; Claude commits)
- ~/.cache/btrc/qualification/ (evidence)

**Must not touch**

- the repositories (Claude commits)

**Steps**

1. For each part, Claude or Codex supplies a one-command runbook (device id, build, install, run, ingest).
2. Claude records each row as 'awaiting hardware/account' in devices.toml and the ledger, never as met.
3. When a device or account appears, the owner runs the command and Claude ingests the result.

**Acceptance**

- [ ] Every physical gate of Stage 29 has a runbook and an unavailable record, and test_device_registry.py passes.

**Risks**

- Hardware may never be procured; these gates stay open.

#### Stage 30: UI0 catalog, journeys and evidence hosts

<a id="mac-uia-01"></a>

##### MAC-UIA-01 · tooling-linux-desktop-host: probe FRACTAL-NORTH or record the Linux desktop as unavailable

- **Owner:** Owner · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 1 h
- **PLAN items:** `tooling-linux-desktop-host`
- **Depends on:** [CX-UIA-06](codex.md#cx-uia-06)
- **Why not now:** Needs CX-UIA-06's tools/ui/linux-desktop-check.sh and the owner's Linux desktop. FRACTAL-NORTH did not resolve on 2026-09-30, and D7 re-probes it.
- **Parallel-safe with:** CX-UIA-09, CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13

**Owned paths**

- none in the repository: the owner runs the commands, and Claude records the results in docs/qualification/devices.toml and hosts.toml

**Must not touch**

- system settings
- accounts or purchases (D8)

**Steps**

1. Run: ssh FRACTAL-NORTH.local 'nproc; free -g; lscpu; nix --version' (the D7 probe).
2. If the host answers, run 'tools/ui/linux-desktop-check.sh > ~/linux-desktop-check.json' from a btrc clone on it, once in a Wayland session and once in an X11 session, and send both files.
3. If it does not answer, say so. Claude records linux-desktop as unavailable, with the UTM NixOS VM as a non-physical stand-in.

**Acceptance**

- [ ] hosts.toml and devices.toml carry the GPU/driver, compositor and scales plus the Orca and GPU-reset results, or an explicit unavailable row.

**Risks**

- Without a physical desktop, the D23 IME evidence and later Orca journeys stay awaiting hardware.

#### Stage 31: UI1 shells on all five platforms and the toolkit decision

<a id="mac-uia-02"></a>

##### MAC-UIA-02 · ui-1-macos on the owner's Mac: GPU child, Xcode 27 and Accessibility Inspector

- **Owner:** Owner · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 1.5 h
- **PLAN items:** `ui-1-macos#owner-mac`
- **Depends on:** [CX-UIA-10](codex.md#cx-uia-10)
- **Why not now:** Needs CX-UIA-10 on main and the owner's Mac. Hosted runners cannot run the GPU child.
- **Parallel-safe with:** CX-UIA-11, CX-UIA-12, CX-UIA-13

> **Review change:** Shrunk to the timing rows; correctness rows run on hosted macOS (§10 F8).

**Owned paths**

- none in the repository; results go under ~/.cache/btrc/evidence/ui1-macos/

**Must not touch**

- system settings

**Steps**

1. From a clone outside Drive, run: ~/.cache/btrc/tools/withlock.sh gui-capture nix develop --profile ~/.cache/btrc/gcroots/ui1 --command python -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_macos.py --junitxml ~/.cache/btrc/evidence/ui1-macos/junit.xml
2. Rerun with BTRC_UI_SHELL_PAUSE=1, open Accessibility Inspector on the fixture window, and save one screenshot to the same folder.

**Acceptance**

- [ ] GPU timing rows (frame pacing, idle CPU) pass on real Metal for both frontends; GPU-frame correctness already runs on hosted macOS. Claude ingests the junit and the AX JSON with provenance (mac-m1-max, macOS 27.0, Xcode 27A266a).

**Risks**

- It must not run beside a gate or bootstrap (capacity rules).

<a id="mac-uia-03"></a>

##### MAC-UIA-03 · iOS simulator and Android emulator shell confirmation on the owner's Mac

- **Owner:** Owner · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `ui-1-ios-shell#owner-mac`; `ui-1-android-shell#owner-mac`
- **Depends on:** [CX-UIA-16](codex.md#cx-uia-16); [CX-UIA-17](codex.md#cx-uia-17)
- **Why not now:** Needs both mobile shells, which are behind bucket 3, and the Stage 23 simulator runtimes and AVDs on the Mac.
- **Parallel-safe with:** CX-UIA-24, CX-UIA-25

**Owned paths**

- none in the repository; results go under ~/.cache/btrc/evidence/ui1-mobile/

**Must not touch**

- system settings
- accounts (D8)

**Steps**

1. Run ~/.cache/btrc/tools/withlock.sh guest tools/ui/run-ios-shell.sh: Xcode 27A266a, with the iOS 17 simulator runtime or the oldest one installable per D8.
2. Run ~/.cache/btrc/tools/withlock.sh guest tools/ui/run-android-shell.sh on the API 29, current-API and 16 KiB-page AVDs, one emulator at a time.

**Acceptance**

- [ ] Both shells run from both frontends on the owner's simulator and emulators, and Claude ingests the results with provenance.

**Risks**

- The RAM rule allows only one emulator, and none during a gate or bootstrap.

#### Stage 32: UI2 contracts (events, executor, lifecycle) and the Library.UI split

<a id="mac-uia-04"></a>

##### MAC-UIA-04 · UI2 BTRSmith macOS evidence: journeys and idle wakeups before and after

- **Owner:** Owner · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `ui-2-btrsmith-subscriptions#mac-evidence`
- **Depends on:** [CL-UIA-15](claude.md#cl-uia-15)
- **Why not now:** Needs CL-UIA-15 and the owner's Mac (BTRSmith GUI smokes and signing).
- **Parallel-safe with:** CX-UIA-24, CL-UIA-16

**Owned paths**

- none in the repository; results go under ~/.cache/btrc/evidence/ui2-btrsmith/

**Must not touch**

- system settings

**Steps**

1. Run ~/.cache/btrc/tools/withlock.sh gate make -C ~/.cache/btrsmith/clones/ui2 application-frontend-check library-smoke on both frontends; signing goes through ~/.cache/btrc/tools/withlock.sh signing.
2. Run ~/.cache/btrsmith/clones/ui2/tools/ui-idle-wakeups.sh \<old-pin> \<new-pin> > ~/.cache/btrc/evidence/ui2-btrsmith/wakeups.json

**Acceptance**

- [ ] Idle wakeups per minute before and after are recorded in PLAN's Stage 32 entry, and application-frontend-check and the library smoke pass on both frontends.

**Risks**

- It must not run beside a gate.

<a id="mac-uia-05"></a>

##### MAC-UIA-05 · Library.UI split: signed macOS smokes and AgentSurfaceAcceptance on the owner's Mac

- **Owner:** Owner · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `btrsmith-libraryui-split#mac-smokes`
- **Depends on:** [CL-UIA-17](claude.md#cl-uia-17); [CL-UIA-18](claude.md#cl-uia-18)
- **Why not now:** Needs both migration packets and the owner's Mac for signed GUI smokes.
- **Parallel-safe with:** CX-UIA-25, CX-UIA-26, CX-UIA-27

**Owned paths**

- none in the repository

**Must not touch**

- system settings

**Steps**

1. Run ~/.cache/btrc/tools/withlock.sh signing make -C ~/.cache/btrsmith/clones/split SIGN_CODE=1 application-frontend-check library-smoke agent-surface-acceptance on both frontends.

**Acceptance**

- [ ] The signed macOS smokes and AgentSurfaceAcceptance pass on both frontends, and Claude records them in Stage 32.

**Risks**

- Signing is ad hoc (D8).

#### Stage 33: UI3 input, focus and commands, then the tray

<a id="mac-uia-06"></a>

##### MAC-UIA-06 · UI3 physical IME and keyboard-layout trials

- **Owner:** Owner · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 1.5 h
- **PLAN items:** `ui-3-macos#physical-ime`; `ui-3-linux#desktop-ime`
- **Depends on:** [CL-UIA-20](claude.md#cl-uia-20)
- **Why not now:** Needs UI3 on main and the owner at the Mac. The Linux half also needs a desktop host (MAC-UIA-01).
- **Parallel-safe with:** CX-UIA-28

**Owned paths**

- none in the repository; results go under ~/.cache/btrc/evidence/ui3-ime/

**Must not touch**

- system settings beyond adding input sources the owner chooses

**Steps**

1. Run tools/ui/ime-trial.sh, which opens ImeTrial, a checklist and a commit log. Type with Japanese Kotoeri, Chinese Pinyin, Korean 2-Set, US-International dead keys, German and French AZERTY layouts and the emoji picker, then send log.json.
2. Run the same trial with ibus or fcitx on the Linux desktop host if MAC-UIA-01 found one. Otherwise Claude records it as awaiting hardware.

**Acceptance**

- [ ] The log shows 0 lost or duplicated commits and no playback command fired from text editing. Claude ingests it with provenance, which meets Stage 33's 'IME trials recorded'.

**Risks**

- Adding input sources is an owner action; the agent changes no settings.

#### Stage 34: UI4–UI9 contract packet and macOS/Linux reference providers

<a id="mac-uib-01"></a>

##### MAC-UIB-01 · Owner sessions on the Mac: VoiceOver and keyboard-only journeys for each Stage 34 landing (L1-L4)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 34 (UI8 in each landing: VoiceOver on macOS) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 4 agent-hours · **Mac wall:** 6 h
- **PLAN items:** `ui-8-macos` (VoiceOver journey evidence); `ui-4/5/6/7-macos` (screen-reader rows)
- **Depends on:** [CX-UIB-40](codex.md#cx-uib-40); [CL-UIB-02](claude.md#cl-uib-02); [CX-UIB-18](codex.md#cx-uib-18) (ready: integ/ui-l1 assembled); [CX-UIB-19](codex.md#cx-uib-19) (ready); [CX-UIB-22](codex.md#cx-uib-22) (ready)
- **Why not now:** No landing exists yet.
- **Parallel-safe with:** MAC-UIB-02

> **Review change:** Runs on each landing's integration branch before its push, one session per landing L1–L4 (§7 Q31); it no longer waits for `CL-UIB-05` (§10 P9).

**Owned paths**

- ~/.cache/btrc/qualification (ledger rows)

**Must not touch**

- repository files (the agent ingests the results)

**Steps**

1. Before each landing's push, on the assembled integ/ui-lN branch, from a clone outside Drive, with no gate running, run: ~/.cache/btrc/tools/withlock.sh gui-capture python3 -m tools.ui_evidence session --host mac --landing ui4 --kind voiceover. Then repeat with --kind keyboard. Repeat for ui5, ui6 and ui7.
2. For L2, the owner toggles Increase Contrast, Reduce Motion and the largest text size in System Settings (agents never change system settings).
3. Answer the checklist prompts. The tool writes the ledger rows.

**Acceptance**

- [ ] Each landing has a VoiceOver journey record and a keyboard-only record for every family it adds, with 0 inaccessible modal exits.

**Risks**

- Human time per landing (about 1 h).

<a id="mac-uib-02"></a>

##### MAC-UIB-02 · Owner sessions on the Linux desktop host: Orca journeys, real Wayland/X11 input and IME, portal trials for each landing

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 34 (UI8 in each landing: Orca on Linux) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 4 agent-hours · **Mac wall:** 6 h
- **PLAN items:** `ui-8-linux` (Orca journey evidence); `ui-7-linux` (portal trials on the desktop host)
- **Depends on:** [CX-UIB-40](codex.md#cx-uib-40); PLAN:tooling-linux-desktop-host (Stage 30) → [MAC-UIA-01](#mac-uia-01); [CL-UIB-02](claude.md#cl-uib-02); [CX-UIB-20](codex.md#cx-uib-20) (ready: integ/ui-l1 assembled); [CX-UIB-21](codex.md#cx-uib-21) (ready); [CX-UIB-23](codex.md#cx-uib-23) (ready)
- **Why not now:** The Linux desktop host (Stage 30) and the landings do not exist yet.
- **Parallel-safe with:** MAC-UIB-01

> **Review change:** Runs on each landing's integration branch before its push, one session per landing L1–L4 (§7 Q31); it no longer waits for `CL-UIB-05` (§10 P9).

**Owned paths**

- ~/.cache/btrc/qualification (ledger rows)

**Must not touch**

- repository files

**Steps**

1. On the desktop host (a VM on the Mac, or FRACTAL-NORTH if D7 finds it), counting as the one guest allowed beside a gate, run: python3 -m tools.ui_evidence session --host linux-desktop --landing ui4 --kind orca. Repeat for each landing before its push, on the assembled integ/ui-lN branch, once on Wayland and once on X11.
2. For L4, run the portal FileChooser and OpenURI trials, and a real IME session (Japanese, Chinese, Korean).

**Acceptance**

- [ ] An Orca journey record for each landing on both display servers; the portal trials are recorded.

**Risks**

- Guest memory alongside other work; one guest at a time.

<a id="mac-uib-03"></a>

##### MAC-UIB-03 · Mac hardware-tier runs and measurements for Stage 34: real GPU, idle CPU, frame timing, fixture hashes, AX trust

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 34 (overall exit evidence) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 6 h
- **PLAN items:** `exit:stage34-E36-E38-E42-E43-idle-cpu` (Mac tier); `qualification-catalog-fixtures` (macOS hash and 10,000-song load)
- **Depends on:** [CX-UIB-40](codex.md#cx-uib-40); [CL-UIB-07](claude.md#cl-uib-07); [CX-UIB-08](codex.md#cx-uib-08); [CX-UIB-09](codex.md#cx-uib-09)
- **Why not now:** Needs L3's GPU cores and the evidence harness.

**Owned paths**

- ~/.cache/btrc/qualification
- ~/.cache/btrc/bench.noindex/ (measurement workspace)

**Must not touch**

- repository files

**Steps**

1. After each landing: ~/.cache/btrc/tools/withlock.sh gui-capture python3 -m tools.ui_evidence hardware-tier --landing \<name>. This runs the real-GPU, AX-trust, trackpad and security-scoped cases that hosted runners skip.
2. Once, under the automated quiet check: withlock.sh bench python3 -m tools.ui_evidence idle-cpu --with-voiceover --without-voiceover, plus 100,000-row frame timing on the built-in display.
3. Run make -C \<btrsmith clone> -f make/AcceptanceCatalog.mk check (macOS hash and a 10,000-song load), and the CX-UIB-08 hash test.

**Acceptance**

- [ ] E36, E38, E42 and E43 pass on Metal.
- [ ] A static idle screen uses at most 1% CPU over 60 s, with and without VoiceOver.
- [ ] The macOS fixture hashes equal the Linux ones.

**Risks**

- Quiet windows compete with bucket-1 measurements; the bench lock serializes them.

#### Stage 35: Windows, iOS and Android UI tracks (one milestone behind Stage 34)

<a id="mac-uib-04"></a>

##### MAC-UIB-04 · Owner: iOS screen reader and devices for Stage 35 (Accessibility Inspector on the simulator; VoiceOver on iPhone and iPad, awaiting hardware)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 35 (iOS exit evidence) · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `ui-ios-a11y-gpu` (VoiceOver and device evidence); `ui-ios-core` (physical iPhone/iPad runs)
- **Depends on:** [CX-UIB-56](codex.md#cx-uib-56); [CX-UIB-57](codex.md#cx-uib-57); PLAN:tooling-ios-simulator-runtimes → [MAC-P1-02](#mac-p1-02); PLAN:tooling-ios-physical-devices → [MAC-P1-04](#mac-p1-04)
- **Why not now:** No iOS provider exists, and physical devices are unavailable under D8.
- **Parallel-safe with:** MAC-UIB-05

**Owned paths**

- ~/.cache/btrc/qualification

**Must not touch**

- repository files

**Steps**

1. On the Mac: withlock.sh guest python3 -m tools.ui_evidence session --host ios-simulator --kind accessibility-inspector, for each family landing.
2. When devices exist: --host iphone and --host ipad --kind voiceover, signed ad hoc (D8). Until then the rows are recorded as awaiting hardware.

**Acceptance**

- [ ] Simulator inspector records are present.
- [ ] VoiceOver device journeys are recorded, or explicitly marked awaiting hardware with the blocking item.

**Risks**

- D8: no device procurement.

<a id="mac-uib-05"></a>

##### MAC-UIB-05 · Owner: Android TalkBack on Mac emulators (API 29, current, 16 KiB) and on two physical vendors (awaiting hardware)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 35 (Android exit evidence) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `ui-android-a11y-gpu` (TalkBack and vendor evidence); `ui-android-core` (physical vendor runs)
- **Depends on:** [CX-UIB-64](codex.md#cx-uib-64); [CX-UIB-65](codex.md#cx-uib-65); PLAN:tooling-android-sdk-ndk → [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](#mac-p1-03); PLAN:tooling-android-physical-devices → [MAC-P1-04](#mac-p1-04)
- **Why not now:** No Android provider exists, and the vendor devices are unavailable under D8.
- **Parallel-safe with:** MAC-UIB-04

**Owned paths**

- ~/.cache/btrc/qualification

**Must not touch**

- repository files

**Steps**

1. withlock.sh guest python3 -m tools.ui_evidence session --host android-emulator --api {29,current,16k} --kind talkback. Runs one emulator at a time, at most one guest beside a gate.
2. Vendor devices: --host android-vendor-{a,b}, recorded as awaiting hardware until they exist.

**Acceptance**

- [ ] Emulator TalkBack journeys are recorded for every family. Vendor rows are present or marked awaiting hardware.

**Risks**

- Emulator images that ship TalkBack need Google Play builds.

<a id="mac-uib-06"></a>

##### MAC-UIB-06 · Owner: Windows Narrator journeys and x64/ARM64 hardware runs (awaiting hardware, D8)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 35 (Windows exit evidence) · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `ui-win-a11y-gpu` (Narrator evidence); `ui-win-core` (hardware IME and ARM64 hardware rows)
- **Depends on:** [CX-UIB-48](codex.md#cx-uib-48)
- **Why not now:** There is no Windows hardware (D8), and no Windows provider yet.
- **Parallel-safe with:** MAC-UIB-04, MAC-UIB-05

> **Review change:** Depends only on `CX-UIB-48`; the device rows are recorded as awaiting hardware until one exists. Its old dependency reached Stage 41 through `MAC-R-12` → `CX-R-12` (§10 P16).

**Owned paths**

- ~/.cache/btrc/qualification

**Must not touch**

- repository files

**Steps**

1. The runbook docs/qualification/ui-sessions/narrator.md and the packaged fixture build come from the windows.yml artifacts.
2. When hardware exists: python -m tools.ui_evidence session --host windows-x64 --kind narrator (and the ARM64 equivalent). Until then the rows are recorded as awaiting hardware.

**Acceptance**

- [ ] Narrator rows exist, either passed or 'awaiting hardware' naming tooling-windows-physical; never counted as met.

**Risks**

- Narrator is never satisfied by a hosted runner.

#### Stage 36: BTRSmith screen migration slices (one milestone behind Stage 34)

<a id="mac-uib-07"></a>

##### MAC-UIB-07 · Owner: BTRSmith Mac evidence for each Stage 36 slice (frontend check, journeys, search p95, idle CPU, VoiceOver per screen)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 36 (macOS exit evidence) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 4 agent-hours · **Mac wall:** 8 h
- **PLAN items:** `btrsmith-ui-slice1..4` and btrsmith-ui-accessibility (macOS evidence)
- **Depends on:** [CX-UIB-40](codex.md#cx-uib-40); [CX-UIB-66](codex.md#cx-uib-66)
- **Why not now:** No slice exists yet.

**Owned paths**

- ~/.cache/btrsmith/clones/\<n>
- ~/.cache/btrc/qualification

**Must not touch**

- repository sources

**Steps**

1. For each integration batch, from a BTRSmith clone outside Drive: make application-frontend-check btrsmith-library-smoke (both frontends), then withlock.sh gui-capture python3 -m tools.ui_evidence btrsmith-slice --slice \<n>. The second command runs the slice's tests/macos journeys, search p95 on the 10,000-song fixture, a static-idle trace, and compact-layout captures.
2. withlock.sh gui-capture python3 -m tools.ui_evidence session --host mac --kind voiceover --screen {library,settings,player}.

**Acceptance**

- [ ] Each slice's E-cases pass on macOS, both frontends.
- [ ] Search p95 is at most 100 ms. Static idle is at most 1% CPU. VoiceOver logs exist per screen.

**Risks**

- Post-link codesign affects receipts; use CODESIGN_IDENTITY=- as Stage 2 found.

<a id="mac-uib-08"></a>

##### MAC-UIB-08 · Owner: Player 30-minute audio/UI soak with physical audio (0 app-induced xruns, frame p95 at most 16.7 ms)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 36 (Player exit) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `ui-9-btrsmith-player` (soak evidence)
- **Depends on:** [CX-UIB-74](codex.md#cx-uib-74); [CX-UIB-38](codex.md#cx-uib-38)
- **Why not now:** Player slice 4 does not exist yet.

**Owned paths**

- ~/.cache/btrc/qualification

**Must not touch**

- repository sources

**Steps**

1. Connect the USB audio interface and the guitar DI.
2. Run withlock.sh gui-capture python3 -m tools.ui_evidence soak --app btrsmith --minutes 30. It scrolls, searches, opens dialogs and plays.

**Acceptance**

- [ ] 0 app-induced xruns over 30 minutes and frame p95 at most 16.7 ms, recorded in the ledger.

**Risks**

- The quiet-machine requirement.

#### Stage 37: UI10 automation and mobile restoration; UI11 long tail

<a id="mac-uib-09"></a>

##### MAC-UIB-09 · Owner: mobile physical qualification (100 restores, 20 launches with p95 at most 4 s; iPhone, iPad and two Android vendors), awaiting hardware

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 37 (UI10 mobile exit) · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 3 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `ui-10-btrsmith-mobile` (physical evidence); `btrsmith-ui-slice5-mobile-restoration` (physical evidence)
- **Depends on:** [CX-UIB-84](codex.md#cx-uib-84); [CX-UIB-85](codex.md#cx-uib-85); PLAN:tooling-ios-physical-devices → [MAC-P1-04](#mac-p1-04); PLAN:tooling-android-physical-devices → [MAC-P1-04](#mac-p1-04)
- **Why not now:** There are no devices (D8) and no mobile builds yet.
- **Parallel-safe with:** MAC-UIB-10

**Owned paths**

- ~/.cache/btrc/qualification

**Must not touch**

- repository sources

**Steps**

1. Run python3 -m tools.ui_evidence mobile --device \<id> --restores 100 --launches 20, at most two devices at a time through the Mac.
2. Until devices exist, record simulator and emulator stand-ins, and mark the physical rows awaiting hardware.

**Acceptance**

- [ ] Physical rows are passed, or explicitly awaiting hardware with blocking item ids; never counted as met.

**Risks**

- D8.

<a id="mac-uib-10"></a>

##### MAC-UIB-10 · Owner: Stage 37 per-host evidence (installed-app journeys on macOS and the Linux desktop host)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 37 (UI10 evidence and full gate) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2.5 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `ui-10-qualification` (Mac and desktop-host evidence); `qualification-p5-journey-drivers` (installed-app runs on macOS and Linux)
- **Depends on:** [CX-UIB-78](codex.md#cx-uib-78); [CX-UIB-79](codex.md#cx-uib-79); [CX-UIB-83](codex.md#cx-uib-83)
- **Why not now:** The drivers and the final revision do not exist yet.
- **Parallel-safe with:** MAC-UIB-09

> **Review change:** Split (§10 P1). This half is the per-host evidence that feeds `CX-UIB-86`; the bucket-4 exit gate moved to `MAC-UIB-11`, which follows `CL-UIB-17`. The old packet closed the cycle `CL-UIB-17` → `CX-UIB-86` → `MAC-UIB-10` → `CL-UIB-17`.

**Owned paths**

- ~/.cache/btrc/qualification

**Must not touch**

- repository sources

**Steps**

1. Grant the driver Accessibility permission (owner). Run withlock.sh gui-capture python3 -m tools.ui_evidence journeys --installed --host mac, then the same with --host linux-desktop on Wayland and X11.
2. Multi-monitor and 120 Hz rows only if those devices exist; otherwise they are recorded as unavailable.

**Acceptance**

- [ ] Installed-app seed journeys pass on macOS and the Linux desktop host, both frontends.

**Risks**

- Journey runs hold the gui-capture lock; nothing heavy runs beside them.

<a id="mac-uib-11"></a>

##### MAC-UIB-11 · Owner: bucket-4 exit gate on the Mac (make test, make bootstrap and make test-c11 on the CL-UIB-17 revision)

- **Owner:** Owner · **Group:** UIB · **Stage:** Stage 37 (bucket-4 exit gate) · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 4.5 h
- **PLAN items:** `ui-10-qualification` (Mac gate)
- **Depends on:** [CL-UIB-17](claude.md#cl-uib-17)
- **Why not now:** Runs on the final bucket-4 revision that CL-UIB-17 produces.

> **Review change:** New (§10 P1): the gate half of the old `MAC-UIB-10`.

**Owned paths**

- ~/.cache/btrc/qualification
- ~/.cache/btrc/roadmap/bucket4-exit/\<sha>/

**Must not touch**

- repository sources

**Steps**

1. Bucket-4 exit gate on the final revision under locks/gate: make test, make bootstrap and make test-c11, one at a time (`tools/runbook/run.sh bucket4-exit` once CL-R-02's presets cover it).
2. Paste summary.txt into the Claude session.

**Acceptance**

- [ ] The Mac gate is green on the CL-UIB-17 revision (summary.txt exit=0 for each step).

**Risks**

- The gate saturates the Mac; nothing runs beside the bootstrap.

#### Stage 39: P5 journeys on installed products and the macOS MVP closure

<a id="mac-r-10"></a>

##### MAC-R-10 · Stage 39 macOS session: MVP captures, the #6 side-by-side review, P5 macOS installed-product journeys, self-host matrix GUI cells (one command plus the review)

- **Owner:** Owner · **Group:** R · **Stage:** 39 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `btrsmith-macos-mvp-automatable`; `qualification-p5-runs-macos-linux`; `btrsmith-q-selfhost-matrix`
- **Depends on:** [CX-R-05](codex.md#cx-r-05); [CX-R-06](codex.md#cx-r-06); [CX-R-07](codex.md#cx-r-07); [CX-R-08](codex.md#cx-r-08); [CL-R-47](claude.md#cl-r-47)
- **Why not now:** Needs the MVP, journey and matrix presets.
- **Parallel-safe with:** MAC-R-11

**Owned paths**

- ~/.cache/btrsmith/build/evidence/stage39-\<date> (local)
- btrc:evidence/stage39-macos-\<date>

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh mvp-library mvp-player mvp-settings p5-macos btrsmith-selfhost-matrix`. GUI capture is serialized.
2. Do the 30-minute side-by-side review of the #6 sheets with the agent and record approve or deviation.

**Acceptance**

- [ ] Captures posted on btrsmith #2, #3, #6, #7, #16-#19; the agent closes them per standing approvals (#6 after your review)
- [ ] P5 macOS journeys passed or adapted with review; 0 missing core
- [ ] Self-host matrix macOS cells green

**Risks**

- 200 FPS and the 120 Hz rows depend on the display panel.

<a id="mac-r-11"></a>

##### MAC-R-11 · Stage 39 qualifying simulator and emulator journeys on the Mac with pinned Xcode 27A266a and the Android AVDs, two at a time (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 39 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `qualification-p5-runs-ios`; `qualification-p5-runs-android`
- **Depends on:** [CX-R-10](codex.md#cx-r-10)
- **Why not now:** Needs the mobile journey presets (CX-R-10).
- **Parallel-safe with:** MAC-R-10

**Owned paths**

- btrc:evidence/stage39-mobile-\<date>

**Must not touch**

- system settings

**Steps**

1. Run `tools/runbook/run.sh p5-ios-simulators p5-android-emulators`. The guest lock allows at most two guests; it accepts the Android SDK licences (approved).

**Acceptance**

- [ ] iOS 17 (or the oldest installable) and current iPhone and iPad simulators, plus Android API 29, current and 16 KiB AVDs: every journey slot passed or adapted
- [ ] Physical rows remain awaiting hardware

**Risks**

- Installing the iOS 17 runtime may be impossible under Xcode 27 (D8 fallback).

<a id="mac-r-12"></a>

##### MAC-R-12 · Physical devices and the Linux desktop: run the prepared one-command scripts when hardware exists; until then the rows stay awaiting hardware (D8)

- **Owner:** Owner · **Group:** R · **Stage:** 39 · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 2 h
- **PLAN items:** `tooling-windows-physical`; `qualification-p5-runs-windows`; `qualification-p5-runs-ios`; `qualification-p5-runs-android`; `qualification-p5-runs-macos-linux`; `qualification-p6-build-measure`; `qualification-p6-runtime-runs`; `qualification-p7-os-version-matrix`
- **Depends on:** [CX-R-08](codex.md#cx-r-08); [CX-R-09](codex.md#cx-r-09); [CX-R-10](codex.md#cx-r-10)
- **Why not now:** No Windows hardware, iPhone, iPad or Android device exists (D8); FRACTAL-NORTH is unverified (MAC-R-07).
- **Parallel-safe with:** MAC-R-10, MAC-R-11

> **Review change:** No longer waits for `CX-R-12` (Stage 41); the P6 runtime rows follow it with `MAC-R-14` (§10 P16).

**Owned paths**

- docs/qualification/devices.toml rows (updated by the integrator from the owner's report)

**Must not touch**

- no procurement or account creation by an agent

**Steps**

1. When a device arrives, tell the integrator the exact model and OS build.
2. Run its script: `pwsh tools/devices/windows/run.ps1 -Journeys all`, `tools/devices/ios/run.sh <udid>`, `tools/devices/android/run.sh <serial>`, or the Linux desktop runbook.
3. Measure P6 build on the device with the same scripts. P6 runtime rows on devices use CX-R-12's orchestration once it lands, in the same session as MAC-R-14.

**Acceptance**

- [ ] Each device row moves from unavailable to available with evidence ingested, or stays explicitly awaiting hardware

**Risks**

- Two devices at most through the Mac at a time.

#### Stage 40: Physical instrument, listening and latency sessions

<a id="mac-r-13"></a>

##### MAC-R-13 · Stage 40 physical sessions: the macOS loopback-latency run, a 2-hour soak, listening, route and visual sign-offs for btrsmith #4, #5, #21, #22; other platforms when hardware exists

- **Owner:** Owner · **Group:** R · **Stage:** 40 · **Environment:** Device or account (owner) · **Start now:** no · **Estimate:** 1 agent-hours · **Mac wall:** 4 h
- **PLAN items:** `qualification-p5-physical-audio-visual`; `btrsmith-macos-mvp-physical`; `tooling-audio-loopback-rig`; `qualification-p6-audio-latency-rig`
- **Depends on:** [CX-R-01](codex.md#cx-r-01); [CX-R-03](codex.md#cx-r-03); [CX-R-04](codex.md#cx-r-04)
- **Why not now:** Needs the rig, the checklists and the #4 DSP work, plus the owner's audio interface, loopback cable and guitar (devices.toml rows unavailable).

**Owned paths**

- ~/.cache/btrsmith/build/evidence/stage40-\<date> (local)

**Must not touch**

- system settings

**Steps**

1. Connect the interface with the loopback cable and run `tools/audio_rig/run_session.sh macos`.
2. Follow docs/qualification/sessions/macos.md for #5, #21 and #22 with the guitar, and the #4 listening approval.
3. Start the 2-hour soak from the checklist.
4. Repeat for Windows, iOS and Android when hardware exists (CX-R-02).

**Acceptance**

- [ ] ≥100 round-trip samples with p95 reported (budgets: ≤20 ms Windows/iOS, ≤30 ms Android when those platforms run)
- [ ] 2-hour soak clean; signed listening, route and visual records
- [ ] Evidence posted on #4, #5, #21, #22; you close them

**Risks**

- Bound by your availability (the plan says so).

#### Stage 41: P6 numeric acceptance

<a id="mac-r-14"></a>

##### MAC-R-14 · Stage 41 P6 quiet measurements on the Mac: iOS and Android build budgets, macOS runtime runs, UI10 numeric rows, 120 Hz panel check (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 41 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 10 h · **Overnights:** 1
- **PLAN items:** `qualification-p6-build-measure`; `qualification-p6-runtime-runs`
- **Depends on:** [CX-R-11](codex.md#cx-r-11); [CX-R-12](codex.md#cx-r-12)
- **Why not now:** Needs the P6 adapters and runtime presets.

**Owned paths**

- btrc:evidence/stage41-\<date>

**Must not touch**

- system settings

**Steps**

1. Run `system_profiler SPDisplaysDataType | grep -i -E 'Display Type|Refresh|Resolution'` once (devices.toml verify line).
2. Run `tools/runbook/run.sh p6-build-ios p6-build-android p6-runtime-macos` overnight under the quiet check.

**Acceptance**

- [ ] Raw distributions (≥5 cold, ≥20 edit and no-op) for every P6 build row on iOS and Android variants built on the Mac, including the reference private-body edit row
- [ ] macOS runtime rows: launch p95 ≤3 s over 20; search ≤100 ms; frame p95 ≤16.7 ms over 10 minutes; working set ≤512 MiB; 100 lifecycle cycles; 30-minute soak
- [ ] UI10 numeric rows on macOS met or revised; misses stated

**Risks**

- Simulator runtime numbers are not device numbers; recorded separately.

#### Stage 42: P7 release engineering

<a id="mac-r-15"></a>

##### MAC-R-15 · Stage 42 Mac-bound steps: notarization declined record, Android release keystore, pinned-Xcode OS matrix, simulator debugger, macOS install/upgrade and stress (one command)

- **Owner:** Owner · **Group:** R · **Stage:** 42 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 1.5 agent-hours · **Mac wall:** 3 h
- **PLAN items:** `qualification-p7-macos-notarization`; `tooling-release-signing-mobile-store`; `qualification-p7-os-version-matrix`; `qualification-p7-devtools-targets`; `qualification-p7-install-upgrade`; `qualification-p7-stress-faults`
- **Depends on:** [CX-R-13](codex.md#cx-r-13); [CX-R-15](codex.md#cx-r-15); [CX-R-16](codex.md#cx-r-16); [CX-R-18](codex.md#cx-r-18); [CX-R-20](codex.md#cx-r-20)
- **Why not now:** Needs the Stage 42 presets.

**Owned paths**

- ~/.cache/btrsmith/signing (local, never committed)
- btrc:evidence/stage42-\<date>

**Must not touch**

- no credentials or agreements beyond the Android SDK licences

**Steps**

1. Run `tools/runbook/run.sh p7-notarization p7-os-matrix p7-install-macos p7-stress-macos p7-debugger-simulators`. Sanitizer and stress cells never run beside a bootstrap.

**Acceptance**

- [ ] Notarization recorded as declined (no Developer ID), or spctl accepts the stapled app if an identity exists
- [ ] The Android release keystore is generated locally; APK and AAB validate
- [ ] Minimum and current OS rows pass on the pinned simulators; a .btrc breakpoint and crash symbolication work on the simulator
- [ ] macOS upgrade loses no state; every macOS fault class passes 100 cycles

**Risks**

- Notarization stays declined until you have an account.

#### Stage 43: Final platform exits and the release candidate

<a id="mac-r-16"></a>

##### MAC-R-16 · Stage 43 release-candidate Mac gate chain on the frozen SHAs (one command; any fix restarts)

- **Owner:** Owner · **Group:** R · **Stage:** 43 · **Environment:** Owner's Mac · **Start now:** no · **Estimate:** 2 agent-hours · **Mac wall:** 6 h
- **PLAN items:** `qualification-p7-release-candidate-run`
- **Depends on:** [CL-R-46](claude.md#cl-r-46)
- **Why not now:** Needs the frozen SHAs and the rc-mac preset (CL-R-46).

**Owned paths**

- btrc:evidence/rc-\<date>

**Must not touch**

- the frozen SHAs

**Steps**

1. Run `tools/runbook/run.sh rc-mac --freeze <btrc-sha> <btrsmith-sha>`. Strict order: D5 gate, determinism tier, Mac test-c11, BTRSmith release-check on both frontends, P5 macOS, simulators two at a time.

**Acceptance**

- [ ] Every Mac step green on the frozen SHAs; its records join CL-R-46's single ledger bundle

**Risks**

- Any red step or fix restarts the whole run.
