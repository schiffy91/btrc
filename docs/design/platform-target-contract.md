# P1 shared target contract (Stage 24)

PLAN.md Stage 24 turns the platform matrix into one target contract that both compilers, the native reader, the link-plan builder and every cache read. Its seven items are:

- `platforms-p1-target-spec`
- `platforms-p1-hosted-abi-targets`
- `platforms-p1-native-import-targets`
- `platforms-p1-native-plan-toolchain`
- `platforms-p1-provider-filters`
- `platforms-p1-cache-identity`
- `platforms-p1-abi-fixture`

This document is Stage 24's serial **Spec** step: the design that the fan-out implements. It changes no code.

**Inputs:**
- D8, D21 and D22;
- [`c-preprocessor-conditionals.md`](c-preprocessor-conditionals.md) (C4), which creates `src/language/targets.toml` and lists what Stage 24 owes it ("What later stages rely on");
- [`platform-parity.md`](platform-parity.md) P1;
- the Stage 22 toolchain matrix, device registry and adaptations. On 2026-10-02 these were on lane `stage22/p0-matrix`, not yet on `main-kn9jxh`: `platform-toolchain-matrix.md`, `platform-adaptations.md` and `docs/qualification/devices.toml`.

**Dependency.** Stage 24's implementation starts after C4's `ccompat-r18-spec` commit (Stage 16) has created `targets.toml` and its generator. Every delta below is written against that file as C4 designs it. If C4 has not landed when Stage 24 starts, Stage 24 waits; it does not create the file a second way.

