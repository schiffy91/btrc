"""Hand-written C11 sources that runtime and operator contract tests compile beside generated code."""

from __future__ import annotations

RUNTIME_HELPER_HEADERS = """\
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <math.h>
#include <setjmp.h>
#include <pthread.h>
"""


TYPED_OPERATOR_RUNTIME = r"""
#include <assert.h>

int left_calls = 0;
int right_calls = 0;

string? left_probe(string? value) {
    left_calls++;
    return value;
}

string? right_probe(string? value) {
    right_calls++;
    return value;
}

int identity(int value) { return value; }
int negate(int value) { return -value; }
int callback_order = 0;

__fn_ptr<int, int> callback_probe(
    __fn_ptr<int, int> callback, int marker
) {
    callback_order = callback_order * 10 + marker;
    return callback;
}

class StringOps<T> {
    public T value;
    public StringOps(T value) { self.value = value; }
    public bool eq(T other) { return self.value == other; }
    public bool ne(T other) { return self.value != other; }
    public bool lt(T other) { return self.value < other; }
    public bool gt(T other) { return self.value > other; }
    public bool le(T other) { return self.value <= other; }
    public bool ge(T other) { return self.value >= other; }
    public T join(T other) { return self.value + other; }
    public T fallback(T other) { return self.value ?? other; }
}

class MagicOps<T> {
    public MagicOps() {}
    public bool eq(T left, T right) { return __btrc_eq(left, right); }
    public bool lt(T left, T right) { return __btrc_lt(left, right); }
    public bool gt(T left, T right) { return __btrc_gt(left, right); }
    public uint hash(T value) { return __btrc_hash(value); }
}

class NumberOps<T> {
    public NumberOps() {}
    public T divide(T left, T right) { return left / right; }
    public T modulo(T left, T right) { return left % right; }
}

class Base {
    public Base() {}
}

class Child extends Base {
    public Child() {}
}

int main() {
    string dynamic = "sa" + "me";
    string? nil = null;

    assert(dynamic == "same");
    assert(dynamic != "different");
    assert("alpha" < "beta");
    assert("beta" > "alpha");
    assert("alpha" <= "alpha");
    assert("beta" >= "beta");

    assert(nil == null);
    assert(nil < "alpha");
    assert("alpha" > nil);
    assert(nil <= null);
    assert("alpha" >= nil);
    assert(nil != "alpha");

    assert(left_probe(null) < right_probe("x"));
    assert(left_calls == 1 && right_calls == 1);
    left_calls = 0;
    right_calls = 0;
    assert(left_probe(dynamic) == right_probe("same"));
    assert(left_calls == 1 && right_calls == 1);

    StringOps<string?> empty = new StringOps<string?>(null);
    StringOps<string?> text = new StringOps<string?>(dynamic);
    assert(empty.eq(null));
    assert(empty.ne("same"));
    assert(empty.lt("same"));
    assert(text.gt(null));
    assert(empty.le(null));
    assert(text.ge("same"));
    assert(text.eq("same"));
    assert(text.fallback("fallback") == "same");
    assert(empty.fallback("fallback") == "fallback");
    assert(text.join("!") == "same!");

    MagicOps<string?> magic = new MagicOps<string?>();
    assert(magic.eq(dynamic, "same"));
    assert(magic.lt(null, "same"));
    assert(magic.gt("same", null));
    assert(magic.hash(null) == 0u);
    assert(magic.hash(dynamic) == magic.hash("same"));
    MagicOps<double> real_magic = new MagicOps<double>();
    assert(real_magic.hash(0.0) == real_magic.hash(-0.0));
    assert(real_magic.hash(1.5) == real_magic.hash(1.5));
    assert(real_magic.hash(NAN) == real_magic.hash(NAN));
    assert(real_magic.hash(INFINITY) == real_magic.hash(INFINITY));

    NumberOps<int> ints = new NumberOps<int>();
    assert(ints.divide(21, 2) == 10);
    assert(ints.modulo(21, 2) == 1);
    NumberOps<float> floats = new NumberOps<float>();
    assert(floats.modulo(7.9, 2.0) == 1.0);
    NumberOps<long long> wide = new NumberOps<long long>();
    assert(wide.divide(8589934592LL, 2LL) == 4294967296LL);
    assert(wide.modulo(8589934593LL, 2LL) == 1LL);
    long negative = -2L;
    uint one = 1u;
    var mixed_first = negative + one;
    var mixed_second = one + negative;
    assert(mixed_first == (unsigned long)-1L);
    assert(mixed_second == (unsigned long)-1L);
    printf("%lu %lu", mixed_first, mixed_second);
    printf("%llu %llu", true ? 1LL : 2u, false ? 2u : 1LL);
    printf("%f", 7.9 % 2.0);

    Base base = new Base();
    Child child = new Child();
    Base alias = child;
    assert(alias == child);
    assert(base != child);
    __fn_ptr<int, int> callback = identity;
    assert(callback == callback);
    assert(callback != null);
    assert(callback_probe(identity, 1) == callback_probe(identity, 2));
    assert(callback_order == 12);
    callback_order = 0;
    assert(callback_probe(identity, 1) != callback_probe(negate, 2));
    assert(callback_order == 12);
    MagicOps<__fn_ptr<int, int>> callback_magic =
        new MagicOps<__fn_ptr<int, int>>();
    assert(callback_magic.eq(callback, callback));
    return 0;
}
"""


NUMERIC_COMPARISON_RUNTIME = r"""
#include <assert.h>

enum Rank { Low, High };

bool compareUnsignedInt(unsigned int value, int same, int lower) {
    return value == 42 && 42 == value
        && value != 41 && 41 != value
        && value == same && same == value
        && value != lower && lower != value
        && value > 41 && 41 < value
        && value >= 42 && 42 <= value
        && value > lower && lower < value
        && value >= same && same <= value;
}

bool compareUnsignedLongLong(
        unsigned long long value, long long same, long long lower) {
    return value == 42 && 42 == value
        && value != 41 && 41 != value
        && value == same && same == value
        && value != lower && lower != value
        && value > 41 && 41 < value
        && value >= 42 && 42 <= value
        && value > lower && lower < value
        && value >= same && same <= value;
}

bool compareSameTypes(size_t left, size_t right, Rank low, Rank high) {
    return left == right && low < high;
}

int main() {
    assert(compareUnsignedInt(42u, 42, 41));
    assert(compareUnsignedLongLong(42ULL, 42LL, 41LL));
    size_t amount = 7;
    assert(compareSameTypes(amount, amount, Low, High));
    print("PASS: numeric comparison C11");
    return 0;
}
"""
