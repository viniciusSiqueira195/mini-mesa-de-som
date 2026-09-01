param(
    [switch]$SkipTests,
    [switch]$SkipDependencyDownload
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$installerScript = Join-Path $projectRoot "installer\MiniMesaDeSom.iss"
$versionMatch = [regex]::Match(
    (Get-Content -LiteralPath $installerScript -Raw),
    '#define AppVersion "([^"]+)"'
)
if (-not $versionMatch.Success) {
    throw "Não foi possível ler a versão do instalador."
}
$appVersion = $versionMatch.Groups[1].Value

if (-not (Test-Path -LiteralPath $python)) {
    throw "Ambiente virtual não encontrado. Crie .venv e instale o extra de build."
}

Push-Location $projectRoot
try {
    if (-not $SkipTests) {
        & $python -m pytest
        if ($LASTEXITCODE -ne 0) {
            throw "A suíte de testes falhou."
        }
    }

    & $python -m PyInstaller --clean --noconfirm .\MiniMesaDeSom.spec
    if ($LASTEXITCODE -ne 0) {
        throw "O PyInstaller não conseguiu gerar o aplicativo."
    }

    if (-not $SkipDependencyDownload) {
        & .\installer\prepare_dependencies.ps1
    }

    $compilerCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $compiler = $compilerCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if (-not $compiler) {
        throw "Inno Setup 6 não encontrado. Instale JRSoftware.InnoSetup com o winget."
    }

    & $compiler .\installer\MiniMesaDeSom.iss
    if ($LASTEXITCODE -ne 0) {
        throw "O Inno Setup não conseguiu gerar o instalador."
    }

    $installerPath = Join-Path $projectRoot "installer-output\MiniMesaDeSom-Setup-$appVersion.exe"
    $checksumPath = "$installerPath.sha256"
    $checksum = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$checksum *$(Split-Path -Leaf $installerPath)" |
        Set-Content -LiteralPath $checksumPath -Encoding ascii
}
finally {
    Pop-Location
}

Write-Host "Instalador e assinatura SHA-256 gerados em installer-output."
