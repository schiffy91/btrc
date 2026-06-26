/* btrc Windows compatibility layer (force-included via `-include` on Windows
   builds only; POSIX builds never see this file).

   The missing-FILE shims (regex.h, sys/wait.h, …) live beside this header and
   are found via `-I`. This header handles missing-SYMBOL gaps: POSIX functions
   MinGW-w64 omits but that survive DCE in the emitted C. Mappings are the
   no-symlink Windows equivalents; richer Win32 behaviour is Milestone 2. */
#pragma once
#include <sys/stat.h>
/* Windows has no POSIX symlinks: lstat == stat. */
#ifndef lstat
#define lstat stat
#endif
