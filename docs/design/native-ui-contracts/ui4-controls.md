# UI4 controls contract pre-draft

Status: draft under D27, not approved

Packet: **CX-UIB-01**. Source baseline:
`f4317455de1e567d4d6290139e5ba28fbada7d0c`.
This planning document proposes the N11–N22 control surface. It changes no
public interface, provider, fixture, catalog row or frozen denominator.
CX-UIB-10/11 must re-derive it against landed UI2/UI3, all five UI1 shells and
CL-UIA-22. N22 relationships are reconciled with the IView/UI8 writer chain;
CX-UIB-17 reconciles factories and shared values. Claude approves through
CL-UIB-02. No platform mapping below is executed evidence.

## Existing surface and shared assumptions

The family requirements and E-case numbers come from
[native-ui-parity](../native-ui-parity.md), especially UI4, N11–N22 and
E15/E19/E33/E34/E45. The stage exit is
[PLAN Stage 34](../../../PLAN.md#stage-34-ui4ui9-contract-packet-and-macoslinux-reference-providers).
The paths in this source list all exist at the baseline:

| Source | What the pre-draft extends |
|---|---|
| [IButton](../../../src/stdlib/GUI/IButton.btrc) | Title, enabled/selected state, symbols, queued action, and typography bounds. |
| [ITextField](../../../src/stdlib/GUI/ITextField.btrc) | Native text owner with setters; no portable input-purpose/mode contract. |
| [ISlider](../../../src/stdlib/GUI/ISlider.btrc) | Double value and enabled state; UI2 adds coherent ranges/events. |
| [ISelect](../../../src/stdlib/GUI/ISelect.btrc) | Index-based choices and 20 pt typography bound; UI2 supplies stable-key compatibility. |
| [ILabel](../../../src/stdlib/GUI/ILabel.btrc) | Text, font, centered and wrapping options. |
| [IImageView](../../../src/stdlib/GUI/IImageView.btrc), [IImageHandle](../../../src/stdlib/GUI/IImageHandle.btrc) | Decoded image publication and lifecycle. |
| [IProgressIndicator](../../../src/stdlib/GUI/IProgressIndicator.btrc), [ILevelIndicator](../../../src/stdlib/GUI/ILevelIndicator.btrc) | Running state and a meter value. |
| [IView](../../../src/stdlib/GUI/IView.btrc), [IApplication](../../../src/stdlib/GUI/IApplication.btrc), [Callback](../../../src/stdlib/Callback.btrc) | View identity/lifetime, factories and scope-owned cancellation. |
| [MacOSButton](../../../src/stdlib/GUI/MacOS/MacOSButton.btrc), [MacOSSelect](../../../src/stdlib/GUI/MacOS/MacOSSelect.btrc) | Current bordered-button/select throws above 20 pt. |
| [MacOSTextField](../../../src/stdlib/GUI/MacOS/MacOSTextField.btrc), [LinuxTextField](../../../src/stdlib/GUI/Linux/LinuxTextField.btrc) | Preserve the existing editor owner and no-op refresh; do not introduce a competing text buffer. |
| [MacOSImageView](../../../src/stdlib/GUI/MacOS/MacOSImageView.btrc), [LinuxImageView](../../../src/stdlib/GUI/Linux/LinuxImageView.btrc) | Different retained-image behavior identified for UI2 to reconcile. |
| [LinuxIndicators](../../../src/stdlib/GUI/Linux/LinuxIndicators.btrc) | Existing painted progress/meter owners. |

Proposed types/signatures below use btrc spelling. They are design excerpts,
not compilable modules or authorization to write the named interfaces. Value
types are immutable snapshots after publication. Stable string keys identify
items; labels, indices and native handles never act as identity. Factory
additions belong to CX-UIB-17 and must use the existing application owner.

Reuse the approved UI2 event/value model when it lands. The current separate
drafts are CX-UIA-18/19/20; no dependency on their unmerged files is introduced
here. Every event registration uses `ICallbackRegistration`/`CallbackScope`,
with typed handler methods and immutable payload snapshots. Semantic delivery
is queued on the UI executor, not inline in setters or native callbacks.
Synchronous native input decisions remain the UI3 input owner's responsibility.
Setters issue **zero user commands**. One accepted interaction has one terminal
commit; cancel/model/system observations cannot masquerade as user commands.
Only replaceable previews may coalesce; final commits are never coalesced away.

Optional capabilities return a proposed `ControlApplyResult` with status
`applied`, `unsupported`, `invalid` or `closed`, plus operation and reason codes.
Unsupported and invalid leave prior state intact. An explicitly accepted
adaptation is described in the result; silent no-ops and silent clamping are
forbidden. Required family behavior cannot qualify merely by returning
unsupported. Existing `void` setters and approved UI2 signatures retain their
error contract; this draft does not silently change their return types. New
`configure...` operations below use the typed result. Concrete enum names and
shared result ownership are for CX-UIB-17/CL-UIB-02 to freeze.

All controls honor effective eligibility and close/drain from UI2, focus and
commands from UI3, measurement/direction from UI5, and native semantics from
UI8. The tables name candidate native defaults and remaining adaptations.
Linux has one platform row with GTK4 and SDL-custom candidates side by side;
D23 is open. iPhone and iPad share the `ios` family and differ by `device_class`.

## N11 — Buttons and links

Owner: extend **IButton**. Preserve `onAction`, `activate`, selected state and
existing symbol vocabulary; default/cancel roles bind to UI3 command scope,
not hard-coded global Return/Escape handlers. A link emits activation intent
with a validated destination; UI7 owns external opening and its failure.
Icon-only actions require a semantic label independent of tooltip/title.

```btrc
ControlApplyResult configureRole(ButtonRole role);
ControlApplyResult configureLink(string destination);
void setSelected(bool selected);
ICallbackRegistration onAction(IButtonAction action, CallbackScope owner);
```

Roles are normal/default/cancel/link; selected is model state, not another
toggle event pipeline. Disabled/default-role conflicts resolve through the
active command scope. Cases: **E06, E13, E15, E23, E39**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSButton tracking/key equivalents; scoped default/cancel resolution and accessible link semantics, large-text bezel adaptation. |
| Linux | GTK4: GtkButton/GtkLinkButton and window default activation. SDL-custom: existing button tracking plus UI3 key routing and AT-SPI role/action bridge. Both must avoid duplicate key/action delivery. |
| Windows | BUTTON default-pushbutton behavior and SysLink; dialog/default routing must coexist with focused editor handling and UI Automation. |
| iOS | UIButton primary actions and link presentation; default/cancel is a scene command adaptation for hardware keyboards, never an unconditional Return binding. |
| Android | Button and accessible link activation; Back/cancel uses navigation policy, not a desktop Escape imitation. Explicit selectable state and TalkBack action. |

## N12 — Checkbox, radio and switch

New owners: **IToggle** for two/three-state values with checkbox/switch
presentation; **IRadioGroup** for keyed mutually exclusive selection. Radio
group owns selection once, preventing individual controls from independently
claiming exclusivity. Mixed state is valid for a tri-state checkbox; unsupported
native switch/mixed combinations return an explicit outcome.

```btrc
// IToggle
ControlApplyResult configureToggle(ToggleModel model);
ToggleState state();
ICallbackRegistration onChanged(IToggleEventHandler handler, CallbackScope owner);
// IRadioGroup
ControlApplyResult configureChoices(RadioModel model);
string? selectedKey();
ICallbackRegistration onChanged(IChoiceEventHandler handler, CallbackScope owner);
```

`ToggleModel` has label, enabled, state and presentation; `RadioModel` has
unique-key options, enabled flags, selection and allow-unselected policy.
Payloads contain key/state, origin and interaction identity. Cases:
**E05, E06, E11, E13, E15, E39**; apply E02's key-preservation invariant.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSButton switch/radio types, NSSwitch where available; explicit group model and mixed-state policy. |
| Linux | GTK4: GtkCheckButton grouping and GtkSwitch. SDL-custom: composed checkbox/radio/switch with keyboard navigation, focus and AT-SPI checked/mixed states. |
| Windows | BUTTON checkbox/three-state/radio styles and dialog group traversal; switch appearance may adapt to checkbox while retaining Boolean semantics. |
| iOS | UISwitch for Boolean switch; keyed button/list choice presentation for radio/checkbox. Mixed state requires an explicit accessible presentation or unsupported result. |
| Android | CheckBox, RadioGroup/RadioButton and Switch; mixed checkbox needs explicit semantic adaptation rather than silently treating mixed as false. |

## N13 — Segmented selection

New owner: **ISegmentedControl**. A snapshot contains stable-key segments,
labels/icons/enabled state and exclusive or multiple-selection mode. Compact
overflow must keep every enabled item reachable by keyboard/touch and semantics;
truncating the model to what fits is forbidden. Unsupported multiple selection
is a typed result, not automatic conversion to exclusive mode.

```btrc
ControlApplyResult configureSegments(SegmentedModel model);
Vector<string> selectedKeys();
ICallbackRegistration onChanged(ISegmentEventHandler handler, CallbackScope owner);
```

Reject duplicate keys and impossible selected sets before publication. Preserve
selection across reordering; removing a selected key has a model-origin outcome.
Cases: **E02, E05, E13, E15, E26, E39**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSSegmentedControl tracking modes; compact overflow/popover and label remeasurement without key loss. |
| Linux | GTK4: grouped GtkToggleButton composition; SDL-custom: keyed toggle strip. Both need explicit multiple selection and accessible overflow. |
| Windows | Toolbar check/checkgroup button styles or composed buttons; stable-key selection and keyboard overflow are provider responsibilities. |
| iOS | UISegmentedControl for exclusive mode; multiple mode needs a distinct accessible composition or typed unsupported, not emulated single selection. |
| Android | Composed ToggleButtons/native Views; group state and overflow are owned by the provider, with each item accessible exactly once. |

## N14 — Labels and read-only text

Owner: extend **ILabel** with semantic leading/center/trailing alignment,
selectability, truncation and an associated-control relation. Preserve existing
wrapping. Association resolves to a stable live control identity; its relation
disappears on close and cannot become a dangling pointer.

```btrc
ControlApplyResult configureTextPresentation(LabelPresentation presentation);
ControlApplyResult associateControl(IView? control);
void setText(string text);
```

`LabelPresentation` separates wrapping from truncation (none/head/middle/tail),
alignment and selectability. An unsupported combination is reported without
changing the label. Label activation focuses its associated eligible control
where native convention supports it. Cases: **E07, E11, E15, E20, E26, E37**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSTextField label/selectable text behavior; natural alignment, wrapping/truncation and accessibility label relation. |
| Linux | GTK4: GtkLabel selectability, ellipsization and mnemonic target. SDL-custom: shaped text, selectable range and explicit AT-SPI label relation. |
| Windows | STATIC for simple labels; read-only EDIT/RichEdit when selectable. Preserve one semantic text owner and UIA labelled-by relationship. |
| iOS | UILabel for display; noneditable selectable UITextView when requested. Match baseline/layout and avoid duplicate VoiceOver elements. |
| Android | TextView gravity/text direction, ellipsize and text selection; labelFor association and directional layout without replacing active controls. |

## N15 — Text, search and secure fields

Owner: extend **ITextField**, retaining UI2 draft/commit/cancel subscriptions.
`TextFieldConfiguration` separates role (plain/search/secure), read-only,
input purpose, submit action, autofill policy and text-admission policy. A
keyboard hint is not validation. Secure values never appear in diagnostics,
accessibility custom values, event logs or cached screenshots; editing events
remain scope-owned and carry sensitive text only where the model needs it.

```btrc
ControlApplyResult configureInput(TextFieldConfiguration configuration);
ControlApplyResult requestClear();
ICallbackRegistration onCommit(ITextControlEventHandler handler, CallbackScope owner);
ICallbackRegistration onCancel(ITextControlEventHandler handler, CallbackScope owner);
```

`requestClear` is a model operation and emits no user commit. Native clear
activation is user editing, routed through the existing event owner. Switching
secure/read-only role during composition must cancel/defer explicitly; unchanged
configuration preserves selection/undo. Secure mode disables plaintext copying
where the product policy requires it and reports native autofill limitations.
Cases: **E01, E07, E14, E18, E19, E44, E45**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSTextField, NSSearchField, NSSecureTextField and field editor; switching control class must preserve or explicitly settle the current interaction. |
| Linux | GTK4: GtkEntry/GtkSearchEntry/GtkPasswordEntry and input-purpose hints. SDL-custom: existing edit owner plus IME, secure masking and explicit unavailable autofill policy. |
| Windows | EDIT/RichEdit styles, password masking and cue text; search clear/submit composition and UIA secure-state handling. |
| iOS | UITextField/UISearchTextField traits, secureTextEntry and textContentType; native submit/autofill, keyboard occlusion and hardware-keyboard proof. |
| Android | EditText inputType/imeOptions/autofill hints; avoid resetting input connections for no-op model updates and suppress password diagnostic values. |

## N16 — Multiline plain-text editing

New owner: **ITextEditor**, reusing the UI2 text payload and native editing
owner discipline. It owns plain text, wrapping, scrolling, selection, IME,
clipboard and undo. It is not a rich-document engine or a competing buffer
inside the application command layer.

```btrc
ControlApplyResult configureEditor(TextEditorConfiguration configuration);
string text();
ControlApplyResult replaceText(string text, TextReplacementPolicy policy);
TextSelection selection();
ICallbackRegistration onDraftChanged(ITextControlEventHandler handler, CallbackScope owner);
ICallbackRegistration onCommit(ITextControlEventHandler handler, CallbackScope owner);
```

Return inserts a newline by default; commit is explicit submit/focus policy,
not every key press. Selection values use the approved text-range model with
direction preserved, never ambiguous native offsets. Cases:
**E01, E07, E14, E18, E19, E44, E45**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSTextView in NSScrollView; native text storage/undo and UTF-16 range conversion, plain-text-only configuration. |
| Linux | GTK4: GtkTextView/GtkTextBuffer. SDL-custom: existing text-input integration extended with multiline layout, native IME protocol and explicit clipboard/undo owner. |
| Windows | Unicode multiline EDIT/RichEdit; plain-text mode, undo groups, selection conversion and UIA text patterns. |
| iOS | UITextView text input and undo; resize/keyboard occlusion and scroll/focus retention through iPad split-view changes. |
| Android | Multiline EditText; IME composition, selection/action mode and TalkBack text actions, with no duplicate application editing buffer. |

## N17 — Numeric field and stepper

New owner: **INumericField**, composing a native editor and optional stepper.
`NumericModel` separates the current draft string from the last accepted typed
value, locale, range, step and units. Empty, sign-only and incomplete decimal
drafts remain editable; validation runs at the declared draft/commit boundary.
No successful parse is inferred from a keyboard's numeric layout.

```btrc
ControlApplyResult configureNumber(NumericModel model);
string draft();
NumericValue? committedValue();
ControlApplyResult stepBy(long long steps);
ICallbackRegistration onCommit(INumericEventHandler handler, CallbackScope owner);
```

`NumericValue` is a proposed tagged integer/decimal representation; integer
values never round-trip through double. The exact decimal representation is a
review choice, not an implied new language primitive. `stepBy` is model-origin;
native stepper activation yields one user commit. Invalid commit preserves the
draft and exposes validation rather than clamping it silently. Cases:
**E01, E07, E13, E19, E26, E34, E45**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSTextField/formatter plus NSStepper; preserve invalid intermediate drafts independently of committed numeric value. |
| Linux | GTK4: GtkSpinButton where its numeric representation fits, otherwise GtkEntry plus step buttons. SDL-custom: edit owner plus bounded exact-value step model. |
| Windows | EDIT plus up-down control; application numeric model owns locale and wider-than-native integer ranges. |
| iOS | UITextField purpose hints plus UIStepper when range fits; exact-value provider composition otherwise, and accessible adjust actions. |
| Android | EditText plus native increment/decrement buttons; NumberPicker only for suitable integral ranges, never a locale/precision substitute. |

## N18 — Slider and adjustable range

Owner: extend **ISlider**, preserving UI2 `SliderRange`, coherent range/value
publication and preview/commit/cancel. Units and keyboard/accessibility
adjustments carry semantic meaning independent of visual tick density.

```btrc
void setRange(double minimum, double maximum, double step);
void setRangeValue(SliderRange range, double value);
ControlApplyResult configureUnits(RangeUnits units);
ICallbackRegistration onCommit(ISliderControlEventHandler handler, CallbackScope owner);
```

Reuse UI2's validation and mid-drag cancellation policy, including degenerate
ranges, nonfinite/reversed inputs and explicit quantization. Product timeline
values stay `long long`: relative keyboard/accessibility deltas update the
exact model; double is only a native display/pointer projection. No-op refresh
cannot round `2^53+1` to `2^53`. Cases: **E03, E13, E19, E34, E39**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSSlider tracking and accessibility value; distinguish previews from terminal action and exact relative increments. |
| Linux | GTK4: GtkScale/GtkAdjustment. SDL-custom: existing slider owner. Neither native ticks nor floating-point range replace exact product coordinates. |
| Windows | TRACKBAR messages and UIA range value; map native integer position to model explicitly and retain exact keyboard/accessibility deltas. |
| iOS | UISlider tracking/touch terminal events and accessibility increment/decrement; cancellation after interruption emits no stale commit. |
| Android | SeekBar listener start/progress/stop tracking plus keyboard/accessibility actions; distinguish programmatic change and project exact model to native progress. |

## N19 — Select and combo box

Owner: extend **ISelect** and UI2 `SelectModel`, not a second option/event
protocol. Group headings are nonselectable; each option has key/title/enabled
and optional group key. Loading/empty/error/unselected/unavailable selection
remain distinct. Editable-combo capability is optional and typed.

```btrc
void setOptions(SelectModel model);
ControlApplyResult configureSelection(SelectConfiguration configuration);
string? selectedKey();
ICallbackRegistration onCommit(ISelectionControlEventHandler handler, CallbackScope owner);
```

UI2's index shim stays until BTRSmith re-pins under D24. Type-ahead uses the
declared locale matching policy, skips disabled options and can reach the final
enabled item. Refresh preserves stable selection/open candidate or reports an
explicit model cancellation. Cases: **E02, E13, E15, E19, E23, E33**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSPopUpButton/menu for noneditable selection, NSComboBox when requested; grouped/disabled rows, large text and 10,000-item cost measured. |
| Linux | GTK4: GtkDropDown/GtkListView or editable GtkEntry composition. SDL-custom: existing popup extended with keyed refresh, scrolling/search and AT-SPI. |
| Windows | COMBOBOX/common list presentation; groups/disabled rows require an accessible adapter or explicit unsupported, not owner drawing without UIA. |
| iOS | UIButton menu or picker/list presentation appropriate to size; searchable list for large choices, stable keys and focus return on iPad popover dismissal. |
| Android | Spinner or AutoCompleteTextView/list popup; grouped/disabled options and large-list search through stable-key adapter, preserving TalkBack focus. |

## N20 — Images and symbols

Owner: extend **IImageView** with fit/fill, semantic alignment, tint and an
exclusive accessible-description/decorative choice. UI2 retained presentation
remains the ownership contract. Async loading stays outside IImageView, using
the executor's cancellation and generation checks; this surface publishes
already decoded content.

```btrc
ControlApplyResult configurePresentation(ImagePresentation presentation);
void setImageHandle(IImageHandle? handle);
void setImage(Image? pixels, int maximumPixels = 16777216);
```

`ImagePresentation` includes fit/fill, leading/center/trailing alignment,
optional tint and semantics. Decorative images have no duplicate semantic node;
meaningful images require a description. Tinting is explicit; it cannot alter
another view's shared source image. Cases: **E11, E20, E24, E35, E38**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSImageView scaling and template-image tint; independent retained NSImage presentation and accessible description. |
| Linux | GTK4: GtkPicture/GtkImage content fit. SDL-custom: painter fit/fill/tint plus retained resource and AT-SPI semantics. |
| Windows | STATIC bitmap/icon or provider image view for fit/fill/tint; DPI variants and independent resource ownership, with UIA description. |
| iOS | UIImageView contentMode/tintColor and image variants; template versus original image distinction and VoiceOver element policy. |
| Android | ImageView scaleType/tint/contentDescription; decorative importance and shared drawable mutation isolated between views. |

## N21 — Progress and meters

Owners: extend **IProgressIndicator** and **ILevelIndicator**. Progress separates
hidden/indeterminate/determinate/completed/error/canceled state from activity.
Determinate fraction is finite in `[0,1]`; invalid values leave state intact.
Cancellation is a user request to the operation owner, never evidence the worker
has stopped. Meter snapshot carries finite range/value/thresholds and units.

```btrc
// IProgressIndicator
ControlApplyResult configureProgress(ProgressState state);
ICallbackRegistration onCancelRequested(IButtonAction action, CallbackScope owner);
// ILevelIndicator
ControlApplyResult configureMeter(MeterState state);
double value();
```

Cancellation availability and status text are explicit. Meter thresholds use
ordered warning/critical boundaries with declared clipping for presentation;
the reported model value is not silently rewritten. UI8 announcements coalesce
replaceable value changes and rate-limit status, while completion/error remain
terminal observations. Cases: **E04, E11, E20, E24, E39, E42**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | NSProgressIndicator/NSLevelIndicator; visible status/cancel composition and throttled accessibility value changes. |
| Linux | GTK4: GtkProgressBar/GtkLevelBar. SDL-custom: existing indicators plus deterministic states, no hidden animation loop and AT-SPI values. |
| Windows | PROGRESS_CLASS plus accessible meter adaptation; cancellation/status is a separate labelled action and UIA range values are coherent. |
| iOS | UIProgressView/UIActivityIndicatorView; meters use an accessible custom view with units/thresholds, not an animated progress spinner. |
| Android | ProgressBar determinate/indeterminate modes; meter View exposes range semantics, status and explicit cancel action without announcement flooding. |

## N22 — Forms and validation

New owner: **IForm**, a relationship/transaction owner attached to an existing
container, not a new renderer or another document store. `FormFieldBinding`
maps stable field id to control, label, help and error views. Dirty revisions
and persistence stay with the document model; UI2 close transactions and UI3
commands own Save/Discard/Cancel. Async validation is revision-tagged.

```btrc
ControlApplyResult setFields(Vector<FormFieldBinding> fields);
ControlApplyResult publishValidation(FormValidation validation);
ControlApplyResult focusFirstError();
ICallbackRegistration onSubmitRequested(IFormEventHandler handler, CallbackScope owner);
ICallbackRegistration onCancelRequested(IFormEventHandler handler, CallbackScope owner);
```

Reject duplicate ids, foreign/closed controls and cross-owner relationships.
Pending validation does not erase the current draft. An old result cannot
replace a newer field revision. Submit focuses the first reachable invalid
field in declared traversal order or reports why none is reachable; it does
not automatically discard edits. Error text survives relayout and is linked
semantically without repeating announcements on unchanged publication.
Cases: **E01, E05, E11, E18, E19, E26, E39, E46**.

| Platform | Native default and adaptation to prove |
|---|---|
| macOS | Existing NSView/control composition plus label/error accessibility relations and field-editor focus; no second native form state store. |
| Linux | GTK4: grid/box controls with accessible relations. SDL-custom: existing container plus relationship bridge and explicit keyboard/error focus order. |
| Windows | Dialog-style control composition, tab traversal and UIA labelled-by/help/status relations; validation remains revisioned application data. |
| iOS | UIKit stack/list form and accessibility labels/hints; first-error focus scrolls above keyboard, with iPad multi-scene ownership preserved. |
| Android | Native ViewGroup/EditText composition with labelFor/error/description; first-error focus and IME visibility cooperate with Back and TalkBack. |

## E15: large text changes measurement, not the user's preference

The baseline `IButton` exposes `ButtonTypography.borderedMaximumSize() == 20`;
MacOSButton rejects a bordered font above it, including when a previously
borderless button becomes bordered. ISelect/SelectTypography similarly cap
fonts at 20, and MacOSSelect throws. These are real current contracts requiring
a reviewed change, not checks to delete without replacement.

The proposed replacement is semantic typography plus constrained measurement.
At a valid accessibility text-size change, invalidate each affected intrinsic
measurement, remeasure with the same logical width and direction, then relayout
without recreating the editor or losing focus, selection, composition or undo.
For a native bezel that cannot accommodate large text, use an explicitly reviewed
native/composed presentation with equivalent action and accessibility semantics.
Do not clamp text to 20, crop a required label, or switch to an unlabeled icon.
Finite positive font/resource admission remains; invalid numeric input is still
rejected. This proposal removes the small-bezel ceiling for accessible text,
not every allocation bound.

Qualify 100/150/200% text size and explicit 19/20/21/32 pt transitions, including
bordered/borderless changes, at 320/480/1024 logical-unit widths in LTR and RTL.
Long translations, duplicate select labels and wrapped form errors must leave
actions reachable; overflow/scroll is explicit where content cannot fit.
Repeated unchanged measurement input settles without continuous relayout.
Capture native semantic bounds and clipping as well as pixels. E26 supplies
constrained measurement; UI5's writer owns the final IView signature.

## Portable fixture plan and acceptance

The following are **future fixture stems**, to be created by the final packets
under the planned `src/tests/native/gui/controls/` directory. They do not claim
these files exist on main. Every fixture runs through both compiler frontends
and the provider's real native input/probe boundary, not mock controls.

| Family | Planned fixture stems | Required assertions |
|---|---|---|
| N11 | ButtonRoles | Enabled/disabled, default/cancel precedence, icon labels, link intent; one command per accepted activation. |
| N12 | Toggles, RadioGroups | Mixed/Boolean states, stable exclusivity, keyboard/touch action, label activation and callback drain. |
| N13 | SegmentedControls | Reorder/remove stable keys, exclusive/multiple outcomes, narrow overflow and focus restoration. |
| N14 | LabelText | Leading/trailing RTL, wrapping/truncation, selection and semantic relation lifetime. |
| N15 | TextFieldModes, SecureText | Search/clear/submit, secure/autofill policy, read-only selection, unchanged-refresh continuity and no secret diagnostics. |
| N16 | TextEditor | IME, multiline Return, undo/redo and clipboard failures; no competing buffer or partial edit. |
| N17 | NumericEntry | Locale decimal/sign drafts, validation, exact integers, range/step update and explicit invalid commit. |
| N18 | RangeValues | E34 zero/reversed/nonfinite ranges, 999/1,000/1,001 intervals and exact values at 2^53−1, 2^53, 2^53+1; preview/commit/cancel order. |
| N19 | KeyedSelectLarge | E33 0/1/100/10,000 options, grouped/disabled/duplicate labels, final enabled item reachable, refresh while open and one accepted commit. |
| N20 | ImagePresentation | Two-view retention, close/replace/clear, tint isolation, decode completion after recycle, fit/fill and decorative semantics. |
| N21 | ProgressStates | Progress mode transitions, invalid fractions, cancel request versus completion, meter thresholds and bounded announcements. |
| N22 | FormValidation | Dirty revisions, stale async validation, label/error links, first-error focus and E46 failed save/cancel preservation. |
| All | LargeTextControls | E15/E26 size/direction matrix; no 20 pt throw/clamp, no clipped required actions, stable active editors. |

For every family include enabled/disabled, hidden/detached/closed, empty/invalid,
keyboard/touch/accessibility action, registration cancellation and repeated
close/drain cases. Unsupported combinations must assert a typed outcome and
unchanged state; they remain qualification gaps for required behavior.

E45 uses configurable **64 KiB single-line** and **1 MiB multiline** fixture
limits: L−1/L/L+1 UTF-8 bytes, including multibyte crossings, empty strings,
construction/setters/typing/IME/paste/drop. State the line-ending normalization
before byte admission; reject the whole oversized edit without cutting a
grapheme. These are fixture configurations, not universal product ceilings.
Collect at least 100 pointer/selection/edit samples with p95 ≤100 ms, including
validation/layout cost; record peak native and managed allocation separately.

E33 uses the same 100-sample response budget and records realization/update work
at each size, including toolkit-internal allocations. E34 runs 100
range/refresh/cancel cycles. E35 runs 100 presentation/lifetime cycles; E46 runs
100 cycles for each applicable dirty dismissal path, with zero lost drafts,
duplicate saves, stale-revision closes or wrong-owner outcomes. Run Linux X11
and Wayland separately; record iPhone/iPad device class without a sixth family.
Hosted/simulator evidence is labelled stand-in; physical IME, screen-reader
usability and display evidence remain owner sessions when automation cannot
exercise them. A table of candidate controls is not qualification.

## Questions for the five platform reviewers

1. **macOS:** which large-text button/select presentation preserves native
   keyboard and accessibility behavior above the 20 pt bezel constraint? Can
   search/secure mode changes preserve or explicitly settle the field editor?
2. **Linux:** under D23, does GTK4 satisfy input/accessibility and WebGPU
   composition together? For SDL-custom, what owned IME, shaping, AT-SPI and
   selection work is still needed for each of the 12 families? Provide both
   X11 and Wayland evidence, not a screenshot equivalence claim.
3. **Windows:** which common-control adaptations need custom UIA providers
   (grouped select, meter, selectable label, segmented overflow)? Which native
   range/selection integer limits require a wider exact model?
4. **iOS/iPadOS:** which desktop-shaped roles need scene/navigation adaptations,
   and which multiple-selection/mixed-toggle presentations are acceptable?
   Prove keyboard, software-keyboard occlusion, split view and two-scene field
   identity on iPad as well as iPhone.
5. **Android:** which native View input/Back/autofill paths require JNI additions?
   Can large select, invalid numeric draft and semantic error relationships
   survive Activity recreation without replaying commands or logging secrets?

Before approval, all reviewers must reconcile operation/result names with UI2,
the exact numeric representation, N22 ownership with UI5/UI8, text-admission
and secure-mode policy, and accepted adaptations versus remaining unsupported
requirements. New compiler/interop/runtime needs become REQUEST blocks from
the implementing packet. This pre-draft does not authorize those changes.
