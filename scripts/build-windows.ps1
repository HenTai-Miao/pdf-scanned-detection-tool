[CmdletBinding()]
param(
    [switch]$SkipArchive
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceDir = Join-Path $ProjectRoot "src"
$EntryPoint = Join-Path $ProjectRoot "packaging\scanspy_main.py"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
$ReleaseDir = Join-Path $ProjectRoot "release\scanspy-windows-x64"
$ReleaseExe = Join-Path $ReleaseDir "scanspy.exe"
$ReadmeFileName = "README-" + [char]0x7528 + [char]0x6237 + [char]0x4F7F + [char]0x7528 + ".txt"
$ReleaseReadme = Join-Path $ReleaseDir $ReadmeFileName
$ZipPath = Join-Path $ProjectRoot "release\scanspy-windows-x64.zip"

function Remove-ProjectPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside project: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to build scanspy.exe. Install uv first, then rerun this script."
}

Set-Location -LiteralPath $ProjectRoot
uv sync --frozen --dev
if ($LASTEXITCODE -ne 0) {
    throw "Dependency synchronization failed."
}

Remove-ProjectPath -Path $DistDir
Remove-ProjectPath -Path $BuildDir
Remove-ProjectPath -Path $ReleaseDir
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

uv run --frozen pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --python-option "X utf8" `
    --name scanspy `
    --noupx `
    --paths $SourceDir `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $BuildDir `
    --collect-all fitz `
    --collect-all pymupdf `
    $EntryPoint

$BuiltExe = Join-Path $DistDir "scanspy.exe"
if (-not (Test-Path -LiteralPath $BuiltExe)) {
    throw "PyInstaller finished but dist\scanspy.exe was not created."
}

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
Copy-Item -LiteralPath $BuiltExe -Destination $ReleaseExe -Force

$ReadmeSource = Join-Path (Join-Path $ProjectRoot "packaging") $ReadmeFileName
if (-not (Test-Path -LiteralPath $ReadmeSource)) {
    throw "Release README source was not found: $ReadmeSource"
}
$ReadmeText = [System.IO.File]::ReadAllText($ReadmeSource, [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($ReleaseReadme, $ReadmeText, [System.Text.Encoding]::UTF8)

if (-not $SkipArchive) {
    Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $ZipPath -Force
}

Write-Host "Build complete:"
Write-Host "  $ReleaseExe"
if (-not $SkipArchive) {
    Write-Host "  $ZipPath"
}
