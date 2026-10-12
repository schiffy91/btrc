/* One C surface whose layout depends on the target's data model: `long`,
 * `wchar_t` and `size_t` widths, `_Bool`, a nested array, an enum, a callback
 * typedef, a variadic function and a by-value record result. It includes only
 * the SDK's own headers, so each target reads it through that target's SDK. */
#ifndef TARGET_IMPORT_H
#define TARGET_IMPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <wchar.h>

typedef enum TargetMode { TARGET_MODE_OFF = 0, TARGET_MODE_ON = 3 } TargetMode;

typedef struct TargetRecord {
    long count;
    wchar_t symbol;
    size_t length;
    bool ready;
    int values[4];
} TargetRecord;

typedef void (*TargetCallback)(void* context, int value);

int targetSum(int count, ...);
TargetRecord targetMake(long count, TargetMode mode);
long targetCount(const TargetRecord* record);

#endif
