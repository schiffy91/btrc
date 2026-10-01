# Design: module reuse and parallel module compilation (M11a + M10)

Status: **in progress — Stage A implemented in both compilers
(`--module-units`) and measured on BTRSmith; product integration and Stages
B/C open**.
Owner milestone: PLAN.md bucket 1, M11a with the M10 concurrency contracts.

## Why the design is staged

Both compilers splice every import into one source string, parse one
`Program`, analyze it once, lower it to one `IRModule` and only then split C
into line-packed units. Two read-only audits (September 22) established which
facts cross declaration boundaries. They decide the order of work.

### Measured workload shape

BTRSmith (`src/BTRSmith.btrc`, strict imports, resolved by the reference
frontend): **444 source files, 100,202 lines, 435 import/include SCCs**. The
largest SCC has 5 files (4,715 lines, `Library.UI`); the next has 5 files of
the sqlite package. 110 files are stdlib. The longest dependency chain,
weighted by lines, is **13,332 lines**, about 13% of the program. The import
graph is therefore almost a DAG of single-file groups: module-level reuse is
not blocked by a whole-program cycle, and the line-weighted critical path
bounds ideal group parallelism at roughly 7.5×. This is a structural bound,
not a speedup prediction.

### Analysis reads other declarations' bodies

The analyzer is not declaration-local:

- raw-borrow proofs (`OwnershipAnalyzer._raw_parameter_is_borrow_only`) walk
  a callee's body and read that body's `node_types`, transitively;
- consuming-parameter detection (`owned_transfer_param_indices`) reads the
  callee's leading statements; IR lowering calls it too;
- native-invocation locality recurses into callee bodies;
- the realtime analyzer scans every callable body, whenever any `@realtime`
  root exists, and solves a program-wide fixed point;
- generic closure rescans template bodies with their annotations;
- callee default-argument and field-initializer annotations are produced by
  the defining declaration's body pass;
- many rules key on `body is None` (prototype, hosted/FFI routing, trusted
  prototypes, required concrete bodies, auto-property storage).

Stripping foreign bodies would silently change semantics. Restricting body
analysis needs persisted per-callable summaries for every item above.

### Lowering reads program-wide facts

- setjmp volatility and capture rejection solve a least fixed point over the
  lowered IR of every function (`FunctionEffectCatalog`), with conservative
  effects for anything only declared;
- `program_uses_trycatch` scans every declaration and changes cleanup
  registration and ARC descriptors everywhere;
- cycle metadata closes over the whole class table;
- stdlib reachability and generic instance tables are program-wide;
- the realtime verifier follows callees transitively through defined
  functions;
- lambda, cleanup-slot and GPU-dispatch names come from per-session counters,
  and helpers, descriptors and default-argument helpers are deduplicated per
  session;
- `main` gets `__btrc_flush_cycles` only if its own module releases cyclable
  values.

## Staged delivery

**Stage A — module-owned lowering under whole-program analysis.** Keep the
existing whole-program analysis. Partition the program into compilation
groups and lower each group in its own lowering session. A group's unit
defines only what the group owns and declares everything else. Program facts
(exception use, class hierarchy/cycle facts, generic demand, stdlib
reachability) are inputs to every group. Cross-group lowering summaries
(setjmp `FunctionEffect`s, realtime-verified callees, cyclable releases) are
published by the defining group. Validate on the full language corpus through
both compilers, then add per-group artifacts and reuse.

**Stage B — module-owned analysis.** Replace whole-program body analysis of
unchanged groups with persisted per-callable analysis summaries for every
cross-declaration fact listed above. Stage A's artifacts, keys and scheduler
are unchanged; only their inputs shrink.

Stage B requirements found on September 23 (self-hosted analyzer; the
reference analyzer has the same shape). An edit build today is bounded by
whole-program front end (about 7 s) and analysis (about 20 s, of which body
validation is 9.7 s). Skipping an unchanged group's body analysis needs:

- **Stable node identities.** Validation records facts keyed by a node's
  address: generic constructor types taken from context
  (`Analyzed.genericConstructorTypes`), hosted-call classification
  (`hostedCallKeys`), constant array bounds (`constantArrayBoundKeys`) and
  array iteration capacities (`arrayIterationCapacityKeys`). Type inference,
  the generic closure, the realtime analyzer and IR lowering all read them.
  A persisted group record must key them by structural position within the
  group and restore them before the generic closure runs.
- **Per-group generic demand.** Both generic phases build the program's
  instance list by scanning every body, and lowering consumes that list in
  order. Each group must publish the instances its bodies request, and the
  program list must not depend on which groups were scanned.
- **Deferred symbol checks.** Generated-symbol references collected during
  body walks are checked against the final instance set; a skipped group's
  references must be re-checked from its record.
- **Callee body facts.** A caller's validation walks callee bodies for
  raw-borrow proofs, which the interface digest does not capture; those
  proofs join the per-callable summaries listed above.

Both analyzers were mapped on September 23. Four facts shape the plan.

- **Node-keyed facts cross groups.** Several facts are keyed by node
  identity and read across groups: a callee's default arguments are lowered
  and realtime-visited in the caller, and `constantArrayBoundKeys` covers
  foreign field and global bound nodes. The reference analyzer's
  `node_types` values alias other declarations' type nodes.
- **Some results depend on analysis order.**
  - Raw-borrow proofs are cached per run and answer a call cycle with a
    provisional `false`. In the reference analyzer they read the callee's
    `node_types`, which do not exist yet when the callee comes later in
    program order.
  - Constant array bounds of a class declared later are not visible to an
    earlier caller.
  - In the self-hosted analyzer, generic method-call arguments on template
    nodes are last-writer-wins across instances.
