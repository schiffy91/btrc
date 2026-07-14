"""Runtime hardening: mid-edit staleness, validation races, cache bounds,
URI decoding, overlay snapshotting, diagnostic spans, and packaging hygiene."""

import importlib
import importlib.util
import os
import re
import threading
import time
from pathlib import Path

from lsprotocol import types as lsp

from src.devex.lsp import unit_cache
from src.devex.lsp import units as units_mod
from src.devex.lsp.completion import get_completions
from src.devex.lsp.diagnostics import AnalysisResult, compute_diagnostics, uri_to_path
from src.devex.lsp.signature_help import get_signature_help
from src.devex.lsp.tests.lsphelp import SAMPLE, pos_of
from src.devex.lsp.units import FileUnit
from src.devex.lsp.workspace import Workspace

srv = importlib.import_module("src.devex.lsp.server")
srv_state = importlib.import_module("src.devex.lsp.server_state")

REPO_ROOT = Path(__file__).resolve().parents[4]
URI = "file:///hardening.btrc"

SNAP = """\
class Dog { public int bones; public void bark() {} public Dog() {} }
class Cat { public int lives; public void purr(int n) {} public Cat() {} }
int main() {
    Dog d = Dog();
    Cat c = Cat();
    d.bark();
    return 0;
}
"""


def _swapped(live: str, uri: str = URI) -> AnalysisResult:
    """Mirror server_state._result_with_current_source's snapshot swap."""
    s = compute_diagnostics(uri, SNAP)
    assert s.diagnostics == [] and s.analyzed is not None
    return AnalysisResult(
        uri=s.uri,
        source=live,
        diagnostics=s.diagnostics,
        tokens=s.tokens,
        ast=s.ast,
        analyzed=s.analyzed,
        source_positions=s.source_positions,
        path=s.path,
        units=s.units,
        snapshot_source=s.source,
        _caches=s._caches,
    )


class _Doc:
    def __init__(self, source):
        self.source = source


class _Workspace:
    def __init__(self, source, uri=URI):
        self.text_documents = {uri: _Doc(source)} if source is not None else {}
        self._source = source

    def get_text_document(self, uri):
        return _Doc(self._source) if self._source is not None else None


def _install(monkeypatch, source, uri=URI):
    published = []
    monkeypatch.setattr(
        srv.server, "text_document_publish_diagnostics", lambda params: published.append(params), raising=False
    )
    monkeypatch.setattr(srv.server.protocol, "_workspace", _Workspace(source, uri), raising=False)
    monkeypatch.setattr(srv, "DEBOUNCE_SECONDS", 0)
    return published


# --------------------------------------------------------------------------- #
# 1. mid-edit staleness: the snapshot's tokens must not name the receiver
# --------------------------------------------------------------------------- #


def test_midedit_completion_does_not_use_stale_receiver():
    live = SNAP.replace("    d.bark();\n", "    c.\n")
    labels = {i.label for i in get_completions(_swapped(live), lsp.Position(line=5, character=6))}
    assert "purr" in labels and "lives" in labels
    assert "bark" not in labels and "bones" not in labels


def test_midedit_signature_help_does_not_use_stale_callee():
    live = SNAP.replace("    d.bark();\n", "    c.purr(\n")
    sig = get_signature_help(_swapped(live), lsp.Position(line=5, character=11))
    assert sig is not None and "purr" in sig.signatures[0].label


def test_midedit_unchanged_lines_still_use_token_path():
    # source swapped, but the queried line is identical -> token path intact
    live = SNAP + "\n"
    labels = {i.label for i in get_completions(_swapped(live), pos_of(SNAP, "d.bark", offset=2))}
    assert "bark" in labels


def test_server_swaps_live_buffer_and_resolves_new_receiver(monkeypatch):
    _install(monkeypatch, SNAP.replace("    d.bark();\n", "    c.\n"))
    srv._validate_document(URI, SNAP)  # snapshot analyzed from the OLD text
    items = srv.completion(
        lsp.CompletionParams(
            text_document=lsp.TextDocumentIdentifier(uri=URI), position=lsp.Position(line=5, character=6)
        )
    )
    labels = {i.label for i in items}
    assert "purr" in labels and "bark" not in labels


# --------------------------------------------------------------------------- #
# 2. feature-request pipeline fallback: locked + caches consistently
# --------------------------------------------------------------------------- #


def test_uncached_feature_compute_populates_both_caches(monkeypatch):
    _install(monkeypatch, SAMPLE)
    srv._analysis_cache.pop(URI, None)
    srv._good_analysis_cache.pop(URI, None)
    result = srv_state._result_with_current_source(URI)
    assert result is not None
    assert URI in srv._analysis_cache
    assert URI in srv._good_analysis_cache  # good analysis recorded too


