# Compila l'exe per Windows in locale, con gli stessi passaggi di
# .github/workflows/build.yml (job windows). Uso, da PowerShell nella cartella del progetto:
#
#     powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
#
# Servono (una volta sola): Python 3.12 da python.org con "Add python.exe to PATH"
# e 7-Zip da 7-zip.org installato in C:\Program Files\7-Zip.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# i programmi esterni non fermano lo script da soli: si controlla il codice di uscita
function Run {
    & $args[0] $args[1..($args.Count - 1)]
    if ($LASTEXITCODE -ne 0) { throw "Comando fallito ($LASTEXITCODE): $($args -join ' ')" }
}

$sevenZip = "C:\Program Files\7-Zip"
if (-not (Test-Path "$sevenZip\7z.exe")) { throw "7-Zip non trovato in ${sevenZip}: installalo da https://www.7-zip.org" }

if (-not (Test-Path "venv-win\Scripts\python.exe")) {
    Write-Host "== Creo l'ambiente venv-win"
    Run python -m venv venv-win
}
$py = ".\venv-win\Scripts\python.exe"   # .\ : PowerShell non cerca nella cartella corrente
Write-Host "== Dipendenze Python"
Run $py -m pip install -q --upgrade pip
Run $py -m pip install -q -r requirements.txt pyinstaller
$version = (& $py -c "from comicoptimizer.config import APP_VERSION; print(APP_VERSION)").Trim()
Write-Host "== ComicOptimizer $version : compilazione exe"

Write-Host "== Icona .ico dal PNG"
Run $py -c "from PIL import Image; Image.open('comicoptimizer.png').save('comicoptimizer.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host "== 7-Zip da includere"
New-Item -ItemType Directory -Force bin | Out-Null
Copy-Item "$sevenZip\7z.exe", "$sevenZip\7z.dll" bin\
Copy-Item "$sevenZip\License.txt" bin\7-Zip-License.txt

Write-Host "== PyInstaller"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
Run $py -m PyInstaller main.py `
    --noconfirm --clean --windowed `
    --name ComicOptimizer `
    --icon comicoptimizer.ico `
    --add-data "comicoptimizer.png;." `
    --add-data "comicoptimizer_banner.png;." `
    --add-data "comicoptimizer_drop.png;." `
    --add-binary "bin\7z.exe;bin" `
    --add-binary "bin\7z.dll;bin" `
    --add-data "bin\7-Zip-License.txt;bin" `
    --collect-submodules send2trash `
    --exclude-module tkinter

Write-Host "== Controlli"
if (-not (Test-Path "dist\ComicOptimizer\ComicOptimizer.exe")) { throw "exe mancante" }
if (-not (Test-Path "dist\ComicOptimizer\_internal\bin\7z.exe")) { throw "7z.exe mancante" }

Write-Host "== Pacchetto zip"
Copy-Item README.md, CHANGELOG.md, LEGGIMI-WINDOWS.txt dist\ComicOptimizer\
$zip = "ComicOptimizer-v$version-windows.zip"
Compress-Archive -Path dist\ComicOptimizer -DestinationPath $zip -Force
Write-Host "== Fatto: $zip (l'exe e' anche in dist\ComicOptimizer\ComicOptimizer.exe)"
