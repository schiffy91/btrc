# Linux muted speaker provider extension

Packet: CX-LINUX-MUTED-SPEAKER, draft PR73. Prepared from exact main
`36b647f079ed7338e51b119a11046eb222dd4877` on `codex/linux-muted-speaker-36b`.
The documentation-only claim is published; baseline and candidate source remain
local until actual Linux evidence and the hosted CI slot are available.
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
on a native failure. It has not been executed. Candidate success requires all four native rows;
no native, compiler, capture or sanitizer qualification is claimed here.

Run the existing driver on an admitted Linux SDK/display host (with its normal
native header reader, Vulkan/font dependencies and freshly matching selfhost):
`python -B -m pytest src/tests/python/test_native_linux_providers.py::test_linux_muted_speaker`.
Keep the owner's existing 600-second transpile, native-plan compile bounds and
180-second native bound. The unchanged gui_provider_root creates only the usual
test-owned provider export copy. No compiler/stdlib generated lock update is part
of this patch. Baseline and candidate need genuine Linux execution and the final
hosted packet gates; source checks are not substitutes.

Separate proposed integrator fragments add only `*::test_linux_muted_speaker*`
to the existing linux-native-reader-covered rule in macos.json and
macos-hosted.json. All four Linux cells remain required: no missing-reader/display
skip allowance is added on Linux. The current Windows workflow does not select
this module; no Windows ledger change is proposed. Manifests are not modified by
this scratch patch, and future integration must retain those fragments separately.

Preparation checks: BTRC formatter check, Ruff check/format, exact donor-provider
identity, Python AST preservation of all original tests, fixture/import source
inspection and patch application checks. The documentation claim was published separately after scratch preparation. No
pytest collection, compiler or native run has executed these new source rows. Raster output under the supported Linux
GPU/display/sanitizer matrix is still an execution obligation.
