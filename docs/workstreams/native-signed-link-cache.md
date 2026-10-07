# Native signed executable link reuse

Packet: native-signed-link-cache. Branch: `codex/native-signed-link-cache`.
Base: `dff538ef502f4a074c3019f677220810e4061225`.

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
