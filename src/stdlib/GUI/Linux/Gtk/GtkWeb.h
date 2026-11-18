#ifndef BTRC_GTK_WEB_H
#define BTRC_GTK_WEB_H
/* The provider's web view: a WebKitGTK view the shim owns, placed among the
 * window's other controls like any of them (GtkControls.h). It is bound and
 * linked only by programs that import the web view, which is why it is a
 * module of its own: WebKitGTK is a large library.
 *
 * A web view serves one bundle of files under the private origin
 * app://bundle/ and loads nothing from anywhere else, unless the program
 * allows an origin. Its storage is not kept. The page and the program
 * exchange JSON messages; neither calls into the other. */
#include "GtkControls.h"

/* A BTRC_GTK_EVENT_CONTROL_WEB_NAVIGATION event's data1: what became of a
 * navigation. */
enum BtrcGtkWebNavigation {
	/* Inside the bundle or to an allowed origin: it went ahead. */
	BTRC_GTK_WEB_NAVIGATION_ALLOWED = 0,
	/* Somewhere else, and not a person's doing: nothing happened. */
	BTRC_GTK_WEB_NAVIGATION_REFUSED = 1,
	/* Somewhere else, by a person's click: the system's handler for the
	 * address (a browser) was asked to open it. */
	BTRC_GTK_WEB_NAVIGATION_HANDED_TO_SYSTEM = 2
};

/* A new web view showing nothing, or NULL. BTRC_GTK_EVENT_CONTROL_WEB_MESSAGE
 * carries, as `text`, the JSON of a value the page passed to
 * window.btrc.post; BTRC_GTK_EVENT_CONTROL_WEB_NAVIGATION carries the address
 * of a navigation as `text` and what became of it as data1. */
BtrcGtkControl* btrcGtkWebCreate(unsigned int id);
/* The bundle is this directory's files, */
void btrcGtkWebServeDirectory(BtrcGtkControl* web, const char* directory);
/* or these files, each added under its path from the origin (copied). Either
 * replaces what was served before. */
void btrcGtkWebServeFiles(BtrcGtkControl* web);
void btrcGtkWebServeFile(BtrcGtkControl* web, const char* path, const unsigned char* bytes, unsigned long long length);
/* Let pages load from, and navigate to, this origin too ("https://host"). */
void btrcGtkWebAllowOrigin(BtrcGtkControl* web, const char* origin);
/* Show the bundle's file at this path from the origin. */
void btrcGtkWebLoad(BtrcGtkControl* web, const char* entryPath);
/* Hand the page a JSON value: window.btrc.onMessage is called with it, once
 * the page has loaded. */
void btrcGtkWebPost(BtrcGtkControl* web, const char* json);
#endif
