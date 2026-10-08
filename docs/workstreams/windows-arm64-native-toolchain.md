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

### Follow-up claim: compatibility declaration (2026-10-08)

The parent integrator owns `src/runtime/windows/btrc_win_compat.h`,
`src/tests/python/test_native_win_compat.py`, this report and its WORKSTREAMS
claim for the follow-up based on `fe115d6be927b23ac2bda7ef5e9bd8639de1a763`.
Native run 37711636840 (hosted merge `adef61ea2349196924f625416361e9b625c72d5b`)
links the minimal GNU executable successfully, then the actual strict probe
reveals a newer MinGW `stdlib.h` declaration of `mkdtemp` conflicting with our
static implementation. BTRC/bootstrap have not executed. Preserve the existing
adapter semantics and generated-extern compatibility on old and new headers;
do not gate this on a guessed toolchain version or change compiler flags.

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

Claim commit: `34170217`. Fixture-only red commit: `f008131c`.

The native archive row now owns its version as well as URL, size and digest.
`identify()` validates the version selected by the execution mode. The existing
cross version pin and cross manifest checks stay at 0.16.0. Native reports carry
the selected archive metadata, actual Zig version, and verified cross Zig
version separately. The unchanged workflow validates the downloaded archive's
size and SHA-256 before placing its executable on PATH. Local metadata review
does not claim that the Windows archive was downloaded or executed here.

After validating the cross artifact, each native invocation creates a unique
cache root beneath its evidence directory, with empty global/local caches.
Both environment variables override inherited cache paths in the private child
environment, including subsequent bootstrap children. The parent environment
is unchanged. Failed cache directories remain retained with the evidence;
repeating an invocation never reuses or deletes them.

Focused validation used retained Python
`/nix/store/35r726j0hx21698i9p7ry53l1afprc84-python3-3.14.6-env/bin/python3`:

```text
PYTHONDONTWRITEBYTECODE=1 <python> -m unittest tools.windows_toolchain.test_arm64 -v
PYTHONDONTWRITEBYTECODE=1 BTRC_TEST_RUNNER=macos <python> -m pytest -q \
  src/tests/python/test_ci_workflow_contracts.py::test_windows_arm64_lane_keeps_cross_and_native_qualification_separate
```

- Baseline: 38 tests, 37 passed and one existing Windows-native skip, 3.209 s.
- Red: both new regression tests fail against unmodified production; native
  mode incorrectly accepts the cross pin and lacks isolated cache provenance.
- Green: 40 tests, 39 passed and the same native-only skip, 3.293 s. The cache
  regression executes a real Python child through the shared process owner,
  verifies both environment values, and retains the first failed run's marker
  across a second run with the same output directory.
- The existing workflow separation contract passed, 1 test in 0.18 s.
- Ruff lint/format and `git diff --check` passed. The qualified Python contains
  no Ruff module; the check used the retained Ruff 0.15.14 executable instead.
- Independent source/wiring review by execution_review found no blocker. It
  compared the pin with both retained and live official metadata and checked
  that fresh caches reach bootstrap without weakening cross/native gates.

Evidence lives outside Drive at
`~/.cache/btrc/plan-consolidation-2026-10-07/windows-native-zig-017/`:
`baseline.log`, `red.log`, `green.log`, `workflow.log`, and retained official
index/release-note responses. The native pin was compared directly with the
official index's `0.17.0` ARM64 Windows row. Index response SHA-256:
`4787934a28d494dc496d93cfa46cabb840158db938cfbea0cde3f3cce63bb936`;
release-note response SHA-256:
`55d4e9d4b489195dbca2631169b6def135ef97c05a7742c784ca28cacb7dd210`.

The pin repair was published at `fe115d6b`. Actual native run 37711636840 verifies
and runs Zig 0.17.0 on Windows ARM64 with ARM64 Python. Its ordinary minimal GNU
executable link succeeds (exit zero); object generation also passes. The strict
stdio probe stops at a C declaration error, before BTRC or bootstrap executes:
newer MinGW `stdlib.h` declares `mkdtemp`, while our force-included compatibility
header defines a static function with the same name. The independent MSVC/wgpu
smoke remains separate. This advances the investigation beyond the previous
driver access violation but does not qualify the native BTRC compiler.

The follow-up names the existing implementation `btrc_win_mkdtemp` and maps the
portable name with an object-like macro after its definition, following the
existing locale/stdio/durability wrappers. Its argument validation, collision
retry, allocation, errors and directory creation are unchanged. The CRT keeps
its own declaration; generated extern declarations and calls resolve to the
already-declared internal wrapper. No version test or toolchain flag is added.

The existing three-translation-unit strict C11 regression now also force-includes
an external CRT declaration before the compatibility header, reproducing newer
headers on the retained older Zig cross compiler. Fixture-only checkpoint
`1a80527d` gives **one pass and one failure**, with the same static-versus-external
linkage diagnostic in all three translation units. With the fix, the complete
compatibility module has **five passes, zero skips** in 1.25 seconds using
Zig 0.16.0. It verifies compilation/linking, later generated-style externs and
multiple translation units against both header layouts. Windows executables are
not run on this Mac; actual native runtime/bootstrap qualification still requires
the hosted rerun. Evidence is retained at
`~/.cache/btrc/plan-consolidation-2026-10-07/windows-mkdtemp-compat/`, with the
actual failed native artifact at sibling `windows-fe115d6b-native/`.

Time categories: the pin repair used source/review and small Python checks;
the follow-up additionally ran the bounded Windows cross-compile regression
under the Mac's gate/build locks. No measurement or Windows native execution is
claimed from local checks. The parent owns publication and CI slots.
