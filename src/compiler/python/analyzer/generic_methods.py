"""Generic-method instance collection and method-level type inference.

A *generic method* introduces its own type parameters (``MethodDecl.generic_params``)
on top of any class-level generics, e.g. ``Vector<U> mapTo<U>(__fn_ptr<U, T> fn)``.
Each call site picks a concrete ``U`` (inferred from the arguments), and the IR
generator emits one monomorphized C function per (receiver instance x method
type-args) combination.

This mixin records those (class_args, method_args) combinations into
``self.generic_method_instances`` during analysis, and registers any concrete
generic types that the substituted return/parameter types reference (e.g.
``Vector<string>`` from ``mapTo<string>``) so they are monomorphized too.
"""

from __future__ import annotations

from ..ast_nodes import Identifier, LambdaExpr, TypeExpr


class GenericMethodsMixin:

    def _collect_generic_method_instance(self, expr, cls, method, obj_type):
        """Record a monomorphization target for a generic-method call site.

        ``expr`` is the CallExpr, ``cls``/``method`` the resolved receiver class
        and method, ``obj_type`` the receiver's (concrete) TypeExpr. Inference of
        each method type parameter is best-effort: if any cannot be resolved to a
        concrete type, the call site is skipped (no instance recorded), which
        keeps existing non-generic methods and unresolved cases harmless.
        """
        # Receiver class substitutions, e.g. {T: int} for Vector<int>.
        class_subs = {}
        if cls.generic_params and obj_type.generic_args:
            class_subs = dict(zip(cls.generic_params, obj_type.generic_args))

        # Infer each method type parameter from the arguments.
        method_subs = self._infer_method_type_args(expr, method, class_subs)
        if method_subs is None:
            return  # incomplete inference — leave it un-monomorphized

        method_args = tuple(method_subs[gp] for gp in method.generic_params)
        if not self._all_concrete(method_args):
            return

        class_args = tuple(obj_type.generic_args) if obj_type.generic_args else ()

        key = (obj_type.base, method.name)
        bucket = self.generic_method_instances.setdefault(key, [])
        entry = (class_args, method_args)
        if not self._method_instance_seen(bucket, entry):
            bucket.append(entry)

        # Record the per-call-site method args so IR-gen can mangle the call to
        # the monomorphized instance without re-running inference.
        self.generic_method_call_args[id(expr)] = method_args

        # Register concrete generic types that the substituted signature
        # references (e.g. Vector<string> from mapTo's return type) so the
        # class-instance monomorphization loop emits them.
        full_subs = {**class_subs, **method_subs}
        for t in [method.return_type] + [p.type for p in method.params]:
            resolved = self._substitute_type(t, full_subs)
            if resolved and resolved.generic_args:
                self._collect_generic_instances(resolved)

    def _method_instance_seen(self, bucket, entry) -> bool:
        class_args, method_args = entry
        target = (
            tuple(self._normalize_type_key(a) for a in class_args),
            tuple(self._normalize_type_key(a) for a in method_args),
        )
        for ex_class, ex_method in bucket:
            existing = (
                tuple(self._normalize_type_key(a) for a in ex_class),
                tuple(self._normalize_type_key(a) for a in ex_method),
            )
            if existing == target:
                return True
        return False

    def _infer_method_type_args(self, expr, method, class_subs):
        """Infer concrete bindings for each method type parameter.

        Returns a dict {param_name: TypeExpr} when every parameter is resolved,
        otherwise None. Inference unifies each method parameter's declared type
        (after class-level substitution) against the corresponding argument's
        inferred type.
        """
        type_params = set(method.generic_params)
        subs: dict[str, TypeExpr] = {}

        for i, param in enumerate(method.params):
            if i >= len(expr.args):
                break
            declared = self._substitute_type(param.type, class_subs)
            actual = self._arg_type_for_inference(expr.args[i])
            if declared is None or actual is None:
                continue
            self._unify_type_param(declared, actual, type_params, subs)

        for gp in method.generic_params:
            if gp not in subs:
                return None
        return subs

    def _arg_type_for_inference(self, arg) -> TypeExpr | None:
        """Inferred TypeExpr of a call argument, normalized for unification.

        Lambdas infer to ``__fn_ptr<ret, params...>`` already. A bare function
        reference (Identifier naming a top-level function) is reconstructed into
        the same ``__fn_ptr`` shape so it unifies the same way.
        """
        if isinstance(arg, Identifier) and arg.name in self.function_table:
            func = self.function_table[arg.name]
            generic_args = [func.return_type] + [p.type for p in func.params]
            return TypeExpr(base="__fn_ptr", generic_args=generic_args)
        if isinstance(arg, LambdaExpr):
            return self._infer_type(arg)
        return self._infer_type(arg)

    def _unify_type_param(self, declared, actual, type_params, subs):
        """Structurally unify ``declared`` (may mention type params) with ``actual``.

        Records bindings for any name in ``type_params`` into ``subs``. Pointer
        depth and extra structure are ignored beyond what's needed to bind the
        type parameters.
        """
        if declared is None or actual is None:
            return
        if declared.base in type_params and not declared.generic_args:
            if declared.base not in subs:
                # Bind to the actual type with the type-parameter's pointer depth
                # stripped (declared `T` vs `T*` is handled structurally below).
                subs[declared.base] = self._strip_one_pointer(actual, declared)
            return
        # Recurse into matching generic argument lists positionally
        if declared.generic_args and actual.generic_args:
            for d, a in zip(declared.generic_args, actual.generic_args):
                self._unify_type_param(d, a, type_params, subs)

    def _strip_one_pointer(self, actual, declared) -> TypeExpr:
        """Adjust ``actual`` for the pointer depth the declared param adds.

        When the declared parameter is ``U*`` and the actual is ``int*``, the
        bound ``U`` is ``int``. Pointer depths beyond the type-parameter slot are
        subtracted. Plain (non-pointer) parameters bind to ``actual`` as-is.
        """
        extra = getattr(declared, "pointer_depth", 0)
        if extra and getattr(actual, "pointer_depth", 0) >= extra:
            return TypeExpr(
                base=actual.base,
                generic_args=actual.generic_args,
                pointer_depth=actual.pointer_depth - extra,
                is_array=getattr(actual, "is_array", False),
                is_nullable=getattr(actual, "is_nullable", False),
            )
        return actual

    def _all_concrete(self, args) -> bool:
        """True if every TypeExpr in ``args`` is fully concrete (no type params).

        A single uppercase-letter base (T, U, K, V, ...) is treated as an
        unresolved type parameter, mirroring ir.gen.types.is_concrete_type.
        """
        return all(self._type_is_concrete(a) for a in args)

    def _type_is_concrete(self, t) -> bool:
        if t is None:
            return False
        base = t.base
        if len(base) == 1 and base.isupper():
            return False
        return all(self._type_is_concrete(a) for a in (t.generic_args or []))
