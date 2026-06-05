{
  description = "btrc — a modern take on C";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      cfg = {
        name = "btrc";
        image = "btrc-devcontainer:latest";
        runtime = "podman";
        machine = { memory = 8192; cpus = 4; disk = 100; };
        workspace = "/workspace";
        user = { name = "dev"; uid = 1000; };
        ports = [ 3000 ];
        extensions = [ "anthropic.claude-code" "ms-python.python" "jnoortheen.nix-ide" ];
        share = { ssh = true; git = true; gh = true; claude = true; };
        paths = { ssh = ".ssh"; gitconfig = ".gitconfig"; gh = ".config/gh"; claude = ".claude"; };
        claudeCode = { enable = true; version = "latest"; };
        initialShellCmd = "echo make help && make help";
        packages = pkgs: with pkgs; [
          (python314.withPackages (ps: [ ps.pytest ps.pytest-xdist ps.pytest-cov ps.pygls ps.lsprotocol ]))
            ruff gcc clang gnumake git jq gh nodejs_22 nixd wgpu-native glfw freetype
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            bubblewrap libx11.dev libxrandr.dev libxinerama.dev libxcursor.dev libxi.dev
            pkg-config dbus.dev   # native system-tray (StatusNotifierItem) shim
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
      in {
        default = pkgs.mkShell {
          packages = cfg.packages pkgs;
          GPU_CFLAGS = "-DGLFW_INCLUDE_NONE -I${pkgs.wgpu-native.dev}/include/webgpu -I${pkgs.glfw}/include"
            + lib.optionalString isDarwin " -x objective-c";
          GPU_LDFLAGS = "-L${pkgs.wgpu-native}/lib -lwgpu_native -L${pkgs.glfw}/lib -lglfw"
            + lib.optionalString isDarwin
              " -framework Metal -framework QuartzCore -framework Cocoa -framework IOKit -framework CoreVideo";
          FONT_CFLAGS = "-I${pkgs.freetype.dev}/include/freetype2";
          FONT_LDFLAGS = "-L${pkgs.freetype}/lib -lfreetype";
        };
      });
      packages = eachSystem (pkgs: let
        lspPython = pkgs.python314.withPackages (ps: [ ps.pygls ps.lsprotocol ]);
        btrcpy = pkgs.writeShellApplication {
          name = "btrcpy";
          runtimeInputs = [ pkgs.python314 ];
          text = ''
            export PYTHONPATH="${self}''${PYTHONPATH:+:$PYTHONPATH}"
            exec ${pkgs.python314}/bin/python3 -m src.compiler.python.main "$@"
          '';
        };
        btrc-lsp = pkgs.writeShellApplication {
          name = "btrc-lsp";
          runtimeInputs = [ lspPython ];
          text = ''
            export PYTHONPATH="${self}''${PYTHONPATH:+:$PYTHONPATH}"
            exec python3 -m src.devex.lsp.server "$@"
          '';
        };
      in {
        inherit btrcpy btrc-lsp;
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
