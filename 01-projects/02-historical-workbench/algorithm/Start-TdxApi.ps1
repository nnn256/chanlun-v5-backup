[CmdletBinding()]
param([switch]$Build, [int]$StartupTimeoutSeconds = 120)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$address = '127.0.0.1:18080'
$runtime = Join-Path $taskRoot 'runtime'
$binary = Join-Path $runtime 'tdx-api-revised.exe'
$vendorWeb = Join-Path $taskRoot 'vendor/tdx-api/web'
if (-not (Test-Path -LiteralPath (Join-Path $vendorWeb 'go.mod'))) {
    throw 'Repository missing. Clone https://github.com/oficcejo/tdx-api into vendor/tdx-api and apply artifacts/tdx-integration/service.diff.patch.'
}
try {
    $response = Invoke-RestMethod -Uri "http://$address/api/codes" -TimeoutSec 5
    if ($response.code -eq 0 -and $response.data.Codes.Count -gt 0) {
        [ordered]@{status='already_running'; address=$address; stocks=$response.data.Codes.Count; coverage=$response.data.coverage} | ConvertTo-Json -Depth 8
        exit 0
    }
} catch { }
if ($Build -or -not (Test-Path -LiteralPath $binary)) {
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Push-Location $vendorWeb
    try {
        & go build -o $binary .
        if ($LASTEXITCODE -ne 0) { throw "Go build failed with exit $LASTEXITCODE" }
    } finally { Pop-Location }
}
$state = Join-Path $runtime 'state'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdout = Join-Path $runtime "tdx-api-$stamp.stdout.log"
$stderr = Join-Path $runtime "tdx-api-$stamp.stderr.log"
$oldTZ = $env:TZ
$oldAddress = $env:TDX_API_ADDR
$oldLite = $env:TDX_API_LITE
try {
    $env:TZ = 'Asia/Shanghai'
    $env:TDX_API_ADDR = $address
    $env:TDX_API_LITE = '1'
    $process = Start-Process -FilePath $binary -WorkingDirectory $state -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
} finally {
    $env:TZ = $oldTZ
    $env:TDX_API_ADDR = $oldAddress
    $env:TDX_API_LITE = $oldLite
}
$receipt = [ordered]@{pid=$process.Id; address=$address; binary=$binary; stdout=$stdout; stderr=$stderr; timezone='Asia/Shanghai'; lite_mode=$true; started_at=(Get-Date).ToString('o')}
$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'service.json') -Encoding utf8
$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    $process.Refresh()
    if ($process.HasExited) { throw "Service exited; inspect $stderr" }
    try {
        $codes = Invoke-RestMethod -Uri "http://$address/api/codes" -TimeoutSec 3
        if ($codes.code -eq 0 -and $codes.data.Codes.Count -gt 0) {
            [ordered]@{status='ready'; pid=$process.Id; address=$address; stocks=$codes.data.Codes.Count; coverage=$codes.data.coverage; stderr=$stderr} | ConvertTo-Json -Depth 8
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 1
}
throw "Service readiness timeout; process is retained, see $stderr"
