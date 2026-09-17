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
  after their primary class, so a module path reads folder then class.
- **Platform code lives in a platform subfolder of its group** (`Audio/MacOS`,
  `GUI/MacOS`, `Image/MacOS`, `Tray/Linux`, `Tray/MacOS`) and implements the group's portable
  contract: `GUI/MacOS/MacOSDirectoryPicker` implements `GUI/IDirectoryPicker`,
  `Image/MacOS/MacOSEncodedImageDecoder` implements `Image/IEncodedImageDecoder`
  (declared in `Image/EncodedImage.btrc`), `Audio/MacOS/CoreAudioDevice`
  implements `Audio/AudioDevice`'s provider contract. A Linux or Windows
  provider is the sibling folder (`GUI/Linux/LinuxDirectoryPicker`) selected by
  the same `[[package.providers]]` entry in `btrc.toml`; consumers never name a
  platform module.
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
  `Windows/` is the toolchain compatibility layer, not a module group.
- **Interfaces are `I`-prefixed** (`IView`, `IWindow`, `IDirectoryPicker`,
  `IEncodedImageDecoder`); providers are `<Platform><Capability>`; facades keep
  the group name. Value types carry no platform prefix.

Current groups: `App`, `Audio`, `BackgroundJobs`, `Daemon`, `Digest`,
`FileSystem`, `GPU`, `Graph`, `GUI` (`FreeType/`, `MacOS/`), `HTTP`, `Image`
(`MacOS/`), `LocalApplicationChannel`, `Realtime`, `Terminal`, `Tray` (`Linux/`, `MacOS/`), `UI`. Each group with behavior worth explaining has its own `README.md`.
