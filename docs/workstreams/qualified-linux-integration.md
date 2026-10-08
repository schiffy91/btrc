# Qualified Linux component integration

Owned paths: the eight Linux GUI provider files and fourteen native fixtures/observers/drivers listed below, their four retained packet reports, PLAN.md, this report, and the append-only WORKSTREAMS.md claim. The two Mac expected-skip manifests are final integrator fragments. No Linux skip allowance changes.

This source-only assembly starts from compiler checkpoint `56d548c49ca027c9698c8546acdaf4df918630bd`, then merges current main `49f136ec94bb46cf67dd9bf407df6e4b0d79332c` at `5f176518`. Windows main retains exactly tested tree `97eb2d8e5d7c7459e8bf1675c3bffd5f671769fa`. One append-only conflict in `test_ci_workflow_contracts.py` retained both the Android license-status regression and Windows ARM64 workflow contract unchanged. Compiler sources and unrelated root audit repairs remain at56d.

The provider/test snapshots are exact47e64e21, except the single E40 fixture from2e82334d. The broader UI2 history containing2e is not imported. Frozen reference, generated files, runtime/specifications, and the existing final-gate policy are unchanged by this assembly.

| Component | Native fixed cases | Native counterfactual |
| --- | ---: | ---: |
| Grid replacement | 4 passed | 4 intended failures |
| Event budget | 64 passed | 32 intended failures,32 passing controls |
| Cut/popup/visibility | 16 passed | 12 intended failures,4 passing controls |
| Grid/Stack layout | 12 passed | 12 intended failures |
| Scrollbar | 4 passed | 4 intended failures |

**Proof boundaries:** the96-case positive tree is2202c0bd+fixture2e, while Grid4 is47e64e21. Both use the repaired808592c9 compiler, ELF AArch64 binarySHA256 `1739f6b16838694fa52297379f431777238ed8a01ec24577fc51ca7d9b07c505`, built with GCC15.2.0-O2. Eleven reachability checks and paired native baseline passed. All accepted rows have zero skips/setup errors. The100 counterfactual rows are64 native failures plus36 controls; failures are traced to exact native assertions or explicit event metrics, never setup failures.

ImageSHA256 `f68b039191ea701af68573a2a4e6ff6e9e63a224a7d62f663cd27bc083389235`; native-readerSHA256 `5358e51d4b18fd13bd0e2789b10e1215db9a94acf6ebe127ec59b8a04311d36d`; shellSHA256 `41f8c44c4368af74bbd4240b1688e2eba58a70bcf229adfbf495d8cf74f2d768`. Actual Linux ARM64/Xvfb/SDL/wgpu/lavapipe execution, not hardware-GPU or other-platform GUI evidence. Host provenance: Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0. The shared guest was stopped after all containers exited; image/configuration/evidence were preserved.

Evidence root: `~/.cache/btrc/plan-consolidation-2026-10-07/linux-provider-native-2202-grid47/repaired-808592c9/`. `qualification-summary.json` hashes every result/classification; `integration-inputs.json` hashes every desired source blob. Source inventories, original failures, corrected fixture branch-truth/laziness proof and all JUnit/native outputs remain retained.

**Pending:** this assembled tree with compiler56d has not run tests/builds. It requires independent diff review, exact-tree full tests/bootstrap/C11/generated/lint/format/extension/hygiene gates and applicable native qualification. The current tuple repair still needs source-matched paired proof. No performance improvement or final main qualification is claimed. The two reviewed Mac fragments cover the observed96 platform skips only. Grid4 Mac classification awaits an actual normal-driver skip report; no unknown skip is waived.

## Exact component inventory

