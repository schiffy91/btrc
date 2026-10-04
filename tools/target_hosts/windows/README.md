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
nix develop --command python3 -m tools.target_hosts.windows.bundle --target windows-x86_64 --output build/windows-host-x64
nix develop --command python3 -m tools.target_hosts.windows.bundle --target windows-aarch64 --output build/windows-host-arm64
```

`--btrcc /absolute/path/to/btrcc` selects a separately built compiler. Both
bundles use `zig cc` with the existing Windows workflow's exact strict flags:
`-std=c11 -O2 -Wall -Wextra -Werror -pedantic`, the Windows runtime include
directory and forced `btrc_win_compat.h`, and `-lm`. Targets are
`x86_64-windows-gnu` and `aarch64-windows-gnu`.

Each bundle contains six PE executables: two strict C11 fixtures and the
existing `BracesInCodeGen` and `PathWindowsLexical` corpus programs compiled
through both Python and self-hosted frontends with explicit `--target`.
No corpus program is edited. The manifest records the source revision,
self-hosted compiler digest, Zig version, flags, executable digests, PE
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
characters. Byte streams remain bytes: fixtures cover NUL and non-UTF-8
output, 256 KiB binary stdin, arguments with quoting/empty/trailing-backslash
cases, environment, working directory, ordinary exits 3/124/137, a real
access violation, deadline expiry, and a three-generation process tree.
The tree also has a normal-return case: its parent waits until its grandchild
is running, then returns while both descendants still hold the output pipes.
The two corpus programs use an explicit CRLF-to-LF stdout comparison, matching
the existing Windows workflow's newline policy. Reports retain raw stream
digests alongside outcomes, duration and provenance; they never silently
normalize fixture streams.

## Process ownership and the assignment race

Each request creates a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Assigning an already running target
after `Popen` normally leaves a window in which that target can spawn an
unowned child. Here `Popen` starts a Python launch gate waiting on a uniquely
named event. The host assigns the gate to the job before releasing the event;
only then can the gate create the target. The target and descendants inherit
the job, and breakaway is not enabled. A failure to assign kills the unreleased
gate. Job handles are not inherited by the gate or target.

Timeouts use `TerminateJobObject`, drain the captured pipes, and query job
accounting until no active processes remain. Normal returns also terminate
remaining descendants: polling the atomic target-status file distinguishes a
returned target from descendants that still hold its pipes open. The deadline
includes setup time. Stdin uses a binary temporary file, avoiding Windows
`communicate`'s synchronous stdin write blocking beyond that deadline.
Handles close before the working directory is removed.
The tree fixture prints the PIDs of its parent, child and grandchild; the
checker requires all three generations, verifies job accounting is empty,
then independently checks that each observed PID is dead. This is an
execution assertion, not evidence supplied by a portable mock.

The gate writes a status file after the target returns, preserving the full
32-bit exit status. Missing status is an infrastructure error. Known NTSTATUS
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

The portable suite exercises admission failures, binary transport, launch
ordering, timeout cleanup, normal and crash statuses, and the tree-evidence
checker using a fake transport. It does not exercise Windows APIs.
Two portable tests also create actual POSIX descendants holding inherited
pipes to exercise normal-return and error cleanup; these remain stand-in
transport checks, not Windows process evidence.

In the Linux cloud container, both architecture bundles compiled successfully:
12 PE executables, including four Python and four self-hosted corpus outputs.
All PE machine checks passed. Native execution, actual Job Object behavior,
tree cleanup and corpus golden matches remain unverified until hosted Windows
runs complete. No Wine or Linux mock result is counted as native evidence.

The user's explicit prohibition on editing workflow files leaves
`host-windows.yml` absent. The draft PR contains an integrator request for the
Linux build and native Windows matrix, its exact commands, artifact handoff,
contract rows and skip-report handling. None of the packet's native runtime
acceptance boxes are marked complete solely from cross-compilation.
