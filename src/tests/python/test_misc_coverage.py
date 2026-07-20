"""Coverage for leaf modules: the EBNF grammar loader, the generated AST
NodeVisitor, and package-manager edge paths."""

import json
import os
import subprocess

import pytest

from src.compiler.python import ebnf, pkg, pkg_git
from src.compiler.python.pkg import IncludeResolutionError

# --------------------------------------------------------------------------
# ebnf grammar loader
# --------------------------------------------------------------------------


def test_op_to_token_name_single_unknown():
    with pytest.raises(ValueError):
        ebnf._op_to_token_name("§")


def test_op_to_token_name_multi_unknown():
    with pytest.raises(ValueError):
        ebnf._op_to_token_name("+§")  # multi-char with an unknown component


def test_op_to_token_name_known():
    assert ebnf._op_to_token_name("+=") == "PLUS_EQ"
    assert ebnf._op_to_token_name("->") == "ARROW"


def test_extract_brace_block_missing_marker():
    assert ebnf._extract_brace_block("nothing here", "@nope") is None


def test_extract_brace_block_unbalanced():
    assert ebnf._extract_brace_block("@x { unbalanced", "@x") is None


def test_extract_brace_block_with_comments_and_strings():
    body = ebnf._extract_brace_block('@x { -- line comment\n (* block *) "a" /regex/ }', "@x")
    assert '"a"' in body


def test_parse_grammar_no_lexical():
    with pytest.raises(ValueError):
        ebnf.parse_grammar("no lexical section here")


def test_parse_grammar_minimal():
    info = ebnf.parse_grammar('@lexical { @keywords { if while } @operators { "+" "==" } @annotations { gpu } }')
    assert "if" in info.keywords and "while" in info.keywords
    assert "+" in info.operators and "==" in info.operators
    assert "gpu" in info.annotations
    assert info.op_to_token["+"] == "PLUS"


def test_extract_brace_block_escapes():
    # Escaped quote inside a string and escaped slash inside a regex.
    body = ebnf._extract_brace_block(r'@x { "a\"b" /a\/b/ }', "@x")
    assert body is not None


def test_get_grammar_info_loads_real_grammar():
    info = ebnf.get_grammar_info()
    assert "class" in info.keywords
    assert ebnf.get_grammar_info() is info  # cached on subsequent calls


# --------------------------------------------------------------------------
# package manager
# --------------------------------------------------------------------------


def test_resolve_dep_bare_string(tmp_path):
    d = pkg._resolve_dep("x", "../sibling", str(tmp_path))
    assert os.path.isabs(d["path"])


def test_resolve_dep_path_dict_relative(tmp_path):
    d = pkg._resolve_dep("x", {"path": "../sib"}, str(tmp_path))
    assert d["path"].endswith("sib") and os.path.isabs(d["path"])


def test_resolve_dep_path_dict_absolute():
    d = pkg._resolve_dep("x", {"path": "/abs/path"}, "/manifest")
    assert d["path"] == "/abs/path"


def test_resolve_dep_git(monkeypatch):
    monkeypatch.setattr(pkg, "_resolve_git", lambda n, u, r, refresh=False: "/clone/root")
    monkeypatch.setattr(pkg, "_resolved_git_commit", lambda _path: "a" * 40)
    d = pkg._resolve_dep("net", {"git": "https://x/n.git", "rev": "v1"}, "/m")
    assert d == {
        "commit": "a" * 40,
        "git": "https://x/n.git",
        "path": "/clone/root",
        "rev": "v1",
    }


def test_resolve_dep_invalid():
    with pytest.raises(ValueError):
        pkg._resolve_dep("x", {"version": "1.0"}, "/m")


def _fake_git_run(calls):
    """subprocess.run stand-in: records commands, reports success."""

    def run(cmd, *a, **k):
        calls.append(cmd)
        output = "a" * 40 + "\n" if "rev-parse" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, output, "")

    return run


