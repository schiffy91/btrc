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
from .ast_nodes import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    CastExpr,
    CForStmt,
    CharLiteral,
    ClassDecl,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    EnumDecl,
    ExprStmt,
    FieldAccessExpr,
    FieldDecl,
    FloatLiteral,
    ForInStmt,
    FStringLiteral,
    FunctionDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    NewExpr,
    NullLiteral,
    ParallelForStmt,
    Program,
    PropertyDecl,
    ReturnStmt,
    SelfExpr,
    SizeofExpr,
    StringLiteral,
    SwitchStmt,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)


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
    properties: dict[str, PropertyDecl] = field(default_factory=dict)
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
    function_table: dict[str, FunctionDecl] = field(default_factory=dict)
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
        self.current_return_type: TypeExpr | None = None
        self.in_gpu_function: bool = False
        self.node_types: dict[int, TypeExpr] = {}  # id(expr_node) -> TypeExpr
        self.loop_depth: int = 0  # track nesting for break/continue validation
        self.break_depth: int = 0  # loops + switches (break is valid in both)
        self.enum_table: dict[str, list[str]] = {}  # enum_name -> [value_names]

    def analyze(self, program: Program) -> AnalyzedProgram:
        # Pass 1: Register all classes and top-level functions
        self._register_declarations(program)

        # Pass 1.5: Validate inheritance (after all classes registered)
        self._validate_inheritance(program)

        # Pass 2: Analyze bodies
        for decl in program.declarations:
            self._analyze_decl(decl)

        return AnalyzedProgram(
            program=program,
            generic_instances=self.generic_instances,
            class_table=self.class_table,
            function_table=self.function_table,
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
        # Check for duplicate class names
        if decl.name in self.class_table:
            self._error(f"Duplicate class name '{decl.name}'", decl.line, decl.col)
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

    def _register_function(self, decl: FunctionDecl):
        if decl.name in self.function_table:
            existing = self.function_table[decl.name]
            # Forward declaration followed by definition is allowed
            if existing.body is None and decl.body is not None:
                pass  # Replace forward decl with definition
            elif existing.body is not None and decl.body is None:
                return  # Ignore forward decl after definition
            else:
                self._error(f"Duplicate function name '{decl.name}'", decl.line, decl.col)
        self.function_table[decl.name] = decl

    def _validate_inheritance(self, program: Program):
        """Check for circular inheritance and missing parent classes."""
        for decl in program.declarations:
            if not isinstance(decl, ClassDecl) or not decl.parent:
                continue
            if decl.parent not in self.class_table:
                self._error(f"Parent class '{decl.parent}' not found", decl.line, decl.col)
                continue
            # Walk the parent chain to detect cycles
            seen = {decl.name}
            cur = decl.parent
            while cur and cur in self.class_table:
                if cur in seen:
                    self._error(f"Circular inheritance detected: '{decl.name}' -> '{cur}'", decl.line, decl.col)
                    break
                seen.add(cur)
                cur = self.class_table[cur].parent

    # ---- Pass 2: Analysis ----

    def _analyze_decl(self, decl):
        if isinstance(decl, ClassDecl):
            self._analyze_class(decl)
        elif isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        elif isinstance(decl, VarDeclStmt):
            self._analyze_var_decl(decl)
        elif isinstance(decl, EnumDecl):
            self.enum_table[decl.name] = [v[0] if isinstance(v, tuple) else v for v in decl.values]
        # PreprocessorDirective, StructDecl, TypedefDecl — no analysis needed

    def _analyze_class(self, decl: ClassDecl):
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

    def _validate_default_params(self, params: list, line: int, col: int):
        """Ensure default parameters come after all non-default parameters."""
        seen_default = False
        for param in params:
            if param.default is not None:
                seen_default = True
            elif seen_default:
                self._error(
                    f"Non-default parameter '{param.name}' follows default parameter",
                    param.line or line, param.col or col,
                )
                break

    def _upgrade_class_type(self, type_expr: TypeExpr) -> TypeExpr:
        """Auto-upgrade class-typed references to pointers (reference types)."""
        if type_expr is None:
            return type_expr
        # Recursively upgrade generic args (e.g., List<Token> → List<Token*>)
        upgraded_args = type_expr.generic_args
        if type_expr.generic_args:
            upgraded_args = [self._upgrade_class_type(arg) for arg in type_expr.generic_args]
            if upgraded_args != type_expr.generic_args:
                type_expr = TypeExpr(
                    base=type_expr.base,
                    generic_args=upgraded_args,
                    pointer_depth=type_expr.pointer_depth,
                    is_array=type_expr.is_array,
                    array_size=type_expr.array_size,
                    line=type_expr.line,
                    col=type_expr.col,
                )
        if type_expr.base in self.class_table and type_expr.pointer_depth == 0:
            return TypeExpr(
                base=type_expr.base,
                generic_args=upgraded_args,
                pointer_depth=1,
                is_array=type_expr.is_array,
                array_size=type_expr.array_size,
                line=type_expr.line,
                col=type_expr.col,
            )
        return type_expr

    def _analyze_method(self, method: MethodDecl):
        prev_method = self.current_method
        self.current_method = method
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = method.is_gpu
        prev_return_type = self.current_return_type
        self.current_return_type = method.return_type

        # Auto-upgrade class-typed params and return type to pointer
        for param in method.params:
            param.type = self._upgrade_class_type(param.type)
        is_constructor = method.name == (self.current_class.name if self.current_class else "")
        if is_constructor:
            # Constructors must not have an explicit non-void return type
            if method.return_type and method.return_type.base not in ("void", self.current_class.name if self.current_class else ""):
                self._error(
                    f"Constructor '{method.name}' cannot have return type '{method.return_type.base}'",
                    method.line, method.col,
                )
        else:
            method.return_type = self._upgrade_class_type(method.return_type)

        self._push_scope()

        # Validate default parameter ordering
        self._validate_default_params(method.params, method.line, method.col)

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

        # Check that non-void, non-constructor methods have at least one return statement
        if (not is_constructor and method.return_type
                and method.return_type.base != "void"
                and method.body and not self._has_return(method.body)):
            class_name = self.current_class.name if self.current_class else ""
            self._error(
                f"Method '{class_name}.{method.name}' has non-void return type but no return statement",
                method.line, method.col,
            )

        self._pop_scope()
        self.current_method = prev_method
        self.in_gpu_function = prev_gpu
        self.current_return_type = prev_return_type

    def _analyze_property(self, prop: PropertyDecl):
        """Analyze a C#-style property declaration."""
        self._collect_generic_instances(prop.type)
        prop.type = self._upgrade_class_type(prop.type)

        # Create a synthetic method so _validate_self works inside property bodies
        synthetic_method = MethodDecl(access=prop.access, return_type=prop.type,
                                      name=f"_prop_{prop.name}")
        prev_method = self.current_method
        self.current_method = synthetic_method

        # Analyze custom getter body
        if prop.getter_body:
            self._push_scope()
            self_type = TypeExpr(base=self.current_class.name, pointer_depth=1)
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
            self._analyze_block(prop.getter_body)
            self._pop_scope()

        # Analyze custom setter body
        if prop.setter_body:
            self._push_scope()
            self_type = TypeExpr(base=self.current_class.name, pointer_depth=1)
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
            self.scope.define("value", SymbolInfo("value", prop.type, "param"))
            self._analyze_block(prop.setter_body)
            self._pop_scope()

        self.current_method = prev_method

    def _analyze_function(self, func: FunctionDecl):
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = func.is_gpu
        prev_return_type = self.current_return_type
        self.current_return_type = func.return_type

        # Auto-upgrade class-typed params and return type to pointer
        for param in func.params:
            param.type = self._upgrade_class_type(param.type)
        func.return_type = self._upgrade_class_type(func.return_type)

        self._push_scope()

        # Validate default parameter ordering
        self._validate_default_params(func.params, func.line, func.col)

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

        # Check that non-void functions have at least one return statement
        if (func.return_type and func.return_type.base != "void"
                and func.body and not self._has_return(func.body)):
            self._error(f"Function '{func.name}' has non-void return type but no return statement",
                        func.line, func.col)

        self._pop_scope()
        self.in_gpu_function = prev_gpu
        self.current_return_type = prev_return_type

    def _has_return(self, block: Block) -> bool:
        """Check if a block contains at least one return/throw statement (recursively)."""
        if block is None:
            return False
        for stmt in block.statements:
            if isinstance(stmt, (ReturnStmt, ThrowStmt)):
                return True
            # Check top-level if/else: exhaustive return (both branches return)
            if isinstance(stmt, IfStmt):
                if stmt.else_block is not None and self._has_return_in_if(stmt):
                    return True
            # Check inside switch cases
            if isinstance(stmt, SwitchStmt):
                for case in stmt.cases:
                    for case_stmt in case.body:
                        if isinstance(case_stmt, (ReturnStmt, ThrowStmt)):
                            return True
                        if isinstance(case_stmt, Block) and self._has_return(case_stmt):
                            return True
                        if isinstance(case_stmt, IfStmt) and case_stmt.else_block is not None:
                            if self._has_return_in_if(case_stmt):
                                return True
            # while(true) { return x; } is an infinite loop that always returns
            if isinstance(stmt, WhileStmt) and isinstance(stmt.condition, BoolLiteral):
                if stmt.condition.value and stmt.body and self._has_return(stmt.body):
                    return True
            # Check try/catch blocks (not loop bodies — loops may execute 0 times)
            for attr in ('try_block', 'catch_block'):
                child = getattr(stmt, attr, None)
                if isinstance(child, Block) and self._has_return(child):
                    return True
        return False

    def _has_return_in_if(self, stmt: IfStmt) -> bool:
        """Check if ALL branches of an if/else return (exhaustive)."""
        then_returns = isinstance(stmt.then_block, Block) and self._has_return(stmt.then_block)
        if not then_returns:
            return False
        if isinstance(stmt.else_block, Block):
            return self._has_return(stmt.else_block)
        if isinstance(stmt.else_block, IfStmt):
            return self._has_return_in_if(stmt.else_block)
        return False  # no else = not exhaustive

    def _analyze_block(self, block: Block):
        if block is None:
            return
        self._push_scope()
        found_terminal = False
        for stmt in block.statements:
            if found_terminal:
                line = getattr(stmt, 'line', 0)
                col = getattr(stmt, 'col', 0)
                self._error("Unreachable code after return/throw/break/continue", line, col)
                break  # only report once per block
            self._analyze_stmt(stmt)
            if isinstance(stmt, (ReturnStmt, BreakStmt, ContinueStmt, ThrowStmt)):
                found_terminal = True
        self._pop_scope()

    # ---- Statements ----

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, VarDeclStmt):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self._analyze_expr(stmt.value)
                # Check return type matches declared return type
                if self.current_return_type and self.current_return_type.base != "void":
                    ret_type = self._infer_type(stmt.value)
                    if ret_type and not self._types_compatible(self.current_return_type, ret_type):
                        self._error(
                            f"Return type mismatch: expected '{self._format_type(self.current_return_type)}' but got '{self._format_type(ret_type)}'",
                            stmt.line, stmt.col,
                        )
        elif isinstance(stmt, IfStmt):
            self._analyze_expr(stmt.condition)
            self._analyze_block(stmt.then_block)
            if isinstance(stmt.else_block, IfStmt):
                self._analyze_stmt(stmt.else_block)
            elif isinstance(stmt.else_block, Block):
                self._analyze_block(stmt.else_block)
        elif isinstance(stmt, WhileStmt):
            self._analyze_expr(stmt.condition)
            self.loop_depth += 1
            self.break_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            self.break_depth -= 1
        elif isinstance(stmt, DoWhileStmt):
            self.loop_depth += 1
            self.break_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            self.break_depth -= 1
            self._analyze_expr(stmt.condition)
        elif isinstance(stmt, ForInStmt):
            self._analyze_for_in(stmt)
        elif isinstance(stmt, ParallelForStmt):
            self._analyze_parallel_for(stmt)
        elif isinstance(stmt, CForStmt):
            self._analyze_c_for(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._analyze_expr(stmt.value)
            self.break_depth += 1
            has_default = False
            for case in stmt.cases:
                if case.value:
                    self._analyze_expr(case.value)
                else:
                    has_default = True
                for s in case.body:
                    self._analyze_stmt(s)
            self.break_depth -= 1
            # Check enum exhaustiveness
            if not has_default:
                val_type = self._infer_type(stmt.value)
                if val_type and val_type.base in self.enum_table:
                    enum_values = set(self.enum_table[val_type.base])
                    covered = set()
                    for case in stmt.cases:
                        if case.value and isinstance(case.value, Identifier):
                            covered.add(case.value.name)
                    missing = enum_values - covered
                    if missing:
                        names = ", ".join(sorted(missing))
                        self._error(
                            f"Switch on enum '{val_type.base}' is not exhaustive, missing: {names}",
                            getattr(stmt, 'line', 0), getattr(stmt, 'col', 0)
                        )
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
        elif isinstance(stmt, BreakStmt):
            if self.break_depth == 0:
                self._error("'break' statement outside of loop or switch", stmt.line, stmt.col)
        elif isinstance(stmt, ContinueStmt):
            if self.loop_depth == 0:
                self._error("'continue' statement outside of loop", stmt.line, stmt.col)

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
                if self.scope.parent:
                    existing = self.scope.parent.lookup(stmt.name)
                    if existing and existing.kind in ("variable", "param"):
                        self._error(f"Variable '{stmt.name}' shadows outer variable of same name",
                                    stmt.line, stmt.col)
                self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))
                return

        # Auto-upgrade class-typed variables to pointer (reference type)
        stmt.type = self._upgrade_class_type(stmt.type)
        self._collect_generic_instances(stmt.type)
        if stmt.initializer:
            self._analyze_expr(stmt.initializer)
            # Type mismatch check
            init_type = self._infer_type(stmt.initializer)
            if init_type and init_type.base == "void" and init_type.pointer_depth == 0:
                self._error(
                    f"Cannot assign void expression to variable '{stmt.name}'",
                    stmt.line, stmt.col,
                )
            elif init_type and stmt.type and not self._types_compatible(stmt.type, init_type):
                self._error(
                    f"Cannot assign '{init_type.base}' to variable '{stmt.name}' of type '{stmt.type.base}'",
                    stmt.line, stmt.col,
                )
        # Variable shadowing warning: check parent scopes (not current scope)
        if self.scope.parent:
            existing = self.scope.parent.lookup(stmt.name)
            if existing and existing.kind in ("variable", "param"):
                self._error(f"Variable '{stmt.name}' shadows outer variable of same name",
                            stmt.line, stmt.col)
        self.scope.define(stmt.name, SymbolInfo(stmt.name, stmt.type, "variable"))

    def _analyze_for_in(self, stmt: ForInStmt):
        self._analyze_expr(stmt.iterable)
        self.loop_depth += 1
        self.break_depth += 1

        # Check for range() call — element type is always int
        if self._is_range_call(stmt.iterable):
            elem_type = TypeExpr(base="int")
            self._push_scope()
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
            self._analyze_block(stmt.body)
            self._pop_scope()
            self.loop_depth -= 1
            self.break_depth -= 1
            return

        iter_type = self._infer_type(stmt.iterable)

        # Map iteration: for k, v in map  OR  for k in map (keys only)
        if iter_type and iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            key_type = iter_type.generic_args[0]
            val_type = iter_type.generic_args[1]
            self._push_scope()
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, key_type, "variable"))
            if stmt.var_name2:
                self.scope.define(stmt.var_name2, SymbolInfo(stmt.var_name2, val_type, "variable"))
            self._analyze_block(stmt.body)
            self._pop_scope()
            self.loop_depth -= 1
            self.break_depth -= 1
            return

        # Two-variable iteration (for k, v in x) requires a Map
        if stmt.var_name2:
            self._error(f"Two-variable for-in iteration requires a Map type, got '{iter_type}'", stmt.line, stmt.col)

        # List/Array iteration
        elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)
        self._push_scope()
        if elem_type:
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
        self._analyze_block(stmt.body)
        self._pop_scope()
        self.loop_depth -= 1
        self.break_depth -= 1

    def _is_range_call(self, expr) -> bool:
        return (isinstance(expr, CallExpr) and
                isinstance(expr.callee, Identifier) and
                expr.callee.name == "range")

    def _analyze_parallel_for(self, stmt: ParallelForStmt):
        self._analyze_expr(stmt.iterable)

        iter_type = self._infer_type(stmt.iterable)
        elem_type = self._get_element_type(iter_type, stmt.line, stmt.col)

        self.loop_depth += 1
        self.break_depth += 1
        self._push_scope()
        if elem_type:
            self.scope.define(stmt.var_name, SymbolInfo(stmt.var_name, elem_type, "variable"))
        self._analyze_block(stmt.body)
        self._pop_scope()
        self.loop_depth -= 1
        self.break_depth -= 1

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
        self.loop_depth += 1
        self.break_depth += 1
        self._analyze_block(stmt.body)
        self.loop_depth -= 1
        self.break_depth -= 1
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
            # Division by literal zero
            if expr.op in ("/", "%", "/=", "%="):
                r = expr.right
                if (isinstance(r, IntLiteral) and r.value == 0) or \
                   (isinstance(r, FloatLiteral) and r.value == 0.0):
                    self._error("Division by zero", r.line, r.col)

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
            # Validate all elements have consistent types
            if len(expr.elements) >= 2:
                first_type = self._infer_type(expr.elements[0])
                if first_type:
                    for i, el in enumerate(expr.elements[1:], 1):
                        el_type = self._infer_type(el)
                        if el_type and not self._types_compatible(first_type, el_type):
                            self._error(
                                f"List element {i} has type '{el_type.base}' but expected '{first_type.base}'",
                                getattr(el, 'line', 0), getattr(el, 'col', 0)
                            )

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

        elif isinstance(expr, LambdaExpr):
            self._analyze_lambda(expr)

        elif isinstance(expr, NewExpr):
            self._collect_generic_instances(expr.type)
            for arg in expr.args:
                self._analyze_expr(arg)
            # Validate constructor args
            if expr.type.base in self.class_table:
                cls = self.class_table[expr.type.base]
                self._validate_constructor_args(cls, expr.args, expr.line, expr.col)

        # Record inferred type for codegen
        inferred = self._infer_type(expr)
        if inferred:
            self.node_types[id(expr)] = inferred

    def _analyze_lambda(self, expr: LambdaExpr):
        """Analyze a lambda expression."""
        prev_return_type = self.current_return_type
        self._push_scope()
        for param in expr.params:
            param.type = self._upgrade_class_type(param.type)
            self._collect_generic_instances(param.type)
            self.scope.define(param.name, SymbolInfo(param.name, param.type, "param"))
        if expr.return_type:
            expr.return_type = self._upgrade_class_type(expr.return_type)
            self._collect_generic_instances(expr.return_type)
            self.current_return_type = expr.return_type
        else:
            self.current_return_type = None
        if isinstance(expr.body, Block):
            self._analyze_block(expr.body)
        else:
            self._analyze_expr(expr.body)
        self._pop_scope()
        self.current_return_type = prev_return_type

    def _analyze_call(self, expr: CallExpr):
        self._analyze_expr(expr.callee)
        for arg in expr.args:
            self._analyze_expr(arg)

        # Check if this is a constructor call: foo(args) where foo is a class name
        if isinstance(expr.callee, Identifier) and expr.callee.name in self.class_table:
            cls = self.class_table[expr.callee.name]
            self._validate_constructor_args(cls, expr.args, expr.line, expr.col)
        # Check function call arity
        elif isinstance(expr.callee, Identifier) and expr.callee.name in self.function_table:
            func = self.function_table[expr.callee.name]
            if func.body is not None:  # skip forward declarations
                self._validate_call_arity(func.name, func.params, expr.args, expr.line, expr.col)
        # Check method call arity on user-defined classes
        elif isinstance(expr.callee, FieldAccessExpr):
            obj_type = self._infer_type(expr.callee.obj)
            if obj_type and obj_type.base in self.class_table:
                cls = self.class_table[obj_type.base]
                method_name = expr.callee.field
                if method_name in cls.methods:
                    method = cls.methods[method_name]
                    self._validate_call_arity(
                        f"{cls.name}.{method_name}", method.params, expr.args,
                        expr.line, expr.col
                    )

        # When Map.keys() or Map.values() is called, ensure the corresponding
        # List<K> or List<V> generic instance is registered for codegen.
        if isinstance(expr.callee, FieldAccessExpr):
            obj_type = self._infer_type(expr.callee.obj)
            if obj_type and obj_type.base == "Map" and len(obj_type.generic_args) == 2:
                method = expr.callee.field
                if method == "keys":
                    list_type = TypeExpr(base="List", generic_args=[obj_type.generic_args[0]])
                    self._collect_generic_instances(list_type)
                elif method == "values":
                    list_type = TypeExpr(base="List", generic_args=[obj_type.generic_args[1]])
                    self._collect_generic_instances(list_type)

    def _validate_call_arity(self, name: str, params: list, args: list, line: int, col: int):
        """Validate argument count for function/method calls."""
        required = sum(1 for p in params if p.default is None)
        max_args = len(params)
        if len(args) < required:
            self._error(f"'{name}()' expects at least {required} argument(s) but got {len(args)}", line, col)
        elif len(args) > max_args:
            self._error(f"'{name}()' expects at most {max_args} argument(s) but got {len(args)}", line, col)

    def _validate_constructor_args(self, cls: ClassInfo, args: list, line: int, col: int):
        """Validate argument count for constructor calls."""
        if cls.constructor is None:
            if len(args) > 0:
                self._error(f"Class '{cls.name}' has no constructor but was called with "
                            f"{len(args)} argument(s)", line, col)
            return
        params = cls.constructor.params
        required = sum(1 for p in params if p.default is None)
        max_args = len(params)
        if len(args) < required:
            self._error(f"Constructor '{cls.name}()' expects at least {required} "
                        f"argument(s) but got {len(args)}", line, col)
        elif len(args) > max_args:
            self._error(f"Constructor '{cls.name}()' expects at most {max_args} "
                        f"argument(s) but got {len(args)}", line, col)

    def _analyze_field_access(self, expr: FieldAccessExpr):
        self._analyze_expr(expr.obj)

        # Check access control
        obj_type = self._infer_type(expr.obj)
        if obj_type and obj_type.base in self.class_table:
            cls = self.class_table[obj_type.base]
            # Check if this is a property access
            if expr.field in cls.properties:
                prop = cls.properties[expr.field]
                if prop.access == "private":
                    if self.current_class is None or self.current_class.name != cls.name:
                        self._error(
                            f"Cannot access private property '{expr.field}' of class '{cls.name}'",
                            expr.line, expr.col
                        )
                return
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
            else:
                # Field does not exist on this class
                self._error(
                    f"Class '{cls.name}' has no field or method '{expr.field}'",
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

    # Expected generic parameter counts for builtin types
    _BUILTIN_GENERIC_COUNTS = {"List": 1, "Map": 2, "Array": 1, "Set": 1}

    def _collect_generic_instances(self, type_expr: TypeExpr):
        if type_expr is None:
            return
        if type_expr.generic_args:
            key = type_expr.base
            args_tuple = tuple(type_expr.generic_args)
            # Validate generic argument count
            expected = self._BUILTIN_GENERIC_COUNTS.get(key)
            if expected is None and key in self.class_table:
                expected = len(self.class_table[key].generic_params) or None
            if expected is not None and len(type_expr.generic_args) != expected:
                self._error(
                    f"Type '{key}' expects {expected} generic argument(s) "
                    f"but got {len(type_expr.generic_args)}",
                    getattr(type_expr, 'line', 0),
                    getattr(type_expr, 'col', 0)
                )
            if key not in self.generic_instances:
                self.generic_instances[key] = []
            # Avoid duplicates
            existing = [t for t in self.generic_instances[key]]
            if args_tuple not in existing:
                self.generic_instances[key].append(args_tuple)
            # For Map<K,V>, always register List<K> and List<V> so that
            # keys() and values() functions can be emitted.
            if key == "Map" and len(type_expr.generic_args) == 2:
                k_type, v_type = type_expr.generic_args
                self._collect_generic_instances(TypeExpr(base="List", generic_args=[k_type]))
                self._collect_generic_instances(TypeExpr(base="List", generic_args=[v_type]))
            # For Set<T>, register List<T> so that toList() can be emitted.
            if key == "Set" and len(type_expr.generic_args) == 1:
                self._collect_generic_instances(TypeExpr(base="List", generic_args=[type_expr.generic_args[0]]))
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
                if expr.field in cls.properties:
                    return cls.properties[expr.field].type
                if expr.field in cls.fields:
                    return cls.fields[expr.field].type
            return None
        elif isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                if expr.callee.name in self.class_table:
                    return TypeExpr(base=expr.callee.name, pointer_depth=1)
                if expr.callee.name in self.function_table:
                    return self.function_table[expr.callee.name].return_type
            # Method call on an object: check for string methods, Map methods, and class methods
            if isinstance(expr.callee, FieldAccessExpr):
                obj_type = self._infer_type(expr.callee.obj)
                # Numeric/bool .toString()
                if obj_type and obj_type.base in ("int", "float", "double", "long", "bool") and obj_type.pointer_depth == 0:
                    if expr.callee.field == "toString":
                        return TypeExpr(base="string")
                if obj_type and (obj_type.base == "string" or
                    (obj_type.base == "char" and obj_type.pointer_depth >= 1)):
                    return self._string_method_return_type(expr.callee.field)
                # Map method return types
                if obj_type and obj_type.base == "Map" and len(obj_type.generic_args) == 2:
                    return self._map_method_return_type(expr.callee.field, obj_type)
                # List method return types
                if obj_type and obj_type.base == "List" and obj_type.generic_args:
                    return self._list_method_return_type(expr.callee.field, obj_type)
                # Set method return types
                if obj_type and obj_type.base == "Set" and obj_type.generic_args:
                    return self._set_method_return_type(expr.callee.field, obj_type)
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
            if obj_type and obj_type.base == "Map" and obj_type.generic_args and len(obj_type.generic_args) == 2:
                return obj_type.generic_args[1]
            return None
        elif isinstance(expr, BinaryExpr):
            left_type = self._infer_type(expr.left)
            right_type = self._infer_type(expr.right)
            if expr.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
                return TypeExpr(base="bool")
            if left_type and right_type:
                # Type promotion: double > float > long > int
                if left_type.base == "double" or right_type.base == "double":
                    return TypeExpr(base="double")
                if left_type.base == "float" or right_type.base == "float":
                    return TypeExpr(base="float")
                if left_type.base == "long" or right_type.base == "long":
                    return TypeExpr(base="long")
                if left_type.base == "int" and right_type.base == "int":
                    return TypeExpr(base="int")
            return left_type or right_type
        elif isinstance(expr, CastExpr):
            return expr.target_type
        elif isinstance(expr, UnaryExpr):
            return self._infer_type(expr.operand)
        elif isinstance(expr, TernaryExpr):
            return self._infer_type(expr.true_expr)
        elif isinstance(expr, AssignExpr):
            return self._infer_type(expr.target)
        elif isinstance(expr, LambdaExpr):
            # Return a function-pointer marker type: __fn_ptr<ret_type, param_types...>
            if expr.return_type:
                ret = expr.return_type
            else:
                ret = self._infer_lambda_return(expr)
            param_types = [p.type for p in expr.params]
            return TypeExpr(base="__fn_ptr", generic_args=[ret] + param_types)
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
        _STR_INT = TypeExpr(base="int")
        _STR_BOOL = TypeExpr(base="bool")
        _STR_STRING = TypeExpr(base="string")
        _STR_CHAR = TypeExpr(base="char")
        _STR_FLOAT = TypeExpr(base="float")
        string_methods = {
            # length
            "len": _STR_INT, "byteLen": _STR_INT, "charLen": _STR_INT,
            # search
            "contains": _STR_BOOL, "startsWith": _STR_BOOL, "endsWith": _STR_BOOL,
            "equals": _STR_BOOL, "indexOf": _STR_INT, "lastIndexOf": _STR_INT,
            "find": _STR_INT, "count": _STR_INT,
            # char access
            "charAt": _STR_CHAR,
            # transform
            "substring": _STR_STRING, "trim": _STR_STRING, "lstrip": _STR_STRING,
            "rstrip": _STR_STRING, "toUpper": _STR_STRING, "toLower": _STR_STRING,
            "replace": _STR_STRING, "repeat": _STR_STRING,
            "capitalize": _STR_STRING, "title": _STR_STRING, "swapCase": _STR_STRING,
            "padLeft": _STR_STRING, "padRight": _STR_STRING, "center": _STR_STRING,
            "zfill": _STR_STRING,
            # predicates (isDigit/isAlpha are single-char — use Strings.isDigit(c))
            "isBlank": _STR_BOOL, "isAlnum": _STR_BOOL,
            "isDigitStr": _STR_BOOL, "isAlphaStr": _STR_BOOL,
            "isUpper": _STR_BOOL, "isLower": _STR_BOOL,
            # conversion
            "toInt": _STR_INT, "toFloat": _STR_FLOAT,
            "toDouble": TypeExpr(base="double"), "toLong": TypeExpr(base="long"),
            "toBool": _STR_BOOL,
            # new methods
            "reverse": _STR_STRING, "isEmpty": _STR_BOOL,
            "removePrefix": _STR_STRING, "removeSuffix": _STR_STRING,
            # split returns char** (string array)
            "split": TypeExpr(base="string", pointer_depth=1),
        }
        return string_methods.get(method_name)

    def _map_method_return_type(self, method_name: str, map_type: TypeExpr) -> TypeExpr | None:
        """Return the type of a Map method call."""
        k_type = map_type.generic_args[0]
        v_type = map_type.generic_args[1]
        if method_name in ("get", "getOrDefault"):
            return v_type
        elif method_name in ("has", "contains", "containsValue"):
            return TypeExpr(base="bool")
        elif method_name == "keys":
            return TypeExpr(base="List", generic_args=[k_type])
        elif method_name == "values":
            return TypeExpr(base="List", generic_args=[v_type])
        elif method_name in ("put", "remove", "free", "clear", "forEach", "putIfAbsent", "merge"):
            return TypeExpr(base="void")
        elif method_name == "size":
            return TypeExpr(base="int")
        elif method_name == "isEmpty":
            return TypeExpr(base="bool")
        return None

    def _list_method_return_type(self, method_name: str, list_type: TypeExpr) -> TypeExpr | None:
        """Return the type of a List method call."""
        elem_type = list_type.generic_args[0]
        if method_name in ("get", "pop", "first", "last", "reduce", "min", "max", "sum"):
            return elem_type
        elif method_name in ("contains", "any", "all"):
            return TypeExpr(base="bool")
        elif method_name in ("indexOf", "lastIndexOf", "count", "findIndex"):
            return TypeExpr(base="int")
        elif method_name in ("slice", "subList", "filter", "sorted", "distinct", "reversed", "take", "drop"):
            return TypeExpr(base="List", generic_args=[elem_type])
        elif method_name in ("join", "joinToString"):
            return TypeExpr(base="string")
        elif method_name in ("push", "set", "remove", "removeAt", "reverse", "sort", "clear", "free", "forEach", "extend", "addAll", "insert", "fill", "removeAll", "swap"):
            return TypeExpr(base="void")
        elif method_name == "size":
            return TypeExpr(base="int")
        elif method_name == "isEmpty":
            return TypeExpr(base="bool")
        elif method_name == "map":
            return TypeExpr(base="List", generic_args=[elem_type])
        return None

    def _set_method_return_type(self, method_name: str, set_type: TypeExpr) -> TypeExpr | None:
        """Return the type of a Set method call."""
        elem_type = set_type.generic_args[0]
        if method_name in ("contains", "has"):
            return TypeExpr(base="bool")
        elif method_name == "toList":
            return TypeExpr(base="List", generic_args=[elem_type])
        elif method_name in ("add", "remove", "free", "clear", "forEach"):
            return TypeExpr(base="void")
        elif method_name == "filter":
            return TypeExpr(base="Set", generic_args=[elem_type])
        elif method_name in ("any", "all"):
            return TypeExpr(base="bool")
        elif method_name == "size":
            return TypeExpr(base="int")
        elif method_name == "isEmpty":
            return TypeExpr(base="bool")
        elif method_name in ("unite", "intersect", "subtract", "symmetricDifference", "copy"):
            return TypeExpr(base="Set", generic_args=[elem_type])
        elif method_name in ("isSubsetOf", "isSupersetOf"):
            return TypeExpr(base="bool")
        return None

    def _infer_lambda_return(self, expr: LambdaExpr) -> TypeExpr:
        """Infer the return type of a lambda from its body."""
        if isinstance(expr.body, Block):
            for stmt in expr.body.statements:
                if isinstance(stmt, ReturnStmt) and stmt.value:
                    t = self._infer_type(stmt.value)
                    if t:
                        return t
        return TypeExpr(base="int")  # default fallback

    def _get_element_type(self, iter_type: TypeExpr | None, line: int, col: int) -> TypeExpr | None:
        """Get the element type for for-in iteration."""
        if iter_type is None:
            return None

        if iter_type.base in ("List", "Array", "Set") and iter_type.generic_args:
            return iter_type.generic_args[0]

        # String iteration: each element is a char
        if iter_type.base == "string" or (iter_type.base == "char" and iter_type.pointer_depth >= 1):
            return TypeExpr(base="char")

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
        if iter_type.base in ("int", "float", "double", "bool"):
            self._error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None

        return None

    def _format_type(self, t: TypeExpr) -> str:
        """Format a TypeExpr for error messages, e.g. 'List<int>', 'string*'."""
        result = t.base
        if t.generic_args:
            args = ", ".join(self._format_type(a) for a in t.generic_args)
            result += f"<{args}>"
        result += "*" * t.pointer_depth
        return result

    def _types_compatible(self, target: TypeExpr, source: TypeExpr) -> bool:
        """Check if source type can be assigned to target type."""
        # Same base type is always compatible
        if target.base == source.base:
            return True
        # Numeric types are mutually compatible (int/float/double/char)
        numeric = {"int", "float", "double", "char"}
        if target.base in numeric and source.base in numeric:
            return True
        # string and char* are compatible
        if target.base == "string" and source.base == "char" and source.pointer_depth >= 1:
            return True
        if source.base == "string" and target.base == "char" and target.pointer_depth >= 1:
            return True
        # null/void* can be assigned to any pointer type or string
        if source.base == "null" or (source.base == "void" and source.pointer_depth > 0):
            return target.pointer_depth > 0 or target.base == "string"
        # Class types: check inheritance
        if target.base in self.class_table and source.base in self.class_table:
            return self._is_subclass(source.base, target.base)
        # Collections: must match exactly
        collections = {"Map", "List", "Set", "Array"}
        if target.base in collections and source.base in collections:
            return target.base == source.base
        # Known incompatible: string ↔ numeric, bool ↔ string, etc.
        all_known = numeric | {"string", "bool", "void"} | collections
        if target.base in all_known and source.base in all_known:
            return False  # Both types are known, and they don't match any rule above
        # Unknown types (C headers, etc.) — be permissive
        return True

    def _is_subclass(self, child: str, parent: str) -> bool:
        """Check if child class extends parent (directly or transitively)."""
        if child == parent:
            return True
        info = self.class_table.get(child)
        visited = set()
        while info and info.parent and info.parent not in visited:
            visited.add(info.parent)
            if info.parent == parent:
                return True
            info = self.class_table.get(info.parent)
        return False
