# macOS release shell

Packet `codex/macos-release-shell-6f` starts from published `6f1b81d9`.

## Observed failure

PR68 macOS x64 bundle job `113504238329` entered
`nix develop --command make NIX= btrcc-macos-x64` at 19:39:46 UTC on
2026-10-08. Cancellation arrived at 20:23:27 while Nix was still realizing
Python dependencies; neither generated-source checking nor compiler generation
had started. The retained log has 149 distinct built derivations, including
125 Python derivations. This establishes preparation overhead, not compiler
slowness or a completed performance comparison.

The default shell includes Python build, setuptools, pytest, xdist, coverage
and LSP packages. The Darwin interpreter/libffi overlay changes their closure.
Source inspection of the compiler and generator finds only standard-library
and repository Python imports. The release recipe does not package a Python
wheel or run those development tools. No existing narrow shell provides the
same release path: `platforms` extends default; packaged `btrcc` uses the native
MacOSMain entry instead of the portable release BtrccMain and Zig build.

## Change and preserved contract

A Darwin-only `macos-release` shell uses the same locked package set, Python
3.14/libffi overlay, GCC, Clang, Zig, Make and Git. Its native SDK, reader and
provider CC/CXX environment is shared with default, as is the shell hardening
policy. GCC remains explicit because the relocated-output smoke calls `cc`.
The host shell remains arm64 even when Zig produces x64 and Rosetta runs it.
Only the two native-bundle shell selections change in the workflow.

Make's generated-source check, x64/arm64 portable C equality, release entry,
strict compilation flags, archive/checksum, relocation, architecture check,
Rosetta execution, stdlib discovery, strict output compilation and exact stdout
comparison remain unchanged. The original 45-minute job deadline remains.
The default and platform shell behavior and flake lock are unchanged.

## Qualification

Source preparation only. Independent source review, actual Nix evaluation and
closure/tool/SDK equivalence, affected workflow contracts and both original
bundle journeys remain required. No elapsed-time improvement is claimed yet.
