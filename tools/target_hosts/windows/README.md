# Windows native host spike (CX-P1-06)

This standalone spike exposes the proposed CL-P1-17 protocol:
`prepare(bundle_dir, label)`, `run(ExecutionRequest) -> ExecutionResult`, and
`close()`. Integration into the shared target runner is CX-P1-07 after that
contract is frozen. No shared runner, compiler, runtime, test corpus, or
workflow file changes are included here.

## Build a bounded bundle on Linux

Use the repository's pinned development shell and a freshly built self-hosted
compiler from the same source revision:

```sh
export BTRC_TEST_RUNNER=linux-devcontainer
nix develop --command make NIX= btrcc
nix develop --command python3 -m tools.target_hosts.windows.bundle --record-compiler-provenance bin/btrcc.provenance.json
nix develop --command python3 -m tools.target_hosts.windows.bundle --target windows-x86_64 --output build/windows-host-x64
nix develop --command python3 -m tools.target_hosts.windows.bundle --target windows-aarch64 --output build/windows-host-arm64
```

`--btrcc /absolute/path/to/btrcc --compiler-receipt /absolute/path/to/receipt.json`
selects a separately built compiler. If that binary is relocated outside its
checkout or installation tree, set `BTRC_HOME="$PWD/src"` in the source-matched
checkout so it can locate the grammar and standard library.
Record its receipt immediately after building
it from the stated checkout; never generate a receipt to relabel an unknown binary.
The receipt binds the binary SHA-256, full build-source revision and a digest of
tracked compiler/spec/runtime/stdlib/generator input contents. Bundle construction
requires both digests to match and verifies that the recorded source revision
exists and has the same compiler inputs as the current HEAD. The receipt records
tracked-tree and compiler-input dirty state; dirty compiler inputs are refused.
Tool-only branch changes may reuse a source-identical compiler. The source commit
must be available in the producer checkout (fetch it when reusing a separate build). This is retained build provenance,
not a cryptographic attestation of who performed the build. Both
bundles use `zig cc` with the existing Windows workflow's exact strict flags:
`-std=c11 -O2 -Wall -Wextra -Werror -pedantic`, the Windows runtime include
directory and forced `btrc_win_compat.h`, and `-lm`. Targets are
`x86_64-windows-gnu` and `aarch64-windows-gnu`.

Each bundle contains six PE executables: two strict C11 fixtures and the
existing `BracesInCodeGen` and `PathWindowsLexical` corpus programs compiled
through both Python and self-hosted frontends with explicit `--target`.
No corpus program is edited. The manifest records the source revision,
self-hosted compiler build receipt, Zig version, flags, executable digests, PE
machine values, and 16 execution cases with arguments, deadlines, expected
stdout/stderr digests and expected process outcomes.

## Execute on a native Windows runner

Keep the repository checkout available for the Python host tooling and
download the matching bundle. Python 3.13 or later is sufficient; the
native execution path uses only its standard library.

```powershell
python -m tools.target_hosts.windows.check --bundle build/windows-host-x64 --report build/windows-host-x64-results.json --label windows-latest
```

On `windows-11-arm`, use `windows-host-arm64` and a corresponding report
name. `IsWow64Process2` supplies the native hardware architecture, which must
match the bundle PE machine. An ARM64 bundle run under x64 emulation cannot
be accepted as ARM64 evidence. `windows-latest` is Windows Server 2025, a
stand-in for the Windows 11 x64 slice; ARM64 hosted runner availability still
needs confirmation.

The checker copies the bundle to a path containing spaces and a Greek lambda,
then runs every case from a different temporary working directory with those
characters. Admission requires the exact 16 unique case identities, including both
tree cases and all four corpus/frontend cases, their exact executable mappings, argv,
stdin, environment, deadlines, expected outcomes and evidence policies. Golden
digests are recomputed from the runner checkout, whose revision must match the
bundle. Empty, truncated or modified cases cannot yield a successful report.
Ordinary case failures retain an error row and the checker continues collecting
all remaining cases; any failure leaves `complete=false`. Admission failures and
interrupts abort while retaining the evidence already collected. Byte streams remain bytes: fixtures cover NUL and non-UTF-8
output, 256 KiB binary stdin, arguments with quoting/empty/trailing-backslash
cases, environment, working directory, ordinary exits 3/124/137, a raised
EXCEPTION_ACCESS_VIOLATION status (not a hardware memory fault), deadline expiry,
and a three-generation process tree.
The tree also has a normal-return case: its parent waits until its grandchild
is running, then returns while both descendants still hold the output pipes.
The two corpus programs use an explicit CRLF-to-LF stdout comparison, matching
the existing Windows workflow's newline policy. Reports retain raw stream
digests alongside outcomes, duration and provenance; they never silently
normalize fixture streams.

## Process ownership and the assignment race

