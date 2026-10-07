"""Realtime plain-data payload rules rechecked at every generic specialization.

A template such as ``class Mailbox<T> { OwnedBuffer<T> storage; }`` cannot
check its payload where it is declared, because ``T`` is not yet a type. Both
compilers recheck the rule under each specialization's arguments -- direct,
nested, transitive, through generic methods and through typedef aliases -- and
refuse a managed payload with one identical first diagnostic that names the
instantiation site and the offending argument. Plain-data arguments still
compile and run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.selfhost_snippet_harness import compile_reference_source, compile_source, strict_build_and_run

PRELUDE = """import Library.OwnedBuffer;
import Library.SPSC;
import Library.Vector;

class ProbeView {
    public int id;

    public ProbeView(int id) {
        self.id = id;
    }
}

struct PodPoint {
    int x;
    float y;
};

typedef string Name;

class UIWorkMailbox<T> {
    private OwnedBuffer<T> storage;

    public UIWorkMailbox(size_t capacity) {
        self.storage = new OwnedBuffer<T>(capacity);
    }

    public bool tryPublish(T payload) {
        return self.storage.set((size_t)0, payload);
    }
}
"""

OWNED = "OwnedBuffer<T> payload '{}' must be realtime POD without managed or atomic ownership"

REFUSED = (
    (
        "string",
        "int main() {\n    var mailbox = new UIWorkMailbox<string>((size_t)2);\n    return 0;\n}\n",
        "Generic specialization 'UIWorkMailbox<string>' is invalid: " + OWNED.format("string"),
        (33, 23),
    ),
    (
        "class",
        "int main() {\n    var mailbox = new UIWorkMailbox<ProbeView>((size_t)1);\n    return 0;\n}\n",
        "Generic specialization 'UIWorkMailbox<ProbeView>' is invalid: " + OWNED.format("ProbeView"),
        (33, 23),
    ),
    (
        "typedef-alias",
        "int main() {\n    var mailbox = new UIWorkMailbox<Name>((size_t)1);\n    return 0;\n}\n",
        "Generic specialization 'UIWorkMailbox<Name>' is invalid: " + OWNED.format("Name"),
        (33, 23),
    ),
    (
        "declared-type",
        "int main() {\n    UIWorkMailbox<string> mailbox = new UIWorkMailbox<string>((size_t)2);\n    return 0;\n}\n",
        "Generic specialization 'UIWorkMailbox<string>' is invalid: " + OWNED.format("string"),
        (33, 5),
    ),
    (
        "nested",
        "class Outer<U> {\n"
        "    private UIWorkMailbox<U> inner;\n\n"
        "    public Outer() {\n"
        "        self.inner = new UIWorkMailbox<U>((size_t)1);\n"
        "    }\n"
        "}\n\n"
        "int main() {\n    var outer = new Outer<string>();\n    return 0;\n}\n",
        "Generic specialization 'Outer<string>' is invalid: " + OWNED.format("string"),
        (41, 21),
    ),
    (
        "body-local",
        "class Scratch<U> {\n"
        "    public int fill(U value) {\n"
        "        OwnedBuffer<U> local = new OwnedBuffer<U>((size_t)1);\n"
        "        local.set((size_t)0, value);\n"
        "        return 0;\n"
        "    }\n"
        "}\n\n"
        'int main() {\n    var scratch = new Scratch<string>();\n    return scratch.fill("x");\n}\n',
        "Generic specialization 'Scratch<string>' is invalid: " + OWNED.format("string"),
        (41, 23),
    ),
    (
        "generic-method",
        "class Host {\n"
        "    public int fill<U>(U value) {\n"
        "        OwnedBuffer<U> local = new OwnedBuffer<U>((size_t)1);\n"
        "        local.set((size_t)0, value);\n"
        "        return 0;\n"
        "    }\n"
        "}\n\n"
        'int main() {\n    var host = new Host();\n    host.fill(3);\n    return host.fill("x");\n}\n',
        "Generic specialization 'Host.fill<string>' is invalid: " + OWNED.format("string"),
        (43, 12),
    ),
    (
        "generic-method-of-generic-class",
        "class Relay<V> {\n"
        "    public int send<U>(U value) {\n"
        "        SPSCQueue<U> queue = new SPSCQueue<U>((size_t)2);\n"
        "        return 0;\n"
        "    }\n"
        "}\n\n"
        "int main() {\n    var relay = new Relay<int>();\n    return relay.send(new ProbeView(1));\n}\n",
        "Generic specialization 'Relay<int>.send<ProbeView>' is invalid: "
        "SPSCQueue<T> payload 'ProbeView' must be realtime POD without managed ownership",
        (41, 12),
    ),
    (
        "nested-argument",
        "class Shelf<U> {\n"
        "    private Vector<UIWorkMailbox<U>> boxes = [];\n"
        "}\n\n"
        "int main() {\n    var shelf = new Shelf<string>();\n    return 0;\n}\n",
        "Generic specialization 'Shelf<string>' is invalid: " + OWNED.format("string"),
        (37, 21),
    ),
    (
        "atomic",
        "class Cell<U> {\n"
        "    private Atomic<U> value;\n\n"
        "    public Cell(U value) {\n"
        "        self.value.init(value);\n"
        "    }\n"
        "}\n\n"
        'int main() {\n    var cell = new Cell<string>("x");\n    return 0;\n}\n',
        "Generic specialization 'Cell<string>' is invalid: "
        "Atomic<T> payload 'string' must be bool, int, uint, or a raw pointer",
        (41, 20),
    ),
)


@pytest.mark.parametrize(("source", "message", "position"), [case[1:] for case in REFUSED], ids=[c[0] for c in REFUSED])
def test_managed_specialization_payloads_are_refused_identically(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    message: str,
    position: tuple[int, int],
) -> None:
    program = PRELUDE + "\n" + source
    reference, _reference_c = compile_reference_source(tmp_path, program)
    selfhost, _selfhost_c = compile_source(semantic_btrcc, tmp_path, program)

    assert reference.returncode == 1, reference.stderr
    assert selfhost.returncode == 1, selfhost.stderr
    assert diagnostic_identity(reference.stderr) == (message, *position)
    assert diagnostic_identity(selfhost.stderr) == (message, *position)


def test_plain_data_specializations_still_compile_and_run(semantic_btrcc: Path, tmp_path: Path) -> None:
    program = PRELUDE + (
        "\n"
        "class Relay<V> {\n"
        "    public bool send<U>(U value) {\n"
        "        SPSCQueue<U> queue = new SPSCQueue<U>((size_t)2);\n"
        "        return queue.tryPush(value);\n"
        "    }\n"
        "}\n\n"
        "class Shelf<U> {\n"
        "    public Vector<UIWorkMailbox<U>> boxes = [];\n"
        "}\n\n"
        "int main() {\n"
        "    var ints = new UIWorkMailbox<int>((size_t)2);\n"
        "    var floats = new UIWorkMailbox<float>((size_t)2);\n"
        "    var points = new UIWorkMailbox<PodPoint>((size_t)2);\n"
        "    var flags = new UIWorkMailbox<bool>((size_t)2);\n"
        "    var relay = new Relay<string>();\n"
        "    var shelf = new Shelf<int>();\n"
        "    shelf.boxes.push(new UIWorkMailbox<int>((size_t)1));\n"
        "    PodPoint point = {1, 2.0f};\n"
        "    if (!ints.tryPublish(7) || !floats.tryPublish(1.5f) || !points.tryPublish(point) || !flags.tryPublish(true)) {\n"
        "        return 1;\n"
        "    }\n"
        "    if (!relay.send(3) || !relay.send(point) || shelf.boxes.len != 1) {\n"
        "        return 2;\n"
        "    }\n"
        "    return 0;\n"
        "}\n"
    )
    reference, reference_c = compile_reference_source(tmp_path, program)
    selfhost, selfhost_c = compile_source(semantic_btrcc, tmp_path, program)
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    strict_build_and_run(reference_c, tmp_path / "reference")
    strict_build_and_run(selfhost_c, tmp_path / "selfhost")


def test_template_own_payloads_are_not_rechecked_per_specialization(semantic_btrcc: Path, tmp_path: Path) -> None:
    """A payload no type argument reaches is the template's own error, reported once where it is declared."""
    program = PRELUDE + (
        "\nclass Fixed<T> {\n"
        "    public SPSCQueue<string> queue;\n\n"
        "    public Fixed() {\n"
        "        self.queue = new SPSCQueue<string>((size_t)2);\n"
        "    }\n"
        "}\n\n"
        "int main() {\n    var fixed = new Fixed<int>();\n    return 0;\n}\n"
    )
    reference, _reference_c = compile_reference_source(tmp_path, program)
    selfhost, _selfhost_c = compile_source(semantic_btrcc, tmp_path, program)
    rule = "SPSCQueue<T> payload must be realtime POD without managed ownership"
    for result in (reference, selfhost):
        assert result.returncode == 1, result.stderr
        assert "Generic specialization" not in result.stderr
        assert diagnostic_identity(result.stderr) == (rule, 33, 12)
