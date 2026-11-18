#ifndef BTRC_TEST_LINUX_PLACEMENT_H
#define BTRC_TEST_LINUX_PLACEMENT_H
/* Native fixture instrumentation only: what the provider handed to GTK. */
/* How many controls the latest placement pass placed. */
int placementPlaced(void);
/* How many placement passes there have been. */
int placementPasses(void);
/* How many frames were presented, on the surface or as pictures. */
int placementFrames(void);
#endif
