# Install / uninstall the per-user autostart entry for the daily-credit scheduler.
#
# Why this instead of Task Scheduler:
#   When the logged-on account is NOT a member of Administrators,
#   Register-ScheduledTask / schtasks.exe / COM Schedule.Service are all denied.
#   A per-user Run entry + resident scheduler gives the same effect without admin.
#
# NOTE: messages are ASCII on purpose, so this file does NOT need a UTF-8 BOM
#       (Windows PowerShell 5.1 would otherwise decode it as GBK).

param(
    [switch]$Uninstall,
    [string]$PythonwPath
)

$ErrorActionPreference = 'Stop'
$scriptsDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$scheduler  = Join-Path $scriptsDir 'scheduler.py'
$runKey     = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$valueName  = 'WorkBuddyDailyCredit'

function Get-Existing {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*scheduler.py*' }
}

# ---------- uninstall ----------
if ($Uninstall) {
    Remove-ItemProperty -Path $runKey -Name $valueName -ErrorAction SilentlyContinue
    Get-Existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Output 'UNINSTALLED: autostart entry removed, scheduler stopped.'
    exit 0
}

# ---------- locate pythonw ----------
if (-not $PythonwPath) {
    $candidates = @(
        (Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe'),
        (Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\default\Scripts\python.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $PythonwPath = $c; break }
    }
    if (-not $PythonwPath) {
        $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if ($cmd) { $PythonwPath = $cmd.Source }
    }
    if (-not $PythonwPath -or -not (Test-Path $PythonwPath)) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($cmd) { $PythonwPath = $cmd.Source }
    }
}
if (-not $PythonwPath -or -not (Test-Path $PythonwPath)) {
    Write-Output 'ERROR: pythonw.exe / python.exe not found. Pass -PythonwPath <full path>.'
    exit 2
}
if (-not (Test-Path $scheduler)) {
    Write-Output "ERROR: scheduler.py not found at $scheduler"
    exit 2
}

# python.exe would flash a console window; prefer pythonw when available next to it
$pyw = $PythonwPath
$sibling = Join-Path (Split-Path -Parent $PythonwPath) 'pythonw.exe'
if ((Test-Path $sibling) -and ($PythonwPath -notlike '*pythonw.exe')) { $pyw = $sibling }

# ---------- register + start ----------
$cmd = '"{0}" "{1}"' -f $pyw, $scheduler
New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name $valueName -Value $cmd
Write-Output "AUTOSTART_SET: $cmd"

Get-Existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
Start-Process -FilePath $pyw -ArgumentList "`"$scheduler`"" -WorkingDirectory $scriptsDir -WindowStyle Hidden
Start-Sleep -Seconds 3

$alive = Get-Existing
if ($alive) {
    Write-Output ("RUNNING: pid=" + ($alive.ProcessId -join ','))
} else {
    Write-Output 'NOT_RUNNING (check runner.log next to scheduler.py)'
}
Write-Output '--- autostart entry ---'
(Get-ItemProperty -Path $runKey -Name $valueName).$valueName
