{
  description = "btrc — a modern take on C";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
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
      });
      devShells = eachSystem (pkgs: let
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
        system = pkgs.stdenv.hostPlatform.system;
      in {
        default = pkgs.mkShell {
          # btrc-lsp on PATH: the VSCode extension launches the language server
          # via `nix develop <workspace> --command btrc-lsp`.
          packages = cfg.packages pkgs ++ [ self.packages.${system}.btrc-lsp ];
          GPU_CFLAGS = "-DGLFW_INCLUDE_NONE -I${pkgs.wgpu-native.dev}/include/webgpu -I${pkgs.glfw}/include"
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
                  || lib.hasInfix "/node_modules/" pathPrefix
                  || lib.hasSuffix "/.DS_Store" relativePath
                  || lib.any (suffix: lib.hasSuffix suffix relativePath) [
                    ".a" ".o" ".pyc" ".pyo" ".vsix"
                  ];
              in (needed || parent) && !derived;
          };
        runtimeSource = sourceSubset {
          prefixes = runtimePrefixes;
          excludedPrefixes = [
            "src/compiler/python/tests/"
            "src/devex/lsp/tests/"
            "src/stdlib/gpu/build/"
            "src/stdlib/gui/build/"
          ];
        };
        extensionVersion = (builtins.fromJSON (builtins.readFile ./src/devex/ext/package.json)).version;
        extensionSource = sourceSubset {
          prefixes = runtimePrefixes ++ [
            "src/devex/debug/"
            "src/devex/ext/"
          ];
          files = [ "flake.lock" ];
          excludedPrefixes = [
            "src/compiler/python/tests/"
            "src/devex/debug/tests/"
            "src/devex/ext/btrc.vsix"
            "src/devex/ext/debug/"
            "src/devex/ext/node_modules/"
            "src/devex/ext/out/"
            "src/devex/ext/server/"
            "src/devex/lsp/tests/"
            "src/stdlib/gpu/build/"
            "src/stdlib/gui/build/"
          ];
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
            exec python3 -m src.devex.lsp.server "$@"
          '';
        };
        btrc-vscode = pkgs.buildNpmPackage {
          pname = "vscode-extension-btrc";
          version = extensionVersion;
          src = extensionSource;
          sourceRoot = "source/src/devex/ext";
          npmDepsHash = "sha256-irbS7G2WHGkr8gjfeaL8i+HNkiSzW8jhu1yZQ8D0hHQ=";
          npmInstallFlags = [ "--ignore-scripts" ];
          npmRebuildFlags = [ "--ignore-scripts" ];
          nodejs = pkgs.nodejs_22;
          nativeBuildInputs = [ pkgs.esbuild pkgs.python314 ];
          buildPhase = ''
            runHook preBuild
            python3 scripts/prepare_lsp_package.py
            esbuild ./src/extension.ts ./src/launch.ts ./src/debug_launch.ts --bundle --outdir=out --external:vscode --format=cjs --platform=node
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            extension="$out/share/vscode/extensions/btrc-dev.btrc"
            mkdir -p "$extension"
            cp package.json language-configuration.json LICENSE "$extension"/
            cp -R debug icons out server syntaxes "$extension"/
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
        btrc-vscode-extension = btrc-vscode;
        btrc = btrcpy;
        default = btrcpy;
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
    };
}
