{ pkgs, project }:
let
  cross = pkgs.pkgsCross.aarch64-multiplatform;
  build = compiler: staticLib: name: source:
    compiler.stdenv.mkDerivation {
      pname = name;
      version = "1";
      dontUnpack = true;
      buildInputs = [ staticLib ];
      buildPhase = ''
        $CC -static -O2 -Wall -Wextra -Werror -std=gnu11 \
          ${project}/${source} -o ${name}
        if ${compiler.stdenv.cc.targetPrefix}readelf -l ${name} | grep -q INTERP; then
          echo "Diagnostic must be static" >&2
          exit 1
        fi
      '';
      installPhase = ''
        mkdir -p "$out/bin" "$out/evidence"
        cp ${name} "$out/bin/"
        cp ${project}/${source} "$out/evidence/"
      '';
      dontPatchELF = true;
    };
in {
  runner = build cross cross.glibc.static "readonly-runner" "tools/readonly-runner.c";
  runnerNative = build pkgs pkgs.glibc.static "readonly-runner" "tools/readonly-runner.c";
  reader = build cross cross.glibc.static "readonly-range-reader" "tools/readonly-range-reader.c";
  readerNative = build pkgs pkgs.glibc.static "readonly-range-reader" "tools/readonly-range-reader.c";
  testChild = build cross cross.glibc.static "readonly-runner-child" "tests/readonly_runner_child.c";
  testChildNative = build pkgs pkgs.glibc.static "readonly-runner-child" "tests/readonly_runner_child.c";
}
