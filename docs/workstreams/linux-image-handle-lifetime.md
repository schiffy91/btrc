# Linux image handle publication lifetime

Packet: CX-LINUX-IMAGE-LIFETIME. Base `36b647f079ed7338e51b119a11046eb222dd4877`; donor `bac92b20830e5adde31c638a7dd95cb917da8721`.
The same Codex writer extracts only the two exact donor source blobs from the
held UI2 composition. This packet imports no UI2 interface, manifest or harness
changes and leaves the donor untouched.

## Contract and repair

`IImageHandle` already promises that views keep their own reference after the
publication handle closes. Main's Linux view instead checked the handle's open
state while painting, so closing it removed an already published image. The
view now retains decoded pixels and their stable texture identity independently.
Closed-handle republication is rejected consistently with existing macOS resource
behavior (`MacOSImageView.setImageHandle` calls `MacOSImageHandle.nativeImage`,
which rejects a closed handle); that rejection is not explicit wording in the
portable image contract. Clearing or completing view closure releases the
presentation. No public API is added.

## Baseline and regression

Claim commit: `141a15f408fe6f83e955734e58624a5d78b9a80e`. Test-only baseline: `cc50fbb3e8ff335742c13703e100892aee16f696`.
The baseline retains main's exact production provider and installs the donor
fixture. The expected failure is the exact RGBA equality assertion after handle
close, following the original visible-green-image prerequisite. Compile/setup
failures would not establish this defect. This baseline has NOT been executed.
The fixture also checks stable handle identity, rejected closed publication and
explicit clearing; original event and capture journey remains. These pixel
oracles do not establish concurrent close races, stress or heap reclamation. The old assertion
that close erases presentation is replaced because it contradicted the existing
portable contract.

## Validation and remaining gates

Syntax-aware formatter check passed for both exact donor files. Source inspection
confirms the new explicit LinuxImageView import names an existing main module
and ILinuxImageHandle declaration; the unchanged GUIProviderRoot owner exports
Linux provider modules for this white-box fixture. This is not semantic or native
qualification.

Use the unchanged `test_native_linux_providers.py::test_linux_gui_controls`
on an admitted real Linux SDK/display host: Python/reference and selfhost, each
plain and sanitized (four cells), preserving the original 180-second native
deadline and all original driver/build guards. Execute the test-only baseline
first and authenticate its intended native assertion, then all four candidate
cells. Draft-PR CI and final-tree gates remain required; no Linux, Mac-as-Linux,
physical-input, or completed-UI2 acceptance is claimed. No native compiler,
reader, build, guest or test execution occurred during this extraction.
