# Known language gaps

These are language features the grammar/spec permits (or the docs imply) but the
reference Python compiler and self-hosted compiler do not yet implement safely.
The historical numbering is retained so fixes and tests can refer to a stable
gap ID.

## Open gaps

| # | Feature | Symptom | Where |
|---|---------|---------|-------|
| — | Generic class inheritance | A generic class cannot extend another class, and inherited generic properties are not lowered. Both analyzers reject these declarations before code generation. | `python/analyzer/declarations.py`, `btrc/analyzer/validation/Declarations.btrc`, `btrc/analyzer/validation/Storage.btrc` |
| — | Static storage on generic classes | Static fields and properties do not yet have a per-definition versus per-specialization storage model. Both backends reject them explicitly. | `python/analyzer/storage.py`, `btrc/analyzer/validation/Storage.btrc` |
| — | Static methods on generic classes | A class-qualified static method call or method value has no specialization target for the class type parameters. Both analyzers reject the declaration instead of emitting an ambiguous unspecialized symbol. | `python/analyzer/declarations.py`, `btrc/analyzer/validation/Storage.btrc` |
| — | Lambda expressions inside generic declarations | Generic-body lowering does not yet lift lambda declarations and their capture environments for each specialization. Inline lambdas passed to an ordinary generic method are supported; a lambda declared inside a generic class or method body is rejected. | `python/analyzer/expressions.py`, `btrc/analyzer/validation/Expressions.btrc` |
| — | A discarded managed result in a C-`for` header | A `for` initializer or update operand that returns a fresh managed value (`for (make(); …; make())`, or one operand of a comma list) is never released, in both compilers; an expression statement releases the same call. Found while adding row 19, which keeps that behavior per operand rather than changing it. | `python/ir/lowering/statements.py`, `btrc/ir/lowering/Statements.btrc` |
| — | Realtime loop bounds the proof does not see | A `@realtime` C-`for` is certified when the bound's address escapes before the loop (`int* q = &n;` then `(*q)++` in the body), or when a narrow induction type cannot reach a literal bound (`for (signed char i = 0; i < 200; i++)`). Both compilers agree; found by the Stage 16 r19 review. | `python/analyzer/realtime.py`, `btrc/analyzer/Realtime.btrc` |
| — | A discarded tuple literal in btrcc | `(j = 1, i = i + 1);` as a statement, or as a for-update operand, makes btrcc emit C naming an undeclared tuple struct; the reference compiles it. Found by the Stage 16 r19 review. | `btrc/ir/lowering` tuple instance collection |
| — | The address of a `volatile` managed local | When the setjmp planner keeps a managed local `volatile` (`char* volatile value`), `string* view = &value;` emits `char** view = (&value);`, which strict C11 refuses (`-Wdiscarded-qualifiers`), whether the declarations are separate or share one list, in both compilers. Found by the Stage 16 C1 exit's ARC witness. | `python/ir/lowering/storage.py`, `btrc/ir/lowering` address-of lowering |
| — | A null raw pointer to `string` warns | `string* p = null;` warns `Possibly-null value stored in non-nullable variable 'p' of type 'string'`: the nullable check reads the pointer as its pointee, and a raw pointer may hold null; both compilers warn alike. Found by the Stage 16 C1 exit. | `python/analyzer/flow.py`, `btrc/analyzer` nullable flow |
| — | `spawn` expressions inside generic declarations | Generic-body lowering does not yet specialize the thread entry and capture boundary. Both analyzers reject the expression before code generation. | `python/analyzer/expressions.py`, `btrc/analyzer/validation/Expressions.btrc` |
| — | `for`-in over an array a lambda captured | A lambda captures an array as a pointer, so `for (int v in captured)` inside it iterates the pointer's decayed shape (summing 3 where the array sums 45), in both compilers. `sizeof(captured)` there is refused instead (CL-REQ-11). | `python/ir/lowering`, `btrc/ir/lowering` lambda capture of arrays |
| — | Tuple misuse that reaches C | `int x = w._0;` on an array of tuples, `(int)t` and `if (t)` on a tuple value are not refused; both compilers emit C that does not compile. | `python/analyzer/expressions.py`, `btrc/analyzer/validation/Expressions.btrc` |
| — | `sizeof` of a name that is not a variable | `sizeof(LARGE)` for an enum constant, or `sizeof(gone)` for a variable out of scope, is read as a type name and emitted as written, so C reports an undeclared identifier, in both compilers. | `python/analyzer/aggregates.py`, `btrc/ir/lowering/Expressions.btrc` |
| — | Shallow tuple elements of class type | A tuple stored in a class's array or field holds its class references without retaining them, so an element outlives an owner that dies first; and an indexed store does not retain its receiver while the right-hand side runs. Both compilers agree. | `python/ir/lowering/ownership.py`, `btrc/ir/lowering/ownership` |
| — | A `Vector<Tree<T>>` field initializer in a generic class (btrcc) | `public Vector<Tree<T>> children = new Vector<Tree<T>>();` inside `class Tree<T>` is refused by btrcc (`expects 'Vector<Tree<T>*>' but got 'Vector<Tree<T>>*'`); the reference accepts it. | `btrc/analyzer/validation` field initializer typing |
| — | A function-literal lambda in a generic class method (btrcc) | `var f = int function(int k) { ... };` inside a method of `class Box<T>` is refused by the reference ("Lambda expressions are not supported inside generic declarations") but compiled by btrcc, which scans its body under each specialization. | `btrc/analyzer/validation/Expressions.btrc` |
| — | btrcc line numbers in importing programs | A diagnostic in a program that imports the stdlib reports a line counted across the prepended stdlib (516:12 where the reference says 5:12); messages and columns agree. | `btrc/frontend` source line mapping |

