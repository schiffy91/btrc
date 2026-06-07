{ self, lib }:
{ pkgs, src, name, entry, nativeBuildInputs ? [], buildInputs ? [], extraCInputs ? [], extraCFlags ? [], extraLibs ? [], extraInstall ? "", usePrebuiltStdlib ? true }:
let
  system = pkgs.stdenv.hostPlatform.system;
  btrcpy = self.packages.${system}.btrcpy;
  shellWords = words: lib.concatStringsSep " " words;
  stdlib = pkgs.stdenv.mkDerivation {
    name = "btrc-stdlib";
    dontUnpack = true;
    nativeBuildInputs = [ btrcpy ];
    buildPhase = ''
      export HOME=$TMPDIR
      btrcpy --build-stdlib "$PWD/stdlib"
      $CC -std=c11 -O2 -ffunction-sections -fdata-sections \
        -c "$PWD/stdlib/btrc_stdlib.c" -o btrc_stdlib.o
      ar rcs libbtrc.a btrc_stdlib.o
    '';
    installPhase = ''
      mkdir -p $out
      cp "$PWD/stdlib/btrc_stdlib.h" $out/btrc_stdlib.h
      cp "$PWD/stdlib/btrc_stdlib.c" $out/btrc_stdlib.c
      cp "$PWD/stdlib/btrc_stdlib.manifest" $out/btrc_stdlib.manifest
      cp libbtrc.a $out/libbtrc.a
    '';
  };
  stdlibInput = if usePrebuiltStdlib then "${stdlib}/libbtrc.a" else "${stdlib}/btrc_stdlib.c";
  gcFlags = "-ffunction-sections -fdata-sections " + (if pkgs.stdenv.hostPlatform.isDarwin then "-Wl,-dead_strip" else "-Wl,--gc-sections");
in
pkgs.stdenv.mkDerivation {
  inherit name src buildInputs;
  nativeBuildInputs = [ btrcpy ] ++ nativeBuildInputs;
  buildPhase = ''
    export HOME=$TMPDIR
    btrcpy --no-stdlib --strict-imports --stdlib ${stdlib} "$src/${entry}" -o ${name}.c
    $CC -std=c11 -O2 -I${stdlib} ${gcFlags} ${shellWords extraCFlags} \
      ${name}.c ${shellWords extraCInputs} ${stdlibInput} ${shellWords extraLibs} -o ${name}
  '';
  installPhase = ''
    mkdir -p $out/bin
    cp ${name} $out/bin/${name}
    ${extraInstall}
  '';
}
