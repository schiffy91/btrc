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
            ruff gcc clang zig gnumake git jq gh nodejs_22 nixd wgpu-native glfw freetype
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            bubblewrap libx11.dev libxrandr.dev libxinerama.dev libxcursor.dev libxi.dev
            wayland.dev pkg-config dbus.dev   # native windowing and system-tray shims
          ];
      };
      files = import ./build { inherit cfg lib; };
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs { inherit system; }));
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
        btrc-native-plan = {
          type = "app";
          program = "${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan";
        };
      });
      devShells = eachSystem (pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        system = pkgs.stdenv.hostPlatform.system;
      in {
        default = pkgs.mkShell {
          # btrc-lsp on PATH: the VSCode extension launches the language server
          # via `nix develop <workspace> --command btrc-lsp`.
          packages = cfg.packages pkgs ++ [ self.packages.${system}.btrc-lsp ];
          APP_CFLAGS = "-DGLFW_INCLUDE_NONE -I${pkgs.glfw.dev}/include";
          APP_LDFLAGS = "-L${pkgs.glfw}/lib -lglfw"
            + lib.optionalString isDarwin
              " -framework Cocoa -framework IOKit -framework CoreVideo";
          GPU_CFLAGS = "-DGLFW_INCLUDE_NONE -I${pkgs.wgpu-native.dev}/include/webgpu -I${pkgs.glfw.dev}/include"
            + lib.optionalString pkgs.stdenv.hostPlatform.isLinux
              " -I${pkgs.wayland.dev}/include";
          GPU_LDFLAGS = "-L${pkgs.wgpu-native}/lib -lwgpu_native -L${pkgs.glfw}/lib -lglfw"
            + lib.optionalString isDarwin
              " -framework Metal -framework QuartzCore -framework Cocoa -framework IOKit -framework CoreVideo";
          FONT_CFLAGS = "-I${pkgs.freetype.dev}/include/freetype2";
          FONT_LDFLAGS = "-L${pkgs.freetype}/lib -lfreetype";
        };
      });
      packages = eachSystem (pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        isLinux = pkgs.stdenv.hostPlatform.isLinux;
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
        appRuntimeSource = sourceSubset {
          prefixes = [ "src/stdlib/app/" ];
          excludedPrefixes = [ ];
        };
        gpuRuntimeSource = sourceSubset {
          prefixes = [
            "src/stdlib/app/"
            "src/stdlib/gpu/"
          ];
          excludedPrefixes = [ ];
        };
        nativePlanSource = sourceSubset {
          prefixes = [ "tools/native_plan.py" ];
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
            btrcpy --strict-imports --no-cache \
              src/compiler/btrc/btrcc_main.btrc -o btrcc.c
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
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/bin" "$out/share/btrc/language"
            install -m 0755 ${btrccExecutable}/bin/btrcc "$out/bin/btrcc"
            install -m 0644 src/language/grammar.ebnf \
              "$out/share/btrc/language/grammar.ebnf"
            cp -R src/stdlib "$out/share/btrc/stdlib"
            runHook postInstall
          '';
        };
        appFrameworks = lib.optionalString isDarwin
          " -framework Cocoa -framework IOKit -framework CoreVideo";
        gpuFrameworks = lib.optionalString isDarwin
          " -framework Metal -framework QuartzCore -framework Cocoa -framework IOKit -framework CoreVideo";
        appCompileFlags = "-DGLFW_INCLUDE_NONE -I${pkgs.glfw.dev}/include";
        gpuCompileFlags = appCompileFlags
          + " -DBTRC_GPU_WGPU_NATIVE -I${pkgs.wgpu-native.dev}/include/webgpu"
          + lib.optionalString isLinux
            " -I${pkgs.libx11.dev}/include -I${pkgs.wayland.dev}/include";
        appPkgConfig = pkgs.writeText "btrc-app.pc.in" ''
          prefix=@out@
          libdir=''${prefix}/lib
          includedir=''${prefix}/include

          Name: btrc-app
          Description: BTRC application and window runtime
          Version: 0
          Cflags: -I''${includedir}
          Libs: -L''${libdir} -lbtrc_app -L${pkgs.glfw}/lib -lglfw${appFrameworks}
        '';
        gpuPkgConfig = pkgs.writeText "btrc-gpu.pc.in" ''
          prefix=@out@
          libdir=''${prefix}/lib
          includedir=''${prefix}/include

          Name: btrc-gpu
          Description: BTRC application and WebGPU runtime
          Version: 0
          Cflags: -I''${includedir}
          Libs: -L''${libdir} -lbtrc_gpu -lbtrc_app -L${pkgs.wgpu-native}/lib -lwgpu_native -L${pkgs.glfw}/lib -lglfw${gpuFrameworks}
        '';
        btrcApp = pkgs.stdenv.mkDerivation {
          pname = "btrc-app";
          version = "0";
          src = appRuntimeSource;
          strictDeps = true;
          propagatedBuildInputs = [ pkgs.glfw ];
          buildPhase = ''
            runHook preBuild
            $CC -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 \
              -pthread ${appCompileFlags} -Isrc/stdlib/app \
              -c src/stdlib/app/btrc_app.c -o btrc_app.o
            $AR rcs libbtrc_app.a btrc_app.o
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/include" "$out/lib/pkgconfig"
            install -m 0644 src/stdlib/app/btrc_app.h "$out/include/"
            install -m 0644 libbtrc_app.a "$out/lib/"
            substitute ${appPkgConfig} "$out/lib/pkgconfig/btrc-app.pc" \
              --replace-fail @out@ "$out"
            runHook postInstall
          '';
        };
        btrcGpu = pkgs.stdenv.mkDerivation {
          pname = "btrc-gpu";
          version = "0";
          src = gpuRuntimeSource;
          strictDeps = true;
          buildInputs = [ btrcApp ];
          propagatedBuildInputs = [
            pkgs.glfw
            pkgs.wgpu-native
          ] ++ lib.optionals isLinux [
            pkgs.libx11.dev
            pkgs.wayland.dev
          ];
          buildPhase = ''
            runHook preBuild
            for source in \
              btrc_gpu.c \
              btrc_gpu_async.c \
              btrc_gpu_native_ui.c \
              btrc_gpu_surface.c; do
              $CC -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 \
                -pthread ${gpuCompileFlags} \
                -Isrc/stdlib/app -Isrc/stdlib/gpu \
                -c "src/stdlib/gpu/$source" -o "''${source%.c}.o"
            done
            objects="btrc_gpu.o btrc_gpu_async.o btrc_gpu_native_ui.o btrc_gpu_surface.o"
            ${lib.optionalString isDarwin ''
              $CC -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 \
                -x objective-c ${gpuCompileFlags} \
                -Isrc/stdlib/app -Isrc/stdlib/gpu \
                -c src/stdlib/gpu/btrc_gpu_surface_macos.m \
                -o btrc_gpu_surface_macos.o
              objects="$objects btrc_gpu_surface_macos.o"
            ''}
            $AR rcs libbtrc_gpu.a $objects
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/include" "$out/lib/pkgconfig"
            install -m 0644 src/stdlib/app/btrc_app.h "$out/include/"
            install -m 0644 src/stdlib/gpu/btrc_gpu.h "$out/include/"
            install -m 0644 ${btrcApp}/lib/libbtrc_app.a "$out/lib/"
            install -m 0644 libbtrc_gpu.a "$out/lib/"
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
        nativePlan = pkgs.writeShellApplication {
          name = "btrc-native-plan";
          runtimeInputs = [ pkgs.python314 pkgs.stdenv.cc pkgs.pkg-config ];
          text = ''
            export PYTHONPATH="${nativePlanSource}''${PYTHONPATH:+:$PYTHONPATH}"
            exec ${pkgs.python314}/bin/python3 -m tools.native_plan "$@"
          '';
        };
        btrc = pkgs.symlinkJoin {
          name = "btrc-tools";
          paths = [ btrcpy btrcc nativePlan ];
        };
        btrc-vscode = pkgs.buildNpmPackage {
          pname = "vscode-extension-btrc";
          version = extensionVersion;
          src = extensionSource;
          sourceRoot = "source/src/devex/vscode";
          npmDepsHash = "sha256-Onn3nJ4r8wTjX/32gc+75CNmid32yxdqnntB0xsZjcI=";
          npmInstallFlags = [ "--ignore-scripts" ];
          npmRebuildFlags = [ "--ignore-scripts" ];
          nodejs = pkgs.nodejs_22;
          nativeBuildInputs = [ pkgs.esbuild lspPython ];
          buildPhase = ''
            runHook preBuild
            node packaging/prepare.js
            bundle_root="$PWD/../../../build/devex/vscode"
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
        inherit btrcpy btrcc btrc-lsp btrc-vscode;
        btrc-app = btrcApp;
        btrc-gpu = btrcGpu;
        btrc-native-plan = nativePlan;
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
          printf '%s\n' \
            '#include <btrc_app.h>' \
            '#include <btrc_gpu.h>' \
            '#include <string.h>' \
            'int main(void) {' \
            '  if (std_app_error_code(0) != BTRC_APP_ERROR_NONE) { return 1; }' \
            '  return strcmp(std_gpu_status_message(BTRC_GPU_ATTACH_INVALID_SURFACE),' \
            '    "invalid or stale application surface") != 0;' \
            '}' > smoke.c
          cc -std=c11 -pedantic-errors -Wall -Wextra -Werror \
            $(pkg-config --cflags btrc-gpu) smoke.c \
            $(pkg-config --libs btrc-gpu) -lm -pthread -o smoke
          ./smoke
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
              src/main.btrc > build/native-package.selfhost.c
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
