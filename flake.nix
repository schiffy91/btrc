{
  description = "btrc — a modern take on C";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      # nixpkgs builds the AT-SPI bus launcher against NixOS's
      # /run/current-system dbus-daemon, which no container or other Linux
      # host has; this one spawns the store's dbus-daemon instead. It is not
      # told of a dbus-broker either: on a NixOS host that has one the launcher
      # starts it, and outside a systemd session it serves no accessibility bus.
      atSpiCore = pkgs: pkgs.at-spi2-core.overrideAttrs (old: {
        mesonFlags = map (flag:
          if lib.hasPrefix "-Ddbus_daemon=" flag then "-Ddbus_daemon=${pkgs.dbus}/bin/dbus-daemon" else flag
        ) (lib.filter (flag: !lib.hasPrefix "-Ddbus_broker=" flag) old.mesonFlags);
      });
      cfg = {
        name = "btrc";
        image = "btrc-devcontainer:latest";
        baseImage = "alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b";
        nixInstallerVersion = "v3.21.5";
        nixInstallerSha256 = "c9368f4bbfbc78ace32bf018cb15534344b33c0161468deddbfcc8a04f7c9a01";
        runtime = "podman";
        machine = { memory = 24576; cpus = 6; disk = 40; };   # AGENTS.md host capacity: podman-machine-default
        workspace = "/workspace";
        user = { name = "dev"; uid = 1000; };
        extensions = [ "anthropic.claude-code" "ms-python.python" "jnoortheen.nix-ide" ];
        share = { ssh = true; git = true; gh = true; claude = true; };
        paths = { ssh = ".ssh"; gitconfig = ".gitconfig"; gh = ".config/gh"; claude = ".claude"; };
        claudeCode = { enable = true; version = "2.1.207"; };
        initialShellCmd = "echo make help && make help";
        packages = pkgs: with pkgs; [
          (python314.withPackages (ps: [
            ps.build ps.setuptools
            ps.pytest ps.pytest-xdist ps.pytest-cov ps.pygls ps.lsprotocol
          ] ++ lib.optionals stdenv.hostPlatform.isLinux [
            # AT-SPI tree dumps of a headless GUI session (tools/ui/headless-session.sh).
            ps.pyatspi ps.pygobject3
          ]))
            ruff gcc clang zig gnumake git jq gh nodejs_22 nixd freetype
            # naga validates generated WGSL in the GPU tests. wgpu-utils builds
            # the whole wgpu workspace; expose only its naga CLI, so its example
            # and xtask binaries stay off PATH and out of the container's bin.
            (runCommand "naga-${wgpu-utils.version}" { meta.mainProgram = "naga"; } ''
              mkdir -p "$out/bin"
              ln -s ${wgpu-utils}/bin/naga "$out/bin/naga"
            '')
            # The HTTP TLS fixtures mint a per-run CA and leaf keys on the host
            # that serves them (docs/design/http-transport.md, Curl-free
            # endpoint and trust fixture plan). Pin an OpenSSL 3.x CLI ahead of
            # macOS's LibreSSL /usr/bin/openssl; only its bin output, the CLI.
            openssl.bin
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isDarwin [
            # Real SDKs the macOS-only native-interop proofs link through
            # pkg-config: the C++ owner proof (pugixml) and the owned-output
            # proof (sqlite3). Both suites skip off macOS before probing them.
            pugixml sqlite.dev
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            bubblewrap libx11.dev libxrandr.dev libxinerama.dev libxcursor.dev libxi.dev
            wayland.dev pkg-config            # native windowing shims
            fontconfig.dev                    # Linux font provider
            openssh   # ssh-keygen: writes the key files the Library.Crypto driver reads back
            xvfb-run   # tools/virtual-display.sh: CI's X display for the GUI tests
            # tools/ui/headless-session.sh: a private X (Xvfb) or Wayland
            # (labwc's headless backend) display inside its own session bus,
            # with the AT-SPI accessibility bus. The GUI conformance probe
            # sends real input in it: XTEST on X11, and on Wayland a wlroots
            # compositor's virtual pointer and keyboard.
            xvfb dbus (atSpiCore pkgs) libxtst labwc wlr-randr
            # gtk4.pc: the Linux GUI provider's windows and controls.
            gtk4.dev glib.dev
          ];
      };
      files = import ./nix { inherit cfg lib; };
      # CI's image: the same toolchain without Claude Code or its host
      # credential mirror, which no CI job uses.
      ciFiles = import ./nix {
        inherit lib;
        cfg = cfg // {
          # The CI image runs the embedded web package's GUI suites as well.
          devShell = ".#embedded-web";
          claudeCode = cfg.claudeCode // { enable = false; };
          share = cfg.share // { claude = false; };
          extensions = lib.remove "anthropic.claude-code" cfg.extensions;
        };
      };
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs {
        inherit system;
        overlays = [ (final: prev: lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
          # Apple's libffi-40 aborts while allocating trampolines on macOS 27.
          # Keep Python's build-time interpreters and cffi on the same upstream
          # library without rebuilding unrelated consumers such as LLVM.
          # https://github.com/NixOS/nixpkgs/issues/541367
          python314 = prev.python314.override (old: {
            self = final.python314;
            libffi = final.libffiReal;
            packageOverrides = lib.composeManyExtensions [
              (old.packageOverrides or (_: _: { }))
              (_pythonFinal: pythonPrev: {
                cffi = (pythonPrev.cffi.override { libffi = final.libffiReal; }).overrideAttrs (oldCffi: {
                  patches = (oldCffi.patches or [ ]) ++ [ ./nix/cffi-darwin-upstream-libffi.patch ];
                });
              })
              # Overriding the interpreter changes every package's hash, so no
              # Darwin Python package here is in cache.nixos.org. A hosted
              # runner whose Magic Nix Cache is throttled rebuilds the set
              # from source, upstream test suites included, and one of them
              # (pytest-timeout's pexpect case) failed macOS CI on 2026-10-17
              # and 2026-10-18. Skip those package checks: the packages are
              # uncached either way, and btrc's own tests are unaffected.
              (_pythonFinal: pythonPrev: {
                buildPythonPackage = args: pythonPrev.buildPythonPackage (
                  if builtins.isFunction args then
                    (finalAttrs: (args finalAttrs) // { doCheck = false; })
                  else
                    args // { doCheck = false; }
                );
              })
            ];
          });
        }) ];
      }));
      nativeHeaderEnvironment = pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        linuxHeaders = pkgs.symlinkJoin {
          name = "btrc-native-sdk-headers";
          paths = [ (lib.getDev pkgs.stdenv.cc.libc) pkgs.linuxHeaders ];
        };
        linuxSysroot = pkgs.runCommand "btrc-native-sysroot" { } ''
          mkdir -p "$out/usr"
          ln -s ${linuxHeaders}/include "$out/usr/include"
        '';
      in {
        BTRC_NATIVE_HEADER_READER = "${self.packages.${pkgs.stdenv.hostPlatform.system}.btrc-native-header}/bin/btrc-native-header";
        # Java bindings read class files through their own reader, never
        # through the header reader (docs/design/native-interop-ownership.md 2.3).
        BTRC_JAVA_CLASS_READER = "${self.packages.${pkgs.stdenv.hostPlatform.system}.btrc-java-class-reader}/bin/btrc-java-class-reader";
        BTRC_NATIVE_SYSROOT = if isDarwin then "${pkgs.apple-sdk}/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk" else "${linuxSysroot}";
        BTRC_NATIVE_TARGET = if isDarwin then "${if pkgs.stdenv.hostPlatform.isAarch64 then "arm64" else "x86_64"}-apple-macosx${lib.versions.pad 3 pkgs.stdenv.hostPlatform.darwinMinVersion}"
          else "${if pkgs.stdenv.hostPlatform.isAarch64 then "aarch64" else "x86_64"}-unknown-linux-gnu";
      };
    in {
      apps = eachSystem (pkgs: let
        system = pkgs.stdenv.hostPlatform.system;
      in {
        btrc = {
          type = "app";
          program = "${self.packages.${system}.btrcpy}/bin/btrcpy";
        };
        btrcc = {
          type = "app";
          program = "${self.packages.${system}.btrcc}/bin/btrcc";
        };
        default = self.apps.${system}.btrc;
        btrc-lsp = {
          type = "app";
          program = "${self.packages.${system}.btrc-lsp}/bin/btrc-lsp";
        };
        btrc-format = {
          type = "app";
          program = "${self.packages.${system}.btrc-format}/bin/btrc-format";
        };
        btrc-native-plan = {
          type = "app";
          program = "${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan";
        };
      });
      devShells = eachSystem (pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        system = pkgs.stdenv.hostPlatform.system;
        nativeEnvironment = nativeHeaderEnvironment pkgs // lib.optionalAttrs isDarwin {
          # Keep the SDK reader and its compiler-context provider identical in
          # the development and release shells.
          BTRC_NATIVE_PROVIDER_CC = "${pkgs.llvmPackages_21.stdenv.cc}/bin/clang";
          BTRC_NATIVE_PROVIDER_CXX = "${pkgs.llvmPackages_21.stdenv.cc}/bin/clang++";
        };
        defaultShell = {
          # The test suite deliberately compiles strict C at -O0. Nixpkgs'
          # fortify setup diagnoses -O0 as a preprocessor warning, and -Werror
          # correctly promotes it. Release derivations retain their hardening;
          # only the interactive/test shell disables this incompatible pair.
          hardeningDisable = [ "fortify" "fortify3" ];
          # btrc-lsp on PATH: the VSCode extension launches the language server
          # via `nix develop <workspace> --command btrc-lsp`.
          # The flake's wgpu-native carries the driver runpath and a pkg-config
          # file; the bare nixpkgs library lacks both, so it is not added too.
          packages = cfg.packages pkgs ++ [
            pkgs.pkg-config
            self.packages.${system}.wgpu-native
            self.packages.${system}.btrc-gpu
            self.packages.${system}.btrc-format
            self.packages.${system}.btrc-lsp
          ];
          GPU_CFLAGS = "-I${pkgs.wgpu-native.dev}/include/webgpu";
          GPU_LDFLAGS = "-L${self.packages.${system}.wgpu-native}/lib -lwgpu_native -pthread"
            + lib.optionalString isDarwin
              " -framework Metal -framework QuartzCore -framework Foundation";
        } // lib.optionalAttrs (!isDarwin) {
          # Mesa's software Vulkan driver (lavapipe) and the loader wgpu-native
          # dlopens. Only tools/virtual-display.sh selects them, so a developer's
          # shell keeps its real GPU and CI's headless runner still gets an adapter.
          BTRC_LAVAPIPE_ICD = "${pkgs.mesa}/share/vulkan/icd.d/lvp_icd.${pkgs.stdenv.hostPlatform.uname.processor}.json";
          BTRC_VULKAN_LOADER = "${pkgs.vulkan-loader}/lib";
          # wgpu-native also probes OpenGL through EGL. On a virtual display the
          # host's own GPU vendor library has no screen to answer for.
          BTRC_MESA_EGL = "${pkgs.mesa}/share/glvnd/egl_vendor.d/50_mesa.json";
          # The fonts a private session has (tools/ui/headless-session.sh): one
          # family, the same on a desktop and in a container that has none, so
          # text has a size wherever the GUI tests run.
          BTRC_FONTS_CONFIG = "${pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; }}";
          # GTK's file chooser reads its settings schema, and aborts where
          # none is installed; a private session has no system data to find
          # one in, so it is given GTK's own.
          BTRC_GSETTINGS_SCHEMAS = "${pkgs.gtk4}/share/gsettings-schemas/${pkgs.gtk4.name}/glib-2.0/schemas";
          # tools/ui/headless-session.sh starts the AT-SPI bus from here; the
          # launcher is a libexec program, not on PATH.
          BTRC_ATSPI_LIBEXEC = "${atSpiCore pkgs}/libexec";
          # The AT-SPI and GLib typelibs pyatspi loads to dump a session's
          # accessibility tree; mkShell sets no typelib path of its own.
          GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
            (lib.getLib (atSpiCore pkgs)) (lib.getLib pkgs.glib) (lib.getLib pkgs.gobject-introspection)
          ];
        } // nativeEnvironment;
        platforms = import ./nix/platforms.nix { inherit nixpkgs system lib; };
      in {
        default = pkgs.mkShell defaultShell;
        # Desktop programs hosting HotSpot and the checked-JNI test suite.
        jni = pkgs.mkShell (defaultShell // {
          packages = defaultShell.packages ++ [ self.packages.${system}.btrc-jni pkgs.jdk17_headless ];
        });
      } // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
        embedded-web = import ./packages/embedded-web/shell.nix { inherit pkgs defaultShell; };
      } // lib.optionalAttrs isDarwin {
        # The portable compiler, generator and bundle writer use Python's
        # standard library. Keep their toolchain and the native smoke-test CC,
        # without realizing pytest, LSP, GPU or editor development packages.
        macos-release = pkgs.mkShell ({
          inherit (defaultShell) hardeningDisable;
          packages = with pkgs; [ python314 gcc clang zig gnumake git ];
        } // nativeEnvironment);
      } // lib.optionalAttrs (system != "aarch64-linux") {
        # The default shell plus the Android SDK, NDK r29 and JDK 17
        # (nix/platforms.nix), kept out of the default shell and the CI image.
        # Google ships no aarch64-linux SDK host tools, so that system has none.
        # Enter it with a GC root, which Determinate Nix's collector otherwise
        # sweeps:
        #   nix develop .#platforms --profile ~/.cache/btrc/gcroots/platforms
        # It also carries wgpu-native's pinned prebuilt release archives for
        # the cross GPU slices (nix/wgpu-native-prebuilt.nix):
        #   nix build .#devShells.<system>.platforms.wgpuNativePrebuilt.<slice>
        platforms = pkgs.mkShell (defaultShell // platforms.environment // {
          packages = defaultShell.packages ++ platforms.packages;
          passthru.wgpuNativePrebuilt = import ./nix/wgpu-native-prebuilt.nix { inherit (pkgs) fetchurl; };
        });
      });
      packages = eachSystem (pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        # What the reference compiler runs from. Every program a consumer builds
        # with btrcpy has this source among its inputs, so nothing the compiler
        # does not import belongs here: with the language server in it, an
        # editor-only commit rebuilt every program of every consumer.
        compilerPrefixes = [
          "src/compiler/python/"
          "src/language/"
          "src/runtime/c/"
          "src/stdlib/"
        ];
        runtimePrefixes = compilerPrefixes ++ [ "src/devex/lsp/" ];
        sourceSubset = { prefixes, files ? [ ], excludedPrefixes ? [ ] }:
          lib.cleanSourceWith {
            src = ./.;
            filter = path: type:
              let
                relativePath = lib.removePrefix "${toString ./.}/" (toString path);
                relativePrefix = lib.optionalString (relativePath != "") "${relativePath}/";
                pathPrefix = if type == "directory" then relativePrefix else relativePath;
                needed = lib.any (prefix: lib.hasPrefix prefix pathPrefix) prefixes
                  || lib.elem relativePath files;
                parent = type == "directory"
                  && lib.any (prefix: lib.hasPrefix relativePrefix prefix) (prefixes ++ files);
                derived = lib.any (prefix: lib.hasPrefix prefix pathPrefix) excludedPrefixes
                  || lib.hasInfix "/__pycache__/" pathPrefix
                  || lib.hasInfix "/.pytest_cache/" pathPrefix
                  || lib.hasInfix "/.venv/" pathPrefix
                  || lib.hasInfix "/build/" pathPrefix
                  || lib.hasInfix "/node_modules/" pathPrefix
                  || lib.hasSuffix "/.DS_Store" relativePath
                  || lib.any (suffix: lib.hasSuffix suffix relativePath) [
                    ".a" ".o" ".pyc" ".pyo" ".vsix"
                  ];
              in (needed || parent) && !derived;
          };
        compilerSource = sourceSubset {
          prefixes = compilerPrefixes;
          excludedPrefixes = [ ];
        };
        runtimeSource = sourceSubset {
          prefixes = runtimePrefixes;
          excludedPrefixes = [ ];
        };
        selfhostCompilerSource = sourceSubset {
          prefixes = [
            "src/compiler/btrc/"
            "src/language/"
            "src/runtime/c/"
            "src/stdlib/"
          ];
          excludedPrefixes = [ ];
        };
        selfhostBundleSource = sourceSubset {
          prefixes = [
            "src/language/"
            "src/optional/"
            "src/runtime/c/"
            "src/stdlib/"
          ];
          files = [ "LICENSE" ];
          excludedPrefixes = [ ];
        };
        gpuRuntimeSource = sourceSubset {
          prefixes = [
            "src/runtime/gpu/"
          ];
          excludedPrefixes = [ ];
        };
        # Exactly the import closure of tools/native_plan.py, its lazy imports
        # and the package initializers they execute included. The adapter
        # imports the header reader's owner while it keys cached objects, so a
        # missing module fails only builds that pass --object-cache.
        # test_flake_installs_adapter_and_runs_native_plan_check recomputes it.
        nativePlanSource = sourceSubset {
          # TargetToolchain force-includes the Windows compatibility overlay
          # into every windows-gnu unit it cross-builds, and RuntimeObjects
          # reads the runtime manifest's separately compiled objects and
          # builds their C sources.
          prefixes = [ "src/runtime/c/" "src/runtime/windows/" ];
          files = [
            "tools/native_plan.py"
            "tools/daemon_supervisor.py"
            "src/compiler/python/__init__.py"
            "src/compiler/python/abi/__init__.py"
            "src/compiler/python/abi/declarations.py"
            "src/compiler/python/abi/generated.py"
            "src/compiler/python/abi/hosted.py"
            "src/compiler/python/abi/native_generated.py"
            "src/compiler/python/artifacts/__init__.py"
            "src/compiler/python/artifacts/publication.py"
            "src/compiler/python/frontend/__init__.py"
            "src/compiler/python/frontend/native_imports.py"
            "src/compiler/python/frontend/packages.py"
            "src/compiler/python/syntax/__init__.py"
            "src/compiler/python/syntax/ast/__init__.py"
            "src/compiler/python/syntax/ast/generated.py"
            "src/compiler/python/syntax/grammar.py"
          ];
          excludedPrefixes = [ ];
        };
        formatterSource = sourceSubset {
          # The formatter and what it imports: its engine reads a file's conditionals with the frontend's
          # source reader, which brings the ABI tables with it. The check `formatter-starts` runs the packaged
          # program from an empty folder, where a module left out of this list cannot be found beside it.
          prefixes = [
            "src/compiler/python/abi/"
            "src/compiler/python/frontend/"
            "src/compiler/python/lexer/"
            "src/compiler/python/parser/"
            "src/compiler/python/syntax/"
            "src/devex/formatter/"
            "src/language/"
          ];
          files = [ "src/devex/__init__.py" ];
          excludedPrefixes = [ ];
        };
        extensionVersion = (builtins.fromJSON (builtins.readFile ./src/devex/vscode/package.json)).version;
        extensionSource = sourceSubset {
          prefixes = runtimePrefixes ++ [
            "src/devex/debug/"
            "src/devex/vscode/"
          ];
          files = [ "LICENSE" "flake.lock" "src/devex/__init__.py" ];
          excludedPrefixes = [ ];
        };
        lspPython = pkgs.python314.withPackages (ps: [ ps.pygls ps.lsprotocol ]);
        btrcpy = pkgs.writeShellApplication {
          name = "btrcpy";
          # Git-backed btrc.toml dependencies are a production compiler feature;
          # the installed app must not rely on an ambient host Git executable.
          runtimeInputs = [ pkgs.python314 pkgs.git ];
          text = ''
            export PYTHONPATH="${compilerSource}''${PYTHONPATH:+:$PYTHONPATH}"
            ${lib.concatStringsSep "\n" (lib.mapAttrsToList (name: value:
              ''export ${name}="''${${name}-${value}}"''
            ) (nativeHeaderEnvironment pkgs))}
            exec ${pkgs.python314}/bin/python3 -m src.compiler.python.main "$@"
          '';
        };
        btrccExecutable = pkgs.stdenv.mkDerivation {
          pname = "btrcc-binary";
          version = "0";
          src = selfhostCompilerSource;
          strictDeps = true;
          nativeBuildInputs = [ btrcpy ];
          buildPhase = ''
            runHook preBuild
            export BTRC_STATE_DIR="$TMPDIR/btrc-state"
            export BTRC_CACHE_DIR="$TMPDIR/btrc-cache"
            btrcpy --strict-imports --no-cache \
              --target ${if isDarwin then "macos" else "linux"}-${if pkgs.stdenv.hostPlatform.isAarch64 then "arm64" else "x64"} \
              src/compiler/btrc/${if isDarwin then "cli/MacOSMain.btrc" else "BtrccMain.btrc"} -o btrcc.c
            $CC -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
              btrcc.c -o btrcc -lm -lpthread
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/bin"
            install -m 0755 btrcc "$out/bin/btrcc"
            runHook postInstall
          '';
        };
        btrcc = pkgs.stdenvNoCC.mkDerivation {
          pname = "btrcc";
          version = "0";
          src = selfhostBundleSource;
          strictDeps = true;
          dontBuild = true;
          nativeBuildInputs = [ pkgs.makeWrapper ];
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/bin" "$out/share/btrc/language"
            install -m 0755 ${btrccExecutable}/bin/btrcc "$out/bin/btrcc"
            install -m 0644 src/language/grammar.ebnf \
              "$out/share/btrc/language/grammar.ebnf"
            cp -R src/stdlib "$out/share/btrc/stdlib"
            cp -R src/optional "$out/share/btrc/optional"
            mkdir -p "$out/share/btrc/runtime"
            cp -R src/runtime/c "$out/share/btrc/runtime/c"
            wrapProgram "$out/bin/btrcc" \
              --set-default BTRC_HOME "$out/share/btrc" \
              ${lib.concatStringsSep " " (lib.mapAttrsToList (name: value:
                "--set-default ${name} ${lib.escapeShellArg value}"
              ) (nativeHeaderEnvironment pkgs))}
            runHook postInstall
          '';
        };
        gpuFrameworks = lib.optionalString isDarwin
          " -framework Metal -framework QuartzCore -framework Foundation";
        gpuCompileFlags = "-DBTRC_GPU_WGPU_NATIVE -I${pkgs.wgpu-native.dev}/include/webgpu";
        gpuPkgConfig = pkgs.writeText "btrc-gpu.pc.in" ''
          prefix=@out@
          libdir=''${prefix}/lib
          includedir=''${prefix}/include

          Name: btrc-gpu
          Description: BTRC compiler-only WebGPU compute runtime
          Version: 0
          Cflags: -I''${includedir}
          Libs: -L''${libdir} -lbtrc_gpu -L${wgpuNativeLibrary}/lib -Wl,-rpath,${wgpuNativeLibrary}/lib -lwgpu_native -pthread${gpuFrameworks}
        '';
        btrcGpu = pkgs.stdenv.mkDerivation {
          pname = "btrc-gpu";
          version = "0";
          src = gpuRuntimeSource;
          strictDeps = true;
          propagatedBuildInputs = [ pkgs.wgpu-native ];
          buildPhase = ''
            runHook preBuild
            for source in \
              btrc_gpu.c \
              btrc_gpu_async.c; do
              $CC -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 \
                -pthread ${gpuCompileFlags} \
                -Isrc/runtime/gpu \
                -c "src/runtime/gpu/$source" -o "''${source%.c}.o"
            done
            $AR rcs libbtrc_gpu.a btrc_gpu.o btrc_gpu_async.o
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            licenseRoot="$out/share/licenses/btrc"
            mkdir -p \
              "$out/include" \
              "$out/lib/pkgconfig" \
              "$licenseRoot/third-party/wgpu-native" \
              "$licenseRoot/third-party/webgpu-headers"
            install -m 0644 src/runtime/gpu/btrc_gpu_compute_internal.h "$out/include/"
            install -m 0644 libbtrc_gpu.a "$out/lib/"
            install -m 0644 ${./LICENSE} "$licenseRoot/LICENSE"
            install -m 0644 ${pkgs.wgpu-native.src}/LICENSE.APACHE \
              "$licenseRoot/third-party/wgpu-native/LICENSE.APACHE"
            install -m 0644 ${pkgs.wgpu-native.src}/LICENSE.MIT \
              "$licenseRoot/third-party/wgpu-native/LICENSE.MIT"
            install -m 0644 ${pkgs.wgpu-native.src}/ffi/webgpu-headers/LICENSE \
              "$licenseRoot/third-party/webgpu-headers/LICENSE"
            substitute ${gpuPkgConfig} "$out/lib/pkgconfig/btrc-gpu.pc" \
              --replace-fail @out@ "$out"
            runHook postInstall
          '';
        };
        btrc-lsp = pkgs.writeShellApplication {
          name = "btrc-lsp";
          # LSP composition resolves the same locked Git dependencies as the
          # CLI, including inside minimal editor launch environments.
          runtimeInputs = [ lspPython pkgs.git ];
          text = ''
            export PYTHONPATH="${runtimeSource}''${PYTHONPATH:+:$PYTHONPATH}"
            ${lib.concatStringsSep "\n" (lib.mapAttrsToList (name: value:
              ''export ${name}="''${${name}-${value}}"''
            ) (nativeHeaderEnvironment pkgs))}
            exec python3 -m src.devex.lsp "$@"
          '';
        };
        btrc-format = pkgs.writeShellApplication {
          name = "btrc-format";
          runtimeInputs = [ pkgs.python314 ];
          text = ''
            export PYTHONPATH="${formatterSource}''${PYTHONPATH:+:$PYTHONPATH}"
            exec ${pkgs.python314}/bin/python3 -m src.devex.formatter "$@"
          '';
        };
        nativePlan = pkgs.writeShellApplication {
          name = "btrc-native-plan";
          runtimeInputs = [ pkgs.python314 pkgs.stdenv.cc pkgs.pkg-config ];
          text = ''
            export PYTHONPATH="${nativePlanSource}"
            exec ${pkgs.python314}/bin/python3 -P -m tools.native_plan "$@"
          '';
        };
        nativeHeaderReader = pkgs.llvmPackages_21.stdenv.mkDerivation {
          pname = "btrc-native-header";
          version = "0";
          src = ./tools/NativeHeaderReader.cpp;
          dontUnpack = true;
          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = with pkgs.llvmPackages_21; [ libclang llvm ];
          buildPhase = ''
            runHook preBuild
            $CXX -std=c++17 -Wall -Wextra -Werror \
              -DBTRC_NATIVE_CLANG_DRIVER='"${pkgs.llvmPackages_21.stdenv.cc}/bin/clang"' \
              -DBTRC_NATIVE_CLANGXX_DRIVER='"${pkgs.llvmPackages_21.stdenv.cc}/bin/clang++"' \
              -DBTRC_NATIVE_CLANG_COMPILER='"${pkgs.llvmPackages_21.stdenv.cc.cc}/bin/clang"' \
              -DBTRC_NATIVE_CLANGXX_COMPILER='"${pkgs.llvmPackages_21.stdenv.cc.cc}/bin/clang++"' \
              "$src" -lclang-cpp -lLLVM -o btrc-native-header
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/bin"
            install -m755 btrc-native-header "$out/bin/"
            wrapProgram "$out/bin/btrc-native-header" --prefix PATH : ${lib.makeBinPath [ pkgs.pkg-config ]}
            runHook postInstall
          '';
        };
        # The Java class-file reader: strict C11 and zlib, which inflates jar
        # entries. It needs no JVM and no LLVM.
        javaClassReader = pkgs.stdenv.mkDerivation {
          pname = "btrc-java-class-reader";
          version = "0";
          src = ./tools/JavaClassReader.c;
          dontUnpack = true;
          buildInputs = [ pkgs.zlib ];
          buildPhase = ''
            runHook preBuild
            $CC -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 "$src" -lz -o btrc-java-class-reader
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            install -Dm755 btrc-java-class-reader "$out/bin/btrc-java-class-reader"
            runHook postInstall
          '';
        };
        # wgpu-native dlopens the Vulkan loader. A NixOS host whose driver
        # package carries one (NVIDIA's) has it under the driver prefix, which
        # comes first; a Mesa-only host such as the Steam Deck has none there,
        # so nixpkgs' loader follows. Either loader finds the host's drivers
        # through /run/opengl-driver/share/vulkan/icd.d.
        wgpuNativeLibrary = if isDarwin then pkgs.wgpu-native else pkgs.runCommand "wgpu-native-driver-runpath" {
          nativeBuildInputs = [ pkgs.patchelf ];
        } ''
          mkdir -p "$out/lib"
          cp ${pkgs.wgpu-native}/lib/* "$out/lib/"
          chmod u+w "$out/lib/"*
          for library in "$out"/lib/*.so; do
            patchelf --add-rpath /run/opengl-driver/lib:${pkgs.vulkan-loader}/lib "$library"
          done
        '';
        # JNI headers and HotSpot for the optional JavaHost package: its JNI.h
        # binding and runtime source compile against this, and its tests create
        # a VM under -Xcheck:jni. Android reads jni.h from the NDK sysroot and
        # links no VM. Only JavaHost consumers and desktop JNI tests select this.
        javaNativeInterface = let
          jdk = pkgs.jdk17_headless;
          platform = if isDarwin then "darwin" else "linux";
        in pkgs.writeTextDir "lib/pkgconfig/btrc-jni.pc" ''
          Name: btrc-jni
          Description: JNI headers and the HotSpot VM for btrc host-JVM programs
          Version: ${jdk.version}
          Cflags: -I${jdk.home}/include -I${jdk.home}/include/${platform}
          Libs: -L${jdk.home}/lib/server -Wl,-rpath,${jdk.home}/lib/server -ljvm
        '';
        nativeWebGpu = pkgs.symlinkJoin {
          name = "wgpu-native-${pkgs.wgpu-native.version}";
          paths = [ wgpuNativeLibrary pkgs.wgpu-native.dev
            (pkgs.writeTextDir "lib/pkgconfig/wgpu-native.pc" ''
              Name: wgpu-native
              Description: Pinned WebGPU native implementation
              Version: ${pkgs.wgpu-native.version}
              Cflags: -I${pkgs.wgpu-native.dev}/include/webgpu
              Libs: -L${wgpuNativeLibrary}/lib -Wl,-rpath,${wgpuNativeLibrary}/lib${lib.optionalString (!isDarwin) " -Wl,-rpath,/run/opengl-driver/lib"} -lwgpu_native
            '')
          ];
        };
        btrc = pkgs.symlinkJoin {
          name = "btrc-tools";
          paths = [ btrcpy btrcc btrc-format nativePlan ];
        };
        devcontainerFiles = name: generated: pkgs.linkFarm name
          (lib.mapAttrsToList (name: content: {
            inherit name;
            path = pkgs.writeTextFile {
              inherit name;
              text = content;
              executable = lib.hasSuffix ".sh" name;
            };
          }) generated);
        btrc-vscode = pkgs.buildNpmPackage {
          pname = "vscode-extension-btrc";
          version = extensionVersion;
          src = extensionSource;
          sourceRoot = "source/src/devex/vscode";
          npmDepsHash = "sha256-xm6xxb4Nz1kYBJSRBkO3hJmOsw7vZRUkOkZtLQq+MWI=";
          npmInstallFlags = [ "--ignore-scripts" ];
          npmRebuildFlags = [ "--ignore-scripts" ];
          nodejs = pkgs.nodejs_22;
          nativeBuildInputs = [ pkgs.esbuild lspPython ];
          buildPhase = ''
            runHook preBuild
            bundle_root="$TMPDIR/btrc-vscode-bundle"
            BTRC_PACKAGING_OUTPUT_ROOT="$bundle_root" node packaging/prepare.js
            cp -R node_modules "$bundle_root/node_modules"
            cd "$bundle_root"
            npm run typecheck
            npm run compile
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            extension="$out/share/vscode/extensions/btrc-dev.btrc"
            mkdir -p "$extension"
            cp package.json LICENSE "$extension"/
            cp -R assets config out server "$extension"/
            runHook postInstall
          '';
          passthru = {
            vscodeExtPublisher = "btrc-dev";
            vscodeExtName = "btrc";
            vscodeExtUniqueId = "btrc-dev.btrc";
          };
        };
      in {
        inherit btrcpy btrcc btrc-format btrc-lsp;
        stdlib-windows-sdk = import ./nix/stdlib-windows-sdk.nix { inherit pkgs; };
        btrc-gpu = btrcGpu;
        btrc-native-plan = nativePlan;
        btrc-native-header = nativeHeaderReader;
        btrc-java-class-reader = javaClassReader;
        btrc-jni = javaNativeInterface;
        wgpu-native = nativeWebGpu;
        btrc-vscode-extension = btrc-vscode;
        inherit btrc;
        default = btrc;
        # nix build .#devcontainer (or .#devcontainer-ci) generates .devcontainer/.
        devcontainer = devcontainerFiles "${cfg.name}-devcontainer" files;
        devcontainer-ci = devcontainerFiles "${cfg.name}-devcontainer-ci" ciFiles;
      });
      # What another repository builds and tests its BTRC programs with. Each
      # function takes that repository's `pkgs` first; the compiler and the
      # native plan builder are this flake's, for the system that builds.
      lib = {
        # buildPackage pkgs { name; src; programs; buildInputs; runtimeInputs;
        #   linkFlags; linkPlan; nativeBuildInputs; env; wrapperArgs; postInstall; }
        buildPackage = pkgs: self.lib.buildPackageWith { inherit pkgs; };
        # The same builder with another compiler; `btrc-native-plan = null`
        # builds without a link plan unless a call says `linkPlan = true`.
        buildPackageWith = {
          pkgs,
          btrcpy ? self.packages.${pkgs.stdenv.buildPlatform.system}.btrcpy,
          btrc-native-plan ? self.packages.${pkgs.stdenv.buildPlatform.system}.btrc-native-plan,
        }: import ./nix/lib/build-package.nix { inherit pkgs btrcpy btrc-native-plan; };
        # sources { lib } root entry: the files a program is built from, as a fileset.
        sources = import ./nix/lib/sources.nix;
        # The test library as a package directory, and a source tree with it inside:
        # withTestkit pkgs { name; src; at ? "testkit"; }
        testkit = ./nix/lib/testkit;
        withTestkit = pkgs: import ./nix/lib/with-testkit.nix { inherit pkgs; };
        # vmTest pkgs { name; nodes; scenario; extraFiles; settings; graphical; }
        vmTest = pkgs: import ./nix/lib/vm-test.nix {
          inherit pkgs;
          buildPackage = self.lib.buildPackage pkgs;
          withTestkit = self.lib.withTestkit pkgs;
        };
      };
      checks = eachSystem (pkgs: let
        system = pkgs.stdenv.hostPlatform.system;
        nativeTarget = {
          aarch64-darwin = "macos-arm64";
          x86_64-darwin = "macos-x64";
          x86_64-linux = "linux-x64";
          aarch64-linux = "linux-arm64";
        }.${system};
      in {
        gpu-runtime-package = pkgs.runCommand "btrc-gpu-runtime-package-check" {
          nativeBuildInputs = [
            pkgs.pkg-config
            pkgs.stdenv.cc
          ];
          buildInputs = [ self.packages.${system}.btrc-gpu ];
        } ''
          pkg-config --validate btrc-gpu
          gpuLicenseRoot=${self.packages.${system}.btrc-gpu}/share/licenses/btrc
          cmp ${./LICENSE} "$gpuLicenseRoot/LICENSE"
          cmp ${pkgs.wgpu-native.src}/LICENSE.APACHE \
            "$gpuLicenseRoot/third-party/wgpu-native/LICENSE.APACHE"
          cmp ${pkgs.wgpu-native.src}/LICENSE.MIT \
            "$gpuLicenseRoot/third-party/wgpu-native/LICENSE.MIT"
          cmp ${pkgs.wgpu-native.src}/ffi/webgpu-headers/LICENSE \
            "$gpuLicenseRoot/third-party/webgpu-headers/LICENSE"
          printf '%s\n' \
            '#include <btrc_gpu_compute_internal.h>' \
            'int main(void) {' \
            '  btrc_gpu_destroy(0);' \
            '  return btrc_gpu_available() ? 1 : 0;' \
            '}' > smoke.c
          cc -std=c11 -pedantic-errors -Wall -Wextra -Werror \
            $(pkg-config --cflags btrc-gpu) smoke.c \
            $(pkg-config --libs btrc-gpu) -lm -pthread -o smoke
          BTRC_NO_GPU=1 ./smoke
          mkdir -p "$out"
          cp smoke "$out/"
        '';
        native-package-plan = pkgs.runCommand "btrc-native-package-plan-check" {
          nativeBuildInputs = [
            pkgs.gnumake
            pkgs.jq
            pkgs.stdenv.cc
            self.packages.${system}.btrcc
            self.packages.${system}.btrcpy
            self.packages.${system}.btrc-native-plan
          ];
        } ''
          # The sandbox's HOME is read-only; both compilers publish generations
          # through a state directory, as the btrcc derivation does.
          export BTRC_STATE_DIR="$TMPDIR/btrc-state"
          export BTRC_CACHE_DIR="$TMPDIR/btrc-cache"
          mkdir source
          cp -R ${./examples/native-package}/. source/
          chmod -R u+w source
          make -C source run \
            TARGET=${nativeTarget} \
            BTRCPY=${self.packages.${system}.btrcpy}/bin/btrcpy \
            NATIVE_PLAN=${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan \
            CC=cc CXX=c++ PKG_CONFIG=pkg-config
          (
            cd source
            ${self.packages.${system}.btrcc}/bin/btrcc \
              --no-stdlib --strict-imports --target ${nativeTarget} \
              --emit-link-plan build/native-package.selfhost.link.json \
              src/Main.btrc > build/native-package.selfhost.c
            cmp \
              build/native-package.link.json \
              build/native-package.selfhost.link.json
            ${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan \
              --plan build/native-package.selfhost.link.json \
              --generated-c build/native-package.selfhost.c \
              --output build/native-package.selfhost \
              --cc cc --cxx c++ --pkg-config pkg-config
            ./build/native-package.selfhost
            # Cached objects are keyed through modules the plain build never
            # imports; the second build must reuse every translation unit.
            for run in 1 2; do
              ${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan \
                --plan build/native-package.link.json \
                --generated-c build/native-package.c \
                --output build/native-package.cached \
                --object-cache build/objects \
                --report-json "build/native-package.cached-$run.json" \
                --cc cc --cxx c++ --pkg-config pkg-config
              ./build/native-package.cached
            done
            jq -e '.reused_units == 0 and .compiled_units == (.units | length)' \
              build/native-package.cached-1.json
            jq -e '.compiled_units == 0 and .reused_units == (.units | length)' \
              build/native-package.cached-2.json
          )
          mkdir -p "$out"
          cp source/build/native-package*.link.json "$out/"
        '';
        # lib.buildPackage and lib.sources: a program whose manifest names a
        # pkg-config dependency is built from the files it imports, and runs.
        build-package = let
          program = self.lib.buildPackage pkgs {
            name = "btrc-build-package-check";
            src = lib.fileset.toSource {
              root = ./src/tests/native/build_package;
              fileset = self.lib.sources { inherit lib; } ./src/tests/native/build_package "Main.btrc";
            };
            programs.checksum = "Main.btrc";
            buildInputs = [ pkgs.zlib ];
          };
        in pkgs.runCommand "btrc-build-package-check" { passthru = { inherit program; }; } ''
          test "$(${program}/bin/checksum)" = "PASS: zlib through pkg-config"
          mkdir -p "$out"
        '';
        # The packaged formatter carries every module it imports: run from a folder that holds nothing else,
        # it formats a file. From the repository it finds the missing ones beside it, and so hid this once.
        formatter-starts = pkgs.runCommand "btrc-formatter-starts-check" { } ''
          printf 'int main() {\n\treturn 0;\n}\n' > probe.btrc
          ${self.packages.${system}.btrc-format}/bin/btrc-format write probe.btrc
          ${self.packages.${system}.btrc-format}/bin/btrc-format check probe.btrc
          mkdir -p "$out"
        '';
      } // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
        # lib.vmTest and the testkit package: a machine boots, runs a command,
        # reboots and still has the file it wrote. It boots a VM and needs KVM.
        vm-test = self.lib.vmTest pkgs {
          name = "btrc-vm-test";
          nodes.machine = { };
          scenario = ./src/tests/native/vm_test/Reboot.btrc;
          settings.marker = "kept-across-the-reboot";
        };
        # The kernel as the host of an emulated USB device; it boots a VM.
        usb-kernel-host = import ./src/tests/native/usb/usb-kernel-host.nix {
          inherit pkgs;
          btrcpy = self.packages.${system}.btrcpy;
          source = ./src/tests/native/usb;
        };
        # This machine as a USB device on a loopback controller; it boots VMs.
        usb-gadget-loopback = import ./src/tests/native/usb/usb-gadget-loopback.nix {
          inherit pkgs;
          btrcpy = self.packages.${system}.btrcpy;
          source = ./src/tests/native/usb;
        };
        # Filesystems served by a program, used through the kernel; it boots a VM.
        userspace-filesystem = import ./src/tests/native/userspace/userspace-filesystem.nix {
          inherit pkgs;
          btrcpy = self.packages.${system}.btrcpy;
          source = ./src/tests/native/userspace;
        };
        # A Bluetooth HID device and its host on emulated controllers; it boots a VM.
        bluetooth-hid-loopback = import ./src/tests/native/bluetooth/bluetooth-hid-loopback.nix {
          inherit pkgs;
          btrcpy = self.packages.${system}.btrcpy;
          source = ./src/tests/native/bluetooth;
        };
      });
    };
}
