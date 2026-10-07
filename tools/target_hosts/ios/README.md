# iOS simulator test-host spike (CX-P1-04)

This standalone host implements the proposed CL-P1-17 executor shape for
hand-written strict C11 fixtures. It is not integrated with the compiler's target
runner. The native results below qualify their recorded host and runtime only.
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
- `app/`: strict C11/POSIX fixture wrapper, a thin UIKit app launcher and
  Info.plist declaring minimum iOS 17.0, `UIDeviceFamily [1,2]` and an
  ad-hoc-signed simulator executable.
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

The first hosted run (`37554311440`, revision `ddc26d0a`) passed all twelve
iPhone spawn fixtures, then timed out launching the first iPhone app bundle.
The independent iPad steps passed twelve spawn and thirteen app executions:
37 of 50 scheduled executions passed overall, with thirteen iPhone app cases
uncompleted. Thus the timeout alone does not establish the plain-C entry point
as its cause. The revised app host uses UIKit’s normal launch lifecycle to avoid
waiting for the executor on the application launch thread. App mode now enters `UIApplicationMain` and returns from its launch delegate
while a worker runs the same C fixture wrapper. This lets UIKit complete its
launch handshake while the wrapper waits for the executor acknowledgement.
The worker exits the process after publishing the fixture result. Spawn mode
retains its ordinary C entry point; local transport tests retain their explicitly
branded non-iOS binaries. This small launcher does not qualify GUI or scene
behavior. The complete hosted simulator matrix remains required; the local native matrix
recorded below qualifies a different host/runtime combination.

