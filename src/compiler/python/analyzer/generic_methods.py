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
        if not self._all_concrete(method_args, method.generic_params):
            return

        class_args = tuple(obj_type.generic_args) if obj_type.generic_args else ()
        owner = f"{obj_type.base}.{method.name}"
        if not self._validate_generic_arguments(owner, method_args, expr.line, expr.col):
            return
        full_subs = {**class_subs, **method_subs}
        signature_types = [method.return_type, *(param.type for param in method.params)]
        if not self._validate_substitution_shapes(owner, signature_types, full_subs, expr.line, expr.col):
            return

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

        names = self._arg_names(expr.args, expr.arg_names)
        for param_index, arg_index in self._bound_arguments(method.params, names):
            param = method.params[param_index]
            declared = self._substitute_type(param.type, class_subs)
            actual = self._arg_type_for_inference(expr.args[arg_index])
            if declared is None or actual is None:
                continue
            if not self._unify_type_param(declared, actual, type_params, subs):
                return None

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
        if isinstance(arg, Identifier) and arg.name in self.declarations.function_table:
            func = self.declarations.function_table[arg.name]
            return self.declaration_policy.callables.function_value_type(func)
        if isinstance(arg, LambdaExpr):
            return self._infer_type(arg)
        return self._infer_type(arg)

    def _unify_type_param(self, declared, actual, type_params, subs) -> bool:
        """Structurally unify ``declared`` (may mention type params) with ``actual``.

        Records bindings for any name in ``type_params`` into ``subs``. Pointer
        depth and extra structure are ignored beyond what's needed to bind the
        type parameters.
        """
        if declared is None or actual is None:
            return True
        if declared.base in type_params and not declared.generic_args:
            binding = self._strip_one_pointer(actual, declared)
            if binding is None:
                return False
            existing = subs.get(declared.base)
            if existing is not None:
                return self._types_equal(existing, binding)
            subs[declared.base] = binding
            return True

        if declared.generic_args or actual.generic_args:
            if (
                declared.base != actual.base
                or declared.pointer_depth != actual.pointer_depth
                or declared.is_array != actual.is_array
                or len(declared.generic_args) != len(actual.generic_args)
            ):
                return False
            return all(
                self._unify_type_param(d, a, type_params, subs)
                for d, a in zip(declared.generic_args, actual.generic_args)
            )
        return True

    def _strip_one_pointer(self, actual, declared) -> TypeExpr | None:
        """Adjust ``actual`` for the pointer depth the declared param adds.

        When the declared parameter is ``U*`` and the actual is ``int*``, the
        bound ``U`` is ``int``. Pointer depths beyond the type-parameter slot are
        subtracted. Plain (non-pointer) parameters bind to ``actual`` as-is.
        """
        binding = actual
        if getattr(declared, "is_array", False):
            if not getattr(binding, "is_array", False):
                return None
            from ..type_composition import strip_outer_storage

            binding = strip_outer_storage(binding, array=True)
        extra = getattr(declared, "pointer_depth", 0)
        if extra:
            if getattr(binding, "pointer_depth", 0) < extra:
                return None
            from ..type_composition import strip_outer_storage

            for _ in range(extra):
                if binding.pointer_depth <= 0:
                    return None
                binding = strip_outer_storage(binding)
        return binding

    def _all_concrete(self, args, unresolved=()) -> bool:
        """True if every TypeExpr in ``args`` is fully concrete (no type params).

        Only parameters declared by the generic method are unresolved. A real
        user type named ``T`` is otherwise a perfectly concrete type.
        """
        unresolved = set(unresolved)
        return all(self._type_is_concrete(a, unresolved) for a in args)

    def _type_is_concrete(self, t, unresolved) -> bool:
        if t is None:
            return False
        if t.base in unresolved:
            return False
        return all(self._type_is_concrete(a, unresolved) for a in (t.generic_args or []))
