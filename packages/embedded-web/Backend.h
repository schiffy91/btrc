#ifndef BTRC_EMBEDDED_WEB_BACKEND_H
#define BTRC_EMBEDDED_WEB_BACKEND_H
#include <BtrcEmbeddedWebHost.h>
#include "Install.h"

static BtrcShimControl* btrcEmbeddedWebCreate(unsigned int);
static void btrcEmbeddedWebServeDirectory(BtrcShimControl*, const char*);
static void btrcEmbeddedWebServeFiles(BtrcShimControl*);
static void btrcEmbeddedWebServeFile(BtrcShimControl*, const char*, const unsigned char*, unsigned long long);
static void btrcEmbeddedWebAllowOrigin(BtrcShimControl*, const char*);
static void btrcEmbeddedWebLoad(BtrcShimControl*, const char*);
static void btrcEmbeddedWebPost(BtrcShimControl*, const char*);

void btrcInstallEmbeddedWeb(void) {
	static const BtrcEmbeddedWebBackend backend = {
		btrcEmbeddedWebCreate, btrcEmbeddedWebServeDirectory, btrcEmbeddedWebServeFiles, btrcEmbeddedWebServeFile,
		btrcEmbeddedWebAllowOrigin, btrcEmbeddedWebLoad, btrcEmbeddedWebPost,
	};
	btrcShimRegisterWebBackend(&backend);
}
#endif
