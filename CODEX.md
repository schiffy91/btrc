# CODEX: platform stdlib implementation lane

Updated 2026-10-06. Owner-directed plan, introduced by `CX-PLAN-01` on
`codex/stdlib-lane-plan`, based on main `9971ee1709b59b9185b9cf38b09693f52c2441f8`.
Read [AGENTS.md](AGENTS.md) for the shared architecture and parity rules.
[PLAN.md](PLAN.md#owner-update-separate-claude-and-codex-plans-2026-10-06) records
the owner update; Claude will migrate its remaining roadmap to CLAUDE.md.

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
| CX-STDLIB-01 (from UIA23) | Retain queued input; match popup hit testing to painted position; preserve text/selection on clipboard Cut failure; honor external hide/show rendering | `d6df2cb6335e122526204f0408602aeef6d31b66`; 84 native cases across staged revisions, plus final controls | Port to current main, wire normal driver, rerun both compilers and sanitizer/control cases on final source |
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
  remain open with their individual acceptance/dependency gaps. Reuse these
  branches; do not duplicate their tools or describe them as finished providers.
- The six Linux repairs and Mac alignment repair above remain unpublished
  experiments. Their existing regression wiring proposals and frozen evidence
  are retained; normal integration and current-source validation remain to do.

## Claude handoff: migrate and synchronize the plans

**Claude: the owner explicitly requested this split and the PLAN-to-CLAUDE rename.
Use this CODEX.md as Codex's active lane, not the older blanket start gates.**

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
normal checks pass. The rename is pending Claude's synchronization commit; this
plan update intentionally changes only PLAN.md and CODEX.md.
