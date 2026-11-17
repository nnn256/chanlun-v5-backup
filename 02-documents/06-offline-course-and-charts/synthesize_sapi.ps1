param([string]$LessonsPath,[string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$raw = Get-Content -LiteralPath $LessonsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($raw -is [Array]) { $lessons = $raw }
elseif ($raw.PSObject.Properties.Name -contains 'lessons') { $lessons = $raw.lessons }
else { throw 'Expected a lessons array.' }
$voice = New-Object -ComObject SAPI.SpVoice
$chosen = $voice.GetVoices() | Where-Object { $_.GetDescription() -like '*Huihui*' } | Select-Object -First 1
if (-not $chosen) { throw 'Installed Chinese SAPI voice not found.' }
$voice.Voice = $chosen
$voice.Rate = 1
$index = 0
foreach ($lesson in $lessons) {
  $index++
  $id = '{0:d2}' -f $index
  $target = Join-Path $OutputDirectory ($id + '.wav')
  if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -gt 1000) { continue }
  $stream = New-Object -ComObject SAPI.SpFileStream
  $stream.Format.Type = 22
  $stream.Open($target,3,$false)
  $voice.AudioOutputStream = $stream
  $words = [string]$lesson.narration
  if ($words.Length -lt 10) { throw ('Narration is missing at ' + $id) }
  [void]$voice.Speak($words)
  [void]$voice.WaitUntilDone(60000)
  $stream.Close()
  Write-Output ('speech=' + $id)
}
