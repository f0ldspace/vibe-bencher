{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = with pkgs; [
    python3
    python3Packages.rich
    python3Packages.click
    python3Packages.questionary
  ];

  shellHook = ''
    export PYTHONPATH="$PWD:$PYTHONPATH"
    alias vb='python -m vibebencher'
    echo "vibebencher dev shell — use 'vb' or 'python -m vibebencher'"
  '';
}
