#ifndef CLIPBOARD_READ_CONTROL_H
#define CLIPBOARD_READ_CONTROL_H

void clipboardReadArm(int mode);
int clipboardReadFinish(int allocationExpected);
int clipboardReadComplete(void);

#endif
