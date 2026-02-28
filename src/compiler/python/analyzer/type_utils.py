"""Type utilities: method return type tables, compatibility checking."""

from __future__ import annotations

from ..ast_nodes import TypeExpr


class TypeUtilsMixin:

    def _string_method_return_type(self, method_name: str) -> TypeExpr | None:
        """Return the type of a string method call."""
        _INT = TypeExpr(base="int")
        _BOOL = TypeExpr(base="bool")
        _STRING = TypeExpr(base="string")
        _CHAR = TypeExpr(base="char")
        _FLOAT = TypeExpr(base="float")
        string_methods = {
            "len": _INT, "byteLen": _INT, "charLen": _INT,
            "contains": _BOOL, "startsWith": _BOOL, "endsWith": _BOOL,
            "equals": _BOOL, "indexOf": _INT, "lastIndexOf": _INT,
            "find": _INT, "count": _INT,
            "charAt": _CHAR,
            "substring": _STRING, "trim": _STRING, "lstrip": _STRING,
            "rstrip": _STRING, "toUpper": _STRING, "toLower": _STRING,
            "replace": _STRING, "repeat": _STRING,
            "capitalize": _STRING, "title": _STRING, "swapCase": _STRING,
            "padLeft": _STRING, "padRight": _STRING, "center": _STRING,
            "zfill": _STRING,
            "isBlank": _BOOL, "isAlnum": _BOOL,
            "isDigitStr": _BOOL, "isAlphaStr": _BOOL,
            "isUpper": _BOOL, "isLower": _BOOL,
            "toInt": _INT, "toFloat": _FLOAT,
            "toDouble": TypeExpr(base="double"), "toLong": TypeExpr(base="long"),
            "toBool": _BOOL,
            "reverse": _STRING, "isEmpty": _BOOL,
            "removePrefix": _STRING, "removeSuffix": _STRING,
            "split": TypeExpr(base="string", pointer_depth=1),
        }
        return string_methods.get(method_name)

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
        numeric = {"int", "float", "double", "char"}
        if target.base in numeric and source.base in numeric:
            return True
        if target.base == "string" and source.base == "char" and source.pointer_depth >= 1:
            return True
        if source.base == "string" and target.base == "char" and target.pointer_depth >= 1:
            return True
        if source.base == "null" or (source.base == "void" and source.pointer_depth > 0):
            return target.pointer_depth > 0 or target.base == "string"
        if target.base in self.class_table and source.base in self.class_table:
            return self._is_subclass(source.base, target.base)
        all_known = numeric | {"string", "bool", "void"}
        if target.base in all_known and source.base in all_known:
            return False
        return True

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
