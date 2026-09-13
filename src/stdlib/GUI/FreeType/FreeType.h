#ifndef BTRC_GUI_FREETYPE_H
#define BTRC_GUI_FREETYPE_H

/* Declarations and ABI come entirely from the selected FreeType SDK. */
#include <ft2build.h>
#include FT_FREETYPE_H

/* Give selected SDK macro expressions declaration identities. Clang checks
 * the installed header values; no SDK numeric values are duplicated here. */
enum {
    BTRC_FT_LOAD_DEFAULT = FT_LOAD_DEFAULT,
    BTRC_FT_LOAD_RENDER = FT_LOAD_RENDER
};

#endif
