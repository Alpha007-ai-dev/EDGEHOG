@echo off
rem EDGEHOG gyujto telepitese: Windows utemezett feladat, 2 percenkent, ablak nelkul.
rem Leallitas: uninstall_collector.bat   Naplo: output\collector.log
cd /d C:\dev\edgehog
set "PYW="
for /f "delims=" %%i in ('python -c "import sys,os;p=os.path.join(os.path.dirname(sys.executable),'pythonw.exe');print(p if os.path.exists(p) else '')"') do set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo Nem talalom a pythonw.exe-t. Telepitve van a Python?
  pause
  exit /b 1
)
echo Python: %PYW%
echo.
echo 1. Probafutas...
set PYTHONIOENCODING=utf-8
python collect.py
echo.
echo 2. Utemezett feladat letrehozasa (2 percenkent)...
schtasks /create /tn "EDGEHOG gyujto" /sc minute /mo 2 /tr "\"%PYW%\" \"C:\dev\edgehog\collect.py\"" /f
if errorlevel 1 (
  echo Nem sikerult letrehozni az utemezett feladatot.
  pause
  exit /b 1
)
schtasks /query /tn "EDGEHOG gyujto" /fo list | findstr /i "TaskName Next Status"
echo.
echo KESZ. A gyujto 2 percenkent fut, amig a gep be van kapcsolva es be vagy jelentkezve.
pause