## Open native-platform defects

These are not language gaps, but they are open defects no gate catches yet, so
they are tracked here rather than only beside their reproducers.

| Area | Symptom | Reproducer |
|------|---------|------------|
| macOS `NSSlider` presentation | After tracking, or disabling and re-enabling, the native value and cell value read 100 but the knob is drawn at the left; the 64-by-30 compact case also fails. Layout/display invalidation and a direct bitmap draw do not resolve it. | `src/tests/native/gui/SliderPresentation.m` (run instructions in `SliderPresentation.md`; macOS only) |

## Intentional syntax limits

Multi-dimensional fixed arrays (`int grid[2][3]`, historical gap 9) are not
part of the current language grammar or ASDL: a declaration has one optional
array suffix and `TypeExpr` has one `array_size`. Both parsers now reject a
second dimension explicitly instead of silently producing a partial AST. Adding
multiple dimensions would be a language/specification change, not a missing
implementation of the current grammar.

Grammar keywords are reserved and cannot be used as source identifiers. Code
generators escape schema field names that collide with those keywords, but that
internal escaping does not create quoted identifiers in the language.

Tuple element names such as `_0` and `_1` are ordinary postfix members. A
second tuple access must currently use a parenthesized intermediate—
`(value._1)._0`—because the unparenthesized numeric-looking boundary in
`value._1._0` is intentionally not accepted by the lexer. The equivalent
separate local binding is also supported.

Exceptions carry string messages. A catch may be untyped or bind `string`; a
different catch annotation is rejected explicitly. The stdlib error classes
are ordinary values and do not introduce typed exception payloads.

## Translation limits

Generic specialization must end. A cycle of type-parameter uses that wraps a
parameter (`class Chain<T>` with a field `Chain<(T, int)>?`, a generic method
calling itself with `(item, depth)`, or two classes that specialize each other
with a growing argument) is refused at the cycle's first growing use, with one
diagnostic, in both compilers: `Generic class 'Chain' grows its own type
arguments through this use, so its specializations never end`. As a
backstop, a derived specialization whose type arguments nest deeper than 32
levels (`limits.generic_argument_nesting` in `src/language/hosted_abi.toml`)
is refused. Types a program writes out are not limited.
[docs/language/translation-limits.md](language/translation-limits.md) states
the rule.

## C that btrc rejects on purpose

