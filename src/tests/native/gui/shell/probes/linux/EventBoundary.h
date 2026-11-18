#ifndef BTRC_TEST_EVENT_BOUNDARY_H
#define BTRC_TEST_EVENT_BOUNDARY_H
/* The burst fixture's observer. It queues events for one window through the
 * provider's own queue, each key carrying an ordinal, and watches the queue
 * being polled and frames being presented. */
void eventBoundaryArm(unsigned int window);
/* One key event: `ordinal` is what eventBoundaryLatest reports when it is polled. */
void eventBoundaryKey(unsigned int window, int ordinal, int down);
/* A text field's control reporting `text` as its edited text. */
void eventBoundaryText(unsigned int window, unsigned int control, const char *text);
void eventBoundaryClose(unsigned int window);
int eventBoundaryQueued(void);
int eventBoundaryLatest(void);
int eventBoundaryFrames(void);
void eventBoundaryDisarm(void);
int eventBoundaryAccepted(void);
int eventBoundaryRejected(void);
#endif
