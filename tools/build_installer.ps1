param(
    [switch]$SkipTests,
    [switch]$SkipDependencyDownload
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Ambiente virtual não encontrado. Crie .venv e instale o extra de build."
}

Push-Location $projectRoot
try {
    if (-not $SkipTests) {
        & $python -m unittest discover -s tests -v
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
}
finally {
    Pop-Location
}

Write-Host "Instalador gerado em installer-output."
