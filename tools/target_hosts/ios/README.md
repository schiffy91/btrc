# iOS simulator target host (CX-P1-04, CX-P1-08)

The `ios-simulator` executor runs a target-runner bundle for the
`ios-aarch64-simulator` row on a booted iOS simulator. It conforms to executor
protocol 1, which `src/tests/target_runner.py` freezes, and the runner finds it
through `TARGET_EXECUTORS` in `executor.py`:

```sh
python3 -m src.tests.target_runner --target ios-aarch64-simulator --frontend both \
  --compile-only --btrcc bin/btrcc --output build/target-corpus/build
python3 -m src.tests.target_runner --execute-bundle build/target-corpus/build/bundle \
  --executor ios-simulator --executor-option device_class=iphone --output build/target-corpus/run
```

Simulator results are never physical-device evidence (D8), and the newest
installed runtime is not the iOS 17 floor (MAC-P1-02).

## Contents

- `executor.py`: `IOSSimulatorExecutor`, the protocol-1 executor. Options
  (`--executor-option NAME=VALUE`): `device_class` (`iphone` or `ipad`),
  `runtime` (an iOS version prefix or runtime identifier; default the newest
  available at or above 17.0), `launch_timeout_s` (60), `warmup_timeout_s`
  (600) and `diagnostics` (a directory for host observations when booting
  fails).
- `supervisor.c`: the strict C11/POSIX program that runs inside the simulator
  and starts each program under test.
- `simhost.py`: the CoreSimulator device: runtime and device selection, boot,
  boot status and shutdown, every simctl call bounded.
- `spike.py` and `fixtures/fixture.c`: twelve hand-written fixtures that
  qualify the executor on a real simulator (host-ios.yml).
- `test_executor.py`: portable tests. The supervisor and fixtures are built
  with the host's C compiler and run as local processes; only simctl's
  transport is replaced, so spawn, wait, deadline and group kill are real.

## How a program runs

`prepare(bundle_dir, label)` admits a `btrc.target-bundle/1` bundle built for
`ios-aarch64-simulator` only, on an arm64 Mac only (the arm64 simulator runs
natively on Apple silicon; anything else would be emulation). It copies every
built program into a private 0700 staging directory as a 0500 file, and the
staged bytes must match the bundle's SHA-256 and be an arm64 Mach-O whose
`LC_BUILD_VERSION` names the iOS simulator platform. It compiles
`supervisor.c` for the bundle's triple with Xcode's clang, boots the device,
and warms it: a probe spawn under `warmup_timeout_s`, then a self-test that
runs the supervisor as a child of itself. Admission is atomic.

Each `run(request)` checks the staged copy's digest again, then issues one
`simctl spawn <device> supervisor run <control> <deadline-ms> <cwd> <program>
<argument...>`, with the request's environment as `SIMCTL_CHILD_<name>`
(`SIMCTL_*` and `DYLD_*` names are refused). The supervisor:

1. opens the staged stdin and the stdout and stderr files in the run's control
   directory, and changes to the cwd: a fresh empty `work` directory beside the
   control directory (`isolated`), or the staged program's directory
   (`bundle`);
2. checks for a `cancel` file, so a launch the executor already withdrew never
   starts the program;
3. `posix_spawn`s the program in a new process group with default signal
   dispositions and an empty mask, and (on Darwin) only descriptors 0 to 2;
4. waits with `waitpid`, kills the program's whole group with SIGKILL at the
   deadline, and kills the group again after a normal return so no descendant
   outlives the run;
5. reports `started`, then `exit`, `signal` or `timeout` with the elapsed time,
   as lines on its own stdout.

The outcome is the supervisor's `waitpid` status. Its stdout reaches the
executor through simctl's pipe, which the program never holds, and simctl's
own exit status (the supervisor's) must be 0. A spawn that does not start the
program within `launch_timeout_s`, a supervisor that reports nothing by the
program's deadline plus 30 s, a malformed report, or a stream larger than
16 MiB raises `SimulatorError`; none of these becomes a program outcome. A
launch withdrawn before the program could have started (simctl never started
the supervisor, or the supervisor reported the cancel) is retried once in a
fresh run directory. The withdrawn directory keeps its `cancel` file until
`close()`, so a supervisor simctl starts late still never runs the program,
and `provenance["launch_retries"]` records the retry.

Programs that create a new session (`setsid`) leave the group the supervisor
kills; nothing in the corpus does that on this row today.

## History

Codex's first host (PR #34) linked a C wrapper into each fixture and read the
outcome from files that wrapper wrote, and launched app bundles for an app
mode. Its hosted runs failed on CoreSimulator latency rather than on the
fixtures: on macos-15 (Xcode 16.4, iOS 26.2), run 37567969350 passed all twelve
iPhone spawn fixtures and timed out the first app launch and the first iPad
identity; on xcode-27 (Xcode 27A266a), run 37579929097 timed out the very first
spawn after a cold boot at its 30 s launch deadline. The protocol-1 executor
keeps its device lifecycle and fixtures, moves the wrapper into a separate
supervisor process, takes the outcome from `waitpid`, and gives the first spawn
after boot its own long warm-up deadline.

App mode (an installed app on a fresh container, with `app_roots`) is not
implemented: corpus programs are plain executables, and an app needs the
entry adaptation CL-P1-21 owns and the host-entry encoding CX-P2-41 owns.

## Hosted evidence

`host-ios.yml` runs on one hosted macOS runner (`simulator`): the fixtures on
iPhone and iPad, then the whole corpus through both compilers on an iPhone,
whose step reports only until its failures are triaged. Its `portable` job
runs the portable tests on Linux. A lane workflow has no `ci/tiers.toml` rows;
folding it into the tiers is CL-R-39.

The first protocol-1 run, [39260417889](https://github.com/schiffy91/btrc/actions/runs/39260417889)
(xcode-27 image, Xcode 27A266a, iOS 27.0 24A434), passed all 13 fixture runs
on an iPhone 11 and an iPad Pro (12.9-inch, 4th generation) simulator. The
first spawn after each cold boot took 77 s and 239 s. After that, a launch
took a median of 0.2 s. The corpus results:

| frontend | passed | failed | restricted | missing |
| --- | ---: | ---: | ---: | ---: |
| reference | 1005 | 13 | 0 | 3 |
| selfhost | 1006 | 12 | 0 | 3 |

The failures had three causes:

- eleven programs per frontend reach the Process provider, which the iOS SDK
  refuses to compile (now restricted in `target-applicability.toml`);
- `stdlib/ApplicationDirectories.btrc` still expected iOS to be unsupported
  after CL-P1-16 gave it the Apple resolver (the test now expects it to
  resolve);
- one reference launch, which CoreSimulator did not start within 60 s (now
  retried once, as described above).

The three missing programs are the dispatching `@gpu` programs.

## Local checks

```sh
python3 -m pytest tools/target_hosts/ios/test_executor.py -q
ruff check tools/target_hosts/ios && ruff format --check tools/target_hosts/ios
```

These never touch a simulator.