btrc accepts most C11 as written (the battery in
`btrc/test_c_compatibility_inventory.py` records which constructs, through
both compilers). The refusals below are deliberate: each keeps a btrc rule
that C does not have, and each gives the same diagnostic in both compilers
(`btrc/test_c_compatibility_refusals.py`). Row numbers refer to the
C-compatibility table in `docs/design/plan-reference.md`.

| Row | C source | btrc's rule | Diagnostic |
|-----|----------|-------------|------------|
| 4 | `char s[3] = "abc";` — the exact fit | A narrow string literal initializes a `char`, `signed char` or `unsigned char` array: `char s[] = "abc"` takes four elements and `char s[4] = "abc"` holds the terminator (`c_compat/CharArrayStringInit.btrc`, locals, statics, globals and struct-field elements). C drops the terminator silently when the literal exactly fills the bound; btrc refuses it (D20). Extents count bytes: a UTF-8 character or universal character name is its encoded length. Only a literal initializes a char array: an f-string or a `string` value is refused, and wide literals wait for row 16. A bound the front end cannot evaluate, such as a C preprocessor macro or a `sizeof`, is left to the C compiler, whose strict flags may or may not catch the exact fit (gcc 15 refuses it; C11 itself allows it). | `String literal fills all 3 elements of the char array and leaves no room for its terminator; declare 4 elements or leave the bound empty` |
| 18 | `#if UNKNOWN` (C reads 0) | btrc evaluates `#if`, `#ifdef`, `#ifndef` and `#elif` per file before lexing, against the selected target's predefined macros (`src/language/targets.toml`) and the file's own earlier `#define`s (D20, `c_compat/PreprocessorConditionals.btrc`). An evaluated identifier that is neither is an error, never C's silent 0; test it with `defined(X)`. An unevaluated operand (`0 && X`) is never read. | `Identifier 'UNKNOWN' in #if is not a macro defined earlier in this file or a target macro; test it with defined(UNKNOWN)` |
| 18 | `#ifdef __GNUC__`, `#if __LINE__` | A reserved name (`_` prefix) that is not a target macro names the C implementation btrc cannot see. | `'__GNUC__' is reserved for the C implementation and is not a btrc target macro; #if cannot test it` |
| 18 | `#if PATH_MAX`, `#ifdef NDEBUG`, `#if bool` | A hosted-ABI name, a `foreign_macro_names` entry, a `btrc_`/`BTRC_` name or a package's `[[native.defines]]` name is set by headers or compiler flags, which `#if` runs before. | `'PATH_MAX' is defined by C headers or C compiler flags, not by btrc; #if is evaluated before C compilation and cannot test it` (a package define names its package) |
| 18 | `#if VERSION(2)`, `#define X X` / `#if X`, `#define X a ## b` / `#if X` | `#if` expands only the file's object-like macros, never into themselves, and pastes no tokens. | `Function-like macro 'VERSION' cannot be used in #if; btrc expands only object-like macros there`; `Macro 'X' expands to itself in #if`; `Macro 'X' uses '##', which #if does not evaluate` |
| 18 | `#if 0 && (1, 2)`, `#if '\xff'`, `#if L'a'` | The comma operator is refused even unevaluated; a character constant above 127 and a wide one have target-dependent values. | `',' is not allowed in a #if expression`; `Character constant '\xff' in #if has a target-dependent value; write its integer value`; `Wide character constant L'a' in #if; write its integer value` |
| 18 | `#if -1 << 1`, `#if -1 < 0u` | A negative left shift and a negative value silently converted to unsigned are errors in an evaluated operand. | `Left shift of negative value in #if expression`; `#if expression converts negative value -1 to unsigned for '<'` |
| 18 | `#ifdef USE_FAST` beside an import whose file `#define`s it; `#ifndef HAVE_X` beside `#include "config.h"` or a C import | `#if` sees only target macros and its own file's directives, so a test whose answer another file, a native header or C btrc does not read could change is refused (P1-P4). | `'USE_FAST' is defined in Config.btrc, but #if in Main.btrc cannot see it; #if sees only target macros and #defines earlier in the same file`; `'HAVE_X' may come from C that btrc does not read ("config.h" in Main.btrc); #if is evaluated before C compilation and cannot test it` |
| 18 | `#define N 1` … `#define N 2`; `#undef max` | A redefinition must be identical (C11 6.10.3p2), because `#if` reads a value at its position and code the final one. `#undef` names only a macro a btrc source `#define`s, and code may not use a macro that is `#undef`'d anywhere: every directive is emitted before the program. | `Macro 'N' is redefined with a different replacement; #undef it first (C11 6.10.3p2)`; `#undef of 'max' is not allowed; btrc undefines only macros that its own sources #define`; `Source macro 'WRAP' cannot be used in code because it is #undef'd; btrc emits every #define and #undef before the program` |
| 18 | `#elifdef X`; `%:if 1`; `#/**/if 1`; a `#if` after `// note \`; `#if\f1` | C23 forms, digraph and trigraph spellings of `#`, comments and splices that C removes before it recognizes a directive, and form feeds are refused at every level, also in dead groups. A dead group must still lex. The null directive `#` stays refused by lowering. | `'#elifdef' is C23; write '#elif defined(NAME)'`; `'%:' is not supported as a spelling of '#'; write '#'`; `a comment between '#' and the directive name is unsupported`; `multi-line preprocessor directives are unsupported`; `only spaces and tabs may separate tokens in a preprocessor directive (C11 6.10p5)` |
| 19 | `int x = (1, 2);` — the comma operator | A parenthesized comma list is a tuple literal, so `(1, 2)` is a `Tuple<int, int>`. Only a C-`for` initializer and update accept the comma operator (`c_compat/CommaForHeaders.btrc`). | `Cannot assign 'Tuple<int, int>' to variable 'x' of type 'int'; btrc reads a parenthesized comma list as a tuple, not C's comma operator` |
| 20 | `int string = 0;`, `int f(int self)`, `struct S { int new; };` | Every word in `src/language/grammar.ebnf`'s `@keywords` is reserved, including the btrc words C programs commonly use as names: `in`, `string`, `keep`, `self`, `class`, `interface`, `spawn`, `new`, `var`, `null`, `true`, `false`. There is no quoting syntax for identifiers. | `'string' is a reserved word and cannot be used as a name` |
| 21 | `strlen(s) == 2` | An ABI-dependent integer (`size_t`, `ptrdiff_t`, `intptr_t`, …) never mixes implicitly with a built-in integer type whose width can differ from it; write the conversion: `(int)strlen(s) == 2` or `strlen(s) == (size_t)2`. Covered by `python/test_numeric_comparison_c11.py`, `python/test_numeric_semantics_contract.py` and their `btrc/` counterparts. | `Operator '==' mixes ABI-dependent integer type 'size_t' with 'int'; cast explicitly to a fixed-width or built-in integer type` |
| 22 | `_Bool b = 1;`, `bool b = 1;` | `_Bool` is accepted as a spelling of `bool`, but an integer never converts to `bool` implicitly; write `b = n != 0` or a `true`/`false` literal. | `Cannot assign 'int' to variable 'b' of type 'bool'` |
| 22 | `return f();` in a `void` function | A `return` with an expression in a `void` function violates C11 6.8.6.4, so this refusal is conformance, not policy. Call `f();` and `return;`. | `Void function or method cannot return a value` |
| 24 | `_Atomic int n;`, `_Atomic(int) n;`, `double _Complex z;` | Deferred: neither has a btrc type-system entry yet. For atomic storage use btrc's `Atomic<T>` (`docs/language/realtime-primitives.md`), which lowers to C11 `_Atomic(T)` with explicit memory orders and stable-storage rules; it is unaffected by this refusal. | `C11 '_Atomic' is not supported; use btrc's Atomic<T> for atomic storage` / `C11 '_Complex' is not supported; btrc has no complex types` |

Deviations from C11 in `#if`, documented rather than refused:

