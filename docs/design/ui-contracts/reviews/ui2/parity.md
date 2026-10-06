# CL-UIA-13 UI2 contract review: Parity review

Reviewed read-only on main `f6c2f2ae` (2026-10-06) by an integrator review workflow (`wf_b7573fea-5df`). Verdict: **fix-first**. Every finding raised as blocking was adversarially verified; none was confirmed, and each is closed by a decision in [ui2-approved.md](../../ui2-approved.md).

## Summary

I reviewed parity for CL-UIA-13 read-only on main f6c2f2ae. Probes ran through the reference compiler at HEAD and through a btrcc. That btrcc was built today from 3ca9baa6, which is main 19f75abf plus the stage17/c2-l2 compiler lane. It has no stdlib or runtime diff against 19f75abf, and f6c2f2ae only adds docs on top of 19f75abf. I cross-checked two results with the 2026-10-03 btrcc bundle.

Most of what the drafts propose works today on both compilers, with identical results. That covers the value classes, nullable string keys, exact long long identity, enums, Vector-owned option models, CallbackScope subscriptions, UIRangeAdjustment/UISemanticRange reuse (2^53+1 is exact), and a mutex-guarded worker publisher called through an interface from a spawned thread. Three items block approval as drafted. Each can be fixed by a decision recorded in ui2-approved.md, and none needs a compiler change:
1. The executor's typed payload, with its "maximum payload bytes", cannot be generic in either compiler (`implements I<T>` is a parse error), so it must be frozen as a fixed non-generic record.
2. `IApplication.attachHost`, `createPublisher` and `schedule` cannot be reached from portable code. The facade-initialized application lives in a package-private slot. So UI1 condition (1) needs GUI facade entries.
3. `BackgroundJobExecutor.subscribeCompletionReady` cannot be a UI catalog operation id. The drift gate fails on it.

The non-blocking findings fix the shape of three things:
- **Lifecycle and executor outcomes** must be owning classes, not rich enums. btrcc rejects `Vector<class>` rich-enum payloads, and on both compilers a rich-enum payload is a shallow borrow (ASan reports a heap-use-after-free on return).
- **Typed receivers** should not all be called `invoke`. Neither compiler has overloading, and lambdas cannot implement an interface.
- **The cleanup lease** must use raw `Atomic<uint>` cells from an `AtomicBuffer`. A lease reached through a managed field is detached before `__del__` when its holder is collected in a cycle. Dropping the last reference to a component that owns a CallbackScope on a worker aborts.

On the catalog side, the GUI ids are representable as amendment `[[additions]]`. The loader admits all 39 new ids (56 pending in total), and the drift gate passes on a simulated landing with `[current]` 20/31/191. CX-UIA-21's owned paths lack the amendment file, though. Adding UI2 to E42 and E46 is admitted; E01–E04 have no milestone link at all and should get UI2 too.

The index.md conflicts (terminal capacity per interaction; what text eligibility loss cancels) have no parity dimension: either choice can be expressed on both compilers.

Probes are in the review workspace (not retained) parity/ (run.sh drives both compilers, then cc and a run). Catalog trials are trial.py, trial2.py and trial3.py in .../work/catalog/, run against a scratch copy of the shards with the real loader and the drift-gate functions.

## Decisions proposed

- Parity evidence comes from the reference compiler at repo HEAD f6c2f2ae and from a btrcc (built 2026-10-06 11:47 from 3ca9baa6 = main 19f75abf + stage17/c2-l2). git diff 19f75abf..3ca9baa6 shows no src/stdlib or src/runtime changes, and f6c2f2ae only adds docs after 19f75abf. The btrcc-only rich-enum gap and the diagnostic line offset were reproduced on the older 2026-10-03 btrcc bundle, so they are not artifacts of the C2 lane.
- Every runnable probe was transpiled by both compilers, then built with cc -std=c11 -pthread and run. The rich-enum escape was confirmed with -fsanitize=address. BTRC_CACHE_DIR and TMPDIR pointed to scratch, and nothing was written into the repository.
- The catalog was checked with the real UICatalog loader and the real drift-gate functions from src/tests/python/test_ui0_catalog.py (verify_surface, verify_outside_interfaces), run against a scratch copy of docs/design/native-ui-catalog with a trial amendment. The simulated landing inserts the proposed declarations into the in-memory GUI sources only.
- The executor's typed payload is rated blocking because the draft's 'maximum payload bytes' plus 'plain-data payload' can only be built by erasing the type (Span or void* plus a size) or with generic interface implementation, which neither compiler supports. The fixed non-generic UIWorkRecord route is proven on both compilers and resolves it without compiler work.
- The facade gap is rated blocking because UI1 condition (1) asks for host attachment 'without a private bridge', and both compilers refuse to import the package-private application slot.
- BackgroundJobExecutor.subscribeCompletionReady is rated blocking only as a catalog id. The hook itself is expressible: a worker calling an interface method works on both compilers.
- Using rich enums for outcomes, giving every receiver the same `invoke` name, writing optional enums as `T?`, missing 64-bit atomics, and the cleanup-lease form are rated non-blocking, because a form both compilers accept exists and is recommended for each.
- The two known index.md conflicts (terminal capacity per interaction; what text eligibility loss cancels) are left to the feasibility reviewers and the reconciler: either answer can be written on both compilers.

