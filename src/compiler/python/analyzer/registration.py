"""Pass 1: Register declarations and validate inheritance/interfaces."""

from ..ast_nodes import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
)
from .core import ClassInfo, InterfaceInfo


class RegistrationMixin:

    def _register_declarations(self, program):
        # Deep left-leaning expression chains (a+a+...+a) recurse one Python
        # frame per term in _analyze_expr/_infer_type. The default limit
        # (1000) rejects real programs; CPython 3.12+ heap-allocates pure
        # Python frames, so a higher limit is safe here.
        import sys
        if sys.getrecursionlimit() < 40000:
            sys.setrecursionlimit(40000)
        for decl in self._decls_with_file(program):
            if isinstance(decl, InterfaceDecl):
                self._register_interface(decl)
        # Struct/enum/typedef names, available before pass 2 runs (cast
        # validation needs them regardless of declaration order).
        self.declared_type_names: set[str] = set()
        for decl in self._decls_with_file(program):
            if isinstance(decl, ClassDecl):
                self._register_class(decl)
            elif isinstance(decl, FunctionDecl):
                self._register_function(decl)
            elif isinstance(decl, (StructDecl, EnumDecl, RichEnumDecl)):
                self.declared_type_names.add(decl.name)
            elif isinstance(decl, TypedefDecl):
                self.declared_type_names.add(decl.alias)
        self._resolve_class_parents()

    def _register_interface(self, decl):
        if decl.name in self.interface_table:
            self._error(f"Duplicate interface name '{decl.name}'", decl.line, decl.col)
        info = InterfaceInfo(name=decl.name, parent=decl.parent,
                             generic_params=decl.generic_params)
        for method in decl.methods:
            info.methods[method.name] = method
        self.interface_table[decl.name] = info

    def _resolve_interface_parents(self, program):
        """Second pass: inherit parent interface methods after all interfaces are registered."""
        for decl in self._decls_with_file(program):
            if not isinstance(decl, InterfaceDecl) or not decl.parent:
                continue
            if decl.parent not in self.interface_table:
                self._error(f"Parent interface '{decl.parent}' not found", decl.line, decl.col)
                continue
            info = self.interface_table[decl.name]
            parent_info = self.interface_table[decl.parent]
            for mname, method in parent_info.methods.items():
                if mname not in info.methods:
                    info.methods[mname] = method

    def _register_class(self, decl):
        if decl.name in self.class_table:
            self._error(f"Duplicate class name '{decl.name}'", decl.line, decl.col)
        info = ClassInfo(name=decl.name, generic_params=decl.generic_params,
                         parent=decl.parent, interfaces=decl.interfaces,
                         is_abstract=decl.is_abstract)
        declared_fields: set[str] = set()
        declared_methods: set[str] = set()
        for member in decl.members:
            if isinstance(member, FieldDecl):
                if member.name in declared_fields:
                    self._error(f"Duplicate field '{member.name}' in class '{decl.name}'",
                                member.line, member.col)
                declared_fields.add(member.name)
                info.fields[member.name] = member
            elif isinstance(member, MethodDecl):
                if member.name in declared_methods:
                    self._error(f"Duplicate method '{member.name}' in class '{decl.name}'",
                                member.line, member.col)
                declared_methods.add(member.name)
                if member.name == decl.name:
                    info.constructor = member
                info.methods[member.name] = member
            elif isinstance(member, PropertyDecl):
                info.properties[member.name] = member
        self.class_table[decl.name] = info

    def _resolve_class_parents(self):
        """Second pass: copy parent members into children in dependency order.

        Classes may be declared before their parents (interfaces already use
        the same two-pass scheme — see _resolve_interface_parents). Parents
        are processed before children (topological order over `parent`
        edges); missing parents and inheritance cycles are skipped here —
        _validate_inheritance reports them.
        """
        order: list[str] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(name: str):
            if name in done or name in visiting:
                return  # already handled, or a cycle (reported elsewhere)
            visiting.add(name)
            info = self.class_table.get(name)
            if info and info.parent and info.parent in self.class_table:
                visit(info.parent)
            visiting.discard(name)
            done.add(name)
            order.append(name)

        for name in list(self.class_table):
            visit(name)

        for name in order:
            info = self.class_table[name]
            if not info.parent or info.parent not in self.class_table:
                continue
            parent_info = self.class_table[info.parent]
            # Inherited members come first (struct layout contract); the
            # child's own declarations override same-named entries in place.
            merged_fields = dict(parent_info.fields)
            merged_fields.update(info.fields)
            info.fields = merged_fields
            merged_methods = {mname: m for mname, m in parent_info.methods.items()
                              if mname != parent_info.name}  # not the ctor
            merged_methods.update(info.methods)
            info.methods = merged_methods

    def _register_function(self, decl):
        if decl.name in self.function_table:
            existing = self.function_table[decl.name]
            if existing.body is None and decl.body is not None:
                pass
            elif existing.body is not None and decl.body is None:
                return
            else:
                self._error(f"Duplicate function name '{decl.name}'", decl.line, decl.col)
        self.function_table[decl.name] = decl

    def _validate_inheritance(self, program):
        """Check for circular inheritance and missing parent classes."""
        for decl in self._decls_with_file(program):
            if not isinstance(decl, ClassDecl) or not decl.parent:
                continue
            if decl.parent not in self.class_table:
                self._error(f"Parent class '{decl.parent}' not found", decl.line, decl.col)
                continue
            seen = {decl.name}
            cur = decl.parent
            while cur and cur in self.class_table:
                if cur in seen:
                    self._error(f"Circular inheritance detected: '{decl.name}' -> '{cur}'",
                                decl.line, decl.col)
                    break
                seen.add(cur)
                cur = self.class_table[cur].parent

    def _validate_interfaces(self, program):
        """Validate interface implementations and abstract class constraints."""
        for decl in self._decls_with_file(program):
            if not isinstance(decl, ClassDecl):
                continue
            cls = self.class_table.get(decl.name)
            if not cls:
                continue
            for iface_name in cls.interfaces:
                if iface_name not in self.interface_table:
                    self._error(f"Interface '{iface_name}' not found", decl.line, decl.col)
                    continue
                iface = self.interface_table[iface_name]
                for mname, iface_method in iface.methods.items():
                    if mname not in cls.methods:
                        self._error(
                            f"Class '{decl.name}' does not implement interface method "
                            f"'{mname}' from '{iface_name}'",
                            decl.line, decl.col)
                    else:
                        self._check_signature_compat(
                            decl.name, cls.methods[mname], iface_method,
                            f"interface '{iface_name}'")
            if cls.parent and cls.parent in self.class_table and not cls.is_abstract:
                parent = self.class_table[cls.parent]
                if parent.is_abstract:
                    for mname, method in parent.methods.items():
                        if method.is_abstract and mname not in {
                            m.name for m in decl.members if isinstance(m, MethodDecl)
                        }:
                            self._error(
                                f"Class '{decl.name}' must implement abstract method "
                                f"'{mname}' from '{cls.parent}'",
                                decl.line, decl.col)

    def _validate_overrides(self, program):
        """Validate that method overrides have compatible signatures."""
        for decl in self._decls_with_file(program):
            if not isinstance(decl, ClassDecl) or not decl.parent:
                continue
            parent_cls = self.class_table.get(decl.parent)
            if not parent_cls:
                continue
            for member in decl.members:
                if not isinstance(member, MethodDecl):
                    continue
                if member.name == decl.name:  # skip constructor
                    continue
                parent_method = parent_cls.methods.get(member.name)
                if not parent_method:
                    continue
                self._check_signature_compat(
                    decl.name, member, parent_method,
                    f"parent class '{decl.parent}'")

    def _check_signature_compat(self, class_name, impl, expected, source):
        """Check that impl method signature is compatible with expected."""
        name = impl.name
        line = getattr(impl, 'line', 0)
        col = getattr(impl, 'col', 0)
        # Check return type
        impl_ret = getattr(impl, 'return_type', None)
        exp_ret = getattr(expected, 'return_type', None)
        if (exp_ret and impl_ret
                and exp_ret.base and impl_ret.base
                and not self._types_compatible(exp_ret, impl_ret)):
            self._error(
                f"Override '{name}' in '{class_name}' has incompatible "
                f"return type '{impl_ret.base}' (expected '{exp_ret.base}' "
                f"from {source})", line, col)
        # Check parameter count
        impl_params = getattr(impl, 'params', [])
        exp_params = getattr(expected, 'params', [])
        if len(impl_params) != len(exp_params):
            self._error(
                f"Override '{name}' in '{class_name}' has "
                f"{len(impl_params)} parameter(s) (expected "
                f"{len(exp_params)} from {source})", line, col)
        else:
            for i, (ep, ip) in enumerate(zip(exp_params, impl_params)):
                if (ep.type and ip.type
                        and not self._types_compatible(ep.type, ip.type)):
                    self._error(
                        f"Override '{name}' param {i+1} in '{class_name}' "
                        f"has incompatible type '{ip.type.base}' "
                        f"(expected '{ep.type.base}' from {source})",
                        line, col)
