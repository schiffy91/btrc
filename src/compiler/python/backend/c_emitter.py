"""C code emitter for the btrc compiler.

Walks an IR tree and serializes it to C text. This is intentionally simple --
all lowering (class layout, generics, method-to-function, etc.) is done
during IR generation. The emitter just formats.
"""

from __future__ import annotations

from ..ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRBreak,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRContinue,
    IRCxxDelete,
    IRCxxExceptionBoundary,
    IRCxxNew,
    IRDeref,
    IRDoWhile,
    IREnumDef,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRGlobalDecl,
    IRGpuKernel,
    IRIf,
    IRInclude,
    IRIndex,
    IRInitializerList,
    IRLineMarker,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCBlock,
    IRObjectiveCClass,
    IRObjectiveCExceptionBoundary,
    IRObjectiveCMessage,
    IRObjectiveCMethod,
    IRObjectiveCSelector,
    IRReturn,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRStructDef,
    IRStructForward,
    IRSwitch,
    IRTaggedUnionDef,
    IRTernary,
    IRTypedefDef,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from ..ir.verifier import IRVerifier
from . import runtime_state
from .wgsl_emitter import WgslEmitter

_INLINE_EXPRESSION_LIMIT = 1000


class CEmitter:
    """Emits C source text from an IRModule."""

    _CLINE_PLACEHOLDER = "@@BTRC_CLINE@@"

    def __init__(self):
        self._lines: list[str] = []
        self._indent: int = 0
        self._module = None  # set by emit(); archive header/impl paths leave None
        self._dbg_enabled = False  # stamp #line on each content line (in func bodies)
        self._dbg_loc = None  # current (btrc_file, line) or None for .c-mapped
        self._debug_cfile = ""  # this unit's own path for #line resets
        # Several units share one program: functions and globals lose internal
        # linkage, and a secondary unit only declares the globals and kernels.
        self._shared_linkage = False
        self._declarations_only = False

    @staticmethod
    def _prepare_module(module: IRModule) -> None:
        """Validate the complete optimizer-prepared IR input."""

        IRVerifier(module).validate()

    def emit(self, module: IRModule) -> str:
        """Emit the entire IR module as C source text."""
        self._prepare_module(module)
        return self._emit_unit(module, -1, 0, len(module.function_defs))

    def emit_units(self, module: IRModule, target_lines: int) -> list[str]:
        """The module as one primary unit followed by secondaries of about
        `target_lines` lines of function definitions each. Every unit carries
        the prologue, helpers, types and prototypes; the primary defines the
        globals and kernels and the secondaries declare them. Functions are
        split in module order. Objective-C and C++ modules stay one unit."""
        self._prepare_module(module)
        if module.language != "c" or module.objective_c_classes or target_lines <= 0:
            return [self._emit_unit(module, -1, 0, len(module.function_defs))]
        self._module = module
        self._shared_linkage = True
        sizes = []
        for func in module.function_defs:
            self._lines = []
            self._indent = 0
            self._emit_function(func)
            sizes.append(len(self._lines))
        starts = self._unit_starts(module, sizes, target_lines)
        return [
            self._emit_unit(module, unit, first, starts[unit + 1] if unit + 1 < len(starts) else len(sizes))
            for unit, first in enumerate(starts)
        ]

    @staticmethod
    def _unit_starts(module: IRModule, sizes: list[int], target_lines: int) -> list[int]:
        """Units are runs of consecutive functions from the same source module
        packed to about `target_lines` each (at most 64 units), so editing one
        module changes that module's unit and leaves the others byte-identical
        for the native object cache. Synthesized functions join the preceding
        module's run."""
        total = sum(sizes)
        target = max(target_lines, total // 64 + 1)
        starts = [0]
        run_file = module.function_defs[0].source_file if module.function_defs else ""
        run_start = 0
        unit_lines = 0
        for index in range(len(sizes) + 1):
            file = module.function_defs[index].source_file if index < len(sizes) else ""
            if index < len(sizes) and (not file or file == run_file):
                continue
            run_lines = sum(sizes[run_start:index])
            if unit_lines and unit_lines + run_lines > target:
                starts.append(run_start)
                unit_lines = 0
            unit_lines += run_lines
            run_start, run_file = index, file
        return starts

    def _emit_unit(self, module: IRModule, unit_index: int, first: int, end: int) -> str:
        """unit_index -1 is the whole program as one unit; 0 the primary of a
        split program; higher indices are secondaries. [first, end) selects
        function definitions."""
        self._lines = []
        self._indent = 0
        self._module = module
        self._shared_linkage = unit_index >= 0
        self._declarations_only = unit_index > 0
        self._debug_cfile = module.debug_cfile
        if unit_index > 0 and module.debug_cfile:
            self._debug_cfile = f"{module.debug_cfile}.unit-{unit_index}.c"

        self._line("/* Generated by btrc */")
        if unit_index >= 0:
            # Every unit carries every helper the program selected; the ones
            # this unit's functions do not reach are unused here by design.
            self._line('#pragma GCC diagnostic ignored "-Wunused-function"')

        # Reserve the preprocessor slot. In freestanding mode whether btrc_rt.h is
        # needed depends on what the body actually references (e.g. print ->
        # printf is emitted directly, registering no helper), so the prologue is
        # filled in at the end once the whole unit is known.
        preprocessor_slot = len(self._lines)

        for declaration in module.objective_c_classes:
            self._line(f"@class {declaration.name};")
        if module.objective_c_classes:
            self._line("")

        # Runtime helpers; a split program defines their file-scope state in
        # the primary unit and declares it extern in the others.
        for helper in module.helper_decls:
            source = helper.c_source
            if unit_index >= 0:
                source = runtime_state.unit_state(source, unit_index == 0)
            self._raw(source)
            self._line("")

        # Type forwards precede the module's already-planned heterogeneous type
        # declarations. Ordinary function declarations follow complete types.
        for declaration in module.struct_forwards:
            self._emit_struct_forward(declaration)
        if module.struct_forwards:
            self._line("")

        for declaration in module.ordered_type_declarations:
            self._emit_type_declaration(declaration)

        for declaration in module.function_decls:
            self._emit_function_decl(declaration)
        if module.function_decls:
            self._line("")
        if self._shared_linkage:
            # Functions defined in another unit need a prototype here; the
            # module only declares some of them itself.
            for func in module.function_defs:
                self._line(f"{self._function_signature(func)};")
            if module.function_defs:
                self._line("")

        # Global variables
        for declaration in module.global_decls:
            self._emit_global_decl(declaration)
        if module.global_decls:
            self._line("")

        for declaration in module.objective_c_classes:
            self._emit_objective_c_interface(declaration)
        for declaration in module.objective_c_classes:
            self._emit_objective_c_implementation(declaration)

        # GPU kernel WGSL string constants
        for kernel in module.gpu_kernels:
            self._emit_gpu_kernel(kernel)

        # Function definitions
        for func in module.function_defs[first:end]:
            self._emit_function(func)

        # Fill in the reserved include slot now that the body is complete.
        preprocessor_lines = self._build_preprocessor_lines(module)
        self._lines[preprocessor_slot:preprocessor_slot] = preprocessor_lines

        # Resolve #line-reset placeholders now that all line positions are final.
        if module.debug:
            self._fix_cline_resets()

        return "\n".join(self._lines) + "\n"

    def _objective_c_method_signature(self, method: IRObjectiveCMethod) -> str:
        prefix = "+" if method.is_class_method else "-"
        signature = f"{prefix} ({method.return_type.text})"
        if not method.params:
            return signature + method.selector
        return signature + " ".join(
            f"{piece}:({parameter.c_type.text}){parameter.name}"
            for piece, parameter in zip(method.selector.split(":")[:-1], method.params, strict=True)
        )

    def _emit_objective_c_interface(self, declaration: IRObjectiveCClass) -> None:
        protocols = f" <{', '.join(declaration.protocols)}>" if declaration.protocols else ""
        self._line(f"@interface {declaration.name} : {declaration.superclass}{protocols} {{")
        self._line("@private")
        self._indent += 1
        for value in declaration.fields:
            c_type = value.c_type.qualify_volatile_object(
                value.c_type.text, value.is_volatile or value.effective_is_volatile
            )
            self._line(f"{c_type} {value.name};")
        self._indent -= 1
        self._line("}")
        for method in declaration.methods:
            self._line(self._objective_c_method_signature(method) + ";")
        self._line("@end")
        self._line("")

    def _emit_objective_c_implementation(self, declaration: IRObjectiveCClass) -> None:
        self._line(f"@implementation {declaration.name}")
        for method in declaration.methods:
            self._line(self._objective_c_method_signature(method) + " {")
            self._indent += 1
            for statement in method.body.stmts:
                self._emit_stmt(statement)
            self._indent -= 1
            self._line("}")
        self._line("@end")
        self._line("")

    def emit_header(
        self,
        module: IRModule,
        shared_decls: dict | None = None,
    ) -> str:
        """Emit the public header for a precompiled archive."""

        if module.language != "c":
            raise ValueError("native adapters require separate translation units, not a C archive header")
        self._prepare_module(module)
        shared_decls = shared_decls or {}
        self._lines = []
        self._indent = 0

        self._line("#ifndef BTRC_STDLIB_H")
        self._line("#define BTRC_STDLIB_H")
        self._line("")
        self._emit_preprocessor_declarations(module)

        for helper in module.helper_decls:
            self._raw(shared_decls.get(helper.name, helper.c_source))
            self._line("")

        for declaration in module.struct_forwards:
            self._emit_struct_forward(declaration)
        if module.struct_forwards:
            self._line("")

        for declaration in module.ordered_type_declarations:
            self._emit_type_declaration(declaration)

        for declaration in module.function_decls:
            if declaration.is_static:
                continue
            self._emit_function_decl(declaration)
        if any(not declaration.is_static for declaration in module.function_decls):
            self._line("")

        for declaration in module.global_decls:
            if declaration.is_extern:
                self._emit_global_decl(declaration)

        self._line("#endif")
        return "\n".join(self._lines) + "\n"

    def emit_impl(
        self,
        module: IRModule,
        header_include: str,
        shared_names: set | None = None,
    ) -> str:
        """Emit the definition-only implementation for a precompiled archive."""

        if module.language != "c":
            raise ValueError("native adapters require separate translation units, not a C archive implementation")
        self._prepare_module(module)
        shared_names = shared_names or set()
        self._lines = []
        self._indent = 0

        self._line(self._include_text(IRInclude(header=header_include, is_system=False)))
        self._line("")

        private_declarations = [declaration for declaration in module.function_decls if declaration.is_static]
        for declaration in private_declarations:
            self._emit_function_decl(declaration)
        if private_declarations:
            self._line("")

        for helper in module.helper_decls:
            if helper.name in shared_names:
                self._raw(helper.c_source)
                self._line("")

        for declaration in module.global_decls:
            self._emit_global_decl(declaration)
        if module.global_decls:
            self._line("")

        for kernel in module.gpu_kernels:
            self._emit_gpu_kernel(kernel)

        for function in module.function_defs:
            self._emit_function(function)

        return "\n".join(self._lines) + "\n"

    def _build_preprocessor_lines(
        self,
        module: IRModule,
    ) -> list[str]:
        """Build the translation unit's include prologue.

        Hosted mode lists the system headers the IR gen recorded. Freestanding
        mode emits no system header at all: every runtime dependency is funneled
        through one project-local seam, ``btrc_rt.h`` (the embedder retargets it
        — e.g. malloc->kmalloc, printf->printk). A unit that references no
        runtime symbol (the pure subset) and no explicit ``#include`` gets an
        empty prologue, so its translation unit is fully self-contained.

        Runtime requirements are materialized from structured IR before this
        formatting pass; the emitter never scans generated C to infer them."""
        if module.freestanding:
            if any(
                not isinstance(declaration, IRMacroDef) and declaration.is_system
                for declaration in module.preprocessor_decls
            ):
                raise ValueError("freestanding system includes must be lowered before C emission")
            has_seam = any(
                not isinstance(declaration, IRMacroDef) and declaration.header == "btrc_rt.h"
                for declaration in module.preprocessor_decls
            )
            if module.needs_runtime and not has_seam:
                raise ValueError("freestanding runtime dependency lacks a typed btrc_rt.h include")
            lines = [self._preprocessor_text(declaration) for declaration in module.preprocessor_decls]
            if lines:
                lines.append("")
            return lines
        lines = [self._preprocessor_text(declaration) for declaration in module.preprocessor_decls]
        if lines:
            lines.append("")
        return lines

    # --- Function emission ---

    def _emit_function(self, func: IRFunctionDef):
        self._line(f"{self._function_signature(func)} {{")
        if func.body:
            self._indent += 1
            # Reset #line to the generated .c at function entry so a btrc #line
            # left active by the previous function cannot leak into this one's
            # body (which matters for synthesized functions that emit no markers
            # of their own — otherwise a btrc breakpoint binds to glue code).
            debug = getattr(self._module, "debug", False)
            if debug:
                # Stamp every body line with its btrc location. #line only sets a
                # *starting* line — each subsequent physical line auto-increments,
                # so a btrc statement spanning several C lines (e.g. a Vector
                # literal -> N pushes) would smear across N btrc lines unless each
                # line is restamped. Reset to None first so a synthesized function
                # with no markers (e.g. Point_new) maps to the .c, not stale lines.
                self._dbg_enabled = True
                self._dbg_loc = None
            self._emit_block_contents(func.body)
            self._dbg_enabled = False
            self._indent -= 1
        self._line("}")
        self._line("")

    # --- Output helpers ---
    def _line(self, text: str):
        """Emit physical lines with current indentation."""
        for part in text.split("\n"):
            if part.strip():
                if self._dbg_enabled:
                    self._emit_line_directive()
                self._lines.append("    " * self._indent + part)
            else:
                self._lines.append("")

    def _raw(self, text: str):
        """Emit raw text without indentation adjustment."""
        for line in text.rstrip("\n").split("\n"):
            self._lines.append(line)

    @staticmethod
    def _c_line_filename(path: str) -> str:
        """Encode a source path as one C string-literal payload."""

        escaped: list[str] = []
        for character in path:
            codepoint = ord(character)
            if character in {"\\", '"', "?"}:
                escaped.append("\\" + character)
            elif 0x20 <= codepoint < 0x7F:
                escaped.append(character)
            elif codepoint <= 0xFF:
                escaped.append(f"\\{codepoint:03o}")
            else:
                escaped.append(character)
        return "".join(escaped)

    def _emit_line_directive(self):
        """Map the next C line to its btrc origin or generated source."""

        if self._dbg_loc is not None:
            path = self._c_line_filename(self._dbg_loc[0])
            self._lines.append(f'#line {self._dbg_loc[1]} "{path}"')
            return
        cfile = self._debug_cfile or "<btrc-generated>"
        path = self._c_line_filename(cfile)
        self._lines.append(f'#line {self._CLINE_PLACEHOLDER} "{path}"')

    def _fix_cline_resets(self):
        """Resolve generated-source placeholders after final layout is known."""

        for index, line in enumerate(self._lines):
            if self._CLINE_PLACEHOLDER in line:
                self._lines[index] = line.replace(
                    self._CLINE_PLACEHOLDER,
                    str(index + 2),
                )

    def _compound(
        self,
        opening: str,
        values: list[str],
        closing: str,
        *,
        inline_separator: str = "",
        line_separator: str = "\n",
    ) -> str:
        """Keep one structured expression group within the inline budget."""

        inline = opening + inline_separator.join(values) + closing
        if "\n" not in inline and len(inline) <= _INLINE_EXPRESSION_LIMIT:
            return inline
        return opening + "\n" + line_separator.join(values) + "\n" + closing

    def _delimited(
        self,
        opening: str,
        values: list[str],
        closing: str,
    ) -> str:
        """Format a structured expression list without oversized C lines."""

        return self._compound(
            opening,
            values,
            closing,
            inline_separator=", ",
            line_separator=",\n",
        )

    def _cond_expr(self, expression: IRExpr) -> str:
        """Emit an expression for use as a control-flow condition."""

        result = self._expr(expression)
        if result.startswith("(") and result.endswith(")"):
            depth = 0
            quote = None
            escaped = False
            for index, character in enumerate(result):
                if quote is not None:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == quote:
                        quote = None
                    continue
                if character in ("'", '"'):
                    quote = character
                    continue
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                if depth == 0 and index < len(result) - 1:
                    break
            else:
                result = result[1:-1]
        return result

    def _discarded_expr(self, expression: IRExpr) -> str:
        """Render an expression whose value is intentionally discarded."""

        return self._compound("(void)(", [self._expr(expression)], ")")

    def _expr(self, expression: IRExpr) -> str:
        if expression is None:
            raise TypeError("cannot emit a null IR expression")

        if isinstance(expression, IRLiteral):
            return expression.text
        if isinstance(expression, (IRVar, IRFunctionRef)):
            return expression.name
        if isinstance(expression, IRBinOp):
            return self._compound(
                "(",
                [
                    self._expr(expression.left),
                    expression.op,
                    self._expr(expression.right),
                ],
                ")",
                inline_separator=" ",
            )
        if isinstance(expression, IRCommaExpr):
            return self._delimited(
                "(",
                [self._expr(item) for item in expression.expressions],
                ")",
            )
        if isinstance(expression, IRUnaryOp):
            if expression.prefix:
                return self._compound(
                    f"({expression.op}",
                    [self._expr(expression.operand)],
                    ")",
                )
            return self._compound(
                "(",
                [self._expr(expression.operand)],
                f"{expression.op})",
            )
        if isinstance(expression, IRCall):
            arguments = self._delimited(
                "(",
                [self._expr(argument) for argument in expression.args],
                ")",
            )
            callee = expression.callee if isinstance(expression.callee, str) else self._expr(expression.callee)
            return self._compound("", [callee, arguments], "")
        if isinstance(expression, IRObjectiveCSelector):
            return f"@selector({expression.selector})"
        if isinstance(expression, IRCxxNew):
            return f"new {expression.value_type}({', '.join(self._expr(argument) for argument in expression.args)})"
        if isinstance(expression, IRObjectiveCMessage):
            parts = [self._expr(expression.receiver)]
            if expression.args:
                parts.extend(
                    f"{piece}:{self._expr(argument)}"
                    for piece, argument in zip(expression.selector.split(":"), expression.args)
                )
            else:
                parts.append(expression.selector)
            return self._compound("[", parts, "]", inline_separator=" ")
        if isinstance(expression, IRObjectiveCBlock):
            body = CEmitter()
            body._module = self._module
            body._indent = 1
            body._emit_block_contents(expression.body)
            parameters = (
                ", ".join(
                    f"{CType.qualify_volatile_object(str(param.c_type), param.is_volatile)} {param.name}"
                    for param in expression.params
                )
                or "void"
            )
            return f"^{expression.return_type}({parameters}) {{\n" + "\n".join(body._lines) + "\n}"
        if isinstance(expression, IRFieldAccess):
            operator = "->" if expression.arrow else "."
            return self._compound(
                "",
                [self._expr(expression.obj), f"{operator}{expression.field}"],
                "",
            )
        if isinstance(expression, IRCast):
            bridge = {"": "", "borrow": "__bridge ", "retain": "__bridge_retained ", "transfer": "__bridge_transfer "}[
                expression.bridge
            ]
            return self._compound(
                f"(({bridge}{expression.target_type})",
                [self._expr(expression.expr)],
                ")",
            )
        if isinstance(expression, IRTernary):
            return self._compound(
                "(",
                [
                    self._expr(expression.condition),
                    "?",
                    self._expr(expression.true_expr),
                    ":",
                    self._expr(expression.false_expr),
                ],
                ")",
                inline_separator=" ",
            )
        if isinstance(expression, IRSizeof):
            operand = (
                self._expr(expression.operand) if isinstance(expression.operand, IRExpr) else str(expression.operand)
            )
            return self._compound("sizeof(", [operand], ")")
        if isinstance(expression, IRInitializerList):
            values = [self._expr(value) for value in expression.elements] or ["0"]
            return self._delimited("{", values, "}")
        if isinstance(expression, IRCompoundLiteral):
            fields = [
                self._compound(
                    f".{name} = ",
                    [self._expr(value)],
                    "",
                )
                for name, value in expression.fields
            ] or ["0"]
            return self._compound(
                f"({expression.c_type})",
                [self._delimited("{", fields, "}")],
                "",
            )
        if isinstance(expression, IRIndex):
            index = self._compound("[", [self._expr(expression.index)], "]")
            return self._compound("", [self._expr(expression.obj), index], "")
        if isinstance(expression, IRAddressOf):
            return self._compound("(&", [self._expr(expression.expr)], ")")
        if isinstance(expression, IRDeref):
            return self._compound("(*", [self._expr(expression.expr)], ")")
        if isinstance(expression, IRStmtExpr):
            for statement in expression.stmts:
                safe_initializer = isinstance(statement, IRVarDecl) and (
                    statement.init is None
                    or (isinstance(statement.init, IRLiteral) and statement.init.text in {"0", "NULL", "false"})
                )
                if not safe_initializer:
                    raise ValueError(
                        "IRStmtExpr setup permits uninitialized variable declarations "
                        "or declarations with a literal zero initializer only"
                    )
                self._emit_stmt(statement)
            return self._expr(expression.result)
        raise TypeError(f"unsupported IR expression: {type(expression).__name__}")

    @staticmethod
    def _qualified_decl_type(declaration: IRVarDecl) -> str:
        """Format a local declaration's storage and volatile qualifiers."""

        if declaration.is_static and declaration.is_extern:
            raise ValueError(f"IR variable {declaration.name!r} is both static and extern")
        storage = "static " if declaration.is_static else "extern " if declaration.is_extern else ""
        return storage + CType.qualify_volatile_object(
            str(declaration.c_type),
            declaration.is_volatile,
        )

    def _qualified_global_type(self, declaration: IRGlobalDecl) -> str:
        if declaration.is_static and declaration.is_extern:
            raise ValueError(f"IR global {declaration.name!r} is both static and extern")
        if self._declarations_only or declaration.is_extern:
            storage = "extern "
        elif declaration.is_static and not self._shared_linkage:
            storage = "static "
        else:
            storage = ""
        return storage + CType.qualify_volatile_object(
            str(declaration.c_type),
            declaration.is_volatile,
        )

    def _emit_global_decl(self, declaration: IRGlobalDecl):
        suffix = (
            f"[{self._expr(declaration.array_size)}]"
            if declaration.array_size is not None
            else "[]"
            if declaration.is_unsized_array
            else ""
        )
        initializer = f" = {self._expr(declaration.init)}" if declaration.init and not self._declarations_only else ""
        self._line(f"{self._qualified_global_type(declaration)} {declaration.name}{suffix}{initializer};")

    def _emit_block_contents(self, block):
        for statement in block.stmts:
            self._emit_stmt(statement)

    def _emit_stmt(self, statement: IRStmt):
        if isinstance(statement, IRLineMarker):
            self._dbg_loc = (statement.file, statement.line)
            return
        if isinstance(statement, IRVarDecl):
            c_type = self._qualified_decl_type(statement)
            array = (
                f"[{self._expr(statement.array_size)}]"
                if statement.array_size is not None
                else "[]"
                if statement.is_unsized_array
                else ""
            )
            initializer = f" = {self._expr(statement.init)}" if statement.init else ""
            self._line(f"{c_type} {statement.name}{array}{initializer};")
        elif isinstance(statement, IRAssign):
            self._line(f"{self._expr(statement.target)} = {self._expr(statement.value)};")
        elif isinstance(statement, IRReturn):
            value = f" {self._expr(statement.value)}" if statement.value else ""
            self._line(f"return{value};")
        elif isinstance(statement, IRBlock):
            self._line("{")
            self._indent += 1
            self._emit_block_contents(statement)
            self._indent -= 1
            self._line("}")
        elif isinstance(statement, IRCxxDelete):
            self._line(f"delete {self._expr(statement.value)};")
        elif isinstance(statement, IRCxxExceptionBoundary):
            self._line("try {")
            self._indent += 1
            self._emit_block_contents(statement.body)
            self._indent -= 1
            if statement.allocation_failure is not None:
                self._line("} catch (const std::bad_alloc&) {")
                self._indent += 1
                self._emit_block_contents(statement.allocation_failure)
                self._indent -= 1
            self._line("} catch (...) {")
            self._indent += 1
            self._emit_block_contents(statement.failure)
            self._indent -= 1
            self._line("}")
        elif isinstance(statement, (IRObjectiveCAutoreleasePool, IRObjectiveCExceptionBoundary)):
            self._line("@autoreleasepool {" if isinstance(statement, IRObjectiveCAutoreleasePool) else "@try {")
            self._indent += 1
            self._emit_block_contents(statement.body)
            self._indent -= 1
            if isinstance(statement, IRObjectiveCExceptionBoundary):
                self._line("} @catch (...) {")
                self._indent += 1
                self._emit_block_contents(statement.failure)
                self._indent -= 1
            self._line("}")
        elif isinstance(statement, IRIf):
            self._line(f"if ({self._cond_expr(statement.condition)}) {{")
            if statement.then_block:
                self._indent += 1
                self._emit_block_contents(statement.then_block)
                self._indent -= 1
            self._emit_else_tail(statement)
        elif isinstance(statement, IRWhile):
            self._line(f"while ({self._cond_expr(statement.condition)}) {{")
            if statement.body:
                self._indent += 1
                self._emit_block_contents(statement.body)
                self._indent -= 1
            self._line("}")
        elif isinstance(statement, IRDoWhile):
            condition = self._cond_expr(statement.condition)
            self._line("do {")
            if statement.body:
                self._indent += 1
                self._emit_block_contents(statement.body)
                self._indent -= 1
            self._line(f"}} while ({condition});")
        elif isinstance(statement, IRFor):
            initialization = self._for_init_text(statement.init)
            condition = self._expr(statement.condition) if statement.condition else ""
            update = self._expr(statement.update) if statement.update else ""
            self._line(f"for ({initialization}; {condition}; {update}) {{")
            if statement.body:
                self._indent += 1
                self._emit_block_contents(statement.body)
                self._indent -= 1
            self._line("}")
        elif isinstance(statement, IRSwitch):
            self._line(f"switch ({self._expr(statement.value)}) {{")
            self._indent += 1
            for index, case in enumerate(statement.cases):
                label = f"case {self._expr(case.value)}:" if case.value else "default:"
                self._line(label)
                self._line("{")
                self._indent += 1
                for child in case.body:
                    self._emit_stmt(child)
                self._indent -= 1
                self._line("}")
                if case.falls_through and index + 1 < len(statement.cases):
                    self._line("/* fall through */")
            self._indent -= 1
            self._line("}")
        elif isinstance(statement, IRExprStmt):
            self._line(f"{self._discarded_expr(statement.expr)};")
        elif isinstance(statement, IRBreak):
            self._line("break;")
        elif isinstance(statement, IRContinue):
            self._line("continue;")
        elif isinstance(statement, IRGpuKernel):
            self._emit_gpu_kernel(statement)
        else:
            raise TypeError(f"unsupported IR statement: {type(statement).__name__}")

    def _for_init_text(self, initialization) -> str:
        if isinstance(initialization, IRVarDecl):
            c_type = self._qualified_decl_type(initialization)
            array = (
                f"[{self._expr(initialization.array_size)}]"
                if initialization.array_size is not None
                else "[]"
                if initialization.is_unsized_array
                else ""
            )
            initializer = f" = {self._expr(initialization.init)}" if initialization.init else ""
            return f"{c_type} {initialization.name}{array}{initializer}"
        if isinstance(initialization, IRAssign):
            return f"{self._expr(initialization.target)} = {self._expr(initialization.value)}"
        if isinstance(initialization, IRExprStmt):
            return self._discarded_expr(initialization.expr)
        if initialization is None:
            return ""
        raise TypeError(f"unsupported IR for-loop initializer: {type(initialization).__name__}")

    def _emit_else_tail(self, statement: IRIf):
        if not statement.else_block or not statement.else_block.stmts:
            self._line("}")
            return
        self._line("} else {")
        self._indent += 1
        self._emit_block_contents(statement.else_block)
        self._indent -= 1
        self._line("}")

    def _emit_type_declaration(self, declaration):
        """Format one already-ordered typed declaration."""

        if isinstance(declaration, IREnumDef):
            self._emit_enum_def(declaration)
        elif isinstance(declaration, IRFunctionPointerTypedef):
            self._emit_function_pointer_typedef(declaration)
            self._line("")
        elif isinstance(declaration, IRTypedefDef):
            self._emit_typedef(declaration)
        elif isinstance(declaration, IRTaggedUnionDef):
            self._emit_tagged_union(declaration)
        elif isinstance(declaration, IRStructDef):
            self._emit_struct(declaration)
        else:
            raise TypeError(f"unsupported typed declaration {type(declaration).__name__}")

    def _emit_enum_def(self, enum: IREnumDef):
        self._line("typedef enum {" if enum.name is not None else "enum {")
        self._indent += 1
        for index, value in enumerate(enum.values):
            comma = "," if index < len(enum.values) - 1 else ""
            suffix = f" = {self._expr(value.value)}" if value.value is not None else ""
            self._line(f"{value.name}{suffix}{comma}")
        self._indent -= 1
        self._line(f"}} {enum.name};" if enum.name is not None else "};")
        self._line("")

    def _emit_struct_forward(self, declaration: IRStructForward):
        self._line(f"typedef struct {declaration.name} {declaration.name};")

    def _emit_function_pointer_typedef(
        self,
        declaration: IRFunctionPointerTypedef,
    ):
        parameters = ", ".join(map(str, declaration.param_types)) or "void"
        self._line(f"typedef {declaration.return_type} (*{declaration.name})({parameters});")

    def _function_signature(self, declaration: IRFunctionDecl) -> str:
        parameters = (
            ", ".join(
                f"{CType.qualify_volatile_object(str(parameter.c_type), parameter.is_volatile)} {parameter.name}"
                for parameter in declaration.params
            )
            or "void"
        )
        internal = declaration.is_static and not self._shared_linkage
        storage = 'extern "C" ' if declaration.c_linkage else "static " if internal else ""
        return f"{storage}{declaration.return_type} {declaration.name}({parameters})"

    def _emit_function_decl(self, declaration: IRFunctionDecl):
        self._line(f"{self._function_signature(declaration)};")

    def _emit_typedef(self, typedef: IRTypedefDef):
        target_type = CType.qualify_volatile_object(
            str(typedef.target_type),
            typedef.is_volatile,
        )
        self._line(f"typedef {target_type} {typedef.name};")
        self._line("")

    def _emit_tagged_union(self, tagged: IRTaggedUnionDef):
        payload_variants = [variant for variant in tagged.variants if variant.fields]
        for variant in payload_variants:
            data_name = f"{tagged.name}_{variant.name}_Data"
            self._line(f"typedef struct {data_name} {{")
            self._indent += 1
            for field in variant.fields:
                c_type = CType.qualify_volatile_object(
                    str(field.c_type),
                    field.is_volatile,
                )
                self._line(f"{c_type} {field.name};")
            self._indent -= 1
            self._line(f"}} {data_name};")
            self._line("")

        self._line(f"struct {tagged.name} {{")
        self._indent += 1
        self._line(f"{tagged.tag_type} tag;")
        if payload_variants:
            self._line("union {")
            self._indent += 1
            for variant in payload_variants:
                data_name = f"{tagged.name}_{variant.name}_Data"
                self._line(f"{data_name} {variant.name};")
            self._indent -= 1
            self._line("} data;")
        self._indent -= 1
        self._line("};")
        self._line("")

    def _emit_struct(self, struct: IRStructDef):
        if struct.pack_alignment is not None:
            self._line(f"#pragma pack(push, {struct.pack_alignment})")
        self._line(f"struct {struct.name} {{")
        self._indent += 1
        for field in struct.fields:
            suffix = f"[{self._expr(field.array_size)}]" if field.array_size is not None else ""
            c_type = CType.qualify_volatile_object(
                str(field.c_type),
                field.is_volatile,
            )
            self._line(f"{c_type} {field.name}{suffix};")
        self._indent -= 1
        self._line("};")
        if struct.pack_alignment is not None:
            self._line("#pragma pack(pop)")
        self._line("")

    @staticmethod
    def _include_text(include: IRInclude) -> str:
        if include.is_system:
            return f"#include <{include.header}>"
        return f'#include "{include.header}"'

    @staticmethod
    def _macro_text(macro: IRMacroDef) -> str:
        parameters = "" if macro.params is None else f"({', '.join(macro.params)})"
        replacement = f" {macro.replacement}" if macro.replacement else ""
        return f"#define {macro.name}{parameters}{replacement}"

    def _preprocessor_text(
        self,
        declaration: IRInclude | IRMacroDef,
    ) -> str:
        if isinstance(declaration, IRInclude):
            return self._include_text(declaration)
        return self._macro_text(declaration)

    def _emit_preprocessor_declarations(self, module: IRModule) -> None:
        for declaration in module.preprocessor_decls:
            self._line(self._preprocessor_text(declaration))
        if module.preprocessor_decls:
            self._line("")

    def _emit_gpu_kernel(self, kernel: IRGpuKernel):
        if self._declarations_only:
            self._line(f"extern const char* {kernel.name}_wgsl;")
            self._line("")
            return
        source = WgslEmitter.emit_ir_kernel(kernel)
        escaped = source.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        storage = "" if self._shared_linkage else "static "
        self._line(f'{storage}const char* {kernel.name}_wgsl = "{escaped}";')
        self._line("")
