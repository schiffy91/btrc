#ifndef UI2_LINUX_RESOURCE_LIFETIME_H
#define UI2_LINUX_RESOURCE_LIFETIME_H
void ui2ResourceBegin(int cycle);
void ui2ResourceEnd(int cycle);
void ui2ResourcePointer(unsigned int window, float x, float y);
int ui2ResourceCursorCount(int text);
#endif
