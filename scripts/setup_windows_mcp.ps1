# NOTE: UTF-8 with BOM is required so Windows PowerShell 5.1 parses the
# Chinese text in this file correctly.
<#
  setup_windows_mcp.ps1 —— 兼容入口，实际转交给 install.ps1

  保留这个文件名是为了兼容旧版教程/脚本调用。请直接用 install.ps1。
#>

$ErrorActionPreference = 'Stop'
$target = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'install.ps1'
if (-not (Test-Path $target)) {
    Write-Host "[X] 找不到 install.ps1：$target" -ForegroundColor Red
    exit 1
}
Write-Host '[i] 转交给 install.ps1 执行 ...' -ForegroundColor Cyan
& $target
exit $LASTEXITCODE
