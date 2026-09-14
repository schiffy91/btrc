#ifndef TEST_WEBGPU_H
#define TEST_WEBGPU_H

#include <stddef.h>
#include <stdint.h>

typedef struct WGPUInstanceImpl* WGPUInstance;

typedef struct {
    uint64_t id;
} WGPUFuture;

typedef uint32_t WGPUBool;

typedef enum {
    WGPUWaitStatus_Success = 1,
    WGPUWaitStatus_TimedOut = 2,
    WGPUWaitStatus_Error = 3,
} WGPUWaitStatus;

typedef struct {
    WGPUFuture future;
    WGPUBool completed;
} WGPUFutureWaitInfo;

WGPUWaitStatus wgpuInstanceWaitAny(
    WGPUInstance instance, size_t future_count,
    WGPUFutureWaitInfo* futures, uint64_t timeout_ns);
void wgpuInstanceProcessEvents(WGPUInstance instance);

#endif
