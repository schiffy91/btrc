{ cfg, lib }:
let
  containerfile = import ./containerfile.nix { inherit cfg lib; };
  devcontainer = import ./devcontainer.nix { inherit cfg lib; };
  host = import ./host.nix { inherit cfg lib; };
in {
  "devcontainer.json" = builtins.toJSON devcontainer + "\n";
  "Containerfile" = containerfile.containerfile;
  "bashrc" = containerfile.bashrc;
  "host.sh" = host;
}
