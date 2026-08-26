param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\.installer-dependencies")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$vbCableUrl = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
$vbCableHash = "B950E39F01AF1D04EA623C8F6D8EB9B6EA5C477C637295FABF20631C85116BFB"
$audioModuleUrl = "https://www.powershellgallery.com/api/v2/package/AudioDeviceCmdlets/3.1.0.2"
$audioModuleHash = "F4911B867C01FD6B391C51024131007598A81782A7B9D3AE77D6E266D5780DAC"

function Get-VerifiedArchive {
    param(
        [string]$Url,
        [string]$ExpectedHash,
        [string]$Path
    )

    Invoke-WebRequest -Uri $Url -OutFile $Path
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
    if ($actualHash -ne $ExpectedHash) {
        throw "Checksum inválido para $Url. Esperado $ExpectedHash; recebido $actualHash."
    }
}

$resolvedDestination = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $resolvedDestination | Out-Null

$vbCableZip = Join-Path $resolvedDestination "VBCABLE_Driver_Pack45.zip"
$vbCableDirectory = Join-Path $resolvedDestination "vbcable"
Get-VerifiedArchive -Url $vbCableUrl -ExpectedHash $vbCableHash -Path $vbCableZip
if (Test-Path -LiteralPath $vbCableDirectory) {
    Remove-Item -LiteralPath $vbCableDirectory -Recurse -Force
}
Expand-Archive -LiteralPath $vbCableZip -DestinationPath $vbCableDirectory

$audioModulePackage = Join-Path $resolvedDestination "AudioDeviceCmdlets.3.1.0.2.nupkg"
$audioModuleDirectory = Join-Path $resolvedDestination "AudioDeviceCmdlets"
Get-VerifiedArchive -Url $audioModuleUrl -ExpectedHash $audioModuleHash -Path $audioModulePackage
if (Test-Path -LiteralPath $audioModuleDirectory) {
    Remove-Item -LiteralPath $audioModuleDirectory -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $audioModuleDirectory | Out-Null
tar -xf $audioModulePackage -C $audioModuleDirectory `
    AudioDeviceCmdlets.psd1 AudioDeviceCmdlets.dll
if ($LASTEXITCODE -ne 0) {
    throw "Não foi possível extrair AudioDeviceCmdlets."
}

Write-Host "Dependências do instalador verificadas em $resolvedDestination"
