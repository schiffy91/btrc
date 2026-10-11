# Native reader job lifetime

Base: 3694ce58b11f9c1cd945f9c4ee64cf2801195ece. Owned paths: macos.yml,
its existing workflow contract tests, tools/qualification/toolchain.py, and this
report. The ordinary checkout/index and integration refs are preserved.

Main36b unit job113737981637 had eight WebGPU import failures before native
execution. Its log proves the reader was fetched and admitted by the ordinary
flake at setup, then was not launchable later. No exact store hash is embedded
in source. Garbage collection is not established as the cause: ENOENT can also
mean a missing script interpreter. The Git gc.auto0 message is unrelated to Nix.

Both macOS reader setup owners now retain their normal nix build output using
an explicit job-temporary out-link. Native commands, assertions, selection,
shards, compile/run limits and job deadlines stay unchanged. Linux's unrelated
immediate package validation --no-link build is untouched. The out-link remains
through runner teardown rather than being removed before tests or post evidence.

NativeReaderProbe extends the existing toolchain observation owner. Independent
/usr/bin/python3 captures the reader wrapper, its actual shebang interpreter,
wrapped backend and exact Nix requisite paths before and after testing. Post runs
with always(), outside nix develop, and never realizes/repairs missing paths.
It records failed queries and the original closure even when the output/root is
missing; artifacts are uploaded with always(). A changed/unusable prerequisite
fails the evidence step after its JSON is saved. This is bounded by 30s query and
2min step limits. A force-killed/lost runner may still prevent post/upload.

The helper's exact module CLI --help runs with this Mac's independent Python3.9.6;
source is stdlib-only and future-annotated. Hosted interpreter identity is recorded
by the evidence JSON during qualification. Focused contract/negative tests and a
real retention check are prepared, not executed during source preparation.

The retention check uses one nonce-bearing task-owned file/store path and the
same nix build --out-link operation (offline/no substitutes). Exact-path deletion
must be refused while the root exists; after removing only that owned root the
same exact path can be deleted. No global GC, force deletion, unrelated path,
settings mutation, dependency download or toolchain change is allowed. Existing
bounded process ownership retains all exit/cleanup receipts. This proves Nix
root retention only and does not reproduce the old hosted disappearance.
