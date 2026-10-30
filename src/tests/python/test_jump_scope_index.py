"""Jump indexing must retain lexical regions without mixing callable scopes."""

import pytest

from src.compiler.python.analyzer.flow import JumpScopeIndex
from src.compiler.python.syntax.ast.generated import (
    Block,
    BoolLiteral,
    CaseClause,
    CForStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    ExprStmt,
    ForInStmt,
    GotoStmt,
    IfStmt,
    IntLiteral,
    LabelStmt,
    LambdaBlock,
    LambdaExpr,
    ParallelForStmt,
    SwitchStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)


def _block(*statements):
    return Block(statements=list(statements))


def _lambda(*statements):
    return LambdaExpr(body=LambdaBlock(body=_block(*statements)))


def test_target_identity_duplicate_first_and_undefined():
    first = LabelStmt(name="again")
    duplicate = LabelStmt(name="again")
    back = GotoStmt(name="again")
    missing = GotoStmt(name="missing")
    root = _block(first, back, duplicate, missing)
    index = JumpScopeIndex.build(root)
    assert index.target(back).node is first
    assert index.is_backward(back)
    assert index.target(missing) is None
    assert not index.is_backward(missing)
    assert index.left_lists(missing) == index.entered_lists(missing) == ()
    assert index.entered_declarations(missing) == []
    assert index.targeted_names == {"again", "missing"}
    assert not index.targeted("unused")
    assert index.targeted("again")
    assert len(index.sites) == 4  # All nodes deliberately share default source positions.
    assert index.sites[id(duplicate)].ordinal == 2
    assert index.enclosing(back) == (index.lists[id(root)], 1, 0)


def test_outward_jump_leaves_innermost_list_first():
    jump = GotoStmt(name="out")
    inner = _block(jump)
    loop_body = _block(inner)
    root = _block(WhileStmt(condition=BoolLiteral(value=True), body=loop_body), LabelStmt(name="out"))
    index = JumpScopeIndex.build(root)
    assert [scope.node for scope in index.left_lists(jump)] == [inner, loop_body]
    assert index.entered_lists(jump) == ()
    assert index.enclosing(jump) == (index.lists[id(root)], 0, 1)
    assert index.lists[id(inner)].parent is index.lists[id(loop_body)]
    assert index.lists[id(loop_body)].parent_index == 0


def test_sibling_jump_records_both_paths_without_claiming_enclosure():
    jump = GotoStmt(name="other")
    left, right = _block(jump), _block(LabelStmt(name="other"))
    root = _block(IfStmt(condition=BoolLiteral(value=True), then_block=left, else_block=ElseBlock(body=right)))
    index = JumpScopeIndex.build(root)
    assert [scope.kind for scope in index.left_lists(jump)] == ["if"]
    assert [scope.kind for scope in index.entered_lists(jump)] == ["else"]
    assert index.enclosing(jump) is None
    assert index.entered_declarations(jump) == []


@pytest.mark.parametrize(
    "kind",
    ["block", "if", "else", "else-if", "while", "do", "for", "for-in", "parallel", "case", "try", "catch", "finally"],
)
def test_nested_region_is_never_an_enclosing_target(kind):
    jump, label = GotoStmt(name="inside"), LabelStmt(name="inside")
    body = _block(label)
    truth = BoolLiteral(value=True)
    expected = kind
    if kind == "block":
        statement = body
    elif kind == "if":
        statement = IfStmt(condition=truth, then_block=body)
    elif kind == "else":
        statement = IfStmt(condition=truth, then_block=_block(), else_block=ElseBlock(body=body))
    elif kind == "else-if":
        statement = IfStmt(
            condition=truth, then_block=_block(), else_block=ElseIf(if_stmt=IfStmt(condition=truth, then_block=body))
        )
        expected = "if"
    elif kind == "while":
        statement = WhileStmt(condition=truth, body=body)
        expected = "loop"
    elif kind == "do":
        statement = DoWhileStmt(condition=truth, body=body)
        expected = "loop"
    elif kind == "for":
        statement = CForStmt(body=body)
        expected = "loop"
    elif kind == "for-in":
        statement = ForInStmt(var_name="i", iterable=IntLiteral(value=0), body=body)
        expected = "loop"
    elif kind == "parallel":
        statement = ParallelForStmt(var_name="i", iterable=IntLiteral(value=0), body=body)
    elif kind == "case":
        statement = SwitchStmt(value=IntLiteral(value=0), cases=[CaseClause(body=[label])])
    else:
        statement = TryCatchStmt(try_block=_block())
        setattr(statement, kind + "_block", body)
    root = _block(jump, statement)
    index = JumpScopeIndex.build(root)
    assert index.target(jump).node is label
    assert index.enclosing(jump) is None
    assert index.left_lists(jump) == ()
    assert [scope.kind for scope in index.entered_lists(jump)] == [expected]


