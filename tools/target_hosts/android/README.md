# Android target host (CX-P1-05, CX-P1-09)

`executor.py` is the `android-emulator` executor of the target runner's frozen
protocol 1 (`src/tests/target_runner.py`): `prepare(bundle_dir, label)`
admits a `bundle.json` for `android-x86_64` or `android-aarch64`,
`run(ExecutionRequest)` runs one program through `adb shell`, and `close()`
removes what it staged and stops the emulator it booted. The whole corpus runs
through it on hosted CI (below). `app.py` keeps CX-P1-05's debug-signed,
Java-free NativeActivity app mode as a spike for C fixtures; `check.py` runs
the hand-written probe through both.

The local unit tests (`test_android_executor.py`, `test_android_host_versions.py`)
run the supervisor and the shell executor against this host's own shell, and
the app mode against a stateful fake. They are not Android execution evidence.
The hosted workflow uses KVM and retains native results separately; the
fixture matrix's history on API 29 and 36 is recorded below.

## The corpus on an emulator (CX-P1-09)

```sh
python -m src.tests.target_runner --target android-x86_64 --frontend both --compile-only --btrcc bin/btrcc --output build/target-corpus/android-x86_64
python -m src.tests.target_runner --execute-bundle build/target-corpus/android-x86_64/bundle --executor android-emulator \
  --executor-option boot=true --executor-option state=build/android-avds --executor-option api=29
```

The cross-build needs the pinned NDK (`ANDROID_NDK_HOME`); the run needs the
SDK (`ANDROID_SDK_ROOT`), KVM, and the NDK again, because the executor builds
its on-device supervisor (`supervisor.c`) for the bundle's row. Options:
`sdk`, `ndk`, `serial` (an already running emulator), or `boot=true` with
`state`, `api` and `port` for an AVD the executor boots on its first
`prepare` and stops on `close`.

Admission refuses another row and any device whose primary ABI is not the
row's: an `android-aarch64` bundle on an x86_64 image would run under binary
translation, which is emulation, not evidence. No hosted runner executes
`android-aarch64` natively, so CI builds it compile-only. Every built program
is copied, checked against its SHA-256, pushed once to a fresh
`/data/local/tmp/btrc-<random>/programs`, and checked again there with the
device's `sha256sum`; a failure removes the directory and leaves the executor
as it was. The executor grants `loopback-listener` when the supervisor's
`--probe-loopback` binds, connects and accepts on 127.0.0.1 on the device.

Each run is one `adb shell -T` command (shell protocol v2, which `prepare`
requires: raw stdout and stderr streams and the remote exit status). It creates
the run's fresh cwd under `runs/`, re-checks the staged supervisor's and
program's digests, and execs the supervisor. Nothing of an earlier run is
alive by then, so the checked bytes are the launched bytes. The supervisor
starts the program in a new session from that cwd, with its stdin (a file
staged under `control/`, or `/dev/null`), the request's environment overrides
and arguments. The program writes stdout straight to adb's stream; its stderr
goes through a pipe the supervisor relays. At the deadline the supervisor kills
the program's process group; when the program ends it kills every remaining
descendant (it is a child subreaper, so a descendant that leaves the group is
re-parented to it rather than escaping), waits for the relayed pipe's end of
file, and appends one status line from `waitpid` to stderr:
`BTRC-ANDROID-SUPERVISOR/1 exit|signal|timeout VALUE DURATION_US`.

The program cannot decide its outcome. Every byte it writes to stderr precedes
the status line, it never holds adb's stderr stream, and the supervisor is not
dumpable, so the program (the same `shell` user) can neither open
`/proc/<supervisor>/fd` nor trace it. A program that kills the supervisor ends
the adb command with a nonzero status and no status line, which the executor
raises as an infrastructure error, as it does a launch error, a digest
mismatch before launch, a transport failure or adb outliving the deadline by
30 seconds. After any of those it kills every device process whose cwd or
command line lies in its directory. The run's cwd and staged stdin are removed
after every run; a removal failure is a `cleanup_warnings` entry in the
result's provenance, which also names the executor, the device model and
emulator serial, the build fingerprint, the ABI, API, AVD name, page size and
the supervisor's digest, never a host or user name.

