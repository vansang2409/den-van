# Chạy tại thư mục dự án, ưu tiên Python đã cài sẵn trong Codex Desktop.
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not $env:FFMPEG -and -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $package = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe'
    $installed = Get-ChildItem -Path "$package\*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($installed) {
        $env:FFMPEG = $installed.FullName
        if (-not $env:FFPROBE) { $env:FFPROBE = Join-Path $installed.DirectoryName 'ffprobe.exe' }
    }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    if (Test-Path -LiteralPath $bundledPython) {
        & $bundledPython -B -m studio @args
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -B -m studio @args
    } else {
        & python -B -m studio @args
    }
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
