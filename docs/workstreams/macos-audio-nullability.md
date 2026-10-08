# CoreAudio aggregate nullable ownership

Base: `3974d47bc87851b1ac19b8d2b4bd5022f2d94676`.
Branch: `codex/macos-audio-nullability`.
Owned paths are the WORKSTREAMS claim, this report, MacOSAudioDevice.btrc and
CoreAudioAggregateAllocations.btrc. No product, compiler, generated or frozen
boundary edits. Token candidate71352c50 remains on its original local branch.

The original BTRSmith3974 frontend run reports24 nullable CF assignment sites
on each frontend. The aggregate owner stores empty/fallible CF handles in
non-null fields. Its dictionary getter also exposes a null or incomplete
result before successful preparation. The existing create caller checks
prepare, so no observed application null dereference is claimed.

Preparation only: source regression and fix are next. No transpile, native
build, test, or measurement is authorized during the active BTRSmith lane.

## Source checkpoints and behavior

- Claim: `4349fb7d`.
- Fixture-only checkpoint: `91c45d4b`. This is an unexecuted counterfactual,
  not a claimed red runtime result. The old getter returns before preparation;
  the new fixture requires its specific unavailable error.
- Twelve owned CF slots now explicitly allow null. Checked local managed CF
  values keep their owners stable through calls and field writes; the existing
  fields still retain every partial allocation. No manual retain/release,
  raw cast, SDK metadata change or analyzer suppression was added.
- `_prepared` keeps its existing single-attempt behavior. A distinct `_ready`
  flag is published only after all dictionary entries succeed, so a failed
  late key allocation cannot expose a partially initialized dictionary.
- The getter returns a checked, retained local only after success. The fixture
  checks rejection before preparation, after invalid empty input and after
  each injected allocation failure; it checks a nonempty dictionary on success.
  Existing repeated-prepare rejection and zero-outstanding-reference assertions
  remain unchanged.

## Qualification still required

No reference/selfhost transpilation, C build, native run or sanitizer run was
performed in this packet. Only the existing formatter check for both changed
BTRC files and `git diff --check` passed. The original24 warning sites per
frontend remain the baseline evidence in the retained BTRSmith3974 frontend
stderr; their elimination has not yet been observed by a compiler.

After the parent allocates the native lane, use the original driver in the
qualified Nix/Apple SDK environment, with a freshly source-matched compiler:

```sh
BTRC_TEST_BTRCC=/absolute/path/to/source-matched/btrcc python3 -m pytest \
  src/tests/python/test_core_audio_device_runtime.py \
  --compilers=python,btrc \
  -k 'test_core_audio_inventory_sdk_failures and (CoreAudioAggregateAllocations or CoreAudioResourcesConformance)' \
  --junitxml=/absolute/evidence/audio-nullability.xml
```

Expected selection:8 rows, two fixtures × two frontends × plain/sanitized,
with no skips. Retain compiler stderr to establish zero nullable diagnostics
for this owner: the existing driver checks successful transpilation but does
not itself reject warnings. Also run the fixture-only checkpoint on original
3974 production through the same SDK/compiler inputs to demonstrate the new
boundary assertion genuinely fails. The source remains based on3974; the
fixture-only run and final fix must use identical failure adapters and preserve
all failed outputs. Full final-tree gates remain integrator-owned.
