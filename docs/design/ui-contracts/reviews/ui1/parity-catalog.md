# CL-UIA-09 UI1 checkpoint: Parity and catalog review

Reviewed read-only on main `19f75abf` (2026-10-06) by an integrator review workflow (`wf_271409ca-5fd`). Verdict: **fix-first**.

## Summary

Parity holds for the claims the packet needs: macOS AppKit and Linux SDL under X11 pass every UI1 shell assertion on both compilers (reference and btrcc), plain and with ASan/UBSan. That is true in the evidence shards and again on current main 19f75abf, which already includes the batch 41 SDL patch and the batch 45 fixture change.

On macOS, I downloaded JUnit artifact 11354918053; its SHA-256 matches ui1-macos.toml:4. All four variants pass, and their observations are identical value for value per compiler: 100 cycles, 100 GPU frames, 100 restores, 0 provider or registration survivors, at most 1 private AppKit object, the same fixture accessibility identities, and the same gaps. Main 19f75abf re-ran all four in the macOS unit shard (run 37422912514, skip-report artifact 11399916021: all passed). On Linux X11, the four shard rows pass at 72592d36, and main 19f75abf passed all four under X11 with 4 workers and 100 cycles (run 37422912212, job 112136078860, skip-report artifact 11394289502). The Windows, iOS and Android exclusions are also symmetric across compilers.

Two findings block, and neither needs new evidence or code; both are resolved in how the decision is written and recorded.
- Wayland with sanitizers is proven for the reference compiler only. "Linux SDL" must be scoped to X11.
- The catalog schema has no field for milestone eligibility. Every direct encoding I tested is rejected by the loader or the host test. The packet's second acceptance line has to be met with an accepted note-only hosts.toml edit plus the decision record, and that wording amended.

The other gaps are the same on both compilers, so they are not parity defects: E46 is missing, E47 is fixture-only, Linux has no AT-SPI bridge, Tab delivery is unproven, the GPU view is outside Tab order and the accessibility tree, and E40 drops the 4,097th event.

## Findings

### Linux SDL under Wayland with sanitizers is proven for the reference compiler only (blocking)

docs/design/native-ui-catalog/evidence/ui1-linux.toml:17-21: reference linux-wayland-sanitized passed. :53-57: selfhost linux-wayland-sanitized has evidence status implemented-unverified, observed failed ('Restore 61 (zero-based) timed out'), recorded at 72592d36. The other three Wayland rows (:11-27) passed, also only at 72592d36. CODEX.md:271-283 says the libdecor 0.2.5 restore-61 timeout is still open and asks for 'Wayland 4/4 rows'. Batch 41 (claude-integration-record.md:480): 'The Wayland restore timeout inside libdecor stays open.' CI never runs Wayland: tools/virtual-display.sh:27 defaults to x11, and ci.yml:423 and the unit shard run under it. Main 19f75abf's skip report 11394289502 shows DISPLAY set, which means X11. The X11 rows are 4/4 on both compilers (ui1-linux.toml:29-51, plus 19f75abf CI). CLAUDE.md:1054 (Stage 31) requires the harness to pass on every provider × frontend × sanitizer.

**Recommendation:** Scope the decision to 'Linux on the shipping SDL provider under X11: both compilers, plain and ASan/UBSan'. Record Wayland as open, owned by the CX-UIA-11 residual. Do not write 'Linux SDL' unqualified. Closing Wayland needs all four Wayland rows re-run at a current revision; the three passing rows predate batches 41 and 45. When the selfhost-sanitized row is re-recorded as passed, update test_native_ui_shell_linux.py:66 from 21 recorded failures to 20.

**Adversarial verification:** refuted (carried, not blocking). The finding's facts are correct, but they describe a gap UI2 can carry, not something that stops UI2 entry for Linux SDL.

