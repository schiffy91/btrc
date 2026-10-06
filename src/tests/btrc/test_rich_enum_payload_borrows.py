"""Rich-enum managed payloads are lexical borrows (CL-REQ-UI2-B, CL-REQ-UI2-C).

A rich-enum value never retains its payloads, so an enum that carries a
string, class, interface or collection is nonescaping, like Span<T>: it may be
a direct local or a parameter, and every flow that could make it outlive a
payload owner is refused with the same first diagnostic by both compilers.
The allowed flows run clean under ASan and UBSan (and LeakSanitizer where the
platform has it) through both compilers.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
    sanitizer_environment,
)
from src.tests.btrc.selfhost_snippet_harness import REPO, compile_source

REASON = "its managed payloads are borrowed references that it never retains"

PRELUDE = """import Library.Map;
import Library.Vector;

interface INamed {
	int identity();
}

class Probe implements INamed {
	public int id;
	public Probe(int id) {
		self.id = id;
	}
	public int identity() {
		return self.id;
	}
}

"""

# Each payload kind is one variant shape and the argument that builds it from a
# local `Probe child`.
PAYLOADS = {
    "string": ("string text", 'f"probe-{child.id}"'),
    "class": ("Probe child", "child"),
    "interface": ("INamed view", "child"),
    "collection": ("Vector<Probe> probes", "probes"),
}


def _program(payload: str, body: str) -> str:
    slot, argument = PAYLOADS[payload]
    setup = "\tProbe child = Probe(42);\n\tVector<Probe> probes = [];\n\tprobes.push(child);\n"
    if payload == "string":
        setup += f"\tstring owned = {argument};\n"
        argument = "owned"
    declaration = f"enum class Outcome {{\n\tHeld({slot}),\n\tRejected(int code)\n}}\n\n"
    field = slot.rpartition(" ")[2]
    return PRELUDE + declaration + body.replace("SETUP", setup).replace("ARG", argument).replace("FIELD", field)


# flow -> (program body, expected first diagnostic). SETUP declares the
# payload owners; ARG is the payload argument.
FLOWS = {
    "return": (
        "Outcome make() {\nSETUP\treturn Outcome.Held(ARG);\n}\n\nint main() {\n\tmake();\n\treturn 0;\n}\n",
        f"Return type of function 'make' cannot be nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "method-return": (
        "class Factory {\n\tpublic Outcome make(Probe child) {\n\t\treturn Outcome.Rejected(child.id);\n\t}\n}\n\n"
        "int main() {\n\treturn 0;\n}\n",
        f"Return type of method 'Factory.make' cannot be nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "outer-assignment": (
        "int main() {\n\tOutcome result = Outcome.Rejected(0);\n\t{\nSETUP\t\tresult = Outcome.Held(ARG);\n\t}\n"
        "\treturn result.tag;\n}\n",
        f"Nonescaping rich enum 'Outcome' cannot be reassigned; {REASON}, so declare a new local",
    ),
    "payload-store": (
        "int main() {\nSETUP\tOutcome result = Outcome.Held(ARG);\n\tresult.data.Held.FIELD = ARG;\n"
        "\treturn 0;\n}\n",
        f"Payload of nonescaping rich enum 'Outcome' cannot be reassigned; {REASON}, so declare a new local",
    ),
    "class-field": (
        "class Holder {\n\tpublic Outcome result;\n}\n\nint main() {\n\treturn 0;\n}\n",
        f"Field 'Holder.result' cannot store nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "struct-field": (
        "struct Pair {\n\tOutcome result;\n};\n\nint main() {\n\treturn 0;\n}\n",
        f"Struct field 'Pair.result' cannot store nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "global": (
        "Outcome saved = Outcome.Rejected(0);\n\nint main() {\n\treturn saved.tag;\n}\n",
        f"Global 'saved' cannot store nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "static-local": (
        "int main() {\n\tstatic Outcome saved = Outcome.Rejected(0);\n\treturn saved.tag;\n}\n",
        f"Variable 'saved' cannot store nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "uninitialized": (
        "int main() {\n\tOutcome result;\n\treturn 0;\n}\n",
        "Variable 'result' must initialize its nonescaping rich enum 'Outcome' borrow",
    ),
    "vector-insert": (
        "int main() {\nSETUP\tVector<Outcome> results = [];\n\tresults.push(Outcome.Held(ARG));\n\treturn 0;\n}\n",
        "Variable 'results' cannot contain nonescaping rich enum 'Outcome' in aggregate or managed storage",
    ),
    "map-value": (
        "int main() {\n\tMap<string, Outcome> results = {};\n\treturn 0;\n}\n",
        "Variable 'results' cannot contain nonescaping rich enum 'Outcome' in aggregate or managed storage",
    ),
    "collection-parameter": (
        "int count(Vector<Outcome> results) {\n\treturn results.len;\n}\n\nint main() {\n\treturn 0;\n}\n",
        "Parameter 'results' of function 'count' cannot contain nonescaping rich enum 'Outcome' in aggregate or "
        "managed storage",
    ),
    "tuple": (
        "int main() {\nSETUP\tTuple<Outcome, int> pair = (Outcome.Held(ARG), 1);\n\treturn 0;\n}\n",
        "Variable 'pair' cannot contain nonescaping rich enum 'Outcome' in aggregate or managed storage",
    ),
    "array": (
        "int main() {\nSETUP\tOutcome results[1] = {Outcome.Held(ARG)};\n\treturn 0;\n}\n",
        "Rich enum 'Outcome' borrows its managed payloads and must be one direct value; pointer, nullable and "
        "array shapes are not supported",
    ),
    "pointer": (
        "void fill(Outcome* out) {\n\tout->tag = Outcome.Rejected;\n}\n\nint main() {\n\treturn 0;\n}\n",
        "Rich enum 'Outcome' borrows its managed payloads and must be one direct value; pointer, nullable and "
        "array shapes are not supported",
    ),
    "nested-payload": (
        "enum class Wrapper {\n\tWrap(Outcome inner),\n\tNothing\n}\n\nint main() {\n\treturn 0;\n}\n",
        f"Rich-enum payload 'Wrapper.Wrap.inner' cannot store nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "lambda-capture": (
        "int main() {\nSETUP\tOutcome result = Outcome.Held(ARG);\n\tvar read = () => result.tag;\n"
        "\treturn read();\n}\n",
        "A lambda cannot capture nonescaping rich enum 'result'",
    ),
    "lambda-return": (
        "int main() {\n\tvar make = (int code) => Outcome.Rejected(code);\n\treturn 0;\n}\n",
        f"Lambda return type cannot be nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "lambda-block-return": (
        "int main() {\n\tvar make = () => {\nSETUP\t\treturn Outcome.Held(ARG);\n\t};\n\treturn 0;\n}\n",
        f"Lambda return type cannot be nonescaping rich enum 'Outcome'; {REASON}",
    ),
    "spawn-capture": (
        "int main() {\nSETUP\tOutcome result = Outcome.Held(ARG);\n"
        "\tThread<int> worker = spawn(() => result.tag);\n\treturn worker.join();\n}\n",
        "A lambda cannot capture nonescaping rich enum 'result'",
    ),
    "thread-result": (
        "int main() {\n\tThread<Outcome> worker = spawn(() => Outcome.Rejected(1));\n\tworker.join();\n"
        "\treturn 0;\n}\n",
        "Variable 'worker' cannot contain nonescaping rich enum 'Outcome' in aggregate or managed storage",
    ),
}

# The full flow matrix runs for class payloads; each other payload kind runs
# the flows that build a value from its own owner.
PAYLOAD_FLOWS = ("return", "outer-assignment", "payload-store", "vector-insert", "lambda-capture", "spawn-capture")
CASES = [("class", flow) for flow in FLOWS] + [
    (payload, flow) for payload in ("string", "interface", "collection") for flow in PAYLOAD_FLOWS
]


def _compile_reference(tmp_path: Path, source: str, stem: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / f"{stem}.btrc"
    generated = tmp_path / f"{stem}-reference.c"
    program.write_text(source)
    result = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(program), "--no-cache", "-o", str(generated)],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / f"cache-{stem}")},
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result, generated


def _first_error(stderr: str) -> str:
    for line in stderr.splitlines():
        if line.startswith("error: "):
            message = line.removeprefix("error: ")
            head, separator, position = message.rpartition(" at ")
            if separator and position.replace(":", "").isdigit():
                return head
            return message
    raise AssertionError(f"no error diagnostic in:\n{stderr}")


@pytest.mark.parametrize(("payload", "flow"), CASES, ids=[f"{payload}-{flow}" for payload, flow in CASES])
def test_nonescaping_rich_enum_flow_is_refused_with_parity(
    semantic_btrcc: Path, tmp_path: Path, payload: str, flow: str
) -> None:
    body, diagnostic = FLOWS[flow]
    source = _program(payload, body)
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source, no_stdlib=False)
    reference, _ = _compile_reference(tmp_path, source, "Escape")

    assert reference.returncode != 0, f"reference compiler accepted the {flow} escape:\n{source}"
    assert selfhost.returncode != 0, f"btrcc accepted the {flow} escape:\n{source}"
    assert _first_error(reference.stderr) == diagnostic
    assert _first_error(selfhost.stderr) == diagnostic


SCALAR_FLOWS = """enum class Measure {
	Exact(double value, long count),
	Missing
}

