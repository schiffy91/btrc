"""Generated symbol claims for simple and rich enums."""


def claim_enum_symbols(analyzer, declaration, claims) -> None:
    for value in declaration.values:
        analyzer._claim_generated_symbol(
            f"{declaration.name}_{value.name}",
            f"enum value '{declaration.name}.{value.name}'",
            value.line,
            value.col,
            claims,
        )
    analyzer._claim_generated_symbol(
        f"{declaration.name}_toString",
        f"enum helper for '{declaration.name}'",
        declaration.line,
        declaration.col,
        claims,
    )


def claim_rich_enum_symbols(analyzer, declaration, claims) -> None:
    name = declaration.name
    analyzer._claim_generated_symbol(
        f"{name}_Tag",
        f"tag type for rich enum '{name}'",
        declaration.line,
        declaration.col,
        claims,
    )
    for variant in declaration.variants:
        for symbol, role in (
            (f"{name}_{variant.name}_TAG", "tag value"),
            (f"{name}_{variant.name}", "constructor"),
        ):
            analyzer._claim_generated_symbol(
                symbol,
                f"{role} for rich-enum variant '{name}.{variant.name}'",
                variant.line,
                variant.col,
                claims,
            )
        if variant.params:
            analyzer._claim_generated_symbol(
                f"{name}_{variant.name}_Data",
                f"payload type for rich-enum variant '{name}.{variant.name}'",
                variant.line,
                variant.col,
                claims,
            )
    analyzer._claim_generated_symbol(
        f"{name}_toString",
        f"enum helper for '{name}'",
        declaration.line,
        declaration.col,
        claims,
    )


__all__ = ["claim_enum_symbols", "claim_rich_enum_symbols"]
