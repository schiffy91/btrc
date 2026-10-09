# Compact tagged IR payloads

Packet: CX-HARMONIZE-COMPACT-IR-PAYLOADS
Base: 6f1b81d937745ee3a3fbc1be803ffcf1b7e52ba9

Status: claimed before source edits; implementation and qualification pending.

The current-product diagnostic retained 3,219,828 unique live IR nodes using
1,236,413,952 allocator bytes. A tagged core with one optional typed payload
models about 510 MiB savings after charging payload headers and incoming edges.
This is a planning estimate, not measured savings or the 1.5 GiB target.

The model keeps node identity and frequently used expression fields. A complete
kind/field read-write audit precedes consumer migration. Absent-field reads must
retain defaults without allocating; writes must enforce the matching domain.
No shared owned defaults, unsafe cross-kind cast, fresh per-node child lists or
new runtime/language semantics are permitted. The extra payload allocations
and ARC edges require instruction and peak-memory qualification.

Root owns compiler/native gates; no test or build has run for this packet.
