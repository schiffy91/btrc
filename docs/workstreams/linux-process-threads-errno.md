# Linux ProcessThreads: directory-read failure

Exact independent base: `36b647f079ed7338e51b119a11046eb222dd4877`.
Packet owns the explicitly named compiler-import Linux provider; there is no
PR70 dependency and no Android selector or qualification.

## Contract and source finding

`ProcessThreads.count()` promises the calling process's live thread count,
including its caller, or -1 when the host cannot determine it. The Linux owner
uses real `/proc/self/task` entries but currently treats every NULL from readdir
as end-of-directory. An initial read error therefore returns zero and a later
read error returns a partial successful count. This is a source finding until
the retained baseline is executed on Linux.

The existing `FileSystem.DirectoryStream.next()` convention clears errno before
each readdir and reads it when NULL is returned. The proposed Linux fix uses that
convention and snapshots the final read error before closedir, whose errno must
not replace the read outcome. Existing name filtering, opendir failure, close
call count, API and provider/native manifests remain unchanged.

## Real native regression and proof boundaries

The dedicated Linux ProcessThreads pytest owner packages the real SDK control
header through NativeBindingPackage and reuses the unchanged BackgroundJobs
transpilation helper. Its generated-unit-only forced-header interception is retained:
the separate C probe calls the genuine opendir/readdir/closedir declarations from
Linux's dirent.h and reads the actual process directory. No fabricated dirent
layout, copied count implementation, replacement compiler or extra executor is
introduced. A selected fixture control header uses the canonical native reader.

Each native run requires successful real enumeration/closure, EIO before any
entry, EIO after an actual non-dot entry, opendir refusal without a close,
stale errno across successful reads/EOF, and a successful recovery call.
The probe deliberately changes errno in closedir in both directions. The original
baseline must fail the explicit initial-EIO count==-1 assertion; candidate must
complete all cases, including partial-EIO and exact opened-stream closure.

Planned focused command in the existing Linux Nix host (not executed here):

```sh
python3 -B -m pytest src/tests/python/test_linux_process_threads.py --compilers python,btrc
```

Four rows: both frontends by plain/ASan+UBSan, existing strict C11 flags,
180-second transpile/compile/link and 90-second native bounds. No skips permitted
on Linux; other platform manifests explicitly classify the Linux-only fixture.
The test-only baseline is retained separately from the candidate provider fix.
Reference baseline may be run first to establish the native defect; all four
candidate rows and ordinary BackgroundJobs controls remain required. Since this
provider enters the compiler import closure, use a fresh candidate selfhost
binary and retain §3.4 bootstrap and host-entry C parity requirements. No local
Mac execution substitutes for Linux evidence.

No test collection, compiler, SDK reader, native build, sanitizer execution,
bootstrap, publication or complete qualification has occurred for this packet.

## Ownership successor

The old unpublished packet is preserved. This successor changes no shared
BackgroundJobs test source: PR67 and PR70 retain their existing claims. The new
module imports only the established fixture path, 180/90-second constants and
transpilation helper; it explicitly requires the reader and creates the native
control package before transpilation. Its two-object Clang build keeps forced
SDK interception confined to generated code, so the probe still calls real libc.
Provider and all four fixture blobs are byte-identical to the reviewed donor.
No BINDINGS mutation, monkeypatch, production wrapper or new test harness.
The original BackgroundJobs tests remain qualification controls, unmodified.
