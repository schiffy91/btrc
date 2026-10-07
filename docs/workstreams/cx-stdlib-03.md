# CX-STDLIB-03: preserve explicit Mac button alignment

Owned paths: `src/stdlib/GUI/MacOS/MacOSButton.btrc`,
`src/tests/native/gui/controls/macos/ButtonAlignment.btrc`, and the narrow
registration in `src/tests/python/test_native_gui_appkit.py`. This report records
the packet and its evidence.

Base: `87dd60d7`. Implement the accepted first-delivery repair from PLAN.md.
The original unpublished source is unavailable locally; reproduce the defect on
current source and reconstruct the minimal owner-layer change.

Acceptance: explicit alignment survives title/symbol changes, default alignment
remains correct, and the real AppKit fixture passes through both compilers and
required sanitizer variants. No native result is claimed by this claim commit.
