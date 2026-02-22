"""Semantic analyzer for the btrc language.

Responsibilities:
- Build symbol tables (nested scopes)
- Resolve types and validate type usage
- Enforce access control (public/private/class)
- Validate self usage
- Collect generic instantiations for monomorphization
- Validate @gpu functions
- Resolve constructors and method calls
"""

from __future__ import annotations
from dataclasses import dataclass, field
from .ast_nodes import *


class AnalyzerError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


@dataclass
class ClassInfo:
    name: str
    generic_params: list[str] = field(default_factory=list)
    fields: dict[str, FieldDecl] = field(default_factory=dict)
    methods: dict[str, MethodDecl] = field(default_factory=dict)
    constructor: MethodDecl = None
    parent: str = None  # parent class name for inheritance


@dataclass
class SymbolInfo:
    name: str
    type: TypeExpr
    kind: str = "variable"  # "variable" | "function" | "param"


@dataclass
class Scope:
    symbols: dict[str, SymbolInfo] = field(default_factory=dict)
    parent: Scope = None

    def lookup(self, name: str) -> SymbolInfo | None:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, info: SymbolInfo):
        self.symbols[name] = info


@dataclass
class AnalyzedProgram:
    program: Program
    generic_instances: dict[str, list[tuple[TypeExpr, ...]]]
    class_table: dict[str, ClassInfo]
    node_types: dict[int, TypeExpr] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Analyzer:
    def __init__(self):
        self.class_table: dict[str, ClassInfo] = {}
        self.function_table: dict[str, FunctionDecl] = {}
        self.generic_instances: dict[str, list[tuple[TypeExpr, ...]]] = {}
        self.errors: list[str] = []
        self.scope: Scope = Scope()  # global scope
        self.current_class: ClassInfo | None = None
        self.current_method: MethodDecl | None = None
        self.in_gpu_function: bool = False
        self.node_types: dict[int, TypeExpr] = {}  # id(expr_node) -> TypeExpr

    def analyze(self, program: Program) -> AnalyzedProgram:
        # Pass 1: Register all classes and top-level functions
        self._register_declarations(program)

        # Pass 2: Analyze bodies
        for decl in program.declarations:
            self._analyze_decl(decl)

        return AnalyzedProgram(
            program=program,
            generic_instances=self.generic_instances,
            class_table=self.class_table,
            node_types=self.node_types,
            errors=self.errors,
        )

    def _error(self, msg: str, line: int = 0, col: int = 0):
        self.errors.append(f"{msg} at {line}:{col}")

    # ---- Scope management ----

    def _push_scope(self):
        self.scope = Scope(parent=self.scope)

    def _pop_scope(self):
        self.scope = self.scope.parent

    # ---- Pass 1: Registration ----

    def _register_declarations(self, program: Program):
        for decl in program.declarations:
            if isinstance(decl, ClassDecl):
                self._register_class(decl)
            elif isinstance(decl, FunctionDecl):
                self._register_function(decl)

    def _register_class(self, decl: ClassDecl):
        info = ClassInfo(name=decl.name, generic_params=decl.generic_params,
                         parent=decl.parent)

        # Inherit from parent class if specified
        if decl.parent and decl.parent in self.class_table:
            parent_info = self.class_table[decl.parent]
            # Inherit parent fields (child fields override if same name)
            for fname, fld in parent_info.fields.items():
                info.fields[fname] = fld
            # Inherit parent methods (child methods override if same name)
            for mname, method in parent_info.methods.items():
                if mname != parent_info.name:  # don't inherit parent constructor
                    info.methods[mname] = method

        for member in decl.members:
            if isinstance(member, FieldDecl):
                info.fields[member.name] = member
            elif isinstance(member, MethodDecl):
                if member.name == decl.name:
                    info.constructor = member
                info.methods[member.name] = member
        self.class_table[decl.name] = info

    def _register_function(self, decl: FunctionDecl):
        self.function_table[decl.name] = decl

    # ---- Pass 2: Analysis ----

    def _analyze_decl(self, decl):
        if isinstance(decl, ClassDecl):
            self._analyze_class(decl)
        elif isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        elif isinstance(decl, VarDeclStmt):
            self._analyze_var_decl(decl)
        # PreprocessorDirective, StructDecl, EnumDecl, TypedefDecl — no analysis needed

    def _analyze_class(self, decl: ClassDecl):
        prev_class = self.current_class
        self.current_class = self.class_table[decl.name]

        for member in decl.members:
            if isinstance(member, FieldDecl):
                self._collect_generic_instances(member.type)
                if member.initializer:
                    self._analyze_expr(member.initializer)
            elif isinstance(member, MethodDecl):
                self._analyze_method(member)

        self.current_class = prev_class

    def _analyze_method(self, method: MethodDecl):
        prev_method = self.current_method
        self.current_method = method
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = method.is_gpu

        self._push_scope()

        # Add 'self' to scope for non-static methods
        if method.access != "class":
            self_type = TypeExpr(base=self.current_class.name, pointer_depth=1)
            self.scope.define("self", SymbolInfo("self", self_type, "param"))

        # Add params
        for param in method.params:
            self._collect_generic_instances(param.type)
            self.scope.define(param.name, SymbolInfo(param.name, param.type, "param"))

        # Analyze body
        self._collect_generic_instances(method.return_type)
        self._analyze_block(method.body)

        self._pop_scope()
        self.current_method = prev_method
        self.in_gpu_function = prev_gpu

    def _analyze_function(self, func: FunctionDecl):
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = func.is_gpu

        self._push_scope()

        # Register in global scope
        self.scope.define(func.name, SymbolInfo(
            func.name,
            func.return_type,
            "function"
        ))

        # Add params
        for param in func.params:
            self._collect_generic_instances(param.type)
            self.scope.define(param.name, SymbolInfo(param.name, param.type, "param"))

        self._collect_generic_instances(func.return_type)
        self._analyze_block(func.body)

        self._pop_scope()
        self.in_gpu_function = prev_gpu

    def _analyze_block(self, block: Block):
        if block is None:
            return
        self._push_scope()
        for stmt in block.statements:
            self._analyze_stmt(stmt)
        self._pop_scope()

    # ---- Statements ----

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, VarDeclStmt):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self._analyze_expr(stmt.value)
        elif isinstance(stmt, IfStmt):
            self._analyze_expr(stmt.condition)
            self._analyze_block(stmt.then_block)
            if isinstance(stmt.else_block, IfStmt):
                self._analyze_stmt(stmt.else_block)
            elif isinstance(stmt.else_block, Block):
                self._analyze_block(stmt.else_block)
        elif isinstance(stmt, WhileStmt):
            self._analyze_expr(stmt.condition)
            self._analyze_block(stmt.body)
        elif isinstance(stmt, DoWhileStmt):
            self._analyze_block(stmt.body)
            self._analyze_expr(stmt.condition)
        elif isinstance(stmt, ForInStmt):
            self._analyze_for_in(stmt)
        elif isinstance(stmt, ParallelForStmt):
            self._analyze_parallel_for(stmt)
        elif isinstance(stmt, CForStmt):
            self._analyze_c_for(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._analyze_expr(stmt.value)
            for case in stmt.cases:
                if case.value:
                    self._analyze_expr(case.value)
                for s in case.body:
                    self._analyze_stmt(s)
        elif isinstance(stmt, ExprStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, DeleteStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, Block):
            self._analyze_block(stmt)
        elif isinstance(stmt, TryCatchStmt):
            self._analyze_block(stmt.try_block)
            self._push_scope()
            self.scope.define(stmt.catch_var, SymbolInfo(stmt.catch_var, TypeExpr(base="string"), "variable"))
            self._analyze_block(stmt.catch_block)
            self._pop_scope()
        elif isinstance(stmt, ThrowStmt):
            self._analyze_expr(stmt.expr)
        elif isinstance(stmt, (BreakStmt, ContinueStmt)):
            pass

    def _analyze_var_decl(self, stmt: VarDeclStmt):
        # Handle 'var' type inference: type is None when declared with 'var'
        if stmt.type is None:
            if stmt.initializer is None:
                self._error(f"'var' declaration of '{stmt.name}' requires an initializer",
                            stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")  # fallback to avoid downstream crashes
            else:
                self._analyze_expr(stmt.initializer)
                inferred = self._infer_type(stmt.initializer)
                if inferred is None:
                    self._error(f"Cannot infer type for 'var' declaration of '{stmt.name}'",
                                stmt.line, stmt.col)
                    stmt.type = TypeExpr(base="int")  # fallback
                else:
                    stmt.type = inferred
                self._collect_generic_instances(stmt.type)
                self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))
                return

        self._collect_generic_instances(stmt.type)
        if stmt.initializer:
            self._analyze_expr(stmt.initializer)
        self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))

    def _analyze_for_in(self, stmt: ForInStmt):
        self._analyze_expr(stmt.iterable)

        # Check for range() call — element type is always int
        if self._is_range_call(stmt.iterable):
            elem_type = TypeExpr(base="int")
        else:
            # Determine element type from iterable
            iter_type = self._infer_type(stmt.iterable)
            elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)

        self._push_scope()
        if elem_type:
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
        self._analyze_block(stmt.body)
        self._pop_scope()

    def _is_range_call(self, expr) -> bool:
        return (isinstance(expr, CallExpr) and
                isinstance(expr.callee, Identifier) and
                expr.callee.name == "range")

    def _analyze_parallel_for(self, stmt: ParallelForStmt):
        self._analyze_expr(stmt.iterable)

        iter_type = self._infer_type(stmt.iterable)
        elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)

        self._push_scope()
        if elem_type:
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
        self._analyze_block(stmt.body)
        self._pop_scope()

    def _analyze_c_for(self, stmt: CForStmt):
        self._push_scope()
        if stmt.init:
            if isinstance(stmt.init, VarDeclStmt):
                self._analyze_var_decl(stmt.init)
            else:
                self._analyze_expr(stmt.init)
        if stmt.condition:
            self._analyze_expr(stmt.condition)
        if stmt.update:
            self._analyze_expr(stmt.update)
        self._analyze_block(stmt.body)
        self._pop_scope()

    # ---- Expressions ----

    def _analyze_expr(self, expr):
        if expr is None:
            return

        if isinstance(expr, (IntLiteral, FloatLiteral, StringLiteral,
                             CharLiteral, BoolLiteral, NullLiteral)):
            pass

        elif isinstance(expr, Identifier):
            # Don't error on unknown identifiers — they may come from C headers
            # (#include <stdio.h> etc.) that we don't parse. The C compiler
            # will catch real undefined symbols.
            pass

        elif isinstance(expr, SelfExpr):
            self._validate_self(expr)

        elif isinstance(expr, BinaryExpr):
            self._analyze_expr(expr.left)
            self._analyze_expr(expr.right)

        elif isinstance(expr, UnaryExpr):
            self._analyze_expr(expr.operand)

        elif isinstance(expr, CallExpr):
            self._analyze_call(expr)

        elif isinstance(expr, IndexExpr):
            self._analyze_expr(expr.obj)
            self._analyze_expr(expr.index)

        elif isinstance(expr, FieldAccessExpr):
            self._analyze_field_access(expr)

        elif isinstance(expr, AssignExpr):
            self._analyze_expr(expr.target)
            self._analyze_expr(expr.value)

        elif isinstance(expr, TernaryExpr):
            self._analyze_expr(expr.condition)
            self._analyze_expr(expr.true_expr)
            self._analyze_expr(expr.false_expr)

        elif isinstance(expr, CastExpr):
            self._collect_generic_instances(expr.target_type)
            self._analyze_expr(expr.expr)

        elif isinstance(expr, SizeofExpr):
            if isinstance(expr.operand, TypeExpr):
                self._collect_generic_instances(expr.operand)
            else:
                self._analyze_expr(expr.operand)

        elif isinstance(expr, ListLiteral):
            for el in expr.elements:
                self._analyze_expr(el)

        elif isinstance(expr, MapLiteral):
            for key, val in expr.entries:
                self._analyze_expr(key)
                self._analyze_expr(val)

        elif isinstance(expr, FStringLiteral):
            for kind, val in expr.parts:
                if kind == "expr":
                    self._analyze_expr(val)

        elif isinstance(expr, TupleLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
            # Collect the tuple type as a generic instance
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            tuple_type = TypeExpr(base="Tuple", generic_args=elem_types)
            self._collect_generic_instances(tuple_type)

        elif isinstance(expr, NewExpr):
            self._collect_generic_instances(expr.type)
            for arg in expr.args:
                self._analyze_expr(arg)
            # Validate that the type has a constructor
            if expr.type.base in self.class_table:
                cls = self.class_table[expr.type.base]
                if cls.constructor is None and len(expr.args) > 0:
                    self._error(f"Class '{expr.type.base}' has no constructor",
                                expr.line, expr.col)

        # Record inferred type for codegen
        inferred = self._infer_type(expr)
        if inferred:
            self.node_types[id(expr)] = inferred

    def _analyze_call(self, expr: CallExpr):
        self._analyze_expr(expr.callee)
        for arg in expr.args:
            self._analyze_expr(arg)

        # Check if this is a constructor call: foo(args) where foo is a class name
        if isinstance(expr.callee, Identifier) and expr.callee.name in self.class_table:
            cls = self.class_table[expr.callee.name]
            if cls.constructor is None and len(expr.args) > 0:
                self._error(f"Class '{expr.callee.name}' has no constructor",
                            expr.line, expr.col)

    def _analyze_field_access(self, expr: FieldAccessExpr):
        self._analyze_expr(expr.obj)

        # Check access control
        obj_type = self._infer_type(expr.obj)
        if obj_type and obj_type.base in self.class_table:
            cls = self.class_table[obj_type.base]
            # Check if field exists
            if expr.field in cls.fields:
                field_decl = cls.fields[expr.field]
                if field_decl.access == "private":
                    if self.current_class is None or self.current_class.name != cls.name:
                        self._error(
                            f"Cannot access private field '{expr.field}' of class '{cls.name}'",
                            expr.line, expr.col
                        )
            elif expr.field in cls.methods:
                method = cls.methods[expr.field]
                if method.access == "private":
                    if self.current_class is None or self.current_class.name != cls.name:
                        self._error(
                            f"Cannot access private method '{expr.field}' of class '{cls.name}'",
                            expr.line, expr.col
                        )
        # For Identifier.method (static call), check class table
        elif isinstance(expr.obj, Identifier) and expr.obj.name in self.class_table:
            cls = self.class_table[expr.obj.name]
            if expr.field in cls.methods:
                method = cls.methods[expr.field]
                if method.access != "class":
                    self._error(
                        f"Method '{expr.field}' is not a class method, cannot call statically",
                        expr.line, expr.col
                    )

    # ---- Self validation ----

    def _validate_self(self, expr: SelfExpr):
        if self.current_class is None:
            self._error("'self' used outside of a class", expr.line, expr.col)
        elif self.current_method is None:
            self._error("'self' used outside of a method", expr.line, expr.col)
        elif self.current_method.access == "class":
            self._error("'self' cannot be used in a class (static) method",
                        expr.line, expr.col)

    # ---- Generic instance collection ----

    def _collect_generic_instances(self, type_expr: TypeExpr):
        if type_expr is None:
            return
        if type_expr.generic_args:
            key = type_expr.base
            args_tuple = tuple(type_expr.generic_args)
            if key not in self.generic_instances:
                self.generic_instances[key] = []
            # Avoid duplicates
            existing = [t for t in self.generic_instances[key]]
            if args_tuple not in existing:
                self.generic_instances[key].append(args_tuple)
            # Recurse into generic args
            for arg in type_expr.generic_args:
                self._collect_generic_instances(arg)

    # ---- Type inference (simplified) ----

    def _infer_type(self, expr) -> TypeExpr | None:
        """Best-effort type inference. Returns None if unknown."""
        if isinstance(expr, IntLiteral):
            return TypeExpr(base="int")
        elif isinstance(expr, FloatLiteral):
            return TypeExpr(base="float")
        elif isinstance(expr, StringLiteral):
            return TypeExpr(base="string")
        elif isinstance(expr, CharLiteral):
            return TypeExpr(base="char")
        elif isinstance(expr, BoolLiteral):
            return TypeExpr(base="bool")
        elif isinstance(expr, NullLiteral):
            return TypeExpr(base="void", pointer_depth=1)
        elif isinstance(expr, Identifier):
            sym = self.scope.lookup(expr.name)
            if sym:
                return sym.type
            return None
        elif isinstance(expr, SelfExpr):
            if self.current_class:
                return TypeExpr(base=self.current_class.name, pointer_depth=1)
            return None
        elif isinstance(expr, FieldAccessExpr):
            obj_type = self._infer_type(expr.obj)
            if obj_type and obj_type.base in self.class_table:
                cls = self.class_table[obj_type.base]
                if expr.field in cls.fields:
                    return cls.fields[expr.field].type
            return None
        elif isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                if expr.callee.name in self.class_table:
                    return TypeExpr(base=expr.callee.name)
                if expr.callee.name in self.function_table:
                    return self.function_table[expr.callee.name].return_type
            # Method call on an object: check for string methods and class methods
            if isinstance(expr.callee, FieldAccessExpr):
                obj_type = self._infer_type(expr.callee.obj)
                if obj_type and (obj_type.base == "string" or
                    (obj_type.base == "char" and obj_type.pointer_depth >= 1)):
                    return self._string_method_return_type(expr.callee.field)
                if obj_type and obj_type.base in self.class_table:
                    cls = self.class_table[obj_type.base]
                    if expr.callee.field in cls.methods:
                        return cls.methods[expr.callee.field].return_type
                # Static method call: ClassName.method() where ClassName is a class
                if isinstance(expr.callee.obj, Identifier) and expr.callee.obj.name in self.class_table:
                    cls = self.class_table[expr.callee.obj.name]
                    if expr.callee.field in cls.methods:
                        return cls.methods[expr.callee.field].return_type
            return None
        elif isinstance(expr, NewExpr):
            return TypeExpr(base=expr.type.base, generic_args=expr.type.generic_args,
                            pointer_depth=1)
        elif isinstance(expr, IndexExpr):
            obj_type = self._infer_type(expr.obj)
            if obj_type and obj_type.base in ("List", "Array") and obj_type.generic_args:
                return obj_type.generic_args[0]
            return None
        elif isinstance(expr, BinaryExpr):
            left_type = self._infer_type(expr.left)
            right_type = self._infer_type(expr.right)
            if expr.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
                return TypeExpr(base="bool")
            if left_type and right_type:
                if left_type.base in ("float", "double") or right_type.base in ("float", "double"):
                    return TypeExpr(base="float")
                if left_type.base == "int" and right_type.base == "int":
                    return TypeExpr(base="int")
            return left_type
        elif isinstance(expr, CastExpr):
            return expr.target_type
        elif isinstance(expr, UnaryExpr):
            return self._infer_type(expr.operand)
        elif isinstance(expr, TernaryExpr):
            return self._infer_type(expr.true_expr)
        elif isinstance(expr, AssignExpr):
            return self._infer_type(expr.target)
        elif isinstance(expr, TupleLiteral):
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            return TypeExpr(base="Tuple", generic_args=elem_types)
        elif isinstance(expr, ListLiteral):
            if expr.elements:
                elem_type = self._infer_type(expr.elements[0])
                if elem_type:
                    return TypeExpr(base="List", generic_args=[elem_type])
            return TypeExpr(base="List", generic_args=[TypeExpr(base="int")])
        elif isinstance(expr, MapLiteral):
            if expr.entries:
                key_type = self._infer_type(expr.entries[0][0])
                val_type = self._infer_type(expr.entries[0][1])
                if key_type and val_type:
                    return TypeExpr(base="Map", generic_args=[key_type, val_type])
            return TypeExpr(base="Map", generic_args=[TypeExpr(base="string"), TypeExpr(base="int")])
        return None

    def _string_method_return_type(self, method_name: str) -> TypeExpr | None:
        """Return the type of a string method call."""
        string_methods = {
            "len": TypeExpr(base="int"),
            "byteLen": TypeExpr(base="int"),
            "charLen": TypeExpr(base="int"),
            "contains": TypeExpr(base="bool"),
            "startsWith": TypeExpr(base="bool"),
            "endsWith": TypeExpr(base="bool"),
            "equals": TypeExpr(base="bool"),
            "indexOf": TypeExpr(base="int"),
            "charAt": TypeExpr(base="char"),
            "substring": TypeExpr(base="string"),
            "trim": TypeExpr(base="string"),
            "toUpper": TypeExpr(base="string"),
            "toLower": TypeExpr(base="string"),
            "split": TypeExpr(base="string", pointer_depth=1),  # char**
        }
        return string_methods.get(method_name)

    def _get_element_type(self, iter_type: TypeExpr | None, line: int, col: int) -> TypeExpr | None:
        """Get the element type for for-in iteration."""
        if iter_type is None:
            return None

        if iter_type.base in ("List", "Array") and iter_type.generic_args:
            return iter_type.generic_args[0]

        if iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            # For maps, we'd need a key-value pair type
            # For now, return None and let codegen handle it
            return None

        # Check if it's a user-defined class with generic args (monomorphized List/Array)
        if iter_type.base in self.class_table:
            # Not inherently iterable
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None

        # Primitive types are not iterable
        if iter_type.base in ("int", "float", "double", "char", "bool", "string"):
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None

        return None
