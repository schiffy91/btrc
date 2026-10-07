# Codex UI lanes (2026-10-03)

**2026-10-07 consolidation:** [PLAN.md](../../PLAN.md) is the single active roadmap and queue. D29 supersedes older split-plan and integration-role wording for the authorized harmonization session; packet IDs, file claims, review and evidence requirements remain.

> **Historical assignment (2026-10-03/04). Superseded for scheduling by [CODEX.md](../../CODEX.md) (D28).** Codex's
> active queue is now CODEX.md. Packet ids here stay for traceability. Where this file conflicts with D28 or
> CODEX.md, CODEX.md governs ([CLAUDE.md D28](../../CLAUDE.md#decisions-all-resolved-2026-09-30)).

This was the file Codex's standing goal waited for: the owner asked for Codex to do all the native-UI work, with
macOS, Linux, iOS/iPadOS, Android and Windows parallelized. It was Claude's assignment as integrator under
CLAUDE.md D27 and WORKSTREAMS.md §2–§3. It no longer takes precedence over `docs/workstreams/codex.md`; both yield
to CODEX.md. Queue changes now go in CODEX.md: read it on `origin/main` before each new unit.

## Corrections (2026-10-04)

- **Lane workflows are yours (superseded by D28).** Under D28 Codex edits no workflow or `ci/proposed/` file. Claude adds lane workflows from the PR's `REQUEST` block. The 2026-10-04 text follows, kept as history. The goal text the owner pasted said never to edit "CI-workflow files". That was the integrator's wording, and it was too broad. Only `.github/workflows/{ci,macos,windows,release}.yml` are Claude's. A packet's own lane workflow (`host-android.yml`, `host-ios.yml`, `host-windows.yml`, `windows-arm64.yml`, …) is that packet's owned path. Commit it in the lane-workflow class (CI policy, item 8). If the token lacks the `workflows` permission, commit it as `ci/proposed/<name>.yml` instead, and Claude installs and dispatches it.
- **Evidence artifacts.** Codex's token gets HTTP 403 on `gh run download` for the shared UI0 runs. Claude can download them. Until the token can, leave cells implemented-unverified and say so in the PR, as `CX-UIA-03`, `04` and `30` did. Claude promotes the evidence in a follow-up. If your environment can read artifacts, cite the `[runs.ui0-*]` headers in the cells. The first promotion landed on `main` 2b33cdaa (`evidence/ui0-junit-2026-10-04.toml`, 438 operation cells).
- **Three Stage 26 designs returned (2026-10-04).** `CL-P2-01` reviewed `windows-os-services.md` (`CX-P2-01`), `http-transport.md` (`CX-P2-02`) and `mobile-storage.md` (`CX-P2-03`). All three need a revision: 7, 5 and 1 blocking findings. The findings, resolutions, assumed adaptation defaults and the requests to Claude are posted on PRs #37, #39 and #36. Revise each design in a new docs-only PR (`codex/cx-p2-0N-r2`). The docs tier is uncapped. These revisions come before any `CX-P2-04…16` provider code, which waits for the approval.
- **`CX-C-01` follow-up.** PR #26 is integrated. Its five minor follow-ups, posted on the PR, go in one small PR.

## Where each platform stands

UI0's serial foundation landed first: PR #21's catalog seed and drift gate (`b7aa53f`, batch 11), the focused
`make test-native-gui` gate (batch 13), the CI tiers with the macOS `native-gui` job in the lane tier, the headless
Linux session (`tools/ui/headless-session.sh`) and the `.#platforms` Android toolchain shell. Since then `main` has
gained the catalog shard loader (`CX-UIA-02` follow-up, batch 20), the UI1 shell fixture (`CX-UIA-09`, batch 30),
the Linux SDL shell evidence (`CX-UIA-11`, batches 34 and 38) and the macOS accessibility evidence (`CX-UIA-10`,
batch 36). `src/stdlib/GUI` still has only `MacOS/`, `Linux/` and `FreeType/`. For current readiness and each
platform's next checkpoint, read [CODEX.md](../../CODEX.md#platform-slices-beyond-the-repairs). The table below is
the 2026-10-03 snapshot, kept as history.

| Platform | Can start now (2026-10-03, historical) | What blocks the native shell and its UI tracks |
|---|---|---|
| macOS | `CX-UIA-09` (shell fixture, macOS probes), `CX-UIA-01` remainder, UI2 drafts `CX-UIA-18/19/20`, `CX-UIB-07/08` | `CX-UIA-10` waits for `CX-UIA-09` and the `CX-UIA-02` follow-up; UI2/UI3 follow the Stage 31–33 chain |
| Linux | `CX-UIA-09` (Linux probes), `CX-UIA-12` (GTK4/WebGPU pre-spike), `CX-UIA-06` (hosts, desktop check) | `CX-UIA-11` as macOS; the btrc-hosted GTK4 spike waits for the GObject binding (after interop) and D23 |
| iOS / iPadOS (one lane) | `CX-P1-04` (simulator host spike with an iPad destination), `ios.md` from `CX-UIA-13` with an iPadOS section, `CX-P2-03` | Stage 24 target rows (Claude, starts when C4 lands; the owner approved the early start), Stage 25 host lane `CX-P1-08`, UIKit interop `CL-P2-21`, `MAC-P1-02` (Xcode and simulators) |
| Android | `CX-P1-05` (KVM emulator host spike), `android.md` from `CX-UIA-13` | Stage 24/25 as iOS, host lane `CX-P1-09`, checked JNI `CL-P2-09`/`CL-P2-24`, `MAC-P1-03` |
| Windows | `CX-P1-06`, `CX-P1-03`, `CX-P2-01`, `windows.md` from `CX-UIA-13` | Stage 24/25, host lane `CX-P1-07`, function tables `CL-P2-06`, COM `CL-P2-10` |

iPadOS is not a separate family: it shares `GUI/IOS`, `App/IOS` and the `ios` ledger family, and an iPad run shows
in `provenance.device_class`. iPad work rides inside each iOS packet (a simulator destination and `device_class`
evidence), never as a separate agent on the same files.

The new-platform shells (`CX-UIA-15/16/17`) are roughly 290–350 agent-hours of Claude-side compiler, host and
interop work away. Until then a Windows, iOS or Android agent can do the foundations only (host spikes, shell notes,
designs: about 40–50 agent-hours), and those foundations do gate the shells, so do them early. **D28:** the
per-platform slices in [CODEX.md](../../CODEX.md#platform-slices-beyond-the-repairs) start on their own
prerequisites.

## Lanes that can run at the same time

Owned paths are disjoint across these lanes, so they can be separate Codex tasks authored in parallel. CI is the
shared bottleneck (see the CI policy below).

| Lane | Packets now → next | Owned paths | CI tier |
|---|---|---|---|
| 0. Bucket-2 tooling | `CX-C-01` (about 3 h; the owner's C4 checkpoint `MAC-C-02` needs it the moment C4 lands) | `tools/bench/scripts/ccompat_checkpoint.sh`, one README row, `test_ccompat_checkpoint_script.py` | lane (first in the CI queue) |
| 1. Catalog (the Stage 30 critical path) | `CX-UIA-02` follow-up → (integrated) `CX-UIA-03` → `04` → `30` → `05` → `CX-UIA-07` (after `CL-UIA-03`; `CX-UIA-07` gates nothing under D28) | `ui_catalog.py`, `test_ui0_catalog.py`, `native-ui-catalog/{README.md,families.toml}`, the amendments, `ui0-catalog.md`, one D068 bullet; then `operations/*.toml`, `cases/*.toml`, `surface/*.toml`, `test_ui0_surface.py` | lane |
| 2. macOS + Linux shells | `CX-UIA-09` and the `CX-UIA-01` remainder → `CX-UIA-10` ∥ `CX-UIA-11` | `src/tests/native/gui/shell/**`, `test_native_ui_shell{,_macos,_linux}.py`, fixtures; the runbook, `test_native_gui_target.py`, `tools/ui/codex-setup.sh`; then `probes/{macos,linux}`, `evidence/ui1-{macos,linux}.toml` | lane |
| 3. Contracts, notes, spikes, designs | `CX-UIA-19` ∥ `20` ∥ `18`; `CX-UIA-13` split per platform (with iPadOS); `CX-UIA-12` (prototype on a no-PR spike branch); `CX-P2-01/02/03` | `docs/design/ui-contracts/{index,ui2-*}.md`, `docs/design/native-ui-shells/{windows,ios,android}.md`, `docs/design/linux-gtk4-feasibility.md`, the three design docs | docs (uncapped) |
| 4. Host spikes and Linux extras | `CX-P1-05` → `CX-P1-04` (with iPad) → `CX-P1-06` → `CX-P1-03`; `CX-UIA-06`; `CX-P1-02` | `tools/target_hosts/{android,ios,windows}/**`, `host-*.yml` and `windows-arm64.yml` (Claude's under D28; see Corrections), `tools/windows_toolchain/**`, append-only rows in `test_ci_workflow_contracts.py`; `hosts.toml`, `test_native_ui_hosts.py`, `linux-desktop-check.sh`; `platform-adaptations.md` and inventory cells | lane plus the packet's own workflow |

Claude, meanwhile (2026-10-03, historical): lands C4 (`CL-C-06`), then Stage 24 sub-batch 1 (`CL-P1-03`→`06`, which adds the `ios` and
`android` target rows) and on through Stage 25 (`CL-P1-16/17`, which open `CX-P1-07/08/09`); adds
`test_native_webgpu_imports.py` to `NATIVE_GUI_TESTS`; lands `CL-R-50` (a path-selective lane tier, which lets
catalog-data and tools-only Codex PRs run a few jobs instead of the full lane matrix, and then raises the Codex CI cap
to two); lands `CL-UIA-24` (several denominator releases per kind, the retired disposition, frozen sources read from
the seed ledger) before `CX-UIA-05` integrates; and reviews the drafts that gate later work (`CL-P2-22` after
`CX-UIA-19/20`, `CL-UIA-13` after the UI2 drafts).

---

## The assignment

### Context
- **Catalog status.**
  - PR #21's commit `b7aa53f` is on `main` (batch 11), and PR #21 is closed. Its CI was green: ci.yml 37090470053, macos.yml 37090470052, windows.yml 37090470074.
  - **The CX-UIA-02 follow-up was integrated in batch 20** (PR #22). `tools/qualification/ui_catalog.py` now exists and is a Claude hotspot.
- **Stage 24's early start is approved** (owner, 2026-10-03). The Windows, iOS and Android host lanes open once Stage 25's runner core lands.
- **Read first:** AGENTS.md's Codex section, then [CODEX.md](../../CODEX.md), then WORKSTREAMS.md §2–§3. Where this text conflicts with D28 or CODEX.md, CODEX.md governs.
- **Environment.**
  - Run `export BTRC_TEST_RUNNER=linux-devcontainer`.
  - Run every command through `nix develop --command …`; inside an open shell, use `make NIX= …`.
  - Branch from the current `origin/main`.
- **Parallelism.** Tasks 0–4 below are separate Codex tasks that can be authored at the same time, with disjoint owned paths. CI is the shared bottleneck (see the CI policy), so their pushes take turns.

---

### CI policy (every task): monitor and fix before handing back

1. **Tiers** (ci.yml scope step; WORKSTREAMS §3.2):
   - **docs:** every changed file is Markdown outside `TEST_READ_MARKDOWN` (not `README.md`, `native-ui-parity.md` or `native-ui-api-inventory.md`). Only `scope` and `static` run.
   - **lane:** any other `codex/*` PR. Since `CL-R-50` (batch 18) it always runs `scope`, `static`, `release` and the unit shard; the heavy Linux shards run only for `src/stdlib/**`, `src/tests/**` (except `src/tests/python/test_*.py`), `examples/**`, `tools/**` (except `tools/ui/**`, `tools/target_hosts/**` and `tools/qualification/ui_catalog.py`) and the root config files, and the macOS jobs only for the macOS/GUI/native paths. A heavy lane run is about 18 Linux jobs, 3 macOS jobs and windows.yml `scope`; a catalog-data PR is four Linux jobs and no macOS job.
   - **main:** any path in `FULL_PATHS` (`Makefile`, `ci/tiers.toml`, the core workflows, …). The full matrix runs.
2. **Cap.** At most **one** Codex PR with a lane- or main-tier run in flight (queued or running). Docs-tier PRs are not capped.
   - **Why:** a heavy lane run is about 22 jobs, against the account's 20-job concurrency limit, which macOS jobs count toward; `main`'s batch pushes share it. A lane run that `CL-R-50` reduces to `scope`, `static`, `release` and the unit shard (a catalog-data or docs-and-tests-only PR) does not count against the cap.
   - **Check before pushing:**
     ```
     nix develop --command gh api "repos/schiffy91/btrc/actions/runs?per_page=50" --jq '.workflow_runs[]|select(.head_branch|startswith("codex/"))|select(.status!="completed")|"\(.id) \(.head_branch) \(.name) \(.status)"'
     ```
     If another Codex branch has a run listed, keep working locally and push when it completes.
   - **Priority:** follow the order of [CODEX.md](../../CODEX.md#first-delivery-queue)'s queue (D28). The 2026-10-03 advisory order (CX-C-01, then the CX-UIA-02 follow-up, then CX-UIA-09, then CX-P1-05, then the rest) is historical.
   - **When it rises:** Claude raises the cap to two once CL-R-50 (path-selective lane tier) lands and the first lane run's runner-minutes are recorded.
3. **Before every push:**
   - the packet's acceptance commands pass locally;
   - for any branch that adds or changes Python, shell or btrc files: the whole unit shard passes locally (`nix develop --command make NIX= test-unit`), not only your new tests. Three of the first ten Codex code pushes went red on `test_subprocess_timeouts.py` alone: every waited `subprocess` call in `src/tests/**` and `tools/bench/**` passes `timeout=` (use `src/tests/process_limits.py`). A macOS-facing change also needs the macOS `native-gui` job green before hand-back, and if a fixture cannot pass there, say so instead of handing back;
   - `git diff --name-only origin/main...HEAD` lists only owned paths (plus any `fragment:`/`derived:` commits). A stacked packet diffs against its base branch instead.
4. **Push budget: batch corrections (D28).** Aim for four pushes per packet: the claim, the final commit and two fixes. Four is not a hard stop, and the count must not strand a verified repair. The cap in item 2 still applies; avoid redundant runs.
   - Claim with your first real commit.
   - Where the packet owns a Markdown file outside the test-read set, the claim commit may carry only that file, so the claim runs the docs tier.
5. **Find the runs, then watch the fast jobs first.**
   ```
   nix develop --command gh api "repos/schiffy91/btrc/actions/runs?branch=<branch>&event=pull_request&per_page=6" --jq '.workflow_runs[]|"\(.id) \(.name) \(.head_sha[0:8]) \(.status) \(.conclusion)"'
   ```
   - Watch `release` (generated-check, lint, format, packaging), `tests (unit)`, `tests (btrc)` and, where it runs, macOS `native-gui`, using `gh run view <id> --json jobs`.
   - On red, run `gh run view <id> --log-failed`, fix inside your owned paths and re-push at once.
6. **Then wait for the whole run** with `gh run watch <id> --exit-status --interval 120`, for at most **180 minutes** after your final push. If it has not finished, record the run ids in the PR body and hand back; Claude's `@codex` comment loop (§3.2) takes over. Then continue another independent CODEX.md unit (D28).
7. **A red job your diff cannot affect** (C11, bootstrap, corpus or bench on a docs/tools/tests-only change):
   - compare it with `main`'s latest run;
   - for an infrastructure failure only, rerun once with `gh run rerun <id> --failed`;
   - otherwise record the job, run id and log lines in the PR body and hand back, then continue another independent CODEX.md unit (D28).
8. **Never:**
   - add `ci:full`;
   - dispatch `full` or `extended`;
   - change `Makefile`, `ci/tiers.toml` or a core workflow, unless your packet names it as a `fragment:` commit (§3.5).

   **About fragments.** Such a fragment puts the PR in the main tier, and it takes the single CI slot. Prefer a `REQUEST(…)` when Claude can land the line first.

   **Lane workflows** (superseded by D28: Claude writes lane workflows; see Corrections). If your workflow has a matrix job that runs pytest, it needs a `fragment: ci/tiers.toml` row: `test_ci_workflow_contracts.py:564` looks up every matrix pytest job of every workflow in that file.
9. **Dispatches** (`gh workflow run … -f focus=native-gui`) need `actions:write`. Use at most one per workflow per packet. If the dispatch is refused, ask Claude in the PR to dispatch and post the run id.
10. **Hand back** when every scheduled job is green, after a third red, or at the time box, then continue another independent CODEX.md unit (D28).
    - In the lane tier, windows.yml runs only `scope` and still concludes success. Record it as "green (scope only)".
    - Never merge, close or mark your PR ready; it stays a draft.

---

### Task 0: CX-C-01, the one-command Mac checkpoint script (about 3 h; bucket-2 tooling, first in line)

**Why first:**
- It is PLAN-sanctioned bucket-2 work, and D27 says Codex work never displaces bucket 1–3 work.
- The owner's C4 checkpoint `MAC-C-02` needs it the moment `CL-C-06` (in flight) lands.

**Branch:** `codex/cx-c-01`. **PR title:** `[CX-C-01] One-command Mac checkpoint script for bucket-2 evidence`.

**Owned paths:**
- `tools/bench/scripts/ccompat_checkpoint.sh` (new)
- `tools/bench/scripts/README.md` (one new table row only; shared append-only with CL-R-02)
- `src/tests/python/test_ccompat_checkpoint_script.py` (new)

**Must not touch:** every other script under `tools/bench/scripts/`, `tools/budget_bench.py`, `Makefile`, `flake.*`, `nix/*`, `src/**` except the new test, PLAN.md, AGENTS.md.

**Steps:** codex.md CX-C-01 steps 1–11, unchanged.

**Acceptance:**
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_ccompat_checkpoint_script.py -q -rs` passes.
- [ ] `bash -n` passes, and shellcheck too where the dev shell has it.
- [ ] The dry-run plans for MAC-C-02's and MAC-C-09's invocations match the commands those packets list.
- [ ] Lane CI is green under the policy (run ids; windows "green (scope only)").

The branch is lane tier, because `README.md` is test-read.

---

### Task 1: CX-UIA-02 follow-up (shard loader, shard contract, family cells, IFontFace scope)

This is the Stage 30 critical path, about 6 h.

**Branch:** `codex/cx-uia-02-shards`, from `origin/main`.

**Draft PR:**
- Title: `[CX-UIA-02] ui-0-catalog-schema follow-up: shard loader, family cells, IFontFace scope`.
- Body: `.github/PULL_REQUEST_TEMPLATE/codex-packet.md`, with Owned paths first, then `Packet: CX-UIA-02 … Branch: codex/cx-uia-02-shards Base: <origin/main sha>`.

#### Owned paths
- `tools/qualification/ui_catalog.py` (new)
- `src/tests/python/test_ui0_catalog.py`
- `docs/design/native-ui-catalog/README.md` (new)
- `docs/design/native-ui-catalog/families.toml` (new)
- `docs/design/ui0-source-amendments.toml`
- `docs/design/ui0-catalog.md`
- `docs/design/native-ui-api-inventory.md`: **one new bullet only** (btrc-D068) under `## Changes since the frozen inventory`, and no table rows.

#### Must not touch
- **The seed:** `docs/design/native-ui-catalog.toml` stays byte-identical.
- **Qualification code and data:**
  - every existing `tools/qualification/*.py`;
  - `tools/qualification/denominators.toml`;
  - `src/tests/python/test_qualification_ledger.py` and `test_ci_workflow_contracts.py`.
- **Other catalog paths:** every other path under `docs/design/native-ui-catalog/`. They belong to the later packets named in the README table.
- **Frozen inventories:**
  - the tables in `native-ui-api-inventory.md`;
  - all of `native-ui-parity.md`;
  - `platform-inventory.toml`.
- **Claude-owned paths:**
  - `src/**`. You may import the reference `Lexer` and `Parser` read-only, as `test_ui0_catalog.py` already does.
  - `Makefile`, `ci/tiers.toml`, `.github/**`, `flake.*`, `nix/*`;
  - `PLAN.md`, `AGENTS.md`, `CLAUDE.md`, `WORKSTREAMS.md`, `docs/workstreams/**`, `docs/design/plan-reference.md`.

#### Binding rules
1. **Build every shard kind now.** `ui_catalog.py` becomes a Claude hotspot the moment it lands (§3.3.1, "tools/qualification/*.py (existing modules)"), so later packets will only add data files.
2. **Leave the frozen id sources alone.**
   - Never add a row shaped ``| `Owner.member` | … |`` to `native-ui-api-inventory.md`.
   - Never change an N-row or E-row id in `native-ui-parity.md`.
   - Both are the regex sources of the frozen releases until CL-UIA-24 repoints them.
3. **Mind which Markdown files code may name.** No string literal in `src/tests/**` or `tools/**` may name a `.md` file outside `TEST_READ_MARKDOWN`. Never read `ui0-catalog.md` from code.
4. **No denominator change and no re-freeze.** Release `ui0-source-inventory-2026-09-21` stays at 162/1,620 operations, 47/470 cases and 60/300 family cells.

#### Steps

**1. Shard layout.** Declare it as data in `ui_catalog.py`, and mirror it in `README.md`. Any other file or directory is an error.

| Path | Content | Admission rule |
|---|---|---|
| `families.toml` | ledger/1, `family-cell` only | N01–N60 × 5 platforms, no frontend |
| `operations/<Owner>.toml` | `ui-operation` only | every id starts with `<Owner>.`, and `<Owner>` owns an admissible id (below) |
| `cases/E<aa>-E<bb>.toml` | `ui-case` only | ids inside the filename's range; ranges never overlap |
| `surface/<Stem>.toml` | `btrc.ui-catalog.surface/1` | see the surface rules below |
| `evidence/<name>.toml` or `.jsonl` | ledger/1 evidence with provenance, `test` records, and `note` | see the evidence rules below |
| `amendments/<packet-id-lowercase>.toml` | the `ui0-source-amendments.toml` grammar (step 7) | one file per packet |
| `hosts.toml`, `README.md` | — | skipped explicitly; CX-UIA-06's test validates `hosts.toml` |

- **Surface shards:**
  - `<Stem>` comes from a declared list: `GUIModules` (GUI modules outside `I*.btrc`), `App`, `UI` and `Tray`.
  - There is one table per exported symbol: `module`, `symbol`, `kind`, a `disposition` of `family`, `legacy`, `provider-internal` or `out-of-scope`, `links`, and `reason` (required unless the disposition is `family`).
  - A `family` row may carry an optional `operations` list of proposed ui-operation ids.
  - Rows are validated against the GUI, App, UI and Tray `btrc.toml` exports.
- **Evidence shards:**
  - `<name>` is lowercase kebab-case, for example `ui1-macos`.
  - The only classification allowed is `note`.
  - The README table names each file's packet; ledger/1 rejects extra top-level keys, so the packet is not stored in the file.
- **Admissible ids** are the union of:
  - the seed;
  - the amendments;
  - every ui-operation and ui-case release `denominators.toml` declares, read through `DenominatorManifest`: one today, more after CL-UIA-24;
  - the `operations` ids of surface rows whose disposition is `family`.
- **README owner-to-packet table.** It lists every planned path:

  | Path | Packet |
  |---|---|
  | `families.toml` | CX-UIA-02 |
  | `operations/{IApplication,IApplicationWork,IWindow,IWindowKeyHandler,IView,IViewPointerHandler,IViewScrollHandler,IContainer,IGPUView,IDirectoryPicker,GUI}.toml` | CX-UIA-03 |
  | `operations/{IButton,IButtonAction,ITextField,ISelect,ISlider,ILabel,IStack,IGrid,IScrollView,IPanel,IImageView,IImageHandle,IProgressIndicator,ILevelIndicator,IFontFace}.toml` | CX-UIA-04 |
  | `cases/E01-E24.toml`, `cases/E25-E47.toml` | CX-UIA-30 |
  | `surface/{GUIModules,App,UI,Tray}.toml` | CX-UIA-05 |
  | `hosts.toml` | CX-UIA-06 |
  | `evidence/ui1-macos.toml` | CX-UIA-10 |
  | `evidence/ui1-linux.toml` | CX-UIA-11 |
  | UI2 and UI3 `operations/` rows | CX-UIA-21, CX-UIA-25 |

**2. Compact form.** Operation and case shards accept a compact form as well as verbose `[[records]]`.
- **One table per id.** Write one `[[operations]]` or `[[cases]]` table per id. Shared fields go on the table: `implementation`, `parity`, `owner`, `links`, `regression`, `decision`, `note`.
- **Per-platform cells.** Cells `macos`, `linux`, `windows`, `ios` and `android` each take one of two forms:
  - a mapping that applies to both frontends;
  - `{ reference = {…}, selfhost = {…} }`.
- **Cell contents.** A cell holds overrides plus `evidence = { status, observed, reason, artifact, covered_by }` and `run = "<name>"`.
- **Runs.** `[runs.<name>]` carries `source`, `recorded_at`, `runner`, `btrc_revision`, `device_class`, and so on.
- **Validation.** Expand every cell to ledger/1 and pass it through `LedgerRecord.from_mapping`, so every `schema.py` invariant applies.

**3. Merge and partitions.**
- **Ledger order:** the seed, then `families.toml`, then `operations/` and `cases/` in sorted order, then `evidence/` in sorted order.
- **Classification is unique.** One slot is classified in at most one file.
- **Evidence is not unique.** Several files may carry evidence for one slot. The last in ledger order wins, exactly as `schema.py:143-144` and `report.py` specify.
- **Stale overwrites.** `check` reports, as a problem, an evidence record that replaces one whose `provenance.recorded_at` is newer.
- **Reject:**
  - a slot outside the admissible ids;
  - classification in two files;
  - a duplicate within one file;
  - a `variant` on a UI slot;
  - a foreign owner, or an out-of-range case id;
  - a classification other than `note` under `evidence/`.
- **Partitions:**
  - **frozen:** 1,620 operation, 470 case and 300 family-cell slots;
  - **pending:** the amendment ids plus surface proposals. Today that is 17 ids / 170 slots if IFontFace is in scope, and 15 / 150 if not. They may be classified in their owner's shard, but they are excluded from the frozen report.
  - **retired:** the removal ids, today `GUI.rasterText` and its 10 slots. No shard may classify them; they are reported with their decision, btrc-D056.
- **Pending ids come from the parser.** Derive them through the reference Lexer and Parser public API, never by regex.

**4. Define "classified" in one place** (in the code and in the README).
- A ui-operation or ui-case slot is classified when it has `classification.implementation` and `evidence.status`.
- A family-cell slot is classified when it has `implementation`.
- Provide `unclassified(owner=…, kind=…)`, which **excludes retired slots**.

**5. CLI** (exit status 1 on any problem).
- **`check`:**
  ```
  python3 -m tools.qualification.ui_catalog check [--strict] [--owner O]... [--kind ui-operation|ui-case|family-cell|surface]... [--junit RUN=PATH]...
  ```
  - It runs the layout and admission rules, then builds `QualificationReport(frozen records, DenominatorManifest([the three UI kinds]))` and requires `problems() == []`.
  - `--strict` also fails on any unclassified non-retired slot in the selected scope. Retired slots are listed separately and never fail it.
  - With `--junit`, every `passed` cell whose `run` is `RUN` must list `classification.regression` node ids that passed in that XML (read it with `JUnitAdapter`, read-only).
- **`report`:**
  ```
  python3 -m tools.qualification.ui_catalog report [--format markdown|json] [--owner O]... [--kind K]...
  ```
  It gives per-kind × platform × frontend counts, the frozen, pending and retired partitions, and the unclassified slots per owner.

**6. `families.toml`.**
- **Seed it** from the 2026-09-21 P/C/M matrix in `native-ui-parity.md`:
  - P → `implementation = "partial"`;
  - C → `"custom"`;
  - M → `"missing"` with `parity = "missing"`.
- **Links:** `links = ["Nxx", "UIx"]`.
- **Notes.** The matrix cells carry no footnotes; take the notes from the paragraph under the legend (`native-ui-parity.md:306-309`):
  - N10, N37, N40, N42 and N43, macOS: P credits only the native editor and control foundation, not a verified shared editing or accessibility contract;
  - N41: missing, because native control defaults provide no custom-content bridge.
- **No evidence.**
- **The test does not re-read `native-ui-parity.md`.** It pins the seeded 300-cell grid as data, with its sha256. Any `families.toml` cell that differs from the seed must carry a `decision`.
  - Totals: P 48, C 15, M 237.
  - Per platform: macOS 33/0/27; Linux 15/15/30; Windows, iOS and Android 0/0/60 each.

**7. Amendments.**
- **IFontFace scope.** Record it in `ui0-source-amendments.toml`.
  - Recommended: in scope, linked to N44 (UI5) and N49 (UI9), because `GUI/btrc.toml` exports it and `Font(IFontFace)` is public.
  - Otherwise, record out-of-scope with the reason.
- **Wider grammar:**
  - `[[changes]]`: `id`, `decision`, `frozen`, `current`. A changed signature keeps its frozen id.
  - an optional `parent` on additions;
  - an optional `replacement` on removals.
- **Per-packet files.** Also load `amendments/*.toml`.
- **Counts from data.** Derive the counts test from `[current]` plus the amendments, replacing the literals 20/25/152/26/17.
- **Outside-interface guard.** Add a test that fails when an exported GUI module outside `I*.btrc` declares an `interface` that an `[[outside_interfaces]]` list (`id`, `decision`, `reason`) does not name. Today that list holds `ActionMailbox.IQueuedAction`.

**8. Documentation.**
- Add the btrc-D068 bullet: `FontFace.btrc` was renamed to `IFontFace.btrc` (16185609), which brings `IFontFace.metrics`/`.glyph` into the `I*.btrc` scope.
- Update `ui0-catalog.md`: the layout, the CLI, the partitions, "classified", and the IFontFace decision.

**9. Tests in `test_ui0_catalog.py`.**
- `verify_catalog` runs over the merged view.
- **One negative case per admission rule:**
  - an unknown file;
  - a foreign owner;
  - a case id out of range;
  - classification duplicated across two files;
  - an unknown id;
  - a classification under `evidence/`;
  - a `variant`;
  - a tampered seed slot set;
  - a pending slot leaking into the frozen count;
  - a retired id classified;
  - a stale evidence overwrite reported.
- **Positive cases:**
  - an `operations/` shard and an `evidence/` shard touching one slot, where the last evidence wins;
  - a surface `family` row that admits a new owner shard;
  - `hosts.toml`, `evidence/ui1-macos.toml` and `surface/GUIModules.toml` accepted;
  - retired slots excluded from `--strict`;
  - a compact-form round trip;
  - a merge of two packets' fixture shards in `tmp_path`.
- The families seed check and the outside-interface guard are covered.
- The existing dummy-method failure still fails.

#### Acceptance
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_ui0_catalog.py -q -rs` → 0 failed, 0 skipped.
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_qualification_ledger.py src/tests/python/test_platform_inventory.py -q -rs` → 0 failed.
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_ci_workflow_contracts.py -k markdown -q` passes.
- [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check` exits 0 and prints:
  - 1,620/1,620 ui-operation, 470/470 ui-case and 300/300 family-cell slots;
  - 0 undeclared and 0 duplicate;
  - pending 17 ids / 170 slots (15 / 150 if IFontFace is recorded out of scope, with its 2 ids and the reason listed);
  - retired 1 id / 10 slots.
- [ ] `… ui_catalog report --format json` gives:
  - family-cell partial 48, custom 15, missing 237, with the per-platform split above;
  - ui-operation and ui-case at 0 classified.
- [ ] `nix develop --command python3 -m tools.qualification denominators` exits 0.
- [ ] `git diff --exit-code origin/main -- docs/design/native-ui-catalog.toml tools/qualification/denominators.toml` exits 0, and the diff lists only owned paths.
- [ ] `make lint format-check generated-check` and `git diff --check` pass.
- [ ] Lane CI is green on the final head: ci.yml and macos.yml with run ids, and windows.yml "green (scope only)".

#### REQUEST blocks for the PR body (do not implement)
- **`REQUEST(CL-UIA-24)`:**
  - several releases per kind in `denominators.py`, with per-release missing counts and union undeclared counts in `report.py`;
  - a retired disposition in `schema.py`;
  - point the 2026-09-21 ui-operation and ui-case sources at `{ ledger = "docs/design/native-ui-catalog.toml" }`, and the family-cell source at `families.toml` once it is on `main` (same ids and sha256);
  - adjust `test_qualification_ledger.py`'s `_frozen_copy` cases.
- **`REQUEST(CL-UIA-05)`:** wire `ui_catalog` into `make qualification-report`.

---

### Task 2: macOS and Linux shell lane

**Open defect for this lane (`CX-UIA-11`).** `src/tests/python/test_native_linux_providers.py::test_linux_gui_controls[True-python]` fails intermittently with `X Error of failed request: BadWindow (invalid Window parameter)`, major opcode 18 (`X_ChangeProperty`), when `make test-native-gui` runs four workers on one Xvfb display in the cloud container. It passed 24 of 24 runs alone and failed in two of two four-worker gates (batches 17 and 19); GitHub's runners have not hit it. A property is being set on a window that is already gone, which is a race in the Linux SDL provider or its test program, not load. Root-cause it in `CX-UIA-11` with a reproduction that forces the interleaving, and fix it; never mark it flaky or skip it.

#### B1. CX-UIA-09: shell fixture and harness (about 10 h, start now)
It has no dependencies and heads UI1 → UI2.

**Branch:** `codex/cx-uia-09`. **PR title:** `[CX-UIA-09] ui-1-shell-fixture: portable native-shell fixture, probe contract and harness`.

**Owned paths:**
- `src/tests/native/gui/shell/`: `NativeShell.btrc`, `probes/macos/ShellProbe.{h,m}`, `probes/linux/`.
- `src/tests/python/test_native_ui_shell.py`: the portable harness plus the windows-x86_64 provider-missing case.
- `src/tests/python/native_ui_shell_fixtures.py`.
- `src/tests/python/test_native_ui_shell_macos.py` and `test_native_ui_shell_linux.py`: the initial per-platform rows. The existing `test_native_ui_*.py` Makefile glob collects them.

**Must not touch:** `src/stdlib/**`, `Makefile`, `src/compiler/**`, `src/language/**`, `src/runtime/**`, `.github/**`, PLAN.md.

**Steps.** Do codex.md CX-UIA-09 steps 1–9. CL-UIA-21 has landed, so the Wayland rows run through `tools/ui/headless-session.sh --wayland`.

**Acceptance:**
- [ ] `nix develop --command tools/ui/headless-session.sh --x11 -- python3 -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_linux.py -q -rs` passes:
  - the linux-x11 rows for python and selfhost, plain and sanitized;
  - the windows-x86_64 provider-missing case.

  Report the `--wayland` counts too.
- [ ] The macos.yml `native-gui` job on the draft PR passes the macOS rows for both frontends, including the GPU-frame rows (run id).
- [ ] The JSONL under `build/ui-shell/` loads through `LedgerDocument`.
- [ ] `make lint format-check` and `git diff --check` pass. Lane CI is green under the policy.

#### B2. CX-UIA-01 remainder (about 3 h, beside or after B1)
**Branch:** `codex/cx-uia-01`. **PR title:** `[CX-UIA-01] ui-0-focused-gate remainder: runbook, setup script, target coverage test`.

**Owned paths:**
- `docs/qualification/ui-agent-runbook.md` (new)
- `src/tests/python/test_native_gui_target.py` (new)
- `tools/ui/codex-setup.sh` (new)

**No Makefile change of yours.**
- `test-native-gui` is already on `main` (Makefile:301-316). It writes `build/skip-report-native-gui.json` and runs its own skip gate.
- Today the coverage rule fails, because `webgpu_child/*.btrc` are driven only by `test_native_webgpu_imports.py`, which `NATIVE_GUI_TESTS` does not select.
- Claude adds that module to `NATIVE_GUI_TESTS` in its next batch. If that line is not on `main` when you are otherwise done, add it as a `fragment: Makefile` commit; that takes the single CI slot as a main-tier run.

**Steps.** Do codex.md CX-UIA-01 steps 4–8.
- The coverage test parses `NATIVE_GUI_TESTS`, including the glob. It counts a `.btrc` as driven when a selected module does one of three things:
  - names its file or stem;
  - names a directory above it (a module naming `webgpu_child` drives every `.btrc` under it);
  - carries an f-string template that matches it as a glob, for example `f"MacOS{control}Conformance.btrc"`.
- Add an in-memory negative case.
- The test never names the runbook path in a literal.
- `codex-setup.sh` follows the §3.11 script, plus an Xvfb check and the header-reader build. The `.#platforms` GC root is opt-in only (`--platforms`), never the default (17.75 GB).

**Acceptance:**
- [ ] `nix develop --command python3 -m pytest src/tests/python/test_native_gui_target.py -q -rs` passes against `main`'s `NATIVE_GUI_TESTS`.
- [ ] `bash -n tools/ui/codex-setup.sh` passes. Running it twice succeeds, and the second run changes nothing (log in the PR body).
- [ ] `make test-native-gui` in the container has 0 failures and passes its own skip gate. Give pass and skip counts per frontend.
- [ ] `make lint format-check` and `git diff --check` pass.
- [ ] Lane CI is green, and `junit-macos-native-gui` shows the AppKit cases executed, not skipped.

---

### Task 3: docs tier (uncapped CI)
Only Markdown outside `TEST_READ_MARKDOWN`. Each item is its own packet and PR.

1. **CX-UIA-19 and CX-UIA-20 first, with CX-UIA-18 beside them.** They are separate files, marked parallel-safe with each other. D27's single writer chain covers the IView, IWindow and `App.btrc` contract files, not these drafts.
   - 19 and 20 also gate CL-P2-22, which gates the iOS and Android lifecycle packets.
   - CX-UIA-18's index file is `docs/design/ui-contracts/index.md`, not `README.md`, which is test-read.
2. **CX-UIA-13, split per platform:** `docs/design/native-ui-shells/{windows,ios,android}.md`, following codex.md steps 1–5. `ios.md` adds an iPadOS section:
   - multiple scenes (E16/N02);
   - size classes and split view, and Stage Manager;
   - the hardware keyboard and the pointer/trackpad;
   - `UIDeviceFamily [1,2]`;
   - which ios slots need iPad `device_class` evidence.
3. **CX-UIA-12, the GTK4/WebGPU pre-spike.** Do it early, because CL-UIA-12 waits for it.
   - Put the prototype on `codex/cx-uia-12-spike`: push it, open no PR, and never merge it.
   - The findings PR `codex/cx-uia-12` carries only `docs/design/linux-gtk4-feasibility.md`, so it runs the docs tier.
4. **CX-P2-01, 02 and 03:** the Windows OS-services, HTTP-transport and mobile-storage designs. Record the platform-adaptations Q-defaults as assumptions.

---

### Task 4: new-platform host spikes and Linux extras (lane tier, plus their own workflows; under the cap)

**Order:**
1. **CX-P1-05**, Android. It gates CX-P1-09 → CL-P2-09 → every new-platform shell.
2. **CX-P1-04**, iOS, with an iPad simulator destination and an Info.plist `UIDeviceFamily [1,2]` check.
3. **CX-P1-06**, then **CX-P1-03**.

**Superseded by D28 (workflow files):** Codex edits no workflow or `ci/proposed/` file. Claude adds lane workflows from the PR's `REQUEST` block. The workflow and `ci/proposed/` instructions in the next two paragraphs are history.

**They start now.** CL-UIA-02 is on `main`, and Q20's default ("Yes") is in force. If the token lacks the workflows permission, commit `ci/proposed/<name>.yml` (Q20's fallback); the evidence then arrives one batch later.

**Workflow files** follow the lane class: push and pull_request to `main`, each with a paths filter that includes the workflow file itself, plus `workflow_dispatch`. Add your row to `test_ci_workflow_contracts.py` (append-only). A matrix pytest job needs a `fragment: ci/tiers.toml` row, which makes that PR main tier.

**CX-P1-05 specifics:**
- `nix/platforms.nix` is the single version source; `sdkmanager` installs exactly its revisions on the KVM runner, and a test asserts they are equal.
- Hosted runners never enter `.#platforms`.
- 16 KiB pages are a Mac arm64 run (`MAC-P1-03`).

**Then, when the slot is free:**
- CX-UIA-06: `hosts.toml` with iPhone and iPad simulator `device_class` rows for `ios`, `test_native_ui_hosts.py` and `linux-desktop-check.sh`.
- CX-P1-02: `platform-adaptations.md` plus inventory cells. It is lane tier, because it edits `platform-inventory.toml`.

---

### Wave 2: after the follow-up is integrated on main
**No stacking.** Branch each packet from `origin/main` after Claude integrates the follow-up. You may draft locally earlier on a branch off `codex/cx-uia-02-shards`, then rebase onto `main` before opening the PR.

**Evidence comes from one shared "UI0 evidence run",** not from each PR's own lane run.
- When Claude pushes the batch that lands the follow-up, it dispatches:
  - `gh workflow run ci.yml --ref main -f focus=native-gui`;
  - `gh workflow run macos.yml --ref main -f focus=native-gui`.

  It posts both run ids on the follow-up PR.
- Every wave-2 packet records them as `[runs.ui0-linux-<id>]` and `[runs.ui0-macos-<id>]`, with `btrc_revision` set to that SHA.
- Download with `gh run download <id> -n junit-ci-native-gui` or `-n junit-macos-native-gui` within 14 days. If the artifacts have expired, dispatch one fresh pair, or ask Claude.

| Packet | Branch | Owned paths | Slots |
|---|---|---|---|
| CX-UIA-03 | `codex/cx-uia-03` | `operations/{IApplication,IApplicationWork,IWindow,IWindowKeyHandler,IView,IViewPointerHandler,IViewScrollHandler,IContainer,IGPUView,IDirectoryPicker,GUI}.toml` | 81 frozen ids (810 slots) + 15 pending factories (150); `GUI.rasterText` retired, not classified |
| CX-UIA-04 | `codex/cx-uia-04` | `operations/{IButton,IButtonAction,ITextField,ISelect,ISlider,ILabel,IStack,IGrid,IScrollView,IPanel,IImageView,IImageHandle,IProgressIndicator,ILevelIndicator,IFontFace}.toml` | 80 frozen ids (800) + 2 pending IFontFace (20) if in scope |
| CX-UIA-30 (new, ui-0-case-map) | `codex/cx-uia-30` | `cases/E01-E24.toml`, `cases/E25-E47.toml` | 470 |
| CX-UIA-05 (rescoped) | `codex/cx-uia-05` | `surface/{GUIModules,App,UI,Tray}.toml`; `src/tests/python/test_ui0_surface.py` (new) | proposals only |

**CI order.** Until CL-R-50 lands, each of these is a lane-tier PR, so their CI runs one at a time: 03, then 04, then 30, then 05. Authoring may overlap. Once CL-R-50 makes catalog-data PRs cheap, they stop counting against the cap.

**Rules for all four:**
- **No runner:** Windows, iOS and Android are `implementation = "missing"` with `evidence.status = "unavailable"`, and `covered_by = []` where no runner exists.
- **Pending ids** are classified in their owner's shard.
- **CX-UIA-30 baselines:**
  - E40 on Linux: implementation `partial`, evidence `implemented-unverified`, with a note citing the drop of the 4,097th event (the reproduction stays on CX-UIA-11's branch, D24);
  - E46: `missing` (`windowShouldClose` is always true; SDL closes on request);
  - E47: `missing`.
- **Acceptance:**
  - [ ] `nix develop --command python3 -m tools.qualification.ui_catalog check --strict` with the packet's `--owner` flags (CX-UIA-30: `--kind ui-case`) and `--junit ui0-macos-<id>=… --junit ui0-linux-<id>=…` exits 0. Retired slots are excluded.
  - [ ] `test_ui0_catalog.py` passes.
  - [ ] The PR body has a table of passed, implemented-unverified, source-only and missing counts per owner and platform.
  - [ ] Lane CI is green.
- **CX-UIA-05 specifics:**
  - Add no tables to `native-ui-api-inventory.md` and no `denominators.toml` fragment.
  - Proposed ids go in the `operations` lists of `family` rows, where they become pending.
  - Put the release proposal in the PR body (the ids, their count, and the sha256 from `Denominator.digest`), with `REQUEST(CL-UIA-24)`.
  - It integrates only after CL-UIA-24.

**Then, after CX-UIA-09 and the follow-up are both integrated:**
- **CX-UIA-10 ∥ CX-UIA-11.** These are plain dependencies, branched from `main`.
  - They take over `probes/{macos,linux}/` and `test_native_ui_shell_{macos,linux}.py`.
  - Their catalog output goes to `evidence/ui1-{macos,linux}.toml` as evidence, `test` records and notes.
  - A classification change to an operation or case slot goes into its owner shard. If that shard's packet is still open, ask its holder in the PR to carry the hunk (§3.3).
- **CX-UIA-07 last**, after CX-UIA-03, 04, 05 and 30 and CL-UIA-03.
  - Its doc-count case goes in a new `test_ui0_doc_counts.py`.
  - The first column of its "Broader surface" prose is never a backticked `Owner.member`.
