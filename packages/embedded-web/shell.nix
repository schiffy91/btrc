{ pkgs, defaultShell }:
pkgs.mkShell (defaultShell // {
  packages = defaultShell.packages ++ [
    pkgs.webkitgtk_6_0.dev
    pkgs.gtk4.dev
    pkgs.glib.dev
  ];
  BTRC_GSETTINGS_SCHEMAS = "${pkgs.gtk4}/share/gsettings-schemas/${pkgs.gtk4.name}/glib-2.0/schemas";
})
