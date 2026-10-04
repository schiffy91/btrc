# UI7 services contract pre-draft

Status: **draft under D27; not approved and not implemented**. CX-UIB-04
prepares `ui-7-contract-services` for CX-UIB-15 and CL-UIB-02. The final
contract must be re-derived against landed UI2/UI3, the Stage 26 P3
scoped-resource contract, all five UI1 shells and CL-UIA-22. The names below
are proposed btrc interfaces and value types, not current exports or additions
to the frozen UI0 denominator. No native execution or feasibility pass is
claimed.

Scope is the eight [UI7 families N33–N40](../native-ui-parity.md), their
desktop/mobile adaptations, and E10/E17/E22/E23/E44/E46. Native editor state
continues to belong to its editor. Commands, focus, geometry, lifecycle and
foreign claims keep their UI2/UI3/UI5 and
[interop ownership](../native-interop-ownership.md) owners.

## Current source and the replacement boundary

- [IDirectoryPicker](../../../src/stdlib/GUI/IDirectoryPicker.btrc) returns a
  synchronous `DirectoryPickerOutcome` containing a filesystem path. That
  representation cannot carry a valid Android document URI or an Apple
  security-scoped resource that has no usable path.
- [MacOSDirectoryPicker](../../../src/stdlib/GUI/MacOS/MacOSDirectoryPicker.btrc)
  calls `NSOpenPanel.runModal()` and converts its URL to a bounded path buffer.
- [LinuxDirectoryPicker](../../../src/stdlib/GUI/Linux/LinuxDirectoryPicker.btrc)
  loops through `ILinuxDialogPump.pumpOnce(50)` and throws when called from
  existing native event dispatch. Its asynchronous SDL callback is wrapped in
  a synchronous nested pump today.
- [IWindow](../../../src/stdlib/GUI/IWindow.btrc) has `showAlert(title, message)`
  without typed completion. [IView](../../../src/stdlib/GUI/IView.btrc) has
  local logical geometry and close/drain, but no shared anchor subscription.
- [App/App.btrc](../../../src/stdlib/App/App.btrc) owns input/error values;
  `AppClipboardText` was removed by btrc-D057. Do not revive that unused result
  as a second clipboard layer. In
  [LinuxTextField](../../../src/stdlib/GUI/Linux/LinuxTextField.btrc), cut calls
  `copySelection()` and deletes regardless of write success; paste needs an
  explicit failed-read outcome before replacing any draft.

The replacement picker is asynchronous and parent-owned. CX-UIB-15 owns the
eventual IDirectoryPicker compatibility boundary; it must not implement a
synchronous result by spinning or blocking the UI executor. Existing callers
migrate to completion-based use. If the old synchronous method must remain
temporarily, the contract owner must approve its explicit unsupported/migration
outcome and deprecation separately. This draft does not silently change that API.

## Shared request and ownership rules

The UI application/scene composes its services; each presentation takes a live
parent window or scene and, when needed, an attached anchor. These are existing
native owners, not another window/scene abstraction. The proposed service
interfaces are IMenu, IPopover, IDialog, IFilePicker, IClipboard,
ITransferSession, IShareService and IDocumentState.

Each accepted request returns an `IServiceOperation`. Request validation is
synchronous; accepted requests complete later on the owning UI executor,
including immediate native failure and user cancellation. A closed parent,
invalid anchor or invalid options yields a typed rejected start and no callback.
The final return envelope (`ServiceStart<T>`) has exactly one of an operation
or a rejection reason; its representation awaits CX-UIB-15.

```btrc
interface IServiceOperation {
	void cancel();
	bool isFinished();
}
```

`cancel()` is idempotent and requests cancellation, not proof that a native
dialog has already disappeared. The owner retains its native claim and callback
holder until the declared terminal event and release-executor drain. Generation
checks reject late native delivery. No arbitrary worker may retain/release btrc
ARC values: foreign replies use the reviewed holder/dispatch mechanism.

An accepted request has one terminal outcome: succeeded, cancelled (with user,
explicit-cancel or parent-lost reason), denied, revoked, unsupported, unavailable
or failed. Clipboard adds unavailable-format and successful empty content.
Outcome payloads are present only on success; errors carry native diagnostic
detail without reclassifying cancellation as failure. When an OS cannot expose a
distinction, return its documented coarser status and diagnostic, not an invented
permission result.

