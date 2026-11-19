/* The WebGPU surface of a Win32 window's drawn content; ../Shim/ShimSurface.h is the contract. */
#include "../Shim/ShimSurface.h"
#include <string.h>

/* The window's content window and its module, as Win32ShimPrivate.h has
 * them: this file names WebGPU and nothing of Win32. */
void* btrcWinContentWindow(BtrcShimWindow* window);
void* btrcWinContentModule(void);

WGPUInstance btrcShimCreateInstance(void) { return wgpuCreateInstance(NULL); }

WGPUSurface btrcShimWindowCreateSurface(BtrcShimWindow* window, WGPUInstance instance) {
	WGPUSurfaceDescriptor descriptor;
	WGPUSurfaceSourceWindowsHWND source;
	memset(&descriptor, 0, sizeof descriptor);
	memset(&source, 0, sizeof source);
	source.chain.sType = WGPUSType_SurfaceSourceWindowsHWND;
	source.hinstance = btrcWinContentModule();
	source.hwnd = btrcWinContentWindow(window);
	if (source.hwnd == NULL) { return NULL; }
	descriptor.nextInChain = &source.chain;
	return wgpuInstanceCreateSurface(instance, &descriptor);
}