## Findings

### Executor payload: a typed generic IUIWorkPublisher/IUIWorkReceiver cannot be written in either compiler; 'maximum payload bytes' forces byte erasure (blocking)

Draft: IUIWorkPublisher.tryPublish(UIWorkRecord record) -> UIWorkAdmission, where UIWorkRecord is a fixed realtime-POD struct { unsigned long long generation; unsigned long long sequence; unsigned long long key; int kind; long long value0; long long value1; }. IApplication.createPublisher(int capacity, IUIWorkReceiver receiver, CallbackScope owner) -> UIWorkPublisherOutcome (a class holding the publisher and an ICallbackRegistration). The receiver gets a UIWorkDelivery class holding the copied record and its receipt identity. Large results are fetched from their owning job slot, never sent as payload.

The draft gives `IApplication.createPublisher` 'capacity, maximum payload bytes, delivery receiver and lifetime scope', `IUIWorkPublisher.tryPublish` a 'bounded plain-data payload', and `IUIWorkReceiver.deliver` an 'immutable delivery snapshot' (docs/design/ui-contracts/ui2-executor.md:47-50, 77-82). It also leaves the signatures open: 'The payload/writer ABI needs the ownership review below before signatures freeze' (:41).

Why the generic form fails on both compilers:
- Probe GenericInterfaceImplements.btrc, `class ProgressReceiver implements IUIWorkReceiver<ProgressRecord>`: reference prints `error: Expected LBRACE, got LT '<'` at 7:50; btrcc prints `error: Expected LBRACE, got LT '<' at 7:50`.
- The generic-class version (GenericPublisherPod.btrc, `class UIWorkMailbox<T> implements IUIWorkPublisher<T>`) fails the same way on both.
- The grammar allows `implements ident_list` only (src/language/grammar.ebnf:201-203). The corpus already pins the parse error (src/tests/generics/GenericInterfaceImpl.btrc:5-7).
- Generic interface values are rejected (docs/known-language-gaps.md:290).
- Methods cannot be generic (grammar.ebnf method_rest).
- Static methods on generic classes are rejected (known-language-gaps.md:14).

Forms both compilers accept:
- (a) A non-generic `struct UIWorkRecord { unsigned long long generation; unsigned long long sequence; int kind; long long value; }` passed through a non-generic `IUIWorkPublisher.tryPublish(UIWorkRecord)`. A spawned worker publishes 1,000 records into a pthread-mutex-guarded `OwnedBuffer<UIWorkRecord>` that the UI thread drains. WorkerPublisherStruct.btrc prints `PASS: worker publisher struct` on both compilers.
- (b) `Span<unsigned char>` through an interface. SpanPayloadInterface.btrc passes on both, but the payload is type-erased.

**Recommendation:** In ui2-approved.md, freeze form (a) and drop the 'maximum payload bytes' parameter. The fixed record carries identity plus a few scalars, and large results stay with their owner (the BackgroundJobCompletion path), as the draft already intends (:79-82). Do not freeze form (b): that would freeze type erasure into the public API. If typed payloads are required, CL-REQ-UI2-A (generic interface implementation in both compilers) must land before the signature freezes.

**Adversarial verification:** not a blocker; closed in the approved record. The language facts in the finding hold, but they do not block approval and the draft does not need revising.

The facts I confirmed:
- grammar.ebnf:201-203 allows only `implements ident_list`.
- src/tests/generics/GenericInterfaceImpl.btrc:5-7 already pins the `implements X<T>` parse error.
- known-language-gaps.md lists static methods on generic classes as rejected, and closed gap 3 (around line 290) says generic interface values remain rejected.
- My own probe of `class ProgressReceiver implements IUIWorkReceiver<ProgressRecord>` fails in the reference compiler with "Expected LBRACE, got LT '<'" at 9:50.
- A non-generic POD struct with `unsigned long long`/`int`/`long long` fields passes through non-generic `IUIWorkPublisher.tryPublish(UIWorkRecord)` and `IUIWorkReceiver.deliver(UIWorkRecord)`. It compiles under the Python compiler and the C runs, printing PASS. So form (a) is expressible.

Why this is not blocking:
1. The finding attacks a design the draft never makes. ui2-executor.md proposes no generic `IUIWorkPublisher<T>` or `IUIWorkReceiver<T>`, and no `<T>` appears anywhere in the three UI2 drafts or index.md. The draft speaks only of a "bounded plain-data record/payload" (:48, :77-79). `UIWorkRecord`, `UIWorkAdmission` and `UIWorkPublisherOutcome` are not in the repository at all; the finding's "Draft:" line is the reviewer's own proposal.
2. The draft leaves the signature open and hands the decision to this review. Line 41 says "The payload/writer ABI needs the ownership review below before signatures freeze". Lines 267-270 tell CL-UIA-13 to "approve or revise operation names, bounded native-writer transport...", and add that interface edits wait for that approval. Picking a fixed, non-generic POD record in ui2-approved.md is therefore exactly the choice the drafts delegate. The finding's own recommendation ("In ui2-approved.md, freeze form (a)") is an approved-record decision, not a draft revision.
3. "Maximum payload bytes" does not force byte erasure. With a fixed record, the per-record byte cap is either trivially sizeof(record) and can be dropped from the frozen signature, or it is read as the mailbox byte budget the draft already declares separately (:86, "mailbox bytes"; E24 at :247, "declared capacity and byte limit"). Either reading is recorded in ui2-approved.md without Codex changing a draft.
4. Large results stay with their owning job slot and are fetched through the BackgroundJobCompletion path (:79-82, :153-160), so the drafts already intend a small identity/scalar record. Typed generic payloads are not required, and CL-REQ-UI2-A is not a prerequisite.

