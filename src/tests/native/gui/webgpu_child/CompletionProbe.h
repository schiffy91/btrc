#pragma once

void probeDelayCompletions(int stage);
void probeDeliverCompletion(void);
int probePendingCompletions(void);
int probeAdapterClaims(void);
int probeDeviceClaims(void);
int probeBufferClaims(void);
