/* The C side of the target ABI fixture: each function exercises one data-model
 * fact on the target's own C compiler. */
#include "target_abi.h"

#include <limits.h>
#include <stdarg.h>

long targetAbiLongEcho(long value) { return value; }

long targetAbiLongMax(void) { return LONG_MAX; }

unsigned long targetAbiUnsignedLongMax(void) { return ULONG_MAX; }

size_t targetAbiMixedSize(void) { return sizeof(TargetAbiMixed); }

ptrdiff_t targetAbiDistance(const unsigned char* first, const unsigned char* last) { return last - first; }

int targetAbiWideEcho(int letter) {
    wchar_t wide = (wchar_t)letter;
    return (int)wide;
}

bool targetAbiNot(bool value) { return !value; }

bool targetAbiCharIsSigned(void) { return CHAR_MIN < 0; }

signed char targetAbiNegate(signed char value) { return (signed char)-value; }

double targetAbiLongDoubleThird(double value) {
    long double wide = (long double)value;
    return (double)(wide / 3.0L);
}

TargetAbiMixed targetAbiMakeMixed(long count) {
    TargetAbiMixed value = {0};
    value.tag = 'm';
    value.count = count;
    value.delta = -7;
    value.mask = ULONG_MAX;
    value.ready = true;
    value.length = sizeof(TargetAbiMixed);
    value.symbol = L'Z';
    value.distance = -2;
    value.ratio = 0.5;
    value.color = TARGET_ABI_GREEN;
    return value;
}

bool targetAbiCheckMixed(TargetAbiMixed value) {
    return value.tag == 'b' && value.count == -40 && value.delta == -3 && value.mask == ULONG_MAX / 2 && !value.ready &&
           value.length == sizeof(TargetAbiMixed) && value.symbol == L'Z' && value.distance == -2 && value.ratio == 0.25 &&
           value.color == TARGET_ABI_BLUE;
}

TargetAbiPacked targetAbiMakePacked(int value) {
    TargetAbiPacked packed;
    packed.tag = 'p';
    packed.value = value;
    packed.half = (short)(value / 2);
    packed.wide = (long long)value * 1000000000LL;
    return packed;
}

long long targetAbiPackedSum(TargetAbiPacked value) { return (long long)value.tag + value.value + value.half + value.wide; }

long targetAbiCount(const TargetAbiMixed* record) { return record == NULL ? -1 : record->count; }

int targetAbiSum(int count, ...) {
    va_list arguments;
    va_start(arguments, count);
    int total = 0;
    for (int index = 0; index < count; index++) {
        total += va_arg(arguments, int);
    }
    va_end(arguments);
    return total;
}

int targetAbiVisit(TargetAbiVisitor visitor, void* context, long value) {
    return visitor(context, value) + visitor(context, value + 1);
}

int targetAbiColorValue(TargetAbiColor color) { return (int)color; }
