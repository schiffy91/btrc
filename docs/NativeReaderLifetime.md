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

The authentic retained Nix wrapper starts with `#! /nix/store/.../bash -e`.
The probe records the absolute interpreter and its optional argument separately,
without executing or shell-splitting it. The same missing wrapper/interpreter/
backend/closure/root cases now cover both bare and actual `-e` shebang forms.
The prior rejected draft remains retained; no hosted or retention result exists.


## Qualification results

The corrected original-toolchain recipe passes91 baseline and106 candidate
workflow/toolchain tests, with zero skips/failures/errors. Result SHA-256:
`19782782b8627ca26ad5e1247f7976be36b645e1b49999f02b7345e5b147d674`.
The first recipe's system-Bash3 classifier failures remain retained; production,
assertions and240-second bounds were unchanged in the corrected attempt.

The real disposable-path trace demonstrates that its exact registered root
prevents deletion and removal of only that root permits deletion of the same
authenticated payload. Nix's refusal named the exact protecting root. The runner
expected different wording, so original result `75893f24` remains failed.
Independent review verifies the intended mechanism, all inputs/logs, six closed
groups and final root/store absence. No repeat deletion is needed for that proof.

Actual pre/post observations use Xcode's independent Python3.9.6 on the retained
warm out-link and the original retained reader package. Both authentic bash-e
wrappers, interpreters, backends and47-path requisite closures remain usable and
unchanged. Four observed command groups close. Result SHA-256:
`6de6df8e850ac546955d95ae628552190f631f6fcddc1eb3608f4114cb5d0c5f`.
No reader execution, rebuild, store realization or historical-cause inference is
part of that observation. The final hosted matrix must still qualify the job
lifetime change in its actual macOS workflows.
