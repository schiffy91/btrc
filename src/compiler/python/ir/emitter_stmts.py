"""Formatting of structured IR statements."""

from .c_types import qualify_volatile_object
from .nodes import (
    IRAssign,
    IRBlock,
    IRBreak,
    IRContinue,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRGlobalDecl,
    IRGpuKernel,
    IRIf,
    IRLineMarker,
    IRReturn,
    IRStmt,
    IRSwitch,
    IRVarDecl,
    IRWhile,
)

_volatile_type = qualify_volatile_object


def _qualified_decl_type(decl: IRVarDecl) -> str:
    """Format a local declaration's storage and volatile qualifiers."""

    if decl.is_static and decl.is_extern:
        raise ValueError(f"IR variable {decl.name!r} is both static and extern")
    storage = "static " if decl.is_static else "extern " if decl.is_extern else ""
    return storage + _volatile_type(str(decl.c_type), decl.is_volatile)


def _qualified_global_type(decl: IRGlobalDecl) -> str:
    if decl.is_static and decl.is_extern:
        raise ValueError(f"IR global {decl.name!r} is both static and extern")
    storage = "static " if decl.is_static else "extern " if decl.is_extern else ""
    return storage + _volatile_type(str(decl.c_type), decl.is_volatile)


class _StmtEmitterMixin:
    def _emit_global_decl(self, decl: IRGlobalDecl):
        suffix = f"[{self._expr(decl.array_size)}]" if decl.array_size is not None else ""
        initializer = f" = {self._expr(decl.init)}" if decl.init else ""
        self._line(f"{_qualified_global_type(decl)} {decl.name}{suffix}{initializer};")

    def _emit_block_contents(self, block):
        for stmt in block.stmts:
            self._emit_stmt(stmt)

    def _emit_stmt(self, stmt: IRStmt):
        if isinstance(stmt, IRLineMarker):
            self._dbg_loc = (stmt.file, stmt.line)
            return

        if isinstance(stmt, IRVarDecl):
            c_type = _qualified_decl_type(stmt)
            array = (
                f"[{self._expr(stmt.array_size)}]"
                if stmt.array_size is not None
                else "[]"
                if stmt.is_unsized_array
                else ""
            )
            initializer = f" = {self._expr(stmt.init)}" if stmt.init else ""
            self._line(f"{c_type} {stmt.name}{array}{initializer};")
        elif isinstance(stmt, IRAssign):
            self._line(f"{self._expr(stmt.target)} = {self._expr(stmt.value)};")
        elif isinstance(stmt, IRReturn):
            value = f" {self._expr(stmt.value)}" if stmt.value else ""
            self._line(f"return{value};")
        elif isinstance(stmt, IRBlock):
            self._line("{")
            self._indent += 1
            self._emit_block_contents(stmt)
            self._indent -= 1
            self._line("}")
        elif isinstance(stmt, IRIf):
            self._line(f"if ({self._cond_expr(stmt.condition)}) {{")
            if stmt.then_block:
                self._indent += 1
                self._emit_block_contents(stmt.then_block)
                self._indent -= 1
            self._emit_else_tail(stmt)
        elif isinstance(stmt, IRWhile):
            self._line(f"while ({self._cond_expr(stmt.condition)}) {{")
            if stmt.body:
                self._indent += 1
                self._emit_block_contents(stmt.body)
                self._indent -= 1
            self._line("}")
        elif isinstance(stmt, IRDoWhile):
            condition = self._cond_expr(stmt.condition)
            self._line("do {")
            if stmt.body:
                self._indent += 1
                self._emit_block_contents(stmt.body)
                self._indent -= 1
            self._line(f"}} while ({condition});")
        elif isinstance(stmt, IRFor):
            init_text = self._for_init_text(stmt.init)
            cond_text = self._expr(stmt.condition) if stmt.condition else ""
            update_text = self._expr(stmt.update) if stmt.update else ""
            self._line(f"for ({init_text}; {cond_text}; {update_text}) {{")
            if stmt.body:
                self._indent += 1
                self._emit_block_contents(stmt.body)
                self._indent -= 1
            self._line("}")
        elif isinstance(stmt, IRSwitch):
            self._line(f"switch ({self._expr(stmt.value)}) {{")
            self._indent += 1
            for index, case in enumerate(stmt.cases):
                label = f"case {self._expr(case.value)}:" if case.value else "default:"
                self._line(label)
                self._line("{")
                self._indent += 1
                for child in case.body:
                    self._emit_stmt(child)
                self._indent -= 1
                self._line("}")
                if case.falls_through and index + 1 < len(stmt.cases):
                    self._line("/* fall through */")
            self._indent -= 1
            self._line("}")
        elif isinstance(stmt, IRExprStmt):
            self._line(f"{self._discarded_expr(stmt.expr)};")
        elif isinstance(stmt, IRBreak):
            self._line("break;")
        elif isinstance(stmt, IRContinue):
            self._line("continue;")
        elif isinstance(stmt, IRGpuKernel):
            self._emit_gpu_kernel(stmt)
        else:
            raise TypeError(f"unsupported IR statement: {type(stmt).__name__}")

    def _for_init_text(self, init) -> str:
        if isinstance(init, IRVarDecl):
            c_type = _qualified_decl_type(init)
            array = (
                f"[{self._expr(init.array_size)}]"
                if init.array_size is not None
                else "[]"
                if init.is_unsized_array
                else ""
            )
            initializer = f" = {self._expr(init.init)}" if init.init else ""
            return f"{c_type} {init.name}{array}{initializer}"
        if isinstance(init, IRAssign):
            return f"{self._expr(init.target)} = {self._expr(init.value)}"
        if isinstance(init, IRExprStmt):
            return self._discarded_expr(init.expr)
        if init is None:
            return ""
        raise TypeError(f"unsupported IR for-loop initializer: {type(init).__name__}")

    def _emit_else_tail(self, stmt: IRIf):
        if not stmt.else_block or not stmt.else_block.stmts:
            self._line("}")
            return
        self._line("} else {")
        self._indent += 1
        self._emit_block_contents(stmt.else_block)
        self._indent -= 1
        self._line("}")