The parent owns an operation registry. Parent teardown cancels that registry,
invalidates controller callbacks and drains native release obligations. Each
operation still records its terminal outcome exactly once; delivery goes to a
still-live completion scope, never into a destroyed controller. A detached
completion is recorded as suppressed, not retried against a new parent. Requests
and resource results have no implicit process-wide singleton.

One modal presentation occupies a parent at a time. A second modal request
returns `busy` before acceptance; there is no hidden unbounded queue. Menus,
tooltips and popovers obey the parent's modal focus scope. Native tracking may
dispatch platform events, so callbacks must tolerate re-entry; application code
never starts a nested event pump or synchronously waits for a service result.

## Mobile adaptations

| Concern | Desktop proposal | iOS / iPadOS | Android |
| --- | --- | --- | --- |
| Main menu | Application/window command menu and keyboard equivalents | Scene command menus and discoverable keyboard commands; an action/context menu supplies touch access | Activity toolbar/overflow and context actions; keyboard access remains available |
| Anchored transient | Popover/tooltip with native focus and dismissal | Popover when the idiom permits; sheet/action sheet in compact width. iPad popovers and share sheets require a live source anchor | PopupWindow/tooltip or adaptive bottom sheet; Back dismisses the top eligible presentation |
| Picker result | Scoped file/folder/resource capability | UIDocumentPicker URL plus security-scope claim; export may represent a copy | SAF document/tree URI plus the actual transient or persistable grant |
| Clipboard | Explicit focused command; typed formats | User-triggered read with platform privacy/permission behavior; no background polling | Foreground/focus and sensitive-content policies; no background polling |
| Drag / share / reveal | Pointer drag, share UI and file-manager reveal | Drag/drop where available, including iPad cross-app delivery; touch actions always remain. No promised Finder-style reveal | Drag/drop where available; share Intent and copy/import actions remain. No promised general file-manager reveal |
| Dirty departure | Window close, quit or document/tab switch | Navigation, scene destruction and interactive dismissal; process death cannot be vetoed | Back/navigation and Activity lifecycle; process death cannot be vetoed |

iPad is `platform = ios` with `provenance.device_class = ipad`, not a sixth
family. Required iPad observations include scene isolation, split view/Stage
Manager anchor movement, hardware-keyboard command invocation and pointer or
cross-app transfer. UI2 lifecycle owns suspension and recreation policy. A
recreated controller cannot inherit a pending native operation by matching only
its visible title.

## N33 — Menus and context menus

Owner: IMenu presents an immutable menu snapshot whose entries reference UI3
command identities. It does not own a second action dispatcher. Proposed
operations:

```btrc
interface IMenu {
	ServiceStart<IServiceOperation> present(MenuRequest request, IMenuCompletion completion);
	void update(MenuSnapshot snapshot);
}
```

MenuRequest identifies parent, optional anchor, stable item keys, submenus,
checked/radio state and key equivalents. Separators and disabled items never
invoke. On selection, resolve the current UI3 command and revalidate availability,
target identity and modal scope; a visible old snapshot is not authority to run
an action. A model update preserves stable identity or cancels that presentation.
Programmatic updates dispatch zero user commands. Escape/dismiss returns focus
to the still-valid originating target, otherwise UI3's focus fallback.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSMenu/NSMenuItem and contextual menus; key equivalents route into the same UI3 command registry as controls |
| Linux | GTK4 GMenuModel/GAction and popover menus if D23 selects GTK4; SDL-custom accessible menu presenter otherwise, using the same command and focus contract |
| Windows | HMENU and native menu/context tracking; WM_COMMAND resolves a stable command identity, never an index into a stale list |
| iOS | UIMenu/UIAction and context menus; scene-scoped keyboard commands and touch-accessible equivalents, including iPad |
| Android | PopupMenu/MenuItem and toolbar/overflow actions; stable command IDs and activity-generation checks |

E23: open a menu, finish background work that disables its command, then invoke
the formerly enabled item. Expect zero product action, one dismissal outcome,
valid focus return and no escaped modal scope. Test checked/radio state and the
same command through a key equivalent and a control.

