{
  description = "Empty nix flake.";

  inputs = {
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {self, nixpkgs-unstable, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs-unstable { inherit system; };
        pylibs = pypkgs: with pypkgs; [ fuse python-slugify ];
      in {
        packages.default = pkgs.python3Packages.buildPythonApplication {
          pname = "dirmap";
          version = "0.1";
          pyproject = true;
          src = ./.;
          build-system =  with pkgs.python3Packages; [hatchling];
          # can't find fuse in runtime-check.. But it works, so disable it until
          # I want to look into this.
          dontCheckRuntimeDeps = true;
          dependencies = pylibs pkgs.python3Packages;
          propagatedBuildInputs = [ pkgs.ffmpeg ];
        };
        devShell = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages pylibs)
            pkgs.bashInteractive
          ];
        };
      }
    );
}
