# BTRC standard library layout

`src/stdlib` is the compiler-owned `btrc_stdlib_runtime` package. Its shape is
the API surface, so the layout follows a few fixed rules.

- **The root is the closed prelude.** Each root file is one self-contained
  primitive imported as `Library.<Name>` (`Vector`, `Map`, `Strings`, `Bytes`,
  `Math`, `JSON`, `Process`, `Callback`, `Random`, ...), and a root module
  imports only other root modules. The root set is also the legacy relaxed
  composition unit (`import Library.*`) and the prebuilt core archive, so
  nothing with a native binding, a nested source graph, or a dependency on a
  group folder lives here; `Graph` is a folder for that reason even though it
  holds one module today.
- **A functional group with more than one module is a folder** named after the
  group, with a facade module of the same name inside it: `HTTP/HTTP.btrc`,
  `Terminal/Terminal.btrc`, `Daemon/Daemon.btrc`, `FileSystem/FileSystem.btrc`,
  `Digest/Digest.btrc`, `Image/Image.btrc`, `UI/UI.btrc`.
  `import Library.HTTP;` still selects the facade; the group's other modules
  are addressed by their folder path (`Library.HTTP.HTTPClient`,
  `Library.FileSystem.FileTree`, `Library.Digest.SHA256`). Files are named
  after their primary class, so a module path reads folder then class. A
  facade only imports: `Image/Image.btrc` imports `Image/Pixels.btrc` (the
  `Image` pixel class and fixture codecs), `EncodedImage` and
  `DDSEncodedImageDecoder`, and `UI/UI.btrc` imports the six UI modules.
  Three groups are documented exceptions. `GPU` has no facade: every module
  binds the native WebGPU SDK, so a consumer imports only the owners it uses
  (`Library.GPU.GPUDevice`, `Library.GPU.GPUSurfaceRenderer`, ...) rather than
  linking all of them through one import. `Realtime` has no facade either:
  each of its modules is a separate realtime contract a consumer takes on only
  when it needs it (see `Realtime/README.md`). `App` is a folder holding one
  module, like `Graph`: its input-event and application-error values
  belong beside the GUI groups, not in the closed prelude and its
  prebuilt core archive.
- **Platform code lives in a platform subfolder of its group** (`Audio/MacOS`,
  `Audio/Linux`, `Digest/MacOS`, `GUI/MacOS`, `GUI/Linux`, `Image/MacOS`,
  `Image/Linux`, `LocalApplicationChannel/MacOS`,
  `LocalApplicationChannel/Linux`, `Tray/MacOS`, `Tray/Linux`,
  `BackgroundJobs/MacOS`, `BackgroundJobs/Linux`, and `BackgroundJobs/Unix`
  for code shared by Linux and macOS) and implements the
  group's portable contract: `GUI/MacOS/MacOSDirectoryPicker` and
  `GUI/Linux/LinuxDirectoryPicker` implement `GUI/IDirectoryPicker`,
  `Image/MacOS/MacOSEncodedImageDecoder` implements `Image/IEncodedImageDecoder`
  (declared in `Image/EncodedImage.btrc`), and `Audio/MacOS/MacOSAudioDevice`
  and `Audio/Linux/LinuxAudioDevice` each supply an `IAudioDevicePlatform` to the
  shared provider in `Audio/AudioDevice.btrc`. A `[[package.providers]]`
  entry in the group's `btrc.toml` maps one portable module to its
  implementation per target OS (`GUI` to `MacOS.GUIProvider` or
  `Linux.GUIProvider`, `Audio` to `MacOS.AudioProvider` or
  `Linux.AudioProvider`); consumers import the portable module and never name
  a platform module. Selection follows the compilation target, so a program
  transpiled on one host for another must pass `--target` or compose its host
  capabilities explicitly; the self-hosted compiler's Windows entry therefore
  passes no worker-pool factory (see `BackgroundJobs/README.md`).
- **`btrc.symbols` is generated, not edited.** It maps every canonical root
  symbol to its owning module so strict import visibility does not have to
  parse the root stdlib on every compile. `make compiler-codegen-generate`
  rewrites it after a root module changes; a stale index is ignored, and
  `generated-check` fails until it is regenerated.
- **Each group is its own package.** A group folder carries its own
  `btrc.toml` (`btrc_stdlib_<group>`) with the group's exports, providers,
  `[[native.bindings]]`, frameworks and pkg-config entries, and its import
  headers (`GUI/MacOS/AppKit.h`, `Image/MacOS/ImageIO.h`,
  `GPU/WebGPUImports.h`, `BackgroundJobs/NativeThreads.h`) sit beside the code
  they describe. Module names inside a group manifest are group-relative
  (`MacOS.MacOSWindow`). The root `btrc.toml` names `btrc_stdlib_runtime`,
  exports the prelude and depends on every group by path; both compilers
  resolve that graph, and ordinary export visibility applies between groups.
  A group that imports another group (`Daemon` imports `FileSystem`, `Tray`
  imports `GUI`) does not list it under `[dependencies]`: every group is
  already a dependency of the root package, so `import Library.<Group>...`
  resolves through the stdlib tree and the root `btrc.lock` covers the whole
  graph. A group folder therefore never carries its own `btrc.lock`.
