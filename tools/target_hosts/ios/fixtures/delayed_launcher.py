"""Local transport regression: a client launches a separately sessioned C host."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    delay, child_file, executable, *argv = sys.argv[1:]
    time.sleep(float(delay))
    child = subprocess.Popen([executable, *argv], env=os.environ)
    Path(child_file).write_text(str(child.pid))
    try:
        status = child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=3)
        raise
    output = Path(os.environ["BTRC_TESTHOST_DIR"]) / "stdout"
    if output.exists():
        Path(child_file).with_suffix(".stdout").write_bytes(output.read_bytes())
    raise SystemExit(status if status >= 0 else 128 - status)


if __name__ == "__main__":
    main()
