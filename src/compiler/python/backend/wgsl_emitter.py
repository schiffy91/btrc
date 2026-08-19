"""Statement and control-flow lowering for btrc GPU bodies to WGSL."""

from __future__ import annotations

from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    CForStmt,
    CastExpr,
    ContinueStmt,
    ExprStmt,
    FloatLiteral,
    ForInitExpr,
    ForInitVar,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    NullLiteral,
    ReturnStmt,
    TernaryExpr,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from src.compiler.python.analyzer.gpu import WGSL_CALL_BUILTINS
from src.compiler.python.analyzer.gpu import GPU_STATUS_BOUNDS, GPU_STATUS_DIV_OVERFLOW, GPU_STATUS_DIV_ZERO, GPU_STATUS_MOD_ZERO
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.ir.nodes import IRGpuKernel

_DIRECT_BINARY_OPERATORS = frozenset(
    {
        "+",
        "-",
        "*",
        "/",
        "%",
        "==",
        "!=",
        "<",
        ">",
        "<=",
        ">=",
        "&",
        "|",
        "^",
        "<<",
        ">>",
    }
)


class WgslEmissionError(RuntimeError):
    """The analyzed GPU subset cannot be represented as valid WGSL."""


class WgslEmitter:
    """Emit the analyzed GPU-compatible AST subset as WGSL statements."""

    _TYPE_MAP = {
        "int": "i32",
        "float": "f32",
        "bool": "bool",
    }

    @staticmethod
    def _unsupported_node(phase: str, node: object) -> WgslEmissionError:
        return WgslEmissionError(
            f"unsupported {phase} node: {type(node).__name__}"
        )

    def __init__(
        self,
        array_params: list[str] | dict[str, str],
        has_output: bool = True,
        uniform_params: list[str] | dict[str, str] | None = None,
        bool_uniform_params: list[str] | None = None,
        array_lengths: dict[str, str] | None = None,
        node_types: dict[int, object] | None = None,
        output_type: TypeExpr | None = None,
    ) -> None:
        self._indent = 1
        self._lines: list[str] = []
        self._array_params = self._name_map(array_params)
        self._uniform_params = self._name_map(uniform_params or [])
        self._bool_uniform_params = set(bool_uniform_params or [])
        self._array_lengths = dict(array_lengths or {})
        self._has_output = has_output
        self._output_type = output_type
        self._node_types = node_types or {}
        self._name_scopes = [{**self._array_params, **self._uniform_params}]
        self._next_local = 0
        self._next_value = 0

    @classmethod
    def emit_ir_kernel(cls, kernel: IRGpuKernel) -> str:
        """Materialize one backend-neutral GPU kernel IR value as WGSL."""

        shader = kernel.shader_module
        if shader is None:
            raise WgslEmissionError(
                f"GPU kernel '{kernel.name}' is missing its shader module"
            )
        boolean_uniforms = set(shader.bool_uniform_params)
        uniform_params = [
            (
                name,
                "u32" if name in boolean_uniforms else cls.element_type(type_expr),
            )
            for name, type_expr in kernel.uniform_params
        ]
        return cls.emit_kernel(
            kernel.param_buffers,
            uniform_params,
            shader.bool_uniform_params,
            kernel.output_buffer,
            shader.body,
            kernel.output_buffer is not None,
            shader.node_types,
            shader.output_type,
            kernel.workgroup_size,
        )

    @classmethod
    def emit_kernel(
        cls,
        param_buffers,
        uniform_params: list[tuple[str, str]],
        bool_uniform_params: list[str],
        output_buffer,
        body,
        has_output: bool,
        node_types: dict[int, object],
        output_type,
        workgroup_size: int,
    ) -> str:
        """Emit one complete WGSL compute module from typed kernel metadata."""

        lines: list[str] = []
        source_names = [buffer.name for buffer in param_buffers] + [
            name for name, _ in uniform_params
        ]
        shader_names = {
            source_name: f"btrc_p_{index}"
            for index, source_name in enumerate(source_names)
        }
        array_lengths = {
            buffer.name: f"btrc_len_{index}"
            for index, buffer in enumerate(param_buffers)
        }
        for buffer in param_buffers:
            access = "read_write" if buffer.access == "read_write" else "read"
            lines.append(
                f"@group(0) @binding({buffer.binding}) var<storage, {access}> "
                f"{shader_names[buffer.name]}: "
                f"array<{cls.element_type(buffer.elem_type)}>;"
            )
        if output_buffer:
            lines.append(
                f"@group(0) @binding({output_buffer.binding}) "
                f"var<storage, read_write> _output: "
                f"array<{cls.element_type(output_buffer.elem_type)}>;"
            )

        lines.extend(("", "struct Uniforms {"))
        for name, wgsl_type in uniform_params:
            lines.append(f"    {shader_names[name]}: {wgsl_type},")
        for buffer in param_buffers:
            lines.append(f"    {array_lengths[buffer.name]}: i32,")
        lines.extend(("    btrc_off: i32,", "    btrc_n: i32,", "}"))
        uniform_binding = cls._uniform_binding(param_buffers, output_buffer)
        lines.append(
            f"@group(0) @binding({uniform_binding}) "
            "var<uniform> uniforms: Uniforms;"
        )
        lines.extend(("", "struct BtrcStatus { code: atomic<u32>, }"))
        lines.append(
            f"@group(0) @binding({uniform_binding + 1}) "
            "var<storage, read_write> btrc_status: BtrcStatus;"
        )
        lines.extend(
            (
                "",
                f"@compute @workgroup_size({workgroup_size})",
                "fn main(@builtin(global_invocation_id) gid: vec3<u32>) {",
                "    let btrc_gid: i32 = i32(gid.x) + uniforms.btrc_off;",
                "    if (btrc_gid >= uniforms.btrc_n) { return; }",
            )
        )
        emitter = cls(
            {
                buffer.name: shader_names[buffer.name]
                for buffer in param_buffers
            },
            has_output=has_output,
            uniform_params={
                name: shader_names[name] for name, _ in uniform_params
            },
            bool_uniform_params=bool_uniform_params,
            array_lengths=array_lengths,
            node_types=node_types,
            output_type=output_type,
        )
        body_text = emitter.emit_block(body)
        if body_text:
            lines.append(body_text)
        lines.append("}")
        return "\n".join(lines)

    @classmethod
    def status_binding(cls, param_buffers, output_buffer) -> int:
        """Return the binding reserved for checked-operation status."""

        return cls._uniform_binding(param_buffers, output_buffer) + 1

    @classmethod
    def type_name(cls, type_expr) -> str:
        """Map one btrc type to its complete WGSL spelling."""

        if type_expr is None:
            return "void"
        scalar = cls._scalar_type(type_expr)
        return f"array<{scalar}>" if type_expr.is_array else scalar

    @classmethod
    def element_type(cls, type_expr) -> str:
        """Map one btrc scalar or array element type to WGSL."""

        return cls._scalar_type(type_expr)

    @staticmethod
    def host_type(wgsl_type: str) -> str:
        """Map a host-shareable WGSL scalar to its C storage type."""

        return {
            "f32": "float",
            "i32": "int",
            "u32": "uint32_t",
            "bool": "bool",
        }.get(wgsl_type, "float")

    @classmethod
    def _scalar_type(cls, type_expr) -> str:
        if type_expr is None or type_expr.base not in cls._TYPE_MAP:
            name = "void" if type_expr is None else type_expr.base
            raise WgslEmissionError(
                f"type '{name}' has no WGSL scalar representation"
            )
        return cls._TYPE_MAP[type_expr.base]

    @staticmethod
    def _uniform_binding(param_buffers, output_buffer) -> int:
        if output_buffer:
            return output_buffer.binding + 1
        return param_buffers[-1].binding + 1 if param_buffers else 0

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
            raise self._unsupported_node("WGSL statement", statement)

    def _emit_var_decl(self, statement: VarDeclStmt) -> None:
        initializer = None
        if statement.initializer is not None:
            initializer = self._coerced_expr(statement.initializer, statement.type)
        name = self._declare_name(statement.name)
        declaration = f"var {name}: {self._scalar_type(statement.type)}"
        if initializer is not None:
            declaration += f" = {initializer}"
        self._line(declaration + ";")

    def _emit_return(self, statement: ReturnStmt) -> None:
        if statement.value is not None and self._has_output:
            value_type = self._type_of(statement.value)
            if value_type is not None and value_type.is_array:
                if not isinstance(statement.value, Identifier):
                    raise self._unsupported_node("WGSL array return", statement.value)
                value = self._checked_array_access(statement.value.name, "btrc_gid")
                value_type = self._array_element_type(value_type)
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
            raise self._unsupported_node("WGSL expression statement", expression)
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
        raise self._unsupported_node("WGSL identifier", source_name)

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


    @staticmethod
    def _name_map(names: list[str] | dict[str, str]) -> dict[str, str]:
        return (
            dict(names)
            if isinstance(names, dict)
            else {name: name for name in names}
        )

    @staticmethod
    def _array_element_type(type_expr):
        return TypeSystem.strip_outer_storage(type_expr, array=True)

    def _checked_index_expr(self, expression: IndexExpr) -> str:
        if not isinstance(expression.obj, Identifier):
            raise WgslEmissionError(
                "WGSL checked indexing requires an array parameter"
            )
        return self._checked_array_access(
            expression.obj.name,
            self._expr(expression.index),
        )

    def _checked_array_access(self, source_name: str, index: str) -> str:
        length_field = self._array_lengths.get(source_name)
        if length_field is None:
            raise WgslEmissionError(
                f"WGSL array '{source_name}' has no length metadata"
            )
        array = self._identifier(source_name)
        index_name = self._fresh_value_name()
        valid_name = self._fresh_value_name()
        safe_name = self._fresh_value_name()
        self._line(f"let {index_name}: i32 = {index};")
        self._line(
            f"let {valid_name}: bool = "
            f"({index_name} >= 0 && "
            f"{index_name} < uniforms.{length_field});"
        )
        self._line(f"if (!{valid_name}) {{")
        self._indent += 1
        self._signal_status(GPU_STATUS_BOUNDS)
        self._indent -= 1
        self._line("}")
        self._line(
            f"let {safe_name}: i32 = select(0, {index_name}, {valid_name});"
        )
        return f"{array}[{safe_name}]"

    def _checked_divmod_expr(
        self,
        operator: str,
        left: str,
        right: str,
        result_base: str,
    ) -> str:
        wgsl_type = "f32" if result_base == "float" else "i32"
        zero = "0.0" if result_base == "float" else "0"
        left_name = self._fresh_value_name()
        right_name = self._fresh_value_name()
        result_name = self._fresh_value_name()
        self._line(f"let {left_name}: {wgsl_type} = {left};")
        self._line(f"let {right_name}: {wgsl_type} = {right};")
        self._line(f"var {result_name}: {wgsl_type} = {zero};")
        self._line(f"if ({right_name} == {zero}) {{")
        self._indent += 1
        self._signal_status(
            GPU_STATUS_DIV_ZERO if operator == "/" else GPU_STATUS_MOD_ZERO
        )
        self._indent -= 1
        if result_base == "int":
            self._line(
                f"}} else if ({left_name} == -2147483648 "
                f"&& {right_name} == -1) {{"
            )
            self._indent += 1
            if operator == "/":
                self._signal_status(GPU_STATUS_DIV_OVERFLOW)
            else:
                self._line(f"{result_name} = 0;")
            self._indent -= 1
        self._line("} else {")
        self._indent += 1
        self._line(f"{result_name} = {left_name} {operator} {right_name};")
        self._indent -= 1
        self._line("}")
        return result_name

    def _signal_status(self, code: int) -> None:
        self._line(f"_ = atomicMax(&btrc_status.code, {code}u);")

    def _expr(self, expression) -> str:
        if isinstance(expression, IntLiteral):
            return str(expression.value)
        if isinstance(expression, FloatLiteral):
            raw = expression.raw or str(expression.value)
            if raw.endswith(("f", "F")):
                raw = raw[:-1]
            if "." not in raw and "e" not in raw.lower():
                raw += ".0"
            return raw
        if isinstance(expression, BoolLiteral):
            return "true" if expression.value else "false"
        if isinstance(expression, NullLiteral):
            raise self._unsupported_node("WGSL expression", expression)
        if isinstance(expression, Identifier):
            return self._identifier(expression.name)
        if isinstance(expression, BinaryExpr):
            return self._binary_expr(expression)
        if isinstance(expression, UnaryExpr):
            return self._unary_expr(expression)
        if isinstance(expression, CallExpr):
            return self._call_expr(expression)
        if isinstance(expression, IndexExpr):
            return self._checked_index_expr(expression)
        if isinstance(expression, AssignExpr):
            target = self._expr(expression.target)
            target_type = self._type_of(expression.target)
            value = self._coerced_expr(expression.value, target_type)
            if expression.op in ("/=", "%="):
                checked = self._checked_divmod_expr(
                    expression.op[0],
                    target,
                    value,
                    getattr(target_type, "base", "int"),
                )
                return f"{target} = {checked}"
            if (
                expression.op == "^="
                and getattr(target_type, "base", None) == "bool"
            ):
                return f"{target} = ({target} != {value})"
            if expression.op in ("<<=", ">>="):
                return f"{target} {expression.op} u32({value})"
            return f"{target} {expression.op} {value}"
        if isinstance(expression, TernaryExpr):
            return self._ternary_expr(expression)
        if isinstance(expression, CastExpr):
            return self._cast_expr(expression)
        raise self._unsupported_node("WGSL expression", expression)

    def _identifier(self, name: str) -> str:
        mapped = self._lookup_name(name)
        if name in self._uniform_params:
            field = self._uniform_params[name]
            if name in self._bool_uniform_params:
                return f"(uniforms.{field} != 0u)"
            return f"uniforms.{field}"
        return mapped

    def _binary_expr(self, expression: BinaryExpr) -> str:
        if expression.op in ("&&", "||"):
            return self._short_circuit_expr(expression)
        if expression.op not in _DIRECT_BINARY_OPERATORS:
            raise self._unsupported_node("WGSL binary expression", expression)
        left_type = self._type_of(expression.left)
        right_type = self._type_of(expression.right)
        left = self._expr(expression.left)
        right = self._expr(expression.right)
        if (
            expression.op == "^"
            and left_type is not None
            and left_type.base == "bool"
        ):
            return f"({left} != {right})"
        if self._is_mixed_numeric(left_type, right_type):
            left = self._coerce_text(left, left_type, "float")
            right = self._coerce_text(right, right_type, "float")
        if expression.op in ("/", "%"):
            result_base = (
                "float"
                if "float"
                in {
                    getattr(left_type, "base", None),
                    getattr(right_type, "base", None),
                }
                else "int"
            )
            return self._checked_divmod_expr(
                expression.op,
                left,
                right,
                result_base,
            )
        if expression.op in ("<<", ">>"):
            right = f"u32({right})"
        return f"({left} {expression.op} {right})"

    def _short_circuit_expr(self, expression: BinaryExpr) -> str:
        left = self._expr(expression.left)
        temporary = self._fresh_value_name()
        self._line(f"var {temporary}: bool = {left};")
        condition = temporary if expression.op == "&&" else f"!{temporary}"
        self._line(f"if ({condition}) {{")
        self._indent += 1
        right = self._expr(expression.right)
        self._line(f"{temporary} = {right};")
        self._indent -= 1
        self._line("}")
        return temporary

    def _unary_expr(self, expression: UnaryExpr) -> str:
        operand = self._expr(expression.operand)
        if expression.op in ("++", "--"):
            operand_type = self._type_of(expression.operand)
            if operand_type is not None and operand_type.base == "float":
                operator = "+=" if expression.op == "++" else "-="
                return f"{operand} {operator} 1.0"
            return f"{operand}{expression.op}"
        if expression.op == "+":
            return operand
        if expression.op in ("!", "~", "-"):
            return f"({expression.op}{operand})"
        raise self._unsupported_node("WGSL unary expression", expression)

    def _call_expr(self, expression: CallExpr) -> str:
        if not isinstance(expression.callee, Identifier):
            raise self._unsupported_node(
                "WGSL call expression",
                expression.callee,
            )
        name = expression.callee.name
        if name == "gpu_id":
            return "btrc_gid"
        if name not in WGSL_CALL_BUILTINS:
            raise self._unsupported_node("WGSL call expression", expression)
        if name == "round":
            return self._round_away_from_zero(expression.args[0])
        arguments = ", ".join(
            self._expr(argument) for argument in expression.args
        )
        return f"{name}({arguments})"

    def _round_away_from_zero(self, argument) -> str:
        value = self._expr(argument)
        temporary = self._fresh_value_name()
        self._line(f"let {temporary}: f32 = {value};")
        away = (
            f"select(ceil({temporary} - 0.5), "
            f"floor({temporary} + 0.5), {temporary} >= 0.0)"
        )
        return f"select({away}, {temporary}, {temporary} == 0.0)"

    def _ternary_expr(self, expression: TernaryExpr) -> str:
        result_type = self._type_of(expression)
        temporary = self._fresh_value_name()
        condition = self._expr(expression.condition)
        self._line(f"var {temporary}: {self._scalar_type(result_type)};")
        self._line(f"if ({condition}) {{")
        self._indent += 1
        true_value = self._coerced_expr(expression.true_expr, result_type)
        self._line(f"{temporary} = {true_value};")
        self._indent -= 1
        self._line("} else {")
        self._indent += 1
        false_value = self._coerced_expr(expression.false_expr, result_type)
        self._line(f"{temporary} = {false_value};")
        self._indent -= 1
        self._line("}")
        return temporary

    def _cast_expr(self, expression: CastExpr) -> str:
        inner = self._expr(expression.expr)
        source = self._type_of(expression.expr)
        return self._coerce_text(inner, source, expression.target_type.base)

    def _coerced_expr(self, expression, target_type) -> str:
        return self._coerce_text(
            self._expr(expression),
            self._type_of(expression),
            target_type,
        )

    def _coerce_text(self, text: str, source_type, target_type) -> str:
        source = getattr(source_type, "base", source_type)
        target = getattr(target_type, "base", target_type)
        if source is None or target is None or source == target:
            return text
        if source == "bool" and target == "int":
            return f"select(0, 1, {text})"
        if source == "bool" and target == "float":
            return f"select(0.0, 1.0, {text})"
        if target == "bool" and source == "int":
            return f"({text} != 0)"
        if target == "bool" and source == "float":
            return f"({text} != 0.0)"
        if source in ("int", "float") and target in ("int", "float"):
            return f"{self._scalar_type(self._type_with_base(target))}({text})"
        return text

    @staticmethod
    def _is_mixed_numeric(left_type, right_type) -> bool:
        return {
            getattr(left_type, "base", None),
            getattr(right_type, "base", None),
        } == {"int", "float"}

    @staticmethod
    def _type_with_base(base: str) -> TypeExpr:
        return TypeExpr(base=base)
