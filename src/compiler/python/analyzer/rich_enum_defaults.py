"""Declaration-scope analysis for rich-enum variant defaults."""

from __future__ import annotations

from ..ast_nodes import TypeExpr


def analyze_rich_enum_defaults(analyzer, declaration) -> None:
    """Analyze each variant default with only earlier parameters in scope."""

    previous_callable = analyzer.current_callable
    previous_return = analyzer.current_return_type
    previous_parameter_default = analyzer._analyzing_parameter_default
    analyzer.current_return_type = TypeExpr(base=declaration.name)
    try:
        for variant in declaration.variants:
            analyzer.current_callable = variant
            analyzer._push_scope()
            try:
                analyzer._validate_default_params(
                    variant.params,
                    variant.line,
                    variant.col,
                )
                for parameter in variant.params:
                    analyzer._collect_generic_instances(parameter.type)
                    if parameter.default is not None:
                        analyzer._analyzing_parameter_default = True
                        analyzer._analyze_expr(parameter.default)
                        analyzer._validate_callable_storage(
                            parameter.type,
                            parameter.default,
                            True,
                            parameter.line or variant.line,
                            parameter.col or variant.col,
                        )
                        analyzer._validate_typed_initializer(
                            parameter.type,
                            parameter.default,
                            f"Default for rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                            parameter.line or variant.line,
                            parameter.col or variant.col,
                        )
                        actual = analyzer._infer_type(parameter.default)
                        if analyzer._argument_produces_owned_result(
                            parameter.default
                        ) or analyzer._requires_string_conversion(
                            parameter.type,
                            actual,
                        ):
                            analyzer.rich_enum_unsafe_default_ids.add(id(parameter.default))
                    analyzer._analyzing_parameter_default = False
                    if analyzer._claim_local_binding(
                        parameter.name,
                        "parameter",
                        parameter.name_line or parameter.line,
                        parameter.name_col or parameter.col,
                        c_name_generated=True,
                    ):
                        analyzer.scope.define(
                            parameter.name,
                            analyzer._param_symbol(parameter),
                        )
            finally:
                analyzer._pop_scope()
    finally:
        analyzer.current_callable = previous_callable
        analyzer.current_return_type = previous_return
        analyzer._analyzing_parameter_default = previous_parameter_default


__all__ = ["analyze_rich_enum_defaults"]
