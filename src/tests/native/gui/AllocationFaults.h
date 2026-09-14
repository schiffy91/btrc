#ifndef GUI_SURFACE_ALLOCATION_FAULTS_H
#define GUI_SURFACE_ALLOCATION_FAULTS_H
#include <stdlib.h>

void guiFailAllocation(int countdown);
void* guiSurfaceCalloc(size_t count, size_t size);

#define calloc guiSurfaceCalloc
#endif
