"""String-operation helper registry compatibility facade."""

from .strings_composition import STRING_COMPOSITION
from .strings_layout import STRING_LAYOUT
from .strings_transform import STRING_TRANSFORM

STRING_OPS = {
    **STRING_TRANSFORM,
    **STRING_LAYOUT,
    **STRING_COMPOSITION,
}

__all__ = ["STRING_OPS"]
