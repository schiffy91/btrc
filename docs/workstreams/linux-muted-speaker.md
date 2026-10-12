# Linux muted speaker provider extension

Packet: CX-LINUX-MUTED-SPEAKER, draft PR73. Prepared from exact main
`36b647f079ed7338e51b119a11046eb222dd4877` on `codex/linux-muted-speaker-36b`.
The documentation-only claim is published; baseline and candidate source remain
local while the hosted CI slot is occupied. Actual local Linux baseline/candidate
evidence is recorded below; final hosted source qualification remains pending.
The provider implementation is the exact LinuxSymbols blob from held donor
`773287e4523fe05cf03ba91e8b28f6b92cc069eb`, extracted by the same Codex writer.
The donor remains unchanged. This packet has no image-lifetime/PR72 dependency.

`IButton.setSystemSymbol` accepts SF Symbols names, guarantees a portable minimum,
and rejects names a provider cannot draw. Linux adding `speaker.slash.fill` is a
provider extension; this patch leaves the portable minimum and IButton unchanged.
The existing Linux button rejects that name with `Native button system symbol is
unavailable`. This blocks the Linux Player muted icon; supporting its glyph alone
does not qualify the BTRSmith mute, persistence or full application journey.

LinuxSymbols appends ID18, leaving IDs0–17 intact. Muted and audible symbols share
the existing speaker body; the muted branch substitutes a diagonal slash for the
sound arcs. No native bindings, manifests, exports or public interfaces change.

The independent LinuxMutedSpeaker fixture creates one blank borderless button.
On a live composed root it first proves the audible symbol draws nonblank pixels.
It then requires the muted name to succeed, equal fitting size, nonblank muted
pixels different from audible pixels, and pixel-exact audible restoration in the
same button rectangle. Captures happen in one callback before pointer movement.
The restored symbol's fitting size is checked too. The fixture returns to muted,
requires setters to be silent, requires disabled activate() refusal, and checks
zero delivered callbacks on a later application turn before pushing one actual
SDL motion/down/up sequence. Exactly one callback must then arrive and normal
GUI shutdown must close the root. This is injected SDL input, not physical input.

The new test_linux_muted_speaker is appended to the existing native Linux driver,
using _build_and_run, gui_provider_root, native-plan build and provider environment
unchanged. Python/selfhost × plain/ASan+UBSan gives four rows, each with the existing
180-second GUI native bound. No old test body changes. The reserved
LinuxGUIControls fixture, including its image assertions, is untouched.

Baseline preparation uses the same fixture/driver with main's original provider.
The intended native RED is after `OBSERVED: audible speaker draws`, followed by
`OBSERVED: muted speaker rejected: Native button system symbol is unavailable`
and the exact `symbolError.isEmpty()` assertion failure. Compilation, display,
capture, different exceptions or timeout failures must not be classified as that
RED. Both causal markers are flushed to stderr, which the unchanged driver retains
on a native failure. All four baseline cells now reproduce that exact native failure. Candidate
success is separately established for all four unchanged native rows below.

Run the existing driver on an admitted Linux SDK/display host (with its normal
native header reader, Vulkan/font dependencies and freshly matching selfhost):
`python -B -m pytest src/tests/python/test_native_linux_providers.py::test_linux_muted_speaker`.
Keep the owner's existing 600-second transpile, native-plan compile bounds and
180-second native bound. The unchanged gui_provider_root creates only the usual
test-owned provider export copy. No compiler/stdlib generated lock update is part
of this patch. Baseline and candidate have completed the scoped Linux ARM64/X11 diagnostic;
final hosted packet gates remain required. Source checks alone are not substitutes.

Separate proposed integrator fragments add only `*::test_linux_muted_speaker*`
to the existing linux-native-reader-covered rule in macos.json and
macos-hosted.json. All four Linux cells remain required: no missing-reader/display
skip allowance is added on Linux. The current Windows workflow does not select
this module; no Windows ledger change is proposed. Those two manifest additions are the final fragment commit; integration retains
them separately from the provider and qualification report.

Preparation checks: BTRC formatter check, Ruff check/format, exact donor-provider
identity, Python AST preservation of all original tests, fixture/import source
inspection and patch application checks passed. The documentation claim was
published separately; no other source owner, shared checkout or index changed.

## Actual local Linux qualification

The retained immutable Linux ARM64 image ran under X11 with the original native
header reader/SDK/tool closure. Commands entered the authenticated saved Nix dev
environment through nix develop --command. Baseline f39f5650b3ddbfc35b901f79f129872fb356ee78
and candidate2ff4d57a05b56233800dd46ad56b9b60b53fbfd7 each received a fresh
source-consistent selfhost build through the existing make NIX= btrcc owner,
plus original paired Hello controls. Although the two resulting compiler files
are byte-identical, each was built from its own row; no stale binary reuse occurred.

Actual pytest selector: src/tests/python/test_native_linux_providers.py::test_linux_muted_speaker,
Python/selfhost × plain/ASan+UBSan, four cells per source. Baseline produced four
intended native SIGABRT failures and zero skips/errors. Every cell passed the
audible pixel control and printed the exact unavailable-symbol error, then failed
__btrc_assert_condition_38 evaluating __btrc_isEmpty(symbolError). Retained emitted
C binds the native failure to line48564 (Python) or48701 (selfhost). The baseline
receipt's passed state denotes correct RED classification, not passing programs.

Candidate passed all four original native cells, zero failures/errors/skips,
with the unchanged native PASS check and all pixel/fit/event/shutdown assertions.
The 600-second transpile, 180-second native and existing sanitizer settings remain.
ASan/UBSan coverage uses the original detect_leaks=0; no leak-test claim is made.
The in-memory composed captures establish the asserted pixel relationships,
not an independent screenshot or physical-input review.

Evidence: linux-muted-speaker-2ff4d57a-local-attempt-3 under the retained
plan-consolidation-2026-10-07 evidence root. Result SHA256:
a5b487a65e1915f99dc9bcd62e98881d2d6584b90285fb6c353d2b082c3362a5.
Baseline tests SHA256: fbaa6d16d60908dfb3c69fee4577cb07d928d8877b97c5a8a62a598aeda8117d.
Candidate tests SHA256: 7483acb91662fe15472d74c8885630564f1ab8a85f6594f7c0fbeec8d22fbea6.
Each fresh selfhost SHA256: 28ecd1602f29eb524da180b0d0a3fc8995982ae9cd32f3f66ed133221bfe077e.
All eight owned containers retired; final process-group list is empty, the owned
VM is stopped and original source/tools/inputs are unchanged. Independent audit:
3b75b85fe685bbca86c51527aae4936bfec55169d0a0f3828262afdec9bbebbe..

Earlier local attempts remain retained infrastructure failures: attempt1 stopped
before any container after the machine-start lifecycle problem; attempt2 stopped
before inner admission while offline Nix sought absent interactive-shell inputs.
Neither substitutes for the actual baseline or candidate proof.

## Hosted scope still pending

PR73's published docs-only claim is8b9ced7193c3240bca56841aedd225d5c8ac14e5.
CI run38207572143 passed generated-check/lint/format-check and seven naming
checks, and uploaded the static skip report, then exceeded its unchanged30-minute
job limit during post-job cache finalization. Its conclusion is cancelled, not
green. macOS38207572153 and Windows38207572172 were scope-only green.

The local result qualifies this provider extension on Linux ARM64/X11 only.
Final source draft-PR CI and skip gates, other architecture/Wayland coverage and
integrator landing remain pending. It is not complete UI2, physical desktop,
Windows/mobile or full BTRSmith mute/persistence/MVP acceptance.
