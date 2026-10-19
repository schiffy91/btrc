"""Build strict C11 Android spike bundles; no emulator is needed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from tools.target_hosts.android.sdk import SDKVersions

ROOT = Path(__file__).resolve().parent
# Each ABI's targets.toml row and that row's triple, for the probe's bundle.json.
ROWS = {
    "x86_64": ("android-x86_64", "x86_64-unknown-linux-android29", "x86_64"),
    "arm64-v8a": ("android-aarch64", "aarch64-unknown-linux-android29", "aarch64"),
}


class AndroidHostBuilder:
    def __init__(self, ndk, output, *, abi="x86_64"):
        if abi not in ("x86_64", "arm64-v8a"):
            raise ValueError("supported Android ABIs are x86_64 and arm64-v8a")
        self.ndk, self.output, self.abi = Path(ndk), Path(output).resolve(), abi
        revision = re.search(r"^Pkg.Revision\s*=\s*(\S+)", (self.ndk / "source.properties").read_text(), re.MULTILINE)
        if not revision or revision[1] != SDKVersions().ndk:
            raise ValueError("the selected NDK does not match the platforms.nix revision")
        self.triple = "x86_64-linux-android29" if abi == "x86_64" else "aarch64-linux-android29"
        self.bin = self.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
        self.clang = self.bin / "clang"

    @staticmethod
    def load_alignment(text):
        rows = [line.split() for line in text.splitlines() if line.strip().startswith("LOAD ")]
        if not rows or any(int(row[-1], 16) < 0x4000 for row in rows):
            raise ValueError("every ELF LOAD segment must be aligned to at least 0x4000")

    def build(self, *, app=False, native_only=False):
        self.output.mkdir(parents=True, exist_ok=True)
        source = ROOT / "fixtures/probe.c"
        command = [
            str(self.clang),
            f"--target={self.triple}",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
        ]
        executable = self.output / "probe"
        subprocess.run([*command, str(source), "-o", str(executable)], check=True, timeout=120)
        self.write_bundle(executable)
        programs = {}
        if app or native_only:
            native = self.output / "jniLibs" / self.abi
            native.mkdir(parents=True, exist_ok=True)
            entry = self.output / "program.o"
            subprocess.run(
                [*command, "-fPIC", "-Dmain=btrc_program_main", "-c", str(source), "-o", str(entry)],
                check=True,
                timeout=120,
            )
            glue = self.ndk / "sources/android/native_app_glue"
            library = native / "libbtrcprogram.so"
            subprocess.run(
                [
                    str(self.clang),
                    f"--target={self.triple}",
                    "-std=c11",
                    "-fPIC",
                    "-shared",
                    "-I",
                    str(glue),
                    str(ROOT / "app/host_main.c"),
                    str(glue / "android_native_app_glue.c"),
                    str(entry),
                    "-Wl,-z,max-page-size=16384",
                    "-Wl,-u,ANativeActivity_onCreate",
                    "-landroid",
                    "-llog",
                    "-o",
                    str(library),
                ],
                check=True,
                timeout=120,
            )
            segments = subprocess.run(
                [str(self.bin / "llvm-readelf"), "-lW", str(library)],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            ).stdout
            self.load_alignment(segments)
            (self.output / "load-segments.txt").write_text(segments)
        if app:
            package = "dev.btrc.testhost.fixture"
            build_dir = self.output / "gradle-build"
            subprocess.run(
                [
                    str(ROOT / "app/gradlew"),
                    "--project-dir",
                    str(ROOT / "app"),
                    "--no-daemon",
                    "--console=plain",
                    "assembleDebug",
                    f"-PbtrcNdk={SDKVersions().ndk}",
                    f"-PbtrcBuildTools={SDKVersions().build_tools[-1]}",
                    f"-PbtrcPackage={package}",
                    f"-PbtrcAbi={self.abi}",
                    f"-PbtrcJniLibs={native.parent}",
                    f"-PbtrcBuildDir={build_dir}",
                ],
                check=True,
                timeout=600,
            )
            apks = list((build_dir / "outputs/apk/debug").glob("*.apk"))
            if len(apks) != 1:
                raise RuntimeError("Gradle did not produce exactly one debug APK")
            shutil.copy2(apks[0], self.output / "host.apk")
            programs["app"] = {"mode": "app", "apk": "host.apk", "package": package}
        listing = self.output / "programs.json"
        if programs:
            listing.write_text(json.dumps(programs, indent=2) + "\n")
        else:
            listing.unlink(missing_ok=True)
        (self.output / "toolchain.json").write_text(json.dumps(self.toolchain(), indent=2) + "\n")
        return programs

    def toolchain(self):
        return {"ndk": SDKVersions().ndk, "abi": self.abi, "target": self.triple}

    def write_bundle(self, executable):
        """The probe as a btrc.target-bundle/1 bundle, which the protocol-1 shell executor admits."""

        label, triple, architecture = ROWS[self.abi]
        document = {
            "schema": "btrc.target-bundle/1",
            "protocol": 1,
            "target": {"label": label, "triple": triple, "operating_system": "android", "architecture": architecture},
            "toolchain": self.toolchain(),
            "programs": {
                "probe": {
                    "source": "tools/target_hosts/android/fixtures/probe.c",
                    "frontend": "fixture",
                    "status": "built",
                    "artifact": executable.name,
                    "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                }
            },
        }
        (self.output / "bundle.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, default=os.environ.get("ANDROID_NDK_HOME"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--abi", choices=("x86_64", "arm64-v8a"), default="x86_64")
    parser.add_argument("--app", action="store_true")
    parser.add_argument(
        "--native-only", action="store_true", help="compile and inspect the .so without packaging an APK"
    )
    args = parser.parse_args(argv)
    if args.ndk is None:
        parser.error("--ndk or ANDROID_NDK_HOME is required")
    AndroidHostBuilder(args.ndk, args.output, abi=args.abi).build(app=args.app, native_only=args.native_only)


if __name__ == "__main__":
    main()
