{
  description = "btrc — a modern take on C";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      cfg = {
        name = "btrc";
        image = "btrc-devcontainer:latest";
        baseImage = "alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b";
        nixInstallerVersion = "v3.21.5";
        nixInstallerSha256 = "c9368f4bbfbc78ace32bf018cb15534344b33c0161468deddbfcc8a04f7c9a01";
        runtime = "podman";
        machine = { memory = 8192; cpus = 4; disk = 100; };
        workspace = "/workspace";
        user = { name = "dev"; uid = 1000; };
        ports = [ 3000 ];
        extensions = [ "anthropic.claude-code" "ms-python.python" "jnoortheen.nix-ide" ];
        share = { ssh = true; git = true; gh = true; claude = true; };
        paths = { ssh = ".ssh"; gitconfig = ".gitconfig"; gh = ".config/gh"; claude = ".claude"; };
        claudeCode = { enable = true; version = "2.1.207"; };
        initialShellCmd = "echo make help && make help";
        packages = pkgs: with pkgs; [
          (python314.withPackages (ps: [
            ps.build ps.setuptools
            ps.pytest ps.pytest-xdist ps.pytest-cov ps.pygls ps.lsprotocol
          ]))
            ruff gcc clang zig gnumake git jq gh nodejs_22 nixd wgpu-native freetype
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            bubblewrap libx11.dev libxrandr.dev libxinerama.dev libxcursor.dev libxi.dev
            wayland.dev pkg-config dbus.dev   # native windowing and system-tray shims
            sdl3.dev fontconfig.dev libpng.dev libjpeg_turbo.dev alsa-lib.dev   # Linux GUI, image and audio providers
          ];
      };
      files = import ./nix { inherit cfg lib; };
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs { inherit system; }));
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
        btrcpy = self.apps.${system}.btrc;
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
      in {
        default = pkgs.mkShell ({
          # The test suite deliberately compiles strict C at -O0. Nixpkgs'
          # fortify setup diagnoses -O0 as a preprocessor warning, and -Werror
          # correctly promotes it. Release derivations retain their hardening;
          # only the interactive/test shell disables this incompatible pair.
          hardeningDisable = [ "fortify" "fortify3" ];
          # btrc-lsp on PATH: the VSCode extension launches the language server
          # via `nix develop <workspace> --command btrc-lsp`.
          packages = cfg.packages pkgs ++ [
            pkgs.pkg-config
            self.packages.${system}.wgpu-native
            self.packages.${system}.btrc-gpu
            self.packages.${system}.btrc-format
            self.packages.${system}.btrc-lsp
          ];
          GPU_CFLAGS = "-I${pkgs.wgpu-native.dev}/include/webgpu";
          GPU_LDFLAGS = "-L${pkgs.wgpu-native}/lib -lwgpu_native -pthread"
            + lib.optionalString isDarwin
              " -framework Metal -framework QuartzCore -framework Foundation";
          FONT_CFLAGS = "-I${pkgs.freetype.dev}/include/freetype2";
          FONT_LDFLAGS = "-L${pkgs.freetype}/lib -lfreetype";
        } // nativeHeaderEnvironment pkgs);
      });
      packages = eachSystem (pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        runtimePrefixes = [
          "src/compiler/python/"
          "src/devex/lsp/"
          "src/language/"
          "src/stdlib/"
        ];
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
                  && lib.any (prefix: lib.hasPrefix relativePrefix prefix) prefixes;
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
            "src/stdlib/"
          ];
          files = [ "LICENSE" ];
          excludedPrefixes = [ ];
        };
        gpuRuntimeSource = sourceSubset {
          prefixes = [
            "src/stdlib/GPU/"
          ];
          excludedPrefixes = [ ];
        };
        nativePlanSource = sourceSubset {
          prefixes = [
            "tools/native_plan.py"
            "src/compiler/python/artifacts/publication.py"
          ];
          excludedPrefixes = [ ];
        };
        formatterSource = sourceSubset {
          prefixes = [
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
            export PYTHONPATH="${runtimeSource}''${PYTHONPATH:+:$PYTHONPATH}"
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
                -Isrc/stdlib/GPU \
                -c "src/stdlib/GPU/$source" -o "''${source%.c}.o"
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
            install -m 0644 src/stdlib/GPU/btrc_gpu_compute_internal.h "$out/include/"
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
        # wgpu-native dlopens the Vulkan loader; on NixOS that lives under the
        # driver prefix, which the library's own runpath must name.
        wgpuNativeLibrary = if isDarwin then pkgs.wgpu-native else pkgs.runCommand "wgpu-native-driver-runpath" {
          nativeBuildInputs = [ pkgs.patchelf ];
        } ''
          mkdir -p "$out/lib"
          cp ${pkgs.wgpu-native}/lib/* "$out/lib/"
          chmod u+w "$out/lib/"*
          for library in "$out"/lib/*.so; do
            patchelf --add-rpath /run/opengl-driver/lib "$library"
          done
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
        inherit btrcpy btrcc btrc-format btrc-lsp btrc-vscode;
        btrc-gpu = btrcGpu;
        btrc-native-plan = nativePlan;
        btrc-native-header = nativeHeaderReader;
        wgpu-native = nativeWebGpu;
        btrc-vscode-extension = btrc-vscode;
        inherit btrc;
        default = btrc;
        devcontainer = pkgs.linkFarm "${cfg.name}-devcontainer" # nix build .#devcontainer — generates .devcontainer/ files
          (lib.mapAttrsToList (name: content: {
            inherit name;
            path = pkgs.writeTextFile {
              inherit name;
              text = content;
              executable = lib.hasSuffix ".sh" name;
            };
          }) files);
      });
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
            pkgs.stdenv.cc
            self.packages.${system}.btrcc
            self.packages.${system}.btrcpy
            self.packages.${system}.btrc-native-plan
          ];
        } ''
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
          )
          mkdir -p "$out"
          cp source/build/native-package*.link.json "$out/"
        '';
      });
    };
}