def test_resolve_git_clones(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(pkg_git.subprocess, "run", _fake_git_run(calls))
    path = pkg._resolve_git("net", "https://x/n.git", "v1")
    assert os.path.isabs(path) and len(calls) == 3  # clone + checkout + rev-parse


def test_resolve_git_uses_pinned_ref_record(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    record = pkg_git._ref_record_path("net", "https://x/n.git", "v1")
    pkg_git._publish_ref_record(record, "net", "https://x/n.git", "v1", "a" * 40)
    observed = []

    def pinned(name, url, rev, commit):
        observed.append((name, url, rev, commit))
        return "/immutable/checkout"

    monkeypatch.setattr(pkg_git, "_ensure_commit_checkout", pinned)
    assert pkg._resolve_git("net", "https://x/n.git", "v1") == "/immutable/checkout"
    assert observed == [("net", "https://x/n.git", "v1", "a" * 40)]


def test_resolve_git_separates_url_from_options(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(pkg_git.subprocess, "run", _fake_git_run(calls))
    pkg._resolve_git("net", "--upload-pack=untrusted", "v1")
    assert calls[0][0:4] == ["git", "clone", "--quiet", "--"]
    assert calls[0][4] == "--upload-pack=untrusted"


def test_git_subprocesses_are_noninteractive_and_bounded(monkeypatch):
    observed = {}

    def run(cmd, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pkg_git.subprocess, "run", run)
    pkg_git._git(["status"])

    assert observed["check"] is True
    assert observed["timeout"] == pkg_git._GIT_TIMEOUT_SECONDS
    assert observed["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert observed["env"]["GCM_INTERACTIVE"] == "Never"


def test_resolve_git_rejects_option_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(pkg_git.subprocess, "run", _fake_git_run(calls))
    with pytest.raises(ValueError, match="invalid revision"):
        pkg._resolve_git("net", "https://x/n.git", "--orphan")
    assert calls == []


def test_failed_git_checkout_does_not_poison_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setenv("BTRC_PKG_CACHE", str(cache))
    monkeypatch.setattr(pkg_git, "_git", lambda _args: None)

    def fail_checkout(_dest, _rev):
        raise ValueError("bad revision")

    monkeypatch.setattr(pkg_git, "_checkout", fail_checkout)

    with pytest.raises(ValueError, match="bad revision"):
        pkg._resolve_git("net", "https://x/n.git", "missing")

    assert list(cache.iterdir()) == []


def test_resolve_uses_lock(tmp_path):
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    lock = {
        "manifest_hash": pkg._deps_hash({}),
        "packages": {"dep": {"path": "/p"}},
        "schema": pkg.LOCK_SCHEMA,
    }
    (tmp_path / "btrc.lock").write_text(json.dumps(lock))
    assert pkg.resolve(str(tmp_path / "btrc.toml")) == {"dep": {"path": "/p"}}


def test_resolve_ignores_stale_lock(tmp_path):
    # Legacy (hash-less) and out-of-date locks are re-resolved, not trusted.
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    (tmp_path / "btrc.lock").write_text('{"packages": {"dep": {"path": "/p"}}}')
    assert pkg.resolve(str(tmp_path / "btrc.toml")) == {}


@pytest.mark.parametrize(
    "lock",
    [
        [],
        {"packages": [], "schema": pkg.LOCK_SCHEMA},
        {"packages": {"dep": []}, "schema": pkg.LOCK_SCHEMA},
        {"packages": {"dep": {"path": 1}}, "schema": pkg.LOCK_SCHEMA},
        {
            "packages": {"dep": {"commit": "a" * 40, "git": 1, "rev": "main"}},
            "schema": pkg.LOCK_SCHEMA,
        },
        {
            "packages": {"dep": {"commit": "bad", "git": "https://x/n.git", "rev": "main"}},
            "schema": pkg.LOCK_SCHEMA,
        },
    ],
)
def test_resolve_fails_closed_on_structurally_invalid_current_lock(tmp_path, lock):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('[package]\nname = "x"\n')
    if isinstance(lock, dict):
        lock["manifest_hash"] = pkg._deps_hash({})
    (tmp_path / "btrc.lock").write_text(json.dumps(lock))
    before = (tmp_path / "btrc.lock").read_bytes()
    with pytest.raises(pkg.LockfileError):
        pkg.resolve(str(manifest))
    assert (tmp_path / "btrc.lock").read_bytes() == before


def test_configure_for_invalid_dependency_shape_is_controlled(tmp_path):
    (tmp_path / "btrc.toml").write_text("dependencies = 1\n")
    with pytest.raises(IncludeResolutionError, match=r"dependencies.*table"):
        pkg.configure_for(str(tmp_path / "main.btrc"))
    assert pkg.configured_packages() == {}


def test_resolve_writes_lock(tmp_path):
    (tmp_path / "sib").mkdir()
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n[dependencies]\nsib = { path = "./sib" }\n')
    res = pkg.resolve(str(tmp_path / "btrc.toml"), refresh=True)
    assert "sib" in res and (tmp_path / "btrc.lock").exists()


def test_configure_for_no_manifest(tmp_path):
    pkg.configure_for(str(tmp_path / "x.btrc"))
    assert pkg.configured_packages() == {}


def test_configure_for_failure(tmp_path):
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n[dependencies]\nbad = { version = "1" }\n')
    with pytest.raises(IncludeResolutionError, match="package resolution failed"):
        pkg.configure_for(str(tmp_path / "x.btrc"), refresh=True)
    assert pkg.configured_packages() == {}  # failure never leaves stale packages behind


def test_package_import_paths_unknown():
    with pkg.package_context({}):
        assert pkg.package_import_paths("unknowndep.mod") == []


def test_package_import_paths_src_layout(tmp_path):
    root = tmp_path / "mathx"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mathx.btrc").write_text("int f() { return 0; }\n")
    with pkg.package_context({"mathx": {"path": str(root)}}):
        paths = pkg.package_import_paths("mathx")
        assert paths and paths[0].endswith(os.path.join("src", "mathx.btrc"))


def test_package_import_paths_root_layout(tmp_path):
    root = tmp_path / "vec"
    root.mkdir()
    (root / "sub.btrc").write_text("int f() { return 0; }\n")
    with pkg.package_context({"vec": {"path": str(root)}}):
        paths = pkg.package_import_paths("vec.sub")
        assert paths and paths[0].endswith("sub.btrc")


def test_package_import_paths_not_found(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    with (
        pkg.package_context({"empty": {"path": str(root)}}),
        pytest.raises(IncludeResolutionError, match="not found"),
    ):
        pkg.package_import_paths("empty.missing")
