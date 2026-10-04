#ifndef BTRC_SHELL_PROBE_H
#define BTRC_SHELL_PROBE_H
/* Test-only ABI. Coordinates are content-local logical points, from top left.
 * focus: 0 unknown/none, 1 text editor, 2 button. Native counts exclude
 * process-global toolkit objects. Linux has one native window and drawn views.
 * JSON describes observations; an absent accessibility bridge is never a tree. */
void shellProbeClick(double x, double y);
void shellProbeTab(void);
void shellProbeText(void);
void shellProbeEnter(void);
void shellProbeScroll(void);
void shellProbeClose(void);
int shellProbeFocus(void);
int shellProbeNativeCount(void);
void shellProbeObserve(void);
void shellProbeDump(void);
void shellStateCommit(const char *directory, int sequence);
void shellStateCheckpoint(const char *directory, const char *draft, double anchor, int commits);
int shellStateRestore(const char *directory);
#endif