- `true` and `false` are 1 and 0, their C23 values; C11 reads them as 0
  unless `<stdbool.h>` is included.
- `0b` and `0o` constants are accepted; gcc `-pedantic-errors` rejects `0b`
  in C11.
- `#include "X.btrc"` is not textual for `#if`: X's `#define`s and `#undef`s
  do not reach the includer's conditionals (P1 and P4 refuse a test that would
  see a difference).
- C that btrc does not read cannot change what `#if` read: btrc evaluates
  before the C compiler runs.
- A system macro outside the hosted ABI, tested with `defined`, reads 0;
  angle includes are not C evidence for P3.

## Unresolved ALL_CAPS names

A name that resolves to no btrc or imported declaration is an error at its
use site in both compilers: `Unresolved identifier 'NAME' used as a value`.
Before October 2026 an ALL_CAPS spelling was exempt, on the theory that it
was a C macro, so a misspelt or removed constant (`COLOR_BLUE` for an enum
member that does not exist, a constant deleted from a library) transpiled and
failed only as "undeclared" in the C compile. An unresolved ALL_CAPS value now
passes through to C only when the compiler can account for it:

- a hosted ABI macro (`src/language/hosted_abi.toml`, `[names] macros`), such
  as `EOF`, `SEEK_SET` or `_SC_NPROCESSORS_ONLN`;