- **Body analysis rewrites the AST.** It upgrades generic arguments, infers
  `var` types, fills lambda captures and merges defaults, so a skipped
  group's AST still needs those patches.
- **Instance demand is order-sensitive.** The instance lists are ordered and
  their de-duplication suppresses fan-out depending on earlier demand. A
  record therefore replays demand calls in program order; it does not store
  the resulting lists.

The plan: a group that is lowered is analyzed live. A reused group replays a
record at each declaration's place in program order, with its diagnostics,
demand calls, AST patches, node facts keyed by structural position,
deferred symbol references, realtime events and the raw-borrow summaries it
consulted. Delivery order:

0. **Groundwork.**
   - Make raw-borrow proofs order-independent (solved after every body is
     analyzed).
   - Make template call arguments per instance.
   - Add a structural node index per group (declaration ordinal plus
     pre-order position, verified by kind and relative position), and a
     differential harness that replays every group and compares every
     analysis table and emitted unit with live analysis across the corpus.
1. **Skip body validation** for reused groups (about 10 s of the
   self-hosted edit build).
2. **Skip the generic body scans**, replaying demand (about 5 s).
3. **Skip the realtime scans**, replaying events; the fixed point stays live
   (about 3 s).
4. **Key reuse by the declarations a group consulted** rather than the
   program interface, so a signature edit invalidates only its consumers.

Stage B alone does not reach the 10 s edit budget. After it, an edit still
parses every file, reads native headers, builds visibility and lowers the
declarations session. Per-file parse and header caches are separate work.

#### Prior work and resulting changes (September 24)

A survey of published work and production compilers changes the plan in
six ways.

- **Identity by declaration path.** Record keys are
  `(group, declaration path, index local to the declaration)`, not a
  position within the group. A position shifts every key below an edit;
  rustc, Zig and Nominal Adapton key by stable names for that reason.
- **Two hashes per declaration, and recorded lookups.** Each declaration
  has an interface hash and a body hash, and each group logs the name
  lookups its analysis made together with their answers (Zwaan et al.,
  OOPSLA 2022). A group re-validates when its own body changed or a
  recorded answer differs. A dependency's changed source alone does not
  make it stale. This replaces the program-wide interface digest in record
  keys (slice 4) and moves it earlier.
- **Summaries with early cutoff.** Setjmp, realtime and raw-borrow
  summaries are keyed by the group's own body and the summaries it
  consulted, never by dependency sources (Leino and Wüstholz, CAV 2015;
  Infer). The setjmp solve already works this way. Cross-unit fixed points
  restart from clean groups' recorded summaries rather than retracting
  facts.
- **A durable tier.** The standard library and native headers are durable
  inputs, as in Salsa. When their combined hash is unchanged, their groups
  replay without being revisited. Native header import (about 3 s) gets its
  own cache keyed by header content, like clangd's preambles.
- **A correctness gate before speed.**
  - A scripted edit-sequence harness requires incremental output to equal a
    clean build's after each edit (Zig's incremental test tool). The
    function-body comparison added for M11a is its first check.
  - Stage B falls back to full analysis when many groups are dirty, since
    updating a large change can cost more than recomputing it.
  - When a record is ambiguous, it is invalidated.
- **No general query engine.** With a nearly acyclic graph of single-file
  groups, fixed per-group records with explicit hashes are the lower-risk
  route. rustc pays 10–20% on cold builds and hashing is its largest
  incremental cost.

#### Slice 1 implementation design (self-hosted compiler first)

*Measured basis.* A self-hosted module-unit edit compile spends 9.8 s in
body validation. Every identity-keyed fact the reference analyzer records
maps to exactly one structural position: 311,000 facts on the compiler's
own source and 306,000 on BTRSmith, none unreachable and none shared.

*Structural positions.* `AstStructure` in `syntax/Identity.btrc` walks every
`Node`-valued field in declaration order, and a structure test keeps that
walk equal to `Node`'s field list. A position is (declaration path,
pre-order index within the declaration). The declaration path follows the
research recommendation: the source file plus the declaration's name path,
with an ordinal only to separate same-named declarations such as
prototypes.

*When a group qualifies.* The key is computed after registration and before
validation. It covers:
- the compiler identity;
- options;
- the group's source digest;
- the analysis interface digest, which is the position-free rendering of
  every declaration with bodies elided (`programDigest`'s interface part,
  computed before analysis instead of after).

Groups the edit changed, and groups without a record, are validated live.

*The record.* Written only after a build that passed, it holds for each
declaration of the group, in program order:
- node facts, as a position plus a value:
  - the positions in `hostedCallKeys`, `constantArrayBoundKeys` and
    `arrayIterationCapacityKeys`;
  - `genericConstructorTypes` and ordinary `methodGenCallArgs`, whose values
    are serialized TypeExprs. A value carrying an array-bound expression
    makes the group non-reusable;
- deferred generated-symbol references, as a position plus the decision
  inputs;
- the raw-borrow summaries the group consulted, as callee path, parameter
  and result.

Facts a declaration writes about another declaration's nodes, such as a
callee's defaults, are stored under the owning declaration's path.

*What body validation leaves behind (self-hosted analyzer, audited
September 24).* The journal must reproduce exactly these effects; nothing
else in the body loop outlives it.
- **Four `Analyzed` side tables**, keyed today by node address:
  - `hostedCallKeys`, `constantArrayBoundKeys` and
    `arrayIterationCapacityKeys` are only ever added to.
  - `genericConstructorTypes` is last-writer-wins. Its value can be a node
    owned by another declaration (a callee's parameter type, a field type, a
    typedef original) or a fresh node.