The approved record should note the constraint: no generic publisher/receiver, no type-erased Span payload in the public API, a fixed POD record, and the byte limit read as the mailbox budget. That is a recording choice, not an open blocker.

### IApplication.attachHost, createPublisher and schedule cannot be reached from portable code, so UI1 condition (1) cannot be met as drafted (blocking)

Draft: class UIHostAttachment attachHost(IApplicationHost host) { GUIProvider.requireUIThread(); return GUIApplicationSlot.require().attachHost(host); } — and the same for createPublisher and schedule. Catalog ids: GUI.attachHost, GUI.createPublisher, GUI.schedule, plus the IApplicationHost.* methods.

- `GUI.initialize` stores the only application reference in `GUIApplicationSlot.active` (src/stdlib/GUI/GUI.btrc:33-38; ApplicationSlot.btrc:3-7, described there as 'Package-private').
- ApplicationSlot is not in GUI's exports (src/stdlib/GUI/btrc.toml:5).
- The facade wraps only post, postAfter, requestQuit, run and close (GUI.btrc:82-102).
- The shared shell journey uses only the facade (src/tests/native/gui/shell/NativeShell.btrc:59, 84, 163).

Probe HostAttachReach.btrc (`import Library.GUI.ApplicationSlot;`) is refused by both compilers:
- reference: `module 'src/stdlib/GUI/ApplicationSlot.btrc' is private to package 'btrc_stdlib_gui'; import an exported module`
- btrcc: `package resolution failed: module '.../GUI/ApplicationSlot.btrc' is private to package 'btrc_stdlib_gui'`

The executor draft lists only `IApplication.*` ids (ui2-executor.md:45-58). ui1-feasibility.md:29-31 requires attachHost to be frozen so that the iOS and Android shells can run the shared journey 'without a private bridge'.

**Recommendation:** Add facade entries `GUI.attachHost`, `GUI.createPublisher` and `GUI.schedule`. Each calls requireUIThread and forwards to the slot, as `GUI.post` does. Catalog them as `[[additions]] owner = "GUI"` (CatalogAmendments.declaration wraps GUI owners as `class GUI {...}`). Freeze `IApplication.attachHost`, the facade entry and the `IApplicationHost` adapter interface provisionally, with Windows and Android marked provisional per condition (2).

**Adversarial verification:** not a blocker; closed in the approved record. The finding is factually correct, but it does not block approval. The approved record can close the gap without Codex revising a draft.

What holds:
- GUI.initialize stores the only application in GUIApplicationSlot.active (src/stdlib/GUI/GUI.btrc:33-38). ApplicationSlot.btrc:3-7 calls that slot package-private.
- ApplicationSlot is missing from the exports in src/stdlib/GUI/btrc.toml:5. Both compilers refuse a private import with the quoted messages (src/compiler/python/frontend/packages.py:1071, src/compiler/btrc/frontend/Packages.btrc:1954).
- The facade has no accessor for the application. It forwards only factories plus post, postAfter, requestQuit, run and close (GUI.btrc:40-102). Even pollClose and isRunning have no facade twin.
- The shell journey uses only the facade (NativeShell.btrc:59, 163-194).
- ui2-executor.md:45-58 proposes only IApplication.* ids for createPublisher, schedule and attachHost. As drafted, code outside the package could not reach them.
- The catalog keeps facade ids separate from IApplication ids (native-ui-catalog/operations/GUI.toml has GUI.post, GUI.postAfter, GUI.run and so on). So the GUI.* ids really are missing from the proposal.

Why it does not block:
- The executor draft says its names are "proposed catalog ids, not declarations to copy into production" (ui2-executor.md:40). Its review clause says "CL-UIA-13: approve or revise operation names" (ui2-executor.md:267-270).
- The control-events draft already treats facade twins as decisions for the approved interface diff. It says `IApplication.createSlider` and `GUI.createSlider` need a reviewed compatibility decision whose ledger inventory "must be part of the approved interface diff" (ui2-control-events.md:294-300).
- CX-UIA-21 writes the production interface from ui2-approved.md (index.md:5-7), not from the drafts.
- The fix is therefore a provisional row in the approved record. Add GUI.attachHost, GUI.createPublisher and GUI.schedule, each calling requireUIThread and then forwarding to the slot, as GUI.post already does (GUI.btrc:82-84). Freeze IApplication.attachHost and IApplicationHost provisionally, with the Windows and Android rows provisional under UI1 condition (2). This is the reviewer's own recommendation.
- The fix stays inside the drafts' semantics. Each facade entry forwards to an IApplication operation the draft already defines, so no executor, lifecycle or control rule changes. The iOS and Android shell notes (native-ui-shells/ios.md:19-26, android.md:23-28) leave the GUI.run and host-entry route to the UI2 decision, so adding a facade route contradicts nothing.

