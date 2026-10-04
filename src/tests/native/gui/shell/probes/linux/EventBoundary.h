#ifndef BTRC_TEST_EVENT_BOUNDARY_H
#define BTRC_TEST_EVENT_BOUNDARY_H
void eventBoundaryArm(unsigned int window);
int eventBoundaryQueued(void);
int eventBoundaryLatest(void);
void eventBoundaryClose(unsigned int window);
void eventBoundaryDisarm(void);
#endif
