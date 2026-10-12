# Linux ProcessThreads: directory-read failure

Exact independent base: `36b647f079ed7338e51b119a11046eb222dd4877`.
Packet owns the explicitly named compiler-import Linux provider; there is no
PR70 dependency and no Android selector or qualification.

## Contract and source finding

`ProcessThreads.count()` promises the calling process's live thread count,
including its caller, or -1 when the host cannot determine it. The Linux owner
uses real `/proc/self/task` entries but currently treats every NULL from readdir
as end-of-directory. An initial read error therefore returns zero and a later
read error returns a partial successful count. The retained Linux baseline reproduces the initial-read error on both
frontends with and without sanitizers; the repair passes the complete fixture.

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

Focused test owner in the existing Linux Nix host:

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

The local qualification below executed all four error cases plus 18 unchanged
BackgroundJobs control cases. Hosted final-head gates, bootstrap and host-entry
C parity remain required; this local result does not replace them.

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


## Completed local Linux qualification — 2026-10-12

Baseline `19ae46e00772ba76f4ee91b34edac0a84190bd01` and candidate
`07cc018a8c70e64ea0568b27ad32bc70dfacaa16` each used a fresh canonical
Linux compiler build and paired Python/selfhost Hello controls. The original
180-second transpile/compile/link and 90-second native test bounds were retained.
Both rows executed exactly the same 22 collected cases with zero skips or setup
errors, including the original BackgroundJobs tests without source edits.

Baseline: 18 controls passed and all four fault cases aborted at the exact
`initial == -1` assertion. Retained generated C binds condition2/line86 in all
four cases. The original runner receipt remains failed because its diagnostic
parser expected `main:` while libc printed `int main(void):`. Independent offline
audit `c6b81315b6b078717e830d0da60aad7e6e7cc0f9b4258d4379580642e4609de3`
authenticates those native failures, the generated predicates, sources, outputs,
compiler controls and cleanup. Neither the failed original receipt nor its
executed recipe was rewritten, and no baseline rerun was needed.

Candidate: **22 passed, zero failures/errors/skips**. All four Python/selfhost
by plain/ASan+UBSan fault programs complete, covering initial and partial EIO,
opendir refusal, stale errno at successful EOF, closedir errno interference,
exact stream closure and recovery. The other 18 BackgroundJobs cases also pass.
The candidate-only continuation retains the original test source, selection,
timeouts, toolchain and process lifecycle; it performs its own fresh compiler
build because the changed provider is in the compiler import closure.

Candidate binary SHA256 `858c254a12bac0474342b0f9be5e5286554d81313df5d1814cff4d91842a9dba`;
final result `972d32cc9473f0e3ce4b7a5f4c4c6b7c122425319faacf76403273d229017dca`;
native tests receipt `118eff3fef8b2d4318f2d6c35a8f6d5a8a36d9bd2b2dfded5e4994826942ea87`.
The baseline compiler binary was `28ecd1602f29eb524da180b0d0a3fc8995982ae9cd32f3f66ed133221bfe077e`;
the distinct candidate binary is expected and is not substituted for baseline
evidence. Independent candidate audit
`9607f7bf17ed63f7108f76b921336cffb68419c3cc9da812abbeda879fbc2df3`
verified all 22 case identities, 48 input pins, 4,513 source files, 4,952 output
hashes and 62 reaped host commands. Four owned containers were retired, all
process groups were absent, and the VM stopped with unchanged resources. Twelve
expected nonzero container-absence probes are cleanup evidence, not test failures.

This is local Linux ARM64 behavior evidence. Final hosted qualification of the
published source, compiler-import bootstrap/host-entry parity, integrator landing
and full final-tree gates remain open. It does not establish Android behavior,
other platform thread counts, physical-device evidence or completed MVP goals.
