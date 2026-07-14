"""Self-contained formatted-output implementation for the reference runtime."""

from __future__ import annotations

from .freestanding_float_formatter import REFERENCE_FLOAT_FORMATTER

REFERENCE_FORMATTER = (
    r"""
typedef struct {
    char *out;
    size_t cap;
    size_t pos;
} __btrc_rt_sink;

static void __btrc_rt_put(__btrc_rt_sink *sink, char value) {
    if (sink->out && sink->pos + 1U < sink->cap) sink->out[sink->pos] = value;
    sink->pos++;
}

static void __btrc_rt_pad(__btrc_rt_sink *sink, char value, int count) {
    while (count-- > 0) __btrc_rt_put(sink, value);
}

static int __btrc_rt_digits(
        char *reversed, uintmax_t value, unsigned int base, bool upper) {
    const char *alphabet = upper
        ? "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        : "0123456789abcdefghijklmnopqrstuvwxyz";
    int length = 0;
    do {
        reversed[length++] = alphabet[value % base];
        value /= base;
    } while (value != 0U);
    return length;
}

static void __btrc_rt_emit_integer(
        __btrc_rt_sink *sink, uintmax_t value, bool negative,
        unsigned int base, bool upper, bool alternate, int width,
        int precision, bool zero, bool left, bool plus, bool space) {
    char reversed[sizeof(uintmax_t) * CHAR_BIT + 1U];
    int digits = value == 0U && precision == 0
        ? 0 : __btrc_rt_digits(reversed, value, base, upper);
    char sign = negative ? '-' : plus ? '+' : space ? ' ' : '\0';
    const char *prefix = "";
    int prefix_length = sign ? 1 : 0;
    if (alternate && value != 0U && base == 16U) {
        prefix = upper ? "0X" : "0x";
        prefix_length += 2;
    } else if (alternate && base == 8U && (digits == 0 || reversed[digits - 1] != '0')) {
        prefix = "0";
        prefix_length += 1;
    }
    int leading_zeroes = precision > digits ? precision - digits : 0;
    int padding = width - prefix_length - leading_zeroes - digits;
    if (!left && (!zero || precision >= 0)) __btrc_rt_pad(sink, ' ', padding);
    if (sign) __btrc_rt_put(sink, sign);
    while (*prefix) __btrc_rt_put(sink, *prefix++);
    if (!left && zero && precision < 0) __btrc_rt_pad(sink, '0', padding);
    __btrc_rt_pad(sink, '0', leading_zeroes);
    while (digits-- > 0) __btrc_rt_put(sink, reversed[digits]);
    if (left) __btrc_rt_pad(sink, ' ', padding);
}

"""
    + REFERENCE_FLOAT_FORMATTER
    + r"""
static size_t __btrc_fmt(char *out, size_t cap, const char *fmt, va_list ap) {
    __btrc_rt_sink sink = {out, cap, 0U};
    while (*fmt) {
        if (*fmt != '%') { __btrc_rt_put(&sink, *fmt++); continue; }
        fmt++;
        bool left = false, plus = false, space = false, alternate = false, zero = false;
        bool flags = true;
        while (flags) {
            switch (*fmt) {
            case '-': left = true; fmt++; break;
            case '+': plus = true; fmt++; break;
            case ' ': space = true; fmt++; break;
            case '#': alternate = true; fmt++; break;
            case '0': zero = true; fmt++; break;
            default: flags = false; break;
            }
        }
        int width = 0;
        if (*fmt == '*') {
            width = va_arg(ap, int);
            fmt++;
            if (width < 0) {
                left = true;
                width = width == INT_MIN ? INT_MAX : -width;
            }
        }
        else while (*fmt >= '0' && *fmt <= '9') {
            if (width <= (INT_MAX - 9) / 10) width = width * 10 + (*fmt - '0');
            fmt++;
        }
        int precision = -1;
        if (*fmt == '.') {
            fmt++; precision = 0;
            if (*fmt == '*') { precision = va_arg(ap, int); fmt++; }
            else while (*fmt >= '0' && *fmt <= '9') {
                if (precision <= (INT_MAX - 9) / 10) precision = precision * 10 + (*fmt - '0');
                fmt++;
            }
            if (precision < 0) precision = -1;
        }
        int length = 0;
        if (*fmt == 'h') { fmt++; length = *fmt == 'h' ? (fmt++, -2) : -1; }
        else if (*fmt == 'l') { fmt++; length = *fmt == 'l' ? (fmt++, 2) : 1; }
        else if (*fmt == 'j') { fmt++; length = 3; }
        else if (*fmt == 'z') { fmt++; length = 4; }
        else if (*fmt == 't') { fmt++; length = 5; }
        else if (*fmt == 'L') { fmt++; length = 6; }
        char spec = *fmt;
        if (!spec) break;
        fmt++;
        if (spec == 'd' || spec == 'i') {
            intmax_t signed_value = length == 1 ? (intmax_t)va_arg(ap, long)
                : length == 2 ? (intmax_t)va_arg(ap, long long)
                : length == 3 ? va_arg(ap, intmax_t)
                : length == 4 || length == 5 ? (intmax_t)va_arg(ap, ptrdiff_t)
                : (intmax_t)va_arg(ap, int);
            bool negative = signed_value < 0;
            uintmax_t magnitude = negative
                ? (uintmax_t)(-(signed_value + 1)) + 1U : (uintmax_t)signed_value;
            __btrc_rt_emit_integer(&sink, magnitude, negative, 10U, false,
                false, width, precision, zero, left, plus, space);
        } else if (spec == 'u' || spec == 'o' || spec == 'x' || spec == 'X') {
            uintmax_t value = length == 1 ? (uintmax_t)va_arg(ap, unsigned long)
                : length == 2 ? (uintmax_t)va_arg(ap, unsigned long long)
                : length == 3 ? va_arg(ap, uintmax_t)
                : length == 4 ? (uintmax_t)va_arg(ap, size_t)
                : length == 5 ? (uintmax_t)va_arg(ap, uintptr_t)
                : (uintmax_t)va_arg(ap, unsigned int);
            unsigned int base = spec == 'o' ? 8U : (spec == 'x' || spec == 'X' ? 16U : 10U);
            __btrc_rt_emit_integer(&sink, value, false, base, spec == 'X',
                alternate, width, precision, zero, left, false, false);
        } else if (spec == 'f' || spec == 'F' || spec == 'e' || spec == 'E'
                || spec == 'g' || spec == 'G') {
            long double value = length == 6 ? va_arg(ap, long double)
                                            : (long double)va_arg(ap, double);
            int real_precision = precision < 0 ? 6 : precision;
            if ((spec == 'g' || spec == 'G') && real_precision == 0) real_precision = 1;
            if (real_precision > 18) real_precision = 18;
            __btrc_rt_emit_real(&sink, value, spec, width, real_precision,
                zero, left, plus, space, alternate);
        } else if (spec == 'c') {
            int padding = width - 1;
            if (!left) __btrc_rt_pad(&sink, ' ', padding);
            __btrc_rt_put(&sink, (char)va_arg(ap, int));
            if (left) __btrc_rt_pad(&sink, ' ', padding);
        } else if (spec == 's') {
            const char *value = va_arg(ap, const char *);
            if (!value) value = "(null)";
            size_t length_value = strlen(value);
            if (precision >= 0 && length_value > (size_t)precision) length_value = (size_t)precision;
            int padding = length_value < (size_t)width ? width - (int)length_value : 0;
            if (!left) __btrc_rt_pad(&sink, ' ', padding);
            for (size_t i = 0; i < length_value; ++i) __btrc_rt_put(&sink, value[i]);
            if (left) __btrc_rt_pad(&sink, ' ', padding);
        } else if (spec == 'p') {
            uintptr_t value = (uintptr_t)va_arg(ap, void *);
            __btrc_rt_emit_integer(&sink, (uintmax_t)value, false, 16U, false,
                true, width, precision, zero, left, false, false);
        } else if (spec == '%') {
            __btrc_rt_put(&sink, '%');
        } else {
            __btrc_rt_put(&sink, '%');
            __btrc_rt_put(&sink, spec);
        }
    }
    if (out && cap) out[sink.pos < cap ? sink.pos : cap - 1U] = '\0';
    return sink.pos;
}
"""
)

__all__ = ["REFERENCE_FORMATTER"]
