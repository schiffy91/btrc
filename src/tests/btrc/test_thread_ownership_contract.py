"""Fail-closed unique-owner contracts for ``Thread<T>`` handles."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run
from src.tests.btrc.test_thread_result_abi import _compile_pair, _compile_reference

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "class Owner { public Thread<int> worker; } int main() { return 0; }",
            "cannot own a Thread handle",
        ),
        (
            "int consume(Thread<int> worker) { return 0; } int main() { return 0; }",
            "cannot own a Thread handle",
        ),
        (
            "Thread<int> worker = spawn(() => 7); int main() { return 0; }",
            "cannot own a Thread handle with static storage",
        ),
        (
            "int main() { Thread<int> worker; return 0; }",
            "must initialize its Thread<T> owner",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); worker = spawn(() => 8); return 0; }",
            "Thread owner variables are single-assignment",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); var callback = () => worker.join(); return 0; }",
            "cannot capture Thread handle",
        ),
        (
            "class Box { public int value; public Box(int value) { self.value = value; } } struct Payload { Box box; }; Thread<int> launch() { Box box = new Box(7); Payload payload = {box}; return spawn(() => payload.box.value); } int main() { return launch().join(); }",
            "spawn cannot capture shallow aggregate 'payload'",
        ),
        (
            "Thread<int> launch() { int values[2] = {7, 8}; return spawn(() => values[0]); } int main() { return launch().join(); }",
            "spawn cannot capture array storage through 'values'",
        ),
        (
            "int main() { Thread<Thread<int>> worker = null; return 0; }",
            "result type cannot contain another Thread handle",
        ),
        (
            "int main() { Thread<int[]> worker = spawn(() => { int[] values = {1, 2}; return values; }); return 0; }",
            "result type cannot contain an unsized array",
        ),
        (
            "int main() { Thread<(int[], int)> worker = null; return 0; }",
            "result type cannot contain an unsized array",
        ),
        (
            "struct Payload { int[] values; }; int main() { Thread<Payload> worker = null; return 0; }",
            "result type cannot contain an unsized array",
        ),
        (
            "enum class Payload { Values(int[] values), Empty } int main() { Thread<Payload> worker = null; return 0; }",
            "result type cannot contain an unsized array",
        ),
        (
            "int main() { Thread<Mutex<int>> worker = null; return 0; }",
            "result type cannot contain a Mutex handle",
        ),
        (
            "int main() { Thread<(Mutex<int>, int)> worker = null; return 0; }",
            "result type cannot contain a Mutex handle",
        ),
        (
            "struct Payload { Mutex<int> gate; }; int main() { Thread<Payload> worker = null; return 0; }",
            "result type cannot contain a Mutex handle",
        ),
        (
            "enum class Payload { Guard(Mutex<int> gate), Empty } int main() { Thread<Payload> worker = null; return 0; }",
            "result type cannot contain a Mutex handle",
        ),
        (
            "struct Payload { Mutex<int> gates[2]; }; int main() { Thread<Payload> worker = null; return 0; }",
            "result type cannot contain a Mutex handle",
        ),
        (
            "typedef Mutex<int> Gate; struct Payload { Gate gate; }; int main() { Thread<Payload> worker = null; return 0; }",
            "result type cannot contain a Mutex handle",
        ),
        (
            "int main() { for (Thread<int> worker = spawn(() => 7); false; ) {} return 0; }",
            "C-style for initializer cannot own a Thread handle",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); delete worker; return 0; }",
            "delete is not valid for type 'Thread<int>'",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); keep worker; return 0; }",
            "keep is not valid for type 'Thread<int>'",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); release worker; return 0; }",
            "release is not valid for type 'Thread<int>'",
        ),
        (
            "int main() { Thread<int>* worker = null; return 0; }",
            "Thread<T> owner type must be one direct mutable handle",
        ),
        (
            "int main() { Thread<int>[] workers = {}; return 0; }",
            "Thread<T> owner type must be one direct mutable handle",
        ),
        (
            "int main() { const Thread<int> worker = spawn(() => 7); return 0; }",
            "Thread<T> owner type must be one direct mutable handle",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); return ((Thread<int>)worker).join(); }",
            "Thread handles cannot be cast",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); return (true ? worker : worker).join(); }",
            "Thread.join() receiver must be a unique local owner or a fresh Thread result",
        ),
        (
            "int main() { Thread<int>? worker = null; return 0; }",
            "Thread<T> owner type must be one direct mutable handle",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); return worker?.join(); }",
            "Thread.join() receiver must be a unique local owner or a fresh Thread result",
        ),
        (
            "int main() { Thread<int> worker = spawn(() => 7); { int worker = 1; return worker; } }",
            "cannot shadow an active Thread owner",
        ),
        (
            "Thread<int> launch() { int worker = 1; { Thread<int> worker = spawn(() => 7); return worker; } } int main() { return launch().join(); }",
            "cannot shadow another active binding",
        ),
        (
            "class Workers { public int iterLen() { return 1; } public Thread<int> iterGet(int index) { return spawn(() => index); } } int main() { Workers workers = new Workers(); for worker in workers { return 0; } return 0; }",
            "for-in loop variables cannot own a Thread handle",
        ),
        (
            'int main() { Thread<(string, int)> worker = spawn(() => { string text = "abc".substring(0, 2); (string, int) result = (text, 7); return result; }); return 0; }',
            "aggregate result type cannot contain string or class references",
        ),
        (
            'struct Payload { string text; int value; }; int main() { Thread<Payload> worker = spawn(() => { string text = "abc".substring(0, 2); Payload result = {text, 7}; return result; }); return 0; }',
            "aggregate result type cannot contain string or class references",
        ),
        (
            'enum class Payload { Text(string text), Empty } int main() { Thread<Payload> worker = spawn(() => { string text = "abc".substring(0, 2); Payload result = Payload.Text(text); return result; }); return 0; }',
            "aggregate result type cannot contain string or class references",
        ),
        (
            "struct Payload { string names[2]; }; int main() { Thread<Payload> worker = null; return 0; }",
            "aggregate result type cannot contain string or class references",
        ),
        (
            "struct Payload { string text; }; typedef Payload Alias; typedef Alias Result; int main() { Thread<Result> worker = null; return 0; }",
            "aggregate result type cannot contain string or class references",
        ),
        (
            "int main() { bool live = spawn(() => 7) != null; return live ? 0 : 1; }",
            "Fresh Thread result must be joined, returned, discarded directly",
        ),
        (
            "int main() { (void*)spawn(() => 7); return 0; }",
            "Thread handles cannot be cast",
        ),
        (
            "int main() { consume(spawn(() => 7)); return 0; }",
            "Thread handles cannot be passed as arguments",
        ),
        (
            "int main() { for value in range(spawn(() => 7)) { return value; } return 0; }",
            "Thread handles cannot be passed as range arguments",
        ),
        (
            "int main() { (spawn(() => 7), 1); return 0; }",
            "Thread handles cannot be embedded in aggregate values",
        ),
        (
            "class Workers { public Thread<int> get(int index) { return spawn(() => index); } } int main() { Workers workers = new Workers(); workers[0]; return 0; }",
            "Only a direct fresh Thread result can be discarded safely",
        ),
        (
            "Thread<int> choose() { Thread<int> left = spawn(() => 1); Thread<int> right = spawn(() => 2); return true ? left : right; } int main() { return choose().join(); }",
            "Thread transfer must use one unique local owner or a direct fresh result",
        ),
    ],
)
def test_thread_owner_shapes_are_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference(
        tmp_path,
        source,
        "thread-owner-diagnostic",
    )
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr


def test_fixed_scalar_array_thread_result_remains_supported(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        struct Payload { int values[2]; };
        Thread<int> capturePayload() {
            Payload payload = {};
            payload.values[0] = 3;
            payload.values[1] = 4;
            return spawn(() => payload.values[0] + payload.values[1]);
        }
        int main() {
            Thread<Payload> worker = spawn(() => {
                Payload value = {};
                value.values[0] = 1;
                value.values[1] = 2;
                return value;
            });
            Payload result = worker.join();
            int captured = capturePayload().join();
            return result.values[0] == 1 && result.values[1] == 2
                    && captured == 7 ? 0 : 1;
        }
    """
    for name, generated in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "thread-fixed-array-result",
    ):
        _strict_build_and_run(generated, tmp_path / f"thread-fixed-array-{name}")
