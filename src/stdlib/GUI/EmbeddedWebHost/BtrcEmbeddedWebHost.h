#ifndef BTRC_EMBEDDED_WEB_HOST_H
#define BTRC_EMBEDDED_WEB_HOST_H
/* The GUI owns control layout, lifetimes and event delivery. An optional
 * embedded engine creates one such control and serves the IWebView operations.
 * Install a process-lifetime table before creating a web view. */
#include "../Shim/ShimWeb.h"

typedef struct BtrcEmbeddedWebBackend {
	BtrcShimControl* (*create)(unsigned int id);
	void (*serveDirectory)(BtrcShimControl*, const char*);
	void (*serveFiles)(BtrcShimControl*);
	void (*serveFile)(BtrcShimControl*, const char*, const unsigned char*, unsigned long long);
	void (*allowOrigin)(BtrcShimControl*, const char*);
	void (*load)(BtrcShimControl*, const char*);
	void (*post)(BtrcShimControl*, const char*);
} BtrcEmbeddedWebBackend;

void btrcShimRegisterWebBackend(const BtrcEmbeddedWebBackend* backend);

struct _GtkWidget;
BtrcShimControl* btrcGtkControlNew(unsigned int id, struct _GtkWidget* widget);
struct _GtkWidget* btrcGtkControlWidget(BtrcShimControl* control);
void btrcGtkControlPushText(BtrcShimControl* control, unsigned int type, int data, const char* text);
#endif
