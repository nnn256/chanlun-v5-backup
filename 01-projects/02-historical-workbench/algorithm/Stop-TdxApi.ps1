[CmdletBinding()]
param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $PSScriptRoot 'runtime/service.json'
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding utf8 | ConvertFrom-Json
$process = Get-Process -Id $receipt.pid -ErrorAction SilentlyContinue
if (-not $process) { Write-Output 'Recorded service is already stopped.'; exit 0 }
$expected = [IO.Path]::GetFullPath($receipt.binary)
if ([IO.Path]::GetFullPath($process.Path) -ne $expected) { throw 'PID now belongs to another binary; no process stopped.' }
if ($Preview) { @{action='would_stop';pid=$process.Id;binary=$expected} | ConvertTo-Json -Compress; exit 0 }
Stop-Process -Id $process.Id
@{action='stopped';pid=$process.Id;binary=$expected} | ConvertTo-Json -Compress
