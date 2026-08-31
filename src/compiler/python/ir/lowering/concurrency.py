"""Cohesive concurrency IR lowering owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRDoWhile,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRSwitch,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from src.compiler.python.syntax.ast.generated import (
    Block,
    Capture,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    ReturnStmt,
    TypeExpr,
)

from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from .calls import CallableProvenance, CallableReturnABI
    from .ownership import (
        CleanupSlotRegistry,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
    )
    from .session import LoweringSession
    from .storage import StorageLowerer


@dataclass(frozen=True, slots=True)
class ThreadSpawnPlan:
    """Deferred wrapper declaration for one source spawn lambda."""

    function: LambdaExpr
    wrapper_name: str
    environment_name: str
    return_c_type: str
    return_type: TypeExpr | None
    capture_abis: tuple[tuple[Capture, CallableReturnABI], ...]


@dataclass(frozen=True, slots=True)
class ThreadWrapperBodyPlan:
    source: Block | None
    prelude: tuple[IRStmt, ...]
    local_bindings: tuple[str, ...]
    callable_abis: tuple[tuple[Capture, CallableReturnABI], ...]


@dataclass(frozen=True, slots=True)
class SyncMethodPlan:
    """A canonical built-in concurrency method selected without lowering operands."""

    receiver_type: TypeExpr
    method_name: str


class ConcurrencyLowerer:
    """Own concurrency lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        type_identity: TypeIdentity,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cleanup_slots: CleanupSlotRegistry,
        storage: StorageLowerer,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._type_identity = type_identity
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cleanup_slots = cleanup_slots
        self._storage = storage

    def create_mutex_value(self, value, value_type: TypeExpr):
        """Create a mutex that owns an exact copy of ``value``."""
        canonical = self._types.canonical_value_type(value_type)
        if canonical is None:
            raise CodegenError("cannot resolve Mutex value type")
        access, slot_access, context, context_size, retain, release, finalize, raise_callback = (
            self._ownership_callbacks(
                canonical,
            )
        )
        self._session.require_helper("__btrc_mutex_val_create")
        return IRCall(
            callee="__btrc_mutex_val_create",
            args=[
                self._types.box_exact_value(value, canonical, prefix="__btrc_mutex"),
                IRSizeof(operand=CType(text=self._types.value_storage_c_type(canonical))),
                access,
                slot_access,
                context,
                context_size,
                retain,
                release,
                finalize,
                raise_callback,
            ],
            helper_ref="__btrc_mutex_val_create",
        )

    def get_mutex_value(self, mutex, value_type: TypeExpr):
        """Copy the stored value while locked and return one typed value."""
        self._session.require_helper("__btrc_mutex_val_get")
        payload = IRCall(callee="__btrc_mutex_val_get", args=[mutex], helper_ref="__btrc_mutex_val_get")
        return self._types.unbox_exact_value(payload, value_type, prefix="__btrc_mutex")

    def set_mutex_value(self, mutex: IRExpr, value: IRExpr, mutex_type: TypeExpr) -> IRExpr:
        """Evaluate the receiver before boxing the value for a locked swap."""
        value_type = mutex_type.generic_args[0]
        receiver_declaration = IRVarDecl(
            c_type=CType(text=self._types.render(mutex_type)),
            name=self._session.fresh_temp("__btrc_mutex_receiver"),
        )
        self._session.record_declaration(receiver_declaration)
        receiver = IRVar(name=receiver_declaration.name)
        self._session.require_helper("__btrc_mutex_val_set")
        call = IRCall(
            callee="__btrc_mutex_val_set",
            args=[receiver, self._types.box_exact_value(value, value_type, prefix="__btrc_mutex")],
            helper_ref="__btrc_mutex_val_set",
        )
        return IRStmtExpr(
            stmts=[receiver_declaration],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=receiver, op="=", right=mutex),
                    call,
                ]
            ),
        )

    def _ownership_callbacks(self, value_type: TypeExpr):
        if self._values.is_string(value_type):
            access = self._value_access(
                value_type,
            )
            return (
                access,
                IRLiteral(text="NULL"),
                IRLiteral(text="NULL"),
                IRLiteral(text="0"),
                self._callback("__btrc_mutex_string_retain"),
                self._callback("__btrc_mutex_string_release"),
                IRLiteral(text="NULL"),
                IRLiteral(text="NULL"),
            )
        if self._values.is_class(value_type):
            return (
                self._value_access(
                    value_type,
                ),
                self._slot_access(
                    value_type,
                ),
                self._lifetime.arc_type_descriptor(value_type),
                IRSizeof(operand=CType(text="__btrc_arc_type")),
                self._callback("__btrc_mutex_arc_retain"),
                self._callback("__btrc_mutex_arc_release"),
                self._callback("__btrc_mutex_arc_finalize"),
                self._callback("__btrc_throw"),
            )
        null = IRLiteral(text="NULL")
        return (null, null, null, IRLiteral(text="0"), null, null, null, null)

    def _value_access(self, value_type: TypeExpr):
        name = self._cleanup_slots.ensure_mutex_value_adapter(CType(text=self._types.value_storage_c_type(value_type)))
        return IRFunctionRef(name=name)

    def _slot_access(self, value_type: TypeExpr):
        name = self._cleanup_slots.ensure_arc_slot_adapter(CType(text=self._types.value_storage_c_type(value_type)))
        return IRFunctionRef(name=name)

    def _callback(self, name: str):
        self._session.require_helper(name)
        return IRFunctionRef(name=name)

    def lower_thread_method(self, obj, method_name, obj_type):
        if method_name != "join":
            return IRCall(callee=f"__btrc_thread_{method_name}", args=[obj])
        self._session.require_helper("__btrc_thread_join")
        return_type = obj_type.generic_args[0] if obj_type.generic_args else None
        call = IRCall(
            callee="__btrc_thread_join", args=[self.consume_thread_handle(obj)], helper_ref="__btrc_thread_join"
        )
        if return_type is None or return_type.base == "void":
            return call
        return self.unbox_thread_result(
            call,
            return_type,
        )

    def lower_mutex_method(self, obj, method_name, obj_type, args):
        value_type = obj_type.generic_args[0] if obj_type.generic_args else None
        if method_name == "get":
            return self.get_mutex_value(
                obj,
                value_type,
            )
        if method_name == "set":
            if args:
                return self.set_mutex_value(
                    obj,
                    args[0],
                    obj_type,
                )
            raise CodegenError("Mutex.set() requires one value")
        if method_name == "destroy":
            raise CodegenError("Mutex.destroy() must be lowered as a standalone expression statement")
        return IRCall(callee=f"__btrc_mutex_val_{method_name}", args=[obj] + args)

    def plan_sync_method(
        self,
        obj_type: TypeExpr | None,
        method_name: str,
    ) -> SyncMethodPlan | None:
        """Classify a Thread/Mutex/Atomic method without traversing source operands."""
        receiver_type = self._types.canonical_type(obj_type)
        if (
            receiver_type is None
            or receiver_type.base not in {"Thread", "Mutex", "Atomic"}
            or not receiver_type.generic_args
        ):
            return None
        return SyncMethodPlan(receiver_type=receiver_type, method_name=method_name)

    def materialize_sync_method(
        self,
        plan: SyncMethodPlan,
        obj: IRExpr,
        args: list[IRExpr],
    ) -> IRExpr:
        """Materialize a classified method from source-ordered operands."""
        if plan.receiver_type.base == "Thread":
            return self.lower_thread_method(
                obj,
                plan.method_name,
                plan.receiver_type,
            )
        if plan.receiver_type.base == "Atomic":
            return self.lower_atomic_method(
                obj,
                plan.method_name,
                plan.receiver_type,
                args,
            )
        return self.lower_mutex_method(
            obj,
            plan.method_name,
            plan.receiver_type,
            args,
        )

    def lower_atomic_method(
        self,
        atomic: IRExpr,
        method_name: str,
        receiver_type: TypeExpr,
        args: list[IRExpr],
    ) -> IRExpr:
        """Lower one validated typed operation directly to its explicit C11 form."""
        self._session.require_runtime_header("stdatomic.h")
        address = atomic if receiver_type.pointer_depth > 0 else IRUnaryOp(op="&", operand=atomic)
        functions = {
            "init": "atomic_init",
            "load": "atomic_load_explicit",
            "store": "atomic_store_explicit",
            "exchange": "atomic_exchange_explicit",
            "fetchAdd": "atomic_fetch_add_explicit",
            "fetchSub": "atomic_fetch_sub_explicit",
            "fetchAnd": "atomic_fetch_and_explicit",
            "fetchOr": "atomic_fetch_or_explicit",
            "fetchXor": "atomic_fetch_xor_explicit",
            "compareExchangeStrong": "atomic_compare_exchange_strong_explicit",
        }
        function = functions.get(method_name)
        if function is None:
            raise CodegenError(f"unsupported Atomic<T> method '{method_name}'")
        return IRCall(callee=function, args=[address, *args])

    def managed_capture_type(self, capture):
        """Return a direct managed capture type, excluding arrays/raw pointers."""
        capture_type = capture.type
        if capture_type is None or capture_type.is_array:
            return None
        return capture_type if self._values.is_managed(capture_type) else None

    def emit_capture_disposer(
        self,
        fn,
        env_name: str,
        spawn_id: int,
        provenance: CallableProvenance,
    ) -> str | None:
        """Emit one completion-safe owner for a captured lambda environment."""
        if not fn.captures:
            return None
        adapters: list[str] = []
        for capture in fn.captures:
            capture_type = self.managed_capture_type(capture)
            if capture_type is None:
                continue
            name = f"__btrc_spawn_capture_release_{spawn_id}_{capture.name}"
            self._session.module.function_defs.append(
                self._capture_release_adapter(
                    name,
                    env_name,
                    capture.name,
                    capture_type,
                    provenance,
                )
            )
            adapters.append(name)
        disposer_name = f"__btrc_spawn_env_dispose_{spawn_id}"
        self._session.module.function_defs.append(self._capture_disposer(disposer_name, env_name, adapters))
        return disposer_name

    def _capture_release_adapter(
        self,
        name: str,
        env_name: str,
        field_name: str,
        capture_type,
        provenance: CallableProvenance,
    ) -> IRFunctionDef:
        env = IRVar(name="__env")
        field = IRFieldAccess(
            obj=env,
            field=self._ownership.source_binding_c_name(field_name, provenance),
            arrow=True,
        )
        value = IRVar(name="__value")
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text="void*"), name="__raw")],
            body=IRBlock(
                stmts=[
                    IRVarDecl(
                        c_type=CType(text=f"{env_name}*"),
                        name=env.name,
                        init=IRCast(target_type=CType(text=f"{env_name}*"), expr=IRVar(name="__raw")),
                    ),
                    IRVarDecl(c_type=CType(text=self._types.render(capture_type)), name=value.name, init=field),
                    IRAssign(target=field, value=IRLiteral(text="NULL")),
                    IRExprStmt(expr=self._lifetime.release_value(value, capture_type)),
                ]
            ),
            is_static=True,
        )

    def _capture_disposer(self, name: str, env_name: str, adapters: list[str]) -> IRFunctionDef:
        env = IRVar(name="__env")
        has_error = IRVar(name="__has_error")
        first_error = IRVar(name="__first_error")
        error = IRVar(name="__error")
        body = [
            IRVarDecl(
                c_type=CType(text=f"{env_name}*"),
                name=env.name,
                init=IRCast(target_type=CType(text=f"{env_name}*"), expr=IRVar(name="__raw")),
            )
        ]
        if adapters:
            self._session.require_helper("__btrc_arc_guard_hook")
            self._session.require_helper("__btrc_raise_captured")
            self._session.require_helper("__btrc_throw")
            body.extend(
                [
                    IRVarDecl(c_type=CType(text="int"), name=has_error.name, init=IRLiteral(text="0")),
                    ConcurrencyLowerer._error_buffer(first_error.name),
                    ConcurrencyLowerer._error_buffer(error.name),
                ]
            )
            body.extend(
                ConcurrencyLowerer._guard_capture(adapter, env, has_error, first_error, error) for adapter in adapters
            )
        body.append(IRExprStmt(expr=IRCall(callee="free", args=[env])))
        if adapters:
            body.append(
                IRIf(
                    condition=has_error,
                    then_block=IRBlock(
                        stmts=[
                            IRExprStmt(
                                expr=IRCall(
                                    callee="__btrc_raise_captured",
                                    args=[IRFunctionRef(name="__btrc_throw"), first_error],
                                    helper_ref="__btrc_raise_captured",
                                )
                            )
                        ]
                    ),
                )
            )
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text="void*"), name="__raw")],
            body=IRBlock(stmts=body),
            is_static=True,
        )

    @staticmethod
    def _error_buffer(name: str) -> IRVarDecl:
        return IRVarDecl(
            c_type=CType(text="char"), name=name, array_size=IRLiteral(text="1024"), init=IRLiteral(text='""')
        )

    @staticmethod
    def _guard_capture(adapter, env, has_error, first_error, error):
        guarded = IRCall(
            callee="__btrc_arc_guard_hook",
            args=[IRFunctionRef(name=adapter), env, error, IRSizeof(operand=error)],
            helper_ref="__btrc_arc_guard_hook",
        )
        return IRIf(
            condition=IRBinOp(left=guarded, op="&&", right=IRUnaryOp(op="!", operand=has_error)),
            then_block=IRBlock(
                stmts=[
                    IRExprStmt(expr=IRCall(callee="memcpy", args=[first_error, error, IRSizeof(operand=first_error)])),
                    IRAssign(target=has_error, value=IRLiteral(text="1")),
                ]
            ),
        )

    def rewrite_thread_returns(self, block: IRBlock, return_type: TypeExpr | None) -> IRBlock:
        """Box every structured return; the runtime owns capture cleanup."""
        block.stmts = self._rewrite_statements(
            block.stmts,
            return_type,
        )
        return block

    def _rewrite_statements(self, statements, return_type):
        rewritten = []
        for statement in statements:
            if isinstance(statement, IRReturn):
                rewritten.extend(
                    self._rewrite_return(
                        statement,
                        return_type,
                    )
                )
                continue
            if isinstance(statement, IRIf):
                self._rewrite_block(
                    statement.then_block,
                    return_type,
                )
                self._rewrite_block(
                    statement.else_block,
                    return_type,
                )
            elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
                self._rewrite_block(
                    statement.body,
                    return_type,
                )
            elif isinstance(statement, IRSwitch):
                for case in statement.cases:
                    case.body = self._rewrite_statements(
                        case.body,
                        return_type,
                    )
            elif isinstance(statement, IRBlock):
                self._rewrite_block(
                    statement,
                    return_type,
                )
            rewritten.append(statement)
        return rewritten

    def _rewrite_block(self, block, return_type):
        if block is not None:
            self.rewrite_thread_returns(
                block,
                return_type,
            )

    def _rewrite_return(self, statement, return_type):
        value = statement.value or IRLiteral(text="NULL")
        boxed = self.box_thread_result(
            value,
            return_type,
        )
        return [IRReturn(value=boxed)]

    def box_thread_result(self, expr, result_type: TypeExpr | None):
        """Return one ``void*`` payload without changing the result's bits."""
        canonical = self._types.canonical_value_type(result_type)
        if canonical is None or self._types.is_scalar_void(canonical):
            return IRLiteral(text="NULL")
        if not self._requires_box(canonical):
            return IRCast(target_type=CType(text="void*"), expr=expr)
        return self._types.box_exact_value(expr, canonical, prefix="__btrc_thread")

    def unbox_thread_result(self, payload_call, result_type: TypeExpr | None):
        """Copy a boxed value before freeing its transport allocation."""
        canonical = self._types.canonical_value_type(result_type)
        if canonical is None or self._types.is_scalar_void(canonical):
            return payload_call
        if not self._requires_box(canonical):
            return IRCast(target_type=CType(text=self._types.render(result_type)), expr=payload_call)
        return self._types.unbox_exact_value(payload_call, canonical, prefix="__btrc_thread")

    def consume_thread_handle(self, obj):
        """Move an addressable handle out of its source slot exactly once."""
        return self._storage.consume_addressable_handle(obj, handle_c_type="__btrc_thread_t", prefix="__btrc_thread")

    def thread_result_disposal_args(self, result_type: TypeExpr | None):
        """Describe how scope cleanup must dispose an unclaimed thread result."""
        canonical = self._types.canonical_value_type(result_type)
        null = IRLiteral(text="NULL")
        zero = IRLiteral(text="0")
        if canonical is None or self._types.is_scalar_void(canonical):
            return [null, zero, null, null]
        if self._values.is_string(canonical):
            return [null, zero, self._disposal_callback("__btrc_thread_string_dispose"), null]
        if self._values.is_class(canonical):
            return [
                self._lifetime.arc_type_descriptor(canonical),
                IRSizeof(operand=CType(text="__btrc_arc_type")),
                self._disposal_callback("__btrc_thread_arc_dispose"),
                self._disposal_callback("__btrc_throw"),
            ]
        if self._requires_box(canonical):
            return [null, zero, self._disposal_callback("__btrc_thread_box_dispose"), null]
        return [null, zero, null, null]

    def _disposal_callback(self, name: str):
        self._session.require_helper(name)
        return IRFunctionRef(name=name)

    def _requires_box(self, type_expr: TypeExpr) -> bool:
        if type_expr.base == "__fn_ptr":
            return True
        return not self._type_identity.is_reference(
            type_expr, self._analyzed.class_table, self._analyzed.interface_table
        )

    def lower_spawn(
        self,
        node,
        provenance: CallableProvenance,
        *,
        lowered_function: IRExpr | None = None,
    ):
        """Lower a SpawnExpr to IR that spawns a thread.

        Returns __btrc_thread_t* — the opaque thread handle.
        """
        fn = node.fn
        self._session.require_helper("__btrc_thread_spawn")
        if not isinstance(fn, LambdaExpr):
            if lowered_function is None:
                raise CodegenError("spawn function operand was not materialized")
            spawn_type = self._session.type_of(node)
            result_type = spawn_type.generic_args[0] if spawn_type and spawn_type.generic_args else None
            return self._spawn_call(lowered_function, result_type)
        return_type = self.resolved_lambda_return_type(fn)
        ret_c_type = self._types.render(return_type) if return_type else "void"
        spawn_id = self._session.fresh_lambda_id()
        wrapper_name = f"__btrc_spawn_wrapper_{spawn_id}"
        env_name = f"__btrc_spawn_env_{spawn_id}"
        has_captures = bool(fn.captures)
        if has_captures:
            cap_fields = []
            for cap in fn.captures:
                c_type = self._types.render(cap.type) if cap.type else "int"
                cap_fields.append(
                    IRStructField(
                        c_type=CType(text=c_type),
                        name=self._ownership.source_binding_c_name(cap.name, provenance),
                        is_volatile=bool(cap.type and cap.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            cap.type, self._analyzed.typedef_table
                        ),
                    )
                )
            self._session.module.struct_forwards.append(IRStructForward(name=env_name))
            self._session.module.struct_defs.append(IRStructDef(name=env_name, fields=cap_fields))
        arg_disposer = self.emit_capture_disposer(
            fn,
            env_name,
            spawn_id,
            provenance,
        )
        self._session.pending_thread_spawns.append(
            ThreadSpawnPlan(
                function=fn,
                wrapper_name=wrapper_name,
                environment_name=env_name,
                return_c_type=ret_c_type,
                return_type=return_type,
                capture_abis=tuple((capture, provenance.return_abi_for_name(capture.name)) for capture in fn.captures),
            )
        )
        if has_captures:
            self._session.require_helper("__btrc_safe_realloc")
            se_var = f"__se{spawn_id}"
            stmts = [IRVarDecl(c_type=CType(text=f"{env_name}*"), name=se_var, init=None)]
            sequence = [
                IRBinOp(
                    left=IRVar(name=se_var),
                    op="=",
                    right=IRCast(
                        target_type=CType(text=f"{env_name}*"),
                        expr=IRCall(
                            callee="__btrc_safe_realloc",
                            args=[IRLiteral(text="NULL"), IRSizeof(operand=CType(text=env_name))],
                            helper_ref="__btrc_safe_realloc",
                        ),
                    ),
                )
            ]
            for cap in fn.captures:
                sequence.append(
                    IRBinOp(
                        left=IRFieldAccess(
                            obj=IRVar(name=se_var),
                            field=self._ownership.source_binding_c_name(cap.name, provenance),
                            arrow=True,
                        ),
                        op="=",
                        right=IRVar(name=self._ownership.source_binding_c_name(cap.name, provenance)),
                    )
                )
                capture_type = self.managed_capture_type(cap)
                if capture_type is not None:
                    sequence.append(
                        self._lifetime.retain_value(
                            IRVar(name=self._ownership.source_binding_c_name(cap.name, provenance)), capture_type
                        )
                    )
            spawn_call = self._spawn_call(
                IRFunctionRef(name=wrapper_name),
                return_type,
                IRCast(target_type=CType(text="void*"), expr=IRVar(name=se_var)),
                IRFunctionRef(name=arg_disposer),
            )
            sequence.append(spawn_call)
            return IRStmtExpr(stmts=stmts, result=IRCommaExpr(expressions=sequence))
        else:
            return self._spawn_call(IRFunctionRef(name=wrapper_name), return_type)

    def _spawn_call(
        self, fn_expr: IRExpr, result_type, capture_arg: IRExpr | None = None, arg_disposer: IRExpr | None = None
    ) -> IRCall:
        """Build an ordinary helper call for the pthread entry ABI."""
        return IRCall(
            callee="__btrc_thread_spawn",
            args=[
                IRCast(target_type=CType(text="void*(*)(void*)"), expr=fn_expr),
                capture_arg if capture_arg is not None else IRLiteral(text="NULL"),
                arg_disposer if arg_disposer is not None else IRLiteral(text="NULL"),
                *self.thread_result_disposal_args(result_type),
            ],
            helper_ref="__btrc_thread_spawn",
        )

    def plan_spawn_wrapper_body(
        self,
        plan: ThreadSpawnPlan,
        provenance: CallableProvenance,
    ) -> ThreadWrapperBodyPlan:
        """Describe wrapper source and bindings without traversing statements."""
        fn = plan.function
        has_captures = bool(fn.captures)
        body_stmts = []
        if has_captures:
            body_stmts.append(
                IRVarDecl(
                    c_type=CType(text=f"{plan.environment_name}*"),
                    name="__env",
                    init=IRCast(
                        target_type=CType(text=f"{plan.environment_name}*"),
                        expr=IRVar(name="__arg"),
                    ),
                )
            )
            for cap in fn.captures:
                c_type = self._types.render(cap.type) if cap.type else "int"
                body_stmts.append(
                    IRVarDecl(
                        c_type=CType(text=c_type),
                        name=self._ownership.source_binding_c_name(cap.name, provenance),
                        is_volatile=bool(cap.type and cap.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            cap.type, self._analyzed.typedef_table
                        ),
                        init=IRFieldAccess(
                            obj=IRVar(name="__env"),
                            field=self._ownership.source_binding_c_name(cap.name, provenance),
                            arrow=True,
                        ),
                    )
                )
        local_bindings = [parameter.name for parameter in fn.params]
        local_bindings.extend(capture.name for capture in fn.captures)
        if isinstance(fn.body, LambdaBlock) and fn.body.body:
            body = fn.body.body
        elif isinstance(fn.body, LambdaExprBody) and fn.body.expression:
            body = Block(
                statements=[
                    ReturnStmt(value=fn.body.expression, line=fn.body.expression.line, col=fn.body.expression.col)
                ]
            )
        else:
            body = None
        return ThreadWrapperBodyPlan(
            source=body,
            prelude=tuple(body_stmts),
            local_bindings=tuple(local_bindings),
            callable_abis=plan.capture_abis,
        )

    def materialize_spawn_wrapper(
        self,
        plan: ThreadSpawnPlan,
        body_plan: ThreadWrapperBodyPlan,
        lowered_body: IRBlock | None,
    ) -> None:
        """Install one wrapper from an explicitly lowered ordinary block."""
        body = list(body_plan.prelude)
        if lowered_body is not None:
            body.extend(
                self.rewrite_thread_returns(
                    lowered_body,
                    plan.return_type,
                ).stmts
            )
        if not body or not isinstance(body[-1], IRReturn):
            body.append(IRReturn(value=IRLiteral(text="NULL")))
        declaration = IRFunctionDecl(
            name=plan.wrapper_name,
            return_type=CType(text="void*"),
            params=[IRParam(c_type=CType(text="void*"), name="__arg")],
            is_static=True,
        )
        if declaration not in self._session.module.function_decls:
            self._session.module.function_decls.append(declaration)
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=plan.wrapper_name,
                return_type=CType(text="void*"),
                params=[IRParam(c_type=CType(text="void*"), name="__arg")],
                body=IRBlock(stmts=body),
                is_static=True,
            )
        )

    def resolved_lambda_return_type(self, node: LambdaExpr):
        """Return the analyzer-resolved result type for a spawn lambda."""
        if node.return_type:
            return node.return_type
        function_type = self._session.type_of(node)
        if function_type and function_type.base == "__fn_ptr" and function_type.generic_args:
            return function_type.generic_args[0]
        if isinstance(node.body, LambdaExprBody) and node.body.expression:
            return self._session.type_of(node.body.expression)
        return None
