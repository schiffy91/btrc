# UI8 native semantics and assistive interaction

**Pre-draft — CX-UIB-02, `ui-8-contract-a11y`.** This document is input to
CX-UIB-13 and the Stage 34 CL-UIB-02 review, not an approved IView API. The
UI2/UI3 writer chain and all five shells with CL-UIA-22 review precede provider
landing. Platform mappings and request scopes are provisional; no inspection,
screen-reader session or native execution is claimed.

The source baseline is `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
[UISemantics](../../../src/stdlib/UI/Semantics.btrc) already owns role, label,
hint, string value, live mode, checked/pressed/expanded, busy and read-only.
`UIResolvedSemantics` adds enabled/selected/focusable/focused. `valid()` calls
[UIText.valid](../../../src/stdlib/UI/Text.btrc) with a **512-byte inclusive**
limit for label, hint and value. [IView](../../../src/stdlib/GUI/IView.btrc)
currently has no semantic attachment or virtual-child contract. Native control
defaults do not establish a bridge for custom GPU content.

## Coverage and proposed operations

| Family | Contract responsibility | Acceptance links |
|---|---|---|
| N41 | Attach native roles/names/values/states/relations/actions with stable identity, coherent screen geometry and custom GPU children. | E27/E28/E39; native tree inspection. |
| N42 | Accessible collections and text/ranges, virtual realization, reading order, live/busy updates, modal isolation and no duplicate native/custom nodes. | E21/E28/E34/E45. |
| N43 | Keyboard, screen-reader, switch and voice-control actions with visible focus and alternatives to gestures; no focus traps. | E05/E13/E18/E21/E39. |
| N23–N25 | Consume measurement, participation and viewport transforms from the [layout pre-draft](ui5-layout.md); accessibility owns no alternate layout. | E26/E27/E39. |
| N31/N32 | Expose tabs/navigation, pane dividers and toolbar overflow using the same command identities. | E18/E23/E46. |
| N44–N46 | Full localized labels/native text, live text scale/contrast and reduced-motion alternatives match visible state. | E15/E20/E28. |

Candidate catalog ids below require a reviewed amendment; no frozen UI0 row or
current source interface is changed here.

| Candidate operation ids | Proposed values and result |
|---|---|
| IView.setSemantics | Existing UISemantics plus identity/relations/action attachment → applied, invalid, too-large, unsupported or closed; atomic snapshot replacement. |
| IView.clearSemantics | Remove only this explicit attachment; preserve the native default owner and stable view identity. |
| IView.setVirtualChildren | Scoped virtual-source registration for custom content → registration outcome; children stay lazy and keyed. |
| IAccessibleChildren.count, IAccessibleChildren.childAt, IAccessibleChildren.find | Revisioned count and stable-key lookup, bounded enumeration and explicit missing/unavailable results. |
| IAccessibleChildren.realize | Stable key and revision → realized, pending, stale or missing; no synchronous unbounded data load. |
| IAccessibleActions.perform | Keyed typed action and expected generation/revision → accepted/pending/rejected/unsupported; same product command path as pointer/keyboard. |
| IAccessibleText.range, IAccessibleText.selection, IAccessibleText.setSelection | Versioned text range, normalized coordinate unit and explicit stale/invalid outcomes. Native editor stays the text owner. |
| IAccessibleRange.value, IAccessibleRange.adjust | Exact model value/min/max/step plus formatted display and typed relative/absolute adjustment. |
| IAccessibility.announce | Owner, semantic priority and bounded replace key → accepted/coalesced/full/closed; scoped to the relevant transport/scene. |

Names are design inputs, not btrc declarations or a second semantic vocabulary.
Extend UISemantics with typed companion identity, relations, action and range
values only where it lacks the information. Do not encode table coordinates,
text selection or timecode solely in its existing string `value` field.

## Identity, ownership and update rules

An attachment has a stable automation id scoped to its scene plus a generation.
Duplicate live ids in that scope reject before replacing state. Product stable
keys survive sorting/recycling; a native pointer or row index is not identity.
Treat incoming mutable UISemantics builder values as copied snapshots; later
builder mutation cannot silently alter an already-published native node.

Exactly one owner exposes each interaction. Native text fields/buttons keep
native accessibility; annotate their native nodes instead of overlaying a second
GPU node. A GPU semantic subtree exposes only content not already represented by
a native child. Relations (labelled-by, described-by, controls, member-of) resolve
within the published tree with bounded validation; dangling/cross-scene ids
reject explicitly. Reading order is logical/content order and does not assume
left-to-right screen coordinates or z-order. Cycle rejection applies to parent
ownership, while legitimate typed relations need not form a tree.

An update validates all fields and publishes one revision atomically. On invalid
UTF-8, overflow, unsupported required action or a failed native update, preserve
the previous valid snapshot and report the outcome. Best-effort partial native
publication is not silently accepted. An unavailable optional platform feature
is a named adaptation with its fallback; missing provider implementation is not
OS-restricted merely because this draft mentions an adaptation.

UI queries observe a stable committed snapshot; commands enter the same model
owner as normal interaction and revalidate enabled state, revision and lifetime.
Setters and refreshes synthesize zero user commands. Keyboard/switch/voice invoke
once; a screen-reader press must not also synthesize a second pointer click.
Subscriptions reuse CallbackScope/ICallbackRegistration. Foreign calls pin their
receiver until return; teardown seals new entry, drains active calls and then
releases native holders on their declared executor.

## Text limits, ranges and exact values

For the current UISemantics value shape, propose retaining the inclusive 512-byte
limit until a reviewed version changes it. **Valid 511/512-byte UTF-8 is admitted;
513 bytes returns too-large**, leaves the old snapshot and never truncates inside
a code point. Test multibyte characters crossing the boundary, malformed UTF-8,
embedded NUL transport limitations and empty fields. A transport that cannot
represent a value returns an explicit failure, not a shortened success.

This limit applies to compact semantic label/hint/value fields, not an editor's
full document. A native editor with more than 512 bytes remains available through
its native text/range owner. The proposed text API queries bounded ranges lazily;
it must not require copying the entire document into a semantic string. Password
contents never enter labels, values, logs, snapshots or restoration metadata;
secure native editor capabilities remain authoritative.

Text ranges carry document revision and a declared model unit (proposed UTF-8
byte offsets at valid boundaries). Providers explicitly convert to UTF-16 or
other platform units without splitting surrogate pairs; user selection respects
grapheme clusters where required by the editor. Define checked conversion for
combining marks, emoji sequences, RTL and deleted text. A range from a stale
revision returns stale unless the document owner supplies a deliberate mapping;
it never selects unrelated replacement content by an old index.

Collections expose stable selection ids, index-in-current-view, row/column count,
hierarchy and expansion without parsing strings. Timeline/range values retain
exact 64-bit model units outside platform floating-point controls. Native range
patterns that cannot represent every model value expose truthful limits and
route increment/decrement or a typed text command to exact operations; never
round-trip a 64-bit timeline through double and call it exact. E34 covers
endpoint, step, cancel and no-duplicate-commit behavior.

## Virtual content, focus and modal isolation

A virtual child descriptor contains key, generation, parent, role, current
logical geometry or offscreen state, and supported actions. `childAt` resolves
against one revision; chunked enumeration returns that revision so callers can
restart after a structural change rather than duplicating/skipping rows. Native
bridge objects are bounded cached proxies, not one eagerly allocated object per
item in a 100,000-row model. Stale proxies remain safely queryable as unavailable
until foreign clients release them; their ids must not silently alias new rows.

Realization is asynchronous when data is unavailable: mark pending/busy, schedule
through the UI executor and notify the requesting transport on completion. Do
not block a native query waiting for I/O or pump a nested loop. Deletion during
realization cancels the old request and selects the documented next valid item
or container fallback. Offscreen-but-realizable is distinct from hidden,
collapsed or disabled. Requesting focus may scroll/realize the stable item once,
then transfer focus only if its owner/generation is still valid.

Keyboard focus and accessibility focus are related facts, not identical bits.
Native editor focus remains native; custom controls provide visible focus and
accessible actions for every gesture. Hiding/disabling an ancestor settles
composition/capture under E39, dismisses invalid anchors and moves focus to the
nearest valid owner without replaying old input when shown. Tab/Shift-Tab,
activation, adjust, escape/Back, switch scanning and voice targets cannot trap
the user in a GPU subtree.

A modal/popup scope isolates native and virtual children coherently; background
controls cannot still be invoked through accessibility. On dismissal, restore
focus by stable identity or an explicit fallback. Owner close cancels pending
realization, actions and announcements. No notifications target a destroyed node.

Announcements have a per-transport, per-scene bounded queue. Proposed default:
polite replaceable status updates coalesce by stable status key and emit at most
one update per key per 250 ms while retaining the latest; assertive messages
bypass that delay but have a bounded declared burst capacity. Overload returns
full, never silently drops a required alert. Focus/structural changes and action
results are not disposable progress chatter. Suspend/close cancels stale output;
resume announces current state once. Qualify VoiceOver, TalkBack, UIA and AT-SPI
behavior separately; this default is not a universal screen-reader timing fact.

## Five-platform bridges and expected interop requests

All bridges reuse [native-interop-ownership](../native-interop-ownership.md),
including executor checks, entry pinning, explicit cycle-breaking cancellation
and native claims. Worker/RPC threads cannot mutate UI objects or non-atomic ARC.

| Family | Bridge and required proof | Interop dependency |
|---|---|---|
| macOS | Annotate NSAccessibility native controls; NSAccessibilityElement subclass for custom children/actions, stable parent/child identity and screen frames. Inspect with native AX APIs and exercise VoiceOver separately. | Steps 3 and 6 (Objective-C protocols, subclasses/overrides); CL-UIB-09 after CL-P2-21. |
| Linux | D23 GTK4 route uses GtkAccessible/custom widget interfaces. SDL route exports verified org.a11y.atspi objects over D-Bus; an SDL window alone is not a bridge. Inspect via AT-SPI on X11 and Wayland. | Step 8 (GObject); CL-UIB-12 proves GTK implementations or actual D-Bus method/property export. |
| Windows | UIA simple/fragment/root and typed pattern providers with QueryInterface identity; inspect with a real UIA client on x64/ARM64. RPC-thread queries require immutable snapshots or a reviewed marshaling path, never an unchecked UI callback. | Step 5 COM after function-table support; CL-UIB-10 after CL-P2-10. No blanket claim that apartment-only holders already solve UIA RPC entry. |
| iOS/iPadOS | UIAccessibility native controls plus UIAccessibilityElement virtual children and custom actions. Use ios family/device_class for iPhone and iPad; scene identity, hardware keyboard, switch and VoiceOver paths remain explicit. | Steps 3/6 UIKit interop; CL-UIB-09 after CL-P2-21; Stage 24/25 simulator/host lanes. |
| Android | AccessibilityNodeProvider virtual ids, native View nodes and typed actions with TalkBack/UiAutomator inspection. Convert text units correctly and bound global refs across activity recreation. | Steps 4/7 checked JNI/RegisterNatives; CL-UIB-11 after CL-P2-24 and packaging prerequisite CX-P2-45. |

Expected request scopes for implementation (design requests, not reported
compiler failures):

- **REQUEST(CL-UIB-09):** qualify accessibility-element subclasses/overrides,
  protocol methods, main-executor callbacks and teardown during AX calls through
  both compilers on AppKit/UIKit. Include native-holder count and cycle tests.
- **REQUEST(CL-UIB-10):** qualify multiple UIA interfaces and pattern providers
  with consistent QueryInterface identity, exact release counts and an explicit
  safe RPC-thread query/command strategy. A Linux COM proxy is structural
  evidence; real Windows client calls remain required.
- **REQUEST(CL-UIB-11):** qualify AccessibilityNodeProvider shim callbacks,
  RegisterNatives, string/range conversion and class/global-ref lifetime across
  100 activity recreation cycles, with CheckJNI and both frontends.
- **REQUEST(CL-UIB-12):** after D23, qualify GtkAccessible/GtkAccessibleRange
  implementation and virtual children, or SDL AT-SPI D-Bus object export with
  method/property/action round trips. Header import alone does not prove export.

No compiler/spec/runtime changes accompany this packet. These requests become
concrete reproduction fixtures under the named interop owners before provider
implementation; inability to marshal safely remains a blocker, not a wrapper
that bypasses the approved ownership rules.

## Proposed acceptance and limits

For each provider and reference/selfhost, preserve native inspection artifacts
with revision, runner, OS/toolkit, backend and device_class. Missing bridge,
unavailable runner and unverified assistive journey are distinct results.

- **E28:** 511/512/513-byte labels and text beyond 512 bytes; typed invoke/toggle/
  select/expand/adjust, text ranges and table positions; no silent truncation or
  duplicate product command. Include malformed UTF-8 and non-BMP conversions.
- **E21:** traverse/realize an initially unrealized item in a 100,000-row
  collection, sort/filter/delete during the request and maintain stable selection,
  current position and bounded live native proxies. Record the configured cell/
  proxy budgets and peak counts instead of asserting a full tree is cheap.
- **E05/E13/E18/E39:** native-to-GPU focus, keyboard/switch/voice alternatives,
  modal isolation, ancestor hide/disable, recreation and no focus traps; repeat
  100 transition/cancellation cycles per applicable configuration.
- **E27:** screen bounds round-trip within one device pixel through scroll,
  scale and viewport changes; offscreen and hidden remain distinguishable.
- **E15/E20/E26:** text scaling and RTL reading order match live layout; large
  text/contrast/reduced motion preserve required actions and nonvisual feedback.
- **E31:** construction/query/callback/teardown failure, foreign-held proxy after
  owner close and cancellation from within a callback; zero double releases,
  stale calls or orphan holders after successful drain, otherwise explicit pending
  or failed cleanup. Scope-only CI cannot satisfy these native requirements.

Hosted inspection and simulators are stand-ins, not physical-device or owner
screen-reader evidence. Acceptance needs real platform transports plus the
attended assistive journeys; a JSON projection alone does not close N41–N43.