What checks out:
- In docs/design/native-ui-catalog/evidence/ui1-linux.toml, the selfhost linux-wayland-sanitized row (lines 53-57) is implemented-unverified with observed failed: restore 61 timed out. The other three Wayland rows passed, but only at 72592d36, before batches 41 and 45.
- tools/virtual-display.sh:27 defaults to x11, and ci.yml:267/423 run under it. CI on 19f75abf (run 37422912212) is green under X11 only.
- CODEX.md:271-283 and integration record line 480 both say the libdecor timeout is still open.

Why it does not block UI2 entry:
1. The reviewer's own fix keeps Linux SDL in UI2. It only narrows the wording to "X11, both compilers, plain and ASan/UBSan" and records Wayland as an open CX-UIA-11 residual. A wording fix in the decision record is not a blocker to entry.
2. CLAUDE.md:1054 is the Stage 31 exit. CL-UIA-10 closes Stage 31, not CL-UIA-09. That exit also asks for "accessibility bridges and tree artifacts from the start". Linux SDL has none on X11 either (a fixed "no bridge" label, E46 missing). If 1054 were the UI2 entry bar it would block the reviewer's own X11 scope too, so it cannot be that bar.
3. D27 starts the macOS and Linux-SDL halves of UI1–UI3 "as soon as its in-stage dependencies land". native-ui-parity.md:695 makes UI2 depend on "UI1 for the provider under test", and :691 says "Partial platform slices can unlock later work."
4. hosts.toml:59 accepts "Xvfb/X11 or weston headless/Wayland" for the linux-devcontainer automation route.
5. Wayland and X11 CI belong to a separate Stage 31 packet, CL-UIA-11 ("Linux GUI and audio CI shard under Wayland and X11"). It is parallel-safe with CL-UIA-09, not a precondition of it.
6. The root cause is a third-party bug, not a contract problem. The stall is in libdecor 0.2.5's GTK plugin (SDL_ShowWindow -> libdecor_plugin_gtk_dispatch -> poll(-1)). The standalone C probe LibdecorPending reproduces it with no BTRC, provider or GPU code. It hits once, at fresh restore 61, in one of four Wayland combinations, and touches none of UI2's surfaces (control events, executor, lifecycle). The fix is a dependency pin, which CODEX.md assigns to Claude, with Codex re-running the acceptance afterwards.

How CL-UIA-09 should take it: as a non-blocking precision note.
- Say Linux SDL is proven on X11 (4/4, re-proven by CI at 19f75abf) and on Wayland at 3/4 (stale, at 72592d36).
- Record the Wayland restore-61 failure as an open residual.
- Note that the assertion of 21 recorded failures in src/tests/python/test_native_ui_shell_linux.py drops to 20 when the selfhost Wayland sanitized row passes.

### The catalog has no milestone-eligibility field; direct encodings are rejected (blocking)

Packet acceptance (docs/workstreams/claude.md:5995): 'The catalog marks macOS and Linux-SDL as eligible for UI2.' No field can express that:
- Ledger classification fields are exactly parity, implementation, owner, regression, links, configuration, input, decision and note (tools/qualification/schema.py:478-488).
- `links` is a roadmap cross-reference (schema.py:95-96). families.toml already uses it to name each family's owning milestone (N01 has links ["N01","UI1"]), and test_ui0_catalog.py:1017-1018 requires that. E40's case row already links UI2 to mean 'belongs to UI2'.
- Evidence shards may carry only `note` (ui_catalog.py:533-535). Unknown files fail the LAYOUT check (ui_catalog.py:61-71).
- The loader never parses hosts.toml (README.md:7,16; ui_catalog.py:242 loops only families, operations, cases and evidence). test_native_ui_hosts.py validates it: exact top-level keys (:70-78), schema btrc.ui-hosts/2 (:79), allowed route keys (:85,91), status enum (:103), and blocked_by drawn from the CLAUDE.md appendix ids (:58-66,107-109).