Treat it as a required item for ui2-approved.md, not as a blocker that needs Codex to revise a draft.

### BackgroundJobExecutor.subscribeCompletionReady cannot be a UI catalog operation id (blocking)

Draft: Catalog: BackgroundJobExecutor.subscribeCompletionReady is not a ui-operation. Its acceptance is the BackgroundJobs regression <test id>, cited in cases/E01-E24.toml E04 regression lists.

The executor draft proposes it as a catalog id (ui2-executor.md:58), and CX-UIA-21 step 4 adds 'catalog rows for the new operations' (docs/workstreams/codex.md:3816).

Trial on a scratch copy of the shards (catalog/trial.py):
- Written as an amendment addition (source BackgroundJobExecutor.btrc), the loader admits it (57 pending ids). It only parses the signature.
- The drift gate rejects it: 'portable GUI file drift: update the UI0 catalog'. test_ui0_catalog.py:83 reads only GUI/I*.btrc and GUI.btrc, so that file can never match the source.
- Surface proposals cover only the GUI, App, UI and Tray stems (tools/qualification/ui_catalog.py:53).
- An operations/BackgroundJobExecutor.toml shard without admissible ids fails with 'foreign owner has no admissible operations' (ui_catalog.py:432-435; trial2.py shows the same error for an undeclared owner).

**Recommendation:** Remove it from the UI catalog id list in ui2-approved.md. Specify it as a BackgroundJobs contract (BackgroundJobs/README.md) with its own regression tests, cite those tests as regressions on E04's case rows, and keep the provider-side wake endpoint as a GUI operation.

**Adversarial verification:** not a blocker; closed in the approved record. The facts in the finding are correct, but the issue does not block approval. Claude's own approved record fixes it, and no draft needs to change.

What holds, checked against main f6c2f2ae:
- The executor draft proposes `BackgroundJobExecutor.subscribeCompletionReady` as a catalog id (docs/design/ui-contracts/ui2-executor.md:58).
- CX-UIA-21 step 4 adds catalog rows for the new operations (docs/workstreams/codex.md:3816).
- **Amendment route fails.** `CatalogAmendments.methods` only parses the signature, so the loader would admit the id. The drift gate then fails. `sources()` in src/tests/python/test_ui0_catalog.py reads only `GUI/I*.btrc` and `GUI.btrc`. `verify_surface` asserts actual files equal expected files, so an addition whose source is BackgroundJobExecutor.btrc fails with "portable GUI file drift". An addition that names a GUI file but has the owner `BackgroundJobExecutor` fails the owner check instead, since no such GUI interface exists.
- **Surface route fails.** Surface proposals cover only the GUIModules, App, UI and Tray stems (`SURFACE_STEMS` and the `LAYOUT` surface regex in tools/qualification/ui_catalog.py).
- **Shard route fails.** An operations/BackgroundJobExecutor.toml shard with no admissible ids is rejected with "foreign owner has no admissible operations" (`load_records`).
- **No other route.** `[[outside_interfaces]]` is only for exported GUI interfaces and admits no ids.
- So under the current tooling this id cannot be a ui-operation. If ui2-approved.md listed it, CX-UIA-21 could not pass its acceptance check (test_ui0_catalog.py passing with the new ids).

Why it does not block:
- CL-UIA-13 owns ui2-approved.md. Its step 4 and its acceptance line ("ui2-approved.md lists every operation id the catalog will gain") make Claude the one who decides which ids the catalog gains.
- The executor draft says its names are "proposed catalog ids, not declarations to copy into production" and asks CL-UIA-13 to "approve or revise operation names".
- docs/design/ui-contracts/index.md says catalog amendments and release handling belong to the landing packet, not the draft.
- The draft already fully specifies the hook's behaviour: owner-thread registration, a level-triggered ready bit, and registration after a slot is terminal still seeing it. Moving its acceptance out of the UI catalog changes none of that.
- The reviewer's own fix is to edit the approved record: leave the id out of the catalog list, record it as a BackgroundJobs contract with regression tests, and keep the provider-side wake endpoint as a GUI operation.
- The parity backlog already expects this split. The E04 row (native-ui-parity.md:727) names "IApplication, background completion owner" as owners, and case rows carry `regression` fields.

Needed in Claude-owned packet docs, not in any draft:
- CX-UIA-21's owned paths do not cover src/stdlib/BackgroundJobs/README.md or a BackgroundJobs regression test. Its packet text should either gain those paths or move that work to the packet that owns them.
- The alternative is to extend ui_catalog.py and test_ui0_catalog.py to admit non-GUI owners. That is also outside the drafts.

### Catalog: the GUI ids are representable only through an amendment file CX-UIA-21 does not own; receivers must live in I*.btrc; some owners are missing from the id lists (non-blocking)

Draft: docs/design/native-ui-catalog/amendments/cx-uia-21.toml: release = "ui0-source-inventory-2026-09-21"; additions per owner, for example { source = "ISlider.btrc", owner = "ISlider", parent = "IView", decision = "CL-UIA-13", links = ["UI2", "E03", "E34"], declarations = ["SliderRange range();", "void setRange(double minimum, double maximum, double step);", ...] }; [current] interface_files = 20, interfaces = 31 + handler owners, interface_declarations = 191 + handler methods.