## N34 — Popovers, tooltips and transient UI

Owner: IPopover owns a presentation, not its anchor view. UI5 supplies a
generation-checked anchor observation in window/screen logical coordinates.

```btrc
interface IPopover {
	ServiceStart<IServiceOperation> present(PopoverRequest request, IPopoverCompletion completion);
	ServiceStart<IServiceOperation> showTooltip(TooltipRequest request, IPopoverCompletion completion);
}
```

An anchor remains owned by its container. Move/scroll/scale changes update
placement through the one geometry conversion owner; detaching, closing or
replacing the anchor cancels its presentation. Placement clamps to available
viewport bounds, preserves reachable content and never moves an unrelated
scene. Popovers declare whether they take focus and dismiss outside; passive
tooltips do not take focus or trap keyboard navigation. The visible content and
dismissal action must be accessible through UI8.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSPopover and native tooltip facilities; observe anchor/window movement and close before releasing their native view claims |
| Linux | GTK4 GtkPopover/tooltip facilities, or SDL-custom transient content with explicit focus/AT-SPI ownership; portal services do not supply these widgets |
| Windows | Native tooltip window and an owned popup window for popover content; DPI-aware geometry and capture dismissal use UI3/UI5 |
| iOS | UIPopoverPresentationController with source view/rect, adapting to an approved compact sheet; iPad resizing and scene changes update the anchor |
| Android | PopupWindow and native tooltips, or an approved adaptive sheet; anchor detach and Activity recreation cancel the old operation |

E23 plus E27/E33: dismiss under an active modal scope, scroll the anchor, cross
fractional-scale displays and remove the anchor. Return focus only to a valid
target; large content remains reachable at all viewport edges.

## N35 — Alerts, sheets and dialogs

Owner: IDialog presents typed buttons and results. Buttons have stable IDs and
default/cancel/destructive roles; labels are not result identities.

```btrc
interface IDialog {
	ServiceStart<IServiceOperation> present(DialogRequest request, IDialogCompletion completion);
}
```

Validation belongs to the request/document owner. A rejected validation leaves
the presentation open with a recoverable error; a pending asynchronous validation
disables duplicate acceptance. Terminal button selection is delivered once.
Parent loss, Escape, explicit cancel and backend failure remain distinguishable.
The single-modal-per-parent rule also applies to alerts opened by menu commands.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSAlert with beginSheetModalForWindow/completion handler; no application call to runModal |
| Linux | GTK4 asynchronous alert/dialog response or SDL-custom parent-owned dialog; no application event-pump loop |
| Windows | Native task/dialog presenter with a reviewed asynchronous host adapter; a blocking native API may not block the UI service caller or retain unleased btrc state |
| iOS | UIAlertController alert/action sheet under the owning scene; popover presentation on iPad has an explicit anchor |
| Android | AlertDialog/DialogFragment and generation-bound results; lifecycle cancellation cannot deliver to a replaced Activity |

E10/E23/E46: try a nested request, cancel validation, destroy the parent and
exercise typed Save/Discard/Cancel results. Busy rejection creates no second
modal and no completion obligation; every accepted request resolves once.

## N36 — Open, save and folder pickers

Owner: IFilePicker. **Picker request/result resource types are provisional until
Stage 26 `platforms-p3-fs-mobile` / CL-P2-01 approves the P3 scoped-resource
contract.** UI7 must consume that type instead of inventing a path wrapper.

```btrc
interface IFilePicker {
	ServiceStart<IServiceOperation> open(OpenPickerRequest request, IPickerCompletion completion);
	ServiceStart<IServiceOperation> save(SavePickerRequest request, IPickerCompletion completion);
	ServiceStart<IServiceOperation> folder(FolderPickerRequest request, IPickerCompletion completion);
}
```

Requests carry parent, single/multiple selection policy, admitted content types,
suggested name and optional initial resource/location hint. An initial hint is
not an access grant. A successful selection owns at least one resource, exactly
one for save or folder; an empty selection is a
cancel or a documented backend error. Mixed selections are admitted atomically
or returned with explicit per-item failures before product mutation.

