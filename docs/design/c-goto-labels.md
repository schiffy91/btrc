# goto and labels (Stage 20)

PLAN.md Stage 20 (`ccompat-r11-goto-labels`) adds `goto` and labels. D19 approves the row, and its consumer is the Stage 14 probe battery. Header inline functions never reach btrc, because the C compiler compiles their bodies.

`goto` is already a keyword (`grammar.ebnf:38`). The RESERVED note says no rule consumes it (`grammar.ebnf:22-31`), so today each parser refuses it with its own wording (`c3_c4.toml:5-47`, `:745-766`).

A drafter and two adversarial reviewers compared the options on 2026-10-02 (workflow `wf_926e5dfc-b6e`). One reviewer covered implementability in both compilers; the other covered ARC and setjmp. Every finding was re-checked against the code at `3812e44`, or with gcc 13.3 and clang 18.1 under the gate flags (`Makefile:321`). Each finding and its resolution is listed at the end of this section.

C1's and C2's principles carry over:
- one representation per C concept;
- kinds that fail closed;
- positions identical in both parsers;
- every deliberate refusal documented, with the same text and position in both compilers and a test in both;
- the fat `Node` gains no field.

btrc has no `defer`. Its cleanup scopes are three things, and this section decides how `goto` interacts with each:
- lexical ARC scopes, released at scope exit;
- `try`/`catch`/`finally` frames, built on `setjmp`;
- runtime exception-cleanup registrations, bracketed by `__btrc_cleanup_mark` and `__btrc_discard_cleanups_to`.

## Decisions

| Topic | Decision |
|---|---|
| AST | **`GotoStmt(identifier name, int name_line, int name_col)`** sits at `goto`, and its name position is the label identifier. **`LabelStmt(identifier name)`** sits at its identifier. A label is a statement-list item of its own: it marks the position before the next item, or the end of the list (the C23 6.8.2 block-item form). It owns no sub-statement, which is why it is `LabelStmt` and not the roadmap's `LabeledStmt`. Both kinds are appended to `stmt`. |
| Placement | A label may stand wherever a statement-list item may: in function, method, constructor, accessor and lambda bodies, blocks, loop bodies, case bodies, and `try`/`catch`/`finally` blocks. It may precede a declaration, end a block or a case body, or follow another label (`a: b:`). That is C23 placement, a documented btrc extension: C11 6.8.1 requires a statement after a label, and gcc `-std=c11 -pedantic-errors` rejects `L: int x;` and `{ L: }` (probe). btrc always emits `name: ;`, so its output stays strict C11. In a braceless body (Stage 16), leading labels and the statement after them form the synthesized block. |
| Scope and name space | Labels have function scope (C11 6.2.1p3). Each callable body is one label scope: function, method, constructor, getter, setter, and the body of every lambda (including `spawn` lambdas). Labels live in their own name space (C11 6.2.3p1), so a label may share a name with any variable, type or function, and it never claims a binding. |
| Spelling | A label name is checked like a binding whose C name the compiler generates. Python calls `validate_name(name, "Label", …, c_name_generated=True)`; btrc calls a new `validateLabelName`. A source-macro collision is refused in both compilers, so btrc gains that check for labels (`declarations.py:823-825` has it; `Names.btrc:132-146` lacks it). A hosted-macro name such as `EOF` is accepted and renamed (row C names below). |
| C names | Labels use the stateless binding rule in both compilers: Python `source_binding_c_name(name)` (`ir/lowering/calls.py:851-855`) and btrc `HostedAbi.lexicalBindingCName(name, typeConflict)` (`analyzer/HostedAbi.btrc:316`). They never use the lexical, shadow-aware versions (`ir/lowering/ownership.py:2063-2068`, `ir/lowering/Context.btrc:283-288`). So `EOF:` becomes `__btrc_source_EOF: ;`, and a goto and its label always agree. |
| Duplicate, undefined | Both are refused, because both are C constraints (C11 6.8.1p3, 6.8.6.1p1). |
| Reachability | A goto may target a label only in its own statement list or an enclosing one, within the same callable body. It never jumps into a nested list: a block, an if or else body, a loop body, a case body, a `try`/`catch`/`finally` block or a lambda body. This is a btrc policy, stricter than C. It can later be relaxed for plain blocks without changing any accepted program. |
| Entering a scope | A forward goto in item `k` of list `E`, aimed at a label at index `j > k`, enters every declaration between them. Its *entered declarations* are: the direct `VarDeclStmt`s of `E` at indices `(k, j)`; the direct `VarDeclStmt`s of the `finally_block` of every `TryCatchStmt` at those indices, because lowering splices `finally` statements into the enclosing C list (`ir/lowering/exceptions.py:1685-1688`); and the same, recursively, through `TryCatchStmt`s that sit directly in such a `finally` list. A variably modified declaration among them is refused, because C refuses it (C11 6.8.6.1p1). The other rules apply only to `E`'s own automatic declarations (not `static` or `extern`): each must be a plain C value (R10) and must never be named on a path after the label (R11). A backward goto enters nothing. |
| Leaving a scope | At the jump site, lowering releases every owner whose scope the goto leaves, innermost first, with the `release_scope(…, force=True)` that `break` uses (`ir/lowering/statements.py:583-598`). It then discards the exception-cleanup registrations of the left scopes. A backward goto also releases the owners its own frame declared after the label, so each pass releases the previous pass's values, as a loop does. |
| try / catch / finally | No goto enters or leaves a `try`, `catch` or `finally` block; a goto and its label inside one such region are allowed. `return`, `break` and `continue` do leave a try today: they pop frames and skip `finally` (pinned in `control_flow/ExceptionsFinallyControlFlowEscape.btrc:1-25`). That surprising rule is not extended to a new construct. |
| parallel for | A goto cannot leave a `parallel for` body. `break` and `return` may leave it today (`analyzer/statements.py:892-893`), but a goto can target a label before the loop and re-enter it, which no future parallel lowering can express. The README promises independent iterations (`README.md:800-803`). The refusal can be relaxed later. |
| Lambdas | A lambda body is its own label scope. A goto can neither leave nor enter one, and each case has a targeted diagnostic. |
| Termination | A `goto` never falls through. In a statement list, only the items after the last *targeted* direct label decide whether the list must terminate. A goto never counts as a loop break (`contains_loop_break` is unchanged). An untargeted label changes nothing. |
| Unreachable code | After a `return`, `throw`, `break`, `continue` or `goto`, the next item must be a label that some goto in the body targets. |
| keep / release | No new rule. A label is a statement, so it ends the keep/release adjacency proof (`analyzer/ownership.py:1576-1587`, btrc `validation/Ownership.btrc:559`) and the leading-consumption proof (`analyzer/ownership.py:1803-1819`). `release` and `delete` are take-and-clear, so a later scope release sees NULL. |
| @realtime | A backward goto is the blocking effect `backward goto 'L'`, the same kind as `unproven while loop`. A forward goto is effect-free, because every cycle needs a loop back-edge or a backward goto. |
| @gpu | `goto` and labels are refused through the existing statement table. The WGSL emitters fail closed. |
| Unused labels | They are accepted and emit nothing; `-Wall -Werror` would otherwise fail on `-Wunused-label`. |
| Fall-through comments | gcc's `-Wimplicit-fallthrough` fails `-Werror` when a falling case ends in a label, directly or at the end of a nested block (probes `ft4.c`, `ft_more.c`). Lowering therefore sets `IRLabel.falls_through` on each such tail label, and both emitters write `/* fall through */` immediately before it. |
| Schema timing | The two AST constructors and the two IR kinds land in Stage 19's serial `ccompat-c3-schema-vocabulary` commit. If that commit lands without them, Stage 20 opens with the same serial schema commit in the main session. The grammar rules land with the parsers, as C1's did. Until then, both parsers keep today's errors, with no interim message, so the probes change only once. |

### Why a goto never enters a nested list

btrc's lowering keeps hidden state at the start of nested lists, and around compound statements, that a jump into the middle would skip:
- **Cleanup markers.** A block's exception-cleanup marker is inserted as its first statement after the block is lowered (`ir/lowering/statements.py:203-207`). Its exits call `__btrc_discard_cleanups_to(marker)`.
- **for-in owners.** The owned iterable of a for-in is registered in the enclosing scope before the loop and released after it (`ir/lowering/iteration.py:406-441`).
- **Case bodies.** Each case body pushes its own managed scope and marker (`ir/lowering/control_flow.py:164-220`).
- **try.** A `try` block is the then-branch of `if (setjmp(...) == 0)` after `__btrc_push_try()` (`ir/lowering/exceptions.py:1660-1702`).

Proving each construct safe one at a time would be fragile. This one rule is cheap, and it is always safe.

## Shared owners

