# Design: Precompiled standard library

Status: **implemented and opt-in**

## Purpose

The compiler can publish the generated standard library as a separate C
translation unit and compile a program against that artifact. This avoids
emitting and compiling another copy of archive-owned declarations, functions,
helpers, and shared runtime state in every program translation unit.

Two existing caches solve different problems:

- `CompilerCache` caches final generated C for an unchanged resolved source.
- the frontend stdlib cache stores a schema-validated JSON representation of
  parsed stdlib declarations.

The precompiled archive is not another frontend cache. It establishes a C
linkage boundary and records exactly which generated IR elements that boundary
owns.

## Commands

```bash
# Publish btrc_stdlib.h, btrc_stdlib.c, and btrc_stdlib.manifest.
./bin/btrcpy --build-stdlib build/stdlib

# Emit program-only C that includes the published header.
./bin/btrcpy --stdlib build/stdlib app.btrc -o app.c
```

The caller compiles `btrc_stdlib.c` into an object or static library and links
it with the generated program C. The mode remains explicit; normal compilation
still emits a self-contained translation unit.

## Published artifacts

One archive generation contains:

- `btrc_stdlib.h` — public type declarations, function prototypes, and extern
  declarations for archive-owned runtime state;
- `btrc_stdlib.c` — the corresponding definitions;
- `btrc_stdlib.manifest` — strict JSON describing the artifact hashes,
  compiler/stdlib fingerprints, exported types and functions, macros, helpers,
  globals, and shared helpers.

The manifest is the partition contract. A consumer validates its schema,
toolchain fingerprint, canonical stdlib-source hash, and the SHA-256 digest of
both C artifacts before changing the program IR.

The three files are staged privately and published as one crash-recoverable
generation. Publication serializes writers, rejects links/reparse points at the
artifact boundary, fsyncs payloads and directories, writes the manifest last,
and restores the prior generation after an interrupted replacement. Readers
treat an in-progress journal as a retryable archive-version mismatch.

## Build flow

`--build-stdlib` runs the canonical stdlib through the normal compiler pipeline
with dead-code elimination disabled, then transforms the resulting IR for
separate linkage:

1. Concrete generic instances and structured callbacks exported by the stdlib
   become external definitions with matching external prototypes.
2. Runtime helpers that own process-global state are completed as dependency
   groups and emitted once in `btrc_stdlib.c`.
3. Header declarations for shared helpers are derived from the same helper
   source used for the implementation, preventing a hand-maintained ABI from
   drifting.
4. Other helper functions remain translation-unit local.
5. The emitter produces the header and implementation, and the publisher
   commits them together with their manifest.

## Consumer flow

`--stdlib DIR` still parses, analyzes, and lowers the resolved program through
the normal typed pipeline. At the IR boundary it:

1. validates the archive manifest and both published C files;
2. rejects user declarations that override archive-provided stdlib symbols;
3. removes types, functions, declarations, macros, globals, and helpers already
   owned by the archive;
4. retains program-specific generic instances that are absent from the
   manifest; and
5. inserts `#include "btrc_stdlib.h"` before emitting program-only C.

Consumer-side DCE is disabled before partitioning because the manifest, rather
than reachability in one program, defines the archive boundary.

## Generic and ownership boundary

btrc monomorphizes generic types per use. The archive contains the concrete
instances required by the stdlib build itself. A program-specific instance,
such as `Vector<UserType>`, is not named in the manifest and therefore remains
local to the program translation unit.

Most runtime helpers are `static` or `static inline` and may safely exist in
both translation units. State that must be unique across the process is owned
by the archive and declared `extern` to consumers. This includes complete state
families for managed strings, destroyed-pointer tracking, cycle suspects, and
try/catch cleanup. Completeness is dependency-derived so a lock, bucket array,
counter, or cleanup stack cannot be split across translation units.

Managed values and exceptions may cross the boundary. The archive therefore
preserves the same ARC, destructor, cleanup, and helper ABI used by inline
compilation.

## Correctness gates

The implementation is covered by contracts that require:

- inline and archive-linked programs to have identical behavior;
- program-only C to be smaller than the inline translation unit;
- program-specific generic instances to remain available;
- archive-owned globals and helpers to have exactly one definition;
- strict manifest schema, artifact hashes, and toolchain/stdlib fingerprints;
- retryable reader behavior during publication;
- concurrent writers to leave one complete valid generation; and
- interrupted publication to restore the previous complete generation.

Generated C is compiled under the repository's strict C11 gates. The artifact
publisher's link/reparse, identity, durability, and crash-recovery tests are
part of the focused archive suite.

## Current limitation

The implemented mode creates the separate C/link boundary, but it does not yet
deserialize an analyzed stdlib symbol table or skip stdlib analysis and IR
generation. A future performance phase may preload typed extern signatures and
generic templates so `--stdlib` also reduces compiler frontend/lowering time.
That optimization must preserve the manifest, ownership, and transactional
publication contracts documented here.