## Versions and setup

`nix/platforms.nix` is the sole SDK/NDK version source. `SDKVersions` reads its
literal pins, emits the hosted runner's sdkmanager package list, derives the
cache key, and verifies installed tool revisions. The packet pins Gradle
9.6.0 (official wrapper and distribution SHA-256), AGP 9.4.0, JDK 17, minSdk
29, and compile/targetSdk 36. The build selects the pinned NDK and build-tools
through Gradle properties rather than relying on AGP defaults.

For a local Linux workstation with the necessary kernel support:

```sh
export BTRC_TEST_RUNNER=linux-devcontainer
nix develop .#platforms --command true
nix develop .#platforms --command bash -c 'python3 -m tools.target_hosts.android.sdk verify --sdk "$ANDROID_SDK_ROOT"'
```

Inside that shell use the following commands directly. Hosted CI uses its SDK
tools and JDK 17; it must not enter `.#platforms`, whose closure
is about 17.75 GB.

Print the exact sdkmanager package names and the SDK/AVD cache key:

```sh
python3 -m tools.target_hosts.android.sdk packages
python3 -m tools.target_hosts.android.sdk cache-key
python3 -m tools.target_hosts.android.sdk verify --sdk "$ANDROID_SDK_ROOT"
```

`emulator` and `platform-tools` have unversioned sdkmanager package names.
Their installed revisions must still match the pins; `verify` rejects newer
or older revisions. If Google's current packages drift, the integrator must
install the exact Linux archives and checksums in `nix/android-repo-overlay.json`,
not relax the check. API 29/36 images use `google_apis;x86_64`. No x86_64
16 KiB image is invented: API 36's pinned 16 KiB arm64 image remains MAC-P1-03.
Platform and system-image package revisions are not pinned independently:
verification checks their API-specific payloads exist, not their package
revision. The package-list unit check covers the SDK helper, not a workflow's
installation commands. Checking that the eventual workflow consumes
`sdk packages` and runs `sdk verify` remains part of the workflow REQUEST.

This cloud environment's full `.#platforms` realization failed because
`ncurses-abi5-compat` invokes an i386 Bash binary unsupported by its kernel
(`Exec format error`). The pinned NDK component was realized separately,
allowing real x86_64 and arm64 shell/shared-library builds and ELF inspection.
The x86_64 debug APK was also packaged successfully with the pinned SDK
archives and JDK 17; Gradle used the environment's existing network proxy.
That fallback does not establish that the complete platforms shell works or
that the APK executes on Android.

## Build and execute

Build x86_64 shell fixtures and the NativeActivity `.so` without an emulator:

```sh
python3 -m tools.target_hosts.android.build --output build/android-host-x64 --native-only
```

Build the arm64 pair, for compile-only coverage on an x86_64 host:

```sh
python3 -m tools.target_hosts.android.build --output build/android-host-arm64 --abi arm64-v8a --native-only
```

Package the x86_64 app with the pinned wrapper:

```sh
python3 -m tools.target_hosts.android.build --output build/android-host-x64 --app
```

`ANDROID_NDK_HOME` supplies the NDK, or use `--ndk`. The shared library is
linked with `-z max-page-size=16384`; every ELF LOAD alignment is inspected
with `llvm-readelf -lW` and saved as `load-segments.txt`. Alignment is build
evidence, not execution on a 16 KiB system. `bundle.json` admits the probe
to the shell executor, `programs.json` (written only with the APK) indexes the
app mode, and `toolchain.json` carries the ABI, NDK revision and clang target.

Create the API 29 AVD or smoke-test its boot on a KVM runner:

