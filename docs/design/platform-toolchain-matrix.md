# Platform toolchain matrix

Status: pinned 2026-10-02 for PLAN.md Stage 22 (`tooling-p0-toolchain-matrix`
and `platforms-p0-matrix-pin`, one unit). It turns the proposed floors of
[platform-parity.md](platform-parity.md#proposed-support-matrix) and decisions
D8 and D21 into versions with sources. Stage 23 provisions what it names; Stage
24 moves the target values into a new `src/language` spec file (D21). That file
is **not** created here, so the values below are the input to its design.

Every row says where its version came from. "Verified online" means the
version was read from the cited official page on the access date. "Recorded
host" means it was read on the acceptance Mac on 2026-09-30. "Flake" means
`nix eval` of the pinned nixpkgs (`flake.lock`: `nixpkgs-26.05-darwin` at
`fca2dbd4`) on 2026-10-02. No mobile or Windows build has been run with any of
this. The probe in [Recorded host](#recorded-host) re-checks the host rows.

## Slices

Every slice the D21 target spec has to name. The iOS simulator and the Android
x86_64 emulator are listed apart from their devices because they are separate
artifacts (platform-parity.md §1).

| Slice | Target triple (proposed for the D21 spec) | Floor | Current | Build host |
| --- | --- | --- | --- | --- |
| macOS arm64 | `arm64-apple-macos` | macOS 12 (Xcode 27's deployment minimum) | macOS 27.0 | the Mac |
| Linux x86_64 | `x86_64-linux-gnu` | the flake's glibc | NixOS / `ubuntu-24.04` runners (D7) | Linux or the podman `linux-ci` machine |
| Windows x64 | `x86_64-windows-gnu` | Windows 11 24H2 (build 26100) | Windows 11 26H2 (build 26300) | the Mac (cross) and `windows-latest` |
| Windows ARM64 | `aarch64-windows-gnu`; `aarch64-windows-msvc` for any GPU-linked artifact (see [Windows ARM64](#windows-arm64-and-the-msvc-question)) | Windows 11 24H2 (build 26100) | Windows 11 26H2 | the Mac (cross) and `windows-11-arm` |
| iOS/iPadOS device | `arm64-apple-ios17.0` | iOS/iPadOS 17.0 | iOS/iPadOS 27.0 SDK | the Mac, Xcode 27A266a |
| iOS/iPadOS simulator | `arm64-apple-ios17.0-simulator` | iOS 17.0 | runtime 26.4.1 installed | the Mac, Xcode 27A266a |
| Android arm64-v8a | `aarch64-linux-android29` | API 29 | target API 36, compile API 36 | the Mac or Linux, NDK r29 |
| Android x86_64 (emulator) | `x86_64-linux-android29` | API 29 | API 36 | the Mac or Linux, NDK r29 |

## Pinned toolchain

One row per slice and tool. "Floor" is the oldest version the slice must
accept; "Pinned" is the exact version provisioned.

| Slice | Tool | Pinned | Floor | Source | Accessed | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| macOS / iOS | Xcode | **27.0 (27A266a)**, GA 2026-09-14 | Xcode 27 needs macOS Tahoe 26.6+ and Apple silicon | https://developer.apple.com/news/releases/ ; https://developer.apple.com/support/xcode/ | 2026-10-02 | verified online; recorded host |
| iOS device | iOS SDK | iOS 27.0 (bundled with Xcode 27.0) | deployment targets iOS 15–27; the iOS 17 floor is inside it | https://developer.apple.com/support/xcode/ | 2026-10-02 | verified online; recorded host |
| iOS device | on-device debugging | Xcode 27.0 | iOS 17 or later (Instruments too) | https://developer.apple.com/documentation/xcode-release-notes/xcode-27-release-notes | 2026-10-02 | verified online |
| iOS simulator | simulator SDK | iOS 27.0 | — | https://developer.apple.com/support/xcode/ | 2026-10-02 | verified online |
| iOS simulator | simulator runtimes | 26.4.1 (installed); iOS 17.x to install in Stage 23 | Xcode 27 supports simulators of iOS 17 or later | https://developer.apple.com/support/xcode/ ; https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components | 2026-10-02 | verified online (support); 17.x install unverified |
| iOS simulator | simulator architecture | arm64 runtime variant (the Apple-silicon default) | x86_64 needs the universal variant under Rosetta; not a required slice | https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components ; https://support.apple.com/en-us/102527 | 2026-10-02 | verified online |
| iOS | App Store upload SDK | iOS 26 SDK or later (since 2026-04-28) | Xcode 27.0 satisfies it | https://developer.apple.com/news/upcoming-requirements/?id=04282026a | 2026-10-02 | verified online |
| macOS / Linux | C compilers | clang 21.1.8, gcc 15.2.0 | — | flake (`nix eval`) | 2026-10-02 | flake |
| Windows x64 / ARM64 | zig (MinGW-w64 libc) | **0.16.0** (2026-04-13); bundles MinGW-w64 commit `38c8142f` | `x86_64-windows` Tier 2; `aarch64-windows` Tier 2 with libc, CI ⚠ partial | https://ziglang.org/download/ ; https://ziglang.org/download/0.16.0/release-notes.html | 2026-10-02 | verified online; flake; `windows.yml:86` pins 0.16.0 with its SHA-256 |
| Windows ARM64 | llvm-mingw (alternative to zig for `aarch64-windows-gnu`) | 20260922 (not adopted) | — | https://github.com/mstorsjo/llvm-mingw/releases/tag/20260922 | 2026-10-02 | verified online |
| Windows x64 / ARM64 | OS floor | **Windows 11 24H2, build 26100** | Home/Pro servicing ends 2026-10-13, Enterprise 2027-10-12, LTSC 2029-10-09; 25H2 (26200) is then the consumer floor | https://learn.microsoft.com/windows/release-health/windows11-release-information | 2026-10-02 | verified online |
| Windows ARM64 | x64 emulation | Prism (24H2 and later) | emulated x64 is never native evidence (Stage 23) | https://learn.microsoft.com/windows/arm/apps-on-arm-x86-emulation | 2026-10-02 | verified online |
| Windows x64 | CI runner | `windows-latest` = Windows Server 2025 | — | https://docs.github.com/en/actions/reference/runners/github-hosted-runners | 2026-10-02 | verified online |
| Windows ARM64 | CI runner | `windows-11-arm` (GA for public repositories 2025-08-07) | availability to this repository still unverified ⚠ | https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/ | 2026-10-02 | verified online (GA); repo access unverified |
| Android | NDK | **r29, `29.0.14206865`** (2025-10-06), as PLAN.md Stage 23 names | r28+: 16 KiB ELF alignment by default for arm64-v8a and x86_64; NDK minimum API 21 | https://github.com/android/ndk/releases ; https://github.com/android/ndk/wiki/Changelog-r28 | 2026-10-02 | verified online; `nix develop .#platforms` (2026-10-03) |
| Android | newer NDK (not adopted) | r30, `30.0.16248370` (2026-09-08, current LTS) | — | https://developer.android.com/ndk/downloads ; https://github.com/android/ndk/wiki/Changelog-r30 | 2026-10-02 | verified online |
| Android | `minSdk` | **API 29** | D21 | PLAN.md D21 | 2026-10-02 | decision |
| Android | `targetSdk` / `compileSdk` | **API 36** | Play requires target API 36 for new apps and updates from 2026-08-31 (extension to 2026-11-01); API 37 is stable (2026-06-16) and optional | https://developer.android.com/google/play/requirements/target-sdk ; https://android-developers.googleblog.com/2026/06/Android-17.html | 2026-10-02 | verified online |
| Android | 16 KiB pages | NDK r29 defaults plus AGP ≥8.5.1 zip alignment | Play blocks non-16 KiB updates from 2027-02-01 (the 2025 blog's 2025-11-01 applied to new Android 15+ targets) | https://developer.android.com/guide/practices/page-sizes | 2026-10-02 | verified online |
| Android | JDK | **JDK 17** | AGP 9.4's minimum and default; no official page requires 21 | https://developer.android.com/build/releases/gradle-plugin | 2026-10-02 | verified online; `nix develop .#platforms` (2026-10-03): nixpkgs `jdk17` 17.0.20+2 |
| Android | packaging driver | **Gradle 9.6.0 with AGP 9.4.0** | the direct aapt2/d8/zipalign/apksigner path is not documented as a supported end-to-end build ("invoked by the build tools") | https://developer.android.com/build/releases/gradle-plugin ; https://developer.android.com/tools | 2026-10-02 | verified online |
| Android | build-tools | 37.0.0 | AGP 9.4 needs ≥36.0.0 | `https://dl.google.com/android/repository/repository2-3.xml` | 2026-10-02 | verified online (SDK repository feed); `nix develop .#platforms` (2026-10-03) |
| Android | platform-tools (adb) | 37.0.1 | — | https://developer.android.com/tools/releases/platform-tools | 2026-10-02 | verified online; `nix develop .#platforms` (2026-10-03) |
| Android | cmdline-tools (`sdkmanager`) | 23.0 (`commandlinetools-mac_arm64-16111833_latest.zip`; the feed re-published 23.0 under build 16111833 by 2026-10-03, replacing 15859902) | the page now marks `sdkmanager` deprecated in favour of `android sdk`; 23.0's `sdkmanager --version` prints the Android CLI's version (`1.0.16500706`) | https://developer.android.com/tools/sdkmanager ; SDK repository feed | 2026-10-03 | verified online; `nix develop .#platforms` (2026-10-03) |
| Android | emulator | 37.2.12 | — | SDK repository feed | 2026-10-02 | verified online; `nix develop .#platforms` (2026-10-03) |
| Android emulator | 16 KiB system image | `system-images;android-36;google_apis_ps16k;arm64-v8a` | `adb shell getconf PAGE_SIZE` prints 16384 | `https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml` | 2026-10-02 | verified online; in `.#platforms` on aarch64-darwin (evaluated; realized on the Mac) |
| Android emulator | current and floor images | `system-images;android-36;google_apis;arm64-v8a`, `system-images;android-29;google_apis;arm64-v8a` | — | same feed | 2026-10-02 | in `.#platforms` on aarch64-darwin (evaluated; realized on the Mac); the x86_64 twins of both are realized on x86_64-linux and listed by `sdkmanager --list_installed` (2026-10-03) |
| all GPU slices | wgpu-native | **v27.0.4.0** prebuilt release archives, `release` builds | the same version the flake builds for macOS/Linux; naga 29 (flake `wgpu-utils` 29.0.1) is newer and does not prove wgpu-native acceptance | https://github.com/gfx-rs/wgpu-native/releases/tag/v27.0.4.0 | 2026-10-02 | verified online; flake |
| all GUI slices | FreeType | **2.14.3** (2026-03-22) | `src/stdlib/GUI/btrc.toml` already documents 2.14.3 behaviour | https://download.savannah.gnu.org/releases/freetype/ | 2026-10-02 | verified online; flake |
| host | Nix | 2.34.6 (Determinate, host) | the flake's own `nix` package is 2.34.8 and is not the one in use | recorded host | 2026-09-30 | recorded host |
| host | podman | 5.8.2 | — | recorded host | 2026-09-30 | recorded host |

### wgpu-native archives per slice

Asset names of release v27.0.4.0 (each also has a `-debug` twin). The latest
release is v29.0.1.1; moving to it is a separate change that moves the flake
too, so every slice keeps one version.

| Slice | Archive | SHA-256 |
| --- | --- | --- |
| macOS arm64 | `wgpu-macos-aarch64-release.zip` (the flake builds the same version from source) | `15367c26fdbe6892db35007d39f3883593384e777360b70e6bd704cb5dedde53` |
| Linux x86_64 | `wgpu-linux-x86_64-release.zip` (the flake builds the same version from source) | `271481ef76fbf3ea09631a6079e9493636ecf813cd9c92306c44a1a452991ba1` |
| Windows x64 | `wgpu-windows-x86_64-gnu-release.zip` | `c0c2dbcef3c6a9933a1a1bf7cbdaaebed61a33c833bacb0269662f91536be8bd` |
| Windows ARM64 | `wgpu-windows-aarch64-msvc-release.zip`, the only Windows ARM64 asset | `71271c3671bbcbb8935211dc18bfc1f765326d72f6d1710c93afb0d597000aa9` |
| iOS device | `wgpu-ios-aarch64-release.zip` | `d7adb36b2ca7aa22c40bcf9ac96f1222353533040027db4f95288cdb590c06be` |
| iOS simulator | `wgpu-ios-aarch64-simulator-release.zip` | `1f7c89e4b400dcacd145322f41c5e7a4a2c8b306e74259b8298a55f858279f51` |
| Android arm64-v8a | `wgpu-android-aarch64-release.zip` | `80a93ecfcb14d07f6cadb8bc9bdcf78974f3668b27a89f52a1b006cd14e985a0` |
| Android x86_64 | `wgpu-android-x86_64-release.zip` | `01dfab96efcb980f04da1814c3d0300c06bd3cadb3ee65cc7f1be17ff904523a` |

Each digest is the SHA-256 of the archive file, downloaded on 2026-10-03 from
`https://github.com/gfx-rs/wgpu-native/releases/download/v27.0.4.0/<archive>`
with `nix store prefetch-file`. GitHub's release API was not reachable from
that session, so the digests were not compared with the assets' published
`digest` fields. `nix/wgpu-native-prebuilt.nix` pins the same digests as
fixed-output fetches, so every later fetch checks them; nothing consumes them
until Stage 28 (`tooling-cross-gpu-deps`). To re-check one:

```sh
nix store prefetch-file --hash-type sha256 \
  https://github.com/gfx-rs/wgpu-native/releases/download/v27.0.4.0/<archive>
gh api repos/gfx-rs/wgpu-native/releases/tags/v27.0.4.0 \
  --jq '.assets[] | select(.name | endswith("-release.zip")) | "\(.name) \(.digest)"'
nix build --no-link .#devShells.x86_64-linux.platforms.wgpuNativePrebuilt.<slice>
```

### Windows ARM64 and the MSVC question

D21 says MinGW first, and MSVC only if the arm64 wgpu-native build forces it.
**It does:** v27.0.4.0 and the latest v29.0.1.1 both ship Windows ARM64 only as
`windows-aarch64-msvc` ("Windows builds are built using MSVC on all
architectures and GNU on x64"). So:

- Non-GPU Windows ARM64 artifacts, including btrcc itself, stay on
  `aarch64-windows-gnu` through zig 0.16.0.
- GPU-linked Windows ARM64 artifacts need either the MSVC ABI
  (`aarch64-windows-msvc`: clang plus the Windows SDK and MSVC CRT import
  libraries on the `windows-11-arm` runner, `tooling-windows-ci-arm64-llvm`)
  or a wgpu-native built from source for Rust's `aarch64-pc-windows-gnullvm`
  target with llvm-mingw. Building from source contradicts D21's "pinned
  prebuilt archives", so the MSVC route is the default.
- Linking the MSVC `.lib` into a MinGW image is untested and is not a plan.

The owner confirms this at the Stage 24 target-spec review.

## The `.#platforms` shell

`nix develop .#platforms` is the default dev shell plus the Android SDK, NDK
r29 and JDK 17 above (`nix/platforms.nix`), with `ANDROID_HOME`,
`ANDROID_SDK_ROOT`, `ANDROID_NDK_HOME` and `JAVA_HOME` exported. The default
shell and the CI image stay unchanged. It exists on x86_64-linux,
aarch64-darwin and x86_64-darwin; Google ships no aarch64-linux SDK host tools.
Enter it with a GC root, which Determinate Nix's collector otherwise sweeps:

```sh
nix develop .#platforms --profile ~/.cache/btrc/gcroots/platforms
```

| Host | System images | Closure |
| --- | --- | --- |
| x86_64-linux | `google_apis;x86_64` for API 29 and 36 | 17.75 GB, against the default shell's 4.66 GB (2026-10-03); the emulator's closure is 9.19 GB and the two images 3.38 and 4.59 GB |
| aarch64-darwin | `google_apis;arm64-v8a` for API 29 and 36, and `google_apis_ps16k;arm64-v8a` for API 36 | evaluated only; the Mac realizes it (`MAC-P1-03`) |

The API 29 image brings platform 29 with it, because androidenv composes
images only for the platforms it installs. The SDK licences are accepted in a
nixpkgs import that only this shell evaluates (D8).

The pinned nixpkgs' androidenv feed lacks platform-tools 37.0.1, cmdline-tools
23.0, emulator 37.2.12 and the API 36 `google_apis_ps16k` image.
`nix/android-repo-overlay.json` adds exactly those entries, produced by
nixpkgs' own `androidenv/update.rb` from Google's
`repository2-3.xml` and `sys-img/google_apis/sys-img2-3.xml` on 2026-10-03.
Each archive is fetched against the SHA-1 that feed publishes; re-check an
entry by comparing its `url` and `sha1` with the feed.

Checked on x86_64-linux on 2026-10-03: `java -version` prints 17.0.20,
`adb version` 37.0.1, `zig version` 0.16.0, the NDK's `source.properties`
`Pkg.Revision = 29.0.14206865`, and the NDK's clang builds a strict C11 program
for `aarch64-linux-android29` (ELF64, AArch64) and `x86_64-linux-android29`
(ELF64, X86-64), both with 16 KiB (`0x4000`) segment alignment.

`wine` is not in the shell. Its closure is 1.89 GB, under the 2 GB the
provisioning step allows, but it is supplementary only and the cloud
container's disk could not carry it beside the SDK; it stays an unavailable row.

## Recorded host

The acceptance Mac on 2026-09-30: Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0.
`python3 -m tools.qualification.toolchain` (owner:
`tools/qualification/toolchain.py`) reads the table below, runs each command
read-only on the Mac, and prints every fact that no longer holds. Change a row
here when a provisioning step changes the host. `present` means the command
succeeds and prints the text; `absent` means the command is missing or fails,
or does not print it. On Linux every probe is reported not applicable.

<!-- host-facts:begin -->
| Probe | Command | Expect | Recorded value |
| --- | --- | --- | --- |
| `macos` | `sw_vers -productVersion` | present | `27.0` |
| `xcode-version` | `xcodebuild -version` | present | `Xcode 27.0` |
| `xcode-build` | `xcodebuild -version` | present | `Build version 27A266a` |
| `ios-sdk` | `xcrun --sdk iphoneos --show-sdk-version` | present | `27.0` |
| `ios-simulator-sdk` | `xcrun --sdk iphonesimulator --show-sdk-version` | present | `27.0` |
| `ios-simulator-runtime` | `xcrun simctl list runtimes` | present | `26.4.1` |
| `ios-17-simulator-runtime` | `xcrun simctl list runtimes` | absent | `iOS 17.` |
| `signing-identities` | `security find-identity -v -p codesigning` | present | `0 valid identities found` |
| `zig` | `nix develop --command zig version` | present | `0.16.0` |
| `nix` | `nix --version` | present | `2.34.6` |
| `podman` | `podman --version` | present | `5.8.2` |
| `jdk` | `nix develop .#platforms --command java -version` | present | `openjdk version "17.` |
| `android-sdk` | `nix develop .#platforms --command sdkmanager --list_installed` | present | `build-tools/37.0.0` |
| `adb` | `nix develop .#platforms --command adb version` | present | `Version 37.0.1` |
| `wine` | `wine --version` | absent | `wine-` |
<!-- host-facts:end -->

The `jdk`, `android-sdk` and `adb` rows record the `.#platforms` shell as
checked on x86_64-linux on 2026-10-03. The Mac matches them once `MAC-P1-03`
realizes that shell there (with the `--profile` command above, before the probe:
the probe's 300 s command timeout cannot cover the first download); until then
the probe reports them as mismatches.

wgpu-native 27.0.4.0 is a flake pin, not a host install, so it is checked with
`nix eval`, not by the probe.

## Unavailable evidence

Nothing below is met. Each row names the item that has to close first.

| Missing evidence | Blocking item | Why |
| --- | --- | --- |
| An installed iOS 17.x simulator runtime launching a C11 app; Xcode 27 does not accept keyboard or mouse input on simulators older than iOS 18.0, which limits UI automation there | `tooling-ios-simulator-runtimes` | not installed; the download is a Stage 23 step on the Mac |
| iOS/iPadOS 17 and current on physical iPhone and iPad | `tooling-ios-physical-devices` | no device (D8) |
| Development-signed or distribution-signed iOS builds; notarization | `qualification-signing-accounts`, `tooling-apple-signing` | 0 valid signing identities; no account (D8) |
| API 29, API 36 and 16 KiB AVDs booting | `tooling-android-sdk-ndk` | the SDK and images are in `.#platforms`; no AVD has been created or booted (`MAC-P1-03`) |
| Android hardware: an API 29 vendor and a current 16 KiB vendor | `tooling-android-physical-devices` | no device (D8) |
| Native Windows 11 x64 and ARM64 hardware runs | `tooling-windows-physical` | no hardware (D8) |
| A local Windows 11 ARM VM (`ssh winvm`) | `tooling-windows-vm` | D8 declines a local Windows VM |
| `windows-11-arm` runner access and an `aarch64-windows-msvc` GPU link | `tooling-windows-ci-arm64-llvm` | blocked on a pushed `ci/**` job (D4) |
| An extracted, linked wgpu-native archive per slice | `tooling-cross-gpu-deps` | the digests are pinned (above); linking waits for Stage 28 |
| `wine` for supplementary Windows runs | `platforms-p1-toolchains` | not in `.#platforms` (see [the shell](#the-platforms-shell)); supplementary only (platform-parity.md §2) |
| The D21 target spec in `src/language` carrying these values | `platforms-p1-target-spec` | Stage 24 |

## Revisit

- NDK r30 (`30.0.16248370`) is the current LTS. Moving from r29 is one
  matrix-row change plus a Stage 24 header re-extraction.
- Target API 37 becomes a Play requirement on the next yearly cycle; API 36
  stays the pin until then.
- The 24H2 floor's consumer servicing ends 2026-10-13. If Windows qualification
  starts after that, re-pin the floor to 25H2 (26200).
