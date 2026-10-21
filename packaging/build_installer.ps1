$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$ScriptPath = Join-Path $ProjectRoot "packaging\Paper-Agent-Hohai.iss"
$ExePath = Join-Path $ProjectRoot "release\Paper-Agent-Hohai.exe"
$Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $Iscc) {
    $KnownPaths = @(
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($KnownPath in $KnownPaths) {
        if (Test-Path -LiteralPath $KnownPath) {
            $Iscc = Get-Item -LiteralPath $KnownPath
            break
        }
    }
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "没有找到应用 EXE，请先运行 packaging\build_exe.ps1。"
}
if (-not $Iscc) {
    throw "没有找到 Inno Setup。请安装 Inno Setup 6 后重新运行此脚本。"
}

$CompilerPath = if ($Iscc -is [System.Management.Automation.CommandInfo]) { $Iscc.Source } else { $Iscc.FullName }
& $CompilerPath $ScriptPath
if ($LASTEXITCODE -ne 0) { throw "安装包构建失败。" }