Each request creates a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`. Assigning an already running target
after `Popen` normally leaves a window in which that target can spawn an
unowned child. Here `Popen` starts a Python launch gate waiting on a uniquely
named event. The host assigns the gate to the job before releasing the event;
only then can the gate create the target. The target and descendants inherit
the job, and breakaway is not enabled. A failure to assign kills the unreleased
gate. Job handles are not inherited by the gate or target. The gate uses the
base Python interpreter rather than a venv redirector, and sets inherited error
mode flags to suppress system/GP-fault/open-file dialogs for all target programs,
including corpus executables. Exact CreateProcessW failures retain winerror,
errno and message in an atomic error record, distinct from a target exit.

Timeouts use `TerminateJobObject`, drain the captured pipes, and query job
accounting until no active processes remain. Normal returns also terminate
remaining descendants: polling the gate process distinguishes its completion
from descendants that still hold its pipes open. The deadline
includes setup time. Stdin uses a binary temporary file, avoiding Windows
`communicate`'s synchronous stdin write blocking beyond that deadline.
Handles close before the working directory is removed. The target cwd starts
empty; request, stdin and status records live in a sibling control directory.
Only target environment overrides are serialized; merging is case-insensitive.
The gate and target start detached in new process groups, so the target
cannot signal the harness through its console. The gate explicitly forwards all
three standard handles to its target: detached Windows processes cannot rely on
console inheritance for the binary stdin file and stdout/stderr capture pipes.
Both pipes drain concurrently with a 1 MiB retained-byte limit per stream;
overflow is an infrastructure failure, never
a successful truncated digest. Failed temporary-directory removal is retained as
`provenance.cleanup_warnings` without discarding the completed result; Job Object
termination/accounting failures still fail execution.

Admission commits bundle state only after every check succeeds, and each run
rechecks the executable digest immediately before spawning. Program mappings
must be exactly `<program>.exe`; batch/cmd launchers are refused. This harness
runs trusted repository fixtures under the same Windows user: sibling control
files and repeated digests address accidental cwd collisions and stale artifacts,
not a hostile same-user sandbox or an atomic filesystem-to-CreateProcess guarantee.
The tree fixture prints the PIDs of its parent, child and grandchild; the
checker requires all three generations; the executor queries job accounting until empty,
then independently checks that each observed PID is dead. This is an
execution assertion, not evidence supplied by a portable mock.

The gate writes a completion marker after the target returns, then exits with
the full 32-bit target status. The parent reads the gate process exit code, never
a numeric status supplied by a cwd file. A missing marker is an infrastructure error. Known NTSTATUS
values map to signal-like results, and their original hexadecimal value is
retained. This is a Windows exit-code convention: an application deliberately
calling `ExitProcess` with a crash NTSTATUS is indistinguishable from that
crash code. Ordinary exits 124 and 137 are not classified as timeouts.
Only a host deadline expiry sets `timed_out`. Cleanup has a separate bounded
10-second allowance; a failure to empty the job raises an infrastructure
error rather than claiming a successful cleanup.

## Validation and remaining evidence

```sh
nix develop --command python3 -m pytest tools/target_hosts/windows/test_executor.py -q -rs
nix develop --command ruff check tools/target_hosts/windows
nix develop --command ruff format --check tools/target_hosts/windows
```

Build commands have finite deadlines; the Linux producer terminates the
compiler process group after success, failure or timeout before a bounded pipe
drain. Metadata subprocesses also have finite deadlines.

`test_executor.py` is collected by the `host-windows.yml` bundle job, not by
the shared unit shard. Invoke it explicitly for local changes; its builder/validator
roundtrip uses stubbed compiler effects and does not claim native execution.

The portable suite exercises admission failures, binary transport, launch
ordering, timeout cleanup, normal and crash statuses, and the tree-evidence
checker using a fake transport. It does not exercise Windows APIs.
Two portable tests also create actual POSIX descendants holding inherited
pipes to exercise normal-return and error cleanup; these remain stand-in
transport checks, not Windows process evidence. Their status/ready files publish
atomically and tests assert descendants are terminated (an exited Linux zombie
awaiting the host reaper is distinguished from a live process). Executor-clock
injection is local to the instance; tests do not replace process-global clocks.
Cleanup exceptions are suppressed only when this invocation itself raised a
primary error, never merely because its caller is handling another exception.

The integrator installed `host-windows.yml` in batch35. Its first run,
[37311381559](https://github.com/schiffy91/btrc/actions/runs/37311381559), verified
the original spike at merged revision `87727690`: both downloaded native reports
contain 16 passed, 0 failed, 0 skipped, including both tree cases and both corpus
programs through both compilers. x64 is hosted Windows Server 2025 stand-in
evidence; ARM64 ran natively on `windows-11-arm`. This baseline does not validate
subsequent hardening; that requires the follow-up PR's own host lane results.
No Wine or Linux mock result is counted as native Windows evidence.
