[CmdletBinding()]
param([string]$DestinationDirectory = [Environment]::GetFolderPath('Desktop'), [string]$Name = 'Chanlun Workbench')
$ErrorActionPreference = 'Stop'
try {
    $project = $PSScriptRoot
    $launcher = Join-Path $project 'Start-Workbench.ps1'
    if (-not (Test-Path -LiteralPath $launcher)) { throw 'The project launcher is missing. Extract the complete ZIP.' }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $destination = Join-Path $DestinationDirectory ($Name + '.lnk')
    if (Test-Path -LiteralPath $destination) {
        Copy-Item -LiteralPath $destination -Destination ($destination + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    }
    $shellObject = New-Object -ComObject WScript.Shell
    $shortcut = $shellObject.CreateShortcut($destination)
    $shortcut.TargetPath = Join-Path $PSHOME 'powershell.exe'
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '" -OpenBrowser'
    $shortcut.WorkingDirectory = $project
    $shortcut.Description = 'Open the local Chanlun workbench. Keep the extracted project folder in place.'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $destination"
    Write-Host "Project: $project"
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
