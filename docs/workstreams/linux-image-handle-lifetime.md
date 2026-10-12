# Linux image handle publication lifetime

Packet: CX-LINUX-IMAGE-LIFETIME. Base 36b647f079ed7338e51b119a11046eb222dd4877;
donor bac92b20830e5adde31c638a7dd95cb917da8721. The same Codex writer extracts
only two exact donor source blobs from the held UI2 composition. No UI2 interface,
manifest or harness dependency is imported; the donor remains untouched.

## Contract and repair

IImageHandle already promises views keep their own reference after handle close.
Main's Linux view instead checked handle openness while painting, making the
published image disappear. The view now retains decoded pixels and stable texture
identity independently, and releases them on clearing or completed view closure.

Closed-handle republication rejection follows existing MacOSImageView/nativeImage
resource behavior; it is not explicit portable image-contract wording. No public
API change. Source review confirms failed replacement is checked before mutation;
the pixel regression is not a concurrent-close, race, stress or reclamation proof.

## Baseline and original regression

Claim 141a15f408fe6f83e955734e58624a5d78b9a80e precedes test-only baseline
cc50fbb3e8ff335742c13703e100892aee16f696 and candidate
2a338a6a0491afcbcd2e4749edf8ce2119802cfa. Baseline retains main's provider;
only provider/report differ between baseline and candidate. Original controls,
input, capture and shutdown checks remain. The old expected-disappearance
assertion is replaced because it contradicted the existing retention contract.
New checks require retained RGBA pixels, stable identity, refusal of closed-handle
republication and explicit clearing.

Formatter/import/diff and independent source review passed before execution.
The unchanged test_linux_gui_controls driver supplies four frontend/sanitizer
cells with the original 600-second transpile and 180-second native deadline.

## Actual local baseline and candidate qualification

The Linux ARM64/X11 baseline completed four intended native SIGABRT failures,
zero skips/errors. All reached the complete closed-versus-artwork RGBA assertion
after the visible-green control. Emitted C binds Python condition 97/line50478 and
selfhost condition 93/line50620 to that precise predicate. Baseline tests receipt:
094b3900f59abeb65e919310f7f626b7c6faae8d767ee85fcb7da4d15b779215.
Python C SHA256:7fc5a44039f2630b990c1a5a3d680e9c35ea59637d22a3ace1d5189a75c5147b.
Selfhost C SHA256:b54041033d3df5a37c0a8a28489c4d7c40f1e1c60a05ce3c62a257098be19c2f.

Candidate completed all four Python/selfhost × plain/ASan+UBSan native cells:
4 passed, zero failures/errors/skips. Both rows independently built fresh canonical
selfhost binaries and passed the paired Hello controls. The original complete
fixture checks passed, including retained pixels/identity, closed republication
refusal, explicit clearing and existing input/shutdown assertions. Source and
fixture bytes remain fixed; no skip fragment is needed.

Candidate tests receipt:
6d47a39b35d6bfa30c373f9c6361a220e4afa48eb81487c562ceb4e13f63dccb.
Final result:
e3f2fbdf3b2c0fc1e9b74dc546229b5b01d7eb180cd6bfee47837756b65284ec.
Root audit (CLEAR):
6664975b282bd24ecbf902611c76a76682321c6bb9dc88c74587cdb7c680674f.
Evidence is retained under
`linux-image-lifetime-2a338a6a-local-v2-attempt-1`; root audit is in
`linux-image-lifetime-attempt1-final-audit/root-audit.json`.

The audit checked 110 host commands, 9,967 output hashes, unchanged inputs,
eight retired containers and absent process groups. The VM was stopped with
its resource allocation unchanged. Exactly 24 nonzero owned-container absence
probes are expected cleanup evidence. Correcting the auditor's initial all-zero
assumption changed neither the runner nor any native result. Both independent
fresh builds produced the same binary hash; this is not a reuse claim.

## Hosted baseline and remaining acceptance

Hosted baseline wave: 22 successful jobs, 5 skipped, 3 failed. Linux 38206492316 unit:
7243 passed/4 failed/3128 skipped. X11:320 passed/4 failed/199 expected skips.
Wayland:318 passed/4 failed/199 expected skips. All four GUI-controls cells fail
in each session; the uploaded GUI artifacts lack generated C/binary identity, so
they alone do not establish the exact source predicate. The local retained-C
proof establishes scoped causal RED; matching hosted line/condition labels do not
retroactively fill that provenance gap. Earlier hosted audit files remain intact.

Final candidate-head hosted gates/skip reports and X11/Wayland sessions remain
required. Local ARM64/X11 pixel and injected SDL evidence is not physical input,
other-platform acceptance, full UI2, race/stress or heap-reclamation coverage.
No compiler/runtime/generated/manifest/workflow or additional test changes.
