# Install the ascii-media binary on Windows.
# Usage: irm https://raw.githubusercontent.com/anargia-pixels/ascii-media-convertor/master/install.ps1 | iex
# Set $env:ASCII_MEDIA_VERSION (for example v1.0.0) to install a specific release.
# Set $env:ASCII_MEDIA_INSTALL_DIR to change the install directory.

# Run in a script block so the settings below do not leak into the caller.
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue' # the progress UI makes downloads slow

    $Repo = 'anargia-pixels/ascii-media-convertor'
    $Version = if ($env:ASCII_MEDIA_VERSION) { $env:ASCII_MEDIA_VERSION } else { 'latest' }
    $InstallDir = if ($env:ASCII_MEDIA_INSTALL_DIR) {
        $env:ASCII_MEDIA_INSTALL_DIR
    } else {
        Join-Path $env:LOCALAPPDATA 'Programs\ascii-media'
    }
    $Asset = 'ascii-media-windows-x86_64.exe' # ARM64 Windows runs it through emulation
    $Base = if ($Version -eq 'latest') {
        "https://github.com/$Repo/releases/latest/download"
    } else {
        "https://github.com/$Repo/releases/download/$Version"
    }

    # Download and verify
    $Tmp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid())
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    try {
        Write-Host "Downloading $Asset ($Version)"
        Invoke-WebRequest "$Base/$Asset" -OutFile "$Tmp\$Asset" -UseBasicParsing
        Invoke-WebRequest "$Base/SHA256SUMS" -OutFile "$Tmp\SHA256SUMS" -UseBasicParsing

        $Line = Select-String -Path "$Tmp\SHA256SUMS" -Pattern " $([regex]::Escape($Asset))$"
        if (-not $Line) { throw "No checksum for $Asset in SHA256SUMS." }
        $Expected = $Line.Line.Split(' ')[0]
        $Actual = (Get-FileHash "$Tmp\$Asset" -Algorithm SHA256).Hash
        if ($Actual -ne $Expected) { throw "Checksum mismatch for $Asset." }

        # Install
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        Move-Item -Force "$Tmp\$Asset" (Join-Path $InstallDir 'ascii-media.exe')
    } finally {
        Remove-Item -Recurse -Force $Tmp
    }
    Write-Host "Installed ascii-media to $InstallDir\ascii-media.exe"

    # Add the install directory to the user PATH once.
    $UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (($UserPath -split ';') -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable('Path', "$UserPath;$InstallDir", 'User')
        $env:Path += ";$InstallDir"
        Write-Host "Added $InstallDir to your user PATH. Open a new terminal to use it."
    }
    Write-Host 'Run: ascii-media --help'
}