What the trial shows:
- trial.py writes amendments/cl-uia-13.toml with all 39 GUI ids as `[[additions]]`, giving the source, owner and parent for each (ITextField, ISelect and ISlider extend IView; IScrollView extends IContainer; IContainer extends IView).
- UICatalog admits it: 56 pending ids, no problems.
- On a simulated landing the drift gate passes, with `[current]` interface_files=20, interfaces=31, interface_declarations=191.

What would be rejected:
- Without the amendment, the operation shard rows are rejected: 'foreign owner has no admissible operations' (trial2.py).
- CX-UIA-21 owns only operations/ and native-ui-api-inventory.md (codex.md:3794-3800).
- Adding rows to the frozen checklist would break test_surface_counts_explain_the_frozen_release_delta (162 ids; 19 files and 24 interfaces) and the binding rule at codex.md:2929.
- Receivers declared in a new GUI/ControlEvents.btrc (ui2-control-events.md:37) fail the outside-interface guard: 'outside interface drift: added={'ControlEvents.ITextControlEventHandler'}' (trial3.py). As outside interfaces, their invoke ids would not be operations.

Owners missing from the id lists:
- The lifecycle decision handler and the state and interaction observers (ui2-lifecycle.md:41, 43, 46) and the executor's host adapter (ui2-executor.md:54) are missing from the id tables.
- If they are interfaces in I*.btrc files, the drift gate will require them as additions.

**Recommendation:** ui2-approved.md should list:
- the exact `[[additions]]` (source, owner, parent, declarations), with value classes and enums in ControlEvents.btrc and every receiver or handler interface in its owner's I*.btrc file (as IButtonAction lives in IButton.btrc);
- the new `[current]` counts;
- the amendment file name, added to CX-UIA-21's owned paths (amendments/cx-uia-21.toml) or written by Claude in CL-UIA-13.

ControlEvents.btrc classes and enums also need surface/GUIModules.toml rows (writer CX-UIA-05) before `check --strict --kind surface` passes.

### Typed receivers all named `invoke` with different event types: one component cannot implement two channels, and lambdas cannot implement an interface (non-blocking)

Draft: interface ITextControlEventHandler { void textEvent(TextControlEvent event); } — catalog id ITextControlEventHandler.textEvent (and likewise for the other receivers).

The draft gives every receiver 'one typed `void invoke(<Event> event)`' (ui2-control-events.md:56, 290).

Probe TwoInvokeReceivers.btrc (one class implementing ITextReceiver.invoke(TextEvent) and ISliderReceiver.invoke(SliderEvent)) is refused by both compilers:
- reference: `Duplicate method 'invoke' in class 'Component'` plus `Override 'invoke' param 1 ... incompatible type 'SliderEvent' (expected 'TextEvent' ...)`
- btrcc: `Duplicate member 'Component.invoke' at 13:2`

Probe LambdaAsReceiver.btrc is also refused by both:
- reference: `A capturing lambda ... cannot escape through a bare __fn_ptr`
- btrcc: `expects 'ITextReceiver' but got 'CFunction<void, TextEvent>'`

The existing typed handlers use distinct method names: IViewPointerHandler.pointer and IViewScrollHandler.scroll (IView.btrc:10-11), IWindowKeyHandler.key (IWindow.btrc:7).

**Recommendation:** Before the ids freeze, give each receiver its own method name (for example textEvent, selectionEvent, sliderEvent, scrollEvent; closeRequested, stateChanged, interactionChanged). One component can then implement several channels. Otherwise every channel needs its own named class.

### E29 and E46 outcome encodings must be owning classes, not rich enums (btrcc parity gap and a use-after-free on both compilers) (non-blocking)

Draft: class ContainerBatchResult { public ContainerBatchKind kind; public long long revision; public int failedStep; public string error; public Vector<IView> retained; } with enum ContainerBatchKind { CONTAINER_BATCH_COMMITTED, CONTAINER_BATCH_REJECTED, CONTAINER_BATCH_ROLLED_BACK, CONTAINER_BATCH_FAILED_CONSISTENT }.

The lifecycle draft says 'CL-UIA-13 must choose the concrete result/error encoding, including this quarantine state' (ui2-lifecycle.md:147-148). FailedConsistent carries a 'retained/detached ownership list' (:139).

btrcc rejects `Vector<class>` and `Vector<interface>` rich-enum payloads:
- RichEnumVectorInterface.btrc and RichEnumVectorClass.btrc pass on the reference compiler.
- btrcc fails with `Argument 'retained' to 'BatchResult.FailedConsistent()' expects 'Vector<IProbeView>' but got 'Vector<IProbeView*>'`. The 2026-10-03 bundle fails the same way, so this is long-standing.
- `Vector<string>` and `Vector<int>` payloads pass on both (RichEnumVectorScalar.btrc).

On both compilers, rich-enum managed payloads are shallow borrows:
- A temporary is refused with 'caller-owned temporary cannot be embedded in rich-enum payload 'ContainerEdit.Insert'; aggregate class elements are shallow borrowed references' (RichEnumTemporaryPayload.btrc).
- Returning `DetachResult.Detached(child)` where child is a callee local compiles on both. It prints 'live after return=0' and then reads the freed object; ASan reports `heap-use-after-free` on both compilers (RichEnumEscapingBorrow.btrc).

