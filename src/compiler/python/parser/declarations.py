"""Top-level dispatch, preprocessor, and import declaration parsing."""

from ..ast_nodes import (
    ImportDecl,
    PackagePath,
    PreprocessorDirective,
    QuotedPath,
    RelativePath,
    StdGlob,
    StdModules,
)
from ..tokens import TokenType
from .core import ParseError


class DeclarationsMixin:
    def _parse_top_level_item(self):
        tok = self._peek()
        if tok.type == TokenType.PREPROCESSOR:
            return self._parse_preprocessor()
        if tok.type == TokenType.IMPORT:
            return self._parse_import_decl()

        is_gpu = False
        keep_return = False
        if tok.type == TokenType.AT_GPU:
            is_gpu = True
            self._advance()
            tok = self._peek()
        if tok.type == TokenType.KEEP:
            keep_return = True
            self._advance()
            tok = self._peek()

        if tok.type == TokenType.INTERFACE and not is_gpu and not keep_return:
            return self._parse_interface_decl()
        if tok.type == TokenType.ABSTRACT and not is_gpu and not keep_return:
            if self._peek(1).type == TokenType.CLASS:
                return self._parse_class_decl(is_abstract=True)
        if tok.type == TokenType.CLASS and not is_gpu and not keep_return:
            if self._peek(1).type == TokenType.IDENT:
                after = self._peek(2)
                if after.type in (
                    TokenType.LBRACE,
                    TokenType.LT,
                    TokenType.EXTENDS,
                    TokenType.IMPLEMENTS,
                ):
                    return self._parse_class_decl()
        if tok.type == TokenType.STRUCT and not is_gpu and not keep_return:
            next_tok = self._peek(1)
            if next_tok.type == TokenType.IDENT:
                if self._peek(2).type in (TokenType.LBRACE, TokenType.SEMICOLON):
                    return self._parse_struct_decl()
            elif next_tok.type == TokenType.LBRACE:
                return self._parse_struct_decl()
        if tok.type == TokenType.ENUM and not is_gpu and not keep_return:
            if self._peek(1).type == TokenType.CLASS:
                return self._parse_rich_enum_decl()
            return self._parse_enum_decl()
        if tok.type == TokenType.TYPEDEF and not is_gpu and not keep_return:
            return self._parse_typedef_decl()
        if self._is_type_start(tok):
            return self._parse_function_or_var_decl(is_gpu, keep_return=keep_return)
        raise self._error(f"Unexpected token '{tok.value}' at top level")

    def _parse_preprocessor(self) -> PreprocessorDirective:
        tok = self._advance()
        return PreprocessorDirective(text=tok.value, line=tok.line, col=tok.col)

    def _parse_import_decl(self) -> ImportDecl:
        """Parse an import that owns its complete source line."""
        prev = self.tokens[self.pos - 1] if self.pos > 0 else None
        tok = self._expect(TokenType.IMPORT)
        if prev is not None and prev.line == tok.line:
            raise ParseError(
                "import must be the first token on its line "
                "(an import sharing a line with other code is never resolved)",
                tok.line,
                tok.col,
            )
        spec = self._parse_import_spec()
        end = self._match(TokenType.SEMICOLON)
        end_tok = end if end is not None else self.tokens[self.pos - 1]
        next_token = self._peek()
        if next_token.type != TokenType.EOF and next_token.line == end_tok.line:
            raise ParseError(
                "import must be the only statement on its line "
                "(an import sharing a line with other code is never resolved)",
                next_token.line,
                next_token.col,
            )
        return ImportDecl(spec=spec, line=tok.line, col=tok.col)

    def _parse_import_spec(self):
        if self._check(TokenType.PATH_SPEC):
            return RelativePath(path=self._advance().value)
        if self._check(TokenType.STRING_LIT):
            raw = self._advance().value
            if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
                raw = raw[1:-1]
            return QuotedPath(path=raw)

        ident = self._expect(TokenType.IDENT, "import path")
        if ident.value == "std" and self._match(TokenType.DOT):
            return self._parse_std_spec()
        segments = [ident.value]
        while self._match(TokenType.DOT):
            segments.append(self._expect(TokenType.IDENT, "package segment").value)
        return PackagePath(segments=segments)

    def _parse_std_spec(self):
        if self._match(TokenType.STAR):
            return StdGlob(recursive=bool(self._match(TokenType.STAR)))
        if self._match(TokenType.LBRACE):
            names = [self._expect(TokenType.IDENT, "module name").value]
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break
                names.append(self._expect(TokenType.IDENT, "module name").value)
            self._expect(TokenType.RBRACE)
            return StdModules(names=names)
        return StdModules(names=[self._expect(TokenType.IDENT, "module name").value])