I ran the real loader and validator on scratch copies:
- Rejected: an evidence-shard record with classification.links ["UI2"] or classification.decision ('evidence shard classification may contain only note'); a new file ui2-eligibility.toml ('unknown catalog file'); a families.toml field `eligible` ('unknown field(s) eligible'); a hosts route key `eligible_for`; a top-level hosts table `milestones`; blocked_by ["CL-UIA-22"] ('unknown PLAN item').
- Accepted: a note-only hosts edit with recorded_at bumped; note-only ui-case or test records in a new evidence/ui1-feasibility.toml.

hosts.toml's writer is CX-UIA-06 (README.md:16), and the file is outside CL-UIA-09's owned paths (claude.md:5975-5978). Those owned paths still say PLAN.md, which became CLAUDE.md under D28.

**Recommendation:** Record eligibility in docs/design/ui-contracts/ui1-feasibility.md and in the CLAUDE.md Stage 31 entry. Express it in the catalog with the note-only hosts.toml edit given in catalog_change; the validator accepts it with no test change. Amend the acceptance line to 'the decision record and the hosts.toml route notes record...'. Add hosts.toml to the packet's owned paths, or apply the edit as integrator. Do not put UI2 in `links`. It would be admitted, but it would conflate milestone ownership with readiness. Do not add note-only test records that stand in for a decision: they would read as tests with no recorded result.

**Adversarial verification:** refuted (carried, not blocking). The finding's facts are right, but nothing about them stops macOS or Linux SDL from entering UI2.

What holds:
- `Classification.FIELDS` is exactly parity, implementation, owner, regression, links, configuration, input, decision and note (`tools/qualification/schema.py:478-488`).
- `links` is documented as a roadmap cross-reference (`schema.py:95-96`).
- Evidence shards may carry only `note` (`ui_catalog.py:533-535`).
- `LAYOUT` rejects unknown paths (`ui_catalog.py:61-71`), and the merge loop skips `hosts.toml` (`ui_catalog.py:242`; README.md:7,16).
- `test_native_ui_hosts.validate_hosts` pins the exact top-level keys (:70-78), the schema `btrc.ui-hosts/2` (:79), the route keys (:85,91) and the status enum (:103). It also requires `blocked_by` ⊆ the CLAUDE.md appendix ids (:58-66,107-109).
- Family rows must link their own N-ID and a UI milestone (`test_ui0_catalog.py:1017-1018`). Several case rows already link UI2 in its "belongs to UI2" sense, for example `cases/E25-E47.toml:79,92`.
- So the catalog has no field that says "eligible for UI2". The literal acceptance line at `docs/workstreams/claude.md:5995` has no data field to land in.
- The packet's owned paths (:5975-5978) still say PLAN.md and do not include `hosts.toml`.

Why it does not block UI2 entry:
1. **No downstream consumer reads catalog eligibility.** CL-UIA-13 depends on the CL-UIA-09 packet (`claude.md:6160-6161`), and its inputs are the decision record and the drafts. CL-UIA-14 depends on the CX-UIA-21/22/23 branches. The repository has no "eligible" field or test anywhere in the catalog, its loader or its tests. A grep for "eligib" finds nothing UI2-gating.
2. **The substantive gate can be met in the packet's own paths.** Those are `docs/design/ui-contracts/ui1-feasibility.md`, with its review files and 0 unresolved blocking findings, and the Stage 31 entry. Under D28, PLAN.md anchors resolve to CLAUDE.md, which Claude owns.
3. **The finding supplies its own admissible encoding.** `validate_hosts` only checks that a route note is non-empty (:104) and that `recorded_at` is a date (:80). So a note-only edit to the `macos-hosted-correctness` and `linux-devcontainer-automation` routes passes with no test change. Those routes are already `status = "available"`, and the `hosts.toml` header defines that as "an eligible host, never a pass". Claude can apply this edit as integrator.
4. **The rest is wording Claude owns.** Changing ":5995" from "the catalog marks" to "the decision record and the `hosts.toml` route notes record", and fixing the stale PLAN.md path, are edits to Claude's own packet document. Neither needs a schema, loader or validator change.

