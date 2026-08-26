param(
    [Parameter(Mandatory = $true)][string]$DriverDirectory,
    [Parameter(Mandatory = $true)][string]$AudioModuleDirectory,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [Parameter(Mandatory = $true)][string]$InstalledMarkerPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-InstallerLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Get-DefaultAudioState {
    $roles = [ordered]@{}
    foreach ($role in @(
        "Playback",
        "PlaybackCommunication",
        "Recording",
        "RecordingCommunication"
    )) {
        try {
            $parameters = @{ $role = $true }
            $roles[$role] = (Get-AudioDevice @parameters).ID
        }
        catch {
            $roles[$role] = $null
            Write-InstallerLog "Não foi possível ler o padrão ${role}: $_"
        }
    }
    return $roles
}

function Restore-DefaultAudioState {
    param($State)
    $operations = @(
        @{ Name = "Playback"; Communication = $false },
        @{ Name = "Recording"; Communication = $false },
        @{ Name = "PlaybackCommunication"; Communication = $true },
        @{ Name = "RecordingCommunication"; Communication = $true }
    )
    foreach ($operation in $operations) {
        $deviceId = $State[$operation.Name]
        if (-not $deviceId) {
            continue
        }
        try {
            if ($operation.Communication) {
                Set-AudioDevice -ID $deviceId -CommunicationOnly
            }
            else {
                Set-AudioDevice -ID $deviceId -DefaultOnly
            }
            Write-InstallerLog "Padrão $($operation.Name) restaurado."
        }
        catch {
            Write-InstallerLog "Falha ao restaurar $($operation.Name): $_"
        }
    }
}

function Test-VBCableInstalled {
    $audioEndpoints = Get-AudioDevice -List | Where-Object {
        $_.Name -match "CABLE (Input|Output).*VB-Audio Virtual Cable"
    }
    if ($audioEndpoints) {
        return $true
    }

    $endpointRoots = @(
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture",
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
    )
    foreach ($root in $endpointRoots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        foreach ($endpoint in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
            $propertiesPath = Join-Path $endpoint.PSPath "Properties"
            $properties = Get-ItemProperty -LiteralPath $propertiesPath `
                -ErrorAction SilentlyContinue
            $propertyText = $properties.PSObject.Properties.Value -join " "
            if ($propertyText -match "(?i)(VB-Audio Virtual Cable|VBCABLE)") {
                return $true
            }
        }
    }

    try {
        $pnpDevices = Get-PnpDevice -PresentOnly:$false -ErrorAction Stop |
            Where-Object {
                $_.FriendlyName -match "(CABLE (Input|Output)|VB-Audio Virtual Cable)" -and
                $_.FriendlyName -notmatch "CABLE-[A-D]"
            }
        return [bool]$pnpDevices
    }
    catch {
        Write-InstallerLog "Não foi possível consultar dispositivos PnP: $_"
        return $false
    }
}

New-Item -ItemType File -Force -Path $LogPath | Out-Null
Import-Module (Join-Path $AudioModuleDirectory "AudioDeviceCmdlets.psd1") -Force

if (Test-VBCableInstalled) {
    Write-InstallerLog "VB-CABLE já está instalado; etapa ignorada."
    exit 0
}

$defaults = Get-DefaultAudioState
$setupName = if ([Environment]::Is64BitOperatingSystem) {
    "VBCABLE_Setup_x64.exe"
}
else {
    "VBCABLE_Setup.exe"
}
$setupPath = Join-Path $DriverDirectory $setupName
if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Instalador oficial do VB-CABLE não encontrado: $setupPath"
}

try {
    Write-InstallerLog "Solicitando instalação elevada do VB-CABLE."
    $process = Start-Process -FilePath $setupPath -ArgumentList "-i", "-h" `
        -WorkingDirectory $DriverDirectory -Verb RunAs -Wait -PassThru
    Write-InstallerLog "Instalador do VB-CABLE terminou com código $($process.ExitCode)."
    if ($process.ExitCode -notin @(0, 3010, 1641)) {
        throw "O instalador do VB-CABLE retornou $($process.ExitCode)."
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-VBCableInstalled) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Restore-DefaultAudioState -State $defaults
}

Write-InstallerLog "Instalação opcional do VB-CABLE concluída."
New-Item -ItemType File -Force -Path $InstalledMarkerPath | Out-Null
