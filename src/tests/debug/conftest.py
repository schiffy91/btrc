"""Debugger package test setup."""

import sys
import types

sys.modules.setdefault("lldb", types.SimpleNamespace())
