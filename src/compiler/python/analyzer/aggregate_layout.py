"""Completeness and dependency contracts for by-value aggregate layouts."""

from ..ast_nodes import (
    ClassDecl,
    FieldDecl,
    FunctionDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    SizeofExprOp,
    SizeofType,
    StructDecl,
    TypedefDecl,
)
from ..type_identity import is_semantic_scalar_void


class AggregateLayoutContractsMixin:
    def _validate_aggregate_declarations(self, program) -> None:
        """Reject source layouts that no strict-C declaration order can satisfy."""

        declarations = list(self._decls_with_file(program))
        self._validate_typedef_cycles(declarations)
        graph: dict[str, set[str]] = {}
        owners = {}
        previous_file = self.current_source_file
        for declaration in declarations:
            self.current_source_file = getattr(declaration, "source_file", None)
            if isinstance(declaration, StructDecl) and not declaration.is_forward:
                owners[declaration.name] = declaration
                graph[declaration.name] = set()
                for field in declaration.fields:
                    subject = f"Struct field '{declaration.name}.{field.name}'"
                    self._validate_complete_aggregate_use(field.type, subject, field.line, field.col)
                    graph[declaration.name].update(self._value_aggregate_names(field.type))
            elif isinstance(declaration, RichEnumDecl):
                owners[declaration.name] = declaration
                graph[declaration.name] = set()
                for variant in declaration.variants:
                    for parameter in variant.params:
                        subject = f"Rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'"
                        self._validate_complete_aggregate_use(
                            parameter.type,
                            subject,
                            parameter.line,
                            parameter.col,
                        )
                        graph[declaration.name].update(self._value_aggregate_names(parameter.type))
            elif isinstance(declaration, FunctionDecl) and declaration.body:
                self._validate_callable_complete_types(declaration, declaration.name)
            elif isinstance(declaration, ClassDecl):
                self._validate_class_complete_types(declaration)
        self.current_source_file = previous_file
        self._report_dependency_cycles(graph, owners, "Aggregate")

    def _validate_callable_complete_types(self, declaration, owner) -> None:
        if not getattr(declaration, "is_constructor", False):
            self._validate_complete_aggregate_use(
                declaration.return_type,
                f"Return type of '{owner}'",
                declaration.line,
                declaration.col,
            )
        for parameter in declaration.params:
            self._validate_complete_aggregate_use(
                parameter.type,
                f"Parameter '{owner}.{parameter.name}'",
                parameter.line,
                parameter.col,
            )

    def _validate_class_complete_types(self, declaration) -> None:
        for member in declaration.members:
            if isinstance(member, FieldDecl):
                self._validate_complete_aggregate_use(
                    member.type,
                    f"Field '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                )
            elif isinstance(member, PropertyDecl):
                self._validate_complete_aggregate_use(
                    member.type,
                    f"Property '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                )
            elif isinstance(member, MethodDecl) and member.body:
                self._validate_callable_complete_types(member, f"{declaration.name}.{member.name}")

    def _validate_complete_aggregate_use(self, type_expr, subject, line=0, col=0, *, sizeof=False) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None or canonical.pointer_depth > 0:
            return True
        if canonical.base == "Tuple":
            return all(
                self._validate_complete_aggregate_use(argument, subject, line, col, sizeof=sizeof)
                for argument in canonical.generic_args
            )
        name = canonical.base.removeprefix("struct ")
        if name not in self.declarations.struct_table or name in self.declarations.struct_definitions:
            return True
        if sizeof:
            self._error(f"{subject} cannot use incomplete type '{name}'", line, col)
        else:
            self._error(f"{subject} uses incomplete struct '{name}'", line, col)
        return False

    def _value_aggregate_names(self, type_expr) -> set[str]:
        canonical = self._canonical_type(type_expr)
        if canonical is None or canonical.pointer_depth > 0:
            return set()
        if canonical.base == "Tuple":
            return {name for argument in canonical.generic_args for name in self._value_aggregate_names(argument)}
        name = canonical.base.removeprefix("struct ")
        if name in self.declarations.struct_definitions or name in self.declarations.rich_enum_table:
            return {name}
        return set()

    def _validate_typedef_cycles(self, declarations) -> None:
        typedefs = {
            declaration.alias: declaration for declaration in declarations if isinstance(declaration, TypedefDecl)
        }
        graph = {
            name: self._referenced_aliases(declaration.original, set(typedefs))
            for name, declaration in typedefs.items()
        }
        self._report_dependency_cycles(graph, typedefs, "Cyclic typedef")

    def _referenced_aliases(self, type_expr, aliases) -> set[str]:
        result = {type_expr.base} & aliases
        for argument in type_expr.generic_args:
            result.update(self._referenced_aliases(argument, aliases))
        return result

    def _report_dependency_cycles(self, graph, owners, label) -> None:
        state: dict[str, int] = {}
        stack: list[str] = []
        reported: set[frozenset[str]] = set()

        def visit(name):
            state[name] = 1
            stack.append(name)
            for dependency in sorted(graph.get(name, ())):
                if dependency not in graph:
                    continue
                if state.get(dependency, 0) == 0:
                    visit(dependency)
                elif state.get(dependency) == 1:
                    cycle = stack[stack.index(dependency) :] + [dependency]
                    key = frozenset(cycle)
                    if key not in reported:
                        reported.add(key)
                        owner = owners[name]
                        previous_file = self.current_source_file
                        self.current_source_file = getattr(owner, "source_file", None)
                        self._error(
                            f"{label} dependency cycle involving " + " -> ".join(f"'{item}'" for item in cycle),
                            owner.line,
                            owner.col,
                        )
                        self.current_source_file = previous_file
            stack.pop()
            state[name] = 2

        for name in graph:
            if state.get(name, 0) == 0:
                visit(name)

    def _validate_sizeof_operand(self, expression) -> None:
        operand = expression.operand
        if isinstance(operand, SizeofType):
            type_expr = operand.type
            line, col = type_expr.line or expression.line, type_expr.col or expression.col
        elif isinstance(operand, SizeofExprOp):
            type_expr = self._infer_type(operand.expr)
            line, col = expression.line, expression.col
        else:
            return
        canonical = self._canonical_type(type_expr)
        if canonical is None:
            return
        if is_semantic_scalar_void(canonical):
            self._error("sizeof cannot be applied to void", line, col)
            return
        self._validate_complete_aggregate_use(canonical, "sizeof", line, col, sizeof=True)


__all__ = ["AggregateLayoutContractsMixin"]
