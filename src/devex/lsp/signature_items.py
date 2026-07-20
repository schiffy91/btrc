"""LSP signature and parameter item construction."""

from lsprotocol import types as lsp

from src.compiler.python.ast_nodes import FunctionDecl, MethodDecl
from src.devex.lsp.position_utils import type_repr


def _make_param_info(ptype: str, pname: str) -> lsp.ParameterInformation:
    return lsp.ParameterInformation(label=f"{ptype} {pname}", documentation=None)


def _make_signature(
    label: str,
    params: list[lsp.ParameterInformation],
    active_param: int,
    documentation: str | None = None,
) -> lsp.SignatureHelp:
    active = min(active_param, max(0, len(params) - 1)) if params else 0
    signature = lsp.SignatureInformation(
        label=label,
        parameters=params,
        documentation=documentation,
        active_parameter=active,
    )
    return lsp.SignatureHelp(
        signatures=[signature],
        active_signature=0,
        active_parameter=active,
    )


def _signature_from_param_list(
    func_name: str,
    return_type: str,
    param_list: list[tuple[str, str]],
    active_param: int,
    context: str | None = None,
) -> lsp.SignatureHelp:
    params = ", ".join(f"{ptype} {name}" for ptype, name in param_list)
    label = f"{func_name}({params})"
    if return_type and return_type != "void":
        label = f"{return_type} {label}"
    return _make_signature(
        label,
        [_make_param_info(ptype, name) for ptype, name in param_list],
        active_param,
        documentation=context,
    )


def _signature_from_function_decl(
    decl: FunctionDecl,
    active_param: int,
) -> lsp.SignatureHelp:
    params = [(type_repr(param.type), param.name) for param in decl.params]
    return _signature_from_param_list(
        decl.name,
        type_repr(decl.return_type),
        params,
        active_param,
    )


def _signature_from_method_decl(
    class_name: str,
    method: MethodDecl,
    active_param: int,
    is_constructor: bool = False,
) -> lsp.SignatureHelp:
    params = [(type_repr(param.type), param.name) for param in method.params]
    name = class_name if is_constructor else method.name
    return_type = class_name if is_constructor else type_repr(method.return_type)
    kind = "Constructor" if is_constructor else "Method"
    return _signature_from_param_list(
        name,
        return_type,
        params,
        active_param,
        context=f"{kind} of {class_name}",
    )
