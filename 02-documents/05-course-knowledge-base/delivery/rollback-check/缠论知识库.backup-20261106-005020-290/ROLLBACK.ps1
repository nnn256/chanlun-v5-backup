[CmdletBinding()]
param([switch]$Preview)

$ErrorActionPreference = 'Stop'
$libraryPath = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$libraryParent = [IO.Directory]::GetParent($libraryPath).FullName
$expectedName = '缠论知识库'
if ([IO.Path]::GetFileName($libraryPath) -ne $expectedName) {
    throw "Unexpected library directory: $libraryPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $libraryPath 'sources/coverage.json'))) {
    throw 'Knowledge-library marker is missing; no files moved.'
}
$backupPath = $libraryPath + '.backup-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff')
if ([IO.Path]::GetFullPath([IO.Path]::GetDirectoryName($backupPath)) -ne [IO.Path]::GetFullPath($libraryParent)) {
    throw 'Backup destination must stay in the same parent directory.'
}
if (Test-Path -LiteralPath $backupPath) { throw "Destination exists: $backupPath" }
if ($Preview) {
    [ordered]@{Action='Preview'; Source=$libraryPath; Destination=$backupPath} | ConvertTo-Json -Compress
    exit 0
}
Move-Item -LiteralPath $libraryPath -Destination $backupPath
[ordered]@{Action='Moved'; Source=$libraryPath; Destination=$backupPath; Deleted=$false} | ConvertTo-Json -Compress
