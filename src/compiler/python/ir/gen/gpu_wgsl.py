"""Statement and control-flow lowering for btrc GPU bodies to WGSL."""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BreakStmt,
    CallExpr,
    CForStmt,
    ContinueStmt,
    ExprStmt,
    ForInitExpr,
    ForInitVar,
    Identifier,
    IfStmt,
    ReturnStmt,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from .errors import unsupported_node
from .gpu_wgsl_exprs import WgslExpressionsMixin
from .gpu_wgsl_types import (
    btrc_type_to_wgsl,
    btrc_type_to_wgsl_elem,
    scalar_type,
)

__all__ = ["WgslEmitter", "btrc_type_to_wgsl", "btrc_type_to_wgsl_elem"]


class WgslEmitter(WgslExpressionsMixin):
    """Emit the analyzed GPU-compatible AST subset as WGSL statements."""

    def __init__(
        self,
        array_params: list[str] | dict[str, str],
        has_output: bool = True,
        uniform_params: list[str] | dict[str, str] | None = None,
        bool_uniform_params: list[str] | None = None,
        array_lengths: dict[str, str] | None = None,
        node_types: dict[int, object] | None = None,
        output_type=None,
    ):
        self._indent = 1
        self._lines: list[str] = []
        self._array_params = _name_map(array_params)
        self._uniform_params = _name_map(uniform_params or [])
        self._bool_uniform_params = set(bool_uniform_params or [])
        self._array_lengths = dict(array_lengths or {})
        self._has_output = has_output
        self._output_type = output_type
        self._node_types = node_types or {}
        self._name_scopes = [{**self._array_params, **self._uniform_params}]
        self._next_local = 0
        self._next_value = 0

    def emit_block(self, block) -> str:
        if block is None:
            return ""
        self._push_name_scope()
        self._emit_block_contents(block)
        self._pop_name_scope()
        return "\n".join(self._lines)

    def _line(self, text: str) -> None:
        self._lines.append("    " * self._indent + text)

    def _emit_block_contents(self, block) -> None:
        for statement in block.statements:
            self._emit_stmt(statement)

    def _emit_scoped_contents(self, block) -> None:
        self._push_name_scope()
        self._emit_block_contents(block)
        self._pop_name_scope()

    def _emit_stmt(self, statement) -> None:
        if isinstance(statement, VarDeclStmt):
            self._emit_var_decl(statement)
        elif isinstance(statement, ReturnStmt):
            self._emit_return(statement)
        elif isinstance(statement, IfStmt):
            self._emit_if(statement)
        elif isinstance(statement, WhileStmt):
            self._emit_while(statement)
        elif isinstance(statement, CForStmt):
            self._emit_for(statement)
        elif isinstance(statement, ExprStmt):
            self._emit_expression_statement(statement.expr)
        elif isinstance(statement, BreakStmt):
            self._line("break;")
        elif isinstance(statement, ContinueStmt):
            self._line("continue;")
        else:
            raise unsupported_node("WGSL statement", statement)

    def _emit_var_decl(self, statement: VarDeclStmt) -> None:
        initializer = None
        if statement.initializer is not None:
            initializer = self._coerced_expr(statement.initializer, statement.type)
        name = self._declare_name(statement.name)
        declaration = f"var {name}: {scalar_type(statement.type)}"
        if initializer is not None:
            declaration += f" = {initializer}"
        self._line(declaration + ";")

    def _emit_return(self, statement: ReturnStmt) -> None:
        if statement.value is not None and self._has_output:
            value_type = self._type_of(statement.value)
            if value_type is not None and value_type.is_array:
                if not isinstance(statement.value, Identifier):
                    raise unsupported_node("WGSL array return", statement.value)
                value = self._checked_array_access(statement.value.name, "btrc_gid")
                value_type = _array_element_type(value_type)
            else:
                value = self._expr(statement.value)
            value = self._coerce_text(value, value_type, self._output_type)
            self._line(f"_output[btrc_gid] = {value};")
        self._line("return;")

    def _emit_if(self, statement: IfStmt) -> None:
        condition = self._expr(statement.condition)
        self._line(f"if ({condition}) {{")
        self._indent += 1
        self._emit_scoped_contents(statement.then_block)
        self._indent -= 1
        if statement.else_block and hasattr(statement.else_block, "body"):
            self._line("} else {")
            self._indent += 1
            self._emit_scoped_contents(statement.else_block.body)
            self._indent -= 1
            self._line("}")
        elif statement.else_block and hasattr(statement.else_block, "if_stmt"):
            self._line("} else {")
            self._indent += 1
            self._push_name_scope()
            self._emit_if(statement.else_block.if_stmt)
            self._pop_name_scope()
            self._indent -= 1
            self._line("}")
        else:
            self._line("}")

    def _emit_while(self, statement: WhileStmt) -> None:
        self._line("loop {")
        self._indent += 1
        self._push_name_scope()
        condition = self._expr(statement.condition)
        self._line(f"if (!({condition})) {{ break; }}")
        self._emit_scoped_contents(statement.body)
        self._pop_name_scope()
        self._indent -= 1
        self._line("}")

    def _emit_for(self, statement: CForStmt) -> None:
        self._line("{")
        self._indent += 1
        self._push_name_scope()
        if isinstance(statement.init, ForInitVar):
            self._emit_var_decl(statement.init.var_decl)
        elif isinstance(statement.init, ForInitExpr):
            self._emit_expression_statement(statement.init.expression)
        self._line("loop {")
        self._indent += 1
        self._push_name_scope()
        if statement.condition is not None:
            condition = self._expr(statement.condition)
            self._line(f"if (!({condition})) {{ break; }}")
        self._emit_scoped_contents(statement.body)
        if statement.update is not None:
            self._line("continuing {")
            self._indent += 1
            self._emit_expression_statement(statement.update)
            self._indent -= 1
            self._line("}")
        self._pop_name_scope()
        self._indent -= 1
        self._line("}")
        self._pop_name_scope()
        self._indent -= 1
        self._line("}")

    def _emit_expression_statement(self, expression) -> None:
        if not isinstance(expression, (AssignExpr, CallExpr)) and not (
            isinstance(expression, UnaryExpr) and expression.op in ("++", "--")
        ):
            raise unsupported_node("WGSL expression statement", expression)
        rendered = self._expr(expression)
        if isinstance(expression, CallExpr):
            self._line(f"_ = {rendered};")
        else:
            self._line(f"{rendered};")

    def _type_of(self, expression):
        return self._node_types.get(id(expression))

    def _lookup_name(self, source_name: str) -> str:
        for scope in reversed(self._name_scopes):
            if source_name in scope:
                return scope[source_name]
        raise unsupported_node("WGSL identifier", source_name)

    def _declare_name(self, source_name: str) -> str:
        name = f"btrc_v_{self._next_local}"
        self._next_local += 1
        self._name_scopes[-1][source_name] = name
        return name

    def _fresh_value_name(self) -> str:
        name = f"btrc_e_{self._next_value}"
        self._next_value += 1
        return name

    def _push_name_scope(self) -> None:
        self._name_scopes.append({})

    def _pop_name_scope(self) -> None:
        self._name_scopes.pop()


def _name_map(names: list[str] | dict[str, str]) -> dict[str, str]:
    return dict(names) if isinstance(names, dict) else {name: name for name in names}


def _array_element_type(type_expr):
    from dataclasses import replace

    return replace(type_expr, is_array=False, array_size=None)