def test_uncached_feature_compute_serializes_with_validation(monkeypatch):
    _install(monkeypatch, SAMPLE)
    srv._analysis_cache.pop(URI, None)
    done = threading.Event()

    def compute():
        srv_state._compute_uncached(URI, SAMPLE)
        done.set()

    with srv_state._validate_lock:  # a validation is "running"
        t = threading.Thread(target=compute, daemon=True)
        t.start()
        assert not done.wait(0.15)  # blocked behind the pipeline lock
    assert done.wait(5)  # released -> completes


# --------------------------------------------------------------------------- #
# 3. stale publishes are dropped; closed documents stay closed
# --------------------------------------------------------------------------- #


def test_stale_generation_does_not_cache_or_publish(monkeypatch):
    published = _install(monkeypatch, SAMPLE)
    srv._validate_document(URI, SAMPLE)
    stale_gen = srv_state._generations[URI]
    newer = "int main() { return 1; }\n"
    srv._validate_document(URI, newer)  # claims a newer generation
    published.clear()
    srv._validate_document(URI, SAMPLE, generation=stale_gen)  # stale run lands last
    assert published == []  # dropped, newer diagnostics not overwritten
    assert srv._analysis_cache[URI].source == newer


def test_validation_after_did_close_is_dropped(monkeypatch):
    published = _install(monkeypatch, SAMPLE)
    srv._validate_document(URI, SAMPLE)
    gen = srv_state._generations[URI]
    srv.did_close(lsp.DidCloseTextDocumentParams(text_document=lsp.TextDocumentIdentifier(uri=URI)))
    assert URI not in srv._analysis_cache
    published.clear()
    # A run that passed its pre-check before the close finishes now: dropped.
    srv._validate_document(URI, SAMPLE, generation=gen)
    assert published == []
    assert URI not in srv._analysis_cache
    assert URI not in srv._good_analysis_cache
    # An explicit reopen (didOpen-style direct call) works again.
    srv._validate_document(URI, SAMPLE)
    assert URI in srv._analysis_cache


# --------------------------------------------------------------------------- #
# 4. stdlib units build once, atomically
# --------------------------------------------------------------------------- #


def test_stdlib_units_concurrent_first_build_is_single_and_none_free():
    w = Workspace()
    results = []

    def grab():
        results.append(w.stdlib_units())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8
    first = results[0]
    assert all(r is first for r in results)  # one build, shared list
    assert first and all(u is not None for u in first)  # no None placeholders


# --------------------------------------------------------------------------- #
# 5. cache bounds and freshness
# --------------------------------------------------------------------------- #


def test_stdlib_base_cache_is_lru_capped():
    w = Workspace()
    for i in range(6):
        unit = FileUnit(path=f"/fake/stdlib{i}.btrc", source="", content_hash=str(i))
        assert w._stdlib_base([unit]) is not None
    assert len(w._stdlib_base_cache) == w._STDLIB_BASE_CACHE_MAX
    kept = {next(iter(k)) for k in w._stdlib_base_cache}
    assert kept == {f"/fake/stdlib{i}.btrc" for i in (2, 3, 4, 5)}  # oldest evicted


def test_unit_cache_version_is_content_derived():
    v = units_mod._UNIT_CACHE_VERSION
    assert re.fullmatch(r"[0-9a-f]{16}", v), v  # a hash, not a hand-bumped counter
    assert units_mod._compute_unit_cache_version() == v  # deterministic
    assert v != units_mod.toolchain_hash("frontend")  # LSP codec/extraction included


