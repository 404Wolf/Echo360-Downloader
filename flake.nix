{
  description = "Echo360 video downloading utility";

  inputs = {
    flake-utils = { url = "github:numtide/flake-utils"; };
    nixpkgs = { url = "github:nixos/nixpkgs/nixos-unstable"; };
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; })
          mkPoetryApplication;
      in rec {
        LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
        necessaryBuildInputs =
          [ pkgs.jellyfin-ffmpeg pkgs.poetry pkgs.geckodriver pkgs.firefox ];

        packages = {
          inherit LD_LIBRARY_PATH;
          myapp = mkPoetryApplication {
            inherit necessaryBuildInputs;
            projectDir = self;
          };
          default = self.packages.${system}.myapp;
        };

        devShells.default = pkgs.mkShell {
          inherit LD_LIBRARY_PATH;
          packages = [ pkgs.vlc pkgs.poetry ] ++ necessaryBuildInputs;
          inputsFrom = [ self.packages.${system}.myapp ];
        };
      });
}
