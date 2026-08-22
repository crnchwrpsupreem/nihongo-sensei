[CmdletBinding()]
param(
    [switch]$NoSync,
    [switch]$NoPush,
    [string]$ConfigFile
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Publisher = Join-Path $PSScriptRoot "publish_update.py"
$Arguments = @()
if ($NoSync) { $Arguments += "--no-sync" }
if ($NoPush) { $Arguments += "--no-push" }
if ($ConfigFile) { $Arguments += @("--config-file", $ConfigFile) }

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $Publisher @Arguments
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Publisher @Arguments
} else {
    throw "Python 3 was not found. Install it and ensure 'py' or 'python' is available."
}
exit $LASTEXITCODE
