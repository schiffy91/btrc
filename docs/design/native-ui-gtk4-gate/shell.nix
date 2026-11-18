# The btrc dev shell plus what the gate spike needs and the shell does not yet
# carry: WebKitGTK 6.0, the Wayland scanner and protocols, and all of Weston
# (for weston-screenshooter). From the flake's own nixpkgs.
#
#   nix develop --impure -f docs/design/native-ui-gtk4-gate/shell.nix
let
  # git+file: the tracked tree only, so a build directory's sockets are not copied.
  flake = builtins.getFlake ("git+file://" + toString ../../..);
  pkgs = import flake.inputs.nixpkgs { system = builtins.currentSystem; };
  shell = flake.devShells.${builtins.currentSystem}.default;
in pkgs.mkShell {
  inputsFrom = [ shell ];
  packages = with pkgs; [ webkitgtk_6_0 wayland-scanner wayland-protocols weston ];
  inherit (shell) BTRC_LAVAPIPE_ICD BTRC_VULKAN_LOADER BTRC_MESA_EGL BTRC_ATSPI_LIBEXEC;
}
