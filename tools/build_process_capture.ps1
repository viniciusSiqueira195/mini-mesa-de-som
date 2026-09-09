param()

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$source = Join-Path $root "placasom.cpp"
$output = Join-Path $root "Placasom.exe"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw "O Microsoft C++ Build Tools é necessário para compilar a captura de programas."
}
$installation = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw "Microsoft C++ Build Tools não encontrado." }
$environment = Join-Path $installation "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path -LiteralPath $environment)) { throw "Ambiente x64 do MSVC não encontrado." }

$object = Join-Path $env:TEMP "mini-mesa-placasom.obj"
cmd /c "`"$environment`" >nul && cl.exe /nologo /std:c++17 /EHsc /O2 /DUNICODE /D_UNICODE `"$source`" /Fo`"$object`" /Fe:`"$output`""
if ($LASTEXITCODE -ne 0) { throw "A compilação de Placasom.exe falhou." }