So this is a real bookkeeping gap in how the checkpoint's acceptance is worded, with a ready fix. It is not a technical or contractual blocker of UI2 entry for macOS AppKit or Linux SDL.

### macOS AppKit: both compilers verified value for value, at the shard revision and on current main (non-blocking)

Artifact 11354918053 (run 37318960723, head 43b24996, expires 2026-10-19T15:30:23Z): native-gui.xml SHA-256 f132900e…8c08 matches ui1-macos.toml:4. Extracted from its ui1_macos_evidence properties for plain-python, plain-selfhost, sanitized-python and sanitized-selfhost:
- Each passes, with frontend reference or selfhost, btrc_revision 25a160f7, and build_mode plain or asan-ubsan.
- Each has cycles, frames and restores of 100; 0 provider or registration survivors; at most 1 private AppKit object; subview_totals {60}.
- Each has the fixture accessibility identities field (NSTextFieldCell/AXTextField), button (NSButtonCell/AXButton 'Commit') and scroll (NSScrollView/AXScrollArea).
- Each shows the same gaps: Tab order field×4, every pre-Tab context (False, False), and GPU view (accessibility-exposed False, accepts first responder False, direct focus True, reached by Tab False).

Current main: macOS run 37422912514, unit job 112136079609, skip report 11399916021 at revision 19f75abf. All four test_macos_native_shell variants passed. The log shows 9791 passed and 0 failed, with no skip for this test.

**Recommendation:** Cite both runs in the decision record. Copy the per-compiler table into the record, because both artifacts expire on 2026-10-19 and 2026-10-20 and the shard's condensed note is identical across its four records.

### Linux SDL X11: both compilers verified at the shard revision and on current main (non-blocking)

ui1-linux.toml:29-51: x11 plain and sanitized pass for reference and selfhost at 72592d36, with 100 cycles, frames and restores, and 0 handles and registrations. Current main: CI run 37422912212, unit job 112136078860, skip report 11394289502 (revision 19f75abf, runner linux-devcontainer, DISPLAY set). test_linux_native_shell[plain-python], [plain-selfhost], [sanitized-python] and [sanitized-selfhost] all passed under 4 workers on one Xvfb display, at the default 100 cycles (native_ui_shell_fixtures.py:183; nothing sets BTRC_UI_SHELL_CYCLES). That revision includes the batch 41 SDL selection-requestor patch and the batch 45 journey fix (2f94a67e).

**Recommendation:** Cite skip report 11394289502 as the current-tree X11 proof. The shard rows are historical local observations with build/ paths as artifacts. For durable per-compiler JUnit at the current fixture, dispatch `ci.yml -f focus=native-gui` and `macos.yml -f focus=native-gui`: those jobs upload junit-ci-native-gui and junit-macos-native-gui (ci.yml:428, macos.yml:388).

### The evidence shards predate the current fixture (non-blocking)

2f94a67e (batch 45) changed src/tests/native/gui/shell/NativeShell.btrc: journey steps 1, 4, 5 and 6 now wait up to 15 s for injected input. The shard provenance is 25a160f7 for macOS and 72592d36 for Linux. The 19f75abf unit shards record only pass or fail, not the JUnit observation properties, because PYTEST_ADDOPTS junitxml is set only in the native-gui jobs. Batch 45's own check ran 10 cycles, X11 only (integration record :507). Passing still implies every exercise_shell and summarize_macos_shell assertion held for each compiler at 19f75abf (native_ui_shell_fixtures.py:181-259; test_native_ui_shell_macos.py:44-138), including the 'no warning:' transpile check for both compilers (:95).

**Recommendation:** Either note in the record that the detailed observations are at 25a160f7 and 72592d36 and the pass/fail at 19f75abf, or take the native-gui dispatches above before recording.

### The macOS selfhost rows do not bind the btrcc binary that produced them (non-blocking)

