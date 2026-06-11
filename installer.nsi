!include "MUI2.nsh"

Name "Translation Assistant"
OutFile "TranslationAssistant-Setup.exe"
InstallDir "$PROGRAMFILES\TranslationAssistant"
InstallDirRegKey HKCU "Software\TranslationAssistant" ""

RequestExecutionLevel admin

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "MainSection" SEC01
    SetOutPath "$INSTDIR"
    File /r "dist\TranslationAssistant\*.*"

    CreateDirectory "$SMPROGRAMS\Translation Assistant"
    CreateShortCut "$SMPROGRAMS\Translation Assistant\Translation Assistant.lnk" "$INSTDIR\TranslationAssistant.exe" "" "$INSTDIR\TranslationAssistant.exe"
    CreateShortCut "$DESKTOP\Translation Assistant.lnk" "$INSTDIR\TranslationAssistant.exe" "" "$INSTDIR\TranslationAssistant.exe"

    WriteUninstaller "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant" \
        "DisplayName" "Translation Assistant"
    WriteRegStr HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant" \
        "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant" \
        "DisplayVersion" "1.0"
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\Translation Assistant\Translation Assistant.lnk"
    RMDir "$SMPROGRAMS\Translation Assistant"
    Delete "$DESKTOP\Translation Assistant.lnk"
    DeleteRegKey HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant"
SectionEnd
