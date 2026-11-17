[CmdletBinding()]
param(
  [string]$RunDirectory,
  [ValidateRange(1,16)][int]$Workers = 8,
  [switch]$Resume,
  [switch]$Smoke,
  [ValidateSet('tdx','ths')][string]$Source = 'tdx'
)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot

$candidates=New-Object System.Collections.Generic.List[object]
$venv=Join-Path $root '.venv/Scripts/python.exe'
if(Test-Path -LiteralPath $venv){$candidates.Add(@{path=$venv;args=@()})}
foreach($name in @('python','python3','py')){
  $command=Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if($command){$candidates.Add(@{path=$command.Source;args=$(if($name -eq 'py'){@('-3')}else{@()})})}
}
$python=$null
foreach($candidate in $candidates){
  try{
    $probeArgs=@($candidate.args)+@('-c','import sys,json; print(json.dumps(dict(exe=sys.executable,version=list(sys.version_info[:3]))))')
    $probe=& $candidate.path @probeArgs 2>$null
    if($LASTEXITCODE -ne 0){continue}
    $identity=($probe | Select-Object -Last 1) | ConvertFrom-Json
    if($identity.version[0] -eq 3 -and $identity.version[1] -ge 11 -and (Test-Path -LiteralPath $identity.exe)){
      $python=$identity.exe
      break
    }
  }catch{}
}
if(-not $python){throw 'Python 3.11+ is required; install Python and retry. WindowsApps execution aliases are skipped.'}
$runnerArgs=@($root+'/run_v5_market.py','--workers',"$Workers",'--source',$Source)
if($RunDirectory){$runnerArgs+=@('--run-dir',$RunDirectory)}
if($Resume){$runnerArgs+='--resume'}
if($Smoke){$runnerArgs+='--smoke'}
Write-Host "Starting acquisition + V5 L8 recursive analysis with $python"
& $python @runnerArgs
exit $LASTEXITCODE
