#define AppName "Mini Mesa de Som"
#define AppVersion "0.1.0"
#define AppPublisher "Projeto Mini Mesa de Som"
#define AppURL "https://github.com/viniciusSiqueira195/mini-mesa-de-som"
#define AppExeName "MiniMesaDeSom.exe"

[Setup]
AppId={{D5463387-E281-4AF8-92E9-A504632810B1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\Mini Mesa de Som
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\installer-output
OutputBaseFilename=MiniMesaDeSom-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no
RestartIfNeededByRun=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "vbcable"; Description: "Instalar o VB-CABLE oficial (recomendado)"; GroupDescription: "Driver de áudio virtual:"; Flags: checkedonce

[Files]
Source: "..\dist\MiniMesaDeSom\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "VB-CABLE-NOTICE.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "AudioDeviceCmdlets-NOTICE.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "install_vbcable.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: vbcable
Source: "..\.installer-dependencies\vbcable\*"; DestDir: "{tmp}\vbcable"; Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall; Tasks: vbcable
Source: "..\.installer-dependencies\AudioDeviceCmdlets\AudioDeviceCmdlets.psd1"; DestDir: "{tmp}\AudioDeviceCmdlets"; Flags: ignoreversion deleteafterinstall; Tasks: vbcable
Source: "..\.installer-dependencies\AudioDeviceCmdlets\AudioDeviceCmdlets.dll"; DestDir: "{tmp}\AudioDeviceCmdlets"; Flags: ignoreversion deleteafterinstall; Tasks: vbcable

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  VBCableInstalledNow: Boolean;

procedure InstallOptionalVBCable;
var
  PowerShellPath: String;
  ScriptPath: String;
  Parameters: String;
  ResultCode: Integer;
begin
  if not WizardIsTaskSelected('vbcable') then
    Exit;

  PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  ScriptPath := ExpandConstant('{tmp}\install_vbcable.ps1');
  Parameters := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass ' +
    '-File "' + ScriptPath + '" ' +
    '-DriverDirectory "' + ExpandConstant('{tmp}\vbcable') + '" ' +
    '-AudioModuleDirectory "' + ExpandConstant('{tmp}\AudioDeviceCmdlets') + '" ' +
    '-LogPath "' + ExpandConstant('{app}\install-vbcable.log') + '" ' +
    '-InstalledMarkerPath "' + ExpandConstant('{tmp}\vbcable-installed.marker') + '"';

  WizardForm.StatusLabel.Caption := 'Instalando o VB-CABLE e preservando os dispositivos de áudio padrão...';
  if not Exec(PowerShellPath, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('A Mini Mesa de Som foi instalada, mas não foi possível iniciar a instalação do VB-CABLE.', mbError, MB_OK);
    Exit;
  end;

  if ResultCode <> 0 then
  begin
    MsgBox('A Mini Mesa de Som foi instalada, mas o VB-CABLE não pôde ser instalado. Seus dispositivos de áudio anteriores foram preservados. Consulte install-vbcable.log na pasta do programa.', mbError, MB_OK);
    Exit;
  end;

  VBCableInstalledNow := FileExists(ExpandConstant('{tmp}\vbcable-installed.marker'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallOptionalVBCable;
end;

function NeedRestart(): Boolean;
begin
  Result := VBCableInstalledNow;
end;
