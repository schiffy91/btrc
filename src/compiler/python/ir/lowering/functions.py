"""Cohesive functions IR lowering owner."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar

from src.compiler.python.abi.native_generated import NativeAlias, NativeEnumType, NativeQualifiedType
from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.frontend.native_imports import (
    NativeActionProjection,
    NativeControlActionProjection,
    NativeDelegateProjection,
    NativeHeaderSource,
    NativeInstantiatedProjection,
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
    IRCxxDelete,
    IRCxxExceptionBoundary,
    IRCxxNew,
    IRDeref,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRGlobalDecl,
    IRIf,
    IRInclude,
    IRIndex,
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
    IRSizeof,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
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
from .types import CodegenError, CTypeLowerer

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
        self._native_resources = {
            declaration.name: declaration.source_file.resource
            for declaration in analyzed.program.declarations
            if isinstance(getattr(declaration, "source_file", None), NativeHeaderSource)
            and declaration.source_file.resource is not None
        }
        # The C type each resource's adapters convert to: a COM interface is
        # its record pointer (`IStream*`), a reference-counted resource its typedef.
        self._native_spellings = {
            declaration.name: declaration.source_file.type_spelling or declaration.source_file.resource.name
            for declaration in analyzed.program.declarations
            if isinstance(getattr(declaration, "source_file", None), NativeHeaderSource)
            and declaration.source_file.resource is not None
        }

    def _unique_resource(self, name):
        resource = self._native_resources.get(name)
        return resource if resource is not None and resource.ownership == "unique" else None

    def _com_resource(self, name):
        resource = self._native_resources.get(name)
        return resource if resource is not None and resource.ownership == "com" else None

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
        if any(getattr(callback, "realtime", None) is not None for callback in contract.callbacks):
            self._emit_realtime_c_adapter(declaration, contract)
            return
        if any(callback.one_shot for callback in contract.callbacks):
            self._emit_one_shot_c_adapter(declaration, contract)
            return
        if any(getattr(callback, "registration_contexts", ()) for callback in contract.callbacks):
            self._emit_stored_c_adapter(declaration, contract)
            return
        if any(isinstance(callback, NativeInstantiatedProjection) for callback in contract.callbacks):
            self._emit_instantiated_adapter(declaration, contract)
            return
        if contract.callback_table is not None:
            self._emit_callback_table_adapter(declaration, contract)
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
            or contract.record_snapshot
            or contract.owned_output
            or contract.copied_result
            or leases
            or any(field.managed for record in contract.record_types for field in record.fields)
        ):
            cleanup = self._native_cleanup_scope(parameters, statements)
            for index in sorted(leases):
                arguments[index] = self._native_lease(
                    index,
                    declaration.params[index].type,
                    arguments[index],
                    parameters,
                    statements,
                    releases,
                    attachment=bool(contract.copied_input and index == contract.copied_input.owner_index),
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
                if contract.copied_input and index == contract.copied_input.owner_index:
                    continue
                arguments[index] = (
                    IRTernary(arguments[index], IRFieldAccess(arguments[index], "value", arrow=True), IRLiteral("NULL"))
                    if self._unique_resource(resource)
                    else IRCast(target_type=CType(text=self._native_spellings[resource]), expr=arguments[index])
                )
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
        if contract.bound_parameter >= 0:
            arguments.insert(contract.bound_parameter, IRVar(name=contract.bound_constant))
        call = IRCall(callee=declaration.name, args=arguments)
        if contract.copied_input:
            self._native_copied_input(
                declaration, contract.copied_input, arguments, parameters, statements, releases, cleanup
            )
            call = None
        elif contract.record_snapshot:
            self._native_record_snapshot(
                declaration, contract.record_snapshot, arguments, parameters, statements, releases, cleanup
            )
            call = None
        elif contract.copied_result:
            self._native_copied_result(declaration, contract, arguments, parameters, statements, releases, cleanup)
            call = None
        elif contract.owned_output:
            self._native_owned_output(
                declaration, contract.owned_output, arguments, parameters, statements, releases, cleanup
            )
            call = None
        elif self._unique_resource(contract.resource_result):
            self._native_unique_result(declaration, call, parameters, statements, releases, cleanup)
            call = None
        if contract.resource_result:
            if call is not None and self._com_resource(contract.resource_result) and contract.borrowed_result_owner < 0:
                # A factory's interface pointer is one claim, counted against the apartment.
                call = IRCall(f"__btrc_com_{contract.resource_result}_adopt", [call])
            call = IRCast(target_type=return_type, expr=call) if call is not None else None
        if call is None:
            pass
        elif contract.record_output:
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
            if contract.borrowed_result_owner >= 0:
                # The declared foreign lifetime promise extends through this
                # retain. No argument lease may end before the claim is owned.
                statements.append(
                    IRExprStmt(expr=self._lifetime.retain_value(IRVar(name=result), declaration.return_type))
                )
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

    def _native_copied_result(self, declaration, contract, arguments, parameters, statements, releases, cleanup):
        projection = contract.copied_result
        names = {parameter.name for parameter in parameters}
        locals = []
        for stem in ("copied_result", "copied_pointer", "copied_length"):
            name = "__btrc_native_" + stem
            while name in names:
                name += "_"
            names.add(name)
            locals.append(name)
        result, pointer, length = (IRVar(name) for name in locals)
        result_type = declaration.return_type
        slot = IRVarDecl(CType(self._types.render(result_type)), locals[0], init=IRLiteral("NULL"))
        statements.extend(
            [
                slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(slot, result_type)),
                IRVarDecl(
                    CType("const char*" if projection.kind == "string" else "const void*"),
                    locals[1],
                    init=IRCall(declaration.name, arguments),
                ),
            ]
        )
        if contract.nonnull_return:
            statements.append(self._native_null_guard(pointer, f"Native call {declaration.name}: null result"))
        if projection.kind == "string":
            self._session.require_helper("__btrc_string_alloc")
            statements.append(
                IRIf(
                    IRBinOp(pointer, "!=", IRLiteral("NULL")),
                    IRBlock(
                        [
                            IRVarDecl(CType("size_t"), locals[2], init=IRCall("strlen", [pointer])),
                            IRIf(
                                IRBinOp(length, "<=", IRLiteral("2147483647U")),
                                IRBlock(
                                    [
                                        IRAssign(result, IRCall("__btrc_string_alloc", [IRCast(CType("int"), length)])),
                                        IRExprStmt(IRCall("memcpy", [result, pointer, length])),
                                    ]
                                ),
                            ),
                        ]
                    ),
                )
            )
        else:
            statements.extend(
                [
                    IRVarDecl(
                        CType("int"),
                        locals[2],
                        init=IRCall(
                            projection.length_function, [arguments[index] for index in projection.length_arguments]
                        ),
                    ),
                    IRIf(
                        IRBinOp(
                            IRBinOp(
                                IRBinOp(length, ">=", IRLiteral("0")),
                                "&&",
                                IRBinOp(length, "<=", IRLiteral("2147483646")),
                            ),
                            "&&",
                            IRBinOp(
                                IRBinOp(pointer, "!=", IRLiteral("NULL")), "||", IRBinOp(length, "==", IRLiteral("0"))
                            ),
                        ),
                        IRBlock([IRAssign(result, IRCall("Bytes_fromRaw", [IRCast(CType("char*"), pointer), length]))]),
                    ),
                ]
            )
        statements.extend([*releases, *cleanup, IRReturn(result)])

    def _native_owned_output(self, declaration, output, arguments, parameters, statements, releases, cleanup):
        if output.initializer:
            self._native_initializer(declaration, output, arguments, parameters, statements, releases, cleanup)
            return
        if output.sized_resource:
            self._native_resource_output(declaration, output, arguments, parameters, statements, releases, cleanup)
            return
        name = "__btrc_native_owned_output"
        while any(parameter.name == name for parameter in parameters):
            name += "_"
        owner_type = declaration.return_type
        owner_c = CType(self._types.render(owner_type))
        slot = IRVarDecl(owner_c, name, init=IRCall(f"{output.result_name}_new", []))
        owner = IRVar(name)
        if self._com_resource(output.resource):
            # The [out] interface lands in a zeroed slot; a nonnull one is one
            # adopted claim on every HRESULT, which the caller inspects.
            interface = IRVar(name + "_interface")
            statements.extend(
                [
                    slot,
                    IRExprStmt(self._lifetime.register_cleanup_slot(slot, owner_type)),
                    IRVarDecl(CType(self._native_spellings[output.resource]), interface.name, init=IRLiteral("NULL")),
                ]
            )
            arguments.insert(output.parameter_index, IRAddressOf(interface))
            statements.extend(
                [
                    IRAssign(IRFieldAccess(owner, "status", arrow=True), IRCall(declaration.name, arguments)),
                    IRAssign(
                        IRFieldAccess(owner, "value", arrow=True),
                        IRCast(
                            CType(f"struct __btrc_native_{output.resource}*"),
                            IRCall(f"__btrc_com_{output.resource}_adopt", [interface]),
                        ),
                    ),
                    *releases,
                    *cleanup,
                    IRReturn(owner),
                ]
            )
            return
        child = IRFieldAccess(owner, "value", arrow=True)
        native = IRFieldAccess(child, "value", arrow=True)
        statements.extend(
            [
                slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(slot, owner_type)),
                IRAssign(child, IRCall(f"__btrc_unique_{output.resource}_new", [])),
            ]
        )
        offset = output.offset
        if offset:
            visible = [index for index in range(len(arguments) + 2) if not output.hides(index)]
            native_arguments = dict(zip(visible, arguments, strict=True))
            reserved = {parameter.name for parameter in parameters} | {name}
            offset_names = []
            for stem in ("tail", "tail_base", "tail_address"):
                local = f"__btrc_native_{stem}"
                while local in reserved:
                    local += "_"
                reserved.add(local)
                offset_names.append(local)
            tail, base, address = (IRVar(local) for local in offset_names)
            source, length = native_arguments[offset.input_index], native_arguments[offset.length_index]
            statements.extend(
                [
                    IRVarDecl(CType("const char*"), offset_names[0], init=IRLiteral("NULL")),
                    IRIf(
                        IRBinOp(length, "<", IRLiteral("0")),
                        self._native_null_guard(
                            IRLiteral("NULL"), f"Native call {declaration.name}: negative bounded input length"
                        ).then_block,
                    ),
                ]
            )
            native_arguments[output.parameter_index] = IRAddressOf(native)
            native_arguments[offset.parameter_index] = IRAddressOf(tail)
            arguments = [native_arguments[index] for index in range(len(native_arguments))]
        else:
            arguments.insert(output.parameter_index, IRAddressOf(native))
        statements.append(IRAssign(IRFieldAccess(owner, "status", arrow=True), IRCall(declaration.name, arguments)))
        if offset:
            difference = IRBinOp(address, "-", base)
            valid = IRBinOp(
                IRBinOp(IRBinOp(tail, "!=", IRLiteral("NULL")), "&&", IRBinOp(source, "!=", IRLiteral("NULL"))),
                "&&",
                IRBinOp(
                    IRBinOp(address, ">=", base), "&&", IRBinOp(difference, "<=", IRCast(CType("uintptr_t"), length))
                ),
            )
            statements.extend(
                [
                    IRVarDecl(CType("uintptr_t"), offset_names[1], init=IRCast(CType("uintptr_t"), source)),
                    IRVarDecl(CType("uintptr_t"), offset_names[2], init=IRCast(CType("uintptr_t"), tail)),
                    IRAssign(IRFieldAccess(owner, offset.field, arrow=True), IRLiteral("-1")),
                    IRIf(
                        valid,
                        IRBlock(
                            [IRAssign(IRFieldAccess(owner, offset.field, arrow=True), IRCast(CType("int"), difference))]
                        ),
                    ),
                ]
            )
        statements.append(
            IRIf(
                IRBinOp(native, "==", IRLiteral("NULL")),
                IRBlock(
                    [
                        IRExprStmt(IRCall(f"__btrc_native_{output.resource}_release", [child])),
                        IRAssign(child, IRLiteral("NULL")),
                    ]
                ),
            )
        )
        statements.extend([*releases, *cleanup, IRReturn(owner)])

    def _native_copied_input(self, declaration, shape, arguments, parameters, statements, releases, cleanup):
        owner = arguments[shape.owner_index]
        source, length = arguments[shape.input_index], arguments[shape.length_index]
        backing = IRFieldAccess(owner, "input", arrow=True)
        called_name = "__btrc_native_input_called"
        while any(parameter.name == called_name for parameter in parameters):
            called_name += "_"
        called = IRVar(called_name)
        invalid = self._native_null_guard(
            IRLiteral("NULL"), f"Native call {declaration.name}: invalid copied input span"
        )
        invalid.condition = IRBinOp(
            IRBinOp(IRCast(CType("uintmax_t"), length), ">", IRCast(CType("uintmax_t"), IRVar("SIZE_MAX"))),
            "||",
            IRBinOp(IRBinOp(length, "!=", IRLiteral("0")), "&&", IRBinOp(source, "==", IRLiteral("NULL"))),
        )
        native_arguments = list(arguments)
        native_arguments[shape.owner_index] = IRFieldAccess(owner, "value", arrow=True)
        native_arguments[shape.input_index] = backing
        statements.extend(
            [
                IRVarDecl(CType("bool"), called_name, init=IRLiteral("false")),
                invalid,
                IRAssign(
                    backing,
                    IRCall(
                        "calloc",
                        [IRLiteral("1"), IRTernary(IRBinOp(length, "==", IRLiteral("0")), IRLiteral("1"), length)],
                    ),
                ),
                IRIf(
                    IRBinOp(backing, "!=", IRLiteral("NULL")),
                    IRBlock(
                        [
                            IRIf(
                                IRBinOp(length, "!=", IRLiteral("0")),
                                IRBlock([IRExprStmt(IRCall("memcpy", [backing, source, length]))]),
                            ),
                            IRExprStmt(IRCall(declaration.name, native_arguments)),
                            IRAssign(IRFieldAccess(owner, "inputAttached", arrow=True), IRLiteral("true")),
                            IRAssign(called, IRLiteral("true")),
                        ]
                    ),
                ),
                *releases,
                *cleanup,
                IRReturn(called),
            ]
        )

    def _native_initializer(self, declaration, output, arguments, parameters, statements, releases, cleanup):
        name = "__btrc_native_initializer"
        while any(parameter.name == name for parameter in parameters):
            name += "_"
        owner_type = declaration.return_type
        owner = IRVar(name)
        child = IRFieldAccess(owner, "value", arrow=True)
        storage = IRFieldAccess(child, "storage", arrow=True)
        backing = IRFieldAccess(child, "input", arrow=True)
        native = IRFieldAccess(child, "value", arrow=True)
        called = IRFieldAccess(owner, "called", arrow=True)
        status = IRFieldAccess(owner, "status", arrow=True)
        slot = IRVarDecl(CType(self._types.render(owner_type)), name, init=IRCall(f"{output.result_name}_new", []))
        statements.extend(
            [
                slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(slot, owner_type)),
                IRAssign(child, IRCall(f"__btrc_unique_{output.resource}_new", [])),
                IRAssign(storage, IRCall("calloc", [IRLiteral("1"), IRSizeof(operand=IRDeref(storage))])),
            ]
        )
        shape = output.initializer
        arguments = list(arguments)
        arguments.insert(output.parameter_index, storage)
        ready = IRBinOp(storage, "!=", IRLiteral("NULL"))
        if shape.copied_input >= 0:
            source, length = arguments[shape.copied_input], arguments[shape.length]
            self._session.require_helper("__btrc_safe_calloc")
            invalid = self._native_null_guard(
                IRLiteral("NULL"), f"Native call {declaration.name}: invalid copied input span"
            )
            invalid.condition = IRBinOp(
                IRBinOp(IRCast(CType("uintmax_t"), length), ">", IRCast(CType("uintmax_t"), IRVar("SIZE_MAX"))),
                "||",
                IRBinOp(IRBinOp(length, "!=", IRLiteral("0")), "&&", IRBinOp(source, "==", IRLiteral("NULL"))),
            )
            statements.extend(
                [
                    invalid,
                    IRIf(
                        ready,
                        IRBlock(
                            [
                                IRAssign(
                                    backing,
                                    IRCall(
                                        "calloc",
                                        [
                                            IRLiteral("1"),
                                            IRTernary(IRBinOp(length, "==", IRLiteral("0")), IRLiteral("1"), length),
                                        ],
                                    ),
                                ),
                                IRIf(
                                    IRBinOp(
                                        IRBinOp(backing, "!=", IRLiteral("NULL")),
                                        "&&",
                                        IRBinOp(length, "!=", IRLiteral("0")),
                                    ),
                                    IRBlock([IRExprStmt(IRCall("memcpy", [backing, source, length]))]),
                                ),
                            ]
                        ),
                    ),
                ]
            )
            ready = IRBinOp(ready, "&&", IRBinOp(backing, "!=", IRLiteral("NULL")))
            arguments[shape.copied_input] = IRTernary(source, backing, IRLiteral("NULL"))
        statements.append(
            IRIf(
                ready,
                IRBlock(
                    [
                        IRAssign(status, IRCall(declaration.name, arguments)),
                        IRAssign(called, IRLiteral("true")),
                        IRIf(
                            IRBinOp(
                                status,
                                "==" if shape.success else "!=",
                                IRVar(shape.success) if shape.success else IRLiteral("0"),
                            ),
                            IRBlock([IRAssign(native, storage)]),
                        ),
                    ]
                ),
            )
        )
        statements.append(
            IRIf(
                IRBinOp(native, "==", IRLiteral("NULL")),
                IRBlock(
                    [
                        IRExprStmt(IRCall(f"__btrc_native_{output.resource}_release", [child])),
                        IRAssign(child, IRLiteral("NULL")),
                    ]
                ),
            )
        )
        statements.extend([*releases, *cleanup, IRReturn(owner)])

    def _native_resource_output(self, declaration, output, arguments, parameters, statements, releases, cleanup):
        names = {parameter.name for parameter in parameters}
        slots = []
        for stem in ("owner", "value", "size"):
            name = "__btrc_native_output_" + stem
            while name in names:
                name += "_"
            names.add(name)
            slots.append(name)
        owner_name, value_name, size_name = slots
        owner_type = declaration.return_type
        value_type = TypeExpr(base=output.resource, is_nullable=True, pointer_depth=1)
        owner_slot = IRVarDecl(
            CType(self._types.render(owner_type)), owner_name, init=IRCall(output.result_name + "_new", [])
        )
        value_slot = IRVarDecl(CType(output.resource), value_name, init=IRLiteral("NULL"), is_volatile=True)
        size_slot = IRVarDecl(
            CType(self._types.render(output.sized_resource.size_type)),
            size_name,
            init=IRSizeof(operand=CType(output.resource)),
            is_volatile=True,
        )
        owner, value, size = IRVar(owner_name), IRVar(value_name), IRVar(size_name)
        statements.extend(
            [
                owner_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(owner_slot, owner_type)),
                value_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(value_slot, value_type)),
                size_slot,
            ]
        )
        native_arguments = []
        cursor = 0
        for index in range(len(arguments) + 2):
            if index == output.parameter_index:
                native_arguments.append(IRCast(CType("void*"), IRAddressOf(value)))
            elif index == output.sized_resource.size_index:
                native_arguments.append(
                    IRCast(CType(self._types.render(output.sized_resource.size_type) + "*"), IRAddressOf(size))
                )
            else:
                native_arguments.append(arguments[cursor])
                cursor += 1
        statements.extend(
            [
                IRAssign(
                    IRFieldAccess(owner, "status", arrow=True),
                    IRCall(output.sized_resource.native_function, native_arguments),
                ),
                IRAssign(IRFieldAccess(owner, "size", arrow=True), size),
                IRAssign(
                    IRFieldAccess(owner, "sizeValid", arrow=True),
                    IRBinOp(size, "==", IRSizeof(operand=CType(output.resource))),
                ),
                IRAssign(
                    IRFieldAccess(owner, "value", arrow=True), IRCast(CType(self._types.render(value_type)), value)
                ),
                IRAssign(value, IRLiteral("NULL")),
                *releases,
                *cleanup,
                IRReturn(owner),
            ]
        )

    def _native_record_snapshot(self, declaration, snapshot, arguments, parameters, statements, releases, cleanup):
        failure = [*releases, *cleanup, IRReturn(IRLiteral("NULL"))]
        if snapshot.byte_field or snapshot.strings:
            statements.append(IRIf(IRBinOp(arguments[1], "<", IRLiteral("0")), IRBlock(list(failure))))
        if snapshot.guard_path:
            guard = self._native_snapshot_path(snapshot.guard_path, arguments[0], statements, failure)
            statements.append(IRIf(IRBinOp(guard, "!=", IRVar(snapshot.guard_constant)), IRBlock(list(failure))))
            self._session.module.native_external_names.add(snapshot.guard_constant)
        values = []
        for index, path in enumerate(snapshot.paths):
            value = self._native_snapshot_path(path, arguments[0], statements, failure)
            name = f"__btrc_snapshot_field_{index}"
            statements.append(IRVarDecl(CType(self._types.render(path.value_type)), name, init=value))
            values.append(IRVar(name))
        plane = None
        if snapshot.byte_field:
            plane = (self._native_snapshot_span if snapshot.byte_span else self._native_snapshot_plane)(
                snapshot.byte_paths, arguments, statements, failure
            )
        strings = []
        for index, (name, path) in enumerate(snapshot.strings):
            value = self._native_snapshot_path(path, arguments[0], statements, failure)
            pointer, length = IRVar(f"__btrc_snapshot_string_{index}"), IRVar(f"__btrc_snapshot_length_{index}")
            statements.extend(
                [
                    IRVarDecl(CType("const char*"), pointer.name, init=IRCast(CType("const char*"), value)),
                    IRVarDecl(CType("size_t"), length.name, init=IRLiteral("0")),
                    IRIf(
                        IRBinOp(pointer, "!=", IRLiteral("NULL")),
                        IRBlock(
                            [
                                IRWhile(
                                    IRBinOp(
                                        IRBinOp(length, "<=", IRCast(CType("size_t"), arguments[1])),
                                        "&&",
                                        IRBinOp(IRDeref(IRBinOp(pointer, "+", length)), "!=", IRLiteral("0")),
                                    ),
                                    IRBlock([IRAssign(length, IRBinOp(length, "+", IRLiteral("1")))]),
                                ),
                                IRIf(
                                    IRBinOp(
                                        IRBinOp(length, ">", IRCast(CType("size_t"), arguments[1])),
                                        "||",
                                        IRBinOp(length, ">", IRLiteral("2147483646U")),
                                    ),
                                    IRBlock(list(failure)),
                                ),
                            ]
                        ),
                    ),
                ]
            )
            strings.append((name, pointer, length))
        owner_name = "__btrc_snapshot_result"
        owner = IRVar(owner_name)
        owner_slot = IRVarDecl(
            CType(self._types.render(declaration.return_type)),
            owner_name,
            init=IRCall(snapshot.result_name + "_new", []),
        )
        statements.extend(
            [owner_slot, IRExprStmt(self._lifetime.register_cleanup_slot(owner_slot, declaration.return_type))]
        )
        for field, value in zip(snapshot.fields, values, strict=True):
            statements.append(IRAssign(IRFieldAccess(owner, field.name, arrow=True), value))
        if strings:
            self._session.require_helper("__btrc_string_alloc")
        for name, pointer, length in strings:
            field = IRFieldAccess(owner, name, arrow=True)
            statements.append(
                IRIf(
                    IRBinOp(pointer, "!=", IRLiteral("NULL")),
                    IRBlock(
                        [
                            IRAssign(field, IRCall("__btrc_string_alloc", [IRCast(CType("int"), length)])),
                            IRExprStmt(IRCall("memcpy", [field, pointer, length])),
                        ]
                    ),
                )
            )
        if snapshot.byte_field:
            statements.append(
                IRExprStmt(
                    self._lifetime.replace_edge_value(
                        IRFieldAccess(owner, snapshot.byte_field, arrow=True),
                        IRCall("Bytes_fromRaw", [IRCast(CType("char*"), plane[0]), IRCast(CType("int"), plane[1])]),
                        TypeExpr(base="Bytes", pointer_depth=1),
                        owner,
                        adopt=True,
                    )
                )
            )
        statements.extend([*releases, *cleanup, IRReturn(owner)])

    def _native_snapshot_span(self, paths, arguments, statements, failure):
        length_path = paths[1]
        length = IRVar("__btrc_snapshot_length")
        pointer = IRVar("__btrc_snapshot_pointer")
        value = self._native_snapshot_path(length_path, arguments[0], statements, failure)
        statements.append(IRVarDecl(CType(self._types.render(length_path.value_type)), length.name, init=value))
        if not length_path.value_type.base.startswith("unsigned"):
            statements.append(IRIf(IRBinOp(length, "<", IRLiteral("0")), IRBlock(list(failure))))
        wide = IRCast(CType("uintmax_t"), length)
        statements.append(
            IRIf(
                IRBinOp(
                    IRBinOp(wide, ">", IRCast(CType("uintmax_t"), arguments[1])),
                    "||",
                    IRBinOp(wide, ">", IRLiteral("2147483646U")),
                ),
                IRBlock(list(failure)),
            )
        )
        value = self._native_snapshot_path(paths[0], arguments[0], statements, failure)
        statements.extend(
            [
                IRVarDecl(
                    CType("const unsigned char*"), pointer.name, init=IRCast(CType("const unsigned char*"), value)
                ),
                IRIf(
                    IRBinOp(IRBinOp(length, "!=", IRLiteral("0")), "&&", IRBinOp(pointer, "==", IRLiteral("NULL"))),
                    IRBlock(list(failure)),
                ),
                IRIf(
                    IRBinOp(
                        wide,
                        ">",
                        IRBinOp(
                            IRCast(CType("uintmax_t"), IRVar("UINTPTR_MAX")),
                            "-",
                            IRCast(CType("uintmax_t"), IRCast(CType("uintptr_t"), pointer)),
                        ),
                    ),
                    IRBlock(list(failure)),
                ),
            ]
        )
        return pointer, length

    def _native_snapshot_plane(self, paths, arguments, statements, failure):
        width, rows, pitch, pointer, span, stride, offset, address = (
            IRVar("__btrc_snapshot_" + name)
            for name in ("width", "rows", "pitch", "pointer", "span", "stride", "offset", "address")
        )
        for name, path in ((width.name, paths[1]), (rows.name, paths[2])):
            value = self._native_snapshot_path(path, arguments[0], statements, failure)
            statements.append(IRVarDecl(CType(self._types.render(path.value_type)), name, init=value))
            if not path.value_type.base.startswith("unsigned"):
                statements.append(IRIf(IRBinOp(IRVar(name), "<", IRLiteral("0")), IRBlock(list(failure))))
        statements.extend(
            [
                IRVarDecl(CType("const unsigned char*"), pointer.name, init=IRLiteral("NULL")),
                IRVarDecl(CType("unsigned long long"), span.name, init=IRLiteral("0ULL")),
            ]
        )
        nonempty = []
        value = self._native_snapshot_path(paths[3], arguments[0], nonempty, failure)
        nonempty.extend(
            [
                IRVarDecl(CType("long long"), pitch.name, init=IRCast(CType("long long"), value)),
                IRVarDecl(
                    CType("unsigned long long"),
                    stride.name,
                    init=IRTernary(
                        IRBinOp(pitch, "<", IRLiteral("0LL")),
                        IRBinOp(IRLiteral("0ULL"), "-", IRCast(CType("unsigned long long"), pitch)),
                        IRCast(CType("unsigned long long"), pitch),
                    ),
                ),
                IRIf(IRBinOp(stride, "==", IRLiteral("0ULL")), IRBlock(list(failure))),
                IRIf(
                    IRBinOp(
                        IRCast(CType("unsigned long long"), rows),
                        ">",
                        IRBinOp(IRCast(CType("unsigned long long"), arguments[1]), "/", stride),
                    ),
                    IRBlock(list(failure)),
                ),
                IRAssign(span, IRBinOp(IRCast(CType("unsigned long long"), rows), "*", stride)),
                IRIf(IRBinOp(span, ">", IRLiteral("2147483646ULL")), IRBlock(list(failure))),
            ]
        )
        data = self._native_snapshot_path(paths[0], arguments[0], nonempty, failure)
        nonempty.extend(
            [
                IRAssign(pointer, IRCast(CType("const unsigned char*"), data)),
                IRIf(IRBinOp(pointer, "==", IRLiteral("NULL")), IRBlock(list(failure))),
                IRVarDecl(CType("uintptr_t"), address.name, init=IRCast(CType("uintptr_t"), pointer)),
                IRVarDecl(CType("unsigned long long"), offset.name, init=IRBinOp(span, "-", stride)),
                IRIf(
                    IRBinOp(pitch, "<", IRLiteral("0LL")),
                    IRBlock(
                        [
                            IRIf(
                                IRBinOp(IRCast(CType("unsigned long long"), address), "<=", offset),
                                IRBlock(list(failure)),
                            ),
                            IRAssign(address, IRBinOp(address, "-", IRCast(CType("uintptr_t"), offset))),
                        ]
                    ),
                ),
                IRIf(
                    IRBinOp(
                        span,
                        ">",
                        IRBinOp(
                            IRCast(CType("unsigned long long"), IRVar("UINTPTR_MAX")),
                            "-",
                            IRCast(CType("unsigned long long"), address),
                        ),
                    ),
                    IRBlock(list(failure)),
                ),
                IRIf(
                    IRBinOp(pitch, "<", IRLiteral("0LL")),
                    IRBlock([IRAssign(pointer, IRBinOp(pointer, "-", IRCast(CType("size_t"), offset)))]),
                ),
            ]
        )
        statements.append(
            IRIf(
                IRBinOp(IRBinOp(width, "!=", IRLiteral("0")), "&&", IRBinOp(rows, "!=", IRLiteral("0"))),
                IRBlock(nonempty),
            )
        )
        return pointer, span

    def _native_snapshot_path(self, path, root, statements, failure):
        value = root
        for field, pointer in path.steps:
            if pointer:
                statements.append(IRIf(IRBinOp(value, "==", IRLiteral("NULL")), IRBlock(list(failure))))
            value = IRFieldAccess(value, field, arrow=pointer)
        return value

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

    def _emit_realtime_c_adapter(self, declaration, contract):
        """Publish one pre-owned receiver and stable native lease, never ARC on ingress."""
        callback = contract.callbacks[0]
        shape = callback.realtime
        prefix = contract.adapter_symbol(declaration.name)
        context_name = prefix + "_context"
        context_type = CType("struct " + context_name + "*")
        receiver_type = TypeExpr(base=callback.interface, pointer_depth=1)
        owner_type = TypeExpr(base=shape.resource, pointer_depth=1)
        unique_prefix = "__btrc_unique_" + shape.resource
        context = IRVar("context")
        owner = IRFieldAccess(context, "owner", arrow=True)
        receiver = IRFieldAccess(context, "receiver", arrow=True)
        gate = IRFieldAccess(context, "gate", arrow=True)
        unit = IRFieldAccess(owner, "value", arrow=True)
        payload = [
            IRParam(CType(self._types.render(value)), f"argument{index}")
            for index, value in enumerate(callback.parameters)
            if not callback.is_context(index)
        ]
        result_type = CType(self._types.render(callback.return_type))
        fallback_name = prefix + "_fallback"
        interface_table = f"__btrc_interface_{len(callback.interface)}_{callback.interface}"
        self._session.module.function_pointer_typedefs.append(
            IRFunctionPointerTypedef(fallback_name, result_type, [value.c_type for value in payload])
        )
        self._session.module.struct_defs.append(
            IRStructDef(
                context_name,
                [
                    IRStructField(CType(self._types.render(receiver_type)), "receiver"),
                    IRStructField(CType(self._types.render(owner_type)), "owner"),
                    IRStructField(
                        CType(
                            self._types.render(
                                TypeExpr(base="Atomic", generic_args=[TypeExpr(base="uint")], pointer_depth=1)
                            )
                        ),
                        "gate",
                    ),
                    IRStructField(CType(fallback_name), "denied"),
                    IRStructField(CType(interface_table + "_invoke_fn"), "invoke"),
                ],
            )
        )
        self._session.module.struct_defs.append(
            IRStructDef(shape.invocation, [IRStructField(CType("void*"), "_context")])
        )
        self._session.module.struct_forwards.append(IRStructForward(shape.invocation))
        self._session.module.struct_forwards.append(IRStructForward(context_name))
        raw = IRVar("raw")
        load_context = IRVarDecl(context_type, "context", init=IRCast(context_type, raw))
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=prefix + "_destroy",
                return_type=CType("void"),
                params=[IRParam(CType("void*"), "raw")],
                is_static=True,
                body=IRBlock(
                    [
                        load_context,
                        IRExprStmt(IRCall(unique_prefix + "_end_borrow", [owner])),
                        IRExprStmt(self._lifetime.release_value(receiver, receiver_type)),
                        IRExprStmt(IRCall("free", [context])),
                    ]
                ),
            )
        )
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=prefix + "_unregister",
                return_type=CType("bool"),
                params=[IRParam(CType("void*"), "raw")],
                is_static=True,
                body=IRBlock(
                    [
                        load_context,
                        IRReturn(IRBinOp(IRCall(callback.unregister.name, [unit]), "==", IRLiteral("0"))),
                    ]
                ),
            )
        )
        capability_type = CType("struct " + shape.invocation)
        parameters = [
            IRParam(CType(self._types.render(value)), f"argument{index}")
            for index, value in enumerate(callback.parameters)
        ]
        payload_values = [IRVar(value.name) for value in payload]
        body = [
            IRVarDecl(
                context_type,
                "context",
                init=IRCast(context_type, IRVar(parameters[callback.callback_context_index].name)),
            ),
            IRIf(
                IRBinOp(IRCall("callbackGateTryEnter", [gate]), "==", IRLiteral("false")),
                IRBlock(
                    [
                        IRReturn(
                            IRCall(
                                IRFieldAccess(context, "denied", arrow=True),
                                payload_values,
                                realtime_provenance="typed-realtime-function",
                            )
                        ),
                    ]
                ),
            ),
            IRVarDecl(capability_type, "invocation", init=IRInitializerList([IRLiteral("0")])),
            IRAssign(IRFieldAccess(IRVar("invocation"), "_context"), context),
            IRVarDecl(
                result_type,
                "result",
                init=IRCall(
                    IRFieldAccess(context, "invoke", arrow=True),
                    [receiver, IRAddressOf(IRVar("invocation")), *payload_values],
                    realtime_provenance="typed-realtime-function",
                ),
            ),
            IRExprStmt(IRCall("callbackGateLeave", [gate])),
            IRReturn(IRVar("result")),
        ]
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=prefix + "_invoke",
                return_type=result_type,
                params=parameters,
                is_static=True,
                body=IRBlock(body),
                is_realtime=True,
            )
        )
        for operation in shape.operations:
            operation_parameters = [
                IRParam(CType("struct " + shape.invocation + "*"), "self"),
                *[self._signatures.lower_source_param(value) for value in operation.parameters],
            ]
            arguments = [IRVar(value.name) for value in operation_parameters[1:]]
            arguments.insert(operation.owner_index, unit)
            self._session.module.native_external_names.add(operation.function)
            self._session.module.realtime_safe_externals.add(operation.function)
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=shape.invocation + "_" + operation.name,
                    return_type=CType(self._types.render(operation.return_type)),
                    params=operation_parameters,
                    body=IRBlock(
                        [
                            IRVarDecl(
                                context_type,
                                "context",
                                init=IRCast(context_type, IRFieldAccess(IRVar("self"), "_context", arrow=True)),
                            ),
                            IRReturn(IRCall(operation.function, arguments)),
                        ]
                    ),
                    is_realtime=True,
                )
            )
        parameters = [self._signatures.lower_source_param(value) for value in declaration.params]
        visible = [
            index
            for index in range(len(shape.native_parameters))
            if index not in {callback.parameter_index, shape.size_index}
        ]
        owner_argument = IRVar(parameters[visible.index(shape.owner_index)].name)
        receiver_argument, denied_argument, scope_argument = [IRVar(value.name) for value in parameters[-3:]]
        self._session.require_helper("__btrc_safe_calloc")
        statements = [
            self._native_null_guard(owner_argument, "Realtime registration requires an owner"),
            self._native_null_guard(receiver_argument, "Realtime registration requires a receiver"),
            self._native_null_guard(denied_argument, "Realtime registration requires a denied-admission fallback"),
            self._native_null_guard(scope_argument, "Realtime registration requires a scope"),
            IRVarDecl(
                context_type,
                "context",
                init=IRCast(
                    context_type,
                    IRCall("__btrc_safe_calloc", [IRLiteral("1"), IRSizeof(CType("struct " + context_name))]),
                ),
            ),
            IRAssign(owner, owner_argument),
            IRExprStmt(self._lifetime.retain_value(owner, owner_type)),
            IRExprStmt(IRCall(unique_prefix + "_begin_borrow", [owner])),
            IRAssign(receiver, receiver_argument),
            IRExprStmt(self._lifetime.retain_value(receiver, receiver_type)),
            IRAssign(IRFieldAccess(context, "denied", arrow=True), denied_argument),
            IRAssign(
                IRFieldAccess(context, "invoke", arrow=True),
                IRFieldAccess(
                    IRCast(
                        CType("const struct " + interface_table + "*"),
                        IRCall(
                            "__btrc_interface_methods",
                            [receiver, IRLiteral(json.dumps(callback.interface))],
                            helper_ref="__btrc_interface_methods",
                        ),
                    ),
                    "invoke",
                    arrow=True,
                ),
            ),
            IRVarDecl(
                CType("struct CallbackState*"),
                "registration",
                init=IRCall(
                    "CallbackScope_createNative",
                    [
                        scope_argument,
                        context,
                        IRFunctionRef(prefix + "_destroy"),
                        IRFunctionRef(prefix + "_unregister"),
                    ],
                ),
            ),
            IRAssign(gate, IRCall("CallbackState_activationGate", [IRVar("registration")])),
            IRVarDecl(CType(callback.record), "record", init=IRInitializerList([IRLiteral("0")])),
            IRAssign(IRFieldAccess(IRVar("record"), callback.field), IRFunctionRef(prefix + "_invoke")),
            IRAssign(IRFieldAccess(IRVar("record"), callback.context_fields[0]), context),
        ]
        native_arguments = dict(zip(visible, [IRVar(value.name) for value in parameters[:-3]], strict=True))
        native_arguments[shape.owner_index] = unit
        native_arguments[callback.parameter_index] = IRAddressOf(IRVar("record"))
        native_arguments[shape.size_index] = IRSizeof(CType(callback.record))
        failure = self._native_null_guard(
            IRLiteral("NULL"), "Realtime callback activation failed with indeterminate publication"
        )
        failure.condition = IRBinOp(IRVar("status"), "!=", IRLiteral("0"))
        statements.extend(
            [
                IRVarDecl(
                    CType(self._types.render(shape.status_type)),
                    "status",
                    init=IRCall(shape.function, [native_arguments[index] for index in range(len(native_arguments))]),
                ),
                failure,
                IRExprStmt(IRCall("CallbackState_finishActivation", [IRVar("registration"), IRLiteral("true")])),
                IRReturn(IRVar("registration")),
            ]
        )
        self._session.module.native_external_names.update((shape.function, callback.unregister.name))
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=prefix,
                return_type=CType(self._types.render(declaration.return_type)),
                params=parameters,
                body=IRBlock(statements),
            )
        )

    def _emit_callback_table_adapter(self, declaration, contract):
        """One holder claim per live SDK table: the original and every SDK reopen."""
        table = contract.callback_table
        prefix = f"__btrc_native_table_{table.resource}"
        holder_name = prefix + "_holder"
        holder_type = CType(f"struct {holder_name}*")
        receiver_type = TypeExpr(base=table.interface, pointer_depth=1)
        receiver_c = CType(self._types.render(receiver_type))
        table_type = CType(table.native_type + "*")
        self._session.module.struct_forwards.append(IRStructForward(holder_name))
        self._session.module.struct_defs.append(
            IRStructDef(
                holder_name,
                [
                    IRStructField(receiver_c, "receiver"),
                    IRStructField(CType("char*"), "label"),
                    IRStructField(CType("long"), "claims"),
                    IRStructField(CType("volatile int*"), "thread"),
                ],
            )
        )
        self._session.require_helper("__btrc_safe_calloc")
        holder = IRVar("holder")
        claims = IRFieldAccess(holder, "claims", arrow=True)
        receiver = IRFieldAccess(holder, "receiver", arrow=True)
        label = IRFieldAccess(holder, "label", arrow=True)

        def load(context):
            return IRVarDecl(holder_type, "holder", init=IRCast(holder_type, context))

        def thread_guard():
            return IRIf(
                IRBinOp(
                    IRFieldAccess(holder, "thread", arrow=True),
                    "!=",
                    IRAddressOf(IRFieldAccess(IRVar("__btrc_tls"), "try_top")),
                ),
                IRBlock(
                    [
                        IRExprStmt(
                            IRCall(
                                "fputs",
                                [IRLiteral('"BTRC native callback delivered on the wrong thread\\n"'), IRVar("stderr")],
                            )
                        ),
                        IRExprStmt(IRCall("abort", [], never_returns=True)),
                    ]
                ),
            )

        def define(name, result, params, body):
            self._session.module.function_decls.append(IRFunctionDecl(name, result, params, is_static=True))
            self._session.module.function_defs.append(
                IRFunctionDef(name=name, return_type=result, params=params, is_static=True, body=IRBlock(body))
            )

        assignments = []
        for method in table.methods:
            params = [
                IRParam(CType(spelling), f"argument{index}") for index, spelling in enumerate(method.native_parameters)
            ]
            result = CType(method.native_return)
            arguments = [IRVar(param.name) for index, param in enumerate(params) if index != table.context_index]
            call = IRCall(f"{table.interface}_{method.name}", [receiver, *arguments])
            inner = [IRExprStmt(call)] if result.text == "void" else [IRVarDecl(result, "result", init=call)]
            inner.extend(self._exceptions.pop_try_frames(1))
            inner.append(IRReturn(None if result.text == "void" else IRVar("result")))
            define(
                f"{prefix}_{method.name}",
                result,
                params,
                [
                    load(IRVar(params[table.context_index].name)),
                    thread_guard(),
                    self._exceptions.native_callback_boundary(IRBlock(inner)),
                ],
            )
            assignments.append((method.field, f"{prefix}_{method.name}"))
        if table.label:
            define(
                f"{prefix}_label",
                CType("const char*"),
                [IRParam(CType("void*"), "argument0")],
                [load(IRVar("argument0")), thread_guard(), IRReturn(label)],
            )
            assignments.append((table.label, f"{prefix}_label"))
        if table.reopen:
            assignments.append((table.reopen, f"{prefix}_reopen"))
        if table.release:
            assignments.append((table.release, f"{prefix}_release"))
        native_table = IRVar("table")
        body = [
            IRVarDecl(
                table_type,
                "table",
                init=IRCast(
                    table_type, IRCall("__btrc_safe_calloc", [IRLiteral("1"), IRSizeof(CType(table.native_type))])
                ),
            ),
            IRAssign(IRFieldAccess(native_table, table.context, arrow=True), IRCast(CType("void*"), holder)),
            *(
                IRAssign(IRFieldAccess(native_table, field, arrow=True), IRFunctionRef(function))
                for field, function in assignments
            ),
            IRAssign(claims, IRBinOp(claims, "+", IRLiteral("1"))),
            IRReturn(native_table),
        ]
        define(f"{prefix}_table", table_type, [IRParam(holder_type, "holder")], body)
        if table.reopen:
            name = IRVar("argument1")
            mismatch = IRBinOp(
                IRBinOp(name, "==", IRLiteral("NULL")),
                "||",
                IRBinOp(IRCall("strcmp", [name, label]), "!=", IRLiteral("0")),
            )
            define(
                f"{prefix}_reopen",
                table_type,
                [IRParam(CType("void*"), "argument0"), IRParam(CType("const char*"), "argument1")],
                [
                    load(IRVar("argument0")),
                    thread_guard(),
                    IRIf(mismatch, IRBlock([IRReturn(IRLiteral("NULL"))])),
                    IRReturn(IRCall(f"{prefix}_table", [holder])),
                ],
            )
        if table.release:
            argument = IRVar("argument0")
            final = [
                IRExprStmt(self._lifetime.release_value(receiver, receiver_type)),
                IRExprStmt(IRCall("free", [label])),
                IRExprStmt(IRCall("free", [holder])),
                *self._exceptions.pop_try_frames(1),
            ]
            define(
                f"{prefix}_release",
                CType("void"),
                [IRParam(table_type, "argument0")],
                [
                    IRIf(IRBinOp(argument, "==", IRLiteral("NULL")), IRBlock([IRReturn(None)])),
                    load(IRFieldAccess(argument, table.context, arrow=True)),
                    thread_guard(),
                    IRExprStmt(IRCall("free", [argument])),
                    IRAssign(claims, IRBinOp(claims, "-", IRLiteral("1"))),
                    IRIf(
                        IRBinOp(claims, "==", IRLiteral("0")), self._exceptions.native_callback_boundary(IRBlock(final))
                    ),
                ],
            )
        create_params = [IRParam(receiver_c, "receiver")]
        body = [
            IRVarDecl(
                holder_type,
                "holder",
                init=IRCast(
                    holder_type,
                    IRCall("__btrc_safe_calloc", [IRLiteral("1"), IRSizeof(CType(f"struct {holder_name}"))]),
                ),
            ),
            IRAssign(receiver, IRVar("receiver")),
            IRExprStmt(self._lifetime.retain_value(IRVar("receiver"), receiver_type)),
            IRAssign(
                IRFieldAccess(holder, "thread", arrow=True), IRAddressOf(IRFieldAccess(IRVar("__btrc_tls"), "try_top"))
            ),
        ]
        if table.label:
            create_params.append(IRParam(CType("char*"), "label"))
            body.extend(
                [
                    IRVarDecl(CType("size_t"), "length", init=IRCall("strlen", [IRVar("label")])),
                    IRAssign(
                        label,
                        IRCast(
                            CType("char*"),
                            IRCall(
                                "__btrc_safe_calloc", [IRLiteral("1"), IRBinOp(IRVar("length"), "+", IRLiteral("1"))]
                            ),
                        ),
                    ),
                    IRExprStmt(IRCall("memcpy", [label, IRVar("label"), IRVar("length")])),
                ]
            )
        body.append(IRReturn(IRCall(f"{prefix}_table", [holder])))
        define(f"{prefix}_create", table_type, create_params, body)
        name = contract.adapter_symbol(declaration.name)
        parameters = [self._signatures.lower_source_param(parameter) for parameter in declaration.params]
        statements = [
            self._native_null_guard(
                IRVar(parameter.name), f"Native call {declaration.name}: null argument {parameter.name}"
            )
            for parameter in parameters
        ]
        call = IRCall(f"{prefix}_create", [IRVar(parameter.name) for parameter in parameters])
        releases, cleanup = [], []
        self._native_unique_result(declaration, call, parameters, statements, releases, cleanup)
        return_type = CType(self._types.render(declaration.return_type))
        self._session.module.function_decls.append(IRFunctionDecl(name, return_type, parameters, is_static=True))
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=name, return_type=return_type, params=parameters, is_static=True, body=IRBlock(statements)
            )
        )

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

    def _native_lease(
        self, index, value_type, argument, parameters, statements, releases, owned=False, locals=None, attachment=False
    ):
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
        registration = self._lifetime.register_cleanup_slot(slot, value_type)
        if self._unique_resource(value_type.base):
            prefix = f"__btrc_unique_{value_type.base}"
            operation = "attachment" if attachment else "borrow"
            statements.append(IRExprStmt(IRCall(prefix + "_begin_" + operation, [value])))
            registration.args[2] = IRFunctionRef(prefix + "_end_" + operation)
            statements.append(IRExprStmt(registration))
            released = name + "_released"
            releases[:0] = [
                IRVarDecl(slot.c_type, released, init=value),
                IRAssign(value, IRLiteral("NULL")),
                IRExprStmt(IRCall(prefix + "_end_" + operation, [IRVar(released)])),
            ]
            return value
        statements.append(IRExprStmt(expr=registration))
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
                        ("thread", IRAddressOf(expr=IRFieldAccess(obj=IRVar(name="__btrc_tls"), field="try_top"))),
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

    def _native_callback_result(self, callback):
        return self._analyzed.interface_table[callback.interface].methods[callback.method_name].return_type

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
        result_type = CType(text=self._types.render(self._native_callback_result(callback)))
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
                                right=IRAddressOf(expr=IRFieldAccess(obj=IRVar(name="__btrc_tls"), field="try_top")),
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
        if resource.ownership == "unique":
            dispatch = resource.dispatch
            release = self._emit_dispatch_release(declaration) if dispatch is not None and dispatch.release else None
            self._emit_unique_resource(declaration, release_symbol=release)
            if dispatch is not None:
                for method in declaration.members:
                    if method.name not in {"close", "isOpen"}:
                        self._emit_dispatch_method(
                            declaration, method, declaration.source_file.methods[method.name].dispatch_method
                        )
            return
        if resource.ownership == "com":
            self._emit_com_interface(declaration)
            return
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
        if declaration.source_file.resource_query_type:
            self._emit_resource_query(declaration)

    def _emit_resource_query(self, declaration):
        resource = declaration.source_file.resource
        source_name = declaration.source_file.resource_query_type
        source_type = TypeExpr(base=source_name, is_nullable=True, pointer_depth=1)
        target_type = TypeExpr(base=resource.name, is_nullable=True, pointer_depth=1)
        result_type = CType(self._types.render(target_type))
        parameters = [IRParam(CType(self._types.render(source_type)), "source")]
        statements, releases = [], []
        cleanup = self._native_cleanup_scope(parameters, statements)
        source = self._native_lease(0, source_type, IRVar("source"), parameters, statements, releases)
        matches = IRBinOp(
            source,
            "&&",
            IRBinOp(
                IRCall(resource.type_query, [IRCast(CType(source_name), source)]), "==", IRCall(resource.type_tag, [])
            ),
        )
        result = IRVarDecl(
            result_type,
            "__btrc_native_projection",
            init=IRTernary(matches, IRCast(result_type, source), IRLiteral("NULL")),
        )
        value = IRVar(result.name)
        statements.extend(
            [
                result,
                IRExprStmt(self._lifetime.retain_value(value, target_type)),
                IRExprStmt(self._lifetime.register_cleanup_slot(result, target_type)),
                *releases,
                *cleanup,
                IRReturn(value),
            ]
        )
        name = f"__btrc_native_{resource.name}_try_cast"
        self._session.module.function_decls.append(IRFunctionDecl(name, result_type, parameters, is_static=True))
        self._session.module.function_defs.append(
            IRFunctionDef(name, result_type, parameters, IRBlock(statements), is_static=True)
        )

    def _native_unique_function(self, name, result, parameters, statements):
        self._session.module.function_decls.append(IRFunctionDecl(name, CType(result), parameters, is_static=True))
        self._session.module.function_defs.append(
            IRFunctionDef(name, CType(result), parameters, IRBlock(statements), is_static=True)
        )

    def _native_unique_checked(self, function, arguments):
        guard = self._native_null_guard(IRLiteral("NULL"), f"Native resource synchronization: {function} failed")
        guard.condition = IRBinOp(IRCall(function, arguments), "!=", IRLiteral("0"))
        return guard

    def _dispatch_call(self, declaration, method, native, arguments):
        """Reload the object's table and slot, check both, and call through the slot.

        The object owns its table, so nothing is cached between calls: an SDK
        that swaps tables is honored on the next call (M1 dispatch).
        """
        resource = declaration.source_file.resource
        dispatch = resource.dispatch
        what = f"{declaration.name}.{method.name or 'release'}"
        table = IRVar("table")
        slot = IRFieldAccess(table, method.slot, arrow=True)
        context = IRFieldAccess(native, dispatch.context, arrow=True) if dispatch.context else native
        arguments = [*arguments[: dispatch.context_index], context, *arguments[dispatch.context_index :]]
        return [
            IRVarDecl(CType(method.table_type), "table", init=IRFieldAccess(native, dispatch.table, arrow=True)),
            self._native_null_guard(table, f"Native dispatch {what}: null function table"),
            self._native_null_guard(slot, f"Native dispatch {what}: null table slot {method.slot}"),
        ], IRCall(slot, arguments)

    def _emit_dispatch_release(self, declaration):
        """Final owner cleanup runs the table's release slot exactly once."""
        resource = declaration.source_file.resource
        method = declaration.source_file.methods[""].dispatch_method
        name = f"__btrc_dispatch_{declaration.name}_release"
        native_type = declaration.source_file.type_spelling or resource.name
        native = IRVar("native")
        statements, call = self._dispatch_call(declaration, method, native, [])
        self._native_unique_function(
            name, "void", [IRParam(CType(native_type), "native")], [*statements, IRExprStmt(call)]
        )
        return name

    def _emit_dispatch_method(self, declaration, member, method):
        """A dispatched slot borrows the unique owner for exactly the native call."""
        resource = declaration.source_file.resource
        symbol = declaration.name
        owner = IRVar("self")
        native = IRVar("native")
        native_type = declaration.source_file.type_spelling or resource.name
        parameters = [self._signatures.lower_source_param(parameter) for parameter in member.params]
        result_type = CType(self._types.render(member.return_type))
        statements, call = self._dispatch_call(
            declaration,
            method,
            native,
            [
                IRCast(CType(spelling), IRVar(parameter.name))
                for parameter, spelling in zip(parameters, method.native_parameters, strict=True)
            ],
        )
        returns_value = result_type.text != "void"
        body = [
            self._native_null_guard(owner, f"Native dispatch {symbol}.{method.name}: null receiver"),
            IRExprStmt(IRCall(f"__btrc_native_{symbol}_retain", [owner])),
            IRExprStmt(IRCall(f"__btrc_unique_{symbol}_begin_borrow", [owner])),
            IRVarDecl(CType(native_type), "native", init=IRFieldAccess(owner, "value", arrow=True)),
            *statements,
            IRVarDecl(result_type, "result", init=IRCast(result_type, call)) if returns_value else IRExprStmt(call),
            IRExprStmt(IRCall(f"__btrc_unique_{symbol}_end_borrow", [owner])),
            *([IRReturn(IRVar("result"))] if returns_value else []),
        ]
        self._native_unique_function(
            f"__btrc_unique_{symbol}_{method.name}_public",
            result_type.text,
            [IRParam(CType(f"struct __btrc_native_{symbol}*"), "self"), *parameters],
            body,
        )

    # E_NOINTERFACE, the HRESULT 0x80004002 as a 32-bit signed value: the one
    # QueryInterface failure that answers "no" rather than reporting an error.
    _COM_NO_INTERFACE = "-2147467262"

    @staticmethod
    def _com_call(interface, native, slot, arguments, what):
        """Reload the interface's table and slot, check both, and call through the slot with This first."""
        table = IRVar("__btrc_table")
        callee = IRFieldAccess(table, slot, arrow=True)
        return [
            IRVarDecl(CType(interface.table_type), table.name, init=IRFieldAccess(native, "lpVtbl", arrow=True)),
            FunctionLowerer._native_null_guard(table, f"{what}: null function table"),
            FunctionLowerer._native_null_guard(callee, f"{what}: null table slot {slot}"),
        ], IRCall(callee, [native, *arguments])

    @staticmethod
    def _com_apartment():
        """Every COM adapter runs on its apartment's thread (Library.COM checks it)."""
        return IRExprStmt(IRCall("btrcCOMRequireApartment", []))

    def _emit_com_interface(self, declaration):
        """A COM interface: AddRef and Release through its table, M3 queries, sameObject and its methods.

        A BTRC value of the interface is the SDK's own pointer, and each value
        holds one claim: adopted from a factory, an [out] parameter or
        QueryInterface, or taken by AddRef for an alias. Release ends it. Every
        adapter checks its apartment, and Library.COM counts each claim against
        it, so the apartment cannot be uninitialized while one is live
        (native-interop-ownership.md section 2.4).
        """
        symbol = declaration.name
        interface = declaration.source_file.methods[""].com_interface
        module = self._session.module
        forward = IRStructForward(name=f"__btrc_native_{symbol}")
        if forward not in module.struct_forwards:
            module.struct_forwards.append(forward)
        value = IRVar("value")
        native = IRVar("__btrc_native")
        for operation, slot, count in (("retain", "AddRef", "btrcCOMClaim"), ("release", "Release", "btrcCOMUnclaim")):
            statements, call = self._com_call(interface, native, slot, [], f"Native COM {symbol}.{slot}")
            self._native_unique_function(
                f"__btrc_native_{symbol}_{operation}",
                "void",
                [IRParam(CType("void*"), "value")],
                [
                    IRIf(
                        IRBinOp(value, "!=", IRLiteral("NULL")),
                        IRBlock(
                            [
                                self._com_apartment(),
                                IRVarDecl(
                                    CType(interface.native_type),
                                    native.name,
                                    init=IRCast(CType(interface.native_type), value),
                                ),
                                *statements,
                                # The returned count is diagnostic only, and discarded.
                                IRExprStmt(call),
                                IRExprStmt(IRCall(count, [])),
                            ]
                        ),
                    )
                ],
            )
        self._native_unique_function(
            f"__btrc_com_{symbol}_adopt",
            "void*",
            [IRParam(CType("void*"), "value")],
            [
                IRIf(
                    IRBinOp(value, "!=", IRLiteral("NULL")),
                    IRBlock([self._com_apartment(), IRExprStmt(IRCall("btrcCOMClaim", []))]),
                ),
                IRReturn(value),
            ],
        )
        self._emit_com_query(declaration, interface)
        for member in declaration.members:
            contract = declaration.source_file.methods[member.name]
            if contract.dispatch_method is not None:
                self._emit_com_method(declaration, member, contract.dispatch_method, interface)
            else:
                self._emit_com_identity(declaration, member, interface)

    def _emit_com_query(self, declaration, interface):
        """M3: QueryInterface through the source's own table.

        Success is one new claim; E_NOINTERFACE gives null; any other failure
        terminates, and a failure that still wrote an interface adopts it first.
        """
        symbol = declaration.name
        source, result, status = IRVar("source"), IRVar("__btrc_result"), IRVar("__btrc_status")
        native = IRVar("__btrc_native")
        what = f"Native COM {symbol}.QueryInterface"
        statements, call = self._com_call(
            interface, native, "QueryInterface", [IRVar("iid"), IRAddressOf(result)], what
        )
        failure = self._native_null_guard(IRLiteral("NULL"), f"{what}: a failed query returned an interface")
        failure.condition = IRBinOp(result, "!=", IRLiteral("NULL"))
        failure.then_block.stmts.insert(0, IRExprStmt(IRCall("btrcCOMClaim", [])))
        self._native_unique_function(
            f"__btrc_com_{symbol}_query",
            "void*",
            [IRParam(CType("void*"), "source"), IRParam(CType(interface.iid_type), "iid")],
            [
                IRIf(IRBinOp(source, "==", IRLiteral("NULL")), IRBlock([IRReturn(IRLiteral("NULL"))])),
                self._com_apartment(),
                IRVarDecl(CType(interface.native_type), native.name, init=IRCast(CType(interface.native_type), source)),
                *statements,
                IRVarDecl(CType("void*"), result.name, init=IRLiteral("NULL")),
                IRVarDecl(CType(interface.status_type), status.name, init=call),
                IRIf(
                    IRBinOp(status, ">=", IRLiteral("0")),
                    IRBlock(
                        [
                            self._native_null_guard(result, f"{what}: success without an interface"),
                            IRExprStmt(IRCall("btrcCOMClaim", [])),
                            IRReturn(result),
                        ]
                    ),
                ),
                failure,
                IRIf(IRBinOp(status, "==", IRLiteral(self._COM_NO_INTERFACE)), IRBlock([IRReturn(IRLiteral("NULL"))])),
                IRExprStmt(
                    IRCall(
                        "fprintf",
                        [
                            IRVar("stderr"),
                            IRLiteral(json.dumps(f"{what} failed with HRESULT 0x%08X\n")),
                            IRCast(CType("unsigned int"), status),
                        ],
                    )
                ),
                IRExprStmt(IRCall("abort", [], never_returns=True)),
            ],
        )

    def _emit_com_identity(self, declaration, member, interface):
        """sameObject(a, b): two objects are one when their IUnknown identities are one pointer."""
        symbol = declaration.name
        parameters = [self._signatures.lower_source_param(parameter) for parameter in member.params]
        first, second = (IRVar(parameter.name) for parameter in parameters)
        query = f"__btrc_com_{symbol}_query"
        identities = (IRVar("__btrc_first"), IRVar("__btrc_second"))
        statements = [
            IRIf(
                IRBinOp(IRBinOp(first, "==", IRLiteral("NULL")), "||", IRBinOp(second, "==", IRLiteral("NULL"))),
                IRBlock([IRReturn(IRBinOp(first, "==", second))]),
            )
        ]
        for identity, value in zip(identities, (first, second), strict=True):
            statements.extend(
                [
                    IRVarDecl(
                        CType("void*"),
                        identity.name,
                        init=IRCall(query, [value, IRAddressOf(IRVar(interface.unknown_iid))]),
                    ),
                    self._native_null_guard(identity, f"Native COM {symbol}.sameObject: an object has no IUnknown"),
                ]
            )
        statements.extend(
            [
                IRVarDecl(CType("bool"), "__btrc_same", init=IRBinOp(identities[0], "==", identities[1])),
                # Release is slot 2 of every table, so the interface's own adapter ends each IUnknown claim.
                *(IRExprStmt(IRCall(f"__btrc_native_{symbol}_release", [identity])) for identity in identities),
                IRReturn(IRVar("__btrc_same")),
            ]
        )
        self._native_unique_function(f"__btrc_com_{symbol}_{member.name}_public", "bool", parameters, statements)

    def _emit_com_method(self, declaration, member, method, interface):
        """A dispatched COM method: borrow the receiver and each [in] interface, call, then report.

        The adapter holds one claim on the receiver and on every [in] interface
        for the call, and adopts a nonnull [out] interface before those end.
        With status-results a failing HRESULT releases the adopted output and
        throws (F1); an owned-outputs result class carries the HRESULT and the
        output; otherwise the slot's result is returned unchanged.
        """
        symbol = declaration.name
        owner = IRVar("self")
        native = IRVar("__btrc_native")
        status = IRVar("__btrc_status")
        output = IRVar("__btrc_output")
        result = IRVar("__btrc_result")
        what = f"Native dispatch {symbol}.{method.name}"
        parameters = [self._signatures.lower_source_param(parameter) for parameter in member.params]
        result_type = CType(self._types.render(member.return_type))
        arguments = [
            IRCast(CType(spelling), IRVar(parameter.name))
            for parameter, spelling in zip(parameters, method.native_parameters, strict=True)
        ]
        if method.output_position >= 0:
            # The slot's argument list puts This first; the output keeps its own position.
            arguments.insert(method.output_position - 1, IRAddressOf(output))
        statements, call = self._com_call(interface, native, method.slot, arguments, what)
        borrowed = [
            (parameter, resource) for parameter, resource in zip(parameters, method.resources, strict=True) if resource
        ]
        body = [
            self._native_null_guard(owner, f"{what}: null receiver"),
            IRExprStmt(IRCall(f"__btrc_native_{symbol}_retain", [owner])),
            *(
                IRExprStmt(IRCall(f"__btrc_native_{resource}_retain", [IRVar(parameter.name)]))
                for parameter, resource in borrowed
            ),
            IRVarDecl(CType(interface.native_type), native.name, init=IRCast(CType(interface.native_type), owner)),
        ]
        if method.status == "result":
            body.append(IRVarDecl(result_type, result.name, init=IRCall(f"{method.result_class}_new", [])))
        if method.output_position >= 0:
            body.append(IRVarDecl(CType(method.output_spelling), output.name, init=IRLiteral("NULL")))
        body.extend(statements)
        returns = method.native_return != "void"
        body.append(IRVarDecl(CType(method.native_return), status.name, init=call) if returns else IRExprStmt(call))
        if method.output_position >= 0:
            body.append(IRExprStmt(IRCall(f"__btrc_com_{method.output_resource}_adopt", [output])))
        body.extend(
            IRExprStmt(IRCall(f"__btrc_native_{resource}_release", [IRVar(parameter.name)]))
            for parameter, resource in reversed(borrowed)
        )
        body.append(IRExprStmt(IRCall(f"__btrc_native_{symbol}_release", [owner])))
        managed_output = IRCast(CType(f"struct __btrc_native_{method.output_resource}*"), output)
        if method.status == "throw":
            self._session.require_helper("__btrc_throw")
            message = IRVar("__btrc_message")
            body.append(
                IRIf(
                    IRBinOp(status, "<", IRLiteral("0")),
                    IRBlock(
                        [
                            *(
                                [IRExprStmt(IRCall(f"__btrc_native_{method.output_resource}_release", [output]))]
                                if method.output_position >= 0
                                else []
                            ),
                            IRVarDecl(CType("char"), message.name, array_size=IRLiteral("128")),
                            IRExprStmt(
                                IRCall(
                                    "snprintf",
                                    [
                                        message,
                                        IRSizeof(message),
                                        IRLiteral(json.dumps(f"COM {symbol}.{method.name} failed with HRESULT 0x%08X")),
                                        IRCast(CType("unsigned int"), status),
                                    ],
                                )
                            ),
                            IRExprStmt(
                                IRCall("__btrc_throw", [message], helper_ref="__btrc_throw", never_returns=True)
                            ),
                        ]
                    ),
                )
            )
            body.append(IRReturn(managed_output if method.output_position >= 0 else IRCast(result_type, status)))
        elif method.status == "result":
            body.extend(
                [
                    IRAssign(IRFieldAccess(result, "status", arrow=True), status),
                    IRAssign(IRFieldAccess(result, "value", arrow=True), managed_output),
                    IRReturn(result),
                ]
            )
        elif returns:
            body.append(IRReturn(IRCast(result_type, status)))
        self._native_unique_function(
            f"__btrc_com_{symbol}_{method.name}_public",
            result_type.text,
            [IRParam(CType(f"struct __btrc_native_{symbol}*"), "self"), *parameters],
            body,
        )

    def _emit_unique_resource(self, declaration, symbol=None, release_symbol=None):
        resource = declaration.source_file.resource
        native_type = declaration.source_file.type_spelling or resource.name
        status_release = bool(resource.release_consumption)
        close_type = self._types.render(
            next(member.return_type for member in declaration.members if member.name == "close")
        )
        include = IRInclude(header="pthread.h")
        if include not in self._session.module.preprocessor_decls:
            self._session.module.preprocessor_decls.append(include)
        # C++ owners are published under their BTRC alias and released through a
        # generated extern "C" adapter rather than a selected C function.
        symbol = symbol or resource.name
        release_symbol = release_symbol or resource.release
        native_prefix = f"__btrc_native_{symbol}"
        prefix = f"__btrc_unique_{symbol}"
        forward = IRStructForward(name=native_prefix)
        if forward not in self._session.module.struct_forwards:
            self._session.module.struct_forwards.append(forward)
        pointer_type = f"struct {native_prefix}*"
        pointer = CType(pointer_type)
        owner = IRVar("owner")
        value = IRFieldAccess(owner, "value", arrow=True)
        borrows = IRFieldAccess(owner, "borrows", arrow=True)
        closing = IRFieldAccess(owner, "closing", arrow=True)
        status = IRFieldAccess(owner, "status", arrow=True)
        closing_thread = IRFieldAccess(owner, "closingThread", arrow=True)
        mutex = IRAddressOf(IRFieldAccess(owner, "lock", arrow=True))
        completed = IRAddressOf(IRFieldAccess(owner, "completed", arrow=True))
        parameters = [IRParam(pointer, "owner")]
        self._session.module.struct_defs.append(
            IRStructDef(
                native_prefix,
                [
                    IRStructField(CType("__btrc_arc_header"), "__arc"),
                    IRStructField(CType(native_type), "value"),
                    IRStructField(CType("unsigned int"), "borrows"),
                    IRStructField(CType("bool"), "closing"),
                    IRStructField(CType("pthread_t"), "closingThread"),
                    IRStructField(CType("pthread_mutex_t"), "lock"),
                    IRStructField(CType("pthread_cond_t"), "completed"),
                    *([IRStructField(CType(close_type), "status")] if status_release else []),
                    *(
                        [
                            IRStructField(CType(native_type), "storage"),
                            IRStructField(CType("void*"), "input"),
                            IRStructField(CType("bool"), "inputAttached"),
                        ]
                        if resource.storage
                        else []
                    ),
                ],
            )
        )
        for helper in ("__btrc_arc_retain", "__btrc_arc_release", "__btrc_safe_calloc"):
            self._session.require_helper(helper)
        if release_symbol == resource.release:
            self._session.module.native_external_names.add(resource.release)
        lock = self._native_unique_checked("pthread_mutex_lock", [mutex])
        unlock = self._native_unique_checked("pthread_mutex_unlock", [mutex])
        reentrant = self._native_null_guard(IRLiteral("NULL"), f"Native resource {resource.name}: reentrant close")
        reentrant.condition = IRCall("pthread_equal", [closing_thread, IRCall("pthread_self", [])])
        wait = IRWhile(
            closing,
            IRBlock(
                [
                    reentrant,
                    self._native_unique_checked("pthread_cond_wait", [completed, mutex]),
                ]
            ),
        )
        borrowed = self._native_null_guard(IRLiteral("NULL"), f"Native resource {resource.name}: close during borrow")
        borrowed.condition = IRBinOp(borrows, "!=", IRLiteral("0"))
        close = [
            IRIf(
                IRBinOp(owner, "==", IRLiteral("NULL")), IRBlock([IRReturn(IRLiteral("0") if status_release else None)])
            ),
            lock,
            wait,
        ]
        if status_release:
            close.append(
                IRIf(
                    IRBinOp(value, "==", IRLiteral("NULL")),
                    IRBlock(
                        [
                            IRVarDecl(CType(close_type), "result", init=status),
                            unlock,
                            IRReturn(IRVar("result")),
                        ]
                    ),
                )
            )
        close.extend(
            [
                borrowed,
                IRVarDecl(CType(native_type), "native", init=value),
                IRAssign(value, IRLiteral("NULL")),
                IRAssign(closing, IRLiteral("true")),
                IRAssign(closing_thread, IRCall("pthread_self", [])),
                unlock,
                IRVarDecl(CType(close_type), "result", init=IRCall(release_symbol, [IRVar("native")]))
                if status_release
                else IRIf(IRVar("native"), IRBlock([IRExprStmt(IRCall(release_symbol, [IRVar("native")]))])),
                *(
                    [
                        IRExprStmt(IRCall("free", [IRFieldAccess(owner, "input", arrow=True)])),
                        IRAssign(IRFieldAccess(owner, "input", arrow=True), IRLiteral("NULL")),
                        IRExprStmt(IRCall("free", [IRFieldAccess(owner, "storage", arrow=True)])),
                        IRAssign(IRFieldAccess(owner, "storage", arrow=True), IRLiteral("NULL")),
                    ]
                    if resource.storage
                    else []
                ),
                lock,
                *([IRAssign(status, IRVar("result"))] if status_release else []),
                IRAssign(closing, IRLiteral("false")),
                self._native_unique_checked("pthread_cond_broadcast", [completed]),
                unlock,
                *([IRReturn(IRVar("result"))] if status_release else []),
            ]
        )
        self._native_unique_function(prefix + "_close", close_type, parameters, close)
        self._native_unique_function(
            prefix + "_isOpen_public",
            "bool",
            parameters,
            [
                IRIf(IRBinOp(owner, "==", IRLiteral("NULL")), IRBlock([IRReturn(IRLiteral("false"))])),
                lock,
                IRVarDecl(
                    CType("bool"),
                    "opened",
                    init=IRBinOp(
                        IRBinOp(value, "!=", IRLiteral("NULL")), "&&", IRBinOp(closing, "==", IRLiteral("false"))
                    ),
                ),
                unlock,
                IRReturn(IRVar("opened")),
            ],
        )
        destroy_close = IRCall(prefix + "_close", [owner])
        destroy_check = self._native_null_guard(
            IRLiteral("NULL"), f"Native resource {resource.name}: destruction outcome is indeterminate"
        )
        destroy_check.condition = IRBinOp(destroy_close, "!=", IRLiteral("0"))
        self._native_unique_function(
            prefix + "_destroy",
            "void",
            [IRParam(CType("void*"), "raw")],
            [
                IRVarDecl(pointer, "owner", init=IRCast(pointer, IRVar("raw"))),
                destroy_check if resource.cleanup_status == "abort" else IRExprStmt(destroy_close),
                *(
                    [
                        IRExprStmt(IRCall("free", [IRFieldAccess(owner, "input", arrow=True)])),
                        IRExprStmt(IRCall("free", [IRFieldAccess(owner, "storage", arrow=True)])),
                    ]
                    if resource.storage
                    else []
                ),
                self._native_unique_checked("pthread_cond_destroy", [completed]),
                self._native_unique_checked("pthread_mutex_destroy", [mutex]),
                IRExprStmt(IRCall("free", [owner])),
            ],
        )
        self._ownership.emit_arc_descriptor(prefix, None)
        self._native_unique_function(
            prefix + "_new",
            pointer_type,
            [],
            [
                IRVarDecl(
                    pointer,
                    "owner",
                    init=IRCast(
                        pointer,
                        IRCall(
                            "__btrc_safe_calloc", [IRLiteral("1"), IRSizeof(operand=CType(f"struct {native_prefix}"))]
                        ),
                    ),
                ),
                self._native_unique_checked("pthread_mutex_init", [mutex, IRLiteral("NULL")]),
                self._native_unique_checked("pthread_cond_init", [completed, IRLiteral("NULL")]),
                *self._ownership.arc_header_initialization(prefix, "owner"),
                IRReturn(owner),
            ],
        )
        self._native_unique_function(
            native_prefix + "_retain",
            "void",
            [IRParam(CType("void*"), "raw")],
            [
                IRExprStmt(IRCall("__btrc_arc_retain", [IRVar("raw")])),
            ],
        )
        self._native_unique_function(
            native_prefix + "_release",
            "void",
            [IRParam(CType("void*"), "raw")],
            [
                IRExprStmt(IRCall("__btrc_arc_release", [IRVar("raw"), self._ownership.descriptor_pointer(prefix)])),
            ],
        )
        self._native_unique_function(
            prefix + "_close_public",
            close_type,
            parameters,
            [
                *(
                    [self._native_null_guard(owner, f"Native resource {resource.name}: close on null owner")]
                    if status_release
                    else []
                ),
                IRExprStmt(IRCall(native_prefix + "_retain", [owner])),
                IRVarDecl(CType(close_type), "result", init=IRCall(prefix + "_close", [owner]))
                if status_release
                else IRExprStmt(IRCall(prefix + "_close", [owner])),
                IRExprStmt(IRCall(native_prefix + "_release", [owner])),
                *([IRReturn(IRVar("result"))] if status_release else []),
            ],
        )
        overflow = self._native_null_guard(IRLiteral("NULL"), f"Native resource {resource.name}: borrow overflow")
        overflow.condition = IRBinOp(borrows, "==", IRVar("UINT_MAX"))
        exclusive = self._native_null_guard(
            IRLiteral("NULL"), f"Native resource {resource.name}: exclusive operation in progress"
        )
        exclusive.condition = closing
        self._native_unique_function(
            prefix + "_begin_borrow",
            "void",
            parameters,
            [
                IRIf(IRBinOp(owner, "==", IRLiteral("NULL")), IRBlock([IRReturn()])),
                lock,
                self._native_null_guard(value, f"Native resource {resource.name}: use after close"),
                exclusive,
                overflow,
                IRAssign(borrows, IRBinOp(borrows, "+", IRLiteral("1"))),
                unlock,
            ],
        )
        self._native_unique_function(
            prefix + "_end_borrow",
            "void",
            [IRParam(CType("void*"), "raw")],
            [
                IRIf(IRBinOp(IRVar("raw"), "==", IRLiteral("NULL")), IRBlock([IRReturn()])),
                IRVarDecl(pointer, "owner", init=IRCast(pointer, IRVar("raw"))),
                lock,
                IRAssign(borrows, IRBinOp(borrows, "-", IRLiteral("1"))),
                unlock,
                IRExprStmt(IRCall(native_prefix + "_release", [owner])),
            ],
        )
        if resource.storage:
            attachment_borrowed = self._native_null_guard(
                IRLiteral("NULL"), f"Native resource {resource.name}: attachment during borrow"
            )
            attachment_borrowed.condition = IRBinOp(borrows, "!=", IRLiteral("0"))
            attached = self._native_null_guard(
                IRLiteral("NULL"), f"Native resource {resource.name}: input already attached"
            )
            attached.condition = IRFieldAccess(owner, "inputAttached", arrow=True)
            self._native_unique_function(
                prefix + "_begin_attachment",
                "void",
                parameters,
                [
                    self._native_null_guard(owner, f"Native resource {resource.name}: attachment on null owner"),
                    lock,
                    exclusive,
                    self._native_null_guard(value, f"Native resource {resource.name}: use after close"),
                    attachment_borrowed,
                    attached,
                    IRAssign(closing, IRLiteral("true")),
                    IRAssign(closing_thread, IRCall("pthread_self", [])),
                    unlock,
                ],
            )
            self._native_unique_function(
                prefix + "_end_attachment",
                "void",
                [IRParam(CType("void*"), "raw")],
                [
                    IRIf(IRBinOp(IRVar("raw"), "==", IRLiteral("NULL")), IRBlock([IRReturn()])),
                    IRVarDecl(pointer, "owner", init=IRCast(pointer, IRVar("raw"))),
                    lock,
                    IRAssign(closing, IRLiteral("false")),
                    self._native_unique_checked("pthread_cond_broadcast", [completed]),
                    unlock,
                    IRExprStmt(IRCall(native_prefix + "_release", [owner])),
                ],
            )

    def _cxx_unit(self, declaration):
        module = self._session.module
        native = module.native_units.setdefault("CxxAdapters", IRModule(language="c++"))
        includes = [IRInclude(header="stdlib.h")]
        includes.extend(IRInclude(header=header, is_system=False) for header in declaration.source_file.headers)
        for include in includes:
            if include not in native.preprocessor_decls:
                native.preprocessor_decls.append(include)
        return native

    def _cxx_extern(self, native, name, result, parameters, body):
        """One extern "C" adapter: defined in the C++ unit, declared to the strict C module."""
        native.function_defs.append(
            IRFunctionDef(name=name, return_type=result, params=parameters, body=IRBlock(body), c_linkage=True)
        )
        self._session.module.function_decls.append(IRFunctionDecl(name=name, return_type=result, params=parameters))

    def emit_cxx_class(self, declaration):
        """Opaque C++ owners and owner-bound views never expose the SDK object to generated C."""
        resource = declaration.source_file.resource
        native = self._cxx_unit(declaration)
        alias, sdk = declaration.name, resource.name
        abort = IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))])
        delete = f"__btrc_cxx_{alias}_delete"
        self._cxx_extern(
            native,
            delete,
            CType("void"),
            [IRParam(CType("void*"), "value")],
            [
                IRCxxExceptionBoundary(
                    body=IRBlock([IRCxxDelete(IRCast(CType(f"{sdk}*"), IRVar("value")))]), failure=abort
                )
            ],
        )
        if resource.ownership == "unique":
            self._emit_unique_resource(declaration, symbol=alias, release_symbol=delete)
            root = alias
        elif resource.ownership == "owner-bound-value":
            root = next(name for name, owner in self._native_resources.items() if owner.name == resource.owner)
            self._emit_cxx_view(declaration, root, delete)
        else:
            raise ValueError(f"unsupported C++ ownership {resource.ownership!r}")
        for method in declaration.members:
            if method.name in {"close", "isOpen"}:
                continue
            self._emit_cxx_method(declaration, method, declaration.source_file.methods[method.name], native, root)

    def _emit_cxx_view(self, declaration, root, delete):
        """A view is an ordinary ARC object: one copied SDK value plus a claim on its root owner."""
        alias = declaration.name
        module = self._session.module
        struct_name = f"__btrc_native_{alias}"
        prefix = f"__btrc_view_{alias}"
        owner_c = CType(f"struct __btrc_native_{root}*")
        pointer = CType(f"struct {struct_name}*")
        forward = IRStructForward(name=struct_name)
        if forward not in module.struct_forwards:
            module.struct_forwards.append(forward)
        module.struct_defs.append(
            IRStructDef(
                struct_name,
                [
                    IRStructField(CType("__btrc_arc_header"), "__arc"),
                    IRStructField(owner_c, "owner"),
                    IRStructField(CType("void*"), "value"),
                ],
            )
        )
        for helper in ("__btrc_arc_retain", "__btrc_arc_release", "__btrc_safe_calloc"):
            self._session.require_helper(helper)
        self_value = IRVar("self")
        owner = IRFieldAccess(self_value, "owner", arrow=True)
        value = IRFieldAccess(self_value, "value", arrow=True)
        raw = IRParam(CType("void*"), "raw")
        self._native_unique_function(
            prefix + "_destroy",
            "void",
            [raw],
            [
                IRVarDecl(pointer, "self", init=IRCast(pointer, IRVar("raw"))),
                IRIf(IRBinOp(value, "!=", IRLiteral("NULL")), IRBlock([IRExprStmt(IRCall(delete, [value]))])),
                IRIf(
                    IRBinOp(owner, "!=", IRLiteral("NULL")),
                    IRBlock([IRExprStmt(IRCall(f"__btrc_native_{root}_release", [owner]))]),
                ),
                IRExprStmt(IRCall("free", [self_value])),
            ],
        )
        self._ownership.emit_arc_descriptor(prefix, None)
        self._native_unique_function(
            struct_name + "_retain", "void", [raw], [IRExprStmt(IRCall("__btrc_arc_retain", [IRVar("raw")]))]
        )
        self._native_unique_function(
            struct_name + "_release",
            "void",
            [raw],
            [IRExprStmt(IRCall("__btrc_arc_release", [IRVar("raw"), self._ownership.descriptor_pointer(prefix)]))],
        )
        self._native_unique_function(
            prefix + "_new",
            pointer.text,
            [IRParam(owner_c, "owner"), IRParam(CType("void*"), "value")],
            [
                IRVarDecl(
                    pointer,
                    "self",
                    init=IRCast(
                        pointer,
                        IRCall("__btrc_safe_calloc", [IRLiteral("1"), IRSizeof(CType(f"struct {struct_name}"))]),
                    ),
                ),
                *self._ownership.arc_header_initialization(prefix, "self"),
                IRExprStmt(IRCall(f"__btrc_native_{root}_retain", [IRVar("owner")])),
                IRAssign(owner, IRVar("owner")),
                IRAssign(value, IRVar("value")),
                IRReturn(self_value),
            ],
        )

    def _emit_cxx_method(self, declaration, method, contract, native, root):
        """The C++ unit catches every exception; the C wrapper borrows the root owner and throws afterwards."""
        resource = declaration.source_file.resource
        projection = contract.cxx_method
        sdk_method = projection.method
        alias, sdk = declaration.name, resource.name
        # Calls on a unique owner route through its public symbol family; views
        # are ordinary native classes.
        name = (
            f"__btrc_unique_{alias}_{method.name}_public"
            if resource.ownership == "unique"
            else f"{alias}_{method.name}"
        )
        adapter = f"__btrc_cxx_{alias}_{method.name}"
        module = self._session.module
        factory = bool(projection.factory_result)
        view_result = contract.resource_result
        string_result = contract.copied_result is not None
        result_type = CType(self._types.render(method.return_type))
        returns_scalar = not factory and not view_result and not string_result and result_type.text != "void"
        parameters = [self._signatures.lower_source_param(parameter) for parameter in method.params]
        cxx_parameters = [] if factory else [IRParam(CType("void*"), "receiver")]
        cxx_parameters.extend(IRParam(parameter.c_type, parameter.name) for parameter in parameters)
        record = projection.result_record
        outputs = []
        if factory:
            outputs.append(IRParam(CType("void**"), "outValue"))
            outputs.extend(
                IRParam(CType(self._types.render(field.value_type) + "*"), f"out_{field.name}")
                for field in record.fields
            )
        elif view_result:
            outputs.append(IRParam(CType("void**"), "outValue"))
        elif string_result:
            outputs.append(IRParam(CType("const char**"), "outValue"))
        elif returns_scalar:
            outputs.append(IRParam(CType(result_type.text + "*"), "outValue"))
        cxx_parameters.extend(outputs)
        native_arguments = []
        for parameter, native_type in zip(parameters, sdk_method.signature.parameters, strict=True):
            unqualified = native_type
            while isinstance(unqualified, (NativeAlias, NativeQualifiedType)):
                unqualified = unqualified.underlying
            value = IRVar(parameter.name)
            if isinstance(unqualified, NativeEnumType):
                value = IRCast(CType(unqualified.name), value)
            native_arguments.append(value)
        out = IRDeref(IRVar("outValue"))
        if factory:
            target = IRVar("object")
            sdk_result = IRVar("sdkResult")
            attempt = [
                IRAssign(target, IRCxxNew(CType(sdk), [])),
                IRVarDecl(
                    CType(record.native_spelling),
                    "sdkResult",
                    init=IRCall(IRFieldAccess(target, sdk_method.method_name, arrow=True), native_arguments),
                ),
                *[
                    IRAssign(IRDeref(IRVar(f"out_{field.name}")), IRFieldAccess(sdk_result, field.name))
                    for field in record.fields
                ],
                IRIf(
                    condition=IRBinOp(
                        IRFieldAccess(sdk_result, projection.status_field), "!=", IRVar(projection.success)
                    ),
                    then_block=IRBlock([IRCxxDelete(target), IRAssign(out, IRLiteral("NULL"))]),
                    else_block=IRBlock([IRAssign(out, target)]),
                ),
                IRReturn(IRLiteral("0")),
            ]
            body = [
                IRVarDecl(CType(f"{sdk}*"), "object", init=IRLiteral("NULL")),
                IRCxxExceptionBoundary(
                    body=IRBlock(attempt), failure=IRBlock([IRCxxDelete(target), IRReturn(IRLiteral("1"))])
                ),
            ]
        else:
            receiver = IRCast(CType(f"{sdk}*"), IRVar("receiver"))
            call = IRCall(IRFieldAccess(receiver, sdk_method.method_name, arrow=True), native_arguments)
            if view_result:
                attempt = [IRAssign(out, IRCxxNew(CType(self._native_resources[view_result].name), [call]))]
            elif string_result or returns_scalar:
                attempt = [IRAssign(out, call)]
            else:
                attempt = [IRExprStmt(call)]
            attempt.append(IRReturn(IRLiteral("0")))
            body = [IRCxxExceptionBoundary(body=IRBlock(attempt), failure=IRBlock([IRReturn(IRLiteral("1"))]))]
        self._cxx_extern(native, adapter, CType("int"), cxx_parameters, body)
        self._session.require_helper("__btrc_throw")
        c_parameters = list(parameters)
        statements = []
        call_arguments = [IRVar(parameter.name) for parameter in parameters]
        owner = None
        if not factory:
            self_value = IRVar("self")
            c_parameters.insert(0, IRParam(CType(f"struct __btrc_native_{alias}*"), "self"))
            statements.append(self._native_null_guard(self_value, f"C++ call {sdk_method.name}: null receiver"))
            owner = self_value if resource.ownership == "unique" else IRFieldAccess(self_value, "owner", arrow=True)
            statements.extend(
                [
                    IRExprStmt(IRCall(f"__btrc_native_{root}_retain", [owner])),
                    IRExprStmt(IRCall(f"__btrc_unique_{root}_begin_borrow", [owner])),
                ]
            )
            call_arguments.insert(0, IRFieldAccess(self_value, "value", arrow=True))
        if factory:
            statements.append(IRVarDecl(CType("void*"), "outValue", init=IRLiteral("NULL")))
            call_arguments.append(IRAddressOf(IRVar("outValue")))
            for field in record.fields:
                statements.append(
                    IRVarDecl(CType(self._types.render(field.value_type)), f"out_{field.name}", init=IRLiteral("0"))
                )
                call_arguments.append(IRAddressOf(IRVar(f"out_{field.name}")))
        elif view_result:
            statements.append(IRVarDecl(CType("void*"), "outValue", init=IRLiteral("NULL")))
            call_arguments.append(IRAddressOf(IRVar("outValue")))
        elif string_result:
            statements.append(IRVarDecl(CType("const char*"), "outValue", init=IRLiteral("NULL")))
            call_arguments.append(IRAddressOf(IRVar("outValue")))
        elif returns_scalar:
            statements.append(IRVarDecl(result_type, "outValue", init=IRLiteral("0")))
            call_arguments.append(IRAddressOf(IRVar("outValue")))
        statements.append(IRVarDecl(CType("int"), "status", init=IRCall(adapter, call_arguments)))
        if owner is not None:
            statements.append(IRExprStmt(IRCall(f"__btrc_unique_{root}_end_borrow", [owner])))
        statements.append(
            IRIf(
                IRBinOp(IRVar("status"), "!=", IRLiteral("0")),
                IRBlock(
                    [
                        IRExprStmt(
                            IRCall(
                                "__btrc_throw",
                                helper_ref="__btrc_throw",
                                never_returns=True,
                                args=[IRLiteral(json.dumps(f"C++ exception in {sdk_method.name}"))],
                            )
                        )
                    ]
                ),
            )
        )
        if factory:
            status_field_type = TypeExpr(base=record.name, pointer_depth=1)
            status_type = CType(self._types.render(status_field_type))
            outcome_type = CType(self._types.render(TypeExpr(base=projection.factory_result, pointer_depth=1)))
            owner_type = CType(f"struct __btrc_native_{alias}*")
            status_value, outcome = IRVar("statusValue"), IRVar("outcome")
            statements.extend(
                [
                    IRVarDecl(status_type, "statusValue", init=IRCall(f"{record.name}_new", [])),
                    *[
                        IRAssign(IRFieldAccess(status_value, field.name, arrow=True), IRVar(f"out_{field.name}"))
                        for field in record.fields
                    ],
                    IRVarDecl(outcome_type, "outcome", init=IRCall(f"{projection.factory_result}_new", [])),
                    IRAssign(IRFieldAccess(outcome, "called", arrow=True), IRLiteral("true")),
                    # The outcome's field holds the status record through an ordinary
                    # managed edge; the constructing local drops its own claim.
                    IRAssign(IRFieldAccess(outcome, "status", arrow=True), status_value),
                    IRExprStmt(self._lifetime.retain_edge_value(status_value, status_field_type, outcome)),
                    IRExprStmt(self._lifetime.release_value(status_value, status_field_type)),
                    IRIf(
                        IRBinOp(IRVar("outValue"), "!=", IRLiteral("NULL")),
                        IRBlock(
                            [
                                IRVarDecl(owner_type, "owner", init=IRCall(f"__btrc_unique_{alias}_new", [])),
                                IRAssign(IRFieldAccess(IRVar("owner"), "value", arrow=True), IRVar("outValue")),
                                IRAssign(IRFieldAccess(outcome, "value", arrow=True), IRVar("owner")),
                            ]
                        ),
                    ),
                    IRReturn(outcome),
                ]
            )
        elif view_result:
            statements.append(IRReturn(IRCall(f"__btrc_view_{view_result}_new", [owner, IRVar("outValue")])))
        elif string_result:
            self._session.require_helper("__btrc_string_alloc")
            pointer, length, result = IRVar("outValue"), IRVar("length"), IRVar("result")
            statements.extend(
                [
                    IRVarDecl(result_type, "result", init=IRLiteral("NULL")),
                    IRIf(
                        IRBinOp(pointer, "!=", IRLiteral("NULL")),
                        IRBlock(
                            [
                                IRVarDecl(CType("size_t"), "length", init=IRCall("strlen", [pointer])),
                                IRIf(
                                    IRBinOp(length, "<=", IRLiteral("2147483647U")),
                                    IRBlock(
                                        [
                                            IRAssign(
                                                result, IRCall("__btrc_string_alloc", [IRCast(CType("int"), length)])
                                            ),
                                            IRExprStmt(IRCall("memcpy", [result, pointer, length])),
                                        ]
                                    ),
                                ),
                            ]
                        ),
                    ),
                    IRReturn(result),
                ]
            )
        elif returns_scalar:
            statements.append(IRReturn(IRVar("outValue")))
        module.function_decls.append(
            IRFunctionDecl(name=name, return_type=result_type, params=c_parameters, is_static=True)
        )
        module.function_defs.append(
            IRFunctionDef(
                name=name, return_type=result_type, params=c_parameters, is_static=True, body=IRBlock(statements)
            )
        )

    # Per Java value kind: the JNI call-family suffix, its C type and its jvalue member.
    _JAVA_VALUES: ClassVar[dict[str, tuple[str, str, str]]] = {
        "Z": ("Boolean", "jboolean", "z"),
        "B": ("Byte", "jbyte", "b"),
        "C": ("Char", "jchar", "c"),
        "S": ("Short", "jshort", "s"),
        "I": ("Int", "jint", "i"),
        "J": ("Long", "jlong", "j"),
        "F": ("Float", "jfloat", "f"),
        "D": ("Double", "jdouble", "d"),
        "string": ("Object", "jstring", "l"),
        "object": ("Object", "jobject", "l"),
        "V": ("Void", "void", ""),
    }
    _JAVA_ENVIRONMENT = "__btrc_java_env"

    @classmethod
    def _java_env_call(cls, slot, *arguments):
        """A call through the thread's JNI function table, by its JNI-spec slot name."""
        environment = IRVar(cls._JAVA_ENVIRONMENT)
        return IRCall(IRFieldAccess(IRDeref(environment), slot, arrow=True), [environment, *arguments])

    def _java_translate(self, pop, before=()):
        """F1: clear the pending Java exception, pop the frame when `pop`, and throw its message."""
        self._session.require_helper("__btrc_throw")
        message = IRVar("__btrc_java_message")
        return IRBlock(
            [
                *before,
                IRVarDecl(CType("char"), message.name, array_size=IRLiteral("1024")),
                IRExprStmt(
                    IRCall(
                        "btrcJavaTakeException",
                        [IRVar(self._JAVA_ENVIRONMENT), IRLiteral("1" if pop else "0"), message, IRSizeof(message)],
                    )
                ),
                IRExprStmt(IRCall("__btrc_throw", [message], helper_ref="__btrc_throw", never_returns=True)),
            ]
        )

    def _java_check(self, before=()):
        """The exception check that follows every throwing JNI call in an adapter."""
        return IRIf(self._java_env_call("ExceptionCheck"), self._java_translate(True, before))

    def emit_java_class(self, declaration):
        """A selected Java class: a unique owner of one global reference, and one checked adapter per member."""
        symbol = declaration.name
        release = f"__btrc_java_{symbol}_release"
        native = IRVar("native")
        self._native_unique_function(
            release,
            "void",
            [IRParam(CType("jobject"), "native")],
            [
                IRVarDecl(CType("JNIEnv*"), self._JAVA_ENVIRONMENT, init=IRCall("btrcJavaEnvironment", [])),
                IRExprStmt(self._java_env_call("DeleteGlobalRef", native)),
                IRExprStmt(IRCall("btrcJavaUnclaim", [])),
            ],
        )
        self._emit_unique_resource(declaration, symbol=symbol, release_symbol=release)
        for member in declaration.members:
            if member.name not in {"close", "isOpen"}:
                self._emit_java_member(declaration, member, declaration.source_file.methods[member.name].java_member)

    def _emit_java_member(self, declaration, member, java):
        """One member's adapter: borrow owners, frame the local references, call, check, convert, unwind.

        Every throwing JNI call is followed by its exception check; a failure
        translates through btrcJavaTakeException, which pops the frame on
        every path a successful PushLocalFrame dominates, before the BTRC
        exception starts (F1). Leased owners end their borrows through the
        adapter's cleanup scope on both paths.
        """
        symbol = declaration.name
        what = f"Java call {symbol}.{member.name}"
        field = java.kind in ("getter", "setter")
        environment = IRVar(self._JAVA_ENVIRONMENT)
        parameters = [self._signatures.lower_source_param(parameter) for parameter in member.params]
        result_type = CType(self._types.render(member.return_type))
        instance = not java.static_member and java.kind != "constructor"
        c_parameters = list(parameters)
        statements = [
            IRVarDecl(CType("jclass"), "__btrc_java_class", init=IRLiteral("NULL"), is_static=True),
            IRVarDecl(
                CType("jfieldID" if field else "jmethodID"),
                "__btrc_java_member",
                init=IRLiteral("NULL"),
                is_static=True,
            ),
        ]
        releases = []
        if instance:
            c_parameters.insert(0, IRParam(CType(f"struct __btrc_native_{symbol}*"), "self"))
            statements.append(self._native_null_guard(IRVar("self"), f"{what}: null receiver"))
        cleanup = self._native_cleanup_scope(c_parameters, statements)
        receiver = (
            self._native_lease(
                0,
                TypeExpr(base=symbol, is_nullable=True, pointer_depth=1),
                IRVar("self"),
                c_parameters,
                statements,
                releases,
            )
            if instance
            else None
        )
        leases = {
            index: self._native_lease(
                index + 1, parameter.type, IRVar(parameter.name), c_parameters, statements, releases
            )
            for index, (parameter, kind) in enumerate(zip(member.params, java.parameters, strict=True))
            if kind == "object"
        }
        strings = sum(kind == "string" for kind in java.parameters)
        capacity = 2 + strings + int(java.result in ("string", "object"))
        statements.extend(
            [
                IRVarDecl(CType("JNIEnv*"), self._JAVA_ENVIRONMENT, init=IRCall("btrcJavaEnvironment", [])),
                IRIf(
                    IRBinOp(self._java_env_call("PushLocalFrame", IRLiteral(str(capacity))), "!=", IRLiteral("0")),
                    self._java_translate(False),
                ),
                IRVarDecl(
                    CType("jclass"),
                    "__btrc_java_owner",
                    init=IRCall(
                        "btrcJavaClass",
                        [environment, IRAddressOf(IRVar("__btrc_java_class")), IRLiteral(json.dumps(java.binary_name))],
                    ),
                ),
                self._java_check(),
                IRVarDecl(
                    CType("jfieldID" if field else "jmethodID"),
                    "__btrc_java_id",
                    init=IRCall(
                        "btrcJavaField" if field else "btrcJavaMethod",
                        [
                            environment,
                            IRVar("__btrc_java_owner"),
                            IRAddressOf(IRVar("__btrc_java_member")),
                            IRLiteral(json.dumps(java.member_name)),
                            IRLiteral(json.dumps(java.descriptor)),
                            IRLiteral("1" if java.static_member else "0"),
                        ],
                    ),
                ),
                self._java_check(),
            ]
        )
        arguments = IRVar("__btrc_java_arguments")
        if java.kind != "getter":
            statements.append(
                IRVarDecl(CType("jvalue"), arguments.name, array_size=IRLiteral(str(max(1, len(member.params)))))
            )
        if not member.params and java.kind != "getter":
            statements.append(IRAssign(IRFieldAccess(IRIndex(arguments, IRLiteral("0")), "j"), IRLiteral("0")))
        for index, (parameter, kind) in enumerate(zip(member.params, java.parameters, strict=True)):
            slot = IRFieldAccess(IRIndex(arguments, IRLiteral(str(index))), self._JAVA_VALUES[kind][2])
            value = IRVar(parameter.name)
            if kind == "string":
                statements.extend(
                    [IRAssign(slot, IRCall("btrcJavaNewString", [environment, value])), self._java_check()]
                )
            elif kind == "object":
                lease = leases[index]
                statements.append(
                    IRAssign(
                        slot,
                        IRTernary(
                            IRBinOp(lease, "!=", IRLiteral("NULL")),
                            IRFieldAccess(lease, "value", arrow=True),
                            IRLiteral("NULL"),
                        ),
                    )
                )
            else:
                statements.append(IRAssign(slot, IRCast(CType(self._JAVA_VALUES[kind][1]), value)))
        target = IRFieldAccess(receiver, "value", arrow=True) if instance else IRVar("__btrc_java_owner")
        identifier = IRVar("__btrc_java_id")
        family = self._JAVA_VALUES[java.result][0]
        static = "Static" if java.static_member else ""
        if java.kind == "constructor":
            call = self._java_env_call("NewObjectA", target, identifier, arguments)
        elif java.kind == "method":
            call = self._java_env_call(f"Call{static}{family}MethodA", target, identifier, arguments)
        elif java.kind == "getter":
            call = self._java_env_call(f"Get{static}{family}Field", target, identifier)
        else:
            value_kind = java.parameters[0]
            call = self._java_env_call(
                f"Set{static}{self._JAVA_VALUES[value_kind][0]}Field",
                target,
                identifier,
                IRFieldAccess(IRIndex(arguments, IRLiteral("0")), self._JAVA_VALUES[value_kind][2]),
            )
        outcome = IRVar("__btrc_java_result")
        if java.result == "V":
            statements.append(IRExprStmt(call))
        else:
            native_type = CType(self._JAVA_VALUES[java.result][1])
            statements.append(
                IRVarDecl(
                    native_type, outcome.name, init=IRCast(native_type, call) if java.result == "string" else call
                )
            )
        statements.append(self._java_check())
        returned = None
        if java.result == "object":
            returned = self._java_object_result(member, java, outcome, c_parameters, statements)
        elif java.result == "string":
            returned = self._java_string_result(outcome, result_type, statements)
        elif java.result != "V":
            returned = IRCast(result_type, outcome)
        statements.append(IRExprStmt(self._java_env_call("PopLocalFrame", IRLiteral("NULL"))))
        statements.extend([*releases, *cleanup])
        if java.kind == "constructor":
            statements.append(self._native_null_guard(returned, f"{what}: null result"))
        if returned is not None:
            statements.append(IRReturn(returned))
        name = f"__btrc_unique_{symbol}_{member.name}_public"
        self._native_unique_function(name, result_type.text, c_parameters, statements)

    def _java_object_result(self, member, java, outcome, parameters, statements):
        """A local result becomes a new owner of one global reference before the frame pops.

        The owner is registered in a cleanup slot before NewGlobalRef, the next
        throwing call, so a failure there releases it with no reference.
        """
        owner = java.owner if java.kind == "constructor" else member.return_type.base
        value_type = TypeExpr(base=owner, is_nullable=True, pointer_depth=1)
        slot = IRVarDecl(CType(self._types.render(value_type)), "__btrc_java_object", init=IRLiteral("NULL"))
        result = IRVar(slot.name)
        global_reference = IRVar("__btrc_java_global")
        missing = self._native_null_guard(
            global_reference, f"Java call {java.owner}.{member.name}: no memory for a global reference"
        )
        statements.extend(
            [
                slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(slot, value_type)),
                IRIf(
                    IRBinOp(outcome, "!=", IRLiteral("NULL")),
                    IRBlock(
                        [
                            IRAssign(result, IRCall(f"__btrc_unique_{owner}_new", [])),
                            IRVarDecl(
                                CType("jobject"),
                                global_reference.name,
                                init=self._java_env_call("NewGlobalRef", outcome),
                            ),
                            self._java_check(),
                            missing,
                            IRAssign(IRFieldAccess(result, "value", arrow=True), global_reference),
                            IRExprStmt(IRCall("btrcJavaClaim", [])),
                        ]
                    ),
                ),
            ]
        )
        return result

    def _java_string_result(self, outcome, result_type, statements):
        """A Java string copies through UTF-16 into a new BTRC string; null stays null.

        U+0000 has no BTRC spelling, so such a string throws after the copy is
        freed and the frame is popped.
        """
        for helper in ("__btrc_string_alloc", "__btrc_safe_calloc", "__btrc_throw"):
            self._session.require_helper(helper)
        text, count, units, length = (
            IRVar("__btrc_java_text"),
            IRVar("__btrc_java_count"),
            IRVar("__btrc_java_units"),
            IRVar("__btrc_java_length"),
        )
        release_units = IRExprStmt(IRCall("free", [units]))

        def refuse(message):
            return IRBlock(
                [
                    release_units,
                    IRExprStmt(self._java_env_call("PopLocalFrame", IRLiteral("NULL"))),
                    IRExprStmt(
                        IRCall(
                            "__btrc_throw",
                            [IRLiteral(json.dumps(message))],
                            helper_ref="__btrc_throw",
                            never_returns=True,
                        )
                    ),
                ]
            )

        statements.extend(
            [
                IRVarDecl(result_type, text.name, init=IRLiteral("NULL")),
                IRIf(
                    IRBinOp(outcome, "!=", IRLiteral("NULL")),
                    IRBlock(
                        [
                            IRVarDecl(CType("jsize"), count.name, init=self._java_env_call("GetStringLength", outcome)),
                            self._java_check(),
                            IRVarDecl(
                                CType("jchar*"),
                                units.name,
                                init=IRCast(
                                    CType("jchar*"),
                                    IRCall(
                                        "__btrc_safe_calloc",
                                        [
                                            IRBinOp(IRCast(CType("size_t"), count), "+", IRLiteral("1")),
                                            IRSizeof(CType("jchar")),
                                        ],
                                    ),
                                ),
                            ),
                            IRExprStmt(self._java_env_call("GetStringRegion", outcome, IRLiteral("0"), count, units)),
                            self._java_check([release_units]),
                            IRVarDecl(
                                CType("long long"), length.name, init=IRCall("btrcJavaStringLength", [units, count])
                            ),
                            IRIf(
                                IRBinOp(length, "<", IRLiteral("0")),
                                refuse("Java string contains U+0000, which a BTRC string cannot hold"),
                            ),
                            IRIf(
                                IRBinOp(length, ">", IRLiteral("2147483646")),
                                refuse("Java string is too long for a BTRC string"),
                            ),
                            IRAssign(text, IRCall("__btrc_string_alloc", [IRCast(CType("int"), length)])),
                            IRExprStmt(IRCall("btrcJavaEncodeString", [units, count, text])),
                            release_units,
                        ]
                    ),
                ),
            ]
        )
        return text

    def _native_unique_result(self, declaration, call, parameters, statements, releases, cleanup):
        # Allocate and register the ordinary ARC owner before native publication.
        # Null factory results discard that empty owner; no native claim can leak
        # if allocating the owner fails.
        resource = declaration.source_file.call_contract.resource_result
        prefix = f"__btrc_unique_{resource}"
        name = "__btrc_unique_result"
        while any(parameter.name == name for parameter in parameters):
            name += "_"
        result_type = CType(self._types.render(declaration.return_type))
        if not cleanup:
            cleanup.extend(self._native_cleanup_scope(parameters, statements))
        slot = IRVarDecl(result_type, name, init=IRCall(prefix + "_new", []))
        result = IRVar(name)
        value = IRFieldAccess(result, "value", arrow=True)
        statements.extend(
            [
                slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(slot, declaration.return_type)),
                IRAssign(value, call),
            ]
        )
        statements.append(
            IRIf(
                IRBinOp(value, "==", IRLiteral("NULL")),
                IRBlock(
                    [
                        IRExprStmt(IRCall(f"__btrc_native_{resource}_release", [result])),
                        IRAssign(result, IRLiteral("NULL")),
                    ]
                ),
            )
        )
        statements.extend(releases)
        if declaration.source_file.call_contract.nonnull_return:
            statements.append(self._native_null_guard(result, f"Native call {declaration.name}: null result"))
        statements.extend([*cleanup, IRReturn(result)])

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
            self._require_objective_c_struct(record)
            # The analyzer has validated by-value layouts. Preserve the same
            # dependency-first order as the self-hosted native declaration owner.
            for field in TypeSystem.record_fields(record):
                if not field.type.pointer_depth and field.type.base in records:
                    append_record(records[field.type.base])
            fields = [
                IRStructField(c_type=CType(text=self._types.render(field.type)), name=field.name)
                for field in TypeSystem.record_declarators(record)
            ]
            for unit in (module, native):
                unit.struct_forwards.append(IRStructForward(name=name))
                unit.struct_defs.append(IRStructDef(name=name, fields=fields))

        for record in records.values():
            append_record(record)
        return native

    @staticmethod
    def _require_objective_c_struct(record) -> None:
        """The Objective-C adapters rebuild a record member by member, which is
        wrong for a union; native union values stay refused (ref:3191-3192),
        so meeting one here is a compiler defect, never a user error."""
        if record.is_union:
            raise CodegenError(f"internal error: Objective-C record '{record.name}' is a union")

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
        self._require_objective_c_struct(record)
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
                for field in TypeSystem.record_fields(record)
            ],
        )

    def emit_native_global(self, declaration):
        """Expose scalar storage; object reads cross ARC as independent owned values."""
        if declaration.source_file.language == "c":
            name = f"__btrc_native_read_{declaration.name}"
            result_type = CType(text=self._types.render(declaration.type))
            result_name = "__btrc_native_global_result"
            while result_name == declaration.name:
                result_name += "_"
            result = IRVar(name=result_name)
            statements = [
                IRVarDecl(
                    c_type=result_type,
                    name=result.name,
                    init=IRCast(target_type=result_type, expr=IRVar(name=declaration.name)),
                )
            ]
            if not declaration.type.is_nullable:
                statements.append(self._native_null_guard(result, f"Native global {declaration.name}: null result"))
            statements.append(IRExprStmt(expr=self._lifetime.retain_value(result, declaration.type)))
            statements.append(IRReturn(value=result))
            self._session.module.function_decls.append(
                IRFunctionDecl(name=name, return_type=result_type, params=[], is_static=True)
            )
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=name, return_type=result_type, params=[], is_static=True, body=IRBlock(stmts=statements)
                )
            )
            return
        native = self._objective_c_unit(declaration)
        if declaration.name in self._analyzed.native_owned_globals:
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
            if info.native_language != "objective-c":
                continue
            forward = IRStructForward(name=f"__btrc_native_{info.name}")
            if forward not in native.struct_forwards:
                native.struct_forwards.append(forward)
                module.struct_forwards.append(forward)
        self._emit_objective_c_lifetime(declaration, native)
        self._emit_objective_c_downcast(declaration, native)
        for method in declaration.members:
            contract = declaration.source_file.methods[method.name]
            if any(callback.one_shot for callback in contract.callbacks):
                self._emit_one_shot_objective_c_adapter(declaration, method, contract, native)
                continue
            if any(isinstance(callback, NativeInstantiatedProjection) for callback in contract.callbacks):
                self._emit_instance_instantiated_adapter(declaration, method, contract, native)
                continue
            if any(callback.unregister is not None for callback in contract.callbacks):
                self._emit_stored_objective_c_adapter(declaration, method, contract, native)
                continue
            descriptor = contract.objective_c_method
            initializer = (
                descriptor.method_family == "init" and not descriptor.class_method and descriptor.related_result
            )
            class_factory = descriptor.class_method or initializer
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
            if initializer:
                receiver = IRObjectiveCMessage(receiver, "alloc", [])
            if not class_factory:
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
            offset = int(not class_factory)
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
            if not class_factory:
                required.insert(0, "self")
            for parameter in required:
                statements.append(
                    self._objective_c_null_guard(
                        IRVar(name=parameter), f"Objective-C call {descriptor.name}: null argument {parameter}"
                    )
                )
            argument_types = [parameter.type for parameter in method.params]
            if not class_factory:
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
        result_value_type = self._native_callback_result(callback)
        result_type = CType(self._types.render(result_value_type))
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
        context_value = IRVar(parameters[context_index].name)
        if getattr(callback, "context_spelling", "") not in {"", "pointer"}:
            # A pointer-width integer slot holds the context pointer exactly.
            context_value = IRCast(CType("uintptr_t"), context_value)
        context = IRCast(CType(self._types.render(context_type)), context_value)
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
            result_slot = IRVarDecl(result_type, "result", init=IRLiteral("0"))
            body.append(result_slot)
            info = self._analyzed.class_table.get(callback.return_type.base)
            if info is not None and info.native_language:
                # The callback returns one ordinary managed claim. Unwinding
                # releases it; normal return transfers it to the native block.
                body.append(IRExprStmt(self._lifetime.register_cleanup_slot(result_slot, result_value_type)))
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

    _STATUS_SUCCESS: ClassVar[dict[str, tuple[str, str]]] = {
        "nonzero": ("!=", "0"),
        "positive": (">", "0"),
        "nonnegative": (">=", "0"),
        "zero": ("==", "0"),
    }

    def _emit_stored_c_adapter(self, declaration, contract):
        """Register a C callback the SDK stores until its unregister call returns.

        A calloc'd holder records the context and every captured unregister
        argument. The registration's token is an OwnedClosure over that holder:
        its unregister calls the SDK with the same callback, context and
        captured values; its destroy, run once the registration has drained,
        drops the external context claim the SDK held and frees the holder.
        Context slots carry the context itself, so each live registration is
        distinct to the SDK (a Win32 subclass id, its reference data).
        """
        module = self._session.module
        callback = contract.callbacks[0]
        name = contract.adapter_symbol(declaration.name)
        prefix = f"__btrc_native_{declaration.name}_stored"
        context_type = declaration.return_type
        context_c = CType(self._types.render(context_type))
        context_symbol = context_c.text.removesuffix("*").strip()
        token_type = context_type.generic_args[1]
        token_c = CType(self._types.render(token_type))
        token_symbol = token_c.text.removesuffix("*").strip()
        invoke, _values = self._stored_context_invoker(prefix, callback, context_type, context_symbol)
        integer_context = callback.context_spelling not in {"", "pointer"}

        def context_argument(value):
            raw = IRCast(CType("void*"), value)
            if integer_context:
                return IRCast(CType(callback.context_spelling), IRCast(CType("uintptr_t"), raw))
            return raw

        parameters = [self._signatures.lower_source_param(parameter) for parameter in declaration.params]
        native_count = len(parameters) - 1 + len(callback.registration_contexts)
        visible = [index for index in range(native_count) if index not in callback.registration_contexts]
        holder_type = CType(f"struct {prefix}_holder*")
        captured = sorted(
            {source for kind, *rest in callback.unregister_arguments if kind == "captured" for source in rest}
        )
        module.struct_defs.append(
            IRStructDef(
                name=f"{prefix}_holder",
                fields=[
                    IRStructField(CType("void*"), "context"),
                    *(
                        IRStructField(CType(parameters[visible.index(source)].c_type.text), f"captured{source}")
                        for source in captured
                    ),
                ],
            )
        )
        holder = IRVar("holder")
        raw = IRVar("rawHolder")

        def status_check(value, status):
            if not status:
                return []
            operator, bound = self._STATUS_SUCCESS[status]
            return [
                IRIf(
                    IRUnaryOp(op="!", operand=IRBinOp(value, operator, IRLiteral(bound))),
                    IRBlock([IRReturn(IRLiteral("false"))]),
                )
            ]

        # Destroy: the registration has drained; drop the SDK's claim and the holder.
        stored_context = IRCast(context_c, IRFieldAccess(holder, "context", arrow=True))
        module.function_defs.append(
            IRFunctionDef(
                name=f"{prefix}_destroy",
                return_type=CType("void"),
                params=[IRParam(CType("void*"), raw.name)],
                is_static=True,
                body=IRBlock(
                    [
                        IRVarDecl(holder_type, holder.name, init=IRCast(holder_type, raw)),
                        IRIf(
                            IRFieldAccess(holder, "context", arrow=True),
                            IRBlock([IRExprStmt(self._lifetime.release_value(stored_context, context_type))]),
                        ),
                        IRExprStmt(IRCall("free", [holder])),
                    ]
                ),
            )
        )
        module.function_decls.append(
            IRFunctionDecl(f"{prefix}_destroy", CType("void"), [IRParam(CType("void*"), raw.name)], is_static=True)
        )
        # Native unregister: the same callback, context and captured values.
        unregister = callback.unregister
        unregister_arguments = []
        for kind, *rest in callback.unregister_arguments:
            if kind == "callback":
                unregister_arguments.append(IRFunctionRef(invoke))
            elif kind == "context":
                unregister_arguments.append(context_argument(IRFieldAccess(holder, "context", arrow=True)))
            else:
                unregister_arguments.append(IRFieldAccess(holder, f"captured{rest[0]}", arrow=True))
        unregister_call = IRCall(unregister.name, unregister_arguments)
        self._session.module.native_external_names.add(unregister.name)
        unregister_body = [IRVarDecl(holder_type, holder.name, init=IRCast(holder_type, raw))]
        if callback.unregister_status:
            result_c = CType(self._types.render(callback.unregister_result))
            unregister_body.append(IRVarDecl(result_c, "status", init=unregister_call))
            unregister_body.extend(status_check(IRVar("status"), callback.unregister_status))
        else:
            unregister_body.append(IRExprStmt(unregister_call))
        unregister_body.append(IRReturn(IRLiteral("true")))
        module.function_defs.append(
            IRFunctionDef(
                name=f"{prefix}_unregister",
                return_type=CType("bool"),
                params=[IRParam(CType("void*"), raw.name)],
                is_static=True,
                body=IRBlock(unregister_body),
            )
        )
        module.function_decls.append(
            IRFunctionDecl(f"{prefix}_unregister", CType("bool"), [IRParam(CType("void*"), raw.name)], is_static=True)
        )
        # The context's cancellation operation forwards to its token.
        token = IRVar("token")
        module.function_defs.append(
            IRFunctionDef(
                name=f"{prefix}_cancel",
                return_type=CType("bool"),
                params=[IRParam(token_c, token.name)],
                is_static=True,
                body=IRBlock([IRReturn(IRCall(f"{token_symbol}_unregister", [token]))]),
            )
        )
        module.function_decls.append(
            IRFunctionDecl(f"{prefix}_cancel", CType("bool"), [IRParam(token_c, token.name)], is_static=True)
        )
        # The registration adapter.
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
        scope = arguments[-1]
        receiver = arguments[visible.index(callback.parameter_index)]
        self._session.require_helper("__btrc_safe_calloc")
        body.append(
            IRVarDecl(
                holder_type,
                holder.name,
                init=IRCast(
                    holder_type,
                    IRCall("__btrc_safe_calloc", [IRLiteral("1"), IRSizeof(CType(f"struct {prefix}_holder"))]),
                ),
            )
        )
        for source in captured:
            body.append(
                IRAssign(IRFieldAccess(holder, f"captured{source}", arrow=True), arguments[visible.index(source)])
            )
        token_slot = IRVarDecl(
            token_c,
            "registrationToken",
            init=IRCall(
                f"{token_symbol}_new",
                [
                    IRFunctionRef(f"{prefix}_destroy"),
                    IRCast(CType("void*"), holder),
                    IRFunctionRef(f"{prefix}_destroy"),
                    IRFunctionRef(f"{prefix}_unregister"),
                    IRCast(CType("void*"), holder),
                ],
            ),
        )
        body.extend([token_slot, IRExprStmt(self._lifetime.register_cleanup_slot(token_slot, token_type))])
        context = IRVar("context")
        context_slot = IRVarDecl(
            context_c, context.name, init=IRCall(f"{context_symbol}_new", [receiver, IRFunctionRef(f"{prefix}_cancel")])
        )
        body.extend([context_slot, IRExprStmt(self._lifetime.register_cleanup_slot(context_slot, context_type))])
        # The SDK holds one external claim from here until destroy.
        body.extend(
            [
                IRExprStmt(self._lifetime.retain_value(context, context_type)),
                IRAssign(IRFieldAccess(holder, "context", arrow=True), IRCast(CType("void*"), context)),
                IRExprStmt(IRCall(f"{context_symbol}_activate", [context, scope])),
            ]
        )
        native_arguments = {}
        for position, index in enumerate(visible):
            native_arguments[index] = arguments[position]
        native_arguments[callback.parameter_index] = IRFunctionRef(invoke)
        for index in callback.registration_contexts:
            native_arguments[index] = context_argument(context)
        registration = IRCall(declaration.name, [native_arguments[index] for index in range(native_count)])
        if callback.registration_status:
            operator, bound = self._STATUS_SUCCESS[callback.registration_status]
            result_c = CType(self._types.render(callback.registration_result))
            body.append(IRVarDecl(result_c, "registrationStatus", init=registration))
            body.append(
                IRIf(
                    IRUnaryOp(op="!", operand=IRBinOp(IRVar("registrationStatus"), operator, IRLiteral(bound))),
                    self._stored_activation_failure(
                        callback, context_symbol, context, f"Stored callback {declaration.name}: registration failed"
                    ),
                )
            )
        else:
            body.append(IRExprStmt(registration))
        body.append(IRExprStmt(IRCall(f"{context_symbol}_publish", [context, IRVar(token_slot.name)])))
        release_locals = []
        token_release = self._lifetime.release_and_clear(
            IRVar(token_slot.name), token_type, release_locals, token_c.text
        )
        body.extend(
            [
                *release_locals,
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

    def _stored_action_holder(self, native, invocation_type, captured_types=()):
        """The target answers btrcInvoke: from its own source only.

        A control action's holder also keeps the registration values its
        remove call repeats, read back through btrcCaptured<i>.
        """
        holder = native.objective_c_classes[-1]
        configure = holder.methods[0]
        configure.selector += "invoke:source:"
        configure.params.extend([IRParam(CType(invocation_type), "invoke"), IRParam(CType("id"), "source")])
        holder.fields.extend([IRStructField(CType(invocation_type), "_invoke"), IRStructField(CType("id"), "_source")])
        configure.body.stmts.extend(
            [IRAssign(IRVar("_invoke"), IRVar("invoke")), IRAssign(IRVar("_source"), IRVar("source"))]
        )
        for index, captured_type in enumerate(captured_types):
            configure.selector += f"captured{index}:"
            configure.params.append(IRParam(captured_type, f"captured{index}"))
            holder.fields.append(IRStructField(captured_type, f"_captured{index}"))
            configure.body.stmts.append(IRAssign(IRVar(f"_captured{index}"), IRVar(f"captured{index}")))
            holder.methods.append(
                IRObjectiveCMethod(
                    f"btrcCaptured{index}", captured_type, [], IRBlock([IRReturn(IRVar(f"_captured{index}"))])
                )
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
        control = isinstance(callback, NativeControlActionProjection)
        object_callback = isinstance(
            callback, (NativeDelegateProjection, NativeActionProjection, NativeControlActionProjection)
        )
        # The projected method omits a control action's selector parameter.
        target_position = callback.parameter_index - int(control and callback.parameter_index > callback.action_index)

        captured_types = []
        if control:
            for position in callback.captured:
                value_type = method.params[position - int(position > callback.action_index)].type
                captured_types.append((position, value_type, CType(self._types.render(value_type))))
        name = f"{declaration.name}_{method.name}"
        prefix = f"__btrc_objc_{name}"
        context_type = method.return_type
        context_symbol = self._types.render(context_type).removesuffix("*").strip()
        token_type = context_type.generic_args[1]
        paired = bool(callback.unregister.signature.parameters) and not callback.unregister.class_method
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
                    CType(self._types.render(self._native_callback_result(projection))),
                    [CType(self._types.render(value)) for value in value_types],
                )
            )
        for typedef in typedefs:
            module.function_pointer_typedefs.append(typedef)
            native.function_pointer_typedefs.append(typedef)
        holder_name = self._stored_context_holder(prefix, native, lifetime_type)
        configure_selector = (
            self._stored_action_holder(native, invocation_types[0], [c_type for _, _, c_type in captured_types])
            if action or control
            else self._stored_delegate_holder(callback, native, invocation_types, callback_types)
            if object_callback
            else "configure:retain:release:"
        )
        token = IRVar("token")
        unregister_adapter = prefix + "_unregister_adapter"
        unregister_parameters = [IRParam(native_token_c, token.name)]
        unregister_receiver = IRCast(self._objective_c_object_type(native_token_type.base), token, bridge="borrow")
        unregister_arguments = []
        if callback.unregister.class_method:
            unregister_arguments.append(unregister_receiver)
            unregister_receiver = IRVar(callback.unregister.receiver)
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
        if control:
            stored_holder = IRCast(CType(holder_name + "*"), token, bridge="borrow")
            remove_arguments = []
            for position in range(len(callback.unregister.signature.parameters)):
                if position == callback.parameter_index:
                    remove_arguments.append(IRCast(CType("id"), token, bridge="borrow"))
                elif position == callback.action_index:
                    remove_arguments.append(IRObjectiveCSelector("btrcInvoke:"))
                else:
                    index = [captured for captured, _, _ in captured_types].index(position)
                    remove_arguments.append(
                        self._objective_c_value(
                            captured_types[index][1],
                            IRObjectiveCMessage(stored_holder, f"btrcCaptured{index}", []),
                            to_native=True,
                        )
                    )
            unregister_body = [
                IRExprStmt(IRObjectiveCMessage(unregister_receiver, callback.unregister.selector, remove_arguments))
            ]
        elif object_callback:
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
            if index == target_position:
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
                                else IRReturn(
                                    IRCast(
                                        CType(callback.native_return),
                                        invocation,
                                        bridge="transfer"
                                        if self._analyzed.class_table.get(callback.return_type.base) is not None
                                        else "",
                                    )
                                ),
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
        if control:
            native_arguments.insert(callback.action_index, IRObjectiveCSelector("btrcInvoke:"))
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
                        *([native_receiver] if action or control else []),
                        *[
                            IRVar(parameters[receiver_offset + position - int(position > callback.action_index)].name)
                            for position, _, _ in captured_types
                        ],
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
        if control:
            # The control adds a pair and keeps every other target; it has no slot to verify.
            native_body[-2:-1] = [
                IRExprStmt(IRObjectiveCMessage(native_receiver, descriptor.selector, native_arguments)),
                IRAssign(IRDeref(IRVar("nativeResult")), IRCast(native_token_c, holder, bridge="retain")),
            ]
        elif object_callback:
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
                [arguments[target_position + receiver_offset], IRFunctionRef(unregister)],
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
                if index == target_position + receiver_offset
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

    def _emit_instantiated_adapter(self, declaration, contract):
        """Name a generated adapter class to the SDK entry that instantiates it.

        The C wrapper roots the receiver in a CallbackRoot and passes the root,
        its retain function and one invoker per protocol method to the
        Objective-C unit. There the adapter keeps them in file statics for the
        generated class, takes the permanent external claim and calls the SDK
        entry with that class's name. With scope = "process" the first `-init`
        claims the root; a second instantiation or registration aborts.
        """
        module = self._session.module
        native = self._objective_c_unit(declaration)
        for info in self._analyzed.class_table.values():
            if info.native_language != "objective-c":
                continue
            forward = IRStructForward(name=f"__btrc_native_{info.name}")
            if forward not in native.struct_forwards:
                native.struct_forwards.append(forward)
                module.struct_forwards.append(forward)
        callback = contract.callbacks[0]
        prefix = f"__btrc_objc_{declaration.name}"
        root_type = TypeExpr(
            base="CallbackRoot", generic_args=[declaration.params[callback.parameter_index].type], pointer_depth=1
        )
        root_symbol = self._types.render(root_type).removesuffix("*").strip()
        self._stored_context_lifetime(prefix, root_type, root_symbol)
        lifetime_type = prefix + "_lifetime"
        typedefs = [IRFunctionPointerTypedef(lifetime_type, CType("void"), [CType("void*")])]
        invokers = []
        invocation_types = []
        callback_types = []
        for index, projection in enumerate(callback.methods):
            invocation_type = f"{prefix}_callback{index}"
            invoke, value_types = self._stored_context_invoker(f"{prefix}_{index}", projection, root_type, root_symbol)
            invokers.append(invoke)
            invocation_types.append(invocation_type)
            callback_types.append(value_types)
            typedefs.append(
                IRFunctionPointerTypedef(
                    invocation_type,
                    CType(self._types.render(self._native_callback_result(projection))),
                    [CType(self._types.render(value)) for value in value_types],
                )
            )
        for typedef in typedefs:
            module.function_pointer_typedefs.append(typedef)
            native.function_pointer_typedefs.append(typedef)
        context = IRVar(prefix + "_context")
        instances = IRVar(prefix + "_instances")
        native.global_decls.extend(
            [
                IRGlobalDecl(CType("void*"), context.name, init=IRLiteral("NULL")),
                IRGlobalDecl(CType("int"), instances.name, init=IRLiteral("0")),
                *[
                    IRGlobalDecl(CType(invocation_type), f"{prefix}_invoke{index}", init=IRLiteral("NULL"))
                    for index, invocation_type in enumerate(invocation_types)
                ],
            ]
        )

        def reject():
            return IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))])

        holder = prefix + "Holder"
        methods = [
            IRObjectiveCMethod(
                "init",
                CType("instancetype"),
                [],
                IRBlock(
                    [
                        IRAssign(IRVar("self"), IRObjectiveCMessage(IRVar("super"), "init", [])),
                        IRIf(IRBinOp(IRVar("self"), "==", IRLiteral("nil")), IRBlock([IRReturn(IRLiteral("nil"))])),
                        IRIf(
                            IRBinOp(
                                IRBinOp(instances, "!=", IRLiteral("0")),
                                "||",
                                IRBinOp(context, "==", IRLiteral("NULL")),
                            ),
                            reject(),
                        ),
                        IRAssign(instances, IRLiteral("1")),
                        IRReturn(IRVar("self")),
                    ]
                ),
            )
        ]
        for index, (method, value_types) in enumerate(zip(callback.methods, callback_types)):
            native_parameters, arguments = self._instantiated_arguments(method, value_types)
            invocation = IRCall(IRVar(f"{prefix}_invoke{index}"), [*arguments, context])
            methods.append(
                IRObjectiveCMethod(
                    method.native_method.selector,
                    CType(method.native_return),
                    native_parameters,
                    IRBlock(
                        [IRExprStmt(invocation)]
                        if self._types.render(method.return_type) == "void"
                        else self._instantiated_result(method, invocation)
                    ),
                )
            )
        native.objective_c_classes.append(
            IRObjectiveCClass(name=holder, superclass="NSObject", methods=methods, protocols=[callback.protocol])
        )
        parameters = [self._signatures.lower_source_param(parameter) for parameter in declaration.params]
        result_type = CType(self._types.render(declaration.return_type))
        returns = result_type.text != "void"
        adapter_parameters = [
            parameter for index, parameter in enumerate(parameters) if index != callback.parameter_index
        ]
        adapter_parameters.extend(
            [
                *[IRParam(CType(value), f"invoke{index}") for index, value in enumerate(invocation_types)],
                IRParam(CType("void*"), "context"),
                IRParam(CType(lifetime_type), "retainContext"),
            ]
        )
        native_arguments = []
        for index, (parameter, source) in enumerate(zip(parameters, declaration.params)):
            if index == callback.parameter_index:
                native_arguments.append(IRVar("className"))
                continue
            argument = IRVar(parameter.name)
            info = self._analyzed.class_table.get(source.type.base)
            native_arguments.append(
                IRCast(self._objective_c_object_type(source.type.base), argument, bridge="borrow")
                if info is not None and info.native_language
                else argument
            )
        call = IRCall(declaration.name, native_arguments)
        native_body = [
            IRIf(IRBinOp(context, "!=", IRLiteral("NULL")), reject()),
            IRExprStmt(IRCall(IRVar("retainContext"), [IRVar("context")])),
            IRAssign(context, IRVar("context")),
            *[IRAssign(IRVar(f"{prefix}_invoke{index}"), IRVar(f"invoke{index}")) for index in range(len(invokers))],
            IRVarDecl(
                CType("NSString*"),
                "className",
                init=IRCall("NSStringFromClass", [IRObjectiveCMessage(IRVar(holder), "class", [])]),
            ),
            IRReturn(call) if returns else IRExprStmt(call),
        ]
        native.function_defs.append(
            IRFunctionDef(
                name=prefix,
                return_type=result_type,
                params=adapter_parameters,
                body=IRBlock(
                    [
                        IRObjectiveCAutoreleasePool(
                            IRBlock([IRObjectiveCExceptionBoundary(IRBlock(native_body), reject())])
                        )
                    ]
                ),
            )
        )
        module.function_decls.append(IRFunctionDecl(prefix, result_type, adapter_parameters))
        body = []
        cleanup = self._native_cleanup_scope(parameters, body)
        arguments = [IRVar(parameter.name) for parameter in parameters]
        for index, nonnull in enumerate(contract.nonnull_parameters):
            if nonnull:
                body.append(
                    self._native_null_guard(
                        arguments[index], f"Native call {declaration.name}: null argument {parameters[index].name}"
                    )
                )
        root_slot = IRVarDecl(
            CType(self._types.render(root_type)),
            "root",
            init=IRCall(f"{root_symbol}_new", [arguments[callback.parameter_index]]),
        )
        body.extend([root_slot, IRExprStmt(self._lifetime.register_cleanup_slot(root_slot, root_type))])
        adapter_arguments = [argument for index, argument in enumerate(arguments) if index != callback.parameter_index]
        adapter_arguments.extend(
            [
                *[IRFunctionRef(invoke) for invoke in invokers],
                IRCast(CType("void*"), IRVar(root_slot.name)),
                IRFunctionRef(prefix + "_retain"),
            ]
        )
        call = IRCall(prefix, adapter_arguments)
        if returns:
            body.append(IRVarDecl(result_type, "result", init=call))
            body.extend(cleanup)
            body.append(IRReturn(IRVar("result")))
        else:
            body.append(IRExprStmt(call))
            body.extend(cleanup)
        name = contract.adapter_symbol(declaration.name)
        module.function_decls.append(IRFunctionDecl(name, result_type, parameters, is_static=True))
        module.function_defs.append(
            IRFunctionDef(name=name, return_type=result_type, params=parameters, body=IRBlock(body), is_static=True)
        )

    def _instantiated_arguments(self, method, value_types):
        """A generated instantiated class's native parameters and the invoker arguments they become."""
        parameters = [
            IRParam(CType(value), f"argument{position}") for position, value in enumerate(method.native_parameters)
        ]
        arguments = []
        for parameter, value_type in zip(parameters, value_types):
            value = IRVar(parameter.name)
            info = self._analyzed.class_table.get(value_type.base)
            if info is not None and info.native_language:
                value = IRCast(CType(self._types.render(value_type)), value, bridge="borrow")
            arguments.append(value)
        return parameters, arguments

    def _instantiated_result(self, method, invocation, before_return=()):
        """Return one protocol method's result from a generated instantiated class.

        A managed object result is the receiver's own claim, transferred to
        ARC; null for an SDK non-null object result terminates here.
        """
        info = self._analyzed.class_table.get(method.return_type.base)
        managed = info is not None and bool(info.native_language)
        value = IRCast(CType(method.native_return), invocation, bridge="transfer" if managed else "")
        statements = [IRVarDecl(CType(method.native_return), "result", init=value), *before_return]
        if managed and not method.return_type.is_nullable:
            statements.append(
                IRIf(
                    IRBinOp(IRVar("result"), "==", IRLiteral("nil")),
                    IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))]),
                )
            )
        statements.append(IRReturn(IRVar("result")))
        return statements

    def _instantiated_receiver_creator(self, prefix, callback, factory_root, receiver_root):
        """Enter the rooted factory, call create() and root the receiver it returns for one instance.

        The new root carries one claim, which the instance owns.
        """
        factory_type, receiver_type = factory_root.generic_args[0], receiver_root.generic_args[0]
        factory_symbol = self._types.render(factory_root).removesuffix("*").strip()
        receiver_symbol = self._types.render(receiver_root).removesuffix("*").strip()
        parameters = [IRParam(CType("void*"), "rawFactory")]
        body = []
        cleanup = self._native_cleanup_scope(parameters, body)
        context = IRCast(CType(self._types.render(factory_root)), IRVar("rawFactory"))
        factory_slot = IRVarDecl(
            CType(self._types.render(factory_type)), "factory", init=IRCall(f"{factory_symbol}_enter", [context])
        )
        receiver_slot = IRVarDecl(CType(self._types.render(receiver_type)), "receiver", init=IRLiteral("NULL"))
        factory, receiver = IRVar(factory_slot.name), IRVar(receiver_slot.name)
        body.extend(
            [
                factory_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(factory_slot, factory_type)),
                receiver_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(receiver_slot, receiver_type)),
                IRIf(
                    factory,
                    IRBlock(
                        [
                            IRAssign(receiver, IRCall(f"{callback.factory}_create", [factory])),
                            IRExprStmt(IRCall(f"{factory_symbol}_leave", [context])),
                        ]
                    ),
                ),
                self._native_null_guard(receiver, "Instantiated adapter factory returned no receiver"),
                IRVarDecl(
                    CType(self._types.render(receiver_root)), "root", init=IRCall(f"{receiver_symbol}_new", [receiver])
                ),
            ]
        )
        release_locals = []
        releases = [
            *self._lifetime.release_and_clear(
                receiver, receiver_type, release_locals, self._types.render(receiver_type)
            ),
            *self._lifetime.release_and_clear(factory, factory_type, release_locals, self._types.render(factory_type)),
        ]
        body.extend(
            [
                *release_locals,
                *[IRExprStmt(value) for value in releases],
                *cleanup,
                *self._exceptions.pop_try_frames(1),
                IRReturn(IRCast(CType("void*"), IRVar("root"))),
            ]
        )
        name = prefix + "_create"
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=name,
                return_type=CType("void*"),
                params=parameters,
                is_static=True,
                body=self._exceptions.native_callback_boundary(IRBlock(body)),
            )
        )
        return name

    def _emit_instance_instantiated_adapter(self, declaration, method, contract, native):
        """Hand the SDK a generated class it instantiates once per instance (scope = "instance").

        `-[UISceneConfiguration setDelegateClass:]` takes a class, and UIKit
        creates one delegate per scene. The C wrapper roots the factory in a
        CallbackRoot. The Objective-C unit keeps that root, the receiver
        creator and one invoker per protocol method in file statics, replacing
        and then releasing a previous factory, and passes the generated
        class. Each `-init` takes a new receiver root from the factory, and
        each method pins that root for its call. After the terminal method
        returns the instance releases its receiver: later void methods do
        nothing and value methods abort. `-dealloc` releases a receiver still
        held. Instances that already exist keep their receivers when the
        factory is replaced.
        """
        module = self._session.module
        descriptor = contract.objective_c_method
        callback = contract.callbacks[0]
        prefix = f"__btrc_objc_{declaration.name}_{method.name}"
        factory_type = method.params[callback.parameter_index].type
        factory_root = TypeExpr(base="CallbackRoot", generic_args=[factory_type], pointer_depth=1)
        receiver_root = TypeExpr(
            base="CallbackRoot", generic_args=[TypeExpr(base=callback.interface, pointer_depth=1)], pointer_depth=1
        )
        factory_symbol = self._types.render(factory_root).removesuffix("*").strip()
        receiver_symbol = self._types.render(receiver_root).removesuffix("*").strip()
        self._stored_context_lifetime(prefix, factory_root, factory_symbol)
        self._stored_context_lifetime(prefix + "_receiver", receiver_root, receiver_symbol)
        lifetime_type = prefix + "_lifetime"
        creator_type = prefix + "_creator"
        typedefs = [
            IRFunctionPointerTypedef(lifetime_type, CType("void"), [CType("void*")]),
            IRFunctionPointerTypedef(creator_type, CType("void*"), [CType("void*")]),
        ]
        invokers = []
        callback_types = []
        for index, projection in enumerate(callback.methods):
            invoke, value_types = self._stored_context_invoker(
                f"{prefix}_{index}", projection, receiver_root, receiver_symbol
            )
            invokers.append(invoke)
            callback_types.append(value_types)
            typedefs.append(
                IRFunctionPointerTypedef(
                    f"{prefix}_callback{index}",
                    CType(self._types.render(self._native_callback_result(projection))),
                    [CType(self._types.render(value)) for value in value_types],
                )
            )
        for typedef in typedefs:
            module.function_pointer_typedefs.append(typedef)
            native.function_pointer_typedefs.append(typedef)
        creator = self._instantiated_receiver_creator(prefix, callback, factory_root, receiver_root)
        statics = {
            "factory": "void*",
            "retainFactory": lifetime_type,
            "releaseFactory": lifetime_type,
            "createReceiver": creator_type,
            "retainReceiver": lifetime_type,
            "releaseReceiver": lifetime_type,
            **{f"invoke{index}": f"{prefix}_callback{index}" for index in range(len(invokers))},
        }
        native.global_decls.extend(
            IRGlobalDecl(CType(value), f"{prefix}_{name}", init=IRLiteral("NULL")) for name, value in statics.items()
        )

        def static(name):
            return IRVar(f"{prefix}_{name}")

        def reject():
            return IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))])

        receiver = IRVar("receiver")
        held = IRVar("_receiver")
        methods = [
            IRObjectiveCMethod(
                "init",
                CType("instancetype"),
                [],
                IRBlock(
                    [
                        IRAssign(IRVar("self"), IRObjectiveCMessage(IRVar("super"), "init", [])),
                        IRIf(IRBinOp(IRVar("self"), "==", IRLiteral("nil")), IRBlock([IRReturn(IRLiteral("nil"))])),
                        IRVarDecl(CType("void*"), "factory", init=static("factory")),
                        IRIf(IRBinOp(IRVar("factory"), "==", IRLiteral("NULL")), reject()),
                        IRExprStmt(IRCall(static("retainFactory"), [IRVar("factory")])),
                        IRAssign(held, IRCall(static("createReceiver"), [IRVar("factory")])),
                        IRExprStmt(IRCall(static("releaseFactory"), [IRVar("factory")])),
                        IRReturn(IRVar("self")),
                    ]
                ),
            )
        ]
        for index, (projection, value_types) in enumerate(zip(callback.methods, callback_types)):
            parameters, arguments = self._instantiated_arguments(projection, value_types)
            returns = self._types.render(projection.return_type) != "void"
            body = [
                IRVarDecl(CType("void*"), receiver.name, init=held),
                IRIf(IRBinOp(receiver, "==", IRLiteral("NULL")), reject() if returns else IRBlock([IRReturn()])),
                # The terminal method takes the instance's claim; any other
                # method pins the receiver root for its call.
                IRAssign(held, IRLiteral("NULL"))
                if index == callback.terminal_index
                else IRExprStmt(IRCall(static("retainReceiver"), [receiver])),
            ]
            invocation = IRCall(static(f"invoke{index}"), [*arguments, receiver])
            release = IRExprStmt(IRCall(static("releaseReceiver"), [receiver]))
            body.extend(
                self._instantiated_result(projection, invocation, (release,))
                if returns
                else [IRExprStmt(invocation), release]
            )
            methods.append(
                IRObjectiveCMethod(
                    projection.native_method.selector, CType(projection.native_return), parameters, IRBlock(body)
                )
            )
        methods.append(
            IRObjectiveCMethod(
                "dealloc",
                CType("void"),
                [],
                IRBlock(
                    [
                        IRVarDecl(CType("void*"), receiver.name, init=held),
                        IRIf(
                            IRBinOp(receiver, "!=", IRLiteral("NULL")),
                            IRBlock(
                                [
                                    IRAssign(held, IRLiteral("NULL")),
                                    IRExprStmt(IRCall(static("releaseReceiver"), [receiver])),
                                ]
                            ),
                        ),
                    ]
                ),
            )
        )
        holder = prefix + "Holder"
        native.objective_c_classes.append(
            IRObjectiveCClass(
                name=holder,
                superclass="NSObject",
                fields=[IRStructField(CType("void*"), held.name)],
                methods=methods,
                protocols=[callback.protocol],
            )
        )
        receiver_parameter = IRParam(CType(f"struct __btrc_native_{declaration.name}*"), "self")
        adapter_parameters = [
            receiver_parameter,
            *[IRParam(CType(f"{prefix}_callback{index}"), f"invoke{index}") for index in range(len(invokers))],
            IRParam(CType(creator_type), "create"),
            IRParam(CType("void*"), "context"),
            *[
                IRParam(CType(lifetime_type), name)
                for name in ("retainContext", "releaseContext", "retainReceiver", "releaseReceiver")
            ],
        ]
        registration = [
            IRExprStmt(IRCall(IRVar("retainContext"), [IRVar("context")])),
            IRVarDecl(CType("void*"), "previous", init=static("factory")),
            IRAssign(static("factory"), IRVar("context")),
            IRAssign(static("retainFactory"), IRVar("retainContext")),
            IRAssign(static("releaseFactory"), IRVar("releaseContext")),
            IRAssign(static("createReceiver"), IRVar("create")),
            IRAssign(static("retainReceiver"), IRVar("retainReceiver")),
            IRAssign(static("releaseReceiver"), IRVar("releaseReceiver")),
            *[IRAssign(static(f"invoke{index}"), IRVar(f"invoke{index}")) for index in range(len(invokers))],
            IRExprStmt(
                IRObjectiveCMessage(
                    IRCast(self._objective_c_object_type(declaration.name), IRVar("self"), bridge="borrow"),
                    descriptor.selector,
                    [IRObjectiveCMessage(IRVar(holder), "class", [])],
                )
            ),
            # Instances already created keep their own receiver roots.
            IRIf(
                IRBinOp(IRVar("previous"), "!=", IRLiteral("NULL")),
                IRBlock([IRExprStmt(IRCall(IRVar("releaseContext"), [IRVar("previous")]))]),
            ),
        ]
        native.function_defs.append(
            IRFunctionDef(
                name=prefix,
                return_type=CType("void"),
                params=adapter_parameters,
                body=IRBlock(
                    [
                        IRObjectiveCAutoreleasePool(
                            IRBlock([IRObjectiveCExceptionBoundary(IRBlock(registration), reject())])
                        )
                    ]
                ),
            )
        )
        module.function_decls.append(IRFunctionDecl(prefix, CType("void"), adapter_parameters))
        parameters = [receiver_parameter, *[self._signatures.lower_source_param(item) for item in method.params]]
        self._session.require_helper("__btrc_throw")
        statements = [
            self._objective_c_null_guard(
                IRVar(parameter.name), f"Objective-C call {descriptor.name}: null argument {parameter.name}"
            )
            for parameter in parameters
        ]
        releases = []
        cleanup = self._native_cleanup_scope(parameters, statements)
        receiver_type = TypeExpr(base=declaration.name, pointer_depth=1)
        leased = self._native_lease(0, receiver_type, IRVar("self"), parameters, statements, releases)
        root_slot = IRVarDecl(
            CType(self._types.render(factory_root)),
            "root",
            init=IRCall(f"{factory_symbol}_new", [IRVar(parameters[1 + callback.parameter_index].name)]),
        )
        statements.extend(
            [
                root_slot,
                IRExprStmt(self._lifetime.register_cleanup_slot(root_slot, factory_root)),
                IRExprStmt(
                    IRCall(
                        prefix,
                        [
                            leased,
                            *[IRFunctionRef(invoke) for invoke in invokers],
                            IRFunctionRef(creator),
                            IRCast(CType("void*"), IRVar(root_slot.name)),
                            IRFunctionRef(prefix + "_retain"),
                            IRFunctionRef(prefix + "_release"),
                            IRFunctionRef(prefix + "_receiver_retain"),
                            IRFunctionRef(prefix + "_receiver_release"),
                        ],
                    )
                ),
            ]
        )
        release_locals = []
        root_release = self._lifetime.release_and_clear(
            IRVar(root_slot.name), factory_root, release_locals, self._types.render(factory_root)
        )
        statements.extend([*release_locals, *[IRExprStmt(value) for value in root_release], *releases])
        flush = self._lifetime.flush_release_batch(type_exprs=[receiver_type])
        if flush is not None:
            statements.append(IRExprStmt(flush))
        statements.extend(cleanup)
        name = f"{declaration.name}_{method.name}"
        result_type = CType(self._types.render(method.return_type))
        module.function_decls.append(
            IRFunctionDecl(name=name, return_type=result_type, params=parameters, is_static=True)
        )
        module.function_defs.append(
            IRFunctionDef(
                name=name, return_type=result_type, params=parameters, is_static=True, body=IRBlock(statements)
            )
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

    def _emit_objective_c_downcast(self, declaration, native):
        """M3 for Objective-C: `(T?)value` asks the object isKindOfClass: in the Objective-C unit.

        Every class gets the C helper, which the optimizer drops when no cast
        reaches it. The helper leases the source, and a match takes a new
        native claim before that lease ends; null skips the test.
        """
        if declaration.name == "id":
            return
        self._emit_objective_c_kind_test(native)
        target_type = TypeExpr(base=declaration.name, is_nullable=True, pointer_depth=1)
        result_type = CType(self._types.render(target_type))
        parameters = [IRParam(result_type, "source")]
        statements, releases = [], []
        cleanup = self._native_cleanup_scope(parameters, statements)
        source = self._native_lease(0, target_type, IRVar("source"), parameters, statements, releases)
        matches = IRBinOp(
            source,
            "&&",
            IRCall("__btrc_objc_is_kind", [IRCast(CType("void*"), source), IRLiteral(json.dumps(declaration.name))]),
        )
        result = IRVarDecl(result_type, "__btrc_native_projection", init=IRTernary(matches, source, IRLiteral("NULL")))
        value = IRVar(result.name)
        statements.extend(
            [
                result,
                IRExprStmt(self._lifetime.retain_value(value, target_type)),
                IRExprStmt(self._lifetime.register_cleanup_slot(result, target_type)),
                *releases,
                *cleanup,
                IRReturn(value),
            ]
        )
        name = f"__btrc_objc_{declaration.name}_try_cast"
        self._session.module.function_decls.append(IRFunctionDecl(name, result_type, parameters, is_static=True))
        self._session.module.function_defs.append(
            IRFunctionDef(name, result_type, parameters, IRBlock(statements), is_static=True)
        )

    def _emit_objective_c_kind_test(self, native):
        """One isKindOfClass: test per Objective-C unit, naming the class by its runtime name.

        An imported class may be only a forward declaration in the selected
        headers, where `[T class]` would neither compile nor link, so the
        unit looks the class up with objc_lookUpClass. A class missing at run
        time matches no object.
        """
        name = "__btrc_objc_is_kind"
        if any(function.name == name for function in native.function_defs):
            return
        include = IRInclude(header="objc/runtime.h")
        if include not in native.preprocessor_decls:
            native.preprocessor_decls.append(include)
        parameters = [IRParam(CType("void*"), "value"), IRParam(CType("const char*"), "name")]
        test = IRObjectiveCMessage(
            IRCast(CType("id"), IRVar("value"), bridge="borrow"),
            "isKindOfClass:",
            [IRCall("objc_lookUpClass", [IRVar("name")])],
        )
        boundary = IRObjectiveCExceptionBoundary(
            IRBlock([IRReturn(IRTernary(test, IRLiteral("1"), IRLiteral("0")))]),
            IRBlock([IRExprStmt(IRCall("abort", [], never_returns=True))]),
        )
        native.function_defs.append(
            IRFunctionDef(name, CType("int"), parameters, IRBlock([IRObjectiveCAutoreleasePool(IRBlock([boundary]))]))
        )
        self._session.module.function_decls.append(IRFunctionDecl(name, CType("int"), parameters))

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
        self._session.declare_function_once(declaration)

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
