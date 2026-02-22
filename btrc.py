#!/usr/bin/env python3
"""btrc — a language that transpiles to C.

Thin entry point that delegates to compiler.python.main.
"""

from src.compiler.python.main import main

if __name__ == "__main__":
    main()