def test_prune_unit_cache_removes_legacy_pickles_and_only_expired_json(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    legacy = cache / "lspunit-legacy.pkl"
    old = cache / "lspunit-old.json"
    new = cache / "lspunit-new.json"
    other = cache / "unrelated.txt"
    for f in (legacy, old, new, other):
        f.write_bytes(b"x")
    stale = time.time() - 40 * 24 * 3600
    os.utime(old, (stale, stale))
    os.utime(other, (stale, stale))
    unit_cache.prune_unit_cache(str(cache))
    assert not legacy.exists()  # unsafe legacy format is invalidated immediately
    assert not old.exists()
    assert new.exists()
    assert other.exists()


# --------------------------------------------------------------------------- #
# 6. URI decoding
# --------------------------------------------------------------------------- #


def test_uri_to_path_posix_behavior_unchanged():
    assert uri_to_path("file:///tmp/t.btrc") == "/tmp/t.btrc"
    assert uri_to_path("file:///tmp/a%20b.btrc") == "/tmp/a b.btrc"


def test_uri_to_path_windows_drive_loses_leading_slash():
    path = uri_to_path("file:///C:/Users/a%20b/x.btrc")
    assert not path.startswith("/")
    assert path.replace("\\", "/") == "C:/Users/a b/x.btrc"


def test_uri_to_path_preserves_unc_authority_and_virtual_uri_identity():
    assert uri_to_path("file://server/share/a%20b.btrc").replace("\\", "/") == "//server/share/a b.btrc"
    left = uri_to_path("untitled:one.btrc")
    right = uri_to_path("untitled:two.btrc")
    assert left != right and left.endswith(".btrc") and right.endswith(".btrc")


def test_older_document_version_cannot_overwrite_newer_analysis(monkeypatch):
    published = _install(monkeypatch, "int main() { return 2; }\n")
    newer = "int main() { return 2; }\n"
    older = "int main() { return 1; }\n"

    srv._schedule_validation(URI, newer, 0, version=2)
    published.clear()
    srv._schedule_validation(URI, older, 0, version=1)

    assert srv._analysis_cache[URI].source == newer
    assert published == []


# --------------------------------------------------------------------------- #
# 7. overlay provider reads a snapshot of open documents
# --------------------------------------------------------------------------- #


def test_overlay_provider_serves_open_buffer(monkeypatch):
    _install(monkeypatch, "class Overlay {}\n", uri="file:///ov.btrc")
    target = os.path.abspath(uri_to_path("file:///ov.btrc"))
    assert srv_state._overlay_provider(target) == "class Overlay {}\n"
    assert srv_state._overlay_provider("/no/such/file.btrc") is None


# --------------------------------------------------------------------------- #
# 8. diagnostic spans widen to the offending token
# --------------------------------------------------------------------------- #


def test_analyzer_diagnostic_covers_full_token():
    src = "int main() { string s = 42; return 0; }\n"
    r = compute_diagnostics("file:///span.btrc", src)
    d = next(d for d in r.diagnostics if "Cannot assign" in d.message)
    line = src.split("\n")[d.range.start.line]
    assert line[d.range.start.character : d.range.end.character] == "string"


def test_lexer_diagnostic_without_tokens_stays_one_char():
    r = compute_diagnostics("file:///span2.btrc", 'int main() { string s = "x; }\n')
    d = r.diagnostics[0]
    assert d.range.end.character == d.range.start.character + 1


# --------------------------------------------------------------------------- #
# 10b. packaging hygiene
# --------------------------------------------------------------------------- #

_PREPARE = REPO_ROOT / "src" / "devex" / "ext" / "scripts" / "prepare_lsp_package.py"


def _load_prepare():
    spec = importlib.util.spec_from_file_location("prepare_lsp_package", _PREPARE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prepare_lsp_package_excludes_local_state_and_artifacts(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "compiler" / "python").mkdir(parents=True)
    (repo / "src" / "compiler" / "python" / "main.py").write_text("# compiler\n")
    (repo / "src" / "stdlib" / "gui" / "build").mkdir(parents=True)
    (repo / "src" / "stdlib" / "gui" / "build" / "libbtrc_gui.a").write_bytes(b"ar")
    (repo / "src" / "stdlib" / "core.btrc").write_text("class Core {}\n")
    (repo / "src" / "language").mkdir(parents=True)
    (repo / "src" / "language" / "grammar.ebnf").write_text("@keywords\n")
    lsp_dir = repo / "src" / "devex" / "lsp"
    (lsp_dir / ".venv" / "bin").mkdir(parents=True)
    (lsp_dir / ".venv" / "bin" / "python3").write_text("")
    (lsp_dir / ".btrc-cache").mkdir()
    (lsp_dir / ".btrc-cache" / "lspunit-x.pkl").write_bytes(b"p")
    (lsp_dir / "server.py").write_text("# server\n")
    (lsp_dir / "old.vsix").write_bytes(b"z")

    bundle = _load_prepare().prepare(ext_dir=tmp_path / "ext", repo_root=repo)

    assert (bundle / "src" / "compiler" / "python" / "main.py").exists()
    assert (bundle / "src" / "devex" / "lsp" / "server.py").exists()
    assert not (bundle / "src" / "stdlib" / "gui" / "build").exists()
    assert not (bundle / "src" / "devex" / "lsp" / ".venv").exists()
    assert not (bundle / "src" / "devex" / "lsp" / ".btrc-cache").exists()
    assert not list(bundle.rglob("*.a"))
    assert not list(bundle.rglob("*.vsix"))


def test_bundle_flake_python_matches_repo_lsp_python():
    script = _PREPARE.read_text()
    bundle_py = re.search(r"pkgs\.(python\d+)\.withPackages \(ps: \[ ps\.pygls", script)
    assert bundle_py, "bundle flake no longer pins a python version"
    repo_flake = (REPO_ROOT / "flake.nix").read_text()
    repo_py = re.search(r"lspPython = pkgs\.(python\d+)\.withPackages", repo_flake)
    assert repo_py, "repo flake no longer defines lspPython"
    assert bundle_py.group(1) == repo_py.group(1)
