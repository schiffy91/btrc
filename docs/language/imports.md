# Imports and compilation units

Status: **normative language contract**.

btrc resolves source dependencies before semantic analysis. Dependency edges
have language meaning; they are not merely an ordering hint.

## Strict visibility

Strict visibility is the default for compiler APIs and command-line tools. A
source file may reference a language-owned top-level symbol only when the file
that owns the symbol is visible through the dependency graph.

Visibility covers:

- classes, interfaces, functions, structs, enums, rich enums, and typedefs;
- top-level variables, including references from other global initializers;
- bare members of simple enums; and
- compiler-recognized source macros declared with `#define`.

Lexical locals, parameters, loop and catch bindings, and generic parameters do
not create import requirements. Compiler built-ins and names supplied by an
external C header are not owned by a btrc source file and therefore are outside
this graph check.

`--strict-imports` remains accepted as an explicit assertion of the default.
`--relaxed-imports` is the only compatibility opt-out. Relaxed mode preserves
the legacy implicit-stdlib behavior and does not enforce per-file visibility.

## `import` is directed

For an edge `a.btrc -> b.btrc` created by `import`:

- declarations in `a.btrc` may reference declarations in `b.btrc`;
- that visibility is transitive through imports made by `b.btrc`;
- `b.btrc` does not gain visibility into `a.btrc`; and
- two modules imported by the same parent do not automatically see one
  another.

Directory and standard-library import forms create one directed edge to every
resolved module. Each imported module must still declare its own dependencies.

```btrc
import std.vector;
import std.{fs, json};
import ./model.btrc;
import ./commands/*;
```

## `#include` creates one compilation unit

`#include "fragment.btrc"` is the legacy textual-composition operation. Files
connected by btrc `#include` edges form one compilation unit, so visibility is
reciprocal within that include-connected component. The component can use the
directed imports made by any of its members, but an imported module cannot see
back into the including component unless it imports it itself.

C header includes remain C preprocessor directives and do not create btrc
declaration ownership.

## Resolution and deduplication

Declarations are textually composed once, using canonical file identity to
break cycles and repeated imports. The dependency graph retains every resolved
edge even when a target's text was already composed; visibility therefore does
not depend on which importer happened to reach the file first.

Explicit imports are always resolved. `--no-stdlib` only disables the implicit
stdlib composition available in relaxed compatibility mode.

Both reference and self-hosted compilers must produce the same visibility
decision and source-mapped diagnostic for the same dependency graph.
