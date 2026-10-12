#ifndef DIRECTORY_PICKER_DEFERRED_CONTROL_H
#define DIRECTORY_PICKER_DEFERRED_CONTROL_H

void pickerReset(int mode);
void pickerComplete(int result);
void pickerDispose(void);
int pickerOpenCount(void);
int pickerCallbackCount(void);
int pickerOwners(void);
int pickerCallbackOwners(void);
int pickerFreeCount(void);
int pickerFallbackCount(void);
int pickerPushQuit(void);

#endif
