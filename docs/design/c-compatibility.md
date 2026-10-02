# C compatibility: AST representation

PLAN.md Stage 15 lands every C1 representation decision in one schema commit,
so `src/language/ast.asdl`, the generated `Node`/dataclasses, the canonical
renderers and the boundary records churn once. The parsers keep rejecting the
new syntax until each construct lands in Stage 16 (and C4 in its own stage).
Two read-only design reviews (workflow `wf_7d48ab51-ee9`, 2026-10-01) compared
the options; the choices below cost no new fat-Node field and remove one
(`Node.varDecl`), because every new sequence reuses lazy list storage that
already exists (`declarations`, `parts`, `elements`).

User-facing refusals stay in `docs/known-language-gaps.md`.

The later C rows have their own design documents, each drafted and
adversarially reviewed by workflow `wf_926e5dfc-b6e` (2026-10-02):
[`c-preprocessor-conditionals.md`](c-preprocessor-conditionals.md) (C4, the
end of Stage 16), [`c-vocabulary-specifiers.md`](c-vocabulary-specifiers.md)
(C3, Stage 19) and [`c-goto-labels.md`](c-goto-labels.md) (Stage 20).

## Decisions

| Item | Representation | Schema change |
|------|----------------|---------------|
| (a) Unnamed parameters, `(void)` | An unnamed prototype parameter is `Param(name="")` with `name_line`/`name_col` 0 and `line`/`col` at its type, as an anonymous `StructDecl` uses `""`. `(void)` is an empty `params` list with no `Param`. Unnamed parameters are accepted only in a body-less `FunctionDecl`; methods, interface signatures, lambdas, rich-enum variants and definitions refuse them (C11 6.9.1p5). `f(void, int)`, `f(void x)` and qualified `void` are refused. A prototype parameter without a name emits no C name. `(void)` is accepted as an empty list wherever a parameter list appears (Stage 16, r01). | none (comment only) |
| (b) Several declarators | Each declarator becomes its own complete node (`VarDeclStmt`, `FieldDef`, `FieldDecl`, `TypedefDecl`) with its own deep copy of the specifier type, spliced in source order into the list that holds the declaration (`Block`, `CaseClause`, `Program`, `StructDecl.fields`, `ClassDecl.members`). `*`, `[n]` and a function-pointer declarator bind to their own declarator (PLAN.md D20); specifiers, qualifiers and generic arguments are copied. The C-for initializer is the only single-statement slot, so `ForInitVar` holds a list. | `ForInitVar(stmt* declarations)` replaces `ForInitVar(stmt var_decl)` |
| (c) Empty statement | No node. A `;` inside a statement list produces nothing; a `;` used as a body becomes an empty synthesized `Block` at the `;`. A stray file-scope `;` stays refused. Stage 20 (`goto` and labels) adds its own label and jump nodes. | none |
| (d) Braceless bodies | A non-block body of `if`/`else`/`while`/C-`for`/`do` is wrapped in a synthesized `Block` through one shared helper per parser. A declaration as the sole body is refused (C does not treat a declaration as a statement). A dangling `else` binds to the nearest `if`. `for`-in, parallel `for`, `try`/`catch`/`finally` and `switch` stay braced. | none |
| (e) Adjacent string literals | `StringConcat(expr* parts)`, each part a `StringLiteral` or an `Identifier` naming a source macro that resolves to one. A single literal stays a plain `StringLiteral`, so no existing consumer or frozen record changes. Each part decodes separately, because C's translation phase 5 runs before phase 6 (`"\x4" "1"` is two characters). Lowering emits the parts' C spellings, space-joined, as one literal. An f-string next to a literal, or an identifier that does not resolve to a string literal, is refused with a diagnostic (D20). | new `expr` constructor, appended |
| (f) Comma operator in `for` headers | `CommaExpr(expr* elements)`, produced only at the top of `ForInitExpr.expression` and `CForStmt.update` with two or more operands, never in the condition; elsewhere `(a, b)` stays a tuple (D19 row 19). Its value is the last operand's, discarded in both positions; it lowers to the existing `IRCommaExpr`. `for (int i = 0, j = 9; …)` is (b)'s declaration list, not a comma expression. | new `expr` constructor, appended |
| C4 `#if` | No AST change: conditionals are evaluated before lexing, dead lines are blanked so positions survive, and live `#define`/`#include`/`#undef` stay `PreprocessorDirective(string text)`. | none |

## Conventions the Stage 16 lanes must keep identical in both parsers

Positions are part of the canonical AST, so a difference here fails every
parity test:

- The first declarator keeps the declaration's start; each later declarator
  starts at its own first token (`*` or its name). `name_line`/`name_col` are
  per declarator.
- A synthesized body `Block` is positioned at the body statement's first
  token; an empty-statement body at the `;`.
- `CommaExpr` and `StringConcat` are positioned at their first operand/part.
- A single-declarator declaration renders byte-identically to today.

Further rules fixed now so no construct needs a second schema commit:

- **Nullable marker and several declarators.** D20 is silent on btrc's `?`.
  A declaration with more than one declarator whose specifier carries `?` is
  refused with a targeted diagnostic (write one declaration per nullable
  variable); generic arguments are part of the specifier and are copied.
- **Function-pointer declarators (r07).** `T (*name)(...)` is a declaration
  when `T` is a built-in type keyword or a type declared earlier in the same
  file, or when the parenthesized list that follows is a parameter-type list;
  otherwise it is an expression. Per-file parse results are cached under a
  context-free digest, so the parser cannot consult imported type names; the
  analyzer refuses a parsed declaration whose head does not resolve to a type.
  A function-pointer type is the existing `CFunction<...>` type, never a
  `Param` list.
- **Kind coverage.** btrc's analyzer and validators dispatch on `kind` and
  silently skip a kind they do not know, while lowering aborts loudly
  (`ir/lowering/Statements.btrc`, `ir/lowering/Expressions.btrc`). A lane that
  starts producing `StringConcat` or `CommaExpr` audits every btrc switch that
  already handles `NK_TERNARY_EXPR` and adds a contract test for its kind.
  Python's dataclass walkers descend into a new constructor automatically.

## Schema commit

`ForInitVar.declarations` replaced `var_decl` in both compilers; the
kind-independent walkers (`AstStructure.children`, frontend visibility,
stdlib reachability, the `try` scan, realtime dispatch, expression identifier
collection, generic closures) read the shared `declarations` storage. The
realtime canonical-loop proof accepts exactly one declaration. No frozen
boundary record changes: the boundary source contains no C-for, parameter,
or adjacent string.

## Stage 16 progress

- **r02 and r06 (braceless bodies, empty statement).** One body helper per
  parser (`Parser._parse_body`, `Parser.parseBody`) serves `if`, `else`,
  `while`, `do` and the C-`for`; `_parse_block`/`parseBlock` and the case-clause
  loop drop a `;` from statement lists. A declaration body and a file-scope
  `;` are refused with one diagnostic in both compilers. No analyzer or
  lowering change: `src/tests/btrc/test_c_compatibility_bodies.py` proves raw
  IR and C (with and without `--debug`) identical to the braced twin,
  including managed temporaries. The formatter indents an unbraced body one
  level past its header, keeps it on its own line, and aligns a dangling
  `else` with its `if`. Lanes that add to `_parse_for_stmt`/`parseForStmt`
  call the helper only for the body, after `)`.

## Stage 16 r01: `(void)` and unnamed parameters

