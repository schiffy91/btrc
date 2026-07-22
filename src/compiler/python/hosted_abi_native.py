"""Merged exact ABI seams supplied by optional native runtimes."""

from .hosted_abi_model import HostedFunction
from .hosted_abi_native_gpu import HOSTED_NATIVE_GPU_FUNCTIONS
from .hosted_abi_native_gui import HOSTED_NATIVE_GUI_FUNCTIONS
from .hosted_abi_native_tray import HOSTED_NATIVE_TRAY_FUNCTIONS


def _merge(*registries) -> dict[str, HostedFunction]:
    merged = {}
    for registry in registries:
        overlap = merged.keys() & registry.keys()
        if overlap:
            raise ValueError(f"duplicate native ABI specs: {sorted(overlap)!r}")
        merged.update(registry)
    return merged


HOSTED_NATIVE_FUNCTIONS = _merge(
    HOSTED_NATIVE_GPU_FUNCTIONS,
    HOSTED_NATIVE_GUI_FUNCTIONS,
    HOSTED_NATIVE_TRAY_FUNCTIONS,
)
HOSTED_NATIVE_NAMES = frozenset(HOSTED_NATIVE_FUNCTIONS)
HOSTED_NATIVE_INTERNAL_NAMES = frozenset(
    {
        "btrc_gpu_async_complete",
        "btrc_gpu_async_create",
        "btrc_gpu_async_release",
        "btrc_gpu_async_wait",
        "btrc_gpu_create_surface",
        "btrc_gpu_pending_list_destroy",
        "btrc_gpu_pending_list_init",
        "btrc_gpu_pending_list_lock",
        "btrc_gpu_pending_list_merge",
        "btrc_gpu_pending_list_prepend",
        "btrc_gpu_pending_list_take_all",
        "btrc_gpu_pending_list_unlock",
        "btrc_gpu_publish_compute_candidate",
        "btrc_gui_clear_font_if_active",
        "btrc_gui_install_font_backend",
        "btrc_gui_surface_pixels",
    }
)

__all__ = [
    "HOSTED_NATIVE_FUNCTIONS",
    "HOSTED_NATIVE_INTERNAL_NAMES",
    "HOSTED_NATIVE_NAMES",
]
