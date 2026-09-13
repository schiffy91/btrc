#include "CompletionProbe.h"
#include <assert.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <webgpu.h>

/* Interpose only the test executable's SDK calls. Real WebGPU creates every
 * resource; this driver delays delivery and counts the caller's native claims. */
#define NATIVE_CALL(type, name) \
    type native; \
    void* symbol = dlsym(RTLD_NEXT, #name); \
    _Static_assert(sizeof(native) == sizeof(symbol), "macOS function pointer ABI"); \
    assert(symbol); \
    memcpy(&native, &symbol, sizeof(native))

static int delayed_stage;
static int adapter_claims;
static int device_claims;
static int buffer_claims;
static int pending_stage;
static WGPUAdapter pending_adapter;
static WGPUDevice pending_device;
static WGPURequestAdapterCallbackInfo adapter_delivery;
static WGPURequestDeviceCallbackInfo device_delivery;
static WGPUPopErrorScopeCallbackInfo validation_delivery;
static WGPUBufferMapCallbackInfo mapping_delivery;
static WGPUPopErrorScopeStatus validation_status;
static WGPUErrorType validation_error;
static WGPUMapAsyncStatus mapping_status;

void probeDelayCompletions(int stage) {
    assert(!pending_stage && stage >= 0 && stage <= 4);
    delayed_stage = stage;
}

int probePendingCompletions(void) { return pending_stage != 0; }
int probeAdapterClaims(void) { return adapter_claims; }
int probeDeviceClaims(void) { return device_claims; }
int probeBufferClaims(void) { return buffer_claims; }

static void validation_ready(WGPUPopErrorScopeStatus status, WGPUErrorType type, WGPUStringView message, void* first, void* second) {
    (void)second;
    WGPUPopErrorScopeCallbackInfo delivery = *(WGPUPopErrorScopeCallbackInfo*)first;
    free(first);
    if (delayed_stage == 3) {
        assert(!pending_stage);
        pending_stage = 3;
        validation_status = status;
        validation_error = type;
        validation_delivery = delivery;
    } else {
        delivery.callback(status, type, message, delivery.userdata1, delivery.userdata2);
    }
}

static void mapping_ready(WGPUMapAsyncStatus status, WGPUStringView message, void* first, void* second) {
    (void)second;
    WGPUBufferMapCallbackInfo delivery = *(WGPUBufferMapCallbackInfo*)first;
    free(first);
    if (delayed_stage == 4) {
        assert(!pending_stage);
        pending_stage = 4;
        mapping_status = status;
        mapping_delivery = delivery;
    } else {
        delivery.callback(status, message, delivery.userdata1, delivery.userdata2);
    }
}

WGPUFuture wgpuDevicePopErrorScope(WGPUDevice device, WGPUPopErrorScopeCallbackInfo info) {
    NATIVE_CALL(WGPUProcDevicePopErrorScope, wgpuDevicePopErrorScope);
    assert(!pending_stage);
    WGPUPopErrorScopeCallbackInfo* delivery = malloc(sizeof(*delivery));
    assert(delivery);
    *delivery = info;
    info.callback = validation_ready;
    info.userdata1 = delivery; info.userdata2 = NULL;
    return native(device, info);
}

WGPUFuture wgpuBufferMapAsync(WGPUBuffer buffer, WGPUMapMode mode, size_t offset, size_t size, WGPUBufferMapCallbackInfo info) {
    NATIVE_CALL(WGPUProcBufferMapAsync, wgpuBufferMapAsync);
    assert(!pending_stage);
    WGPUBufferMapCallbackInfo* delivery = malloc(sizeof(*delivery));
    assert(delivery);
    *delivery = info;
    info.callback = mapping_ready;
    info.userdata1 = delivery; info.userdata2 = NULL;
    return native(buffer, mode, offset, size, info);
}

WGPUBuffer wgpuDeviceCreateBuffer(WGPUDevice device, const WGPUBufferDescriptor* descriptor) {
    NATIVE_CALL(WGPUProcDeviceCreateBuffer, wgpuDeviceCreateBuffer);
    WGPUBuffer buffer = native(device, descriptor);
    if (buffer) { buffer_claims++; }
    return buffer;
}

void wgpuBufferRelease(WGPUBuffer buffer) {
    NATIVE_CALL(WGPUProcBufferRelease, wgpuBufferRelease);
    assert(buffer && buffer_claims > 0); buffer_claims--; native(buffer);
}

static void adapter_ready(WGPURequestAdapterStatus status, WGPUAdapter adapter, WGPUStringView message, void* first, void* second) {
    (void)first; (void)second;
    assert(status == WGPURequestAdapterStatus_Success && adapter);
    adapter_claims++;
    if (delayed_stage == 1) {
        assert(!pending_stage);
        pending_stage = 1;
        pending_adapter = adapter;
    } else {
        adapter_delivery.callback(status, adapter, message, adapter_delivery.userdata1, adapter_delivery.userdata2);
    }
}

static void device_ready(WGPURequestDeviceStatus status, WGPUDevice device, WGPUStringView message, void* first, void* second) {
    (void)first; (void)second;
    assert(status == WGPURequestDeviceStatus_Success && device);
    device_claims++;
    if (delayed_stage == 2) {
        assert(!pending_stage);
        pending_stage = 2;
        pending_device = device;
    } else {
        device_delivery.callback(status, device, message, device_delivery.userdata1, device_delivery.userdata2);
    }
}

WGPUFuture wgpuInstanceRequestAdapter(WGPUInstance instance, const WGPURequestAdapterOptions* options, WGPURequestAdapterCallbackInfo info) {
    NATIVE_CALL(WGPUProcInstanceRequestAdapter, wgpuInstanceRequestAdapter);
    assert(!pending_stage);
    adapter_delivery = info;
    info.callback = adapter_ready;
    info.userdata1 = NULL; info.userdata2 = NULL;
    return native(instance, options, info);
}

WGPUFuture wgpuAdapterRequestDevice(WGPUAdapter adapter, const WGPUDeviceDescriptor* descriptor, WGPURequestDeviceCallbackInfo info) {
    NATIVE_CALL(WGPUProcAdapterRequestDevice, wgpuAdapterRequestDevice);
    assert(!pending_stage);
    device_delivery = info;
    info.callback = device_ready;
    info.userdata1 = NULL; info.userdata2 = NULL;
    return native(adapter, descriptor, info);
}

void probeDeliverCompletion(void) {
    static const char text[] = "delayed real WebGPU result";
    const WGPUStringView message = {text, sizeof(text) - 1};
    int stage = pending_stage;
    pending_stage = 0;
    if (stage == 1) {
        WGPUAdapter adapter = pending_adapter;
        pending_adapter = NULL;
        adapter_delivery.callback(WGPURequestAdapterStatus_Success, adapter, message, adapter_delivery.userdata1, adapter_delivery.userdata2);
    } else if (stage == 2) {
        WGPUDevice device = pending_device;
        pending_device = NULL;
        device_delivery.callback(WGPURequestDeviceStatus_Success, device, message, device_delivery.userdata1, device_delivery.userdata2);
    } else if (stage == 3) {
        validation_delivery.callback(validation_status, validation_error, message, validation_delivery.userdata1, validation_delivery.userdata2);
    } else {
        assert(stage == 4);
        mapping_delivery.callback(mapping_status, message, mapping_delivery.userdata1, mapping_delivery.userdata2);
    }
}

void wgpuAdapterAddRef(WGPUAdapter adapter) {
    NATIVE_CALL(WGPUProcAdapterAddRef, wgpuAdapterAddRef);
    assert(adapter); adapter_claims++; native(adapter);
}

void wgpuAdapterRelease(WGPUAdapter adapter) {
    NATIVE_CALL(WGPUProcAdapterRelease, wgpuAdapterRelease);
    assert(adapter && adapter_claims > 0); adapter_claims--; native(adapter);
}

void wgpuDeviceAddRef(WGPUDevice device) {
    NATIVE_CALL(WGPUProcDeviceAddRef, wgpuDeviceAddRef);
    assert(device); device_claims++; native(device);
}

void wgpuDeviceRelease(WGPUDevice device) {
    NATIVE_CALL(WGPUProcDeviceRelease, wgpuDeviceRelease);
    assert(device && device_claims > 0); device_claims--; native(device);
}
