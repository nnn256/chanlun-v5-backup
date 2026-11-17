[CmdletBinding()]
param([switch]$Build)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$binary = Join-Path $root 'runtime/tdx-api-revised.exe'
try {
    $probe = Invoke-RestMethod -Uri 'http://127.0.0.1:18080/api/codes' -TimeoutSec 3
    if ($probe.code -eq 0 -and $probe.data.codes.Count -gt 0) {
        @{status='already_running';address='127.0.0.1:18080';stocks=$probe.data.codes.Count} | ConvertTo-Json
        exit 0
    }
} catch { }
if ($Build -or -not (Test-Path -LiteralPath $binary)) {
    Push-Location (Join-Path $root 'vendor/tdx-api/web')
    try { go build -o $binary .; if ($LASTEXITCODE -ne 0) { throw 'Build failed' } } finally { Pop-Location }
}
$env:TZ = 'Asia/Shanghai'
$env:TDX_API_ADDR = '127.0.0.1:18080'
$env:TDX_API_LITE = '1'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdout = Join-Path $root "runtime/tdx-$stamp.stdout.log"
$stderr = Join-Path $root "runtime/tdx-$stamp.stderr.log"
$taskProcess = Start-Process -FilePath $binary -WorkingDirectory (Join-Path $root 'runtime/state') -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
@{pid=$taskProcess.Id;binary=$binary;address=$env:TDX_API_ADDR;stdout=$stdout;stderr=$stderr;timezone=$env:TZ;lite_mode=$true;started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'runtime/service.json') -Encoding utf8
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    $taskProcess.Refresh()
    if ($taskProcess.HasExited) { throw "Service exited; inspect $stderr" }
    try {
        $probe = Invoke-RestMethod -Uri 'http://127.0.0.1:18080/api/codes' -TimeoutSec 3
        if ($probe.code -eq 0 -and $probe.data.codes.Count -gt 0) {
            @{status='ready';pid=$taskProcess.Id;stocks=$probe.data.codes.Count;coverage=$probe.data.coverage} | ConvertTo-Json -Depth 8
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 1
}
throw "Service readiness timed out; process retained, inspect $stderr"
