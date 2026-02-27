"""User-defined generic class monomorphization: struct + methods."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type
from .core import _resolve_type
from .user_emitter import _UserGenericEmitter

if TYPE_CHECKING:
    from ..generator import IRGenerator

# Runtime helpers to register when referenced in emitted code
_KNOWN_HELPERS = {"__btrc_safe_realloc", "__btrc_safe_calloc"}


def _is_type_incompatible(body_text: str, first_arg_c: str) -> bool:
    """Check if emitted method body uses ops incompatible with the type.

    C doesn't have templates — all static functions must type-check even if
    unused.  This skips methods like sum() for pointer types (pointer + pointer
    is invalid) and join() for non-string types (strlen on non-string).
    """
    is_pointer = first_arg_c.endswith("*")
    if not is_pointer:
        # strlen/memcpy on non-string element data (join/joinToString)
        if "strlen(self->" in body_text or "memcpy(" in body_text:
            return True
    if is_pointer:
        # ptr + ptr is invalid C (sum-like methods use T + T arithmetic)
        if "+ self->data[" in body_text:
            return True
        # strlen/strncmp/memcpy on non-string pointer types
        if first_arg_c != "char*":
            if "strlen(self->" in body_text or "memcpy(" in body_text:
                return True
    return False


def _register_transitive_generic_deps(gen: IRGenerator, cls_info,
                                       type_map: dict[str, TypeExpr]):
    """Scan resolved field types for generic class references and register them.

    When List<string> has a field of type ListNode<T>, resolving T→string
    gives ListNode<string>. This must be registered as a new generic instance
    so the while-changed loop in core.py emits it.
    """
    for _name, fd in cls_info.fields.items():
        resolved = _resolve_type(fd.type, type_map)
        _register_if_generic(gen, resolved)
    # Also scan method return types and parameter types
    for method in cls_info.methods.values():
        if method.return_type:
            resolved = _resolve_type(method.return_type, type_map)
            _register_if_generic(gen, resolved)
        for p in method.params:
            if p.type:
                resolved = _resolve_type(p.type, type_map)
                _register_if_generic(gen, resolved)


def _register_if_generic(gen: IRGenerator, t: TypeExpr):
    """Register a resolved type as a generic instance if it's a generic class."""
    if not t or not t.generic_args:
        return
    cls = gen.analyzed.class_table.get(t.base)
    if cls and cls.generic_params:
        instances = gen.analyzed.generic_instances.setdefault(t.base, [])
        args_tuple = tuple(t.generic_args)
        if args_tuple not in instances:
            instances.append(args_tuple)


def _emit_user_generic_instance(gen: IRGenerator, base_name: str,
                                 args: list[TypeExpr],
                                 seen: set | None = None):
    """Emit a user-defined generic class instance (struct + methods).

    The `seen` set tracks already-emitted mangled names. When field types
    reference other generic classes (transitive deps), those are emitted
    first so their forward declarations and method definitions appear
    before the current type's method bodies.
    """
    cls_info = gen.analyzed.class_table.get(base_name)
    if not cls_info:
        return
    mangled = mangle_generic_type(base_name, args)

    # Build type parameter mapping
    type_map = {}
    for i, gp in enumerate(cls_info.generic_params):
        if i < len(args):
            type_map[gp] = args[i]

    # Register transitive generic dependencies (e.g. ListNode<string> from List<string>)
    _register_transitive_generic_deps(gen, cls_info, type_map)

    # Recursively emit transitive field-type dependencies FIRST
    if seen is not None:
        for _name, fd in cls_info.fields.items():
            resolved = _resolve_type(fd.type, type_map)
            if resolved.generic_args and resolved.base in gen.analyzed.class_table:
                dep_cls = gen.analyzed.class_table[resolved.base]
                if dep_cls.generic_params:
                    dep_mangled = mangle_generic_type(resolved.base,
                                                      list(resolved.generic_args))
                    if dep_mangled not in seen:
                        seen.add(dep_mangled)
                        _emit_user_generic_instance(
                            gen, resolved.base, list(resolved.generic_args), seen)

    # Emit forward typedef if not already present (for transitive deps
    # discovered after the initial forward_decls pass in generator.py)
    fwd = f"typedef struct {mangled} {mangled};"
    if fwd not in gen.module.forward_decls:
        gen.module.forward_decls.append(fwd)

    # Emit struct with resolved types
    fields = []
    for name, fd in cls_info.fields.items():
        resolved = _resolve_type(fd.type, type_map)
        fields.append(IRStructField(c_type=CType(text=type_to_c(resolved)), name=name))
    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=fields))

    # Emit constructor, destructor, and methods
    _emit_user_generic_methods(gen, base_name, mangled, args, type_map, cls_info)


