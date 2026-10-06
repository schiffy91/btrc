"""The editor's ``btrc.target`` setting (platform-target-contract.md §1.10).

The workspace parses the setting through ``PackageTarget.parse``: a valid
label conditions every file and types every literal for its row, an invalid
one is one workspace diagnostic with the §1.5 message and falls back to the
host, and an unrecognized host with no setting analyses with the named
fallback row while conditioning keeps no target (D13).
"""

from __future__ import annotations

import json
from pathlib import Path

from lsprotocol import types as lsp

from src.compiler.python.abi.hosted import TargetRepository
from src.compiler.python.frontend.packages import PackageTarget
from src.devex.lsp.analysis.document import DocumentAnalyzer
from src.devex.lsp.protocol.server import BtrcLanguageServer
from src.devex.lsp.workspace.cache import UnitCache
from src.devex.lsp.workspace.workspace import LSP_FALLBACK_TARGET, TargetSelection, Workspace

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_JSON = REPO_ROOT / "src" / "devex" / "vscode" / "package.json"

# Windows defines _WIN32 and Linux does not, so the two rows keep different
# halves; only the Windows half names an undefined identifier.
WIN32_REGION = """\
#if _WIN32
int main() { return undefinedOnWindows; }
#else
int main() { return 0; }
#endif
"""

INVALID_LABEL = "windows-x86_64-msvc"
INVALID_MESSAGE = (
    "unsupported target 'windows-x86_64-msvc'; expected one of android-aarch64, android-x86_64, "
    "ios-aarch64, ios-aarch64-simulator, linux-aarch64, linux-x86_64, macos-aarch64, macos-x86_64, "
    "windows-aarch64, windows-aarch64-msvc, windows-x86_64"
)


def _host_target() -> PackageTarget | None:
    try:
        return PackageTarget.parse(None)
    except ValueError:
        return None


def _messages(workspace: Workspace, uri: str, source: str) -> list[str]:
    return [diagnostic.message for diagnostic in DocumentAnalyzer(workspace).analyze(uri, source).diagnostics]


def test_the_enum_suggestions_are_the_target_rows() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    setting = package["contributes"]["configuration"]["properties"]["btrc.target"]
    assert setting["type"] == "string"
    assert setting["default"] == ""
    # Regenerate by replacing this list with ["", *TargetRepository.labels()].
    assert setting["enum"] == ["", *TargetRepository.labels()]
    assert len(setting["enumDescriptions"]) == len(setting["enum"])
    assert "./src/language_server/target.ts" in package["scripts"]["esbuild-test-modules"]


def test_a_switch_from_linux_to_windows_flips_a_win32_region(tmp_path) -> None:
    uri = (tmp_path / "Main.btrc").as_uri()
    workspace = Workspace(target="linux-x86_64")
    assert workspace.target.conditioning == PackageTarget("linux", "x86_64")
    assert workspace.target.problems == ()
    assert _messages(workspace, uri, WIN32_REGION) == []

    assert workspace.set_target("windows-x86_64") is True
    assert workspace.target.analysis.label == "windows-x86_64"
    messages = _messages(workspace, uri, WIN32_REGION)
    assert len(messages) == 1 and "undefinedOnWindows" in messages[0]

    # An alias of the same row changes nothing, and switching back restores.
    assert workspace.set_target("windows-x64") is False
    assert workspace.set_target("linux-x86_64") is True
    assert _messages(workspace, uri, WIN32_REGION) == []


def test_the_target_types_long_for_its_row() -> None:
    linux = TargetSelection.resolve("linux-x86_64").analysis
    windows = TargetSelection.resolve("windows-x86_64").analysis
    assert linux.sizeof_long == 8
    assert windows.sizeof_long == 4


def test_an_invalid_label_is_one_diagnostic_and_falls_back_to_the_host() -> None:
    selection = TargetSelection.resolve(INVALID_LABEL)
    host = _host_target()
    unknown_host = () if host is not None else (TargetRepository.UNKNOWN_HOST_MESSAGE,)
    assert selection.problems == (INVALID_MESSAGE, *unknown_host)
    assert selection.setting == INVALID_LABEL
    assert selection.conditioning == host
    assert selection.analysis == (host.row if host is not None else PackageTarget.parse(LSP_FALLBACK_TARGET).row)
    # The empty setting is the host, with no problem.
    assert TargetSelection.resolve("") == TargetSelection.resolve(None)
    assert TargetSelection.resolve("").problems == unknown_host
    assert TargetSelection.resolve("").conditioning == host


def test_an_unknown_host_reports_once_and_analyses_with_the_fallback_row(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TargetRepository, "host", classmethod(lambda cls, system=None, machine=None: None))
    workspace = Workspace()
    assert workspace.target.problems == (TargetRepository.UNKNOWN_HOST_MESSAGE,)
    assert workspace.target.conditioning is None
    assert workspace.target.analysis.label == LSP_FALLBACK_TARGET == "linux-x86_64"

    # A plain file analyses; the first conditional still fails (D13).
    assert _messages(workspace, (tmp_path / "Plain.btrc").as_uri(), "int main() { return 0; }\n") == []
    conditioned = _messages(workspace, (tmp_path / "Tested.btrc").as_uri(), WIN32_REGION)
    assert len(conditioned) == 1 and "preprocessor conditionals need a target" in conditioned[0]

    # An invalid label adds its own message; a valid one clears both.
    assert TargetSelection.resolve(INVALID_LABEL).problems == (
        INVALID_MESSAGE,
        TargetRepository.UNKNOWN_HOST_MESSAGE,
    )
    assert workspace.set_target("windows-x86_64") is True
    assert workspace.target.problems == ()


