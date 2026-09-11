"""Cohesive functions IR lowering owner."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.frontend.native_imports import NativeHeaderSource
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCompoundLiteral,
    IRDeref,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRInclude,
    IRInitializerList,
    IRLiteral,
    IRModule,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCExceptionBoundary,
    IRObjectiveCMessage,
    IRParam,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    Block,
    FunctionDecl,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    MethodDecl,
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
    from .generics import SpecializedDeclarationView
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

    @staticmethod
    def _native_null_guard(value, message, realtime=False):
        if realtime:
            return IRIf(
                condition=IRBinOp(left=value, op="==", right=IRLiteral(text="NULL")),
                then_block=IRBlock(
                    stmts=[IRExprStmt(expr=IRCall(callee="__builtin_trap", args=[], never_returns=True))]
                ),
            )
        return IRIf(
            condition=IRBinOp(left=value, op="==", right=IRLiteral(text="NULL")),
            then_block=IRBlock(
                stmts=[
                    IRExprStmt(
                        expr=IRCall(
                            callee="fputs", args=[IRLiteral(text=json.dumps(message + "\n")), IRVar(name="stderr")]
                        )
                    ),
                    IRExprStmt(expr=IRCall(callee="abort", args=[], never_returns=True)),
                ]
            ),
        )

    def emit_native_adapter(self, declaration):
        contract = declaration.source_file.call_contract
        if contract is None:
            return
        name = contract.adapter_symbol(declaration.name)
        if name == declaration.name:
            return
        parameters = [self._signatures.lower_source_param(parameter) for parameter in declaration.params]
        return_type = CType(text=self._types.render(declaration.return_type))
        statements = []
        arguments = [IRVar(name=parameter.name) for parameter in parameters]
        for index, nonnull in enumerate(contract.nonnull_parameters):
            if nonnull:
                statements.append(
                    self._native_null_guard(
                        arguments[index],
                        f"Native call {declaration.name}: null argument {parameters[index].name}",
                        contract.realtime_safe,
                    )
                )
        locals = []
        for index, projection in enumerate(contract.record_inputs):
            if projection is not None:
                arguments[index] = self._native_record_input(
                    projection,
                    arguments[index],
                    locals,
                    statements,
                    declaration.name,
                    parameters[index].name,
                    {parameter.name for parameter in parameters},
                    {record.name: record for record in contract.record_types},
                )
        statements = [*locals, *statements]
        call = IRCall(callee=declaration.name, args=arguments)
        if return_type.text == "void":
            statements.append(IRExprStmt(expr=call))
        elif contract.nonnull_return:
            result = "__btrc_native_result"
            while any(parameter.name == result for parameter in parameters):
                result += "_"
            statements.append(IRVarDecl(c_type=return_type, name=result, init=call))
            statements.append(
                self._native_null_guard(
                    IRVar(name=result), f"Native call {declaration.name}: null result", contract.realtime_safe
                )
            )
            statements.append(IRReturn(value=IRVar(name=result)))
        else:
            statements.append(IRReturn(value=call))
        self._session.module.function_decls.append(
            IRFunctionDecl(name=name, return_type=return_type, params=parameters, is_static=True)
        )
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=name, return_type=return_type, params=parameters, body=IRBlock(stmts=statements), is_static=True
            )
        )

    def _native_record_input(
        self, projection, value, locals, statements, function, path, parameter_names, record_types, prefix=""
    ):
        # Storage is adapter-scoped, including children initialized conditionally.
        # None of these SDK descriptor addresses escape to BTRC caller storage.
        name = f"__btrc_record_input_{len(locals)}"
        while name in parameter_names:
            name += "_"
        native = IRVar(name=name)
        locals.append(
            IRVarDecl(
                c_type=CType(text=projection.native_spelling),
                name=name,
                init=IRInitializerList(elements=[IRLiteral(text="0")]),
            )
        )
        assignments = []
        for field in projection.fields:
            source = IRFieldAccess(obj=value, field=field.name, arrow=True)
            target = IRFieldAccess(obj=native, field=field.name)
            field_path = f"{path}.{field.name}"
            if (field.record or field.object_type) and not field.value_type.is_nullable:
                assignments.append(self._native_null_guard(source, f"Native call {function}: null input {field_path}"))
            if field.record:
                source = self._native_record_input(
                    record_types[field.record],
                    source,
                    locals,
                    assignments,
                    function,
                    field_path,
                    parameter_names,
                    record_types,
                    field.prefix,
                )
            elif field.object_type:
                source = IRCast(target_type=CType(text="void*"), expr=source)
            assignments.append(IRAssign(target=target, value=source))
        statements.append(
            IRIf(
                condition=IRBinOp(left=value, op="!=", right=IRLiteral(text="NULL")),
                then_block=IRBlock(stmts=assignments),
            )
        )
        address = IRAddressOf(expr=IRFieldAccess(obj=native, field=prefix) if prefix else native)
        return IRTernary(
            condition=IRBinOp(left=value, op="==", right=IRLiteral(text="NULL")),
            true_expr=IRLiteral(text="NULL"),
            false_expr=address,
        )

    def _objective_c_unit(self, declaration):
        module = self._session.module
        native = module.native_units.setdefault("ObjectiveCAdapters", IRModule(language="objective-c"))
        for header in declaration.source_file.headers:
            include = IRInclude(header=header, is_system=False)
            if include not in native.preprocessor_decls:
                native.preprocessor_decls.append(include)
        standard = IRInclude(header="stdlib.h")
        if standard not in native.preprocessor_decls:
            native.preprocessor_decls.insert(0, standard)
        records = {
            record.name: record
            for record in self._analyzed.struct_table.values()
            if isinstance(record.source_file, NativeHeaderSource) and record.source_file.language == "objective-c"
        }
        declared = {item.name for item in native.struct_defs}

        def append_record(record):
            name = f"__btrc_value_{record.name}"
            if name in declared:
                return
            declared.add(name)
            # The analyzer has validated by-value layouts. Preserve the same
            # dependency-first order as the self-hosted native declaration owner.
            for field in record.fields:
                if not field.type.pointer_depth and field.type.base in records:
                    append_record(records[field.type.base])
            fields = [
                IRStructField(c_type=CType(text=self._types.render(field.type)), name=field.name)
                for field in record.fields
            ]
            for unit in (module, native):
                unit.struct_forwards.append(IRStructForward(name=name))
                unit.struct_defs.append(IRStructDef(name=name, fields=fields))

        for record in records.values():
            append_record(record)
        return native

    def _objective_c_record(self, value_type):
        if value_type.pointer_depth or value_type.is_array:
            return None
        record = self._analyzed.struct_table.get(value_type.base)
        origin = getattr(record, "source_file", None)
        return record if isinstance(origin, NativeHeaderSource) and origin.language == "objective-c" else None

    def _objective_c_value(self, value_type, value, *, to_native):
        record = self._objective_c_record(value_type)
        if record is None:
            return value
        spelling = record.source_file.type_spelling if to_native else self._types.render(value_type)
        return IRCompoundLiteral(
            c_type=CType(text=spelling),
            fields=[
                (
                    field.name,
                    self._objective_c_value(
                        field.type, IRFieldAccess(obj=value, field=field.name), to_native=to_native
                    ),
                )
                for field in record.fields
            ],
        )

    def emit_objective_c_global(self, declaration):
        """Expose scalar storage; object reads cross ARC as independent owned values."""
        native = self._objective_c_unit(declaration)
        if declaration.name in self._analyzed.native_object_globals:
            self._emit_objective_c_object_global(declaration, native)
            return
        name = f"__btrc_objc_address_{declaration.name}"
        return_type = CType(text=self._types.render(declaration.type) + "*")
        native.function_defs.append(
            IRFunctionDef(
                name=name,
                return_type=return_type,
                params=[],
                body=IRBlock(stmts=[IRReturn(value=IRAddressOf(expr=IRVar(name=declaration.name)))]),
            )
        )
        self._session.module.function_decls.append(IRFunctionDecl(name=name, return_type=return_type, params=[]))

    def _emit_objective_c_object_global(self, declaration, native):
        module = self._session.module
        name = f"__btrc_objc_read_{declaration.name}"
        adapter = f"{name}_adapter"
        result_type = CType(text=self._types.render(declaration.type))
        result = IRVar(name="nativeResult")
        parameters = [IRParam(c_type=CType(text=result_type.text + "*"), name="nativeResult")]
        boundary = IRObjectiveCExceptionBoundary(
            body=IRBlock(
                stmts=[
                    IRAssign(
                        target=IRDeref(expr=result),
                        value=IRCast(target_type=result_type, expr=IRVar(name=declaration.name), bridge="retain"),
                    ),
                    IRReturn(value=IRLiteral(text="0")),
                ]
            ),
            failure=IRBlock(stmts=[IRReturn(value=IRLiteral(text="1"))]),
        )
        native.function_defs.append(
            IRFunctionDef(
                name=adapter,
                return_type=CType(text="int"),
                params=parameters,
                body=IRBlock(stmts=[IRObjectiveCAutoreleasePool(body=IRBlock(stmts=[boundary]))]),
            )
        )
        module.function_decls.append(IRFunctionDecl(name=adapter, return_type=CType(text="int"), params=parameters))
        self._session.require_helper("__btrc_throw")
        statements = [
            IRVarDecl(c_type=result_type, name="nativeResult", init=IRLiteral(text="0")),
            IRIf(
                condition=IRCall(callee=adapter, args=[IRAddressOf(expr=result)]),
                then_block=IRBlock(
                    stmts=[
                        IRExprStmt(
                            expr=IRCall(
                                callee="__btrc_throw",
                                helper_ref="__btrc_throw",
                                never_returns=True,
                                args=[IRLiteral(text=json.dumps(f"Objective-C exception reading {declaration.name}"))],
                            )
                        ),
                    ]
                ),
            ),
        ]
        if not declaration.type.is_nullable:
            statements.append(
                self._objective_c_null_guard(result, f"Objective-C global {declaration.name}: null result")
            )
        statements.append(IRReturn(value=result))
        module.function_decls.append(IRFunctionDecl(name=name, return_type=result_type, params=[], is_static=True))
        module.function_defs.append(
            IRFunctionDef(name=name, return_type=result_type, params=[], is_static=True, body=IRBlock(stmts=statements))
        )

    def emit_objective_c_adapters(self, declaration):
        """Keep ARC/foreign unwinding inside a generated unit; throw only after it returns."""
        module = self._session.module
        native = self._objective_c_unit(declaration)
        for info in self._analyzed.class_table.values():
            if not info.native_language:
                continue
            forward = IRStructForward(name=f"__btrc_native_{info.name}")
            if forward not in native.struct_forwards:
                native.struct_forwards.append(forward)
                module.struct_forwards.append(forward)
        self._emit_objective_c_lifetime(declaration, native)
        for method in declaration.members:
            descriptor = declaration.source_file.methods[method.name]
            name = f"{declaration.name}_{method.name}"
            adapter = f"__btrc_objc_{name}"
            result_type = CType(text=self._types.render(method.return_type))
            parameters = [self._signatures.lower_source_param(parameter) for parameter in method.params]
            arguments = [IRVar(name=parameter.name) for parameter in parameters]
            native_arguments = [
                IRCast(target_type=self._objective_c_object_type(parameter.type.base), expr=argument, bridge="borrow")
                if self._analyzed.class_table.get(parameter.type.base) is not None
                and self._analyzed.class_table[parameter.type.base].native_language
                else self._objective_c_value(parameter.type, argument, to_native=True)
                for parameter, argument in zip(method.params, arguments)
            ]
            receiver = IRVar(name=declaration.name)
            if not descriptor.class_method:
                parameters.insert(
                    0, IRParam(c_type=CType(text=f"struct __btrc_native_{declaration.name}*"), name="self")
                )
                arguments.insert(0, IRVar(name="self"))
                receiver = IRCast(
                    target_type=self._objective_c_object_type(declaration.name),
                    expr=IRVar(name="self"),
                    bridge="borrow",
                )
            result = IRVar(name="nativeResult")
            returns_value = result_type.text != "void"
            adapter_parameters = [
                *parameters,
                *([IRParam(c_type=CType(text=f"{result_type.text}*"), name="nativeResult")] if returns_value else []),
            ]
            call = IRObjectiveCMessage(receiver=receiver, selector=descriptor.selector, args=native_arguments)
            object_return = self._analyzed.class_table.get(method.return_type.base)
            if object_return is not None and object_return.native_language:
                call = IRCast(target_type=result_type, expr=call, bridge="retain")
            body = []
            record_return = self._objective_c_record(method.return_type)
            if record_return is not None:
                body.append(
                    IRVarDecl(c_type=CType(text=record_return.source_file.type_spelling), name="sdkResult", init=call)
                )
                call = self._objective_c_value(method.return_type, IRVar(name="sdkResult"), to_native=False)
            body.extend(
                [
                    IRAssign(target=IRDeref(expr=result), value=call) if returns_value else IRExprStmt(expr=call),
                    IRReturn(value=IRLiteral(text="0")),
                ]
            )
            boundary = IRObjectiveCExceptionBoundary(
                body=IRBlock(stmts=body), failure=IRBlock(stmts=[IRReturn(value=IRLiteral(text="1"))])
            )
            pool = IRObjectiveCAutoreleasePool(body=IRBlock(stmts=[boundary]))
            native.function_defs.append(
                IRFunctionDef(
                    name=adapter,
                    return_type=CType(text="int"),
                    params=adapter_parameters,
                    body=IRBlock(stmts=[pool]),
                )
            )
            module.function_decls.append(
                IRFunctionDecl(name=adapter, return_type=CType(text="int"), params=adapter_parameters)
            )
            self._session.require_helper("__btrc_throw")
            statements = (
                [
                    IRVarDecl(
                        c_type=result_type,
                        name="nativeResult",
                        init=IRInitializerList(elements=[IRLiteral(text="0")])
                        if (
                            method.return_type.base in self._analyzed.struct_table
                            and not method.return_type.pointer_depth
                            and not method.return_type.is_array
                        )
                        else IRLiteral(text="0"),
                    )
                ]
                if returns_value
                else []
            )
            required = [
                parameter.name
                for parameter in method.params
                if parameter.type.pointer_depth > 0 and not parameter.type.is_nullable
            ]
            if not descriptor.class_method:
                required.insert(0, "self")
            for parameter in required:
                statements.append(
                    self._objective_c_null_guard(
                        IRVar(name=parameter), f"Objective-C call {descriptor.name}: null argument {parameter}"
                    )
                )
            statements.append(
                IRIf(
                    condition=IRCall(
                        callee=adapter, args=[*arguments, *([IRAddressOf(expr=result)] if returns_value else [])]
                    ),
                    then_block=IRBlock(
                        stmts=[
                            IRExprStmt(
                                expr=IRCall(
                                    callee="__btrc_throw",
                                    helper_ref="__btrc_throw",
                                    never_returns=True,
                                    args=[IRLiteral(text=json.dumps(f"Objective-C exception in {descriptor.name}"))],
                                )
                            )
                        ]
                    ),
                )
            )
            if returns_value:
                if object_return is not None and object_return.native_language and not method.return_type.is_nullable:
                    statements.append(
                        self._objective_c_null_guard(result, f"Objective-C call {descriptor.name}: null result")
                    )
                statements.append(IRReturn(value=result))
            module.function_decls.append(
                IRFunctionDecl(name=name, return_type=result_type, params=parameters, is_static=True)
            )
            module.function_defs.append(
                IRFunctionDef(
                    name=name,
                    return_type=result_type,
                    params=parameters,
                    is_static=True,
                    body=IRBlock(stmts=statements),
                )
            )

    def _objective_c_null_guard(self, value, message):
        self._session.require_helper("__btrc_throw")
        return IRIf(
            condition=IRBinOp(left=value, op="==", right=IRLiteral(text="NULL")),
            then_block=IRBlock(
                stmts=[
                    IRExprStmt(
                        expr=IRCall(
                            callee="__btrc_throw",
                            helper_ref="__btrc_throw",
                            never_returns=True,
                            args=[IRLiteral(text=json.dumps(message))],
                        )
                    )
                ]
            ),
        )

    @staticmethod
    def _objective_c_object_type(name):
        return CType(text="id" if name == "id" else f"{name}*")

    def _emit_objective_c_lifetime(self, declaration, native):
        """Foreign ownership uses ARC bridges, never BTRC object headers or cycle metadata."""
        for operation in ("retain", "release"):
            name = f"__btrc_objc_{declaration.name}_{operation}"
            parameters = [IRParam(c_type=CType(text="void*"), name="value")]
            value = IRVar(name="value")
            if operation == "retain":
                borrowed = IRCast(
                    target_type=self._objective_c_object_type(declaration.name), expr=value, bridge="borrow"
                )
                owned = IRCast(target_type=CType(text="void*"), expr=borrowed, bridge="retain")
                body = [IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=owned))]
            else:
                body = [
                    IRVarDecl(
                        c_type=self._objective_c_object_type(declaration.name),
                        name="owned",
                        init=IRCast(
                            target_type=self._objective_c_object_type(declaration.name), expr=value, bridge="transfer"
                        ),
                    ),
                    IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="owned"))),
                ]
            failure = IRBlock(stmts=[IRExprStmt(expr=IRCall(callee="abort", args=[], never_returns=True))])
            boundary = IRObjectiveCExceptionBoundary(body=IRBlock(stmts=body), failure=failure)
            pool = IRObjectiveCAutoreleasePool(body=IRBlock(stmts=[boundary]))
            native.function_defs.append(
                IRFunctionDef(name=name, return_type=CType(text="void"), params=parameters, body=IRBlock(stmts=[pool]))
            )
            self._session.module.function_decls.append(
                IRFunctionDecl(name=name, return_type=CType(text="void"), params=parameters)
            )

    def lower_specialization(self, view: SpecializedDeclarationView[MethodDecl]) -> None:
        method = view.declaration
        if method.body is None:
            return
        declaration = self.specialization_declaration(view)
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        previous_class = self._session.current_class
        previous_class_name = self._session.current_class_name
        self._session.current_class = self._analyzed.class_table.get(view.owner_name)
        self._session.current_class_name = view.owner_name
        return_type = self._types.resolve_active_type(method.return_type)
        return_c_type = self._types.render(return_type) if return_type is not None else "void"
        self._session.function_declarations = []
        try:
            with self.isolated_function_context(return_c_type, return_type):
                body = self._statements.lower_block(
                    method.body,
                    provenance,
                    local_bindings=[
                        *([] if method.access == "class" else ["self"]),
                        *(parameter.name for parameter in method.params),
                    ],
                    callable_bindings=method.params,
                )
        finally:
            self._session.current_class = previous_class
            self._session.current_class_name = previous_class_name
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=declaration.name,
                return_type=declaration.return_type,
                params=list(declaration.params),
                body=body,
                is_static=True,
            )
        )

    def declare_specialization(self, view: SpecializedDeclarationView[MethodDecl]) -> None:
        declaration = self.specialization_declaration(view)
        if declaration not in self._session.module.function_decls:
            self._session.module.function_decls.append(declaration)

    def specialization_declaration(
        self,
        view: SpecializedDeclarationView[MethodDecl],
    ) -> IRFunctionDecl:
        """Describe one generic method instance through shared signature policy."""
        method = view.declaration
        params = []
        if method.access != "class":
            params.append(IRParam(c_type=CType(text=f"{view.owner_symbol}*"), name="self"))
        for parameter in method.params:
            resolved = self._types.resolve_active_type(parameter.type)
            params.append(self._signatures.lower_source_param(parameter, resolved_type=resolved))
        return_type = self._types.resolve_active_type(method.return_type)
        return IRFunctionDecl(
            name=view.symbol,
            return_type=CType(text=self._types.render(return_type) if return_type is not None else "void"),
            params=params,
            is_static=True,
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

    def materialize_deferred_closure(
        self,
        default_plans: list[GenericDefaultHelperPlan],
    ) -> None:
        """Reach a fixed point across mutually discovered deferred bodies."""

        while default_plans or self._session.pending_lambdas or self._session.pending_thread_spawns:
            self.materialize_default_helpers(default_plans)
            self.materialize_deferred_functions()

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
            IRFunctionDef(
                name=c_name,
                return_type=CType(text=ret_type),
                params=params,
                body=body,
                is_static=is_static,
                is_realtime=decl.is_realtime,
            )
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
        fn_type = self._session.type_of(node)
        if fn_type and fn_type.base in {"__fn_ptr", "__realtime_fn_ptr"} and fn_type.generic_args:
            return fn_type.generic_args[0]
        if isinstance(node.body, LambdaExprBody) and node.body.expression:
            return self._session.type_of(node.body.expression)
        return None
