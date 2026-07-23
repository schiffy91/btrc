"""Method emission for user-defined generic class instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ....source_runtime_symbols import SOURCE_RUNTIME_HELPERS
from ...cycle_boundaries import (
    PUBLIC_COLLECTION_BASES,
    install_function_cycle_boundary,
)
from ...nodes import (
    CType,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRParam,
    IRVar,
)
from ...topology_boundaries import install_collection_topology_boundary
from ..cycle_metadata import generic_instance_needs_visitor
from ..errors import TypedOperatorError
from ..parameters import lower_source_param
from ..types import CTypeRenderer
from .user_emitter import _UserGenericEmitter
from .user_ir_queries import (
    called_callees,
    called_generic_methods,
    is_type_incompatible,
    referenced_helpers,
)
from .user_lifecycle import emit_generic_lifecycle
from .user_properties import emit_generic_properties

if TYPE_CHECKING:
    from ..lowerer import IRLowerer


def _emit_user_generic_methods(
    gen: IRLowerer,
    base_name: str,
    mangled: str,
    args: list[TypeExpr],
    type_map: dict[str, TypeExpr],
    cls_info,
    type_renderer: CTypeRenderer,
):
    """Emit constructor + methods for a user-defined generic class instance."""
    if args:
        from ..type_resolution import canonical_type

        first_arg = canonical_type(args[0], gen.analyzed.typedef_table)
        first_arg_c = type_renderer.render(first_arg)
    else:
        first_arg_c = "int"
    emitter = _UserGenericEmitter(
        type_map,
        mangled,
        type_renderer,
        gen=gen,
        cls_info=cls_info,
    )
    function_decls, lifecycle_functions = emit_generic_lifecycle(
        gen, base_name, mangled, args, type_map, cls_info, emitter
    )

    property_functions = emit_generic_properties(gen, mangled, type_map, cls_info, emitter)

    # --- Emit methods ---
    # Two-phase: emit all, then filter out incompatible ones
    emitted = {}
    skipped = set()
    skip_reasons = {}
    managed_collection = base_name in PUBLIC_COLLECTION_BASES and generic_instance_needs_visitor(gen, base_name, args)
    for mname, method in cls_info.methods.items():
        if mname == "__del__" or method.is_constructor:
            continue
        # Generic methods are emitted per call site (see generic_methods.py).
        if getattr(method, "generic_params", None):
            continue
        public_collection_method = base_name in PUBLIC_COLLECTION_BASES and method.access == "public"
        emitter.reset_var_types(
            method.params,
            method.return_type,
            batch_explicit_releases=public_collection_method,
        )
        ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
        m_params_ir = [IRParam(c_type=CType(text=f"{mangled}*"), name="self")]
        for p in method.params:
            m_params_ir.append(
                lower_source_param(
                    p,
                    emitter.resolve_c,
                    emitter._gen.analyzed,
                    resolved_type=emitter._resolve(p.type),
                )
            )
        try:
            body_stmts = emitter.emit_stmts(method.body.statements) if method.body else []
        except TypedOperatorError as error:
            skipped.add(mname)
            skip_reasons[mname] = str(error)
            continue
        if not body_stmts:
            body_stmts = [IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self")))]

        func_def = IRFunctionDef(
            name=f"{mangled}_{mname}",
            return_type=CType(text=ret_c),
            params=m_params_ir,
            body=IRBlock(stmts=body_stmts),
            is_static=True,
        )
        if managed_collection:
            install_collection_topology_boundary(gen, func_def)
        if public_collection_method and install_function_cycle_boundary(func_def):
            gen.helpers.use("__btrc_flush_cycles")
        if is_type_incompatible(func_def, first_arg_c):
            skipped.add(mname)
            continue
        emitted[mname] = func_def

    _drop_methods_calling_skipped(emitted, skipped, mangled)
    called = called_generic_methods(
        gen.analyzed.program,
        gen.analyzed.node_types,
        base_name,
        args,
    )
    unavailable = called & skipped
    if unavailable:
        name = sorted(unavailable)[0]
        reason = skip_reasons.get(name, "it depends on another unavailable specialization")
        raise TypedOperatorError(f"cannot instantiate generic method '{base_name}.{name}': {reason}")

    for function in emitted.values():
        function_decls.append(
            IRFunctionDecl(
                name=function.name,
                return_type=function.return_type,
                params=list(function.params),
                is_static=True,
            )
        )

    gen.module.function_decls.extend(function_decls)

    for func_def in emitted.values():
        gen.module.function_defs.append(func_def)

    # Register any runtime helpers referenced in the emitted code
    all_stmts = []
    for func_def in lifecycle_functions + property_functions + list(emitted.values()):
        if func_def.body:
            all_stmts.extend(func_def.body.stmts)
    for helper in referenced_helpers(all_stmts, SOURCE_RUNTIME_HELPERS):
        gen.helpers.use(helper)


def _drop_methods_calling_skipped(
    emitted: dict[str, IRFunctionDef],
    skipped: set[str],
    mangled: str,
) -> None:
    """Transitively drop methods whose structured bodies call skipped ones."""
    while skipped:
        skipped_callees = {f"{mangled}_{name}" for name in skipped}
        newly_skipped = {name for name, function in emitted.items() if called_callees(function) & skipped_callees}
        if not newly_skipped:
            return
        for name in newly_skipped:
            del emitted[name]
        skipped.update(newly_skipped)
