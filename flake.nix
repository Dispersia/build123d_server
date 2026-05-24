{
  description = "Python app to reload YACV";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        libPath = pkgs.lib.makeLibraryPath [
          pkgs.libglvnd
          pkgs.mesa

          pkgs.libx11
          pkgs.libxext
          pkgs.libxrender
          pkgs.libice
          pkgs.libsm

          pkgs.stdenv.cc.cc.lib

          pkgs.expat
        ];

      in
      {
        packages.default = pkgs.writeShellApplication {
          name = "b123d-server";

          runtimeInputs = [
            pkgs.python312
            pkgs.uv
          ];

          text = ''
            export UV_PROJECT_ENVIRONMENT="$HOME/.cache/build123d-server/.venv"
            export LD_LIBRARY_PATH="${libPath}:''${LD_LIBRARY_PATH:-}"

            user_venv="''${VIRTUAL_ENV:-.venv}"
            for sp in "$user_venv"/lib/python*/site-packages; do
              if [[ -d "$sp" ]]; then
                export B123D_USER_SITE
                B123D_USER_SITE="$(realpath "$sp")"
                break
              fi
            done
            unset VIRTUAL_ENV

            exec uv run --project ${self} --directory "$PWD" b123d-server "$@"
          '';
        };
      });
}
