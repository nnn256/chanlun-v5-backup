[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port=8895,[switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$project=Split-Path $root -Parent
$data='../workbench-data-8895'
$dataPath=Join-Path $project 'workbench-data-8895'
New-Item -ItemType Directory -Force -Path $dataPath | Out-Null
Push-Location -LiteralPath $root
try {
    & (Join-Path $root 'Start-Workbench.ps1') -Port $Port -DataDir $data -OpenBrowser:$OpenBrowser
    $exitCode=$LASTEXITCODE
} finally { Pop-Location }
exit $exitCode
