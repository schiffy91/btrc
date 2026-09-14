{ cfg, lib }:
let
  home = "/home/${cfg.user.name}";
in
{
  name = "\${localWorkspaceFolderBasename}";
  image = cfg.image;
  remoteUser = cfg.user.name;
  workspaceMount = "source=\${localWorkspaceFolder},target=${cfg.workspace},type=bind,consistency=delegated";
  workspaceFolder = cfg.workspace;
  forwardPorts = cfg.ports;
  customizations.vscode = {
    inherit (cfg) extensions;
    settings = {
      "terminal.integrated.defaultProfile.linux" = "bash";
      "python.defaultInterpreterPath" = "python3";
    };
  };
  mounts =
    [ "source=\${localWorkspaceFolderBasename}-bashhistory-\${devcontainerId},target=/commandhistory,type=volume" ]
    ++ lib.optional cfg.share.ssh
      "source=\${localEnv:HOME}/${cfg.paths.ssh},target=${home}/${cfg.paths.ssh},type=bind,readonly"
    ++ lib.optional cfg.share.git
      "source=\${localEnv:HOME}/${cfg.paths.gitconfig},target=${home}/${cfg.paths.gitconfig},type=bind,readonly"
    ++ lib.optional cfg.share.gh
      "source=\${localEnv:HOME}/${cfg.paths.gh},target=${home}/${cfg.paths.gh},type=bind,readonly"
    ++ lib.optional cfg.share.claude
      "source=\${localEnv:HOME}/${cfg.paths.claude},target=${home}/${cfg.paths.claude},type=bind";
  initializeCommand = ".devcontainer/host.sh";
}
