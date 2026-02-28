"""Declaration, class, method, property, and function analysis."""

from ..ast_nodes import (
    BoolLiteral, ClassDecl, EnumDecl, FieldDecl, FunctionDecl,
    IfStmt, MethodDecl, PropertyDecl, ReturnStmt, RichEnumDecl,
    SwitchStmt, ThrowStmt, TypeExpr, VarDeclStmt, WhileStmt,
    Block, ElseBlock, ElseIf,
)
from .core import SymbolInfo


class FunctionsMixin:

    def _analyze_decl(self, decl):
        if isinstance(decl, ClassDecl):
            self._analyze_class(decl)
        elif isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        elif isinstance(decl, VarDeclStmt):
            self._analyze_var_decl(decl)
        elif isinstance(decl, EnumDecl):
            self.enum_table[decl.name] = [v.name for v in decl.values]
        elif isinstance(decl, RichEnumDecl):
            self.rich_enum_table[decl.name] = decl

    def _analyze_class(self, decl):
        prev_class = self.current_class
        self.current_class = self.class_table[decl.name]
        for member in decl.members:
            if isinstance(member, FieldDecl):
                member.type = self._upgrade_class_type(member.type)
                self._collect_generic_instances(member.type)
                if member.initializer:
                    self._analyze_expr(member.initializer)
            elif isinstance(member, MethodDecl):
                self._analyze_method(member)
            elif isinstance(member, PropertyDecl):
                self._analyze_property(member)
        self.current_class = prev_class

    def _validate_default_params(self, params, line, col):
        """Ensure default parameters come after all non-default parameters."""
        seen_default = False
        for param in params:
            if param.default is not None:
                seen_default = True
            elif seen_default:
                self._error(
                    f"Non-default parameter '{param.name}' follows default parameter",
                    param.line or line, param.col or col)
                break

    def _upgrade_class_type(self, type_expr):
        """Auto-upgrade class-typed references to pointers (reference types)."""
        if type_expr is None:
            return type_expr
        upgraded_args = type_expr.generic_args
        if type_expr.generic_args:
            upgraded_args = [self._upgrade_class_type(arg) for arg in type_expr.generic_args]
            if upgraded_args != type_expr.generic_args:
                type_expr = TypeExpr(
                    base=type_expr.base, generic_args=upgraded_args,
                    pointer_depth=type_expr.pointer_depth, is_array=type_expr.is_array,
                    array_size=type_expr.array_size,
                    line=type_expr.line, col=type_expr.col)
        if type_expr.base in self.class_table:
            if type_expr.pointer_depth > 0 and not type_expr.is_nullable:
                self._error(
                    f"Redundant pointer for class type '{type_expr.base}' — "
                    f"classes are always heap-allocated. "
                    f"Use '{type_expr.base}' instead of '{type_expr.base}*'",
                    type_expr.line, type_expr.col)
            return TypeExpr(
                base=type_expr.base, generic_args=upgraded_args,
                pointer_depth=1, is_array=type_expr.is_array,
                array_size=type_expr.array_size,
                is_nullable=type_expr.is_nullable,
                line=type_expr.line, col=type_expr.col)
        return type_expr

    def _analyze_method(self, method):
        prev_method = self.current_method
        self.current_method = method
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = method.is_gpu
        prev_return_type = self.current_return_type
        self.current_return_type = method.return_type

        for param in method.params:
            param.type = self._upgrade_class_type(param.type)
        is_constructor = method.name == (self.current_class.name if self.current_class else "")
        if is_constructor:
            if method.return_type and method.return_type.base not in (
                    "void", self.current_class.name if self.current_class else ""):
                self._error(
                    f"Constructor '{method.name}' cannot have return type "
                    f"'{method.return_type.base}'", method.line, method.col)
        else:
            method.return_type = self._upgrade_class_type(method.return_type)

        self._push_scope()
        self._validate_default_params(method.params, method.line, method.col)

        if method.access != "class":
            self_type = TypeExpr(base=self.current_class.name, pointer_depth=1)
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
        for param in method.params:
            self._collect_generic_instances(param.type)
            self.scope.define(param.name, SymbolInfo(param.name, param.type, "param"))
        self._collect_generic_instances(method.return_type)
        self._analyze_block(method.body)

        if (not is_constructor and method.return_type
                and method.return_type.base != "void"
                and method.body and not self._has_return(method.body)):
            class_name = self.current_class.name if self.current_class else ""
            self._error(
                f"Method '{class_name}.{method.name}' has non-void return type "
                f"but no return statement", method.line, method.col)

        self._pop_scope()
        self.current_method = prev_method
        self.in_gpu_function = prev_gpu
        self.current_return_type = prev_return_type

    def _analyze_property(self, prop):
        """Analyze a C#-style property declaration."""
        self._collect_generic_instances(prop.type)
        prop.type = self._upgrade_class_type(prop.type)
        synthetic_method = MethodDecl(access=prop.access, return_type=prop.type,
                                      name=f"_prop_{prop.name}")
        prev_method = self.current_method
        self.current_method = synthetic_method
        if prop.getter_body:
            self._push_scope()
            self_type = TypeExpr(base=self.current_class.name, pointer_depth=1)
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
            self._analyze_block(prop.getter_body)
            self._pop_scope()
        if prop.setter_body:
            self._push_scope()
            self_type = TypeExpr(base=self.current_class.name, pointer_depth=1)
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
            self.scope.define("value", SymbolInfo("value", prop.type, "param"))
            self._analyze_block(prop.setter_body)
            self._pop_scope()
        self.current_method = prev_method

    def _analyze_function(self, func):
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = func.is_gpu
        prev_return_type = self.current_return_type
        self.current_return_type = func.return_type

        for param in func.params:
            param.type = self._upgrade_class_type(param.type)
        func.return_type = self._upgrade_class_type(func.return_type)

        self._push_scope()
        self._validate_default_params(func.params, func.line, func.col)
        self.scope.define(func.name, SymbolInfo(func.name, func.return_type, "function"))
        for param in func.params:
            self._collect_generic_instances(param.type)
            self.scope.define(param.name, SymbolInfo(param.name, param.type, "param"))
        self._collect_generic_instances(func.return_type)
        self._analyze_block(func.body)

        if (func.return_type and func.return_type.base != "void"
                and func.body and not self._has_return(func.body)):
            self._error(f"Function '{func.name}' has non-void return type "
                        f"but no return statement", func.line, func.col)

        self._pop_scope()
        self.in_gpu_function = prev_gpu
        self.current_return_type = prev_return_type

    def _has_return(self, block) -> bool:
        """Check if a block contains at least one return/throw statement."""
        if block is None:
            return False
        for stmt in block.statements:
            if isinstance(stmt, (ReturnStmt, ThrowStmt)):
                return True
            if isinstance(stmt, IfStmt):
                if stmt.else_block is not None and self._has_return_in_if(stmt):
                    return True
            if isinstance(stmt, SwitchStmt):
                for case in stmt.cases:
                    for case_stmt in case.body:
                        if isinstance(case_stmt, (ReturnStmt, ThrowStmt)):
                            return True
                        if isinstance(case_stmt, Block) and self._has_return(case_stmt):
                            return True
                        if (isinstance(case_stmt, IfStmt)
                                and case_stmt.else_block is not None):
                            if self._has_return_in_if(case_stmt):
                                return True
            if isinstance(stmt, WhileStmt) and isinstance(stmt.condition, BoolLiteral):
                if stmt.condition.value and stmt.body and self._has_return(stmt.body):
                    return True
            for attr in ('try_block', 'catch_block'):
                child = getattr(stmt, attr, None)
                if isinstance(child, Block) and self._has_return(child):
                    return True
        return False

    def _has_return_in_if(self, stmt) -> bool:
        """Check if ALL branches of an if/else return (exhaustive)."""
        then_returns = isinstance(stmt.then_block, Block) and self._has_return(stmt.then_block)
        if not then_returns:
            return False
        if isinstance(stmt.else_block, ElseBlock):
            return self._has_return(stmt.else_block.body)
        if isinstance(stmt.else_block, ElseIf):
            return self._has_return_in_if(stmt.else_block.if_stmt)
        return False
