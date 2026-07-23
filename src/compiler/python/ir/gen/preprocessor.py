"""Structured lowering for supported source preprocessor directives."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ...ast_nodes import PreprocessorDirective
from ..nodes import IRInclude, IRMacroDef
from .errors import CodegenError
from .packing import is_pack_pragma

if TYPE_CHECKING:
    from .lowerer import IRLowerer

_DIRECTIVE = re.compile(r"^#\s*([A-Za-z_][A-Za-z0-9_]*)(.*)$")
_DEFINE_NAME = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*)(.*)$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INCLUDE = re.compile(r'^\s*(?:<([^>\r\n]+)>|"([^"\r\n]+)")\s*$')
_C11_TRIGRAPH = re.compile(r"\?\?[=/'()!<>-]")


def lower_preprocessor(
    generator: IRLowerer,
    declaration: PreprocessorDirective,
) -> None:
    """Lower one directive or reject it before C emission."""

    if _C11_TRIGRAPH.search(declaration.text):
        raise CodegenError("C11 trigraphs in preprocessor directives are unsupported")
    if "\n" in declaration.text or "\r" in declaration.text:
        raise CodegenError("multi-line preprocessor directives are unsupported")
    text = declaration.text.strip()
    if text.endswith("\\"):
        raise CodegenError("multi-line preprocessor directives are unsupported")
    if is_pack_pragma(text):
        return

    match = _DIRECTIVE.fullmatch(text)
    if match is None:
        raise CodegenError(f"malformed preprocessor directive: {text!r}")
    directive, payload = match.groups()
    if directive == "include":
        generator.module.preprocessor_decls.append(_parse_include(payload, text))
    elif directive == "define":
        generator.module.preprocessor_decls.append(_parse_define(payload, text))
    elif directive == "pragma":
        raise CodegenError(f"unsupported #pragma directive: {text}")
    else:
        raise CodegenError(f"unsupported preprocessor directive '#{directive}'")


def _parse_include(payload: str, source: str) -> IRInclude:
    match = _INCLUDE.fullmatch(payload)
    if match is None:
        raise CodegenError(f"malformed #include directive: {source}")
    system_header, local_header = match.groups()
    header = system_header or local_header
    if not header:
        raise CodegenError(f"malformed #include directive: {source}")
    try:
        return IRInclude(header=header, is_system=system_header is not None)
    except (TypeError, ValueError) as error:
        raise CodegenError(f"malformed #include directive: {source}") from error


def _parse_define(payload: str, source: str) -> IRMacroDef:
    match = _DEFINE_NAME.fullmatch(payload)
    if match is None:
        raise CodegenError(f"malformed #define directive: {source}")
    name, suffix = match.groups()
    if not suffix.startswith("("):
        try:
            return IRMacroDef(name=name, replacement=suffix.lstrip())
        except (TypeError, ValueError) as error:
            raise CodegenError(f"malformed #define directive: {source}") from error

    close = suffix.find(")")
    if close < 0:
        raise CodegenError(f"malformed function-like #define: {source}")
    parameter_text = suffix[1:close].strip()
    params = [] if not parameter_text else [parameter.strip() for parameter in parameter_text.split(",")]
    if any(
        not _IDENTIFIER.fullmatch(parameter) and not (parameter == "..." and index == len(params) - 1)
        for index, parameter in enumerate(params)
    ):
        raise CodegenError(f"invalid function-like macro parameters: {source}")
    if len(params) != len(set(params)):
        raise CodegenError(f"duplicate function-like macro parameter: {source}")
    try:
        return IRMacroDef(
            name=name,
            params=params,
            replacement=suffix[close + 1 :].lstrip(),
        )
    except (TypeError, ValueError) as error:
        raise CodegenError(f"malformed #define directive: {source}") from error
