/* btrc: stands in for musl's internal src/internal/locale_impl.h, the one
   private musl header regerror.c and fnmatch.c include. btrc programs run in
   the C locale, whose message catalogue is the identity and whose characters
   are single bytes. btrc_win_musl.h saves and restores MB_CUR_MAX around the
   vendored sources, so the caller's definition is untouched. */
#define LCTRANS_CUR(msg) (msg)
#undef MB_CUR_MAX
#define MB_CUR_MAX 1
