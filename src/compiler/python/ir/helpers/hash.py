"""Portable string hashing helper used by type-directed generic lowering."""

from .core import HelperDef

HASH = {
    "__btrc_hash_real": HelperDef(
        c_source=(
            "static inline unsigned int __btrc_hash_real(long double value) {\n"
            "    if (value == 0.0L) return 0U;\n"
            "    /* Hash a canonical-width conversion, not long-double padding.\n"
            "       Equal real values convert to equal doubles; unequal values\n"
            "       may collide, which is permitted by the hash contract. */\n"
            "    double canonical = (double)value;\n"
            "    unsigned char bytes[sizeof canonical];\n"
            "    memcpy(bytes, &canonical, sizeof canonical);\n"
            "    unsigned int h = 2166136261U;\n"
            "    for (size_t i = 0; i < sizeof canonical; ++i) {\n"
            "        h ^= (unsigned int)bytes[i];\n"
            "        h *= 16777619U;\n"
            "    }\n"
            "    return h;\n"
            "}"
        ),
    ),
    "__btrc_hash_str": HelperDef(
        c_source=(
            "static inline unsigned int __btrc_hash_str(const char* s) {\n"
            "    if (!s) return 0;\n"
            "    unsigned int h = 5381;\n"
            "    while (*s) { h = ((h << 5) + h) + (unsigned char)*s++; }\n"
            "    return h;\n"
            "}"
        ),
    ),
}
