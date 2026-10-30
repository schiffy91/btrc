# Windows native target host (CX-P1-06, CX-P1-07)

`executor.py` is the `windows-native` executor of the shared target runner:
`src/tests/target_runner.py` freezes executor protocol 1 in its docstring
(`prepare(bundle_dir, label)`, `run(ExecutionRequest) -> ExecutionResult`,
`close()`), and its registry imports this module and finds
`WindowsNativeExecutor` through `TARGET_EXECUTORS`. The runner builds a
bundle on Linux and runs it here:

```sh
nix develop --command python3 -m src.tests.target_runner --target windows-x86_64 --frontend both \
  --compile-only --btrcc bin/btrcc --output build/target-corpus/windows-x86_64
```

```powershell
python -m src.tests.target_runner --execute-bundle build/target-corpus/windows-x86_64/bundle --executor windows-native
```

`windows.yml`'s `target-corpus-build` and `target-corpus` jobs do exactly
this for `windows-x86_64` on `windows-latest` and `windows-aarch64` on
`windows-11-arm`, through both compilers, on every main-tier run; see
"The corpus lane" below.

`bundle.py` and `check.py` are the original spike: six PE executables (two C
fixtures and two corpus programs through both compilers) and 16 fixed
execution cases that `host-windows.yml` runs on both architectures.

## Admission (`prepare`)

The executor reads only `bundle.json` (`btrc.target-bundle/1`), which both
the runner and `bundle.py` write. It refuses:

- a bundle built for another `targets.toml` row than the `label` it is
  given, or a row that is not one of `bundle.TARGETS` (the two gnu rows);
- an architecture this hardware would only emulate: `IsWow64Process2`
  supplies the native machine, which must equal the row's PE machine, so an
  ARM64 bundle under x64 emulation is never ARM64 evidence;
- any built program whose artifact is not exactly `<program_id>.exe`, is not
  a regular file inside the bundle, resolves to another extension (a `.cmd`
  or `.bat` launcher behind a link), lacks a SHA-256, or whose bytes do not
  match that digest and the row's PE machine.

Every built program is copied into a private staging directory and opened
with a handle that shares only reading: until `close`, no process can write,
replace or delete the copy (`CreateProcessW`'s own open of the image needs
only shared reading). The digest and PE machine are checked on the bytes read
through that handle, so the bytes checked are the bytes every run launches;
the bundle directory is never read again. Programs the bundle records as
failed, restricted or missing are not staged. Admission is atomic: any
refusal removes the new staging directory and keeps the previously admitted
bundle, if any.

An optional `companion` record contains exactly `artifact` and `sha256`.
Its name must be the primary name plus `.btrc-supervisor.exe`. The executor
copies it beside the staged primary and applies the same read-only hold,
digest and PE-machine checks. Any companion failure rejects the new bundle;
`close` releases both images. This stages an unpackaged pair, not an MSIX package.

After admission the runner asks `granted_capabilities()` which
`BTRC_TEST_REQUIRES` host capabilities the programs get here. The executor
answers `loopback-listener` when this host opens an IPv4 loopback listener,
probed as the runner's local executor probes its own host; a Job Object does
not restrict sockets, so the answer holds for every run.

## Launch and outcome (`run`)

