"""Coverage for leaf modules: the EBNF grammar loader, the generated AST
NodeVisitor, and package-manager edge paths."""

import os

import pytest

from src.compiler.python import ebnf, pkg


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
    body = ebnf._extract_brace_block(
        '@x { -- line comment\n (* block *) "a" /regex/ }', "@x")
    assert '"a"' in body


def test_parse_grammar_no_lexical():
    with pytest.raises(ValueError):
        ebnf.parse_grammar("no lexical section here")


def test_parse_grammar_minimal():
    info = ebnf.parse_grammar(
        '@lexical { @keywords { if while } '
        '@operators { "+" "==" } @annotations { gpu } }')
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
    monkeypatch.setattr(pkg, "_resolve_git", lambda n, u, r: "/clone/root")
    d = pkg._resolve_dep("net", {"git": "https://x/n.git", "rev": "v1"}, "/m")
    assert d == {"path": "/clone/root", "git": "https://x/n.git", "rev": "v1"}


def test_resolve_dep_invalid():
    with pytest.raises(ValueError):
        pkg._resolve_dep("x", {"version": "1.0"}, "/m")


def test_resolve_git_clones(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(pkg.subprocess, "run", lambda *a, **k: calls.append(a))
    path = pkg._resolve_git("net", "https://x/n.git", "v1")
    assert os.path.isabs(path) and len(calls) == 2  # clone + checkout


def test_resolve_git_already_cloned(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    (tmp_path / "cache" / "net-v1" / ".git").mkdir(parents=True)
    called = []
    monkeypatch.setattr(pkg.subprocess, "run", lambda *a, **k: called.append(a))
    pkg._resolve_git("net", "https://x/n.git", "v1")
    assert called == []  # skipped — already present


def test_resolve_uses_lock(tmp_path):
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    (tmp_path / "btrc.lock").write_text('{"packages": {"dep": {"path": "/p"}}}')
    assert pkg.resolve(str(tmp_path / "btrc.toml")) == {"dep": {"path": "/p"}}


def test_resolve_writes_lock(tmp_path):
    (tmp_path / "sib").mkdir()
    (tmp_path / "btrc.toml").write_text(
        '[package]\nname = "x"\n[dependencies]\nsib = { path = "./sib" }\n')
    res = pkg.resolve(str(tmp_path / "btrc.toml"), refresh=True)
    assert "sib" in res and (tmp_path / "btrc.lock").exists()


def test_configure_for_no_manifest(tmp_path):
    pkg.configure_for(str(tmp_path / "x.btrc"))
    assert pkg._PACKAGES == {}


def test_configure_for_failure(tmp_path, capsys):
    (tmp_path / "btrc.toml").write_text(
        '[package]\nname = "x"\n[dependencies]\nbad = { version = "1" }\n')
    with pytest.raises(SystemExit):
        pkg.configure_for(str(tmp_path / "x.btrc"), refresh=True)
    assert "package resolution failed" in capsys.readouterr().err


def test_package_import_paths_unknown():
    pkg._PACKAGES = {}
    assert pkg.package_import_paths("unknowndep.mod") == []


def test_package_import_paths_src_layout(tmp_path):
    root = tmp_path / "mathx"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mathx.btrc").write_text("int f() { return 0; }\n")
    pkg._PACKAGES = {"mathx": {"path": str(root)}}
    paths = pkg.package_import_paths("mathx")
    assert paths and paths[0].endswith(os.path.join("src", "mathx.btrc"))


def test_package_import_paths_root_layout(tmp_path):
    root = tmp_path / "vec"
    root.mkdir()
    (root / "sub.btrc").write_text("int f() { return 0; }\n")
    pkg._PACKAGES = {"vec": {"path": str(root)}}
    paths = pkg.package_import_paths("vec.sub")
    assert paths and paths[0].endswith("sub.btrc")


def test_package_import_paths_not_found(tmp_path, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    pkg._PACKAGES = {"empty": {"path": str(root)}}
    with pytest.raises(SystemExit):
        pkg.package_import_paths("empty.missing")
    assert "not found" in capsys.readouterr().err
