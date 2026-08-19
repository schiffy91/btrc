"""Signature-context recognition and signature-help publication."""

from __future__ import annotations

import re

from lsprotocol import types as lsp

from src.compiler.python.analyzer.program import ClassInfo
from src.compiler.python.syntax.ast.generated import FunctionDecl, MethodDecl
from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.syntax.tokens import Token, TokenKind
from src.devex.lsp.analysis.document import DocumentAnalysis
from src.devex.lsp.analysis.resolution import SemanticResolver
from src.devex.lsp.catalog.builtins import BuiltinCatalog

_CALLEE_RE = re.compile("((?:new\\s+)?[A-Za-z_]\\w*(?:(?:\\.|->|\\?\\.)[A-Za-z_]\\w*)*)\\s*$")
_ACCESS_VALUES = frozenset({".", "->", "?."})


class SignatureHelpProvider:
    """Signature-context recognition and signature-help publication."""

    def __init__(self, catalog: BuiltinCatalog, resolver: SemanticResolver) -> None:
        self.catalog = catalog
        self.resolver = resolver

    def _source_prefix(self, source: str, position: lsp.Position) -> str | None:
        lines = source.split("\n")
        if position.line < 0 or position.line >= len(lines):
            return None
        return "\n".join(lines[: position.line] + [lines[position.line][: position.character]])

    def _mask_literals_and_comments(self, text: str) -> str:
        """Replace non-code characters with spaces while retaining offsets."""
        chars = list(text)
        index = 0
        quote: str | None = None
        escaped = False
        line_comment = False
        block_comment = False
        while index < len(chars):
            char = chars[index]
            next_char = chars[index + 1] if index + 1 < len(chars) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
                else:
                    chars[index] = " "
                index += 1
                continue
            if block_comment:
                chars[index] = "\n" if char == "\n" else " "
                if char == "*" and next_char == "/":
                    chars[index + 1] = " "
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                chars[index] = "\n" if char == "\n" else " "
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char == "/" and next_char == "/":
                chars[index] = chars[index + 1] = " "
                line_comment = True
                index += 2
            elif char == "/" and next_char == "*":
                chars[index] = chars[index + 1] = " "
                block_comment = True
                index += 2
            elif char in ('"', "'"):
                chars[index] = " "
                quote = char
                index += 1
            else:
                index += 1
        return "".join(chars)

    def _unmatched_open_parens(self, text: str) -> list[int]:
        stack: list[int] = []
        for index, char in enumerate(text):
            if char == "(":
                stack.append(index)
            elif char == ")" and stack:
                stack.pop()
        return stack

    def _raw_call(self, text: str) -> tuple[str, int] | None:
        for open_index in reversed(self._unmatched_open_parens(text)):
            match = _CALLEE_RE.search(text[:open_index])
            if match:
                return (match.group(1).strip(), open_index)
        return None

    def _find_call_context(self, source: str, position: lsp.Position) -> str | None:
        prefix = self._source_prefix(source, position)
        if prefix is None:
            return None
        call = self._raw_call(self._mask_literals_and_comments(prefix))
        return call[0] if call else None

    def _count_active_parameter(self, source: str, position: lsp.Position) -> int:
        """Count argument separators, excluding nested collections and calls."""
        prefix = self._source_prefix(source, position)
        if prefix is None:
            return 0
        masked = self._mask_literals_and_comments(prefix)
        call = self._raw_call(masked)
        if call:
            start = call[1] + 1
        else:
            opens = self._unmatched_open_parens(masked)
            start = opens[-1] + 1 if opens else 0
        paren = bracket = brace = commas = 0
        for char in masked[start:]:
            if char == "(":
                paren += 1
            elif char == ")" and paren:
                paren -= 1
            elif char == "[":
                bracket += 1
            elif char == "]" and bracket:
                bracket -= 1
            elif char == "{":
                brace += 1
            elif char == "}" and brace:
                brace -= 1
            elif char == "," and paren == bracket == brace == 0:
                commas += 1
        return commas

    def _before_cursor(self, token: Token, position: lsp.Position) -> bool:
        token_line = token.line - 1
        token_col = token.col - 1
        return token_line < position.line or (token_line == position.line and token_col < position.character)

    def _call_site(self, tokens: list[Token] | None, position: lsp.Position) -> tuple[int, int] | None:
        """Return the innermost unmatched callable (open-paren, callee) indices."""
        if not tokens:
            return None
        stack: list[int] = []
        for index, token in enumerate(tokens):
            if not self._before_cursor(token, position):
                continue
            if token.value == "(":
                stack.append(index)
            elif token.value == ")" and stack:
                stack.pop()
        for open_index in reversed(stack):
            callee_index = open_index - 1
            if callee_index >= 0 and tokens[callee_index].type in (TokenKind.IDENT, TokenKind.SELF):
                return (open_index, callee_index)
        return None

    def _active_call_callee_index(self, tokens: list[Token] | None, position: lsp.Position) -> int | None:
        site = self._call_site(tokens, position)
        return site[1] if site else None

    def _active_parameter_from_tokens(self, tokens: list[Token], open_index: int, position: lsp.Position) -> int:
        paren = bracket = brace = commas = 0
        for token in tokens[open_index + 1 :]:
            if not self._before_cursor(token, position):
                continue
            value = token.value
            if value == "(":
                paren += 1
            elif value == ")" and paren:
                paren -= 1
            elif value == "[":
                bracket += 1
            elif value == "]" and bracket:
                bracket -= 1
            elif value == "{":
                brace += 1
            elif value == "}" and brace:
                brace -= 1
            elif value == "," and paren == bracket == brace == 0:
                commas += 1
        return commas

    def _tokens_for_position(self, result: DocumentAnalysis, position: lsp.Position) -> list[Token] | None:
        """Use snapshot navigation tokens or re-lex a changed live line."""
        if not result.line_changed_since_snapshot(position.line):
            return self.resolver.nav_tokens(result) if result.tokens is not None else None
        lines = result.source.split("\n")
        if not 0 <= position.line < len(lines):
            return None
        try:
            line_tokens = Lexer(lines[position.line], "<live-line>").tokenize()
        except LexerError:
            return None
        expanded = self.resolver.navigation_tokens([token for token in line_tokens if token.type != TokenKind.EOF])
        return [Token(token.type, token.value, position.line + token.line, token.col) for token in expanded]

    def _make_param_info(self, ptype: str, pname: str) -> lsp.ParameterInformation:
        return lsp.ParameterInformation(label=f"{ptype} {pname}", documentation=None)

    def _make_signature(
        self, label: str, params: list[lsp.ParameterInformation], active_param: int, documentation: str | None = None
    ) -> lsp.SignatureHelp:
        active = min(active_param, max(0, len(params) - 1)) if params else 0
        signature = lsp.SignatureInformation(
            label=label, parameters=params, documentation=documentation, active_parameter=active
        )
        return lsp.SignatureHelp(signatures=[signature], active_signature=0, active_parameter=active)

    def _signature_from_param_list(
        self,
        func_name: str,
        return_type: str,
        param_list: list[tuple[str, str]],
        active_param: int,
        context: str | None = None,
    ) -> lsp.SignatureHelp:
        params = ", ".join((f"{ptype} {name}" for ptype, name in param_list))
        label = f"{func_name}({params})"
        if return_type and return_type != "void":
            label = f"{return_type} {label}"
        return self._make_signature(
            label,
            [self._make_param_info(ptype, name) for ptype, name in param_list],
            active_param,
            documentation=context,
        )

    def _signature_from_function_decl(self, decl: FunctionDecl, active_param: int) -> lsp.SignatureHelp:
        params = [(self.resolver.type_repr(param.type), param.name) for param in decl.params]
        return self._signature_from_param_list(
            decl.name, self.resolver.type_repr(decl.return_type), params, active_param
        )

    def _signature_from_method_decl(
        self, class_name: str, method: MethodDecl, active_param: int, is_constructor: bool = False
    ) -> lsp.SignatureHelp:
        params = [(self.resolver.type_repr(param.type), param.name) for param in method.params]
        name = class_name if is_constructor else method.name
        return_type = class_name if is_constructor else self.resolver.type_repr(method.return_type)
        kind = "Constructor" if is_constructor else "Method"
        return self._signature_from_param_list(
            name, return_type, params, active_param, context=f"{kind} of {class_name}"
        )

    def get_signature_help(self, result: DocumentAnalysis, position: lsp.Position) -> lsp.SignatureHelp | None:
        """Compute signature help from lexical call structure, then semantic types."""
        if not result.source:
            return None
        position = result.text.source_position(position)
        class_table = result.analyzed.class_table if result.analyzed else {}
        function_table = result.analyzed.function_table if result.analyzed else {}
        tokens = self._tokens_for_position(result, position)
        site = self._call_site(tokens, position)
        if site is not None:
            open_index, callee_index = site
            active_param = self._active_parameter_from_tokens(tokens, open_index, position)
            return self._resolve_token_call(result, tokens, callee_index, class_table, function_table, active_param)
        if tokens is not None and (not result.line_changed_since_snapshot(position.line)):
            return None
        context = self._find_call_context(result.source, position)
        if context is None:
            return None
        return self._resolve_raw_call(
            context, class_table, function_table, self._count_active_parameter(result.source, position)
        )

    def _resolve_token_call(
        self,
        result: DocumentAnalysis,
        tokens: list[Token],
        callee_index: int,
        class_table: dict[str, ClassInfo],
        function_table: dict[str, FunctionDecl],
        active_param: int,
    ) -> lsp.SignatureHelp | None:
        callee = tokens[callee_index]
        if callee_index >= 2 and tokens[callee_index - 1].value in _ACCESS_VALUES:
            return self._resolve_member_call(result, tokens, callee_index - 2, callee.value, class_table, active_param)
        if callee_index >= 1 and tokens[callee_index - 1].value == "new":
            return self._resolve_constructor(callee.value, class_table, active_param)
        return self._resolve_plain_call(callee.value, class_table, function_table, active_param)

    def _resolve_raw_call(
        self,
        context: str,
        class_table: dict[str, ClassInfo],
        function_table: dict[str, FunctionDecl],
        active_param: int,
    ) -> lsp.SignatureHelp | None:
        new_match = re.fullmatch("new\\s+(\\w+)", context)
        if new_match:
            return self._resolve_constructor(new_match.group(1), class_table, active_param)
        parts = re.split("(?:\\.|->|\\?\\.)", context)
        if len(parts) == 2:
            receiver, method = parts
            if receiver in class_table:
                return self._resolve_method_on_type(receiver, method, class_table, active_param, require_static=True)
            params = self.catalog.static_signature(receiver, method)
            if params is not None:
                return self._signature_from_param_list(
                    f"{receiver}.{method}", "", params, active_param, context=f"Static method of {receiver}"
                )
            return None
        return self._resolve_plain_call(context, class_table, function_table, active_param)

    def _resolve_plain_call(
        self, name: str, class_table: dict[str, ClassInfo], function_table: dict[str, FunctionDecl], active_param: int
    ) -> lsp.SignatureHelp | None:
        if name in class_table:
            return self._resolve_constructor(name, class_table, active_param)
        function = function_table.get(name)
        if function is not None:
            return self._signature_from_function_decl(function, active_param)
        builtin = self.catalog.function_signature(name)
        if builtin:
            return self._signature_from_param_list(
                name, builtin[0], builtin[1], active_param, context="Built-in function"
            )
        return None

    def _resolve_constructor(
        self, class_name: str, class_table: dict[str, ClassInfo], active_param: int
    ) -> lsp.SignatureHelp | None:
        info = class_table.get(class_name)
        if info is None:
            return None
        if isinstance(info.constructor, MethodDecl):
            return self._signature_from_method_decl(class_name, info.constructor, active_param, is_constructor=True)
        return self._signature_from_param_list(
            class_name, class_name, [], active_param, context=f"Constructor of {class_name}"
        )

    def _resolve_member_call(
        self,
        result: DocumentAnalysis,
        tokens: list[Token],
        receiver_end_idx: int,
        method_name: str,
        class_table: dict[str, ClassInfo],
        active_param: int,
    ) -> lsp.SignatureHelp | None:
        receiver = self.resolver.resolve_chain(result, tokens, receiver_end_idx, class_table)
        if receiver is not None:
            signature = self._resolve_method_on_type(
                receiver.type_name,
                method_name,
                class_table,
                active_param,
                require_static=receiver.direct_type_reference,
            )
            if signature is not None:
                return signature
            if receiver.direct_type_reference and receiver.type_name in class_table:
                return None
        receiver_name = self._simple_receiver_name(tokens, receiver_end_idx)
        if receiver_name is None or receiver_name in class_table:
            return None
        params = self.catalog.static_signature(receiver_name, method_name)
        if params is None:
            return None
        return self._signature_from_param_list(
            f"{receiver_name}.{method_name}", "", params, active_param, context=f"Static method of {receiver_name}"
        )

    def _simple_receiver_name(self, tokens: list[Token], index: int) -> str | None:
        if index < 0 or index >= len(tokens) or tokens[index].value == ")":
            return None
        if index >= 2 and tokens[index - 1].value in _ACCESS_VALUES:
            return None
        return tokens[index].value

    def _resolve_method_on_type(
        self,
        type_name: str,
        method_name: str,
        class_table: dict[str, ClassInfo],
        active_param: int,
        *,
        require_static: bool = False,
    ) -> lsp.SignatureHelp | None:
        current = type_name
        while current and current in class_table:
            info = class_table[current]
            method = info.methods.get(method_name)
            if isinstance(method, MethodDecl):
                if (method.access == "class") != require_static:
                    return None
                return self._signature_from_method_decl(current, method, active_param)
            current = info.parent
        if not require_static:
            params = self.catalog.signature_parameters(type_name, method_name)
            if params is not None:
                return self._signature_from_param_list(
                    f"{type_name}.{method_name}", "", params, active_param, context=f"Built-in {type_name} method"
                )
        return None
