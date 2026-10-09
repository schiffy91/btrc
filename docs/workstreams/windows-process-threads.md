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
need bounded release/join/handle cleanup on test exits. Overflow needs an
explicit boundary proof without billions of native iterations. Both frontends
must emit then run strict C11 on Windows x64 and ARM64; WindowsMain SDK-reader
process support is not included.
