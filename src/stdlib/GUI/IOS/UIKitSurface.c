/* The WebGPU surface of a UIKit window's drawn content; ../Shim/ShimSurface.h is the contract. */
#include "../Shim/ShimSurface.h"
#include <string.h>

/* The CAMetalLayer of the window's content view, as UIKitShim.m has it: this
 * file names WebGPU and nothing of UIKit. */
void* btrcUIKitContentLayer(BtrcShimWindow* window);

/* Metal is the one graphics API here, on a device and in the simulator. */
WGPUInstance btrcShimCreateInstance(void) { return wgpuCreateInstance(NULL); }

WGPUSurface btrcShimWindowCreateSurface(BtrcShimWindow* window, WGPUInstance instance) {
	WGPUSurfaceDescriptor descriptor;
	WGPUSurfaceSourceMetalLayer source;
	memset(&descriptor, 0, sizeof descriptor);
	memset(&source, 0, sizeof source);
	source.chain.sType = WGPUSType_SurfaceSourceMetalLayer;
	source.layer = btrcUIKitContentLayer(window);
	if (source.layer == NULL) { return NULL; }
	descriptor.nextInChain = &source.chain;
	return wgpuInstanceCreateSurface(instance, &descriptor);
}