P3's resource provides capability-checked access, display metadata and explicit
scope/lease lifetime. It need not expose a path. Taking a result transfers or
duplicates its grant by the P3 rule; unclaimed results are released on terminal
drain. Permission persistence is separately requested, may fail, and never
follows merely from storing a URI/bookmark string. Reacquisition after restart
can be denied or revoked. Save returns a destination capability with explicit
create/replace semantics; a native overwrite confirmation is not a guarantee of
race-free or durable storage. P3 owns commit/replace behavior and failure.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSOpenPanel/NSSavePanel using beginSheet completion; keep the security-scoped URL claim through P3 access, not a copied path |
| Linux | xdg-desktop-portal FileChooser request/Response with parent identifier and resource/FD translation through P3; GTK4 may broker it. SDL callback completion replaces LinuxDirectoryPicker's nested pump; absent backend is unavailable |
| Windows | IFileOpenDialog/IFileSaveDialog and folder mode, producing IShellItem/resource access; Show is synchronous, so the asynchronous presenter/STA ownership bridge needs proof before this mapping is accepted |
| iOS | UIDocumentPickerViewController import/open/export modes; security-scoped URLs, coordinated access and scene-owned completion, including iPad folder/multiple-selection availability |
| Android | SAF ACTION_OPEN_DOCUMENT/ACTION_CREATE_DOCUMENT/ACTION_OPEN_DOCUMENT_TREE with returned URI grant flags; takePersistableUriPermission only when offered and requested |

E10/E17: select a resource with no path, cancel, deny, revoke and close the
parent during reply delivery. Resolve once, release every unclaimed grant, and
preserve an existing unsaved document when opening the new resource fails.

## N37 — Clipboard and edit commands

Owner: IClipboard owns transfer access; UI3 routes cut/copy/paste/select-all to
the focused editor or product target exactly once. A native editor retains its
IME, selection and undo implementation.

```btrc
interface IClipboard {
	ServiceStart<IServiceOperation> read(ClipboardRequest request, IClipboardCompletion completion);
	ServiceStart<IServiceOperation> write(ClipboardPayload payload, IClipboardCompletion completion);
}
```

Typed payloads advertise formats and bounded lazy representations. Successful
empty text is distinct from unavailable format, denied access, unavailable
backend, revoked access and conversion/read failure. No empty-string fallback
may turn failure into a successful paste. Native ownership loss terminates lazy
offers without retaining a dead editor.

Cut snapshots the editor identity/generation, selection, composition state and
document revision. It deletes only after a successful clipboard write and a
matching current edit transaction. Paste admits and validates all data against
UI3/UI4's text/size policy before mutation; failure preserves draft, selection,
composition and both undo stacks. A focus or revision change while waiting
cancels the intended edit, never redirects it to the newly focused target.
Successful cut/paste is exactly one editor transaction. A clipboard write that
succeeded before a later edit was cancelled cannot be rolled back reliably;
report that distinction and preserve the draft.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSPasteboard with typed representations and change identity; native NSText editor actions remain the editor's transactions |
| Linux | GTK4 GdkClipboard asynchronous reads or SDL clipboard callbacks/text bridge; clipboard/selection ownership and unsupported formats are explicit |
| Windows | Native clipboard formats with OLE IDataObject for richer/delayed data; access contention and conversion failure are typed failures, not empty text |
| iOS | UIPasteboard and system paste controls where appropriate; user intent and privacy restrictions govern reads; do not poll to infer permission |
| Android | ClipboardManager/ClipData with foreground and sensitive-content policy; temporary content URI access follows P3 grants |

E44/E45: 100 write-failure/cut and read-failure/paste success/failure/retry
cycles at the actual provider boundary, including closed/replaced editors.
Expect zero failed-operation draft/selection/history mutation and one successful
edit transaction. Native editor behavior needs native-boundary evidence, not
only a mocked IClipboard reply.

## N38 — Drag/drop and transfer

Owner: ITransferSession leases typed data and a source identity until one
terminal transfer outcome. UI3 owns hit testing and input capture; a drop target
does not take over their coordinate model.

```btrc
interface ITransferSession {
	ServiceStart<ITransferSession> begin(TransferOffer offer, ITransferCompletion completion);
	void cancel();
	void accept(TransferAcceptance acceptance);
}
```

