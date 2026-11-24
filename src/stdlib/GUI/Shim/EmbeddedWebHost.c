#include "../EmbeddedWebHost/BtrcEmbeddedWebHost.h"
#include <stddef.h>
#include <stdatomic.h>

static _Atomic(const BtrcEmbeddedWebBackend*) btrcWebBackend;

void btrcShimRegisterWebBackend(const BtrcEmbeddedWebBackend* backend) {
	const BtrcEmbeddedWebBackend* unset = NULL;
	atomic_compare_exchange_strong(&btrcWebBackend, &unset, backend);
}

bool btrcShimWebInstalled(void) { return atomic_load(&btrcWebBackend) != NULL; }
BtrcShimControl* btrcShimWebCreate(unsigned int id) {
	const BtrcEmbeddedWebBackend* backend = atomic_load(&btrcWebBackend);
	return backend != NULL ? backend->create(id) : NULL;
}

/* Only a successfully created view can call these methods, and its backend
 * stays installed for the process lifetime. */
void btrcShimWebServeDirectory(BtrcShimControl* view, const char* directory) { atomic_load(&btrcWebBackend)->serveDirectory(view, directory); }
void btrcShimWebServeFiles(BtrcShimControl* view) { atomic_load(&btrcWebBackend)->serveFiles(view); }
void btrcShimWebServeFile(BtrcShimControl* view, const char* path, const unsigned char* bytes, unsigned long long size) {
	atomic_load(&btrcWebBackend)->serveFile(view, path, bytes, size);
}
void btrcShimWebAllowOrigin(BtrcShimControl* view, const char* origin) { atomic_load(&btrcWebBackend)->allowOrigin(view, origin); }
void btrcShimWebLoad(BtrcShimControl* view, const char* path) { atomic_load(&btrcWebBackend)->load(view, path); }
void btrcShimWebPost(BtrcShimControl* view, const char* json) { atomic_load(&btrcWebBackend)->post(view, json); }
