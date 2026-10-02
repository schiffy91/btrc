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
  r07's. btrcc still refuses a second prototype of an already-declared
  function, which the reference compiler accepts (pre-existing; see
  `docs/known-language-gaps.md`).