Each owner lives in one class per compiler and gets a contract test in both. Neither compiler gains a file.

- **`JumpScopeIndex`** (Python `analyzer/flow.py`, beside `ControlFlowAnalyzer`; btrc `analyzer/validation/ControlFlow.btrc`, which `ir/lowering/Statements.btrc:10` already imports).
  - **What it is.** A pure function of one callable body, `build(root)`. It walks statement lists only. It enters expressions only to find `LambdaExpr` bodies, and it records those as nested label scopes without indexing them.
  - **Its records** are `JumpList` and `JumpSite`.
    - A `JumpList` holds the list node, its kind (`body`, `block`, `if`, `else`, `loop`, `parallel`, `case`, `try`, `catch`, `finally`), its parent list and its index in the parent.
    - A `JumpSite` is one `GotoStmt` or `LabelStmt`, with its path of `(list, index)` from the root and its pre-order ordinal.
  - **Its queries:** `target(goto)` (the first label of that name), `targeted(name)`, `targeted_names`, `is_backward(goto)` (the target's ordinal is lower than the goto's), `enclosing(goto) -> (E, k, j) | None`, `left_lists(goto)`, `entered_lists(goto)`, `entered_declarations(goto)` (with the `finally` recursion) and `nested_lambda_label(name)`.
    - `reach_start(E, d, j)` is the R11 fixpoint. Start from `{j}`. Repeatedly add the index of any direct label of `E` in `(d, j)` that a goto located anywhere in `E[min:]` targets, nested lambda bodies excluded. The result is the smallest index reached.
  - **Who calls it.** The analyzer, the realtime analyzer and lowering each call `build` on demand and cache the result per body for one pass. Nothing stores it in `AnalyzedProgram`.
  - **Why lowering rebuilds it.** btrc module units can replay validation records instead of validating live (`analyzer/validation/Validator.btrc:154-176`), so an index that only live validation writes would be missing.
- **Jump-body marker.** Python `AnalyzedProgram.jump_body_ids`, keyed by `id(body)`; btrc `Analyzed.jumpBodyKeys`, keyed by `AstIdentity.key`.
  - The analyzer records every callable body that contains a goto or a label.
  - btrc journals the new fact `VALIDATION_JUMP_BODY = 13` (`analyzer/Models.btrc:46-59`), and `Validator.replay` installs it.
  - The record context becomes `validation-record-v5` (`pipeline/ModuleUnits.btrc:2748`, `:2842`, `:3057`).
  - Lowering builds frames only for marked bodies. btrc checks the map's emptiness before computing any key, so a program without goto pays one check per body.
- **Plain-value owner.** Python `TypeSystem.is_plain_c_object(type)` and `declaration_is_plain(type, initializer_type)`; btrc `SemanticTypeSystem.plainCObject` and `plainDeclaration`. The table is applied after typedef resolution and fails closed:

  | Plain | Not plain |
  |---|---|
  | `bool` and the `NUMERIC_TYPES` (`analyzer/types.py:2008`) | `string`, classes, interfaces, nullable references |
  | plain btrc enums | rich enums, tuples, `Span`, `Atomic<T>`, `Thread`, `Mutex`, collections and every other generic class |
  | hosted integer typedefs and `enum X` tags, through `is_opaque_c_scalar` (`types.py:2139-2150`), so `size_t` is plain | `__fn_ptr` (`CFunction`, lambdas) and `__realtime_fn_ptr` |
  | names in `hosted_abi.toml` `types`/`typedefs` used by value | generic type parameters; R10 runs on the template, where `T` is unresolved |
  | non-nullable raw pointers whose pointee is not `string`, a class or an interface | anything not in the left column |
  | fixed arrays whose extents are all constant and whose elements are plain | |
  | structs and unions whose members are all plain, read through the Stage 17 record-member owner | |
  | an unknown foreign `struct X`/`union X`, which is trusted C as today | |

  A declaration is plain when its declared type is plain and its initializer's type, if it has one, is neither a managed value type nor a type parameter. The managed-value test is Python `StorageModel.is_managed_value_type` (`analyzer/storage.py:263-277`) and its btrc counterpart. The initializer rule exists because `StorageLowerer` makes an owner from either type (`ir/lowering/storage.py:855-884`). Probes show scope-end releases for `void* p = new Box();`, `char* q = make();` and even `const char* r = "abc";` in both compilers.
- **Variably modified.** Python `TypeSystem.is_variably_modified(type, constant_bounds)`; btrc `SemanticTypeSystem.variablyModified`. A type is variably modified when its outermost `array_size` is non-null and is *not* in `constant_array_bound_ids`/`constantArrayBoundKeys`. The analyzer adds a bound exactly when it is constant (`analyzer/statements.py:509-511`), and Stage 18 allows a run-time bound only on the outermost extent. Later rows for pointer-to-VLA and block-scope VM typedefs inherit this predicate.
- **Termination predicates take the targeted names.** Python `ControlFlowAnalyzer.statement_must_terminate`, `block_must_terminate` and `statement_sequence_must_terminate` (`flow.py:249-306`) and btrc `ControlFlowValidator.statementTerminates`, `blockTerminates` and `statementSequenceTerminates` (`validation/ControlFlow.btrc:157-259`) gain a targeted-name parameter. It is empty or null for bodies without jumps.
  - btrc deletes the duplicate `ExpressionTypeResolver.blockTerminates/elseTerminates/statementTerminates` (`analyzer/Expressions.btrc:86-119`). Both lambda paths call `ControlFlowValidator` instead (`validation/ControlFlow.btrc:63`, `validation/Expressions.btrc:775`).
  - That change lands first, as its own parity commit with a both-compiler test (a typed lambda ending in `while (true) { return n; }` and one ending in a terminating `switch`). Python accepts both today and btrc refuses them; no accepted program changes.

## Conventions both parsers keep identical