```sh
python3 -m tools.target_hosts.android.avd create --state build/android-avds --api 29
python3 -m tools.target_hosts.android.avd smoke --state build/android-avds --api 29
```

Run all fixtures in both built modes and stop the emulator afterward:

```sh
python3 -m tools.target_hosts.android.check --boot --state build/android-avds --api 29 --bundle build/android-host-x64 --output build/android-api29.json
python3 -m tools.target_hosts.android.check --boot --state build/android-avds --api 36 --bundle build/android-host-x64 --output build/android-api36.json
```

Use `--serial emulator-<even-port>` to select an independent emulator. Without
`--boot`, the check uses an already running emulator. `--save-snapshot` saves
a clean `btrc-clean` snapshot before fixtures. Cache the state directory using
the version cache key, runner OS, API and device profile. No manager terminates
an emulator it did not launch.

The fixture cases cover stdout, stderr, exits 3/124/137, abort, deliberate
SIGKILL, timeout, 256 KiB on
each stream, quoting/empty argv, environment, binary stdin and isolated cwd.
The cwd case runs twice to reject accidental state reuse. Reports contain
byte counts and SHA-256 digests, exit/signal/timeout results, boot/page-size
data, and app install/launch durations. Emulator results are stand-in evidence.

## Transport and limits

Shell runs are the protocol-1 executor's, described above: the supervisor's
status line keeps deliberate exits such as 124/137 distinct from signals and
timeouts. The adb client's stdin is `/dev/null` for a launch, so it cannot
consume the invoking terminal's input.

The app uses `hasCode=false`, loads `libbtrcprogram.so`, and calls
`android_main`. A worker forks a child that reads a length-delimited request,
redirects streams under `internalDataPath`, and calls the fixture entry
renamed by `-Dmain=btrc_program_main`. Its parent records `waitpid` status,
including signals. This process boundary is a spike for C fixtures; its
post-fork behavior is not a claim of JNI/ART or arbitrary threaded-program
safety. Those require the later Android host/interop contract.

App request writes and file reads use `adb shell -T` with shell protocol v2,
one explicit quoting pass, separate stdout/stderr and the remote exit status.
Raw `exec-in`/`exec-out` return success after a successful connection and merge
error output; they cannot be used to infer whether a status file exists.
The app writes `signal=0` on a normal exit before publishing its atomic exit
marker. Missing status is an explicit pending result; failed reads and malformed
status values are infrastructure errors. The host-shell regression demonstrates
the previous double-quoting and missing-file failures but does not exercise
Android `run-as`, adb itself or NativeActivity.

Each app run uninstalls/reinstalls the fixture package before launch. Timeout
force-stops the app and polls `pidof` for at most two seconds before uninstall. Status
polls are bounded by the remaining program deadline; infrastructure failures
also force-stop and uninstall in cleanup. Only
`cwd_policy="isolated"` is supported until CL-P1-17 specifies other policies.
Request strings are NUL-free; the binary stdin stream has no such restriction.
The entry rename is tested on hand-written C, not btrc-emitted C; integration
must request CL-P1-21 if it needs a compiler entry-symbol option.
An initial uninstall failure is tolerated only when a successful package-list
query proves the package is absent; a still-installed package fails before
`install -r` can preserve stale success markers. Cleanup attempts both force-stop
and uninstall, including a failed installation, and attaches cleanup errors to
the original failure. A cleanup error after an otherwise successful fixture
remains a host failure.
The app child prepares its streams, arguments and environment, atomically
publishes `ready`, then waits for the host's `start` acknowledgement before
calling fixture code. The host allows 30 seconds for launch readiness, then
starts the independent requested execution budget and acknowledges. An
unacknowledged child exits after its own bounded wait. Launch-command and
ready timings are recorded separately. It does not use `-W`: that option waits
for a displayed activity, which a short fixture can finish before ever
producing. Terminal status, bounded polling and cleanup remain required.
Fixture checks remain active under optimized Python (`python -O`). The app
mode's harness files still share the fixture's data directory; the shell
executor keeps its control files out of the program's cwd.