- **Deferred generated-symbol references** (`NameValidator.generatedReferences`),
  in order, because the order decides which error is reported first.
- **The top-level `globals` map.** A top-level variable puts its binding
  type there for later globals, and that type can differ from
  `globalVarTypes`.
- **No AST mutation.** `var` inference stays local, and every assignment is
  to a copy or a synthetic node. The defaults merge and `sourceFile`
  stamping run in pre-passes.
- **Writes onto other declarations' nodes.** After the defaults merge, a
  definition's defaults are the prototype's nodes. Validating either one
  writes keys onto them.
- **Order sensitivity.** A caller reads facts on its callee's nodes: default
  expressions during ownership checks, and callee bodies during raw-borrow
  proofs. Those facts exist only once the callee has been validated.
  Replaying each journal at its declaration's place in program order
  reproduces that state. The raw-borrow cache answers a cycle
  pessimistically, and every member of the cycle comes out unsafe whatever
  the query order, so the cache needs no replay.
- **Errors abort.** `TypeValidator.fail` exits on the first error, so
  records exist only for builds that passed.

*Replay.* At a skipped declaration's place in the validation loop, the
analyzer:
- resolves each position through `AstStructure`;
- installs the facts;
- re-checks each consulted raw-borrow summary live, where any change
  validates the group live instead;
- queues the deferred references for the end-of-analysis check.

AST patches that validation performs, such as `mergeCallableDefaults`, still
run for every declaration.

*The gate.* A developer option analyzes live and replays side by side, then
requires every analysis map, compared by structural key, and every emitted
unit to be equal. The option runs over the whole corpus, the self-hosted
compiler's source and BTRSmith. A fallback to live analysis triggers when
more than a set share of groups is dirty.

#### Slice 1 as implemented (self-hosted compiler, September 25)

- **Journal.** `Analyzed` owns the four side-table writes
  (`recordHostedCall` and its siblings). While a declaration is validated
  for a record, each write, each deferred generated-symbol reference
  (`NameValidator.deferGenerated`) and each top-level raw-borrow proof
  (`BorrowValidator`) is appended to a `ValidationJournal`.
- **Positions.** `ValidationRecordCodec` in `pipeline/ModuleUnits.btrc`
  names a node by (file, ordinal among that file's top-level declarations,
  pre-order index from `AstStructure.preorder`, node kind).
  - The inline standard library is one file.
  - Native declarations are another; they are bodyless, and the interface
    digest in every key covers them.
  - A resolved position must have the recorded kind, and a raw-borrow callee
    must be a function or method with the recorded name.
  - A generic constructor type is recorded as a position when the node is
    in the tree, so replay yields the shared node that later phases mutate.
    Otherwise it uses `TypeIdentity.encode`, and `TypeIdentity.decode`
    inverts it. A type carrying an array size makes its group unrecordable.
- **Keys.** `ValidationRecords` keys each group by options, the group's
  source digest and the program interface digest.
  - The interface digest is assembled from per-group interface digests,
    cached under each group's source digest, plus the native declarations'
    rendering. An edit build renders only the changed group.
  - A record that names nodes in another group carries that group's key as
    a dependency.
- **Replay.** The validator loop replays a function or class whose group
  has a record. Top-level variables always validate live: they are cheap,
  and they extend the `globals` map.
  - Raw-borrow proofs are re-proved. A failure undoes the deferred
    references, validates the declaration live, and voids the record.
  - A record is written only when every function and class of its group
    was journaled.
- **Gate.** `BTRC_VERIFY_VALIDATION_RECORDS` validates everything live. It
  requires each stored record to equal the live journal, and each record to
  resolve and re-encode to the same text. It never takes a stored result
  generation.

*Result on BTRSmith* (one-string edit, instructions retired, because this
Mac throttles idle work):
- **Replay:** 1,687 declarations replay and one validates live.
- **Emitted units:** byte-identical to a clean build.
- **Verify mode:** passes.
- **Edit-build cost:** 433.9 billion instructions before, 360.7 billion
  with records (−16.9%, about 6 s at normal clock). Body validation falls
  from about 9 s to 0.3 s. Record setup costs about 0.6 s.

*Corpus:* every language-corpus program was built once with a cache and
then again under the verify gate. All 964 passed, with 6,251 declarations
compared with their records and round-tripped through their nodes. The
module-unit tests add an edit fixture that checks replay counts, the verify
gate and byte equality with a fresh build.

#### Slice 2 as implemented: generic demand (September 25)

A record now has three sections per function or class, in the order the
passes run:
- **Discover:** generic discovery's method scan.
- **Validate:** body validation.
- **Close:** the closure's per-declaration scan.

The two generic sections hold demand events, recorded at the push sites
before de-duplication:
- a class instance (base and arguments);
- a method instance (class, method and both argument lists);
- a call's method arguments.

Replay re-runs only each event's `genericSeen`/`methodGenSeen` check and
push, or `recordMethodCallArguments`. The instance lists, their order and
the last-writer-wins call arguments therefore come out as a live scan
leaves them. Specialization validation is skipped, since it only throws,
and a record exists only for a build that passed.

Unchanged and still live:
- the idempotent generic-argument upgrade;
- the cheap signature collection;
- the transitive fixed points;
- native callback instances;
- the instance-body closure.

A group whose validation replay is abandoned also scans its close section
live, because that scan reads validation's facts.

*Result on BTRSmith* (same edit):
- **Edit-build cost:** 324.7 billion instructions, against 358.5 with slice
  1 alone and 433.9 without records (−25.2% overall).