- a C11 predefined macro (`__FILE__`, `__LINE__`, `__DATE__`, `__TIME__`,
  `__STDC__`, `__STDC_HOSTED__`, `__STDC_VERSION__`);
- in a source file that has a raw quoted `#include "header.h"` (or an
  `import ./file.c`, which becomes one) of a C header or source that the
  importer does not model: the compatibility path. It covers that file only,
  never a module it imports, and angle-bracket includes are not part of it,
  because the hosted ABI already models the system headers.

Everything else needs a declaration the compiler can see. Source macros
(`#define`) and enum members in scope always resolve. An SDK macro or
enumerator of a native binding is imported by naming it in the binding's
`symbols` (`docs/design/native-interop.md`); it then has its C type, and every
module importing the bound module sees it. The Linux GUI, Tray and Image
providers name their SDL, fontconfig, libdbus and TurboJPEG constants that way.
`btrc/test_analyzer_parity_battery.py` pins the diagnostic, its position and
the compatibility path in both compilers.

## Parameter lists (C row 1)

`(void)` is an empty parameter list wherever a parameter list appears, and a
function prototype ending in `;` may leave its parameters unnamed
(`int scale(int, double);`, `c_compat/VoidAndUnnamedParameters.btrc`). The
definition's names are the ones named arguments and defaults use. Refused,
with the same diagnostic in both compilers:

| C source | Diagnostic |
|----------|------------|
| `int f(void x)`, `int f(void, int)`, `int f(const void)` | `A 'void' parameter must be the only one, unnamed and unqualified: write '(void)'` |
| `int f(int) { ... }`, or an unnamed parameter of a method, interface signature, lambda or rich-enum variant | `Parameter name required: only a function prototype without a body may omit it` |
| `void f(keep T);` | `A 'keep' parameter requires a name` |
| `int f(int = 3);` | `An unnamed parameter cannot have a default value` |
| a prototype and definition whose arity, types or `keep` differ | `Conflicting declarations for function 'f'` |

Still open: a prototype whose parameter names differ from its definition's
(`int f(int a);` then `int f(int b) {}`) is refused as conflicting, though C
accepts it; `typedef void V; int f(V);` is refused although C reads it as
`(void)`; and a diagnostic about an unnamed parameter names it `''`.

## Several declarators (C row 3)

