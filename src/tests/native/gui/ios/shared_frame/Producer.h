#pragma once
#include <stdbool.h>
int frameProducerPid(void);
bool sendTestFrame(const char *address, int width, bool bgra);
