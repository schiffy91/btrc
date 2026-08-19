"""Cohesive functions IR lowering owner."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCast,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionRef,
    IRParam,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    Block,
    FunctionDecl,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    ReturnStmt,
)

from .calls import (
    CallableProvenance,
    CallableReturnABI,
    CallableSignatureLowerer,
    CallLowerer,
    DefaultArgumentLoweringContext,
    GenericDefaultHelperPlan,
)
from .ownership import OwnershipLowerer
from .types import CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .concurrency import ConcurrencyLowerer
    from .exceptions import ExceptionLowerer
    from .expressions import ExpressionLowerer
    from .gpu import GpuLowerer
    from .session import LoweringSession
    from .statements import StatementLowerer


class FunctionLowerer:
    """Own functions lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        signatures: CallableSignatureLowerer,
        default_context: DefaultArgumentLoweringContext,
        expressions: ExpressionLowerer,
        statements: StatementLowerer,
        ownership: OwnershipLowerer,
        exceptions: ExceptionLowerer,
        concurrency: ConcurrencyLowerer,
        gpu: GpuLowerer,
        calls: CallLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._signatures = signatures
        self._default_arguments = default_context
        self._expressions = expressions
        self._statements = statements
        self._ownership = ownership
        self._exceptions = exceptions
        self._concurrency = concurrency
        self._gpu = gpu
        self._calls = calls
        self._emitted_gpu_functions: set[str] = set()
        self._last_lambda_id = 0
        self._normalizing_void_main = False

    def lower_declaration(self, declaration):
        return self.emit_function_decl(
            declaration,
        )

    def lower_specialization(self, view):
        return self.emit_function_decl(
            view.declaration,
        )

    def materialize_default_helpers(
        self,
        plans: list[GenericDefaultHelperPlan],
    ) -> None:
        """Lower deferred defaults through the ordinary statement stack."""
        while plans:
            plan = plans.pop(0)
            target = plan.target
            parameters = list(plan.parameters)
            parameter = parameters[plan.parameter_index]
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            previous_class = self._session.current_class
            previous_class_name = self._session.current_class_name
            self._session.current_class = self._analyzed.class_table.get(target.owner_name)
            self._session.current_class_name = target.owner_name
            source_file = getattr(target.declaration, "source_file", None) or self._session.source_file
            try:
                with (
                    self.isolated_function_context(self._types.render(parameter.type), parameter.type),
                    self._default_arguments.scope(
                        parameter,
                        True,
                        function_name=target.c_name,
                        source_file=source_file,
                        source_map=self._session.source_map,
                    ),
                ):
                    body = self._statements.lower_block(
                        Block(statements=[ReturnStmt(value=parameter.default)]),
                        provenance,
                        local_bindings=[
                            *(["self"] if target.self_type is not None else []),
                            *(item.name for item in parameters[: plan.parameter_index]),
                        ],
                        callable_bindings=parameters[: plan.parameter_index],
                    )
            finally:
                self._session.current_class = previous_class
                self._session.current_class_name = previous_class_name
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=plan.symbol,
                    return_type=CType(text=self._types.render(parameter.type)),
                    params=list(plan.helper_parameters),
                    body=body,
                    is_static=True,
                )
            )

    def materialize_deferred_functions(
        self,
    ) -> None:
        """Materialize deferred lambdas and thread wrappers through this stack."""
        while self._session.pending_lambdas:
            plan = self._session.pending_lambdas.pop(0)
            self.lower_lambda(
                plan.node,
                function_name=plan.function_name,
                capture_abis=plan.capture_abis,
            )
        while self._session.pending_thread_spawns:
            plan = self._session.pending_thread_spawns.pop(0)
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            body_plan = self._concurrency.plan_spawn_wrapper_body(
                plan,
                provenance,
            )
            with self.isolated_function_context(
                plan.return_c_type,
                plan.return_type,
            ):
                lowered_body = (
                    self._statements.lower_block(
                        body_plan.source,
                        provenance,
                        local_bindings=body_plan.local_bindings,
                        callable_bindings=plan.function.params,
                        callable_abis=body_plan.callable_abis,
                    )
                    if body_plan.source is not None
                    else None
                )
            self._concurrency.materialize_spawn_wrapper(
                plan,
                body_plan,
                lowered_body,
            )

    def emit_function_decl(self, decl: FunctionDecl):
        """Lower a top-level FunctionDecl to an IRFunctionDef or forward decl."""
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        if decl.is_gpu:
            if decl.name in self._emitted_gpu_functions:
                return
            self._gpu.emit_gpu_kernel(decl)
            fallback = self._gpu.plan_gpu_cpu_fallback(decl, provenance)
            if fallback is not None:
                with (
                    self.isolated_function_context(
                        fallback.item_return_c_type,
                        fallback.item_return_type,
                    ),
                    self._gpu.gpu_cpu_item_scope(fallback),
                ):
                    body = self._statements.lower_block(
                        fallback.source,
                        provenance,
                        local_bindings=fallback.local_bindings,
                        callable_bindings=fallback.callable_bindings,
                    )
                self._gpu.materialize_gpu_cpu_fallback(fallback, body)
            self._emitted_gpu_functions.add(decl.name)
            return
        ret_type = self._types.render(decl.return_type) if decl.return_type else "void"
        if decl.name == "main" and ret_type == "void":
            ret_type = "int"
        params = [provenance.lower_source_param(parameter) for parameter in decl.params]
        is_static = bool(decl.return_type and decl.return_type.is_static)
        c_name = provenance.source_function_c_name(decl.name)
        if decl.body is None:
            self._session.module.function_decls.append(
                IRFunctionDecl(name=c_name, return_type=CType(text=ret_type), params=params, is_static=is_static)
            )
            return
        name = decl.name
        self._session.function_declarations = []
        previous_return_type = self._session.current_return_type
        previous_return_c_type = self._session.current_return_c_type
        previous_return_owned = self._session.current_return_owned
        previous_void_main = self._normalizing_void_main
        self._session.current_return_c_type = ret_type
        self._session.current_return_type = decl.return_type
        self._session.current_return_owned = True
        self._normalizing_void_main = bool(name == "main" and decl.return_type.base == "void")
        try:
            body = self._statements.lower_block(
                decl.body,
                provenance,
                local_bindings=[parameter.name for parameter in decl.params],
                callable_bindings=decl.params,
            )
        finally:
            self._normalizing_void_main = previous_void_main
            self._session.current_return_type = previous_return_type
            self._session.current_return_c_type = previous_return_c_type
            self._session.current_return_owned = previous_return_owned
        self._session.module.function_defs.append(
            IRFunctionDef(name=c_name, return_type=CType(text=ret_type), params=params, body=body, is_static=is_static)
        )

    @contextmanager
    def isolated_function_context(self, return_c_type, return_type):
        """Prevent a lambda/thread wrapper from inheriting outer control state."""
        previous_lambda_id = self._last_lambda_id
        previous_void_main = self._normalizing_void_main
        self._last_lambda_id = 0
        self._normalizing_void_main = False
        try:
            with self._ownership.isolated_function_state(return_c_type, return_type):
                yield
        finally:
            self._last_lambda_id = previous_lambda_id
            self._normalizing_void_main = previous_void_main

    def lower_lambda(
        self,
        node: LambdaExpr,
        *,
        function_name: str | None = None,
        capture_abis: tuple[tuple[object, CallableReturnABI], ...] = (),
    ) -> IRFunctionRef:
        """Lower a lambda expression to a static function + capture struct.

        Returns a structured function-name reference for function-pointer use.
        """
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        if function_name is None:
            lambda_id = self._session.fresh_lambda_id()
            fn_name = f"__btrc_lambda_{lambda_id}"
        else:
            fn_name = function_name
            lambda_id = int(function_name.rsplit("_", 1)[-1])
        env_name = f"__btrc_lambda_{lambda_id}_env"
        has_captures = bool(node.captures)
        if has_captures:
            cap_fields = []
            for cap in node.captures:
                c_type = self._types.render(cap.type) if cap.type else "int"
                cap_fields.append(
                    IRStructField(
                        c_type=CType(text=c_type),
                        name=provenance.source_binding_c_name(cap.name),
                        is_volatile=bool(cap.type and cap.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            cap.type, self._analyzed.typedef_table
                        ),
                    )
                )
            self._session.module.struct_defs.append(IRStructDef(name=env_name, fields=cap_fields))
        params = []
        for p in node.params:
            params.append(provenance.lower_source_param(p))
        if has_captures:
            params.append(IRParam(c_type=CType(text="void*"), name="__btrc_env"))
        return_type = self.resolved_lambda_return_type(node)
        ret_type = self._types.render(return_type) if return_type else "void"
        body_stmts = []
        if has_captures:
            body_stmts.append(
                IRVarDecl(
                    c_type=CType(text=f"struct {env_name}*"),
                    name="__env",
                    init=IRCast(target_type=CType(text=f"struct {env_name}*"), expr=IRVar(name="__btrc_env")),
                )
            )
            for cap in node.captures:
                c_type = self._types.render(cap.type) if cap.type else "int"
                body_stmts.append(
                    IRVarDecl(
                        c_type=CType(text=c_type),
                        name=provenance.source_binding_c_name(cap.name),
                        is_volatile=bool(cap.type and cap.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            cap.type, self._analyzed.typedef_table
                        ),
                        init=IRFieldAccess(
                            obj=IRVar(name="__env"),
                            field=provenance.source_binding_c_name(cap.name),
                            arrow=True,
                        ),
                    )
                )
        local_bindings = [param.name for param in node.params]
        local_bindings.extend(capture.name for capture in node.captures)
        with self.isolated_function_context(ret_type, return_type):
            if isinstance(node.body, LambdaBlock) and node.body.body:
                block = self._statements.lower_block(
                    node.body.body,
                    provenance,
                    local_bindings=local_bindings,
                    callable_bindings=node.params,
                    callable_abis=capture_abis,
                )
                body_stmts.extend(block.stmts)
            elif isinstance(node.body, LambdaExprBody) and node.body.expression:
                self._ownership.push_local_ownership_scope()
                enclosing_callables = provenance.begin_scope()
                try:
                    for name in local_bindings:
                        self._ownership.declare_local_ownership(name, provenance)
                        provenance.shadow(name)
                    for parameter in node.params:
                        provenance.bind_borrowed(parameter.name, parameter.type)
                    for capture, return_abi in capture_abis:
                        provenance.bind_with_abi(capture.name, capture.type, return_abi)
                    body_stmts.extend(
                        self._statements.lower_return(
                            ReturnStmt(
                                value=node.body.expression,
                                line=node.body.expression.line,
                                col=node.body.expression.col,
                            ),
                            provenance,
                        )
                    )
                finally:
                    provenance.finish_scope(enclosing_callables)
                    self._ownership.pop_local_ownership_scope()
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=fn_name,
                return_type=CType(text=ret_type),
                params=params,
                body=IRBlock(stmts=body_stmts),
                is_static=True,
            )
        )
        self._last_lambda_id = lambda_id
        return IRFunctionRef(name=fn_name)

    def resolved_lambda_return_type(self, node: LambdaExpr):
        """Return the analyzer-resolved lambda result type, if one is known."""
        if node.return_type:
            return node.return_type
        fn_type = self._analyzed.node_types.get(id(node))
        if fn_type and fn_type.base == "__fn_ptr" and fn_type.generic_args:
            return fn_type.generic_args[0]
        if isinstance(node.body, LambdaExprBody) and node.body.expression:
            return self._analyzed.node_types.get(id(node.body.expression))
        return None
