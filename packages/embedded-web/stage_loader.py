"""Extract Microsoft's supported WebView2 loader for an application."""

import argparse
import hashlib
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

PIN = tomllib.loads(Path(__file__).with_name("webview2-sdk.toml").read_text(encoding="utf-8"))
VERSION = PIN["version"]
SHA256 = PIN["sha256"]


def stage(archive: Path, target: str, directory: Path) -> Path:
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != SHA256:
            raise ValueError(f"{archive} is not the pinned Microsoft.Web.WebView2 {VERSION} package")
        source.seek(0)
        with ZipFile(source) as bundle:
            loader = bundle.read(f"build/native/{target}/WebView2Loader.dll")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "WebView2Loader.dll"
    with TemporaryDirectory(dir=directory) as temporary:
        staged = Path(temporary) / destination.name
        staged.write_bytes(loader)
        staged.replace(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help=f"Microsoft.Web.WebView2.{VERSION}.nupkg")
    parser.add_argument("target", choices=("x64", "arm64"))
    parser.add_argument("directory", type=Path, help="the directory containing the program")
    args = parser.parse_args()
    try:
        print(stage(args.archive, args.target, args.directory))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
