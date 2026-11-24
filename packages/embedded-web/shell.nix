{ pkgs, defaultShell }:
pkgs.mkShell (defaultShell // {
  packages = defaultShell.packages ++ [ pkgs.webkitgtk_6_0.dev ];
})
