# CX-STDLIB-01: Linux existing-interface input repairs

Branch: `codex/stdlib-linux-event-repair`.
Base: `dff538ef502f4a074c3019f677220810e4061225`.
Parent assigned this reconstruction under PLAN D29 on 2026-10-08. The prior
scrollbar branch remains at `e3281e6ef5990479e3ae0eb22c3a09d96a64df70`.

## Owned paths

- `src/stdlib/GUI/Linux/LinuxApplication.btrc`
- `src/stdlib/GUI/Linux/LinuxSelect.btrc`
- `src/stdlib/GUI/Linux/LinuxTextField.btrc`
- `src/stdlib/GUI/Linux/LinuxWindow.btrc`
- `src/tests/native/gui/linux/LinuxEventBoundary.btrc`
- `src/tests/native/gui/shell/probes/linux/EventBoundary.c`
- `src/tests/native/gui/shell/probes/linux/EventBoundary.h`
- `src/tests/native/gui/ui2/probes/linux/` (new focused regression probes only)
- `src/tests/python/test_native_ui_linux_spike.py`
- This report.

The existing shell collector remains untouched: the recovered E40 collector
will move directly into the packet's prescribed driver, so there is only one
copy. No portable contract, compiler, generated file, PLAN, workflow or shared
harness change is claimed. Catalog/skip admission remains an integrator fragment.

## Reconstruction and qualification

The unpublished input repair `d6df2cb6335e122526204f0408602aeef6d31b66`
and combined layout repair `0f6f3448967720480365d43980c74baf7280b7e4`
were not recoverable from the checked local object stores or exact GitHub
commit endpoints. The E40 reproduction is available at
`bbe4f56e9a462002bb8d96df4bc7c7d1bed4a6f3` and will be reused.

First implement the bounded event-pump repair, preserving a fixture-only commit
before the production correction. Popup geometry, failed Cut and native
visibility are separate remaining outcomes of this packet; no acceptance is
claimed for them by the first commit pair.

Native reproduction and repaired qualification have NOT run on this source.
The parent has reserved all native/guest execution until headroom and its lane
are available. Source inspection and lightweight checks are permitted. Old
unpublished counts do not qualify this reconstruction. The fixture-only red
candidate must never land without the production repair.
