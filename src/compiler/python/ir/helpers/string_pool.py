"""Compatibility spellings for the managed-string ownership runtime."""

from .core import HelperDef

STRING_POOL = {
    "__btrc_str_track": HelperDef(
        depends_on=["__btrc_string_adopt"],
        c_source=("static inline char* __btrc_str_track(char* s) {\n    return __btrc_string_adopt(s);\n}"),
    ),
    "__btrc_str_flush": HelperDef(
        c_source=(
            "static inline void __btrc_str_flush(void) {\n"
            "    /* Retained for source compatibility; ownership is explicit. */\n"
            "}"
        ),
    ),
}
