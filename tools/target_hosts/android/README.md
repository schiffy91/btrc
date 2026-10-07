# Android target-host spike (CX-P1-05)

This standalone host implements the proposed CL-P1-17 executor shape:
`prepare(bundle_dir, label)`, `run(ExecutionRequest) -> ExecutionResult`, and
`close()`. It builds hand-written strict C11 fixtures, with an adb shell mode
and a debug-signed, Java-free NativeActivity app mode. Compiler integration
belongs to CX-P1-09 after the target runner contract lands.

The local unit tests use a stateful fake and real host-shell subprocesses to
exercise quoting, binary file transfer, separate streams and command status.
They are not Android execution evidence. The cloud container has no `/dev/kvm`;
emulator boot, app installation, launch timings and on-device fixture results
remain unverified until the requested `host-android.yml` workflow runs.
No workflow file, including a proposed workflow, is added under the owner's
explicit instruction in the standing goal: "Never edit ... CI-workflow files."
The integrator's repository correction does not supersede that instruction;
the workflow remains a concrete REQUEST in the PR body.

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
evidence, not execution on a 16 KiB system. `programs.json` is the executor's
bundle index; `toolchain.json` carries the ABI, NDK revision and clang target.

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

Shell runs use an unpredictable subdirectory under `/data/local/tmp/btrc/`,
push stdin separately, preserve program stdout as bytes, and pull stderr
through a separate file. Arguments/environment are shell-quoted. A native
supervisor records the actual wait status and an explicit deadline flag,
keeping deliberate exits such as 124/137 distinct from signals and timeouts.
It kills the child process group at its deadline and cleans up descendants.
Toybox timeout remains an outer infrastructure guard; its failure or an adb
transport failure is an infrastructure error, not a program result.
The adb client receives empty stdin for commands that do not transfer a
payload, so it cannot consume the invoking terminal's input. An adb timeout
beyond the supervisor's outer guard is reported as an infrastructure error.
If the supervisor itself hangs, the outer guard does not prove that its
detached child process group has stopped; full failure-path process cleanup
remains a CX-P1-09 prerequisite.

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
The program deadline starts after `am start -W` returns; installation and launch
retain their own bounded transport deadlines and separately recorded timings.
Fixture checks remain active under optimized Python (`python -O`). Harness
files currently share the fixture cwd; separating control files from program
data and proving cleanup of arbitrary descendants belong to CX-P1-09.

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
transport/workflow tests pass (139 tests); a new emulator run is needed to
diagnose the API 29 service failure. No retry or skip masks that failure.
