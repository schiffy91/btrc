"""Read Android host versions from the integrator-owned platforms shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


class SDKVersions:
    """The pinned package contract, shared by local builds and future CI setup."""

    def __init__(self, source=REPO / "nix/platforms.nix"):
        text = re.sub(r"#.*", "", Path(source).read_text())
        self.ndk = self.scalar(text, "ndkVersion")
        self.commandline = self.scalar(text, "cmdLineToolsVersion")
        self.platform_tools = self.scalar(text, "platformToolsVersion")
        self.emulator = self.scalar(text, "emulatorVersion")
        self.build_tools = self.sequence(text, "buildToolsVersions")
        self.apis = self.sequence(text, "platformVersions")

    @staticmethod
    def scalar(text, key):
        values = re.findall(rf'\b{key}\s*=\s*"([0-9.]+)"\s*;', text)
        if len(values) != 1:
            raise ValueError(f"platforms.nix must declare one literal {key}")
        return values[0]

    @staticmethod
    def sequence(text, key):
        values = re.findall(rf"\b{key}\s*=\s*\[([^]]+)\]\s*;", text)
        if len(values) != 1 or not re.fullmatch(r'(?:\s*"[0-9.]+"\s*)+', values[0]):
            raise ValueError(f"platforms.nix must declare one literal {key} list")
        return re.findall(r'"([0-9.]+)"', values[0])

    def packages(self):
        return [
            f"cmdline-tools;{self.commandline}",
            "platform-tools",
            "emulator",
            f"ndk;{self.ndk}",
            *(f"build-tools;{version}" for version in self.build_tools),
            *(f"platforms;android-{api}" for api in self.apis),
            *(f"system-images;android-{api};google_apis;x86_64" for api in self.apis),
        ]

    def cache_key(self):
        return hashlib.sha256(json.dumps(vars(self), sort_keys=True).encode()).hexdigest()

    def verify(self, root):
        root = Path(root)
        versions = {
            "platform-tools": self.platform_tools,
            "emulator": self.emulator,
            f"cmdline-tools/{self.commandline}": self.commandline,
            f"ndk/{self.ndk}": self.ndk,
        }
        versions.update({f"build-tools/{version}": version for version in self.build_tools})
        for relative, expected in versions.items():
            properties = (root / relative / "source.properties").read_text()
            match = re.search(r"^Pkg.Revision\s*=\s*(\S+)", properties, re.MULTILINE)
            if not match or match[1] != expected:
                raise ValueError(f"{relative}: expected revision {expected}, found {match[1] if match else 'missing'}")
        for api in self.apis:
            for relative in (
                f"platforms/android-{api}/android.jar",
                f"system-images/android-{api}/google_apis/x86_64/system.img",
            ):
                if not (root / relative).is_file():
                    raise ValueError(f"missing SDK package payload: {relative}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("packages", "cache-key", "verify"))
    parser.add_argument("--sdk", type=Path)
    args = parser.parse_args(argv)
    versions = SDKVersions()
    if args.command == "packages":
        print("\n".join(versions.packages()))
    elif args.command == "cache-key":
        print(versions.cache_key())
    else:
        if args.sdk is None:
            parser.error("verify requires --sdk")
        versions.verify(args.sdk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
