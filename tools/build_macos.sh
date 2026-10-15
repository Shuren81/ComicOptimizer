#!/usr/bin/env bash
# Compila ComicOptimizer.app per macOS e la impacchetta in un .dmg (da lanciare su un Mac).
# Uso, dal Terminale nella cartella del progetto:
#
#     bash tools/build_macos.sh
#
# Servono (una volta sola):
#   - Python 3.12 da python.org (installer per macOS)
#   - 7-Zip per macOS da https://www.7-zip.org/download.html (voce "macOS", 7zXXXX-mac.tar.xz),
#     estratto in tools/7zip-mac/ (devono esserci 7zz e License.txt): legge anche i RAR
# L'app funziona sui Mac con lo stesso processore di questo (Apple Silicon o Intel).
set -euo pipefail
cd "$(dirname "$0")/.."

SEVEN=tools/7zip-mac
if [ ! -f "$SEVEN/7zz" ]; then
    echo "Manca 7-Zip: scarica l'archivio per macOS da https://www.7-zip.org/download.html"
    echo "ed estrailo in $SEVEN/ (devono esserci 7zz e License.txt)."
    exit 1
fi

PYTHON=$(command -v python3.12 || command -v python3)
if [ ! -x venv-mac/bin/python ]; then
    echo "== Creo l'ambiente venv-mac con $PYTHON"
    "$PYTHON" -m venv venv-mac
fi
PY=venv-mac/bin/python
echo "== Dipendenze Python"
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r requirements.txt pyinstaller
VERSION=$("$PY" -c "from comicoptimizer.config import APP_VERSION; print(APP_VERSION)")
ARCH=$(uname -m)
OUT="ComicOptimizer-v${VERSION}-macos-${ARCH}.dmg"
echo "== ComicOptimizer ${VERSION}: compilazione per macOS (${ARCH})"

echo "== 7-Zip da includere (nell'app si chiama bin/7z)"
mkdir -p bin
cp "$SEVEN/7zz" bin/7z
cp "$SEVEN/License.txt" bin/7-Zip-License.txt
chmod +x bin/7z
xattr -c bin/7z 2> /dev/null || true   # toglie il "scaricato da Internet" di macOS

echo "== PyInstaller"
rm -rf build dist
"$PY" -m PyInstaller main.py \
    --noconfirm --clean --windowed \
    --name ComicOptimizer \
    --icon comicoptimizer.png \
    --osx-bundle-identifier com.shuren.comicoptimizer \
    --add-data "comicoptimizer.png:." \
    --add-data "comicoptimizer_banner.png:." \
    --add-data "comicoptimizer_drop.png:." \
    --add-binary "bin/7z:bin" \
    --add-data "bin/7-Zip-License.txt:bin" \
    --collect-submodules send2trash \
    --exclude-module tkinter

echo "== Controlli"
APP=dist/ComicOptimizer.app
[ -d "$APP" ] || { echo "ComicOptimizer.app mancante"; exit 1; }
[ -n "$(find "$APP" -path '*/bin/7z' -type f | head -1)" ] || { echo "7z mancante nell'app"; exit 1; }

echo "== DMG"
STAGE=dist/dmg
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # nel DMG: trascina l'app su Applicazioni
rm -f "$OUT"
hdiutil create -volname "ComicOptimizer" -srcfolder "$STAGE" -ov -format UDZO "$OUT" > /dev/null
rm -rf build "$STAGE"
echo "== Fatto: $OUT (l'app è anche in $APP)"
