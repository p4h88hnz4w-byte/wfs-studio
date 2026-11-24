#!/bin/bash
# Build native/wfs-catalog/build/wfs-catalog.
# Checks out the wfslib submodule only. Does not clone vcpkg.

set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

if [ ! -f third_party/wfs-tools/wfslib/CMakeLists.txt ]; then
  git -C third_party/wfs-tools submodule update --init --depth 1 wfslib
fi

if [ -d /opt/homebrew/bin ]; then
  PATH="/opt/homebrew/bin:$PATH"
  export PATH
fi

# Linux builds require GCC 14.
gcc_major() {
  local ver
  ver=$("$1" -dumpversion 2>/dev/null || true)
  ver=${ver%%.*}
  printf '%s\n' "$ver"
}

cxx_flag=""
cc_flag=""
os_name=$(uname -s)
if [ -n "${WFS_CATALOG_UNAME:-}" ]; then
  os_name=$WFS_CATALOG_UNAME
fi
if [ "$os_name" = "Linux" ]; then
  if command -v g++-14 >/dev/null 2>&1; then
    cxx_bin=g++-14
  elif command -v g++ >/dev/null 2>&1; then
    cxx_bin=g++
  else
    cxx_bin=""
  fi
  cxx_major=""
  if [ -n "$cxx_bin" ]; then
    cxx_major=$(gcc_major "$cxx_bin")
  fi
  case "$cxx_major" in
    ''|*[!0-9]*)
      cxx_major=0
      ;;
  esac
  if [ "$cxx_major" -lt 14 ]; then
    echo "GCC 14 is required." >&2
    exit 1
  fi
  cxx_flag="-DCMAKE_CXX_COMPILER=$cxx_bin"
  if [ "$cxx_bin" = "g++-14" ] && command -v gcc-14 >/dev/null 2>&1; then
    cc_flag="-DCMAKE_C_COMPILER=gcc-14"
  fi
fi

if [ "${WFS_CATALOG_CHECK_ONLY:-}" = "1" ]; then
  if [ -n "$cxx_flag" ]; then
    printf '%s\n' "$cxx_bin"
  else
    echo default
  fi
  exit 0
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "cmake is required." >&2
  if [ "$os_name" != "Linux" ]; then
    echo "On this Mac: brew install cmake boost cryptopp" >&2
  fi
  exit 1
fi

if [ -d /opt/homebrew ]; then
  cmake -S native/wfs-catalog -B native/wfs-catalog/build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="/opt/homebrew" \
    $cc_flag $cxx_flag
else
  cmake -S native/wfs-catalog -B native/wfs-catalog/build \
    -DCMAKE_BUILD_TYPE=Release \
    $cc_flag $cxx_flag
fi

cmake --build native/wfs-catalog/build --parallel
echo "Built $root/native/wfs-catalog/build/wfs-catalog"
