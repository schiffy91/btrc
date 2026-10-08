# Canonical tuple declarations across both compilers

Branch: `codex/compiler-tuple-canonical-order`. Base: `277b9cfc`, including
paired interface-parent repair `808592c9`. Compiler declaration owners and tests
are claimed in WORKSTREAMS.md. No main integration or qualification is claimed.

## Observed failure

Hosted run `37715597772`, root source `71a22734`, reports one failure and
5,849 passes in the self-hosted suite: `TupleGenericInstanceType.btrc` no longer
emits identical C through both compilers. The Python compiler records the
inferred `(int, int)` result of `numbers.both()` while scanning the ordinary
program. The self-hosted compiler records that shape later, in the concrete
`Box<int>` declaration. Canonical generic ordering now visits `Box<char>` first,
exposing this difference in discovery order. The fixture previously depended on
`Box<int>` being the first demanded instance.

The original log is retained in `hosted-71-current/btrc.log`. This is a real
parity failure; the identical-output manifest and corpus assertion stay intact.

## Intended repair and acceptance

G12 in `docs/design/stage-b-reuse-keys.md` already requires canonical tuple
declarations. Preserve both collectors' complete concrete shape sets, then
visit roots in emitted-symbol order with nested tuple dependencies before their
containing tuple. The existing lowering owners emit structured IR in that order;
the C emitter remains unchanged. Keep conservative shared-declaration cache
identity until its separate precise-reuse proof is complete.

Required evidence: fixture-only failure, reference/self-host parity for multiple
generic instances and nested shapes, strict-C compilation/execution, ordering
independent of body discovery, and the existing incremental tuple guard. Rebuild
the self-hosted compiler from the actual changed source. Recapture and review
all frozen boundary records before final combined-tree gates. No performance
improvement follows merely from changing the declaration order.