One declaration may declare several names, as in C
(`c_compat/MultipleDeclarators.btrc`): locals, globals, struct fields, class
fields (`public int x = 1, y;`, each its own field with the same access),
typedefs (`typedef int Count, *CountPointer;`) and the C-`for` initializer.
`*` and a suffix `[n]` bind to their own declarator, so `int *p, v;` makes `v`
an `int` (PLAN.md D20). Qualifiers, the base type, generic arguments and
btrc's prefix `[]` are the specifier and are copied, so `int[] a = {1}, b =
{2};` declares two arrays. Each declarator keeps its own initializer, its name
is in scope only after its own declarator, initializers run left to right, and
a managed declarator owns its own reference. Refused, with the same diagnostic
in both compilers:

| Source | Diagnostic |
|--------|------------|
| `int a, ;` | `Expected declarator name, got SEMICOLON ';'` |
| `int f(), x;` (legal C) or `int x, f();` | `Function 'f' must be declared on its own, not beside other declarators` |
| `int? a, b;` | `A nullable declaration declares one variable: write one declaration per nullable variable` |
| `var a = 1, b = 2;` | `'var' declares one variable: write one 'var' declaration per variable` |
| `int a, a;` | the ordinary duplicate-name diagnostic for locals, globals, fields and typedefs |
| `int a[], b;` | `Variable 'a' requires an array bound or initializer` |

A typedef declarator takes no array suffix yet (`typedef int Row[3];` waits
for PLAN.md Stage 18), and a property declares one name.

## The comma operator in `for` headers (C row 19)

A C-`for` initializer and update take a comma list
(`for (i = 0, j = n - 1; i < j; i++, j--)`, `c_compat/CommaForHeaders.btrc`):
operands run left to right and every value but the last is discarded. The
condition takes one expression, and a declaration list in the initializer is
row 3's (`for (int i = 0, j = 9; …)`). A `@realtime` loop stays provably
bounded when its update steps the induction variable exactly once among other
operands that write neither it nor its bound; a `@gpu` kernel emits one WGSL
statement per operand. Everywhere else `(a, b)` is a tuple, and assigning one
to a non-tuple says so in the diagnostic (table above).

## Function-pointer declarators (C row 7)

`R (*name)(params)` is C's spelling of `CFunction<R, params...>` in local and
global variables, the C-`for` initializer, struct and class fields,
parameters (named, or abstract `R (*)(params)` in a prototype) and typedefs;
`R (*name[n])(params)` is an array of them, and casts and `sizeof` take the
abstract form (`c_compat/FunctionPointer*.btrc`). A statement whose head is
not a type in scope stays an expression, as in C (PLAN.md D20). Refused, with
the same diagnostic in both compilers:

| C source | Diagnostic |
|----------|------------|
| `int (*pick(int))(int)` | `A function returning a function pointer needs a typedef: write 'typedef R (*Name)(...);' and return 'Name'` |
| `int (**p)(int)` | `A pointer to a function pointer needs a typedef: write 'typedef R (*Name)(...);' and use 'Name*'` |
| `int (* const p)(int)` | `A qualified function pointer needs a typedef: write 'typedef R (*Name)(...);' and use 'const Name'` |
| `sizeof(int (*[3])(int))` | `An array of function pointers needs a name: write 'typedef R (*Name)(...);' and use 'Name[n]'` |
| `typedef int (*T[2])(int);` | `A typedef cannot name an array of function pointers: write 'typedef R (*Name)(...);' and declare 'Name ops[n]'` |
| `typedef int F(int);` | `A function type typedef is not supported: write 'typedef R (*Name)(...);' for the pointer` |
| `void (*log)(const char*, ...)` | `A variadic function-pointer type is not supported until variadic definitions (C row 14)` |

Still open: a statement `T (*name)(list);` whose head is a bare type name and
whose list an expression could also spell (`size_t (*f)(size_t);`, or
`Count (*f)(Count);` after `typedef int Count;`) parses as an expression,
because the parser's rule never consults type names; add an initializer or
write `CFunction<...>`. An abstract declarator is not a generic argument
(`Vector<int (*)(int)>`); write `Vector<CFunction<int, int>>`.

## Variable-length arrays (C row 23)

A block-scope array whose bound is not a constant expression is a C
variable-length array, and btrc keeps it
(`c_compat/VariableLengthArrays.btrc`). Supported forms:

- a local `T name[expr];` with an integral bound, including inside loop bodies,
  where each iteration gets an array of its own extent;
- `sizeof(name)`, evaluated at run time from the bound;
- a parameter `T name[expr]` whose bound names an earlier parameter (C adjusts
  it to `T*`);
- `for item in name`, which iterates the declared length;
- a lambda reading the array; the lambda's environment holds a pointer to the
  caller's storage, so it borrows the array for its own lexical lifetime.

The bound expression is evaluated exactly once, into a typed local, before the
declaration. **btrc deviates from C on a bound that is zero or negative**: C
leaves that undefined, while btrc gives the array one element of storage
(`sizeof` reports one element) and iteration and GPU dispatch use the declared
length, so they see no elements.

These contexts refuse a runtime bound, with the same diagnostic in both
compilers (`btrc/test_c_compatibility_refusals.py`):

| Context | Diagnostic |
|---------|------------|
| a global, a `static` local, a class field or a struct field | `Array bound for … must be a constant expression` |
| an initializer of any kind | `Variable 'v' is a variable-length array and cannot have an initializer` |
| capture by `spawn` | `spawn cannot capture array storage through 'v'; copy it into a scalar-only struct or managed collection` |

Like a fixed-size local array, a VLA of a managed element type (a class,
`string` or collection) is shallow storage of borrowed references: storing a
freshly owned value in it is refused (`caller-owned temporary cannot be stored
in a shallow aggregate`). `goto` is not part of the grammar yet (PLAN.md Stage
20), so a jump into a VLA's scope cannot be written; Stage 20's negative
fixtures must cover it.

## Adjacent string literals (C row 5)

Adjacent string literals concatenate as in C (`c_compat/AdjacentStringLiterals.btrc`):
each piece decodes on its own before they join, so `"\x4" "1"` is two
characters and `"\x1" "2"` never becomes `"\x12"`; `sizeof` and constant
folding see the decoded total plus one terminator. A triple-quoted piece is
allowed, and a piece may be the name of a source `#define` that expands to
string literals (directly or through other such macros). The generated C keeps
every piece's own spelling, so the C compiler performs the same concatenation.
An import path and an `#include` never concatenate.