The house pattern for outcomes is a class holding a kind enum plus owning fields (BackgroundJobPollOutcome, src/stdlib/BackgroundJobs/BackgroundJobExecutor.btrc:160-170).

**Recommendation:** Freeze IContainer.applyBatch's result, the close transaction outcome and the executor admission outcomes as classes with a kind enum and owning fields. Rich enums are acceptable only for scalar or string payloads (for example the batch edits, which borrow children the caller keeps alive). Open CL-REQ-UI2-B (btrcc parity) and CL-REQ-UI2-C (escape check).

### Optional enums and enumerator spelling: `ControlCancelReason?` is a pointer type; the draft's bare COMMIT/CANCEL names collide across enums (non-blocking)

Draft: enum ControlCancelReason { CONTROL_CANCEL_NONE, CONTROL_CANCEL_ESCAPE, CONTROL_CANCEL_CAPTURE_LOST, CONTROL_CANCEL_ELIGIBILITY_LOST, CONTROL_CANCEL_MODEL_REPLACED, CONTROL_CANCEL_SOURCE_CLOSING, CONTROL_CANCEL_PLATFORM_INTERRUPTION }; enum TextControlPhase { TEXT_CONTROL_DRAFT, TEXT_CONTROL_COMMIT, TEXT_CONTROL_CANCEL };

Optional enum:
- The draft calls for an 'optional cancellation reason' (ui2-control-events.md:46, 51, 54).
- Probe NullableEnumReason.btrc is rejected identically by both compilers: `Argument 'reason' to 'CancelNotice()' expects 'ControlCancelReason*' but got 'ControlCancelReason'`.

Enumerator collisions:
- The draft names its phases DRAFT/COMMIT/CANCEL, CHANGE/COMMIT/CANCEL and PREVIEW/COMMIT/CANCEL (:46-51).
- With the names qualified, both compilers accept the collision and emit `TextControlPhase_COMMIT` in C (EnumMemberCollision.btrc passes on both). Enumerators are always emitted with the enum-name prefix, so there is no C macro clash.
- A bare ambiguous name is refused, with different wording. Reference reports each use: `Ambiguous enum member 'COMMIT' belongs to SelectionControlPhase, TextControlPhase; qualify it`. btrcc reports only the first: `Ambiguous enum value 'COMMIT'; qualify it with the enum name` (EnumBareAmbiguity.btrc).

**Recommendation:** Encode optional reasons with an explicit NONE enumerator (ControlCancelReason.CONTROL_CANCEL_NONE). Use the house-style prefixed enumerators (as CALLBACK_CANCELLATION_* and UI_RANGE_ADJUST_* do), so consumers can use bare names without ambiguity.

### Cleanup lease and E31 'worker last release': btrc has no executor-affine release, and a lease reached through a managed field is lost when its holder is collected in a cycle (non-blocking)

Draft: Lease rule: a native owner registers an Atomic<uint> cell (AtomicBuffer owned by the application executor) before publication; the user-visible handle stores only that Atomic<uint>* and the generation; handle.__del__ performs fetchAdd plus a native wake and touches nothing else; the executor drains signalled cells on its loop turn, calls close(), and frees the cell after Complete.

The lifecycle draft says 'Dropping the external reference signals that lease ... requiring proof with the language's existing ownership/cycle rules' (ui2-lifecycle.md:232-247). The executor draft adds that the cleanup lease must be reserved while the object is live (ui2-executor.md:179-182). The E31 fixture includes 'worker last release' (ui2-lifecycle.md:297).

Probe results:
- WorkerLastRelease.btrc: a component holding a fully cancelled CallbackScope loses its last reference on a spawned worker. Both compilers abort with 'Callback scope destruction requires its creating thread' (Callback.btrc:476-479).
- LeaseFieldInDestructor.btrc: a handle whose `__del__` signals a lease through a managed field reaches the lease when it dies acyclically. When it is collected in a cycle, the field has already been detached. Both print `acyclic: reached=1 missing=0` and `after cycle: reached=1 missing=2` (docs/language/callbacks.md:162).
- LeaseRawCell.btrc: each handle keeps a raw `Atomic<uint>*` into an executor-owned `AtomicBuffer<uint>`, the pattern CallbackState uses (Callback.btrc:219, 244). Both print `signals=4`, counting acyclic, cyclic and worker-thread releases.

**Recommendation:** State in ui2-approved.md that public handles hold only raw lease cells borrowed from executor-owned AtomicBuffer storage, never managed references to native owners or scopes. The executor roots the native owners and runs close/drain on the UI executor when signalled. Component CallbackScopes are UI-executor affine, and releasing the last reference on a worker aborts. E31 can then be met in provider code with no compiler change. CL-REQ-UI2-F is optional.

### Worker-safe identity and plain-data constraints: no 64-bit Atomic; OwnedBuffer's POD rule is skipped for generic parameters (non-blocking)

The draft requires that 'an epoch never reuses an exhausted identity' and gives worker-safe requestCancel generation/sequence checks (ui2-executor.md:49, 95-96).

