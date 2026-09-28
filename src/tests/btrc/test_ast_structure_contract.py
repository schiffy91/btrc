"""The self-hosted structural AST walk visits every Node-valued field."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NODE = ROOT / "src/compiler/btrc/generated/ast/Node.btrc"
IDENTITY = ROOT / "src/compiler/btrc/syntax/Identity.btrc"


def test_structural_walk_lists_every_node_field_in_declaration_order():
    # A lazy list field is declared as nullable storage and walked through an
    # accessor named for the field, so the suffix comes off before comparing.
    declared = re.findall(r"public (?:Node\??|Vector<Node>\??) ([a-zA-Z_]+);", NODE.read_text())
    fields = [re.sub(r"Storage$", "", name) for name in declared]
    source = IDENTITY.read_text()
    body = source[source.index("class void children(Node node, Vector<Node> out) {") :]
    body = body[: body.index("\n\t}")]
    walked = re.findall(r"node\.([a-zA-Z_]+)", body)
    # Each single child is named twice (null check, push); a list once.
    assert list(dict.fromkeys(walked)) == fields
