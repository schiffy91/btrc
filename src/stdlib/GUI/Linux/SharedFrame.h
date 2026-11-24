#ifndef BTRC_LINUX_SHARED_FRAME_H
#define BTRC_LINUX_SHARED_FRAME_H
#include "../Shim/ShimControls.h"

typedef struct BtrcDmaBufReceiver BtrcDmaBufReceiver;
BtrcDmaBufReceiver* btrcDmaBufListen(int producerPid);
const char* btrcDmaBufAddress(BtrcDmaBufReceiver* receiver);
void btrcDmaBufDisconnect(BtrcDmaBufReceiver* receiver);
BtrcShimControl* btrcGtkSharedFrameCreate(unsigned int id);
void btrcGtkSharedFrameClear(BtrcShimControl* picture);
bool btrcGtkSupportsSharedFrames(void);
bool btrcGtkPictureReceive(BtrcShimControl* picture, BtrcDmaBufReceiver* receiver);
int btrcGtkPictureFrameWidth(BtrcShimControl* picture);
int btrcGtkPictureFrameHeight(BtrcShimControl* picture);
#endif
