<#
  setup_windows_mcp.ps1
  为 WorkBuddy 安装 windows-mcp 桌面自动化 MCP 服务（幂等，可重复运行）。

  用法（在 WorkBuddy 的 Bash/PowerShell 工具里执行）：
    powershell -ExecutionPolicy Bypass -File "<技能目录>\scripts\setup_windows_mcp.ps1"

  说明：
    - 自动定位 WorkBuddy 托管的 Python（<USERPROFILE>\.workbuddy\binaries\python\versions\*\python.exe）
    - 在其 venv（<USERPROFILE>\.workbuddy\binaries\python\envs\default）中安装 windows-mcp
    - 写入/合并 <USERPROFILE>\.workbuddy\mcp.json
  安装后仍需用户在 WorkBuddy「连接器」面板点击「信任」启用，并重启会话。
#>

$ErrorActionPreference = 'Stop'

$base      = Join-Path $env:USERPROFILE '.workbuddy'
$venvDir   = Join-Path $base 'binaries\python\envs\default'
$versionsDir = Join-Path $base 'binaries\python\versions'
$mcpJson   = Join-Path $base 'mcp.json'

# 1) 定位托管的 Python
$managedPy = $null
if (Test-Path $versionsDir) {
    foreach ($ver in (Get-ChildItem -Path $versionsDir -Directory)) {
        $cand = Join-Path $ver.FullName 'python.exe'
        if (Test-Path $cand) { $managedPy = $cand; break }
    }
}
if (-not $managedPy) {
    Write-Error "未找到 WorkBuddy 托管 Python，请确认 WorkBuddy 已安装并至少运行过一次（路径: $versionsDir）。"
    exit 1
}
Write-Host "[1/4] 托管 Python: $managedPy"

# 2) 确保 venv 存在
$venvPy  = Join-Path $venvDir 'Scripts\python.exe'
$venvPip = Join-Path $venvDir 'Scripts\pip.exe'
$venvExe = Join-Path $venvDir 'Scripts\windows-mcp.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "[2/4] 创建 venv: $venvDir"
    & $managedPy -m venv $venvDir | Out-Host
} else {
    Write-Host "[2/4] venv 已存在，跳过创建。"
}

# 3) 安装 windows-mcp
if (Test-Path $venvExe) {
    Write-Host "[3/4] windows-mcp 已安装，跳过安装。"
} else {
    Write-Host "[3/4] 安装 windows-mcp ..."
    & $venvPip install --upgrade windows-mcp | Out-Host
}

# 4) 写入/合并 mcp.json
$entry = [ordered]@{
    command = $venvExe
    args    = @('serve')
    env     = [ordered]@{ ANONYMIZED_TELEMETRY = 'false' }
}

$obj = $null
if (Test-Path $mcpJson) {
    try { $obj = Get-Content -Path $mcpJson -Raw | ConvertFrom-Json } catch { $obj = $null }
}
if (-not $obj) { $obj = New-Object PSObject }
if (-not $obj.mcpServers) { $obj | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject) }
$obj.mcpServers | Add-Member -Force -NotePropertyName 'windows-mcp' -NotePropertyValue $entry

$obj | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 -Path $mcpJson
Write-Host "[4/4] 已写入 MCP 配置: $mcpJson"

Write-Host ""
Write-Host "==== 完成 ===="
Write-Host "下一步：在 WorkBuddy 左侧「连接器」面板找到 windows-mcp，点击「信任」启用，"
Write-Host "然后重启/新建一个会话，让 mcp__windows-mcp__* 工具生效，再让 WorkBuddy 帮你建每日自动领取任务。"
