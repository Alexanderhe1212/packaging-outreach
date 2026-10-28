Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
Name "User Radar"
OutFile "UserRadar-Setup-1.4.0-win-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\UserRadarCustomer"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "1.4.0.0"
VIAddVersionKey "ProductName" "User Radar"
VIAddVersionKey "FileDescription" "User Radar customer setup"
VIAddVersionKey "FileVersion" "1.4.0"
VIAddVersionKey "LegalCopyright" "User Radar"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\runtime\python.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS '-X utf8 $\"$INSTDIR\app\launcher.py$\"'
!define MUI_FINISHPAGE_RUN_TEXT "打开 User Radar（账号保持暂停）"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\app\使用说明书.html"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "阅读使用说明书"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "payload/app/LICENSE"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

!macro CheckRunning
  System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\UserRadarCustomerRunning") p .r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK|MB_ICONSTOP "请先暂停发送并退出 User Radar，再安装或卸载。 / Close User Radar first."
    Abort
  ${EndIf}
!macroend

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "此安装包需要 64 位 Windows 10/11。"
    Abort
  ${EndIf}
  !insertmacro CheckRunning
  IfFileExists "$INSTDIR\app\*" 0 safe
  IfFileExists "$INSTDIR\user-radar-install.marker" safe
  MessageBox MB_OK|MB_ICONSTOP "目标目录已有其他文件，请勿覆盖。"
  Abort
  safe:
FunctionEnd

Section "User Radar" Main
  !insertmacro CheckRunning
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "payload/*"
  FileOpen $0 "$INSTDIR\user-radar-install.marker" w
  FileWrite $0 "UserRadarCustomer 1.4.0"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\User Radar"
  CreateShortcut "$DESKTOP\User Radar.lnk" "$INSTDIR\runtime\python.exe" '-X utf8 $\"$INSTDIR\app\launcher.py$\"' "$INSTDIR\runtime\python.exe" 0
  CreateShortcut "$SMPROGRAMS\User Radar\User Radar.lnk" "$INSTDIR\runtime\python.exe" '-X utf8 $\"$INSTDIR\app\launcher.py$\"'
  CreateShortcut "$SMPROGRAMS\User Radar\使用说明书.lnk" "$INSTDIR\app\使用说明书.html"
  CreateShortcut "$SMPROGRAMS\User Radar\卸载.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer" "DisplayName" "User Radar"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer" "DisplayVersion" "1.4.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer" "NoRepair" 1
SectionEnd

Function un.onInit
  !insertmacro CheckRunning
  IfFileExists "$INSTDIR\user-radar-install.marker" safe
  Abort
  safe:
FunctionEnd
Section "Uninstall"
  !insertmacro CheckRunning
  SetShellVarContext current
  ; Only program directories are removed. Customer data is a separate sibling.
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  Delete "$INSTDIR\user-radar-install.marker"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\User Radar.lnk"
  Delete "$SMPROGRAMS\User Radar\User Radar.lnk"
  Delete "$SMPROGRAMS\User Radar\使用说明书.lnk"
  Delete "$SMPROGRAMS\User Radar\卸载.lnk"
  RMDir "$SMPROGRAMS\User Radar"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\UserRadarCustomer"
SectionEnd
