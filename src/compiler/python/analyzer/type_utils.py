"""Type utilities: method return type lookup, compatibility checking."""

from __future__ import annotations

from ..ast_nodes import TypeExpr
from ..string_methods import STRING_METHODS


class TypeUtilsMixin:

    def _string_method_return_type(self, method_name: str) -> TypeExpr | None:
        """Return the type of a string method call (shared spec table)."""
        spec = STRING_METHODS.get(method_name)
        if spec is None:
            return None
        if spec.return_type == "string*":
            return TypeExpr(base="string", pointer_depth=1)
        return TypeExpr(base=spec.return_type)

    def _format_type(self, t) -> str:
        """Format a TypeExpr for error messages."""
        result = t.base
        if t.generic_args:
            args = ", ".join(self._format_type(a) for a in t.generic_args)
            result += f"<{args}>"
        result += "*" * t.pointer_depth
        return result

    def _types_compatible(self, target, source) -> bool:
        """Check if source type can be assigned to target type."""
        if target.base == source.base:
            # Check generic arg compatibility
            t_args = getattr(target, 'generic_args', None) or []
            s_args = getattr(source, 'generic_args', None) or []
            if t_args and s_args and len(t_args) == len(s_args):
                for t_arg, s_arg in zip(t_args, s_args):
                    if not self._types_compatible(t_arg, s_arg):
                        return False
            return True
        numeric = {"int", "float", "double", "char", "long", "short", "byte", "uint"}
        if target.base in numeric and source.base in numeric:
            return True
        if target.base == "string" and source.base == "char" and source.pointer_depth >= 1:
            return True
        if source.base == "string" and target.base == "char" and target.pointer_depth >= 1:
            return True
        if target.base == "string" and source.base in self.class_table:
            method = self.class_table[source.base].methods.get("toString")
            return bool(method and not method.params
                        and method.return_type
                        and method.return_type.base == "string")
        if source.base == "null" or (source.base == "void" and source.pointer_depth > 0):
            return target.pointer_depth > 0 or target.base == "string"
        if target.base in self.class_table and source.base in self.class_table:
            return self._is_subclass(source.base, target.base)
        all_known = numeric | {"string", "bool", "void"}
        # A raw pointer to a builtin (string*, int*, ...) is never a generic
        # collection (List<string>, Map<K,V>, ...) and vice versa: rejecting
        # the pair turns e.g. `List<string> xs = s.split(",")` (split returns
        # string*) into a clear analyzer error instead of broken C. `void` is
        # excluded (void* C interop is resolved above and stays permissive),
        # and unknown<->unknown pairs stay compatible for extern C types.
        def _builtin_ptr(t) -> bool:
            return (t.base in all_known and t.base != "void"
                    and t.pointer_depth > 0)
        if (_builtin_ptr(source) and target.generic_args) or \
                (_builtin_ptr(target) and source.generic_args):
            return False
        return not (target.base in all_known and source.base in all_known)

    def _is_subclass(self, child: str, parent: str) -> bool:
        """Check if child class extends parent (directly or transitively)."""
        if child == parent:
            return True
        info = self.class_table.get(child)
        if not info:
            return False
        if parent in self.interface_table:
            cur = info
            visited = set()
            while cur and cur.name not in visited:
                visited.add(cur.name)
                if parent in cur.interfaces:
                    return True
                cur = self.class_table.get(cur.parent) if cur.parent else None
            return False
        visited = set()
        while info and info.parent and info.parent not in visited:
            visited.add(info.parent)
            if info.parent == parent:
                return True
            info = self.class_table.get(info.parent)
        return False
