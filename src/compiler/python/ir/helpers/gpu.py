"""CPU fallback helpers for the checked GPU execution contract."""

from ...gpu_errors import GPU_STATUS_BOUNDS, GPU_STATUS_MESSAGES
from .core import HelperDef

_INDEX_MESSAGE = GPU_STATUS_MESSAGES[GPU_STATUS_BOUNDS].replace("\n", "\\n")

GPU = {
    "__btrc_gpu_index_check": HelperDef(
        c_source=(
            "static inline int __btrc_gpu_index_check(int index, int length) {\n"
            "    if (index < 0 || index >= length) {\n"
            f'        fputs("{_INDEX_MESSAGE}", stderr); exit(1);\n'
            "    }\n"
            "    return index;\n"
            "}"
        ),
        required_headers=["stdio.h", "stdlib.h"],
    ),
}
