#ifndef BTRC_CONFORMANCE_MODAL_PROBE_H
#define BTRC_CONFORMANCE_MODAL_PROBE_H
/* A person's answer to a modal window: an alert or a chooser runs a loop of
 * its own, so the program that opened it cannot press its keys. A helper
 * thread does, with the same real input the rest of the probe sends
 * (RealInput.h): it presses one key again and again, to whatever window is
 * in front, until it is told the modal has returned. */

/* Start pressing `key` (a ConformanceKey), first after `milliseconds`.
 * 1 when the helper started; 0 when the session has no real input. */
int modalProbeAnswer(int key, int milliseconds);
/* The modal returned: stop pressing. */
void modalProbeDone(void);
/* 1 where the platform has a folder chooser that names a path. */
int modalProbeHasFolderChooser(void);
#endif
