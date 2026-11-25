#include "WebGPUImports.h"

#include <stdlib.h>

#ifdef WGPU_QUEUE_WORK_DONE_CALLBACK_INFO_INIT
typedef struct BtrcWGPUQueueWorkDoneTrampoline {
	BtrcWGPUQueueWorkDoneCallback callback;
	void *userdata1;
	void *userdata2;
} BtrcWGPUQueueWorkDoneTrampoline;

static void btrcWgpuQueueWorkDoneAdapter(
	WGPUQueueWorkDoneStatus status,
	WGPUStringView message,
	void *userdata1,
	void *userdata2
) {
	(void)message;
	(void)userdata2;
	BtrcWGPUQueueWorkDoneTrampoline *state = (BtrcWGPUQueueWorkDoneTrampoline *)userdata1;
	if (state == NULL) {
		return;
	}
	BtrcWGPUQueueWorkDoneCallback callback = state->callback;
	void *first = state->userdata1;
	void *second = state->userdata2;
	free(state);
	if (callback != NULL) {
		callback(status, first, second);
	}
}
#endif

WGPUFuture btrcWgpuQueueOnSubmittedWorkDone(WGPUQueue queue, BtrcWGPUQueueWorkDoneCallbackInfo callbackInfo) {
#ifdef WGPU_QUEUE_WORK_DONE_CALLBACK_INFO_INIT
	BtrcWGPUQueueWorkDoneTrampoline *state = (BtrcWGPUQueueWorkDoneTrampoline *)malloc(sizeof(*state));
	if (state == NULL) {
		if (callbackInfo.callback != NULL) {
			callbackInfo.callback(WGPUQueueWorkDoneStatus_Error, callbackInfo.userdata1, callbackInfo.userdata2);
		}
		WGPUFuture empty = {0};
		return empty;
	}
	state->callback = callbackInfo.callback;
	state->userdata1 = callbackInfo.userdata1;
	state->userdata2 = callbackInfo.userdata2;
	WGPUQueueWorkDoneCallbackInfo raw = {0};
	raw.mode = callbackInfo.mode;
	raw.callback = btrcWgpuQueueWorkDoneAdapter;
	raw.userdata1 = state;
	raw.userdata2 = NULL;
	return wgpuQueueOnSubmittedWorkDone(queue, raw);
#else
	WGPUQueueWorkDoneCallbackInfo raw = {0};
	raw.mode = callbackInfo.mode;
	raw.callback = callbackInfo.callback;
	raw.userdata1 = callbackInfo.userdata1;
	raw.userdata2 = callbackInfo.userdata2;
	return wgpuQueueOnSubmittedWorkDone(queue, raw);
#endif
}
