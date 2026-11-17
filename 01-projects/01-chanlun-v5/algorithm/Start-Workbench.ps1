[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 8895, [string]$DataDir, [switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$project = Split-Path $root -Parent
$V5Universe = '../runs/full-market-20261114-tdx-partial/universe.json'
$DataDir = if ($DataDir) { $DataDir } else { '../workbench-data-8895' }
$env:CHANLUN_WORKBENCH_ROOT = '.'
$env:CHANLUN_WORKBENCH_DATA_DIR = $DataDir
$env:CHANLUN_APP_DATA_DIR = $env:CHANLUN_WORKBENCH_DATA_DIR
$env:CHANLUN_V5_PROFILE = 'course_feature_sequence_recursive_v2'
$env:CHANLUN_V5_UNIVERSE = $V5Universe
$script:ObservedHealth = $null
$script:ExpectedDatabase = if ([IO.Path]::IsPathRooted($DataDir)) {
    [IO.Path]::GetFullPath((Join-Path $DataDir 'workbench.sqlite3'))
} else {
    [IO.Path]::GetFullPath((Join-Path (Join-Path $root $DataDir) 'workbench.sqlite3'))
}
$url = "http://127.0.0.1:$Port"
$runtime = Join-Path $root 'runtime/workbench'
$startupLog = Join-Path $runtime 'startup.log'

function Write-Startup([string]$Message) {
    Write-Host $Message
    Add-Content -LiteralPath $startupLog -Value ((Get-Date).ToString('o') + ' ' + $Message) -Encoding utf8
}

function Test-Ready {
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        $script:ObservedHealth = $health
        $database = [IO.Path]::GetFullPath([string]$health.database)
        return $health.service -eq 'chanlun-workbench-v1' -and
            $health.release -eq 'V5' -and
            $health.version -eq '5.0.0' -and
            $health.workbench_profile -eq 'course_feature_sequence_recursive_v2' -and
            $database -ieq $script:ExpectedDatabase
    } catch { $script:ObservedHealth = $null; return $false }
}

function Complete-Startup {
    Write-Startup "READY $url/?symbol=sz300949"
    if ($OpenBrowser -and $env:CHANLUN_NO_BROWSER -ne '1') {
        try { Start-Process -FilePath "$url/?symbol=sz300949" | Out-Null }
        catch { Write-Startup "Browser did not open automatically. Open $url manually." }
    }
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'workbench/server.py'))) {
        throw 'Project files are missing. Extract the complete ZIP; do not move this script alone.'
    }
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Write-Startup "Project: $root"
    if (Test-Ready) { Complete-Startup; exit 0 }
    if ($script:ObservedHealth) {
        throw "Port $Port is occupied by $($script:ObservedHealth.release) $($script:ObservedHealth.version), profile=$($script:ObservedHealth.workbench_profile), database=$($script:ObservedHealth.database). Expected V5 profile course_feature_sequence_recursive_v2 at $($script:ExpectedDatabase)."
    }

    $candidates = New-Object System.Collections.Generic.List[object]
    $venv = Join-Path $root '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $venv) { $candidates.Add(@{path=$venv;args=@()}) }
    foreach ($name in @('python','python3','py')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidates.Add(@{path=$command.Source;args=$(if ($name -eq 'py') { @('-3') } else { @() })}) }
    }
    $python = $null
    foreach ($candidate in $candidates) {
        try {
            $probeArgs = @($candidate.args) + @('-c','import sys,json; print(json.dumps({"exe":sys.executable,"version":list(sys.version_info[:3])}))')
            # Windows PowerShell re-quotes native argument strings, so avoid
            # embedded double quotes in the Python expression.
            $probeArgs[-1] = "import sys,json; print(json.dumps(dict(exe=sys.executable,version=list(sys.version_info[:3]))))"
            $probe = & $candidate.path @probeArgs 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $identity = ($probe | Select-Object -Last 1) | ConvertFrom-Json
            if ($identity.version[0] -eq 3 -and $identity.version[1] -ge 11 -and (Test-Path -LiteralPath $identity.exe)) {
                $python = $identity.exe
                Write-Startup ("Python: " + $python + ' / ' + ($identity.version -join '.'))
                break
            }
        } catch { }
    }
    if (-not $python) { throw 'Python 3.11+ was not found. Install Python with Add to PATH, then run again.' }
    $env:PYTHONIOENCODING = 'utf-8'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $runtime "$stamp.stdout.log"
    $stderr = Join-Path $runtime "$stamp.stderr.log"
    Push-Location -LiteralPath $root
    try {
        & $python -c 'import sys; import workbench.server; print(sys.version)' > (Join-Path $runtime 'preflight.stdout.log') 2> (Join-Path $runtime 'preflight.stderr.log')
        if ($LASTEXITCODE -ne 0) { throw 'Python could not import workbench.server.' }
    } catch {
        if (Test-Path -LiteralPath (Join-Path $runtime 'preflight.stderr.log')) {
            Get-Content -LiteralPath (Join-Path $runtime 'preflight.stderr.log') -Tail 20 | ForEach-Object { Write-Startup $_ }
        }
        throw
    } finally { Pop-Location }
    $process = Start-Process -FilePath $python -ArgumentList @('-m','workbench.server','--port',"$Port") -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    @{pid=$process.Id;url=$url;python=$python;root=$root;stdout=$stdout;stderr=$stderr;started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'service.json') -Encoding utf8
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-Ready) { Complete-Startup; exit 0 }
        if ($script:ObservedHealth) {
            throw "Port $Port returned a different workbench identity after startup: release=$($script:ObservedHealth.release), profile=$($script:ObservedHealth.workbench_profile), database=$($script:ObservedHealth.database)."
        }
        $process.Refresh()
        if ($process.HasExited) {
            Get-Content -LiteralPath $stderr -Tail 25 | ForEach-Object { Write-Startup $_ }
            throw "Workbench exited with code $($process.ExitCode). Error log: $stderr"
        }
        Start-Sleep -Milliseconds 500
    }
    Get-Content -LiteralPath $stderr -Tail 25 | ForEach-Object { Write-Startup $_ }
    throw "Startup timed out. Process $($process.Id) retained. Error log: $stderr"
} catch {
    Write-Host ("START FAILED: " + $_.Exception.Message) -ForegroundColor Red
    if (Test-Path -LiteralPath $runtime) {
        Add-Content -LiteralPath $startupLog -Value $_.Exception.Message -Encoding utf8
        Write-Host "Diagnostic log: $startupLog"
    }
    exit 1
}
