#pragma once

#include <webgpu.h>

typedef void (*BtrcWGPUQueueWorkDoneCallback)(WGPUQueueWorkDoneStatus status, void *userdata1, void *userdata2);

typedef struct BtrcWGPUQueueWorkDoneCallbackInfo {
	WGPUCallbackMode mode;
	BtrcWGPUQueueWorkDoneCallback callback;
	void *userdata1;
	void *userdata2;
} BtrcWGPUQueueWorkDoneCallbackInfo;

WGPUFuture btrcWgpuQueueOnSubmittedWorkDone(WGPUQueue queue, BtrcWGPUQueueWorkDoneCallbackInfo callbackInfo);
