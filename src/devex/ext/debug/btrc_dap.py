#!/usr/bin/env python3
"""Entry point for the btrc Debug Adapter (DAP server over stdio).

VSCode launches this. It first ensures the lldb Python module is importable
(re-exec'ing under a compatible interpreter if necessary), then runs the
adapter. The folder is self-contained: siblings are imported by name, so the
whole directory can be copied into the packaged extension.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bootstrap import ensure_lldb  # noqa: E402

ensure_lldb()  # may os.execve under a different python and not return

from adapter import main  # noqa: E402  (imports lldb; safe after bootstrap)

if __name__ == "__main__":
    main()