The final contract may place `begin` on a factory; the factory writer resolves
that placement. Offers contain stable item identity, formats, permitted copy/move
intents and lazy data/resource access. Feedback is provisional; acceptance does
not mean data is loaded or committed. The receiver validates and stages data,
then acknowledges durable product acceptance. A move removes the source only
after that acknowledgement and source-revision revalidation. External protocols
that cannot prove this advertise copy-only or report their documented weaker
semantics; never assume an OS cursor means a safe move.

Cancellation/parent loss releases offers and scoped resources once, invalidates
late loads and leaves recoverable partial data under the receiving product's
explicit cleanup policy. Large streams apply P3 limits/backpressure; do not
materialize an unbounded payload in UI memory. Copy/paste, an import picker or
an explicit move command provides keyboard/touch alternatives.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSDraggingSession/NSDraggingDestination and promised pasteboard data; completion maps the actual operation and lifetime |
| Linux | GTK4 drag/drop or X11/Wayland transfer through the selected SDL/native provider; cross-process lazy data requires real protocol evidence |
| Windows | OLE IDataObject/IDropSource/IDropTarget; apartment-affine callbacks, delayed rendering and actual drop effect are explicit |
| iOS | UIDragInteraction/UIDropInteraction and NSItemProvider; iPad cross-app/scene grants outlive loading only under declared P3 leases |
| Android | startDragAndDrop/DragEvent with ClipData and temporary drag/drop permissions; scope expires unless the platform explicitly grants persistence |

E22: internal/external drag, copy/move choice, cancellation during lazy read,
destination close and retry. Run 100 applicable transition/cancellation cycles;
verify exactly one terminal result, zero premature source deletion and usable
keyboard/touch alternatives.

## N39 — Open, share and reveal

Owner: IShareService requests an OS action on validated URLs or scoped
resources. UI1 activation routing separately owns incoming open events.

```btrc
interface IShareService {
	ServiceStart<IServiceOperation> open(OpenResourceRequest request, IShareCompletion completion);
	ServiceStart<IServiceOperation> share(ShareRequest request, IShareCompletion completion);
	ServiceStart<IServiceOperation> reveal(RevealRequest request, IShareCompletion completion);
}
```

Success means the OS accepted or handed off the action according to the selected
API; it does not prove the other app displayed, imported or durably stored it.
Share dismissal is cancelled when observable. No handler, denied/revoked access,
unsupported reveal and native launch failure are explicit outcomes. Retain the
resource grant until the OS handoff/loading obligation ends, not merely until the
service method returns. Reveal must not silently become open, share or a raw
path conversion.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | NSWorkspace open/reveal and NSSharingServicePicker; callbacks report API-specific handoff/cancel semantics |
| Linux | portal OpenURI/OpenFile and FileManager1 ShowItems where available; share UI requires an explicit supported backend, otherwise unsupported |
| Windows | ShellExecute/association launch and shell selection/reveal; DataTransferManager through its desktop interop requires a separately reviewed sharing bridge, never inferred from ShellExecute success |
| iOS | UIApplication open and UIActivityViewController with scene/anchor ownership; no general reveal capability, including on iPad |
| Android | ACTION_VIEW/ACTION_SEND with grant flags and chooser; no general reveal promise and no assumption of target-app completion |

E17: cold/warm/recreation activation validates and routes once by UI1's event
identity and duplicate policy. A failed incoming resource leaves the current
dirty document intact. Delayed outgoing completion cannot activate a replaced
scene. Replaying restoration never replays open/share side effects.

## N40 — Undo/redo and document state

Owner: IDocumentState records product mutations and revision-based dirty state.
Native editor undo stays with the editor; UI3 resolves the focused command target
before dispatching undo/redo. One user command must not enter both histories.

```btrc
interface IDocumentState {
	DocumentSnapshot snapshot();
	void record(DocumentMutation mutation);
	ServiceStart<IServiceOperation> undo(IDocumentCompletion completion);
	ServiceStart<IServiceOperation> redo(IDocumentCompletion completion);
	ServiceStart<IServiceOperation> requestDeparture(DepartureRequest request, IDepartureCompletion completion);
}
```

