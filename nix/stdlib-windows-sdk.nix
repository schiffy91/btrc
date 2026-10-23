# Header-reading dependencies for strict Windows stdlib analysis on a Unix host.
# Use the existing WebGPU pin and the Windows JNI headers from pinned OpenJDK.
{ pkgs, nixpkgs }:
let
  wgpu = (import ./wgpu-native-prebuilt.nix { inherit (pkgs) fetchurl; }).windows-x64;
  # Darwin's jdk17 is a binary distribution without Windows headers. Read the
  # source pin from the Linux package, then fetch it with this host's builder.
  jdk = (import nixpkgs { system = "x86_64-linux"; }).openjdk17_headless.src;
  jdkSource = pkgs.fetchzip {
    url = builtins.head jdk.urls;
    hash = jdk.outputHash;
  };
in pkgs.runCommand "btrc-stdlib-windows-sdk" {
  nativeBuildInputs = [ pkgs.unzip ];
} ''
  mkdir -p "$out/wgpu" "$out/include" "$out/lib/pkgconfig" "$out/share/licenses/jni"
  unzip -q ${wgpu} -d "$out/wgpu"
  cp ${jdkSource}/src/java.base/share/native/include/jni.h "$out/include/"
  cp ${jdkSource}/src/java.base/windows/native/include/jni_md.h "$out/include/"
  cp ${jdkSource}/LICENSE ${jdkSource}/ADDITIONAL_LICENSE_INFO "$out/share/licenses/jni/"
  cat > "$out/lib/pkgconfig/wgpu-native-windows-x86_64.pc" <<EOF
  Name: wgpu-native-windows-x86_64
  Description: Pinned Windows WebGPU SDK
  Version: ${wgpu.version}
  Cflags: -I$out/wgpu/include/webgpu
  Libs: $out/wgpu/lib/libwgpu_native.dll.a
  EOF
''
