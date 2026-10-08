# Native signed executable link reuse

Packet: native-signed-link-cache. Branch: `codex/native-signed-link-cache`.
Base: `dff538ef502f4a074c3019f677220810e4061225`.

Current outcome: real certificate-backed downstream paired regression passes
on source override `3c5a89ec`; locked-product and final combined qualification
remain open. The chronological pending statements below describe their earlier
checkpoints; the final section records the actual product proof.

Owned paths:
- `tools/native_plan.py`
- `src/tests/python/test_native_link_reuse.py`
- `src/tests/python/test_native_plan_builder.py`
- `docs/workstreams/native-signed-link-cache.md`

The integrator explicitly assigned this bounded native-builder repair under
PLAN D29, including the normally integrator-owned native-plan file. Existing
Windows work remains on its original branch; this packet reuses its clean clone.
No publication is authorized until the integrator coordinates a CI slot.

A real downstream Make build reproduces a warm link on both compiler frontends:
zero units compile but one link runs. Its caller signs the executable after
native-plan stores the link receipt, so the receipt correctly rejects the
changed executable bytes on the next build. This is an output-finalization
ordering defect; the executable content check must remain strict.

The existing native builder will accept explicit Darwin signing configuration,
resolve one unambiguous certificate identity, sign and verify its staged output,
and only then publish the executable and its receipt. Credential access and
keychain unlocking remain caller-owned. Cache identity includes the selected
certificate, signer and signing configuration. Signing is never an arbitrary
shell hook. Unsigned and non-Darwin behavior remain unchanged. A signing failure
must preserve the prior executable and receipt; unchanged signed outputs must
retain bytes, inode and mtime without another link or sign operation.

Started 2026-10-08. Initial free space 78,360,128 KiB (above 80 GB decimal).
Host: Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0.
Baseline and focused tests run only in the secondary lane assigned by the
integrator; all native work pauses before its bootstrap phase. Full combined
qualification, product caller integration and locked release proof are pending.

## Implementation and evidence

`DarwinSigning` supplies an identity, optional already-unlocked keychain,
optional identifier, and signer executable. The CLI exposes the corresponding
`--codesign-identity`, `--codesign-keychain`, `--codesign-identifier`, and
`--codesign-tool` flags. An omitted identifier omits the codesign flag and
preserves existing policy; the staging path already retains the final basename.
The builder resolves an exact certificate name or fingerprint, includes
that certificate and the signing configuration/tool content in the receipt,
and verifies the staged signature before publishing it. It revalidates signing
context before accepting a receipt hit and before/after signing. No keychain
unlock or credential-file reading moved into the builder.

The downstream reproduction is retained at
`~/.cache/btrc/plan-consolidation-2026-10-07/btrsmith-build-artifacts-dff-second`: both
original frontends fail the unchanged warm-link assertion (one link instead of
zero), and both final signed executable digests differ from their link receipts.
This is diagnostic source-override evidence, not qualification of the product's
unchanged compiler lock. The integrator owns the product caller change and its
real certificate-backed paired rerun.

Local logs live under
`~/.cache/btrc/plan-consolidation-2026-10-07/native-signed-link-cache/`.
The initial unmodified baseline (`baseline.log`) had 10 passes and 13 failures:
Nix purity rejected library search paths under the default pytest temporary
root. Retesting with an explicit clone-local `--basetemp` repaired the test
environment; all six selected unchanged unsigned/library baseline cases then
passed. No baseline failures were suppressed.

The first focused implementation run (`focused.log`) had 14 passes and five
failures: three exposed a missing `=` prefix for literal codesign verification
requirements, and two exposed an invalid test assumption that ad-hoc designated
requirements survive executable-content edits. The second (`focused-r2.log`)
had 12 passes and one failure: default linker-derived ad-hoc identifiers can
also change with content. Tests now compare staged signing with the caller's
existing policy for the same content, require exact warm/touch retention, and
require an explicit identifier to remain stable across edits. No new default
identity or across-edit TCC guarantee is claimed.

Independent source review identified a stale-context receipt-hit path. The
repair now validates signing context immediately before accepting the hit; a
deterministic test changes the signer after receipt validation and proves
fail-closed behavior without replacing the executable or receipt. The reviewer
rechecked that correction and found no remaining actionable source blocker.

Tests include real Darwin clang/ad-hoc signing, same-size/mtime signer and output
tampering, sign/verify failure retention, warm/touch/edit behavior, deterministic
certificate resolution/ambiguity/rotation, and early rejection of unsupported
hosts or targets. Deterministic certificate-listing tests do not count as actual
product certificate evidence. Full product, Linux, and final-tree qualification
remain integrator-owned and pending.