def _emit_user_generic_methods(gen: IRGenerator, base_name: str, mangled: str,
                                args: list[TypeExpr],
                                type_map: dict[str, TypeExpr],
                                cls_info):
    """Emit constructor + methods for a user-defined generic class instance."""
    from ..types import type_to_c as ttc

    first_arg_c = ttc(args[0]) if args else "int"
    emitter = _UserGenericEmitter(type_map, mangled, ttc, gen=gen)

    ctor = cls_info.constructor
    ctor_params = []
    if ctor:
        for p in ctor.params:
            ctor_params.append(f"{emitter.resolve_c(p.type)} {p.name}")

    # Constructor: init + new
    init_params = [f"{mangled}* self"] + ctor_params
    init_body = ""
    if ctor and ctor.body:
        init_body = emitter.emit_stmts(ctor.body.statements)
    if not init_body.strip():
        init_body = "    (void)self;\n"

    # Collect forward declarations for all methods to avoid order issues
    fwd_decls = []
    fwd_decls.append(f"static void {mangled}_init({', '.join(init_params)});")
    fwd_decls.append(
        f"static {mangled}* {mangled}_new("
        f"{', '.join(ctor_params) if ctor_params else 'void'});")
    fwd_decls.append(f"static void {mangled}_destroy({mangled}* self);")
    for mname, method in cls_info.methods.items():
        if mname == "__del__" or mname == base_name:
            continue
        ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
        m_params = [f"{mangled}* self"]
        for p in method.params:
            m_params.append(f"{emitter.resolve_c(p.type)} {p.name}")
        fwd_decls.append(
            f"static {ret_c} {mangled}_{mname}({', '.join(m_params)});")

    methods = "\n".join(fwd_decls) + "\n"
    methods += f"""
static void {mangled}_init({', '.join(init_params)}) {{
{init_body}}}
static {mangled}* {mangled}_new({', '.join(ctor_params) if ctor_params else 'void'}) {{
    {mangled}* self = ({mangled}*)malloc(sizeof({mangled}));
    memset(self, 0, sizeof({mangled}));
    {mangled}_init(self{(''.join(', ' + p.name for p in ctor.params)) if ctor else ''});
    return self;
}}
static void {mangled}_destroy({mangled}* self) {{ free(self); }}
"""
    # Emit methods — two-phase: emit all, then filter out incompatible ones
    emitted = {}
    skipped = set()
    for mname, method in cls_info.methods.items():
        if mname == "__del__" or mname == base_name:
            continue
        emitter.reset_var_types(method.params)
        ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
        m_params = [f"{mangled}* self"]
        for p in method.params:
            m_params.append(f"{emitter.resolve_c(p.type)} {p.name}")
        m_body = emitter.emit_stmts(method.body.statements) if method.body else ""
        if not m_body.strip():
            m_body = "    (void)self;\n"
        if _is_type_incompatible(m_body, first_arg_c):
            skipped.add(mname)
            continue
        emitted[mname] = (
            f"static {ret_c} {mangled}_{mname}"
            f"({', '.join(m_params)}) {{\n{m_body}}}\n"
        )

    # Second pass: skip methods that call skipped methods
    for mname, text in list(emitted.items()):
        for sk in skipped:
            if f"{mangled}_{sk}(" in text:
                del emitted[mname]
                break

    for text in emitted.values():
        methods += text

    methods_text = methods.strip()

    # Register any runtime helpers referenced in the emitted code
    for h in _KNOWN_HELPERS:
        if h in methods_text:
            gen.use_helper(h)

    gen.module.raw_sections.append(methods_text)
