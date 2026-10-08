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

### E40 fixture-only checkpoint

Recovered the native fixture and link-only poll observer from `bbe4f56e`.
The collector now lives only in `test_native_ui_linux_spike.py`. Unlike the old
collector, it requests the provider root only after Linux/reader/display guards
and compiles both frontends with plain and ASan/UBSan modes (64 executions).
It preserves the four burst sizes and four terminal kinds, and additionally
checks that the first turn leaves exactly `max(0, count - 4096)` events queued
and services posted application work once. This prevents an unbounded-drain
"fix" from passing. The original close-prefix semantics remain.

Observer setup side effects were removed from assert expressions. Native
execution remains pending: this is a fixture-only **red candidate**, not an
executed red result. Real rendering progress under backlog still needs a
separate observed frame assertion before the full E40 outcome can be accepted.

Checks so far: Ruff lint/format and BTRC syntax/format checks; no native builds,
pytest suite or guest execution. Shared expected-skip and catalog fragments are
not yet applied; do not publish the branch as a qualified normal gate.

### Bounded dequeue correction

Fixture-only commit: `5299b7a8`. Production now stops after dispatching event
4096 **before** polling for another event. The next loop turn obtains event
4097 from SDL; no private event cache or lifetime is introduced. Window
settlement, delayed work, posted work, actions, frames and close processing
remain after the bounded batch, in their existing order.

The fixture-only and corrected revisions must be run on the same qualified
Linux environment. Expected old-source failures are genuine E40 queue/cardinality
assertions at 4097 and 8193, not compiler/setup errors. All 64 corrected rows
must pass without skips. Use the existing parent-scheduled Linux native lane:

```sh
PYTEST_WORKERS=1 tools/linux-ci.sh test-native-gui \
  'BTRC_TEST_RUNNER=linux-devcontainer' \
  'PYTEST_ARGS=-q -rs -k linux_event_boundary --basetemp=build/linux-event-proof/pytest --junitxml=build/linux-event-proof/junit.xml'
```

Preserve each run's outputs before reusing `--basetemp`. Neither this command
nor the original native reproduction has been executed in this reconstruction.
Static format checks and `git diff --check` pass. Full E40 rendering progress,
remaining input outcomes, catalog/skip admission, native qualification and
normal final gates remain open.

### Additional fixture-only checkpoint

Added a link-only `wgpuSurfacePresent` observer to E40. Startup waits boundedly
for a successful native presentation. After queuing input and invalidating the
field, the first loop turn must successfully present another frame while
backlog remains; a close request within that same turn must instead close the
window. This supersedes the earlier missing-frame-assertion note; execution is
still pending. The observer returns the original GPU result unchanged.

The new `LinuxInputRepair.btrc` and `InputRepair.c/.h` probe under the claimed
UI2 Linux probe directory cover failed Cut, downward/upward popups, and external
SDL hide/show (16 executions across the paired/sanitized matrix). Cut injects a
failed clipboard write, then retries without reselecting to prove both text and
selection survived. Popup checks an unhighlighted menu pixel in GPU readback
before clicking that exact item at a nested nonzero origin. Visibility observes
successful presentations, suppresses hidden-window work, preserves offscreen
capture, and requires resumed presentation after external SDL show.

These fixtures precede their three production corrections. They are unexecuted
red candidates, not historical-result reclassifications. No minimized/restore
or new exposure API is added by this existing hide/show repair.
