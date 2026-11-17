# Build a BTRC package's programs: `lib.buildPackage pkgs { name; src; programs; ... }`.
# `programs` maps each binary's name to its entry file, relative to `src`.
#
# `linkPlan` builds through btrc's native plan so `[[native.pkg-config]]` and
# `[[native.libraries]]` in `btrc.toml` drive compilation and linking directly.
{ pkgs, btrcpy, btrc-native-plan ? null }:
{ name, src, programs, buildInputs ? [], runtimeInputs ? [], linkFlags ? []
, linkPlan ? (btrc-native-plan != null && linkFlags == [])
, nativeBuildInputs ? [], env ? {}, wrapperArgs ? [], postInstall ? "" }:
pkgs.stdenv.mkDerivation {
  inherit name src buildInputs env postInstall;
  nativeBuildInputs = [ btrcpy pkgs.makeWrapper pkgs.pkg-config ] ++ nativeBuildInputs
    ++ pkgs.lib.optional linkPlan btrc-native-plan;
  CPATH = pkgs.lib.makeSearchPath "include" (map pkgs.lib.getDev buildInputs);
  dontConfigure = true;
  buildPhase = ''
    runHook preBuild
    export BTRC_CACHE_DIR="$TMPDIR/btrc-cache"
    export BTRC_STATE_DIR="$TMPDIR/btrc-state"
    export BTRC_PKG_CACHE="$TMPDIR/btrc-packages"
    ${pkgs.lib.concatStringsSep "\n" (pkgs.lib.mapAttrsToList (binary: entry: if linkPlan then ''
      btrcpy --strict-imports ${pkgs.lib.escapeShellArg entry} -o ${pkgs.lib.escapeShellArg "${binary}.c"} --emit-link-plan ${pkgs.lib.escapeShellArg "${binary}.link.json"}
      btrc-native-plan --plan ${pkgs.lib.escapeShellArg "${binary}.link.json"} --generated-c ${pkgs.lib.escapeShellArg "${binary}.c"} --output ${pkgs.lib.escapeShellArg binary} --cc ${pkgs.stdenv.cc}/bin/cc --cxx ${pkgs.stdenv.cc}/bin/c++ --pkg-config ${pkgs.pkg-config}/bin/pkg-config  # by path: the tool's own wrapper puts its compiler first
    '' else ''
      btrcpy --strict-imports ${pkgs.lib.escapeShellArg entry} -o ${pkgs.lib.escapeShellArg "${binary}.c"}
      $CC -std=c11 -O2 ${pkgs.lib.escapeShellArg "${binary}.c"} -lm -lpthread ${pkgs.lib.escapeShellArgs linkFlags} -o ${pkgs.lib.escapeShellArg binary}
    '') programs)}
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin"
    ${pkgs.lib.concatMapStringsSep "\n" (binary: ''
      install -m755 ${pkgs.lib.escapeShellArg binary} "$out/bin/${binary}"
      ${pkgs.lib.optionalString (runtimeInputs != [] || wrapperArgs != []) ''
        wrapProgram "$out/bin/${binary}" ${pkgs.lib.escapeShellArgs (
          pkgs.lib.optionals (runtimeInputs != []) [ "--prefix" "PATH" ":" (pkgs.lib.makeBinPath runtimeInputs) ] ++ wrapperArgs
        )}
      ''}
    '') (builtins.attrNames programs)}
    runHook postInstall
  '';
}