Two forms are refused, with the same diagnostic in both compilers, at the
first piece:

| Source | Diagnostic |
|--------|------------|
| an f-string beside a literal (`f"{n}" " tail"`) | `An f-string cannot be concatenated with an adjacent string literal` |
| a piece naming anything but a source macro that expands to string literals, including a native macro such as `PRId64` that the front end cannot resolve (D20) | `Cannot concatenate 'PRId64' with an adjacent string literal: it is not a source macro that expands to a string literal` |

## Nullable references are checked by warnings

A nullable reference (`T?`) and a non-nullable one (`T`) share one
representation, and the type system does not refuse a store of one into the
other. Both compilers instead report path-sensitive **warnings**: a
non-optional access on a value of nullable type (`x.f` where `x` is `T?`), and
a possibly-null value (`null`, a `T?` value, a `?:` with such an arm, an
`a ?? b` whose fallback may be null) stored into a non-nullable class,
interface or `string` reference by an initializer, `=`, `return`, a call
argument, or a field or parameter default. A null check, an early `return`,
`throw` or call that never returns (`exit`, `abort`, or a function every path
of which ends in one), or a store of a non-null value silences them on the
paths it proves. A warning never fails a compile; the compiler, the stdlib and
the examples are kept free of them. `docs/design/compiler-parity.md` records
the exact rule.

## Closed gaps

