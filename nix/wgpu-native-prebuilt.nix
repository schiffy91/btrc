# wgpu-native v27.0.4.0's prebuilt release archives, one per GPU slice
# (docs/design/platform-toolchain-matrix.md, "wgpu-native archives per slice";
# D21 pins prebuilt archives). The flake builds the same version from source for
# the macOS and Linux dev shells; these fixed-output fetches are for the cross
# slices, and nothing consumes them until Stage 28 (`tooling-cross-gpu-deps`).
#
# Each hash is the SHA-256 of the archive file itself, as downloaded from
# https://github.com/gfx-rs/wgpu-native/releases/download/v27.0.4.0/<archive>
# on 2026-10-03 with `nix store prefetch-file`; the matrix records the same
# digests in hex. To re-check one:
#   nix store prefetch-file --hash-type sha256 <url>
# or compare with the asset's `digest` in
#   gh api repos/gfx-rs/wgpu-native/releases/tags/v27.0.4.0
{ fetchurl }:
let
  version = "27.0.4.0";
  archive = name: hash: fetchurl {
    url = "https://github.com/gfx-rs/wgpu-native/releases/download/v${version}/${name}";
    inherit hash;
  };
in {
  macos-arm64 = archive "wgpu-macos-aarch64-release.zip" "sha256-FTZ8Jv2+aJLbNQB9OfOINZM4TndzYLcOa9cEy13t3lM=";
  linux-x64 = archive "wgpu-linux-x86_64-release.zip" "sha256-JxSB73b78+oJYxpgeelJNjbs+BPNnJIwbEShpFKZG6E=";
  windows-x64 = archive "wgpu-windows-x86_64-gnu-release.zip" "sha256-wMLbzvPGqZM6Ghv3y9quvtYaM8gzussCaWYvkVNr6L0=";
  # The only Windows ARM64 asset is the MSVC build (the matrix's "Windows ARM64
  # and the MSVC question").
  windows-arm64 = archive "wgpu-windows-aarch64-msvc-release.zip" "sha256-cSccNnG7y7iTUhHcGL/B92UybXL20XEMk6+w1ZcACqk=";
  ios-arm64 = archive "wgpu-ios-aarch64-release.zip" "sha256-162zayynqiLEC8+ayW8SIjU1MwQAJ9tPlSiM21kMBr4=";
  ios-simulator-arm64 = archive "wgpu-ios-aarch64-simulator-release.zip" "sha256-H3yJ5LQA3KzRRTIvQcXnpKLIswbnQlm4KYpV+Fgnn1E=";
  android-arm64 = archive "wgpu-android-aarch64-release.zip" "sha256-gKk+z8sU0H9srbi8m9z3iXTzZosnqJ9SobAGzRTphaA=";
  android-x64 = archive "wgpu-android-x86_64-release.zip" "sha256-Ad+rlu/LmA8E2hgUw9AwDAa9PK2z7mXMfxvhf/kEUjo=";
}
