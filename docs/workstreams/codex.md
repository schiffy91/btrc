# WORKSTREAMS packets: Codex

Part of [WORKSTREAMS.md](../../WORKSTREAMS.md), the shared plan for Claude, Codex and the owner. That file holds the purpose, decision D27, the coordination protocol, the assignment matrix, the timeline and the open questions; this file holds the Codex packets in full. `packets.json` beside it is the same packet set in machine-readable form.


Grouped by owner, then by stage (the first stage a packet's `plan_stage` names), then by group and number. Owned paths, steps, acceptance and risks are the analysts' text, escaped for Markdown only. Changes are marked **Writer note** (listed in §9) or **Review change** (listed in §10); where the two differ, the review change wins.

### 6.2 Codex packets

Codex: read §2 (D27) and §3 (protocol) before your first packet. Every packet below follows the branch, PR, fragment, skip-rule and report rules in §3, even where its own text is shorter or older: §3.5 says how to read older fragment wording, §3.11 how to run every command, and a **Review change** note on a packet overrides its body.

#### What Codex inherits: GUI, UI, Tray and App on `430a892`

This summarizes the Stage 30–33 analyst's inventory; Appendix C has the full text.

| | macOS | Linux | Windows | iOS | Android |
|---|---|---|---|---|---|
| **Portable contracts** | 20 `GUI/I*.btrc` files, 25 interfaces, 152 interface methods, plus 26 `GUI` facade methods (178 declarations), shared by every platform | same | same | same | same |
| **GUI provider** | 33 files: real AppKit controls for all 15 factories, `NSStackView`/`NSGridView`, a `CAMetalLayer` WebGPU child, composed capture, CoreText raster text, a synchronous `runModal` folder picker, `NSTimer` delayed work, and a run-loop action queue (256 entries) | 28 files: SDL3 windows, each with one WebGPU surface; every control custom-painted (`LinuxPainter`, fontconfig/FreeType); an overlay select; SDL message boxes; a portal/zenity folder dialog pumped modally; offscreen-composited GPU views; whole-window capture that ignores the supplied layers | none: `GUI/btrc.toml` selects only macOS and Linux | none: no iOS target until Stage 24 | none: no Android target until Stage 24 |
| **Known gaps** | no close veto (`windowShouldClose` always returns true); no `NSAccessibility`; no scoped control events; no worker wakeup; bordered fonts above 20 pt are rejected | no native widgets; no AT-SPI; no IME preedit; no text undo; button, slider and scroll ignore the keyboard; no exposure tracking; presentation failure is not recoverable; `pumpEvents` drops the 4,097th event (E40) | everything | everything | everything |
| **Tray** | `NSStatusItem`/`NSMenu` | StatusNotifierItem plus DBusMenu over libdbus; tested only through the reference frontend, and the test skips in CI without a watcher | fails at provider selection | OS-restricted | OS-restricted |
| **Tests and CI** | 27 native GUI fixtures plus Objective-C probes; hosted macos-15 has a paravirtual Metal adapter, so GPU correctness rows run in CI (timing rows stay owner-tier) | 3 Linux fixtures under Xvfb with lavapipe, X11 only (no Wayland, GTK4 or AT-SPI in Nix until `CL-UIA-21`) | — | — | — |

- **Missing across all platforms (the contracts):**
  - edit, commit and change events;
  - a keyed `ISelect` (today it is index-only);
  - `ISlider` range updates;
  - two-axis scrolling;
  - a worker-safe `post`;
  - a close veto;
  - a focus and command API;
  - scene restoration;
  - effective visibility;
  - any accessibility attachment.
- **`App` input values:** pointer, scroll (with phases) and key values, and an `AppKeyCode` with 27 named values plus unknown. There is no touch, pen, IME or text-edit event, no split between physical and layout keys, and no Page Up/Down or F-keys.
- **`UI`:** a custom retained renderer (`Element` is 1,102 lines and `Render` 2,905), with semantics, focus, text editing, a virtual grid and a proof raster. It has no presentation host and no OS accessibility bridge.
- **`Tray` model:** `SystemTray`, `ITray`, `TrayModel`; shell-string commands run synchronously through `Library.Process`; no typed commands, notifications or badges.

The Codex packets below build the rest, platform by platform:
- UI0 catalog and hosts (Stage 30);
- shells (31);
- UI2/UI3 contracts and the macOS/Linux providers (32–33);
- the tray (33);
- UI4–UI9 (34);
- the Windows, iOS and Android UI tracks (35);
- BTRSmith screens (36);
- automation and the long tail (37).

#### Stage 7: Correctness nets, M10 pool qualification, first cold-path cuts

<a id="cx-r-22"></a>

##### CX-R-22 · BTRSmith portable coverage: port the unported PortableCoverage.md rows (PlayerPan; SharedGPUComposition; Library/Journey/Hover), plus the stage7 GUI preset

- **Owner:** Codex · **Group:** R · **Stage:** 7 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `btrsmith-portable-coverage`
- **Depends on:** [CL-R-08](claude.md#cl-r-08); [CL-R-01](claude.md#cl-r-01)
- **Why not now:** Stage 7 opens after Stage 6 (CL-R-08); needs the new BTRSmith pin (CL-R-01).
- **Parallel-safe with:** CL-R-09, CL-R-11

> **Review change:** macOS evidence moves to `MAC-R-04`: BTRSmith has no macOS runner outside tagged releases (D26) (§10 F7).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- btrsmith:tests/macos/PlayerPan.btrc
- btrsmith:tests/macos/SharedGPUComposition.btrc
- btrsmith:tests/macos/AlbumHoverJourney.btrc
- btrsmith:tests/macos/ApplicationJourney.btrc
- btrsmith:tests/macos/LibraryScrollProfile.btrc
- btrsmith:tests/macos/PortableCoverage.md
- tools/runbook/presets/stage7-btrsmith-portable.toml

**Must not touch**

- btrc `src/**`
- `btrsmith:src/**`

**Steps**

1. Branch codex/cx-r-22.
2. Three authors port the rows listed as still unported: strike glyphs across drag, section click and persistence, seek button and repeat, mute restoration, metronome persistence and save failure, restart-restored cycles, header and transport geometry, the compositor rows, and the library-profile rows.
3. Compile through both frontends on the macOS runner.
4. Write the preset for the real-song runs on the Mac.

**Acceptance**

- [ ] Every PortableCoverage.md row maps to an executable; both frontends build in the cloud; macOS compile and run in MAC-R-04
- [ ] MAC-R-04 runs every row on both frontends

**Risks**

- Real songs are private and Mac-only; hosted runners lack a real GPU.

#### Stage 16: C1 constructs, then C4 (approved, D19)

<a id="cx-c-01"></a>

##### CX-C-01 · One-command Mac checkpoint script for bucket-2 evidence (memory A/B, budget scenarios, D5 gate, BTRSmith, pin bump), with a Linux dry-run test

- **Owner:** Codex · **Group:** C · **Stage:** Stage 16-21 (Mac evidence tooling) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 3 agent-hours
- **PLAN items:** `btrsmith-c-compat-regression` (one-command preparation for every rerun); Stage 15 method memory rows required by ccompat-r18, ccompat-c2-schema/c2-integrate and ccompat-c3-schema-vocabulary/c3-integrate (tooling only)
- **Depends on:** none
- **Parallel-safe with:** CL-C-00, CL-C-01, CL-C-02, CL-C-03, CL-C-04

> **Writer note:** `CL-R-02`'s runbook engine overlaps; keep this script as the bucket-2 wrapper, and `CL-R-02` may later expose it as a `ccompat` preset. `tools/bench/scripts/README.md` is append-only and shared with `CL-R-02` (§3.3, §9 items 11 and 13).

**Owned paths**

- tools/bench/scripts/ccompat_checkpoint.sh (new)
- tools/bench/scripts/README.md (one new table row only)
- src/tests/python/test_ccompat_checkpoint_script.py (new)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `tools/compiler_codegen/**`
- `src/runtime/c/**`
- tools/NativeHeaderReader.cpp
- tools/budget_bench.py (hotspot) and every other existing script under tools/bench/scripts/
- Makefile, flake.nix, flake.lock, `nix/*`
- PLAN.md, AGENTS.md, docs/design/plan-reference.md
- `src/tests/fixtures/compiler_boundaries/**`

**Steps**

1. Branch codex/cx-c-01 from main.
2. Write ccompat_checkpoint.sh with these options: --parent SHA, --commit SHA, --memory, --budget SCENARIOS, --gate, --btrsmith PATH, --bump-btrsmith-pin, --logdir DIR, --dry-run. It composes only the existing scripts.
3. Parent and commit worktrees go under ~/.cache/btrc/bench.noindex/ccompat/\<sha> (never /tmp). Build each btrcc with withlock.sh btrcc-build build_btrcc.sh.
4. --memory: three alternating instr.sh runs per binary under withlock.sh bench.
5. --budget: bench.sh for both frontends, running the standing-approval quiet check first when bucket 1 provides one, and otherwise printing that the wall-clock half needs a quiet window.
6. --gate: withlock.sh gate batch_gate.sh, passing the BTRSmith clone when given.
7. --bump-btrsmith-pin runs only after a GREEN gate: nix flake lock --update-input btrc, application-frontend-check on the pinned flake, an unsigned commit, then the push.
8. Write summary.json: for each binary, instructions retired, peak footprint, the C compiler that built it and its size, the deltas in %, and the host provenance string 'Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0'. Also write a human summary.txt. Exit non-zero if the memory delta is above 1%, and flag above 0.3%.
9. --dry-run prints the exact command plan without executing anything, so it runs on Linux.
10. Add test_ccompat_checkpoint_script.py: bash -n, plus the dry-run plan for three representative option sets checked against expected command lines. Add the README row.
11. Open a draft PR against main for CI; report in the PR body.

**Acceptance**

- [ ] pytest src/tests/python/test_ccompat_checkpoint_script.py green on Linux; bash -n clean; shellcheck clean if available in the dev shell
- [ ] The dry-run output for MAC-C-02's and MAC-C-09's invocations matches the commands those packets list
- [ ] Draft PR with ci.yml green (run id; macos.yml/windows.yml as they run on PRs); PR body lists commits, tests with pass/skip counts, CI run ids and deferrals; Claude integrates it

**Risks**

- It cannot be exercised for real outside macOS; the first MAC packet that uses it (MAC-C-02) is its acceptance run, and MAC-C-01 deliberately uses batch_gate.sh directly.
- If bucket 1 adds a quiet-check script later, wire it in through a separate small PR rather than duplicating its logic.

#### Stage 18: Multi-dimensional arrays, alone (approved, D19)

<a id="cx-c-02"></a>

##### CX-C-02 · Optional devex fuzz pass over C4, C2 and Stage 18 syntax (formatter and LSP only, no compiler change)

- **Owner:** Codex · **Group:** C · **Stage:** Stage 18 exit (devex follow-up) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ccompat-c2-integrate` / ccompat-r17-multidimensional-arrays (devex follow-up; precedent: stage16/devex-c1-fixes)
- **Depends on:** [CL-C-22](claude.md#cl-c-22)
- **Why not now:** Fuzzes syntax the compilers only accept after C4, C2 and Stage 18 merge (the formatter validates input with the Python parser).
- **Parallel-safe with:** CL-C-24

> **Review change:** Owned paths narrowed: as written it held the formatter and LSP files the C3 lane edits (`CL-C-23`, `30`, `31`, `32`, `35`) (§10 C9).

**Owned paths**

- new test files under src/tests/formatter/ and src/tests/lsp/
- the single src/devex file each finding names, added to Owned paths only when no CL-C packet holds it
- `src/tests/c_compat/*.btrc` whitespace-only reformatting produced by make format-btrc

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `tools/compiler_codegen/**`
- `src/runtime/c/**`
- src/devex/lsp/catalog/generated.py
- src/devex/vscode/config/grammar.json (vocabulary is Claude's)
- any non-whitespace change to `src/tests/**` corpus programs
- PLAN.md, docs/design/plan-reference.md
- src/devex/lsp/features/completion.py and src/devex/formatter/{lexing,engine}.py while CL-C-23…35 are in flight; a defect there becomes REQUEST(CL-C-…)

**Steps**

1. Branch codex/cx-c-02 from main after Stage 18 lands.
2. Generate fuzz inputs from the accepted c_compat corpus and c2/c3_c4 probe sources: conditional regions (balanced, unbalanced, nested, around braceless bodies), unions, typedef records, anonymous members, designators (.f = / [k] =), compound literals, bit-fields (named and unnamed), FAM structs, int g[2][3].
3. Check formatter idempotence (format twice equals format once) and token preservation. Check LSP document symbols, hover, navigation and semantic tokens on the same files, and that dead #if lines get none.
4. For each defect: a minimal reproduction plus a fix in formatter or LSP code, with a test. Anything that needs a parser or compiler change is filed for the integrator to make a Claude packet (do not fix).
5. Draft PR; report.

**Acceptance**

- [ ] pytest src/tests/formatter and make test-lsp green; make format-check green on the whole tree
- [ ] Every fixed defect has a regression test; the PR lists filed compiler requests separately
- [ ] ci.yml green on the draft PR (run id); PR body has commits, test counts, run ids, deferrals

**Risks**

- Low priority filler: Codex should take it only when UI work is blocked.
- Must finish before CL-C-30 (r16) starts touching src/devex/formatter.

#### Stage 19: C3 vocabulary and specifier lanes

<a id="cx-c-03"></a>

##### CX-C-03 · Optional devex fuzz pass over C3 and goto syntax (formatter and LSP only, no compiler change)

- **Owner:** Codex · **Group:** C · **Stage:** Stage 19/20 exit (devex follow-up) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ccompat-c3-integrate` / ccompat-r11-goto-labels (devex follow-up)
- **Depends on:** [CL-C-37](claude.md#cl-c-37)
- **Why not now:** Fuzzes C3 and goto syntax that only exists after c3-integrate.
- **Parallel-safe with:** CL-C-38, CL-C-39, CL-C-40

> **Review change:** Owned paths narrowed: as written it held the formatter and LSP files the C3 lane edits (`CL-C-23`, `30`, `31`, `32`, `35`) (§10 C9).

**Owned paths**

- new test files under src/tests/formatter/ and src/tests/lsp/
- the single src/devex file each finding names, added to Owned paths only when no CL-C packet holds it
- `src/tests/c_compat/*.btrc` whitespace-only reformatting produced by make format-btrc

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `tools/compiler_codegen/**`
- `src/runtime/c/**`
- src/devex/lsp/catalog/generated.py
- src/devex/vscode/config/grammar.json
- any non-whitespace change to corpus programs
- PLAN.md, docs/design/plan-reference.md
- src/devex/lsp/features/completion.py and src/devex/formatter/{lexing,engine}.py while CL-C-23…35 are in flight; a defect there becomes REQUEST(CL-C-…)

**Steps**

1. Branch codex/cx-c-03 from main after CL-C-37.
2. Fuzz inputs: east const, per-level pointer qualifiers, restrict, register/auto/_Thread_local, inline/_Noreturn, _Static_assert at three positions, _Alignas/_Alignof, wide and UTF literals, 1.5L, hex floats, .5/1.f, variadic ', ...', va_arg, labels (before declarations, at block end, in case bodies, a: b:), goto.
3. Check formatter idempotence and token preservation; LSP keyword completion, label navigation, and qualifier rendering in hover and symbols.
4. Fix formatter/LSP defects with tests; file compiler-side issues for the integrator; draft PR; report.

**Acceptance**

- [ ] pytest src/tests/formatter and make test-lsp green; make format-check green
- [ ] Every fixed defect has a regression test; compiler requests listed separately
- [ ] ci.yml green on the draft PR (run id); PR body has commits, test counts, run ids, deferrals

**Risks**

- Should land before MAC-C-09's final gate; if late, it moves to the first bucket-3 batch without blocking the bucket-2 exit.

#### Stage 22: P0 entry, parity inventory, adaptations, toolchain matrix, device registry

<a id="cx-p1-01"></a>

##### CX-P1-01 · BTRSmith P0 inventory: every product journey and native package contract classified on the six slices

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 22 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-p0-inventory`
- **Depends on:** none
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-01, MAC-P1-02

> **Writer note:** BTRSmith `docs/NativePlatformPlan.md` is shared append-only with `CL-UIA-03`, which adds a separate section (§9 item 11). Needs Codex access to BTRSmith (§7 Q19).

**Owned paths**

- schiffy91/btrsmith: docs/PlatformInventory.toml (new; follow BTRSmith's docs naming if it differs)
- schiffy91/btrsmith: tests/packaging/PlatformInventory.py (new verifier, modelled on tests/packaging/BuildArtifacts.py)
- schiffy91/btrsmith: docs/NativePlatformPlan.md (a new 'P0 inventory' totals section only)

**Must not touch**

- the btrc repository (Claude records the PLAN progress entry and the platform-parity pointer)
- BTRSmith product sources, ApplicationSession/ApplicationView/GUIApplication and the Make graph (hotspots)
- btrc tools/qualification/denominators.toml (public repo; BTRSmith's denominator stays in the private repo)

**Steps**

1. Branch codex/cx-p1-01 in schiffy91/btrsmith from main. Read BTRSmith issue #15 (MVP epic), docs/HWW.md, docs/DD.md, docs/NativePlatformPlan.md, the PRD's post-MVP section (D25) and `docs/product/*`; read btrc docs/design/platform-parity.md P0, platform-adaptations.md and tools/qualification/schema.py (SubjectKind.JOURNEY, TARGET_SLICES, the InventoryRows compact form).
2. Enumerate journeys: Library, search/filters, Settings, import, playback, practice, rendering, input, persistence, restoration, plus the desktop-only control surfaces (btrsmithctl/MCP, D25). Enumerate the native package contracts: SQLite, YAML, zlib, miniz, pugixml, vgmstream, PSARC, Sloppak. Fan out at most 6 read-only product-area reviewers (PLAN Stage 22 shape) and merge their rows.
3. Write one compact row per journey and per package, with a cell for each of windows-x64, windows-arm64, ios-device, ios-simulator, android-arm64 and android-x86_64. Each cell carries its class (equivalent/adapted/os-restricted/missing), implementation state, owner milestone (`W2/I1/I2/A1/A2/P4/UI*`), the regression tests that pin it, and its evidence status (nothing 'passed'). Rows that depend on an unanswered adaptation question cite the platform-adaptations.md contract number and owner 'platforms-p0-adaptations'. D25 rows: btrsmithctl/MCP is desktop-only, and plug-in hosting is excluded on mobile by product policy, not by the OS.
4. Freeze a BTRSmith-local denominator release 'btrsmith-p0-inventory-\<date>' inside the TOML.
5. Verifier: load the file with btrc's tools.qualification.schema from the flake-pinned btrc; recompute the journey and package sets from the BTRSmith tree (PRD journey list, package manifests) and fail on drift; check 100% coverage of rows x 6 slices.
6. Have a skeptical read-only reviewer check 30 sampled cells, apply its findings, and write the per-slice totals into NativePlatformPlan.md.
7. Open a draft PR to BTRSmith main (it has no CI until Stage 38, D26). The PR body carries the protocol report: commits, test counts and deferrals.

**Acceptance**

- [ ] nix develop --command python3 -m pytest tests/packaging/PlatformInventory.py -q passes in the BTRSmith clone
- [ ] 100% of journeys and package contracts x 6 slices classified; per-slice equivalent/adapted/os-restricted/missing totals reported
- [ ] Reviewer sample of 30 cells recorded with findings applied
- [ ] Draft PR from codex/cx-p1-01 with the protocol report

**Risks**

- Codex needs read/write access to the private schiffy91/btrsmith repository.
- BTRSmith's flake pin may predate tools/qualification TARGET_SLICES (stage22/p0-inventory); then the verifier needs a pin bump, which is Claude's (D4).
- Classes for rows that depend on the adaptation answers can change after CX-P1-02's sign-off, so re-check them then.

<a id="cx-p1-02"></a>

##### CX-P1-02 · Finish platform-adaptations.md for owner sign-off and reconcile the inventory classes

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 22 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p0-adaptations`
- **Depends on:** none
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CX-P1-01, CX-P1-03, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-01, MAC-P1-02

**Owned paths**

- docs/design/platform-adaptations.md
- docs/design/platform-inventory.toml (class, owner and reason cells of rows the ten contracts cover; nothing else)

**Must not touch**

- tools/qualification/denominators.toml (release p0-inventory-2026-10-02-native-worker stays frozen)
- `tools/qualification/*.py`
- `src/stdlib/**` (no provider work here)
- docs/design/platform-parity.md (totals change goes to Claude as a fragment in the PR body)
- PLAN.md
- `src/compiler/**`, `src/language/**`

**Steps**

1. Re-verify the three sources the Windows drafter cited from memory (the logon-trigger example, the notification-area overview and the WinHTTP overview) and every other link; fix the URLs and access dates.
2. Add a 'Recommended answers' section for Q1-Q10, each with its trade-off and its per-platform row consequences, consistent with D22/D24/D25 and Stage 29's exit (MSIX validates). Defaults to propose: Q1 typed outcome errors (FileSystemError/AppError) everywhere; Q2 an opaque grant owned by DirectoryHandle; Q3 GlobalShortcut in GUI, a new Notifications owner shared with macOS/Linux, Browser in App, PluginHost beside Audio; Q4 MSIX with its consequences recorded on rows 4, 7 and 9; Q5 named pipes; Q6 LockFileEx documented as mandatory; Q7 HTTPServer OS-restricted on iOS unless a journey needs it, Android grant check following target API 36 with 37 anticipated; Q8 Process stays OS-restricted on Android; Q9 HttpURLConnection over D22 JNI, no Cronet; Q10 BGContinuedProcessingTask optional above the floor.
3. Run two read-only adversarial reviewers (platform facts against official docs; consistency with the existing stdlib owners and failure channels) and one parity reviewer (consistency with platform-inventory.toml and platform-parity.md). Resolve every blocking finding in a Review section.
4. Reconcile platform-inventory.toml cells for the operations named in the ten contracts with the recommended answers; keep the denominator, ids and slice set unchanged; run test_platform_inventory.py.
5. PR body: the Q1-Q10 recommendations for the owner, the recomputed per-slice totals as a fragment for platform-parity.md's '#### P0 inventory' table, reviewer files, and the protocol report. When the owner signs off, flip the header from Draft to Approved with the date (one follow-up commit on the same branch).

**Acceptance**

- [ ] python3 -m pytest src/tests/python/test_platform_inventory.py -q passes with the frozen denominator (1,944 slots) unchanged
- [ ] Two adversarial reviewers and one parity reviewer leave no unresolved blocking finding (review files listed in the PR body)
- [ ] Owner sign-off recorded in the document header (or the orchestrator's approved substitute rule)
- [ ] git diff --check clean; draft PR from codex/cx-p1-02 with the protocol report

**Risks**

- The Stage 22 exit needs the owner's sign-off; PLAN's standing approvals do not name the adaptations, so the packet cannot close on reviewers alone.
- Answers to Q2/Q3 shape later UI contracts (UI7 services, Stage 32); keep them as recommendations, not interface commitments.

#### Stage 23: P1 provisioning (toolchains, simulators, SDK, VM, signing, devices)

<a id="cx-p1-03"></a>

##### CX-P1-03 · Windows ARM64 runner job: native btrcc bootstrap, MSVC/LLVM probe and wgpu ARM64 link (stand-in for the declined Windows VM)

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 23 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `tooling-windows-ci-arm64-llvm`; `tooling-windows-vm` (D8 declines a local VM; the windows-11-arm runner running a Linux-cross-built btrcc is the stand-in evidence)
- **Depends on:** [CL-UIA-02](claude.md#cl-uia-02)
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CX-P1-01, CX-P1-02, CX-P1-04, CX-P1-05, CX-P1-06, MAC-P1-01, MAC-P1-02

> **Writer note:** `CL-UIA-02` is on `main` (batch 13), so this starts now. Q20's default is in force; without the workflows permission use the `ci/proposed/` fallback (evidence one batch later). The workflow triggers on push and pull_request to `main`, each with a paths filter that includes the workflow file itself, plus `workflow_dispatch`. A matrix pytest job needs a `fragment: ci/tiers.toml` row, and that PR takes the main-tier CI slot (§3.2).

> **Review change:** Waits for `CL-UIA-02`'s workflow-class policy: until it lands, a new workflow with a paths filter fails `test_ci_workflow_contracts.py` in every unit shard (§10 C1).

**Owned paths**

- .github/workflows/windows-arm64.yml (new)
- tools/windows_toolchain/ (new: msvc_probe.ps1, wgpu_link_smoke.c, README.md)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- .github/workflows/ci.yml, macos.yml, windows.yml (Claude)
- Makefile, flake.nix, flake.lock, `nix/*`
- `src/compiler/**`, `src/language/**`, `tools/compiler_codegen/**`, `src/runtime/**`, tools/NativeHeaderReader.cpp
- docs/design/platform-toolchain-matrix.md and docs/qualification/devices.toml (evidence rows go to Claude as PR-body fragments)
- `src/tests/fixtures/expected-skips/*.json` (fragments only)

**Steps**

1. Read windows.yml: the zig install with SHA-256 (:83-95), the btrcc transpile and build (:104-115), the three-stage bootstrap (:121), the sample golden (:136). Read platform-toolchain-matrix.md 'Windows ARM64 and the MSVC question' and platform-target-contract.md sections 1.2 and 1.9.
2. windows-arm64.yml: triggers are push and pull_request to `main`, each with a paths filter (the workflow itself, `tools/windows_toolchain/**`, `src/compiler/**`, `src/runtime/**`, `src/stdlib/**`), plus workflow_dispatch, on runs-on windows-11-arm. Use actions/setup-python 3.13 (arm64) and zig-aarch64-windows-0.16.0.zip with its SHA-256 from ziglang.org's index.json; pin every action by commit as ci.yml does.
3. Mirror windows.yml for aarch64: transpile dist/btrcc-windows.c with the Python compiler; zig cc -target aarch64-windows-gnu with the same strict flags and -I src/runtime/windows -include btrc_win_compat.h; run the three-stage bootstrap with BTRC_CC='zig cc -target aarch64-windows-gnu' and the sample golden; check the PE machine (0xAA64) of btrcc.exe.
4. VM stand-in: an ubuntu-latest job cross-builds btrcc.exe for aarch64-windows-gnu with zig and uploads it. The ARM64 job runs it on a corpus program and compares the C byte-for-byte with the natively built btrcc.
5. msvc_probe.ps1: use vswhere to find Visual Studio; report cl.exe (assert >= 19.40 for the pinned aarch64-pc-windows-msvc19.40.0 triple), the Windows SDK version and clang --version as JSON. Then build and run a strict C11 hello with clang --target=aarch64-pc-windows-msvc19.40.0 against the MSVC CRT.
6. wgpu link smoke: download wgpu-windows-aarch64-msvc-release.zip v27.0.4.0 and verify its SHA-256 (CL-P1-02's digest if merged, otherwise compute and report it). Compile wgpu_link_smoke.c (calls wgpuCreateInstance and reports whether an adapter request returned) with the MSVC triple and run it.
7. Open a draft PR from codex/cx-p1-03. The PR body carries the protocol report plus proposed text for the matrix's 'Unavailable evidence' rows and the devices.toml mac-m1-max stand_in for tooling-windows-vm.

**Acceptance**

- [ ] windows-arm64.yml green on windows-11-arm on the draft PR (run id); ci.yml, macos.yml and windows.yml unaffected
- [ ] btrcc.exe is PE ARM64 and its three-stage bootstrap is byte-identical
- [ ] Cross-built (Linux zig) and native ARM64 btrcc.exe emit byte-identical C for the sample
- [ ] msvc_probe JSON shows cl.exe >= 19.40, or a failure, which is reported as a Stage 24 finding against the windows-aarch64-msvc row
- [ ] MSVC-ABI hello and the wgpu link smoke run, or the exact failure is reported

**Risks**

- windows-11-arm availability to this repository is unverified (marked ⚠ in PLAN).
- Pushing a new workflow file needs a token with the workflow scope.
- The hosted runner has no GPU adapter: prove the link and instance creation only.
- A bootstrap failure caused by the compiler or runtime becomes a Claude request (a new CL packet), not a fix here.

#### Stage 25: P1 test hosts and P2 runtime parity

<a id="cx-p1-04"></a>

##### CX-P1-04 · iOS test-host spike: simulator executor (spawn and app modes) with hand-written C11 fixtures on a GitHub macOS runner

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-host-ios` (spike: simulator executor and test-host app bundle)
- **Depends on:** [CL-UIA-02](claude.md#cl-uia-02)
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CL-P1-03, CL-P1-04, CL-P1-05, CL-P1-06, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-05, CX-P1-06, MAC-P1-02

> **Writer note:** `CL-UIA-02` is on `main` (batch 13), so this starts now. Q20's default is in force; without the workflows permission use the `ci/proposed/` fallback (evidence one batch later). The workflow triggers on push and pull_request to `main`, each with a paths filter that includes the workflow file itself, plus `workflow_dispatch`. A matrix pytest job needs a `fragment: ci/tiers.toml` row, and that PR takes the main-tier CI slot (§3.2).

> **Review change:** Waits for `CL-UIA-02`'s workflow-class policy: until it lands, a new workflow with a paths filter fails `test_ci_workflow_contracts.py` in every unit shard (§10 C1).

**Owned paths**

- tools/target_hosts/ios/ (new: simhost.py with IOSSimulatorHost, executor.py with IOSSimulatorExecutor, app/ with an Info.plist template and host_main.c, fixtures/, README.md; tools/target_hosts/ stays a namespace directory with no parent __init__.py)
- .github/workflows/host-ios.yml (new)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- `src/compiler/**`, `src/language/**`, `tools/compiler_codegen/**`, `src/runtime/**`, tools/NativeHeaderReader.cpp, generated files
- `src/tests/**` (the runner core is CL-P1-17)
- .github/workflows/{ci,macos,windows}.yml, Makefile, flake.nix, `nix/*`
- `docs/design/**`, PLAN.md, AGENTS.md

**Steps**

1. IOSSimulatorHost: list with xcrun simctl list -j; create btrc-host on the newest iOS runtime if missing; boot and wait with simctl bootstatus -b; shut down or erase between runs on request.
2. Spawn mode: xcrun simctl spawn \<udid> \<exe> args, passing the environment through `SIMCTL_CHILD_*`. Capture stdout, stderr and the exit status. Prove that a timeout kills the spawned process (and record how signals propagate).
3. App mode: host_main.c redirects stdout and stderr to files under $HOME in the app's data container, calls the program entry renamed with -Dmain=btrc_program_main, writes an exit_status file and exits. The bundle has an Info.plist (CFBundleIdentifier dev.btrc.testhost.\<id>, MinimumOSVersion 17.0) and an ad-hoc codesign -s - signature. Then: simctl install, simctl launch --terminate-running-process, poll the status file through simctl get_app_container \<udid> \<bundle> data, collect the outputs, simctl uninstall. Record the cold-launch time.
4. Fixtures: strict C11 programs for stdout, stderr, exit 3, abort, timeout, large output, argv, env and cwd, built with xcrun --sdk iphonesimulator clang -target arm64-apple-ios17.0-simulator -std=c11 -pedantic-errors -Wall -Wextra -Werror.
5. IOSSimulatorExecutor has the run(ExecutionRequest) -> ExecutionResult shape that CL-P1-17 freezes (fields as in that packet); it stays standalone until CL-P1-17 lands.
6. host-ios.yml: push and pull_request to `main`, each with paths `tools/target_hosts/ios/**` and the workflow itself, plus workflow_dispatch, on macos-15. Record xcodebuild -version and the runtimes; run both modes over the fixtures; assert exit codes, byte-exact output, the timeout kill and a fresh container per app-mode run. Add an iPad simulator destination beside the iPhone one, and check that the app's Info.plist declares `UIDeviceFamily` [1,2] (iOS and iPadOS are one lane).
7. Open a draft PR from codex/cx-p1-04 with the protocol report.

**Acceptance**

- [ ] host-ios.yml green on the draft PR (run id), with every fixture passing in both modes
- [ ] Report: runner Xcode version (a stand-in, not 27A266a), runtime, per-fixture results and the cold-launch time
- [ ] No file changed outside the owned paths

**Risks**

- simctl spawn's timeout and exit-status semantics need proof.
- The -Dmain rename may be fragile on btrc-emitted C. If it is, file a request that becomes a Claude packet: 'test-host entry-symbol option', paired in both compilers (proposed CL-P1-21).
- New workflow files need a push token with the workflow scope.

<a id="cx-p1-05"></a>

##### CX-P1-05 · Android test-host spike and the CI emulator: KVM x86_64 emulators, shell and NativeActivity modes on GitHub Linux runners

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** yes · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p1-host-android` (spike: emulator executor and NativeActivity test host); `tooling-android-ci-emulator`
- **Depends on:** [CL-UIA-02](claude.md#cl-uia-02)
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CL-P1-03, CL-P1-04, CL-P1-05, CL-P1-06, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-06, MAC-P1-02

> **Writer note:** `CL-UIA-02` is on `main` (batch 13), so this starts now. Q20's default is in force; without the workflows permission use the `ci/proposed/` fallback (evidence one batch later). The workflow triggers on push and pull_request to `main`, each with a paths filter that includes the workflow file itself, plus `workflow_dispatch`. A matrix pytest job needs a `fragment: ci/tiers.toml` row, and that PR takes the main-tier CI slot (§3.2).

> **Review change:** Waits for `CL-UIA-02`'s workflow-class policy: until it lands, a new workflow with a paths filter fails `test_ci_workflow_contracts.py` in every unit shard (§10 C1).

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- tools/target_hosts/android/ (new: avd.py with AvdManager, executor.py with AndroidEmulatorExecutor, app/ as a Gradle project with a pinned wrapper (Gradle 9.6.0, AGP 9.4.0, minSdk 29, target/compileSdk 36, hasCode=false NativeActivity, host_main.c with android_main), fixtures/, README.md)
- .github/workflows/host-android.yml (new)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)
- src/tests/python/test_android_host_versions.py (new: host-android.yml's sdkmanager packages against `nix/platforms.nix`)

**Must not touch**

- `src/compiler/**`, `src/language/**`, `tools/compiler_codegen/**`, `src/runtime/**`, generated files
- `src/tests/**` other than the two test files above
- .github/workflows/{ci,macos,windows}.yml, Makefile, flake.nix, `nix/*` (read only; the nix .#platforms shell is CL-P1-02)
- `docs/design/**`, PLAN.md

**Steps**

1. host-android.yml on ubuntu-latest, triggered on push and pull_request to `main` (each with a paths filter that includes the workflow itself and `tools/target_hosts/android/**`) plus workflow_dispatch: enable KVM with the udev rule for /dev/kvm; actions/setup-java with JDK 17. `nix/platforms.nix` is the single version source: sdkmanager (accepting licences, approved by D8) installs exactly the revisions it pins (the NDK, cmdline-tools, platform-tools, build-tools, the emulator, platforms 29 and 36, and the x86_64 `google_apis` system images for API 29 and 36), and test_android_host_versions.py asserts that the workflow's package list equals them. Add no 16 KiB image: platforms.nix pins the 16 KiB (`ps16k`) image only for API 36 on Apple silicon, so 16 KiB pages are a Mac arm64 run (MAC-P1-03). Hosted runners never enter `.#platforms` (its closure is 17.75 GB). Cache the SDK and the AVD snapshots keyed on the versions. The emulator runs only there; the cloud container has no KVM.
2. AvdManager: create and boot headless (-no-window -no-audio -no-boot-anim -gpu swiftshader_indirect), wait for sys.boot_completed, check the page size, kill.
3. Shell mode: NDK clang --target=x86_64-linux-android29 (and aarch64 build-only); adb push to /data/local/tmp/btrc/\<run>/; run through adb shell with the shell protocol's exit status and toybox timeout; keep stdout and stderr separate (stderr to a file that is pulled).
4. App mode: the program is built as libbtrcprogram.so with -Dmain=btrc_program_main. android_main runs it on a thread, redirects stdout and stderr to files in ANativeActivity internalDataPath and writes exit_status. Then: adb install -r, am start -W -n \<pkg>/android.app.NativeActivity, poll run-as \<pkg> cat files/exit_status, collect, uninstall. Debug-signed by AGP. Check the LOAD alignment of the .so with llvm-readelf -l (0x4000).
5. Fixtures as in the iOS spike. AndroidEmulatorExecutor has the CL-P1-17 protocol shape.
6. Open a draft PR from codex/cx-p1-05 with the protocol report.

**Acceptance**

- [ ] host-android.yml green on the draft PR (run id): the API 29 and API 36 x86_64 emulators boot, and both modes pass every fixture
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_android_host_versions.py -q` passes
- [ ] The .so is 16 KiB-aligned; boot, install and launch timings reported
- [ ] README gives one command per action

**Risks**

- Emulator boot flakiness on hosted runners (retry and snapshot cache).
- Gradle and AGP downloads in CI.
- arm64-v8a images cannot run accelerated on x86_64 runners, so android-aarch64 execution is the Mac's (MAC-P1-08).
- -Dmain fragility: same request path as CX-P1-04.

<a id="cx-p1-06"></a>

##### CX-P1-06 · Windows test-host spike: a native executor with job-object timeouts on windows-latest and windows-11-arm

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `platforms-p1-host-windows` (spike: native executor and Linux-built bundles)
- **Depends on:** [CL-UIA-02](claude.md#cl-uia-02)
- **Parallel-safe with:** CL-P1-01, CL-P1-02, CL-P1-03, CL-P1-04, CL-P1-05, CL-P1-06, CX-P1-01, CX-P1-02, CX-P1-03, CX-P1-04, CX-P1-05, MAC-P1-02

> **Writer note:** `CL-UIA-02` is on `main` (batch 13), so this starts now. Q20's default is in force; without the workflows permission use the `ci/proposed/` fallback (evidence one batch later). The workflow triggers on push and pull_request to `main`, each with a paths filter that includes the workflow file itself, plus `workflow_dispatch`. A matrix pytest job needs a `fragment: ci/tiers.toml` row, and that PR takes the main-tier CI slot (§3.2).

> **Review change:** Waits for `CL-UIA-02`'s workflow-class policy: until it lands, a new workflow with a paths filter fails `test_ci_workflow_contracts.py` in every unit shard (§10 C1).

**Owned paths**

- tools/target_hosts/windows/ (new: executor.py with WindowsNativeExecutor, bundle.py manifest writer, fixtures/, README.md)
- .github/workflows/host-windows.yml (new)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- `src/compiler/**`, `src/language/**`, `src/runtime/**`, generated files
- `src/tests/**`
- .github/workflows/{ci,macos,windows}.yml, windows-arm64.yml (CX-P1-03), Makefile, flake.nix
- `docs/design/**`, PLAN.md

**Steps**

1. host-windows.yml triggers on push and pull_request to `main`, each with a paths filter that includes the workflow itself and `tools/target_hosts/windows/**`, plus workflow_dispatch. Linux job: build the fixtures plus at most 5 existing corpus programs for windows-x86_64 and windows-aarch64, using today's --target support in both compilers and zig cc -target x86_64-windows-gnu / aarch64-windows-gnu with windows.yml's exact strict flags and overlay. Write a bundle manifest (program, argv, timeout, expected-stdout digest) and upload it as an artifact.
2. Windows jobs, matrix [windows-latest, windows-11-arm]: download and run WindowsNativeExecutor. It wraps subprocess.Popen in a Job Object (ctypes CreateJobObjectW, AssignProcessToJobObject, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; document the assignment race), uses TerminateJobObject on timeout, captures stdout and stderr as bytes, and maps NTSTATUS crash codes. It runs from an unrelated working directory and from a path with spaces and non-ASCII characters.
3. Fixtures include a child that spawns a grandchild, to prove the tree kill leaves no orphan.
4. WindowsNativeExecutor has the CL-P1-17 protocol shape. Open a draft PR from codex/cx-p1-06 with the protocol report.

**Acceptance**

- [ ] host-windows.yml green on windows-latest and windows-11-arm (run ids)
- [ ] The tree-kill fixture leaves no surviving process; ARM64 PE executables run natively
- [ ] The corpus programs match their goldens through both compilers

**Risks**

- windows-latest is Windows Server 2025, a stand-in for the Windows 11 x64 slice.
- windows-11-arm availability (⚠).

<a id="cx-p1-07"></a>

##### CX-P1-07 · Windows host integration and CI lane: the runner executor, the ABI fixture and the full applicable corpus on x64 and ARM64

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-host-windows` (runner executor and ABI fixture run); `platforms-p2-ci-lanes` (Windows x64 and ARM64 lanes)
- **Depends on:** [CX-P1-06](#cx-p1-06); [CL-P1-17](claude.md#cl-p1-17); [CL-P1-13](claude.md#cl-p1-13); [CL-P1-16](claude.md#cl-p1-16)
- **Why not now:** Needs the frozen executor protocol and runner (CL-P1-17), the ABI fixture (CL-P1-13) and the target probes (CL-P1-16).
- **Parallel-safe with:** CX-P1-08, CX-P1-09, CL-P1-19, CL-P1-20

> **Review change:** Adds the provider-suite job later Stage 26–31 packets need: windows.yml runs a fixed module list, and nothing else ran the new platform suites (§10 C6, F6).

**Owned paths**

- tools/target_hosts/windows/ (executor conformed to src/tests/target_runner.TargetExecutor and registered as windows-native)
- .github/workflows/host-windows.yml (extended with the corpus lane)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- src/tests/target_runner.py and src/tests/btrc/test_target_abi_fixture.py (Claude; request changes)
- compiler, runtime, specs, generated files, the existing workflows
- `src/tests/fixtures/expected-skips/*.json` and target-applicability.toml (fragments to Claude)

**Steps**

1. Conform WindowsNativeExecutor to the frozen protocol and register it.
2. Linux job: python3 -m src.tests.target_runner --target windows-x86_64 --frontend both --compile-only --bundle out/x64 (and windows-aarch64), uploaded as an artifact.
3. Windows jobs: python -m src.tests.target_runner --execute-bundle out/\<arch> --executor windows-native with BTRC_TEST_CAPABILITIES=windows-native; run the run mode of test_target_abi_fixture.py against target_abi.expected.
4. Upload the logs, JUnit and ledger records and the skip report; put the windows expected-skip and applicability fragments as the `fragment:` commit (§3.5).
5. Triggers: pull_request (paths `src/compiler/**`, `src/runtime/**`, `src/stdlib/**`, `tools/target_hosts/windows/**`) and workflow_dispatch.
6. Add a provider-suite job to host-windows.yml that runs `python -m pytest src/tests/python/test_windows_*.py src/tests/python/test_native_ui_*.py -k windows` with BTRC_TEST_CAPABILITIES=windows-native and uploads its skip report as its last step, so later provider packets never edit workflows.

**Acceptance**

- [ ] The ABI fixture passes on windows-latest and windows-11-arm through both frontends (run ids)
- [ ] The lane runs the whole applicable corpus and publishes per-frontend pass/fail/restricted counts; failures go to CL-P1-18's triage, and the lane is green after the fix waves
- [ ] Draft PR from codex/cx-p1-07 with the protocol report

**Risks**

- Hosted Windows minutes are long for a full corpus through both frontends; shard by topic if needed.

<a id="cx-p1-08"></a>

##### CX-P1-08 · iOS host integration and CI lane: the simulator executor, the ABI fixture and the full applicable corpus on macos-15

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p1-host-ios` (runner executor and ABI fixture run); `platforms-p2-ci-lanes` (iOS simulator lane)
- **Depends on:** [CX-P1-04](#cx-p1-04); [CL-P1-17](claude.md#cl-p1-17); [CL-P1-13](claude.md#cl-p1-13); [CL-P1-16](claude.md#cl-p1-16)
- **Why not now:** Needs the runner core (CL-P1-17), the ABI fixture (CL-P1-13), the probes (CL-P1-16) and the iOS spike (CX-P1-04).
- **Parallel-safe with:** CX-P1-07, CX-P1-09, CL-P1-19, CL-P1-20

> **Review change:** Adds the provider-suite job later Stage 26–31 packets need: windows.yml runs a fixed module list, and nothing else ran the new platform suites (§10 C6, F6).

**Owned paths**

- tools/target_hosts/ios/ (executor conformed and registered as ios-simulator)
- .github/workflows/host-ios.yml (extended with the corpus lane)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- src/tests/target_runner.py, src/tests/btrc/test_target_abi_fixture.py (Claude)
- compiler, runtime, specs, generated files, the existing workflows
- expected-skips and applicability (fragments to Claude)

**Steps**

1. Conform IOSSimulatorExecutor to the frozen protocol and register it.
2. On macos-15, under nix develop (as macos.yml does): python3 -m src.tests.target_runner --target ios-aarch64-simulator --frontend both --executor ios-simulator. Use spawn mode for the corpus and app mode for the ABI fixture (cold launch).
3. Run test_target_abi_fixture.py's run mode with BTRC_TEST_CAPABILITIES=ios-simulator.
4. Upload the logs, JUnit, ledger records and skip report; record the runner Xcode as stand-in provenance; put the fragments as the `fragment:` commit (§3.5).
5. Add a provider-suite job to host-ios.yml that runs `python -m pytest src/tests/python/test_ios_*.py src/tests/python/test_native_ui_*.py -k ios` with BTRC_TEST_CAPABILITIES=ios-simulator and uploads its skip report as its last step, so later provider packets never edit workflows.

**Acceptance**

- [ ] The ABI fixture passes on the simulator through both frontends in app mode (run id)
- [ ] The full applicable corpus runs and its counts are published; the lane is green after the fix waves
- [ ] Draft PR from codex/cx-p1-08 with the protocol report

**Risks**

- The pinned-Xcode evidence comes only from MAC-P1-08.
- Hosted macOS concurrency is limited; shard by topic.

<a id="cx-p1-09"></a>

##### CX-P1-09 · Android host integration and CI lane: the emulator executor, the ABI fixture and the full applicable corpus on x86_64 emulators

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p1-host-android` (runner executor and ABI fixture run); `platforms-p2-ci-lanes` (Android emulator lane)
- **Depends on:** [CX-P1-05](#cx-p1-05); [CL-P1-17](claude.md#cl-p1-17); [CL-P1-13](claude.md#cl-p1-13); [CL-P1-16](claude.md#cl-p1-16)
- **Why not now:** Needs the runner core (CL-P1-17), the ABI fixture (CL-P1-13), the probes (CL-P1-16) and the Android spike (CX-P1-05).
- **Parallel-safe with:** CX-P1-07, CX-P1-08, CL-P1-19, CL-P1-20

> **Review change:** Adds the provider-suite job later Stage 26–31 packets need: windows.yml runs a fixed module list, and nothing else ran the new platform suites (§10 C6, F6).

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- tools/target_hosts/android/ (executor conformed and registered as android-emulator)
- .github/workflows/host-android.yml (extended with the corpus lane)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- src/tests/target_runner.py, src/tests/btrc/test_target_abi_fixture.py (Claude)
- compiler, runtime, specs, generated files, the existing workflows, flake.nix
- expected-skips and applicability (fragments to Claude)

**Steps**

1. Conform AndroidEmulatorExecutor to the frozen protocol and register it.
2. On the KVM ubuntu runner: python3 -m src.tests.target_runner --target android-x86_64 --frontend both --executor android-emulator on the API 29 and API 36 x86_64 AVDs. Use shell mode for the corpus and NativeActivity app mode for the ABI fixture; add the 16 KiB x86_64 image if CX-P1-05 found one.
3. android-aarch64: compile-only in CI (--compile-only); execution is MAC-P1-08.
4. Upload the logs, JUnit, ledger records and skip report; put the fragments as the `fragment:` commit (§3.5).
5. Add a provider-suite job to host-android.yml that runs `python -m pytest src/tests/python/test_android_*.py src/tests/python/test_native_ui_*.py -k android` with BTRC_TEST_CAPABILITIES=android-emulator and uploads its skip report as its last step, so later provider packets never edit workflows.

**Acceptance**

- [ ] The ABI fixture passes through both frontends on API 29 and API 36 x86_64 emulators (run id)
- [ ] The android-x86_64 applicable corpus runs and its counts are published; android-aarch64 compiles everything applicable; the lane is green after the fix waves
- [ ] Draft PR from codex/cx-p1-09 with the protocol report

**Risks**

- Emulator runtime for a full corpus through two frontends; shard by topic and reuse booted AVDs.

<a id="cx-p1-10"></a>

##### CX-P1-10 · Stage 25 stdlib portability fixes outside the compiler's import closure

- **Owner:** Codex · **Group:** P1 · **Stage:** Stage 25 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p2-portable-corpus` (stdlib fixes outside the compiler's import closure)
- **Depends on:** [CL-P1-18](claude.md#cl-p1-18)
- **Why not now:** Fixes come from the triage ledger (CL-P1-18).
- **Parallel-safe with:** CL-P1-19, CL-P1-20, CX-P1-07, CX-P1-08, CX-P1-09

> **Writer note:** `Callback.btrc` moved out of this packet: the self-hosted compiler imports `Library.Callback` directly, so fixes there are Claude's, via `CL-P1-20` (§3.4, §9 item 5).

> **Review change:** Its root modules feed `btrc.symbols`, whose header is a CRC over every root module, so `generated-check` (a prerequisite of `test-btrc`) fails without the `derived:` commit (§10 C3).

**Owned paths**

- only files named by triage among src/stdlib/{Random,SPSC,Set,List,Array,BitPattern,Pattern,DateTime,CLI}.btrc, src/stdlib/Graph/ and src/stdlib/Realtime/ (portable primitives only)
- new corpus regression programs with goldens under src/tests/stdlib/ for the fixes

**Must not touch**

- the compiler's stdlib import closure: Callback, Vector, Map, Strings, Result, Bytes, Timer, Platform, JSON, TOML, IO, Console, Iterable, Math, OwnedBuffer, FileSystem/, Digest/, BackgroundJobs/ (request a Claude fix via CL-P1-20)
- Stage 26 provider files (Process, Terminal, HTTP, Regex, LocalApplicationChannel, Daemon)
- `src/compiler/**`, `src/runtime/**`, `src/language/**`, generated files (src/stdlib/btrc.symbols, btrc.lock) except in the final `derived:` commit
- existing macOS/Linux goldens (must stay byte-identical)

**Steps**

1. Before editing a module, confirm it is outside the compiler's transitive import closure (grep 'import Library.' from the modules src/compiler/btrc imports). If it is inside, file the item to CL-P1-20.
2. Fix each routed item without platform-specific copies of pure algorithms (P2). Use C4 #if guards or adaptation diagnostics only where the platform lacks the facility.
3. Add a regression program; run it through both compilers locally on Linux and through the host lanes (gh workflow run `host-*.yml` --ref codex/cx-p1-10).
4. End the branch with `fragment:` (any btrc.toml change) and then `derived: regenerate` (btrc.symbols changes whenever a root module changes). Paste btrc.symbols' owner-line diff in the PR body (§3.4). Open a draft PR from codex/cx-p1-10 with the protocol report.

**Acceptance**

- [ ] Every routed item fixed with a regression program passing through both frontends on Linux (make test-btrc, make test-btrc-selfhost for the new programs) and on the affected lanes (run ids)
- [ ] macOS/Linux goldens unchanged; no file outside the owned set

**Risks**

- Many portable failures will sit in compiler-import modules, so this packet may stay small; that is expected.

#### Stage 26: P3 OS services

<a id="cx-p2-01"></a>

##### CX-P2-01 · Windows OS-services provider design (FileSystem, Process, Terminal, Daemon, LocalApplicationChannel, BackgroundJobs)

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p3-fs-windows[design]`; `platforms-p3-process-terminal[design]`; `platforms-p3-jobs-ipc[design]`
- **Depends on:** none
- **Parallel-safe with:** CX-P2-02, CX-P2-03

**Owned paths**

- docs/design/windows-os-services.md (new)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/runtime/**`
- `src/stdlib/**` (design only; no code)
- docs/design/platform-adaptations.md (owner sign-off pending; propose deltas in the new doc)
- PLAN.md
- AGENTS.md/CLAUDE.md
- docs/design/plan-reference.md

**Steps**

1. Read AGENTS.md, PLAN.md Stages 24-27, platform-parity.md P3/W1, platform-adaptations.md Windows rows 1, 1b, 2, 4, 5 and 7, and platform-target-contract.md §2 (hosted availability) and §5 (provider filters and the platform-directory rule).
2. Read the current owners: FileSystem/{FileSystem,FileSystemHandles,FileTree,ApplicationDirectories}.btrc (Windows refusals at FileSystemHandles.btrc:551, :1285 and :2019, and at IO.btrc:249), Process.btrc, `Terminal/*`, `Daemon/*`, `LocalApplicationChannel/*`, `BackgroundJobs/*` and src/runtime/windows/README.md.
3. For each owner, specify the Windows provider shape that satisfies Stage 24 §5.2: provider modules under \<Group>/Windows/ with os=["windows"], the portable seam that replaces each runtime Platform.isWindows() refusal, and each [[native.bindings]] header with its symbol list (for example FileSystem/Windows/Win32FileSystem.h: CreateFileW, NtCreateFile, GetFileInformationByHandleEx, ReplaceFileW, MoveFileExW, LockFileEx, SHGetKnownFolderPath, SetSecurityInfo). Check each symbol against the zig 0.16.0 MinGW headers. Bindings must be read through the native reader for x86_64/aarch64-windows-gnu, with no hosted_abi.toml additions.
4. Decide where root modules (Process.btrc) get their Windows provider, since the root package has no providers today: either a root [[package.providers]] with a platform directory, or a move into a group. List any compiler-import consequence.
5. Write a 'Requests to Claude' table: the exact launch-seam helper signatures CL-P2-02 must ship (STARTUPINFOEXW handle list, a job object with kill-on-close, stdio pipes, bounded capture, wait with timeout, tree terminate, UTF-8→UTF-16 argv quoting, launch-failure codes), any hosted-ABI or flake needs, and the compat shims in src/runtime/windows that CL-P2-14 can retire after migration.
6. Write the test plan per exit, naming the new `src/tests/python/test_windows_*.py` drivers, the `src/tests/native/*_windows/` fixtures and their skip-ledger rules: junction swap during traversal, permission denial, long/UNC/non-ASCII paths, interrupted replace, LockFileEx contention, the argv quoting matrix, timeout tree-kill, console password with redirected stdin, and named-pipe peer identity with single instance.
7. Record the defaults taken for adaptations Q4, Q5 (named pipes) and Q6 (LockFileEx under AdvisoryFileLock), each marked as awaiting the owner's sign-off. Open a draft PR from codex/cx-p2-01.

**Acceptance**

- [ ] docs/design/windows-os-services.md covers every Windows row of adaptation contracts 1, 1b, 2, 4, 5 and 7 and the exits of the three P3 items, with file-level owners, binding symbol lists, test module names and the Requests-to-Claude table.
- [ ] ci.yml lint and format-check run green on the draft PR (run id reported); `git diff --check` is clean.
- [ ] CL-P2-01's review leaves no unresolved blocking finding, and Claude records the approval in PLAN.md.
- [ ] The PR body reports commits, open questions and deferrals.

**Risks**

- The adaptations doc is unsigned, so defaults may be overturned.
- MinGW headers expose only part of winternl.h/NtCreateFile; the design must name a fallback.
- The design may assume reader behaviour for windows-gnu triples that is unproven until Stage 24 §3.

<a id="cx-p2-02"></a>

##### CX-P2-02 · HTTP transport contract (interface freeze), curl-free test endpoints and Browser.open owner proposal

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `platforms-p3-sockets-http[contract]`
- **Depends on:** none
- **Parallel-safe with:** CX-P2-01, CX-P2-03

**Owned paths**

- docs/design/http-transport.md (new)

**Must not touch**

- `src/stdlib/HTTP/**` (design only)
- `src/compiler/**`
- `src/language/**`
- flake.nix
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Read HTTP/HTTPClient.btrc (the curl child process at lines 1-110), HTTPSocket.btrc, HTTPServer.btrc, HTTPFraming.btrc, the corpus programs `src/tests/stdlib/Http*.btrc`, adaptations rows 6 and 10, and D22.
2. Specify the transport seam: a provider-selected module behind HTTPClient. It preserves maxResponseBytes, binary bodies, a redirect limit, timeouts, cancellation, the TLS trust and hostname failures, and the existing error channel and messages.
3. Specify the providers: linux on the libcurl library with the system trust store (no executable); macos and ios on NSURLSession, as separate MacOS/ and IOS/ modules sharing portable code; windows on WinHTTP with Schannel; android on HttpURLConnection over JNI (needs CL-P2-09) or the Cronet C API (adaptations Q9).
4. Specify the Winsock port of HTTPSocket and HTTPServer: WSAStartup ownership, SOCKET handles, closesocket, WSAGetLastError mapping and SO_EXCLUSIVEADDRUSE.
5. Specify the test endpoints: an HTTPServer loopback endpoint plus a pytest-hosted TLS endpoint (Python ssl) with a per-run CA trusted only by the test. Name the trust mechanism per platform without disabling verification: CAINFO, a pinned test anchor, a `CurrentUser\Root` install and removal on Windows, and a debug network-security-config. Also specify the PATH-scrub proof that no curl executable is used.
6. Propose the Browser.open owner (adaptations Q3) with providers ShellExecuteExW, UIApplication open and Android intent, mapped to the packets that implement each (CX-P2-09/10/11/12/42). Open a draft PR from codex/cx-p2-02.

**Acceptance**

- [ ] http-transport.md names the interface, providers, error mapping, test endpoints and curl-free proof, plus the Claude requests (flake inputs to CL-P2-04).
- [ ] CL-P2-01's review leaves no unresolved blocking finding; approval recorded in PLAN.md.
- [ ] ci.yml lint and format-check are green on the draft PR (run id).

**Risks**

- Trusting a test CA under WinHTTP requires a cert-store change on the runner.
- NSURLSession completion blocks or delegates may need interop steps 3/6.
- The Android transport waits for the JNI slice or the owner's Q9 answer.

<a id="cx-p2-03"></a>

##### CX-P2-03 · Mobile storage, non-seekable stream and grant contract

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `platforms-p3-fs-mobile[contract]`
- **Depends on:** none
- **Parallel-safe with:** CX-P2-01, CX-P2-02

**Owned paths**

- docs/design/mobile-storage.md (new)

**Must not touch**

- `src/stdlib/**` (design only)
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Read ApplicationDirectories.btrc, FileSystem.btrc, FileSystemHandles.btrc, IO.btrc, GUI/IDirectoryPicker.btrc (DirectoryPickerOutcome), adaptations row 7 and Q2, and the platform-parity P3 filesystem bullets plus the I1/A1 storage bullets.
2. Specify the app roots: the iOS container (NSFileManager URLsForDirectory, Library/Caches, NSTemporaryDirectory) through an Objective-C binding, and Android filesDir/cacheDir delivered by the app host. The Stage 25 test host passes them first; CX-P2-41 later supplies Context.getFilesDir. A missing root fails explicitly.
3. Specify an additive IO.btrc contract: a non-seekable byte source, a bounded import into app storage (size cap, cancellation, temp file plus rename), and revocation and unavailable-file errors in FileSystemError. IO and FileSystem are compiler imports, so every change is additive and bootstrap-checked.
4. Answer Q2 with a recommendation: either an opaque grant owned by DirectoryHandle or a separate DocumentTree owner. Map what lands in Stage 26 (CX-P2-14), I1 (CX-P2-37) and A1 (CX-P2-42).
5. Write the simulator and emulator test plan and the adaptation diagnostics, exact text per adaptations. Open a draft PR from codex/cx-p2-03.

**Acceptance**

- [ ] mobile-storage.md specifies the roots, stream, bounded import, grant owner and errors, with a packet mapping.
- [ ] CL-P2-01's review leaves no unresolved blocking finding; approval recorded in PLAN.md.
- [ ] ci.yml lint and format-check are green (run id).

**Risks**

- Q2 is unanswered by the owner.
- Additive IO.btrc changes still alter btrcc's own build and need a bootstrap.

<a id="cx-p2-04"></a>

##### CX-P2-04 · Windows FileSystem provider I: exact handles, snapshots, reparse-safe traversal, long/UNC/non-ASCII paths, durable replace

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-p3-fs-windows[handles-paths-replace]`
- **Depends on:** [CL-P2-01](claude.md#cl-p2-01); stage24:platforms-p1-native-import-targets → [CL-P1-10](claude.md#cl-p1-10); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14); stage25:platforms-p1-host-windows → [CX-P1-07](#cx-p1-07); stage25:platforms-p2-runtime-semantics → [CL-P1-19](claude.md#cl-p1-19); [CL-P1-15](claude.md#cl-p1-15); [CL-P1-20](claude.md#cl-p1-20)
- **Why not now:** Needs the approved Windows design (CL-P2-01), Stage 24 sub-batches 3-4 (Win32 header reads for windows-gnu, provider filters with the platform-directory rule) and Stage 25's Windows host and runtime semantics.
- **Parallel-safe with:** CX-P2-07, CX-P2-09, CX-P2-13, CL-P2-02, CL-P2-05

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Lands through `CL-P2-27`, which checks btrcc's own C for every host entry and runs the native Windows bootstrap; this packet is done when `CL-P2-27` is (§10 C7).

> **Review change:** Waits for `CL-P1-20`, which holds the same closure files during Stage 25 triage (§10 C7).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/FileSystem/Windows/ (new: provider classes and the Win32FileSystem.h binding header)
- src/stdlib/FileSystem/FileSystemHandles.btrc
- src/stdlib/FileSystem/FileSystem.btrc
- src/stdlib/FileSystem/FileTree.btrc
- src/stdlib/IO.btrc (only the Windows FileSnapshotRead path at :249)
- fragment (not held): src/stdlib/FileSystem/btrc.toml (isolated fragment commit)
- src/stdlib/FileSystem/README.md
- src/tests/native/filesystem_windows/ (new)
- src/tests/python/test_windows_filesystem_handles.py (new)
- docs/design/platform-inventory.toml (`Library.FileSystem*` windows cells only)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `tools/compiler_codegen/**`
- tools/NativeHeaderReader.cpp
- `src/runtime/c/**`
- `src/runtime/windows/**` (shim retirement is CL-P2-14)
- src/stdlib/FileSystem/ApplicationDirectories.btrc (CX-P2-05)
- src/stdlib/btrc.symbols and btrc.lock except in an isolated derived: commit
- flake.nix, Makefile, conftest.py, native_plan.py
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md, AGENTS.md, docs/design/plan-reference.md

**Steps**

1. Add the Win32FileSystem.h binding (os=["windows"]) per windows-os-services.md, and confirm the native reader extracts it for x86_64- and aarch64-windows-gnu on Linux.
2. Implement the Windows provider for DirectoryHandle.openExact, FileHandle.openExact, RegularFileSnapshot.open and FileTreeSnapshot. It uses CreateFileW with FILE_FLAG_OPEN_REPARSE_POINT|FILE_FLAG_BACKUP_SEMANTICS; NtCreateFile relative to a held root handle per component, refusing reparse points mid-path; GetFileInformationByHandleEx identity (volume serial + FileId); `\\?\` and `\\?\UNC\` forms; and UTF-8↔UTF-16 at the boundary.
3. Make atomic replace durable with ReplaceFileW or MoveFileExW(REPLACE_EXISTING|WRITE_THROUGH) plus FlushFileBuffers, and support large offsets, timestamps and case-insensitive name rules.
4. Replace the Windows refusals at FileSystemHandles.btrc:551 and :1285 and IO.btrc:249 with provider dispatch; Linux/macOS emitted C stays byte-identical.
5. Write tests in src/tests/native/filesystem_windows/ plus test_windows_filesystem_handles.py, run through both frontends. Cover a hostile junction swap during traversal (a racing thread), a path over 260 characters, UNC via `\\localhost\C$` (classified skip if the runner denies it), non-ASCII names, an interrupted replace and the case rules. Linux/macOS skip rules travel as a fragment.
6. FileSystem is a compiler import: build your own btrcc, run make bootstrap, and transpile BtrccMain.btrc, cli/WindowsMain.btrc (windows-x86_64 and windows-aarch64) and cli/MacOSMain.btrc with zero warnings.
7. Open a draft PR from codex/cx-p2-04, and file each needed compat-shim retirement as a request to CL-P2-14.

**Acceptance**

- [ ] The Windows run on the draft PR (host-windows.yml's provider-suite job, or `gh workflow run host-windows.yml --ref codex/cx-p2-04` once that file is on main) shows test_windows_filesystem_handles.py passed with skips classified, and the native three-stage bootstrap green with the new provider (run id).
- [ ] On Linux: draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts, the make bootstrap fixed point (or ci.yml's bootstrap shard, §3.11), and the FileSystem corpus (`src/tests/stdlib/Fs*.btrc`, `FileSystemHandles*.btrc`, FileTreeSnapshotReal.btrc) unchanged through both compilers.
- [ ] macos.yml is green (run id).
- [ ] The PR body reports commits, test counts, CI run ids and deferrals.

**Risks**

- MinGW's winternl.h coverage is partial.
- The runner may deny admin shares (UNC).
- Hosted availability interacts with the remaining runtime Platform branches (Stage 24 §2).
- A compiler-import change needs a 20-minute bootstrap per iteration.

<a id="cx-p2-05"></a>

##### CX-P2-05 · Windows FileSystem provider II: owner-only DACLs, LockFileEx locks, KnownFolder roots, junction-safe recursive delete

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p3-fs-windows[acl-locks-roots-delete]`
- **Depends on:** [CX-P2-04](#cx-p2-04) (ready); stage25:platforms-p2-target-probes → [CL-P1-16](claude.md#cl-p1-16); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Follows CX-P2-04 (the same files). ApplicationDirectories.btrc is also touched by Stage 25's target probes, which land first.
- **Parallel-safe with:** CX-P2-06, CX-P2-07, CX-P2-09, CX-P2-13

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

> **Review change:** Lands through `CL-P2-27`, which checks btrcc's own C for every host entry and runs the native Windows bootstrap; this packet is done when `CL-P2-27` is (§10 C7).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/FileSystem/Windows/
- src/stdlib/FileSystem/FileSystemHandles.btrc (PrivateDirectory, AdvisoryFileLock at :2019)
- src/stdlib/FileSystem/ApplicationDirectories.btrc
- src/stdlib/FileSystem/FileSystem.btrc (recursive delete)
- fragment (not held): src/stdlib/FileSystem/btrc.toml (fragment)
- src/tests/native/filesystem_windows/
- src/tests/python/test_windows_filesystem_handles.py
- docs/design/platform-inventory.toml (own cells)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/runtime/**`
- Platform.btrc (Stage 25)
- flake.nix, Makefile, conftest.py
- .github/workflows/ci.yml, macos.yml, windows.yml
- btrc.symbols/btrc.lock except in a derived: commit
- PLAN.md

**Steps**

1. Give PrivateDirectory.openAbsoluteLeaf and private files a protected owner-only DACL (SetSecurityInfo with PROTECTED_DACL_SECURITY_INFORMATION, using the current user SID from the process token), replacing the root-UID sentinel and verifying the ACL on open.
2. Implement AdvisoryFileLock with LockFileEx/UnlockFileEx, documenting its mandatory semantics per Q6.
3. Resolve the ApplicationDirectories roots with SHGetKnownFolderPath (RoamingAppData, LocalAppData), in UTF-16.
4. Make recursive deletion remove a junction itself without following it, and map permission denial to FileSystemError.
5. Test permission denial (a DACL denying the current user), lock contention between two processes, private-directory DACL inspection, a recursive delete over a junction pointing outside (the target stays untouched) and the app roots through both frontends.
6. Run make bootstrap and the zero-warning transpiles (compiler import), then open a draft PR from codex/cx-p2-05.

**Acceptance**

- [ ] The Windows run passes the new tests plus AdvisoryFileLockReal.btrc and ApplicationDirectories.btrc natively through both frontends (Stage 25 runner) (run id).
- [ ] The Linux bootstrap reaches its fixed point; draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; macos.yml is green.
- [ ] The PR body reports commits, counts, run ids and deferrals.

**Risks**

- Calling LockFileEx 'advisory' needs the owner's Q6 answer.
- Hosted runners run as an administrator, which weakens permission-denial tests.

<a id="cx-p2-06"></a>

##### CX-P2-06 · Windows Process provider over the launch seam, and explicit mobile process refusals

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p3-process-terminal[process]`
- **Depends on:** [CL-P2-02](claude.md#cl-p2-02); [CL-P2-01](claude.md#cl-p2-01); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14); stage25:platforms-p2-target-runner → [CL-P1-17](claude.md#cl-p1-17); stage25:platforms-p1-host-ios → [CX-P1-08](#cx-p1-08); stage25:platforms-p1-host-android → [CX-P1-09](#cx-p1-09); [CL-P1-15](claude.md#cl-p1-15); [CL-P1-20](claude.md#cl-p1-20)
- **Why not now:** Needs the CL-P2-02 launch seam, the approved design and Stage 24/25 provider filters, target runner and mobile hosts.
- **Parallel-safe with:** CX-P2-05, CX-P2-07, CX-P2-09, CX-P2-13

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Lands through `CL-P2-27`, which checks btrcc's own C for every host entry and runs the native Windows bootstrap; this packet is done when `CL-P2-27` is (§10 C7).

> **Review change:** Waits for `CL-P1-20`, which holds the same closure files during Stage 25 triage (§10 C7).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/Process.btrc
- fragment (not held): the Windows and mobile Process provider location fixed by windows-os-services.md (for example src/stdlib/Windows/ProcessProvider.btrc plus a root btrc.toml fragment)
- src/tests/native/process_windows/ (new)
- src/tests/python/test_windows_process.py (new)
- src/tests/python/test_mobile_process_refusals.py (new)
- docs/design/platform-inventory.toml (Library.Process cells)

**Must not touch**

- `src/runtime/c/**` (request changes from Claude)
- `src/compiler/**`
- `src/language/**`
- src/stdlib/btrc.toml except an isolated fragment commit
- `src/stdlib/Daemon/**` (CX-P2-08)
- `src/stdlib/Terminal/**` (CX-P2-07)
- .github/workflows/ci.yml, macos.yml, windows.yml, Makefile, conftest.py
- PLAN.md

**Steps**

1. Implement ChildProcess on Windows over the CL-P2-02 helpers. It covers: argv vector to canonical command line; a Unicode environment block and cwd; pipes with bounded capture; timeout and cancellation through job termination; exit codes (ProcessStatus without WIFEXITED on Windows); and ChildDescriptorMapping limited to stdio, reporting the adaptations diagnostic for any other mapping.
2. Make UnixShell.run on Windows report the adaptations row 1b diagnostic.
3. On iOS and Android, ChildProcess.run, UnixShell.run and Command report the exact adaptations row 1 diagnostics through ExecResult failure, with no link-only stubs.
4. Run the existing Process corpus natively on Windows through the Stage 25 runner (`ChildProcess*.btrc`, CommandBuilder.btrc, Environment.btrc), and add test_windows_process.py: an argv matrix, timeout tree-kill, exit codes and launch failure.
5. Add the mobile refusal tests on the iOS simulator (GitHub macOS runner) and the Android emulator (GitHub ubuntu KVM runner) through both frontends.
6. Process is a compiler import: run make bootstrap and the zero-warning transpiles, then open a draft PR from codex/cx-p2-06.

**Acceptance**

- [ ] The Process corpus and test_windows_process.py pass natively on Windows through both frontends (run id, counts).
- [ ] The mobile refusal tests pass on the simulator and emulator CI runs (run ids); pinned-Xcode acceptance is batched in MAC-P2-01.
- [ ] The Linux make bootstrap reaches its fixed point; draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; macos.yml is green.
- [ ] The PR body report is complete.

**Risks**

- A root module has no provider mechanism today (see the CX-P2-01 decision).
- btrcc runs C compilers through Process, so a Windows Process change alters btrcc on Windows (the native bootstrap must stay green).

<a id="cx-p2-07"></a>

##### CX-P2-07 · Windows Terminal console provider and mobile terminal refusals

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p3-process-terminal[terminal]`
- **Depends on:** [CL-P2-01](claude.md#cl-p2-01); stage24:platforms-p1-native-import-targets → [CL-P1-10](claude.md#cl-p1-10); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14); stage25:platforms-p1-host-windows → [CX-P1-07](#cx-p1-07); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the approved design plus Stage 24 Win32 header reads and provider filters, and Stage 25's Windows host.
- **Parallel-safe with:** CX-P2-04, CX-P2-06, CX-P2-09

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/Terminal/Terminal.btrc
- src/stdlib/Terminal/TerminalPasswordInput.btrc
- src/stdlib/Terminal/Windows/ (new)
- src/stdlib/Terminal/IOS/ and Terminal/Android/ restriction providers (new)
- fragment (not held): src/stdlib/Terminal/btrc.toml (fragment)
- src/tests/native/terminal_windows/ (new)
- src/tests/python/test_windows_terminal.py (new)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/runtime/**`
- src/stdlib/Process.btrc (CX-P2-06)
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Implement the console provider: GetConsoleMode/SetConsoleMode, clearing ENABLE_ECHO_INPUT for passwords and line/processed input for raw mode, with the mode always restored.
2. Read input with ReadConsoleW and convert UTF-16 to UTF-8; take resize from screen-buffer events; replace the signal self-pipe with SetConsoleCtrlHandler.
3. When stdin is not a console, report the adaptations row 2 diagnostic. On iOS and Android, report the exact row 2 diagnostics.
4. Build a ConPTY (CreatePseudoConsole) harness that drives prompt and promptPassword on Windows, plus a redirected-stdin test; add mobile refusal tests.
5. Open a draft PR from codex/cx-p2-07.

**Acceptance**

- [ ] The Windows run passes test_windows_terminal.py and the existing Terminal tests natively through both frontends (run id).
- [ ] The mobile refusal tests pass on the simulator and emulator CI runs (run ids).
- [ ] draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; the PR body report is complete.

**Risks**

- ConPTY availability in the MinGW headers and on hosted runners.

<a id="cx-p2-08"></a>

##### CX-P2-08 · Daemon on Windows (native supervisor) and mobile daemon refusals

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p3-process-terminal[daemon]`
- **Depends on:** [CX-P2-06](#cx-p2-06); [CX-P2-05](#cx-p2-05); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the Windows Process provider (CX-P2-06) and the DACL helpers (CX-P2-05).
- **Parallel-safe with:** CX-P2-09, CX-P2-13, CX-P2-15

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/Daemon/ (Daemon.btrc, `DaemonControl*.btrc`, new Daemon/Windows/, IOS/ and Android/ restriction providers)
- fragment (not held): src/stdlib/Daemon/btrc.toml (fragment)
- src/stdlib/Daemon/README.md
- src/tests/native/daemon_windows/ (new)
- src/tests/python/test_windows_daemon.py (new)

**Must not touch**

- src/stdlib/Process.btrc
- `src/runtime/**`
- `src/compiler/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Implement the native supervisor (adaptations row 4). Start it with DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP|CREATE_BREAKAWAY_FROM_JOB through the seam; stop it with a control request and then TerminateJobObject; take tokens from BCryptGenRandom; give the record and log owner-only DACLs.
2. Make DaemonSpec.renderStartCommand on Windows report its diagnostic. On iOS and Android, DaemonController.start, stop and status and renderStartCommand report the exact row 4 diagnostics.
3. Run stdlib/Daemon.btrc natively on Windows within the corpus runner's 15 s limit through both frontends, and add the start/stop/status, stale-record and token tests.
4. Open a draft PR from codex/cx-p2-08.

**Acceptance**

- [ ] The Windows run passes test_windows_daemon.py and stdlib/Daemon.btrc through both frontends (run id).
- [ ] The mobile refusal tests pass in the simulator and emulator runs.
- [ ] draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; the PR body report is complete.

**Risks**

- Breakaway from the CI job may be refused (JOB_OBJECT_LIMIT_BREAKAWAY_OK).

<a id="cx-p2-09"></a>

##### CX-P2-09 · Native HTTP transports on Linux (libcurl library) and macOS (NSURLSession), loopback/TLS endpoints, curl-free corpus

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p3-sockets-http[transport-unix]`
- **Depends on:** [CL-P2-01](claude.md#cl-p2-01); [CL-P2-04](claude.md#cl-p2-04); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14)
- **Why not now:** Needs the approved transport contract (CX-P2-02 via CL-P2-01), libcurl in the dev shell (CL-P2-04) and Stage 24's provider filters.
- **Parallel-safe with:** CX-P2-04, CX-P2-06, CX-P2-13, CX-P2-15

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/HTTP/HTTPClient.btrc
- src/stdlib/HTTP/Linux/ (new transport provider)
- src/stdlib/HTTP/MacOS/ (new transport provider)
- fragment (not held): src/stdlib/HTTP/btrc.toml (fragment)
- src/stdlib/HTTP/README.md (new)
- `src/tests/stdlib/Http*.btrc` and expected/
- src/tests/native/http/ (new)
- src/tests/python/test_http_transports.py (new)

**Must not touch**

- src/stdlib/HTTP/HTTPSocket.btrc, HTTPServer.btrc, HTTPFraming.btrc (CX-P2-10 ports them)
- `src/compiler/**`
- `src/language/**`
- flake.nix
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Implement the approved transport seam so that HTTPClient.btrc no longer spawns curl.
2. Write the Linux provider over the libcurl easy API (pkg-config libcurl, system trust store, size limit, timeouts, redirect limit, cancellation).
3. Write the macOS provider over NSURLSession with a synchronous wrapper; file a Claude request if a block or delegate shape needs interop step 3/6.
4. Add the test endpoints: HTTPServer for plain loopback and a pytest-hosted TLS server (Python ssl) with a per-run CA. Cover redirects, binary bodies, limits, timeouts, a hostname mismatch, an untrusted CA, connection refused and cancellation.
5. Prove no curl is used by running the HTTP corpus with PATH scrubbed of curl; the test asserts shutil.which('curl') is None.
6. Open a draft PR from codex/cx-p2-09.

**Acceptance**

- [ ] On Linux, the HTTP corpus and test_http_transports.py pass through both frontends with no curl on PATH (counts).
- [ ] On macOS, test_http_transports.py passes on the macos.yml unit shard (run id).
- [ ] draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; the PR body report is complete.

**Risks**

- NSURLSession blocks may need interop features not yet landed.
- libcurl adds a new pkg-config dependency for HTTP users on Linux.

<a id="cx-p2-10"></a>

##### CX-P2-10 · Winsock sockets/server, WinHTTP transport and Browser.open on Windows

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p3-sockets-http[windows]`
- **Depends on:** [CX-P2-09](#cx-p2-09); stage24:platforms-p1-native-import-targets → [CL-P1-10](claude.md#cl-p1-10); stage25:platforms-p1-host-windows → [CX-P1-07](#cx-p1-07); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the shared transport seam and endpoints (CX-P2-09), Stage 24 Win32 header reads and Stage 25's Windows host.
- **Parallel-safe with:** CX-P2-05, CX-P2-08, CX-P2-13, CX-P2-15

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/HTTP/HTTPSocket.btrc
- src/stdlib/HTTP/HTTPServer.btrc
- src/stdlib/HTTP/HTTPFraming.btrc
- src/stdlib/HTTP/Windows/ (new: Winsock and WinHTTP bindings and providers)
- the Browser owner's Windows provider (location per http-transport.md)
- fragment (not held): src/stdlib/HTTP/btrc.toml (fragment)
- src/tests/python/test_windows_http.py (new)
- src/tests/native/http_windows/ (new)

**Must not touch**

- src/stdlib/HTTP/HTTPClient.btrc seam (owned by CX-P2-09 until it merges)
- `src/compiler/**`
- `src/runtime/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Port HTTPSocket and HTTPServer to Winsock: a WSAStartup/WSACleanup owner, SOCKET handles, closesocket, WSAGetLastError mapping and SO_EXCLUSIVEADDRUSE. Loopback stays the default; binding to all interfaces gives the adaptations row 6 warning.
2. Implement the WinHTTP plus Schannel transport (WinHttpOpen through WinHttpReadData), with WinHttpSetTimeouts, a redirect policy and the TLS error mapping.
3. Implement Browser.open with ShellExecuteExW, limited to https: and ms-settings: URLs.
4. Add Windows tests: the HTTP corpus with System32 curl.exe hidden from PATH, a TLS failure with an untrusted test CA, and success with the test CA installed in `CurrentUser\Root` during the test and then removed.
5. Open a draft PR from codex/cx-p2-10.

**Acceptance**

- [ ] The Windows run passes the HTTP client and server corpus plus test_windows_http.py through both frontends with no curl on PATH (run id, counts).
- [ ] Linux and macOS HTTP stay green (ci.yml, macos.yml run ids); the PR body report is complete.

**Risks**

- The cert-store change on the runner must be undone even if the test fails.
- WinHTTP proxy autodetection on runners.

<a id="cx-p2-11"></a>

##### CX-P2-11 · iOS HTTP transport (NSURLSession) and foreground-listener adaptation

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p3-sockets-http[ios]`
- **Depends on:** [CX-P2-09](#cx-p2-09); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14); stage25:platforms-p1-host-ios → [CX-P1-08](#cx-p1-08); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the Unix transports (CX-P2-09), the ios rows and filters (Stage 24) and Stage 25's iOS simulator host.
- **Parallel-safe with:** CX-P2-10, CX-P2-12, CX-P2-14

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/HTTP/IOS/ (new)
- fragment (not held): src/stdlib/HTTP/btrc.toml (fragment)
- src/tests/python/test_ios_http.py (new)

**Must not touch**

- src/stdlib/HTTP/MacOS/ (no aliasing; shared code goes in portable files via CX-P2-09's owner)
- `src/compiler/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Write the IOS/ NSURLSession transport, a separate module per D24 and Stage 24 §5.2 that reuses the portable seam.
2. Adapt HTTPServer.start to a foreground-only listener, giving the adaptations row 6 diagnostic when the listener cannot be held. Document the NSLocalNetworkUsageDescription requirement for app hosts.
3. Record Browser.open on iOS as missing until CX-P2-36 provides UIApplication.
4. Run simulator tests against a host loopback server (the simulator shares the host network): client corpus, TLS failure and cancellation, through both frontends.
5. Open a draft PR from codex/cx-p2-11.

**Acceptance**

- [ ] The iOS simulator run on a GitHub macOS runner (Stage 25 iOS host executor) passes test_ios_http.py through both frontends (run id). Pinned-Xcode acceptance is in MAC-P2-01.
- [ ] The PR body report is complete.

**Risks**

- The hosted runner's Xcode differs from the pinned 27A266a.

<a id="cx-p2-12"></a>

##### CX-P2-12 · Android HTTP transport (HttpURLConnection over JNI or Cronet), loopback listener and network permission states

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p3-sockets-http[android]`
- **Depends on:** [CX-P2-09](#cx-p2-09); [CL-P2-09](claude.md#cl-p2-09); stage25:platforms-p1-host-android → [CX-P1-09](#cx-p1-09); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the JNI call slice (CL-P2-09) for HttpURLConnection, or the owner's Q9 answer for Cronet, plus Stage 25's Android host.
- **Parallel-safe with:** CX-P2-10, CX-P2-11, CX-P2-14

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/HTTP/Android/ (new)
- fragment (not held): src/stdlib/HTTP/btrc.toml (fragment)
- src/tests/python/test_android_http.py (new)

**Must not touch**

- `src/stdlib/Java/**` (CL-P2-09)
- `src/compiler/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Implement the transport through language="java" bindings over android.jar (BTRC_JAVA_CLASSPATH), or through the Cronet C API if Q9 approves it.
2. Add a loopback HTTPServer on 127.0.0.1 with INTERNET. A non-loopback bind without the grant gives the adaptations row 6 diagnostic, and the permission states are distinguished: pending, denied and granted.
3. Enable cleartext for loopback tests only, through the test host's debug network config.
4. Run emulator tests through the Stage 25 Android host (app_process or NativeActivity APK) on a GitHub ubuntu KVM runner, through both frontends.
5. Defer the browser intent to CX-P2-42, then open a draft PR from codex/cx-p2-12.

**Acceptance**

- [ ] The emulator run (API 29 and 36, x86_64) passes test_android_http.py through both frontends (run ids).
- [ ] The PR body report is complete.

**Risks**

- JNI step 4 offers calls only, with no callbacks, which is enough for blocking I/O.
- Q9 is undecided.

<a id="cx-p2-13"></a>

##### CX-P2-13 · Regex/glob/fnmatch parity: vendored POSIX engine on Windows and behaviour checks on all slices

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p3-regex-glob[engine-parity]`
- **Depends on:** [CL-P2-03](claude.md#cl-p2-03); stage25:platforms-p2-target-runner → [CL-P1-17](claude.md#cl-p1-17); [CX-P1-10](#cx-p1-10); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the hosted-ABI route (CL-P2-03) and Stage 25's target runner, which executes the corpus on every slice.
- **Parallel-safe with:** CX-P2-04, CX-P2-06, CX-P2-09, CX-P2-15

> **Review change:** Route (b) only; `src/runtime/windows` is force-included into `btrcc.exe` and its README says the shims are empty by design (§10 C8). Waits for `CX-P1-10`, which may also edit `Pattern.btrc` (§10 C16).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/Regex.btrc
- src/stdlib/Pattern.btrc
- `src/tests/stdlib/Regex*.btrc` and expected/
- src/tests/python/test_regex_parity.py (new)
- src/stdlib/Regex/Windows/ (new provider package with the vendored POSIX engine, its LICENSE and revision; route b)

**Must not touch**

- src/runtime/windows/btrc_win_compat.h
- src/language/hosted_abi.toml (CL-P2-03)
- `src/compiler/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md
- `src/runtime/windows/**` (REQUEST(CL-P2-14))

**Steps**

1. Vendor a pinned POSIX regex implementation (for example the NetBSD/OpenBSD regcomp family) and record its licence and revision.
2. Implement glob and fnmatch for Windows over FindFirstFileExW (UTF-16), honouring the existing flags.
3. Keep the syntax and error contract: `REG_*` errors map to the existing messages, and the malformed-pattern corpus is unchanged.
4. Run the regex, glob and fnmatch corpus on all five slices: linux, macos, windows x64, the iOS simulator (GitHub macOS) and the Android emulator (GitHub ubuntu). Fix bionic or iOS libc differences in the btrc layer, not with per-platform forks.
5. Route (b) only: the engine lives in a stdlib provider package selected for os=windows. Route (a), changing the src/runtime/windows shims that btrcc.exe force-includes, is a REQUEST(CL-P2-14).
6. Open a draft PR from codex/cx-p2-13.

**Acceptance**

- [ ] The Regex, glob and fnmatch corpus, including the malformed-pattern errors, passes on the five slices through both frontends (run ids per slice). Pinned-Xcode iOS acceptance is in MAC-P2-01.
- [ ] The Windows native bootstrap is green, and draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts.
- [ ] The PR body report includes the licence notice.

**Risks**

- Bionic's regex differs on edge cases.
- Licence compatibility of the vendored code.

<a id="cx-p2-14"></a>

##### CX-P2-14 · Mobile storage foundation: app roots, non-seekable streams, bounded import, revocation errors

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p3-fs-mobile[implementation]`
- **Depends on:** [CX-P2-05](#cx-p2-05); [CL-P2-01](claude.md#cl-p2-01); stage25:platforms-p1-host-ios → [CX-P1-08](#cx-p1-08); stage25:platforms-p1-host-android → [CX-P1-09](#cx-p1-09); stage25:platforms-p2-target-probes → [CL-P1-16](claude.md#cl-p1-16); [CL-P1-15](claude.md#cl-p1-15); [CL-P2-27](claude.md#cl-p2-27); [CL-P1-20](claude.md#cl-p1-20)
- **Why not now:** Sequenced after the Windows FileSystem merge (CX-P2-05) per items.json. It also needs the approved mobile contract and Stage 25's mobile hosts and platform codes 4/5.
- **Parallel-safe with:** CX-P2-10, CX-P2-11, CX-P2-12, CX-P2-15

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Waits for `CL-P2-27`: PLAN puts the mobile filesystem after the `FileSystem.btrc` merge (§10 C7).

> **Review change:** Waits for `CL-P1-20`, which holds the same closure files during Stage 25 triage (§10 C7).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/FileSystem/ApplicationDirectories.btrc
- src/stdlib/FileSystem/IOS/ (new)
- src/stdlib/FileSystem/Android/ (new)
- fragment (not held): src/stdlib/FileSystem/btrc.toml (fragment)
- src/stdlib/IO.btrc (additive stream contract)
- src/tests/native/filesystem_mobile/ (new)
- src/tests/python/test_mobile_filesystem.py (new)

**Must not touch**

- `src/stdlib/FileSystem/Windows/**`
- `src/compiler/**`
- `src/runtime/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Resolve the iOS container roots (data, cache, temp) through an Objective-C binding on the ios rows.
2. Take the Android roots from the app host (Stage 25 test host argv or env), failing explicitly when they are absent; CX-P2-41 later swaps in Context.getFilesDir.
3. Add the IO.btrc non-seekable byte-source contract and a bounded import (size cap, cancellation, temp plus rename into app storage).
4. Add the revocation and unavailable-file errors, and give openExact outside the container the adaptations row 7 diagnostic.
5. IO and FileSystem are compiler imports: run make bootstrap and the zero-warning transpiles, and keep Linux/macOS emitted C unchanged.
6. Run the simulator and emulator tests (roots, bounded import, non-seekable read, revoked access) through both frontends, then open a draft PR from codex/cx-p2-14.

**Acceptance**

- [ ] The iOS simulator (GitHub macOS) and Android emulator (GitHub ubuntu KVM) runs pass test_mobile_filesystem.py through both frontends (run ids). Pinned-Xcode acceptance is in MAC-P2-01.
- [ ] The Linux bootstrap reaches its fixed point; draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; the PR body report is complete.

**Risks**

- The Android app-root handoff changes when A1 lands.
- Additive IO changes still re-run the bootstrap.

<a id="cx-p2-15"></a>

##### CX-P2-15 · BackgroundJobs on Windows (winpthreads) and qualification on bionic/iOS

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-p3-jobs-ipc[jobs]`
- **Depends on:** [CL-P2-01](claude.md#cl-p2-01); stage24:platforms-p1-native-import-targets → [CL-P1-10](claude.md#cl-p1-10); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14); stage25:platforms-p2-runtime-semantics → [CL-P1-19](claude.md#cl-p1-19); [CL-P1-15](claude.md#cl-p1-15); [CL-P1-20](claude.md#cl-p1-20)
- **Why not now:** Needs winpthreads extraction from the MinGW sysroot (Stage 24 §3), provider filters and Stage 25's runtime semantics on every target.
- **Parallel-safe with:** CX-P2-09, CX-P2-13, CX-P2-14, CX-P2-16

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Waits for `CL-P1-20`, which holds the same closure files during Stage 25 triage (§10 C7).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- fragment (not held): src/stdlib/BackgroundJobs/btrc.toml (fragment: the NativeThreads.h binding and ProcessThreads providers for windows, ios and android)
- src/stdlib/BackgroundJobs/NativeThreads.h
- src/stdlib/BackgroundJobs/ProcessThreads.btrc
- src/stdlib/BackgroundJobs/{Windows,IOS,Android}/ProcessThreadsProvider.btrc (new)
- src/stdlib/BackgroundJobs/README.md
- src/tests/native/background_jobs/ (target expected variants)
- src/tests/python/test_background_jobs_runtime.py (target parameters)

**Must not touch**

- src/stdlib/BackgroundJobs/WorkerPoolProvider.btrc, HostWorkerPools.btrc, WorkerPools.btrc, Unix/WorkerPoolProvider.btrc (CL-P2-12)
- `src/compiler/**`
- `src/runtime/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Bind winpthreads through NativeThreads.h for windows, and add ProcessThreads providers (thread ids) for windows, ios and android.
2. Run BackgroundJobsConformance.btrc, BackgroundJobsFailures.btrc and NativeWorkerFailures.btrc (cancellation, drain, bounded queue) natively on Windows, the simulator and the emulator through both frontends.
3. Document in the README how thread-pool jobs differ from OS background execution.
4. BackgroundJobs is a compiler import: run make bootstrap and the zero-warning transpiles, then open a draft PR from codex/cx-p2-15.

**Acceptance**

- [ ] The jobs cancellation and drain tests pass on Windows, the iOS simulator and the Android emulator through both frontends (run ids).
- [ ] The Linux bootstrap reaches its fixed point; draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; the PR body report is complete.

**Risks**

- Joining a winpthreads thread differs from a native pthread join on shutdown.

<a id="cx-p2-16"></a>

##### CX-P2-16 · LocalApplicationChannel on Windows (named pipes with peer identity) and mobile restrictions

- **Owner:** Codex · **Group:** P2 · **Stage:** 26 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p3-jobs-ipc[channel]`
- **Depends on:** [CX-P2-05](#cx-p2-05); [CL-P2-01](claude.md#cl-p2-01); stage24:platforms-p1-native-import-targets → [CL-P1-10](claude.md#cl-p1-10); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the DACL helpers (CX-P2-05), the approved transport choice (named pipes, Q5) and Win32 header reads.
- **Parallel-safe with:** CX-P2-10, CX-P2-13, CX-P2-15

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Acceptance no longer asks for a local `make test`, which §3.11 reserves for Claude's batch gate; draft-PR `ci.yml` carries it (§10 C17, F14).

**Owned paths**

- src/stdlib/LocalApplicationChannel/LocalApplicationChannel.btrc (transport seam)
- src/stdlib/LocalApplicationChannel/Windows/ (new: named-pipe provider and LocalPeerCredentialsProvider)
- src/stdlib/LocalApplicationChannel/IOS/ and Android/ restriction providers (new)
- fragment (not held): src/stdlib/LocalApplicationChannel/btrc.toml (fragment)
- src/stdlib/LocalApplicationChannel/README.md
- src/tests/native/local_application_channel/ (Windows variants)
- src/tests/python/test_local_application_channel_runtime.py (Windows parameters)

**Must not touch**

- `src/stdlib/HTTP/**`
- `src/compiler/**`
- `src/runtime/**`
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Implement the named pipe with FILE_FLAG_FIRST_PIPE_INSTANCE and PIPE_REJECT_REMOTE_CLIENTS and an explicit current-user DACL (the default DACL grants Everyone read).
2. Establish peer identity with GetNamedPipeClientProcessId plus a token-SID comparison, and keep single-instance behaviour; the frame format is unchanged.
3. On iOS and Android, give the exact adaptations row 5 diagnostics.
4. Pass the 16 channel tests on Windows through both frontends, then open a draft PR from codex/cx-p2-16.

**Acceptance**

- [ ] The 16 LocalApplicationChannel tests pass natively on Windows (run id); the mobile refusal tests pass in the simulator and emulator runs.
- [ ] draft-PR ci.yml green (13 shards = make test plus test-c11), plus `nix develop --command python3 -m pytest <packet modules and corpus> -n 4 -rs` with counts; the PR body report is complete.

**Risks**

- Q5 (named pipes vs AF_UNIX) is still awaiting the owner's sign-off.

#### Stage 27: W1 Windows host and interop lane I (one ownership design, function tables, early Objective-C and JNI slices, then COM)

<a id="cx-p2-17"></a>

##### CX-P2-17 · COM fixture servers (C side): Linux ComShape proxy counter server and registry-free Windows in-proc DLL

- **Owner:** Codex · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-w1-win32-com-imports[fixture-server]`
- **Depends on:** [CL-P2-06](claude.md#cl-p2-06)
- **Why not now:** A Stage 27 implementation fixture. It starts once function-table dispatch conventions land (CL-P2-06) so it can merge alongside the COM step (CL-P2-10).
- **Parallel-safe with:** CL-P2-09, CL-P2-11, CX-P2-10

> **Writer note:** Pre-assigned: starts the moment CL-P2-06 lands; it gates CL-P2-10 (COM), and through it CL-P2-21 and all three shells (2026-10-03, §5.1).

**Owned paths**

- src/tests/native/com/ (new): ComShape.h, com_counter_server.c, com_fixture_server.c, com_fixture_server.def, build_com_fixture.py
- src/tests/python/test_com_fixture_server.py (new; C-only harness)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/stdlib/COM/**` (CL-P2-10)
- .github/workflows/ci.yml, macos.yml, windows.yml
- PLAN.md

**Steps**

1. Write the ComShape.h proxy per native-interop-ownership.md §2.4: int32_t HRESULT, uint32_t ULONG, GUID, extern IIDs, a flattened IUnknown prefix, and a counter server with live, AddRef and Release hooks.
2. Write the registry-free in-proc server: DllGetClassObject plus IClassFactory, and an object with Clone, IConnectionPointContainer/IConnectionPoint Advise and Unadvise, and an event method. It exports deterministic live and claim counters.
3. Build it with zig cc -target x86_64- and aarch64-windows-gnu -shared.
4. Write a C-only harness for create, alias, QI identity, Clone, Advise, fire, Unadvise inside the event, and release, asserting the counts. On Linux the proxy harness runs under ASan/UBSan.
5. Open a draft PR from codex/cx-p2-17. After merge the directory passes to CL-P2-10.

**Acceptance**

- [ ] The Windows run passes test_com_fixture_server.py on x64 (run id); arm64 follows once the runner exists.
- [ ] The Linux ASan/UBSan proxy harness is green, and the PR body report is complete.

**Risks**

- The fixture's conventions must match the btrc side written in CL-P2-10, so coordinate through the design doc only.

<a id="cx-p2-18"></a>

##### CX-P2-18 · Windows CI matrix workflows: corpus shards x2 frontends x{O0,O2}, ARM64 bootstrap job, MSIX smoke, skip ledger, flake triage

- **Owner:** Codex · **Group:** P2 · **Stage:** 27 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-ci-windows-matrix[workflows]`; `platforms-w1-ci-and-bundle[ci-suite]`
- **Depends on:** [CL-P2-15](claude.md#cl-p2-15); stage23:tooling-windows-ci-arm64-llvm → [CX-P1-03](#cx-p1-03); stage25:platforms-p2-ci-lanes → [CX-P1-07](#cx-p1-07), [CX-P1-08](#cx-p1-08), [CX-P1-09](#cx-p1-09); [CX-P1-03](#cx-p1-03)
- **Why not now:** Needs the Windows bundle (CL-P2-15), proven windows-11-arm runner access (Stage 23) and Stage 25's Windows corpus lane.
- **Parallel-safe with:** CL-P2-12, CL-P2-13, CX-P2-19

> **Writer note:** `windows-arm64.yml` already exists by now (`CX-P1-03` creates it), so this packet extends it; `CX-P1-03` became a dependency (§9 item 3). Expected-skip manifests travel in the `fragment:` commit (§3.5).

**Owned paths**

- .github/workflows/windows-corpus.yml (new; reusable plus pull_request and workflow_dispatch)
- .github/workflows/windows-arm64.yml (extends the file CX-P1-03 creates; not a new file)
- .github/workflows/windows-package-smoke.yml (new)
- fragment (not held): src/tests/fixtures/expected-skips/windows-corpus.json, windows-arm64.json (new; delivered in the `fragment:` commit, and Claude adds the RUNNERS entries)
- src/tests/python/test_ci_workflow_contracts.py (rows for the new workflows only)
- docs/design/ci-health.md (Windows flake-rate section)

**Must not touch**

- .github/workflows/windows.yml, ci.yml, macos.yml (Claude)
- Makefile, src/tests/conftest.py, src/compiler/python/artifacts/archive.py (file requests)
- `src/compiler/**`
- PLAN.md

**Steps**

1. Add sharded corpus jobs through both frontends at O0 and O2 with zig x86_64-windows-gnu through the Stage 25 runner, each with a skip report and skip-gate.
2. Add a test-debug line-mapping job, and SDK-reader plus Win32/COM fixture jobs once CL-P2-10 and CL-P2-11 are on main.
3. Add a windows-11-arm job that builds the arm64 bundle with the Stage 23 Makefile target and runs the native bootstrap.
4. Add an MSIX build/install/uninstall smoke for a hello app, using a test-signing certificate generated per run and never committed.
5. Triage the historical 8-of-15 failure rate and record the flake rate in ci-health.md. Open a draft PR from codex/cx-p2-18.

**Acceptance**

- [ ] Each new workflow runs green on the draft PR (run ids), with no unexpected skips (skip-gate).
- [ ] After integration, CL-P2-18 records 10 consecutive green main runs covering corpus × 2 frontends × {O0, O2}, the x64 and ARM64 bootstrap fixed points and the MSIX smoke.
- [ ] The PR body report is complete.

**Risks**

- Pushing workflow files needs a token with the workflow scope.
- windows-11-arm availability ⚠.
- Windows runner minutes.

#### Stage 28: P4 dependency closure and library artifacts (W1 exit)

<a id="cx-p2-19"></a>

##### CX-P2-19 · BTRSmith Windows launch artifact (packaging/windows shell, zig cross build, both frontends)

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `btrsmith-cross-target-build[windows-shell]`
- **Depends on:** [CL-P2-16](claude.md#cl-p2-16); [CL-R-48](claude.md#cl-r-48)
- **Why not now:** Needs the shared target abstraction (CL-P2-16).
- **Parallel-safe with:** CX-P2-20, CX-P2-21, CX-P2-22

> **Review change:** Its BTRSmith run ids come from `CL-R-48`'s emulator and Windows jobs (§10 F7).

**Owned paths**

- BTRSmith packaging/windows/ (new)
- BTRSmith make/targets/windows-x86_64.mk and windows-aarch64.mk (new)
- BTRSmith tests/windows/LaunchFixture.btrc (new)

**Must not touch**

- BTRSmith make/Config.mk, Toolchain.mk, flake.nix (CL-P2-16)
- btrc repository paths

**Steps**

1. Build a minimal launch fixture app for windows-x86_64 and windows-aarch64 through both frontends with zig MinGW in the cloud.
2. Run it on a BTRSmith workflow_dispatch windows-latest job, measuring the cost per run under D26.
3. Open a draft PR in BTRSmith from codex/cx-p2-19, with the report in its body.

**Acceptance**

- [ ] Both frontends build the launch artifact for both Windows rows, and it runs on windows-latest (run id).
- [ ] The Linux host build is unchanged.

**Risks**

- Codex access to the private BTRSmith repository.
- BTRSmith CI minutes for Windows.

<a id="cx-p2-20"></a>

##### CX-P2-20 · BTRSmith Android launch artifact (thin Gradle/Activity shell, NDK cross build, emulator launch)

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-cross-target-build[android-shell]`
- **Depends on:** [CL-P2-16](claude.md#cl-p2-16); stage23:tooling-android-sdk-ndk → [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03); stage25:platforms-p1-host-android → [CX-P1-09](#cx-p1-09); [CL-R-48](claude.md#cl-r-48)
- **Why not now:** Needs the target abstraction, a pinned NDK/SDK/Gradle and Stage 25's Android host conventions.
- **Parallel-safe with:** CX-P2-19, CX-P2-21, CX-P2-22

> **Review change:** Its BTRSmith run ids come from `CL-R-48`'s emulator and Windows jobs (§10 F7).

**Owned paths**

- BTRSmith packaging/android/ (new; Gradle 9.6.0, AGP 9.4.0, minSdk 29, target 36)
- BTRSmith make/targets/android-aarch64.mk and android-x86_64.mk (new)
- BTRSmith tests/android/LaunchFixture.btrc (new)

**Must not touch**

- BTRSmith make/Config.mk, flake.nix
- btrc repository paths

**Steps**

1. Write a startup-only Java Activity that calls System.loadLibrary, and build the .so files for both ABIs through both frontends with the NDK in the cloud.
2. Launch on the API 29 and 36 x86_64 emulators in BTRSmith's Linux CI with KVM (D26 Linux-only CI).
3. Open a draft PR in BTRSmith from codex/cx-p2-20.

**Acceptance**

- [ ] The APK launches and prints its PASS line on the emulator through both frontends (run id), and the PR report is complete.

**Risks**

- Gradle and Maven downloads through the proxy.
- Emulator flakiness.

<a id="cx-p2-21"></a>

##### CX-P2-21 · BTRSmith iOS launch artifact scripts (thin Xcode shell, device and simulator slices)

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `btrsmith-cross-target-build[ios-shell]`
- **Depends on:** [CL-P2-16](claude.md#cl-p2-16); stage25:platforms-p1-host-ios → [CX-P1-08](#cx-p1-08)
- **Why not now:** Needs the target abstraction and Stage 25's iOS host conventions.
- **Parallel-safe with:** CX-P2-19, CX-P2-20

**Owned paths**

- BTRSmith packaging/ios/ (new: project generation, Info.plist, ad-hoc signing script)
- BTRSmith make/targets/ios-aarch64.mk and ios-aarch64-simulator.mk (new)
- BTRSmith tests/ios/LaunchFixture.btrc (new)

**Must not touch**

- BTRSmith make/Config.mk, flake.nix
- btrc repository paths

**Steps**

1. Generate the Xcode project from the link plan, keeping the device and simulator slices distinct and never swapped.
2. Make the build script one command for MAC-P2-03, and smoke it on a btrc-independent GitHub macOS runner only if BTRSmith's CI budget allows; otherwise it is Mac-only.
3. Open a draft PR in BTRSmith from codex/cx-p2-21.

**Acceptance**

- [ ] The script builds both slices on a macOS host; the pinned-Xcode run and simctl launch are recorded by MAC-P2-03.

**Risks**

- D26 limits BTRSmith macOS CI to tagged releases.

<a id="cx-p2-22"></a>

##### CX-P2-22 · Cross-build driver and dependency manifest; zlib, miniz, libyaml, SQLite for every ABI

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p4-dependency-crossbuild[driver-manifest-core-deps]`; `btrsmith-package-closure[driver-manifest-core-deps]`
- **Depends on:** [CL-P2-16](claude.md#cl-p2-16); stage23:platforms-p1-toolchains → [CL-P1-02](claude.md#cl-p1-02); stage24:platforms-p1-native-plan-toolchain → [CL-P1-11](claude.md#cl-p1-11), [CL-P1-12](claude.md#cl-p1-12); stage24:platforms-p1-cache-identity → [CL-P1-15](claude.md#cl-p1-15); stage24:platforms-p1-abi-fixture → [CL-P1-13](claude.md#cl-p1-13)
- **Why not now:** Needs the BTRSmith target abstraction, the pinned cross toolchains (Stage 23) and link plan v5 cross builds (Stage 24).
- **Parallel-safe with:** CX-P2-25, CL-P2-19, CX-P2-19

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- tools/xbuild/ (new: driver over native_plan.py v5 cross builds, manifest writer)
- docs/qualification/dependency-manifest.toml (new: hash, features, transitive libraries, disabled upstream options and licence per dependency × ABI)
- BTRSmith `packages/zlib/**`, `packages/miniz/**`, `packages/yaml/**`, `packages/sqlite/**` (os/arch/env predicates, Makefile, tests)

**Must not touch**

- tools/native_plan.py (file a request)
- flake.nix, flake.lock and the BTRSmith flake.lock/btrc.lock (CL-P2-17)
- `src/compiler/**`

**Steps**

1. Write the driver: for each dependency × {windows-x86_64, windows-aarch64, android-aarch64, android-x86_64}, build in the cloud under a cache directory (not /tmp, not Drive), with at most 4 concurrent builds and intermediates pruned. The iOS rows run in MAC-P2-03.
2. Record features, transitive libraries, disabled options and licence notices in the manifest.
3. Link each library into the Stage 24 ABI fixture app per target, and check every Android .so for 16 KiB alignment.
4. Open draft PRs in btrc and BTRSmith from codex/cx-p2-22, with lock changes handed to CL-P2-17 as fragments.

**Acceptance**

- [ ] The manifest has rows for every dependency × cloud ABI with hashes and licences, and each library links into the ABI fixture (log per target).
- [ ] Every Android .so is 16 KiB aligned (checker output), and the PR report is complete.

**Risks**

- Disk usage.
- Upstream options that differ per target.

<a id="cx-p2-23"></a>

##### CX-P2-23 · Cross-build pugixml (C++ runtimes per target) and vgmstream with libogg/libvorbis for every ABI

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p4-dependency-crossbuild[pugixml-vgmstream]`; `btrsmith-package-closure[pugixml-vgmstream]`
- **Depends on:** [CX-P2-22](#cx-p2-22)
- **Why not now:** Uses the driver and manifest from CX-P2-22.
- **Parallel-safe with:** CX-P2-24, CX-P2-25

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- BTRSmith `packages/pugixml/**`
- BTRSmith `packages/vgmstream/**` (including the btrc.toml:55 os/arch predicates)
- tools/xbuild/ recipes for these two
- docs/qualification/dependency-manifest.toml (their rows)

**Must not touch**

- tools/native_plan.py
- flake files (CL-P2-17)
- `src/compiler/**`

**Steps**

1. Select the C++ runtime per target (zig libc++ for MinGW, NDK libc++_shared or static), recording the choice.
2. Build vgmstream with its selected codecs and no codec dropped, checking that the feature list equals the host build's.
3. Link each into the ABI fixture and check the 16 KiB alignment, then open draft PRs from codex/cx-p2-23.

**Acceptance**

- [ ] The manifest rows are complete, vgmstream's codec set is identical to the host's, and the link logs and alignment report pass.

**Risks**

- The C++ runtime boundary on MinGW/MSVC (see CX-P2-26).

<a id="cx-p2-24"></a>

##### CX-P2-24 · Cross-build PSARC/Sloppak consumers, FreeType 2.14.3 and image codecs (libpng/libjpeg-turbo) for every ABI

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p4-dependency-crossbuild[psarc-sloppak-freetype-image]`; `btrsmith-package-closure[psarc-sloppak-freetype-image]`
- **Depends on:** [CX-P2-22](#cx-p2-22)
- **Why not now:** PSARC and Sloppak need zlib, miniz and yaml from CX-P2-22 first.
- **Parallel-safe with:** CX-P2-23, CX-P2-25

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- BTRSmith `packages/psarc/**`, `packages/sloppak/**`
- tools/xbuild/ recipes for freetype, libpng and libjpeg-turbo
- docs/qualification/dependency-manifest.toml (their rows)
- fragment (not held): src/stdlib/GUI/btrc.toml FreeType rows and src/stdlib/Image/btrc.toml (fragments only)

**Must not touch**

- tools/native_plan.py
- flake files
- `src/compiler/**`

**Steps**

1. Build each for the cloud ABIs, record them in the manifest, link them into the fixture and check 16 KiB alignment.
2. Submit the FreeType and image rows for windows, ios and android as btrc.toml fragments.
3. Open draft PRs from codex/cx-p2-24.

**Acceptance**

- [ ] The manifest rows are complete, and the link and alignment logs pass.

**Risks**

- The image codecs that Android at API 29 needs (no AImageDecoder).

<a id="cx-p2-25"></a>

##### CX-P2-25 · wgpu-native v27.0.4.0 prebuilt archives per slice: digests, link smoke, btrc_gpu_available() per target

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `tooling-cross-gpu-deps[archives-smoke]`
- **Depends on:** stage23:platforms-p1-toolchains → [CL-P1-02](claude.md#cl-p1-02); stage24:platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14)
- **Why not now:** Stage 23 records the first-download digests and toolchains; Stage 24's env selector is needed for per-slice library rows.
- **Parallel-safe with:** CX-P2-22, CX-P2-23, CX-P2-24

**Owned paths**

- tools/xbuild/gpu/ (new: wgpu-native.toml with url and sha256 per slice, fetch-and-verify script, link smoke C program)
- fragment (not held): src/stdlib/GPU/btrc.toml (fragment: per-slice library rows with env selectors)
- src/tests/python/test_gpu_cross_link.py (new)

**Must not touch**

- flake.nix, `nix/**` (CL-P2-29 wires the pins)
- `src/runtime/gpu/**` and the Makefile gpu target (file requests)
- `src/compiler/**`

**Steps**

1. Fetch the 8 archives and verify each against the matrix digests from Stage 23, recording any that are missing.
2. Extract the headers and libraries, then link the smoke per target and run where executable: Windows x64 gnu on windows-latest (WARP/D3D12, result recorded), the Android x86_64 emulator, and the iOS simulator on a GitHub macOS runner. The arm64 msvc link is deferred to CX-P2-26.
3. Hand the flake wiring request to CL-P2-29, then open a draft PR from codex/cx-p2-25.

**Acceptance**

- [ ] Pins with sha256 exist for all 8 slices, and btrc_gpu_available() results are recorded per executable target (run ids).

**Risks**

- Hosted runners have no GPU, so WARP or SwiftShader results are not hardware evidence.

<a id="cx-p2-26"></a>

##### CX-P2-26 · Windows ABI route research and runner probe: MSVC aarch64 for wgpu-native, CRT/allocator pairing

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-w1-toolchain-abi-route[research-probe]`
- **Depends on:** [CX-P2-25](#cx-p2-25); [CX-P2-22](#cx-p2-22); stage23:tooling-windows-ci-arm64-llvm → [CX-P1-03](#cx-p1-03)
- **Why not now:** Needs the wgpu-native archives, the dependency closure and windows-11-arm access.
- **Parallel-safe with:** CX-P2-27, CX-P2-29

**Owned paths**

- docs/design/windows-abi-route.md (new)
- .github/workflows/windows-msvc-probe.yml (new; dispatch-only)
- src/tests/native/msvc_route/ (new probe sources)
- src/tests/python/test_ci_workflow_contracts.py (rows for this workflow; shared append-only)

**Must not touch**

- src/language/targets.toml (CL-P2-18)
- tools/native_plan.py
- `src/compiler/**`

**Steps**

1. On windows-11-arm, link the wgpu-native msvc archive into a probe with clang --target=aarch64-pc-windows-msvc, the runner's Windows SDK and the MSVC CRT import libraries, and run a compute dispatch.
2. Test CRT and allocator pairing across the boundary (malloc and free on both sides; UCRT vs msvcrt), plus the pugixml C++ runtime boundary.
3. Write the decision draft: keep or remove the windows-aarch64-msvc row, what stays unsupported, and the run ids. Open a draft PR from codex/cx-p2-26.

**Acceptance**

- [ ] The decision draft cites run ids; the probe passes, or its failure is classified.

**Risks**

- MSVC CRT licensing on hosted runners is acceptable for CI but the products must say what they ship.

<a id="cx-p2-27"></a>

##### CX-P2-27 · Packaged assets and non-seekable media sources on every platform

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p4-assets-streams-plugins[assets-streams]`
- **Depends on:** [CX-P2-14](#cx-p2-14); [CL-P2-09](claude.md#cl-p2-09)
- **Why not now:** Needs the mobile stream contract (CX-P2-14) and JNI calls for Android AAssetManager (CL-P2-09).
- **Parallel-safe with:** CX-P2-26, CX-P2-29

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- the packaged-asset owner per mobile-storage.md (for example src/stdlib/Assets/ with Desktop, Windows, IOS and Android providers; new group, with a root [dependencies] fragment)
- BTRSmith packages/psarc and packages/sloppak decoder entry points (stream sources)
- src/tests/python/test_packaged_assets.py (new)

**Must not touch**

- src/stdlib/IO.btrc (owned via CX-P2-14; file follow-ups)
- `src/compiler/**`

**Steps**

1. Read assets from the executable-relative bundle on desktop and Windows, NSBundle on iOS, and AAssetManager on Android.
2. Let the decoders read from asset and stream sources, with a bounded import when random access is required.
3. Run the tests on the simulator and emulator through both frontends, then open draft PRs from codex/cx-p2-27.

**Acceptance**

- [ ] The decoders read from asset and stream sources on the iOS simulator and the Android emulator through both frontends (run ids), and desktop is unchanged.

**Risks**

- Every new stdlib group requires the integrator's fragment work.

<a id="cx-p2-28"></a>

##### CX-P2-28 · Plugin and content inventory: bundled plugins vs data packages, restricted extension points with diagnostics

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `platforms-p4-assets-streams-plugins[plugin-inventory]`
- **Depends on:** [CX-P2-27](#cx-p2-27); stage22:platforms-p0-adaptations → [CX-P1-02](#cx-p1-02)
- **Why not now:** Needs the assets work and the owner's adaptations sign-off (Q3: the PluginHost owner).
- **Parallel-safe with:** CX-P2-29, CX-P2-30

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- BTRSmith inventory file from btrsmith-p0-inventory (plugin rows)
- BTRSmith src/plugins/bundled/ (classification only)
- the PluginHost diagnostics location decided by Q3
- tests for the restricted paths

**Must not touch**

- docs/design/platform-inventory.toml denominators (frozen)
- `src/compiler/**`

**Steps**

1. Inventory bundled plugins separately from data-only song and asset packages, and decide ahead-of-time inclusion per application model.
2. Implement the adaptations row 9 diagnostics with tests, then open draft PRs from codex/cx-p2-28.

**Acceptance**

- [ ] Every plugin row is classified with a test, and no extension point is silently dropped.

**Risks**

- The private BTRSmith inventory may not exist yet (btrsmith-p0-inventory pending).

<a id="cx-p2-29"></a>

##### CX-P2-29 · Package contracts per ABI, data packages: SQLite (migrations, locking), libyaml, zlib, miniz

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-p4-package-contracts[data-packages]`
- **Depends on:** [CX-P2-22](#cx-p2-22); stage25:platforms-p2-target-runner → [CL-P1-17](claude.md#cl-p1-17); [CX-P2-05](#cx-p2-05); [CX-P2-14](#cx-p2-14)
- **Why not now:** Needs the cross-built libraries, Stage 25's target runner and the Windows and mobile filesystems.
- **Parallel-safe with:** CX-P2-30, CX-P2-27

**Owned paths**

- BTRSmith packages/{sqlite,yaml,zlib,miniz}/tests (target runner hooks)

**Must not touch**

- `src/compiler/**`
- the runtime (failures go to Claude as requests)

**Steps**

1. Run each package's conformance and consumer suites per ABI through both frontends: Windows on the runner, Android on the GitHub emulator, iOS in MAC-P2-03.
2. Cover migrations, locking, invalid input and resource closure, and list each failure against the inventory.

**Acceptance**

- [ ] Per-ABI pass reports for both frontends (run ids), with failures listed.

**Risks**

- Emulator storage speed.

<a id="cx-p2-30"></a>

##### CX-P2-30 · Package contracts per ABI, media and archive: pugixml C++ owner, vgmstream callback table, PSARC, Sloppak

- **Owner:** Codex · **Group:** P2 · **Stage:** 28 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-p4-package-contracts[media-archive-packages]`
- **Depends on:** [CX-P2-23](#cx-p2-23); [CX-P2-24](#cx-p2-24); stage25:platforms-p2-target-runner → [CL-P1-17](claude.md#cl-p1-17)
- **Why not now:** Needs the cross-built libraries and Stage 25's target runner.
- **Parallel-safe with:** CX-P2-29, CX-P2-28

> **Review change:** Edits only new parametrization rows of the compiler's interop test (shared append-only, §3.3) (§10 C16).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- BTRSmith packages/{pugixml,vgmstream,psarc,sloppak}/tests
- src/tests/python/test_native_cxx_owners.py (new parametrization rows only; shared append-only) (per-target parametrization only)

**Must not touch**

- `src/compiler/**`

**Steps**

1. Run traversal limits, exact media metadata, channel layouts, seeking and end-of-stream, plus packaged-asset access and sandboxed import, per ABI through both frontends.
2. Send any compiler or runtime defect to Claude.

**Acceptance**

- [ ] Per-ABI pass reports (run ids), with failures listed against the inventory.

**Risks**

- The C++ owner on MinGW.

#### Stage 29: Non-UI platform tracks and interop lane II (Objective-C protocols, then JNI)

<a id="cx-p2-31"></a>

##### CX-P2-31 · Windows ARM64 native qualification on windows-11-arm (bootstrap, corpus shard, ABI fixture, provider suites)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `platforms-w2-arm64[runner-qualification]`
- **Depends on:** [CL-P2-18](claude.md#cl-p2-18); [CX-P2-18](#cx-p2-18)
- **Why not now:** Needs W1 closed with the ABI-route decision and the CI matrix.
- **Parallel-safe with:** CX-P2-32, CX-P2-33, CX-P2-36

> **Writer note:** Expected-skip rules travel in the `fragment:` commit (§9 item 4).

**Owned paths**

- .github/workflows/windows-arm64.yml (after CX-P2-18 merges)
- fragment (not held): src/tests/fixtures/expected-skips/windows-arm64.json (rules delivered in the `fragment:` commit)

**Must not touch**

- Makefile, src/compiler/python/artifacts/archive.py (requests)
- `src/compiler/**`

**Steps**

1. Run the native ARM64 bootstrap fixed point, the corpus shard and the ABI fixture, plus the FileSystem, Process, Terminal, channel and HTTP provider suites, on arm64.
2. Link GPU artifacts per the route decision.
3. Open a draft PR from codex/cx-p2-31.

**Acceptance**

- [ ] windows-11-arm runs are green (run ids); physical hardware is recorded in MAC-P2-05.

**Risks**

- Runner availability ⚠.

<a id="cx-p2-32"></a>

##### CX-P2-32 · WASAPI/MMDevice audio provider (Audio/Windows) with fault fixtures

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-w2-wasapi[provider]`
- **Depends on:** [CL-P2-10](claude.md#cl-p2-10); stage25:platforms-p2-runtime-semantics → [CL-P1-19](claude.md#cl-p1-19); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** WASAPI is COM, so it needs interop step 5 (CL-P2-10).
- **Parallel-safe with:** CX-P2-33, CX-P2-34, CX-P2-38, CX-P2-43

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/Audio/Windows/ (new)
- fragment (not held): src/stdlib/Audio/btrc.toml (fragment)
- src/tests/native/audio/windows/ (new fault fixtures)
- src/tests/python/test_wasapi_runtime.py (new)

**Must not touch**

- `src/stdlib/Audio/MacOS/**`, `Linux/**`
- `src/stdlib/COM/**` (Claude)
- `src/compiler/**`

**Steps**

1. Use IMMDeviceEnumerator, IAudioClient, IAudioRenderClient and IAudioCaptureClient, event-driven buffers on an AvSetMmThreadCharacteristics thread, shared-mode mix-format negotiation with the exclusive options, and an IMMNotificationClient sink for endpoint changes.
2. Handle AUDCLNT_E_DEVICE_INVALIDATED, map the clock through IAudioClock, and keep callbacks allocation-free under the realtime verifier, with terminal-close behaviour.
3. Hosted runners have no endpoints, so use fault fixtures plus the absent-endpoint path.
4. Open a draft PR from codex/cx-p2-32.

**Acceptance**

- [ ] The fault-fixture provider suite passes through both frontends on windows-latest (run id), and the realtime verifier is clean. Physical render and capture are recorded in MAC-P2-05.

**Risks**

- COM sink apartment rules.

<a id="cx-p2-33"></a>

##### CX-P2-33 · Windows GPU foundations: wgpu-native compute, offscreen, async readback, device loss

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-w2-gpu-image-font[gpu]`
- **Depends on:** [CX-P2-25](#cx-p2-25); [CL-P2-29](claude.md#cl-p2-29); [CL-P2-18](claude.md#cl-p2-18)
- **Why not now:** Needs CX-P2-25's per-slice archives with the GPU `btrc.toml` rows CL-P2-29 applies, and the ARM64 route decision.
- **Parallel-safe with:** CX-P2-32, CX-P2-34

> **Review change:** No longer edits `src/runtime/gpu`: its platform branch is a `REQUEST(CL-P2-28)` (§10 C8).

**Owned paths**

- fragment (not held): src/stdlib/GPU/btrc.toml (fragment: windows rows)
- src/stdlib/GPU/Windows/ (new, if needed)
- src/tests/python/test_windows_gpu_runtime.py (new)

**Must not touch**

- Makefile gpu target (request)
- `src/compiler/**`
- HWND child surfaces and DPI layout (bucket 4)
- `src/runtime/gpu/**` and every exported `btrc_gpu_*` signature (REQUEST(CL-P2-28))

**Steps**

1. Run compute, offscreen rendering, async readback and a simulated device loss on D3D12 WARP on windows-latest through both frontends.
2. Link the arm64 msvc artifact per the route.
3. Keep the @gpu suites green on Linux and macOS, then open a draft PR from codex/cx-p2-33.

**Acceptance**

- [ ] The pixel checks and readback pass on the runner (run id). Real-GPU evidence is recorded in MAC-P2-05.

**Risks**

- WARP limitations.

<a id="cx-p2-34"></a>

##### CX-P2-34 · Windows image decoding (WIC via COM) and FreeType font loading/metrics at 100/150/200% scale

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-w2-gpu-image-font[image-font]`
- **Depends on:** [CL-P2-10](claude.md#cl-p2-10); [CX-P2-24](#cx-p2-24); [CL-P2-17](claude.md#cl-p2-17)
- **Why not now:** Needs COM (CL-P2-10) and cross-built FreeType in the flake.
- **Parallel-safe with:** CX-P2-32, CX-P2-33

**Owned paths**

- src/stdlib/Image/Windows/ (new)
- fragment (not held): src/stdlib/Image/btrc.toml (fragment)
- fragment (not held): src/stdlib/GUI/FreeType/ (Windows binding rows via a GUI/btrc.toml fragment)
- src/tests/python/test_windows_image_font.py (new)

**Must not touch**

- `src/stdlib/GUI/*.btrc` interfaces (bucket 4)
- `src/compiler/**`

**Steps**

1. Write a WIC SystemImageDecoder provider whose output matches the decode corpus of the other platforms.
2. Load fonts and take metrics with FreeType, checking the metrics at 100%, 150% and 200% scale.
3. Open a draft PR from codex/cx-p2-34.

**Acceptance**

- [ ] The image decode corpus matches on native Windows through both frontends, and the font metrics tests pass (run id).

**Risks**

- WIC pixel formats differ from ImageIO.

<a id="cx-p2-35"></a>

##### CX-P2-35 · Windows packaging: unpackaged developer executable plus test-signed MSIX (install, upgrade, uninstall, symbols)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-w2-packaging`
- **Depends on:** [CX-P2-19](#cx-p2-19); [CL-P2-20](claude.md#cl-p2-20); [CX-P2-18](#cx-p2-18); stage22:platforms-p0-adaptations → [CX-P1-02](#cx-p1-02); [CL-R-48](claude.md#cl-r-48)
- **Why not now:** Needs the BTRSmith Windows shell, library artifacts, the MSIX smoke workflow and the owner's Q4 answer (MSIX vs unpackaged).
- **Parallel-safe with:** CX-P2-32, CX-P2-33

> **Review change:** Its BTRSmith run ids come from `CL-R-48`'s emulator and Windows jobs (§10 F7).

**Owned paths**

- BTRSmith packaging/windows/ (MSIX manifest, scripts)
- BTRSmith `tests/windows/PackagingInstall.*` (new)

**Must not touch**

- btrc Makefile (request)
- signing secrets (never committed)

**Steps**

1. Build an unpackaged executable and an MSIX with a per-run test certificate.
2. Test install, upgrade and uninstall, running from an unrelated cwd, plus crash symbols (DWARF or PDB) and persistence.
3. Open a draft PR in BTRSmith from codex/cx-p2-35.

**Acceptance**

- [ ] The test-signed MSIX installs, upgrades and uninstalls on Windows 11 (run id). Real code signing is recorded unavailable (D8).

**Risks**

- Q4 may change to an unpackaged installer.

<a id="cx-p2-36"></a>

##### CX-P2-36 · iOS application/scene lifecycle and main-executor owner (lifecycle only)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-i1-app-lifecycle[implementation]`
- **Depends on:** [CL-P2-21](claude.md#cl-p2-21); [CL-P2-22](claude.md#cl-p2-22); stage25:platforms-p1-host-ios → [CX-P1-08](#cx-p1-08); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the UIKit adapters (CL-P2-21) and the UI2 shape check.
- **Parallel-safe with:** CX-P2-41, CX-P2-32

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/GUI/IOS/ (new, lifecycle files only)
- src/stdlib/App/IOS/ (new, if the design places it there)
- fragment (not held): GUI/btrc.toml and App/btrc.toml (fragments)
- src/tests/native/app_ios/ (new)
- src/tests/python/test_ios_app_lifecycle.py (new)

**Must not touch**

- src/stdlib/GUI/IApplication.btrc, IView.btrc, IWindow.btrc, App/App.btrc (UI hotspots; contract changes go to the UI contract owner)
- `src/stdlib/GUI/MacOS/**` (no aliasing)
- `src/compiler/**`

**Steps**

1. Handle startup, foreground and background, memory warnings, termination and relaunch, and deliver IApplication.post on the main executor. GUI.run and poll adapt to the OS-owned loop with no busy polling.
2. Run 100 background/foreground/memory-warning cycles on the simulator through both frontends, then open a draft PR from codex/cx-p2-36.

**Acceptance**

- [ ] The simulator cycles show post() delivered with no leaked owners (GitHub macOS run id); pinned-Xcode acceptance is in MAC-P2-04.

**Risks**

- Changes to the IApplication contract belong to bucket 4.

<a id="cx-p2-37"></a>

##### CX-P2-37 · iOS sandbox storage: security-scoped resource owner, bookmarks, revocation, SQLite durability

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-i1-sandbox-storage`
- **Depends on:** [CX-P2-14](#cx-p2-14); [CX-P2-36](#cx-p2-36); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the mobile storage foundation and the iOS lifecycle owner.
- **Parallel-safe with:** CX-P2-38, CX-P2-39

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/FileSystem/IOS/ (security-scoped owner, bookmarks)
- fragment (not held): FileSystem/btrc.toml (fragment)
- src/tests/python/test_ios_sandbox_storage.py (new)

**Must not touch**

- `src/stdlib/FileSystem/Windows/**`, `Android/**`
- `src/compiler/**`

**Steps**

1. Balance start/stopAccessingSecurityScopedResource through the owner, and keep bookmark data across relaunch.
2. Add cancellable, restartable scanning, revocation errors, and SQLite durability under a kill during write.
3. Open a draft PR from codex/cx-p2-37.

**Acceptance**

- [ ] On the simulator: a bookmark survives relaunch, revoked access errors, and SQLite survives a kill during write, through both frontends (run id).

**Risks**

- Picker presentation is UI7 (bucket 4); tests use pre-granted URLs.

<a id="cx-p2-38"></a>

##### CX-P2-38 · iOS audio provider: AVAudioSession plus RemoteIO (Audio/IOS)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `platforms-i2-audio[provider]`
- **Depends on:** [CX-P2-36](#cx-p2-36); [CL-P2-21](claude.md#cl-p2-21); stage25:platforms-p2-runtime-semantics → [CL-P1-19](claude.md#cl-p1-19); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the lifecycle owner and the AVAudioSession notification adapters.
- **Parallel-safe with:** CX-P2-37, CX-P2-39, CX-P2-32

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/Audio/IOS/ (new)
- fragment (not held): Audio/btrc.toml (fragment)
- src/tests/native/audio/ios/ (new fault fixtures)
- src/tests/python/test_ios_audio_runtime.py (new)

**Must not touch**

- `src/stdlib/Audio/MacOS/**` (AUHAL does not port)
- `src/compiler/**`

**Steps**

1. Cover the session category and activation, record permission, the negotiated rate and buffer, interruptions, route changes, media-services reset and USB I/O with clock discontinuities.
2. Run the simulator suite with simulated notifications through both frontends, then open a draft PR from codex/cx-p2-38.

**Acceptance**

- [ ] The simulator provider suite passes, with interruption and route-change recovery (run id); physical evidence is in MAC-P2-05.

**Risks**

- Simulator audio is not hardware evidence.

<a id="cx-p2-39"></a>

##### CX-P2-39 · iOS GPU: wgpu-native Metal path for device and simulator, CAMetalLayer surface lifecycle

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-i2-gpu[provider]`
- **Depends on:** [CX-P2-25](#cx-p2-25); [CL-P2-29](claude.md#cl-p2-29); [CX-P2-36](#cx-p2-36)
- **Why not now:** Needs the pinned archives and the lifecycle owner.
- **Parallel-safe with:** CX-P2-37, CX-P2-38

> **Review change:** No longer edits `src/runtime/gpu`: its platform branch is a `REQUEST(CL-P2-28)` (§10 C8).

> **Review change:** Probes the simulator's Metal device first (§10 F8).

**Owned paths**

- fragment (not held): src/stdlib/GPU/btrc.toml (fragment: ios rows)
- src/stdlib/GPU/IOS/ (new: surface lifecycle, no view hosting)
- src/tests/python/test_ios_gpu_runtime.py (new)

**Must not touch**

- view hosting (bucket 4)
- Makefile
- `src/compiler/**`
- `src/runtime/gpu/**` and every exported `btrc_gpu_*` signature (REQUEST(CL-P2-28))

**Steps**

1. First probe MTLCreateSystemDefaultDevice inside the runner's simulator. If it returns nil, the simulator GPU rows fall back to MAC-P2-04 and are recorded so.
2. Run compute and readback pixel checks on the simulator, including an unavailable drawable, resize and a suspension cycle, through both frontends.
3. Open a draft PR from codex/cx-p2-39.

**Acceptance**

- [ ] The simulator checks pass (run id); the device is recorded in MAC-P2-05.

**Risks**

- The simulator's Metal differs from the device's.

<a id="cx-p2-40"></a>

##### CX-P2-40 · iOS app packaging tooling: reproducible Xcode-controlled build, entitlements, dSYMs, xcarchive for device and simulator

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-i2-app-packaging[tooling]`
- **Depends on:** [CL-P2-20](claude.md#cl-p2-20); [CX-P1-08](#cx-p1-08); [CX-P2-21](#cx-p2-21)
- **Why not now:** Needs library artifacts, the lifecycle owner and the BTRSmith iOS shell.
- **Parallel-safe with:** CX-P2-38, CX-P2-39

> **Review change:** PLAN Stage 29 starts the iOS lane with packaging and the Android lane with NDK GPU and 16 KiB packaging (plain C), so this waits for the test host, not for the lifecycle owner (§10 P14).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- tools/apple/ (new: project generation from v6 library artifacts, Info.plist and entitlement templates, dSYM handling)
- BTRSmith packaging/ios/

**Must not touch**

- tools/native_plan.py (request)
- `src/compiler/**`

**Steps**

1. Package the library, adapters, dependencies, assets, entitlements, permission strings and deployment target, never swapping the device and simulator slices.
2. Produce an unsigned archive on a GitHub macOS runner as a supplementary check, then open a draft PR from codex/cx-p2-40.

**Acceptance**

- [ ] xcodebuild archive succeeds for both slices on the runner (run id); pinned-Xcode validation and symbolication are in MAC-P2-04.

**Risks**

- Hosted Xcode version drift.

<a id="cx-p2-41"></a>

##### CX-P2-41 · Android Activity shell and application lifecycle owner (Looper executor, recreation, process-death restore)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-a1-activity-lifecycle[implementation]`
- **Depends on:** [CL-P2-24](claude.md#cl-p2-24); [CL-P2-22](claude.md#cl-p2-22); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs JNI entry and callbacks (CL-P2-24) and the UI2 shape check.
- **Parallel-safe with:** CX-P2-36, CX-P2-43

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- tools/android/shell/ (new: a Java Activity template with no policy, using System.loadLibrary and RegisterNatives)
- src/stdlib/App/Android/ and src/stdlib/GUI/Android/ (new, lifecycle files only)
- fragment (not held): App and GUI btrc.toml fragments
- src/tests/python/test_android_activity_lifecycle.py (new)

**Must not touch**

- src/stdlib/GUI/IApplication.btrc and the other UI hotspots
- `src/stdlib/Java/**` (Claude)
- `src/compiler/**`

**Steps**

1. Evaluate GameActivity against a standard Activity and record the decision.
2. Handle configuration changes, recreation and process-death recovery, and supply the app roots to FileSystem/Android, replacing the host handoff.
3. Run 100 recreate cycles plus a process-death restore on the emulator through both frontends, then open a draft PR from codex/cx-p2-41.

**Acceptance**

- [ ] The emulator APK survives 100 recreations and a process-death restore with no stale Activity references (run id).

**Risks**

- The ART lifecycle differs between API 29 and 36.

<a id="cx-p2-42"></a>

##### CX-P2-42 · Android storage and permissions: app-private files, SAF descriptor owners, persisted grants, permission states, intents

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-a1-storage-permissions`
- **Depends on:** [CX-P2-41](#cx-p2-41); [CX-P2-14](#cx-p2-14); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the Activity owner and the mobile storage foundation.
- **Parallel-safe with:** CX-P2-43, CX-P2-44

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/FileSystem/Android/ (SAF descriptor owners)
- src/stdlib/App/Android/ (permissions owner)
- the Browser owner's Android provider (intent)
- src/tests/python/test_android_storage_permissions.py (new)

**Must not touch**

- src/stdlib/HTTP/HTTPClient.btrc seam (request if needed)
- `src/compiler/**`

**Steps**

1. Persist grants with takePersistableUriPermission and handle revocation, non-seekable streams, RECORD_AUDIO and network permission states (pending is not denied), Custom Tab or ACTION_VIEW intents from a visible activity, and the background limits.
2. Open a draft PR from codex/cx-p2-42.

**Acceptance**

- [ ] On the emulator: grant persistence across process death, revoked grants and permission denial pass through both frontends (run id).

**Risks**

- Driving SAF pickers in tests (UIAutomator).

<a id="cx-p2-43"></a>

##### CX-P2-43 · AAudio realtime provider (Audio/Android) with fault fixtures

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-a2-aaudio[provider]`
- **Depends on:** stage25:platforms-p1-host-android → [CX-P1-09](#cx-p1-09); stage24:platforms-p1-native-import-targets → [CL-P1-10](claude.md#cl-p1-10); stage25:platforms-p2-runtime-semantics → [CL-P1-19](claude.md#cl-p1-19); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs NDK header reads for android rows and Stage 25's Android host and runtime semantics. It can start before CX-P2-41, using the NativeActivity host; focus and permission hook in after CX-P2-41.
- **Parallel-safe with:** CX-P2-41, CX-P2-44, CX-P2-38

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

**Owned paths**

- src/stdlib/Audio/Android/ (new)
- fragment (not held): Audio/btrc.toml (fragment)
- src/tests/native/audio/android/ (new)
- src/tests/python/test_aaudio_runtime.py (new)

**Must not touch**

- `src/compiler/**`
- `src/stdlib/Audio/Linux/**`

**Steps**

1. Negotiate the real rate, burst and channels, record xruns, disconnects and drift, and keep callbacks allocation-free under the realtime verifier.
2. Run the emulator suite through both frontends, then open a draft PR from codex/cx-p2-43.

**Acceptance**

- [ ] The emulator suite passes with callbacks, disconnect recovery and drain (run id); physical evidence is in MAC-P2-05.

**Risks**

- Emulator audio timing is unrealistic.

<a id="cx-p2-44"></a>

##### CX-P2-44 · Android GPU: wgpu-native Vulkan for arm64/x86_64, ANativeWindow surface lifecycle

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `platforms-a2-gpu[provider]`
- **Depends on:** [CX-P2-25](#cx-p2-25); [CL-P2-29](claude.md#cl-p2-29); [CX-P1-09](#cx-p1-09); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Needs the pinned archives and an Activity surface.
- **Parallel-safe with:** CX-P2-42, CX-P2-43

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** PLAN Stage 29 starts the iOS lane with packaging and the Android lane with NDK GPU and 16 KiB packaging (plain C), so this waits for the test host, not for the lifecycle owner (§10 P14).

> **Review change:** No longer edits `src/runtime/gpu`: its platform branch is a `REQUEST(CL-P2-28)` (§10 C8).

**Owned paths**

- fragment (not held): src/stdlib/GPU/btrc.toml (fragment: android rows)
- src/stdlib/GPU/Android/ (new)
- src/tests/python/test_android_gpu_runtime.py (new)

**Must not touch**

- Makefile
- `src/compiler/**`
- `src/runtime/gpu/**` and every exported `btrc_gpu_*` signature (REQUEST(CL-P2-28))

**Steps**

1. Run compute and readback pixel checks on the emulator's Vulkan, plus surface replacement, pause/resume, orientation and a simulated device loss, with explicit capability failure.
2. Open a draft PR from codex/cx-p2-44.

**Acceptance**

- [ ] The emulator checks pass (run id); the device is recorded in MAC-P2-05.

**Risks**

- Emulator Vulkan support on hosted runners.

<a id="cx-p2-45"></a>

##### CX-P2-45 · Android packaging with full 16 KiB compatibility: APK/AAB, per-library alignment checker, bundletool validation

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `platforms-a2-packaging-16k`
- **Depends on:** [CL-P2-20](claude.md#cl-p2-20); [CX-P1-09](#cx-p1-09); [CX-P2-20](#cx-p2-20)
- **Why not now:** Needs library artifacts, the Activity shell and the BTRSmith Android shell.
- **Parallel-safe with:** CX-P2-43, CX-P2-44

> **Review change:** PLAN Stage 29 starts the iOS lane with packaging and the Android lane with NDK GPU and 16 KiB packaging (plain C), so this waits for the test host, not for the lifecycle owner (§10 P14).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- tools/android/ (Gradle template, check_alignment.py: ELF PT_LOAD of at least 16384 plus zip alignment)
- BTRSmith packaging/android/
- src/tests/python/test_android_alignment.py (new)

**Must not touch**

- tools/native_plan.py (max-page-size flags as a request)
- keystores (never committed)

**Steps**

1. Package the .so files, adapters, Java shell, permissions, resources, C++ runtime and symbols.
2. Make the checker reject a deliberately 4 KiB-aligned fixture.
3. Build a debug APK and a release AAB signed with a per-run throwaway keystore, and validate with bundletool.
4. Run on the 4 KiB and 16 KiB emulator images, then open a draft PR from codex/cx-p2-45.

**Acceptance**

- [ ] A per-library alignment report shows every library at 16 KiB, the APK runs on both page sizes, and bundletool passes (run ids).

**Risks**

- AGP and Gradle pins and network access.

<a id="cx-p2-46"></a>

##### CX-P2-46 · BTRSmith storage fixtures per platform: revoked/unavailable roots, rescan after restart, kill during write

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-storage-resources[platform-fixtures]`
- **Depends on:** [CL-P2-25](claude.md#cl-p2-25)
- **Why not now:** Needs the token abstraction.
- **Parallel-safe with:** CX-P2-47, CX-P2-48

**Owned paths**

- BTRSmith tests/windows/, tests/ios/, tests/android/ storage fixtures (new)

**Must not touch**

- BTRSmith `src/**` (CL-P2-25)

**Steps**

1. Write the fixtures per platform and run them through both frontends: Windows on a BTRSmith dispatch, Android on the Linux CI emulator, iOS in MAC-P2-04.

**Acceptance**

- [ ] The fixtures pass per platform (run ids).

**Risks**

- BTRSmith CI minutes.

<a id="cx-p2-47"></a>

##### CX-P2-47 · BTRSmith AudioSetupFailure journeys ported to WASAPI, iOS and AAudio fault fixtures

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-audio-adaptation[fault-journey-ports]`
- **Depends on:** [CL-P2-26](claude.md#cl-p2-26); [CL-R-48](claude.md#cl-r-48)
- **Why not now:** Needs the audio policy.
- **Parallel-safe with:** CX-P2-46, CX-P2-48

> **Review change:** Its BTRSmith run ids come from `CL-R-48`'s emulator and Windows jobs (§10 F7).

**Owned paths**

- BTRSmith `tests/windows/AudioSetupFailure*.btrc`, tests/ios/..., tests/android/... (new)

**Must not touch**

- BTRSmith `src/**`

**Steps**

1. Port the tests/macos and tests/linux variants to each provider's fault fixtures, through both frontends.

**Acceptance**

- [ ] The journeys pass on each fault fixture (run ids); physical audio is bucket 5.

**Risks**

- Fixture fidelity.

<a id="cx-p2-48"></a>

##### CX-P2-48 · BTRSmith GPU portability on Vulkan and D3D12, with capability-chosen present mode

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-gpu-portability[vulkan-d3d12-present-mode]`
- **Depends on:** [CX-P2-33](#cx-p2-33); [CX-P2-44](#cx-p2-44); [CL-P2-16](claude.md#cl-p2-16); [CL-R-48](claude.md#cl-r-48)
- **Why not now:** Needs the Windows and Android GPU providers.
- **Parallel-safe with:** CX-P2-46, CX-P2-47

> **Review change:** Its BTRSmith run ids come from `CL-R-48`'s emulator and Windows jobs (§10 F7).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/stdlib/GPU/GPUSurfaceRenderer.btrc (present mode by capability, replacing the hard-coded Immediate)
- BTRSmith `src/platform/gpu/*`
- BTRSmith `tests/<backend>/PlayerGPU*.btrc`, `SharedGPUComposition*.btrc`

**Must not touch**

- `src/compiler/**`

**Steps**

1. Choose Fifo or Mailbox by capability with pacing, validate the WGSL per backend and bound mobile texture memory (artwork at most 64 MiB).
2. Run the pixel readback on Vulkan (lavapipe on Linux, the Android emulator) and on D3D12 WARP (Windows), through both frontends.

**Acceptance**

- [ ] The readback suites pass per backend (run ids), with no per-screen OS conditionals; Metal is in MAC-P2-04.

**Risks**

- Software rasterizers hide driver bugs.

<a id="cx-p2-49"></a>

##### CX-P2-49 · iOS simulator CI workflow (corpus x2 frontends, provider suites, device-slice archive)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-ci-ios[workflow]`
- **Depends on:** stage25:platforms-p2-ci-lanes → [CX-P1-07](#cx-p1-07), [CX-P1-08](#cx-p1-08), [CX-P1-09](#cx-p1-09); [CX-P2-36](#cx-p2-36); [CX-P2-40](#cx-p2-40)
- **Why not now:** Needs Stage 25's iOS lane, the lifecycle owner and the packaging tooling.
- **Parallel-safe with:** CX-P2-50

> **Writer note:** The new expected-skip manifest travels in the `fragment:` commit (§9 item 4).

> **Review change:** `tools/qualification/skips.py` already lists `ios` and `android` in RUNNERS, so no RUNNERS entry is needed; only the `windows-arm64` and `windows-corpus` manifests (`CX-P2-18`/`31`) need one (§10 C2).

**Owned paths**

- .github/workflows/ios.yml (new)
- fragment (not held): src/tests/fixtures/expected-skips/ios.json (new; delivered in the `fragment:` commit, `ios` is already in RUNNERS)
- src/tests/python/test_ci_workflow_contracts.py (rows for the new workflow)

**Must not touch**

- macos.yml, ci.yml, windows.yml, Makefile, conftest.py (requests)

**Steps**

1. Run the applicable corpus on iPhone and iPad simulators at O0 and O2 through both frontends, plus the I1/I2 provider suites.
2. Build an unsigned device-slice xcarchive, ingest the xcresult, and record the physical jobs as unavailable.
3. Open a draft PR from codex/cx-p2-49.

**Acceptance**

- [ ] The simulator corpus report has a skip ledger, the xcresult is ingested, the archive artifact exists, and the draft PR runs are green (run ids).

**Risks**

- The hosted Xcode is not 27A266a.
- The workflow-scope token.

<a id="cx-p2-50"></a>

##### CX-P2-50 · Android emulator CI workflow (API 29/36 x 4/16 KiB, corpus, APK/AAB, alignment gate, lifecycle tests)

- **Owner:** Codex · **Group:** P2 · **Stage:** 29 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-ci-android`
- **Depends on:** stage25:tooling-android-ci-emulator → [CX-P1-05](#cx-p1-05); [CX-P2-45](#cx-p2-45); [CX-P2-41](#cx-p2-41)
- **Why not now:** Needs Stage 25's emulator CI, the packaging and alignment checker, and the Activity owner.
- **Parallel-safe with:** CX-P2-49

> **Writer note:** The new expected-skip manifest travels in the `fragment:` commit (§9 item 4).

> **Review change:** `tools/qualification/skips.py` already lists `ios` and `android` in RUNNERS, so no RUNNERS entry is needed; only the `windows-arm64` and `windows-corpus` manifests (`CX-P2-18`/`31`) need one (§10 C2).

**Owned paths**

- .github/workflows/android.yml (new, or an extension of Stage 25's mobile workflow by agreement)
- fragment (not held): src/tests/fixtures/expected-skips/android.json (new; delivered in the `fragment:` commit, `android` is already in RUNNERS)
- src/tests/python/test_ci_workflow_contracts.py (rows)

**Must not touch**

- ci.yml, Makefile, conftest.py (requests)

**Steps**

1. Run KVM emulators at API 29 and 36 with 4 KiB and 16 KiB x86_64 images, the corpus at O0 and O2 through both frontends, a debug APK and release AAB, the alignment gate, a UIAutomator smoke, and the recreation and process-death tests.
2. Open a draft PR from codex/cx-p2-50.

**Acceptance**

- [ ] Corpus reports exist for {29, 36} × {4, 16 KiB} through both frontends; the checker rejects the 4 KiB fixture; the process-death test is green (run ids).

**Risks**

- Hosted 16 KiB x86_64 image availability.

#### Stage 30: UI0 catalog, journeys and evidence hosts

<a id="cx-uia-01"></a>

##### CX-UIA-01 · ui-0-focused-gate: the make test-native-gui target and the UI agent runbook

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 3 agent-hours
- **PLAN items:** `ui-0-focused-gate` (the make test-native-gui target; the drift gate is CX-UIA-02's PR #21)
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-02, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Writer note:** Steps 1–3 landed in batch 13 (CL-UIA-02's integrator fragment): `make test-native-gui` is on `main`, writes `build/skip-report-native-gui.json` and runs its own skip gate. Today the coverage rule fails, because `webgpu_child/*.btrc` are driven only by `test_native_webgpu_imports.py`, which `NATIVE_GUI_TESTS` does not select; Claude adds that module in its next batch (`CL-UIA-05` step 6). That wait is a risk below, not a dependency, because `CL-UIA-05` is the rolling packet that lands this one. The remaining steps keep their numbers, 4–8 (2026-10-03, [codex-ui-lanes.md](codex-ui-lanes.md) Task 2).

> **Review change:** PR #21 already claims the drift-gate half of `ui-0-focused-gate`, so this packet keeps only the GUI target, its coverage test, the runbook and `codex-setup.sh` (§10 F3).

> **Review change:** Commit naming corrected: hand-written integrator data goes in the `fragment:` commit, which Claude re-applies; regenerated outputs go in `derived:`, which Claude drops (§3.5, §10 C3).

> **Review change:** Setup and commands corrected: no nested nix, the skip-gate runner name for cloud containers (which have neither `/.dockerenv` nor `/run/.containerenv`), the gcc check and the gh credential step (§10 F5, F13, F16).

**Owned paths**

- docs/qualification/ui-agent-runbook.md (new)
- src/tests/python/test_native_gui_target.py (new)
- tools/ui/codex-setup.sh (new)
- fragment (not held): Makefile `NATIVE_GUI_TESTS` line (only if `CL-UIA-05` step 6 is not on `main` when the rest is done)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `tools/compiler_codegen/**`
- `src/runtime/**`
- tools/NativeHeaderReader.cpp
- docs/design/plan-reference.md
- PLAN.md
- AGENTS.md
- `.github/workflows/**`
- flake.lock
- src/stdlib/btrc.lock, btrc.symbols and the LSP catalog except in the final `derived:` commit; expected-skip JSON only in the `fragment:` commit
- src/tests/conftest.py

**Steps**

Steps 1–3 landed in batch 13 (CL-UIA-02's integrator fragment).

4. Add test_native_gui_target.py. It fails when any .btrc under `src/tests/native/gui/**` or src/tests/native/tray/ is not driven by a module the target selects. It parses `NATIVE_GUI_TESTS`, including the glob, and resolves literal names (a file or stem), directory references (a module naming `webgpu_child` drives every `.btrc` under it) and f-string templates matched as globs (`f"MacOS{control}Conformance.btrc"`); add an in-memory negative case. The test never names the runbook path in a literal (no test or tool may name a Markdown file outside ci.yml's `TEST_READ_MARKDOWN`).
5. Write the runbook. It covers the cloud clone and the codex/\<id> branch, and nix develop with a gcroot profile. It explains how to build BTRC_NATIVE_HEADER_READER from the branch's own tools/NativeHeaderReader.cpp; without it the Linux provider tests skip.
6. The runbook also covers sharing one btrcc through BTRC_TEST_BTRCC, reading skips, and the fragment rule. macOS evidence comes from the draft PR's macos.yml, or from a focus=native-gui dispatch (available since CL-UIA-02 landed in batch 13).
7. It also says that a change to a compiler-import stdlib module (BackgroundJobs, FileSystem, Process and the others) needs the lane's own btrcc and a bootstrap run, and that only Claude runs the landing gate.
8. Add tools/ui/codex-setup.sh, an idempotent container bootstrap: verify nix, warm and GC-root the dev shell, check that the dev shell's gcc is 15.2, build the header reader and one btrcc through make btrcc, export BTRC_TEST_RUNNER=linux-devcontainer in ~/.bashrc, and persist gh credentials only when GH_TOKEN is set (§3.11). It fails loudly if Xvfb or nix is missing. The `.#platforms` GC root is opt-in only (`--platforms`), never the default (its closure is 17.75 GB).

**Acceptance**

- [ ] `nix develop --command python3 -m pytest src/tests/python/test_native_gui_target.py -q -rs` passes against `main`'s `NATIVE_GUI_TESTS` (with `CL-UIA-05` step 6, or this packet's fragment).
- [ ] `bash -n tools/ui/codex-setup.sh` passes. Running it twice succeeds, and the second run changes nothing (log in the PR body).
- [ ] In the cloud container, `nix develop --command tools/virtual-display.sh make NIX= test-native-gui` has 0 failures and reports pass and skip counts for each frontend (python and selfhost), with the skip list printed.
- [ ] `make test-native-gui` passes its own skip gate on `build/skip-report-native-gui.json`; new rules go only in the fragment commit.
- [ ] Lane CI green (run ids; windows.yml "green (scope only)"), and `junit-macos-native-gui` shows the AppKit cases executed.
- [ ] make lint, make format-check and git diff --check pass. The PR-body report follows the protocol.

**Risks**

- No Makefile change of its own: if Claude's `NATIVE_GUI_TESTS` line is not on `main` when the rest is done, add it as a `fragment: Makefile` commit, which makes the PR main tier and takes the single CI slot (§3.2).
- A Codex container without nix or Xvfb would silently skip the Linux GUI cases.
- A cold btrcc build takes 10-20 minutes on 4 CPUs.

<a id="cx-uia-02"></a>

##### CX-UIA-02 · ui-0-catalog-schema (adopted from PR #21): frozen catalog slots with the amendment model and drift gate, plus the shard loader

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** yes (follow-up; first commit integrated in batch 11, CI green) · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-0-catalog-schema`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Writer note:** PR #21's commit `b7aa53f` (the seed, the amendments and the drift gate) was integrated in batch 11 with green CI (ci.yml 37090470053, macos.yml 37090470052, windows.yml 37090470074), and PR #21 is closed. The follow-up has not started: `tools/qualification/ui_catalog.py` and `docs/design/native-ui-catalog/` do not exist on any ref. Steps and acceptance below are the follow-up's, from Task 1 of [codex-ui-lanes.md](codex-ui-lanes.md), and carry its layout, README table, compact-form fields and test cases in full (2026-10-03).

> **Review change:** Adopted from Codex's draft PR #21 (`codex/ui0-catalog`, head `b7aa53f`), the earliest claim on `ui-0-catalog-schema` (§3.9). Its amendment model keeps PLAN's frozen 162/1,620/470 release and pins the 17 added declarations, so this packet no longer re-freezes the denominator, and the `fragment:` denominator and ledger-test entries of §9 item 4 are dropped. Layout: PR #21's seed file plus a shard directory beside it (§7 Q35, Q36, recorded by `CL-UIA-01`). Supersedes the writer note of §9 items 4 and 9 for this packet (§10 P10, F3).

**Owned paths**

- branch codex/cx-uia-02-shards (the follow-up's draft PR, `[CX-UIA-02] ui-0-catalog-schema follow-up: shard loader, family cells, IFontFace scope`)
- tools/qualification/ui_catalog.py (new: the shard layout, loader, merge, partitions and CLI)
- src/tests/python/test_ui0_catalog.py
- docs/design/native-ui-catalog/README.md (new: the shard layout and the owner-to-packet table)
- docs/design/native-ui-catalog/families.toml (new: the 300 family cells)
- docs/design/ui0-source-amendments.toml
- docs/design/ui0-catalog.md
- docs/design/native-ui-api-inventory.md (one btrc-D068 bullet under 'Changes since the frozen inventory' only; no table rows)

**Must not touch**

- `src/**` other than the owned test_ui0_catalog.py (the reference `Lexer` and `Parser` may only be imported read-only, as that test already does)
- every existing `tools/qualification/*.py` (send Claude a 'ledger request' if a field is missing)
- docs/design/native-ui-catalog.toml (the seed stays byte-identical)
- src/tests/python/test_qualification_ledger.py and test_ci_workflow_contracts.py
- every other path under docs/design/native-ui-catalog/ (each belongs to the packet the README names)
- the tables in docs/design/native-ui-api-inventory.md, all of native-ui-parity.md, and docs/design/platform-inventory.toml with its denominator entry
- docs/design/plan-reference.md
- PLAN.md, AGENTS.md, CLAUDE.md, WORKSTREAMS.md and `docs/workstreams/**`
- `.github/**`, Makefile, ci/tiers.toml, `flake.*` and `nix/*`
- tools/qualification/denominators.toml (unchanged: no re-freeze in this packet)

**Steps**

1. Branch `codex/cx-uia-02-shards` from `origin/main` (PR #21's `b7aa53f` is already there) and open the draft PR with Owned paths first and `Packet: CX-UIA-02 … Branch: codex/cx-uia-02-shards Base: <origin/main sha>`.
2. Shard layout, declared as data in ui_catalog.py and mirrored in README.md; any other file or directory is an error. `families.toml` holds family cells only (N01–N60 × 5 platforms, no frontend); `operations/<Owner>.toml` holds ui-operation ids that start with `<Owner>.` for an admissible owner; `cases/E<aa>-E<bb>.toml` holds ui-case ids inside the filename's range, and ranges never overlap; `surface/<Stem>.toml` (`btrc.ui-catalog.surface/1`; stems `GUIModules` for the GUI modules outside `I*.btrc`, `App`, `UI` and `Tray`) has one table per exported symbol with `module`, `symbol`, `kind`, a `disposition` of `family`, `legacy`, `provider-internal` or `out-of-scope`, `links`, a `reason` (required unless the disposition is `family`) and, on a `family` row, an optional `operations` list of proposed ui-operation ids, validated against the GUI, App, UI and Tray btrc.toml exports; `evidence/<kebab-name>.toml` or `.jsonl` (for example `ui1-macos`) holds ledger/1 evidence with provenance, `test` records and `note` only, and stores no packet key (ledger/1 rejects extra top-level keys; the README names the packet); `amendments/<packet-id-lowercase>.toml` uses the amendments grammar (step 8), one file per packet; `hosts.toml` (CX-UIA-06's test validates it) and `README.md` are skipped explicitly. Admissible ids are the seed, the amendments, every ui-operation and ui-case release denominators.toml declares (read through `DenominatorManifest`), and the `operations` ids of `family` surface rows. The README's owner-to-packet table lists every planned path: `families.toml` (CX-UIA-02); `operations/{IApplication,IApplicationWork,IWindow,IWindowKeyHandler,IView,IViewPointerHandler,IViewScrollHandler,IContainer,IGPUView,IDirectoryPicker,GUI}.toml` (CX-UIA-03); `operations/{IButton,IButtonAction,ITextField,ISelect,ISlider,ILabel,IStack,IGrid,IScrollView,IPanel,IImageView,IImageHandle,IProgressIndicator,ILevelIndicator,IFontFace}.toml` (CX-UIA-04); `cases/E01-E24.toml` and `cases/E25-E47.toml` (CX-UIA-30); `surface/{GUIModules,App,UI,Tray}.toml` (CX-UIA-05); `hosts.toml` (CX-UIA-06); `evidence/ui1-macos.toml` (CX-UIA-10); `evidence/ui1-linux.toml` (CX-UIA-11); and the UI2 and UI3 `operations/` rows (CX-UIA-21, CX-UIA-25).
3. Compact form: beside verbose `[[records]]`, operation and case shards accept one `[[operations]]` or `[[cases]]` table per id. Shared fields go on the table (`implementation`, `parity`, `owner`, `links`, `regression`, `decision`, `note`). The cells `macos`, `linux`, `windows`, `ios` and `android` are each a mapping for both frontends or `{ reference = {…}, selfhost = {…} }`, and carry overrides, `evidence = { status, observed, reason, artifact, covered_by }` and `run = "<name>"`. `[runs.<name>]` tables carry `source`, `recorded_at`, `runner`, `btrc_revision`, `device_class` and the other provenance fields. Every cell expands to ledger/1 through `LedgerRecord.from_mapping`, so every schema.py invariant applies.
4. Merge and partitions. Ledger order: the seed, `families.toml`, then `operations/` and `cases/` sorted, then `evidence/` sorted. Classification is unique per slot; evidence may come from several files and the last in ledger order wins (schema.py:143-144, as report.py reads it), and `check` reports as a problem an evidence record that replaces one whose `provenance.recorded_at` is newer. Reject a slot outside the admissible ids, classification in two files, a duplicate in one file, a `variant` on a UI slot, a foreign owner or an out-of-range case id, and any classification other than `note` under `evidence/`. Partitions: frozen (1,620 operation, 470 case and 300 family-cell slots); pending (the amendment ids and surface proposals, derived through the reference Lexer and Parser, never by regex: today 17 ids / 170 slots, or 15 / 150 if IFontFace is out of scope; they may be classified in their owner's shard but never count in the frozen report); retired (`GUI.rasterText`, 10 slots, decision btrc-D056), which no shard may classify and which is reported with its decision.
5. Define "classified" once, in the code and the README: an operation or case slot has `classification.implementation` and `evidence.status`; a family cell has `implementation`. Provide `unclassified(owner=…, kind=…)`, which excludes retired slots.
6. CLI, exit status 1 on any problem: `python3 -m tools.qualification.ui_catalog check [--strict] [--owner O]... [--kind ui-operation|ui-case|family-cell|surface]... [--junit RUN=PATH]...` runs the layout and admission rules and requires `QualificationReport(frozen records, DenominatorManifest([the three UI kinds])).problems() == []`; `--strict` also fails on an unclassified non-retired slot in scope; `--junit` checks that every `passed` cell of that run lists regression node ids that passed in the XML (read with `JUnitAdapter`). `report [--format markdown|json] [--owner O]... [--kind K]...` gives counts per kind × platform × frontend, the three partitions and the unclassified slots per owner.
7. `families.toml`: seed it from the 2026-09-21 P/C/M matrix in native-ui-parity.md (P → `partial`, C → `custom`, M → `missing` with `parity = "missing"`), with `links = ["Nxx", "UIx"]` and no evidence. The matrix cells carry no footnotes, so take the notes from the paragraph under the legend (native-ui-parity.md:306-309): N10, N37, N40, N42 and N43 on macOS, "P credits only the native editor and control foundation, not a verified shared editing or accessibility contract"; N41, "missing, because native control defaults provide no custom-content bridge". The test pins the seeded 300-cell grid as data with its sha256 (P 48, C 15, M 237; macOS 33/0/27, Linux 15/15/30, Windows, iOS and Android 0/0/60 each) and does not re-read native-ui-parity.md; a cell that differs from the seed carries a `decision`.
8. Amendments: record IFontFace's scope in ui0-source-amendments.toml (recommended in scope, linked to N44 and N49, because GUI/btrc.toml exports it and `Font(IFontFace)` is public; otherwise out of scope with the reason). Widen the grammar (`[[changes]]` with `id`, `decision`, `frozen`, `current`; an optional `parent` on additions and `replacement` on removals), also load `amendments/*.toml`, derive the counts test from `[current]` plus the amendments instead of the literals 20/25/152/26/17, and add the outside-interface guard (`[[outside_interfaces]]`, today `ActionMailbox.IQueuedAction`).
9. Documentation and tests: add the btrc-D068 bullet (`FontFace.btrc` renamed to `IFontFace.btrc` in 16185609, which brings `IFontFace.metrics`/`.glyph` into the `I*.btrc` scope); update ui0-catalog.md (layout, CLI, partitions, "classified", the IFontFace decision). In test_ui0_catalog.py, run `verify_catalog` over the merged view. Add one negative case per admission rule: an unknown file, a foreign owner, a case id out of range, classification duplicated across two files, an unknown id, a classification under `evidence/`, a `variant`, a tampered seed slot set, a pending slot leaking into the frozen count, a retired id classified, and a stale evidence overwrite reported. Add the positive cases: an `operations/` shard and an `evidence/` shard touching one slot, where the last evidence wins; a surface `family` row that admits a new owner shard; `hosts.toml`, `evidence/ui1-macos.toml` and `surface/GUIModules.toml` accepted; retired slots excluded from `--strict`; a compact-form round trip; and a merge of two packets' fixture shards in `tmp_path`. Cover the families seed and the outside-interface guard, and keep the dummy-method failure.
10. Binding rules: no denominator change and no re-freeze (`ui0-source-inventory-2026-09-21` stays at 162/1,620, 47/470 and 60/300); never add a row shaped ``| `Owner.member` |`` to native-ui-api-inventory.md or change an N/E row id in native-ui-parity.md; no string literal in `src/tests/**` or `tools/**` names a Markdown file outside `TEST_READ_MARKDOWN`, and no code reads ui0-catalog.md. Put `REQUEST(CL-UIA-24)` (several releases per kind, the retired disposition, frozen sources read from the seed ledger and families.toml, the `_frozen_copy` cases) and `REQUEST(CL-UIA-05)` (wire `ui_catalog` into `make qualification-report`) in the PR body.

**Acceptance**

- [ ] `nix develop --command python3 -m pytest src/tests/python/test_ui0_catalog.py -q -rs` → 0 failed, 0 skipped.
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_qualification_ledger.py src/tests/python/test_platform_inventory.py -q -rs` → 0 failed, and `nix develop --command python3 -m pytest src/tests/python/test_ci_workflow_contracts.py -k markdown -q` passes.
- [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check` exits 0 and prints 1,620/1,620 ui-operation, 470/470 ui-case and 300/300 family-cell slots; 0 undeclared and 0 duplicate; pending 17 ids / 170 slots (15 / 150 if IFontFace is recorded out of scope, with its 2 ids and the reason); retired 1 id / 10 slots.
- [ ] `… ui_catalog report --format json` gives family-cell partial 48, custom 15, missing 237 (macOS 33/0/27; Linux 15/15/30; Windows, iOS and Android 0/0/60 each), and ui-operation and ui-case at 0 classified.
- [ ] `nix develop --command python3 -m tools.qualification denominators` exits 0.
- [ ] `git diff --exit-code origin/main -- docs/design/native-ui-catalog.toml tools/qualification/denominators.toml` exits 0, and the diff lists only owned paths.
- [ ] `make lint format-check generated-check` and `git diff --check` pass.
- [ ] Lane CI is green on the final head: ci.yml and macos.yml with run ids, and windows.yml "green (scope only)".

**Risks**

- `ui_catalog.py` becomes a Claude hotspot the moment it lands (§3.3.1, existing `tools/qualification/*.py` modules), so it builds every shard kind now and later packets only add data files.
- The drift test depends on the reference parser's public API; it must not reach into compiler internals.
- The seed is one 6,485-line file: later packets write sibling shard documents, never the seed, which changes only through reviewed releases.

<a id="cx-uia-03"></a>

##### CX-UIA-03 · ui-0-operation-map (A): application, window, view, container, handlers, GPU view, picker and GUI facade

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-0-operation-map`
- **Depends on:** [CX-UIA-02](#cx-uia-02)
- **Why not now:** Needs CX-UIA-02's shard format and seeded rows.
- **Parallel-safe with:** CX-UIA-04, CX-UIA-05, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-03

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

> **Review change:** GPU-adapter claim corrected (§10 F8).

**Owned paths**

- docs/design/native-ui-catalog/operations/{IApplication,IApplicationWork,IWindow,IWindowKeyHandler,IView,IViewPointerHandler,IViewScrollHandler,IContainer,IGPUView,IDirectoryPicker,GUI}.toml

**Must not touch**

- `src/**`
- `tools/qualification/*.py`
- docs/design/native-ui-catalog/operations/ shards owned by CX-UIA-04
- docs/design/plan-reference.md
- PLAN.md

**Steps**

1. For every operation × {macos, linux} × {reference, selfhost}, find the assertion that exercises it in `src/tests/native/gui/*.btrc`, `gui/linux/*.btrc` or the `test_native_*` drivers, and record the pytest node id and the assertion text.
2. Check inherited IView and IContainer operations at each concrete receiver (button, field, select, slider, label, image, panel, indicators, stack, grid, scroll and GPU view), not once per interface.
3. Evidence is 'passed' only where a current run passed: from the shared UI0 evidence run, Claude's `focus=native-gui` dispatch of ci.yml and macos.yml on the `main` SHA that landed the CX-UIA-02 follow-up, recorded as `[runs.ui0-*-<id>]` with `btrc_revision` set to that SHA (the JUnit read with tools/qualification/adapters.py). Otherwise it is implemented-unverified or missing.
4. Windows, iOS and Android are recorded as implementation missing, with evidence unavailable and covered_by [] where no runner exists. A missing provider is never implemented-unverified.
5. `GUI.rasterText` is retired (btrc-D056) and is not classified. Pending ids (the 15 `IApplication.create*` factories) are classified in their owner shard.
6. Branch from `main` after Claude integrates the CX-UIA-02 follow-up (no stacking). Drafting earlier on a local branch off `codex/cx-uia-02-shards` is fine; rebase onto `main` before opening the PR.

**Acceptance**

- [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check --strict --owner <each owner above> --junit ui0-macos-<id>=… --junit ui0-linux-<id>=…` exits 0 (0 unclassified slots for these owners; retired slots excluded), and test_ui0_catalog.py passes.
- [ ] Every passed cell names a pytest node id, an assertion and its run id.
- [ ] The PR-body table gives passed / implemented-unverified / missing counts per owner and platform.

**Risks**

- macOS junit artifacts expire after the retention window, so record run ids promptly.
- Hosted macos-15 exposes a paravirtual Metal adapter: GPU correctness rows run there; real-GPU timing, pacing and idle-CPU rows stay owner-tier.

<a id="cx-uia-04"></a>

##### CX-UIA-04 · ui-0-operation-map (B): controls, layout containers, indicators, images and fonts

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-0-operation-map#controls-layout`
- **Depends on:** [CX-UIA-02](#cx-uia-02)
- **Why not now:** Needs CX-UIA-02's shard format and seeded rows.
- **Parallel-safe with:** CX-UIA-03, CX-UIA-05, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-03

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

**Owned paths**

- docs/design/native-ui-catalog/operations/{IButton,IButtonAction,ITextField,ISelect,ISlider,ILabel,IStack,IGrid,IScrollView,IPanel,IImageView,IImageHandle,IProgressIndicator,ILevelIndicator,IFontFace}.toml

**Must not touch**

- `src/**`
- `tools/qualification/*.py`
- docs/design/native-ui-catalog/operations/ shards owned by CX-UIA-03
- docs/design/plan-reference.md
- PLAN.md

**Steps**

1. Map the same way as CX-UIA-03, with evidence from the shared UI0 evidence run (Claude's `focus=native-gui` dispatch of ci.yml and macos.yml on the `main` SHA that landed the CX-UIA-02 follow-up, recorded as `[runs.ui0-*-<id>]`), using the NativeButtons, NativeSelect, NativeSlider, NativeLabels, NativeStacks, NativeGrid, NativePanel, NativeProgressIndicator, NativeLevelIndicator, NativeControlSizing, `MacOS*Conformance`, font and LinuxGUIControls assertions.
2. Record known source limits as catalog notes: ISelect is index-only; ISlider's range is fixed at construction with a 1,000-interval cap; the scroll offset is vertical only; macOS rejects bordered fonts above 20 pt; LinuxImageView stops painting a closed handle.
3. Windows, iOS and Android are missing, with evidence unavailable.
4. Pending ids (`IFontFace.metrics` and `.glyph`, if CX-UIA-02 records IFontFace in scope) are classified in their owner shard. `GUI.rasterText` is retired and not classified.
5. Branch from `main` after Claude integrates the CX-UIA-02 follow-up (no stacking). Drafting earlier on a local branch off `codex/cx-uia-02-shards` is fine; rebase onto `main` before opening the PR.

**Acceptance**

- [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check --strict --owner <each owner above> --junit ui0-macos-<id>=… --junit ui0-linux-<id>=…` exits 0 (0 unclassified slots for these owners; retired slots excluded), and test_ui0_catalog.py passes.
- [ ] Every passed cell names a node id, an assertion and its run id. The PR-body report gives counts per owner and platform.

**Risks**

- Inherited operations multiply the assertions to check per concrete control; budget for it.
- IFontFace's scope depends on CX-UIA-02's decision.

<a id="cx-uia-05"></a>

##### CX-UIA-05 · ui-0-broader-surface: classify every GUI, App, UI and Tray export outside the interfaces

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ui-0-broader-surface`
- **Depends on:** [CX-UIA-02](#cx-uia-02); [CL-UIA-24](claude.md#cl-uia-24) (to finish)
- **Why not now:** Needs CX-UIA-02's follow-up (shard loader and surface schema) on main; its release lands through CL-UIA-24.
- **Parallel-safe with:** CX-UIA-03, CX-UIA-04, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-03

> **Writer note:** The release proposal goes in the PR body with `REQUEST(CL-UIA-24)`; this packet commits no denominator.

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

**Owned paths**

- docs/design/native-ui-catalog/surface/{GUIModules,App,UI,Tray}.toml (new)
- src/tests/python/test_ui0_surface.py (new: the export-coverage case)

**Must not touch**

- `src/**`
- tools/qualification/schema.py and denominators.py
- tools/qualification/denominators.toml (no fragment: the release lands through CL-UIA-24)
- docs/design/native-ui-api-inventory.md (no new tables, and never a row shaped ``| `X.y` |``) and native-ui-parity.md
- src/tests/python/test_ui0_catalog.py
- docs/design/plan-reference.md
- PLAN.md

**Steps**

1. Enumerate every export of the GUI, App, UI and Tray btrc.toml manifests and each exported module's top-level classes, interfaces and enums.
2. Classify the GUI modules: ActionMailbox, ApplicationSlot (private), Font, FreeType/FreeTypeFace, GUICaptureLayer, GUIInt, TextRun, Raster (legacy per D24), and MacOS.AppKitText and MacOS.MacOSRunLoop (the provider-internal Tray seam). Each gets a family and milestone, or a legacy, provider-internal or out-of-scope disposition with a reason.
3. Classify App: AppError/AppErrorCode, AppKeyModifiers, `AppPointer*`, `AppScroll*`, AppKeyAction, AppKeyCode (27 named values plus unknown, not the 24 the roadmap quotes) and AppKeyboardEvent. They link to N06-N10 and UI3.
4. Classify UI exports (Element, Render, Semantics with its 512-byte limits, Text, TextRaster, Typography, UIEventKind) as D24 reuse or custom renderer.
5. Classify Tray exports (ITray, SystemTray, Tray/TrayItem/TraySignal) under N56 and UI11.
6. Put proposed ids in the `operations` lists of `family` rows (they become pending), and put the release proposal (ids, count, sha256 from `Denominator.digest`) in the PR body.
7. Add a case to test_ui0_surface.py that fails when any exported symbol has no row.
8. Binding rule: add no ``| `X.y` |`` rows to native-ui-api-inventory.md; it is a regex source of the frozen release until CL-UIA-24 repoints it.

**Acceptance**

- [ ] test_ui0_surface.py passes, including the export-coverage case, with 0 unclassified exports, and test_ui0_catalog.py passes.
- [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check --strict --kind surface` exits 0; the proposals are reported as pending.
- [ ] lint, format-check and git diff --check pass. The PR-body report follows the protocol, with the release proposal and `REQUEST(CL-UIA-24)`.

**Risks**

- Counting each enum value as an operation would inflate the denominator; count the type instead.
- It integrates only after CL-UIA-24, which lands the release it proposes.

<a id="cx-uia-06"></a>

##### CX-UIA-06 · ui-0-host-matrix: UI evidence hosts per platform, plus the Linux desktop check script

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 4 agent-hours
- **PLAN items:** `ui-0-host-matrix`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-02, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Review change:** GPU-adapter claim corrected (§10 F8).

**Owned paths**

- docs/design/native-ui-catalog/hosts.toml (new)
- src/tests/python/test_native_ui_hosts.py (new)
- tools/ui/linux-desktop-check.sh (new)

**Must not touch**

- docs/qualification/devices.toml (send Claude any needed rows)
- `src/compiler/**`
- `src/stdlib/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Fill hosts.toml for each platform × frontend × evidence class (automation, accessibility tree, assistive technology, physical input/IME, GPU).
2. macOS: hosted macos-15 for automation and GPU correctness (paravirtual Metal adapter), and mac-m1-max for GPU, VoiceOver, IME and Accessibility Inspector.
3. Linux: the cloud container and ci.yml under Xvfb and weston headless with lavapipe for automation; linux-fractal-north (unverified per D7) for Orca, IME, HiDPI and GPU reset.
4. Windows: windows.yml windows-latest x64 and windows-11-arm (availability unverified). Narrator and hardware are unavailable (D8).
5. iOS: the owner's Mac simulator after tooling-ios-simulator-runtimes, with GitHub macOS simulators as the automation stand-in. Add iPhone and iPad simulator rows for `ios`, told apart by `provenance.device_class`.
6. Android: the owner's Mac emulator after tooling-android-sdk-ndk, and the CI emulator after tooling-android-ci-emulator.
7. Mobile devices are unavailable (D8).
8. Every unavailable row lists its blocked_by PLAN item ids. Record the disk budget (Android SDK/NDK/AVDs about 10-15 GB, iOS runtimes) against the 100 GB rule.
9. Write test_native_ui_hosts.py. It checks the schema, that every slot names a runner or 'unavailable', that device ids exist in docs/qualification/devices.toml, and that blocked_by ids are PLAN.md items.
10. Write tools/ui/linux-desktop-check.sh as one command for MAC-UIA-01. It records GPU/driver, compositor, session and scales, runs the Linux GUI fixture with Orca reading a button label (AT-SPI event log), runs a GPU-view device-reset trial, and writes JSON.

**Acceptance**

- [ ] python -m pytest src/tests/python/test_native_ui_hosts.py src/tests/python/test_device_registry.py -q passes.
- [ ] bash -n tools/ui/linux-desktop-check.sh passes, and shellcheck too where installed.
- [ ] Claude records the table as consistent with D7 and D8, so no new owner decision is needed. The PR-body report follows the protocol.

**Risks**

- windows-11-arm runner availability is an open assumption in PLAN.
- The owner sign-off item in items.json is replaced by consistency with D7/D8; the owner may still want to review.
- The catalog loader (`ui_catalog.py`) skips `hosts.toml` explicitly, so test_native_ui_hosts.py is its only validator.

<a id="cx-uia-07"></a>

##### CX-UIA-07 · ui-0-doc-reconcile: GUI/UI/Tray/App READMEs and the roadmap docs derived from the catalog

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 4 agent-hours
- **PLAN items:** `ui-0-doc-reconcile`
- **Depends on:** [CX-UIA-03](#cx-uia-03); [CX-UIA-04](#cx-uia-04); [CX-UIA-05](#cx-uia-05); [CX-UIA-30](#cx-uia-30); [CL-UIA-03](claude.md#cl-uia-03)
- **Why not now:** Needs the completed operation map (CX-UIA-03/04), the case map (CX-UIA-30), the broader surface (CX-UIA-05) and the BTRSmith caller counts (CL-UIA-03).
- **Parallel-safe with:** CX-UIA-09, CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-04

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

> **Review change:** Excludes `native-ui-parity.md`'s Review checkpoint section, which `CL-P1-01` edits (§10 C16).

**Owned paths**

- src/stdlib/GUI/README.md
- src/stdlib/UI/README.md
- src/stdlib/Tray/README.md
- src/stdlib/App/README.md
- docs/design/native-ui-parity.md (except the Review checkpoint section, which CL-P1-01 owns)
- docs/design/native-ui-api-inventory.md
- src/tests/python/test_ui0_doc_counts.py (new: the doc-count case)

**Must not touch**

- PLAN.md (send section text to Claude in the PR body)
- docs/design/plan-reference.md
- `src/stdlib/**/*.btrc`
- src/tests/python/test_ui0_catalog.py and every shard under docs/design/native-ui-catalog/

**Steps**

1. Give every implemented or unfinished claim a source or test citation. Reconcile the GUI README's statement that GPU subtree shutdown, worker publication and dialogs prevent qualification with MacOSGPUView, MacOSComposedCapture and the catalog states.
2. Label Raster as legacy (D24).
3. Refresh the audit revision (4e5c982).
4. Derive these from the catalog: the family matrix counts (from `families.toml`), the AppKeyCode count, the IApplication factory set and the slot totals.
5. Note that the Linux tray test compiles only through the reference frontend and skips without a StatusNotifierWatcher.
6. Record the D21 floors (iOS 17, API 29, Windows 11) and the pending macOS minimum (Stage 24 Q1).
7. Add a doc-count case in test_ui0_doc_counts.py: every count quoted in the two roadmap docs equals the derived count.
8. The "Broader surface" prose never puts a backticked `Owner.member` in a table's first column, and no N/E row id in native-ui-parity.md changes: both documents are regex sources of the frozen release until CL-UIA-24 repoints it.

**Acceptance**

- [ ] test_ui0_doc_counts.py, including the doc-count case, and test_ui0_catalog.py pass.
- [ ] git diff --check and make lint pass. The PR body carries the Stage 30 status text for Claude.

**Risks**

- native-ui-parity.md is long and dense with prose; keep edits to claims and counts.

<a id="cx-uia-30"></a>

##### CX-UIA-30 · ui-0-operation-map (cases): classify the 47 E-cases × 5 platforms × 2 frontends (470 slots)

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 30 (UI0) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-0-operation-map` (the case slots: Stage 30's exit classifies all 470)
- **Depends on:** [CX-UIA-02](#cx-uia-02)
- **Why not now:** Needs CX-UIA-02's follow-up (shard loader and the `cases/` layout) integrated on main, and the shared UI0 evidence run Claude dispatches on that SHA.
- **Parallel-safe with:** CX-UIA-03, CX-UIA-04, CX-UIA-05, CX-UIA-06, CX-UIA-09, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-03, CL-UIA-24

> **Writer note:** New on 2026-10-03 ([codex-ui-lanes.md](codex-ui-lanes.md), wave 2). No packet owned the 470 ui-case slots that PLAN's Stage 30 exit requires classified; splitting the E-cases between CX-UIA-03 and 04 was rejected to keep their shard files disjoint. codex-ui-lanes.md calls it `ui-0-case-map`, a packet name, not a PLAN id.

**Owned paths**

- docs/design/native-ui-catalog/cases/E01-E24.toml (new)
- docs/design/native-ui-catalog/cases/E25-E47.toml (new)

**Must not touch**

- `src/**`
- `tools/qualification/*.py`
- docs/design/native-ui-catalog.toml (the seed) and every other shard under docs/design/native-ui-catalog/
- docs/design/native-ui-parity.md (its E-row ids are a frozen source until CL-UIA-24)
- docs/design/plan-reference.md
- PLAN.md

**Steps**

1. Branch `codex/cx-uia-30` from `main` after Claude integrates the CX-UIA-02 follow-up (no stacking). Drafting earlier on a local branch off `codex/cx-uia-02-shards` is fine; rebase onto `main` before opening the PR.
2. For every E-case (E01–E47) × {macos, linux, windows, ios, android} × {reference, selfhost}, find the fixture or test that exercises it and classify the slot in the compact form: implementation, evidence status, regression node ids, links and notes.
3. Evidence comes from the shared UI0 evidence run: Claude's `focus=native-gui` dispatch of ci.yml and macos.yml on the `main` SHA that landed the follow-up, recorded as `[runs.ui0-linux-<id>]` and `[runs.ui0-macos-<id>]` with `btrc_revision` set to that SHA. Download with `gh run download <id> -n junit-ci-native-gui` or `-n junit-macos-native-gui` within 14 days; if the artifacts have expired, dispatch one fresh pair or ask Claude.
4. No runner: Windows, iOS and Android are `implementation = "missing"` with `evidence.status = "unavailable"`, and `covered_by = []` where no runner exists.
5. Baselines: E40 on Linux is implementation `partial` with evidence `implemented-unverified` and a note citing the drop of the 4,097th event (the reproduction stays on CX-UIA-11's branch, D24); E46 is `missing` (`windowShouldClose` is always true; SDL closes on request); E47 is `missing`.

**Acceptance**

- [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check --strict --kind ui-case --junit ui0-macos-<id>=… --junit ui0-linux-<id>=…` exits 0 (retired slots excluded), and test_ui0_catalog.py passes.
- [ ] The PR body has a table of passed, implemented-unverified, source-only and missing counts per E-range and platform.
- [ ] Lane CI is green (run ids; windows.yml "green (scope only)").

**Risks**

- The evidence run's JUnit artifacts expire after 14 days, so record the run ids promptly.
- A case that a fixture covers only in part stays implemented-unverified, never passed.
- CX-UIA-10 and CX-UIA-11 route their case classification changes through this packet while it is open (§3.3).

#### Stage 31: UI1 shells on all five platforms and the toolkit decision

<a id="cx-uia-09"></a>

##### CX-UIA-09 · ui-1-shell-fixture: portable native-shell fixture, probe contract and provider × frontend × sanitizer harness

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-1-shell-fixture`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-02, CX-UIA-03, CX-UIA-04, CX-UIA-05, CX-UIA-06, CL-UIA-21, CX-UIA-12, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Review change:** GPU-frame rows run on hosted macOS: adapter-gated GPU tests passed rather than skipped in run 37084025400 (§10 F8).

**Owned paths**

- src/tests/native/gui/shell/ (new: NativeShell.btrc, probes/macos/ShellProbe.h and .m, probes/linux/)
- src/tests/python/test_native_ui_shell.py (new: the portable harness and the windows-x86_64 provider-missing case)
- src/tests/python/native_ui_shell_fixtures.py (new)
- src/tests/python/test_native_ui_shell_macos.py and test_native_ui_shell_linux.py (new: the initial per-platform rows; the Makefile's `test_native_ui_*.py` glob collects them)

**Must not touch**

- `src/stdlib/**` (no provider change in this packet)
- Makefile
- `src/compiler/**`
- `src/language/**`
- `src/runtime/**`
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Write NativeShell.btrc using only the GUI facade and `I*` interfaces. It opens a window with an ITextField, an IButton, an IScrollView of 50 label rows and an IGPUView child.
2. One scripted run does Tab traversal, a text entry plus Enter, one button activation, a scroll, and one GPU frame or a classified not-ready outcome, then closes.
3. Run 100 open/close cycles, counting owned native handles and live registrations; expect 0 leaks.
4. Define the probe contract. On macOS it is C/Objective-C after NativePointerEvents.m and StackProbe.m; on Linux it uses the bound `btrcSdlPush*` functions.
5. The probes inject key, text and pointer events, query the focused view, dump the accessibility tree as JSON and count native views. macOS walks NSAccessibility in-process; Linux SDL records 'no bridge'.
6. E46 baseline: record today's close of a dirty draft as missing. macOS windowShouldClose always returns true, and Linux closes on SDL_EVENT_WINDOW_CLOSE_REQUESTED.
7. E47 harness: the fixture checkpoints its draft and scroll anchor atomically, and 100 fresh-process restarts assert that the draft restores and no commit replays, using a side-effect journal. The stdlib restoration contract stays missing.
8. Parametrize the shell rows over macos, linux-x11 and linux-wayland × python/selfhost × plain/ASan-UBSan, in test_native_ui_shell_macos.py and test_native_ui_shell_linux.py, with the portable harness in test_native_ui_shell.py. CL-UIA-21 has landed, so the Wayland rows run through `tools/ui/headless-session.sh --wayland`.
9. test_native_ui_shell.py also asserts the windows-x86_64 provider-missing compile diagnostic, records iOS and Android as unavailable until Stage 24, and writes ledger/1 JSONL under build/ui-shell/.

**Acceptance**

- [ ] In the cloud, `nix develop --command tools/ui/headless-session.sh --x11 -- python3 -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_linux.py -q -rs` passes linux-x11 for python and selfhost, plain and sanitized, and passes the windows-x86_64 provider-missing case; the `--wayland` counts are reported too.
- [ ] macos.yml on the draft PR passes the macOS rows for both frontends, including the GPU-frame rows (hosted macos-15 exposes a paravirtual Metal adapter). Only GPU timing rows are covered_by MAC-UIA-02.
- [ ] The JSONL loads through tools.qualification's LedgerDocument.
- [ ] btrc-format check and make lint pass. The PR-body report follows the protocol.

**Risks**

- ITextField has no commit event today, so the text commit is observed by reading the value and stays an E01 gap until UI2.
- Sanitized GUI runs on hosted macOS are slow. Keep the cycle count configurable, with 100 as the gate.
- In-process NSAccessibility needs no TCC permission; a cross-process AXUIElement would.

<a id="cx-uia-10"></a>

##### CX-UIA-10 · ui-1-macos: AppKit native-shell proof on hosted macOS runners

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 7 agent-hours
- **PLAN items:** `ui-1-macos`
- **Depends on:** [CX-UIA-09](#cx-uia-09); [CX-UIA-02](#cx-uia-02)
- **Why not now:** Needs CX-UIA-09's fixture and harness and CX-UIA-02's catalog format (the follow-up), both integrated on main; plain dependencies, no stacking. Allowed by D27 once both exist.
- **Parallel-safe with:** CX-UIA-11, CX-UIA-12, CX-UIA-13, CX-UIA-07, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-06

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

> **Review change:** GPU-adapter claim corrected (§10 F8).

**Owned paths**

- src/tests/native/gui/shell/probes/macos/ (AX dump and key-view probes)
- src/tests/python/test_native_ui_shell_macos.py (held once CX-UIA-09 is integrated)
- docs/design/native-ui-catalog/evidence/ui1-macos.toml (new)

**Must not touch**

- `src/stdlib/GUI/**` (no provider change)
- `src/compiler/**`
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Write an AX tree probe. It walks accessibilityChildren from the window and emits role, label, value, focused and frame as JSON, uploaded as a macos.yml artifact.
2. Prove key-view traversal NSTextField -> NSButton -> NSScrollView -> MacOSGPUView, and record the GPU child's focusability as a pass or an explicit gap.
3. Run 100 lifecycle cycles, counting native views (subview totals and CallbackScope registrations).
4. Record evidence, `test` records and notes in the evidence shard, with citations: windowShouldClose always true (E46 baseline), bordered button/select fonts above 20 pt rejected, and the synchronous NSOpenPanel runModal. Route classification changes to the owner shard (§3.3: ask the holder while it is open).

**Acceptance**

- [ ] On macos.yml (the draft PR's run, or a focus=native-gui dispatch), the macOS rows of test_native_ui_shell_macos.py pass for python and selfhost, plain and ASan/UBSan (run id).
- [ ] The AX artifact shows the field, button, scroll area and GPU-child status, and 100 cycles leak 0 views.
- [ ] The evidence shard validates in test_ui0_catalog.py (and ui_catalog.py's shard check). The PR-body report follows the protocol.

**Risks**

- Hosted macos-15 differs from the owner's macOS 27 with Xcode 27A266a; MAC-UIA-02 confirms on the real host.
- Hosted macos-15 exposes a paravirtual Metal adapter: GPU correctness rows run there; real-GPU timing, pacing and idle-CPU rows stay owner-tier.

<a id="cx-uia-11"></a>

##### CX-UIA-11 · ui-1-linux-sdl-baseline: shell fixture on the SDL provider under X11 and Wayland, with the E40 reproduction on a branch

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 7 agent-hours
- **PLAN items:** `ui-1-linux-sdl-baseline`
- **Depends on:** [CX-UIA-09](#cx-uia-09); [CL-UIA-21](claude.md#cl-uia-21); [CX-UIA-02](#cx-uia-02)
- **Why not now:** Needs CX-UIA-09 (fixture), CL-UIA-21 (weston headless and AT-SPI in the dev shell) and CX-UIA-02 (catalog, the follow-up); CX-UIA-09 and CX-UIA-02 must be integrated on main (plain dependencies, no stacking).
- **Parallel-safe with:** CX-UIA-10, CX-UIA-12, CX-UIA-13, CX-UIA-07, CX-UIA-18, CX-UIA-19, CX-UIA-20, CL-UIA-06

**Owned paths**

- src/tests/native/gui/shell/probes/linux/
- src/tests/python/test_native_ui_shell_linux.py (held once CX-UIA-09 is integrated)
- src/tests/native/gui/linux/LinuxEventBoundary.btrc (new; only on branch codex/cx-uia-11-e40-repro, per D24)
- docs/design/native-ui-catalog/evidence/ui1-linux.toml (new)

**Must not touch**

- `src/stdlib/GUI/**` (no provider change; the fixes belong to CX-UIA-23 and CX-UIA-27)
- `src/compiler/**`
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Run the shell fixture under X11 (Xvfb) and Wayland (weston headless) through both frontends, plain and sanitized.
2. Record evidence, `test` records and notes in the evidence shard: the controls are custom and the AT-SPI bridge is missing (the dump shows the SDL window with no accessible children). Route classification changes to the owner shard (§3.3: ask the holder while it is open).
3. On the separate branch, reproduce E40. Push 4,095, 4,096, 4,097 and 8,193 identifiable events through btrcSdlPushKey/btrcSdlPushText before one loop turn, with a release, a committed text and a close request at the boundary in separate trials.
4. Show that pumpEvents dequeues the 4,097th event and drops it. Record the fault position as a failed catalog row; it is not merged (D24).
5. Record evidence, `test` records and notes in the evidence shard, with citations: _visible is never updated on hide or minimize; the provider throws after 120 unavailable frames; key() returns false in LinuxButton, LinuxSlider and LinuxScrollView; LinuxSlider.focus is a no-op; SDL text input has no preedit. Route classification changes to the owner shard (§3.3: ask the holder while it is open).

**Acceptance**

- [ ] 'tools/ui/headless-session.sh --x11 -- python -m pytest src/tests/python/test_native_ui_shell_linux.py -q' and the --wayland variant pass for python and selfhost, plain and sanitized (counts reported).
- [ ] The E40 branch fails deterministically at the recorded position (log in the PR body).
- [ ] The merged part keeps ci.yml green (run id). The PR-body report follows the protocol.

**Risks**

- The SDL Wayland backend may not get a usable Vulkan surface on weston headless with lavapipe. Record it and keep X11 as the gate.
- Landing a failing test is forbidden, so the reproduction waits on its branch for CX-UIA-23.

<a id="cx-uia-12"></a>

##### CX-UIA-12 · GTK4/WebGPU interop pre-spike in plain C (throwaway; feeds ui-1-linux-gtk-spike)

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-1-linux-gtk-spike#c-prespike`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-02, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-13, CX-UIA-18, CX-UIA-19, CX-UIA-20

> **Writer note:** On UI2's path (CL-UIA-12 waits for it); schedule early (2026-10-03, [codex-ui-lanes.md](codex-ui-lanes.md) Task 3).

**Owned paths**

- docs/design/linux-gtk4-feasibility.md (new; the findings PR on codex/cx-uia-12 carries only this file, so it runs the docs tier)
- spikes/gtk4-webgpu/ on branch codex/cx-uia-12-spike (pushed, no PR, never merged)

**Must not touch**

- `src/**`
- flake.nix and flake.lock (use 'nix shell' on the pinned nixpkgs instead)
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Build a plain-C GtkApplicationWindow with a GtkEntry, a GtkButton, a GtkScrolledWindow holding a 1,000-row GtkListView, and a WebGPU child, using 'nix shell' with gtk4, wgpu-native, weston, xvfb-run and at-spi2-core from the pinned nixpkgs.
2. Try each GPU-child route and record its result: a Wayland subsurface from GdkWaylandSurface's wl_surface given to wgpu-native; an X11 foreign child (GTK4 has none, so confirm that); dmabuf into GdkDmabufTexture or GtkGraphicsOffload (check wgpu-native v27 external-memory support); CPU readback, measured only as a non-final baseline.
3. Prove overlapping native controls (GtkOverlay) and clipping over the GPU child, dump the AT-SPI tree with pyatspi, and run 100 create/destroy cycles under ASan or valgrind.
4. Write the record: for each route, works or fails with reproduction commands, frames presented, clip correctness, the AT-SPI JSON, leak counts, and what a btrc-hosted provider needs from the GObject binding.

**Acceptance**

- [ ] linux-gtk4-feasibility.md has a result and a reproduction for every route on both Wayland and X11.
- [ ] It states that it does not satisfy D23, which requires a btrc-hosted window.
- [ ] git diff --check passes. The PR-body report follows the protocol.

**Risks**

- No route may work with wgpu-native 27. That is a valid D23 input, not a failure of the packet.
- Without nix, versions are unpinned; record the exact versions used.

<a id="cx-uia-13"></a>

##### CX-UIA-13 · Native-shell design notes for Win32, UIKit and Android Views (docs-only spike)

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-1-windows-shell#design-note`; `ui-1-ios-shell#design-note`; `ui-1-android-shell#design-note`
- **Depends on:** none
- **Parallel-safe with:** CL-UIA-01, CL-UIA-02, CL-UIA-03, CX-UIA-01, CX-UIA-02, CX-UIA-06, CL-UIA-21, CX-UIA-09, CX-UIA-12, CX-UIA-18, CX-UIA-19, CX-UIA-20

**Owned paths**

- docs/design/native-ui-shells/{windows,ios,android}.md (new; one file per platform)

**Must not touch**

- `src/**`
- docs/design/native-interop-ownership.md and platform-target-contract.md (cite them; never edit)
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. For each platform, describe the provider directory (GUI/Windows, GUI/IOS per D24, GUI/Android) and the host-owned loop (D24): MsgWaitForMultipleObjectsEx; UIApplicationMain with a scene delegate; an Activity with the main Looper.
2. Also describe the native controls (ComCtl32 v6 EDIT/BUTTON; UITextField/UIButton/UIScrollView; EditText/Button/RecyclerView) and the GPU child (a child HWND; a CAMetalLayer view; a SurfaceView with Vulkan).
3. Map each interop need to a native-interop-ownership.md step: WndProc through function tables (step 2), UI Automation through COM (step 5), UIKit delegates (steps 3 and 6), JNI (steps 4 and 7). Map each target and host need to platform-target-contract.md rows and the Stage 25 hosts.
4. Name each platform's accessibility probe (IUIAutomation, XCUITest/UIAccessibility, UiAutomator) and its evidence host from hosts.toml.
5. List the compiler requests for Claude and the PLAN item ids each shell waits on.
6. `ios.md` has an iPadOS section (iOS and iPadOS are one lane, `GUI/IOS`): E16 scenes, size classes and split view, Stage Manager, the hardware keyboard, the pointer, `UIDeviceFamily [1,2]`, and the ios slots that need iPad `device_class` evidence.

**Acceptance**

- [ ] Claude's feasibility and parity reviewer finds no blocking gap; the note is linked in the PR.
- [ ] Every dependency cites a PLAN item id. git diff --check passes, and the PR-body report follows the protocol.

**Risks**

- The Stage 27 and 29 designs may change; the notes cite their review state.

<a id="cx-uia-14"></a>

##### CX-UIA-14 · ui-1-linux-gtk-spike: btrc-hosted GTK4 provider prototype on Wayland and X11

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-1-linux-gtk-spike`
- **Depends on:** [CL-UIA-08](claude.md#cl-uia-08); [CX-UIA-11](#cx-uia-11); [CX-UIA-12](#cx-uia-12)
- **Why not now:** Needs the GObject binding through Tier B (CL-UIA-08, which waits for Stage 27 steps 1-2), the SDL baseline for comparison, and the GPU route proven by CX-UIA-12.
- **Parallel-safe with:** CX-UIA-21, CX-UIA-22, CX-UIA-23, CX-UIA-24

**Owned paths**

- fragment (not held): branch codex/cx-uia-14 only: src/stdlib/GUI/LinuxGTK/ (prototype provider), a GUI/btrc.toml fragment, src/tests/native/gui/shell/probes/linux-gtk/
- merged: docs/design/linux-gtk4-feasibility.md (btrc-hosted section)

**Must not touch**

- `src/stdlib/GUI/Linux/**` (the shipping SDL provider)
- src/stdlib/GUI/Linux/GLibMainContext.btrc (consume only)
- `src/compiler/**`
- `src/language/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Prototype the provider with every ownership going through sunk-results and signals with CallbackScope: IApplication over GLibMainContext as the host loop, IWindow (GtkWindow), ITextField (GtkEntry), IButton (GtkButton), IScrollView with a GtkListView, and IGPUView over the route CX-UIA-12 proved.
2. Run the shell fixture through both frontends on Wayland and X11, with AT-SPI dumps, focus traversal and 100 cycles.
3. IME: run ibus or fcitx5 in the headless session if it works. Otherwise mark IME 'needs desktop host' (MAC-UIA-01).
4. Fill the D23 table: native controls, keyboard focus, IME and AT-SPI tree, each a pass or a named blocker with a reproduction.

**Acceptance**

- [ ] The feasibility record has the D23 table for both frontends × Wayland/X11, with linked logs and artifacts.
- [ ] The prototype is not merged before CL-UIA-10's decision. The PR-body report follows the protocol.

**Risks**

- IME evidence may be unobtainable without a real desktop, which leaves D23's criterion untested.
- The prototype directory name awaits the decision.

<a id="cx-uia-15"></a>

##### CX-UIA-15 · ui-1-windows-shell: Win32 GUI provider skeleton and shell proof

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-1-windows-shell`
- **Depends on:** [CX-UIA-09](#cx-uia-09); [CX-UIA-13](#cx-uia-13); platforms-p1-target-spec → [CL-P1-06](claude.md#cl-p1-06); platforms-p1-provider-filters → [CL-P1-14](claude.md#cl-p1-14); platforms-interop-function-table-calls → [CL-P2-06](claude.md#cl-p2-06); platforms-w1-win32-com-imports → [CL-P2-10](claude.md#cl-p2-10); [CL-P2-29](claude.md#cl-p2-29); [CX-P2-25](#cx-p2-25); [CX-P1-07](#cx-p1-07)
- **Why not now:** Bucket 3 prerequisites are missing on 8b73c79: target rows and provider filters (Stage 24), callback tables for WndProc and COM for UI Automation (Stage 27), and wgpu-native Windows archives (Stage 28).
- **Parallel-safe with:** CX-UIA-16, CX-UIA-17, CX-UIA-24, CX-UIA-25, CX-UIA-26, CX-UIA-27

> **Review change:** Adds the landed UI2/UI3 surface, implemented or typed-unsupported (§10 P5).

> **Review change:** Runs on its host lane's provider-suite job (`CX-P1-07/08/09`), not on windows.yml or a nonexistent macos.yml simulator job, and owns its rows in the shared shell test (§10 C6, F6).

**Owned paths**

- src/stdlib/GUI/Windows/ (new)
- src/tests/native/gui/shell/probes/windows/
- fragment (not held): a GUI/btrc.toml provider fragment
- src/tests/python/test_native_ui_shell_windows.py (new) and native_ui_shell_fixtures.py (this platform's rows; shared append-only)
- src/tests/python/test_package_ownership.py (the Windows GUI no-provider case only, in the `fragment:` commit)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/runtime/**`
- `src/stdlib/GUI/I*.btrc` and GUI.btrc
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Write the GUIProvider and an application loop woken through MsgWaitForMultipleObjectsEx, with an HWND window using per-monitor DPI v2.
2. Add ComCtl32 v6 EDIT and BUTTON controls through an activation context, a scroll container and a WebGPU child HWND. WndProc and subclass callbacks are checked through function-table bindings.
3. Add a UI Automation tree probe through COM IUIAutomation, and run 100 cycles counting HWND and GDI/USER objects with GetGuiResources.
4. Cross-compile in the cloud with zig 0.16 for x86_64-windows-gnu; run on host-windows.yml's provider-suite job.
5. Implement the UI2 and UI3 methods already landed (ui2-approved.md, ui3-approved.md) where the Win32 shell supports them; every other method throws the typed unsupported error, and its catalog rows stay 'missing'.

**Acceptance**

- [ ] On host-windows.yml's provider-suite job for the draft PR, the windows-x86_64 rows of test_native_ui_shell_windows.py pass both frontends (run id), the UIA tree artifact is uploaded, and 100 cycles leak 0 HWND or GDI objects.
- [ ] The zig cross-compile from Linux passes. The PR-body report follows the protocol.

**Risks**

- Hosted Windows runners may not expose a UIA desktop session; record it as unavailable if so.
- The Win32-versus-WinUI choice is still open.

<a id="cx-uia-16"></a>

##### CX-UIA-16 · ui-1-ios-shell: UIKit GUI provider skeleton and shell proof on the simulator

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-1-ios-shell`
- **Depends on:** [CX-UIA-09](#cx-uia-09); [CX-UIA-13](#cx-uia-13); platforms-p1-target-spec → [CL-P1-06](claude.md#cl-p1-06); tooling-ios-simulator-runtimes → [MAC-P1-02](owner.md#mac-p1-02); platforms-p1-host-ios → [CX-P1-08](#cx-p1-08); platforms-i1-objc-protocol-adapters → [CL-P2-21](claude.md#cl-p2-21); platforms-i1-app-lifecycle → [CX-P2-36](#cx-p2-36); platforms-i2-gpu → [CX-P2-39](#cx-p2-39)
- **Why not now:** Bucket 3 prerequisites are missing on 8b73c79: no iOS target in either compiler (Stage 24), no simulator runtime or test host (Stages 23 and 25), and no UIApplicationDelegate/scene adapters or CAMetalLayer hosting (Stage 29).
- **Parallel-safe with:** CX-UIA-15, CX-UIA-17, CX-UIA-24, CX-UIA-25, CX-UIA-26, CX-UIA-27

> **Review change:** Adds the landed UI2/UI3 surface, implemented or typed-unsupported (§10 P5).

> **Review change:** Runs on its host lane's provider-suite job (`CX-P1-07/08/09`), not on windows.yml or a nonexistent macos.yml simulator job, and owns its rows in the shared shell test (§10 C6, F6).

**Owned paths**

- src/stdlib/GUI/IOS/ (new; D24 name)
- src/tests/native/gui/shell/probes/ios/
- tools/ui/run-ios-shell.sh (new; for MAC-UIA-03)
- fragment (not held): a GUI/btrc.toml provider fragment
- src/tests/python/test_native_ui_shell_ios.py (new) and native_ui_shell_fixtures.py (this platform's rows; shared append-only)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/stdlib/GUI/I*.btrc` and GUI.btrc
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Use UIApplicationMain with a process-scoped app delegate and an instance-scoped scene delegate, through Stage 29's instantiated Objective-C adapters. GUI.run maps to the OS-owned loop, which feeds ui-2-contract-executor.
2. Add UITextField, UIButton, UIScrollView and a CAMetalLayer-backed WebGPU view.
3. Add an accessibility probe through UIAccessibility/XCUITest, and run 100 scene connect/disconnect cycles.
4. Build and run on a GitHub macOS runner's simulator. Prepare tools/ui/run-ios-shell.sh for the owner's Mac.
5. Implement the UI2 and UI3 methods already landed (ui2-approved.md, ui3-approved.md) where the UIKit shell supports them; every other method throws the typed unsupported error, and its catalog rows stay 'missing'.

**Acceptance**

- [ ] The host-ios.yml provider-suite job runs the shell fixture app from each frontend on the simulator, with an accessibility artifact and 100 leak-free cycles (run id).
- [ ] The physical device is recorded as awaiting hardware (D8). The PR-body report follows the protocol.

**Risks**

- An iOS 17 runtime may not install under Xcode 27 (an open PLAN assumption).

<a id="cx-uia-17"></a>

##### CX-UIA-17 · ui-1-android-shell: Android Views shell proof (Activity plus checked JNI)

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 31 (UI1) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-1-android-shell`
- **Depends on:** [CX-UIA-09](#cx-uia-09); [CX-UIA-13](#cx-uia-13); platforms-p1-target-spec → [CL-P1-06](claude.md#cl-p1-06); tooling-android-sdk-ndk → [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03); platforms-p1-host-android → [CX-P1-09](#cx-p1-09); tooling-android-ci-emulator → [CX-P1-05](#cx-p1-05); platforms-a1-checked-jni → [CL-P2-24](claude.md#cl-p2-24); platforms-a1-activity-lifecycle → [CX-P2-41](#cx-p2-41); [CX-P2-44](#cx-p2-44); [CL-P1-15](claude.md#cl-p1-15)
- **Why not now:** Bucket 3 prerequisites are missing on 8b73c79: no Android target (Stage 24), no SDK/NDK or emulator host (Stages 23 and 25), and no checked JNI or Activity lifecycle (Stages 27 and 29), nor the Android GPU surface (CX-P2-44) its WebGPU SurfaceView needs.
- **Parallel-safe with:** CX-UIA-15, CX-UIA-16, CX-UIA-24, CX-UIA-25, CX-UIA-26, CX-UIA-27

> **Review change:** Adds the landed UI2/UI3 surface, implemented or typed-unsupported (§10 P5).

> **Review change:** Waits for `CL-P1-15` (cache identity, after `CL-P1-14`'s platform-directory rule): Stage 24's exit, zero foreign SDK imports and the cache-poisoning matrix, is what a new `{Windows,IOS,Android}` directory relies on (§10 P8).

> **Review change:** Runs on its host lane's provider-suite job (`CX-P1-07/08/09`), not on windows.yml or a nonexistent macos.yml simulator job, and owns its rows in the shared shell test (§10 C6, F6).

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ (new)
- tools/android/shell/ (new; a minimal Java Activity shell that owns no product policy)
- src/tests/native/gui/shell/probes/android/
- tools/ui/run-android-shell.sh (new; for MAC-UIA-03)
- fragment (not held): a GUI/btrc.toml provider fragment
- src/tests/python/test_native_ui_shell_android.py (new) and native_ui_shell_fixtures.py (this platform's rows; shared append-only)

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/stdlib/GUI/I*.btrc` and GUI.btrc
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Write the Java Activity shell and a GUI/Android provider over checked JNI: EditText, Button, RecyclerView and a SurfaceView WebGPU child over Vulkan.
2. Add an accessibility dump through UiAutomator/AccessibilityNodeInfo, and run 100 Activity-recreation cycles plus process-death trials.
3. Build the APKs in the cloud and run them on host-android.yml's provider-suite job (KVM emulator). Prepare tools/ui/run-android-shell.sh for the owner's Mac.
4. Implement the UI2 and UI3 methods already landed (ui2-approved.md, ui3-approved.md) where the Android Views shell supports them; every other method throws the typed unsupported error, and its catalog rows stay 'missing'.

**Acceptance**

- [ ] On the CI emulator, the shell APK from each frontend passes with an accessibility dump, and the recreation and process-death cycles show 0 stale-Activity references (run id).
- [ ] Physical devices are recorded as awaiting hardware (D8). The PR-body report follows the protocol.

**Risks**

- The emulator needs KVM on the runner.
- The Views-versus-GameActivity choice is still open.

#### Stage 32: UI2 contracts (events, executor, lifecycle) and the Library.UI split

<a id="cx-uia-18"></a>

##### CX-UIA-18 · ui-2-contract-control-events: docs-only draft of typed control events, stable keys and setter suppression

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-2-contract-control-events`
- **Depends on:** none
- **Parallel-safe with:** CX-UIA-19, CX-UIA-20, CX-UIA-09, CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13, CL-UIA-01, CL-UIA-03

> **Writer note:** Parallel-safe with CX-UIA-19 and CX-UIA-20: the drafts are separate files and are not part of D27's `.btrc` writer chain (IView, IWindow and `App.btrc`). The index is `index.md`, not `README.md`, which is test-read, so the PR stays docs tier (2026-10-03, [codex-ui-lanes.md](codex-ui-lanes.md) Task 3).

**Owned paths**

- docs/design/ui-contracts/index.md (new)
- docs/design/ui-contracts/ui2-control-events.md (new)

**Must not touch**

- `src/stdlib/**` (no interface edits before approval, per D27)
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Draft the interface changes. ITextField gains draft-change, commit and cancel events.
2. ISelect gains keyed options (key, title, enabled); unselected, loading, empty and error states; and change/commit events. D24's index shim stays until BTRSmith re-pins.
3. ISlider gains preview, commit and cancel plus a coherent setRange(min, max, step), keeping exact 64-bit timeline values outside the native double.
4. IScrollView gains a two-axis offset, scrollTo, the visible rect and an offset-changed subscription. Value types go in a proposed GUI/ControlEvents.btrc.
5. Reuse ICallbackRegistration/CallbackScope, and D24's UIEventKind where it fits. Classify every event as a synchronous native decision or a queued semantic event. Coalesce only replaceable state; setters emit zero user actions.
6. Specify E01-E03, E33 and E34 as fixture outlines, with proposed operation ids.
7. List any compiler request; none is expected.

**Acceptance**

- [ ] The draft lists every new or changed operation id and an outline for each E-case. git diff --check passes, and the PR-body report follows the protocol.
- [ ] It is reviewed only in CL-UIA-13, against real UI1 results.

**Risks**

- It is written before UI1 results exist, so expect revision.
- AppKit-shaped APIs are the review's main rejection reason.

<a id="cx-uia-19"></a>

##### CX-UIA-19 · ui-2-contract-executor: docs-only draft of worker wakeup, fair dispatch and the host-owned loop

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-2-contract-executor`
- **Depends on:** none
- **Parallel-safe with:** CX-UIA-18, CX-UIA-20, CX-UIA-09, CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13, CL-UIA-01, CL-UIA-03

**Owned paths**

- docs/design/ui-contracts/ui2-executor.md (new)

**Must not touch**

- `src/stdlib/**` (including BackgroundJobs, a compiler import)
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Worker publication into the UI executor (IApplication.post requires the UI thread today): a bounded native-loop wakeup with generation and cancel checks, rejection and backpressure outcomes, and completion-after-close semantics tied to BackgroundJobCompletion in BackgroundJobs/BackgroundJobExecutor.btrc.
2. Lossless batch boundaries and fair progress across input, work, timers, presentation and close (E40); suspension classes cancel, defer and replace (E30); queue pressure (E24).
3. An OS-owned-loop entry for UIKit and Android beside GUI.run (D24).
4. Specify E04, E24, E30 and E40: 4,095/4,096/4,097/8,193 events × 100 bursts, and a 10-minute load with p95 delivery ≤ 100 ms, service gaps ≤ 250 ms and close starting within 250 ms.
5. Flag that BackgroundJobs is a compiler import, so its implementation needs the lane's own btrcc and a bootstrap run.

**Acceptance**

- [ ] The draft has operation ids and E-case outlines. git diff --check passes, and the PR-body report follows the protocol.
- [ ] It is reviewed only in CL-UIA-13.

**Risks**

- The BackgroundJobs hook touches compiler-imported code.

<a id="cx-uia-20"></a>

##### CX-UIA-20 · ui-2-contract-lifecycle: docs-only draft of close transactions, exposure, ordered mutation and final release

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-2-contract-lifecycle`
- **Depends on:** none
- **Parallel-safe with:** CX-UIA-18, CX-UIA-19, CX-UIA-09, CX-UIA-10, CX-UIA-11, CX-UIA-12, CX-UIA-13, CL-UIA-01, CL-UIA-03

**Owned paths**

- docs/design/ui-contracts/ui2-lifecycle.md (new)

**Must not touch**

- `src/stdlib/**`
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. IWindow: a close-request decision hook with an asynchronous Save/Discard/Cancel transaction (E46), and resize, scale, activation and exposure observation (E42).
2. IContainer: ordered insert, move and batch with a commit/rollback failure policy (E29).
3. IView: effective interaction state separating local visibility, inherited eligibility, layout participation and exposure (E39), plus a final-release protocol on the UI executor (E31).
4. IImageHandle: retained presentation (E35). Today LinuxImageView stops painting a closed handle while macOS keeps the NSImage.
5. This lane is IView's only writer during UI2. Specify 100 cycles per path, with 0 lost drafts and 0 duplicate saves.

**Acceptance**

- [ ] The draft has operation ids and E-case outlines. git diff --check passes, and the PR-body report follows the protocol.
- [ ] It is reviewed only in CL-UIA-13.

**Risks**

- IView is shared with UI3, UI5 and UI8, so the scope must stay narrow.

<a id="cx-uia-21"></a>

##### CX-UIA-21 · UI2 interface landing branch: approved `I*.btrc` diff, BackgroundJobs hook, portable E-case fixtures and catalog rows

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-2-contract-control-events#interfaces`; `ui-2-contract-executor#interfaces`; `ui-2-contract-lifecycle#interfaces`
- **Depends on:** [CL-UIA-13](claude.md#cl-uia-13); [CL-UIA-12](claude.md#cl-uia-12); [CX-UIA-07](#cx-uia-07)
- **Why not now:** Needs the approved UI2 diff (CL-UIA-13) and the shell harness on main (CL-UIA-12).
- **Parallel-safe with:** CL-UIA-08, CX-UIA-14

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

> **Review change:** No own `btrcc` or bootstrap: `BackgroundJobExecutor.btrc` is outside the compiler's import closure (§10 C17).

**Owned paths**

- src/stdlib/GUI/{ITextField,ISelect,ISlider,IScrollView,IApplication,IWindow,IContainer,IView,IImageHandle}.btrc
- src/stdlib/GUI/GUI.btrc
- src/stdlib/GUI/ControlEvents.btrc (new)
- src/stdlib/BackgroundJobs/BackgroundJobExecutor.btrc (completion hook only)
- src/tests/native/gui/ui2/ (portable fixtures)
- docs/design/native-ui-catalog/operations/ (new UI2 rows, a shard document)
- docs/design/native-ui-api-inventory.md
- fragment (not held): GUI/btrc.toml exports fragment

**Must not touch**

- `src/stdlib/GUI/MacOS/**` and `src/stdlib/GUI/Linux/**` (the stacked branches)
- `src/compiler/**`
- `src/language/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Apply ui2-approved.md exactly to the interfaces and the facade, and add ControlEvents.btrc.
2. Add the BackgroundJobs completion hook. BackgroundJobExecutor.btrc is outside btrcc's import closure (§3.4), so the pinned btrcc is enough; no bootstrap.
3. Write portable fixtures for E01-E04, E29, E31, E35, E39, E40 and E46 against the interfaces only.
4. Add catalog rows for the new operations as the next reviewed ui-operation release (fragment: commit).
5. This branch is the base the macOS and Linux branches stack on; on its own it does not build the providers.

**Acceptance**

- [ ] test_ui0_catalog.py (and ui_catalog.py's shard check) passes with the new ids, and the changed .btrc pass the btrc-format check.
- [ ] test_bootstrap.py reaches its fixed point, and the self-host transpiles have zero warnings with the BackgroundJobs change.
- [ ] The PR-body report names CX-UIA-22 and CX-UIA-23 as the stacked branches.

**Risks**

- Alone, the branch leaves the providers unimplemented, so CI means something only on the stacked branches.
- The BackgroundJobs change affects the compiler's own build.

<a id="cx-uia-22"></a>

##### CX-UIA-22 · ui-2-macos: AppKit implementation of the UI2 contracts

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-2-macos`
- **Depends on:** [CX-UIA-21](#cx-uia-21) (ready)
- **Why not now:** Stacks on the UI2 interface branch (CX-UIA-21).
- **Parallel-safe with:** CX-UIA-23, CL-UIA-08, CX-UIA-14

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

> **Review change:** GPU-adapter claim corrected (§10 F8).

**Owned paths**

- src/stdlib/GUI/MacOS/{MacOSTextField,MacOSSelect,MacOSSlider,MacOSScrollView,MacOSWindow,MacOSApplication,MacOSImageView,MacOSImageHandle,MacOSView,MacOSContainer,MacOSRunLoop,MacOSActionQueue}.btrc
- src/tests/native/gui/ui2/probes/macos/
- fragment (not held): GUI/btrc.toml binding fragment (new AppKit selectors)

**Must not touch**

- `src/stdlib/GUI/I*.btrc` and GUI.btrc (CX-UIA-21)
- `src/stdlib/GUI/Linux/**`
- `src/compiler/**`
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. MacOSTextField: NSTextField delegate draft, commit and cancel events that keep the field editor, selection and undo.
2. MacOSSelect: keyed NSPopUpButton items. MacOSSlider: continuous tracking with one end commit. MacOSScrollView: two-axis offsets from bounds-changed notifications.
3. MacOSWindow: windowShouldClose becomes the decision hook, with an asynchronous sheet. MacOSApplication: a thread-safe wakeup (CFRunLoopSource or performBlock) for worker publication, with no polling timer.
4. Audit final release for every native owner (E31), keep image presentation (E35) and honor effective visibility (E39). Run the portable fixtures through both frontends, plain and ASan/UBSan.

**Acceptance**

- [ ] On macos.yml for the stacked draft PR (and focus=native-gui): E01-E03 produce one product command per commit and 0 setter actions; E04 wakes an idle loop with no timer armed; E29 and E31 pass; E35, E39 and E46 pass at 100 cycles. Both frontends, plain and sanitized (run ids).
- [ ] GPU-dependent rows are left for owner-Mac confirmation. The PR-body report follows the protocol.

**Risks**

- The asynchronous sheet close interacts with the run loop's modal handling; test reentrancy.
- Hosted macos-15 exposes a paravirtual Metal adapter: GPU correctness rows run there; real-GPU timing, pacing and idle-CPU rows stay owner-tier.

<a id="cx-uia-23"></a>

##### CX-UIA-23 · ui-2-linux: SDL provider implementation of the UI2 contracts, lossless pump and exposure repairs

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 32 (UI2) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-2-linux`
- **Depends on:** [CX-UIA-21](#cx-uia-21) (ready); [CX-UIA-11](#cx-uia-11)
- **Why not now:** Stacks on the UI2 interface branch (CX-UIA-21), and brings in CX-UIA-11's E40 reproduction.
- **Parallel-safe with:** CX-UIA-22, CL-UIA-08, CX-UIA-14

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

> **Review change:** Latency thresholds apply to plain builds; sanitized runs on shared 4-core runners check counts and losses only (§10 F19).

> **Review change:** Already depends on `CX-UIA-11`, whose E40 reproduction branch it lands (§3.2) (§10 C16).

**Owned paths**

- src/stdlib/GUI/Linux/{LinuxApplication,LinuxWindow,LinuxTextField,LinuxSelect,LinuxSlider,LinuxScrollView,LinuxImageView,LinuxView,LinuxActionQueue}.btrc
- src/tests/native/gui/ui2/probes/linux/
- src/tests/native/gui/linux/LinuxEventBoundary.btrc (the E40 reproduction lands with its fix)
- fragment (not held): GUI/btrc.toml SDL symbol fragment

**Must not touch**

- src/stdlib/GUI/Linux/GLibMainContext.btrc
- `src/stdlib/GUI/MacOS/**`
- `src/stdlib/GUI/I*.btrc` and GUI.btrc
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Implement the event, keyed-select, range and two-axis scroll contracts on the SDL provider; D23 scopes GTK4 to UI4-UI8.
2. Make the pump lossless: keep a dequeued event across yields instead of polling past the 4,096 limit. Schedule fairly across input, work, timers, presentation and close, and wake for worker results through btrcSdlPushWake.
3. A close request becomes a decision. Track hidden and minimized exposure, and use effective visibility in hit lookup and focus settlement.
4. Classify presentation failures recoverably instead of throwing after 120 frames, and keep image presentation for closed handles.
5. Bring CX-UIA-11's E40 reproduction in with the fix (D24).

**Acceptance**

- [ ] Under tools/ui/headless-session.sh --x11 and --wayland, both frontends, plain and sanitized: E40 passes 100 bursts at 4,095/4,096/4,097/8,193 events with 0 unexplained losses.
- [ ] On plain builds, the 10-minute load keeps p95 delivery ≤ 100 ms and service gaps ≤ 250 ms, and close starts within 250 ms; sanitized runs check counts and losses only.
- [ ] E01-E04, E29, E35, E39 and E46 pass as on macOS, and LinuxGUIControls still passes.
- [ ] ci.yml is green on the stacked draft PR (run id). The PR-body report follows the protocol.

**Risks**

- If D23 later picks GTK4, the SDL provider remains the shipping one until UI4.
- The 10-minute load test needs stable cloud CPU time.

#### Stage 33: UI3 input, focus and commands, then the tray

<a id="cx-uia-24"></a>

##### CX-UIA-24 · ui-3-contract-input: draft of focus, commands, key identity, pointer/touch and edit transactions

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-3-contract-input`
- **Depends on:** [CL-UIA-13](claude.md#cl-uia-13)
- **Why not now:** Builds on the approved UI2 shapes (CL-UIA-13).
- **Parallel-safe with:** CL-UIA-14, CL-UIA-15, CL-UIA-16, CX-UIA-14, CX-UIA-15, CX-UIA-16, CX-UIA-17

**Owned paths**

- docs/design/ui-contracts/ui3-input.md (new)

**Must not touch**

- `src/stdlib/**`
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Focus on IView and IWindow: query and request, tab order, scopes, restoration and focus-visible (E05).
2. Commands: one shared command owner with enabled and checked state and responder routing. The editor goes first, so playback keys never consume text editing; this replaces LinuxWindow.deliverKey's window-handlers-first order (E06, E23).
3. Keys: separate the physical key, its layout meaning and the command binding. Extend AppKeyCode (27 named values plus unknown) with Page Up/Down, F1-F12 and unknown passthrough (E25).
4. Pointer capture and coordinate/anchor conversion (E27); touch and pen contact identity and cancellation (N09).
5. Editing: IME preedit/commit, explicit range-unit conversion, undo grouping, and fallible clipboard transactions with an admission policy (E07, E13, E14, E44, E45). This lane is the only writer of IView, IWindow and App.btrc.

**Acceptance**

- [ ] The draft has operation ids and fixture outlines for E05-E07, E13, E14, E25, E27, E44 and E45. The PR-body report follows the protocol.

**Risks**

- Touch and pen cannot be exercised before the mobile shells exist; specify them, and qualify later.

<a id="cx-uia-25"></a>

##### CX-UIA-25 · UI3 interface landing branch: approved IView/IWindow/ITextField/App diff, Commands owner and portable fixtures

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-3-contract-input#interfaces`
- **Depends on:** [CL-UIA-19](claude.md#cl-uia-19)
- **Why not now:** Needs the approved UI3 diff (CL-UIA-19).
- **Parallel-safe with:** CL-UIA-17, CL-UIA-18, MAC-UIA-05

> **Review change:** Catalog layout per §7 Q36: PR #21's seed `docs/design/native-ui-catalog.toml` plus sibling shard documents under `docs/design/native-ui-catalog/`, checked by `test_ui0_catalog.py` and `ui_catalog.py` (§10 F3).

**Owned paths**

- src/stdlib/GUI/IView.btrc
- src/stdlib/GUI/IWindow.btrc
- src/stdlib/GUI/ITextField.btrc
- src/stdlib/App/App.btrc
- src/stdlib/GUI/Commands.btrc (new)
- src/tests/native/gui/ui3/ (portable fixtures)
- docs/design/native-ui-catalog/operations/ (new UI3 rows, a shard document)
- docs/design/native-ui-api-inventory.md
- fragment (not held): GUI and App btrc.toml export fragments

**Must not touch**

- `src/stdlib/GUI/MacOS/**` and `src/stdlib/GUI/Linux/**` (the stacked branches)
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Apply ui3-approved.md exactly, and add the Commands owner.
2. Write portable fixtures for E05-E07, E13, E14, E25, E27, E44, E45 and E46 against the interfaces.
3. Add catalog rows and re-freeze the ui-operation denominator.

**Acceptance**

- [ ] test_ui0_catalog.py (and ui_catalog.py's shard check) passes with the new ids, and the btrc-format check passes.
- [ ] The PR-body report names CX-UIA-26 and CX-UIA-27 as the stacked branches.

**Risks**

- The App.btrc enum changes ripple into BTRSmith; add them to the rename table at landing.

<a id="cx-uia-26"></a>

##### CX-UIA-26 · ui-3-macos: AppKit focus, responder-chain commands, IME, undo and keyboard identity

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-3-macos`
- **Depends on:** [CX-UIA-25](#cx-uia-25) (ready)
- **Why not now:** Stacks on the UI3 interface branch (CX-UIA-25).
- **Parallel-safe with:** CX-UIA-27, CL-UIA-17, CL-UIA-18

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/MacOS/{MacOSWindow,MacOSViewInput,MacOSTextField,AppKitEvents,MacOSGPUView}.btrc
- src/tests/native/gui/ui3/probes/macos/
- src/tests/native/gui/NativeKeyboard.btrc (extension)
- src/tests/native/gui/ui3/ImeTrial.btrc (new)
- tools/ui/ime-trial.sh (new; for MAC-UIA-06)
- fragment (not held): GUI/btrc.toml binding fragment

**Must not touch**

- `src/stdlib/GUI/I*.btrc`, App.btrc and Commands.btrc (CX-UIA-25)
- `src/stdlib/GUI/Linux/**`
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Route commands through the NSResponder chain: key equivalents versus the field editor, and menu validation for enabled and checked state.
2. Extend the key-view loop over native controls and the GPU child. Add NSTextInputClient where the GPU child needs text, keep NSUndoManager with the editor, add coordinate conversion, and give clipboard edits outcomes through a pasteboard fault seam.
3. Prepare the ImeTrial fixture and tools/ui/ime-trial.sh for MAC-UIA-06.

**Acceptance**

- [ ] On macos.yml for the stacked draft PR: E05, E06, E13, E25 and E27 pass via in-process event injection; E44 passes 100 cycles with 0 mutations on failure; E46 passes 100 cycles per UI3 entry path. Both frontends, plain and sanitized (run ids).
- [ ] The PR-body report follows the protocol.

**Risks**

- Physical IME cannot be automated on hosted runners; it is MAC-UIA-06.

<a id="cx-uia-27"></a>

##### CX-UIA-27 · ui-3-linux: Linux keyboard behaviour, editor precedence, preedit, undo and clipboard transactions

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 33 (UI3) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-3-linux`
- **Depends on:** [CX-UIA-25](#cx-uia-25) (ready)
- **Why not now:** Stacks on the UI3 interface branch (CX-UIA-25).
- **Parallel-safe with:** CX-UIA-26, CL-UIA-17, CL-UIA-18

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

> **Review change:** Latency thresholds apply to plain builds; sanitized runs on shared 4-core runners check counts and losses only (§10 F19).

**Owned paths**

- src/stdlib/GUI/Linux/{LinuxWindow,LinuxTextField,LinuxButton,LinuxSlider,LinuxScrollView,LinuxSelect}.btrc
- src/stdlib/GUI/Linux/SDL.h
- src/tests/native/gui/ui3/probes/linux/
- src/tests/native/gui/linux/
- fragment (not held): GUI/btrc.toml SDL symbol fragment

**Must not touch**

- src/stdlib/GUI/Linux/GLibMainContext.btrc
- `src/stdlib/GUI/I*.btrc`, App.btrc and Commands.btrc
- `src/stdlib/GUI/MacOS/**`
- `src/compiler/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Route keys editor-first in LinuxWindow.deliverKey. Give LinuxButton, LinuxSlider (whose focus is a no-op today) and LinuxScrollView keyboard and focus behaviour, and let LinuxSelect open from the keyboard.
2. LinuxTextField: undo/redo grouping, and SDL text-editing preedit by flattening SDL_EVENT_TEXT_EDITING in SDL.h. Keep boundaries grapheme-safe.
3. LinuxTextField clipboard: a cut keeps the selection when the clipboard write fails, and paste tells a failed read apart from empty content. Programmatic setText validates UTF-8.
4. Complete the AppKeyCode mapping, separating physical from logical keys.

**Acceptance**

- [ ] Under headless X11 and Wayland, both frontends, plain and sanitized: E13 keyboard-only traversal; E14 undo/redo; E44 at 100 cycles with 0 lost selections; E45 at L-1/L/L+1 for 64 KiB and 1 MiB; E25 key identity; E46 at 100 cycles per UI3 entry path (counts).
- [ ] ci.yml is green (run id). The PR-body report follows the protocol.

**Risks**

- Real IME needs a desktop host; headless results do not count as IME evidence.

<a id="cx-uia-28"></a>

##### CX-UIA-28 · ui-11-tray: typed tray commands, lifecycle qualification and a test StatusNotifierWatcher

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 33 (UI3 + UI11 tray) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-11-tray`
- **Depends on:** [CL-UIA-20](claude.md#cl-uia-20)
- **Why not now:** Needs UI3's typed command owner on main (CL-UIA-20).
- **Parallel-safe with:** MAC-UIA-06

**Owned paths**

- src/stdlib/Tray/ (Tray.btrc, TrayModel.btrc, ITray.btrc, MacOS/, Linux/, README.md)
- src/tests/native/tray/
- src/tests/python/test_native_tray_runtime.py
- tools/ui/sni-watcher-stub.py (new)
- examples/tray/
- fragment (not held): Tray/btrc.toml fragment

**Must not touch**

- `src/stdlib/GUI/**`
- `src/compiler/**`
- `src/language/**`
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Send tray commands as typed in-process actions through UI3's command owner. Shell strings become an explicit opt-in that runs off the UI executor under owned cancellation, keeping semantic delivery p95 ≤ 100 ms beside a slow external command.
2. Drive check-item state from typed state, keeping the shell stateCommand as an opt-in.
3. Add a test-only StatusNotifierWatcher stub on a dbus-run-session bus so the Linux lifecycle runs in CI, and add the selfhost frontend to the Linux tray test, which is reference-only today.
4. Run 100 create/update/activate/close cycles: exactly one command per activation, 0 late actions after close, and 0 leaked D-Bus or status-item registrations. Stop and restart the watcher to show an explicit availability outcome.
5. Update the N56 catalog rows: Windows missing (Stage 35); iOS and Android OS-restricted per platform-adaptations; notifications and badges as separate missing rows; accessibility rows deferred to Stage 34's UI8.

**Acceptance**

- [ ] On Linux in the cloud (dbus-run-session with the stub), test_native_tray_runtime.py passes both frontends, plain and ASan/UBSan, with the 100-cycle counts.
- [ ] On macOS, macos.yml runs the tray lifecycle for both frontends (run id). The PR-body report follows the protocol.

**Risks**

- Moving shell execution off the UI executor touches Process and BackgroundJobs usage; neither file may be edited here.
- examples/tray must keep building under make examples.

<a id="cx-uia-29"></a>

##### CX-UIA-29 · Linux GTK4 provider core: UI2/UI3 window, pump, executor, focus, commands and IME on GTK4 (only if D23 = GTK4)

- **Owner:** Codex · **Group:** UIA · **Stage:** Stage 33 (D23 follow-up) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 16 agent-hours
- **PLAN items:** `ui-2-linux#gtk4`; `ui-3-linux#gtk4`
- **Depends on:** [CL-UIA-10](claude.md#cl-uia-10); [CL-UIA-20](claude.md#cl-uia-20)
- **Why not now:** Runs only if D23 (CL-UIA-10) picks GTK4, after the SDL UI3 landing.

> **Review change:** New (§10 P7). D27 lands UI2/UI3 on SDL before D23, so nothing else would move the Linux core to GTK4.

**Owned paths**

- src/stdlib/GUI/LinuxGTK/ (new provider core; the CX-UIA-14 spike is a reference only)
- src/tests/native/gui/ui2/probes/linux-gtk/ and ui3/probes/linux-gtk/ (new)
- fragment (not held): GUI/btrc.toml provider rows

**Must not touch**

- docs/design/plan-reference.md
- src/stdlib/GUI/Linux/ (the SDL provider stays selectable until CL-UIA-23)
- portable contract files (`I*.btrc`, GUI.btrc, App.btrc)
- `src/compiler/**`

**Steps**

1. Port the window, the lossless event pump (E40), the GLib main-context executor with worker wakeup, close decisions, focus, commands and IME preedit onto GTK4 through the GObject binding (CL-UIA-06…08).
2. Keep the SDL provider selectable; the provider filter switches Linux to GTK4 only in CL-UIA-23.
3. Run the UI2 and UI3 E-cases on GTK4 under X11 and Wayland, both frontends, plain and sanitized.

**Acceptance**

- [ ] UI2 E01–E04, E29, E31, E35, E39, E40, E46 and UI3 E05–E07, E13, E14, E25, E27, E44, E45 pass on GTK4 under tools/ui/headless-session.sh --x11 and --wayland, both frontends, plain and sanitized (latency thresholds on plain builds only).
- [ ] ci.yml is green on the draft PR (run id); the report follows §3.7.

**Risks**

- If D23 picks SDL, Claude records this packet and CL-UIA-23 as not applicable, which satisfies their dependents.

#### Stage 34: UI4–UI9 contract packet and macOS/Linux reference providers

<a id="cx-uib-01"></a>

##### CX-UIB-01 · UI4 controls contract pre-draft with five-platform mapping (D27 planning)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (pre-draft under D27) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-4-contract-controls` (pre-draft)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-08, CX-UIB-09

**Owned paths**

- docs/design/native-ui-contracts/ui4-controls.md (new; header 'Status: draft under D27, not approved')

**Must not touch**

- src/
- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md
- PLAN.md
- AGENTS.md

**Steps**

1. For N11-N22, propose the owners.
   - Extensions: IButton (default/cancel/link roles, toggle state); ITextField (search/secure/read-only, input purpose, E19); ISlider (coherent range/step/units, E34); ISelect (grouped options, type-ahead, E33); IImageView (fit/fill/tint/decorative); IProgressIndicator (determinate); ILabel (semantic alignment, selectable, truncation).
   - New owners for N12 (toggle/radio/switch), N13 (segmented), N16 (multiline), N17 (numeric) and N22 (form/label/error relations).
2. Write signatures in btrc spelling. Event payloads reuse UI2's CallbackScope/ICallbackRegistration pattern. Unsupported operations return typed outcomes, never silent no-ops.
3. For each family, add one mapping row per platform: AppKit; GTK4 and SDL-custom side by side (D23 is open); Win32 common controls; UIKit; Android Views. Name the native default that carries the behavior and the expected adaptation.
4. Specify E15 large text: remeasure, replacing the 20 pt throws at MacOSButton.btrc:74/84/86 and in MacOSSelect.
5. List the portable fixtures the final packet will write under src/tests/native/gui/controls/, and the E-case links for each family.
6. End with the questions for the five platform reviewers.

**Acceptance**

- [ ] Every N11-N22 family has an owner, signatures, a five-platform row and E-case links.
- [ ] Every source path cited exists on main; the PR body lists them.
- [ ] git diff --check and make format-check are clean. Report per protocol.

**Risks**

- It predates the UI2/UI3 contracts (Stages 32-33). CX-UIB-10/11 must re-derive it against the landed interfaces and the five Stage 31 shells.

<a id="cx-uib-02"></a>

##### CX-UIB-02 · UI5 layout and UI8 accessibility contract pre-draft (the IView/IWindow chain)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (pre-draft under D27) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-5-contract-layout` (pre-draft); `ui-8-contract-a11y` (pre-draft)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-08, CX-UIB-09

**Owned paths**

- docs/design/native-ui-contracts/ui5-layout.md (new)
- docs/design/native-ui-contracts/ui8-accessibility.md (new)

**Must not touch**

- src/
- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md

**Steps**

1. UI5, part 1:
   - Constrained measurement. Today IView.fittingWidth()/fittingHeight() take no constraint. Add height-for-width, min/preferred/max, baseline, grow/shrink, and hidden versus collapsed (E26, E39).
   - IStack/IGrid behavior.
   - Leading/trailing alignment that follows reading direction (MacOSLabel.setCentered).
2. UI5, part 2:
   - Viewport, safe-area and keyboard-inset facts on IWindow/App.btrc (E18).
   - Navigation, tabs, split panes and toolbars (N31/N32).
   - Appearance roles, text scaling, contrast, reduced motion and localization keys (N44-N46, E20), after auditing UI/Typography.btrc.
   - A versioned scene-restoration value and codec with a 64 KiB budget (E47), and E46 departure transactions.
3. UI8: semantic attachment on IView (automation id, role, label, relations, actions).
   - It reuses UISemantics (UI/Semantics.btrc:53), with explicit outcomes at 511/512/513 bytes (E28).
   - A virtual-children API for GPU content.
   - Accessible collections, text ranges and timeline ranges.
   - Announcements throttled per transport; modal isolation.
4. Map each bridge: NSAccessibility; GtkAccessible or AT-SPI over D-Bus; UIA providers; UIAccessibility; AccessibilityNodeProvider. Cite the native-interop-ownership.md step each one needs (3, 5, 6, 7 or 8). List the expected interop requests for CL-UIB-09..12.

**Acceptance**

- [ ] Both docs cover every N23-N25, N31, N32, N41-N46 row, with E-case links and the interop request list.
- [ ] git diff --check is clean. Report per protocol.

**Risks**

- The UI3 contract (Stage 33) also edits IView/IWindow/App.btrc. Treat this draft as input to CX-UIB-12/13, not as an API.

<a id="cx-uib-03"></a>

##### CX-UIB-03 · UI6 collections contract pre-draft

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (pre-draft under D27) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-6-contract-collections` (pre-draft)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-08, CX-UIB-09

**Owned paths**

- docs/design/native-ui-contracts/ui6-collections.md (new)

**Must not touch**

- src/
- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md

**Steps**

1. Extract identity, pooling and viewport semantics from UIVirtualGrid and UIVirtualGridViewport (src/stdlib/UI/Element.btrc:526-700), and from BTRSmith's AlbumGrid. Read AlbumGrid only if Codex can read the BTRSmith repository; otherwise mark it pending btrsmith-ui0-callers.
2. Propose new owners:
   - a keyed data source with diff batches;
   - reusable cells with generation checks;
   - a selection model with an anchor and an active item, independent of cells;
   - scroll-to-item and anchors;
   - two axes on IScrollView (today's offset is vertical only);
   - nested-scroll handoff (E41);
   - accessible realization (E21).
3. Encode the budgets: at most 3× viewport plus 2 cells, 0 rebinds when unchanged, and the E36 artwork hooks.
4. Map to NSCollectionView/NSTableView/NSOutlineView; GtkListView/ColumnView/TreeListModel or an SDL recycler; Win32 owner-data ListView/TreeView; UICollectionView diffable data sources; RecyclerView with DiffUtil.
5. Write the 100,000-row stress fixture plan that CX-UIB-28 implements.

**Acceptance**

- [ ] N26-N30 are covered, with E09/E21/E24/E29/E36/E41 links and the budget rules.
- [ ] Report per protocol.

**Risks**

- BTRSmith access is an open question for Codex.

<a id="cx-uib-04"></a>

##### CX-UIB-04 · UI7 services contract pre-draft

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (pre-draft under D27) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-7-contract-services` (pre-draft)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-08, CX-UIB-09

**Owned paths**

- docs/design/native-ui-contracts/ui7-services.md (new)

**Must not touch**

- src/
- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md

**Steps**

1. Replace the synchronous IDirectoryPicker. LinuxDirectoryPicker pumps nested events; MacOSDirectoryPicker.btrc:41 calls runModal. The replacement is a parent-owned asynchronous open/save/folder picker returning scoped, non-path resources (E10). Record the dependency on the Stage 26 P3 scoped-resource contract.
2. Main and context menus bound to UI3 commands; popover and tooltip anchor ownership; typed asynchronous alerts and sheets (E23).
3. Typed clipboard outcomes (E44). The old App clipboard value was removed (btrc-D057). Also drag/drop sessions (E22), open/share/reveal (N39), and document undo and dirty state (E46).
4. Write the mobile-adaptation table, then map each service: NSMenu/NSPopover/beginSheet/NSPasteboard/NSDraggingSession/NSSharingServicePicker; portal FileChooser/OpenURI; HMENU/IFileOpenDialog/OLE/ShellExecute; UIMenu/UIDocumentPicker/UIActivityViewController; PopupMenu/SAF/ClipboardManager/Intent.

**Acceptance**

- [ ] All 8 families N33-N40 are drafted, with adaptations and E10/E17/E22/E23/E44/E46 links.
- [ ] Report per protocol.

**Risks**

- The P3 scoped-resource shape is not designed yet (Stage 26). Mark the picker results provisional.

<a id="cx-uib-05"></a>

##### CX-UIB-05 · UI9 GPU/scheduling and P6 runtime-probe contract pre-drafts

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (pre-draft under D27) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-9-contract-gpu` (pre-draft); `qualification-p6-runtime-probes` (contract pre-draft)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-06, CX-UIB-07, CX-UIB-08, CX-UIB-09

**Owned paths**

- docs/design/native-ui-contracts/ui9-gpu.md (new)
- docs/design/native-ui-contracts/runtime-probes.md (new)

**Must not touch**

- src/
- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md

**Steps**

1. UI9:
   - A display-paced invalidation owner, separate from GUI.postAfter.
   - Exposure and drawable state (E42). LinuxWindow's needsFrame/isVisible ignore minimize and hide.
   - Presentation-failure classes, with at most 10 retries per second and an explicit failure within 5 s (E43). LinuxWindow throws after 120 unavailable frames.
   - Subtree capture with frame identity and layer validation, and no UI-thread wait (E38). Linux GUIProvider.capture ignores layers and polls for up to 5 s.
   - Byte-accounted artwork admission and trim (E36), replacing LinuxPainter.evictImages.
   - A shaped custom-text owner (E37), replacing LinuxFonts' scalar walk.
2. Map the clocks: CVDisplayLink/CADisplayLink, the GTK frame clock or SDL, the DXGI waitable swapchain, iOS CADisplayLink, Choreographer.
3. Probes: one counter and trace contract covering:
   - launch to interactive;
   - input to presentation, with debounce reported separately;
   - frame p95/p99 and longest stall;
   - working set with GPU and native accounting;
   - handle and registration counters;
   - artwork residency and cell/rebind counts;
   - idle passes and CPU;
   - realtime callback duration, and xrun/route counters;
   - close/drain time.

   Nothing allocates or blocks in a callback. Results export as btrc.qualification.ledger/1 measurement rows.

**Acceptance**

- [ ] E12/E32/E36/E37/E38/E42/E43 are specified with their numeric limits.
- [ ] The probe metric list matches platform-parity.md's P6 runtime rows.
- [ ] Report per protocol.

**Risks**

- The realtime-proof form for probe counters may need analyzer support. Note it for CL-UIB-13.

<a id="cx-uib-06"></a>

##### CX-UIB-06 · Spike: keyed collection data model in pure btrc (never merged)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (spike under D27) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `ui-6-contract-collections` (spike input)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-07, CX-UIB-08, CX-UIB-09

**Owned paths**

- branch codex/cx-uib-06-spike (the prototype: pushed, no PR, never merged; §3.2)
- docs/design/native-ui-contracts/spikes/collections-data-model.md (new; the only file that lands: the findings PR on codex/cx-uib-06 carries only this file, so it runs the docs tier)

**Must not touch**

- src/stdlib/
- src/compiler/
- src/tests/ (on any merged commit)

**Steps**

1. On the spike branch codex/cx-uib-06-spike, prototype against a synthetic 100,000-record source:
   - a keyed data source with diff batches;
   - a selection model (anchor and active item);
   - a cell pool that binds by key, with generation checks.
2. Simulate sort, filter and delete during scrolling. Count binds and live cells against the 3× viewport plus 2 rule and the 0-rebind rule. Run through both frontends under ASan/UBSan.
3. File any parity or compiler defect as REQUEST(CL-UIB-13) with a repro.
4. Write the findings note: the shapes that work in btrc today (generics, interfaces, ARC cycles), their costs, recommendations for CX-UIB-14, and the spike branch's head SHA. Open the findings PR from codex/cx-uib-06 with only the note; the spike branch gets no PR.

**Acceptance**

- [ ] The prototype's run command and its bind and cell counts appear in the note, for both frontends with sanitizers.
- [ ] Only the findings note lands.

**Risks**

- Prototype code must not leak into a merge. The integrator skips spike branches.

<a id="cx-uib-07"></a>

##### CX-UIB-07 · Spike: accessibility bridge feasibility, AT-SPI on Linux and NSAccessibility virtual children on a macOS runner (never merged)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (spike under D27) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-8-contract-a11y` (spike input)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-08, CX-UIB-09

**Owned paths**

- branch codex/cx-uib-07-spike (the prototype: pushed, no PR, never merged; §3.2)
- docs/design/native-ui-contracts/spikes/accessibility-bridges.md (new; the findings PR on codex/cx-uib-07 carries only this file, so it runs the docs tier)

**Must not touch**

- src/stdlib/ (on any merged commit)
- src/compiler/
- .github/workflows/

**Steps**

1. Linux: export a three-node AT-SPI tree (window, button, one virtual child) over D-Bus from a btrc process, reusing the D-Bus binding pattern in src/stdlib/Tray/Linux. Run under Xvfb with at-spi2-core installed in the spike container, and dump the tree with gdbus or pyatspi.
2. macOS: on codex/cx-uib-07-spike, attach NSAccessibilityElement virtual children to a MacOSGPUView fixture and read them back in-process, from a `test_native_ui_*.py` module so that `make test-native-gui` collects it. Run it with one `gh workflow run macos.yml --ref codex/cx-uib-07-spike -f focus=native-gui` dispatch (§3.2 policy item 8); without `actions:write`, ask Claude in the findings PR to dispatch it.
3. Record two facts: whether hosted runners grant AX/TCC trust, and which actions need Objective-C subclass overrides (I1 step 6).
4. File the interop gaps for CL-UIB-09 and CL-UIB-12, with repros, in the findings PR on codex/cx-uib-07, which carries only the note.

**Acceptance**

- [ ] The findings note includes the AT-SPI dump, the macOS run id and an explicit yes/no on hosted-runner AX trust.
- [ ] The gap list is filed.

**Risks**

- at-spi is not in the devcontainer until Stage 30.
- Objective-C subclassing is unavailable until Stage 29, so the macOS half may only read properties.

<a id="cx-uib-08"></a>

##### CX-UIB-08 · 100,000-record toolkit fixture generator (btrc data half of the fixture pair)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (D27 (c): dependencies met) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 4 agent-hours
- **PLAN items:** `qualification-catalog-fixtures` (btrc 100k-row generator); `ui-6-stress-fixture` (data half)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-09

**Owned paths**

- src/tests/native/gui/collections/CollectionRecords.btrc (new; src/tests/native is not a corpus directory)
- src/tests/native/gui/collections/records.sha256 (new)
- src/tests/python/test_native_ui_collection_records.py (new)

**Must not touch**

- src/tests/fixtures/ (it is a corpus directory)
- src/stdlib/
- src/compiler/

**Steps**

1. Write a deterministic generator for 100,000 stable records with no media files. Records carry a stable key, varied title lengths including RTL and emoji strings, sort keys, filter facets, and a deterministic delete/insert schedule.
2. Emit a canonical serialization and its sha256, and freeze it in records.sha256.
3. Add a pytest that compiles the generator through both frontends, checks the hash, and records generator time and output size as ledger measurement rows.

**Acceptance**

- [ ] python -m pytest src/tests/python/test_native_ui_collection_records.py passes on Linux and in the macos.yml unit shard, with the same hash on both: two hosts and two frontends.
- [ ] make lint format-check generated-check are clean. Report per protocol.

**Risks**

- Floating-point formatting can differ between hosts. Serialize integers and strings only.

<a id="cx-uib-09"></a>

##### CX-UIB-09 · BTRSmith 10,000-song / 1,000-album license-clean acceptance catalog generator

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (D27 (c): dependencies met) · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-catalog-fixtures` (BTRSmith media/catalog/SQLite half)
- **Depends on:** none
- **Parallel-safe with:** CX-UIB-01, CX-UIB-02, CX-UIB-03, CX-UIB-04, CX-UIB-05, CX-UIB-06, CX-UIB-07, CX-UIB-08

> **Review change:** Commit naming corrected: hand-written integrator data goes in the `fragment:` commit, which Claude re-applies; regenerated outputs go in `derived:`, which Claude drops (§3.5, §10 C3).

**Owned paths**

- btrsmith: packages/psarc/tests/MediaFixtureBuilder.btrc
- btrsmith: make/AcceptanceCatalog.mk (new; its include line in the Makefile goes in a `fragment:` commit)
- btrsmith: tests/fixtures/acceptance-catalog/ (manifests only; media stays under ~/.cache/btrsmith or build/)

**Must not touch**

- btrsmith: src/application/runtime/{ApplicationSession,ApplicationView,GUIApplication}.btrc
- btrsmith: flake.lock
- btrc repository

**Steps**

1. Extend MediaFixtureBuilder to emit:
   - varied artists, years and artwork sizes (256 and 512 thumbnails, plus oversized sources);
   - corrupt and unreadable entries;
   - a pre-indexed SQLite snapshot;
   - a raw import variant.

   The output is content-hashed and kept out of git.
2. Add AcceptanceCatalog.mk targets for building the catalog and checking its hashes. Make the catalog importable through the picker/import path for mobile.
3. Build twice on Linux through both frontends and compare hashes. Record generator time and output size.

**Acceptance**

- [ ] Two Linux builds through both frontends give identical content hashes.
- [ ] The macOS hash and the 10,000-song load are produced by MAC-UIB-03.
- [ ] Report per protocol, against the BTRSmith hub branch.

**Risks**

- It needs Codex access to the private BTRSmith repository (open question). If Codex has none, Claude takes this packet.
- The BTRSmith Make graph is a hotspot.

<a id="cx-uib-10"></a>

##### CX-UIB-10 · UI4 contract, drafter A: buttons and links, toggles and radios, segmented control, images, progress and meters

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-4-contract-controls` (N11, N12, N13, N20, N21)
- **Depends on:** PLAN:ui-3-contract-input (Stage 33 atomic landing with ui-3-macos/ui-3-linux) → [CL-UIA-20](claude.md#cl-uia-20); PLAN:ui-1-feasibility-review (five shells, D23) → [CL-UIA-10](claude.md#cl-uia-10), [CX-UIA-15](#cx-uia-15), [CX-UIA-16](#cx-uia-16), [CX-UIA-17](#cx-uia-17); [CX-UIB-01](#cx-uib-01); [CL-UIA-22](claude.md#cl-uia-22)
- **Why not now:** UI3's contract and provider landing (Stage 33), and Stages 30-32 before it, have not started; under D1 bucket 4 has not begun.
- **Parallel-safe with:** CX-UIB-11, CX-UIB-12, CX-UIB-14, CX-UIB-15, CX-UIB-16

> **Review change:** Waits for `CL-UIA-22`: the toolkit decision and the UI2/UI3 re-check on the real shells (§10 P6).

**Owned paths**

- src/stdlib/GUI/IButton.btrc
- src/stdlib/GUI/IImageView.btrc
- src/stdlib/GUI/IProgressIndicator.btrc
- src/stdlib/GUI/ILevelIndicator.btrc
- src/stdlib/GUI/IToggle.btrc (new)
- src/stdlib/GUI/IRadioGroup.btrc (new)
- src/stdlib/GUI/ISegmentedControl.btrc (new)
- src/tests/native/gui/controls/{ButtonRoles,Toggles,RadioGroups,SegmentedControls,ImagePresentation,ProgressStates}.btrc (new portable fixtures)

**Must not touch**

- src/compiler/, src/language/, tools/compiler_codegen/, src/runtime/c/ (compiler and specs)
- src/stdlib/GUI/{GUI,IApplication,IView,IWindow}.btrc and src/stdlib/App/App.btrc (owned by CX-UIB-12/13/17)
- src/stdlib/GUI/{MacOS,Linux,Windows,IOS,Android}/

**Steps**

1. Re-derive CX-UIB-01's part A against the landed UI2/UI3 interfaces and the five Stage 31 shells.
2. Write:
   - N11 default/cancel/link roles and toggle state on IButton;
   - N12 IToggle (bool and tri-state, checkbox/switch presentation) and IRadioGroup (stable item ids);
   - N13 ISegmentedControl (exclusive/multiple selection, overflow);
   - N20 fit/fill/alignment/tint/decorative state on IImageView;
   - N21 determinate fraction and status text on IProgressIndicator, and range/threshold semantics on ILevelIndicator.
3. Events use UI2's scoped registrations. Setters emit zero user actions.
4. Write the portable fixtures. They assert enabled/disabled, empty/invalid, keyboard and callback lifetime, and must compile against the reconciler's typed-unsupported provider stubs.
5. Send factory and doc entries to CX-UIB-17. Do not edit GUI.btrc.

**Acceptance**

- [ ] The interfaces and fixtures compile through both frontends on Linux and in the macos.yml unit shard, with zero analyzer warnings.
- [ ] test_naming_convention_contract.py passes.
- [ ] Report per protocol; the packet is folded into CX-UIB-17 for review.

**Risks**

- Name collisions with UI2/UI3 additions. Rebase on the Stage 33 landing first.

<a id="cx-uib-11"></a>

##### CX-UIB-11 · UI4 contract, drafter B: labels, text/search/password fields, multiline editor, numeric entry, ranges and selects

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-4-contract-controls` (N14, N15, N16, N17, N18, N19)
- **Depends on:** PLAN:ui-3-contract-input (Stage 33 landing) → [CL-UIA-20](claude.md#cl-uia-20); [CX-UIB-01](#cx-uib-01)
- **Why not now:** Stage 33's UI3 landing has not happened (bucket 4 has not started).
- **Parallel-safe with:** CX-UIB-10, CX-UIB-12, CX-UIB-14, CX-UIB-15, CX-UIB-16

**Owned paths**

- src/stdlib/GUI/ILabel.btrc
- src/stdlib/GUI/ITextField.btrc
- src/stdlib/GUI/ISlider.btrc
- src/stdlib/GUI/ISelect.btrc
- src/stdlib/GUI/ITextEditor.btrc (new)
- src/stdlib/GUI/INumericField.btrc (new)
- src/tests/native/gui/controls/{LabelText,TextFieldModes,SecureText,TextEditor,NumericEntry,RangeValues,KeyedSelectLarge,LargeTextControls}.btrc (new)

**Must not touch**

- src/compiler/, src/language/ (compiler and specs)
- src/stdlib/GUI/{GUI,IApplication,IView,IWindow}.btrc
- src/stdlib/GUI/{MacOS,Linux,Windows,IOS,Android}/

**Steps**

1. N14 ILabel: semantic leading/trailing alignment (which UI5 consumes), selectable text, truncation, and the associated-control link.
2. N15 ITextField: search/clear/submit, secure and read-only modes, and input purpose. Secure contents never enter diagnostics or semantic values (E19). Admission limits follow E45 (64 KiB).
3. N16 ITextEditor: wrapping, native undo, and a 1 MiB fixture limit (E45). N17 INumericField: locale parsing, invalid drafts preserved, commit.
4. N18 ISlider: coherent range/step/value updates, degenerate ranges, and exact values around 2^53 (E34). N19 ISelect: grouped and disabled options, type-ahead, and 0/1/100/10,000 options (E33).
5. E15: large text remeasures with no throw and no clamp. Fixtures cover L-1, L and L+1 bytes, and 999/1,000/1,001 intervals.

**Acceptance**

- [ ] Interfaces and fixtures compile through both frontends on Linux and macOS (macos.yml) with zero warnings.
- [ ] The E15/E19/E33/E34 assertions are present in the fixtures. Report per protocol.

**Risks**

- UI2's stable-key ISelect events (Stage 32) must be extended, not duplicated.

<a id="cx-uib-12"></a>

##### CX-UIB-12 · IView/IWindow chain, part 1: UI5 layout, viewport, navigation, appearance and scene-restoration contract

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet; the single IView/IWindow/App.btrc writer) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-5-contract-layout`
- **Depends on:** PLAN:ui-3-contract-input (Stage 33 landing) → [CL-UIA-20](claude.md#cl-uia-20); [CX-UIB-02](#cx-uib-02); [CX-UIB-11](#cx-uib-11) (ready; ILabel alignment)
- **Why not now:** Stage 33's UI3 landing has not happened; the UI3 writer releases IView/IWindow/App.btrc only then.
- **Parallel-safe with:** CX-UIB-10, CX-UIB-14, CX-UIB-15, CX-UIB-16

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/IView.btrc
- src/stdlib/GUI/IWindow.btrc
- src/stdlib/GUI/IStack.btrc
- src/stdlib/GUI/IGrid.btrc
- src/stdlib/GUI/IContainer.btrc
- src/stdlib/GUI/IPanel.btrc
- src/stdlib/App/App.btrc
- src/stdlib/GUI/{INavigationStack,ITabView,ISplitView,IToolbar,SceneRestoration,Appearance}.btrc (new)
- src/stdlib/UI/Typography.btrc (audited and reused; edits only if needed)
- src/tests/native/gui/layout/ (new portable fixtures)

**Must not touch**

- src/compiler/ (compiler)
- src/stdlib/GUI/{GUI,IApplication}.btrc (CX-UIB-17)
- provider directories

**Steps**

1. IView: constrained measurement (height-for-width, min/preferred/max, baseline, grow/shrink), hidden versus collapsed, and effective interaction state (E26, E39). Keep isVisible() as the view's own flag.
2. IStack/IGrid: grow/shrink, baselines and spanning. IWindow and App.btrc: viewport, safe area and keyboard inset (E18), and display scale with coordinate conversion (E27).
3. New navigation stack, tab, split and toolbar owners (N31/N32), with E46 departure transactions. Appearance roles; text-scale, contrast and reduced-motion observation (N44-N46, E20).
4. SceneRestoration: a versioned descriptor and codec with a 64 KiB budget, validated before any view is created (E47).
5. Write the layout fixtures: a 320/480/1024 × 100/150/200% matrix, in LTR and RTL.

**Acceptance**

- [ ] Compiles through both frontends on Linux and macos.yml, with zero warnings.
- [ ] The fixture matrix asserts 'no clipped essential action' and '100 resize/theme cycles keep focus and anchor'. Report per protocol.

**Risks**

- IView fan-out: every provider must implement the new measurement. The reconciler's stubs must keep the Windows/iOS/Android shells compiling.

<a id="cx-uib-13"></a>

##### CX-UIB-13 · IView/IWindow chain, part 2: UI8 accessibility contract, plus the IWindow/App.btrc parts that UI7 and UI9 request

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet; the single IView/IWindow/App.btrc writer) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-8-contract-a11y`
- **Depends on:** [CX-UIB-12](#cx-uib-12) (ready); [CX-UIB-15](#cx-uib-15) (ready; IWindow presentation and clipboard requests); [CX-UIB-16](#cx-uib-16) (ready; IWindow exposure requests)
- **Why not now:** It follows CX-UIB-12, which waits for Stage 33.
- **Parallel-safe with:** CX-UIB-10, CX-UIB-11, CX-UIB-14

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/IView.btrc
- src/stdlib/GUI/IWindow.btrc
- src/stdlib/App/App.btrc
- src/stdlib/UI/Semantics.btrc
- src/stdlib/GUI/{AccessibilityNode,Announcement}.btrc (new)
- src/tests/native/gui/accessibility/ (new portable fixtures)

**Must not touch**

- src/compiler/ (compiler)
- src/stdlib/GUI/IGPUView.btrc (CX-UIB-16 adds the one-line adoption)
- provider directories

**Steps**

1. IView: stable automation id and semantic attachment (role, label, relations, actions), reusing UISemantics. Replace UISemantics' silent 512-byte limit with explicit outcomes at 511/512/513 bytes (E28).
2. AccessibilityNode: virtual-child identity, bounds and actions for GPU content; collection, text-range and timeline-range accessibles (E11, E21).
3. Announcements throttled per transport, never per frame; modal isolation.
4. Fold in the IWindow presentation/exposure members and the App.btrc clipboard outcome that CX-UIB-15/16 specified, so IView/IWindow/App.btrc each have one writer.
5. Write the accessibility fixtures (E11/E21/E28) and the keyboard-only journey fixture.

**Acceptance**

- [ ] Compiles through both frontends on Linux and macos.yml with zero warnings.
- [ ] The fixtures assert '511/512/513 never truncates inside a character'. Report per protocol.

**Risks**

- The bridge shapes depend on interop that lands in Stages 27, 29 and 31. CL-UIB-02's parity reviewer must check that nothing needs a compiler change that has not been filed.

<a id="cx-uib-14"></a>

##### CX-UIB-14 · UI6 collections contract: keyed data source, selection model, cells and two-axis scrolling

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-6-contract-collections`
- **Depends on:** PLAN:ui-3-contract-input (Stage 33 landing) → [CL-UIA-20](claude.md#cl-uia-20); [CX-UIB-03](#cx-uib-03); [CX-UIB-06](#cx-uib-06)
- **Why not now:** Stage 33's UI3 landing has not happened.
- **Parallel-safe with:** CX-UIB-10, CX-UIB-11, CX-UIB-12, CX-UIB-15, CX-UIB-16

**Owned paths**

- src/stdlib/GUI/IScrollView.btrc
- src/stdlib/GUI/{ICollectionView,ICollectionDataSource,ISelectionModel,ITableView,ITreeView}.btrc (new)
- src/tests/native/gui/collections/{KeyedDiff,SelectionAnchor,ScrollAnchor,NestedScroll}.btrc (new)

**Must not touch**

- src/tests/native/gui/collections/CollectionRecords.btrc (CX-UIB-08)
- src/tests/native/gui/collections/CollectionStress.btrc (CX-UIB-28)
- src/stdlib/GUI/IGrid.btrc (it stays a fixed-cell container)
- src/compiler/

**Steps**

1. Define the keyed data source with diff batches and a defined failure outcome (E29); reusable cells with generation checks (E24); a selection model independent of cells, stable through sort, filter and delete (E09); scroll-to-item and anchors.
2. Give IScrollView two-axis positions, units and phase, and nested-scroll handoff (E41).
3. Accessible realization of unrealized items (E21) and E36 artwork hooks.
4. Encode the budget assertions as fixture checks: at most 3× viewport plus 2 cells, and 0 rebinds when unchanged.

**Acceptance**

- [ ] Compiles through both frontends on Linux and macos.yml.
- [ ] The budget assertions fail on a deliberately unbounded mock owner in a unit test. Report per protocol.

**Risks**

- Generic data-source interfaces can hit compiler limits. File REQUEST(CL-UIB-13) early.

<a id="cx-uib-15"></a>

##### CX-UIB-15 · UI7 services contract: menus, popovers, async dialogs and pickers, clipboard, drag/drop, open/share, document state

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-7-contract-services`
- **Depends on:** PLAN:ui-3-contract-input (Stage 33 landing) → [CL-UIA-20](claude.md#cl-uia-20); PLAN:platforms-p3-fs-mobile (Stage 26 scoped-resource contract) → [CL-P2-01](claude.md#cl-p2-01); [CX-UIB-04](#cx-uib-04)
- **Why not now:** Stage 33's UI3 landing and the Stage 26 P3 scoped-resource contract have not landed.
- **Parallel-safe with:** CX-UIB-10, CX-UIB-11, CX-UIB-12, CX-UIB-14, CX-UIB-16

**Owned paths**

- src/stdlib/GUI/IDirectoryPicker.btrc (becomes a compatibility shim over the async picker)
- src/stdlib/GUI/{IFilePicker,IMenu,IPopover,IDialog,IClipboard,ITransferSession,IShareService,IDocumentState}.btrc (new)
- src/tests/native/gui/services/ (new portable fixtures)

**Must not touch**

- src/stdlib/GUI/IWindow.btrc and src/stdlib/App/App.btrc (send the needed members to CX-UIB-13)
- src/compiler/

**Steps**

1. Asynchronous parent-owned pickers returning scoped resources; cancel, deny, revoke and parent-destroy each resolve exactly once (E10, E17).
2. Menus and context menus bound to UI3 commands, with availability rechecked when invoked (E23). Popovers and tooltips with anchor ownership.
3. A typed clipboard with denied/unavailable/empty/error outcomes (E44). Drag/drop sessions (E22). Open/share/reveal (N39). Document undo and dirty state for E46 service paths.
4. Write the mobile-adaptation rows, and the fixtures for 100 cancel/parent-close cycles.

**Acceptance**

- [ ] Compiles through both frontends on Linux and macos.yml.
- [ ] 8 of 8 families have owners and fixtures. Report per protocol.

**Risks**

- If P3 slips, the picker result type stays provisional and the approval records that.

<a id="cx-uib-16"></a>

##### CX-UIB-16 · UI9 GPU contract: display clock, exposure, presentation recovery, subtree capture, artwork budget and shaped text

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-9-contract-gpu`
- **Depends on:** PLAN:ui-3-contract-input (Stage 33 landing) → [CL-UIA-20](claude.md#cl-uia-20); [CX-UIB-05](#cx-uib-05)
- **Why not now:** Stage 33's UI3 landing has not happened.
- **Parallel-safe with:** CX-UIB-10, CX-UIB-11, CX-UIB-12, CX-UIB-14, CX-UIB-15

**Owned paths**

- src/stdlib/GUI/IGPUView.btrc
- src/stdlib/GUI/GUICaptureLayer.btrc
- src/stdlib/GUI/TextRun.btrc
- src/stdlib/GUI/{IDisplayClock,ArtworkBudget,PresentationOutcome}.btrc (new)
- src/tests/native/gui/gpu/ (new portable fixtures)

**Must not touch**

- src/stdlib/GUI/IWindow.btrc (exposure members go to CX-UIB-13)
- src/stdlib/GUI/GUI.btrc (GUI.capture semantics go to CX-UIB-17)
- src/stdlib/GPU/ (unless a request is filed)
- src/compiler/

**Steps**

1. IDisplayClock: display-paced invalidation, separate from GUI.postAfter. Static idle requests no passes.
2. PresentationOutcome: transient, device-loss and terminal classes; at most 10 retries per second; explicit failure within 5 s; healthy windows keep working (E43). Exposure and drawable states go to CX-UIB-13 (E42).
3. Capture: subtree scope, frame identity, and validation of foreign, duplicate, detached and wrongly sized layers; no UI-thread wait (E38).
4. ArtworkBudget: byte reservation before allocation, at most 2 decode jobs, and trim within 1 s with no repaint (E36). TextRun: shaped runs, cluster mapping and ink bounds (E37). IGPUView adopts AccessibilityNode, as CX-UIB-13 specifies.

**Acceptance**

- [ ] Compiles through both frontends on Linux and macos.yml.
- [ ] The numeric limits are encoded as fixture assertions. Report per protocol.

**Risks**

- GPU fixtures skip on hosted runners that have no real adapter. Their evidence comes from MAC-UIB-03 and the Linux lavapipe runs.

<a id="cx-uib-17"></a>

##### CX-UIB-17 · Contract packet reconciler: factories, stubs, portable drivers, docs and the single review packet

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 step 0 (contract packet assembly) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-4-contract-controls` (reconciliation, N22 forms); `native-ui-api-inventory.md` / native-ui-parity.md contract sections
- **Depends on:** [CX-UIB-10](#cx-uib-10) (ready); [CX-UIB-11](#cx-uib-11) (ready); [CX-UIB-12](#cx-uib-12) (ready); [CX-UIB-13](#cx-uib-13) (ready); [CX-UIB-14](#cx-uib-14) (ready); [CX-UIB-15](#cx-uib-15) (ready); [CX-UIB-16](#cx-uib-16) (ready)
- **Why not now:** It needs all the drafters, which wait for Stage 33.

> **Writer note:** Claude is the D6(c) contract owner; this packet assembles the **draft** that Claude approves in `CL-UIB-02` (§2.1, §9 item 8). The analyst's summary calling Codex the "single UI contract owner" is read as "the single designated writer chain".

> **Review change:** Commit naming corrected: hand-written integrator data goes in the `fragment:` commit, which Claude re-applies; regenerated outputs go in `derived:`, which Claude drops (§3.5, §10 C3).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/GUI.btrc
- src/stdlib/GUI/IApplication.btrc
- src/stdlib/GUI/IForm.btrc (new, N22)
- src/stdlib/GUI/README.md
- src/stdlib/GUI/{MacOS,Linux}/GUIProvider.btrc and their Application owners (typed-unsupported stubs only)
- src/tests/python/test_native_ui_{controls,layout,services,accessibility,gpu}.py (new portable drivers; frozen at approval)
- src/tests/native/gui/controls/FormValidation.btrc (new)
- `docs/design/native-ui-contracts/*.md` (promoted from draft)
- docs/design/native-ui-api-inventory.md (rows for new owners and the change log)
- docs/design/native-ui-parity.md (section 3 contracts and E-case cross-links)
- the UI0 catalog's new operation rows (Stage 30 layout)

**Must not touch**

- src/compiler/ (compiler)
- tools/qualification/denominators.toml (CL-UIB-08 re-freezes it)
- src/stdlib/GUI/{Windows,IOS,Android}/ while a Stage 35 track owns it (request a stub-only commit from that owner)

**Steps**

1. Add GUI and IApplication factories for every new owner, and N22 IForm (label/control/error relations, dirty drafts, first-error focus, save/cancel).
2. Add typed-unsupported stubs to the macOS and Linux providers. For the Windows/iOS/Android shells, add them directly if no track is in flight; otherwise request a stub-only commit from the track's owner.
3. Write the portable pytest drivers, which pick the host's provider and are parametrized frontend × sanitized. Write the GUI/btrc.toml exports as the `fragment:` commit, followed by `derived: regenerate` (btrc.lock, LSP catalog).
4. Update the API inventory, the parity doc's section 3 and the contract docs. Assemble one review packet: the interface diff, the fixtures and the five-platform maps.

**Acceptance**

- [ ] Every portable driver's -k contract_compiles cases pass through both frontends on Linux and in the macos.yml unit shard, with zero warnings. windows.yml still builds the shell.
- [ ] make lint format-check are clean. Report per protocol; this is the input to CL-UIB-02.

**Risks**

- Stub churn across five providers. Keep the stubs mechanical and listed in the PR body.

<a id="cx-uib-18"></a>

##### CX-UIB-18 · ui-4-macos part A: AppKit buttons and roles, switch/checkbox/radio, segmented control, images, progress and level, with their UI8 rows

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L1 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-4-macos` (N11, N12, N13, N20, N21, N22)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); [CX-UIB-22](#cx-uib-22) (ready; MacOSView semantic attachment; rebase on it)
- **Why not now:** The contract packet is not approved; Stages 30-33 have not started.
- **Parallel-safe with:** CX-UIB-19, CX-UIB-20, CX-UIB-21, CX-UIB-23

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSButton.btrc
- src/stdlib/GUI/MacOS/MacOSImageView.btrc
- src/stdlib/GUI/MacOS/MacOSImageHandle.btrc
- src/stdlib/GUI/MacOS/MacOSProgressIndicator.btrc
- src/stdlib/GUI/MacOS/MacOSLevelIndicator.btrc
- src/stdlib/GUI/MacOS/{MacOSToggle,MacOSRadioGroup,MacOSSegmentedControl,MacOSForm}.btrc (new)
- `src/tests/native/gui/controls/macos/{Button,Toggle,Radio,Segmented,Image,Progress,Form}*.btrc`
- the UI0 catalog shard for macOS UI4 part A

**Must not touch**

- `src/stdlib/GUI/I*.btrc` and GUI.btrc (approved contract)
- src/tests/python/test_native_ui_controls.py (frozen driver)
- src/stdlib/GUI/MacOS/MacOSView.btrc (CX-UIB-22)
- src/compiler/

**Steps**

1. Implement over AppKit: NSButton switch, checkbox and radio types; NSSwitch; NSSegmentedControl; NSImageView scaling, tint and decorative state; determinate NSProgressIndicator; NSLevelIndicator thresholds.
2. N22 forms: label/control/error relations and first-error focus.
3. Remove the 20 pt bordered-button throws (MacOSButton.btrc:74/84/86). Remeasure natively under large text, with no clamp (E15).
4. Apply UI8 attachment for every new control: AX role, label, state and actions; keyboard activation and focus ring.
5. Write catalog rows for each family and E-case, for each frontend.

**Acceptance**

- [ ] In the macos.yml unit shard, test_native_ui_controls.py (part A families) and test_native_gui_appkit.py pass, both frontends × sanitized.
- [ ] The E15 fixture goes beyond 20 pt with no exception or clipping.
- [ ] AX attribute assertions pass in-process, or are rule-skipped to MAC-UIB-03. Report per protocol.

**Risks**

- VoiceOver journeys are an owner step (MAC-UIB-01).

<a id="cx-uib-19"></a>

##### CX-UIB-19 · ui-4-macos part B: labels, search/secure fields, NSTextView editor, stepper numeric field, ranges and selects

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L1 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-4-macos` (N14, N15, N16, N17, N18, N19)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); [CX-UIB-22](#cx-uib-22) (ready)
- **Why not now:** The contract packet is not approved.
- **Parallel-safe with:** CX-UIB-18, CX-UIB-20, CX-UIB-21, CX-UIB-23

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSLabel.btrc
- src/stdlib/GUI/MacOS/MacOSTextField.btrc
- src/stdlib/GUI/MacOS/AppKitText.btrc
- src/stdlib/GUI/MacOS/MacOSSlider.btrc
- src/stdlib/GUI/MacOS/MacOSSelect.btrc
- src/stdlib/GUI/MacOS/{MacOSTextEditor,MacOSNumericField}.btrc (new)
- src/tests/native/gui/SliderPresentation.m (the knob defect reproduction)
- `src/tests/native/gui/controls/macos/{Label,TextMode,SecureText,TextEditor,Numeric,Range,KeyedSelect}*.btrc`

**Must not touch**

- approved contract files
- src/stdlib/GUI/MacOS/MacOSButton.btrc (CX-UIB-18)
- src/compiler/

**Steps**

1. NSSearchField and NSSecureTextField modes, read-only, and input purpose. Secure text never appears in logs or semantics (E19).
2. NSTextView inside NSScrollView with native undo and a 1 MiB fixture limit (E45). An NSStepper with an NSNumberFormatter field keeps invalid drafts (N17).
3. MacOSSlider: coherent range/step updates and exact 64-bit values (E34). Fix the knob presentation defect that SliderPresentation.m reproduces, for BTRSmith's speed slider.
4. MacOSSelect: grouped options and type-ahead. Remove the 20 pt throw at MacOSSelect.btrc:110 (E15). 10,000 options stay reachable by keyboard (E33).
5. Add UI8 rows for each control, and write catalog rows.

**Acceptance**

- [ ] The part B families and E15/E19/E33/E34 pass in the macos.yml unit shard, both frontends × sanitized.
- [ ] test_native_gui_appkit.py and the MacOSTextFieldConformance tests stay green. Report per protocol.

**Risks**

- IME and undo continuity across model refresh (E07/E14) must not regress UI3.

<a id="cx-uib-20"></a>

##### CX-UIB-20 · ui-4-linux part A: buttons, toggles, radios, segmented control, images and symbols, progress, forms (D23 route)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L1 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-4-linux` (N11, N12, N13, N20, N21, N22)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); PLAN:ui-1-feasibility-review (D23 toolkit) → [CL-UIA-10](claude.md#cl-uia-10); [CX-UIB-23](#cx-uib-23) (ready); [CL-UIA-23](claude.md#cl-uia-23) (only if D23 = GTK4; otherwise recorded not applicable)
- **Why not now:** The contract is not approved and the D23 toolkit is not chosen (Stage 31).
- **Parallel-safe with:** CX-UIB-18, CX-UIB-19, CX-UIB-21, CX-UIB-22

> **Review change:** If D23 picks GTK4, waits for the GTK4 core landing `CL-UIA-23` (§10 P7).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxButton.btrc
- src/stdlib/GUI/Linux/LinuxImageView.btrc
- src/stdlib/GUI/Linux/LinuxIndicators.btrc
- src/stdlib/GUI/Linux/LinuxSymbols.btrc
- src/stdlib/GUI/Linux/{LinuxToggle,LinuxRadioGroup,LinuxSegmentedControl,LinuxForm}.btrc (new)
- `src/tests/native/gui/controls/linux/{Button,Toggle,Radio,Segmented,Image,Progress,Form}*.btrc`

**Must not touch**

- approved contract files
- src/stdlib/GUI/Linux/LinuxView.btrc and LinuxWindow.btrc (CX-UIB-23 / later landings)
- src/compiler/

**Steps**

1. On the GTK route: GtkCheckButton, GtkSwitch, grouped GtkToggleButton, GtkPicture/GtkImage, GtkProgressBar, GtkLevelBar.
2. On the SDL route: painted owners with full keyboard behavior. Today LinuxButton.key returns false; add default activation and a focus ring.
3. LinuxSymbols: semantic icon ids, including tuningfork and quote.bubble, which are missing today.
4. Add UI8 rows through CX-UIB-23's bridge, and write catalog rows.

**Acceptance**

- [ ] BTRC_TEST_BTRCC=$BTRCC tools/virtual-display.sh python -m pytest src/tests/python/test_native_ui_controls.py src/tests/python/test_native_linux_providers.py -n 4 passes, both frontends × sanitized, under X11 and Wayland.
- [ ] The ci.yml run on the draft PR is green. Report per protocol.

**Risks**

- The SDL route is much larger. Re-estimate once D23 is recorded.

<a id="cx-uib-21"></a>

##### CX-UIB-21 · ui-4-linux part B: labels, text modes, multiline editor, numeric entry, keyboard ranges and selects (D23 route)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L1 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-4-linux` (N14, N15, N16, N17, N18, N19)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); PLAN:ui-1-feasibility-review (D23) → [CL-UIA-10](claude.md#cl-uia-10); [CX-UIB-23](#cx-uib-23) (ready); [CL-UIA-23](claude.md#cl-uia-23) (only if D23 = GTK4; otherwise recorded not applicable)
- **Why not now:** The contract is not approved and D23 is not decided.
- **Parallel-safe with:** CX-UIB-18, CX-UIB-19, CX-UIB-20, CX-UIB-22

> **Review change:** If D23 picks GTK4, waits for the GTK4 core landing `CL-UIA-23` (§10 P7).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxLabel.btrc
- src/stdlib/GUI/Linux/LinuxTextField.btrc
- src/stdlib/GUI/Linux/LinuxSlider.btrc
- src/stdlib/GUI/Linux/LinuxSelect.btrc
- src/stdlib/GUI/Linux/{LinuxTextEditor,LinuxNumericField}.btrc (new)
- `src/tests/native/gui/controls/linux/{Label,TextMode,SecureText,TextEditor,Numeric,Range,KeyedSelect}*.btrc`

**Must not touch**

- approved contract files
- src/stdlib/GUI/Linux/LinuxScrollView.btrc (CX-UIB-31)
- src/compiler/

**Steps**

1. LinuxTextField: search, secure and read-only modes; an undo/redo branch, which is missing today; grapheme-safe boundaries; cut and paste as fallible transactions, so a failed SDL write does not delete text (E44); admission limits (E45).
2. GtkTextView or a painted multiline editor; GtkSpinButton or a painted numeric field.
3. LinuxSlider: arrow, page, Home and End steps (key returns false today); range and step updates (E34).
4. LinuxSelect: opens from the keyboard (key returns false while closed), grouped options, type-ahead. The bounded popup comes in CX-UIB-31.
5. Add UI8 rows and catalog rows.

**Acceptance**

- [ ] The part B families pass test_native_ui_controls.py under tools/virtual-display.sh, X11 and Wayland, both frontends × sanitized.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- Real IME evidence is a desktop-host session (MAC-UIB-02).

<a id="cx-uib-22"></a>

##### CX-UIB-22 · ui-8-macos core: NSAccessibility bridge, automation ids, GPU virtual children, throttled notifications

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L1 (UI8 core) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-8-macos`
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); [CL-UIB-09](claude.md#cl-uib-09) (Objective-C subclass overrides for NSAccessibilityElement)
- **Why not now:** The contract is not approved, and the Stage 29 Objective-C subclassing (I1 step 6) behind CL-UIB-09 has not landed.
- **Parallel-safe with:** CX-UIB-20, CX-UIB-21, CX-UIB-23

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSView.btrc
- src/stdlib/GUI/MacOS/MacOSGPUView.btrc (accessibility adoption only)
- src/stdlib/GUI/MacOS/{MacOSAccessibility,MacOSAccessibilityElement}.btrc (new)
- src/tests/native/gui/accessibility/macos/

**Must not touch**

- approved contract files
- src/compiler/ (file REQUEST(CL-UIB-09) instead)

**Steps**

1. Map UI8 semantic attachment onto NSView/NSControl accessibility properties and identifiers. Native controls appear once.
2. Attach NSAccessibilityElement virtual children to MacOSGPUView, with stable identity, screen frames that hold after scroll and scale, and press/increment actions.
3. Accessible text and range values, transport-throttled announcements, and modal isolation.
4. Assert E11 and E28 in-process, plus the keyboard-only traversal fixture.

**Acceptance**

- [ ] test_native_ui_accessibility.py passes in the macos.yml unit shard, or its AX-trust cases are rule-skipped to MAC-UIB-03, both frontends × sanitized.
- [ ] VoiceOver journeys are recorded by MAC-UIB-01. Report per protocol.

**Risks**

- Hosted-runner AX trust (CX-UIB-07).

<a id="cx-uib-23"></a>

##### CX-UIB-23 · ui-8-linux core, part 1: accessibility tree for native and painted controls (GtkAccessible or AT-SPI over D-Bus)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L1 (UI8 core) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-8-linux` (controls bridge)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); [CL-UIB-03](claude.md#cl-uib-03) (at-spi in the container); [CL-UIB-12](claude.md#cl-uib-12); [CL-UIA-23](claude.md#cl-uia-23) (only if D23 = GTK4; otherwise recorded not applicable)
- **Why not now:** The contract is not approved; D23 and the Stage 31 GObject binding have not landed.
- **Parallel-safe with:** CX-UIB-18, CX-UIB-19, CX-UIB-22

> **Review change:** If D23 picks GTK4, waits for the GTK4 core landing `CL-UIA-23` (§10 P7).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxView.btrc
- src/stdlib/GUI/Linux/{LinuxAccessibility,LinuxAccessibleNode}.btrc (new)
- src/tests/native/gui/accessibility/linux/

**Must not touch**

- approved contract files
- src/stdlib/Tray/ (reuse its D-Bus binding pattern; do not edit it)
- src/compiler/

**Steps**

1. GTK route: GtkAccessible roles, properties and relations on native widgets.
2. SDL route: an AT-SPI provider (org.a11y.atspi.Accessible/Action/Component/Text/Value) for the painted controls, over D-Bus.
3. Apply effective visibility: hidden subtrees leave the tree; disabled controls stay discoverable (E39).
4. Add an AT-SPI tree-dump test with role, name and action assertions (E11 native part, E28).

**Acceptance**

- [ ] tools/virtual-display.sh python -m pytest src/tests/python/test_native_ui_accessibility.py -n 4 dumps the AT-SPI tree with the correct roles and actions, both frontends.
- [ ] Orca journeys are recorded by MAC-UIB-02. Report per protocol.

**Risks**

- The SDL route is a large AT-SPI provider.

<a id="cx-uib-24"></a>

##### CX-UIB-24 · ui-8-linux, part 2: GPU virtual children, accessible collections, text and range values, throttled announcements

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-8-linux` (GPU children and collections)
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06); [CX-UIB-30](#cx-uib-30) (ready)
- **Why not now:** It follows L2 and the UI6 Linux collection owner.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-31, CX-UIB-32, CX-UIB-34

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxAccessibility.btrc
- src/stdlib/GUI/Linux/LinuxAccessibleNode.btrc
- src/stdlib/GUI/Linux/LinuxAccessibleCollection.btrc (new)
- src/tests/native/gui/accessibility/linux/

**Must not touch**

- src/stdlib/GUI/Linux/LinuxGPUView.btrc (request the one adoption hook from CX-UIB-33)
- src/compiler/

**Steps**

1. Expose GPU virtual children with identity and bounds that hold after scroll and scale.
2. Accessible recycled cells keep their identity; an unrealized item can be realized on request (E21).
3. Text and timeline range values (E28 parts) and transport-throttled live/busy announcements.

**Acceptance**

- [ ] The E21 and E28 AT-SPI assertions pass under tools/virtual-display.sh, both frontends.
- [ ] Orca collection journeys are recorded by MAC-UIB-02. Report per protocol.

**Risks**

- On the GTK route, a custom GtkAccessible may need CL-UIB-12.

<a id="cx-uib-25"></a>

##### CX-UIB-25 · ui-5-macos: constrained layout, navigation/split/toolbar, appearance, RTL, text scaling, dismissal and restoration

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L2 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-5-macos`
- **Depends on:** [CL-UIB-05](claude.md#cl-uib-05)
- **Why not now:** Landing L1 and the contract approval have not happened.
- **Parallel-safe with:** CX-UIB-26, CX-UIB-27

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSStack.btrc
- src/stdlib/GUI/MacOS/MacOSGrid.btrc
- src/stdlib/GUI/MacOS/MacOSPanel.btrc
- src/stdlib/GUI/MacOS/MacOSWindow.btrc
- src/stdlib/GUI/MacOS/MacOSLabel.btrc
- src/stdlib/GUI/MacOS/{MacOSNavigationStack,MacOSTabView,MacOSSplitView,MacOSToolbar,MacOSAppearance}.btrc (new)
- src/tests/native/gui/layout/macos/

**Must not touch**

- approved contract files
- src/compiler/

**Steps**

1. Constrained fitting through intrinsicContentSize and constraint-based fittingSize, with baselines; hidden versus collapsed.
2. NSTabView or a segmented navigation, NSSplitView and NSToolbar, each bound to UI3 commands.
3. Observe effectiveAppearance, increased contrast and reduced motion. Labels follow userInterfaceLayoutDirection. Remeasure on font, scale and theme changes.
4. MacOSWindow close veto: windowShouldClose always returns true today. Add the E46 Save/Discard/Cancel transaction and E47 restoration through the SceneRestoration codec.

**Acceptance**

- [ ] In the macos.yml unit shard, test_native_ui_layout.py passes the 320/480/1024 × 100/150/200% × LTR/RTL × light/dark matrix with 0 clipped essential actions, plus 100 resize/theme cycles, E46 for 100 cycles and E47 for 100 fresh-process restores, both frontends.
- [ ] System-setting variants are recorded by MAC-UIB-01. Report per protocol.

**Risks**

- Contrast and reduce-motion are system settings that agents never change. In-process overrides are used where possible; the rest is an owner step.

<a id="cx-uib-26"></a>

##### CX-UIB-26 · ui-5-linux layout: constrained measurement, navigation and split, portal theme and contrast, RTL, close veto

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L2 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-5-linux` (layout, navigation, appearance)
- **Depends on:** [CL-UIB-05](claude.md#cl-uib-05); [CL-UIB-03](claude.md#cl-uib-03); [CL-UIA-23](claude.md#cl-uia-23) (only if D23 = GTK4; otherwise recorded not applicable)
- **Why not now:** Landing L1 has not happened.
- **Parallel-safe with:** CX-UIB-25, CX-UIB-27

> **Review change:** If D23 picks GTK4, waits for the GTK4 core landing `CL-UIA-23` (§10 P7).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxStack.btrc
- src/stdlib/GUI/Linux/LinuxGrid.btrc
- src/stdlib/GUI/Linux/LinuxPanel.btrc
- src/stdlib/GUI/Linux/LinuxLabel.btrc
- src/stdlib/GUI/Linux/LinuxApplication.btrc (close-request path only)
- src/stdlib/GUI/Linux/{LinuxNavigationStack,LinuxTabView,LinuxSplitView,LinuxToolbar,LinuxAppearance}.btrc (new)
- src/tests/native/gui/layout/linux/

**Must not touch**

- src/stdlib/GUI/Linux/{LinuxFonts,LinuxPainter}.btrc (CX-UIB-27)
- src/stdlib/GUI/Linux/LinuxWindow.btrc (CX-UIB-33 in L3)
- src/compiler/

**Steps**

1. Constrained measurement in LinuxStack and LinuxGrid, replacing the independent fittingWidth/fittingHeight queries.
2. Navigation, tab, split and toolbar owners. Theme and contrast from the portal's org.freedesktop.appearance settings. RTL mirroring.
3. Close veto: LinuxApplication.renderWindows closes a window as soon as closeRequested() is set. Route the request through the E46 transaction.
4. Write UI8 rows for the navigation controls.

**Acceptance**

- [ ] tools/virtual-display.sh python -m pytest src/tests/python/test_native_ui_layout.py -n 4 passes the same matrix plus E46 and E47 under X11 and Wayland, both frontends.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- Portal settings need a D-Bus session in the container (CL-UIB-03).

<a id="cx-uib-27"></a>

##### CX-UIB-27 · ui-5-linux shaping: shaped runs and fallback fonts for control text (E37, control part)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L2 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-5-linux` (shaped control text)
- **Depends on:** [CL-UIB-05](claude.md#cl-uib-05); [CL-UIB-03](claude.md#cl-uib-03) (HarfBuzz or Pango); [CL-UIA-23](claude.md#cl-uia-23) (only if D23 = GTK4; otherwise recorded not applicable)
- **Why not now:** Landing L1 and the shaping packages (CL-UIB-03) are missing.
- **Parallel-safe with:** CX-UIB-25, CX-UIB-26

> **Review change:** If D23 picks GTK4, waits for the GTK4 core landing `CL-UIA-23` (§10 P7).

> **Review change:** Commit naming corrected: hand-written integrator data goes in the `fragment:` commit, which Claude re-applies; regenerated outputs go in `derived:`, which Claude drops (§3.5, §10 C3).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxFonts.btrc
- src/stdlib/GUI/Linux/LinuxPainter.btrc (text paths only)
- src/stdlib/GUI/Linux/{LinuxTextShaper.btrc,HarfBuzz.h} (new; Pango.h on the GTK route)
- `src/tests/native/gui/layout/linux/Shaping*.btrc`

**Must not touch**

- src/stdlib/GUI/FreeType/ (reuse it)
- src/compiler/ (file REQUEST(CL-UIB-13) if the header reader rejects the HarfBuzz headers)

**Steps**

1. Replace LinuxFonts.advance and LinuxPainter.text's scalar walk with shaped runs: HarfBuzz plus FreeType with a per-run fallback chain, or Pango on the GTK route.
2. Measurement and drawing share the shaped advances, the cluster mapping and the ink bounds.
3. Add the binding to the GUI/btrc.toml fragment (pkg-config) in the `fragment:` commit.
4. Freeze the E37 strings: Latin ligatures, combining marks, Arabic, Hebrew/Latin bidi, Devanagari, Thai, CJK, Korean and an emoji ZWJ sequence, with named fonts.

**Acceptance**

- [ ] Ink bounds match measurement within one backing pixel at 100/150/200%. There is no '?' substitution when the fallback font has the glyph. Both frontends, under tools/virtual-display.sh.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- The native header reader may not bind HarfBuzz cleanly (a CL-UIB-13 request).

<a id="cx-uib-28"></a>

##### CX-UIB-28 · ui-6-stress-fixture: the 100,000-row collection stress fixture with cell, bind, memory and frame counters

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-6-stress-fixture` (fixture half); `qualification-catalog-fixtures` (UI6 consumer)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); [CX-UIB-08](#cx-uib-08)
- **Why not now:** The UI6 contract is not approved.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-30, CX-UIB-31, CX-UIB-32, CX-UIB-33, CX-UIB-34

**Owned paths**

- src/tests/native/gui/collections/CollectionStress.btrc (new)
- src/tests/python/test_native_ui_collections.py (new)

**Must not touch**

- src/tests/native/gui/collections/CollectionRecords.btrc (CX-UIB-08)
- provider directories

**Steps**

1. Drive the UI6 contract over CX-UIB-08's records: sort, filter and delete during scrolling, stale asynchronous results, and assistive realization requests.
2. Publish native cell counts, binds, memory and frame timing as ledger measurement rows.
3. Add a unit test that proves the fixture fails when the budget is exceeded, using a deliberately unbounded mock owner.

**Acceptance**

- [ ] It compiles and reports counters through both frontends on Linux and in macos.yml.
- [ ] The mock-owner test fails as designed. Report per protocol.

**Risks**

- Frame-timing numbers from software rendering are stand-ins. The owner Mac records the real ones (MAC-UIB-03).

<a id="cx-uib-29"></a>

##### CX-UIB-29 · ui-6-macos: NSCollectionView, NSTableView and NSOutlineView collections with keyed diffing, selection, anchors and two-axis scrolling

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-6-macos`
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06); [CX-UIB-28](#cx-uib-28) (ready); [CL-UIB-09](claude.md#cl-uib-09) (data-source protocols)
- **Why not now:** It follows L2 and the contract approval.
- **Parallel-safe with:** CX-UIB-30, CX-UIB-31, CX-UIB-32, CX-UIB-33, CX-UIB-34

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSScrollView.btrc
- src/stdlib/GUI/MacOS/{MacOSCollectionView,MacOSTableView,MacOSOutlineView,MacOSSelectionModel}.btrc (new)
- src/tests/native/gui/collections/macos/

**Must not touch**

- approved contract files
- src/stdlib/GUI/MacOS/MacOSView.btrc (UI8 is done in L1)
- src/compiler/

**Steps**

1. View-based reuse with keyed diffing and generation checks; a selection model independent of cells; scroll anchors.
2. Two-axis MacOSScrollView with native momentum and honest phase reporting (E41).
3. Accessibility for rows, cells and outline expansion, and realization of unrealized items (E21).

**Acceptance**

- [ ] In the macos.yml unit shard: the 100,000-row fixture meets at most 3× viewport plus 2 cells and 0 rebinds when unchanged; E09 passes; E41 passes 100 synthetic gestures per input class with at most 1 logical unit of error; both frontends × sanitized.
- [ ] Trackpad and frame timing are recorded by MAC-UIB-03. Report per protocol.

**Risks**

- The NSCollectionView diffable API may need generic erasure (CL-UIB-09).

<a id="cx-uib-30"></a>

##### CX-UIB-30 · ui-6-linux collection owner: GtkListView/ColumnView/TreeListModel or an SDL recycler

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-6-linux` (collection owner)
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06); [CX-UIB-28](#cx-uib-28) (ready); [CL-UIA-23](claude.md#cl-uia-23) (only if D23 = GTK4; otherwise recorded not applicable)
- **Why not now:** It follows L2.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-32

> **Review change:** If D23 picks GTK4, waits for the GTK4 core landing `CL-UIA-23` (§10 P7).

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/Linux/{LinuxCollectionView,LinuxTableView,LinuxTreeView,LinuxSelectionModel}.btrc (new)
- src/tests/native/gui/collections/linux/

**Must not touch**

- src/stdlib/GUI/Linux/{LinuxScrollView,LinuxSelect,LinuxWindow}.btrc (CX-UIB-31 and CX-UIB-33)
- src/stdlib/UI/Element.btrc (reuse UIVirtualGrid's semantics; no edits)

**Steps**

1. GTK route: list models, item factories, GtkColumnView and GtkTreeListModel.
2. SDL route: a recycler that keeps UIVirtualGrid's pooling gains, with keyed binds and generation checks.
3. A selection model with anchor and active item; lazily loaded trees with failure and retry (N29).

**Acceptance**

- [ ] Under tools/virtual-display.sh, the 100,000-row fixture meets its budget and E09 and E29 pass, both frontends.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- The SDL recycler is a large custom owner.

<a id="cx-uib-31"></a>

##### CX-UIB-31 · ui-6-linux scroll and select repairs: boundary handoff, horizontal axis, honest phase, viewport-bounded select popup

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-6-linux` (LinuxScrollView/LinuxSelect repairs)
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06); [CX-UIB-33](#cx-uib-33) (ready; it owns LinuxWindow; the deliverScroll hunk follows its merge)
- **Why not now:** It follows L2.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-30, CX-UIB-32, CX-UIB-34

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/GUI/Linux/LinuxScrollView.btrc
- src/stdlib/GUI/Linux/LinuxSelect.btrc
- src/stdlib/GUI/Linux/SDL.h (wheel payload fields only)
- `src/tests/native/gui/linux/{ScrollHandoff,SelectLarge}*.btrc`

**Must not touch**

- src/stdlib/GUI/Linux/LinuxWindow.btrc except the deliverScroll hunk, written after CX-UIB-33 merges

**Steps**

1. LinuxScrollView hands wheel input at a boundary to the parent instead of consuming it; scrolls horizontally; reports precise and phase information only when SDL has it (E41).
2. LinuxSelect gets a viewport-bounded popup that no longer paints every option, real scrolling, and search. The final enabled item among 10,000 is reachable by keyboard (E33).

**Acceptance**

- [ ] Under tools/virtual-display.sh, E41 passes 100 gestures per input class and E33 passes at 10,000 options, both frontends.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- SDL wheel units are not pixels. Document the conversion.

<a id="cx-uib-32"></a>

##### CX-UIB-32 · ui-9-macos: display-link pacing, occlusion state, GPU recovery that keeps editors, capture alignment, artwork accounting

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 (UI9 core) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-9-macos`
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06); [CL-UIB-09](claude.md#cl-uib-09) (display-link target-action, if needed)
- **Why not now:** It follows L2.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-30, CX-UIB-33, CX-UIB-34

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSGPUView.btrc
- src/stdlib/GUI/MacOS/MacOSGPUSurface.btrc
- src/stdlib/GUI/MacOS/MacOSComposedCapture.btrc
- src/stdlib/GUI/MacOS/MacOSViewCapture.btrc
- src/stdlib/GUI/MacOS/MacOSWindow.btrc (occlusion and exposure)
- src/stdlib/GUI/MacOS/MacOSImageHandle.btrc (byte accounting)
- src/stdlib/GUI/MacOS/MacOSDisplayClock.btrc (new)
- src/tests/native/gui/gpu/macos/

**Must not touch**

- approved contract files
- src/stdlib/GPU/ (request it)
- src/compiler/

**Steps**

1. Pace with CVDisplayLink or NSView displayLink only while invalidated. A static idle screen requests 0 passes.
2. Observe NSWindow occlusion state separately from visibility (E42).
3. Recover from surface or device loss without closing native editors or healthy windows (E43).
4. Move MacOSComposedCapture onto the frame-identity contract (E38). Account artwork bytes (E36).

**Acceptance**

- [ ] E42, E43 and E38 pass 100 cycles each with fault injection at the provider boundary, wherever the hosted runner allows (macos.yml).
- [ ] The real-GPU and idle-CPU rows come from MAC-UIB-03. Report per protocol.

**Risks**

- Hosted runners skip real-GPU cases, so most of the UI9 evidence is owner-tier.

<a id="cx-uib-33"></a>

##### CX-UIB-33 · ui-9-linux, part 1: exposure-aware frames, presentation recovery, display pacing, subtree capture without sleeping

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 (UI9 core) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-9-linux` (pacing, exposure, recovery, capture)
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06)
- **Why not now:** It follows L2.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-30, CX-UIB-32, CX-UIB-34

**Owned paths**

- src/stdlib/GUI/Linux/LinuxWindow.btrc
- src/stdlib/GUI/Linux/GUIProvider.btrc
- src/stdlib/GUI/Linux/LinuxGPUView.btrc
- src/stdlib/GUI/Linux/LinuxGPUSurface.btrc
- src/stdlib/GUI/Linux/LinuxDisplayClock.btrc (new)
- src/tests/native/gui/gpu/linux/

**Must not touch**

- src/stdlib/GUI/Linux/{LinuxPainter,LinuxSystemText,LinuxImageView}.btrc (CX-UIB-34)
- src/compiler/

**Steps**

1. Make needsFrame exposure-aware: hidden and minimized events must update visibility, which they do not today (E42).
2. Recover from presentation failure, replacing the throw after 120 unavailable frames (E43).
3. Make capture subtree-scoped and honor the supplied layers. Remove the GPU-readiness polling loop of up to 5 s (E38).
4. Pace frames through the display clock; static idle requests 0 passes. Add the GPU-children adoption hook for CX-UIB-24.

**Acceptance**

- [ ] Under tools/virtual-display.sh with lavapipe, E42, E43 and E38 pass 100 cycles each, both frontends, and static idle requests 0 passes over 60 s.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- Lavapipe timing is not representative. Owner-tier numbers come from the desktop host.

<a id="cx-uib-34"></a>

##### CX-UIB-34 · ui-9-linux, part 2: byte-accounted artwork trim without repaint, and shaped GPU text

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L3 (UI9 core) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-9-linux` (artwork eviction, GPU text shaping)
- **Depends on:** [CL-UIB-06](claude.md#cl-uib-06); [CX-UIB-27](#cx-uib-27)
- **Why not now:** It follows L2 and the L2 shaper.
- **Parallel-safe with:** CX-UIB-29, CX-UIB-30, CX-UIB-32, CX-UIB-33

**Owned paths**

- src/stdlib/GUI/Linux/LinuxPainter.btrc
- src/stdlib/GUI/Linux/LinuxImageView.btrc
- src/stdlib/GUI/Linux/LinuxSystemText.btrc
- `src/tests/native/gui/gpu/linux/{Artwork,GPUText}*.btrc`

**Must not touch**

- src/stdlib/GUI/Linux/{LinuxWindow,GUIProvider}.btrc (CX-UIB-33)

**Steps**

1. Replace the frame-clock image eviction in LinuxPainter with byte-accounted admission and trim: at most 2 decode jobs, and eligible entries released within 1 s with no repaint (E36).
2. Run E36 over a 1,000-album traversal with 256 and 512 thumbnails and oversized sources.
3. Use CX-UIB-27's shaper for LinuxSystemText's GPU text (E37, GPU part).

**Acceptance**

- [ ] E36 stays within 128 MiB and trims within 1 s with 0 repaints; the E37 GPU-text fixtures pass; both frontends under tools/virtual-display.sh.
- [ ] The ci.yml run is green. Report per protocol.

**Risks**

- Counting GPU-retired bytes needs runtime hooks. Request them if the GPU module lacks them.

<a id="cx-uib-35"></a>

##### CX-UIB-35 · ui-7-macos: NSMenu commands, NSPopover, async sheets and panels, security-scoped picks, pasteboard, drag/drop, sharing

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L4 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-7-macos`
- **Depends on:** [CL-UIB-07](claude.md#cl-uib-07); [CL-UIB-09](claude.md#cl-uib-09) (completion blocks)
- **Why not now:** It follows L3.
- **Parallel-safe with:** CX-UIB-36, CX-UIB-37

**Owned paths**

- src/stdlib/GUI/MacOS/MacOSDirectoryPicker.btrc
- src/stdlib/GUI/MacOS/{MacOSFilePicker,MacOSMenu,MacOSPopover,MacOSDialog,MacOSPasteboard,MacOSDragSession,MacOSShareService,MacOSDocumentState}.btrc (new)
- src/tests/native/gui/DirectoryPickerControl.{h,m}
- src/tests/native/gui/services/macos/

**Must not touch**

- src/stdlib/GUI/MacOS/MacOSWindow.btrc (L3 owner; sheet presentation goes through MacOSDialog)
- src/compiler/

**Steps**

1. Bind NSMenu to UI3 commands with validation. Add NSPopover.
2. Use beginSheetModalForWindow-style asynchronous alerts and panels, replacing runModal at MacOSDirectoryPicker.btrc:41. Picks use security-scoped bookmarks.
3. Typed NSPasteboard data with outcomes (E44); NSDraggingSession (E22); NSSharingServicePicker and reveal in Finder (N39); document undo and dirty state (E46 service paths).

**Acceptance**

- [ ] In the macos.yml unit shard: E10 cancel, deny, revoke and parent-destroy each resolve exactly once; E22 and E23 run 100 cycles with 0 stale actions; no blocking picker loop remains; both frontends.
- [ ] Report per protocol.

**Risks**

- Hosted runners may not allow security-scoped bookmarks or the share picker. Rule-skip those to MAC-UIB-03.

<a id="cx-uib-36"></a>

##### CX-UIB-36 · ui-7-linux: portal pickers without the nested pump, menus and popovers, typed clipboard, drag/drop, portal open and share

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 landing L4 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-7-linux`
- **Depends on:** [CL-UIB-07](claude.md#cl-uib-07); [CL-UIB-03](claude.md#cl-uib-03) (portal plus D-Bus session)
- **Why not now:** It follows L3.
- **Parallel-safe with:** CX-UIB-35, CX-UIB-37

**Owned paths**

- src/stdlib/GUI/Linux/LinuxDirectoryPicker.btrc
- src/stdlib/GUI/Linux/SDL.h (folder-dialog and clipboard shims)
- src/stdlib/GUI/Linux/{LinuxFilePicker,LinuxMenu,LinuxPopover,LinuxDialog,LinuxClipboard,LinuxDragSession,LinuxShareService,LinuxPortal}.btrc (new)
- src/tests/native/gui/services/linux/

**Must not touch**

- src/stdlib/GUI/Linux/{LinuxWindow,LinuxScrollView}.btrc
- src/compiler/

**Steps**

1. Asynchronous FileChooser through xdg-desktop-portal, or SDL's asynchronous folder dialog without the nested event pump.
2. Context menus and popovers bound to commands. A typed clipboard that checks the result of SDL_SetClipboardText and treats an empty read as an error (E44).
3. Drag/drop (E22) and portal OpenURI for open, share and reveal (N39).

**Acceptance**

- [ ] Under tools/virtual-display.sh with a D-Bus session, the 8 of 8 family fixtures pass, both frontends.
- [ ] Real-desktop portal trials are recorded by MAC-UIB-02. Report per protocol.

**Risks**

- Portal availability inside the container.

<a id="cx-uib-37"></a>

##### CX-UIB-37 · P6 runtime-probe contract with a realtime no-allocation proof

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (probes, serial contract) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `qualification-p6-runtime-probes` (contract and realtime proof)
- **Depends on:** [CL-UIB-02](claude.md#cl-uib-02); [CX-UIB-05](#cx-uib-05)
- **Why not now:** The UI9 contract (from which the probe item depends) is not approved.
- **Parallel-safe with:** CX-UIB-35, CX-UIB-36

**Owned paths**

- src/stdlib/Realtime/RuntimeProbe.btrc (new)
- src/stdlib/GUI/GUIProbes.btrc (new)
- docs/design/native-ui-contracts/runtime-probes.md
- src/tests/python/test_runtime_probes.py (new)

**Must not touch**

- src/stdlib/Audio/ (provider probes are CX-UIB-38)
- src/compiler/ (if the realtime analyzer cannot prove the counters, file REQUEST(CL-UIB-13))

**Steps**

1. Define one counter and trace owner: preallocated rings of atomic counters, drained by a non-realtime thread into ledger measurement rows.
2. Define the GUI counters: passes, cells, binds, artwork bytes, handles and registrations.
3. Prove with the realtime analyzer, through both compilers, that the callback record path neither allocates nor blocks. Add negative tests that allocate.

**Acceptance**

- [ ] python -m pytest src/tests/python/test_runtime_probes.py passes on Linux and macos.yml, both frontends. The realtime proof accepts the probe and rejects the negatives.
- [ ] Report per protocol.

**Risks**

- Atomics in realtime proofs may need analyzer work (CL-UIB-13).

<a id="cx-uib-38"></a>

##### CX-UIB-38 · Desktop probe providers: CoreAudio, ALSA, macOS and Linux GPU-surface timing, GUI counters, ledger export

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (probes, per provider) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p6-runtime-probes` (desktop providers)
- **Depends on:** [CX-UIB-37](#cx-uib-37) (ready); [CL-UIB-07](claude.md#cl-uib-07)
- **Why not now:** The probe contract and the UI9 cores (L3) are missing.
- **Parallel-safe with:** CX-UIB-35, CX-UIB-36

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- src/stdlib/Audio/Linux/AlsaDevice.btrc (probe hooks only)
- src/stdlib/Audio/ CoreAudio owner (probe hooks only)
- `src/stdlib/GUI/{MacOS,Linux}/*DisplayClock.btrc` probe hooks (after L3)
- src/tests/python/test_runtime_probes_desktop.py (new)

**Must not touch**

- src/stdlib/Realtime/RuntimeProbe.btrc (CX-UIB-37)
- src/compiler/

**Steps**

1. Wire the probes into xrun, dropout and route-change handling, realtime callback durations, frame p95/p99 and longest stall, working set, handles, artwork and cells, idle passes and CPU, and close/drain time.
2. Emit every P6 runtime metric into the ledger from one desktop run.

**Acceptance**

- [ ] A Linux run (tools/virtual-display.sh) and a macos.yml run emit every P6 metric row, both frontends.
- [ ] Real-device numbers come from MAC-UIB-03. Report per protocol.

**Risks**

- Hosted runners have no audio device, so audio probe cases are rule-skipped to the Mac tier.

<a id="cx-uib-39"></a>

##### CX-UIB-39 · New-platform probe providers: WASAPI, RemoteIO and AAudio, plus their GPU-surface timing

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (probes, per provider; runs alongside Stage 35) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p6-runtime-probes` (Windows, iOS and Android providers)
- **Depends on:** [CX-UIB-37](#cx-uib-37); PLAN:platforms-w2-wasapi → [CX-P2-32](#cx-p2-32); PLAN:platforms-i2-audio → [CX-P2-38](#cx-p2-38); PLAN:platforms-a2-aaudio → [CX-P2-43](#cx-p2-43); [CX-UIB-49](#cx-uib-49); [CX-UIB-57](#cx-uib-57); [CX-UIB-65](#cx-uib-65)
- **Why not now:** The new-platform audio providers come from Stage 29, and the GPU tracks from Stage 35.
- **Parallel-safe with:** CX-UIB-48, CX-UIB-56, CX-UIB-64

**Owned paths**

- src/stdlib/Audio/ Windows, iOS and Android owners (probe hooks only)
- src/tests/python/test_runtime_probes_mobile.py (new)

**Must not touch**

- src/stdlib/GUI/{Windows,IOS,Android}/ (request the hooks from the track owners)
- src/compiler/

**Steps**

1. Add probe hooks for callback duration, xruns and route changes to each audio provider.
2. Collect frame timing from the DXGI, CADisplayLink and Choreographer clocks through the track owners' hooks.
3. Export ledger rows from windows.yml, the iOS simulator job and the Android emulator job.

**Acceptance**

- [ ] Each provider emits its metric rows from its CI job, both frontends.
- [ ] Physical numbers come from MAC-UIB-04, 05, 06 and 09. Report per protocol.

**Risks**

- Real xrun evidence needs physical hardware (D8).

<a id="cx-uib-40"></a>

##### CX-UIB-40 · UI evidence harness and screen-reader session runbooks: one command for each owner step

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 (evidence tooling for the MAC packets) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `exit:stage34-ui8-screen-reader-and-hardware-evidence` (tooling)
- **Depends on:** PLAN:ui-0-catalog-schema (Stage 30) → [CX-UIA-02](#cx-uia-02); [CL-UIB-04](claude.md#cl-uib-04)
- **Why not now:** The UI0 catalog schema (Stage 30) and the new test capabilities (CL-UIB-04) do not exist yet.
- **Parallel-safe with:** CX-UIB-10, CX-UIB-11, CX-UIB-14

**Owned paths**

- tools/ui_evidence/ (new package: python3 -m tools.ui_evidence)
- docs/qualification/ui-sessions/ (new VoiceOver, Orca, Narrator and TalkBack checklists for each landing and screen)
- src/tests/python/test_ui_evidence_tools.py (new)

**Must not touch**

- tools/qualification/ (use its API read-only)
- docs/qualification/devices.toml (Claude-owned)

**Steps**

1. Subcommand session --host {mac,linux-desktop} --landing {ui4,ui5,ui6,ui7} --kind {voiceover,orca,keyboard}: launches each journey's fixture app, steps through the checklist, and writes pass/fail notes as ledger rows.
2. Subcommand hardware-tier --landing ...: runs the pytest selections with BTRC_TEST_CAPABILITIES grants (real-gpu, accessibility-api) and ingests the JUnit output with python3 -m tools.qualification ingest --this-host.
3. Subcommand idle-cpu: a 60 s sampler, with and without assistive technology. Subcommand btrsmith-slice --slice N for Stage 36.
4. Every command is wrapped as ~/.cache/btrc/tools/withlock.sh gui-capture ... in the runbooks.

**Acceptance**

- [ ] python -m pytest src/tests/python/test_ui_evidence_tools.py passes, including the dry-run mode, on Linux.
- [ ] Each MAC packet's command runs end to end in dry-run. Report per protocol.

**Risks**

- The capability names must match CL-UIB-04 exactly.

<a id="cx-uib-41"></a>

##### CX-UIB-41 · Stage 34 docs close-out: parity matrix, milestone states and the API inventory change log

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 34 close (lands with L4) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 3 agent-hours
- **PLAN items:** `native-ui-parity.md` / native-ui-api-inventory.md (Stage 34 status)
- **Depends on:** [CX-UIB-35](#cx-uib-35) (ready); [CX-UIB-36](#cx-uib-36) (ready)
- **Why not now:** It follows the UI7 providers.
- **Parallel-safe with:** CX-UIB-37, CX-UIB-38

> **Review change:** Dependencies marked `(ready)` are stacked contract or base branches that only a landing packet merges; they are met when acceptance is ticked and draft-PR CI is green (§3.2 stacked branches, §3.10; §10 C5).

**Owned paths**

- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md
- src/stdlib/GUI/README.md

**Must not touch**

- tools/qualification/denominators.toml (CL-UIB-08)
- PLAN.md

**Steps**

1. Reclassify the macOS and Linux cells for N11-N49 from the catalog evidence, keeping implementation and qualification states distinct.
2. Update UI4-UI9 milestone states and the 'What the tree currently provides' table.
3. Consolidate the API inventory change log, and propose the new frozen release of added operations, kept separate from the 1,620-slot ui0 release.
4. Record that 100% of core actionable controls are covered by UI8, linking the evidence.

**Acceptance**

- [ ] The denominators test passes after CL-UIB-08 re-freezes (test_qualification_ledger.py).
- [ ] git diff --check is clean. Report per protocol.

**Risks**

- Changing the frozen tables would shift the 1,620-slot denominator. Only append.

#### Stage 35: Windows, iOS and Android UI tracks (one milestone behind Stage 34)

<a id="cx-uib-42"></a>

##### CX-UIB-42 · Windows track, core part 1: lossless message pump, worker wakeup, close decision, control events (UI2)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-core` (part 1 of 2)
- **Depends on:** PLAN:ui-1-windows-shell (Stage 31) → [CX-UIA-15](#cx-uia-15); PLAN:ui-3-contract-input (Stage 33) → [CL-UIA-20](claude.md#cl-uia-20); PLAN:platforms-w1-win32-com-imports (Stage 27) → [CL-P2-10](claude.md#cl-p2-10); PLAN:qualification-ci-windows-matrix → [CX-P2-18](#cx-p2-18); [CL-UIB-14](claude.md#cl-uib-14); [CL-UIA-22](claude.md#cl-uia-22)
- **Why not now:** The Windows shell (Stage 31) and W1 (Stages 27-28) have not landed.
- **Parallel-safe with:** CX-UIB-50, CX-UIB-58

> **Review change:** Waits for `CL-UIA-22`: the toolkit decision and the UI2/UI3 re-check on the real shells (§10 P6).

**Owned paths**

- src/stdlib/GUI/Windows/ application, window, action-queue and message-pump owners, plus a new WindowsControlEvents.btrc (names follow the Stage 31 shell)
- `src/tests/native/gui/windows/Core*.btrc`
- src/tests/python/test_native_ui_windows_core.py (new)

**Must not touch**

- src/stdlib/GUI/{MacOS,Linux,IOS,Android}/
- approved contract files
- src/compiler/

**Steps**

1. Pump messages losslessly, with the E40 limit-1, limit and limit+1 cases. Wake on worker completion with PostMessage and MsgWaitForMultipleObjects (E04).
2. Make the WM_CLOSE decision through E46 Save/Discard/Cancel.
3. Map EN_CHANGE to draft and EN_KILLFOCUS/Enter to commit (E01). Keyed combo box (E02). Trackbar preview and commit (E03). Hidden and disabled subtrees (E39).
4. Compile with zig 0.16.0 (--target windows-x86_64) in the cloud. Run on the windows.yml UI shard with BTRC_TEST_CAPABILITIES=windows-native, on windows-latest and windows-11-arm.

**Acceptance**

- [ ] E01-E04, E39, E40 and E46 pass on windows-latest through both frontends. The ARM64 run is recorded separately.
- [ ] UIA tree dumps of the native controls are attached. Report per protocol.

**Risks**

- devices.toml classes hosted-runner GUI runs as stand-ins (an open question).

<a id="cx-uib-43"></a>

##### CX-UIB-43 · Windows track, core part 2: tab order, accelerators with editor precedence, IMM/TSF composition, undo, clipboard, WM_POINTER (UI3)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-core` (part 2 of 2)
- **Depends on:** [CX-UIB-42](#cx-uib-42)
- **Why not now:** It follows Windows core part 1.
- **Parallel-safe with:** CX-UIB-51, CX-UIB-59

**Owned paths**

- src/stdlib/GUI/Windows/{WindowsFocus,WindowsCommands,WindowsTextInput,WindowsPointer,WindowsClipboard}.btrc (new)
- `src/tests/native/gui/windows/Input*.btrc`
- src/tests/python/test_native_ui_windows_input.py (new)

**Must not touch**

- part 1's files (register handlers through its message router)
- src/compiler/

**Steps**

1. Tab order through IsDialogMessage (E05). Accelerators versus WM_KEYDOWN, with the editor taking precedence (E06), and key identity (E25).
2. IMM/TSF composition and text boundaries (E07). EM_UNDO transactions (E14). Keyboard-only form traversal (E13).
3. Clipboard outcomes (E44). WM_POINTER pointer, pen and touch handling, with cancellation.

**Acceptance**

- [ ] E05-E07, E13, E14, E25 and E44 pass on windows.yml through both frontends.
- [ ] Real IME and Narrator await hardware (MAC-UIB-06). Report per protocol.

**Risks**

- TSF in a hosted session may be limited. Record what is unavailable.

<a id="cx-uib-44"></a>

##### CX-UIB-44 · Windows track, controls: the 12 UI4 control families on common controls

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track, one landing behind L1) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-controls-layout` (part 1 of 2: controls)
- **Depends on:** [CX-UIB-43](#cx-uib-43); [CL-UIB-05](claude.md#cl-uib-05)
- **Why not now:** It needs the Windows core and landing L1.
- **Parallel-safe with:** CX-UIB-45, CX-UIB-52, CX-UIB-60

**Owned paths**

- src/stdlib/GUI/Windows/ control owners (button, toggle, radio, segmented, label, text, editor, numeric, slider, select, image, progress, form)
- src/tests/native/gui/controls/windows/

**Must not touch**

- layout, window and DPI owners (CX-UIB-45)
- src/compiler/

**Steps**

1. BS_AUTOCHECKBOX and BS_AUTORADIO, a radio-group or toolbar segmented control, ES_PASSWORD and search EDIT styles, multiline EDIT or RichEdit, an UPDOWN numeric control, trackbar ranges, a grouped combo box, determinate progress and a static image.
2. E15 text scaling, E19, E33 and E34. Native UIA trees for every family.

**Acceptance**

- [ ] The 12 of 12 family fixtures (test_native_ui_controls.py on the Windows host) pass on windows.yml through both frontends, with UIA dumps attached.
- [ ] Report per protocol.

**Risks**

- The RichEdit DLL version varies across runner images.

<a id="cx-uib-45"></a>

##### CX-UIB-45 · Windows track, layout: constrained layout, per-monitor DPI, high contrast and dark mode, RTL, text scaling, navigation

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track, one landing behind L2) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-controls-layout` (part 2 of 2: layout)
- **Depends on:** [CX-UIB-43](#cx-uib-43); [CL-UIB-06](claude.md#cl-uib-06)
- **Why not now:** It needs the Windows core and landing L2.
- **Parallel-safe with:** CX-UIB-44, CX-UIB-53, CX-UIB-61

**Owned paths**

- src/stdlib/GUI/Windows/ stack, grid, panel, window-DPI, navigation, split, toolbar and appearance owners
- src/tests/native/gui/layout/windows/

**Must not touch**

- control owners (CX-UIB-44)
- src/compiler/

**Steps**

1. Constrained measurement. WM_DPICHANGED with per-monitor DPI awareness v2.
2. High contrast and dark mode. WS_EX_LAYOUTRTL. Text scaling.
3. Tab and navigation stack, split pane and toolbar. E26, E27, E46 and E47 where applicable.

**Acceptance**

- [ ] The layout matrix passes at 100/150/200% DPI with 0 clipped actions on windows.yml, both frontends.
- [ ] Report per protocol.

**Risks**

- Runners have a single monitor, so the multi-monitor rows are owner-tier or await hardware.

<a id="cx-uib-46"></a>

##### CX-UIB-46 · Windows track, collections: owner-data virtual ListView and TreeView, selection, anchors

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track, one landing behind L3) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-win-collections-services` (part 1 of 2: collections)
- **Depends on:** [CX-UIB-44](#cx-uib-44); [CX-UIB-45](#cx-uib-45); [CL-UIB-07](claude.md#cl-uib-07)
- **Why not now:** It follows the controls/layout steps and landing L3.
- **Parallel-safe with:** CX-UIB-47, CX-UIB-54, CX-UIB-62

**Owned paths**

- src/stdlib/GUI/Windows/ collection, table, tree and selection owners
- src/tests/native/gui/collections/windows/

**Must not touch**

- service owners (CX-UIB-47)
- src/compiler/

**Steps**

1. An LVS_OWNERDATA virtual list, or a custom recycler. A lazily loaded TreeView. A selection model and scroll anchors.
2. E09, E29 and E41 on windows.yml.

**Acceptance**

- [ ] The 100,000-row fixture (test_native_ui_collections.py) meets its budget on windows.yml, both frontends.
- [ ] Report per protocol.

**Risks**

- Owner-data ListView accessibility needs UIA work in CX-UIB-48.

<a id="cx-uib-47"></a>

##### CX-UIB-47 · Windows track, services: HMENU commands, async IFileOpenDialog, OLE drag/drop, typed clipboard, ShellExecute and share

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track, one landing behind L4) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-collections-services` (part 2 of 2: services)
- **Depends on:** [CX-UIB-44](#cx-uib-44); [CX-UIB-45](#cx-uib-45); [CL-UIB-08](claude.md#cl-uib-08); [CL-UIB-10](claude.md#cl-uib-10)
- **Why not now:** Needs landing L4 and COM provider objects (CL-UIB-10, built on W1).
- **Parallel-safe with:** CX-UIB-46, CX-UIB-55, CX-UIB-63

**Owned paths**

- src/stdlib/GUI/Windows/ menu, popover, dialog, file-picker, clipboard, drag-session and share owners
- src/tests/native/gui/services/windows/

**Must not touch**

- collection owners (CX-UIB-46)
- src/compiler/

**Steps**

1. HMENU bound to commands (E23). Asynchronous IFileOpenDialog through COM, with IFileDialogEvents (E10, E17).
2. OLE IDropTarget, IDropSource and IDataObject (E22). A typed clipboard (E44). ShellExecute, and the share UI where it exists (N39).

**Acceptance**

- [ ] 8 of 8 service families pass, or have a reviewed adaptation, on windows.yml through both frontends.
- [ ] Report per protocol.

**Risks**

- COM sinks depend on Stage 27 step 5.

<a id="cx-uib-48"></a>

##### CX-UIB-48 · Windows track, accessibility: UIA providers for custom controls and GPU virtual children (UI8)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-a11y-gpu` (part 1 of 2: UI Automation)
- **Depends on:** [CX-UIB-46](#cx-uib-46); [CX-UIB-47](#cx-uib-47); [CL-UIB-10](claude.md#cl-uib-10)
- **Why not now:** It follows the collections/services steps and the COM provider objects.
- **Parallel-safe with:** CX-UIB-49, CX-UIB-56, CX-UIB-64

**Owned paths**

- `src/stdlib/GUI/Windows/WindowsAutomation*.btrc` (new)
- src/tests/native/gui/accessibility/windows/

**Must not touch**

- the Windows GPU view owner (CX-UIB-49 adds the one adoption hook)
- src/compiler/

**Steps**

1. Implement IRawElementProviderSimple, IRawElementProviderFragment and IRawElementProviderFragmentRoot, plus the Invoke, Value, RangeValue, Selection and Grid patterns, for custom content and GPU virtual children.
2. Return the provider through WM_GETOBJECT and UiaReturnRawElementProvider.
3. Test with an in-process IUIAutomation client: E11, E21, E28.

**Acceptance**

- [ ] E11, E21 and E28 pass through the UIA client on windows.yml, both frontends, with exact COM release counts.
- [ ] Narrator awaits hardware (MAC-UIB-06). Report per protocol.

**Risks**

- COM identity across several interfaces (CL-UIB-10).

<a id="cx-uib-49"></a>

##### CX-UIB-49 · Windows track, GPU: WebGPU child HWND clipping and overlays, DXGI waitable pacing, device-loss recovery, capture (UI9)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Windows track) · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-win-a11y-gpu` (part 2 of 2: GPU)
- **Depends on:** [CX-UIB-46](#cx-uib-46); [CL-UIB-07](claude.md#cl-uib-07); PLAN:platforms-w2-gpu-image-font (Stage 29) → [CX-P2-33](#cx-p2-33), [CX-P2-34](#cx-p2-34)
- **Why not now:** Needs W2 GPU (Stage 29) and landing L3.
- **Parallel-safe with:** CX-UIB-48, CX-UIB-57, CX-UIB-65

**Owned paths**

- src/stdlib/GUI/Windows/ GPU view, surface, display-clock and capture owners
- src/tests/native/gui/gpu/windows/

**Must not touch**

- src/stdlib/GPU/ (request it)
- src/compiler/

**Steps**

1. Clip the child HWND and composite overlays. Pace frames on the DXGI waitable swapchain.
2. Recover from device loss (E43). Track exposure (E42). Align capture (E38). Static idle requests 0 passes.

**Acceptance**

- [ ] E12, E38, E42 and E43 pass on windows.yml (WARP adapter) through both frontends. ARM64 is recorded separately.
- [ ] Report per protocol.

**Risks**

- Runners have no real GPU; hardware evidence awaits D8.

<a id="cx-uib-50"></a>

##### CX-UIB-50 · iOS track, core part 1: scene lifecycle on an OS-owned loop, CFRunLoop worker wakeup, control events, suspension, dismissal, restoration

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-ios-core` (part 1 of 2)
- **Depends on:** PLAN:ui-1-ios-shell (Stage 31) → [CX-UIA-16](#cx-uia-16); PLAN:ui-3-contract-input → [CL-UIA-20](claude.md#cl-uia-20); PLAN:platforms-i1-app-lifecycle → [CX-P2-36](#cx-p2-36); PLAN:platforms-i1-objc-protocol-adapters → [CL-P2-21](claude.md#cl-p2-21); PLAN:qualification-ci-ios (Stage 29) → [CX-P2-49](#cx-p2-49); [CL-UIB-14](claude.md#cl-uib-14); [CL-UIA-22](claude.md#cl-uia-22)
- **Why not now:** The iOS shell (Stage 31) and I1 (Stage 29) have not landed; the iOS target is still unimplemented (Stage 24).
- **Parallel-safe with:** CX-UIB-42, CX-UIB-58

> **Review change:** Waits for `CL-UIA-22`: the toolkit decision and the UI2/UI3 re-check on the real shells (§10 P6).

**Owned paths**

- src/stdlib/GUI/IOS/ application, scene, window, action-queue and control-event owners (names follow the Stage 31 shell)
- `src/tests/native/gui/ios/Core*.btrc`
- src/tests/python/test_native_ui_ios_core.py (new)

**Must not touch**

- src/stdlib/GUI/{MacOS,Linux,Windows,Android}/
- src/compiler/

**Steps**

1. UIApplicationMain and scene delegates from I1, on an OS-owned loop. Worker wakeup through a CFRunLoop source (E04).
2. UITextField delegate draft and commit (E01). A keyed select backed by UIMenu (E02). UISlider events (E03).
3. Suspension (E30). E46 departure. E47 restoration within the 64 KiB codec.
4. All compiles and simulator runs go through the macos.yml iOS job (BTRC_TEST_CAPABILITIES=ios-simulator). The cloud container has no Apple SDK.

**Acceptance**

- [ ] E01-E04, E30, E46 and E47 pass on the simulator in macos.yml through both frontends, with XCUITest accessibility dumps attached.
- [ ] Physical runs are in MAC-UIB-04. Report per protocol.

**Risks**

- Every iteration waits for a hosted macOS run.

<a id="cx-uib-51"></a>

##### CX-UIB-51 · iOS track, core part 2: UIFocusSystem, UIKeyCommand with editor precedence, UITextInput composition and undo, touch and Pencil, software keyboard

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-ios-core` (part 2 of 2)
- **Depends on:** [CX-UIB-50](#cx-uib-50)
- **Why not now:** It follows iOS core part 1.
- **Parallel-safe with:** CX-UIB-43, CX-UIB-59

**Owned paths**

- src/stdlib/GUI/IOS/{IOSFocus,IOSCommands,IOSTextInput,IOSTouch}.btrc (new)
- `src/tests/native/gui/ios/Input*.btrc`
- src/tests/python/test_native_ui_ios_input.py (new)

**Must not touch**

- part 1's files
- src/compiler/

**Steps**

1. UIFocusSystem traversal (E05). UIKeyCommand with the editor first (E06). Hardware keyboard (E13).
2. UITextInput composition and undo (E07, E14). Touch contact identity and cancellation, and Pencil metadata (N09). Software keyboard (E18).

**Acceptance**

- [ ] E05-E07, E13, E14 and E18 pass on the simulator through both frontends.
- [ ] Report per protocol.

**Risks**

- Simulator IME coverage is partial.

<a id="cx-uib-52"></a>

##### CX-UIB-52 · iOS track, controls: UISwitch, UISegmentedControl, UITextView, UIStepper, search and secure fields, progress, images

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track, one landing behind L1) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-ios-controls-layout` (part 1 of 2: controls)
- **Depends on:** [CX-UIB-51](#cx-uib-51); [CL-UIB-05](claude.md#cl-uib-05)
- **Why not now:** Needs the iOS core and landing L1.
- **Parallel-safe with:** CX-UIB-53, CX-UIB-44, CX-UIB-60

**Owned paths**

- src/stdlib/GUI/IOS/ control owners
- src/tests/native/gui/controls/ios/

**Must not touch**

- layout owners (CX-UIB-53)
- src/compiler/

**Steps**

1. Implement the 12 control families. E15 through Dynamic Type, E19, E33 and E34.
2. Attach XCUITest accessibility trees for every family.

**Acceptance**

- [ ] 12 of 12 families pass on the simulator through both frontends.
- [ ] Report per protocol.

**Risks**

- Generic erasure in UIKit APIs (CL-UIB-09).

<a id="cx-uib-53"></a>

##### CX-UIB-53 · iOS track, layout: safe areas, keyboard layout guide, size classes, split view, navigation and tab bar, Dynamic Type, RTL, reduced motion

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track, one landing behind L2) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-ios-controls-layout` (part 2 of 2: layout)
- **Depends on:** [CX-UIB-51](#cx-uib-51); [CL-UIB-06](claude.md#cl-uib-06)
- **Why not now:** Needs the iOS core and landing L2.
- **Parallel-safe with:** CX-UIB-52, CX-UIB-45, CX-UIB-61

**Owned paths**

- src/stdlib/GUI/IOS/ stack, grid, navigation, split, inset and appearance owners
- src/tests/native/gui/layout/ios/

**Must not touch**

- control owners (CX-UIB-52)
- src/compiler/

**Steps**

1. Safe areas and keyboardLayoutGuide (E18). Size classes and split view. UINavigationController and tab bar (N31, N32).
2. Dynamic Type through the accessibility sizes, RTL and reduced motion (E20, E26), and E46/E47 across navigation.

**Acceptance**

- [ ] The matrix from 320 pt, including rotation, split screen and the largest accessibility text category, has 0 clipped actions on the simulator, both frontends.
- [ ] Report per protocol.

**Risks**

- Split-screen simulation is limited to iPad simulators.

<a id="cx-uib-54"></a>

##### CX-UIB-54 · iOS track, collections: UICollectionView with diffable data sources, selection, anchors

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track, one landing behind L3) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-ios-collections-services` (part 1 of 2: collections)
- **Depends on:** [CX-UIB-52](#cx-uib-52); [CX-UIB-53](#cx-uib-53); [CL-UIB-07](claude.md#cl-uib-07); [CL-UIB-09](claude.md#cl-uib-09)
- **Why not now:** Needs landing L3 and diffable/generic Objective-C interop.
- **Parallel-safe with:** CX-UIB-55, CX-UIB-46, CX-UIB-62

**Owned paths**

- src/stdlib/GUI/IOS/ collection and selection owners
- src/tests/native/gui/collections/ios/

**Must not touch**

- service owners (CX-UIB-55)
- src/compiler/

**Steps**

1. A diffable data source with cell registrations, a selection model and anchors. E09, E29 and E41 (touch pan).

**Acceptance**

- [ ] The 100,000-row fixture meets its budget on the simulator through both frontends.
- [ ] Report per protocol.

**Risks**

- Cell-registration blocks (CL-UIB-09).

<a id="cx-uib-55"></a>

##### CX-UIB-55 · iOS track, services: UIMenu and context menus, async alerts, document picker with security-scoped URLs, pasteboard, drag/drop, share sheet

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track, one landing behind L4) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-ios-collections-services` (part 2 of 2: services)
- **Depends on:** [CX-UIB-52](#cx-uib-52); [CX-UIB-53](#cx-uib-53); [CL-UIB-08](claude.md#cl-uib-08); PLAN:platforms-p3-fs-mobile → [CX-P2-14](#cx-p2-14); PLAN:platforms-i1-sandbox-storage → [CX-P2-37](#cx-p2-37)
- **Why not now:** Needs landing L4 and the P3/I1 storage contracts.
- **Parallel-safe with:** CX-UIB-54, CX-UIB-47, CX-UIB-63

**Owned paths**

- src/stdlib/GUI/IOS/ menu, dialog, document-picker, pasteboard, drag and share owners
- src/tests/native/gui/services/ios/

**Must not touch**

- collection owners (CX-UIB-54)
- src/compiler/

**Steps**

1. UIContextMenuInteraction and UIMenu (E23). Asynchronous UIAlertController.
2. UIDocumentPickerViewController with security-scoped URLs: the E10 non-path resource case.
3. A typed UIPasteboard (E44). UIDragInteraction and UIDropInteraction (E22). UIActivityViewController (N39).

**Acceptance**

- [ ] 8 of 8 service families pass, or are adapted, on the simulator through both frontends.
- [ ] Report per protocol.

**Risks**

- The document picker cannot be driven unattended on the simulator; use XCUITest.

<a id="cx-uib-56"></a>

##### CX-UIB-56 · iOS track, accessibility: UIAccessibilityElement virtual children and XCUITest accessibility assertions (UI8)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-ios-a11y-gpu` (part 1 of 2: accessibility)
- **Depends on:** [CX-UIB-54](#cx-uib-54); [CX-UIB-55](#cx-uib-55); [CL-UIB-09](claude.md#cl-uib-09)
- **Why not now:** It follows collections/services and needs Objective-C subclass overrides.
- **Parallel-safe with:** CX-UIB-57, CX-UIB-48, CX-UIB-64

**Owned paths**

- `src/stdlib/GUI/IOS/IOSAccessibility*.btrc` (new)
- src/tests/native/gui/accessibility/ios/

**Must not touch**

- the iOS GPU view owner (CX-UIB-57 adds the hook)
- src/compiler/

**Steps**

1. UIAccessibilityElement virtual children for the GPU view, accessibility identifiers, and accessible collections and ranges.
2. Assert E11, E21 and E28 through XCUITest.

**Acceptance**

- [ ] E11, E21 and E28 pass on the simulator through both frontends.
- [ ] VoiceOver on devices is MAC-UIB-04. Report per protocol.

**Risks**

- VoiceOver itself does not run in the Simulator.

<a id="cx-uib-57"></a>

##### CX-UIB-57 · iOS track, GPU: CADisplayLink pacing, background/foreground surfaces, memory-pressure trim, mobile artwork at or below 64 MiB (UI9)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (iOS track) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-ios-a11y-gpu` (part 2 of 2: GPU)
- **Depends on:** [CX-UIB-54](#cx-uib-54); [CL-UIB-07](claude.md#cl-uib-07); PLAN:platforms-i2-gpu (Stage 29) → [CX-P2-39](#cx-p2-39)
- **Why not now:** Needs I2 GPU (Stage 29) and landing L3.
- **Parallel-safe with:** CX-UIB-56, CX-UIB-49, CX-UIB-65

> **Review change:** Probes the simulator's Metal device first (§10 F8).

**Owned paths**

- src/stdlib/GUI/IOS/ GPU view, surface, display-clock and capture owners
- src/tests/native/gui/gpu/ios/

**Must not touch**

- src/stdlib/GPU/ (request it)
- src/compiler/

**Steps**

1. First probe MTLCreateSystemDefaultDevice inside the runner's simulator. If it returns nil, the simulator GPU rows fall back to MAC-P2-04 and are recorded so.
2. CADisplayLink pacing. Release and restore surfaces on background and foreground. Trim on memory warnings.
3. E36 mobile budget: artwork at or below 64 MiB. E38, E42 and E43.

**Acceptance**

- [ ] E38, E42 and E43 pass on the simulator, and artwork stays at or below 64 MiB, both frontends.
- [ ] Report per protocol.

**Risks**

- Simulator GPU behavior differs from devices.

<a id="cx-uib-58"></a>

##### CX-UIB-58 · Android track, core part 1: Looper wakeup without a cached JNIEnv, control events, Activity recreation and process death, predictive Back

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-android-core` (part 1 of 2)
- **Depends on:** PLAN:ui-1-android-shell (Stage 31) → [CX-UIA-17](#cx-uia-17); PLAN:ui-3-contract-input → [CL-UIA-20](claude.md#cl-uia-20); PLAN:platforms-a1-checked-jni → [CL-P2-24](claude.md#cl-p2-24); PLAN:platforms-a1-activity-lifecycle → [CX-P2-41](#cx-p2-41); PLAN:qualification-ci-android → [CX-P2-50](#cx-p2-50); [CL-UIB-11](claude.md#cl-uib-11); [CL-UIB-14](claude.md#cl-uib-14); [CL-UIA-22](claude.md#cl-uia-22)
- **Why not now:** The Android shell (Stage 31) and A1 (Stage 29) have not landed; the Android targets are still unimplemented (Stage 24).
- **Parallel-safe with:** CX-UIB-42, CX-UIB-50

> **Review change:** Waits for `CL-UIA-22`: the toolkit decision and the UI2/UI3 re-check on the real shells (§10 P6).

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ application, activity, window, action-queue and control-event owners
- src/stdlib/GUI/Android/java/ (Java shim sources: TextWatcher, OnBackPressedCallback)
- `src/tests/native/gui/android/Core*.btrc`
- src/tests/python/test_native_ui_android_core.py (new)

**Must not touch**

- src/stdlib/GUI/{MacOS,Linux,Windows,IOS}/
- src/stdlib/Java/ (Claude, A1)
- src/compiler/

**Steps**

1. Wake through Looper/Handler from workers, never caching a JNIEnv (E04).
2. A TextWatcher and the IME action for draft and commit (E01). A keyed Spinner or AutoComplete (E02). SeekBar events (E03).
3. Activity recreation and process death (E30, E47). OnBackPressedDispatcher and predictive Back with Save/Discard/Cancel (E46).
4. Cross-compile with the NDK in the cloud. Get evidence from the ci.yml Android emulator job (BTRC_TEST_CAPABILITIES=android-emulator) on API 29, the current API and the 16 KiB-page image.

**Acceptance**

- [ ] E01-E04, E30, E46 and E47 (process death) pass on the emulator through both frontends, with UiAutomator dumps attached.
- [ ] Report per protocol.

**Risks**

- Emulators on hosted runners are slow and flaky; retry policy goes through CL-UIB-14.

<a id="cx-uib-59"></a>

##### CX-UIB-59 · Android track, core part 2: focus navigation, KeyEvent versus InputConnection, composition, hardware and software keyboard, MotionEvent identity, clipboard

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-android-core` (part 2 of 2)
- **Depends on:** [CX-UIB-58](#cx-uib-58)
- **Why not now:** It follows Android core part 1.
- **Parallel-safe with:** CX-UIB-43, CX-UIB-51

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/{AndroidFocus,AndroidCommands,AndroidTextInput,AndroidTouch,AndroidClipboard}.btrc (new)
- `src/tests/native/gui/android/Input*.btrc`
- src/tests/python/test_native_ui_android_input.py (new)

**Must not touch**

- part 1's files
- src/compiler/

**Steps**

1. Focus navigation (E05). Keep hardware keys and the IME separate (E06, E25). Composition (E07). Hardware keyboard (E13). IME insets (E18).
2. MotionEvent pointer identity and cancellation (N08/N09). Undo where it exists (E14, adapted). Clipboard (E44).

**Acceptance**

- [ ] E05-E07, E13, E18 and E44 pass on the emulator through both frontends.
- [ ] Report per protocol.

**Risks**

- Emulator IME coverage is partial.

<a id="cx-uib-60"></a>

##### CX-UIB-60 · Android track, controls: CheckBox, Switch, RadioGroup, segmented toggles, multiline EditText, numeric input, SearchView, progress, images

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track, one landing behind L1) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-android-controls-layout` (part 1 of 2: controls)
- **Depends on:** [CX-UIB-59](#cx-uib-59); [CL-UIB-05](claude.md#cl-uib-05); [CL-UIB-11](claude.md#cl-uib-11) (AAR classes for the toggle group)
- **Why not now:** Needs the Android core and landing L1.
- **Parallel-safe with:** CX-UIB-61, CX-UIB-44, CX-UIB-52

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ control owners
- src/tests/native/gui/controls/android/

**Must not touch**

- layout owners (CX-UIB-61)
- src/compiler/

**Steps**

1. Implement the 12 control families. E15 through fontScale, E19, E33 and E34.
2. Attach UiAutomator trees for every family.

**Acceptance**

- [ ] 12 of 12 families pass on the emulator through both frontends.
- [ ] Report per protocol.

**Risks**

- The Material components AAR dependency.

<a id="cx-uib-61"></a>

##### CX-UIB-61 · Android track, layout: WindowInsets including the IME, density, fontScale, Fragment and navigation stacks, RTL, split screen

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track, one landing behind L2) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-android-controls-layout` (part 2 of 2: layout)
- **Depends on:** [CX-UIB-59](#cx-uib-59); [CL-UIB-06](claude.md#cl-uib-06)
- **Why not now:** Needs the Android core and landing L2.
- **Parallel-safe with:** CX-UIB-60, CX-UIB-45, CX-UIB-53

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ stack, grid, navigation, inset and appearance owners
- src/tests/native/gui/layout/android/

**Must not touch**

- control owners (CX-UIB-60)
- src/compiler/

**Steps**

1. WindowInsets (IME, system bars), density and fontScale. Navigation stacks. RTL. Split screen.
2. E18, E20, E26 and E46/E47 across navigation.

**Acceptance**

- [ ] The matrix from 320 dp, at the largest font scale and with rotation, has 0 clipped actions on the emulator, both frontends.
- [ ] Report per protocol.

**Risks**

- Split screen on the emulator.

<a id="cx-uib-62"></a>

##### CX-UIB-62 · Android track, collections: RecyclerView with stable ids and DiffUtil, selection, anchors

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track, one landing behind L3) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-android-collections-services` (part 1 of 2: collections)
- **Depends on:** [CX-UIB-60](#cx-uib-60); [CX-UIB-61](#cx-uib-61); [CL-UIB-07](claude.md#cl-uib-07); [CL-UIB-11](claude.md#cl-uib-11) (androidx RecyclerView through the AAR reader and a shim adapter)
- **Why not now:** Needs landing L3 and androidx interop.
- **Parallel-safe with:** CX-UIB-63, CX-UIB-46, CX-UIB-54

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ collection and selection owners
- src/stdlib/GUI/Android/java/ RecyclerView adapter shim
- src/tests/native/gui/collections/android/

**Must not touch**

- service owners (CX-UIB-63)
- src/compiler/

**Steps**

1. RecyclerView with stable ids and DiffUtil through a Java adapter shim. A selection model. E09, E29 and E41 (nested scrolling).

**Acceptance**

- [ ] The 100,000-row fixture meets its budget on the emulator through both frontends.
- [ ] Report per protocol.

**Risks**

- Callbacks crossing JNI on every bind.

<a id="cx-uib-63"></a>

##### CX-UIB-63 · Android track, services: PopupMenu commands, async dialogs, SAF pickers with persisted grants, ClipboardManager, drag/drop, Intent share

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track, one landing behind L4) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-android-collections-services` (part 2 of 2: services)
- **Depends on:** [CX-UIB-60](#cx-uib-60); [CX-UIB-61](#cx-uib-61); [CL-UIB-08](claude.md#cl-uib-08); PLAN:platforms-a1-storage-permissions → [CX-P2-42](#cx-p2-42); PLAN:platforms-p3-fs-mobile → [CX-P2-14](#cx-p2-14)
- **Why not now:** Needs landing L4 and the A1/P3 storage contracts.
- **Parallel-safe with:** CX-UIB-62, CX-UIB-47, CX-UIB-55

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ menu, dialog, SAF-picker, clipboard, drag and share owners
- src/tests/native/gui/services/android/

**Must not touch**

- collection owners (CX-UIB-62)
- src/compiler/

**Steps**

1. PopupMenu and ContextMenu bound to commands (E23). Asynchronous dialogs.
2. Storage Access Framework pickers with content URIs and persisted grants: E10 with revoked grants and process recreation.
3. ClipboardManager (E44). Drag/drop (E22). Intent share and open (N39).

**Acceptance**

- [ ] 8 of 8 service families pass, or are adapted, on the emulator through both frontends.
- [ ] Report per protocol.

**Risks**

- Driving the SAF UI needs UiAutomator.

<a id="cx-uib-64"></a>

##### CX-UIB-64 · Android track, accessibility: AccessibilityNodeProvider virtual children through a Java shim, UiAutomator assertions (UI8)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-android-a11y-gpu` (part 1 of 2: accessibility)
- **Depends on:** [CX-UIB-62](#cx-uib-62); [CX-UIB-63](#cx-uib-63); [CL-UIB-11](claude.md#cl-uib-11)
- **Why not now:** It follows collections/services and needs the JNI shim registration (CL-UIB-11).
- **Parallel-safe with:** CX-UIB-65, CX-UIB-48, CX-UIB-56

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- `src/stdlib/GUI/Android/AndroidAccessibility*.btrc` (new)
- src/stdlib/GUI/Android/java/ AccessibilityNodeProvider shim
- src/tests/native/gui/accessibility/android/

**Must not touch**

- the Android GPU view owner (CX-UIB-65 adds the hook)
- src/compiler/

**Steps**

1. AccessibilityNodeProvider virtual children for the GPU view, accessible collections and ranges.
2. Assert E11, E21 and E28 through UiAutomator.

**Acceptance**

- [ ] E11, E21 and E28 pass on the emulator through both frontends.
- [ ] TalkBack is MAC-UIB-05. Report per protocol.

**Risks**

- Shim class packaging (CL-UIB-11).

<a id="cx-uib-65"></a>

##### CX-UIB-65 · Android track, GPU: Choreographer pacing, SurfaceView recreation that leaves audio alone, onTrimMemory, mobile artwork at or below 64 MiB (UI9)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 35 (Android track) · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-android-a11y-gpu` (part 2 of 2: GPU)
- **Depends on:** [CX-UIB-62](#cx-uib-62); [CL-UIB-07](claude.md#cl-uib-07); PLAN:platforms-a2-gpu (Stage 29) → [CX-P2-44](#cx-p2-44)
- **Why not now:** Needs A2 GPU (Stage 29) and landing L3.
- **Parallel-safe with:** CX-UIB-64, CX-UIB-49, CX-UIB-57

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- src/stdlib/GUI/Android/ GPU view, surface, display-clock and capture owners
- src/tests/native/gui/gpu/android/

**Must not touch**

- src/stdlib/Audio/
- src/stdlib/GPU/ (request it)
- src/compiler/

**Steps**

1. Pace with Choreographer. Destroy and recreate the surface without disturbing the audio owner. Trim on onTrimMemory.
2. E36 mobile budget, E38, E42 and E43.

**Acceptance**

- [ ] E38, E42 and E43 pass on the emulator, and artwork stays at or below 64 MiB, both frontends.
- [ ] Report per protocol.

**Risks**

- Emulator GPU (swiftshader) differs from devices.

#### Stage 36: BTRSmith screen migration slices (one milestone behind Stage 34)

<a id="cx-uib-66"></a>

##### CX-UIB-66 · BTRSmith: replace the self-reposting step loop with worker wakeups and a display clock

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 (serial composition-root change) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-event-loop`
- **Depends on:** PLAN:ui-2-macos → [CL-UIA-14](claude.md#cl-uia-14); PLAN:ui-2-linux → [CL-UIA-14](claude.md#cl-uia-14); PLAN:btrsmith-libraryui-split (Stage 32) → [CL-UIA-17](claude.md#cl-uia-17), [CL-UIA-18](claude.md#cl-uia-18); [CL-UIB-07](claude.md#cl-uib-07) (UI9 display clock); [CL-UIB-15](claude.md#cl-uib-15) (step: BTRSmith pinned to the landing this slice needs)
- **Why not now:** UI2 (Stage 32) and the UI9 display clock (L3) have not landed.
- **Parallel-safe with:** CX-UIB-69

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/runtime/GUIApplication.btrc
- btrsmith: src/application/runtime/LibrarySessionOwner.btrc
- btrsmith: src/application/runtime/AlbumLibraryPreviewCoordinator.btrc
- btrsmith: src/application/runtime/PlayerSessionOwner.btrc

**Must not touch**

- btrsmith: src/application/runtime/ApplicationSession.btrc and adapters/ApplicationView.btrc (integrator hotspots)
- btrc repository

**Steps**

1. Remove the step() re-post through GUI.postAfter (GUIApplication.btrc:374-382).
2. Deliver scanner, artwork, preview and catalog-page completions through UI2's bounded worker-to-UI wakeups.
3. Drive musical frames from the UI9 display clock. A static screen requests no passes.
4. Verify the Linux frontend in the cloud (Xvfb). macOS evidence comes from MAC-UIB-07.

**Acceptance**

- [ ] On Linux, a 60 s static-idle trace shows 0 presentation passes and 0 timer wakeups over 60 s (counters); CPU % is MAC-UIB-07's, both frontends.
- [ ] Shutdown and drain journeys pass. Player frame pacing is unchanged (frame stats).
- [ ] macOS is MAC-UIB-07. Report per protocol on the BTRSmith hub.

**Risks**

- The single composition root: everything serializes behind it.
- Codex access to BTRSmith (open question).

<a id="cx-uib-67"></a>

##### CX-UIB-67 · BTRSmith slice 1: Library search and filters on subscriptions with stable option ids

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-slice1-search-filters`
- **Depends on:** PLAN:btrsmith-ui0-callers → [CL-UIA-03](claude.md#cl-uia-03); PLAN:btrsmith-libraryui-split → [CL-UIA-17](claude.md#cl-uia-17), [CL-UIA-18](claude.md#cl-uia-18); PLAN:ui-3-macos → [CL-UIA-20](claude.md#cl-uia-20); PLAN:ui-3-linux → [CL-UIA-20](claude.md#cl-uia-20); [CL-UIB-05](claude.md#cl-uib-05); [CX-UIB-09](#cx-uib-09); [CL-UIB-15](claude.md#cl-uib-15) (step: BTRSmith pinned to the landing this slice needs)
- **Why not now:** UI1-UI4 (Stages 31-34 L1) have not landed.
- **Parallel-safe with:** CX-UIB-69

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/adapters/TextBinding.btrc
- btrsmith: src/application/adapters/SelectionBinding.btrc
- btrsmith: src/application/adapters/LibraryFilters.btrc
- btrsmith: tests/macos/ApplicationJourney.btrc
- btrsmith: ApplicationView.btrc search hunk (through the integrator)

**Must not touch**

- btrsmith: GUIApplication.btrc (CX-UIB-66)
- btrc repository

**Steps**

1. Move the search ITextField and the four filter ISelects from nextChange polling (31 call sites) to scoped edit, commit and selection subscriptions with stable option ids.
2. Replacing LibraryFilters' hand-computed popover geometry (LibraryFilters.btrc:24-33) needs UI7. Record it as a deferral to CX-UIB-72.
3. Measure search and filter p95 on the 10,000-song fixture.

**Acceptance**

- [ ] E01-E07 pass for this slice on Linux, both frontends. No polling remains at these call sites.
- [ ] Search p95 is at most 100 ms (Linux stand-in; MAC-UIB-07 for macOS). Report per protocol.

**Risks**

- The ApplicationView hotspot.

<a id="cx-uib-68"></a>

##### CX-UIB-68 · BTRSmith slice 2: Settings and device changes on keyed selects, the E46 departure transaction, async alerts

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-slice2-settings`; `ui-4-btrsmith-settings`
- **Depends on:** [CX-UIB-67](#cx-uib-67); [CL-UIB-06](claude.md#cl-uib-06); [CL-UIB-08](claude.md#cl-uib-08) (async alerts); PLAN:btrsmith-audio-adaptation (Stage 29) → [CL-P2-26](claude.md#cl-p2-26), [CX-P2-47](#cx-p2-47)
- **Why not now:** UI4, UI5 and UI7 have not landed.
- **Parallel-safe with:** CX-UIB-70

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/adapters/SettingsScreen.btrc
- btrsmith: `src/application/adapters/*SettingsBinding.btrc`
- btrsmith: src/frontend/settings/
- btrsmith: src/application/runtime/SettingsSessionOwner.btrc (except the picker hunk, which is CX-UIB-72)
- btrsmith: `tests/macos/Settings*.btrc`

**Must not touch**

- btrsmith: GUIApplication.btrc
- btrc repository

**Steps**

1. Keyed device selects that survive a device-list refresh while the form is open. Native validation keeps invalid drafts. Volume and speed use preview and commit.
2. The E46 Save/Discard/Cancel transaction replaces history-peek draft retention.
3. Asynchronous alerts. A narrow-window section selector. Save and Back by keyboard. Cancel restores focus.

**Acceptance**

- [ ] E46 passes 100 cycles with 0 lost drafts or duplicate saves.
- [ ] 100 device refreshes never reset the active editor.
- [ ] Linux both frontends; macOS through MAC-UIB-07. Report per protocol.

**Risks**

- Device changes need audio hardware on the Mac.

<a id="cx-uib-69"></a>

##### CX-UIB-69 · BTRSmith adaptive layout, part A: platform-derived admission bounds, semantic icon ids, localizable strings, desktop E46/E47

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-adaptive-layout` (shared primitives); `ui-5-btrsmith-adaptive` (E46/E47 and admission bounds)
- **Depends on:** PLAN:btrsmith-ui0-callers → [CL-UIA-03](claude.md#cl-uia-03); [CL-UIB-06](claude.md#cl-uib-06); [CL-UIA-17](claude.md#cl-uia-17); [CL-UIA-18](claude.md#cl-uia-18); [CL-UIB-15](claude.md#cl-uib-15) (step: BTRSmith pinned to landing L2)
- **Why not now:** UI5 (landing L2) has not landed.
- **Parallel-safe with:** CX-UIB-66, CX-UIB-67

> **Review change:** Waits for the Library.UI split (`CL-UIA-17/18`), which edits the same BTRSmith adapters, and for the L2 pin bump (§10 C16).

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/adapters/ApplicationView.btrc (present admission; serialized through the integrator)
- btrsmith: src/application/runtime/ desktop scene-descriptor owner (new)
- btrsmith: docs/UXConstants.md
- btrsmith: string resources (new)

**Must not touch**

- btrsmith: GUIApplication.btrc
- btrc repository

**Steps**

1. Replace the 480-4096 × 240-4096 admission (ApplicationView.btrc:123) with platform-derived bounds that admit 320-unit phones and keep the resource limits.
2. Replace the 13 SF Symbol strings with semantic icon ids. Move compiled-in labels and tooltips into localizable strings (issue #18).
3. Add desktop E46 dirty dismissal and E47 versioned scene descriptors, kept separate from btrsmith.json and SQLite.

**Acceptance**

- [ ] On Linux: E46 passes 100 cycles; E47 passes 100 fresh-process restores with 0 replayed side effects; 20 launches have p95 at most 3 s. Both frontends.
- [ ] MAC-UIB-07 for macOS. Report per protocol.

**Risks**

- The ApplicationView hotspot.

<a id="cx-uib-70"></a>

##### CX-UIB-70 · BTRSmith adaptive layout, part B: compact Library, Settings and Player layouts on intrinsic stacks

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `btrsmith-ui-adaptive-layout` (per-screen compact layouts); `ui-5-btrsmith-adaptive` (compact layouts and matrix)
- **Depends on:** [CX-UIB-69](#cx-uib-69); [CL-UIA-17](claude.md#cl-uia-17); [CL-UIA-18](claude.md#cl-uia-18); [CL-UIB-15](claude.md#cl-uib-15) (step: BTRSmith pinned to landing L2)
- **Why not now:** It follows part A.
- **Parallel-safe with:** CX-UIB-68

> **Review change:** Waits for the Library.UI split (`CL-UIA-17/18`), which edits the same BTRSmith adapters, and for the L2 pin bump (§10 C16).

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/adapters/{SettingsScreen,PlayerScreen,AlbumDetailScreen}.btrc (layout hunks, merged after their slice owners)
- btrsmith: `src/frontend/**` layout code

**Must not touch**

- btrsmith: ApplicationView.btrc
- btrc repository

**Steps**

1. Replace the 102 manual .arrange calls with intrinsic stacks. Add compact layouts with safe areas and keyboard insets. Support text scaling to 200% and RTL.
2. Interleave with slices 1-4, not as one big change.

**Acceptance**

- [ ] The matrix (320 phone, tablet, split screen, desktop at 100/150/200%) has 0 clipped essential actions.
- [ ] 100 resize/theme cycles keep state, focus and anchors on Linux, both frontends. MAC-UIB-07 for macOS.

**Risks**

- Merge conflicts with the slice owners. The integrator orders the merges.

<a id="cx-uib-71"></a>

##### CX-UIB-71 · BTRSmith slice 3a: Library browse on the shared collection contract with the artwork budget

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `btrsmith-ui-slice3-library` (browse); `ui-6-btrsmith-library`
- **Depends on:** [CX-UIB-68](#cx-uib-68); [CL-UIB-07](claude.md#cl-uib-07); PLAN:btrsmith-storage-resources → [CL-P2-25](claude.md#cl-p2-25)
- **Why not now:** UI6 (landing L3) has not landed.
- **Parallel-safe with:** CX-UIB-72

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/frontend/library/ (AlbumGrid, AlbumWindowCache, BoundedWindowCache)
- btrsmith: src/application/adapters/{AlbumCardActions,AlbumHoverOverlay,AlbumDetailScreen,LibraryBinding}.btrc
- btrsmith: tests/macos/{AlbumGrid,AlbumHoverJourney,LibraryScrollProfile}.btrc

**Must not touch**

- btrsmith: GUIApplication.btrc
- btrc repository

**Steps**

1. Rebase AlbumGrid onto the UI6 owners while keeping the stable-key pool (36 cells at full width, 12 compact) and the scroll anchors.
2. Add a touch replacement for the hover-only preview, pending the UX decision. Make empty, error and progress states accessible.

**Acceptance**

- [ ] On the 1,000-album catalog: at most 3× viewport cells; E36 artwork at most 128 MiB with trim within 1 s and no repaint; 60 Hz scroll p95 at most 16.7 ms (MAC-UIB-07). Both frontends.
- [ ] Report per protocol.

**Risks**

- The hover-preview gesture is an open UX decision.

<a id="cx-uib-72"></a>

##### CX-UIB-72 · BTRSmith slice 3b: async import picker, scan/cancel progress, unsaved-edit flows, filter popover

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-ui-slice3-library` (import); `ui-7-btrsmith-import`
- **Depends on:** [CX-UIB-66](#cx-uib-66); [CX-UIB-67](#cx-uib-67); [CL-UIB-08](claude.md#cl-uib-08); PLAN:btrsmith-storage-resources → [CL-P2-25](claude.md#cl-p2-25)
- **Why not now:** UI7 (landing L4) has not landed.
- **Parallel-safe with:** CX-UIB-71

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/runtime/GUIApplication.btrc (picker hunk; serialized after CX-UIB-66)
- btrsmith: src/application/runtime/SettingsSessionOwner.btrc (picker hunk)
- btrsmith: src/application/commands/ApplicationEffect.btrc
- btrsmith: src/application/adapters/LibraryFilters.btrc (popover; after CX-UIB-67)

**Must not touch**

- btrc repository

**Steps**

1. Replace the synchronous GUI.chooseDirectory calls (GUIApplication.btrc:144, SettingsSessionOwner.btrc:172) with the asynchronous scoped-resource picker.
2. Import, scan and cancel progress. Save/Discard on the settings forms. Replace the filter geometry with the native popover (slice 1's deferral).

**Acceptance**

- [ ] No blocking picker and no duplicate completion. 100 cancel and parent-close cycles on Linux, both frontends. MAC-UIB-07 for macOS.

**Risks**

- The GUIApplication hotspot is serialized.

<a id="cx-uib-73"></a>

##### CX-UIB-73 · BTRSmith slice 4, part A: Player transport, keys and exact scrub through shared commands

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-slice4-player` (transport and keys); `ui-9-btrsmith-player` (transport part)
- **Depends on:** [CX-UIB-71](#cx-uib-71); [CX-UIB-66](#cx-uib-66); [CL-UIB-07](claude.md#cl-uib-07); PLAN:btrsmith-gpu-portability → [CX-P2-48](#cx-p2-48)
- **Why not now:** UI9 (landing L3) and the earlier slices have not landed.
- **Parallel-safe with:** CX-UIB-75

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/application/adapters/PlayerScreen.btrc
- btrsmith: src/frontend/player/ transport, keyboard and keys owners (UiPlayerTransport, UiPlayerKeyboard, PlayerKeys)
- btrsmith: `tests/macos/{PlayerKeys,PlayerPointer}*.btrc`

**Must not touch**

- btrsmith: src/platform/gpu/PlayerRenderer.btrc (CX-UIB-74)
- btrc repository (the slider knob fix is in CX-UIB-19)

**Steps**

1. Scrub preview and commit keep exact 64-bit values around 2^53 (E34). Volume, speed and select go through the shared commands.
2. Route Space and Left/Right Option through command precedence, so typing a space never starts playback.

**Acceptance**

- [ ] The PlayerKeys and PlayerPointer journeys pass on Linux, both frontends.
- [ ] Exact values survive keyboard and accessibility increments. MAC-UIB-07 for macOS.

**Risks**

- Keyboard precedence across GPU focus.

<a id="cx-uib-74"></a>

##### CX-UIB-74 · BTRSmith slice 4, part B: tab drag, cycle lane, lyric band and auto-hide over GPU content, overlay clipping, soak instrumentation

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-slice4-player` (gestures and overlays); `ui-9-btrsmith-player` (GPU, soak part)
- **Depends on:** [CX-UIB-73](#cx-uib-73); [CX-UIB-38](#cx-uib-38)
- **Why not now:** It follows part A.
- **Parallel-safe with:** CX-UIB-75

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/frontend/player/ tab, cycle and lyric owners
- btrsmith: src/platform/gpu/PlayerRenderer.btrc
- btrsmith: src/application/runtime/NativeVisualCoordinator.btrc
- btrsmith: `tests/macos/{PlayerPan,PlayerComposition,PlayerGPU}*.btrc`

**Must not touch**

- btrsmith: PlayerScreen.btrc (CX-UIB-73)
- btrc repository

**Steps**

1. Tab drag with momentum adapted from pointer to touch, the cycle lane, the lyric band, and auto-hide as a tap toggle.
2. Clip native overlays over IGPUView (PlayerRenderer.btrc:36). Add probe instrumentation for the 30-minute soak.

**Acceptance**

- [ ] The PlayerPan, PlayerComposition and PlayerGPU journeys pass on Linux, both frontends. Frame p95 is at most 16.7 ms (MAC-UIB-07).
- [ ] The soak is MAC-UIB-08.

**Risks**

- Hosted Linux has no audio device.

<a id="cx-uib-75"></a>

##### CX-UIB-75 · BTRSmith accessibility, part A: accessible musical GPU surfaces and recycled album cells

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-ui-accessibility` (GPU surfaces and cells)
- **Depends on:** [CX-UIB-67](#cx-uib-67); [CL-UIB-07](claude.md#cl-uib-07)
- **Why not now:** The UI8 GPU-children bridges (L1 and L3) have not landed.
- **Parallel-safe with:** CX-UIB-73, CX-UIB-74

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: src/platform/gpu/ accessibility adapters (new files only)
- btrsmith: src/frontend/player/ and src/frontend/library/ accessibility adapters (new files only)

**Must not touch**

- files owned by CX-UIB-71, 73 and 74 (hook requests go to them)
- btrc repository

**Steps**

1. Expose the tab, highway and fretboard surfaces as virtual children with stable ids and transport-level announcements, never one per note.
2. Accessible recycled album cells. D25 places accessibility in the post-MVP section of the PRD (PRD.md:159).

**Acceptance**

- [ ] An AT-SPI inspection on Linux finds every core musical surface named and operable, both frontends.
- [ ] VoiceOver per screen is MAC-UIB-07.

**Risks**

- Announcement flooding.

<a id="cx-uib-76"></a>

##### CX-UIB-76 · BTRSmith accessibility, part B: an audit of every core actionable control, plus per-platform screen-reader journey scripts

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 36 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `btrsmith-ui-accessibility` (audit and journeys)
- **Depends on:** [CX-UIB-75](#cx-uib-75); [CX-UIB-68](#cx-uib-68); [CX-UIB-71](#cx-uib-71); [CX-UIB-73](#cx-uib-73)
- **Why not now:** It follows the slices.

> **Review change:** Environment relabelled: the steps verify the BTRSmith Linux frontend in the cloud under tools/virtual-display.sh; macOS evidence is `MAC-UIB-07` (§10 F9).

**Owned paths**

- btrsmith: tests/accessibility/ (new audit and journey scripts)
- btrsmith: src/application/adapters/ label-only fixes (requested from the slice owners if they are in flight)

**Must not touch**

- btrc repository

**Steps**

1. Audit name, role, state and action for 100% of core actionable controls. Fill any gap with the slice owner.
2. Write journey scripts for VoiceOver (Mac, iPhone, iPad), Orca, Narrator and TalkBack.

**Acceptance**

- [ ] The audit reports 100% on Linux. Screen-reader logs come from the MAC packets for each platform.

**Risks**

- Mobile and Windows rows wait for Stage 35.

#### Stage 37: UI10 automation and mobile restoration; UI11 long tail

<a id="cx-uib-77"></a>

##### CX-UIB-77 · UI10: journey script schema, shared harness, stable automation ids, diagnostics and the E32 input-to-presentation observer

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (serial schema) · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-10-automation-diagnostics` (schema, harness, diagnostics); `qualification-p5-journey-drivers` (schema)
- **Depends on:** PLAN:qualification-p5-journey-catalog (Stage 30) → [CL-UIA-04](claude.md#cl-uia-04); PLAN:ui-1-shell-fixture (Stage 31) → [CX-UIA-09](#cx-uia-09); [CX-UIB-22](#cx-uib-22); [CX-UIB-23](#cx-uib-23); [CX-UIB-40](#cx-uib-40)
- **Why not now:** The journey catalog (Stage 30), the shell harness (Stage 31) and the UI8 bridges have not landed.
- **Parallel-safe with:** CX-UIB-83

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/tests/native/gui/shell/ harness files
- src/tests/python/test_native_ui_shell.py
- src/stdlib/GUI/Diagnostics.btrc (new)
- tools/ui_evidence/journeys.py (new)
- btrsmith: tests/journeys/schema/ (new)

**Must not touch**

- per-platform driver directories (CX-UIB-78..82)
- src/compiler/

**Steps**

1. One journey model: steps; expected state queried through btrsmithctl/btrsmith-mcp (AgentOperationChannel); captures through GUI.capture.
2. Expose stable automation ids, and layout, focus and owner diagnostics.
3. The E32 observer: input receipt, command delivery, model update and actual presentation, on a documented monotonic clock mapping, with unavailable timestamps flagged.
4. Write catalog results through tools.qualification ingest.

**Acceptance**

- [ ] The shell harness reports automation ids and accessibility trees for macOS and Linux through one harness.
- [ ] E32 produces distributions of at least 100 samples on Linux. Report per protocol.

**Risks**

- The schema serializes all five drivers.

<a id="cx-uib-78"></a>

##### CX-UIB-78 · macOS journey driver: AX API plus CGEvent, extending the ApplicationJourney and PlayerPan harnesses

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-10-automation-diagnostics` (macOS driver); `qualification-p5-journey-drivers` (macOS)
- **Depends on:** [CX-UIB-77](#cx-uib-77)
- **Why not now:** It follows the schema.
- **Parallel-safe with:** CX-UIB-79, CX-UIB-80, CX-UIB-81, CX-UIB-82

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/tests/native/gui/shell/macos/
- btrsmith: tests/journeys/macos/

**Must not touch**

- the shared harness (CX-UIB-77)

**Steps**

1. Deliver real input with CGEvent and query state with the AX API, against the shell fixture on macos.yml.
2. Run the three seed journeys (search/filter; Settings save/back; open a song, then play/pause) against the installed app on the Mac in MAC-UIB-10.

**Acceptance**

- [ ] The shell-fixture journeys pass on macos.yml (or are rule-skipped where AX trust is missing).
- [ ] Installed-app runs are MAC-UIB-10.

**Risks**

- CGEvent posting needs Accessibility permission (owner).

<a id="cx-uib-79"></a>

##### CX-UIB-79 · Linux journey driver: AT-SPI plus libei/uinput on Wayland and XTest on X11

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-10-automation-diagnostics` (Linux driver); `qualification-p5-journey-drivers` (Linux)
- **Depends on:** [CX-UIB-77](#cx-uib-77); [CL-UIB-03](claude.md#cl-uib-03)
- **Why not now:** It follows the schema and the driver tooling.
- **Parallel-safe with:** CX-UIB-78, CX-UIB-80, CX-UIB-81, CX-UIB-82

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/tests/native/gui/shell/linux/
- btrsmith: tests/journeys/linux/

**Must not touch**

- the shared harness

**Steps**

1. Query with AT-SPI. Inject input with libei on weston and XTest on Xvfb. Run the seed journeys on the shell fixture in the cloud.

**Acceptance**

- [ ] The seed journeys pass on X11 and Wayland, both frontends. The desktop host runs in MAC-UIB-10.

**Risks**

- libei support in weston.

<a id="cx-uib-80"></a>

##### CX-UIB-80 · Windows journey driver: UI Automation plus SendInput

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-10-automation-diagnostics` (Windows driver); `qualification-p5-journey-drivers` (Windows)
- **Depends on:** [CX-UIB-77](#cx-uib-77); [CX-UIB-48](#cx-uib-48)
- **Why not now:** It follows the schema and the UIA providers.
- **Parallel-safe with:** CX-UIB-78, CX-UIB-79, CX-UIB-81, CX-UIB-82

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/tests/native/gui/shell/windows/
- btrsmith: tests/journeys/windows/

**Must not touch**

- the shared harness

**Steps**

1. Query with IUIAutomation and inject with SendInput. Run the seed journeys on windows.yml.

**Acceptance**

- [ ] The seed journeys pass on windows.yml, both frontends (stand-in until hardware exists).

**Risks**

- Input on the runner desktop session.

<a id="cx-uib-81"></a>

##### CX-UIB-81 · iOS journey driver: XCUITest

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-10-automation-diagnostics` (iOS driver); `qualification-p5-journey-drivers` (iOS)
- **Depends on:** [CX-UIB-77](#cx-uib-77); [CX-UIB-56](#cx-uib-56)
- **Why not now:** It follows the schema and the iOS accessibility work.
- **Parallel-safe with:** CX-UIB-78, CX-UIB-79, CX-UIB-80, CX-UIB-82

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/tests/native/gui/shell/ios/
- btrsmith: tests/journeys/ios/

**Must not touch**

- the shared harness

**Steps**

1. An XCUITest bundle that drives the shell fixture and the installed app on the simulator in macos.yml.

**Acceptance**

- [ ] The seed journeys pass on the simulator, both frontends. Devices are MAC-UIB-09.

**Risks**

- Building the XCUITest bundle without an Xcode project.

<a id="cx-uib-82"></a>

##### CX-UIB-82 · Android journey driver: UiAutomator

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-10-automation-diagnostics` (Android driver); `qualification-p5-journey-drivers` (Android)
- **Depends on:** [CX-UIB-77](#cx-uib-77); [CX-UIB-64](#cx-uib-64)
- **Why not now:** It follows the schema and the Android accessibility work.
- **Parallel-safe with:** CX-UIB-78, CX-UIB-79, CX-UIB-80, CX-UIB-81

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- src/tests/native/gui/shell/android/
- btrsmith: tests/journeys/android/

**Must not touch**

- the shared harness

**Steps**

1. A UiAutomator instrumentation APK that drives the fixture and the installed app on the ci.yml emulator job.

**Acceptance**

- [ ] The seed journeys pass on the emulator, both frontends. Devices are MAC-UIB-09.

**Risks**

- Emulator flakiness.

<a id="cx-uib-83"></a>

##### CX-UIB-83 · BTRSmith mobile restoration: the versioned scene checkpoint format and restore logic (serial)

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-10-btrsmith-mobile` (checkpoint); `btrsmith-ui-slice5-mobile-restoration` (checkpoint and restore)
- **Depends on:** [CX-UIB-74](#cx-uib-74); [CX-UIB-70](#cx-uib-70); PLAN:btrsmith-storage-resources → [CL-P2-25](claude.md#cl-p2-25)
- **Why not now:** Slices 1-4 and the adaptive layout have not landed.
- **Parallel-safe with:** CX-UIB-77

**Owned paths**

- btrsmith: src/application/runtime/NavigationHistory.btrc
- btrsmith: src/application/runtime/ApplicationSession.btrc (checkpoint hunk; integrator-serialized)
- btrsmith: src/backend/state/ scene checkpoint (new)

**Must not touch**

- btrsmith: packaging/ (CX-UIB-84 and 85)
- btrc repository

**Steps**

1. Build a checkpoint of at most 64 KiB from NavigationHistory and NavigationLocation identities, the Settings draft and the Player position, kept separate from btrsmith.json and SQLite.
2. Restore after real process death with 0 replayed side effects (DD.md:315). Cover schema upgrade, corrupt checkpoints, missing resources and concurrent activation.

**Acceptance**

- [ ] 100 desktop fresh-process restores on Linux, both frontends, with 0 replayed side effects or cross-scene swaps.

**Risks**

- The ApplicationSession hotspot.

<a id="cx-uib-84"></a>

##### CX-UIB-84 · BTRSmith iOS adaptation and packaging lane: rotation, keyboard occlusion, backgrounding, scene recreation, simulator journeys

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-10-btrsmith-mobile` (iOS); `btrsmith-ui-slice5-mobile-restoration` (iOS lane)
- **Depends on:** [CX-UIB-83](#cx-uib-83); [CX-UIB-57](#cx-uib-57); PLAN:platforms-i2-app-packaging → [CX-P2-40](#cx-p2-40)
- **Why not now:** I2 packaging (Stage 29) and the iOS track have not landed.
- **Parallel-safe with:** CX-UIB-85

> **Review change:** macOS/iOS runs move to owner sessions: BTRSmith has no macOS runner outside tagged releases (D26) (§10 F7).

**Owned paths**

- btrsmith: packaging/ios/

**Must not touch**

- btrsmith: packaging/android/

**Steps**

1. Make Library, Settings and Player survive rotation, keyboard occlusion, backgrounding and scene recreation. Run the installed-app journeys on the simulator.

**Acceptance**

- [ ] Builds for iOS in the cloud for both frontends; simulator journeys with 100 recreation cycles run on the Mac in MAC-UIB-09's session (BTRSmith has no macOS CI before tagged releases, D26).

**Risks**

- BTRSmith has no CI before Stage 38, so iOS runs need a dispatch in BTRSmith or the Mac.

<a id="cx-uib-85"></a>

##### CX-UIB-85 · BTRSmith Android adaptation and packaging lane: Activity recreation, process death, insets, emulator journeys

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub Linux KVM runner (Android emulator) · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-10-btrsmith-mobile` (Android); `btrsmith-ui-slice5-mobile-restoration` (Android lane)
- **Depends on:** [CX-UIB-83](#cx-uib-83); [CX-UIB-65](#cx-uib-65); PLAN:platforms-a2-packaging-16k → [CX-P2-45](#cx-p2-45); [CL-R-48](claude.md#cl-r-48)
- **Why not now:** A2 packaging (Stage 29) and the Android track have not landed.
- **Parallel-safe with:** CX-UIB-84

> **Review change:** Its BTRSmith run ids come from `CL-R-48`'s emulator and Windows jobs (§10 F7).

> **Review change:** Environment relabelled `linux+kvm-ci`: the Android emulator runs on GitHub's ubuntu runners with KVM (host-android.yml, or `CL-UIB-14`'s Android job), never in the cloud container (§10 F9).

**Owned paths**

- btrsmith: packaging/android/

**Must not touch**

- btrsmith: packaging/ios/

**Steps**

1. Handle Activity recreation, process death, insets and rotation. Run the installed-app journeys on the emulator (APK and AAB, per D26).

**Acceptance**

- [ ] Emulator journeys pass, both frontends, with 100 recreation cycles. Devices are MAC-UIB-09.

**Risks**

- Emulator speed.

<a id="cx-uib-86"></a>

##### CX-UIB-86 · UI10 qualification aggregation: 470/470 case slots, 1,620/1,620 operation slots, 50/50 core families, final parity docs

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `ui-10-qualification` (evidence aggregation and docs)
- **Depends on:** [CX-UIB-78](#cx-uib-78); [CX-UIB-79](#cx-uib-79); [CX-UIB-80](#cx-uib-80); [CX-UIB-81](#cx-uib-81); [CX-UIB-82](#cx-uib-82); [CX-UIB-84](#cx-uib-84); [CX-UIB-85](#cx-uib-85); [CX-UIB-49](#cx-uib-49); [CX-UIB-57](#cx-uib-57); [CX-UIB-65](#cx-uib-65); [CX-UIB-68](#cx-uib-68); [CX-UIB-71](#cx-uib-71); [CX-UIB-72](#cx-uib-72); [CX-UIB-74](#cx-uib-74); [MAC-UIB-09](owner.md#mac-uib-09); [MAC-UIB-10](owner.md#mac-uib-10)
- **Why not now:** All tracks and slices must finish first.
- **Parallel-safe with:** CX-UIB-93, CX-UIB-94

> **Writer note:** Read "1,620 of 1,620 operation slots" as "every slot of every ui-operation release in force" (2026-09-21, plus the `CX-UIA-05`, `CX-UIA-21`, `CX-UIA-25` and `CL-UIB-08` releases; `CX-UIA-02` freezes none) (§7 Q35, §9 item 9).

**Owned paths**

- docs/design/native-ui-parity.md
- docs/design/native-ui-api-inventory.md
- the UI0 catalog result shards (final classification)

**Must not touch**

- tools/qualification/ (Claude)
- PLAN.md

**Steps**

1. Resolve every slot as passed, failed, adapted or unavailable, each explicit, with its evidence link.
2. Update the 300-cell matrix and every milestone state. Publish captures, accessibility trees, native-input results, resource traces and unavailable coverage.
3. Keep two rows open: numeric goals on the named matrix (Stage 41), and minimum/current OS and SDK-update evidence (Stage 42).

**Acceptance**

- [ ] make qualification-report shows 470 of 470 case slots and 1,620 of 1,620 operation slots resolved, and 50 of 50 core families passed or adapted, with 0 missing core journeys.
- [ ] The UI10 row stays open until Stage 42.

**Risks**

- Any physical row awaiting hardware stays visible.

<a id="cx-uib-87"></a>

##### CX-UIB-87 · UI11 pickers on the desktop: date/time and color/font contracts with AppKit and GTK (or portal) providers

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-11-pickers-n51-n52` (contract plus macOS and Linux)
- **Depends on:** [CL-UIB-08](claude.md#cl-uib-08); [CL-UIB-18](claude.md#cl-uib-18); [CX-UIB-95](#cx-uib-95) (ready)
- **Why not now:** The UI7 contract (L4) has not landed.
- **Parallel-safe with:** CX-UIB-89, CX-UIB-91, CX-UIB-93

> **Review change:** Stacks on `CX-UIB-95`, whose interfaces and factory lines `CL-UIB-18` approves; this packet adds providers only (§10 C10).

**Owned paths**

- src/stdlib/GUI/MacOS/{MacOSDatePicker,MacOSColorPanel,MacOSFontPanel}.btrc (new)
- src/stdlib/GUI/Linux/{LinuxDatePicker,LinuxColorPicker,LinuxFontPicker}.btrc (new)
- src/tests/native/gui/extended/pickers/

**Must not touch**

- existing Stage 34 declarations, and the UI11 interface and factory files (CX-UIB-95)
- src/compiler/
- src/stdlib/GUI/{IDatePicker,IColorPicker,IFontPicker}.btrc (CX-UIB-95's base branch, approved by CL-UIB-18)

**Steps**

1. Locale, calendar and timezone policy; typed results; preview and cancel. NSDatePicker, NSColorPanel and NSFontPanel; GtkCalendar, GtkColorDialog and GtkFontDialog, or a documented SDL adaptation.

**Acceptance**

- [ ] 2 of 2 families are dispositioned on desktop, both frontends (macos.yml and Linux). Report per protocol.

**Risks**

- The SDL route needs custom pickers or an adaptation.

<a id="cx-uib-88"></a>

##### CX-UIB-88 · UI11 pickers on Windows, iOS and Android: providers or reviewed adaptations

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-11-pickers-n51-n52` (Windows, iOS, Android)
- **Depends on:** [CX-UIB-87](#cx-uib-87); [CX-UIB-47](#cx-uib-47); [CX-UIB-55](#cx-uib-55); [CX-UIB-63](#cx-uib-63)
- **Why not now:** The new-platform tracks have not landed.
- **Parallel-safe with:** CX-UIB-90, CX-UIB-92, CX-UIB-94

**Owned paths**

- src/stdlib/GUI/{Windows,IOS,Android}/ picker owners (new files only)
- src/tests/native/gui/extended/pickers/{windows,ios,android}/

**Must not touch**

- other track files
- src/compiler/

**Steps**

1. Win32 date/time picker, ChooseColor and ChooseFont; UIDatePicker, UIColorPickerViewController and UIFontPickerViewController; MaterialDatePicker or a platform dialog adaptation.

**Acceptance**

- [ ] Dispositions recorded for every platform, qualified where supported, both frontends, in each platform's CI job. Report per protocol.

**Risks**

- Material components need an AAR (CL-UIB-11).

<a id="cx-uib-89"></a>

##### CX-UIB-89 · UI11 rich text and web view on the desktop: NSTextView with WKWebView, and GtkTextView with WebKitGTK

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-11-rich-web-n53-n54` (contract plus macOS and Linux)
- **Depends on:** [CL-UIB-08](claude.md#cl-uib-08); [CL-UIB-03](claude.md#cl-uib-03) (WebKitGTK); [CL-UIB-18](claude.md#cl-uib-18); [CX-UIB-95](#cx-uib-95) (ready)
- **Why not now:** Stage 34 is not closed, and WebKitGTK is not packaged.
- **Parallel-safe with:** CX-UIB-87, CX-UIB-91, CX-UIB-93

> **Review change:** Stacks on `CX-UIB-95`, whose interfaces and factory lines `CL-UIB-18` approves; this packet adds providers only (§10 C10).

**Owned paths**

- src/stdlib/GUI/MacOS/{MacOSRichTextView,MacOSWebView}.btrc (new)
- src/stdlib/GUI/Linux/{LinuxRichTextView,LinuxWebView}.btrc (new)
- src/tests/native/gui/extended/rich-web/

**Must not touch**

- src/compiler/
- src/stdlib/GUI/{IRichTextView,IWebView}.btrc (CX-UIB-95's base branch, approved by CL-UIB-18)

**Steps**

1. Spans, links and attachments; navigation policy; ownership of script messages; load, error and cancel; accessible focus traversal; bounded document resources.

**Acceptance**

- [ ] 2 of 2 families qualified on desktop, both frontends, or OS restrictions recorded. Report per protocol.

**Risks**

- WebKitGTK size in the dev shell.

<a id="cx-uib-90"></a>

##### CX-UIB-90 · UI11 rich text and web view on Windows, iOS and Android: RichEdit with WebView2, UITextView with WKWebView, Spannable with WebView

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-11-rich-web-n53-n54` (Windows, iOS, Android)
- **Depends on:** [CX-UIB-89](#cx-uib-89); [CX-UIB-48](#cx-uib-48); [CX-UIB-56](#cx-uib-56); [CX-UIB-64](#cx-uib-64); PLAN:platforms-p4-dependency-crossbuild (WebView2 packaging) → [CL-P2-17](claude.md#cl-p2-17)
- **Why not now:** The new-platform tracks and P4 packaging have not landed.
- **Parallel-safe with:** CX-UIB-88, CX-UIB-92, CX-UIB-94

**Owned paths**

- src/stdlib/GUI/{Windows,IOS,Android}/ rich-text and web owners (new files only)
- src/tests/native/gui/extended/rich-web/{windows,ios,android}/

**Must not touch**

- src/compiler/

**Steps**

1. Implement each provider, or record an explicit OS restriction. WebView2 is a COM API (CL-UIB-10).

**Acceptance**

- [ ] Dispositions are recorded per platform, both frontends. Report per protocol.

**Risks**

- The WebView2 runtime is absent on some runners.

<a id="cx-uib-91"></a>

##### CX-UIB-91 · UI11 print, preview and system media transport on the desktop: NSPrintOperation, GTK/portal Print, MPNowPlayingInfoCenter, MPRIS

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-11-print-media-n55-n57` (contract plus macOS and Linux)
- **Depends on:** [CL-UIB-08](claude.md#cl-uib-08); [CL-UIB-18](claude.md#cl-uib-18); [CX-UIB-95](#cx-uib-95) (ready)
- **Why not now:** Stage 34 is not closed (the item depends on UI3, and the stage order puts it in 37).
- **Parallel-safe with:** CX-UIB-87, CX-UIB-89, CX-UIB-93

> **Review change:** Stacks on `CX-UIB-95`, whose interfaces and factory lines `CL-UIB-18` approves; this packet adds providers only (§10 C10).

**Owned paths**

- src/stdlib/GUI/MacOS/{MacOSPrintService,MacOSNowPlaying}.btrc (new)
- src/stdlib/GUI/Linux/{LinuxPrintService,LinuxMpris}.btrc (new)
- src/tests/native/gui/extended/print-media/

**Must not touch**

- src/compiler/
- src/stdlib/GUI/{IPrintService,INowPlaying}.btrc (CX-UIB-95's base branch, approved by CL-UIB-18)

**Steps**

1. Print and preview flows with cancellation and a share-sheet adaptation. Now-playing metadata and actions that share the product commands.

**Acceptance**

- [ ] 2 of 2 families dispositioned on desktop, both frontends. The N57 promotion decision is recorded. Report per protocol.

**Risks**

- The P5 product decision on N57.

<a id="cx-uib-92"></a>

##### CX-UIB-92 · UI11 print and media transport on Windows, iOS and Android: print dialogs, SMTC or an adaptation, UIPrintInteractionController, PrintManager, MediaSession

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-11-print-media-n55-n57` (Windows, iOS, Android)
- **Depends on:** [CX-UIB-91](#cx-uib-91); [CX-UIB-47](#cx-uib-47); [CX-UIB-55](#cx-uib-55); [CX-UIB-63](#cx-uib-63)
- **Why not now:** The new-platform tracks have not landed.
- **Parallel-safe with:** CX-UIB-88, CX-UIB-90, CX-UIB-94

**Owned paths**

- src/stdlib/GUI/{Windows,IOS,Android}/ print and now-playing owners (new files only)
- src/tests/native/gui/extended/print-media/{windows,ios,android}/

**Must not touch**

- src/compiler/

**Steps**

1. Implement each provider, or record an adaptation. SMTC is WinRT; if WinRT activation is not available, record an adaptation.

**Acceptance**

- [ ] Dispositions are recorded per platform, both frontends. Report per protocol.

**Risks**

- WinRT interop is out of scope for the current ownership plan.

<a id="cx-uib-93"></a>

##### CX-UIB-93 · UI11 N58 advanced data editing on the UI6 collections: reorderable sections, drag handles, inline editors, hierarchical tables

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `ui-11-data-docs-help-n58-n60` (N58 contract plus macOS and Linux)
- **Depends on:** [CL-UIB-07](claude.md#cl-uib-07); [CL-UIB-08](claude.md#cl-uib-08); [CL-UIB-18](claude.md#cl-uib-18); [CX-UIB-95](#cx-uib-95) (ready)
- **Why not now:** The UI6 and UI8 landings (Stage 34) have not happened.
- **Parallel-safe with:** CX-UIB-87, CX-UIB-89, CX-UIB-91, CX-UIB-86

> **Review change:** Stacks on `CX-UIB-95`, whose interfaces and factory lines `CL-UIB-18` approves; this packet adds providers only (§10 C10).

**Owned paths**

- src/stdlib/GUI/{MacOS,Linux}/ editable-collection owners (new files only)
- src/tests/native/gui/extended/data-editing/

**Must not touch**

- Stage 34 collection files (extend, do not edit)
- src/compiler/
- src/stdlib/GUI/IEditableCollection.btrc (CX-UIB-95's base branch, approved by CL-UIB-18)

**Steps**

1. Reordering, inline editing and hierarchical rows, preserving accessible identity and keyboard alternatives.

**Acceptance**

- [ ] N58 qualified on macOS and Linux, both frontends. Report per protocol.

**Risks**

- Extends contract files that are already frozen.

<a id="cx-uib-94"></a>

##### CX-UIB-94 · UI11 N59 document surfaces and N60 help/services, plus Windows, iOS and Android dispositions for N58-N60

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 (UI11) · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `ui-11-data-docs-help-n58-n60` (N59, N60 and new-platform dispositions)
- **Depends on:** [CX-UIB-93](#cx-uib-93); [CX-UIB-46](#cx-uib-46); [CX-UIB-54](#cx-uib-54); [CX-UIB-62](#cx-uib-62); [CL-UIB-18](claude.md#cl-uib-18); [CX-UIB-95](#cx-uib-95) (ready)
- **Why not now:** Needs N58 and the new-platform collection tracks.
- **Parallel-safe with:** CX-UIB-88, CX-UIB-90, CX-UIB-92

> **Review change:** Stacks on `CX-UIB-95`, whose interfaces and factory lines `CL-UIB-18` approves; this packet adds providers only (§10 C10).

**Owned paths**

- src/stdlib/GUI/{MacOS,Linux,Windows,IOS,Android}/ document-surface and help owners (new files only)
- src/tests/native/gui/extended/docs-help/

**Must not touch**

- src/compiler/
- src/stdlib/GUI/{IDocumentSurface,IHelpService}.btrc (CX-UIB-95's base branch, approved by CL-UIB-18)

**Steps**

1. Accessible chart and timeline host contracts that keep BTRSmith's custom renderers. Context help and services, and typed platform extensions with explicit unsupported results.
2. Record N58-N60 dispositions for Windows, iOS and Android.

**Acceptance**

- [ ] 3 of 3 families are dispositioned on every platform. The final report keeps every missing or OS-restricted operation. Report per protocol.

**Risks**

- The broadest UI11 packet; split it further by family if needed.

<a id="cx-uib-95"></a>

##### CX-UIB-95 · UI11 contract drafts (docs-only), then the approved interfaces, factory lines and stubs as the base branch for CX-UIB-87…94

- **Owner:** Codex · **Group:** UIB · **Stage:** Stage 37 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `ui-11-pickers-n51-n52#contract`; `ui-11-rich-web-n53-n54#contract`; `ui-11-print-media-n55-n57#contract`; `ui-11-data-docs-help-n58-n60#contract`
- **Depends on:** [CL-UIB-08](claude.md#cl-uib-08)
- **Why not now:** UI11 follows the Stage 34 freeze (CL-UIB-08).

> **Review change:** New (§10 C10). UI11 added portable contracts after the Stage 34 freeze with no approval packet, and four concurrent packets needed the frozen `GUI.btrc`/`IApplication.btrc`.

**Owned paths**

- docs/design/ui-contracts/drafts/ui11/ (new; docs-only drafts of IDatePicker, IColorPicker, IFontPicker, IRichTextView, IWebView, IPrintService, INowPlaying, IEditableCollection, IDocumentSurface, IHelpService)
- after CL-UIB-18 approves: src/stdlib/GUI/{those ten}.btrc (new) and the UI11 factory lines in src/stdlib/GUI/GUI.btrc and IApplication.btrc (UI11 factories only)
- typed-unsupported stubs for the ten interfaces in providers that lack them (stub-only commits)

**Must not touch**

- docs/design/plan-reference.md
- existing Stage 34 declarations
- `src/compiler/**`

**Steps**

1. Draft the ten interfaces as docs only, with operation ids, E-case links and the five-platform maps; open the draft PR (docs-only until approval).
2. After CL-UIB-18 approves, commit the interfaces, the factory lines and the stubs exactly as ui11-approved.md says. This branch is the base CX-UIB-87…94 stack on; CL-UIB-17 lands it with them.

**Acceptance**

- [ ] CL-UIB-18 records 0 unresolved blocking findings on the drafts.
- [ ] The interfaces match ui11-approved.md; every provider compiles with typed-unsupported stubs; ci.yml, macos.yml and windows.yml green on the draft PR (run ids).

#### Stage 38: CI tiers, macOS native suite, BTRSmith CI, cross-target benchmarks

<a id="cx-r-11"></a>

##### CX-R-11 · P6 build-bench target adapters for Windows, iOS and Android build drivers

- **Owner:** Codex · **Group:** R · **Stage:** 38 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p6-build-bench-targets`
- **Depends on:** [CL-R-40](claude.md#cl-r-40); ext:platforms-w2-packaging, platforms-i2-app-packaging, platforms-a2-packaging-16k (Stage 29) → [CX-P2-35](#cx-p2-35), [CX-P2-40](#cx-p2-40), [CX-P2-45](#cx-p2-45)
- **Why not now:** Needs the TargetDriver core (CL-R-40) and the platform packaging.
- **Parallel-safe with:** CX-R-12

**Owned paths**

- tools/bench/targets/windows.py
- tools/bench/targets/ios.py
- tools/bench/targets/android.py
- src/tests/python/test_bench_target_adapters.py
- tools/runbook/presets/p6-build-ios.toml
- tools/runbook/presets/p6-build-android.toml
- tools/runbook/presets/p6-build-windows.toml

**Must not touch**

- tools/budget_bench.py
- `tools/qualification/**`
- `src/compiler/**`

**Steps**

1. Branch codex/cx-r-11.
2. Implement TargetDriver per platform: the Windows packager; the iOS app bundle, simulator install and launch; Android Gradle (or the direct path), adb install and relaunch.
3. Dry runs on hosted runners.

**Acceptance**

- [ ] Each adapter's dry run emits records that `python3 -m tools.qualification ingest --budget-bench` accepts, with platform and variant
- [ ] Windows adapter on windows-latest, iOS on the macOS runner (simulator variant), Android on a Linux KVM runner

**Risks**

- Gradle cold start is timed separately (P6 rule).

#### Stage 39: P5 journeys on installed products and the macOS MVP closure

<a id="cx-r-05"></a>

##### CX-R-05 · MVP Library screen closure prep: #16 library milestone, #7 scroll 5 ms mean and page-fetch spikes, #3 hover and tooltip captures, plus the mvp-library preset

- **Owner:** Codex · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `btrsmith-macos-mvp-automatable`
- **Depends on:** ext:ui-6-btrsmith-library and btrsmith-ui-slice3-library (Stage 36) → [CX-UIB-71](#cx-uib-71), [CX-UIB-72](#cx-uib-72); ext:qualification-p5-journey-drivers (Stage 37) → CX-UIB-77…82; [CL-R-37](claude.md#cl-r-37)
- **Why not now:** The Library screen is migrated in Stage 36; journeys come from Stage 37.
- **Parallel-safe with:** CX-R-06, CX-R-07

> **Review change:** macOS evidence moves to `MAC-R-10`: BTRSmith has no macOS runner outside tagged releases (D26) (§10 F7).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `btrsmith:src/frontend/library/**`
- `btrsmith:src/backend/catalog/**`
- btrsmith:tests/macos/LibraryScrollProfile.btrc
- btrsmith:tests/macos/AlbumHoverJourney.btrc
- btrsmith:tests/macos/LibrarySession.btrc
- tools/runbook/presets/mvp-library.toml

**Must not touch**

- btrc `src/compiler/**`
- `src/stdlib/GUI/**` (provider packets)
- `btrsmith:src/frontend/player/**`

**Steps**

1. Branch codex/cx-r-05; draft PRs in BTRSmith and btrc for the preset.
2. #16: automate every format, filter, ordering and stress path.
3. #7: fix page-fetch spikes in catalog paging; make the scroll profile report the mean per batch.
4. #3: hover and tooltip capture through the compositor for every hoverable control.
5. The preset produces the capture sheets that MAC-R-10 runs. GUI provider defects go to the GUI provider packet; compiler defects go to Claude.

**Acceptance**

- [ ] #16 journeys pass on Linux CI (portable parts) and build in the cloud; macOS compile and run in MAC-R-10
- [ ] MAC-R-10: LibraryScrollProfile mean ≤5 ms with no page-fetch spikes; hover captures complete
- [ ] Evidence drafts ready to post

**Risks**

- The real catalog fixtures are private and Mac-only.

<a id="cx-r-06"></a>

##### CX-R-06 · MVP Player closure prep: #17 transport, shortcuts, speed, metronome, cycles, four skins; #2 200 FPS framebuffer-only swapchain and GPU pacing; #19 fretboard hints and landing glow

- **Owner:** Codex · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `btrsmith-macos-mvp-automatable`
- **Depends on:** ext:ui-9-btrsmith-player and btrsmith-ui-slice4-player (Stage 36) → [CX-UIB-73](#cx-uib-73), [CX-UIB-74](#cx-uib-74); ext:qualification-p5-journey-drivers (Stage 37) → CX-UIB-77…82; [CL-R-37](claude.md#cl-r-37)
- **Why not now:** The Player screen is migrated in Stage 36; journeys come from Stage 37.
- **Parallel-safe with:** CX-R-05, CX-R-07

> **Review change:** macOS evidence moves to `MAC-R-10`: BTRSmith has no macOS runner outside tagged releases (D26) (§10 F7).

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `btrsmith:src/frontend/player/**`
- `btrsmith:src/frontend/visualization/**`
- btrsmith:tests/macos/PlayerScreen.btrc
- btrsmith:tests/macos/PlayerKeys.btrc
- btrsmith:tests/macos/PlayerGPU.btrc
- tools/runbook/presets/mvp-player.toml

**Must not touch**

- btrc `src/compiler/**`
- `src/stdlib/GPU/**`
- `btrsmith:src/frontend/library/**`

**Steps**

1. Branch codex/cx-r-06.
2. #17: an automated journey per control and skin.
3. #2: a frame-pacing probe that records the present-interval distribution.
4. #19: verify defaults and edited values through btrsmith.json edits plus captures.
5. Write the preset.

**Acceptance**

- [ ] #17 journeys pass on both frontends (Linux in the cloud; macOS compile and run in MAC-R-10)
- [ ] MAC-R-10: frame-time distribution at the 200 FPS target; #19 captures match the defaults and edits

**Risks**

- 200 FPS needs a real ProMotion panel (devices.toml mac-builtin-display-120hz is unverified).

<a id="cx-r-07"></a>

##### CX-R-07 · MVP Settings and visual acceptance prep: #18 btrsmith.json as the source of truth for every UX constant and string; #6 side-by-side capture sheets against the mocks and instrument art

- **Owner:** Codex · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `btrsmith-macos-mvp-automatable`
- **Depends on:** ext:ui-4-btrsmith-settings, ui-5-btrsmith-adaptive (Stage 36) → [CX-UIB-68](#cx-uib-68), [CX-UIB-69](#cx-uib-69), [CX-UIB-70](#cx-uib-70); [CL-R-37](claude.md#cl-r-37)
- **Why not now:** The Settings screens are migrated in Stage 36.
- **Parallel-safe with:** CX-R-05, CX-R-06

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `btrsmith:src/frontend/settings/**`
- `btrsmith:src/backend/state/**`
- btrsmith:docs/UXConstants.md
- btrsmith:docs/product/PlayerConfiguration.md
- `btrsmith:tools/verify/**`
- tools/runbook/presets/mvp-settings.toml

**Must not touch**

- btrc `src/**`
- `btrsmith:src/frontend/player/**`

**Steps**

1. Branch codex/cx-r-07.
2. #18: a test enumerates every UX constant and string in UXConstants.md, edits it in btrsmith.json and observes the effect.
3. #6: tools/verify produces Library, Player and Settings capture sheets beside docs/product/PlayerScreenReference.png and the approved mocks, covering all four skins and the instrument art.
4. Record deliberate deviations (D25).

**Acceptance**

- [ ] #18 enumeration test passes on both frontends (Linux)
- [ ] Capture sheets generated on the macOS runner (headless parts) and on the Mac (MAC-R-10)
- [ ] The owner's side-by-side review for #6 is scheduled in MAC-R-10

**Risks**

- Licensed skin art outside Apple platforms (D25).

<a id="cx-r-08"></a>

##### CX-R-08 · P5 journeys on installed products, macOS and Linux: driver runs, ledger ingest, Linux stand-in on hosted runners, real-desktop runbook

- **Owner:** Codex · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p5-runs-macos-linux`
- **Depends on:** ext:qualification-p5-journey-drivers and ui-10-automation-diagnostics (Stage 37) → CX-UIB-77…82; [CL-R-37](claude.md#cl-r-37); [CL-R-38](claude.md#cl-r-38)
- **Why not now:** Needs the Stage 37 journey drivers.
- **Parallel-safe with:** CX-R-09, CX-R-10, CL-R-47

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `btrsmith:tests/journeys/linux/**`
- tools/runbook/presets/p5-macos.toml
- docs/qualification/journeys/linux-desktop.md
- fragment (not held): ci/tiers.toml fragment (submitted to the integrator)

**Must not touch**

- `src/compiler/**`
- `.github/workflows/**` (fragment only)
- `tools/qualification/**` (Claude)

**Steps**

1. Branch codex/cx-r-08.
2. Run the drivers against installed packages: macos-app-bundle-smoke and the installed .app; linux-install-smoke and the Nix-installed product.
3. Linux on hosted runners under Xvfb and lavapipe is stand-in evidence; write the FRACTAL-NORTH real Wayland/X11 plus AT-SPI runbook.
4. Classify every journey slot as passed, adapted, os-restricted or missing.

**Acceptance**

- [ ] Linux hosted run classifies every journey slot, with 0 missing core journeys or each missing one tied to an owner packet
- [ ] Ledger records ingested; the p5-macos preset dry-runs
- [ ] Linux desktop runbook ready for MAC-R-12

**Risks**

- Virtual displays don't prove real IME or AT; recorded separately.

<a id="cx-r-09"></a>

##### CX-R-09 · P5 Windows journeys on hosted x64 and ARM64 runners, plus the one-command physical Windows script (tooling-windows-physical prep)

- **Owner:** Codex · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud + GitHub Windows runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p5-runs-windows`; `tooling-windows-physical`
- **Depends on:** `ext:ui-win-*` (Stage 35) → CX-UIB-42…49; ext:platforms-w2-packaging (Stage 29) → [CX-P2-35](#cx-p2-35); ext:qualification-p5-journey-drivers (Stage 37) → CX-UIB-77…82; [CL-R-39](claude.md#cl-r-39)
- **Why not now:** Needs the Windows UI track, W2 packaging and the journey drivers.
- **Parallel-safe with:** CX-R-08, CX-R-10

**Owned paths**

- tools/devices/windows/run.ps1
- tools/devices/windows/README.md
- docs/qualification/journeys/windows.md

**Must not touch**

- `src/compiler/**`
- `src/runtime/windows/**`
- `src/stdlib/GUI/Windows/**` (provider packet)

**Steps**

1. Branch codex/cx-r-09.
2. Run journeys against the installed package on windows-latest and windows-11-arm; label them stand-in.
3. `pwsh tools/devices/windows/run.ps1 -Journeys all` is the physical one-command script, validated on the hosted runner.
4. Physical rows stay awaiting hardware (D8).

**Acceptance**

- [ ] Hosted x64 and ARM64 runs ingested with stand_in provenance
- [ ] run.ps1 completes on windows-latest

**Risks**

- windows-11-arm availability is an unverified assumption.

<a id="cx-r-10"></a>

##### CX-R-10 · P5 iOS-simulator and Android-emulator journey lanes (stand-in) plus device scripts and the pinned-run presets

- **Owner:** Codex · **Group:** R · **Stage:** 39 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p5-runs-ios`; `qualification-p5-runs-android`
- **Depends on:** `ext:ui-ios-*` and `ui-android-*` (Stage 35) → CX-UIB-50…57, CX-UIB-58…65; ext:platforms-i2-app-packaging and platforms-a2-packaging-16k (Stage 29) → [CX-P2-40](#cx-p2-40), [CX-P2-45](#cx-p2-45); ext:ui-10-btrsmith-mobile and qualification-p5-journey-drivers (Stage 37) → [CX-UIB-84](#cx-uib-84), [CX-UIB-85](#cx-uib-85), CX-UIB-77…82; [CL-R-39](claude.md#cl-r-39)
- **Why not now:** Needs the mobile UI tracks, mobile packaging and the journey drivers.
- **Parallel-safe with:** CX-R-08, CX-R-09

**Owned paths**

- `tools/devices/ios/**`
- `tools/devices/android/**`
- tools/runbook/presets/p5-ios-simulators.toml
- tools/runbook/presets/p5-android-emulators.toml
- docs/qualification/journeys/ios.md
- docs/qualification/journeys/android.md

**Must not touch**

- `src/compiler/**`
- `src/stdlib/GUI/IOS/**`, `GUI/Android/**` (provider packets)

**Steps**

1. Branch codex/cx-r-10.
2. iOS simulator journeys on macOS runners (runner Xcode, stand-in).
3. Android API 29, current API and 16 KiB-page emulators on Linux KVM runners.
4. devicectl and adb device scripts; presets for the pinned Xcode 27A266a runs on the Mac.

**Acceptance**

- [ ] Simulator and emulator journey runs ingested with stand_in provenance
- [ ] Device scripts dry-run; presets validate

**Risks**

- Hosted runners lack Xcode 27A266a (open question 9).

#### Stage 40: Physical instrument, listening and latency sessions

<a id="cx-r-01"></a>

##### CX-R-01 · Audio loopback latency rig, macOS and Linux: btrc program plus analyzer (≥100 round-trip samples, p50/p95/p99, method recorded)

- **Owner:** Codex · **Group:** R · **Stage:** 40 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** yes · **Estimate:** 8 agent-hours
- **PLAN items:** `tooling-audio-loopback-rig`; `qualification-p6-audio-latency-rig`
- **Depends on:** none
- **Parallel-safe with:** CX-R-03, CL-R-01, CL-R-02, CL-R-04, CL-R-36, CL-R-37

**Owned paths**

- tools/audio_rig/__init__.py
- tools/audio_rig/LoopbackLatency.btrc
- tools/audio_rig/analyze.py
- tools/audio_rig/run_session.sh
- tools/audio_rig/README.md
- src/tests/python/test_audio_rig.py

**Must not touch**

- `src/compiler/**`
- `src/language/**`
- `src/runtime/c/**`
- `src/stdlib/Audio/**` (provider changes are separate provider packets)
- `.github/workflows/**`
- PLAN.md
- docs/design/plan-reference.md

**Steps**

1. Work on branch codex/cx-r-01 and open a draft PR to main for CI; never merge.
2. LoopbackLatency.btrc uses Library.Audio (RealtimeAudio, AudioDevice) to open duplex on a named device, emit an MLS or chirp burst train, and capture input.
3. analyze.py cross-correlates the bursts for round-trip latency and records sample rate, negotiated buffers, device name and method. Callback duration is never counted as latency.
4. run_session.sh \<platform> is the one-command owner session: it checks the device, takes ≥100 samples and writes a ledger-format JSON record.
5. Unit-test the analyzer on synthetic signals with known delays. Any compiler or runtime defect becomes a Claude request.

**Acceptance**

- [ ] `python3 -m pytest src/tests/python/test_audio_rig.py -q` passes (delays of 64-4,096 samples recovered within ±1 sample)
- [ ] LoopbackLatency.btrc transpiles warning-free through both compilers and builds with strict C11 on Linux; macos.yml compiles it on the draft PR
- [ ] The record JSON parses as a tools.qualification ledger record
- [ ] PR body: commits, test counts, CI run ids, deferrals

**Risks**

- Pulled forward under D27(c).
- No audio device on hosted runners, so the real run happens only in MAC-R-13.
- If the ledger lacks a latency field, file a Claude request against tools/qualification/schema.py.

<a id="cx-r-02"></a>

##### CX-R-02 · Latency rig backends and session scripts for Windows (WASAPI), iOS and Android (AAudio)

- **Owner:** Codex · **Group:** R · **Stage:** 40 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `tooling-audio-loopback-rig`; `qualification-p6-audio-latency-rig`
- **Depends on:** [CX-R-01](#cx-r-01); ext:platforms-w2-wasapi, platforms-i2-audio, platforms-a2-aaudio (Stage 29) → [CX-P2-32](#cx-p2-32), [CX-P2-38](#cx-p2-38), [CX-P2-43](#cx-p2-43)
- **Why not now:** Needs the Windows, iOS and Android audio providers (Stage 29).
- **Parallel-safe with:** CX-R-12

**Owned paths**

- `tools/audio_rig/windows/**`
- `tools/audio_rig/ios/**`
- `tools/audio_rig/android/**`
- docs/qualification/sessions/windows.md
- docs/qualification/sessions/ios.md
- docs/qualification/sessions/android.md

**Must not touch**

- `src/compiler/**`
- `src/stdlib/Audio/**` providers
- `src/runtime/c/**`
- `.github/workflows/**`

**Steps**

1. Branch codex/cx-r-02; draft PR to main.
2. Package the rig per platform: a Windows executable, an iOS app for simulator and device, an Android APK; add one-command device scripts.
3. Self-test with software loopback where the platform allows it.

**Acceptance**

- [ ] Windows build and analyzer self-test on windows-latest; iOS simulator run on the macOS runner; Android emulator run on a Linux KVM runner
- [ ] Session checklists ready for MAC-R-13; physical runs stay awaiting hardware

**Risks**

- Hosted runners have no audio hardware; only software loopback is possible there.

<a id="cx-r-03"></a>

##### CX-R-03 · Stage 40 session kit for macOS: checklists for btrsmith #4, #5, #21, #22, signed listening/route/visual record template, latency and 2-hour soak procedures

- **Owner:** Codex · **Group:** R · **Stage:** 40 · **Environment:** Linux cloud · **Start now:** yes · **Estimate:** 5 agent-hours
- **PLAN items:** `qualification-p5-physical-audio-visual`; `btrsmith-macos-mvp-physical`
- **Depends on:** none
- **Parallel-safe with:** CX-R-01, CL-R-01, CL-R-02

**Owned paths**

- docs/qualification/sessions/README.md
- docs/qualification/sessions/macos.md
- docs/qualification/sessions/record-template.json
- src/tests/python/test_session_records.py

**Must not touch**

- `src/**`
- `tools/qualification/**` (Claude)
- PLAN.md

**Steps**

1. Branch codex/cx-r-03; draft PR to main.
2. Per issue: exact steps, expected observations and sign-off fields. #4 amp/cab models and auto-switching; #5 Settings input test, monitoring, note feedback, full journey; #21 autoplay on a real click and trackpad scroll feel; #22 tuner and note scoring with a real guitar.
3. Route-change and visual records; the latency session with the rig (≥100 samples); the 2-hour soak; the push-notification text that announces a ready session.
4. A test validates the filled template against the ledger schema.

**Acceptance**

- [ ] test_session_records.py passes
- [ ] A read-only reviewer confirms every P6 audio row and each issue's acceptance text maps to a checklist field

**Risks**

- Allowed under D27(c) as planning; the BTRSmith issue texts may change before Stage 40.

<a id="cx-r-04"></a>

##### CX-R-04 · BTRSmith #4: distinct amp and cabinet DSP models with authored auto-switching under 1 ms

- **Owner:** Codex · **Group:** R · **Stage:** 40 · **Environment:** Linux cloud · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `btrsmith-macos-mvp-physical`
- **Depends on:** [CL-R-01](claude.md#cl-r-01); ext:bucket-5 opening (D1/D25) → (no packet in this plan)
- **Why not now:** D25 keeps the macOS MVP closure in bucket 5 (D1); open question 8 proposes pulling it forward.
- **Parallel-safe with:** CX-R-05

**Owned paths**

- `btrsmith:src/backend/effects/**`
- btrsmith:tests/integration/ (new DSP tests)
- btrsmith:docs/product/ (DSP notes)

**Must not touch**

- btrc `src/**`
- `btrsmith:src/frontend/**`

**Steps**

1. Branch codex/cx-r-04 in BTRSmith; draft PR (CI from CL-R-37).
2. Implement distinct amp and cab models and block-accurate authored switching (crossfade ≤48 samples at 48 kHz).
3. Prove realtime safety through the compiler's realtime analyzer; a compiler gap becomes a Claude request.
4. Write offline render tests on both frontends.

**Acceptance**

- [ ] Offline renders of each model are measurably distinct (spectral distance above a fixed threshold)
- [ ] Switch completes in ≤1 ms in offline tests; realtime proof passes through both frontends
- [ ] `make check source-check` green; the listening approval comes from MAC-R-13

**Risks**

- Product DSP quality is judged by ear; only the owner closes #4.

#### Stage 41: P6 numeric acceptance

<a id="cx-r-12"></a>

##### CX-R-12 · P6 runtime-run orchestration per platform and the UI10 numeric report, using the Stage 34 runtime probes

- **Owner:** Codex · **Group:** R · **Stage:** 41 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p6-runtime-runs`
- **Depends on:** ext:qualification-p6-runtime-probes (Stage 34) → [CX-UIB-38](#cx-uib-38); ext:ui-10-qualification (Stage 37) → [CL-UIB-17](claude.md#cl-uib-17); [CX-R-08](#cx-r-08)
- **Why not now:** Needs the Stage 34 probes and Stage 37 UI10 qualification.
- **Parallel-safe with:** CX-R-11

**Owned paths**

- `tools/devices/runtime/**`
- tools/runbook/presets/p6-runtime-macos.toml
- docs/qualification/p6-runtime.md

**Must not touch**

- `tools/qualification/**` (request schema additions)
- `src/compiler/**`

**Steps**

1. Branch codex/cx-r-12.
2. Drive every P6 runtime row: 20 launches; ≥100 search and navigation actions; 10 minutes of frame data; working set; 100 lifecycle cycles; 30-minute soak; callback p99 and p99.9; close/drain; 100 pause/resume cycles. Emit raw distributions.
3. Generate the UI10 numeric table from the records.

**Acceptance**

- [ ] A Linux hosted dry run produces the record set
- [ ] UI10 numeric table renders from ledger records
- [ ] The macOS preset validates

**Risks**

- Hosted-runner numbers are diagnostic only; qualifying runs are MAC-R-14 and MAC-R-12.

#### Stage 42: P7 release engineering

<a id="cx-r-13"></a>

##### CX-R-13 · Devtools per-target adapters: Windows, iOS (simulator and device) and Android launch/attach and symbolication

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 10 agent-hours
- **PLAN items:** `qualification-p7-devtools-targets`; `tooling-target-debuggers`
- **Depends on:** [CL-R-43](claude.md#cl-r-43)
- **Why not now:** Needs the target debug interface (CL-R-43).
- **Parallel-safe with:** CX-R-14

**Owned paths**

- src/devex/debug/targets/windows.py
- src/devex/debug/targets/ios.py
- src/devex/debug/targets/android.py
- src/tests/debug/test_target_adapters.py
- tools/runbook/presets/p7-debugger-simulators.toml

**Must not touch**

- `src/devex/debug/protocol/**`, `backend/**` (CL-R-43)
- `src/compiler/**`

**Steps**

1. Branch codex/cx-r-13.
2. Windows: lldb or gdb with the MinGW toolchain.
3. iOS: debugserver attach through devicectl, or lldb on the simulator.
4. Android: lldb-server via adb.
5. Symbolicate crashes to .btrc lines.

**Acceptance**

- [ ] A .btrc breakpoint hits and a crash symbolicates on windows-latest, the iOS simulator (macOS runner) and the Android emulator (KVM runner)
- [ ] Device rows go to MAC-R-12 and MAC-R-15

**Risks**

- Windows debugger choice depends on the MinGW/MSVC rows (Stage 24 Q2).

<a id="cx-r-14"></a>

##### CX-R-14 · P7 release artifacts, app half: reproducible unsigned BTRSmith packages per platform with notices, symbols and checksums

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `qualification-p7-release-artifacts`
- **Depends on:** [CL-R-44](claude.md#cl-r-44); ext:btrsmith-package-closure (Stage 28) → [CL-P2-17](claude.md#cl-p2-17); ext:platforms-w2-packaging, platforms-i2-app-packaging, platforms-a2-packaging-16k (Stage 29) → [CX-P2-35](#cx-p2-35), [CX-P2-40](#cx-p2-40), [CX-P2-45](#cx-p2-45)
- **Why not now:** Needs the compiler-bundle reproducibility work and every platform's packaging.
- **Parallel-safe with:** CX-R-13

**Owned paths**

- btrsmith:make/Packaging.mk
- `btrsmith:packaging/**`
- btrsmith:docs/ReproducibleBuild.md

**Must not touch**

- btrc `src/**`
- `btrsmith:src/**`

**Steps**

1. Branch codex/cx-r-14 in BTRSmith.
2. Build each package twice, unsigned: macOS .app, Linux via Nix (D26), Windows, iOS archive, Android APK and AAB.
3. Compare byte for byte; include license notices and symbols.

**Acceptance**

- [ ] Each platform's unsigned package is byte-identical across two builds
- [ ] Notices, symbols and checksums are present

**Risks**

- Asset compilers (actool, aapt2) can be nondeterministic; document fixes or exceptions.

<a id="cx-r-15"></a>

##### CX-R-15 · Signing and store validation prep: Android release-keystore flow, apksigner and bundletool validation, a notarization path that records 'declined', Windows test-signing, and the p7-notarization preset

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `tooling-release-signing-mobile-store`; `qualification-p7-macos-notarization`
- **Depends on:** [CX-R-14](#cx-r-14)
- **Why not now:** Needs the release packages (CX-R-14).
- **Parallel-safe with:** CX-R-16

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `btrsmith:tools/signing/**`
- `btrsmith:packaging/signing/**`
- tools/runbook/presets/p7-notarization.toml

**Must not touch**

- any secret or key material in the repository
- btrc `src/**`

**Steps**

1. Branch codex/cx-r-15.
2. Android: debug keystore validation in CI; a keytool script for the release keystore in ~/.cache/btrsmith/signing (run by the owner).
3. macOS: notarytool, stapler and spctl, guarded on identity presence, otherwise writing a 'declined: no Developer ID' record (standing approvals).
4. iOS: ad-hoc signing; store validation recorded as declined.
5. Windows: signtool with a runner-generated self-signed test certificate.

**Acceptance**

- [ ] APK and AAB validate with apksigner and bundletool on a Linux runner
- [ ] The macOS script deterministically records declined on the macOS runner
- [ ] A Windows test-signed artifact verifies on windows-latest

**Risks**

- Credentials never enter CI or a commit (D8).

<a id="cx-r-16"></a>

##### CX-R-16 · P7 install, upgrade and uninstall on desktop (macOS, Linux, Windows): state preserved across upgrade, libraries load from an unrelated cwd/user

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p7-install-upgrade`
- **Depends on:** [CX-R-14](#cx-r-14)
- **Why not now:** Needs the release packages (CX-R-14).
- **Parallel-safe with:** CX-R-17, CX-R-18

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `tools/devices/install/desktop/**`
- `btrsmith:tests/packaging/upgrade/**`
- tools/runbook/presets/p7-install-macos.toml

**Must not touch**

- btrc `src/**`
- `btrsmith:src/**`

**Steps**

1. Branch codex/cx-r-16.
2. Install the previous package, create state (catalog, settings, btrsmith.json), upgrade, hash-compare the state, uninstall cleanly.
3. Launch from an unrelated cwd and user.

**Acceptance**

- [ ] Upgrade loses no state on the macOS runner, ubuntu (Nix profile) and windows-latest
- [ ] Uninstall leaves no residue

**Risks**

- There is no previous release package until the first release; use the Stage 43 RC minus one.

<a id="cx-r-17"></a>

##### CX-R-17 · P7 install and upgrade on mobile: iOS simulator and Android emulator upgrade with durable-state retention

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `qualification-p7-install-upgrade`
- **Depends on:** [CX-R-14](#cx-r-14); [CX-R-10](#cx-r-10)
- **Why not now:** Needs the mobile packages and lanes.
- **Parallel-safe with:** CX-R-16, CX-R-19

**Owned paths**

- `tools/devices/install/mobile/**`

**Must not touch**

- btrc `src/**`

**Steps**

1. Branch codex/cx-r-17.
2. `xcrun simctl install` upgrade, and `adb install -r`; verify sandbox and content-URI state survives.
3. Device rows go to MAC-R-12.

**Acceptance**

- [ ] The simulator and emulator upgrade lose no state; ledger records ingested

**Risks**

- Simulator state differs from a device; stand-in only.

<a id="cx-r-18"></a>

##### CX-R-18 · P7 stress and fault classes on desktop, 100 cycles each

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 12 agent-hours
- **PLAN items:** `qualification-p7-stress-faults`
- **Depends on:** [CX-R-14](#cx-r-14); ext:qualification-p5-journey-drivers (Stage 37) → CX-UIB-77…82
- **Why not now:** Needs packages and journey drivers.
- **Parallel-safe with:** CX-R-16, CX-R-19

> **Review change:** Two repositories: run it as two Codex tasks, one per repository environment, both under this packet id. The btrc half (its btrc paths, `codex/<id>` in btrc) merges first; the BTRSmith half pins it. The packet is done when both are (§3.2, §10 F15).

**Owned paths**

- `tools/devices/stress/desktop/**`
- `btrsmith:tests/stress/**`
- tools/runbook/presets/p7-stress-macos.toml

**Must not touch**

- btrc `src/compiler/**`
- `src/runtime/c/**` (defects go to Claude requests)

**Steps**

1. Branch codex/cx-r-18.
2. Fault classes: denied and revoked permissions, low storage, absent devices, corrupt media, native initialization failure, process death, GPU loss, callback races, upgrade from the previous package.
3. Inject each fault 100 cycles on macOS, Linux and Windows runners; runtime defects are filed as Claude requests.

**Acceptance**

- [ ] Every desktop fault class passes 100 cycles, or is filed with a reproduction

**Risks**

- GPU loss is hard to inject on hosted runners; the Mac run covers it.

<a id="cx-r-19"></a>

##### CX-R-19 · P7 stress and fault classes on mobile: suspension, process death, permission revocation, low storage (simulator and emulator)

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS runner · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p7-stress-faults`
- **Depends on:** [CX-R-17](#cx-r-17)
- **Why not now:** Needs the mobile install lanes.
- **Parallel-safe with:** CX-R-18

**Owned paths**

- `tools/devices/stress/mobile/**`

**Must not touch**

- btrc `src/**`

**Steps**

1. Branch codex/cx-r-19.
2. Use simctl and adb fault hooks, 100 cycles each.

**Acceptance**

- [ ] Every mobile fault class passes 100 cycles on the simulator and emulator; device rows awaiting

**Risks**

- Emulator flakiness; retries recorded.

<a id="cx-r-20"></a>

##### CX-R-20 · P7 OS-version matrix: minimum and current OS and SDK-update evidence on hosted runners, simulators and emulators; closes UI10's OS evidence

- **Owner:** Codex · **Group:** R · **Stage:** 42 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 8 agent-hours
- **PLAN items:** `qualification-p7-os-version-matrix`
- **Depends on:** [CX-R-14](#cx-r-14); [CX-R-10](#cx-r-10)
- **Why not now:** Needs packages and mobile lanes.
- **Parallel-safe with:** CX-R-18

**Owned paths**

- `tools/devices/os_matrix/**`
- tools/runbook/presets/p7-os-matrix.toml
- docs/qualification/os-matrix.md

**Must not touch**

- btrc `src/**`

**Steps**

1. Branch codex/cx-r-20.
2. macOS on macos-14 and macos-15 runners (Stage 24 Q1 floor).
3. Windows Server images as a stand-in for Windows 11.
4. iOS 17 (or the oldest installable) and current simulators.
5. Android API 29, current and 16 KiB emulators.
6. Build against the current SDK and run on the minimum OS (UI10 section 3).

**Acceptance**

- [ ] Every OS row is passed or stand-in-only, with the physical rows listed
- [ ] UI10 minimum/current OS evidence table generated

**Risks**

- Hosted images change under you; pin the image versions in records.

#### Stage 43: Final platform exits and the release candidate

<a id="cx-r-21"></a>

##### CX-R-21 · BTRSmith platform release assembly on the frozen SHAs: per-platform packages signed as far as D8 allows, release notes, coverage-report links

- **Owner:** Codex · **Group:** R · **Stage:** 43 · **Environment:** Linux cloud + GitHub macOS and Windows runners · **Start now:** no · **Estimate:** 6 agent-hours
- **PLAN items:** `btrsmith-q-platform-release`
- **Depends on:** [CX-R-14](#cx-r-14); [CX-R-15](#cx-r-15); [CX-R-16](#cx-r-16); [CX-R-20](#cx-r-20)
- **Why not now:** Needs every Stage 42 artifact packet.
- **Parallel-safe with:** CL-R-45

**Owned paths**

- `btrsmith:packaging/release/**`
- btrsmith:docs/Release.md (new)

**Must not touch**

- btrc `src/**`
- the frozen SHAs

**Steps**

1. Branch codex/cx-r-21.
2. Assemble the release set from the frozen package set; link CL-R-46's coverage report.

**Acceptance**

- [ ] The release set is complete for every platform, with unsigned/declined states explicit

**Risks**

- Store submission is declined until accounts exist (standing approvals).
