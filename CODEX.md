# CODEX: platform stdlib implementation lane

Updated 2026-10-06. Owner-directed plan, introduced by `CX-PLAN-01` on
`codex/stdlib-lane-plan`, based on main `9971ee1709b59b9185b9cf38b09693f52c2441f8`.
Read [AGENTS.md](AGENTS.md) for the shared architecture and parity rules.
[CLAUDE.md](CLAUDE.md#owner-update-separate-claude-and-codex-plans-2026-10-06)
records the owner update; Claude's roadmap moved there from PLAN.md in batch 40.

## Goal and ownership

Deliver usable btrc standard-library providers on Linux, macOS, Windows,
iOS/iPadOS and Android. BTRSmith may verify a library feature, but app migration
and caller-count documentation do not gate unrelated stdlib repairs.

Codex owns the active queue here, provider implementation, dedicated regression
drivers/fixtures, and its existing platform test-host tools. Claude owns the
compiler pair, shared specs/generators/runtime/readers and integration. One writer
holds a file at a time. A current-interface repair may start independently of the
larger future packet that originally named the file. Check active claims first;
carry any shared-data changes as integrator fragments. Public API changes still
need explicit contract review and coordinated provider validation.

This owner update supersedes older scheduling clauses that make these repairs
wait for BTRSmith, documentation reconciliation, future widget contracts, or all
five native shells. Each new platform slice starts when its own demonstrated
prerequisites are ready. Missing native evidence remains missing; simulator,
emulator and hosted results never become physical-device qualification.

## Why the queue changes

- `CX-UIA-23` bundles the existing event-loss bug with future UI2 work. Its base
  `CX-UIA-21` waits for `CX-UIA-07`, which waits for BTRSmith caller counts. That
  chain is unnecessary for preserving the 4,097th queued input event.
- Grid/Stack resize fixes and Mac button alignment preserve existing interfaces;
  they need their real regression tests and integration, not all of Stage 34.
- The old `codex-ui-lanes.md` says no UI1 shell or shard loader exists, despite
  subsequent integrations. Determine readiness from current source and evidence.
- The stacked UI2 base is described as unable to build providers, while its
  dependents require its green acceptance. Claude must separate reviewed interface
  readiness from acceptance of the combined interface/provider tree. The packet's
  contradictory bootstrap requirements also need reconciliation.
- Real target/ABI, cache isolation and callback-lifetime defects remain blockers.
  Do not replace checked bindings with a second handwritten runtime or ABI.

These findings concern packet boundaries and scheduling. Compiler reviews have
found substantive parity and memory-safety defects; keep that review discipline.
Codex also treated blocked publication as a reason to stop all work. This queue
requires continuing another independent slice when one is blocked.

## First delivery queue

These are small repair units extracted from the named older packets, not claims
that those entire future milestones are complete. Check live path claims before
opening each implementation branch. Existing unpublished source revisions below
are preserved in the Codex workspace and recovery bundles; they are not yet
remote branches or merged code. Publish reviewable repair commits with their tests.

| Unit | Outcome and scope | Starting evidence | Remaining acceptance |
|---|---|---|---|
| CX-STDLIB-01 (from UIA23) | Retain queued input; match popup hit testing to painted position; preserve text/selection on clipboard Cut failure; honor external hide/show rendering | `d6df2cb6335e122526204f0408602aeef6d31b66`; 84 native cases across staged revisions, plus final controls | Port to current main, wire normal driver, rerun both compilers and sanitizer/control cases on final source; catalog: a new `evidence/ui2-linux-e40.toml` shard plus the E40 hunk in `cases/E25-E47.toml`, carried per WORKSTREAMS §3.3 step 4 ([catalog README](docs/design/native-ui-catalog/README.md)) |
| CX-STDLIB-02 (from UIB26) | Grid and both Stack orientations invoke child layout so scroll offsets clamp after resize | Combined `0f6f3448967720480365d43980c74baf7280b7e4`; 40/40 final-source native cases | Port combined repair, wire normal driver, verify actual pixel/offset behavior and fixture discovery |
| CX-STDLIB-03 (from UIB18) | Explicit Mac button alignment survives title/symbol updates; defaults preserved | `f6071c8aa1c42998fd1db3266d078285798299af`; source reviewed/formatted only | Wire actual AppKit fixture; compile and execute on macOS through both compilers; no native pass yet |
| CX-STDLIB-04 | Reject an invalid Linux grid replacement without losing the old child | Source finding: Linux detaches before validating; Mac validates/rolls back | Reproduce with an already-parented replacement; check old child identity/rendering, valid replacement, null clear and ownership cleanup; fix only after reproduction |
| CX-STDLIB-05 | Keep scrollbar geometry valid in a tiny viewport | Source candidate: 24-point minimum thumb can exceed available track | Reproduce at small/normal sizes, overflow/non-overflow and actual pointer/pixel behavior; no executed failure or fix claimed |

### Repair files and test admission

CX-STDLIB-01 production files are
`src/stdlib/GUI/Linux/{LinuxApplication,LinuxSelect,LinuxTextField,LinuxWindow}.btrc`.
Its existing event fixture is under `src/tests/native/gui/linux/`; the other probes
are under `src/tests/native/gui/ui2/probes/linux/`. Move the existing collector into
`src/tests/python/test_native_ui_linux_spike.py` with the established platform,
native-reader and display guards; remove the old collector to avoid duplicate
unguarded collection. The historical `spike` spelling does not relax acceptance.
Its catalog update is the new `docs/design/native-ui-catalog/evidence/ui2-linux-e40.toml`
shard plus the E40 hunk in `docs/design/native-ui-catalog/cases/E25-E47.toml`.

CX-STDLIB-02 owns `src/stdlib/GUI/Linux/{LinuxGrid,LinuxStack}.btrc`, the existing
`src/tests/native/gui/layout/linux/{LinuxGridScrollResize,LinuxStackScrollResize}.btrc`
fixtures and `src/tests/python/test_native_ui_layout_resize.py`. Use the combined
repair rather than applying both the original Grid-only and combined patches.
CX-STDLIB-04 follows this unit because both edit LinuxGrid; reserve any needed
LinuxViewNode validation change explicitly. CX-STDLIB-05 owns LinuxScrollView and
its dedicated fixture/driver, independently of the grid writer.

CX-STDLIB-03 owns `src/stdlib/GUI/MacOS/MacOSButton.btrc`,
`src/tests/native/gui/controls/macos/ButtonAlignment.btrc` and the narrow fixture
registration in `src/tests/python/test_native_gui_appkit.py`, coordinated with any
active AppKit harness writer.

The Linux driver names already match the normal native-GUI target's selection.
Keep the fixture-discovery guard active. These repair units include their test
admission work; shared expected-skip data still travels as a reviewed integrator
fragment with actual node IDs and capability reasons. No Makefile or workflow edit
is needed for these Linux drivers. Do not publish a known-red normal gate or hide
an unwired fixture. Old passing counts do not validate a newly ported tree.

## Platform slices beyond the repairs

| Platform | Next concrete checkpoint | Actual dependency and evidence |
|---|---|---|
| Windows | Recheck the smallest real SDK import, then Toolhelp/process thread count | Historical SDK reads succeeded but both compilers rejected a qualified function type in eight architecture/frontend cases. Recheck with current compilers; request the narrow paired codec repair if still failing. Preserve ABI qualifiers. Use real x64/ARM64 execution. |
| iOS/iPadOS | App-private file create/write/read and relaunch persistence through both frontends | Actual iOS target/provider/cache selection, required nongeneric Foundation ownership/calls, filesystem seam and a real Xcode simulator host. Full UIKit widgets are not prerequisites for this service. |
| Android | NativeActivity host execution, then app-private file create/write/read and relaunch persistence | NDK/SDK, correct target/provider selection, trusted host-derived roots, filesystem seam and emulator execution. Initial private roots need not wait for the complete Java UI/JNI stack. |
| Each mobile GUI | Lifecycle, one native button and one editable field with events and safe teardown | Checked UIKit/main-executor adapters on iOS; checked JNI/Looper/callback ownership on Android. GPU embedding and richer collection controls are subsequent milestones. |

Reuse the existing stdlib shell fixture as a small conformance app: window,
button, editable field, scrolling, clipboard, visibility and teardown. Attach
real platform adapters as they become executable. A plain C SDK probe or mock is
useful evidence for its limited purpose, not a delivered btrc provider.

The retained Android host in [PR35](https://github.com/schiffy91/btrc/pull/35) forks
C fixtures and excludes JNI/ART and arbitrary threaded-provider safety. Add a
proper in-process provider mode before general callback/audio tests. The iOS host
in [PR34](https://github.com/schiffy91/btrc/pull/34) is a short-lived C/POSIX entry,
not a UIKit scene loop. Neither proves completed mobile GUI support.

## Validation and progress reporting

- Use the cached Nix Linux environment for edit/test loops, actual SDL/X11/Wayland
  where supported, both compiler frontends and appropriate sanitizer checks.
  Serialize expensive local builds; independent agents may inspect and edit
  disjoint files while a gate runs.
- Build a source-matched compiler after compiler changes. Run focused red/green
  regressions during development and the required static/unit/integration gates
  on the final candidate. Preserve ordinary fixture discovery and skip accounting.
- Use native Mac/Windows/emulator hosts for OS behavior. This Linux environment
  cannot run Apple's simulator and lacks KVM for accelerated Android execution;
  Android cross-builds remain useful locally. No new workflow edits are authorized
  by this plan update.
- Batch meaningful corrections. The former four-push limit must not strand a
  verified repair; retain measured CI concurrency limits and avoid redundant
  dispatches. A busy hosted queue does not block independent local work.
- Report **implemented**, **locally tested**, **natively tested**, and **merged**
  separately. Every blocker names the smallest failing program/missing API, its
  owner and the next milestone it prevents. Never stop unrelated platform work
  merely because one prerequisite or approval is pending.
- Claude continues to integrate; Codex does not merge PRs or push main. Keep
  strict imports, structured IR, generated-source discipline, both-compiler parity,
  reviewed shared contracts and source-bound native evidence.

## Current handoff state

Checked against main `9971ee1` and the open PRs when preparing this plan:

- Mac evidence [PR54](https://github.com/schiffy91/btrc/pull/54) and
  [PR56](https://github.com/schiffy91/btrc/pull/56) merged in batch 36; Linux
  diagnostics [PR57](https://github.com/schiffy91/btrc/pull/57) merged in batch 38.
- Windows host hardening [PR58](https://github.com/schiffy91/btrc/pull/58), head
  `6ec9b9dc`, is open with final CI green and 16 native cases passing on each of
  x64 and ARM64. This is execution infrastructure, not a Windows GUI provider.
- HTTP [PR51](https://github.com/schiffy91/btrc/pull/51), head `0fa4c093`, and
  Windows services [PR52](https://github.com/schiffy91/btrc/pull/52), head
  `d77b4b14`, address their latest findings and have green final docs CI; contract
  approvals remain pending. That does not block unrelated Linux repairs.
- Windows ARM64 toolchain [PR53](https://github.com/schiffy91/btrc/pull/53), mobile
  hosts PR34/35 and accessibility [PR42](https://github.com/schiffy91/btrc/pull/42)
  remain open with their individual acceptance/dependency gaps, listed in the
  next section. Reuse these branches; do not duplicate their tools or describe
  them as finished providers.
- The six Linux repairs and Mac alignment repair above remain unpublished
  experiments. Their existing regression wiring proposals and frozen evidence
  are retained; normal integration and current-source validation remain to do.

## Active assignments carried from WORKSTREAMS (D28)

These assignments moved here from WORKSTREAMS.md and the old packet files in
batch 40. Old packet IDs stay for traceability; WORKSTREAMS.md §3.3.2 keeps the
path claims. Each entry names its source (a PR, branch or review comment), the
owner, the exact prerequisite and the next acceptance.

- **PR58, `CX-P1-06` Windows host hardening** (head `6ec9b9dc`). Owner: Claude.
  Prerequisite: none; final CI is green. Next: Claude integration (batch gate).
  It unblocks the `CL-P1-17` protocol freeze and the PR53 rebase.
- **PR53, `CX-P1-03` Windows ARM64 toolchain** (`codex/cx-p1-03`, head
  `958d309b`). Owner: Codex (`tools/windows_toolchain/**`); Claude then adds the
  drafted `windows-arm64.yml`. Returned in batch 36: it duplicates
  `tools/target_hosts/windows` (`process_runner.run_windows` vs
  `executor.WindowsJob`, `arm64.TARGET/FLAGS` vs `bundle.TARGETS`, `pe_arm64` vs
  `bundle.pe_machine`). Prerequisite: PR58 integrated. Then rebase on main, use
  `WindowsJob` and the executor gate, and drop the ephemeral-runner/taskkill
  path. Non-blocking fixes: VsDevCmd `1>&2`; vswhere `-requires` ARM64 and Clang
  with `installationVersion`; an overall deadline in `native()`; the README.
  Next acceptance, on `windows-11-arm` (nothing has run there yet): PE ARM64
  with a byte-identical 3-stage bootstrap; byte-identical C from cross and
  native builds; `msvc_probe` cl.exe ≥19.40; an MSVC-ABI hello; a wgpu smoke.
- **PR34, `CX-P1-04` iOS simulator test host** (`codex/cx-p1-04`, head
  `55a71b8c`, CI green, scope only). Owner: Codex for code; Claude for the
  review and for `host-ios.yml` on macos-15 (`REQUEST(CL-R-38)`), running the
  six commands in the PR. Prerequisite: Claude reviews the repair (bounded
  launch deadline, start/cancel handshake, late-identity reaping); returned in
  batch 23 and not re-reviewed since. Next acceptance: 12 fixtures ×
  spawn/app × iPhone/iPad, plus one repeated app invocation per class (50
  executions), with Xcode/runtime provenance and `UIDeviceFamily [1,2]`. This is
  the real Xcode simulator host the iOS private-file slice needs. Afterwards:
  `CX-P1-08` (needs `CL-P1-17`, `CL-P1-13`, `CL-P1-16`), `REQUEST(CL-P1-17)`
  (protocol) and `REQUEST(CL-P1-21)` (entry symbol).
- **PR35, `CX-P1-05` Android host** (`codex/cx-p1-05`, head `628a4a54`, CI
  green, scope only). Owner: Codex (`tools/target_hosts/android/**`); Claude for
  the review, `host-android.yml` and the i686 shell issue. Prerequisite: Claude
  re-reviews the repair (returned in batch 23), then adds `host-android.yml`
  from the PR's `REQUEST(CL-REQ)` KVM spec (API 29/36, SDK packages and verify,
  cache key). `REQUEST(CL-P1-02)`: the `.#platforms` shell's i686 compatibility
  builder fails on cloud kernels. Next acceptance: API 29 and 36 KVM emulators
  boot and pass shell and NativeActivity modes, with boot/install/launch
  timings. Later, the in-process provider mode named above.
- **PR42, `CX-UIB-07` accessibility spike** (findings head `6d62e046`, docs CI
  green; prototype `codex/cx-uib-07-spike` `0d6127a6`). Owner: Codex for the
  note, Claude for the decision. macOS run 37217909473 failed at compile in both
  frontends: a managed NSView passed as raw `void*`. AX trust is unknown.
  `REQUEST(CL-UIB-09)` asks for a nonescaping mutable NSView adapter boundary,
  but `CL-UIB-09` depends on this packet's gap list and Stage 29 interop step 6,
  so the two wait on each other. `REQUEST(CL-UIB-12)` covers D-Bus vtables after
  D23. Recommended next acceptance: land the findings note with AX trust
  recorded as "unknown, blocked on CL-UIB-09". Missing evidence stays missing
  (D28), and landing the note meets `CL-UIB-09`'s gap-list dependency. The
  native re-run follows `CL-UIB-09`.
- **PR51, `CX-P2-02` HTTP contract rev 4** (head `0fa4c093`) and **PR52,
  `CX-P2-01` Windows services design rev 4** (head `d77b4b14`). Owner: Claude.
  Prerequisite: none on Codex's side. Next: `CL-P2-01` round 4 (Claude: two
  adversarial reviewers, a parity reviewer and a verifier). On approval, the
  request lists become `CL-P2-02/03/04/14` scope. D28 lifts the push stop for
  further revisions.
- **`CX-C-01` follow-ups** (batch 26 comment on PR26; no PR yet). Owner: Codex
  (`tools/bench/scripts/ccompat_checkpoint.sh`,
  `src/tests/python/test_ccompat_checkpoint_script.py`). Prerequisite: none.
  They fail closed today. (1) Read the RED gate summary in a `finally` block,
  with a test. (2) Make parent budget runs opt-in (`--budget-parent`).
  (3) Record the QuietCheck verdict in `summary.json`. (4) The macOS `sun_path`
  is 104 bytes: shorten the paths or use `$TMPDIR`. (5) The dry-run `READER=`
  placeholder and the `BTRC_NATIVE_TARGET`/`SYSROOT` record. Acceptance: one
  small PR with tests, before `MAC-C-02` uses the script.
- **`CX-UIA-10` follow-ups** (batch 36 comment on PR54; no PR yet). Owner: Codex
  (`src/tests/native/gui/shell/probes/macos`, the evidence shard).
  Prerequisite: none. (1) Add `wrong_field_identity` and `wrong_scroll_identity`
  mutation cases. (2) `native_controls[].ax_exposed` compares raw views
  (`ShellProbe.m:271`); map through `controlView`. (3) Test-record slot keys set
  frontend/variant values that `JUnitAdapter` never emits. Acceptance: the
  mutation tests fail on the old gate, and macos.yml `native-gui` is green.
  Separately, Tab delivery is unproven because all 300 contexts were inactive
  (`MAC-UIA-02`).
- **`CX-UIA-11` residuals** (after batch 38). Owner: Claude for the flake/nix
  pins (WORKSTREAMS §3.3.1 hotspots); Codex re-runs the acceptance once they
  land. Prerequisites: a libdecor 0.2.5 fix for the Wayland
  selfhost+sanitizer restore-61 timeout; `libdecor-0.pc` in the dev shell, so CI
  compiles `LibdecorPending`; a pinned SDL fix for the X11 BadWindow clipboard
  crash. Per-worker Xvfb is an integrator mitigation. Next acceptance: Codex
  re-runs the Wayland acceptance row and the `LibdecorPending` CI build; Wayland
  4/4 rows and the X11 clipboard probe pass.
- **`CX-P1-02` platform inventory.** Owner: the owner (sign-off), then Codex
  (the 58 cells in `platform-inventory.toml`) and Claude (the
  `platform-parity.md` totals fragment). Prerequisite: the owner's sign-off on
  `platform-adaptations.md` (WORKSTREAMS §7 Q9). The platform slices above
  assume those adaptation defaults. Acceptance: `test_platform_inventory`
  passes with the cells applied.
- **Claude `CL-REQ` packets awaiting Codex's minimal repros.** Neither failure
  is recorded on GitHub yet as a REQUEST, PR comment or issue (open and closed
  PRs 26–59 were searched).
  Codex posts each repro: the command, run through both frontends. Claude then
  opens the `CL-REQ` packet and owns the paired fix. Acceptance: a paired fix in
  both compilers plus a regression.
  - The catalog partition assertion (handoff step 6).
  - The Windows SDK qualified function type, which both compilers rejected in
    eight architecture/frontend cases (the Windows slice above).
- **Not active, carried.** Owner: Codex.
  - `CX-UIB-08` follow-up (batch 32): the 100,000-record fixture has 989
    repeated sort keys and only 8 distinct titles. Add a tie-break or richer
    titles before `CX-UIB-28` consumes the digest.
  - `CX-UIA-05` (broader surface): startable, since `CX-UIA-02` and
    `CL-UIA-24` landed, but unclaimed. Stage 30; it gates nothing under D28.
  - `CX-UIA-07`: unclaimed. Stage 30; it gates nothing under D28.

## Claude handoff: migrate and synchronize the plans

**Done in batch 40 (2026-10-06).** The owner explicitly requested this split and
the PLAN-to-CLAUDE rename, and Claude carried it out in batch 40. The six steps
below are kept as the record. This CODEX.md is Codex's active lane, not the
older blanket start gates.

1. Integrate this owner-directed update. Reconcile D27, WORKSTREAMS and the older
   Codex packet/lane files with D28 instead of making Codex re-request approval for
   this split. Keep old packet IDs as traceability; split existing-contract repairs
   from unfinished feature expansions. Move any remaining active Codex-owned work
   into CODEX.md and link to it rather than maintaining competing task queues.
2. **Preserve AGENTS.md.** CLAUDE.md currently points to it as a symlink. Replace
   that symlink deliberately when moving the Claude roadmap from PLAN.md into a
   regular CLAUDE.md file; never write the roadmap through the symlink. Keep an
   explicit shared-instruction import/reference to AGENTS.md at the beginning.
3. Retain roadmap decisions, historical evidence and stable stage/decision anchors
   in the moved document. Keep PLAN.md as a compatibility pointer with stable
   anchors and onward links, or update all active links/consumers in the same migration.
   Do not alter the frozen `docs/design/plan-reference.md` or its `ref:N` meaning.
4. Audit AGENTS.md, WORKSTREAMS, both workstream assignment files, UI lane notes,
   templates, scripts and tests for PLAN/CLAUDE/CODEX references. PLAN.md is read
   by tests and named in CI's test-read Markdown classification. Move those
   references and their classification consistently; the rename must not make
   executable policy look like untested prose. Workflow changes, if required,
   remain Claude's task under the owner's existing restriction.
5. Synchronize by linking, not copying: CLAUDE.md holds Claude's compiler/runtime
   queue and integration record; CODEX.md holds Codex's stdlib queue/results;
   WORKSTREAMS holds shared path claims and cross-agent dependencies. A handoff
   records source/PR, exact prerequisite, acceptance and owner. Update the relevant
   plan when an integration or blocker resolution changes readiness.
6. Prioritize the smallest shared unblocks: current regression admission/skip
   fragments; the already reported catalog partition assertion; Windows SDK
   function representation in both compilers; target/environment and cache
   isolation; then each platform's actual checked callback/lifecycle seams. Check
   active compiler branches before assigning them. Do not duplicate the current
   `CL-P1-05` target-data-model work or claim it is already complete.

Migration acceptance: AGENTS remains intact and loaded, CLAUDE is a regular plan
file with the shared rules referenced, all active Codex assignments have one
canonical home here, old links and test-read consumers are resolved, and the
normal checks pass. The migration landed in batch 40: CLAUDE.md is a regular
file importing AGENTS.md, PLAN.md is a pointer, the Progress log is in
[docs/design/claude-integration-record.md](docs/design/claude-integration-record.md),
and the tests that read the roadmap now read CLAUDE.md.
