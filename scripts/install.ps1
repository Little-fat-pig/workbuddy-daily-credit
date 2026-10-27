# NOTE: Windows PowerShell 5.1 needs a UTF-8 BOM to parse the non-ASCII
# (Chinese) text in this file. Without the BOM the literals are mis-decoded
# as GBK and the script fails with a parser error. Do NOT strip the BOM.
<#
  install.ps1 —— 一键安装「每日自动领取 WorkBuddy 积分」所需的全部组件（幂等，可重复运行）

  做什么：
    1. 定位 WorkBuddy 托管的 Python
    2. 确保 venv 存在
    3. 安装 windows-mcp
    4. **无 BOM** 合并写入 ~/.workbuddy/mcp.json（自动备份原文件）
    5. 跑 verify.py 自检，输出明确结论

  用法：
    powershell -ExecutionPolicy Bypass -File "<技能目录>\scripts\install.ps1"

  安装后仍需用户完成 1 个人工步骤（WorkBuddy 的安全闸门，AI 无法代做）：
    连接器面板 **右上角「自定义连接器」** -> 找到 windows-mcp -> 点「信任」-> 彻底重启 WorkBuddy
#>

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$base      = Join-Path $env:USERPROFILE '.workbuddy'
$venvDir   = Join-Path $base 'binaries\python\envs\default'
$versionsDir = Join-Path $base 'binaries\python\versions'
$mcpJson   = Join-Path $base 'mcp.json'
$venvExe   = Join-Path $venvDir 'Scripts\windows-mcp.exe'

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }

# ---------- 1) 定位托管 Python ----------
Step '1/5' '定位 WorkBuddy 托管 Python'
$managedPy = $null
if (Test-Path $venvDir) {
    $c = Join-Path $venvDir 'Scripts\python.exe'
    if (Test-Path $c) { $managedPy = $c }
}
if (-not $managedPy -and (Test-Path $versionsDir)) {
    foreach ($ver in (Get-ChildItem -Path $versionsDir -Directory | Sort-Object Name -Descending)) {
        $cand = Join-Path $ver.FullName 'python.exe'
        if (Test-Path $cand) { $managedPy = $cand; break }
    }
}
if (-not $managedPy) {
    Write-Host '[X] 未找到 WorkBuddy 托管 Python。请确认 WorkBuddy 已安装并至少运行过一次。' -ForegroundColor Red
    Write-Host "    期望路径: $versionsDir"
    exit 1
}
Write-Host "    托管 Python: $managedPy"

# ---------- 2) 确保 venv ----------
Step '2/5' '确保 venv 存在'
$venvPy  = Join-Path $venvDir 'Scripts\python.exe'
$venvPip = Join-Path $venvDir 'Scripts\pip.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "    创建 venv: $venvDir"
    & $managedPy -m venv $venvDir | Out-Host
} else {
    Write-Host '    venv 已存在，跳过。'
}

# ---------- 3) 安装 windows-mcp ----------
Step '3/5' '安装 windows-mcp'
if (Test-Path $venvExe) {
    Write-Host '    windows-mcp 已安装，跳过安装（幂等）。'
} else {
    & $venvPip install --upgrade windows-mcp | Out-Host
}
if (-not (Test-Path $venvExe)) {
    Write-Host "[X] 安装后仍未找到 $venvExe" -ForegroundColor Red
    exit 1
}
Write-Host "    可执行: $venvExe"

# ---------- 4) 无 BOM 写 mcp.json ----------
Step '4/5' '合并写入 MCP 配置（无 BOM）'
$writer = Join-Path $scriptDir 'write_mcp_config.py'
& $venvPy $writer --command $venvExe --arg serve --mcp-json $mcpJson
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] 写入 MCP 配置失败。' -ForegroundColor Red
    exit 1
}

# ---------- 5) 自检 ----------
Step '5/5' '环境自检'
$verify = Join-Path $scriptDir 'verify.py'
& $venvPy $verify
$vc = $LASTEXITCODE

Write-Host ''
Write-Host '==================== 安装完成 ====================' -ForegroundColor Green
if ($vc -eq 0) {
    Write-Host '下一步（需你点一下，WorkBuddy 安全闸门）：' -ForegroundColor Yellow
    Write-Host '  1. 打开 WorkBuddy「连接器」管理页，点 **右上角「自定义连接器」**'
    Write-Host '  2. 找到 windows-mcp，点「信任」启用'
    Write-Host '  3. **彻底退出 WorkBuddy（托盘图标右键→退出）再重开**（让 mcp.json 重新加载）'
    Write-Host '  4. 回来告诉 WorkBuddy：「已信任」，它会立刻建每日 09:30 的领取任务并跑一次验证。'
} else {
    Write-Host '自检有未通过项，请按上方 [FAIL] 提示修复后重跑 install.ps1。' -ForegroundColor Yellow
}
exit $vc
