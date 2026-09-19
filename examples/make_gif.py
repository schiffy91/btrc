"""Turn the PPM frames written by sgd_render into the README animation.

Usage: python3 make_gif.py [frames_dir] [output.gif]
Requires Pillow. The renderers themselves have no Python dependency; this is only
here so the committed GIF can be regenerated from a fresh run.
"""

import pathlib
import sys

from PIL import Image

FRAME_MS = 60
HOLD_MS = 1500


def main() -> int:
    frames_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "frames")
    output = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "sgd.gif")

    paths = sorted(frames_dir.glob("frame*.ppm"))
    if not paths:
        print(f"No frames in {frames_dir}; run ./sgd_render first.", file=sys.stderr)
        return 1

    frames = [Image.open(path).convert("RGB") for path in paths]
    palette = frames[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]

    durations = [FRAME_MS] * len(quantized)
    durations[-1] = HOLD_MS

    quantized[0].save(
        output,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"{output}: {len(quantized)} frames, {output.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
