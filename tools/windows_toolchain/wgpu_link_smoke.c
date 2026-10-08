/* Link/instance/callback evidence only. No rendering or GPU performance claim. */
#include <stdio.h>
#include <time.h>
#include <webgpu.h>
#ifdef _WIN32
#include <windows.h>
#endif

struct Request {
    int completed;
    WGPURequestAdapterStatus status;
    WGPUAdapter adapter;
};

static void adapter_ready(WGPURequestAdapterStatus status, WGPUAdapter adapter,
                          WGPUStringView message, void *userdata1, void *userdata2) {
    struct Request *request = userdata1;
    (void)message;
    (void)userdata2;
    request->status = status;
    request->adapter = adapter;
    request->completed = 1;
}

int main(void) {
    WGPUInstanceDescriptor descriptor = {0};
    WGPUInstance instance = wgpuCreateInstance(&descriptor);
    if (instance == NULL) {
        fprintf(stderr, "wgpuCreateInstance returned NULL\n");
        return 1;
    }
    struct Request request = {0};
    WGPURequestAdapterCallbackInfo callback = {0};
    callback.mode = WGPUCallbackMode_AllowProcessEvents;
    callback.callback = adapter_ready;
    callback.userdata1 = &request;
    (void)wgpuInstanceRequestAdapter(instance, NULL, callback);
    time_t started = time(NULL);
    while (!request.completed && difftime(time(NULL), started) < 10.0) {
        wgpuInstanceProcessEvents(instance);
#ifdef _WIN32
        Sleep(10);
#endif
    }
    printf("{\"instance_created\":true,\"callback_returned\":%s,\"adapter_present\":%s,\"adapter_status\":%d}\n",
           request.completed ? "true" : "false", request.adapter != NULL ? "true" : "false", (int)request.status);
    if (request.adapter != NULL) wgpuAdapterRelease(request.adapter);
    wgpuInstanceRelease(instance);
    return request.completed ? 0 : 2;
}
