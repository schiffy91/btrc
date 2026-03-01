# GPU setup — declarative version of scripts/setup-gpu.sh
#
# Provides a shell script that installs WebGPU (wgpu-native) + GLFW
# and builds the btrc GPU C runtime (libbtrc_gpu.a).
{ cfg, lib, pkgs }:
let
  gpuDir = "${cfg.workspace}/src/stdlib/gpu";
  buildDir = "${gpuDir}/build";
in
{
  setupScript = pkgs.writeShellScriptBin "btrc-setup-gpu" ''
    set -euo pipefail

    GPU_DIR="${gpuDir}"
    BUILD_DIR="${buildDir}"
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    USE_DAWN=false
    if [[ "''${1:-}" == "--dawn" ]]; then
      USE_DAWN=true
    fi

    echo "=== btrc GPU setup ==="
    echo "Platform: $OS $ARCH"

    # ---- Install dependencies ----
    if [[ "$OS" == "Darwin" ]]; then
      if ! command -v brew &>/dev/null; then
        echo "Error: Homebrew required. Install from https://brew.sh" >&2
        exit 1
      fi

      echo "--- Installing GLFW ---"
      brew install glfw 2>/dev/null || echo "GLFW already installed"

      if [[ "$USE_DAWN" == "false" ]]; then
        echo "--- Installing wgpu-native ---"
        brew install wgpu-native 2>/dev/null || echo "wgpu-native already installed"
        WEBGPU_INCLUDE="$(brew --prefix wgpu-native)/include"
        WEBGPU_LIB="$(brew --prefix wgpu-native)/lib"
      else
        echo "--- Building Dawn from source ---"
        BTRC_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
        DAWN_DIR="$BTRC_ROOT/deps/dawn"
        if [ ! -d "$DAWN_DIR" ]; then
          mkdir -p "$BTRC_ROOT/deps"
          git clone https://dawn.googlesource.com/dawn "$DAWN_DIR"
          cd "$DAWN_DIR"
          cp scripts/standalone.gclient .gclient
          gclient sync
        fi
        cd "$DAWN_DIR"
        mkdir -p out/Release && cd out/Release
        cmake ../.. -DCMAKE_BUILD_TYPE=Release \
                    -DDAWN_BUILD_SAMPLES=OFF \
                    -DDAWN_ENABLE_D3D11=OFF \
                    -DDAWN_ENABLE_D3D12=OFF \
                    -DDAWN_ENABLE_NULL=OFF
        make -j"$(sysctl -n hw.ncpu)" dawn_native dawn_proc
        WEBGPU_INCLUDE="$DAWN_DIR/include:$DAWN_DIR/out/Release/gen/include"
        WEBGPU_LIB="$DAWN_DIR/out/Release/src/dawn"
      fi

      GLFW_INCLUDE="$(brew --prefix glfw)/include"
      GLFW_LIB="$(brew --prefix glfw)/lib"

    elif [[ "$OS" == "Linux" ]]; then
      echo "Installing via system package manager..."
      if command -v apt-get &>/dev/null; then
        sudo apt-get install -y libglfw3-dev
      elif command -v dnf &>/dev/null; then
        sudo dnf install -y glfw-devel
      fi

      WGPU_VERSION="v25.0.2.2"
      WGPU_DIR="$BTRC_ROOT/deps/wgpu-native"
      if [ ! -d "$WGPU_DIR" ]; then
        mkdir -p "$WGPU_DIR"
        echo "Downloading wgpu-native $WGPU_VERSION..."
        curl -L "https://github.com/gfx-rs/wgpu-native/releases/download/$WGPU_VERSION/wgpu-linux-x86_64-release.zip" \
          -o /tmp/wgpu.zip
        unzip -o /tmp/wgpu.zip -d "$WGPU_DIR"
        rm /tmp/wgpu.zip
      fi

      WEBGPU_INCLUDE="$WGPU_DIR"
      WEBGPU_LIB="$WGPU_DIR"
      GLFW_INCLUDE="/usr/include"
      GLFW_LIB="/usr/lib/x86_64-linux-gnu"
    else
      echo "Error: Unsupported platform $OS" >&2
      exit 1
    fi

    # ---- Build C runtime ----
    echo "--- Building btrc GPU runtime ---"
    mkdir -p "$BUILD_DIR"

    cat > "$BUILD_DIR/gpu_paths.sh" <<PATHS
    WEBGPU_INCLUDE="$WEBGPU_INCLUDE"
    WEBGPU_LIB="$WEBGPU_LIB"
    GLFW_INCLUDE="$GLFW_INCLUDE"
    GLFW_LIB="$GLFW_LIB"
    PATHS

    IFS=':' read -ra WEBGPU_INCS <<< "$WEBGPU_INCLUDE"
    INCLUDE_FLAGS=""
    for inc in "''${WEBGPU_INCS[@]}"; do
      INCLUDE_FLAGS="$INCLUDE_FLAGS -I$inc"
    done

    if [[ "$OS" == "Darwin" ]]; then
      clang -x objective-c -c "$GPU_DIR/btrc_gpu.c" -o "$BUILD_DIR/btrc_gpu.o" \
        $INCLUDE_FLAGS -I"$GLFW_INCLUDE" -Wall -Wextra -O2
    else
      gcc -c "$GPU_DIR/btrc_gpu.c" -o "$BUILD_DIR/btrc_gpu.o" \
        $INCLUDE_FLAGS -I"$GLFW_INCLUDE" -Wall -Wextra -O2
    fi

    ar rcs "$BUILD_DIR/libbtrc_gpu.a" "$BUILD_DIR/btrc_gpu.o"

    echo ""
    echo "=== btrc GPU setup complete ==="
    echo "Runtime:  $BUILD_DIR/libbtrc_gpu.a"
    echo ""
    echo "To compile a btrc GPU program:"
    echo "  python3 -m src.compiler.python.main your_program.btrc -o your_program.c"
    if [[ "$OS" == "Darwin" ]]; then
      echo "  clang your_program.c -o your_program \\"
      echo "    -I$GPU_DIR -L$BUILD_DIR -lbtrc_gpu \\"
      echo "    -L$WEBGPU_LIB -lwgpu_native \\"
      echo "    -L$GLFW_LIB -lglfw \\"
      echo "    -framework Metal -framework QuartzCore -framework Cocoa \\"
      echo "    -framework IOKit -framework CoreVideo -lm"
    else
      echo "  gcc your_program.c -o your_program \\"
      echo "    -I$GPU_DIR -L$BUILD_DIR -lbtrc_gpu \\"
      echo "    -L$WEBGPU_LIB -lwgpu_native \\"
      echo "    -lglfw -lm -lpthread"
    fi
  '';
}
