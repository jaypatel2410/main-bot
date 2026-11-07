@echo off
REM ==========================================================================
REM  Builds the Windows installer: installer\Kestrel_Setup_3.12.0.exe
REM  1) builds dist\Kestrel.exe first if it is not there (build_bot_exe.bat)
REM  2) finds Inno Setup 6 (installs it with winget if it is missing)
REM  3) compiles Kestrel.iss
REM  Put this file in the bot folder (next to build_bot_exe.bat and Kestrel.iss) and double-click it.
REM  Your .env (keys) is never put into the installer.
REM ==========================================================================
setlocal
cd /d "%~dp0"

if not exist Kestrel.iss (
  echo Kestrel.iss was not found in %cd%
  goto :err
)

if not exist dist\Kestrel.exe (
  echo [1/3] dist\Kestrel.exe not found - building it first ^(build_bot_exe.bat^) ...
  call build_bot_exe.bat
  if not exist dist\Kestrel.exe goto :err
) else (
  echo [1/3] Using dist\Kestrel.exe ^(delete the dist folder to rebuild it^)
)

echo [2/3] Looking for Inno Setup 6 ...
call :findiscc
if not defined ISCC (
  echo Inno Setup 6 not found - installing it with winget ^(free, from jrsoftware.org^) ...
  winget install -e --id JRSoftware.InnoSetup --scope user --silent --accept-package-agreements --accept-source-agreements
  call :findiscc
)
if not defined ISCC (
  echo.
  echo Could not find or install Inno Setup 6. Install it from https://jrsoftware.org/isdl.php
  echo ^(the default options^), then run this file again.
  goto :err
)
echo        %ISCC%

echo [3/3] Building the installer ...
"%ISCC%" /Q Kestrel.iss || goto :err

echo.
echo ==========================================================================
echo  Done:  %cd%\installer\Kestrel_Setup_3.12.0.exe
echo  Copy that one file to the other PC and run it ^(no admin rights needed^).
echo  On the other PC: IB Gateway, and its own .env with your keys
echo  ^(Start menu ^> Kestrel - keys and settings ^(.env^)^).
echo  Run the bot on ONE PC at a time per TradeZero account.
echo ==========================================================================
pause
exit /b 0

:findiscc
set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
  if exist %%P set "ISCC=%%~P"
)
exit /b 0

:err
echo.
echo Installer build failed - see the messages above.
pause
exit /b 1
