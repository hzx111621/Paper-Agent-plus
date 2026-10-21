$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$ReleaseRoot = Join-Path $ProjectRoot "release"
$ExePath = Join-Path $ReleaseRoot "Paper-Agent-Hohai.exe"
$BuildRoot = Join-Path $ProjectRoot "build\pyinstaller"

# 中文说明：任何移动或清理前先核对绝对路径，避免操作到项目外的文件。
$projectPrefix = $ProjectRoot.TrimEnd('\') + '\'
foreach ($target in @($ExePath, $BuildRoot)) {
    if (-not [System.IO.Path]::GetFullPath($target).StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "输出目录不在项目目录内，已停止打包。"
    }
}

Write-Host "[1/5] 构建前端..."
npm run front:build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败，已停止打包。" }

Write-Host "[2/5] 备份旧 EXE 并清理构建文件..."
if (Test-Path -LiteralPath $ExePath) {
    $BackupDir = Join-Path $ProjectRoot ("backups\Paper-Agent-Hohai-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Move-Item -LiteralPath $ExePath -Destination (Join-Path $BackupDir "Paper-Agent-Hohai.exe")
}
if (Test-Path -LiteralPath $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null

Write-Host "[3/5] 使用 uv 临时安装 PyInstaller 并打包..."
uv run --with pyinstaller pyinstaller `
    --noconfirm `
    --clean `
    --distpath $ReleaseRoot `
    --workpath $BuildRoot `
    (Join-Path $ProjectRoot "packaging\Paper-Agent.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败，请查看输出；旧发布版仍在 backups 中。" }

Write-Host "[4/5] 检查单文件输出..."
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "打包结束但没有找到 exe：$ExePath"
}
Write-Host "[5/5] 输出完成：$ExePath"
