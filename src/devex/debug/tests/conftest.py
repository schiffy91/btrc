"""Test setup for the debugger's self-contained sibling imports."""

import sys
import types
from pathlib import Path

sys.modules.setdefault("lldb", types.SimpleNamespace())

DEBUG_DIR = Path(__file__).resolve().parents[1]
if str(DEBUG_DIR) not in sys.path:
    sys.path.insert(0, str(DEBUG_DIR))
