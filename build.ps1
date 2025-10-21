param([string]$Python = "python")
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..")
$VenvDir   = Join-Path $RepoRoot "build\.venv"
$PyExe     = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "🔧 RepoRoot = $RepoRoot"
if (!(Test-Path $VenvDir)) { & $Python -m venv $VenvDir }
. (Join-Path $VenvDir "Scripts\Activate.ps1")

python -m pip install --upgrade pip setuptools wheel
pip install -q pyinstaller PySide6 mss "opencv-python<4.11"

$CoreDir     = Join-Path $RepoRoot "source\core"
$PlayerMain  = Join-Path $RepoRoot "source\player\main.py"
$EditorMain  = Join-Path $RepoRoot "source\editor\main.py"
$DistDir     = Join-Path $RepoRoot "dist"
$WorkDir     = Join-Path $RepoRoot "build\pyi-work"
$SpecDir     = Join-Path $RepoRoot "build\pyi-spec"
$BinDir      = Join-Path $RepoRoot "bin"
New-Item -ItemType Directory -Force -Path $DistDir, $WorkDir, $SpecDir, $BinDir | Out-Null

Write-Host "⚙️ Building Player (collect-all cv2, mss)..."
& $PyExe -m PyInstaller --noconfirm --clean --onefile --windowed `
  --distpath "$DistDir" --workpath "$WorkDir" --specpath "$SpecDir" `
  --name "Player" `
  --add-data "$CoreDir;core" `
  --collect-all cv2 `
  --collect-all mss `
  "$PlayerMain"

Write-Host "⚙️ Building Editor (collect-all cv2, mss)..."
& $PyExe -m PyInstaller --noconfirm --clean --onefile --windowed `
  --distpath "$DistDir" --workpath "$WorkDir" --specpath "$SpecDir" `
  --name "Editor" `
  --add-data "$CoreDir;core" `
  --collect-all cv2 `
  --collect-all mss `
  "$EditorMain"

if (Test-Path (Join-Path $DistDir "Player.exe")) {
  Copy-Item (Join-Path $DistDir "Player.exe") (Join-Path $BinDir "Player.exe") -Force
  Write-Host "✅ Player.exe -> bin"
} else { Write-Host "⚠️ Player.exe not found. Check PyInstaller logs." }

if (Test-Path (Join-Path $DistDir "Editor.exe")) {
  Copy-Item (Join-Path $DistDir "Editor.exe") (Join-Path $BinDir "Editor.exe") -Force
  Write-Host "✅ Editor.exe -> bin"
} else { Write-Host "⚠️ Editor.exe not found. Check PyInstaller logs." }

Write-Host "🏁 Done."
