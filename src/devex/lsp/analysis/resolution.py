"""Semantic lookup and lexical-scope indexes for immutable snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types as lsp

from src.compiler.python.analyzer.program import ClassInfo
from src.compiler.python.syntax.ast.generated import (
    Block,
    CallExpr,
    CaseClause,
    CForStmt,
    ClassDecl,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    FieldDecl,
    ForInitVar,
    ForInStmt,
    FunctionDecl,
    Identifier,
    IfStmt,
    MethodDecl,
    NewExpr,
    ParallelForStmt,
    Param,
    Program,
    PropertyDecl,
    SwitchStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)
from src.compiler.python.syntax.tokens import Token, TokenKind
from src.devex.lsp.analysis.document import DocumentAnalysis, DocumentText
from src.devex.lsp.catalog.builtins import BuiltinCatalog


@dataclass
class VarDef:
    """A single variable-like definition with its scope context.

    ``line``/``col`` point at the NAME token. ``scope_start``..``scope_end``
    is the inclusive 1-based line range the definition is visible in.
    """

    name: str
    line: int
    col: int
    scope_start: int
    scope_end: int
    kind: str = "local"
    node: object = None
    owner: str | None = None


@dataclass(frozen=True)
class ChainResolution:
    """The resolved receiver type and whether it denotes a type itself."""

    type_name: str
    direct_type_reference: bool = False


_PRIMITIVE_TYPES = frozenset({"int", "float", "double", "long", "short", "char", "bool", "void", "unsigned"})


class LexicalScopeIndex:
    """Cached block-granular variable definitions for one snapshot."""

    def __init__(self, definitions: list[VarDef]) -> None:
        self.definitions = definitions

    @classmethod
    def from_analysis(cls, analysis: DocumentAnalysis, resolver: SemanticResolver) -> LexicalScopeIndex:
        cached = analysis._caches.get("lexical_scope")
        if cached is None:
            cached = cls(cls.collect_lexical_vars(resolver.active_decls(analysis), analysis.tokens))
            analysis._caches["lexical_scope"] = cached
        return cached

    def visible(self, name: str, line: int, col: int) -> VarDef | None:
        return self.find_visible_var_def(self.definitions, name, line, col)

    @staticmethod
    def find_closing_brace_line(source_lines: list[str], start_line: int) -> int | None:
        """Find a matching closing brace without counting literals or comments."""
        from src.compiler.python.lexer.lexer import Lexer, LexerError

        fragment = "\n".join(source_lines[start_line:])
        try:
            tokens = Lexer(fragment, "<lsp-braces>").tokenize()
        except LexerError:
            return LexicalScopeIndex._find_closing_brace_line_raw(source_lines, start_line)
        matched = LexicalScopeIndex.find_matching_brace_line(tokens, 1, 1)
        return start_line + matched - 1 if matched is not None else None

    @staticmethod
    def _find_closing_brace_line_raw(source_lines: list[str], start_line: int) -> int | None:
        """Best-effort fallback for lexically incomplete live text."""
        depth = 0
        found_open = False
        for line_index in range(start_line, len(source_lines)):
            for char in source_lines[line_index]:
                if char == "{":
                    depth += 1
                    found_open = True
                elif char == "}":
                    depth -= 1
                    if found_open and depth == 0:
                        return line_index
        return None

    @staticmethod
    def find_matching_brace_line(tokens: list[Token], line: int, col: int) -> int | None:
        """Find the brace-token match at/after a 1-based source position."""
        depth = 0
        opened = False
        for token in tokens:
            if token.line < line or (token.line == line and token.col < col):
                continue
            if token.type == TokenKind.LBRACE:
                depth += 1
                opened = True
            elif token.type == TokenKind.RBRACE and opened:
                depth -= 1
                if depth == 0:
                    return token.line
        return None

    @staticmethod
    def body_range(body: Block | None, fallback_start: int, tokens: list[Token] | None = None) -> tuple[int, int]:
        """Compute the inclusive source-line range of a block."""
        start = body.line if body is not None and body.line else fallback_start
        if tokens and body is not None and body.line:
            end = LexicalScopeIndex.find_matching_brace_line(tokens, body.line, body.col)
            if end is not None:
                return (start, end)
        if not body or not body.statements:
            return (fallback_start, fallback_start + 1000)
        end = max((LexicalScopeIndex.deepest_line(stmt) for stmt in body.statements), default=start)
        return (start, end + 50)

    @staticmethod
    def deepest_line(node) -> int:
        """Return the greatest source line reachable through control-flow children."""
        best = getattr(node, "line", 0)
        for attr in ("body", "then_block", "else_block", "try_block", "catch_block", "getter_body", "setter_body"):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, ElseBlock) and child.body:
                child = child.body
            elif isinstance(child, ElseIf) and child.if_stmt:
                child = child.if_stmt
            best = max(best, LexicalScopeIndex.deepest_line(child))
        if isinstance(node, Block):
            best = max((LexicalScopeIndex.deepest_line(stmt) for stmt in node.statements), default=best)
        if isinstance(node, SwitchStmt):
            for case in node.cases:
                best = max((LexicalScopeIndex.deepest_line(stmt) for stmt in case.body), default=best)
        return best

    @staticmethod
    def decl_list(ast_or_decls) -> list:
        if ast_or_decls is None:
            return []
        if isinstance(ast_or_decls, Program):
            return ast_or_decls.declarations
        return ast_or_decls

    @staticmethod
    def find_enclosing_class(ast: Program | list, line: int) -> str | None:
        """Find the class whose AST extent contains a 1-based source line."""
        for decl in LexicalScopeIndex.decl_list(ast):
            if not isinstance(decl, ClassDecl) or decl.line > line:
                continue
            max_line = max((LexicalScopeIndex.deepest_line(member) for member in decl.members), default=decl.line)
            if line <= max_line:
                return decl.name
        return None

    @staticmethod
    def find_enclosing_class_from_source(ast: Program | list, source: str, cursor_line: int) -> str | None:
        """Find an enclosing class using lexical braces, never string braces."""
        declarations = LexicalScopeIndex.decl_list(ast)
        if not declarations:
            return None
        from src.compiler.python.lexer.lexer import Lexer, LexerError

        try:
            tokens = Lexer(source, "<lsp-scope>").tokenize()
        except LexerError:
            tokens = None
        source_lines = source.split("\n")
        for decl in declarations:
            if not isinstance(decl, ClassDecl):
                continue
            class_start = decl.line - 1
            if tokens is not None:
                matched = LexicalScopeIndex.find_matching_brace_line(tokens, decl.line, decl.col)
                class_end = matched - 1 if matched is not None else None
            else:
                class_end = LexicalScopeIndex.find_closing_brace_line(source_lines, class_start)
            if class_end is not None and class_start <= cursor_line <= class_end:
                return decl.name
        return None

    @staticmethod
    def _name_token_pos(tokens: list[Token] | None, name: str, line: int, col: int) -> tuple[int, int]:
        """Position of the first token spelling *name* at/after (line, col)."""
        if tokens:
            for tok in tokens:
                if tok.line < line or (tok.line == line and tok.col < col):
                    continue
                if tok.value == name:
                    return (tok.line, tok.col)
        return (line, col)

    @staticmethod
    def _block_end(tokens: list[Token] | None, block: Block | None, fallback: int) -> int:
        """Real end line of *block* via brace matching; *fallback* when unknown."""
        if tokens and block is not None and block.line:
            end = LexicalScopeIndex.find_matching_brace_line(tokens, block.line, block.col)
            if end is not None:
                return end
        return fallback

    @staticmethod
    def collect_callable_vars(
        var_defs: list[VarDef], node, tokens: list[Token] | None, class_name: str | None = None
    ) -> None:
        """Collect params + body variables of a FunctionDecl/MethodDecl."""
        scope_start, scope_end = LexicalScopeIndex.body_range(node.body, node.line, tokens)
        owner = f"{class_name}.{node.name}" if class_name else node.name
        for p in node.params:
            if p.name and p.line:
                line, col = LexicalScopeIndex._name_token_pos(tokens, p.name, p.line, p.col)
                var_defs.append(VarDef(p.name, line, col, scope_start, scope_end, "param", p, owner))
        if node.body:
            LexicalScopeIndex._collect_block(var_defs, node.body, tokens, scope_end)

    @staticmethod
    def collect_lexical_vars(declarations, tokens: list[Token] | None) -> list[VarDef]:
        """Collect variable-like definitions from active-file callables."""
        var_defs: list[VarDef] = []
        for declaration in declarations:
            if isinstance(declaration, FunctionDecl):
                LexicalScopeIndex.collect_callable_vars(var_defs, declaration, tokens)
            elif isinstance(declaration, ClassDecl):
                for member in declaration.members:
                    if isinstance(member, MethodDecl):
                        LexicalScopeIndex.collect_callable_vars(var_defs, member, tokens, declaration.name)
        return var_defs

    @staticmethod
    def find_visible_var_def(var_defs: list[VarDef], name: str, line: int, col: int) -> VarDef | None:
        """Return the innermost syntactic definition visible at a position."""
        best: VarDef | None = None
        for var_def in var_defs:
            if var_def.name != name:
                continue
            at_def_site = (var_def.line, var_def.col) == (line, col)
            in_scope = var_def.scope_start <= line <= var_def.scope_end and (var_def.line, var_def.col) <= (line, col)
            if not (at_def_site or in_scope):
                continue
            if best is None or (var_def.scope_start, var_def.line) > (best.scope_start, best.line):
                best = var_def
        return best

    @staticmethod
    def _collect_block(var_defs: list[VarDef], block: Block, tokens: list[Token] | None, block_end: int) -> None:
        """Collect definitions inside *block*; *block_end* is its real end line."""
        for stmt in block.statements:
            LexicalScopeIndex._collect_stmt(var_defs, stmt, tokens, block_end)

    @staticmethod
    def _add_var(
        var_defs: list[VarDef], tokens: list[Token] | None, name: str, at, scope: tuple[int, int], kind: str, node=None
    ) -> None:
        line, col = LexicalScopeIndex._name_token_pos(tokens, name, at.line, at.col)
        var_defs.append(VarDef(name, line, col, scope[0], scope[1], kind, node))

    @staticmethod
    def _collect_stmt(var_defs, stmt, tokens, block_end: int) -> None:
        if isinstance(stmt, VarDeclStmt):
            if stmt.name and stmt.line:
                LexicalScopeIndex._add_var(var_defs, tokens, stmt.name, stmt, (stmt.line, block_end), "local", stmt)
        elif isinstance(stmt, Block):
            LexicalScopeIndex._collect_block(
                var_defs, stmt, tokens, LexicalScopeIndex._block_end(tokens, stmt, block_end)
            )
        elif isinstance(stmt, ForInStmt):
            end = LexicalScopeIndex._block_end(tokens, stmt.body, block_end)
            if stmt.var_name and stmt.line:
                LexicalScopeIndex._add_var(var_defs, tokens, stmt.var_name, stmt, (stmt.line, end), "loop")
            if stmt.var_name2 and stmt.line:
                LexicalScopeIndex._add_var(var_defs, tokens, stmt.var_name2, stmt, (stmt.line, end), "loop_key")
            if stmt.body:
                LexicalScopeIndex._collect_block(var_defs, stmt.body, tokens, end)
        elif isinstance(stmt, ParallelForStmt):
            end = LexicalScopeIndex._block_end(tokens, stmt.body, block_end)
            if stmt.var_name and stmt.line:
                LexicalScopeIndex._add_var(var_defs, tokens, stmt.var_name, stmt, (stmt.line, end), "parallel")
            if stmt.body:
                LexicalScopeIndex._collect_block(var_defs, stmt.body, tokens, end)
        elif isinstance(stmt, CForStmt):
            end = LexicalScopeIndex._block_end(tokens, stmt.body, block_end)
            if isinstance(stmt.init, ForInitVar):
                var_decl = stmt.init.var_decl
                if isinstance(var_decl, VarDeclStmt) and var_decl.name and var_decl.line:
                    LexicalScopeIndex._add_var(
                        var_defs, tokens, var_decl.name, var_decl, (var_decl.line, end), "cfor", var_decl
                    )
            if stmt.body:
                LexicalScopeIndex._collect_block(var_defs, stmt.body, tokens, end)
        elif isinstance(stmt, TryCatchStmt):
            if stmt.try_block:
                LexicalScopeIndex._collect_block(
                    var_defs, stmt.try_block, tokens, LexicalScopeIndex._block_end(tokens, stmt.try_block, block_end)
                )
            catch_end = LexicalScopeIndex._block_end(tokens, stmt.catch_block, block_end)
            if stmt.catch_var and stmt.catch_block is not None and stmt.catch_block.line:
                try_end = LexicalScopeIndex._block_end(tokens, stmt.try_block, stmt.line)
                line, col = LexicalScopeIndex._catch_var_pos(tokens, stmt.catch_var, try_end, stmt.catch_block)
                var_defs.append(VarDef(stmt.catch_var, line, col, stmt.catch_block.line, catch_end, "catch"))
            if stmt.catch_block:
                LexicalScopeIndex._collect_block(var_defs, stmt.catch_block, tokens, catch_end)
            if stmt.finally_block:
                LexicalScopeIndex._collect_block(
                    var_defs,
                    stmt.finally_block,
                    tokens,
                    LexicalScopeIndex._block_end(tokens, stmt.finally_block, block_end),
                )
        elif isinstance(stmt, IfStmt):
            if stmt.then_block:
                LexicalScopeIndex._collect_block(
                    var_defs, stmt.then_block, tokens, LexicalScopeIndex._block_end(tokens, stmt.then_block, block_end)
                )
            if isinstance(stmt.else_block, ElseBlock) and stmt.else_block.body:
                body = stmt.else_block.body
                LexicalScopeIndex._collect_block(
                    var_defs, body, tokens, LexicalScopeIndex._block_end(tokens, body, block_end)
                )
            elif isinstance(stmt.else_block, ElseIf) and stmt.else_block.if_stmt:
                LexicalScopeIndex._collect_stmt(var_defs, stmt.else_block.if_stmt, tokens, block_end)
        elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
            if stmt.body:
                LexicalScopeIndex._collect_block(
                    var_defs, stmt.body, tokens, LexicalScopeIndex._block_end(tokens, stmt.body, block_end)
                )
        elif isinstance(stmt, SwitchStmt):
            end = block_end
            if tokens and stmt.line:
                end = LexicalScopeIndex.find_matching_brace_line(tokens, stmt.line, stmt.col) or block_end
            for case in stmt.cases:
                if isinstance(case, CaseClause):
                    for s in case.body:
                        LexicalScopeIndex._collect_stmt(var_defs, s, tokens, end)

    @staticmethod
    def _catch_var_pos(tokens: list[Token] | None, name: str, after_line: int, catch_block: Block) -> tuple[int, int]:
        """Name-token position of a catch variable (last *name* in the header)."""
        best = (catch_block.line, catch_block.col)
        if tokens:
            for tok in tokens:
                if (tok.line, tok.col) >= (catch_block.line, catch_block.col):
                    break
                if tok.line >= after_line and tok.value == name:
                    best = (tok.line, tok.col)
        return best


class SemanticResolver:
    """Resolve types, scopes, tokens, and source locations."""

    def __init__(self, catalog: BuiltinCatalog) -> None:
        self.catalog = catalog

    def type_repr(self, type_expr, class_table: dict[str, ClassInfo] | None = None) -> str:
        """Format a TypeExpr as source-like text."""
        if type_expr is None:
            return "void"
        base = getattr(type_expr, "base", None) or "void"
        result = base
        generic_args = getattr(type_expr, "generic_args", None) or []
        if generic_args:
            args = ", ".join(self.type_repr(arg, class_table) for arg in generic_args)
            result += f"<{args}>"
        pointer_depth = getattr(type_expr, "pointer_depth", 0)
        if class_table and base in class_table and (pointer_depth == 1):
            pointer_depth = 0
        result += "*" * pointer_depth
        if getattr(type_expr, "is_array", False):
            result += "[]"
        if getattr(type_expr, "is_nullable", False):
            result += "?"
        if getattr(type_expr, "is_const", False):
            result = f"const {result}"
        return result

    def _is_wordish(self, token: Token) -> bool:
        first = token.value[:1]
        return first.isalpha() or first == "_"

    def find_token_at_position(
        self, tokens: list[Token], position: lsp.Position, source: str | None = None
    ) -> Token | None:
        """Find a token at a 0-based LSP position, including a trailing caret."""
        if source is not None:
            position = DocumentText(source).source_position(position)
        target_line = position.line + 1
        target_col = position.character + 1
        containing: Token | None = None
        ending: Token | None = None
        for token in tokens:
            if token.type == TokenKind.EOF or token.line != target_line:
                continue
            end_col = token.col + len(token.value)
            if containing is None and token.col <= target_col < end_col:
                containing = token
            if ending is None and end_col == target_col:
                ending = token
        if containing is not None and self._is_wordish(containing):
            return containing
        if ending is not None and self._is_wordish(ending):
            return ending
        return containing if containing is not None else ending

    def nav_tokens(self, result: DocumentAnalysis) -> list[Token]:
        """Return cached navigation tokens with f-string expressions expanded."""
        cached = result._caches.get("nav_tokens")
        if cached is None:
            cached = self.navigation_tokens(result.tokens or [])
            result._caches["nav_tokens"] = cached
        return cached

    def navigation_tokens(self, tokens: list[Token]) -> list[Token]:
        expanded: list[Token] = []
        for token in tokens:
            if token.type == TokenKind.FSTRING_LIT:
                expanded.extend(self._fstring_expression_tokens(token))
            expanded.append(token)
        return expanded

    def _fstring_expression_tokens(self, token: Token) -> list[Token]:
        from src.compiler.python.lexer.lexer import Lexer, LexerError

        result: list[Token] = []
        content = token.value
        for start, end in self._fstring_expression_spans(content):
            expression = content[start:end]
            line_offset = content[:start].count("\n")
            base_col = token.col + 2 + start if line_offset == 0 else len(content[:start].rsplit("\n", 1)[-1]) + 1
            try:
                inner_tokens = Lexer(expression, "<fstring>").tokenize()
            except LexerError:
                continue
            for inner in inner_tokens:
                if inner.type == TokenKind.EOF:
                    continue
                result.append(
                    Token(
                        inner.type,
                        inner.value,
                        token.line + line_offset + inner.line - 1,
                        base_col + inner.col - 1 if inner.line == 1 else inner.col,
                    )
                )
        return result

    def _fstring_expression_spans(self, content: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        index = 0
        while index < len(content):
            if content[index] == "{" and (not (index + 1 < len(content) and content[index + 1] == "{")):
                end = self._fstring_expression_end(content, index + 1)
                if end is not None:
                    spans.append((index + 1, end))
                    index = end + 1
                    continue
            index += 2 if content[index] == "}" and index + 1 < len(content) and (content[index + 1] == "}") else 1
        return spans

    def _fstring_expression_end(self, content: str, start: int) -> int | None:
        depth = 1
        index = start
        quote: str | None = None
        escaped = False
        while index < len(content):
            char = content[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return None

    def result_location(
        self, result: DocumentAnalysis, line: int, col: int, length: int = 0, file: str | None = None
    ) -> lsp.Location:
        """Create a location in the active document or an explicitly named file."""
        uri = Path(file).absolute().as_uri() if file and file != result.path else result.uri
        source = self.source_for_file(result, file)
        return lsp.Location(uri=uri, range=DocumentText(source).protocol_range(line, col, length))

    def source_for_file(self, result: DocumentAnalysis, file: str | None = None) -> str:
        """Return the analyzed source text for an active or imported location."""
        target = file or result.path
        for unit in result.units:
            if unit.path == target and unit.source:
                return unit.source
        if target == result.path:
            return result.snapshot_source or result.source
        if target:
            try:
                with open(target, encoding="utf-8") as source_file:
                    return source_file.read()
            except OSError:
                pass
        return ""

    def active_decls(self, result: DocumentAnalysis) -> list:
        """Return top-level declarations belonging to the active document."""
        cached = result._caches.get("active_decls")
        if cached is not None:
            return cached
        if not result.ast:
            return []
        decls = [decl for decl in result.ast.declarations if getattr(decl, "source_file", None) in (None, result.path)]
        result._caches["active_decls"] = decls
        return decls

    def find_token_index(self, tokens: list[Token], token: Token) -> int | None:
        for index, candidate in enumerate(tokens):
            if candidate is token:
                return index
        return None

    def get_text_before_cursor(self, source: str, position: lsp.Position) -> str:
        """Return text on the current line before the cursor."""
        lines = source.split("\n")
        if 0 <= position.line < len(lines):
            return lines[position.line][: position.character]
        return ""

    def resolve_chain(
        self,
        result: DocumentAnalysis,
        tokens: list[Token],
        end_idx: int,
        class_table: dict[str, ClassInfo],
        decls: list | None = None,
    ) -> ChainResolution | None:
        """Resolve the base type produced by an identifier/member/call chain."""
        root_idx, was_call = self._chain_segment(tokens, end_idx)
        if root_idx is None or not self._is_chain_identifier(tokens[root_idx]):
            return None
        chain: list[tuple[str, bool]] = [(tokens[root_idx].value, was_call)]
        while root_idx >= 2 and tokens[root_idx - 1].value in (".", "->", "?."):
            candidate, was_call = self._chain_segment(tokens, root_idx - 2)
            if candidate is None or not self._is_chain_identifier(tokens[candidate]):
                return None
            root_idx = candidate
            chain.append((tokens[root_idx].value, was_call))
        chain.reverse()
        root, root_called = chain[0]
        scope_decls = decls if decls is not None else self.active_decls(result)
        root_resolution = self._resolve_root(
            result, root, root_called, tokens[root_idx], scope_decls, class_table, use_scope_map=decls is None
        )
        if root_resolution is None:
            return None
        current_type = root_resolution.type_name
        receiver_is_type = root_resolution.direct_type_reference
        for member, called in chain[1:]:
            current_type = self.resolve_member_type(
                current_type, member, class_table, prefer_method=called, static_access=receiver_is_type
            )
            if current_type is None:
                return None
            receiver_is_type = False
        return ChainResolution(
            current_type, direct_type_reference=len(chain) == 1 and root_resolution.direct_type_reference
        )

    def _resolve_root(
        self,
        result: DocumentAnalysis,
        root: str,
        called: bool,
        token: Token,
        decls: list,
        class_table: dict[str, ClassInfo],
        *,
        use_scope_map: bool,
    ) -> ChainResolution | None:
        if called:
            if root in class_table:
                return ChainResolution(root)
            function_table = result.analyzed.function_table if result.analyzed else {}
            function = function_table.get(root)
            if function is not None and function.return_type:
                return ChainResolution(function.return_type.base)
            builtin = self.catalog.function_signature(root)
            return ChainResolution(self.catalog.base_type_name(builtin[0])) if builtin else None
        if root == "self":
            enclosing = None
            if use_scope_map:
                enclosing = LexicalScopeIndex.find_enclosing_class_from_source(decls, result.source, token.line - 1)
            enclosing = enclosing or LexicalScopeIndex.find_enclosing_class(decls, token.line)
            return ChainResolution(enclosing) if enclosing else None
        variable_type = self.resolve_variable_type(
            root, decls, class_table, token.line, result=result if use_scope_map else None, cursor_col=token.col
        )
        if variable_type is not None:
            return ChainResolution(variable_type)
        return ChainResolution(root, direct_type_reference=True) if root in class_table else None

    def resolve_chain_type(
        self,
        result: DocumentAnalysis,
        tokens: list[Token],
        end_idx: int,
        class_table: dict[str, ClassInfo],
        decls: list | None = None,
    ) -> str | None:
        """Resolve a chain to its resulting type name."""
        resolved = self.resolve_chain(result, tokens, end_idx, class_table, decls)
        return resolved.type_name if resolved else None

    def _is_chain_identifier(self, token: Token) -> bool:
        return token.type in (TokenKind.IDENT, TokenKind.SELF)

    def _chain_segment(self, tokens: list[Token], index: int) -> tuple[int | None, bool]:
        if index < 0 or index >= len(tokens):
            return (None, False)
        if tokens[index].value != ")":
            return (index, False)
        return (self._skip_call_to_callee(tokens, index), True)

    def _skip_call_to_callee(self, tokens: list[Token], index: int) -> int | None:
        if index < 0 or index >= len(tokens):
            return None
        if tokens[index].value != ")":
            return index
        depth = 1
        index -= 1
        while index >= 0:
            if tokens[index].value == ")":
                depth += 1
            elif tokens[index].value == "(":
                depth -= 1
                if depth == 0:
                    return index - 1 if index > 0 else None
            index -= 1
        return None

    def resolve_member_type(
        self,
        owner_type: str,
        member_name: str,
        class_table: dict[str, ClassInfo],
        *,
        prefer_method: bool = False,
        static_access: bool | None = None,
    ) -> str | None:
        """Resolve the base type of a field or method result."""
        class_name = owner_type
        while class_name and class_name in class_table:
            info = class_table[class_name]
            if prefer_method:
                found, result = self._method_return_type(info, member_name, static_access)
                if found:
                    return result
            field = info.fields.get(member_name)
            if isinstance(field, FieldDecl) and field.type:
                if static_access is not None and (field.access == "class") != static_access:
                    return None
                return field.type.base
            prop = info.properties.get(member_name)
            if isinstance(prop, PropertyDecl) and prop.type:
                if static_access is not None and (prop.access == "class") != static_access:
                    return None
                return prop.type.base
            if not prefer_method:
                found, result = self._method_return_type(info, member_name, static_access)
                if found:
                    return result
            class_name = info.parent
        if static_access:
            return None
        member = self.catalog.member(owner_type, member_name)
        return self.catalog.base_type_name(member.return_type) if member else None

    def _method_return_type(self, info: ClassInfo, name: str, static_access: bool | None) -> tuple[bool, str | None]:
        method = info.methods.get(name)
        if isinstance(method, MethodDecl) and method.return_type:
            if static_access is not None and (method.access == "class") != static_access:
                return (True, None)
            return (True, method.return_type.base)
        return (False, None)

    def resolve_variable_type(
        self,
        name: str,
        ast: object,
        class_table: dict[str, ClassInfo],
        cursor_line: int | None = None,
        result: DocumentAnalysis | None = None,
        cursor_col: int | None = None,
    ) -> str | None:
        """Resolve a variable's base type at an optional source position."""
        if result is not None and cursor_line is not None:
            scope = LexicalScopeIndex.from_analysis(result, self)
            definition = scope.visible(name, cursor_line, cursor_col if cursor_col is not None else 10**9)
            if definition is not None:
                return self._vardef_type_name(definition, class_table)
            for decl in LexicalScopeIndex.decl_list(ast):
                if isinstance(decl, VarDeclStmt) and decl.name == name:
                    type_name = self._var_decl_type(decl, class_table)
                    if type_name:
                        return type_name
            return None
        candidates: list[tuple[int, str]] = []
        for decl in LexicalScopeIndex.decl_list(ast):
            self._scan_for_var_types(name, decl, class_table, candidates)
        if cursor_line is not None:
            candidates = [candidate for candidate in candidates if candidate[0] <= cursor_line]
        return max(candidates, default=(0, None), key=lambda candidate: candidate[0])[1]

    def _vardef_type_name(self, definition, class_table: dict[str, ClassInfo]) -> str | None:
        node = definition.node
        if isinstance(node, VarDeclStmt):
            return self._var_decl_type(node, class_table)
        if isinstance(node, Param):
            if node.type and self._known_type(node.type.base, class_table):
                return node.type.base
            return None
        if definition.kind == "catch":
            return "string"
        return None

    def _known_type(self, type_name: str, class_table: dict[str, ClassInfo]) -> bool:
        return type_name in class_table or type_name in _PRIMITIVE_TYPES or type_name in self.catalog.type_names

    def _scan_for_var_types(
        self, var_name: str, node, class_table: dict[str, ClassInfo], candidates: list[tuple[int, str]]
    ) -> None:
        if isinstance(node, VarDeclStmt):
            if node.name == var_name:
                type_name = self._var_decl_type(node, class_table)
                if type_name:
                    candidates.append((node.line, type_name))
            return
        if isinstance(node, ClassDecl):
            for member in node.members:
                self._scan_for_var_types(var_name, member, class_table, candidates)
            return
        if isinstance(node, (FunctionDecl, MethodDecl)):
            for param in node.params:
                if param.name == var_name and param.type and self._known_type(param.type.base, class_table):
                    candidates.append((param.line, param.type.base))
            if node.body:
                for statement in node.body.statements:
                    self._scan_for_var_types(var_name, statement, class_table, candidates)
            return
        for attr_name in ("then_block", "else_block", "body", "try_block", "catch_block"):
            child = getattr(node, attr_name, None)
            if child is None:
                continue
            if isinstance(child, ElseBlock) and child.body:
                child = child.body
            elif isinstance(child, ElseIf) and child.if_stmt:
                self._scan_for_var_types(var_name, child.if_stmt, class_table, candidates)
                continue
            for statement in getattr(child, "statements", []):
                self._scan_for_var_types(var_name, statement, class_table, candidates)

    def _var_decl_type(self, node: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str | None:
        if node.type and self._known_type(node.type.base, class_table):
            return node.type.base
        if isinstance(node.initializer, CallExpr):
            callee = node.initializer.callee
            if isinstance(callee, Identifier) and callee.name in class_table:
                return callee.name
        if isinstance(node.initializer, NewExpr):
            type_expr = node.initializer.type
            if type_expr and self._known_type(type_expr.base, class_table):
                return type_expr.base
        return None
