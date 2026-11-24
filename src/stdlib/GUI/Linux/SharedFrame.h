#ifndef BTRC_LINUX_SHARED_FRAME_H
#define BTRC_LINUX_SHARED_FRAME_H
#include "../Shim/ShimControls.h"

typedef struct BtrcDmaBufReceiver BtrcDmaBufReceiver;
BtrcDmaBufReceiver* btrcDmaBufListen(int producerPid);
const char* btrcDmaBufAddress(BtrcDmaBufReceiver* receiver);
void btrcDmaBufDisconnect(BtrcDmaBufReceiver* receiver);
BtrcShimControl* btrcLinuxSharedFrameCreate(unsigned int id);
void btrcLinuxSharedFrameClear(BtrcShimControl* picture);
bool btrcLinuxSupportsSharedFrames(void);
bool btrcLinuxSharedFrameReceive(BtrcShimControl* picture, BtrcDmaBufReceiver* receiver);
int btrcLinuxSharedFrameWidth(BtrcShimControl* picture);
int btrcLinuxSharedFrameHeight(BtrcShimControl* picture);
#endif
