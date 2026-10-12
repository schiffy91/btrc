#ifndef BTRC_UI2_APPLICATION_QUIT_FAULTS_H
#define BTRC_UI2_APPLICATION_QUIT_FAULTS_H
#include <stdbool.h>
bool ui2ArmQuitPublisherFault(void);
void ui2DisarmQuitPublisherFault(void);
int ui2QuitPublisherFaultCount(void);
#endif
