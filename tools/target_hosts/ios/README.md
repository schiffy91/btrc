# iOS simulator test-host spike (CX-P1-04)

This standalone host implements the proposed CL-P1-17 executor shape for
hand-written strict C11 fixtures. It is not integrated with the compiler's target
runner, and no simulator result is claimed until the hosted commands below run.
The local tests execute real C processes while substituting only the simctl
transport; their provenance says `not-ios`. Local artifacts are explicitly
branded `local-host-check-only` and rejected by simulator `prepare`.

## Contents and limits

- `simhost.py`: newest available iOS runtime at or above 17.0, named
  `btrc-host-iphone` / `btrc-host-ipad` devices, boot and bootstatus, explicit
  erase on `IOSSimulatorHost.prepare(erase=True)`, shutdown only when this
  instance booted the device. An already booted matching device remains booted.
- `executor.py`: `prepare(bundle_dir, label)`, `run(ExecutionRequest)` and
  `close()`, with CL-P1-17's documented request/result fields. Only
  `ios-aarch64-simulator` is accepted. No registry or runner-core edit is made.
- `app/`: strict C11/POSIX main wrapper and Info.plist declaring minimum iOS
  17.0, `UIDeviceFamily [1,2]` and an ad-hoc-signed simulator executable.
- `fixtures/fixture.c`: twelve separately built programs for stdout, stderr,
  exit 3, abort, timeout ignoring TERM, 1 MiB output, argv, environment, cwd,
  binary stdin (including NUL/non-UTF-8 bytes), and ordinary exits 124/137
  (distinct from timeout and signal outcomes).
- `spike.py`: build and run CLI, byte/status assertions and machine-readable
  per-fixture outputs/provenance.
- `test_executor.py`: isolated local process and fake-inventory tests, outside
  the Claude-owned `src/tests` runner files.

`ExecutionRequest` contains program_id, argv (arguments after argv[0]), stdin
bytes, env, timeout_s and cwd_policy. Policies are `temp` (a fresh `work`
directory) and `bundle` (the installed app bundle, or the spawn binary's
directory). Unknown policies and unsafe environment keys are rejected before
launch. Program ids and artifact paths are validated; app identifiers must be
inside `dev.btrc.testhost` so the host cannot uninstall an unrelated app.

The C wrapper and fixture compile as separate units: only the fixture receives
`-Dmain=btrc_program_main`. The fixture entry signature is `int(int, char **)`.
This does not establish that arbitrary btrc-generated main functions can be
renamed safely. CL-P1-21 owns an entry-symbol option if that integration needs
one; no compiler workaround belongs here. Direct fixture calls to `exit` or
`_Exit` bypass the normal return-status wrapper and are not qualified by these
fixtures. Abrupt exit without a status is a host error, never a successful run.

This is a short-lived C test-host process launched as an app bundle, not the
later UIApplicationMain/scene host. Whether SpringBoard accepts short-lived
non-UIKit fixture launches with these exact semantics is part of the hosted
spike. No native GUI behavior is implemented here.

## Lifetime and output protocol

The host redirects stdin/stdout/stderr before publishing an atomic `process`
identity file. In app mode files are beneath the app data container's `tmp`
directory (under its HOME); in spawn mode they live in an isolated temporary
directory. No shell interpolation is used for paths, environment or arguments.
Every requested environment variable travels through `SIMCTL_CHILD_*` in the
real host; stale inherited child assignments are cleared between requests.

Normal return flushes byte streams and atomically publishes `exit_status`.
Handled fatal signals publish `signal_status` with async-signal-safe operations
and re-raise with the default disposition; abort is distinct from exit 3.
The parent waits for process disappearance as well as a terminal status.
Missing/malformed status, failed launch or unverified cleanup raises
SimulatorError instead of creating a passed ExecutionResult.

