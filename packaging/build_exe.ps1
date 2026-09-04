$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$ReleaseRoot = Join-Path $ProjectRoot "release"
$ReleaseDir = Join-Path $ReleaseRoot "Paper-Agent"
$BuildRoot = Join-Path $ProjectRoot "build\pyinstaller"

# 中文说明：只允许清理项目目录下的 release，避免路径配置错误时误删其它目录。
$projectPrefix = $ProjectRoot.TrimEnd('\') + '\'
if (-not $ReleaseRoot.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "release 输出目录不在项目目录内，已停止打包。"
}

Write-Host "[1/5] 构建前端..."
npm run front:build

Write-Host "[2/5] 清理旧的 exe 输出..."
if (Test-Path -LiteralPath $ReleaseRoot) {
    Remove-Item -LiteralPath $ReleaseRoot -Recurse -Force
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

Write-Host "[4/5] 复制运行所需的外部资源..."
$RuntimeDirs = @("config", "front\dist", "assets")
foreach ($relativePath in $RuntimeDirs) {
    $sourcePath = Join-Path $ProjectRoot $relativePath
    $targetPath = Join-Path $ReleaseDir $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "缺少打包所需目录：$sourcePath"
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse -Force
}

# 中文说明：data 和 logs 是可写目录。复制当前项目里的内容，保留已经注册的账户、会话和历史缓存；
# 如果目录不存在则创建空目录，exe 启动后会继续在这里写入新数据。
foreach ($relativePath in @("data", "logs")) {
    $sourcePath = Join-Path $ProjectRoot $relativePath
    $targetPath = Join-Path $ReleaseDir $relativePath
    if (Test-Path -LiteralPath $sourcePath) {
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse -Force
    } else {
        New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
    }
}

$readmeSource = Join-Path $ProjectRoot "packaging\运行说明.txt"
Copy-Item -LiteralPath $readmeSource -Destination (Join-Path $ReleaseDir "运行说明.txt") -Force

Write-Host "[5/5] 检查输出文件..."
$ExePath = Join-Path $ReleaseDir "Paper-Agent.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "打包结束但没有找到 exe：$ExePath"
}
if (-not (Test-Path -LiteralPath (Join-Path $ReleaseDir "front\dist\index.html"))) {
    throw "打包输出缺少前端首页。"
}
if (-not (Test-Path -LiteralPath (Join-Path $ReleaseDir "config\model.json"))) {
    throw "打包输出缺少模型配置文件。"
}

Write-Host "打包完成：$ExePath"
