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
uv sync --dev

Remove-ProjectPath -Path $DistDir
Remove-ProjectPath -Path $BuildDir
Remove-ProjectPath -Path $ReleaseDir
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

uv run pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
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

$ReadmeTextBase64 = "c2NhbnNweSBXaW5kb3dzIHg2NCDkvb/nlKjor7TmmI4KCui/kOihjOaWueW8j++8mgogIEM6XHBhdGhcdG9cc2NhbnNweS5leGUgIkM6XHBhdGhcdG9cZmlsZS5wZGYiCiAgQzpccGF0aFx0b1xzY2Fuc3B5LmV4ZSAiaHR0cHM6Ly9leGFtcGxlLmNvbS9maWxlLnBkZiIKICBDOlxwYXRoXHRvXHNjYW5zcHkuZXhlICJDOlxwYXRoXHRvXGEucGRmIiAiQzpccGF0aFx0b1xiLnBkZiIKCuivtOaYju+8mgogIC0g5LuF5pSv5oyB5pys5ZywIC5wZGYg5paH5Lu25ZKM5LulIC5wZGYg57uT5bC+55qEIEhUVFAvSFRUUFMgUERGIOebtOmTvuOAggogIC0gSFRUUC9IVFRQUyDmlofku7bkvJrkuIvovb3liLAgJVRNUCUgLyAlVEVNUCUg5LiL55qEIHNjYW5zcHktKiDkuLTml7bnm67lvZXvvIzmo4DmtYvlrozmiJDlkI7oh6rliqjliKDpmaTjgIIKICAtIOi+k+WHuuS4uuS4gOihjCBKU09O77yM5a2X5q6157uT5p6E5LiO6aG555uuIFJFQURNRSDkuK3nmoQgUjxMaXN0PFNjYW5EZXRlY3RSZXN1bHQ+PiDkv53mjIHkuIDoh7TjgIIKICAtIOajgOa1i+mAu+i+keS4peagvOS9v+eUqCBvY3ItZGV0ZWN0aW9uLmRldGVjdF9vY3IoKSDlhazlvIAgQVBJ44CCCgrluLjop4Hov5Tlm57vvJoKICAtIFNUQU5EQVJE77ya5LiN6ZyA6KaBIE9DUgogIC0gU0NBTk5FRO+8muWFqOmDqOmhtemcgOimgSBPQ1IKICAtIE1JWEVEX1NDQU5ORUTvvJrpg6jliIbpobXpnIDopoEgT0NSCg=="
$ReadmeText = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ReadmeTextBase64))
[System.IO.File]::WriteAllText($ReleaseReadme, $ReadmeText, [System.Text.Encoding]::UTF8)

if (-not $SkipArchive) {
    Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $ZipPath -Force
}

Write-Host "Build complete:"
Write-Host "  $ReleaseExe"
if (-not $SkipArchive) {
    Write-Host "  $ZipPath"
}
