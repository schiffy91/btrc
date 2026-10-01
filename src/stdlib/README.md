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
  Two groups are documented exceptions. `GPU` has no facade: every module
  binds the native WebGPU SDK, so a consumer imports only the owners it uses
  (`Library.GPU.GPUDevice`, `Library.GPU.GPUSurfaceRenderer`, ...) rather than
  linking all of them through one import. `App` is a folder holding one
  module, like `Graph`: its application event and window-description
  values belong beside the GUI groups, not in the closed prelude and its
  prebuilt core archive.
- **Platform code lives in a platform subfolder of its group** (`Audio/MacOS`,
  `Audio/Linux`, `GUI/MacOS`, `GUI/Linux`, `Image/MacOS`, `Image/Linux`,
  `Tray/Linux`, `Tray/MacOS`, and `BackgroundJobs/Unix` for code shared by
  linux and macOS) and implements the group's portable
  contract: `GUI/MacOS/MacOSDirectoryPicker` implements `GUI/IDirectoryPicker`,
  `Image/MacOS/MacOSEncodedImageDecoder` implements `Image/IEncodedImageDecoder`
  (declared in `Image/EncodedImage.btrc`), `Audio/MacOS/MacOSAudioDevice`
  implements `Audio/AudioDevice`'s provider contract. A Linux or Windows
  provider is the sibling folder (`GUI/Linux/LinuxDirectoryPicker`) selected by
  the same `[[package.providers]]` entry in `btrc.toml`; consumers never name a
  platform module. Selection follows the compilation target, so a program
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
  `Windows/` is the toolchain compatibility layer, not a module group.
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

Current groups: `App`, `Audio`, `BackgroundJobs`, `Daemon`, `Digest`,
`FileSystem`, `GPU`, `Graph`, `GUI` (`FreeType/`, `Linux/`, `MacOS/`), `HTTP`, `Image`
(`Linux/`, `MacOS/`), `LocalApplicationChannel`, `Realtime`, `Terminal`, `Tray` (`Linux/`, `MacOS/`), `UI`. Each group with behavior worth explaining has its own `README.md`.