| # | Feature | Resolution | Regression test |
|---|---------|------------|-----------------|
| 1 | `typedef` aliases | Lowered as typed `IRTypedefDef` declarations and emitted before dependent declarations. | `basics/TypedefAliasLowering.btrc` |
| 2 | Local storage qualifiers | `static`, `extern`, and `volatile` are preserved as `IRVarDecl` metadata in ordinary declarations and loop initializers. | `basics/LocalStorageQualifiers.btrc` |
| 3 | Class C-style casts | Class targets lower to pointer C types. Non-generic interfaces support managed runtime values, proven implementation upcasts and checked nullable interface queries. Unchecked interface-to-class downcasts and generic interface values remain rejected. | `classes/ClassCastLowering.btrc`, `python/test_interface_runtime_boundaries.py` |
| 4 | Wide and unsigned integer string conversion | Dedicated helpers and matching format specifiers cover `long long`, unsigned integer widths, and `long double`. | `basics/WideIntegerStrings.btrc` |
| 5 | Rich enums in by-value declarations | Rich enums use structured tagged-union IR and are completed before callable declarations or class fields that use them by value. | `enums/RichEnumSignatures.btrc` |
| 6 | Class compound assignment | Compound operators call the corresponding overload once and assign its result. | `classes/ClassCompoundAssignment.btrc` |
| 7 | Nullable class element in a generic collection (`Vector<Box?>`) | `keep` and keep-parameter retains are null-guarded in both compilers; generic ownership paths use the terminal destructor. | `memory/NullableGenericArc.btrc`, `memory/NullableOwnershipOps.btrc` |
| 8 | Valid multi-word C integer spellings | The parsers accept the valid signed/unsigned `short`, `long`, and `long long` spellings; invalid `long long double` is no longer treated as a supported base type. | `basics/ExtendedIntTypes.btrc` |
| — | Self-host parser diagnostics | Token expectations record one fatal expected/actual diagnostic, unwind to the program boundary, and prevent malformed ASTs from entering analysis or IR generation. | `btrc/test_parser_diagnostics.py` |
| 10 | Capturing IIFEs | The call site creates a typed stack environment, initializes it in an `IRCommaExpr`, and passes its address to the lifted expression- or block-body lambda. Only the inert declaration is hoisted, so branches and loop conditions retain source evaluation semantics. | `functions/LambdaCaptureIife.btrc` |
| 11 | Capturing lambda conversion to exact `CFunction<Signature>` | `CFunction` is the public spelling of one noncapturing C function-pointer word; result, parameter, pointer, and `const` shapes are checked recursively from the canonical hosted-ABI manifest. A direct inferred local may retain an associated environment only through its dedicated lexical path. Every environment-erasing conversion—explicit storage, aliasing, return, argument, assignment, default/field, or recursively nested collection literal—is rejected once at its source site. Direct `spawn(lambda)` and capturing IIFEs retain their environment-aware lowerings; the self-hosted compiler also fails closed at unsafe IR boundaries. | `btrc/test_cfunction_callback_contract.py`, `python/test_analyzer_lambda_contracts.py`, `functions/LambdaCaptureLocal.btrc` |
| 12 | Self-hosted `@gpu` lowering | `btrcc` now registers typed kernel/buffer/uniform IR, emits collision-safe checked WGSL, builds host dispatch/setup/readback/cleanup as structured C IR, prunes unreachable shaders, and provides per-invocation CPU fallbacks for void and array-output kernels. Checked bounds/arithmetic status is read before user data; post-submit transfer failures fail closed, while pre-submit failures use the CPU worker. The native compute context is acquired through an atomic process singleton. Kernel validation is an analyzer-stage contract in both compilers: every `@gpu` declaration is checked whether or not a dispatch reaches it, with identical diagnostics, and both emit byte-identical WGSL. | `btrc/test_gpu_boundary.py`, `btrc/test_gpu_diagnostics_parity.py`, `btrc/fixtures/GpuCheckedSemantics.btrc`, `btrc/fixtures/GpuCompoundSemantics.btrc` |

Single-dimensional top-level fixed arrays are also represented by typed
`IRGlobalDecl` nodes and covered by `basics/GlobalFixedArray.btrc`.

For an interface reference, `(IButton?)view` queries the receiver's actual
implementation. It returns the same object, or `null` for a missing interface or
null receiver. The nullable target is required for a query; implicit conversions
remain proven upcasts. Raw pointers and unrelated concrete objects cannot be
converted into interface references this way. Queries evaluate their operand
once, reuse the existing per-class dispatch directory, and allocate no adapter.
A temporary operand is released on a miss; on success its normal managed
ownership follows the result, including exception cleanup. Empty marker
interfaces and interfaces inherited by a class participate in the same lookup.
