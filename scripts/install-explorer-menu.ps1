param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$jarvisRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $jarvisRoot '.venv\Scripts\pythonw.exe'

if (-not $Uninstall -and -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "JARVIS virtual environment was not found: $pythonw"
}

$targets = @(
    @{ Key = 'HKCU:\Software\Classes\Directory\shell\JARVIS'; Argument = '%1' },
    @{ Key = 'HKCU:\Software\Classes\Directory\Background\shell\JARVIS'; Argument = '%V' }
)

foreach ($target in $targets) {
    if ($Uninstall) {
        if (Test-Path -LiteralPath $target.Key) {
            Remove-Item -LiteralPath $target.Key -Recurse -Force
        }
        continue
    }

    New-Item -Path $target.Key -Force | Out-Null
    Set-Item -LiteralPath $target.Key -Value 'Open JARVIS here'
    Set-ItemProperty -LiteralPath $target.Key -Name 'Icon' -Value $pythonw
    $commandKey = Join-Path $target.Key 'command'
    New-Item -Path $commandKey -Force | Out-Null
    $command = ('"{0}" -m jarvis_agent.gui --workspace "{1}"' -f $pythonw, $target.Argument)
    Set-Item -LiteralPath $commandKey -Value $command
}

if ($Uninstall) {
    Write-Host 'Removed the JARVIS Explorer context menu for the current user.'
} else {
    Write-Host 'Installed "Open JARVIS here" for folders and folder backgrounds.'
    Write-Host 'Use -Uninstall to remove it.'
}

