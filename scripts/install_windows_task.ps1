[CmdletBinding()]
param(
    [ValidatePattern('^[0-9]+(min|h|d)$')]
    [string]$Interval = "3h",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$TaskName = "Nihongo Sensei Publisher"
$RepoDir = Split-Path -Parent $PSScriptRoot
$Publisher = Join-Path $PSScriptRoot "publish_update.ps1"
$ConfigDir = Join-Path $env:APPDATA "nihongo-sensei"
$ConfigFile = Join-Path $ConfigDir "config.env"

if ($Interval -notmatch '^([0-9]+)(min|h|d)$') {
    throw "Invalid interval '$Interval'. Examples: 30min, 3h, 1d."
}
$Amount = [int]$Matches[1]
$Unit = $Matches[2]
$Span = switch ($Unit) {
    "min" { [TimeSpan]::FromMinutes($Amount) }
    "h"   { [TimeSpan]::FromHours($Amount) }
    "d"   { [TimeSpan]::FromDays($Amount) }
}
if ($Span -lt [TimeSpan]::FromMinutes(1) -or $Span -gt [TimeSpan]::FromDays(31)) {
    throw "Windows Task Scheduler intervals must be between 1 minute and 31 days."
}

New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
if (-not (Test-Path $ConfigFile)) {
    Copy-Item (Join-Path $RepoDir "config.env.example") $ConfigFile
    Write-Host "Created $ConfigFile; review it before the first scheduled run."
}

$PowerShellExe = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path $PowerShellExe)) {
    $PowerShellExe = (Get-Process -Id $PID).Path
}
$ActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Publisher`""
$Action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument $ActionArgs `
    -WorkingDirectory $RepoDir
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval $Span `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew
$UserId = if ($env:USERDOMAIN) {
    "$env:USERDOMAIN\$env:USERNAME"
} else {
    $env:USERNAME
}
$Principal = New-ScheduledTaskPrincipal `
    -UserId $UserId `
    -LogonType Interactive `
    -RunLevel Limited

$Task = New-ScheduledTask `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Sync Anki, export reviewed Japanese tutor data, and publish it to GitHub."
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

Write-Host "Installed '$TaskName' with interval $Interval."
Write-Host "It runs only in this user's logged-in desktop session so Anki can open safely."
if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started the task."
} else {
    Write-Host "Run it now with: Start-ScheduledTask -TaskName '$TaskName'"
}
