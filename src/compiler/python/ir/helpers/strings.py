"""String runtime helpers — aggregator for all string helper categories."""

from .strings_convert import STRING_CONVERT
from .strings_ops import STRING_OPS
from .strings_query import STRING_QUERY

STRING = {**STRING_OPS, **STRING_QUERY, **STRING_CONVERT}
