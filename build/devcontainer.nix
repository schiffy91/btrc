{ cfg, lib }:
let
  home = "/home/${cfg.user.name}";
in
{
  name = "\${localWorkspaceFolderBasename}";
  image = "${cfg.name}-devcontainer:latest";
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
    ++ lib.optional cfg.share.claude
      "source=\${localWorkspaceFolderBasename}-claude-config,target=${home}/.claude,type=volume"
    ++ [ "source=\${localEnv:HOME}/.devcontainer-credentials,target=/tmp/credentials,type=bind,readonly" ];
  containerEnv = {
    CREDENTIALS_DIR = "/tmp/credentials";
    LD_LIBRARY_PATH = "/usr/lib/nix-fhs";
  } // lib.optionalAttrs cfg.share.claude {
    CLAUDE_CONFIG_DIR = "${home}/.claude";
  };
  initializeCommand = ".devcontainer/host.sh";
  postStartCommand = ".devcontainer/container.sh";
} // lib.optionalAttrs cfg.claudeCode.enable {
  postCreateCommand = "nix develop ${cfg.workspace} --command bash -c 'npm config set prefix ${home}/.local && npm install -g @anthropic-ai/claude-code@${cfg.claudeCode.version}'";
}
