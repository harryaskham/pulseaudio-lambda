{ packages, config, lib, pkgs, ... }:

pkgs.mkShell {
  inputsFrom = [ packages.default ];

  packages = with pkgs; [
    # Development tools
    gdb
    valgrind
    bear  # For compile_commands.json

    # Audio tools for testing
    sox
    ffmpeg
    pavucontrol

    # Documentation
    man-pages
    man-pages-posix
  ];

  shellHook = ''
    echo "PulseAudio Lambda Development Environment"
    echo "==========================================="
    echo ""
    echo "Build with: make"
    echo "Test with: make test"
    echo "Clean with: make clean"
    echo ""
    echo "Load module: pactl load-module module-lambda source_name=lambda_source sink_name=lambda_sink lambda_command=/path/to/lambda"
    echo ""
  '';
}
