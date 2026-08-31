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
          paths = [ btrcpy nativePlan ];
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
        inherit btrcpy btrc-lsp btrc-vscode;
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
        native-package-plan = pkgs.runCommand "btrc-native-package-plan-check" {
          nativeBuildInputs = [
            pkgs.gnumake
            pkgs.stdenv.cc
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
          mkdir -p "$out"
          cp source/build/native-package.link.json "$out/"
        '';
      });
    };
}