The UIKit revision `3bd942dd` ran in
[37560529912](https://github.com/schiffy91/btrc/actions/runs/37560529912):
all thirteen iPhone app executions and two iPad spawn cases passed (15/50).
Other paths failed at process-identity or app-launch deadlines, sometimes with
simctl shutdown, terminate, uninstall or client-drain failures. These results
do not establish a runtime incompatibility or justify longer fixture deadlines.
On failure the spike now retains bounded read-only device, capacity, memory,
process and CoreSimulator service-log observations, including partial output
when a diagnostic times out. Summaries retain the failing invocation, stage
and original exception notes alongside cleanup errors.

Revision `532d4e45` completed two further native runs on 2026-10-07:

| Host and runtime | iPhone spawn | iPhone app | iPad spawn | iPad app |
| --- | --- | --- | --- | --- |
| Hosted run [37567969350](https://github.com/schiffy91/btrc/actions/runs/37567969350), Xcode 16.4 / iOS 26.2 (23C54) | 12 passed | first launch failed | first identity deadline failed | first launch failed |
| Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0; Xcode 27A266a / iOS 26.4.1 (23E254a) | 12 passed | 13 passed | 12 passed | 13 passed |

The local run passed all 50 executions using the same fixture binaries and
unchanged launch/execution deadlines. Every app invocation, including the
repeat in each class, proved a fresh data container. All four summaries were
complete without cleanup errors; both owned simulators were verified shut down.
Observed launch times ranged from 0.429 to 0.791 seconds. The retained manifest
records revision, Xcode/runtime, fixture hashes and per-case status/streams.

The hosted diagnostics record 7 GiB RAM and three CPUs, heavy memory
compression and basic `simctl list devices` queries exceeding their ten-second
diagnostic limit. Those observations support host pressure as a hypothesis;
they do not establish it as the sole cause. Hosted 26.2 reliability remains
unresolved. The local 26.4.1 pass does not qualify the iOS 17 runtime floor,
arbitrary descendants, compiler entry adaptation, physical devices or GUI
behavior. The results retain their existing `stand-in` provenance.

## Lifetime and output protocol

The host redirects stdin/stdout/stderr before publishing an atomic `process`
identity file. It then waits for the executor to acknowledge that identity with
a `start` file before invoking fixture code. A `cancel` file or removal of the
result directory aborts that wait; the wait itself is bounded at 30 seconds. In app mode files are beneath the app data container's `tmp`
directory (under its HOME); in spawn mode they live in an isolated temporary
directory. No shell interpolation is used for paths, environment or arguments.
Every requested environment variable travels through `SIMCTL_CHILD_*` in the
real host; stale inherited child assignments are cleared between requests.

Normal return flushes byte streams and atomically publishes `exit_status`.
Handled fatal signals (ABRT, TERM, INT, SEGV, BUS, ILL, FPE, TRAP, PIPE and SYS)
publish `signal_status` with async-signal-safe operations and re-raise with the
default disposition; abort is distinct from exit 3. A lock-free C11 atomic flag arbitrates terminal publication across UIKit
threads and the fixture worker. The winning signal handler publishes its result
and terminates the process; normal completion claims the same flag before
blocking signals on its own thread, publishing `exit_status` and closing the
signal descriptor. A late handler cannot publish a second terminal result. Uncatchable
SIGKILL and direct `exit`/`_Exit` still require a runner-core fallback before
full corpus integration; this spike reports a host error when no status exists.
The parent waits for process disappearance as well as a terminal status.
Missing/malformed status, failed launch or unverified cleanup raises
SimulatorError instead of creating a passed ExecutionResult.

On timeout the parent signals the **simulator PID**, first TERM then KILL if
needed, and verifies that PID is gone. CoreSimulator shares the host kernel,
so these are direct host POSIX signals, not attempts to run a second `kill`
executable inside a stalled simulator. The wrapper attempts a private session;
when its group is isolated the signal targets that group. Only after native
child cleanup does the parent reap/kill a stuck local simctl client. On a launch
failure it first cancels the C wrapper, polls for late identity publication for
up to three seconds, and rechecks identity after the launcher is reaped. Known
identity is retained across errors; cleanup diagnostics supplement the original
exception. Both launcher drain/reap attempts are bounded. Killing
the simctl client alone is not a timeout proof. **This spike accepts only
fixtures that do not create child processes.** Cleanup verification covers the
direct process only and is recorded as `cleanup_scope=direct-process-only`.
Group signaling is best effort; it does not verify surviving same-group children
after the leader exits, or descendants that create another session. Those
programs need additional containment/whole-group proof before full corpus
integration; none of the hand-written fixtures creates a child.
The C timeout fixture ignores TERM so tests prove the KILL path.

Launch has its own bounded 30-second deadline, measured from the spawn/launch
request, including xcrun/simctl startup. The execution deadline starts when the
executor first observes the native child identity and acknowledges execution;
it therefore excludes startup latency in **both** modes. The 0.5-second timeout
fixture still exercises short execution budgets after slow simulator startup.
Host commands and each compiler/codesign call also have bounded timeouts.
Duration includes install/launch/collection.
`cold_launch_s` is the observed time from issuing spawn/launch until the first
process-identity observation, an upper bound influenced by simctl/poll latency;
`launch_command_s` is recorded separately. Neither is GPU presentation latency
or a benchmark. The result also records the simctl spawn client's status so the
hosted run can establish signal/exit propagation rather than guess it. Raw simctl
stdout/stderr are retained in provenance, and error diagnostics include them.
For normal exits the spike requires simctl status to match the fixture exit;
for handled signals it accepts the POSIX negative signal or 128+signal forms.
An unexpected mapping fails and leaves diagnostics for the first hosted review.

App mode checks for a previous fixture install, uninstalls it, installs the app,
uses `get_app_container` to find data and installed-bundle paths, launches with
`--terminate-running-process`, collects results and uninstalls in `finally`.
Each run creates a fresh result/work directory and checks a persistent marker in
the installed data container before writing it. If uninstall/reinstall preserves
the previous marker, execution fails; a different temporary subdirectory alone
is not proof. The app-mode CLI repeats the stdout fixture after the full fixture
set, records the actual container path and marker absence, and writes separate
`stdout-repeat` evidence. Successful cleanup never leaves the fixture installed.
Termination and uninstall are attempted independently; cleanup failure is a host
failure, and an original execution error is preserved with cleanup notes. Local
regressions deliberately retain an old container to prove marker rejection.
Actual CoreSimulator container behavior still needs hosted validation.

## Local validation

The October 7 Mac check at `97f31e31` passed 23 local tests plus 36 subtests
using pytest; lint and format checks also passed. The test fixture resolves its
temporary root before bypassing `prepare`, matching production's canonical path
handling on macOS. The UIKit-launcher revision also passes all 23 tests and 36 subtests (11.32 s),
and all twelve app bundles compile and ad-hoc sign with the local simulator SDK.
These are local process/build results, not simulator execution evidence.


From the repository root, using the pinned development shell:

```sh
export BTRC_TEST_RUNNER=linux-devcontainer
nix develop --command python3 -m unittest tools.target_hosts.ios.test_executor -v
nix develop --command make NIX= test-unit
nix develop --command ruff check tools/target_hosts/ios
nix develop --command ruff format --check tools/target_hosts/ios
nix develop --command git diff --check
```

The unit tests compile the host/fixtures with `cc -std=c11 -pedantic-errors
-Wall -Wextra -Werror` and run both transport modes against real local
processes. They test byte streams, exact arguments/environment, signal versus
normal exit, forced timeout cleanup, cwd, fresh-container cleanup and request
validation. The delayed-launch regressions use distinct launcher and native
fixture processes: one delays startup beyond the execution budget, and another
publishes identity during launch-failure cleanup. Each independently checks
child disappearance. Additional tests cover raw launcher failure diagnostics,
bounded reap/exit races, cleanup error preservation, runtime-supported device
selection, and checks remaining active under `python3 -O`. Simulated inventory
tests cover iPhone/iPad selection, unavailable runtimes and preserving an already
booted matching device. No tests skip or
claim Apple execution on Linux.

## Hosted simulator qualification

The lane workflow now exists at
[host-ios.yml](../../../.github/workflows/host-ios.yml). The host directory
activates its simulator job. The workflow now uses the
standard `xcode-27` image, whose [published inventory](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)
includes Xcode 27A266a and iOS 27.0. This advances the hosted lane from its old
Xcode 16.4 stand-in to D21's pinned toolchain; it does not assert that changing
the image fixes the old runner's observed pressure. The image is currently a
public preview, and its native matrix must qualify before acceptance.

The job selects `/Applications/Xcode_27.app/Contents/Developer` through its
own `DEVELOPER_DIR`, verifies the exact Xcode build, and records the selected
simctl path, simulator SDK version and complete runtime inventory. A different
build fails before fixture compilation. It then uses Python 3.13 to run:

```sh
python3 -m unittest tools.target_hosts.ios.test_executor -v
python3 -m tools.target_hosts.ios.spike build build/ios-testhost
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class iphone --mode spawn
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class iphone --mode app
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class ipad --mode spawn
python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class ipad --mode app
```

Build uses `xcrun --sdk iphonesimulator clang -target
arm64-apple-ios17.0-simulator` and the strict C11 flags, then
`codesign --force --sign -` on each bundle. The matrix is twelve fixtures × two
modes × two device classes, plus one repeated stdout app run per class: 50
fixture executions. Checks use explicit exceptions and remain active under
`python3 -O`. All modes must pass before the host
spike's runtime acceptance is ticked. A job should upload `build/ios-results`
even on failure, plus Xcode/runtime inventory and stdout/stderr of the CLI.
Unavailable iPad/runtime/tooling is a recorded blocker, not a substituted iPhone
pass. Stop at the first failing case in each run; summaries set complete=false
unless every scheduled fixture (including the app-mode repeat) passed and
host cleanup succeeded.

Use the existing pinned action revisions and lane trigger policy: push and PR
to main with paths for this directory and the workflow itself, plus dispatch.
Prefer serial commands above on one runner to avoid simulator-name collisions.
If the CI owner uses matrix pytest jobs instead, the matching `ci/tiers.toml`
fragment and expected-skip/report policy remain its responsibility. Regular
docs/lane CI does not discover these standalone tests or run a simulator.

The hosted toolchain must match 27A266a. The execution results keep their
existing `stand-in` designation because hosted hardware and runtime coverage
are not the entire acceptance matrix. Runtime selection chooses the newest
installed available iOS >= 17; it does not prove the iOS 17 deployment-floor runtime, which remains a separate
MAC-P1-02 question. iPhone and iPad results share the ios family and record
device_class. Physical devices and UI/IME/accessibility proof are outside this
spike and remain D8-gated.


## Remaining integration requests

`REQUEST(CL-R-38)`: workflow implementation is present on current main;
execution of its local checks and all 50 native fixture runs remains the
acceptance requirement. Hosted results must identify the tested revision and
retain the native result artifacts before this request is closed.

`REQUEST(CL-P1-17)` / `REQUEST(CL-P1-21)`: before full corpus integration,
reconcile executor types, prove entry/exit handling for compiler-emitted C,
and qualify stronger child/process-group containment and PID ownership. Current
fixtures are trusted, do not create descendants, and cleanup remains explicitly
`direct-process-only`. The process file and host PID namespace are not a secure
sandbox; PID reuse and a forged initial identity need a stronger transport-level
ownership proof before arbitrary corpus programs are admitted. These limitations
are not solved by the delayed-launch regression or by green ordinary lane CI.


The host captures Xcode provenance before creating or booting its owned guest
and reuses that value in execution reports. This avoids launching `xcodebuild`
after simulator boot has consumed host capacity. The ordering regression
reproduced the old post-boot timeout through a controlled command transport;
it is not native simulator qualification. Toolchain failures occur before any
device mutation. Fixture binaries, timeouts, and the 50-invocation native matrix
are unchanged. The Xcode-27 hosted failure above remains historical evidence;
the reordered preparation still needs fresh hosted qualification.