64-bit atomics:
- AtomicSequence64.btrc (`Atomic<unsigned long long>`) is rejected by both compilers: `Atomic<T> payload must be bool, int, uint, or a raw pointer` (docs/language/realtime-primitives.md:81).
- The column differs: 4:10 on the reference compiler, 4:2 on btrcc.
- The mutex path works on both (WorkerPublisherStruct.btrc).

Generic parameters:
- The Python check skips type parameters (src/compiler/python/analyzer/types.py:1746-1749, 'generic_args[0].base not in set(active_type_params)'; btrcc's check is at analyzer/validation/Types.btrc:879).
- No recheck happens at specialization. `new UIWorkMailbox<string>` and `new UIWorkMailbox<ProbeView>` (GenericClassPublisherManaged.btrc, GenericClassPublisherClassPayload.btrc) transpile on both compilers. cc then fails: `passing argument 3 of 'btrc_OwnedBuffer_string_trySet' from incompatible pointer type` (char** vs const char**).

**Recommendation:** Keep admission behind the bounded mutex the draft already allows (:101-102), and keep the payload a non-generic POD struct, which makes the POD hole moot. Open CL-REQ-UI2-D (recheck at specialization) and, optionally, CL-REQ-UI2-E (64-bit atomics) as general compiler work.

### E-case links: UI2 on E42 and E46 is admitted; E01–E04 have no milestone link at all (non-blocking)

UI2 links:
- UI1 condition (4) asks for UI2 on E42 and E46 (ui1-feasibility.md:41-44).
- trial.py added UI2 to E42 (cases/E25-E47.toml:248) and E46 (:300). The loader admits both: E42 links=('N01','N02','N25','N48','UI1','UI2','UI5','UI9'), E46 links=(...'UI1','UI2','UI3','UI5','UI7').

E01–E04:
- They carry only N-IDs (cases/E01-E24.toml:27, 40, 53, 66: ['N05','N10'], ['N05','N19'], ['N05','N18'], ['N04']).
- They are UI2's acceptance cases (CLAUDE.md Stage 32 exit; N04/N05 map to UI2 in native-ui-parity.md:317-318).
- `_LINK` accepts 'UI2' (tools/qualification/schema.py:294).

**Recommendation:** In the same reviewed UI2 catalog amendment, add UI2 to E01, E02, E03 and E04 as well as E42 and E46. That keeps milestone selection consistent for CX-UIA-22 and CX-UIA-23.

### No default interface methods: new IView, IContainer and IWindow methods break every implementer, including a fixture outside CX-UIA-21's paths (non-blocking)

Interface signatures have no bodies (grammar.ebnf method_signature). The lifecycle draft adds methods to IView, IContainer and IWindow (ui2-lifecycle.md:41-47). src/tests/native/gui/NativeGUI.btrc:198 declares `class ForeignView implements IView`, but CX-UIA-21 owns only src/tests/native/gui/ui2/ (codex.md:3798). Any BTRSmith IView implementers would break the same way at its pin bump.

**Recommendation:** Add NativeGUI.btrc, and every other implementer the landing touches, to the CX-UIA-21 or CL-UIA-14 paths. Have the Windows, iOS and Android shells implement the new methods by throwing the typed 'unsupported' error, as Stage 32 already plans.

### Shapes confirmed expressible on both compilers (control-event values, UI vocabulary reuse, worker publication) (non-blocking)

ControlEventsProbe.btrc passes on both compilers. It covers:
- ControlEventContext with unsigned long long identity and an origin enum;
- TextControlEvent; SelectOption/SelectModel copying a Vector<SelectOption>, with a `string?` selected key;
- SelectionControlEvent with nullable previous, candidate and accepted keys;
- SliderRange and ScrollOffset;
- interface methods named range, offset, setRangeValue and scrollToOffset, `string? selectedKey()` and `void setSelectedKey(string? key)`;
- a receiver invoked with a CallbackScope.

SliderEventVocabulary.btrc passes on both. A GUI-side SliderControlEvent carrying UIRangeAdjustment imports Library.UI.Element, and UISemanticRange.adjustedValue moves 9007199254740992 to 9007199254740993 exactly. Today GUI does not import UI and UI does not import GUI, so this adds a new GUI→UI edge with no cycle.

WorkerPublisherStruct.btrc passes on both: an interface publisher with a mutex and OwnedBuffer, called from a spawned worker. ARC retain/release is serialized by the process-wide lock (src/runtime/c/cycles.c:784-801, 1052-1060).

No provider member collides with the new names (state, offset, range, move, insert and the rest).

**Recommendation:** Record these as parity-confirmed in ui2-approved.md. Keep Library.UI from ever importing Library.GUI, which would create a package cycle.

### Incidental btrcc diagnostic parity defects found by the probes (non-blocking)

Line numbers and file names:
- In any file that imports a stdlib module, btrcc reports the line offset by the imported module's lines and gives no file name.
- DiagnosticLineWithImport.btrc (error on line 4): reference reports `DiagnosticLineWithImport.btrc:4:14`; btrcc reports `Unresolved identifier 'missingName' used as a value at 515:14`. The 2026-10-03 bundle prints the same.
- The same offset appears for other errors: 211:51 vs 9:51, 226:30 vs 24:30, and 531:57 for a 25-line file.

Wording that diverges:
- duplicate member (two errors from the reference, one from btrcc);
- ambiguous enum member (wording and count);
- lambda passed as an interface (a capture-escape error vs a type mismatch);
- the Atomic payload column (4:10 vs 4:2).

**Recommendation:** Track these outside UI2 as CL-REQ-UI2-G. They do not block any UI2 operation, but they will surface in the CX-UIA-21 fixtures' diagnostics.

## Compiler gaps

- CL-REQ-UI2-A · Generic interface implementation and values (both compilers). Repro: `struct ProgressRecord { int percent; }; interface IUIWorkReceiver<T> { void deliver(T payload); } class ProgressReceiver implements IUIWorkReceiver<ProgressRecord> { public void deliver(ProgressRecord payload) {} }`. Reference: `Expected LBRACE, got LT '<'` at 7:50. btrcc: the same message at 7:50. Needed by a typed IUIWorkPublisher<T>.tryPublish / IUIWorkReceiver<T>.deliver, and only if CL-UIA-13 rejects the fixed UIWorkRecord.
- CL-REQ-UI2-B · btrcc parity: rich-enum variant with a Vector<class> or Vector<interface> payload. Repro: `interface IProbeView { int identity(); } enum class BatchResult { Committed(long long revision), FailedConsistent(long long revision, Vector<IProbeView> retained) }`, then `BatchResult.FailedConsistent(1LL, retained)` with a local `Vector<IProbeView> retained`. The reference compiles and runs it (PASS). btrcc rejects it: `Argument 'retained' to 'BatchResult.FailedConsistent()' expects 'Vector<IProbeView>' but got 'Vector<IProbeView*>'` (also in the 2026-10-03 bundle). Vector<string> and Vector<int> payloads pass on both. Needed by IContainer.applyBatch's result if it were encoded as a rich enum (recommended against).
- CL-REQ-UI2-C · Rich-enum borrowed payload escape (both compilers, memory safety). Repro: `class ProbeView { public int id; public ProbeView(int id) { self.id = id; } } enum class DetachResult { Detached(ProbeView child), Rejected(int code) } DetachResult detachOne() { ProbeView child = ProbeView(42); return DetachResult.Detached(child); }`, with main reading `result.data.Detached.child.id`. Both compilers transpile it. The run reads freed memory, and ASan reports `heap-use-after-free` under both. Needed by IContainer.applyBatch and IWindow.requestClose outcome encodings: forbid rich enums with managed payloads there until this is fixed.
- CL-REQ-UI2-D · OwnedBuffer/SPSCQueue/Span realtime-POD rule not rechecked at generic specialization (both compilers). Repro: `class UIWorkMailbox<T> { private OwnedBuffer<T> storage; public UIWorkMailbox(size_t capacity) { self.storage = new OwnedBuffer<T>(capacity); } public bool tryPublish(T payload) { return self.storage.set((size_t)0, payload); } }` with `new UIWorkMailbox<string>((size_t)2)` or `new UIWorkMailbox<ProbeView>((size_t)1)`. Both compilers transpile it. cc fails with `incompatible pointer type` (char** vs const char**); without -Werror the buffer would store unretained managed pointers. Python skips the check at analyzer/types.py:1746-1749; btrcc's check is at analyzer/validation/Types.btrc:879. Needed by a generic plain-data UI work mailbox behind IUIWorkPublisher.tryPublish (moot with a non-generic record).
- CL-REQ-UI2-E (optional) · Atomic<T> with 64-bit integer payloads (both compilers reject). Repro: `class PublisherIdentity { private Atomic<unsigned long long> nextSequence; public PublisherIdentity() { self.nextSequence.init(1ULL); } }`. Reference: `Atomic<T> payload must be bool, int, uint, or a raw pointer` at 4:10; btrcc: the same message at 4:2 (column differs). Needed by a lock-free 64-bit generation/sequence in IUIWorkPublisher.tryPublish / requestCancel. The draft's mutex path works today.
- CL-REQ-UI2-F (optional) · Executor-affine release for managed classes, analogous to the native `release-executor` key. Repro A: `class Component { public CallbackScope scope; ... } class Holder { public Component? item; }`; main stores the component in holder.item and cancels its scope; a spawned worker sets `holder.item = null`. Both compilers abort with 'Callback scope destruction requires its creating thread'. Repro B: a handle whose `__del__` reads a managed `lease` field finds it null when collected in a cycle (both print `missing=2`). Needed by the E31 'worker last release' path of IView.close/pollClose and IWindow.close/pollClose. The raw `Atomic<uint>*` lease-cell pattern works today on both compilers (signals=4).
- CL-REQ-UI2-G · btrcc diagnostic positions in files with imports, plus wording parity. Repro: `import Library.Vector; int main() { int value = missingName; return value; }`. Reference: `DiagnosticLineWithImport.btrc:4:14`; btrcc: `... used as a value at 515:14`, with no file name (also in the 2026-10-03 bundle). Wording also diverges for a duplicate member, an ambiguous bare enumerator and a lambda passed as an interface. Needed by no UI2 operation, but it affects the diagnostic parity of the CX-UIA-21 fixtures.
