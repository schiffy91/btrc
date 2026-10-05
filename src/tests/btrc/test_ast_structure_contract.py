"""The self-hosted structural AST walk visits every Node-valued field."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NODE = ROOT / "src/compiler/btrc/generated/ast/Node.btrc"
IDENTITY = ROOT / "src/compiler/btrc/syntax/Identity.btrc"


def test_structural_walk_lists_every_node_field_in_declaration_order():
    # A lazy list field is declared, and walked, as nullable storage named for
    # the field, so the suffix comes off both sides before comparing.
    declared = re.findall(r"public (?:Node\??|Vector<Node>\??) ([a-zA-Z_]+);", NODE.read_text())
    fields = [re.sub(r"Storage$", "", name) for name in declared]
    source = IDENTITY.read_text()
    body = source[source.index("class void children(Node node, Vector<Node> out) {") :]
    body = body[: body.index("\n\t}")]
    walked = [re.sub(r"Storage$", "", name) for name in re.findall(r"node\.([a-zA-Z_]+)", body)]
    # Each single child is named twice (null check, push); a list once.
    assert list(dict.fromkeys(walked)) == fields


SELFHOST = ROOT / "src/compiler/btrc"
_METHOD_HEAD = re.compile(r"^\t(?:class|public|private) [^\n]*\{", re.MULTILINE)


def _handwritten_methods():
    """Each handwritten btrc method body, with the file it belongs to."""
    for path in sorted(SELFHOST.rglob("*.btrc")):
        if "generated" in path.relative_to(SELFHOST).parts:
            continue
        source = path.read_text()
        heads = [match.start() for match in _METHOD_HEAD.finditer(source)]
        for index, start in enumerate(heads):
            end = heads[index + 1] if index + 1 < len(heads) else len(source)
            yield path.relative_to(ROOT), source[start:end]


def test_type_expr_copies_carry_inner_extents_and_outer_pointers():
    # C2/r17 (docs/design/c-compatibility.md, "Copies"): `elements` holds a
    # TypeExpr's inner array extents and travels with `arraySize`, copied only
    # when written; `arrayPointerDepth` is copied like `pointerDepth`.
    array_copy = re.compile(r"(\w+)\.arraySize = (\w+)\.arraySize;")
    whole_copy = re.compile(r"(\w+)\.nullableOuterDepth = (\w+)\.nullableOuterDepth;")
    problems = []
    copies = 0
    for path, body in _handwritten_methods():
        for match in array_copy.finditer(body):
            copies += 1
            target, source = match.groups()
            guarded = f"if ({source}.elementsStorage != null)"
            following = body[match.end() :].lstrip()
            if not following.startswith(guarded) or f"{target}.elementsStorage = " not in body:
                problems.append(f"{path}: {match.group(0)} without a guarded copy of {source}'s inner extents")
        for match in whole_copy.finditer(body):
            target, source = match.groups()
            if f"{target}.isVolatile = {source}.isVolatile;" not in body:
                continue
            copies += 1
            if f"{target}.arrayPointerDepth = {source}.arrayPointerDepth;" not in body:
                problems.append(f"{path}: TypeExpr copy into '{target}' drops arrayPointerDepth")
        # A reader's answer may be the shared empty list, which no field holds.
        problems.extend(
            f"{path}: stores a reader's list: {stored.group(0)}"
            for stored in re.finditer(r"\w+\.elementsStorage = \w+\.elements\(\)", body)
        )
    assert copies >= 4
    assert problems == []


def test_type_identity_refuses_inner_extents_and_outer_array_pointers():
    # Module units replay encodable types by their encoding, which carries no
    # extents: `int m[][3]` must never come back as `int[]`.
    source = IDENTITY.read_text()
    body = source[source.index("class bool encodable(Node typeExpr) {") :]
    body = body[: body.index("\n\t}")]
    assert "typeExpr.elementsStorage" in body
    assert "typeExpr.arrayPointerDepth != 0" in body
