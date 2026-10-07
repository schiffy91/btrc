# WORKSTREAMS appendices, writer adjustments and review

Part of [WORKSTREAMS.md](../../WORKSTREAMS.md). These sections record how the plan was built and checked: dependency resolution and path tables, the writer adjustments, and the adversarial review.

## 8. Appendices

### Appendix A. PLAN-item references resolved to packets

Analysts wrote cross-group dependencies as PLAN item ids. Each resolves to the packet(s) that complete the item for the dependent's purpose. Ranges such as `CX-UIB-42…49` mean every packet in the range.

| Reference (as written) | Completing packet(s) | Used by |
|---|---|---|
| PLAN:btrsmith-audio-adaptation (Stage 29) | [CL-P2-26](claude.md#cl-p2-26), [CX-P2-47](codex.md#cx-p2-47) | [CX-UIB-68](codex.md#cx-uib-68) |
| PLAN:btrsmith-gpu-portability | [CX-P2-48](codex.md#cx-p2-48) | [CX-UIB-73](codex.md#cx-uib-73) |
| PLAN:btrsmith-libraryui-split | [CL-UIA-17](claude.md#cl-uia-17), [CL-UIA-18](claude.md#cl-uia-18) | [CX-UIB-67](codex.md#cx-uib-67) |
| PLAN:btrsmith-libraryui-split (Stage 32) | [CL-UIA-17](claude.md#cl-uia-17), [CL-UIA-18](claude.md#cl-uia-18) | [CX-UIB-66](codex.md#cx-uib-66) |
| PLAN:btrsmith-storage-resources | [CL-P2-25](claude.md#cl-p2-25) | [CX-UIB-71](codex.md#cx-uib-71), [CX-UIB-72](codex.md#cx-uib-72), [CX-UIB-83](codex.md#cx-uib-83) |
| PLAN:btrsmith-ui0-callers | [CL-UIA-03](claude.md#cl-uia-03) | [CX-UIB-67](codex.md#cx-uib-67), [CX-UIB-69](codex.md#cx-uib-69) |
| PLAN:platforms-a1-activity-lifecycle | [CX-P2-41](codex.md#cx-p2-41) | [CX-UIB-58](codex.md#cx-uib-58) |
| PLAN:platforms-a1-checked-jni | [CL-P2-24](claude.md#cl-p2-24) | [CL-UIB-16](claude.md#cl-uib-16), [CX-UIB-58](codex.md#cx-uib-58) |
| PLAN:platforms-a1-checked-jni (Stage 29 interop step 7: RegisterNatives) | [CL-P2-24](claude.md#cl-p2-24) | [CL-UIB-11](claude.md#cl-uib-11) |
| PLAN:platforms-a1-storage-permissions | [CX-P2-42](codex.md#cx-p2-42) | [CX-UIB-63](codex.md#cx-uib-63) |
| PLAN:platforms-a2-aaudio | [CX-P2-43](codex.md#cx-p2-43) | [CX-UIB-39](codex.md#cx-uib-39) |
| PLAN:platforms-a2-gpu (Stage 29) | [CX-P2-44](codex.md#cx-p2-44) | [CX-UIB-65](codex.md#cx-uib-65) |
| PLAN:platforms-a2-packaging-16k | [CX-P2-45](codex.md#cx-p2-45) | [CL-UIB-11](claude.md#cl-uib-11), [CX-UIB-85](codex.md#cx-uib-85) |
| PLAN:platforms-i1-app-lifecycle | [CX-P2-36](codex.md#cx-p2-36) | [CX-UIB-50](codex.md#cx-uib-50) |
| PLAN:platforms-i1-objc-protocol-adapters | [CL-P2-21](claude.md#cl-p2-21) | [CL-UIB-16](claude.md#cl-uib-16), [CX-UIB-50](codex.md#cx-uib-50) |
| PLAN:platforms-i1-objc-protocol-adapters (Stage 29, interop step 6: superclass, overrides, generic erasure) | [CL-P2-21](claude.md#cl-p2-21) | [CL-UIB-09](claude.md#cl-uib-09) |
| PLAN:platforms-i1-sandbox-storage | [CX-P2-37](codex.md#cx-p2-37) | [CX-UIB-55](codex.md#cx-uib-55) |
| PLAN:platforms-i2-app-packaging | [CX-P2-40](codex.md#cx-p2-40) | [CX-UIB-84](codex.md#cx-uib-84) |
| PLAN:platforms-i2-audio | [CX-P2-38](codex.md#cx-p2-38) | [CX-UIB-39](codex.md#cx-uib-39) |
| PLAN:platforms-i2-gpu (Stage 29) | [CX-P2-39](codex.md#cx-p2-39) | [CX-UIB-57](codex.md#cx-uib-57) |
| PLAN:platforms-p1-target-spec (Stage 24) | [CL-P1-06](claude.md#cl-p1-06) | [CL-UIB-16](claude.md#cl-uib-16) |
| PLAN:platforms-p3-fs-mobile | [CX-P2-14](codex.md#cx-p2-14) | [CX-UIB-55](codex.md#cx-uib-55), [CX-UIB-63](codex.md#cx-uib-63) |
| PLAN:platforms-p3-fs-mobile (Stage 26 scoped-resource contract) | [CL-P2-01](claude.md#cl-p2-01) | [CX-UIB-15](codex.md#cx-uib-15) |
| PLAN:platforms-p4-dependency-crossbuild (WebView2 packaging) | [CL-P2-17](claude.md#cl-p2-17) | [CX-UIB-90](codex.md#cx-uib-90) |
| PLAN:platforms-w1-win32-com-imports (Stage 27 interop step 5: com-sinks) | [CL-P2-10](claude.md#cl-p2-10) | [CL-UIB-10](claude.md#cl-uib-10) |
| PLAN:platforms-w1-win32-com-imports (Stage 27) | [CL-P2-10](claude.md#cl-p2-10) | [CX-UIB-42](codex.md#cx-uib-42) |
| PLAN:platforms-w2-gpu-image-font (Stage 29) | [CX-P2-33](codex.md#cx-p2-33), [CX-P2-34](codex.md#cx-p2-34) | [CX-UIB-49](codex.md#cx-uib-49) |
| PLAN:platforms-w2-wasapi | [CX-P2-32](codex.md#cx-p2-32) | [CX-UIB-39](codex.md#cx-uib-39) |
| PLAN:qualification-ci-android | [CX-P2-50](codex.md#cx-p2-50) | [CX-UIB-58](codex.md#cx-uib-58) |
| PLAN:qualification-ci-ios (Stage 29) | [CX-P2-49](codex.md#cx-p2-49) | [CX-UIB-50](codex.md#cx-uib-50) |
| PLAN:qualification-ci-linux-gui-audio (Stage 31) | [CL-UIA-11](claude.md#cl-uia-11) | [CL-UIB-04](claude.md#cl-uib-04) |
| PLAN:qualification-ci-windows-matrix | [CX-P2-18](codex.md#cx-p2-18) | [CX-UIB-42](codex.md#cx-uib-42) |
| PLAN:qualification-p5-journey-catalog (Stage 30) | [CL-UIA-04](claude.md#cl-uia-04) | [CX-UIB-77](codex.md#cx-uib-77) |
| PLAN:tooling-android-physical-devices | [MAC-P1-04](owner.md#mac-p1-04) | [MAC-UIB-05](owner.md#mac-uib-05), [MAC-UIB-09](owner.md#mac-uib-09) |
| PLAN:tooling-android-sdk-ndk | [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03) | [MAC-UIB-05](owner.md#mac-uib-05) |
| PLAN:tooling-ios-physical-devices | [MAC-P1-04](owner.md#mac-p1-04) | [MAC-UIB-04](owner.md#mac-uib-04), [MAC-UIB-09](owner.md#mac-uib-09) |
| PLAN:tooling-ios-simulator-runtimes | [MAC-P1-02](owner.md#mac-p1-02) | [MAC-UIB-04](owner.md#mac-uib-04) |
| PLAN:tooling-linux-desktop-host (Stage 30) | [MAC-UIA-01](owner.md#mac-uia-01) | [MAC-UIB-02](owner.md#mac-uib-02) |
| PLAN:tooling-linux-headless-gui (Stage 30) | [CL-UIA-21](claude.md#cl-uia-21) | [CL-UIB-03](claude.md#cl-uib-03), [CL-UIB-04](claude.md#cl-uib-04) |
| PLAN:ui-0-catalog-schema (Stage 30) | [CX-UIA-02](codex.md#cx-uia-02) | [CX-UIB-40](codex.md#cx-uib-40) |
| PLAN:ui-1-android-shell (Stage 31) | [CX-UIA-17](codex.md#cx-uia-17) | [CX-UIB-58](codex.md#cx-uib-58) |
| PLAN:ui-1-feasibility-review (D23 toolkit) | [CL-UIA-10](claude.md#cl-uia-10) | [CX-UIB-20](codex.md#cx-uib-20) |
| PLAN:ui-1-feasibility-review (D23) | [CL-UIA-10](claude.md#cl-uia-10) | [CL-UIB-03](claude.md#cl-uib-03), [CL-UIB-12](claude.md#cl-uib-12), [CX-UIB-21](codex.md#cx-uib-21) |
| PLAN:ui-1-feasibility-review (five shells, D23) | [CL-UIA-10](claude.md#cl-uia-10), [CX-UIA-15](codex.md#cx-uia-15), [CX-UIA-16](codex.md#cx-uia-16), [CX-UIA-17](codex.md#cx-uia-17) | [CX-UIB-10](codex.md#cx-uib-10) |
| PLAN:ui-1-ios-shell (Stage 31) | [CX-UIA-16](codex.md#cx-uia-16) | [CX-UIB-50](codex.md#cx-uib-50) |
| PLAN:ui-1-linux-gobject-binding (Stage 31 interop step 8) | [CL-UIA-08](claude.md#cl-uia-08) | [CL-UIB-12](claude.md#cl-uib-12) |
| PLAN:ui-1-shell-fixture (Stage 31) | [CX-UIA-09](codex.md#cx-uia-09) | [CX-UIB-77](codex.md#cx-uib-77) |
| PLAN:ui-1-windows-shell (Stage 31) | [CX-UIA-15](codex.md#cx-uia-15) | [CX-UIB-42](codex.md#cx-uib-42) |
| PLAN:ui-2-linux | [CL-UIA-14](claude.md#cl-uia-14) | [CX-UIB-66](codex.md#cx-uib-66) |
| PLAN:ui-2-macos | [CL-UIA-14](claude.md#cl-uia-14) | [CX-UIB-66](codex.md#cx-uib-66) |
| PLAN:ui-3-contract-input | [CL-UIA-20](claude.md#cl-uia-20) | [CX-UIB-50](codex.md#cx-uib-50), [CX-UIB-58](codex.md#cx-uib-58) |
| PLAN:ui-3-contract-input (Stage 33 atomic landing with ui-3-macos/ui-3-linux) | [CL-UIA-20](claude.md#cl-uia-20) | [CX-UIB-10](codex.md#cx-uib-10) |
| PLAN:ui-3-contract-input (Stage 33 landing) | [CL-UIA-20](claude.md#cl-uia-20) | [CX-UIB-11](codex.md#cx-uib-11), [CX-UIB-12](codex.md#cx-uib-12), [CX-UIB-14](codex.md#cx-uib-14), [CX-UIB-15](codex.md#cx-uib-15), [CX-UIB-16](codex.md#cx-uib-16) |
| PLAN:ui-3-contract-input (Stage 33) | [CL-UIA-20](claude.md#cl-uia-20) | [CX-UIB-42](codex.md#cx-uib-42) |
| PLAN:ui-3-linux | [CL-UIA-20](claude.md#cl-uia-20) | [CX-UIB-67](codex.md#cx-uib-67) |
| PLAN:ui-3-macos | [CL-UIA-20](claude.md#cl-uia-20) | [CX-UIB-67](codex.md#cx-uib-67) |
| btrsmith-p0-inventory | [CX-P1-01](codex.md#cx-p1-01) | [CL-UIA-04](claude.md#cl-uia-04) |
| ccompat-r18-preprocessor-conditionals (C4's lazy ConditionalEnvironment and UnitCache in the LSP) | [CL-C-06](claude.md#cl-c-06) | [CL-P1-06](claude.md#cl-p1-06) |
| ccompat-r18-preprocessor-conditionals (Stage 16 C4 evaluator lane: test_preprocessor_conditionals.py and the M3 predicate exist) | [CL-C-06](claude.md#cl-c-06) | [CL-P1-05](claude.md#cl-p1-05) |
| ext:btrsmith-cross-target-build (Stage 28) | [CL-P2-16](claude.md#cl-p2-16) | [CL-R-40](claude.md#cl-r-40) |
| ext:btrsmith-package-closure (Stage 28) | [CL-P2-17](claude.md#cl-p2-17) | [CX-R-14](codex.md#cx-r-14) |
| `ext:btrsmith-ui-slice*` (Stage 36) | CX-UIB-66…76 | [CL-R-47](claude.md#cl-r-47) |
| ext:bucket-5 opening (D1/D25) | (no packet: outside this plan) | [CX-R-04](codex.md#cx-r-04) |
| ext:ccompat-c5-docs-final (Stage 21) for M8b | [CL-C-40](claude.md#cl-c-40) | [CL-R-34](claude.md#cl-r-34) |
| ext:platforms-i2-app-packaging and platforms-a2-packaging-16k (Stage 29) | [CX-P2-40](codex.md#cx-p2-40), [CX-P2-45](codex.md#cx-p2-45) | [CX-R-10](codex.md#cx-r-10) |
| ext:platforms-p1-host-ios and platforms-p1-host-android (Stage 25) | [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09) | [CL-R-42](claude.md#cl-r-42) |
| ext:platforms-p1-host-windows, host-ios, host-android (Stage 25) | [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09) | [CL-R-43](claude.md#cl-r-43) |
| ext:platforms-p1-target-spec (Stage 24, includes the btrc.target LSP setting) | [CL-P1-06](claude.md#cl-p1-06) | [CL-R-43](claude.md#cl-r-43) |
| ext:platforms-p1-target-spec and platforms-p1-native-plan-toolchain (Stage 24) | [CL-P1-06](claude.md#cl-p1-06), [CL-P1-11](claude.md#cl-p1-11), [CL-P1-12](claude.md#cl-p1-12) | [CL-R-40](claude.md#cl-r-40) |
| ext:platforms-p2-ci-lanes (Stage 25) | [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09) | [CL-R-39](claude.md#cl-r-39) |
| ext:platforms-w1-ci-and-bundle (Stage 27) | [CL-P2-15](claude.md#cl-p2-15), [CX-P2-18](codex.md#cx-p2-18) | [CL-R-44](claude.md#cl-r-44) |
| ext:platforms-w2-packaging (Stage 29) | [CX-P2-35](codex.md#cx-p2-35) | [CX-R-09](codex.md#cx-r-09) |
| ext:platforms-w2-packaging, platforms-i2-app-packaging, platforms-a2-packaging-16k (Stage 29) | [CX-P2-35](codex.md#cx-p2-35), [CX-P2-40](codex.md#cx-p2-40), [CX-P2-45](codex.md#cx-p2-45) | [CX-R-11](codex.md#cx-r-11), [CX-R-14](codex.md#cx-r-14) |
| ext:platforms-w2-wasapi, platforms-i2-audio, platforms-a2-aaudio (Stage 29) | [CX-P2-32](codex.md#cx-p2-32), [CX-P2-38](codex.md#cx-p2-38), [CX-P2-43](codex.md#cx-p2-43) | [CX-R-02](codex.md#cx-r-02) |
| ext:qualification-ci-android (Stage 29) | [CX-P2-50](codex.md#cx-p2-50) | [CL-R-39](claude.md#cl-r-39) |
| ext:qualification-ci-ios (Stage 29) | [CX-P2-49](codex.md#cx-p2-49) | [CL-R-39](claude.md#cl-r-39) |
| ext:qualification-ci-linux-gui-audio (Stage 31) | [CL-UIA-11](claude.md#cl-uia-11) | [CL-R-39](claude.md#cl-r-39) |
| ext:qualification-ci-windows-matrix (Stage 27) | [CX-P2-18](codex.md#cx-p2-18) | [CL-R-39](claude.md#cl-r-39) |
| ext:qualification-p5-journey-drivers (Stage 37) | CX-UIB-77…82 | [CL-R-41](claude.md#cl-r-41), [CX-R-05](codex.md#cx-r-05), [CX-R-06](codex.md#cx-r-06), [CX-R-09](codex.md#cx-r-09), [CX-R-18](codex.md#cx-r-18) |
| ext:qualification-p5-journey-drivers and ui-10-automation-diagnostics (Stage 37) | CX-UIB-77…82 | [CX-R-08](codex.md#cx-r-08) |
| ext:qualification-p6-runtime-probes (Stage 34) | [CX-UIB-38](codex.md#cx-uib-38) | [CX-R-12](codex.md#cx-r-12) |
| ext:tooling-android-ci-emulator (Stage 25) | [CX-P1-05](codex.md#cx-p1-05) | [CL-R-39](claude.md#cl-r-39) |
| ext:ui-10-btrsmith-mobile and qualification-p5-journey-drivers (Stage 37) | [CX-UIB-84](codex.md#cx-uib-84), [CX-UIB-85](codex.md#cx-uib-85), CX-UIB-77…82 | [CX-R-10](codex.md#cx-r-10) |
| ext:ui-10-qualification (Stage 37) | [CL-UIB-17](claude.md#cl-uib-17) | [CX-R-12](codex.md#cx-r-12) |
| ext:ui-4-btrsmith-settings, ui-5-btrsmith-adaptive (Stage 36) | [CX-UIB-68](codex.md#cx-uib-68), [CX-UIB-69](codex.md#cx-uib-69), [CX-UIB-70](codex.md#cx-uib-70) | [CX-R-07](codex.md#cx-r-07) |
| ext:ui-6-btrsmith-library and btrsmith-ui-slice3-library (Stage 36) | [CX-UIB-71](codex.md#cx-uib-71), [CX-UIB-72](codex.md#cx-uib-72) | [CX-R-05](codex.md#cx-r-05) |
| ext:ui-9-btrsmith-player and btrsmith-ui-slice4-player (Stage 36) | [CX-UIB-73](codex.md#cx-uib-73), [CX-UIB-74](codex.md#cx-uib-74) | [CX-R-06](codex.md#cx-r-06) |
| `ext:ui-ios-*` and `ui-android-*` (Stage 35) | CX-UIB-50…57, CX-UIB-58…65 | [CX-R-10](codex.md#cx-r-10) |
| `ext:ui-win-*` (Stage 35) | CX-UIB-42…49 | [CX-R-09](codex.md#cx-r-09) |
| native_abi.asdl v2-v4 sequence (Stage 27 steps 1-4) | [CL-P2-05](claude.md#cl-p2-05), [CL-P2-07](claude.md#cl-p2-07), [CL-P2-08](claude.md#cl-p2-08) | [CL-UIB-16](claude.md#cl-uib-16) |
| platforms-a1-activity-lifecycle | [CX-P2-41](codex.md#cx-p2-41) | [CX-UIA-17](codex.md#cx-uia-17) |
| platforms-a1-checked-jni | [CL-P2-24](claude.md#cl-p2-24) | [CX-UIA-17](codex.md#cx-uia-17) |
| platforms-i1-app-lifecycle | [CX-P2-36](codex.md#cx-p2-36) | [CX-UIA-16](codex.md#cx-uia-16) |
| platforms-i1-objc-protocol-adapters | [CL-P2-21](claude.md#cl-p2-21) | [CX-UIA-16](codex.md#cx-uia-16) |
| platforms-i2-gpu | [CX-P2-39](codex.md#cx-p2-39) | [CX-UIA-16](codex.md#cx-uia-16) |
| platforms-interop-function-table-calls | [CL-P2-06](claude.md#cl-p2-06) | [CX-UIA-15](codex.md#cx-uia-15) |
| platforms-p0-adaptations | [CX-P1-02](codex.md#cx-p1-02) | [CL-UIA-04](claude.md#cl-uia-04) |
| platforms-p1-host-android | [CX-P1-09](codex.md#cx-p1-09) | [CX-UIA-17](codex.md#cx-uia-17) |
| platforms-p1-host-ios | [CX-P1-08](codex.md#cx-p1-08) | [CX-UIA-16](codex.md#cx-uia-16) |
| platforms-p1-provider-filters | [CL-P1-14](claude.md#cl-p1-14) | [CX-UIA-15](codex.md#cx-uia-15) |
| platforms-p1-target-spec | [CL-P1-06](claude.md#cl-p1-06) | [CX-UIA-15](codex.md#cx-uia-15), [CX-UIA-16](codex.md#cx-uia-16), [CX-UIA-17](codex.md#cx-uia-17) |
| platforms-w1-win32-com-imports | [CL-P2-10](claude.md#cl-p2-10) | [CX-UIA-15](codex.md#cx-uia-15) |
| stage22:platforms-p0-adaptations | [CX-P1-02](codex.md#cx-p1-02) | [CX-P2-28](codex.md#cx-p2-28), [CX-P2-35](codex.md#cx-p2-35) |
| stage23:platforms-p1-toolchains | [CL-P1-02](claude.md#cl-p1-02) | [CX-P2-22](codex.md#cx-p2-22), [CX-P2-25](codex.md#cx-p2-25) |
| stage23:tooling-android-sdk-ndk | [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03) | [CL-P2-08](claude.md#cl-p2-08), [CX-P2-20](codex.md#cx-p2-20), [MAC-P2-02](owner.md#mac-p2-02) |
| stage23:tooling-ios-simulator-runtimes | [MAC-P1-02](owner.md#mac-p1-02) | [MAC-P2-01](owner.md#mac-p2-01), [MAC-P2-02](owner.md#mac-p2-02) |
| stage23:tooling-windows-ci-arm64-llvm | [CX-P1-03](codex.md#cx-p1-03) | [CL-P2-11](claude.md#cl-p2-11), [CX-P2-18](codex.md#cx-p2-18), [CX-P2-26](codex.md#cx-p2-26) |
| stage24:platforms-p1-abi-fixture | [CL-P1-13](claude.md#cl-p1-13) | [CL-P2-05](claude.md#cl-p2-05), [CX-P2-22](codex.md#cx-p2-22) |
| stage24:platforms-p1-cache-identity | [CL-P1-15](claude.md#cl-p1-15) | [CL-P2-16](claude.md#cl-p2-16), [CL-P2-19](claude.md#cl-p2-19), [CX-P2-22](codex.md#cx-p2-22) |
| stage24:platforms-p1-hosted-abi-targets | [CL-P1-09](claude.md#cl-p1-09) | [CL-P2-02](claude.md#cl-p2-02), [CL-P2-03](claude.md#cl-p2-03) |
| stage24:platforms-p1-native-import-targets | [CL-P1-10](claude.md#cl-p1-10) | [CL-P2-05](claude.md#cl-p2-05), [CL-P2-10](claude.md#cl-p2-10), [CL-P2-11](claude.md#cl-p2-11), [CX-P2-04](codex.md#cx-p2-04), [CX-P2-07](codex.md#cx-p2-07), [CX-P2-10](codex.md#cx-p2-10), [CX-P2-15](codex.md#cx-p2-15), [CX-P2-16](codex.md#cx-p2-16), [CX-P2-43](codex.md#cx-p2-43) |
| stage24:platforms-p1-native-plan-toolchain | [CL-P1-11](claude.md#cl-p1-11), [CL-P1-12](claude.md#cl-p1-12) | [CL-P2-16](claude.md#cl-p2-16), [CL-P2-19](claude.md#cl-p2-19), [CX-P2-22](codex.md#cx-p2-22) |
| stage24:platforms-p1-provider-filters | [CL-P1-14](claude.md#cl-p1-14) | [CX-P2-04](codex.md#cx-p2-04), [CX-P2-06](codex.md#cx-p2-06), [CX-P2-07](codex.md#cx-p2-07), [CX-P2-09](codex.md#cx-p2-09), [CX-P2-11](codex.md#cx-p2-11), [CX-P2-15](codex.md#cx-p2-15), [CX-P2-25](codex.md#cx-p2-25) |
| stage24:platforms-p1-target-spec | [CL-P1-06](claude.md#cl-p1-06) | [CL-P2-07](claude.md#cl-p2-07) |
| stage25:platforms-p1-host-android | [CX-P1-09](codex.md#cx-p1-09) | [CL-P2-09](claude.md#cl-p2-09), [CL-P2-24](claude.md#cl-p2-24), [CX-P2-06](codex.md#cx-p2-06), [CX-P2-12](codex.md#cx-p2-12), [CX-P2-14](codex.md#cx-p2-14), [CX-P2-20](codex.md#cx-p2-20), [CX-P2-43](codex.md#cx-p2-43), [MAC-P2-02](owner.md#mac-p2-02) |
| stage25:platforms-p1-host-ios | [CX-P1-08](codex.md#cx-p1-08) | [CL-P2-21](claude.md#cl-p2-21), [CX-P2-06](codex.md#cx-p2-06), [CX-P2-11](codex.md#cx-p2-11), [CX-P2-14](codex.md#cx-p2-14), [CX-P2-21](codex.md#cx-p2-21), [CX-P2-36](codex.md#cx-p2-36), [MAC-P2-02](owner.md#mac-p2-02) |
| stage25:platforms-p1-host-windows | [CX-P1-07](codex.md#cx-p1-07) | [CL-P2-02](claude.md#cl-p2-02), [CX-P2-04](codex.md#cx-p2-04), [CX-P2-07](codex.md#cx-p2-07), [CX-P2-10](codex.md#cx-p2-10) |
| stage25:platforms-p2-ci-lanes | [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09) | [CL-P2-15](claude.md#cl-p2-15), [CX-P2-18](codex.md#cx-p2-18), [CX-P2-49](codex.md#cx-p2-49) |
| stage25:platforms-p2-runtime-semantics | [CL-P1-19](claude.md#cl-p1-19) | [CX-P2-04](codex.md#cx-p2-04), [CX-P2-15](codex.md#cx-p2-15), [CX-P2-32](codex.md#cx-p2-32), [CX-P2-38](codex.md#cx-p2-38), [CX-P2-43](codex.md#cx-p2-43) |
| stage25:platforms-p2-target-probes | [CL-P1-16](claude.md#cl-p1-16) | [CL-P2-02](claude.md#cl-p2-02), [CX-P2-05](codex.md#cx-p2-05), [CX-P2-14](codex.md#cx-p2-14) |
| stage25:platforms-p2-target-runner | [CL-P1-17](claude.md#cl-p1-17) | [CX-P2-06](codex.md#cx-p2-06), [CX-P2-13](codex.md#cx-p2-13), [CX-P2-29](codex.md#cx-p2-29), [CX-P2-30](codex.md#cx-p2-30) |
| stage25:tooling-android-ci-emulator | [CX-P1-05](codex.md#cx-p1-05) | [CX-P2-50](codex.md#cx-p2-50) |
| stage32:ui-2-contract-executor (draft) | [CX-UIA-19](codex.md#cx-uia-19) | [CL-P2-22](claude.md#cl-p2-22) |
| stage32:ui-2-contract-lifecycle (draft) | [CX-UIA-20](codex.md#cx-uia-20) | [CL-P2-22](claude.md#cl-p2-22) |
| tooling-android-ci-emulator | [CX-P1-05](codex.md#cx-p1-05) | [CX-UIA-17](codex.md#cx-uia-17) |
| tooling-android-sdk-ndk | [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03) | [CX-UIA-17](codex.md#cx-uia-17) |
| tooling-cross-gpu-deps | [CL-P2-29](claude.md#cl-p2-29) | [CX-UIA-15](codex.md#cx-uia-15) |
| tooling-ios-simulator-runtimes | [MAC-P1-02](owner.md#mac-p1-02) | [CX-UIA-16](codex.md#cx-uia-16) |

### Appendix B. PLAN items → packets

Every PLAN item named in a packet's `plan_items`. A `[part]`, `#part` or `(part)` suffix in a packet's own list shows which share it carries. A `(+ CX-STDLIB-0N)` suffix names the [CODEX.md](../../CODEX.md#first-delivery-queue) unit that took over that item's existing-interface repair (D28); it is not a packet.

| PLAN item | Packets |
|---|---|
| `btrsmith-audio-adaptation` | [CL-P2-26](claude.md#cl-p2-26), [CX-P2-47](codex.md#cx-p2-47) |
| `btrsmith-c-compat-regression` | [CX-C-01](codex.md#cx-c-01), [MAC-C-01](owner.md#mac-c-01), [MAC-C-04](owner.md#mac-c-04), [MAC-C-08](owner.md#mac-c-08), [MAC-C-09](owner.md#mac-c-09) |
| `btrsmith-c-compatibility-regression` | [MAC-C-02](owner.md#mac-c-02) |
| `btrsmith-cross-target-build` | [CL-P2-16](claude.md#cl-p2-16), [CX-P2-19](codex.md#cx-p2-19), [CX-P2-20](codex.md#cx-p2-20), [CX-P2-21](codex.md#cx-p2-21), [MAC-P2-03](owner.md#mac-p2-03), [CL-R-48](claude.md#cl-r-48) |
| `btrsmith-dev-mode` | [CL-R-22](claude.md#cl-r-22), [MAC-R-06](owner.md#mac-r-06) |
| `btrsmith-gpu-portability` | [CX-P2-48](codex.md#cx-p2-48), [MAC-P2-04](owner.md#mac-p2-04) |
| `btrsmith-libraryui-split` | [CL-UIA-16](claude.md#cl-uia-16), [CL-UIA-17](claude.md#cl-uia-17), [CL-UIA-18](claude.md#cl-uia-18), [MAC-UIA-05](owner.md#mac-uia-05) |
| `btrsmith-macos-mvp-automatable` | [CX-R-05](codex.md#cx-r-05), [CX-R-06](codex.md#cx-r-06), [CX-R-07](codex.md#cx-r-07), [MAC-R-10](owner.md#mac-r-10) |
| `btrsmith-macos-mvp-physical` | [CX-R-03](codex.md#cx-r-03), [CX-R-04](codex.md#cx-r-04), [MAC-R-13](owner.md#mac-r-13) |
| `btrsmith-p0-inventory` | [CX-P1-01](codex.md#cx-p1-01) |
| `btrsmith-package-closure` | [CL-P2-17](claude.md#cl-p2-17), [CX-P2-22](codex.md#cx-p2-22), [CX-P2-23](codex.md#cx-p2-23), [CX-P2-24](codex.md#cx-p2-24), [MAC-P2-03](owner.md#mac-p2-03) |
| `btrsmith-pin-bump` | [CL-R-01](claude.md#cl-r-01), [MAC-R-01](owner.md#mac-r-01) |
| `btrsmith-portable-coverage` | [CX-R-22](codex.md#cx-r-22), [MAC-R-04](owner.md#mac-r-04) |
| `btrsmith-q-ci` | [CL-R-37](claude.md#cl-r-37) |
| `btrsmith-q-platform-release` | [CX-R-21](codex.md#cx-r-21) |
| `btrsmith-q-selfhost-matrix` | [CL-R-47](claude.md#cl-r-47), [MAC-R-10](owner.md#mac-r-10) |
| `btrsmith-storage-resources` | [CL-P2-25](claude.md#cl-p2-25), [CX-P2-46](codex.md#cx-p2-46) |
| `btrsmith-structure-repo` | [CL-R-00](claude.md#cl-r-00) |
| `btrsmith-structure-stdlib` | [CL-R-00](claude.md#cl-r-00) |
| `btrsmith-test-batch` | [CL-R-20](claude.md#cl-r-20), [MAC-R-06](owner.md#mac-r-06) |
| `btrsmith-ui-accessibility` | [CX-UIB-75](codex.md#cx-uib-75), [CX-UIB-76](codex.md#cx-uib-76) |
| `btrsmith-ui-adaptive-layout` | [CX-UIB-69](codex.md#cx-uib-69), [CX-UIB-70](codex.md#cx-uib-70) |
| `btrsmith-ui-event-loop` | [CX-UIB-66](codex.md#cx-uib-66) |
| `btrsmith-ui-slice1` | [MAC-UIB-07](owner.md#mac-uib-07) |
| `btrsmith-ui-slice1-search-filters` | [CX-UIB-67](codex.md#cx-uib-67) |
| `btrsmith-ui-slice2-settings` | [CX-UIB-68](codex.md#cx-uib-68) |
| `btrsmith-ui-slice3-library` | [CX-UIB-71](codex.md#cx-uib-71), [CX-UIB-72](codex.md#cx-uib-72) |
| `btrsmith-ui-slice4-player` | [CX-UIB-73](codex.md#cx-uib-73), [CX-UIB-74](codex.md#cx-uib-74) |
| `btrsmith-ui-slice5-mobile-restoration` | [CX-UIB-83](codex.md#cx-uib-83), [CX-UIB-84](codex.md#cx-uib-84), [CX-UIB-85](codex.md#cx-uib-85), [MAC-UIB-09](owner.md#mac-uib-09) |
| `btrsmith-ui0-callers` | [CL-UIA-03](claude.md#cl-uia-03) |
| `ccompat-c1-integrate` | [CL-C-01](claude.md#cl-c-01), [MAC-C-01](owner.md#mac-c-01) |
| `ccompat-c2-integrate` | [CL-C-16](claude.md#cl-c-16), [CX-C-02](codex.md#cx-c-02), [MAC-C-04](owner.md#mac-c-04) |
| `ccompat-c2-schema` | [CL-C-07](claude.md#cl-c-07), [CL-C-08](claude.md#cl-c-08), [MAC-C-03](owner.md#mac-c-03) |
| `ccompat-c3-integrate` | [CL-C-37](claude.md#cl-c-37), [CX-C-03](codex.md#cx-c-03), [MAC-C-08](owner.md#mac-c-08) |
| `ccompat-c3-schema-vocabulary` | [CL-C-00](claude.md#cl-c-00), [CL-C-23](claude.md#cl-c-23), [CL-C-24](claude.md#cl-c-24), [CL-C-25](claude.md#cl-c-25), [CL-C-26](claude.md#cl-c-26), [MAC-C-05](owner.md#mac-c-05), [MAC-C-06](owner.md#mac-c-06) |
| `ccompat-c5-docs-final` | [CL-C-38](claude.md#cl-c-38), [CL-C-39](claude.md#cl-c-39), [CL-C-40](claude.md#cl-c-40), [MAC-C-09](owner.md#mac-c-09) |
| `ccompat-r08-typedef-struct-anonymous-members` | [CL-C-10](claude.md#cl-c-10) |
| `ccompat-r09-union-declarations` | [CL-C-09](claude.md#cl-c-09) |
| `ccompat-r10-designated-init-compound-literals` | [CL-C-11](claude.md#cl-c-11), [CL-C-12](claude.md#cl-c-12) |
| `ccompat-r11-goto-labels` | [CL-C-00](claude.md#cl-c-00), [CL-C-02](claude.md#cl-c-02), [CL-C-34](claude.md#cl-c-34), [CL-C-35](claude.md#cl-c-35), [CL-C-36](claude.md#cl-c-36) |
| `ccompat-r12-bitfields` | [CL-C-15](claude.md#cl-c-15) |
| `ccompat-r13-flexible-array-members` | [CL-C-13](claude.md#cl-c-13), [CL-C-17](claude.md#cl-c-17) |
| `ccompat-r14-variadic-definitions` | [CL-C-33](claude.md#cl-c-33) |
| `ccompat-r15a-qualifiers-storage-classes` | [CL-C-32](claude.md#cl-c-32), [MAC-C-07](owner.md#mac-c-07) |
| `ccompat-r15b-inline-noreturn` | [CL-C-02](claude.md#cl-c-02), [CL-C-27](claude.md#cl-c-27) |
| `ccompat-r15c-static-assert` | [CL-C-28](claude.md#cl-c-28) |
| `ccompat-r15d-alignment` | [CL-C-29](claude.md#cl-c-29) |
| `ccompat-r16-wide-literals-long-double` | [CL-C-30](claude.md#cl-c-30) |
| `ccompat-r17-multidimensional-arrays` | [CL-C-18](claude.md#cl-c-18), [CL-C-19](claude.md#cl-c-19), [CL-C-20](claude.md#cl-c-20), [CL-C-21](claude.md#cl-c-21), [CL-C-22](claude.md#cl-c-22), [MAC-C-05](owner.md#mac-c-05) |
| `ccompat-r18-preprocessor-conditionals` | [CL-C-03](claude.md#cl-c-03), [CL-C-04](claude.md#cl-c-04), [CL-C-05](claude.md#cl-c-05), [CL-C-06](claude.md#cl-c-06), [MAC-C-02](owner.md#mac-c-02) |
| `ccompat-x-enum-tag-spelling` | [CL-C-14](claude.md#cl-c-14) |
| `ccompat-x-expression-stragglers` | [CL-C-31](claude.md#cl-c-31) |
| `decision:D27` | [CL-UIB-01](claude.md#cl-uib-01) |
| `exit:compiler-requests-from-codex-packets` | [CL-UIB-13](claude.md#cl-uib-13) |
| `exit:stage34-E36-E38-E42-E43-idle-cpu` | [MAC-UIB-03](owner.md#mac-uib-03) |
| `exit:stage34-ci-ui-shards` | [CL-UIB-04](claude.md#cl-uib-04) |
| `exit:stage34-contract-packet-approval` | [CL-UIB-02](claude.md#cl-uib-02) |
| `exit:stage34-landing-L1-UI4` | [CL-UIB-05](claude.md#cl-uib-05) |
| `exit:stage34-landing-L2-UI5` | [CL-UIB-06](claude.md#cl-uib-06) |
| `exit:stage34-landing-L3-UI6-UI9` | [CL-UIB-07](claude.md#cl-uib-07) |
| `exit:stage34-landing-L4-UI7-and-close` | [CL-UIB-08](claude.md#cl-uib-08) |
| `exit:stage34-linux-tooling` | [CL-UIB-03](claude.md#cl-uib-03) |
| `exit:stage34-ui8-screen-reader-and-hardware-evidence` | [CX-UIB-40](codex.md#cx-uib-40) |
| `exit:stage35-track-landings` | [CL-UIB-14](claude.md#cl-uib-14), [CL-UIB-19](claude.md#cl-uib-19) |
| `exit:stage36-integration` | [CL-UIB-15](claude.md#cl-uib-15) |
| `exit:stage37-full-gate` | [CL-UIB-17](claude.md#cl-uib-17) |
| `native-ui-api-inventory` | [CX-UIB-17](codex.md#cx-uib-17) |
| `native-ui-parity` | [CX-UIB-41](codex.md#cx-uib-41) |
| `perf-arc-thread-confined` | [CL-R-32](claude.md#cl-r-32), [CL-R-33](claude.md#cl-r-33) |
| `perf-baseline-round` | [CL-R-02](claude.md#cl-r-02), [CL-R-03](claude.md#cl-r-03), [MAC-R-02](owner.md#mac-r-02) |
| `perf-batch-10` | [CL-R-20](claude.md#cl-r-20), [MAC-R-06](owner.md#mac-r-06) |
| `perf-borrowed-returns` | [CL-R-32](claude.md#cl-r-32), [CL-R-33](claude.md#cl-r-33) |
| `perf-cold-native` | [CL-R-28](claude.md#cl-r-28), [MAC-R-08](owner.md#mac-r-08) |
| `perf-cold-release` | [CL-R-21](claude.md#cl-r-21), [MAC-R-06](owner.md#mac-r-06) |
| `perf-decl-lowering-hotspots` | [CL-R-30](claude.md#cl-r-30), [MAC-R-08](owner.md#mac-r-08) |
| `perf-decl-session-cache` | [CL-R-25](claude.md#cl-r-25), [MAC-R-08](owner.md#mac-r-08) |
| `perf-final-qualification` | [CL-R-35](claude.md#cl-r-35), [MAC-R-09](owner.md#mac-r-09) |
| `perf-floor-spikes` | [CL-R-05](claude.md#cl-r-05), [CL-R-08](claude.md#cl-r-08), [MAC-R-03](owner.md#mac-r-03) |
| `perf-frontend-durable` | [CL-R-26](claude.md#cl-r-26), [MAC-R-08](owner.md#mac-r-08) |
| `perf-generic-temporaries` | [CL-R-12](claude.md#cl-r-12), [MAC-R-04](owner.md#mac-r-04) |
| `perf-m10-pool-qualification` | [CL-R-14](claude.md#cl-r-14), [MAC-R-04](owner.md#mac-r-04) |
| `perf-m11-acceptance` | [CL-R-09](claude.md#cl-r-09), [CL-R-10](claude.md#cl-r-10), [MAC-R-04](owner.md#mac-r-04) |
| `perf-m8b` | [CL-R-32](claude.md#cl-r-32), [CL-R-34](claude.md#cl-r-34) |
| `perf-m9-arena` | [CL-R-32](claude.md#cl-r-32), [CL-R-34](claude.md#cl-r-34) |
| `perf-mimalloc` | [CL-R-13](claude.md#cl-r-13), [MAC-R-04](owner.md#mac-r-04) |
| `perf-native-link` | [CL-R-28](claude.md#cl-r-28), [MAC-R-08](owner.md#mac-r-08) |
| `perf-native-receipts` | [CL-R-07](claude.md#cl-r-07), [CL-R-08](claude.md#cl-r-08), [MAC-R-03](owner.md#mac-r-03) |
| `perf-nixos-acceptance` | [CL-R-49](claude.md#cl-r-49) |
| `perf-parallel-analysis` | [CL-R-31](claude.md#cl-r-31) |
| `perf-parse-cache` | [CL-R-27](claude.md#cl-r-27), [MAC-R-08](owner.md#mac-r-08) |
| `perf-product-integration` | [CL-R-22](claude.md#cl-r-22), [MAC-R-06](owner.md#mac-r-06) |
| `perf-records-pack` | [CL-R-24](claude.md#cl-r-24), [MAC-R-08](owner.md#mac-r-08) |
| `perf-ref-attribution` | [CL-R-06](claude.md#cl-r-06), [CL-R-08](claude.md#cl-r-08), [MAC-R-03](owner.md#mac-r-03) |
| `perf-ref-cold` | [CL-R-17](claude.md#cl-r-17), [MAC-R-05](owner.md#mac-r-05) |
| `perf-ref-frontend-cache` | [CL-R-15](claude.md#cl-r-15), [MAC-R-05](owner.md#mac-r-05) |
| `perf-ref-stageb` | [CL-R-16](claude.md#cl-r-16), [MAC-R-05](owner.md#mac-r-05) |
| `perf-resident-compiler` | [CL-R-29](claude.md#cl-r-29), [MAC-R-08](owner.md#mac-r-08) |
| `perf-setjmp-barriers` | [CL-R-11](claude.md#cl-r-11), [MAC-R-04](owner.md#mac-r-04) |
| `perf-signing-attest` | [CL-R-07](claude.md#cl-r-07), [CL-R-08](claude.md#cl-r-08), [MAC-R-03](owner.md#mac-r-03) |
| `perf-stageb-skip-unchanged` | [CL-R-04](claude.md#cl-r-04), [CL-R-19](claude.md#cl-r-19), [MAC-R-06](owner.md#mac-r-06) |
| `perf-stageb-slice4` | [CL-R-04](claude.md#cl-r-04), [CL-R-18](claude.md#cl-r-18), [MAC-R-06](owner.md#mac-r-06) |
| `platforms-a1-activity-lifecycle` | [CL-P2-22](claude.md#cl-p2-22), [CX-P2-41](codex.md#cx-p2-41) |
| `platforms-a1-checked-jni` | [CL-P2-08](claude.md#cl-p2-08), [CL-P2-09](claude.md#cl-p2-09), [CL-P2-23](claude.md#cl-p2-23), [CL-P2-24](claude.md#cl-p2-24), [MAC-P2-02](owner.md#mac-p2-02), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-a1-storage-permissions` | [CX-P2-42](codex.md#cx-p2-42) |
| `platforms-a2-aaudio` | [CX-P2-43](codex.md#cx-p2-43), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-a2-gpu` | [CL-P2-28](claude.md#cl-p2-28), [CX-P2-44](codex.md#cx-p2-44), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-a2-packaging-16k` | [CX-P2-45](codex.md#cx-p2-45) |
| `platforms-i1-app-lifecycle` | [CL-P2-22](claude.md#cl-p2-22), [CX-P2-36](codex.md#cx-p2-36) |
| `platforms-i1-objc-protocol-adapters` | [CL-P2-07](claude.md#cl-p2-07), [CL-P2-21](claude.md#cl-p2-21), [MAC-P2-02](owner.md#mac-p2-02), [MAC-P2-04](owner.md#mac-p2-04), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-i1-sandbox-storage` | [CX-P2-37](codex.md#cx-p2-37) |
| `platforms-i2-app-packaging` | [CX-P2-40](codex.md#cx-p2-40), [MAC-P2-04](owner.md#mac-p2-04), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-i2-audio` | [CX-P2-38](codex.md#cx-p2-38), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-i2-gpu` | [CL-P2-28](claude.md#cl-p2-28), [CX-P2-39](codex.md#cx-p2-39), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-interop-function-table-calls` | [CL-P2-05](claude.md#cl-p2-05), [CL-P2-06](claude.md#cl-p2-06) |
| `platforms-p0-adaptations` | [CX-P1-02](codex.md#cx-p1-02) |
| `platforms-p0-entry-baseline` | [MAC-P1-01](owner.md#mac-p1-01) |
| `platforms-p1-abi-fixture` | [CL-P1-13](claude.md#cl-p1-13), [MAC-P1-06](owner.md#mac-p1-06) |
| `platforms-p1-cache-identity` | [CL-P1-15](claude.md#cl-p1-15), [MAC-P1-07](owner.md#mac-p1-07) |
| `platforms-p1-host-android` | [CX-P1-05](codex.md#cx-p1-05), [CX-P1-09](codex.md#cx-p1-09) |
| `platforms-p1-host-ios` | [CX-P1-04](codex.md#cx-p1-04), [CX-P1-08](codex.md#cx-p1-08) |
| `platforms-p1-host-windows` | [CX-P1-06](codex.md#cx-p1-06), [CX-P1-07](codex.md#cx-p1-07) |
| `platforms-p1-hosted-abi-targets` | [CL-P1-07](claude.md#cl-p1-07), [CL-P1-08](claude.md#cl-p1-08), [CL-P1-09](claude.md#cl-p1-09), [MAC-P1-05](owner.md#mac-p1-05) |
| `platforms-p1-native-import-targets` | [CL-P1-10](claude.md#cl-p1-10), [MAC-P1-06](owner.md#mac-p1-06) |
| `platforms-p1-native-plan-toolchain` | [CL-P1-11](claude.md#cl-p1-11), [CL-P1-12](claude.md#cl-p1-12), [MAC-P1-06](owner.md#mac-p1-06) |
| `platforms-p1-provider-filters` | [CL-P1-14](claude.md#cl-p1-14) |
| `platforms-p1-target-spec` | [CL-P1-03](claude.md#cl-p1-03), [CL-P1-04](claude.md#cl-p1-04), [CL-P1-05](claude.md#cl-p1-05), [CL-P1-06](claude.md#cl-p1-06), [MAC-P1-05](owner.md#mac-p1-05) |
| `platforms-p1-toolchains` | [CL-P1-02](claude.md#cl-p1-02) |
| `platforms-p2-ci-lanes` | [CX-P1-07](codex.md#cx-p1-07), [CX-P1-08](codex.md#cx-p1-08), [CX-P1-09](codex.md#cx-p1-09) |
| `platforms-p2-portable-corpus` | [CL-P1-18](claude.md#cl-p1-18), [CL-P1-20](claude.md#cl-p1-20), [CX-P1-10](codex.md#cx-p1-10), [MAC-P1-08](owner.md#mac-p1-08) |
| `platforms-p2-runtime-semantics` | [CL-P1-19](claude.md#cl-p1-19) |
| `platforms-p2-target-probes` | [CL-P1-16](claude.md#cl-p1-16) |
| `platforms-p2-target-runner` | [CL-P1-17](claude.md#cl-p1-17) |
| `platforms-p3-fs-mobile` | [CL-P2-01](claude.md#cl-p2-01), [CX-P2-03](codex.md#cx-p2-03), [CX-P2-14](codex.md#cx-p2-14), [MAC-P2-01](owner.md#mac-p2-01) |
| `platforms-p3-fs-windows` | [CL-P2-01](claude.md#cl-p2-01), [CL-P2-14](claude.md#cl-p2-14), [CL-P2-27](claude.md#cl-p2-27), [CX-P2-01](codex.md#cx-p2-01), [CX-P2-04](codex.md#cx-p2-04), [CX-P2-05](codex.md#cx-p2-05) |
| `platforms-p3-jobs-ipc` | [CL-P2-01](claude.md#cl-p2-01), [CX-P2-01](codex.md#cx-p2-01), [CX-P2-15](codex.md#cx-p2-15), [CX-P2-16](codex.md#cx-p2-16), [MAC-P2-01](owner.md#mac-p2-01) |
| `platforms-p3-process-terminal` | [CL-P2-01](claude.md#cl-p2-01), [CL-P2-27](claude.md#cl-p2-27), [CX-P2-01](codex.md#cx-p2-01), [CX-P2-06](codex.md#cx-p2-06), [CX-P2-07](codex.md#cx-p2-07), [CX-P2-08](codex.md#cx-p2-08), [MAC-P2-01](owner.md#mac-p2-01) |
| `platforms-p3-regex-glob` | [CL-P2-03](claude.md#cl-p2-03), [CX-P2-13](codex.md#cx-p2-13), [MAC-P2-01](owner.md#mac-p2-01) |
| `platforms-p3-sockets-http` | [CL-P2-01](claude.md#cl-p2-01), [CL-P2-04](claude.md#cl-p2-04), [CX-P2-02](codex.md#cx-p2-02), [CX-P2-09](codex.md#cx-p2-09), [CX-P2-10](codex.md#cx-p2-10), [CX-P2-11](codex.md#cx-p2-11), [CX-P2-12](codex.md#cx-p2-12), [MAC-P2-01](owner.md#mac-p2-01) |
| `platforms-p3-windows-launch-seam` | [CL-P2-02](claude.md#cl-p2-02) |
| `platforms-p4-assets-streams-plugins` | [CX-P2-27](codex.md#cx-p2-27), [CX-P2-28](codex.md#cx-p2-28) |
| `platforms-p4-dependency-crossbuild` | [CL-P2-17](claude.md#cl-p2-17), [CX-P2-22](codex.md#cx-p2-22), [CX-P2-23](codex.md#cx-p2-23), [CX-P2-24](codex.md#cx-p2-24), [MAC-P2-03](owner.md#mac-p2-03) |
| `platforms-p4-library-artifacts` | [CL-P2-19](claude.md#cl-p2-19), [CL-P2-20](claude.md#cl-p2-20) |
| `platforms-p4-package-contracts` | [CX-P2-29](codex.md#cx-p2-29), [CX-P2-30](codex.md#cx-p2-30), [MAC-P2-03](owner.md#mac-p2-03) |
| `platforms-w1-ci-and-bundle` | [CL-P2-15](claude.md#cl-p2-15), [CX-P2-18](codex.md#cx-p2-18) |
| `platforms-w1-sdk-reader-provider` | [CL-P2-11](claude.md#cl-p2-11) |
| `platforms-w1-toolchain-abi-route` | [CL-P2-18](claude.md#cl-p2-18), [CX-P2-26](codex.md#cx-p2-26) |
| `platforms-w1-unicode-host` | [CL-P2-14](claude.md#cl-p2-14) |
| `platforms-w1-win32-com-imports` | [CL-P2-10](claude.md#cl-p2-10), [CL-P2-11](claude.md#cl-p2-11), [CX-P2-17](codex.md#cx-p2-17) |
| `platforms-w1-worker-pools` | [CL-P2-12](claude.md#cl-p2-12), [CL-P2-13](claude.md#cl-p2-13) |
| `platforms-w2-arm64` | [CX-P2-31](codex.md#cx-p2-31), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-w2-gpu-image-font` | [CL-P2-28](claude.md#cl-p2-28), [CX-P2-33](codex.md#cx-p2-33), [CX-P2-34](codex.md#cx-p2-34), [MAC-P2-05](owner.md#mac-p2-05) |
| `platforms-w2-packaging` | [CX-P2-35](codex.md#cx-p2-35) |
| `platforms-w2-wasapi` | [CX-P2-32](codex.md#cx-p2-32), [MAC-P2-05](owner.md#mac-p2-05) |
| `qualification-acceptance-hosts` | [CL-R-23](claude.md#cl-r-23), [MAC-R-07](owner.md#mac-r-07) |
| `qualification-catalog-fixtures` | [CX-UIB-08](codex.md#cx-uib-08), [CX-UIB-09](codex.md#cx-uib-09), [CX-UIB-28](codex.md#cx-uib-28), [MAC-UIB-03](owner.md#mac-uib-03) |
| `qualification-ci-android` | [CX-P2-50](codex.md#cx-p2-50) |
| `qualification-ci-btrsmith` | [CL-R-37](claude.md#cl-r-37) |
| `qualification-ci-ios` | [CX-P2-49](codex.md#cx-p2-49), [MAC-P2-05](owner.md#mac-p2-05) |
| `qualification-ci-linux-gui-audio` | [CL-UIA-11](claude.md#cl-uia-11) |
| `qualification-ci-macos-native-suite` | [CL-R-36](claude.md#cl-r-36) |
| `qualification-ci-tiering` | [CL-R-38](claude.md#cl-r-38), [CL-R-39](claude.md#cl-r-39), [CL-R-50](claude.md#cl-r-50) |
| `qualification-ci-windows-matrix` | [CL-P2-18](claude.md#cl-p2-18), [CX-P2-18](codex.md#cx-p2-18) |
| `qualification-final-a2-exit` | [CL-R-45](claude.md#cl-r-45) |
| `qualification-final-i2-exit` | [CL-R-45](claude.md#cl-r-45) |
| `qualification-final-w2-exit` | [CL-R-45](claude.md#cl-r-45) |
| `qualification-p5-journey-catalog` | [CL-UIA-04](claude.md#cl-uia-04) |
| `qualification-p5-journey-drivers` | [CX-UIB-77](codex.md#cx-uib-77), [CX-UIB-78](codex.md#cx-uib-78), [CX-UIB-79](codex.md#cx-uib-79), [CX-UIB-80](codex.md#cx-uib-80), [CX-UIB-81](codex.md#cx-uib-81), [CX-UIB-82](codex.md#cx-uib-82), [MAC-UIB-10](owner.md#mac-uib-10) |
| `qualification-p5-physical-audio-visual` | [CX-R-03](codex.md#cx-r-03), [MAC-R-13](owner.md#mac-r-13) |
| `qualification-p5-runs-android` | [CX-R-10](codex.md#cx-r-10), [MAC-R-11](owner.md#mac-r-11), [MAC-R-12](owner.md#mac-r-12) |
| `qualification-p5-runs-ios` | [CX-R-10](codex.md#cx-r-10), [MAC-R-11](owner.md#mac-r-11), [MAC-R-12](owner.md#mac-r-12) |
| `qualification-p5-runs-macos-linux` | [CX-R-08](codex.md#cx-r-08), [MAC-R-10](owner.md#mac-r-10), [MAC-R-12](owner.md#mac-r-12) |
| `qualification-p5-runs-windows` | [CX-R-09](codex.md#cx-r-09), [MAC-R-12](owner.md#mac-r-12) |
| `qualification-p6-audio-latency-rig` | [CX-R-01](codex.md#cx-r-01), [CX-R-02](codex.md#cx-r-02), [MAC-R-13](owner.md#mac-r-13) |
| `qualification-p6-build-bench-targets` | [CL-R-40](claude.md#cl-r-40), [CX-R-11](codex.md#cx-r-11) |
| `qualification-p6-build-measure` | [MAC-R-12](owner.md#mac-r-12), [MAC-R-14](owner.md#mac-r-14) |
| `qualification-p6-runtime-probes` | [CX-UIB-05](codex.md#cx-uib-05), [CX-UIB-37](codex.md#cx-uib-37), [CX-UIB-38](codex.md#cx-uib-38), [CX-UIB-39](codex.md#cx-uib-39) |
| `qualification-p6-runtime-runs` | [CX-R-12](codex.md#cx-r-12), [MAC-R-12](owner.md#mac-r-12), [MAC-R-14](owner.md#mac-r-14) |
| `qualification-p7-devtools-targets` | [CL-R-43](claude.md#cl-r-43), [CX-R-13](codex.md#cx-r-13), [MAC-R-15](owner.md#mac-r-15) |
| `qualification-p7-install-upgrade` | [CX-R-16](codex.md#cx-r-16), [CX-R-17](codex.md#cx-r-17), [MAC-R-15](owner.md#mac-r-15) |
| `qualification-p7-macos-notarization` | [CX-R-15](codex.md#cx-r-15), [MAC-R-15](owner.md#mac-r-15) |
| `qualification-p7-os-version-matrix` | [CX-R-20](codex.md#cx-r-20), [MAC-R-12](owner.md#mac-r-12), [MAC-R-15](owner.md#mac-r-15) |
| `qualification-p7-release-artifacts` | [CL-R-44](claude.md#cl-r-44), [CX-R-14](codex.md#cx-r-14) |
| `qualification-p7-release-candidate-run` | [CL-R-46](claude.md#cl-r-46), [MAC-R-16](owner.md#mac-r-16) |
| `qualification-p7-sanitizers` | [CL-R-41](claude.md#cl-r-41), [CL-R-42](claude.md#cl-r-42) |
| `qualification-p7-stress-faults` | [CX-R-18](codex.md#cx-r-18), [CX-R-19](codex.md#cx-r-19), [MAC-R-15](owner.md#mac-r-15) |
| `qualification-signing-accounts` | [MAC-P1-04](owner.md#mac-p1-04) |
| `tooling-android-ci-emulator` | [CX-P1-05](codex.md#cx-p1-05) |
| `tooling-android-physical-devices` | [MAC-P1-04](owner.md#mac-p1-04) |
| `tooling-android-sdk-ndk` | [CL-P1-02](claude.md#cl-p1-02), [MAC-P1-03](owner.md#mac-p1-03) |
| `tooling-apple-signing` | [MAC-P1-04](owner.md#mac-p1-04) |
| `tooling-audio-loopback-rig` | [CX-R-01](codex.md#cx-r-01), [CX-R-02](codex.md#cx-r-02), [MAC-R-13](owner.md#mac-r-13) |
| `tooling-cross-gpu-deps` | [CL-P2-29](claude.md#cl-p2-29), [CX-P2-25](codex.md#cx-p2-25) |
| `tooling-ios-physical-devices` | [MAC-P1-04](owner.md#mac-p1-04) |
| `tooling-ios-simulator-runtimes` | [MAC-P1-02](owner.md#mac-p1-02) |
| `tooling-linux-desktop-host` | [MAC-UIA-01](owner.md#mac-uia-01) |
| `tooling-linux-headless-gui` | [CL-UIA-21](claude.md#cl-uia-21) |
| `tooling-release-signing-mobile-store` | [CX-R-15](codex.md#cx-r-15), [MAC-R-15](owner.md#mac-r-15) |
| `tooling-target-debuggers` | [CL-R-43](claude.md#cl-r-43), [CX-R-13](codex.md#cx-r-13) |
| `tooling-windows-ci-arm64-llvm` | [CX-P1-03](codex.md#cx-p1-03) |
| `tooling-windows-physical` | [CX-R-09](codex.md#cx-r-09), [MAC-R-12](owner.md#mac-r-12) |
| `tooling-windows-vm` | [CX-P1-03](codex.md#cx-p1-03) |
| `tooling-x86-acceptance-host` | [CL-R-49](claude.md#cl-r-49), [MAC-R-07](owner.md#mac-r-07) |
| `ui-0-broader-surface` | [CX-UIA-05](codex.md#cx-uia-05) |
| `ui-0-catalog-schema` | [CX-UIA-02](codex.md#cx-uia-02), [CL-UIA-24](claude.md#cl-uia-24) |
| `ui-0-doc-reconcile` | [CX-UIA-07](codex.md#cx-uia-07) |
| `ui-0-focused-gate` | [CL-UIA-02](claude.md#cl-uia-02), [CX-UIA-01](codex.md#cx-uia-01) |
| `ui-0-host-matrix` | [CX-UIA-06](codex.md#cx-uia-06) |
| `ui-0-operation-map` | [CX-UIA-03](codex.md#cx-uia-03), [CX-UIA-04](codex.md#cx-uia-04), [CX-UIA-30](codex.md#cx-uia-30) |
| `ui-0-product-journeys` | [CL-UIA-03](claude.md#cl-uia-03) |
| `ui-1-android-shell` | [CX-UIA-13](codex.md#cx-uia-13), [CX-UIA-17](codex.md#cx-uia-17), [MAC-UIA-03](owner.md#mac-uia-03) |
| `ui-1-feasibility-review` | [CL-UIA-09](claude.md#cl-uia-09), [CL-UIA-10](claude.md#cl-uia-10), [CL-UIA-22](claude.md#cl-uia-22) |
| `ui-1-ios-shell` | [CX-UIA-13](codex.md#cx-uia-13), [CX-UIA-16](codex.md#cx-uia-16), [MAC-UIA-03](owner.md#mac-uia-03) |
| `ui-1-linux-gobject-binding` | [CL-UIA-06](claude.md#cl-uia-06), [CL-UIA-07](claude.md#cl-uia-07), [CL-UIA-08](claude.md#cl-uia-08) |
| `ui-1-linux-gtk-spike` | [CX-UIA-12](codex.md#cx-uia-12), [CX-UIA-14](codex.md#cx-uia-14) |
| `ui-1-linux-sdl-baseline` | [CX-UIA-11](codex.md#cx-uia-11) |
| `ui-1-macos` | [CX-UIA-10](codex.md#cx-uia-10), [MAC-UIA-02](owner.md#mac-uia-02) |
| `ui-1-shell-fixture` | [CX-UIA-09](codex.md#cx-uia-09) |
| `ui-1-windows-shell` | [CX-UIA-13](codex.md#cx-uia-13), [CX-UIA-15](codex.md#cx-uia-15) |
| `ui-10-automation-diagnostics` | [CX-UIB-77](codex.md#cx-uib-77), [CX-UIB-78](codex.md#cx-uib-78), [CX-UIB-79](codex.md#cx-uib-79), [CX-UIB-80](codex.md#cx-uib-80), [CX-UIB-81](codex.md#cx-uib-81), [CX-UIB-82](codex.md#cx-uib-82) |
| `ui-10-btrsmith-mobile` | [CX-UIB-83](codex.md#cx-uib-83), [CX-UIB-84](codex.md#cx-uib-84), [CX-UIB-85](codex.md#cx-uib-85), [MAC-UIB-09](owner.md#mac-uib-09) |
| `ui-10-qualification` | [CL-UIB-16](claude.md#cl-uib-16), [CL-UIB-17](claude.md#cl-uib-17), [CX-UIB-86](codex.md#cx-uib-86), [MAC-UIB-10](owner.md#mac-uib-10), [MAC-UIB-11](owner.md#mac-uib-11) |
| `ui-11-data-docs-help-n58-n60` | [CL-UIB-18](claude.md#cl-uib-18), [CX-UIB-93](codex.md#cx-uib-93), [CX-UIB-94](codex.md#cx-uib-94), [CX-UIB-95](codex.md#cx-uib-95) |
| `ui-11-pickers-n51-n52` | [CL-UIB-18](claude.md#cl-uib-18), [CX-UIB-87](codex.md#cx-uib-87), [CX-UIB-88](codex.md#cx-uib-88), [CX-UIB-95](codex.md#cx-uib-95) |
| `ui-11-print-media-n55-n57` | [CL-UIB-18](claude.md#cl-uib-18), [CX-UIB-91](codex.md#cx-uib-91), [CX-UIB-92](codex.md#cx-uib-92), [CX-UIB-95](codex.md#cx-uib-95) |
| `ui-11-rich-web-n53-n54` | [CL-UIB-18](claude.md#cl-uib-18), [CX-UIB-89](codex.md#cx-uib-89), [CX-UIB-90](codex.md#cx-uib-90), [CX-UIB-95](codex.md#cx-uib-95) |
| `ui-11-tray` | [CX-UIA-28](codex.md#cx-uia-28) |
| `ui-2-btrsmith-subscriptions` | [CL-UIA-15](claude.md#cl-uia-15), [MAC-UIA-04](owner.md#mac-uia-04) |
| `ui-2-contract-control-events` | [CX-UIA-18](codex.md#cx-uia-18), [CX-UIA-21](codex.md#cx-uia-21) |
| `ui-2-contract-executor` | [CX-UIA-19](codex.md#cx-uia-19), [CX-UIA-21](codex.md#cx-uia-21) |
| `ui-2-contract-lifecycle` | [CX-UIA-20](codex.md#cx-uia-20), [CX-UIA-21](codex.md#cx-uia-21) |
| `ui-2-contract-review` | [CL-UIA-13](claude.md#cl-uia-13) |
| `ui-2-linux` | [CL-UIA-23](claude.md#cl-uia-23), [CX-UIA-23](codex.md#cx-uia-23), [CX-UIA-29](codex.md#cx-uia-29) (+ CX-STDLIB-01) |
| `ui-2-macos` | [CX-UIA-22](codex.md#cx-uia-22) |
| `ui-3-contract-input` | [CL-UIA-19](claude.md#cl-uia-19), [CX-UIA-24](codex.md#cx-uia-24), [CX-UIA-25](codex.md#cx-uia-25) |
| `ui-3-linux` | [CL-UIA-23](claude.md#cl-uia-23), [CX-UIA-27](codex.md#cx-uia-27), [CX-UIA-29](codex.md#cx-uia-29), [MAC-UIA-06](owner.md#mac-uia-06) |
| `ui-3-macos` | [CX-UIA-26](codex.md#cx-uia-26), [MAC-UIA-06](owner.md#mac-uia-06) |
| `ui-4` | [MAC-UIB-01](owner.md#mac-uib-01) |
| `ui-4-btrsmith-settings` | [CX-UIB-68](codex.md#cx-uib-68) |
| `ui-4-contract-controls` | [CX-UIB-01](codex.md#cx-uib-01), [CX-UIB-10](codex.md#cx-uib-10), [CX-UIB-11](codex.md#cx-uib-11), [CX-UIB-17](codex.md#cx-uib-17) |
| `ui-4-linux` | [CX-UIB-20](codex.md#cx-uib-20), [CX-UIB-21](codex.md#cx-uib-21) |
| `ui-4-macos` | [CX-UIB-18](codex.md#cx-uib-18), [CX-UIB-19](codex.md#cx-uib-19) (+ CX-STDLIB-03) |
| `ui-5-btrsmith-adaptive` | [CX-UIB-69](codex.md#cx-uib-69), [CX-UIB-70](codex.md#cx-uib-70) |
| `ui-5-contract-layout` | [CX-UIB-02](codex.md#cx-uib-02), [CX-UIB-12](codex.md#cx-uib-12) |
| `ui-5-linux` | [CX-UIB-26](codex.md#cx-uib-26), [CX-UIB-27](codex.md#cx-uib-27) (+ CX-STDLIB-02) |
| `ui-5-macos` | [CX-UIB-25](codex.md#cx-uib-25) |
| `ui-6-btrsmith-library` | [CX-UIB-71](codex.md#cx-uib-71) |
| `ui-6-contract-collections` | [CX-UIB-03](codex.md#cx-uib-03), [CX-UIB-06](codex.md#cx-uib-06), [CX-UIB-14](codex.md#cx-uib-14) |
| `ui-6-linux` | [CX-UIB-30](codex.md#cx-uib-30), [CX-UIB-31](codex.md#cx-uib-31) |
| `ui-6-macos` | [CX-UIB-29](codex.md#cx-uib-29) |
| `ui-6-stress-fixture` | [CX-UIB-08](codex.md#cx-uib-08), [CX-UIB-28](codex.md#cx-uib-28) |
| `ui-7-btrsmith-import` | [CX-UIB-72](codex.md#cx-uib-72) |
| `ui-7-contract-services` | [CX-UIB-04](codex.md#cx-uib-04), [CX-UIB-15](codex.md#cx-uib-15) |
| `ui-7-linux` | [CX-UIB-36](codex.md#cx-uib-36), [MAC-UIB-02](owner.md#mac-uib-02) |
| `ui-7-macos` | [CX-UIB-35](codex.md#cx-uib-35) |
| `ui-8-contract-a11y` | [CX-UIB-02](codex.md#cx-uib-02), [CX-UIB-07](codex.md#cx-uib-07), [CX-UIB-13](codex.md#cx-uib-13) |
| `ui-8-linux` | [CL-UIB-12](claude.md#cl-uib-12), [CX-UIB-23](codex.md#cx-uib-23), [CX-UIB-24](codex.md#cx-uib-24), [MAC-UIB-02](owner.md#mac-uib-02) |
| `ui-8-macos` | [CL-UIB-09](claude.md#cl-uib-09), [CX-UIB-22](codex.md#cx-uib-22), [MAC-UIB-01](owner.md#mac-uib-01) |
| `ui-9-btrsmith-player` | [CX-UIB-73](codex.md#cx-uib-73), [CX-UIB-74](codex.md#cx-uib-74), [MAC-UIB-08](owner.md#mac-uib-08) |
| `ui-9-contract-gpu` | [CX-UIB-05](codex.md#cx-uib-05), [CX-UIB-16](codex.md#cx-uib-16) |
| `ui-9-linux` | [CX-UIB-33](codex.md#cx-uib-33), [CX-UIB-34](codex.md#cx-uib-34) |
| `ui-9-macos` | [CX-UIB-32](codex.md#cx-uib-32) |
| `ui-android-a11y-gpu` | [CL-UIB-11](claude.md#cl-uib-11), [CX-UIB-64](codex.md#cx-uib-64), [CX-UIB-65](codex.md#cx-uib-65), [MAC-UIB-05](owner.md#mac-uib-05) |
| `ui-android-collections-services` | [CL-UIB-11](claude.md#cl-uib-11), [CX-UIB-62](codex.md#cx-uib-62), [CX-UIB-63](codex.md#cx-uib-63) |
| `ui-android-controls-layout` | [CX-UIB-60](codex.md#cx-uib-60), [CX-UIB-61](codex.md#cx-uib-61) |
| `ui-android-core` | [CL-UIB-11](claude.md#cl-uib-11), [CX-UIB-58](codex.md#cx-uib-58), [CX-UIB-59](codex.md#cx-uib-59), [MAC-UIB-05](owner.md#mac-uib-05) |
| `ui-ios-a11y-gpu` | [CL-UIB-09](claude.md#cl-uib-09), [CX-UIB-56](codex.md#cx-uib-56), [CX-UIB-57](codex.md#cx-uib-57), [MAC-UIB-04](owner.md#mac-uib-04) |
| `ui-ios-collections-services` | [CL-UIB-09](claude.md#cl-uib-09), [CX-UIB-54](codex.md#cx-uib-54), [CX-UIB-55](codex.md#cx-uib-55) |
| `ui-ios-controls-layout` | [CX-UIB-52](codex.md#cx-uib-52), [CX-UIB-53](codex.md#cx-uib-53) |
| `ui-ios-core` | [CX-UIB-50](codex.md#cx-uib-50), [CX-UIB-51](codex.md#cx-uib-51), [MAC-UIB-04](owner.md#mac-uib-04) |
| `ui-win-a11y-gpu` | [CL-UIB-10](claude.md#cl-uib-10), [CX-UIB-48](codex.md#cx-uib-48), [CX-UIB-49](codex.md#cx-uib-49), [MAC-UIB-06](owner.md#mac-uib-06) |
| `ui-win-collections-services` | [CL-UIB-10](claude.md#cl-uib-10), [CX-UIB-46](codex.md#cx-uib-46), [CX-UIB-47](codex.md#cx-uib-47) |
| `ui-win-controls-layout` | [CX-UIB-44](codex.md#cx-uib-44), [CX-UIB-45](codex.md#cx-uib-45) |
| `ui-win-core` | [CX-UIB-42](codex.md#cx-uib-42), [CX-UIB-43](codex.md#cx-uib-43), [MAC-UIB-06](owner.md#mac-uib-06) |

### Appendix C. Analyst scope notes (verbatim)

Each planning analyst's summary, kept for context: the GUI inventory, the platform verification split, and the reasoning behind each scope's packets. **Where a note disagrees with §2 (D27) or §3 (protocol), §2 and §3 win.**

#### Group C: Bucket 2 remainder: Stage 16 (ccompat-c1-integrate, C4 r18), 17 (C2), 18, 19 (C3), 20 (goto), 21 (C5 close-out)

Bucket 2 remainder (Stages 16-21) is split into 41 Claude packets (CL-C-00..40), 9 owner-Mac checkpoints (MAC-C-01..09) and 3 small Codex packets (CX-C-01..03). Every PLAN item in Stages 16-21 is covered. A large item is split across consecutive packets, and each packet names the part it covers.

**Why Codex gets so little here.** Bucket 2 is compiler work by definition: every construct changes both compilers in one commit (the parity rule), so all of it is Claude's. Codex only gets work that never changes compiler behavior:
- CX-C-01: a one-command script for the Mac checkpoints.
- CX-C-02 and CX-C-03: optional formatter and LSP fuzz passes after C2/r17 and after C3/goto. None of the three blocks the C track.

**What can start now on main 8b73c79:**
- CL-C-00: doc-only reconciliation. c-vocabulary-specifiers.md reserves `GotoStmt(name)`/`LabeledStmt(name, body, …)` and puts `goto` in its pending-refusal tables. c-goto-labels.md instead specifies `GotoStmt(name, name_line, name_col)`/`LabelStmt(name)` and no interim message. The two documents also disagree on who owns D-13 and D-7. This must land before the C3 vocabulary commit, or Stage 20 would need a second schema commit.
- CL-C-02: the btrc lambda-termination parity fix (D-13). It is a pre-existing parity defect that both designs want landed first, not a C construct.
- CX-C-01.
- CL-C-01 (ccompat-c1-integrate) is already in flight.

**Critical path:** CL-C-01 → CL-C-03 ∥ CL-C-04 → CL-C-05 → CL-C-06 (C4) → CL-C-07 (C2 schema) → CL-C-08 (shared owners) → L1 09→10→11→12 ∥ L2 13→14→15 → CL-C-16 → CL-C-17 → CL-C-18 → CL-C-19 → CL-C-20 ∥ CL-C-21 → CL-C-22 → CL-C-23 (C3 vocabulary) → 24 → 25 → 26 → wave 27/28/29/30→31, then 32 ∥ 33 → goto 35→36 (34 prepares earlier) → CL-C-37 → CL-C-38 ∥ CL-C-39 → CL-C-40 → MAC-C-09.

CL-C-03 (the `targets.toml` spec) also gates bucket 3's Stage 24. That makes it the first dependency for every iOS, Android and Windows UI lane, so it should run as early as D18 allows.

**Scheduling choices that differ from the design docs** (recorded in CL-C-00 and in the open questions):
- The C2 schema waits for the C4 behavior commit. This follows D18, and the two share hotspots: `ir/nodes.py`, `ir/Model.btrc`, `ir/Emitter.btrc`, `backend/c_emitter.py`, `grammar.ebnf` and the ModuleUnits pair.
- C3 commit B is split into B1 (target widths, typed evaluator, constant lowering) and B2 (layout model, `sizeof` operands, cross-check asserts, `#pragma pack` move). One D5 gate runs after B2.
- r10 is split into designators, then compound literals.
- goto runs after r15a and r14, because both edit flow, ownership and setjmp code, which the goto design forbids sibling lanes to touch. r11 therefore still merges last, into c3-integrate.

**Platform split:**
- **GitHub macOS runner** (`macos.yml`: unit/btrc/corpus/bootstrap shards plus clang C11 at O0/O2): packets that touch native import, Objective-C, Darwin layout, TLS or setjmp: 09, 13, 14, 15, 17, 22, 26, 27, 29, 32, 35.
- **All three workflows** (`ci.yml`, `macos.yml`, `windows.yml`), for packets whose behavior depends on the target or host: 06, 16, 25, 30, 33, 36. `windows.yml` gives the native Windows bootstrap and VSIX packaging; Linux supplies the cross-target transpiles.
- **Owner Mac**, only for:
  - BTRSmith `application-frontend-check` and the library smoke (BTRSmith is private and macOS-only);
  - the 8-cell Darwin `test-c11`;
  - BTRSmith `--jobs 1` instructions-retired and peak-footprint rows;
  - C4's quiet M11 re-measure;
  - the BTRSmith pin bump.

  Each checkpoint is one command, through CX-C-01's script or, as a fallback, `tools/bench/scripts/batch_gate.sh` and `instr.sh`.

**D27 as seen from bucket 2** (other scopes name the specific UI items):
- **What may start now.** Codex may start any UI or stdlib-provider work that needs no compiler or spec change and no C2, C3 or C4 construct.
- **Forward-compatibility rules,** so the C lanes cannot break that work:
  - no `#if`, `#ifdef` or `#undef` in `src/stdlib` until CL-C-06 lands; after that, only conditions valid for every target and never `#undef`;
  - no struct members spelled `T[] name`, which r13 will refuse (write `T* name`);
  - no `volatile T*`, whose meaning r15a flips;
  - import every btrc type spelled `struct X`, `union X` or `enum X`, because r09 counts tags for strict imports;
  - no identifiers that C3 reserves (`va_arg`, `inline`, `restrict`, `_Alignas`, …).
- **How the two agents stay apart:**
  - Claude C lanes do not edit `src/stdlib/{GUI,UI,App,Tray}`. A required change there goes through the integrator.
  - Codex stdlib PRs are re-gated after each batch that changes semantics visible to the stdlib: C4, r09, r13, the C3 vocabulary commit and r15a.
- **What stays gated:**
  - platform selection by `#if` in the stdlib, until CL-C-06;
  - iOS, Android and Windows target rows, until CL-C-03 and then bucket 3's Stage 24;
  - any use of unions, bit-fields, designators, compound literals, 2-D arrays, `_Alignas`, `_Static_assert`, wide literals or variadic definitions, until the packet that adds it merges.

#### Group P1: Bucket 3 first half: Stages 22 (what remains), 23 (P1 provisioning), 24 (P1 target contract), 25 (P1 test hosts, P2 runtime parity)

Scope: the first half of bucket 3, which is Stage 22 (the items still open), Stage 23 (P1 provisioning), Stage 24 (P1 target contract) and Stage 25 (P1 test hosts and P2 runtime parity). I read PLAN.md, platform-target-contract.md, platform-parity.md, platform-toolchain-matrix.md, platform-adaptations.md, devices.toml, the C4 design and the tree at 8b73c79.

What is already done and needs no packet:
- Stage 22's platforms-p0-inventory, matrix-pin, toolchain-matrix and device-lab items.
- The Stage 24 design, which is written and approved.

What is still open in Stage 22: the entry gate, btrsmith-p0-inventory, the adaptation sign-off, and D6's amendment to the ordering text.

There are 38 packets:
- **Claude, 20 packets, about 159 agent-hours.** This covers the D6/D27 docs, the nix platforms shell, all of Stage 24 (4 sub-batches, 13 packets) and the Stage 25 compiler, runtime and runner work: the target probes, the runner core, triage, runtime semantics and compiler fixes.
- **Codex, 10 packets, about 83 agent-hours.** This covers the BTRSmith P0 inventory, finishing the adaptations, the Windows ARM64 runner job, and the three test-host lanes. Each lane is a spike now and an integration plus CI lane later, and each owns tools/target_hosts/\<platform>/ and its own workflow file. It also covers the stdlib fixes outside the compiler's import closure.
- **Owner Mac, 8 packets, about 26 agent-hours.** Each step is prepared as one command: the entry gate, the iOS runtimes, the Android AVDs, signing and device records, the Apple extractions, the Stage 24 Mac evidence, the quiet re-measure, and the device-queue corpus runs.

Why Codex gets these packets: the Codex packets touch no compiler, spec, generator, runtime or generated file. The iOS and Android test-host apps built here (a NativeActivity APK and a simulator app bundle) are the same vehicles that UI1's iOS and Android shells will reuse. That fits the owner's idea of Codex owning per-platform GUI work later.

**Proposed D27, as it applies to this scope.**
- Codex works only on codex/\<packet-id> branches. It opens draft PRs to main only to get CI. Claude integrates codex branches into main-kn9jxh in gated batches, and the parity rule is unchanged.
- D1's bucket order still governs compiler work and every gate.
- A packet may start before its bucket only when both of these hold:
  - its dependencies are met on main, or it is planning or spike work;
  - it touches no compiler source, shared spec, generator, runtime asset, generated file, or hotspot held by an in-flight lane.
- Allowed now:
  - CL-P1-01 (docs);
  - CL-P1-02 (Stage 23 provisioning; PLAN already allows provisioning during bucket 2);
  - CX-P1-01, CX-P1-02 and CX-P1-03;
  - CX-P1-04, CX-P1-05 and CX-P1-06: host spikes with hand-written C11 fixtures on GitHub runners, which platform-parity P1 asks for early ('package and execute the first minimal test apps early');
  - MAC-P1-01 and MAC-P1-02, at the owner's next Mac session. D27 also makes the 'bucket-order call' the entry gate was waiting on: the baseline is taken on the current main.
- Stays gated:
  - **All of Stage 24.** src/language/targets.toml does not exist on 8b73c79. C4's ccompat-r18-spec creates it, and C4's evaluator lane must land before commits 1c and 1d. D18 puts C4 after ccompat-c1-integrate.
  - **All of Stage 25's integration work:** the probes, the runner core, the host integrations, the CI lanes, triage and fixes. These need Stage 24 sub-batch 1, and the runner needs sub-batch 3.
  - **Every native UI provider.** The bucket-4 groups set that part of D27.

**Critical path.**
- C4 spec, then CL-P1-03, 04, 05 and 06 (sub-batch 1 gate).
- Then CL-P1-07 together with MAC-P1-05 (Apple extraction), then CL-P1-08 and 09 (sub-batch 2 gate).
- Then CL-P1-10, 11, 12 and 13 in parallel, with at most 4 writers (PLAN Stage 24).
- Then CL-P1-14 and 15, the full-matrix gate, and MAC-P1-07's quiet re-measure.
- Stage 25: CL-P1-16 and CL-P1-17, then CX-P1-07, 08 and 09 (CI lanes), then CL-P1-18 triage, then CL-P1-19 and 20 and CX-P1-10 fix waves, then MAC-P1-08 and the exit record.

**Where verification runs.**
- **GitHub runners:**
  - windows-latest (Windows Server 2025) is a stand-in for windows-x64;
  - windows-11-arm is real windows-arm64 evidence, but its availability is unverified (⚠);
  - macos-15 runs the iOS simulator with a runner Xcode, not the pinned 27A266a, so it is a stand-in;
  - ubuntu-latest with KVM runs the android-x86_64 emulator, which is real slice evidence.
- **The owner's Mac:**
  - the pinned-Xcode iOS simulators, including the iOS 17 runtime;
  - the arm64-v8a emulators at API 29, 36 and 36 with 16 KiB pages;
  - Apple SDK extractions and the Apple clang macro checks;
  - BTRSmith checks and object comparisons;
  - the quiet M11 re-measure;
  - signing and device records.
- **Physical devices** stay unavailable under D8.

**Shared files have a single writer.** Expected-skip manifests, the boundary manifest, btrc.toml manifest edits, platform-toolchain-matrix.md and devices.toml evidence rows, and PLAN.md are changed only by Claude at integration. Codex packets put their changes to these files in the PR body as fragments.

#### Group P2: Bucket 3 second half: Stages 26 (P3 OS services), 27 (W1 Windows + interop lane I), 28 (P4 dependencies, library artifacts), 29 (non-UI platform tracks, interop lane II)

Scope: bucket 3 second half, Stages 26 (P3 OS services), 27 (W1 + interop lane I), 28 (P4 dependencies and library artifacts) and 29 (W2/I1/I2/A1/A2 non-UI tracks + interop lane II). The roadmap item descriptions in /home/user/btrsmith-state/roadmap/items.json (deps, touches, exits) were read alongside PLAN.md, platform-parity.md, platform-adaptations.md, platform-target-contract.md, platform-toolchain-matrix.md and native-interop-ownership.md. The result is 81 packets: 26 Claude (CL-P2), 50 Codex (CX-P2) and 5 owner-Mac (MAC-P2).

How items are cited: an item that one packet carries whole is cited by its bare id. An item split across packets is cited as item[part], and the parts partition the item. Every Stage 26–29 item appears exactly once, either bare or through its parts. Two items run as one unit: platforms-p4-dependency-crossbuild and btrsmith-package-closure share their parts.

Who does what:
- **Claude.** Claude keeps the whole interop lane, run serially:
  - schema v2 (CL-P2-05);
  - function tables (CL-P2-06);
  - the Objective-C slice (CL-P2-07);
  - the Java reader with schema v4 (CL-P2-08);
  - JNI calls (CL-P2-09);
  - COM (CL-P2-10);
  - Objective-C instantiated adapters (CL-P2-21);
  - JavaClassReader v2 (CL-P2-23);
  - JNI entry and callbacks (CL-P2-24).
- **Claude, Windows compiler host.** The runtime/c Windows launch seam with its D14 re-capture (CL-P2-02), the SDK reader (CL-P2-11), worker pools (CL-P2-12/13), the Unicode host plus compat-shim retirement (CL-P2-14), the bundle with native-plan realization and debug mapping (CL-P2-15), and the W1 close-out (CL-P2-18).
- **Claude, everything else.**
  - Shared-file deltas: hosted ABI (CL-P2-03), flake inputs (CL-P2-04) and the Stage 28 lock merges (CL-P2-17).
  - Link-plan schema 6 and the library builder (CL-P2-19/20).
  - BTRSmith's serial abstractions: Config.mk (CL-P2-16), storage tokens (CL-P2-25) and audio policy (CL-P2-26).
  - Contract reviews (CL-P2-01) and the UI2 lifecycle-shape check (CL-P2-22).
- **Codex.**
  - Every stdlib OS-service provider: Windows FileSystem, Process, Terminal, Daemon, LocalApplicationChannel and BackgroundJobs, the HTTP transports, the regex engine, and mobile storage.
  - Every W2/I1/I2/A1/A2 non-UI provider and lifecycle owner: Audio, GPU, Image/Font, and the App/GUI lifecycle-only files.
  - Packaging: MSIX, Xcode and Gradle with the 16 KiB checks.
  - Dependency cross-builds, wgpu-native archives and package-contract runs.
  - BTRSmith per-target shells, fixtures and ports.
  - The COM fixture server.
  - The new Windows, iOS and Android CI workflows.

**Compiler imports.** FileSystem, Process, IO and BackgroundJobs are stdlib modules the compiler imports. They stay with Codex under one hard rule: such a packet builds its own btrcc and passes three checks:
- `make bootstrap`;
- zero-warning transpiles of BtrccMain, cli/WindowsMain and cli/MacOSMain;
- the Windows native bootstrap step.

Linux and macOS emitted C must not change.

**Protocol additions.** Every Codex packet follows these rules:
- **Fragments.** btrc.toml changes go in an isolated 'fragment:' commit.
- **Derived files.** Any regenerated btrc.symbols, btrc.lock or LSP catalog goes in an isolated 'derived:' commit, which Claude drops and regenerates at integration.
- **Skip ledger.** Rules travel as fragments.
- **Inventory.** A packet edits only its own operations' cells in platform-inventory.toml.
- **Hotspots.** Codex never edits windows.yml, macos.yml, ci.yml, the Makefile, conftest.py, native_plan.py, flake.nix or the runtime manifest. Each needed change is filed as a Claude request.

**Readiness on 8b73c79.** Nothing in Stages 26–29 is implementable yet, for three reasons:
- Stage 24 implementation waits for C4's targets.toml.
- Stage 25 (test hosts, target probes, target runner, CI lanes) has not started.
- items.json makes even interop step 1 depend on Stage 24 sub-batch 3 (platforms-p1-native-import-targets, platforms-p1-abi-fixture).

**Critical paths.**
- C4 → Stage 24 sub-batches 1–3 → CL-P2-05 → 06 → 07 → 08 → 09 → 10 (COM) → 21 (UIKit adapters) → 24 (JNI entry).
- Stage 25 → CL-P2-02 → CL-P2-11/12/14/15 → CL-P2-18 (W1 close).

Codex fans out behind Stage 24 sub-batch 4 (provider filters and the platform-directory rule) and the matching Stage 25 hosts. Its WASAPI and WIC work also waits for COM, the iOS lifecycle and audio for CL-P2-21, and the Android Activity work for CL-P2-24.

**Proposed D27 clause for Stages 26–29.** Codex may start now only:
- CX-P2-01: the Windows OS-services design;
- CX-P2-02: the HTTP transport contract;
- CX-P2-03: the mobile storage contract.

All three are docs-only draft PRs on codex/ branches, approved through CL-P2-01 under the standing design-approval rule. Everything else stays gated by its Stage 23/24/25 or interop dependency, and no Windows, iOS or Android provider code merges before Stage 24 sub-batch 4.

For the UI half of D27:
- ui-1-windows-shell cannot start before CL-P2-10 (COM).
- ui-1-ios-shell cannot start before CL-P2-21 (UIKit adapters).
- ui-1-android-shell cannot start before CL-P2-24 (JNI entry).
- The I1/A1 lifecycle owners (CX-P2-36/41) must pass CL-P2-22's UI2-shape check.

Early UI work is therefore limited to the macOS and Linux providers plus read-only UI0/UI2 drafting.

**Where verification runs.**
- **Windows:** GitHub windows-latest through draft-PR runs and `gh workflow run --ref`. windows-11-arm is added once Stage 23 proves access.
- **macOS:** macos.yml.
- **iOS simulator, development evidence:** GitHub macOS runners, using the runner's own Xcode.
- **iOS acceptance on pinned Xcode 27A266a:** batched into MAC-P2-01..04.
- **Android emulator:** GitHub ubuntu KVM runners (Stage 25's tooling-android-ci-emulator) for x86_64 API 29/36 images at 4 and 16 KiB. The arm64 16 KiB image runs on the Mac (MAC-P2-02).
- **Physical evidence:** devices, audio endpoints, GPUs, signing and distribution are recorded as unavailable under D8 in MAC-P2-05.

#### Group UIA: Bucket 4 first half: Stages 30 (UI0 catalog/journeys/evidence hosts), 31 (UI1 shells on five platforms + toolkit decision incl. the D23 GTK4 spike), 32 (UI2 contracts + Library.UI split), 33 (UI3 input/focus/commands + tray). Also inventory the current src/stdlib/GUI, UI, Tray and App trees (portable contracts, MacOS and Linux providers) and say what each platform has and lacks.

Scope: PLAN Stages 30-33 (UI0 catalog, journeys and hosts; UI1 shells and the D23 GTK4 spike; UI2 contracts and the Library.UI split; UI3 input and the tray). That is 31 PLAN items, with the ui-0-product-journeys/btrsmith-ui0-callers pair counted once, split into 54 packets: 20 CL, 28 CX and 6 MAC. A PLAN item split across packets is cited by its bare id in its main packet and as 'id#part' in the others.

ANSWER TO THE OWNER'S 'SAME DOC?' QUESTION. Keep one plan. PLAN.md stays the roadmap. Its new D27 row and a 'Work packets' table using these CL-/CX-/MAC- ids say who does what. AGENTS.md gets a short Codex section; Codex reads that file natively, and CLAUDE.md is a symlink to it. Each packet's evidence goes in its draft-PR body. Both agents run in the cloud. macOS and Windows proof comes from GitHub runners on Codex's draft PRs. Anything that needs the owner's Mac, devices or decisions is a MAC- packet reduced to one command.

PROPOSED D27: Codex as a second builder, and which UI work may start early.

(a) Starts now. Dependencies are met on 8b73c79, or the work is planning or a spike:
- coordination and CI support: CL-UIA-01 and CL-UIA-02;
- read-only BTRSmith caller mapping: CL-UIA-03;
- UI0 writers: CX-UIA-01 (focused gate), 02 (catalog and drift test), 06 (host matrix) and 08 (Linux headless Wayland/X11/GTK4/AT-SPI tooling). CX-UIA-03/04/05/07 follow as soon as 02 lands;
- the shell fixture and harness on the two existing providers: CX-UIA-09. 10 (macOS) and 11 (Linux SDL) follow it, with the E40 reproduction kept on a branch per D24;
- spikes that merge only documents: CX-UIA-12 (a plain-C GTK4/WebGPU interop pre-spike) and CX-UIA-13 (Win32, UIKit and Android shell design notes);
- docs-only predrafts of the three UI2 contracts: CX-UIA-18/19/20. They are reviewed only against real UI1 results.

(b) May start as soon as their own in-stage dependencies land, without waiting for buckets 2-3 to close: the macOS and Linux-SDL halves of Stages 31-33 and the tray. They touch no compiler, and D23 scopes GTK4 to UI4-UI8.

(c) Stays gated:
- Any edit to a portable contract (GUI/I\*.btrc, GUI.btrc, App.btrc, the Tray model) waits for its UI2 or UI3 standing approval, then lands atomically with both providers.
- Every compiler, spec or runtime change stays with Claude under D1/D18. Codex files a 'compiler request' instead. This covers the GObject binding (Stage 27 step 8, which comes after steps 1-2), so the btrc-hosted GTK4 spike and the D23 decision follow the bucket-3 interop lane.
- The Windows, iOS and Android shells wait for their Stage 23-29 prerequisites.
- BTRSmith migration waits for the UI2 landing and a pin bump.
- Mac and device evidence and owner decisions are unchanged.
- At most two Codex branches go into each Claude integration batch, and they never displace a C-track or schema batch. Claude's bucket order is unchanged.

INVENTORY AT 8b73c79.

Portable contracts:
- 20 GUI/I\*.btrc files, 25 interfaces, 152 interface methods, plus 26 GUI facade methods: 178 declarations. PLAN's exit text still quotes the frozen 19/24/162 counts. D035 added 15 IApplication factories, D056 removed GUI.rasterText, and D068 renamed FontFace.btrc to IFontFace.btrc.
- Other GUI modules: ActionMailbox, ApplicationSlot, Font/FreeType, GUICaptureLayer, GUIInt, TextRun, and Raster (legacy per D24).
- Missing from the contracts: edit/commit/change events, a keyed ISelect (it is index-only), ISlider range updates, two-axis scrolling, worker-safe post, a close veto, a focus/command API, scene restoration, effective visibility, and any accessibility attachment.

App: pointer, scroll (with phases) and key values, and an AppKeyCode with 27 named values plus unknown. There is no touch or pen input, no IME/text-edit event, no split between physical and layout keys, and no PageUp/Down or F-keys.

UI: a custom retained renderer (Element 1,102 lines, Render 2,905) with semantics, focus, text editing, a virtual grid and a proof raster. It has no presentation host and no OS accessibility bridge.

Tray: SystemTray, ITray and TrayModel, with shell-string commands run synchronously through Library.Process. There are no typed commands, notifications or badges.

macOS provider (33 files):
- Has real AppKit controls for all 15 factories, NSStackView/NSGridView layout, a CAMetalLayer WebGPU child, composed capture, CoreText raster text, a synchronous runModal folder picker, NSTimer delayed work, and a run-loop signal with a 256-entry ordered action queue. The tray uses NSStatusItem/NSMenu.
- Lacks a close veto (windowShouldClose always returns true), any NSAccessibility use, scoped control events, worker wakeup, and bordered fonts above 20 pt.

Linux provider (28 files):
- Uses SDL3 windows, each one WebGPU surface, with every control custom-painted by LinuxPainter and fontconfig/FreeType text. It has an overlay select, SDL message boxes, a portal/zenity folder dialog pumped modally, offscreen-composited GPU views, and whole-window capture that ignores the supplied layers.
- CI runs it under Xvfb with lavapipe and SDL pinned to X11. Nix provides no Wayland compositor, GTK4 or AT-SPI.
- Lacks native widgets, AT-SPI, IME preedit, text undo, keyboard handling on button/slider/scroll, exposure tracking, and recoverable presentation failure. pumpEvents drops the 4,097th event (E40).
- The tray uses StatusNotifierItem and DBusMenu over libdbus. It is tested only through the reference frontend, and that test skips in CI because no watcher is running.

Windows, iOS and Android have nothing:
- GUI/btrc.toml selects only the macOS and Linux providers.
- The tray fails at provider selection on Windows.
- Neither compiler has an iOS or Android target until Stage 24.

Tests: 27 native GUI .btrc fixtures plus Objective-C probes, 3 Linux fixtures, and TrayNative. Hosted macOS runners have no GPU adapter, so GPU-child evidence needs the owner's Mac.

CRITICAL PATHS.
- UI0: CX-02 -> CX-03/04/05 -> CX-07 -> CL-05.
- UI1-UI3 on macOS and Linux, with no bucket-3 dependency: CX-09 -> CX-10/11 -> CL-09 -> CL-13 -> CX-21 -> CX-22/23 -> CL-14 -> CX-24 -> CL-19 -> CX-25 -> CX-26/27 -> CL-20 -> CX-28.
- D23 (bound to bucket 3): Stage 27 steps 1-2 -> CL-06 -> CL-07 -> CL-08 -> CX-14 -> CL-10.
- The Windows and mobile shells wait on Stages 23-29.

All paths are relative to /home/user/btrc.

#### Group UIB: Bucket 4 second half: Stages 34 (UI4-UI9 contract packet + macOS/Linux reference providers), 35 (Windows, iOS, Android UI tracks), 36 (BTRSmith screen migration slices), 37 (UI10 automation, mobile restoration, UI11 long tail). Also docs/design/native-ui-parity.md and native-ui-api-inventory.md.

SCOPE: PLAN Stages 34–37 (the second half of bucket 4), plus docs/design/native-ui-parity.md and docs/design/native-ui-api-inventory.md.

STATE ON main 8b73c79: nothing in bucket 4 has started.
- Stages 30–33 are all open: UI0 catalog and journeys, UI1 shells and the D23 toolkit decision, the UI2 contract, and the UI3 contract plus its landing.
- The bucket-3 prerequisites for the new platforms are also open: Stage 24 targets, Stage 25 hosts, Stage 26 P3 scoped resources, Stage 27 W1/COM, and Stage 29 I1 Objective-C subclassing, A1 JNI and W2/I2/A2 GPU and packaging.
- So every implementation packet below is blocked. Only what the proposed D27 allows can start now:
  - CL-UIB-01: record D27.
  - CX-UIB-01..05: contract pre-drafts.
  - CX-UIB-06..07: spikes.
  - CX-UIB-08..09: the catalog-fixture generators, which depend only on the Stage 2 ledger.
  - CL-UIB-13: the request queue.

PROPOSED D27 (recorded once by CL-UIB-01): Codex is a second builder agent; some UI work starts early.
- Ownership.
  - Codex owns:
    - src/stdlib/{GUI,UI,App,Tray}: contracts and providers;
    - the BTRSmith UI slices;
    - UI fixtures, harnesses and journey drivers (tools/ui_evidence/);
    - the native-ui docs.
  - Codex is D6(c)'s single UI contract owner:
    - one writer chain for IView, IWindow and App.btrc (CX-UIB-12 → CX-UIB-13);
    - one reconciler for GUI.btrc/IApplication.btrc factories and the docs (CX-UIB-17).
  - Claude owns:
    - both compilers, the shared specs and generators;
    - the interop work (Objective-C, COM, JNI, GObject) and the native reader;
    - the hotspots: flake.nix/nix, the Makefile, conftest.py, runner_capabilities.py, the workflows and tools/qualification;
    - integration, gates, pushes and PLAN.md;
    - contract approval: its own two adversarial reviewers plus a parity reviewer, under the standing approval rule.
- Allowed now, before buckets 2–3 finish:
  - (a) Planning. UI4–UI9 contract pre-drafts and five-platform API maps go in docs/design/native-ui-contracts/, marked 'draft, not approved'. They land as docs-only commits. This is Stage 33's pre-draft step, moved earlier.
  - (b) Spikes. They go on codex/\* branches, are never merged, and land only a findings note.
  - (c) Stage 34 items whose recorded dependencies are already met: only the data generators of the qualification-catalog-fixtures pair.
- Still gated:
  - Any edit to GUI/UI/App/Tray interfaces, providers or btrc.toml beyond (c).
  - The new provider directories (Stage 31).
  - Any contract approval before Stage 33's UI3 landing. Approval is also re-checked against the five Stage 31 shells.
  - Provider work before its contract is approved and Stages 31–33 have landed.
  - The Windows, iOS and Android tracks before their Stage 24/25/27/29 prerequisites.
  - The BTRSmith slices before their btrc landing.
- D1 is otherwise unchanged. No bucket-4 work displaces a bucket 1–3 gate, a quiet window or the Mac's queues. Codex never edits compiler sources or shared specs.

STAGE 34 SHAPE:
- One contract packet: drafters CX-UIB-10, 11, 14, 15 and 16; the IView/IWindow chain CX-UIB-12 then CX-UIB-13; the reconciler CX-UIB-17.
- Claude reviews and approves it (CL-UIB-02).
- Then four atomic landings, each with a gate:
  - L1 = UI4 controls plus the UI8 bridge cores (CL-UIB-05);
  - L2 = UI5 (CL-UIB-06);
  - L3 = UI6, the UI9 cores, the 100k stress fixture and Linux GPU-children accessibility (CL-UIB-07);
  - L4 = UI7, the probes and the Stage 34 close (CL-UIB-08).
- Every provider packet carries the UI8 rows for its families (names, roles, states, actions, focus, keyboard-only journeys) and their UI9 rows.
- VoiceOver and Orca journeys, real-GPU runs and idle-CPU measurements are owner steps: MAC-UIB-01, 02 and 03.

STAGES 35–37:
- Stage 35 (CX-UIB-42..65): three tracks, one landing behind Stage 34. Each item is split in two, and one track at a time owns each provider directory. Claude supplies the interop each track needs (CL-UIB-09..12) and lands the tracks (CL-UIB-14).
- Stage 36 (CX-UIB-66..76): the BTRSmith slices follow their btrc landing. Claude merges and bumps pins (CL-UIB-15); the owner's Mac carries the macOS evidence (MAC-UIB-07, 08).
- Stage 37: journey drivers (CX-UIB-77..82), mobile restoration (CX-UIB-83..85), UI10 aggregation (CX-UIB-86), the availability model (CL-UIB-16) and the final gate (CL-UIB-17). UI11 is CX-UIB-87..94.

CONVENTIONS FOR EVERY CX PACKET:
- Branch: codex/\<packet-id-lowercase>. A draft PR against main exists only to get ci.yml, macos.yml and windows.yml runs. Codex never merges.
- Derived files: the btrc.toml fragments, the btrc.lock re-resolved with `btrcpy --fetch`, btrc.symbols and src/devex/lsp/catalog/generated.py go only in one final commit titled 'derived: …'. The integrator drops that commit and regenerates the files.
- Tests:
  - parametrized frontend ∈ {python, selfhost} × sanitized ∈ {False, True};
  - pinned to the integrator's btrcc with BTRC_TEST_BTRCC. GUI, UI, App, Tray and Realtime are not compiler imports, so a lane runs no bootstrap;
  - zero analyzer warnings in new fixtures.
- Hardware-tier cases get expected-skip rules for their own files in src/tests/fixtures/expected-skips/\*.json.
- Ledger/catalog rows are written per family and E-case, per provider × frontend, in the Stage 30 UI0 catalog layout.
- Compiler needs are filed as REQUEST(CL-UIB-13), or to the matching interop packet, with a minimal repro.
- The PR body report lists: commits, tests with pass/skip counts, CI run ids, catalog rows, fragments and deferrals.

VERIFICATION SURFACES:
- Linux cloud: the Linux provider under tools/virtual-display.sh (Xvfb plus lavapipe; Wayland after Stage 30).
- GitHub macos.yml (macos-15): AppKit fixtures, plus the iOS simulator after Stage 29. It has no real GPU adapter and no VoiceOver, and AX trust is unproven (CX-UIB-07 settles it).
- GitHub windows.yml (windows-latest, windows-11-arm): Win32 fixtures and UIA client tests. devices.toml counts these runners as stand-ins, not physical evidence.
- ci.yml Android emulator job (Stage 25).
- Owner Mac: screen readers, real GPU, measurements, BTRSmith macOS checks, the Linux desktop host, devices (all awaiting hardware per D8) and the bucket-exit gate.

PACKET COUNTS: 17 Claude, 94 Codex, 10 owner.

CRITICAL PATH: Stage 33 UI3 landing → CX-UIB-10..17 → CL-UIB-02 → L1..L4. Stage 35 also waits on the Stage 31 shells and on Stage 27/29 interop.

#### Group R: Bucket 5 (Stages 38-43: CI tiers, journeys, physical sessions, P6 numeric acceptance, P7 release engineering, final exits) AND the Mac-bound remainder of bucket 1 (Stages 5-13) and the Stage 4 BTRSmith pin bump/requalification: classify every item, and make the owner_mac packets one-command runbooks where possible.

Scope: the Stage 4 BTRSmith pin bump and requalification, the rest of bucket 1 (Stages 5-13), and bucket 5 (Stages 38-43). There are 85 packets: 47 for Claude (CL-R), 22 for Codex (CX-R) and 16 for the owner (MAC-R). Each remaining PLAN item in scope appears in at least one packet. Where an item mixes compiler work, cloud UI/packaging work and Mac or device evidence, it is split into packets with explicit dependencies.

What I checked read-only before writing these (main 8b73c79):
- **Bucket-5 CI.**
  - `macos.yml` already runs the native suite, pulled forward in Stage 2. The one exit still unmet is "hosted shards skip only hardware-tier cases".
  - BTRSmith has no `.github` directory.
  - BTRSmith branch `stage4/w2-btrsmith` (e8a53e27) pins btrc c7f785e and was never merged into BTRSmith main (adb3276f). It needs the rename-table rows from batches 7-9.
  - BTRSmith now builds `btrsmith-native` and passes `application-frontend-check` on Linux, so a lot of BTRSmith checking can move off the Mac.
- **No quiet-check script exists anywhere.** The Mac runbooks therefore need a small kit first.
- **The cloud has no `perf` instructions counter.**
- **BTRSmith issue mapping (read from GitHub).**
  - Automatable in Stage 39: #2, #3, #6, #7, #16-#19.
  - Physical, Stage 40: #4, #5, #21, #22.
  - Product integration evidence, Stage 9: #1.

Owner runbook mechanism (one command each): CL-R-02 adds `tools/runbook/` with:
- an engine that resumes interrupted runs;
- the automated quiet check from the standing approvals;
- lock handling;
- evidence publication.

Every MAC packet is then `tools/runbook/run.sh <preset...>`. Each preset is a TOML file under `tools/runbook/presets/`, owned by the packet whose work it measures. Mac results reach cloud agents as redacted summary JSON pushed to never-merged `evidence/<preset>-<date>` branches (open question 2). Raw logs stay in `~/.cache/btrc/bench`.

Where verification happens: each packet's `environment` field shows it.
- **GitHub macOS runners:** codesign, skip tiers, iOS simulator stand-ins, the debug adapter (DAP).
- **GitHub Windows runners:** x64 and ARM64 stand-ins.
- **The owner's Mac:** quiet wall-clock, instructions retired, GUI/GPU captures, the pinned Xcode 27A266a simulators, requalification, signing pushes.
- **Device or account (owner):** physical hardware and credentials. These stay "awaiting hardware" under D8.

Proposed D27 for this scope. It sits next to the UI clauses the other planners propose.
- **(a) Bucket-1 preparation in the cloud, before the Mac is back.** Only work that measures nothing and merges no compiler behavior change:
  - the Stage 6 reuse-key and journal spec, under adversarial review (CL-R-04);
  - the five Stage 6 floor spikes, as never-merged `spike/stage6-*` branches (CL-R-05);
  - measurement tooling: the runbook kit (CL-R-02) and the reference-profile capture (CL-R-06);
  - the D7 x86_64 fallback lane (CL-R-23); its own dependencies, D7 and Stage 3, are already met.
- **(b) Stage 38 CI for runners that already exist is pulled forward**, as Stage 2 did for the macOS suite:
  - macOS hardware-tier closure (CL-R-36);
  - BTRSmith Linux CI (CL-R-37), so BTRSmith requalification stops depending on the Mac;
  - CI tiering for Linux, macOS and Windows (CL-R-38, right after CL-R-36), because Codex and Claude draft PRs now compete for hosted macOS/Windows capacity.
- **(c) Owner-session preparation:** the macOS/Linux audio loopback rig against the existing CoreAudio/ALSA providers (CX-R-01) and the macOS session checklists (CX-R-03). The sessions themselves stay in Stage 40.
- **(d) Everything else stays gated.**
  - Stages 6-12 implementation merges nothing before the Stage 5 baseline (MAC-R-02).
  - Stages 39-43 wait for their bucket 3-4 prerequisites, because the macOS MVP closure stays in bucket 5 under D25.

Can start now: CL-R-01, CL-R-02, CL-R-04, CL-R-05, CL-R-06, CL-R-23, CL-R-36, CL-R-37, CX-R-01, CX-R-03 and MAC-R-07.

Critical path for bucket 1: CL-R-01 and CL-R-02, then MAC-R-01 (requalify and merge BTRSmith main), then MAC-R-02 (overnight Stage 5 round), then CL-R-03 and MAC-R-03. Stages 7-13 follow, alternating cloud implementation with one-command Mac measurement sessions.

Codex in this scope:
- **Bucket 5:** product journeys, packaging, signing, install/upgrade, stress, OS-matrix runs, device scripts, the latency rig, and the per-platform debugger and benchmark adapters.
- **Stage 7:** porting BTRSmith's PortableCoverage tests (CX-R-22).

Any compiler or runtime defect Codex finds is filed as a request; it becomes a Claude packet. The likely ones are named in each Codex packet's risks.

## 9. Writer adjustments

The six analysts' packets are reproduced faithfully in §6, except for the changes below and the review changes in §10. Every changed packet carries a **Writer note** in §6. The analysts' raw output is unchanged in `packets.analyst.json`; `packets.json` holds the final packets. Where §10 changes an item below, §10 wins; those items say so.

1. **Ownership: `CX-UIA-08` became `CL-UIA-21` (Claude).** Its owned paths are `flake.nix`, `nix/containerfile.nix`, `nix/devcontainer.nix` and `src/tests/runner_capabilities.py`. Four other groups treat these as Claude-only hotspots, and `CL-P1-02`, `CL-UIB-03`, `CL-R-13` and `CL-P2-04/17` edit the same files serially under Claude. The packet's content is unchanged. All references to it (`CL-UIA-05/06/08/11`, `CX-UIA-11` and the parallel-safe lists) now point at `CL-UIA-21`.
2. **Duplicate merged: `CL-UIB-01` into `CL-UIA-01`.** Both recorded D27 and the Codex protocol in PLAN.md and AGENTS.md.
   - `CL-UIA-01` now carries `CL-UIB-01`'s Stage 34–37 lane-owner annotations and its AGENTS.md list of paths Codex never edits.
   - It also commits this doc as `WORKSTREAMS.md` at the repository root. Its estimate rises from 2.5 h to 3.5 h.
   - `CL-UIB-01` stays in §4 as merged, with 0 h. No packet depended on it.
3. **Path collision: `.github/workflows/windows-arm64.yml`.** `CX-P1-03` (Stage 23) and `CX-P2-18` (Stage 27) both created it. `CX-P2-18` now extends the file `CX-P1-03` creates and depends on `CX-P1-03`.
4. **Codex edits to Claude-owned files became `fragment:` commits** (§3.5):
   - `CX-UIA-01`: the `Makefile` target;
   - `CX-UIA-02` and `CX-UIA-05`: the `denominators.toml` releases, plus `CX-UIA-02`'s `test_qualification_ledger.py` assertions (`CX-UIA-02`'s no longer apply: it adopts PR #21, which changes no denominator, §10 P10);
   - `CX-P2-18`, `CX-P2-31`, `CX-P2-49`, `CX-P2-50`: new expected-skip manifests. Claude adds `RUNNERS` entries in `tools/qualification/skips.py` only for names it lacks (`windows-arm64`, `windows-corpus`); `ios` and `android` are already listed (§10 C2).

   Analysts disagreed on this convention: some had Codex edit these files directly, others routed them through fragments. §3.5 now governs all of them.
5. **Compiler import closure fixed in `CX-P1-10`.** Its "outside the closure" set listed `Callback.btrc`, but the self-hosted compiler imports `Library.Callback` directly (six files). `Callback` moved to `CX-P1-10`'s must-not-touch list and to `CL-P1-20`'s closure.
   - §3.4 lists the transitive closure computed on `430a892`: the root prelude, `BackgroundJobs`, `Bytes`, `Callback`, `Console`, `Digest`, `FileSystem`, `IO`, `Iterable`, `JSON`, `Map`, `Math`, `OwnedBuffer`, `Platform`, `Process`, `Result`, `Strings`, `TOML`, `Timer` and `Vector`.
   - PLAN.md's disk-and-RAM rule also names `Datetime`, which the compiler does not import today.
6. **Missing dependencies added.**
   - `CL-P1-01` depends on `CL-UIA-01`, because its own risk says D27 must be recorded first.
   - `CX-P2-18` depends on `CX-P1-03` (item 3).
7. **PLAN-item dependencies resolved to packet ids.** Analysts wrote cross-group dependencies as PLAN item ids (`stage24:platforms-p1-native-import-targets`, `PLAN:ui-3-contract-input`, `ext:…`). §4 and §6 now show the packet that completes each one; Appendix A gives the full mapping. The Stage 4 close-out is now `CL-R-00` (§10 P2); only the bucket-5 opening remains outside any packet.
8. **Contract owner reconciled.** The Stage 34–37 analyst made Codex the D6(c) UI contract owner, while the brief makes Claude the contract owner. §2.1 settles it: Claude owns and approves; Codex is the single writer chain. Writer notes sit on `CX-UIB-17` and `CL-UIB-02`.
9. **UI denominator conflict reconciled** (§7 Q35). `CX-UIA-02` re-freezes about 178 operations, while `CX-UIB-86` and `CL-UIB-08` count 1,620/1,620 against the 2026-09-21 release. Every re-freeze is now a new release, and the Stage 37 count covers every release in force. Writer notes sit on `CX-UIA-02`, `CL-UIB-08` and `CX-UIB-86`. §10 P10 refines this: `CX-UIA-02` adopts PR #21's amendment model and does not re-freeze; `CX-UIA-05` cuts the first reviewed release.
10. **New packet `CL-REQ-01`.** It fixes the pre-existing failure `test_cached_split_cli_restores_complete_executable_generation`, recorded at Stage 18 and owned by no scope (§7 Q14).
11. **Shared append-only files.** `tools/bench/scripts/README.md` gets a row from both `CX-C-01` and `CL-R-02`. BTRSmith `docs/NativePlatformPlan.md` gets a section from both `CX-P1-01` and `CL-UIA-03`. Each pair may run in parallel, and the second to merge rebases (§3.3).
12. **Owner sessions combined.** One gate run in Session 1 (`MAC-R-01`'s `stage4-requal` preset) also serves `MAC-C-01` on the same `main` SHA, and folds in Stage 15's pending BTRSmith memory row. (`MAC-P1-01` moved after C4, §10 P11.)
13. **Overlap noted, not removed.**
    - `CL-UIB-04`'s CI concurrency-group step is already done by `CL-UIA-02`.
    - `CX-C-01` (bucket-2 checkpoint script) and `CL-R-02` (runbook engine) overlap. `CX-C-01` stays as the bucket-2 wrapper, and `CL-R-02` may later expose it as a `ccompat` preset.
14. **Scheduling note on `CL-UIB-16`.** The availability model moves earlier than Stage 37 (§7 Q12). §10 P4 places it after the GObject binding (`CL-UIA-08`) rather than right after `CL-P2-24`.
15. **Base moved.** `main` advanced from `8b73c79` to `430a892` (batch 10a, realtime seam). It touched `src/tests/native_targets.py`, which `CL-P1-10` later rewrites: a trivial rebase. No other packet is affected.
16. **Display only.** Packet text was escaped for Markdown: glob stars, angle brackets and backslash paths. Nothing else was reworded.
17. **UI parallel plan (2026-10-03, after the owner asked for all the UI work in parallel).** Four packets were added: `CX-UIA-30` (the 470 ui-case slots no packet owned), `CL-UIA-24` (several ledger releases per kind, the retired disposition, frozen UI sources read from the seed ledger), `CL-R-50` (path-selective lane tier) and `CL-P2-29` (the wgpu flake wiring split out of `CL-P2-17`, which keeps only the BTRSmith lock merges). `CX-P1-03…06` start now under Q20's default; Q48–Q51 were added. The Codex-facing summary is `docs/workstreams/codex-ui-lanes.md`. The §10.1 counts stay the review's historical counts; WORKSTREAMS.md §1 carries the current ones.

## 10. Review

> **D28 (2026-10-06):** this review record and §9 are historical. Where its scheduling outcomes conflict with D28 or [CODEX.md](../../CODEX.md), D28 governs ([CLAUDE.md D28](../../CLAUDE.md#decisions-all-resolved-2026-09-30)).

Three adversarial reviewers read the first version of this doc, each through one lens:
- **Plan:** sequencing, dependencies, and agreement with PLAN.md's decisions and stage exits.
- **Collisions:** path ownership, the protocol, and the repository contracts a packet would break.
- **Feasibility:** whether the cloud containers, Codex, GitHub CI and the Mac can actually do what the packets say.

Every finding was checked against PLAN.md, the repository at `430a892`, the `origin` branches, Codex's draft PR #21, recent CI runs and their skip reports, `gh` 2.89.0 and the pinned dev shell before it was applied. Each changed packet carries a **Review change** note in §6 that cites the finding (`§10 P3`, `§10 C7`, `§10 F6`, and `X` for changes found while applying).

### 10.1 Counts

| Lens | Findings | Blocking | Minor | Applied as written | Applied with a different mechanism | Rejected |
|---|---:|---:|---:|---:|---:|---:|
| Plan | 18 | 9 | 9 | 15 | 3 | 0 |
| Collisions | 17 | 10 | 7 | 14 | 3 | 0 |
| Feasibility | 19 | 7 | 12 | 15 | 4 | 0 |
| **Total** | **54** | **26** | **28** | **44** | **10** | **0** |

Every blocking finding was confirmed and applied. No finding was rejected outright. Ten were applied with a different mechanism than the reviewer proposed, and two (P3, C8) offered options; §10.3 gives the reasons. Three facts in the findings had moved on by the time of checking, and the doc uses the measured values: `stage4/btrsmith-defects-compiler` is now 12 commits ahead (not 9), PR #21's base is `e4a904e` (not `430a892`), and the two AGENTS.md measurement sections are 6.0 KB (not about 10 KB).

**Packets.** Before the review: 433 (Claude 173, Codex 206, owner 54); agent-hours Claude 1403, Codex 1872, owner 106.8; start-now Claude 19, Codex 30, owner 3. After: **445** (Claude 182, Codex 208, owner 55); agent-hours Claude 1448, Codex 1890, owner 106.3 attended, plus about 282.5 h of Mac wall time and 14 overnights; start-now Claude 17, Codex 26, owner 2. Twelve packets are new; no id was renumbered.

**Checks on the final doc.** The dependency graph has 0 cycles and 0 dangling ids (the first version had two cycles). Every Codex packet that creates a `{Windows,IOS,Android}` stdlib directory depends, at least transitively, on `CL-P1-15`. No Codex acceptance item asks for a local `make test`. `packets.json` is regenerated from the same data as §6.

### 10.2 What changed, finding by finding

**Plan lens**

| # | Sev. | Finding | Change |
|---|---|---|---|
| P1 | B | Two dependency cycles stopped Stages 36 and 37 | `CL-UIB-15` depends only on `CL-UIB-05` (`MAC-UIB-07` stays an acceptance item). `MAC-UIB-10` is now the per-host evidence (feeds `CX-UIB-86`); the bucket-4 Mac gate is new `MAC-UIB-11` after `CL-UIB-17`. |
| P2 | B | Stage 4's close-out had no owner; three unmerged Stage 4 lanes were unknown | New `CL-R-00` integrates `stage4/btrsmith-defects-compiler`, `stage4/residual-final` and `stage4/c-output-parity` (with D14 re-captures) and writes the findings ledger. Lock-table rows added. `CL-C-03` and `CL-C-04` depend on it; `CL-R-01` depends on it to finish and takes the `*.swift` native-source-check. |
| P3 | B | The Q2 default let Stage 24 merge during bucket 2, contradicting D1 | Option B: D27's last clause amends D1 explicitly (Stage 24 and Stage 25's compiler packets after `CL-C-06`; interop, GObject and `CL-UIB-16` after `CL-C-40`), and needs the owner's approval. `CL-P1-03` → `CL-C-06`; `CL-P2-05` adds `CL-C-40`; §2.1 rewritten, including what happens if the clause is struck. |
| P4 | B | GObject was moved ahead of interop steps 3–7 | `CL-UIA-06` depends on `CL-P2-24` and `CL-UIA-21`; D27's gated bullet and the mermaid edge (`INT2 --> GOB`) follow. |
| P5 | B | UI2/UI3 frozen before any new-platform shell exists | `CL-UIA-13`/`19` depend on `CX-UIA-13`; D27 makes those approvals provisional for Windows, iOS and Android until `CL-UIA-22`; `CL-P2-22` re-checks against `ui2-approved.md`; `CX-UIA-15/16/17` implement the landed methods or throw typed unsupported. |
| P6 | B | No packet for the new-platform half of `ui-1-feasibility-review` or Stage 31's close for those providers | New `CL-UIA-22`; `CX-UIB-10/42/50/58` depend on it. |
| P7 | B | Nothing ports the Linux UI2/UI3 core to GTK4 if D23 picks it | New `CX-UIA-29` and its landing `CL-UIA-23`, both only if D23 = GTK4; `CX-UIB-20/21/23/26/27/30` depend on `CL-UIA-23` conditionally. |
| P8 | B | New-platform provider packets did not wait for Stage 24's filters and cache identity | `CL-P1-15` added to 20 Codex packets (and to `CX-P2-13`, whose route now creates `Regex/Windows/`). |
| P9 | B | Stage 34 landings dropped their own UI8/UI9 acceptance | `CL-UIB-05…08` require the family's UI8 rows, keyboard journeys, and the VoiceOver and Orca records run on `integ/ui-lN` before the push, plus UI9 rows. `MAC-UIB-01/02` depend on the L1 branches (ready), not on `CL-UIB-05`; Q31 matches PLAN. |
| P10 | m | PR #21 was unknown, and its layout differed | Lock-table row; `CX-UIA-02` adopts PR #21; Q35/Q36 reconciled to one layout (§10.3). |
| P11 | m | `MAC-P1-01` folded into Session 1 on a C1-only tree | `MAC-P1-01` depends on `CL-C-06`; Session 1 serves `MAC-C-01` only; the baseline moves to session 5. |
| P12 | m | `CL-UIA-15…18` and `CL-UIB-13` started early against D27's own rule | `CL-UIA-15…18` listed in D27's Claude-early clause (bucket 1 measures the D9 copy, never BTRSmith `main`). `CL-UIB-13` depends on `CL-UIB-02` and holds only each request's files. |
| P13 | m | `CL-UIA-03` started before the catalog schema | Depends on `CX-UIA-02` (ready). |
| P14 | m | Three plain-C mobile packets waited for lifecycle owners | `CX-P2-40` waits for `CX-P1-08`; `CX-P2-44`/`45` wait for `CX-P1-09`. |
| P15 | m | `CL-R-23` started before D7's probe | Split: `CL-R-23` keeps the host manifests (start now); new `CL-R-49` holds the workflow after `MAC-R-07` and `MAC-R-02`. `CL-R-35` waits for `CL-R-49`. |
| P16 | m | Stage 35 owner evidence waited on bucket 5 | `MAC-UIB-06` depends on `CX-UIB-48` only; `MAC-R-12` drops `CX-R-12` and runs P6 device rows with `MAC-R-14`'s session. |
| P17 | m | `CL-P1-01` marked start-now while waiting for Gate 0 | Now `no`, "after Gate 0". |
| P18 | m | Owner decisions amended by default | §2: D27 takes effect on the owner's approval, with a defined pre-approval set. §7 marks Q1, Q2, Q9, Q10, Q12, Q27, Q30, Q33 and Q40 **needs owner approval**; Q31 now matches PLAN, so it needs none. |

**Collisions lens**

| # | Sev. | Finding | Change |
|---|---|---|---|
| C1 | B | `test_ci_workflow_contracts.py` rejects every new workflow and `inputs:` | `CL-UIA-02` owns that test and replaces the exact-trigger check with a per-class policy and derived skip-report names. `CX-P1-03…06` and `CL-R-49` depend on it; lane-workflow packets own their rows; §3.2 rewritten. |
| C2 | B | New platform-gated tests had no expected-skip rules | §3.5 skip-rule paragraph; §3.7 skip-gate line; `CL-UIB-04`'s wording; `CX-P1-07/08/09` and `CX-P1-10` use the `fragment:` commit; `CX-P2-49/50` drop the RUNNERS step (`ios` and `android` are already listed). |
| C3 | B | `fragment:`/`derived:` misused | `CX-P1-10`, `CX-UIB-17`, `CX-UIB-27`, `CX-UIB-09`, `CX-UIA-01`, `CL-UIA-01` step 3, `CL-UIB-01` step 4 and `CL-UIA-05` corrected; §3.5 says how to read older wording. |
| C4 | B | Shared manifests would serialize every provider lane | §3.3: integrator-owned data and generated files are never held. Codex entries are labelled `fragment (not held)`, Claude landing entries "(integrator: applies fragments; not held)"; the Codex-areas row excludes `btrc.toml`; D27 names the integrator-owned data. |
| C5 | B | Stacked contract branches deadlocked; landings broke the two-branch cap | §3.2 stacked branches; 37 packets now mark such dependencies `(ready)`; §3.10 done rules; D27: an atomic landing counts as one branch. |
| C6 | B | No workflow ran the new platforms' pytest suites | `CX-P1-07/08/09` add provider-suite jobs; `CX-UIA-15/16/17` run there, own their rows in the shared shell test, and `CX-UIA-15` owns the Windows no-provider case; `CX-UIA-15` depends on `CX-P1-07`; `CX-P2-04`'s fallback points at `host-windows.yml`. |
| C7 | B | §3.4 let Codex change the self-hosted compiler | §3.4 step 4: byte-identical C for every host entry, never waived. New `CL-P2-27` lands the Windows FileSystem and Process providers into `btrcc`; `CL-P2-14` and `CX-P2-14` wait for it. `CX-P2-37/42` added to §3.4; `Process.btrc` added to `CL-P1-20`; `CX-P2-04/06/14/15` depend on `CL-P1-20`. |
| C8 | B | `src/runtime/gpu` and `src/runtime/windows` had no owner class | Runtime class and D27 cover `src/runtime/**`. New `CL-P2-28` owns the GPU runtime's platform branches; `CX-P2-33/39/44` request them. `CX-P2-13` takes route (b) only, and route (a) is `REQUEST(CL-P2-14)`. |
| C9 | B | Optional devex fuzz packets could hold C-track files | `CX-C-02/03` own new tests plus one named file at a time; must-not-touch the C3 lane's files; `CL-C-23` removed from `CX-C-02`'s parallel list; new editor-tooling row in §3.3.1. |
| C10 | B | UI11 added portable contracts after the Stage 34 freeze | New `CX-UIB-95` (drafts, then the approved interfaces, factory lines and stubs as the stacked base) and `CL-UIB-18` (review and approval). `CX-UIB-87/89/91/93/94` depend on both and no longer create interface files. |
| C11 | m | Gate 0 was circular | Gate 0 is `CL-UIA-01` alone; `CL-UIA-02` lands in the next batch. |
| C12 | m | Claude's between-batch claims were invisible | §3.2: Claude claims a lane with a `[CL-…]` draft PR before the first edit. |
| C13 | m | Root-module changes alter strict imports | §3.4 paragraph on `btrc.symbols` owner-line diffs; renames and removals are requests. |
| C14 | m | Nothing wired the UI catalog into the report | `CL-UIA-05` wires it; `CX-UIA-02`'s acceptance uses the catalog's own `--report` until then. |
| C15 | m | Registering an executor needed a forbidden edit | `CL-P1-17` discovers executors by import. |
| C16 | m | Other unordered same-file claims | `CX-UIA-07` excludes the Review checkpoint section; `CX-P2-13` waits for `CX-P1-10`; `CL-P2-12` narrowed; `ci-health.md`, shell-test rows and `test_native_cxx_owners.py` rows are shared append-only; `CX-UIB-69/70` wait for `CL-UIA-17/18` and the L2 pin; D24 reproduction branches allowed in §3.2. |
| C17 | m | Inaccuracies | §3.4 and §3.3.1 list the BackgroundJobs modules btrcc really imports; `CX-UIA-21` needs no bootstrap; local `make test` removed from Codex acceptance. |

**Feasibility lens**

| # | Sev. | Finding | Change |
|---|---|---|---|
| F1 | B | GitHub CI capacity cannot carry per-push PR CI | `CL-UIA-02` gains concurrency groups, a scope job and capacity acceptance; §3.2 capacity rewritten from the measured runs; at most one Codex PR with a full macOS run in flight. |
| F2 | B | The Codex CI feedback loop was unspecified | §3.2 feedback loop; §3.11 item 8; §7 Q47. |
| F3 | B | PR #21 was ignored | Lock-table row; `CX-UIA-02` adopts PR #21; Q35/Q36 record one decision; `CX-UIA-03…07`, `21`, `25` re-pointed; `CX-UIA-01` gives the drift-gate half of `ui-0-focused-gate` to PR #21; §5.4 says PR #21 predates Gate 0. |
| F4 | B | AGENTS.md exceeds Codex's read limit | `CL-UIA-01` puts a ≤3 KB Codex section first and cuts AGENTS.md to ≤30,000 bytes, with a byte-count acceptance check. |
| F5 | B | The setup script and container facts were wrong | The `gh` step persists credentials with `GH_TOKEN` unset; a gcc 15.2 check; builds only through `make btrcc`; resources reworded from PR #21's numbers. |
| F6 | B | Acceptance relied on nonexistent jobs; `CL-UIB-14` had a cycle | `CL-UIB-14` is now the CI UI shards; new `CL-UIB-19` holds the rolling landings. Shell acceptance moved to the host lanes (with C6). |
| F7 | B | BTRSmith packets cited runners BTRSmith cannot use | New `CL-R-48` (KVM emulator and Windows dispatch jobs, billed minutes recorded); `CX-P2-19/20/35/47/48` and `CX-UIB-85` depend on it; `CX-UIB-84`, `CX-R-05/06/22` move macOS evidence to `MAC-UIB-09`, `MAC-R-10` and `MAC-R-04`; Q30 needs approval. |
| F8 | m | Hosted macOS runners do have a GPU adapter | Corrected in §3.2, §6.2, `CL-UIA-02`, `CX-UIA-03/06/09/10/22`; `MAC-UIA-02` shrinks to timing rows; `CX-P2-39` and `CX-UIB-57` probe the simulator's Metal device first. |
| F9 | m | Wrong environment labels | `CX-UIB-66…76` → Linux cloud (and `CX-UIB-66` measures counters, not CPU%); new class `linux+kvm-ci` for 14 Android packets, including `CL-UIB-11`. |
| F10 | m | A branch-only workflow cannot be dispatched | §3.2 and §3.11. |
| F11 | m | GraphQL is blocked in Claude Code sessions | §3.3 and §3.8 use REST. |
| F12 | m | Claims keyed on a branch name Codex may not control | The claim key is the `[CX-…]` title plus the `Packet:` line. |
| F13 | m | The skip gate fails in cloud containers | `BTRC_TEST_RUNNER=linux-devcontainer` in §3.11, the setup script and `CX-UIA-01`. |
| F14 | m | Acceptance asked Codex for `make test` and macOS C | Ten `CX-P2` acceptance items now name draft-PR `ci.yml`; §3.4 step 4 checks macOS C through the macos.yml bootstrap shard; §3.11 allows the CI bootstrap shard. |
| F15 | m | Packets spanning two repositories | A rule in §3.2 and a note on all 23 affected packets (§10.3). |
| F16 | m | Bare `python -m pytest` and nested nix | §3.11 command rule; `CX-UIA-01` item 1. |
| F17 | m | The cloud batch gate was undefined | §3.8 step 4 defines it. |
| F18 | m | Owner hours hid Mac occupancy | Every owner packet carries `mac_wall_h` and `overnights`; §1, §4 and §5.5 show Mac wall hours. |
| F19 | m | Timing thresholds in sanitized shared-runner runs | Thresholds apply to plain builds only (`CX-UIA-23`, `CX-UIA-27`, `CX-UIA-29`). |

**Found while applying**

| # | Change |
|---|---|
| X1 | `MAC-R-07`'s optional BTRSmith token for the public btrc repository contradicted §7 Q28; the step is dropped, and `CL-R-49` runs no BTRSmith workload. |
| X2 | `CL-C-25` and `CL-P1-05` would both add `CIntegerWidths.for_target`; `CL-C-25` consumes Stage 24's owner if it landed first. |
| X3 | Start-now flags recomputed after the new dependencies (`CX-P1-03…06`, `CL-UIA-03`, `CL-UIB-13`, `MAC-P1-01`). |
| X4 | `CL-UIB-15`, `CL-UIB-19` and `CL-P2-28` are rolling packets; their consumers name the step they need, so the `CL-UIB-14` cycle shape cannot recur (§3.10). |

### 10.3 Applied differently, or a choice between offered options, and why

- **P3 (option B, not A).** The reviewer offered keeping D1 (Stage 24 after Stage 21) or amending it explicitly. The doc takes B, because every Windows, iOS and Android lane, and so most of Codex's non-UI work, sits behind Stage 24, and the Stage 24 design already says it "waits for C4". B is written as an explicit, strikeable D27 clause pending the owner's approval, and §2.1 states what changes if it is struck. That is option A, so the doc never holds both at once.
- **P4 (where `CL-UIB-16` goes).** The reviewer said `CL-UIA-06` should also wait for `CL-UIB-16` if Q12 keeps the availability model right after `CL-P2-24`. Instead, `CL-UIB-16` now follows the GObject binding (`CL-UIA-08`). GObject gates D23 and with it Stage 34, while the availability model is a Stage 37 prerequisite, so this keeps the shorter path critical. Both still serialize on `native_abi.asdl`.
- **P10 and F3 (catalog layout).** The two reviewers asked for one layout, either PR #21's or the analysts'. The default adopts PR #21's seed file and amendment model, because it is the earliest claim and already tested, and it keeps PLAN's 162/1,620/470 exit numbers true. The analysts' shard directory survives only for later shard documents (classifications, surface, hosts, evidence) beside the seed, merged by subject. That way the parallel operation-map packets never edit one 6,485-line file. `CL-UIA-01` records it.
- **F3 (narrowing `CX-UIA-01`).** It keeps `test_native_gui_target.py`, which proves every GUI fixture is driven by the new target. PR #21 does not cover that, and dropping it would let fixtures fall out of the focused gate silently.
- **F4 (AGENTS.md size).** The two measurement sections are 6,022 bytes, not about 10 KB. With a 3 KB Codex section, moving them alone leaves AGENTS.md near 34 KB. The Python file tree (4,954 bytes, already in `compiler-structure.md`) moves too, and `test_python_compiler_structure.py` drops its AGENTS.md entry in the same commit.
- **F15 (two-repository packets).** The packets are not split into `<id>-btrc`/`<id>-btrsmith` ids. The id scheme is numeric, and §4, the anchors and `packets.json` key on it. A §3.2 rule (two tasks, one per repository environment, btrc half first, done when both are) and a note on each of the 23 packets give the same coordination.
- **C7 (`CL-P2-27`'s dependencies).** The reviewer had the landing packet depend on `CL-P2-14`. PLAN puts the Unicode host after Stage 26's filesystem work, and `CL-P2-14` already depended on `CX-P2-05`. So the edge runs the other way: `CL-P2-14` waits for `CL-P2-27`.
- **C8 (GPU runtime).** Of the two options, the doc takes the Claude packet (`CL-P2-28`), because `btrc_gpu.c` exports an ABI that both compilers lower against. Serializing three Codex packets on one runtime file would still leave a Codex agent editing a hosted-ABI implementation.
- **C10 (UI11 drafts).** Drafts from four packets become one Codex packet, `CX-UIB-95`, which drafts all ten interfaces and then carries the approved interfaces and factory lines as the base branch. All four packets needed the same frozen `GUI.btrc` and `IApplication.btrc`, so one writer is simpler than four drafts plus a separate base.
- **C16 (`CX-UIA-23` → `CX-UIA-11`).** That dependency already existed, so the only change is the §3.2 rule for the E40 branch.
- **P1 and F6 (ids).** The reviewers named the halves `MAC-UIB-10a/10b` and `CL-UIB-14a/14b`. Ids stay numeric: the half that existing packets already point at keeps the old id (`MAC-UIB-10` stays the evidence that `CX-UIB-86` needs; `CL-UIB-14` stays the CI shards that `CX-UIB-42/50/58` need), and the other half gets the next free number (`MAC-UIB-11`, `CL-UIB-19`). `CL-R-37b` is `CL-R-48`.

### 10.4 Residual risks the review leaves open

- **Bucket-1 workload drift.** D27 lets Codex's stdlib GUI changes land while bucket 1 measures. BTRSmith compiles `Library.GUI`, so the measured workload can move with the btrc commit even though BTRSmith itself is pinned (D9). Bucket-1 A/B comparisons must build both compilers against one stdlib revision; `CL-R-02`'s runbook should record the stdlib digest in every report.
- **Codex settings are unconfirmed.** The CI feedback loop, AGENTS.md's read limit, container size and BTRSmith access are all "confirm in the Codex settings" (§3.11). Until the owner confirms them, Claude posts the `@codex` comments and the owner starts follow-up tasks.
- **Mac wall hours are estimates.** They are derived from each packet's steps (a D5 gate is taken as about 4.5 h and a quiet round as one overnight). `MAC-R-08` assumes five Stage 11/12 batches.
