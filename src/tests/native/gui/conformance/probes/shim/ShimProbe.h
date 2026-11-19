#ifndef BTRC_CONFORMANCE_SHIM_PROBE_H
#define BTRC_CONFORMANCE_SHIM_PROBE_H
/* ConformanceProbe.h for one window of the shim provider, named by the
 * shim's id for it and its title. Each returns 1 when the input was sent. */
int shimProbeMove(unsigned int window, const char *title, double x, double y);
int shimProbeButton(unsigned int window, const char *title, double x, double y, int down);
int shimProbeWheel(unsigned int window, const char *title, double x, double y, double deltaX, double deltaY);
int shimProbeKey(unsigned int window, const char *title, int key);
int shimProbeText(unsigned int window, const char *title, const char *text);
int shimProbeClose(unsigned int window, const char *title);
/* 1 when the session gives a new window the whole screen. */
int shimProbeFillsScreen(void);
/* 1 when a window keeps the whole screen whatever it asks for. */
int shimProbeKeepsScreen(void);
#endif