ui1-macos.toml:20,32 (selfhost) have no compiler_digest or c_compiler. The artifact's provenance shows compiler_digest None for all four macOS variants. The Linux selfhost rows do carry compiler_digest sha256:373a1f75… (ui1-linux.toml:26,44,50). The writer, write_evidence (native_ui_shell_fixtures.py:161-172), never emits compiler_digest, so the Linux digests were added by hand. The Linux test records also use the bare id 'native-shell' (ui1-linux.toml:12…), which JUnitAdapter cannot bind, where macOS uses pytest node ids.

**Recommendation:** Codex follow-up, alongside CODEX.md:262-268 item (3): have write_evidence record the immutable_btrcc SHA-256 and the C compiler for selfhost rows, and give the Linux shard pytest node ids. Not required for UI2 eligibility, because btrc_revision pins the source btrcc is built from.

### Gaps that are identical on both compilers (no parity defect) must be stated as such (non-blocking)

- E46 is implementation missing, evidence source-only, for macOS and Linux on both compilers (cases/E25-E47.toml, E46 row). ui1-macos.toml:34-40 cites MacOSWindow.btrc:19. The harness requires the literal 'dirty-close=missing' (native_ui_shell_fixtures.py:205).
- E47 is 'fixture-only; stdlib missing' for every row (native_ui_shell_fixtures.py:255).
- On Linux the accessibility report is a fixed 'no bridge' string (probes/linux/ShellProbe.c:56; native_ui_shell_fixtures.py:215-216).
- E40 fails identically on both compilers at event 4,097 (ui1-linux.toml:89-291, 34 boundary and E40 records), pinned by test_native_ui_shell_linux.py:59-67. Its repair is CX-STDLIB-01; evidence/ui2-linux-e40.toml does not exist yet.

CLAUDE.md:1054-1055 (Stage 31 exit) asks for accessibility bridges and for E46 over 100 cycles.

**Recommendation:** The feasibility reviewers decide whether these block UI2. The record should say each one is absent or failed on both compilers, not proven on one.

### Tab delivery has no packet whose acceptance proves it (non-blocking)

CODEX.md:269-270 assigns Tab delivery to MAC-UIA-02. docs/workstreams/owner.md:1210-1212 limits MAC-UIA-02's acceptance to GPU timing rows. Its step 2, BTRC_UI_SHELL_PAUSE=1 (owner.md:1208), is read by no source file (grep finds it only in owner.md and packets.json). summarize_macos_shell reports Tab traversal as 'passed' only when every pre-Tab context is application-active and key-window (test_native_ui_shell_macos.py:109-113). All 300 contexts per compiler were inactive.

**Recommendation:** Do not cite MAC-UIA-02 as closing Tab delivery unless its acceptance gains a row requiring key_view_traversal 'passed' for both compilers, and the pause knob is implemented or dropped from step 2. The gap is the same on both compilers.

### Windows, iOS and Android are already blocked with the right ids; CL-UIA-22 cannot be a blocker id (non-blocking)

test_native_ui_shell.py:8-37 treats both compilers the same. The Windows transpile refuses with 'has no provider for target windows-x86_64', and the mobile rows are recorded unavailable with executed False. All six of those cases pass in JUnit 37318960723. hosts.toml already blocks those routes with CLAUDE.md appendix ids (CLAUDE.md:1456):
- windows-x64-ci [platforms-p1-host-windows, ui-1-windows-shell] (:87-97)
- windows-arm64-ci [tooling-windows-ci-arm64-llvm, ui-1-windows-shell] (:99-109)
- the iOS simulator routes, owner and GitHub (:137-160, :188-211)
- the Android emulator routes, owner and GitHub (:239-262)

test_native_ui_hosts.py:434-449 pins those blockers. CL-UIA-22's item is `ui-1-feasibility-review#windows-ios-android` (claude.md:6118), which is not an appendix id; the validator rejects it.

**Recommendation:** Cite these exact ids in the decision record. Name CL-UIA-22 as the owner of Win32 vs WinUI and Android Views vs GameActivity in prose only. Leave every blocked_by unchanged.

## Gaps UI2 and later carry

