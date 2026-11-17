[CmdletBinding()]
param(
    [string]$RunDirectory,
    [ValidateRange(1,16)][int]$Workers = 4,
    [switch]$Resume,
    [ValidateSet('tdx','ths')][string]$Source = 'tdx'
)
$ErrorActionPreference = 'Stop'
if (-not $RunDirectory) {
    $RunDirectory = Join-Path $PSScriptRoot ('runs/tdx-all-a-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
& (Join-Path $PSScriptRoot 'Start-TdxApi.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Data service failed to start' }
$scanArgs = @((Join-Path $PSScriptRoot 'market_scan.py'),'--run-dir',$RunDirectory,'--cache-dir',(Join-Path $PSScriptRoot 'market_data'),'--workers',"$Workers",'--source',$Source)
if ($Resume) { $scanArgs += '--resume' }
& python @scanArgs
exit $LASTEXITCODE
