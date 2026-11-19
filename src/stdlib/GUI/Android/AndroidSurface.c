/* The WebGPU surface of an Android window's drawn content; ../Shim/ShimSurface.h is the contract. */
#include "../Shim/ShimSurface.h"
#include "AndroidShimPrivate.h"

#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <wgpu.h>

/* The system makes a window's surface in its own time, after the window is
 * on show: the program's thread waits for it here, briefly. */
enum { BTRC_ANDROID_SURFACE_MILLISECONDS = 5000 };

static WGPUInstance btrcAndroidInstance(WGPUInstanceBackend backends) {
	WGPUInstanceDescriptor descriptor;
	WGPUInstanceExtras extras;
	memset(&descriptor, 0, sizeof descriptor);
	memset(&extras, 0, sizeof extras);
	extras.chain.sType = (WGPUSType)WGPUSType_InstanceExtras;
	extras.backends = backends;
	descriptor.nextInChain = &extras.chain;
	return wgpuCreateInstance(&descriptor);
}

/* One graphics API a window: a native window is connected to the first that
 * makes a surface on it, and on older systems Vulkan does so the moment it
 * is asked, leaving none for OpenGL ES. Vulkan where the device has it,
 * OpenGL ES where it does not. */
WGPUInstance btrcShimCreateInstance(void) {
	WGPUInstance vulkan = btrcAndroidInstance(WGPUInstanceBackend_Vulkan);
	if (vulkan != NULL && wgpuInstanceEnumerateAdapters(vulkan, NULL, NULL) > 0u) { return vulkan; }
	if (vulkan != NULL) { wgpuInstanceRelease(vulkan); }
	return btrcAndroidInstance(WGPUInstanceBackend_GL);
}

WGPUSurface btrcShimWindowCreateSurface(BtrcShimWindow* window, WGPUInstance instance) {
	static jmethodID method;
	JNIEnv* env = btrcAndroidEnv();
	jclass shim = btrcAndroidShimClass();
	if (method == NULL) { method = btrcAndroidMethod(env, shim, "windowSurface", "(II)Landroid/view/Surface;"); }
	(*env)->PushLocalFrame(env, 8);
	jobject surface = (*env)->CallStaticObjectMethod(env, shim, method, (jint)window->id, (jint)BTRC_ANDROID_SURFACE_MILLISECONDS);
	ANativeWindow* native = btrcAndroidFailed(env) || surface == NULL ? NULL : ANativeWindow_fromSurface(env, surface);
	(*env)->PopLocalFrame(env, NULL);
	if (native == NULL) { btrcAndroidFail("the window has no surface: it is not on show"); return NULL; }
	btrcAndroidReleaseNativeWindow(window);
	window->native = native;
	WGPUSurfaceDescriptor descriptor;
	WGPUSurfaceSourceAndroidNativeWindow source;
	memset(&descriptor, 0, sizeof descriptor);
	memset(&source, 0, sizeof source);
	source.chain.sType = WGPUSType_SurfaceSourceAndroidNativeWindow;
	source.window = native;
	descriptor.nextInChain = &source.chain;
	return wgpuInstanceCreateSurface(instance, &descriptor);
}

void btrcAndroidReleaseNativeWindow(BtrcShimWindow* window) {
	if (window->native != NULL) { ANativeWindow_release(window->native); window->native = NULL; }
}