- **Per-declaration scans:** the closure scan drops from about 4.5 s to
  0.6 s and the method scan to under 0.01 s.
- **Correctness:** units are byte-identical to a clean build and verify mode
  passes.
- **What remains:** the instance-body closure inside the transitive fixed
  point (about 4–5 s) is now the largest analysis cost. It scans each
  generic class instance's members under substitution, which a
  per-instance record could reuse.

#### Slice 3 as implemented: realtime scans (September 25)

A fourth section per function or class records its realtime scan:
- each callable's events in order: an effect (category and operation) or an
  edge (target callable key), each at a site node position;
- the bounded-loop proofs lowering reads.

For a replayed declaration, the analyzer indexes its callables without
inferring their locals and installs the recorded events before the scan.
Event sites take their node's current line and column, so a witness still
points at the right line after an earlier file shifts. The call-graph fixed
point, witnesses and failure reporting stay live. A record that names a
callable its unchanged declaration lacks is an internal error, not a
fallback.

*Record costs.* Two changes keep them in check:
- Positions are computed once per declaration across the four phases, with
  identity-keyed maps (`Map<Node, …>` hashes by address), not formatted
  address strings.
- A node outside the encoded declaration is looked up first among
  declarations with parameter defaults (a callee's defaults are read at its
  call sites), then across the whole program. Each index stores an integer
  running position per node.

*Same-shape scope copies.* Three more places copied the global variable map
entry by entry:
- the generic closure's scope copy;
- lowering's per-function seed;
- the realtime analyzer's per-callable seed.

They now use `Map.merge` into an empty map, which copies slots. That removed
about 9% of cold-build instructions and halved the instance closure.

*Module-unit keys reuse the interface digest.* Analysis changes interfaces
only as a function of the whole program's pre-analysis source (generic
argument upgrades, merged defaults), and the program digest appends the
analysis facts anyway. So the module-unit program digest now uses the
records' cached pre-analysis interface digest instead of rendering every
declaration again. On an edit build the digest falls from about 2.4 s to
0.17 s.

*Result on BTRSmith* (instructions retired, one-string edit):

| Build | Before Stage B | With records |
| --- | ---: | ---: |
| Edit | 433.9 billion | 246.5 billion (−43.2%) |
| Cold | 448.3 billion | 436.5 billion (−2.6%) |

Records cost a cold build about 5% (journaling, encoding, interface
rendering). The scope-copy fixes more than repay that.

Two smaller cuts:
- The native-invocation type walk skips declarations whose group record is
  reusable. It reads only the declaration's own tree and the interface. The
  per-parameter checks, which may follow callees, stay live. This pass fell
  from 0.54 s to 0.02 s.
- Record positions name a file by a 12-hex-digit tag of its path, so
  realtime records, one line per event, no longer repeat long paths.

- **Correctness:** units are byte-identical to a clean build, verify passes,
  and all 965 corpus programs verify.
- **Remaining analysis costs in an edit build:**
  - the instance-body closure (about 3 s, throttled);
  - decoding realtime records (about 1.1 s, since every call edge is a
    line);
  - record setup (about 0.9 s).

  A foreign node is looked up first among declarations with defaults, then
  among all type nodes, then anywhere, so a cold build rarely indexes every
  node.

#### Per-instance closure records (September 25)

The instance closure scans every generic class and method instance's
members under substitution. Each scan is now recorded as a demand journal:
- class and method instances;
- call arguments under the instance's context, which go to
  `instanceMethodCallArgs`.

Records live in one rewritable record per template group,
`validation-instances-v1`:
- keyed by the group's record key;
- loaded on first use;
- with sections added as new instances appear.

A section is named by the instance's context and by whether validation had
run when it was scanned. An instance discovered before validation reads no
validation facts, so the same instance can be recorded at both stages.
Replay runs in place in the closure loop, under the instance's context, so
the instance lists come out in the same order. Instance records keep their
own dependency set. Mixing it into the validation records' set had made an
unrelated group's validation record depend on the edited group.

Also: `registerGenericInstanceWithUnresolved` computes the instance key
once, for both de-duplication tables, and mangles only new instances. The
inference memo is keyed by node identity.

*Result on BTRSmith* (same edit):
- **Edit-build cost:** 215.8 billion instructions (−50.3% against 433.9
  without records); 276 instance scans replay.
- **Instance closure:** about 2.7 s falls to 1.5 s (throttled).
- **Cold build:** 439.6 billion.
- **Correctness:** units byte-identical, verify passes, and all 965 corpus
  programs verify.

*Not yet:*
- The reference compiler has no records (its output is unaffected).
- Stdlib reachability's per-declaration name walks (about 0.8 s) and the
  lowering declarations session (about 4 s) are the largest per-build costs
  left in analysis and lowering.
- The front end (parse, native headers, visibility, graph; about 5 s) needs
  per-file caching.

#### What an edit build still spends (September 26)

Wall clock, BTRSmith, three fixture edits: 22.4–23.8 s end to end (compiler
16.6–18.0 s, native 5.3 s), against a 10 s budget. Throttled phase marks
split the compiler share roughly as:

| Area | Seconds | Kind |
| --- | ---: | --- |
| Front end: parse 1.8, native header import 1.5, visibility 0.9, dependency graph 0.8, lex 0.6 | ~5.6 | per build, whole program |
| Declarations-only lowering session | ~4 | per build, whole program |
| Module-unit plumbing: record parse 1.2, setjmp solve 1.2, record setup 0.6 | ~3 | per build |
| Generic instance closure (fixed point, instances not yet recorded) | ~1.4 | per build |
| Realtime record decoding | ~0.9 | per build |