**Method.** One drafter and three read-only research agents (Apple, Android, Windows) wrote this on 2026-10-02 at `7948af0`. They checked every macro and triple claim with clang 21.1.8 and zig 0.16.0 (`clang -std=c11 -dM -E -x c /dev/null --target=…`, `-###`, and `zig cc -target …`). Two adversarial reviewers and one parity reviewer then read it; [Review](#review) lists every finding and its resolution. Claims that need the Mac, the NDK or a Windows runner are marked **Mac-bound**, **NDK-bound** or **runner-bound** and have a named check.

## Contents

- [Principles](#principles)
- [Current state](#current-state)
- [Decisions](#decisions)
- [1. `platforms-p1-target-spec`](#1-platforms-p1-target-spec)
- [2. `platforms-p1-hosted-abi-targets`](#2-platforms-p1-hosted-abi-targets)
- [3. `platforms-p1-native-import-targets`](#3-platforms-p1-native-import-targets)
- [4. `platforms-p1-native-plan-toolchain`](#4-platforms-p1-native-plan-toolchain)
- [5. `platforms-p1-provider-filters`](#5-platforms-p1-provider-filters)
- [6. `platforms-p1-cache-identity`](#6-platforms-p1-cache-identity)
- [7. `platforms-p1-abi-fixture`](#7-platforms-p1-abi-fixture)
- [Where each part can run](#where-each-part-can-run)
- [Sub-batches and gates](#sub-batches-and-gates)
- [Stage 24 exit, mapped](#stage-24-exit-mapped)
- [Hand-offs](#hand-offs)
- [Owner questions](#owner-questions)
- [Rejected alternatives](#rejected-alternatives)
- [Review](#review)

## Principles

- **One row per artifact identity.** A target row is the unit that every consumer selects, keys and reports. It joins OS, architecture, environment, deployment minimum, triple, data model and sysroot rule. iOS device and simulator are two rows, and so are Windows GNU and MSVC (platform-parity.md §1).
- **The spec is the only source.** `targets.toml` holds every row and value. Generated catalogs are data only. Parsing, selection, host inference and validation belong to the existing owners in each compiler (AGENTS.md rule 9). No hand-written list of OS names, architectures or triples survives anywhere: not in `packages.py`, `Packages.btrc`, `native_imports.py`, `NativeImports.btrc`, `tools/native_plan.py` or `artifacts/archive.py`.
- **The compilers never discover a toolchain.** A compiler process does not run `xcrun`, scan for an NDK or guess a sysroot. It reads the selected row and the sysroot it is given, and it validates that sysroot by reading files. Discovery belongs to the tools that start builds (the test harness, `tools/native_plan.py`, `tools/bench/scripts/bsm_env.sh`).
- **Never the host by accident.** A plan or a compile for a non-host row carries its target arguments explicitly. A row whose target arguments are empty, which is the native Linux and Windows-GNU behaviour of today, builds only on a host of that same row.
- **Parity by construction.** Both compilers parse the same labels, give the same diagnostics, infer the same host and write byte-identical link plans. One parity test covers each of these.
- **Build mode stays out of the row.** platform-parity P1 lists build mode in target identity. Debug/release and DCE are already compile options in every cache key (`--debug`, `--no-dce`; `application/compiler.py:205-222`, `Compiler.btrc:30-41`), and artifact kind is Stage 28's. A row is the target, not the build.
- **Inventories unchanged.** Every change lands in existing files and owners. The 88 Python and 97 btrc production files stay as they are (D21).

## Current state

| Fact | Evidence |
|------|----------|
| Targets exist only as `(operating_system, architecture)` ∈ {linux, macos, windows} × {x86_64, aarch64}, hand-written in each compiler. Aliases `x64` and `arm64` are accepted. The error messages differ between the compilers. | `src/compiler/python/frontend/packages.py:55-56`, `:160-201`; `src/compiler/btrc/frontend/Packages.btrc:25-66` |
| On a host it cannot map, Python raises before resolving. btrcc keeps an empty target, so only target-dependent inputs fail. | `packages.py:168-180`; `Packages.btrc:38-49`, `:2905-2910`, `:1975` |
| btrcc's host comes from `__btrc_target_platform()`/`__btrc_target_architecture()`, which test `__APPLE__`, `__linux__`, `_WIN32`, `__x86_64__`/`_M_X64` and `__aarch64__`/`_M_ARM64`. An iOS build would report `macos`, and an Android build `linux`. | `src/runtime/c/core.c:168-195` |
| A third target table, for release bundles, spells `linux-x64` and `macos-arm64`. Its host map lacks Windows ARM64. | `src/compiler/python/artifacts/archive.py:1306-1400` |
| The link plan writes `"target": {"arch", "os"}` and schema 1, 2 or 4. The builder reads 1, 2 and 4, compiles with the host `cc`/`c++` and never passes `--target`. Frameworks require macOS. | `packages.py:43`, `:564-620`; `Packages.btrc:2370-2403`; `tools/native_plan.py:33-48`, `:312-334`, `:891-966`; `src/language/package-manifest.md:1789-1831` |
| The native reader takes its triple and sysroot only from `BTRC_NATIVE_TARGET` and `BTRC_NATIVE_SYSROOT`. It accepts `{arm64,x86_64}-apple-macosxN.N.N` or `<arch>-(unknown-)linux-gnu` and refuses everything else, Windows included. Objective-C requires macOS. | `src/compiler/python/frontend/native_imports.py:790-806`, `:1018-1075`; `src/compiler/btrc/frontend/NativeImports.btrc:2530-2547`, `:3146-3149` |
| The native read cache keys on the reader argv, which includes `--target=` and `-isysroot <path>`. The reader's own cache re-verifies every recorded input file (inode, size, mtime, digest) before reuse. | `native_imports.py:951-1017`; `src/compiler/btrc/frontend/NativeHeaderProcess.btrc:58-77` |
| Both analyzers take integer widths from the compiler's own process: Python `CIntegerWidths.native()` uses `struct.calcsize`, and btrcc uses its C `LONG_MAX`. | `src/compiler/python/analyzer/types.py:105-125`; `src/compiler/btrc/analyzer/validation/Constants.btrc:316-330` |
| `hosted_abi.toml` `[platform]` is one target-independent union of automatic-header names (about 3,300 functions, macros, objects and types; it includes Windows seams such as `GetFileAttributesA`). Nothing selects it by target. | `src/language/hosted_abi.toml:8108-11400`; `tools/compiler_codegen/hosted_abi.py:128-146`, `:396-433`; `src/tests/python/test_hosted_abi_platform_names.py` |
| Package predicates are `os` and `arch` string arrays over the closed sets. An empty array matches every value. | `src/language/package-manifest.md:64-90`, `:113-116` |
| Cache keys spell the target as the raw option string in btrcc (`options.target`, empty when inferred) and in Python's module units. The prebuilt stdlib archive keys only on the composed stdlib text. | `src/compiler/btrc/Compiler.btrc:30-41`; `src/compiler/btrc/pipeline/ModuleUnits.btrc:1817`, `:2705`; `src/compiler/python/application/modules.py:863`; `src/compiler/python/artifacts/stdlib.py:119-170`, `:276-300` |
| The VS Code extension has no target setting, and the LSP reads no client configuration. | `src/devex/vscode/package.json:146-180`; `src/devex/lsp/` |
| The qualification ledger names six P0 slices (`windows-x64`, `windows-arm64`, `ios-device`, `ios-simulator`, `android-arm64`, `android-x86_64`). | `tools/qualification/schema.py:259-268` |

## Decisions

| Item | Decision |
|------|----------|
| Rows | **Eleven rows** (table in §1.2): the six desktop rows of today, plus `windows-aarch64-msvc`, `ios-aarch64`, `ios-aarch64-simulator`, `android-aarch64` and `android-x86_64`. There is no `ios-x86_64-simulator` (the matrix makes it optional; it needs Rosetta) and no `windows-x86_64-msvc` (D21: MSVC only where wgpu-native forces it). |
| Label grammar | `OS-ARCH[-ENVIRONMENT]`. The environment suffix is omitted when it is the OS's default (`gnu` for linux and windows; none for the others). The existing aliases `x64` → `x86_64` and `arm64` → `aarch64` stay. An explicit default (`windows-x86_64-gnu`) is accepted, and the canonical label omits it. |
| Environment axis | `environment` ∈ {`""`, `gnu`, `msvc`, `simulator`}. linux and windows rows are `gnu` or `msvc`; macOS, iOS device and Android are `""`; the iOS simulator is `simulator`. |
| Deployment minimum | One `minimum_version` column. It is fixed by the row, appears in the triple, and drives the derived version macros. There is no per-build override in Stage 24 (§1.6). |
| Data model | Explicit per-row columns. The generator derives `__SIZEOF_LONG__`, `__SIZEOF_WCHAR_T__`, `__SIZEOF_LONG_DOUBLE__`, `__LP64__`, `_LP64`, `__CHAR_UNSIGNED__` and `__WCHAR_UNSIGNED__` from them, and both analyzers take their widths from the selected row. |
| `__ANDROID_API__` | **Defined, not refused.** It equals `__ANDROID_MIN_SDK_VERSION__`, which equals the row's `minimum_version` (29). clang computes exactly this from the `android29` triple. |
| `TARGET_OS_*` | **Rows, not foreign.** clang 21 predefines 18 `TARGET_OS_*` names and `TARGET_IPHONE_SIMULATOR` for every Darwin triple, and nothing for other triples. They become rows selected on macOS and iOS. `TARGET_CPU_*`, `TARGET_RT_*` and `TARGET_OS_BRIDGE` stay foreign. |
| MSVC `__STDC__` | clang does not define `__STDC__` for `*-pc-windows-msvc`. The `__STDC__` row therefore excludes the `msvc` environment, and `#if __STDC__` on that row reads 0, as in C. |
| Sysroots | A row names a sysroot **kind**: `none`, `xcrun`, `ndk`, `zig-mingw` or `windows-sdk`. The process that starts a compile resolves the path. The compiler validates it from files and hashes a version file into the **sysroot identity**. |
| Hosted availability | `hosted_abi.toml` gains one `[[platform_targets]]` table per row, listing the `[platform]` names that are unavailable there. The optimizer refuses a reachable reference to an unavailable name. |
| Link plan | **Schema 5 is always written.** It adds target identity, target arguments and the sysroot identity. The builder reads 1, 2, 4 and 5, but a legacy plan builds only on the host row it names. |
| Provider filters | Manifests gain an `env` selector. A platform-named module directory (`MacOS`, `IOS`, `Linux`, `Android`, `Windows`) must select only its own OS. |
| Cache identity | Every key spells the **canonical label**, never the raw option. The prebuilt stdlib archive and the builder caches gain the label; the native resolution fingerprint and the builder caches gain the sysroot identity. A matrix test proves each cache misses (or, for the stdlib archive, refuses) across every axis. |
| Host inference | Desktop rows only (`compiler_host = true`, the default environment). Python and btrcc refuse every other host with the same message and at the same point. |

## 1. `platforms-p1-target-spec`

### 1.1 Schema delta to `targets.toml`

C4 creates `schema_version = 1` with `[[targets]]` holding `(operating_system, architecture)`, `[[predefined_macros]]`, and `[conditionals]` holding `undefined_macro_names` and `foreign_macro_names`. Stage 24 makes it **schema 2**. Spec fields are snake_case and are named once. Each generator respells them for its own language (AGENTS.md, Naming): `minimum_version` is `minimum_version` in `abi/generated.py` and `minimumVersion` in `Tables.btrc`.

```toml
schema_version = 2

[aliases]
architectures = { x64 = "x86_64", arm64 = "aarch64" }   # existing spellings
default_environments = { linux = "gnu", windows = "gnu" }

[[targets]]
label = "ios-aarch64-simulator"   # derived; the generator checks it
operating_system = "ios"
architecture = "aarch64"
environment = "simulator"         # "", "gnu", "msvc" or "simulator"
minimum_version = "17.0"          # "" when the triple carries none
triple = "arm64-apple-ios17.0.0-simulator"
triple_aliases = ["arm64-apple-ios17.0-simulator"]
zig_target = ""                   # zig cc -target spelling, or ""
target_arguments = ["--target=arm64-apple-ios17.0.0-simulator"]
sizeof_pointer = 8
sizeof_long = 8
sizeof_wchar_t = 4
sizeof_long_double = 8
char_signed = true
wchar_signed = true
sysroot_kind = "xcrun"            # none, xcrun, ndk, zig-mingw, windows-sdk
sysroot_name = "iphonesimulator"  # xcrun SDK name; "" otherwise
compiler_host = false             # may a compiler run here (host inference)
objective_c = true                # Objective-C adapters allowed
frameworks = true                 # [[native.frameworks]] allowed
```

`[[predefined_macros]]` keeps C4's shape, `name, value, operating_systems, architectures, environments`, and now uses `environments`. `[conditionals]` keeps both lists. The changes are below.

**Generator rules.** These are added to C4's rules, in the `HostedAbiManifestError` style:
- `label` equals `operating_system-architecture`, plus `-environment` when the environment is non-empty and is not the OS's default environment. Labels are unique.
- `operating_system` ∈ {linux, macos, windows, ios, android}; `architecture` ∈ {x86_64, aarch64}.
- The environment fits the OS: linux takes `gnu`; windows takes `gnu` or `msvc`; macos and android take `""`; ios takes `""` or `simulator`.
- `default_environments` names only OSes that have rows. Each OS with a default environment has exactly one row per architecture in that default.
- `triple` is in the form clang's cc1 uses (`-###`): `arm64`/`x86_64` for Apple, `aarch64`/`x86_64` elsewhere, a three-part Apple version, and the `unknown` vendor on linux and android. For the `msvc` environment, cc1's form carries an MSVC compatibility version: without one, clang appends its own default (`aarch64-pc-windows-msvc19.33.0` here) or the installed Visual Studio's on a runner, so the reader's echo would vary by host. The row therefore pins it: `aarch64-pc-windows-msvc19.40.0` (Visual Studio 2022 17.10, the oldest the `windows-11-arm` image is expected to carry; a runner-bound check in `tooling-windows-ci-arm64-llvm` confirms `cl.exe` ≥ 19.40). A pinned triple fixes cc1's triple and `_MSC_VER` (checked: `--target=aarch64-pc-windows-msvc19.40.0` gives `-triple aarch64-pc-windows-msvc19.40.0` and `_MSC_VER 1940`). A version in the triple equals `minimum_version`, except this MSVC compatibility version, which is a toolchain floor and not a deployment minimum:
  - Apple: `macosx<minimum_version>.0` or `ios<minimum_version>.0`;
  - Android: `android<minimum_version>`.
- `triple_aliases` are other spellings that clang maps to the same cc1 triple. They are unique across rows, and none equals a row's `triple`.
- `target_arguments` is exactly `["--target=" + triple]` on every row. These are the **clang** arguments: the native reader, the hosted-platform extractor, the macro oracle and every clang-driven build use them. zig takes `-target <zig_target>` instead and never receives them (zig rejects `-target x86_64-windows-gnu --target=x86_64-w64-windows-gnu` with `UnknownOperatingSystem`); its cc1 triple, `x86_64-unknown-windows-gnu`, differs only in the vendor and gives a byte-identical `-dM` dump. The host's own `cc` (gcc on Linux) receives neither (§4.2).
- `sizeof_pointer` is 8 in every row: there is no 32-bit row. `sizeof_long` ∈ {4, 8}, and it is 4 exactly when the OS is windows. `sizeof_wchar_t` ∈ {2, 4}, and it is 2 exactly when the OS is windows. `sizeof_long_double` ∈ {8, 16}.
- `sysroot_name` is non-empty exactly when `sysroot_kind` is `xcrun`.
- `compiler_host` rows are exactly the six desktop default-environment rows.
- `objective_c` and `frameworks` are true exactly on macos and ios.
- A `[[predefined_macros]]` row may not name a **derived** macro (§1.3).
- C4's "every predefined name is reserved" rule gains one exemption: a name starting with `TARGET_` is allowed when the row's `operating_systems` ⊆ {macos, ios}.

**Generated forms.**
- **Python:** `GeneratedTargetRow` gains every column above. `TARGET_ROWS` holds the rows in label order. `TARGET_ARCHITECTURE_ALIASES` and `TARGET_DEFAULT_ENVIRONMENTS` are new tables. `TARGET_PREDEFINED_MACRO_ROWS` holds the hand-written rows and then the derived ones, sorted by name and then label. `TARGET_SPEC_FINGERPRINT` stays.
- **btrc:** `GeneratedTargetRow` gains the same fields in camelCase (`minimumVersion`, `tripleAliases`, `targetArguments`, `sizeofLong`, `charSigned`, `sysrootKind`, `compilerHost`, `objectiveC` and the rest). `GeneratedHostedAbiData` gains memoized `architectureAliases()` and `defaultEnvironments()`, both as `Map<string, string>`.
- Neither generated module owns parsing, label rendering or selection. They are data, and generated data owns no behaviour.

### 1.2 Rows

| Label | Triple | Aliases | `zig_target` | Min | long / wchar / ldouble | `char` | Sysroot kind | Host |
|-------|--------|---------|--------------|-----|------------------------|--------|--------------|------|
| `linux-x86_64` | `x86_64-unknown-linux-gnu` | `x86_64-linux-gnu` | `x86_64-linux-gnu` | | 8 / 4 / 16 | signed | `none` | yes |
| `linux-aarch64` | `aarch64-unknown-linux-gnu` | `aarch64-linux-gnu` | `aarch64-linux-gnu` | | 8 / 4 / 16 | unsigned | `none` | yes |
| `macos-x86_64` | `x86_64-apple-macosx14.0.0` | `x86_64-apple-macosx14.0` | | 14.0 | 8 / 4 / 16 | signed | `xcrun` `macosx` | yes |
| `macos-aarch64` | `arm64-apple-macosx14.0.0` | `arm64-apple-macosx14.0`, `aarch64-apple-macosx14.0.0` | | 14.0 | 8 / 4 / 8 | signed | `xcrun` `macosx` | yes |
| `windows-x86_64` | `x86_64-w64-windows-gnu` | `x86_64-w64-mingw32` | `x86_64-windows-gnu` | | 4 / 2 / 16 | signed | `zig-mingw` | yes |
| `windows-aarch64` | `aarch64-w64-windows-gnu` | `aarch64-w64-mingw32` | `aarch64-windows-gnu` | | 4 / 2 / 8 | signed | `zig-mingw` | yes |
| `windows-aarch64-msvc` | `aarch64-pc-windows-msvc19.40.0` | | `aarch64-windows-msvc` | | 4 / 2 / 8 | signed | `windows-sdk` | no |
| `ios-aarch64` | `arm64-apple-ios17.0.0` | `arm64-apple-ios17.0` | | 17.0 | 8 / 4 / 8 | signed | `xcrun` `iphoneos` | no |
| `ios-aarch64-simulator` | `arm64-apple-ios17.0.0-simulator` | `arm64-apple-ios17.0-simulator` | | 17.0 | 8 / 4 / 8 | signed | `xcrun` `iphonesimulator` | no |
| `android-aarch64` | `aarch64-unknown-linux-android29` | `aarch64-linux-android29` | | 29 | 8 / 4 / 16 | unsigned | `ndk` | no |
| `android-x86_64` | `x86_64-unknown-linux-android29` | `x86_64-linux-android29` | | 29 | 8 / 4 / 16 | signed | `ndk` | no |

The research agents read every value from clang 21.1.8 (`-dM -E`, `-###`). `wchar_signed` is false on linux-aarch64 and android-aarch64 (`unsigned int`) and on every Windows row (`unsigned short`); clang defines `__WCHAR_UNSIGNED__` on exactly those rows. The rows also record two facts that the C ABI fixture (§7) checks:
- `long double` is binary128 on Android x86_64 (`__LDBL_MANT_DIG__` 113), unlike x87 on Linux x86_64 (64). Both have size 16.
- `long double` is the same as `double` on every Apple arm64 row, on Windows ARM64 (both environments) and on MSVC generally.

**Slices.** Each `TARGET_SLICES` entry in `tools/qualification/schema.py` maps to one or more rows: `windows-x64` → `windows-x86_64`; `windows-arm64` → `windows-aarch64`, plus `windows-aarch64-msvc` for GPU-linked artifacts; `ios-device` → `ios-aarch64`; `ios-simulator` → `ios-aarch64-simulator`; `android-arm64` → `android-aarch64`; `android-x86_64` → `android-x86_64`. The slice names stay qualification vocabulary. `test_target_contract.py` checks the mapping: a slice without a row fails, and so does a non-desktop row that no slice names. The six desktop rows are exempt, because P0's slices cover only the new platforms.

### 1.3 Predefined-macro deltas

Every value below is clang 21.1.8 `-std=c11 -dM -E` for the row's triple.

**Moved or widened hand rows.**

| Name | C4 selection | Stage 24 selection |
|------|--------------|--------------------|
| `__linux__`, `__linux`, `__unix__`, `__unix`, `__ELF__` | linux | linux, android |
| `__APPLE__`, `__MACH__` | macos | macos, ios |
| `__arm64__`, `__arm64` | macos and aarch64 | macos, ios; aarch64 |
| `__ANDROID__` | `undefined_macro_names` | a row on android |
| `__STDC__`=1 | every target | every environment except `msvc` |
| `__CHAR_UNSIGNED__` | linux and aarch64 | derived (below) |

**New hand rows.**
- `__APPLE_EMBEDDED_SIMULATOR__`: ios with `simulator`.
- `__MINGW32__`, `__MINGW64__` and `__SEH__`: windows with `gnu`. With the environment axis, these name an ABI, not a toolchain version, and `#ifdef __MINGW32__` is common in real headers. zig and clang agree on all three.
- `_M_ARM64`=1: windows with `msvc` and aarch64. clang defines `_M_*` only for the msvc environment, never for gnu, so the row is exact. (`_M_X64`/`_M_AMD64`=100 would join it with a `windows-x86_64-msvc` row; there is none.)
- `TARGET_OS_MAC`: macos and ios.
- `TARGET_OS_OSX`: macos.
- `TARGET_OS_IPHONE` and `TARGET_OS_IOS`: ios.
- `TARGET_OS_SIMULATOR` and `TARGET_IPHONE_SIMULATOR`: ios with `simulator`.
- `TARGET_OS_EMBEDDED`: ios with `""` (the device only).
- Each of these names is also given a row with value 0 on the macos and ios rows where clang defines it as 0, because clang **defines** them there, so `defined(TARGET_OS_IOS)` is 1 on macOS.
- The remaining clang names have value 0 on every macos and ios row: `TARGET_OS_DRIVERKIT`, `TARGET_OS_LINUX`, `TARGET_OS_MACCATALYST`, `TARGET_OS_NANO`, `TARGET_OS_TV`, `TARGET_OS_UEFI`, `TARGET_OS_UIKITFORMAC`, `TARGET_OS_UNIX`, `TARGET_OS_VISION`, `TARGET_OS_WATCH`, `TARGET_OS_WIN32` and `TARGET_OS_WINDOWS`.
- C4's rule that rows sharing a name select disjoint targets holds: each name has one row for value 1 and as many value-0 rows as its 0 set needs to be a union of `operating_systems × architectures × environments` products. `TARGET_OS_EMBEDDED` needs two (macos; ios with `simulator`).
- **Selector spelling.** C4 reads an empty selector list as "every value". To select the empty environment, a list names `""` explicitly: the iOS device is `environments = [""]` with ios, and "every environment except `msvc`" is `environments = ["", "gnu", "simulator"]`. The generator accepts `""` as a list element only in `environments`.
- **Reserved for `#define`/`#undef`.** Before Stage 24 every predefined name started with `_` and was refused by the existing underscore rule. The `TARGET_*` rows do not, so C4's M3 gains one clause: `#define` or `#undef` of any predefined-macro row name or derived name, on any row, is refused with M3's message. Otherwise `#define TARGET_OS_IPHONE 1` would change `#if` in that file and redefine a clang predefine in C. Conditioning and the analyzer apply it through the same predicate (C4, "Source macro rules"); `test_preprocessor_conditionals.py` gains the refusal.

**Derived macros.** The generator emits these from row columns, and a hand row may not name them:

| Macro | Value | When |
|-------|-------|------|
| `__SIZEOF_LONG__` | `sizeof_long` | every row |
| `__SIZEOF_WCHAR_T__` | `sizeof_wchar_t` | every row |
| `__SIZEOF_LONG_DOUBLE__` | `sizeof_long_double` | every row |
| `__LP64__`, `_LP64` | 1 | `sizeof_long` = 8 and `sizeof_pointer` = 8 |
| `__CHAR_UNSIGNED__` | 1 | not `char_signed` |
| `__WCHAR_UNSIGNED__` | 1 | not `wchar_signed` |
| `__ANDROID_API__`, `__ANDROID_MIN_SDK_VERSION__` | `minimum_version` as an integer | android |
| `__ENVIRONMENT_OS_VERSION_MIN_REQUIRED__` | `MMmmpp` (170000, 140000) | macos, ios |
| `__ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__` | `MMmmpp` | macos |
| `__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__` | `MMmmpp` | ios |

`__SIZEOF_LONG_DOUBLE__` was left out of C4 because MinGW and MSVC disagree on windows-x86_64. Now that the environments are separate rows, it is well defined. `__ANDROID_API__` is the decision C4 deferred. clang defines it as an alias of `__ANDROID_MIN_SDK_VERSION__`, both equal to the triple's API level, so the table and the C compile cannot disagree.

**Still left out (I2).** These are toolchain identity, invocation identity or CPU feature sets, as C4 decided:
- `__GNUC__`, `__clang__`, `_MSC_VER`, `__STDC_HOSTED__`, `__OPTIMIZE__`, `__gnu_linux__` (still left out: Android does not define it);
- `_MSC_FULL_VER`, `_MSC_EXTENSIONS`, `_MSC_BUILD`, `_INTEGRAL_MAX_BITS` and `__MSVCRT__`: clang's values are its own MSVC emulation (19.33), not a real toolchain's;
- `__STDC_NO_THREADS__` (msvc), `__STRICT_ANSI__` and the gnu-only `__WIN32__`/`__WINNT__` spellings;
- `__ARM_FEATURE_*`, `__SSE*__` and `__NO_MATH_ERRNO__`;
- `__OBJC_BOOL_IS_BOOL`.

**`[conditionals]`.**
- `undefined_macro_names` loses `__ANDROID__` and keeps `__cplusplus`.
- `foreign_macro_names` loses the 16 names of C4's list that became rows (15 `TARGET_OS_*` names, all but `BRIDGE`, plus `TARGET_IPHONE_SIMULATOR`). `TARGET_OS_NANO`, `TARGET_OS_UEFI` and `TARGET_OS_UIKITFORMAC` were never listed and are new rows. It keeps `TARGET_OS_BRIDGE`, `TARGET_CPU_*` and `TARGET_RT_*`, which clang never defines, and gains `__BIONIC__` (bionic's `<sys/cdefs.h>`).

**C4's test 3** (`src/tests/python/test_target_macro_table.py`) takes its triples from `TARGET_ROWS[*].triple` instead of a list in the test. It covers all eleven rows on Linux, because clang needs no sysroot for `-dM`. It runs the **unwrapped** clang binary (the wrapper's `-fPIC` makes `*-pc-windows-msvc` fail with "unsupported option '-fPIC'", and it warns on every foreign target); the test reads its store path from the wrapper's `nix-support/orig-cc` and runs `<orig-cc>/bin/clang`. clang dumps `#define __ANDROID_API__ __ANDROID_MIN_SDK_VERSION__`, so the test resolves an object-like alias to its target's value before comparing, as C4 already does for `__BYTE_ORDER__`. Two checks stay Mac-bound:
- `xcrun clang` (Apple clang from Xcode 27A266a) defines the same `TARGET_OS_*` set for the four Apple rows.
- `<TargetConditionals.h>` from the iOS 27.0 SDK accepts the predefined values.

The test names them as classified skips off the Mac.

### 1.4 One target owner per compiler

**Python.** Parsing, labels and host inference live in a new class `TargetRepository` in `abi/hosted.py`, beside `HostedAbiRepository`, which already owns the generated ABI data. `abi` is the one package that every consumer may import under `test_compiler_api.py:270-284`: `frontend` and `artifacts` may import it, and neither may import the other. `TargetRepository` provides:
- `parse(value)`:
  - It splits on `-` into two or three parts and refuses any empty part. So `macos-aarch64-`, `linux-x86_64-`, `-` and `""` are refused, and an empty environment is never spelled in a label.
  - It applies `TARGET_ARCHITECTURE_ALIASES` to the architecture.
  - When the environment is absent, it uses `TARGET_DEFAULT_ENVIRONMENTS.get(os, "")`.
  - It looks up `(os, arch, environment)` in `TARGET_ROWS`.
  - On failure it raises `TargetSelectionError(ValueError)` with the message in §1.5.
- `host(system=None, machine=None)` (§1.7).
- `labels()`.

`frontend/packages.py::PackageTarget` keeps its role as the frontend's value:
- **Fields:** `operating_system`, `architecture` and `environment`. `row` and `label` are properties.
- **Construction:** `parse` and `coerce` delegate to `TargetRepository`.
- **Deleted:** `_TARGET_OPERATING_SYSTEMS` and `_TARGET_ARCHITECTURES`.
- **`as_dict()` is deleted.** Schema 5 writes the full identity (§4), and no writer is left on the `{"arch", "os"}` form.

**Also in Python:**
- `NativeDeclaration.selected_for` and the binding and provider predicates gain the `env` selector (§5).
- `artifacts/archive.py::TargetCatalog` builds its default host map from `TargetRepository.host()`, an `abi` import that is allowed. Its release names, `linux-x64` and the rest, are rendered from the `compiler_host` rows with the inverse of `TARGET_ARCHITECTURE_ALIASES`. This adds the missing Windows ARM64 host. Its constructor keeps the signature that `test_compiler_api.py:338-343` pins.
- The CLI's `--target` help and its validation (§1.5) go through a new `application/compiler.py` API, `Compiler.target_labels()` and `Compiler.select_target(raw)`, because `cli/` may import only `application` (`test_compiler_api.py:276-278`).

**btrc.** `frontend/Packages.btrc::FePackageTarget` gets the same fields (`operatingSystem`, `architecture`, `environment`), the `row()` and `label()` accessors, and `parse(raw)`, `host()` and `hostFrom(…)` (§1.7). They read `GeneratedHostedAbiData` rows. `validOperatingSystem` and `validArchitecture` are deleted. The btrc frontend imports only generated data, which C4 introduces; today `Resolver.btrc:3-15` imports none.

**Ripple, both compilers.**
- `--target`'s metavar and help become `OS-ARCH[-ENV]`: `cli/compiler.py:79-83`, `cli/Driver.btrc:202`, `:237-245`, and `tools/FrontendMain.btrc:29`, `:49-52`. The help text lists the labels.
- Every message that spells a target uses the label, so `windows-aarch64` and `windows-aarch64-msvc` stay distinguishable:
  - "no provider for target" (`packages.py:1012`, `Packages.btrc:1865`);
  - "native header bindings require --target OS-ARCH" (`Packages.btrc:1975`, which becomes unreachable once §1.7 removes the empty target);
  - `tools/native_plan.py:320`, `:966`.
- No test pins the old target messages. A grep of `src/tests` and `tools` for `unsupported package target`, `cannot infer a supported package target` and `requires OS-ARCH` finds nothing.

### 1.5 One accepted set, one message

Both compilers accept exactly the eleven labels, each optional explicit default environment, and each architecture alias. That is 11 canonical labels plus 19 alias spellings, 30 in all, and the test lists every one:
- `x64` or `arm64` on each of the 11 rows (including `windows-arm64-msvc` and `ios-arm64-simulator`);
- `-gnu` on each of the 4 linux and windows-gnu rows;
- both forms together on those 4 rows.

They reject everything else with one message, character for character:

```text
unsupported target '<raw>'; expected one of android-aarch64, android-x86_64, ios-aarch64, ios-aarch64-simulator, linux-aarch64, linux-x86_64, macos-aarch64, macos-x86_64, windows-aarch64, windows-aarch64-msvc, windows-x86_64
```

The list is the sorted canonical labels. Today's messages differ: compare `packages.py:181-192` with `Packages.btrc:51-66`.

**Where the check runs.** Both CLIs check in this order: argument errors first, then the target, then reading the input. Each prints `error: <message>` with no `package resolution failed:` prefix, and exits 1. A target error therefore appears even when the input path does not exist, and the test uses a missing input path to prove it.
- **Python today.** `--target bogus` ends in a raw traceback, because `PackageTarget.coerce` runs at `packages.py:2528`, outside the `try`. The CLI also reads the source (`cli/compiler.py:230`) before `compile()`. With Stage 24, `CompilerCommand` calls `Compiler.select_target` right after argument parsing. `select_target` returns a `CompilerFailure` of the existing kind `CompilerFailureKind.INPUT` (`application/results.py:30-39`).
- **btrcc today.** An empty `options.target` means "infer the host" (`Driver.btrc:238-245`; `Packages.btrc:2906`). So `--target ""` silently selects the host, and `--target "" --target linux-x86_64` passes the only-once check. Stage 24 adds a `targetGiven` flag to `BtrccOptions`: an explicit empty value is the §1.5 error in both CLIs, and a repeated `--target` is refused whatever its first value.
- **The LSP.** Only the LSP's empty `btrc.target` setting means "the host".

**Round-trip.** Every spelling accepted today parses to the same `(os, arch)`, with an environment of `""` or the default. Its canonical label is `os-arch`, the same as today's normalized spelling. After Stage 24, all spellings of one target give identical cache keys, link plans and bundle names. The keys themselves change once: btrcc used the raw spelling, and every plan becomes schema 5.

### 1.6 Deployment minimum

- `minimum_version` is fixed per row: macOS 14.0 (owner question Q1), iOS 17.0 (D21), Android 29 (D21). It is empty for linux and windows, whose triples carry no version. The Windows 11 floor is a runtime and packaging fact in the matrix, not a compile flag.
- There is no `--min-version` option. A later stage that needs one adds a row, or a validated override that changes the triple and every derived macro together. Never a separate `-D`.
- **`BTRC_NATIVE_TARGET`** stays accepted, for BTRSmith's `bsm_env.sh` and the existing tests. When set, it must equal the row's `triple` or one of its `triple_aliases`. Otherwise both readers refuse with:

  ```text
  BTRC_NATIVE_TARGET '<value>' does not match target <label> (<triple>)
  ```

  - It no longer selects the triple; the row does.
  - The Stage 22 matrix proposes zig spellings (`x86_64-windows-gnu`) as triples. Those are `zig_target` values. clang maps them to a different vendor (`x86_64-unknown-windows-gnu`), so they are not aliases. The matrix's slice table is updated to the row triples when it merges.
  - Today's macOS regex accepts any `N.N.N` version, so a value other than 14.0 now refuses. Every in-repo user spells 14.0.0 (`tools/bench/scripts/bsm_env.sh:29`, `src/tests/python/native_import_fixtures.py`).

### 1.7 Host inference

Both compilers infer the host only when `--target` is absent. Both reduce the host to a pair of **normalized tokens**, an OS token in {`macos`, `linux`, `windows`} and an architecture token in {`x86_64`, `aarch64`}, or to nothing. They then select the `compiler_host` row in that OS's default environment.

- **Python** (`TargetRepository.host(system, machine)`). It maps `platform.system().lower()`: `darwin` → `macos`, `linux` → `linux`, `windows` → `windows`. It maps `platform.machine().lower()`: `x86_64` and `amd64` → `x86_64`; `aarch64` and `arm64` → `aarch64`. Everything else maps to nothing, including Python 3.13's `ios` and `android` and MSYS2's `msys_nt-…`.
- **btrcc** (`FePackageTarget.hostFrom(int platform, int architecture)`). It maps `__btrc_target_platform()`'s codes 1/2/3 to `macos`/`linux`/`windows`, and `__btrc_target_architecture()`'s codes 1/2 to `x86_64`/`aarch64`. Code 0 maps to nothing.
  - Stage 24 leaves the runtime helpers alone, which avoids a D14 re-capture here. Stage 25 owns the iOS and Android codes ([Hand-offs](#hand-offs)).
  - A btrcc for a non-host row cannot exist: `SelfhostBundleBuilder` and `TargetCatalog` accept only `compiler_host` rows.
- **Different bases, documented.** Python infers from the interpreter process: x86_64 under Rosetta, and x86_64 for x64 Python on Windows ARM64. btrcc infers from the target it was built for. The parity test does not assume the two agree on one machine. It takes btrcc's expected row from the binary's machine type through `ExecutableFormatInspector`, and Python's from the interpreter.
- **Unrecognized host, both compilers.** The compile stops at the target check (§1.5), before reading any source, with this message and exit 1:

  ```text
  error: cannot infer a supported target from this host; pass --target
  ```

  - **No host details.** The message names no host, because btrcc's only facts are code 0 and 0, and it has no `uname` binding (`src/stdlib/Platform.btrc` has none, and `uname` is not in `hosted_abi.toml`).
  - **What it replaces.** It replaces btrcc's empty target (`Packages.btrc:38-49`). From Stage 24 every compile needs a row, because the analyzer widths come from it (§1.8).
  - **The LSP keeps C4's lazy D13.** On an unrecognized host with no `btrc.target`, the workspace shows this message once as a workspace diagnostic. It then analyses with the named fallback row `LSP_FALLBACK_TARGET = "linux-x86_64"`, defined in `src/devex/lsp/workspace/workspace.py`, so hovers and widths work. It conditions lazily, as C4 designs, so D13 still appears at a file's first conditional. Compiles never use the fallback.
- **Testing.** One table in `test_target_contract.py` holds rows of `(system, machine) | (platform code, architecture code) → tokens → expected label or message`. It drives the Python string seam and the btrc integer seam. Every row whose tokens are equal must give the same answer.
  - For an end-to-end unknown host, a btrcc is built once with `-DBTRC_TARGET_PLATFORM_OVERRIDE=0`. That seam already exists (`core.c:170-171`) and `test_application_directories_contract.py:80` already uses it.

### 1.8 Data model in both analyzers

- **Python.** `analyzer/types.py::CIntegerWidths` gains `for_target(row)`. It is built from `sizeof_long`, with char 8, short 16, int 32 and long long 64; a generator rule pins those four across every row.
  - `NumericLiteralSemantics` and `SemanticAnalyzer` take a target row.
  - About 118 call sites construct them with no target, most of them tests and the LSP (`workspace.py:319`, `:323`, `:352`). For those, the default is `TargetRepository.host()`'s row, so they keep today's widths on every supported host.
  - `CIntegerWidths.native()` is deleted, so no analysis depends on `struct.calcsize`.
- **btrc.** Three sites use the C compiler's own `long` limits, and all three switch to the row's `sizeofLong`:
  - `analyzer/validation/Constants.btrc::ConstantValidator` (`:38`), `builtinCastRange` (`:333-337`);
  - `syntax/Literals.btrc::IntegerLiteral.typeName()` (`:105-140`), which types an unsuffixed or `l`/`u` literal as `long` or `long long` through `LONG_MAX`/`ULONG_MAX`. It gains a `long`-width parameter. Its callers pass the selected row's width: the class method `analyzer/Operators.btrc:138-142` (`integerLiteralType`) and `frontend/NativeImports.btrc:1530`.
  - The row reaches them through the analyzer context and the native importer, both filled by `CompilerPipeline`.
- **Widths contract.** C4's widths check covers `__CHAR_BIT__`, `__SIZEOF_SHORT__`, `__SIZEOF_INT__` and `__SIZEOF_LONG_LONG__` against both analyzers' widths. It gains `__SIZEOF_LONG__` against `for_target` for every row, and stays in `test_hosted_abi_contract.py`.
- **Observable change.** A Linux → `windows-x86_64` compile now types `long` as 32 bits:
  - `long x = 3000000000;` is refused, with the existing out-of-range message;
  - the constant cast-range checks for `long` and `unsigned long` use the 32-bit range;
  - the unsuffixed decimal literal `3000000000` is typed `long long` in both compilers. Today both compilers type it from the host (`long` on every LP64 host, whatever the target). Switching only Python would have split them, which would change overload choice and f-string formats, so all three btrc sites move in the same commit.

  Neither analyzer folds the hosted `LONG_MAX` macro. It reaches C unchanged, and C's `<limits.h>` gives the target's value. `test_target_data_model.py` pins all three in both compilers.
- **Release C files.** `Makefile:128-129` generates `dist/btrcc-windows.c` with no `--target`, so the host row's LP64 widths and availability would analyse a Windows build. It gains `--target windows-x86_64`. The portable `dist/btrcc.c` is generated once and cross-compiled for the four LP64 desktop rows (`Makefile:150-169`). The release gate regenerates it with `--target` for each of those rows and requires byte-identical output. If any row differs, that row gets its own C file.

### 1.9 MSVC

D21 adopts MSVC only where wgpu-native forces it. The Stage 22 matrix (lane `stage22/p0-matrix`) records that it does for Windows ARM64: wgpu-native v27.0.4.0 and v29.0.1.1 publish no `windows-aarch64-gnu` asset, only `wgpu-windows-aarch64-msvc-release.zip` ("Windows builds are built using MSVC on all architectures and GNU on x64"). So `windows-aarch64-msvc` is a row, the environment axis is real, and C4's deferred "`__STDC__` row, if MSVC is adopted" is decided in §1.3.

**The row is provisional.** PLAN Stage 28's `platforms-w1-toolchain-abi-route` owns the Windows ABI-route decision. Stage 24 adds the row so the environment axis, the `__STDC__` row and the cache matrix are exercised by a real second environment; Stage 28 confirms or removes it. Removing it is one row, its macro selections and its availability table; no consumer names it. This is recorded as a PLAN.md amendment in the Stage 24 progress entry.

- **Not a compiler host.** btrcc for Windows ARM64 stays `aarch64-windows-gnu` (`compiler_host` is false on the MSVC row).
- **Toolchain identity stays out.** `_MSC_VER` and its relatives name the MSVC toolchain version, so they stay out (I2). `_M_ARM64` is a row (§1.3). Portable code tests `__aarch64__` or `__x86_64__`, which clang defines in both environments.
- **Mac-bound and runner-bound evidence.** A link of a btrc program against the MSVC CRT needs the Windows SDK, which only the `windows-11-arm` runner has (`tooling-windows-ci-arm64-llvm`, Stage 23). Before that, Linux checks the macro table and a header-free `-c` compile for the row. Its `windows-sdk` sysroot validation is runner-bound.

### 1.10 LSP target setting

The setting is `btrc.target`: a string, default `""` (the host), with enum suggestions generated from the rows. It goes in `src/devex/vscode/package.json` `contributes.configuration` and reaches the server in two ways:
- in `initializationOptions.target`;
- on `workspace/didChangeConfiguration`.

The LSP owner is `src/devex/lsp/workspace/workspace.py`:
- It parses the setting through `PackageTarget.parse`. An invalid label is one workspace diagnostic with the message from §1.5, and the workspace falls back to the host.
- It rebuilds the lazy `ConditionalEnvironment` (C4).
- It invalidates the `UnitCache` entries, because the key already holds the target label (C4, §6).

`FileUnit.parse` stops using the host directly. The VS Code test (`src/tests/vscode/`) and an LSP test (`src/tests/lsp/test_target_setting.py`) check:
- a switch from `linux-x86_64` to `windows-x86_64` flips a `#if _WIN32` region;
- an invalid label gives one diagnostic;
- a reopened workspace keeps the setting.

### 1.11 Tests (sub-batch 1)

| Test | What it proves |
|------|----------------|
| `src/tests/btrc/test_target_contract.py` (new; both compilers) | The accepted set: the 11 labels and their 19 aliases, and a rejection battery (`linux-x86`, `ios-x86_64-simulator`, `macos-arm64-gnu`, `windows-x86_64-msvc`, `android-arm64-29`, `ios-aarch64-device`, `macos-aarch64-`, `linux-x86_64-`, an explicit `--target ""`, `-`, `linux-`, and a repeated `--target`). Accepted labels give identical canonical labels and rejected ones identical messages and exit 1, through `btrcc --target X --emit-link-plan` and `btrcpy`, with an input path that does not exist (so no source is read). Host inference: the seam table in both compilers and the unknown-host message. Every spelling accepted today round-trips (§1.5). Slices map to rows (§1.2). Only `compiler_host` rows reach `TargetCatalog`. |
| `src/tests/python/test_hosted_abi_contract.py` (extended) | Each generator rule in §1.1 has a failing fixture. The generated rows equal the spec. Derived macros come only from columns. The widths contract covers `__SIZEOF_LONG__`. |
| `src/tests/python/test_target_macro_table.py` (C4's test 3, extended) | All 11 triples from the rows against clang 21. Mac-bound: Apple clang and `TargetConditionals.h`. |
| `src/tests/btrc/test_target_data_model.py` (new; both compilers) | For each of `linux-x86_64`, `windows-x86_64` and `windows-aarch64-msvc`: `long` literal and cast-range refusals are the same in both compilers, and they follow the row, not the host. |
| `src/tests/btrc/test_preprocessor_conditionals.py` (C4's, extended) | The per-target selection fixture runs over all 11 rows. `TARGET_OS_IPHONE` and `__ANDROID_API__ >= 29` select. `TARGET_CPU_ARM64` is I3. |
| `src/tests/lsp/test_target_setting.py` (new) | §1.10. |

**Exit evidence:**
- the generated-source check;
- the tests above, which run on Linux;
- the btrcc fixture rebuild and the bootstrap fixed point;
- zero analyzer warnings on the three self-host entries;
- `boundary-check` unchanged. No boundary source has a conditional or a `long` literal near the 32-bit range; the run confirms it.

## 2. `platforms-p1-hosted-abi-targets`

### 2.1 What exists

`[names]` is btrc's hosted namespace: the C names a btrc source may use without declaring them. `[platform]` is the subset that comes from automatic platform headers rather than ISO C. It is one union over macOS, glibc and the Windows seam, and nothing selects it by target (§Current state). So a Linux program that calls `arc4random_uniform` passes btrc's analysis and fails only in the C compiler, and on iOS or Android nothing would say which names exist.

### 2.2 Spec delta (`hosted_abi.toml`, schema 3)

```toml
[[platform_targets]]
target = "android-aarch64"              # a targets.toml label
unavailable_functions = ["accessx_np", "arc4random_addrandom", "..."]
unavailable_macros = ["..."]
unavailable_objects = ["..."]
unavailable_types = ["..."]
unavailable_typedefs = ["..."]
source = "ndk 29.0.14206865 sysroot, API 29, extracted <date> by tools/hosted_platform.py"
```

**Representation.** Each row lists the `[platform]` names **unavailable** on it, rather than the available ones. The lists stay short for the Unix-like rows. Each extraction is then one reviewable diff, and the union stays where it is.

**Generator rules:**
- There is exactly one table per target row, and `target` names an existing label. The generator loads `targets.toml` to check it.
- Each list is sorted, unique, and a subset of the matching `[platform]` list.
- `source` is non-empty.
- A name in `[names]` but not in `[platform]` (ISO C, runtime and native names) is available everywhere and may not appear in these lists.
- A runtime helper (`origin = "runtime"`) may never be listed. The runtime is ported, not filtered.

**Generated forms:**
- **Python:** `HOSTED_PLATFORM_UNAVAILABLE`, a `dict[str, frozenset[str]]` keyed by label for each of the five kinds.
- **btrc:** `GeneratedHostedAbiData.platformUnavailable(string label)` returns a memoized `Set<string>` per kind. It is emitted as small methods, like the existing tables (CLAUDE.md: one large constructor cost about 90% of compiling the compiler).
- `HOSTED_ABI_FINGERPRINT` covers the new tables, so `ToolchainFingerprint('full')` and btrcc's identity follow them unchanged.

### 2.3 Extraction

The extraction is a read-only `tools/hosted_platform.py`, owned by the class `HostedPlatformExtractor`. It sits beside `tools/native_plan.py`, outside `tools/compiler_codegen/`, whose file list is normative in `compiler-structure.md`; the generator never runs it. The Stage 24 fan-out runs it. For one row, it compiles a probe translation unit and reads the declared names with the existing native header reader in a names-only mode, or with `clang -Xclang -ast-dump=json` when the reader is unavailable. The probe includes the row's automatic headers (the same list the C emitter's prologue includes) with exactly the flags the row's real C build uses, including `-I src/runtime/windows -include src/runtime/windows/btrc_win_compat.h` on windows-gnu rows (`Makefile:121`). The rule is that availability equals what the row's C compile declares, so the check (§2.4) is never stricter than C on a toolchain that builds today, uses the row's `target_arguments` and resolved sysroot, and passes no `-D__ANDROID_API__`: the triple already sets `__ANDROID_MIN_SDK_VERSION__`, which current bionic gates on, and a `-D` would split the two macros. The output is `[platform] − declared`.

| Row(s) | Sysroot | Where |
|--------|---------|-------|
| `linux-*` | the flake's glibc headers (the aarch64 row through zig's `aarch64-linux-gnu` glibc headers when the host is x86_64) | Linux |
| `windows-x86_64`, `windows-aarch64` | zig 0.16.0's `lib/libc/include/any-windows-any` (MinGW-w64 `38c8142f`) plus `src/runtime/windows/` | Linux |
| `android-*` | the NDK r29 sysroot (`toolchains/llvm/prebuilt/linux-x86_64/sysroot`) at API 29 | Linux after Stage 23 puts the NDK in `nix develop` (NDK-bound) |
| `macos-*`, `ios-*` | `xcrun --sdk macosx|iphoneos|iphonesimulator --show-sdk-path` | Mac-bound |
| `windows-aarch64-msvc` | the Windows SDK and MSVC headers on `windows-11-arm` | runner-bound. Until extracted, its table is conservative: `windows-aarch64`'s list plus every name that only MinGW, winpthreads or the btrc compat overlay provides (POSIX and pthread names), so the row can only refuse too much, never too little. Its `source` says `"conservative copy pending runner extraction"`. A Stage 24 exit row tracks it as **awaiting runner**. |

**Bionic gating.** An API-gated bionic name hidden at API 29 is unavailable at the floor, which is correct (`__INTRODUCED_IN`). C11 `<threads.h>` (API 30) is the researched example of a hidden one. The names introduced at 28–29 (`getrandom`, `posix_spawn`, `aligned_alloc`, `timespec_get`, `reallocarray`) are available at the floor and are the borderline cases the extraction test spot-checks. The extractor reads them through the triple, with no separate column.

### 2.4 Consumer: reachable references only

The check runs in the **optimizer stage** (pipeline stage 5, not PLAN Stage 5), after reachability, not in the analyzer. A stdlib function that names a macOS-only symbol and is unreachable from a Linux program is removed before emission today, and the analyzer cannot know that.

- **Python.** `ir/optimizer.py::IROptimizer` gains `refuse_unavailable_hosted(target)`. Once the reachability graph is final, it walks the reachable functions' calls and identifier references to hosted names, the reachable globals' initializers and the kept extern declarations. On references whose name is in `HOSTED_PLATFORM_UNAVAILABLE[label]`, it reports the one that sorts first by `(function, name)`. Emission order is not stable across whole-program and `--module-units` builds, where btrcc optimizes in forked worker groups, it raises a `CompilerFailureKind.ANALYSIS` failure:

  ```text
  '<name>' is not available on target <label> (hosted ABI); referenced from <function>
  ```

- **btrc.** The same check lives in `ir/optimization/Optimizer.btrc`'s reachability owner (`IROptimizer`), with the same message and the same `(function, name)` order. Under `--module-units` the owner process runs it over the merged reachability result, never inside a worker.
- **Scope.** Live `#include` lines and `.c` imports are not inspected; the C compiler owns them. A user-declared prototype of a hosted name (`extern int fork(void);`) is still a hosted-name reference: btrc already refuses redeclaring hosted names in user code.
- **`--no-dce`** keeps every function, so the check sees every reference. That matches C, where an undeclared call in an emitted function already fails under `-std=c11`.
- **Stdlib on new targets.** A stdlib module that names an unavailable symbol, inside a function a program reaches, now fails at btrc time with the name and the target. The mobile and Windows stdlib adaptations (Stages 25–26, `platform-adaptations.md`) clear these with C4 `#if` guards or providers. For bionic, this is the safety net that platform-parity P1 asks for ("minimum-version code must not reference an unavailable symbol unguarded"), because `__INTRODUCED_IN` hides a declaration above the triple's API level. For Apple it is weaker: the iOS 27.0 SDK declares newer APIs with `API_AVAILABLE(ios(18.0))` rather than hiding them, so names-only extraction reports them available at 17.0. Stage 24 relies on clang's `-Wunguarded-availability` in the C compile for those; reading availability attributes into the tables is left to a later stage and recorded as a gap.

### 2.5 Tests (sub-batch 2)

| Test | What it proves |
|------|----------------|
| `src/tests/python/test_hosted_abi_platform_names.py` (extended) | Every row has a table. The lists are subsets. No ISO C or runtime name is listed. `source` is set. Spot names: `fork` unavailable on both ios rows; `GetFileAttributesA` unavailable on every non-windows row; `arc4random_uniform` available on macos, ios and android but not linux-gnu; `explicit_bzero` available on linux and android. |
| `src/tests/btrc/test_hosted_availability.py` (new; both compilers) | For `linux-x86_64`, `windows-x86_64`, `ios-aarch64` and `android-aarch64`: a reachable reference gives the identical message and exit 1; an unreachable one compiles; a C4-guarded one compiles. The `--no-dce` behaviour. |
| Corpus and BTRSmith | The full corpus through both compilers, and BTRSmith's `application-frontend-check`, stay green on linux-x86_64 and macos-aarch64. This proves the desktop lists are not too strict. |

**Exit evidence:** the generated-source check; the tests above; the corpus and bootstrap; the desktop BTRSmith check on the Mac. The `ios-*` and `macos-*` extractions are committed from the Mac. A missing extraction fails the generator, so no row can ship without a table.

## 3. `platforms-p1-native-import-targets`

### 3.1 Both readers derive the triple from the row

- **Python.** In `frontend/native_imports.py`, inside the owner around `:777-806`, the hand-written patterns are deleted. The target is `plan.target.row.triple`. If `BTRC_NATIVE_TARGET` is set, it must equal the triple or an alias (§1.6). Codec decoding uses `expected_target=row.triple`. If the reader echoes a normalized triple, `NativeHeaderCodec` compares the echo with the triple or its aliases.
- **btrc.** `frontend/NativeImports.btrc::matchesTarget` (`:2530-2547`) is replaced by the same row lookup, with the same message.
- **Arguments.** `_reader_arguments` (`:1018-1075`) and its btrc twin (`:3102`) build the argument list from the row and the validated sysroot:

| Row kind | Arguments after `-std=…` |
|----------|--------------------------|
| macos, ios | `--target=<triple> -isysroot <sysroot>`; Objective-C adds `-fblocks -fobjc-arc` |
| linux | `--target=<triple> -isysroot <sysroot> -isystem <sysroot>/usr/include` (unchanged) |
| android | `--target=<triple> --sysroot=<sysroot>` (clang then searches `usr/local/include`, `usr/include/<arch>-linux-android` and `usr/include`, checked with `-###`) |
| windows gnu | `--target=<triple> -nostdinc -isystem <zig lib>/include -isystem <sysroot>/include/any-windows-any -isystem <runtime root>/windows`, where `<runtime root>` is each compiler's existing runtime-asset root (the checkout's `src/runtime` for btrcpy; the installed data root beside `--stdlib-dir` for btrcc). The two argv strings may then differ in that path, which changes only each compiler's own reader-cache key, never the decoded semantics. In this row, `<sysroot>` is zig's `lib/libc` and `<zig lib>/include` is zig's bundled clang resource headers, searched first as `zig cc -v -E` shows |
| windows msvc | `--target=<triple> -isystem <VC include> -isystem <SDK ucrt/um/shared>`, all from `windows-sdk` validation (runner-bound) |

- **Objective-C** is allowed when `row.objective_c` is true: macOS and iOS. The error at `:1068` becomes `Objective-C adapters require an Apple target`.
- **C++ adapters** keep `_cxx_toolchain_includes`, with the row's triple and sysroot.

### 3.2 Sysroot validation and identity

**Owners.** The new class `NativeSysroot` (Python, in `frontend/native_imports.py`) and `FeNativeSysroot` (btrc, in `frontend/NativeImports.btrc`). They are new classes in existing files, so the inventory is unchanged. Each takes the row and the `BTRC_NATIVE_SYSROOT` path and returns the validated path plus a 64-hex **identity**, or the error `native imports require a valid <kind> sysroot for <label>: <reason>`.

| Kind | Validation (files only, no process) | Identity file |
|------|-------------------------------------|---------------|
| `none` | the directory exists (today's rule) | `""` |
| `xcrun` | `SDKSettings.json` parses; `CanonicalName` starts with `sysroot_name`; `Version` is at least the row's `minimum_version` | `SDKSettings.json` |
| `ndk` | `usr/include/android/api-level.h` exists; `usr/lib/<arch>-linux-android/<minimum_version>/` is a directory; `../../../../../source.properties` (the NDK root above `toolchains/llvm/prebuilt/<host>/sysroot`) has `Pkg.Revision` | `source.properties` |
| `zig-mingw` | `include/any-windows-any/windows.h` and `include/any-windows-any/_mingw_mac.h` exist | `include/any-windows-any/_mingw_mac.h` (it carries the MinGW-w64 version: `__MINGW64_VERSION_MAJOR` 13 in zig 0.16.0) |
| `windows-sdk` | runner-bound; `Include/<version>/um/windows.h` exists | `Include/<version>` directory name plus the `SDKManifest.xml` digest |

The identity is SHA-256 over `kind\0name\0<file bytes>`. It enters the native resolution fingerprint (`native_imports.py:782-788`, `btrc-native-resolution-v4`), and link plan v5 (§4).

**Rejected:** running `xcrun` from the compiler. That would add a process and an environment-dependent answer to both compilers, which goes against the principle that the compilers never discover a toolchain.

### 3.3 Real header extraction for five new triples

The Stage 24 exit's "five new triples" are:
- `arm64-apple-ios17.0.0`
- `arm64-apple-ios17.0.0-simulator`
- `aarch64-unknown-linux-android29`
- `x86_64-unknown-linux-android29`
- `x86_64-w64-windows-gnu`

Windows has a row today, but no reader triple. `aarch64-w64-windows-gnu` comes along with x64 at no extra cost. MSVC extraction is W1 (platform-parity P1: "full Windows SDK extraction is W1").

`src/tests/btrc/test_native_import_targets.py` (new; both compilers) imports one C fixture package per row. Its header, `src/tests/native/target_import/target_import.h`, declares:
- a record with `long`, `wchar_t`, `size_t`, `bool` and a nested array;
- an enum;
- a callback typedef;
- a variadic function;
- a function returning a record by value.

The test checks two things:
- The reader's semantic JSON is byte-identical between the two compilers for each triple.
- Record sizes, alignments and offsets equal the row's data model: `long` is 4 bytes on windows. This compares against a `_Static_assert` translation unit compiled with the same arguments (§7).

The test also covers the native-type differences between targets. The values are known per triple: `long` is 4 on windows, `char` is unsigned on android-aarch64, `wchar_t` is 2 on windows.

**Skips.** Each triple whose sysroot is missing is a classified skip in `src/tests/fixtures/expected-skips/{macos,linux-devcontainer,windows}.json`, with its reason: Mac-bound, NDK-bound or runner-bound.

**Exit evidence:**
- the Windows row passes on Linux (zig MinGW);
- the Android rows pass on Linux once Stage 23's NDK is in `nix develop`;
- the iOS rows pass on the Mac.

## 4. `platforms-p1-native-plan-toolchain`

### 4.1 Link-plan schema 5

Both compilers always write schema 5. Its JSON is the canonical form of today (sorted keys, `separators=(",", ":")`, `ensure_ascii=False`, trailing newline), so the two compilers' output is byte-identical:

```json
{
  "defines": [],
  "emitted-units": ["/abs/out.unit-1.c"],
  "frameworks": [],
  "generated-units": [],
  "headers": [],
  "include-directories": [],
  "linker-language": "c",
  "packages": [],
  "pkg-config": [],
  "schema": 5,
  "target": {
    "arch": "aarch64",
    "environment": "simulator",
    "label": "ios-aarch64-simulator",
    "minimum": "17.0",
    "os": "ios",
    "triple": "arm64-apple-ios17.0.0-simulator"
  },
  "toolchain": {
    "sysroot": {"identity": "", "kind": "xcrun", "name": "iphonesimulator"},
    "target-arguments": ["--target=arm64-apple-ios17.0.0-simulator"]
  },
  "units": []
}
```

**Rules:**
- `generated-units` and `emitted-units` keep their schema 2 and 4 meanings and stay optional. They are present exactly when non-empty, as today.
- `target` is the row identity. `environment` and `minimum` are always present, possibly empty.
- `toolchain.target-arguments` is the row's `target_arguments`, copied.
- `toolchain.sysroot.identity` is §3.2's identity when the compile read native headers through a sysroot, and `""` otherwise.
- The plan never holds a sysroot path. Paths are host facts: the builder resolves them again and checks them against `identity` when it is non-empty.
- `NATIVE_LINK_PLAN_SCHEMA = 5` (`packages.py:43`), and the btrc writer (`Packages.btrc:2400`) writes 5. The 1/2/4 selection logic is deleted from both writers.

**Owners.** Python `NativeLinkPlan.as_dict` (`packages.py:564-620`) and btrc's link-plan writer in `Packages.btrc` (`:2370-2403`; the class that owns `canonicalJson()`). One commit changes both, Python first.

**Documentation.** `src/language/package-manifest.md` "Native link-plan schemas" gains a schema-5 paragraph. Its statement that "schema 1 is retained for plans without adapters" is replaced by "new compilers write schema 5; readers keep 1, 2 and 4 for host-native plans only". Its predicate section lists the new OS set and `env` (§5).

### 4.2 Builder (`tools/native_plan.py`)

- **`ROOT_FIELDS` gains `toolchain`.** The schema check accepts `(1, 2, 4, 5)`. Field sets are exact per schema: `toolchain` is required at 5 and refused below.
- **Target validation.** `TARGET_OPERATING_SYSTEMS` and `TARGET_ARCHITECTURES` are deleted. The builder imports `TARGET_ROWS` from `src.compiler.python.abi.generated` (it already imports the Python compiler's `artifacts.publication`). At schema 5, `target` must equal the row for `label` exactly. At schemas 1, 2 and 4, `{os, arch}` must map to a `compiler_host` row equal to `PackageTarget.host()`, or the plan is refused: `legacy native link plan for <os>-<arch> cannot be built on host <label>; regenerate it as schema 5`.
- **Drivers.**
  - **The plan's row is the host row** (`PackageTarget.host()`): the builder uses `cc`/`cxx` as today, with no target arguments. This keeps gcc on Linux and the `test-c11` matrix unchanged.
  - **Otherwise**, the driver comes from the row, and the builder refuses a row whose driver it cannot find (`no toolchain for <label>: <what is missing>`), so it never falls back to the host compiler:
    - `zig_target` non-empty (windows-gnu rows, linux rows cross-built from another host): `zig cc -target <zig_target>`, as the `Makefile`'s cross builds do. `target-arguments` are not passed.
    - `xcrun` rows: `xcrun --sdk <name> clang` with `target-arguments` and `-isysroot`.
    - `ndk` rows: `$NDK/toolchains/llvm/prebuilt/<host>/bin/clang` with `target-arguments` and `--sysroot=`.
    - `windows-sdk` rows: clang with `target-arguments` and the SDK include and library set (runner-bound).
- **Discovery.** Sysroot resolution, which lives only here and in the test harness, is a new class `TargetToolchain` in `tools/native_plan.py`:
  - `xcrun`: `xcrun --sdk <name> --show-sdk-path`;
  - `ndk`: `$ANDROID_NDK_HOME`, else `$ANDROID_HOME/ndk/29.0.14206865`;
  - `zig-mingw`: the `.lib_dir` field of `zig env` (ZON output in 0.16.0, not JSON) joined with `libc`.

  It recomputes the identity with the same function the compilers use, imported from `src.compiler.python.frontend.native_imports.NativeSysroot`, and refuses a mismatch: `sysroot identity changed since the plan was emitted`.
- **Frameworks** require `row.frameworks`, which is macOS or iOS. `pkg-config` is refused for ios, android and `windows-sdk` rows.
- **Caches.** `NativeBuildReport.target` becomes the label. The object cache, `_DarwinLinkReceipt` and `_RetainedGenerations` keys gain the label and the sysroot identity (§6).

### 4.3 Frozen v5 schema and the test agent

The JSON in §4.1 is the **frozen** schema for the fan-out's native-plan owner and test agent. Changing it after the spec gate needs a new review.

| Test | What it proves |
|------|----------------|
| `src/tests/btrc/test_link_plan_parity.py` (new; both compilers) | For each of the 11 rows, over three fixture packages (plain C units; a C++ unit with generated units; `--emit-units` split), both compilers' `--emit-link-plan` output is byte-identical. One golden per row lives under `src/tests/fixtures/link_plan_v5/`. No toolchain is needed, so this runs on Linux. |
| `src/tests/python/test_native_plan_builder.py` (extended) | v5 field sets; legacy plans only on the host row; empty target arguments refused off-host; the frameworks and pkg-config row rules; sysroot identity mismatch; `NativeBuildReport.target` is the label. |
| `src/tests/python/test_native_plan_cross.py` (new) | Builds a v5 plan for `windows-x86_64` with zig on Linux and checks the PE machine with `ExecutableFormatInspector`. Builds `android-aarch64` with the NDK (NDK-bound) and checks the ELF machine and 16 KiB alignment (`-z max-page-size=16384`, which clang 21 already passes). Builds `ios-aarch64-simulator` on the Mac (Mac-bound) and checks the Mach-O platform `IOSSIMULATOR`. |

**Exit evidence:**
- link-plan parity green for all 11 rows on Linux;
- the cross builds: windows on Linux, android with the NDK, ios on the Mac;
- `test_native_plan_builder.py` and every existing link-plan consumer test updated to schema 5, which flips the `"schema": 1` goldens;
- BTRSmith's Makefiles read plans only through `tools/native_plan.py`, so the reader change is invisible to them. Host-row builds keep today's driver and flags (§4.2: no `--target` on the host row), so BTRSmith's macOS objects keep today's minimum OS, which comes from `MACOSX_DEPLOYMENT_TARGET` or the SDK default (`tools/perf.py:288` lists it as a build input). The builder records the effective deployment target in `NativeBuildReport` and, when it differs from the row's `minimum_version`, reports it as a warning, not a failure: Stage 28's "host builds byte-identical to before" stays true. Evidence: BTRSmith's Mac objects built before and after sub-batch 3 compare equal (`LC_BUILD_VERSION` included), plus its `application-frontend-check`. Owner question Q1 decides whether the row minimum later becomes binding on host builds.

## 5. `platforms-p1-provider-filters`

### 5.1 Manifest delta

These predicate rules hold for `[[package.providers]]` and every `[[native.*]]` table:
- `os` ∈ the five operating systems (from `TARGET_ROWS`, not a list in the manifest owner).
- `arch` is unchanged.
- The new `env` is a string array over the environment values of `targets.toml`, generated into both parsers as `TARGET_ENVIRONMENTS` (`""`, `gnu`, `msvc`, `simulator`). `""` selects the empty environment, so `os = ["ios"], env = [""]` selects the iOS device alone, with the same spelling as `targets.toml` selectors (§1.3). An omitted or empty array matches every value, as for `os`.

The owners are `NativeDeclaration`, `NativeBinding` and the provider record in `packages.py`, and `FeNativeDeclaration`, `FeNativeBinding` and the provider record in `Packages.btrc`. Each gains `environments`, and `selected_for` tests it. The env values are spelled once, in `targets.toml`; `package-manifest.md` documents them by reference. Both parsers refuse unknown values with `unsupported env '<value>' in <table>; expected "", gnu, msvc or simulator`.

**Disjointness.** The existing rule that providers for one module are disjoint "even on inactive targets" is checked over all rows (the label set), not over the old 3 × 2 grid.

### 5.2 Platform-directory rule

This rule closes "zero foreign SDK imports". A provider implementation or native declaration whose module path contains a platform directory segment selects only that platform:

| Segment | Required `os` |
|---------|---------------|
| `MacOS` | `["macos"]` |
| `IOS` (D24 names `GUI/IOS`) | `["ios"]` |
| `Linux` | `["linux"]` |
| `Android` | `["android"]` |
| `Windows` | `["windows"]` |

The selector must be exactly that one OS, never empty. Both manifest parsers enforce it with `module '<module>' lives under <Segment>/ and must select os = ["<os>"]`.

**Other selection rules:**
- `[[native.frameworks]]` and Objective-C bindings must select a subset of the rows where `frameworks` or `objective_c` is true.
- `[[native.pkg-config]]` must not select ios or android.

### 5.3 The provider matrix

`src/tests/python/test_target_provider_matrix.py` (new) resolves, for each of the 11 rows:
- every stdlib group manifest;
- `examples/` packages with a `btrc.toml`;
- the native test packages.

It resolves with every export imported, through the reference package resolver. A parity variant in `src/tests/btrc/` does the same through btrcc's `FrontendMain --target`. It then classifies every selected provider, binding, header, framework and pkg-config record:
- **foreign:** a platform segment or framework whose OS differs from the row's. Zero is required: this is the exit.
- **missing:** a configured module with no provider for the row. It is reported, and is expected for `GUI`, `Audio`, `Tray` and `UI` on mobile until Stages 31–35. The test compares the missing set with `docs/design/platform-inventory.toml`'s `missing`/`os-restricted` cells and fails on any disagreement, so the two stay one denominator.
- **portable:** the rest.

**Audit, part of the item.** Every stdlib native declaration with an empty `os` array now also matches ios and android. The provider-filter writer lists them, about a dozen per the P0 inventory, and gives each an explicit `os` or a reason to stay portable. Today every platform-directory record in `src/stdlib/GUI/btrc.toml` already selects its own OS (`:27-44` binds `Linux/SDL.h` with `os = ["linux"]`), so the rule should hold there from the start. The matrix will show whether any other manifest breaks it.

**Exit evidence:** zero foreign records for every row through both frontends; the missing set equals the inventory; `make test` green. All of this runs on Linux, because it reads only manifests.

## 6. `platforms-p1-cache-identity`

### 6.1 One rule

Every cache key that can depend on the target spells the **canonical label** from `PackageTarget.label`/`FePackageTarget.label()`, never the raw option string. A key that reads a sysroot also includes the sysroot identity.

- The spec fingerprint is already covered: `abi/generated.py` and `Tables.btrc` are part of the toolchain identity (C4, "Caches and fingerprints").
- The data model, the minimum and the environment are functions of the label.

### 6.2 Changes

| Cache | Key today | Stage 24 |
|-------|-----------|----------|
| btrcc whole-program artifacts (`Compiler.btrc:30-41`) | raw `options.target`, link plan JSON | Label instead of the raw string. The v5 plan adds environment, minimum, triple and sysroot identity. |
| Python whole-program artifacts (`application/compiler.py:197-222`) | `cache_identity()` includes `native_plan.canonical_json()` | No code change: the v5 plan carries the identity. The test proves it. |
| Module units (`modules.py:863`; `ModuleUnits.btrc:1817`) | raw `options.target` | Label. |
| btrc `ValidationRecords` (`ModuleUnits.btrc:2705`) | `target=options.target` | `target=<label>`; context version `validation-record-v5`. |
| Prebuilt stdlib archive (`artifacts/stdlib.py:75-170`, `:276-300`) | hash of the composed stdlib text | **Changed.** `StdlibArchiveManifest.SCHEMA` goes from 5 to 6, because `valid()` requires the exact field set. The manifest gains `target` (the label) and `target_spec` (`TARGET_SPEC_FINGERPRINT`). The archive holds emitted C, which depends on widths and hosted availability, not only on conditioned text. It is an artifact with one slot per stdlib directory, not a cache, so a mismatch is not a silent miss: `load` raises the existing `ArchiveVersionError` with `prebuilt stdlib archive was built for <label>; regenerate it for <label>`. The matrix (§6.3) asserts that refusal, which is the poisoning guard for this row. |
| Native header reads (`native_imports.py:951-1017`; `NativeHeaderProcess.btrc:67-77`; the reader's own cache in `tools/NativeHeaderReader.cpp`) | the argv (`--target=`, `-isysroot <path>`); the reader re-checks every recorded file's inode, size, mtime and content digest before reuse (`NativeTraceVerifier`, `NativeFileTrace`, `:1306-1340`, `:1518+`, `:2465`) | **Unchanged.** An in-place Xcode or NDK update already misses there. The request stays `btrc.native-read.v1`: the reader accepts only that exact five-key request (`:2747`), so a v2 would break every pinned reader, including `bsm_env.sh`'s. The `--target=` in the argv separates rows. |
| Native resolution fingerprint (`native_imports.py:782-788`; btrc twin) | `btrc-native-resolution-v3` | v4, with the label and the sysroot identity. |
| Directive cache, stdlib AST cache | conditioned text (C4) | Unchanged. Conditioned text is a pure function of raw text and label. |
| LSP `UnitCache` (C4) | target label plus environment identity | Unchanged in shape. The label is now the `btrc.target` setting's (§1.10). |
| Builder object cache, `_DarwinLinkReceipt`, `_RetainedGenerations` (`tools/native_plan.py`) | target `os-arch`; Darwin receipts only on macOS | Label plus sysroot identity. Darwin receipts apply to macos and ios rows; any other row relinks (`:1182-1184`). |
| Test-harness btrcc cache (`build/test-btrcc/<fingerprint>`) | compiler sources and the C compiler | Unchanged. It is the host compiler, not a target artifact. |

### 6.3 The cache-poisoning matrix

`src/tests/btrc/test_target_cache_identity.py` is new and covers both compilers. For each cache above that a compile can reach, and for each **axis pair** below, it runs four steps:
1. A cold compile under A.
2. A warm compile under B. It must miss, and its output must equal a cold compile under B.
3. A warm compile under A. It must hit, and its output must equal step 1.
4. A spelling alias of A. It must hit.

The counters are those of C4's test plan: Python `module_units_lowered`/`reused` and btrcc `{"lowered", "reused"}`. Artifact hits and misses are read from the existing cache reports.

| Axis | A | B | Runs on |
|------|---|---|---------|
| architecture | `linux-x86_64` | `linux-aarch64` | Linux |
| OS and data model | `linux-x86_64` | `windows-x86_64` | Linux |
| environment (ABI) | `windows-aarch64` | `windows-aarch64-msvc` | Linux (no link) |
| environment (device/simulator) | `ios-aarch64` | `ios-aarch64-simulator` | Linux for emission; Mac for native reads |
| OS with the same data model | `linux-aarch64` | `android-aarch64` | Linux |
| spelling | `macos-arm64` | `macos-aarch64` | must **hit** in step 2 |
| sysroot identity | one row, two stub sysroots differing only in the identity file | | Linux, with a stub header reader (`BTRC_NATIVE_HEADER_READER`, as `test_native_header_cache.py` does) |
| spec fingerprint | the same row before and after a generated-table change | | covered by the toolchain fingerprint; asserted once |

The program uses `#if defined(_WIN32)`, `long`, a hosted name unavailable on one side, and one native binding. Every step's emitted C or error is compared, not only the counters. The prebuilt stdlib archive is exercised through `build_stdlib_archive` under A and B.

**Quiet re-measure** (Mac, PLAN Stage 24 exit). After this sub-batch, Stage 3's `budget_bench` runs no-op, edit and the cold transpile (the data-model and optimizer changes touch cold paths), on both frontends, measuring instructions retired and peak footprint at `--jobs 1`. ≤0.3% passes (standing approvals). Each run names the C compiler that built btrcc.

**Exit evidence:** the matrix is green on Linux for every row that needs no SDK, and on the Mac for the iOS native-read row; the quiet re-measure is recorded in PLAN.md.

## 7. `platforms-p1-abi-fixture`

The fixture is the Stage 25 "ABI fixture runs on every host" input. Stage 24 builds and statically checks it; Stage 25 runs it.

**Files.** `native/` is a non-corpus directory (`corpus_files.NON_CORPUS_DIRECTORIES`) with a dedicated driver:
- `src/tests/native/target_abi/TargetAbi.btrc` is the program. It imports `target_abi.h` through the package's `btrc.toml` binding, and it calls and receives the following:
  - `long`, `unsigned long`, `size_t`, `ptrdiff_t`, `wchar_t`, `bool`, `char`, `signed char` and `long double` (passed through `double` helpers where btrc lacks a `long double` value type);
  - a record with mixed widths;
  - a packed record (`#pragma pack(1)`), passed and returned by value;
  - a nullable pointer;
  - a variadic `int sum(int count, ...)`;
  - a callback, `int (*)(void*, long)`, invoked from C with a btrc context;
  - `_Atomic`-free atomics through the runtime helpers;
  - an enum.

  It prints one line per check.
- `src/tests/native/target_abi/target_abi.c` and `target_abi.h` are the C side (one casing per pair, as `background_job_probe.c/.h`), declared by `src/tests/native/target_abi/btrc.toml` (`[[native.sources]]`, `[[native.headers]]`, `[[native.bindings]]`). They include `_Static_assert`s generated from the row (§7.1).
- `src/tests/native/target_abi/target_abi.expected` holds the golden lines, in the native drivers' `<name>.expected` convention. They are the same on every row, because the program prints facts it checked, not raw sizes.

### 7.1 Static half (Stage 24)

`src/tests/btrc/test_target_abi_fixture.py` (new; both compilers) renders `target_abi_static.h` from the selected row:
- `_Static_assert(sizeof(long) == <sizeof_long>, …)`, and likewise for `wchar_t`, `long double`, pointers and `size_t`;
- the signedness of `char` and `wchar_t` (`(char)-1 < 0`);
- `offsetof` for each record field, as the native reader reported it for that triple (§3.3).

It then compiles the fixture's C, and each compiler's generated C for `TargetAbi.btrc`, with the row's `target_arguments` and sysroot. It compiles only, with no link and no run:

| Row | Compile | Where |
|-----|---------|-------|
| `linux-*`, `windows-*` (gnu) | yes | Linux (zig for windows and aarch64) |
| `windows-aarch64-msvc` | header-free `-c` with `-ffreestanding` on the static half only | Linux; the full compile is runner-bound |
| `android-*` | yes | NDK-bound |
| `macos-*`, `ios-*` | yes | Mac-bound |

**Exit evidence:** every row compiles where its toolchain exists, and both compilers' generated C compiles for every such row. Each row without a toolchain in the run is a classified skip naming its bound.

### 7.2 Dynamic half (Stage 25)

The same files are run by each Stage 25 host lane, and the golden is compared. Nothing is added in Stage 24 beyond the driver's `run` mode, which skips with "Stage 25 host lane" until a host executor exists.

## Where each part can run

| Part | Linux / CI (this container class) | Mac | NDK (Linux or Mac) | Windows runner |
|------|-----------------------------------|-----|--------------------|----------------|
| Spec, generator, labels, host seam, data model, LSP setting | all | — | — | — |
| Macro table oracle | all 11 rows with clang 21 | Apple clang and `TargetConditionals.h` | — | — |
| Hosted availability extraction | linux, windows-gnu | macos, ios | android | windows-msvc |
| Availability check (optimizer) | all rows (it reads tables) | — | — | — |
| Native reader per triple | windows-gnu | ios, macos | android | windows-msvc (W1) |
| Link plan v5 parity | all 11 rows | — | — | — |
| Cross builds through the builder | windows-gnu, linux-aarch64 | ios, macos | android | windows-msvc link |
| Provider matrix | all | — | — | — |
| Cache-poisoning matrix | all rows without native reads | the ios native-read row | android native-read row | — |
| ABI fixture, static half | linux, windows-gnu, windows-msvc static asserts | macos, ios | android | windows-msvc full compile |
| Quiet M11 re-measure | — | required | — | — |

## Sub-batches and gates

PLAN.md Stage 24 fixes the order: spec; ABI names; importers plus native plan; filters plus cache. Each sub-batch is gated before the next merges (D5). Every behaviour commit changes Python first and then its btrc twin, in one commit. Where PLAN's fan-out names a pair ("2 consumer writers (Python, btrc)", "an importer pair"), the Python writer hands its finished, tested change to the btrc writer on one branch, and the btrc writer lands both as one commit; neither half merges alone.

1. **Spec** (`platforms-p1-target-spec`). Serial: the spec owner is the only writer of `targets.toml` and of `tools/compiler_codegen/hosted_abi.py`'s `TargetManifest`.
   - **Commit 1a:** the schema-2 spec, the generator, the generated modules, and the `test_hosted_abi_contract.py` and `test_target_macro_table.py` extensions. No behaviour change.
   - **Commit 1b:** `PackageTarget`/`FePackageTarget` reading the rows, the unified message, host inference, `TargetCatalog`, and `test_target_contract.py`.
   - **Commit 1c:** the data model in both analyzers, `test_target_data_model.py`, and the C4 test extension.
   - **Commit 1d:** the LSP setting.
   - **Gate:** the generated-source check, lint, format-check, the btrcc fixture rebuild, `make test`, the bootstrap fixed point, zero analyzer warnings, `boundary-check`, and, for commit 1d, `make extension` and the VS Code tests (`src/tests/vscode/target_setting.test.js`, new).
2. **ABI names** (`platforms-p1-hosted-abi-targets`). Three read-only extractors (iOS SDK on the Mac, NDK bionic, MinGW) hand their lists to one integrator, the only writer of `hosted_abi.toml`.
   - **Commit 2a:** the schema-3 spec and generated tables.
   - **Commit 2b:** the optimizer check in both compilers.
   - **Gate:** as sub-batch 1, plus:
     - the corpus through both compilers on linux-x86_64, and on `windows-x86_64` emitted on Linux and compiled with zig (no run);
     - transpiles with zero diagnostics of `cli/WindowsMain.btrc` under `--target windows-x86_64` and `windows-aarch64` (what `windows.yml:109` builds), `BtrccMain.btrc` under both linux rows, and `cli/MacOSMain.btrc` under both macOS rows. The stdlib selects platforms with runtime branches (`FileSystemHandles.btrc:1551-1560` calls `open(… O_DIRECTORY | O_NOFOLLOW …)` after `if (Platform.isWindows()) return`), so those calls are reachable on every row, and only the compat-overlay extraction rule (§2.3) keeps them available on windows-gnu;
     - BTRSmith's `application-frontend-check` on the Mac.
3. **Importers plus native plan** (`platforms-p1-native-import-targets`, `platforms-p1-native-plan-toolchain`, `platforms-p1-abi-fixture`).
   - **Commit 3a** (the importer pair): readers, sysroots and identity.
   - **Commit 3b** (the native-plan owner, against the frozen §4.1 schema): v5 writers, the builder, `package-manifest.md` and the plan goldens.
   - **Commit 3c** (the test agent and the ABI-fixture author): `test_link_plan_parity.py`, `test_native_plan_cross.py`, `test_native_import_targets.py` and the fixture.
   - **Gate:** as sub-batch 1, plus `make test-c11` (the plan builder compiles C), the cross builds where their toolchain exists, and the native suites on the Mac.
4. **Filters plus cache** (`platforms-p1-provider-filters`, then `platforms-p1-cache-identity`).
   - **Commit 4a:** the provider-filter writer's manifest predicates, the platform-directory rule, the stdlib audit and the matrix test.
   - **Commit 4b:** the single cache owner's key changes and `test_target_cache_identity.py`.
   - **Gate:** the full matrix (`make test`, `make bootstrap`, `make test-c11`, lint, format, generated, extension, hygiene, `git diff --check`), then the quiet M11 re-measure on the Mac.

## Stage 24 exit, mapped

| PLAN exit | Evidence here |
|-----------|---------------|
| Both frontends accept and reject the same target set, proven by a parity test | `test_target_contract.py` (§1.11) |
| Existing spellings still round-trip | `test_target_contract.py`'s round-trip cases (§1.5); the spelling axis of `test_target_cache_identity.py` |
| Real header extraction works for 5 new triples | `test_native_import_targets.py` (§3.3): Windows on Linux, Android with the NDK, iOS on the Mac |
| Link-plan schema v5 output is byte-identical across frontends | `test_link_plan_parity.py` (§4.3) |
| The provider matrix shows zero foreign SDK imports | `test_target_provider_matrix.py` (§5.3) |
| The cache-poisoning matrix is green, and a quiet M11 re-measure shows no regression | `test_target_cache_identity.py` (§6.3); the Mac re-measure |
| C4's iOS and Android rows are added if C4 landed | §1.2, §1.3; C4 is a prerequisite here, so the rows are always added |

**Awaiting a runner** (recorded, never met):
- the `windows-aarch64-msvc` hosted extraction;
- the `windows-aarch64-msvc` full fixture compile and link;
- MSVC header extraction (W1).

## Hand-offs

- **Stage 25 (`platforms-p2-runtime-semantics`).**
  - `__btrc_target_platform()` returns 1 on iOS and 2 on Android today, so `Library.Platform`, `ApplicationDirectories` (`:201`) and `WorkerPoolProvider` (`:181`) would treat iOS as macOS and Android as Linux.
  - Stage 25 adds codes 4 (iOS) and 5 (Android). Their tests are `__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__` and `__ANDROID__`, both compiler-defined. That is a D14 runtime re-capture, which D14 already approves for the P2 probes.
  - Until then, the hosted availability check (§2) and the provider matrix (§5) keep mobile builds from silently using desktop paths that do not exist there.
- **Stage 25 host lanes** run §7's dynamic half.
- **Stage 27 (W1)** owns MSVC header extraction and the Windows SDK sysroot beyond validation.
- **Stage 28 (P4)** owns artifact kinds (static and shared libraries, PIC, exports). Link plan v5 deliberately carries none, so P4 adds them as schema 6 rather than reshaping v5.
- **C4's document** gains, in Stage 24's spec commit, a pointer to this file at each amended rule:
  - its "Left out on purpose" data-model bullet and `__SIZEOF_LONG_DOUBLE__` bullet (now derived, §1.3);
  - `__MINGW32__`/`__MINGW64__` leaving "toolchain identity" (§1.3);
  - the `__STDC__`, `__CHAR_UNSIGNED__`, `__linux__`-family, `__APPLE__`/`__MACH__` and `__arm64__` selections (§1.3);
  - `__ANDROID__` leaving `undefined_macro_names`, and the `TARGET_OS_*` foreign-list sentence (§1.3);
  - the generator rules "`environments` is absent or empty" and "every predefined name is reserved" (§1.1, §1.3);
  - M3/M4: every predefined-macro row name and derived name is refused by `#define`/`#undef` (§1.3);
  - the cache table's prebuilt-stdlib-archive and module-unit rows (§6.2);
  - D13's lazy host completion and its message, superseded by §1.7;
  - test 3's "the triples live in the test until Stage 24" (§1.3).

## Owner questions

None of these blocks the spec commit. Each has a default that the design uses.

1. **Q1: macOS row minimum.** The default is **14.0**: every in-repo `BTRC_NATIVE_TARGET` and BTRSmith's `bsm_env.sh` use 14.0.0. The toolchain matrix records macOS 12 as Xcode 27's deployment minimum, not as a product floor. If 12.0 is wanted, change the two rows; `BTRC_NATIVE_TARGET` users must then spell 12.0.
2. **Q2: the MSVC row and the toolchain matrix.** The matrix leaves "the owner confirms this at the Stage 24 target-spec review" open. The default here: `windows-aarch64-msvc` is a row, but not a compiler host; it is used only for GPU-linked Windows ARM64 artifacts. A `windows-x86_64-msvc` row is not added.
3. **Q3: `ios-x86_64-simulator`.** Not added: the matrix marks it optional and Rosetta-only. Adding it later is one row plus its macro selections.

## Rejected alternatives

| Alternative | Reason |
|-------------|--------|
| Keep `(os, arch)` and put environment and minimum in separate options | platform-parity §1 requires distinct artifact identities. Separate options would multiply the invalid combinations both parsers must refuse, and every cache key would need three more components. |
| Use the `Platform`/slice vocabulary of `tools/qualification` (`ios-device`, `windows-x64`) as compiler labels | Those are evidence-ledger names, and `windows-x64` is a different spelling of an existing label. Mapping them is a test (§1.2), not a second spelling inside the compilers. |
| Algorithmic triple normalization in both compilers | A second implementation of clang's triple parser in btrc, with its own parity risk. Enumerated `triple_aliases` cover the spellings in use, and the generator checks them. |
| The compiler runs `xcrun`/finds the NDK | Process spawning and environment-dependent discovery in both compilers. The tools already resolve SDK paths (`native_import_fixtures.py:52`). |
| `TARGET_OS_*` stay foreign | clang 21 predefines them for every Darwin triple. Refusing them would make `#if TARGET_OS_IPHONE`, the most common Apple conditional, impossible, while the C compiler sees a definite value. |
| Refuse `__ANDROID_API__` | It would make the NDK's standard `#if __ANDROID_API__ >= N` pattern an error, although the value is fixed by the triple. |
| Hosted availability as an analyzer error | It would refuse stdlib functions that are unreachable from the program and are removed before C emission today. |
| Per-target available-name lists | Eleven copies of about 3,300 names. Unavailable lists are short for the Unix rows, and each extraction is one diff. |
| Link plan v5 only when the row is not the host | Two writer paths and two reader paths. The builder still could not tell a host plan from an accidental cross plan. |
| A sysroot path in the plan | It differs per host and checkout. The identity proves that both are the same SDK without embedding a path. |
| Map `linux` to Android with an `android` environment | platform-parity §1: "Android is not a Linux GNU target". Its macros, libc and API level differ. Rows sharing `__linux__` select both OSes explicitly instead. |

## Review

Two adversarial reviewers and one parity reviewer read the first draft (read-only, 2026-10-02). Their blocking findings and the resolutions follow.

| Finding | Resolution |
|---------|------------|
| *(filled by the review round; see below)* | |
