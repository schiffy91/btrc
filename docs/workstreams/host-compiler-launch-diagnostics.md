# Host compiler launch failure evidence

The macOS unit retry on source `00e45379` (test merge `d38f344f`), run
37786709071 attempt 2, job 113416271573, completed with 10,127 passing,
227 expected skipped and six failing cases. Each failure was an actual
`FileNotFoundError` launching the selected absolute GCC wrapper; none reached
GCC diagnostics. All 920 failures/errors from attempt 1 passed on attempt 2,
and these six had passed on attempt 1. Both failed attempts remain evidence.
The log cannot distinguish a removed wrapper from a missing shebang interpreter
or establish who removed a file. No garbage-collection cause is asserted.

## Diagnostic boundary

The existing test toolchain owner records filesystem facts immediately after
`HOST_C_COMPILERS` selection. The existing pytest report boundary appends a JSON
section only when the original exception is `FileNotFoundError` and its filename
exactly matches that retained selection. Test identity, exception, result,
coverage, commands, environments and deadlines remain unchanged. There is no
compiler fallback, PATH re-selection, retry, skip or Nix operation.

Snapshots record selected path, lstat identity, bounded symlink traversal,
resolved path when available, first unavailable component, Nix store ancestor
identity, and a readable regular file's shebang interpreter path/identity.
The initial and failure observations have separate timestamps. Traversal is
bounded to 128 components and 40 links; header reads are bounded to 4096 bytes.
No executable body, shebang arguments or environment values are reported.
Nonregular files are not read; nonblocking open and descriptor validation also
reject a FIFO swapped in after inspection. Diagnostic errors remain data.

These are observations, not an atomic filesystem snapshot or proof of removal
cause. An intact failure-time path can reflect a race or another exec dependency;
a native binary's dynamic loader is not inspected. Interpreter arguments such as
`env` dispatch are deliberately not resolved or executed.

## Verification scope

The unchanged ef65e208 harness-selection baseline passed all 15 cases. Exact
candidate66047414 passed 109 cases: 25 harness-selection, 23 coordination and
61 existing skip-ledger checks. Actual collection and JUnit identities agree;
there were zero failures, errors or skips in either outer suite. This includes
real POSIX missing-wrapper/interpreter/parent launch failures, intact-path and
unrelated-error controls, malformed headers, FIFO/loop and symlink-parent facts,
and a real child pytest failure whose identity/outcome survives the reporting
hook and SkipLedger. Windows retains filesystem facts for the POSIX shebang
case; no Windows execution is claimed by this local proof and no new skip exists.

Evidence: `host-compiler-launch-66047414-attempt-1/result.json`, SHA256
`74dfdf9306a63b439d99d0d49749754fba8aa80b9eb56427cfb7d41ae8fa0372`.
Baseline JUnit SHA256
`97cdc64bebdab9a1d8dda03b4ee2d5d1ad81ac66719b0de94a04101630c37664`;
candidate JUnit SHA256
`20aab459f5411323552a4bd49f89fd8c0f5f68baf87733f60e2e474e2ce53d20`.
All eight recorded process-group leaders reaped with exit0, their groups were
absent, logs rehashed, and complete source/mode/tool/archive inputs closed
unchanged. Ruff and diff checks passed. This is focused diagnostic/reporting
qualification, not the final compiler matrix or a hosted macOS unit pass.

The hosted ENOENT cause remains unresolved. These diagnostics neither repair
that failure nor authorize treating it as a skip; the next source-changed hosted
qualification must preserve the original GCC coverage and report any repeated
failure with the new filesystem facts. No hosted replay was dispatched by this
packet's writer.
