Unicode True
Name "User Radar"
OutFile "dist\UserRadar-Windows-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\UserRadar"
RequestExecutionLevel user
Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles
Section
 SetOutPath "$INSTDIR"
 File /r "dist\UserRadar\*"
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 CreateDirectory "$SMPROGRAMS\User Radar"
 CreateShortcut "$SMPROGRAMS\User Radar\User Radar.lnk" "$INSTDIR\UserRadar.exe"
 CreateShortcut "$DESKTOP\User Radar.lnk" "$INSTDIR\UserRadar.exe"
SectionEnd
Section "Uninstall"
 Delete "$DESKTOP\User Radar.lnk"
 Delete "$SMPROGRAMS\User Radar\User Radar.lnk"
 RMDir "$SMPROGRAMS\User Radar"
 Delete "$INSTDIR\UserRadar.exe"
 RMDir /r "$INSTDIR\_internal"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 ; User configuration and customer data are outside INSTDIR and are retained.
SectionEnd
