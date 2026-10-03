# The `.#platforms` dev shell's additions (PLAN.md Stage 23,
# `tooling-android-sdk-ndk`): the Android SDK and NDK r29 and JDK 17, pinned to
# the revisions docs/design/platform-toolchain-matrix.md records. The default
# shell and the CI image never import this file.
#
# The Android SDK licences are accepted here, in a nixpkgs import that only this
# shell evaluates (D8 approves the acceptance). androidenv's packages are
# unfree, so that import also allows unfree packages; nothing else is drawn
# from it.
#
# The pinned nixpkgs' androidenv feed (pkgs/development/mobile/androidenv/
# repo.json) carries NDK 29.0.14206865, build-tools 37.0.0 and platform 36, but
# not platform-tools 37.0.1, cmdline-tools 23.0, emulator 37.2.12 or the
# google_apis_ps16k API 36 image. ./android-repo-overlay.json adds exactly
# those entries, unchanged from nixpkgs' own androidenv/update.rb run over
# Google's feeds on 2026-10-03:
#   https://dl.google.com/android/repository/repository2-3.xml
#   https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml
# (only the feed's fetch-day bookkeeping, `last-available-day`, is dropped).
# Every archive is fetched against the SHA-1 Google's feed publishes. To
# re-check one, compare its `sha1` and `url` with the same package's
# <archive> in the feed above, or run `nix store prefetch-file --hash-type sha1
# <url>`.
{ nixpkgs, system, lib }:
let
  pkgs = import nixpkgs {
    inherit system;
    config = {
      android_sdk.accept_license = true;
      allowUnfree = true;
    };
  };
  appleSilicon = pkgs.stdenv.hostPlatform.isDarwin && pkgs.stdenv.hostPlatform.isAarch64;
  ndkVersion = "29.0.14206865";
  # A package entry is replaced whole (packages.<name>.<revision>,
  # images.<api>.<type>.<abi>), never merged field by field into an older one.
  repo = lib.recursiveUpdateUntil
    (path: _: _: lib.length path == (if lib.head path == "images" then 4 else 3))
    (lib.importJSON "${nixpkgs}/pkgs/development/mobile/androidenv/repo.json")
    (lib.importJSON ./android-repo-overlay.json);
  android = pkgs.androidenv.composeAndroidPackages {
    inherit repo;
    cmdLineToolsVersion = "23.0";
    toolsVersion = null;
    platformToolsVersion = "37.0.1";
    buildToolsVersions = [ "37.0.0" ];
    includeEmulator = true;
    emulatorVersion = "37.2.12";
    # Platform 36 is the compile and target API. androidenv composes system
    # images only for the platforms it installs, so the API 29 floor image
    # also brings platform 29 (the minSdk), about 70 MB.
    platformVersions = [ "29" "36" ];
    includeNDK = true;
    ndkVersions = [ ndkVersion ];
    includeCmake = false;
    includeSystemImages = true;
    # The emulator's native ABI per host: arm64-v8a on Apple silicon, which
    # also gets the 16 KiB image (page_size_16kb is the feed's tag for
    # system-images;android-36;google_apis_ps16k; it exists only for API 36),
    # and x86_64 elsewhere.
    systemImageTypes = [ "google_apis" ] ++ lib.optional appleSilicon "page_size_16kb";
    abiVersions = if appleSilicon then [ "arm64-v8a" ] else [ "x86_64" ];
  };
  sdkRoot = "${android.androidsdk}/libexec/android-sdk";
  jdk = pkgs.jdk17;
in {
  packages = [ android.androidsdk jdk ];
  environment = {
    ANDROID_HOME = sdkRoot;
    ANDROID_SDK_ROOT = sdkRoot;
    ANDROID_NDK_HOME = "${sdkRoot}/ndk/${ndkVersion}";
    JAVA_HOME = jdk.home;
  };
  inherit android;
}
