# Windows process thread count

Source draft against `3e02deba`; no provider projection or native test has run.
The existing Toolhelp importer prerequisite is independently qualified through
reference projection; its full paired retry remains pending. This draft does not
change Windows worker-pool behavior or the count()/−1 public API.

The provider owns one real Toolhelp snapshot, resets the input record size before
every enumeration call, checks the SDK-derived owner-field extent before reading
that field, and filters GetCurrentProcessId(). It rejects counter overflow and
unknown/empty results. It captures GetLastError before a single CloseHandle
attempt; only ERROR_NO_MORE_FILES plus successful close is a completed result.
The header provides SDK includes and one SDK-derived extent constant, no wrapper
implementation or fabricated ABI. Manifest provider/binding rows remain pending
a final fragment commit.

Required native behavior: held real threads increase and restore the measured
count, a foreign process's held threads are excluded, and successful enumeration
uses real SDK operations. Targeted test-only interception must prove failed
snapshot opens do not close, short records are rejected before field reads,
dwSize is reset, both enumeration failures reject, and CloseHandle is attempted
once even when it fails or overwrites last error. All child threads/processes
need bounded release/join/handle cleanup on test exits. Overflow has a structural boundary proof: the int counter starts at zero, its
only update is +1 after an equality check against the actual imported INT_MAX,
and no other write can put it outside [0, INT_MAX]. The equality path fails
before arithmetic. This is not a runtime overflow-branch claim; no reduced
constant or test-only production helper is introduced. Both frontends
must emit then run strict C11 on Windows x64 and ARM64; WindowsMain SDK-reader
process support is not included.

The native fixture and explicit two-stage driver now live in the existing
background-jobs test owner. `WindowsProcessThreadsFixture.project` requires an
explicit real SDK reader and immutable selected frontend, emits for x64 or ARM64,
and seals the original C/plan plus native fixture and copied header hashes.
`run_native` requires actual matching-architecture Windows and a supplied pinned
Clang-compatible C command. It uses a VFS overlay for only the two authenticated
project headers; emitted C is not rewritten and native SDK headers remain real.
The allocated qualifier must pin that projection receipt. No new default pytest
rows or platform skip claims are introduced; the explicit native stage has not run.

The real-thread trial checks +3 then restoration; the foreign child contributes
at least four actual snapshot records while leaving the parent's count unchanged.
The child waits on release or the exact parent-process handle and has its own
bounded deadline. Test-only interception covers open/first/next/close failure,
short foreign records, valid shortened records requiring size reset, empty and
foreign-only results, and close overwriting last error. A close-failure injection
still performs the real close to avoid leaking the fixture handle. No SDK layouts
or production return values are replaced on the successful real-operations path.
