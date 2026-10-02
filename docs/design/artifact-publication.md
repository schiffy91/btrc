# Compilation caches and artifact publication

How `btrcpy`, `btrcc` and `btrc-native-plan` reuse earlier work and publish
their outputs. The [README](../../README.md#quick-start) carries the summary;
this page is the detailed contract. `btrcpy --help` and `btrcc --help` list
the flags named here.

## Reference compilation cache

The reference compiler caches complete emitted generations, including split C
units and debug source maps, after resolving current sources and imports. Each
generation contains checksummed C files, its native link plan and diagnostics;
missing or corrupt payloads cause recompilation. Native SDK builds can reuse
output after the actual reader validates current headers and binding contracts;
the reader's identity and admitted semantics participate in the key. Warnings
and source locations survive reuse. Profiling, freestanding output,
prebuilt-stdlib builds and unavailable native reader identity bypass this cache.
The default aggregate artifact limit is 512 MiB; a larger successful build
forgoes caching.
Use `--no-cache` to run the full pipeline. Cache placement follows
`BTRC_CACHE_DIR`, the nearest package's `.btrc-cache`, then the user cache.

## Self-hosted compilation cache

The self-hosted CLI also caches complete emitted generations for named outputs
on POSIX hosts. It resolves current sources, packages and native declarations
before lookup, verifies the compiler and native reader contents, and checks the
cached plan against current package facts. Missing, corrupt or unsupported
entries fall back to compilation. Its private cache lives under
`$BTRC_CACHE_DIR/selfhost-artifacts-v1`, or
`$HOME/.cache/btrc/selfhost-artifacts-v1`; the aggregate limit is 512 MiB.
`btrcc --no-cache` disables compilation-cache reuse. Cached results still pass
through output publication. Both CLIs can retain a complete owned generation
when its current bytes, modes, paths and ownership record match the requested
outputs. They recover first and verify under directory locks with fresh source
and path guards, preserving output inodes and timestamps without staging new
payloads. This also applies after a full `--no-cache` compilation. Changed,
missing or unowned output uses normal publication. Cache eviction and Windows
artifact storage remain unfinished.

## Output publication

The reference CLI now publishes regular primary C, secondary units and the
requested link plan as one recoverable generation. A failed replacement rolls
back; the next successful compilation recovers an interrupted attempt before
publishing its own layout. Obsolete owned units/plans are removed only when
their recorded contents are unchanged, and resolved compiler inputs are
protected from replacement and retirement. Output symlinks keep their targets
and existing file permissions are preserved.

## Recovery state

Recovery state is durable and separate from compilation caches, including with
`--no-cache`. Set `BTRC_STATE_DIR` to an absolute private state directory, or use
the default: `~/Library/Application Support/btrc/generations` on macOS,
`$LOCALAPPDATA/btrc/generations` on Windows, and
`${XDG_STATE_HOME:-~/.local/state}/btrc/generations` on Linux. Retain this state
while its outputs may require recovery. Inspection-only requests do not create
it. Freestanding header creation and output requests containing devices retain
their separate I/O behavior; they are not covered by the regular-file
transaction. The POSIX self-host CLI uses the same generation protocol; native
Windows publication support and the complete release/product matrix remain open.

## Native-plan builds and publication locks

`btrc-native-plan` holds the publication directory locks while reading the plan,
compiling its generated C units and linking. Generated primary/secondary C and
link-plan paths may be symlinks to regular files: discovery locks both the
requested parent and resolved target parent, then rechecks those bindings before
starting tools. C compilation retains the requested filenames so relative quoted
includes keep their meaning. Native package/header inputs retain their no-follow
validation. A pending publication journal stops the build
with a recovery-required error; rerun the owning compiler with its retained
state to recover before building. The reader never recovers paths from an
untrusted journal. Lock files remain in place after successful builds. This
coordinates with both CLIs' named-primary regular-file generations. Direct
external writes do not participate. The self-host writer acquires the same
private per-primary generation owner, then the sorted union of current and
interrupted output directories and the shared publication lock. It validates
private authority and path bindings after waiting, recovers the authorized
journal, then writes durable intent before replacing public files. The committed
ownership manifest is the final validator. Retirement requires the previous
owned digest; changed files and current source inputs are preserved with an
explicit error. Invalid journals never enlarge recovery authority.

## Cross-frontend recovery

Both frontends can recover the other's regular-file generation. The self-host
validates all requested primary, secondary and link-plan paths before writing,
stages and flushes the payloads, and checks prepared bytes and permissions before
journaling. Existing output symlinks and target permissions are preserved through
validated canonical targets. Recovery restores the previous validator last and
retains journals when durability or cleanup is uncertain. A failed directory
flush never counts as successful publication. Snapshot-close and lock-release
failures also produce a nonzero self-host CLI result, preserving the original
diagnostic when cleanup fails too. A cleanup error after commit can leave the
complete new generation installed; rerunning the owning compiler validates and
recovers state before another publication. Self-host stdout/secondary-only
requests retain their separate staging path; native Windows private-state and
locking support remains unfinished. Retirement digests are computed through one
immutable file snapshot in 64 KiB reads. The self-host writer revalidates resolved
outputs after waiting for the generation owner, before persisting recovery intent;
outputs redirected into private state are rejected without creating that intent.

## Source identity

Source text read by the CLI/reference import resolver and the POSIX self-host
source reader now carries the identity of the stream that supplied its bytes.
Version and requested-path checks run after reading and again in publication
guards, including after lock contention. A detected edit, replacement,
retarget or removal rejects publication instead of treating a replacement at
the same filename as the original input. Metadata is copied; source descriptors
do not stay open throughout compilation. The reference library API still
accepts in-memory root text and exposes identities for file-backed dependencies.
These checks do not lock out uncooperative external writers, and they do not
yet cover every reference metadata/SDK reader or native Windows publication.

## Import-directive cache

Both CLIs also cache import-directive spans by source content, compiler identity
and grammar. They reparse those small fragments while still reading current
sources and resolving paths, packages, directory imports and native SDK
declarations afresh. Corrupt entries, unavailable storage and fragments needing
surrounding comment context fall back to full scanning. `--no-cache` bypasses
directive reuse in both CLIs; the reference CLI's `--profile` also bypasses it.
This does not cache an old filesystem dependency graph. For self-host named
outputs on POSIX, spans live under `$BTRC_CACHE_DIR/selfhost-directives-v1` or
`$HOME/.cache/btrc/selfhost-directives-v1`, with an 8 MiB limit per entry.
