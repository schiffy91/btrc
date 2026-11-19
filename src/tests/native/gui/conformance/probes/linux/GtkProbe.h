#ifndef BTRC_CONFORMANCE_GTK_PROBE_H
#define BTRC_CONFORMANCE_GTK_PROBE_H
/* ConformanceProbe.h for one window of the GTK provider, named by the shim's
 * id for it and its title. Each returns 1 when the input was sent. */
int gtkProbeMove(unsigned int window, const char *title, double x, double y);
int gtkProbeButton(unsigned int window, const char *title, double x, double y, int down);
int gtkProbeWheel(unsigned int window, const char *title, double x, double y, double deltaX, double deltaY);
int gtkProbeKey(unsigned int window, const char *title, int key);
int gtkProbeText(unsigned int window, const char *title, const char *text);
int gtkProbeClose(unsigned int window, const char *title);
/* 1 when the session gives a new window the whole screen. */
int gtkProbeFillsScreen(void);
#endif
