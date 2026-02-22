"""C code generator for the btrc language.

Transforms an analyzed AST into C source code.
"""

from __future__ import annotations
from .ast_nodes import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BraceInitializer,
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
    Param,
    ParallelForStmt,
    PreprocessorDirective,
    Program,
    PropertyDecl,
    ReturnStmt,
    SelfExpr,
    SizeofExpr,
    StringLiteral,
    StructDecl,
    SwitchStmt,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    TupleLiteral,
    TypedefDecl,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from .analyzer import AnalyzedProgram, ClassInfo


class CodeGen:
    def __init__(self, analyzed: AnalyzedProgram, debug: bool = False, source_file: str = ""):
        self.analyzed = analyzed
        self.class_table = analyzed.class_table
        self.generic_instances = analyzed.generic_instances
        self.output: list[str] = []
        self.indent_level = 0
        self.node_types: dict[int, TypeExpr] = analyzed.node_types
        self.gpu_shaders: list[tuple[str, str]] = []  # (name, glsl_source)
        self.current_class: ClassInfo | None = None
        # in_constructor flag removed — self is always a pointer now
        self.debug = debug
        self.source_file = source_file
        self._fstr_counter: int = 0
        self._lambda_counter: int = 0
        self._step_counter: int = 0
        self._lambda_defs: list[str] = []  # collected lambda function definitions
        self._emitted_globals: set[int] = set()  # track already-emitted globals
        self._hash_str_emitted: bool = False  # track if __btrc_hash_str was emitted
        self._tmp_counter: int = 0  # temp variable counter for safe expression evaluation

    def generate(self) -> str:
        # Collect user includes and determine needed auto-includes
        self._collect_user_includes()
        # Pre-scan for lambdas so their definitions can be emitted before use
        self._prescan_lambdas()
        self._emit_header()
        self._emit_forward_declarations()       # typedef struct Foo Foo;
        self._emit_generic_struct_typedefs()     # btrc_List_Foo struct (pointers only)
        self._emit_struct_definitions()          # full struct bodies
        self._emit_destroy_forward_declarations()  # void Foo_destroy(Foo* self);
        self._emit_generic_function_bodies()     # List/Map function implementations
        # Emit globals/enums first so lambdas can reference them
        self._emit_globals_and_enums()
        # Forward declare all user functions (enables mutual recursion)
        self._emit_function_forward_declarations()
        # Emit lambda function definitions (before user declarations that reference them)
        for ldef in self._lambda_defs:
            self._emit_raw(ldef)
        self._emit_declarations()                # class methods, functions, etc.
        return "\n".join(self.output) + "\n"

    # ---- Output helpers ----

    def _emit(self, line: str = ""):
        if line:
            self.output.append("    " * self.indent_level + line)
        else:
            self.output.append("")

    def _emit_raw(self, line: str):
        self.output.append(line)

    def _emit_line_directive(self, line: int):
        """Emit a #line directive for source-level debugging when debug mode is enabled."""
        if self.debug and line > 0:
            self._emit_raw(f'#line {line} "{self.source_file}"')

    # ---- Lambda pre-scan ----

    def _prescan_lambdas(self):
        """Walk the AST to find all LambdaExpr nodes and pre-generate their C functions."""
        self._walk_for_lambdas(self.analyzed.program)

    def _walk_for_lambdas(self, node):
        """Recursively walk AST to find and process LambdaExpr nodes."""
        if node is None:
            return
        if isinstance(node, LambdaExpr):
            self._register_lambda(node)
        # Walk children
        for attr in ('declarations', 'members', 'statements', 'args', 'elements', 'cases',
                     'entries', 'parts'):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for item in child:
                    if isinstance(item, tuple):
                        for sub in item:
                            if hasattr(sub, '__dict__'):
                                self._walk_for_lambdas(sub)
                    elif hasattr(item, '__dict__'):
                        self._walk_for_lambdas(item)
        for attr in ('body', 'left', 'right', 'operand', 'callee', 'obj', 'expr', 'value',
                     'target', 'condition', 'true_expr', 'false_expr', 'iterable',
                     'init', 'update', 'initializer', 'index', 'then_block', 'else_block',
                     'try_block', 'catch_block', 'getter_body', 'setter_body'):
            child = getattr(node, attr, None)
            if child is not None and hasattr(child, '__dict__'):
                self._walk_for_lambdas(child)

    def _register_lambda(self, expr: LambdaExpr):
        """Pre-generate a C function for a lambda and assign it a name."""
        self._lambda_counter += 1
        name = f"__btrc_lambda_{self._lambda_counter}"
        # Store the name on the LambdaExpr node for later reference in _expr_to_c
        expr._c_name = name

        # Determine return type
        if expr.return_type:
            ret_type = self._type_to_c(expr.return_type)
        else:
            # Try to infer from body (single return statement)
            ret_type = self._infer_lambda_return_type(expr)

        # Build parameter list
        params = []
        for p in expr.params:
            params.append(self._param_to_c(p))
        params_str = ", ".join(params) if params else "void"

        # Generate function body
        lines = []
        lines.append(f"static {ret_type} {name}({params_str}) {{")
        if isinstance(expr.body, Block):
            # Save and restore codegen state
            saved_output = self.output
            saved_indent = self.indent_level
            self.output = []
            self.indent_level = 1
            self._emit_block_contents(expr.body)
            body_lines = self.output
            self.output = saved_output
            self.indent_level = saved_indent
            lines.extend(body_lines)
        lines.append("}")
        lines.append("")

        self._lambda_defs.append("\n".join(lines))

    def _infer_lambda_return_type(self, expr: LambdaExpr) -> str:
        """Infer the return type of a lambda from its body."""
        if isinstance(expr.body, Block) and expr.body.statements:
            for stmt in expr.body.statements:
                if isinstance(stmt, ReturnStmt) and stmt.value:
                    t = self.node_types.get(id(stmt.value))
                    if t:
                        return self._type_to_c(t)
        return "int"  # default fallback

    # ---- Include management ----

    # Map of known functions/identifiers to the headers they need
    _INCLUDE_MAPPINGS = {
        # stdio.h
        "printf": "<stdio.h>", "fprintf": "<stdio.h>", "sprintf": "<stdio.h>",
        "snprintf": "<stdio.h>", "scanf": "<stdio.h>", "fscanf": "<stdio.h>",
        "sscanf": "<stdio.h>", "fopen": "<stdio.h>", "fclose": "<stdio.h>",
        "fread": "<stdio.h>", "fwrite": "<stdio.h>", "fgets": "<stdio.h>",
        "fputs": "<stdio.h>", "puts": "<stdio.h>", "getchar": "<stdio.h>",
        "putchar": "<stdio.h>", "perror": "<stdio.h>", "fflush": "<stdio.h>",
        "fseek": "<stdio.h>", "ftell": "<stdio.h>", "rewind": "<stdio.h>",
        "remove": "<stdio.h>", "rename": "<stdio.h>", "tmpfile": "<stdio.h>",
        # stdlib.h
        "malloc": "<stdlib.h>", "calloc": "<stdlib.h>", "realloc": "<stdlib.h>",
        "free": "<stdlib.h>", "exit": "<stdlib.h>", "abort": "<stdlib.h>",
        "atoi": "<stdlib.h>", "atof": "<stdlib.h>", "atol": "<stdlib.h>",
        "strtol": "<stdlib.h>", "strtod": "<stdlib.h>", "rand": "<stdlib.h>",
        "srand": "<stdlib.h>", "abs": "<stdlib.h>", "qsort": "<stdlib.h>",
        "bsearch": "<stdlib.h>", "system": "<stdlib.h>",
        # math.h
        "sin": "<math.h>", "cos": "<math.h>", "tan": "<math.h>",
        "asin": "<math.h>", "acos": "<math.h>", "atan": "<math.h>",
        "atan2": "<math.h>", "sqrt": "<math.h>", "pow": "<math.h>",
        "exp": "<math.h>", "log": "<math.h>", "log2": "<math.h>",
        "log10": "<math.h>", "ceil": "<math.h>", "floor": "<math.h>",
        "round": "<math.h>", "fabs": "<math.h>", "fmod": "<math.h>",
        "hypot": "<math.h>",
        # string.h
        "strlen": "<string.h>", "strcmp": "<string.h>", "strncmp": "<string.h>",
        "strcpy": "<string.h>", "strncpy": "<string.h>", "strcat": "<string.h>",
        "strncat": "<string.h>", "strstr": "<string.h>", "strchr": "<string.h>",
        "strrchr": "<string.h>", "memset": "<string.h>", "memcpy": "<string.h>",
        "memmove": "<string.h>", "memcmp": "<string.h>", "strdup": "<string.h>",
        "strtok": "<string.h>",
        # ctype.h
        "isalpha": "<ctype.h>", "isdigit": "<ctype.h>", "isalnum": "<ctype.h>",
        "isspace": "<ctype.h>", "toupper": "<ctype.h>", "tolower": "<ctype.h>",
        "isupper": "<ctype.h>", "islower": "<ctype.h>", "isprint": "<ctype.h>",
        "ispunct": "<ctype.h>",
        # assert.h
        "assert": "<assert.h>",
        # time.h
        "time": "<time.h>", "clock": "<time.h>", "difftime": "<time.h>",
        "mktime": "<time.h>", "strftime": "<time.h>",
    }

    def _collect_user_includes(self):
        """Scan user preprocessor directives to find explicit includes."""
        self.user_includes: set[str] = set()
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, PreprocessorDirective):
                text = decl.text.strip()
                if text.startswith("#include"):
                    # Extract the include path
                    rest = text[len("#include"):].strip()
                    self.user_includes.add(rest)

    def _walk_for_includes(self, node, needed: set[str]):
        """Recursively walk AST to find function calls that need headers."""
        if node is None:
            return
        if isinstance(node, CallExpr):
            if isinstance(node.callee, Identifier):
                header = self._INCLUDE_MAPPINGS.get(node.callee.name)
                if header:
                    needed.add(header)
            for arg in node.args:
                self._walk_for_includes(arg, needed)
            self._walk_for_includes(node.callee, needed)
            return
        if isinstance(node, Program):
            for d in node.declarations:
                self._walk_for_includes(d, needed)
            return
        if isinstance(node, (FunctionDecl, MethodDecl)):
            if node.body:
                self._walk_for_includes(node.body, needed)
            return
        if isinstance(node, ClassDecl):
            for m in node.members:
                self._walk_for_includes(m, needed)
            return
        if isinstance(node, Block):
            for s in node.statements:
                self._walk_for_includes(s, needed)
            return
        # Statements
        if isinstance(node, (ExprStmt, ReturnStmt, DeleteStmt)):
            self._walk_for_includes(getattr(node, 'expr', None) or getattr(node, 'value', None), needed)
            return
        if isinstance(node, VarDeclStmt):
            self._walk_for_includes(node.initializer, needed)
            return
        if isinstance(node, IfStmt):
            self._walk_for_includes(node.condition, needed)
            self._walk_for_includes(node.then_block, needed)
            self._walk_for_includes(node.else_block, needed)
            return
        if isinstance(node, (WhileStmt, DoWhileStmt)):
            self._walk_for_includes(node.condition, needed)
            self._walk_for_includes(node.body, needed)
            return
        if isinstance(node, (ForInStmt, ParallelForStmt)):
            self._walk_for_includes(node.iterable, needed)
            self._walk_for_includes(node.body, needed)
            return
        if isinstance(node, CForStmt):
            self._walk_for_includes(node.init, needed)
            self._walk_for_includes(node.condition, needed)
            self._walk_for_includes(node.update, needed)
            self._walk_for_includes(node.body, needed)
            return
        if isinstance(node, SwitchStmt):
            self._walk_for_includes(node.value, needed)
            for case in node.cases:
                for s in case.body:
                    self._walk_for_includes(s, needed)
            return
        if isinstance(node, TryCatchStmt):
            self._walk_for_includes(node.try_block, needed)
            self._walk_for_includes(node.catch_block, needed)
            return
        if isinstance(node, ThrowStmt):
            self._walk_for_includes(node.expr, needed)
            return
        # Expressions
        if isinstance(node, BinaryExpr):
            self._walk_for_includes(node.left, needed)
            self._walk_for_includes(node.right, needed)
            return
        if isinstance(node, UnaryExpr):
            self._walk_for_includes(node.operand, needed)
            return
        if isinstance(node, AssignExpr):
            self._walk_for_includes(node.target, needed)
            self._walk_for_includes(node.value, needed)
            return
        if isinstance(node, TernaryExpr):
            self._walk_for_includes(node.condition, needed)
            self._walk_for_includes(node.true_expr, needed)
            self._walk_for_includes(node.false_expr, needed)
            return
        if isinstance(node, IndexExpr):
            self._walk_for_includes(node.obj, needed)
            self._walk_for_includes(node.index, needed)
            return
        if isinstance(node, FieldAccessExpr):
            self._walk_for_includes(node.obj, needed)
            return
        if isinstance(node, CastExpr):
            self._walk_for_includes(node.expr, needed)
            return
        if isinstance(node, SizeofExpr):
            if not isinstance(node.operand, TypeExpr):
                self._walk_for_includes(node.operand, needed)
            return
        if isinstance(node, NewExpr):
            for a in node.args:
                self._walk_for_includes(a, needed)
            return
        if isinstance(node, FStringLiteral):
            for kind, val in node.parts:
                if kind == "expr":
                    self._walk_for_includes(val, needed)
            return
        if isinstance(node, TupleLiteral):
            for el in node.elements:
                self._walk_for_includes(el, needed)
            return

    # ---- Header ----

    def _emit_header(self):
        self._emit("/* Generated by btrc */")
        # Always-included headers
        always_include = {"<stdio.h>", "<stdlib.h>", "<stdbool.h>", "<string.h>"}
        # Find additional needed headers by walking the AST
        needed: set[str] = set()
        self._walk_for_includes(self.analyzed.program, needed)
        # Check if string helpers are needed
        self._needs_string_helpers = self._check_needs_string_helpers()
        if self._needs_string_helpers:
            # ctype.h must be in always_include because string helpers are
            # emitted before user code — a user #include <ctype.h> would
            # come too late.
            always_include.add("<ctype.h>")
        self._needs_math_helpers = self._check_needs_math_helpers()
        if self._needs_math_helpers:
            always_include.add("<math.h>")
        self._needs_try_catch = self._check_needs_try_catch()
        if self._needs_try_catch:
            needed.add("<setjmp.h>")
        # Always emit the core runtime headers unconditionally — generic
        # instantiations (Map/List) are emitted before user declarations,
        # so these must appear first even if the user also #includes them.
        # Duplicate includes are harmless due to include guards.
        for header in sorted(always_include):
            self._emit(f"#include {header}")
        # Emit additional needed headers only if user didn't include them
        for header in sorted(needed - always_include):
            if header not in self.user_includes:
                self._emit(f"#include {header}")
        self._emit()
        # Always emit div/mod safety helpers (lightweight, always needed)
        self._emit_divmod_helpers()
        if self._needs_string_helpers:
            self._emit_string_helpers()
        if self._needs_math_helpers:
            self._emit_math_helpers()
        if self._needs_try_catch:
            self._emit_try_catch_runtime()

    def _emit_divmod_helpers(self):
        """Emit division/modulo by zero runtime checks."""
        self._emit("static inline int __btrc_div_int(int a, int b) {")
        self._emit("    if (b == 0) { fprintf(stderr, \"Division by zero\\n\"); exit(1); }")
        self._emit("    return a / b;")
        self._emit("}")
        self._emit("static inline double __btrc_div_double(double a, double b) {")
        self._emit("    if (b == 0.0) { fprintf(stderr, \"Division by zero\\n\"); exit(1); }")
        self._emit("    return a / b;")
        self._emit("}")
        self._emit("static inline int __btrc_mod_int(int a, int b) {")
        self._emit("    if (b == 0) { fprintf(stderr, \"Modulo by zero\\n\"); exit(1); }")
        self._emit("    return a % b;")
        self._emit("}")
        self._emit()

    def _check_needs_string_helpers(self) -> bool:
        """Check if the AST uses any string methods that require helper functions."""
        return self._walk_for_string_methods(self.analyzed.program)

    def _walk_for_string_methods(self, node) -> bool:
        if node is None:
            return False
        if isinstance(node, CallExpr) and isinstance(node.callee, FieldAccessExpr):
            method = node.callee.field
            if method in ("substring", "trim", "toUpper", "toLower", "indexOf", "lastIndexOf",
                         "replace", "split", "charLen", "repeat", "count", "find", "lstrip",
                         "rstrip", "capitalize", "title", "swapCase", "padLeft", "padRight",
                         "center", "isBlank", "isAlnum", "charAt",
                         "reverse", "isEmpty", "removePrefix", "removeSuffix",
                         "isDigitStr", "isAlphaStr", "isUpper", "isLower",
                         "contains", "startsWith", "endsWith", "zfill"):
                obj_type = self.node_types.get(id(node.callee.obj))
                if obj_type and (obj_type.base == "string" or
                    (obj_type.base == "char" and obj_type.pointer_depth >= 1)):
                    return True
            # Detect numeric .toString() calls that need sprintf helpers
            if method == "toString":
                obj_type = self.node_types.get(id(node.callee.obj))
                if obj_type and obj_type.base in ("int", "float", "double", "long"):
                    return True
            # Detect Strings.X() static calls that need helpers
            if isinstance(node.callee.obj, Identifier) and node.callee.obj.name == "Strings":
                return True
        # String + / += / == / != require helpers
        if isinstance(node, BinaryExpr) and node.op in ("+", "==", "!="):
            left_type = self.node_types.get(id(node.left))
            if left_type and left_type.base == "string":
                return True
        if isinstance(node, AssignExpr) and node.op == "+=":
            target_type = self.node_types.get(id(node.target))
            if target_type and target_type.base == "string":
                return True
        # Recurse into FStringLiteral expression parts
        if isinstance(node, FStringLiteral):
            for kind, val in node.parts:
                if kind == "expr" and self._walk_for_string_methods(val):
                    return True
        for attr in ('declarations', 'members', 'statements', 'body', 'then_block',
                     'else_block', 'args', 'elements', 'entries', 'cases'):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for item in child:
                    if isinstance(item, tuple):
                        for sub in item:
                            if hasattr(sub, '__dict__') and self._walk_for_string_methods(sub):
                                return True
                    elif hasattr(item, '__dict__') and self._walk_for_string_methods(item):
                        return True
            elif hasattr(child, '__dict__') and self._walk_for_string_methods(child):
                return True
        for attr in ('left', 'right', 'operand', 'callee', 'obj', 'expr', 'value',
                     'target', 'condition', 'true_expr', 'false_expr', 'iterable',
                     'init', 'update', 'initializer', 'index'):
            child = getattr(node, attr, None)
            if child is not None and hasattr(child, '__dict__') and self._walk_for_string_methods(child):
                return True
        return False

    def _emit_string_helpers(self):
        """Emit helper functions for string methods."""
        self._emit("/* btrc string helper functions */")
        # substring(s, start, len)
        self._emit("static inline char* __btrc_substring(const char* s, int start, int len) {")
        self._emit("    int slen = (int)strlen(s);")
        self._emit("    if (start < 0) start = 0;")
        self._emit("    if (start > slen) start = slen;")
        self._emit("    if (start + len > slen) len = slen - start;")
        self._emit("    if (len < 0) len = 0;")
        self._emit("    char* result = (char*)malloc(len + 1);")
        self._emit("    strncpy(result, s + start, len);")
        self._emit("    result[len] = '\\0';")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # trim(s)
        self._emit("static inline char* __btrc_trim(const char* s) {")
        self._emit("    while (*s && isspace((unsigned char)*s)) s++;")
        self._emit("    if (*s == '\\0') { char* r = (char*)malloc(1); r[0]='\\0'; return r; }")
        self._emit("    const char* end = s + strlen(s) - 1;")
        self._emit("    while (end > s && isspace((unsigned char)*end)) end--;")
        self._emit("    int len = (int)(end - s + 1);")
        self._emit("    char* result = (char*)malloc(len + 1);")
        self._emit("    strncpy(result, s, len);")
        self._emit("    result[len] = '\\0';")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # toUpper(s)
        self._emit("static inline char* __btrc_toUpper(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    char* result = (char*)malloc(len + 1);")
        self._emit("    for (int i = 0; i < len; i++) result[i] = (char)toupper((unsigned char)s[i]);")
        self._emit("    result[len] = '\\0';")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # toLower(s)
        self._emit("static inline char* __btrc_toLower(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    char* result = (char*)malloc(len + 1);")
        self._emit("    for (int i = 0; i < len; i++) result[i] = (char)tolower((unsigned char)s[i]);")
        self._emit("    result[len] = '\\0';")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # utf8 charLen(s) — count UTF-8 code points
        self._emit("static inline int __btrc_utf8_charlen(const char* s) {")
        self._emit("    int count = 0;")
        self._emit("    while (*s) {")
        self._emit("        if ((*s & 0xC0) != 0x80) count++;")
        self._emit("        s++;")
        self._emit("    }")
        self._emit("    return count;")
        self._emit("}")
        self._emit()
        # charAt(s, index) — bounds-checked character access
        self._emit("static inline char __btrc_charAt(const char* s, int idx) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    if (idx < 0 || idx >= len) { fprintf(stderr, \"String index out of bounds: %d (length %d)\\n\", idx, len); exit(1); }")
        self._emit("    return s[idx];")
        self._emit("}")
        self._emit()
        # indexOf(s, sub)
        self._emit("static inline int __btrc_indexOf(const char* s, const char* sub) {")
        self._emit("    char* p = strstr(s, sub);")
        self._emit("    return p ? (int)(p - s) : -1;")
        self._emit("}")
        self._emit()
        # lastIndexOf(s, sub)
        self._emit("static inline int __btrc_lastIndexOf(const char* s, const char* sub) {")
        self._emit("    int slen = (int)strlen(s);")
        self._emit("    int sublen = (int)strlen(sub);")
        self._emit("    if (sublen == 0) return slen;")
        self._emit("    for (int i = slen - sublen; i >= 0; i--) {")
        self._emit("        if (strncmp(s + i, sub, sublen) == 0) return i;")
        self._emit("    }")
        self._emit("    return -1;")
        self._emit("}")
        self._emit()
        # replace(s, old, replacement)
        self._emit("static inline char* __btrc_replace(const char* s, const char* old, const char* rep) {")
        self._emit("    int slen = (int)strlen(s);")
        self._emit("    int oldlen = (int)strlen(old);")
        self._emit("    int replen = (int)strlen(rep);")
        self._emit("    if (oldlen == 0) return strdup(s);")
        self._emit("    int cap = slen * 2 + 1;")
        self._emit("    char* result = (char*)malloc(cap);")
        self._emit("    int rlen = 0, i = 0;")
        self._emit("    while (i < slen) {")
        self._emit("        if (i + oldlen <= slen && strncmp(s + i, old, oldlen) == 0) {")
        self._emit("            while (rlen + replen >= cap) { cap *= 2; result = (char*)realloc(result, cap); }")
        self._emit("            memcpy(result + rlen, rep, replen);")
        self._emit("            rlen += replen; i += oldlen;")
        self._emit("        } else {")
        self._emit("            if (rlen + 1 >= cap) { cap *= 2; result = (char*)realloc(result, cap); }")
        self._emit("            result[rlen++] = s[i++];")
        self._emit("        }")
        self._emit("    }")
        self._emit("    result[rlen] = '\\0';")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # split(s, delim) — returns char** (NULL-terminated array)
        self._emit("static inline char** __btrc_split(const char* s, const char* delim) {")
        self._emit("    int dlen = (int)strlen(delim);")
        self._emit("    if (dlen == 0) { fprintf(stderr, \"Empty delimiter in split()\\n\"); exit(1); }")
        self._emit("    int cap = 8;")
        self._emit("    char** result = (char**)malloc(sizeof(char*) * cap);")
        self._emit("    int count = 0;")
        self._emit("    const char* p = s;")
        self._emit("    while (*p) {")
        self._emit("        const char* found = strstr(p, delim);")
        self._emit("        int seglen = found ? (int)(found - p) : (int)strlen(p);")
        self._emit("        if (count + 2 > cap) { cap *= 2; result = (char**)realloc(result, sizeof(char*) * cap); }")
        self._emit("        result[count] = (char*)malloc(seglen + 1);")
        self._emit("        memcpy(result[count], p, seglen);")
        self._emit("        result[count][seglen] = '\\0';")
        self._emit("        count++;")
        self._emit("        if (!found) break;")
        self._emit("        p = found + dlen;")
        self._emit("    }")
        self._emit("    result[count] = NULL;")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # repeat(s, count) — repeat a string N times
        self._emit("static inline char* __btrc_repeat(const char* s, int count) {")
        self._emit("    if (count < 0) { fprintf(stderr, \"repeat count must be non-negative\\n\"); exit(1); }")
        self._emit("    if (count == 0) { char* r = (char*)malloc(1); r[0] = '\\0'; return r; }")
        self._emit("    int slen = (int)strlen(s);")
        self._emit("    char* result = (char*)malloc((size_t)slen * count + 1);")
        self._emit("    for (int i = 0; i < count; i++) memcpy(result + i * slen, s, slen);")
        self._emit("    result[slen * count] = '\\0';")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # reverse(s) — reverse string
        self._emit("static inline char* __btrc_reverse(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    char* r = (char*)malloc(len + 1);")
        self._emit("    for (int i = 0; i < len; i++) r[i] = s[len - 1 - i];")
        self._emit("    r[len] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # isEmpty(s) — check if string is empty
        self._emit("static inline bool __btrc_isEmpty(const char* s) {")
        self._emit("    return s[0] == '\\0';")
        self._emit("}")
        self._emit()
        # removePrefix(s, prefix) — remove prefix if present
        self._emit("static inline char* __btrc_removePrefix(const char* s, const char* prefix) {")
        self._emit("    int plen = (int)strlen(prefix);")
        self._emit("    if (strncmp(s, prefix, plen) == 0) {")
        self._emit("        int rlen = (int)strlen(s) - plen;")
        self._emit("        char* r = (char*)malloc(rlen + 1);")
        self._emit("        memcpy(r, s + plen, rlen + 1);")
        self._emit("        return r;")
        self._emit("    }")
        self._emit("    return strdup(s);")
        self._emit("}")
        self._emit()
        # removeSuffix(s, suffix) — remove suffix if present
        self._emit("static inline char* __btrc_removeSuffix(const char* s, const char* suffix) {")
        self._emit("    int slen = (int)strlen(s);")
        self._emit("    int suflen = (int)strlen(suffix);")
        self._emit("    if (slen >= suflen && strcmp(s + slen - suflen, suffix) == 0) {")
        self._emit("        int rlen = slen - suflen;")
        self._emit("        char* r = (char*)malloc(rlen + 1);")
        self._emit("        memcpy(r, s, rlen);")
        self._emit("        r[rlen] = '\\0';")
        self._emit("        return r;")
        self._emit("    }")
        self._emit("    return strdup(s);")
        self._emit("}")
        self._emit()
        # startsWith(s, prefix) — check if string starts with prefix
        self._emit("static inline bool __btrc_startsWith(const char* s, const char* prefix) {")
        self._emit("    return strncmp(s, prefix, strlen(prefix)) == 0;")
        self._emit("}")
        self._emit()
        # endsWith(s, suffix) — check if string ends with suffix
        self._emit("static inline bool __btrc_endsWith(const char* s, const char* suffix) {")
        self._emit("    int slen = (int)strlen(s);")
        self._emit("    int suflen = (int)strlen(suffix);")
        self._emit("    if (suflen > slen) return false;")
        self._emit("    return strcmp(s + slen - suflen, suffix) == 0;")
        self._emit("}")
        self._emit()
        # strContains(s, sub) — check if string contains substring
        self._emit("static inline bool __btrc_strContains(const char* s, const char* sub) {")
        self._emit("    return strstr(s, sub) != NULL;")
        self._emit("}")
        self._emit()
        # capitalize(s) — uppercase first char, lowercase rest
        self._emit("static inline char* __btrc_capitalize(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    char* r = (char*)malloc(len + 1);")
        self._emit("    for (int i = 0; i < len; i++) r[i] = tolower((unsigned char)s[i]);")
        self._emit("    if (len > 0) r[0] = toupper((unsigned char)r[0]);")
        self._emit("    r[len] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # title(s) — capitalize first letter of each word
        self._emit("static inline char* __btrc_title(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    char* r = (char*)malloc(len + 1);")
        self._emit("    int cap_next = 1;")
        self._emit("    for (int i = 0; i < len; i++) {")
        self._emit("        if (isspace((unsigned char)s[i])) { r[i] = s[i]; cap_next = 1; }")
        self._emit("        else if (cap_next) { r[i] = toupper((unsigned char)s[i]); cap_next = 0; }")
        self._emit("        else { r[i] = tolower((unsigned char)s[i]); }")
        self._emit("    }")
        self._emit("    r[len] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # swapCase(s) — swap upper/lower case
        self._emit("static inline char* __btrc_swapCase(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    char* r = (char*)malloc(len + 1);")
        self._emit("    for (int i = 0; i < len; i++) {")
        self._emit("        if (isupper((unsigned char)s[i])) r[i] = tolower((unsigned char)s[i]);")
        self._emit("        else if (islower((unsigned char)s[i])) r[i] = toupper((unsigned char)s[i]);")
        self._emit("        else r[i] = s[i];")
        self._emit("    }")
        self._emit("    r[len] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # padLeft(s, width, fill) — left-pad string
        self._emit("static inline char* __btrc_padLeft(const char* s, int width, char fill) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    if (len >= width) { char* r = (char*)malloc(len + 1); strcpy(r, s); return r; }")
        self._emit("    char* r = (char*)malloc(width + 1);")
        self._emit("    int pad = width - len;")
        self._emit("    memset(r, fill, pad);")
        self._emit("    memcpy(r + pad, s, len);")
        self._emit("    r[width] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # padRight(s, width, fill) — right-pad string
        self._emit("static inline char* __btrc_padRight(const char* s, int width, char fill) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    if (len >= width) { char* r = (char*)malloc(len + 1); strcpy(r, s); return r; }")
        self._emit("    char* r = (char*)malloc(width + 1);")
        self._emit("    memcpy(r, s, len);")
        self._emit("    memset(r + len, fill, width - len);")
        self._emit("    r[width] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # center(s, width, fill) — center string with padding
        self._emit("static inline char* __btrc_center(const char* s, int width, char fill) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    if (len >= width) { char* r = (char*)malloc(len + 1); strcpy(r, s); return r; }")
        self._emit("    char* r = (char*)malloc(width + 1);")
        self._emit("    int left = (width - len) / 2;")
        self._emit("    int right = width - len - left;")
        self._emit("    memset(r, fill, left);")
        self._emit("    memcpy(r + left, s, len);")
        self._emit("    memset(r + left + len, fill, right);")
        self._emit("    r[width] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # lstrip(s) — strip leading whitespace
        self._emit("static inline char* __btrc_lstrip(const char* s) {")
        self._emit("    while (*s && isspace((unsigned char)*s)) s++;")
        self._emit("    char* r = (char*)malloc(strlen(s) + 1);")
        self._emit("    strcpy(r, s);")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # rstrip(s) — strip trailing whitespace
        self._emit("static inline char* __btrc_rstrip(const char* s) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    while (len > 0 && isspace((unsigned char)s[len - 1])) len--;")
        self._emit("    char* r = (char*)malloc(len + 1);")
        self._emit("    memcpy(r, s, len);")
        self._emit("    r[len] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # count(s, sub) — count non-overlapping occurrences
        self._emit("static inline int __btrc_count(const char* s, const char* sub) {")
        self._emit("    int count = 0;")
        self._emit("    int sublen = (int)strlen(sub);")
        self._emit("    if (sublen == 0) return 0;")
        self._emit("    const char* p = s;")
        self._emit("    while ((p = strstr(p, sub)) != NULL) { count++; p += sublen; }")
        self._emit("    return count;")
        self._emit("}")
        self._emit()
        # find(s, sub, start) — find first occurrence from start index
        self._emit("static inline int __btrc_find(const char* s, const char* sub, int start) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    if (start < 0 || start >= len) return -1;")
        self._emit("    const char* found = strstr(s + start, sub);")
        self._emit("    if (!found) return -1;")
        self._emit("    return (int)(found - s);")
        self._emit("}")
        self._emit()
        # fromInt(n) — convert int to string
        self._emit("static inline char* __btrc_fromInt(int n) {")
        self._emit("    char* r = (char*)malloc(21);")
        self._emit("    snprintf(r, 21, \"%d\", n);")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # fromFloat(f) — convert float to string
        self._emit("static inline char* __btrc_fromFloat(float f) {")
        self._emit("    char* r = (char*)malloc(32);")
        self._emit("    snprintf(r, 32, \"%g\", (double)f);")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # isDigitStr(s) — check if all chars are digits
        self._emit("static inline bool __btrc_isDigitStr(const char* s) {")
        self._emit("    if (!*s) return false;")
        self._emit("    for (; *s; s++) if (!isdigit((unsigned char)*s)) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # isAlphaStr(s) — check if all chars are alphabetic
        self._emit("static inline bool __btrc_isAlphaStr(const char* s) {")
        self._emit("    if (!*s) return false;")
        self._emit("    for (; *s; s++) if (!isalpha((unsigned char)*s)) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # isBlank(s) — check if string is empty or all whitespace
        self._emit("static inline bool __btrc_isBlank(const char* s) {")
        self._emit("    for (; *s; s++) if (!isspace((unsigned char)*s)) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        self._emit("static inline bool __btrc_isUpper(const char* s) {")
        self._emit("    if (*s == '\\0') return false;")
        self._emit("    for (; *s; s++) if (!isupper((unsigned char)*s) && !isspace((unsigned char)*s)) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        self._emit("static inline bool __btrc_isLower(const char* s) {")
        self._emit("    if (*s == '\\0') return false;")
        self._emit("    for (; *s; s++) if (!islower((unsigned char)*s) && !isspace((unsigned char)*s)) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # isAlnum(s) — check if all chars are alphanumeric
        self._emit("static inline bool __btrc_isAlnumStr(const char* s) {")
        self._emit("    if (*s == '\\0') return false;")
        self._emit("    for (; *s; s++) if (!isalnum((unsigned char)*s)) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # intToString / longToString / floatToString / doubleToString
        self._emit("static inline char* __btrc_intToString(int n) {")
        self._emit("    char* buf = (char*)malloc(32);")
        self._emit("    snprintf(buf, 32, \"%d\", n);")
        self._emit("    return buf;")
        self._emit("}")
        self._emit()
        self._emit("static inline char* __btrc_longToString(long n) {")
        self._emit("    char* buf = (char*)malloc(32);")
        self._emit("    snprintf(buf, 32, \"%ld\", n);")
        self._emit("    return buf;")
        self._emit("}")
        self._emit()
        self._emit("static inline char* __btrc_floatToString(float f) {")
        self._emit("    char* buf = (char*)malloc(64);")
        self._emit("    snprintf(buf, 64, \"%g\", (double)f);")
        self._emit("    return buf;")
        self._emit("}")
        self._emit()
        self._emit("static inline char* __btrc_doubleToString(double d) {")
        self._emit("    char* buf = (char*)malloc(64);")
        self._emit("    snprintf(buf, 64, \"%g\", d);")
        self._emit("    return buf;")
        self._emit("}")
        self._emit()
        # zfill(s, width) — left-pad with zeros
        self._emit("static inline char* __btrc_zfill(const char* s, int width) {")
        self._emit("    int len = (int)strlen(s);")
        self._emit("    if (len >= width) return strdup(s);")
        self._emit("    char* r = (char*)malloc(width + 1);")
        self._emit("    int pad = width - len;")
        self._emit("    int start = 0;")
        self._emit("    if (s[0] == '-' || s[0] == '+') { r[0] = s[0]; start = 1; }")
        self._emit("    for (int i = start; i < start + pad; i++) r[i] = '0';")
        self._emit("    memcpy(r + start + pad, s + start, len - start);")
        self._emit("    r[width] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # join(items, sep) — join a NULL-terminated char** array with separator
        self._emit("static inline char* __btrc_join(char** items, int count, const char* sep) {")
        self._emit("    if (count == 0) { char* r = (char*)malloc(1); r[0] = '\\0'; return r; }")
        self._emit("    int seplen = (int)strlen(sep);")
        self._emit("    int total = 0;")
        self._emit("    for (int i = 0; i < count; i++) total += (int)strlen(items[i]);")
        self._emit("    total += seplen * (count - 1);")
        self._emit("    char* r = (char*)malloc(total + 1);")
        self._emit("    int pos = 0;")
        self._emit("    for (int i = 0; i < count; i++) {")
        self._emit("        if (i > 0) { memcpy(r + pos, sep, seplen); pos += seplen; }")
        self._emit("        int len = (int)strlen(items[i]);")
        self._emit("        memcpy(r + pos, items[i], len);")
        self._emit("        pos += len;")
        self._emit("    }")
        self._emit("    r[pos] = '\\0';")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # strcat(a, b) — concatenate two strings
        self._emit("static inline char* __btrc_strcat(const char* a, const char* b) {")
        self._emit("    int la = (int)strlen(a), lb = (int)strlen(b);")
        self._emit("    char* r = (char*)malloc(la + lb + 1);")
        self._emit("    memcpy(r, a, la);")
        self._emit("    memcpy(r + la, b, lb + 1);")
        self._emit("    return r;")
        self._emit("}")
        self._emit()

    def _check_needs_math_helpers(self) -> bool:
        """Check if the AST uses any Math static methods."""
        return self._walk_for_math_methods(self.analyzed.program)

    def _walk_for_math_methods(self, node) -> bool:
        if node is None:
            return False
        if isinstance(node, CallExpr) and isinstance(node.callee, FieldAccessExpr):
            if isinstance(node.callee.obj, Identifier) and node.callee.obj.name == "Math":
                return True
        for attr in ('declarations', 'members', 'statements', 'body', 'then_block',
                     'else_block', 'args', 'elements', 'entries', 'cases'):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for item in child:
                    if hasattr(item, '__dict__') and self._walk_for_math_methods(item):
                        return True
            elif hasattr(child, '__dict__'):
                if self._walk_for_math_methods(child):
                    return True
        for attr in ('condition', 'callee', 'obj', 'left', 'right', 'operand',
                     'value', 'initializer', 'iterator', 'expr', 'test',
                     'consequent', 'alternate', 'target', 'expression'):
            child = getattr(node, attr, None)
            if child is not None and hasattr(child, '__dict__'):
                if self._walk_for_math_methods(child):
                    return True
        return False

    def _emit_math_helpers(self):
        """Emit C helper functions for Math stdlib methods."""
        self._emit("/* Math stdlib helpers */")
        # factorial (iterative)
        self._emit("static inline int __btrc_math_factorial(int n) {")
        self._emit("    int r = 1;")
        self._emit("    for (int i = 2; i <= n; i++) r *= i;")
        self._emit("    return r;")
        self._emit("}")
        self._emit()
        # gcd (Euclidean)
        self._emit("static inline int __btrc_math_gcd(int a, int b) {")
        self._emit("    if (a < 0) a = -a;")
        self._emit("    if (b < 0) b = -b;")
        self._emit("    while (b) { int t = b; b = a % b; a = t; }")
        self._emit("    return a;")
        self._emit("}")
        self._emit()
        # lcm (uses gcd)
        self._emit("static inline int __btrc_math_lcm(int a, int b) {")
        self._emit("    if (a == 0 || b == 0) return 0;")
        self._emit("    int g = __btrc_math_gcd(a, b);")
        self._emit("    return (a / g) * b;")
        self._emit("}")
        self._emit()
        # fibonacci (iterative)
        self._emit("static inline int __btrc_math_fibonacci(int n) {")
        self._emit("    if (n <= 0) return 0;")
        self._emit("    if (n == 1) return 1;")
        self._emit("    int a = 0, b = 1;")
        self._emit("    for (int i = 2; i <= n; i++) { int t = a + b; a = b; b = t; }")
        self._emit("    return b;")
        self._emit("}")
        self._emit()
        # isPrime (trial division)
        self._emit("static inline bool __btrc_math_isPrime(int n) {")
        self._emit("    if (n < 2) return false;")
        self._emit("    if (n < 4) return true;")
        self._emit("    if (n % 2 == 0 || n % 3 == 0) return false;")
        self._emit("    for (int i = 5; i * i <= n; i += 6)")
        self._emit("        if (n % i == 0 || n % (i + 2) == 0) return false;")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # sum for int array
        self._emit("static inline int __btrc_math_sum_int(int* data, int size) {")
        self._emit("    int s = 0;")
        self._emit("    for (int i = 0; i < size; i++) s += data[i];")
        self._emit("    return s;")
        self._emit("}")
        self._emit()
        # fsum for float array
        self._emit("static inline float __btrc_math_fsum(float* data, int size) {")
        self._emit("    float s = 0.0f;")
        self._emit("    for (int i = 0; i < size; i++) s += data[i];")
        self._emit("    return s;")
        self._emit("}")
        self._emit()

    def _check_needs_try_catch(self) -> bool:
        """Check if the AST uses try/catch or throw statements."""
        return self._walk_for_try_catch(self.analyzed.program)

    def _walk_for_try_catch(self, node) -> bool:
        if node is None:
            return False
        if isinstance(node, (TryCatchStmt, ThrowStmt)):
            return True
        for attr in ('declarations', 'members', 'statements', 'body', 'then_block',
                     'else_block', 'cases'):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for item in child:
                    if hasattr(item, '__dict__') and self._walk_for_try_catch(item):
                        return True
            elif hasattr(child, '__dict__') and self._walk_for_try_catch(child):
                return True
        for attr in ('try_block', 'catch_block',):
            child = getattr(node, attr, None)
            if child is not None and hasattr(child, '__dict__') and self._walk_for_try_catch(child):
                return True
        return False

    def _emit_try_catch_runtime(self):
        """Emit the setjmp/longjmp-based try/catch runtime."""
        self._emit("/* btrc try/catch runtime */")
        self._emit("#define __BTRC_TRY_STACK_SIZE 64")
        self._emit("static jmp_buf __btrc_try_stack[__BTRC_TRY_STACK_SIZE];")
        self._emit("static int __btrc_try_top = -1;")
        self._emit("static char __btrc_error_msg[1024] = \"\";")
        self._emit()
        self._emit("static inline void __btrc_throw(const char* msg) {")
        self._emit("    if (__btrc_try_top < 0) {")
        self._emit('        fprintf(stderr, "Unhandled exception: %s\\n", msg);')
        self._emit("        exit(1);")
        self._emit("    }")
        self._emit("    strncpy(__btrc_error_msg, msg, 1023);")
        self._emit("    __btrc_error_msg[1023] = '\\0';")
        self._emit("    longjmp(__btrc_try_stack[__btrc_try_top--], 1);")
        self._emit("}")
        self._emit()

    def _emit_try_catch(self, stmt: TryCatchStmt):
        """Emit try/catch using setjmp/longjmp."""
        self._emit("if (__btrc_try_top + 1 >= __BTRC_TRY_STACK_SIZE) { fprintf(stderr, \"try/catch stack overflow\\n\"); exit(1); }")
        self._emit("__btrc_try_top++;")
        self._emit("if (setjmp(__btrc_try_stack[__btrc_try_top]) == 0) {")
        self.indent_level += 1
        self._emit_block_contents(stmt.try_block)
        self._emit("__btrc_try_top--;")
        self.indent_level -= 1
        self._emit("} else {")
        self.indent_level += 1
        self._emit(f"const char* {stmt.catch_var} = __btrc_error_msg;")
        self._emit_block_contents(stmt.catch_block)
        self.indent_level -= 1
        self._emit("}")

    # ---- Generic instantiations ----

    def _emit_generic_struct_typedefs(self):
        """Emit only the struct typedefs for generic types (no function bodies).
        These only use pointer fields, so forward declarations suffice."""
        emitted_types: set[str] = set()
        for base_name, instances in self.generic_instances.items():
            if base_name == "Tuple":
                for args in instances:
                    mangled = "_".join(self._mangle_type(a) for a in args)
                    key = f"Tuple_{mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        self._emit_tuple_definition(args)
            elif base_name == "List":
                for args in instances:
                    mangled = self._mangle_type(args[0])
                    key = f"List_{mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        c_type = self._type_to_c(args[0])
                        self._emit_list_struct_typedef(c_type, mangled)
            elif base_name == "Array":
                for args in instances:
                    mangled = self._mangle_type(args[0])
                    key = f"Array_{mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        c_type = self._type_to_c(args[0])
                        self._emit_array_struct_typedef(c_type, mangled)
            elif base_name == "Map":
                for args in instances:
                    if len(args) == 2:
                        k_mangled = self._mangle_type(args[0])
                        v_mangled = self._mangle_type(args[1])
                        key = f"Map_{k_mangled}_{v_mangled}"
                        if key not in emitted_types:
                            emitted_types.add(key)
                            k_type = self._type_to_c(args[0])
                            v_type = self._type_to_c(args[1])
                            self._emit_map_struct_typedef(k_type, v_type, k_mangled, v_mangled)
            elif base_name == "Set":
                for args in instances:
                    mangled = self._mangle_type(args[0])
                    key = f"Set_{mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        c_type = self._type_to_c(args[0])
                        self._emit_set_struct_typedef(c_type, mangled)

    def _emit_generic_function_bodies(self):
        """Emit function implementations for generic types.
        Called after all struct definitions are complete.
        List functions are always emitted before Map functions so that
        Map.keys() and Map.values() can reference List types."""
        emitted_types: set[str] = set()
        # Pass 1: Emit List functions first (Map.keys/values depend on them)
        if "List" in self.generic_instances:
            for args in self.generic_instances["List"]:
                mangled = self._mangle_type(args[0])
                key = f"List_{mangled}"
                if key not in emitted_types:
                    emitted_types.add(key)
                    c_type = self._type_to_c(args[0])
                    self._emit_list_functions(c_type, mangled)
        # Pass 2: Emit Map functions
        if "Map" in self.generic_instances:
            for args in self.generic_instances["Map"]:
                if len(args) == 2:
                    k_mangled = self._mangle_type(args[0])
                    v_mangled = self._mangle_type(args[1])
                    key = f"Map_{k_mangled}_{v_mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        k_type = self._type_to_c(args[0])
                        v_type = self._type_to_c(args[1])
                        self._emit_map_functions(k_type, v_type, k_mangled, v_mangled)
        # Pass 3: Emit Set functions (Set.toList depends on List — already registered by analyzer)
        if "Set" in self.generic_instances:
            for args in self.generic_instances["Set"]:
                mangled = self._mangle_type(args[0])
                key = f"Set_{mangled}"
                if key not in emitted_types:
                    emitted_types.add(key)
                    c_type = self._type_to_c(args[0])
                    self._emit_set_functions(c_type, mangled)
        # Pass 4: Other generic types (Array, user-defined generics)
        for base_name, instances in self.generic_instances.items():
            if base_name in ("List", "Map", "Set"):
                continue  # Already handled
            if base_name == "Array":
                # Array doesn't have function bodies, only struct typedefs
                pass
            elif base_name in self.class_table:
                cls = self.class_table[base_name]
                for args in instances:
                    mangled = "_".join(self._mangle_type(a) for a in args)
                    key = f"{base_name}_{mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        self._emit_monomorphized_class(cls, args)

    def _emit_tuple_definition(self, args: tuple):
        """Emit a tuple struct: typedef struct { T0 _0; T1 _1; ... } btrc_Tuple_T0_T1;"""
        mangled = "_".join(self._mangle_type(a) for a in args)
        name = f"btrc_Tuple_{mangled}"
        self._emit("typedef struct {")
        for i, arg in enumerate(args):
            c_type = self._type_to_c(arg)
            self._emit(f"    {c_type} _{i};")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_list_struct_typedef(self, c_type: str, mangled: str):
        name = f"btrc_List_{mangled}"
        self._emit("typedef struct {")
        self._emit(f"    {c_type}* data;")
        self._emit("    int len;")
        self._emit("    int cap;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_list_functions(self, c_type: str, mangled: str):
        name = f"btrc_List_{mangled}"
        self._emit(f"static inline {name} {name}_new(void) {{")
        self._emit(f"    return ({name}){{NULL, 0, 0}};")
        self._emit("}")
        self._emit()
        self._emit(f"static inline void {name}_push({name}* l, {c_type} val) {{")
        self._emit("    if (l->len >= l->cap) {")
        self._emit("        l->cap = l->cap ? l->cap * 2 : 4;")
        self._emit(f"        l->data = ({c_type}*)realloc(l->data, sizeof({c_type}) * l->cap);")
        self._emit("    }")
        self._emit("    l->data[l->len++] = val;")
        self._emit("}")
        self._emit()
        self._emit(f"static inline {c_type} {name}_get({name}* l, int i) {{")
        self._emit("    if (i < 0 || i >= l->len) { fprintf(stderr, \"List index out of bounds: %d (len=%d)\\n\", i, l->len); exit(1); }")
        self._emit("    return l->data[i];")
        self._emit("}")
        self._emit()
        self._emit(f"static inline void {name}_set({name}* l, int i, {c_type} val) {{")
        self._emit("    if (i < 0 || i >= l->len) { fprintf(stderr, \"List index out of bounds: %d (len=%d)\\n\", i, l->len); exit(1); }")
        self._emit("    l->data[i] = val;")
        self._emit("}")
        self._emit()
        self._emit(f"static inline void {name}_free({name}* l) {{")
        self._emit("    free(l->data);")
        self._emit("    l->data = NULL; l->len = 0; l->cap = 0;")
        self._emit("}")
        self._emit()
        # Only emit contains/sort for primitive types (structs can't be compared with ==/</>)
        is_collection_struct = c_type.startswith("btrc_List_") or c_type.startswith("btrc_Map_") or c_type.startswith("btrc_Set_")
        is_primitive = c_type not in self.class_table and not is_collection_struct
        is_string = c_type == "char*"
        eq_expr = "strcmp(l->data[i], val) == 0" if is_string else "l->data[i] == val"
        if is_primitive:
            # contains
            self._emit(f"static inline bool {name}_contains({name}* l, {c_type} val) {{")
            self._emit("    for (int i = 0; i < l->len; i++) {")
            self._emit(f"        if ({eq_expr}) return true;")
            self._emit("    }")
            self._emit("    return false;")
            self._emit("}")
            self._emit()
            # indexOf
            self._emit(f"static inline int {name}_indexOf({name}* l, {c_type} val) {{")
            self._emit("    for (int i = 0; i < l->len; i++) {")
            self._emit(f"        if ({eq_expr}) return i;")
            self._emit("    }")
            self._emit("    return -1;")
            self._emit("}")
            self._emit()
            # lastIndexOf
            self._emit(f"static inline int {name}_lastIndexOf({name}* l, {c_type} val) {{")
            self._emit("    for (int i = l->len - 1; i >= 0; i--) {")
            self._emit(f"        if ({eq_expr}) return i;")
            self._emit("    }")
            self._emit("    return -1;")
            self._emit("}")
            self._emit()
        # remove (by index)
        self._emit(f"static inline void {name}_remove({name}* l, int idx) {{")
        self._emit("    if (idx < 0 || idx >= l->len) { fprintf(stderr, \"List remove index out of bounds: %d (len=%d)\\n\", idx, l->len); exit(1); }")
        self._emit("    for (int i = idx; i < l->len - 1; i++) {")
        self._emit("        l->data[i] = l->data[i + 1];")
        self._emit("    }")
        self._emit("    l->len--;")
        self._emit("}")
        self._emit()
        # reverse
        self._emit(f"static inline void {name}_reverse({name}* l) {{")
        self._emit("    for (int i = 0; i < l->len / 2; i++) {")
        self._emit(f"        {c_type} tmp = l->data[i];")
        self._emit("        l->data[i] = l->data[l->len - 1 - i];")
        self._emit("        l->data[l->len - 1 - i] = tmp;")
        self._emit("    }")
        self._emit("}")
        self._emit()
        # reversed() — non-mutating: returns a new reversed copy
        self._emit(f"static inline {name} {name}_reversed({name}* l) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit(f"    for (int i = l->len - 1; i >= 0; i--) {name}_push(&result, l->data[i]);")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        if is_primitive:
            # sort (ascending, using qsort)
            self._emit(f"static int __{name}_cmp(const void* a, const void* b) {{")
            if is_string:
                self._emit("    return strcmp(*(char**)a, *(char**)b);")
            else:
                self._emit(f"    {c_type} va = *({c_type}*)a;")
                self._emit(f"    {c_type} vb = *({c_type}*)b;")
                self._emit("    return (va > vb) - (va < vb);")
            self._emit("}")
            self._emit(f"static inline void {name}_sort({name}* l) {{")
            self._emit(f"    qsort(l->data, l->len, sizeof({c_type}), __{name}_cmp);")
            self._emit("}")
            self._emit()
            # sorted() — non-mutating sort: returns a new sorted copy
            self._emit(f"static inline {name} {name}_sorted({name}* l) {{")
            self._emit(f"    {name} result = {name}_new();")
            self._emit(f"    for (int i = 0; i < l->len; i++) {name}_push(&result, l->data[i]);")
            self._emit(f"    qsort(result.data, result.len, sizeof({c_type}), __{name}_cmp);")
            self._emit("    return result;")
            self._emit("}")
            self._emit()
        # min/max/sum — only for numeric primitive types (not string, not struct)
        is_numeric = c_type in ("int", "float", "double", "long", "short", "unsigned int", "unsigned long")
        if is_numeric:
            # min()
            self._emit(f"static inline {c_type} {name}_min({name}* l) {{")
            self._emit("    if (l->len <= 0) { fprintf(stderr, \"List min on empty list\\n\"); exit(1); }")
            self._emit(f"    {c_type} m = l->data[0];")
            self._emit("    for (int i = 1; i < l->len; i++) if (l->data[i] < m) m = l->data[i];")
            self._emit("    return m;")
            self._emit("}")
            self._emit()
            # max()
            self._emit(f"static inline {c_type} {name}_max({name}* l) {{")
            self._emit("    if (l->len <= 0) { fprintf(stderr, \"List max on empty list\\n\"); exit(1); }")
            self._emit(f"    {c_type} m = l->data[0];")
            self._emit("    for (int i = 1; i < l->len; i++) if (l->data[i] > m) m = l->data[i];")
            self._emit("    return m;")
            self._emit("}")
            self._emit()
            # sum()
            self._emit(f"static inline {c_type} {name}_sum({name}* l) {{")
            self._emit(f"    {c_type} s = 0;")
            self._emit("    for (int i = 0; i < l->len; i++) s += l->data[i];")
            self._emit("    return s;")
            self._emit("}")
            self._emit()
        # swap(i, j) — swap two elements
        self._emit(f"static inline void {name}_swap({name}* l, int i, int j) {{")
        self._emit("    if (i < 0 || i >= l->len || j < 0 || j >= l->len) { fprintf(stderr, \"List swap index out of bounds\\n\"); exit(1); }")
        self._emit(f"    {c_type} tmp = l->data[i]; l->data[i] = l->data[j]; l->data[j] = tmp;")
        self._emit("}")
        self._emit()
        # pop — remove and return the last element
        self._emit(f"static inline {c_type} {name}_pop({name}* l) {{")
        self._emit("    if (l->len <= 0) { fprintf(stderr, \"List pop from empty list\\n\"); exit(1); }")
        self._emit("    return l->data[--l->len];")
        self._emit("}")
        self._emit()
        # clear
        self._emit(f"static inline void {name}_clear({name}* l) {{")
        self._emit("    l->len = 0;")
        self._emit("}")
        self._emit()
        # fill(value) — set all elements to a given value
        self._emit(f"static inline void {name}_fill({name}* l, {c_type} val) {{")
        self._emit("    for (int i = 0; i < l->len; i++) l->data[i] = val;")
        self._emit("}")
        self._emit()
        # count(value) — count occurrences (only for primitive types)
        if is_primitive:
            self._emit(f"static inline int {name}_count({name}* l, {c_type} val) {{")
            self._emit("    int c = 0;")
            self._emit(f"    for (int i = 0; i < l->len; i++) if ({eq_expr}) c++;")
            self._emit("    return c;")
            self._emit("}")
            self._emit()
            # removeAll(value) — remove all occurrences of value
            self._emit(f"static inline void {name}_removeAll({name}* l, {c_type} val) {{")
            self._emit("    int j = 0;")
            self._emit("    for (int i = 0; i < l->len; i++) {")
            self._emit(f"        if (!({eq_expr})) l->data[j++] = l->data[i];")
            self._emit("    }")
            self._emit("    l->len = j;")
            self._emit("}")
            self._emit()
            # distinct() — return new list with duplicates removed
            self._emit(f"static inline {name} {name}_distinct({name}* l) {{")
            self._emit(f"    {name} result = {name}_new();")
            self._emit("    for (int i = 0; i < l->len; i++) {")
            self._emit(f"        if (!{name}_contains(&result, l->data[i])) {{")
            self._emit(f"            {name}_push(&result, l->data[i]);")
            self._emit("        }")
            self._emit("    }")
            self._emit("    return result;")
            self._emit("}")
            self._emit()
        # slice(start, end) — returns a new list from [start, end)
        self._emit(f"static inline {name} {name}_slice({name}* l, int start, int end) {{")
        self._emit("    if (start < 0) start = l->len + start;")
        self._emit("    if (end < 0) end = l->len + end;")
        self._emit("    if (start < 0) start = 0;")
        self._emit("    if (end > l->len) end = l->len;")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = start; i < end; i++) {")
        self._emit(f"        {name}_push(&result, l->data[i]);")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # take(n) — returns first n elements
        self._emit(f"static inline {name} {name}_take({name}* l, int n) {{")
        self._emit("    if (n > l->len) n = l->len;")
        self._emit("    if (n < 0) n = 0;")
        self._emit(f"    return {name}_slice(l, 0, n);")
        self._emit("}")
        self._emit()
        # drop(n) — returns all elements after skipping first n
        self._emit(f"static inline {name} {name}_drop({name}* l, int n) {{")
        self._emit("    if (n > l->len) n = l->len;")
        self._emit("    if (n < 0) n = 0;")
        self._emit(f"    return {name}_slice(l, n, l->len);")
        self._emit("}")
        self._emit()
        # join(separator) — only for List<string>
        if c_type == "char*":
            self._emit(f"static inline char* {name}_join({name}* l, const char* sep) {{")
            self._emit("    int total = 0;")
            self._emit("    int sep_len = strlen(sep);")
            self._emit("    for (int i = 0; i < l->len; i++) {")
            self._emit("        total += strlen(l->data[i]);")
            self._emit("        if (i < l->len - 1) total += sep_len;")
            self._emit("    }")
            self._emit("    char* result = (char*)malloc(total + 1);")
            self._emit("    int pos = 0;")
            self._emit("    for (int i = 0; i < l->len; i++) {")
            self._emit("        int slen = strlen(l->data[i]);")
            self._emit("        memcpy(result + pos, l->data[i], slen); pos += slen;")
            self._emit("        if (i < l->len - 1) { memcpy(result + pos, sep, sep_len); pos += sep_len; }")
            self._emit("    }")
            self._emit("    result[pos] = '\\0';")
            self._emit("    return result;")
            self._emit("}")
            self._emit()
        # forEach(fn) — call fn(element) for each element
        self._emit(f"static inline void {name}_forEach({name}* l, void (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < l->len; i++) fn(l->data[i]);")
        self._emit("}")
        self._emit()
        # filter(fn) — return new list of elements where fn(element) returns true
        self._emit(f"static inline {name} {name}_filter({name}* l, bool (*fn)({c_type})) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < l->len; i++) {")
        self._emit(f"        if (fn(l->data[i])) {name}_push(&result, l->data[i]);")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # any(fn) — return true if fn(element) is true for any element
        self._emit(f"static inline bool {name}_any({name}* l, bool (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < l->len; i++) { if (fn(l->data[i])) return true; }")
        self._emit("    return false;")
        self._emit("}")
        self._emit()
        # all(fn) — return true if fn(element) is true for all elements
        self._emit(f"static inline bool {name}_all({name}* l, bool (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < l->len; i++) { if (!fn(l->data[i])) return false; }")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # findIndex(fn) — return index of first element where fn(element) is true, or -1
        self._emit(f"static inline int {name}_findIndex({name}* l, bool (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < l->len; i++) { if (fn(l->data[i])) return i; }")
        self._emit("    return -1;")
        self._emit("}")
        self._emit()
        # size — returns number of elements
        self._emit(f"static inline int {name}_size({name}* l) {{")
        self._emit("    return l->len;")
        self._emit("}")
        self._emit()
        # isEmpty() — check if list has no elements
        self._emit(f"static inline bool {name}_isEmpty({name}* l) {{")
        self._emit("    return l->len == 0;")
        self._emit("}")
        self._emit()
        # first() — get first element (bounds-checked)
        self._emit(f"static inline {c_type} {name}_first({name}* l) {{")
        self._emit("    if (l->len == 0) { fprintf(stderr, \"List.first() called on empty list\\n\"); exit(1); }")
        self._emit("    return l->data[0];")
        self._emit("}")
        self._emit()
        # last() — get last element (bounds-checked)
        self._emit(f"static inline {c_type} {name}_last({name}* l) {{")
        self._emit("    if (l->len == 0) { fprintf(stderr, \"List.last() called on empty list\\n\"); exit(1); }")
        self._emit("    return l->data[l->len - 1];")
        self._emit("}")
        self._emit()
        # map(fn) — apply fn to each element, return new list (same type)
        self._emit(f"static inline {name} {name}_map({name}* l, {c_type} (*fn)({c_type})) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit(f"    for (int i = 0; i < l->len; i++) {name}_push(&result, fn(l->data[i]));")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # reduce(init, fn) — fold list into a single value
        self._emit(f"static inline {c_type} {name}_reduce({name}* l, {c_type} init, {c_type} (*fn)({c_type}, {c_type})) {{")
        self._emit(f"    {c_type} acc = init;")
        self._emit("    for (int i = 0; i < l->len; i++) acc = fn(acc, l->data[i]);")
        self._emit("    return acc;")
        self._emit("}")
        self._emit()
        # extend(other) — append all elements from another list
        self._emit(f"static inline void {name}_extend({name}* l, {name}* other) {{")
        self._emit(f"    for (int i = 0; i < other->len; i++) {name}_push(l, other->data[i]);")
        self._emit("}")
        self._emit()
        # joinToString — alias for join (only for char* lists)
        if c_type == "char*":
            self._emit(f"static inline char* {name}_joinToString({name}* l, const char* sep) {{")
            self._emit(f"    return {name}_join(l, sep);")
            self._emit("}")
            self._emit()
        # insert(index, value) — insert element at index, shifting others right
        self._emit(f"static inline void {name}_insert({name}* l, int idx, {c_type} val) {{")
        self._emit("    if (idx < 0 || idx > l->len) { fprintf(stderr, \"List insert index out of bounds: %d (size %d)\\n\", idx, l->len); exit(1); }")
        self._emit(f"    if (l->len >= l->cap) {{ l->cap = l->cap == 0 ? 4 : l->cap * 2; l->data = ({c_type}*)realloc(l->data, sizeof({c_type}) * l->cap); }}")
        self._emit("    for (int i = l->len; i > idx; i--) l->data[i] = l->data[i-1];")
        self._emit("    l->data[idx] = val;")
        self._emit("    l->len++;")
        self._emit("}")
        self._emit()

    def _emit_array_struct_typedef(self, c_type: str, mangled: str):
        name = f"btrc_Array_{mangled}"
        self._emit("typedef struct {")
        self._emit(f"    {c_type}* data;")
        self._emit("    int len;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_map_struct_typedef(self, k_type: str, v_type: str, k_mangled: str, v_mangled: str):
        name = f"btrc_Map_{k_mangled}_{v_mangled}"
        entry = f"{name}_entry"
        self._emit(f"typedef struct {{ {k_type} key; {v_type} value; bool occupied; }} {entry};")
        self._emit("typedef struct {")
        self._emit(f"    {entry}* buckets;")
        self._emit("    int cap;")
        self._emit("    int len;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_map_functions(self, k_type: str, v_type: str, k_mangled: str, v_mangled: str):
        name = f"btrc_Map_{k_mangled}_{v_mangled}"
        entry = f"{name}_entry"

        # Hash function selection
        if k_type == "char*":
            hash_expr = "__btrc_hash_str(key)"
            eq_expr = "strcmp(m->buckets[idx].key, key) == 0"
            if not self._hash_str_emitted:
                self._emit("static inline unsigned int __btrc_hash_str(const char* s) {")
                self._emit("    unsigned int h = 5381;")
                self._emit("    while (*s) h = h * 33 + (unsigned char)*s++;")
                self._emit("    return h;")
                self._emit("}")
                self._emit()
                self._hash_str_emitted = True
        else:
            hash_expr = "(unsigned int)key"
            eq_expr = "m->buckets[idx].key == key"

        # new
        self._emit(f"static inline {name} {name}_new(void) {{")
        self._emit(f"    {name} m;")
        self._emit("    m.cap = 16;")
        self._emit("    m.len = 0;")
        self._emit(f"    m.buckets = ({entry}*)calloc(m.cap, sizeof({entry}));")
        self._emit("    return m;")
        self._emit("}")
        self._emit()

        # Forward declare put (needed by resize)
        self._emit(f"static inline void {name}_put({name}* m, {k_type} key, {v_type} value);")
        self._emit()

        # resize — doubles capacity and rehashes all entries
        self._emit(f"static inline void {name}_resize({name}* m) {{")
        self._emit("    int old_cap = m->cap;")
        self._emit(f"    {entry}* old_buckets = m->buckets;")
        self._emit("    m->cap *= 2;")
        self._emit("    m->len = 0;")
        self._emit(f"    m->buckets = ({entry}*)calloc(m->cap, sizeof({entry}));")
        self._emit("    for (int i = 0; i < old_cap; i++) {")
        self._emit("        if (old_buckets[i].occupied) {")
        self._emit(f"            {name}_put(m, old_buckets[i].key, old_buckets[i].value);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    free(old_buckets);")
        self._emit("}")
        self._emit()

        # put — with auto-resize at 75% load factor
        self._emit(f"static inline void {name}_put({name}* m, {k_type} key, {v_type} value) {{")
        self._emit(f"    if (m->len * 4 >= m->cap * 3) {{ {name}_resize(m); }}")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit("    while (m->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) {{ m->buckets[idx].value = value; return; }}")
        self._emit("        idx = (idx + 1) % m->cap;")
        self._emit("    }")
        self._emit("    m->buckets[idx].key = key;")
        self._emit("    m->buckets[idx].value = value;")
        self._emit("    m->buckets[idx].occupied = true;")
        self._emit("    m->len++;")
        self._emit("}")
        self._emit()

        # get
        self._emit(f"static inline {v_type} {name}_get({name}* m, {k_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit("    while (m->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) return m->buckets[idx].value;")
        self._emit("        idx = (idx + 1) % m->cap;")
        self._emit("    }")
        self._emit("    fprintf(stderr, \"Map key not found\\n\"); exit(1);")
        if v_type.endswith("*"):
            self._emit("    return NULL;")
        else:
            self._emit(f"    return ({v_type}){{0}};")
        self._emit("}")
        self._emit()

        # getOrDefault
        self._emit(f"static inline {v_type} {name}_getOrDefault({name}* m, {k_type} key, {v_type} fallback) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit("    while (m->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) return m->buckets[idx].value;")
        self._emit("        idx = (idx + 1) % m->cap;")
        self._emit("    }")
        self._emit("    return fallback;")
        self._emit("}")
        self._emit()

        # has
        self._emit(f"static inline bool {name}_has({name}* m, {k_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit("    while (m->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) return true;")
        self._emit("        idx = (idx + 1) % m->cap;")
        self._emit("    }")
        self._emit("    return false;")
        self._emit("}")
        self._emit()

        # contains (alias for has — consistent with List.contains)
        self._emit(f"static inline bool {name}_contains({name}* m, {k_type} key) {{")
        self._emit(f"    return {name}_has(m, key);")
        self._emit("}")
        self._emit()

        # putIfAbsent — only insert if key doesn't exist
        self._emit(f"static inline void {name}_putIfAbsent({name}* m, {k_type} key, {v_type} value) {{")
        self._emit(f"    if (!{name}_has(m, key)) {name}_put(m, key, value);")
        self._emit("}")
        self._emit()

        # free
        self._emit(f"static inline void {name}_free({name}* m) {{")
        self._emit("    free(m->buckets);")
        self._emit("    m->buckets = NULL; m->cap = 0; m->len = 0;")
        self._emit("}")
        self._emit()

        # remove — find and remove a key, rehashing the cluster to fix open-addressing probes
        self._emit(f"static inline void {name}_remove({name}* m, {k_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit("    while (m->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) {{")
        self._emit("            m->buckets[idx].occupied = false;")
        self._emit("            m->len--;")
        self._emit("            /* Rehash the rest of the cluster */")
        self._emit("            unsigned int j = (idx + 1) % m->cap;")
        self._emit("            while (m->buckets[j].occupied) {")
        self._emit(f"                {k_type} rk = m->buckets[j].key;")
        self._emit(f"                {v_type} rv = m->buckets[j].value;")
        self._emit("                m->buckets[j].occupied = false;")
        self._emit("                m->len--;")
        self._emit(f"                {name}_put(m, rk, rv);")
        self._emit("                j = (j + 1) % m->cap;")
        self._emit("            }")
        self._emit("            return;")
        self._emit("        }")
        self._emit("        idx = (idx + 1) % m->cap;")
        self._emit("    }")
        self._emit("}")
        self._emit()

        # keys — returns a List<K> of all keys in the map
        k_list = f"btrc_List_{k_mangled}"
        self._emit(f"static inline {k_list} {name}_keys({name}* m) {{")
        self._emit(f"    {k_list} result = {k_list}_new();")
        self._emit("    for (int i = 0; i < m->cap; i++) {")
        self._emit("        if (m->buckets[i].occupied) {")
        self._emit(f"            {k_list}_push(&result, m->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()

        # values — returns a List<V> of all values in the map
        v_list = f"btrc_List_{v_mangled}"
        self._emit(f"static inline {v_list} {name}_values({name}* m) {{")
        self._emit(f"    {v_list} result = {v_list}_new();")
        self._emit("    for (int i = 0; i < m->cap; i++) {")
        self._emit("        if (m->buckets[i].occupied) {")
        self._emit(f"            {v_list}_push(&result, m->buckets[i].value);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()

        # clear — remove all entries without deallocating
        self._emit(f"static inline void {name}_clear({name}* m) {{")
        self._emit("    for (int i = 0; i < m->cap; i++) m->buckets[i].occupied = false;")
        self._emit("    m->len = 0;")
        self._emit("}")
        self._emit()

        # forEach(fn) — call fn(key, value) for each entry
        self._emit(f"static inline void {name}_forEach({name}* m, void (*fn)({k_type}, {v_type})) {{")
        self._emit("    for (int i = 0; i < m->cap; i++) {")
        self._emit("        if (m->buckets[i].occupied) fn(m->buckets[i].key, m->buckets[i].value);")
        self._emit("    }")
        self._emit("}")
        self._emit()
        # size — returns number of entries
        self._emit(f"static inline int {name}_size({name}* m) {{")
        self._emit("    return m->len;")
        self._emit("}")
        self._emit()
        # isEmpty() — check if map has no entries
        self._emit(f"static inline bool {name}_isEmpty({name}* m) {{")
        self._emit("    return m->len == 0;")
        self._emit("}")
        self._emit()
        # containsValue(value) — only for primitive value types (structs can't use ==)
        v_is_coll = v_type.startswith("btrc_List_") or v_type.startswith("btrc_Map_") or v_type.startswith("btrc_Set_")
        v_is_primitive = v_type not in self.class_table and not v_is_coll
        if v_is_primitive:
            if v_type == "char*":
                val_eq = "strcmp(m->buckets[i].value, value) == 0"
            else:
                val_eq = "m->buckets[i].value == value"
            self._emit(f"static inline bool {name}_containsValue({name}* m, {v_type} value) {{")
            self._emit("    for (int i = 0; i < m->cap; i++) {")
            self._emit(f"        if (m->buckets[i].occupied && {val_eq}) return true;")
            self._emit("    }")
            self._emit("    return false;")
            self._emit("}")
            self._emit()
        # merge(other) — copy all entries from other map into this map
        self._emit(f"static inline void {name}_merge({name}* m, {name}* other) {{")
        self._emit("    for (int i = 0; i < other->cap; i++) {")
        self._emit(f"        if (other->buckets[i].occupied) {name}_put(m, other->buckets[i].key, other->buckets[i].value);")
        self._emit("    }")
        self._emit("}")
        self._emit()

    def _emit_set_struct_typedef(self, c_type: str, mangled: str):
        name = f"btrc_Set_{mangled}"
        entry = f"{name}_entry"
        self._emit(f"typedef struct {{ {c_type} key; bool occupied; }} {entry};")
        self._emit("typedef struct {")
        self._emit(f"    {entry}* buckets;")
        self._emit("    int len;")
        self._emit("    int cap;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_set_functions(self, c_type: str, mangled: str):
        name = f"btrc_Set_{mangled}"
        entry = f"{name}_entry"

        # Hash function selection
        if c_type == "char*":
            hash_expr = "__btrc_hash_str(key)"
            eq_expr = "strcmp(s->buckets[idx].key, key) == 0"
            if not self._hash_str_emitted:
                self._emit("static inline unsigned int __btrc_hash_str(const char* s) {")
                self._emit("    unsigned int h = 5381;")
                self._emit("    while (*s) h = h * 33 + (unsigned char)*s++;")
                self._emit("    return h;")
                self._emit("}")
                self._emit()
                self._hash_str_emitted = True
        else:
            hash_expr = "(unsigned int)key"
            eq_expr = "s->buckets[idx].key == key"

        # new
        self._emit(f"static inline {name} {name}_new(void) {{")
        self._emit(f"    {name} s;")
        self._emit("    s.cap = 16;")
        self._emit("    s.len = 0;")
        self._emit(f"    s.buckets = ({entry}*)calloc(s.cap, sizeof({entry}));")
        self._emit("    return s;")
        self._emit("}")
        self._emit()

        # Forward declare add (needed by resize)
        self._emit(f"static inline void {name}_add({name}* s, {c_type} key);")
        self._emit()

        # resize
        self._emit(f"static inline void {name}_resize({name}* s) {{")
        self._emit("    int old_cap = s->cap;")
        self._emit(f"    {entry}* old_buckets = s->buckets;")
        self._emit("    s->cap *= 2;")
        self._emit("    s->len = 0;")
        self._emit(f"    s->buckets = ({entry}*)calloc(s->cap, sizeof({entry}));")
        self._emit("    for (int i = 0; i < old_cap; i++) {")
        self._emit("        if (old_buckets[i].occupied) {")
        self._emit(f"            {name}_add(s, old_buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    free(old_buckets);")
        self._emit("}")
        self._emit()

        # add
        self._emit(f"static inline void {name}_add({name}* s, {c_type} key) {{")
        self._emit(f"    if (s->len * 4 >= s->cap * 3) {{ {name}_resize(s); }}")
        self._emit(f"    unsigned int idx = {hash_expr} % s->cap;")
        self._emit("    while (s->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) return;")  # Already exists
        self._emit("        idx = (idx + 1) % s->cap;")
        self._emit("    }")
        self._emit("    s->buckets[idx].key = key;")
        self._emit("    s->buckets[idx].occupied = true;")
        self._emit("    s->len++;")
        self._emit("}")
        self._emit()

        # contains
        self._emit(f"static inline bool {name}_contains({name}* s, {c_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % s->cap;")
        self._emit("    while (s->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) return true;")
        self._emit("        idx = (idx + 1) % s->cap;")
        self._emit("    }")
        self._emit("    return false;")
        self._emit("}")
        self._emit()

        # has (alias for contains)
        self._emit(f"static inline bool {name}_has({name}* s, {c_type} key) {{")
        self._emit(f"    return {name}_contains(s, key);")
        self._emit("}")
        self._emit()

        # remove
        self._emit(f"static inline void {name}_remove({name}* s, {c_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % s->cap;")
        self._emit("    while (s->buckets[idx].occupied) {")
        self._emit(f"        if ({eq_expr}) {{")
        self._emit("            s->buckets[idx].occupied = false;")
        self._emit("            s->len--;")
        self._emit("            /* Rehash the rest of the cluster */")
        self._emit("            unsigned int j = (idx + 1) % s->cap;")
        self._emit("            while (s->buckets[j].occupied) {")
        self._emit(f"                {c_type} rk = s->buckets[j].key;")
        self._emit("                s->buckets[j].occupied = false;")
        self._emit("                s->len--;")
        self._emit(f"                {name}_add(s, rk);")
        self._emit("                j = (j + 1) % s->cap;")
        self._emit("            }")
        self._emit("            return;")
        self._emit("        }")
        self._emit("        idx = (idx + 1) % s->cap;")
        self._emit("    }")
        self._emit("}")
        self._emit()

        # free
        self._emit(f"static inline void {name}_free({name}* s) {{")
        self._emit("    free(s->buckets);")
        self._emit("    s->buckets = NULL; s->cap = 0; s->len = 0;")
        self._emit("}")
        self._emit()

        # toList — returns a List<T> of all elements
        list_name = f"btrc_List_{mangled}"
        self._emit(f"static inline {list_name} {name}_toList({name}* s) {{")
        self._emit(f"    {list_name} result = {list_name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit("        if (s->buckets[i].occupied) {")
        self._emit(f"            {list_name}_push(&result, s->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()

        # clear
        self._emit(f"static inline void {name}_clear({name}* s) {{")
        self._emit("    for (int i = 0; i < s->cap; i++) s->buckets[i].occupied = false;")
        self._emit("    s->len = 0;")
        self._emit("}")
        self._emit()

        # forEach
        self._emit(f"static inline void {name}_forEach({name}* s, void (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit("        if (s->buckets[i].occupied) fn(s->buckets[i].key);")
        self._emit("    }")
        self._emit("}")
        self._emit()

        # filter(fn) — return new Set of elements where fn(element) returns true
        self._emit(f"static inline {name} {name}_filter({name}* s, bool (*fn)({c_type})) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit("        if (s->buckets[i].occupied && fn(s->buckets[i].key)) {")
        self._emit(f"            {name}_add(&result, s->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()

        # any(fn) — return true if fn(element) is true for any element
        self._emit(f"static inline bool {name}_any({name}* s, bool (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit("        if (s->buckets[i].occupied && fn(s->buckets[i].key)) return true;")
        self._emit("    }")
        self._emit("    return false;")
        self._emit("}")
        self._emit()

        # all(fn) — return true if fn(element) is true for all elements
        self._emit(f"static inline bool {name}_all({name}* s, bool (*fn)({c_type})) {{")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit("        if (s->buckets[i].occupied && !fn(s->buckets[i].key)) return false;")
        self._emit("    }")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # size — returns number of elements
        self._emit(f"static inline int {name}_size({name}* s) {{")
        self._emit("    return s->len;")
        self._emit("}")
        self._emit()
        # isEmpty() — check if set has no elements
        self._emit(f"static inline bool {name}_isEmpty({name}* s) {{")
        self._emit("    return s->len == 0;")
        self._emit("}")
        self._emit()
        # unite(other) — return new set with elements from both sets
        self._emit(f"static inline {name} {name}_unite({name}* s, {name}* other) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit(f"        if (s->buckets[i].occupied) {name}_add(&result, s->buckets[i].key);")
        self._emit("    }")
        self._emit("    for (int i = 0; i < other->cap; i++) {")
        self._emit(f"        if (other->buckets[i].occupied) {name}_add(&result, other->buckets[i].key);")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # intersection(other) — return new set with elements in both sets
        self._emit(f"static inline {name} {name}_intersect({name}* s, {name}* other) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit(f"        if (s->buckets[i].occupied && {name}_contains(other, s->buckets[i].key)) {{")
        self._emit(f"            {name}_add(&result, s->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # subtract(other) — return new set with elements in s but not other
        self._emit(f"static inline {name} {name}_subtract({name}* s, {name}* other) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit(f"        if (s->buckets[i].occupied && !{name}_contains(other, s->buckets[i].key)) {{")
        self._emit(f"            {name}_add(&result, s->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # isSubsetOf(other) — true if every element in s is also in other
        self._emit(f"static inline bool {name}_isSubsetOf({name}* s, {name}* other) {{")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit(f"        if (s->buckets[i].occupied && !{name}_contains(other, s->buckets[i].key)) return false;")
        self._emit("    }")
        self._emit("    return true;")
        self._emit("}")
        self._emit()
        # isSupersetOf(other) — true if every element in other is also in s
        self._emit(f"static inline bool {name}_isSupersetOf({name}* s, {name}* other) {{")
        self._emit(f"    return {name}_isSubsetOf(other, s);")
        self._emit("}")
        self._emit()
        # symmetricDifference(other) — elements in either set but not both
        self._emit(f"static inline {name} {name}_symmetricDifference({name}* s, {name}* other) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit(f"        if (s->buckets[i].occupied && !{name}_contains(other, s->buckets[i].key)) {{")
        self._emit(f"            {name}_add(&result, s->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    for (int i = 0; i < other->cap; i++) {")
        self._emit(f"        if (other->buckets[i].occupied && !{name}_contains(s, other->buckets[i].key)) {{")
        self._emit(f"            {name}_add(&result, other->buckets[i].key);")
        self._emit("        }")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()
        # copy() — create independent copy
        self._emit(f"static inline {name} {name}_copy({name}* s) {{")
        self._emit(f"    {name} result = {name}_new();")
        self._emit("    for (int i = 0; i < s->cap; i++) {")
        self._emit(f"        if (s->buckets[i].occupied) {name}_add(&result, s->buckets[i].key);")
        self._emit("    }")
        self._emit("    return result;")
        self._emit("}")
        self._emit()

    def _emit_monomorphized_class(self, cls: ClassInfo, args: tuple[TypeExpr, ...]):
        """Emit a monomorphized version of a generic class."""
        # Build substitution map: T -> concrete type
        subs = {}
        for param, arg in zip(cls.generic_params, args):
            subs[param] = arg

        mangled_args = "_".join(self._mangle_type(a) for a in args)
        mono_name = f"btrc_{cls.name}_{mangled_args}"

        # Struct
        self._emit("typedef struct {")
        self.indent_level += 1
        if not cls.fields:
            self._emit("char _dummy;")
        for fname, field in cls.fields.items():
            ftype = self._substitute_type(field.type, subs)
            self._emit(f"{self._type_to_c(ftype)} {fname};")
        self.indent_level -= 1
        self._emit(f"}} {mono_name};")
        self._emit()

    # ---- Forward declarations ----

    def _emit_function_forward_declarations(self):
        """Forward-declare all top-level functions to enable mutual recursion."""
        any_emitted = False
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, FunctionDecl) and decl.body is not None and decl.name != "main":
                # Skip functions using raw C struct types (struct declarations may not
                # be visible yet; these are C-interop functions, not btrc functions)
                uses_struct = any(
                    p.type and p.type.base.startswith("struct ")
                    for p in decl.params
                )
                if decl.return_type and decl.return_type.base.startswith("struct "):
                    uses_struct = True
                if uses_struct:
                    continue
                ret_type = self._type_to_c(decl.return_type)
                params = [self._param_to_c(p) for p in decl.params]
                params_str = ", ".join(params) if params else "void"
                self._emit(f"{ret_type} {decl.name}({params_str});")
                any_emitted = True
        if any_emitted:
            self._emit()

    def _emit_forward_declarations(self):
        for name, cls in self.class_table.items():
            if not cls.generic_params:  # non-generic classes
                self._emit(f"typedef struct {name} {name};")
        self._emit()

    def _emit_struct_definitions(self):
        """Emit struct bodies for all classes before generic instantiations.
        This ensures List<MyClass> etc. can see the full type."""
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, ClassDecl) and not decl.generic_params:
                self._emit_class_struct(decl)

    def _emit_class_struct(self, decl: ClassDecl):
        """Emit only the struct definition for a class (no methods)."""
        child_field_names = {m.name for m in decl.members if isinstance(m, FieldDecl)}
        self._emit_line_directive(decl.line)
        self._emit(f"struct {decl.name} {{")
        self.indent_level += 1
        field_count = 0
        if decl.parent and decl.parent in self.class_table:
            parent_cls = self.class_table[decl.parent]
            for fname, fld in parent_cls.fields.items():
                if fname not in child_field_names:
                    self._emit(f"{self._type_to_c(fld.type)} {fname};")
                    field_count += 1
        for member in decl.members:
            if isinstance(member, FieldDecl):
                self._emit(f"{self._type_to_c(member.type)} {member.name};")
                field_count += 1
            elif isinstance(member, PropertyDecl):
                # Auto-properties get a backing field _name
                is_auto_getter = member.has_getter and member.getter_body is None
                is_auto_setter = member.has_setter and member.setter_body is None
                if is_auto_getter or is_auto_setter:
                    self._emit(f"{self._type_to_c(member.type)} _{member.name};")
                    field_count += 1
        if field_count == 0:
            self._emit("char _dummy;")
        self.indent_level -= 1
        self._emit("};")
        self._emit()

    # ---- Auto-destructor ----

    def _emit_destroy_forward_declarations(self):
        """Forward-declare destroy functions for all classes so they can reference each other."""
        any_emitted = False
        for name, cls in self.class_table.items():
            if not cls.generic_params:
                self._emit(f"void {name}_destroy({name}* self);")
                any_emitted = True
        if any_emitted:
            self._emit()

    def _emit_destroy_function(self, class_name: str, cls: ClassInfo):
        """Emit a destroy function that handles recursive cleanup when delete is called."""
        self._emit(f"void {class_name}_destroy({class_name}* self) {{")
        self.indent_level += 1
        self._emit("if (self == NULL) return;")

        # 1. Call user's __del__ if defined
        if "__del__" in cls.methods:
            self._emit(f"{class_name}___del__(self);")

        # 2. Recursively destroy class-instance pointer fields
        for fname, fld in cls.fields.items():
            if fld.type is None:
                continue
            if fld.type.pointer_depth > 0 and fld.type.base in self.class_table:
                # Pointer to another class — recursively destroy
                self._emit(f"{fld.type.base}_destroy(self->{fname});")
            elif fld.type.base == "List" and fld.type.generic_args:
                # Free list data
                c_type = self._type_to_c(fld.type)
                self._emit(f"{c_type}_free(&self->{fname});")
            elif fld.type.base == "Map" and len(fld.type.generic_args) == 2:
                # Free map data
                c_type = self._type_to_c(fld.type)
                self._emit(f"{c_type}_free(&self->{fname});")
            elif fld.type.base == "Set" and fld.type.generic_args:
                # Free set data
                c_type = self._type_to_c(fld.type)
                self._emit(f"{c_type}_free(&self->{fname});")

        # 3. Free the object itself
        self._emit("free(self);")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

    # ---- Declarations ----

    def _emit_globals_and_enums(self):
        """Emit global variables and enums before lambdas so lambdas can reference them."""
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, (VarDeclStmt, EnumDecl)):
                self._emit_decl(decl)
                self._emitted_globals.add(id(decl))

    def _emit_declarations(self):
        for decl in self.analyzed.program.declarations:
            if id(decl) not in self._emitted_globals:
                self._emit_decl(decl)

    def _emit_decl(self, decl):
        if isinstance(decl, PreprocessorDirective):
            self._emit_raw(decl.text)
        elif isinstance(decl, ClassDecl):
            self._emit_class(decl)
        elif isinstance(decl, FunctionDecl):
            if decl.is_gpu:
                self._emit_gpu_function(decl)
            else:
                self._emit_function(decl)
        elif isinstance(decl, VarDeclStmt):
            self._emit_var_decl(decl)
        elif isinstance(decl, StructDecl):
            self._emit_struct(decl)
        elif isinstance(decl, EnumDecl):
            self._emit_enum(decl)
        elif isinstance(decl, TypedefDecl):
            self._emit_typedef(decl)

    # ---- Class → struct + functions ----

    def _emit_class(self, decl: ClassDecl):
        if decl.generic_params:
            return  # Generic classes are monomorphized, not emitted directly

        cls = self.class_table[decl.name]
        self.current_class = cls

        # Struct definition is already emitted by _emit_struct_definitions()

        # Collect child-declared method names
        child_method_names = {m.name for m in decl.members if isinstance(m, MethodDecl)}

        # Collect all methods to emit (inherited + child's own)
        methods_to_emit = []
        if decl.parent and decl.parent in self.class_table:
            parent_cls = self.class_table[decl.parent]
            for mname, method in parent_cls.methods.items():
                if mname not in child_method_names and mname != decl.parent:
                    methods_to_emit.append(method)
        for member in decl.members:
            if isinstance(member, MethodDecl):
                methods_to_emit.append(member)

        # Emit forward declarations for all methods (handles cross-references
        # between inherited methods and child overrides)
        for method in methods_to_emit:
            self._emit_method_forward_decl(decl.name, method, cls)

        # Emit method bodies
        for method in methods_to_emit:
            self._emit_method(decl.name, method, cls)

        # Emit property getters and setters
        for member in decl.members:
            if isinstance(member, PropertyDecl):
                self._emit_property_accessors(decl.name, member)

        # Generate default constructor if class has field defaults or auto-properties but no explicit constructor
        has_explicit_constructor = cls.constructor is not None
        has_field_defaults = any(
            isinstance(m, FieldDecl) and m.initializer is not None
            for m in decl.members
        )
        has_auto_properties = any(
            isinstance(m, PropertyDecl) for m in decl.members
        )
        # Also check inherited field defaults (for child classes)
        has_inherited_defaults = False
        if decl.parent and decl.parent in self.class_table:
            parent_cls = self.class_table[decl.parent]
            has_inherited_defaults = any(
                f.initializer is not None for f in parent_cls.fields.values()
            )
        if (has_field_defaults or has_inherited_defaults or has_auto_properties) and not has_explicit_constructor:
            # Merge parent fields (with initializers) + child members for constructor
            all_members = list(decl.members)
            if has_inherited_defaults:
                child_field_names = {m.name for m in decl.members if isinstance(m, FieldDecl)}
                for fname, fld in parent_cls.fields.items():
                    if fname not in child_field_names:
                        all_members.insert(0, fld)
            self._emit_default_constructor(decl.name, all_members, cls)

        # Destroy function for 'delete' keyword (recursive cleanup)
        self._emit_destroy_function(decl.name, cls)

        self.current_class = None

    def _emit_method_forward_decl(self, class_name: str, method: MethodDecl, cls: ClassInfo):
        """Emit a forward declaration for a method."""
        is_constructor = method.name == class_name
        is_static = method.access == "class"
        if is_constructor:
            ret_type = f"{class_name}*"
            func_name = f"{class_name}_new"
        else:
            ret_type = self._type_to_c(method.return_type)
            func_name = f"{class_name}_{method.name}"
        params = []
        if not is_static and not is_constructor:
            params.append(f"{class_name}* self")
        for p in method.params:
            params.append(self._param_to_c(p))
        params_str = ", ".join(params) if params else "void"
        self._emit(f"{ret_type} {func_name}({params_str});")

    def _emit_method(self, class_name: str, method: MethodDecl, cls: ClassInfo):
        is_constructor = method.name == class_name
        is_static = method.access == "class"

        if is_constructor:
            ret_type = f"{class_name}*"
            func_name = f"{class_name}_new"
        else:
            ret_type = self._type_to_c(method.return_type)
            func_name = f"{class_name}_{method.name}"

        # Parameters
        params = []
        if not is_static and not is_constructor:
            params.append(f"{class_name}* self")
        for p in method.params:
            params.append(self._param_to_c(p))
        params_str = ", ".join(params) if params else "void"

        self._emit_line_directive(method.line)
        if is_constructor:
            self._emit(f"{ret_type} {func_name}({params_str}) {{")
            self.indent_level += 1
            self._emit(f"{class_name}* self = ({class_name}*)malloc(sizeof({class_name}));")
            self._emit(f"memset(self, 0, sizeof({class_name}));")
            # Apply field defaults before user constructor body
            for fname, fld in cls.fields.items():
                if fld.initializer:
                    init_c = self._expr_to_c(fld.initializer)
                    self._emit(f"self->{fname} = {init_c};")
            self._emit_block_contents(method.body)
            self._emit("return self;")
            self.indent_level -= 1
            self._emit("}")
        else:
            self._emit(f"{ret_type} {func_name}({params_str}) {{")
            self.indent_level += 1
            self._emit_block_contents(method.body)
            self.indent_level -= 1
            self._emit("}")
        self._emit()

    def _emit_default_constructor(self, class_name: str, members: list, cls: ClassInfo):
        """Generate a default constructor from field initializers."""
        self._emit(f"{class_name}* {class_name}_new(void) {{")
        self.indent_level += 1
        self._emit(f"{class_name}* self = ({class_name}*)malloc(sizeof({class_name}));")
        self._emit(f"memset(self, 0, sizeof({class_name}));")
        for member in members:
            if isinstance(member, FieldDecl) and member.initializer:
                # Handle collection field initializers: List<T> items = [] or Map<K,V> m = {}
                is_collection_init = isinstance(member.initializer, (ListLiteral, MapLiteral))
                is_empty_brace = isinstance(member.initializer, BraceInitializer) and len(member.initializer.elements) == 0
                if (is_collection_init or is_empty_brace) and member.type and member.type.base in ("Map", "List", "Set"):
                    c_type = self._type_to_c(member.type)
                    self._emit(f"self->{member.name} = {c_type}_new();")
                    # Push elements for non-empty list literals
                    if isinstance(member.initializer, ListLiteral):
                        for el in member.initializer.elements:
                            self._emit(f"{c_type}_push(&self->{member.name}, {self._expr_to_c(el)});")
                    elif isinstance(member.initializer, MapLiteral):
                        for key, val in member.initializer.entries:
                            self._emit(f"{c_type}_put(&self->{member.name}, {self._expr_to_c(key)}, {self._expr_to_c(val)});")
                else:
                    init_c = self._expr_to_c(member.initializer)
                    self._emit(f"self->{member.name} = {init_c};")
        self._emit("return self;")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

    # ---- Properties ----

    def _emit_property_accessors(self, class_name: str, prop: PropertyDecl):
        """Emit getter and setter functions for a property."""
        c_type = self._type_to_c(prop.type)
        is_auto_getter = prop.has_getter and prop.getter_body is None
        is_auto_setter = prop.has_setter and prop.setter_body is None

        # Getter
        if prop.has_getter:
            self._emit(f"{c_type} {class_name}_get_{prop.name}({class_name}* self) {{")
            self.indent_level += 1
            if is_auto_getter:
                self._emit(f"return self->_{prop.name};")
            else:
                self._emit_block_contents(prop.getter_body)
            self.indent_level -= 1
            self._emit("}")
            self._emit()

        # Setter
        if prop.has_setter:
            self._emit(f"void {class_name}_set_{prop.name}({class_name}* self, {c_type} value) {{")
            self.indent_level += 1
            if is_auto_setter:
                self._emit(f"self->_{prop.name} = value;")
            else:
                self._emit_block_contents(prop.setter_body)
            self.indent_level -= 1
            self._emit("}")
            self._emit()

    def _is_property_access(self, expr: FieldAccessExpr) -> PropertyDecl | None:
        """Check if a field access is actually a property access. Returns the PropertyDecl or None."""
        obj_type = self.node_types.get(id(expr.obj))
        if obj_type and obj_type.base in self.class_table:
            cls = self.class_table[obj_type.base]
            if expr.field in cls.properties:
                return cls.properties[expr.field]
        # Also check SelfExpr with current_class
        if isinstance(expr.obj, SelfExpr) and self.current_class:
            if expr.field in self.current_class.properties:
                return self.current_class.properties[expr.field]
        return None

    # ---- Function ----

    def _param_to_c(self, p: Param) -> str:
        """Format a parameter as C, handling array suffix."""
        c_type = self._type_to_c(p.type)
        suffix = ""
        if getattr(p.type, 'array_size', None) is not None:
            suffix = f"[{self._expr_to_c(p.type.array_size)}]"
        elif p.type.is_array and not p.type.generic_args:
            suffix = "[]"
        return f"{c_type} {p.name}{suffix}"

    def _emit_function(self, decl: FunctionDecl):
        if decl.body is None:
            return  # Forward declaration — already emitted in forward decls pass
        ret_type = self._type_to_c(decl.return_type)
        params = [self._param_to_c(p) for p in decl.params]
        params_str = ", ".join(params) if params else "void"

        self._emit_line_directive(decl.line)
        self._emit(f"{ret_type} {decl.name}({params_str}) {{")
        self.indent_level += 1
        self._emit_block_contents(decl.body)
        self.indent_level -= 1
        self._emit("}")
        self._emit()

    # ---- GPU function ----

    def _emit_gpu_function(self, decl: FunctionDecl):
        # Emit the kernel body as a GLSL compute shader string
        glsl = self._generate_glsl(decl)
        shader_name = f"__btrc_gpu_shader_{decl.name}"

        self._emit(f'static const char* {shader_name} =')
        for line in glsl.split("\n"):
            self._emit(f'    "{line}\\n"')
        self._emit(";")
        self._emit()

        # Emit a host wrapper function
        params = []
        for p in decl.params:
            params.append(f"{self._type_to_c(p.type)} {p.name}")
        params.append("int __btrc_n")
        params_str = ", ".join(params)

        self._emit(f"void {decl.name}({params_str}) {{")
        self.indent_level += 1
        self._emit(f"/* TODO: OpenGL compute dispatch using {shader_name} */")
        self._emit("/* Buffer setup, shader compilation, and dispatch */")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

    def _generate_glsl(self, decl: FunctionDecl) -> str:
        lines = []
        lines.append("#version 430")
        lines.append("layout(local_size_x = 256) in;")
        for i, p in enumerate(decl.params):
            lines.append(f"layout(std430, binding = {i}) buffer buf{i} {{ float {p.name}[]; }};")
        lines.append("void main() {")
        lines.append("    uint i = gl_GlobalInvocationID.x;")
        # Emit body as GLSL (simplified — real impl would translate AST)
        lines.append("    /* kernel body */")
        lines.append("}")
        return "\n".join(lines)

    # ---- Struct / Enum / Typedef ----

    def _emit_struct(self, decl: StructDecl):
        if decl.fields:
            self._emit(f"typedef struct {decl.name} {{")
            self.indent_level += 1
            for f in decl.fields:
                suffix = ""
                if getattr(f.type, 'array_size', None) is not None:
                    suffix = f"[{self._expr_to_c(f.type.array_size)}]"
                elif f.type.is_array and not f.type.generic_args:
                    suffix = "[]"
                self._emit(f"{self._type_to_c(f.type)} {f.name}{suffix};")
            self.indent_level -= 1
            self._emit(f"}} {decl.name};")
        else:
            self._emit(f"struct {decl.name};")
        self._emit()

    def _emit_enum(self, decl: EnumDecl):
        self._emit("typedef enum {")
        self.indent_level += 1
        for i, (name, val) in enumerate(decl.values):
            suffix = "," if i < len(decl.values) - 1 else ""
            if val:
                self._emit(f"{name} = {self._expr_to_c(val)}{suffix}")
            else:
                self._emit(f"{name}{suffix}")
        self.indent_level -= 1
        self._emit(f"}} {decl.name};")
        self._emit()

    def _emit_typedef(self, decl: TypedefDecl):
        self._emit(f"typedef {self._type_to_c(decl.original)} {decl.alias};")
        self._emit()

    # ---- Var decl ----

    def _emit_var_decl(self, stmt: VarDeclStmt):
        # Function pointer type (from lambda inference)
        if stmt.type and stmt.type.base == "__fn_ptr" and stmt.type.generic_args:
            ret_type = self._type_to_c(stmt.type.generic_args[0])
            param_types = ", ".join(self._type_to_c(a) for a in stmt.type.generic_args[1:])
            if not param_types:
                param_types = "void"
            init = f" = {self._expr_to_c(stmt.initializer)}" if stmt.initializer else ""
            self._emit(f"{ret_type} (*{stmt.name})({param_types}){init};")
            return

        c_type = self._type_to_c(stmt.type)
        array_suffix = ""
        if getattr(stmt.type, 'array_size', None) is not None:
            array_suffix = f"[{self._expr_to_c(stmt.type.array_size)}]"
        elif stmt.type.is_array and not stmt.type.generic_args:
            array_suffix = "[]"
        if stmt.initializer:
            init = self._emit_initializer(stmt.type, stmt.initializer)
            self._emit(f"{c_type} {stmt.name}{array_suffix} = {init};")
        else:
            self._emit(f"{c_type} {stmt.name}{array_suffix};")

    # ---- Statements ----

    def _emit_block_contents(self, block: Block):
        if block is None:
            return
        for stmt in block.statements:
            self._emit_stmt(stmt)

    def _emit_stmt(self, stmt):
        self._emit_line_directive(stmt.line)
        if isinstance(stmt, VarDeclStmt):
            self._emit_var_decl_stmt(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                if isinstance(stmt.value, FStringLiteral):
                    tmp = self._emit_fstring_as_value(stmt.value)
                    self._emit(f"return {tmp};")
                else:
                    self._emit(f"return {self._expr_to_c(stmt.value)};")
            else:
                self._emit("return;")
        elif isinstance(stmt, IfStmt):
            self._emit_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._emit(f"while ({self._expr_to_c(stmt.condition)}) {{")
            self.indent_level += 1
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit("}")
        elif isinstance(stmt, DoWhileStmt):
            self._emit("do {")
            self.indent_level += 1
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit(f"}} while ({self._expr_to_c(stmt.condition)});")
        elif isinstance(stmt, ForInStmt):
            self._emit_for_in(stmt)
        elif isinstance(stmt, ParallelForStmt):
            self._emit_parallel_for(stmt)
        elif isinstance(stmt, CForStmt):
            self._emit_c_for(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._emit_switch(stmt)
        elif isinstance(stmt, BreakStmt):
            self._emit("break;")
        elif isinstance(stmt, ContinueStmt):
            self._emit("continue;")
        elif isinstance(stmt, ExprStmt):
            if isinstance(stmt.expr, AssignExpr) and isinstance(stmt.expr.value, FStringLiteral):
                target = self._expr_to_c(stmt.expr.target)
                tmp = self._emit_fstring_as_value(stmt.expr.value)
                self._emit(f"{target} = {tmp};")
            else:
                self._emit(f"{self._expr_to_c(stmt.expr)};")
        elif isinstance(stmt, DeleteStmt):
            del_type = self.node_types.get(id(stmt.expr))
            if del_type and del_type.base in self.class_table:
                self._emit(f"{del_type.base}_destroy({self._expr_to_c(stmt.expr)});")
            else:
                self._emit(f"free({self._expr_to_c(stmt.expr)});")
        elif isinstance(stmt, TryCatchStmt):
            self._emit_try_catch(stmt)
        elif isinstance(stmt, ThrowStmt):
            self._emit(f"__btrc_throw({self._expr_to_c(stmt.expr)});")
        elif isinstance(stmt, Block):
            self._emit("{")
            self.indent_level += 1
            self._emit_block_contents(stmt)
            self.indent_level -= 1
            self._emit("}")

    def _emit_var_decl_stmt(self, stmt: VarDeclStmt):
        # Function pointer type (from lambda inference): emit as ret_type (*name)(param_types)
        if stmt.type and stmt.type.base == "__fn_ptr" and stmt.type.generic_args:
            ret_type = self._type_to_c(stmt.type.generic_args[0])
            param_types = ", ".join(self._type_to_c(a) for a in stmt.type.generic_args[1:])
            if not param_types:
                param_types = "void"
            init = f" = {self._expr_to_c(stmt.initializer)}" if stmt.initializer else ""
            self._emit(f"{ret_type} (*{stmt.name})({param_types}){init};")
            return

        c_type = self._type_to_c(stmt.type)
        # C-style array: type name[N] or type name[]
        array_suffix = ""
        if getattr(stmt.type, 'array_size', None) is not None:
            array_suffix = f"[{self._expr_to_c(stmt.type.array_size)}]"
        elif stmt.type.is_array and not stmt.type.generic_args:
            array_suffix = "[]"
        if stmt.initializer:
            if isinstance(stmt.initializer, ListLiteral):
                self._emit_list_init(c_type, stmt.name, stmt.type, stmt.initializer)
            elif isinstance(stmt.initializer, MapLiteral):
                self._emit_map_init(c_type, stmt.name, stmt.type, stmt.initializer)
            elif isinstance(stmt.initializer, BraceInitializer) and len(stmt.initializer.elements) == 0 and stmt.type.base in ("Map", "List", "Set"):
                self._emit(f"{c_type} {stmt.name} = {c_type}_new();")
            elif isinstance(stmt.initializer, CallExpr) and self._is_constructor_call(stmt.initializer):
                self._emit_constructor_init(c_type, stmt.name, stmt.initializer)
            elif isinstance(stmt.initializer, FStringLiteral):
                tmp = self._emit_fstring_as_value(stmt.initializer)
                self._emit(f"{c_type} {stmt.name}{array_suffix} = {tmp};")
            else:
                init = self._expr_to_c(stmt.initializer)
                self._emit(f"{c_type} {stmt.name}{array_suffix} = {init};")
        else:
            self._emit(f"{c_type} {stmt.name}{array_suffix};")

    def _emit_list_init(self, c_type: str, name: str, type_expr: TypeExpr, lit: ListLiteral):
        self._emit(f"{c_type} {name} = {c_type}_new();")
        for el in lit.elements:
            self._emit(f"{c_type}_push(&{name}, {self._expr_to_c(el)});")

    def _emit_map_init(self, c_type: str, name: str, type_expr: TypeExpr, lit: MapLiteral):
        self._emit(f"{c_type} {name} = {c_type}_new();")
        for key, val in lit.entries:
            self._emit(f"{c_type}_put(&{name}, {self._expr_to_c(key)}, {self._expr_to_c(val)});")

    def _emit_constructor_init(self, c_type: str, name: str, call: CallExpr):
        class_name = call.callee.name
        args = self._fill_default_args(call.args, class_name=class_name)
        self._emit(f"{c_type} {name} = {class_name}_new({', '.join(args)});")

    def _is_constructor_call(self, expr: CallExpr) -> bool:
        return isinstance(expr.callee, Identifier) and expr.callee.name in self.class_table

    def _strip_outer_parens(self, s: str) -> str:
        """Strip matching outer parentheses from a C expression string.
        E.g. '(a == b)' -> 'a == b', but '(a) + (b)' is left unchanged."""
        if s.startswith("(") and s.endswith(")"):
            depth = 0
            for i, ch in enumerate(s):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if depth == 0 and i < len(s) - 1:
                    return s  # parens don't match as outer pair
            return s[1:-1]
        return s

    def _emit_if(self, stmt: IfStmt):
        cond = self._strip_outer_parens(self._expr_to_c(stmt.condition))
        self._emit(f"if ({cond}) {{")
        self.indent_level += 1
        self._emit_block_contents(stmt.then_block)
        self.indent_level -= 1
        if isinstance(stmt.else_block, IfStmt):
            self._emit("} else")
            self._emit_if(stmt.else_block)
        elif isinstance(stmt.else_block, Block):
            self._emit("} else {")
            self.indent_level += 1
            self._emit_block_contents(stmt.else_block)
            self.indent_level -= 1
            self._emit("}")
        else:
            self._emit("}")

    def _emit_for_in(self, stmt: ForInStmt):
        # Check for range() calls: for x in range(n) or range(a, b)
        if self._is_range_call(stmt.iterable):
            self._emit_range_for(stmt)
            return

        iterable = self._expr_to_c(stmt.iterable)
        var = stmt.var_name
        type_info = self.node_types.get(id(stmt.iterable))
        acc = "->" if (type_info and type_info.pointer_depth > 0) else "."

        # Map iteration: for k, v in map  OR  for k in map
        if type_info and type_info.base == "Map" and len(type_info.generic_args) == 2:
            k_type = self._type_to_c(type_info.generic_args[0])
            v_type = self._type_to_c(type_info.generic_args[1])
            idx = f"__btrc_i_{var}"
            self._emit(f"for (int {idx} = 0; {idx} < {iterable}{acc}cap; {idx}++) {{")
            self.indent_level += 1
            self._emit(f"if (!{iterable}{acc}buckets[{idx}].occupied) continue;")
            self._emit(f"{k_type} {var} = {iterable}{acc}buckets[{idx}].key;")
            if stmt.var_name2:
                self._emit(f"{v_type} {stmt.var_name2} = {iterable}{acc}buckets[{idx}].value;")
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit("}")
            return

        # Set iteration: for val in set
        if type_info and type_info.base == "Set" and type_info.generic_args:
            elem_c_type = self._type_to_c(type_info.generic_args[0])
            idx = f"__btrc_i_{var}"
            self._emit(f"for (int {idx} = 0; {idx} < {iterable}{acc}cap; {idx}++) {{")
            self.indent_level += 1
            self._emit(f"if (!{iterable}{acc}buckets[{idx}].occupied) continue;")
            self._emit(f"{elem_c_type} {var} = {iterable}{acc}buckets[{idx}].key;")
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit("}")
            return

        # String array iteration: for s in str.split(...) → iterate char** (NULL-terminated)
        if type_info and type_info.base == "string" and type_info.pointer_depth >= 1:
            idx = f"__btrc_i_{var}"
            self._emit(f"for (int {idx} = 0; {iterable}[{idx}] != NULL; {idx}++) {{")
            self.indent_level += 1
            self._emit(f"char* {var} = {iterable}[{idx}];")
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit("}")
            return

        # String iteration: for c in str → iterate each char
        if type_info and (type_info.base == "string" or
                          (type_info.base == "char" and type_info.pointer_depth >= 1)):
            idx = f"__btrc_i_{var}"
            self._emit(f"for (int {idx} = 0; {iterable}[{idx}] != '\\0'; {idx}++) {{")
            self.indent_level += 1
            self._emit(f"char {var} = {iterable}[{idx}];")
            self._emit_block_contents(stmt.body)
            self.indent_level -= 1
            self._emit("}")
            return

        # List/Array iteration
        idx = f"__btrc_i_{var}"
        self._emit(f"for (int {idx} = 0; {idx} < {iterable}{acc}len; {idx}++) {{")
        self.indent_level += 1
        elem_c_type = self._get_element_type_c(stmt.iterable)
        self._emit(f"{elem_c_type} {var} = {iterable}{acc}data[{idx}];")
        self._emit_block_contents(stmt.body)
        self.indent_level -= 1
        self._emit("}")

    def _is_range_call(self, expr) -> bool:
        return (isinstance(expr, CallExpr) and
                isinstance(expr.callee, Identifier) and
                expr.callee.name == "range")

    def _emit_range_for(self, stmt: ForInStmt):
        call = stmt.iterable
        var = stmt.var_name
        args = call.args
        if len(args) == 1:
            end = self._expr_to_c(args[0])
            self._emit(f"for (int {var} = 0; {var} < {end}; {var}++) {{")
        elif len(args) == 2:
            start = self._expr_to_c(args[0])
            end = self._expr_to_c(args[1])
            self._emit(f"for (int {var} = {start}; {var} < {end}; {var}++) {{")
        elif len(args) == 3:
            start = self._expr_to_c(args[0])
            end = self._expr_to_c(args[1])
            step = self._expr_to_c(args[2])
            self._step_counter += 1
            step_var = f"__btrc_step_{self._step_counter}"
            self._emit(f"int {step_var} = {step};")
            self._emit(f"for (int {var} = {start}; ({step_var} > 0 ? {var} < {end} : {var} > {end}); {var} += {step_var}) {{")
        else:
            self._emit("/* invalid range() call */")
            return
        self.indent_level += 1
        self._emit_block_contents(stmt.body)
        self.indent_level -= 1
        self._emit("}")

    def _emit_parallel_for(self, stmt: ParallelForStmt):
        iterable = self._expr_to_c(stmt.iterable)
        var = stmt.var_name
        idx = f"__btrc_i_{var}"
        type_info = self.node_types.get(id(stmt.iterable))
        acc = "->" if (type_info and type_info.pointer_depth > 0) else "."
        self._emit("#pragma omp parallel for")
        self._emit(f"for (int {idx} = 0; {idx} < {iterable}{acc}len; {idx}++) {{")
        self.indent_level += 1
        elem_c_type = self._get_element_type_c(stmt.iterable)
        self._emit(f"{elem_c_type} {var} = {iterable}{acc}data[{idx}];")
        self._emit_block_contents(stmt.body)
        self.indent_level -= 1
        self._emit("}")

    def _emit_c_for(self, stmt: CForStmt):
        # Init
        if isinstance(stmt.init, VarDeclStmt):
            init_str = f"{self._type_to_c(stmt.init.type)} {stmt.init.name}"
            if stmt.init.initializer:
                init_str += f" = {self._expr_to_c(stmt.init.initializer)}"
        elif stmt.init:
            init_str = self._expr_to_c(stmt.init)
        else:
            init_str = ""

        cond_str = self._expr_to_c(stmt.condition) if stmt.condition else ""
        update_str = self._expr_to_c(stmt.update) if stmt.update else ""

        self._emit(f"for ({init_str}; {cond_str}; {update_str}) {{")
        self.indent_level += 1
        self._emit_block_contents(stmt.body)
        self.indent_level -= 1
        self._emit("}")

    def _emit_switch(self, stmt: SwitchStmt):
        self._emit(f"switch ({self._expr_to_c(stmt.value)}) {{")
        self.indent_level += 1
        for case in stmt.cases:
            if case.value:
                self._emit(f"case {self._expr_to_c(case.value)}:")
            else:
                self._emit("default:")
            self.indent_level += 1
            for s in case.body:
                self._emit_stmt(s)
            # Auto-insert break if case doesn't end with break/return
            if not self._case_ends_with_exit(case.body):
                self._emit("break;")
            self.indent_level -= 1
        self.indent_level -= 1
        self._emit("}")

    def _case_ends_with_exit(self, body: list) -> bool:
        """Check if a switch case body ends with break, return, or throw.
        Empty bodies are treated as intentional fallthrough."""
        if not body:
            return True  # Empty body = intentional fallthrough (e.g., case 1: case 2:)
        last = body[-1]
        return isinstance(last, (BreakStmt, ReturnStmt, ThrowStmt))

    # ---- Expressions → C code ----

    def _expr_to_c(self, expr) -> str:
        if expr is None:
            return ""

        if isinstance(expr, IntLiteral):
            # Convert 0o/0O octal prefix to C format (0 prefix)
            if expr.raw.startswith(("0o", "0O")):
                return "0" + expr.raw[2:]
            return expr.raw

        if isinstance(expr, FloatLiteral):
            return expr.raw

        if isinstance(expr, StringLiteral):
            return expr.value

        if isinstance(expr, CharLiteral):
            return expr.value

        if isinstance(expr, BoolLiteral):
            return "true" if expr.value else "false"

        if isinstance(expr, NullLiteral):
            return "NULL"

        if isinstance(expr, Identifier):
            return expr.name

        if isinstance(expr, SelfExpr):
            return "self"

        if isinstance(expr, BinaryExpr):
            # Check for operator overloading
            left_type = self.node_types.get(id(expr.left))
            if left_type and left_type.base in self.class_table:
                op_method = self._op_to_method_name(expr.op)
                if op_method:
                    cls = self.class_table[left_type.base]
                    if op_method in cls.methods:
                        left_c = self._expr_to_c(expr.left)
                        right_c = self._expr_to_c(expr.right)
                        cn = left_type.base
                        # All class instances are pointers — pass directly
                        return f"{cn}_{op_method}({left_c}, {right_c})"
            # Null coalescing: a ?? b → use temp to avoid evaluating left twice
            if expr.op == "??":
                left = self._expr_to_c(expr.left)
                right = self._expr_to_c(expr.right)
                left_type = self.node_types.get(id(expr.left))
                c_type = self._type_to_c(left_type) if left_type else "void*"
                tmp = f"__btrc_tmp_{self._tmp_counter}"
                self._tmp_counter += 1
                return f"({{ {c_type} {tmp} = {left}; {tmp} != NULL ? {tmp} : {right}; }})"
            # String operations
            if left_type and left_type.base == "string":
                left = self._expr_to_c(expr.left)
                right = self._expr_to_c(expr.right)
                if expr.op == "+":
                    return f"__btrc_strcat({left}, {right})"
                if expr.op == "==":
                    return f"(strcmp({left}, {right}) == 0)"
                if expr.op == "!=":
                    return f"(strcmp({left}, {right}) != 0)"
                if expr.op in ("<", ">", "<=", ">="):
                    return f"(strcmp({left}, {right}) {expr.op} 0)"
            left = self._expr_to_c(expr.left)
            right = self._expr_to_c(expr.right)
            # Division and modulo: use bounds-checked helpers for known numeric types
            if expr.op in ("/", "%"):
                left_t = self.node_types.get(id(expr.left))
                right_t = self.node_types.get(id(expr.right))
                known_numeric = left_t and left_t.base in ("int", "float", "double") and left_t.pointer_depth == 0
                if known_numeric:
                    if expr.op == "/":
                        if (left_t and left_t.base in ("float", "double")) or (right_t and right_t.base in ("float", "double")):
                            return f"__btrc_div_double({left}, {right})"
                        return f"__btrc_div_int({left}, {right})"
                    if expr.op == "%":
                        return f"__btrc_mod_int({left}, {right})"
            return f"({left} {expr.op} {right})"

        if isinstance(expr, UnaryExpr):
            # Check for unary operator overloading (__neg__)
            if expr.prefix and expr.op == "-":
                operand_type = self.node_types.get(id(expr.operand))
                if operand_type and operand_type.base in self.class_table:
                    cls = self.class_table[operand_type.base]
                    if "__neg__" in cls.methods:
                        operand_c = self._expr_to_c(expr.operand)
                        cn = operand_type.base
                        if operand_type.pointer_depth > 0:
                            return f"{cn}___neg__({operand_c})"
                        else:
                            return f"{cn}___neg__(&{operand_c})"
            operand = self._expr_to_c(expr.operand)
            if expr.prefix:
                return f"({expr.op}{operand})"
            else:
                return f"({operand}{expr.op})"

        if isinstance(expr, CallExpr):
            return self._call_to_c(expr)

        if isinstance(expr, IndexExpr):
            obj = self._expr_to_c(expr.obj)
            idx = self._expr_to_c(expr.index)
            # Check if obj is a collection type — translate to bounds-checked access
            coll_type = self._get_collection_type_for_obj(expr.obj)
            if coll_type and coll_type.base == "List":
                c_type = self._type_to_c(coll_type)
                obj_ref = obj if coll_type.pointer_depth > 0 else f"&{obj}"
                return f"{c_type}_get({obj_ref}, {idx})"
            if coll_type and coll_type.base == "Array":
                if coll_type.pointer_depth > 0:
                    return f"{obj}->data[{idx}]"
                return f"{obj}.data[{idx}]"
            if coll_type and coll_type.base == "Map":
                c_type = self._type_to_c(coll_type)
                obj_ref = obj if coll_type.pointer_depth > 0 else f"&{obj}"
                return f"{c_type}_get({obj_ref}, {idx})"
            return f"{obj}[{idx}]"

        if isinstance(expr, FieldAccessExpr):
            return self._field_access_to_c(expr)

        if isinstance(expr, AssignExpr):
            # Check if this is a property setter: obj.prop = value
            if isinstance(expr.target, FieldAccessExpr) and expr.op == "=":
                prop = self._is_property_access(expr.target)
                if prop and prop.has_setter:
                    obj_c = self._expr_to_c(expr.target.obj)
                    class_name = self._get_class_name_for_obj(expr.target.obj)
                    value_c = self._expr_to_c(expr.value)
                    if class_name:
                        return f"{class_name}_set_{expr.target.field}({obj_c}, {value_c})"
            # Check if this is list[i] = value or map[key] = value assignment
            if isinstance(expr.target, IndexExpr) and expr.op == "=":
                coll_type = self._get_collection_type_for_obj(expr.target.obj)
                if coll_type and coll_type.base == "List":
                    c_type = self._type_to_c(coll_type)
                    obj_c = self._expr_to_c(expr.target.obj)
                    obj_ref = obj_c if coll_type.pointer_depth > 0 else f"&{obj_c}"
                    idx_c = self._expr_to_c(expr.target.index)
                    val_c = self._expr_to_c(expr.value)
                    return f"{c_type}_set({obj_ref}, {idx_c}, {val_c})"
                if coll_type and coll_type.base == "Map":
                    c_type = self._type_to_c(coll_type)
                    obj_c = self._expr_to_c(expr.target.obj)
                    obj_ref = obj_c if coll_type.pointer_depth > 0 else f"&{obj_c}"
                    key_c = self._expr_to_c(expr.target.index)
                    val_c = self._expr_to_c(expr.value)
                    return f"{c_type}_put({obj_ref}, {key_c}, {val_c})"
            target = self._expr_to_c(expr.target)
            # Handle Map/List/empty-brace literal assignments (e.g. self.counts = {}, self.items = [])
            is_collection_lit = isinstance(expr.value, (MapLiteral, ListLiteral))
            is_empty_brace = isinstance(expr.value, BraceInitializer) and len(expr.value.elements) == 0
            if is_collection_lit or is_empty_brace:
                target_type = self.node_types.get(id(expr.target))
                if target_type and target_type.base in ("Map", "List", "Set"):
                    c_type = self._type_to_c(target_type)
                    return f"({target} = {c_type}_new())"
            value = self._expr_to_c(expr.value)
            # String += concatenation
            if expr.op == "+=" :
                target_type = self.node_types.get(id(expr.target))
                if target_type and target_type.base == "string":
                    return f"({target} = __btrc_strcat({target}, {value}))"
            # Safe /= and %= compound assignments
            if expr.op in ("/=", "%="):
                target_type = self.node_types.get(id(expr.target))
                if target_type and target_type.base in ("int", "float", "double") and target_type.pointer_depth == 0:
                    if expr.op == "/=":
                        if target_type.base in ("float", "double"):
                            return f"({target} = __btrc_div_double({target}, {value}))"
                        return f"({target} = __btrc_div_int({target}, {value}))"
                    if expr.op == "%=":
                        return f"({target} = __btrc_mod_int({target}, {value}))"
            return f"({target} {expr.op} {value})"

        if isinstance(expr, TernaryExpr):
            cond = self._expr_to_c(expr.condition)
            t = self._expr_to_c(expr.true_expr)
            f = self._expr_to_c(expr.false_expr)
            return f"({cond} ? {t} : {f})"

        if isinstance(expr, CastExpr):
            target = self._type_to_c(expr.target_type)
            e = self._expr_to_c(expr.expr)
            return f"(({target}){e})"

        if isinstance(expr, SizeofExpr):
            if isinstance(expr.operand, TypeExpr):
                return f"sizeof({self._type_to_c(expr.operand)})"
            else:
                return f"sizeof({self._expr_to_c(expr.operand)})"

        if isinstance(expr, NewExpr):
            return self._new_to_c(expr)

        if isinstance(expr, ListLiteral):
            # List literals in expression context — rare, usually in var decl
            return "/* list literal */"

        if isinstance(expr, FStringLiteral):
            return self._fstring_to_c(expr)

        if isinstance(expr, MapLiteral):
            return "/* map literal */"

        if isinstance(expr, TupleLiteral):
            return self._tuple_to_c(expr)

        if isinstance(expr, BraceInitializer):
            elems = ", ".join(self._expr_to_c(e) for e in expr.elements)
            return f"{{{elems}}}"

        if isinstance(expr, LambdaExpr):
            # Return the pre-generated function name
            return getattr(expr, '_c_name', '/* lambda */')

        return "/* unknown expr */"

    def _call_to_c(self, expr: CallExpr) -> str:
        # Check if this is a method call: callee is FieldAccessExpr
        if isinstance(expr.callee, FieldAccessExpr):
            return self._method_call_to_c(expr)

        # Check if this is a constructor call
        if isinstance(expr.callee, Identifier) and expr.callee.name in self.class_table:
            class_name = expr.callee.name
            args = self._fill_default_args(expr.args, class_name=class_name)
            return f"{class_name}_new({', '.join(args)})"

        # Built-in print() — intercept if no user-defined print function exists
        if isinstance(expr.callee, Identifier) and expr.callee.name == "print":
            if not self._has_user_function("print"):
                return self._print_to_c(expr)

        # Regular function call — fill defaults if applicable
        if isinstance(expr.callee, Identifier):
            filled = self._fill_default_args(expr.args, func_name=expr.callee.name)
            callee = self._expr_to_c(expr.callee)
            return f"{callee}({', '.join(filled)})"

        callee = self._expr_to_c(expr.callee)
        args = ", ".join(self._expr_to_c(a) for a in expr.args)
        return f"{callee}({args})"

    def _fill_default_args(self, provided_args: list, func_name: str = None,
                           class_name: str = None, method_name: str = None) -> list[str]:
        """Fill in default values for missing arguments."""
        params = None
        if class_name and method_name:
            cls = self.class_table.get(class_name)
            if cls and method_name in cls.methods:
                params = cls.methods[method_name].params
        elif class_name:
            cls = self.class_table.get(class_name)
            if cls and cls.constructor:
                params = cls.constructor.params
        elif func_name:
            for decl in self.analyzed.program.declarations:
                if isinstance(decl, FunctionDecl) and decl.name == func_name:
                    params = decl.params
                    break

        args_c = [self._expr_to_c(a) for a in provided_args]
        if params and len(args_c) < len(params):
            for i in range(len(args_c), len(params)):
                if params[i].default is not None:
                    args_c.append(self._expr_to_c(params[i].default))
        return args_c

    def _method_call_to_c(self, expr: CallExpr) -> str:
        access = expr.callee  # FieldAccessExpr
        obj = access.obj
        method_name = access.field
        args_exprs = expr.args

        # Stdlib static method calls: Strings.method(), Math.method()
        # Only dispatch to stdlib if not a user-defined class
        if isinstance(obj, Identifier) and obj.name == "Strings" and obj.name not in self.class_table:
            return self._strings_static_to_c(method_name, args_exprs)
        if isinstance(obj, Identifier) and obj.name == "Math" and obj.name not in self.class_table:
            return self._math_static_to_c(method_name, args_exprs)

        # Static method call: ClassName.method(args)
        if isinstance(obj, Identifier) and obj.name in self.class_table:
            class_name = obj.name
            args = ", ".join(self._expr_to_c(a) for a in args_exprs)
            return f"{class_name}_{method_name}({args})"

        obj_c = self._expr_to_c(obj)

        # Numeric/bool type method call: n.toString() → sprintf helper
        num_type = self.node_types.get(id(obj))
        if num_type and num_type.base in ("int", "float", "double", "long", "bool") and num_type.pointer_depth == 0:
            if method_name == "toString":
                return self._numeric_to_string(obj_c, num_type.base)

        # String method call: s.len() → strlen(s), etc.
        str_type = self._get_string_type_for_obj(obj)
        if str_type:
            return self._string_method_to_c(obj_c, method_name, args_exprs)

        # Collection method call: obj.push(x) → btrc_List_T_push(&obj, x)
        coll_type = self._get_collection_type_for_obj(obj)
        if coll_type:
            return self._collection_method_to_c(coll_type, obj_c, method_name, args_exprs, access.arrow)

        # Instance method call: obj.method(args) → Class_method(obj, args)
        # All class instances are pointers (reference types), so pass directly
        class_name = self._get_class_name_for_obj(obj)
        if class_name:
            all_args = [obj_c] + self._fill_default_args(
                args_exprs, class_name=class_name, method_name=method_name)
            args_str = ", ".join(all_args)
            return f"{class_name}_{method_name}({args_str})"

        # Fallback: emit as C-style obj.method(args) — might be a struct function pointer
        if access.arrow:
            args = ", ".join(self._expr_to_c(a) for a in args_exprs)
            return f"{obj_c}->{method_name}({args})"
        else:
            args = ", ".join(self._expr_to_c(a) for a in args_exprs)
            return f"{obj_c}.{method_name}({args})"

    # Methods where the second argument is a collection pointer (same type as self)
    _COLLECTION_PTR_ARG_METHODS = {"extend", "unite", "intersect", "subtract", "merge"}

    def _collection_method_to_c(self, type_info: TypeExpr, obj_c: str,
                                 method_name: str, args_exprs: list, arrow: bool) -> str:
        """Translate collection method calls: obj.push(x) → btrc_List_T_push(&obj, x)"""
        # Resolve aliases
        if method_name == "addAll":
            method_name = "extend"
        elif method_name == "subList":
            method_name = "slice"
        elif method_name == "removeAt":
            method_name = "remove"
        c_type = self._type_to_c(type_info)
        obj_ref = obj_c if (arrow or type_info.pointer_depth > 0) else f"&{obj_c}"
        translated_args = []
        for i, a in enumerate(args_exprs):
            arg_c = self._expr_to_c(a)
            # For methods taking a second collection by pointer, add & if needed
            if i == 0 and method_name in self._COLLECTION_PTR_ARG_METHODS:
                arg_type = self.node_types.get(id(a))
                if arg_type and arg_type.pointer_depth == 0:
                    arg_c = f"&{arg_c}"
            translated_args.append(arg_c)
        args = [obj_ref] + translated_args
        return f"{c_type}_{method_name}({', '.join(args)})"

    def _get_class_name_for_obj(self, obj) -> str | None:
        """Determine the class name for an object expression using type info."""
        # For self expressions, always use current_class — this ensures
        # inherited methods dispatch to the child class's methods
        if isinstance(obj, SelfExpr) and self.current_class:
            return self.current_class.name

        # Check node_types from analyzer
        type_info = self.node_types.get(id(obj))
        if type_info and type_info.base in self.class_table:
            return type_info.base

        # Fallback: Identifier whose name IS a class (static call context)
        if isinstance(obj, Identifier) and obj.name in self.class_table:
            return obj.name
        return None

    def _has_user_function(self, name: str) -> bool:
        """Check if the user has defined a function with the given name."""
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, FunctionDecl) and decl.name == name:
                return True
        return False

    def _numeric_to_string(self, obj_c: str, base_type: str) -> str:
        """Emit toString() for numeric/bool types."""
        if base_type == "int":
            return f"__btrc_intToString({obj_c})"
        elif base_type == "long":
            return f"__btrc_longToString({obj_c})"
        elif base_type == "float":
            return f"__btrc_floatToString({obj_c})"
        elif base_type == "double":
            return f"__btrc_doubleToString({obj_c})"
        elif base_type == "bool":
            return f"({obj_c} ? \"true\" : \"false\")"
        return f"/* unknown numeric toString for {base_type} */"

    def _get_string_type_for_obj(self, obj) -> bool:
        """Check if obj is a string type (char*)."""
        type_info = self.node_types.get(id(obj))
        if type_info:
            if type_info.base == "string":
                return True
            if type_info.base == "char" and type_info.pointer_depth >= 1:
                return True
        return False

    def _string_method_to_c(self, obj_c: str, method_name: str, args_exprs: list) -> str:
        """Translate string method calls to C stdlib calls."""
        args = [self._expr_to_c(a) for a in args_exprs]

        if method_name == "len" or method_name == "byteLen":
            return f"(int)strlen({obj_c})"
        elif method_name == "charLen":
            return f"__btrc_utf8_charlen({obj_c})"
        elif method_name == "contains":
            return f"__btrc_strContains({obj_c}, {args[0]})"
        elif method_name == "startsWith":
            return f"__btrc_startsWith({obj_c}, {args[0]})"
        elif method_name == "endsWith":
            return f"__btrc_endsWith({obj_c}, {args[0]})"
        elif method_name == "substring":
            return f"__btrc_substring({obj_c}, {', '.join(args)})"
        elif method_name == "trim":
            return f"__btrc_trim({obj_c})"
        elif method_name == "toUpper":
            return f"__btrc_toUpper({obj_c})"
        elif method_name == "toLower":
            return f"__btrc_toLower({obj_c})"
        elif method_name == "indexOf":
            return f"__btrc_indexOf({obj_c}, {args[0]})"
        elif method_name == "split":
            return f"__btrc_split({obj_c}, {args[0]})"
        elif method_name == "charAt":
            return f"__btrc_charAt({obj_c}, {args[0]})"
        elif method_name == "equals":
            return f"(strcmp({obj_c}, {args[0]}) == 0)"
        elif method_name == "lastIndexOf":
            return f"__btrc_lastIndexOf({obj_c}, {args[0]})"
        elif method_name == "replace":
            return f"__btrc_replace({obj_c}, {args[0]}, {args[1]})"
        elif method_name == "repeat":
            return f"__btrc_repeat({obj_c}, {args[0]})"
        elif method_name == "count":
            return f"__btrc_count({obj_c}, {args[0]})"
        elif method_name == "find":
            return f"__btrc_find({obj_c}, {args[0]}, {args[1]})"
        elif method_name == "lstrip":
            return f"__btrc_lstrip({obj_c})"
        elif method_name == "rstrip":
            return f"__btrc_rstrip({obj_c})"
        elif method_name == "capitalize":
            return f"__btrc_capitalize({obj_c})"
        elif method_name == "title":
            return f"__btrc_title({obj_c})"
        elif method_name == "swapCase":
            return f"__btrc_swapCase({obj_c})"
        elif method_name == "padLeft":
            return f"__btrc_padLeft({obj_c}, {args[0]}, {args[1]})"
        elif method_name == "padRight":
            return f"__btrc_padRight({obj_c}, {args[0]}, {args[1]})"
        elif method_name == "center":
            return f"__btrc_center({obj_c}, {args[0]}, {args[1]})"
        elif method_name == "isBlank":
            return f"__btrc_isBlank({obj_c})"
        elif method_name == "isAlnum":
            return f"__btrc_isAlnumStr({obj_c})"
        elif method_name == "isUpper":
            return f"__btrc_isUpper({obj_c})"
        elif method_name == "isLower":
            return f"__btrc_isLower({obj_c})"
        elif method_name == "toInt":
            return f"atoi({obj_c})"
        elif method_name == "toFloat":
            return f"((float)atof({obj_c}))"
        elif method_name == "toDouble":
            return f"atof({obj_c})"
        elif method_name == "toLong":
            return f"atol({obj_c})"
        elif method_name == "toBool":
            return f"(strlen({obj_c}) > 0 && strcmp({obj_c}, \"false\") != 0 && strcmp({obj_c}, \"0\") != 0)"
        elif method_name == "reverse":
            return f"__btrc_reverse({obj_c})"
        elif method_name == "isEmpty":
            return f"__btrc_isEmpty({obj_c})"
        elif method_name == "removePrefix":
            return f"__btrc_removePrefix({obj_c}, {args[0]})"
        elif method_name == "removeSuffix":
            return f"__btrc_removeSuffix({obj_c}, {args[0]})"
        elif method_name == "zfill":
            return f"__btrc_zfill({obj_c}, {args[0]})"
        elif method_name == "isDigitStr":
            return f"__btrc_isDigitStr({obj_c})"
        elif method_name == "isAlphaStr":
            return f"__btrc_isAlphaStr({obj_c})"
        else:
            return f"/* unknown string method: {method_name} */"

    def _strings_static_to_c(self, method_name: str, args_exprs: list) -> str:
        """Translate Strings.method(...) static calls to C."""
        args = [self._expr_to_c(a) for a in args_exprs]
        if method_name == "repeat":
            return f"__btrc_repeat({args[0]}, {args[1]})"
        elif method_name == "join":
            return f"__btrc_join({args[0]}, {args[1]})"
        elif method_name == "replace":
            return f"__btrc_replace({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "isDigit":
            return f"isdigit((unsigned char){args[0]})"
        elif method_name == "isAlpha":
            return f"isalpha((unsigned char){args[0]})"
        elif method_name == "isAlnum":
            return f"isalnum((unsigned char){args[0]})"
        elif method_name == "isSpace":
            return f"isspace((unsigned char){args[0]})"
        elif method_name == "toInt":
            return f"atoi({args[0]})"
        elif method_name == "toFloat":
            return f"((float)atof({args[0]}))"
        elif method_name == "count":
            return f"__btrc_count({args[0]}, {args[1]})"
        elif method_name == "find":
            return f"__btrc_find({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "rfind":
            return f"__btrc_lastIndexOf({args[0]}, {args[1]})"
        elif method_name == "capitalize":
            return f"__btrc_capitalize({args[0]})"
        elif method_name == "title":
            return f"__btrc_title({args[0]})"
        elif method_name == "swapCase":
            return f"__btrc_swapCase({args[0]})"
        elif method_name == "padLeft":
            return f"__btrc_padLeft({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "padRight":
            return f"__btrc_padRight({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "center":
            return f"__btrc_center({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "lstrip":
            return f"__btrc_lstrip({args[0]})"
        elif method_name == "rstrip":
            return f"__btrc_rstrip({args[0]})"
        elif method_name == "fromInt":
            return f"__btrc_fromInt({args[0]})"
        elif method_name == "fromFloat":
            return f"__btrc_fromFloat({args[0]})"
        elif method_name == "isDigitStr":
            return f"__btrc_isDigitStr({args[0]})"
        elif method_name == "isAlphaStr":
            return f"__btrc_isAlphaStr({args[0]})"
        elif method_name == "isBlank":
            return f"__btrc_isBlank({args[0]})"
        elif method_name == "isUpper":
            return f"__btrc_isUpper({args[0]})"
        elif method_name == "isLower":
            return f"__btrc_isLower({args[0]})"
        elif method_name == "isAlnumStr":
            return f"__btrc_isAlnumStr({args[0]})"
        elif method_name == "indexOf":
            return f"__btrc_indexOf({args[0]}, {args[1]})"
        elif method_name == "lastIndexOf":
            return f"__btrc_lastIndexOf({args[0]}, {args[1]})"
        elif method_name == "contains":
            return f"__btrc_strContains({args[0]}, {args[1]})"
        elif method_name == "startsWith":
            return f"__btrc_startsWith({args[0]}, {args[1]})"
        elif method_name == "endsWith":
            return f"__btrc_endsWith({args[0]}, {args[1]})"
        elif method_name == "substring":
            return f"__btrc_substring({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "trim":
            return f"__btrc_trim({args[0]})"
        elif method_name == "toUpper":
            return f"__btrc_toUpper({args[0]})"
        elif method_name == "toLower":
            return f"__btrc_toLower({args[0]})"
        elif method_name == "reverse":
            return f"__btrc_reverse({args[0]})"
        elif method_name == "isEmpty":
            return f"__btrc_isEmpty({args[0]})"
        elif method_name == "repeat":
            return f"__btrc_repeat({args[0]}, {args[1]})"
        elif method_name == "replace":
            return f"__btrc_replace({args[0]}, {args[1]}, {args[2]})"
        elif method_name == "charAt":
            return f"{args[0]}[(int){args[1]}]"
        else:
            return f"/* unknown Strings method: {method_name} */"

    def _math_static_to_c(self, method_name: str, args_exprs: list) -> str:
        """Translate Math.method(...) static calls to C."""
        args = [self._expr_to_c(a) for a in args_exprs]
        # Constants
        if method_name == "PI":
            return "3.14159265358979323846"
        elif method_name == "E":
            return "2.71828182845904523536"
        elif method_name == "TAU":
            return "6.28318530717958647692"
        elif method_name == "INF":
            return "(1.0 / 0.0)"
        # Basic operations
        elif method_name == "abs":
            return f"(({args[0]}) < 0 ? -({args[0]}) : ({args[0]}))"
        elif method_name == "fabs":
            return f"fabsf({args[0]})"
        elif method_name == "max":
            return f"(({args[0]}) > ({args[1]}) ? ({args[0]}) : ({args[1]}))"
        elif method_name == "min":
            return f"(({args[0]}) < ({args[1]}) ? ({args[0]}) : ({args[1]}))"
        elif method_name == "fmax":
            return f"fmaxf({args[0]}, {args[1]})"
        elif method_name == "fmin":
            return f"fminf({args[0]}, {args[1]})"
        elif method_name == "clamp":
            v, lo, hi = args[0], args[1], args[2]
            return f"(({v}) < ({lo}) ? ({lo}) : (({v}) > ({hi}) ? ({hi}) : ({v})))"
        elif method_name == "fclamp":
            v, lo, hi = args[0], args[1], args[2]
            return f"(({v}) < ({lo}) ? ({lo}) : (({v}) > ({hi}) ? ({hi}) : ({v})))"
        # Power and roots
        elif method_name == "power":
            return f"powf({args[0]}, (float)({args[1]}))"
        elif method_name == "sqrt":
            return f"sqrtf({args[0]})"
        # Combinatorics (helper functions)
        elif method_name == "factorial":
            return f"__btrc_math_factorial({args[0]})"
        elif method_name == "gcd":
            return f"__btrc_math_gcd({args[0]}, {args[1]})"
        elif method_name == "lcm":
            return f"__btrc_math_lcm({args[0]}, {args[1]})"
        elif method_name == "fibonacci":
            return f"__btrc_math_fibonacci({args[0]})"
        # Checks (helper functions)
        elif method_name == "isPrime":
            return f"__btrc_math_isPrime({args[0]})"
        elif method_name == "isEven":
            return f"(({args[0]}) % 2 == 0)"
        elif method_name == "isOdd":
            return f"(({args[0]}) % 2 != 0)"
        # List operations (helper functions)
        elif method_name == "sum":
            return f"__btrc_math_sum_int({args[0]}.data, {args[0]}.len)"
        elif method_name == "fsum":
            return f"__btrc_math_fsum({args[0]}.data, {args[0]}.len)"
        # Trigonometry
        elif method_name == "sin":
            return f"sinf({args[0]})"
        elif method_name == "cos":
            return f"cosf({args[0]})"
        elif method_name == "tan":
            return f"tanf({args[0]})"
        elif method_name == "asin":
            return f"asinf({args[0]})"
        elif method_name == "acos":
            return f"acosf({args[0]})"
        elif method_name == "atan":
            return f"atanf({args[0]})"
        elif method_name == "atan2":
            return f"atan2f({args[0]}, {args[1]})"
        # Rounding
        elif method_name == "ceil":
            return f"ceilf({args[0]})"
        elif method_name == "floor":
            return f"floorf({args[0]})"
        elif method_name == "round":
            return f"((int)roundf({args[0]}))"
        elif method_name == "truncate":
            return f"((int)truncf({args[0]}))"
        # Logarithms and exponentials
        elif method_name == "log":
            return f"logf({args[0]})"
        elif method_name == "log10":
            return f"log10f({args[0]})"
        elif method_name == "log2":
            return f"log2f({args[0]})"
        elif method_name == "exp":
            return f"expf({args[0]})"
        # Conversions
        elif method_name == "toRadians":
            return f"(({args[0]}) * 3.14159265358979323846f / 180.0f)"
        elif method_name == "toDegrees":
            return f"(({args[0]}) * 180.0f / 3.14159265358979323846f)"
        # Utility
        elif method_name == "sign":
            return f"(({args[0]}) > 0 ? 1 : (({args[0]}) < 0 ? -1 : 0))"
        elif method_name == "fsign":
            return f"(({args[0]}) > 0.0f ? 1.0f : (({args[0]}) < 0.0f ? -1.0f : 0.0f))"
        else:
            return f"/* unknown Math method: {method_name} */"

    def _get_collection_type_for_obj(self, obj) -> TypeExpr | None:
        """Check if obj is a collection type (List/Array/Map/Set)."""
        type_info = self.node_types.get(id(obj))
        if type_info and type_info.base in ("List", "Array", "Map", "Set"):
            return type_info
        return None

    def _get_element_type_c(self, iterable_expr) -> str:
        """Get the C type of the element for a collection iterable expression."""
        type_info = self.node_types.get(id(iterable_expr))
        if type_info and type_info.generic_args:
            return self._type_to_c(type_info.generic_args[0])
        # Fallback: use int if type info is unavailable
        return "int"

    def _field_access_to_c(self, expr: FieldAccessExpr) -> str:
        # Check if this is a property getter
        prop = self._is_property_access(expr)
        if prop and prop.has_getter:
            obj_c = self._expr_to_c(expr.obj)
            class_name = self._get_class_name_for_obj(expr.obj)
            if class_name:
                return f"{class_name}_get_{expr.field}({obj_c})"

        obj = self._expr_to_c(expr.obj)
        if isinstance(expr.obj, SelfExpr):
            return f"self->{expr.field}"
        elif expr.optional:
            # Optional chaining: obj?.field → (obj != NULL ? obj->field : 0/NULL)
            default = self._default_for_field(expr)
            return f"({obj} != NULL ? {obj}->{expr.field} : {default})"
        elif expr.arrow:
            return f"{obj}->{expr.field}"
        else:
            # Check if the object is a pointer type — use -> instead of .
            obj_type = self.node_types.get(id(expr.obj))
            if obj_type and obj_type.pointer_depth > 0:
                return f"{obj}->{expr.field}"
            return f"{obj}.{expr.field}"

    def _default_for_field(self, expr: FieldAccessExpr) -> str:
        """Get default value for optional chaining based on inferred type."""
        type_info = self.node_types.get(id(expr))
        if type_info:
            if type_info.pointer_depth > 0 or type_info.base == "string":
                return "NULL"
            if type_info.base in ("float", "double"):
                return "0.0"
            if type_info.base == "bool":
                return "false"
        return "0"

    def _new_to_c(self, expr: NewExpr) -> str:
        c_type = self._type_to_c(expr.type)
        if expr.type.base in self.class_table:
            args = ", ".join(self._expr_to_c(a) for a in expr.args)
            # Constructor already returns a heap-allocated pointer
            return f"{c_type}_new({args})"
        else:
            return f"({c_type}*)malloc(sizeof({c_type}))"

    def _emit_initializer(self, type_expr: TypeExpr, init) -> str:
        """Generate initializer for simple assignments."""
        if isinstance(init, CallExpr) and self._is_constructor_call(init):
            class_name = init.callee.name
            args = self._fill_default_args(init.args, class_name=class_name)
            return f"{class_name}_new({', '.join(args)})"
        return self._expr_to_c(init)

    # ---- F-string + print ----

    def _emit_fstring_as_value(self, expr: FStringLiteral) -> str:
        """Emit snprintf code to build an f-string into a heap-allocated buffer.
        Returns the variable name holding the result (char*)."""
        fmt_parts = []
        args = []
        for kind, val in expr.parts:
            if kind == "text":
                fmt_parts.append(val.replace("%", "%%"))
            elif kind == "expr":
                spec = self._infer_format_spec(val)
                fmt_parts.append(spec)
                c_arg = self._expr_to_c(val)
                args.append(self._format_printf_arg(val, c_arg))
        fmt = ''.join(fmt_parts)
        self._fstr_counter += 1
        tmp = f"__btrc_fstr_{self._fstr_counter}"
        args_str = f', {", ".join(args)}' if args else ""
        self._emit(f'int {tmp}_len = snprintf(NULL, 0, "{fmt}"{args_str});')
        self._emit(f'char* {tmp} = (char*)malloc({tmp}_len + 1);')
        self._emit(f'snprintf({tmp}, {tmp}_len + 1, "{fmt}"{args_str});')
        return tmp

    def _fstring_to_c(self, expr: FStringLiteral) -> str:
        """Convert f-string to printf-style format string and args.
        Returns a tuple-like string: the format string followed by args, for use in printf."""
        fmt_parts = []
        args = []
        for kind, val in expr.parts:
            if kind == "text":
                # Escape % for printf
                fmt_parts.append(val.replace("%", "%%"))
            elif kind == "expr":
                spec = self._infer_format_spec(val)
                fmt_parts.append(spec)
                c_arg = self._expr_to_c(val)
                args.append(self._format_printf_arg(val, c_arg))
        fmt = ''.join(fmt_parts)
        if args:
            return f'"{fmt}", {", ".join(args)}'
        else:
            return f'"{fmt}"'

    def _format_printf_arg(self, expr, c_arg: str) -> str:
        """Wrap a printf argument if needed (e.g., bool → ternary for true/false)."""
        type_info = self.node_types.get(id(expr))
        if type_info and type_info.base == "bool" and type_info.pointer_depth == 0:
            return f'(({c_arg}) ? "true" : "false")'
        if isinstance(expr, BoolLiteral):
            return f'(({c_arg}) ? "true" : "false")'
        return c_arg

    def _infer_format_spec(self, expr) -> str:
        """Infer printf format specifier for an expression."""
        type_info = self.node_types.get(id(expr))
        if type_info:
            base = type_info.base
            if type_info.pointer_depth > 0 and base != "string" and base != "char":
                return "%p"
            if base == "bool" and type_info.pointer_depth == 0:
                return "%s"
            if base in ("int", "short"):
                return "%d"
            if base in ("long",):
                return "%ld"
            if base in ("long long", "unsigned long long"):
                return "%lld"
            if base in ("unsigned", "unsigned int"):
                return "%u"
            if base in ("unsigned long",):
                return "%lu"
            if base in ("float", "double"):
                return "%f"
            if base in ("string", "char*") or (base == "char" and type_info.pointer_depth > 0):
                return "%s"
            if base == "char" and type_info.pointer_depth == 0:
                return "%c"
        # Fallback: try to guess from AST node type
        if isinstance(expr, IntLiteral):
            return "%d"
        if isinstance(expr, FloatLiteral):
            return "%f"
        if isinstance(expr, StringLiteral):
            return "%s"
        if isinstance(expr, CharLiteral):
            return "%c"
        if isinstance(expr, BoolLiteral):
            return "%s"
        # Default to int
        return "%d"

    def _print_to_c(self, expr: CallExpr) -> str:
        """Translate print() calls to printf()."""
        args = expr.args
        if not args:
            return 'printf("\\n")'

        # Single f-string argument
        if len(args) == 1 and isinstance(args[0], FStringLiteral):
            fstr = self._fstring_to_c(args[0])
            # fstr is already "fmt", arg1, arg2... — append \n to format
            # We need to insert \n before the closing quote
            parts = fstr.split('"', 2)
            # parts[0] is empty, parts[1] is the format content, parts[2] is rest
            fmt_content = parts[1]
            rest = parts[2] if len(parts) > 2 else ""
            return f'printf("{fmt_content}\\n"{rest})'

        # Single string literal
        if len(args) == 1 and isinstance(args[0], StringLiteral):
            # Strip quotes, add \n
            raw = args[0].value  # includes surrounding quotes
            inner = raw[1:-1]  # strip quotes
            return f'printf("{inner}\\n")'

        # Single or multiple arguments — auto-format each
        fmt_parts = []
        c_args = []
        for i, arg in enumerate(args):
            if isinstance(arg, FStringLiteral):
                fstr_c = self._fstring_to_c(arg)
                # Parse out the format and args from the fstring result
                first_quote_end = fstr_c.index('"', 1)
                fmt_content = fstr_c[1:first_quote_end]
                rest = fstr_c[first_quote_end + 1:]
                fmt_parts.append(fmt_content)
                if rest.startswith(", "):
                    c_args.extend(a.strip() for a in self._split_c_args(rest[2:]))
            elif isinstance(arg, StringLiteral):
                fmt_parts.append(arg.value[1:-1])  # strip quotes
            else:
                spec = self._infer_format_spec(arg)
                fmt_parts.append(spec)
                c_arg = self._expr_to_c(arg)
                c_args.append(self._format_printf_arg(arg, c_arg))

        sep = " "
        fmt = sep.join(fmt_parts) + "\\n"
        if c_args:
            return f'printf("{fmt}", {", ".join(c_args)})'
        else:
            return f'printf("{fmt}")'

    def _split_c_args(self, s: str) -> list[str]:
        """Split a comma-separated C argument string, respecting parentheses."""
        args = []
        depth = 0
        current = []
        for ch in s:
            if ch == ',' and depth == 0:
                args.append(''.join(current).strip())
                current = []
            else:
                if ch in ('(', '['):
                    depth += 1
                elif ch in (')', ']'):
                    depth -= 1
                current.append(ch)
        if current:
            args.append(''.join(current).strip())
        return args

    # ---- Tuple support ----

    def _tuple_to_c(self, expr: TupleLiteral) -> str:
        """Convert tuple literal to C compound literal."""
        # Infer element types from the tuple elements
        type_args = []
        for el in expr.elements:
            t = self.node_types.get(id(el))
            if t:
                type_args.append(t)
            else:
                type_args.append(TypeExpr(base="int"))  # fallback
        mangled = "_".join(self._mangle_type(a) for a in type_args)
        struct_name = f"btrc_Tuple_{mangled}"
        elems = ", ".join(self._expr_to_c(e) for e in expr.elements)
        return f"({struct_name}){{{elems}}}"

    # ---- Operator overloading ----

    _OP_METHOD_MAP = {
        "+": "__add__", "-": "__sub__", "*": "__mul__", "/": "__div__",
        "%": "__mod__", "==": "__eq__", "!=": "__ne__",
        "<": "__lt__", ">": "__gt__", "<=": "__le__", ">=": "__ge__",
    }

    def _op_to_method_name(self, op: str) -> str | None:
        return self._OP_METHOD_MAP.get(op)

    # ---- Type → C string ----

    def _type_to_c(self, type_expr: TypeExpr) -> str:
        if type_expr is None:
            return "void"

        base = type_expr.base

        # btrc type mappings
        if base == "string":
            base = "char*"
        elif base == "bool":
            base = "bool"  # stdbool.h
        elif base == "List" and type_expr.generic_args:
            mangled = self._mangle_type(type_expr.generic_args[0])
            base = f"btrc_List_{mangled}"
        elif base == "Array" and type_expr.generic_args:
            mangled = self._mangle_type(type_expr.generic_args[0])
            base = f"btrc_Array_{mangled}"
        elif base == "Tuple" and type_expr.generic_args:
            mangled = "_".join(self._mangle_type(a) for a in type_expr.generic_args)
            base = f"btrc_Tuple_{mangled}"
        elif base == "Map" and len(type_expr.generic_args) == 2:
            k_mangled = self._mangle_type(type_expr.generic_args[0])
            v_mangled = self._mangle_type(type_expr.generic_args[1])
            base = f"btrc_Map_{k_mangled}_{v_mangled}"
        elif base == "Set" and type_expr.generic_args:
            mangled = self._mangle_type(type_expr.generic_args[0])
            base = f"btrc_Set_{mangled}"
        elif base in self.class_table and type_expr.generic_args:
            mangled = "_".join(self._mangle_type(a) for a in type_expr.generic_args)
            base = f"btrc_{base}_{mangled}"

        result = base
        if base == "char*" and type_expr.pointer_depth > 0:
            # string* → char**
            result += "*" * type_expr.pointer_depth
        elif base != "char*":
            result += "*" * type_expr.pointer_depth

        return result

    def _mangle_type(self, type_expr: TypeExpr) -> str:
        """Create a C-safe name from a type expression."""
        base = type_expr.base
        if base == "string":
            base = "string"
        if type_expr.generic_args:
            args = "_".join(self._mangle_type(a) for a in type_expr.generic_args)
            return f"{base}_{args}"
        return base + ("_ptr" * type_expr.pointer_depth)

    def _substitute_type(self, type_expr: TypeExpr, subs: dict[str, TypeExpr]) -> TypeExpr:
        """Substitute generic type parameters with concrete types."""
        if type_expr.base in subs:
            concrete = subs[type_expr.base]
            return TypeExpr(
                base=concrete.base,
                generic_args=concrete.generic_args,
                pointer_depth=type_expr.pointer_depth + concrete.pointer_depth,
            )
        new_args = [self._substitute_type(a, subs) for a in type_expr.generic_args]
        return TypeExpr(
            base=type_expr.base,
            generic_args=new_args,
            pointer_depth=type_expr.pointer_depth,
        )
