{
  description = "btrc — a language that transpiles to C";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs { inherit system; }));
    in {
      devShells = eachSystem (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            (python313.withPackages (ps: [ ps.pytest ps.pytest-xdist ]))
            ruff
            gcc
            gnumake

            # Dev tools
            git jq gh
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            bubblewrap  # sandbox (Linux only)
          ];
          shellHook = ''echo "btrc dev — run: make test"'';
        };
      });
    };
}
