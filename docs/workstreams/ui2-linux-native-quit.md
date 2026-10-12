# Linux native application quit

## Claim and boundary

This packet owns the following paths on `codex/ui2-linux-native-quit`. The ordinary Linux Window checkout and index remain unchanged.

- `src/stdlib/GUI/Linux/LinuxApplication.btrc`
- `src/stdlib/GUI/Linux/LinuxPublisher.btrc`
- `src/stdlib/GUI/Linux/LinuxWindow.btrc`
- `src/tests/native/gui/ui2/probes/linux/ApplicationQuitFaults.btrc`
- `src/tests/native/gui/ui2/probes/linux/ApplicationQuitFaults.c`
- `src/tests/native/gui/ui2/probes/linux/ApplicationQuitFaults.h`
- `src/tests/native/gui/ui2/probes/linux/ApplicationQuitProbe.btrc`
- `src/tests/native/gui/ui2/probes/linux/ApplicationQuitProbe.c`
- `src/tests/native/gui/ui2/probes/linux/ApplicationQuitProbe.h`
- `src/tests/native/gui/ui2/probes/linux/UI2LinuxApplicationQuit.btrc`
- `src/tests/native/gui/ui2/probes/linux/UI2LinuxApplicationQuitCleanup.btrc`
- `src/tests/native/gui/ui2/probes/linux/UI2LinuxApplicationQuitRetry.btrc`
- `src/tests/native/gui/ui2/probes/linux/UI2LinuxApplicationQuitTransactions.btrc`
- `src/tests/python/test_native_ui_core_linux.py`
- `docs/workstreams/ui2-linux-native-quit.md`

The implementation extends the existing Linux Application, Window transaction and Publisher owners. It adds no portable API, runtime shim, second transaction model or production manifest row. It follows the approved D29 held-authorization clarification recorded in the macOS native-quit packet: document owners report revisions, identity and membership are revalidated, and all ingress is sealed before releasing references that can run user finalizers. Direct `requestQuit` remains irreversible. An SDL QUIT is captured when the existing event pump dequeues it; queue insertion alone grants no authority.

## Retained baseline and intended proof

The base is qualified Linux Window candidate `fbb9e27a2badafb50f2379a0395cde11e0028ada`. Hosted run 37874567498 retained four exact missing-API semantic baseline failures and four passing candidate native cells (both compilers, plain and ASan/UBSan), with no skips. Artifact ZIP SHA256 is `922690528d3d198953e2e85f6ea0d6b8a3a63ef43386551312edacd43a745c6f`; scoped audit SHA256 is `0fa89c0835403cb070c43d74e48ad8398c3922e83f1b3de828c33e51dd756941`. That evidence covers Window close transactions, not application group quit.

The fixture-only baseline preserves the complete first cancellation journey: actual SDL QUIT, two dirty windows and a clean peer, deferred decision delivery, repeated-request identity, held DISCARD, peer cancellation, retained roots/drafts and queued work/publication. The intended old-source failure is the exact assertion that DISCARD returns AUTHORIZED while every native window remains open. Compilation, link, timeout, prerequisite or another assertion failure is not this baseline. No actual group-quit baseline has run yet.

The candidate also tests pending SAVE promotion after real QUIT dequeue, stale revisions and attempts, direct CANCEL on AUTHORIZED, early peer-prompt suppression, handler replacement, clean-to-dirty and new-window membership, all-authorized consumption, late-call rejection, finalizer reentry and all-producer admission sealing. The explicitly armed native mutex return-code probe requires public RETRYABLE then recovery; it does not claim an executed thrown-cleanup path.

Planned acceptance is 28 Linux native cells: four new quit fixtures plus unchanged Window, Executor and Lifecycle regressions, each through reference/selfhost and plain/ASan-UBSan. Existing 30-second native, 600-second transpile and inherited compile/process/container limits remain. Mac-only legacy application scenarios, Linux Controls and full UI2 are outside this scoped matrix.

Current compiler `5aa232ad27854b7f45a2a42f75cbf0cbab589578` is selected symmetrically for both roles. Compared with the previous f75 compiler, only the two separately qualified selfhost pipeline lifetime owners differ within compiler/stdlib/runtime/language/codegen; reference native semantics, ABI, runtime and stdlib are identical. The hosted recipe builds it freshly; source compatibility is not a substitute for actual native acceptance.

## Source checkpoint

Root and independent source review are clear. BTRC formatting and Python Ruff checks passed on the drafts. No new compiler/native execution, publication, performance or full-provider acceptance is claimed by this source checkpoint. The fixture-only and production commits are kept separate for authentic baseline comparison.
