"""Floating-point portion of the freestanding reference formatter."""

from __future__ import annotations

REFERENCE_FLOAT_FORMATTER = r"""
static int __btrc_rt_normalize(long double *value) {
    int exponent = 0;
    if (*value == 0.0L) return 0;
    while (*value >= 10.0L) { *value /= 10.0L; exponent++; }
    while (*value < 1.0L) { *value *= 10.0L; exponent--; }
    return exponent;
}

static int __btrc_rt_next_digit(long double *value) {
    int digit = (int)*value;
    if (digit < 0) digit = 0;
    if (digit > 9) digit = 9;
    *value = (*value - (long double)digit) * 10.0L;
    if (*value < 0.0L) *value = 0.0L;
    return digit;
}

static void __btrc_rt_emit_exponent(
        __btrc_rt_sink *sink, int exponent, bool upper) {
    char reversed[16];
    int length;
    __btrc_rt_put(sink, upper ? 'E' : 'e');
    if (exponent < 0) { __btrc_rt_put(sink, '-'); exponent = -exponent; }
    else __btrc_rt_put(sink, '+');
    length = __btrc_rt_digits(reversed, (uintmax_t)exponent, 10U, false);
    if (length < 2) __btrc_rt_put(sink, '0');
    while (length-- > 0) __btrc_rt_put(sink, reversed[length]);
}

static void __btrc_rt_emit_fixed_body(
        __btrc_rt_sink *sink, long double value, int precision) {
    long double rounding = 0.5L;
    for (int i = 0; i < precision; ++i) rounding /= 10.0L;
    long double rounded = value + rounding;
    if (rounded != 0.0L && rounded + rounded == rounded) rounded = value;
    value = rounded;
    int exponent = __btrc_rt_normalize(&value);
    if (rounded == 0.0L || exponent < 0) {
        __btrc_rt_put(sink, '0');
    } else {
        for (int place = exponent; place >= 0; --place)
            __btrc_rt_put(sink, (char)('0' + __btrc_rt_next_digit(&value)));
    }
    if (precision <= 0) return;
    __btrc_rt_put(sink, '.');
    for (int place = -1; place >= -precision; --place) {
        int digit = place > exponent || rounded == 0.0L
            ? 0 : __btrc_rt_next_digit(&value);
        __btrc_rt_put(sink, (char)('0' + digit));
    }
}

static int __btrc_rt_significant_digits(
        long double *value, int count, unsigned char *digits) {
    if (*value == 0.0L) {
        for (int i = 0; i < count; ++i) digits[i] = 0U;
        return 0;
    }
    int exponent = __btrc_rt_normalize(value);
    long double rounding = 0.5L;
    for (int i = 1; i < count; ++i) rounding /= 10.0L;
    *value += rounding;
    if (*value >= 10.0L) { *value /= 10.0L; exponent++; }
    for (int i = 0; i < count; ++i)
        digits[i] = (unsigned char)__btrc_rt_next_digit(value);
    return exponent;
}

static void __btrc_rt_emit_scientific_body(
        __btrc_rt_sink *sink, long double value, int precision, bool upper) {
    unsigned char digits[20];
    int count = precision + 1;
    int exponent = __btrc_rt_significant_digits(&value, count, digits);
    __btrc_rt_put(sink, (char)('0' + digits[0]));
    if (precision > 0) {
        __btrc_rt_put(sink, '.');
        for (int i = 1; i < count; ++i)
            __btrc_rt_put(sink, (char)('0' + digits[i]));
    }
    __btrc_rt_emit_exponent(sink, exponent, upper);
}

static void __btrc_rt_emit_general_body(
        __btrc_rt_sink *sink, long double value, int precision,
        bool upper, bool alternate) {
    unsigned char digits[18];
    int exponent = __btrc_rt_significant_digits(&value, precision, digits);
    int last = precision - 1;
    if (!alternate) while (last >= 0 && digits[last] == 0) last--;
    if (last < 0) { __btrc_rt_put(sink, '0'); return; }
    if (exponent < -4 || exponent >= precision) {
        __btrc_rt_put(sink, (char)('0' + digits[0]));
        if (last > 0 || alternate) {
            __btrc_rt_put(sink, '.');
            for (int i = 1; i <= last; ++i)
                __btrc_rt_put(sink, (char)('0' + digits[i]));
        }
        __btrc_rt_emit_exponent(sink, exponent, upper);
        return;
    }
    if (exponent < 0) {
        __btrc_rt_put(sink, '0');
        __btrc_rt_put(sink, '.');
        for (int place = -1; place > exponent; --place) __btrc_rt_put(sink, '0');
        for (int i = 0; i <= last; ++i)
            __btrc_rt_put(sink, (char)('0' + digits[i]));
        return;
    }
    for (int place = 0; place <= exponent; ++place) {
        int digit = place < precision ? digits[place] : 0;
        __btrc_rt_put(sink, (char)('0' + digit));
    }
    if (last > exponent || alternate) {
        __btrc_rt_put(sink, '.');
        for (int i = exponent + 1; i <= last; ++i)
            __btrc_rt_put(sink, (char)('0' + digits[i]));
    }
}

static void __btrc_rt_emit_real_body(
        __btrc_rt_sink *sink, long double value, char spec,
        int precision, bool alternate) {
    bool upper = spec == 'F' || spec == 'E' || spec == 'G';
    char lower = upper ? (char)(spec + ('a' - 'A')) : spec;
    if (value != value) {
        const char *word = upper ? "NAN" : "nan";
        while (*word) __btrc_rt_put(sink, *word++);
    } else if (value != 0.0L && value + value == value) {
        const char *word = upper ? "INF" : "inf";
        while (*word) __btrc_rt_put(sink, *word++);
    } else if (lower == 'f') {
        __btrc_rt_emit_fixed_body(sink, value, precision);
    } else if (lower == 'e') {
        __btrc_rt_emit_scientific_body(sink, value, precision, upper);
    } else {
        __btrc_rt_emit_general_body(sink, value, precision, upper, alternate);
    }
}

static void __btrc_rt_emit_real(
        __btrc_rt_sink *sink, long double value, char spec, int width,
        int precision, bool zero, bool left, bool plus, bool space,
        bool alternate) {
    bool negative = value < 0.0L;
    if (negative) value = -value;
    char sign = negative ? '-' : plus ? '+' : space ? ' ' : '\0';
    __btrc_rt_sink count = {0};
    __btrc_rt_emit_real_body(&count, value, spec, precision, alternate);
    int padding = width - (int)count.pos - (sign ? 1 : 0);
    if (!left && !zero) __btrc_rt_pad(sink, ' ', padding);
    if (sign) __btrc_rt_put(sink, sign);
    if (!left && zero) __btrc_rt_pad(sink, '0', padding);
    __btrc_rt_emit_real_body(sink, value, spec, precision, alternate);
    if (left) __btrc_rt_pad(sink, ' ', padding);
}
"""

__all__ = ["REFERENCE_FLOAT_FORMATTER"]
