# String lifetime and ownership

## Problem

The source `string` type has a stable C ABI of `char*`. String literals and
borrowed C strings therefore have the same representation as strings allocated
by btrc helpers. The old thread-local temporary pool records allocations but is
never flushed by generated programs. Flushing it at a function or statement
boundary is not sound: a generated string may escape through a return, local,
field, collection, exception, or thread result.

This is an ownership problem, not a missing-cleanup call. Production code must
neither retain every generated string until process exit nor free values that
have escaped.

## ABI contract

- `string` remains `char*` at every C boundary.
- String literals and unregistered C/FFI strings are borrowed. Runtime retain
  and release operations are no-ops for them.
- A btrc allocation is registered in a process-wide side table with reference
  count one. The allocation itself remains a normal `malloc`-compatible pointer;
  no metadata is read before an arbitrary `char*`.
- A source-language function or method that returns a dynamically managed
  string transfers one reference to its caller. Unknown C and function-pointer
  calls returning `char*` remain borrowed unless an explicit runtime adoption
  boundary is used.
- String properties are borrowed projections, matching class properties.
- Every owning local, instance field, property backing slot, collection slot,
  captured thread value, and thread result retains or adopts exactly one
  reference and releases it exactly once.
- A string cannot participate in an object cycle, so string releases never
  enter the class cycle collector.

## Runtime atoms

The runtime exposes these small operations:

| Operation | Contract |
|---|---|
| `__btrc_string_alloc(length)` | Allocate, NUL-terminate, register, return +1. |
| `__btrc_string_adopt(value)` | Register an unregistered heap value at +1; leave an already registered value unchanged. |
| `__btrc_string_retain(value)` | Increment a registered value and return it; borrowed values are unchanged. |
| `__btrc_string_release(value)` | Decrement a registered value and free at zero; borrowed values are unchanged. |
| `__btrc_string_release_cleanup(value)` | Exception-cleanup adapter with the existing `void (*)(void*)` ABI. |
| `__btrc_str_track(value)` | Compatibility spelling for adoption, not a temporary pool. |

The side table must use a C11 process-wide synchronization primitive, perform
overflow and underflow checks, and remove the last table allocation when the
last managed string dies so leak sanitizers observe a clean process. It must not
depend on pthreads. As with ordinary ARC, retaining a value after its last owner
has concurrently released it is invalid; synchronization protects registry
integrity, not unsynchronized application aliases.

## Compiler ownership domains

Ownership lowering distinguishes two managed domains:

1. Class references use the ARC header, dynamic descriptor, edge accounting,
   and cycle collector.
2. Strings use the side-table retain/release atoms and have no graph edge or
   collector metadata.

Shared lowering asks the domain for `retain`, `adopt`, `release`, exception
cleanup, and result provenance. It must not make strings look like classes or
special-case strings independently at every call site.

The required boundaries are:

- declarations, reassignment, discarded expressions, and all control exits;
- borrowed versus +1 returns, conditional/coalescing branches, and calls;
- constructor initializers, fields, auto-properties, and destructors;
- `Vector`, `Map`, and `Set` insert/replace/remove/copy/filter/clear/destroy;
- iteration bindings and lambda captures;
- throw/catch cleanup and return through active try frames;
- `spawn`, `Thread<string>`, and `Mutex<string>` transfer paths;
- generated helpers, f-strings, conversions, and stdlib allocation routines.

Shallow C aggregates remain borrowed-only unless they gain explicit generated
destruction. Embedding a caller-owned dynamic string in such an aggregate must
be rejected just like a caller-owned class value.

## Verification matrix

- Exact runtime live-count tests for allocate/retain/release/adopt, literals,
  NULL, overflow protection, and concurrent independent owners.
- Strict GCC and Clang C11 builds with `-pedantic-errors -Wall -Wextra -Werror`.
- ASan, UBSan, LSan, and an available TSan lane for the registry.
- Language tests covering local aliases/reassignment, borrowed and dynamic
  returns, fields/properties, collection replacement/removal, exception exits,
  lambda capture, string thread results, and long-running allocation loops.
- Both the Python reference compiler and the freshly rebuilt self-hosted
  compiler must emit the same ownership behavior.
- The stdlib must contain no raw allocation returned as `string` without an
  adoption boundary, and generated C must contain no temporary string pool.
