# `Library.FileSystem`

The `btrc_stdlib_filesystem` group: path helpers, simple whole-file
operations, and exact, descriptor-backed handles with typed outcomes. The
implementation is POSIX, and on Windows rows a Win32 provider backs the same
API ([Windows](#windows) below). `import Library.FileSystem;` selects the
facade; the other modules are addressed by their folder path.

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

## Outcomes

Every open, read, snapshot and resolution in the package returns one
generic `FileSystemOutcome<T>`: `ok()`, then `value()` on success or
`error()` (a `FileSystemError` carrying kind, operation, path, native code
and message) on failure. A generic `T` cannot be compared with null, so the
constructor cannot reject a null success value; producers pass a non-null
value or a non-null error, never neither. The instances are
`FileSystemOutcome<FileSnapshot>` (`inspectExact`, the handles' `snapshot()`,
`inspect` and `validate*` methods),
`<FileHandle>` (`openFileExact`, `DirectoryHandle.openFile`),
`<DirectoryHandle>` (`openDirectoryExact`, `openDirectory`),
`<RegularFileSnapshot>`, `<Bytes>` (exact-length reads: empty `Bytes` are a
valid value for a zero-byte read and a short read is always an error),
`<TemporaryDirectory>`, `<PrivateDirectory>`, `<ExclusiveFileLease>`,
`<AdvisoryFileLock>`, `<FileTreeSnapshot>` and
`<ApplicationDirectoryRoots>`. A generic class cannot yet declare static
methods (docs/known-language-gaps.md), so producers construct it directly:
`new FileSystemOutcome<T>(value, null)` or `new FileSystemOutcome<T>(null,
error)`.

Documented exception: outcomes with a third, non-error terminal state keep
their own kinded types, because folding them into a value-or-error shape
would drop that state. They are `FileReadOutcome` (data, end of file,
failure), `DirectoryStepOutcome` (entry, end, failure),
`FileTreeSnapshotStep` (advanced, complete, failure), `FileSystemCloseOutcome`
(closed, already closed, failure), `PrivateFileReadOutcome` (data, missing,
failure) and `DurableReplaceOutcome` (committed, failed, or failed with
durability uncertain). Each still reports failure through `FileSystemError`.

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
defaults on Linux, and the shell's known folders on Windows (state
`FOLDERID_LocalAppData`, cache `LocalAppData\Cache`, configuration
`FOLDERID_RoamingAppData`, never an environment variable), as a
`FileSystemOutcome<ApplicationDirectoryRoots>`. A
failure is a `FileSystemError` from operation `resolve application directories`:
invalid limits are `FS_INVALID_ARGUMENT`, a root over the byte limit is
`FS_INVALID_ARGUMENT` with native code `ENAMETOOLONG`, a missing or relative
`HOME` is `FS_NOT_FOUND`, and other platforms report `FS_UNSUPPORTED`.
Environment values are bounded before they are copied. Callers append their
own application identifier and create the directories themselves.

`Library.Daemon` builds its owner-only control files on this group. The
corpus tests are `src/tests/stdlib/FileSystemHandlesContract.btrc`,
`FileSystemHandlesReal.btrc`, `FileSystemHandleInventoryReal.btrc`,
`FileSystemReadBytes.btrc`, `FileTreeSnapshotReal.btrc` and
`ApplicationDirectories.btrc`.

## Windows

`btrc.toml` gives `FileSystemHandles` a provider per row:
`Unix.PosixFileSystemProvider` (a selection shell: the POSIX bodies stay in
`FileSystemHandles.btrc`) on android, ios, linux and macos, and
`Windows.Win32FileSystemProvider` on windows. The Windows provider imports
`Windows/Win32FileSystem.c`, which is spliced into the program's C, so a
windows build needs the toolchain's MinGW-w64 headers and no native header
reader or extra library. `FileSystemHandles.btrc` keeps one class per
concept: each POSIX body sits under `#if !defined(_WIN32)` and its Windows
twin under `#else`, so the generated C on every other row is unchanged.
Identity shared with `Library.IO` (`File.snapshot`) lives in
`src/stdlib/Windows/Win32FileIdentity.c`.

What Windows does differently, each adaptation pinned by
`src/tests/native/filesystem_windows/WindowsFileSystemCases.btrc` (run on x64
and ARM64 by `windows.yml`'s `win32-native` job, through both compilers, with
the FileSystem corpus programs):

- **Reparse points.** Exact opens never follow the final component
  (`FILE_FLAG_OPEN_REPARSE_POINT`), and every name below a held directory is
  opened relative to its handle (`NtCreateFile` with a root directory and
  `FILE_OPEN_REPARSE_POINT`). A symbolic link, junction or mount point is
  `FS_SYMLINK`, as a POSIX symlink is; a tree walk records it and never
  enters it, so a junction swapped in mid-walk is opened as itself and
  refused (case `junction-swap`).
- **Removal and rename** are by handle with POSIX semantics
  (`FileDispositionInfoEx`, `FileRenameInfoEx` relative to the held parent),
  so a name being replaced or held open elsewhere still unlinks. Tree
  removal (`TemporaryDirectory.close`, `FileSystem.removeRecursive`) removes
  read-only files too, as POSIX `unlink` does.
- **Identity** is the volume serial number plus the 64-bit file ID. A 128-bit
  file ID (ReFS) does not fit `FileSnapshot` and is `FS_UNSUPPORTED`.
- **Owner-only access.** Instead of mode 0700 and 0600, a private directory or
  file is owned by the current user and has a protected DACL granting only
  that user. One whose DACL grants anyone else is refused as
  `FS_ACCESS_DENIED`. `FileSnapshot.mode()` is synthesized from the
  attributes (`0666`, or `0444` when read-only), not read from an ACL.
- **Locks** are `LockFileEx` over the whole lock file. They are mandatory:
  while one is held, other handles cannot read or write the locked file
  (POSIX `flock` is advisory). Contention without `wait` is
  `FS_RESOURCE_EXHAUSTED`.
- **Names** compare as NTFS compares them, ordinally ignoring case, so
  `Lock` and `lock` are the same lock child. A name Windows paths cannot
  address (`CON`, `NUL`, a trailing dot or space, a `:` stream, control
  characters) is `FS_INVALID_ARGUMENT`.
- **Durable replacement** writes and flushes an owner-only temporary file,
  renames it over the target by handle and flushes the directory; an
  interrupted replacement leaves the old contents or the new, never a mix.
- **Paths** are UTF-8, converted strictly to UTF-16 and used in `\\?\` and
  `\\?\UNC\` form, so long, UNC and non-ASCII paths work and `MAX_PATH`
  never applies. Separators may be `\` or `/`; results use `\`.
- **Symlinks.** `FileSystem.symlink` creates a directory link when the target
  is a directory; Windows allows it only with the symlink privilege or in
  Developer Mode. `FileSystem.readLink` reads symbolic links and junctions.
