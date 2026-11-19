#ifndef BTRC_SHIM_WEB_H
#define BTRC_SHIM_WEB_H
/* The provider's web view: a WebKitGTK view the shim owns, placed among the
 * window's other controls like any of them (GtkControls.h). It is bound and
 * linked only by programs that import the web view, which is why it is a
 * module of its own: WebKitGTK is a large library.
 *
 * A web view serves one bundle of files under the private origin
 * app://bundle/ and loads nothing from anywhere else, unless the program
 * allows an origin. Its storage is not kept. The page and the program
 * exchange JSON messages; neither calls into the other. */
#include "ShimControls.h"

/* A BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION event's data1: what became of a
 * navigation. */
enum BtrcShimWebNavigation {
	/* Inside the bundle or to an allowed origin: it went ahead. */
	BTRC_SHIM_WEB_NAVIGATION_ALLOWED = 0,
	/* Somewhere else, and not a person's doing: nothing happened. */
	BTRC_SHIM_WEB_NAVIGATION_REFUSED = 1,
	/* Somewhere else, by a person's click: the system's handler for the
	 * address (a browser) was asked to open it. */
	BTRC_SHIM_WEB_NAVIGATION_HANDED_TO_SYSTEM = 2
};

/* A new web view showing nothing, or NULL. BTRC_SHIM_EVENT_CONTROL_WEB_MESSAGE
 * carries, as `text`, the JSON of a value the page passed to
 * window.btrc.post; BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION carries the address
 * of a navigation as `text` and what became of it as data1. */
BtrcShimControl* btrcShimWebCreate(unsigned int id);
/* The bundle is this directory's files, */
void btrcShimWebServeDirectory(BtrcShimControl* web, const char* directory);
/* or these files, each added under its path from the origin (copied). Either
 * replaces what was served before. */
void btrcShimWebServeFiles(BtrcShimControl* web);
void btrcShimWebServeFile(BtrcShimControl* web, const char* path, const unsigned char* bytes, unsigned long long length);
/* Let pages load from, and navigate to, this origin too ("https://host"). */
void btrcShimWebAllowOrigin(BtrcShimControl* web, const char* origin);
/* Show the bundle's file at this path from the origin. */
void btrcShimWebLoad(BtrcShimControl* web, const char* entryPath);
/* Hand the page a JSON value: window.btrc.onMessage is called with it, once
 * the page has loaded. */
void btrcShimWebPost(BtrcShimControl* web, const char* json);
#endif
