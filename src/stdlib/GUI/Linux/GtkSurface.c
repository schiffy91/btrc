/* The WebGPU surface of a GTK window's drawn content; ShimSurface.h is the contract. */
#include "../Shim/ShimSurface.h"
#include <stdint.h>
#include <string.h>

/* What the window's surface is made on, as GtkShimPrivate.h declares it:
 * this file names WebGPU and nothing of GTK. */
bool btrcGtkEnsureSurface(BtrcShimWindow* window);
void* btrcGtkWindowWaylandDisplay(BtrcShimWindow* window);
void* btrcGtkWindowWaylandSurface(BtrcShimWindow* window);
void* btrcGtkWindowX11Display(BtrcShimWindow* window);
unsigned long btrcGtkWindowX11Window(BtrcShimWindow* window);

WGPUInstance btrcShimCreateInstance(void) { return wgpuCreateInstance(NULL); }

WGPUSurface btrcShimWindowCreateSurface(BtrcShimWindow* window, WGPUInstance instance) {
	if (!btrcGtkEnsureSurface(window)) { return NULL; }
	WGPUSurfaceDescriptor descriptor;
	WGPUSurfaceSourceWaylandSurface wayland;
	WGPUSurfaceSourceXlibWindow xlib;
	memset(&descriptor, 0, sizeof descriptor);
	memset(&wayland, 0, sizeof wayland);
	memset(&xlib, 0, sizeof xlib);
	void* waylandDisplay = btrcGtkWindowWaylandDisplay(window);
	void* waylandSurface = btrcGtkWindowWaylandSurface(window);
	if (waylandDisplay != NULL && waylandSurface != NULL) {
		wayland.chain.sType = WGPUSType_SurfaceSourceWaylandSurface;
		wayland.display = waylandDisplay;
		wayland.surface = waylandSurface;
		descriptor.nextInChain = &wayland.chain;
	} else {
		void* xDisplay = btrcGtkWindowX11Display(window);
		unsigned long xWindow = btrcGtkWindowX11Window(window);
		if (xDisplay == NULL || xWindow == 0ul) { return NULL; }
		xlib.chain.sType = WGPUSType_SurfaceSourceXlibWindow;
		xlib.display = xDisplay;
		xlib.window = (uint64_t)xWindow;
		descriptor.nextInChain = &xlib.chain;
	}
	return wgpuInstanceCreateSurface(instance, &descriptor);
}
