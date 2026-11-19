<#
.SYNOPSIS
  Stop Lumen on Windows: stops the containers (models are kept) and lets WSL
  shut down again.
#>
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

$distro = $env:LUMEN_WSL_DISTRO
if (-not $distro) {
    $names = (wsl.exe --list --quiet) -replace "`0", "" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }
    # A distribution without Docker writes errors; with "Stop" Windows PowerShell
    # would treat them as fatal, so probe with errors ignored.
    $ErrorActionPreference = "Continue"
    foreach ($name in $names) {
        wsl.exe -d $name --exec docker info 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $distro = $name; break }
    }
    $ErrorActionPreference = "Stop"
}
if ($distro) {
    wsl.exe -d $distro --cd $repo -- docker compose down
}
Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
    Where-Object { $_.CommandLine -like "*--exec sleep infinity*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Lumen stopped. Start it again with .\start.ps1 --offline"
