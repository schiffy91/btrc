#ifndef BTRC_SHARED_FRAME_DXGI_H
#define BTRC_SHARED_FRAME_DXGI_H
#include <windows.h>

/* One message per completed texture. Create the named NT handle with
 * DXGI_SHARED_RESOURCE_READ and a unique GUID. The producer releases key 1
 * after rendering. Keep the handle open until a one-byte response arrives.
 * A response of 1 means presentation succeeded; the receiver releases key 0
 * after it has queued its copy. Discard a rejected texture. Use the same
 * adapter until the receiver opens a new session. */
typedef struct BtrcDxgiFrameMessage {
	DWORD version;
	LUID adapter;
	GUID resource;
} BtrcDxgiFrameMessage;

#define BTRC_DXGI_FRAME_VERSION 1u
#define BTRC_DXGI_RESOURCE_PREFIX L"Local\\BtrcFrame-"
#endif
