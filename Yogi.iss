; Inno Setup script for Yogi (ships dist\Yogi as Yogi-Setup.exe)
#define MyAppName "Yogi"
#define MyAppVersion "0.1.1-beta"
#define MyAppPublisher "EskraS"
#define MyAppExeName "Yogi.exe"

[Setup]
AppId={{B7E4D2A1-9C38-4F6B-8E15-2A9D0C4F7B31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=Yogi-Setup
SetupIconFile=logo\yogi.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Keep one install path; upgrades replace the previous copy.
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startmenu"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\Yogi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ensure the .ico is present even if the last PyInstaller build predated it.
Source: "logo\yogi.ico"; DestDir: "{app}\_internal\logo"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\logo\yogi.ico"; Tasks: startmenu
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\logo\yogi.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeleteAllData: Boolean;
  DeleteDataCheck: TNewCheckBox;

function InitializeUninstall(): Boolean;
var
  Form: TSetupForm;
  Info: TNewStaticText;
  OKButton, CancelButton: TNewButton;
begin
  DeleteAllData := False;
  Result := True;
  { A modal form would hang /SILENT and /VERYSILENT uninstalls; keep user data. }
  if UninstallSilent then
    Exit;
  Result := False;

  { Inno Setup 7: CreateCustomForm(ClientWidth, ClientHeight, KeepSizeX, KeepSizeY) }
  Form := CreateCustomForm(460, 200, False, True);
  try
    Form.Caption := 'Uninstall Yogi';

    Info := TNewStaticText.Create(Form);
    Info.Parent := Form;
    Info.Left := ScaleX(16);
    Info.Top := ScaleY(16);
    Info.Width := Form.ClientWidth - ScaleX(32);
    Info.Height := ScaleY(60);
    Info.WordWrap := True;
    Info.Caption :=
      'Remove Yogi from this PC?'#13#10#13#10 +
      'By default your settings, API keys, and chat history are kept.';

    DeleteDataCheck := TNewCheckBox.Create(Form);
    DeleteDataCheck.Parent := Form;
    DeleteDataCheck.Left := ScaleX(16);
    DeleteDataCheck.Top := ScaleY(90);
    DeleteDataCheck.Width := Form.ClientWidth - ScaleX(32);
    DeleteDataCheck.Caption :=
      'Also remove everything Yogi stored (settings, API keys, chat history, speech model cache)';
    DeleteDataCheck.Checked := False;

    OKButton := TNewButton.Create(Form);
    OKButton.Parent := Form;
    OKButton.Caption := 'Uninstall';
    OKButton.ModalResult := mrOk;
    OKButton.Default := True;
    OKButton.Width := ScaleX(100);
    OKButton.Height := ScaleY(23);
    OKButton.Left := Form.ClientWidth - ScaleX(220);
    OKButton.Top := Form.ClientHeight - ScaleY(44);

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    CancelButton.Width := ScaleX(100);
    CancelButton.Height := ScaleY(23);
    CancelButton.Left := Form.ClientWidth - ScaleX(110);
    CancelButton.Top := OKButton.Top;

    if Form.ShowModal() = mrOk then
    begin
      DeleteAllData := DeleteDataCheck.Checked;
      Result := True;
    end;
  finally
    Form.Free();
  end;
end;

procedure DeleteCredentialTarget(const Target: String);
var
  ResultCode: Integer;
begin
  Exec('cmd.exe', '/c cmdkey /delete:' + Target, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure WipeYogiUserData();
var
  ResultCode: Integer;
  HubDir: String;
begin
  { Settings (QSettings) }
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Yogi');

  { API keys (Windows Credential Manager / python-keyring targets) }
  DeleteCredentialTarget('Yogi');
  DeleteCredentialTarget('openrouter@Yogi');
  DeleteCredentialTarget('openrouter_tts@Yogi');
  DeleteCredentialTarget('xai@Yogi');
  DeleteCredentialTarget('fish_audio@Yogi');

  { Installed blocks and their Python environments (created at runtime, not tracked by Setup) }
  DelTree(ExpandConstant('{app}'), True, True, True);

  { Chat history and any other %LOCALAPPDATA%\Yogi data }
  DelTree(ExpandConstant('{localappdata}\Yogi'), True, True, True);

  { Local Whisper model used by Yogi STT }
  HubDir := ExpandConstant('{%USERPROFILE}\.cache\huggingface\hub\models--Systran--faster-whisper-small');
  if DirExists(HubDir) then
    DelTree(HubDir, True, True, True);

  { Best-effort: clear any leftover cmdkey targets that still mention Yogi }
  Exec(
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "cmdkey /list | Select-String -Pattern ''Yogi'' | ForEach-Object { if ($_ -match ''Target:\s*(.+)$'') { cmdkey /delete:$($Matches[1].Trim()) } }"',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DeleteAllData then
    WipeYogiUserData();
end;
