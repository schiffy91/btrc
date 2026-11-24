#include <turbojpeg.h>

/* libjpeg-turbo 3.2 turned tj3Init into a macro over tj3InitVersion, and a
 * binding names functions, not macros. This is a function under either. */
static inline tjhandle btrcJpegCreate(int initType) {
	return tj3Init(initType);
}
