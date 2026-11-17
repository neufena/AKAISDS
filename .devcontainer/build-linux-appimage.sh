#!/usr/bin/env bash
# Builds the Linux app (scripts/build_linux.sh) and wraps it in an AppImage like CI does. Output: AKAISDS-linux.AppImage
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
"$ROOT/scripts/build_linux.sh"

rm -rf AppDir; mkdir -p AppDir/usr/bin
cp -r src/AKAISDS.dist/* AppDir/usr/bin
cp assets/linux/AKAISDS.desktop AppDir/AKAISDS.desktop
cp assets/icon/icon_512x512.png AppDir/icon_512x512.png
ln -s icon_512x512.png AppDir/.DirIcon
printf '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/bin/main.bin" "$@"\n' > AppDir/AppRun
chmod +x AppDir/AppRun

[ -f appimagetool-x86_64.AppImage ] || wget -q -O appimagetool-x86_64.AppImage \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
ARCH=x86_64 ./appimagetool-x86_64.AppImage --appimage-extract-and-run AppDir AKAISDS-linux.AppImage