def test_forward_declarations_include_only_direct_and_spliced_finally_declarations():
    jump = GotoStmt(name="done")
    direct, final, recursive = [VarDeclStmt(name=name) for name in ("direct", "final", "recursive")]
    skipped_nested = _block(VarDeclStmt(name="nested"))
    try_stmt = TryCatchStmt(
        try_block=_block(VarDeclStmt(name="insideTry")),
        catch_block=_block(VarDeclStmt(name="insideCatch")),
        finally_block=_block(final, skipped_nested, TryCatchStmt(try_block=_block(), finally_block=_block(recursive))),
    )
    root = _block(jump, direct, skipped_nested, try_stmt, LabelStmt(name="done"), VarDeclStmt(name="after"))
    index = JumpScopeIndex.build(root)
    assert index.entered_declarations(jump) == [direct, final, recursive]
    root.statements.reverse()
    rebuilt = JumpScopeIndex.build(root)
    assert rebuilt.entered_declarations(jump) == []
    assert rebuilt.is_backward(jump)


def test_lambda_labels_and_gotos_do_not_leak_into_outer_scope():
    inner = LabelStmt(name="inner")
    nested = LabelStmt(name="inner")
    callback = _lambda(ExprStmt(expr=_lambda(nested)), inner, GotoStmt(name="outer"))
    outer = LabelStmt(name="outer")
    root = _block(ExprStmt(expr=callback), outer, GotoStmt(name="inner"))
    index = JumpScopeIndex.build(root)
    assert set(index.labels) == {"outer"}
    assert index.targeted_names == {"inner"}
    assert index.nested_lambda_label("inner") is nested
    assert index.nested_lambda_label("absent") is None
    assert len(index.sites) == 2
    inner_index = JumpScopeIndex.build(callback.body.body)
    assert inner_index.labels["inner"].node is inner
    assert inner_index.targeted_names == {"outer"}
    assert inner_index.nested_lambda_label("inner") is nested


def test_reachable_suffix_follows_multiple_back_edges_but_not_nested_lambda_jumps():
    declaration = VarDeclStmt(name="value")
    early, middle, end = [LabelStmt(name=name) for name in ("early", "middle", "end")]
    root = _block(
        LabelStmt(name="before"),
        declaration,
        early,
        GotoStmt(name="before"),
        middle,
        _block(GotoStmt(name="early")),
        end,
        _block(GotoStmt(name="middle")),
        ExprStmt(expr=_lambda(GotoStmt(name="before"))),
    )
    index = JumpScopeIndex.build(root)
    scope = index.lists[id(root)]
    assert index.reach_start(scope, 1, 6) == 2
    assert index.reach_start(scope, 4, 6) == 6
    root.statements[7] = ExprStmt(expr=_lambda(GotoStmt(name="middle")))
    index = JumpScopeIndex.build(root)
    assert index.reach_start(index.lists[id(root)], 1, 6) == 6


def test_jump_ast_round_trip_keeps_identifier_positions():
    from src.compiler.python.syntax.ast.codec import AstCanonicalRenderer, AstJsonCodec

    jump = GotoStmt(name="done", line=2, col=3, name_line=2, name_col=8)
    label = LabelStmt(name="done", line=7, col=4)
    tree = _block(jump, label)
    codec = AstJsonCodec()
    restored = codec.decode(codec.encode(tree))
    assert AstCanonicalRenderer().render(restored) == AstCanonicalRenderer().render(tree)
    assert restored.statements[0].name_line == 2 and restored.statements[0].name_col == 8
    assert restored.statements[1].line == 7 and restored.statements[1].col == 4
    position_free = AstCanonicalRenderer.position_free_renderer().render(tree)
    assert "name_line" not in position_free and "name_col" not in position_free
    assert AstCanonicalRenderer.position_free_renderer().render(jump) == '(GotoStmt\n  name="done")'


def test_nested_lambda_preorder_visits_for_initializer_before_body():
    from src.compiler.python.syntax.ast.generated import ForInitExpr

    first, later = LabelStmt(name="inside"), LabelStmt(name="inside")
    root = _block(CForStmt(init=ForInitExpr(expression=_lambda(first)), body=_block(ExprStmt(expr=_lambda(later)))))
    assert JumpScopeIndex.build(root).nested_lambda_label("inside") is first
