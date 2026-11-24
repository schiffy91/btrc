#ifndef BTRC_SHIM_SHARED_FRAME_H
#define BTRC_SHIM_SHARED_FRAME_H
#include "ShimControls.h"

const char* btrcShimFrameTransport(void);
BtrcShimControl* btrcShimFrameCreate(unsigned int id);
const char* btrcShimFrameListen(BtrcShimControl* control, int producerPid);
void btrcShimFrameDisconnect(BtrcShimControl* control);
bool btrcShimFramePresent(BtrcShimControl* control);
int btrcShimFrameWidth(BtrcShimControl* control);
int btrcShimFrameHeight(BtrcShimControl* control);
#endif
