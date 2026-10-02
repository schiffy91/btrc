# `Library.FileSystem`

The `btrc_stdlib_filesystem` group: path helpers, simple whole-file
operations, and exact, descriptor-backed handles with typed outcomes. The
implementation is POSIX. `import Library.FileSystem;` selects the facade; the
other modules are addressed by their folder path.

| Module | Owns |
|--------|------|
| `Library.FileSystem` (`FileSystem.btrc`) | The `FileSystem` facade, `FileStatus`, `DirectoryStream`, `Directory` and `PathTools`. |
| `Library.FileSystem.FileSystemHandles` | Exact handles and their typed outcomes. |
| `Library.FileSystem.FileTree` | Bounded, deterministic tree snapshots and cache revisions. |
| `Library.FileSystem.ApplicationDirectories` | Per-user state, cache and configuration roots. |

## Paths and simple operations

`PathTools` joins, splits and absolutizes paths (`join`, `basename`,
`dirname`, `isAbsolute`, `absolute`); its `*For(..., windows)` variants apply
Windows separator and drive rules explicitly. `FileSystem` covers the common
cases as class methods: `exists`, `isDir`, `isFile`, `isSymlink`, `mkdir`,
`mkdirp`, `chmod`, `removeRecursive`, `symlink`, `readLink`, `realPath`,
`absolutePath`, `tempDir`, `listDir`, `readText`, `readBytes` and
`writeText`; the working directory is `Platform.currentDirectory()`. `DirectoryStream` reads one directory
as a stream of names, so a caller that filters entries never materializes the
whole listing; `close()` reports read or close failure, and a dropped stream
closes itself.

## Exact handles

`FileSystemHandles.btrc` is the capability API for code that must not act on
a path that changed underneath it. Every operation returns copied BTRC values
or a typed outcome (`FileSystemError` with a `FileSystemErrorKind`); native
descriptors never cross the API, each read or directory step does bounded
work, and callers own their byte, traversal and cancellation budgets. The
facade opens each kind:

- `FileSystem.inspectExact` / `openFileExact` / `openDirectoryExact` return a
  `FileHandle` or `DirectoryHandle` pinned to the object that was opened.
- `openRegularFileSnapshot(path, maximumBytes)` returns a read-only
  `RegularFileSnapshot` whose reads are exact-length and checked against both
  the pinned descriptor and the named path.
- `createTemporaryDirectory(prefix)` returns a `TemporaryDirectory` whose
  `close()` removes it through a descriptor-relative recursive delete.
- `openPrivateDirectory(absolutePath)` returns a `PrivateDirectory`: an
  owner-only (0700) directory reached without following links, creating at
  most the final leaf. Its `acquireExclusiveLease(childName)` returns an
  `ExclusiveFileLease` over an owner-only 0600 lock child, with
  generation-checked reads and durable replacement relative to the pinned
  directory.
- `AdvisoryFileLock.acquire(path)` takes a POSIX `flock` on a persistent
  coordination file. It is advisory, not authorization, and is nonblocking
  unless `wait` is true.
- `ownedHandleInventory()` counts the exact handles this program holds open,
  without probing native descriptor tables.

## Tree snapshots

`FileSystem.openFileTreeSnapshot(path, limits)` returns a `FileTreeSnapshot`
that owns its `DirectoryHandle`s. Each `advance()` performs one bounded read,
validation, open, close or state transition, within `FileTreeLimits`.
`FileRevision` and `FileRevisionBuilder` produce stable, non-cryptographic
cache identities; a revision is not an authorization token, so stale work
still checks exact snapshots before it publishes.

## Application directories

`ApplicationDirectories.resolveStandard()` (or `resolve(limits)`) returns the
user's generic state, cache and configuration roots: `~/Library/Application
Support` (state and configuration) and `~/Library/Caches` on macOS, and
`XDG_STATE_HOME`, `XDG_CACHE_HOME` and `XDG_CONFIG_HOME` with their `HOME`
defaults on Linux. Other platforms report `APP_DIRECTORY_UNSUPPORTED`.
Environment values are bounded before they are copied. Callers append their
own application identifier and create the directories themselves.

`Library.Daemon` builds its owner-only control files on this group. The
corpus tests are `src/tests/stdlib/FileSystemHandlesContract.btrc`,
`FileSystemHandlesReal.btrc`, `FileSystemHandleInventoryReal.btrc`,
`FileSystemReadBytes.btrc`, `FileTreeSnapshotReal.btrc` and
`ApplicationDirectories.btrc`.
