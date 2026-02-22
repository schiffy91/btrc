"""C code generator for the btrc language.

Transforms an analyzed AST into C source code.
"""

from __future__ import annotations
from .ast_nodes import *
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
        self.in_constructor: bool = False
        self.debug = debug
        self.source_file = source_file

    def generate(self) -> str:
        # Collect user includes and determine needed auto-includes
        self._collect_user_includes()
        self._emit_header()
        self._emit_forward_declarations()       # typedef struct Foo Foo;
        self._emit_generic_struct_typedefs()     # btrc_List_Foo struct (pointers only)
        self._emit_struct_definitions()          # full struct bodies
        self._emit_destroy_forward_declarations()  # void Foo_destroy(Foo* self);
        self._emit_generic_function_bodies()     # List/Map function implementations
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
        if self._needs_string_helpers:
            self._emit_string_helpers()
        if self._needs_try_catch:
            self._emit_try_catch_runtime()

    def _check_needs_string_helpers(self) -> bool:
        """Check if the AST uses any string methods that require helper functions."""
        return self._walk_for_string_methods(self.analyzed.program)

    def _walk_for_string_methods(self, node) -> bool:
        if node is None:
            return False
        if isinstance(node, CallExpr) and isinstance(node.callee, FieldAccessExpr):
            method = node.callee.field
            if method in ("substring", "trim", "toUpper", "toLower", "indexOf", "split", "charLen"):
                obj_type = self.node_types.get(id(node.callee.obj))
                if obj_type and (obj_type.base == "string" or
                    (obj_type.base == "char" and obj_type.pointer_depth >= 1)):
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
        # indexOf(s, sub)
        self._emit("static inline int __btrc_indexOf(const char* s, const char* sub) {")
        self._emit("    char* p = strstr(s, sub);")
        self._emit("    return p ? (int)(p - s) : -1;")
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

    def _emit_generic_function_bodies(self):
        """Emit function implementations for generic types.
        Called after all struct definitions are complete."""
        emitted_types: set[str] = set()
        for base_name, instances in self.generic_instances.items():
            if base_name == "List":
                for args in instances:
                    mangled = self._mangle_type(args[0])
                    key = f"List_{mangled}"
                    if key not in emitted_types:
                        emitted_types.add(key)
                        c_type = self._type_to_c(args[0])
                        self._emit_list_functions(c_type, mangled)
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
                            self._emit_map_functions(k_type, v_type, k_mangled, v_mangled)
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
        self._emit(f"typedef struct {{")
        for i, arg in enumerate(args):
            c_type = self._type_to_c(arg)
            self._emit(f"    {c_type} _{i};")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_list_struct_typedef(self, c_type: str, mangled: str):
        name = f"btrc_List_{mangled}"
        self._emit(f"typedef struct {{")
        self._emit(f"    {c_type}* data;")
        self._emit(f"    int len;")
        self._emit(f"    int cap;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_list_functions(self, c_type: str, mangled: str):
        name = f"btrc_List_{mangled}"
        self._emit(f"static inline {name} {name}_new() {{")
        self._emit(f"    return ({name}){{NULL, 0, 0}};")
        self._emit(f"}}")
        self._emit()
        self._emit(f"static inline void {name}_push({name}* l, {c_type} val) {{")
        self._emit(f"    if (l->len >= l->cap) {{")
        self._emit(f"        l->cap = l->cap ? l->cap * 2 : 4;")
        self._emit(f"        l->data = ({c_type}*)realloc(l->data, sizeof({c_type}) * l->cap);")
        self._emit(f"    }}")
        self._emit(f"    l->data[l->len++] = val;")
        self._emit(f"}}")
        self._emit()
        self._emit(f"static inline {c_type} {name}_get({name}* l, int i) {{")
        self._emit(f"    return l->data[i];")
        self._emit(f"}}")
        self._emit()
        self._emit(f"static inline void {name}_set({name}* l, int i, {c_type} val) {{")
        self._emit(f"    l->data[i] = val;")
        self._emit(f"}}")
        self._emit()
        self._emit(f"static inline void {name}_free({name}* l) {{")
        self._emit(f"    free(l->data);")
        self._emit(f"    l->data = NULL; l->len = 0; l->cap = 0;")
        self._emit(f"}}")
        self._emit()
        # Only emit contains/sort for primitive types (structs can't be compared with ==/</>)
        is_primitive = c_type not in self.class_table
        if is_primitive:
            # contains
            self._emit(f"static inline bool {name}_contains({name}* l, {c_type} val) {{")
            self._emit(f"    for (int i = 0; i < l->len; i++) {{")
            self._emit(f"        if (l->data[i] == val) return true;")
            self._emit(f"    }}")
            self._emit(f"    return false;")
            self._emit(f"}}")
            self._emit()
        # remove (by index)
        self._emit(f"static inline void {name}_remove({name}* l, int idx) {{")
        self._emit(f"    for (int i = idx; i < l->len - 1; i++) {{")
        self._emit(f"        l->data[i] = l->data[i + 1];")
        self._emit(f"    }}")
        self._emit(f"    l->len--;")
        self._emit(f"}}")
        self._emit()
        # reverse
        self._emit(f"static inline void {name}_reverse({name}* l) {{")
        self._emit(f"    for (int i = 0; i < l->len / 2; i++) {{")
        self._emit(f"        {c_type} tmp = l->data[i];")
        self._emit(f"        l->data[i] = l->data[l->len - 1 - i];")
        self._emit(f"        l->data[l->len - 1 - i] = tmp;")
        self._emit(f"    }}")
        self._emit(f"}}")
        self._emit()
        if is_primitive:
            # sort (ascending, using qsort)
            self._emit(f"static int __{name}_cmp(const void* a, const void* b) {{")
            self._emit(f"    {c_type} va = *({c_type}*)a;")
            self._emit(f"    {c_type} vb = *({c_type}*)b;")
            self._emit(f"    return (va > vb) - (va < vb);")
            self._emit(f"}}")
            self._emit(f"static inline void {name}_sort({name}* l) {{")
            self._emit(f"    qsort(l->data, l->len, sizeof({c_type}), __{name}_cmp);")
            self._emit(f"}}")
            self._emit()
        # clear
        self._emit(f"static inline void {name}_clear({name}* l) {{")
        self._emit(f"    l->len = 0;")
        self._emit(f"}}")
        self._emit()

    def _emit_array_struct_typedef(self, c_type: str, mangled: str):
        name = f"btrc_Array_{mangled}"
        self._emit(f"typedef struct {{")
        self._emit(f"    {c_type}* data;")
        self._emit(f"    int len;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_map_struct_typedef(self, k_type: str, v_type: str, k_mangled: str, v_mangled: str):
        name = f"btrc_Map_{k_mangled}_{v_mangled}"
        entry = f"{name}_entry"
        self._emit(f"typedef struct {{ {k_type} key; {v_type} value; bool occupied; }} {entry};")
        self._emit(f"typedef struct {{")
        self._emit(f"    {entry}* buckets;")
        self._emit(f"    int cap;")
        self._emit(f"    int len;")
        self._emit(f"}} {name};")
        self._emit()

    def _emit_map_functions(self, k_type: str, v_type: str, k_mangled: str, v_mangled: str):
        name = f"btrc_Map_{k_mangled}_{v_mangled}"
        entry = f"{name}_entry"

        # Hash function selection
        if k_type == "char*":
            hash_expr = "__btrc_hash_str(key)"
            eq_expr = "strcmp(m->buckets[idx].key, key) == 0"
            self._emit(f"static inline unsigned int __btrc_hash_str(const char* s) {{")
            self._emit(f"    unsigned int h = 5381;")
            self._emit(f"    while (*s) h = h * 33 + (unsigned char)*s++;")
            self._emit(f"    return h;")
            self._emit(f"}}")
            self._emit()
        else:
            hash_expr = "(unsigned int)key"
            eq_expr = f"m->buckets[idx].key == key"

        # new
        self._emit(f"static inline {name} {name}_new() {{")
        self._emit(f"    {name} m;")
        self._emit(f"    m.cap = 16;")
        self._emit(f"    m.len = 0;")
        self._emit(f"    m.buckets = ({entry}*)calloc(m.cap, sizeof({entry}));")
        self._emit(f"    return m;")
        self._emit(f"}}")
        self._emit()

        # Forward declare put (needed by resize)
        self._emit(f"static inline void {name}_put({name}* m, {k_type} key, {v_type} value);")
        self._emit()

        # resize — doubles capacity and rehashes all entries
        self._emit(f"static inline void {name}_resize({name}* m) {{")
        self._emit(f"    int old_cap = m->cap;")
        self._emit(f"    {entry}* old_buckets = m->buckets;")
        self._emit(f"    m->cap *= 2;")
        self._emit(f"    m->len = 0;")
        self._emit(f"    m->buckets = ({entry}*)calloc(m->cap, sizeof({entry}));")
        self._emit(f"    for (int i = 0; i < old_cap; i++) {{")
        self._emit(f"        if (old_buckets[i].occupied) {{")
        self._emit(f"            {name}_put(m, old_buckets[i].key, old_buckets[i].value);")
        self._emit(f"        }}")
        self._emit(f"    }}")
        self._emit(f"    free(old_buckets);")
        self._emit(f"}}")
        self._emit()

        # put — with auto-resize at 75% load factor
        self._emit(f"static inline void {name}_put({name}* m, {k_type} key, {v_type} value) {{")
        self._emit(f"    if (m->len * 4 >= m->cap * 3) {{ {name}_resize(m); }}")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit(f"    while (m->buckets[idx].occupied) {{")
        self._emit(f"        if ({eq_expr}) {{ m->buckets[idx].value = value; return; }}")
        self._emit(f"        idx = (idx + 1) % m->cap;")
        self._emit(f"    }}")
        self._emit(f"    m->buckets[idx].key = key;")
        self._emit(f"    m->buckets[idx].value = value;")
        self._emit(f"    m->buckets[idx].occupied = true;")
        self._emit(f"    m->len++;")
        self._emit(f"}}")
        self._emit()

        # get
        self._emit(f"static inline {v_type} {name}_get({name}* m, {k_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit(f"    while (m->buckets[idx].occupied) {{")
        self._emit(f"        if ({eq_expr}) return m->buckets[idx].value;")
        self._emit(f"        idx = (idx + 1) % m->cap;")
        self._emit(f"    }}")
        self._emit(f"    return ({v_type}){{0}};")
        self._emit(f"}}")
        self._emit()

        # has
        self._emit(f"static inline bool {name}_has({name}* m, {k_type} key) {{")
        self._emit(f"    unsigned int idx = {hash_expr} % m->cap;")
        self._emit(f"    while (m->buckets[idx].occupied) {{")
        self._emit(f"        if ({eq_expr}) return true;")
        self._emit(f"        idx = (idx + 1) % m->cap;")
        self._emit(f"    }}")
        self._emit(f"    return false;")
        self._emit(f"}}")
        self._emit()

        # free
        self._emit(f"static inline void {name}_free({name}* m) {{")
        self._emit(f"    free(m->buckets);")
        self._emit(f"    m->buckets = NULL; m->cap = 0; m->len = 0;")
        self._emit(f"}}")
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
        self._emit(f"typedef struct {{")
        self.indent_level += 1
        for fname, field in cls.fields.items():
            ftype = self._substitute_type(field.type, subs)
            self._emit(f"{self._type_to_c(ftype)} {fname};")
        self.indent_level -= 1
        self._emit(f"}} {mono_name};")
        self._emit()

    # ---- Forward declarations ----

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
        cls = self.class_table[decl.name]
        child_field_names = {m.name for m in decl.members if isinstance(m, FieldDecl)}
        self._emit_line_directive(decl.line)
        self._emit(f"struct {decl.name} {{")
        self.indent_level += 1
        if decl.parent and decl.parent in self.class_table:
            parent_cls = self.class_table[decl.parent]
            for fname, fld in parent_cls.fields.items():
                if fname not in child_field_names:
                    self._emit(f"{self._type_to_c(fld.type)} {fname};")
        for member in decl.members:
            if isinstance(member, FieldDecl):
                self._emit(f"{self._type_to_c(member.type)} {member.name};")
        self.indent_level -= 1
        self._emit(f"}};")
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

        # 3. Free the object itself
        self._emit("free(self);")
        self.indent_level -= 1
        self._emit("}")
        self._emit()

    # ---- Declarations ----

    def _emit_declarations(self):
        for decl in self.analyzed.program.declarations:
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

        # Generate default constructor if class has field defaults but no explicit constructor
        has_explicit_constructor = cls.constructor is not None
        has_field_defaults = any(
            isinstance(m, FieldDecl) and m.initializer is not None
            for m in decl.members
        )
        if has_field_defaults and not has_explicit_constructor:
            self._emit_default_constructor(decl.name, decl.members, cls)

        # Heap allocation helper for 'new' keyword
        self._emit(f"static inline {decl.name}* __btrc_heap_{decl.name}({decl.name} val) {{")
        self.indent_level += 1
        self._emit(f"{decl.name}* ptr = ({decl.name}*)malloc(sizeof({decl.name}));")
        self._emit(f"*ptr = val;")
        self._emit(f"return ptr;")
        self.indent_level -= 1
        self._emit(f"}}")
        self._emit()

        # Destroy function for 'delete' keyword (recursive cleanup)
        self._emit_destroy_function(decl.name, cls)

        self.current_class = None

    def _emit_method_forward_decl(self, class_name: str, method: MethodDecl, cls: ClassInfo):
        """Emit a forward declaration for a method."""
        is_constructor = method.name == class_name
        is_static = method.access == "class"
        if is_constructor:
            ret_type = class_name
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
            # Constructor: returns the struct by value
            ret_type = class_name
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
            self._emit(f"{class_name} self;")
            # Apply field defaults before user constructor body
            for fname, fld in cls.fields.items():
                if fld.initializer:
                    init_c = self._expr_to_c(fld.initializer)
                    self._emit(f"self.{fname} = {init_c};")
            # In constructor, self is a value type (not pointer), so use . not ->
            self.in_constructor = True
            self._emit_block_contents(method.body)
            self.in_constructor = False
            self._emit(f"return self;")
            self.indent_level -= 1
            self._emit(f"}}")
        else:
            self._emit(f"{ret_type} {func_name}({params_str}) {{")
            self.indent_level += 1
            self._emit_block_contents(method.body)
            self.indent_level -= 1
            self._emit(f"}}")
        self._emit()

    def _emit_default_constructor(self, class_name: str, members: list, cls: ClassInfo):
        """Generate a default constructor from field initializers."""
        self._emit(f"{class_name} {class_name}_new(void) {{")
        self.indent_level += 1
        self._emit(f"{class_name} self;")
        self._emit(f"memset(&self, 0, sizeof({class_name}));")
        for member in members:
            if isinstance(member, FieldDecl) and member.initializer:
                init_c = self._expr_to_c(member.initializer)
                self._emit(f"self.{member.name} = {init_c};")
        self._emit(f"return self;")
        self.indent_level -= 1
        self._emit(f"}}")
        self._emit()

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
        ret_type = self._type_to_c(decl.return_type)
        params = [self._param_to_c(p) for p in decl.params]
        params_str = ", ".join(params) if params else "void"

        self._emit_line_directive(decl.line)
        self._emit(f"{ret_type} {decl.name}({params_str}) {{")
        self.indent_level += 1
        self._emit_block_contents(decl.body)
        self.indent_level -= 1
        self._emit(f"}}")
        self._emit()

    # ---- GPU function ----

    def _emit_gpu_function(self, decl: FunctionDecl):
        # Emit the kernel body as a GLSL compute shader string
        glsl = self._generate_glsl(decl)
        shader_name = f"__btrc_gpu_shader_{decl.name}"

        self._emit(f'static const char* {shader_name} =')
        for line in glsl.split("\n"):
            self._emit(f'    "{line}\\n"')
        self._emit(f";")
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
        self._emit(f"/* Buffer setup, shader compilation, and dispatch */")
        self.indent_level -= 1
        self._emit(f"}}")
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
        self._emit(f"typedef enum {{")
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
            elif isinstance(stmt.initializer, CallExpr) and self._is_constructor_call(stmt.initializer):
                self._emit_constructor_init(c_type, stmt.name, stmt.initializer)
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

    def _emit_if(self, stmt: IfStmt):
        self._emit(f"if ({self._expr_to_c(stmt.condition)}) {{")
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
        idx = f"__btrc_i_{var}"
        self._emit(f"for (int {idx} = 0; {idx} < {iterable}.len; {idx}++) {{")
        self.indent_level += 1
        # We'd need the element type. For now, use auto-like approach with typeof (GNU extension)
        # or we can look up the type from the analyzer
        self._emit(f"__typeof__({iterable}.data[0]) {var} = {iterable}.data[{idx}];")
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
            self._emit(f"for (int {var} = {start}; {var} < {end}; {var} += {step}) {{")
        else:
            self._emit(f"/* invalid range() call */")
            return
        self.indent_level += 1
        self._emit_block_contents(stmt.body)
        self.indent_level -= 1
        self._emit("}")

    def _emit_parallel_for(self, stmt: ParallelForStmt):
        iterable = self._expr_to_c(stmt.iterable)
        var = stmt.var_name
        idx = f"__btrc_i_{var}"
        self._emit("#pragma omp parallel for")
        self._emit(f"for (int {idx} = 0; {idx} < {iterable}.len; {idx}++) {{")
        self.indent_level += 1
        self._emit(f"__typeof__({iterable}.data[0]) {var} = {iterable}.data[{idx}];")
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
            self.indent_level -= 1
        self.indent_level -= 1
        self._emit("}")

    # ---- Expressions → C code ----

    def _expr_to_c(self, expr) -> str:
        if expr is None:
            return ""

        if isinstance(expr, IntLiteral):
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
                        if left_type.pointer_depth > 0:
                            return f"{cn}_{op_method}({left_c}, &{right_c})"
                        else:
                            return f"{cn}_{op_method}(&{left_c}, &{right_c})"
            # Null coalescing: a ?? b → (a != NULL ? a : b)
            if expr.op == "??":
                left = self._expr_to_c(expr.left)
                right = self._expr_to_c(expr.right)
                return f"({left} != NULL ? {left} : {right})"
            left = self._expr_to_c(expr.left)
            right = self._expr_to_c(expr.right)
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
            # Check if obj is a collection type — translate to .data[] access
            coll_type = self._get_collection_type_for_obj(expr.obj)
            if coll_type and coll_type.base in ("List", "Array"):
                if coll_type.pointer_depth > 0:
                    return f"{obj}->data[{idx}]"
                return f"{obj}.data[{idx}]"
            return f"{obj}[{idx}]"

        if isinstance(expr, FieldAccessExpr):
            return self._field_access_to_c(expr)

        if isinstance(expr, AssignExpr):
            target = self._expr_to_c(expr.target)
            # Handle Map/List/empty-brace literal assignments (e.g. self.counts = {}, self.items = [])
            is_collection_lit = isinstance(expr.value, (MapLiteral, ListLiteral))
            is_empty_brace = isinstance(expr.value, BraceInitializer) and len(expr.value.elements) == 0
            if is_collection_lit or is_empty_brace:
                target_type = self.node_types.get(id(expr.target))
                if target_type and target_type.base in ("Map", "List"):
                    c_type = self._type_to_c(target_type)
                    return f"({target} = {c_type}_new())"
            value = self._expr_to_c(expr.value)
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

        return f"/* unknown expr */"

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

        # Static method call: ClassName.method(args)
        if isinstance(obj, Identifier) and obj.name in self.class_table:
            class_name = obj.name
            args = ", ".join(self._expr_to_c(a) for a in args_exprs)
            return f"{class_name}_{method_name}({args})"

        obj_c = self._expr_to_c(obj)

        # String method call: s.len() → strlen(s), etc.
        str_type = self._get_string_type_for_obj(obj)
        if str_type:
            return self._string_method_to_c(obj_c, method_name, args_exprs)

        # Collection method call: obj.push(x) → btrc_List_T_push(&obj, x)
        coll_type = self._get_collection_type_for_obj(obj)
        if coll_type:
            return self._collection_method_to_c(coll_type, obj_c, method_name, args_exprs, access.arrow)

        # Instance method call: obj.method(args) → Class_method(&obj, args)
        class_name = self._get_class_name_for_obj(obj)
        if class_name:
            # self is already a pointer in non-constructor methods; don't add &
            already_ptr = access.arrow or (isinstance(obj, SelfExpr) and not self.in_constructor)
            if already_ptr:
                all_args = [obj_c] + self._fill_default_args(
                    args_exprs, class_name=class_name, method_name=method_name)
            else:
                all_args = [f"&{obj_c}"] + self._fill_default_args(
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

    def _collection_method_to_c(self, type_info: TypeExpr, obj_c: str,
                                 method_name: str, args_exprs: list, arrow: bool) -> str:
        """Translate collection method calls: obj.push(x) → btrc_List_T_push(&obj, x)"""
        c_type = self._type_to_c(type_info)
        obj_ref = obj_c if (arrow or type_info.pointer_depth > 0) else f"&{obj_c}"
        args = [obj_ref] + [self._expr_to_c(a) for a in args_exprs]
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
            return f"(strstr({obj_c}, {args[0]}) != NULL)"
        elif method_name == "startsWith":
            return f"(strncmp({obj_c}, {args[0]}, strlen({args[0]})) == 0)"
        elif method_name == "endsWith":
            return f"(strlen({obj_c}) >= strlen({args[0]}) && strcmp({obj_c} + strlen({obj_c}) - strlen({args[0]}), {args[0]}) == 0)"
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
            return f"{obj_c}[{args[0]}]"
        elif method_name == "equals":
            return f"(strcmp({obj_c}, {args[0]}) == 0)"
        else:
            return f"/* unknown string method: {method_name} */"

    def _get_collection_type_for_obj(self, obj) -> TypeExpr | None:
        """Check if obj is a collection type (List/Array/Map)."""
        type_info = self.node_types.get(id(obj))
        if type_info and type_info.base in ("List", "Array", "Map"):
            return type_info
        return None

    def _field_access_to_c(self, expr: FieldAccessExpr) -> str:
        obj = self._expr_to_c(expr.obj)
        if isinstance(expr.obj, SelfExpr):
            # In constructors, self is a value type; in methods, it's a pointer
            if self.in_constructor:
                return f"self.{expr.field}"
            return f"self->{expr.field}"
        elif expr.optional:
            # Optional chaining: obj?.field → (obj != NULL ? obj->field : 0/NULL)
            default = self._default_for_field(expr)
            return f"({obj} != NULL ? {obj}->{expr.field} : {default})"
        elif expr.arrow:
            return f"{obj}->{expr.field}"
        else:
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
            # Allocate + construct using a compound literal copy
            return (f"__btrc_heap_{c_type}({c_type}_new({args}))")
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
                args.append(self._expr_to_c(val))
        fmt = ''.join(fmt_parts)
        if args:
            return f'"{fmt}", {", ".join(args)}'
        else:
            return f'"{fmt}"'

    def _infer_format_spec(self, expr) -> str:
        """Infer printf format specifier for an expression."""
        type_info = self.node_types.get(id(expr))
        if type_info:
            base = type_info.base
            if type_info.pointer_depth > 0 and base != "string" and base != "char":
                return "%p"
            if base in ("int", "short", "bool"):
                return "%d"
            if base in ("long",):
                return "%ld"
            if base in ("unsigned", "unsigned int"):
                return "%u"
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
            return "%d"
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
                c_args.append(self._expr_to_c(arg))

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
