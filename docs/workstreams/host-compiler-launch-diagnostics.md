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

Source and tests are prepared; execution is pending. Existing harness-selection
checks will establish the unchanged baseline. New controlled cases exercise
real missing-wrapper/parent launches, POSIX missing-interpreter launches, intact
path ambiguity, unrelated failures, bounded malformed headers, special files,
symlink loops and parent-link traversal. Windows tests retain filesystem facts
for the POSIX-only shebang case without claiming a native shebang execution.
No additional skip is introduced. A real child pytest session must retain the
original failing test identity and result through the actual report hook and
SkipLedger. Existing scheduling/report serialization regressions are required
as a composition check. No hosted replay has been dispatched for this packet.