## Verification and integrator handoff

```sh
nix develop --command python3 -m pytest src/tests/python/test_android_host_versions.py -q -rs
```

The workflow now exists at
[host-android.yml](../../../.github/workflows/host-android.yml). It installs the
emitted SDK package list, verifies revisions, enables KVM, builds the x86_64 app
and arm64 compile-only artifacts, and runs both API checks. It retains JSON
reports, emulator logs and LOAD tables even on failure. License acceptance
preserves sdkmanager’s exit status when its finite input consumption stops the
answer producer; the workflow regression checks both success and failure.
The October 7 refresh onto main passed all 56 local transport/version tests
before and after the merge, plus changed-file lint/format checks. No missing
emulator evidence is represented as passed or skipped unit coverage.
Acceptance remains open until both emulator matrices actually execute and the
run artifacts include LOAD tables, boot/install/launch timings and fixture
results. Previously reported cross-build and APK packaging success is historical
build evidence, not a revalidated result of the transport repair.


At revision `97a2a76a`, [hosted run 37557518213](https://github.com/schiffy91/btrc/actions/runs/37557518213)
passed all 28 shell/NativeActivity fixtures on API 36 (4 KiB pages). API 29
booted and completed its shell phase, but its first APK install failed because
the package service was unavailable; cleanup also could not reach the activity
service. This is not a passing API 29 result or a 16 KiB qualification.

The checker now retains completed fixture rows, the failing case/stage and
cleanup errors in its JSON report. Before closing an owned failed emulator, it
captures bounded logcat, properties and service-list diagnostics. Local
transport/workflow tests passed (139 tests). The next
[hosted run 37560687135](https://github.com/schiffy91/btrc/actions/runs/37560687135)
reached 25/28 API 29 cases, including every shell case and eleven app cases.
Its `cwd` app reached `onCreate`, `onResume`, and `onDestroy` in under one second,
but `am start -W` timed out waiting for a displayed frame. The launcher now
uses the native result protocol independently of display acknowledgement;
its regression models completion before the first displayed frame. The new
head still needs both emulator matrices. The earlier unavailable-service
failure remains recorded; this later failure is not evidence of its cause.

The `f1cbf0db` [run 37563205491](https://github.com/schiffy91/btrc/actions/runs/37563205491)
passed all 28 API 29 cases. API 36 reached 21 cases before its deliberate
one-second timeout expired during activity startup, without the fixture's
`started` output. The ready/start handshake separates that startup latency
from the execution deadline; the one-second fixture limit stays unchanged.
This repair requires a new complete two-API run.

At `68c7b553`, [run 37564454274](https://github.com/schiffy91/btrc/actions/runs/37564454274)
passed all 56 cases across API 29 and 36. The combined candidate's
[run 37570754359](https://github.com/schiffy91/btrc/actions/runs/37570754359)
then passed API 29 but failed API 36's large-output app after 22 successful
checks. Logcat records NativeActivity recreation in the same process and the
old worker finishing an activity whose native glue had already been destroyed.
The previous report omitted the failing result; it now retains its stream byte
counts/hashes, status, signal and timing separately from successful rows.

Fixture execution is now owned by the process across activity recreation.
The worker copies its input directory, runs only once, and finishes only the
currently registered live activity. A recreated activity after completion
observes the same terminal result without reopening or truncating output files.
The lifecycle regression compiles the actual C host against a small native-glue
simulator, using real threads, fork and files: it destroys the first activity
while the fixture is running, recreates it before completion, and recreates it
again afterwards. The original host fails by finishing a retired activity;
the repair preserves one fixture invocation and complete output. This local
simulation does not replace API 29/36 emulator qualification, which must pass
again with the unchanged execution deadlines and exact stream assertions.