- **The Windows POSIX header overlays are not stdlib modules.** They live in
  `src/runtime/windows/` (see its `README.md`) and are added only to Windows
  builds through the Makefile's `WIN_COMPAT` flags.
- **Interfaces are `I`-prefixed** (`IView`, `IWindow`, `IDirectoryPicker`,
  `IEncodedImageDecoder`, `IAudioDeviceProvider`, `IRealtimeClipTransport`);
  providers are `<Platform><Capability>`; facades keep the group name. Value
  types carry no platform prefix. The one exemption is the root `Iterable<T>`:
  it is the language's for-in protocol, named for the loop it enables, not a
  stdlib capability.
- **Enum members are prefixed constants** (`AUDIO_DEVICE_BUSY`,
  `STACK_ALIGN_START`, `CALLBACK_CANCELLATION_PENDING`): upper snake case
  carrying their enum's stem, named unqualified. A bare `Pending` or `Start`
  would claim a root symbol every importer sees.

Current groups: `App`, `Audio` (`Linux/`, `MacOS/`), `BackgroundJobs`
(`Linux/`, `MacOS/`, `Unix/`), `Daemon`, `Digest` (`MacOS/`), `FileSystem`,
`GPU`, `Graph`, `GUI` (`FreeType/`, `Linux/`, `MacOS/`), `HTTP`, `Image`
(`Linux/`, `MacOS/`), `LocalApplicationChannel` (`Linux/`, `MacOS/`),
`Realtime`, `Terminal`, `Tray` (`Linux/`, `MacOS/`), `UI`.
Each group with behavior worth explaining has its own `README.md`.

## Drift findings