The native step's 5.3 s is:
- preprocessing receipts: 2.0 s, spent in the header reader's session
  (which already shares filesystem observations across units);
- two links (discovery and qualification): 0.85 s;
- link validation: 0.74 s;
- dependency scans and cache validation.

Records have removed the per-declaration analysis. What remains is
whole-program work that runs on every build, and the next steps each remove
one such pass:

1. **Declarations session cache.** For a body-only edit the program
   identity (interface plus analysis facts) is unchanged, so the
   declarations-only IR is too. Caching it needs an IR codec for the node
   kinds that session produces (about 3–4 s).
2. **Durable standard-library front end.** The inline standard library is
   identical across builds, so its tokens and AST could be restored.
   Restoring allocates as many nodes as parsing does, so prototype the
   decoder and measure it before building on it.
3. **Native step.**
   - Skip the qualifying second link when the output will be replaced
     anyway (about 0.4 s).
   - Make receipt-session parsing cheaper in the reader (about 1 s).
*September 26 follow-up.* Measured end to end after these steps: an edit takes
20.8–21.6 s (compiler about 16.5 s, native 4.0–4.2 s), a no-op 6.3 s, and a cold
build about 135 s.
- **Items that can be removed incrementally**, with estimated wall-clock
  gains:
  - the declarations session: IR and facts serializers, keyed after
    reachability (about 1.4 s);
  - module-unit record loading: one opened store root (about 0.35 s; the
    line format replaced JSON records on September 26 and removed 8.3 G of
    the edit's 213.1 G instructions);
  - realtime record decoding (about 0.6 s);
  - the instance closure's remaining fixed point (about 1 s);
  - front-end parse caching for the durable standard library (unmeasured).
- **Together** they leave the compiler near 9 s, and the native step about
  4 s on top.
- **Conclusion:** the ≤10 s edit budget needs the resident compiler in step 4,
  or an equivalent that keeps the analyzed program between builds.

4. **Resident compiler (not in the plan).** A process that keeps the
   analyzed program between builds would re-parse and re-analyze only the
   edited group, which is the most direct route under 10 s. Its lifetime,
   invalidation and memory policy are a product decision.


Allocation is a separate lever and the only one that also reduces cold time
and memory; the reports put arena gains at roughly 10–20% and more with a
flat layout. Before any node-layout redesign, measure a faster general
allocator and per-group arenas. Parallel body validation over the import
DAG's dependency layers is the other cold-build lever: Scope States reported
5× on 8 cores, and rustc's parallel front end 30–50%.

**Stage C — bounded parallel groups.** Schedule dependency-ready groups on
workers with the same scheduler used for one worker.

Stage A alone cannot meet the 10 s body-edit budget: whole-program analysis
is about 18–21 s of the self-host cold compile. It is still on the critical
path, because partitioning, ownership, naming, linkage, summaries, keys and
the scheduler are the same in Stage B.

## Compilation groups

A group is a strongly connected component of the resolved source graph, with
import edges directed and textual include edges treated as reciprocal (the
same rule `SourceDependencyGraph.visibility_reachable` uses). A declaration
belongs to the group of its stamped `source_file`. Native-header declarations,
the classes the native importer writes for a binding (record inputs and
outputs, snapshots, initializer outcomes, copied results) and anything without
a source file belong to the **program unit**, which also carries the generated
Objective-C and C++ adapter units into the link plan and gathers every runtime
helper any unit selected. The **runtime unit**
(`unit-runtime`) defines those helpers and their process-unique state once,
with external linkage; every other unit, the program unit included, keeps the
helpers' types and macros and declares their functions and state. The runtime
is then compiled once per build instead of once per unit: on BTRSmith that
removed 26% of the emitted C and 23% of the native compile's CPU time.

Groups are ordered topologically for summaries. Mutual recursion across groups
requires an import cycle and is therefore inside one group. Generic
specializations are **definition-owned**: every instance of a template is
lowered in the template's group, keyed by the demanded instance set.

## Ownership, linkage and names

Every emitted definition has exactly one owning unit; every other unit that
needs it sees a declaration. Declarations with program-wide names —
functions, methods, constructors, destructors and destructor hooks, ARC
descriptors and visitors, interface tables and dispatchers, generic instance
members, enum `_toString` functions and rich-enum variant constructors, and
globals — have external linkage in their owner's unit. An enum's functions
belong to the enum's group even when only other groups call them, so a module
that declares nothing but enums and interfaces still has a unit of its own.
Session-counted or session-deduplicated synthesized functions (lambdas,
spawn wrappers, cleanup adapters, default-argument helpers, GPU dispatch
helpers) stay `static` in the unit that uses them, so per-unit counters
cannot collide. Generated C remains strict C11; there are no weak symbols.

A unit's C text must depend only on its group's inputs, never on which other
groups were lowered in the same process. Each group therefore uses a fresh
lowering session; only immutable program facts are shared.

### Compiling the units natively

Nearly every unit begins with the same feature macros and includes, and a
cold build otherwise parses those headers once per unit: preprocessing was
most of the native compile. The native plan builder (`tools/native_plan.py`,
`_PreludeAccelerator`) precompiles each prologue that at least sixteen of the
units it is about to compile share, and compiles a unit with the longest one
that is a prefix of its own leading lines; fewer units, as in an edit build,
compile as before. The unit's own includes then meet the guards the prelude
already defined, and its own feature macros the prelude's closing
restatement of them: a C library may rewrite a feature macro it reads --
glibc's `features.h` makes `_DEFAULT_SOURCE` 1 -- and the unit's definition
would otherwise be a redefinition, which `-Werror` rejects. Its translation is
unchanged but for such a macro keeping the unit's spelling past the prologue,
which only the library read, behind its own guard. A native header need not
carry a guard of its own: a module unit emits each native include inside an
include-once block named for the header (`BTRC_INCLUDE_<hash>`), and a
prologue takes only whole blocks with absolute paths, since a precompiled
header resolves a relative name against itself. The prelude only
accelerates: object-cache keys and dependency receipts come from the
unaltered command, and a compile that fails with a prelude runs again
without it.

A debug build also leaves out any `#line` directive that restates the
mapping the next line already has, and names the file only when it changes.
Every C line keeps its btrc location.

On BTRSmith (409 units, clang -O0 -g, 8 jobs, same machine state) these two
cut native compile CPU by 14-15% after the runtime unit, and the emitted C
from 129.8 MB to 73.8 MB. The `#line` trim alone is about 1%: Clang reads
directives cheaply, and the prelude carries the step.

## Keys and invalidation

A group artifact is valid when all of these match: compiler and runtime
identity; options, target and mode; the group's source bytes; the program
interface digest (declarations with non-template bodies removed, default
arguments, field initializers, templates, native declarations); the program
facts digest; and the digests of every cross-group summary the group's
lowering consulted. Stage A over-approximates with a program-wide interface
digest, so a public signature change invalidates every group; this is visible
in the counters and replaced by dependency-closure declarations later.

Summaries that participate in a call-graph cycle are recomputed from bottom
for the whole cycle, so reuse never keeps a non-least fixed point. Cache
misses rebuild; corruption must never produce a successful stale binary.
Clean and incremental builds are compared unit-for-unit in tests.

## Stage A as implemented (reference compiler)

`btrcpy --emit-units PREFIX --module-units` (`ModuleUnitCompiler`,
`application/modules.py`) compiles one build as follows:

1. Whole-program resolve, parse and analysis are unchanged.
2. One **declarations-only session** lowers every declaration with bodies
   gated off. After partition its function definitions become prototypes and
   its globals externs; this is the program's shared declaration IR
   (`SharedDeclarations`). It also computes the program lowering facts every
   later session shares (`ProgramLoweringFacts`: exception use, stdlib
   reachability, tuple shapes).
3. The **program unit** and every **stale group** are lowered in their own
   sessions with `declarations_elsewhere`: foreign declarations are skipped
   entirely, owned declarations and their bodies are lowered, and definitions
   created under a declaration are stamped with its group. Each unit then takes
   the shared declarations it references by name closure.
4. Setjmp call effects are solved across units by chaotic iteration from
   bottom, with reused units' published summaries fixed
   (`ExceptionLowerer.solve_program_setjmp_effects`). Restricting the program
   least fixed point to one unit and re-solving that unit with the others fixed
   reproduces the same values (the program solution is a pre-fixed point of the
   restricted system and the restricted least solution is below it), so each
   unit's volatility and capture rejection match whole-program lowering.
5. Realtime proofs follow calls into other units' IR
   (`IRVerifier.validate_program_realtime`); the program-wide cyclable-release
   fact is supplied to the unit defining `main`; the runtime unit defines
   every helper any unit selected, and its state.
6. Units that define nothing externally are dropped; each kept unit is named
   `unit-<stem>-<path hash>` so its file and native object stay stable, and the
   runtime unit is `unit-runtime`.

A **`ModuleUnitRecord`** per group (in the compiler cache, checksummed and
framed by the toolchain fingerprint) holds the unit text and the facts it
published or consulted: exported setjmp summaries, the summaries it consulted,
whether it contains `setjmp`, releases cyclable values or defines the entry,
the cyclable-release fact it consulted, its helpers, and the groups its
realtime proofs traversed. A record is reused only when its key matches and,
after the stale groups are solved, every consulted summary is unchanged, no
summary-dependency cycle joins it to a stale group, and no realtime proof it
made or needs crosses a stale group; otherwise the group is lowered again and
the solve repeats.

The **key** is the context (debug, DCE, target, output paths in debug mode),
the group's resolved lines with their original positions, the **program
interface digest** and the **program facts digest**. The interface digest
covers every declaration without source positions; callable bodies are elided
except in generic templates, keeping only whether a body exists and which
parameters its leading statements consume (the two body facts lowering reads
from other declarations). The facts digest covers exception use, generic class,
method and callable instance tables, the realtime-safe set and stdlib
reachability. Both are whole-program: a public signature change, a new generic
instance or newly reached stdlib declaration anywhere invalidates every group.
That over-approximation is visible in the lowered/reused counters and is the
next refinement (per-group consulted facts).

### Validation so far

- The full language corpus passes in module-unit mode through both
  compilers (1,922 runs), each unit linked with the others, with
  whole-program output unchanged (285 frozen boundary records) and the
  self-hosted bootstrap at its byte-stable fixed point.
- `src/tests/python/test_module_units.py`: groups/SCC ordering, record
  round-trip and corruption, stable names, and the fixture's clean build,
  full reuse, private body edit (only `Catalog` lowered, only its unit
  changes), byte-identical clean rebuild in a fresh cache, interface edit and
  corrupted records; the same private-edit sequence through btrcc; and the
  CoreAudio unit conformance program built from units in both compilers,
  whose realtime proof crosses into another unit's native callback adapter;
  and Objective-C bindings split across three modules and pugixml's C++
  owners, whose module-unit link plans carry the same generated adapter units
  and linker as a whole-program build, match between the two compilers, and
  link and run.

## Stage A in the self-hosted compiler

`btrcc --emit-units PREFIX --module-units` (`ModuleUnitCompiler` in
`pipeline/ModuleUnits.btrc`) follows the same steps. Two differences come from
how btrcc lowers generics:

- btrcc lowers every member of a demanded generic instance and relies on DCE,
  so a unit cannot tell alone which instance members the program needs. Each
  unit publishes a reference graph (its roots, instance members and the names
  each function references); the kept members are the fixed point of every
  unit's roots through all graphs, and a reused unit is exact only while its
  kept set is unchanged.
- An exported instance member whose body failed lowering (a deferred invalid
  operator) is not a DCE root; if another unit still calls it, its deferred
  diagnostic is reported as whole-program DCE would.

Records are stored as two files per key in the self-hosted artifact cache:
`unit.c` holds the C text verbatim, and `record.txt` starts with the digests
of the record and of the text, followed by the record itself: one
tab-separated line per field, then counted sections for the effect summaries,
realtime proofs and reference-graph edges, so reading it back is a split per
line. Either digest failing is a
miss. Module-unit cache opens skip revalidating every input read so far: a key
already digests the exact group sources, and publishing the build still
validates.

### Cross-unit facts in both compilers

- Whether a native callee is realtime-safe is a program fact. A unit that
  lowers a native realtime callback adapter records its callee; the program
  realtime proof uses the union of every unit's safe externals, as a single
  whole-program module does.
- The program setjmp solve re-analyzes a unit only when a summary it consulted
  moved after its last analysis. Units arrive dependencies first, so on
  BTRSmith 439 units take 458 analyses.
- A unit emits the interface dispatchers its own IR calls, after its bodies
  are lowered; the dispatch tables arrive with the shared declarations.

### BTRSmith measurements (September 23, macOS arm64, single samples)

The macOS self-hosted compiler (`cli/MacOSMain.btrc`, clang -O2) compiling the
BTRSmith copy in dev mode (`--debug`, 444 sources, 438 compilation groups),
compiler only (no native build). Each mode keeps a fixed output directory,
since debug-mode keys include the output path.

| Scenario | Whole program | Module units |
| --- | ---: | ---: |
| Cold (empty caches), in-process | 101.1 s | 105.5 s (104%) |
| Cold, two workers (the default) | 96.6 s | 88.2 s (91%) |
| Unchanged repeat | 5.3 s | 5.4 s |
| One-line private body edit | 97.8 s | **40.5 s**: 2 groups lowered, 436 reused, 1 of 401 units changed |

The edit build is now whole-program front end and analysis (about 28 s:
validation 9.7 s, generics 7.1 s, realtime 3.1 s, native headers 2.8 s,
parsing 2.3 s), the program interface digest (2.8 s), lowering the edited
group and the program unit (about 5 s) and loading 436 records (about 2 s).
Only Stage B removes the analysis share.

The cold overhead first measured 186 s (190%). The cuts, each found with an
in-process sampling profiler:

- releasing each group's lowering session, and the struct lists a unit's DCE
  drops (shared declaration IR alive in other units), ran an ARC
  reverse-reachability proof per object; the sessions now live until exit, as
  whole-program compiles already do (optimize 18.7 → 6.1 s, emit 12.3 → 6.8 s);
- the setjmp solve re-queued every consumer of a summary that moved earlier in
  the same round (30.2 → 8.2 s with the other cuts);
- three IR walks allocated an 18-element child list per node (graph 10.8 →
  about 1 s);
- every module-unit cache open revalidated all inputs (4.4 s of misses);
- records were JSON-encoded twice and the pure-btrc digest hashed them (edit
  61 → 45 s before the other cuts).

About 45% of CPU in both modes is the system allocator (`IRNode`/`Node`
construction allocates their child vectors eagerly). That is shared with
whole-program compiles and is not module-unit overhead.

### Measurements so far (diagnostic, single samples, macOS)

Self-hosted compiler source through btrcpy, cold, no caches: whole-program
**194.7 s** (lowering 94.9 s) after two quadratic scans were removed
(generic-parameter membership and prototype deduplication; lowering was
113.5 s before). The first module-unit implementation lowered the whole
program's declarations in every group session and took **511 s**; per-unit
optimizer passes then paid for program-sized regex alternations. Identifier
scans now tokenize once per text, and units draw declarations from the shared
IR, which removes that per-group program-sized work.

## Stage C: forked group workers (implemented in both compilers)

The analyzed program, the shared declaration IR and the program lowering facts
never change once computed, so worker processes forked after they exist share
them copy-on-write. A group's lowered IR stays in the worker that lowered it;
only small messages cross the pipes. The owner keeps every program-wide
decision and runs the same schedule with one worker (answered in-process) or
many, so the emitted units are byte-identical for every worker count.
`--jobs N` sets the count (both CLIs); without it the self-hosted compiler
uses one per CPU, at most four, the reference CLI at most two, and the Python
API stays in-process unless asked, because a threaded embedding process must
not fork.

Memory decides that default. Each worker starts as a copy-on-write image of
the analyzed program, but ARC writes reference counts into the objects
lowering reads, so a worker soon holds its own copy of much of that program
besides its units. System-wide anonymous memory growth on the BTRSmith dev
build (September 23): 4.83 GiB in-process, 5.93 GiB with two workers and
6.85 GiB with four, against the 6 GiB aggregate budget. Once IR nodes stopped
allocating lists they do not use (September 29), a cold btrcc transpile of
BTRSmith sampled 4.20 / 4.62 / 4.97 / 5.78 GiB of process-tree RSS with two,
three, four and six workers, taking 65.6 / 56.5 / 52.6 / 49.8 s, so btrcc now
defaults to four. The in-process figure
depends on keeping the lowered units alive until the process exits: releasing
them at the end of the compile ran ARC reverse-reachability proofs over the
whole graph and doubled the peak to 10 GB.

1. **Plan (owner).** Keys, record loads and the stale set are computed as
   before. Workers start on first need; a build that reuses everything never
   forks.
2. **Lower (workers).** Stale groups go to idle workers, largest first. A
   worker lowers the group, keeps the unit and returns its exports, reference
   graph, realtime roots and whether it calls `setjmp` or releases cyclable
   values.
3. **Solve (owner schedules, workers analyze).** Setjmp summaries follow calls
   between units, so the owner orders units by the SCCs of those calls and
   analyzes each dependency level together, callees first; a unit is analyzed
   again only when a summary it consulted moved in or after its wave (a call
   back into a lower level). Summaries travel as compact text, a worker
   receives only the summaries that moved since it last heard and replies
   only with its own that moved, and every solve pass has a generation, so a
   pass after a reuse check restarts both sides from bottom. Within a unit,
   a re-analysis recomputes only the functions that consulted a moved
   summary, and their unit-local callers. Summaries are snapshotted whenever
   they are published or recorded, because the solver widens effects in
   place. Without the snapshot, a recorded consulted summary silently
   followed later widening. It then compared equal to the exporter's final
   summary, which cost relowering, never output.
4. **Program checks (owner).** Instance demand runs on the reference graphs.
   Realtime proofs are composed: each unit proves functions through its own
   definitions and returns the calls it cannot resolve; the owner continues a
   call into another unit's export in that unit, checks every other call
   against the program-wide realtime-safe externals, and rejects call cycles
   between units. A record keeps its unit's realtime roots and, for each
   function a proof checked, the calls that proof left; a later proof through
   a reused unit resumes from that record, so a reused unit is lowered again
   only when a proof reaches one of its functions that was never proven.
5. **Finish (workers).** Each worker applies the solved effects, optimizes and
   emits its unit; the owner stores the record and assembles the build in
   group order.

Timing: under `BTRC_TIMING` (or `--profile`) a forked worker keeps its own
report from its first request: the idle time before each request (`w-wait`),
each operation's request count and busy time, and in btrcc its lowering marks
and `w-reply`. Just before closing a forked pool the owner sends each worker
one `timing` request, and after a clean close it prints the replies as
`<compiler> worker timing: worker=<i> ...` lines after its own line. Only the
owner writes, so worker reports never interleave and never repeat the owner's
marks; a failed compile prints none, and an inline pool, whose work is already
in the owner's line, adds no worker line and no `w-*` mark. Per-worker resource
usage (`wait4`) is a follow-up. Tests check one owner line first, one line per
worker from distinct processes whose lowerings add up to the owner's count, no
worker lines for inline, unchanged or one-group rebuilds, and identical units
with timing on and off.

Failure: a worker that exits, is killed or breaks the protocol fails the
compile with its diagnostic after every worker has been terminated and reaped;
a lowering diagnostic raised in a Python worker is raised again in the owner.
Records are written only by the owner, only for finished units, and are
content-keyed and checksummed, so a failed compile publishes no output and
leaves no partial record. Tests cover identical units across worker counts in
both compilers, a worker dying mid-compile (failure reported, no output, no
child processes left), cancelling the owner mid-lowering (its workers exit,
nothing is published), an effect-changing edit that forces a second solve
(the incremental build equals a clean one and lowers only the two groups
concerned, and every function body equals the whole-program build's), and
the real link plan, native object cache and linker: a clean
build compiles every unit, an unchanged rebuild none, and a private edit
exactly the edited group's unit.

## Concurrency contracts (M10)

The compiler owns grouping, ordering, barriers and deterministic merging. The
stdlib owns synchronization, bounded work delivery and worker lifecycle:
`Library.BackgroundJobs.BackgroundJobExecutor` is the bounded pool, and
`awaitCompletion()` is the blocking completion wait a dependency scheduler
needs (predicate-rechecked condition wait; `EMPTY` with nothing outstanding;
`CLOSED` after worker failure). Worker-owned lowering sessions and immutable
shared program facts are the sharing rule.

Every ARC retain and release currently takes one process-wide spinlock.
Measured September 23 (macOS arm64, clang -O2): each thread builds 20,000
managed nodes of 64 managed children, as lowering does, with no shared
objects (program: `~/.cache/btrc/checkpoints/2026-09-22-m11a/ArcScaling.btrc`,
run as `ArcScaling <threads> 20000`).

| Threads (same work each) | Wall | Ideal |
| ---: | ---: | ---: |
| 1 | 0.73 s | 0.73 s |
| 2 | 3.37 s | 0.73 s |
| 4 | 17.2 s | 0.73 s |
| 8 | 69.0 s | 0.73 s |

Threads contending for the ARC lock are slower in total than one thread doing
all the work. Worker threads therefore cannot parallelize ARC-heavy compiler
work until the runtime stops serializing thread-confined objects; Stage C
uses worker processes forked after analysis, which share the analyzed program
copy-on-write and exchange only records and summaries. The same holds for the
reference compiler, whose interpreter lock serializes threads.

## Fixture

`src/tests/native/modules/` holds the M11a fixture: the `Shapes` library
(generic `Box<T>`, inherited managed `Shape` with `Square`/`Rectangle`
implementing the `Measured` interface, a native header `ShapeScale.h`, a
throwing `checkedArea`, and a retaining `ShapeShelf`), consumers `Gallery`
and `Catalog`, and entry points `GalleryMain` and `CatalogMain`. Class
dispatch is static in btrc; cross-module dynamic dispatch goes through the
interface.