Final focused validation:

- `link-r3.log`: all 31 native link-reuse tests passed in 101.78 s, including
  the entire existing unsigned/library suite and the new signed cases.
- `builder-r3.log`: six signing unit tests passed; two new host/target rejection
  fixtures failed their initial noncanonical JSON before reaching the behavior
  under test. Their serialization was corrected to the existing canonical
  fixture format, without a production change.
- `builder-r4.log`: all eight signing configuration tests passed in 0.23 s
  (141 unrelated builder tests deselected).
- Ruff lint, Ruff formatting and `git diff --check` passed for the owned source.

No heavy self-host compiler build, guest, broad gate, CI publication or product
lock change was performed in this packet. The current integrator-approved
secondary lane was used; there was no bootstrap overlap or outstanding wait
when these focused tests finished. Existing baseline and failed-attempt logs
and scratch fixtures are retained.

Implementation and focused validation completed 2026-10-08 00:02:19 UTC.
The packet is ready for integrator review/combination and the unchanged real
product paired regression, not a claim that all repository goals are complete.

## Existing local certificate policy correction

The integrator's unchanged paired product regression against `490507a9` failed
both cold builds before native compilation: the valid-only identity lookup
returned no selected certificate. Evidence is retained at
`~/.cache/btrc/plan-consolidation-2026-10-07/btrsmith-build-artifacts-signed-490507a9`.
Read-only public `security find-identity -p codesigning` output lists the
existing BTRSmith Build Signing certificate with fingerprint
`d3d5aa4395e93cc694c136dd3f327db4da18d703` and diagnostic
`CSSMERR_TP_NOT_TRUSTED`; adding `-v` excludes it. The product's existing
selection deliberately uses the lookup without `-v`.

The resolver now preserves that caller policy: lookup without `-v`, accept
numbered identity rows with an optional public diagnostic suffix, and require
one exact selected name/fingerprint. This does not change system or keychain
trust, unlock any keychain, read credentials, or weaken strict signature and
exact-leaf verification. The builder still signs with the resolved fingerprint.

Two deterministic cases containing the observed public output (name and full
fingerprint selection) failed against `490507a9`, then passed after this repair.
All ten signing units pass in 0.59 s; lint, formatting, and diff checks pass.
Read-only resolution against the actual existing keychain also selects that
same fingerprint. Public listings/context and red/green logs are retained in
the packet evidence directory. This proves lookup compatibility; the integrator
still owns actual paired named-certificate signing and warm-cache proof.

Independent read-only review found no blocker in the resolver correction;
unique selection, repeated-section fingerprint deduplication and strict
exact-leaf verification remain intact. Review and focused validation finished
2026-10-08 00:09:42 UTC. No native build or signing stage ran in this correction.

## Actual paired product regression passed

The integrator ran the two original, unchanged
`BuildArtifacts.*BuildArtifactsTests.test_import_content_touch_edit_and_removal`
cases through both compiler frontends: **2 passed in 16.093 s**, terminal exit 0.
Evidence (manifest, exact tools, per-step output/signature capture, and unittest
log) is retained at
`~/.cache/btrc/plan-consolidation-2026-10-07/btrsmith-build-artifacts-signed-3c5a89ec/`.

The exact source combination was product
`e00c61d2cb38286eafece19f7107a3dd5c27230d`, native-plan provider
`3c5a89ec3529491bfe44c5988b14a8c56fa854b7`, and compiler source
`dff538ef502f4a074c3019f677220810e4061225` with the existing compiler binary
SHA-256 `85c4029079568b3a73fbd6853148d5b1e8038a05224e6e75c4ccd3768511e1c3`.

For both frontends, cold/warm/touch retained the same signed executable identity
and designated requirement, and warm/touch performed zero links. Each of the
five successful build phases retained the same designated requirement,
`identifier btrsmith and certificate leaf = H"d3d5aa4395e93cc694c136dd3f327db4da18d703"`,
including content edits. Signature checks used the existing named certificate,
not ad-hoc signing. The original removed-import negative assertion also passed;
no test assertion was weakened. Evidence retention reported no errors and all
three source trees were clean at the run's end.

This closes the reproduced signed warm-link defect for the measured source
combination. It remains diagnostic source-override evidence: the product's
compiler lock is still `cdf9d952011d5ee93bcdbdb9bd31d58d15f072ef`. It does not
qualify the product shell, locked package, complete release suite, or final
combined compiler tree. Those integration gates remain with the integrator.
This report-only update changes no provider or product source and reruns no tests.
