#!/usr/bin/env bash
# Compila l'AppImage per Linux in locale, con gli stessi passaggi di
# .github/workflows/build.yml (job linux-appimage). Uso, dalla cartella del progetto:
#
#     bash tools/build_appimage.sh
#
# Serve il venv del progetto (python3 -m venv venv && venv/bin/pip install -r requirements.txt).
# La prima volta scarica appimagetool da GitHub in tools/appimagetool.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=venv/bin/python
[ -x "$PY" ] || { echo "Manca il venv: python3 -m venv venv && venv/bin/pip install -r requirements.txt"; exit 1; }
VERSION=$("$PY" -c "from comicoptimizer.config import APP_VERSION; print(APP_VERSION)")
OUT="ComicOptimizer-v${VERSION}-x86_64.AppImage"
echo "== ComicOptimizer ${VERSION}: compilazione AppImage"

echo "== PyInstaller"
"$PY" -m pip install -q pyinstaller
rm -rf build dist AppDir
"$PY" -m PyInstaller main.py \
    --noconfirm --clean --windowed \
    --name ComicOptimizer \
    --add-data "comicoptimizer.png:." \
    --add-data "comicoptimizer_banner.png:." \
    --add-data "comicoptimizer_drop.png:." \
    --collect-submodules send2trash \
    --exclude-module tkinter

echo "== AppDir"
APP=AppDir
mkdir -p "$APP/usr/bin"
cp -r dist/ComicOptimizer/. "$APP/usr/bin/"
cp comicoptimizer.png "$APP/comicoptimizer.png"
cp comicoptimizer.png "$APP/.DirIcon"
cat > "$APP/comicoptimizer.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=ComicOptimizer
Comment=Gestione, riparazione e ottimizzazione di librerie di fumetti digitali
Exec=ComicOptimizer
Icon=comicoptimizer
Categories=Graphics;Utility;
Terminal=false
EOF
ln -s usr/bin/ComicOptimizer "$APP/AppRun"

TOOL=tools/appimagetool
if [ ! -x "$TOOL" ]; then
    echo "== Scarico appimagetool"
    URL=https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    if command -v wget > /dev/null; then wget -q -O "$TOOL" "$URL"; else curl -fsSL -o "$TOOL" "$URL"; fi
    chmod +x "$TOOL"
fi

echo "== AppImage"
# --appimage-extract-and-run: funziona anche senza FUSE
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APP" "$OUT"
chmod +x "$OUT"
rm -rf build AppDir
echo "== Fatto: $OUT"