- Wayland: the selfhost ASan/UBSan row failed at restore 61 (libdecor 0.2.5 dispatch stall). The three passing Wayland rows date from 72592d36, and CI never runs Wayland. All four rows need re-running at the current revision (CX-UIA-11 residual, CODEX.md:271-283), then test_native_ui_shell_linux.py:66 changes from 21 to 20.
- E46 dirty-close veto is missing on both platforms and both compilers (MacOSWindow.btrc:19; the Linux fixture reports e46 missing).
- E47 is fixture-only on both compilers; the stdlib restoration contract is missing.
- Linux has no AT-SPI bridge: the probe prints a fixed 'no bridge' label (ShellProbe.c:56), and linux-devcontainer-tree stays blocked.
- macOS Tab delivery is unproven: all pre-Tab contexts were inactive on both compilers. MAC-UIA-02's acceptance (owner.md:1210-1212) does not cover it, and BTRC_UI_SHELL_PAUSE is not implemented.
- macOS GPU view: direct focus works, but it is outside Tab order and the accessibility tree on both compilers.
- E40: both compilers drop the 4,097th queued event; the repair is CX-STDLIB-01.
- macOS selfhost evidence has no compiler_digest; the Linux shard uses non-node-id test ids.
- Evidence expiry: JUnit artifact 11354918053 on 2026-10-19 and skip reports 11394289502 and 11399916021 on 2026-10-20. Copy the per-compiler values into the decision record.

## Catalog

No catalog field expresses milestone eligibility: not in the ledger, families.toml, operations, cases or evidence shards, nor in hosts.toml. Every direct encoding I tested is rejected (see the second finding). The smallest change the loader and tests accept is note-only, in docs/design/native-ui-catalog/hosts.toml, with the decision itself in docs/design/ui-contracts/ui1-feasibility.md and the CLAUDE.md Stage 31 entry:

1. Top level: `recorded_at = "2026-10-06"` (was "2026-10-05").
2. `[[routes]]` id = "macos-hosted-correctness" (hosts.toml:18-26): keep every key and append to `note`: " CL-UIA-09 (ui-1-feasibility-review, 2026-10-06): AppKit is eligible for UI2 on both frontends, plain and ASan/UBSan (run 37318960723; main 19f75abf skip report 11399916021). Tab delivery and GPU Tab/AX inclusion remain gaps."
3. `[[routes]]` id = "linux-devcontainer-automation" (hosts.toml:51-59): append to `note`: " CL-UIA-09 (ui-1-feasibility-review, 2026-10-06): the SDL provider under X11 is eligible for UI2 on both frontends, plain and ASan/UBSan (main 19f75abf skip report 11394289502). Wayland stays open until all four rows pass, after the selfhost ASan/UBSan restore-61 libdecor stall (CX-UIA-11 residual)."
4. No change to any `status` or `blocked_by`. Windows, iOS and Android stay blocked by ui-1-windows-shell, ui-1-ios-shell and ui-1-android-shell plus their host items, as test_native_ui_hosts.py:434-449 pins. Leave macos-hosted-tree `unverified`: flipping it to available is validator-accepted, but the GPU child is not in the accessibility tree. Leave linux-devcontainer-tree `blocked`: Linux has no bridge.

I validated this edit with validate_hosts. It needs no test change, and ui_catalog check is unaffected because the loader skips hosts.toml.

If a machine-checkable field is wanted later, the smallest consistent form is a new hosts schema btrc.ui-hosts/3 with an optional top-level `[[milestones]]` array of {milestone, platform, status, decision, blocked_by}. That changes test_native_ui_hosts.py:70-79 (top-level key set and schema string), adds validation of the milestone (UI1–UI11), the platform and blocked_by against plan_items, adds mutation cases to test_invalid_host_claims_are_rejected (:190-230), and updates README.md:16. ui_catalog.py and test_ui0_catalog.py would not change; the only hosts reference there is the placeholder at test_ui0_catalog.py:731. That is a CX-UIA-06 schema change and is not recommended for this packet.
