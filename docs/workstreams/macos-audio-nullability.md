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
