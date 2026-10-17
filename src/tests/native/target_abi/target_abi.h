/* The C side of the target ABI fixture (platform-target-contract.md section 7).
 * Every declaration here depends on the target's data model: the widths and
 * signedness of long, wchar_t and char, record padding and packing, by-value
 * records, a variadic call and a callback with a BTRC context. It includes
 * only freestanding headers, so each target row reads it without an SDK. */
#ifndef TARGET_ABI_H
#define TARGET_ABI_H

#include <stdbool.h>
#include <stddef.h>

typedef enum TargetAbiColor { TARGET_ABI_RED = 1, TARGET_ABI_GREEN = 2, TARGET_ABI_BLUE = 4 } TargetAbiColor;

/* Mixed widths: the padding before almost every field differs between the
 * LP64 and LLP64 data models and between the long double formats. */
typedef struct TargetAbiMixed {
    char tag;
    long count;
    signed char delta;
    unsigned long mask;
    bool ready;
    size_t length;
    wchar_t symbol;
    ptrdiff_t distance;
    double ratio;
    TargetAbiColor color;
} TargetAbiMixed;

/* No padding at all: every field is at its byte offset in declaration order. */
#pragma pack(push, 1)
typedef struct TargetAbiPacked {
    char tag;
    int value;
    short half;
    long long wide;
} TargetAbiPacked;
#pragma pack(pop)

typedef int (*TargetAbiVisitor)(void* context, long value);

long targetAbiLongEcho(long value);
long targetAbiLongMax(void);
unsigned long targetAbiUnsignedLongMax(void);
size_t targetAbiMixedSize(void);
ptrdiff_t targetAbiDistance(const unsigned char* first, const unsigned char* last);
int targetAbiWideEcho(int letter);
bool targetAbiNot(bool value);
bool targetAbiCharIsSigned(void);
signed char targetAbiNegate(signed char value);
double targetAbiLongDoubleThird(double value);
TargetAbiMixed targetAbiMakeMixed(long count);
bool targetAbiCheckMixed(TargetAbiMixed value);
TargetAbiPacked targetAbiMakePacked(int value);
long long targetAbiPackedSum(TargetAbiPacked value);
long targetAbiCount(const TargetAbiMixed* record);
int targetAbiSum(int count, ...);
int targetAbiVisit(TargetAbiVisitor visitor, void* context, long value);
int targetAbiColorValue(TargetAbiColor color);

#endif
