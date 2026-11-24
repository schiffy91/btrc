#ifndef BTRC_EMBEDDED_WEB_HOST_H
#define BTRC_EMBEDDED_WEB_HOST_H
/* The GUI owns control layout, lifetimes and event delivery. An optional
 * embedded engine creates one such control and serves the IWebView operations.
 * Install a process-lifetime table before creating a web view. */
#include "../Shim/ShimWeb.h"
#include <stddef.h>

typedef struct BtrcEmbeddedWebBackend {
	BtrcShimControl* (*create)(unsigned int id);
	void (*serveDirectory)(BtrcShimControl*, const char*);
	void (*serveFiles)(BtrcShimControl*);
	void (*serveFile)(BtrcShimControl*, const char*, const unsigned char*, unsigned long long);
	void (*allowOrigin)(BtrcShimControl*, const char*);
	void (*load)(BtrcShimControl*, const char*);
	void (*post)(BtrcShimControl*, const char*);
} BtrcEmbeddedWebBackend;

typedef struct BtrcExternalControlMethods {
	void (*destroy)(void* state);
	void (*place)(void* state, int x, int y, int width, int height, bool visible, double scale);
	bool (*paint)(void* state, unsigned char* rgba, size_t stride, int width, int height);
	void (*pointer)(void* state, unsigned int type, double x, double y, unsigned int button, unsigned int modifiers);
	void (*scroll)(void* state, double x, double y, double dx, double dy, bool precise, unsigned int modifiers);
	void (*key)(void* state, unsigned int type, unsigned int key, unsigned int scancode, unsigned int modifiers, bool repeat);
	void (*text)(void* state, const char* utf8);
	void (*focus)(void* state, bool focused);
} BtrcExternalControlMethods;

void btrcShimRegisterWebBackend(const BtrcEmbeddedWebBackend* backend);

BtrcShimControl* btrcExternalControlCreate(unsigned int id, void* state, const BtrcExternalControlMethods* methods);
void* btrcExternalControlState(BtrcShimControl* control);
void btrcExternalControlMarkDirty(BtrcShimControl* control);
void btrcExternalControlPushText(BtrcShimControl* control, unsigned int type, int data, const char* text);
void btrcExternalControlRegisterPoller(int (*poll)(void* context), void* context);
#endif