| Path | SHA-256 |
| --- | --- |
| `docs/workstreams/cx-stdlib-05.md` | `e2e873b755b49e669666571561c5e6cf72888bfd168a1ed14f9065501eaa991c` |
| `docs/workstreams/stdlib-grid-replacement.md` | `d425d99e4c9476ae46ce1f27e0d24a8045f6bc1d83f3b53e9d50352fba3f8a69` |
| `docs/workstreams/stdlib-linux-event-repair.md` | `f40e643038f2ce6b5882a89ea32fd0f5a35811a06a5bcd92371c93d1241d1d66` |
| `docs/workstreams/stdlib-linux-layout.md` | `82925958abe8264d96561ea792040e88aafac4ce312c19bfccbe51452ad9be54` |
| `src/stdlib/GUI/Linux/LinuxApplication.btrc` | `c5bf71fb8a8b03a724ad2743e8500701f68e6475cdb7e9eed011983a57e73872` |
| `src/stdlib/GUI/Linux/LinuxGrid.btrc` | `4003707dd39c497701066f4900b18cdeb94c61019c2b303aa53d55eb7a8b0215` |
| `src/stdlib/GUI/Linux/LinuxScrollView.btrc` | `1d7c6df91a62051a454028a1b9386652cd61c0ac48c865666ad7522d8a42e81b` |
| `src/stdlib/GUI/Linux/LinuxSelect.btrc` | `9883de68ec6c9b89debd67dd9bae1d52530174faeadb873222687e2eafe2f5be` |
| `src/stdlib/GUI/Linux/LinuxStack.btrc` | `73fa640cd1709677c435cbc9850c7aa1b705bd229cb1d24652efe991709b0b8a` |
| `src/stdlib/GUI/Linux/LinuxTextField.btrc` | `9ae0e08f1ce8fb025ecb0dbc535934368485989332504b5e00ff587b54393850` |
| `src/stdlib/GUI/Linux/LinuxView.btrc` | `52956b80191c0c7d7f2089147653c843da006819e3dd4c1c6a335b36423b471d` |
| `src/stdlib/GUI/Linux/LinuxWindow.btrc` | `864d2a4d8e543e7a84daa4fd66463056adfaea2c1cc5bcbd75f3cd8763f22ed3` |
| `src/tests/native/gui/controls/linux/ScrollThumbBounds.btrc` | `acab381b738c4a992f30e7fc06d9b61d6ca7dc2a5e6e0d74a5381c6f59aae656` |
| `src/tests/native/gui/layout/linux/LinuxGridReplacement.btrc` | `967a3bf88bf9c6323a78d526f54af1969936d2dba9b464872c227ce1ddbd43b4` |
| `src/tests/native/gui/layout/linux/LinuxGridScrollResize.btrc` | `744e7d2e75920ec1a2676cf7ae1074434318926c00a301a794703a3f30c3e8db` |
| `src/tests/native/gui/layout/linux/LinuxStackScrollResize.btrc` | `868b7bdee4eeaecc46539d8d49b5f500ee6276f14b75b6182b63a625c55f2468` |
| `src/tests/native/gui/linux/LinuxEventBoundary.btrc` | `19c4b9fe77efacc87ecbf6eb25aaa53beaefcdacda452427309ec6d210c2b647` |
| `src/tests/native/gui/shell/probes/linux/EventBoundary.c` | `453e9498ae17fd3807f9303eb9c763a973ceddf034004c5b58ecdc353a66fc9a` |
| `src/tests/native/gui/shell/probes/linux/EventBoundary.h` | `00de333b8c6f5f90c11f92b7205dd636086aed7cdc81f69a329d7cbf23f2ae9c` |
| `src/tests/native/gui/ui2/probes/linux/InputRepair.c` | `40b6eacf5dde913a3849212d9339c98089c22e95a1e87fbbdb3f3da5cff5be04` |
| `src/tests/native/gui/ui2/probes/linux/InputRepair.h` | `325d4de54cabf4f279d6b8c811a1bb6382edbbfa449f765d1d910105801d4e8c` |
| `src/tests/native/gui/ui2/probes/linux/LinuxInputRepair.btrc` | `d10f6d4b7f80d8a95b69c0ddbbd3c0f41bb26080fa11cf6da5cd6fdce5d9650c` |
| `src/tests/python/test_native_ui_grid_replacement.py` | `31cc91341407df036ca9d086a7bf7512942ee7543c46b8780dc36b26ce6f1477` |
| `src/tests/python/test_native_ui_layout_resize.py` | `e29708de52e3fd4ce68705ec5dad489734403a920573bec5f299dfa24a33129d` |
| `src/tests/python/test_native_ui_linux_spike.py` | `b60b231111db19f971dde65d5cd9ccbf682b25de636f3cd5b0ff2319f53b1608` |
| `src/tests/python/test_native_ui_scroll_thumb.py` | `e37ad3bd13c03b17b229999d573d55c186d92a3de36f0b77f0e6f03185bfc37d` |
