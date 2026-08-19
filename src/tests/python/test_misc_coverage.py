"""Coverage for leaf modules: the EBNF grammar loader, the generated AST
NodeVisitor, and package-manager edge paths."""

import json
import os
import subprocess

import pytest

import src.compiler.python.frontend.packages as pkg
import src.compiler.python.syntax.grammar as ebnf
from src.compiler.python.frontend.packages import GitDependencyCache, IncludeResolutionError
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.syntax.tokens import TokenKind, TokenVocabulary

GIT = GitDependencyCache()
PACKAGE_RESOLVER = pkg.PackageUniverse(GIT)
GRAMMAR_PARSER = ebnf.EbnfGrammarParser()

# --------------------------------------------------------------------------
# ebnf grammar loader
# --------------------------------------------------------------------------


def test_op_to_token_name_single_unknown():
    with pytest.raises(ValueError):
        GRAMMAR_PARSER.operator_token_name("§")


def test_op_to_token_name_multi_unknown():
    with pytest.raises(ValueError):
        GRAMMAR_PARSER.operator_token_name("+§")  # multi-char with an unknown component


def test_op_to_token_name_known():
    assert GRAMMAR_PARSER.operator_token_name("+=") == "PLUS_EQ"
    assert GRAMMAR_PARSER.operator_token_name("->") == "ARROW"


def test_extract_brace_block_missing_marker():
    assert GRAMMAR_PARSER.extract_brace_block("nothing here", "@nope") is None


def test_extract_brace_block_unbalanced():
    assert GRAMMAR_PARSER.extract_brace_block("@x { unbalanced", "@x") is None


def test_extract_brace_block_with_comments_and_strings():
    body = GRAMMAR_PARSER.extract_brace_block('@x { -- line comment\n (* block *) "a" /regex/ }', "@x")
    assert '"a"' in body


def test_parse_grammar_no_lexical():
    with pytest.raises(ValueError):
        GRAMMAR_PARSER.parse("no lexical section here")


def test_parse_grammar_minimal():
    info = GRAMMAR_PARSER.parse('@lexical { @keywords { if while } @operators { "+" "==" } @annotations { gpu } }')
    assert "if" in info.keywords and "while" in info.keywords
    assert "+" in info.operators and "==" in info.operators
    assert "gpu" in info.annotations
    assert info.op_to_token["+"] == "PLUS"


def test_extract_brace_block_escapes():
    # Escaped quote inside a string and escaped slash inside a regex.
    body = GRAMMAR_PARSER.extract_brace_block(r'@x { "a\"b" /a\/b/ }', "@x")
    assert body is not None


def test_grammar_repository_loads_real_grammar_once():
    repository = ebnf.GrammarRepository.canonical()
    info = repository.load()
    assert "class" in info.keywords
    assert repository.load() is info  # cached by this explicit owner


def test_grammar_repository_does_not_publish_a_failed_snapshot(tmp_path):
    grammar_path = tmp_path / "grammar.ebnf"
    grammar_path.write_text("malformed")
    repository = ebnf.GrammarRepository(str(grammar_path))

    with pytest.raises(ValueError):
        repository.load()

    grammar_path.write_text('@lexical { @keywords { class } @operators { "+" } }')
    assert repository.load().keywords == frozenset({"class"})


def test_lexer_uses_its_explicit_immutable_vocabulary():
    grammar = GRAMMAR_PARSER.parse('@lexical { @keywords { class } @operators { "+" } @annotations { gpu } }')
    vocabulary = TokenVocabulary(grammar)

    tokens = Lexer("class + value", vocabulary=vocabulary).tokenize()

    assert [token.type for token in tokens] == [
        TokenKind.CLASS,
        TokenKind.PLUS,
        TokenKind.IDENT,
        TokenKind.EOF,
    ]
    with pytest.raises(TypeError):
        vocabulary.keywords["while"] = TokenKind.WHILE


# --------------------------------------------------------------------------
# package manager
# --------------------------------------------------------------------------


def test_resolve_dep_bare_string(tmp_path):
    d = PACKAGE_RESOLVER._resolve_dependency(
        "x",
        "../sibling",
        str(tmp_path),
    )
    assert os.path.isabs(d["path"])


def test_resolve_dep_path_dict_relative(tmp_path):
    d = PACKAGE_RESOLVER._resolve_dependency(
        "x",
        {"path": "../sib"},
        str(tmp_path),
    )
    assert d["path"].endswith("sib") and os.path.isabs(d["path"])


def test_resolve_dep_path_dict_absolute():
    d = PACKAGE_RESOLVER._resolve_dependency(
        "x",
        {"path": "/abs/path"},
        "/manifest",
    )
    assert d["path"] == "/abs/path"


def test_resolve_dep_git(monkeypatch):
    monkeypatch.setattr(
        GIT,
        "resolve",
        lambda n, u, r, refresh=False: "/clone/root",
    )
    monkeypatch.setattr(GIT, "resolved_commit", lambda _path: "a" * 40)
    d = PACKAGE_RESOLVER._resolve_dependency(
        "net",
        {"git": "https://x/n.git", "rev": "v1"},
        "/m",
    )
    assert d == {
        "commit": "a" * 40,
        "git": "https://x/n.git",
        "path": "/clone/root",
        "rev": "v1",
    }


def test_resolve_dep_invalid():
    with pytest.raises(ValueError):
        PACKAGE_RESOLVER._resolve_dependency(
            "x",
            {"version": "1.0"},
            "/m",
        )


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
    monkeypatch.setattr(pkg.subprocess, "run", _fake_git_run(calls))
    path = GIT.resolve("net", "https://x/n.git", "v1")
    assert os.path.isabs(path) and len(calls) == 3  # clone + checkout + rev-parse