- **`(void)` everywhere.** Exactly `void` followed by `)` is an empty
  parameter list in every parameter-list position: functions, prototypes,
  methods, constructors, interface signatures, both lambda forms and rich-enum
  variants. It is unambiguous and produces the same AST as `()`, so nothing
  downstream can tell them apart. Any other plain `void` parameter (named,
  qualified, `keep`, or beside another parameter) is refused at the
  parameter's first token: `A 'void' parameter must be the only one, unnamed
  and unqualified: write '(void)'`. `void*` and other derived types are
  ordinary parameter types.
- **Unnamed parameters.** A parameter is unnamed when its type is followed by
  `,`, `)`, `[` or `=`. Only a `FunctionDecl` (including `extern` and
  `static` ones) may have them, and only when it ends in `;`. The parser
  checks this once the `)` is read: a body after an unnamed parameter, or an
  unnamed parameter in any other list, is refused at that parameter's first
  token with `Parameter name required: only a function prototype without a
  body may omit it`. An unnamed parameter takes no `keep` (`A 'keep'
  parameter requires a name`, at the `keep`) and no default (`An unnamed
  parameter cannot have a default value`, at the `=`), because a default
  belongs to the name named arguments use.
- **Semantics.** Name validation and duplicate checks skip `""`. A prototype
  and a definition are compatible when each parameter's name matches or
  either side is unnamed; arity, types and `keep` must still agree, and a
  mismatch reports `Conflicting declarations for function 'f'` at the later
  declaration in both compilers. The definition stays the function's
  registered owner, so named arguments and defaults use its names; a function
  declared only by an unnamed prototype can be called positionally.
  `int main(void)` is `int main()`.
- **Lowering.** An unnamed `IRParam` has the empty name and both emitters print
  its type alone (`int f(int, char*);`). An empty list still prints `(void)`.
- **Not in r01.** Abstract function-pointer declarators (`int (*)(int)`) are
  r07's.
- **Repeated prototypes.** Both compilers accept any number of compatible
  prototypes (btrcc used to refuse a second one). A named prototype
  supersedes an unnamed one as the registered declaration, so
  `int f(int); int f(int a); int f(int b) {}` conflicts at the definition in
  both compilers. A `(` list not followed by `;` or `{` is the ordinary
  `Expected LBRACE` error, not an unnamed-parameter refusal.

## Stage 16 r03: several declarators

- **One declarator parser per compiler.** `Parser._parse_declarators` and
  `Parser.parseDeclarators` read a declaration's declarator list once the
  first name and its array suffix are read: the first declarator's
  initializer, then per `,` its own `{*}`, name, array suffix and
  initializer. Locals and the C-`for` initializer (`_parse_declaration_head`,
  `parseVarDeclStmtsInto`), globals (`_parse_function_or_var_decl`,
  `parseFunctionOrVarDeclInto`), struct fields, class fields and typedefs all
  call it, and the declarators come back as `VarDeclStmt`s that the field,
  member and typedef callers re-shape into `FieldDef`, `FieldDecl` and
  `TypedefDecl`. Statement lists splice through `_parse_block_item` /
  `parseBlockItemInto`; `_lookahead_is_var_decl` / `lookaheadIsVarDecl` treat
  `,` after the first name as a declaration boundary.
- **Specifier versus declarator.** `_parse_type_expr` still reads the first
  declarator's `*`s greedily. Each later declarator starts from a deep copy of
  the specifier (`copy.deepcopy`; btrc's `Parser.copySpecifier`) with no
  pointer level and no suffix extent, then binds its own `*`s and `[n]`, so
  `int *p, v;` makes `v` an `int` (D20). The specifier is everything else
  `_parse_type_expr` reads: qualifiers and storage class, the base, generic
  arguments, and btrc's prefix `[]`, so `int[] a, b;` and `Vector<int> a, b;`
  declare two arrays and two vectors. The copied `TypeExpr` keeps the
  specifier's position.
- **Positions.** The first declarator keeps the declaration's start (the
  access keyword for a class field, `typedef` for an alias); each later one
  starts at its first token, `*` or its name. A `FieldDef` stays positioned at
  its name, as before. A single declarator parses byte-identically to before.
- **Decisions.** Class fields are in scope: `public int x = 1, y;` declares two
  fields with the same access, each with its own initializer; a property
  declares one name. `typedef int A, *B;` declares one alias per declarator,
  `*` bound to each; a typedef declarator takes no array suffix until Stage
  18. `T? a, b` is refused at the `,` (`A nullable declaration declares one
  variable: write one declaration per nullable variable`), and so is a second
  `var` declarator (`'var' declares one variable: write one 'var' declaration
  per variable`). A function declarator beside others is legal C and refused
  at its name either way round (`Function 'f' must be declared on its own, not
  beside other declarators`). A missing later name is `Expected declarator
  name, got …`; a keyword there is the reserved-word refusal. `int a[], b;`
  meets the ordinary unsized-array refusal for `a` alone.
- **Semantics.** Splicing makes each declarator an ordinary declaration, so
  the analyzer and lowering need no change: duplicates use the existing
  per-scope, global, field and typedef checks; a name enters scope after its
  own declarator (`int a = b, b = 1;` is `Unresolved identifier 'b'`);
  initializers lower in source order; each declarator gets its own `IRVarDecl`
  and cleanup slot. btrcc now reports a duplicate local at its name with the
  reference's wording and words a duplicate struct field as it does, and it
  checks a C-`for` initializer's declarators for duplicates (it used to emit
  C that redeclared the name). A duplicate class field or typedef and an
  unknown name keep the two compilers' existing wordings; the refusal test
  pins each per compiler. The parity review found that btrcc never checked a
  `switch` case's own declarations for duplicates (`case 1: int a, a;`); it
  now does, as the reference does, with each case its own scope in both. A C-`for` initializer with several declarators keeps them
  in `ForInitVar.declarations`, and both compilers lower every for-init
  declaration (one or many) to declarations in a block enclosing the `IRFor`,
  as single declarations already did, so the loop variables keep the loop's
  scope.
- **Tooling.** LSP document symbols list every spliced field and typedef with
  its own range, and global variables as `Variable` symbols. The formatter
  needed no change (it lays out tokens).
- **Tests.** `c_compat/MultipleDeclarators.btrc` covers locals, `int
  *pointer, value;`, globals, struct and class fields, typedefs, the C-`for`
  initializer, left-to-right side effects and per-declarator ARC (creation and
  destruction counts across a block and a loop with `continue`). The refusals
  above and the duplicate, scope and binding cases are pinned in
  `btrc/test_c_compatibility_refusals.py`; inventory rows
  `r03-multiple-local-declarators`, `r03-pointer-declarator-binding` and
  `r03-multiple-field-declarators` are PASS.

## Stage 16 r19: the comma operator in `for` headers

- **Parser.** `Parser._parse_for_header_expr` / `Parser.parseForHeaderExpression`
  read the C-`for` initializer (when it is not a declaration) and the update:
  two or more operands become `CommaExpr(elements)` positioned at the first
  operand, one stays a plain expression. The condition still takes one
  expression (`Expected SEMICOLON, got COMMA`), and `(a, b)` everywhere else
  stays a `TupleLiteral` (D19 row 19).
- **Analyzer.** A `CommaExpr` types as its last operand. Each operand is
  analyzed in order and refused if it observes a `Thread` handle, as the
  single header expression always was, and the reference's nullable-flow
  effects (an assignment recording or clearing a non-null fact) apply per
  operand, in order. In btrcc the comma is handled by the
  type resolver, the expression validator, the raw-parameter safety walk
  (`Borrows.rawParamExprSafe`) and the method-generic and generic-instance
  collectors; the value-origin and ownership classifiers never see one,
  because a `CommaExpr` is only ever the discarded root of a header.
- **Lowering.** Both compilers lower it to `IRCommaExpr`, each operand exactly
  as that header position lowers one expression, with every operand cast to
  `void`: both positions discard the value, and strict C11 otherwise warns
  about an unused operand. A
  discarded fresh managed result in a header is not released, with or
  without a comma; that predates r19 and is recorded in
  `docs/known-language-gaps.md`'s open gaps.
- **Realtime.** The bounded-loop proof (`RealtimeAnalyzer._canonical_c_for`,
  btrc `canonicalCFor`) now takes the induction variable from the declarator
  the condition compares, among any number of declarators, and accepts an
  update with exactly one canonical step of it. Every other declarator and
  update operand is checked, like the body, under a guard that forbids
  writing or taking the address of the induction variable or its bound (a
  declarator may declare the bound itself), so
  `for (int i = 0, n = 10, *q = &n; i < n; i++) { (*q)++; }` stays unproven.
- **GPU.** A kernel's comma header validates each operand as an update and
  emits one WGSL statement per operand.
- **Diagnostics.** A tuple literal assigned to or initializing a non-tuple
  adds `; btrc reads a parenthesized comma list as a tuple, not C's comma
  operator` in both compilers (`TypeSystem.comma_tuple_hint`,
  `TypeValidator.commaTupleHint`). The initializer diagnostic is identical;
  the assignment diagnostic keeps each compiler's existing wording
  (`Cannot assign … to 'int'` against btrcc's `Assignment expects 'int' but
  got …`), both with the hint, pinned per compiler.
- **Tests.** `c_compat/CommaForHeaders.btrc` (two-index loops with assignment
  and declaration initializers, operand order including `continue`, managed
  operands); the realtime suites accept multi-update loops and refuse a double
  step, a guarded write and an induction write in another initializer, in
  both compilers; a GPU probe emits identical WGSL; inventory row
  `r19-comma-in-for-header` is PASS and `r19-comma-operator-expression` carries
  the hint.

## Stage 16 integration notes (`ccompat-c1-integrate`)

The four C1 lanes (r02/r06 bodies, r01 parameters, r05 adjacent strings, r04
char arrays) landed in that order as separate merges. What the integration
step did and still owes, in both compilers:

- **Adjacent strings into a char array (done at integration).** r04's
  predicates and its extent owner (`string_initializer_byte_length` /
  `stringInitializerByteLength`) take any string constant, and the extent is
  the source-macro namespace's decoded length (`string_constant` /
  `stringConstantLength`), so `char s[] = "ab" "cd";`, a macro piece and a
  global all work, and the exact fit and overflow refuse with r04's
  diagnostics. `c_compat/CharArrayStringInit.btrc` and the refusal tests cover
  them through both compilers.
- **One decoder (done at integration).** r04's duplicate byte counters
  (`LiteralDecoder.string_byte_length`, `StringLiteral.byteLength`) are gone;
  r05's decoder is the one owner in each compiler, and the lexer test checks
  its byte counts.
- **Body IR proof in btrcc.** btrcc has no `--emit-ir`, so r02's
  braced-versus-braceless proof compares btrcc's C output, while the Python
  compiler compares raw IR.
- **Deferred by r04, all existing behavior shared with `int` arrays:** a bound
  the front end cannot evaluate (a C `#define` or `sizeof`) leaves the exact
  fit to the C compiler; a line splice inside a literal gains the emitter's
  indentation; a global used only through `sizeof(g)` is dropped by the
  optimizer; `const int N = 3; char t[N] = "abc";` is emitted as a VLA with an
  initializer.

## C2 aggregates (Stage 17) and array dimensions (Stage 18)

PLAN.md Stage 17 puts every C2 representation decision into one serial schema commit. That commit also fixes `TypeExpr`'s array dimensions for Stage 18 (r17). As a result, `src/language/ast.asdl`, the generated `Node` and dataclasses, the canonical renderers and the AST boundary records churn only once.

D19 approves every row:
- unions (r09)
- typedef records and anonymous members (r08)
- designated initializers and compound literals (r10)
- flexible array members with C11 semantics (r13, option a)
- bit-fields (r12)
- the enum tag spelling fix
- multi-dimensional arrays (r17)

Three read-only drafters and two adversarial reviewers (workflow `wf_104e132f-1a7`) compared the options on 2026-10-02. Every finding and its resolution is listed at the end of this section.

The fat `Node` gains no pointer. Two new scalars fill existing padding, and every other new field reuses storage that already exists. The parsers keep rejecting each new form until its lane lands.

C1's principles still hold:
- one representation per C concept;
- kinds that fail closed;
- positions identical in both parsers;
- deliberate refusals documented, with a test in both compilers.

### Decisions

| Row | Representation | Schema / IR change |
|-----|----------------|--------------------|
| r09 unions | `union U { … };` and `union U;` are `StructDecl(is_union=true)`, so every existing `StructDecl` consumer keeps working. A separate kind was rejected: btrc's kind dispatch skips unknown kinds silently, so a missed site would quietly drop a union from export, reachability, module units, native imports or the LSP. btrc always emits `typedef union U U;`, so `U` and `union U` are one type in btrc's single type namespace. Members are plain C values, transitively. A union has no ARC header and copies bitwise. `==`, print, f-strings, `new`, `delete`, `keep` and `release` are refused, as for structs. `{}` zero-initializes; a single positional element initializes the first named member (C11 6.7.9p17); a designator selects any member. Reading a member other than the last one written is C type punning (C11 6.5.2.3 footnote 95): documented, not checked. Native opaque unions import as `StructDecl(is_union=true)`. Native union values stay refused (ref:3191-3192). | `StructDecl.is_union`; `IRStructDef.is_union`; `IRStructForward.is_union`. Unions stay in `struct_defs` and `struct_forwards`, because a new `IRModule` list would change all four IR boundary artifacts. |
| r08 typedef records | The parser splices complete declarations, as C1 (b) does. `typedef struct [Tag] { … } D1, D2;` (or `union`) becomes one `StructDecl` followed by one `TypedefDecl` per declarator. `typedef enum` likewise becomes an `EnumDecl` plus its `TypedefDecl`s. Each `TypedefDecl.original` is a deep copy of the specifier, spelled as written (`struct P`) or as the synthesized name, with its own declarator's `*` and `[]` (D20). An untagged record takes its first plain declarator's name as its tag. `struct T` then names it too; this is a documented extension, because in C it names a different, incomplete type. A plain declarator equal to the tag is dropped. A tagged definition may also declare file-scope objects: `struct T { … } v, *p;` splices `VarDeclStmt`s. Record and enum definitions stay file-scope only. | none |
| r08 anonymous members | `AnonymousMember(is_union, fields)` is its own `field_def` constructor. It is legal only inside a struct or union body, and nesting is allowed. A walker that reads `.type` or `.name` from it fails loudly rather than resolving a bare `struct` to nothing. Its members belong to the enclosing record (C11 6.7.2.1p13): lookup is flattened, and names must be unique across the flattened set. In Stage 17 every member of an anonymous member is a plain C value, transitively, so a field walk that skips one misses nothing managed. Named members of an untagged type (`union { … } as;`) and nested tagged definitions are refused. | `AnonymousMember` (1 kind); `IRStructField.record`, an untagged `IRStructDef` emitted inline |
| r10 designated initializers | `BraceInitializer.elements` keeps the plain value expressions. Ownership, environment, thread-escape, realtime, GPU and evaluation-order checks therefore keep seeing the real value. Designators sit in a parallel list, `entries`. It is null until an element is designated; after that it holds one `Designation(parts)` per element, with empty `parts` for a positional element. `parts` is a chain of `FieldDesignator(field)` and `IndexDesignator(index)`. Only the initializer-slot owner reads designators. Elements evaluate in source order. Overlapping initializers and GNU ranges are refused. | `BraceInitializer.entries`; `designation` and `designator` (3 kinds, none of them an `expr`); `IRDesignation`; positional `IRCompoundLiteral` entries |
| r10 compound literals | `CompoundLiteral(target_type, initializer)`. Its `initializer` is always a `BraceInitializer`, so both analyzers plan it exactly as they plan `T tmp = {…}`. The head is a C11 6.7.7 type name. Inside a function the literal has automatic storage: one object per execution of the enclosing block, re-initialized at each evaluation (C11 6.5.2.5p5, p16). At file scope it is static and its operands must be constant. btrc lowers parameter defaults and class field initializers inside functions, so there it may be used only as a value. | `CompoundLiteral` (1 `expr` kind, appended); lowers to the existing `IRCompoundLiteral` and `IRInitializerList` |
| r13 flexible array members | A struct member `T name[]`, whose own `TypeExpr` has `is_array` and no `array_size`, is a flexible array member (FAM) when three conditions hold: it is the last member, it follows a named member, and it sits directly in a named struct's body (C11 6.7.2.1p3, p18). The type-position spelling `T[] name` is refused in struct and union bodies. The AST cannot tell it from `T name[]`, and silently giving a pointer-valued field FAM layout would break structs that mirror C. Class fields, parameters, locals and `typedef int[] V` keep btrc's pointer-valued `T[]`. A FAM struct exists only behind a pointer. | `IRStructField.is_unsized_array`, emitted as `T name[];` |
| x-enum-tag | `TypeExpr.base` keeps the written `enum Color`. A named plain btrc enum is emitted as `typedef enum Color { … } Color;`, so the spelling is valid C. The C tag aliases make `enum Color` the same btrc type as `Color` everywhere. An unknown `enum X` needs evidence of C that btrc does not read, because C11 6.7.2.3p3 forbids an incomplete enum (unlike an incomplete struct). | none; emission only |
| r12 bit-fields | `FieldDef.value` is the width (C11 6.7.2.1 `declarator : constant-expression`); it is null for an ordinary member. An unnamed bit-field is `FieldDef(name="", value=width)`, distinct by kind from `AnonymousMember`. The type is `bool`, `int`, `signed int` or `unsigned int`, and the width is an integer constant with a known value. Reads have the C11 6.3.1.1p2 promoted type. Compound assignment and `++`/`--` read, compute and store back through the containing object, never through the member's address. The layout is the C compiler's. | `FieldDef.value`; `IRStructField.bit_width` (folded integer); `IRFieldAccess.bit_field`, with a verifier rule that forbids taking its address |
| r17 multi-dimensional arrays (Stage 18) | `array_size` stays the outermost extent, and `elements` holds the inner extents, outermost first. For example, `int g[2][3][4]` is `array_size=2, elements=[3, 4]`. Rank is `1 + len(elements)` for an array and 0 otherwise. Only the outermost extent may be omitted or be a run-time (VLA) bound. `array_pointer_depth` counts the `*` applied outside the extents (`int (*p)[3]`). It is decided now so that x-pointer-to-array needs no second schema commit; the parsers refuse that form until its row lands. Lowering names each row type with a typedef chain, so a decayed rank≥2 value always has a prefix C spelling (`R3*`) and no IR declarator changes. | `TypeExpr.elements`; `TypeExpr.array_pointer_depth`; Stage 18 adds `IRTypedefDef.array_size` |
| C tags | When the registry registers a btrc record or plain enum, or a tagged native record or enum, it also enters `"struct X"`, `"union X"` or `"enum X"` mapping to `X` in the existing typedef alias index (Python `typedef_table`, btrc `typedefTable`). Every canonicalization then resolves a tag in one place, and each post-canonical `removeprefix("struct ")` becomes a no-op. One validator refuses a tag that names a declaration of another kind. An unknown `struct X` or `union X` stays a trusted foreign C tag, as today. | none |
| Layout | btrc computes no C2 layout in Stage 17; the emitted C carries it. Each row gets a corpus program that declares its aggregates in btrc and imports a C mirror returning `sizeof` and `offsetof` as `size_t`. `make test` covers both compilers, and `make test-c11` covers gcc and clang at `-O0` through `-O3`. | none |

### Shared owners

The main session lands two serial commits before the lanes fork: the schema commit, then a shared-owner commit. The shared-owner commit changes the behavior of no accepted program, except for the evaluator parity fix below. Each owner gets a contract test in both compilers.

- **Record members.** One stateless owner per compiler, as class methods on `TypeSystem` (Python) and `SemanticTypeSystem` (btrc); lowering already uses both classes.
  - It answers a record's direct members (`FieldDef` and `AnonymousMember`) and its flattened named members, each with its member path. Unnamed bit-fields are not members.
  - Every struct-field walk in both compilers goes through it: aggregate dependencies and ordering, ownership, thread and mutex payloads, realtime proofs, closure environments, module-unit collection and LSP symbols.
  - The contract test fails on a raw iteration of `StructDecl.fields` anywhere else. Today there are about 58 such walks in btrc.
- **Initializer slots.** Python `InitializerAnalyzer.plan_aggregate` and btrc `ExpressionValidator.validateStructInitializer` map each brace element to a member path or an array index.
  - The mapping flattens anonymous members, skips unnamed bit-fields and follows designators.
  - The plan is recorded in `AnalyzedProgram`, and in `Analyzed` keyed by `AstIdentity.key`.
  - Every site that pairs an element with a field reads the plan:
    - Python: `CollectionLowerer.plan_brace` and the `OwnershipAnalyzer` slot walks (`literal_slots`);
    - btrc: `analyzer/validation/Expressions.btrc` (the count message and element types), `analyzer/validation/Ownership.btrc` (`shallowElementType`) and `ir/lowering/{Expressions, Aggregates, Callables, CallableFlow}.btrc`.
  - The contract test fails on an element index paired with a field index outside the owner.
- **Integer constants.** One query in each compiler (Python `ExpressionAnalyzer.integer_constant_expression`, btrc `ConstantValidator.integerConstant`) gives one of three answers:
  - not a constant expression;
  - a constant expression btrc cannot evaluate (`sizeof`, or an unresolved native macro);
  - a value.

  Python adopts btrc's `long long` overflow rule. r10 indexes, r12 widths and r17 inner extents all use this query, so Stage 19's layout evaluator (D20) can later lift the middle case without changing any diagnostic.
- **C tag aliases** change behavior, so they land with r09 rather than in the shared-owner commit. r09 brings:
  - the alias rows for btrc and native records;
  - the wrong-keyword validator;
  - both import reference collectors counting `struct X`, `union X` and `enum X` as references to `X` for strict imports. Today Python `ImportReferenceCollector` records the whole spelled base, so `struct X` requires no import.

  The enum lane registers enums on the same owner. Alias keys contain a space, so they never collide with a source name and claim no name. No consumer iterates the alias index; a contract test checks this. Generic instance identity does not resolve aliases, so the rows change no instance or symbol.

### Conventions both parsers keep identical

**Positions** are canonical AST data:

- `union U { … }` and `union U;` sit at `union`, with the name at the tag, as structs do.
- A spliced typedef record or enum sits at its keyword. Its name sits at the tag, or at the naming declarator when the tag is synthesized. Its `TypedefDecl`s are positioned as C1 (b) positions declarators. `typedef struct P P;` without a body renders byte-identically to today.
- `AnonymousMember` sits at its `struct` or `union` keyword.
- A named `FieldDef` keeps its line and column at its name. An unnamed bit-field has name `""` and sits at its type's first token, as an unnamed `Param` does.
- `FieldDesignator` sits at `.` and `IndexDesignator` at `[`. `Designation` has no position.
- `CompoundLiteral` sits at `(`; its `BraceInitializer` keeps its `{` position.
- The first bracket fills `array_size` and later brackets fill `elements`. `nullable_outer_depth` grows by one per extent.

**Disambiguation:**

- **Designations.** In a brace initializer:
  - an element that starts with `.` IDENT is a designation;
  - an element that starts with a `[…]` group and continues through further `.f` or `[k]` to `=` is a designation;
  - `[2]` followed by `,` or `}` stays a list literal;
  - map literals still need `:`.

  This retires the misleading `{[2] = 7}` diagnostic. Elements of the form `[…] = v` parse as designations from now on.
- **Range designators.** `[a ... b]` is refused in both of its token forms: three `.` tokens today, and the `...` token that Stage 19's vocabulary commit adds. One probe pins the diagnostic across r14.
- **Compound literals.** `(` type_name `)` `{` is a compound literal. `{` is not in the cast-follow set, so no cast changes meaning.
  - A head that is a bare identifier is a compound literal syntactically. Per-file parse caching hides imported names (as for r07), so the analyzer refuses a head that names no type.
  - **Exception:** in the iterable of a for-in or parallel `for`, a head that also parses as an expression, `(IDENT)` or `(IDENT[expr])`, stays the iterable when `{` follows, and the `{` opens the body. `for x in (items) {` keeps working; a compound literal there is written `for x in ((T){…}) {`.
- **Type names.** `type_name = type_expr [ array_declarator ]` (C11 6.7.7) is the one abstract form.
  - Its `[]` is C's array of unknown size, never btrc's pointer-valued `T[]`.
  - r10 uses it for compound-literal heads, Stage 18 for `sizeof(type)`, and Stage 19 for `_Alignof` and `_Static_assert`.
  - Casts to an array type stay refused (C11 6.5.4p2).
- **Record bodies.** In a struct or union body:
  - `struct` or `union` followed directly by `{` is an anonymous member;
  - `type_expr : expr ;` is an unnamed bit-field;
  - `: expr` after a declarator is a width;
  - `T[] name` is refused (P1).
- **Array spellings.** `T[][]` and `T[] name[N]` get the one-dimension refusal; `T[]` alone keeps its btrc meaning.

**Rendering and generated code:**

- **Render order.** New fields render in ASDL order:
  - `is_union` after `is_forward`;
  - `value` after `name`;
  - `elements` after `array_size`;
  - `array_pointer_depth` after `is_volatile`;
  - `entries` after `elements`.

  The Python renderer is generic. The btrc `AstCanonicalRenderer` adds each line and a branch for each new kind, and the generator contract checks them.
- **Child order.** Declaring `elements` on `TypeExpr` moves `elementsStorage` next to `arraySize` in `Node`, and `AstStructure.children` follows field order, so its `elementsStorage` line moves too (`test_ast_structure_contract.py`). Pre-order keys of existing kinds do not change, because no existing kind has `elements` beside another child list.
- **Copies.** `TypeExpr` copies carry both new fields:
  - `array_pointer_depth` is copied like `pointer_depth`.
  - `elements` is copied only when written: if `src.elementsStorage != null`, its nodes are copied into `dst.elementsMut()`.
  - A reader's result (`elements()`, `genericArgs()`) is never stored in a field. Node.btrc forbids storing the shared empty list, and AGENTS.md measured that pattern at 2-3x slower.
  - `TypeShape.copyWithArguments` and `TypeShape.copy` already store `genericArgs()` this way. Fixing them is a separate, measured change.
  - A contract test requires every btrc site that sets `arraySize` on a copy to handle both new fields.
- **Type encoding.** btrc `TypeIdentity.encodable` returns false when `elementsStorage` is non-empty or `arrayPointerDepth` is non-zero, as it already does for `arraySize`. `appendEncoded` is unchanged, so rank-1 encodings stay byte-identical, and module units never replay `int m[][3]` as `int[]`.

**Kind coverage** (extends C1's rule):

- **`CompoundLiteral`** is an `expr`, so its lane audits every site that might meet it:
  - every btrc switch that handles `NK_BRACE_INITIALIZER` (51 sites in 21 files) or `NK_TERNARY_EXPR`;
  - every Python file that names `BraceInitializer` (16 files).

  This matters because ownership predicates (`OwnershipLowerer.owns_result`, `OwnershipAnalyzer._contains_managed_callable_value`, btrc `expressionOwnsResult`) return false for a kind they do not know. A contract test requires each such site to name the compound literal too, or to sit on a reasoned allow-list.
- **Designators** are reached only by the parsers, the renderers, `AstStructure.children`, frontend visibility and the slot owner; a contract test checks this. The generic walkers already visit `entriesStorage`, `partsStorage` and `index`, so `[RED] = 1` keeps its import and reachability edges.
- **`AnonymousMember`** is reached only through the record-member owner.

### Rules by row

#### r09 unions

- **Declaration.** Unions are declared at file scope, with a forward form. Anonymous top-level unions are refused, as structs are.
- **Members.** This extends `TypeSystem.is_realtime_pod`.
  - Allowed: integers, floats, `bool`, `char`, plain enums, and raw pointers whose pointee is not `string`, a class or an interface. Also allowed: `CFunction` pointers with no managed type in their signature, fixed arrays and records of these, foreign tags, and bit-fields.
  - Refused: `string`, classes, interfaces, nullable references, collections and other generic classes, `Span`, `Atomic<T>`, `Thread`, `Mutex`, rich enums, closures and `RealtimeFunction`.
  - Refused on purpose: a flexible array member (C11 6.7.2.1p18) and the `T[] name` spelling. r09 owns both refusals from its first commit, so main never accepts `union U { int n; int d[]; };` with pointer layout.
- **Where unions may appear.** Struct and class fields, array and `Vector` elements, generic arguments, parameters and returns. `sizeof` comes from the emitted C. A union is realtime POD by construction. `@gpu` refuses it through the existing int/float/bool rule, pinned by a test.
- **Initialization.** Positional initialization lowers to a designator of the first member, `(U){.i = 5}`, just as positional struct initialization already lowers to named fields. An aggregate first member needs its own braces, because btrc has no brace elision.
- **Objective-C sites.** These sites rebuild IR records or per-field compound literals from `FieldDef`s: btrc `DeclarationLowerer.objectiveCUnit` and `objectiveCValue`, and their Python counterparts in `ir/lowering/functions.py`. Each asserts that the record is not a union and raises an internal error otherwise, so a later native-union lift must handle each one explicitly.

#### r08 typedef records and anonymous members

- **Identity typedefs.** A source `typedef struct X X;` (or `union`, `enum`) is a redeclaration when it has no qualifier, pointer, array or generic argument and X is a btrc record or enum declared with that keyword anywhere in the program.
  - Registration therefore indexes records and enums before it classifies typedefs, because C puts `typedef struct P P;` before `struct P { … }`.
  - If no btrc declaration exists, the typedef stays an ordinary foreign typedef, as today.
  - Native typedefs keep the importer's rules.
- **Aliases.** `typedef struct P { … } Q;` is an ordinary typedef: `Q`, `P` and `struct P` are one type through the tag aliases. `typedef enum { … } T;` is `enum T { … };`, so `enum T` resolves too.
- **Anonymous members.**
  - `s.m` searches the record's own members, then its anonymous members recursively; the C spelling is the same `s.m`.
  - A name collision is refused at the later member in source order.
  - An anonymous member is one positional slot and needs its own braces (`{1, {7}}`). Inside those braces the union first-member rule or the struct positional rule applies.
  - Designators name flattened members (`{.integer = 7}`). The anonymous type cannot be named in C, so lowering writes every initializer of such a record as flattened designators: `(struct Value){.kind = 1, .integer = 7}`.
  - A positional element directly after a designator that reaches into an anonymous member is refused, rather than following C's "next subobject" rule through it.
- **Layout.** Stage 19's layout model (r15c) adds the union rule (largest size and alignment) and the inline anonymous-member rule. Until then no front-end layout query sees these records.

#### r10 designated initializers

- **Targets.** Structs, unions, and fixed or unsized arrays, nested to any depth: at block scope, at file scope, in static locals and inside compound literals. Tuple, collection, `Map` and class targets are refused, `._0` included.
- **Current object.** The innermost enclosing brace is the current object (C11 6.7.9p17-20).
  - `.f` names a flattened member.
  - `[k]` must be an integer constant with a known value in `[0, bound)`.
  - An unsized outermost array's extent is the largest index plus one. It is recorded in the analysis result and used by `sizeof`, for-in and global declarations.
  - A positional element after a designated one continues at the next member or index.
- **Brace elision.** None, as today.
- **Overrides are refused.** Each initializer designates a path of members and indexes, with anonymous members made explicit. Two initializers conflict when:
  - one path is a prefix of the other; or
  - the paths first diverge at a union, choosing two different members of it.

  Two members of one anonymous struct inside an anonymous union therefore do not conflict. A positional element that lands on a designated slot conflicts by the same rule. C11 6.7.9p19 overrides silently, and footnote 151 lets the overridden initializer go unevaluated; gcc's `-Woverride-init` also fails the strict `-Werror` build.
- **Other rules.**
  - Unnamed subobjects are zero-initialized (C11 6.7.9p21).
  - Static initializers need constant values.
  - A string literal designated into a `char[]` member follows r04.
  - A native record with private fields accepts designators that name its public fields; the rest are zero.
- **Lowering.** A designator chain is normalized: `.a.b = x` becomes a nested initializer for `a`. That is a nested `IRCompoundLiteral` for a nameable struct or union member in an expression context, and an `IRInitializerList` in static initializers and for array members. `IRDesignation` is therefore always one step, and its index is the folded value as an `IRLiteral`.

#### r10 compound literals

- **Type.** A complete object type, or an array of unknown size whose extent comes from the initializer (C11 6.5.2.5p1).
  - Allowed: struct, union, tuple, array, scalar and raw pointer types.
  - Refused: VLA, `void`, incomplete and managed types.
  - The expression's type is T, with an unsized array made sized; arrays decay as named arrays do.
- **Lvalue.** A compound literal is an lvalue (C11 6.5.2.5p4): `&`, `++`/`--`, assignment and member or index stores apply.
- **Initialization** reuses `InitializerAnalyzer.plan_typed` and `ExpressionValidator.validateInitializerValue` on the nested brace. That includes designators, the union first-member rule and shallow managed elements.
- **Whole initializer.** A compound literal that is the whole initializer of a declared struct, union, tuple or scalar object of the same unqualified type is that object's initializer, everywhere. This is required at file scope and for static locals, where gcc `-pedantic-errors` rejects a compound literal as non-constant. An array object initialized by an array compound literal is refused, as in C11 6.7.9p16.
- **File scope.** `T* p = &(T){…};` and `int* p = (int[]){…};` are address constants and are accepted. Anything else non-constant is refused.
- **Escapes.**
  - Returning the address of a block-scope compound literal is refused, whether directly or through a cast, ternary or comma arm, and whether by `&` or by a decaying array. gcc `-Wreturn-local-addr` and clang `-Wreturn-stack-address` fail the strict build.
  - Initializing a static object with such an address is refused.
  - Other escapes follow C, as `&local` does, and are documented.
- **`try`.** A compound literal whose address is used (`&`, array decay, `++`/`--`, a member or index store) cannot appear in a block that contains a `try` statement. Value-only uses are unaffected. The reasons:
  - after `longjmp` the object is indeterminate if it was modified (C11 7.13.2.1p3);
  - it has no declaration the setjmp planner could qualify;
  - the qualifier-safety pass already refuses source address aliases across `setjmp`.

  The literal stays at its source position, so Stage 20's `goto` sees C's own semantics.
- **Parameter defaults and class field initializers.** Both are lowered inside a function, so a compound literal there is a value: `&`, decay, `var` array aliases and stores are refused.
- **`sizeof`.** `sizeof (T){1}` without the outer parentheses stays a parse error, because btrc's `sizeof` always takes parentheses; `sizeof((T){1})` works.
- **`@gpu` and `@realtime`.** Refused in `@gpu`; allowed in `@realtime` when its operands are.

#### r13 flexible array members

- **Placement.** One FAM, last, after at least one named member, directly in a named struct's body. Members of an anonymous member count as named; an unnamed bit-field does not.
- **Element type.** A complete type: a scalar, an enum, a raw or function pointer, a struct without a FAM, or (Stage 18) a fixed array. Managed elements are refused for now; relaxing to the shallow-aggregate rule later is compatible, while tightening would not be.
- **Layout follows C.** The size is the size as if the FAM were omitted, plus trailing padding, with the element's alignment counted:
  - `struct {char c; double d[];}` has size 8;
  - `struct {double x; char c; char d[];}` has `offsetof(d) == 9` and size 16.

  r15c's front-end model must implement the same rule, with `#pragma pack` capping both.
- **Access.**
  - `p->data[i]` is an lvalue of the element type; `p->data` decays to `T*`; `&p->data[i]` is allowed.
  - The FAM is array storage, not a pointer slot. Assigning it, `sizeof(p->data)` and `&p->data` are refused, and for-in over it has no capacity.
  - Borrow analysis treats it like a fixed array field.
  - Pointer arithmetic on `struct Buffer*` is allowed.
- **Only behind a pointer.** A FAM struct exists only behind a pointer to allocated or C-provided storage.
  - Refused: objects of the struct (local, global, `static`, `extern`, `var`); by-value parameters and returns; casts to it; brace and compound-literal initialization; whole-object copy or assignment (`*a = *b`); `new`; and storage inside arrays, records, tuples, rich-enum payloads and generic arguments. C11 6.7.2.1p3 makes that last group a constraint violation anyway.
  - Allowed: `sizeof(struct S)` and `sizeof(*p)`.
  - C11 permits the object declarations, the partial copy `*s1 = *s2` (6.7.2.1p25) and `extern struct S g;`. btrc refuses them on purpose. `docs/known-language-gaps.md` lists each in "C that btrc rejects on purpose", with a test in `test_c_compatibility_refusals.py`.
- **Allocation** is documented and needs no runtime helper:

  ```
  struct Buffer* b = (struct Buffer*)calloc((size_t)1, sizeof(struct Buffer) + (size_t)n * sizeof(int));
  ```

  then a NULL check, then `free(b)`. Growth uses `realloc` with the same size expression (C11 6.7.2.1p20). `offsetof`-exact sizing waits for btrc `offsetof`.
- **Typedefs.** A typedef never makes a FAM: `typedef int[] V` stays btrc's pointer alias. If r03 accepts typedef declarator suffixes, `typedef int V[];` is refused.

#### Enum tags

- **Resolution of `enum X`, in order:**
  1. a btrc plain enum;
  2. a native enum tag (the importer registers `enum <tag>` for each tagged native enum);
  3. a declaration of any other kind named X, which is refused with the tag template;
  4. an unknown X.
- **Unknown `enum X`.** It is accepted as a C tag only when the source file that spells it names C that btrc does not read. That means either:
  - an import edge from that file to a `.c` file in the source dependency graph (the graph strict imports use); or
  - a quoted `#include "…"` of a non-`.btrc` target.

  A system `#include <…>` is not evidence. 1,100 of the 1,203 test sources contain an `#include` (1,096 of them a system one), so counting it would disable the rule, and a system enum reaches btrc through a native import anyway. The fact is computed from the file's own source, so module units compute it identically. `basics/InteropCEnumBaseType.btrc` stays green through its `.c` import.
- **Generic instance identity** keeps the written spelling, as it already does for `OwnedBuffer<struct X>` in `stdlib/Audio/RealtimeAudioRouter.btrc` and `tests/memory/OwnedBuffer.btrc`. `Vector<enum Color>` and `Vector<Color>` are two instances, just as `OwnedBuffer<struct P>` and `OwnedBuffer<P>` are today.
- **Tag ownership.** A btrc enum owns the C tag of its name. C has one tag namespace, and Apple SDK tags are PascalCase (`struct CGPoint`). A btrc enum whose name equals a record or enum tag registered by a native import is therefore refused at the enum. A clash with a header btrc does not read is reported by the C compiler, as for any tag.

#### r12 bit-fields

- **Where.** Struct and union bodies only. Not class fields, locals, globals, parameters, typedefs or rich-enum payloads.
- **Type.** After typedef resolution: `bool` (`_Bool`, D20), `int`, `signed int` or `unsigned int`, or a btrc spelling that canonicalizes to one of them (`uint`), optionally `const` or `volatile`. These are the types strict C11 accepts under `-pedantic-errors`.
  - Plain `int` is signed. C11 leaves this implementation-defined; gcc and clang are signed on every supported target, and this is documented.
  - Fixed-width typedefs (`uint32_t`) are refused for now.
- **Width.** An integer constant with a known value: literals, character constants, enum members, casts, arithmetic and ternaries, plus source macros once C4 supplies their values.
  - `0 <= w <= 32` for the int family (int is 32 bits on every hosted-ABI target), and `w <= 1` for `bool`.
  - `w == 0` only for an unnamed bit-field.
  - The IR carries the folded width, so both compilers print the same digits and no declaration walker gains references.
- **Naming.** Named bit-fields follow member naming and duplicate rules. Unnamed ones are not members: lookup, designators, positional initialization (C11 6.7.9p9) and LSP symbols skip them. A record must keep at least one named member.
- **Read type.** Reads have the promoted type:
  - `int` for `int`, for `signed int`, and for `unsigned int` narrower than 32 bits;
  - `unsigned int` for `unsigned int : 32`;
  - `bool` for `bool`.

  This is the promotion btrc already gives `unsigned char` and `short`, so lowering needs no cast. `var x = s.f` and print and f-string formats follow it.
- **Stores.** Stores convert as C does: unsigned values wrap modulo 2^w, and signed out-of-range values wrap on gcc and clang. An integer constant that does not fit is refused.
- **Compound assignment and `++`/`--`.**
  - They read into a value temporary, compute with btrc's typed arithmetic, and store back through the member lvalue. Postfix forms yield the old value.
  - When the receiver must be evaluated once, lowering stabilizes the containing object (`&recv` for `.`, the pointer for `->`) and stores through `p->f`.
  - btrc `ExpressionLowerer.lowerDirectStore` and `lowerDirectCompound` currently take `&target` for every non-identifier store; they must take the containing object instead.
- **Never addressable.** `&s.f`, `sizeof(s.f)` (C11 6.5.3.4p1), `offsetof` (C11 7.19p3) and, from Stage 19, `_Alignof` and `_Alignas` (C11 6.7.5p2) are refused.
  - Lowering marks every bit-field access `IRFieldAccess.bit_field`.
  - A post-optimization check refuses an `IRAddressOf`, an array decay or an out-parameter adapter whose root is such an access. In Python the check is `IRVerifier`; in btrc it is `CEmitter`, which runs after the optimizer.
  - An address-taking rewrite added later, such as setjmp stabilization or an optimizer pass, therefore cannot slip through.
- **Layout.** The C compiler's. A struct with bit-fields has no front-end layout, so a D20 `_Static_assert(sizeof(S) …)` on it is refused. `#pragma pack` passes through.
- **Boundaries.**
  - `@gpu` refuses structs through the existing rule, pinned by a test.
  - Objective-C value projections keep refusing them.
  - Native records keep "anonymous fields and bitfields require native-type lowering" (ref:3191-3192).
  - Source structs with bit-fields may cross into C, because the same C compiler builds both sides.
- **Concurrency.** Adjacent bit-fields share one memory location (C11 3.14), so concurrent writes to neighbours race. This is documented, not analyzed.

#### r17 multi-dimensional arrays (Stage 18)

- **Rank.** The element type of a rank-k array is rank k-1. Python `TypeSystem.strip_outer_storage(array=True)` and btrc `TypeShape.withoutOuterArray` pop one extent (`array_size <- elements[0]`).
  - One rank helper per compiler replaces every storage-level `int(is_array)`.
  - Rank 1 equals `int(is_array)`, so rank-1 shape keys, symbols and generated C do not change.
  - Without the helper, `char names[4][16]` would pass for a C string.
- **Extents.** Inner extents are integer constants with known values. They are recorded per extent in the analysis result: Python `constant_array_bound_ids` and btrc `constantArrayBoundKeys` each become a value map.
  - Only the outermost extent of a local may be a run-time bound (row 23).
  - Inner run-time extents (`int a[n][m]`) are refused and listed in the VLA table. A block-scope, variably modified `IRTypedefDef` is the path to supporting them later.
- **Storage.**
  - Allowed holders: locals, globals, struct fields, class instance and static fields, `extern T g[][N]`, and C-for initializers.
  - Elements are scalars, raw pointers or non-managed structs; managed or nullable elements are refused.
  - Initializers brace every row, because brace elision fails `-Wmissing-braces` under `-Wall -Werror`. `int g[][3] = {{…}, {…}}` infers the outer extent, and each level's count is checked.
  - Arrays stay unassignable and unreturnable.
- **Decay.** A rank≥2 value decays to a pointer to its rows.
  - Allowed: indexing, unary `*`, `sizeof`, passing to a parameter whose inner extents are equal by value, and passing to `void*` or `const void*`.
  - Refused until x-pointer-to-array lands: `&a`, arithmetic, comparison, casts, assignment to a pointer, `var`, `return`, `Span`, generic and collection elements, and `CFunction` or callable signatures.
  - A single row (`grid[i]`) is an ordinary 1-D array.
- **Parameters** keep the declared array type. For rank≥2, `array_parameter_value_type` and `arrayParameterValueType` drop only the outer extent, and the binding is the row-typedef pointer. `sizeof` of a rank≥2 array parameter is refused.
- **Qualifiers** apply to the elements (C11 6.7.3p9). `int (*)[3]` and `const int (*)[3]` are therefore incompatible in C11, and gcc `-pedantic-errors` rejects the implicit conversion. Lowering inserts an explicit cast, `(const R3*)arg`, whenever a conversion only adds element qualifiers to a row pointer, including for iterator and stabilization temporaries. A strict C11 corpus case passes a non-const 2-D array to a const parameter.
- **Iteration.** for-in and parallel `for` over a rank≥2 array are refused (index the rows with a C `for` instead); `for x in grid[i]` works.
- **Typedefs.** If r03 parses typedef declarator extents, `typedef int Row[3]` makes `Row g[2]` compose to `int[2][3]`. An unsized typedef target cannot be an element. btrc's prefix `typedef int[] X` keeps its meaning.
- **`@gpu`** refuses rank≥2 everywhere and never flattens.
- **Lowering.**
  - `CTypeLowerer` owns an `ArrayTypedefRegistry` beside its function-pointer registry. It registers one typedef per (element, inner extent values) as a chain: `int[2][3][4]` emits `typedef int R4[4]; typedef R4 R34[3];`.
  - Names are deterministic and identical in both compilers, built from the element's type-identity encoding and the extents. The typedefs are drained into `typedef_defs`.
  - A declaration keeps today's shape: the row typedef plus the existing outer `array_size` or `is_unsized_array`, so `int grid[2][3]` emits `R3 grid[2];`.
  - `CTypeLowerer.render` stays the decayed C type: `T*` for rank 1 and `R*` for rank≥2.
- **Native fields.** Native fixed multi-dimensional fields of scalar elements are lifted in their own commit after the corpus lands.

### Evaluation order and ownership

- **Source order.**
  - Brace elements (designated or not) and compound-literal operands evaluate in the order they appear, depth-first through nested braces, never in member or declaration order.
  - This extends the pinned left-to-right aggregate order (`test_aggregate_evaluation_order_parity.py`, btrc `AggregateEvaluationPlan`, Python `CallableProvenance.plan_evaluation`). C11 6.7.9p23 leaves the order indeterminate, so this is a btrc guarantee, tested in both compilers with out-of-order designators.
  - When any operand has an effect, operands are hoisted to temporaries in source order; otherwise C's order is unobservable.
  - A compound literal is one operand of its enclosing expression. A lvalue operator applied to it stays inside the evaluation boundary: `(t1 = f(), t2 = g(), &(T){.x = t1, .y = t2})`, never `&` applied to a comma result.
- **One evaluation of a receiver.** Bit-field updates stabilize the containing object, never the member. A VLA outer extent is evaluated once (row 23).
- **No ARC in C2 storage.**
  - Unions, anonymous members, FAM elements and bit-fields hold plain C values only.
  - Brace initializers and compound literals of structs, unions, tuples and arrays are shallow. Managed elements are borrowed references, and a caller-owned temporary is refused with the existing message.
  - A compound literal is never retained or released and has no ARC header.
- **Lifetimes.**
  - A block-scope compound literal lives until its enclosing C block ends; a file-scope one is static.
  - Returned addresses, and statics initialized from automatic literals, are refused.
  - The `try` rule above covers `setjmp`.

### Refusals

Each refusal below has the same text and position in both compilers. Each also has either a negative probe in `c2.toml`, or, for a deliberate C11 refusal, a test in `test_c_compatibility_refusals.py`. Declaration refusals sit at the named member (its name, or its type when it is unnamed); type refusals sit at the `TypeExpr`; use refusals sit at the operator or access.

Before r09 derives union wording from the struct messages, it makes those messages identical in both compilers. btrc adopts Python's existing wording for duplicate fields, duplicate definitions and empty bodies.

**Records and tags (r09, enum lane)**

| Case | Diagnostic |
|------|------------|
| Duplicate member, at the later one | `Duplicate field 'x' in struct 'S'` (or `in union 'U'`) |
| Second complete definition | `Duplicate definition of struct 'S'` (or `union 'U'`) |
| Empty body | `Struct 'S' cannot have an empty body under strict C11` (or `Union 'U'`) |
| Untagged top-level union | `anonymous union at top level must be named` |
| Struct and union with one name | `Top-level name 'U' is declared as both struct and union` |
| Unknown member | `Union 'U' has no field 'z'` (the struct form exists) |
| Tag of another kind, in every type position | `'union P' does not name a union: 'P' is a struct` (kind word: struct, union, enum, rich enum, class, interface, typedef) |
| Unknown `enum X` without evidence (`x-enum-tag-unknown`, at 2:2) | `Unknown enum 'Missing'; declare it, or import the C source that declares it` |
| btrc enum named like a native tag, at the enum's name | `Enum 'Foo' would declare C tag 'enum Foo', which conflicts with 'struct Foo' from a native header; rename the enum` |
| Managed union member | `Union 'Holder' member 'text' cannot hold managed type 'string'; a union cannot tell which member is live, so its members must be plain C values` |
| Managed field reached through a by-value member | `Union 'Holder' member 'pair' cannot hold 'Pair', which contains managed field 'name'; a union cannot tell which member is live, so its members must be plain C values` |
| `Atomic<T>` member | `Union field 'U.counter' cannot embed an Atomic<T> owner in shallow copyable storage; keep Atomic<T> as a direct class field or local owner` (existing template) |
| `RealtimeFunction` member | `Union 'U' member 'callback' cannot hold a RealtimeFunction; a union could reinterpret it without its realtime proof` |
| Unsized array member (C11 6.7.2.1p18) | `Union member 'U.data' cannot be a flexible array member` |
| `T[] name` member | `Union field 'data' cannot use the 'T[] name' spelling; declare a pointer as 'T* data'` |
| Two positional elements | `Union 'U' initializer has 2 elements; a positional union initializer sets only the first member (use a designator such as {.f = ...})` |
| Union in `@gpu` | existing `@gpu function 'k': type 'U' not allowed in parameter (use int, float, or bool)` |

**Typedef records and anonymous members (r08)**

| Case | Diagnostic |
|------|------------|
| Untagged record with no plain declarator | `An untagged struct in a typedef needs a plain declarator to name it; add a tag (typedef struct Name { ... } *Alias;)` (also union, enum) |
| Untagged definition that declares objects | `An untagged struct definition needs a tag to declare 'v'; write 'struct Name { ... } v;'` |
| Qualified identity typedef | existing `Top-level name 'P' is declared as both struct and typedef` |
| Synthesized tag that collides | existing `Duplicate definition of struct 'T'` or `Top-level name 'T' is declared as both ...` |
| Member collision through an anonymous member (`r08-anonymous-member-collision`, at 3:14) | `Duplicate field 'integer' in struct 'Value'` |
| Managed anonymous-member member | `Member 'text' of an anonymous union in struct 'Value' cannot hold managed type 'string'; anonymous members must be plain C values` |
| Named member of an untagged type | `Member 'u' of struct 'S' has an untagged union type; declare 'union Name' at file scope or make the member anonymous` |
| Nested tagged definition | `A union defined inside struct 'S' must be declared at file scope` |
| Anonymous member in a class | `Anonymous struct and union members are only allowed in struct and union declarations` |
| Positional initializer without the member's braces | `The anonymous union member of struct 'Value' requires its own braces in a positional initializer` |
| Positional element after a designator into it | `A positional initializer cannot follow a designator into an anonymous member; designate the next member` |
| Unnamed member that is neither form | `Struct 'S' declares an unnamed member that is neither a bit-field nor an anonymous struct or union` |

**Designated initializers and compound literals (r10)**

| Case | Diagnostic |
|------|------------|
| Unknown member, at the `.` (`r10-unknown-field-designator`, at 3:24) | `Struct 'Point' has no field 'z'` |
| `.f` on a non-record | `Designator '.x' needs a struct or union, but the initialized type is 'int[4]'` |
| `[k]` on a non-array | `Designator '[2]' needs an array, but the initialized type is 'Point'` |
| Non-constant index | `Array designator index must be an integer constant expression` |
| Constant btrc cannot evaluate | `Array designator index is a constant expression btrc cannot evaluate; write its integer value` |
| Index out of range, or negative | `Array designator index 5 is outside 'int[4]'` |
| Positional continuation past the bound | `Initializer element for index 4 is outside 'int[4]'` |
| Member initialized twice (`r10-duplicate-designator`, at 3:32); names the outermost overlapping member | `Field 'x' of struct 'Point' is initialized more than once (first at 3:24); each member may be initialized once` |
| Element initialized twice | `Index 2 of 'int[4]' is initialized more than once (first at 3:20); each element may be initialized once` |
| Two members of one union | `Union 'U' initializer sets both 'i' and 'f'; a union initializer sets one member` |
| Wrong target, tuples included | `Designated initializers apply to structs, unions and arrays, not 'Vector<int>'` |
| No contextual type (`var p = {.x = 1};`) | `A designated initializer needs a declared struct, union or array type` |
| GNU range | `Range designators ('[a ... b]') are a GNU extension, not C11; designate each index` |
| Managed literal type (also string, collections, Atomic, Thread, Mutex, Span, rich enums) | `Compound literal type 'Foo' is managed; compound literals build plain C values (construct a class with new or its constructor)` |
| VLA type | `Compound literal type cannot be a variable-length array` |
| `void` | `Compound literal type cannot be void` |
| Head names no type | `'x' is not a type; a compound literal needs a type name` |
| Empty unsized array | `An unsized array compound literal needs at least one element` |
| Non-constant at file scope | `A file-scope compound literal has static storage; its initializers must be constant expressions` |
| Automatic literal's address in a static | `A compound literal inside a function has automatic storage; its address cannot initialize a static object` |
| Returned address | `Cannot return the address of a compound literal; it has automatic storage that ends with its enclosing block` |
| Address used in a block containing `try` | `A compound literal whose address is used cannot appear in a block that contains a try statement; declare a local instead` |
| Address used in a default or a field initializer | `A compound literal in a parameter default or field initializer is a value; its address cannot be used` |
| Array object initialized from an array literal | `An array cannot be initialized from a compound literal; write the brace list directly` |
| `@gpu` | `@gpu function 'k': compound literal has no WGSL lowering` |
| Incomplete type; caller-owned temporaries | existing incomplete-record and shallow-aggregate diagnostics |

**Flexible array members (r13)**

| Case | Diagnostic |
|------|------------|
| `T[] name` in a struct, at the name | `Struct field 'data' cannot use the 'T[] name' spelling; declare a flexible array member as 'T data[]' or a pointer as 'T* data'` |
| Not last (`r13-flexible-array-not-last`, at 1:21) | `Flexible array member 'Buffer.data' must be the last field of struct 'Buffer'` |
| No named member before it | `Flexible array member 'Buffer.data' needs a named field before it` |
| Inside an anonymous member | `Flexible array member 'data' must be declared directly in a struct, not in an anonymous member` |
| Managed element | `Flexible array member 'Buffer.items' cannot hold managed type 'string'` |
| By-value use, reported where today's `uses incomplete struct` is reported | `{subject} uses struct 'Buffer' with a flexible array member by value; use a pointer` (the subject as today: `Variable 'b'`, `Parameter 'f.b'`, `Return type of 'f'`, `Struct field 'Outer.inner'`, `Field 'Box.b'`, `Rich-enum payload 'E.V.p'`, `Generic argument 1 of ...`) |
| Copy or assignment | `Struct 'Buffer' with a flexible array member cannot be assigned or copied` |
| `sizeof` of the member | `sizeof cannot be applied to flexible array member 'Buffer.data'` |
| Address of the member | `Cannot take the address of flexible array member 'Buffer.data'; use the member itself or an element's address` |
| Unsized typedef declarator | `Typedef 'V' cannot declare an array of unknown size; write 'typedef int[] V' for a btrc array alias or give the extent` |
| Reused | `Array object 'int[]' is not assignable`; `Array for-in iterable has no provable element capacity`; `new requires a class type, got 'Buffer'` (the reference compiler adopts btrcc's message); for `Thread<FamStruct>`, `Thread<T> result type cannot contain an unsized array; ...` fires first |

**Bit-fields (r12)**

| Case | Diagnostic |
|------|------------|
| Type | `Bit-field 'S.f' must have type bool, int, signed int or unsigned int; 'unsigned char' bit-fields are not portable C11` |
| Non-constant width | `Bit-field width for 'S.f' must be an integer constant expression` |
| Constant btrc cannot evaluate | `Bit-field width for 'S.f' is a constant expression btrc cannot evaluate; write its integer value` |
| Negative width | `Bit-field width for 'S.f' must not be negative` |
| Too wide | `Bit-field width 33 for 'S.f' exceeds the 32 bits of 'unsigned int'` (for `bool`: `exceeds the 1 bit of 'bool'`) |
| Named member with width 0 | `Bit-field 'S.f' has zero width; only an unnamed bit-field may have width 0` |
| Array | `Bit-field 'S.f' cannot be an array` |
| Only unnamed bit-fields | `Struct 'S' has no named members under strict C11` (or `Union 'U'`) |
| In a class | `Bit-field 'C.f' is only allowed in a struct or union; class fields cannot declare a width` |
| Address (`r12-bitfield-address`) | `Cannot take the address of bit-field 'S.f'` |
| `sizeof` | `sizeof cannot be applied to bit-field 'S.f'` |
| Constant that does not fit | `Value 9 does not fit in bit-field 'S.f' (unsigned int : 3 holds 0 to 7)` |
| Reserved for Stage 19 | `_Alignas cannot apply to bit-field 'S.f'` |
| Unchanged | `@gpu`: the existing type refusal; native records: `anonymous fields and bitfields require native-type lowering`; locals, globals, parameters: the parse error `Expected SEMICOLON, got COLON ':'` |

**Multi-dimensional arrays (r17, Stage 18)**

| Case | Diagnostic |
|------|------------|
| Empty inner extent, at its `[` (`r17-unsized-inner-dimension`, at 2:12) | `Only the outermost array extent may be omitted` |
| `T[][]` or `T[] x[3]` | `A btrc T[] array type has one dimension; write the extents after the name, as in int grid[2][3]` |
| Inner extent not constant, including inner VLAs | `Inner array bound for Variable 'g' must be a constant expression` |
| Inner constant btrc cannot evaluate | `Inner array bound for Variable 'g' is a constant expression btrc cannot evaluate; write its integer value` |
| Per-extent rules | existing `Array bound for ... must be integral` and `... must be positive` |
| Managed elements | `Variable 'g' cannot hold managed elements ('string') in a multi-dimensional array; use a collection` |
| Nullable elements | `Variable 'g' cannot combine '?' with a multi-dimensional array` |
| Unbraced rows | `Initializer for Variable 'g' must brace each row of a multi-dimensional array` |
| Too many rows | `Variable 'g' has 3 rows but fixed array bound is 2` |
| Decay to a pointer to rows | `'int[2][3]' decays to 'int (*)[3]', a pointer-to-array type btrc does not accept; index it or pass it to an array parameter` |
| Argument extents | `Argument 1 of type 'int[2][4]' does not match parameter 'm' of type 'int[][3]'` |
| `sizeof` of an array parameter | `sizeof cannot measure array parameter 'm'; C adjusts it to a pointer to its rows` |
| `@gpu` | `@gpu buffers are one-dimensional; flatten 'g' into int[] and index it as row * columns + column` |
| for-in over rows | `for-in cannot iterate the rows of multi-dimensional array 'g'; index the rows with a C for loop` |
| parallel `for` over rows | `parallel for cannot iterate the rows of multi-dimensional array 'g'` |
| Generic argument | `Generic argument cannot be a multi-dimensional array` |
| `Span` | `Span<T> requires a one-dimensional array` |
| Unsized typedef as an element | `Array element type 'Row' has no extent` (replaces `Nested array composition through typedef is not supported` for sized typedefs) |
| Deleted | `Multi-dimensional arrays require an AST/IR representation...` and `Expected one array dimension...` |

### Schema commit (`ccompat-c2-schema`)

**ASDL.** The comments do not reach the generated files.

```asdl
    decl = ...
         -- `union U { ... };` and `union U;` share StructDecl; is_union
         -- selects the C keyword, the plain-member rule and first-member
         -- brace initialization.
         | StructDecl(identifier name, field_def* fields, bool is_forward,
                      bool is_union, int name_line, int name_col)

    -- array_size is the outermost extent; elements are the inner extents,
    -- outermost first (int g[2][3][4]: array_size=2, elements=[3, 4]); only
    -- array_size may be absent. pointer_depth pointers sit inside the arrays
    -- (int *p[2] holds int*); array_pointer_depth counts the pointers applied
    -- outside them (int (*p)[3]). btrc's prefix T[] never has elements.
    type_expr = TypeExpr(identifier base, type_expr* generic_args,
                         int pointer_depth, bool is_array,
                         expr? array_size, expr* elements, bool is_const,
                         bool is_nullable, int nullable_outer_depth,
                         bool is_static,
                         bool is_extern, bool is_volatile,
                         int array_pointer_depth)
                attributes(int line, int col)

    -- value is a bit-field width (C11 6.7.2.1), null for an ordinary member;
    -- an unnamed bit-field has name "" and sits at its type. A flexible
    -- array member is a struct's last FieldDef whose own type is an unsized
    -- array. AnonymousMember is a C11 anonymous struct or union member; its
    -- fields belong to the enclosing record.
    field_def = FieldDef(type_expr type, identifier name, expr? value)
              | AnonymousMember(bool is_union, field_def* fields)
              attributes(int line, int col)

    expr = ...
         -- entries is null until an element is designated, then holds one
         -- Designation per element (empty parts for a positional element);
         -- elements always hold the values.
         | BraceInitializer(expr* elements, designation* entries)
         ...
         | CommaExpr(expr* elements)
         -- (T){...} (C11 6.5.2.5): an lvalue of type T whose initializer is
         -- always a BraceInitializer.
         | CompoundLiteral(type_expr target_type, expr initializer)
         attributes(int line, int col)

    -- after capture:
    designation = Designation(designator* parts)
    designator  = FieldDesignator(identifier field)
                | IndexDesignator(expr index)
                attributes(int line, int col)
```

**Where each new field lives in the btrc `Node`:**

| Field | btrc `Node` storage | Note |
|-------|---------------------|------|
| `StructDecl.is_union`, `AnonymousMember.is_union` | new `isUnion` (bool) | first appears right after `isForward`, in the 7 padding bytes before `valuesStorage` |
| `TypeExpr.array_pointer_depth` | new `arrayPointerDepth` (int) | after `isVolatile`, in the padding before `type` |
| `TypeExpr.elements` | `elementsStorage` (lazy) | moves next to `arraySize`; `sizeof(Node)` is unchanged |
| `AnonymousMember.fields` | `fieldsStorage` (lazy) | |
| `FieldDef.value` | `valueNode` | |
| `BraceInitializer.entries` | `entriesStorage` (lazy) | |
| `Designation.parts` | `partsStorage` (lazy) | |
| `FieldDesignator.field` | `field` | |
| `IndexDesignator.index` | `index` | |
| `CompoundLiteral.target_type`, `.initializer` | `targetType`, `initializer` | |

**New kinds** (five):
- `NK_ANONYMOUS_MEMBER`, after `NK_FIELD_DEF`;
- `NK_COMPOUND_LITERAL`, after `NK_COMMA_EXPR`;
- `NK_DESIGNATION`, `NK_FIELD_DESIGNATOR` and `NK_INDEX_DESIGNATOR`, after `NK_CAPTURE`.

Kinds render by name. Renumbering reaches only the module-unit validation records, and the toolchain fingerprint invalidates those because it includes `ast.asdl`.

**Python dataclasses** gain:
- `StructDecl.is_union` (`False`);
- `TypeExpr.elements` (a list) and `TypeExpr.array_pointer_depth` (`0`);
- `FieldDef.value` (`None`);
- `BraceInitializer.entries` (a list);
- `AnonymousMember`, `CompoundLiteral`, `Designation`, `FieldDesignator` and `IndexDesignator`.

**Renderers.** The btrc `AstCanonicalRenderer` adds a line for each new field and a branch for each new kind, and `AstStructure.children` moves its `elementsStorage` line. The Python renderer and `AstJsonCodec` are generic.

**Grammar** (`src/language/grammar.ebnf`):
- `struct_decl = record_keyword [ IDENT ] "{" { struct_member } "}" ";" | record_keyword IDENT ";"`, with `record_keyword = "struct" | "union"`. Delete the reserved-word note that `union` is only a base_type.
- `struct_member = type_expr struct_declarator { "," struct_declarator } ";" | record_keyword "{" { struct_member } "}" ";" | type_expr ":" expr ";"`.
- `struct_declarator = IDENT [ array_declarator ] [ ":" expr ]`; r03 owns the declarator list.
- `array_declarator = "[" [ expr ] "]" { "[" expr "]" }`, used by parameter, struct member, class field, variable and typedef declarators.
- `typedef_decl = "typedef" ( type_expr | record_keyword [ IDENT ] "{" { struct_member } "}" | "enum" [ IDENT ] "{" enum_values "}" ) declarator { "," declarator } ";"`.
- `type_name = type_expr [ array_declarator ]`.
- `compound_literal = "(" type_name ")" brace_initializer` in the postfix rule, with the for-in head exception.
- `initializer_item = [ designation "=" ] initializer`, `designation = designator { designator }` and `designator = "." IDENT | "[" expr "]"`.
- Comments: the `type_expr` comment says `T[]` stays one-dimensional. The `base_type` comment says `struct X`, `union X` and `enum X` name the btrc declaration X when one exists.

**IR, in both compilers:**

| Python `ir/nodes.py` | btrc `ir/Model.btrc` | Meaning |
|----------------------|----------------------|---------|
| `IRStructDef.is_union: bool = False` | `IRStructDef.isUnion` | `union U { ... };` |
| `IRStructForward.is_union: bool = False` | `IRStructForward.isUnion` | `typedef union U U;` |
| `IRStructField.record`, an `IRStructDef` or `None` | `IRStructField.record` (`IRStructDef?`) | anonymous member, emitted inline |
| `IRStructField.is_unsized_array: bool = False` | `IRStructField.isUnsizedArray` | FAM, `T name[];` |
| `IRStructField.bit_width`, an `int` or `None` | `IRStructField.bitWidth` (int, -1 when absent) | folded width, `T name : w;` or `T : w;` |
| `IRFieldAccess.bit_field: bool = False` | `IRNode.bitField`, in the scalar tail | a bit-field access |
| `IRDesignation(IRExpr)` with `field: str = ""`, `index: IRExpr = None`, `value: IRExpr = None` | `IRK_DESIGNATION` in the expression group after `IRK_COMPOUND_LITERAL` (`Optimizer.btrc` treats `kind >= IRK_VAR_DECL` as a statement), built by `IRNode.designation(...)` reusing `field`, `index` and `value` | `.f = v` or `[k] = v` |
| `IRCompoundLiteral` entries named `""` are positional | `fieldNames` entries `""` | array and scalar literals |

The bit width is an integer because a C bit-field width is never a run-time value. Stage 18's `IRTypedefDef.array_size` stays an `IRExpr`, because C allows a variably modified typedef at block scope.

**Shape invariant.** Python `IRVerifier` checks these rules; in btrc, `CEmitter.structFieldDeclaration` and `emitStruct` raise internal errors for violations.
- At most one of `array_size`, `is_unsized_array`, `bit_width` and `record` is set on an `IRStructField`.
- `name == ""` only together with `bit_width` or `record`.
- `record` is set exactly when `c_type` is the keyword `struct` or `union`, and the keyword matches `record.is_union`. `record.name` is empty and its fields are non-empty. An untagged `IRStructDef` appears nowhere else.
- `is_unsized_array` appears only on the last field of a non-union `IRStructDef` that has a named field before it.
- `bit_width` appears only on `IRStructDef` fields whose C type is an int or bool type.
- Neither appears in `IRTaggedUnionVariant`, in GPU structs, or in `IRObjectiveCClass`, whose "Objective-C adapter array fields require a fixed native layout" refusal is extended to cover them.
- `IRDesignation`: exactly one of `field` and `index` is set; `index` is an `IRLiteral`; `value` is non-null. It is legal only as an `IRInitializerList` element or as a positional `IRCompoundLiteral` entry's value.
- After optimization, no `IRAddressOf`, array decay or out-parameter adapter is rooted at an `IRFieldAccess` with `bit_field`.

**Walkers.**
- Python's type-order planner already finds nested `CType`s through `IRNode.walk_value`.
- btrc's `IROptimizer` struct ordering and `ModuleUnitDeclarations.collectField` must recurse into `record`.
- The Python `ExceptionLowerer` setjmp walkers must descend into `IRDesignation`. btrc's `ir/optimization/setjmp/Analysis.btrc` does so through its generic fallback, which visits every `IRNode` field.

The parsers produce none of the new syntax in this commit. The gate is:
- the generated-source check;
- the two AST boundary re-captures;
- AST and parser parity;
- the corpus through both compilers;
- the bootstrap fixed point;
- zero analyzer warnings on the self-host transpile;
- the memory measurement below.

### Consumers to update

Each lane changes Python first and then ports to btrc in the same commit. The lists name the owners; the kind-coverage and record-member contract tests catch anything they miss.

**r09 unions and C tags**
- **Python:**
  - Parser: `Parser._parse_top_level_item`; `Parser._parse_struct_decl` (record keyword; P1 and R8 in union bodies).
  - Analyzer: `TopLevelRegistrar.register_struct` and `claim_name` (kind `union`); `TypeSystem` (alias rows through `canonical_type`, `_is_known_declaration_type`, `is_realtime_pod`, `contains_realtime_function_storage`, `_aggregate_field_types`, the Atomic field-role check, the wrong-keyword validator); `AggregateAnalyzer` (member rule and complete-use checks); `InitializerAnalyzer.plan_aggregate` (first member).
  - Every `removeprefix("struct ")` reader canonicalizes first: analyzer `aggregates`, `types`, `expressions`, `storage`, `macros`, `ownership`; lowering `collections`, `calls`, `storage`, `ownership`.
  - Frontend: `ImportReferenceCollector` (tag references); `NativeDeclarationImporter._record` (`is_union`, tag alias).
  - Lowering and emission: `TranslationUnitLowerer._emit_forward_decls`; `ClassLowerer.emit_struct_decl`; `CollectionLowerer.plan_brace`; the Objective-C rebuild sites in `ir/lowering/functions.py`; `IRVerifier`; `CEmitter._emit_struct` and `_emit_struct_forward`.
- **btrc:**
  - Parser: `Parser.parseTopLevelItem`, `parseStructDecl`.
  - Analyzer: `DeclarationRegistry` (alias rows); `SemanticTypeSystem.resolveAliases` and `structFieldFor`; `NameValidator` (message unification, claim kinds); `DeclarationValidator.orderedStructDefinitions` and the member rule; `TypeValidator.validateDeclaredType`, `explicitCTag`, `knownDeclarationType`; `StorageValidator.structTypeName`, `arrayTargetMember`, `structContainsConst`; the tag readers in `OwnershipValidator`, `realtimePodInner` and `ExpressionTypeResolver`; `ExpressionValidator.validateStructInitializer`.
  - Frontend: `FeImportReferenceCollector`; `FeNativeDeclarationImporter.record`.
  - Lowering and emission: `DeclarationLowerer.emitStructDecl`, its forward loop, `emitStructDefinitions`, `objectiveCUnit` and `objectiveCValue`; `ExpressionLowerer.lowerBraceInitPlain`; `AggregateValueLowerer`; `CEmitter.emitStructForward` and `emitStruct`.
- **Tests, LSP and docs:**
  - LSP: `symbols.py` (a union is a Struct symbol).
  - Probes and corpus: `c2.toml` r09 and x-typedef-union rows; `c_compat/UnionDeclaration.btrc`; `c_compat/UnionLayout.btrc`.
  - A probe requires a native opaque union used as `union T*` and as `T*` to be one type.
  - `test_c_compatibility_refusals.py` covers struct message parity.

**r08 typedef records and anonymous members**
- **Python:**
  - Parser: `Parser._parse_typedef_decl`; `_parse_top_level_item` (r03 splice); the `_parse_struct_decl` member loop.
  - Analyzer: `DeclarationRegistry` (records and enums first; identity typedefs); `AggregateAnalyzer._validate_typedef_cycles`.
  - Record-member owner users: flattened duplicates in `register_struct`, `validate_struct_field_access`, `_collect_aggregate_dependencies`, `ExpressionAnalyzer` field typing, `OwnershipAnalyzer`, `RealtimeAnalyzer`.
  - Lowering and emission: `TranslationUnitLowerer._emit_declarations` (identity) and `_declaration_types`; `ClassLowerer.emit_struct_decl` (`record`); `CEmitter._emit_struct` (inline body).
- **btrc:**
  - Parser: `Parser.parseTypedefDecl`, `parseTopLevelItem`, `parseStructField`.
  - Analyzer: `DeclarationRegistry` (no `typedefTable` entry for an identity typedef); `NameValidator` (claims, flattened uniqueness); `TypeValidator` typedef checks; `DeclarationValidator.orderedStructDefinitions` (dependencies inside anonymous members); `SemanticTypeSystem.structFieldFor` (flattened).
  - Lowering and emission: `CTypeLowerer.appendTypedefs` (identity); `DeclarationLowerer.emitStructDecl`; `CEmitter.structFieldDeclaration`; `IROptimizer` struct ordering; `ModuleUnitDeclarations.collectField`.
- **Tests, LSP and docs:**
  - LSP: `symbols.py` (recurses into anonymous members; no duplicate symbol for an identity typedef); `navigation.py` (flattened members).
  - Tests and probes: `test_structured_ir_contract.py`; `c2.toml` r08 and x-typedef rows.
  - Corpus: `c_compat/TypedefRecords.btrc`, `AnonymousMembers.btrc`, `AnonymousMemberLayout.btrc`.
  - The untagged named-member refusal is documented in known-language-gaps.

**r10 designated initializers and compound literals**
- **Python:**
  - Parser: `Parser._parse_map_or_brace_initializer` plus a new `_parse_designation`; `_parse_primary` plus a new `_is_compound_literal`; the iterable rule in `_parse_for_stmt` and `_parse_parallel_for_stmt`.
  - Analyzer: `InitializerAnalyzer` (designators, overrides, extents); `AggregateAnalyzer.validate_fixed_array_initializer`; `StatementAnalyzer._is_static_storage_initializer`, `_static_initializer_category`, `_inferred_array_binding_type`; `ExpressionAnalyzer` (literal type, `_is_addressable_storage`, `_validate_address_operand`, the return escape, the `try` rule); `AnalyzedProgram` side tables; compound-literal arms in `ownership.py`; `_EXPRESSION_LABELS` in `analyzer/gpu.py`.
  - Lowering and emission: `CollectionLowerer.plan_brace` and the static plans; `ExpressionLowerer` (compound literal, `&` inside the boundary); global extents in `TranslationUnitLowerer` and `ClassLowerer`; `OwnershipLowerer.owns_result`; `ExceptionLowerer` children; `IRDesignation` in `IRVerifier` and `CEmitter`.
- **btrc:**
  - Parser: `Parser.parseMapOrBraceInitializer` plus `parseDesignation`; `parsePrimary` plus `isCompoundLiteral` (beside `isCast` and `isCastFollow`); `parseForStmt`.
  - Analyzer: `ExpressionValidator.validateInitializerValue`, `validateStructInitializer`, `validateInitializerElements`; `StorageValidator` (bounds, static initializers, addressability); `ConstantValidator`; `Analyzed` side tables; `ExpressionTypeResolver`; the `GpuKernelValidator` label; `RealtimeAnalyzer`; compound-literal arms in validation `{Ownership, Borrows, Calls, ControlFlow, Declarations, Types}`.
  - Lowering: `ExpressionLowerer.lowerBraceInit`, `lowerBraceInitPlain`, `lowerFixedArrayInitializer` and a new `lowerCompoundLiteral`; `AggregateValueLowerer.collectOperands` and `contextualElementType`; `DeclarationLowerer.emitGlobalVar`.
  - Kind coverage (lower or fail closed): `valueRequiresEnvironment`, `unsafePersistentValue` and the other walkers in `ir/lowering/{Statements, Callables, CallableFlow, Concurrency, ownership/Operands, ownership/Semantics}`; `ir/gpu/{Pipeline, Wgsl}`.
  - Emission: `CEmitter` (`IRK_DESIGNATION`, `""` field names); setjmp `Analysis.btrc`.
- **Tests and docs:**
  - Probes: the `c2.toml` r10 rows; `KNOWN_DIVERGENCES` drops `r10-designated-index-initializer`.
  - Corpus: `c_compat/DesignatedInitializers.btrc`, `CompoundLiterals.btrc`.
  - `test_aggregate_evaluation_order_parity.py` gains out-of-order designators.
  - New negative probes: a capturing lambda through a designator and through a compound literal; `for x in (items) {` parse parity; field-initializer and default-argument addresses; `try`; escapes; VLA, managed and non-constant file-scope literals.

**r13 flexible array members**
- **Python:**
  - Parser: `Parser._parse_struct_decl` (P1).
  - Analyzer: `AggregateAnalyzer.array_field_value_type`, `is_pointer_backed_array_target`, `array_target_has_capacity`, `validate_complete_aggregate_use` (R4), `validate_sizeof_operand` (R6) and `_collect_aggregate_dependencies`; `InitializerTypeLayout.array_field_value` (a `FieldDef` has no `access`); `TypeSystem.validate_declared_type` (R3, and R4 for generic and payload roles); `ExpressionAnalyzer._validate_assignment` (R5), `&` (R7) and `NewExpr`; `StatementAnalyzer` declaration checks (the `extern` and `var` paths); `StorageModel.projection_embeds_storage`.
  - Lowering and emission: `ClassLowerer.emit_struct_decl`; `IRObjectiveCClass.validate`; `CEmitter._emit_struct`.
- **btrc:**
  - Parser: `Parser.parseStructField` (P1).
  - Analyzer: `StorageValidator.arrayFieldValueType`, `pointerBackedArrayTarget`, `arrayTargetHasCapacity` and the projection owners. The FAM predicate is a class method, because `test_array_projection_storage_owner_contract.py` pins StorageValidator's private state. Also `DeclarationValidator.visitStructDefinition` and `validateStructLayouts`; `TypeValidator.validateDeclaredType`, `validateAggregateDeclarationTypes` and `threadResultHasUnsizedArray`; `ExpressionValidator` (sizeof, assignment, `&`, `validateNew`).
  - Lowering and emission: `DeclarationLowerer.emitStructDecl`; `CEmitter.structFieldDeclaration` and its Objective-C field branch.
- **Tests and docs:**
  - Probes: both `c2.toml` r13 rows (the not-last case rejected at 1:21); `KNOWN_DIVERGENCES` drops both.
  - Corpus: `c_compat/FlexibleArrayMembers.btrc`; `c_compat/FlexibleArrayLayout.btrc` with `c_compat/layout/flexible_array_layout.c`.
  - New tests: `test_flexible_array_member_contract.py`; `test_c_aggregate_layout.py`, which requires identical emitted declarations from both compilers and checks that raw IR carries `is_unsized_array`.
  - Updated tests: `test_generic_array_assignment_contract.py` (use `typedef int[] Values`), `test_thread_ownership_contract.py`, `test_parser_decls.py::test_struct_with_array_fields`, `test_structured_ir_contract.py`.
  - known-language-gaps: the refusal rows and the allocation pattern.
  - Before landing, grep BTRSmith for struct fields spelled `T[] name`.

**Enum tags**
- **Python:**
  - Analyzer: `EnumRegistrar.register_simple` (alias); per-file evidence from the source dependency graph and quoted `#include`s; `TypeSystem.validate_declared_type`, `validate_cast_target_name` and `_is_known_declaration_type` (an `enum ` prefix alone no longer makes a type known); `AggregateAnalyzer.validate_sizeof_operand`.
  - Frontend: `NativeDeclarationImporter._enum` (alias).
  - Emission: `CEmitter._emit_enum_def`.
- **btrc:**
  - Analyzer: `DeclarationRegistry` (alias, evidence); `TypeValidator.validateDeclaredType`, `knownDeclarationType` and `explicitCTag`; `ExpressionValidator` cast and sizeof operands. Audit `isEnum(base)` callers that read non-canonical bases: `Operators.btrc`, `Realtime.btrc`, `validation/Constants.btrc`, `ir/lowering/Strings.btrc`.
  - Frontend: native enum registration in `NativeImports.btrc`.
  - Emission: `CEmitter.emitEnum`.
- **Tests and docs:**
  - Probes: the `c2.toml` x-enum-tag rows (the unknown tag rejected at 2:2); `KNOWN_DIVERGENCES` drops both.
  - Corpus: `c_compat/EnumTagSpelling.btrc`, covering parameters, returns, pointers, arrays, casts, `sizeof`, `switch`, print, `toString`, `typedef enum Color Shade`, a struct field and a generic argument.
  - New test: `test_enum_tag_contract.py`, covering the tag template, the evidence rule, strict imports, the emitted `typedef enum Color {` and a macOS-shaped native-tag collision.
  - `basics/InteropCEnumBaseType.btrc` stays as is.

**r12 bit-fields**
- **Python:**
  - Parser: `Parser._parse_struct_decl` (named and unnamed widths); `_parse_class_member` (the targeted refusal).
  - Analyzer: `TopLevelRegistrar.register_struct` (skip `""`; require a named member); a new `AggregateAnalyzer.validate_bit_field`; `validate_struct_field_access` and `validate_sizeof_operand`; `InitializerAnalyzer.plan_aggregate` (constants must fit); `ExpressionAnalyzer` (read type, `_validate_address_operand`, `_is_addressable_storage`, store fit).
  - Lowering: `ClassLowerer.emit_struct_decl` (`bit_width`); `ExpressionLowerer` field access (`bit_field`) and fail-closed `&`; `StorageLowerer.materialize_target` and `prepare_update`; `OwnershipLowerer.assignment_target_operands` and `_receiver_operands` (the containing object); out-parameter adapters in `functions.py` and `calls.py` fail closed; `exceptions.py` (volatility on the containing automatic).
  - Verification and emission: `IRVerifier`; `CEmitter._emit_struct`.
- **btrc:**
  - Parser: `Parser.parseStructField` and the class-member refusal.
  - Analyzer: `TypeValidator.validateAggregateDeclarationTypes`; `ConstantValidator.integerConstant`; `NameValidator` (skip unnamed members); `ExpressionValidator.validateUnary`, its sizeof branch, initializer fit; `StorageValidator.isAddressableStorage` and static initializers; `ExpressionTypeResolver.inferTypeRaw` (read type); `SemanticTypeSystem.structFieldFor`.
  - Lowering: `DeclarationLowerer.emitStructDecl` (`bitWidth`); `ExpressionLowerer.lowerDirectStore`, `lowerDirectCompound`, `directLvaluePointerType`, `lowerIndirectIncDec`, `staticInitializerFieldCount`; setjmp `Analysis.btrc` and `Safety.btrc`.
  - Emission: `CEmitter.structFieldDeclaration` and the no-address assertion.
- **Tests and docs:**
  - Probes and corpus: the `c2.toml` r12 rows; `c_compat/BitFields.btrc`; `c_compat/BitfieldLayout.btrc` (`sizeof` only).
  - New test: `test_bitfield_lvalue_contract.py`, covering `=`, `op=`, prefix and postfix `++`/`--` through `.` and `->`, `arr[i++].f`, `call()->f`, try/catch, lambdas and generic bodies, in both compilers, under gcc and clang `-pedantic-errors`.
  - LSP: `symbols.py` (skip unnamed members; detail `unsigned int : 3`); `resolution.py` hover.

**r17 multi-dimensional arrays (Stage 18)**
- **Python:**
  - Parser: `Parser._parse_declarator_array_suffix`, `_parse_type_expr`.
  - Types: `TypeIdentity` (`shape_key`, `_encode_type`, `substitute`, `is_c_string_pointer`); `TypeSystem` (rank helper, `compose_type_expr`, `strip_outer_storage`, `add_outer_pointer` (which must never build a pointer to an array), `types_compatible`, qualifier depths, `validate_declared_type`, `format_type`, the thread and realtime strips).
  - Analyzer: `StatementAnalyzer._validate_array_bound` and `_analyze_for_in`; `AggregateAnalyzer.array_parameter_value_type` and `validate_fixed_array_initializer`; `ExpressionAnalyzer` (index, `&` and `*`, casts, spawn captures); `CallAnalyzer` argument extents; `analyzer/gpu.py`; `GenericAnalyzer`; `AnalyzedProgram` extent values.
  - Frontend: `ImportReferenceCollector.visit`. Its `TypeExpr` branch visits only `generic_args` and `array_size`, so it must also visit `elements`.
  - Lowering: `CTypeLowerer` (`ArrayTypedefRegistry`, `render`); `StorageLowerer.plan_declaration`; `ClassLowerer`; `TranslationUnitLowerer`; `IterationLowerer`; `ExpressionLowerer._lower_sizeof`; `exceptions.py`; `GpuLowerer`.
  - Optimizer, emission and units: `IROptimizer.plan_type_declarations`; `CEmitter._emit_typedef`; `IRTypedefDef`; `ModuleUnitCompiler` typedef dependencies.
- **btrc:**
  - Parser: `Parser.parseDeclaratorArraySuffix`, `parseType`.
  - Syntax: `AstStructure.children`, `AstCanonicalRenderer`, `TypeIdentity`; `TypeShape` copies and `withoutOuterArray`; `TypeComposition.compose`.
  - Analyzer: `SemanticTypeSystem.resolveGenericType`, `composeTypedefType` and `indexResultType`; `StorageValidator.validateArrayBound`, `arrayParameterValueType` and `validateVariableStorage`; `TypeValidator`; `ExpressionValidator`; validation `Calls.btrc` and `Constants.btrc`; `ExpressionTypeResolver`; `OperatorSemantics`; `GpuKernelValidator`; the `Generics.btrc` closure walk.
  - Frontend: `Visibility.btrc`, whose `TypeExpr` branch must visit `elements`.
  - Lowering: the `CTypeLowerer` registry; `DeclarationLowerer`; `StatementLowerer`; `ExpressionLowerer`; `AggregateValueLowerer`.
  - Units and optimizer: `ModuleUnitDeclarations`; `ir/runtime/References.btrc`; `IROptimizer`; setjmp `Safety.btrc` and `Analysis.btrc`; `ir/gpu/Pipeline.btrc`.
  - Emission: `CEmitter.emitTypedef`, `emitOrderedAliases` and the module emission order.
- **Tests and docs:**
  - Probes and corpus: the `c2.toml` r17 rows; `c_compat/TwoDimensionalArrays.btrc`.
  - Inverted tests: `test_parser_decls.py::test_multidimensional_array_has_architecture_error` and the one-dimension case in `test_parser_diagnostics.py`.
  - Other tests: `test_ast_structure_contract.py`; a `--module-units` regression for a rank-2 parameter; the strict C11 const-row case.
  - LSP: `resolution.py` (`[2][3]`), `navigation.py`.
  - Docs: replace the known-language-gaps "Intentional syntax limits" paragraph and extend the VLA table.

### Memory impact

- **btrc `Node`: 0 bytes.**
  - `isUnion` takes a padding byte after `isForward`.
  - `arrayPointerDepth` fills the padding after `isVolatile`, before `type`.
  - `elementsStorage` moves next to `arraySize` without changing `sizeof(Node)`.
  - Every other new field reuses existing storage.
  - `Node()` gains two stores, `isUnion = false` and `arrayPointerDepth = 0`, and there are five new kinds.
  - The measurement checks `sizeof(Node)` in the generated C.
- **Why reuse matters.** Stage 15 removed one 8-byte pointer (`varDecl`) and measured −9,564 KiB (−0.35%) of peak RSS on the BtrccMain self-compile. One new `Node` pointer therefore costs about the whole ≤0.3% gate. That rules out `designators`, `bit_width`, `array_dims` and `record` fields on `Node`; `bit_width` and `array_dims` together would cost about +0.7%.
- **btrc `IRNode`: 0 bytes.**
  - `bitField` joins the scalar tail, which today is `kind`, 15 bools, `sourceLine` and `realtimeBounded`: 25 bytes padded to 32.
  - `IRK_DESIGNATION` reuses `field`, `index` and `value`.
  - Positional entries reuse `fieldNames` and `args`.
- **Small IR classes.**
  - `IRStructField` gains a pointer, a bool and an int, for struct members only.
  - `IRStructDef` and `IRStructForward` each gain a bool.
  - In Stage 18, `IRTypedefDef` gains a pointer.
- **Analysis data.**
  - Alias rows: one entry and one `TypeExpr` per btrc record and plain enum, a few hundred across the compiler and the stdlib.
  - One initializer plan per brace initializer.
  - Extent and width values.

  Each is well under 1 MB.
- **Python.**
  - Every new `TypeExpr` carries one more empty list (`elements`) and an int.
  - Every `BraceInitializer` carries an empty `entries` list.
  - `StructDecl` gains a bool and `FieldDef` gains an attribute.

  These are measured against D13's 2 GiB peak on the same BtrccMain compile.
- **What the self-compile exercises.** btrc's own source contains no union, anonymous member, designator, compound literal, FAM, bit-field or rank≥2 array. The self-compile therefore pays only the two constructor stores and the alias rows, and the delta is expected to be within noise.
- **Evidence.** Stage 15's method, run at the schema commit and again at `ccompat-c2-integrate`:
  1. Build btrcc from the parent and from the commit, recording which C compiler built each.
  2. Run three alternating `--target linux-x86_64 --no-cache` compiles of `src/compiler/btrc/BtrccMain.btrc` with each, measuring peak RSS and user CPU through `wait4`.
  3. On the Mac, record the BTRSmith `--jobs 1` row under `/usr/bin/time -l` (instructions retired, peak memory footprint).

  ≤0.3% passes. Up to 1% is accepted with the delta recorded, per the standing approvals.

### Boundary records

The manifest holds 310 records (`test_boundary_manifest.py`). Exactly two change, once, in the schema commit:

- `surface.python.ast.artifact` and `surface.btrc.ast.artifact`, both currently `f85c8dd1…`. Each `TypeExpr` in the surface source (the `int` return types of `dead` and `main`) gains two lines: `elements=[]` after `array_size=nil`, and `array_pointer_depth=0` after `is_volatile=false`.
- Re-capture both with one reason: "TypeExpr carries inner array extents and outer pointers for C2/r17".
- Their regressions are `test_boundary_renderers.py`, `test_ast_structure_contract.py` and the AST parity tests.
- The two artifacts stay equal. The status records and the frozen baselines are untouched.

These are unchanged, checked against the inputs and artifacts:
- **AST.** No boundary source declares a struct, union, enum, typedef, brace initializer, designator, compound literal or array, so `StructDecl`, `FieldDef`, `BraceInitializer` and the new kinds never render.
- **IR.** The four Python raw and optimized IR artifacts have empty `struct_defs`, `struct_forwards`, `enum_defs` and `typedef_defs`. They contain no `IRFieldAccess`, `IRStructField`, `IRCompoundLiteral` or `IRInitializerList`, and `IRModule` gains no list.
- **Tokens.** No new token: `...` waits for Stage 19; designators use `.`, `[`, `]` and `=`; bit-fields use `:`.
- **C.** No record or enum is emitted, and rank-1 shape keys and symbols are unchanged. Stage 18's btrc emission-order commit changes nothing here either, because neither C fixture has a type definition.
- **Other records.** Diagnostics, gcc/clang behavior, and the runtime source, metadata and order records.

Outside the manifest:
- `c2.toml` entries flip as each lane lands, each with `revision` set to its parent commit.
- `KNOWN_DIVERGENCES` drops five entries (`r10-designated-index-initializer`, both r13 rows, both x-enum-tag rows), leaving the two Stage 19 rows.
- Canonical AST text and Python IR text pinned elsewhere gain the new fields.
- btrcc's own C changes with the enum tags (enum lane) and with the emission order (Stage 18), so each of those commits re-proves the bootstrap fixed point.

### Lanes and merge order

**Stage 17** (D5 gates per batch):

1. **Serial, main session, 2 reviewers:** `ccompat-c2-schema`, then the shared-owner commit.
2. **Two lanes**, because both touch `ir/lowering/Aggregates.btrc`, the type owners and record-body parsing. Each construct is one commit: Python first, then the btrc port by the same agent. Each lane builds its own btrcc under the semaphore.
   - **L1:**
     1. r09: unions; C tag aliases for records; the wrong-keyword validator; tag references in both import collectors; struct message unification; R8 and P1 in union bodies; native opaque `is_union`; the Objective-C assertions.
     2. r08: typedef records, identity typedefs, object declarators, anonymous members.
     3. r10: designators, compound literals, `type_name`, the for-in head rule.
   - **L2:**
     1. r13: FAMs; P1 in struct bodies; the layout harness and `test_c_aggregate_layout.py`.
     2. enum: enum aliases on r09's owner, the evidence rule, tagged emission, native enum tags, the collision refusal.
     3. r12: bit-fields, the `bit_field` verifier rule, stores through the containing object.
3. **Merge order:** r09, r08, r13, enum, r10, r12.
   - The enum lane rebases on r09's tag owner.
   - r12 rebases on r08 (an unnamed bit-field versus an `AnonymousMember`) and on r10 (designators skip unnamed bit-fields).
4. **Parity review:** one reviewer per construct (semantics, diagnostics, ARC witnesses), reusing the lane's btrcc. Strict C11 is checked by the gate.
5. **`ccompat-c2-integrate`:**
   - every approved C2 row is PASS;
   - `sizeof` and `offsetof` agree with gcc and clang through the layout harness;
   - the FAM divergence and the `{[2] = 7}` diagnostic are gone;
   - the bit-field no-address rule holds;
   - the memory delta is recorded;
   - BTRSmith is rerun.
6. **After the exit, as its own L2 commit:** lift native FAMs, meaning the last incomplete-array field of a native struct record. A test compares the reader's Clang `offset_bits` with offsets measured from the emitted C. Native union values, anonymous fields and bit-fields stay refused until separately qualified (ref:3191-3192).

**Stage 18** (serial first, then 2 lanes, 2 reviewers):

1. **btrc emission-order parity commit.** The btrc `CEmitter` today prints every alias and prototype before struct definitions. It changes to emit planned type declarations, then prototypes, as Python does. The commit gets its own bootstrap fixed point and a byte-diff review of btrcc's C. The Python planner treats an `IRTypedefDef` with `array_size` as a complete-type context.
2. **Representation and analyzer:** the parsers accept extents; rank helpers; extent values; decay, argument, `sizeof` and initializer rules; refusals; the `--module-units` rank-2 regression.
3. **Storage lowering:** `IRTypedefDef.array_size`; the row-typedef registry in both `CTypeLowerer`s; declarations; qualifier casts.
4. **In parallel:**
   - the GPU lane: analyzer refusals, `ir/gpu`, WGSL fail-closed;
   - the collections and iteration lane: for-in, `Span`, generics, `var`, lambda captures.
5. **Native fixed multi-dimensional scalar fields**, as their own commit with the same reader-layout cross-check.

Stage 18 exits when `c_compat/TwoDimensionalArrays.btrc` passes through both compilers under strict C11 and the pinned rejection tests are inverted.

### Review resolutions

| Finding | Resolution |
|---------|------------|
| A `DesignatedInitializer` wrapper in `BraceInitializer.elements` hides values from both compilers' ownership predicates, which return false for an unknown kind (blocking) | Accepted. Designators move to the parallel `entries` list of `Designation(parts)`; `elements` keep the values; 0 bytes. |
| The anonymous member as an overloaded `FieldDef` with base `struct` fails open in `_aggregate_field_types`, `_mutex_aggregate_fields`, `contains_realtime_function_storage` and btrc validators (blocking) | Accepted. `AnonymousMember(is_union, fields)` reuses `isUnion` and `fieldsStorage`; the plain-value rule, the record-member owner and its contract test go with it. |
| Anonymous structs may hold managed members, so about 58 field walks would each have to recurse | Accepted. Every anonymous member holds plain C values in Stage 17; relaxing later is compatible. |
| btrc pairs `elements[i]` with `fields[i]` in at least 9 places, which anonymous slots, designators and unnamed bit-fields all break | Accepted. The initializer-slot owner lands in the shared-owner commit, so both lanes branch from it, with a contract test against pairing elsewhere. |
| Two incompatible tag mechanisms (a helper versus typedef-table rows) | Resolved with alias rows in the existing alias index, one registrar, extended to native records and enums. A separate (keyword, name) table was rejected: canonicalization already threads the typedef index through about 50 static call sites per compiler, a second table would have to follow it everywhere, and generic identity does not resolve aliases, so the rows change no instance. |
| One unknown-tag rule for all three keywords | Rejected. C itself splits them: an incomplete struct or union is legal, an incomplete enum is not (C11 6.7.2.3p3). 112 by-value uses of system structs under `src/` come from `#include <…>` alone, so an evidence rule for `struct` would break them. |
| E3's per-file rule rarely fires because 1,100 of 1,203 test sources contain an `#include` | Accepted. Evidence is a `.c` import edge or a quoted `#include`; system includes do not count; native imports resolve their own tags. |
| r09's list of `removeprefix` sites is incomplete | Accepted. With alias rows, post-canonical sites are no-ops, and non-canonical readers canonicalize first. The tag-reference collectors were also missing (strict-import hole). |
| Opaque native unions import as plain `StructDecl`s, so the wrong-keyword check would misfire | Accepted. Both importers set `is_union` from `record_kind` in r09; a probe pins `union T*` and `T*` as one type. |
| A FAM in a union: each draft assigned the refusal to the other | Accepted. r09 owns R8 and P1 in union bodies from its first commit. |
| `(IDENT){` swallows the body in `for x in (items) {` | Accepted. In the for-in and parallel-for iterable, an expression-shaped head stays the iterable. A declared-type rule was rejected because per-file parsing cannot see imported types. |
| `TypeIdentity.encodable` accepts `int m[][3]` and module units replay it as `int[]` | Accepted. `encodable` also rejects non-empty `elements` and a non-zero `arrayPointerDepth`. |
| Copying `elements` through the shared-empty pattern breaks the memory gate | Accepted. Guarded copies only; the existing `copyWithArguments` misuse is recorded as a separate measured fix. |
| Designator and compound-literal walkers fail open | Accepted, for `CompoundLiteral` arms in every `BraceInitializer` site plus a contract test and capturing-lambda probes. Banning all `.elements` iteration was rejected: values stay in `elements`, so only slot pairing is banned. |
| Compound literals in parameter defaults and field initializers point at dead automatics | Accepted. They are value-only there. |
| Lifetime wording, `setjmp` and `goto` | p16 correction accepted (one object per execution of the enclosing block). Hidden-local lowering rejected: array literals, the common `f((int[]){1, 2, 3})`, cannot be assigned in C, and the qualifier-safety pass already refuses address aliases across `setjmp`. Address-using literals are refused in blocks that contain `try`. |
| `const` row pointers fail `-pedantic-errors` | Accepted. Explicit qualifier-adding casts, plus a strict C11 corpus case. |
| No abstract declarator for type names | Accepted. One `type_name` rule now, used by compound literals (r10), `sizeof` (Stage 18) and `_Alignof`/`_Static_assert` (Stage 19). |
| No slot for pointers outside arrays (x-pointer-to-array) | Accepted. `array_pointer_depth` is added now at 0 bytes, with one AST churn; the parsers refuse `(*p)[N]` until that row lands. |
| The "no `&` of a bit-field" proof rests on lowering-time checks; the drafter thought a marker would churn the IR boundary | Accepted. `IRFieldAccess.bit_field` plus a post-optimization rule. No boundary dump contains `IRFieldAccess`, and the btrc bool fits the scalar tail. |
| The override rule refuses valid nested anonymous structs | Accepted. Overlap is defined on designated paths: a prefix, or divergence at a union. |
| Four native-reader policies | Accepted. One rule: each lift is its own commit after its source row, with a Clang-layout cross-check. Everything else stays refused (ref:3191-3192). |
| Evaluator parity was scheduled after its first consumer, and valid-but-uncomputable constants were mislabeled | Accepted. Parity and the three-way query land in the shared-owner commit, with a distinct "cannot evaluate" diagnostic. |
| The range refusal breaks when Stage 19 adds `...` | Accepted (both token forms, pinned by a probe). Adding `...` now was rejected: Stage 19's serial vocabulary commit owns the lexical table. |
| `_Static_assert` members and `_Alignas` on bit-fields | Accepted. `field_def` is a sum that Stage 19 can extend, the record-member owner skips non-members, and the `_Alignas` message is reserved. |
| The whole-initializer rule made `int a[3] = (int[3]){…}` valid, against C11 6.7.9p16 | Accepted. The rule is limited to struct, union, tuple and scalar targets; the array form is refused. |
| Named members of an untagged type are a common header idiom | Rejected for Stage 17. Supporting them needs either a synthesized tag (which leaks into diagnostics, the LSP, generic identity and module-unit encodings) or a new member constructor plus a structural type identity in both identity owners. The refusal is documented, tested, and relaxable later; native records with such members stay refused by the reader. |
| Inner VLA extents are refused without a record | Accepted. A VLA-table row and tests; the block-scope variably modified typedef is the later path. |
| PascalCase SDK tags collide with tagged btrc enums | Accepted. A refusal at the enum when a native import registers the same tag, with a macOS-shaped probe. |
| r13 refuses C11-valid FAM forms without saying so | Accepted. Each is listed in "C that btrc rejects on purpose", with tests. |
| Struct messages already differ between the compilers | Accepted, with a correction: Python does refuse an empty body, in different words. btrc adopts Python's wording in r09 before union wording is derived. |
| r12's new `@gpu` message is unreachable | Accepted. Dropped; the existing type refusal is pinned. |
| Keeping the bit width as a source expression forces new reference collectors | Accepted, as a folded `int`: a width is never a run-time value, unlike the outer array extent that `IRTypedefDef.array_size` may carry. |
| Three lanes add independent `IRStructField` facets | Accepted. One shape invariant in the schema commit. |
| Generic identity of `Vector<enum Color>` | Neither proposal adopted. Draft normalization would be a third identity rule. Refusing tag spellings as generic arguments would break `OwnedBuffer<struct X>` in the stdlib. The written spelling stays the identity, as today. |
| btrc emits typedefs before struct definitions | Accepted. A separate parity commit opens Stage 18, with its own fixed point; the Python planner completes array typedef contexts. |
| The for-in row view needs a dereference rule at every use site | Accepted as a refusal: for-in and parallel `for` over rank≥2 arrays are refused. |
| The layout harness compares `long` with `size_t` | Accepted. Mirrors return `size_t`; pointer differences are cast explicitly. |
| Objective-C rebuild sites silently treat a union as a struct | Accepted. Fail-closed `isUnion` assertions land in r09. |
| `IRDesignation` declares a non-default field after defaults | Accepted. `value: IRExpr = None`, with non-null enforced by the verifier. |
| The boundary manifest count | 310 records (one draft said 309). |
