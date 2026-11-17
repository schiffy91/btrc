# The files a BTRC program is made from: its entry and the modules its package's manifest names (the
# compiler wants every exported and bound module to exist), every file those reach by relative imports,
# and the package's manifest, lock and C headers. A program built from these is not rebuilt by an edit
# to a file of its package that it does not import.
{ lib }: root: entry:
let
  manifest = builtins.fromTOML (builtins.readFile (root + "/btrc.toml"));
  named = (manifest.package.exports or [ ]) ++ map (binding: binding.module) (manifest.native.bindings or [ ]);
  module = name: root + "/${lib.replaceStrings [ "." ] [ "/" ] name}.btrc";
  imported = file: lib.concatMap (line:
    let found = builtins.match "import (\\.[^ ;]+\\.btrc).*" line;
    in lib.optional (found != null) (dirOf file + "/${builtins.head found}"))
    (lib.splitString "\n" (builtins.readFile file));
  item = file: { key = toString file; inherit file; };
  reached = builtins.genericClosure {
    startSet = map item ([ (root + "/${entry}") ] ++ map module named);
    operator = from: map item (imported from.file);
  };
in lib.fileset.unions (map (found: found.file) reached
  ++ [ (lib.fileset.fileFilter (file: file.hasExt "h" || file.name == "btrc.toml" || file.name == "btrc.lock") root) ])