def test_resolve_git_uses_pinned_ref_record(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    record = GIT._ref_record_path("net", "https://x/n.git", "v1")
    GIT._publish_ref_record(record, "net", "https://x/n.git", "v1", "a" * 40)
    observed = []

    def pinned(name, url, rev, commit):
        observed.append((name, url, rev, commit))
        return "/immutable/checkout"

    monkeypatch.setattr(GIT, "_ensure_commit_checkout", pinned)
    assert GIT.resolve("net", "https://x/n.git", "v1") == "/immutable/checkout"
    assert observed == [("net", "https://x/n.git", "v1", "a" * 40)]


def test_resolve_git_separates_url_from_options(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(pkg.subprocess, "run", _fake_git_run(calls))
    GIT.resolve("net", "--upload-pack=untrusted", "v1")
    assert calls[0][0:4] == ["git", "clone", "--quiet", "--"]
    assert calls[0][4] == "--upload-pack=untrusted"


def test_git_subprocesses_are_noninteractive_and_bounded(monkeypatch):
    observed = {}

    def run(cmd, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pkg.subprocess, "run", run)
    GIT._git(["status"])

    assert observed["check"] is True
    assert observed["timeout"] == GIT.GIT_TIMEOUT_SECONDS
    assert observed["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert observed["env"]["GCM_INTERACTIVE"] == "Never"


def test_resolve_git_rejects_option_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(pkg.subprocess, "run", _fake_git_run(calls))
    with pytest.raises(ValueError, match="invalid revision"):
        GIT.resolve("net", "https://x/n.git", "--orphan")
    assert calls == []


def test_failed_git_checkout_does_not_poison_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setenv("BTRC_PKG_CACHE", str(cache))
    monkeypatch.setattr(GIT, "_git", lambda _args: None)

    def fail_checkout(_dest, _rev):
        raise ValueError("bad revision")

    monkeypatch.setattr(GIT, "_checkout", fail_checkout)

    with pytest.raises(ValueError, match="bad revision"):
        GIT.resolve("net", "https://x/n.git", "missing")

    assert list(cache.iterdir()) == []


def test_resolve_uses_lock(tmp_path):
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    lock = {
        "manifest_hash": PACKAGE_RESOLVER.dependencies_hash({}),
        "packages": {"dep": {"path": "/p"}},
        "schema": pkg.LOCK_SCHEMA,
    }
    (tmp_path / "btrc.lock").write_text(json.dumps(lock))
    resolved = PACKAGE_RESOLVER.resolve_manifest(str(tmp_path / "btrc.toml"))
    assert resolved.entries == {"dep": {"path": "/p"}}


def test_resolve_ignores_stale_lock(tmp_path):
    # Legacy (hash-less) and out-of-date locks are re-resolved, not trusted.
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    (tmp_path / "btrc.lock").write_text('{"packages": {"dep": {"path": "/p"}}}')
    assert PACKAGE_RESOLVER.resolve_manifest(str(tmp_path / "btrc.toml")).entries == {}


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
        lock["manifest_hash"] = PACKAGE_RESOLVER.dependencies_hash({})
    (tmp_path / "btrc.lock").write_text(json.dumps(lock))
    before = (tmp_path / "btrc.lock").read_bytes()
    with pytest.raises(pkg.LockfileError):
        PACKAGE_RESOLVER.resolve_manifest(str(manifest))
    assert (tmp_path / "btrc.lock").read_bytes() == before


def test_resolve_for_invalid_dependency_shape_is_controlled(tmp_path):
    (tmp_path / "btrc.toml").write_text("dependencies = 1\n")
    with pytest.raises(IncludeResolutionError, match=r"dependencies.*table"):
        PACKAGE_RESOLVER.resolve_for(str(tmp_path / "main.btrc"))


def test_resolve_writes_lock(tmp_path):
    (tmp_path / "sib").mkdir()
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n[dependencies]\nsib = { path = "./sib" }\n')
    result = PACKAGE_RESOLVER.resolve_manifest(
        str(tmp_path / "btrc.toml"),
        refresh=True,
    )
    assert "sib" in result.entries and (tmp_path / "btrc.lock").exists()


def test_resolve_for_no_manifest(tmp_path):
    assert PACKAGE_RESOLVER.resolve_for(str(tmp_path / "x.btrc")).entries == {}


def test_resolve_for_failure(tmp_path):
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n[dependencies]\nbad = { version = "1" }\n')
    with pytest.raises(IncludeResolutionError, match="package resolution failed"):
        PACKAGE_RESOLVER.resolve_for(
            str(tmp_path / "x.btrc"),
            refresh=True,
        )


def test_resolved_packages_ignore_unknown_dependency():
    assert pkg.ResolvedPackages.empty().paths_for_import("unknowndep.mod") == ()


def test_resolved_packages_support_src_layout(tmp_path):
    root = tmp_path / "mathx"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mathx.btrc").write_text("int f() { return 0; }\n")
    packages = pkg.ResolvedPackages(None, {"mathx": {"path": str(root)}})
    paths = packages.paths_for_import("mathx")
    assert paths and paths[0].endswith(os.path.join("src", "mathx.btrc"))


def test_resolved_packages_support_root_layout(tmp_path):
    root = tmp_path / "vec"
    root.mkdir()
    (root / "sub.btrc").write_text("int f() { return 0; }\n")
    packages = pkg.ResolvedPackages(None, {"vec": {"path": str(root)}})
    paths = packages.paths_for_import("vec.sub")
    assert paths and paths[0].endswith("sub.btrc")


def test_resolved_packages_report_missing_module(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    packages = pkg.ResolvedPackages(None, {"empty": {"path": str(root)}})
    with pytest.raises(IncludeResolutionError, match="not found"):
        packages.paths_for_import("empty.missing")
