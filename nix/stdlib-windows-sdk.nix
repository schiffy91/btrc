# Header-reading dependencies for strict Windows stdlib analysis on a Unix host.
{ pkgs }:
let
  wgpu = (import ./wgpu-native-prebuilt.nix { inherit (pkgs) fetchurl; }).windows-x64;
  webview2 = import ./webview2-sdk-prebuilt.nix { inherit (pkgs) fetchurl; };
in pkgs.runCommand "btrc-stdlib-windows-sdk" {
  nativeBuildInputs = [ pkgs.unzip ];
} ''
  mkdir -p "$out/wgpu" "$out/webview2" "$out/include" "$out/lib/pkgconfig"
  unzip -q ${wgpu} -d "$out/wgpu"
  unzip -q -j ${webview2} build/native/include/WebView2.h LICENSE.txt -d "$out/webview2"
  # MinGW-w64 has no EventToken.h; WebView2.h needs only this from it.
  cat > "$out/webview2/EventToken.h" <<EOF
  #ifndef BTRC_EVENT_TOKEN_H
  #define BTRC_EVENT_TOKEN_H
  typedef struct EventRegistrationToken { __int64 value; } EventRegistrationToken;
  #endif
  EOF
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