Each request creates a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`.
Assigning an already running target after `Popen` would leave a window in
which it could spawn an unowned child, so `Popen` starts a Python launch gate
(this file with `--gate`) waiting on a uniquely named event; the executor
assigns the gate to the job before releasing the event, and only then does
the gate create the program. The program and its descendants inherit the
job; breakaway is not enabled. A failure to assign kills the unreleased gate.
The gate uses the base interpreter rather than a venv redirector and sets
inherited error-mode flags that suppress system, GP-fault and open-file
dialogs. Gate and program start detached in new process groups, and the gate
forwards all three standard handles explicitly.

The outcome comes only from the operating system:

- **Exit status and crashes.** The gate exits with the program's full 32-bit
  status, and the executor reads the gate's process exit code. Known crash
  NTSTATUS values map to a POSIX signal number, keeping the original value in
  `provenance.ntstatus` (an application that calls `ExitProcess` with a crash
  code is indistinguishable from that crash). Ordinary exits 124 and 137 are
  never timeouts.
- **Deadline.** Only the executor's own deadline (which includes setup) sets
  `timed_out`; `TerminateJobObject` then ends the whole tree before the pipes
  drain. A normal return also terminates remaining descendants, and the job's
  accounting must reach zero active processes within 10 s or the run is an
  infrastructure error.
- **Launch failure.** The gate is the job's first process. If the job's
  accounting (`TotalProcesses`) shows that no second process ever started,
  the program never launched: that is an infrastructure error carrying the
  gate's own stderr (it reports `CreateProcessW` failures with their
  `winerror` and `errno`), never a program outcome.

No file decides anything. The gate writes no status or error marker; the
request and staged stdin sit in a control directory inside the staging root,
neither in nor beside the program's fresh, empty cwd (its name contains
spaces and a Greek lambda), and nothing reads them back after launch. A
program that overwrites every file it can find still gets its own exit
status. Only the request's environment overrides are serialized, merged
case-insensitively. Both pipes drain concurrently with a 1 MiB limit per
stream; overflow is an infrastructure failure, never a truncated result.
Directories are removed with a read-only retry, so a program that leaves a
read-only file behind does not leak its cwd; a removal that still fails is
recorded in `provenance.cleanup_warnings` without discarding the result.

`provenance` names the executor, a device class (the processor model and
architecture, never a host name), the Windows build and edition, and the
bundle's toolchain.

This harness runs trusted repository programs under the runner's own user:
the staging handle, private directories and OS-derived outcome address
accidental interference, not a hostile same-user sandbox.

## The corpus lane

`windows.yml` (planned by `ci/tiers.toml`) runs it in the main, extended and
release tiers, and on a pull request that touches a Windows provider, this
directory, the runner or its applicability data:

1. `target-corpus-build` (Ubuntu, the pinned dev shell) builds `bin/btrcc`,
   then `src.tests.target_runner --compile-only --frontend both` for
   `windows-x86_64` and `windows-aarch64` with zig 0.16.0 and the strict C11
   flags. Each bundle (`bundle.json` and the executables) is an artifact; the
   compile-only reports and the C of every program that failed to build are
   another.
2. `target-corpus` runs on `windows-latest` (x64; Windows Server, a stand-in
   for the Windows 11 x64 slice) and `windows-11-arm` (ARM64) with a native
   Python of the runner's architecture. `--execute-bundle` admits the bundle
   only for this checkout's revision, goldens and request pins, then runs
   every program serially through this executor. The step summary carries
   the per-frontend passed/failed/restricted/missing counts and every
   failure; the `target-corpus-run-<target>` artifact keeps each program's
   streams and JSON, `target-run.json`, `junit.xml` and `ledger.jsonl` (the
   `TargetRunAdapter` records).

Both rows report only until the triaged failures are fixed: the job shows
red without failing the run.

## The spike bundle (`bundle.py`, `check.py`)

```sh
nix develop --command make NIX= btrcc
nix develop --command python3 -m tools.target_hosts.windows.bundle --record-compiler-provenance bin/btrcc.provenance.json
nix develop --command python3 -m tools.target_hosts.windows.bundle --target windows-x86_64 --output build/windows-host-x64
```

```powershell
python -m tools.target_hosts.windows.check --bundle build/windows-host-x64 --report build/windows-host-x64-results.json --runner windows-latest
```

The compiler receipt binds the binary's SHA-256, the full build-source
revision and a digest of the tracked compiler, spec, runtime, stdlib and
generator inputs; bundle construction refuses a mismatch or dirty compiler
inputs. `bundle.py` writes `bundle.json` for the executor and `manifest.json`
for the 16 acceptance cases: NUL and non-UTF-8 streams, 256 KiB binary stdin,
argv quoting, environment, the isolated cwd, exits 3/124/137, a raised access
violation, deadline expiry and a three-generation process tree (both on
expiry and on a normal return while descendants hold the pipes; each observed
PID is then checked dead). `check.py` copies the bundle to a path with spaces
and a Greek lambda, admits it for its own row, recomputes every golden from
this checkout, and records each case; any failure leaves `complete=false`.

## Validation

```sh
nix develop --command python3 -m pytest -p src.tests.conftest tools/target_hosts/windows/test_executor.py -q -rs
nix develop --command python3 -m pytest src/tests/python/test_target_runner.py -q
```

`test_executor.py` uses fake transports and POSIX process groups as stand-ins
for the Windows APIs; none of it is native Windows evidence. Native evidence
comes from `host-windows.yml` (the spike's 16 cases) and `windows.yml`'s
corpus lane.
