<#
.SYNOPSIS
  Start Lumen on Windows. Docker Engine runs inside WSL2; this script runs
  start.sh there, which uses a usable GPU (e.g. Intel Iris Xe/Arc through WSL2)
  and otherwise falls back to the CPU.

.EXAMPLE
  .\start.ps1             # detect GPU, set up models, start the app
  .\start.ps1 --offline   # restart from existing images and models, no network
  .\start.ps1 --cpu       # skip GPU detection
  $env:LUMEN_MODEL_SIZE = "8B"; .\start.ps1   # larger, slower, better model
#>
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

# Networks that inspect HTTPS need their root CA inside the Docker build.
# Export GOC-GDC-ROOT-A (a public root certificate) when this computer has it.
$certDir = Join-Path $repo "certs"
foreach ($cert in Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*CN=GOC-GDC-ROOT*" }) {
    $name = ($cert.GetNameInfo("SimpleName", $false) -replace '[^A-Za-z0-9._-]', '_') + ".crt"
    $target = Join-Path $certDir $name
    if (-not (Test-Path $target)) {
        $pem = "-----BEGIN CERTIFICATE-----`n" +
               [Convert]::ToBase64String($cert.RawData, "InsertLineBreaks").Replace("`r`n", "`n") +
               "`n-----END CERTIFICATE-----`n"
        [IO.File]::WriteAllText($target, $pem)
        Write-Host "Trusted network root certificate exported to certs\$name"
    }
}

# Find a WSL distribution with a working Docker Engine.
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
if (-not $distro) {
    Write-Error ("No WSL distribution with a running Docker Engine was found. Install Docker " +
                 "Engine in WSL (see README), or set LUMEN_WSL_DISTRO.")
}

# Pass these settings through to WSL when they are set in PowerShell.
$env:WSLENV = (@($env:WSLENV, "LUMEN_MODEL_SIZE", "LUMEN_ACCELERATOR", "LUMEN_GPU_LAYERS",
                 "LUMEN_CONTEXT", "LUMEN_TIMEOUT_SECONDS", "LUMEN_IMAGE_PIXELS", "APP_PORT") |
               Where-Object { $_ }) -join ":"
Write-Host "Using Docker in WSL distribution '$distro'."
wsl.exe -d $distro --cd $repo -- bash ./start.sh @args
$code = $LASTEXITCODE
if ($code -eq 0) {
    # WSL shuts a distribution down shortly after its last wsl.exe command ends,
    # which would stop Docker and Lumen with it. Keep one hidden, idle process
    # running until .\stop.ps1 (or a reboot).
    $alive = Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
        Where-Object { $_.CommandLine -like "*--exec sleep infinity*" }
    if (-not $alive) {
        Start-Process wsl.exe -WindowStyle Hidden -ArgumentList "-d $distro --exec sleep infinity"
    }
    Write-Host "Stop Lumen with .\stop.ps1"
}
exit $code
