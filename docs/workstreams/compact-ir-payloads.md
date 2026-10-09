# Compact fat-tagged IR payloads

Owned source is based on exact `6f1b81d937745ee3a3fbc1be803ffcf1b7e52ba9`. This packet is a private, unqualified implementation draft. The ordinary checkout and index remain unchanged.

The node retains its identity, tag, common operands and cross-cutting storage/continuation metadata. Nine typed optional payload families carry structural fields. The constructor creates at most one owned payload, and payload-free leaf kinds retain null storage. No shared owned payload, managed-return field getter, new child-list traversal, or owning union is introduced. Existing lazy list aliasing and shared-empty misuse guards remain.

The full compiler source scan finds 27 owners referring to IRNode. All moved fields are migrated; the lexical receiver audit finds no stale old field access and all kind/payload/domain writes are constructor-owned. Domain-aware generic walks preserve the original default values and child order. This is source evidence, not a semantic or memory result.

The audited current-product census measured 3,219,828 live IRNode blocks at final demand, occupying 1,236,413,952 allocator bytes. The proposed layout estimate of about 510 MiB savings charges one payload and incoming edge per payload-bearing node. It is unmeasured, adds roughly 1.25 million allocations, and cannot alone establish the 1.5 GiB product target.

Required next proof: run authentic 6f canonical/lifecycle baseline drivers; validate all constructor/default/rare-kind paths; build candidate Model through both frontends; inspect concrete ARC visitation/destruction and cast-store ownership; run focused semantics and original compiler/corpus gates; then establish exact current-product emitted output parity and actual allocator, peak-memory and instruction effects. The separate flow-retention packet's arraySize safety-root traversal must be retained when integrating the two source changes.
