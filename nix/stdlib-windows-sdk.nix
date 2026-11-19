# Header-reading dependencies for strict Windows stdlib analysis on a Unix host.
# Use the existing WebGPU and WebView2 pins and the Windows JNI headers from
# pinned OpenJDK.
{ pkgs, nixpkgs }:
let
  wgpu = (import ./wgpu-native-prebuilt.nix { inherit (pkgs) fetchurl; }).windows-x64;
  webview2 = import ./webview2-sdk-prebuilt.nix { inherit (pkgs) fetchurl; };
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
  mkdir -p "$out/wgpu" "$out/webview2" "$out/include" "$out/lib/pkgconfig" "$out/share/licenses/jni"
  unzip -q ${wgpu} -d "$out/wgpu"
  unzip -q -j ${webview2} build/native/include/WebView2.h LICENSE.txt -d "$out/webview2"
  # MinGW-w64 has no EventToken.h; WebView2.h needs only this from it.
  cat > "$out/webview2/EventToken.h" <<EOF
  #ifndef BTRC_EVENT_TOKEN_H
  #define BTRC_EVENT_TOKEN_H
  typedef struct EventRegistrationToken { __int64 value; } EventRegistrationToken;
  #endif
  EOF
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
  cat > "$out/lib/pkgconfig/webview2-windows-x86_64.pc" <<EOF
  Name: webview2-windows-x86_64
  Description: Pinned WebView2 SDK header
  Version: ${webview2.version}
  Cflags: -I$out/webview2
  EOF
''
