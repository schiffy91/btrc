"""Read Android host versions from the integrator-owned platforms shell."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path
from xml.dom import minidom

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

    def selected(self, api=None):
        """Every pinned API, or only `api` (which must be one of them)."""
        if api is None:
            return self.apis
        if api not in self.apis:
            raise ValueError(f"API {api} is not pinned in platforms.nix ({', '.join(self.apis)})")
        return [api]

    def packages(self, api=None):
        apis = self.selected(api)
        return [
            f"cmdline-tools;{self.commandline}",
            "platform-tools",
            "emulator",
            f"ndk;{self.ndk}",
            *(f"build-tools;{version}" for version in self.build_tools),
            *(f"platforms;android-{level}" for level in apis),
            *(f"system-images;android-{level};google_apis;x86_64" for level in apis),
        ]

    def install_archives(self, root, *, fetch=None):
        """Replace sdkmanager's emulator and platform-tools with the checksummed pinned archives.

        sdkmanager installs only their latest revisions; nix/android-repo-overlay.json
        names the pinned archive, its size and its SHA-1.
        """
        root = Path(root)
        fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=600).read())
        overlay = json.loads((REPO / "nix/android-repo-overlay.json").read_text())["packages"]
        for package, revision in (("emulator", self.emulator), ("platform-tools", self.platform_tools)):
            (archive,) = [entry for entry in overlay[package][revision]["archives"] if entry["os"] == "linux"]
            data = fetch(archive["url"])
            digest = hashlib.sha1(data).hexdigest()
            if len(data) != archive["size"] or digest != archive["sha1"]:
                raise ValueError(f"{package} {revision}: size/sha1 mismatch ({len(data)} {digest})")
            # Raw archives omit sdkmanager's package.xml; avdmanager needs it.
            registration = (root / package / "package.xml").read_bytes()
            shutil.rmtree(root / package, ignore_errors=True)
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                for member in bundle.infolist():
                    path = Path(bundle.extract(member, root))
                    mode = member.external_attr >> 16
                    if mode:
                        path.chmod(mode & 0o777)
            self.register_archive(root, package, registration)
            print(f"installed {package} {revision} from {archive['url']}")

    def cache_key(self):
        return hashlib.sha256(json.dumps(vars(self), sort_keys=True).encode()).hexdigest()

    def register_archive(self, root, package, registration):
        """Keep sdkmanager's registration when replacing a generic archive."""
        expected = {"emulator": self.emulator, "platform-tools": self.platform_tools}[package]
        directory = Path(root) / package
        self.verify_revision(directory, expected)
        document = minidom.parseString(registration)
        rows = document.getElementsByTagName("localPackage")
        if len(rows) != 1 or rows[0].getAttribute("path") != package:
            raise ValueError(f"{package}: SDK registration has the wrong package identity")
        revisions = rows[0].getElementsByTagName("revision")
        if len(revisions) != 1:
            raise ValueError(f"{package}: SDK registration must contain one revision")
        metadata = json.loads((REPO / "nix/android-repo-overlay.json").read_text())["packages"][package][expected]
        if metadata.get("dependencies"):
            raise ValueError(f"{package}: pinned archive dependencies require explicit registration support")
        for dependencies in list(rows[0].getElementsByTagName("dependencies")):
            rows[0].removeChild(dependencies)
        revision = document.createElement("revision")
        for name, value in zip(("major", "minor", "micro"), expected.split("."), strict=True):
            part = document.createElement(name)
            part.appendChild(document.createTextNode(value))
            revision.appendChild(part)
        rows[0].replaceChild(revision, revisions[0])
        # DOM serialization preserves xmlns declarations used by xsi:type values.
        (directory / "package.xml").write_bytes(document.toxml(encoding="utf-8"))

    @staticmethod
    def verify_revision(directory, expected):
        properties = (directory / "source.properties").read_text()
        match = re.search(r"^Pkg.Revision\s*=\s*(\S+)", properties, re.MULTILINE)
        if not match or match[1] != expected:
            raise ValueError(f"{directory}: expected revision {expected}, found {match[1] if match else 'missing'}")

    def verify(self, root, api=None):
        root = Path(root)
        versions = {
            "platform-tools": self.platform_tools,
            "emulator": self.emulator,
            f"cmdline-tools/{self.commandline}": self.commandline,
            f"ndk/{self.ndk}": self.ndk,
        }
        versions.update({f"build-tools/{version}": version for version in self.build_tools})
        for relative, expected in versions.items():
            self.verify_revision(root / relative, expected)
        for level in self.selected(api):
            for relative in (
                f"platforms/android-{level}/android.jar",
                f"system-images/android-{level}/google_apis/x86_64/system.img",
            ):
                if not (root / relative).is_file():
                    raise ValueError(f"missing SDK package payload: {relative}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("packages", "cache-key", "verify", "install-archives"))
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--api", help="only this pinned API's platform and system image (packages, verify)")
    args = parser.parse_args(argv)
    versions = SDKVersions()
    if args.command == "packages":
        print("\n".join(versions.packages(args.api)))
    elif args.command == "cache-key":
        print(versions.cache_key())
    else:
        if args.sdk is None:
            parser.error(f"{args.command} requires --sdk")
        if args.command == "verify":
            versions.verify(args.sdk, args.api)
        else:
            versions.install_archives(args.sdk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
