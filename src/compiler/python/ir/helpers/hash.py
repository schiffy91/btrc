"""Hash runtime helpers -- hash helper for string-keyed collections."""

from .core import HelperDef

HASH = {
    "__btrc_hash_str": HelperDef(
        c_source=(
            "static inline unsigned int __btrc_hash_str(const char* s) {\n"
            "    unsigned int h = 5381;\n"
            "    while (*s) { h = ((h << 5) + h) + (unsigned char)*s++; }\n"
            "    return h;\n"
            "}"
        ),
    ),
}
