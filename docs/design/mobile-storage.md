# Mobile storage, bounded streams and document grants

> **Draft for CX-P2-03; not approved or implemented.** This proposes the
> Stage 26 mobile storage contract and the later I1/A1 owners. CL-P2-01 must
> obtain two adversarial reviews and one parity review, resolve blocking
> findings and record approval in PLAN.md. The separate `DocumentTree`
> recommendation answers adaptations Q2 provisionally; neither this draft nor
> WORKSTREAMS §7 Q9 establishes owner sign-off. iOS and iPadOS are one platform
> family, with phone/tablet fixtures and device-class evidence.

## Basis and boundaries

The sources at this draft's base are [ApplicationDirectories](../../src/stdlib/FileSystem/ApplicationDirectories.btrc),
[FileSystem](../../src/stdlib/FileSystem/FileSystem.btrc),
[FileSystemHandles](../../src/stdlib/FileSystem/FileSystemHandles.btrc),
[IO](../../src/stdlib/IO.btrc), and
[IDirectoryPicker](../../src/stdlib/GUI/IDirectoryPicker.btrc). Requirements come
from [platform parity](platform-parity.md)'s P3 filesystem, I1 sandbox-storage
and A1 storage/permission sections and [platform adaptations](platform-adaptations.md)'s
row 7 and Q2. The delivery boundaries are the
[Codex packets](../workstreams/codex.md#cx-p2-03) and
[Claude review packet](../workstreams/claude.md#cl-p2-01).

Today `ApplicationDirectoryRoots` has state, cache and config paths; the
resolver implements macOS/Linux and rejects other platform codes. It does
not provide a temporary root. `IO.File.readBytes()` reads in 8192-byte chunks
but accumulates the whole input. Its borrowed `FILE*` does not establish
ownership of a mobile descriptor, grant or cancellation operation.
`RegularFileSnapshot` depends on seekable regular-file identity/version checks.
`DirectoryHandle.openExact` validates a local directory's identity/version;
`PrivateDirectory` provides descriptor-relative private-file operations. Those
filesystem guarantees are not necessarily available from a document provider.
`DirectoryPickerOutcome.selected` carries a string, not authority.

No existing API is silently reinterpreted. This proposal adds stream and grant
owners, preserves exact-handle semantics, and imports a provider document into
app storage when a consumer needs seeks, snapshots, SQLite or atomic replacement.
Neither a content URI nor a security-scoped URL is converted into a purported
ordinary path by stripping its scheme. Capability-backed data can change or
disappear while an operation is running.

All proposed type/member names below are design notation, not declarations or
an approved compiler surface. Native bridges must use checked Objective-C/JNI
bindings after their dependency packets land; handwritten ABI declarations or
compiler workarounds are not authorized by this document.

## App roots and authority

Roots come from the running app host/container. They are validated nonempty,
absolute local filesystem locations without embedded NUL, opened under their
native authority, and checked for the required directory/access capability.
String normalization alone is not a containment or symlink check. The provider
retains native root handles and performs child traversal relative to them;
prefix matching does not authorize a path. Directory creation is explicit and
failure is typed. No root falls back to the working directory, `/`, another
platform's HOME/XDG interpretation or public shared storage.

An OS-returned container URL can include a platform-managed path alias. The
mobile bridge must establish the trusted root's native identity before applying
no-follow child traversal; blindly feeding that spelling into the current
all-ancestor no-follow `PrivateDirectory.openAbsoluteLeaf` is not a verified
mobile implementation. Any canonicalization is confined to establishing the
OS-authorized root and revalidated against that authority. It never permits
caller-controlled symlink traversal below the root.

| Root | iOS/iPadOS proposal | Android proposal | Persistence |
|---|---|---|---|
| State | `NSFileManager URLsForDirectory` for Application Support in the app's Library | host-provided `filesDir`, later `Context.getFilesDir()` | durable app-private state; subject to uninstall/user deletion |
| Config | same private Application Support root, with caller-chosen child namespace | same private `filesDir`, with caller-chosen child namespace | same durability as state |
| Cache | native Caches URL (`Library/Caches`) | host-provided `cacheDir`, later `Context.getCacheDir()` | disposable; OS eviction is normal |
| Temporary | `NSTemporaryDirectory()`, validated before use | dedicated private temporary child under `cacheDir` | disposable; no survival promise |

Using the same state/config root preserves the current three-field roots
constructor. A proposed additive temporary-root query returns its own checked
outcome; it does not change constructor arity or rename an existing field.
The exact member spelling is for CL-P2-01. Roots already belong to this app:
providers do not append a desktop application id a second time. Callers may
create explicit module children. Durable settings/library records never live
in cache/temp. Backup exclusion and file-protection policy are explicit product
decisions; this draft does not disable protection to hide locked-device errors.

For iOS, resolve native URLs on each launch rather than persisting the sandbox's
absolute path. Retain the URL as needed across the checked binding and release
all native references. Native failure, empty/multiple unexpected root results,
unavailable protected data and inability to create/open a root are observable
failures. Cache and temporary existence does not prove durable state is usable.

Stage 25's Android test host supplies an explicit files/cache root pair through
its structured argv or environment contract. Suggested names are design-only;
the host contract must choose one encoding and reject duplicates/conflicts.
The host obtains the values from its own app context and validates their
ownership before invocation. Arbitrary user input or a shell environment does
not become a grant. Missing, relative, nonexistent/inaccessible or mismatched
roots fail explicitly before the fixture can write. CX-P2-41 replaces this
transport with checked context queries; production does not trust test-host
overrides. Test host and production feed the same validated root resolver.

Closing an Activity, rotating a screen or losing a window does not revoke
app-private storage. Process death closes native handles; the next process
resolves roots anew. Scans and imports are tied to explicit operation owners,
not to a transient view, unless the caller deliberately cancels on view close.

## Additive non-seekable byte source

The proposed `IO.ByteSource` owns one ordered readable stream. Opening it either
transfers a descriptor/native stream and its release obligation, or retains a
lease on a provider owner; the constructor must distinguish these cases.
Borrowing an `IO.File` handle never silently transfers its ownership. Sources
are single-reader: only one read is in flight, and concurrent read/close is
serialized by the owner. Streams need not have a length, seek position,
filesystem path, stable inode or meaningful snapshot metadata.

Proposed operations are `read(maxBytes, cancellation)`, `cancel()` and `close()`.
These may complete asynchronously on an IO executor. They must not block the
UI or realtime audio executor. A read accepts a positive bounded size and
completes exactly once with one of:

| Outcome | Meaning |
|---|---|
| DATA | owned immutable bytes, length in `1..maxBytes`; short reads are ordinary |
| END | successful EOF; subsequent reads return END until closed |
| CANCELLED | the operation accepted cancellation before its terminal completion |
| FAILED | a structured IO-level failure; no bytes are returned in this outcome |

Zero-length DATA never means EOF or a retry loop. The source handles native
short reads and interrupt retries without duplicating data. FAILED/CANCELLED
end the current stream; reopening requires a new authority check and source.
Close is idempotent, seals read admission and drains any in-flight native
operation before releasing its descriptor and grant lease. Close/cancel racing
with completion delivers one terminal result. Completion already accepted by
the owner stays terminal, although a canceled callback registration can discard
its delivery. Cleanup still runs independently of UI callback delivery.

`FileSystemHandles` already imports `IO`; consequently `IO` must not import
`FileSystemError` or `FileReadOutcome` back from that module. Define the new
stream's outcome/failure primitives in IO using IO-owned types. The higher
filesystem/provider layer maps these into filesystem outcomes and preserves
native error provenance. This avoids a new compiler-import cycle. Existing
`IO.File`, `FileReadOutcome` and its DATA/END/FAILED constructors remain intact.

Cancellation is cooperative but must reach a documented native cancellation
mechanism (for example the provider request's cancellation signal). Blindly
closing a descriptor from another thread is not proof that a blocked read
terminates safely. A backend that cannot cancel/drain its native read must
report the missing capability and cannot qualify cancellable imports. Do not
return cancellation and free storage while a native read can still enter it.
An owner retained before the native call lives through final completion and
unregister/drain; generation checks alone cannot protect freed callback memory.

No timeout or throughput promise is invented here. Qualification records
bounded test-provider cancellation latency; CL-P2-01 must approve the production
deadline policy if a finite wall-clock limit is required. OS suspension cannot
be modeled as a continuously running timer.

## Bounded import into app storage

Proposed `importBounded(source, destination, limits, cancellation)` belongs in
the filesystem layer, above IO. The destination is a validated app-private
directory owner plus a single valid child name and an explicit create/replace
policy. It cannot be an arbitrary URI or a path escaping that directory.
The caller supplies a positive maximum byte count; there is no unlimited
default. The implementation validates the cap against its counter/file-size
range before reading and uses checked arithmetic. Metadata length is a hint,
never authority to skip the cap or trust EOF.

1. Admit the operation under a bounded concurrency budget, retain the source
   and destination leases, and create a unique sibling temporary file with
   exclusive creation, restrictive access and no symlink following. A system
   temp/cache root is not a substitute: commit must remain on the destination
   filesystem.
2. Read bounded chunks into a fixed-size buffer and write every returned byte,
   handling short writes. Proposed review defaults are a 64 KiB buffer and at
   most two active imports per app storage owner; these are assumptions, not
   approved product limits. Waiting admission is bounded and cancellable.
3. Count actual bytes. At the cap, read at most one extra byte to distinguish
   exact-cap EOF from oversized input, without adding that byte to the file or
   overflowing the counter. Oversized, revoked, unavailable, canceled, IO-error
   or storage-exhausted imports cannot publish a partial destination.
4. At EOF, flush/sync and close the temporary file successfully. Revalidate
   destination identity and the explicit replacement policy, then arbitrate
   cancellation versus commit exactly once. Cancellation accepted before this
   point removes the temp and leaves the old destination intact.
5. Atomically rename the sibling into place, then synchronize the containing
   directory where the provider supports the promised durability. A replacement
   must use the existing private-directory/lease invariants; a generic precheck
   followed by an unprotected path rename is insufficient.
6. Release all descriptors/leases and remove abandoned temporary files on
   precommit failures. A cleanup failure is retained as secondary evidence and
   surfaced for recovery; it does not erase the original error.

The import returns COMMITTED, CANCELLED_BEFORE_COMMIT, FAILED_BEFORE_COMMIT or
DURABILITY_UNCERTAIN. COMMITTED includes destination identity and actual byte
count. Once rename may have committed, cancellation cannot claim that the old
file remains: report committed/uncertain as appropriate. A post-rename directory
sync failure is DURABILITY_UNCERTAIN, following the existing
`DurableReplaceOutcome.mayHaveCommitted()` distinction. Callers reconcile by
identity/journal on restart rather than blindly retrying a replacement. This
import does not promise a transaction spanning the destination and a separate
database; callers need an idempotent durable journal for that relationship.

The existing `replaceRegularChildDurablyForLease` accepts complete `Bytes`.
The new importer needs a streaming temporary-writer/commit seam with equivalent
identity, no-follow, sync and uncertain-commit guarantees. Calling that method
after collecting the whole stream would defeat bounded memory. Preserve that
API and all desktop behavior; approval must assign the new seam's owned path.

Process kill may leave an exclusively named temporary file. A private recovery
record identifies files created by this importer; startup cleanup removes only
verified abandoned entries under the retained private root and never arbitrary
matching user files. A committed but unacknowledged rename is reconciled before
cleanup. Do not depend on normal process exit, an Activity callback or an iOS
suspension callback to flush durable state. Background-task expiration cancels
or checkpoints before publication; a restartable scan stores its cursor in
durable app storage and revalidates external document identities on resume.

## Recommendation for Q2: separate DocumentTree owner

Choose an additive `DocumentTree` owner for user-granted provider documents.
Keep `DirectoryHandle` a local exact filesystem handle. A common browsing
interface may sit above both, but their capabilities and failure modes remain
visible. SAF document ids are opaque, can be provider-specific and are not
POSIX child paths; cloud-backed iOS resources also have availability and access
lifetimes beyond a string. Fabricating inode identity or seek support would
weaken current callers' guarantees.

This recommendation deliberately differs from CX-P1-02's proposed adaptations
Q2 default, an opaque grant owned by `DirectoryHandle`. CL-P2-01 must reconcile
that choice with the adaptations owner and record the decision before any API
implementation. Separate DocumentTree is this draft's recommendation, not a
claim that the existing default has changed.

The proposed owner contains provider identity, an opaque root document identity,
read/write grant flags, grant provenance and an active-access lease. It exposes
bounded/paged enumeration, checked child references and byte-source opening.
Capabilities explicitly describe supported read, write, seek, enumeration,
create, rename and persistence operations. Unsupported atomic replacement,
locks or snapshots return typed unsupported errors. A method does not emulate
a provider transaction with silent delete/copy. Names/display paths are labels,
not authority; every child operation revalidates its grant and provider result.

There are two different lifetimes:

| Owner | Lifetime and release |
|---|---|
| Persisted grant record | app-private durable record of bookmark/URI, flags and provider identity; survives view/process lifetime when native persistence is granted |
| Active access lease | native authorization plus any open descriptors/streams; retained across each operation and released exactly once after its final native completion |

Closing a tree/view releases active leases but does not implicitly forget the
persisted permission. Explicit forget retires the record, prevents new opens
and releases native persisted authority under an app-level registry only after
dependent operations drain. Multiple documents may share a native grant: one
record's close must not revoke another record's authority. A user/OS revocation
can occur at any time and overrides both owners. Persisted does not mean valid,
writable, downloaded or immortal.

On iOS/iPadOS, retain the security-scoped URL and balance each successful
`startAccessingSecurityScopedResource` with exactly one corresponding stop after
all dependent streams/scans finish. Failed acquisition is not a successful
lease and must not be balanced with a fabricated stop. Resolve bookmarks on
relaunch, detect stale resolution, and persist a refreshed bookmark only after
successful access. Bookmark refresh failure must be visible; preserve useful
old recovery information without claiming current authorization. Provider file
coordination/download requirements belong in the checked bridge; do not assume
that opening a resolved URL makes an iCloud item locally available. A locked
device/unavailable protected file is not proof of permanent grant revocation.

On Android, preserve the returned tree/content URI and granted flags; use
`takePersistableUriPermission` only when the result permits persistence. Record
whether persistence actually succeeded. Open native provider descriptors or
streams under the URI grant and close each exactly once; pipe descriptors are
legitimate non-seekable inputs. Reconcile persisted grants on relaunch and
handle provider removal, deleted documents, revoked rights and security errors.
An Activity recreation cannot discard an admitted operation's owner. Runtime
permission states (including pending) and URI grants are separate: a storage
operation must not label pending user consent as denied or prompt in a read
loop. SAF's restricted selectable roots remain restricted; public path tricks
do not substitute for `ACTION_OPEN_DOCUMENT_TREE`.

The picker needs a new additive grant-bearing outcome/operation, with selected,
canceled and failed variants and explicit ownership transfer on selection.
Cancel returns no grant. The existing desktop string outcome remains unchanged.
Final UI7 spelling and asynchronous lifecycle are owned by its contract chain;
this document does not patch `IDirectoryPicker` or promise a synchronous mobile
modal picker. I1 tests use pre-granted URLs; A1 adds real SAF presentation tests.

## Error channels and exact adaptation diagnostics

Existing FileSystemError fields (`kind`, `operation`, `path`, `nativeCode`,
`message`) remain. Append, without renumbering existing error kinds, proposed
`FS_ACCESS_REVOKED` and `FS_UNAVAILABLE`. Revoked means a formerly held grant is
no longer authorized; unavailable means the document/provider/protected data
cannot currently be reached. Neither is successful EOF. A missing document is
`FS_NOT_FOUND` when the provider establishes absence, and a new request without
authority is `FS_ACCESS_DENIED`; an ambiguous native error must retain its
native code and avoid inventing a revocation history. Limits/quota exhaustion
map to resource-exhausted with a distinct operation/message; invalid caps/names
are invalid-argument, and unsupported capabilities remain unsupported.

The `path` field may hold a redacted display locator when no local path exists;
internal opaque identity stays with the owner. Do not log bookmark blobs,
permission-bearing URLs or full private document names by default. Cancellation
is an explicit operation outcome, not a forged IO failure or user denial.
An unavailable result may be retried through explicit policy and fresh grant
validation; revoked access requires an authorized recovery journey. A provider
failure after some bytes were read still fails an uncommitted import.

These are the exact row-7 diagnostic strings from platform-adaptations.md:

```text
DirectoryHandle.openExact is unavailable on iOS/iPadOS: paths outside the app container need a user grant; use GUI.chooseDirectory
DirectoryHandle.openExact is unavailable on Android: shared storage is reached through user-granted content URIs, not paths; use GUI.chooseDirectory and a document-tree handle
```

Emit the relevant typed failure for unsupported ungranted outside-container
path access, not for a valid app-private handle. The suggested picker journey
is unavailable until UI7 lands and must be presented as such. A later grant
opens a DocumentTree, not a path-based escape hatch. Error-kind/diagnostic
tests must compare these strings exactly while preserving native error details
separately. This proposal does not change failure channels of unrelated APIs.

## Delivery, bootstrap and review dependencies

| Packet | Proposed delivery | Gate / remaining obligation |
|---|---|---|
| CX-P2-14, Stage 26 | validated app roots; additive IO stream; bounded app-private import; native error mapping; pre-granted test capability plumbing | CL-P2-01 approval, Windows filesystem landing, Stage 25 hosts/probes, platform filters/cache identity and closure-file triage gates in packet |
| CX-P2-37, I1 | scoped URL/bookmark owner; relaunch/revocation; restartable scans; SQLite kill-during-write evidence | mobile foundation, iOS lifecycle owner and cache identity; pre-granted URLs until UI7 |
| CX-P2-42, A1 | SAF descriptor/tree owners and persisted grants; runtime permission state integration; provider cancellation/recreation | mobile foundation, CX-P2-41 Activity/context owner and cache identity |
| UI7 contract/provider packets | additive grant selection with lifecycle-safe completion and native picker UX | UI2/UI3 and platform shell/contract approvals; no picker implementation in P2-03 |
| CL-P2-01 | approve this design and record adaptations Q2 / WORKSTREAMS §7 Q9 decisions; assign shared paths below | two adversarial reviewers and one parity reviewer, no blocking findings, PLAN approval |

IO and FileSystem are compiler imports. Additions must preserve current symbols,
constructors, import direction and desktop emitted behavior. Implementation
requires the packet's Linux bootstrap fixed point, zero-warning transpiles and
both frontend tests, plus cache-identity/foreign-SDK exclusion checks. Neither
importing every foreign SDK on every target nor changing compiler/runtime to
accept the design is in the provider author's scope. Read current main again
after the Windows filesystem merge before implementing the streaming seam.

Requests to Claude for CL-P2-01:

- Assign the additive error-kind and streaming-private-replacement seam in
  `FileSystemHandles.btrc`: CX-P2-14's listed paths omit that shared file even
  though its steps require revocation/unavailable errors. Resolve the ownership
  gap in packet scope before implementation; no opportunistic edit is implied.
- Confirm the temporary-root query, IO-level result shape and cancellation
  capability boundary without creating an IO/FileSystem import cycle.
- Record adaptations Q2's DocumentTree choice, WORKSTREAMS §7 Q9's approval
  status (not adaptations Q9, which concerns HTTP), proposed
  64 KiB/two-import defaults, and any required production cancellation deadline.
- Route compiler/checked-bridge gaps through REQUEST packets with minimal
  reproducers when implementation can demonstrate them. This draft reports no
  reproduced compiler defect and supplies no ABI or analyzer workaround.

## Simulator/emulator and parity test plan

Every implementation fixture runs through Python and self-hosted frontends on
the intended target. iPhone and iPad simulator runs share the ios family and
record device class; Android emulator records target/API/ABI and provider.
Use controlled test providers for deterministic revocation, pipe reads and
failure injection. A fake provider proves owner logic, not actual OS grants;
native provider cases are separate. Record counts, run ids, raw results and
stand-in status; no fixture below has run as part of this docs-only packet.

| Area | Required scenarios and oracle | Delivery |
|---|---|---|
| Roots | valid roots; absent/relative/NUL/mismatched/inaccessible host values; Unicode child; cache removed and recreated; container relocation across relaunch; no fallback or outside write | P2-14, then real context P2-41/42 |
| Stream | pipe with no seek; unknown/incorrect length; empty input; repeated short reads; embedded zero and all byte values; EOF versus zero-data bug; no snapshot/seek fabrication | P2-14 |
| Caps | sizes 0, cap−1, cap, cap+1; extreme rejected cap; lying length; stalled source; bounded memory and admission; exactly one overflow probe byte; no partial publication | P2-14 |
| Failures | read and partial-write failure, ENOSPC/quota, close/file-sync/rename/directory-sync failures; prior destination preserved before commit and uncertainty reported after commit | P2-14 |
| Cancellation | before admission, blocked read, final EOF, commit arbitration, after rename, view close; one terminal result; native entry/drain barrier and zero leaked descriptors/leases | P2-14, native bridge I1/A1 |
| Traversal | invalid child, symlink substitution, replaced root/target, rename race; no authority from string prefix, URI text or forged host root | P2-14 |
| Kill recovery | kill before/after temp sync, before/after rename and before directory sync; recognize own abandoned temps, reconcile unacknowledged commit, never delete unrelated file | P2-14/I1/A1 |
| iOS grants | balanced successful start/stop, failed start, stale bookmark refresh, relaunch, revocation, cloud unavailable, protected-data unavailable, background expiration/resume; shared lease survives view close | P2-37 |
| iOS durability | SQLite integrity and committed-state checks after kill during write; restartable scan checkpoints; no dependence on exit/suspend flush; pre-granted URL provenance explicit | P2-37 |
| Android grants | SAF selection/cancel, persisted versus transient flags, persistence failure, process death/relaunch, revocation, missing provider, pipe descriptor, Activity rotation and permission pending/denied | P2-42 |
| Shared grant | two tree/stream users, close one while other reads, explicit forget/drain, external revoke mid-read; exactly-once native release and typed result | I1/A1 |
| Diagnostics | byte-for-byte row-7 strings for restricted outside-container access; valid app-private exact handles still work | P2-14 |
| Desktop/compiler parity | existing Linux/macOS outputs and tests, Windows integration, Linux bootstrap fixed point, zero-warning output, foreign-SDK isolation and target-cache poisoning matrix | implementation gate |

Simulators/emulators do not qualify physical locked-device behavior, cloud
availability, real lifecycle pressure or owner-device performance. Native
permission/picker/device evidence remains in its designated packets and owner
runbooks. This draft changes no stdlib, compiler, runtime, catalog, manifest,
workflow or production contract, and does not check the CL-P2-01 approval box.
