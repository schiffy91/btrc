# Native UI agent runbook

Codex owns the native UI packets assigned by `WORKSTREAMS.md` §2–§3 and
`docs/workstreams/codex.md`. Before each packet, fetch `origin/main`, read the
current `docs/workstreams/codex-ui-lanes.md`, and inspect open draft PR claims.
That lane file supplies the current order and CI capacity policy.

```sh
git clone https://github.com/schiffy91/btrc.git
cd btrc
git fetch origin main
git ls-tree --name-only origin/main docs/workstreams/codex-ui-lanes.md
git show origin/main:docs/workstreams/codex-ui-lanes.md
git switch -c codex/cx-example origin/main
export BTRC_TEST_RUNNER=linux-devcontainer
```

Use one isolated checkout and `codex/<packet-id>` branch per packet. Never push
`main` or `main-kn9jxh`, merge a PR, or close one. Read all of `AGENTS.md` first.
The cloud container has neither a Mac nor devices. Its runner name must be
explicit: automatic container detection may otherwise select an unsupported
`linux` skip manifest.

## Bootstrap and keep the toolchain cached

Install Nix with flakes enabled in the cloud environment's setup phase, with
network access for the large Nix store downloads. If Nix cannot be installed,
document and catalog edits can continue, but repository tests cannot be
claimed as run. Follow the suggested setup script in
[WORKSTREAMS.md §3.11](../../WORKSTREAMS.md#311-codex-cloud-environment):
the Determinate installer uses `--init none` and `NIX_REMOTE=local` for a
daemonless container. If the container forbids a system store, provision a
configured rootless Nix entry point on PATH instead. This script verifies an
existing installation; it does not install Nix or replace the environment’s
Nix configuration. Keep the environment’s existing Git credential helper;
omit the suggested script’s `gh auth setup-git` command. Once Nix is ready:

```sh
tools/ui/codex-setup.sh
# Only for a packet that needs the Android/mobile tools:
tools/ui/codex-setup.sh --platforms
```

The script accepts an existing Nix installation, including a configured
rootless Nix entry point on PATH. It fails if Nix, Xvfb, GCC 15.2 or the native
header reader is missing; it never substitutes a distro compiler. It warms
and GC-roots the development shell, builds `.#btrc-native-header` from this
branch's `tools/NativeHeaderReader.cpp`, and builds `bin/btrcc` with
`make NIX= btrcc` inside the shell. Its default profile directory is
`${XDG_CACHE_HOME:-$HOME/.cache}/btrc/gcroots`; `BTRC_CODEX_GCROOTS` can select
another persistent writable directory. The optional platforms closure is
about 17.75 GB and is never downloaded by default.

The runner export is appended once to `~/.bashrc`. For a setup rehearsal,
`BTRC_CODEX_RC_FILE` may name a disposable writable rc file instead. If a
`GH_TOKEN` setup secret is supplied and no working stored GitHub authentication
exists, the script persists it through `gh auth login --with-token`, without
printing it. It preserves the platform Git credential proxy and never calls
`gh auth setup-git`. It does not store a token when `GH_TOKEN` is absent.
Repository access requires branch and pull-request write;
workflow dispatch also requires `actions:write`. Do not paste tokens in logs.

The Nix shell exports `BTRC_NATIVE_HEADER_READER`; without that executable the
Linux provider tests skip. Re-enter the branch's shell after changing the
reader or flake. To build/root the reader explicitly:

```sh
nix build .#btrc-native-header --out-link "$HOME/.cache/btrc/gcroots/native-header"
nix develop --profile "$HOME/.cache/btrc/gcroots/dev" --command true
nix develop --command bash -c 'test -x "$BTRC_NATIVE_HEADER_READER" && gcc -dumpfullversion && command -v Xvfb'
```

## Compile once, then run focused checks

```sh
export BTRC_TEST_RUNNER=linux-devcontainer
nix develop --command make NIX= btrcc
export BTRC_TEST_BTRCC="$PWD/bin/btrcc"
nix develop --command tools/virtual-display.sh make NIX= test-native-gui
```

Inside an existing `nix develop` shell use `make NIX= …`; do not nest a second
development shell through Make. Independent test processes may share the
same immutable compiler binary only while its compiler, compiler-import
stdlib, spec, runtime and C-toolchain inputs are unchanged. Rebuild after any
such change. Do not point `BTRC_TEST_BTRCC` at a binary from an older checkout
just because it exists. A cold build takes roughly 10–20 minutes on four CPUs.

A packet authorized to edit a compiler-import stdlib module—BackgroundJobs,
FileSystem, Process and the complete list in `WORKSTREAMS.md` §3.4—needs its
own compiler and a bootstrap fixed point, locally or through the allowed CI
bootstrap shard. Ordinary UI fixtures and providers use the integrator's
matching compiler. Compiler, spec, runtime and hotspot changes belong to
Claude; put a `REQUEST(<packet>)` in the PR body instead of editing them.

The focused target selects the GUI, tray, Linux provider and WebGPU suites,
plus `test_native_ui_*.py`. Its coverage test rejects a new GUI/tray `.btrc`
fixture lacking a selected driver. Named fixture/stem literals, specifically
named subdirectories and constrained filename templates count as drivers;
a generic GUI-root anchor or unconstrained `{fixture}.btrc` template does not.

When the native-shell fixture (CX-UIA-09) is available, use a private session
for protocol-specific checks:

```sh
nix develop --command tools/ui/headless-session.sh --x11 -- python3 -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_linux.py -q -rs
nix develop --command tools/ui/headless-session.sh --wayland -- python3 -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_linux.py -q -rs
```

## Read skips and collect the appropriate evidence

`make test-native-gui` writes `build/skip-report-native-gui.json` and runs its
own expected-skip gate. Report passed, skipped and failed counts, separated by
frontend, and keep the actual skip reasons. A green row with a skip does not
prove its provider. New or changed skip rules for existing runners belong
only in the final `fragment:` commit, with `covered_by` naming the runner that
executes each row. Generated outputs, when authorized, belong in a separate
`derived: regenerate` commit. Claude re-applies fragments and regenerates
outputs at integration; Codex never hand-edits generated files.

macOS/AppKit and hosted GPU correctness evidence comes from the draft PR's
`macos.yml` native-gui job. Read its `junit-macos-native-gui` artifact to confirm
the AppKit rows actually executed. The packet may use at most one
`focus=native-gui` dispatch per workflow when needed:

```sh
nix develop --command gh workflow run macos.yml --ref codex/cx-example -f focus=native-gui
nix develop --command gh run list --branch codex/cx-example
nix develop --command gh run view RUN_ID --log-failed
nix develop --command gh run download RUN_ID -n junit-macos-native-gui
```

These are hosted/headless stand-ins. They do not establish physical display,
GPU pacing, input latency, accessibility-user acceptance, signing, account or
device evidence. Leave those to the named `MAC-` packets.

## Draft PR and CI handoff

Before each push that changes Python, shell or btrc files, run the whole unit
shard with `nix develop --command make NIX= test-unit`; focused tests alone do
not meet the current CI policy. Every waited test subprocess needs `timeout=`
from `src/tests/process_limits.py`. Check the current CI cap before pushing. Open a draft PR against `main`, title
it `[CX-…] …`, and start its body with Owned paths followed by the repository's
Codex packet template. Include exact commands, counts, skip rules, evidence
artifacts and run IDs. Use at most four pushes per packet. Watch `release`,
`tests (unit)`, `tests (btrc)` and macOS `native-gui` first; fix failures within
your owned paths and re-push. Compare unrelated failures with current main,
and rerun only an infrastructure failure, once. Never request full/extended CI
or add `ci:full`. The current policy permits at most 180 minutes of monitoring
after the final push; if that expires, record every pending run in the body.

Draft-PR CI is the packet gate. Claude alone integrates branches, runs the
landing gate and pushes main. Local focused checks make the change reviewable;
they do not replace that integration step.
