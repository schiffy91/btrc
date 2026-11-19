# The WebView2 SDK the Windows web view is compiled against: Microsoft's
# NuGet package, which holds the C header (build/native/include/WebView2.h)
# and, per architecture, the loader a program ships beside itself
# (build/native/<arch>/WebView2Loader.dll). The engine itself is the
# system's Edge WebView2 runtime.
#
# The hash is the SHA-256 of the package file as downloaded from
# https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/<version>
# on 2026-11-19. To re-check it:
#   nix store prefetch-file --hash-type sha256 <url>
{ fetchurl }:
let
  version = "1.0.2903.40";
in fetchurl {
  name = "Microsoft.Web.WebView2.${version}.nupkg";
  url = "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/${version}";
  hash = "sha256-7xKAFt0eUcWReMgn7VuKozIsV6+oZ12TD4EJUFVCrXQ=";
  passthru = { inherit version; };
}
