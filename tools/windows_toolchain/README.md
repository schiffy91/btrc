# Windows ARM64 compiler and ABI evidence

These CX-P1-03 tools separate the GNU compiler route from the MSVC GPU ABI.
Linux can cross-build an ARM64 PE image and inspect it. Native bootstrap,
MSVC CRT execution and wgpu callback evidence require a Windows ARM64 runner.

## Pinned inputs

`pins.json` records the Zig 0.16.0 Windows ARM64 archive URL, size and SHA-256 from
`https://ziglang.org/download/index.json`. The Windows ARM64 ZIP digest is
`aee38316ee4111717900f45dd3130145c39289e105541d737eb8c5ed653c78ef`.
The wgpu-native 27.0.4.0 Windows ARM64 MSVC digest comes from
`nix/wgpu-native-prebuilt.nix` (CL-P1-02). Verify each downloaded archive before
extracting it. The installer must verify the Zig archive digest before adding
it to PATH; the helper validates its reported version against `pins.json`.
Linux uses the flake-pinned Zig, so no unused Linux archive pin is retained. The PowerShell probe
verifies the wgpu archive digest itself.

## Linux cross-build

From the repository root, in the pinned development shell:

```sh
python -m tools.windows_toolchain.arm64 cross --out build/windows-arm64-cross
python -m tools.windows_toolchain.arm64 pe --cross build/windows-arm64-cross/btrcc.exe --out build/windows-arm64-pe
```

The cross-build uses `cli/WindowsMain.btrc`, explicit
`aarch64-windows-gnu`, strict C11 and the existing Windows compatibility
header. `summary.json` records the source revision, Zig version, exact argv,
exit codes, PE machine `0xAA64`, artifact SHA-256 and `native_execution:
not-run`. Command stdout/stderr are retained beside the report. A Linux
cross-build is not bootstrap or Windows execution evidence.

## Native Windows ARM64

Windows commands use the integrated `tools.target_hosts.windows.executor.WindowsJob`
owner and its gated launch: assignment precedes target execution, cleanup kills
and drains the whole job, and file-backed captures survive inherited output
handles. Missing target executables retain the gate's structured launch error.
Linux commands reuse `bundle.run_build_command` and its process-group cleanup.
There is one Windows containment owner and no external-containment opt-in.
The target table, PE parsing and strict C flags also come from the shared host.

Use ARM64 Python 3.13 and native ARM64 PowerShell 7. Install the pinned ARM64
Windows Zig archive on PATH. Download the Linux cross-built compiler artifact
into a separate directory; the native command rejects an output path that
contains either the input executable or its provenance summary.

```powershell
python -m pip install '.[dev]'
python -m tools.windows_toolchain.arm64 native --cross cross/btrcc.exe --cross-summary cross/summary.json --out build/windows-arm64-native
pwsh -NoProfile -File tools/windows_toolchain/msvc_probe.ps1 -WgpuArchive downloads/wgpu-windows-aarch64-msvc-release.zip
```

The native command first validates the Linux cross summary's host, mode, source revision, binary size/machine/hash, and ARM64 Python process architecture. It then builds its own compiler, compares its sample C bytes with
the Linux cross-built compiler's output, runs the compiled sample against its
golden, and invokes the repository's existing three-stage bootstrap test.
A skipped bootstrap cannot produce passing evidence. Each bootstrap stage
keeps the repository's 3,600-second Windows limit. The native sequence has one
12,000-second monotonic deadline; every command is capped by its remaining
budget so failure reporting precedes the hosted step's 210-minute deadline. No compiler/runtime edits
or alternative bootstrap implementation are supplied here.

The ABI probe requires Visual Studio's ARM64 and Clang components through
`vswhere`, records `installationVersion`, and enters its ARM64
native developer environment via a temporary `.cmd` script (no nested command-line
quoting). Developer-command diagnostics go to stderr; paths containing carets,
percent signs, quotes or line breaks fail before invocation. It records the detected MSVC version even if it is rejected, requires MSVC >= 19.40, records the SDK and
clang versions, and runs a strict C11 hello with the pinned
`aarch64-pc-windows-msvc19.40.0` triple. It verifies the wgpu archive digest,
links its MSVC import library, and runs `wgpu_link_smoke.c` beside the DLL.
The smoke requires instance creation and a completed adapter callback.
An unavailable adapter is recorded without claiming rendering support.
The callback loop has a ten-second window; the launcher has a thirty-second
process limit. The JSON preserves partial/failed results and exact errors.

## Portable validation

```sh
python -m unittest tools.windows_toolchain.test_arm64 -v
pwsh -NoProfile -File tools/windows_toolchain/test_probe.ps1
cc -std=c11 -Wall -Wextra -Werror -pedantic-errors -fsyntax-only \
  $(pkg-config --cflags wgpu-native) tools/windows_toolchain/wgpu_link_smoke.c
```

PowerShell parsing/version/hash cases are portable stand-ins, not MSVC runs.
All Python helper commands have explicit subprocess deadlines. Windows-native
containment and Visual Studio execution remain unverified until the requested
hosted lane runs; portable mocks do not establish those behaviors.

## Hosted qualification

`.github/workflows/windows-arm64.yml` owns the lane. It runs portable tooling
checks and a Linux cross-build, uploads the compiler and provenance, then uses
`windows-11-arm` with ARM64 Python 3.13 and native PowerShell. The native job
installs checksum-verified Zig/wgpu archives and `.[dev]`, runs the Python and
PowerShell regression suites, qualifies compiler/bootstrap, and separately runs
the MSVC ABI probe even if compiler qualification fails. Both evidence folders
are retained on failure. All actions are pinned; the Nix cache disables FlakeHub.

The native compiler step has a 210-minute outer deadline, the ABI probe 15 minutes,
and the job 240 minutes. The shared Job owner also bounds every command. Successful
portable mocks or a Linux PE inspection do not satisfy the native acceptance rows.
The runner records its actual image/version; the current `windows-11-arm` image
is the Visual Studio 2026 ARM64 image, not an x64 emulation substitute.

Matrix/device updates wait for the actual run artifacts. GNU btrcc execution
does not establish the MSVC GPU ABI route, and linking wgpu does not establish a
usable GPU adapter or platform GUI implementation.