def test_a_target_change_rekeys_the_persistent_unit_cache(tmp_path) -> None:
    source = "int main() { return 0; }\n"
    workspace = Workspace(target="linux-x86_64", unit_cache=UnitCache(str(tmp_path)))
    linux_entry = workspace._unit_cache.entry_path(source)
    workspace.set_target("windows-x86_64")
    windows_entry = workspace._unit_cache.entry_path(source)
    assert linux_entry != windows_entry
    assert Path(windows_entry).parent == Path(linux_entry).parent == tmp_path
    workspace.set_target("linux-x86_64")
    assert workspace._unit_cache.entry_path(source) == linux_entry


class _Document:
    def __init__(self, source: str) -> None:
        self.source = source


class _EditorWorkspace:
    """The pygls workspace slice the server reads: open documents and the root."""

    def __init__(self, uri: str, source: str, root_uri: str) -> None:
        self.text_documents = {uri: _Document(source)}
        self.folders: dict = {}
        self.root_uri = root_uri

    def get_text_document(self, uri: str) -> _Document:
        return self.text_documents[uri]


def _server(monkeypatch, uri: str, root_uri: str) -> tuple[BtrcLanguageServer, list[lsp.PublishDiagnosticsParams]]:
    server = BtrcLanguageServer(debounce_seconds=0)
    published: list[lsp.PublishDiagnosticsParams] = []
    monkeypatch.setattr(server, "text_document_publish_diagnostics", published.append, raising=False)
    monkeypatch.setattr(server.protocol, "_workspace", _EditorWorkspace(uri, WIN32_REGION, root_uri), raising=False)
    return server, published


def _initialize(server: BtrcLanguageServer, options) -> None:
    server.initialize(lsp.InitializeParams(capabilities=lsp.ClientCapabilities(), initialization_options=options))
    server.initialized(lsp.InitializedParams())


def _open(server: BtrcLanguageServer, uri: str) -> None:
    server.did_open(
        lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(uri=uri, language_id="btrc", version=1, text=WIN32_REGION)
        )
    )


def _document_messages(published, uri: str) -> list[str]:
    last = [params for params in published if params.uri == uri][-1]
    return [diagnostic.message for diagnostic in last.diagnostics]


def test_the_server_takes_the_setting_from_initialization_and_configuration(monkeypatch, tmp_path) -> None:
    uri = (tmp_path / "Main.btrc").as_uri()
    root = tmp_path.as_uri()
    server, published = _server(monkeypatch, uri, root)
    _initialize(server, {"target": "windows-x86_64"})
    _open(server, uri)
    messages = _document_messages(published, uri)
    assert len(messages) == 1 and "undefinedOnWindows" in messages[0]

    server.did_change_configuration(lsp.DidChangeConfigurationParams(settings={"btrc": {"target": "linux-x86_64"}}))
    assert _document_messages(published, uri) == []
    # A configuration for another section leaves the target alone.
    server.did_change_configuration(lsp.DidChangeConfigurationParams(settings={"other": {"target": "x"}}))
    assert server.compiler_workspace.target.setting == "linux-x86_64"
    assert [params for params in published if params.uri == root] == []

    # An invalid label: exactly one workspace diagnostic, on the root.
    server.did_change_configuration(lsp.DidChangeConfigurationParams(settings={"btrc": {"target": INVALID_LABEL}}))
    workspace_diagnostics = [params for params in published if params.uri == root]
    assert len(workspace_diagnostics) == 1
    host = _host_target()
    expected = (INVALID_MESSAGE,) if host is not None else (INVALID_MESSAGE, TargetRepository.UNKNOWN_HOST_MESSAGE)
    assert tuple(diagnostic.message for diagnostic in workspace_diagnostics[0].diagnostics) == expected
    # Re-sending the same value publishes nothing new; a valid one clears it.
    server.did_change_configuration(lsp.DidChangeConfigurationParams(settings={"btrc": {"target": INVALID_LABEL}}))
    assert len([params for params in published if params.uri == root]) == 1
    server.did_change_configuration(lsp.DidChangeConfigurationParams(settings={"btrc": {"target": "linux-x86_64"}}))
    assert [params for params in published if params.uri == root][-1].diagnostics == []


def test_a_reopened_workspace_keeps_the_setting(monkeypatch, tmp_path) -> None:
    uri = (tmp_path / "Main.btrc").as_uri()
    for _session in range(2):
        server, published = _server(monkeypatch, uri, tmp_path.as_uri())
        _initialize(server, {"target": "windows-x86_64"})
        assert server.compiler_workspace.target.setting == "windows-x86_64"
        _open(server, uri)
        messages = _document_messages(published, uri)
        assert len(messages) == 1 and "undefinedOnWindows" in messages[0]


def test_an_unknown_host_shows_its_message_once(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TargetRepository, "host", classmethod(lambda cls, system=None, machine=None: None))
    server, published = _server(monkeypatch, (tmp_path / "Main.btrc").as_uri(), tmp_path.as_uri())
    _initialize(server, None)
    server.initialized(lsp.InitializedParams())
    workspace_diagnostics = [params for params in published if params.uri == tmp_path.as_uri()]
    assert len(workspace_diagnostics) == 1
    assert [diagnostic.message for diagnostic in workspace_diagnostics[0].diagnostics] == [
        TargetRepository.UNKNOWN_HOST_MESSAGE
    ]