Product mutations have explicit grouping, inverse/apply failure policy and
revision identity. Failed operations do not advance history; a new edit clears
only the relevant redo branch. `dirty` is derived from the current revision and
the successfully persisted revision, not from a window-visible flag. A save
completion for revision r cannot mark later revision r+1 clean.

Departure uses UI2's one Save/Discard/Cancel decision machine, with UI5 handling
navigation and UI1 the window/scene request. Repeated requests for the same
document/decision coalesce; a concurrent request for a different document does
not. Save failure remains pending with a recoverable error; Cancel preserves
route, focus, scroll anchor and draft. Discard requires explicit authorization
for the intended revision; a later edit requires a fresh decision. Parent loss
releases presentation resources without claiming the unsaved draft was saved.
OS process death is not vetoable; UI2/UI5 restoration records eligible state
without retaining native objects or replaying a product command.

| Platform | Mapping and adaptation |
| --- | --- |
| macOS | Native NSText/NSUndoManager editor history and document/window edited indicators; product history remains IDocumentState's owner |
| Linux | GTK4/native editor facilities where present or the SDL editor's own history; product undo/dirty presentation remains explicit |
| Windows | Native edit/RichEdit undo where selected, with UI3 target routing; product document history and close decisions are separate |
| iOS | Native text/UndoManager behavior and scene/navigation dismissal; iPad keyboard undo and multiple scenes target the correct document |
| Android | Native editor undo where exposed, otherwise a declared editor adaptation; Back/navigation requests enter the shared departure machine |

E14/E44/E46: type, compose, paste, product-edit, undo and redo across refreshes;
then exercise Save/Discard/Cancel through close, quit, Back, tab and interactive
departure. Run 100 cycles per applicable entry path with delayed saves, new
edits, repeat requests and parent loss. Expect zero duplicate saves,
stale-revision closes, lost drafts or wrong-document results.

## Review, implementation and evidence handoff

CX-UIB-15 re-derives these proposals after CL-UIA-20 (`ui-3-contract-input`) and
CL-P2-01 (`platforms-p3-fs-mobile`). CL-UIB-02 is the contract approval gate;
Windows/iOS/Android mappings also need CL-UIA-22's real-shell feasibility check.
Linux GTK4 versus SDL remains D23's decision. Portable IWindow/App changes go
through the designated CX-UIB-13 writer, and factory/value placement through
CX-UIB-17; this pre-draft changes none of those files.

Before approval, resolve these concrete dependencies:

| Dependency | Required review/proof |
| --- | --- |
| P3 scoped resources, CL-P2-01 | Picker/clipboard/drag/share grants, persistence, revocation, stream access and durable save/move semantics; no nullable-path proxy |
| UI2/UI3/UI5 | One executor/cancellation registry, command identity, modal focus scope, anchor coordinates and revision-checked departure; no competing service-specific state machine |
| CL-UIB-09 Apple interop | Block/delegate/NSItemProvider terminal ownership and main-executor release while cancellation happens inside a callback |
| CL-UIB-10 Windows interop | IFileDialog/TaskDialog asynchronous presentation strategy, parent-HWND lifetime and COM apartment ownership; OLE callbacks and delayed data must never move btrc ARC values across threads unchecked |
| CL-UIB-11 Android interop | Activity result/Intent/drag callback ownership, temporary URI grants and recreation cancellation through checked Java peers |
| CL-UIB-12 Linux interop | GObject/main-context, portal request cancellation and transfer/AT-SPI bridges on X11 and Wayland |

The later portable fixture directory is `src/tests/native/gui/services/`, with
one driver per service family and Python/selfhost rows per supported host. It
must include real-native menu invocation, picker completion, clipboard failure
injection, drag cancellation and dirty departure; model tests alone do not
establish native parity. Record unsupported adaptations and unavailable hosts
explicitly. iPad fixtures use the ios family plus device_class; hosted/simulator
results stay distinct from physical input and device evidence.

All eight family mappings above are proposals. No operation/case slot is marked
passed, no existing frozen id is removed, and no BTRSmith screen migrates until
the approved btrc landing and its BTRSmith pin bump. BTRSmith import, Settings
and unsaved-edit flows consume these same owners after that handoff.
