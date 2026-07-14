"""Reachability and strict-warning contracts for generic operation helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.helpers.hash import HASH
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

PLAIN_GENERIC = """
class Box<T> {
    public T value;
    public Box(T value) { self.value = value; }
    public T get() { return self.value; }
}
int main() {
    Box<int> box = new Box<int>(42);
    return box.get() == 42 ? 0 : 1;
}
"""

STRING_GENERIC = """
class Operations<T> {
    public T value;
    public T* data;
    public Operations(T value) { self.value = value; self.data = null; }
    public bool matches(T other) {
        T local = other;
        bool same = __btrc_eq(self.value, local);
        bool indexed = false && __btrc_eq(self.data[0], "unused");
        return same && !indexed
            && __btrc_lt(local, "z")
            && __btrc_gt("z", local);
    }
    public int bucket(T key) { return __btrc_hash(key) % 17; }
}
int main() {
    Operations<string> value = new Operations<string>("same");
    int bucket = value.bucket("key");
    return value.matches("same") && bucket >= 0 && bucket < 17 ? 0 : 1;
}
"""

INT_GENERIC = """
class Operations<T> {
    public Operations() {}
    public bool equal(T left, T right) { return __btrc_eq(left, right); }
    public bool ordered(T low, T high) {
        return __btrc_lt(low, high) && __btrc_gt(high, low);
    }
    public int bucket(T key) { return __btrc_hash(key) % 17; }
}
int main() {
    Operations<int> value = new Operations<int>();
    int bucket = value.bucket(42);
    return value.equal(7, 7) && value.ordered(1, 2)
        && bucket >= 0 && bucket < 17 ? 0 : 1;
}
"""

POINTER_GENERIC = """
class Key {
    public int value;
    public Key(int value) { self.value = value; }
}
class Operations<T> {
    public Operations() {}
    public bool equal(T left, T right) { return __btrc_eq(left, right); }
    public int bucket(T key) { return __btrc_hash(key) % 17; }
}
int main() {
    Key key = new Key(7);
    Operations<Key> value = new Operations<Key>();
    int bucket = value.bucket(key);
    return value.equal(key, key) && bucket >= 0 && bucket < 17 ? 0 : 1;
}
"""

NORMAL_INTRINSICS = """
int main() {
    bool equal = __btrc_eq("same", "same");
    bool ordered = __btrc_lt(1, 2) && __btrc_gt(2, 1);
    int bucket = __btrc_hash("key") % 17;
    return equal && ordered && bucket >= 0 && bucket < 17 ? 0 : 1;
}
"""

DEAD_HASH_GENERIC = """
class Hasher<T> {
    public Hasher() {}
    public int bucket(T key) { return __btrc_hash(key) % 17; }
}
int main() {
    Hasher<string> hasher = new Hasher<string>();
    return hasher == null ? 1 : 0;
}
"""

ADOPT_GENERIC = """
class Adopter<T> {
    public Adopter() {}
    public string make() {
        char* raw = (char*)__btrc_safe_realloc(NULL, (size_t)2);
        raw[0] = (char)120;
        raw[1] = (char)0;
        return __btrc_string_adopt(raw);
    }
}
int main() {
    Adopter<int> adopter = new Adopter<int>();
    string value = adopter.make();
    return value[0] == (char)120 ? 0 : 1;
}
"""


def test_generic_operation_helpers_follow_live_structured_calls():
    generated = {
        "plain": emit_c(PLAIN_GENERIC),
        "string": emit_c(STRING_GENERIC),
        "int": emit_c(INT_GENERIC),
        "pointer": emit_c(POINTER_GENERIC),
        "normal": emit_c(NORMAL_INTRINSICS),
        "dead_hash": emit_c(DEAD_HASH_GENERIC),
        "adopt": emit_c(ADOPT_GENERIC),
    }

    assert set(HASH) == {"__btrc_hash_real", "__btrc_hash_str"}
    for c_source in generated.values():
        assert "__builtin" not in c_source
        assert "__typeof__" not in c_source
        assert "__btrc_eq(" not in c_source
        assert "__btrc_lt(" not in c_source
        assert "__btrc_gt(" not in c_source
        assert "__btrc_hash(" not in c_source

    assert "strcmp(" in generated["string"]
    assert "strcmp(" in generated["normal"]
    assert "static inline unsigned int __btrc_hash_str" in generated["string"]
    assert "static inline unsigned int __btrc_hash_str" in generated["normal"]
    assert "__btrc_hash_real" not in generated["string"]
    assert "__btrc_hash_real" not in generated["normal"]
    assert "((unsigned int)key)" in generated["int"]
    assert "uintptr_t" not in generated["int"]
    assert "((uintptr_t)" in generated["pointer"]
    assert "__btrc_hash_str" not in generated["dead_hash"]

    adopt_start = generated["adopt"].index("static char* btrc_Adopter_int_make(btrc_Adopter_int* self) {")
    adopt_end = generated["adopt"].index("\n}", adopt_start)
    adopt_body = generated["adopt"][adopt_start:adopt_end]
    assert "__btrc_string_adopt(raw)" in adopt_body
    assert "__btrc_string_retain" not in adopt_body


@pytest.mark.skipif(
    not COMPILERS or sys.platform == "win32",
    reason="requires a hosted C11 compiler",
)
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "name, source",
    (
        ("plain", PLAIN_GENERIC),
        ("string", STRING_GENERIC),
        ("int", INT_GENERIC),
        ("pointer", POINTER_GENERIC),
        ("normal", NORMAL_INTRINSICS),
        ("dead_hash", DEAD_HASH_GENERIC),
        ("adopt", ADOPT_GENERIC),
    ),
)
def test_generic_helper_reachability_is_warning_clean(
    tmp_path: Path,
    c_compiler: str,
    name: str,
    source: str,
):
    c_path = tmp_path / f"{name}.c"
    binary = tmp_path / name
    c_path.write_text(emit_c(source))

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([binary], check=True, timeout=15)
