#ifndef BTRC_IOS_SHARED_FRAME_H
#define BTRC_IOS_SHARED_FRAME_H
#include "../Shim/ShimControls.h"

BtrcShimControl* btrcUIKitFrameCreate(unsigned int id);
const char* btrcUIKitFrameListen(BtrcShimControl* control, int producerPid);
void btrcUIKitFrameDisconnect(BtrcShimControl* control);
bool btrcUIKitFramePresent(BtrcShimControl* control);
int btrcUIKitFrameWidth(BtrcShimControl* control);
int btrcUIKitFrameHeight(BtrcShimControl* control);
#endif