**Positions** are canonical AST data:
- `GotoStmt` sits at `goto`, and `name_line`/`name_col` sit at the identifier.
- `LabelStmt` sits at its identifier.
- A synthesized braceless body that begins with a label sits at the first label (C1's rule).

**Statement start**, in Python `Parser._parse_statement` (`parser.py:1206`) and btrc `Parser.parseStatement` (`Parser.btrc:1178`). These two arms come before every existing arm:
1. A token whose spelling is a grammar keyword, other than `case` and `default`, followed by `:` raises R15 at the keyword. The keyword test is the one `_is_reserved_name`/`isReservedName` use. `_expect(IDENT)` alone cannot do this, because `:` is not a declarator follower (`parser.py:240-249`, `Parser.btrc:71-77`).
2. `IDENT ":"` becomes a `LabelStmt`, consumed by `expect(IDENT)` then `expect(COLON)`. `expect(IDENT)` already gives `_Atomic:` and `_Complex:` their deferred-specifier message (`parser.py:162-164`, `Parser.btrc:86-90`). No other statement can start with `IDENT ":"`: a ternary needs `?`, case labels start with a keyword, bit-fields appear only in record bodies, and `{` opens a block.

**`goto`.** The parser reads `goto`, then `expect(IDENT)`, then `expect(SEMICOLON)`.
- `goto;` gives `Expected IDENT, got SEMICOLON ';'` in both parsers.
- A keyword target such as `goto new;` gives `'new' is a reserved word and cannot be used as a name`, because `;` is a declarator follower.

**Braceless bodies (Stage 16).** The shared body helper (Python `_parse_body`, btrc `parseBody`) collects leading labels, then parses one statement under C1 (d)'s rule, so a declaration there stays refused.
- `if (c) L: ;` is a block that holds one `LabelStmt` (C1 (c): no `EmptyStmt`).
- A `}` after the labels gives `Expected a statement after label 'L'` at the `}`.

**Elsewhere.**
- Top-level labels keep today's top-level parse error.
- Labels in `case` bodies parse like any other statement-list item. The switch loop consumes `case` and `default` first, so they never reach the label arm.

**Rendering.** The btrc `AstCanonicalRenderer` gains two branches: `name`, `name_line`, `name_col` for `GotoStmt`, and `name` for `LabelStmt`. The Python renderer and `AstJsonCodec` are generic. `AstStructure.children` gains nothing, because neither kind has a child.

**Kind coverage.** btrc validators skip unknown kinds silently.
- A new contract test requires every btrc function that dispatches on `NK_BREAK_STMT` or `NK_RETURN_STMT` to name `NK_GOTO_STMT` or sit on a reasoned allow-list. It does the same for every function that dispatches on `IRK_BREAK` and `IRK_GOTO`. Today 14 btrc files name those AST kinds and 3 name `IRK_BREAK`.
- The Python test does the same for `BreakStmt`/`GotoStmt` and `IRBreak`/`IRGoto`. That would have caught the btrc lambda predicate (M3).
- It also requires every btrc site that reads `IRNode.name` without a kind check to exclude `IRK_GOTO` and `IRK_LABEL`.

## Rules

### Lookup, at a goto (walk order; the first failure is reported at the goto)

1. **Lookup.** The label exists in this body: continue. It exists in an enclosing body on the body-root stack: R3, naming that label's position. It is a label of a lambda nested in *this* body (the first in pre-order): R4. Otherwise: R2. A sibling lambda's label therefore gives R2.
   - The body-root stack is pushed at the five Python entry points (`analyzer/statements.py:813`, `:1456`, `:1490`, `:1513`, `:1586`) and at btrc `validateCallableBody` and both lambda paths (`validation/ControlFlow.btrc:44`, `validation/Expressions.btrc:743`).
   - It is never pushed in `_analyze_root_block`, which also serves catch blocks (`statements.py:1701`).
   - Every index is built on demand from its root, so R3 works when the label comes after the lambda.
2. **Leaving.** The left lists are checked innermost first. The first `try`/`catch`/`finally` list gives R5, and the first `parallel` list gives R8.
3. **Entering.** If any entered list is `try`/`catch`/`finally`, R6 names the outermost one. If any list is entered at all, the result is R7.

### At a label (walk order)

1. **Spelling.** Source macro first, then the `c_name_generated` template; a failure is R16. The check runs in the `LabelStmt` arm, never in btrc's block-entry `validateDirectLocalNames` (`Names.btrc:272`).
2. **Duplicates.** A label that is not the first of its name gives R1.
3. **Entered declarations.** Each forward goto to this label that passed its own checks is examined, in ordinal order. Its entered declarations are visited in source order, `finally` recursion included, and the first failure is reported at the goto:
   - **R9:** the declaration is variably modified;
   - **R10:** it is one of `E`'s automatic declarations and is not plain;
   - **R11:** it is one of `E`'s automatic declarations, and its name appears as an `Identifier` (inside lambda bodies too) anywhere in `E[reach_start(E, d, j):]`.
   - Types are known by this point. Python reads `stmt.type`, which is set for `var` too, and the initializer's analyzed type. btrc reads the label list's `vars`.
   - R11 matches by name and ignores shadowing, so it fails closed identically in both compilers. It keeps the C cleanup idiom: a resource declared after `if (!a) goto fail;` and released before `fail:` is never named after `fail:`.
   - R11 also covers a backward goto from after the label into the skipped region (fixture `backward-reach`), and clang's `-Wsometimes-uninitialized`, which fails the gate on a skipped initializer that is read later (probe `skipinit.c`, -O0 and -O2).

btrc stops at its first error. Python continues, and its first error is the same for single-error programs. btrc's block-entry validation of local names can reorder multi-error programs, which is recorded for Stage 21.

### Termination and unreachable code (both compilers)

- **Terminals.** `GotoStmt` is a terminal for must-terminate and stops-fallthrough. In a list, only the items after the last direct label in `targeted_names` decide.
  - The Python sites are `flow.py:67-85`, `:249-306`.
  - The btrc sites are `validation/ControlFlow.btrc:157-259`, plus `directTerminal` (`:527`) for R14.
  - Lowering's `try_terminates` (`exceptions.py:1563`, btrc `Statements.btrc:1043`) passes the session index's targeted names.
- **Loops.** `contains_loop_break` (`flow.py:309-331`) and `containsLoopBreak` are unchanged.
  - A goto that leaves a loop targets a label in an enclosing list. If the label is after the loop's ancestor statement there, that statement is not in the decisive suffix. If the label is before it, flow re-runs the loop.
  - So `int f(bool c) { again: while (true) { if (c) { goto again; } return 1; } }` needs no return.
  - `int f(int n) { if (n > 0) { goto done; } return 1; done: }` gets the existing missing-return error.
- **Unreachable code (R14).** After a direct terminal, the next item must be a targeted label (Python `statements.py:1719-1731`; btrc `validation/ControlFlow.btrc:512`, `:543`).
  - **Limitation:** a targeted label that is reachable only from code after it (a dead labeled cycle such as `return 0; again: n++; goto again;`) is accepted. Its C is valid and warning-free, and a test pins it.
- **Rebase on r15b.** Stage 19 r15b adds `_Noreturn` call statements to the same predicates. Stage 20 rebases after r15b and keeps both. R14's wording follows whatever terminal set r15b chooses.

### Python nullable facts (warnings only; btrc has no counterpart)

- At a targeted label, the facts become the intersection of two sets: the fall-through facts, when the list up to the label may fall through, and the facts recorded at each forward goto. Facts whose root is not visible at the label are dropped.
- A label that any backward goto targets starts with no facts.

### Lowering (one algorithm per compiler)

**Frames** exist only in marked bodies.
- **Classes.** `JumpLoweringFrame` and `LoweredLabel` live in Python `ir/lowering/control_flow.py` and btrc `ir/lowering/ControlFlow.btrc`.
- **Who pushes them.** `lower_block` (`statements.py:155-217`; btrc `lowerBlockWithBindings`) pushes a frame after its scope pushes and pops it before its scope pops. The switch-case lowering does the same (`control_flow.py:164-220`).
- **Isolation.** `OwnershipLowerer.isolated_function_state` (`ownership.py:1880`) and its btrc counterpart isolate the frame stack, `jump_index` and the variable-length registry for each lifted lambda.
- **A frame records:**
  - the list node, and its index on the managed-scope stack;
  - its marker's position in `CleanupScopeState._markers`;
  - the try-statement depth (Python `in_trycatch_depth`) and the provenance scope depth;
  - the IR list being built, plus `statement_start` (its owner count) and `statement_ir_start` (its IR length), both set before each item is lowered, after any line marker;
  - its labels, and the pending forward-goto states for each label name;
  - the forward gotos that target it.

**`lower_goto`:**
1. Find the frame F that holds the target label's list; if there is none, fail with an internal error (A5). Assert that the current try-statement depth equals F's (A1). Only the try body pushes a `"try"` control context (`exceptions.py:1582`), so depth is the datum that also covers `catch` and `finally`.
2. **The left owners** are every scope above F, plus F's owners:
   - from `statement_start` for a forward goto, which covers a for-in's hidden iteration owner;
   - from the label's owner prefix for a backward goto.
3. **Callable provenance.** A forward goto appends the projected state to F's pending states for the label. A backward goto calls `require_goto_back_edge(label.entry, projected)`. Projection is defined below.
4. Emit `release_scope(left, force=True)`. It reverses the list into innermost-first order (`ownership.py:1098-1101`).
5. **Cleanup registrations.**
   - A forward goto emits `exit(m)`, where `m` is the first active marker after F's marker. F's own registrations stay; the abandoned statement's hidden owners leave stale entries whose slots are NULL after take-and-clear. The runtime skips those (`runtime/c/trycatch.c:129-145`), as `finish_owned_iterable` already relies on.
   - A backward goto emits `exit(m)` for the first active marker *from* F's marker. If `m` is F's own marker, it then re-issues, in registration order, the registration of every owner F declared before the label.
6. Emit `IRGoto(c_name)`.

**Re-issuing a registration.**
- **The recipe.** `ManagedLocal` gains `cleanup_registration`, a small `CleanupRegistration` record of the `register` inputs: the declaration, the callback names and the direct flag. btrc `Managed` gains `cleanupRegistration: CleanupRegistration?`, null by default.
- **Where it is attached.** `register_named_cleanup` and `register_direct_cleanup` (`ownership.py:1273-1304`; btrc `maybeRegisterCleanup` and `maybeRegisterDirectCleanup`, `Lifetime.btrc:474-489`) attach it to the owner with that C name in the innermost managed scope. Those are the paths for named locals, for-in owners and `Thread` locals; `Thread` locals are `ManagedLocal`s with `cleanup_kind="thread"` (`ownership.py:2007-2018`).
- **How it is re-issued.** By calling `CleanupSlotRegistry.register` again (`ownership.py:150-171`). That builds fresh argument nodes and reuses the declaration's own `IRCleanupSlot`, as a second registration already does. A deep copy would fail the verifier, which matches slot metadata by identity (`ir/verifier.py:366-371`). The emitted call is the plain one, never the register-once ternary.
- **A4:** every owner of F before the label must have a recipe when F's marker is active.

**`lower_label`:**
1. An untargeted label emits nothing.
2. `falls_in` is `IRStatementSequence(F.ir).may_fall_through()`.
3. `enter_label` joins the current state (if `falls_in`) with the pending states through `join_flows`. A label with neither keeps the current state, because it is dead code. The result is recorded as the label's entry.
4. Record the owner prefix, the names F has declared so far and the IR index.
5. Emit `IRLabel(c_name)`.

**Projection** mirrors `_restricted_snapshot` (`calls.py:1802-1813`; btrc `CallableFlow.btrc:396-414`).
- A name declared in a scope deeper than F takes the binding it shadowed.
- For a backward goto, a name F declared after the label takes the binding it shadowed at the label.
- For a forward goto, every name an entered declaration declares is dropped. Those declarations are plain (R10), and `bind_local` removes a plain name's callable binding (`calls.py:1058-1062`).
- Key sets therefore always match, and `join_flows` never raises `mismatched lexical bindings` (`calls.py:1542-1558`).
- Pending states live in the frame, never in a provenance snapshot, so `isolated_flow` and `restore` cannot drop them.
- The new methods are Python `CallableProvenance.record_goto`, `enter_label` and `require_goto_back_edge`, and btrc `CallableFlowState.recordGoto`, `enterLabel` and `requireGotoBackEdge`. A failed back-edge reports R17 in the loop wording (`calls.py:1657-1671`; `CallableFlow.btrc:548`).

**Assertions** fail closed with internal errors:
- **A2.** In a jump body, each item other than a `VarDeclStmt` leaves F's owner count unchanged, and a `VarDeclStmt` adds at most one owner. The failure text is `statement lowering left a managed owner registered in its enclosing scope`. Forward release sets are exact only under this invariant. The for-in owner is registered and unregistered within its statement (`iteration.py:424`, `:438`).
- **A3.** Before F's marker entry is inserted, check each forward goto into F. The direct `IRVarDecl`s of F's IR from the goto's `statement_ir_start` to its label must satisfy three conditions:
  - none is in the session's variable-length registry, which Python `StorageLowerer.materialize_array_bound`'s run-time path (`storage.py:999-1010`) and its btrc counterpart fill;
  - no automatic one is referenced by an `IRVar` in F's IR at or after the label;
  - none names one of F's owners.

  This is the backstop for R9, R10 and R11 across lowering's splices and hidden temporaries. It is a lowering assertion rather than a verifier rule because IR has no VLA marker: `IRVarDecl.array_size` (`ir/nodes.py:760`) is any `IRExpr`, and a constant macro bound lowers to an `IRVar`.

**Sequences.** In `IRStatementSequence.may_fall_through` (`ir/nodes.py:988-1012`; btrc `ir/lowering/ControlFlow.btrc:7-70`), `IRGoto` never falls through. Only the items after the last direct `IRLabel` decide; every emitted label is targeted. Every consumer inherits this:
- Python: `statements.py:202`, `:777`; `control_flow.py:108`, `:116`, `:195`; `exceptions.py:1635-1636`, `:1691`; `collections.py:193`; `iteration.py:343`; `optimizer.py:861`.
- btrc: `ownership/CycleBoundaries.btrc:117`, `:610`; `Statements.btrc:161`, `:266`, `:282`, `:1063`, `:1153`, `:1277`, `:1332`, `:1335`, `:1421`.
- A then-branch that ends in a goto contributes no state to the code after the `if`.

**Tail labels.** When a case's `falls_through` is set, lowering marks the first label of the trailing label run in each tail list, skipping `IRLineMarker`s:
- the case body;
- the body of an `IRBlock` that ends a tail list;
- both branches of an `IRIf` that ends a tail list.

gcc warns for the nested-block form (probe `ft_more.c`, function `b`). The `IRIf` form passes without the comment, but it is marked anyway for robustness across gcc versions. Each emitter writes `/* fall through */` as part of the label's own emission, so it always directly precedes the label. Probe `ft_fix.c` passes gcc and clang at -O0, -O2 and -O3.

### setjmp

- **Volatility region.** Today, in Python `_LexicalVisibilityPass.block` (`exceptions.py:954-962`) and btrc `SetjmpSafetyPlanner.scanBlock` (`setjmp/Safety.btrc:573-586`), the continuation of a setjmp-containing item `i` is `stmts[i+1:]`.
  - New rule: if labels at indices `≤ i` of the same list are targeted by gotos located anywhere in `stmts[i:]`, the continuation becomes `stmts[m:]`. `m` comes from the same fixpoint as `reach_start`.
  - This mirrors the structured-loop rule (`exceptions.py:1061-1070`) at every list level.
  - Gotos never cross a try, so writes inside a try body stay in its then-branch. The `finally` statements sit after the setjmp `IRIf` and fall under the continuation.
  - More inferred-volatile locals can reach the existing qualifier-safety refusal (R18).
- **Pointer flow.** In Python `PointerFlow` (`exceptions.py:383-539`) and btrc `SetjmpEffectAnalysis` (`setjmp/Analysis.btrc:1350-1410`):
  - `IRGoto(L)` joins the current state into `pending[L]` and then sets the state to bottom (the empty alias state). Pending states accumulate per function.
  - At `IRLabel(L)`, `pending[L]` is restricted to the storages bound at that point, then joined into the state. This is one explicit restriction rule in both compilers.
  - If a later goto targets `L`, the rest of the list is iterated: `header = join(entry, restricted pending[L])`, at most 16 times.
  - If it has not converged, both compilers widen the header with Python's `_widen` rule (`exceptions.py:530-533`) and run the suffix once more. btrc gains `flowWiden`.
  - The list's exit is the end state of the last run. The schedule must bound the iteration, because Python's origin depth is unbounded (`PointerOrigin.deeper`, `exceptions.py:146-149`). Structured loops keep today's schedules (see the findings below).
- **No-op arms.** `_MutationCollector`, `_QualifierSafety`, btrc `collectStatementMutations` (`Safety.btrc:276`) and `validateStatement` (`:134`) gain explicit arms for goto and label that do nothing. `contains_setjmp` is generic.

### @realtime and @gpu

- **Realtime.** In Python `RealtimeAnalyzer._visit` (`analyzer/realtime.py:232-272`) and btrc `analyzer/Realtime.btrc`, a `GotoStmt` that its own body's index says is backward emits `_effect(callable_, "blocking", f"backward goto '{name}'", node)`.
  - The visitor tracks the innermost body root, so a label inside a nested lambda never makes an outer forward goto look backward.
  - btrc journals the effect through the existing realtime record.
  - The IR backstop (Python `IRVerifier._validate_realtime_function`, `verifier.py:289-347`; btrc `ir/optimization/Realtime.btrc:94-103`) walks in pre-order and fails `backward goto` on an `IRGoto` whose `IRLabel` it has already seen.
  - Canonical C-for proofs are unaffected: a forward goto inside the loop either leaves it or reaches the update.
- **GPU.** Python `_STATEMENT_LABELS` (`analyzer/gpu.py:763-774`) and btrc `GpuKernelValidator.statementLabel` (`analyzer/GPU.btrc:333-345`) gain `goto` and `labeled`. The existing fallback reports the first offending statement (`gpu.py:254-255`, `GPU.btrc:402-403`).

### IR invariants and emission

Python `IRVerifier` checks these rules. In btrc, `CEmitter` raises internal errors for them, after the optimizer. In every function body:
- **(V1)** Label names are unique, every `IRGoto` names an `IRLabel` of the same body, and every `IRLabel` is named by at least one goto.
- **(V2)** The label's list is the goto's own list or an enclosing one, never inside an `IRStmtExpr`.
- **(V3)** Neither kind appears in an `IRGpuKernel`.
- **(V4)** A goto and its label have the same innermost region. A region is a branch of an `IRIf` whose condition contains `setjmp`, an `IRObjectiveCAutoreleasePool`, an `IRObjectiveCExceptionBoundary` or an `IRCxxExceptionBoundary`.

**Emission.** The C emitters write `goto name;` and `name: ;`, preceded by `/* fall through */` when `falls_through` is set. The WGSL emitters raise "unsupported statement".

**Module units.** btrc `ModuleUnitDeclarations.collectNode` skips `IRK_GOTO` and `IRK_LABEL`, because today it collects `name` from every node (`pipeline/ModuleUnits.btrc:506-508`). Python's `_referenced` is kind-specific (`application/modules.py:616-628`).

**No change needed.** The optimizer's reachability, stdlib reachability and frontend visibility read only identifiers (`frontend/Visibility.btrc:131`; `frontend/imports.py:483-485`). A contract test pins that a label named like a function, type or stdlib type creates no edge and no import.

### LSP, formatter and documentation

- **LSP navigation.** `NavigationProvider.build_index` (`lsp/features/navigation.py:294`) records each `LabelStmt` as a definition site and each `GotoStmt` name as an occurrence of the same-named label in the same callable body. Labels are excluded from variable occurrences. They get no symbols.
- **LSP completion.** `completion.py:18` drops `goto` from `_RESERVED_WITHOUT_SYNTAX` and gains `_KEYWORD_DOCS["goto"]`. `test_completion_signature_correctness.py:45` keeps asserting only `override`.
- **Formatter.** `btrc-format` (`devex/formatter/engine.py`) treats a statement-start `IDENT :` line as a label:
  - no space before the colon;
  - indented at its block's statement level;
  - not a continuation, although `:` is in the continuation sets (`engine.py:310-366`).

  The fixture is `src/tests/formatter/fixtures/GotoLabels.btrc`.
- **Docs.**
  - `known-language-gaps.md` replaces the sentence at `:100-103` with a "goto and labels (C row 11)" section. It lists the supported forms, the C23-placement extension and the refusal table. R5–R8, R10 and R11 also go under "C that btrc rejects on purpose".
  - `README.md:2154` drops `goto` from "Reserved syntax".
  - The grammar's RESERVED note drops `goto`.
  - This section joins `docs/design/c-compatibility.md`.

## Refusals

Each refusal has the same text and position in both compilers. Positions are at the `goto` unless the table says otherwise. Every row has a test in both compilers.

| # | Kind | Diagnostic |
|---|---|---|
| R1 | C 6.8.1p3, at the later label | `Duplicate label 'again' in this function (first at 1:25)` |
| R2 | C 6.8.6.1p1 | `Label 'missing' is not defined in this function` |
| R3 | policy | `goto 'done' cannot leave a lambda body (label at 1:44)` |
| R4 | policy | `goto 'inner' cannot enter a lambda body (label at 1:69)` |
| R5 | policy | `goto 'out' cannot leave a try block; set a flag and test it after the try statement` (also `a catch block`, `a finally block`) |
| R6 | policy | `goto 'inside' cannot enter a try block` (also `a catch block`, `a finally block`) |
| R7 | policy | `goto 'inside' cannot jump into a nested block; jump only to a label in the same block or an enclosing one` |
| R8 | policy | `goto 'done' cannot leave a parallel for body` |
| R9 | C 6.8.6.1p1 | `goto 'inside' jumps into the scope of variable-length array 'values' declared at 1:65` |
| R10 | policy | `goto 'done' skips the declaration of 'name' (1:59), which is not a plain C value; declare it before the goto or inside a nested block` |
| R11 | policy (indeterminate values, C11 6.2.4p6) | `goto 'done' skips the declaration of 'x' (1:56), which is used after the label; declare it before the goto` |
| R12 | realtime, at the goto | `@realtime callable 'audio' reaches forbidden blocking operation 'backward goto 'again'' via audio` |
| R13 | GPU, at the statement | `@gpu function 'kernel': goto statement is not allowed in GPU functions` / `… labeled statement is not allowed in GPU functions` |
| R14 | existing, reworded, at the statement | `Unreachable code after return/throw/break/continue/goto` (today's tests match the substring `Unreachable code`, `test_analyzer.py:2070-2094`, `:2721`) |
| R15 | row 20, at the keyword | `'string' is a reserved word and cannot be used as a name` (keyword labels and keyword goto targets) |
| R16 | spelling, at the label | `Label name 'LIMIT' collides with source macro 'LIMIT'`; `Label name '__btrc_x' uses the compiler-reserved '__btrc_' prefix`; `Label name '_X' is reserved by C11` |
| R17 | lowering, unpositioned as for loops | `Callable ownership ABI must be invariant across a repeated loop back-edge from goto 'again'; changed binding(s): callback` |
| R18 | existing lowering refusal (`exceptions.py:834-840`), unpositioned, now reachable through goto regions around `try` | `storage object 'buf' is modified across try/throw and requires volatile storage; its address or array decay requires unsupported layered pointer qualifiers` |
| P1 | parse | `Expected IDENT, got SEMICOLON ';'` (bare `goto;`); `Expected a statement after label 'L'` (braceless body); existing `C11 '_Atomic' is not supported; use btrc's Atomic<T> for atomic storage` |

## Schema commit (Stage 19 `ccompat-c3-schema-vocabulary`, or Stage 20's opening serial commit)

```asdl
    stmt = ...
         | KeepStmt(expr expr)
         | ReleaseStmt(expr expr)
         -- `goto name;` (C11 6.8.6.1). line/col mark `goto`; name_line and
         -- name_col mark the label identifier.
         | GotoStmt(identifier name, int name_line, int name_col)
         -- `name:` as a statement-list item (C23 6.8.2): it marks the position
         -- before the next item, or the end of the list, and owns no statement.
         -- line/col mark the identifier. Each callable and lambda body is one
         -- label scope; labels have their own name space.
         | LabelStmt(identifier name)
         attributes(int line, int col)
```

**Fat `Node`: 0 bytes.**
- `name`, `nameLine` and `nameCol` already exist (`generated/ast/Node.btrc:112`, `:127-128`).
- The new kinds `NK_GOTO_STMT` and `NK_LABEL_STMT` are appended to `stmt` after `ReleaseStmt`, beside whatever Stage 19 appends.
- Kinds render by name, and the toolchain fingerprint invalidates the numbered module-unit records.

**Python dataclasses** gain `GotoStmt(name, name_line, name_col)` and `LabelStmt(name)`.

**IR, in both compilers:**

| Python `ir/nodes.py` | btrc `ir/Model.btrc` | C |
|---|---|---|
| `IRGoto(IRStmt)`, `name: str = ""` | `IRK_GOTO`, appended after `IRK_LINE_MARKER` (`Model.btrc:66`), so it stays `>= IRK_VAR_DECL`. It reuses `name` and is built by `IRNode.gotoStatement(name)` | `goto name;` |
| `IRLabel(IRStmt)`, `name: str = ""`, `falls_through: bool = False` | `IRK_LABEL`, reusing `name` and `fallsThrough` (`Model.btrc:143`), built by `IRNode.labelStatement(name, fallsThrough)` | `/* fall through */` when set, then `name: ;` |

**IRNode: 0 bytes.** No `IRModule` list is added.

**Grammar** (`grammar.ebnf`) lands with the construct commit, together with the parsers:
- Delete `goto` from the RESERVED note.
- Add `block = "{" { block_item } "}"`, `block_item = label | statement`, `label = IDENT ":"` and `goto_stmt = "goto" IDENT ";"`, and add `goto_stmt` to `statement`.
- Change `case_clause` to `( "case" expr | "default" ) ":" { block_item }`.
- Stage 16's braceless-body rule gains leading `{ label }`.

**Exit for the schema commit:**
- the generated-source check and the `AstCanonicalRenderer` coverage check;
- `boundary-check` unchanged;
- AST and parser parity;
- the bootstrap fixed point;
- zero analyzer warnings on the self-host transpile.

## Consumers to update

The construct is one commit (D5): Python first, then the btrc port by the same implementer. It is preceded by the btrc lambda-termination parity commit.

- **Python:**
  - Parser: `Parser._parse_statement` (two first arms, `goto`) and Stage 16's `_parse_body`.
  - `analyzer/flow.py`: `JumpScopeIndex`, `JumpList`, `JumpSite`; the predicates with targeted names; `ControlFlowAnalyzer.validate_goto` (R2–R8) and `validate_label_entry` (R9–R11).
  - `analyzer/types.py`: `is_plain_c_object`, `declaration_is_plain`, `is_variably_modified`.
  - `analyzer/program.py` and `analyzer.py`: `jump_body_ids`, the body-root stack and the index cache.
  - `analyzer/statements.py`: the five entry points, the `_analyze_stmt` arms, R1, R14, R16, the nullable joins, and termination callers that pass targeted names.
  - `analyzer/realtime.py`; `analyzer/gpu.py`.
  - IR: `ir/nodes.py` (`IRGoto`, `IRLabel`, `IRStatementSequence`); `ir/verifier.py` (V1–V4, the realtime backstop).
  - Lowering:
    - `session.py`: `jump_index`, `jump_frames`, the variable-length registry;
    - `control_flow.py`: frames, `lower_goto`, `lower_label`, the case frame, tail-label marking;
    - `statements.py`: frames, `statement_start`, A2, A3;
    - `storage.py`: the variable-length registry;
    - `ownership.py`: `CleanupRegistration`, `ManagedLocal.cleanup_registration`, `CleanupScopeState.first_active_marker(from_index)`, `isolated_function_state`;
    - `calls.py`: `record_goto`, `enter_label`, `require_goto_back_edge`;
    - `exceptions.py`: the region rule, pointer-flow arms and label fixpoint, the no-op arms, and `:1563`.
  - Backend: `backend/c_emitter.py`; `backend/wgsl_emitter.py`.
- **btrc:**
  - Parser: `Parser.parseStatement` and `parseBody`. Syntax: `AstCanonicalRenderer`.
  - Analyzer:
    - `validation/ControlFlow.btrc`: index, predicates, `directTerminal`, R1–R11, R14, lambda path;
    - `analyzer/Expressions.btrc`: delete the duplicate predicates;
    - `validation/Expressions.btrc:775`; `validation/Declarations.btrc:801`;
    - `validation/Names.btrc`: `validateLabelName`;
    - `analyzer/Models.btrc`: `jumpBodyKeys`, `VALIDATION_JUMP_BODY`;
    - `validation/Validator.btrc`: the replay arm;
    - `analyzer/Types.btrc`: `plainCObject`, `plainDeclaration`, `variablyModified`;
    - `analyzer/Realtime.btrc`; `analyzer/GPU.btrc`.
  - Lowering:
    - `ir/Model.btrc`; `ir/lowering/Context.btrc` (index, frames, registry);
    - `ir/lowering/ControlFlow.btrc` (frames, sequence, goto, label);
    - `ir/lowering/Statements.btrc` (frames, A2, A3, case frames, `:1043`);
    - `ir/lowering/ownership/Lifetime.btrc` (`CleanupRegistration`, `Managed.cleanupRegistration`, first active marker);
    - `ir/lowering/CallableFlow.btrc`.
  - Setjmp: `ir/optimization/setjmp/Analysis.btrc` (arms, fixpoint, `flowWiden`); `ir/optimization/setjmp/Safety.btrc` (region rule, no-op arms).
  - Emission and the rest: `ir/optimization/Realtime.btrc`; `ir/Emitter.btrc` (emission, V1–V4); `ir/gpu/Wgsl.btrc`, `ir/gpu/Pipeline.btrc`; `pipeline/ModuleUnits.btrc` (`collectNode`, `validation-record-v5`).
- **Tests, LSP, formatter and docs:**
  - **Inventory** (`c3_c4.toml`; `REFUSAL_ROWS` gains `"11"`, `test_c_compatibility_inventory.py:78`). Each changed entry takes its parent commit as `revision` and drops `divergence`:
    - `r11-goto-forward-label` → `accepted`, `corpus = "c_compat/GotoForwardLabel.btrc"`;
    - `r11-goto-undefined-label` → `rejected`, R2 at 2:2;
    - `r11-goto-into-vla-scope` → `rejected`, R7 at 3:2.
    - New probes:
      - `r11-goto-past-vla-same-block` (negative, R9);
      - `r11-goto-backward-loop` (positive, accepted, `corpus = "c_compat/GotoBackwardLoop.btrc"`);
      - `r11-goto-duplicate-label` (negative, R1);
      - `r11-goto-into-nested-block` (positive, `refused-on-purpose`, R7);
      - `r11-goto-label-null-statement` (positive, accepted; `L: ;` before a declaration).
    - The C23 forms cannot be inventory probes, because the schema requires `accepted` to have positive (C11-valid) intent (`test_c_compatibility_inventory.py:189-190`).
  - **`test_c_compatibility_refusals.py`** gains `GOTO_REFUSALS` (C11-valid, refused on purpose):

    | id | source | expected |
    |---|---|---|
    | `r11-nested-block` | `int main() { int n = 0; if (n == 0) { goto inside; } { inside: n++; } return n; }` | R7 at 1:39 |
    | `r11-into-loop` | `int main() { int n = 0; if (n == 0) { goto inside; } while (n < 3) { inside: n++; } return n; }` | R7 at 1:39 |
    | `r11-across-cases` | `int main() { int x = 1; switch (x) { case 1: goto two; case 2: two: break; default: break; } return 0; }` | R7 at 1:46 |
    | `r11-skip-literal-pointer` | `int main() { int n = 0; if (n == 0) { goto done; } const char* message = "x"; done: return n; }` | R10, `'message' (1:64)`, at 1:39 |
    | `r11-assign-after-label` | `int main() { int n = 0; if (n == 0) { goto done; } int x = 5; n = x; done: x = 1; return n + x; }` | R11, `'x' (1:56)`, at 1:39 |

    Its `ACCEPTED` list gains `int main() { int n = 0; if (n == 0) { goto done; } int unused = 5; n = unused; done: return n; }`.
  - **`src/tests/btrc/test_goto_contract.py`** (both compilers; diagnostics compared with `_diagnostic_identity`). Positions were computed from these exact strings.

    | id | source | expected |
    |---|---|---|
    | undefined | `int main() { int n = 0; if (n == 0) { goto missing; } return n; }` | R2 at 1:39 |
    | duplicate | `int main() { int n = 0; again: n++; again: return n; }` | R1 at 1:37 |
    | string | `int main() { int n = 0; if (n == 0) { goto done; } string name = "x"; print(name); done: return n; }` | R10 `'name' (1:59)` at 1:39 |
    | class | `class Box { public Box() {} }\nint main() { int n = 0; if (n == 0) { goto done; } Box box = new Box(); done: return n; }` | R10 `'box' (2:56)` at 2:39 |
    | owned initializer | `string make() { return "x"; }\nint main() { int n = 0; if (n == 0) { goto done; } char* text = make(); done: return n; }` | R10 `'text' (2:58)` at 2:39 |
    | object initializer | `class Box { public Box() {} }\nint main() { int n = 0; if (n == 0) { goto done; } void* handle = new Box(); done: return n; }` | R10 `'handle' (2:58)` at 2:39 |
    | leave try / catch / finally | `int main() { try { goto out; } catch (string e) {} out: return 0; }`; `int main() { try { throw "x"; } catch (string e) { goto out; } out: return 0; }`; `int main() { try { print("x"); } finally { goto out; } out: return 0; }` | R5 at 1:20 / 1:52 / 1:44 |
    | enter try | `int main() { int n = 0; if (n == 0) { goto inside; } try { inside: n++; } catch (string e) {} return n; }` | R6 at 1:39 |
    | leave lambda | `int main() { var f = () => { goto done; }; done: return 0; }` | R3 at 1:30 |
    | enter lambda | `int main() { int n = 0; if (n == 0) { goto inner; } var f = () => { inner: print("x"); }; f(); return n; }` | R4 at 1:39 |
    | sibling lambda | `int main() { var f = () => { goto inner; }; var g = () => { inner: print("x"); }; f(); g(); return 0; }` | R2 at 1:30 |
    | parallel | `import Library.Vector;\nint main() { Vector<int> xs = [1, 2]; parallel for x in xs { if (x == 2) { goto done; } } done: return 0; }` | R8 at 2:76 |
    | past VLA | `int main() { int count = 2; if (count > 0) { goto inside; } int values[count]; values[0] = 1; inside: return 0; }` | R9 `values` at 1:65, reported at 1:46 |
    | VLA in finally | `int main() { int count = 2; if (count > 0) { goto done; } try { print("x"); } finally { int values[count]; values[0] = 1; } done: return 0; }` | R9 `values` at 1:93, reported at 1:46 |
    | read / capture / backward reach | `int main() { int n = 0; if (n == 0) { goto done; } int x = 5; n = x; done: return n + x; }`; `… done: var f = () => x; return f(); }`; `… int x = 5; again: n = n + x; done: if (n < 3) { goto again; } return n; }` | R11 `'x' (1:56)` at 1:39 |
    | unreachable | `int main() { int n = 0; goto done; n++; done: return n; }` | R14 at 1:36 |
    | untargeted after return | `int main() { return 0; done: print("x"); }` | R14 at 1:24 |
    | keyword labels | `int main() { int n = 0; string: n++; return n; }`; `int main() { int n = 0; return: n++; return n; }` | R15 at 1:25 |
    | keyword target | `int main() { int n = 0; if (n == 0) { goto new; } return n; }` | R15 at 1:44 |
    | bare goto | `int main() { int n = 0; if (n == 0) { goto; } return n; }` | P1 at 1:43 |
    | `_Atomic:` | `int main() { int n = 0; _Atomic: n++; return n; }` | P1 (deferred) at 1:25 |
    | spelling | `int main() { int n = 0; __btrc_x: n++; return n; }` | R16 at 1:25 |
    | source macro | `#define LIMIT 3\nint main() { int n = 0; if (n == 0) { goto LIMIT; } LIMIT: return n; }` | R16 at 2:53 |
    | leading consumption | `class Box { public Box() {} }\nvoid consume(Box box) { again: release box; }\nint main() { return 0; }` | existing `Managed parameter consumption must be an unconditional leading release/delete so callers can prove ownership transfer` at 2:32 |
    | GPU goto / label | `@gpu int[] kernel(int[] a) { int i = gpu_id(); if (i > 0) { goto done; } done: return a[i]; }`; `@gpu int[] kernel(int[] a) { int i = gpu_id(); done: return a[i]; }` | R13 at 1:61 / 1:48 |
    | realtime | `@realtime void audio(bool ready) { again: if (!ready) { goto again; } }` | R12 at 1:57 |
    | falls off after a label | `int pick(int n) { if (n > 0) { goto done; } return 1; done: }` | pinned per compiler at 1:1: Python `Function 'pick' has non-void return type but no return statement`, btrc `Callable 'pick' has non-void return type but does not return on every path` |

    **Accepted, run strictly through both compilers:**
    - `int spin(bool c) { again: while (true) { if (c) { goto again; } return 1; } }`;
    - a typed lambda loop, `var f = int function(int n) { int i = n; again: if (i > 3) { return i; } i++; goto again; };`;
    - an untargeted label after an if/else that returns on both sides (no label is emitted);
    - the dead labeled cycle `return n; again: n++; goto again;`;
    - `size_t length = (size_t)n;` entered and not used after the label;
    - `EOF:`, which emits `goto __btrc_source_EOF;` and `__btrc_source_EOF: ;`;
    - `goto x;` from a block that shadows `x` (C label `x` in both places);
    - a label named `Vector` without an import;
    - the C23 forms `skip: int m = n;` and `{ … end: }`.

    **Module units:**
    - a warm-cache `--module-units` rebuild of a two-module goto program, also run with `BTRC_VERIFY_VALIDATION_RECORDS=1`;
    - a label named like a function defined in another unit, with identical unit C from both compilers that compiles strictly.

    A **static scan** runs the kind-coverage contract.
  - **`test_callable_control_flow_parity.py`** (`:116-176`) gains:
    - `if (choose) { callback = genericCallableSourceString; goto joined; } joined:` → "ambiguous ownership ABI";
    - `again: pass++; if (choose && pass < 2) { callback = genericCallableSourceString; goto again; }` → "invariant across a repeated loop back-edge";
    - a goto branch followed by a use of `callback` after the `if` → no error.
  - **`test_realtime_parity.py`:**
    - `@realtime int audio(int v) { if (v < 0) { goto done; } v = v * 2; done: return v; }` is accepted;
    - a backward goto in a helper reports `via audio -> helper`;
    - a label inside a nested lambda does not make a later outer forward goto backward.
  - **`test_setjmp_continuation_contract.py` and `test_setjmp_qualifier_state_contract.py`:**
    - a goto retry loop around `try` makes the same locals `volatile` in both compilers' C;
    - an edge carrying `p = &b` makes `b` volatile;
    - a backward goto from after a `try` to a label before it, with a nested `try`;
    - nested goto loops compare the volatile sets;
    - a decayed fixed array mutated in a goto region around `try` gives R18.
  - **Corpus** (both compilers; strict C11 at -O0 through -O3 under `make test-c11`; owned names in camelCase per `test_naming_convention_contract.py:209-239`):
    - `c_compat/GotoForwardLabel.btrc` and `c_compat/GotoBackwardLoop.btrc`.
    - `c_compat/GotoCleanup.btrc` covers:
      - `malloc`, with plain locals entered and unused after `closeFile:` and `fail:`;
      - consecutive labels, a label before a declaration, a label at the end of a block;
      - a braceless `if (err) goto fail;`;
      - leaving nested loops, and a goto out of a case;
      - a falling case whose body, and whose last nested block, end in labels;
      - a retry counter and an unused label.
    - `memory/GotoArcRelease.btrc` is the ARC witness, in the `memory/ArcLoopExit.btrc` pattern: `alive` counts `Resource` objects and is asserted at every checkpoint. It covers forward exits from a block, a C-for with a managed initializer, a for-in over an owned and over a borrowed `Vector`, and a switch case; backward gotos past a declaration and from a nested block; `string` locals; a `Thread<int>` local; and `release`/`delete` before gotos.
    - `control_flow/GotoExceptions.btrc` covers goto loops inside `try`, `catch` and `finally`; the flag-retry loop around `try` with managed and `Thread` locals declared before and after the label and a throw on some passes; a throw after a goto loop; and `assert(alive == 0)`.
    - `btrc/fixtures/GotoArcWitnessRuntime.btrc` runs through `_tracked_strict_matrix` (`test_arc_hidden_lifecycle_boundaries.py:54`; `arc_test_allocation_delta() == 0`). It also runs through `runtime_ownership_harness.sanitized_build_and_run` (`:191`) for both compilers; Linux covers the sanitizer run.
  - **`src/tests/python/test_goto_labels.py`** covers parser shapes and positions, `JumpScopeIndex` paths and `reach_start`, every analyzer diagnostic, release sets and re-issued registrations in `--emit-ir` (Python only, since btrcc has no IR dump), A1–A5, `IRStatementSequence`, tail-label marking, V1–V4, the region rule and the pointer-flow fixpoint.
  - **LSP:** `navigation.py` and `completion.py`, with their tests. **Formatter:** the `engine.py` label rule plus its fixture.
  - **Docs:** `known-language-gaps.md`, `README.md:2154`, the grammar note and this section. The main session amends both roadmap items (`ccompat-c3-schema-vocabulary`, `ccompat-r11-goto-labels`) when this design lands: `LabelStmt`, no interim message, released re-initialization and forward-only realtime.

## Memory impact

- **btrc `Node`: 0 bytes**, two kinds. **btrc `IRNode`: 0 bytes**, two kinds reusing `name` and `fallsThrough`.
- **`Managed`/`ManagedLocal`:** one lowering-only field, null by default, on a transient record.
- **Index, frames and the variable-length registry** are allocated only for bodies in `jump_body_ids`. A body without jumps pays one emptiness check.
- **The self-compile.** btrcc's own source contains no goto or label, so it pays only kind checks, the label scan in `IRStatementSequence` and the emptiness checks.
- **Measurement.** The delta is measured with Stage 15's method at the schema commit and again at `ccompat-c3-integrate`. ≤0.3% passes; up to 1% is accepted with the delta recorded.

## Boundary records

The manifest holds 311 records, and none change:
- **Tokens.** `goto` and `:` are already tokens.
- **Sources.** No boundary source contains a goto, a label, a statement-start `IDENT :` or code after a terminal (`fixtures/compiler_boundaries/sources/*.source`). So no AST, IR, C or diagnostics artifact moves.
- **IR.** `IRModule` gains no list, and no existing IR class gains a field.
- **Commands.** The schema commit and the construct commit each still run `boundary-check` and the generated-source check.

Outside the manifest:
- the `c3_c4.toml` entries change, each with `revision` set to its parent commit;
- `KNOWN_DIVERGENCES` is unchanged;
- `validation-record-v5` invalidates cached btrc module-unit records;
- btrcc's own C is unchanged by the construct, so the bootstrap fixed point should not move.

## Findings for other owners

1. **Python nullable warnings.** Facts survive loop back-edges: a `p = null` after `p.x` inside a `while` body warns nowhere. The label rule above does not inherit the gap. *(Python analyzer owner.)*
2. **Pointer flow ignores `break`/`continue` edges** in both compilers (`exceptions.py:448-482`, `Analysis.btrc:1350-1410`). A loop's exit state can miss a break's state. Goto edges are explicit. *(setjmp owner.)*
3. **Structured-loop schedules differ.** Python widens after 16 steps (`exceptions.py:483-492`); btrc runs to convergence (`Analysis.btrc:1285-1298`). Python also restricts state to visible storages at block exit, while btrc only truncates bindings. Stage 20 aligns only its own label fixpoint. *(setjmp owner.)*
4. **Missing-return messages diverge.**
   - The wording differs (`test_analyzer.py:1887`, `test_semantic_validation.py:153`).
   - The lambda wording differs too: "does not return a value on every path" (`statements.py:819`) against "does not return on every path" (`validation/ControlFlow.btrc:64`).
   - Python checks lambda termination only for an explicit return type (`statements.py:814-818`), while btrc uses the inferred one.

   *(Stage 21.)*
5. **btrc has no source-macro check for locals.** btrcc accepts `#define LIMIT 3` with `int LIMIT = 0;`, which gcc then rejects. Local-name diagnostics also differ: `Variable name 'EOF' … at 2:6` against `Local variable name 'EOF' … at 2:2`. *(Stage 21.)*
6. **btrc `collectNode` collects every node's `name`**, local declarations included (`ModuleUnits.btrc:506-508`). Stage 20 only excludes its two kinds. *(Module-unit owner.)*
7. **btrc validates direct local names at block entry** (`Names.btrc:272`, `validation/ControlFlow.btrc:536`), so multi-error programs order their diagnostics differently from Python. *(Stage 21.)*
8. **Some infinite loops are refused as a missing return in both compilers.** That happens when a `while (true)` or `for (;;)` body does not itself terminate (`flow.py:286-301`, `validation/ControlFlow.btrc:252-256`), although the C is valid. *(Stage 21 docs.)*

## Lanes and merge order

1. **Prerequisites.** `ccompat-c1-integrate` (the braceless-body helper) and Stage 19's vocabulary and schema commit. Stage 20 rebases after r15b. It may overlap the r15c, r15d and r16 lanes, but no sibling lane may touch flow, ownership or setjmp code.
2. **Read-only, in parallel.** One agent writes the fixture drafts listed here and re-verifies every position. A second agent refines the Python contract's signatures against the code.
3. **Serial, main session.** The schema commit if Stage 19 omitted it, then the btrc lambda-termination parity commit.
4. **One implementer, one branch.** Python first, then the btrc port. It lands as one construct commit with the tests, docs and inventory changes, and builds its btrcc under the semaphore.
5. **Two adversarial reviewers.**
   - **ARC checklist:**
     - exact release sets (A2) and no end-of-list release after a list that cannot fall through;
     - take-and-clear prevents any double release;
     - R10 matches lowering's owner rule, with A3 as the backstop;
     - discard and re-issue keep exactly the live slots, `Thread` included, which the throw-after-goto fixtures prove;
     - thread and cycle-flush paths behave as for `break`;
     - `join_flows` never sees mismatched keys.
   - **setjmp checklist:**
     - no goto crosses a try, enforced three times (R5/R6, A1, V4);
     - identical volatile sets from the region rule;
     - sound pointer-flow edges with the bounded label fixpoint;
     - re-issued registrations shaped exactly like the originals;
     - the no-op arms and `contains_setjmp`.
6. **Gate.** D5's batch gate, including `make bootstrap` and `make test-c11`, plus zero analyzer warnings on the self-host transpile and the LSP, formatter and extension tests.
7. **`ccompat-c3-integrate`.** It merges r11 last, as its own batch. Then it changes the inventory rows, records the memory delta and updates the docs.

## Review resolutions

| Finding | Resolution |
|---|---|
| B1: R10 reads only the declared type, but lowering also makes owners from the initializer's type (blocking) | Accepted, and it reaches further than reported: `const char* r = "abc";` is an owner in both compilers too (probe). The plain-declaration owner tests the declared type and the initializer type. A3 makes any entered owner an internal error. Fixtures cover `char* text = make()` and `void* handle = new Box()`, and `GOTO_REFUSALS` covers the string-literal pointer. A single owner shared with `StorageLowerer` was rejected: the analyzer cannot depend on the lowering's `ManagedValueSemantics.is_managed` (`ownership.py:742-747`), so the analyzer side is a superset and A3 catches any disagreement. |
| B2: a label at the end of a falling case fails gcc `-Wimplicit-fallthrough` (blocking) | Accepted and extended: a label at the end of a nested block that ends a case fails gcc too (probe `ft_more.c`). Lowering marks tail labels with `IRLabel.falls_through` (0 bytes in btrc, through `fallsThrough`), so the emitter only formats. `ft_fix.c` passes gcc and clang at -O0, -O2 and -O3; a corpus case pins it. |
| B3: replayed btrc validation records never build the jump index (blocking) | Accepted. The index is a pure function of the body, built by its owner in the analyzer and again in lowering. `VALIDATION_JUMP_BODY` marks jump bodies; replay installs it; the record version becomes v5. A warm-cache test and a record-verification test cover it. |
| M1: which `source_binding_c_name` is meant is ambiguous | Accepted. Only the stateless rule is used (`calls.py:851`, `HostedAbi.btrc:316`), with a shadowing fixture. |
| M2: `EOF:` contradicts local validation, and btrc lacks the source-macro check | Accepted. `c_name_generated` validation runs in the label arm, with a btrc source-macro check for labels. The divergence for locals goes to Stage 21. |
| M3: btrc lambdas use a second termination predicate | Accepted, as a preceding parity commit that deletes the duplicate and has a both-compiler test. |
| M4: btrc module units collect `name` from every IR node | Accepted. `collectNode` skips both kinds, both IR models name the field `name`, and a module-units test covers it. The broader over-collection goes to the module-unit owner. |
| M5 and the second review's major: re-registration misses `Thread` cleanups | Accepted, with a correction: a deep copy would fail the verifier's identity check on `IRCleanupSlot` (`verifier.py:366-371`). The recipe on the `ManagedLocal` is re-issued through `register`, which reuses the slot metadata. A4 asserts completeness. `GotoExceptions.btrc` has a `Thread` case with a throw. |
| M6: two classes named `JumpFrame` | Accepted. The analyzer has `JumpList` and `JumpSite`; lowering has `JumpLoweringFrame` and `LoweredLabel`. All four names are unused in both compilers today. |
| M7 and the second review's minor: lazy indexes turn R3 into R2, and `_analyze_root_block` serves catch blocks | Accepted. Indexes are built on demand from roots on a body-root stack that is pushed only at the callable entry points. R4 names the first label in pre-order, and a sibling lambda's label gives R2. |
| M8: the plain-value definition contradicts itself | Accepted. There is one explicit table, driven by existing predicates. `size_t` is plain (`is_opaque_c_scalar`), and type parameters are not. |
| M9: setjmp fixpoint schedules differ | Accepted for the goto fixpoint: at most 16 steps, then widen, in both compilers, with an explicit restriction at the label. "Run to convergence" was rejected because Python's origin depth is unbounded (`exceptions.py:146-149`). Structured loops are recorded for the setjmp owner. |
| M10: LSP completion still hides `goto` | Accepted. |
| m1 and the second review's minor: counting a goto as a loop exit | Accepted. `contains_loop_break` is unchanged. Both reviews' example, `again: while (true) { if (c) { goto again; } }`, is wrong: it is refused under any goto rule, because `while (true)` must have a terminating body (`flow.py:286-291`). The fixture is corrected to add `return 1;` in the loop, and the pre-existing rule is recorded for Stage 21. |
| m2: the parser placement leaves `return:` without R15 | Accepted, with a correction: `expect(IDENT)` alone cannot yield R15, because `:` is not a declarator follower (`parser.py:240-249`). The keyword-colon arm comes first; `expect(IDENT)` is kept for the deferred specifiers. |
| m3: `may_fall_through` has more consumers | Accepted. All consumers are listed, pending states live outside provenance snapshots, a dead label keeps the current state, and a test checks the after-`if` state. |
| m4: `close_file:` breaks the naming contract | Accepted (`closeFile:`). |
| m5: the wrong sanitizer harness | Accepted (`runtime_ownership_harness.sanitized_build_and_run`). |
| m6: the roadmap items disagree with the draft | Accepted. The main session amends both items. |
| m7: the realtime "seen labels" walk descends into lambdas | Accepted. Each goto is classified against its own body's index. |
| m8: smaller corrections | Accepted. The R9 test reads "*in* the constant set"; `--emit-ir` checks are Python-only; first-error equality is claimed only for single-error programs (ordering recorded); NodeKinds are appended by name; the kind-coverage contract is added. |
| Second review, blocking: VLAs hoisted from `finally` escape R9 | Accepted. Entered declarations include `finally` bodies recursively, and a fixture covers it (gcc and clang both reject the C). The backstop is lowering assertion A3, not a verifier V5: IR has no VLA marker, and adding `IRVarDecl.is_variable_length` would change the `managed` raw and optimized IR boundary artifacts. |
| Second review, major: R9's constant test is inverted | Accepted (the shared `is_variably_modified` owner; "non-static" is dropped, because C11 6.7.6.2p2 already forbids a static VLA). |
| Second review, major: entered plain declarations are read indeterminate, and clang fails the gate | Accepted as R11, with a corrected region: uses in `E[j:]` alone miss a backward goto from after the label into the skipped region (fixture `backward-reach`), so R11 checks `E[reach_start:]`. It applies to declarations with and without initializers, and test cases cover a read, an assignment then a read, a capture and the backward reach. |
| Second review, minor: the analyzer and the IR disagree about untargeted labels | Accepted. Only targeted labels reset the suffix, and the predicates take the targeted names. |
| Second review, minor: goto regions can reach the qualifier-safety refusal | Accepted as R18, with a both-compiler test. |
| Second review, minor: the lowering's try assertion has no data | Accepted with a different datum: the try-statement depth, which also covers `catch` and `finally`, which push no control context. |
| Second review, minor: dead labeled cycles pass R14 | Accepted. The limitation is stated in R14 and pinned by a test. |
| Second review, minor: C23 placement is not C11 | Accepted as a documented extension. It is pinned in `test_goto_contract.py`, because the inventory schema cannot record an accepted program of negative intent. |
| Second review, "checked and found sound" | Confirmed: lazily activated markers, stale entries after take-and-clear (`trycatch.c:129-145`), statement balance, no duplicate C labels, generic `T` not plain, forked module-unit workers keeping `id(body)` valid, and user code built without `-fobjc-arc`. |
| Draft: "module units and reachability read no label names" | Corrected by M4. Stdlib reachability and visibility read only identifiers; a contract test pins that. |