On timeout the parent signals the **simulator PID**, first TERM then KILL if
needed, and verifies that PID is gone. CoreSimulator shares the host kernel,
so these are direct host POSIX signals, not attempts to run a second `kill`
executable inside a stalled simulator. The wrapper attempts a private session;
when its group is isolated the signal targets that group. Only after native
child cleanup does the parent reap/kill a stuck local simctl client. Killing
the simctl client alone is not a timeout proof. **This spike accepts only
fixtures that do not create child processes.** Cleanup verification covers the
direct process only and is recorded as `cleanup_scope=direct-process-only`.
Group signaling is best effort; it does not verify surviving same-group children
after the leader exits, or descendants that create another session. Those
programs need additional containment/whole-group proof before full corpus
integration; none of the hand-written fixtures creates a child.
The C timeout fixture ignores TERM so tests prove the KILL path.

The execution deadline starts after the launch command returns; host commands
have separate bounded timeouts. Duration includes install/launch/collection.
`cold_launch_s` is the observed time from issuing spawn/launch until the first
process-identity observation, an upper bound influenced by simctl/poll latency;
`launch_command_s` is recorded separately. Neither is GPU presentation latency
or a benchmark. The result also records the simctl spawn client's status so the
hosted run can establish signal/exit propagation rather than guess it.

App mode checks for a previous fixture install, uninstalls it, installs the app,
uses `get_app_container` to find data and installed-bundle paths, launches with
`--terminate-running-process`, collects results and uninstalls in `finally`.
Each run creates a fresh result/work directory; successful cleanup never leaves
the fixture installed. Failure to uninstall remains a host failure. Local tests
also assert separate data containers across repeated app invocations; the
actual CoreSimulator container behavior still needs hosted validation.

## Local validation

From the repository root, using the pinned development shell:

```sh
export BTRC_TEST_RUNNER=linux-devcontainer
nix develop --command python3 -m unittest tools.target_hosts.ios.test_executor -v
nix develop --command ruff check tools/target_hosts/ios
nix develop --command ruff format --check tools/target_hosts/ios
nix develop --command git diff --check
```

The unit tests compile the host/fixtures with `cc -std=c11 -pedantic-errors
-Wall -Wextra -Werror` and run both transport modes against real local
processes. They test byte streams, exact arguments/environment, signal versus
normal exit, forced timeout cleanup, cwd, fresh-container cleanup and request
validation. Simulated inventory tests cover iPhone/iPad selection, unavailable
runtimes and preserving an already booted matching device. No tests skip or
claim Apple execution on Linux.

## Hosted run requested from Claude

The user's current instruction forbids Codex from editing CI workflow files,
including proposed workflow files. The PR requests `host-ios.yml` from the CI
owner instead. Until that request lands and runs, simulator evidence is pending.
This packet changes only `tools/target_hosts/ios/**`; no workflow, runner-core,
skip manifest or tier fragment is included.

The requested macos-15 job records `xcodebuild -version` and
`xcrun simctl list -j`, then uses an available Python >= 3.13 to run:

```sh
python3 -m tools.target_hosts.ios.spike build build/ios-testhost
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class iphone --mode spawn
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class iphone --mode app
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class ipad --mode spawn
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class ipad --mode app
```

Build uses `xcrun --sdk iphonesimulator clang -target
arm64-apple-ios17.0-simulator` and the strict C11 flags, then
`codesign --force --sign -` on each bundle. The matrix is twelve fixtures × two
modes × two device classes, 48 assertions; all modes must pass before the host
spike's runtime acceptance is ticked. A job should upload `build/ios-results`
even on failure, plus Xcode/runtime inventory and stdout/stderr of the CLI.
Unavailable iPad/runtime/tooling is a recorded blocker, not a substituted iPhone
pass. Stop at the first failing case in each run; summaries set complete=false
unless all twelve fixtures passed.

Use the existing pinned action revisions and lane trigger policy: push and PR
to main with paths for this directory and the workflow itself, plus dispatch.
Prefer serial commands above on one runner to avoid simulator-name collisions.
If the CI owner uses matrix pytest jobs instead, the matching `ci/tiers.toml`
fragment and expected-skip/report policy remain its responsibility. Regular
docs/lane CI does not discover these standalone tests or run a simulator.

The runner's Xcode version is stand-in provenance, not the owner's pinned
27A266a. Runtime selection chooses the newest installed available iOS >= 17;
it does not prove the iOS 17 deployment-floor runtime, which remains a separate
MAC-P1-02 question. iPhone and iPad results share the ios family and record
device_class. Physical devices and UI/IME/accessibility proof are outside this
spike and remain D8-gated.
