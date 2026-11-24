# Header-reading dependencies for strict Windows stdlib analysis on a Unix host.
{ pkgs }:
let
  wgpu = (import ./wgpu-native-prebuilt.nix { inherit (pkgs) fetchurl; }).windows-x64;
in pkgs.runCommand "btrc-stdlib-windows-sdk" {
  nativeBuildInputs = [ pkgs.unzip ];
} ''
  mkdir -p "$out/wgpu" "$out/include" "$out/lib/pkgconfig"
  unzip -q ${wgpu} -d "$out/wgpu"
  cat > "$out/lib/pkgconfig/wgpu-native-windows-x86_64.pc" <<EOF
  Name: wgpu-native-windows-x86_64
  Description: Pinned Windows WebGPU SDK
  Version: ${wgpu.version}
  Cflags: -I$out/wgpu/include/webgpu
  Libs: $out/wgpu/lib/libwgpu_native.dll.a
  EOF
''
