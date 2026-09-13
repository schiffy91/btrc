"""Cohesive functions IR lowering owner."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.frontend.native_imports import (
    NativeActionProjection,
    NativeDelegateProjection,
    NativeHeaderSource,
)
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
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRIf,
    IRInclude,
    IRInitializerList,
    IRLiteral,
    IRModule,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCBlock,
    IRObjectiveCClass,
    IRObjectiveCExceptionBoundary,
    IRObjectiveCMessage,
    IRObjectiveCMethod,
    IRObjectiveCSelector,
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
    TypeExpr,
)

from .calls import (
    CallableProvenance,
    CallableReturnABI,
    CallableSignatureLowerer,
    CallLowerer,
    DefaultArgumentLoweringContext,
    GenericDefaultHelperPlan,
)
from .ownership import ManagedLifetimeLowerer, OwnershipLowerer
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
        lifetime: ManagedLifetimeLowerer,
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
        self._lifetime = lifetime
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
        if any(callback.one_shot for callback in contract.callbacks):
            self._emit_one_shot_c_adapter(declaration, contract)
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
        releases = []
        cleanup = []
        contexts = {callback.context_index for callback in contract.callbacks}
        visible = [index for index in range(len(arguments) + len(contexts)) if index not in contexts]
        leases = {index for index, resource in enumerate(contract.resource_parameters) if resource}
        leases.update(visible.index(callback.parameter_index) for callback in contract.callbacks)
        if (
            contract.record_output
            or leases
            or any(field.managed for record in contract.record_types for field in record.fields)
        ):
            cleanup = self._native_cleanup_scope(parameters, statements)
            for index in sorted(leases):
                arguments[index] = self._native_lease(
                    index, declaration.params[index].type, arguments[index], parameters, statements, releases
                )
            flush = self._lifetime.flush_release_batch(
                type_exprs=[declaration.params[index].type for index in sorted(leases)]
            )
            if flush is not None:
                cleanup.insert(0, IRExprStmt(expr=flush))
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
                    parameters,
                    {record.name: record for record in contract.record_types},
                    releases,
                )
        statements = [*locals, *statements]
        for index, resource in enumerate(contract.resource_parameters):
            if resource:
                arguments[index] = IRCast(target_type=CType(text=resource), expr=arguments[index])
        if contract.callbacks:
            native_arguments = dict(zip(visible, arguments, strict=True))
            for callback in contract.callbacks:
                receiver = native_arguments[callback.parameter_index]
                thunk, context = self._native_callback_context(
                    declaration.name, callback, receiver, parameters, statements
                )
                native_arguments[callback.context_index] = context
                native_arguments[callback.parameter_index] = thunk
            arguments = [native_arguments[index] for index in range(len(native_arguments))]
        call = IRCall(callee=declaration.name, args=arguments)
        if contract.resource_result:
            call = IRCast(target_type=return_type, expr=call)
        if contract.record_output:
            self._native_record_output(
                declaration, contract.record_output, arguments, parameters, statements, releases, cleanup
            )
        elif return_type.text == "void":
            statements.append(IRExprStmt(expr=call))
            statements.extend(releases)
            statements.extend(cleanup)
        elif contract.nonnull_return or cleanup:
            result = "__btrc_native_result"
            while any(parameter.name == result for parameter in parameters):
                result += "_"
            result_slot = IRVarDecl(c_type=return_type, name=result, init=call)
            statements.append(result_slot)
            if cleanup and contract.resource_result:
                statements.append(
                    IRExprStmt(expr=self._lifetime.register_cleanup_slot(result_slot, declaration.return_type))
                )
            statements.extend(releases)
            if contract.nonnull_return:
                statements.append(
                    self._native_null_guard(
                        IRVar(name=result), f"Native call {declaration.name}: null result", contract.realtime_safe
                    )
                )
            statements.extend(cleanup)
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

    def _native_record_output(self, declaration, output, arguments, parameters, statements, releases, cleanup):
        names = {parameter.name for parameter in parameters}
        reserved = []
        for stem in ("owner", "output"):
            name = f"__btrc_native_{stem}"
            while name in names:
                name += "_"
            names.add(name)
            reserved.append(name)
        owner_name, native_name = reserved
        owner_type = declaration.return_type
        owner_c = CType(self._types.render(owner_type))
        owner_slot = IRVarDecl(owner_c, owner_name, init=IRCall(f"{output.output_name}_new", []))
        statements.extend(
            [
                owner_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(owner_slot, owner_type)),
                IRVarDecl(CType(output.record.native_spelling), native_name, init=IRInitializerList([IRLiteral("0")])),
            ]
        )
        arguments.insert(output.parameter_index, IRAddressOf(IRVar(native_name)))
        statements.append(IRExprStmt(IRCall(declaration.name, arguments)))
        # Fresh, empty managed fields adopt all native claims before validation.
        for field in output.record.fields:
            value = IRFieldAccess(IRVar(native_name), field.name)
            if field.resource_type:
                value = IRCast(CType(self._types.render(field.value_type)), value)
            statements.append(IRAssign(IRFieldAccess(IRVar(owner_name), field.name, arrow=True), value))
        for field in output.record.fields:
            if field.resource_type and not field.value_type.is_nullable:
                statements.append(
                    self._native_null_guard(
                        IRFieldAccess(IRVar(owner_name), field.name, arrow=True),
                        f"Native call {declaration.name}: null output {field.name}",
                    )
                )
        for field in output.null_fields:
            guard = self._native_null_guard(
                IRLiteral("NULL"), f"Native call {declaration.name}: nonnull output {field}"
            )
            guard.condition = IRBinOp(IRFieldAccess(IRVar(native_name), field), "!=", IRLiteral("NULL"))
            statements.append(guard)
        statements.extend([*releases, *cleanup, IRReturn(IRVar(owner_name))])

    def _native_cleanup_scope(self, parameters, statements):
        marker = "__btrc_native_cleanup_mark"
        while any(parameter.name == marker for parameter in parameters):
            marker += "_"
        self._session.require_helper("__btrc_cleanup_mark")
        self._session.require_helper("__btrc_discard_cleanups_to")
        statements.append(
            IRVarDecl(
                c_type=CType(text="int"),
                name=marker,
                init=IRCall(callee="__btrc_cleanup_mark", args=[], helper_ref="__btrc_cleanup_mark"),
            )
        )
        return [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups_to",
                    args=[IRVar(name=marker)],
                    helper_ref="__btrc_discard_cleanups_to",
                )
            )
        ]

    def _native_lease(self, index, value_type, argument, parameters, statements, releases, owned=False, locals=None):
        name = f"__btrc_native_argument_{index}"
        while any(parameter.name == name for parameter in parameters):
            name += "_"
        slot = IRVarDecl(
            c_type=CType(text=self._types.render(value_type)),
            name=name,
            init=argument if locals is None else IRLiteral("NULL"),
        )
        value = IRVar(name=name)
        if locals is None:
            statements.append(slot)
        else:
            locals.append(slot)
            statements.append(IRAssign(value, argument))
        if not owned:
            statements.append(IRExprStmt(expr=self._lifetime.retain_value(value, value_type)))
        statements.append(IRExprStmt(expr=self._lifetime.register_cleanup_slot(slot, value_type)))
        release_statements = []
        release_expressions = self._lifetime.release_and_clear(
            value, value_type, release_statements, self._types.render(value_type)
        )
        releases[:0] = [*release_statements, *[IRExprStmt(expr=expression) for expression in release_expressions]]
        return value

    def _native_callback_context(self, function, callback, receiver, parameters, statements):
        thunk = self._native_callback(function, callback)
        context_type = CType(text=f"struct {thunk.name}_context")
        context_name = f"__btrc_callback_context_{callback.parameter_index}"
        while any(parameter.name == context_name for parameter in parameters):
            context_name += "_"
        statements.append(
            IRVarDecl(
                c_type=context_type,
                name=context_name,
                init=IRCompoundLiteral(
                    c_type=context_type,
                    fields=[
                        ("receiver", receiver),
                        ("thread", IRAddressOf(expr=IRVar(name="__btrc_try_top"))),
                    ],
                ),
            )
        )
        return thunk, IRAddressOf(expr=IRVar(name=context_name))

    def _native_callback_types(self, callback):
        parameters = iter(self._analyzed.interface_table[callback.interface].methods[callback.method_name].params)
        return tuple(
            value if callback.is_context(index) else next(parameters).type
            for index, value in enumerate(callback.parameters)
        )

    def _native_callback(self, function, callback):
        value_types = self._native_callback_types(callback)
        name = f"__btrc_native_callback_{function}_{callback.parameter_index}"
        self._session.module.struct_defs.append(
            IRStructDef(
                name=f"{name}_context",
                fields=[
                    IRStructField(c_type=CType(text=f"{callback.interface}*"), name="receiver"),
                    IRStructField(c_type=CType(text="volatile int*"), name="thread"),
                ],
            )
        )
        parameters = [
            IRParam(c_type=CType(text=self._types.render(value)), name=f"argument{index}")
            for index, value in enumerate(value_types)
        ]
        result_type = CType(text=self._types.render(callback.return_type))
        context_type = CType(text=f"const struct {name}_context*")
        context = IRVar(name="__btrc_context")
        context_declaration = IRVarDecl(
            c_type=context_type,
            name=context.name,
            init=IRCast(
                target_type=context_type,
                expr=IRVar(name=parameters[callback.callback_context_index].name),
            ),
        )
        receiver = IRFieldAccess(obj=context, field="receiver", arrow=True)
        body = []
        releases = []
        cleanup = []
        arguments = [IRVar(name=parameter.name) for parameter in parameters]
        for index, value_type in enumerate(value_types):
            info = self._analyzed.class_table.get(value_type.base)
            if info is None or not info.native_language:
                continue
            if not value_type.is_nullable:
                body.append(
                    self._native_null_guard(arguments[index], f"Native callback {function}: null argument {index}")
                )
            if not cleanup:
                cleanup = self._native_cleanup_scope(parameters, body)
            arguments[index] = self._native_lease(index, value_type, arguments[index], parameters, body, releases)
        call = IRCall(
            callee=f"{callback.interface}_invoke",
            args=[
                receiver,
                *[argument for index, argument in enumerate(arguments) if index != callback.callback_context_index],
            ],
        )
        body.extend(
            [IRExprStmt(expr=call)]
            if result_type.text == "void"
            else [IRVarDecl(c_type=result_type, name="__btrc_callback_result", init=call)]
        )
        body.extend(releases)
        body.extend(cleanup)
        body.extend(self._exceptions.pop_try_frames(1))
        body.append(IRReturn(value=None if result_type.text == "void" else IRVar(name="__btrc_callback_result")))
        self._session.module.function_decls.append(
            IRFunctionDecl(name=name, return_type=result_type, params=parameters, is_static=True)
        )
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=name,
                return_type=result_type,
                params=parameters,
                is_static=True,
                body=IRBlock(
                    stmts=[
                        context_declaration,
                        IRIf(
                            condition=IRBinOp(
                                left=IRFieldAccess(obj=context, field="thread", arrow=True),
                                op="!=",
                                right=IRAddressOf(expr=IRVar(name="__btrc_try_top")),
                            ),
                            then_block=IRBlock(
                                stmts=[
                                    IRExprStmt(
                                        expr=IRCall(
                                            callee="fputs",
                                            args=[
                                                IRLiteral(
                                                    text='"BTRC native callback delivered on the wrong thread\\n"'
                                                ),
                                                IRVar(name="stderr"),
                                            ],
                                        )
                                    ),
                                    IRExprStmt(expr=IRCall(callee="abort", args=[], never_returns=True)),
                                ]
                            ),
                        ),
                        *self._exceptions.native_callback_boundary(IRBlock(stmts=body)).stmts,
                    ]
                ),
            )
        )
        return IRFunctionRef(name=name)

    def emit_resource_lifetime(self, declaration):
        resource = declaration.source_file.resource
        module = self._session.module
        forward = IRStructForward(name=f"__btrc_native_{declaration.name}")
        if forward not in module.struct_forwards:
            module.struct_forwards.append(forward)
        for operation, native_name in (("retain", resource.retain), ("release", resource.release)):
            module.native_external_names.add(native_name)
            name = f"__btrc_native_{declaration.name}_{operation}"
            parameters = [IRParam(c_type=CType(text="void*"), name="value")]
            value = IRVar(name="value")
            call = IRCall(callee=native_name, args=[IRCast(target_type=CType(text=resource.name), expr=value)])
            body = IRBlock(
                stmts=[
                    IRIf(
                        condition=IRBinOp(left=value, op="!=", right=IRLiteral(text="NULL")),
                        then_block=IRBlock(stmts=[IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=call))]),
                    )
                ]
            )
            module.function_decls.append(
                IRFunctionDecl(name=name, return_type=CType(text="void"), params=parameters, is_static=True)
            )
            module.function_defs.append(
                IRFunctionDef(name=name, return_type=CType(text="void"), params=parameters, body=body, is_static=True)
            )

    def _native_record_input(
        self,
        projection,
        value,
        locals,
        statements,
        function,
        path,
        parameters,
        record_types,
        releases,
        prefix="",
        by_value=False,
    ):
        # Storage is adapter-scoped, including children initialized conditionally.
        # None of these SDK descriptor addresses escape to BTRC caller storage.
        name = f"__btrc_record_input_{len(locals)}"
        while any(parameter.name == name for parameter in parameters):
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
            if field.callback:
                continue
            source = IRFieldAccess(obj=value, field=field.name, arrow=True)
            target = IRFieldAccess(obj=native, field=field.name)
            field_path = f"{path}.{field.name}"
            if (field.record or field.managed) and not field.value_type.is_nullable:
                assignments.append(self._native_null_guard(source, f"Native call {function}: null input {field_path}"))
            if field.record:
                source = self._native_record_input(
                    record_types[field.record],
                    source,
                    locals,
                    assignments,
                    function,
                    field_path,
                    parameters,
                    record_types,
                    releases,
                    field.prefix,
                    field.by_value,
                )
            elif field.managed:
                source = self._native_lease(
                    len(parameters) + len(locals),
                    self._analyzed.class_table[projection.input_name].fields[field.name].type,
                    source,
                    parameters,
                    assignments,
                    releases,
                    locals=locals,
                )
                source = IRCast(target_type=CType(text=field.resource_type or "void*"), expr=source)
            assignments.append(IRAssign(target=target, value=source))
        statements.append(
            IRIf(
                condition=IRBinOp(left=value, op="!=", right=IRLiteral(text="NULL")),
                then_block=IRBlock(stmts=assignments),
            )
        )
        if projection.by_value or by_value:
            return native
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
        contract = declaration.source_file.call_contract
        if contract is not None and contract.executor == "main":
            include = IRInclude(header="pthread.h")
            if include not in module.preprocessor_decls:
                module.preprocessor_decls.append(include)
            statements.insert(
                0,
                IRIf(
                    condition=IRBinOp(
                        left=IRCall(callee="pthread_main_np", args=[]), op="==", right=IRLiteral(text="0")
                    ),
                    then_block=IRBlock(
                        stmts=[
                            self._objective_c_null_guard(
                                IRLiteral(text="NULL"), f"Native global {declaration.name} requires the main thread"
                            )
                        ]
                    ),
                ),
            )
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
            contract = declaration.source_file.methods[method.name]
            if any(callback.one_shot for callback in contract.callbacks):
                self._emit_one_shot_objective_c_adapter(declaration, method, contract, native)
                continue
            if any(callback.unregister is not None for callback in contract.callbacks):
                self._emit_stored_objective_c_adapter(declaration, method, contract, native)
                continue
            descriptor = contract.objective_c_method
            callbacks = {callback.parameter_index: callback for callback in contract.callbacks}
            name = f"{declaration.name}_{method.name}"
            adapter = f"__btrc_objc_{name}"
            result_type = CType(text=self._types.render(method.return_type))
            object_return = self._analyzed.class_table.get(method.return_type.base)
            parameters = [self._signatures.lower_source_param(parameter) for parameter in method.params]
            arguments = [IRVar(name=parameter.name) for parameter in parameters]
            native_arguments = []
            for index, (parameter, argument) in enumerate(zip(method.params, arguments)):
                info = self._analyzed.class_table.get(parameter.type.base)
                if index in callbacks:
                    native_arguments.append(IRLiteral("0"))
                elif info is not None and info.native_language:
                    native_arguments.append(
                        IRCast(self._objective_c_object_type(parameter.type.base), argument, bridge="borrow")
                    )
                else:
                    native_arguments.append(self._objective_c_value(parameter.type, argument, to_native=True))
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
            offset = int(not descriptor.class_method)
            adapter_parameters = []
            for index, parameter in enumerate(parameters):
                callback = callbacks.get(index - offset)
                if callback is None:
                    adapter_parameters.append(parameter)
                    continue
                value_types = self._native_callback_types(callback)
                signature = IRFunctionPointerTypedef(
                    name=f"{adapter}_callback{callback.parameter_index}",
                    return_type=CType(self._types.render(callback.return_type)),
                    param_types=[CType(self._types.render(value)) for value in value_types],
                )
                module.function_pointer_typedefs.append(signature)
                native.function_pointer_typedefs.append(signature)
                adapter_parameters.extend(
                    [
                        IRParam(CType(signature.name), parameter.name),
                        IRParam(CType("void*"), parameter.name + "Context"),
                    ]
                )
                block_parameters = [
                    IRParam(CType(value), f"__btrc_block_value{position}")
                    for position, value in enumerate(callback.native_parameters)
                ]
                forwarded = IRCall(
                    callee=IRVar(parameter.name),
                    args=[
                        *[
                            IRCast(CType(self._types.render(value_type)), IRVar(value.name), bridge="borrow")
                            if (info := self._analyzed.class_table.get(value_type.base)) is not None
                            and info.native_language
                            else IRVar(value.name)
                            for value, value_type in zip(block_parameters, value_types)
                        ],
                        IRVar(parameter.name + "Context"),
                    ],
                )
                block_body = (
                    [IRExprStmt(forwarded), IRReturn()]
                    if signature.return_type.text == "void"
                    else [IRReturn(IRCast(CType(callback.native_return), forwarded))]
                )
                native_arguments[callback.parameter_index] = IRObjectiveCBlock(
                    CType(callback.native_return), block_parameters, IRBlock(block_body)
                )
            if returns_value:
                output_type = CType.qualify_volatile_object(
                    result_type.text, object_return is not None and bool(object_return.native_language)
                )
                adapter_parameters.append(IRParam(CType(f"{output_type}*"), "nativeResult"))
            call = IRObjectiveCMessage(receiver=receiver, selector=descriptor.selector, args=native_arguments)
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
                for index, parameter in enumerate(method.params)
                if index in callbacks or (parameter.type.pointer_depth > 0 and not parameter.type.is_nullable)
            ]
            if not descriptor.class_method:
                required.insert(0, "self")
            for parameter in required:
                statements.append(
                    self._objective_c_null_guard(
                        IRVar(name=parameter), f"Objective-C call {descriptor.name}: null argument {parameter}"
                    )
                )
            argument_types = [parameter.type for parameter in method.params]
            if not descriptor.class_method:
                argument_types.insert(0, TypeExpr(base=declaration.name, pointer_depth=1))
            leases = [
                index
                for index, value_type in enumerate(argument_types)
                if index - offset in callbacks
                or ((info := self._analyzed.class_table.get(value_type.base)) is not None and info.native_language)
            ]
            releases = []
            cleanup = self._native_cleanup_scope(parameters, statements) if leases else []
            for index in leases:
                arguments[index] = self._native_lease(
                    index, argument_types[index], arguments[index], parameters, statements, releases
                )
            call_arguments = []
            for index, argument in enumerate(arguments):
                callback = callbacks.get(index - offset)
                if callback is None:
                    call_arguments.append(argument)
                else:
                    call_arguments.extend(
                        self._native_callback_context(name, callback, argument, parameters, statements)
                    )
            statements.append(
                IRIf(
                    condition=IRCall(
                        callee=adapter, args=[*call_arguments, *([IRAddressOf(expr=result)] if returns_value else [])]
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
            if leases and object_return is not None and object_return.native_language:
                statements.append(IRExprStmt(self._lifetime.register_cleanup_slot(statements[0], method.return_type)))
            statements.extend(releases)
            flush = self._lifetime.flush_release_batch(type_exprs=[argument_types[index] for index in leases])
            if flush is not None:
                statements.append(IRExprStmt(flush))
            statements.extend(cleanup)
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

    def _stored_context_lifetime(self, prefix, context_type, context_symbol):
        """Foreign holders acquire ordinary external ARC claims, never field edges."""
        raw = IRVar("rawContext")
        context = IRCast(CType(self._types.render(context_type)), raw)
        for operation in ("retain", "release"):
            action = (
                self._lifetime.retain_value(context, context_type)
                if operation == "retain"
                else self._lifetime.release_value(context, context_type)
            )
            body = IRBlock(
                [
                    IRExprStmt(IRCall(f"{context_symbol}_isOpen", [context])),
                    IRExprStmt(action),
                    *self._exceptions.pop_try_frames(1),
                ]
            )
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=f"{prefix}_{operation}",
                    return_type=CType("void"),
                    params=[IRParam(CType("void*"), raw.name)],
                    is_static=True,
                    body=self._exceptions.native_callback_boundary(body),
                )
            )

    def _stored_context_holder(self, prefix, native, lifetime_type):
        """One ARC-captured Objective-C object transports the managed root claim."""
        name = prefix + "Holder"
        native.objective_c_classes.append(
            IRObjectiveCClass(
                name=name,
                superclass="NSObject",
                fields=[IRStructField(CType("void*"), "_context"), IRStructField(CType(lifetime_type), "_release")],
                methods=[
                    IRObjectiveCMethod(
                        "configure:retain:release:",
                        CType("void"),
                        [
                            IRParam(CType("void*"), "context"),
                            IRParam(CType(lifetime_type), "retainContext"),
                            IRParam(CType(lifetime_type), "releaseContext"),
                        ],
                        IRBlock(
                            [
                                IRExprStmt(IRCall(IRVar("retainContext"), [IRVar("context")])),
                                IRAssign(IRVar("_context"), IRVar("context")),
                                IRAssign(IRVar("_release"), IRVar("releaseContext")),
                            ]
                        ),
                    ),
                    IRObjectiveCMethod("context", CType("void*"), [], IRBlock([IRReturn(IRVar("_context"))])),
                    IRObjectiveCMethod(
                        "dealloc",
                        CType("void"),
                        [],
                        IRBlock(
                            [
                                IRIf(
                                    IRVar("_context"),
                                    IRBlock([IRExprStmt(IRCall(IRVar("_release"), [IRVar("_context")]))]),
                                ),
                            ]
                        ),
                    ),
                ],
            )
        )
        return name

    def _native_string_view(self, index, view, argument, receiver, value_type, parameters, statements, releases):
        value = self._native_lease(index, value_type, IRLiteral("NULL"), parameters, statements, releases, owned=True)
        data = IRFieldAccess(argument, view.data)
        length = IRFieldAccess(argument, view.length)
        present = IRBinOp(data, "!=", IRLiteral("NULL"))
        nonempty = IRBinOp(present, "&&", IRBinOp(length, "!=", IRLiteral("0")))
        invalid_null = IRBinOp(length, "!=", IRLiteral("0"))
        if view.null_maximum:
            invalid_null = IRBinOp(
                invalid_null, "&&", IRBinOp(length, "!=", IRCast(CType(view.length_spelling), IRLiteral("-1")))
            )
        conditions = [
            (IRBinOp(IRBinOp(data, "==", IRLiteral("NULL")), "&&", invalid_null), "null data with nonempty length"),
            (
                IRBinOp(
                    present, "&&", IRBinOp(IRCast(CType("unsigned long long"), length), ">", IRLiteral("2147483647ULL"))
                ),
                "byte length exceeds BTRC string range",
            ),
            (
                IRBinOp(
                    nonempty,
                    "&&",
                    IRBinOp(
                        IRCall("memchr", [data, IRLiteral("0"), IRCast(CType("size_t"), length)]),
                        "!=",
                        IRLiteral("NULL"),
                    ),
                ),
                "embedded NUL cannot be represented as a BTRC string",
            ),
        ]
        body = []
        for condition, message in conditions:
            guard = self._native_null_guard(data, f"Native string view: {message}")
            guard.condition = condition
            body.append(guard)
        body.append(
            IRAssign(
                value,
                IRTernary(nonempty, IRCall("__btrc_string_alloc", [IRCast(CType("int"), length)]), IRLiteral('""')),
            )
        )
        body.append(
            IRIf(nonempty, IRBlock([IRExprStmt(IRCall("memcpy", [value, data, IRCast(CType("size_t"), length)]))]))
        )
        statements.append(IRIf(receiver, IRBlock(body)))
        return value

    def _stored_context_invoker(self, prefix, callback, context_type, context_symbol, consume_native_claim=False):
        value_types = self._native_callback_types(callback)
        string_arguments = dict(callback.string_arguments)
        result_type = CType(self._types.render(callback.return_type))
        returns_value = result_type.text != "void"
        parameters = [
            IRParam(
                CType(
                    string_arguments[index].native_spelling
                    if index in string_arguments
                    else callback.parameters[index].base
                    if index in callback.owned_arguments
                    else self._types.render(value)
                ),
                f"argument{index}",
            )
            for index, value in enumerate(value_types)
        ]
        context_index = callback.callback_context_index
        context = IRCast(CType(self._types.render(context_type)), IRVar(parameters[context_index].name))
        receiver_type = context_type.generic_args[0]
        receiver_slot = IRVarDecl(
            CType(self._types.render(receiver_type)), "receiver", init=IRCall(f"{context_symbol}_enter", [context])
        )
        receiver = IRVar(receiver_slot.name)
        body = []
        cleanup = self._native_cleanup_scope(parameters, body)
        for index in callback.callback_context_indices:
            if index != context_index:
                guard = self._native_null_guard(
                    IRVar(parameters[index].name), f"Native callback {prefix}: inconsistent context slots"
                )
                guard.condition = IRBinOp(IRVar(parameters[index].name), "!=", IRVar(parameters[context_index].name))
                body.append(guard)
        body.extend([receiver_slot, IRExprStmt(self._lifetime.register_cleanup_slot(receiver_slot, receiver_type))])
        if returns_value:
            # A cancelled query has no valid default answer. Use the binding's
            # terminal failure boundary, rather than silently returning zero.
            body.append(self._objective_c_null_guard(receiver, f"Stored callback {prefix}: query after cancellation"))
            body.append(IRVarDecl(result_type, "result", init=IRLiteral("0")))
        payload_indices = [index for index in range(len(value_types)) if not callback.is_context(index)]
        argument_types = [value_types[index] for index in payload_indices]
        arguments = [IRVar(parameters[index].name) for index in payload_indices]
        releases = []
        for index, value_type in enumerate(argument_types):
            native_index = payload_indices[index]
            owned = native_index in callback.owned_arguments
            if native_index in string_arguments:
                arguments[index] = self._native_string_view(
                    index,
                    string_arguments[native_index],
                    arguments[index],
                    receiver,
                    value_type,
                    parameters,
                    body,
                    releases,
                )
                continue
            info = self._analyzed.class_table.get(value_type.base)
            if info is not None and info.native_language:
                if owned:
                    arguments[index] = IRCast(CType(self._types.render(value_type)), arguments[index])
                if not value_type.is_nullable:
                    body.append(
                        self._objective_c_null_guard(
                            arguments[index], f"Stored callback {prefix}: null argument {index}"
                        )
                    )
                arguments[index] = self._native_lease(
                    index, value_type, arguments[index], parameters, body, releases, owned
                )
        body.append(
            IRIf(
                receiver,
                IRBlock(
                    [
                        IRAssign(
                            IRVar("result"),
                            IRCall(f"{callback.interface}_{callback.method_name}", [receiver, *arguments]),
                        )
                        if returns_value
                        else IRExprStmt(IRCall(f"{callback.interface}_{callback.method_name}", [receiver, *arguments])),
                        IRExprStmt(IRCall(f"{context_symbol}_leave", [context])),
                    ]
                ),
            )
        )
        body.extend(releases)
        release_locals = []
        release = self._lifetime.release_and_clear(
            receiver, receiver_type, release_locals, self._types.render(receiver_type)
        )
        body.extend(
            [
                *release_locals,
                *[IRExprStmt(value) for value in release],
                *([IRExprStmt(IRCall(f"{context_symbol}_complete", [context]))] if callback.one_shot else []),
                *([IRExprStmt(self._lifetime.release_value(context, context_type))] if consume_native_claim else []),
                *cleanup,
                *self._exceptions.pop_try_frames(1),
            ]
        )
        if returns_value:
            body.append(IRReturn(IRVar("result")))
        name = prefix + "_invoke"
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=name,
                return_type=result_type,
                params=parameters,
                is_static=True,
                body=self._exceptions.native_callback_boundary(IRBlock(body)),
            )
        )
        return name, value_types

    def _emit_one_shot_c_adapter(self, declaration, contract):
        """C owns one ordinary ARC claim until its promised terminal callback."""
        callback = contract.callbacks[0]
        name = contract.adapter_symbol(declaration.name)
        result_type = declaration.return_type
        returns_value = result_type.base == "CallbackResult"
        context_type = result_type.generic_args[1] if returns_value else result_type
        result_c = CType(self._types.render(result_type))
        context_c = CType(self._types.render(context_type))
        context_symbol = context_c.text.removesuffix("*").strip()
        invoke, _values = self._stored_context_invoker(name, callback, context_type, context_symbol, True)
        parameters = [self._signatures.lower_source_param(parameter) for parameter in declaration.params]
        body = []
        cleanup = self._native_cleanup_scope(parameters, body)
        arguments = [IRVar(parameter.name) for parameter in parameters]
        releases = []
        for index, parameter in enumerate(declaration.params):
            if contract.nonnull_parameters[index]:
                body.append(
                    self._native_null_guard(arguments[index], f"Native call {declaration.name}: null {parameter.name}")
                )
            if (
                parameter.type.base in self._analyzed.class_table
                or parameter.type.base in self._analyzed.interface_table
            ):
                arguments[index] = self._native_lease(
                    index, parameter.type, arguments[index], parameters, body, releases
                )
        context_count = int(callback.context_index >= 0)
        visible = [index for index in range(len(parameters) - 1 + context_count) if index != callback.context_index]
        receiver = arguments[visible.index(callback.parameter_index)]
        if callback.field:
            receiver = IRFieldAccess(receiver, callback.field, arrow=True)
            body.append(
                self._native_null_guard(receiver, f"Native call {declaration.name}: null callback {callback.field}")
            )
            input_type = declaration.params[visible.index(callback.parameter_index)].type
            receiver = self._native_lease(
                len(parameters),
                self._analyzed.class_table[input_type.base].fields[callback.field].type,
                receiver,
                parameters,
                body,
                releases,
            )
        locals = []
        for index, projection in enumerate(contract.record_inputs):
            if projection is not None:
                arguments[index] = self._native_record_input(
                    projection,
                    arguments[index],
                    locals,
                    body,
                    declaration.name,
                    parameters[index].name,
                    parameters,
                    {record.name: record for record in contract.record_types},
                    releases,
                )
        body = [*locals, *body]
        for index, resource in enumerate(contract.resource_parameters):
            if resource:
                arguments[index] = IRCast(CType(resource), arguments[index])
        native_arguments = dict(zip(visible, arguments[:-1], strict=True))
        context_name = "__btrc_native_request"
        while any(parameter.name == context_name for parameter in parameters):
            context_name += "_"
        context_slot = IRVarDecl(context_c, context_name, init=IRCall(f"{context_symbol}_new", [receiver]))
        context = IRVar(context_name)
        body.extend(
            [
                context_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(context_slot, context_type)),
            ]
        )
        result = context
        if returns_value:
            result_name = "__btrc_native_result"
            while any(parameter.name == result_name for parameter in parameters):
                result_name += "_"
            result_symbol = result_c.text.removesuffix("*").strip()
            result_slot = IRVarDecl(result_c, result_name, init=IRCall(f"{result_symbol}_new", [context]))
            result = IRVar(result_name)
            body.extend([result_slot, IRExprStmt(self._lifetime.register_cleanup_slot(result_slot, result_type))])
        body.extend(
            [
                IRExprStmt(IRCall(f"{context_symbol}_activate", [context, arguments[-1]])),
                IRExprStmt(self._lifetime.retain_value(context, context_type)),
            ]
        )
        if callback.field:
            descriptor = native_arguments[callback.parameter_index]
            body.extend(
                [
                    IRAssign(IRFieldAccess(descriptor, callback.field), IRFunctionRef(invoke)),
                    *(
                        IRAssign(IRFieldAccess(descriptor, field), IRCast(CType("void*"), context))
                        for field in callback.context_fields
                    ),
                ]
            )
        else:
            native_arguments[callback.parameter_index] = IRFunctionRef(invoke)
            native_arguments[callback.context_index] = IRCast(CType("void*"), context)
        native_call = IRCall(declaration.name, [native_arguments[index] for index in range(len(native_arguments))])
        if returns_value:
            body.append(IRAssign(IRFieldAccess(result, "value", arrow=True), native_call))
        else:
            body.append(IRExprStmt(native_call))
        body.append(IRExprStmt(IRCall(f"{context_symbol}_publish", [context])))
        if returns_value:
            release_locals = []
            release = self._lifetime.release_and_clear(context, context_type, release_locals, context_c.text)
            body.extend([*release_locals, *[IRExprStmt(value) for value in release]])
        body.extend(
            [
                *releases,
                *cleanup,
                IRReturn(result),
            ]
        )
        self._session.module.function_decls.append(IRFunctionDecl(name, result_c, parameters, is_static=True))
        self._session.module.function_defs.append(
            IRFunctionDef(name=name, return_type=result_c, params=parameters, is_static=True, body=IRBlock(body))
        )

    def _emit_one_shot_objective_c_adapter(self, declaration, method, contract, native):
        """One terminal block, using the same managed holder and admitted ingress."""
        module = self._session.module
        descriptor = contract.objective_c_method
        callback = contract.callbacks[0]
        name = f"{declaration.name}_{method.name}"
        prefix = f"__btrc_objc_{name}"
        context_type = method.return_type
        context_c = CType(self._types.render(context_type))
        context_symbol = context_c.text.removesuffix("*").strip()
        self._stored_context_lifetime(prefix, context_type, context_symbol)
        invoke, values = self._stored_context_invoker(prefix, callback, context_type, context_symbol)
        lifetime_type = prefix + "_lifetime"
        invocation_type = prefix + "_callback"
        typedefs = [
            IRFunctionPointerTypedef(lifetime_type, CType("void"), [CType("void*")]),
            IRFunctionPointerTypedef(invocation_type, CType("void"), [CType(self._types.render(v)) for v in values]),
        ]
        module.function_pointer_typedefs.extend(typedefs)
        native.function_pointer_typedefs.extend(typedefs)
        holder_name = self._stored_context_holder(prefix, native, lifetime_type)
        parameters = [self._signatures.lower_source_param(parameter) for parameter in method.params]
        parameter_types = [parameter.type for parameter in method.params]
        offset = int(not descriptor.class_method)
        if offset:
            source_type = TypeExpr(base=declaration.name, pointer_depth=1)
            parameters.insert(0, IRParam(CType(self._types.render(source_type)), "self"))
            parameter_types.insert(0, source_type)
        native_receiver = (
            IRCast(self._objective_c_object_type(declaration.name), IRVar("self"), bridge="borrow")
            if offset
            else IRVar(declaration.name)
        )
        adapter_parameters = parameters[:offset]
        native_arguments = []
        for index, parameter in enumerate(parameters[offset:-1]):
            if index == callback.parameter_index:
                adapter_parameters.extend(
                    [
                        IRParam(CType(invocation_type), "invoke"),
                        IRParam(CType("void*"), "context"),
                        IRParam(CType(lifetime_type), "retainContext"),
                        IRParam(CType(lifetime_type), "releaseContext"),
                    ]
                )
                block_parameters = [
                    IRParam(CType(value), f"value{i}") for i, value in enumerate(callback.native_parameters)
                ]
                block_arguments = []
                for block_parameter, value_type in zip(block_parameters, values):
                    argument = IRVar(block_parameter.name)
                    info = self._analyzed.class_table.get(value_type.base)
                    if info is not None and info.native_language:
                        argument = IRCast(CType(self._types.render(value_type)), argument, bridge="borrow")
                    block_arguments.append(argument)
                block_arguments.append(IRObjectiveCMessage(IRVar("holder"), "context", []))
                native_arguments.append(
                    IRObjectiveCBlock(
                        CType("void"), block_parameters, IRBlock([IRExprStmt(IRCall(IRVar("invoke"), block_arguments))])
                    )
                )
            else:
                adapter_parameters.append(parameter)
                value_type = method.params[index].type
                argument = IRVar(parameter.name)
                info = self._analyzed.class_table.get(value_type.base)
                native_arguments.append(
                    IRCast(self._objective_c_object_type(value_type.base), argument, bridge="borrow")
                    if info is not None and info.native_language
                    else self._objective_c_value(value_type, argument, to_native=True)
                )
        holder = IRVar("holder")
        native_body = IRBlock(
            [
                IRVarDecl(CType(holder_name + "*"), "holder", init=IRObjectiveCMessage(IRVar(holder_name), "new", [])),
                IRIf(IRBinOp(holder, "==", IRLiteral("nil")), IRBlock([IRReturn(IRLiteral("2"))])),
                IRExprStmt(
                    IRObjectiveCMessage(
                        holder,
                        "configure:retain:release:",
                        [
                            IRVar("context"),
                            IRVar("retainContext"),
                            IRVar("releaseContext"),
                        ],
                    )
                ),
                IRExprStmt(IRObjectiveCMessage(native_receiver, descriptor.selector, native_arguments)),
                IRReturn(IRLiteral("0")),
            ]
        )
        native.function_defs.append(
            IRFunctionDef(
                name=prefix,
                return_type=CType("int"),
                params=adapter_parameters,
                body=IRBlock(
                    [
                        IRObjectiveCAutoreleasePool(
                            IRBlock(
                                [
                                    IRObjectiveCExceptionBoundary(native_body, IRBlock([IRReturn(IRLiteral("1"))])),
                                ]
                            )
                        )
                    ]
                ),
            )
        )
        module.function_decls.append(IRFunctionDecl(prefix, CType("int"), adapter_parameters))
        body = []
        cleanup = self._native_cleanup_scope(parameters, body)
        arguments = [IRVar(parameter.name) for parameter in parameters]
        releases = []
        for index, (parameter, value_type) in enumerate(zip(parameters, parameter_types)):
            if value_type.base in self._analyzed.class_table or value_type.base in self._analyzed.interface_table:
                if not value_type.is_nullable:
                    body.append(
                        self._objective_c_null_guard(
                            arguments[index], f"One-shot {descriptor.name}: null {parameter.name}"
                        )
                    )
                arguments[index] = self._native_lease(index, value_type, arguments[index], parameters, body, releases)
        context_slot = IRVarDecl(
            context_c, "context", init=IRCall(f"{context_symbol}_new", [arguments[callback.parameter_index + offset]])
        )
        context = IRVar("context")
        body.extend(
            [
                context_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(context_slot, context_type)),
                IRExprStmt(IRCall(f"{context_symbol}_activate", [context, arguments[-1]])),
            ]
        )
        adapter_arguments = []
        for index, argument in enumerate(arguments[:-1]):
            adapter_arguments.extend(
                [
                    IRFunctionRef(invoke),
                    IRCast(CType("void*"), context),
                    IRFunctionRef(prefix + "_retain"),
                    IRFunctionRef(prefix + "_release"),
                ]
                if index == callback.parameter_index + offset
                else [argument]
            )
        body.extend(
            [
                IRVarDecl(CType("int"), "activationStatus", init=IRCall(prefix, adapter_arguments)),
                IRIf(
                    IRBinOp(IRVar("activationStatus"), "!=", IRLiteral("0")),
                    self._stored_activation_failure(
                        callback,
                        context_symbol,
                        context,
                        f"One-shot {descriptor.name}: activation failed before publication",
                    ),
                ),
                IRExprStmt(IRCall(f"{context_symbol}_publish", [context])),
                *releases,
                *cleanup,
                IRReturn(context),
            ]
        )
        module.function_decls.append(IRFunctionDecl(name, context_c, parameters, is_static=True))
        module.function_defs.append(
            IRFunctionDef(name=name, return_type=context_c, params=parameters, is_static=True, body=IRBlock(body))
        )

    def _stored_delegate_holder(self, callback, native, invocation_types, value_types):
        """Protocol methods forward through the same rooted context and C boundary."""
        holder = native.objective_c_classes[-1]
        holder.protocols = [callback.protocol]
        configure = holder.methods[0]
        for index, (method, invocation_type, parameters) in enumerate(
            zip(callback.methods, invocation_types, value_types)
        ):
            field = f"_invoke{index}"
            configure.selector += f"invoke{index}:"
            configure.params.append(IRParam(CType(invocation_type), f"invoke{index}"))
            configure.body.stmts.append(IRAssign(IRVar(field), IRVar(f"invoke{index}")))
            holder.fields.append(IRStructField(CType(invocation_type), field))
            native_parameters = [
                IRParam(CType(value), f"argument{position}") for position, value in enumerate(method.native_parameters)
            ]
            arguments = []
            for parameter, value_type in zip(native_parameters, parameters):
                value = IRVar(parameter.name)
                info = self._analyzed.class_table.get(value_type.base)
                if info is not None and info.native_language:
                    value = IRCast(CType(self._types.render(value_type)), value, bridge="borrow")
                arguments.append(value)
            invocation = IRCall(IRVar(field), [*arguments, IRVar("_context")])
            body = (
                IRExprStmt(invocation)
                if self._types.render(method.return_type) == "void"
                else IRReturn(IRCast(CType(method.native_return), invocation))
            )
            holder.methods.append(
                IRObjectiveCMethod(
                    method.native_method.selector, CType(method.native_return), native_parameters, IRBlock([body])
                )
            )
        return configure.selector

    def _stored_action_holder(self, native, invocation_type):
        holder = native.objective_c_classes[-1]
        configure = holder.methods[0]
        configure.selector += "invoke:source:"
        configure.params.extend([IRParam(CType(invocation_type), "invoke"), IRParam(CType("id"), "source")])
        holder.fields.extend([IRStructField(CType(invocation_type), "_invoke"), IRStructField(CType("id"), "_source")])
        configure.body.stmts.extend(
            [IRAssign(IRVar("_invoke"), IRVar("invoke")), IRAssign(IRVar("_source"), IRVar("source"))]
        )
        holder.methods.append(
            IRObjectiveCMethod(
                "btrcInvoke:",
                CType("void"),
                [IRParam(CType("id"), "sender")],
                IRBlock(
                    [
                        IRIf(
                            IRBinOp(IRVar("sender"), "!=", IRVar("_source")),
                            IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))]),
                        ),
                        IRExprStmt(IRCall(IRVar("_invoke"), [IRVar("_context")])),
                    ]
                ),
            )
        )
        return configure.selector

    def _emit_stored_objective_c_adapter(self, declaration, method, contract, native):
        """Compose checked native block storage with the shared BTRC context."""
        module = self._session.module
        descriptor = contract.objective_c_method
        callback = contract.callbacks[0]
        action = isinstance(callback, NativeActionProjection)
        object_callback = isinstance(callback, (NativeDelegateProjection, NativeActionProjection))
        name = f"{declaration.name}_{method.name}"
        prefix = f"__btrc_objc_{name}"
        context_type = method.return_type
        context_symbol = self._types.render(context_type).removesuffix("*").strip()
        token_type = context_type.generic_args[1]
        paired = bool(callback.unregister.signature.parameters)
        native_token_type = token_type.generic_args[1] if paired else token_type
        native_token_c = CType(self._types.render(native_token_type))
        token_symbol = self._types.render(token_type).removesuffix("*").strip()
        token_c = CType(self._types.render(token_type))
        context_c = CType(self._types.render(context_type))
        self._stored_context_lifetime(prefix, context_type, context_symbol)
        lifetime_type = prefix + "_lifetime"
        typedefs = [IRFunctionPointerTypedef(lifetime_type, CType("void"), [CType("void*")])]
        invokers = []
        invocation_types = []
        callback_types = []
        for index, projection in enumerate(callback.methods if object_callback else (callback,)):
            invocation_type = f"{prefix}_callback{index}"
            invoke, value_types = self._stored_context_invoker(
                f"{prefix}_{index}", projection, context_type, context_symbol
            )
            invokers.append(invoke)
            invocation_types.append(invocation_type)
            callback_types.append(value_types)
            typedefs.append(
                IRFunctionPointerTypedef(
                    invocation_type,
                    CType(self._types.render(projection.return_type)),
                    [CType(self._types.render(value)) for value in value_types],
                )
            )
        for typedef in typedefs:
            module.function_pointer_typedefs.append(typedef)
            native.function_pointer_typedefs.append(typedef)
        holder_name = self._stored_context_holder(prefix, native, lifetime_type)
        configure_selector = (
            self._stored_action_holder(native, invocation_types[0])
            if action
            else self._stored_delegate_holder(callback, native, invocation_types, callback_types)
            if object_callback
            else "configure:retain:release:"
        )
        token = IRVar("token")
        unregister_adapter = prefix + "_unregister_adapter"
        unregister_parameters = [IRParam(native_token_c, token.name)]
        unregister_receiver = IRCast(self._objective_c_object_type(native_token_type.base), token, bridge="borrow")
        unregister_arguments = []
        if paired:
            source_type = token_type.generic_args[0]
            unregister_parameters.insert(0, IRParam(CType(self._types.render(source_type)), "source"))
            unregister_arguments.append(unregister_receiver)
            unregister_receiver = IRCast(
                self._objective_c_object_type(source_type.base), IRVar("source"), bridge="borrow"
            )
        unregister_body = [
            IRExprStmt(
                IRObjectiveCMessage(
                    unregister_receiver,
                    callback.unregister.selector,
                    [IRLiteral("nil")] if object_callback else unregister_arguments,
                )
            )
        ]
        if object_callback:
            current = IRObjectiveCMessage(unregister_receiver, callback.getter.selector, [])
            reject = IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))])
            unregister_body.insert(0, IRIf(IRBinOp(current, "!=", IRCast(CType("id"), token, bridge="borrow")), reject))
            unregister_body.append(IRIf(IRBinOp(current, "!=", IRLiteral("nil")), reject))
            if action:
                selector = IRObjectiveCMessage(unregister_receiver, callback.action_getter.selector, [])
                unregister_body.insert(1, IRIf(IRBinOp(selector, "!=", IRObjectiveCSelector("btrcInvoke:")), reject))
                unregister_body.insert(
                    2,
                    IRExprStmt(
                        IRObjectiveCMessage(unregister_receiver, callback.action_setter.selector, [IRLiteral("NULL")])
                    ),
                )
                unregister_body.append(IRIf(IRBinOp(selector, "!=", IRLiteral("NULL")), reject))
        native.function_defs.append(
            IRFunctionDef(
                name=unregister_adapter,
                return_type=CType("void"),
                params=unregister_parameters,
                body=IRBlock(
                    [
                        IRObjectiveCAutoreleasePool(
                            IRBlock(
                                [
                                    IRObjectiveCExceptionBoundary(
                                        IRBlock(unregister_body),
                                        IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))]),
                                    )
                                ]
                            )
                        )
                    ]
                ),
            )
        )
        module.function_decls.append(IRFunctionDecl(unregister_adapter, CType("void"), unregister_parameters))
        unregister = prefix + "_unregister"
        unregister_body = []
        unregister_cleanup = self._native_cleanup_scope([IRParam(token_c, token.name)], unregister_body)
        unregister_values = [token]
        unregister_releases = []
        if paired:
            unregister_values = []
            for accessor, value_type in (("source", source_type), ("value", native_token_type)):
                slot = IRVarDecl(
                    CType(self._types.render(value_type)), accessor, init=IRCall(f"{token_symbol}_{accessor}", [token])
                )
                unregister_body.extend([slot, IRExprStmt(self._lifetime.register_cleanup_slot(slot, value_type))])
                value = IRVar(slot.name)
                unregister_values.append(value)
                release_locals = []
                release = self._lifetime.release_and_clear(value, value_type, release_locals, slot.c_type.text)
                unregister_releases[0:0] = [*release_locals, *[IRExprStmt(item) for item in release]]
        unregister_body.extend(
            [
                IRExprStmt(IRCall(unregister_adapter, unregister_values)),
                *unregister_releases,
                *unregister_cleanup,
                IRReturn(IRLiteral("true")),
            ]
        )
        module.function_defs.append(
            IRFunctionDef(
                name=unregister,
                return_type=CType("bool"),
                params=[IRParam(token_c, token.name)],
                is_static=True,
                body=IRBlock(unregister_body),
            )
        )
        parameters = [self._signatures.lower_source_param(parameter) for parameter in method.params]
        parameter_types = [parameter.type for parameter in method.params]
        if paired:
            parameters.insert(0, IRParam(CType(self._types.render(source_type)), "self"))
            parameter_types.insert(0, source_type)
        receiver_offset = int(paired)
        adapter_parameters = []
        native_receiver = IRVar(declaration.name)
        if paired:
            adapter_parameters.append(parameters[0])
            native_receiver = IRCast(self._objective_c_object_type(source_type.base), IRVar("self"), bridge="borrow")
        native_arguments = []
        for index, parameter in enumerate(parameters[receiver_offset:-1]):
            if index == callback.parameter_index:
                adapter_parameters.extend(
                    [
                        *[
                            IRParam(CType(value), f"invoke{position}")
                            for position, value in enumerate(invocation_types)
                        ],
                        IRParam(CType("void*"), "context"),
                        IRParam(CType(lifetime_type), "retainContext"),
                        IRParam(CType(lifetime_type), "releaseContext"),
                    ]
                )
                if object_callback:
                    native_arguments.append(IRVar("holder"))
                    continue
                block_parameters = [
                    IRParam(CType(value), f"value{position}")
                    for position, value in enumerate(callback.native_parameters)
                ]
                block_arguments = []
                for block_parameter, value_type in zip(block_parameters, value_types):
                    argument = IRVar(block_parameter.name)
                    info = self._analyzed.class_table.get(value_type.base)
                    if info is not None and info.native_language:
                        argument = IRCast(CType(self._types.render(value_type)), argument, bridge="borrow")
                    block_arguments.append(argument)
                block_arguments.append(IRObjectiveCMessage(IRVar("holder"), "context", []))
                invocation = IRCall(IRVar("invoke0"), block_arguments)
                native_arguments.append(
                    IRObjectiveCBlock(
                        CType(callback.native_return),
                        block_parameters,
                        IRBlock(
                            [
                                IRExprStmt(invocation)
                                if self._types.render(callback.return_type) == "void"
                                else IRReturn(IRCast(CType(callback.native_return), invocation)),
                            ]
                        ),
                    )
                )
            else:
                adapter_parameters.append(parameter)
                value_type = method.params[index].type
                argument = IRVar(parameter.name)
                info = self._analyzed.class_table.get(value_type.base)
                native_arguments.append(
                    IRCast(self._objective_c_object_type(value_type.base), argument, bridge="borrow")
                    if info is not None and info.native_language
                    else self._objective_c_value(value_type, argument, to_native=True)
                )
        adapter_parameters.append(IRParam(CType(f"{native_token_c.text} volatile*"), "nativeResult"))
        holder = IRVar("holder")
        native_body = [
            IRVarDecl(CType(holder_name + "*"), holder.name, init=IRObjectiveCMessage(IRVar(holder_name), "new", [])),
            IRIf(IRBinOp(holder, "==", IRLiteral("nil")), IRBlock([IRReturn(IRLiteral("2"))])),
            IRExprStmt(
                IRObjectiveCMessage(
                    holder,
                    configure_selector,
                    [
                        IRVar("context"),
                        IRVar("retainContext"),
                        IRVar("releaseContext"),
                        *([IRVar(f"invoke{index}") for index in range(len(invokers))] if object_callback else []),
                        *([native_receiver] if action else []),
                    ],
                )
            ),
            IRAssign(
                IRDeref(IRVar("nativeResult")),
                IRCast(
                    native_token_c,
                    IRObjectiveCMessage(native_receiver, descriptor.selector, native_arguments),
                    bridge="retain",
                ),
            ),
            IRReturn(IRLiteral("0")),
        ]
        if object_callback:
            current = IRObjectiveCMessage(native_receiver, callback.getter.selector, [])
            native_body.insert(0, IRIf(IRBinOp(current, "!=", IRLiteral("nil")), IRBlock([IRReturn(IRLiteral("3"))])))
            native_body[-2:-1] = [
                IRExprStmt(IRObjectiveCMessage(native_receiver, descriptor.selector, native_arguments)),
                IRIf(IRBinOp(current, "!=", holder), IRBlock([IRReturn(IRLiteral("4"))])),
                IRAssign(IRDeref(IRVar("nativeResult")), IRCast(native_token_c, holder, bridge="retain")),
            ]
            if action:
                selector = IRObjectiveCMessage(native_receiver, callback.action_getter.selector, [])
                native_body.insert(
                    1, IRIf(IRBinOp(selector, "!=", IRLiteral("NULL")), IRBlock([IRReturn(IRLiteral("3"))]))
                )
                native_body[-2:-2] = [
                    IRExprStmt(
                        IRObjectiveCMessage(
                            native_receiver, callback.action_setter.selector, [IRObjectiveCSelector("btrcInvoke:")]
                        )
                    ),
                    IRIf(
                        IRBinOp(selector, "!=", IRObjectiveCSelector("btrcInvoke:")),
                        IRBlock([IRReturn(IRLiteral("4"))]),
                    ),
                    IRIf(IRBinOp(current, "!=", holder), IRBlock([IRReturn(IRLiteral("4"))])),
                ]
        native.function_defs.append(
            IRFunctionDef(
                name=prefix,
                return_type=CType("int"),
                params=adapter_parameters,
                body=IRBlock(
                    [
                        IRObjectiveCAutoreleasePool(
                            IRBlock(
                                [
                                    IRObjectiveCExceptionBoundary(
                                        IRBlock(native_body),
                                        IRBlock([IRReturn(IRLiteral("1"))]),
                                    )
                                ]
                            )
                        )
                    ]
                ),
            )
        )
        module.function_decls.append(IRFunctionDecl(prefix, CType("int"), adapter_parameters))
        body = []
        cleanup = self._native_cleanup_scope(parameters, body)
        arguments = [IRVar(parameter.name) for parameter in parameters]
        releases = []
        for index, (parameter, value_type) in enumerate(zip(parameters, parameter_types)):
            if value_type.base in self._analyzed.class_table or value_type.base in self._analyzed.interface_table:
                if not value_type.is_nullable:
                    body.append(
                        self._objective_c_null_guard(
                            arguments[index], f"Stored callback {descriptor.name}: null {parameter.name}"
                        )
                    )
                arguments[index] = self._native_lease(index, value_type, arguments[index], parameters, body, releases)
        if paired:
            pair_slot = IRVarDecl(token_c, "cancellationToken", init=IRCall(f"{token_symbol}_new", [arguments[0]]))
            body.extend([pair_slot, IRExprStmt(self._lifetime.register_cleanup_slot(pair_slot, token_type))])
        context_slot = IRVarDecl(
            context_c,
            "context",
            init=IRCall(
                f"{context_symbol}_new",
                [arguments[callback.parameter_index + receiver_offset], IRFunctionRef(unregister)],
            ),
        )
        context = IRVar(context_slot.name)
        body.extend([context_slot, IRExprStmt(self._lifetime.register_cleanup_slot(context_slot, context_type))])
        body.append(IRExprStmt(IRCall(f"{context_symbol}_activate", [context, arguments[-1]])))
        token_slot = IRVarDecl(native_token_c, "nativeResult", init=IRLiteral("NULL"))
        body.extend([token_slot, IRExprStmt(self._lifetime.register_cleanup_slot(token_slot, native_token_type))])
        adapter_arguments = []
        for index, argument in enumerate(arguments[:-1]):
            adapter_arguments.extend(
                [
                    *[IRFunctionRef(invoke) for invoke in invokers],
                    IRCast(CType("void*"), context),
                    IRFunctionRef(prefix + "_retain"),
                    IRFunctionRef(prefix + "_release"),
                ]
                if index == callback.parameter_index + receiver_offset
                else [argument]
            )
        adapter_arguments.append(IRAddressOf(IRVar(token_slot.name)))
        body.append(IRVarDecl(CType("int"), "activationStatus", init=IRCall(prefix, adapter_arguments)))
        if object_callback:
            body.append(
                IRIf(
                    IRBinOp(IRVar("activationStatus"), "==", IRLiteral("3")),
                    IRBlock(
                        [
                            IRExprStmt(IRCall(f"{context_symbol}_abortActivation", [context])),
                            self._objective_c_null_guard(
                                IRLiteral("NULL"),
                                "Native action slots are already occupied"
                                if action
                                else "Native delegate slot is already occupied",
                            ),
                        ]
                    ),
                )
            )
        body.append(
            IRIf(
                IRBinOp(IRVar("activationStatus"), "!=", IRLiteral("0")),
                self._stored_activation_failure(
                    callback,
                    context_symbol,
                    context,
                    f"Stored callback {descriptor.name}: activation failed before publication",
                ),
            )
        )
        body.append(
            IRIf(
                IRBinOp(IRVar(token_slot.name), "==", IRLiteral("NULL")),
                self._stored_activation_failure(
                    callback,
                    context_symbol,
                    context,
                    f"Stored callback {descriptor.name}: null cancellation token",
                ),
            )
        )
        published_token = IRVar(token_slot.name)
        if paired:
            published_token = IRVar(pair_slot.name)
            body.append(IRExprStmt(IRCall(f"{token_symbol}_publish", [published_token, IRVar(token_slot.name)])))
        body.append(IRExprStmt(IRCall(f"{context_symbol}_publish", [context, published_token])))
        token_release_locals = []
        token_release = self._lifetime.release_and_clear(
            IRVar(token_slot.name), native_token_type, token_release_locals, native_token_c.text
        )
        if paired:
            token_release.extend(
                self._lifetime.release_and_clear(published_token, token_type, token_release_locals, token_c.text)
            )
        body.extend(
            [
                *token_release_locals,
                *[IRExprStmt(value) for value in token_release],
                *releases,
                *cleanup,
                IRReturn(context),
            ]
        )
        module.function_decls.append(IRFunctionDecl(name, context_c, parameters, is_static=True))
        module.function_defs.append(
            IRFunctionDef(name=name, return_type=context_c, params=parameters, is_static=True, body=IRBlock(body))
        )

    def _stored_activation_failure(self, callback, context_symbol, context, message):
        if callback.activation_failure == "abort":
            return IRBlock(
                [
                    IRExprStmt(
                        IRCall(
                            "fputs",
                            [
                                IRLiteral(
                                    json.dumps("BTRC stored callback activation failed: publication state is unknown\n")
                                ),
                                IRVar("stderr"),
                            ],
                        )
                    ),
                    IRExprStmt(IRCall("abort", [], never_returns=True)),
                ]
            )
        return IRBlock(
            [
                IRExprStmt(IRCall(f"{context_symbol}_abortActivation", [context])),
                self._objective_c_null_guard(IRLiteral("NULL"), message),
            ]
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