class Holder {
	public Measure saved;
	public Holder() {
		self.saved = Measure.Missing();
	}
}

Measure global = Measure.Exact(1.0, 1L);

Measure make(long count) {
	return Measure.Exact(0.5, count);
}

int main() {
	Holder holder = Holder();
	holder.saved = make(3L);
	Vector<Measure> measures = [];
	measures.push(make(4L));
	Measure local = Measure.Missing();
	local = global;
	local.data.Exact.count = 5L;
	var read = () => local.data.Exact.count;
	Thread<Measure> worker = spawn(() => Measure.Exact(2.0, 6L));
	Measure joined = worker.join();
	long total = holder.saved.data.Exact.count + measures.get(0).data.Exact.count + read() + joined.data.Exact.count;
	return total == 18L ? 0 : 1;
}
"""


@pytest.mark.parametrize(
    "program",
    [
        "src/tests/enums/RichEnumBorrowedPayloads.btrc",
        "src/tests/enums/RichEnumManagedCollectionPayloads.btrc",
        "scalar-flows",
    ],
)
def test_allowed_rich_enum_flows_are_sanitizer_clean_in_both_compilers(
    semantic_btrcc: Path, tmp_path: Path, program: str
) -> None:
    source = PRELUDE + SCALAR_FLOWS if program == "scalar-flows" else (REPO / program).read_text()
    toolchain = require_sanitizers(tmp_path)
    selfhost, selfhost_source = compile_source(semantic_btrcc, tmp_path, source, no_stdlib=False)
    reference, reference_source = _compile_reference(tmp_path, source, "Allowed")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    for label, generated in (("selfhost", selfhost_source), ("reference", reference_source)):
        executable = tmp_path / f"{label}-allowed"
        sanitized_build_and_run(generated, executable, toolchain)
        if sys.platform.startswith("linux"):
            environment = sanitizer_environment(toolchain)
            environment["ASAN_OPTIONS"] = "detect_leaks=1:abort_on_error=1"
            leaks = subprocess.run(
                [str(executable)], cwd=REPO, env=environment, capture_output=True, text=True, timeout=30
            )
            assert leaks.returncode == 0, leaks.stderr
