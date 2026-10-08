# Windows ARM64 native toolchain repair

Owner: Codex performance_review, assigned under PLAN D29 on 2026-10-08.
Branch: `codex/windows-arm64-native-zig`.
Base: `75c00a96c433ce75ff389d03e1b0212ecf14271d` (PR head, not its hosted merge).
The token-lifetime branch remains preserved at `d6309c7c`, including production
commit `69ca0f17`. No compiler or stdlib source belongs to this packet.

Owned paths:

- `tools/windows_toolchain/pins.json`
- `tools/windows_toolchain/arm64.py`
- `tools/windows_toolchain/test_arm64.py`
- This report.

## Evidence and intended outcome

Windows75 retained actual native C object and direct no-CRT DLL link successes,
but the ordinary GNU executable driver access-violated before BTRC execution.
The debugger retry timed out after 20 seconds and printed two cached-ZIR EOF
warnings. These warnings do not prove the cause of the first crash.

Zig's [0.17.0 release notes, Target Support](https://ziglang.org/download/0.17.0/release-notes.html#Target-Support)
state that the LLVM defect breaking most ARM64 Windows binaries, including
Zig itself, is worked around. The release uses
[LLVM and Clang 22.1.8](https://ziglang.org/download/0.17.0/release-notes.html#LLVM-22).
The underlying [LLVM issue 199581](https://github.com/llvm/llvm-project/issues/199581)
describes erroneous ARM64 COFF TLS relocations; its
[upstream repair](https://github.com/llvm/llvm-project/pull/199602)
merged as `7f5a6d77bac92ca3273bb0a98b8604f4987001ed` on 2026-06-09.
The Zig release notes say **workaround**; this packet does not infer that the
archive was built directly from that LLVM commit. A separate project's
[minimal native reproduction](https://github.com/kaappi/kaappi/issues/1613)
supports investigating this toolchain defect, but does not diagnose BTRC's
retained failure by itself.

The [official download index](https://ziglang.org/download/index.json) lists
0.17.0, released 2026-10-01, with native ARM64 Windows archive:

- URL: `https://ziglang.org/download/0.17.0/zig-aarch64-windows-0.17.0.zip`
- Size: `95992853` bytes
- SHA-256: `0a59d91fa1cb40cf068e9b0954434ce973500c7a2ea749f1e01af62cdab52d26`

Only the native Windows ARM64 pin changes. The Linux cross-build remains on
0.16.0 at the same source revision, with its artifact digest checked. Native
qualification must still pass the actual C stdout/stderr probe, GNU target and
strict C11 flags, native compiler build, cross/native emitted-C equality,
golden executable, and three-stage bootstrap fixed point. Fresh run-specific
Zig caches prevent inherited or previously interrupted cache files from
confounding this attempt; they are not a substitute for the toolchain repair.
No global platform pin, ABI, deadline or acceptance criterion changes.

## Qualification status

Claim recorded before implementation. Focused regression tests will precede
the repair. Actual Windows native qualification and hosted CI remain pending;
no Mac test can supply that evidence. The parent owns publication and CI slots.
