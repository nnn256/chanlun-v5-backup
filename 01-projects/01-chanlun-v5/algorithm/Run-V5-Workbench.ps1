[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port=8895,[switch]$OpenBrowser)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'Start-V5-Workbench-8895.ps1') -Port $Port -OpenBrowser:$OpenBrowser
exit $LASTEXITCODE
