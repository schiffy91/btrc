# The ABI tests compare btrc's first-party COM declarations against the header
# in this Microsoft NuGet package. Win32Web.c loads the installed Evergreen
# WebView2 runtime directly without shipping WebView2Loader.dll alongside the
# executable. The system Edge WebView2 runtime supplies the browser engine.
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