PLAN.md Stage 4 repeated the structure-first review of the stdlib, the
compilers' stdlib-facing code, tests, tools and CI between 2026-10-01 and
2026-10-03. It ranked 77 btrc findings (`btrc-D001` to `btrc-D077`; the
BTRSmith findings are tracked in BTRSmith's `docs/NativePlatformPlan.md`). A
read-only re-audit checked each against the tree before this ledger was
written: 76 are closed and 1 has a documented exception. Evidence is the
commit or commits that closed it.

- **D024 (exception).** The Linux dev shell has no lldb whose Python matches
  the DAP adapter, and the native header reader has no Linux compiler
  provider, so the Linux runner skips the lldb, pugixml, native-compiler
  provider and native-receipt provider tests with `covered_by = "macos"`
  (`src/tests/fixtures/expected-skips/linux-devcontainer.json`;
  `docs/design/ci-health.md`). Closing it means adding both to the Linux
  shell and deleting those four skip rules.
- **D044.** `ImageIoCleanup`'s packaged binding is proved only on macOS,
  where the native header reader runs it.
- **D067.** `examples/native-package/Makefile` deliberately does not include
  `Example.mk`: the flake's `native-package-plan` check copies only that
  directory into its sandbox. Its header comment says so.

| Finding | Severity | Area | Status | Evidence |
| --- | --- | --- | --- | --- |
| D001 | high | build/packaging | closed | `3120693`, `c61a14b` |
| D002 | high | ci | closed | `75b8911`, `de086fd` |
| D003 | high | stdlib/GUI/Linux | closed | `91ac9c6` |
| D004 | high | stdlib/GUI | closed | `88f5023` |
| D005 | medium | stdlib/GUI/Linux | closed | `f7aefd7` |
| D006 | medium | stdlib/GUI/Linux | closed | `14975a1` |
| D007 | medium | stdlib/GUI/Linux | closed | `f92b761`, `eff50b8` |
| D008 | medium | stdlib/GUI/MacOS | closed | `2e8cf3d`, `f0f19ce` |
| D009 | medium | stdlib/Audio/Linux | closed | `b17bf68` |
| D010 | medium | stdlib/Audio/Linux | closed | `b17bf68` |
| D011 | medium | stdlib/Realtime | closed | `7948af0`, `c920421` |
| D012 | medium | stdlib/root Process | closed | `58bf9bb`, `c278e58` |
| D013 | medium | stdlib/root TOML,Platform | closed | `61e1c95`, `f95af8f` |
| D014 | medium | stdlib/root collections | closed | `12c0838` |
| D015 | medium | stdlib/root JSON | closed | `fae27b4` |
| D016 | medium | stdlib/root Callback | closed | `d1efd49` |
| D017 | medium | stdlib/Image,GPU | closed | `5aa4913`, `a60d01a` |
| D018 | medium | stdlib/UI | closed | `8d2fe02` |
| D019 | medium | stdlib/Tray/Linux | closed | `84483ad` |
| D020 | medium | stdlib/BackgroundJobs,FileSystem | closed | `49e5563`, `7b6ef8a` |
| D021 | medium | tests harness | closed | `6f013a8`, `5f02b09` |
| D022 | medium | build | closed | `82298db`, `799dc97` |
| D023 | medium | gates | closed | `76d85da`, `c61a14b` |
| D024 | medium | nix | exception | `7948af0` |
| D025 | medium | tools | closed | `6f013a8`, `5cd6899` |
| D026 | low | stdlib/GUI | closed | `a12db55`, `1525bfb` |
| D027 | low | stdlib/root Process | closed | `58bf9bb` |
| D028 | low | stdlib FileSystem/Daemon/BackgroundJobs | closed | `eb4db15` |
| D029 | low | stdlib misc correctness | closed | `1e0f757`, `86177db`, `1525bfb`, `b17bf68` |
| D030 | low | test coverage | closed | `3e778bf`, `88f5023`, `d22ae5f`, `5472e1a` |
| D031 | high | stdlib/Realtime structure | closed | `c920421`, `dd3f334`, `bf77ad9` |
| D032 | high | stdlib/UI structure | closed | `8d2fe02` |
| D033 | high | stdlib/GUI manifest | closed | `a26efb0` |
| D034 | medium | stdlib/GUI legacy toolkit | closed | `1bdbfd4` |
| D035 | medium | stdlib/GUI contracts | closed | `1525bfb` |
| D036 | medium | stdlib facades | closed | `dad13d0`, `5aa4913`, `e4825f3` |
| D037 | medium | stdlib/Tray | closed | `84483ad` |
| D038 | medium | stdlib native code | closed | `b6348f0`, `84483ad` |
| D039 | medium | stdlib/LocalApplicationChannel | closed | `b3eb878` |
| D040 | medium | stdlib/BackgroundJobs | closed | `49e5563`, `f79e68a`, `0613211` |
| D041 | medium | stdlib/GPU runtime placement | closed | `1532655` |
| D042 | medium | stdlib/root JSON,Datetime | closed | `86177db`, `16b8d0c` |
| D043 | medium | compiler python structure | closed | `ec1d7b8` |
| D044 | medium | tests structure | closed | `571d2ff`, `a06e9a3`, `ebff3e9`, `95f0406`, `906fcad`, `dcdade3`, `e495f69` |
| D045 | medium | stdlib/GUI/Linux structure | closed | `66cffb1` |
| D046 | medium | examples native | closed | `bb3845a`, `5be7366` |
| D047 | low | manifests | closed | `0429f6e`, `2e8cf3d`, `b6348f0` |
| D048 | low | strict imports and externs | closed | `bb04d06`, `0f2cb5d`, `ece02ef` |
| D049 | low | native header reader | closed | `c51b9da`, `425e5c0` |
| D050 | medium | stdlib duplication UTF-8 | closed | `ac713c5` |
| D051 | medium | stdlib duplication primitives | closed | `ac713c5`, `d2dc5a0`, `0f2cb5d` |
| D052 | medium | stdlib/root Strings | closed | `eb4db15` |
| D053 | medium | stdlib/Audio duplication | closed | `eb4db15` |
| D054 | medium | stdlib/Image duplication | closed | `5aa4913` |
| D055 | medium | stdlib/GUI duplication | closed | `a87bc6b`, `53288fb`, `f0f19ce` |
| D056 | medium | stdlib/GUI dead code | closed | `2e8cf3d`, `f0f19ce`, `66cffb1`, `b17bf68` |
| D057 | medium | stdlib/UI,App dead code | closed | `66aa56c`, `8d2fe02`, `bf77ad9` |
| D058 | medium | stdlib HTTP/Terminal dead code | closed | `0f2cb5d`, `125139d` |
| D059 | medium | stdlib root dead code | closed | `ece02ef`, `58bf9bb`, `d1efd49`, `80c2089` |
| D060 | medium | runtime/compiler aliases | closed | `eb4db15` |
| D061 | low | stdlib FileSystem/Daemon dead code | closed | `11bcd43`, `a34c4bc`, `bbaf468`, `ae628c8` |
| D062 | low | stdlib misc duplication | closed | `a60d01a`, `d1efd49`, `5aa4913`, `8d2fe02` |
| D063 | medium | stdlib/root Math | closed | `032c566` |
| D064 | medium | tests dead code | closed | `3a6d389` |
| D065 | medium | tools dead code and aliases | closed | `dab92e3` |
| D066 | low | tools | closed | `641778b`, `cf7b714`, `2cf1910`, `8957eee` |
| D067 | medium | examples | closed | `812fe83`, `9fa3481` |
| D068 | medium | naming interfaces and files | closed | `755f1d8`, `5edc98a`, `d4539b4`, `1618560` |
| D069 | medium | naming identifiers | closed | `6c0f375`, `efd0cf2`, `8acf2ee`, `71c07cb` |
| D070 | low | facade spelling | closed | `34c5551` |
| D071 | high | docs UI | closed | `8d2fe02` |
| D072 | medium | docs README.md | closed | `180f2d9` |
| D073 | medium | docs AGENTS.md | closed | `180f2d9`, `7f0131e`, `4c9af96` |
| D074 | medium | docs design | closed | `180f2d9` |
| D075 | medium | docs stdlib | closed | `1e940f1`, `c7f785e` |
| D076 | low | docs in-source comments | closed | `eb4db15` |
| D077 | low | repo hygiene | closed | `88a5c36`, `5f02b09` |
