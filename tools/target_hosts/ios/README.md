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
  available at or above 17.0), `launch_timeout_s` (120), `warmup_timeout_s`
  (600) and `diagnostics` (a directory for host observations when booting
  fails).
- `supervisor.c`: the strict C11/POSIX program that runs inside the simulator
  and starts each program under test.
- `simhost.py`: the CoreSimulator device: runtime and device selection, boot,
  boot status and shutdown, every simctl call bounded.
- `fixtures/fixture.c`: twelve hand-written C11 fixtures compiled and exercised
  by `test_executor.py` against the supervisor.
- `test_executor.py`: portable tests. The supervisor and fixtures are built
  with the host's C compiler and run as local processes; only simctl's
  transport is replaced, so spawn, wait, deadline and group kill are real.
- `gui.py`: `GUIAppBuilder` and `GUIAppRunner`, for a BTRC GUI program as
  an app (see "GUI programs" below).
- `simhid.m`: the host's input injector for one booted simulator.
- `compute.py`: builds the `@gpu` compute runtime for the simulator row.

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

## GUI programs

A program that imports `Library.GUI` is an app on iOS, not an executable
`simctl spawn` can run: UIKit owns its process (src/stdlib/GUI/README.md,
the UIKit shim). `GUIAppBuilder.package` packs a linked program into a
bundle with the Info.plist a scene-based app needs (a launch screen, both
device families, more than one scene on a tablet) and an ad-hoc signature;
the program is linked with `-e _btrcUIKitMain` and wgpu-native's static
library (`GUIAppBuilder.link_flags`). `GUIAppRunner` installs it and runs it
one process at a time: `simctl launch` with the program's arguments, its
environment as `SIMCTL_CHILD_<name>`, and `BTRC_SHIM_OUTPUT` naming a
directory in the app's own container, where the program's thread leaves
what it printed and its result. A program that leaves no result crashed or
ran out of time, and the runner returns the simulator's last log lines of
it.

`simhid.m` sends real input to a booted simulator through SimulatorKit's
HID client, the one Xcode's own Simulator uses: a finger, a hardware
keyboard's keys, and on a tablet a mouse pointer, its button and its wheel.
It needs no window and none of the Mac's own pointer, keyboard or focus,
and works on a device booted with `simctl boot` alone. It serves a line
protocol on a local port (its header comment lists the requests), which
the conformance suite's probe speaks from inside the app. SimulatorKit is
a private framework of Xcode: the message layouts are the ones Xcode 27.2
(27B52) builds, and another Xcode may need them read again. A phone
simulator has no pointer; `simhid` says so for `HOVER`, `PDOWN` and
`SCROLL`.

`src/tests/python/ios_simulator_fixtures.py` puts these together for
tests: one device of each class made for the purpose (`btrc-ui-iphone`,
an iPhone 17 Pro Max; `btrc-ui-ipad`, an iPad Air 11-inch (M4)), one booted
at a time, where `BTRC_IOS_UI_DEVICES` asks for them. One app at a time
has its scene made a window there: when an app is launched, iPadOS 26 starts
every other app whose window shows on the stage, with no arguments, and a
test program started so runs beside the one under test. The fixtures
uninstall the last windowed app before another app runs, and the apps a
stopped run left behind when a device is next prepared:

```sh
BTRC_IOS_UI_DEVICES=iphone,ipad nix develop --command python3 -m pytest -q \
  src/tests/python/test_native_ui_conformance_ios.py src/tests/python/test_native_ui_ios_programs.py
```

## The compute runtime

Dispatching `@gpu` corpus programs link `libbtrc_gpu` over wgpu-native. The
simulator row has it when a run builds it and hands the target runner its
flags; without them those programs are reported missing, as before:

```sh
eval "$(python3 -m tools.target_hosts.ios.compute --wgpu-native DIR --output build/ios-compute)"
python3 -m src.tests.target_runner --target ios-aarch64-simulator --frontend both \
  --program 'gpu/*.btrc' --btrcc bin/btrcc --output build/target-corpus-gpu
```

`DIR` is wgpu-native's pinned simulator archive, extracted, with
`libwgpu_native.a` moved alone into `DIR/static` (beside the shared library
the linker would take that one, which a spawned program cannot find).

## Hosted evidence

`host-ios.yml` runs on one hosted macOS runner (`simulator`): the fixtures on
iPhone and iPad, then the whole corpus through both compilers on an iPhone,
whose step reports only until its failures are triaged. Its `portable` job
runs the portable tests on Linux. A lane workflow has no `.github/ci/tiers.toml` rows;
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

With those fixes, run [39274756389](https://github.com/schiffy91/btrc/actions/runs/39274756389)
passed the fixtures again and ran the corpus with no failure:

| frontend | passed | failed | restricted | missing |
| --- | ---: | ---: | ---: | ---: |
| reference | 1007 | 0 | 11 | 3 |
| selfhost | 1007 | 0 | 11 | 3 |

Its 2,014 launches took a median of 0.19 s (p95 0.42 s). One took 44 s,
shortly after boot, so the launch deadline is now 120 s, and provenance
separates `spawn_s` (until the supervisor ran) from `launch_s` (until the
program started).

## Local checks

```sh
python3 -m pytest tools/target_hosts/ios/test_executor.py -q
ruff check tools/target_hosts/ios && ruff format --check tools/target_hosts/ios
```

These never touch a simulator.
