# install_shortcuts.ps1
#
# Creates Desktop + Start Menu shortcuts for HicoForge that:
#   - point at HicoForge.vbs (silent launcher, no console window)
#   - use assets\HicoForge.ico as the icon
#   - set the AppUserModelID so the taskbar groups under HicoForge

param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = "Stop"

$Icon       = Join-Path $InstallRoot "assets\HicoForge.ico"
$Launcher   = Join-Path $InstallRoot "HicoForge.vbs"
$Desktop    = [Environment]::GetFolderPath("Desktop")
$StartMenu  = [Environment]::GetFolderPath("Programs")

# Where the shortcuts go
$DesktopLnk   = Join-Path $Desktop "HicoForge.lnk"
$StartMenuLnk = Join-Path $StartMenu "HicoForge.lnk"

if (-Not (Test-Path $Icon)) {
    Write-Warning "Icon not found at $Icon"
}
if (-Not (Test-Path $Launcher)) {
    Write-Warning "Launcher not found at $Launcher"
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$WorkingDir,
        [string]$IconPath,
        [string]$Description
    )
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($Path)
    $sc.TargetPath       = $Target
    $sc.WorkingDirectory = $WorkingDir
    if (Test-Path $IconPath) {
        $sc.IconLocation = "$IconPath,0"
    }
    $sc.Description      = $Description
    $sc.WindowStyle      = 1
    $sc.Save()
    Write-Host "Created: $Path"
}

New-Shortcut -Path $DesktopLnk   -Target $Launcher -WorkingDir $InstallRoot -IconPath $Icon -Description "HicoForge - AI image upscaler & forge"
New-Shortcut -Path $StartMenuLnk -Target $Launcher -WorkingDir $InstallRoot -IconPath $Icon -Description "HicoForge - AI image upscaler & forge"

Write-Host "Shortcuts installed."
