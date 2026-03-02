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
          (python314.withPackages (ps: [ ps.pytest ps.pytest-xdist ]))
            ruff gcc gnumake git jq gh nodejs_22 nixd
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [ bubblewrap ];
      };
      files = import ./build { inherit cfg lib; };
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs { inherit system; }));
    in {
      devShells = eachSystem (pkgs: {
        default = pkgs.mkShell {
          packages = cfg.packages pkgs;
        };
      });
      packages = eachSystem (pkgs: {
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